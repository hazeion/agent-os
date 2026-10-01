"""Fixed owner-only Project deliverable bridge operations."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path
import re
import sqlite3

from agent_console_attachments import AttachmentError
from project_context import ProjectContextError
from project_repository import ProjectRepositoryError
from task_repository import TaskRepositoryConflict, TaskRepositoryError
from project_deliverables import (
    DeliverableError, publish_owner_edit, read_deliverable_preview,
    read_deliverable_version, read_project_deliverables,
    read_retired_deliverable_history, read_retired_deliverable_version,
)
from project_deliverable_review import (
    DeliverableReviewError, confirm_review, preview_review, read_review_status,
)


READ_OPERATIONS = frozenset({"project", "version", "retired-history", "retired-version", "preview", "review-status"})
WRITE_OPERATIONS = frozenset({"publish", "review-preview", "review-confirm"})
MAX_ACTION_BYTES = 128 * 1024
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_VERSION = re.compile(r"deliverable_version_[0-9a-f]{32}\Z")
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_FIELDS = {
    "project": {"project_id"},
    "version": {"project_id", "version_id"},
    "retired-history": set(),
    "retired-version": {"version_id"},
    "preview": {"version_id"},
    "publish": {"project_id", "slot", "content", "expected_project_revision", "expected_slot_revision",
                "source_version_id", "associated_task_id", "expected_task_revision"},
    "review-status": {"project_id"},
    "review-preview": {"project_id", "action", "note", "affected_slots"},
    "review-confirm": {"project_id", "action", "note", "affected_slots", "confirmation_id"},
}


def _failure(code: str, status: int):
    return {"schema_version": 1, "status": code}, status


def dispatch_project_deliverables(data_dir: Path, operation: str, body: object) -> tuple[dict, int]:
    if operation not in READ_OPERATIONS | WRITE_OPERATIONS or not isinstance(body, dict):
        return _failure("invalid", 400)
    if operation != "retired-history" and set(body) != _FIELDS[operation]:
        return _failure("invalid", 400)
    if operation == "retired-history" and set(body) not in (set(), {"offset"}):
        return _failure("invalid", 400)
    history_offset = 0
    if operation == "retired-history":
        raw_offset = body.get("offset", 0)
        if isinstance(raw_offset, str) and re.fullmatch(r"(?:0|50|100|150|200|250)", raw_offset):
            history_offset = int(raw_offset)
        elif type(raw_offset) is int and raw_offset in {0, 50, 100, 150, 200, 250}:
            history_offset = raw_offset
        else:
            return _failure("invalid", 400)
    if ("project_id" in body and (not isinstance(body["project_id"], str) or _PROJECT.fullmatch(body["project_id"]) is None)
            or "version_id" in body and (not isinstance(body["version_id"], str) or _VERSION.fullmatch(body["version_id"]) is None)):
        return _failure("invalid", 400)
    if operation == "publish":
        if (body["slot"] not in ("layout", "products", "steps")
                or type(body["expected_project_revision"]) is not int or not 1 <= body["expected_project_revision"] <= 9007199254740991
                or type(body["expected_slot_revision"]) is not int or not 0 <= body["expected_slot_revision"] < 32
                or body["source_version_id"] is not None and (not isinstance(body["source_version_id"], str) or _VERSION.fullmatch(body["source_version_id"]) is None)
                or body["associated_task_id"] is not None and (not isinstance(body["associated_task_id"], str) or _TASK.fullmatch(body["associated_task_id"]) is None)
                or (body["associated_task_id"] is None) != (body["expected_task_revision"] is None)
                or body["expected_task_revision"] is not None and (type(body["expected_task_revision"]) is not int or not 1 <= body["expected_task_revision"] <= 9007199254740991)):
            return _failure("invalid", 400)
    try:
        if operation == "project":
            result = read_project_deliverables(data_dir, body["project_id"])
        elif operation == "version":
            result = read_deliverable_version(data_dir, body["project_id"], body["version_id"])
        elif operation == "retired-history":
            result = read_retired_deliverable_history(data_dir, offset=history_offset)
        elif operation == "retired-version":
            result = read_retired_deliverable_version(data_dir, body["version_id"])
        elif operation == "preview":
            content = read_deliverable_preview(data_dir, body["version_id"])
            result = {"version_id": body["version_id"], "content_base64": base64.b64encode(content).decode("ascii"),
                      "sha256": hashlib.sha256(content).hexdigest(), "byte_size": len(content)}
        elif operation == "review-status":
            result = read_review_status(data_dir, body["project_id"])
        elif operation == "review-preview":
            result = preview_review(data_dir, body["project_id"], body["action"], body["note"], body["affected_slots"])
        elif operation == "review-confirm":
            result = confirm_review(data_dir, body["project_id"], body["action"], body["note"], body["affected_slots"], body["confirmation_id"])
        else:
            result = publish_owner_edit(data_dir, body["project_id"], body["slot"], body["content"],
                                        expected_project_revision=body["expected_project_revision"],
                                        expected_slot_revision=body["expected_slot_revision"],
                                        source_version_id=body["source_version_id"],
                                        associated_task_id=body["associated_task_id"],
                                        expected_task_revision=body["expected_task_revision"])
        return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": "ready", "data": result}, 200
    except DeliverableError as exc:
        code = str(exc).rsplit(".", 1)[-1]
        allowed = {"revision_conflict", "source_changed", "project_changed", "task_changed", "version_unavailable",
                   "project_unavailable", "capacity", "inbox_capacity", "content_invalid", "content_capacity", "preview_unavailable",
                   "preview_capacity", "link_invalid", "slot_invalid", "revision_invalid"}
        return _failure(code, 409) if code in allowed else _failure("unavailable", 503)
    except DeliverableReviewError as exc:
        code = str(exc).rsplit(".", 1)[-1]
        if code in {"request_invalid", "confirmation_invalid"}:
            return _failure("invalid", 400)
        if code in {"incomplete", "stale", "confirmation_conflict", "capacity", "inbox_capacity", "project_unavailable"}:
            return _failure(code, 409)
        return _failure("unavailable", 503)
    except ProjectRepositoryError as exc:
        if exc.code == "project_repository.not_found":
            return _failure("project_unavailable", 404)
        return _failure("unavailable", 503)
    except TaskRepositoryConflict:
        return _failure("task_changed", 409)
    except ProjectContextError as exc:
        if str(exc) == "project_context.capacity":
            return _failure("capacity", 409)
        return _failure("unavailable", 503)
    except (TaskRepositoryError, AttachmentError, OSError, sqlite3.Error):
        return _failure("unavailable", 503)
