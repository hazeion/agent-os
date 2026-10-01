"""Fixed owner-only bridge for preparing Project inputs, never dispatching."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from agent_registry import AgentRegistryError
from project_context import ProjectContextError
from project_repository import ProjectRepositoryError
from project_planning_inputs import (ProjectPlanningInputError,
    normalize_project_input_request, publish_project_input,
    read_project_input_editor, reconcile_project_input_action)
from task_repository import TaskRepositoryError


READ_OPERATIONS = frozenset({"project", "version", "reconcile"})
WRITE_OPERATIONS = frozenset({"publish"})
MAX_ACTION_BYTES = 32768
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_INPUT = re.compile(r"project_input_[0-9a-f]{32}\Z")
_ACTION = re.compile(r"project_input_action_[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_CONFLICTS = frozenset({"capacity", "project_changed", "scope_changed", "lead_changed",
    "context_changed", "revision_conflict", "selection_changed", "file_scope",
    "files_unavailable", "image_limit", "action_conflict"})


def _failure(code: str, status: int) -> tuple[dict, int]:
    return {"schema_version": 1, "status": code}, status


def dispatch_project_planning_inputs(data_dir: Path, operation: str,
                                     body: object) -> tuple[dict, int]:
    if not isinstance(body, dict) or operation not in READ_OPERATIONS | WRITE_OPERATIONS:
        return _failure("invalid", 400)
    if operation == "project" and (set(body) != {"project_id"}
            or not isinstance(body["project_id"], str)
            or _PROJECT.fullmatch(body["project_id"]) is None):
        return _failure("invalid", 400)
    if operation == "version" and (set(body) != {"project_id", "input_id"}
            or not isinstance(body["project_id"], str)
            or _PROJECT.fullmatch(body["project_id"]) is None
            or not isinstance(body["input_id"], str)
            or _INPUT.fullmatch(body["input_id"]) is None):
        return _failure("invalid", 400)
    if operation == "reconcile" and (set(body) != {"project_id", "action_id", "scope_token"}
            or not isinstance(body["project_id"], str)
            or _PROJECT.fullmatch(body["project_id"]) is None
            or not isinstance(body["action_id"], str)
            or _ACTION.fullmatch(body["action_id"]) is None
            or not isinstance(body["scope_token"], str)
            or _HEX64.fullmatch(body["scope_token"]) is None):
        return _failure("invalid", 400)
    if operation == "publish":
        try:
            normalize_project_input_request(body)
        except ProjectPlanningInputError:
            return _failure("invalid", 400)
    try:
        if operation == "project":
            data = read_project_input_editor(data_dir, body["project_id"])
        elif operation == "version":
            data = read_project_input_editor(data_dir, body["project_id"],
                                             version_id=body["input_id"])
        elif operation == "reconcile":
            data = reconcile_project_input_action(data_dir, body["project_id"],
                body["action_id"], body["scope_token"])
        else:
            data = publish_project_input(data_dir, body)
        return {"schema_version": 1, "service": "mentat-local-bridge",
                "runtime": "python", "status": "ready", "data": data}, 200
    except ProjectPlanningInputError as exc:
        code = str(exc).rsplit(".", 1)[-1]
        if code in {"request_invalid"}:
            return _failure("invalid", 400)
        if code == "version_unavailable":
            return _failure(code, 404)
        return _failure(code, 409) if code in _CONFLICTS else _failure("unavailable", 503)
    except ProjectRepositoryError as exc:
        return _failure("project_unavailable", 404) if exc.code == "project_repository.not_found" else _failure("unavailable", 503)
    except (ProjectContextError, AgentRegistryError, TaskRepositoryError,
            sqlite3.Error, OSError):
        return _failure("unavailable", 503)
