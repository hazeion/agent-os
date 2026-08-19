from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server
from mentat_db import connect
from task_repository import TaskRepositoryError, ensure_task_sqlite_authority


class TaskDeletionTests(unittest.TestCase):
    def write_tasks(self, root: Path, tasks: list[dict]) -> None:
        (root / "tasks.json").write_text(
            json.dumps(tasks, indent=2) + "\n", encoding="utf-8"
        )
        try:
            ensure_task_sqlite_authority(root, required_source_mode=None)
        except TaskRepositoryError:
            # Invalid legacy source tests assert the bounded startup refusal.
            pass

    def test_preview_and_confirmation_delete_only_the_selected_task(self):
        tasks = [
            {
                "id": "task_keep",
                "title": "Keep me",
                "created_at": "2026-07-11T10:00:00-07:00",
            },
            {
                "id": "task_remove",
                "title": "Remove me",
                "created_at": "2026-07-11T11:00:00-07:00",
                "updated_at": "2026-07-11T12:00:00-07:00",
            },
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_tasks(root, tasks)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                preview, preview_status = server.preview_task_deletion("task_remove")
                payload, status = server.delete_confirmed_task(
                    "task_remove",
                    {
                        "confirmed": True,
                        "confirmation_id": preview["confirmation_id"],
                    },
                )
                stored = server.read_json_file("tasks.json", [])

        self.assertEqual(preview_status, 200)
        self.assertTrue(preview["requires_confirmation"])
        self.assertEqual(preview["task"]["id"], "task_remove")
        self.assertEqual(status, 200)
        self.assertEqual(payload["deleted_task_id"], "task_remove")
        self.assertEqual([task["id"] for task in stored], ["task_keep"])

    def test_confirmation_is_rejected_if_the_task_changes_after_preview(self):
        original = {
            "id": "task_review",
            "title": "Original title",
            "updated_at": "2026-07-11T10:00:00-07:00",
        }
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_tasks(root, [original])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                preview, _ = server.preview_task_deletion("task_review")
                server.update_json_file(
                    "tasks.json",
                    [],
                    lambda tasks: ([{**tasks[0], "title": "Changed title"}], None),
                )
                payload, status = server.delete_confirmed_task(
                    "task_review",
                    {
                        "confirmed": True,
                        "confirmation_id": preview["confirmation_id"],
                    },
                )
                stored = server.read_json_file("tasks.json", [])

        self.assertEqual(status, 409)
        self.assertIn("changed after preview", payload["error"])
        self.assertEqual(stored[0]["title"], "Changed title")

    def test_preview_and_delete_accept_the_exact_maximum_length_task_id(self):
        task_id = "task@" + ("d" * 155)
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_tasks(root, [{"id": task_id, "title": "Wide task"}])
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "CONFIGURED_DATA_DIR", root
            ):
                preview, preview_status = server.preview_task_deletion(task_id)
                payload, status = server.delete_confirmed_task(
                    task_id,
                    {"confirmed": True, "confirmation_id": preview["confirmation_id"]},
                )

        self.assertEqual(preview_status, 200)
        self.assertEqual(status, 200)
        self.assertEqual(payload["deleted_task_id"], task_id)

    def test_delete_requires_confirmation_and_reports_missing_tasks(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_tasks(root, [])
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                unconfirmed, unconfirmed_status = server.delete_confirmed_task(
                    "task_missing", {}
                )
                missing, missing_status = server.preview_task_deletion("task_missing")

        self.assertEqual(unconfirmed_status, 400)
        self.assertIn("explicit confirmation", unconfirmed["error"])
        self.assertEqual(missing_status, 404)
        self.assertIn("not found", missing["error"])

    def test_duplicate_task_ids_fail_closed_without_deleting_records(self):
        duplicate_tasks = [
            {"id": "task_duplicate", "title": "First record"},
            {"id": "task_duplicate", "title": "Second record"},
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_tasks(root, duplicate_tasks)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                preview, preview_status = server.preview_task_deletion("task_duplicate")
                payload, status = server.delete_confirmed_task(
                    "task_duplicate",
                    {
                        "confirmed": True,
                        "confirmation_id": server._task_delete_confirmation(duplicate_tasks[0]),
                    },
                )
            stored = json.loads((root / "tasks.json").read_text(encoding="utf-8"))

        self.assertEqual(preview_status, 500)
        self.assertIn("must contain a list", preview["error"])
        self.assertEqual(status, 503)
        self.assertIn("Task storage is unavailable", payload["error"])
        self.assertEqual(stored, duplicate_tasks)

    def test_deletion_is_blocked_while_other_tasks_depend_on_target(self):
        tasks = [
            {"id": "task-parent", "title": "Parent"},
            {"id": "task-child", "title": "Child", "depends_on": ["task-parent"]},
        ]
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_tasks(root, tasks)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                payload, status = server.preview_task_deletion("task-parent")
        self.assertEqual(status, 409)
        self.assertEqual(payload["dependent_task_ids"], ["task-child"])

    def test_active_orchestration_run_blocks_preview_and_atomic_delete(self):
        task = {"id": "task-running", "title": "Still running"}
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.write_tasks(root, [task])
            connection = connect(root)
            try:
                connection.execute(
                    "INSERT INTO mentat_runs "
                    "(id, source, task_id, runtime_type, status, dispatch_state, "
                    "details_json, created_at, updated_at) "
                    "VALUES (?, 'task_dispatch', ?, 'hermes', 'running', 'accepted', '{}', ?, ?)",
                    (
                        "run_active_delete_guard",
                        "task-running",
                        "2026-08-18T12:00:00+00:00",
                        "2026-08-18T12:00:00+00:00",
                    ),
                )
            finally:
                connection.close()
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "CONFIGURED_DATA_DIR", root
            ):
                confirmation = server._task_delete_confirmation(
                    server.read_json_file("tasks.json", [])[0]
                )
                preview, preview_status = server.preview_task_deletion("task-running")
                direct, direct_status = server.delete_confirmed_task(
                    "task-running",
                    {
                        "confirmed": True,
                        "confirmation_id": confirmation,
                    },
                )
                stored = server.read_json_file("tasks.json", [])

        self.assertEqual((preview_status, direct_status), (409, 409))
        self.assertIn("Run is active", preview["error"])
        self.assertIn("Run is active", direct["error"])
        self.assertEqual([item["id"] for item in stored], ["task-running"])

    def test_routes_expose_preview_and_confirmed_delete_only_as_post(self):
        routes = {pattern.pattern: handler.__name__ for pattern, handler, _ in server.POST_ROUTES}
        self.assertEqual(
            routes[r"^/api/tasks/([^/]+)/delete/preview$"], "preview_task_deletion"
        )
        self.assertEqual(
            routes[r"^/api/tasks/([^/]+)/delete$"], "delete_confirmed_task"
        )


if __name__ == "__main__":
    unittest.main()
