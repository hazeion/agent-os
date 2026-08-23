"""Canonical SQLite repository and one-way authority boundary for Mentat Tasks."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import ctypes
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time
from tempfile import TemporaryDirectory
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar

from data_layout import MAX_PREFLIGHT_JSON_BYTES, _open_readonly_no_follow
from json_store import (
    _durable_mutation_lock,
    _pinned_root_matches,
    _validate_private_descriptor,
    lock_for,
    write_json_bytes_atomic,
)
from mentat_db import (
    SCHEMA_VERSION as DATABASE_SCHEMA_VERSION,
    MIGRATIONS,
    MentatDatabaseError,
    _validate_database_set,
    connect as connect_database,
    connect_with_identity as connect_database_with_identity,
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
TASK_AUTHORITY_CONTRACT = "mentat-task-sqlite-cutover-v1"
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


class TaskRepositoryPartialFailure(TaskRepositoryError):
    """An offline publication failed after its write state became uncertain."""

    def __init__(self, code: str, *, writes_performed: bool | None):
        super().__init__(code)
        self.writes_performed = writes_performed


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
    source: TaskSourceSnapshot | None
    destination: TaskDestinationSnapshot
    confirmation_token: str

    def public_summary(self) -> dict[str, Any]:
        if self.source is None:
            return {
                "status": self.status,
                "source": None,
                "destination": {
                    "state": self.destination.state,
                    "schema_version": self.destination.schema_version,
                    "task_count": self.destination.task_count,
                },
                "confirmation_token": None,
                "writes_performed": False,
            }
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


@dataclass(frozen=True)
class TaskAuthorityReceipt:
    source_sha256: str
    source_task_count: int
    cutover_at: float


@dataclass(frozen=True)
class TaskLegacyExportPreview:
    export: TaskExport
    destination_sha256: str | None
    destination_identity: tuple[int, int, int, int, int] | None
    confirmation_token: str

    def public_summary(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "task_count": self.export.task_count,
            "export_sha256": self.export.sha256,
            "destination": "replace" if self.destination_identity is not None else "create",
            "confirmation_token": self.confirmation_token,
            "writes_performed": False,
        }


@dataclass(frozen=True)
class TaskCompatibleExportPreview:
    export: TaskExport
    target_name: str
    source_digest: str
    private_digest: str
    confirmation_token: str

    def public_summary(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "task_count": self.export.task_count,
            "export_sha256": self.export.sha256,
            "destination": "new_schema5_data_root",
            "target_name": self.target_name,
            "confirmation_token": self.confirmation_token,
            "writes_performed": False,
        }


R = TypeVar("R")


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


def _legacy_timestamp(value: Any) -> Any:
    """Give shipped timezone-naive Task timestamps one deterministic meaning."""

    if not isinstance(value, str) or ("T" not in value and " " not in value):
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return f"{value}+00:00"
    return value


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


def normalize_legacy_task_collection(
    tasks: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Upgrade sparse historical JSON Tasks to the canonical public shape."""

    if not isinstance(tasks, (list, tuple)):
        _fail("tasks.invalid")
    fallback_timestamp = "1970-01-01T00:00:00+00:00"
    upgraded: list[dict[str, Any]] = []
    for item in tasks:
        if not isinstance(item, Mapping):
            _fail("task.invalid")
        task = dict(item)
        task.setdefault("description", "")
        task.setdefault("project", "General")
        task.setdefault("status", "todo")
        task.setdefault("priority", "medium")
        task.setdefault("assignee", None)
        task.setdefault("due_date", None)
        task.setdefault("source", "legacy")
        task.setdefault("tags", [])
        task.setdefault("review_required", False)
        task.setdefault("needs_attention", False)
        task.setdefault("created_at", fallback_timestamp)
        task.setdefault("updated_at", task["created_at"])
        task.setdefault("completed_at", None)
        for field in ("created_at", "updated_at", "completed_at"):
            if task.get(field) is not None:
                task[field] = _legacy_timestamp(task[field])
        if isinstance(task.get("status"), str):
            task["status"] = task["status"].strip().lower().replace("_", " ")
            task["status"] = {
                "open": "todo",
                "ready": "todo",
                "done": "completed",
            }.get(task["status"], task["status"])
        if isinstance(task.get("priority"), str):
            task["priority"] = task["priority"].strip().lower()
        if isinstance(task.get("delegation"), Mapping):
            delegation = dict(task["delegation"])
            delegation.setdefault("profile_id", "legacy-unbound")
            task["delegation"] = delegation
        upgraded.append(task)
    return normalize_task_collection(upgraded)


def _canonical_json(value: Any) -> str:
    return _json_bytes(value, code="task.document.invalid").decode("utf-8")


class _DatabaseIdentityGuard:
    """Bind a live repository connection to the database path it opened."""

    def __init__(
        self,
        data_root: Path,
        opening_identities: Mapping[Path, tuple[int, int] | None],
    ):
        selected = database_path(data_root)
        self.private = selected.parent.resolve(strict=True)
        self.path = self.private / selected.name
        self.main_identity = opening_identities.get(self.path)
        if self.main_identity is None:
            raise TaskRepositoryUnavailable("task_repository.database_changed")
        self.verify(opening_identities)

    def capture(self) -> dict[Path, tuple[int, int] | None]:
        try:
            identities = _validate_database_set(self.path, self.private)
        except (MentatDatabaseError, OSError) as exc:
            raise TaskRepositoryUnavailable("task_repository.database_changed") from exc
        if identities.get(self.path) != self.main_identity:
            raise TaskRepositoryUnavailable("task_repository.database_changed")
        return identities

    def verify(self, expected: Mapping[Path, tuple[int, int] | None]) -> None:
        if self.capture() != dict(expected):
            raise TaskRepositoryUnavailable("task_repository.database_changed")


@contextmanager
def _guarded_transaction(
    connection: sqlite3.Connection,
    guard: _DatabaseIdentityGuard | None,
    *,
    immediate: bool = False,
):
    if guard is None:
        with transaction(connection, immediate=immediate):
            yield
        return
    guard.capture()
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    expected = guard.capture()
    try:
        yield
        guard.verify(expected)
    except Exception:
        connection.rollback()
        raise
    try:
        connection.commit()
        guard.verify(expected)
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise


@contextmanager
def _open_repository_database(data_root: Path):
    """Open and close one bounded repository connection with path identity."""

    connection = None
    try:
        connection, opening_identities = connect_database_with_identity(data_root)
        guard = _DatabaseIdentityGuard(data_root, opening_identities)
        yield connection, guard
        guard.capture()
    except TaskRepositoryError:
        raise
    except sqlite3.IntegrityError as exc:
        raise TaskRepositoryValidationError("task_repository.integrity") from exc
    except (MentatDatabaseError, OSError, sqlite3.Error, ValueError, TypeError) as exc:
        raise TaskRepositoryUnavailable("task_repository.unavailable") from exc
    finally:
        if connection is not None:
            connection.close()


class TaskRepository:
    """Transaction-friendly repository over an already-open Mentat database."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        allow_pre_authority_schema: bool = False,
        identity_guard: _DatabaseIdentityGuard | None = None,
    ):
        self.connection = connection
        self.allow_pre_authority_schema = allow_pre_authority_schema
        self.identity_guard = identity_guard
        self.connection.row_factory = sqlite3.Row
        self._require_schema()

    def _require_schema(self) -> None:
        names = {
            str(row[0])
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required_tables = {
            "mentat_tasks",
            "mentat_task_tags",
            "mentat_task_dependencies",
        }
        if not self.allow_pre_authority_schema:
            required_tables.add("mentat_task_store_state")
        if not required_tables.issubset(names):
            raise TaskRepositoryError("task_repository.schema_unsupported")
        try:
            row = self.connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()
            version = int(row[0] or 0)
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise TaskRepositoryError("task_repository.schema_unsupported") from exc
        allowed_versions = (
            {5, 6, 7, 8, DATABASE_SCHEMA_VERSION}
            if self.allow_pre_authority_schema
            else {6, 7, 8, DATABASE_SCHEMA_VERSION}
        )
        if version not in allowed_versions:
            raise TaskRepositoryError("task_repository.schema_unsupported")
        if _task_schema_fingerprint(self.connection) != _expected_task_schema_fingerprint(version):
            raise TaskRepositoryError("task_repository.schema_unsupported")

    def count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM mentat_tasks").fetchone()
        return int(row[0])

    def authority_receipt(self, *, required: bool = False) -> TaskAuthorityReceipt | None:
        rows = self.connection.execute(
            "SELECT authority, migration_contract, source_sha256, "
            "source_task_count, cutover_at FROM mentat_task_store_state "
            "WHERE singleton = 1"
        ).fetchall()
        if not rows:
            if required:
                raise TaskRepositoryUnavailable("task_repository.authority_missing")
            return None
        if len(rows) != 1:
            raise TaskRepositoryError("task_repository.corrupt")
        row = rows[0]
        source_sha256 = str(row["source_sha256"])
        source_task_count = int(row["source_task_count"])
        cutover_at = float(row["cutover_at"])
        if (
            row["authority"] != "sqlite"
            or row["migration_contract"] != TASK_AUTHORITY_CONTRACT
            or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
            or not 0 <= source_task_count <= MAX_TASKS
            or not math.isfinite(cutover_at)
            or cutover_at <= 0
        ):
            raise TaskRepositoryError("task_repository.corrupt")
        return TaskAuthorityReceipt(source_sha256, source_task_count, cutover_at)

    @contextmanager
    def _snapshot(self):
        if self.connection.in_transaction:
            yield
            return
        with _guarded_transaction(self.connection, self.identity_guard):
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

    def claim_authority(self, source: TaskSourceSnapshot) -> TaskAuthorityReceipt:
        """Record SQLite authority inside the caller's import transaction."""

        if not self.connection.in_transaction:
            raise TaskRepositoryError("task_repository.transaction_required")
        if self.authority_receipt() is not None:
            raise TaskRepositoryConflict("task_repository.already_authoritative")
        cutover_at = time.time()
        self.connection.execute(
            "INSERT INTO mentat_task_store_state("
            "singleton, authority, migration_contract, source_sha256, "
            "source_task_count, cutover_at) VALUES (1, 'sqlite', ?, ?, ?, ?)",
            (
                TASK_AUTHORITY_CONTRACT,
                source.sha256,
                len(source.tasks),
                cutover_at,
            ),
        )
        receipt = self.authority_receipt(required=True)
        if (
            receipt.source_sha256 != source.sha256
            or receipt.source_task_count != len(source.tasks)
        ):
            raise TaskRepositoryError("task_migration.receipt_invalid")
        return receipt

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
            with _guarded_transaction(
                self.connection,
                self.identity_guard,
                immediate=True,
            ):
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

    def mutate_collection(
        self,
        mutator: Callable[[list[dict[str, Any]]], tuple[Any, R]],
    ) -> R:
        """Map the legacy whole-list mutator contract to one SQLite transaction."""

        if not callable(mutator):
            raise TaskRepositoryValidationError("task_repository.mutator_invalid")
        with self._mutation():
            self.authority_receipt(required=True)
            current = self._list_tasks()
            revisions = {
                str(row["id"]): int(row["revision"])
                for row in self.connection.execute(
                    "SELECT id, revision FROM mentat_tasks"
                ).fetchall()
            }
            working = deepcopy(current)
            outcome = mutator(working)
            if not isinstance(outcome, tuple) or len(outcome) != 2:
                raise TaskRepositoryValidationError("task_repository.mutator_invalid")
            candidate, result = outcome
            if candidate is working:
                return result
            normalized = list(normalize_task_collection(candidate))
            if normalized == current:
                return result

            current_by_id = {task["id"]: task for task in current}
            removed_ids = tuple(sorted(set(current_by_id) - {task["id"] for task in normalized}))
            if removed_ids:
                placeholders = ",".join("?" for _ in removed_ids)
                active = self.connection.execute(
                    f"SELECT task_id FROM mentat_runs WHERE task_id IN ({placeholders}) "
                    "AND status NOT IN ('completed', 'failed', 'cancelled', 'stopped', 'interrupted') "
                    "LIMIT 1",
                    removed_ids,
                ).fetchone()
                if active is not None:
                    raise TaskRepositoryConflict("task_repository.active_run")
            current_order = {
                task["id"]: sort_order for sort_order, task in enumerate(current)
            }
            self.connection.execute("DELETE FROM mentat_task_dependencies")
            self.connection.execute("DELETE FROM mentat_task_tags")
            self.connection.execute("DELETE FROM mentat_tasks")
            for sort_order, task in enumerate(normalized):
                previous = current_by_id.get(task["id"])
                revision = (
                    revisions[task["id"]]
                    if previous == task and current_order[task["id"]] == sort_order
                    else revisions[task["id"]] + 1
                    if previous is not None
                    else 1
                )
                self.connection.execute(
                    "INSERT INTO mentat_tasks ("
                    "id, sort_order, revision, title, description, project, status, priority, "
                    "assignee, assigned_agent_id, assigned_agent_id_present, due_date, source, "
                    "review_required, needs_attention, planned_for_today, manual_rank, "
                    "estimated_minutes, recurrence_parent_id, planning_state, depends_on_present, "
                    "nested_planning_json, extensions_json, created_at, updated_at, completed_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        task["id"],
                        sort_order,
                        revision,
                        *self._storage_values(task, sort_order)[1:],
                    ),
                )
            for task in normalized:
                self._insert_children(task)
            if self._list_tasks() != normalized:
                raise TaskRepositoryError("task_repository.reconstruction_failed")
            return result

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
                    after = _validate_private_descriptor(
                        descriptor,
                        required_mode=required_mode,
                        maximum_bytes=MAX_PREFLIGHT_JSON_BYTES,
                    )
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
        tasks = normalize_legacy_task_collection(payload)
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
        "'mentat_tasks', 'mentat_task_tags', 'mentat_task_dependencies', "
        "'mentat_task_store_state'"
        ") ORDER BY type, name"
    ).fetchall()
    canonical = [
        [str(row[0]), str(row[1]), str(row[2]), str(row[3] or "").strip()]
        for row in rows
    ]
    return hashlib.sha256(_json_bytes(canonical, code="task_repository.schema_invalid")).hexdigest()


@lru_cache(maxsize=2)
def _expected_task_schema_fingerprint(schema_version: int = DATABASE_SCHEMA_VERSION) -> str:
    connection = sqlite3.connect(":memory:")
    try:
        for version, script in MIGRATIONS:
            if version == 5 or (version == 6 and schema_version >= 6):
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
            if schema_version in {5, 6}:
                task_count = validate_repository_connection(connection)
                return TaskDestinationSnapshot(
                    "occupied" if task_count else "requires_schema_migration",
                    schema_version,
                    task_count,
                    _task_schema_fingerprint(connection),
                )
            if schema_version < DATABASE_SCHEMA_VERSION:
                return TaskDestinationSnapshot(
                    "requires_schema_migration", schema_version, 0, f"schema-{schema_version}"
                )
            task_count = validate_repository_connection(connection)
            repository = TaskRepository(connection)
            receipt = repository.authority_receipt()
            return TaskDestinationSnapshot(
                "authoritative" if receipt is not None else "empty" if task_count == 0 else "occupied",
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

    destination = _inspect_destination(Path(data_dir))
    if destination.state == "authoritative":
        return TaskMigrationPreview(
            status="already_cut_over",
            source=None,
            destination=destination,
            confirmation_token="",
        )
    source = _read_source_snapshot(
        Path(data_dir) / "tasks.json",
        required_mode=required_source_mode,
    )
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
    if preview.source is None:
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
        with _open_repository_database(data_root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                repository = TaskRepository(connection, identity_guard=guard)
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


def ensure_task_sqlite_authority(
    data_dir: Path,
    *,
    required_source_mode: int | None = 0o600,
) -> TaskAuthorityReceipt:
    """Atomically establish SQLite as the sole Task authority exactly once."""

    data_root = Path(data_dir)
    with private_state_lock(data_root):
        with _open_repository_database(data_root) as (connection, guard):
            repository = TaskRepository(connection, identity_guard=guard)
            receipt = repository.authority_receipt()
            if receipt is not None:
                return receipt
            if repository.count() != 0:
                raise TaskRepositoryConflict("task_repository.occupied")
            source = _read_source_snapshot(
                data_root / "tasks.json",
                required_mode=required_source_mode,
                cross_process_lock=True,
            )
            with _guarded_transaction(connection, guard, immediate=True):
                repository = TaskRepository(connection, identity_guard=guard)
                if repository.authority_receipt() is not None:
                    raise TaskRepositoryConflict("task_repository.already_authoritative")
                if repository.count() != 0:
                    raise TaskRepositoryConflict("task_repository.occupied")
                repository.insert_collection(source.tasks)
                exported = repository.export()
                expected = _json_bytes(
                    list(source.tasks), code="task_migration.source_invalid"
                )
                if not hmac.compare_digest(exported.raw, expected):
                    raise TaskRepositoryError("task_migration.reconstruction_failed")
                current_source = _read_source_snapshot(
                    data_root / "tasks.json",
                    required_mode=required_source_mode,
                    cross_process_lock=True,
                )
                if (
                    current_source.sha256 != source.sha256
                    or current_source.identity != source.identity
                    or current_source.tasks != source.tasks
                ):
                    raise TaskRepositoryConflict("task_migration.source_changed")
                return repository.claim_authority(source)


def read_authoritative_tasks(data_dir: Path) -> list[dict[str, Any]]:
    """Read one committed Task snapshot without consulting legacy JSON."""

    data_root = Path(data_dir)
    with private_state_lock(data_root):
        with _open_repository_database(data_root) as (connection, guard):
            repository = TaskRepository(connection, identity_guard=guard)
            repository.authority_receipt(required=True)
            return repository.list_tasks()


def mutate_authoritative_tasks(
    data_dir: Path,
    mutator: Callable[[list[dict[str, Any]]], tuple[Any, R]],
) -> R:
    """Run one existing Task list mutator against authoritative SQLite."""

    data_root = Path(data_dir)
    with private_state_lock(data_root):
        with _open_repository_database(data_root) as (connection, guard):
            return TaskRepository(
                connection,
                identity_guard=guard,
            ).mutate_collection(mutator)


def export_tasks(data_dir: Path, *, require_authority: bool = False) -> TaskExport:
    """Return a deterministic read-only export from an initialized repository."""

    data_root = Path(data_dir)
    with private_state_lock(data_root):
        destination = _inspect_destination(data_root)
        if destination.state not in {"empty", "occupied", "authoritative"}:
            raise TaskRepositoryUnavailable("task_repository.schema_unsupported")
        if require_authority and destination.state != "authoritative":
            raise TaskRepositoryUnavailable("task_repository.authority_missing")
        path = database_path(data_root)
        private = path.parent.resolve(strict=True)
        path = private / path.name
        with _read_database_snapshot(path, private) as connection:
            repository = TaskRepository(connection)
            if destination.state == "authoritative":
                repository.authority_receipt(required=True)
            exported = repository.export()
        return exported


def _legacy_export_destination(
    data_root: Path,
    *,
    required_mode: int | None,
) -> tuple[str | None, tuple[int, int, int, int, int] | None]:
    path = Path(data_root) / "tasks.json"
    try:
        with _durable_mutation_lock(path.parent) as root_descriptor:
            if not _pinned_root_matches(path.parent, root_descriptor):
                raise OSError("task export root changed")
            try:
                current = (
                    os.stat(path.name, dir_fd=root_descriptor, follow_symlinks=False)
                    if root_descriptor is not None and os.stat in os.supports_dir_fd
                    else os.lstat(path)
                )
            except FileNotFoundError:
                return None, None
            if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                raise OSError("task export destination is unsafe")
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
                    after = _validate_private_descriptor(
                        descriptor,
                        required_mode=required_mode,
                        maximum_bytes=MAX_PREFLIGHT_JSON_BYTES,
                    )
                finally:
                    os.close(descriptor)
            if not _pinned_root_matches(path.parent, root_descriptor):
                raise OSError("task export root changed")
            current = (
                os.stat(path.name, dir_fd=root_descriptor, follow_symlinks=False)
                if root_descriptor is not None and os.stat in os.supports_dir_fd
                else os.lstat(path)
            )
        if (
            len(raw) > MAX_PREFLIGHT_JSON_BYTES
            or not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (
                os.name == "posix"
                and (
                    current.st_uid != os.getuid()
                    or (
                        required_mode is not None
                        and stat.S_IMODE(current.st_mode) != required_mode
                    )
                )
            )
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            )
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) != (
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
            )
        ):
            raise OSError("task export destination changed")
        identity = (
            int(before.st_dev),
            int(before.st_ino),
            int(before.st_size),
            int(before.st_mtime_ns),
            int(stat.S_IMODE(before.st_mode)),
        )
        return hashlib.sha256(raw).hexdigest(), identity
    except (OSError, ValueError, TypeError) as exc:
        raise TaskRepositoryUnavailable("task_export.destination_unavailable") from exc


def _task_export_confirmation_token(
    exported: TaskExport,
    destination_sha256: str | None,
    destination_identity: tuple[int, int, int, int, int] | None,
) -> str:
    evidence = {
        "contract": "mentat-task-legacy-export-v1",
        "export_sha256": exported.sha256,
        "task_count": exported.task_count,
        "destination_sha256": destination_sha256,
        "destination_identity": list(destination_identity) if destination_identity else None,
    }
    digest = hashlib.sha256(
        _json_bytes(evidence, code="task_export.preview_invalid")
    ).hexdigest()
    return f"task_export_{digest}"


@contextmanager
def _task_export_private_state_lock(
    data_root: Path,
    *,
    write_state: Mapping[str, bool] | None = None,
):
    """Translate expected private-state failures at the complete CLI boundary."""

    try:
        with private_state_lock(data_root) as root_descriptor:
            yield root_descriptor
    except TaskRepositoryError:
        raise
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        TypeError,
        UnicodeError,
        RecursionError,
    ) as exc:
        if write_state is not None and write_state.get("performed") is True:
            raise TaskRepositoryPartialFailure(
                "task_export.verification_failed",
                writes_performed=True,
            ) from exc
        raise TaskRepositoryUnavailable("task_export.capture_unavailable") from exc


def preview_task_legacy_export(
    data_dir: Path,
    *,
    required_destination_mode: int | None = 0o600,
) -> TaskLegacyExportPreview:
    """Preview an exact offline replacement of stale ``tasks.json``."""

    from private_state import mentat_server_active

    data_root = Path(data_dir)
    with _task_export_private_state_lock(data_root):
        if mentat_server_active(data_root):
            raise TaskRepositoryConflict("task_export.server_active")
        exported = export_tasks(data_root, require_authority=True)
        destination_sha256, destination_identity = _legacy_export_destination(
            data_root,
            required_mode=required_destination_mode,
        )
        return TaskLegacyExportPreview(
            export=exported,
            destination_sha256=destination_sha256,
            destination_identity=destination_identity,
            confirmation_token=_task_export_confirmation_token(
                exported,
                destination_sha256,
                destination_identity,
            ),
        )


def confirm_task_legacy_export(
    data_dir: Path,
    confirmation_token: str,
    *,
    required_destination_mode: int | None = 0o600,
) -> dict[str, Any]:
    """Publish a token-bound downgrade snapshot while Mentat is stopped."""

    from private_state import mentat_server_active

    data_root = Path(data_dir)
    write_state = {"performed": False}
    with _task_export_private_state_lock(
        data_root,
        write_state=write_state,
    ) as root_descriptor:
        if mentat_server_active(data_root):
            raise TaskRepositoryConflict("task_export.server_active")
        exported = export_tasks(data_root, require_authority=True)
        destination_sha256, destination_identity = _legacy_export_destination(
            data_root,
            required_mode=required_destination_mode,
        )
        expected = _task_export_confirmation_token(
            exported,
            destination_sha256,
            destination_identity,
        )
        if not isinstance(confirmation_token, str) or not hmac.compare_digest(
            confirmation_token,
            expected,
        ):
            raise TaskRepositoryConflict("task_export.confirmation_invalid")
        path = data_root / "tasks.json"
        try:
            write_json_bytes_atomic(
                path,
                exported.raw,
                expected_type=list,
                mode=0o600,
                parent_fd=root_descriptor,
                maximum_bytes=MAX_EXPORT_BYTES,
            )
        except (OSError, ValueError, TypeError) as exc:
            raise TaskRepositoryPartialFailure(
                "task_export.write_uncertain",
                writes_performed=None,
            ) from exc
        write_state["performed"] = True
        try:
            published = _read_source_snapshot(path, required_mode=0o600)
            verified = (
                published.tasks == tuple(exported.payload())
                and published.raw == exported.raw
            )
        except TaskRepositoryError as exc:
            raise TaskRepositoryPartialFailure(
                "task_export.verification_failed",
                writes_performed=True,
            ) from exc
        if not verified:
            raise TaskRepositoryPartialFailure(
                "task_export.verification_failed",
                writes_performed=True,
            )
        return {
            "status": "exported",
            "task_count": exported.task_count,
            "export_sha256": exported.sha256,
            "writes_performed": True,
        }


def _compatible_downgrade_target(data_root: Path) -> Path:
    resolved = Path(data_root).resolve(strict=True)
    return resolved.with_name(f"{resolved.name}-schema5-downgrade")


@contextmanager
def _pinned_publication_parent(path: Path):
    """Pin the publication parent while an exclusive sibling is installed."""

    if os.name == "nt":
        metadata = os.lstat(path)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("compatible export parent invalid")
        yield None
        return
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or not _pinned_root_matches(
            path,
            descriptor,
        ):
            raise OSError("compatible export parent invalid")
        yield descriptor
    finally:
        os.close(descriptor)


def _publish_directory_noreplace(
    source: Path,
    target: Path,
    parent_descriptor: int | None,
) -> None:
    """Atomically publish one sibling directory without replacing any entry."""

    if source.parent != target.parent:
        raise OSError("compatible export publication boundary invalid")
    if os.name == "nt":
        _windows_publish_directory_write_through(source, target)
        return
    if parent_descriptor is None or not _pinned_root_matches(
        target.parent,
        parent_descriptor,
    ):
        raise OSError("compatible export parent changed")
    library = ctypes.CDLL(None, use_errno=True)
    source_name = os.fsencode(source.name)
    target_name = os.fsencode(target.name)
    if sys.platform == "darwin":
        rename = getattr(library, "renameatx_np", None)
        if rename is None:
            raise OSError("atomic exclusive directory publication unavailable")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            parent_descriptor,
            source_name,
            parent_descriptor,
            target_name,
            0x00000004,  # RENAME_EXCL
        )
    elif sys.platform.startswith("linux"):
        rename = getattr(library, "renameat2", None)
        if rename is None:
            raise OSError("atomic exclusive directory publication unavailable")
        rename.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename.restype = ctypes.c_int
        result = rename(
            parent_descriptor,
            source_name,
            parent_descriptor,
            target_name,
            0x00000001,  # RENAME_NOREPLACE
        )
    else:
        raise OSError("atomic exclusive directory publication unavailable")
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), os.fspath(target))


def _windows_publish_directory_write_through(source: Path, target: Path) -> None:
    """Publish one missing Windows directory with durable no-replace semantics."""

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    move_file = kernel32.MoveFileExW
    move_file.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    move_file.restype = wintypes.BOOL
    movefile_write_through = 0x00000008
    # Omitting MOVEFILE_REPLACE_EXISTING preserves the missing-only contract.
    if not move_file(
        os.fspath(source),
        os.fspath(target),
        movefile_write_through,
    ):
        error = ctypes.get_last_error()
        raise OSError(
            error,
            "Windows write-through directory publication failed",
            os.fspath(target),
        )


def _fsync_staged_directory(path: Path) -> None:
    """Synchronize one trusted staged directory before publication."""

    if os.name != "posix":
        # Windows synchronizes the staged hierarchy as part of the final
        # MOVEFILE_WRITE_THROUGH directory publication.
        return
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("compatible export staged directory invalid")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_publication_parent(parent_descriptor: int | None) -> None:
    """Make the exclusive sibling rename durable before reporting success."""

    if os.name == "posix":
        if parent_descriptor is None:
            raise OSError("compatible export parent unavailable")
        os.fsync(parent_descriptor)
    # Windows has no POSIX-style parent-directory fsync. The final
    # MOVEFILE_WRITE_THROUGH call is the durability boundary there.


def _schema5_private_unit(unit):
    from private_console_unit import (
        PrivateConsoleUnit,
        _history_run_ids,
        standalone_agent_registry_raw,
        validate_private_console_unit,
    )

    registry_database_raw = standalone_agent_registry_raw(unit)
    with TemporaryDirectory(prefix="mentat-schema5-export-") as temporary:
        path = Path(temporary) / "mentat.sqlite3"
        path.write_bytes(unit.database_raw)
        if os.name != "nt":
            path.chmod(0o600)
        connection = sqlite3.connect(path)
        try:
            with transaction(connection, immediate=True):
                version = int(
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                    or 0
                )
                if version != DATABASE_SCHEMA_VERSION:
                    raise TaskRepositoryError("task_export.schema_unsupported")
                retained_run_ids = _history_run_ids(unit.history_raw)
                if retained_run_ids:
                    placeholders = ",".join("?" for _ in retained_run_ids)
                    connection.execute(
                        f"DELETE FROM run_attachments WHERE run_id NOT IN ({placeholders})",
                        retained_run_ids,
                    )
                else:
                    connection.execute("DELETE FROM run_attachments")
                connection.execute(
                    "DELETE FROM attachments WHERE id NOT IN "
                    "(SELECT attachment_id FROM run_attachments)"
                )
                connection.execute(
                    "DELETE FROM blobs WHERE id NOT IN "
                    "(SELECT blob_id FROM attachments WHERE blob_id IS NOT NULL)"
                )
                retained_storage_keys = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT storage_key FROM blobs"
                    )
                }
                connection.execute("DROP TABLE mentat_agent_registry_state")
                connection.execute("DROP TABLE mentat_agents")
                connection.execute("DROP TABLE agent_runtime_configs")
                connection.execute("DROP TABLE provider_connections")
                connection.execute("DROP TABLE mentat_agent_events")
                connection.execute("DROP TABLE mentat_dispatch_reservations")
                connection.execute("DROP TABLE mentat_task_dispatch_heads")
                connection.execute("DROP TABLE mentat_runs")
                connection.execute("DROP TABLE mentat_run_store_state")
                connection.execute("DELETE FROM mentat_task_dependencies")
                connection.execute("DELETE FROM mentat_task_tags")
                connection.execute("DELETE FROM mentat_tasks")
                connection.execute("DROP TABLE mentat_task_store_state")
                connection.execute(
                    "DELETE FROM schema_migrations WHERE version >= 6"
                )
            connection.execute("VACUUM")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise TaskRepositoryError("task_export.schema5_invalid")
            validate_repository_connection(connection)
        except sqlite3.Error as exc:
            raise TaskRepositoryUnavailable("task_export.schema5_unavailable") from exc
        finally:
            connection.close()
        database_raw = path.read_bytes()
    return validate_private_console_unit(
        PrivateConsoleUnit(
            history_raw=unit.history_raw,
            database_raw=database_raw,
            registry_database_raw=registry_database_raw,
            blobs=tuple(
                blob
                for blob in unit.blobs
                if blob.storage_key in retained_storage_keys
            ),
        )
    )


def _load_compatible_non_task_documents(
    data_root: Path,
    root_descriptor: int,
) -> dict[str, bytes]:
    """Capture every durable document except obsolete Task JSON."""

    from data_backup_restore import _document_from_raw
    from data_layout import SEED_FILE_NAMES
    from data_schema import _read_private_artifact_at

    documents: dict[str, bytes] = {}
    for name in SEED_FILE_NAMES:
        if name == "tasks.json":
            continue
        raw, state = _read_private_artifact_at(
            data_root / name,
            root_descriptor,
            maximum=MAX_PREFLIGHT_JSON_BYTES,
            maximum_links=1,
        )
        if state.st_nlink != 1:
            raise OSError("durable document links invalid")
        documents[name] = _document_from_raw(name, raw).raw
    return documents


def _capture_compatible_downgrade(data_root: Path, root_descriptor):
    from private_console_unit import (
        capture_private_console_unit,
        private_console_unit_digest,
        schema5_excluded_agent_ids,
    )
    from remote_hermes import RemoteHermesError, load_connection_state_read_only

    exported = export_tasks(data_root, require_authority=True)
    try:
        connection_state = load_connection_state_read_only(data_root)
        if connection_state.mode == "remote":
            raise TaskRepositoryConflict(
                "task_export.compatible_remote_reconfigure_required"
            )
        documents = _load_compatible_non_task_documents(data_root, root_descriptor)
        source_private_unit = capture_private_console_unit(data_root)
        excluded_agent_ids = schema5_excluded_agent_ids(source_private_unit)
        exported_tasks = json.loads(exported.raw.decode("utf-8"))
        if any(
            isinstance(task, dict)
            and task.get("assigned_agent_id") in excluded_agent_ids
            for task in exported_tasks
        ):
            raise TaskRepositoryConflict(
                "task_export.compatible_agent_unsupported"
            )
        private_unit = _schema5_private_unit(source_private_unit)
        target = _compatible_downgrade_target(data_root)
        if os.path.lexists(os.fspath(target)):
            raise TaskRepositoryConflict("task_export.compatible_target_exists")
        source_digest = hashlib.sha256(
            _json_bytes(
                [
                    [name, hashlib.sha256(raw).hexdigest()]
                    for name, raw in sorted(documents.items())
                ],
                code="task_export.compatible_source_invalid",
            )
        ).hexdigest()
        private_digest = private_console_unit_digest(private_unit)
        evidence = {
            "contract": "mentat-task-compatible-downgrade-v1",
            "export_sha256": exported.sha256,
            "task_count": exported.task_count,
            "source_digest": source_digest,
            "private_digest": private_digest,
            "target_name": target.name,
            "target_absent": True,
        }
        confirmation_token = "task_compatible_" + hashlib.sha256(
            _json_bytes(evidence, code="task_export.compatible_preview_invalid")
        ).hexdigest()
    except TaskRepositoryError:
        raise
    except RemoteHermesError as exc:
        raise TaskRepositoryUnavailable("task_export.capture_unavailable") from exc
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        TypeError,
        UnicodeError,
        json.JSONDecodeError,
        RecursionError,
    ) as exc:
        raise TaskRepositoryUnavailable("task_export.capture_unavailable") from exc
    return exported, documents, private_unit, target, source_digest, private_digest, confirmation_token


def preview_task_compatible_export(data_dir: Path) -> TaskCompatibleExportPreview:
    """Preview a runnable schema-5 sibling data root for an old Mentat build."""

    from private_state import mentat_server_active

    data_root = Path(data_dir)
    with _task_export_private_state_lock(data_root) as root_descriptor:
        if mentat_server_active(data_root):
            raise TaskRepositoryConflict("task_export.server_active")
        (
            exported,
            _documents,
            _private_unit,
            target,
            source_digest,
            private_digest,
            confirmation_token,
        ) = _capture_compatible_downgrade(data_root, root_descriptor)
        return TaskCompatibleExportPreview(
            export=exported,
            target_name=target.name,
            source_digest=source_digest,
            private_digest=private_digest,
            confirmation_token=confirmation_token,
        )


def confirm_task_compatible_export(
    data_dir: Path,
    confirmation_token: str,
) -> dict[str, Any]:
    """Atomically publish a validated schema-5 sibling data root."""

    from data_backup_restore import _load_live_documents
    from data_layout import DATA_ROOT_DIRECTORY_NAMES, SEED_ROOT_TYPES
    from private_console_unit import (
        capture_private_console_unit,
        materialize_private_console_unit,
        private_console_unit_digest,
    )
    from private_state import mentat_server_active

    data_root = Path(data_dir)
    write_state = {"performed": False}
    with _task_export_private_state_lock(
        data_root,
        write_state=write_state,
    ) as root_descriptor:
        if mentat_server_active(data_root):
            raise TaskRepositoryConflict("task_export.server_active")
        (
            exported,
            documents,
            private_unit,
            target,
            source_digest,
            private_digest,
            expected,
        ) = _capture_compatible_downgrade(data_root, root_descriptor)
        if not isinstance(confirmation_token, str) or not hmac.compare_digest(
            confirmation_token,
            expected,
        ):
            raise TaskRepositoryConflict("task_export.confirmation_invalid")
        source_documents = dict(documents)
        source_documents["tasks.json"] = exported.raw
        published = False
        try:
            with _pinned_publication_parent(target.parent) as parent_descriptor:
                with TemporaryDirectory(
                    prefix=f".{target.name}-",
                    dir=target.parent,
                ) as temporary:
                    stage = Path(temporary)
                    if os.name != "nt":
                        stage.chmod(0o700)
                    for name in DATA_ROOT_DIRECTORY_NAMES:
                        directory = stage / name
                        directory.mkdir(mode=0o700)
                        if os.name != "nt":
                            directory.chmod(0o700)
                    with _durable_mutation_lock(stage) as stage_descriptor:
                        for name, raw in source_documents.items():
                            write_json_bytes_atomic(
                                stage / name,
                                raw,
                                expected_type=SEED_ROOT_TYPES[name],
                                mode=0o600,
                                parent_fd=stage_descriptor,
                                maximum_bytes=MAX_PREFLIGHT_JSON_BYTES,
                            )
                    materialize_private_console_unit(
                        stage,
                        private_unit,
                        stage / "private" / "console",
                    )
                    staged_documents = _load_live_documents(stage, None)
                    staged_private = capture_private_console_unit(stage)
                    if (
                        {item.name: item.raw for item in staged_documents}
                        != source_documents
                        or private_console_unit_digest(staged_private) != private_digest
                    ):
                        raise TaskRepositoryError(
                            "task_export.compatible_verification_failed"
                        )
                    _fsync_staged_directory(stage)
                    _publish_directory_noreplace(
                        stage,
                        target,
                        parent_descriptor,
                    )
                    published = True
                    write_state["performed"] = True
                    _fsync_publication_parent(parent_descriptor)
                    if parent_descriptor is not None and not _pinned_root_matches(
                        target.parent,
                        parent_descriptor,
                    ):
                        raise OSError("compatible export parent changed")
            final_documents = _load_live_documents(target, None)
            final_private = capture_private_console_unit(target)
            if (
                {item.name: item.raw for item in final_documents} != source_documents
                or private_console_unit_digest(final_private) != private_digest
            ):
                raise TaskRepositoryError("task_export.compatible_verification_failed")
        except TaskRepositoryError:
            if published:
                raise TaskRepositoryPartialFailure(
                    "task_export.compatible_verification_failed",
                    writes_performed=True,
                )
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise TaskRepositoryPartialFailure(
                "task_export.compatible_write_failed",
                writes_performed=True if published else False,
            ) from exc
        return {
            "status": "exported",
            "task_count": exported.task_count,
            "export_sha256": exported.sha256,
            "destination": "new_schema5_data_root",
            "target_name": target.name,
            "source_digest": source_digest,
            "writes_performed": True,
        }


def repository_task_count(connection: sqlite3.Connection) -> int:
    """Small semantic-validation hook used by private backup/restore."""

    return TaskRepository(connection).count()


def validate_repository_connection(
    connection: sqlite3.Connection,
    *,
    require_authority_consistency: bool = False,
) -> int:
    """Validate Task semantics and dependency integrity in one SQLite snapshot."""

    row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    schema_version = int(row[0] or 0)
    repository = TaskRepository(
        connection,
        allow_pre_authority_schema=schema_version == 5,
    )
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise TaskRepositoryError("task_repository.references_invalid")
    tasks = repository.list_tasks()
    normalize_task_collection(tasks)
    if require_authority_consistency and schema_version >= 6:
        receipt = repository.authority_receipt()
        if tasks and receipt is None:
            raise TaskRepositoryError("task_repository.authority_missing")
    return len(tasks)
