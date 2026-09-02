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
    bounded_public_excerpt,
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
from conversation_repository import (
    MAX_ASSISTANT_MESSAGE_LENGTH,
    MAX_MESSAGES as MAX_CONVERSATION_MESSAGES,
    MAX_TOTAL_MESSAGE_BYTES,
    MAX_TURNS as MAX_CONVERSATION_TURNS,
    ConversationMessageRecord,
    ConversationRepositoryError,
    ConversationTurnRecord,
    canonical_message_content,
    conversation_message_record,
    conversation_turn_record,
)
from conversation_attachments import (
    ConversationAttachmentError,
    bind_staged_context_to_run,
    copy_run_input_context,
    staged_context_evidence,
)
from mentat_db import (
    MIGRATIONS,
    SCHEMA_VERSION as DATABASE_SCHEMA_VERSION,
    MentatDatabaseError,
    connect,
)
from private_state import private_state_lock
from task_repository import (
    TaskRepository,
    TaskRepositoryConflict,
    TaskRepositoryError,
)
from task_planning import task_is_deferred, workflow_stage


RUN_AUTHORITY_CONTRACT = "mentat-run-sqlite-cutover-v1"
RUN_SCHEMA_VERSION = 7
CONVERSATION_SUBMISSION_SCHEMA_VERSION = 11
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
_CONVERSATION_ID = re.compile(r"conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
_TURN_ID = re.compile(r"turn_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
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
    conversation_continuations: tuple[tuple[str, str], ...] = ()


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
class TaskExecutionReviewResult:
    task_id: str
    task_revision: int
    run_id: str
    action: str
    duplicate: bool = False


@dataclass(frozen=True)
class ConversationDispatchReservation:
    conversation_id: str
    message_id: str
    turn_id: str
    run_id: str | None
    request_digest: str
    runtime_binding_digest: str | None
    state: str
    attempt_count: int
    duplicate: bool = False


@dataclass(frozen=True)
class ConversationRunAdmission:
    """Private current configuration evidence for one queued Turn claim."""

    run_id: str
    agent_id: str
    agent_name: str
    agent_revision: int
    runtime_type: str
    runtime_config_id: str
    runtime_config_revision: int
    runtime_binding_digest: str
    capabilities: tuple[str, ...]
    capacity_scope_digest: str
    capacity_limit: int
    predecessor_run_id: str | None = None


@dataclass(frozen=True)
class ConversationSubmissionResult:
    """Bounded idempotency result retained after the full Run is compacted."""

    id: str
    status: str
    partial: bool
    updated_at: str


@dataclass(frozen=True)
class ConversationRunAttemptResult:
    action: str
    conversation_id: str
    turn_id: str
    source_run_id: str
    run_id: str
    status: str
    dispatch_state: str
    partial: bool
    updated_at: str


def _conversation_run_attempt_result(
    row: Mapping[str, object],
) -> ConversationRunAttemptResult:
    try:
        action = str(row["action"])
        conversation_id = str(row["conversation_id"])
        turn_id = str(row["turn_id"])
        source_run_id = str(row["source_run_id"])
        run_id = str(row["run_id"])
        status = str(row["status"])
        dispatch_state = str(row["dispatch_state"])
        partial = row["partial"]
        updated_at = _timestamp(row["updated_at"])
        if (
            action not in {"retry", "resume"}
            or _CONVERSATION_ID.fullmatch(conversation_id) is None
            or _TURN_ID.fullmatch(turn_id) is None
            or _RUN_ID.fullmatch(source_run_id) is None
            or _RUN_ID.fullmatch(run_id) is None
            or status not in _ALL_STATUSES
            or dispatch_state
            not in {"reserved", "submitting", "accepted", "rejected", "unknown"}
            or type(partial) is not int
            or partial not in {0, 1}
        ):
            raise RunRepositoryError("run_repository.corrupt")
    except (KeyError, TypeError, ValueError, RunRepositoryError) as exc:
        raise RunRepositoryError("run_repository.corrupt") from exc
    return ConversationRunAttemptResult(
        action=action,
        conversation_id=conversation_id,
        turn_id=turn_id,
        source_run_id=source_run_id,
        run_id=run_id,
        status=status,
        dispatch_state=dispatch_state,
        partial=bool(partial),
        updated_at=updated_at,
    )


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
    terminal_finalized: bool
    timeline_truncated: bool
    first_retained_sequence: int
    last_removed_sequence: int
    last_event_sequence: int
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None
    conversation_id: str | None = None
    turn_id: str | None = None
    agent_revision: int | None = None
    runtime_config_revision: int | None = None
    execution_config_digest: str | None = None
    runtime_execution_digest: str | None = None
    capacity_scope_digest: str | None = None
    admitted_capacity_limit: int | None = None
    retry_of_run_id: str | None = None
    resume_of_run_id: str | None = None


@dataclass(frozen=True)
class HydratedRunEvent:
    """One canonical event paired with its validated private source class."""

    event: AgentEvent
    source_type: str


_RUN_SCHEMA_OBJECTS = frozenset(
    {
        "mentat_run_store_state",
        "mentat_runs",
        "mentat_agent_events",
        "mentat_dispatch_reservations",
        "mentat_task_dispatch_heads",
    }
)
_CONVERSATION_RESULT_SCHEMA_OBJECTS = frozenset(
    {"mentat_conversation_submission_results"}
)
_CONVERSATION_ATTEMPT_SCHEMA_OBJECTS = frozenset(
    {"mentat_conversation_run_attempts"}
)
_TASK_EXECUTION_SCHEMA_OBJECTS = frozenset(
    {"mentat_task_execution_attempts", "mentat_task_execution_reviews"}
)


def _run_schema_objects(schema_version: int) -> frozenset[str]:
    objects = _RUN_SCHEMA_OBJECTS
    if schema_version >= 11:
        objects |= _CONVERSATION_RESULT_SCHEMA_OBJECTS
    if schema_version >= 14:
        objects |= _CONVERSATION_ATTEMPT_SCHEMA_OBJECTS
    if schema_version >= 15:
        objects |= frozenset({"mentat_conversation_run_contexts"})
    if schema_version >= 19:
        objects |= _TASK_EXECUTION_SCHEMA_OBJECTS
    return objects


def _run_schema_fingerprint(
    connection: sqlite3.Connection,
    schema_version: int,
) -> str:
    objects = _run_schema_objects(schema_version)
    placeholders = ",".join("?" for _ in objects)
    rows = connection.execute(
        "SELECT type, name, tbl_name, sql FROM sqlite_master "
        f"WHERE tbl_name IN ({placeholders}) ORDER BY type, name",
        tuple(sorted(objects)),
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
        return _run_schema_fingerprint(connection, schema_version)
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


def _runtime_execution_document(
    identity: Mapping[str, str | None],
) -> tuple[str, str]:
    if not isinstance(identity, Mapping) or set(identity) != {
        "model",
        "provider",
        "reasoning_effort",
        "verification",
    }:
        raise RunRepositoryValidationError("conversation.execution_identity_invalid")
    model = identity.get("model")
    provider = identity.get("provider")
    effort = identity.get("reasoning_effort")
    verification = identity.get("verification")
    if (
        not isinstance(model, str)
        or not model
        or model.strip() != model
        or len(model) > 160
        or "\x00" in model
        or not isinstance(provider, str)
        or not provider
        or provider.strip() != provider
        or len(provider) > 160
        or "\x00" in provider
        or (
            effort is not None
            and (
                not isinstance(effort, str)
                or not effort
                or effort.strip() != effort
                or len(effort) > 64
                or "\x00" in effort
            )
        )
        or verification not in {"runtime_response", "runtime_launch_snapshot"}
    ):
        raise RunRepositoryValidationError("conversation.execution_identity_invalid")
    document = _canonical_json(
        {
            "contract": "mentat-runtime-execution-identity-v1",
            "model": model,
            "provider": provider,
            "reasoning_effort": effort,
            "verification": verification,
        },
        maximum=2_048,
        code="conversation.execution_identity_invalid",
    )
    return document, hashlib.sha256(document.encode("ascii")).hexdigest()


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


def conversation_turn_request_digest(
    *,
    conversation_id: str,
    agent_id: str,
    text: str,
) -> str:
    if (
        not isinstance(conversation_id, str)
        or _CONVERSATION_ID.fullmatch(conversation_id) is None
        or not isinstance(agent_id, str)
        or _identifier(agent_id) != agent_id
    ):
        raise RunRepositoryValidationError("conversation.request_invalid")
    # Canonical message validation fixes both the Unicode code-point bound and
    # the exact text that becomes durable authority.
    try:
        canonical_message_content(text, role="user")
    except ConversationRepositoryError as exc:
        raise RunRepositoryValidationError("conversation.request_invalid") from exc
    encoded = _canonical_json(
        {
            "agent_id": agent_id,
            "contract": "mentat-conversation-turn-v1",
            "conversation_id": conversation_id,
            "text": text,
        },
        # json.dumps uses ASCII escaping for deterministic digests. A valid
        # 6,000-code-point astral prompt can therefore require roughly 72 KiB
        # even though its canonical message storage is compact UTF-8.
        maximum=96 * 1024,
        code="conversation.request_invalid",
    )
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def default_runtime_capacity_evidence(
    *,
    runtime_type: str,
    binding_digest: str,
) -> tuple[str, int]:
    """Return the conservative private capacity evidence for current adapters."""

    if (
        not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", str(runtime_type))
        or not _SHA256.fullmatch(str(binding_digest))
    ):
        raise RunRepositoryValidationError("dispatch.capacity_invalid")
    encoded = _canonical_json(
        {
            "binding_digest": binding_digest,
            "contract": "mentat-runtime-capacity-v1",
            "runtime_type": runtime_type,
        },
        maximum=1_024,
        code="dispatch.capacity_invalid",
    )
    return hashlib.sha256(encoded.encode("ascii")).hexdigest(), 1


def declared_runtime_capacity_evidence(
    *,
    runtime_type: str,
    private_scope: str,
    limit: int,
) -> tuple[str, int]:
    """Hash one validated adapter declaration without persisting its scope."""

    if (
        not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", str(runtime_type))
        or not isinstance(private_scope, str)
        or not private_scope
        or private_scope.strip() != private_scope
        or "\x00" in private_scope
        or len(private_scope.encode("utf-8")) > 512
        or type(limit) is not int
        or not 1 <= limit <= 32
    ):
        raise RunRepositoryValidationError("dispatch.capacity_invalid")
    encoded = _canonical_json(
        {
            "contract": "mentat-runtime-capacity-v1",
            "private_scope": private_scope,
            "runtime_type": runtime_type,
        },
        maximum=1_024,
        code="dispatch.capacity_invalid",
    )
    return hashlib.sha256(encoded.encode("ascii")).hexdigest(), limit


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
        terminal_finalized = (
            int(row["terminal_finalized"])
            if "terminal_finalized" in row.keys()
            else int(str(row["status"]) in _TERMINAL_STATUSES)
        )
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
            or terminal_finalized not in {0, 1}
            or int(row["timeline_truncated"]) not in {0, 1}
        ):
            raise RunRepositoryError("run_repository.corrupt")
        if bool(terminal_finalized) and str(row["status"]) not in _TERMINAL_STATUSES:
            raise RunRepositoryError("run_repository.corrupt")
        run_id = _identifier(row["id"])
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise RunRepositoryError("run_repository.corrupt")
        for relationship_name in ("retry_of_run_id", "resume_of_run_id"):
            if relationship_name not in row.keys() or row[relationship_name] is None:
                continue
            relationship_id = _identifier(str(row[relationship_name]))
            if relationship_id == run_id:
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
        if "conversation_id" in row.keys():
            conversation_id = row["conversation_id"]
            turn_id = row["turn_id"]
            configuration_values = (
                row["agent_revision"],
                row["runtime_config_revision"],
                row["execution_config_json"],
                row["execution_config_digest"],
            )
            capacity_scope = row["capacity_scope_digest"]
            capacity_limit = row["admitted_capacity_limit"]
            binding_digest = row["runtime_binding_digest"]
            runtime_execution_json = (
                row["runtime_execution_json"]
                if "runtime_execution_json" in row.keys()
                else None
            )
            runtime_execution_digest = (
                row["runtime_execution_digest"]
                if "runtime_execution_digest" in row.keys()
                else None
            )
            if (runtime_execution_json is None) != (
                runtime_execution_digest is None
            ):
                raise RunRepositoryError("run_repository.corrupt")
            if (capacity_scope is None) != (capacity_limit is None):
                raise RunRepositoryError("run_repository.corrupt")
            if capacity_scope is not None:
                if (
                    not _SHA256.fullmatch(str(binding_digest))
                    or not _SHA256.fullmatch(str(capacity_scope))
                    or type(capacity_limit) is not int
                    or not 1 <= int(capacity_limit) <= 32
                ):
                    raise RunRepositoryError("run_repository.corrupt")
            if str(row["source"]) == "console" and conversation_id is not None:
                if (
                    not isinstance(conversation_id, str)
                    or _CONVERSATION_ID.fullmatch(conversation_id) is None
                    or not isinstance(turn_id, str)
                    or _TURN_ID.fullmatch(turn_id) is None
                    or row["task_id"] is not None
                    or row["task_revision"] is not None
                    or row["task_snapshot_json"] is not None
                    or row["agent_id"] is None
                    or row["runtime_config_id"] is None
                    or not _SHA256.fullmatch(str(binding_digest))
                    or any(value is None for value in configuration_values)
                    or capacity_scope is None
                    or capacity_limit is None
                    or type(row["agent_revision"]) is not int
                    or int(row["agent_revision"]) < 1
                    or type(row["runtime_config_revision"]) is not int
                    or int(row["runtime_config_revision"]) < 1
                    or not _SHA256.fullmatch(str(row["execution_config_digest"]))
                ):
                    raise RunRepositoryError("run_repository.corrupt")
                execution_config = _decode_json(
                    row["execution_config_json"],
                    expected=dict,
                    code="run_repository.corrupt",
                )
                canonical_config = _canonical_json(
                    execution_config,
                    maximum=16_384,
                    code="run_repository.corrupt",
                )
                if (
                    canonical_config != row["execution_config_json"]
                    or hashlib.sha256(canonical_config.encode("ascii")).hexdigest()
                    != row["execution_config_digest"]
                    or execution_config
                    != {
                        "admitted_capacity_limit": int(capacity_limit),
                        "agent_id": str(row["agent_id"]),
                        "agent_revision": int(row["agent_revision"]),
                        "capabilities": capabilities,
                        "capacity_scope_digest": str(capacity_scope),
                        "contract": "mentat-conversation-execution-v1",
                        "runtime_binding_digest": str(binding_digest),
                        "runtime_config_id": str(row["runtime_config_id"]),
                        "runtime_config_revision": int(
                            row["runtime_config_revision"]
                        ),
                        "runtime_selection": {
                            "evidence": "runtime_execution_json_after_start",
                            "mutation_guard": "runtime_binding",
                        },
                        "runtime_type": runtime_type,
                    }
                ):
                    raise RunRepositoryError("run_repository.corrupt")
                if runtime_execution_json is not None:
                    execution_identity = _decode_json(
                        runtime_execution_json,
                        expected=dict,
                        code="run_repository.corrupt",
                    )
                    if set(execution_identity) != {
                        "contract",
                        "model",
                        "provider",
                        "reasoning_effort",
                        "verification",
                    }:
                        raise RunRepositoryError("run_repository.corrupt")
                    identity_json, identity_digest = _runtime_execution_document(
                        {
                            "model": execution_identity["model"],
                            "provider": execution_identity["provider"],
                            "reasoning_effort": execution_identity["reasoning_effort"],
                            "verification": execution_identity["verification"],
                        }
                    )
                    if (
                        execution_identity["contract"]
                        != "mentat-runtime-execution-identity-v1"
                        or identity_json != runtime_execution_json
                        or identity_digest != runtime_execution_digest
                    ):
                        raise RunRepositoryError("run_repository.corrupt")
            elif (
                conversation_id is not None
                or turn_id is not None
                or any(value is not None for value in configuration_values)
                or runtime_execution_json is not None
                or runtime_execution_digest is not None
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
            version not in {
                RUN_SCHEMA_VERSION,
                8,
                9,
                10,
                CONVERSATION_SUBMISSION_SCHEMA_VERSION,
                12,
                13,
                14,
                15,
                16,
                18,
                DATABASE_SCHEMA_VERSION,
            }
            or not _run_schema_objects(version).issubset(names)
            or _run_schema_fingerprint(self.connection, version)
            != _expected_run_schema_fingerprint(version)
        ):
            raise RunRepositoryError("run_repository.schema_unsupported")

    def _active_capacity_count(
        self,
        *,
        runtime_type: str,
        binding_digest: str,
        capacity_scope_digest: str,
    ) -> int:
        """Count active work that consumes the same conservative adapter slot."""

        placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
        legacy_runtime_clause = (
            "OR (capacity_scope_digest IS NULL AND runtime_binding_digest IS NULL "
            "AND runtime_type = 'hermes') "
            if runtime_type == "hermes"
            else ""
        )
        row = self.connection.execute(
            "SELECT COUNT(*) FROM mentat_runs WHERE status IN ("
            + placeholders
            + ") AND (capacity_scope_digest = ? OR "
            "(capacity_scope_digest IS NULL AND runtime_type = ? "
            "AND runtime_binding_digest = ?) "
            + legacy_runtime_clause
            + ")",
            (
                *tuple(sorted(_ACTIVE_STATUSES)),
                capacity_scope_digest,
                runtime_type,
                binding_digest,
            ),
        ).fetchone()
        return int(row[0])

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
            if DATABASE_SCHEMA_VERSION >= 19:
                for row in self.connection.execute(
                    "SELECT created_at, updated_at FROM mentat_task_execution_attempts"
                ):
                    _ordered_timestamps(row[0], row[1])
                for row in self.connection.execute(
                    "SELECT created_at FROM mentat_task_execution_reviews"
                ):
                    _timestamp(row[0])
        except (TypeError, ValueError, sqlite3.Error, RunRepositoryError) as exc:
            raise RunRepositoryValidationError("run.timestamp_invalid") from exc

    def _enforce_store_budget(self) -> None:
        page_size = int(self.connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(self.connection.execute("PRAGMA page_count").fetchone()[0])
        if page_size * page_count > RUN_STORE_DATABASE_BUDGET:
            raise RunRepositoryValidationError("run.capacity_exceeded")

    def _promote_completed_task_execution(
        self,
        *,
        run_id: str,
        completed: bool,
        terminal_finalized: bool,
        partial: bool,
        occurred_at: str,
    ) -> None:
        """Atomically make one exact successful PT-3A attempt reviewable.

        A completed runtime observation is not enough by itself: this is only
        reachable in the same repository mutation that recorded the verified
        canonical Run terminal state. Any Task edit or ineligible source
        becomes durable ``completion_blocked`` evidence instead of overwriting
        operator work.
        """

        attempt = self.connection.execute(
            "SELECT task_id, task_revision, state, review_task_revision "
            "FROM mentat_task_execution_attempts WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if attempt is None or str(attempt["state"]) != "dispatched":
            return
        if not completed or not terminal_finalized or partial:
            return
        try:
            task = TaskRepository(self.connection).get(str(attempt["task_id"]))
            eligible = (
                task.revision == int(attempt["review_task_revision"])
                and task.document.get("source") == "dashboard"
                and workflow_stage(task.document) == "in_progress"
                and not task_is_deferred(task.document)
                and task.document.get("delegation") is None
            )
        except TaskRepositoryConflict:
            eligible = False
            task = None
        except (TaskRepositoryError, TypeError, ValueError) as exc:
            raise RunRepositoryUnavailable("dispatch.execution_unavailable") from exc
        if not eligible or task is None:
            self.connection.execute(
                "UPDATE mentat_task_execution_attempts SET "
                "state = 'completion_blocked', completion_reason = 'task_changed', "
                "updated_at = ? WHERE run_id = ? AND state = 'dispatched'",
                (occurred_at, run_id),
            )
            return
        next_task = dict(task.document)
        next_task.update(
            {
                "workflow_stage": "review",
                "planning_state": "review",
                "status": "needs attention",
                "review_required": True,
                "needs_attention": False,
                "completed_at": None,
                "updated_at": occurred_at,
            }
        )
        try:
            reviewed = TaskRepository(self.connection).replace(
                next_task,
                expected_revision=task.revision,
                # Only the same mutation that verified the terminal Run may
                # pass the planning-stage lock.  Ordinary Task edits remain
                # unable to manufacture a reviewable state.
                allow_execution_review_transition=True,
            )
        except TaskRepositoryConflict:
            self.connection.execute(
                "UPDATE mentat_task_execution_attempts SET "
                "state = 'completion_blocked', completion_reason = 'task_changed', "
                "updated_at = ? WHERE run_id = ? AND state = 'dispatched'",
                (occurred_at, run_id),
            )
            return
        except TaskRepositoryError as exc:
            raise RunRepositoryUnavailable("dispatch.execution_unavailable") from exc
        changed = self.connection.execute(
            "UPDATE mentat_task_execution_attempts SET state = 'review_ready', "
            "review_task_revision = ?, completion_reason = NULL, updated_at = ? "
            "WHERE run_id = ? AND state = 'dispatched'",
            (reviewed.revision, occurred_at, run_id),
        ).rowcount
        if changed != 1:
            raise RunRepositoryConflict("dispatch.execution_state_changed")

    def task_execution_attempts(self, task_id: str) -> tuple[dict[str, Any], ...]:
        """Return bounded, immutable private records for one Task execution UI."""

        identifier = _task_identifier(task_id)
        rows = self.connection.execute(
            "SELECT a.run_id, a.task_id, a.task_revision, a.agent_id, a.state, "
            "a.review_task_revision, a.completion_reason, a.created_at, a.updated_at, "
            "r.runtime_type, r.status, r.dispatch_state, r.partial, "
            "r.terminal_finalized, r.completed_at, rv.action AS review_action, rv.note "
            "FROM mentat_task_execution_attempts a "
            "JOIN mentat_runs r ON r.id = a.run_id "
            "LEFT JOIN mentat_task_execution_reviews rv ON rv.run_id = a.run_id "
            "WHERE a.task_id = ? ORDER BY a.created_at DESC, a.run_id DESC LIMIT 8",
            (identifier,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            if (
                str(row["task_id"]) != identifier
                or not _RUN_ID.fullmatch(str(row["run_id"]))
                or int(row["task_revision"]) < 1
                or str(row["state"])
                not in {
                    "dispatched", "review_ready", "completion_blocked",
                    "accepted", "changes_requested",
                }
                or str(row["status"]) not in _ALL_STATUSES
                or str(row["dispatch_state"]) not in _DISPATCH_STATES
                or int(row["partial"]) not in {0, 1}
                or int(row["terminal_finalized"]) not in {0, 1}
            ):
                raise RunRepositoryError("run_repository.corrupt")
            review_revision = row["review_task_revision"]
            if review_revision is not None and int(review_revision) < 1:
                raise RunRepositoryError("run_repository.corrupt")
            note = row["note"]
            if note is not None and (not isinstance(note, str) or len(note) > 2000):
                raise RunRepositoryError("run_repository.corrupt")
            result.append(
                {
                    "run_id": str(row["run_id"]),
                    "task_revision": int(row["task_revision"]),
                    "agent_id": str(row["agent_id"]),
                    "state": str(row["state"]),
                    "review_task_revision": (
                        None if review_revision is None else int(review_revision)
                    ),
                    "completion_reason": row["completion_reason"],
                    "runtime_type": str(row["runtime_type"]),
                    "status": str(row["status"]),
                    "dispatch_state": str(row["dispatch_state"]),
                    "partial": bool(row["partial"]),
                    "terminal_finalized": bool(row["terminal_finalized"]),
                    "created_at": _timestamp(row["created_at"]),
                    "updated_at": _timestamp(row["updated_at"]),
                    "completed_at": _timestamp(row["completed_at"], nullable=True),
                    "review_action": row["review_action"],
                    "review_note": note,
                }
            )
        return tuple(result)

    def review_task_execution(
        self,
        *,
        task_id: str,
        expected_revision: int,
        action: str,
        note: str | None,
        idempotency_key: str,
        now: str | None = None,
    ) -> TaskExecutionReviewResult:
        """Apply one operator-only exact review without erasing Run evidence."""

        identifier = _task_identifier(task_id)
        if type(expected_revision) is not int or expected_revision < 1:
            raise RunRepositoryValidationError("dispatch.revision_invalid")
        if action not in {"accept", "request_changes"}:
            raise RunRepositoryValidationError("dispatch.review_invalid")
        if note is not None and (
            not isinstance(note, str)
            or len(note) > 2000
            or "\x00" in note
            or note != note.strip()
        ):
            raise RunRepositoryValidationError("dispatch.review_invalid")
        if action == "accept" and note is not None:
            raise RunRepositoryValidationError("dispatch.review_invalid")
        if action == "request_changes" and not note:
            raise RunRepositoryValidationError("dispatch.review_invalid")
        try:
            key_bytes = idempotency_key.encode("utf-8")
        except (AttributeError, UnicodeEncodeError):
            key_bytes = b""
        if not 16 <= len(key_bytes) <= 256 or "\x00" in idempotency_key:
            raise RunRepositoryValidationError("dispatch.idempotency_key_invalid")
        request_digest = hashlib.sha256(
            _canonical_json(
                {
                    "contract": "mentat-task-review-v1",
                    "task_id": identifier,
                    "task_revision": expected_revision,
                    "action": action,
                    "note": note,
                },
                maximum=8_192,
                code="dispatch.review_invalid",
            ).encode("utf-8")
        ).hexdigest()
        key_digest = hashlib.sha256(key_bytes).hexdigest()
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            existing = self.connection.execute(
                "SELECT task_id, task_revision, run_id, action, result_task_revision, "
                "request_digest FROM mentat_task_execution_reviews WHERE key_digest = ?",
                (key_digest,),
            ).fetchone()
            if existing is not None:
                if str(existing["request_digest"]) != request_digest:
                    raise RunRepositoryConflict("dispatch.idempotency_conflict")
                return TaskExecutionReviewResult(
                    task_id=str(existing["task_id"]),
                    task_revision=int(existing["result_task_revision"]),
                    run_id=str(existing["run_id"]),
                    action=str(existing["action"]),
                    duplicate=True,
                )
            try:
                task = TaskRepository(self.connection).get(identifier)
            except TaskRepositoryConflict as exc:
                raise RunRepositoryConflict("dispatch.task_not_found") from exc
            if task.revision != expected_revision:
                raise RunRepositoryConflict("dispatch.task_changed")
            attempt = self.connection.execute(
                "SELECT a.run_id, a.state, a.review_task_revision, r.status, "
                "r.dispatch_state, r.partial, r.terminal_finalized "
                "FROM mentat_task_execution_attempts a "
                "JOIN mentat_runs r ON r.id = a.run_id "
                "WHERE a.task_id = ? AND a.state = 'review_ready' "
                "ORDER BY a.created_at DESC, a.run_id DESC LIMIT 1",
                (identifier,),
            ).fetchone()
            if (
                attempt is None
                or int(attempt["review_task_revision"] or 0) != expected_revision
                or str(attempt["status"]) != "completed"
                or str(attempt["dispatch_state"]) != "accepted"
                or bool(attempt["partial"])
                or not bool(attempt["terminal_finalized"])
                or task.document.get("source") != "dashboard"
                or workflow_stage(task.document) != "review"
                or task_is_deferred(task.document)
                or task.document.get("delegation") is not None
            ):
                raise RunRepositoryConflict("dispatch.review_unavailable")
            next_task = dict(task.document)
            if action == "accept":
                next_task.update(
                    {
                        "workflow_stage": "done",
                        "planning_state": "done",
                        "status": "completed",
                        "review_required": False,
                        "needs_attention": False,
                        "completed_at": occurred_at,
                        "updated_at": occurred_at,
                    }
                )
            else:
                next_task.update(
                    {
                        "workflow_stage": "planned",
                        "planning_state": "planned",
                        "status": "todo",
                        "review_required": False,
                        "needs_attention": False,
                        "completed_at": None,
                        "updated_at": occurred_at,
                    }
                )
            try:
                updated_task = TaskRepository(self.connection).replace(
                    next_task,
                    expected_revision=expected_revision,
                    allow_execution_review_transition=True,
                )
            except TaskRepositoryConflict as exc:
                raise RunRepositoryConflict("dispatch.task_changed") from exc
            run_id = str(attempt["run_id"])
            self.connection.execute(
                "INSERT INTO mentat_task_execution_reviews ("
                "key_digest, request_digest, task_id, task_revision, run_id, action, "
                "note, result_task_revision, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key_digest, request_digest, identifier, expected_revision,
                    run_id, action, note, updated_task.revision, occurred_at,
                ),
            )
            changed = self.connection.execute(
                "UPDATE mentat_task_execution_attempts SET state = ?, updated_at = ? "
                "WHERE run_id = ? AND state = 'review_ready' AND review_task_revision = ?",
                (
                    "accepted" if action == "accept" else "changes_requested",
                    occurred_at, run_id, expected_revision,
                ),
            ).rowcount
            if changed != 1:
                raise RunRepositoryConflict("dispatch.review_unavailable")
            return TaskExecutionReviewResult(
                task_id=identifier,
                task_revision=updated_task.revision,
                run_id=run_id,
                action=action,
            )

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
            + ") AND NOT (source = 'console' AND conversation_id IS NOT NULL "
            "AND runtime_type = 'hermes' AND terminal_finalized = 0) "
            "AND NOT EXISTS (SELECT 1 FROM mentat_runs AS successor "
            "WHERE successor.resume_of_run_id = mentat_runs.id "
            "AND successor.source = 'console' "
            "AND successor.status = 'reserved' "
            "AND successor.dispatch_state = 'reserved') "
            "AND NOT EXISTS (SELECT 1 FROM mentat_task_execution_attempts "
            "WHERE mentat_task_execution_attempts.run_id = mentat_runs.id) "
            "ORDER BY completed_at, created_at, id LIMIT ?",
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
    def _conversation_reservation(
        row: Mapping[str, Any],
        *,
        duplicate: bool = False,
    ) -> ConversationDispatchReservation:
        live_run_id = row["latest_run_id"]
        result_run_id = row["result_run_id"]
        if result_run_id is None:
            if (
                live_run_id is not None
                or row["state"] not in {"pending", "blocked", "cancelled"}
                or row["run_dispatch_state"] is not None
                or row["run_binding_digest"] is not None
                or row["result_dispatch_state"] is not None
                or row["result_binding_digest"] is not None
            ):
                raise RunRepositoryError("run_repository.corrupt")
            return ConversationDispatchReservation(
                conversation_id=str(row["conversation_id"]),
                message_id=str(row["user_message_id"]),
                turn_id=str(row["id"]),
                run_id=None,
                request_digest=str(row["request_digest"]),
                runtime_binding_digest=None,
                state=str(row["state"]),
                attempt_count=int(row["attempt_count"]),
                duplicate=duplicate,
            )
        # Terminal Run retention may remove the canonical Run row and clear the
        # Turn's foreign-key reference while the compact submission result
        # remains authoritative for exact idempotency replay.
        if live_run_id is not None and live_run_id != result_run_id:
            raise RunRepositoryError("run_repository.corrupt")
        run_dispatch_state = row["run_dispatch_state"]
        result_dispatch_state = row["result_dispatch_state"]
        run_binding_digest = row["run_binding_digest"]
        result_binding_digest = row["result_binding_digest"]
        if (
            result_dispatch_state is None
            or result_binding_digest is None
            or (
                run_dispatch_state is not None
                and run_dispatch_state != result_dispatch_state
            )
            or (
                run_binding_digest is not None
                and run_binding_digest != result_binding_digest
            )
        ):
            raise RunRepositoryError("run_repository.corrupt")
        return ConversationDispatchReservation(
            conversation_id=str(row["conversation_id"]),
            message_id=str(row["user_message_id"]),
            turn_id=str(row["id"]),
            run_id=str(result_run_id),
            request_digest=str(row["request_digest"]),
            runtime_binding_digest=str(result_binding_digest),
            state=str(result_dispatch_state),
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
            terminal_finalized=(
                bool(row["terminal_finalized"])
                if "terminal_finalized" in row.keys()
                else str(row["status"]) in _TERMINAL_STATUSES
            ),
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
            conversation_id=(
                str(row["conversation_id"])
                if "conversation_id" in row.keys() and row["conversation_id"] is not None
                else None
            ),
            turn_id=(
                str(row["turn_id"])
                if "turn_id" in row.keys() and row["turn_id"] is not None
                else None
            ),
            agent_revision=(
                int(row["agent_revision"])
                if "agent_revision" in row.keys() and row["agent_revision"] is not None
                else None
            ),
            runtime_config_revision=(
                int(row["runtime_config_revision"])
                if "runtime_config_revision" in row.keys()
                and row["runtime_config_revision"] is not None
                else None
            ),
            execution_config_digest=(
                str(row["execution_config_digest"])
                if "execution_config_digest" in row.keys()
                and row["execution_config_digest"] is not None
                else None
            ),
            runtime_execution_digest=(
                str(row["runtime_execution_digest"])
                if "runtime_execution_digest" in row.keys()
                and row["runtime_execution_digest"] is not None
                else None
            ),
            capacity_scope_digest=(
                str(row["capacity_scope_digest"])
                if "capacity_scope_digest" in row.keys()
                and row["capacity_scope_digest"] is not None
                else None
            ),
            admitted_capacity_limit=(
                int(row["admitted_capacity_limit"])
                if "admitted_capacity_limit" in row.keys()
                and row["admitted_capacity_limit"] is not None
                else None
            ),
            retry_of_run_id=(
                str(row["retry_of_run_id"])
                if "retry_of_run_id" in row.keys()
                and row["retry_of_run_id"] is not None
                else None
            ),
            resume_of_run_id=(
                str(row["resume_of_run_id"])
                if "resume_of_run_id" in row.keys()
                and row["resume_of_run_id"] is not None
                else None
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

    @staticmethod
    def _idempotency_key_digest(idempotency_key: str) -> str:
        try:
            encoded = idempotency_key.encode("utf-8")
        except (AttributeError, UnicodeEncodeError):
            encoded = b""
        if not 16 <= len(encoded) <= 256 or b"\x00" in encoded:
            raise RunRepositoryValidationError(
                "conversation.idempotency_key_invalid"
            )
        return hashlib.sha256(encoded).hexdigest()

    def _conversation_turn_by_key_digest(
        self,
        key_digest: str,
    ) -> sqlite3.Row | None:
        rows = self.connection.execute(
            """
            SELECT t.*, r.dispatch_state AS run_dispatch_state,
                   r.runtime_binding_digest AS run_binding_digest,
                   s.run_id AS result_run_id,
                   s.dispatch_state AS result_dispatch_state,
                   s.runtime_binding_digest AS result_binding_digest
            FROM mentat_conversation_turns AS t
            LEFT JOIN mentat_runs AS r ON r.id = t.latest_run_id
            LEFT JOIN mentat_conversation_submission_results AS s
                   ON s.turn_id = t.id
            WHERE t.idempotency_key_digest = ?
            ORDER BY t.id
            LIMIT 2
            """,
            (key_digest,),
        ).fetchall()
        if len(rows) > 1:
            raise RunRepositoryError("run_repository.corrupt")
        return rows[0] if rows else None

    def lookup_conversation_turn_retry(
        self,
        *,
        idempotency_key: str,
        conversation_id: str,
        agent_id: str,
        text: str,
        context_digest: str | None = None,
    ) -> ConversationDispatchReservation | None:
        """Resolve exact Send replay before consulting mutable Agent state."""

        key_digest = self._idempotency_key_digest(idempotency_key)
        request_digest = conversation_turn_request_digest(
            conversation_id=conversation_id,
            agent_id=agent_id,
            text=text,
        )
        row = self._conversation_turn_by_key_digest(key_digest)
        if row is None:
            return None
        if (
            str(row["conversation_id"]) != conversation_id
            or str(row["request_digest"]) != request_digest
        ):
            raise RunRepositoryConflict("conversation.idempotency_conflict")
        stored_context = self.connection.execute(
            "SELECT context_digest FROM mentat_conversation_run_contexts "
            "WHERE run_id = COALESCE(?, ?)",
            (row["result_run_id"], row["latest_run_id"]),
        ).fetchone()
        if context_digest is not None and (
            stored_context is None
            or str(stored_context["context_digest"]) != context_digest
        ):
            raise RunRepositoryConflict("conversation.idempotency_conflict")
        return self._conversation_reservation(row, duplicate=True)

    def conversation_turn_reservation(
        self,
        turn_id: str,
    ) -> ConversationDispatchReservation:
        """Read one exact canonical Conversation dispatch reservation."""

        if not isinstance(turn_id, str) or _TURN_ID.fullmatch(turn_id) is None:
            raise RunRepositoryValidationError("conversation.identifier_invalid")
        row = self._conversation_turn_by_id(turn_id)
        if row is None:
            raise RunRepositoryConflict("conversation.turn_not_found")
        return self._conversation_reservation(row)

    def conversation_continuation_predecessor(
        self,
        *,
        run_id: str,
        expected_source_run_id: str | None = None,
    ) -> RunRecord | None:
        """Resolve one persisted FIFO predecessor without trusting the caller."""

        identifier = _identifier(run_id)
        if expected_source_run_id is not None:
            expected_source_run_id = _identifier(expected_source_run_id)
        successor = self.connection.execute(
            "SELECT * FROM mentat_runs WHERE id = ?",
            (identifier,),
        ).fetchone()
        if (
            successor is None
            or successor["source"] != "console"
            or successor["conversation_id"] is None
            or successor["turn_id"] is None
        ):
            raise RunRepositoryConflict("conversation.continuation_changed")
        predecessor_id = successor["resume_of_run_id"]
        if predecessor_id is None:
            if expected_source_run_id is not None:
                raise RunRepositoryConflict("conversation.continuation_changed")
            return None
        predecessor_id = _identifier(str(predecessor_id))
        if (
            predecessor_id == identifier
            or expected_source_run_id is not None
            and predecessor_id != expected_source_run_id
        ):
            raise RunRepositoryConflict("conversation.continuation_changed")
        successor_turn = self.connection.execute(
            "SELECT queue_ordinal FROM mentat_conversation_turns "
            "WHERE id = ? AND conversation_id = ?",
            (successor["turn_id"], successor["conversation_id"]),
        ).fetchone()
        if successor_turn is None:
            raise RunRepositoryError("run_repository.corrupt")
        latest_prior = self.connection.execute(
            "SELECT latest_run_id FROM mentat_conversation_turns "
            "WHERE conversation_id = ? AND queue_ordinal < ? "
            "AND latest_run_id IS NOT NULL "
            "ORDER BY queue_ordinal DESC, id DESC LIMIT 1",
            (
                successor["conversation_id"],
                int(successor_turn["queue_ordinal"]),
            ),
        ).fetchone()
        predecessor = self.connection.execute(
            "SELECT * FROM mentat_runs WHERE id = ?",
            (predecessor_id,),
        ).fetchone()
        if (
            latest_prior is None
            or latest_prior["latest_run_id"] != predecessor_id
            or predecessor is None
            or predecessor["conversation_id"] != successor["conversation_id"]
            or predecessor["agent_id"] != successor["agent_id"]
            or predecessor["runtime_type"] != successor["runtime_type"]
            or predecessor["runtime_binding_digest"]
            != successor["runtime_binding_digest"]
            or predecessor["status"] != "completed"
            or predecessor["dispatch_state"] != "accepted"
            or bool(predecessor["partial"])
            or not bool(predecessor["terminal_finalized"])
        ):
            raise RunRepositoryConflict("conversation.continuation_changed")
        return self._run_record(predecessor)

    def codex_continuation_for_blocked_turn(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        expected_revision: int,
        expected_message_revision: int,
        binding_digest: str,
    ) -> tuple[
        ConversationDispatchReservation,
        bool,
        str | None,
        str | None,
    ]:
        """Revalidate one blocked head and its immediately prior executed Turn."""

        if (
            _CONVERSATION_ID.fullmatch(str(conversation_id)) is None
            or _TURN_ID.fullmatch(str(turn_id)) is None
            or type(expected_revision) is not int
            or expected_revision < 1
            or type(expected_message_revision) is not int
            or expected_message_revision < 1
            or not isinstance(binding_digest, str)
            or _SHA256.fullmatch(binding_digest) is None
        ):
            raise RunRepositoryValidationError("conversation.turn_invalid")
        self.authority_receipt(required=True)
        head = self._oldest_queue_active_turn(conversation_id)
        if (
            head is None
            or head["id"] != turn_id
            or head["state"] != "blocked"
            or int(head["revision"]) != expected_revision
            or int(head["message_revision"]) != expected_message_revision
        ):
            raise RunRepositoryConflict("conversation.turn_changed")
        reservation = self.conversation_turn_reservation(turn_id)
        prior = self.connection.execute(
            """
            SELECT t.state, t.latest_run_id, r.status, r.partial,
                   r.runtime_type, r.runtime_binding_digest, r.runtime_run_ref,
                   s.run_id AS result_run_id
            FROM mentat_conversation_turns AS t
            LEFT JOIN mentat_runs AS r ON r.id = t.latest_run_id
            LEFT JOIN mentat_conversation_submission_results AS s
                   ON s.turn_id = t.id
            WHERE t.conversation_id = ? AND t.queue_ordinal < ?
              AND (t.latest_run_id IS NOT NULL OR s.run_id IS NOT NULL)
            ORDER BY t.queue_ordinal DESC, t.id DESC
            LIMIT 1
            """,
            (conversation_id, int(head["queue_ordinal"])),
        ).fetchone()
        if prior is None:
            return reservation, True, None, None
        reference = prior["runtime_run_ref"]
        eligible = (
            prior["state"] == "consumed"
            and prior["latest_run_id"] is not None
            and prior["result_run_id"] == prior["latest_run_id"]
            and prior["status"] == "completed"
            and not bool(prior["partial"])
            and prior["runtime_type"] == "codex"
            and prior["runtime_binding_digest"] == binding_digest
            and isinstance(reference, str)
            and bool(reference)
        )
        return (
            reservation,
            eligible,
            str(reference) if eligible else None,
            str(prior["latest_run_id"]) if eligible else None,
        )

    def edit_queued_conversation_turn(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        expected_revision: int,
        expected_message_revision: int,
        text: str,
        now: str | None = None,
    ) -> tuple[ConversationTurnRecord, ConversationMessageRecord]:
        """Replace one undispatched Turn's canonical user text under exact CAS."""

        if (
            not isinstance(conversation_id, str)
            or _CONVERSATION_ID.fullmatch(conversation_id) is None
            or not isinstance(turn_id, str)
            or _TURN_ID.fullmatch(turn_id) is None
            or type(expected_revision) is not int
            or expected_revision < 1
            or type(expected_message_revision) is not int
            or expected_message_revision < 1
        ):
            raise RunRepositoryValidationError("conversation.turn_invalid")
        try:
            _, content_json, content_bytes = canonical_message_content(
                text, role="user"
            )
        except ConversationRepositoryError as exc:
            raise RunRepositoryValidationError("conversation.request_invalid") from exc
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            row = self.connection.execute(
                """
                SELECT t.*, m.revision AS message_revision,
                       m.content_bytes AS old_content_bytes,
                       m.state AS message_state, c.agent_id, c.title_source
                FROM mentat_conversation_turns AS t
                JOIN mentat_conversation_messages AS m
                  ON m.id = t.user_message_id
                 AND m.conversation_id = t.conversation_id
                JOIN mentat_conversations AS c ON c.id = t.conversation_id
                WHERE t.id = ? AND t.conversation_id = ?
                """,
                (turn_id, conversation_id),
            ).fetchone()
            if row is None:
                raise RunRepositoryConflict("conversation.turn_not_found")
            if (
                row["state"] not in {"pending", "blocked"}
                or row["latest_run_id"] is not None
                or row["message_state"] != "accepted"
            ):
                raise RunRepositoryConflict("conversation.turn_not_editable")
            if (
                int(row["revision"]) != expected_revision
                or int(row["message_revision"]) != expected_message_revision
            ):
                raise RunRepositoryConflict("conversation.turn_changed")
            total = int(
                self.connection.execute(
                    "SELECT COALESCE(SUM(content_bytes), 0) "
                    "FROM mentat_conversation_messages"
                ).fetchone()[0]
            )
            if total - int(row["old_content_bytes"]) + content_bytes > MAX_TOTAL_MESSAGE_BYTES:
                raise RunRepositoryValidationError("conversation.capacity_exceeded")
            request_digest = conversation_turn_request_digest(
                conversation_id=conversation_id,
                agent_id=str(row["agent_id"]),
                text=text,
            )
            updated_message = self.connection.execute(
                "UPDATE mentat_conversation_messages SET content_json = ?, "
                "content_bytes = ?, revision = revision + 1, updated_at = ? "
                "WHERE id = ? AND conversation_id = ? AND revision = ? "
                "AND state = 'accepted'",
                (
                    content_json,
                    content_bytes,
                    occurred_at,
                    row["user_message_id"],
                    conversation_id,
                    expected_message_revision,
                ),
            ).rowcount
            updated_turn = self.connection.execute(
                "UPDATE mentat_conversation_turns SET request_digest = ?, "
                "revision = revision + 1, updated_at = ? "
                "WHERE id = ? AND conversation_id = ? AND revision = ? "
                "AND state IN ('pending', 'blocked') AND latest_run_id IS NULL",
                (
                    request_digest,
                    occurred_at,
                    turn_id,
                    conversation_id,
                    expected_revision,
                ),
            ).rowcount
            if updated_message != 1 or updated_turn != 1:
                raise RunRepositoryConflict("conversation.turn_changed")
            title = " ".join(text.split())[:80]
            self.connection.execute(
                "UPDATE mentat_conversations SET title = CASE "
                "WHEN title_source = 'first_prompt' AND ? = 1 THEN ? ELSE title END, "
                "revision = revision + 1, updated_at = ? WHERE id = ?",
                (int(row["queue_ordinal"]), title, occurred_at, conversation_id),
            )
            turn_row = self.connection.execute(
                "SELECT * FROM mentat_conversation_turns WHERE id = ?",
                (turn_id,),
            ).fetchone()
            message_row = self.connection.execute(
                "SELECT * FROM mentat_conversation_messages WHERE id = ?",
                (row["user_message_id"],),
            ).fetchone()
            if turn_row is None or message_row is None:
                raise RunRepositoryError("run_repository.corrupt")
            return (
                conversation_turn_record(turn_row),
                conversation_message_record(message_row),
            )

    def cancel_queued_conversation_turn(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        expected_revision: int,
        expected_message_revision: int,
        now: str | None = None,
    ) -> tuple[ConversationTurnRecord, ConversationMessageRecord]:
        """Durably cancel one undispatched queued Turn under exact CAS."""

        if (
            not isinstance(conversation_id, str)
            or _CONVERSATION_ID.fullmatch(conversation_id) is None
            or not isinstance(turn_id, str)
            or _TURN_ID.fullmatch(turn_id) is None
            or type(expected_revision) is not int
            or expected_revision < 1
            or type(expected_message_revision) is not int
            or expected_message_revision < 1
        ):
            raise RunRepositoryValidationError("conversation.turn_invalid")
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            row = self.connection.execute(
                """
                SELECT t.*, m.revision AS message_revision,
                       m.state AS message_state
                FROM mentat_conversation_turns AS t
                JOIN mentat_conversation_messages AS m
                  ON m.id = t.user_message_id
                 AND m.conversation_id = t.conversation_id
                WHERE t.id = ? AND t.conversation_id = ?
                """,
                (turn_id, conversation_id),
            ).fetchone()
            if row is None:
                raise RunRepositoryConflict("conversation.turn_not_found")
            if (
                row["state"] not in {"pending", "blocked"}
                or row["latest_run_id"] is not None
                or row["message_state"] != "accepted"
            ):
                raise RunRepositoryConflict("conversation.turn_not_cancellable")
            if (
                int(row["revision"]) != expected_revision
                or int(row["message_revision"]) != expected_message_revision
            ):
                raise RunRepositoryConflict("conversation.turn_changed")
            cancelling_blocked_head = False
            if row["state"] == "blocked":
                head = self._oldest_queue_active_turn(conversation_id)
                if head is None:
                    raise RunRepositoryConflict("conversation.queue_state_invalid")
                cancelling_blocked_head = head["id"] == row["id"]
            updated_message = self.connection.execute(
                "UPDATE mentat_conversation_messages SET state = 'cancelled', "
                "revision = revision + 1, updated_at = ? "
                "WHERE id = ? AND conversation_id = ? AND revision = ? "
                "AND state = 'accepted'",
                (
                    occurred_at,
                    row["user_message_id"],
                    conversation_id,
                    expected_message_revision,
                ),
            ).rowcount
            updated_turn = self.connection.execute(
                "UPDATE mentat_conversation_turns SET state = 'cancelled', "
                "blocked_reason = NULL, revision = revision + 1, updated_at = ? "
                "WHERE id = ? AND conversation_id = ? AND revision = ? "
                "AND state IN ('pending', 'blocked') AND latest_run_id IS NULL",
                (occurred_at, turn_id, conversation_id, expected_revision),
            ).rowcount
            if updated_message != 1 or updated_turn != 1:
                raise RunRepositoryConflict("conversation.turn_changed")
            if cancelling_blocked_head:
                successor = self._oldest_queue_active_turn(conversation_id)
                if successor is not None:
                    if (
                        successor["latest_run_id"] is not None
                        or successor["message_state"] != "accepted"
                    ):
                        raise RunRepositoryConflict(
                            "conversation.queue_state_invalid"
                        )
                    if successor["state"] == "pending":
                        successor_updated = self.connection.execute(
                            "UPDATE mentat_conversation_turns SET state = 'blocked', "
                            "blocked_reason = ?, revision = revision + 1, "
                            "updated_at = ? WHERE id = ? AND revision = ? "
                            "AND state = 'pending' AND latest_run_id IS NULL",
                            (
                                row["blocked_reason"],
                                occurred_at,
                                successor["id"],
                                successor["revision"],
                            ),
                        ).rowcount
                        if successor_updated != 1:
                            raise RunRepositoryConflict(
                                "conversation.state_changed"
                            )
                    elif successor["state"] != "blocked":
                        raise RunRepositoryConflict(
                            "conversation.queue_state_invalid"
                        )
            self.connection.execute(
                "UPDATE mentat_conversations SET revision = revision + 1, "
                "updated_at = ? WHERE id = ?",
                (occurred_at, conversation_id),
            )
            turn_row = self.connection.execute(
                "SELECT * FROM mentat_conversation_turns WHERE id = ?",
                (turn_id,),
            ).fetchone()
            message_row = self.connection.execute(
                "SELECT * FROM mentat_conversation_messages WHERE id = ?",
                (row["user_message_id"],),
            ).fetchone()
            if turn_row is None or message_row is None:
                raise RunRepositoryError("run_repository.corrupt")
            return (
                conversation_turn_record(turn_row),
                conversation_message_record(message_row),
            )

    @staticmethod
    def _conversation_admission_documents(
        admission: ConversationRunAdmission,
        *,
        text: str,
    ) -> tuple[str, str, str, str]:
        if not isinstance(admission, ConversationRunAdmission):
            raise RunRepositoryValidationError("conversation.admission_invalid")
        if (
            _RUN_ID.fullmatch(str(admission.run_id)) is None
            or _ID.fullmatch(str(admission.agent_id)) is None
            or not isinstance(admission.agent_name, str)
            or not admission.agent_name
            or admission.agent_name.strip() != admission.agent_name
            or len(admission.agent_name) > 160
            or type(admission.agent_revision) is not int
            or admission.agent_revision < 1
            or re.fullmatch(
                r"[a-z][a-z0-9_-]{0,31}", str(admission.runtime_type)
            )
            is None
            or _ID.fullmatch(str(admission.runtime_config_id)) is None
            or type(admission.runtime_config_revision) is not int
            or admission.runtime_config_revision < 1
            or _SHA256.fullmatch(str(admission.runtime_binding_digest)) is None
            or _SHA256.fullmatch(str(admission.capacity_scope_digest)) is None
            or type(admission.capacity_limit) is not int
            or not 1 <= admission.capacity_limit <= 32
            or (
                admission.predecessor_run_id is not None
                and (
                    _RUN_ID.fullmatch(str(admission.predecessor_run_id)) is None
                    or admission.predecessor_run_id == admission.run_id
                )
            )
        ):
            raise RunRepositoryValidationError("conversation.admission_invalid")
        capabilities = tuple(sorted(set(admission.capabilities)))
        if (
            capabilities != admission.capabilities
            or any(
                re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value) is None
                for value in capabilities
            )
        ):
            raise RunRepositoryValidationError("conversation.admission_invalid")
        capabilities_json = _canonical_json(
            list(capabilities),
            maximum=8_192,
            code="conversation.admission_invalid",
        )
        execution_config_json = _canonical_json(
            {
                "admitted_capacity_limit": admission.capacity_limit,
                "agent_id": admission.agent_id,
                "agent_revision": admission.agent_revision,
                "capabilities": list(capabilities),
                "capacity_scope_digest": admission.capacity_scope_digest,
                "contract": "mentat-conversation-execution-v1",
                "runtime_binding_digest": admission.runtime_binding_digest,
                "runtime_config_id": admission.runtime_config_id,
                "runtime_config_revision": admission.runtime_config_revision,
                "runtime_selection": {
                    "evidence": "runtime_execution_json_after_start",
                    "mutation_guard": "runtime_binding",
                },
                "runtime_type": admission.runtime_type,
            },
            maximum=16_384,
            code="conversation.execution_config_invalid",
        )
        execution_config_digest = hashlib.sha256(
            execution_config_json.encode("ascii")
        ).hexdigest()
        prompt_excerpt, prompt_truncated = bounded_excerpt(text, 500)
        details_json = _canonical_json(
            {
                "agent_id": admission.agent_id,
                "agent_name": admission.agent_name,
                "artifacts": [],
                "attachments": [],
                "connection_binding_id": "local-default",
                "duration_seconds": None,
                "error_excerpt": "",
                "error_truncated": False,
                "model": "",
                "new_session_state": None,
                "prompt_excerpt": prompt_excerpt,
                "prompt_truncated": prompt_truncated,
                "response_excerpt": "",
                "response_truncated": False,
                "session_id": None,
                "starts_new_session": False,
                "transport_mode": "local",
                "usage": None,
            },
            maximum=RUN_DETAILS_LIMIT,
            code="run.details_invalid",
        )
        return (
            capabilities_json,
            execution_config_json,
            execution_config_digest,
            details_json,
        )

    def _oldest_queue_active_turn(
        self,
        conversation_id: str,
    ) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT t.*, m.content_json AS message_content_json,
                   m.content_bytes AS message_content_bytes,
                   m.revision AS message_revision,
                   m.state AS message_state
            FROM mentat_conversation_turns AS t
            JOIN mentat_conversation_messages AS m
              ON m.id = t.user_message_id
             AND m.conversation_id = t.conversation_id
            WHERE t.conversation_id = ?
              AND t.state IN ('pending', 'blocked', 'dispatching')
            ORDER BY t.queue_ordinal, t.id
            LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()

    def _block_oldest_pending_turn(
        self,
        *,
        conversation_id: str,
        reason: str,
        occurred_at: str,
    ) -> bool:
        if reason not in {"capacity", "failed", "stopped", "interrupted", "unknown", "partial"}:
            raise RunRepositoryValidationError("conversation.blocked_reason_invalid")
        head = self._oldest_queue_active_turn(conversation_id)
        if head is None or head["state"] == "blocked":
            return False
        if head["state"] != "pending" or head["latest_run_id"] is not None:
            raise RunRepositoryConflict("conversation.queue_state_invalid")
        updated = self.connection.execute(
            "UPDATE mentat_conversation_turns SET state = 'blocked', "
            "blocked_reason = ?, revision = revision + 1, updated_at = ? "
            "WHERE id = ? AND revision = ? AND state = 'pending' "
            "AND latest_run_id IS NULL",
            (reason, occurred_at, head["id"], head["revision"]),
        ).rowcount
        if updated != 1:
            raise RunRepositoryConflict("conversation.state_changed")
        self.connection.execute(
            "UPDATE mentat_conversations SET revision = revision + 1, "
            "updated_at = ? WHERE id = ?",
            (occurred_at, conversation_id),
        )
        return True

    def _reserve_oldest_queued_conversation_turn(
        self,
        *,
        conversation_id: str,
        admission: ConversationRunAdmission,
        allow_blocked: bool,
        expected_turn_id: str | None,
        expected_turn_revision: int | None,
        expected_message_revision: int | None,
        occurred_at: str,
    ) -> ConversationDispatchReservation | None:
        documents = self._conversation_admission_documents(admission, text="placeholder")
        conversation = self.connection.execute(
            "SELECT * FROM mentat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if conversation is None:
            raise RunRepositoryConflict("conversation.not_found")
        if conversation["state"] == "archived":
            # Archive is reversible presentation state. It must not roll back
            # a verified result or start queued work while hidden. Make the
            # exact head explicitly continuable after restore.
            self._block_oldest_pending_turn(
                conversation_id=conversation_id,
                reason="partial",
                occurred_at=occurred_at,
            )
            return None
        if conversation["state"] != "active":
            raise RunRepositoryConflict("conversation.not_active")
        if conversation["agent_id"] != admission.agent_id:
            raise RunRepositoryConflict("conversation.agent_changed")
        agent = self.connection.execute(
            """
            SELECT a.revision, a.runtime_config_id, a.capabilities_json,
                   1 AS runtime_config_revision,
                   c.runtime_type, c.runtime_agent_ref
            FROM mentat_agents AS a
            JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id
            WHERE a.id = ?
            """,
            (admission.agent_id,),
        ).fetchone()
        if agent is None:
            raise RunRepositoryConflict("conversation.agent_missing")
        live_capabilities = _decode_json(
            agent["capabilities_json"],
            expected=list,
            code="run_repository.corrupt",
        )
        if (
            int(agent["revision"]) != admission.agent_revision
            or str(agent["runtime_config_id"]) != admission.runtime_config_id
            or int(agent["runtime_config_revision"])
            != admission.runtime_config_revision
            or str(agent["runtime_type"]) != admission.runtime_type
            or live_capabilities != list(admission.capabilities)
            or runtime_binding_digest(
                agent_id=admission.agent_id,
                runtime_type=admission.runtime_type,
                runtime_config_id=admission.runtime_config_id,
                runtime_agent_ref=str(agent["runtime_agent_ref"]),
                capabilities=live_capabilities,
            )
            != admission.runtime_binding_digest
        ):
            raise RunRepositoryConflict("conversation.binding_changed")
        active = self.connection.execute(
            "SELECT 1 FROM mentat_runs AS r WHERE conversation_id = ? AND ("
            "status IN ("
            + ",".join("?" for _ in _ACTIVE_STATUSES)
            + ") OR (runtime_type = 'hermes' AND status IN ("
            + ",".join("?" for _ in _TERMINAL_STATUSES)
            + ") AND terminal_finalized = 0)) "
            "LIMIT 1",
            (
                conversation_id,
                *tuple(sorted(_ACTIVE_STATUSES)),
                *tuple(sorted(_TERMINAL_STATUSES)),
            ),
        ).fetchone()
        if active is not None:
            raise RunRepositoryConflict("conversation.active_run")
        head = self._oldest_queue_active_turn(conversation_id)
        if head is None:
            return None
        if expected_turn_id is not None and head["id"] != expected_turn_id:
            raise RunRepositoryConflict("conversation.turn_changed")
        if expected_turn_revision is not None and int(head["revision"]) != expected_turn_revision:
            raise RunRepositoryConflict("conversation.turn_changed")
        if expected_message_revision is not None and int(head["message_revision"]) != expected_message_revision:
            raise RunRepositoryConflict("conversation.turn_changed")
        if (
            head["state"] not in ({"pending", "blocked"} if allow_blocked else {"pending"})
            or head["latest_run_id"] is not None
            or head["message_state"] != "accepted"
        ):
            if not allow_blocked and head["state"] == "blocked":
                return None
            raise RunRepositoryConflict("conversation.turn_not_continuable")
        content = _decode_json(
            head["message_content_json"],
            expected=dict,
            code="run_repository.corrupt",
        )
        try:
            text = content["parts"][0]["text"]
            _, canonical_json, content_bytes = canonical_message_content(
                text,
                role="user",
            )
        except (KeyError, IndexError, TypeError, ConversationRepositoryError) as exc:
            raise RunRepositoryError("run_repository.corrupt") from exc
        if (
            canonical_json != head["message_content_json"]
            or content_bytes != int(head["message_content_bytes"])
            or conversation_turn_request_digest(
                conversation_id=conversation_id,
                agent_id=admission.agent_id,
                text=text,
            )
            != head["request_digest"]
        ):
            raise RunRepositoryError("run_repository.corrupt")
        if admission.predecessor_run_id is not None:
            predecessor = self.connection.execute(
                """
                SELECT r.*, t.queue_ordinal AS predecessor_ordinal,
                       t.state AS predecessor_turn_state
                FROM mentat_runs AS r
                JOIN mentat_conversation_turns AS t
                  ON t.id = r.turn_id
                 AND t.conversation_id = r.conversation_id
                WHERE r.id = ?
                """,
                (admission.predecessor_run_id,),
            ).fetchone()
            latest_prior = self.connection.execute(
                "SELECT latest_run_id FROM mentat_conversation_turns "
                "WHERE conversation_id = ? AND queue_ordinal < ? "
                "AND latest_run_id IS NOT NULL "
                "ORDER BY queue_ordinal DESC, id DESC LIMIT 1",
                (conversation_id, int(head["queue_ordinal"])),
            ).fetchone()
            if (
                predecessor is None
                or latest_prior is None
                or latest_prior["latest_run_id"]
                != admission.predecessor_run_id
                or predecessor["conversation_id"] != conversation_id
                or predecessor["agent_id"] != admission.agent_id
                or predecessor["runtime_type"] != admission.runtime_type
                or predecessor["runtime_binding_digest"]
                != admission.runtime_binding_digest
                or predecessor["status"] != "completed"
                or predecessor["dispatch_state"] != "accepted"
                or bool(predecessor["partial"])
                or not bool(predecessor["terminal_finalized"])
                or predecessor["predecessor_turn_state"] != "consumed"
                or int(predecessor["predecessor_ordinal"])
                >= int(head["queue_ordinal"])
            ):
                raise RunRepositoryConflict(
                    "conversation.continuation_changed"
                )
        documents = self._conversation_admission_documents(admission, text=text)
        if self._active_capacity_count(
            runtime_type=admission.runtime_type,
            binding_digest=admission.runtime_binding_digest,
            capacity_scope_digest=admission.capacity_scope_digest,
        ) >= admission.capacity_limit:
            if head["state"] != "blocked" or head["blocked_reason"] != "capacity":
                updated = self.connection.execute(
                    "UPDATE mentat_conversation_turns SET state = 'blocked', "
                    "blocked_reason = 'capacity', revision = revision + 1, "
                    "updated_at = ? WHERE id = ? AND revision = ? "
                    "AND state IN ('pending', 'blocked') AND latest_run_id IS NULL",
                    (occurred_at, head["id"], head["revision"]),
                ).rowcount
                if updated != 1:
                    raise RunRepositoryConflict("conversation.state_changed")
                self.connection.execute(
                    "UPDATE mentat_conversations SET revision = revision + 1, "
                    "updated_at = ? WHERE id = ?",
                    (occurred_at, conversation_id),
                )
            return None
        self._ensure_run_capacity((admission.run_id,))
        capabilities_json, execution_json, execution_digest, details_json = documents
        self.connection.execute(
            """
            INSERT INTO mentat_runs (
                id, source, task_id, task_revision, task_snapshot_json,
                agent_id, runtime_type, runtime_config_id,
                runtime_binding_digest, capabilities_json, status,
                dispatch_state, details_json, created_at, updated_at,
                conversation_id, turn_id, agent_revision,
                runtime_config_revision, execution_config_json,
                execution_config_digest, capacity_scope_digest,
                admitted_capacity_limit, resume_of_run_id
            ) VALUES (
                ?, 'console', NULL, NULL, NULL, ?, ?, ?, ?, ?,
                'reserved', 'reserved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                admission.run_id,
                admission.agent_id,
                admission.runtime_type,
                admission.runtime_config_id,
                admission.runtime_binding_digest,
                capabilities_json,
                details_json,
                occurred_at,
                occurred_at,
                conversation_id,
                head["id"],
                admission.agent_revision,
                admission.runtime_config_revision,
                execution_json,
                execution_digest,
                admission.capacity_scope_digest,
                admission.capacity_limit,
                admission.predecessor_run_id,
            ),
        )
        message_updated = self.connection.execute(
            "UPDATE mentat_conversation_messages SET run_id = ?, "
            "updated_at = ? WHERE id = ? AND conversation_id = ? "
            "AND revision = ? AND state = 'accepted' AND run_id IS NULL",
            (
                admission.run_id,
                occurred_at,
                head["user_message_id"],
                conversation_id,
                head["message_revision"],
            ),
        ).rowcount
        turn_updated = self.connection.execute(
            "UPDATE mentat_conversation_turns SET state = 'dispatching', "
            "blocked_reason = NULL, latest_run_id = ?, revision = revision + 1, "
            "updated_at = ? WHERE id = ? AND conversation_id = ? "
            "AND revision = ? AND state IN ('pending', 'blocked') "
            "AND latest_run_id IS NULL",
            (
                admission.run_id,
                occurred_at,
                head["id"],
                conversation_id,
                head["revision"],
            ),
        ).rowcount
        if message_updated != 1 or turn_updated != 1:
            raise RunRepositoryConflict("conversation.state_changed")
        self.connection.execute(
            "UPDATE mentat_conversations SET revision = revision + 1, "
            "updated_at = ? WHERE id = ?",
            (occurred_at, conversation_id),
        )
        self._append_event_record(
            _event_from_domain(
                AgentEvent(
                    id=(
                        "event_"
                        + hashlib.sha256(
                            f"{head['id']}:reserved".encode("utf-8")
                        ).hexdigest()[:32]
                    ),
                    run_id=admission.run_id,
                    sequence=1,
                    type=AgentEventType.DISPATCH_RESERVED,
                    occurred_at=occurred_at,
                    summary="Conversation Turn reserved",
                )
            )
        )
        reserved = self._conversation_turn_by_id(str(head["id"]))
        if reserved is None:
            raise RunRepositoryError("run_repository.corrupt")
        return self._conversation_reservation(reserved)

    def continue_blocked_conversation_turn(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        expected_revision: int,
        expected_message_revision: int,
        admission: ConversationRunAdmission,
        now: str | None = None,
    ) -> ConversationDispatchReservation:
        """Explicitly revalidate and reserve the exact blocked queue head."""

        if (
            _CONVERSATION_ID.fullmatch(str(conversation_id)) is None
            or _TURN_ID.fullmatch(str(turn_id)) is None
            or type(expected_revision) is not int
            or expected_revision < 1
            or type(expected_message_revision) is not int
            or expected_message_revision < 1
        ):
            raise RunRepositoryValidationError("conversation.turn_invalid")
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            self.authority_receipt(required=True)
            head = self._oldest_queue_active_turn(conversation_id)
            if (
                head is None
                or head["id"] != turn_id
                or head["state"] != "blocked"
                or int(head["revision"]) != expected_revision
                or int(head["message_revision"]) != expected_message_revision
            ):
                raise RunRepositoryConflict("conversation.turn_changed")
            reservation = self._reserve_oldest_queued_conversation_turn(
                conversation_id=conversation_id,
                admission=admission,
                allow_blocked=True,
                expected_turn_id=turn_id,
                expected_turn_revision=expected_revision,
                expected_message_revision=expected_message_revision,
                occurred_at=occurred_at,
            )
            if reservation is not None:
                return reservation
            row = self._conversation_turn_by_id(turn_id)
            if row is None:
                raise RunRepositoryConflict("conversation.turn_not_found")
            return self._conversation_reservation(row)

    def reserve_conversation_run_attempt(
        self,
        *,
        action: str,
        idempotency_key: str,
        conversation_id: str,
        source_run_id: str,
        admission: ConversationRunAdmission,
        now: str | None = None,
    ) -> ConversationDispatchReservation:
        """Reserve one explicit Retry or Resume without replacing prior evidence."""

        key_digest = self._idempotency_key_digest(idempotency_key)
        if (
            action not in {"retry", "resume"}
            or _CONVERSATION_ID.fullmatch(str(conversation_id)) is None
            or _RUN_ID.fullmatch(str(source_run_id)) is None
        ):
            raise RunRepositoryValidationError("conversation.attempt_invalid")
        request_digest = hashlib.sha256(
            _canonical_json(
                {
                    "action": action,
                    "conversation_id": conversation_id,
                    "source_run_id": source_run_id,
                },
                maximum=1_024,
                code="conversation.attempt_invalid",
            ).encode("ascii")
        ).hexdigest()
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            self.authority_receipt(required=True)
            existing = self.connection.execute(
                "SELECT * FROM mentat_conversation_run_attempts "
                "WHERE key_digest = ?",
                (key_digest,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["request_digest"] != request_digest
                    or existing["action"] != action
                    or existing["conversation_id"] != conversation_id
                    or existing["source_run_id"] != source_run_id
                ):
                    raise RunRepositoryConflict(
                        "conversation.attempt_idempotency_conflict"
                    )
                turn = self._conversation_turn_by_id(str(existing["turn_id"]))
                if turn is None:
                    raise RunRepositoryError("run_repository.corrupt")
                return ConversationDispatchReservation(
                    conversation_id=conversation_id,
                    message_id=str(turn["user_message_id"]),
                    turn_id=str(existing["turn_id"]),
                    run_id=str(existing["run_id"]),
                    request_digest=request_digest,
                    runtime_binding_digest=str(
                        existing["runtime_binding_digest"]
                    ),
                    state=str(existing["dispatch_state"]),
                    attempt_count=int(turn["attempt_count"]),
                    duplicate=True,
                )

            self._apply_retention(protected_run_ids=(source_run_id,))
            source = self.connection.execute(
                """
                SELECT r.*, t.user_message_id, t.state AS turn_state,
                       t.revision AS turn_revision, t.attempt_count,
                       t.latest_run_id, m.content_json AS message_content_json,
                       m.content_bytes AS message_content_bytes,
                       m.revision AS message_revision,
                       c.state AS conversation_state,
                       c.agent_id AS conversation_agent_id
                FROM mentat_runs AS r
                JOIN mentat_conversation_turns AS t
                  ON t.id = r.turn_id
                 AND t.conversation_id = r.conversation_id
                JOIN mentat_conversation_messages AS m
                  ON m.id = t.user_message_id
                 AND m.conversation_id = t.conversation_id
                JOIN mentat_conversations AS c ON c.id = t.conversation_id
                WHERE r.id = ? AND r.conversation_id = ?
                """,
                (source_run_id, conversation_id),
            ).fetchone()
            if source is None:
                raise RunRepositoryConflict("run.not_found")
            if (
                source["source"] != "console"
                or source["conversation_state"] != "active"
                or source["conversation_agent_id"] != admission.agent_id
                or source["agent_id"] != admission.agent_id
                or source["turn_state"] != "consumed"
                or source["latest_run_id"] != source_run_id
                or source["status"] not in _TERMINAL_STATUSES
                or not bool(source["terminal_finalized"])
                or int(source["attempt_count"]) >= 8
                or action == "resume"
                and (
                    source["runtime_type"] != admission.runtime_type
                    or source["runtime_binding_digest"]
                    != admission.runtime_binding_digest
                    or source["runtime_run_ref"] is None
                )
            ):
                raise RunRepositoryConflict("conversation.attempt_stale")
            receipt_count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM mentat_conversation_run_attempts "
                    "WHERE turn_id = ?",
                    (source["turn_id"],),
                ).fetchone()[0]
            )
            if receipt_count >= 7:
                raise RunRepositoryConflict(
                    "conversation.attempt_capacity"
                )
            active = self.connection.execute(
                "SELECT 1 FROM mentat_runs WHERE conversation_id = ? "
                "AND status IN (" + ",".join("?" for _ in _ACTIVE_STATUSES) + ") LIMIT 1",
                (conversation_id, *tuple(sorted(_ACTIVE_STATUSES))),
            ).fetchone()
            if active is not None:
                raise RunRepositoryConflict("conversation.active_run")
            agent = self.connection.execute(
                """
                SELECT a.revision, a.runtime_config_id, a.capabilities_json,
                       1 AS runtime_config_revision,
                       c.runtime_type, c.runtime_agent_ref
                FROM mentat_agents AS a
                JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id
                WHERE a.id = ?
                """,
                (admission.agent_id,),
            ).fetchone()
            if agent is None:
                raise RunRepositoryConflict("conversation.agent_missing")
            live_capabilities = _decode_json(
                agent["capabilities_json"],
                expected=list,
                code="run_repository.corrupt",
            )
            if (
                int(agent["revision"]) != admission.agent_revision
                or str(agent["runtime_config_id"])
                != admission.runtime_config_id
                or int(agent["runtime_config_revision"])
                != admission.runtime_config_revision
                or str(agent["runtime_type"]) != admission.runtime_type
                or live_capabilities != list(admission.capabilities)
                or runtime_binding_digest(
                    agent_id=admission.agent_id,
                    runtime_type=admission.runtime_type,
                    runtime_config_id=admission.runtime_config_id,
                    runtime_agent_ref=str(agent["runtime_agent_ref"]),
                    capabilities=live_capabilities,
                )
                != admission.runtime_binding_digest
            ):
                raise RunRepositoryConflict("conversation.binding_changed")
            if self._active_capacity_count(
                runtime_type=admission.runtime_type,
                binding_digest=admission.runtime_binding_digest,
                capacity_scope_digest=admission.capacity_scope_digest,
            ) >= admission.capacity_limit:
                raise RunRepositoryConflict("conversation.capacity_unavailable")
            try:
                content = _decode_json(
                    source["message_content_json"],
                    expected=dict,
                    code="run_repository.corrupt",
                )
                text = str(content["parts"][0]["text"])
                _, canonical_json, content_bytes = canonical_message_content(
                    text,
                    role="user",
                )
            except (KeyError, IndexError, TypeError, ConversationRepositoryError) as exc:
                raise RunRepositoryError("run_repository.corrupt") from exc
            if (
                canonical_json != source["message_content_json"]
                or content_bytes != int(source["message_content_bytes"])
            ):
                raise RunRepositoryError("run_repository.corrupt")
            self._ensure_run_capacity((admission.run_id, source_run_id))
            capabilities_json, execution_json, execution_digest, details_json = (
                self._conversation_admission_documents(admission, text=text)
            )
            self.connection.execute(
                """
                INSERT INTO mentat_runs (
                    id, source, task_id, task_revision, task_snapshot_json,
                    agent_id, runtime_type, runtime_config_id,
                    runtime_binding_digest, capabilities_json, status,
                    dispatch_state, details_json, created_at, updated_at,
                    conversation_id, turn_id, retry_of_run_id,
                    resume_of_run_id, agent_revision,
                    runtime_config_revision, execution_config_json,
                    execution_config_digest, capacity_scope_digest,
                    admitted_capacity_limit
                ) VALUES (
                    ?, 'console', NULL, NULL, NULL, ?, ?, ?, ?, ?,
                    'reserved', 'reserved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    admission.run_id,
                    admission.agent_id,
                    admission.runtime_type,
                    admission.runtime_config_id,
                    admission.runtime_binding_digest,
                    capabilities_json,
                    details_json,
                    occurred_at,
                    occurred_at,
                    conversation_id,
                    source["turn_id"],
                    source_run_id if action == "retry" else None,
                    source_run_id if action == "resume" else None,
                    admission.agent_revision,
                    admission.runtime_config_revision,
                    execution_json,
                    execution_digest,
                    admission.capacity_scope_digest,
                    admission.capacity_limit,
                ),
            )
            try:
                copy_run_input_context(
                    self.connection,
                    source_run_id,
                    admission.run_id,
                    occurred_at=occurred_at,
                )
            except ConversationAttachmentError as exc:
                raise RunRepositoryConflict(exc.code) from exc
            self.connection.execute(
                """
                INSERT INTO mentat_conversation_run_attempts (
                    key_digest, request_digest, action, conversation_id,
                    turn_id, source_run_id, run_id,
                    runtime_binding_digest, dispatch_state, status, partial,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', 'reserved', 0, ?, ?)
                """,
                (
                    key_digest,
                    request_digest,
                    action,
                    conversation_id,
                    source["turn_id"],
                    source_run_id,
                    admission.run_id,
                    admission.runtime_binding_digest,
                    occurred_at,
                    occurred_at,
                ),
            )
            message_updated = self.connection.execute(
                "UPDATE mentat_conversation_messages SET run_id = ?, "
                "revision = revision + 1, updated_at = ? WHERE id = ? "
                "AND conversation_id = ? AND run_id = ? AND revision = ?",
                (
                    admission.run_id,
                    occurred_at,
                    source["user_message_id"],
                    conversation_id,
                    source_run_id,
                    source["message_revision"],
                ),
            ).rowcount
            turn_updated = self.connection.execute(
                "UPDATE mentat_conversation_turns SET state = 'dispatching', "
                "blocked_reason = NULL, latest_run_id = ?, "
                "revision = revision + 1, updated_at = ? WHERE id = ? "
                "AND conversation_id = ? AND state = 'consumed' "
                "AND latest_run_id = ? AND revision = ?",
                (
                    admission.run_id,
                    occurred_at,
                    source["turn_id"],
                    conversation_id,
                    source_run_id,
                    source["turn_revision"],
                ),
            ).rowcount
            if message_updated != 1 or turn_updated != 1:
                raise RunRepositoryConflict("conversation.state_changed")
            self.connection.execute(
                "UPDATE mentat_conversations SET revision = revision + 1, "
                "updated_at = ? WHERE id = ?",
                (occurred_at, conversation_id),
            )
            self._append_event_record(
                _event_from_domain(
                    AgentEvent(
                        id="event_" + hashlib.sha256(
                            f"{admission.run_id}:reserved".encode("utf-8")
                        ).hexdigest()[:32],
                        run_id=admission.run_id,
                        sequence=1,
                        type=AgentEventType.DISPATCH_RESERVED,
                        occurred_at=occurred_at,
                        summary=(
                            "Conversation Turn retry reserved"
                            if action == "retry"
                            else "Conversation Turn resume reserved"
                        ),
                    )
                )
            )
            reserved = self._conversation_turn_by_id(str(source["turn_id"]))
            if reserved is None:
                raise RunRepositoryError("run_repository.corrupt")
            return self._conversation_reservation(reserved)

    def get_conversation_run_attempt_result(
        self,
        *,
        idempotency_key: str,
    ) -> ConversationRunAttemptResult:
        key_digest = self._idempotency_key_digest(idempotency_key)
        row = self.connection.execute(
            "SELECT * FROM mentat_conversation_run_attempts WHERE key_digest = ?",
            (key_digest,),
        ).fetchone()
        if row is None:
            raise RunRepositoryConflict("conversation.attempt_not_found")
        return _conversation_run_attempt_result(row)

    def lookup_conversation_run_attempt(
        self,
        *,
        action: str,
        idempotency_key: str,
        conversation_id: str,
        source_run_id: str,
    ) -> ConversationRunAttemptResult | None:
        key_digest = self._idempotency_key_digest(idempotency_key)
        row = self.connection.execute(
            "SELECT * FROM mentat_conversation_run_attempts WHERE key_digest = ?",
            (key_digest,),
        ).fetchone()
        if row is None:
            return None
        request_digest = hashlib.sha256(
            _canonical_json(
                {
                    "action": action,
                    "conversation_id": conversation_id,
                    "source_run_id": source_run_id,
                },
                maximum=1_024,
                code="conversation.attempt_invalid",
            ).encode("ascii")
        ).hexdigest()
        if (
            row["request_digest"] != request_digest
            or row["action"] != action
            or row["conversation_id"] != conversation_id
            or row["source_run_id"] != source_run_id
        ):
            raise RunRepositoryConflict(
                "conversation.attempt_idempotency_conflict"
            )
        return _conversation_run_attempt_result(row)

    def reserve_conversation_turn(
        self,
        *,
        idempotency_key: str,
        conversation_id: str,
        message_id: str,
        turn_id: str,
        run_id: str,
        text: str,
        agent_id: str,
        agent_name: str,
        agent_revision: int,
        runtime_type: str,
        runtime_config_id: str,
        runtime_config_revision: int,
        binding_digest: str,
        capabilities: Iterable[str],
        capacity_scope_digest: str | None = None,
        capacity_limit: int | None = None,
        now: str | None = None,
    ) -> ConversationDispatchReservation:
        """Atomically reserve one idle Conversation Turn before adapter I/O."""

        key_digest = self._idempotency_key_digest(idempotency_key)
        if (
            not isinstance(conversation_id, str)
            or _CONVERSATION_ID.fullmatch(conversation_id) is None
            or not isinstance(message_id, str)
            or not re.fullmatch(r"msg_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z", message_id)
            or not isinstance(turn_id, str)
            or _TURN_ID.fullmatch(turn_id) is None
        ):
            raise RunRepositoryValidationError("conversation.identifier_invalid")
        run_identifier = _identifier(run_id)
        if not isinstance(run_identifier, str) or _RUN_ID.fullmatch(run_identifier) is None:
            raise RunRepositoryValidationError("run.identifier_invalid")
        agent_identifier = _identifier(agent_id)
        config_identifier = _identifier(runtime_config_id)
        if (
            not isinstance(agent_name, str)
            or not agent_name
            or agent_name.strip() != agent_name
            or len(agent_name) > 160
            or type(agent_revision) is not int
            or agent_revision < 1
            or type(runtime_config_revision) is not int
            or runtime_config_revision < 1
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", str(runtime_type))
            or not _SHA256.fullmatch(str(binding_digest))
        ):
            raise RunRepositoryValidationError("conversation.binding_invalid")
        try:
            _, content_json, content_bytes = canonical_message_content(
                text,
                role="user",
            )
        except ConversationRepositoryError as exc:
            raise RunRepositoryValidationError(
                "conversation.request_invalid"
            ) from exc
        request_digest = conversation_turn_request_digest(
            conversation_id=conversation_id,
            agent_id=agent_identifier,
            text=text,
        )
        capability_values = sorted(set(str(value) for value in capabilities))
        if any(
            re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value) is None
            for value in capability_values
        ):
            raise RunRepositoryValidationError("conversation.binding_invalid")
        capabilities_json = _canonical_json(
            capability_values,
            maximum=8_192,
            code="conversation.binding_invalid",
        )
        if capacity_scope_digest is None and capacity_limit is None:
            capacity_scope_digest, capacity_limit = default_runtime_capacity_evidence(
                runtime_type=runtime_type,
                binding_digest=binding_digest,
            )
        elif (
            not isinstance(capacity_scope_digest, str)
            or _SHA256.fullmatch(capacity_scope_digest) is None
            or type(capacity_limit) is not int
            or not 1 <= capacity_limit <= 32
        ):
            raise RunRepositoryValidationError("conversation.capacity_invalid")
        execution_config_json = _canonical_json(
            {
                "admitted_capacity_limit": capacity_limit,
                "agent_id": agent_identifier,
                "agent_revision": agent_revision,
                "capabilities": capability_values,
                "capacity_scope_digest": capacity_scope_digest,
                "contract": "mentat-conversation-execution-v1",
                "runtime_binding_digest": binding_digest,
                "runtime_config_id": config_identifier,
                "runtime_config_revision": runtime_config_revision,
                "runtime_selection": {
                    "evidence": "runtime_execution_json_after_start",
                    "mutation_guard": "runtime_binding",
                },
                "runtime_type": runtime_type,
            },
            maximum=16_384,
            code="conversation.execution_config_invalid",
        )
        execution_config_digest = hashlib.sha256(
            execution_config_json.encode("ascii")
        ).hexdigest()
        prompt_excerpt, prompt_truncated = bounded_excerpt(text, 500)
        details_json = _canonical_json(
            {
                "agent_id": agent_identifier,
                "agent_name": agent_name,
                "artifacts": [],
                "attachments": [],
                "connection_binding_id": "local-default",
                "duration_seconds": None,
                "error_excerpt": "",
                "error_truncated": False,
                "model": "",
                "new_session_state": None,
                "prompt_excerpt": prompt_excerpt,
                "prompt_truncated": prompt_truncated,
                "response_excerpt": "",
                "response_truncated": False,
                "session_id": None,
                "starts_new_session": False,
                "transport_mode": "local",
                "usage": None,
            },
            maximum=RUN_DETAILS_LIMIT,
            code="run.details_invalid",
        )
        occurred_at = _timestamp(now or _now_iso())
        title = " ".join(text.split())[:80]
        if not title:
            raise RunRepositoryValidationError("conversation.message_invalid")

        with self.mutation():
            self.authority_receipt(required=True)
            existing = self._conversation_turn_by_key_digest(key_digest)
            if existing is not None:
                if (
                    str(existing["conversation_id"]) != conversation_id
                    or str(existing["request_digest"]) != request_digest
                ):
                    raise RunRepositoryConflict("conversation.idempotency_conflict")
                return self._conversation_reservation(existing, duplicate=True)

            self._apply_retention()
            conversation = self.connection.execute(
                "SELECT * FROM mentat_conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            if conversation is None:
                raise RunRepositoryConflict("conversation.not_found")
            if str(conversation["state"]) != "active":
                raise RunRepositoryConflict("conversation.not_active")
            if str(conversation["agent_id"]) != agent_identifier:
                raise RunRepositoryConflict("conversation.agent_changed")
            agent = self.connection.execute(
                """
                SELECT a.revision, a.runtime_config_id, a.capabilities_json,
                       c.runtime_type, c.runtime_agent_ref
                FROM mentat_agents AS a
                JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id
                WHERE a.id = ?
                """,
                (agent_identifier,),
            ).fetchone()
            if agent is None:
                raise RunRepositoryConflict("conversation.agent_missing")
            live_capabilities = _decode_json(
                agent["capabilities_json"],
                expected=list,
                code="run_repository.corrupt",
            )
            if (
                int(agent["revision"]) != agent_revision
                or str(agent["runtime_config_id"]) != config_identifier
                or str(agent["runtime_type"]) != runtime_type
                or live_capabilities != capability_values
                or runtime_binding_digest(
                    agent_id=agent_identifier,
                    runtime_type=runtime_type,
                    runtime_config_id=config_identifier,
                    runtime_agent_ref=str(agent["runtime_agent_ref"]),
                    capabilities=live_capabilities,
                )
                != binding_digest
            ):
                raise RunRepositoryConflict("conversation.binding_changed")
            active = self.connection.execute(
                "SELECT status, partial FROM mentat_runs AS r "
                "WHERE conversation_id = ? AND (status IN ("
                + ",".join("?" for _ in _ACTIVE_STATUSES)
                + ") OR (runtime_type = 'hermes' AND status IN ("
                + ",".join("?" for _ in _TERMINAL_STATUSES)
                + ") AND terminal_finalized = 0)) "
                "LIMIT 1",
                (
                    conversation_id,
                    *tuple(sorted(_ACTIVE_STATUSES)),
                    *tuple(sorted(_TERMINAL_STATUSES)),
                ),
            ).fetchone()
            queue_head = self._oldest_queue_active_turn(conversation_id)
            staged_context = staged_context_evidence(
                self.connection,
                conversation_id,
            )
            if staged_context is not None and (
                runtime_type != "hermes"
                or "run.attachments" not in capability_values
            ):
                raise RunRepositoryConflict(
                    "conversation_context.capability_missing"
                )
            if active is None and queue_head is not None and queue_head["state"] == "dispatching":
                raise RunRepositoryError("run_repository.corrupt")
            create_run = active is None and queue_head is None
            turn_state = "pending"
            blocked_reason = None
            if active is not None:
                if str(active["status"]) == "unknown":
                    turn_state = "blocked"
                    blocked_reason = "unknown"
                elif bool(active["partial"]):
                    turn_state = "blocked"
                    blocked_reason = "partial"
            elif queue_head is None:
                capacity_used = self._active_capacity_count(
                    runtime_type=runtime_type,
                    binding_digest=binding_digest,
                    capacity_scope_digest=capacity_scope_digest,
                )
                if capacity_used >= capacity_limit:
                    create_run = False
                    turn_state = "blocked"
                    blocked_reason = "capacity"
                else:
                    self._ensure_run_capacity((run_identifier,))
                    turn_state = "dispatching"
            if staged_context is not None and not create_run:
                raise RunRepositoryConflict(
                    "conversation_context.requires_idle"
                )
            message_count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM mentat_conversation_messages"
                ).fetchone()[0]
            )
            turn_count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM mentat_conversation_turns"
                ).fetchone()[0]
            )
            total_message_bytes = int(
                self.connection.execute(
                    "SELECT COALESCE(SUM(content_bytes), 0) "
                    "FROM mentat_conversation_messages"
                ).fetchone()[0]
            )
            if (
                message_count >= MAX_CONVERSATION_MESSAGES
                or turn_count >= MAX_CONVERSATION_TURNS
                or total_message_bytes + content_bytes > MAX_TOTAL_MESSAGE_BYTES
            ):
                raise RunRepositoryValidationError("conversation.capacity_exceeded")
            active_turn_count = int(
                self.connection.execute(
                    "SELECT COUNT(*) FROM mentat_conversation_turns "
                    "WHERE conversation_id = ? "
                    "AND state IN ('pending', 'blocked', 'dispatching')",
                    (conversation_id,),
                ).fetchone()[0]
            )
            if active_turn_count >= 8:
                raise RunRepositoryConflict("conversation.turn_capacity")

            message_sequence = int(conversation["next_message_sequence"])
            turn_ordinal = int(conversation["next_turn_ordinal"])
            try:
                self.connection.execute(
                    """
                    INSERT INTO mentat_conversation_messages (
                        id, conversation_id, sequence, role, state, content_json,
                        content_bytes, run_id, revision, source_key, created_at,
                        updated_at
                    ) VALUES (?, ?, ?, 'user', 'accepted', ?, ?, NULL, 1, ?, ?, ?)
                    """,
                    (
                        message_id,
                        conversation_id,
                        message_sequence,
                        content_json,
                        content_bytes,
                        f"console:{turn_id}",
                        occurred_at,
                        occurred_at,
                    ),
                )
                self.connection.execute(
                    """
                    INSERT INTO mentat_conversation_turns (
                        id, conversation_id, user_message_id, queue_ordinal,
                        state, blocked_reason, latest_run_id, revision,
                        attempt_count, idempotency_key_digest, request_digest,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, 1, 0, ?, ?, ?, ?)
                    """,
                    (
                        turn_id,
                        conversation_id,
                        message_id,
                        turn_ordinal,
                        turn_state,
                        blocked_reason,
                        key_digest,
                        request_digest,
                        occurred_at,
                        occurred_at,
                    ),
                )
                if create_run:
                    self.connection.execute(
                        """
                        INSERT INTO mentat_runs (
                        id, source, task_id, task_revision, task_snapshot_json,
                        agent_id, runtime_type, runtime_config_id,
                        runtime_binding_digest, capabilities_json, status,
                        dispatch_state, details_json, created_at, updated_at,
                        conversation_id, turn_id, agent_revision,
                        runtime_config_revision, execution_config_json,
                        execution_config_digest, capacity_scope_digest,
                        admitted_capacity_limit
                        ) VALUES (
                        ?, 'console', NULL, NULL, NULL, ?, ?, ?, ?, ?,
                        'reserved', 'reserved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                        run_identifier,
                        agent_identifier,
                        runtime_type,
                        config_identifier,
                        binding_digest,
                        capabilities_json,
                        details_json,
                        occurred_at,
                        occurred_at,
                        conversation_id,
                        turn_id,
                        agent_revision,
                        runtime_config_revision,
                        execution_config_json,
                        execution_config_digest,
                        capacity_scope_digest,
                        capacity_limit,
                        ),
                    )
                    self.connection.execute(
                        "UPDATE mentat_conversation_messages SET run_id = ? WHERE id = ?",
                        (run_identifier, message_id),
                    )
                    self.connection.execute(
                        "UPDATE mentat_conversation_turns SET latest_run_id = ? WHERE id = ?",
                        (run_identifier, turn_id),
                    )
                    if staged_context is not None:
                        try:
                            bind_staged_context_to_run(
                                self.connection,
                                conversation_id,
                                run_identifier,
                                occurred_at=occurred_at,
                            )
                        except ConversationAttachmentError as exc:
                            raise RunRepositoryConflict(exc.code) from exc
                self.connection.execute(
                    """
                    UPDATE mentat_conversations
                    SET title = CASE WHEN title_source = 'default' THEN ? ELSE title END,
                        title_source = CASE WHEN title_source = 'default'
                            THEN 'first_prompt' ELSE title_source END,
                        revision = revision + 1,
                        next_message_sequence = ?, next_turn_ordinal = ?,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        message_sequence + 1,
                        turn_ordinal + 1,
                        occurred_at,
                        conversation_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if self._conversation_turn_by_key_digest(key_digest) is not None:
                    raise RunRepositoryConflict(
                        "conversation.idempotency_conflict"
                    ) from exc
                raise RunRepositoryConflict("conversation.write_conflict") from exc
            if create_run:
                self._append_event_record(
                    _event_from_domain(
                        AgentEvent(
                        id=(
                            "event_"
                            + hashlib.sha256(
                                f"{turn_id}:reserved".encode("utf-8")
                            ).hexdigest()[:32]
                        ),
                        run_id=run_identifier,
                        sequence=1,
                        type=AgentEventType.DISPATCH_RESERVED,
                        occurred_at=occurred_at,
                        summary="Conversation Turn reserved",
                        )
                    )
                )
            row = self._conversation_turn_by_key_digest(key_digest)
            if row is None:
                raise RunRepositoryError("run_repository.corrupt")
            return self._conversation_reservation(row)

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
        capacity_scope_digest: str | None = None,
        capacity_limit: int | None = None,
        planning_execution: bool = False,
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
        if type(planning_execution) is not bool:
            raise RunRepositoryValidationError("dispatch.planning_invalid")
        if not _SHA256.fullmatch(binding_digest):
            raise RunRepositoryValidationError("dispatch.binding_invalid")
        if capacity_scope_digest is None and capacity_limit is None:
            capacity_scope_digest, capacity_limit = default_runtime_capacity_evidence(
                runtime_type=runtime_type,
                binding_digest=binding_digest,
            )
        elif (
            not isinstance(capacity_scope_digest, str)
            or _SHA256.fullmatch(capacity_scope_digest) is None
            or type(capacity_limit) is not int
            or not 1 <= capacity_limit <= 32
        ):
            raise RunRepositoryValidationError("dispatch.capacity_invalid")
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
            if planning_execution:
                attempt_count = int(
                    self.connection.execute(
                        "SELECT COUNT(*) FROM mentat_task_execution_attempts "
                        "WHERE task_id = ?",
                        (task_id,),
                    ).fetchone()[0]
                )
                if attempt_count >= 8:
                    raise RunRepositoryConflict("dispatch.task_attempt_capacity")
            active = self.connection.execute(
                "SELECT id FROM mentat_runs WHERE task_id = ? AND status IN ("
                + ",".join("?" for _ in _ACTIVE_STATUSES)
                + ") LIMIT 1",
                (task_id, *tuple(sorted(_ACTIVE_STATUSES))),
            ).fetchone()
            if active is not None:
                raise RunRepositoryConflict("dispatch.task_active")
            if self._active_capacity_count(
                runtime_type=runtime_type,
                binding_digest=binding_digest,
                capacity_scope_digest=capacity_scope_digest,
            ) >= capacity_limit:
                raise RunRepositoryConflict("dispatch.capacity_unavailable")
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
                        dispatch_state, details_json, created_at, updated_at,
                        capacity_scope_digest, admitted_capacity_limit
                    ) VALUES (?, 'task_dispatch', ?, ?, ?, ?, ?, ?, ?, ?,
                              'reserved', 'reserved', ?, ?, ?, ?, ?)
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
                        capacity_scope_digest,
                        capacity_limit,
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
            if planning_execution:
                # The running stage and durable reservation share one SQLite
                # transaction. The adapter is not invoked until this exact
                # transition is committed and then revalidated by claim.
                next_task = dict(task)
                next_task.update(
                    {
                        "workflow_stage": "in_progress",
                        "planning_state": "in_progress",
                        "status": "in progress",
                        "review_required": False,
                        "needs_attention": False,
                        "completed_at": None,
                        "updated_at": occurred_at,
                    }
                )
                try:
                    transitioned = TaskRepository(self.connection).replace(
                        next_task,
                        expected_revision=task_revision,
                    )
                except TaskRepositoryError as exc:
                    raise RunRepositoryConflict("dispatch.task_changed") from exc
                self.connection.execute(
                    "INSERT INTO mentat_task_execution_attempts ("
                    "run_id, task_id, task_revision, agent_id, state, "
                    "review_task_revision, completion_reason, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, 'dispatched', ?, NULL, ?, ?)",
                    (
                        run_identifier,
                        task_id,
                        task_revision,
                        agent_identifier,
                        transitioned.revision,
                        occurred_at,
                        occurred_at,
                    ),
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

    def _conversation_turn_by_id(self, turn_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT t.*, r.dispatch_state AS run_dispatch_state,
                   r.runtime_binding_digest AS run_binding_digest,
                   r.status AS run_status, r.agent_id AS run_agent_id,
                   r.runtime_type AS run_runtime_type,
                   r.partial AS run_partial,
                   r.terminal_finalized AS run_terminal_finalized,
                   s.run_id AS result_run_id,
                   s.dispatch_state AS result_dispatch_state,
                   s.runtime_binding_digest AS result_binding_digest
            FROM mentat_conversation_turns AS t
            LEFT JOIN mentat_runs AS r ON r.id = t.latest_run_id
            LEFT JOIN mentat_conversation_submission_results AS s
                   ON s.turn_id = t.id
            WHERE t.id = ?
            """,
            (turn_id,),
        ).fetchone()

    def get_conversation_submission_result(
        self,
        turn_id: str,
    ) -> ConversationSubmissionResult:
        if not isinstance(turn_id, str) or _TURN_ID.fullmatch(turn_id) is None:
            raise RunRepositoryValidationError("conversation.identifier_invalid")
        row = self.connection.execute(
            "SELECT run_id, status, partial, updated_at "
            "FROM mentat_conversation_submission_results WHERE turn_id = ?",
            (turn_id,),
        ).fetchone()
        if row is None:
            raise RunRepositoryConflict("run.not_found")
        try:
            run_id = str(row["run_id"])
            status = str(row["status"])
            partial = row["partial"]
            updated_at = _timestamp(row["updated_at"])
            if (
                _RUN_ID.fullmatch(run_id) is None
                or status not in _ALL_STATUSES
                or type(partial) is not int
                or partial not in {0, 1}
            ):
                raise RunRepositoryError("run_repository.corrupt")
        except (TypeError, ValueError, RunRepositoryError) as exc:
            raise RunRepositoryError("run_repository.corrupt") from exc
        return ConversationSubmissionResult(
            id=run_id,
            status=status,
            partial=bool(partial),
            updated_at=updated_at,
        )

    def claim_conversation_turn_attempt(
        self,
        *,
        turn_id: str,
        expected_binding_digest: str,
        now: str | None = None,
    ) -> ConversationDispatchReservation:
        occurred_at = _timestamp(now or _now_iso())
        if not isinstance(turn_id, str) or _TURN_ID.fullmatch(turn_id) is None:
            raise RunRepositoryValidationError("conversation.identifier_invalid")
        if not _SHA256.fullmatch(str(expected_binding_digest)):
            raise RunRepositoryValidationError("conversation.binding_invalid")
        with self.mutation():
            row = self._conversation_turn_by_id(turn_id)
            if row is None or row["latest_run_id"] is None:
                raise RunRepositoryConflict("conversation.turn_not_found")
            if str(row["run_binding_digest"] or "") != expected_binding_digest:
                raise RunRepositoryConflict("conversation.binding_changed")
            if (
                str(row["state"]) != "dispatching"
                or str(row["run_status"]) != "reserved"
                or str(row["run_dispatch_state"]) != "reserved"
            ):
                raise RunRepositoryConflict("conversation.attempt_already_claimed")
            prior_attempt_count = int(row["attempt_count"])
            if prior_attempt_count < 0 or prior_attempt_count >= 8:
                raise RunRepositoryConflict("conversation.attempt_already_claimed")
            turn_updated = self.connection.execute(
                "UPDATE mentat_conversation_turns SET attempt_count = attempt_count + 1, "
                "revision = revision + 1, updated_at = ? "
                "WHERE id = ? AND state = 'dispatching' AND attempt_count = ?",
                (occurred_at, turn_id, prior_attempt_count),
            ).rowcount
            run_updated = self.connection.execute(
                "UPDATE mentat_runs SET status = 'submitting', "
                "dispatch_state = 'submitting', resume_of_run_id = CASE "
                "WHEN EXISTS (SELECT 1 FROM mentat_conversation_run_attempts "
                "WHERE run_id = ? AND action = 'resume') "
                "THEN resume_of_run_id ELSE NULL END, "
                "state_revision = state_revision + 1, "
                "updated_at = ? WHERE id = ? AND status = 'reserved' "
                "AND dispatch_state = 'reserved'",
                (row["latest_run_id"], occurred_at, row["latest_run_id"]),
            ).rowcount
            if turn_updated != 1 or run_updated != 1:
                raise RunRepositoryConflict("conversation.state_changed")
            claimed = self._conversation_turn_by_id(turn_id)
            if claimed is None:
                raise RunRepositoryError("run_repository.corrupt")
            return self._conversation_reservation(claimed)

    def reject_reserved_conversation_turn(
        self,
        *,
        turn_id: str,
        failure_code: str,
        now: str | None = None,
    ) -> RunRecord:
        if (
            not isinstance(turn_id, str)
            or _TURN_ID.fullmatch(turn_id) is None
            or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", failure_code)
        ):
            raise RunRepositoryValidationError("conversation.rejection_invalid")
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            row = self._conversation_turn_by_id(turn_id)
            if (
                row is None
                or row["latest_run_id"] is None
                or row["state"] != "dispatching"
                or row["run_status"] != "reserved"
                or row["run_dispatch_state"] != "reserved"
            ):
                raise RunRepositoryConflict("conversation.state_changed")
            turn_updated = self.connection.execute(
                "UPDATE mentat_conversation_turns SET state = 'consumed', "
                "revision = revision + 1, updated_at = ? "
                "WHERE id = ? AND state = 'dispatching' AND attempt_count = ?",
                (occurred_at, turn_id, row["attempt_count"]),
            ).rowcount
            run_updated = self.connection.execute(
                "UPDATE mentat_runs SET status = 'failed', dispatch_state = 'rejected', "
                "partial = 0, terminal_finalized = 1, resume_of_run_id = NULL, "
                "state_revision = state_revision + 1, updated_at = ?, "
                "completed_at = ? WHERE id = ? AND status = 'reserved' "
                "AND dispatch_state = 'reserved'",
                (occurred_at, occurred_at, row["latest_run_id"]),
            ).rowcount
            if turn_updated != 1 or run_updated != 1:
                raise RunRepositoryConflict("conversation.state_changed")
            self._append_next_lifecycle_event(
                str(row["latest_run_id"]),
                event_type=AgentEventType.RUN_FAILED,
                occurred_at=occurred_at,
                summary="Conversation Turn rejected before runtime submission",
                source_key=f"conversation:{turn_id}:rejected:{failure_code}",
            )
            self._block_oldest_pending_turn(
                conversation_id=str(row["conversation_id"]),
                reason="failed",
                occurred_at=occurred_at,
            )
            self._apply_retention(
                protected_run_ids=(str(row["latest_run_id"]),)
            )
            return self.get_run(str(row["latest_run_id"]))

    def record_conversation_submission_outcome(
        self,
        *,
        turn_id: str,
        outcome: SubmissionOutcome,
        continuation: ConversationRunAdmission | None = None,
        require_continuation_for_completed: bool = False,
        now: str | None = None,
    ) -> RunRecord:
        if not isinstance(turn_id, str) or _TURN_ID.fullmatch(turn_id) is None:
            raise RunRepositoryValidationError("conversation.identifier_invalid")
        if not isinstance(outcome, SubmissionOutcome):
            raise RunRepositoryValidationError("conversation.outcome_invalid")
        if type(require_continuation_for_completed) is not bool:
            raise RunRepositoryValidationError("conversation.outcome_invalid")
        runtime_execution_json = None
        runtime_execution_digest = None
        if outcome.execution_identity is not None:
            runtime_execution_json, runtime_execution_digest = (
                _runtime_execution_document(outcome.execution_identity)
            )
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            row = self._conversation_turn_by_id(turn_id)
            if (
                row is None
                or row["latest_run_id"] is None
                or row["state"] != "dispatching"
                or int(row["attempt_count"]) < 1
                or row["run_status"] != "submitting"
                or row["run_dispatch_state"] != "submitting"
            ):
                raise RunRepositoryConflict("conversation.state_changed")
            run_id = str(row["latest_run_id"])
            if outcome.disposition == SubmissionDisposition.ACCEPTED:
                if (
                    outcome.run is None
                    or outcome.run.id != run_id
                    or outcome.run.task_id != turn_id
                    or outcome.run.agent_id != row["run_agent_id"]
                    or outcome.run.runtime_type != row["run_runtime_type"]
                ):
                    raise RunRepositoryConflict(
                        "conversation.runtime_identity_mismatch"
                    )
                next_status = outcome.run.status.value
                if next_status not in _ALL_STATUSES or next_status in {
                    "reserved",
                    "submitting",
                    "unknown",
                }:
                    next_status = "starting"
                dispatch_state = "accepted"
                # A worker can finish, or a steer can become ambiguous, before
                # the adapter's initial acceptance returns.  Acceptance
                # resolves only submission authority; independent partial
                # evidence must remain sticky.
                partial = int(row["run_partial"])
                event_type = AgentEventType.RUN_STARTED
                summary = "Runtime accepted Conversation Turn"
            elif outcome.disposition == SubmissionDisposition.REJECTED:
                next_status = "failed"
                dispatch_state = "rejected"
                partial = int(row["run_partial"])
                event_type = AgentEventType.RUN_FAILED
                summary = "Runtime rejected Conversation Turn"
            else:
                next_status = "unknown"
                dispatch_state = "unknown"
                partial = 1
                event_type = AgentEventType.SUBMISSION_UNKNOWN
                summary = "Conversation Turn submission outcome is unknown"
            terminal_at = occurred_at if next_status in _TERMINAL_STATUSES else None
            terminal_finalized = int(
                bool(row["run_terminal_finalized"])
                or (
                    next_status in _TERMINAL_STATUSES
                    and (
                        str(row["run_runtime_type"]) != "hermes"
                        or dispatch_state == "rejected"
                    )
                )
            )
            turn_updated = self.connection.execute(
                "UPDATE mentat_conversation_turns SET state = 'consumed', "
                "revision = revision + 1, updated_at = ? "
                "WHERE id = ? AND state = 'dispatching' AND attempt_count = ?",
                (occurred_at, turn_id, row["attempt_count"]),
            ).rowcount
            run_updated = self.connection.execute(
                "UPDATE mentat_runs SET status = ?, dispatch_state = ?, partial = ?, "
                "terminal_finalized = ?, "
                "runtime_run_ref = ?, runtime_execution_json = ?, "
                "runtime_execution_digest = ?, state_revision = state_revision + 1, "
                "updated_at = ?, started_at = CASE WHEN ? = 'accepted' "
                "THEN COALESCE(started_at, ?) ELSE started_at END, "
                "completed_at = ? WHERE id = ? AND status = 'submitting' "
                "AND dispatch_state = 'submitting'",
                (
                    next_status,
                    dispatch_state,
                    partial,
                    terminal_finalized,
                    outcome.runtime_run_ref,
                    runtime_execution_json,
                    runtime_execution_digest,
                    occurred_at,
                    dispatch_state,
                    occurred_at,
                    terminal_at,
                    run_id,
                ),
            ).rowcount
            if turn_updated != 1 or run_updated != 1:
                raise RunRepositoryConflict("conversation.state_changed")
            self._append_next_lifecycle_event(
                run_id,
                event_type=event_type,
                occurred_at=occurred_at,
                summary=summary,
                source_key=f"conversation:{turn_id}:{dispatch_state}",
            )
            if dispatch_state == "accepted":
                for source_event in outcome.initial_events:
                    current_run = self.connection.execute(
                        "SELECT * FROM mentat_runs WHERE id = ?",
                        (run_id,),
                    ).fetchone()
                    if current_run is None:
                        raise RunRepositoryConflict("run.not_found")
                    record = dict(_event_from_domain(source_event))
                    record["id"] = (
                        "event_"
                        + hashlib.sha256(
                            (run_id + ":" + source_event.id).encode("utf-8")
                        ).hexdigest()[:24]
                    )
                    record["sequence"] = int(current_run["last_event_sequence"]) + 1
                    record["source_key"] = f"submission:{source_event.id}"
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
                    self._project_conversation_assistant_message(
                        run=current_run,
                        event_record=record,
                        projection_at=occurred_at,
                    )
            terminal_event = {
                "completed": AgentEventType.RUN_COMPLETED,
                "failed": AgentEventType.RUN_FAILED,
                "stopped": AgentEventType.RUN_STOPPED,
                "interrupted": AgentEventType.RUN_INTERRUPTED,
            }.get(next_status)
            if terminal_event is not None and terminal_event != event_type:
                self._append_next_lifecycle_event(
                    run_id,
                    event_type=terminal_event,
                    occurred_at=occurred_at,
                    summary=f"Run {next_status}",
                    source_key=f"conversation:{turn_id}:terminal:{next_status}",
                )
            if dispatch_state == "rejected":
                self._block_oldest_pending_turn(
                    conversation_id=str(row["conversation_id"]),
                    reason="failed",
                    occurred_at=occurred_at,
                )
            elif dispatch_state == "unknown":
                self._block_oldest_pending_turn(
                    conversation_id=str(row["conversation_id"]),
                    reason="unknown",
                    occurred_at=occurred_at,
                )
            elif dispatch_state == "accepted" and bool(partial):
                self._block_oldest_pending_turn(
                    conversation_id=str(row["conversation_id"]),
                    reason="partial",
                    occurred_at=occurred_at,
                )
            elif (
                next_status == "completed"
                and terminal_finalized
                and continuation is not None
            ):
                try:
                    self._reserve_oldest_queued_conversation_turn(
                        conversation_id=str(row["conversation_id"]),
                        admission=continuation,
                        allow_blocked=False,
                        expected_turn_id=None,
                        expected_turn_revision=None,
                        expected_message_revision=None,
                        occurred_at=occurred_at,
                    )
                except RunRepositoryConflict as exc:
                    if exc.code not in {
                        "conversation.active_run",
                        "conversation.agent_changed",
                        "conversation.agent_missing",
                        "conversation.binding_changed",
                    }:
                        raise
                    # Preserve the verified completed outcome while pausing an
                    # unsafe continuation for an explicit, fresh revalidation.
                    self._block_oldest_pending_turn(
                        conversation_id=str(row["conversation_id"]),
                        reason="partial",
                        occurred_at=occurred_at,
                    )
            elif next_status == "completed" and require_continuation_for_completed:
                self._block_oldest_pending_turn(
                    conversation_id=str(row["conversation_id"]),
                    reason="partial",
                    occurred_at=occurred_at,
                )
            self._apply_retention()
            return self.get_run(run_id)

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
                "SELECT t.revision, t.assigned_agent_id, t.planning_state, "
                "t.source, t.nested_planning_json, r.task_id, r.task_revision, "
                "r.agent_id, a.review_task_revision FROM mentat_runs r "
                "LEFT JOIN mentat_tasks t ON t.id = r.task_id "
                "LEFT JOIN mentat_task_execution_attempts a ON a.run_id = r.id "
                "WHERE r.id = ?",
                (row["run_id"],),
            ).fetchone()
            expected_task_revision = (
                int(task_state["review_task_revision"])
                if task_state is not None
                and task_state["review_task_revision"] is not None
                else int(row["task_revision"])
            )
            planning_attempt_valid = True
            if task_state is not None and task_state["review_task_revision"] is not None:
                try:
                    nested_planning = json.loads(
                        str(task_state["nested_planning_json"] or "{}")
                    )
                    planning_attempt_valid = (
                        task_state["planning_state"] == "in_progress"
                        and task_state["source"] == "dashboard"
                        and isinstance(nested_planning, dict)
                        and "delegation" not in nested_planning
                    )
                except (TypeError, ValueError, json.JSONDecodeError):
                    planning_attempt_valid = False
            if (
                task_state is None
                or task_state["revision"] is None
                or int(task_state["revision"]) != expected_task_revision
                or int(task_state["task_revision"]) != int(row["task_revision"])
                or str(task_state["task_id"]) != str(row["task_id"])
                or str(task_state["assigned_agent_id"] or "")
                != str(task_state["agent_id"] or "")
                or not planning_attempt_valid
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
            terminal_finalized = int(
                bool(current["terminal_finalized"])
                or (
                    next_status in _TERMINAL_STATUSES
                    and (
                        str(current["runtime_type"]) != "hermes"
                        or reservation_state == "rejected"
                    )
                )
            )
            reservation_updated = self.connection.execute(
                "UPDATE mentat_dispatch_reservations SET state = ?, updated_at = ? "
                "WHERE dispatch_id = ? AND state = 'submitting' AND attempt_count = 1",
                (reservation_state, occurred_at, dispatch_id),
            ).rowcount
            run_updated = self.connection.execute(
                "UPDATE mentat_runs SET status = ?, dispatch_state = ?, partial = ?, "
                "terminal_finalized = ?, "
                "runtime_run_ref = ?, state_revision = state_revision + 1, "
                "updated_at = ?, started_at = CASE WHEN ? = 'accepted' "
                "THEN COALESCE(started_at, ?) ELSE started_at END, "
                "completed_at = COALESCE(completed_at, ?) WHERE id = ? "
                "AND dispatch_state = 'submitting' AND status = ? AND state_revision = ?",
                (
                    next_status,
                    dispatch_state,
                    partial,
                    terminal_finalized,
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
            self._promote_completed_task_execution(
                run_id=run_id,
                completed=next_status == "completed",
                terminal_finalized=bool(terminal_finalized),
                partial=bool(partial),
                occurred_at=occurred_at,
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

    def _project_conversation_assistant_message(
        self,
        *,
        run: Mapping[str, Any],
        event_record: Mapping[str, Any],
        projection_at: str,
    ) -> None:
        """Project one exact safe runtime Message into its Conversation once."""

        conversation_id = run["conversation_id"]
        content = event_record["content"]
        if (
            run["source"] != "console"
            or conversation_id is None
            or run["turn_id"] is None
            or event_record["event_type"] != AgentEventType.MESSAGE.value
            or content is None
        ):
            return
        try:
            _, content_json, content_bytes = canonical_message_content(
                content,
                role="assistant",
            )
        except ConversationRepositoryError as exc:
            raise RunRepositoryValidationError(
                "conversation.message_invalid"
            ) from exc
        source_key = "assistant:" + hashlib.sha256(
            (
                str(run["id"])
                + ":"
                + str(event_record["source_key"])
            ).encode("utf-8")
        ).hexdigest()
        message_id = "msg_" + hashlib.sha256(
            (str(conversation_id) + ":" + source_key).encode("utf-8")
        ).hexdigest()[:32]
        existing = self.connection.execute(
            "SELECT * FROM mentat_conversation_messages "
            "WHERE conversation_id = ? AND source_key = ?",
            (conversation_id, source_key),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["id"]) != message_id
                or str(existing["role"]) != "assistant"
                or str(existing["state"]) != "accepted"
                or str(existing["content_json"]) != content_json
                or int(existing["content_bytes"]) != content_bytes
                or existing["run_id"] != run["id"]
            ):
                raise RunRepositoryError("conversation.message_projection_conflict")
            return
        conversation = self.connection.execute(
            "SELECT next_message_sequence FROM mentat_conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if conversation is None:
            raise RunRepositoryError("run_repository.corrupt")
        message_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM mentat_conversation_messages"
            ).fetchone()[0]
        )
        total_bytes = int(
            self.connection.execute(
                "SELECT COALESCE(SUM(content_bytes), 0) "
                "FROM mentat_conversation_messages"
            ).fetchone()[0]
        )
        if (
            message_count >= MAX_CONVERSATION_MESSAGES
            or total_bytes + content_bytes > MAX_TOTAL_MESSAGE_BYTES
        ):
            raise RunRepositoryValidationError("conversation.capacity_exceeded")
        sequence = int(conversation["next_message_sequence"])
        event_at = _timestamp(event_record["occurred_at"])
        self.connection.execute(
            """
            INSERT INTO mentat_conversation_messages (
                id, conversation_id, sequence, role, state, content_json,
                content_bytes, run_id, revision, source_key, created_at,
                updated_at
            ) VALUES (?, ?, ?, 'assistant', 'accepted', ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                message_id,
                conversation_id,
                sequence,
                content_json,
                content_bytes,
                run["id"],
                source_key,
                event_at,
                event_at,
            ),
        )
        updated = self.connection.execute(
            "UPDATE mentat_conversations SET revision = revision + 1, "
            "next_message_sequence = ?, updated_at = ? "
            "WHERE id = ? AND next_message_sequence = ?",
            (sequence + 1, projection_at, conversation_id, sequence),
        ).rowcount
        if updated != 1:
            raise RunRepositoryConflict("conversation.state_changed")

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

    def recover_conversation_submissions(
        self,
        *,
        now: str | None = None,
    ) -> tuple[str, ...]:
        """Recover pre-attempt reservations and claimed uncertain submissions."""

        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            rows = self.connection.execute(
                """
                SELECT r.id, r.status, r.dispatch_state, r.turn_id,
                       r.conversation_id,
                       t.state AS turn_state, t.attempt_count
                FROM mentat_runs AS r
                JOIN mentat_conversation_turns AS t ON t.id = r.turn_id
                WHERE r.source = 'console' AND r.conversation_id IS NOT NULL
                  AND (
                    (r.status = 'reserved' AND r.dispatch_state = 'reserved'
                     AND t.state = 'dispatching' AND t.attempt_count >= 0)
                    OR
                    (r.status = 'submitting' AND r.dispatch_state = 'submitting'
                     AND t.state = 'dispatching' AND t.attempt_count >= 1)
                    OR
                    (r.dispatch_state = 'accepted' AND r.runtime_run_ref IS NULL
                     AND r.status IN (
                        'queued', 'starting', 'running', 'cancelling', 'waiting',
                        'waiting_for_approval', 'waiting_for_clarification'
                     ) AND t.state = 'consumed' AND t.attempt_count >= 1)
                  )
                ORDER BY r.id
                """
            ).fetchall()
            recovered: list[str] = []
            for row in rows:
                run_id = str(row["id"])
                turn_id = str(row["turn_id"])
                if row["dispatch_state"] == "reserved":
                    next_status = "interrupted"
                    next_dispatch_state = "rejected"
                    event_type = AgentEventType.RUN_INTERRUPTED
                    summary = "Mentat restarted before Conversation Turn submission"
                else:
                    next_status = "unknown"
                    next_dispatch_state = "unknown"
                    event_type = AgentEventType.SUBMISSION_UNKNOWN
                    summary = (
                        "Accepted runtime state could not be reattached after restart"
                        if row["dispatch_state"] == "accepted"
                        else "Mentat restarted during Conversation Turn submission"
                    )
                run_updated = self.connection.execute(
                    "UPDATE mentat_runs SET status = ?, dispatch_state = ?, partial = 1, "
                    "resume_of_run_id = NULL, "
                    "terminal_finalized = CASE WHEN ? = 'interrupted' "
                    "THEN 1 ELSE terminal_finalized END, "
                    "state_revision = state_revision + 1, updated_at = ?, "
                    "completed_at = CASE WHEN ? = 'interrupted' THEN ? ELSE NULL END "
                    "WHERE id = ? AND status = ? AND dispatch_state = ?",
                    (
                        next_status,
                        next_dispatch_state,
                        next_status,
                        occurred_at,
                        next_status,
                        occurred_at,
                        run_id,
                        row["status"],
                        row["dispatch_state"],
                    ),
                ).rowcount
                if row["dispatch_state"] == "accepted":
                    turn_updated = 1
                else:
                    turn_updated = self.connection.execute(
                        "UPDATE mentat_conversation_turns SET state = 'consumed', "
                        "revision = revision + 1, updated_at = ? "
                        "WHERE id = ? AND state = 'dispatching' AND attempt_count = ?",
                        (occurred_at, turn_id, row["attempt_count"]),
                    ).rowcount
                if run_updated != 1 or turn_updated != 1:
                    raise RunRepositoryConflict("conversation.state_changed")
                self._append_next_lifecycle_event(
                    run_id,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    summary=summary,
                    source_key=f"restart:{turn_id}:{next_dispatch_state}",
                )
                self._block_oldest_pending_turn(
                    conversation_id=str(row["conversation_id"]),
                    reason=(
                        "interrupted"
                        if next_status == "interrupted"
                        else "unknown"
                    ),
                    occurred_at=occurred_at,
                )
                recovered.append(run_id)
            self._apply_retention()
            return tuple(recovered)

    def recover_unfinalized_conversation_terminals(
        self,
        *,
        now: str | None = None,
    ) -> tuple[str, ...]:
        """Fail closed after a crash between terminal output and finalization."""

        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            rows = self.connection.execute(
                "SELECT id, conversation_id FROM mentat_runs "
                "WHERE source = 'console' AND conversation_id IS NOT NULL "
                "AND runtime_type = 'hermes' AND dispatch_state = 'accepted' "
                "AND status IN ('completed', 'failed', 'cancelled', 'stopped', "
                "'interrupted') AND terminal_finalized = 0 ORDER BY id"
            ).fetchall()
            recovered: list[str] = []
            for row in rows:
                run_id = str(row["id"])
                updated = self.connection.execute(
                    "UPDATE mentat_runs SET partial = 1, terminal_finalized = 1, "
                    "state_revision = state_revision + 1, updated_at = ? "
                    "WHERE id = ? AND source = 'console' "
                    "AND conversation_id = ? AND runtime_type = 'hermes' "
                    "AND dispatch_state = 'accepted' AND terminal_finalized = 0 "
                    "AND status IN ('completed', 'failed', 'cancelled', 'stopped', "
                    "'interrupted')",
                    (occurred_at, run_id, row["conversation_id"]),
                ).rowcount
                if updated != 1:
                    raise RunRepositoryConflict("conversation.state_changed")
                self._block_oldest_pending_turn(
                    conversation_id=str(row["conversation_id"]),
                    reason="partial",
                    occurred_at=occurred_at,
                )
                recovered.append(run_id)
            self._apply_retention()
            return tuple(recovered)

    def mark_control_delivery_partial(
        self,
        expected: RunRecord,
        *,
        now: str | None = None,
    ) -> RunRecord:
        """Make an ambiguous post-attempt Run control durably sticky.

        Runtime delivery can become unknowable after the external control call
        has started.  Bind that ambiguity to the exact canonical Run identity,
        preserve it across later reconciliation, and pause the exact
        Conversation's FIFO head before it can be admitted automatically.
        """

        if not isinstance(expected, RunRecord):
            raise RunRepositoryValidationError("run.control_invalid")
        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            row = self.connection.execute(
                "SELECT * FROM mentat_runs WHERE id = ?",
                (expected.id,),
            ).fetchone()
            if row is None:
                raise RunRepositoryConflict("run.not_found")
            current = self._run_record(row)
            identity = (
                "source",
                "task_id",
                "agent_id",
                "runtime_type",
                "runtime_config_id",
                "runtime_binding_digest",
                "runtime_run_ref",
                "conversation_id",
                "turn_id",
            )
            if any(getattr(current, key) != getattr(expected, key) for key in identity):
                raise RunRepositoryConflict("run.control_identity_changed")
            if current.dispatch_state not in {"accepted", "unknown"}:
                raise RunRepositoryConflict("run.control_unavailable")
            if datetime.fromisoformat(occurred_at.replace("Z", "+00:00")) < datetime.fromisoformat(
                current.updated_at.replace("Z", "+00:00")
            ):
                raise RunRepositoryConflict("run.timestamp_regression")
            if not current.partial:
                updated = self.connection.execute(
                    "UPDATE mentat_runs SET partial = 1, "
                    "state_revision = state_revision + 1, updated_at = ? "
                    "WHERE id = ? AND partial = 0",
                    (occurred_at, current.id),
                ).rowcount
                if updated != 1:
                    raise RunRepositoryConflict("run.state_changed")
            if current.conversation_id is not None:
                self._block_oldest_pending_turn(
                    conversation_id=current.conversation_id,
                    reason="partial",
                    occurred_at=occurred_at,
                )
            self._apply_retention()
            return self.get_run(current.id)

    def recover_console_runs_as_interrupted(
        self, *, now: str | None = None
    ) -> tuple[str, ...]:
        """Terminalize legacy Console work that has no durable reattachment."""

        occurred_at = _timestamp(now or _now_iso())
        with self.mutation():
            placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
            rows = self.connection.execute(
                f"SELECT id FROM mentat_runs WHERE source = 'console' "
                f"AND conversation_id IS NULL "
                f"AND status IN ({placeholders}) ORDER BY id",
                tuple(sorted(_ACTIVE_STATUSES)),
            ).fetchall()
            recovered: list[str] = []
            for row in rows:
                run_id = str(row["id"])
                updated = self.connection.execute(
                    "UPDATE mentat_runs SET status = 'interrupted', partial = 1, "
                    "state_revision = state_revision + 1, updated_at = ?, completed_at = ? "
                    "WHERE id = ? AND source = 'console' AND conversation_id IS NULL",
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
                "WHERE (source = 'task_dispatch' OR ("
                "source = 'console' AND conversation_id IS NOT NULL "
                "AND turn_id IS NOT NULL AND runtime_run_ref IS NOT NULL)) "
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
        """Lease one exact durably reattachable Run for readback."""

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
                "WHERE id = ? AND (source = 'task_dispatch' OR ("
                "source = 'console' AND conversation_id IS NOT NULL "
                "AND turn_id IS NOT NULL AND runtime_run_ref IS NOT NULL)) "
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

    def lease_transient_conversation_run(
        self,
        *,
        run_id: str,
        owner: str,
        now_epoch: float | None = None,
        lease_seconds: float = 30.0,
    ) -> RunRecord | None:
        """Lease one just-accepted attached Console Run before process loss."""

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
                "WHERE id = ? AND source = 'console' "
                "AND conversation_id IS NOT NULL AND turn_id IS NOT NULL "
                "AND runtime_run_ref IS NULL AND dispatch_state = 'accepted' "
                "AND status IN ('queued', 'starting', 'running', 'cancelling', "
                "'waiting', 'waiting_for_approval', 'waiting_for_clarification') "
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
        continuation: ConversationRunAdmission | None = None,
        require_continuation_for_completed: bool = False,
        now: str | None = None,
    ) -> RunRecord:
        identifier = _identifier(run_id)
        event_batch = tuple(events)
        if observed.id != identifier:
            raise RunRepositoryConflict("reconcile.identity_mismatch")
        observed_status = observed.status.value
        if (
            observed_status not in _OBSERVABLE_RUNTIME_STATUSES
            or type(defer_terminal) is not bool
            or type(require_continuation_for_completed) is not bool
            or continuation is not None
            and not isinstance(continuation, ConversationRunAdmission)
        ):
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
                observed.task_id
                != (
                    row["task_id"]
                    if row["task_id"] is not None
                    else row["turn_id"]
                    if row["source"] == "console"
                    and row["conversation_id"] is not None
                    else None
                )
                or (row["agent_id"] is not None and observed.agent_id != row["agent_id"])
                or observed.runtime_type != row["runtime_type"]
            ):
                raise RunRepositoryConflict("reconcile.identity_mismatch")
            if str(row["status"]) in _TERMINAL_STATUSES:
                raise RunRepositoryConflict("reconcile.run_terminal")
            terminal_event_statuses = {
                {
                    AgentEventType.RUN_COMPLETED: "completed",
                    AgentEventType.RUN_FAILED: "failed",
                    AgentEventType.RUN_STOPPED: "stopped",
                    AgentEventType.RUN_INTERRUPTED: "interrupted",
                }[event.type]
                for event in event_batch
                if event.type
                in {
                    AgentEventType.RUN_COMPLETED,
                    AgentEventType.RUN_FAILED,
                    AgentEventType.RUN_STOPPED,
                    AgentEventType.RUN_INTERRUPTED,
                }
            }
            terminal_events = tuple(
                event
                for event in event_batch
                if event.type
                in {
                    AgentEventType.RUN_COMPLETED,
                    AgentEventType.RUN_FAILED,
                    AgentEventType.RUN_STOPPED,
                    AgentEventType.RUN_INTERRUPTED,
                }
            )
            if terminal_events and (
                len(terminal_events) != 1
                or len(terminal_event_statuses) != 1
                or defer_terminal
                or terminal_events[0].sequence
                != max(event.sequence for event in event_batch)
            ):
                raise RunRepositoryConflict("reconcile.terminal_event_conflict")
            inferred_terminal = False
            if terminal_event_statuses:
                terminal_event_status = next(iter(terminal_event_statuses))
                if (
                    observed_status in _TERMINAL_STATUSES
                    and observed_status != terminal_event_status
                ):
                    raise RunRepositoryConflict("reconcile.terminal_event_conflict")
                inferred_terminal = observed_status != terminal_event_status
                observed_status = terminal_event_status
            expected_terminal_event = {
                "completed": AgentEventType.RUN_COMPLETED,
                "failed": AgentEventType.RUN_FAILED,
                "stopped": AgentEventType.RUN_STOPPED,
                "interrupted": AgentEventType.RUN_INTERRUPTED,
            }.get(observed_status)
            finalized_terminal = bool(
                expected_terminal_event is not None
                and any(
                    event.type == expected_terminal_event
                    for event in event_batch
                )
            )
            wait_for_hermes_finalization = bool(
                str(row["runtime_type"]) == "hermes"
                and expected_terminal_event is not None
                and not finalized_terminal
            )
            next_status = (
                str(row["status"])
                if (defer_terminal or wait_for_hermes_finalization)
                and observed_status in _TERMINAL_STATUSES
                else observed_status
            )
            if next_status not in _RECONCILIATION_TRANSITIONS.get(
                str(row["status"]), frozenset({str(row["status"])})
            ):
                raise RunRepositoryConflict("reconcile.status_regression")

            source_cursor = int(row["runtime_event_cursor"])
            next_source_cursor = source_cursor
            for event in event_batch:
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
                self._project_conversation_assistant_message(
                    run=row,
                    event_record=record,
                    projection_at=occurred_at,
                )
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
            terminal_finalized = int(
                bool(row["terminal_finalized"])
                or (
                    next_status in _TERMINAL_STATUSES
                    and (
                        str(row["runtime_type"]) != "hermes"
                        or finalized_terminal
                    )
                )
            )
            if row["source"] == "task_dispatch":
                authority_updated = self.connection.execute(
                    "UPDATE mentat_dispatch_reservations "
                    "SET state = 'accepted', updated_at = ? "
                    "WHERE run_id = ? AND state IN ('accepted', 'unknown')",
                    (occurred_at, identifier),
                ).rowcount
            elif row["source"] == "console" and row["conversation_id"] is not None:
                turn = self.connection.execute(
                    "SELECT state, attempt_count, latest_run_id "
                    "FROM mentat_conversation_turns WHERE id = ? "
                    "AND conversation_id = ?",
                    (row["turn_id"], row["conversation_id"]),
                ).fetchone()
                authority_updated = int(
                    turn is not None
                    and turn["state"] == "consumed"
                    and int(turn["attempt_count"]) >= 1
                    and turn["latest_run_id"] == identifier
                )
            else:
                authority_updated = 0
            if authority_updated != 1:
                raise RunRepositoryConflict("reconcile.dispatch_state_invalid")
            updated = self.connection.execute(
                "UPDATE mentat_runs SET status = ?, dispatch_state = 'accepted', "
                "partial = ?, terminal_finalized = ?, runtime_event_cursor = ?, updated_at = ?, "
                "started_at = COALESCE(started_at, ?), "
                "completed_at = ?, reconcile_lease_owner = NULL, "
                "reconcile_lease_until = NULL, state_revision = state_revision + 1 "
                "WHERE id = ? AND reconcile_lease_owner = ? AND state_revision = ?",
                (
                    next_status,
                    (
                        0
                        if str(row["dispatch_state"]) == "unknown"
                        else int(row["partial"])
                    ),
                    terminal_finalized,
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
            self._promote_completed_task_execution(
                run_id=identifier,
                completed=next_status == "completed",
                terminal_finalized=bool(terminal_finalized),
                partial=(
                    False
                    if str(row["dispatch_state"]) == "unknown"
                    else bool(row["partial"])
                ),
                occurred_at=occurred_at,
            )
            if (
                row["source"] == "console"
                and row["conversation_id"] is not None
                and next_status in _TERMINAL_STATUSES
            ):
                blocking_reason = None
                if str(row["status"]) == "unknown":
                    blocking_reason = "unknown"
                elif bool(row["partial"]):
                    blocking_reason = "partial"
                elif next_status == "failed":
                    blocking_reason = "failed"
                elif next_status in {"stopped", "cancelled"}:
                    blocking_reason = "stopped"
                elif next_status == "interrupted":
                    blocking_reason = "interrupted"
                if blocking_reason is not None:
                    self._block_oldest_pending_turn(
                        conversation_id=str(row["conversation_id"]),
                        reason=blocking_reason,
                        occurred_at=occurred_at,
                    )
                elif next_status == "completed" and continuation is not None:
                    try:
                        self._reserve_oldest_queued_conversation_turn(
                            conversation_id=str(row["conversation_id"]),
                            admission=continuation,
                            allow_blocked=False,
                            expected_turn_id=None,
                            expected_turn_revision=None,
                            expected_message_revision=None,
                            occurred_at=occurred_at,
                        )
                    except RunRepositoryConflict as exc:
                        if exc.code not in {
                            "conversation.active_run",
                            "conversation.agent_changed",
                            "conversation.agent_missing",
                            "conversation.binding_changed",
                        }:
                            raise
                        # Completion remains verified, but current admission
                        # evidence no longer authorizes an automatic next Run.
                        self._block_oldest_pending_turn(
                            conversation_id=str(row["conversation_id"]),
                            reason="partial",
                            occurred_at=occurred_at,
                        )
                elif next_status == "completed" and (
                    require_continuation_for_completed or inferred_terminal
                ):
                    self._block_oldest_pending_turn(
                        conversation_id=str(row["conversation_id"]),
                        reason="partial",
                        occurred_at=occurred_at,
                    )
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

    def _conversation_worker_continuation_admission(
        self,
        existing: Mapping[str, Any],
    ) -> ConversationRunAdmission | None:
        """Build current private Hermes evidence for one worker continuation."""

        if str(existing["runtime_type"]) != "hermes":
            return None
        agent = self.connection.execute(
            """
            SELECT a.id, a.name, a.revision, a.runtime_config_id,
                   a.capabilities_json, c.runtime_type, c.runtime_agent_ref
            FROM mentat_agents AS a
            JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id
            WHERE a.id = ?
            """,
            (existing["agent_id"],),
        ).fetchone()
        if agent is None or str(agent["runtime_type"]) != "hermes":
            return None
        capabilities = _decode_json(
            agent["capabilities_json"],
            expected=list,
            code="run_repository.corrupt",
        )
        if (
            any(not isinstance(value, str) for value in capabilities)
            or capabilities != sorted(set(capabilities))
            or "run.start" not in capabilities
            or _canonical_json(
                capabilities,
                maximum=8_192,
                code="run_repository.corrupt",
            )
            != agent["capabilities_json"]
        ):
            return None
        binding_digest = runtime_binding_digest(
            agent_id=str(agent["id"]),
            runtime_type=str(agent["runtime_type"]),
            runtime_config_id=str(agent["runtime_config_id"]),
            runtime_agent_ref=str(agent["runtime_agent_ref"]),
            capabilities=capabilities,
        )
        capacity_scope_digest, capacity_limit = default_runtime_capacity_evidence(
            runtime_type=str(agent["runtime_type"]),
            binding_digest=binding_digest,
        )
        return ConversationRunAdmission(
            run_id=(
                "run_auto_"
                + hashlib.sha256(
                    (str(existing["id"]) + ":accepted-continuation").encode(
                        "utf-8"
                    )
                ).hexdigest()[:32]
            ),
            agent_id=str(agent["id"]),
            agent_name=str(agent["name"]),
            agent_revision=int(agent["revision"]),
            runtime_type=str(agent["runtime_type"]),
            runtime_config_id=str(agent["runtime_config_id"]),
            runtime_config_revision=1,
            runtime_binding_digest=binding_digest,
            capabilities=tuple(capabilities),
            capacity_scope_digest=capacity_scope_digest,
            capacity_limit=capacity_limit,
            predecessor_run_id=str(existing["id"]),
        )

    def _update_conversation_console_snapshot(
        self,
        run: Mapping[str, Any],
        *,
        existing: Mapping[str, Any],
        status: str,
        runtime_type: str,
        agent_id: str | None,
        task_id: str | None,
        details_json: str,
        raw_events: Sequence[Mapping[str, Any]],
        updated_at: str,
        started_at: str | None,
        completed_at: str | None,
    ) -> ConversationDispatchReservation | None:
        """Merge one Hermes worker snapshot without touching reserved authority."""

        if (
            str(existing["source"]) != "console"
            or existing["conversation_id"] is None
            or not isinstance(existing["turn_id"], str)
            or task_id != str(existing["turn_id"])
            or agent_id != str(existing["agent_id"])
            or run.get("runtime_type") != str(existing["runtime_type"])
            or runtime_type != str(existing["runtime_type"])
            or run.get("_dispatch_id") != str(existing["turn_id"])
        ):
            raise RunRepositoryConflict("run.console_authority_conflict")

        snapshot_status = run.get("status")
        if not isinstance(snapshot_status, str) or snapshot_status not in _ALL_STATUSES:
            raise RunRepositoryValidationError("run.status_invalid")
        if status != snapshot_status:
            raise RunRepositoryValidationError("run.status_invalid")
        snapshot_partial = run.get("partial")
        if type(snapshot_partial) is not bool:
            raise RunRepositoryValidationError("run.partial_invalid")
        snapshot_finalized = any(
            str(item.get("type") or item.get("kind") or "")
            == "runtime.finalized"
            for item in raw_events
        )
        current_status = str(existing["status"])
        dispatch_state = str(existing["dispatch_state"])
        next_dispatch_state = dispatch_state
        # Independent ambiguity (for example an accepted-but-unverified steer)
        # is sticky across otherwise verified worker snapshots.
        next_partial = max(int(existing["partial"]), int(snapshot_partial))
        projected_status = {
            "queued": "starting",
            "cancelled": "stopped",
            "waiting_for_approval": "waiting",
            "waiting_for_clarification": "waiting",
        }.get(status, status)
        if dispatch_state == "submitting":
            if current_status != "submitting":
                raise RunRepositoryConflict("run.console_authority_conflict")
            projected_status = current_status
            projected_completed = existing["completed_at"]
        elif dispatch_state in {"accepted", "unknown"}:
            if dispatch_state == "unknown" and projected_status == "unknown":
                # An unknown snapshot supplies no new authority. Preserve the
                # exact fail-closed canonical state, details, and events until
                # the still-owning worker supplies a verified observable
                # runtime status.
                return None
            allowed = _RECONCILIATION_TRANSITIONS.get(current_status)
            same_terminal = (
                current_status in _TERMINAL_STATUSES
                and projected_status == current_status
            )
            if (
                not same_terminal
                and (allowed is None or projected_status not in allowed)
            ):
                raise RunRepositoryConflict("run.status_regression")
            if dispatch_state == "unknown":
                # This also repairs the exact pre-fix shape where a verified
                # terminal snapshot changed status before atomically restoring
                # its admission state.
                next_dispatch_state = "accepted"
                # Unknown admission itself sets partial. Exact late runtime
                # evidence resolves only that ambiguity; preserve any separate
                # partial evidence carried by the still-owning worker.
                next_partial = int(snapshot_partial)
            projected_completed = (
                completed_at if projected_status in _TERMINAL_STATUSES else None
            )
            if projected_status in _TERMINAL_STATUSES and projected_completed is None:
                projected_completed = updated_at
        else:
            raise RunRepositoryConflict("run.console_authority_conflict")

        finalized_before = bool(existing["terminal_finalized"])
        next_terminal_finalized = int(
            finalized_before
            or (
                snapshot_finalized
                and dispatch_state != "submitting"
                and projected_status in _TERMINAL_STATUSES
            )
        )

        next_updated = max(
            (_timestamp(existing["updated_at"]), updated_at),
            key=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")),
        )
        projected = (
            projected_status,
            details_json,
            next_updated,
            existing["started_at"]
            if existing["started_at"] is not None
            else started_at,
            projected_completed,
            next_dispatch_state,
            next_partial,
            next_terminal_finalized,
        )
        current = tuple(
            existing[key]
            for key in (
                "status",
                "details_json",
                "updated_at",
                "started_at",
                "completed_at",
                "dispatch_state",
                "partial",
                "terminal_finalized",
            )
        )
        if projected != current:
            updated = self.connection.execute(
                "UPDATE mentat_runs SET status = ?, details_json = ?, updated_at = ?, "
                "started_at = ?, completed_at = ?, dispatch_state = ?, partial = ?, "
                "terminal_finalized = ?, state_revision = state_revision + 1 "
                "WHERE id = ? AND conversation_id = ? AND turn_id = ? "
                "AND dispatch_state = ? AND state_revision = ?",
                (
                    *projected,
                    existing["id"],
                    existing["conversation_id"],
                    existing["turn_id"],
                    dispatch_state,
                    existing["state_revision"],
                ),
            ).rowcount
            if updated != 1:
                raise RunRepositoryConflict("run.state_changed")

        if next_dispatch_state == "accepted":
            provider = run.get("provider")
            model = run.get("model")
            if isinstance(provider, str) and provider and isinstance(model, str) and model:
                identity_json, identity_digest = _runtime_execution_document(
                    {
                        "model": model,
                        "provider": provider,
                        "reasoning_effort": None,
                        "verification": "runtime_launch_snapshot",
                    }
                )
                self.connection.execute(
                    "UPDATE mentat_runs SET runtime_execution_json = ?, "
                    "runtime_execution_digest = ?, state_revision = state_revision + 1 "
                    "WHERE id = ? AND source = 'console' "
                    "AND conversation_id IS NOT NULL "
                    "AND runtime_execution_json IS NULL "
                    "AND runtime_execution_digest IS NULL",
                    (identity_json, identity_digest, existing["id"]),
                )

        current_run = self.connection.execute(
            "SELECT * FROM mentat_runs WHERE id = ?", (existing["id"],)
        ).fetchone()
        if current_run is None:
            raise RunRepositoryConflict("run.not_found")

        run_id = str(existing["id"])
        for raw_event in raw_events:
            raw_type = str(raw_event.get("type") or raw_event.get("kind") or "")
            if (
                raw_type == "runtime.finalized"
                and (
                    dispatch_state == "submitting"
                    or projected_status not in _TERMINAL_STATUSES
                )
            ):
                # Its terminal type depends on the canonical accepted status.
                # A post-acceptance readback records the terminal lifecycle
                # without freezing a pre-acceptance failure classification.
                continue
            normalized = _event_record(run_id, projected_status, raw_event)
            source_key = f"console:{normalized['id']}"
            prior = self.connection.execute(
                "SELECT source_type, occurred_at, summary, metrics_json, data_json "
                "FROM mentat_agent_events WHERE run_id = ? AND source_key = ?",
                (run_id, source_key),
            ).fetchone()
            if prior is not None:
                if any(
                    prior[key] != normalized[key]
                    for key in (
                        "source_type",
                        "occurred_at",
                        "summary",
                        "metrics_json",
                        "data_json",
                    )
                ):
                    raise RunRepositoryConflict("event.conflict")
                continue
            last_sequence = int(
                self.connection.execute(
                    "SELECT last_event_sequence FROM mentat_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            record = dict(normalized)
            record["id"] = (
                "event_"
                + hashlib.sha256(
                    f"{run_id}:{source_key}".encode("utf-8")
                ).hexdigest()[:32]
            )
            record["sequence"] = last_sequence + 1
            record["source_key"] = source_key
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
                _canonical_json(
                    digest_payload,
                    maximum=32_768,
                    code="event.invalid",
                ).encode("ascii")
            ).hexdigest()
            self._append_event_record(record)

        finalized_after = bool(next_terminal_finalized)
        terminal_transition = (
            projected_status in _TERMINAL_STATUSES
            and (
                current_status not in _TERMINAL_STATUSES
                or dispatch_state == "unknown"
            )
        )
        terminal_boundary = (
            finalized_after
            and projected_status in _TERMINAL_STATUSES
            and (terminal_transition or not finalized_before)
        )
        if not terminal_boundary:
            return None
        current_run = self.connection.execute(
            "SELECT * FROM mentat_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if current_run is None:
            raise RunRepositoryConflict("run.not_found")
        if next_dispatch_state == "accepted" and projected_status == "completed":
            self._project_console_snapshot_response(
                run=current_run,
                snapshot=run,
                projection_at=next_updated,
            )
        conversation_id = str(existing["conversation_id"])
        blocking_reason = None
        if dispatch_state == "unknown":
            # Late evidence may repair the Run, but ambiguity must never
            # cause an automatic submission of the next queued Turn.
            blocking_reason = "unknown"
        elif bool(next_partial):
            blocking_reason = "partial"
        elif projected_status == "failed":
            blocking_reason = "failed"
        elif projected_status in {"stopped", "cancelled"}:
            blocking_reason = "stopped"
        elif projected_status == "interrupted":
            blocking_reason = "interrupted"
        if blocking_reason is not None:
            self._block_oldest_pending_turn(
                conversation_id=conversation_id,
                reason=blocking_reason,
                occurred_at=next_updated,
            )
            return None
        if projected_status != "completed":
            return None
        admission = self._conversation_worker_continuation_admission(current_run)
        if admission is None:
            self._block_oldest_pending_turn(
                conversation_id=conversation_id,
                reason="partial",
                occurred_at=next_updated,
            )
            return None
        try:
            return self._reserve_oldest_queued_conversation_turn(
                conversation_id=conversation_id,
                admission=admission,
                allow_blocked=False,
                expected_turn_id=None,
                expected_turn_revision=None,
                expected_message_revision=None,
                occurred_at=next_updated,
            )
        except RunRepositoryConflict as exc:
            if exc.code not in {
                "conversation.active_run",
                "conversation.agent_changed",
                "conversation.agent_missing",
                "conversation.binding_changed",
            }:
                raise
            self._block_oldest_pending_turn(
                conversation_id=conversation_id,
                reason="partial",
                occurred_at=next_updated,
            )
            return None

    def _project_console_snapshot_response(
        self,
        *,
        run: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        projection_at: str,
    ) -> None:
        """Project one verified completed Console response exactly once."""

        response = snapshot.get("response")
        if not isinstance(response, str):
            raise RunRepositoryValidationError("conversation.message_invalid")
        content = bounded_public_excerpt(response, MAX_ASSISTANT_MESSAGE_LENGTH)[0]
        if not content:
            return
        if (
            run["source"] != "console"
            or run["conversation_id"] is None
            or run["turn_id"] is None
            or run["status"] != "completed"
            or run["dispatch_state"] != "accepted"
            or run["completed_at"] is None
        ):
            raise RunRepositoryConflict("run.console_authority_conflict")

        run_id = str(run["id"])
        correlation = hashlib.sha256(
            (run_id + ":" + str(run["turn_id"])).encode("utf-8")
        ).hexdigest()[:32]
        source_key = f"console-response:{correlation}"
        event_id = f"event_{correlation}"
        prior = self.connection.execute(
            "SELECT * FROM mentat_agent_events WHERE run_id = ? AND source_key = ?",
            (run_id, source_key),
        ).fetchone()
        if prior is None:
            sequence = int(run["last_event_sequence"]) + 1
        else:
            sequence = int(prior["sequence"])
        event = AgentEvent(
            id=event_id,
            run_id=run_id,
            sequence=sequence,
            type=AgentEventType.MESSAGE,
            occurred_at=_timestamp(run["completed_at"]),
            summary="Assistant response",
            content=content,
        )
        record = dict(_event_from_domain(event))
        record["source_key"] = source_key
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
            _canonical_json(
                digest_payload,
                maximum=32_768,
                code="event.invalid",
            ).encode("ascii")
        ).hexdigest()
        if prior is None:
            self._append_event_record(record)
        elif any(
            prior[key] != record[key]
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
                "content_bytes",
                "payload_digest",
            )
        ):
            raise RunRepositoryConflict("event.conflict")
        self._project_conversation_assistant_message(
            run=run,
            event_record=record,
            projection_at=projection_at,
        )

    def _upsert_summary(
        self,
        run: Mapping[str, Any],
        *,
        dispatch_state: str = "legacy",
    ) -> ConversationDispatchReservation | None:
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
            "SELECT * FROM mentat_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        importing = existing is None
        if existing is not None and existing["conversation_id"] is not None:
            return self._update_conversation_console_snapshot(
                run,
                existing=existing,
                status=status,
                runtime_type=runtime_type,
                agent_id=agent_id,
                task_id=task_id,
                details_json=details_json,
                raw_events=raw_events,
                updated_at=updated_at,
                started_at=started_at,
                completed_at=completed_at,
            )
        continuation = None
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
        return continuation

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
            continuations: list[tuple[str, str]] = []
            for run in runs:
                continuation = self._upsert_summary(run)
                if continuation is not None:
                    continuations.append(
                        (_identifier(run.get("id")), continuation.turn_id)
                    )
            retained = self._apply_retention()
            return RetentionReport(
                retained.removed_run_ids,
                retained.truncated_run_ids,
                tuple(continuations),
            )

    def _event_rows(self, run_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM mentat_agent_events WHERE run_id = ? ORDER BY sequence",
            (run_id,),
        ).fetchall()

    def _project_bound_media(
        self,
        run_id: str,
        details: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Expose content routes only for canonical, direction-bound media."""

        rows = self.connection.execute(
            "SELECT attachment_id, direction FROM run_attachments WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        retained = {
            "input": {str(row["attachment_id"]) for row in rows if row["direction"] == "input"},
            "output": {str(row["attachment_id"]) for row in rows if row["direction"] == "output"},
        }
        projected = dict(details)
        # details_json is a bounded display snapshot. The run_attachments graph
        # remains the authority for blob retention and access, so stale legacy
        # metadata must never mint a same-origin content route by itself.
        projected["attachments"] = [
            item
            for item in details["attachments"]
            if item["id"] in retained["input"]
        ]
        projected["artifacts"] = [
            item
            for item in details["artifacts"]
            if item["id"] in retained["output"]
        ]
        return projected

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
            f"AND conversation_id IS NULL "
            f"AND status IN ({placeholders}) "
            "ORDER BY created_at DESC, id DESC",
            tuple(sorted(_ACTIVE_STATUSES)),
        ).fetchall()
        terminal_rows = self.connection.execute(
            f"SELECT * FROM mentat_runs WHERE source = 'console' "
            f"AND conversation_id IS NULL "
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
            details = self._project_bound_media(
                str(row["id"]),
                _validated_run_details(row),
            )
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

    def list_hydrated_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[tuple[HydratedRunEvent, ...], bool, int]:
        """Hydrate validated events with server-only presentation provenance."""

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
        events: list[HydratedRunEvent] = []
        for event_row in event_rows:
            if int(event_row["sequence"]) <= after_sequence:
                continue
            events.append(
                HydratedRunEvent(
                    event=AgentEvent(
                        id=str(event_row["id"]),
                        run_id=identifier,
                        sequence=int(event_row["sequence"]),
                        type=str(event_row["event_type"]),
                        occurred_at=str(event_row["occurred_at"]),
                        summary=str(event_row["summary"]),
                        content=event_row["content"],
                        metrics=_decode_json(
                            event_row["metrics_json"],
                            expected=dict,
                            code="event.corrupt",
                        ),
                    ),
                    source_type=str(event_row["source_type"]),
                )
            )
        reset = bool(row["timeline_truncated"]) and (
            int(row["last_event_sequence"]) == 0
            or after_sequence < int(row["first_retained_sequence"]) - 1
        )
        return tuple(events), reset, int(row["last_event_sequence"])

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
    ) -> tuple[tuple[AgentEvent, ...], bool, int]:
        """Return the compatibility event domain without source provenance."""

        hydrated, reset, cursor = self.list_hydrated_events(
            run_id,
            after_sequence=after_sequence,
        )
        return tuple(item.event for item in hydrated), reset, cursor

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

    def _apply_retention(
        self,
        *,
        protected_run_ids: Iterable[str] = (),
    ) -> RetentionReport:
        protected = frozenset(
            _identifier(run_id) for run_id in protected_run_ids
        )
        if len(protected) > TERMINAL_RUN_RETENTION:
            raise RunRepositoryValidationError("run.retention_protection_invalid")
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
            + ") AND NOT (source = 'console' AND conversation_id IS NOT NULL "
            "AND runtime_type = 'hermes' AND terminal_finalized = 0) "
            "AND NOT EXISTS (SELECT 1 FROM mentat_runs AS successor "
            "WHERE successor.resume_of_run_id = mentat_runs.id "
            "AND successor.source = 'console' "
            "AND successor.status = 'reserved' "
            "AND successor.dispatch_state = 'reserved') "
            "AND NOT EXISTS (SELECT 1 FROM mentat_task_execution_attempts "
            "WHERE mentat_task_execution_attempts.run_id = mentat_runs.id) "
            "ORDER BY completed_at DESC, created_at DESC, id DESC",
            tuple(sorted(_ACTIVE_STATUSES)),
        ).fetchall()
        terminal_ids = tuple(str(row[0]) for row in terminal)
        protected_terminal = protected.intersection(terminal_ids)
        unprotected_terminal = tuple(
            run_id for run_id in terminal_ids if run_id not in protected_terminal
        )
        retained_unprotected = max(
            0,
            TERMINAL_RUN_RETENTION - len(protected_terminal),
        )
        removed = unprotected_terminal[retained_unprotected:]
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
        has_terminal_finalized = any(
            str(column[1]) == "terminal_finalized"
            for column in self.connection.execute("PRAGMA table_info(mentat_runs)")
        )
        terminal_count = int(
            self.connection.execute(
                "SELECT COUNT(*) FROM mentat_runs WHERE status NOT IN ("
                + ",".join("?" for _ in _ACTIVE_STATUSES)
                + ")"
                + (
                    " AND NOT (source = 'console' AND conversation_id IS NOT NULL "
                    "AND runtime_type = 'hermes' AND terminal_finalized = 0) "
                    "AND NOT EXISTS (SELECT 1 FROM mentat_runs AS successor "
                    "WHERE successor.resume_of_run_id = mentat_runs.id "
                    "AND successor.source = 'console' "
                    "AND successor.status = 'reserved' "
                    "AND successor.dispatch_state = 'reserved')"
                    if has_terminal_finalized
                    else ""
                ),
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
                if row["conversation_id"] is None:
                    if str(row["dispatch_state"]) != "legacy" or row["turn_id"] is not None:
                        raise RunRepositoryError("run_repository.corrupt")
                else:
                    if (
                        str(row["dispatch_state"]) == "legacy"
                        or row["turn_id"] is None
                        or row["task_id"] is not None
                        or row["task_revision"] is not None
                        or row["task_snapshot_json"] is not None
                        or row["agent_id"] is None
                        or row["runtime_config_id"] is None
                        or row["runtime_binding_digest"] is None
                    ):
                        raise RunRepositoryError("run_repository.corrupt")
                    authority = self.connection.execute(
                        """
                        SELECT c.agent_id AS conversation_agent_id,
                               t.state AS turn_state,
                               t.attempt_count,
                               t.latest_run_id,
                               t.user_message_id,
                               t.queue_ordinal AS turn_queue_ordinal,
                               m.run_id AS message_run_id,
                               m.conversation_id AS message_conversation_id,
                               m.role AS message_role
                        FROM mentat_conversations AS c
                        JOIN mentat_conversation_turns AS t
                          ON t.conversation_id = c.id
                        JOIN mentat_conversation_messages AS m
                          ON m.id = t.user_message_id
                        WHERE c.id = ? AND t.id = ?
                        """,
                        (row["conversation_id"], row["turn_id"]),
                    ).fetchone()
                    if (
                        authority is None
                        or authority["conversation_agent_id"] != row["agent_id"]
                        or authority["message_conversation_id"] != row["conversation_id"]
                        or authority["message_role"] != "user"
                    ):
                        raise RunRepositoryError("run_repository.corrupt")
                    if authority["latest_run_id"] == row["id"]:
                        if authority["message_run_id"] != row["id"]:
                            raise RunRepositoryError("run_repository.corrupt")
                    else:
                        successor = self.connection.execute(
                            "SELECT 1 FROM mentat_conversation_run_attempts "
                            "WHERE conversation_id = ? AND turn_id = ? "
                            "AND source_run_id = ? LIMIT 1",
                            (
                                row["conversation_id"],
                                row["turn_id"],
                                row["id"],
                            ),
                        ).fetchone()
                        if (
                            authority["message_run_id"]
                            != authority["latest_run_id"]
                            or successor is None
                        ):
                            raise RunRepositoryError("run_repository.corrupt")
                    retry_predecessor_id = row["retry_of_run_id"]
                    if retry_predecessor_id is not None:
                        retry_receipt = self.connection.execute(
                            "SELECT 1 FROM mentat_conversation_run_attempts "
                            "WHERE action = 'retry' AND conversation_id = ? "
                            "AND turn_id = ? AND source_run_id = ? "
                            "AND run_id = ? LIMIT 1",
                            (
                                row["conversation_id"],
                                row["turn_id"],
                                retry_predecessor_id,
                                row["id"],
                            ),
                        ).fetchone()
                        if retry_receipt is None:
                            raise RunRepositoryError("run_repository.corrupt")
                    predecessor_id = row["resume_of_run_id"]
                    if predecessor_id is not None:
                        predecessor_id = _identifier(str(predecessor_id))
                        predecessor = self.connection.execute(
                            "SELECT * FROM mentat_runs WHERE id = ?",
                            (predecessor_id,),
                        ).fetchone()
                        resume_receipt = self.connection.execute(
                            "SELECT 1 FROM mentat_conversation_run_attempts "
                            "WHERE action = 'resume' AND conversation_id = ? "
                            "AND turn_id = ? AND source_run_id = ? "
                            "AND run_id = ? LIMIT 1",
                            (
                                row["conversation_id"],
                                row["turn_id"],
                                predecessor_id,
                                row["id"],
                            ),
                        ).fetchone()
                        if resume_receipt is not None:
                            valid_predecessor = (
                                predecessor is not None
                                and predecessor["conversation_id"]
                                == row["conversation_id"]
                                and predecessor["turn_id"] == row["turn_id"]
                                and predecessor["agent_id"] == row["agent_id"]
                                and predecessor["runtime_type"]
                                == row["runtime_type"]
                                and predecessor["runtime_binding_digest"]
                                == row["runtime_binding_digest"]
                                and predecessor["status"] in _TERMINAL_STATUSES
                                and bool(predecessor["terminal_finalized"])
                            )
                        else:
                            latest_prior = self.connection.execute(
                                "SELECT latest_run_id FROM mentat_conversation_turns "
                                "WHERE conversation_id = ? AND queue_ordinal < ? "
                                "AND latest_run_id IS NOT NULL "
                                "ORDER BY queue_ordinal DESC, id DESC LIMIT 1",
                                (
                                    row["conversation_id"],
                                    int(authority["turn_queue_ordinal"]),
                                ),
                            ).fetchone()
                            valid_predecessor = (
                                latest_prior is not None
                                and latest_prior["latest_run_id"] == predecessor_id
                                and predecessor is not None
                                and predecessor["conversation_id"]
                                == row["conversation_id"]
                                and predecessor["agent_id"] == row["agent_id"]
                                and predecessor["runtime_type"]
                                == row["runtime_type"]
                                and predecessor["runtime_binding_digest"]
                                == row["runtime_binding_digest"]
                                and predecessor["status"] == "completed"
                                and predecessor["dispatch_state"] == "accepted"
                                and not bool(predecessor["partial"])
                                and bool(predecessor["terminal_finalized"])
                            )
                        if not valid_predecessor:
                            raise RunRepositoryError("run_repository.corrupt")
                    status = str(row["status"])
                    dispatch_state = str(row["dispatch_state"])
                    turn_state = str(authority["turn_state"])
                    attempt_count = int(authority["attempt_count"])
                    legal = (
                        (
                            dispatch_state == "reserved"
                            and status == "reserved"
                            and turn_state == "dispatching"
                            and attempt_count >= 0
                        )
                        or (
                            dispatch_state == "submitting"
                            and status == "submitting"
                            and turn_state == "dispatching"
                            and attempt_count >= 1
                        )
                        or (
                            dispatch_state == "accepted"
                            and status not in {"reserved", "submitting", "unknown"}
                            and turn_state == "consumed"
                            and attempt_count >= 1
                        )
                        or (
                            dispatch_state == "rejected"
                            and status in {"failed", "interrupted"}
                            and turn_state == "consumed"
                            and attempt_count >= 0
                        )
                        or (
                            dispatch_state == "unknown"
                            and status == "unknown"
                            and turn_state == "consumed"
                            and attempt_count >= 1
                        )
                    )
                    if not legal:
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
    "ConversationDispatchReservation",
    "ConversationRunAdmission",
    "ConversationRunAttemptResult",
    "ConversationSubmissionResult",
    "HydratedRunEvent",
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
