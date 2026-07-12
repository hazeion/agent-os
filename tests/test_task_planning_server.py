from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server


class TaskPlanningServerTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, payload) -> None:
        (root / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def test_create_accepts_valid_personal_planning_metadata(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", [{"id": "project-mentat", "name": "Mentat"}])
            self.write_json(root, "tasks.json", [])
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.create_task(
                    {
                        "title": "Plan tomorrow",
                        "project": "Mentat",
                        "planned_for_today": True,
                        "manual_rank": 10,
                        "estimated_minutes": 30,
                        "planning_state": "planned",
                        "subtasks": [{"id": "outline", "title": "Outline", "completed": False}],
                    }
                )

        self.assertEqual(status, 201)
        self.assertTrue(payload["task"]["planned_for_today"])
        self.assertEqual(payload["task"]["estimated_minutes"], 30)
        self.assertEqual(payload["task"]["subtasks"][0]["id"], "outline")

    def test_ordinary_edit_preserves_existing_planning_fields(self):
        existing = {
            "id": "task-1",
            "title": "Plan tomorrow",
            "project": "Mentat",
            "status": "todo",
            "priority": "medium",
            "planned_for_today": True,
            "manual_rank": 10,
            "planning_state": "planned",
            "legacy_metadata": {"keep": True},
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", [{"id": "project-mentat", "name": "Mentat"}])
            self.write_json(root, "tasks.json", [existing])
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.update_task(
                    "task-1",
                    {
                        "title": "Plan the next day",
                        "project": "Mentat",
                        "status": "todo",
                        "priority": "medium",
                    },
                )

        self.assertEqual(status, 200)
        self.assertTrue(payload["task"]["planned_for_today"])
        self.assertEqual(payload["task"]["manual_rank"], 10)
        self.assertEqual(payload["task"]["planning_state"], "planned")
        self.assertEqual(payload["task"]["legacy_metadata"], {"keep": True})

    def test_invalid_nested_planning_data_fails_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", [{"id": "project-mentat", "name": "Mentat"}])
            self.write_json(root, "tasks.json", [])
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.create_task(
                    {
                        "title": "Unsafe delegation",
                        "project": "Mentat",
                        "delegation": {"profile_id": "worker", "command": "arbitrary shell"},
                    }
                )

        self.assertEqual(status, 400)
        self.assertIn("unsupported fields", payload["error"])

    def test_dependencies_must_exist_and_cannot_form_a_cycle(self):
        tasks = [
            {"id": "task-a", "title": "A", "project": "Mentat", "status": "todo", "priority": "medium", "depends_on": ["task-b"]},
            {"id": "task-b", "title": "B", "project": "Mentat", "status": "todo", "priority": "medium"},
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", [{"id": "project-mentat", "name": "Mentat"}])
            self.write_json(root, "tasks.json", tasks)
            with patch.object(server, "DATA_DIR", root):
                missing, missing_status = server.update_task(
                    "task-b", {"title": "B", "project": "Mentat", "depends_on": ["missing"]}
                )
                cycle, cycle_status = server.update_task(
                    "task-b", {"title": "B", "project": "Mentat", "depends_on": ["task-a"]}
                )

        self.assertEqual(missing_status, 400)
        self.assertIn("Unknown task dependency", missing["error"])
        self.assertEqual(cycle_status, 400)
        self.assertIn("cycle", cycle["error"])

    def test_completing_recurring_task_creates_exactly_one_next_instance(self):
        recurring = {
            "id": "task-daily",
            "title": "Daily review",
            "project": "Mentat",
            "status": "todo",
            "priority": "medium",
            "due_date": "2026-07-13",
            "recurrence": {"frequency": "daily", "interval": 1},
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", [{"id": "project-mentat", "name": "Mentat"}])
            self.write_json(root, "tasks.json", [recurring])
            with patch.object(server, "DATA_DIR", root):
                first, first_status = server.update_task(
                    "task-daily", {"title": "Daily review", "project": "Mentat", "status": "completed"}
                )
                second, second_status = server.update_task(
                    "task-daily", {"title": "Daily review", "project": "Mentat", "status": "completed"}
                )

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        occurrences = [task for task in second["tasks"] if task.get("recurrence_parent_id") == "task-daily"]
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["due_date"], "2026-07-14")

    def test_recurring_instance_shifts_time_data_and_honors_count(self):
        recurring = {
            "id": "task-counted",
            "title": "Two-day routine",
            "project": "Mentat",
            "status": "todo",
            "priority": "medium",
            "due_date": "2026-07-13",
            "recurrence": {"frequency": "daily", "interval": 2, "count": 2},
            "scheduled_block": {
                "start": "2026-07-13T09:00:00-07:00",
                "end": "2026-07-13T09:30:00-07:00",
            },
            "reminders": [
                {
                    "id": "routine-reminder",
                    "at": "2026-07-13T08:45:00-07:00",
                    "channel": "browser",
                    "enabled": True,
                    "notified_at": "2026-07-13T08:45:00-07:00",
                }
            ],
        }

        next_task = server.recurring_task_instance(recurring)

        self.assertIsNotNone(next_task)
        self.assertEqual(next_task["due_date"], "2026-07-15")
        self.assertEqual(next_task["recurrence"]["count"], 1)
        self.assertEqual(next_task["scheduled_block"]["start"], "2026-07-15T09:00:00-07:00")
        self.assertEqual(next_task["reminders"][0]["at"], "2026-07-15T08:45:00-07:00")
        self.assertNotIn("notified_at", next_task["reminders"][0])
        self.assertIsNone(server.recurring_task_instance(next_task))

    def test_recurring_instance_preserves_completed_checklist_and_deduplicates_recompletion(self):
        recurring = {
            "id": "task-series",
            "title": "Routine",
            "project": "Mentat",
            "status": "todo",
            "priority": "medium",
            "due_date": "2026-07-13",
            "recurrence": {"frequency": "daily", "interval": 1},
            "subtasks": [{"id": "step", "title": "Step", "completed": True, "rank": 0}],
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", [{"id": "project-mentat", "name": "Mentat"}])
            self.write_json(root, "tasks.json", [recurring])
            with patch.object(server, "DATA_DIR", root):
                first, _ = server.update_task("task-series", {"status": "completed"})
                server.update_task("task-series", {"status": "todo"})
                final, _ = server.update_task("task-series", {"status": "completed"})

        completed = next(task for task in first["tasks"] if task["id"] == "task-series")
        self.assertTrue(completed["subtasks"][0]["completed"])
        children = [task for task in final["tasks"] if task.get("recurrence_parent_id") == "task-series"]
        self.assertEqual(len(children), 1)
        self.assertFalse(children[0]["subtasks"][0]["completed"])

    def test_weekly_interval_uses_the_next_active_week(self):
        result = server.next_recurrence_date(
            server.date.fromisoformat("2026-07-15"),
            {"frequency": "weekly", "interval": 2, "weekdays": ["mon", "wed"]},
        )
        self.assertEqual(result.isoformat(), "2026-07-27")

    def test_recurring_wall_clock_time_tracks_iana_timezone_across_dst(self):
        shifted = server.shift_recurring_datetime(
            "2026-10-31T16:00:00+00:00",
            server.timedelta(days=2),
            "America/Los_Angeles",
        )
        self.assertEqual(shifted, "2026-11-02T09:00:00-08:00")


if __name__ == "__main__":
    unittest.main()
