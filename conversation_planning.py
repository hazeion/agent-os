"""Safe Project and Task context for durable Mentat Conversations."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import json
import re
import sqlite3
import unicodedata
from typing import Any, Mapping

from conversation_repository import (
    ConversationPlanningAssociation,
    ConversationRecord,
    ConversationRepositoryConflict,
)
from task_planning import PLANNING_STATES, task_is_deferred, workflow_stage
from task_repository import TaskRepository, TaskRepositoryConflict, TaskRepositoryError


MAX_PROJECTS = 256
MAX_ATTENTION = 50
MAX_TASK_PAGE = 50
_PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_CURSOR = re.compile(r"[A-Za-z0-9_-]{1,512}\Z")
_PROJECT_STATUSES = frozenset({"active", "paused", "archived"})
_ATTENTION_ORDER = (
    "overdue",
    "due_today",
    "review",
    "needs_attention",
    "planned_today",
    "due_soon",
)
_ATTENTION_RANK = {reason: index for index, reason in enumerate(_ATTENTION_ORDER)}
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


class ConversationPlanningError(RuntimeError):
    """A bounded planning-context operation failed."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProjectSummary:
    id: str
    name: str
    status: str
    revision: int

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class ProjectRegistry:
    projects: tuple[ProjectSummary, ...]
    by_id: Mapping[str, ProjectSummary]
    name_to_id: Mapping[str, str]


def _text(value: object, *, maximum: int, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ConversationPlanningError(code)
    return value


def validate_project_name(value: object) -> str:
    return _text(value, maximum=120, code="planning.project_name_invalid")


def validate_task_title(value: object) -> str:
    return _text(value, maximum=160, code="planning.task_title_invalid")


def project_registry(payload: object) -> ProjectRegistry:
    """Validate the complete Project identity document and safe alias map."""

    if not isinstance(payload, list) or len(payload) > MAX_PROJECTS:
        raise ConversationPlanningError("planning.projects_invalid")
    projects: list[ProjectSummary] = []
    by_id: dict[str, ProjectSummary] = {}
    name_to_id: dict[str, str] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            raise ConversationPlanningError("planning.projects_invalid")
        identifier = _text(
            raw.get("id"), maximum=80, code="planning.projects_invalid"
        )
        if _PROJECT_ID.fullmatch(identifier) is None or identifier in by_id:
            raise ConversationPlanningError("planning.projects_invalid")
        name = _text(
            raw.get("name"), maximum=120, code="planning.projects_invalid"
        )
        status = _text(
            raw.get("status"), maximum=32, code="planning.projects_invalid"
        )
        if status not in _PROJECT_STATUSES:
            raise ConversationPlanningError("planning.projects_invalid")
        revision = raw.get("revision", 1)
        if type(revision) is not int or revision < 1:
            raise ConversationPlanningError("planning.projects_invalid")
        project = ProjectSummary(identifier, name, status, revision)
        by_id[identifier] = project
        projects.append(project)
        aliases: list[str] = [name]
        for key in ("aliases", "legacy_names"):
            values = raw.get(key, [])
            if values is None:
                values = []
            if not isinstance(values, list) or len(values) > 12:
                raise ConversationPlanningError("planning.projects_invalid")
            aliases.extend(
                _text(item, maximum=120, code="planning.projects_invalid")
                for item in values
            )
        for alias in aliases:
            folded = alias.casefold()
            owner = name_to_id.get(folded)
            if owner is not None and owner != identifier:
                raise ConversationPlanningError("planning.projects_ambiguous")
            name_to_id[folded] = identifier
    projects.sort(key=lambda item: (item.status == "archived", item.name.casefold(), item.id))
    return ProjectRegistry(tuple(projects), by_id, name_to_id)


def _attention_reasons(task: Mapping[str, Any], today: date) -> tuple[str, ...]:
    reasons: list[str] = []
    completed = task["status"] == "completed"
    due_value = task.get("due_date")
    due = date.fromisoformat(due_value) if isinstance(due_value, str) else None
    if not completed and due is not None and due < today:
        reasons.append("overdue")
    if not completed and due == today:
        reasons.append("due_today")
    if task.get("review_required") or task.get("planning_state") == "review":
        reasons.append("review")
    if task.get("needs_attention"):
        reasons.append("needs_attention")
    if task.get("planned_for_today"):
        reasons.append("planned_today")
    if not completed and due is not None and today < due <= today + timedelta(days=7):
        reasons.append("due_soon")
    return tuple(reason for reason in _ATTENTION_ORDER if reason in reasons)


def _task_is_blocked(task: Mapping[str, Any], all_tasks: Mapping[str, Mapping[str, Any]]) -> bool:
    """A Task is blocked only when a present prerequisite is not Done."""

    for dependency_id in task.get("depends_on") or []:
        dependency = all_tasks.get(str(dependency_id))
        if dependency is None or workflow_stage(dependency) != "done":
            return True
    return False


def _task_public(
    task: Mapping[str, Any],
    registry: ProjectRegistry,
    today: date,
) -> dict[str, Any] | None:
    # PT-1A makes this immutable ID authoritative. The name lookup is retained
    # only to read pre-cutover fixtures; live Task authority always supplies it.
    project_id = task.get("project_id")
    if not isinstance(project_id, str):
        project_id = registry.name_to_id.get(str(task["project"]).casefold())
    if project_id is None:
        return None
    project = registry.by_id[project_id]
    planning_state = task.get("planning_state")
    if planning_state is not None and planning_state not in PLANNING_STATES:
        raise ConversationPlanningError("planning.tasks_invalid")
    return {
        "id": str(task["id"]),
        "title": str(task["title"]),
        "project_id": project.id,
        "project_name": project.name,
        "status": str(task["status"]),
        "priority": str(task["priority"]),
        "due_date": task.get("due_date"),
        "planned_for_today": bool(task.get("planned_for_today", False)),
        "planning_state": planning_state,
        "workflow_stage": workflow_stage(task),
        "deferred": task_is_deferred(task),
        "blocked": False,
        "revision": 1,
        "needs_attention": bool(task["needs_attention"]),
        "review_required": bool(task["review_required"]),
        "attention_reasons": list(_attention_reasons(task, today)),
        "updated_at": str(task["updated_at"]),
    }


def safe_task_projection(
    task: Mapping[str, Any],
    registry: ProjectRegistry,
    *,
    today: date,
) -> dict[str, Any]:
    projected = _task_public(task, registry, today)
    if projected is None:
        raise ConversationPlanningError("planning.project_mismatch")
    return projected


def _safe_tasks(
    connection: sqlite3.Connection,
    registry: ProjectRegistry,
    today: date,
) -> list[dict[str, Any]]:
    try:
        repository = TaskRepository(connection)
        tasks = repository.list_tasks()
    except TaskRepositoryError as exc:
        raise ConversationPlanningError("planning.tasks_unavailable") from exc
    task_map = {str(task["id"]): task for task in tasks}
    revisions = {
        str(row["id"]): int(row["revision"])
        for row in connection.execute("SELECT id, revision FROM mentat_tasks")
    }
    if set(task_map) != set(revisions):
        raise ConversationPlanningError("planning.tasks_unavailable")
    public: list[dict[str, Any]] = []
    for task in tasks:
        projected = _task_public(task, registry, today)
        if projected is not None:
            projected["revision"] = revisions[str(task["id"])]
            projected["blocked"] = _task_is_blocked(task, task_map)
            public.append(projected)
    return public


def planning_overview(
    connection: sqlite3.Connection,
    projects_payload: object,
    *,
    today: date,
) -> dict[str, Any]:
    registry = project_registry(projects_payload)
    tasks = _safe_tasks(connection, registry, today)
    attention = [task for task in tasks if task["attention_reasons"]]
    attention.sort(
        key=lambda task: (
            min(_ATTENTION_RANK[reason] for reason in task["attention_reasons"]),
            task["due_date"] is None,
            task["due_date"] or "9999-12-31",
            _PRIORITY_RANK[task["priority"]],
            task["title"].casefold(),
            task["id"],
        )
    )
    return {
        "today": today.isoformat(),
        "projects": [project.public() for project in registry.projects],
        "project_count": len(registry.projects),
        "attention": attention[:MAX_ATTENTION],
        "attention_count": len(attention),
        "truncated": len(attention) > MAX_ATTENTION,
    }


def _cursor_digest(project_id: str) -> str:
    return hashlib.sha256(project_id.encode("utf-8")).hexdigest()


def _task_order_key(task: Mapping[str, Any]) -> tuple[int, str, str]:
    return (1 if task["status"] == "completed" else 0, str(task["updated_at"]), str(task["id"]))


def _encode_cursor(project_id: str, task: Mapping[str, Any]) -> str:
    rank, updated_at, identifier = _task_order_key(task)
    raw = json.dumps(
        [_cursor_digest(project_id), rank, updated_at, identifier],
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(project_id: str, cursor: object) -> tuple[int, str, str]:
    if not isinstance(cursor, str) or _CURSOR.fullmatch(cursor) is None:
        raise ConversationPlanningError("planning.cursor_invalid")
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        if base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != cursor:
            raise ValueError("noncanonical")
        value = json.loads(raw.decode("ascii"))
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConversationPlanningError("planning.cursor_invalid") from exc
    if (
        not isinstance(value, list)
        or len(value) != 4
        or value[0] != _cursor_digest(project_id)
        or type(value[1]) is not int
        or value[1] not in {0, 1}
        or not isinstance(value[2], str)
        or not isinstance(value[3], str)
        or _TASK_ID.fullmatch(value[3]) is None
    ):
        raise ConversationPlanningError("planning.cursor_invalid")
    return value[1], value[2], value[3]


def planning_task_page(
    connection: sqlite3.Connection,
    projects_payload: object,
    *,
    project_id: str,
    cursor: str | None,
    today: date,
) -> dict[str, Any]:
    if not isinstance(project_id, str) or _PROJECT_ID.fullmatch(project_id) is None:
        raise ConversationPlanningError("planning.project_id_invalid")
    registry = project_registry(projects_payload)
    project = registry.by_id.get(project_id)
    if project is None:
        raise ConversationPlanningError("planning.project_not_found")
    tasks = [
        task
        for task in _safe_tasks(connection, registry, today)
        if task["project_id"] == project_id
    ]
    tasks.sort(key=lambda task: (_task_order_key(task)[0], _task_order_key(task)[1], _task_order_key(task)[2]), reverse=False)
    # Keep newest records first within each terminal rank.
    tasks.sort(key=lambda task: task["updated_at"], reverse=True)
    tasks.sort(key=lambda task: 1 if task["status"] == "completed" else 0)
    if cursor is not None:
        boundary = _decode_cursor(project_id, cursor)
        start = next((index + 1 for index, task in enumerate(tasks) if _task_order_key(task) == boundary), None)
        if start is None:
            raise ConversationPlanningError("planning.cursor_invalid")
        tasks = tasks[start:]
    page = tasks[:MAX_TASK_PAGE]
    return {
        "project": project.public(),
        "tasks": page,
        "count": len(page),
        "next_cursor": _encode_cursor(project_id, page[-1]) if len(tasks) > MAX_TASK_PAGE else None,
    }


def planning_task_locator(
    connection: sqlite3.Connection,
    projects_payload: object,
    *,
    task_id: str,
    today: date,
) -> dict[str, Any]:
    """Resolve one canonical Task and its unique safe Project projection."""

    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise ConversationPlanningError("planning.task_id_invalid")
    registry = project_registry(projects_payload)
    try:
        snapshot = TaskRepository(connection).get(task_id)
        task = snapshot.document
    except TaskRepositoryConflict as exc:
        if exc.code == "task_repository.not_found":
            raise ConversationPlanningError("planning.task_not_found") from exc
        raise ConversationPlanningError("planning.tasks_unavailable") from exc
    except TaskRepositoryError as exc:
        raise ConversationPlanningError("planning.tasks_unavailable") from exc
    projected = safe_task_projection(task, registry, today=today)
    projected["revision"] = snapshot.revision
    all_tasks = {item["id"]: item for item in TaskRepository(connection).list_tasks()}
    projected["blocked"] = _task_is_blocked(task, all_tasks)
    project = registry.by_id.get(projected["project_id"])
    if project is None:
        raise ConversationPlanningError("planning.project_mismatch")
    return {"project": project.public(), "task": projected}


def validate_association_targets(
    connection: sqlite3.Connection,
    registry: ProjectRegistry,
    project_id: str,
    task_id: str | None,
) -> None:
    if project_id not in registry.by_id:
        raise ConversationRepositoryConflict("conversation.project_unavailable")
    if task_id is None:
        return
    try:
        task = TaskRepository(connection).get(task_id).document
    except TaskRepositoryError as exc:
        raise ConversationRepositoryConflict("conversation.task_unavailable") from exc
    resolved = task.get("project_id")
    if not isinstance(resolved, str):
        resolved = registry.name_to_id.get(str(task["project"]).casefold())
    if resolved != project_id:
        raise ConversationRepositoryConflict("conversation.project_mismatch")


def planning_context_projection(
    connection: sqlite3.Connection,
    projects_payload: object,
    conversation: ConversationRecord,
    association: ConversationPlanningAssociation | None,
    *,
    today: date,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "conversation_id": conversation.id,
        "conversation_revision": conversation.revision,
        "association": None,
        "project": None,
        "task": None,
        "state": "empty",
    }
    if association is None:
        return base
    base["association"] = {
        "project_id": association.project_id,
        "task_id": association.task_id,
    }
    try:
        registry = project_registry(projects_payload)
    except ConversationPlanningError:
        base["state"] = "project_unavailable"
        return base
    project = registry.by_id.get(association.project_id)
    if project is None:
        base["state"] = "project_unavailable"
        return base
    base["project"] = project.public()
    if association.task_id is None:
        base["state"] = "ready"
        return base
    try:
        task = TaskRepository(connection).get(association.task_id).document
    except TaskRepositoryError:
        base["state"] = "task_unavailable"
        return base
    resolved = task.get("project_id")
    if not isinstance(resolved, str):
        resolved = registry.name_to_id.get(str(task["project"]).casefold())
    if resolved != association.project_id:
        base["state"] = "project_mismatch"
        return base
    public_task = _task_public(task, registry, today)
    if public_task is None:
        base["state"] = "project_mismatch"
        return base
    base["task"] = public_task
    base["state"] = "ready"
    return base


__all__ = [
    "ConversationPlanningError",
    "MAX_ATTENTION",
    "MAX_PROJECTS",
    "MAX_TASK_PAGE",
    "planning_context_projection",
    "planning_overview",
    "planning_task_page",
    "planning_task_locator",
    "project_registry",
    "safe_task_projection",
    "validate_project_name",
    "validate_task_title",
    "validate_association_targets",
]
