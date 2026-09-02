"""One bounded, durable task-creation tool for an exact Codex Task Run.

The App Server callback is only a transport signal.  This module owns the
authorization chain and creates the Task with its one-use receipt in the same
SQLite transaction.  It accepts no model-selected IDs.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Mapping
from uuid import uuid4

from agent_runtime import RuntimeCapability
from mentat_db import SCHEMA_VERSION, connect, schema_signature_state
from private_state import private_state_lock
from project_repository import ProjectRepository, ProjectRepositoryError
from run_repository import RunRepository, RunRepositoryConflict, RunRepositoryError, runtime_binding_digest
from task_repository import (
    TaskRepository,
    TaskRepositoryConflict,
    TaskRepositoryError,
    TaskRepositoryValidationError,
    normalize_task_document,
)


CODEX_TASK_CREATE_CAPABILITY = RuntimeCapability.TASK_CREATE.value
CALLBACK_ACCEPT_WAIT_SECONDS = 3.0
_RUN_ID = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_RUNTIME_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_CALL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ACTIVE_RUN_STATUSES = frozenset({"starting", "running", "waiting"})


class CodexTaskCreationError(RuntimeError):
    """A private, bounded failure that is rendered as a fixed tool result."""


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _proof(task: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(task).encode("ascii")).hexdigest()


def _request_digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(value).encode("ascii")).hexdigest()


def _text(value: object, *, maximum: int, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if (
        not isinstance(value, str)
        or value.strip() != value
        or (required and not value)
        or len(value) > maximum
        or "\x00" in value
        or any(ord(character) < 32 and character not in "\n\t" for character in value)
    ):
        raise CodexTaskCreationError("input_invalid")
    return value


def _arguments(raw: object) -> dict[str, object]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16 * 1024:
        raise CodexTaskCreationError("input_invalid")
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CodexTaskCreationError("input_invalid") from exc
    allowed = {
        "title", "description", "acceptance_criteria", "reason",
        "assign_to_self", "depends_on_origin",
    }
    if not isinstance(value, dict) or set(value) - allowed or "title" not in value:
        raise CodexTaskCreationError("input_invalid")
    result: dict[str, object] = {"title": _text(value.get("title"), maximum=160, required=True)}
    description = _text(value.get("description"), maximum=2_000)
    reason = _text(value.get("reason"), maximum=500)
    if description is not None:
        result["description"] = description
    if reason is not None:
        result["reason"] = reason
    criteria = value.get("acceptance_criteria", [])
    if (
        not isinstance(criteria, list)
        or len(criteria) > 8
    ):
        raise CodexTaskCreationError("input_invalid")
    normalized_criteria = [_text(item, maximum=240, required=True) for item in criteria]
    if len(set(normalized_criteria)) != len(normalized_criteria):
        raise CodexTaskCreationError("input_invalid")
    if normalized_criteria:
        result["acceptance_criteria"] = normalized_criteria
    for name in ("assign_to_self", "depends_on_origin"):
        current = value.get(name, False)
        if type(current) is not bool:
            raise CodexTaskCreationError("input_invalid")
        if current:
            result[name] = current
    return result


class CodexTaskCreationService:
    """Durable preauthorization, runtime binding, and one-use creation."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    @staticmethod
    def _require_schema(connection: sqlite3.Connection) -> None:
        if SCHEMA_VERSION < 22 or schema_signature_state(connection, SCHEMA_VERSION) != "expected":
            raise CodexTaskCreationError("unavailable")
        names = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"mentat_codex_task_create_grants", "mentat_codex_task_create_receipts"}.issubset(names):
            raise CodexTaskCreationError("unavailable")

    def preauthorize_claimed(
        self,
        *,
        connection: sqlite3.Connection,
        run_id: str,
        task_id: str,
        task_revision: int,
        project_id: str,
        agent_id: str,
        runtime_binding_digest: str,
    ) -> bool:
        """Persist a grant in the claimed-dispatch transaction before I/O."""

        if (
            _RUN_ID.fullmatch(run_id or "") is None
            or _TASK_ID.fullmatch(task_id or "") is None
            or type(task_revision) is not int or task_revision < 1
            or _PROJECT_ID.fullmatch(project_id or "") is None
            or _AGENT_ID.fullmatch(agent_id or "") is None
            or _SHA256.fullmatch(runtime_binding_digest or "") is None
        ):
            return False
        try:
            if not connection.in_transaction:
                return False
            self._require_schema(connection)
            run = RunRepository(connection).get_run(run_id)
            task = TaskRepository(connection).get(task_id)
            project = ProjectRepository(connection).get(project_id)
            if (
                run.source != "task_dispatch"
                or run.dispatch_state != "submitting"
                or run.task_id != task_id
                or run.task_revision != task_revision
                or run.agent_id != agent_id
                or run.runtime_type != "codex"
                or run.runtime_binding_digest != runtime_binding_digest
                or task.revision != task_revision
                or task.document.get("project_id") != project_id
                or task.document.get("assigned_agent_id") != agent_id
                or project.document.get("status") != "active"
            ):
                return False
            row = connection.execute(
                "SELECT origin_task_id, origin_task_revision, project_id, agent_id, runtime_binding_digest "
                "FROM mentat_codex_task_create_grants WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            expected = (task_id, task_revision, project_id, agent_id, runtime_binding_digest)
            if row is None:
                connection.execute(
                    "INSERT INTO mentat_codex_task_create_grants (run_id, origin_task_id, origin_task_revision, project_id, agent_id, runtime_binding_digest, state, thread_id, turn_id, runtime_run_ref, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'preauthorized', NULL, NULL, NULL, ?, ?)",
                    (run_id, *expected, _now(), _now()),
                )
            elif tuple(row) != expected:
                return False
            return True
        except Exception:
            return False

    def has_preauthorization(self, *, run_id: str) -> bool:
        if _RUN_ID.fullmatch(run_id or "") is None:
            return False
        try:
            with private_state_lock(self.data_dir):
                connection = connect(self.data_dir)
                try:
                    self._require_schema(connection)
                    row = connection.execute(
                        "SELECT state FROM mentat_codex_task_create_grants WHERE run_id = ?",
                        (run_id,),
                    ).fetchone()
                    return row is not None and row["state"] == "preauthorized"
                finally:
                    connection.close()
        except Exception:
            return False

    def bind_thread(self, *, run_id: str, thread_id: str) -> bool:
        if _RUN_ID.fullmatch(run_id or "") is None or _RUNTIME_ID.fullmatch(thread_id or "") is None:
            return False
        return self._advance_grant(run_id, state="preauthorized", thread_id=thread_id, turn_id=None)

    def arm(self, *, run_id: str, thread_id: str, turn_id: str) -> bool:
        if (
            _RUN_ID.fullmatch(run_id or "") is None
            or _RUNTIME_ID.fullmatch(thread_id or "") is None
            or _RUNTIME_ID.fullmatch(turn_id or "") is None
        ):
            return False
        return self._advance_grant(run_id, state="thread_bound", thread_id=thread_id, turn_id=turn_id)

    def _advance_grant(self, run_id: str, *, state: str, thread_id: str, turn_id: str | None) -> bool:
        try:
            with private_state_lock(self.data_dir):
                connection = connect(self.data_dir)
                try:
                    self._require_schema(connection)
                    connection.execute("BEGIN IMMEDIATE")
                    if state == "preauthorized":
                        changed = connection.execute(
                            "UPDATE mentat_codex_task_create_grants SET state = 'thread_bound', thread_id = ?, updated_at = ? "
                            "WHERE run_id = ? AND state = 'preauthorized'",
                            (thread_id, _now(), run_id),
                        ).rowcount
                    else:
                        changed = connection.execute(
                            "UPDATE mentat_codex_task_create_grants SET state = 'armed', turn_id = ?, runtime_run_ref = ?, updated_at = ? "
                            "WHERE run_id = ? AND state = 'thread_bound' AND thread_id = ?",
                            (turn_id, f"{thread_id}:{turn_id}", _now(), run_id, thread_id),
                        ).rowcount
                    connection.commit()
                    return changed == 1
                except Exception:
                    connection.rollback()
                    return False
                finally:
                    connection.close()
        except Exception:
            return False

    def handle(self, request: Mapping[str, object]) -> Mapping[str, object]:
        """Answer one App Server callback after its exact Run becomes durable."""

        try:
            if set(request) != {"thread_id", "turn_id", "call_id", "tool", "arguments"} or request.get("tool") != "mentat_tasks_create_inbox":
                raise CodexTaskCreationError("callback_invalid")
            thread_id = request.get("thread_id")
            turn_id = request.get("turn_id")
            call_id = request.get("call_id")
            if (
                _RUNTIME_ID.fullmatch(thread_id or "") is None
                or _RUNTIME_ID.fullmatch(turn_id or "") is None
                or _CALL_ID.fullmatch(call_id or "") is None
            ):
                raise CodexTaskCreationError("callback_invalid")
            arguments = _arguments(request.get("arguments"))
        except CodexTaskCreationError:
            return {"success": False, "message": "Task creation request is invalid."}
        deadline = time.monotonic() + CALLBACK_ACCEPT_WAIT_SECONDS
        while True:
            result = self._create_once(
                thread_id=str(thread_id), turn_id=str(turn_id), call_id=str(call_id), arguments=arguments,
            )
            if result != "not_ready" or time.monotonic() >= deadline:
                return (
                    {"success": True, "message": "Inbox Task created."}
                    if result == "created" else
                    {"success": False, "message": "Task creation is not available for this Run."}
                )
            time.sleep(0.025)

    def _create_once(
        self,
        *,
        thread_id: str,
        turn_id: str,
        call_id: str,
        arguments: Mapping[str, object],
    ) -> str:
        try:
            with private_state_lock(self.data_dir):
                connection = connect(self.data_dir)
                try:
                    self._require_schema(connection)
                    connection.execute("BEGIN IMMEDIATE")
                    grant = connection.execute(
                        "SELECT * FROM mentat_codex_task_create_grants WHERE thread_id = ? AND turn_id = ? AND state = 'armed'",
                        (thread_id, turn_id),
                    ).fetchone()
                    if grant is None:
                        connection.rollback()
                        return "invalid"
                    run_id = str(grant["run_id"])
                    request_digest = _request_digest(arguments)
                    receipt = connection.execute(
                        "SELECT * FROM mentat_codex_task_create_receipts WHERE origin_run_id = ?",
                        (run_id,),
                    ).fetchone()
                    if receipt is not None:
                        if (
                            receipt["thread_id"] == thread_id
                            and receipt["turn_id"] == turn_id
                            and receipt["call_id"] == call_id
                            and receipt["request_digest"] == request_digest
                        ):
                            created = TaskRepository(connection).get(str(receipt["created_task_id"]))
                            if (
                                created.revision == int(receipt["created_task_revision"])
                                and _proof(created.document) == receipt["result_proof_digest"]
                            ):
                                connection.commit()
                                return "created"
                        connection.rollback()
                        return "invalid"
                    run = RunRepository(connection).get_run(run_id)
                    if (
                        run.source != "task_dispatch"
                        or run.runtime_type != "codex"
                        or run.runtime_run_ref != grant["runtime_run_ref"]
                        or run.dispatch_state != "accepted"
                    ):
                        connection.rollback()
                        return "not_ready" if run.dispatch_state == "submitting" else "invalid"
                    if run.status not in _ACTIVE_RUN_STATUSES:
                        connection.rollback()
                        return "invalid"
                    agent = connection.execute(
                        "SELECT a.revision, a.runtime_config_id, a.capabilities_json, c.runtime_type, c.runtime_agent_ref, a.name "
                        "FROM mentat_agents AS a JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id WHERE a.id = ?",
                        (grant["agent_id"],),
                    ).fetchone()
                    if agent is None:
                        connection.rollback()
                        return "invalid"
                    capabilities = json.loads(str(agent["capabilities_json"]))
                    if (
                        not isinstance(capabilities, list)
                        or CODEX_TASK_CREATE_CAPABILITY not in capabilities
                        or agent["runtime_type"] != "codex"
                        or runtime_binding_digest(
                            agent_id=str(grant["agent_id"]), runtime_type="codex",
                            runtime_config_id=str(agent["runtime_config_id"]),
                            runtime_agent_ref=str(agent["runtime_agent_ref"]), capabilities=capabilities,
                        ) != grant["runtime_binding_digest"]
                        or run.agent_id != grant["agent_id"]
                        or run.runtime_binding_digest != grant["runtime_binding_digest"]
                    ):
                        connection.rollback()
                        return "invalid"
                    task_repository = TaskRepository(connection)
                    origin = task_repository.get(str(grant["origin_task_id"]))
                    project_repository = ProjectRepository(connection)
                    project = project_repository.get(str(grant["project_id"]))
                    if (
                        origin.revision != int(grant["origin_task_revision"])
                        or run.task_id != grant["origin_task_id"]
                        or run.task_revision != origin.revision
                        or origin.document.get("project_id") != grant["project_id"]
                        or origin.document.get("assigned_agent_id") != grant["agent_id"]
                        or project.document.get("status") != "active"
                    ):
                        connection.rollback()
                        return "invalid"
                    created = self._new_task(
                        arguments=arguments,
                        project=project.document,
                        origin_task_id=str(grant["origin_task_id"]),
                        agent_id=str(grant["agent_id"]),
                        agent_name=str(agent["name"]),
                    )
                    stored = task_repository.insert(created)
                    proof = _proof(stored.document)
                    connection.execute(
                        "INSERT INTO mentat_codex_task_create_receipts (origin_run_id, thread_id, turn_id, call_id, request_digest, origin_task_id, project_id, agent_id, created_task_id, created_task_revision, result_proof_digest, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (run_id, thread_id, turn_id, call_id, request_digest, grant["origin_task_id"], grant["project_id"], grant["agent_id"], stored.document["id"], stored.revision, proof, _now()),
                    )
                    connection.commit()
                    return "created"
                except (sqlite3.Error, ValueError, ProjectRepositoryError, RunRepositoryError, TaskRepositoryError, CodexTaskCreationError):
                    connection.rollback()
                    return "invalid"
                finally:
                    connection.close()
        except Exception:
            return "invalid"

    @staticmethod
    def _new_task(
        *,
        arguments: Mapping[str, object],
        project: Mapping[str, object],
        origin_task_id: str,
        agent_id: str,
        agent_name: str,
    ) -> dict[str, object]:
        assigned = arguments.get("assign_to_self") is True
        now = _now()
        candidate: dict[str, object] = {
            "id": f"task_agent_{uuid4().hex}",
            "title": str(arguments["title"]),
            "description": str(arguments.get("description") or ""),
            "project": str(project["name"]),
            "project_id": str(project["id"]),
            "status": "todo",
            "priority": "medium",
            "assignee": agent_name if assigned else "Operator",
            "due_date": None,
            "source": "agent_tool",
            "tags": [],
            "review_required": False,
            "needs_attention": False,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "workflow_stage": "inbox",
            "planning_state": "inbox",
            "deferred": False,
        }
        if assigned:
            candidate["assigned_agent_id"] = agent_id
        if arguments.get("depends_on_origin") is True:
            candidate["depends_on"] = [origin_task_id]
        if arguments.get("acceptance_criteria"):
            candidate["acceptance_criteria"] = list(arguments["acceptance_criteria"])
        try:
            return normalize_task_document(candidate)
        except TaskRepositoryValidationError as exc:
            raise CodexTaskCreationError("task_invalid") from exc


__all__ = ["CODEX_TASK_CREATE_CAPABILITY", "CodexTaskCreationService"]
