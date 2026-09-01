"""Canonical SQLite repository and protected cutover boundary for Mentat Projects.

Projects are imported from the packaged/recovery JSON document exactly once.
After the receipt is present, callers read and mutate this repository only; the
JSON file is deliberately never a live fallback.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
from typing import Any, Callable, Mapping, Sequence, TypeVar

from data_layout import MAX_PREFLIGHT_JSON_BYTES
from json_store import (
    _durable_mutation_lock,
    _pinned_root_matches,
    _validate_private_descriptor,
    lock_for,
)
from mentat_db import SCHEMA_VERSION as DATABASE_SCHEMA_VERSION
from private_state import private_state_lock
from task_repository import (
    MAX_TASKS,
    TaskRepository,
    TaskRepositoryConflict,
    TaskRepositoryError,
    TaskRepositoryUnavailable,
    _guarded_transaction,
    _open_repository_database,
)


MAX_PROJECTS = 256
MAX_PROJECT_DOCUMENT_BYTES = MAX_PREFLIGHT_JSON_BYTES
PROJECT_AUTHORITY_CONTRACT = "mentat-project-sqlite-cutover-v1"
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
PROJECT_STATUSES = frozenset({"active", "paused", "archived"})
_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|token|password|credential|private[_-]?key|"
    r"(?:^|[_-])path(?:$|[_-])|command|arguments?|environment|env[_-]?var)",
    re.IGNORECASE,
)
_UNKNOWN_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")


class ProjectRepositoryError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ProjectRepositoryConflict(ProjectRepositoryError):
    pass


class ProjectRepositoryValidationError(ProjectRepositoryError):
    pass


@dataclass(frozen=True)
class ProjectSourceSnapshot:
    raw: bytes
    projects: tuple[dict[str, Any], ...]
    sha256: str
    identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class ProjectAuthorityReceipt:
    source_sha256: str
    source_project_count: int
    task_source_sha256: str
    cutover_at: float


R = TypeVar("R")


def _fail(code: str) -> None:
    raise ProjectRepositoryValidationError(code)


def _text(value: object, field: str, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value or value != value.strip():
        _fail(f"project.{field}.invalid")
    if (not empty and not value) or len(value) > maximum:
        _fail(f"project.{field}.invalid")
    return value


def _timestamp(value: object, field: str) -> str:
    value = _text(value, field, 64)
    # Timestamp precision/zone are already constrained by the legacy project
    # document. Keep the source representation intact for recovery exports.
    if "T" not in value and " " not in value:
        _fail(f"project.{field}.invalid")
    return value


def _canonical_json(value: Any, *, code: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProjectRepositoryValidationError(code) from exc


def _validate_extension(value: Any, *, depth: int = 0) -> None:
    if depth > 8:
        _fail("project.extensions.invalid")
    if value is None or type(value) in {bool, int}:
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("project.extensions.invalid")
        return
    if isinstance(value, str):
        if len(value) > MAX_PROJECT_DOCUMENT_BYTES or "\x00" in value:
            _fail("project.extensions.invalid")
        return
    if isinstance(value, list):
        for item in value:
            _validate_extension(item, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or not _UNKNOWN_KEY_RE.fullmatch(key) or _SENSITIVE_KEY_RE.search(key):
                _fail("project.extensions.private_key")
            _validate_extension(item, depth=depth + 1)
        return
    _fail("project.extensions.invalid")


def normalize_project_document(project: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(project, Mapping):
        _fail("project.invalid")
    identifier = _text(project.get("id"), "id", 80)
    if PROJECT_ID_RE.fullmatch(identifier) is None:
        _fail("project.id.invalid")
    name = _text(project.get("name"), "name", 120)
    status = _text(project.get("status", "active"), "status", 32)
    if status not in PROJECT_STATUSES:
        _fail("project.status.invalid")
    aliases_value = project.get("aliases", project.get("legacy_names", []))
    if aliases_value is None:
        aliases_value = []
    if not isinstance(aliases_value, list) or len(aliases_value) > 12:
        _fail("project.aliases.invalid")
    aliases: list[str] = []
    for alias in aliases_value:
        alias = _text(alias, "aliases", 120)
        if alias.casefold() == name.casefold() or alias in aliases:
            _fail("project.aliases.invalid")
        aliases.append(alias)
    result = {
        "id": identifier,
        "name": name,
        "type": _text(project.get("type", "project"), "type", 80),
        "status": status,
        "description": _text(project.get("description", ""), "description", MAX_PROJECT_DOCUMENT_BYTES, empty=True),
        "obsidian_note": None if project.get("obsidian_note") in {None, ""} else _text(project.get("obsidian_note"), "obsidian_note", 160),
        "aliases": aliases,
        "created_at": _timestamp(project.get("created_at"), "created_at"),
        "updated_at": _timestamp(project.get("updated_at"), "updated_at"),
    }
    extensions = {key: value for key, value in project.items() if key not in {"id", "name", "type", "status", "description", "obsidian_note", "aliases", "legacy_names", "created_at", "updated_at"}}
    for key, value in extensions.items():
        if not _UNKNOWN_KEY_RE.fullmatch(key) or _SENSITIVE_KEY_RE.search(key):
            _fail("project.extensions.private_key")
        _validate_extension(value)
    result.update(extensions)
    raw = _canonical_json(result, code="project.invalid").encode("utf-8")
    if len(raw) > MAX_PROJECT_DOCUMENT_BYTES:
        _fail("project.too_large")
    return result


def normalize_project_collection(projects: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    if not isinstance(projects, (list, tuple)) or len(projects) > MAX_PROJECTS:
        _fail("projects.invalid")
    normalized = tuple(normalize_project_document(project) for project in projects)
    identifiers: set[str] = set()
    names: set[str] = set()
    aliases: set[str] = set()
    for project in normalized:
        identifier = project["id"]
        name_key = project["name"].casefold()
        if identifier in identifiers or name_key in names or name_key in aliases:
            _fail("projects.duplicate")
        identifiers.add(identifier)
        names.add(name_key)
        for alias in project["aliases"]:
            alias_key = alias.casefold()
            if alias_key in names or alias_key in aliases:
                _fail("projects.ambiguous")
            aliases.add(alias_key)
    return normalized


def _read_source_snapshot(path: Path, *, required_mode: int | None) -> ProjectSourceSnapshot:
    """Read one stable, private legacy source snapshot.

    The pathname is checked against the opened descriptor before returning, so
    a replacement of ``projects.json`` cannot be mistaken for the file whose
    contents were imported.  The final call from the cutover transaction
    repeats this check immediately before the authority receipt is claimed.
    """

    path = Path(path)
    try:
        with _durable_mutation_lock(path.parent, cross_process_lock=True) as root_descriptor:
            if not _pinned_root_matches(path.parent, root_descriptor):
                raise OSError("project source root changed")
            with lock_for(path):
                flags = (
                    os.O_RDONLY
                    | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NONBLOCK", 0)
                )
                descriptor = (
                    os.open(path.name, flags, dir_fd=root_descriptor)
                    if root_descriptor is not None
                    else os.open(path, flags)
                )
                try:
                    before = _validate_private_descriptor(
                        descriptor,
                        required_mode=required_mode,
                        maximum_bytes=MAX_PREFLIGHT_JSON_BYTES,
                    )
                    chunks: list[bytes] = []
                    remaining = MAX_PREFLIGHT_JSON_BYTES + 1
                    while remaining > 0:
                        chunk = os.read(descriptor, min(64 * 1024, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    raw = b"".join(chunks)
                    after = _validate_private_descriptor(
                        descriptor,
                        required_mode=required_mode,
                        maximum_bytes=MAX_PREFLIGHT_JSON_BYTES,
                    )
                finally:
                    os.close(descriptor)
            if not _pinned_root_matches(path.parent, root_descriptor):
                raise OSError("project source root changed")
            current = (
                os.stat(path.name, dir_fd=root_descriptor, follow_symlinks=False)
                if root_descriptor is not None and os.stat in os.supports_dir_fd
                else os.lstat(path)
            )
        if (
            len(raw) > MAX_PREFLIGHT_JSON_BYTES
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or after.st_nlink != 1
            or not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or before.st_dev != current.st_dev
            or before.st_ino != current.st_ino
            or before.st_size != current.st_size
            or before.st_mtime_ns != current.st_mtime_ns
        ):
            raise OSError("project source changed")
    except ProjectRepositoryError:
        raise
    except OSError as exc:
        raise ProjectRepositoryError("project_source.unavailable") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
        projects = normalize_project_collection(payload)
    except (UnicodeError, json.JSONDecodeError, ProjectRepositoryError) as exc:
        raise ProjectRepositoryError("project_source.invalid") from exc
    return ProjectSourceSnapshot(raw, projects, hashlib.sha256(raw).hexdigest(), (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns))


class ProjectRepository:
    def __init__(self, connection):
        self.connection = connection
        self.connection.row_factory = __import__("sqlite3").Row
        self._require_schema()

    def _require_schema(self) -> None:
        row = self.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        if int(row[0] or 0) != DATABASE_SCHEMA_VERSION:
            raise ProjectRepositoryError("project_repository.schema_unsupported")
        names = {str(row[0]) for row in self.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"mentat_projects", "mentat_project_store_state", "mentat_tasks"}.issubset(names):
            raise ProjectRepositoryError("project_repository.schema_unsupported")

    def authority_receipt(self, *, required: bool = False) -> ProjectAuthorityReceipt | None:
        rows = self.connection.execute("SELECT authority, migration_contract, source_sha256, source_project_count, task_source_sha256, cutover_at FROM mentat_project_store_state WHERE singleton = 1").fetchall()
        if not rows:
            if required:
                raise ProjectRepositoryError("project_repository.authority_missing")
            return None
        if len(rows) != 1:
            raise ProjectRepositoryError("project_repository.corrupt")
        row = rows[0]
        try:
            receipt = ProjectAuthorityReceipt(str(row["source_sha256"]), int(row["source_project_count"]), str(row["task_source_sha256"]), float(row["cutover_at"]))
        except (TypeError, ValueError) as exc:
            raise ProjectRepositoryError("project_repository.corrupt") from exc
        if (row["authority"] != "sqlite" or row["migration_contract"] != PROJECT_AUTHORITY_CONTRACT or not re.fullmatch(r"[0-9a-f]{64}", receipt.source_sha256) or not re.fullmatch(r"[0-9a-f]{64}", receipt.task_source_sha256) or not 0 <= receipt.source_project_count <= MAX_PROJECTS or not math.isfinite(receipt.cutover_at) or receipt.cutover_at <= 0):
            raise ProjectRepositoryError("project_repository.corrupt")
        return receipt

    def _list_projects(self) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM mentat_projects ORDER BY sort_order, id").fetchall()
        projects: list[dict[str, Any]] = []
        for ordinal, row in enumerate(rows):
            if int(row["sort_order"]) != ordinal:
                raise ProjectRepositoryError("project_repository.corrupt")
            try:
                aliases = json.loads(str(row["aliases_json"]))
                extensions = json.loads(str(row["extensions_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ProjectRepositoryError("project_repository.corrupt") from exc
            if not isinstance(aliases, list) or not isinstance(extensions, dict):
                raise ProjectRepositoryError("project_repository.corrupt")
            project = {"id": str(row["id"]), "name": str(row["name"]), "type": str(row["type"]), "status": str(row["status"]), "description": str(row["description"]), "obsidian_note": row["obsidian_note"], "aliases": aliases, "created_at": str(row["created_at"]), "updated_at": str(row["updated_at"]), **extensions}
            projects.append(normalize_project_document(project))
        return list(normalize_project_collection(projects))

    def list_projects(self) -> list[dict[str, Any]]:
        return self._list_projects()

    def _insert(self, project: Mapping[str, Any], sort_order: int, revision: int = 1) -> None:
        extensions = {key: value for key, value in project.items() if key not in {"id", "name", "type", "status", "description", "obsidian_note", "aliases", "created_at", "updated_at"}}
        self.connection.execute("INSERT INTO mentat_projects (id, sort_order, revision, name, name_key, type, status, description, obsidian_note, aliases_json, extensions_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (project["id"], sort_order, revision, project["name"], project["name"].casefold(), project["type"], project["status"], project["description"], project["obsidian_note"], _canonical_json(project["aliases"], code="project.invalid"), _canonical_json(extensions, code="project.invalid"), project["created_at"], project["updated_at"]))

    def insert_collection(self, projects: Sequence[Mapping[str, Any]]) -> None:
        normalized = normalize_project_collection(projects)
        if self.connection.execute("SELECT COUNT(*) FROM mentat_projects").fetchone()[0]:
            raise ProjectRepositoryConflict("project_repository.occupied")
        for ordinal, project in enumerate(normalized):
            self._insert(project, ordinal)

    def claim_authority(self, source: ProjectSourceSnapshot, *, task_source_sha256: str) -> ProjectAuthorityReceipt:
        if not self.connection.in_transaction:
            raise ProjectRepositoryError("project_repository.transaction_required")
        if self.authority_receipt() is not None:
            raise ProjectRepositoryConflict("project_repository.already_authoritative")
        cutover_at = time.time()
        self.connection.execute("INSERT INTO mentat_project_store_state (singleton, authority, migration_contract, source_sha256, source_project_count, task_source_sha256, cutover_at) VALUES (1, 'sqlite', ?, ?, ?, ?, ?)", (PROJECT_AUTHORITY_CONTRACT, source.sha256, len(source.projects), task_source_sha256, cutover_at))
        return self.authority_receipt(required=True)

    def mutate_collection(self, mutator: Callable[[list[dict[str, Any]]], tuple[Any, R]]) -> R:
        if not callable(mutator):
            raise ProjectRepositoryValidationError("project_repository.mutator_invalid")
        self.authority_receipt(required=True)
        current = self._list_projects()
        working = deepcopy(current)
        outcome = mutator(working)
        if not isinstance(outcome, tuple) or len(outcome) != 2:
            raise ProjectRepositoryValidationError("project_repository.mutator_invalid")
        candidate, result = outcome
        if candidate is working:
            return result
        normalized = list(normalize_project_collection(candidate))
        if normalized == current:
            return result
        current_ids = {project["id"] for project in current}
        candidate_ids = {project["id"] for project in normalized}
        if not current_ids.issubset(candidate_ids):
            raise ProjectRepositoryConflict("project_repository.membership_immutable")
        previous_by_id = {project["id"]: project for project in current}
        revisions = {str(row["id"]): int(row["revision"]) for row in self.connection.execute("SELECT id, revision FROM mentat_projects")}
        self.connection.execute("DELETE FROM mentat_projects")
        for ordinal, project in enumerate(normalized):
            previous = next((item for item in current if item["id"] == project["id"]), None)
            revision = revisions[project["id"]] if previous == project else revisions.get(project["id"], 0) + 1
            self._insert(project, ordinal, revision)
        # ``mentat_tasks.project`` is a retained compatibility display field;
        # membership itself is the immutable Project ID. Keep old dashboard
        # readers coherent when the existing narrow Project update route
        # changes a name.
        for project in normalized:
            previous = previous_by_id.get(project["id"])
            if previous is not None and previous["name"] != project["name"]:
                self.connection.execute(
                    "UPDATE mentat_tasks SET project = ? WHERE project_id = ?",
                    (project["name"], project["id"]),
                )
        if self._list_projects() != normalized:
            raise ProjectRepositoryError("project_repository.reconstruction_failed")
        return result


def _project_mapping(projects: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for project in projects:
        for name in [project["name"], *project["aliases"]]:
            key = name.casefold()
            if key in mapping and mapping[key] != project["id"]:
                raise ProjectRepositoryValidationError("projects.ambiguous")
            mapping[key] = project["id"]
    return mapping


def ensure_project_sqlite_authority(data_dir: Path, *, required_source_mode: int | None = 0o600) -> ProjectAuthorityReceipt:
    """Map every canonical Task to an immutable Project ID and claim Projects."""

    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            projects = ProjectRepository(connection)
            existing = projects.authority_receipt()
            if existing is not None:
                missing = connection.execute("SELECT 1 FROM mentat_tasks WHERE project_id IS NULL LIMIT 1").fetchone()
                if missing is not None:
                    raise ProjectRepositoryError("project_repository.membership_missing")
                return existing
            source = _read_source_snapshot(root / "projects.json", required_mode=required_source_mode)
            task_repository = TaskRepository(connection, identity_guard=guard)
            task_receipt = task_repository.authority_receipt(required=True)
            tasks = task_repository.list_tasks()
            if len(tasks) > MAX_TASKS:
                raise ProjectRepositoryError("project_repository.corrupt")
            mapping = _project_mapping(source.projects)
            task_ids: list[tuple[str, str]] = []
            for task in tasks:
                project_id = mapping.get(str(task["project"]).casefold())
                if project_id is None:
                    raise ProjectRepositoryConflict("project_repository.task_project_missing")
                task_ids.append((project_id, str(task["id"])))
            with _guarded_transaction(connection, guard, immediate=True):
                projects = ProjectRepository(connection)
                if projects.authority_receipt() is not None:
                    raise ProjectRepositoryConflict("project_repository.already_authoritative")
                if connection.execute("SELECT COUNT(*) FROM mentat_projects").fetchone()[0]:
                    raise ProjectRepositoryConflict("project_repository.occupied")
                current_source = _read_source_snapshot(root / "projects.json", required_mode=required_source_mode)
                if current_source != source:
                    raise ProjectRepositoryConflict("project_repository.source_changed")
                current_task_receipt = task_repository.authority_receipt(required=True)
                if current_task_receipt != task_receipt:
                    raise ProjectRepositoryConflict("project_repository.task_authority_changed")
                projects.insert_collection(source.projects)
                for project_id, task_id in task_ids:
                    updated = connection.execute("UPDATE mentat_tasks SET project_id = ? WHERE id = ? AND project_id IS NULL", (project_id, task_id))
                    if updated.rowcount != 1:
                        raise ProjectRepositoryConflict("project_repository.membership_changed")
                if connection.execute("SELECT 1 FROM mentat_tasks WHERE project_id IS NULL LIMIT 1").fetchone() is not None:
                    raise ProjectRepositoryError("project_repository.membership_missing")
                return projects.claim_authority(source, task_source_sha256=task_receipt.source_sha256)


def read_authoritative_projects(data_dir: Path) -> list[dict[str, Any]]:
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, _guard):
            repository = ProjectRepository(connection)
            repository.authority_receipt(required=True)
            return repository.list_projects()


def export_authoritative_projects(data_dir: Path) -> bytes:
    """Return deterministic Project recovery bytes from the SQLite authority."""

    projects = read_authoritative_projects(data_dir)
    return (_canonical_json(projects, code="project_repository.export_invalid") + "\n").encode("utf-8")


def mutate_authoritative_projects(data_dir: Path, mutator: Callable[[list[dict[str, Any]]], tuple[Any, R]]) -> R:
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                return ProjectRepository(connection).mutate_collection(mutator)


def validate_project_repository_connection(
    connection,
    *,
    require_authority_consistency: bool = False,
) -> int:
    """Validate Project records and immutable Task membership in one snapshot."""

    repository = ProjectRepository(connection)
    projects = repository.list_projects()
    identifiers = {project["id"] for project in projects}
    receipt = repository.authority_receipt()
    task_rows = connection.execute("SELECT project_id FROM mentat_tasks").fetchall()
    if receipt is not None:
        if any(not isinstance(row[0], str) or row[0] not in identifiers for row in task_rows):
            raise ProjectRepositoryError("project_repository.membership_missing")
    elif require_authority_consistency and (projects or task_rows):
        raise ProjectRepositoryError("project_repository.authority_missing")
    return len(projects)
