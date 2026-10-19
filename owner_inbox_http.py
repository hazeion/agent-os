"""Fixed private bridge for owner inbox receipts; no source action authority."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from owner_inbox import OwnerInboxError, mark_item, read_inbox
from task_repository import TaskRepositoryError


READ_OPERATIONS = frozenset({"list"})
WRITE_OPERATIONS = frozenset({"mark"})
MAX_ACTION_BYTES = 1024
_ITEM = re.compile(r"inbox_item_[0-9a-f]{32}\Z")


def _failure(code: str, status: int) -> tuple[dict, int]:
    return {"schema_version": 1, "status": code}, status


def dispatch_owner_inbox(data_dir: Path, operation: str, body: object) -> tuple[dict, int]:
    if operation == "list":
        if body != {}:
            return _failure("invalid", 400)
    elif operation == "mark":
        if (not isinstance(body, dict) or set(body) != {"item_id", "action", "expected_revision"}
                or not isinstance(body["item_id"], str) or _ITEM.fullmatch(body["item_id"]) is None
                or body["action"] not in ("read", "acknowledge")
                or type(body["expected_revision"]) is not int or not 1 <= body["expected_revision"] <= 16):
            return _failure("invalid", 400)
    else:
        return _failure("invalid", 400)
    try:
        result = read_inbox(data_dir) if operation == "list" else mark_item(
            data_dir, body["item_id"], action=body["action"], expected_revision=body["expected_revision"],
        )
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
    except (TaskRepositoryError, sqlite3.Error, OSError):
        return _failure("unavailable", 503)
