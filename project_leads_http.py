"""Fixed owner-only bridge for a Project lead selection, never dispatch."""

from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from agent_registry import AgentRegistryError
from project_context import ProjectContextError
from project_leads import ProjectLeadError, read_project_lead, select_project_lead
from project_repository import ProjectRepositoryError
from task_repository import TaskRepositoryError


READ_OPERATIONS = frozenset({"project"})
WRITE_OPERATIONS = frozenset({"select"})
MAX_ACTION_BYTES = 4096
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_TOKEN = re.compile(r"[0-9a-f]{64}\Z")


def _failure(code: str, status: int) -> tuple[dict, int]:
    return {"schema_version": 1, "status": code}, status


def dispatch_project_leads(data_dir: Path, operation: str, body: object) -> tuple[dict, int]:
    expected = {"project_id"} if operation == "project" else {
        "project_id", "agent_id", "expected_project_revision",
        "expected_lead_revision", "selection_token",
    }
    if (operation not in READ_OPERATIONS | WRITE_OPERATIONS or not isinstance(body, dict)
            or set(body) != expected or not isinstance(body.get("project_id"), str)
            or _PROJECT.fullmatch(body["project_id"]) is None):
        return _failure("invalid", 400)
    if operation == "select" and (
            body["agent_id"] is not None and (not isinstance(body["agent_id"], str)
                or _AGENT.fullmatch(body["agent_id"]) is None)
            or type(body["expected_project_revision"]) is not int
            or not 1 <= body["expected_project_revision"] <= 9007199254740991
            or type(body["expected_lead_revision"]) is not int
            or not 0 <= body["expected_lead_revision"] <= 32
            or not isinstance(body["selection_token"], str)
            or _TOKEN.fullmatch(body["selection_token"]) is None):
        return _failure("invalid", 400)
    try:
        if operation == "project":
            result = read_project_lead(data_dir, body["project_id"])
        else:
            result = select_project_lead(
                data_dir, body["project_id"], body["agent_id"],
                expected_project_revision=body["expected_project_revision"],
                expected_lead_revision=body["expected_lead_revision"],
                selection_token=body["selection_token"],
            )
        return {"schema_version": 1, "service": "mentat-local-bridge",
                "runtime": "python", "status": "ready", "data": result}, 200
    except ProjectLeadError as exc:
        code = str(exc).rsplit(".", 1)[-1]
        if code in {"invalid", "request_invalid"}:
            return _failure("invalid", 400)
        if code in {"project_changed", "revision_conflict", "selection_changed",
                    "agent_unavailable", "capacity"}:
            return _failure(code, 409)
        return _failure("unavailable", 503)
    except ProjectRepositoryError as exc:
        return _failure("project_unavailable", 404) if exc.code == "project_repository.not_found" else _failure("unavailable", 503)
    except (AgentRegistryError, TaskRepositoryError, ProjectContextError, sqlite3.Error, OSError):
        return _failure("unavailable", 503)
