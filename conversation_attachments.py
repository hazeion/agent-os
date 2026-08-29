"""Conversation-owned staging and retained media over Mentat attachments."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import BinaryIO, Iterable, Mapping, Sequence

from agent_console_attachments import (
    AVAILABLE_STATES,
    AttachmentError,
    AttachmentNotFound,
    AttachmentUnavailable,
    AttachmentValidationError,
    create_attachment,
    get_attachment,
    open_attachment_stream,
    release_attachment,
)
from mentat_db import connect, transaction
from private_state import synchronized_private_state


MAX_STAGED_ATTACHMENTS = 8
MAX_DIRECT_ATTACHMENTS = 5
MAX_STAGED_IMAGES = 1
MAX_MEDIA_RUNS = 50
MAX_RUN_INPUTS = 8
MAX_RUN_OUTPUTS = 20

_CONVERSATION_ID = re.compile(r"conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
_ATTACHMENT_ID = re.compile(r"attachment_[0-9a-f]{32}\Z")
_RUN_ID = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z")
_PACK_ID = re.compile(r"pack_[0-9a-f]{16}\Z")
_PACK_REVISION = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SOURCE_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SOURCES = frozenset({"upload", "workspace", "context_pack"})


class ConversationAttachmentError(RuntimeError):
    """A bounded Conversation attachment failure."""

    def __init__(self, code: str):
        safe = code if re.fullmatch(r"conversation_context\.[a-z0-9_]+", code) else "conversation_context.unavailable"
        super().__init__(safe)
        self.code = safe


def _conversation_id(value: str) -> str:
    if not isinstance(value, str) or _CONVERSATION_ID.fullmatch(value) is None:
        raise ConversationAttachmentError("conversation_context.invalid")
    return value


def _attachment_id(value: str) -> str:
    if not isinstance(value, str) or _ATTACHMENT_ID.fullmatch(value) is None:
        raise ConversationAttachmentError("conversation_context.attachment_not_found")
    return value


def _run_id(value: str) -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise ConversationAttachmentError("conversation_context.invalid")
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_pack(
    pack_id: str | None,
    pack_revision: str | None,
    pack_name: str | None,
) -> dict[str, str] | None:
    if pack_id is None and pack_revision is None and pack_name is None:
        return None
    if (
        not isinstance(pack_id, str)
        or _PACK_ID.fullmatch(pack_id) is None
        or not isinstance(pack_revision, str)
        or _PACK_REVISION.fullmatch(pack_revision) is None
        or not isinstance(pack_name, str)
        or not pack_name
        or pack_name.strip() != pack_name
        or len(pack_name) > 80
        or "\x00" in pack_name
    ):
        raise ConversationAttachmentError("conversation_context.pack_invalid")
    return {"id": pack_id, "name": pack_name, "revision": pack_revision}


def _source_digests(value: object) -> tuple[str, ...]:
    try:
        decoded = json.loads(value) if isinstance(value, str) else list(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ConversationAttachmentError("conversation_context.pack_invalid") from exc
    if (
        not isinstance(decoded, list)
        or len(decoded) > MAX_STAGED_ATTACHMENTS
        or any(
            not isinstance(item, str) or _SOURCE_DIGEST.fullmatch(item) is None
            for item in decoded
        )
    ):
        raise ConversationAttachmentError("conversation_context.pack_invalid")
    return tuple(decoded)


def _available(row: sqlite3.Row) -> bool:
    state = str(row["state"])
    if state == "staged" and (
        row["expires_at"] is None or float(row["expires_at"]) <= time.time()
    ):
        return False
    return state in AVAILABLE_STATES and str(row["blob_state"] or "") == "ready"


def _media_item(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "name": str(row["original_name"]),
        "mime_type": str(row["mime_type"]),
        "kind": str(row["kind"]),
        "byte_size": int(row["byte_size"]),
        "state": str(row["state"]),
        "available": _available(row),
        "created_at": _iso_epoch(row["created_at"]),
        "expires_at": _iso_epoch(row["expires_at"]),
    }


def _staged_item(row: sqlite3.Row) -> dict[str, object]:
    return {
        **_media_item(row),
        "source": str(row["source"]),
        "ordinal": int(row["ordinal"]),
    }


def _iso_epoch(value: object) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat().replace("+00:00", "Z")


def _require_active_idle_conversation(connection: sqlite3.Connection, conversation_id: str) -> None:
    row = connection.execute(
        "SELECT state FROM mentat_conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if row is None:
        raise ConversationAttachmentError("conversation_context.conversation_not_found")
    if str(row["state"]) != "active":
        raise ConversationAttachmentError("conversation_context.conversation_not_active")
    busy = connection.execute(
        "SELECT 1 FROM mentat_runs AS r WHERE r.conversation_id = ? AND ("
        "r.status IN ('reserved','queued','submitting','starting','running',"
        "'cancelling','waiting','waiting_for_approval','waiting_for_clarification','unknown') "
        "OR (r.runtime_type = 'hermes' AND r.status IN "
        "('completed','failed','cancelled','stopped','interrupted') "
        "AND r.terminal_finalized = 0)) LIMIT 1",
        (conversation_id,),
    ).fetchone()
    queued = connection.execute(
        "SELECT 1 FROM mentat_conversation_turns WHERE conversation_id = ? "
        "AND state IN ('pending','blocked','dispatching') LIMIT 1",
        (conversation_id,),
    ).fetchone()
    if busy is not None or queued is not None:
        raise ConversationAttachmentError("conversation_context.requires_idle")


def _projection(connection: sqlite3.Connection, conversation_id: str) -> dict[str, object]:
    conversation = connection.execute(
        "SELECT 1 FROM mentat_conversations WHERE id = ?",
        (conversation_id,),
    ).fetchone()
    if conversation is None:
        raise ConversationAttachmentError("conversation_context.conversation_not_found")
    rows = connection.execute(
        "SELECT a.*, b.state AS blob_state, s.source, s.ordinal "
        "FROM mentat_conversation_staged_attachments AS s "
        "JOIN attachments AS a ON a.id = s.attachment_id "
        "LEFT JOIN blobs AS b ON b.id = a.blob_id "
        "WHERE s.conversation_id = ? ORDER BY s.ordinal, a.id",
        (conversation_id,),
    ).fetchall()
    context = connection.execute(
        "SELECT * FROM mentat_conversation_staged_contexts WHERE conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    pack = None if context is None else _safe_pack(
        context["context_pack_id"],
        context["context_pack_revision"],
        context["context_pack_name"],
    )
    return {
        "schema_version": 1,
        "conversation_id": conversation_id,
        "attachments": [_staged_item(row) for row in rows],
        "context_pack": pack,
        "limits": {
            "direct": MAX_DIRECT_ATTACHMENTS,
            "total": MAX_STAGED_ATTACHMENTS,
            "images": MAX_STAGED_IMAGES,
        },
    }


@synchronized_private_state
def conversation_staged_context(data_dir: Path, conversation_id: str) -> dict[str, object]:
    identifier = _conversation_id(conversation_id)
    connection = connect(data_dir)
    try:
        return _projection(connection, identifier)
    finally:
        connection.close()


def _next_ordinal(connection: sqlite3.Connection, conversation_id: str) -> int:
    used = {
        int(row[0])
        for row in connection.execute(
            "SELECT ordinal FROM mentat_conversation_staged_attachments WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
    }
    for ordinal in range(MAX_STAGED_ATTACHMENTS):
        if ordinal not in used:
            return ordinal
    raise ConversationAttachmentError("conversation_context.capacity")


@synchronized_private_state
def associate_staged_attachment(
    data_dir: Path,
    conversation_id: str,
    attachment_id: str,
    *,
    source: str,
) -> dict[str, object]:
    conversation = _conversation_id(conversation_id)
    attachment = _attachment_id(attachment_id)
    if source not in _SOURCES:
        raise ConversationAttachmentError("conversation_context.invalid")
    connection = connect(data_dir)
    try:
        with transaction(connection, immediate=True):
            _require_active_idle_conversation(connection, conversation)
            row = connection.execute(
                "SELECT a.*, b.state AS blob_state FROM attachments AS a "
                "LEFT JOIN blobs AS b ON b.id = a.blob_id WHERE a.id = ?",
                (attachment,),
            ).fetchone()
            if row is None:
                raise ConversationAttachmentError("conversation_context.attachment_not_found")
            if str(row["state"]) != "staged" or not _available(row):
                raise ConversationAttachmentError("conversation_context.attachment_unavailable")
            if row["expires_at"] is None or float(row["expires_at"]) <= time.time():
                raise ConversationAttachmentError("conversation_context.attachment_unavailable")
            try:
                connection.execute(
                    "INSERT INTO mentat_conversation_staged_attachments "
                    "(conversation_id, attachment_id, source, ordinal, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (conversation, attachment, source, _next_ordinal(connection, conversation), _now_iso()),
                )
            except sqlite3.IntegrityError as exc:
                existing = connection.execute(
                    "SELECT conversation_id FROM mentat_conversation_staged_attachments "
                    "WHERE attachment_id = ?",
                    (attachment,),
                ).fetchone()
                if existing is not None and str(existing["conversation_id"]) == conversation:
                    return _projection(connection, conversation)
                raise ConversationAttachmentError("conversation_context.capacity") from exc
        return _projection(connection, conversation)
    finally:
        connection.close()


def stage_uploaded_attachment(
    data_dir: Path,
    conversation_id: str,
    *,
    original_name: str,
    content: bytes | None = None,
    stream: BinaryIO | None = None,
    content_type: str | None = None,
) -> dict[str, object]:
    metadata = create_attachment(
        data_dir,
        original_name=original_name,
        content=content,
        stream=stream,
        content_type=content_type,
    )
    try:
        return associate_staged_attachment(
            data_dir,
            conversation_id,
            str(metadata["id"]),
            source="upload",
        )
    except Exception:
        try:
            release_attachment(data_dir, str(metadata["id"]))
        except AttachmentError:
            pass
        raise


@synchronized_private_state
def release_staged_attachment(
    data_dir: Path,
    conversation_id: str,
    attachment_id: str,
) -> dict[str, object]:
    conversation = _conversation_id(conversation_id)
    attachment = _attachment_id(attachment_id)
    connection = connect(data_dir)
    released_ids: tuple[str, ...] = ()
    try:
        with transaction(connection, immediate=True):
            _require_active_idle_conversation(connection, conversation)
            row = connection.execute(
                "SELECT source FROM mentat_conversation_staged_attachments "
                "WHERE conversation_id = ? AND attachment_id = ?",
                (conversation, attachment),
            ).fetchone()
            if row is None:
                raise ConversationAttachmentError("conversation_context.attachment_not_found")
            if str(row["source"]) == "context_pack":
                released_ids = tuple(
                    str(item[0])
                    for item in connection.execute(
                        "SELECT attachment_id FROM mentat_conversation_staged_attachments "
                        "WHERE conversation_id = ? AND source = 'context_pack'",
                        (conversation,),
                    ).fetchall()
                )
                connection.execute(
                    "DELETE FROM mentat_conversation_staged_contexts WHERE conversation_id = ?",
                    (conversation,),
                )
            else:
                released_ids = (attachment,)
                connection.execute(
                    "DELETE FROM mentat_conversation_staged_attachments "
                    "WHERE conversation_id = ? AND attachment_id = ?",
                    (conversation, attachment),
                )
        for released in released_ids:
            try:
                release_attachment(data_dir, released)
            except AttachmentUnavailable as exc:
                raise ConversationAttachmentError("conversation_context.attachment_unavailable") from exc
        return _projection(connection, conversation)
    finally:
        connection.close()


@synchronized_private_state
def clear_staged_context_pack(
    data_dir: Path,
    conversation_id: str,
) -> dict[str, object]:
    """Clear the exact staged Context Pack, including an instructions-only pack."""

    conversation = _conversation_id(conversation_id)
    connection = connect(data_dir)
    released_ids: tuple[str, ...] = ()
    try:
        with transaction(connection, immediate=True):
            _require_active_idle_conversation(connection, conversation)
            row = connection.execute(
                "SELECT 1 FROM mentat_conversation_staged_contexts "
                "WHERE conversation_id = ?",
                (conversation,),
            ).fetchone()
            if row is None:
                raise ConversationAttachmentError("conversation_context.pack_not_found")
            released_ids = tuple(
                str(item[0])
                for item in connection.execute(
                    "SELECT attachment_id FROM mentat_conversation_staged_attachments "
                    "WHERE conversation_id = ? AND source = 'context_pack'",
                    (conversation,),
                ).fetchall()
            )
            connection.execute(
                "DELETE FROM mentat_conversation_staged_contexts WHERE conversation_id = ?",
                (conversation,),
            )
        for released in released_ids:
            try:
                release_attachment(data_dir, released)
            except AttachmentUnavailable as exc:
                raise ConversationAttachmentError(
                    "conversation_context.attachment_unavailable"
                ) from exc
        return _projection(connection, conversation)
    finally:
        connection.close()


@synchronized_private_state
def replace_context_pack_stage(
    data_dir: Path,
    conversation_id: str,
    *,
    pack_id: str,
    pack_revision: str,
    pack_name: str,
    attachment_ids: Sequence[str],
    source_digests: Sequence[str],
) -> dict[str, object]:
    conversation = _conversation_id(conversation_id)
    pack = _safe_pack(pack_id, pack_revision, pack_name)
    if pack is None or len(attachment_ids) > MAX_STAGED_ATTACHMENTS:
        raise ConversationAttachmentError("conversation_context.pack_invalid")
    attachments = tuple(_attachment_id(value) for value in attachment_ids)
    digests = _source_digests(source_digests)
    if len(set(attachments)) != len(attachments) or len(digests) != len(attachments):
        raise ConversationAttachmentError("conversation_context.pack_invalid")
    connection = connect(data_dir)
    prior_ids: tuple[str, ...] = ()
    try:
        with transaction(connection, immediate=True):
            _require_active_idle_conversation(connection, conversation)
            prior_ids = tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT attachment_id FROM mentat_conversation_staged_attachments "
                    "WHERE conversation_id = ? AND source = 'context_pack'",
                    (conversation,),
                ).fetchall()
            )
            connection.execute(
                "DELETE FROM mentat_conversation_staged_contexts WHERE conversation_id = ?",
                (conversation,),
            )
            now = _now_iso()
            connection.execute(
                "INSERT INTO mentat_conversation_staged_contexts "
                "(conversation_id, context_pack_id, context_pack_revision, context_pack_name, "
                "context_pack_source_digests_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    conversation,
                    pack["id"],
                    pack["revision"],
                    pack["name"],
                    json.dumps(digests, ensure_ascii=True, separators=(",", ":")),
                    now,
                    now,
                ),
            )
            for attachment in attachments:
                row = connection.execute(
                    "SELECT a.*, b.state AS blob_state FROM attachments AS a "
                    "LEFT JOIN blobs AS b ON b.id = a.blob_id WHERE a.id = ?",
                    (attachment,),
                ).fetchone()
                if row is None or str(row["state"]) != "staged" or not _available(row):
                    raise ConversationAttachmentError("conversation_context.attachment_unavailable")
                connection.execute(
                    "INSERT INTO mentat_conversation_staged_attachments "
                    "(conversation_id, attachment_id, source, ordinal, created_at) "
                    "VALUES (?, ?, 'context_pack', ?, ?)",
                    (conversation, attachment, _next_ordinal(connection, conversation), now),
                )
        for attachment in prior_ids:
            if attachment not in attachments:
                try:
                    release_attachment(data_dir, attachment)
                except AttachmentError:
                    pass
        return _projection(connection, conversation)
    finally:
        connection.close()


def _context_digest(
    attachment_ids: Iterable[str],
    pack: Mapping[str, str] | None,
    source_digests: Iterable[str] = (),
) -> str:
    payload = {
        "attachment_ids": list(attachment_ids),
        "context_pack": None if pack is None else {
            "id": pack["id"],
            "revision": pack["revision"],
        },
        "context_pack_source_digests": list(source_digests),
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def staged_context_evidence(
    connection: sqlite3.Connection,
    conversation_id: str,
) -> dict[str, object] | None:
    conversation = _conversation_id(conversation_id)
    rows = connection.execute(
        "SELECT attachment_id FROM mentat_conversation_staged_attachments "
        "WHERE conversation_id = ? ORDER BY ordinal, attachment_id",
        (conversation,),
    ).fetchall()
    context = connection.execute(
        "SELECT * FROM mentat_conversation_staged_contexts WHERE conversation_id = ?",
        (conversation,),
    ).fetchone()
    pack = None if context is None else _safe_pack(
        context["context_pack_id"], context["context_pack_revision"], context["context_pack_name"]
    )
    source_digests = () if context is None else _source_digests(
        context["context_pack_source_digests_json"]
    )
    attachment_ids = tuple(str(row["attachment_id"]) for row in rows)
    if not attachment_ids and pack is None:
        return None
    return {
        "attachment_ids": attachment_ids,
        "context_pack": pack,
        "context_pack_source_digests": source_digests,
        "context_digest": _context_digest(attachment_ids, pack, source_digests),
    }


def bind_staged_context_to_run(
    connection: sqlite3.Connection,
    conversation_id: str,
    run_id: str,
    *,
    occurred_at: str,
) -> dict[str, object] | None:
    evidence = staged_context_evidence(connection, conversation_id)
    if evidence is None:
        return None
    run = connection.execute(
        "SELECT conversation_id FROM mentat_runs WHERE id = ?",
        (_run_id(run_id),),
    ).fetchone()
    if run is None or str(run["conversation_id"] or "") != conversation_id:
        raise ConversationAttachmentError("conversation_context.run_changed")
    now_epoch = time.time()
    for ordinal, attachment in enumerate(evidence["attachment_ids"]):
        row = connection.execute(
            "SELECT a.*, b.state AS blob_state FROM attachments AS a "
            "LEFT JOIN blobs AS b ON b.id = a.blob_id WHERE a.id = ?",
            (attachment,),
        ).fetchone()
        if (
            row is None
            or str(row["state"]) != "staged"
            or not _available(row)
            or row["expires_at"] is None
            or float(row["expires_at"]) <= now_epoch
        ):
            raise ConversationAttachmentError("conversation_context.attachment_unavailable")
        connection.execute(
            "INSERT INTO run_attachments(run_id, attachment_id, direction, ordinal, created_at) "
            "VALUES (?, ?, 'input', ?, ?)",
            (run_id, attachment, ordinal, now_epoch),
        )
        connection.execute(
            "UPDATE attachments SET state = 'attached', updated_at = ?, expires_at = NULL, delete_after = NULL "
            "WHERE id = ? AND state = 'staged'",
            (now_epoch, attachment),
        )
    pack = evidence["context_pack"]
    connection.execute(
        "INSERT INTO mentat_conversation_run_contexts "
        "(run_id, context_digest, context_pack_id, context_pack_revision, context_pack_name, "
        "context_pack_source_digests_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            evidence["context_digest"],
            None if pack is None else pack["id"],
            None if pack is None else pack["revision"],
            None if pack is None else pack["name"],
            None if pack is None else json.dumps(
                evidence["context_pack_source_digests"],
                ensure_ascii=True,
                separators=(",", ":"),
            ),
            occurred_at,
        ),
    )
    connection.execute(
        "DELETE FROM mentat_conversation_staged_contexts WHERE conversation_id = ?",
        (conversation_id,),
    )
    connection.execute(
        "DELETE FROM mentat_conversation_staged_attachments WHERE conversation_id = ?",
        (conversation_id,),
    )
    return evidence


def copy_run_input_context(
    connection: sqlite3.Connection,
    source_run_id: str,
    target_run_id: str,
    *,
    occurred_at: str,
) -> dict[str, object] | None:
    source = _run_id(source_run_id)
    target = _run_id(target_run_id)
    context = connection.execute(
        "SELECT * FROM mentat_conversation_run_contexts WHERE run_id = ?",
        (source,),
    ).fetchone()
    rows = connection.execute(
        "SELECT r.attachment_id, r.ordinal, a.state, b.state AS blob_state "
        "FROM run_attachments AS r JOIN attachments AS a ON a.id = r.attachment_id "
        "LEFT JOIN blobs AS b ON b.id = a.blob_id "
        "WHERE r.run_id = ? AND r.direction = 'input' ORDER BY r.ordinal, r.attachment_id",
        (source,),
    ).fetchall()
    if context is None and not rows:
        return None
    if context is None:
        raise ConversationAttachmentError("conversation_context.run_changed")
    for row in rows:
        if str(row["state"]) != "attached" or str(row["blob_state"] or "") != "ready":
            raise ConversationAttachmentError("conversation_context.attachment_unavailable")
        connection.execute(
            "INSERT INTO run_attachments(run_id, attachment_id, direction, ordinal, created_at) "
            "VALUES (?, ?, 'input', ?, ?)",
            (target, row["attachment_id"], int(row["ordinal"]), time.time()),
        )
    connection.execute(
        "INSERT INTO mentat_conversation_run_contexts "
        "(run_id, context_digest, context_pack_id, context_pack_revision, context_pack_name, "
        "context_pack_source_digests_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            target,
            context["context_digest"],
            context["context_pack_id"],
            context["context_pack_revision"],
            context["context_pack_name"],
            context["context_pack_source_digests_json"],
            occurred_at,
        ),
    )
    pack = _safe_pack(context["context_pack_id"], context["context_pack_revision"], context["context_pack_name"])
    attachment_ids = tuple(str(row["attachment_id"]) for row in rows)
    return {
        "attachment_ids": attachment_ids,
        "context_pack": pack,
        "context_pack_source_digests": (
            () if pack is None else _source_digests(
                context["context_pack_source_digests_json"]
            )
        ),
        "context_digest": str(context["context_digest"]),
    }


@synchronized_private_state
def run_input_context(data_dir: Path, run_id: str) -> dict[str, object] | None:
    identifier = _run_id(run_id)
    connection = connect(data_dir)
    try:
        context = connection.execute(
            "SELECT * FROM mentat_conversation_run_contexts WHERE run_id = ?",
            (identifier,),
        ).fetchone()
        rows = connection.execute(
            "SELECT attachment_id FROM run_attachments WHERE run_id = ? "
            "AND direction = 'input' ORDER BY ordinal, attachment_id",
            (identifier,),
        ).fetchall()
        if context is None and not rows:
            return None
        if context is None:
            raise ConversationAttachmentError("conversation_context.run_changed")
        return {
            "attachment_ids": tuple(str(row["attachment_id"]) for row in rows),
            "context_pack": _safe_pack(
                context["context_pack_id"], context["context_pack_revision"], context["context_pack_name"]
            ),
            "context_pack_source_digests": (
                () if context["context_pack_id"] is None else _source_digests(
                    context["context_pack_source_digests_json"]
                )
            ),
            "context_digest": str(context["context_digest"]),
        }
    finally:
        connection.close()


@synchronized_private_state
def conversation_media(data_dir: Path, conversation_id: str) -> dict[str, object]:
    conversation = _conversation_id(conversation_id)
    connection = connect(data_dir)
    try:
        exists = connection.execute(
            "SELECT 1 FROM mentat_conversations WHERE id = ?",
            (conversation,),
        ).fetchone()
        if exists is None:
            raise ConversationAttachmentError("conversation_context.conversation_not_found")
        runs = list(connection.execute(
            "SELECT id, created_at FROM mentat_runs WHERE conversation_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (conversation, MAX_MEDIA_RUNS),
        ).fetchall())
        runs.reverse()
        projected: list[dict[str, object]] = []
        for run in runs:
            rows = connection.execute(
                "SELECT a.*, b.state AS blob_state, r.direction, r.ordinal "
                "FROM run_attachments AS r JOIN attachments AS a ON a.id = r.attachment_id "
                "LEFT JOIN blobs AS b ON b.id = a.blob_id "
                "WHERE r.run_id = ? ORDER BY r.direction, r.ordinal, a.id",
                (run["id"],),
            ).fetchall()
            inputs = [_media_item(row) for row in rows if row["direction"] == "input"][:MAX_RUN_INPUTS]
            outputs = [_media_item(row) for row in rows if row["direction"] == "output"][:MAX_RUN_OUTPUTS]
            if inputs or outputs:
                projected.append({
                    "run_id": str(run["id"]),
                    "created_at": str(run["created_at"]),
                    "inputs": inputs,
                    "outputs": outputs,
                })
        return {"schema_version": 1, "conversation_id": conversation, "runs": projected}
    finally:
        connection.close()


@synchronized_private_state
def open_conversation_attachment_stream(
    data_dir: Path,
    conversation_id: str,
    attachment_id: str,
) -> tuple[dict, BinaryIO]:
    conversation = _conversation_id(conversation_id)
    attachment = _attachment_id(attachment_id)
    connection = connect(data_dir)
    try:
        authorized = connection.execute(
            "SELECT 1 FROM mentat_conversation_staged_attachments AS s "
            "JOIN attachments AS a ON a.id = s.attachment_id "
            "JOIN blobs AS b ON b.id = a.blob_id "
            "WHERE s.conversation_id = ? AND s.attachment_id = ? "
            "AND a.state = 'staged' AND a.expires_at IS NOT NULL "
            "AND a.expires_at > ? AND b.state = 'ready' "
            "UNION ALL "
            "SELECT 1 FROM run_attachments AS ra JOIN mentat_runs AS r ON r.id = ra.run_id "
            "WHERE r.conversation_id = ? AND ra.attachment_id = ? LIMIT 1",
            (conversation, attachment, time.time(), conversation, attachment),
        ).fetchone()
        if authorized is None:
            raise ConversationAttachmentError("conversation_context.attachment_not_found")
    finally:
        connection.close()
    try:
        return open_attachment_stream(data_dir, attachment, allowed_states={"staged", "attached"})
    except AttachmentNotFound as exc:
        raise ConversationAttachmentError("conversation_context.attachment_not_found") from exc
    except (AttachmentUnavailable, AttachmentValidationError) as exc:
        raise ConversationAttachmentError("conversation_context.attachment_unavailable") from exc


@synchronized_private_state
def reconcile_staged_contexts(data_dir: Path) -> dict[str, int]:
    connection = connect(data_dir)
    now = time.time()
    pack_attachment_ids: tuple[str, ...] = ()
    try:
        with transaction(connection, immediate=True):
            before = int(connection.execute(
                "SELECT COUNT(*) FROM mentat_conversation_staged_attachments"
            ).fetchone()[0])
            invalid_pack_conversations = tuple(
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT s.conversation_id "
                    "FROM mentat_conversation_staged_attachments AS s "
                    "JOIN attachments AS a ON a.id = s.attachment_id "
                    "LEFT JOIN blobs AS b ON b.id = a.blob_id "
                    "WHERE s.source = 'context_pack' AND ("
                    "a.state != 'staged' OR b.state != 'ready' "
                    "OR a.expires_at IS NULL OR a.expires_at <= ?)",
                    (now,),
                ).fetchall()
            )
            if invalid_pack_conversations:
                placeholders = ",".join("?" for _ in invalid_pack_conversations)
                pack_attachment_ids = tuple(
                    str(row[0])
                    for row in connection.execute(
                        "SELECT attachment_id FROM mentat_conversation_staged_attachments "
                        f"WHERE source = 'context_pack' AND conversation_id IN ({placeholders})",
                        invalid_pack_conversations,
                    ).fetchall()
                )
                connection.execute(
                    "DELETE FROM mentat_conversation_staged_contexts "
                    f"WHERE conversation_id IN ({placeholders})",
                    invalid_pack_conversations,
                )
            connection.execute(
                "DELETE FROM mentat_conversation_staged_attachments "
                "WHERE source != 'context_pack' AND attachment_id IN ("
                "SELECT a.id FROM attachments AS a LEFT JOIN blobs AS b ON b.id = a.blob_id "
                "WHERE a.state != 'staged' OR b.state != 'ready' OR a.expires_at IS NULL OR a.expires_at <= ?)",
                (now,),
            )
            after = int(connection.execute(
                "SELECT COUNT(*) FROM mentat_conversation_staged_attachments"
            ).fetchone()[0])
        for attachment_id in pack_attachment_ids:
            try:
                release_attachment(data_dir, attachment_id)
            except AttachmentError:
                pass
        return {
            "staged_references_removed": max(0, before - after),
            "context_packs_removed": len(invalid_pack_conversations),
        }
    finally:
        connection.close()


__all__ = [
    "ConversationAttachmentError",
    "associate_staged_attachment",
    "clear_staged_context_pack",
    "bind_staged_context_to_run",
    "conversation_media",
    "conversation_staged_context",
    "copy_run_input_context",
    "open_conversation_attachment_stream",
    "reconcile_staged_contexts",
    "release_staged_attachment",
    "replace_context_pack_stage",
    "run_input_context",
    "stage_uploaded_attachment",
    "staged_context_evidence",
]
