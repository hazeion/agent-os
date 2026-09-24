"""Exact owner decisions on the three current Project deliverable versions.

A decision records owner review only. It neither certifies an Agent result nor
dispatches work, changes a Task, or grants a runtime capability.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from private_state import private_state_lock
from project_repository import ProjectRepository
from task_repository import _guarded_transaction, _open_repository_database


MAX_REVIEWS = 256
MAX_REVISION = 9007199254740991
SLOTS = ("layout", "products", "steps")
_REVIEW_ID = re.compile(r"deliverable_review_[0-9a-f]{32}\Z")
_VERSION_ID = re.compile(r"deliverable_version_[0-9a-f]{32}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class DeliverableReviewError(RuntimeError):
    pass


def _fail(code: str) -> None:
    raise DeliverableReviewError(f"deliverable_review.{code}")


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _request(action: object, note: object, affected_slots: object) -> tuple[str, str, tuple[str, ...]]:
    if action not in ("accept", "request_changes") or not isinstance(note, str) or "\x00" in note:
        _fail("request_invalid")
    note = note.strip()
    try:
        note_size = len(note.encode("utf-8"))
    except UnicodeError:
        _fail("request_invalid")
    if note_size > 2000 or any(ord(character) < 32 and character not in "\n\t" for character in note):
        _fail("request_invalid")
    if not isinstance(affected_slots, list) or len(affected_slots) > len(SLOTS):
        _fail("request_invalid")
    if any(not isinstance(slot, str) or slot not in SLOTS for slot in affected_slots):
        _fail("request_invalid")
    if len(affected_slots) != len(set(affected_slots)):
        _fail("request_invalid")
    affected = tuple(slot for slot in SLOTS if slot in affected_slots)
    if action == "accept" and (affected != SLOTS or note):
        _fail("request_invalid")
    if action == "request_changes" and (not affected or not note):
        _fail("request_invalid")
    return action, note, affected


def validate_review_connection(connection: sqlite3.Connection) -> list[list]:
    """Validate a bounded review graph, including historical deleted Projects."""
    state = connection.execute(
        "SELECT singleton,confirmation_epoch,revision FROM mentat_deliverable_review_state"
    ).fetchmany(2)
    if (len(state) != 1 or state[0][0] != 1 or not isinstance(state[0][1], bytes)
            or len(state[0][1]) != 32 or type(state[0][2]) is not int
            or not 0 <= state[0][2] <= MAX_REVISION):
        _fail("invalid")
    reviews = connection.execute(
        "SELECT id,project_id,project_incarnation,project_revision,revision,action,note,"
        "heads_digest,request_digest,confirmation_digest,created_at "
        "FROM mentat_deliverable_reviews ORDER BY revision"
    ).fetchmany(MAX_REVIEWS + 1)
    versions = connection.execute(
        "SELECT review_id,slot,version_id,affected FROM mentat_deliverable_review_versions "
        "ORDER BY review_id,slot"
    ).fetchmany(MAX_REVIEWS * 3 + 1)
    if len(reviews) > MAX_REVIEWS or len(versions) > MAX_REVIEWS * 3:
        _fail("capacity")
    if state[0][2] != len(reviews):
        _fail("invalid")
    if reviews and state[0][1] == bytes(32):
        _fail("invalid")
    grouped: dict[str, list[tuple]] = {}
    for row in versions:
        grouped.setdefault(row[0], []).append(tuple(row))
    for index, row in enumerate(reviews, 1):
        (identifier, project_id, incarnation, project_revision, revision, action,
         note, heads_digest, request_digest, confirmation_digest, created) = tuple(row)
        if (not isinstance(identifier, str) or _REVIEW_ID.fullmatch(identifier) is None
                or not isinstance(project_id, str) or not project_id
                or not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None
                or type(project_revision) is not int or project_revision < 1
                or revision != index or type(created) not in (int, float)
                or not math.isfinite(created) or created <= 0
                or any(not isinstance(value, str) or _HEX64.fullmatch(value) is None
                       for value in (heads_digest, request_digest, confirmation_digest))):
            _fail("invalid")
        selected = grouped.pop(identifier, [])
        if len(selected) != 3 or {item[1] for item in selected} != set(SLOTS):
            _fail("invalid")
        affected = [item[1] for item in selected if item[3] == 1]
        try:
            _request(action, note, affected)
        except DeliverableReviewError:
            _fail("invalid")
        heads = []
        for _, slot, version_id, flag in selected:
            if (flag not in (0, 1) or not isinstance(version_id, str)
                    or _VERSION_ID.fullmatch(version_id) is None):
                _fail("invalid")
            version = connection.execute(
                "SELECT s.project_id,s.project_incarnation,s.slot,s.id,v.revision,v.content_digest,v.origin "
                "FROM mentat_deliverable_versions v JOIN mentat_deliverable_slots s ON s.id=v.slot_id "
                "WHERE v.id=?", (version_id,),
            ).fetchone()
            if (version is None or version[0] != project_id or version[1] != incarnation
                    or version[2] != slot):
                _fail("invalid")
            heads.append([slot, version[3], version_id, version[4], version[5], version[6]])
        heads.sort(key=lambda item: SLOTS.index(item[0]))
        if _digest(heads) != heads_digest:
            _fail("invalid")
        if _digest([project_id, action, note, list(affected)]) != request_digest:
            _fail("invalid")
    if grouped:
        _fail("invalid")
    # Charge full note capacity, rather than current note length, so a valid
    # full history stays within the shared backup budget after future reviews.
    charged = [list(row[:6]) + ["x" * 2000] + list(row[7:]) for row in reviews]
    return [[state[0][0], state[0][1].hex(), state[0][2]], charged,
            [list(row) for row in versions]]


def _current(connection: sqlite3.Connection, project_id: str, *, require_complete: bool = True) -> tuple[object, str, list[list], bytes, int]:
    project = ProjectRepository(connection).get(project_id)
    if project.document["status"] != "active":
        _fail("project_unavailable")
    row = connection.execute(
        "SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (project_id,),
    ).fetchone()
    incarnation = row[0] if row else None
    if not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None:
        _fail("project_unavailable")
    heads = []
    for slot, slot_id, version_id, revision, digest, origin in connection.execute(
        "SELECT s.slot,s.id,v.id,v.revision,v.content_digest,v.origin "
        "FROM mentat_deliverable_slots s JOIN mentat_deliverable_versions v "
        "ON v.slot_id=s.id AND v.revision=s.head_revision "
        "WHERE s.project_id=? AND s.project_incarnation=? AND s.retired_at IS NULL "
        "ORDER BY s.slot", (project_id, incarnation),
    ):
        heads.append([slot, slot_id, version_id, revision, digest, origin])
    if require_complete and (len(heads) != 3 or {head[0] for head in heads} != set(SLOTS)):
        _fail("incomplete")
    heads.sort(key=lambda item: SLOTS.index(item[0]))
    epoch, review_revision = connection.execute(
        "SELECT confirmation_epoch,revision FROM mentat_deliverable_review_state WHERE singleton=1"
    ).fetchone()
    return project, incarnation, heads, epoch, review_revision


def _confirmation(epoch: bytes, project_id: str, incarnation: str, project_revision: int,
                  review_revision: int, heads: list[list], action: str, note: str,
                  affected: tuple[str, ...]) -> str:
    claims = ["mentat.deliverable.review.v1", project_id, incarnation, project_revision,
              review_revision, heads, action, note, list(affected)]
    return hmac.new(epoch, _canonical(claims), hashlib.sha256).hexdigest()


def preview_review(data_dir: Path, project_id: str, action: object, note: object,
                   affected_slots: object) -> dict:
    action, note, affected = _request(action, note, affected_slots)
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                from project_context import validate_project_context_connection
                validate_project_context_connection(connection, require_available=False)
                project, incarnation, heads, epoch, revision = _current(connection, project_id)
                if revision >= MAX_REVIEWS:
                    _fail("capacity")
                if epoch == bytes(32):
                    connection.execute(
                        "UPDATE mentat_deliverable_review_state SET confirmation_epoch=randomblob(32) WHERE singleton=1"
                    )
                    epoch = connection.execute(
                        "SELECT confirmation_epoch FROM mentat_deliverable_review_state WHERE singleton=1"
                    ).fetchone()[0]
                confirmation = _confirmation(epoch, project_id, incarnation, project.revision,
                                             revision, heads, action, note, affected)
                return {"project_id": project_id, "project_name": project.document["name"],
                        "project_revision": project.revision, "action": action, "note": note,
                        "affected_slots": list(affected), "heads": [
                            {"slot": head[0], "version_id": head[2], "revision": head[3],
                             "origin": head[5]} for head in heads],
                        "confirmation_id": confirmation}


def confirm_review(data_dir: Path, project_id: str, action: object, note: object,
                   affected_slots: object, confirmation_id: object) -> dict:
    action, note, affected = _request(action, note, affected_slots)
    if not isinstance(confirmation_id, str) or _HEX64.fullmatch(confirmation_id) is None:
        _fail("confirmation_invalid")
    request_digest = _digest([project_id, action, note, list(affected)])
    confirmation_digest = hashlib.sha256(bytes.fromhex(confirmation_id)).hexdigest()
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                existing = connection.execute(
                    "SELECT id,project_id,request_digest,revision FROM mentat_deliverable_reviews "
                    "WHERE confirmation_digest=?", (confirmation_digest,),
                ).fetchone()
                if existing is not None:
                    if existing[1] != project_id or not hmac.compare_digest(existing[2], request_digest):
                        _fail("confirmation_conflict")
                    return {"id": existing[0], "revision": existing[3], "action": action,
                            "project_id": project_id, "duplicate": True}
                from project_context import validate_project_context_connection
                validate_project_context_connection(connection, require_available=False)
                project, incarnation, heads, epoch, revision = _current(connection, project_id)
                if epoch == bytes(32):
                    _fail("stale")
                if revision >= MAX_REVIEWS:
                    _fail("capacity")
                expected = _confirmation(epoch, project_id, incarnation, project.revision,
                                         revision, heads, action, note, affected)
                if not hmac.compare_digest(expected, confirmation_id):
                    _fail("stale")
                identifier = f"deliverable_review_{uuid.uuid4().hex}"
                next_revision = revision + 1
                connection.execute(
                    "INSERT INTO mentat_deliverable_reviews VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (identifier, project_id, incarnation, project.revision, next_revision, action,
                     note, _digest(heads), request_digest, confirmation_digest, time.time()),
                )
                connection.executemany(
                    "INSERT INTO mentat_deliverable_review_versions VALUES(?,?,?,?)",
                    [(identifier, head[0], head[2], int(head[0] in affected)) for head in heads],
                )
                connection.execute(
                    "UPDATE mentat_deliverable_review_state SET revision=? WHERE singleton=1",
                    (next_revision,),
                )
                from owner_inbox import OwnerInboxError, sync_result_review_connection, validate_inbox_connection
                try:
                    sync_result_review_connection(connection, project_id)
                    validate_inbox_connection(connection)
                except OwnerInboxError as exc:
                    _fail("inbox_capacity" if str(exc) == "owner_inbox.capacity" else "inbox_unavailable")
                validate_project_context_connection(connection, require_available=False)
                return {"id": identifier, "revision": next_revision, "action": action,
                        "project_id": project_id, "duplicate": False}


def read_review_status(data_dir: Path, project_id: str) -> dict:
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                from project_context import validate_project_context_connection
                validate_project_context_connection(connection, require_available=False)
                project, incarnation, heads, _epoch, _revision = _current(
                    connection, project_id, require_complete=False,
                )
                row = connection.execute(
                    "SELECT id,revision,action,note,heads_digest,created_at "
                    "FROM mentat_deliverable_reviews WHERE project_id=? AND project_incarnation=? "
                    "ORDER BY revision DESC LIMIT 1", (project_id, incarnation),
                ).fetchone()
                latest = None if row is None else {
                    "id": row[0], "revision": row[1], "action": row[2], "note": row[3],
                    "created_at": row[5], "current": hmac.compare_digest(row[4], _digest(heads)),
                    "affected_slots": [item[0] for item in connection.execute(
                        "SELECT slot FROM mentat_deliverable_review_versions "
                        "WHERE review_id=? AND affected=1 ORDER BY slot", (row[0],),
                    )],
                }
                complete = len(heads) == 3 and {head[0] for head in heads} == set(SLOTS)
                return {"project_id": project_id, "project_name": project.document["name"],
                        "status": "incomplete" if not complete else latest["action"] if latest and latest["current"] else "pending",
                        "latest": latest}
