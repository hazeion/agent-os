"""Canonical SQLite repository for Mentat Runs and normalized AgentEvents."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence

from agent_run_history import (
    LEGACY_SCHEMA_VERSIONS,
    SCHEMA_VERSION as HISTORY_SCHEMA_VERSION,
    _hydrate,
    _safe_event_data,
    bounded_excerpt,
    normalize_artifacts,
    normalize_attachments,
    normalize_events,
    normalize_transport_binding,
    normalize_usage,
    secure_history_permissions,
    summarize_run,
)
from agent_runtime import (
    AgentEvent,
    AgentEventType,
    MentatTask,
    TaskStatus,
    canonical_event_storage_fields,
)
from agent_runtime import AgentRun, SubmissionDisposition, SubmissionOutcome
from mentat_db import (
    MIGRATIONS,
    SCHEMA_VERSION as DATABASE_SCHEMA_VERSION,
    MentatDatabaseError,
    connect,
)
from private_state import private_state_lock


RUN_AUTHORITY_CONTRACT = "mentat-run-sqlite-cutover-v1"
RUN_SCHEMA_VERSION = 7
MAX_SOURCE_RUNS = 10_000
TERMINAL_RUN_RETENTION = 250
EVENT_COUNT_RETENTION = 1_000
EVENT_CONTENT_RETENTION_BYTES = 4 * 1024 * 1024
GLOBAL_EVENT_COUNT_RETENTION = 50_000
GLOBAL_EVENT_CONTENT_RETENTION_BYTES = 16 * 1024 * 1024
RUN_DETAILS_LIMIT = 1024 * 1024
TASK_SNAPSHOT_LIMIT = 128 * 1024
RUN_STORE_DATABASE_BUDGET = 48 * 1024 * 1024
IDEMPOTENCY_RETENTION_SECONDS = 30 * 24 * 60 * 60

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_RUN_ID = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z")
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SOURCE_TYPE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_SOURCE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_VERCEL_MESSAGE_SOURCE = re.compile(
    r"submission:(vercel_message_[0-9a-f]{24})\Z"
)
_ACTIVE_STATUSES = frozenset(
    {
        "reserved",
        "queued",
        "submitting",
        "starting",
        "running",
        "cancelling",
        "waiting",
        "waiting_for_approval",
        "waiting_for_clarification",
        "unknown",
    }
)
_TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "cancelled", "stopped", "interrupted"}
)
_ALL_STATUSES = _ACTIVE_STATUSES | _TERMINAL_STATUSES
_DISPATCH_STATES = frozenset(
    {"legacy", "reserved", "submitting", "accepted", "rejected", "unknown"}
)
_OBSERVABLE_RUNTIME_STATUSES = frozenset(
    {
        "queued",
        "starting",
        "running",
        "cancelling",
        "waiting",
        "completed",
        "failed",
        "stopped",
        "interrupted",
    }
)
_RECONCILIATION_TRANSITIONS = {
    "queued": frozenset(
        {"queued", "starting", "running", "waiting", "completed", "failed", "stopped", "interrupted"}
    ),
    "starting": frozenset(
        {"starting", "running", "waiting", "completed", "failed", "stopped", "interrupted"}
    ),
    "running": frozenset(
        {"running", "cancelling", "waiting", "completed", "failed", "stopped", "interrupted"}
    ),
    "cancelling": frozenset(
        {"cancelling", "running", "waiting", "completed", "failed", "stopped", "interrupted"}
    ),
    "waiting": frozenset(
        {"waiting", "running", "cancelling", "completed", "failed", "stopped", "interrupted"}
    ),
    "waiting_for_approval": frozenset(
        {"waiting", "running", "cancelling", "completed", "failed", "stopped", "interrupted"}
    ),
    "waiting_for_clarification": frozenset(
        {"waiting", "running", "cancelling", "completed", "failed", "stopped", "interrupted"}
    ),
    "unknown": _OBSERVABLE_RUNTIME_STATUSES,
}


class RunRepositoryError(RuntimeError):
    """A bounded durable orchestration failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class RunRepositoryUnavailable(RunRepositoryError):
    pass


class RunRepositoryValidationError(RunRepositoryError):
    pass


class RunRepositoryConflict(RunRepositoryError):
    pass


@dataclass(frozen=True)
class RunAuthorityReceipt:
    source_sha256: str
    source_run_count: int
    cutover_at: float


@dataclass(frozen=True)
class RetentionReport:
    removed_run_ids: tuple[str, ...]
    truncated_run_ids: tuple[str, ...]


@dataclass(frozen=True)
class DispatchReservation:
    dispatch_id: str
    run_id: str
    task_id: str
    task_revision: int
    request_digest: str
    runtime_binding_digest: str
    state: str
    attempt_count: int
    duplicate: bool = False


@dataclass(frozen=True)
class RunRecord:
    id: str
    source: str
    task_id: str | None
    task_revision: int | None
    agent_id: str | None
    runtime_type: str
    runtime_config_id: str | None
    runtime_binding_digest: str | None
    runtime_run_ref: str | None
    runtime_event_cursor: int
    status: str
    dispatch_state: str
    state_revision: int
    partial: bool
    timeline_truncated: bool
    first_retained_sequence: int
    last_removed_sequence: int
    last_event_sequence: int
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None


_RUN_SCHEMA_OBJECTS = frozenset(
    {
        "mentat_run_store_state",
        "mentat_runs",
        "mentat_agent_events",
        "mentat_dispatch_reservations",
        "mentat_task_dispatch_heads",
    }
)


def _run_schema_fingerprint(connection: sqlite3.Connection) -> str:
    placeholders = ",".join("?" for _ in _RUN_SCHEMA_OBJECTS)
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        f"WHERE tbl_name IN ({placeholders}) ORDER BY type, name",
        tuple(sorted(_RUN_SCHEMA_OBJECTS)),
    ).fetchall()
    canonical = [
        [str(row[0]), str(row[1]), str(row[2]), str(row[3] or "").strip()]
        for row in rows
    ]
    return hashlib.sha256(
        _canonical_json(
            canonical,
            maximum=256 * 1024,
            code="run_repository.schema_unsupported",
        ).encode("ascii")
    ).hexdigest()


@lru_cache(maxsize=None)
def _expected_run_schema_fingerprint(schema_version: int) -> str:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        for version, script in MIGRATIONS:
            if version > schema_version:
                break
            connection.executescript(script)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                (version,),
            )
        return _run_schema_fingerprint(connection)
    finally:
        connection.close()


def _canonical_json(value: Any, *, maximum: int, code: str) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise RunRepositoryValidationError(code) from exc
    if len(encoded.encode("utf-8")) > maximum:
        raise RunRepositoryValidationError(code)
    return encoded


def runtime_binding_digest(
    *,
    agent_id: str,
    runtime_type: str,
    runtime_config_id: str,
    runtime_agent_ref: str,
    capabilities: Iterable[str],
) -> str:
    payload = {
        "agent_id": _identifier(agent_id),
        "runtime_type": str(runtime_type),
        "runtime_config_id": _identifier(runtime_config_id),
        "runtime_agent_ref": _identifier(runtime_agent_ref),
        "capabilities": sorted(str(value) for value in capabilities),
    }
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", payload["runtime_type"]):
        raise RunRepositoryValidationError("dispatch.binding_invalid")
    if any(not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value) for value in payload["capabilities"]):
        raise RunRepositoryValidationError("dispatch.binding_invalid")
    encoded = _canonical_json(payload, maximum=16_384, code="dispatch.binding_invalid")
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def dispatch_request_digest(
    *,
    task: Mapping[str, Any],
    task_revision: int,
    agent_id: str,
    runtime_type: str,
    runtime_config_id: str,
    capabilities: Iterable[str],
) -> str:
    payload = {
        "contract": "mentat-dispatch-v1",
        "task": dict(task),
        "task_revision": task_revision,
        "agent_id": agent_id,
        "runtime_type": runtime_type,
        "runtime_config_id": runtime_config_id,
        "capabilities": sorted(str(value) for value in capabilities),
    }
    encoded = _canonical_json(payload, maximum=TASK_SNAPSHOT_LIMIT, code="dispatch.request_invalid")
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _decode_json(raw: Any, *, expected: type, code: str) -> Any:
    try:
        value = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RunRepositoryError(code) from exc
    if not isinstance(value, expected):
        raise RunRepositoryError(code)
    return value


def _validate_task_snapshot(
    row: Mapping[str, Any], *, run_capabilities: frozenset[str]
) -> dict[str, Any]:
    snapshot = _decode_json(
        row["task_snapshot_json"], expected=dict, code="run_repository.corrupt"
    )
    allowed = {
        "id", "title", "description", "status", "assigned_agent_id",
        "required_capabilities", "acceptance_criteria",
    }
    if not {"id", "title", "status", "assigned_agent_id"}.issubset(snapshot) or not set(
        snapshot
    ).issubset(allowed):
        raise RunRepositoryError("run_repository.corrupt")
    required = snapshot.get("required_capabilities", [])
    criteria = snapshot.get("acceptance_criteria", [])
    task_statuses = {
        "todo": TaskStatus.QUEUED,
        "in progress": TaskStatus.RUNNING,
        "waiting": TaskStatus.BLOCKED,
        "needs attention": TaskStatus.BLOCKED,
        "completed": TaskStatus.COMPLETED,
    }
    if (
        not isinstance(required, list)
        or not isinstance(criteria, list)
        or not isinstance(snapshot.get("description", ""), str)
        or snapshot.get("status") not in task_statuses
    ):
        raise RunRepositoryError("run_repository.corrupt")
    task_status = task_statuses[snapshot["status"]]
    try:
        task = MentatTask(
            id=snapshot["id"],
            title=snapshot["title"],
            objective=str(snapshot.get("description") or snapshot["title"]).strip(),
            status=task_status,
            assigned_agent_id=snapshot["assigned_agent_id"],
            required_capabilities=tuple(required),
            acceptance_criteria=tuple(criteria),
        )
        canonical = _canonical_json(
            snapshot, maximum=TASK_SNAPSHOT_LIMIT, code="run_repository.corrupt"
        )
    except (KeyError, TypeError, ValueError, RunRepositoryError) as exc:
        raise RunRepositoryError("run_repository.corrupt") from exc
    if (
        canonical != row["task_snapshot_json"]
        or snapshot["id"] != row["task_id"]
        or snapshot["assigned_agent_id"] != row["agent_id"]
        or type(row["task_revision"]) is not int
        or int(row["task_revision"]) < 1
        or not frozenset(task.required_capabilities).issubset(run_capabilities)
    ):
        raise RunRepositoryError("run_repository.corrupt")
    return snapshot


def _validate_event_row(event: Mapping[str, Any], *, run_id: str, run_status: str) -> None:
    try:
        metrics = _decode_json(event["metrics_json"], expected=dict, code="event.corrupt")
        data = _decode_json(event["data_json"], expected=dict, code="event.corrupt")
        if (
            _canonical_json(metrics, maximum=1_024, code="event.corrupt")
            != event["metrics_json"]
            or _canonical_json(data, maximum=16_384, code="event.corrupt")
            != event["data_json"]
            or _safe_event_data(data) != data
            or event["run_id"] != run_id
            or not _SOURCE_TYPE.fullmatch(str(event["source_type"]))
            or _normalized_event_type(
                str(event["source_type"]), run_status
            ).value != str(event["event_type"])
            or bounded_excerpt(event["summary"], 500)[0] != event["summary"]
            or (
                event["content"] is not None
                and bounded_excerpt(event["content"], 20_000)[0]
                != event["content"]
            )
        ):
            raise RunRepositoryError("run_repository.corrupt")
        _identifier(event["id"], event=True)
        if not isinstance(event["source_key"], str) or not _SOURCE_KEY.fullmatch(
            event["source_key"]
        ):
            raise RunRepositoryError("run_repository.corrupt")
        AgentEvent(
            id=str(event["id"]), run_id=run_id, sequence=int(event["sequence"]),
            type=str(event["event_type"]), occurred_at=str(event["occurred_at"]),
            summary=str(event["summary"]), content=event["content"], metrics=metrics,
        )
        if int(event["content_bytes"]) != len(
            str(event["content"] or "").encode("utf-8")
        ):
            raise RunRepositoryError("run_repository.corrupt")
        record = {
            key: event[key]
            for key in (
                "id", "run_id", "sequence", "event_type", "source_type",
                "source_key", "occurred_at", "summary", "content",
                "metrics_json", "data_json",
            )
        }
        expected = hashlib.sha256(
            _canonical_json(record, maximum=32_768, code="event.corrupt").encode(
                "ascii"
            )
        ).hexdigest()
        if expected != event["payload_digest"]:
            raise RunRepositoryError("run_repository.corrupt")
    except (TypeError, ValueError, RunRepositoryError) as exc:
        raise RunRepositoryError("run_repository.corrupt") from exc


def _validate_event_window(
    run: Mapping[str, Any], events: Sequence[Mapping[str, Any]]
) -> None:
    retained_content_bytes = sum(int(event["content_bytes"]) for event in events)
    if (
        len(events) > EVENT_COUNT_RETENTION
        or retained_content_bytes > EVENT_CONTENT_RETENTION_BYTES
    ):
        raise RunRepositoryError("run_repository.corrupt")
    sequences = [int(event["sequence"]) for event in events]
    if sequences != sorted(set(sequences)):
        raise RunRepositoryError("run_repository.corrupt")
    if sequences and sequences != list(range(sequences[0], sequences[-1] + 1)):
        raise RunRepositoryError("run_repository.corrupt")
    if sequences and sequences[-1] != int(run["last_event_sequence"]):
        raise RunRepositoryError("run_repository.corrupt")
    if not sequences and not bool(run["timeline_truncated"]) and int(
        run["last_event_sequence"]
    ) != 0:
        raise RunRepositoryError("run_repository.corrupt")
    expected_first = sequences[0] if sequences else int(run["last_event_sequence"]) + 1
    if bool(run["timeline_truncated"]):
        if (
            int(run["first_retained_sequence"]) != expected_first
            or int(run["last_removed_sequence"]) != expected_first - 1
            or int(run["discarded_event_count"]) < int(run["last_removed_sequence"])
            or run["truncation_reason"] is None
        ):
            raise RunRepositoryError("run_repository.corrupt")
    elif (
        expected_first != 1
        or int(run["first_retained_sequence"]) != 1
        or int(run["last_removed_sequence"]) != 0
        or int(run["discarded_event_count"]) != 0
        or int(run["discarded_content_bytes"]) != 0
        or run["truncation_reason"] is not None
    ):
        raise RunRepositoryError("run_repository.corrupt")
    for event in events:
        _validate_event_row(
            event, run_id=str(run["id"]), run_status=str(run["status"])
        )


_CONSOLE_DETAIL_KEYS = frozenset(
    {
        "agent_id", "agent_name", "model", "session_id", "starts_new_session",
        "new_session_state", "transport_mode", "connection_binding_id", "usage",
        "duration_seconds", "prompt_excerpt", "prompt_truncated", "response_excerpt",
        "response_truncated", "error_excerpt", "error_truncated", "attachments",
        "artifacts",
    }
)
_TASK_DISPATCH_DETAIL_KEYS = frozenset(
    {
        "agent_id", "agent_name", "model", "provider", "transport_mode",
        "connection_binding_id", "prompt_excerpt", "prompt_truncated",
        "response_excerpt", "response_truncated", "error_excerpt",
        "error_truncated", "usage", "attachments", "artifacts", "session_id",
        "starts_new_session", "new_session_state",
    }
)


def _validated_run_details(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        details = _decode_json(
            row["details_json"], expected=dict, code="run_repository.corrupt"
        )
        if (
            _canonical_json(
                details, maximum=RUN_DETAILS_LIMIT, code="run_repository.corrupt"
            )
            != row["details_json"]
        ):
            raise RunRepositoryError("run_repository.corrupt")
        source = str(row["source"])
        expected_keys = (
            _CONSOLE_DETAIL_KEYS if source == "console" else _TASK_DISPATCH_DETAIL_KEYS
        )
        if frozenset(details) != expected_keys:
            raise RunRepositoryError("run_repository.corrupt")

        text_limits = {
            "agent_id": 128,
            "agent_name": 160,
            "model": 240,
            "prompt_excerpt": 500,
            "response_excerpt": 2_000,
            "error_excerpt": 1_000,
        }
        if source == "task_dispatch":
            text_limits["provider"] = 120
        for name, maximum in text_limits.items():
            value = details[name]
            if not isinstance(value, str) or bounded_excerpt(value, maximum)[0] != value:
                raise RunRepositoryError("run_repository.corrupt")
        for name in (
            "starts_new_session", "prompt_truncated", "response_truncated",
            "error_truncated",
        ):
            if type(details[name]) is not bool:
                raise RunRepositoryError("run_repository.corrupt")
        if details["session_id"] is not None:
            _identifier(details["session_id"])
        if details["new_session_state"] not in {None, "pending", "started", "failed"}:
            raise RunRepositoryError("run_repository.corrupt")
        if normalize_attachments(details["attachments"]) != details["attachments"]:
            raise RunRepositoryError("run_repository.corrupt")
        if normalize_artifacts(details["artifacts"]) != details["artifacts"]:
            raise RunRepositoryError("run_repository.corrupt")

        if source == "console":
            transport = normalize_transport_binding(
                details["transport_mode"],
                details["connection_binding_id"],
                legacy_default=False,
            )
            if transport != (
                details["transport_mode"], details["connection_binding_id"]
            ):
                raise RunRepositoryError("run_repository.corrupt")
            usage = details["usage"]
            if usage is not None and normalize_usage(usage) != usage:
                raise RunRepositoryError("run_repository.corrupt")
            duration = details["duration_seconds"]
            if duration is not None and (
                isinstance(duration, bool)
                or not isinstance(duration, (int, float))
                or not math.isfinite(float(duration))
                or duration < 0
            ):
                raise RunRepositoryError("run_repository.corrupt")
        elif (
            details["transport_mode"] != "runtime"
            or details["connection_binding_id"] != ""
            or details["usage"] != {}
        ):
            raise RunRepositoryError("run_repository.corrupt")
        return details
    except (TypeError, ValueError, RunRepositoryError) as exc:
        raise RunRepositoryError("run_repository.corrupt") from exc


def _validate_run_row(row: Mapping[str, Any]) -> frozenset[str]:
    try:
        if (
            str(row["source"]) not in {"console", "task_dispatch"}
            or str(row["status"]) not in _ALL_STATUSES
            or str(row["dispatch_state"]) not in _DISPATCH_STATES
            or int(row["state_revision"]) < 1
            or int(row["runtime_event_cursor"]) < 0
            or int(row["first_retained_sequence"]) < 1
            or int(row["last_removed_sequence"]) < 0
            or int(row["last_event_sequence"]) < 0
            or int(row["partial"]) not in {0, 1}
            or int(row["timeline_truncated"]) not in {0, 1}
        ):
            raise RunRepositoryError("run_repository.corrupt")
        run_id = _identifier(row["id"])
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise RunRepositoryError("run_repository.corrupt")
        _task_identifier(row["task_id"], nullable=True)
        _identifier(row["agent_id"], nullable=True)
        _identifier(row["runtime_config_id"], nullable=True)
        _identifier(row["runtime_run_ref"], nullable=True)
        runtime_type = str(row["runtime_type"])
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", runtime_type):
            raise RunRepositoryError("run_repository.corrupt")
        capabilities = _decode_json(
            row["capabilities_json"], expected=list, code="run_repository.corrupt"
        )
        if (
            any(
                not isinstance(value, str)
                or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value)
                for value in capabilities
            )
            or capabilities != sorted(set(capabilities))
            or _canonical_json(
                capabilities, maximum=8_192, code="run_repository.corrupt"
            )
            != row["capabilities_json"]
        ):
            raise RunRepositoryError("run_repository.corrupt")
        created, updated = _ordered_timestamps(row["created_at"], row["updated_at"])
        started = _timestamp(row["started_at"], nullable=True)
        completed = _timestamp(row["completed_at"], nullable=True)
        created_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
        updated_time = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if any(
            datetime.fromisoformat(value.replace("Z", "+00:00")) < created_time
            or datetime.fromisoformat(value.replace("Z", "+00:00")) > updated_time
            for value in (started, completed)
            if value is not None
        ):
            raise RunRepositoryError("run_repository.corrupt")
        if str(row["source"]) == "task_dispatch" and (
            (str(row["status"]) in _TERMINAL_STATUSES) != (completed is not None)
        ):
            raise RunRepositoryError("run_repository.corrupt")
        _validated_run_details(row)
        return frozenset(capabilities)
    except (TypeError, ValueError, RunRepositoryError) as exc:
        raise RunRepositoryError("run_repository.corrupt") from exc


def _timestamp(value: Any, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or len(value) > 64:
        raise RunRepositoryValidationError("run.timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RunRepositoryValidationError("run.timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise RunRepositoryValidationError("run.timestamp_invalid")
    return value


def _ordered_timestamps(created_at: Any, updated_at: Any) -> tuple[str, str]:
    created = _timestamp(created_at)
    updated = _timestamp(updated_at)
    if datetime.fromisoformat(created.replace("Z", "+00:00")) > datetime.fromisoformat(
        updated.replace("Z", "+00:00")
    ):
        raise RunRepositoryValidationError("run.timestamp_invalid")
    return created, updated


def _identifier(value: Any, *, event: bool = False, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    pattern = _EVENT_ID if event else _ID
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise RunRepositoryValidationError("run.identifier_invalid")
    return value


def _task_identifier(value: Any, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _TASK_ID.fullmatch(value):
        raise RunRepositoryValidationError("run.identifier_invalid")
    return value


def _canonical_event_type(source_type: str, run_status: str) -> AgentEventType:
    if source_type in {"queued", "runtime.bound", "run.created"}:
        return AgentEventType.RUN_CREATED
    if source_type == "dispatch.reserved":
        return AgentEventType.DISPATCH_RESERVED
    if source_type in {"running", "run.started"}:
        return AgentEventType.RUN_STARTED
    if source_type == "submission.unknown":
        return AgentEventType.SUBMISSION_UNKNOWN
    if source_type in {"interrupted", "run.interrupted"}:
        return AgentEventType.RUN_INTERRUPTED
    if source_type in {"tool", "tool.requested", "tool.started"}:
        return AgentEventType.TOOL_REQUESTED
    if source_type in {"tool.completed", "tool.finished"}:
        return AgentEventType.TOOL_COMPLETED
    if source_type in {"approval", "clarification", "approval.required", "clarification.required"}:
        return AgentEventType.APPROVAL_REQUIRED
    if source_type in {"artifact", "artifact.created"}:
        return AgentEventType.ARTIFACT_CREATED
    if source_type in {"cost", "usage"}:
        return AgentEventType.COST
    if source_type in {"cancelled", "stopped", "run.stopped"}:
        return AgentEventType.RUN_STOPPED
    if source_type in {"complete", "completed", "run.completed"}:
        return AgentEventType.RUN_COMPLETED
    if source_type == "runtime.finalized":
        return {
            "completed": AgentEventType.RUN_COMPLETED,
            "cancelled": AgentEventType.RUN_STOPPED,
            "stopped": AgentEventType.RUN_STOPPED,
        }.get(run_status, AgentEventType.RUN_FAILED)
    if source_type in {"error", "failed", "run.failed"} and run_status in {
        "failed",
        "interrupted",
    }:
        return AgentEventType.RUN_FAILED
    return AgentEventType.MESSAGE


def _normalized_event_type(source_type: str, run_status: str) -> AgentEventType:
    try:
        return AgentEventType(source_type)
    except ValueError:
        return _canonical_event_type(source_type, run_status)


def _event_record(run_id: str, run_status: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_events(run_id, [dict(raw)])
    if len(normalized) != 1:
        raise RunRepositoryValidationError("event.invalid")
    item = normalized[0]
    source_type = str(item["type"])
    if not _SOURCE_TYPE.fullmatch(source_type):
        raise RunRepositoryValidationError("event.invalid")
    canonical_type = _normalized_event_type(source_type, run_status)
    summary = bounded_excerpt(item.get("display_text") or "Run updated", 500)[0]
    occurred_at = _timestamp(item.get("timestamp"))
    event_id = _identifier(item.get("id"), event=True)
    sequence = item.get("sequence")
    if type(sequence) is not int or sequence < 1:
        raise RunRepositoryValidationError("event.sequence_invalid")
    data = _safe_event_data(item.get("data")) if isinstance(item.get("data"), dict) else {}
    metrics = {
        key: value
        for key, value in data.items()
        if key in {
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "context_tokens",
            "context_length",
        }
        and type(value) is int
        and 0 <= value <= 10**9
    }
    data_json = _canonical_json(data, maximum=16_384, code="event.data_invalid")
    metrics_json = _canonical_json(metrics, maximum=1_024, code="event.metrics_invalid")
    content = None
    payload = {
        "id": event_id,
        "run_id": run_id,
        "sequence": sequence,
        "event_type": canonical_type.value,
        "source_type": source_type,
        "source_key": event_id,
        "occurred_at": occurred_at,
        "summary": summary,
        "content": content,
        "metrics_json": metrics_json,
        "data_json": data_json,
    }
    digest = hashlib.sha256(
        _canonical_json(payload, maximum=32_768, code="event.invalid").encode("ascii")
    ).hexdigest()
    payload["payload_digest"] = digest
    payload["content_bytes"] = 0
    return payload


def _event_from_domain(event: AgentEvent) -> dict[str, Any]:
    summary, content, metrics_json, data_json = canonical_event_storage_fields(
        event
    )
    if len(metrics_json.encode("ascii")) > 1_024:
        raise RunRepositoryValidationError("event.metrics_invalid")
    payload = {
        "id": event.id,
        "run_id": event.run_id,
        "sequence": event.sequence,
        "event_type": event.type.value,
        "source_type": event.type.value,
        "source_key": event.id,
        "occurred_at": _timestamp(event.occurred_at),
        "summary": summary,
        "content": content,
        "metrics_json": metrics_json,
        "data_json": data_json,
    }
    digest = hashlib.sha256(
        _canonical_json(payload, maximum=32_768, code="event.invalid").encode("ascii")
    ).hexdigest()
    payload["payload_digest"] = digest
    payload["content_bytes"] = len((content or "").encode("utf-8"))
    return payload


def _validate_vercel_submission_events(outcome: SubmissionOutcome) -> None:
    events = tuple(outcome.initial_events)
    messages = [event for event in events if event.type == AgentEventType.MESSAGE]
    costs = [event for event in events if event.type == AgentEventType.COST]
    if outcome.run is None:
        raise RunRepositoryValidationError("event.vercel_submission_invalid")
    expected_message_id = "vercel_message_" + hashlib.sha256(
        (outcome.run.id + ":message").encode("utf-8")
    ).hexdigest()[:24]
    expected_cost_id = "vercel_usage_" + hashlib.sha256(
        (outcome.run.id + ":usage").encode("utf-8")
    ).hexdigest()[:24]
    if (
        len(messages) != 1
        or len(costs) > 1
        or len(events) != len(messages) + len(costs)
        or events[0] is not messages[0]
        or not re.fullmatch(r"vercel_message_[0-9a-f]{24}", messages[0].id)
        or messages[0].id != expected_message_id
        or (
            costs
            and (
                events[-1] is not costs[0]
                or not re.fullmatch(r"vercel_usage_[0-9a-f]{24}", costs[0].id)
                or costs[0].id != expected_cost_id
            )
        )
    ):
        raise RunRepositoryValidationError("event.vercel_submission_invalid")


def _details_for_run(run: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = summarize_run(dict(run))
    events = [dict(item) for item in summary.pop("events", []) if isinstance(item, dict)]
    for name in (
        "id",
        "runtime_type",
        "status",
        "partial",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "event_cursor",
        "mentat_agent_id",
        "task_id",
    ):
        summary.pop(name, None)
    return summary, events


def _exact_schema_three_events(run_id: str, raw_events: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw_events, list):
        return None
    result: list[dict[str, Any]] = []
    last_sequence = 0
    seen_ids: set[str] = set()
    for item in raw_events:
        if not isinstance(item, dict):
            return None
        event_id = item.get("id")
        sequence = item.get("sequence")
        if (
            item.get("schema_version") != 1
            or item.get("run_id") != run_id
            or type(sequence) is not int
            or sequence <= last_sequence
            or item.get("cursor") != sequence
            or not isinstance(event_id, str)
            or not _EVENT_ID.fullmatch(event_id)
            or event_id in seen_ids
            or not isinstance(item.get("timestamp"), str)
            or not _SOURCE_TYPE.fullmatch(str(item.get("type") or ""))
        ):
            return None
        try:
            _timestamp(item["timestamp"])
        except RunRepositoryValidationError:
            return None
        result.append(dict(item))
        seen_ids.add(event_id)
        last_sequence = sequence
    return result


def _newest_contiguous_event_suffix(
    events: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep exact newest evidence without inventing a missing legacy prefix."""

    if not events:
        return []
    suffix = [dict(events[-1])]
    expected = int(events[-1]["sequence"]) - 1
    for item in reversed(events[:-1]):
        sequence = int(item["sequence"])
        if sequence != expected:
            break
        suffix.append(dict(item))
        expected -= 1
    suffix.reverse()
    return suffix


class RunRepository:
    """Transaction-friendly repository over one migrated Mentat connection."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self._require_schema()

    def _require_schema(self) -> None:
        try:
            version = int(
                self.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                or 0
            )
            names = {
                str(row[0])
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        except (sqlite3.Error, TypeError, ValueError) as exc:
            raise RunRepositoryError("run_repository.schema_unsupported") from exc
        if (
            version not in {RUN_SCHEMA_VERSION, 8, 9, DATABASE_SCHEMA_VERSION}
            or not _RUN_SCHEMA_OBJECTS.issubset(names)
            or _run_schema_fingerprint(self.connection)
            != _expected_run_schema_fingerprint(version)
        ):
            raise RunRepositoryError("run_repository.schema_unsupported")

    @contextmanager
    def mutation(self) -> Iterator[None]:
        nested = self.connection.in_transaction
        if nested:
            self.connection.execute("SAVEPOINT mentat_run_repository")
        else:
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._require_schema()
            yield
            self._validate_temporal_integrity()
            self._enforce_store_budget()
        except Exception:
            if nested:
                self.connection.execute("ROLLBACK TO mentat_run_repository")
                self.connection.execute("RELEASE mentat_run_repository")
            else:
                self.connection.rollback()
            raise
        else:
            if nested:
                self.connection.execute("RELEASE mentat_run_repository")
            else:
                self.connection.commit()

    def _validate_temporal_integrity(self) -> None:
        try:
            for row in self.connection.execute(
                "SELECT created_at, updated_at, started_at, completed_at FROM mentat_runs"
            ):
                created, updated = _ordered_timestamps(row[0], row[1])
                created_time = datetime.fromisoformat(created.replace("Z", "+00:00"))
                updated_time = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                for value in (row[2], row[3]):
                    timestamp = _timestamp(value, nullable=True)
                    if timestamp is None:
                        continue
                    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if parsed < created_time or parsed > updated_time:
                        raise RunRepositoryValidationError("run.timestamp_invalid")
            for row in self.connection.execute(
                "SELECT created_at, updated_at FROM mentat_dispatch_reservations"
            ):
                _ordered_timestamps(row[0], row[1])
            for row in self.connection.execute(
                "SELECT updated_at FROM mentat_task_dispatch_heads"
            ):
                _timestamp(row[0])
        except (TypeError, ValueError, sqlite3.Error, RunRepositoryError) as exc:
            raise RunRepositoryValidationError("run.timestamp_invalid") from exc

    def _enforce_store_budget(self) -> None:
        page_size = int(self.connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(self.connection.execute("PRAGMA page_count").fetchone()[0])
        if page_size * page_count > RUN_STORE_DATABASE_BUDGET:
            raise RunRepositoryValidationError("run.capacity_exceeded")

    def _ensure_run_capacity(self, incoming_ids: Iterable[str]) -> None:
        identifiers = tuple(dict.fromkeys(_identifier(value) for value in incoming_ids))
        if not identifiers:
            return
        placeholders = ",".join("?" for _ in identifiers)
        existing = int(
            self.connection.execute(
                f"SELECT COUNT(*) FROM mentat_runs WHERE id IN ({placeholders})",
                identifiers,
            ).fetchone()[0]
        )
        current = int(self.connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0])
        excess = current + len(identifiers) - existing - MAX_SOURCE_RUNS
        if excess <= 0:
            return
        terminal = self.connection.execute(
            "SELECT id FROM mentat_runs WHERE status NOT IN ("
            + ",".join("?" for _ in _ACTIVE_STATUSES)
            + ") ORDER BY completed_at, created_at, id LIMIT ?",
            (*tuple(sorted(_ACTIVE_STATUSES)), excess),
        ).fetchall()
        for row in terminal:
            run_id = str(row[0])
            self.connection.execute("DELETE FROM run_attachments WHERE run_id = ?", (run_id,))
            self.connection.execute("DELETE FROM mentat_runs WHERE id = ?", (run_id,))
        if len(terminal) != excess:
            raise RunRepositoryValidationError("run.capacity_exceeded")

    def authority_receipt(self, *, required: bool = False) -> RunAuthorityReceipt | None:
        rows = self.connection.execute(
            "SELECT authority, migration_contract, source_sha256, source_run_count, cutover_at "
            "FROM mentat_run_store_state WHERE singleton = 1"
        ).fetchall()
        if not rows:
            if required:
                raise RunRepositoryUnavailable("run_repository.authority_missing")
            return None
        if len(rows) != 1:
            raise RunRepositoryError("run_repository.corrupt")
        row = rows[0]
        digest = str(row["source_sha256"])
        count = int(row["source_run_count"])
        cutover_at = float(row["cutover_at"])
        if (
            row["authority"] != "sqlite"
            or row["migration_contract"] != RUN_AUTHORITY_CONTRACT
            or not _SHA256.fullmatch(digest)
            or not 0 <= count <= MAX_SOURCE_RUNS
            or not math.isfinite(cutover_at)
            or cutover_at <= 0
        ):
            raise RunRepositoryError("run_repository.corrupt")
        return RunAuthorityReceipt(digest, count, cutover_at)

    @staticmethod
    def _reservation(row: Mapping[str, Any], *, duplicate: bool = False) -> DispatchReservation:
        return DispatchReservation(
            dispatch_id=str(row["dispatch_id"]),
            run_id=str(row["run_id"]),
            task_id=str(row["task_id"]),
            task_revision=int(row["task_revision"]),
            request_digest=str(row["request_digest"]),
            runtime_binding_digest=str(row["runtime_binding_digest"]),
            state=str(row["state"]),
            attempt_count=int(row["attempt_count"]),
            duplicate=duplicate,
        )

    @staticmethod
    def _run_record(row: Mapping[str, Any]) -> RunRecord:
        _validate_run_row(row)
        return RunRecord(
            id=str(row["id"]),
            source=str(row["source"]),
            task_id=str(row["task_id"]) if row["task_id"] is not None else None,
            task_revision=int(row["task_revision"]) if row["task_revision"] is not None else None,
            agent_id=str(row["agent_id"]) if row["agent_id"] is not None else None,
            runtime_type=str(row["runtime_type"]),
            runtime_config_id=(
                str(row["runtime_config_id"]) if row["runtime_config_id"] is not None else None
            ),
            runtime_binding_digest=(
                str(row["runtime_binding_digest"])
                if row["runtime_binding_digest"] is not None
                else None
            ),
            runtime_run_ref=(
                str(row["runtime_run_ref"]) if row["runtime_run_ref"] is not None else None
            ),
            runtime_event_cursor=int(row["runtime_event_cursor"]),
            status=str(row["status"]),
            dispatch_state=str(row["dispatch_state"]),
            state_revision=int(row["state_revision"]),
            partial=bool(row["partial"]),
            timeline_truncated=bool(row["timeline_truncated"]),
            first_retained_sequence=int(row["first_retained_sequence"]),
            last_removed_sequence=int(row["last_removed_sequence"]),
            last_event_sequence=int(row["last_event_sequence"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            started_at=str(row["started_at"]) if row["started_at"] is not None else None,
            completed_at=(
                str(row["completed_at"]) if row["completed_at"] is not None else None
            ),
        )

    def _get_run_record(self, run_id: str) -> RunRecord:
        identifier = _identifier(run_id)
        row = self.connection.execute(
            "SELECT * FROM mentat_runs WHERE id = ?", (identifier,)
        ).fetchone()
        if row is None:
            raise RunRepositoryConflict("run.not_found")
        _validate_event_window(row, self._event_rows(identifier))
        return self._run_record(row)

    def get_run(self, run_id: str) -> RunRecord:
        return self._get_run_record(run_id)

    def list_runs(
        self,
        *,
        limit: int = 50,
        before: tuple[str, str] | None = None,
    ) -> tuple[RunRecord, ...]:
        """Return one deterministic newest-first page without private payloads."""

        # Public pages are capped at 100; one extra row is allowed internally
        # to calculate a deterministic continuation cursor.
        if type(limit) is not int or not 1 <= limit <= 101:
            raise RunRepositoryValidationError("run.limit_invalid")
        parameters: list[Any] = []
        where = ""
        if before is not None:
            if (
                not isinstance(before, tuple)
                or len(before) != 2
                or not isinstance(before[0], str)
                or not isinstance(before[1], str)
            ):
                raise RunRepositoryValidationError("run.cursor_invalid")
            timestamp = _timestamp(before[0])
            identifier = _identifier(before[1])
            where = "WHERE updated_at < ? OR (updated_at = ? AND id < ?)"
            parameters.extend((timestamp, timestamp, identifier))
        rows = self.connection.execute(
            f"SELECT * FROM mentat_runs {where} "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            (*parameters, limit),
        ).fetchall()
        records: list[RunRecord] = []
        for row in rows:
            _validate_event_window(row, self._event_rows(str(row["id"])))
            records.append(self._run_record(row))
        return tuple(records)

    def list_workspace_runs(self, *, limit: int = 50) -> tuple[RunRecord, ...]:
        """Return a bounded workspace view with active Runs before history."""

        if type(limit) is not int or not 1 <= limit <= 100:
            raise RunRepositoryValidationError("run.limit_invalid")
        statuses = tuple(sorted(_ACTIVE_STATUSES))
        placeholders = ",".join("?" for _ in statuses)
        rows = self.connection.execute(
            "SELECT * FROM mentat_runs "
            f"ORDER BY CASE WHEN status IN ({placeholders}) THEN 0 ELSE 1 END, "
            "updated_at DESC, id DESC LIMIT ?",
            (*statuses, limit),
        ).fetchall()
        records: list[RunRecord] = []
        for row in rows:
            _validate_event_window(row, self._event_rows(str(row["id"])))
            records.append(self._run_record(row))
        return tuple(records)

    def lookup_dispatch_retry(
        self,
        *,
        idempotency_key: str,
        task_id: str,
        task_revision: int,
    ) -> DispatchReservation | None:
        """Resolve an exact durable retry without consulting mutable Task state."""

        try:
            encoded = idempotency_key.encode("utf-8")
        except (AttributeError, UnicodeEncodeError):
            encoded = b""
        if not 16 <= len(encoded) <= 256 or b"\x00" in encoded:
            raise RunRepositoryValidationError("dispatch.idempotency_key_invalid")
        if type(task_revision) is not int or task_revision < 1:
            raise RunRepositoryValidationError("dispatch.revision_invalid")
        key_digest = hashlib.sha256(encoded).hexdigest()
        row = self.connection.execute(
            "SELECT * FROM mentat_dispatch_reservations WHERE key_digest = ?",
            (key_digest,),
        ).fetchone()
        if row is None:
            return None
        if (
            str(row["task_id"]) != _task_identifier(task_id)
            or int(row["task_revision"]) != task_revision
        ):
            raise RunRepositoryConflict("dispatch.idempotency_conflict")
        return self._reservation(row, duplicate=True)

    def reserve_dispatch(
        self,
        *,
        idempotency_key: str,
        dispatch_id: str,
        run_id: str,
        task: Mapping[str, Any],
        task_revision: int,
        agent_id: str,
        runtime_type: str,
        runtime_config_id: str,
        binding_digest: str,
        capabilities: Iterable[str],
        now: str | None = None,
    ) -> DispatchReservation:
        try:
            idempotency_size = len(idempotency_key.encode("utf-8"))
        except (AttributeError, UnicodeEncodeError):
            idempotency_size = 0
        if (
            not isinstance(idempotency_key, str)
            or not 16 <= idempotency_size <= 256
            or "\x00" in idempotency_key
        ):
            raise RunRepositoryValidationError("dispatch.idempotency_key_invalid")
        dispatch_identifier = _identifier(dispatch_id)
        run_identifier = _identifier(run_id)
        if not isinstance(run_identifier, str) or not _RUN_ID.fullmatch(run_identifier):
            raise RunRepositoryValidationError("run.identifier_invalid")
        task_id = _task_identifier(task.get("id"))
        agent_identifier = _identifier(agent_id)
        config_identifier = _identifier(runtime_config_id)
        if type(task_revision) is not int or task_revision < 1:
            raise RunRepositoryValidationError("dispatch.revision_invalid")
        if not _SHA256.fullmatch(binding_digest):
            raise RunRepositoryValidationError("dispatch.binding_invalid")
        capability_values = sorted(set(str(value) for value in capabilities))
        capabilities_json = _canonical_json(
            capability_values, maximum=8_192, code="dispatch.capabilities_invalid"
        )
        task_snapshot = {
            key: task.get(key)
            for key in (
                "id",
                "title",
                "description",
                "status",
                "assigned_agent_id",
                "required_capabilities",
                "acceptance_criteria",
            )
            if key in task
        }
        task_json = _canonical_json(
            task_snapshot,
            maximum=TASK_SNAPSHOT_LIMIT,
            code="dispatch.task_invalid",
        )
        request_digest = dispatch_request_digest(
            task=task_snapshot,
            task_revision=task_revision,
            agent_id=agent_identifier,
            runtime_type=runtime_type,
            runtime_config_id=config_identifier,
            capabilities=capability_values,
        )
        key_digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            self.authority_receipt(required=True)
            existing = self.connection.execute(
                "SELECT * FROM mentat_dispatch_reservations WHERE key_digest = ?",
                (key_digest,),
            ).fetchone()
            if existing is not None:
                if str(existing["request_digest"]) != request_digest:
                    raise RunRepositoryConflict("dispatch.idempotency_conflict")
                return self._reservation(existing, duplicate=True)
            self._apply_retention()
            self._ensure_run_capacity((run_identifier,))
            task_row = self.connection.execute(
                "SELECT revision, assigned_agent_id FROM mentat_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if task_row is None:
                raise RunRepositoryConflict("dispatch.task_not_found")
            if int(task_row["revision"]) != task_revision:
                raise RunRepositoryConflict("dispatch.task_changed")
            if str(task_row["assigned_agent_id"] or "") != agent_identifier:
                raise RunRepositoryConflict("dispatch.agent_changed")
            head = self.connection.execute(
                "SELECT * FROM mentat_task_dispatch_heads WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if head is not None and int(head["task_revision"]) == task_revision:
                raise RunRepositoryConflict("dispatch.task_revision_consumed")
            active = self.connection.execute(
                "SELECT id FROM mentat_runs WHERE task_id = ? AND status IN ("
                + ",".join("?" for _ in _ACTIVE_STATUSES)
                + ") LIMIT 1",
                (task_id, *tuple(sorted(_ACTIVE_STATUSES))),
            ).fetchone()
            if active is not None:
                raise RunRepositoryConflict("dispatch.task_active")
            details = {
                "agent_id": "",
                "agent_name": "",
                "model": "",
                "provider": "",
                "transport_mode": "runtime",
                "connection_binding_id": "",
                "prompt_excerpt": bounded_excerpt(task.get("description") or task.get("title"), 500)[0],
                "prompt_truncated": False,
                "response_excerpt": "",
                "response_truncated": False,
                "error_excerpt": "",
                "error_truncated": False,
                "usage": {},
                "attachments": [],
                "artifacts": [],
                "session_id": None,
                "starts_new_session": False,
                "new_session_state": None,
            }
            details_json = _canonical_json(details, maximum=RUN_DETAILS_LIMIT, code="run.details_invalid")
            try:
                self.connection.execute(
                    """
                    INSERT INTO mentat_runs (
                        id, source, task_id, task_revision, task_snapshot_json,
                        agent_id, runtime_type, runtime_config_id,
                        runtime_binding_digest, capabilities_json, status,
                        dispatch_state, details_json, created_at, updated_at
                    ) VALUES (?, 'task_dispatch', ?, ?, ?, ?, ?, ?, ?, ?,
                              'reserved', 'reserved', ?, ?, ?)
                    """,
                    (
                        run_identifier,
                        task_id,
                        task_revision,
                        task_json,
                        agent_identifier,
                        runtime_type,
                        config_identifier,
                        binding_digest,
                        capabilities_json,
                        details_json,
                        occurred_at,
                        occurred_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                active = self.connection.execute(
                    "SELECT 1 FROM mentat_runs WHERE task_id = ? AND status IN ("
                    + ",".join("?" for _ in _ACTIVE_STATUSES)
                    + ") LIMIT 1",
                    (task_id, *tuple(sorted(_ACTIVE_STATUSES))),
                ).fetchone()
                if active is not None:
                    raise RunRepositoryConflict("dispatch.task_active") from exc
                raise RunRepositoryUnavailable("run_repository.unavailable") from exc
            expires_at = time.time() + IDEMPOTENCY_RETENTION_SECONDS
            self.connection.execute(
                """
                INSERT INTO mentat_dispatch_reservations (
                    key_digest, dispatch_id, request_digest, run_id, task_id,
                    task_revision, runtime_binding_digest, state, attempt_count,
                    created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'reserved', 0, ?, ?, ?)
                """,
                (
                    key_digest,
                    dispatch_identifier,
                    request_digest,
                    run_identifier,
                    task_id,
                    task_revision,
                    binding_digest,
                    occurred_at,
                    occurred_at,
                    expires_at,
                ),
            )
            self.connection.execute(
                """
                INSERT INTO mentat_task_dispatch_heads (
                    task_id, task_revision, request_digest, run_id, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    task_revision = excluded.task_revision,
                    request_digest = excluded.request_digest,
                    run_id = excluded.run_id,
                    updated_at = excluded.updated_at
                """,
                (task_id, task_revision, request_digest, run_identifier, occurred_at),
            )
            self._append_event_record(
                _event_from_domain(
                    AgentEvent(
                        id=(
                            "event_"
                            + hashlib.sha256(
                                f"{dispatch_identifier}:reserved".encode("utf-8")
                            ).hexdigest()[:32]
                        ),
                        run_id=run_identifier,
                        sequence=1,
                        type=AgentEventType.DISPATCH_RESERVED,
                        occurred_at=occurred_at,
                        summary="Dispatch reserved",
                    )
                )
            )
            self._apply_retention()
            row = self.connection.execute(
                "SELECT * FROM mentat_dispatch_reservations WHERE key_digest = ?",
                (key_digest,),
            ).fetchone()
            return self._reservation(row)

    def claim_dispatch_attempt(
        self,
        *,
        dispatch_id: str,
        expected_binding_digest: str,
        now: str | None = None,
    ) -> DispatchReservation:
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            row = self.connection.execute(
                "SELECT * FROM mentat_dispatch_reservations WHERE dispatch_id = ?",
                (_identifier(dispatch_id),),
            ).fetchone()
            if row is None:
                raise RunRepositoryConflict("dispatch.not_found")
            if str(row["runtime_binding_digest"]) != expected_binding_digest:
                raise RunRepositoryConflict("dispatch.binding_changed")
            if str(row["state"]) != "reserved" or int(row["attempt_count"]) != 0:
                raise RunRepositoryConflict("dispatch.attempt_already_claimed")
            task_state = self.connection.execute(
                "SELECT t.revision, t.assigned_agent_id, r.task_id, "
                "r.task_revision, r.agent_id FROM mentat_runs r "
                "LEFT JOIN mentat_tasks t ON t.id = r.task_id WHERE r.id = ?",
                (row["run_id"],),
            ).fetchone()
            if (
                task_state is None
                or task_state["revision"] is None
                or int(task_state["revision"]) != int(row["task_revision"])
                or int(task_state["task_revision"]) != int(row["task_revision"])
                or str(task_state["task_id"]) != str(row["task_id"])
                or str(task_state["assigned_agent_id"] or "")
                != str(task_state["agent_id"] or "")
            ):
                raise RunRepositoryConflict("dispatch.task_changed")
            updated = self.connection.execute(
                "UPDATE mentat_dispatch_reservations SET state = 'submitting', "
                "attempt_count = 1, updated_at = ? WHERE dispatch_id = ? "
                "AND state = 'reserved' AND attempt_count = 0",
                (occurred_at, dispatch_id),
            ).rowcount
            run_updated = self.connection.execute(
                "UPDATE mentat_runs SET status = 'submitting', dispatch_state = 'submitting', "
                "state_revision = state_revision + 1, updated_at = ? WHERE id = ? "
                "AND status = 'reserved' AND dispatch_state = 'reserved'",
                (occurred_at, row["run_id"]),
            ).rowcount
            if updated != 1 or run_updated != 1:
                raise RunRepositoryConflict("dispatch.state_changed")
            claimed = self.connection.execute(
                "SELECT * FROM mentat_dispatch_reservations WHERE dispatch_id = ?",
                (dispatch_id,),
            ).fetchone()
            return self._reservation(claimed)

    def reject_reserved_dispatch(
        self,
        *,
        dispatch_id: str,
        failure_code: str,
        now: str | None = None,
    ) -> RunRecord:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", failure_code):
            raise RunRepositoryValidationError("dispatch.failure_invalid")
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            reservation = self.connection.execute(
                "SELECT * FROM mentat_dispatch_reservations WHERE dispatch_id = ?",
                (_identifier(dispatch_id),),
            ).fetchone()
            if reservation is None or reservation["state"] != "reserved" or int(reservation["attempt_count"]) != 0:
                raise RunRepositoryConflict("dispatch.state_changed")
            self.connection.execute(
                "UPDATE mentat_dispatch_reservations SET state = 'rejected', updated_at = ? "
                "WHERE dispatch_id = ?",
                (occurred_at, dispatch_id),
            )
            self.connection.execute(
                "UPDATE mentat_runs SET status = 'failed', dispatch_state = 'rejected', "
                "state_revision = state_revision + 1, partial = 0, updated_at = ?, "
                "completed_at = ? WHERE id = ?",
                (occurred_at, occurred_at, reservation["run_id"]),
            )
            self._append_next_lifecycle_event(
                str(reservation["run_id"]),
                event_type=AgentEventType.RUN_FAILED,
                occurred_at=occurred_at,
                summary="Dispatch rejected",
                source_key=f"dispatch:{dispatch_id}:rejected:{failure_code}",
            )
            self._apply_retention()
            return self.get_run(str(reservation["run_id"]))

    def record_submission_outcome(
        self,
        *,
        dispatch_id: str,
        outcome: SubmissionOutcome,
        now: str | None = None,
    ) -> RunRecord:
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            reservation = self.connection.execute(
                "SELECT * FROM mentat_dispatch_reservations WHERE dispatch_id = ?",
                (_identifier(dispatch_id),),
            ).fetchone()
            if reservation is None:
                raise RunRepositoryConflict("dispatch.not_found")
            if reservation["state"] != "submitting" or int(reservation["attempt_count"]) != 1:
                raise RunRepositoryConflict("dispatch.state_changed")
            run_id = str(reservation["run_id"])
            current = self.connection.execute(
                "SELECT * FROM mentat_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if current is None or str(current["dispatch_state"]) != "submitting":
                raise RunRepositoryConflict("dispatch.state_changed")
            current_status = str(current["status"])
            current_revision = int(current["state_revision"])
            if outcome.disposition == SubmissionDisposition.ACCEPTED:
                if (
                    outcome.run is None
                    or outcome.run.id != run_id
                    or outcome.run.task_id != current["task_id"]
                    or outcome.run.agent_id != current["agent_id"]
                    or outcome.run.runtime_type != current["runtime_type"]
                ):
                    raise RunRepositoryConflict("dispatch.runtime_identity_mismatch")
                if str(current["runtime_type"]) == "vercel":
                    _validate_vercel_submission_events(outcome)
                observed_status = outcome.run.status.value
                if (
                    observed_status not in _ALL_STATUSES
                    or observed_status in {"reserved", "submitting", "unknown"}
                ):
                    observed_status = "starting"
                # The transitional bridge can advance the canonical Run before
                # its handler returns. Acceptance may confirm dispatch state,
                # but it must never regress that already-observed Run state.
                next_status = (
                    observed_status if current_status == "submitting" else current_status
                )
                reservation_state = "accepted"
                dispatch_state = "accepted"
                partial = 0
                event_type = AgentEventType.RUN_STARTED
                summary = "Runtime accepted dispatch"
            elif outcome.disposition == SubmissionDisposition.REJECTED:
                if current_status == "submitting":
                    next_status = "failed"
                    reservation_state = "rejected"
                    dispatch_state = "rejected"
                    partial = 0
                    event_type = AgentEventType.RUN_FAILED
                    summary = "Runtime rejected dispatch"
                else:
                    next_status = current_status
                    reservation_state = "unknown"
                    dispatch_state = "unknown"
                    partial = 1
                    event_type = AgentEventType.SUBMISSION_UNKNOWN
                    summary = "Runtime submission outcome conflicts with observed progress"
            else:
                next_status = "unknown" if current_status == "submitting" else current_status
                reservation_state = "unknown"
                dispatch_state = "unknown"
                partial = 1
                event_type = AgentEventType.SUBMISSION_UNKNOWN
                summary = "Runtime submission outcome is unknown"
            terminal_at = occurred_at if next_status in _TERMINAL_STATUSES else None
            reservation_updated = self.connection.execute(
                "UPDATE mentat_dispatch_reservations SET state = ?, updated_at = ? "
                "WHERE dispatch_id = ? AND state = 'submitting' AND attempt_count = 1",
                (reservation_state, occurred_at, dispatch_id),
            ).rowcount
            run_updated = self.connection.execute(
                "UPDATE mentat_runs SET status = ?, dispatch_state = ?, partial = ?, "
                "runtime_run_ref = ?, state_revision = state_revision + 1, "
                "updated_at = ?, started_at = CASE WHEN ? = 'accepted' "
                "THEN COALESCE(started_at, ?) ELSE started_at END, "
                "completed_at = COALESCE(completed_at, ?) WHERE id = ? "
                "AND dispatch_state = 'submitting' AND status = ? AND state_revision = ?",
                (
                    next_status,
                    dispatch_state,
                    partial,
                    outcome.runtime_run_ref,
                    occurred_at,
                    reservation_state,
                    occurred_at,
                    terminal_at,
                    run_id,
                    current_status,
                    current_revision,
                ),
            ).rowcount
            if reservation_updated != 1 or run_updated != 1:
                raise RunRepositoryConflict("dispatch.state_changed")
            self._append_next_lifecycle_event(
                run_id,
                event_type=event_type,
                occurred_at=occurred_at,
                summary=summary,
                source_key=f"dispatch:{dispatch_id}:{reservation_state}",
            )
            if reservation_state == "accepted":
                for source_event in outcome.initial_events:
                    row = self.connection.execute(
                        "SELECT last_event_sequence FROM mentat_runs WHERE id = ?",
                        (run_id,),
                    ).fetchone()
                    if row is None:
                        raise RunRepositoryConflict("run.not_found")
                    record = dict(_event_from_domain(source_event))
                    source_key = f"submission:{source_event.id}"
                    record["id"] = (
                        "event_"
                        + hashlib.sha256(
                            (run_id + ":" + source_event.id).encode("utf-8")
                        ).hexdigest()[:24]
                    )
                    record["sequence"] = int(row[0]) + 1
                    record["source_key"] = source_key
                    digest_payload = {
                        key: record[key]
                        for key in (
                            "id", "run_id", "sequence", "event_type",
                            "source_type", "source_key", "occurred_at",
                            "summary", "content", "metrics_json", "data_json",
                        )
                    }
                    record["payload_digest"] = hashlib.sha256(
                        _canonical_json(
                            digest_payload,
                            maximum=32_768,
                            code="event.invalid",
                        ).encode("ascii")
                    ).hexdigest()
                    self._append_event_record(record)
            terminal_event = {
                "completed": AgentEventType.RUN_COMPLETED,
                "failed": AgentEventType.RUN_FAILED,
                "stopped": AgentEventType.RUN_STOPPED,
                "interrupted": AgentEventType.RUN_INTERRUPTED,
            }.get(next_status)
            if terminal_event is not None and terminal_event != event_type:
                terminal_exists = self.connection.execute(
                    "SELECT 1 FROM mentat_agent_events WHERE run_id = ? "
                    "AND event_type = ? LIMIT 1",
                    (run_id, terminal_event.value),
                ).fetchone()
                if terminal_exists is None:
                    self._append_next_lifecycle_event(
                        run_id,
                        event_type=terminal_event,
                        occurred_at=occurred_at,
                        summary=f"Run {next_status}",
                        source_key=f"dispatch:{dispatch_id}:terminal:{next_status}",
                    )
            self._apply_retention()
            return self.get_run(run_id)

    def _append_next_lifecycle_event(
        self,
        run_id: str,
        *,
        event_type: AgentEventType,
        occurred_at: str,
        summary: str,
        source_key: str,
    ) -> None:
        row = self.connection.execute(
            "SELECT last_event_sequence FROM mentat_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RunRepositoryConflict("run.not_found")
        sequence = int(row[0]) + 1
        event = AgentEvent(
            id=f"event_{hashlib.sha256(source_key.encode('utf-8')).hexdigest()[:24]}",
            run_id=run_id,
            sequence=sequence,
            type=event_type,
            occurred_at=occurred_at,
            summary=summary,
        )
        record = _event_from_domain(event)
        # The deterministic event ID is the durable idempotency key. Keep the
        # richer correlation input private to ID derivation so compatibility
        # projections can round-trip without exposing or duplicating it.
        record["source_key"] = record["id"]
        digest_payload = {
            key: record[key]
            for key in (
                "id",
                "run_id",
                "sequence",
                "event_type",
                "source_type",
                "source_key",
                "occurred_at",
                "summary",
                "content",
                "metrics_json",
                "data_json",
            )
        }
        record["payload_digest"] = hashlib.sha256(
            _canonical_json(digest_payload, maximum=32_768, code="event.invalid").encode("ascii")
        ).hexdigest()
        self._append_event_record(record)

    def recover_reserved_as_interrupted(
        self, *, now: str | None = None
    ) -> tuple[str, ...]:
        """Resolve durable intent that crashed before any external attempt."""

        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            rows = self.connection.execute(
                "SELECT dispatch_id, run_id FROM mentat_dispatch_reservations "
                "WHERE state = 'reserved' AND attempt_count = 0 ORDER BY dispatch_id"
            ).fetchall()
            recovered: list[str] = []
            for row in rows:
                dispatch_id = str(row["dispatch_id"])
                run_id = str(row["run_id"])
                reservation_updated = self.connection.execute(
                    "UPDATE mentat_dispatch_reservations SET state = 'rejected', updated_at = ? "
                    "WHERE dispatch_id = ? AND state = 'reserved' AND attempt_count = 0",
                    (occurred_at, dispatch_id),
                ).rowcount
                run_updated = self.connection.execute(
                    "UPDATE mentat_runs SET status = 'interrupted', "
                    "dispatch_state = 'rejected', partial = 1, "
                    "state_revision = state_revision + 1, updated_at = ?, completed_at = ? "
                    "WHERE id = ? AND status = 'reserved' AND dispatch_state = 'reserved'",
                    (occurred_at, occurred_at, run_id),
                ).rowcount
                if reservation_updated != 1 or run_updated != 1:
                    raise RunRepositoryConflict("dispatch.state_changed")
                self._append_next_lifecycle_event(
                    run_id,
                    event_type=AgentEventType.RUN_INTERRUPTED,
                    occurred_at=occurred_at,
                    summary="Mentat restarted before runtime submission",
                    source_key=f"dispatch:{dispatch_id}:restart-before-submit",
                )
                recovered.append(run_id)
            self._apply_retention()
            return tuple(recovered)

    def recover_submitting_as_unknown(self, *, now: str | None = None) -> tuple[str, ...]:
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            rows = self.connection.execute(
                "SELECT dispatch_id, run_id FROM mentat_dispatch_reservations "
                "WHERE state = 'submitting' AND attempt_count = 1 ORDER BY dispatch_id"
            ).fetchall()
            recovered: list[str] = []
            for row in rows:
                dispatch_id = str(row["dispatch_id"])
                run_id = str(row["run_id"])
                current = self.connection.execute(
                    "SELECT status, dispatch_state, partial FROM mentat_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
                if current is None or str(current["dispatch_state"]) != "submitting":
                    raise RunRepositoryError("run_repository.corrupt")
                current_status = str(current["status"])
                if current_status == "submitting":
                    reservation_state = "unknown"
                    next_status = "unknown"
                    next_partial = 1
                elif current_status in _ALL_STATUSES:
                    # A worker-authored state beyond `submitting` is durable
                    # evidence that the adapter accepted the preallocated Run.
                    reservation_state = "accepted"
                    next_status = current_status
                    next_partial = int(current["partial"])
                else:
                    raise RunRepositoryError("run_repository.corrupt")
                reservation_updated = self.connection.execute(
                    "UPDATE mentat_dispatch_reservations SET state = ?, updated_at = ? "
                    "WHERE dispatch_id = ? AND state = 'submitting' AND attempt_count = 1",
                    (reservation_state, occurred_at, dispatch_id),
                ).rowcount
                run_updated = self.connection.execute(
                    "UPDATE mentat_runs SET status = ?, dispatch_state = ?, partial = ?, "
                    "state_revision = state_revision + 1, updated_at = ? "
                    "WHERE id = ? AND status = ? AND dispatch_state = 'submitting'",
                    (
                        next_status,
                        reservation_state,
                        next_partial,
                        occurred_at,
                        run_id,
                        current_status,
                    ),
                ).rowcount
                if reservation_updated != 1 or run_updated != 1:
                    raise RunRepositoryConflict("dispatch.state_changed")
                if reservation_state == "unknown":
                    self._append_next_lifecycle_event(
                        run_id,
                        event_type=AgentEventType.SUBMISSION_UNKNOWN,
                        occurred_at=occurred_at,
                        summary="Mentat restarted during runtime submission",
                        source_key=f"dispatch:{dispatch_id}:restart-unknown",
                    )
                recovered.append(run_id)
            self._apply_retention()
            return tuple(recovered)

    def recover_unattached_dispatches_as_unknown(
        self, *, now: str | None = None
    ) -> tuple[str, ...]:
        """Fail honest across restart when the transitional bridge cannot reattach."""

        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            rows = self.connection.execute(
                "SELECT id FROM mentat_runs WHERE source = 'task_dispatch' "
                "AND dispatch_state = 'accepted' "
                "AND runtime_run_ref IS NULL "
                "AND status IN ('queued', 'starting', 'running', 'cancelling', 'waiting', "
                "'waiting_for_approval', 'waiting_for_clarification') ORDER BY id"
            ).fetchall()
            recovered: list[str] = []
            for row in rows:
                run_id = str(row["id"])
                self.connection.execute(
                    "UPDATE mentat_runs SET status = 'unknown', dispatch_state = 'unknown', "
                    "partial = 1, state_revision = state_revision + 1, updated_at = ? "
                    "WHERE id = ? AND dispatch_state = 'accepted'",
                    (occurred_at, run_id),
                )
                self.connection.execute(
                    "UPDATE mentat_dispatch_reservations SET state = 'unknown', updated_at = ? "
                    "WHERE run_id = ? AND state = 'accepted'",
                    (occurred_at, run_id),
                )
                self._append_next_lifecycle_event(
                    run_id,
                    event_type=AgentEventType.SUBMISSION_UNKNOWN,
                    occurred_at=occurred_at,
                    summary="Runtime state could not be reattached after restart",
                    source_key=f"restart:{run_id}:unattached",
                )
                recovered.append(run_id)
            self._apply_retention()
            return tuple(recovered)

    def abandon_unknown_vercel_run(
        self,
        run_id: str,
        *,
        expected_state_revision: int,
        now: str | None = None,
    ) -> RunRecord:
        """Terminalize one explicitly confirmed ambiguous one-shot request."""

        identifier = _identifier(run_id)
        if type(expected_state_revision) is not int or expected_state_revision < 1:
            raise RunRepositoryValidationError("run.state_revision_invalid")
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            self.authority_receipt(required=True)
            row = self.connection.execute(
                "SELECT * FROM mentat_runs WHERE id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise RunRepositoryConflict("run.not_found")
            _validate_run_row(row)
            reservation = self.connection.execute(
                "SELECT dispatch_id, state, attempt_count FROM "
                "mentat_dispatch_reservations WHERE run_id = ?",
                (identifier,),
            ).fetchone()
            if (
                str(row["source"]) != "task_dispatch"
                or str(row["runtime_type"]) != "vercel"
                or str(row["status"]) != "unknown"
                or str(row["dispatch_state"]) != "unknown"
                or row["runtime_run_ref"] is not None
                or int(row["state_revision"]) != expected_state_revision
                or reservation is None
                or str(reservation["state"]) != "unknown"
                or int(reservation["attempt_count"]) != 1
            ):
                raise RunRepositoryConflict("run.recovery_state_changed")
            updated = self.connection.execute(
                "UPDATE mentat_runs SET status = 'interrupted', partial = 1, "
                "state_revision = state_revision + 1, updated_at = ?, "
                "completed_at = ? WHERE id = ? AND runtime_type = 'vercel' "
                "AND status = 'unknown' AND dispatch_state = 'unknown' "
                "AND runtime_run_ref IS NULL AND state_revision = ?",
                (
                    occurred_at,
                    occurred_at,
                    identifier,
                    expected_state_revision,
                ),
            ).rowcount
            if updated != 1:
                raise RunRepositoryConflict("run.recovery_state_changed")
            self.connection.execute(
                "UPDATE mentat_dispatch_reservations SET updated_at = ? "
                "WHERE run_id = ? AND state = 'unknown' AND attempt_count = 1",
                (occurred_at, identifier),
            )
            self._append_next_lifecycle_event(
                identifier,
                event_type=AgentEventType.RUN_INTERRUPTED,
                occurred_at=occurred_at,
                summary="Operator abandoned an ambiguous Vercel submission",
                source_key=f"vercel:{identifier}:abandon-unknown",
            )
            self._apply_retention()
            return self.get_run(identifier)

    def recover_console_runs_as_interrupted(
        self, *, now: str | None = None
    ) -> tuple[str, ...]:
        """Terminalize legacy Console work that has no durable reattachment."""

        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
            rows = self.connection.execute(
                f"SELECT id FROM mentat_runs WHERE source = 'console' "
                f"AND status IN ({placeholders}) ORDER BY id",
                tuple(sorted(_ACTIVE_STATUSES)),
            ).fetchall()
            recovered: list[str] = []
            for row in rows:
                run_id = str(row["id"])
                updated = self.connection.execute(
                    "UPDATE mentat_runs SET status = 'interrupted', partial = 1, "
                    "state_revision = state_revision + 1, updated_at = ?, completed_at = ? "
                    "WHERE id = ? AND source = 'console'",
                    (occurred_at, occurred_at, run_id),
                ).rowcount
                if updated != 1:
                    raise RunRepositoryConflict("run.state_changed")
                self._append_next_lifecycle_event(
                    run_id,
                    event_type=AgentEventType.RUN_INTERRUPTED,
                    occurred_at=occurred_at,
                    summary="Console run interrupted by Mentat restart",
                    source_key=f"restart:{run_id}:console-interrupted",
                )
                recovered.append(run_id)
            self._apply_retention()
            return tuple(recovered)

    def lease_reconcilable_runs(
        self,
        *,
        owner: str,
        limit: int = 20,
        now_epoch: float | None = None,
        lease_seconds: float = 30.0,
    ) -> tuple[RunRecord, ...]:
        owner_id = _identifier(owner)
        moment = time.time() if now_epoch is None else now_epoch
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or not isinstance(moment, (int, float))
            or not math.isfinite(moment)
            or moment <= 0
            or not isinstance(lease_seconds, (int, float))
            or not 1 <= lease_seconds <= 300
        ):
            raise RunRepositoryValidationError("reconcile.request_invalid")
        leased: list[RunRecord] = []
        with self.mutation():
            rows = self.connection.execute(
                "SELECT id, state_revision FROM mentat_runs "
                "WHERE source = 'task_dispatch' "
                "AND status IN ('queued', 'starting', 'running', 'cancelling', "
                "'waiting', 'waiting_for_approval', 'waiting_for_clarification', 'unknown') "
                "AND dispatch_state IN ('accepted', 'unknown') "
                "AND (reconcile_lease_until IS NULL OR reconcile_lease_until <= ?) "
                "ORDER BY updated_at, id LIMIT ?",
                (float(moment), limit),
            ).fetchall()
            for row in rows:
                updated = self.connection.execute(
                    "UPDATE mentat_runs SET reconcile_lease_owner = ?, "
                    "reconcile_lease_until = ?, state_revision = state_revision + 1 "
                    "WHERE id = ? AND state_revision = ? "
                    "AND (reconcile_lease_until IS NULL OR reconcile_lease_until <= ?)",
                    (
                        owner_id,
                        float(moment + lease_seconds),
                        row["id"],
                        row["state_revision"],
                        float(moment),
                    ),
                ).rowcount
                if updated == 1:
                    leased.append(self.get_run(str(row["id"])))
        return tuple(leased)

    def lease_reconcilable_run(
        self,
        *,
        run_id: str,
        owner: str,
        now_epoch: float | None = None,
        lease_seconds: float = 30.0,
    ) -> RunRecord | None:
        """Lease one exact task-dispatch Run for post-action readback."""

        identifier = _identifier(run_id)
        owner_id = _identifier(owner)
        moment = time.time() if now_epoch is None else now_epoch
        if (
            not isinstance(moment, (int, float))
            or isinstance(moment, bool)
            or not math.isfinite(moment)
            or moment <= 0
            or not isinstance(lease_seconds, (int, float))
            or isinstance(lease_seconds, bool)
            or not 1 <= lease_seconds <= 300
        ):
            raise RunRepositoryValidationError("reconcile.request_invalid")
        with self.mutation():
            row = self.connection.execute(
                "SELECT id, state_revision FROM mentat_runs "
                "WHERE id = ? AND source = 'task_dispatch' "
                "AND status IN ('queued', 'starting', 'running', 'cancelling', "
                "'waiting', 'waiting_for_approval', 'waiting_for_clarification', 'unknown') "
                "AND dispatch_state IN ('accepted', 'unknown') "
                "AND (reconcile_lease_until IS NULL OR reconcile_lease_until <= ?)",
                (identifier, float(moment)),
            ).fetchone()
            if row is None:
                return None
            updated = self.connection.execute(
                "UPDATE mentat_runs SET reconcile_lease_owner = ?, "
                "reconcile_lease_until = ?, state_revision = state_revision + 1 "
                "WHERE id = ? AND state_revision = ? "
                "AND (reconcile_lease_until IS NULL OR reconcile_lease_until <= ?)",
                (
                    owner_id,
                    float(moment + lease_seconds),
                    identifier,
                    row["state_revision"],
                    float(moment),
                ),
            ).rowcount
            return self.get_run(identifier) if updated == 1 else None

    def release_reconciliation_lease(
        self,
        *,
        run_id: str,
        owner: str,
        expected_revision: int,
    ) -> bool:
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunRepositoryValidationError("reconcile.revision_invalid")
        with self.mutation():
            return self.connection.execute(
                "UPDATE mentat_runs SET reconcile_lease_owner = NULL, "
                "reconcile_lease_until = NULL, state_revision = state_revision + 1 "
                "WHERE id = ? AND reconcile_lease_owner = ? AND state_revision = ?",
                (_identifier(run_id), _identifier(owner), expected_revision),
            ).rowcount == 1

    def apply_reconciliation(
        self,
        *,
        run_id: str,
        owner: str,
        expected_revision: int,
        observed: AgentRun,
        events: Iterable[AgentEvent] = (),
        defer_terminal: bool = False,
        now: str | None = None,
    ) -> RunRecord:
        identifier = _identifier(run_id)
        if observed.id != identifier:
            raise RunRepositoryConflict("reconcile.identity_mismatch")
        observed_status = observed.status.value
        if observed_status not in _OBSERVABLE_RUNTIME_STATUSES or type(defer_terminal) is not bool:
            raise RunRepositoryValidationError("reconcile.status_invalid")
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            row = self.connection.execute(
                "SELECT * FROM mentat_runs WHERE id = ?", (identifier,)
            ).fetchone()
            if row is None:
                raise RunRepositoryConflict("run.not_found")
            if (
                row["reconcile_lease_owner"] != _identifier(owner)
                or int(row["state_revision"]) != expected_revision
            ):
                raise RunRepositoryConflict("reconcile.lease_lost")
            if (
                (row["task_id"] is not None and observed.task_id != row["task_id"])
                or (row["agent_id"] is not None and observed.agent_id != row["agent_id"])
                or observed.runtime_type != row["runtime_type"]
            ):
                raise RunRepositoryConflict("reconcile.identity_mismatch")
            if str(row["status"]) in _TERMINAL_STATUSES:
                raise RunRepositoryConflict("reconcile.run_terminal")
            next_status = (
                str(row["status"])
                if defer_terminal and observed_status in _TERMINAL_STATUSES
                else observed_status
            )
            if next_status not in _RECONCILIATION_TRANSITIONS.get(
                str(row["status"]), frozenset({str(row["status"])})
            ):
                raise RunRepositoryConflict("reconcile.status_regression")

            source_cursor = int(row["runtime_event_cursor"])
            next_source_cursor = source_cursor
            for event in events:
                if event.run_id != identifier:
                    raise RunRepositoryConflict("reconcile.event_identity_mismatch")
                source_key = f"runtime:{event.id}"
                normalized = _event_from_domain(event)
                existing = self.connection.execute(
                    "SELECT event_type, occurred_at, summary, content, metrics_json "
                    "FROM mentat_agent_events WHERE run_id = ? AND source_key = ?",
                    (identifier, source_key),
                ).fetchone()
                if existing is not None:
                    if (
                        str(existing["event_type"]) != normalized["event_type"]
                        or str(existing["occurred_at"]) != normalized["occurred_at"]
                        or str(existing["summary"]) != normalized["summary"]
                        or existing["content"] != normalized["content"]
                        or str(existing["metrics_json"]) != normalized["metrics_json"]
                    ):
                        raise RunRepositoryConflict("event.conflict")
                    if event.sequence > source_cursor:
                        raise RunRepositoryConflict("event.sequence_conflict")
                    continue
                if event.sequence <= source_cursor:
                    # Retention may have removed the normalized row. The
                    # durable runtime cursor remains the dedup tombstone.
                    continue
                if event.sequence <= next_source_cursor:
                    raise RunRepositoryConflict("reconcile.event_sequence_invalid")
                sequence = int(row["last_event_sequence"]) + 1
                record = dict(normalized)
                record["id"] = (
                    "event_"
                    + hashlib.sha256(
                        (identifier + ":" + event.id).encode("utf-8")
                    ).hexdigest()[:24]
                )
                record["sequence"] = sequence
                record["source_key"] = source_key
                digest_payload = {
                    key: record[key]
                    for key in (
                        "id", "run_id", "sequence", "event_type", "source_type",
                        "source_key", "occurred_at", "summary", "content",
                        "metrics_json", "data_json",
                    )
                }
                record["payload_digest"] = hashlib.sha256(
                    _canonical_json(
                        digest_payload, maximum=32_768, code="event.invalid"
                    ).encode("ascii")
                ).hexdigest()
                self._append_event_record(record)
                next_source_cursor = event.sequence
                row = self.connection.execute(
                    "SELECT * FROM mentat_runs WHERE id = ?", (identifier,)
                ).fetchone()

            terminal_type = {
                "completed": AgentEventType.RUN_COMPLETED,
                "failed": AgentEventType.RUN_FAILED,
                "stopped": AgentEventType.RUN_STOPPED,
                "interrupted": AgentEventType.RUN_INTERRUPTED,
            }.get(next_status)
            if terminal_type is not None:
                terminal_exists = self.connection.execute(
                    "SELECT 1 FROM mentat_agent_events WHERE run_id = ? "
                    "AND event_type = ? LIMIT 1",
                    (identifier, terminal_type.value),
                ).fetchone()
                if terminal_exists is None:
                    self._append_next_lifecycle_event(
                        identifier,
                        event_type=terminal_type,
                        occurred_at=occurred_at,
                        summary=f"Runtime reported {next_status}",
                        source_key=f"runtime-status:{identifier}:{next_status}",
                    )

            terminal_at = occurred_at if next_status in _TERMINAL_STATUSES else None
            reservation_updated = self.connection.execute(
                "UPDATE mentat_dispatch_reservations SET state = 'accepted', updated_at = ? "
                "WHERE run_id = ? AND state IN ('accepted', 'unknown')",
                (occurred_at, identifier),
            ).rowcount
            if reservation_updated != 1:
                raise RunRepositoryConflict("reconcile.dispatch_state_invalid")
            updated = self.connection.execute(
                "UPDATE mentat_runs SET status = ?, dispatch_state = 'accepted', "
                "partial = 0, runtime_event_cursor = ?, updated_at = ?, "
                "started_at = COALESCE(started_at, ?), "
                "completed_at = ?, reconcile_lease_owner = NULL, "
                "reconcile_lease_until = NULL, state_revision = state_revision + 1 "
                "WHERE id = ? AND reconcile_lease_owner = ? AND state_revision = ?",
                (
                    next_status,
                    next_source_cursor,
                    occurred_at,
                    occurred_at,
                    terminal_at,
                    identifier,
                    _identifier(owner),
                    expected_revision,
                ),
            ).rowcount
            if updated != 1:
                raise RunRepositoryConflict("reconcile.lease_lost")
            self._apply_retention()
            return self.get_run(identifier)

    def claim_authority(
        self,
        *,
        source_sha256: str,
        source_run_count: int,
        cutover_at: float | None = None,
    ) -> RunAuthorityReceipt:
        if (
            not _SHA256.fullmatch(source_sha256)
            or type(source_run_count) is not int
            or not 0 <= source_run_count <= MAX_SOURCE_RUNS
        ):
            raise RunRepositoryValidationError("run_migration.source_invalid")
        timestamp = time.time() if cutover_at is None else cutover_at
        if not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp) or timestamp <= 0:
            raise RunRepositoryValidationError("run_migration.timestamp_invalid")
        if self.authority_receipt() is not None:
            raise RunRepositoryConflict("run_repository.authority_exists")
        self.connection.execute(
            "INSERT INTO mentat_run_store_state "
            "(singleton, authority, migration_contract, source_sha256, source_run_count, cutover_at) "
            "VALUES (1, 'sqlite', ?, ?, ?, ?)",
            (RUN_AUTHORITY_CONTRACT, source_sha256, source_run_count, float(timestamp)),
        )
        return RunAuthorityReceipt(source_sha256, source_run_count, float(timestamp))

    def _upsert_summary(self, run: Mapping[str, Any], *, dispatch_state: str = "legacy") -> None:
        details, raw_events = _details_for_run(run)
        run_id = _identifier(run.get("id"))
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise RunRepositoryValidationError("run.identifier_invalid")
        status = str(run.get("status") or "failed")
        if status not in _ALL_STATUSES:
            status = "failed"
        if dispatch_state not in _DISPATCH_STATES:
            raise RunRepositoryValidationError("run.dispatch_state_invalid")
        runtime_type = str(run.get("runtime_type") or "hermes")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", runtime_type):
            raise RunRepositoryValidationError("run.runtime_invalid")
        agent_id = run.get("mentat_agent_id")
        task_id = run.get("task_id")
        agent_id = _identifier(agent_id, nullable=True)
        task_id = _task_identifier(task_id, nullable=True)
        details_json = _canonical_json(details, maximum=RUN_DETAILS_LIMIT, code="run.details_invalid")
        created_at = _timestamp(run.get("created_at"))
        updated_at = _timestamp(run.get("updated_at") or created_at)
        started_at = _timestamp(run.get("started_at"), nullable=True)
        completed_at = _timestamp(run.get("completed_at"), nullable=True)
        existing = self.connection.execute(
            "SELECT source, task_id, agent_id, runtime_type, status, dispatch_state, "
            "partial, details_json, updated_at, started_at, completed_at, "
            "last_event_sequence, last_removed_sequence "
            "FROM mentat_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        importing = existing is None
        if (
            existing is not None
            and str(existing["status"]) in _TERMINAL_STATUSES
            and status != str(existing["status"])
        ):
            raise RunRepositoryConflict("run.status_regression")
        revision_increment = 0
        if existing is not None:
            projected_details_json = (
                existing["details_json"]
                if existing["source"] == "task_dispatch"
                else details_json
            )
            projected = (
                existing["task_id"] if existing["task_id"] is not None else task_id,
                existing["agent_id"] if existing["agent_id"] is not None else agent_id,
                runtime_type,
                status,
                dispatch_state
                if existing["dispatch_state"] == "legacy"
                else existing["dispatch_state"],
                1 if run.get("partial") else 0,
                projected_details_json,
                updated_at,
                existing["started_at"]
                if existing["started_at"] is not None
                else started_at,
                completed_at,
            )
            current = tuple(
                existing[key]
                for key in (
                    "task_id", "agent_id", "runtime_type", "status",
                    "dispatch_state", "partial", "details_json", "updated_at",
                    "started_at", "completed_at",
                )
            )
            revision_increment = 1 if projected != current else 0
        if importing:
            retained_events = _newest_contiguous_event_suffix(raw_events)
        else:
            retained_events = [dict(item) for item in raw_events]
        self.connection.execute(
            """
            INSERT INTO mentat_runs (
                id, source, task_id, agent_id, runtime_type, capabilities_json,
                status, dispatch_state, partial, details_json,
                created_at, updated_at, started_at, completed_at
            ) VALUES (?, 'console', ?, ?, ?, '[]', ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                task_id = COALESCE(mentat_runs.task_id, excluded.task_id),
                agent_id = COALESCE(mentat_runs.agent_id, excluded.agent_id),
                runtime_type = excluded.runtime_type,
                status = excluded.status,
                dispatch_state = CASE
                    WHEN mentat_runs.dispatch_state = 'legacy' THEN excluded.dispatch_state
                    ELSE mentat_runs.dispatch_state
                END,
                partial = excluded.partial,
                details_json = CASE
                    WHEN mentat_runs.source = 'task_dispatch'
                    THEN mentat_runs.details_json
                    ELSE excluded.details_json
                END,
                updated_at = excluded.updated_at,
                started_at = COALESCE(mentat_runs.started_at, excluded.started_at),
                completed_at = excluded.completed_at,
                state_revision = mentat_runs.state_revision + ?
            """,
            (
                run_id,
                task_id,
                agent_id,
                runtime_type,
                status,
                dispatch_state,
                1 if run.get("partial") else 0,
                details_json,
                created_at,
                updated_at,
                started_at,
                completed_at,
                revision_increment,
            ),
        )
        retained_first = (
            int(retained_events[0]["sequence"])
            if retained_events and type(retained_events[0].get("sequence")) is int
            else 1
        )
        if importing and retained_first > 1:
            self.connection.execute(
                "UPDATE mentat_runs SET timeline_truncated = 1, "
                "first_retained_sequence = ?, last_removed_sequence = ?, "
                "discarded_event_count = ?, truncation_reason = 'legacy_unverified', "
                "last_event_sequence = ? WHERE id = ?",
                (
                    retained_first,
                    retained_first - 1,
                    retained_first - 1,
                    retained_first - 1,
                    run_id,
                ),
            )
        last_removed = int(existing["last_removed_sequence"]) if existing is not None else 0
        for raw_event in retained_events:
            if int(raw_event["sequence"]) <= last_removed:
                continue
            record = _event_record(run_id, status, raw_event)
            self._append_event_record(record)
        if importing and (
            run.get("_migration_timeline_truncated") is True
            or len(retained_events) != len(raw_events)
        ):
            first = int(
                self.connection.execute(
                    "SELECT MIN(sequence) FROM mentat_agent_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
                or 1
            )
            self.connection.execute(
                "UPDATE mentat_runs SET timeline_truncated = 1, "
                "first_retained_sequence = ?, last_removed_sequence = ?, "
                "discarded_event_count = MAX(discarded_event_count, ?), "
                "truncation_reason = 'legacy_unverified' "
                "WHERE id = ?",
                (first, first - 1, first - 1, run_id),
            )

    def _append_event_record(self, record: Mapping[str, Any]) -> bool:
        run_id = str(record["run_id"])
        sequence = int(record["sequence"])
        event_id = str(record["id"])
        digest = str(record["payload_digest"])
        by_sequence = self.connection.execute(
            "SELECT id, payload_digest FROM mentat_agent_events WHERE run_id = ? AND sequence = ?",
            (run_id, sequence),
        ).fetchone()
        by_id = self.connection.execute(
            "SELECT sequence, payload_digest FROM mentat_agent_events WHERE run_id = ? AND id = ?",
            (run_id, event_id),
        ).fetchone()
        by_source = self.connection.execute(
            "SELECT sequence, id, payload_digest FROM mentat_agent_events "
            "WHERE run_id = ? AND source_key = ?",
            (run_id, str(record["source_key"])),
        ).fetchone()
        if by_sequence is not None or by_id is not None or by_source is not None:
            identical = (
                by_sequence is not None
                and by_id is not None
                and by_source is not None
                and str(by_sequence["id"]) == event_id
                and int(by_id["sequence"]) == sequence
                and int(by_source["sequence"]) == sequence
                and str(by_source["id"]) == event_id
                and str(by_sequence["payload_digest"]) == digest
                and str(by_id["payload_digest"]) == digest
                and str(by_source["payload_digest"]) == digest
            )
            if identical:
                return False
            raise RunRepositoryConflict("event.conflict")
        row = self.connection.execute(
            "SELECT status, last_event_sequence, updated_at FROM mentat_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise RunRepositoryConflict("run.not_found")
        _validate_event_row(record, run_id=run_id, run_status=str(row["status"]))
        last_sequence = int(row["last_event_sequence"])
        if sequence != last_sequence + 1:
            raise RunRepositoryConflict("event.sequence_conflict")
        self.connection.execute(
            """
            INSERT INTO mentat_agent_events (
                run_id, sequence, id, event_type, source_type, source_key, occurred_at,
                summary, content, metrics_json, data_json, content_bytes,
                payload_digest
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                sequence,
                event_id,
                record["event_type"],
                record["source_type"],
                record["source_key"],
                record["occurred_at"],
                record["summary"],
                record["content"],
                record["metrics_json"],
                record["data_json"],
                record["content_bytes"],
                digest,
            ),
        )
        self.connection.execute(
            "UPDATE mentat_runs SET last_event_sequence = ?, updated_at = ? WHERE id = ?",
            (
                sequence,
                max(
                    (_timestamp(row["updated_at"]), _timestamp(record["occurred_at"])),
                    key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
                ),
                run_id,
            ),
        )
        return True

    def append_event(self, event: AgentEvent) -> bool:
        with self.mutation():
            inserted = self._append_event_record(_event_from_domain(event))
            self._apply_retention()
            return inserted

    def sync_summaries(self, runs: Sequence[Mapping[str, Any]]) -> RetentionReport:
        if len(runs) > MAX_SOURCE_RUNS:
            raise RunRepositoryValidationError("run.limit")
        with self.mutation():
            self.authority_receipt(required=True)
            incoming_ids = []
            for run in runs:
                if not isinstance(run, Mapping):
                    raise RunRepositoryValidationError("run.invalid")
                incoming_ids.append(_identifier(run.get("id")))
            self._apply_retention()
            self._ensure_run_capacity(incoming_ids)
            for run in runs:
                self._upsert_summary(run)
            return self._apply_retention()

    def _event_rows(self, run_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM mentat_agent_events WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()

    def _legacy_event(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "id": str(row["id"]),
            "run_id": str(row["run_id"]),
            "sequence": int(row["sequence"]),
            "cursor": int(row["sequence"]),
            "type": str(row["source_type"]),
            "kind": str(row["source_type"]),
            "timestamp": str(row["occurred_at"]),
            "data": _decode_json(row["data_json"], expected=dict, code="event.corrupt"),
            "display_text": str(row["summary"]),
            "message": str(row["summary"]),
        }

    def list_summaries(self, *, limit: int = 24) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= MAX_SOURCE_RUNS:
            raise RunRepositoryValidationError("run.limit_invalid")
        self.authority_receipt(required=True)
        placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
        active_rows = self.connection.execute(
            f"SELECT * FROM mentat_runs WHERE source = 'console' "
            f"AND status IN ({placeholders}) "
            "ORDER BY created_at DESC, id DESC",
            tuple(sorted(_ACTIVE_STATUSES)),
        ).fetchall()
        terminal_rows = self.connection.execute(
            f"SELECT * FROM mentat_runs WHERE source = 'console' "
            f"AND status NOT IN ({placeholders}) "
            "ORDER BY completed_at DESC, created_at DESC, id DESC LIMIT ?",
            (*tuple(sorted(_ACTIVE_STATUSES)), limit),
        ).fetchall()
        rows = sorted(
            [*active_rows, *terminal_rows],
            key=lambda row: (str(row["created_at"]), str(row["id"])),
            reverse=True,
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            _validate_run_row(row)
            details = _validated_run_details(row)
            details["id"] = str(row["id"])
            details["runtime_type"] = str(row["runtime_type"])
            details["status"] = str(row["status"])
            details["partial"] = bool(row["partial"])
            for name in ("created_at", "updated_at", "started_at", "completed_at"):
                details[name] = row[name]
            event_rows = self._event_rows(str(row["id"]))
            _validate_event_window(row, event_rows)
            events = [self._legacy_event(event) for event in event_rows]
            details["events"] = events
            details["event_cursor"] = int(row["last_event_sequence"])
            if row["agent_id"] is not None:
                details["mentat_agent_id"] = str(row["agent_id"])
            if row["task_id"] is not None:
                details["task_id"] = str(row["task_id"])
            hydrated = _hydrate(details)
            if hydrated is None:
                raise RunRepositoryError("run.corrupt")
            hydrated["event_cursor"] = int(row["last_event_sequence"])
            hydrated["timeline_truncated"] = bool(row["timeline_truncated"])
            hydrated["first_retained_sequence"] = int(row["first_retained_sequence"])
            hydrated["last_removed_sequence"] = int(row["last_removed_sequence"])
            result.append(hydrated)
        return result

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[tuple[AgentEvent, ...], bool, int]:
        identifier = _identifier(run_id)
        if type(after_sequence) is not int or after_sequence < 0:
            raise RunRepositoryValidationError("event.cursor_invalid")
        row = self.connection.execute(
            "SELECT * FROM mentat_runs WHERE id = ?",
            (identifier,),
        ).fetchone()
        if row is None:
            raise RunRepositoryConflict("run.not_found")
        _validate_run_row(row)
        event_rows = self._event_rows(identifier)
        _validate_event_window(row, event_rows)
        events: list[AgentEvent] = []
        for event_row in event_rows:
            if int(event_row["sequence"]) <= after_sequence:
                continue
            events.append(
                AgentEvent(
                    id=str(event_row["id"]),
                    run_id=identifier,
                    sequence=int(event_row["sequence"]),
                    type=str(event_row["event_type"]),
                    occurred_at=str(event_row["occurred_at"]),
                    summary=str(event_row["summary"]),
                    content=event_row["content"],
                    metrics=_decode_json(
                        event_row["metrics_json"], expected=dict, code="event.corrupt"
                    ),
                )
            )
        reset = bool(row["timeline_truncated"]) and (
            int(row["last_event_sequence"]) == 0
            or after_sequence < int(row["first_retained_sequence"]) - 1
        )
        return tuple(events), reset, int(row["last_event_sequence"])

    def trusted_vercel_result_message_id(self, run_id: str) -> str | None:
        """Return the sole provenance-bound Vercel result message, if retained."""

        identifier = _identifier(run_id)
        run = self.connection.execute(
            "SELECT * FROM mentat_runs WHERE id = ?",
            (identifier,),
        ).fetchone()
        if run is None:
            raise RunRepositoryConflict("run.not_found")
        _validate_run_row(run)
        if str(run["runtime_type"]) != "vercel":
            return None
        rows = self.connection.execute(
            "SELECT id, event_type, source_type, source_key, content "
            "FROM mentat_agent_events WHERE run_id = ? AND event_type = 'message' "
            "ORDER BY sequence",
            (identifier,),
        ).fetchall()
        if len(rows) > 1:
            raise RunRepositoryError("event.corrupt")
        if not rows:
            return None
        row = rows[0]
        source_key = str(row["source_key"])
        expected_source_event_id = "vercel_message_" + hashlib.sha256(
            (identifier + ":message").encode("utf-8")
        ).hexdigest()[:24]
        expected_source_key = f"submission:{expected_source_event_id}"
        if (
            str(row["event_type"]) != AgentEventType.MESSAGE.value
            or str(row["source_type"]) != AgentEventType.MESSAGE.value
            or _VERCEL_MESSAGE_SOURCE.fullmatch(source_key) is None
            or source_key != expected_source_key
            or row["content"] is None
        ):
            raise RunRepositoryError("event.corrupt")
        expected_id = "event_" + hashlib.sha256(
            (identifier + ":" + expected_source_event_id).encode("utf-8")
        ).hexdigest()[:24]
        if str(row["id"]) != expected_id:
            raise RunRepositoryError("event.corrupt")
        return expected_id

    def _compact_events(self, run_id: str) -> bool:
        rows = self.connection.execute(
            "SELECT sequence, content_bytes FROM mentat_agent_events "
            "WHERE run_id = ? ORDER BY sequence DESC",
            (run_id,),
        ).fetchall()
        kept: list[int] = []
        total_bytes = 0
        reason = None
        for row in rows:
            size = int(row["content_bytes"])
            if len(kept) >= EVENT_COUNT_RETENTION:
                reason = "per_run_count"
                break
            if total_bytes + size > EVENT_CONTENT_RETENTION_BYTES:
                reason = "per_run_bytes"
                break
            kept.append(int(row["sequence"]))
            total_bytes += size
        if len(kept) == len(rows):
            return False
        first = min(kept) if kept else int(rows[0]["sequence"]) + 1
        removed = [row for row in rows if int(row["sequence"]) < first]
        removed_bytes = sum(int(row["content_bytes"]) for row in removed)
        self.connection.execute(
            "DELETE FROM mentat_agent_events WHERE run_id = ? AND sequence < ?",
            (run_id, first),
        )
        self.connection.execute(
            "UPDATE mentat_runs SET timeline_truncated = 1, first_retained_sequence = ?, "
            "last_removed_sequence = ?, discarded_event_count = discarded_event_count + ?, "
            "discarded_content_bytes = discarded_content_bytes + ?, truncation_reason = ? "
            "WHERE id = ?",
            (first, first - 1, len(removed), removed_bytes, reason or "per_run_count", run_id),
        )
        return True

    def _apply_retention(self) -> RetentionReport:
        truncated: list[str] = []
        for row in self.connection.execute("SELECT id FROM mentat_runs ORDER BY id"):
            run_id = str(row[0])
            if self._compact_events(run_id):
                truncated.append(run_id)
        globally_truncated = self._apply_global_event_retention()
        truncated.extend(run_id for run_id in globally_truncated if run_id not in truncated)
        terminal = self.connection.execute(
            "SELECT id FROM mentat_runs WHERE status NOT IN ("
            + ",".join("?" for _ in _ACTIVE_STATUSES)
            + ") ORDER BY completed_at DESC, created_at DESC, id DESC",
            tuple(sorted(_ACTIVE_STATUSES)),
        ).fetchall()
        removed = tuple(str(row[0]) for row in terminal[TERMINAL_RUN_RETENTION:])
        for run_id in removed:
            self.connection.execute("DELETE FROM run_attachments WHERE run_id = ?", (run_id,))
            self.connection.execute("DELETE FROM mentat_runs WHERE id = ?", (run_id,))
        self.connection.execute(
            "DELETE FROM mentat_dispatch_reservations WHERE expires_at <= ? "
            "AND state IN ('accepted', 'rejected') "
            "AND NOT EXISTS (SELECT 1 FROM mentat_runs r "
            "WHERE r.id = mentat_dispatch_reservations.run_id "
            "AND r.status IN ("
            + ",".join("?" for _ in _ACTIVE_STATUSES)
            + "))",
            (time.time(), *tuple(sorted(_ACTIVE_STATUSES))),
        )
        return RetentionReport(removed, tuple(truncated))

    def _apply_global_event_retention(self) -> tuple[str, ...]:
        totals = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(content_bytes), 0) FROM mentat_agent_events"
        ).fetchone()
        event_count = int(totals[0])
        content_bytes = int(totals[1])
        if (
            event_count <= GLOBAL_EVENT_COUNT_RETENTION
            and content_bytes <= GLOBAL_EVENT_CONTENT_RETENTION_BYTES
        ):
            return ()
        changed: list[str] = []
        rows = self.connection.execute(
            "SELECT e.run_id, e.sequence, e.content_bytes "
            "FROM mentat_agent_events e JOIN mentat_runs r ON r.id = e.run_id "
            "ORDER BY CASE WHEN r.status IN ("
            + ",".join("?" for _ in _ACTIVE_STATUSES)
            + ") THEN 1 ELSE 0 END, r.updated_at, e.sequence",
            tuple(sorted(_ACTIVE_STATUSES)),
        ).fetchall()
        removals: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            if (
                event_count <= GLOBAL_EVENT_COUNT_RETENTION
                and content_bytes <= GLOBAL_EVENT_CONTENT_RETENTION_BYTES
            ):
                break
            run_id = str(row["run_id"])
            removals.setdefault(run_id, []).append(row)
            event_count -= 1
            content_bytes -= int(row["content_bytes"])
        for run_id, removed in removals.items():
            last_removed = max(int(row["sequence"]) for row in removed)
            removed_bytes = sum(int(row["content_bytes"]) for row in removed)
            self.connection.execute(
                "DELETE FROM mentat_agent_events WHERE run_id = ? AND sequence <= ?",
                (run_id, last_removed),
            )
            first_row = self.connection.execute(
                "SELECT MIN(sequence) FROM mentat_agent_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            first = int(first_row[0]) if first_row and first_row[0] is not None else last_removed + 1
            reason = (
                "global_count"
                if int(totals[0]) > GLOBAL_EVENT_COUNT_RETENTION
                else "global_bytes"
            )
            self.connection.execute(
                "UPDATE mentat_runs SET timeline_truncated = 1, "
                "first_retained_sequence = ?, last_removed_sequence = ?, "
                "discarded_event_count = discarded_event_count + ?, "
                "discarded_content_bytes = discarded_content_bytes + ?, "
                "truncation_reason = ? WHERE id = ?",
                (first, last_removed, len(removed), removed_bytes, reason, run_id),
            )
            changed.append(run_id)
        return tuple(changed)

    def validate(self) -> tuple[int, int, int]:
        self.authority_receipt(required=True)
        task_authority = self.connection.execute(
            "SELECT authority FROM mentat_task_store_state WHERE singleton = 1"
        ).fetchone()
        has_task_dispatch = self.connection.execute(
            "SELECT 1 FROM mentat_runs WHERE source = 'task_dispatch' LIMIT 1"
        ).fetchone()
        if has_task_dispatch is not None and (
            task_authority is None or str(task_authority["authority"]) != "sqlite"
        ):
            raise RunRepositoryError("run_repository.corrupt")
        if self.connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RunRepositoryError("run_repository.corrupt")
        run_count = int(self.connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0])
        event_count = int(
            self.connection.execute("SELECT COUNT(*) FROM mentat_agent_events").fetchone()[0]
        )
        reservation_count = int(
            self.connection.execute("SELECT COUNT(*) FROM mentat_dispatch_reservations").fetchone()[0]
        )
        if run_count > MAX_SOURCE_RUNS:
            raise RunRepositoryError("run_repository.corrupt")
        page_size = int(self.connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(self.connection.execute("PRAGMA page_count").fetchone()[0])
        if page_size * page_count > RUN_STORE_DATABASE_BUDGET:
            raise RunRepositoryError("run_repository.corrupt")
        terminal_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM mentat_runs WHERE status NOT IN ("
                + ",".join("?" for _ in _ACTIVE_STATUSES)
                + ")",
                tuple(sorted(_ACTIVE_STATUSES)),
            ).fetchone()[0]
        )
        if terminal_count > TERMINAL_RUN_RETENTION:
            raise RunRepositoryError("run_repository.corrupt")
        for row in self.connection.execute("SELECT * FROM mentat_runs"):
            run_capabilities = _validate_run_row(row)
            if str(row["status"]) not in _ALL_STATUSES or str(row["dispatch_state"]) not in _DISPATCH_STATES:
                raise RunRepositoryError("run_repository.corrupt")
            if int(row["runtime_event_cursor"]) < 0:
                raise RunRepositoryError("run_repository.corrupt")
            if row["runtime_run_ref"] is not None:
                try:
                    _identifier(str(row["runtime_run_ref"]))
                except RunRepositoryValidationError as exc:
                    raise RunRepositoryError("run_repository.corrupt") from exc
            if (row["reconcile_lease_owner"] is None) != (row["reconcile_lease_until"] is None):
                raise RunRepositoryError("run_repository.corrupt")
            if row["reconcile_lease_owner"] is not None:
                _identifier(str(row["reconcile_lease_owner"]))
                lease_until = float(row["reconcile_lease_until"])
                if not math.isfinite(lease_until) or lease_until <= 0:
                    raise RunRepositoryError("run_repository.corrupt")
            if str(row["source"]) == "task_dispatch":
                if (
                    row["task_id"] is None
                    or row["task_revision"] is None
                    or row["task_snapshot_json"] is None
                    or row["agent_id"] is None
                    or row["runtime_config_id"] is None
                    or row["runtime_binding_digest"] is None
                    or not _SHA256.fullmatch(str(row["runtime_binding_digest"]))
                ):
                    raise RunRepositoryError("run_repository.corrupt")
                if str(row["status"]) in _ACTIVE_STATUSES:
                    task_exists = self.connection.execute(
                        "SELECT 1 FROM mentat_tasks WHERE id = ?",
                        (row["task_id"],),
                    ).fetchone()
                    if task_exists is None:
                        raise RunRepositoryError("run_repository.corrupt")
                reservation = self.connection.execute(
                    "SELECT state, attempt_count FROM mentat_dispatch_reservations "
                    "WHERE run_id = ?",
                    (row["id"],),
                ).fetchone()
                status = str(row["status"])
                dispatch_state = str(row["dispatch_state"])
                if reservation is None:
                    if status in _ACTIVE_STATUSES:
                        raise RunRepositoryError("run_repository.corrupt")
                else:
                    state = str(reservation["state"])
                    attempt = int(reservation["attempt_count"])
                    legal = (
                        (state == "reserved" and attempt == 0 and status == "reserved")
                        or (
                            state == "submitting"
                            and attempt == 1
                            and status != "reserved"
                            and status != "unknown"
                        )
                        or (
                            state == "accepted"
                            and attempt == 1
                            and status not in {"reserved", "submitting", "unknown"}
                        )
                        or (
                            state == "rejected"
                            and attempt in {0, 1}
                            and status in {"failed", "interrupted"}
                        )
                        or (
                            state == "unknown"
                            and attempt == 1
                            and status not in {"reserved", "submitting"}
                        )
                    )
                    if not legal or dispatch_state != state:
                        raise RunRepositoryError("run_repository.corrupt")
                _validate_task_snapshot(row, run_capabilities=run_capabilities)
            elif str(row["source"]) == "console":
                if str(row["dispatch_state"]) != "legacy":
                    raise RunRepositoryError("run_repository.corrupt")
            else:
                raise RunRepositoryError("run_repository.corrupt")
            events = self._event_rows(str(row["id"]))
            _validate_event_window(row, events)
        totals = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(content_bytes), 0) FROM mentat_agent_events"
        ).fetchone()
        if (
            int(totals[0]) > GLOBAL_EVENT_COUNT_RETENTION
            or int(totals[1]) > GLOBAL_EVENT_CONTENT_RETENTION_BYTES
        ):
            raise RunRepositoryError("run_repository.corrupt")
        for row in self.connection.execute("SELECT * FROM mentat_dispatch_reservations"):
            try:
                _identifier(row["dispatch_id"])
                run_id = _identifier(row["run_id"])
                _task_identifier(row["task_id"])
                _ordered_timestamps(row["created_at"], row["updated_at"])
            except RunRepositoryError as exc:
                raise RunRepositoryError("run_repository.corrupt") from exc
            if (
                not isinstance(run_id, str)
                or not _RUN_ID.fullmatch(run_id)
                or str(row["state"]) not in {"reserved", "submitting", "accepted", "rejected", "unknown"}
                or int(row["attempt_count"]) not in {0, 1}
                or (
                    str(row["state"]) == "reserved"
                    and int(row["attempt_count"]) != 0
                )
                or (
                    str(row["state"]) in {"submitting", "accepted", "unknown"}
                    and int(row["attempt_count"]) != 1
                )
                or not _SHA256.fullmatch(str(row["key_digest"]))
                or not _SHA256.fullmatch(str(row["request_digest"]))
                or not _SHA256.fullmatch(str(row["runtime_binding_digest"]))
                or not math.isfinite(float(row["expires_at"]))
                or float(row["expires_at"]) <= 0
            ):
                raise RunRepositoryError("run_repository.corrupt")
            linked = self.connection.execute(
                "SELECT * FROM mentat_runs WHERE id = ?",
                (row["run_id"],),
            ).fetchone()
            if linked is None:
                head = self.connection.execute(
                    "SELECT * FROM mentat_task_dispatch_heads WHERE task_id = ?",
                    (row["task_id"],),
                ).fetchone()
                if (
                    str(row["state"]) not in {"accepted", "rejected"}
                    or head is None
                    or int(head["task_revision"]) < int(row["task_revision"])
                    or (
                        int(head["task_revision"]) == int(row["task_revision"])
                        and (
                            str(head["run_id"]) != str(row["run_id"])
                            or str(head["request_digest"])
                            != str(row["request_digest"])
                        )
                    )
                ):
                    raise RunRepositoryError("run_repository.corrupt")
                continue
            capabilities = _validate_run_row(linked)
            snapshot = _validate_task_snapshot(
                linked, run_capabilities=capabilities
            )
            expected_request = dispatch_request_digest(
                task=snapshot,
                task_revision=int(linked["task_revision"]),
                agent_id=str(linked["agent_id"]),
                runtime_type=str(linked["runtime_type"]),
                runtime_config_id=str(linked["runtime_config_id"]),
                capabilities=capabilities,
            )
            if (
                linked["task_id"] != row["task_id"]
                or int(linked["task_revision"]) != int(row["task_revision"])
                or linked["runtime_binding_digest"] != row["runtime_binding_digest"]
                or str(linked["dispatch_state"]) != str(row["state"])
                or str(row["request_digest"]) != expected_request
            ):
                raise RunRepositoryError("run_repository.corrupt")
        for row in self.connection.execute("SELECT * FROM mentat_task_dispatch_heads"):
            try:
                _task_identifier(row["task_id"])
                run_id = _identifier(row["run_id"])
                _timestamp(row["updated_at"])
            except RunRepositoryError as exc:
                raise RunRepositoryError("run_repository.corrupt") from exc
            if (
                not isinstance(run_id, str)
                or int(row["task_revision"]) < 1
                or not _SHA256.fullmatch(str(row["request_digest"]))
                or not _RUN_ID.fullmatch(run_id)
            ):
                raise RunRepositoryError("run_repository.corrupt")
            linked = self.connection.execute(
                "SELECT * FROM mentat_runs WHERE id = ?",
                (row["run_id"],),
            ).fetchone()
            if linked is not None:
                capabilities = _validate_run_row(linked)
                snapshot = _validate_task_snapshot(
                    linked, run_capabilities=capabilities
                )
                expected_request = dispatch_request_digest(
                    task=snapshot,
                    task_revision=int(linked["task_revision"]),
                    agent_id=str(linked["agent_id"]),
                    runtime_type=str(linked["runtime_type"]),
                    runtime_config_id=str(linked["runtime_config_id"]),
                    capabilities=capabilities,
                )
                if (
                    str(linked["task_id"]) != str(row["task_id"])
                    or int(linked["task_revision"]) != int(row["task_revision"])
                    or str(row["request_digest"]) != expected_request
                ):
                    raise RunRepositoryError("run_repository.corrupt")
        return run_count, event_count, reservation_count


def _read_exact_file(path: Path) -> tuple[bytes, tuple[int, int, int, int] | None]:
    if not os.path.lexists(os.fspath(path)):
        return b"", None
    try:
        lexical = path.lstat()
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if (
            stat.S_ISLNK(lexical.st_mode)
            or bool(getattr(lexical, "st_file_attributes", 0) & reparse)
            or not stat.S_ISREG(lexical.st_mode)
            or lexical.st_nlink != 1
            or (os.name == "posix" and lexical.st_uid != os.getuid())
        ):
            raise RunRepositoryValidationError("run_migration.source_unsafe")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            before = os.fstat(descriptor)
            if (
                before.st_dev != lexical.st_dev
                or before.st_ino != lexical.st_ino
                or not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or (os.name == "posix" and before.st_uid != os.getuid())
            ):
                raise RunRepositoryValidationError("run_migration.source_unsafe")
            chunks: list[bytes] = []
            remaining = 4 * 1024 * 1024 + 1
            while remaining:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
            if after.st_nlink != 1:
                raise RunRepositoryValidationError("run_migration.source_unsafe")
        finally:
            os.close(descriptor)
        raw = b"".join(chunks)
        identity = (
            int(before.st_dev),
            int(before.st_ino),
            int(before.st_size),
            int(before.st_mtime_ns),
        )
        if (
            identity
            != (
                int(after.st_dev),
                int(after.st_ino),
                int(after.st_size),
                int(after.st_mtime_ns),
            )
            or len(raw) != before.st_size
        ):
            raise RunRepositoryConflict("run_migration.source_changed")
        return raw, identity
    except RunRepositoryError:
        raise
    except OSError as exc:
        raise RunRepositoryUnavailable("run_migration.source_unavailable") from exc


def _read_legacy_history(
    path: Path,
) -> tuple[bytes, list[dict[str, Any]], int, tuple[int, int, int, int] | None]:
    raw, identity = _read_exact_file(path)
    if not secure_history_permissions(path, data_root=path.parents[2]):
        raise RunRepositoryValidationError("run_migration.source_unsafe")
    verified_raw, verified_identity = _read_exact_file(path)
    if raw != verified_raw or identity != verified_identity:
        raise RunRepositoryConflict("run_migration.source_changed")
    raw, identity = verified_raw, verified_identity
    if identity is None:
        return b"", [], 0, None
    if len(raw) > 4 * 1024 * 1024:
        raise RunRepositoryValidationError("run_migration.source_too_large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RunRepositoryValidationError("run_migration.source_invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "runs"}
        or payload.get("schema_version") not in (LEGACY_SCHEMA_VERSIONS | {HISTORY_SCHEMA_VERSION})
        or not isinstance(payload.get("runs"), list)
        or len(payload["runs"]) > MAX_SOURCE_RUNS
    ):
        raise RunRepositoryValidationError("run_migration.source_invalid")
    hydrated: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    source_version = int(payload["schema_version"])
    for item in payload["runs"]:
        if not isinstance(item, dict):
            raise RunRepositoryValidationError("run_migration.source_invalid")
        run = _hydrate(item)
        if run is None:
            raise RunRepositoryValidationError("run_migration.source_invalid")
        run_id = str(run["id"])
        if run_id in seen_run_ids:
            raise RunRepositoryValidationError("run_migration.source_invalid")
        seen_run_ids.add(run_id)
        exact_events = (
            _exact_schema_three_events(run_id, item.get("events"))
            if source_version == HISTORY_SCHEMA_VERSION
            else None
        )
        if source_version == HISTORY_SCHEMA_VERSION and exact_events is None:
            raise RunRepositoryValidationError("run_migration.source_invalid")
        if exact_events is None:
            run["events"] = []
            run["event_cursor"] = 0
            run["_migration_timeline_truncated"] = True
        else:
            run["events"] = exact_events
            run["event_cursor"] = exact_events[-1]["sequence"] if exact_events else 0
            if exact_events and exact_events[0]["sequence"] > 1:
                run["_migration_timeline_truncated"] = True
        if str(run.get("status") or "") in _ACTIVE_STATUSES:
            occurred_at = _now_iso()
            run["status"] = "interrupted"
            run["partial"] = True
            run["updated_at"] = occurred_at
            run["completed_at"] = occurred_at
            run["_migration_interrupted"] = True
        hydrated.append(run)
    return raw, hydrated, len(payload["runs"]), identity


def _verify_legacy_history(
    path: Path,
    expected_raw: bytes,
    expected_identity: tuple[int, int, int, int] | None,
) -> None:
    raw, identity = _read_exact_file(path)
    if raw != expected_raw or identity != expected_identity:
        raise RunRepositoryConflict("run_migration.source_changed")


def ensure_run_sqlite_authority(data_dir: Path, history_path: Path) -> RunAuthorityReceipt:
    """Import the exact validated legacy summary set once, then ignore stale JSON."""

    root = Path(data_dir)
    with private_state_lock(root):
        connection = None
        try:
            connection = connect(root)
            repository = RunRepository(connection)
            receipt = repository.authority_receipt()
            if receipt is not None:
                repository.validate()
                return receipt
            source_path = Path(history_path)
            raw, runs, source_count, source_identity = _read_legacy_history(source_path)
            digest = hashlib.sha256(raw).hexdigest()
            with repository.mutation():
                if any(
                    int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in (
                        "mentat_runs",
                        "mentat_agent_events",
                        "mentat_dispatch_reservations",
                        "mentat_task_dispatch_heads",
                    )
                ):
                    raise RunRepositoryConflict("run_migration.destination_not_empty")
                for run in runs:
                    repository._upsert_summary(run)
                    if run.get("_migration_interrupted") is True:
                        repository._append_next_lifecycle_event(
                            str(run["id"]),
                            event_type=AgentEventType.RUN_INTERRUPTED,
                            occurred_at=str(run["updated_at"]),
                            summary="Run interrupted during SQLite authority cutover",
                            source_key=f"migration:{run['id']}:interrupted",
                        )
                _verify_legacy_history(source_path, raw, source_identity)
                receipt = repository.claim_authority(
                    source_sha256=digest,
                    source_run_count=source_count,
                )
                repository._apply_retention()
                repository.validate()
            return receipt
        except (MentatDatabaseError, sqlite3.Error) as exc:
            raise RunRepositoryUnavailable("run_repository.unavailable") from exc
        finally:
            if connection is not None:
                connection.close()


def save_authoritative_run_summaries(
    data_dir: Path,
    runs: Sequence[Mapping[str, Any]],
) -> RetentionReport:
    root = Path(data_dir)
    with private_state_lock(root):
        try:
            connection = connect(root)
            try:
                return RunRepository(connection).sync_summaries(runs)
            finally:
                connection.close()
        except (MentatDatabaseError, sqlite3.Error) as exc:
            raise RunRepositoryUnavailable("run_repository.unavailable") from exc


def load_authoritative_run_summaries(data_dir: Path, *, limit: int = 24) -> list[dict[str, Any]]:
    root = Path(data_dir)
    with private_state_lock(root):
        try:
            connection = connect(root)
            try:
                return RunRepository(connection).list_summaries(limit=limit)
            finally:
                connection.close()
        except (MentatDatabaseError, sqlite3.Error) as exc:
            raise RunRepositoryUnavailable("run_repository.unavailable") from exc


__all__ = [
    "EVENT_CONTENT_RETENTION_BYTES",
    "EVENT_COUNT_RETENTION",
    "RUN_AUTHORITY_CONTRACT",
    "RunAuthorityReceipt",
    "RunRepository",
    "RunRepositoryConflict",
    "RunRepositoryError",
    "RunRepositoryUnavailable",
    "RunRepositoryValidationError",
    "TERMINAL_RUN_RETENTION",
    "ensure_run_sqlite_authority",
    "load_authoritative_run_summaries",
    "save_authoritative_run_summaries",
]
