"""Fixed private bridge for owner inbox receipts; no source action authority."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from owner_inbox import (MAX_RUN_REVISION, OwnerInboxError, confirm_result_review_item, mark_item,
                         preview_result_review_item, read_inbox,
                         read_inbox_page, read_owner_inbox_item)
from project_deliverable_review import DeliverableReviewError
from task_repository import TaskRepositoryError


READ_OPERATIONS = frozenset({"list", "page", "open"})
WRITE_OPERATIONS = frozenset({"mark", "preview", "confirm"})
MAX_ACTION_BYTES = 4096
_ITEM = re.compile(r"inbox_item_[0-9a-f]{32}\Z")


def _failure(code: str, status: int) -> tuple[dict, int]:
    return {"schema_version": 1, "status": code}, status


def dispatch_owner_inbox(data_dir: Path, operation: str, body: object) -> tuple[dict, int]:
    if operation == "list":
        if body != {}:
            return _failure("invalid", 400)
    elif operation == "page":
        if (not isinstance(body, dict) or set(body) != {"view", "after"}
                or body["view"] not in ("needs_me", "unread", "all")
                or body["after"] is not None and (not isinstance(body["after"], str)
                    or _ITEM.fullmatch(body["after"]) is None)):
            return _failure("invalid", 400)
    elif operation == "open":
        if (not isinstance(body, dict) or set(body) != {"item_id"}
                or not isinstance(body["item_id"], str) or _ITEM.fullmatch(body["item_id"]) is None):
            return _failure("invalid", 400)
    elif operation == "mark":
        if (not isinstance(body, dict) or set(body) != {"item_id", "action", "expected_revision"}
                or not isinstance(body["item_id"], str) or _ITEM.fullmatch(body["item_id"]) is None
                or body["action"] not in ("read", "acknowledge", "dismiss")
                or type(body["expected_revision"]) is not int or not 1 <= body["expected_revision"] <= MAX_RUN_REVISION):
            return _failure("invalid", 400)
    elif operation in ("preview", "confirm"):
        expected = {"item_id", "action", "note", "affected_slots"}
        if operation == "confirm":
            expected.add("confirmation_id")
        if (not isinstance(body, dict) or set(body) != expected
                or not isinstance(body["item_id"], str) or _ITEM.fullmatch(body["item_id"]) is None):
            return _failure("invalid", 400)
    else:
        return _failure("invalid", 400)
    try:
        if operation == "list":
            result = read_inbox(data_dir)
        elif operation == "page":
            result = read_inbox_page(data_dir, view=body["view"], after=body["after"])
        elif operation == "open":
            result = read_owner_inbox_item(data_dir, body["item_id"])
        elif operation == "preview":
            result = preview_result_review_item(data_dir, body["item_id"], body["action"],
                                                body["note"], body["affected_slots"])
        elif operation == "confirm":
            result = confirm_result_review_item(data_dir, body["item_id"], body["action"],
                                                body["note"], body["affected_slots"],
                                                body["confirmation_id"])
        else:
            result = mark_item(data_dir, body["item_id"], action=body["action"],
                               expected_revision=body["expected_revision"])
        return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
                "status": "ready", "data": result}, 200
    except OwnerInboxError as exc:
        code = str(exc).rsplit(".", 1)[-1]
        if code == "invalid":
            return _failure("invalid", 400)
        if code == "unavailable":
            return _failure("unavailable", 404)
        if code in {"stale", "capacity"}:
            return _failure(code, 409)
        return _failure("unavailable", 503)
    except DeliverableReviewError as exc:
        code = str(exc).rsplit(".", 1)[-1]
        if code in {"request_invalid", "confirmation_invalid"}:
            return _failure("invalid", 400)
        if code in {"incomplete", "stale", "confirmation_conflict", "capacity", "project_unavailable"}:
            return _failure(code, 409)
        return _failure("unavailable", 503)
    except (TaskRepositoryError, sqlite3.Error, OSError):
        return _failure("unavailable", 503)
