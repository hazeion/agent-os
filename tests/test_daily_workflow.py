from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server


class DailyWorkflowTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, payload) -> None:
        (root / name).write_text(json.dumps(payload), encoding="utf-8")

    def test_today_reorder_swaps_planned_rank_atomically(self):
        tasks = [
            {"id": "task-a", "title": "A", "planned_for_today": True, "manual_rank": 1},
            {"id": "task-b", "title": "B", "planned_for_today": True, "manual_rank": 2},
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "tasks.json", tasks)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                payload, status = server.reorder_today_task("task-b", {"direction": "up"})
        self.assertEqual(status, 200)
        by_id = {task["id"]: task for task in payload["tasks"]}
        self.assertEqual(by_id["task-b"]["manual_rank"], 1)
        self.assertEqual(by_id["task-a"]["manual_rank"], 2)

    def test_today_reorder_treats_zero_as_a_valid_rank(self):
        tasks = [
            {"id": "task-a", "title": "A", "planned_for_today": True, "manual_rank": 0},
            {"id": "task-b", "title": "B", "planned_for_today": True},
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "tasks.json", tasks)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                payload, status = server.reorder_today_task("task-b", {"direction": "up"})
        self.assertEqual(status, 200)
        by_id = {task["id"]: task for task in payload["tasks"]}
        self.assertEqual(by_id["task-b"]["manual_rank"], 0)
        self.assertEqual(by_id["task-a"]["manual_rank"], 1)

    def test_calendar_event_creates_only_project_owned_task_link(self):
        event = {
            "id": "event-1",
            "title": "Planning call",
            "description": "Decide next steps",
            "start": "2026-07-14T09:00:00-07:00",
            "end": "2026-07-14T09:30:00-07:00",
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "tasks.json", [])
            self.write_json(root, "projects.json", [{"id": "project-1", "name": "Mentat"}])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(
                server, "calendar_event_by_id", return_value=event
            ) as event_lookup:
                payload, status = server.create_task_from_calendar_event(
                    "event-1",
                    {
                        "project": "Mentat",
                        "week_start": "2026-07-12",
                        "timezone": "America/Los_Angeles",
                    },
                )
        self.assertEqual(status, 201)
        self.assertEqual(payload["task"]["calendar_links"][0]["event_id"], "event-1")
        self.assertEqual(payload["task"]["scheduled_block"]["start"], event["start"])
        event_lookup.assert_called_once_with(
            "event-1",
            week_start="2026-07-12",
            timezone_name="America/Los_Angeles",
        )

    def test_unified_search_groups_results_without_absolute_note_paths(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "tasks.json", [{"id": "task-1", "title": "Mentat research", "project": "Mentat"}])
            self.write_json(root, "projects.json", [{"id": "project-1", "name": "Mentat"}])
            self.write_json(root, "calendar.json", [{"id": "event-1", "title": "Mentat review"}])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(server, "recent_sessions", return_value={"sessions": [{"id": "session-1", "title": "Mentat session"}]}), patch.object(
                server, "obsidian_notes", return_value={"notes": [{"title": "Mentat plan", "relative_path": "Work/Mentat.md", "path": "/Users/private/Mentat.md", "excerpt": "Mentat notes"}]}
            ), patch.object(server, "CALENDAR_CACHE", {"payload": None}):
                payload = server.unified_search("Mentat")
        self.assertEqual(payload["groups"]["tasks"][0]["id"], "task-1")
        self.assertEqual(payload["groups"]["notes"][0]["id"], "Work/Mentat.md")
        self.assertNotIn("/Users/private", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
