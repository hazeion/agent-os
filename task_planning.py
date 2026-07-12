"""Validation helpers for Mentat-owned personal task planning metadata.

The functions in this module are deliberately storage- and transport-agnostic.
They validate project-owned task JSON and treat Hermes values as opaque
references; they never read or mutate Hermes state.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class TaskPlanningError(ValueError):
    """Raised when optional task-planning metadata is malformed or unsafe."""


PLANNING_STATES = frozenset(
    {"inbox", "planned", "in_progress", "waiting", "review", "someday", "blocked", "done"}
)
DELEGATION_STATES = frozenset(
    {"queued", "running", "needs_input", "blocked", "ready_for_review", "completed", "failed", "cancelled"}
)
SYNC_STATES = frozenset({"pending", "synced", "stale", "error"})
REVIEW_STATES = frozenset({"pending", "accepted", "revision_requested", "blocked"})
RUN_OUTCOMES = frozenset({"completed", "blocked", "failed", "cancelled", "timed_out", "reclaimed"})
RECURRENCE_FREQUENCIES = frozenset({"daily", "weekly", "monthly", "yearly"})
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SAVED_VIEWS = frozenset({"today", "waiting", "review", "someday", "blocked", "completed"})
TASK_PLANNING_FIELDS = frozenset(
    {
        "planned_for_today",
        "manual_rank",
        "estimated_minutes",
        "scheduled_block",
        "recurrence",
        "recurrence_parent_id",
        "reminders",
        "subtasks",
        "depends_on",
        "calendar_links",
        "note_links",
        "planning_state",
        "delegation",
    }
)

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}$")
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")


def _fail(field: str, message: str) -> None:
    raise TaskPlanningError(f"{field}: {message}")


def _object(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(field, "must be an object")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        _fail(field, "must be a boolean")
    return value


def _int(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(field, "must be an integer")
    if not minimum <= value <= maximum:
        _fail(field, f"must be between {minimum} and {maximum}")
    return value


def _text(value: Any, field: str, *, maximum: int, required: bool = True) -> str:
    if not isinstance(value, str):
        _fail(field, "must be text")
    result = value.strip()
    if required and not result:
        _fail(field, "is required")
    if len(result) > maximum:
        _fail(field, f"must be at most {maximum} characters")
    if "\x00" in result:
        _fail(field, "contains an invalid character")
    return result


def _identifier(value: Any, field: str) -> str:
    result = _text(value, field, maximum=160)
    if not _ID_RE.fullmatch(result):
        _fail(field, "must be a logical identifier, not a path")
    return result


def _date(value: Any, field: str) -> str:
    result = _text(value, field, maximum=10)
    try:
        date.fromisoformat(result)
    except ValueError:
        _fail(field, "must be YYYY-MM-DD")
    return result


def _datetime(value: Any, field: str) -> str:
    result = _text(value, field, maximum=40)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError:
        _fail(field, "must be an ISO 8601 date-time")
    if parsed.tzinfo is None:
        _fail(field, "must include a UTC offset")
    return result


def _timezone(value: Any, field: str) -> str:
    result = _text(value, field, maximum=80)
    try:
        ZoneInfo(result)
    except (ZoneInfoNotFoundError, ValueError):
        _fail(field, "must be a valid IANA time zone")
    return result


def _enum(value: Any, field: str, allowed: frozenset[str]) -> str:
    result = _text(value, field, maximum=40).lower()
    if result not in allowed:
        _fail(field, f"must be one of: {', '.join(sorted(allowed))}")
    return result


def _reject_unknown(value: Mapping[str, Any], field: str, allowed: set[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail(field, f"contains unsupported fields: {', '.join(unknown)}")


def _relative_note_path(value: Any, field: str) -> str:
    result = _text(value, field, maximum=500)
    lowered = result.lower()
    parts = result.replace("\\", "/").split("/")
    if (
        result.startswith(("/", "~", "\\"))
        or _DRIVE_PATH_RE.match(result)
        or "\\" in result
        or lowered.startswith(("file:", "obsidian:"))
        or any(part in {"", ".", ".."} for part in parts)
    ):
        _fail(field, "must be a safe vault-relative note path")
    return result


def _normalize_scheduled_block(value: Any) -> dict[str, Any]:
    item = _object(value, "scheduled_block")
    _reject_unknown(item, "scheduled_block", {"start", "end", "label", "timezone"})
    start = _datetime(item.get("start"), "scheduled_block.start")
    end = _datetime(item.get("end"), "scheduled_block.end")
    start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
    if end_dt <= start_dt:
        _fail("scheduled_block.end", "must be later than start")
    result: dict[str, Any] = {"start": start, "end": end}
    if "label" in item:
        result["label"] = _text(item["label"], "scheduled_block.label", maximum=120)
    if "timezone" in item:
        result["timezone"] = _timezone(item["timezone"], "scheduled_block.timezone")
    return result


def _normalize_recurrence(value: Any) -> dict[str, Any]:
    item = _object(value, "recurrence")
    _reject_unknown(item, "recurrence", {"frequency", "interval", "weekdays", "ends_on", "count"})
    frequency = _enum(item.get("frequency"), "recurrence.frequency", RECURRENCE_FREQUENCIES)
    result: dict[str, Any] = {
        "frequency": frequency,
        "interval": _int(item.get("interval", 1), "recurrence.interval", minimum=1, maximum=365),
    }
    if "weekdays" in item:
        if frequency != "weekly":
            _fail("recurrence.weekdays", "is supported only for weekly recurrence")
        weekdays = item["weekdays"]
        if not isinstance(weekdays, list) or not weekdays:
            _fail("recurrence.weekdays", "must be a non-empty list")
        normalized = []
        for index, weekday in enumerate(weekdays):
            day = _text(weekday, f"recurrence.weekdays[{index}]", maximum=3).lower()
            if day not in WEEKDAYS:
                _fail(f"recurrence.weekdays[{index}]", "must be a three-letter weekday")
            if day not in normalized:
                normalized.append(day)
        result["weekdays"] = sorted(normalized, key=WEEKDAYS.index)
    if "ends_on" in item and "count" in item:
        _fail("recurrence", "cannot contain both ends_on and count")
    if "ends_on" in item:
        result["ends_on"] = _date(item["ends_on"], "recurrence.ends_on")
    if "count" in item:
        result["count"] = _int(item["count"], "recurrence.count", minimum=1, maximum=10000)
    return result


def _normalize_reminders(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 20:
        _fail("reminders", "must be a list with at most 20 items")
    result = []
    identifiers = set()
    for index, raw in enumerate(value):
        field = f"reminders[{index}]"
        item = _object(raw, field)
        _reject_unknown(item, field, {"id", "at", "channel", "enabled", "notified_at", "timezone"})
        identifier = _identifier(item.get("id"), f"{field}.id")
        if identifier in identifiers:
            _fail(f"{field}.id", "must be unique")
        identifiers.add(identifier)
        channel = _text(item.get("channel", "browser"), f"{field}.channel", maximum=20).lower()
        if channel != "browser":
            _fail(f"{field}.channel", "only browser notifications are supported")
        normalized: dict[str, Any] = {
            "id": identifier,
            "at": _datetime(item.get("at"), f"{field}.at"),
            "channel": "browser",
            "enabled": _bool(item.get("enabled", True), f"{field}.enabled"),
        }
        if item.get("notified_at") is not None:
            normalized["notified_at"] = _datetime(item["notified_at"], f"{field}.notified_at")
        if item.get("timezone") is not None:
            normalized["timezone"] = _timezone(item["timezone"], f"{field}.timezone")
        result.append(normalized)
    return result


def _normalize_subtasks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 200:
        _fail("subtasks", "must be a list with at most 200 items")
    result = []
    identifiers = set()
    for index, raw in enumerate(value):
        field = f"subtasks[{index}]"
        item = _object(raw, field)
        _reject_unknown(item, field, {"id", "title", "completed", "rank"})
        identifier = _identifier(item.get("id"), f"{field}.id")
        if identifier in identifiers:
            _fail(f"{field}.id", "must be unique")
        identifiers.add(identifier)
        result.append(
            {
                "id": identifier,
                "title": _text(item.get("title"), f"{field}.title", maximum=240),
                "completed": _bool(item.get("completed", False), f"{field}.completed"),
                "rank": _int(item.get("rank", index), f"{field}.rank", minimum=0, maximum=1000000),
            }
        )
    return result


def _normalize_dependencies(value: Any, task_id: str | None) -> list[str]:
    if not isinstance(value, list) or len(value) > 100:
        _fail("depends_on", "must be a list with at most 100 items")
    result = []
    for index, raw in enumerate(value):
        identifier = _identifier(raw, f"depends_on[{index}]")
        if identifier == task_id:
            _fail(f"depends_on[{index}]", "a task cannot depend on itself")
        if identifier not in result:
            result.append(identifier)
    return result


def _normalize_calendar_links(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 20:
        _fail("calendar_links", "must be a list with at most 20 items")
    result = []
    seen = set()
    for index, raw in enumerate(value):
        field = f"calendar_links[{index}]"
        item = _object(raw, field)
        _reject_unknown(item, field, {"calendar_id", "event_id", "label"})
        calendar_id = _identifier(item.get("calendar_id"), f"{field}.calendar_id")
        event_id = _identifier(item.get("event_id"), f"{field}.event_id")
        key = (calendar_id, event_id)
        if key in seen:
            _fail(field, "duplicates an existing calendar link")
        seen.add(key)
        normalized = {"calendar_id": calendar_id, "event_id": event_id}
        if "label" in item:
            normalized["label"] = _text(item["label"], f"{field}.label", maximum=160)
        result.append(normalized)
    return result


def _normalize_note_links(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 50:
        _fail("note_links", "must be a list with at most 50 items")
    result = []
    seen = set()
    for index, raw in enumerate(value):
        field = f"note_links[{index}]"
        item = _object(raw, field)
        _reject_unknown(item, field, {"path", "title"})
        path = _relative_note_path(item.get("path"), f"{field}.path")
        if path in seen:
            _fail(f"{field}.path", "must be unique")
        seen.add(path)
        normalized = {"path": path}
        if "title" in item:
            normalized["title"] = _text(item["title"], f"{field}.title", maximum=240)
        result.append(normalized)
    return result


def _normalize_delegation(value: Any) -> dict[str, Any]:
    item = _object(value, "delegation")
    allowed = {
        "profile_id", "board_id", "kanban_task_id", "run_id", "session_id",
        "state", "sync_state", "review_state", "last_outcome", "summary",
        "latest_question", "attempts", "created_at", "updated_at", "last_synced_at", "reservation_id", "audit",
    }
    _reject_unknown(item, "delegation", allowed)
    if "profile_id" not in item:
        _fail("delegation.profile_id", "is required")
    result: dict[str, Any] = {"profile_id": _identifier(item["profile_id"], "delegation.profile_id")}
    for key in ("board_id", "kanban_task_id", "run_id", "session_id", "reservation_id"):
        if item.get(key) is not None:
            result[key] = _identifier(item[key], f"delegation.{key}")
    if "state" in item:
        result["state"] = _enum(item["state"], "delegation.state", DELEGATION_STATES)
    if "sync_state" in item:
        result["sync_state"] = _enum(item["sync_state"], "delegation.sync_state", SYNC_STATES)
    if "review_state" in item:
        result["review_state"] = _enum(item["review_state"], "delegation.review_state", REVIEW_STATES)
    if "last_outcome" in item:
        result["last_outcome"] = _enum(item["last_outcome"], "delegation.last_outcome", RUN_OUTCOMES)
    if "summary" in item:
        result["summary"] = _text(item["summary"], "delegation.summary", maximum=4000, required=False)
    if "latest_question" in item:
        result["latest_question"] = _text(item["latest_question"], "delegation.latest_question", maximum=2000, required=False)
    if "attempts" in item:
        result["attempts"] = _int(item["attempts"], "delegation.attempts", minimum=0, maximum=1000)
    for key in ("created_at", "updated_at"):
        if item.get(key) is not None:
            result[key] = _datetime(item[key], f"delegation.{key}")
    if item.get("last_synced_at") is not None:
        result["last_synced_at"] = _datetime(item["last_synced_at"], "delegation.last_synced_at")
    if "audit" in item:
        audit = item["audit"]
        if not isinstance(audit, list) or len(audit) > 100:
            _fail("delegation.audit", "must be a list with at most 100 items")
        result["audit"] = []
        for index, raw in enumerate(audit):
            field = f"delegation.audit[{index}]"
            event = _object(raw, field)
            _reject_unknown(event, field, {"at", "actor", "event", "note"})
            normalized_event = {
                "at": _datetime(event.get("at"), f"{field}.at"),
                "actor": _identifier(event.get("actor"), f"{field}.actor"),
                "event": _identifier(event.get("event"), f"{field}.event"),
            }
            if "note" in event:
                normalized_event["note"] = _text(event["note"], f"{field}.note", maximum=500, required=False)
            result["audit"].append(normalized_event)
    return result


def normalize_task_planning(task: Mapping[str, Any]) -> dict[str, Any]:
    """Return a defensive, normalized copy of a task.

    Legacy task objects with none of the optional fields remain unchanged.
    Unknown top-level fields are preserved for forward and existing-data
    compatibility. Nested planning objects reject unknown fields so browser
    input cannot smuggle arbitrary execution or local-path metadata into them.
    """

    source = _object(task, "task")
    result = deepcopy(dict(source))
    task_id = None
    if source.get("id") is not None:
        task_id = _identifier(source["id"], "id")

    if "planned_for_today" in source:
        result["planned_for_today"] = _bool(source["planned_for_today"], "planned_for_today")
    if "manual_rank" in source:
        result["manual_rank"] = _int(source["manual_rank"], "manual_rank", minimum=0, maximum=1000000)
    if "estimated_minutes" in source:
        result["estimated_minutes"] = _int(source["estimated_minutes"], "estimated_minutes", minimum=1, maximum=10080)
    if "scheduled_block" in source:
        result["scheduled_block"] = _normalize_scheduled_block(source["scheduled_block"])
    if "recurrence" in source:
        result["recurrence"] = _normalize_recurrence(source["recurrence"])
    if "recurrence_parent_id" in source:
        result["recurrence_parent_id"] = _identifier(source["recurrence_parent_id"], "recurrence_parent_id")
    if "reminders" in source:
        result["reminders"] = _normalize_reminders(source["reminders"])
    if "subtasks" in source:
        result["subtasks"] = _normalize_subtasks(source["subtasks"])
    if "depends_on" in source:
        result["depends_on"] = _normalize_dependencies(source["depends_on"], task_id)
    if "calendar_links" in source:
        result["calendar_links"] = _normalize_calendar_links(source["calendar_links"])
    if "note_links" in source:
        result["note_links"] = _normalize_note_links(source["note_links"])
    if "planning_state" in source:
        result["planning_state"] = _enum(source["planning_state"], "planning_state", PLANNING_STATES)
    if "delegation" in source:
        result["delegation"] = _normalize_delegation(source["delegation"])
    return result


def validate_task_planning(task: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Validate a task without raising, matching Mentat's server helper style."""

    try:
        return normalize_task_planning(task), None
    except TaskPlanningError as exc:
        return None, str(exc)


def task_matches_saved_view(task: Mapping[str, Any], view: str, *, on_date: date | None = None) -> bool:
    """Return whether a validated task belongs in a built-in personal view."""

    normalized = normalize_task_planning(task)
    selected_view = _text(view, "view", maximum=20).lower()
    if selected_view not in SAVED_VIEWS:
        _fail("view", f"must be one of: {', '.join(sorted(SAVED_VIEWS))}")
    state = normalized.get("planning_state")
    status = str(normalized.get("status", "")).strip().lower().replace(" ", "_")
    delegation_state = (normalized.get("delegation") or {}).get("state")
    completed = state == "done" or status in {"done", "completed"}
    if selected_view == "completed":
        return completed
    if completed:
        return False
    if selected_view == "today":
        if normalized.get("planned_for_today") is True:
            return True
        block = normalized.get("scheduled_block")
        if block:
            local_day = on_date or datetime.now().astimezone().date()
            return datetime.fromisoformat(block["start"].replace("Z", "+00:00")).date() == local_day
        return False
    if selected_view == "review":
        return state == "review" or delegation_state == "ready_for_review" or normalized.get("review_required") is True
    if selected_view == "waiting":
        return state == "waiting" or delegation_state in {"queued", "running", "needs_input"}
    return state == selected_view


def task_dependencies_satisfied(task: Mapping[str, Any], completed_task_ids: set[str]) -> bool:
    """Return true when every referenced dependency is in the caller's completed set."""

    normalized = normalize_task_planning(task)
    completed = {_identifier(value, "completed_task_ids") for value in completed_task_ids}
    return all(identifier in completed for identifier in normalized.get("depends_on", []))
