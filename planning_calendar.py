"""Narrow, read-only Calendar planning capability for canonical Mentat Tasks.

This module intentionally does not know how Calendar credentials work, and it
does not write to Calendar.  Its caller supplies a freshly read primary-
Calendar window for each link action.  The only durable mutation here is an
exact-revision update to a Task's already-canonical ``calendar_links`` list.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
import re
import unicodedata
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from task_planning import TaskPlanningError, normalize_task_planning
from task_repository import (
    TaskRepositoryConflict,
    TaskRepositoryError,
    TaskRepositoryValidationError,
    TaskSnapshot,
    read_authoritative_task_snapshot,
    replace_authoritative_task,
)


CALENDAR_ID = "primary"
MAXIMUM_CALENDAR_EVENTS = 250
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_EVENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


class PlanningCalendarError(RuntimeError):
    """A bounded failure in the named Calendar planning capability."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CalendarWindow:
    week_start: str
    timezone: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    start: str
    end: str
    all_day: bool

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "start": self.start,
            "end": self.end,
            "all_day": self.all_day,
        }


@dataclass(frozen=True)
class CalendarMutation:
    action: str
    task: TaskSnapshot


def _safe_text(value: object, *, maximum: int, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    normalized = " ".join(value.split()).strip()
    if not normalized or len(normalized) > maximum or any(
        unicodedata.category(character).startswith("C") for character in normalized
    ):
        return fallback
    return normalized


def _calendar_identifier(value: object) -> str:
    if not isinstance(value, str) or _EVENT_ID.fullmatch(value) is None:
        raise PlanningCalendarError("planning.calendar_event_invalid")
    return value


def calendar_window(value: object) -> CalendarWindow:
    """Validate one explicit Sunday-to-Sunday Calendar window request."""

    if not isinstance(value, Mapping) or set(value) != {"week_start", "timezone"}:
        raise PlanningCalendarError("planning.calendar_window_invalid")
    week_start = value.get("week_start")
    timezone_name = value.get("timezone")
    if (
        not isinstance(week_start, str)
        or not isinstance(timezone_name, str)
        or week_start.strip() != week_start
        or timezone_name.strip() != timezone_name
        or len(timezone_name) > 80
    ):
        raise PlanningCalendarError("planning.calendar_window_invalid")
    try:
        start_day = date.fromisoformat(week_start)
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        raise PlanningCalendarError("planning.calendar_window_invalid") from None
    if _DATE.fullmatch(week_start) is None or start_day.weekday() != 6:
        raise PlanningCalendarError("planning.calendar_window_invalid")
    start = datetime.combine(start_day, time.min, tzinfo=zone)
    return CalendarWindow(
        week_start=week_start,
        timezone=timezone_name,
        start=start,
        end=start + timedelta(days=7),
    )


def _portable_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise PlanningCalendarError("planning.calendar_event_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise PlanningCalendarError("planning.calendar_event_invalid") from None
    if parsed.tzinfo is None:
        raise PlanningCalendarError("planning.calendar_event_invalid")
    return parsed


def _date_value(value: object) -> date:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise PlanningCalendarError("planning.calendar_event_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise PlanningCalendarError("planning.calendar_event_invalid") from None


def _public_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _event_from_source(value: object, window: CalendarWindow) -> CalendarEvent:
    if not isinstance(value, Mapping):
        raise PlanningCalendarError("planning.calendar_event_invalid")
    if value.get("status") == "cancelled":
        raise PlanningCalendarError("planning.calendar_event_invalid")
    identifier = _calendar_identifier(value.get("id"))
    all_day = value.get("all_day")
    if type(all_day) is not bool:
        raise PlanningCalendarError("planning.calendar_event_invalid")
    title = _safe_text(value.get("title"), maximum=160, fallback="Calendar event")
    if all_day:
        start_day = _date_value(value.get("start"))
        end_day = _date_value(value.get("end"))
        if end_day <= start_day:
            raise PlanningCalendarError("planning.calendar_event_invalid")
        start = datetime.combine(start_day, time.min, tzinfo=window.start.tzinfo)
        end = datetime.combine(end_day, time.min, tzinfo=window.start.tzinfo)
        public_start, public_end = start_day.isoformat(), end_day.isoformat()
    else:
        start = _portable_datetime(value.get("start")).astimezone(window.start.tzinfo)
        end = _portable_datetime(value.get("end")).astimezone(window.start.tzinfo)
        if end <= start:
            raise PlanningCalendarError("planning.calendar_event_invalid")
        public_start, public_end = _public_timestamp(start), _public_timestamp(end)
    if start >= window.end or end <= window.start:
        raise PlanningCalendarError("planning.calendar_event_invalid")
    return CalendarEvent(identifier, title, public_start, public_end, all_day)


def _window_label(window: CalendarWindow) -> str:
    first = window.start.date()
    final = window.end.date() - timedelta(days=1)
    if first.year == final.year and first.month == final.month:
        return f"{first.strftime('%B')} {first.day}\u2013{final.day}, {first.year}"
    if first.year == final.year:
        return f"{first.strftime('%b')} {first.day}\u2013{final.strftime('%b')} {final.day}, {first.year}"
    return f"{first.strftime('%b')} {first.day}, {first.year}\u2013{final.strftime('%b')} {final.day}, {final.year}"


def calendar_window_projection(request: object, source: object) -> dict[str, object]:
    """Project one bounded fresh primary-Calendar week with no write surface.

    ``source`` is deliberately a provider result, not a browser payload.  It
    must attest to a connected, read-only read of the fixed primary Calendar.
    Local fallback rows are presentation-only and are never linkable.
    """

    window = calendar_window(request)
    if not isinstance(source, Mapping):
        raise PlanningCalendarError("planning.calendar_unavailable")
    if (
        source.get("source") != "google"
        or source.get("auth") != "connected"
        or source.get("calendar") != CALENDAR_ID
        or source.get("read_only") is not True
    ):
        raise PlanningCalendarError("planning.calendar_unavailable")
    source_window = source.get("window")
    source_timezone = source.get("timezone")
    if (
        not isinstance(source_window, Mapping)
        or not isinstance(source_timezone, Mapping)
        or source_timezone.get("id") != window.timezone
    ):
        raise PlanningCalendarError("planning.calendar_unavailable")
    try:
        source_start = _portable_datetime(source_window.get("start")).astimezone(window.start.tzinfo)
        source_end = _portable_datetime(source_window.get("end")).astimezone(window.start.tzinfo)
    except PlanningCalendarError as exc:
        raise PlanningCalendarError("planning.calendar_unavailable") from exc
    if source_start != window.start or source_end != window.end:
        raise PlanningCalendarError("planning.calendar_unavailable")
    items = source.get("items")
    if not isinstance(items, list) or len(items) > MAXIMUM_CALENDAR_EVENTS:
        raise PlanningCalendarError("planning.calendar_unavailable")
    try:
        events = [_event_from_source(item, window) for item in items]
    except PlanningCalendarError as exc:
        # Provider payload malformation is an unavailable read, never a
        # browser-input validation result.
        raise PlanningCalendarError("planning.calendar_unavailable") from exc
    if len({event.id for event in events}) != len(events):
        raise PlanningCalendarError("planning.calendar_unavailable")
    events.sort(key=lambda item: (item.start, item.end, item.title.casefold(), item.id))
    return {
        "schema_version": 1,
        "calendar_id": CALENDAR_ID,
        "week_start": window.week_start,
        "week_end": window.end.date().isoformat(),
        "timezone": window.timezone,
        "label": _window_label(window),
        "events": [event.public() for event in events],
        "event_count": len(events),
        "read_only": True,
    }


def calendar_event_from_fresh_window(
    request: object,
    event_id: object,
    load_fresh_window: Callable[[CalendarWindow], object],
) -> CalendarEvent:
    """Re-read and resolve exactly one event from a visible primary window."""

    window = calendar_window(request)
    identifier = _calendar_identifier(event_id)
    projection = calendar_window_projection(
        {"week_start": window.week_start, "timezone": window.timezone},
        load_fresh_window(window),
    )
    matches = [item for item in projection["events"] if item["id"] == identifier]
    if len(matches) != 1:
        raise PlanningCalendarError("planning.calendar_event_unavailable")
    event = matches[0]
    return CalendarEvent(
        id=str(event["id"]),
        title=str(event["title"]),
        start=str(event["start"]),
        end=str(event["end"]),
        all_day=bool(event["all_day"]),
    )


def _link_intent(value: object) -> tuple[int, str, CalendarWindow]:
    if not isinstance(value, Mapping) or set(value) != {
        "expected_revision", "event_id", "week_start", "timezone"
    }:
        raise PlanningCalendarError("planning.calendar_link_invalid")
    revision = value.get("expected_revision")
    if type(revision) is not int or revision < 1:
        raise PlanningCalendarError("planning.calendar_link_invalid")
    return revision, _calendar_identifier(value.get("event_id")), calendar_window({
        "week_start": value.get("week_start"), "timezone": value.get("timezone"),
    })


def _unlink_intent(value: object) -> tuple[int, str]:
    if not isinstance(value, Mapping) or set(value) != {
        "expected_revision", "calendar_id", "event_id"
    }:
        raise PlanningCalendarError("planning.calendar_unlink_invalid")
    revision = value.get("expected_revision")
    if (
        type(revision) is not int
        or revision < 1
        or value.get("calendar_id") != CALENDAR_ID
    ):
        raise PlanningCalendarError("planning.calendar_unlink_invalid")
    return revision, _calendar_identifier(value.get("event_id"))


def _task_snapshot(data_dir: Path, task_id: object, expected_revision: int) -> TaskSnapshot:
    if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
        raise PlanningCalendarError("planning.task_invalid")
    try:
        snapshot = read_authoritative_task_snapshot(Path(data_dir), task_id)
    except TaskRepositoryConflict as exc:
        if exc.code == "task_repository.not_found":
            raise PlanningCalendarError("planning.task_not_found") from exc
        raise PlanningCalendarError("planning.unavailable") from exc
    except TaskRepositoryError as exc:
        raise PlanningCalendarError("planning.unavailable") from exc
    if snapshot.revision != expected_revision:
        raise PlanningCalendarError("planning.task_conflict")
    return snapshot


def _replace(data_dir: Path, candidate: Mapping[str, Any], expected_revision: int) -> TaskSnapshot:
    try:
        return replace_authoritative_task(
            Path(data_dir), candidate, expected_revision=expected_revision
        )
    except TaskRepositoryConflict as exc:
        if exc.code == "task_repository.not_found":
            raise PlanningCalendarError("planning.task_not_found") from exc
        raise PlanningCalendarError("planning.task_conflict") from exc
    except (TaskRepositoryError, TaskRepositoryValidationError) as exc:
        raise PlanningCalendarError("planning.unavailable") from exc


def _mark_updated(candidate: dict[str, Any]) -> None:
    candidate["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _calendar_links(task: Mapping[str, Any]) -> list[dict[str, Any]]:
    links = task.get("calendar_links", [])
    try:
        normalized = normalize_task_planning({"calendar_links": links})
    except TaskPlanningError as exc:
        raise PlanningCalendarError("planning.task_invalid") from exc
    return deepcopy(normalized["calendar_links"])


def link_calendar_event(
    data_dir: Path,
    task_id: object,
    intent: object,
    load_fresh_window: Callable[[CalendarWindow], object],
) -> CalendarMutation:
    """Link one freshly re-read primary event at an exact Task revision.

    The only changed field is ``calendar_links``.  In particular, Calendar
    start/end values never create or overwrite a Task scheduled block.
    """

    expected_revision, event_id, window = _link_intent(intent)
    event = calendar_event_from_fresh_window(
        {"week_start": window.week_start, "timezone": window.timezone},
        event_id,
        load_fresh_window,
    )
    snapshot = _task_snapshot(Path(data_dir), task_id, expected_revision)
    candidate = deepcopy(snapshot.document)
    links = _calendar_links(candidate)
    fresh_link = {
        "calendar_id": CALENDAR_ID,
        "event_id": event.id,
        "label": event.title,
    }
    matching = [
        index for index, link in enumerate(links)
        if link.get("calendar_id") == CALENDAR_ID and link.get("event_id") == event.id
    ]
    if len(matching) > 1:
        raise PlanningCalendarError("planning.task_invalid")
    if matching:
        if links[matching[0]] == fresh_link:
            return CalendarMutation("calendar_link", snapshot)
        links[matching[0]] = fresh_link
    else:
        links.append(fresh_link)
    candidate["calendar_links"] = links
    _mark_updated(candidate)
    if candidate.get("scheduled_block") != snapshot.document.get("scheduled_block"):
        raise PlanningCalendarError("planning.calendar_schedule_changed")
    return CalendarMutation("calendar_link", _replace(Path(data_dir), candidate, expected_revision))


def unlink_calendar_event(
    data_dir: Path,
    task_id: object,
    intent: object,
) -> CalendarMutation:
    """Unlink one primary event at the Task's exact current revision."""

    expected_revision, event_id = _unlink_intent(intent)
    snapshot = _task_snapshot(Path(data_dir), task_id, expected_revision)
    candidate = deepcopy(snapshot.document)
    links = _calendar_links(candidate)
    retained = [
        link for link in links
        if not (link.get("calendar_id") == CALENDAR_ID and link.get("event_id") == event_id)
    ]
    if len(retained) == len(links):
        raise PlanningCalendarError("planning.calendar_link_not_found")
    candidate["calendar_links"] = retained
    _mark_updated(candidate)
    return CalendarMutation("calendar_unlink", _replace(Path(data_dir), candidate, expected_revision))
