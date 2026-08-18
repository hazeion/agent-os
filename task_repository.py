"""Canonical SQLite repository and migration-preview boundary for Mentat Tasks.

Slice 1C-A deliberately does not route production Task reads or writes through
this module.  It establishes and verifies the storage contract used by the
one-way source-of-truth cutover in Slice 1C-B.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
from tempfile import TemporaryDirectory
from typing import Any, Iterable, Mapping, Sequence

from data_layout import MAX_PREFLIGHT_JSON_BYTES, _open_readonly_no_follow
from json_store import (
    _durable_mutation_lock,
    _pinned_root_matches,
    _validate_private_descriptor,
    lock_for,
)
from mentat_db import (
    SCHEMA_VERSION as DATABASE_SCHEMA_VERSION,
    MIGRATIONS,
    MentatDatabaseError,
    _validate_database_set,
    connect as connect_database,
    database_path,
    transaction,
)
from private_state import private_state_lock
from task_planning import TASK_PLANNING_FIELDS, TaskPlanningError, normalize_task_planning


MAX_TASKS = 2_048
MAX_TASK_DOCUMENT_BYTES = MAX_PREFLIGHT_JSON_BYTES
MAX_EXPORT_BYTES = MAX_PREFLIGHT_JSON_BYTES
MAX_DATABASE_BYTES = 32 * 1024 * 1024
MAX_DATABASE_SIDECAR_BYTES = 64 * 1024 * 1024
TASK_STATUSES = frozenset({"todo", "in progress", "waiting", "needs attention", "completed"})
TASK_PRIORITIES = frozenset({"high", "medium", "low"})
NESTED_PLANNING_FIELDS = frozenset(
    {
        "scheduled_block",
        "recurrence",
        "reminders",
        "subtasks",
        "calendar_links",
        "note_links",
        "delegation",
    }
)
SCALAR_PLANNING_FIELDS = frozenset(
    {
        "planned_for_today",
        "manual_rank",
        "estimated_minutes",
        "recurrence_parent_id",
        "planning_state",
    }
)
CORE_FIELDS = frozenset(
    {
        "id",
        "title",
        "description",
        "project",
        "status",
        "priority",
        "assignee",
        "assigned_agent_id",
        "due_date",
        "source",
        "tags",
        "review_required",
        "needs_attention",
        "created_at",
        "updated_at",
        "completed_at",
    }
)
REQUIRED_CORE_FIELDS = CORE_FIELDS - {"assigned_agent_id"}
MODELED_FIELDS = CORE_FIELDS | TASK_PLANNING_FIELDS
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$")
UNKNOWN_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|token|password|credential|private[_-]?key|"
    r"(?:^|[_-])path(?:$|[_-])|command|arguments?|environment|env[_-]?var)",
    re.IGNORECASE,
)
WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
DUE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TaskRepositoryError(RuntimeError):
    """A bounded Task repository failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class TaskRepositoryValidationError(TaskRepositoryError):
    """A Task document or collection is invalid."""


class TaskRepositoryConflict(TaskRepositoryError):
    """The repository or preview state changed or is already occupied."""


class TaskRepositoryUnavailable(TaskRepositoryError):
    """The private database or source document is unavailable."""


@dataclass(frozen=True)
class TaskSourceSnapshot:
    raw: bytes
    tasks: tuple[dict[str, Any], ...]
    sha256: str
    identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class TaskDestinationSnapshot:
    state: str
    schema_version: int
    task_count: int
    schema_fingerprint: str


@dataclass(frozen=True)
class TaskMigrationPreview:
    status: str
    source: TaskSourceSnapshot
    destination: TaskDestinationSnapshot
    confirmation_token: str

    def public_summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "source": {
                "sha256": self.source.sha256,
                "byte_size": len(self.source.raw),
                "task_count": len(self.source.tasks),
                "task_ids": [task["id"] for task in self.source.tasks],
            },
            "destination": {
                "state": self.destination.state,
                "schema_version": self.destination.schema_version,
                "task_count": self.destination.task_count,
            },
            "confirmation_token": self.confirmation_token,
            "writes_performed": False,
        }


@dataclass(frozen=True)
class TaskExport:
    raw: bytes
    sha256: str
    task_count: int

    def payload(self) -> list[dict[str, Any]]:
        value = json.loads(self.raw.decode("utf-8"))
        if not isinstance(value, list):
            raise TaskRepositoryError("task_repository.corrupt")
        return value


@dataclass(frozen=True)
class TaskSnapshot:
    document: dict[str, Any]
    revision: int


def _fail(code: str) -> None:
    raise TaskRepositoryValidationError(code)


def _text(value: Any, field: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or "\x00" in value:
        _fail(f"task.{field}.invalid")
    if value != value.strip() or (not allow_empty and not value) or len(value) > maximum:
        _fail(f"task.{field}.invalid")
    return value


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field, maximum=160)
    if not ID_RE.fullmatch(result):
        _fail(f"task.{field}.invalid")
    return result


def _timestamp(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    result = _text(value, field, maximum=64)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError:
        _fail(f"task.{field}.invalid")
    if parsed.tzinfo is None:
        _fail(f"task.{field}.invalid")
    return result


def _due_date(value: Any) -> str | None:
    if value is None:
        return None
    result = _text(value, "due_date", maximum=10)
    if not DUE_DATE_RE.fullmatch(result):
        _fail("task.due_date.invalid")
    return result


def _bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        _fail(f"task.{field}.invalid")
    return value


def _json_bytes(value: Any, *, code: str) -> bytes:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail(code)
    return raw


def _safe_extension_value(value: Any, *, depth: int = 0) -> None:
    if depth > 8:
        _fail("task.extensions.invalid")
    if value is None or type(value) in {bool, int}:
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail("task.extensions.invalid")
        return
    if isinstance(value, str):
        if len(value) > MAX_TASK_DOCUMENT_BYTES or "\x00" in value:
            _fail("task.extensions.invalid")
        stripped = value.strip()
        if stripped.startswith(("/", "~/", "\\", "file:", "obsidian:")) or WINDOWS_PATH_RE.match(stripped):
            _fail("task.extensions.private_value")
        lowered = stripped.lower()
        if lowered.startswith(("bearer ", "sk-", "ghp_", "github_pat_")):
            _fail("task.extensions.private_value")
        return
    if isinstance(value, list):
        for item in value:
            _safe_extension_value(item, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or not UNKNOWN_KEY_RE.fullmatch(key) or SENSITIVE_KEY_RE.search(key):
                _fail("task.extensions.private_key")
            _safe_extension_value(item, depth=depth + 1)
        return
    _fail("task.extensions.invalid")


def normalize_task_document(task: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return one canonical public Task document."""

    if not isinstance(task, Mapping):
        _fail("task.invalid")
    missing = sorted(REQUIRED_CORE_FIELDS - set(task))
    if missing:
        _fail("task.required_field_missing")
    try:
        normalized = normalize_task_planning(task)
    except (TaskPlanningError, RecursionError) as exc:
        raise TaskRepositoryValidationError("task.planning.invalid") from exc

    normalized["id"] = _identifier(normalized.get("id"), "id")
    normalized["title"] = _text(normalized.get("title"), "title", maximum=160)
    normalized["description"] = _text(
        normalized.get("description"),
        "description",
        maximum=MAX_TASK_DOCUMENT_BYTES,
        allow_empty=True,
    )
    normalized["project"] = _text(normalized.get("project"), "project", maximum=120)
    status = _text(normalized.get("status"), "status", maximum=32)
    if status not in TASK_STATUSES:
        _fail("task.status.invalid")
    normalized["status"] = status
    priority = _text(normalized.get("priority"), "priority", maximum=16)
    if priority not in TASK_PRIORITIES:
        _fail("task.priority.invalid")
    normalized["priority"] = priority

    assignee = normalized.get("assignee")
    normalized["assignee"] = None if assignee is None else _text(assignee, "assignee", maximum=120)
    if "assigned_agent_id" in normalized and normalized["assigned_agent_id"] is not None:
        normalized["assigned_agent_id"] = _identifier(
            normalized["assigned_agent_id"], "assigned_agent_id"
        )
    normalized["due_date"] = _due_date(normalized.get("due_date"))
    normalized["source"] = _text(normalized.get("source"), "source", maximum=32)
    normalized["review_required"] = _bool(normalized.get("review_required"), "review_required")
    normalized["needs_attention"] = _bool(normalized.get("needs_attention"), "needs_attention")
    normalized["created_at"] = _timestamp(normalized.get("created_at"), "created_at")
    normalized["updated_at"] = _timestamp(normalized.get("updated_at"), "updated_at")
    normalized["completed_at"] = _timestamp(
        normalized.get("completed_at"), "completed_at", nullable=True
    )

    tags = normalized.get("tags")
    if not isinstance(tags, list):
        _fail("task.tags.invalid")
    clean_tags: list[str] = []
    for tag in tags:
        value = _text(tag, "tags", maximum=48)
        if value in clean_tags:
            _fail("task.tags.duplicate")
        clean_tags.append(value)
    normalized["tags"] = clean_tags

    extensions = {key: value for key, value in normalized.items() if key not in MODELED_FIELDS}
    for key, value in extensions.items():
        if not UNKNOWN_KEY_RE.fullmatch(key) or SENSITIVE_KEY_RE.search(key):
            _fail("task.extensions.private_key")
        _safe_extension_value(value)

    if len(_json_bytes(normalized, code="task.document.invalid")) > MAX_TASK_DOCUMENT_BYTES:
        _fail("task.document.too_large")
    return normalized


def normalize_task_collection(tasks: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    if not isinstance(tasks, (list, tuple)) or len(tasks) > MAX_TASKS:
        _fail("tasks.invalid")
    normalized = tuple(normalize_task_document(task) for task in tasks)
    by_id: dict[str, dict[str, Any]] = {}
    for task in normalized:
        identifier = task["id"]
        if identifier in by_id:
            _fail("tasks.duplicate_id")
        by_id[identifier] = task
    for task in normalized:
        for dependency in task.get("depends_on", []):
            if dependency not in by_id:
                _fail("tasks.dependency_missing")

    visiting: set[str] = set()
    visited: set[str] = set()
    for start in by_id:
        if start in visited:
            continue
        stack: list[tuple[str, bool]] = [(start, False)]
        while stack:
            identifier, expanded = stack.pop()
            if expanded:
                visiting.discard(identifier)
                visited.add(identifier)
                continue
            if identifier in visited:
                continue
            if identifier in visiting:
                _fail("tasks.dependency_cycle")
            visiting.add(identifier)
            stack.append((identifier, True))
            for dependency in reversed(by_id[identifier].get("depends_on", [])):
                if dependency in visiting:
                    _fail("tasks.dependency_cycle")
                if dependency not in visited:
                    stack.append((dependency, False))
    raw = _json_bytes(normalized, code="tasks.invalid")
    if len(raw) > MAX_EXPORT_BYTES:
        _fail("tasks.too_large")
    return normalized


def _canonical_json(value: Any) -> str:
    return _json_bytes(value, code="task.document.invalid").decode("utf-8")


class TaskRepository:
    """Transaction-friendly repository over an already-open Mentat database."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self._require_schema()

    def _require_schema(self) -> None:
        names = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {
            "mentat_tasks",
            "mentat_task_tags",
            "mentat_task_dependencies",
        }.issubset(names):
            raise TaskRepositoryError("task_repository.schema_unsupported")
        try:
            row = self.connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()
            version = int(row[0] or 0)
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise TaskRepositoryError("task_repository.schema_unsupported") from exc
        if version != DATABASE_SCHEMA_VERSION:
            raise TaskRepositoryError("task_repository.schema_unsupported")
        if _task_schema_fingerprint(self.connection) != _expected_task_schema_fingerprint():
            raise TaskRepositoryError("task_repository.schema_unsupported")

    def count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM mentat_tasks").fetchone()
        return int(row[0])

    @contextmanager
    def _snapshot(self):
        if self.connection.in_transaction:
            yield
            return
        with transaction(self.connection):
            yield

    @staticmethod
    def _storage_values(task: Mapping[str, Any], sort_order: int) -> tuple[Any, ...]:
        nested = {key: task[key] for key in NESTED_PLANNING_FIELDS if key in task}
        extensions = {
            key: value
            for key, value in task.items()
            if key not in MODELED_FIELDS
        }
        return (
            sort_order,
            task["title"],
            task["description"],
            task["project"],
            task["status"],
            task["priority"],
            task["assignee"],
            task.get("assigned_agent_id"),
            int("assigned_agent_id" in task),
            task["due_date"],
            task["source"],
            int(task["review_required"]),
            int(task["needs_attention"]),
            None if "planned_for_today" not in task else int(task["planned_for_today"]),
            task.get("manual_rank"),
            task.get("estimated_minutes"),
            task.get("recurrence_parent_id"),
            task.get("planning_state"),
            int("depends_on" in task),
            _canonical_json(nested),
            _canonical_json(extensions),
            task["created_at"],
            task["updated_at"],
            task["completed_at"],
        )

    def _insert_children(self, task: Mapping[str, Any]) -> None:
        for ordinal, tag in enumerate(task["tags"]):
            self.connection.execute(
                "INSERT INTO mentat_task_tags(task_id, ordinal, tag) VALUES (?, ?, ?)",
                (task["id"], ordinal, tag),
            )
        for ordinal, dependency in enumerate(task.get("depends_on", [])):
            self.connection.execute(
                "INSERT INTO mentat_task_dependencies("
                "task_id, dependency_task_id, ordinal) VALUES (?, ?, ?)",
                (task["id"], dependency, ordinal),
            )

    def insert_collection(self, tasks: Sequence[Mapping[str, Any]]) -> None:
        normalized = normalize_task_collection(tasks)
        with self._mutation():
            if self.count() != 0:
                raise TaskRepositoryConflict("task_repository.occupied")
            for sort_order, task in enumerate(normalized):
                self.connection.execute(
                    "INSERT INTO mentat_tasks ("
                    "id, sort_order, revision, title, description, project, status, priority, "
                    "assignee, assigned_agent_id, assigned_agent_id_present, due_date, source, "
                    "review_required, needs_attention, planned_for_today, manual_rank, "
                    "estimated_minutes, recurrence_parent_id, planning_state, depends_on_present, "
                    "nested_planning_json, extensions_json, created_at, updated_at, completed_at"
                    ") VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task["id"],
                        *self._storage_values(task, sort_order),
                    ),
                )
            for task in normalized:
                self._insert_children(task)

    def list_tasks(self) -> list[dict[str, Any]]:
        with self._snapshot():
            return self._list_tasks()

    def _list_tasks(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM mentat_tasks ORDER BY sort_order, id"
        ).fetchall()
        tasks: list[dict[str, Any]] = []
        for expected_order, row in enumerate(rows):
            if int(row["sort_order"]) != expected_order:
                raise TaskRepositoryError("task_repository.corrupt")
            try:
                nested = json.loads(str(row["nested_planning_json"]))
                extensions = json.loads(str(row["extensions_json"]))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise TaskRepositoryError("task_repository.corrupt") from exc
            if not isinstance(nested, dict) or set(nested) - NESTED_PLANNING_FIELDS:
                raise TaskRepositoryError("task_repository.corrupt")
            if not isinstance(extensions, dict) or set(extensions) & MODELED_FIELDS:
                raise TaskRepositoryError("task_repository.corrupt")
            tag_rows = self.connection.execute(
                "SELECT ordinal, tag FROM mentat_task_tags "
                "WHERE task_id = ? ORDER BY ordinal",
                (row["id"],),
            ).fetchall()
            if [int(item["ordinal"]) for item in tag_rows] != list(range(len(tag_rows))):
                raise TaskRepositoryError("task_repository.corrupt")
            dependency_rows = self.connection.execute(
                "SELECT ordinal, dependency_task_id FROM mentat_task_dependencies "
                "WHERE task_id = ? ORDER BY ordinal",
                (row["id"],),
            ).fetchall()
            if [int(item["ordinal"]) for item in dependency_rows] != list(
                range(len(dependency_rows))
            ):
                raise TaskRepositoryError("task_repository.corrupt")
            if not bool(row["depends_on_present"]) and dependency_rows:
                raise TaskRepositoryError("task_repository.corrupt")
            if not bool(row["assigned_agent_id_present"]) and row["assigned_agent_id"] is not None:
                raise TaskRepositoryError("task_repository.corrupt")
            task: dict[str, Any] = {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "description": str(row["description"]),
                "project": str(row["project"]),
                "status": str(row["status"]),
                "priority": str(row["priority"]),
                "assignee": row["assignee"],
                "due_date": row["due_date"],
                "source": str(row["source"]),
                "tags": [str(item["tag"]) for item in tag_rows],
                "review_required": bool(row["review_required"]),
                "needs_attention": bool(row["needs_attention"]),
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "completed_at": row["completed_at"],
            }
            if bool(row["assigned_agent_id_present"]):
                task["assigned_agent_id"] = row["assigned_agent_id"]
            for field in SCALAR_PLANNING_FIELDS:
                if row[field] is not None:
                    task[field] = (
                        bool(row[field]) if field == "planned_for_today" else row[field]
                    )
            if bool(row["depends_on_present"]):
                task["depends_on"] = [
                    str(item["dependency_task_id"])
                    for item in dependency_rows
                ]
            task.update(nested)
            task.update(extensions)
            try:
                tasks.append(normalize_task_document(task))
            except TaskRepositoryValidationError as exc:
                raise TaskRepositoryError("task_repository.corrupt") from exc
        try:
            return list(normalize_task_collection(tasks))
        except TaskRepositoryValidationError as exc:
            raise TaskRepositoryError("task_repository.corrupt") from exc

    def get(self, task_id: str) -> TaskSnapshot:
        identifier = _identifier(task_id, "id")
        with self._snapshot():
            row = self.connection.execute(
                "SELECT revision FROM mentat_tasks WHERE id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise TaskRepositoryConflict("task_repository.not_found")
            document = next(
                (task for task in self._list_tasks() if task["id"] == identifier),
                None,
            )
            if document is None:
                raise TaskRepositoryError("task_repository.corrupt")
            return TaskSnapshot(document=document, revision=int(row[0]))

    @contextmanager
    def _mutation(self):
        if not self.connection.in_transaction:
            with transaction(self.connection, immediate=True):
                self._require_schema()
                yield
            return
        self.connection.execute("SAVEPOINT mentat_task_repository_mutation")
        try:
            self._require_schema()
            yield
        except Exception:
            self.connection.execute("ROLLBACK TO mentat_task_repository_mutation")
            self.connection.execute("RELEASE mentat_task_repository_mutation")
            raise
        else:
            self.connection.execute("RELEASE mentat_task_repository_mutation")

    def replace(self, task: Mapping[str, Any], *, expected_revision: int) -> TaskSnapshot:
        """Atomically replace one Task when its internal revision still matches."""

        if type(expected_revision) is not int or expected_revision < 1:
            raise TaskRepositoryValidationError("task_repository.revision_invalid")
        replacement = normalize_task_document(task)
        identifier = replacement["id"]
        result_snapshot: TaskSnapshot | None = None
        with self._mutation():
            rows = self.connection.execute(
                "SELECT id, sort_order, revision FROM mentat_tasks ORDER BY sort_order, id"
            ).fetchall()
            current = next((row for row in rows if str(row["id"]) == identifier), None)
            if current is None:
                raise TaskRepositoryConflict("task_repository.not_found")
            if int(current["revision"]) != expected_revision:
                raise TaskRepositoryConflict("task_repository.revision_conflict")
            documents = self.list_tasks()
            candidates = [
                replacement if item["id"] == identifier else item
                for item in documents
            ]
            normalize_task_collection(candidates)
            self.connection.execute(
                "DELETE FROM mentat_task_dependencies WHERE task_id = ?",
                (identifier,),
            )
            self.connection.execute(
                "DELETE FROM mentat_task_tags WHERE task_id = ?",
                (identifier,),
            )
            result = self.connection.execute(
                "UPDATE mentat_tasks SET "
                "sort_order = ?, revision = revision + 1, title = ?, description = ?, "
                "project = ?, status = ?, priority = ?, assignee = ?, assigned_agent_id = ?, "
                "assigned_agent_id_present = ?, due_date = ?, source = ?, review_required = ?, "
                "needs_attention = ?, planned_for_today = ?, manual_rank = ?, "
                "estimated_minutes = ?, recurrence_parent_id = ?, planning_state = ?, "
                "depends_on_present = ?, nested_planning_json = ?, extensions_json = ?, "
                "created_at = ?, updated_at = ?, completed_at = ? "
                "WHERE id = ? AND revision = ?",
                (
                    *self._storage_values(replacement, int(current["sort_order"])),
                    identifier,
                    expected_revision,
                ),
            )
            if result.rowcount != 1:
                raise TaskRepositoryConflict("task_repository.revision_conflict")
            self._insert_children(replacement)
            stored = next(
                (item for item in self._list_tasks() if item["id"] == identifier),
                None,
            )
            if stored is None:
                raise TaskRepositoryError("task_repository.corrupt")
            result_snapshot = TaskSnapshot(
                document=stored,
                revision=expected_revision + 1,
            )
        if result_snapshot is None:
            raise TaskRepositoryError("task_repository.corrupt")
        return result_snapshot

    def export(self) -> TaskExport:
        tasks = self.list_tasks()
        raw = _json_bytes(tasks, code="task_repository.export_invalid")
        if len(raw) > MAX_EXPORT_BYTES:
            raise TaskRepositoryError("task_repository.export_too_large")
        return TaskExport(
            raw=raw,
            sha256=hashlib.sha256(raw).hexdigest(),
            task_count=len(tasks),
        )


def _read_source_snapshot(
    path: Path,
    *,
    required_mode: int | None,
    cross_process_lock: bool = False,
) -> TaskSourceSnapshot:
    path = Path(path)
    try:
        with _durable_mutation_lock(
            path.parent,
            cross_process_lock=cross_process_lock,
        ) as root_descriptor:
            if not _pinned_root_matches(path.parent, root_descriptor):
                raise OSError("task source root changed")
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
                    else _open_readonly_no_follow(path)
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
                    after = os.fstat(descriptor)
                finally:
                    os.close(descriptor)
            if not _pinned_root_matches(path.parent, root_descriptor):
                raise OSError("task source root changed")
            current = (
                os.stat(path.name, dir_fd=root_descriptor, follow_symlinks=False)
                if root_descriptor is not None and os.stat in os.supports_dir_fd
                else os.lstat(path)
            )
        if len(raw) > MAX_PREFLIGHT_JSON_BYTES:
            raise OSError("task source too large")
        if (
            before.st_dev != after.st_dev
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
            raise OSError("task source changed")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, list):
            _fail("tasks.invalid")
        tasks = normalize_task_collection(payload)
        return TaskSourceSnapshot(
            raw=raw,
            tasks=tasks,
            sha256=hashlib.sha256(raw).hexdigest(),
            identity=(
                int(before.st_dev),
                int(before.st_ino),
                int(before.st_size),
                int(before.st_mtime_ns),
            ),
        )
    except TaskRepositoryError:
        raise
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
        RecursionError,
    ) as exc:
        raise TaskRepositoryUnavailable("task_source.unavailable") from exc


def _task_schema_fingerprint(connection: sqlite3.Connection) -> str:
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        "WHERE tbl_name IN ("
        "'mentat_tasks', 'mentat_task_tags', 'mentat_task_dependencies'"
        ") ORDER BY type, name"
    ).fetchall()
    canonical = [
        [str(row[0]), str(row[1]), str(row[2]), str(row[3] or "").strip()]
        for row in rows
    ]
    return hashlib.sha256(_json_bytes(canonical, code="task_repository.schema_invalid")).hexdigest()


@lru_cache(maxsize=1)
def _expected_task_schema_fingerprint() -> str:
    connection = sqlite3.connect(":memory:")
    try:
        script = next(script for version, script in MIGRATIONS if version == 5)
        connection.executescript(script)
        return _task_schema_fingerprint(connection)
    finally:
        connection.close()


def _readonly_database_uri(
    path: Path,
    identities: Mapping[Path, tuple[int, int] | None],
) -> str:
    """Avoid creating WAL sidecars when a closed database has none to replay."""

    wal = Path(f"{path}-wal")
    shm = Path(f"{path}-shm")
    immutable = identities.get(wal) is None and identities.get(shm) is None
    base = Path(os.path.abspath(os.fspath(path))).as_uri()
    return f"{base}?mode=ro" + ("&immutable=1" if immutable else "")


def _read_database_member(
    path: Path,
    identity: tuple[int, int],
    maximum: int,
) -> bytes:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise TaskRepositoryUnavailable("task_repository.unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (
            (int(before.st_dev), int(before.st_ino)) != identity
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > maximum
        ):
            raise TaskRepositoryUnavailable("task_repository.unavailable")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(raw) > maximum or (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise TaskRepositoryError("task_repository.database_changed")
        return raw
    except TaskRepositoryError:
        raise
    except OSError as exc:
        raise TaskRepositoryUnavailable("task_repository.unavailable") from exc
    finally:
        os.close(descriptor)


@contextmanager
def _read_database_snapshot(path: Path, private: Path):
    """Read committed state without mutating the source WAL/SHM set."""

    identities = _validate_database_set(path, private)
    wal = Path(f"{path}-wal")
    shm = Path(f"{path}-shm")
    captured: dict[Path, bytes] = {}
    for candidate, maximum in (
        (path, MAX_DATABASE_BYTES),
        (wal, MAX_DATABASE_SIDECAR_BYTES),
    ):
        if identities.get(candidate) is None:
            continue
        captured[candidate] = _read_database_member(
            candidate,
            identities[candidate],
            maximum,
        )

    temporary = None
    connection = None
    try:
        if identities.get(wal) is not None or identities.get(shm) is not None:
            temporary = TemporaryDirectory(prefix="mentat-task-snapshot-")
            snapshot = Path(temporary.name) / path.name
            snapshot.write_bytes(captured[path])
            if os.name != "nt":
                snapshot.chmod(0o600)
            if wal in captured:
                snapshot_wal = Path(f"{snapshot}-wal")
                snapshot_wal.write_bytes(captured[wal])
                if os.name != "nt":
                    snapshot_wal.chmod(0o600)
            connection = sqlite3.connect(snapshot, timeout=5.0, isolation_level=None)
        else:
            connection = sqlite3.connect(
                _readonly_database_uri(path, identities),
                uri=True,
                timeout=5.0,
                isolation_level=None,
            )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        if connection is not None:
            connection.close()
        if temporary is not None:
            temporary.cleanup()
        verified = _validate_database_set(path, private)
        if verified != identities:
            raise TaskRepositoryError("task_repository.database_changed")
        for candidate, raw in captured.items():
            maximum = (
                MAX_DATABASE_BYTES if candidate == path else MAX_DATABASE_SIDECAR_BYTES
            )
            if _read_database_member(candidate, identities[candidate], maximum) != raw:
                raise TaskRepositoryError("task_repository.database_changed")


def _inspect_destination(data_dir: Path) -> TaskDestinationSnapshot:
    path = database_path(data_dir)
    try:
        if not os.path.lexists(os.fspath(path)):
            return TaskDestinationSnapshot("missing", 0, 0, "missing")
        private = path.parent.resolve(strict=True)
        path = private / path.name
        with _read_database_snapshot(path, private) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise TaskRepositoryError("task_repository.corrupt")
            versions = [
                int(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            schema_version = max(versions, default=0)
            if schema_version > DATABASE_SCHEMA_VERSION:
                raise TaskRepositoryError("task_repository.schema_newer")
            if schema_version < DATABASE_SCHEMA_VERSION:
                return TaskDestinationSnapshot(
                    "requires_schema_migration", schema_version, 0, f"schema-{schema_version}"
                )
            task_count = validate_repository_connection(connection)
            return TaskDestinationSnapshot(
                "empty" if task_count == 0 else "occupied",
                schema_version,
                task_count,
                _task_schema_fingerprint(connection),
            )
    except TaskRepositoryError:
        raise
    except (MentatDatabaseError, OSError, sqlite3.Error, ValueError, TypeError) as exc:
        raise TaskRepositoryUnavailable("task_repository.unavailable") from exc


def _confirmation_token(
    source: TaskSourceSnapshot,
    destination: TaskDestinationSnapshot,
) -> str:
    evidence = {
        "contract": "mentat-task-sqlite-migration-v1",
        "source_sha256": source.sha256,
        "source_identity": list(source.identity),
        "source_task_ids": [task["id"] for task in source.tasks],
        "destination_state": destination.state,
        "destination_schema": destination.schema_version,
        "destination_count": destination.task_count,
        "destination_schema_fingerprint": destination.schema_fingerprint,
    }
    digest = hashlib.sha256(_json_bytes(evidence, code="task_migration.preview_invalid")).hexdigest()
    return f"task_sqlite_{digest}"


def preview_task_sqlite_migration(
    data_dir: Path,
    *,
    required_source_mode: int | None = 0o600,
) -> TaskMigrationPreview:
    """Return an exact, bounded, no-write preview for the future cutover."""

    source = _read_source_snapshot(
        Path(data_dir) / "tasks.json",
        required_mode=required_source_mode,
    )
    destination = _inspect_destination(Path(data_dir))
    status = "ready" if destination.state in {"missing", "requires_schema_migration", "empty"} else "blocked"
    return TaskMigrationPreview(
        status=status,
        source=source,
        destination=destination,
        confirmation_token=_confirmation_token(source, destination),
    )


def import_tasks_from_preview(
    data_dir: Path,
    preview: TaskMigrationPreview,
    *,
    required_source_mode: int | None = 0o600,
) -> TaskExport:
    """Transaction-test the future cutover primitive; not exposed by production CLI/API."""

    if preview.status != "ready":
        raise TaskRepositoryConflict("task_migration.preview_blocked")
    data_root = Path(data_dir)
    with private_state_lock(data_root):
        current_source = _read_source_snapshot(
            data_root / "tasks.json",
            required_mode=required_source_mode,
            cross_process_lock=True,
        )
        if (
            current_source.sha256 != preview.source.sha256
            or current_source.identity != preview.source.identity
            or current_source.tasks != preview.source.tasks
        ):
            raise TaskRepositoryConflict("task_migration.source_changed")
        current_destination = _inspect_destination(data_root)
        if current_destination != preview.destination:
            raise TaskRepositoryConflict("task_migration.destination_changed")
        connection = connect_database(data_root)
        try:
            with transaction(connection, immediate=True):
                repository = TaskRepository(connection)
                if repository.count() != 0:
                    raise TaskRepositoryConflict("task_repository.occupied")
                repository.insert_collection(current_source.tasks)
                exported = repository.export()
                expected = _json_bytes(
                    list(current_source.tasks), code="task_migration.source_invalid"
                )
                if not hmac.compare_digest(exported.raw, expected):
                    raise TaskRepositoryError("task_migration.reconstruction_failed")
            return exported
        except sqlite3.IntegrityError as exc:
            raise TaskRepositoryValidationError("task_repository.integrity") from exc
        except sqlite3.OperationalError as exc:
            raise TaskRepositoryUnavailable("task_repository.unavailable") from exc
        finally:
            connection.close()


def export_tasks(data_dir: Path) -> TaskExport:
    """Return a deterministic read-only export from an initialized repository."""

    data_root = Path(data_dir)
    with private_state_lock(data_root):
        destination = _inspect_destination(data_root)
        if destination.state not in {"empty", "occupied"}:
            raise TaskRepositoryUnavailable("task_repository.schema_unsupported")
        path = database_path(data_root)
        private = path.parent.resolve(strict=True)
        path = private / path.name
        with _read_database_snapshot(path, private) as connection:
            exported = TaskRepository(connection).export()
        return exported


def repository_task_count(connection: sqlite3.Connection) -> int:
    """Small semantic-validation hook used by private backup/restore."""

    return TaskRepository(connection).count()


def validate_repository_connection(connection: sqlite3.Connection) -> int:
    """Validate Task semantics and dependency integrity in one SQLite snapshot."""

    repository = TaskRepository(connection)
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise TaskRepositoryError("task_repository.references_invalid")
    tasks = repository.list_tasks()
    normalize_task_collection(tasks)
    return len(tasks)
