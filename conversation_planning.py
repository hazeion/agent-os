"""Safe Project and Task context for durable Mentat Conversations."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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
from task_planning import PLANNING_STATES, TaskPlanningError, normalize_task_planning, task_is_deferred, workflow_stage
from task_repository import TaskRepository, TaskRepositoryConflict, TaskRepositoryError


MAX_PROJECTS = 256
MAX_ATTENTION = 50
MAX_TASK_PAGE = 50
MAX_TASK_DESCRIPTION_PREVIEW = 280
MAX_DIRECT_DEPENDENCY_ITEMS = 100
MAX_DEPENDENCY_PICKER_PAGE = 50
MAX_DEPENDENCY_PICKER_QUERY = 160
MAX_DEPENDENCY_MAP_NODES = 50
MAX_DEPENDENCY_MAP_EXTERNAL_STUBS = 50
MAX_DEPENDENCY_MAP_EDGES = 250
MAX_DEPENDENCY_MAP_QUERY = 160
MAX_PLANNING_SEARCH_QUERY = 160
MAX_PLANNING_SEARCH_PROJECTS = 25
MAX_PLANNING_SEARCH_TASKS = 25
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
_DEPENDENCY_MAP_VIEWS = frozenset({
    "all", "today", "waiting", "review", "someday", "completed",
})


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


def _task_description_preview(task: Mapping[str, Any]) -> str:
    """Return a bounded, plain-text preview for the Project Task list only."""

    raw = task.get("description")
    if not isinstance(raw, str):
        return ""
    preview = " ".join(raw.split())
    if any(unicodedata.category(character).startswith("C") for character in preview):
        return ""
    if len(preview) > MAX_TASK_DESCRIPTION_PREVIEW:
        preview = preview[: MAX_TASK_DESCRIPTION_PREVIEW - 1].rstrip() + "…"
    return preview


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
    *,
    include_description_preview: bool = False,
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
            if include_description_preview:
                projected["description_preview"] = _task_description_preview(task)
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


def _dependency_picker_query(value: object) -> str:
    """Normalize the optional, display-only dependency-picker query."""

    if value is None:
        return ""
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > MAX_DEPENDENCY_PICKER_QUERY
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ConversationPlanningError("planning.picker_query_invalid")
    return value


def _dependency_map_query(value: object) -> str:
    """Normalize the optional selected-Project map filter without echoing it."""

    if value is None:
        return ""
    if (
        not isinstance(value, str)
        or value.strip() != value
        or len(value) > MAX_DEPENDENCY_MAP_QUERY
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ConversationPlanningError("planning.dependency_map_query_invalid")
    return value


def _planning_search_query(value: object) -> str:
    """Validate one explicit, navigation-only planning search query.

    Search is deliberately not a general text index: descriptions, notes,
    sessions, and other private Task or Project fields never participate.
    """

    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > MAX_PLANNING_SEARCH_QUERY
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ConversationPlanningError("planning.search_query_invalid")
    return value


def _dependency_map_view(value: object) -> str:
    if value is None:
        return "all"
    if not isinstance(value, str) or value not in _DEPENDENCY_MAP_VIEWS:
        raise ConversationPlanningError("planning.dependency_map_view_invalid")
    return value


def _dependency_map_matches(
    task: Mapping[str, Any],
    summary: Mapping[str, Any],
    *,
    query: str,
    view: str,
) -> bool:
    """Apply the existing list filters before the dependency-map node cap."""

    description = task.get("description")
    if not isinstance(description, str):
        raise ConversationPlanningError("planning.tasks_invalid")
    if query and query.lower() not in (
        str(summary["title"]) + "\n" + _task_description_preview(task)
    ).lower():
        return False
    if view == "all":
        return True
    if view == "today":
        return task.get("planned_for_today") is True
    if view == "waiting":
        return summary["workflow_stage"] == "waiting"
    if view == "review":
        return summary["workflow_stage"] == "review"
    if view == "someday":
        return task_is_deferred(task)
    return summary["workflow_stage"] == "done"


def _dependency_picker_cursor_digest(task_id: str, query: str) -> str:
    return hashlib.sha256(
        (task_id + "\x00" + query).encode("utf-8")
    ).hexdigest()


def _dependency_picker_boundary(task: Mapping[str, Any]) -> str:
    """Bind a compact cursor to the exact last sortable picker result."""

    raw = json.dumps(
        [task["project_name"], task["title"], task["id"]],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _encode_dependency_picker_cursor(
    task_id: str, query: str, task: Mapping[str, Any]
) -> str:
    raw = json.dumps(
        [
            _dependency_picker_cursor_digest(task_id, query),
            task["id"],
            _dependency_picker_boundary(task),
        ],
        separators=(",", ":"),
    ).encode("ascii")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_dependency_picker_cursor(
    task_id: str, query: str, cursor: object
) -> tuple[str, str]:
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
        or len(value) != 3
        or value[0] != _dependency_picker_cursor_digest(task_id, query)
        or not isinstance(value[1], str)
        or _TASK_ID.fullmatch(value[1]) is None
        or not isinstance(value[2], str)
        or re.fullmatch(r"[0-9a-f]{64}", value[2]) is None
    ):
        raise ConversationPlanningError("planning.cursor_invalid")
    return value[1], value[2]


def _dependency_task_summary(
    task: Mapping[str, Any],
    registry: ProjectRegistry,
    all_tasks: Mapping[str, Mapping[str, Any]],
    *,
    today: date,
) -> dict[str, Any]:
    """Return the intentionally narrow relationship/picker Task projection."""

    projected = safe_task_projection(task, registry, today=today)
    projected["blocked"] = _task_is_blocked(task, all_tasks)
    return {
        key: projected[key]
        for key in (
            "id",
            "title",
            "project_id",
            "project_name",
            "workflow_stage",
            "blocked",
        )
    }


def _dependency_task_sort_key(task: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(task["project_name"]).casefold(),
        str(task["title"]).casefold(),
        str(task["id"]),
    )


def planning_navigation_search(
    connection: sqlite3.Connection,
    projects_payload: object,
    *,
    query: object,
    today: date,
) -> dict[str, Any]:
    """Return bounded, title-only navigation matches from canonical planning data.

    The intentionally small projection makes this useful only for choosing a
    Project or Task to open.  It cannot disclose a Task description, Project
    metadata, a local path, a Run, or any runtime/provider state.
    """

    normalized_query = _planning_search_query(query)
    needle = normalized_query.casefold()
    registry = project_registry(projects_payload)

    all_projects = [
        {"id": project.id, "title": project.name, "type": "project"}
        for project in registry.projects
        if needle in project.name.casefold()
    ]
    all_projects.sort(key=lambda item: (item["title"].casefold(), item["id"]))

    # _safe_tasks validates the entire canonical Task projection and verifies
    # every retained Task has an unambiguous Project association before its
    # title can be included in this otherwise minimal result.
    all_tasks = [
        {"id": task["id"], "title": task["title"], "type": "task"}
        for task in _safe_tasks(connection, registry, today)
        if needle in str(task["title"]).casefold()
    ]
    all_tasks.sort(key=lambda item: (item["title"].casefold(), item["id"]))

    projects = all_projects[:MAX_PLANNING_SEARCH_PROJECTS]
    tasks = all_tasks[:MAX_PLANNING_SEARCH_TASKS]
    return {
        "query": normalized_query,
        "projects": projects,
        "project_count": len(projects),
        "tasks": tasks,
        "task_count": len(tasks),
        "truncated": (
            len(all_projects) > len(projects)
            or len(all_tasks) > len(tasks)
        ),
    }


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
        for task in _safe_tasks(
            connection, registry, today, include_description_preview=True
        )
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


def planning_task_detail_locator(
    connection: sqlite3.Connection,
    projects_payload: object,
    *,
    task_id: str,
    today: date,
) -> dict[str, Any]:
    """Return a bounded, selected-Task-only editor projection.

    This deliberately remains separate from overview, list, and Conversation
    projections: descriptions and editable planning fields do not belong in
    ambient browser state.
    """

    located = planning_task_locator(
        connection, projects_payload, task_id=task_id, today=today
    )
    task = TaskRepository(connection).get(task_id).document
    description = task.get("description", "")
    if not isinstance(description, str) or len(description) > 4000 or any(
        unicodedata.category(character).startswith("C") and character not in "\n\t"
        for character in description
    ):
        raise ConversationPlanningError("planning.task_invalid")
    tags = task.get("tags", [])
    if (
        not isinstance(tags, list)
        or len(tags) > 12
        or any(not isinstance(tag, str) or not tag.strip() or len(tag) > 48 or any(unicodedata.category(character).startswith("C") for character in tag) for tag in tags)
    ):
        raise ConversationPlanningError("planning.task_invalid")
    subtasks = task.get("subtasks", [])
    if not isinstance(subtasks, list) or len(subtasks) > 200:
        raise ConversationPlanningError("planning.task_invalid")
    safe_subtasks = []
    for item in subtasks:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "title", "completed", "rank"}
            or not isinstance(item["id"], str)
            or _TASK_ID.fullmatch(item["id"]) is None
            or not isinstance(item["title"], str)
            or not item["title"].strip()
            or len(item["title"]) > 240
            or any(unicodedata.category(character).startswith("C") for character in item["title"])
            or type(item["completed"]) is not bool
            or type(item["rank"]) is not int
            or not 0 <= item["rank"] <= 1000000
        ):
            raise ConversationPlanningError("planning.task_invalid")
        safe_subtasks.append(dict(item))
    recurrence = task.get("recurrence")
    estimated_minutes = task.get("estimated_minutes")
    if estimated_minutes is not None and (type(estimated_minutes) is not int or not 1 <= estimated_minutes <= 10080):
        raise ConversationPlanningError("planning.task_invalid")
    scheduled_block = task.get("scheduled_block")
    reminders = task.get("reminders", [])
    calendar_links = task.get("calendar_links", [])
    note_links = task.get("note_links", [])
    planning_metadata = {
        "reminders": reminders,
        "calendar_links": calendar_links,
        "note_links": note_links,
    }
    if scheduled_block is not None:
        planning_metadata["scheduled_block"] = scheduled_block
    try:
        normalized_metadata = normalize_task_planning(planning_metadata)
        normalized_recurrence = normalize_task_planning({"recurrence": recurrence}).get("recurrence") if recurrence is not None else None
    except TaskPlanningError as exc:
        raise ConversationPlanningError("planning.task_invalid") from exc
    if normalized_recurrence != recurrence:
        raise ConversationPlanningError("planning.task_invalid")
    assignee = task.get("assigned_agent_id")
    if assignee is not None and (not isinstance(assignee, str) or _TASK_ID.fullmatch(assignee) is None):
        raise ConversationPlanningError("planning.task_invalid")
    # Task authority accepts the full Python ISO-8601 input grammar for stored
    # planning datetimes. Public detail output deliberately has one portable
    # UTC spelling, so a valid legacy offset (including offset seconds) cannot
    # make the Node boundary reject an otherwise canonical Task.
    def public_datetime(value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

    public_metadata = dict(normalized_metadata)
    if isinstance(public_metadata.get("scheduled_block"), dict):
        public_metadata["scheduled_block"] = {
            **public_metadata["scheduled_block"],
            "start": public_datetime(public_metadata["scheduled_block"]["start"]),
            "end": public_datetime(public_metadata["scheduled_block"]["end"]),
        }
    public_metadata["reminders"] = [
        {
            **reminder,
            "at": public_datetime(reminder["at"]),
            **({"notified_at": public_datetime(reminder["notified_at"])} if "notified_at" in reminder else {}),
        }
        for reminder in normalized_metadata["reminders"]
    ]
    located["task"] = {
        **located["task"],
        "description": description,
        "tags": list(tags),
        "estimated_minutes": estimated_minutes,
        "scheduled_block": public_metadata.get("scheduled_block"),
        "recurrence": normalized_recurrence,
        "reminders": public_metadata["reminders"],
        "subtasks": safe_subtasks,
        "calendar_links": public_metadata["calendar_links"],
        "note_links": public_metadata["note_links"],
        "assigned_agent_id": assignee,
    }
    return located


def _dependency_snapshot(
    connection: sqlite3.Connection,
    projects_payload: object,
    *,
    task_id: str,
    today: date,
) -> tuple[ProjectRegistry, dict[str, Mapping[str, Any]], Mapping[str, Any], int]:
    """Load one bounded canonical Task graph for dependency-only readers."""

    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise ConversationPlanningError("planning.task_id_invalid")
    registry = project_registry(projects_payload)
    try:
        repository = TaskRepository(connection)
        snapshot = repository.get(task_id)
        tasks = repository.list_tasks()
    except TaskRepositoryConflict as exc:
        if exc.code == "task_repository.not_found":
            raise ConversationPlanningError("planning.task_not_found") from exc
        raise ConversationPlanningError("planning.tasks_unavailable") from exc
    except TaskRepositoryError as exc:
        raise ConversationPlanningError("planning.tasks_unavailable") from exc
    task_map = {str(task["id"]): task for task in tasks}
    selected = task_map.get(task_id)
    if selected is None or selected != snapshot.document:
        raise ConversationPlanningError("planning.tasks_unavailable")
    # Resolve the selected project here, so a Project mismatch fails closed even
    # when the task has no relationship rows to project below.
    safe_task_projection(selected, registry, today=today)
    return registry, task_map, selected, snapshot.revision


def planning_task_dependencies(
    connection: sqlite3.Connection,
    projects_payload: object,
    *,
    task_id: str,
    today: date,
) -> dict[str, Any]:
    """Project only the selected Task's direct prerequisite and dependent edges."""

    registry, tasks, selected, revision = _dependency_snapshot(
        connection, projects_payload, task_id=task_id, today=today
    )
    dependency_ids = selected.get("depends_on") or []
    if not isinstance(dependency_ids, list) or len(dependency_ids) > MAX_DIRECT_DEPENDENCY_ITEMS:
        raise ConversationPlanningError("planning.tasks_invalid")
    prerequisites: list[dict[str, Any]] = []
    for dependency_id in dependency_ids:
        dependency = tasks.get(str(dependency_id))
        if dependency is None:
            raise ConversationPlanningError("planning.tasks_invalid")
        prerequisites.append(
            _dependency_task_summary(dependency, registry, tasks, today=today)
        )
    dependents = [
        _dependency_task_summary(task, registry, tasks, today=today)
        for task in tasks.values()
        if task_id in (task.get("depends_on") or [])
    ]
    dependents.sort(key=_dependency_task_sort_key)
    return {
        "task_id": task_id,
        "task_revision": revision,
        "prerequisites": prerequisites[:MAX_DIRECT_DEPENDENCY_ITEMS],
        "prerequisite_count": len(prerequisites),
        "prerequisites_truncated": len(prerequisites) > MAX_DIRECT_DEPENDENCY_ITEMS,
        "dependents": dependents[:MAX_DIRECT_DEPENDENCY_ITEMS],
        "dependent_count": len(dependents),
        "dependents_truncated": len(dependents) > MAX_DIRECT_DEPENDENCY_ITEMS,
    }


def planning_dependency_map(
    connection: sqlite3.Connection,
    projects_payload: object,
    *,
    project_id: str,
    query: object = None,
    view: object = None,
    today: date,
) -> dict[str, Any]:
    """Return one bounded, read-only Project dependency-map projection.

    ``nodes`` are Tasks owned by the selected Project.  ``external_stubs`` are
    only the cross-Project endpoints of edges incident to retained nodes.  The
    lists are independently capped before edges are retained, so every visible
    edge always has two visible endpoints and omitted topology is disclosed by
    its exact source totals.
    """

    if not isinstance(project_id, str) or _PROJECT_ID.fullmatch(project_id) is None:
        raise ConversationPlanningError("planning.project_id_invalid")
    registry = project_registry(projects_payload)
    project = registry.by_id.get(project_id)
    if project is None:
        raise ConversationPlanningError("planning.project_not_found")
    normalized_query = _dependency_map_query(query)
    normalized_view = _dependency_map_view(view)
    try:
        tasks = TaskRepository(connection).list_tasks()
    except TaskRepositoryError as exc:
        raise ConversationPlanningError("planning.tasks_unavailable") from exc
    task_map = {str(task["id"]): task for task in tasks}
    if len(task_map) != len(tasks):
        raise ConversationPlanningError("planning.tasks_unavailable")

    summaries = {
        identifier: _dependency_task_summary(task, registry, task_map, today=today)
        for identifier, task in task_map.items()
    }
    selected_all = sorted(
        (
            summary
            for identifier, summary in summaries.items()
            if summary["project_id"] == project_id
            and _dependency_map_matches(
                task_map[identifier],
                summary,
                query=normalized_query,
                view=normalized_view,
            )
        ),
        key=_dependency_task_sort_key,
    )
    nodes = selected_all[:MAX_DEPENDENCY_MAP_NODES]
    node_ids = {node["id"] for node in nodes}

    # The graph edge direction is dependent -> prerequisite.  A cross-Project
    # edge may therefore originate on either side of the selected Project.
    candidate_edges: list[tuple[str, str]] = []
    external_ids: set[str] = set()
    for dependent_id, dependent in task_map.items():
        dependencies = dependent.get("depends_on") or []
        if not isinstance(dependencies, list) or len(dependencies) > MAX_DIRECT_DEPENDENCY_ITEMS:
            raise ConversationPlanningError("planning.tasks_invalid")
        for prerequisite_id in dependencies:
            if not isinstance(prerequisite_id, str) or prerequisite_id not in task_map:
                raise ConversationPlanningError("planning.tasks_invalid")
            if dependent_id not in node_ids and prerequisite_id not in node_ids:
                continue
            other_id = prerequisite_id if dependent_id in node_ids else dependent_id
            other = summaries[other_id]
            if other["project_id"] != project_id:
                external_ids.add(other_id)
            candidate_edges.append((dependent_id, prerequisite_id))

    external_all = sorted(
        (summaries[identifier] for identifier in external_ids),
        key=_dependency_task_sort_key,
    )
    external_stubs = external_all[:MAX_DEPENDENCY_MAP_EXTERNAL_STUBS]
    visible_ids = node_ids | {stub["id"] for stub in external_stubs}
    candidate_edges.sort(
        key=lambda edge: (
            _dependency_task_sort_key(summaries[edge[0]]),
            _dependency_task_sort_key(summaries[edge[1]]),
        )
    )
    edges = [
        {"from_task_id": dependent_id, "to_task_id": prerequisite_id}
        for dependent_id, prerequisite_id in candidate_edges
        if dependent_id in visible_ids and prerequisite_id in visible_ids
    ][:MAX_DEPENDENCY_MAP_EDGES]

    return {
        "project": project.public(),
        "nodes": nodes,
        "node_count": len(nodes),
        "node_total": len(selected_all),
        "nodes_truncated": len(selected_all) > len(nodes),
        "external_stubs": external_stubs,
        "external_stub_count": len(external_stubs),
        "external_stub_total": len(external_all),
        "external_stubs_truncated": len(external_all) > len(external_stubs),
        "edges": edges,
        "edge_count": len(edges),
        "edge_total": len(candidate_edges),
        "edges_truncated": len(candidate_edges) > len(edges),
    }


def planning_dependency_picker(
    connection: sqlite3.Connection,
    projects_payload: object,
    *,
    task_id: str,
    query: object = None,
    cursor: object = None,
    today: date,
) -> dict[str, Any]:
    """Return a bounded, paginated candidate list without asserting eligibility."""

    normalized_query = _dependency_picker_query(query)
    registry, tasks, _selected, _revision = _dependency_snapshot(
        connection, projects_payload, task_id=task_id, today=today
    )
    needle = normalized_query.casefold()
    candidates = []
    for identifier, task in tasks.items():
        if identifier == task_id:
            continue
        summary = _dependency_task_summary(task, registry, tasks, today=today)
        haystack = "\n".join(
            (summary["id"], summary["title"], summary["project_name"])
        ).casefold()
        if not needle or needle in haystack:
            candidates.append(summary)
    candidates.sort(key=_dependency_task_sort_key)
    match_count = len(candidates)
    if cursor is not None:
        cursor_id, cursor_boundary = _decode_dependency_picker_cursor(
            task_id, normalized_query, cursor
        )
        index = next(
            (index for index, item in enumerate(candidates) if item["id"] == cursor_id),
            None,
        )
        if index is None or _dependency_picker_boundary(candidates[index]) != cursor_boundary:
            raise ConversationPlanningError("planning.cursor_invalid")
        candidates = candidates[index + 1 :]
    page = candidates[:MAX_DEPENDENCY_PICKER_PAGE]
    next_cursor = (
        _encode_dependency_picker_cursor(task_id, normalized_query, page[-1])
        if len(candidates) > MAX_DEPENDENCY_PICKER_PAGE
        else None
    )
    return {
        "task_id": task_id,
        "query": normalized_query,
        "candidates": page,
        "candidate_count": len(page),
        "match_count": match_count,
        "next_cursor": next_cursor,
        "truncated": next_cursor is not None,
    }


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
    "MAX_DEPENDENCY_PICKER_PAGE",
    "MAX_DIRECT_DEPENDENCY_ITEMS",
    "MAX_PROJECTS",
    "MAX_TASK_PAGE",
    "planning_context_projection",
    "planning_dependency_picker",
    "planning_overview",
    "planning_task_dependencies",
    "planning_task_page",
    "planning_task_locator",
    "project_registry",
    "safe_task_projection",
    "validate_project_name",
    "validate_task_title",
    "validate_association_targets",
]
