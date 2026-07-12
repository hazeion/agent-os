from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server


class FakeKanban:
    def __init__(self):
        self.calls = []
        self.remote_status = "running"

    def detect_capabilities(self):
        return {"status": "available", "capabilities": {"tasks.create": True, "boards.read": True}}

    def list_boards(self):
        return {"ok": True, "boards": [{"id": "default", "name": "Default"}]}

    def create_task(self, board, **payload):
        self.calls.append(("create", board, payload))
        return {"ok": True, "task": {"id": "t-hermes-1", "title": payload["title"], "status": "ready"}}

    def get_task(self, board, task_id):
        self.calls.append(("show", board, task_id))
        create_payload = next((call[2] for call in reversed(self.calls) if call[0] == "create"), {})
        return {
            "ok": True,
            "task": {
                "id": task_id,
                "title": create_payload.get("title", "Research"),
                "body": create_payload.get("body", ""),
                "assignee": create_payload.get("assignee", "researcher"),
                "workspace_kind": create_payload.get("workspace", "scratch"),
                "status": self.remote_status,
                "session_id": "session-1",
            },
            "runs": [{"id": 7, "status": "running", "profile": "researcher", "summary": "Started"}],
            "comments": [],
            "latest_summary": "Started",
        }

    def reply_task(self, board, task_id, note):
        self.calls.append(("reply", board, task_id, note))
        return {"ok": True}

    def retry_task(self, board, task_id):
        self.calls.append(("retry", board, task_id))
        return {"ok": True}

    def terminate_task(self, board, task_id):
        self.calls.append(("stop", board, task_id))
        return {"ok": True}

    def block_task(self, board, task_id, note):
        self.calls.append(("block", board, task_id, note))
        return {"ok": True}

    def comment_task(self, board, task_id, note):
        self.calls.append(("comment", board, task_id, note))
        return {"ok": True}


class TaskDelegationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "tasks.json").write_text(json.dumps([{
            "id": "task-1",
            "title": "Research",
            "description": "Compare options",
            "project": "Mentat",
            "status": "todo",
            "priority": "high",
            "created_at": "2026-07-12T10:00:00-07:00",
            "updated_at": "2026-07-12T10:00:00-07:00",
        }]), encoding="utf-8")
        (self.root / "projects.json").write_text(json.dumps([{"id": "project-1", "name": "Mentat"}]), encoding="utf-8")
        self.adapter = FakeKanban()
        self.patches = [
            patch.object(server, "DATA_DIR", self.root),
            patch.object(server, "kanban_adapter", return_value=self.adapter),
            patch.object(server, "hermes_profiles_payload", return_value={"status": "available", "profiles": [{"id": "researcher"}]}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.tmp.cleanup()

    def intent(self):
        return {"profile_id": "researcher", "board_id": "default", "workspace": "scratch", "instructions": "Cite sources"}

    def test_preview_binds_exact_task_and_target(self):
        preview, status = server.preview_task_delegation("task-1", self.intent())
        self.assertEqual(status, 200)
        self.assertTrue(preview["requires_confirmation"])
        self.assertTrue(preview["confirmation_id"].startswith("task_delegate_"))
        self.assertIn("Cite sources", preview["context"])
        self.assertEqual(preview["target"]["profile_id"], "researcher")

    def test_confirmed_delegation_creates_verifies_and_persists_link(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        payload, status = server.delegate_confirmed_task("task-1", {
            **self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]
        })
        self.assertEqual(status, 201)
        self.assertEqual(payload["task"]["delegation"]["kanban_task_id"], "t-hermes-1")
        self.assertEqual(payload["task"]["delegation"]["run_id"], "7")
        self.assertEqual(payload["task"]["planning_state"], "waiting")
        self.assertEqual(self.adapter.calls[0][0], "create")
        self.assertTrue(self.adapter.calls[0][2]["idempotency_key"].startswith("mentat-task-1-"))
        self.assertEqual(self.adapter.calls[1], ("show", "default", "t-hermes-1"))
        duplicate, duplicate_status = server.preview_task_delegation("task-1", self.intent())
        self.assertEqual(duplicate_status, 409)
        self.assertIn("already has linked", duplicate["error"])

    def test_changed_task_invalidates_confirmation(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        tasks = json.loads((self.root / "tasks.json").read_text(encoding="utf-8"))
        tasks[0]["title"] = "Changed"
        (self.root / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        payload, status = server.delegate_confirmed_task("task-1", {
            **self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]
        })
        self.assertEqual(status, 409)
        self.assertIn("changed after preview", payload["error"])
        self.assertEqual(self.adapter.calls, [])

    def test_accept_review_completes_mentat_task_without_extra_hermes_mutation(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        server.delegate_confirmed_task("task-1", {**self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]})
        tasks = json.loads((self.root / "tasks.json").read_text(encoding="utf-8"))
        tasks[0]["delegation"]["state"] = "ready_for_review"
        (self.root / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        self.adapter.remote_status = "review"
        action_preview, _ = server.preview_delegation_action("task-1", {"action": "accept"})
        payload, status = server.execute_confirmed_delegation_action("task-1", {
            "action": "accept", "confirmed": True, "confirmation_id": action_preview["confirmation_id"]
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["status"], "completed")
        self.assertEqual(payload["delegation"]["review_state"], "accepted")

    def test_review_actions_reject_incompatible_remote_state(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        server.delegate_confirmed_task("task-1", {**self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]})

        payload, status = server.preview_delegation_action("task-1", {"action": "accept"})

        self.assertEqual(status, 409)
        self.assertIn("unavailable while delegated work is running", payload["error"])

    def test_preview_fails_closed_when_profile_inventory_is_unavailable(self):
        with patch.object(server, "hermes_profiles_payload", return_value={"status": "unavailable", "profiles": []}):
            payload, status = server.preview_task_delegation("task-1", self.intent())

        self.assertEqual(status, 409)
        self.assertIn("profiles are unavailable", payload["error"])

    def test_preview_blocks_incomplete_dependencies(self):
        tasks = json.loads((self.root / "tasks.json").read_text(encoding="utf-8"))
        tasks[0]["depends_on"] = ["task-dependency"]
        tasks.append({"id": "task-dependency", "title": "Dependency", "status": "todo"})
        (self.root / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")

        payload, status = server.preview_task_delegation("task-1", self.intent())

        self.assertEqual(status, 409)
        self.assertEqual(payload["dependency_task_ids"], ["task-dependency"])

    def test_action_rejects_live_hermes_state_change(self):
        preview, _ = server.preview_task_delegation("task-1", self.intent())
        server.delegate_confirmed_task("task-1", {**self.intent(), "confirmed": True, "confirmation_id": preview["confirmation_id"]})
        self.adapter.remote_status = "review"
        action_preview, status = server.preview_delegation_action("task-1", {"action": "accept"})
        self.assertEqual(status, 200)
        self.adapter.remote_status = "running"

        payload, action_status = server.execute_confirmed_delegation_action("task-1", {
            "action": "accept", "confirmed": True, "confirmation_id": action_preview["confirmation_id"]
        })

        self.assertEqual(action_status, 409)
        self.assertIn("unavailable while delegated work is running", payload["error"])

    def test_activity_groups_linked_tasks_by_decision_state(self):
        tasks = json.loads((self.root / "tasks.json").read_text(encoding="utf-8"))
        tasks[0]["delegation"] = {"profile_id": "researcher", "state": "needs_input", "review_state": "pending"}
        (self.root / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        payload = server.agent_activity_payload()
        self.assertEqual(payload["counts"]["needs_input"], 1)
        self.assertEqual(payload["groups"]["needs_input"][0]["task_id"], "task-1")


if __name__ == "__main__":
    unittest.main()
