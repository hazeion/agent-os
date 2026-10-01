"""Owner-private attention receipts derived from exact durable source records.

Inbox reads and acknowledgments never authorize the source action. Only fixed
source adapters may materialize an item inside their own SQLite transaction.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from private_state import private_state_lock
from task_repository import _guarded_transaction, _open_repository_database


MAX_ITEMS = 2048
MAX_RESULT_ITEMS = 256
ROW_CHARGE = 768
METADATA_BUDGET = 2 * 1024 * 1024
SLOTS = ("layout", "products", "steps")
_ITEM = re.compile(r"inbox_item_[0-9a-f]{32}\Z")
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_VERSION = re.compile(r"deliverable_version_[0-9a-f]{32}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class OwnerInboxError(RuntimeError):
    pass


def _fail(code: str) -> None:
    raise OwnerInboxError(f"owner_inbox.{code}")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _heads(connection: sqlite3.Connection, project_id: str, incarnation: str) -> list[list]:
    rows = [list(row) for row in connection.execute(
        "SELECT s.slot,s.id,v.id,v.revision,v.content_digest,v.origin "
        "FROM mentat_deliverable_slots s JOIN mentat_deliverable_versions v "
        "ON v.slot_id=s.id AND v.revision=s.head_revision "
        "WHERE s.project_id=? AND s.project_incarnation=? AND s.retired_at IS NULL "
        "ORDER BY s.slot", (project_id, incarnation),
    )]
    if any(row[0] not in SLOTS for row in rows):
        _fail("source_invalid")
    rows.sort(key=lambda row: SLOTS.index(row[0]))
    return rows


def _stored_heads(heads: list[list]) -> str:
    return _canonical([head[2] for head in heads]).decode("utf-8")


def _row_charge(row: tuple) -> int:
    # Charge the full canonical row, including terminal/action fields, at its
    # largest supported representation rather than its current short values.
    charged = list(row)
    for index in (7, 8, 9, 10, 11):
        charged[index] = "9" * 24
    charged[12] = "f" * 64
    charged[13] = 15
    return len(_canonical(charged))


def validate_inbox_connection(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT id,kind,source_id,source_incarnation,generation_digest,heads_json,revision,"
        "created_at,updated_at,read_at,acknowledged_at,resolved_at,last_action_digest,last_expected_revision "
        "FROM mentat_inbox_items ORDER BY created_at,id"
    ).fetchall()
    if len(rows) > MAX_ITEMS or len(rows) * ROW_CHARGE > METADATA_BUDGET:
        _fail("capacity")
    if len(rows) > MAX_RESULT_ITEMS:  # schema 34 has only the result producer
        _fail("capacity")
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        (identifier, kind, source_id, incarnation, generation, encoded, revision,
         created, updated, read_at, acknowledged, resolved, action_digest, expected) = row
        if (not isinstance(identifier, str) or _ITEM.fullmatch(identifier) is None
                or kind != "result_review" or not isinstance(source_id, str)
                or _PROJECT.fullmatch(source_id) is None
                or not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None
                or not isinstance(generation, str) or _HEX64.fullmatch(generation) is None
                or type(revision) is not int or not 1 <= revision <= 16):
            _fail("invalid")
        key = (kind, source_id, incarnation, generation)
        if key in seen:
            _fail("duplicate")
        seen.add(key)
        try:
            versions = json.loads(encoded)
        except (TypeError, ValueError):
            _fail("invalid")
        if (not isinstance(encoded, str) or not isinstance(versions, list) or len(versions) != 3
                or any(not isinstance(item, str) or _VERSION.fullmatch(item) is None for item in versions)
                or encoded != _canonical(versions).decode("utf-8")
                or generation != _digest(versions)):
            _fail("invalid")
        proof = [tuple(item) for item in connection.execute(
            "SELECT s.slot,v.id FROM mentat_deliverable_versions v "
            "JOIN mentat_deliverable_slots s ON s.id=v.slot_id "
            "WHERE s.project_id=? AND s.project_incarnation=? AND v.id IN (?,?,?)",
            (source_id, incarnation, *versions),
        ).fetchall()]
        if (len(proof) != 3 or any(slot not in SLOTS for slot, _version in proof)
                or sorted(proof, key=lambda pair: SLOTS.index(pair[0])) != list(zip(SLOTS, versions))):
            _fail("source_invalid")
        current_project = connection.execute(
            "SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (source_id,),
        ).fetchone()
        current_pending = False
        if current_project is not None and current_project[0] == incarnation:
            current_heads = _heads(connection, source_id, incarnation)
            if (len(current_heads) == 3 and [head[2] for head in current_heads] == versions):
                latest = connection.execute(
                    "SELECT heads_digest FROM mentat_deliverable_reviews "
                    "WHERE project_id=? AND project_incarnation=? ORDER BY revision DESC LIMIT 1",
                    (source_id, incarnation),
                ).fetchone()
                current_pending = latest is None or latest[0] != _digest(current_heads)
        if current_pending == (resolved is not None):
            _fail("source_state_invalid")
        times = (created, updated, read_at, acknowledged, resolved)
        if (any(value is not None and (type(value) not in (float, int) or not math.isfinite(value)) for value in times)
                or created <= 0 or updated < created
                or any(value is not None and value < created for value in times[2:])):
            _fail("invalid")
        if ((action_digest is None) != (expected is None)
                or action_digest is not None and (not isinstance(action_digest, str) or _HEX64.fullmatch(action_digest) is None)
                or expected is not None and (type(expected) is not int or not 1 <= expected < revision)):
            _fail("invalid")
        if action_digest is not None:
            if action_digest == _digest([identifier, "read", expected]):
                if read_at is None:
                    _fail("receipt_invalid")
            elif action_digest == _digest([identifier, "acknowledge", expected]):
                if acknowledged is None or read_at is None:
                    _fail("receipt_invalid")
            else:
                _fail("receipt_invalid")
        if _row_charge(row) > ROW_CHARGE:
            _fail("budget")


def _prune_resolved(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT id FROM mentat_inbox_items WHERE resolved_at IS NOT NULL AND acknowledged_at IS NOT NULL "
        "ORDER BY created_at,id LIMIT 1"
    ).fetchone()
    if row is None:
        return False
    connection.execute("DELETE FROM mentat_inbox_items WHERE id=?", (row[0],))
    return True


def sync_result_review_connection(connection: sqlite3.Connection, project_id: str) -> None:
    """Synchronize one Project's current review generation in its source transaction."""
    if not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None:
        _fail("invalid")
    project = connection.execute(
        "SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (project_id,),
    ).fetchone()
    if project is None:
        _fail("source_unavailable")
    incarnation = project[0]
    if not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None:
        _fail("source_unavailable")
    heads = _heads(connection, project_id, incarnation)
    complete = len(heads) == 3 and {head[0] for head in heads} == set(SLOTS)
    generation = _digest([head[2] for head in heads]) if complete else None
    now = time.time()
    connection.execute(
        "UPDATE mentat_inbox_items SET resolved_at=MAX(updated_at,created_at,?),updated_at=MAX(updated_at,created_at,?),revision=revision+1 "
        "WHERE kind='result_review' AND source_id=? AND source_incarnation=? "
        "AND resolved_at IS NULL AND (? IS NULL OR generation_digest!=?)",
        (now, now, project_id, incarnation, generation, generation),
    )
    if not complete:
        return
    latest = connection.execute(
        "SELECT heads_digest FROM mentat_deliverable_reviews "
        "WHERE project_id=? AND project_incarnation=? ORDER BY revision DESC LIMIT 1",
        (project_id, incarnation),
    ).fetchone()
    if latest is not None and latest[0] == _digest(heads):
        connection.execute(
            "UPDATE mentat_inbox_items SET resolved_at=MAX(updated_at,created_at,?),updated_at=MAX(updated_at,created_at,?),revision=revision+1 "
            "WHERE kind='result_review' AND source_id=? AND source_incarnation=? "
            "AND generation_digest=? AND resolved_at IS NULL",
            (now, now, project_id, incarnation, generation),
        )
        return
    if connection.execute(
        "SELECT 1 FROM mentat_inbox_items WHERE kind='result_review' AND source_id=? "
        "AND source_incarnation=? AND generation_digest=?",
        (project_id, incarnation, generation),
    ).fetchone():
        return
    while connection.execute("SELECT COUNT(*) FROM mentat_inbox_items").fetchone()[0] >= MAX_ITEMS or connection.execute(
        "SELECT COUNT(*) FROM mentat_inbox_items WHERE kind='result_review'"
    ).fetchone()[0] >= MAX_RESULT_ITEMS:
        if not _prune_resolved(connection):
            _fail("capacity")
    identifier = f"inbox_item_{uuid.uuid4().hex}"
    connection.execute(
        "INSERT INTO mentat_inbox_items VALUES(?,?,?,?,?,?,1,?,?,NULL,NULL,NULL,NULL,NULL)",
        (identifier, "result_review", project_id, incarnation, generation, _stored_heads(heads), now, now),
    )


def read_inbox(data_dir: Path, *, limit: int = 50) -> list[dict]:
    if type(limit) is not int or not 1 <= limit <= 50:
        _fail("invalid")
    return read_inbox_page(data_dir, view="all", after=None, limit=limit)["items"]


def _public_item(row: tuple) -> dict:
    return {"id": row[0], "kind": "result_review", "revision": row[3],
            "created_at": row[4], "unread": row[5] is None,
            "acknowledged": row[6] is not None,
            "state": "resolved" if row[7] is not None else
            "stale" if row[8] is None else
            "activation_required" if row[9] != "active" else "needs_review",
            "title": f"Review {row[8]} results" if row[8] else "Retained Project results"}


def read_inbox_page(data_dir: Path, *, view: str = "needs_me", after: str | None = None,
                    limit: int = 50) -> dict:
    if (view not in ("needs_me", "unread", "all")
            or after is not None and (not isinstance(after, str) or _ITEM.fullmatch(after) is None)
            or type(limit) is not int or not 1 <= limit <= 50):
        _fail("invalid")
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                _reconcile_connection(connection)
                validate_inbox_connection(connection)
                where = "i.resolved_at IS NULL" if view == "needs_me" else "i.read_at IS NULL" if view == "unread" else "1=1"
                params: list[object] = []
                if after is not None:
                    cursor = connection.execute(
                        "SELECT created_at,resolved_at,read_at FROM mentat_inbox_items WHERE id=?", (after,),
                    ).fetchone()
                    if (cursor is None or view == "needs_me" and cursor[1] is not None
                            or view == "unread" and cursor[2] is not None):
                        _fail("stale")
                    where += " AND (i.created_at<? OR (i.created_at=? AND i.id<?))"
                    params.extend((cursor[0], cursor[0], after))
                rows = connection.execute(
                    "SELECT i.id,i.source_id,i.source_incarnation,i.revision,i.created_at,i.read_at,"
                    "i.acknowledged_at,i.resolved_at,p.name,p.status "
                    "FROM mentat_inbox_items i LEFT JOIN mentat_projects p "
                    "ON p.id=i.source_id AND p.deliverable_incarnation=i.source_incarnation "
                    f"WHERE {where} ORDER BY i.created_at DESC,i.id DESC LIMIT ?", (*params, limit + 1),
                ).fetchall()
                shown = rows[:limit]
                return {"items": [_public_item(row) for row in shown],
                        "next_cursor": shown[-1][0] if len(rows) > limit else None,
                        "counts": {"needs_me": connection.execute(
                            "SELECT COUNT(*) FROM mentat_inbox_items WHERE resolved_at IS NULL"
                        ).fetchone()[0], "unread": connection.execute(
                            "SELECT COUNT(*) FROM mentat_inbox_items WHERE read_at IS NULL"
                        ).fetchone()[0], "all": connection.execute(
                            "SELECT COUNT(*) FROM mentat_inbox_items"
                        ).fetchone()[0]}}


def _reconcile_connection(connection: sqlite3.Connection) -> None:
    # Upgrade/current-source reconciliation is bounded by the canonical
    # Project limit and creates no work, decision or execution authority.
    for (project_id,) in connection.execute("SELECT id FROM mentat_projects ORDER BY id"):
        sync_result_review_connection(connection, project_id)


def _item_heads_connection(connection: sqlite3.Connection, item_id: str) -> tuple[str, str, list[str], bool]:
    if not isinstance(item_id, str) or _ITEM.fullmatch(item_id) is None:
        _fail("invalid")
    validate_inbox_connection(connection)
    row = connection.execute(
        "SELECT source_id,source_incarnation,heads_json,resolved_at "
        "FROM mentat_inbox_items WHERE id=? AND kind='result_review'", (item_id,),
    ).fetchone()
    if row is None:
        _fail("unavailable")
    return row[0], row[1], json.loads(row[2]), row[3] is not None


def require_pending_result_item_connection(connection: sqlite3.Connection, item_id: str,
                                           project_id: str, incarnation: str, heads: list[list]) -> None:
    """Bind an Inbox review to the source transaction's current exact heads."""
    source_id, source_incarnation, versions, resolved = _item_heads_connection(connection, item_id)
    if (resolved or source_id != project_id or source_incarnation != incarnation
            or versions != [head[2] for head in heads]):
        _fail("stale")


def require_duplicate_result_item_connection(connection: sqlite3.Connection, item_id: str,
                                             review_id: str, project_id: str) -> None:
    """Permit replay of only a decision on this exact retained generation."""
    source_id, source_incarnation, versions, _resolved = _item_heads_connection(connection, item_id)
    review = connection.execute(
        "SELECT project_id,project_incarnation FROM mentat_deliverable_reviews WHERE id=?",
        (review_id,),
    ).fetchone()
    actual = [tuple(row) for row in connection.execute(
        "SELECT slot,version_id FROM mentat_deliverable_review_versions "
        "WHERE review_id=? ORDER BY slot", (review_id,),
    )]
    if any(slot not in SLOTS for slot, _version in actual):
        _fail("source_invalid")
    actual.sort(key=lambda row: SLOTS.index(row[0]))
    if (review is None or source_id != project_id or review[0] != source_id
            or review[1] != source_incarnation or actual != list(zip(SLOTS, versions))):
        _fail("stale")


def reconcile_inbox_at_startup(data_dir: Path) -> None:
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                _reconcile_connection(connection)
                validate_inbox_connection(connection)


def _item_snapshot(data_dir: Path, item_id: str) -> tuple[dict, str, list[str]]:
    if not isinstance(item_id, str) or _ITEM.fullmatch(item_id) is None:
        _fail("invalid")
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_inbox_connection(connection)
                row = connection.execute(
                    "SELECT i.id,i.source_id,i.source_incarnation,i.revision,i.created_at,i.read_at,"
                    "i.acknowledged_at,i.resolved_at,p.name,p.status,i.heads_json "
                    "FROM mentat_inbox_items i LEFT JOIN mentat_projects p "
                    "ON p.id=i.source_id AND p.deliverable_incarnation=i.source_incarnation "
                    "WHERE i.id=?", (item_id,),
                ).fetchone()
                if row is None:
                    _fail("unavailable")
                return _public_item(row), row[1], json.loads(row[10])


def _retained_item_versions(data_dir: Path, item_id: str) -> list[dict]:
    """Read only the three immutable versions named by this Inbox generation."""
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                source_id, incarnation, versions, _resolved = _item_heads_connection(connection, item_id)
                from project_context import validate_project_context_connection
                validate_project_context_connection(connection, require_available=False)
                result = []
                for slot, version_id in zip(SLOTS, versions):
                    row = connection.execute(
                        "SELECT v.revision,v.origin,v.source_version_id,v.content_json,v.created_at "
                        "FROM mentat_deliverable_versions v JOIN mentat_deliverable_slots s ON s.id=v.slot_id "
                        "WHERE v.id=? AND s.project_id=? AND s.project_incarnation=? AND s.slot=?",
                        (version_id, source_id, incarnation, slot),
                    ).fetchone()
                    if row is None:
                        _fail("source_invalid")
                    preview = connection.execute(
                        "SELECT attachment_id FROM mentat_deliverable_files WHERE version_id=? AND role='preview'",
                        (version_id,),
                    ).fetchone()
                    result.append({"id": version_id, "project_id": source_id, "slot": slot,
                                   "revision": row[0], "origin": row[1],
                                   "source_version_id": row[2], "content": json.loads(row[3]),
                                   "created_at": row[4], "preview_attachment_id": preview[0] if preview else None})
                return result


def read_result_review_item(data_dir: Path, item_id: str) -> dict:
    """Return exact current source content, or an inert stale/resolved item."""
    item, project_id, versions = _item_snapshot(data_dir, item_id)
    if item["state"] != "needs_review":
        return {"item": item, "project": None, "review": None,
                "versions": _retained_item_versions(data_dir, item_id)}
    from project_deliverables import read_project_deliverables
    from project_deliverable_review import read_review_status
    try:
        project = read_project_deliverables(data_dir, project_id)
        review = read_review_status(data_dir, project_id)
    except (RuntimeError, sqlite3.Error, OSError):
        _fail("stale")
    actual = {slot["slot"]: slot["versions"][0]["id"] for slot in project["slots"] if slot["versions"]}
    if (project["project"]["status"] != "active" or review["status"] != "pending"
            or [actual.get(slot) for slot in SLOTS] != versions):
        _fail("stale")
    verified, _, current_versions = _item_snapshot(data_dir, item_id)
    if verified["state"] != "needs_review" or current_versions != versions:
        _fail("stale")
    return {"item": verified, "project": project, "review": review, "versions": None}


def preview_result_review_item(data_dir: Path, item_id: str, action: object,
                               note: object, affected_slots: object) -> dict:
    item, project_id, versions = _item_snapshot(data_dir, item_id)
    if item["state"] != "needs_review":
        _fail("stale")
    from project_deliverable_review import preview_review
    result = preview_review(data_dir, project_id, action, note, affected_slots,
                            inbox_item_id=item_id)
    if [head["version_id"] for head in result["heads"]] != versions:
        _fail("stale")
    current, _, current_versions = _item_snapshot(data_dir, item_id)
    if current["state"] != "needs_review" or current_versions != versions:
        _fail("stale")
    return result


def confirm_result_review_item(data_dir: Path, item_id: str, action: object,
                               note: object, affected_slots: object,
                               confirmation_id: object) -> dict:
    _, project_id, _versions = _item_snapshot(data_dir, item_id)
    from project_deliverable_review import confirm_review
    return confirm_review(data_dir, project_id, action, note, affected_slots,
                          confirmation_id, inbox_item_id=item_id)


def mark_item(data_dir: Path, item_id: str, *, action: str, expected_revision: int) -> dict:
    if (not isinstance(item_id, str) or _ITEM.fullmatch(item_id) is None
            or action not in ("read", "acknowledge")
            or type(expected_revision) is not int or not 1 <= expected_revision <= 16):
        _fail("invalid")
    digest = _digest([item_id, action, expected_revision])
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                row = connection.execute(
                    "SELECT revision,read_at,acknowledged_at,last_action_digest,last_expected_revision,created_at,updated_at "
                    "FROM mentat_inbox_items WHERE id=?", (item_id,),
                ).fetchone()
                if row is None:
                    _fail("unavailable")
                if row[3] == digest and row[4] == expected_revision:
                    return {"id": item_id, "revision": row[0], "duplicate": True}
                if row[0] != expected_revision:
                    _fail("stale")
                if action == "read" and row[1] is not None or action == "acknowledge" and row[2] is not None:
                    return {"id": item_id, "revision": row[0], "duplicate": True}
                if expected_revision >= 16:
                    _fail("capacity")
                now = max(time.time(), row[5], row[6])
                read_at = row[1] if row[1] is not None else now
                ack_at = row[2] if action == "read" or row[2] is not None else now
                connection.execute(
                    "UPDATE mentat_inbox_items SET revision=revision+1,updated_at=?,read_at=?,"
                    "acknowledged_at=?,last_action_digest=?,last_expected_revision=? WHERE id=?",
                    (now, read_at, ack_at, digest, expected_revision, item_id),
                )
                validate_inbox_connection(connection)
                return {"id": item_id, "revision": expected_revision + 1, "duplicate": False}
