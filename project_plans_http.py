"""Named owner-only bridge for Project plan preparation, never dispatch."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from agent_registry import AgentRegistryError
from project_context import ProjectContextError
from project_plans import ProjectPlanError, normalize_owner_plan, publish_owner_plan, read_plan_version, read_project_plan
from project_repository import ProjectRepositoryError
from task_repository import TaskRepositoryError


READ_OPERATIONS = frozenset({"project", "version"})
WRITE_OPERATIONS = frozenset({"publish"})
MAX_ACTION_BYTES = 32 * 1024
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_VERSION = re.compile(r"plan_version_[0-9a-f]{32}\Z")
_FIELDS = {
    "project": {"project_id"},
    "version": {"project_id", "version_id"},
    "publish": {"project_id", "expected_project_revision", "expected_plan_revision", "title", "nodes"},
}
_CONFLICTS = {"capacity", "project_changed", "context_unavailable", "context_changed",
              "revision_conflict", "agent_unavailable", "task_changed", "input_changed",
              "grant_changed", "agent_changed"}


def _failure(code: str, status: int) -> tuple[dict, int]:
    return {"schema_version": 1, "status": code}, status


def dispatch_project_plans(data_dir: Path, operation: str, body: object) -> tuple[dict, int]:
    if (operation not in READ_OPERATIONS | WRITE_OPERATIONS or not isinstance(body, dict)
            or set(body) != _FIELDS[operation]):
        return _failure("invalid", 400)
    project_id = body["project_id"]
    if not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None:
        return _failure("invalid", 400)
    if operation == "version" and (not isinstance(body["version_id"], str) or _VERSION.fullmatch(body["version_id"]) is None):
        return _failure("invalid", 400)
    if operation == "publish":
        if (type(body["expected_project_revision"]) is not int or not 1 <= body["expected_project_revision"] <= 9007199254740991
                or type(body["expected_plan_revision"]) is not int or not 0 <= body["expected_plan_revision"] <= 32):
            return _failure("invalid", 400)
        try:
            normalize_owner_plan(body["title"], body["nodes"])
        except ProjectPlanError as exc:
            return _failure("capacity" if str(exc) == "project_plan.capacity" else "invalid", 400)
    try:
        if operation == "project":
            result = read_project_plan(data_dir, project_id)
        elif operation == "version":
            result = read_plan_version(data_dir, project_id, body["version_id"])
        else:
            result = publish_owner_plan(
                data_dir, project_id, body["title"], body["nodes"],
                expected_project_revision=body["expected_project_revision"],
                expected_plan_revision=body["expected_plan_revision"],
            )
        return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
                "status": "ready", "data": result}, 200
    except ProjectPlanError as exc:
        code = str(exc).rsplit(".", 1)[-1]
        if code in {"invalid", "request_invalid"}:
            return _failure("invalid", 400)
        if code == "version_unavailable":
            return _failure(code, 404)
        return _failure(code if code in _CONFLICTS else "unavailable", 409 if code in _CONFLICTS else 503)
    except ProjectRepositoryError as exc:
        return _failure("project_unavailable", 404) if exc.code == "project_repository.not_found" else _failure("unavailable", 503)
    except TaskRepositoryError as exc:
        return _failure("task_changed", 409) if exc.code == "task_repository.not_found" else _failure("unavailable", 503)
    except (ProjectContextError, AgentRegistryError, sqlite3.Error, OSError):
        return _failure("unavailable", 503)
