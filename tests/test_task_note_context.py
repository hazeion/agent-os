from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

import server


class TaskNoteContextTests(unittest.TestCase):
    def test_attach_accepts_only_existing_vault_relative_markdown(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vault = root / "vault"
            vault.mkdir()
            (vault / "Plan.md").write_text("Safe context", encoding="utf-8")
            (root / "tasks.json").write_text(json.dumps([{"id": "task-1", "title": "Task", "project": "Mentat"}]), encoding="utf-8")
            (root / "projects.json").write_text(json.dumps([{"id": "project-1", "name": "Mentat"}]), encoding="utf-8")
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root), patch.object(server, "OBSIDIAN_VAULT", vault):
                accepted, accepted_status = server.attach_task_note("task-1", {"relative_path": "Plan.md"})
                rejected, rejected_status = server.attach_task_note("task-1", {"relative_path": "../outside.md"})
        self.assertEqual(accepted_status, 200)
        self.assertEqual(accepted["task"]["note_links"][0]["path"], "Plan.md")
        self.assertEqual(rejected_status, 400)

    def test_delegation_note_context_is_bounded_and_names_relative_note(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vault = root / "vault"
            vault.mkdir()
            (vault / "Large.md").write_text("x" * 10000, encoding="utf-8")
            with patch.object(server, "OBSIDIAN_VAULT", vault):
                context = server.task_note_context({"note_links": [{"path": "Large.md"}]}, total_limit=100)
        self.assertIn("Attached note: Large.md", context)
        self.assertLess(len(context), 140)
        self.assertNotIn(str(vault), context)

    def test_delegation_note_context_redacts_credentials_and_private_paths(self):
        with TemporaryDirectory() as tmpdir:
            vault = Path(tmpdir) / "vault"
            vault.mkdir()
            (vault / "Private.md").write_text(
                "api_key=supersecretvalue\nWork in /Users/alice/private/project",
                encoding="utf-8",
            )
            with patch.object(server, "OBSIDIAN_VAULT", vault):
                context = server.task_note_context({"note_links": [{"path": "Private.md"}]})
        self.assertNotIn("supersecretvalue", context)
        self.assertNotIn("/Users/alice", context)
        self.assertIn("[redacted-secret]", context)
        self.assertIn("[redacted-path]", context)


if __name__ == "__main__":
    unittest.main()
