from __future__ import annotations

import unittest
from unittest.mock import patch

from mentat import local_bridge
import server


PROJECT = {"id": "project_mentat", "name": "Mentat", "status": "active", "revision": 1}
TASK = {
    "id": "task_1",
    "title": "Plan Slice 10",
    "project_id": "project_mentat",
    "project_name": "Mentat",
    "status": "todo",
    "priority": "medium",
    "due_date": "2026-08-30",
    "planned_for_today": True,
    "planning_state": "planned",
    "workflow_stage": "planned",
    "deferred": False,
    "blocked": False,
    "revision": 1,
    "needs_attention": False,
    "review_required": False,
    "attention_reasons": ["due_today", "planned_today"],
    "updated_at": "2026-08-30T12:00:00Z",
}
TASK_LIST = {**TASK, "description_preview": "Set the scope and sequence for Slice 10."}
CONVERSATION = {
    "id": "conv_planning",
    "agent_id": "agent_direct",
    "title": "Planning",
    "title_source": "manual",
    "state": "active",
    "revision": 3,
    "created_at": "2026-08-30T12:00:00Z",
    "updated_at": "2026-08-30T12:01:00Z",
    "archived_at": None,
}


class ConversationPlanningBridgeTests(unittest.TestCase):
    def test_exact_global_task_locator_is_safe_and_maps_missing(self):
        source = {"schema_version": 1, "project": PROJECT, "task": {**TASK, "attention_reasons": []}}
        with patch.object(server, "mentat_planning_task_payload", return_value=source) as read:
            payload, status = local_bridge.bridge_planning_task_payload("task_1")
        self.assertEqual((status, payload["project"], payload["task"]["id"]), (200, PROJECT, "task_1"))
        read.assert_called_once_with("task_1")
        self.assertNotIn("description", str(payload))

        with patch.object(
            server,
            "mentat_planning_task_payload",
            return_value={**source, "private_path": "/tmp/private"},
        ):
            rejected, rejected_status = local_bridge.bridge_planning_task_payload("task_1")
        self.assertEqual((rejected_status, rejected["status"]), (500, "error"))

        from conversation_planning import ConversationPlanningError
        with patch.object(
            server,
            "mentat_planning_task_payload",
            side_effect=ConversationPlanningError("planning.task_not_found"),
        ):
            missing, missing_status = local_bridge.bridge_planning_task_payload("task_missing")
        self.assertEqual((missing_status, missing["status"]), (404, "not_found"))
        with patch.object(
            server,
            "mentat_planning_task_payload",
            side_effect=ConversationPlanningError("planning.projects_ambiguous"),
        ):
            ambiguous, ambiguous_status = local_bridge.bridge_planning_task_payload("task_1")
        self.assertEqual((ambiguous_status, ambiguous["status"]), (500, "error"))

    def test_overview_and_task_page_are_exact_and_private(self):
        overview = {
            "schema_version": 1,
            "today": "2026-08-30",
            "projects": [PROJECT],
            "project_count": 1,
            "attention": [TASK],
            "attention_count": 1,
            "truncated": False,
        }
        with patch.object(server, "mentat_planning_overview_payload", return_value=overview):
            payload, status = local_bridge.bridge_planning_overview_payload()
        self.assertEqual(status, 200)
        self.assertEqual(payload["projects"], [PROJECT])
        self.assertNotIn("description", str(payload))

        page = {
            "schema_version": 1,
            "project": PROJECT,
            "tasks": [TASK_LIST],
            "count": 1,
            "next_cursor": "cursor_1",
        }
        with patch.object(server, "mentat_planning_tasks_payload", return_value=page) as read:
            payload, status = local_bridge.bridge_planning_tasks_payload(
                "project_mentat", "prior_1"
            )
        self.assertEqual(status, 200)
        read.assert_called_once_with(project_id="project_mentat", cursor="prior_1")
        self.assertEqual(payload["tasks"], [TASK_LIST])
        self.assertNotIn("'description':", str(payload))

        for unsafe_preview in ("x" * 281, "safe\x01preview"):
            with self.subTest(unsafe_preview=unsafe_preview), patch.object(
                server,
                "mentat_planning_tasks_payload",
                return_value={**page, "tasks": [{**TASK_LIST, "description_preview": unsafe_preview}]},
            ):
                rejected, rejected_status = local_bridge.bridge_planning_tasks_payload(
                    "project_mentat", None
                )
            self.assertEqual((rejected_status, rejected["status"]), (500, "error"))

        with patch.object(
            server,
            "mentat_planning_tasks_payload",
            return_value={**page, "tasks": [{**TASK_LIST, "description": "private source text"}]},
        ):
            rejected, rejected_status = local_bridge.bridge_planning_tasks_payload(
                "project_mentat", None
            )
        self.assertEqual((rejected_status, rejected["status"]), (500, "error"))

        with patch.object(
            server,
            "mentat_planning_overview_payload",
            return_value={**overview, "private_path": "/tmp/private"},
        ):
            rejected, rejected_status = local_bridge.bridge_planning_overview_payload()
        self.assertEqual((rejected_status, rejected["status"]), (500, "error"))

    def test_context_read_and_mutation_bind_exact_conversation(self):
        context = {
            "schema_version": 1,
            "conversation_id": "conv_planning",
            "conversation_revision": 3,
            "association": {"project_id": "project_mentat", "task_id": "task_1"},
            "project": PROJECT,
            "task": TASK,
            "state": "ready",
        }
        with patch.object(server, "mentat_conversation_planning_context_payload", return_value=context):
            payload, status = local_bridge.bridge_conversation_planning_context_payload(
                "conv_planning"
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["task"]["id"], "task_1")

        result = {**context, "action": "set", "conversation": CONVERSATION}
        with patch.object(
            server,
            "set_mentat_conversation_planning_context",
            return_value=(result, 200),
        ):
            payload, status = local_bridge.bridge_set_conversation_planning_context_payload(
                "conv_planning",
                {"expected_revision": 2, "project_id": "project_mentat", "task_id": "task_1"},
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["action"], "set")

        crossed = {**context, "conversation_id": "conv_other"}
        with patch.object(server, "mentat_conversation_planning_context_payload", return_value=crossed):
            payload, status = local_bridge.bridge_conversation_planning_context_payload(
                "conv_planning"
            )
        self.assertEqual((status, payload["status"]), (500, "error"))

    def test_minimal_create_envelopes_reject_private_or_cross_target_results(self):
        with patch.object(
            server,
            "create_mentat_project",
            return_value=({"schema_version": 1, "action": "create", "project": PROJECT}, 201),
        ):
            payload, status = local_bridge.bridge_create_project_payload({"name": "Mentat"})
        self.assertEqual((status, payload["project"]), (201, PROJECT))

        with patch.object(
            server,
            "create_mentat_project_task",
            return_value=({"schema_version": 1, "action": "create", "project": PROJECT, "task": TASK}, 201),
        ):
            payload, status = local_bridge.bridge_create_project_task_payload(
                "project_mentat",
                {"title": "Plan", "assigned_agent_id": None, "due_date": None},
            )
        self.assertEqual((status, payload["task"]["id"]), (201, "task_1"))

        with patch.object(
            server,
            "create_mentat_project_task",
            return_value=({"schema_version": 1, "action": "create", "project": PROJECT, "task": {**TASK, "project_id": "project_other"}}, 201),
        ):
            rejected, rejected_status = local_bridge.bridge_create_project_task_payload(
                "project_mentat", {}
            )
        self.assertEqual((rejected_status, rejected["status"]), (500, "error"))


if __name__ == "__main__":
    unittest.main()
