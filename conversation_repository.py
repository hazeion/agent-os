"""Canonical SQLite authority for Conversation identity and safe messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import base64
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any, Iterable, Mapping

from agent_registry import (
    DIRECT_AGENT_ROLE,
    AgentRegistry,
    CanonicalAgentRecord,
)
from mentat_db import connect as connect_database


MAX_CONVERSATIONS = 1_024
MAX_MESSAGES = 10_000
MAX_TURNS = 10_000
MAX_TOTAL_MESSAGE_BYTES = 12 * 1024 * 1024
MAX_MESSAGE_PAGE = 100
MAX_CONVERSATION_PAGE = 50
MAX_ACTIVITY_CONVERSATIONS = 8
MAX_ACTIVE_TURNS = 8
MAX_TITLE_LENGTH = 160
MAX_USER_MESSAGE_LENGTH = 6_000
MAX_ASSISTANT_MESSAGE_LENGTH = 20_000
MAX_MESSAGE_CONTENT_BYTES = 64 * 1024
CONVERSATION_SCHEMA_VERSION = 1

_CONVERSATION_ID = re.compile(r"conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
_MESSAGE_ID = re.compile(r"msg_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
_TURN_ID = re.compile(r"turn_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CURSOR = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_BLOCKED_REASONS = frozenset({"capacity", "failed", "stopped", "interrupted", "unknown", "partial"})
_ACTIVE_RUN_STATUSES = frozenset(
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
_WAITING_RUN_STATUSES = frozenset(
    {"waiting", "waiting_for_approval", "waiting_for_clarification", "unknown"}
)
_REQUIRED_SCHEMA_OBJECTS = {
    ("index", "idx_mentat_conversations_activity"): """
        CREATE INDEX idx_mentat_conversations_activity
        ON mentat_conversations(state, updated_at DESC, id)
    """,
    ("index", "idx_mentat_conversations_agent_activity"): """
        CREATE INDEX idx_mentat_conversations_agent_activity
        ON mentat_conversations(agent_id, state, updated_at DESC, id)
    """,
    ("index", "idx_mentat_conversation_messages_page"): """
        CREATE INDEX idx_mentat_conversation_messages_page
        ON mentat_conversation_messages(conversation_id, sequence DESC, id)
    """,
    ("index", "idx_mentat_conversation_messages_run"): """
        CREATE INDEX idx_mentat_conversation_messages_run
        ON mentat_conversation_messages(run_id, conversation_id, sequence)
    """,
    ("index", "idx_mentat_conversation_turns_state"): """
        CREATE INDEX idx_mentat_conversation_turns_state
        ON mentat_conversation_turns(conversation_id, state, queue_ordinal)
    """,
    ("index", "idx_mentat_runs_one_active_conversation"): """
        CREATE UNIQUE INDEX idx_mentat_runs_one_active_conversation
        ON mentat_runs(conversation_id)
        WHERE conversation_id IS NOT NULL AND status IN (
            'reserved', 'queued', 'submitting', 'starting', 'running',
            'cancelling', 'waiting', 'waiting_for_approval',
            'waiting_for_clarification', 'unknown'
        )
    """,
    ("trigger", "mentat_conversations_agent_immutable"): """
        CREATE TRIGGER mentat_conversations_agent_immutable
        BEFORE UPDATE OF agent_id ON mentat_conversations
        WHEN OLD.agent_id IS NOT NEW.agent_id
        BEGIN
            SELECT RAISE(ABORT, 'conversation_agent_immutable');
        END
    """,
    ("trigger", "mentat_conversation_turns_queue_capacity_insert"): """
        CREATE TRIGGER mentat_conversation_turns_queue_capacity_insert
        BEFORE INSERT ON mentat_conversation_turns
        WHEN NEW.state IN ('pending', 'blocked', 'dispatching')
            AND (
                SELECT COUNT(*) FROM mentat_conversation_turns
                WHERE conversation_id = NEW.conversation_id
                  AND state IN ('pending', 'blocked', 'dispatching')
            ) >= 8
        BEGIN
            SELECT RAISE(ABORT, 'conversation_turn_capacity');
        END
    """,
    ("trigger", "mentat_conversation_turns_queue_capacity_update"): """
        CREATE TRIGGER mentat_conversation_turns_queue_capacity_update
        BEFORE UPDATE OF conversation_id, state ON mentat_conversation_turns
        WHEN NEW.state IN ('pending', 'blocked', 'dispatching')
            AND (
                SELECT COUNT(*) FROM mentat_conversation_turns
                WHERE conversation_id = NEW.conversation_id
                  AND state IN ('pending', 'blocked', 'dispatching')
                  AND id IS NOT OLD.id
            ) >= 8
        BEGIN
            SELECT RAISE(ABORT, 'conversation_turn_capacity');
        END
    """,
    ("trigger", "mentat_conversation_turns_conversation_immutable"): """
        CREATE TRIGGER mentat_conversation_turns_conversation_immutable
        BEFORE UPDATE OF conversation_id, user_message_id, queue_ordinal
            ON mentat_conversation_turns
        WHEN OLD.conversation_id IS NOT NEW.conversation_id
            OR OLD.user_message_id IS NOT NEW.user_message_id
            OR OLD.queue_ordinal IS NOT NEW.queue_ordinal
        BEGIN
            SELECT RAISE(ABORT, 'conversation_turn_identity_immutable');
        END
    """,
    ("trigger", "mentat_runs_conversation_identity_immutable"): """
        CREATE TRIGGER mentat_runs_conversation_identity_immutable
        BEFORE UPDATE OF conversation_id, turn_id, retry_of_run_id,
            resume_of_run_id, agent_revision, runtime_config_revision,
            execution_config_json, execution_config_digest,
            capacity_scope_digest, admitted_capacity_limit ON mentat_runs
        WHEN OLD.conversation_id IS NOT NEW.conversation_id
            OR OLD.turn_id IS NOT NEW.turn_id
            OR OLD.retry_of_run_id IS NOT NEW.retry_of_run_id
            OR OLD.resume_of_run_id IS NOT NEW.resume_of_run_id
            OR OLD.agent_revision IS NOT NEW.agent_revision
            OR OLD.runtime_config_revision IS NOT NEW.runtime_config_revision
            OR OLD.execution_config_json IS NOT NEW.execution_config_json
            OR OLD.execution_config_digest IS NOT NEW.execution_config_digest
            OR OLD.capacity_scope_digest IS NOT NEW.capacity_scope_digest
            OR OLD.admitted_capacity_limit IS NOT NEW.admitted_capacity_limit
        BEGIN
            SELECT RAISE(ABORT, 'conversation_run_identity_immutable');
        END
    """,
}


def _normalized_sql(value: object) -> str:
    return " ".join(str(value).split()).lower()


class ConversationRepositoryError(RuntimeError):
    """A bounded Conversation authority failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ConversationRepositoryUnavailable(ConversationRepositoryError):
    """The private database could not be opened or validated."""


class ConversationRepositoryValidationError(ConversationRepositoryError):
    """A Conversation request or persisted value is invalid."""


class ConversationRepositoryConflict(ConversationRepositoryError):
    """A Conversation request races or names missing authority."""


class ConversationRepositoryLimitError(ConversationRepositoryError):
    """A fixed Conversation or message bound has been reached."""


@dataclass(frozen=True)
class ConversationRecord:
    id: str
    agent_id: str
    title: str
    title_source: str
    state: str
    revision: int
    created_at: str
    updated_at: str
    archived_at: str | None


@dataclass(frozen=True)
class ConversationMessageRecord:
    id: str
    conversation_id: str
    sequence: int
    role: str
    state: str
    content: dict[str, Any]
    content_bytes: int
    run_id: str | None
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ConversationRead:
    conversation: ConversationRecord
    agent: CanonicalAgentRecord
    messages: tuple[ConversationMessageRecord, ...]
    next_message_cursor: str | None
    current_run: dict[str, Any] | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _text(value: object, *, label: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip() != value
        or "\x00" in value
        or len(value) > maximum
    ):
        raise ConversationRepositoryValidationError(
            f"conversation.{label}_invalid"
        )
    return value


def _identifier(value: object, pattern: re.Pattern[str], code: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ConversationRepositoryValidationError(code)
    return value


def _timestamp(value: object, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        raise ConversationRepositoryValidationError("conversation.timestamp_invalid")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ConversationRepositoryValidationError(
            "conversation.timestamp_invalid"
        ) from exc
    return value


def _content(text: object, *, role: str) -> tuple[dict[str, Any], int]:
    maximum = (
        MAX_USER_MESSAGE_LENGTH if role == "user" else MAX_ASSISTANT_MESSAGE_LENGTH
    )
    clean = _text(text, label="message", maximum=maximum)
    value = {
        "schema_version": CONVERSATION_SCHEMA_VERSION,
        "parts": [{"type": "text", "text": clean}],
    }
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_CONTENT_BYTES:
        raise ConversationRepositoryValidationError("conversation.message_too_large")
    return value, len(encoded)


def _encode_conversation_cursor(row: Mapping[str, object]) -> str:
    state_rank = 0 if row["state"] == "active" else 1
    raw = json.dumps(
        [state_rank, row["updated_at"], row["id"]],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_conversation_cursor(value: object) -> tuple[int, str, str]:
    if not isinstance(value, str) or _CURSOR.fullmatch(value) is None:
        raise ConversationRepositoryValidationError("conversation.cursor_invalid")
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConversationRepositoryValidationError("conversation.cursor_invalid") from exc
    if (
        not isinstance(decoded, list)
        or len(decoded) != 3
        or decoded[0] not in {0, 1}
        or not isinstance(decoded[1], str)
        or _timestamp(decoded[1]) is None
        or not isinstance(decoded[2], str)
        or _CONVERSATION_ID.fullmatch(decoded[2]) is None
    ):
        raise ConversationRepositoryValidationError("conversation.cursor_invalid")
    return int(decoded[0]), decoded[1], decoded[2]


def _decode_content(value: object, *, role: str, content_bytes: object) -> dict[str, Any]:
    if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_MESSAGE_CONTENT_BYTES:
        raise ConversationRepositoryValidationError("conversation.content_invalid")
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConversationRepositoryValidationError("conversation.content_invalid") from exc
    if (
        not isinstance(decoded, dict)
        or set(decoded) != {"parts", "schema_version"}
        or decoded["schema_version"] != CONVERSATION_SCHEMA_VERSION
        or not isinstance(decoded["parts"], list)
        or len(decoded["parts"]) != 1
        or not isinstance(decoded["parts"][0], dict)
        or set(decoded["parts"][0]) != {"text", "type"}
        or decoded["parts"][0]["type"] != "text"
    ):
        raise ConversationRepositoryValidationError("conversation.content_invalid")
    text = decoded["parts"][0]["text"]
    clean = _text(
        text,
        label="message",
        maximum=(
            MAX_USER_MESSAGE_LENGTH
            if role == "user"
            else MAX_ASSISTANT_MESSAGE_LENGTH
        ),
    )
    canonical, encoded_size = _content(clean, role=role)
    if type(content_bytes) is not int or content_bytes != encoded_size:
        raise ConversationRepositoryValidationError("conversation.content_invalid")
    if value != json.dumps(
        canonical,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ):
        raise ConversationRepositoryValidationError("conversation.content_invalid")
    return canonical


def _conversation_row(row: Mapping[str, object]) -> ConversationRecord:
    identifier = _identifier(
        row["id"], _CONVERSATION_ID, "conversation_id_invalid"
    )
    agent_id = _identifier(row["agent_id"], _AGENT_ID, "agent_id_invalid")
    title = _text(row["title"], label="title", maximum=MAX_TITLE_LENGTH)
    title_source = row["title_source"]
    state = row["state"]
    if title_source not in {"default", "first_prompt"} or state not in {
        "active",
        "archived",
    }:
        raise ConversationRepositoryValidationError("conversation.row_invalid")
    revision = row["revision"]
    if type(revision) is not int or revision < 1:
        raise ConversationRepositoryValidationError("conversation.row_invalid")
    created_at = _timestamp(row["created_at"])
    updated_at = _timestamp(row["updated_at"])
    archived_at = _timestamp(row["archived_at"], nullable=True)
    if state == "active" and archived_at is not None:
        raise ConversationRepositoryValidationError("conversation.row_invalid")
    if state == "archived" and archived_at is None:
        raise ConversationRepositoryValidationError("conversation.row_invalid")
    if created_at is None or updated_at is None:
        raise ConversationRepositoryValidationError("conversation.row_invalid")
    return ConversationRecord(
        id=identifier,
        agent_id=agent_id,
        title=title,
        title_source=str(title_source),
        state=str(state),
        revision=revision,
        created_at=created_at,
        updated_at=updated_at,
        archived_at=archived_at,
    )


def _message_row(row: Mapping[str, object]) -> ConversationMessageRecord:
    identifier = _identifier(row["id"], _MESSAGE_ID, "message_id_invalid")
    conversation_id = _identifier(
        row["conversation_id"], _CONVERSATION_ID, "conversation_id_invalid"
    )
    sequence = row["sequence"]
    if type(sequence) is not int or sequence < 1:
        raise ConversationRepositoryValidationError("conversation.message_invalid")
    role = row["role"]
    state = row["state"]
    if role not in {"user", "assistant"} or state not in {"accepted", "cancelled"}:
        raise ConversationRepositoryValidationError("conversation.message_invalid")
    content = _decode_content(
        row["content_json"], role=str(role), content_bytes=row["content_bytes"]
    )
    run_id = row["run_id"]
    if run_id is not None and (
        not isinstance(run_id, str)
        or not re.fullmatch(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z", run_id)
    ):
        raise ConversationRepositoryValidationError("conversation.message_invalid")
    revision = row["revision"]
    if type(revision) is not int or revision < 1:
        raise ConversationRepositoryValidationError("conversation.message_invalid")
    created_at = _timestamp(row["created_at"])
    updated_at = _timestamp(row["updated_at"])
    if created_at is None or updated_at is None:
        raise ConversationRepositoryValidationError("conversation.message_invalid")
    return ConversationMessageRecord(
        id=identifier,
        conversation_id=conversation_id,
        sequence=sequence,
        role=str(role),
        state=str(state),
        content=content,
        content_bytes=int(row["content_bytes"]),
        run_id=str(run_id) if run_id is not None else None,
        revision=revision,
        created_at=created_at,
        updated_at=updated_at,
    )


def _agent_public(record: CanonicalAgentRecord) -> dict[str, Any]:
    return {
        "id": record.agent.id,
        "name": record.agent.name,
        "runtime_type": record.agent.runtime_type,
        "system_role": record.system_role,
        "capabilities": sorted(record.agent.capabilities),
    }


def _conversation_public(record: ConversationRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "agent_id": record.agent_id,
        "title": record.title,
        "title_source": record.title_source,
        "state": record.state,
        "revision": record.revision,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "archived_at": record.archived_at,
    }


def _message_public(record: ConversationMessageRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "conversation_id": record.conversation_id,
        "sequence": record.sequence,
        "role": record.role,
        "state": record.state,
        "content": record.content,
        "run_id": record.run_id,
        "revision": record.revision,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _run_public(row: Mapping[str, object]) -> dict[str, Any]:
    run_id = row["id"]
    status = row["status"]
    if not isinstance(run_id, str) or not re.fullmatch(
        r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z", run_id
    ) or status not in _ACTIVE_RUN_STATUSES | {
        "completed",
        "failed",
        "cancelled",
        "stopped",
        "interrupted",
    }:
        raise ConversationRepositoryValidationError("conversation.run_invalid")
    updated_at = _timestamp(row["updated_at"])
    if updated_at is None or type(row["partial"]) is not int or row["partial"] not in {0, 1}:
        raise ConversationRepositoryValidationError("conversation.run_invalid")
    return {
        "id": run_id,
        "status": str(status),
        "partial": bool(row["partial"]),
        "updated_at": updated_at,
    }


def _agent_activity(
    record: CanonicalAgentRecord,
    rows: Iterable[Mapping[str, object]],
) -> dict[str, Any]:
    selected = list(rows)
    active = next(
        (row for row in selected if row["status"] in _ACTIVE_RUN_STATUSES), None
    )
    relevant = active or (selected[0] if selected else None)
    status = relevant["status"] if relevant is not None else None
    if status in _WAITING_RUN_STATUSES:
        state = "waiting"
    elif status in _ACTIVE_RUN_STATUSES:
        state = "working"
    elif status == "failed":
        state = "failed"
    elif status == "stopped":
        state = "stopped"
    elif status == "interrupted":
        state = "interrupted"
    else:
        state = "idle"
    conversations: list[dict[str, Any]] = []
    for row in selected:
        conversation_id = row["conversation_id"]
        if conversation_id is None:
            continue
        conversation_id = _identifier(
            conversation_id, _CONVERSATION_ID, "conversation_id_invalid"
        )
        title = _text(row["title"], label="title", maximum=MAX_TITLE_LENGTH)
        updated_at = _timestamp(row["updated_at"])
        if updated_at is None:
            raise ConversationRepositoryValidationError("conversation.activity_invalid")
        run_status = str(row["status"])
        conversations.append(
            {
                "id": conversation_id,
                "title": title,
                "run_id": str(row["id"]),
                "run_status": run_status,
                "attention": run_status in _WAITING_RUN_STATUSES
                or run_status in {"failed", "stopped", "interrupted"},
                "updated_at": updated_at,
            }
        )
        if len(conversations) >= MAX_ACTIVITY_CONVERSATIONS:
            break
    if relevant is None:
        summary = "Ready for work"
        updated_at = None
        attention = False
    elif relevant["conversation_id"] is not None:
        summary = _text(relevant["title"], label="title", maximum=MAX_TITLE_LENGTH)
        updated_at = _timestamp(relevant["updated_at"])
        attention = status in _WAITING_RUN_STATUSES or status in {
            "failed", "stopped", "interrupted"
        }
    elif status == "failed":
        summary = "Run needs review"
        updated_at = _timestamp(relevant["updated_at"])
        attention = True
    elif status in _WAITING_RUN_STATUSES:
        summary = "Run is waiting"
        updated_at = _timestamp(relevant["updated_at"])
        attention = True
    elif status in _ACTIVE_RUN_STATUSES:
        summary = "Run in progress"
        updated_at = _timestamp(relevant["updated_at"])
        attention = False
    else:
        summary = "Ready for work"
        updated_at = _timestamp(relevant["updated_at"])
        attention = False
    return {
        "agent": _agent_public(record),
        "state": state,
        "summary": summary,
        "attention": attention,
        "updated_at": updated_at,
        "conversations": conversations,
    }


def validate_repository_connection(connection: sqlite3.Connection) -> int:
    """Validate schema-10 Conversation rows and cross-row content bounds."""

    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required = {
            "mentat_conversations",
            "mentat_conversation_messages",
            "mentat_conversation_turns",
        }
        if not required.issubset(tables):
            raise ConversationRepositoryUnavailable("conversation.schema_unsupported")
        version = int(
            connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            or 0
        )
        if version != 10:
            raise ConversationRepositoryUnavailable("conversation.schema_unsupported")
        for (object_type, object_name), expected_sql in _REQUIRED_SCHEMA_OBJECTS.items():
            object_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
                (object_type, object_name),
            ).fetchone()
            if object_row is None or _normalized_sql(object_row["sql"]) != _normalized_sql(expected_sql):
                raise ConversationRepositoryUnavailable("conversation.schema_unsupported")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ConversationRepositoryError("conversation.corrupt")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ConversationRepositoryError("conversation.corrupt")
        conversation_count = int(
            connection.execute("SELECT COUNT(*) FROM mentat_conversations").fetchone()[0]
        )
        message_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM mentat_conversation_messages"
            ).fetchone()[0]
        )
        turn_count = int(
            connection.execute("SELECT COUNT(*) FROM mentat_conversation_turns").fetchone()[0]
        )
        if (
            conversation_count > MAX_CONVERSATIONS
            or message_count > MAX_MESSAGES
            or turn_count > MAX_TURNS
        ):
            raise ConversationRepositoryLimitError("conversation.capacity_exceeded")
        total_bytes = 0
        for row in connection.execute(
            "SELECT * FROM mentat_conversations ORDER BY id"
        ):
            conversation = _conversation_row(row)
            maximum_sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) FROM mentat_conversation_messages WHERE conversation_id = ?",
                    (conversation.id,),
                ).fetchone()[0]
            )
            next_sequence = int(row["next_message_sequence"])
            if next_sequence != maximum_sequence + 1:
                raise ConversationRepositoryError("conversation.sequence_invalid")
            message_rows = connection.execute(
                "SELECT * FROM mentat_conversation_messages WHERE conversation_id = ? ORDER BY sequence",
                (conversation.id,),
            ).fetchall()
            sequences = [int(message["sequence"]) for message in message_rows]
            if sequences != list(range(1, len(sequences) + 1)):
                raise ConversationRepositoryError("conversation.sequence_invalid")
            for message_row in message_rows:
                message = _message_row(message_row)
                if message.conversation_id != conversation.id:
                    raise ConversationRepositoryError("conversation.message_invalid")
                if message.run_id is not None:
                    run = connection.execute(
                        "SELECT conversation_id FROM mentat_runs WHERE id = ?",
                        (message.run_id,),
                    ).fetchone()
                    if run is None or run["conversation_id"] != conversation.id:
                        raise ConversationRepositoryError("conversation.message_invalid")
                total_bytes += message.content_bytes
                if total_bytes > MAX_TOTAL_MESSAGE_BYTES:
                    raise ConversationRepositoryLimitError("conversation.capacity_exceeded")
            for run_row in connection.execute(
                "SELECT agent_id FROM mentat_runs WHERE conversation_id = ?",
                (conversation.id,),
            ):
                if run_row["agent_id"] != conversation.agent_id:
                    raise ConversationRepositoryError("conversation.run_invalid")
            turn_rows = connection.execute(
                "SELECT * FROM mentat_conversation_turns WHERE conversation_id = ? ORDER BY queue_ordinal",
                (conversation.id,),
            ).fetchall()
            active_turns = sum(
                turn["state"] in {"pending", "blocked", "dispatching"}
                for turn in turn_rows
            )
            for turn in turn_rows:
                turn_id = _identifier(turn["id"], _TURN_ID, "turn_id_invalid")
                if turn["state"] not in {
                    "pending",
                    "dispatching",
                    "consumed",
                    "blocked",
                    "cancelled",
                }:
                    raise ConversationRepositoryError("conversation.turn_invalid")
                if (
                    type(turn["revision"]) is not int
                    or int(turn["revision"]) < 1
                    or type(turn["queue_ordinal"]) is not int
                    or int(turn["queue_ordinal"]) < 1
                    or type(turn["attempt_count"]) is not int
                    or int(turn["attempt_count"]) < 0
                ):
                    raise ConversationRepositoryError("conversation.turn_invalid")
                if not _SHA256.fullmatch(str(turn["idempotency_key_digest"])) or not _SHA256.fullmatch(
                    str(turn["request_digest"])
                ):
                    raise ConversationRepositoryError("conversation.turn_invalid")
                user_message_id = _identifier(
                    turn["user_message_id"], _MESSAGE_ID, "message_id_invalid"
                )
                user_message = connection.execute(
                    "SELECT conversation_id, role FROM mentat_conversation_messages WHERE id = ?",
                    (user_message_id,),
                ).fetchone()
                if (
                    user_message is None
                    or user_message["conversation_id"] != conversation.id
                    or user_message["role"] != "user"
                    or (turn["state"] == "blocked") != (turn["blocked_reason"] is not None)
                    or (
                        turn["blocked_reason"] is not None
                        and turn["blocked_reason"] not in _BLOCKED_REASONS
                    )
                ):
                    raise ConversationRepositoryError("conversation.turn_invalid")
                latest_run_id = turn["latest_run_id"]
                if latest_run_id is not None:
                    if not isinstance(latest_run_id, str) or not re.fullmatch(
                        r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z", latest_run_id
                    ):
                        raise ConversationRepositoryError("conversation.turn_invalid")
                    latest_run = connection.execute(
                        "SELECT conversation_id, turn_id FROM mentat_runs WHERE id = ?",
                        (latest_run_id,),
                    ).fetchone()
                    if (
                        latest_run is None
                        or latest_run["conversation_id"] != conversation.id
                        or latest_run["turn_id"] != turn_id
                    ):
                        raise ConversationRepositoryError("conversation.turn_invalid")
                if not turn_id:
                    raise ConversationRepositoryError("conversation.turn_invalid")
            maximum_turn_ordinal = int(
                connection.execute(
                    "SELECT COALESCE(MAX(queue_ordinal), 0) FROM mentat_conversation_turns WHERE conversation_id = ?",
                    (conversation.id,),
                ).fetchone()[0]
            )
            if int(row["next_turn_ordinal"]) != maximum_turn_ordinal + 1:
                raise ConversationRepositoryError("conversation.sequence_invalid")
            if active_turns > MAX_ACTIVE_TURNS:
                raise ConversationRepositoryLimitError("conversation.turn_capacity")
        return conversation_count
    except ConversationRepositoryError:
        raise
    except (sqlite3.Error, TypeError, ValueError, KeyError) as exc:
        raise ConversationRepositoryError("conversation.corrupt") from exc


class ConversationRepository:
    """Transaction-friendly repository over the migrated Mentat database."""

    def __init__(
        self,
        data_dir: Path,
        *,
        supported_runtime_types: Iterable[str] = ("codex", "hermes", "vercel"),
    ):
        self.data_dir = Path(data_dir)
        self.supported_runtime_types = frozenset(supported_runtime_types)

    def _registry(self) -> AgentRegistry:
        return AgentRegistry(
            self.data_dir,
            supported_runtime_types=self.supported_runtime_types,
        )

    def _bootstrap_agents(self) -> tuple[CanonicalAgentRecord, ...]:
        registry = self._registry()
        registry.ensure_direct_agent()
        return registry.list_agent_records()

    @staticmethod
    def _direct_agent_available(record: CanonicalAgentRecord) -> bool:
        if record.system_role != DIRECT_AGENT_ROLE:
            return True
        from codex_runtime import codex_binding_is_valid, find_codex_command

        return find_codex_command() is not None and codex_binding_is_valid(
            "default", record.agent.capabilities
        )

    def _connection(self) -> sqlite3.Connection:
        connection: sqlite3.Connection | None = None
        try:
            connection = connect_database(self.data_dir)
            connection.row_factory = sqlite3.Row
            validate_repository_connection(connection)
            return connection
        except ConversationRepositoryError:
            if connection is not None:
                connection.close()
            raise
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
            raise ConversationRepositoryUnavailable("conversation.unavailable") from exc

    def create(self, *, agent_id: str | None = None) -> ConversationRead:
        agents = self._bootstrap_agents()
        selected = agent_id
        if selected is None:
            direct = next(
                (
                    record
                    for record in agents
                    if record.system_role == DIRECT_AGENT_ROLE
                    and self._direct_agent_available(record)
                ),
                None,
            )
            if direct is None:
                raise ConversationRepositoryValidationError("conversation.agent_required")
            selected = direct.agent.id
        selected = _identifier(selected, _AGENT_ID, "agent_id_invalid")
        agent = next((record for record in agents if record.agent.id == selected), None)
        if agent is None:
            raise ConversationRepositoryConflict("conversation.agent_not_found")
        if not self._direct_agent_available(agent):
            raise ConversationRepositoryValidationError("conversation.agent_required")
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            count = int(
                connection.execute("SELECT COUNT(*) FROM mentat_conversations").fetchone()[0]
            )
            if count >= MAX_CONVERSATIONS:
                raise ConversationRepositoryLimitError("conversation.capacity_exceeded")
            now = _now()
            identifier = f"conv_{secrets.token_hex(12)}"
            connection.execute(
                """
                INSERT INTO mentat_conversations (
                    id, agent_id, title, title_source, state, revision,
                    next_message_sequence, next_turn_ordinal,
                    created_at, updated_at, archived_at
                ) VALUES (?, ?, 'New conversation', 'default', 'active', 1, 1, 1, ?, ?, NULL)
                """,
                (identifier, selected, now, now),
            )
            connection.commit()
            record = ConversationRecord(
                id=identifier,
                agent_id=selected,
                title="New conversation",
                title_source="default",
                state="active",
                revision=1,
                created_at=now,
                updated_at=now,
                archived_at=None,
            )
            return ConversationRead(record, agent, (), None, None)
        except ConversationRepositoryError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise ConversationRepositoryConflict("conversation.conflict") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise ConversationRepositoryUnavailable("conversation.unavailable") from exc
        finally:
            connection.close()

    def list_page(
        self,
        *,
        limit: int = MAX_CONVERSATION_PAGE,
        cursor: str | None = None,
    ) -> tuple[tuple[ConversationRecord, ...], str | None]:
        if type(limit) is not int or not 1 <= limit <= MAX_CONVERSATION_PAGE:
            raise ConversationRepositoryValidationError("conversation.limit_invalid")
        decoded_cursor = _decode_conversation_cursor(cursor) if cursor is not None else None
        self._bootstrap_agents()
        connection = self._connection()
        try:
            where = ""
            parameters: list[Any] = []
            if decoded_cursor is not None:
                rank, updated_at, identifier = decoded_cursor
                where = "WHERE (CASE state WHEN 'active' THEN 0 ELSE 1 END) > ? " \
                    "OR ((CASE state WHEN 'active' THEN 0 ELSE 1 END) = ? AND updated_at < ?) " \
                    "OR ((CASE state WHEN 'active' THEN 0 ELSE 1 END) = ? AND updated_at = ? AND id < ?)"
                parameters.extend([rank, rank, updated_at, rank, updated_at, identifier])
            rows = connection.execute(
                f"""
                SELECT * FROM mentat_conversations
                {where}
                ORDER BY CASE state WHEN 'active' THEN 0 ELSE 1 END,
                         updated_at DESC, id DESC
                LIMIT ?
                """,
                (*parameters, limit + 1),
            ).fetchall()
            page = tuple(_conversation_row(row) for row in rows[:limit])
            next_cursor = _encode_conversation_cursor(rows[limit - 1]) if len(rows) > limit else None
            return page, next_cursor
        finally:
            connection.close()

    def list(self, *, limit: int = MAX_CONVERSATION_PAGE) -> tuple[ConversationRecord, ...]:
        return self.list_page(limit=limit)[0]

    def read(
        self,
        conversation_id: str,
        *,
        before_sequence: int | None = None,
    ) -> ConversationRead:
        identifier = _identifier(
            conversation_id, _CONVERSATION_ID, "conversation_id_invalid"
        )
        agents = self._bootstrap_agents()
        connection = self._connection()
        try:
            row = connection.execute(
                "SELECT * FROM mentat_conversations WHERE id = ?", (identifier,)
            ).fetchone()
            if row is None:
                raise ConversationRepositoryConflict("conversation.not_found")
            conversation = _conversation_row(row)
            agent = next(
                (record for record in agents if record.agent.id == conversation.agent_id),
                None,
            )
            if agent is None:
                raise ConversationRepositoryError("conversation.agent_missing")
            parameters: list[Any] = [identifier]
            where = "conversation_id = ?"
            if before_sequence is not None:
                if type(before_sequence) is not int or not 1 <= before_sequence <= 10**9:
                    raise ConversationRepositoryValidationError(
                        "conversation.cursor_invalid"
                    )
                where += " AND sequence < ?"
                parameters.append(before_sequence)
            rows = connection.execute(
                f"SELECT * FROM mentat_conversation_messages WHERE {where} "
                "ORDER BY sequence DESC LIMIT ?",
                (*parameters, MAX_MESSAGE_PAGE + 1),
            ).fetchall()
            next_cursor = (
                str(rows[MAX_MESSAGE_PAGE - 1]["sequence"])
                if len(rows) > MAX_MESSAGE_PAGE
                else None
            )
            messages = tuple(
                _message_row(item) for item in reversed(rows[:MAX_MESSAGE_PAGE])
            )
            current = connection.execute(
                """
                SELECT id, status, partial, updated_at
                FROM mentat_runs
                WHERE conversation_id = ? AND agent_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (identifier, conversation.agent_id),
            ).fetchone()
            current_run = _run_public(current) if current is not None else None
            return ConversationRead(
                conversation,
                agent,
                messages,
                next_cursor,
                current_run,
            )
        finally:
            connection.close()

    def activity(self) -> tuple[dict[str, Any], ...]:
        agents = self._bootstrap_agents()
        connection = self._connection()
        try:
            result: list[dict[str, Any]] = []
            for agent in agents:
                rows = connection.execute(
                    """
                    SELECT r.id, r.conversation_id, r.status, r.partial, r.updated_at,
                           c.title
                    FROM mentat_runs AS r
                    LEFT JOIN mentat_conversations AS c ON c.id = r.conversation_id
                    WHERE r.agent_id = ?
                      AND (r.conversation_id IS NULL OR c.agent_id = r.agent_id)
                      AND r.status IN (
                          'reserved', 'queued', 'submitting', 'starting', 'running',
                          'cancelling', 'waiting', 'waiting_for_approval',
                          'waiting_for_clarification', 'unknown', 'failed', 'completed',
                          'stopped', 'interrupted'
                      )
                    ORDER BY CASE
                        WHEN r.status IN (
                            'reserved', 'queued', 'submitting', 'starting', 'running',
                            'cancelling', 'waiting', 'waiting_for_approval',
                            'waiting_for_clarification', 'unknown'
                        ) THEN 0
                        WHEN r.status = 'failed' THEN 1
                        WHEN r.status IN ('stopped', 'interrupted') THEN 2
                        ELSE 3
                    END, r.updated_at DESC, r.id DESC
                    LIMIT ?
                    """,
                    (agent.agent.id, MAX_ACTIVITY_CONVERSATIONS),
                ).fetchall()
                result.append(_agent_activity(agent, rows))
            return tuple(result)
        finally:
            connection.close()

    def append_message_for_test(
        self,
        conversation_id: str,
        *,
        role: str,
        text: str,
        run_id: str | None = None,
    ) -> ConversationMessageRecord:
        """Append a validated message for repository/backup tests and projections."""

        identifier = _identifier(
            conversation_id, _CONVERSATION_ID, "conversation_id_invalid"
        )
        if role not in {"user", "assistant"}:
            raise ConversationRepositoryValidationError("conversation.role_invalid")
        content, content_bytes = _content(text, role=role)
        if run_id is not None and _identifier(
            run_id,
            re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z"),
            "run_id_invalid",
        ) != run_id:
            raise ConversationRepositoryValidationError("run_id_invalid")
        connection = self._connection()
        try:
            connection.execute("BEGIN IMMEDIATE")
            total = int(
                connection.execute(
                    "SELECT COALESCE(SUM(content_bytes), 0) FROM mentat_conversation_messages"
                ).fetchone()[0]
            )
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM mentat_conversation_messages"
                ).fetchone()[0]
            )
            if count >= MAX_MESSAGES or total + content_bytes > MAX_TOTAL_MESSAGE_BYTES:
                raise ConversationRepositoryLimitError("conversation.capacity_exceeded")
            conversation = connection.execute(
                "SELECT * FROM mentat_conversations WHERE id = ?", (identifier,)
            ).fetchone()
            if conversation is None:
                raise ConversationRepositoryConflict("conversation.not_found")
            sequence = int(conversation["next_message_sequence"])
            now = _now()
            message_id = f"msg_{secrets.token_hex(12)}"
            encoded = json.dumps(
                content,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            connection.execute(
                """
                INSERT INTO mentat_conversation_messages (
                    id, conversation_id, sequence, role, state, content_json,
                    content_bytes, run_id, revision, source_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'accepted', ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    message_id,
                    identifier,
                    sequence,
                    role,
                    encoded,
                    content_bytes,
                    run_id,
                    f"console:test:{message_id}",
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE mentat_conversations
                SET next_message_sequence = ?, updated_at = ?
                WHERE id = ?
                """,
                (sequence + 1, now, identifier),
            )
            connection.commit()
            return ConversationMessageRecord(
                id=message_id,
                conversation_id=identifier,
                sequence=sequence,
                role=role,
                state="accepted",
                content=content,
                content_bytes=content_bytes,
                run_id=run_id,
                revision=1,
                created_at=now,
                updated_at=now,
            )
        except ConversationRepositoryError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise ConversationRepositoryConflict("conversation.message_conflict") from exc
        finally:
            connection.close()

    def append_message(self, conversation_id: str, *, role: str, text: str, run_id: str | None = None) -> ConversationMessageRecord:
        """Append one validated transcript Message for the next write slice."""

        return self.append_message_for_test(
            conversation_id, role=role, text=text, run_id=run_id
        )


def conversation_public(record: ConversationRead) -> dict[str, Any]:
    return {
        "schema_version": CONVERSATION_SCHEMA_VERSION,
        "conversation": _conversation_public(record.conversation),
        "agent": _agent_public(record.agent),
        "messages": [_message_public(message) for message in record.messages],
        "next_message_cursor": record.next_message_cursor,
        "current_run": record.current_run,
    }


def conversations_public(
    repository: ConversationRepository,
    *,
    limit: int = MAX_CONVERSATION_PAGE,
    cursor: str | None = None,
) -> dict[str, Any]:
    records, next_cursor = repository.list_page(limit=limit, cursor=cursor)
    agents = repository._bootstrap_agents()
    direct = next(
        (
            record.agent.id
            for record in agents
            if record.system_role == DIRECT_AGENT_ROLE
            and repository._direct_agent_available(record)
        ),
        None,
    )
    return {
        "schema_version": CONVERSATION_SCHEMA_VERSION,
        "conversations": [_conversation_public(record) for record in records],
        "agents": [_agent_public(record) for record in agents],
        "direct_agent_id": direct,
        "count": len(records),
        "next_cursor": next_cursor,
    }


def activity_public(repository: ConversationRepository) -> dict[str, Any]:
    agents = repository._bootstrap_agents()
    direct = next(
        (
            record.agent.id
            for record in agents
            if record.system_role == DIRECT_AGENT_ROLE
            and repository._direct_agent_available(record)
        ),
        None,
    )
    return {
        "schema_version": CONVERSATION_SCHEMA_VERSION,
        "activity": list(repository.activity()),
        "direct_agent_id": direct,
    }


__all__ = [
    "CONVERSATION_SCHEMA_VERSION",
    "ConversationMessageRecord",
    "ConversationRead",
    "ConversationRecord",
    "ConversationRepository",
    "ConversationRepositoryConflict",
    "ConversationRepositoryError",
    "ConversationRepositoryLimitError",
    "ConversationRepositoryUnavailable",
    "ConversationRepositoryValidationError",
    "MAX_ASSISTANT_MESSAGE_LENGTH",
    "MAX_CONVERSATIONS",
    "MAX_MESSAGE_PAGE",
    "MAX_MESSAGES",
    "MAX_TOTAL_MESSAGE_BYTES",
    "MAX_USER_MESSAGE_LENGTH",
    "activity_public",
    "conversation_public",
    "conversations_public",
    "validate_repository_connection",
]
