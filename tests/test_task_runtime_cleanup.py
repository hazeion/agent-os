from __future__ import annotations

import ast
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server
from task_repository import ensure_task_sqlite_authority, read_authoritative_tasks


ROOT = Path(__file__).resolve().parent.parent


class TaskRuntimeCleanupTests(unittest.TestCase):
    def test_server_has_no_generic_json_task_call_sites(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in {"read_json_file", "update_json_file"}:
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value == "tasks.json":
                offenders.append((node.func.id, node.lineno))
        self.assertEqual(offenders, [])
        self.assertNotIn('"tasks.json",', source.split("ALLOWED_DATA_WRITES =", 1)[1].split("\n", 1)[0])

    def test_live_task_read_and_write_ignore_stale_json(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            tasks_path = root / "tasks.json"
            initial = [
                {
                    "id": "task-1",
                    "title": "Authoritative task",
                    "status": "todo",
                    "priority": "medium",
                    "created_at": "2026-08-21T09:00:00+00:00",
                    "updated_at": "2026-08-21T09:00:00+00:00",
                }
            ]
            tasks_path.write_text(json.dumps(initial), encoding="utf-8")
            ensure_task_sqlite_authority(root, required_source_mode=None)
            authoritative_initial = read_authoritative_tasks(root)
            stale = json.dumps(
                [{"id": "stale", "title": "Must never be read", "status": "todo"}]
            ).encode("utf-8")
            tasks_path.write_bytes(stale)

            with patch.object(server, "DATA_DIR", root):
                self.assertEqual(server.read_task_snapshot(), authoritative_initial)
                result = server.update_task_snapshot(
                    lambda tasks: (
                        [
                            *tasks,
                            {
                                **authoritative_initial[0],
                                "id": "task-2",
                                "title": "SQLite task",
                            },
                        ],
                        {"ok": True},
                    )
                )

            self.assertEqual(result, {"ok": True})
            self.assertEqual(tasks_path.read_bytes(), stale)
            self.assertEqual(
                [task["id"] for task in read_authoritative_tasks(root)],
                ["task-1", "task-2"],
            )


if __name__ == "__main__":
    unittest.main()
