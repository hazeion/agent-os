from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server


class DashboardBehaviorTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, payload) -> None:
        (root / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def test_calendar_fallback_payload_is_read_only_and_event_shaped(self):
        tomorrow = (datetime.now().astimezone() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        fallback_events = [
            {
                "id": "cal_demo",
                "title": "Behavior test calendar event",
                "start": tomorrow.isoformat(timespec="seconds"),
                "end": (tomorrow + timedelta(hours=1)).isoformat(timespec="seconds"),
                "type": "local_fallback",
                "description": "Used to verify calendar fallback behavior.",
            }
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "calendar.json", fallback_events)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "google_credentials", return_value=(None, "Google OAuth token not found")
            ):
                server.CALENDAR_CACHE.update({"key": None, "payload": None, "fetched_at": None})
                payload = server.google_calendar_events(days=7)

        self.assertEqual(payload["source"], "local")
        self.assertEqual(payload["auth"], "not_connected")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["summary"]["count"], 1)
        self.assertTrue(payload["summary"]["fallback_available"])
        self.assertFalse(payload["summary"]["stale"])
        self.assertEqual(payload["summary"]["next_event"]["title"], "Behavior test calendar event")
        self.assertEqual(payload["window"]["label"], "Today + next 6 days")

    def test_resolve_attention_item_updates_json_and_keeps_task_attention_open(self):
        attention = [
            {
                "id": "attn_manual",
                "title": "Manual review item",
                "description": "Resolve me",
                "status": "open",
            }
        ]
        tasks = [
            {
                "id": "task_review_api",
                "title": "Review API payloads",
                "description": "Still needs human review",
                "project": "Agent OS",
                "status": "todo",
                "priority": "high",
                "review_required": True,
            },
            {
                "id": "task_done",
                "title": "Already done",
                "status": "completed",
                "project": "Agent OS",
            },
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "attention.json", attention)
            self.write_json(root, "tasks.json", tasks)
            with patch.object(server, "DATA_DIR", root):
                payload, status = server.resolve_attention_item("attn_manual")
                follow_up = server.attention_payload()
                stored_attention = json.loads((root / "attention.json").read_text(encoding="utf-8"))

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resolved"]["status"], "resolved")
        self.assertIn("resolved_at", payload["resolved"])
        self.assertEqual(payload["open_count"], 1)
        self.assertEqual(stored_attention[0]["status"], "resolved")
        self.assertEqual([item["id"] for item in follow_up["attention"]], ["task:task_review_api"])
        self.assertEqual(follow_up["attention"][0]["source"], "task")

    def test_overview_cards_track_real_dashboard_counts(self):
        now = datetime.now().astimezone()
        tasks = [
            {
                "id": "task_active",
                "title": "Active task",
                "status": "todo",
                "project": "Agent OS",
                "created_at": now.isoformat(timespec="seconds"),
            },
            {
                "id": "task_attention",
                "title": "Needs attention task",
                "status": "in progress",
                "project": "Agent OS",
                "needs_attention": True,
                "updated_at": now.isoformat(timespec="seconds"),
            },
            {
                "id": "task_recent_done",
                "title": "Recently completed",
                "status": "completed",
                "project": "Agent OS",
                "completed_at": (now - timedelta(days=1)).isoformat(timespec="seconds"),
            },
            {
                "id": "task_old_done",
                "title": "Older completed",
                "status": "completed",
                "project": "Agent OS",
                "completed_at": (now - timedelta(days=10)).isoformat(timespec="seconds"),
            },
        ]
        projects = [
            {"id": "project_agent_os", "name": "Agent OS", "status": "active"},
            {"id": "project_archive", "name": "Archive", "status": "paused"},
        ]
        dashboard = {"display_name": "Brandon", "greeting_prefix": "Hello"}
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "tasks.json", tasks)
            self.write_json(root, "projects.json", projects)
            self.write_json(root, "attention.json", [])
            self.write_json(root, "dashboard.json", dashboard)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "read_cron_jobs", return_value={"count": 2, "jobs": []}
            ), patch.object(server, "recent_sessions", return_value={"sessions": [{}, {}, {}]}):
                payload = server.overview()

        self.assertEqual(payload["identity"]["display_name"], "Brandon")
        self.assertEqual(payload["identity"]["greeting_prefix"], "Hello")
        self.assertEqual(payload["cards"]["needs_attention"], 1)
        self.assertEqual(payload["cards"]["active_tasks"], 2)
        self.assertEqual(payload["cards"]["completed_this_week"], 1)
        self.assertEqual(payload["cards"]["scheduled_crons"], 2)
        self.assertEqual(payload["cards"]["recent_sessions"], 3)
        self.assertEqual(payload["cards"]["active_projects"], 1)

    def test_projects_endpoint_returns_plain_list_for_ui_hydration(self):
        projects = [
            {
                "id": "project_agent_os",
                "name": "Agent OS",
                "status": "active",
                "obsidian_note": "Agentic OS Project Home",
            }
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_json(root, "projects.json", projects)
            with patch.object(server, "DATA_DIR", root):
                payload = server.API_ROUTES["/api/projects"]()

        self.assertEqual(payload["projects"], projects)
        self.assertEqual(payload["projects"][0]["name"], "Agent OS")
        self.assertEqual(payload["projects"][0]["obsidian_note"], "Agentic OS Project Home")


if __name__ == "__main__":
    unittest.main()
