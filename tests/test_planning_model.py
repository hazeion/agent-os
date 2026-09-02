from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server
from project_repository import ensure_project_sqlite_authority
from task_repository import (
    ensure_task_sqlite_authority,
    read_authoritative_tasks,
)


def project(identifier: str, name: str) -> dict:
    return {
        "id": identifier, "name": name, "type": "software", "status": "active",
        "description": "", "obsidian_note": "", "aliases": [],
        "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00",
    }


def task(identifier: str, project_name: str) -> dict:
    return {
        "id": identifier, "title": identifier, "description": "", "project": project_name,
        "status": "todo", "priority": "medium", "assignee": None, "due_date": None,
        "source": "test", "tags": [], "review_required": False,
        "needs_attention": False, "created_at": "2026-09-01T00:00:00+00:00",
        "updated_at": "2026-09-01T00:00:00+00:00", "completed_at": None,
    }


class PlanningModelTests(unittest.TestCase):
    def root(self, temporary: str, task_records: list[dict] | None = None) -> Path:
        root = Path(temporary)
        (root / "projects.json").write_text(
            json.dumps([project("project_a", "Alpha"), project("project_b", "Bravo")]),
            encoding="utf-8",
        )
        (root / "tasks.json").write_text(
            json.dumps(task_records if task_records is not None else [task("task_a", "Alpha"), task("task_b", "Alpha")]),
            encoding="utf-8",
        )
        ensure_task_sqlite_authority(root, required_source_mode=None)
        ensure_project_sqlite_authority(root, required_source_mode=None)
        return root

    def test_exact_edit_derives_stage_and_rejects_stale_revision(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root):
                response, status = server.update_mentat_planning_task(
                    "task_a",
                    {"expected_revision": 1, "changes": {"workflow_stage": "planned", "deferred": True}},
                )
                self.assertEqual(status, 200)
                self.assertEqual(response["task"]["workflow_stage"], "planned")
                self.assertTrue(response["task"]["deferred"])
                stale, stale_status = server.update_mentat_planning_task(
                    "task_a", {"expected_revision": 1, "changes": {"title": "stale"}}
                )
                self.assertEqual((stale, stale_status), ({"error_code": "planning.task_conflict"}, 409))

                empty, empty_status = server.update_mentat_planning_task(
                    "task_a", {"expected_revision": 2, "changes": {}}
                )
                self.assertEqual((empty, empty_status), ({"error_code": "planning.task_invalid"}, 400))

    def test_ordinary_edit_preserves_legacy_someday_as_deferred(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            legacy = read_authoritative_tasks(root)
            legacy[0]["planning_state"] = "someday"
            from task_repository import mutate_authoritative_tasks
            mutate_authoritative_tasks(root, lambda tasks: ([legacy[0], *tasks[1:]], None))
            with patch.object(server, "DATA_DIR", root):
                edited, status = server.update_mentat_planning_task(
                    "task_a", {"expected_revision": 2, "changes": {"title": "Still someday"}}
                )
                self.assertEqual(status, 200)
                self.assertEqual(edited["task"]["workflow_stage"], "inbox")
                self.assertTrue(edited["task"]["deferred"])

    def test_project_lifecycle_and_task_move_require_exact_active_target(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root):
                archived, status = server.update_mentat_planning_project(
                    "project_b", {"expected_revision": 1, "action": "archive", "name": None}
                )
                self.assertEqual(status, 200)
                self.assertEqual(archived["project"]["status"], "archived")
                blocked, blocked_status = server.move_mentat_planning_task(
                    "task_a", {"expected_task_revision": 1, "project_id": "project_b", "expected_project_revision": 2}
                )
                self.assertEqual((blocked, blocked_status), ({"error_code": "planning.task_conflict"}, 409))
                restored, status = server.update_mentat_planning_project(
                    "project_b", {"expected_revision": 2, "action": "restore", "name": None}
                )
                self.assertEqual(status, 200)
                moved, moved_status = server.move_mentat_planning_task(
                    "task_a", {"expected_task_revision": 1, "project_id": "project_b", "expected_project_revision": 3}
                )
                self.assertEqual(moved_status, 200)
                self.assertEqual(moved["task"]["project_id"], "project_b")

    def test_completion_creates_atomic_successor_without_dependencies_or_review_state(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root):
                edited, status = server.update_mentat_planning_task(
                    "task_a",
                    {"expected_revision": 1, "changes": {"depends_on": ["task_b"], "recurrence": {"frequency": "daily"}, "subtasks": [{"id": "check", "title": "Check", "completed": True, "rank": 0}]}},
                )
                self.assertEqual(status, 200)
                finished, status = server.update_mentat_planning_task(
                    "task_a", {"expected_revision": edited["task"]["revision"], "changes": {"workflow_stage": "done"}}
                )
                self.assertEqual(status, 200)
                tasks = read_authoritative_tasks(root)
                successor = next(item for item in tasks if item["id"] != "task_a" and item.get("recurrence_parent_id") == "task_a")
                self.assertNotIn("depends_on", successor)
                self.assertFalse(successor["review_required"])
                self.assertEqual(successor["workflow_stage"], "inbox")
                self.assertEqual(successor["subtasks"][0]["completed"], False)

    def test_blocked_is_derived_across_projects_and_cycles_are_rejected(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root):
                moved, status = server.move_mentat_planning_task(
                    "task_b", {"expected_task_revision": 1, "project_id": "project_b", "expected_project_revision": 1}
                )
                self.assertEqual(status, 200)
                edited, status = server.update_mentat_planning_task(
                    "task_a", {"expected_revision": 1, "changes": {"depends_on": ["task_b"]}}
                )
                self.assertEqual(status, 200)
                locator = server.mentat_planning_task_payload("task_a")
                self.assertTrue(locator["task"]["blocked"])
                rejected, rejected_status = server.update_mentat_planning_task(
                    "task_b", {"expected_revision": moved["task"]["revision"], "changes": {"depends_on": ["task_a"]}}
                )
                self.assertEqual((rejected, rejected_status), ({"error_code": "planning.task_invalid"}, 400))

    def test_detail_edit_supports_checklists_today_order_and_canonical_assignment(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "_planning_assignee", return_value=("agent_planner", "Planner", None)
            ):
                edited, status = server.update_mentat_planning_task(
                    "task_a",
                    {
                        "expected_revision": 1,
                        "changes": {
                            "assigned_agent_id": "agent_planner",
                            "manual_rank": 7,
                            "planned_for_today": True,
                            "subtasks": [{"id": "first", "title": "First", "completed": False, "rank": 0}],
                        },
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(edited["task"]["revision"], 2)
                stored = next(item for item in read_authoritative_tasks(root) if item["id"] == "task_a")
                self.assertEqual(stored["assigned_agent_id"], "agent_planner")
                self.assertEqual(stored["assignee"], "Planner")
                self.assertEqual(stored["manual_rank"], 7)
                self.assertEqual(stored["subtasks"][0]["title"], "First")

    def test_dependency_reads_are_bounded_cross_project_and_cursor_bound(self):
        with TemporaryDirectory() as temporary:
            tasks = [task("task_a", "Alpha"), task("task_b", "Alpha")]
            tasks[0]["depends_on"] = ["task_b"]
            for index in range(101):
                dependent = task(f"task_dependent_{index:03d}", "Bravo")
                dependent["depends_on"] = ["task_a"]
                tasks.append(dependent)
            root = self.root(temporary, tasks)
            with patch.object(server, "DATA_DIR", root):
                related = server.mentat_planning_task_dependencies_payload("task_a")
                self.assertEqual(related["task_id"], "task_a")
                self.assertEqual(related["task_revision"], 1)
                self.assertEqual(
                    related["prerequisites"],
                    [{
                        "id": "task_b", "title": "task_b", "project_id": "project_a",
                        "project_name": "Alpha", "workflow_stage": "inbox", "blocked": False,
                    }],
                )
                self.assertEqual((related["dependent_count"], len(related["dependents"])), (101, 100))
                self.assertTrue(related["dependents_truncated"])
                self.assertNotIn("description", str(related))

                first = server.mentat_planning_dependency_picker_payload(task_id="task_a")
                self.assertEqual((first["candidate_count"], first["match_count"]), (50, 102))
                self.assertTrue(first["truncated"])
                self.assertNotIn("task_a", {item["id"] for item in first["candidates"]})
                second = server.mentat_planning_dependency_picker_payload(
                    task_id="task_a", cursor=first["next_cursor"]
                )
                self.assertEqual(second["candidate_count"], 50)
                self.assertNotEqual(
                    {item["id"] for item in first["candidates"]},
                    {item["id"] for item in second["candidates"]},
                )
                bravo = server.mentat_planning_dependency_picker_payload(
                    task_id="task_a", query="Bravo"
                )
                self.assertEqual(bravo["match_count"], 101)
                with self.assertRaisesRegex(Exception, "planning.cursor_invalid"):
                    server.mentat_planning_dependency_picker_payload(
                        task_id="task_a", query="Other", cursor=first["next_cursor"]
                    )

    def test_dependency_edit_rejects_raw_duplicate_and_self_without_mutating(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root):
                for dependencies in (["task_a"], [" task_b "], ["task_b", " task_b "]):
                    with self.subTest(dependencies=dependencies):
                        rejected, status = server.update_mentat_planning_task(
                            "task_a", {"expected_revision": 1, "changes": {"depends_on": dependencies}}
                        )
                        self.assertEqual((rejected, status), ({"error_code": "planning.task_invalid"}, 400))
                        stored = next(item for item in read_authoritative_tasks(root) if item["id"] == "task_a")
                        self.assertNotIn("depends_on", stored)


if __name__ == "__main__":
    unittest.main()
