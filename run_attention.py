"""Private, source-bound Run outcome reservations for the owner Inbox."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3


MAX_RUN_ATTENTION = 10_000
MAX_ROW_CHARGE = 1_536
MAX_METADATA_CHARGE = MAX_RUN_ATTENTION * MAX_ROW_CHARGE
_RUN_ID = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z")
_ITEM_ID = re.compile(r"inbox_item_[0-9a-f]{32}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_TERMINAL = frozenset({"completed", "failed", "cancelled", "stopped", "interrupted"})
_STATUSES = _TERMINAL | frozenset({
    "reserved", "queued", "submitting", "starting", "running", "cancelling",
    "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown",
})
_DISPATCH = frozenset({"legacy", "reserved", "submitting", "accepted", "rejected", "unknown"})


class RunAttentionError(RuntimeError):
    pass


def _fail() -> None:
    raise RunAttentionError("run_attention.invalid")


def _digest(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _time(value: object, *, required: bool = False) -> bool:
    return (value is None and not required) or (
        type(value) in (float, int) and math.isfinite(value) and value > 0
    )


def validate_run_attention_connection(connection: sqlite3.Connection) -> None:
    """Validate every hidden, live, and retired Run-attention row."""

    version = int(connection.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0])
    if version < 36:
        return
    rows = connection.execute(
        "SELECT a.run_id,a.incarnation,a.item_id,a.revision,a.created_at,a.updated_at,a.read_at,"
        "a.acknowledged_at,a.resolved_at,a.last_action_digest,a.last_expected_revision,a.retired_at,"
        "a.retired_source,a.retired_status,a.retired_dispatch_state,a.retired_partial,"
        "a.retired_terminal_finalized,a.retired_state_revision,a.retired_task_id,"
        "a.retired_conversation_id,a.retired_agent_id,a.retired_run_created_at,"
        "a.retired_run_updated_at,a.retired_run_completed_at,"
        "r.status,r.dispatch_state,r.partial,r.terminal_finalized,i.incarnation,b.id "
        "FROM mentat_run_attention a LEFT JOIN mentat_runs r ON r.id=a.run_id "
        "LEFT JOIN mentat_run_identities i ON i.run_id=r.id "
        "LEFT JOIN mentat_inbox_items b ON b.id=a.item_id ORDER BY a.run_id,a.incarnation"
    ).fetchall()
    if len(rows) > MAX_RUN_ATTENTION:
        _fail()
    if connection.execute(
        "SELECT 1 FROM mentat_runs r JOIN mentat_run_identities i ON i.run_id=r.id "
        "LEFT JOIN mentat_run_attention a ON a.run_id=i.run_id AND a.incarnation=i.incarnation "
        "WHERE a.run_id IS NULL LIMIT 1"
    ).fetchone() is not None:
        _fail()
    if connection.execute(
        "SELECT 1 FROM mentat_runs r LEFT JOIN mentat_run_identities i ON i.run_id=r.id "
        "WHERE i.run_id IS NULL LIMIT 1"
    ).fetchone() is not None:
        _fail()
    seen_items: set[str] = set()
    seen_sources: set[tuple[str, str]] = set()
    charge = 0
    for row in rows:
        (run_id, incarnation, item_id, revision, created, updated, read_at,
         acknowledged, resolved, action_digest, expected, retired_at,
         retired_source, retired_status, retired_dispatch, retired_partial,
         retired_finalized, retired_revision, retired_task, retired_conversation,
         retired_agent, retired_created, retired_updated, retired_completed) = tuple(row[:24])
        if (not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None
                or not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None
                or type(revision) is not int or not 0 <= revision <= 2_147_483_647):
            _fail()
        source_key = (run_id, incarnation)
        if source_key in seen_sources:
            _fail()
        seen_sources.add(source_key)
        if item_id is None:
            if (revision != 0 or any(value is not None for value in
                    (created, updated, read_at, acknowledged, resolved, action_digest, expected, retired_at))):
                _fail()
        else:
            if (not isinstance(item_id, str) or _ITEM_ID.fullmatch(item_id) is None
                    or item_id in seen_items or not 1 <= revision <= 2_147_483_647
                    or not _time(created, required=True) or not _time(updated, required=True)
                    or updated < created or any(not _time(value) for value in
                        (read_at, acknowledged, resolved))
                    or any(value is not None and value < created for value in
                        (read_at, acknowledged, resolved))):
                _fail()
            seen_items.add(item_id)
            if row[29] is not None:
                _fail()
            if (action_digest is None) != (expected is None):
                _fail()
            if action_digest is not None:
                if (not isinstance(action_digest, str) or _HEX64.fullmatch(action_digest) is None
                        or type(expected) is not int or not 1 <= expected < revision):
                    _fail()
                if action_digest == _digest([item_id, "read", expected]):
                    if read_at is None:
                        _fail()
                elif action_digest == _digest([item_id, "acknowledge", expected]):
                    if read_at is None or acknowledged is None:
                        _fail()
                elif action_digest == _digest([item_id, "dismiss", expected]):
                    if read_at is None or acknowledged is None or resolved is None:
                        _fail()
                else:
                    _fail()
        live = row[24:29] if row[28] is not None else None
        same_live = live is not None and live[4] == incarnation
        if retired_at is None:
            if not same_live or any(value is not None for value in row[12:24]):
                _fail()
            status, _dispatch, partial, finalized = live[:4]
            actionable = (status == "unknown" or status in ("failed", "interrupted")
                          or status in _TERMINAL and (partial == 1 or finalized == 0))
            if actionable and item_id is None:
                _fail()
            uncertain = status == "unknown" or status in _TERMINAL and (partial == 1 or finalized == 0)
        else:
            if (not _time(retired_at, required=True) or same_live or item_id is None
                    or retired_source not in ("console", "task_dispatch")
                    or retired_status not in _TERMINAL or retired_dispatch not in _DISPATCH
                    or type(retired_partial) is not int or retired_partial not in (0, 1)
                    or type(retired_finalized) is not int or retired_finalized not in (0, 1)
                    or type(retired_revision) is not int or retired_revision < 1
                    or not isinstance(retired_created, str) or not isinstance(retired_updated, str)
                    or len(retired_created) > 64 or len(retired_updated) > 64
                    or any(value is not None and (not isinstance(value, str) or len(value) > limit)
                           for value, limit in ((retired_task, 160), (retired_conversation, 128),
                                                (retired_agent, 128), (retired_completed, 64)))):
                _fail()
            uncertain = retired_partial == 1 or retired_finalized == 0
        if uncertain and resolved is not None:
            _fail()
        encoded = json.dumps(list(row[:24]), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        charge += len(encoded.encode("utf-8"))
        if len(encoded.encode("utf-8")) > MAX_ROW_CHARGE or charge > MAX_METADATA_CHARGE:
            _fail()
