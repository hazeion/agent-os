from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from planning_calendar import (
    PlanningCalendarError,
    calendar_window_projection,
    link_calendar_event,
    unlink_calendar_event,
)
from task_repository import ensure_task_sqlite_authority, read_authoritative_task_snapshot


WEEK_START = "2026-09-06"
TIMEZONE = "America/Los_Angeles"


def task(identifier: str = "task_calendar") -> dict:
    return {
        "id": identifier,
        "title": "Calendar Task",
        "description": "",
        "project": "Mentat",
        "status": "todo",
        "priority": "medium",
        "assignee": None,
        "due_date": None,
        "source": "test",
        "tags": [],
        "review_required": False,
        "needs_attention": False,
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
        "completed_at": None,
        "scheduled_block": {
            "start": "2026-09-08T10:00:00-07:00",
            "end": "2026-09-08T11:00:00-07:00",
            "label": "Keep this block",
            "timezone": TIMEZONE,
        },
    }


def source(*, items: list[dict] | None = None, **overrides: object) -> dict:
    value = {
        "source": "google",
        "auth": "connected",
        "calendar": "primary",
        "read_only": True,
        "window": {
            "start": "2026-09-06T00:00:00-07:00",
            "end": "2026-09-13T00:00:00-07:00",
        },
        "timezone": {"id": TIMEZONE},
        "items": items if items is not None else [
            {
                "id": "event_focus",
                "title": "Fresh provider title",
                "start": "2026-09-08T13:00:00-07:00",
                "end": "2026-09-08T14:00:00-07:00",
                "all_day": False,
            }
        ],
    }
    value.update(overrides)
    return value


class PlanningCalendarTests(unittest.TestCase):
    def root(self, temporary: str) -> Path:
        root = Path(temporary)
        (root / "tasks.json").write_text(json.dumps([task()]), encoding="utf-8")
        ensure_task_sqlite_authority(root, required_source_mode=None)
        return root

    def request(self) -> dict:
        return {"week_start": WEEK_START, "timezone": TIMEZONE}

    def test_window_projection_is_primary_connected_read_only_and_bounded(self):
        projection = calendar_window_projection(self.request(), source(items=[
            {
                "id": "event_all_day", "title": "All day", "start": "2026-09-09",
                "end": "2026-09-10", "all_day": True,
            },
            {
                "id": "event_focus", "title": "Provider title", "start": "2026-09-08T13:00:00-07:00",
                "end": "2026-09-08T14:00:00-07:00", "all_day": False,
            },
        ]))

        self.assertEqual(set(projection), {
            "schema_version", "calendar_id", "week_start", "week_end", "timezone",
            "label", "events", "event_count", "read_only",
        })
        self.assertEqual(projection["calendar_id"], "primary")
        self.assertTrue(projection["read_only"])
        self.assertEqual(projection["event_count"], 2)
        self.assertEqual(projection["events"][0], {
            "id": "event_focus", "title": "Provider title",
            "start": "2026-09-08T20:00:00Z", "end": "2026-09-08T21:00:00Z", "all_day": False,
        })
        self.assertEqual(projection["events"][1]["start"], "2026-09-09")
        self.assertNotIn("description", str(projection))

        for invalid in (
            source(auth="not_connected"),
            source(source="local"),
            source(calendar="other"),
            source(read_only=False),
            source(window={"start": "2026-09-07T00:00:00-07:00", "end": "2026-09-14T00:00:00-07:00"}),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(PlanningCalendarError, "calendar_unavailable"):
                    calendar_window_projection(self.request(), invalid)

    def test_link_re_reads_provider_event_and_leaves_schedule_untouched(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            reads = []

            def fresh(window):
                reads.append((window.week_start, window.timezone))
                return source()

            mutation = link_calendar_event(root, "task_calendar", {
                "expected_revision": 1,
                "event_id": "event_focus",
                **self.request(),
            }, fresh)
            current = read_authoritative_task_snapshot(root, "task_calendar")

        self.assertEqual(reads, [(WEEK_START, TIMEZONE)])
        self.assertEqual(mutation.action, "calendar_link")
        self.assertEqual(mutation.task.revision, 2)
        self.assertEqual(current.revision, 2)
        self.assertEqual(current.document["calendar_links"], [{
            "calendar_id": "primary", "event_id": "event_focus", "label": "Fresh provider title",
        }])
        self.assertEqual(current.document["scheduled_block"], task()["scheduled_block"])

    def test_link_rejects_a_stale_task_after_the_fresh_provider_read(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            reads = []

            def fresh(window):
                reads.append(window.week_start)
                return source()

            with self.assertRaisesRegex(PlanningCalendarError, "planning.task_conflict"):
                link_calendar_event(root, "task_calendar", {
                    "expected_revision": 2,
                    "event_id": "event_focus",
                    **self.request(),
                }, fresh)
            current = read_authoritative_task_snapshot(root, "task_calendar")

        self.assertEqual(reads, [WEEK_START])
        self.assertEqual(current.revision, 1)
        self.assertNotIn("calendar_links", current.document)

    def test_unlink_is_exact_revision_and_does_not_touch_calendar(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            link_calendar_event(root, "task_calendar", {
                "expected_revision": 1,
                "event_id": "event_focus",
                **self.request(),
            }, lambda _window: source())
            mutation = unlink_calendar_event(root, "task_calendar", {
                "expected_revision": 2,
                "calendar_id": "primary",
                "event_id": "event_focus",
            })
            current = read_authoritative_task_snapshot(root, "task_calendar")
            with self.assertRaisesRegex(PlanningCalendarError, "planning.calendar_link_not_found"):
                unlink_calendar_event(root, "task_calendar", {
                    "expected_revision": 3,
                    "calendar_id": "primary",
                    "event_id": "event_focus",
                })

        self.assertEqual(mutation.action, "calendar_unlink")
        self.assertEqual(current.revision, 3)
        self.assertEqual(current.document.get("calendar_links"), [])
        self.assertEqual(current.document["scheduled_block"], task()["scheduled_block"])

    def test_unlink_binds_the_fixed_primary_calendar_identity(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            link_calendar_event(root, "task_calendar", {
                "expected_revision": 1,
                "event_id": "event_focus",
                **self.request(),
            }, lambda _window: source())
            with self.assertRaisesRegex(PlanningCalendarError, "calendar_unlink_invalid"):
                unlink_calendar_event(root, "task_calendar", {
                    "expected_revision": 2,
                    "calendar_id": "other",
                    "event_id": "event_focus",
                })
            current = read_authoritative_task_snapshot(root, "task_calendar")

        self.assertEqual(current.revision, 2)
        self.assertEqual(current.document["calendar_links"][0]["calendar_id"], "primary")

    def test_link_requires_a_fresh_event_in_the_exact_visible_window(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with self.assertRaisesRegex(PlanningCalendarError, "calendar_event_unavailable"):
                link_calendar_event(root, "task_calendar", {
                    "expected_revision": 1,
                    "event_id": "event_missing",
                    **self.request(),
                }, lambda _window: source())
            current = read_authoritative_task_snapshot(root, "task_calendar")

        self.assertEqual(current.revision, 1)
        self.assertNotIn("calendar_links", current.document)


if __name__ == "__main__":
    unittest.main()
