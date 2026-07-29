from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import server


class ContextPackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.vault = self.root / "vault"
        self.data.mkdir()
        self.vault.mkdir()
        (self.data / "context_packs.json").write_text("[]\n", encoding="utf-8")
        (self.vault / "Plan.md").write_text("# Plan\nShip the reviewed slice.\n", encoding="utf-8")
        self.data_patch = patch.object(server, "DATA_DIR", self.data)
        self.configured_data_patch = patch.object(server, "CONFIGURED_DATA_DIR", self.data)
        self.vault_patch = patch.object(server, "OBSIDIAN_VAULT", self.vault)
        self.data_patch.start()
        self.configured_data_patch.start()
        self.vault_patch.start()

    def tearDown(self):
        self.vault_patch.stop()
        self.configured_data_patch.stop()
        self.data_patch.stop()
        self.temp.cleanup()

    def payload(self):
        return {
            "name": "Mentat delivery",
            "description": "Reusable delivery context",
            "instructions": "Return a concise verified result.",
            "note_paths": ["Plan.md"],
            "workspace_files": [{
                "root_id": "workspace",
                "relative_path": "README.md",
                "name": "README.md",
                "kind": "text",
                "mime_type": "text/markdown",
                "byte_size": 999,
            }],
        }

    def test_create_update_delete_uses_project_owned_store_and_stale_delete_guard(self):
        created, status = server.create_context_pack(self.payload())
        self.assertEqual(status, 201)
        pack = created["context_pack"]
        stored = json.loads((self.data / "context_packs.json").read_text(encoding="utf-8"))
        self.assertEqual(stored[0]["id"], pack["id"])
        authority = {"root_id": "workspace", "relative_path": "README.md"}
        self.assertEqual(stored[0]["workspace_files"], [authority])
        self.assertEqual(pack["workspace_files"], [authority])
        listed = server.context_packs_payload()["context_packs"][0]
        self.assertEqual(listed["workspace_files"], [authority])

        rejected, status = server.delete_context_pack(pack["id"], {"confirmed": True, "expected_updated_at": "stale"})
        self.assertEqual(status, 409)
        self.assertIn("changed", rejected["error"])

        deleted, status = server.delete_context_pack(pack["id"], {"confirmed": True, "expected_revision": pack["revision"]})
        self.assertEqual(status, 200)
        self.assertEqual(deleted["context_packs"], [])

    def test_same_timestamp_update_changes_revision_and_invalidates_stale_delete(self):
        fixed_timestamp = "2026-07-14T10:30:00-07:00"
        with patch.object(server, "now_iso", return_value=fixed_timestamp):
            created, status = server.create_context_pack(self.payload())
            self.assertEqual(status, 201)
            original = created["context_pack"]

            changed_payload = self.payload()
            changed_payload["instructions"] = "Use the newly reviewed delivery checklist."
            updated, status = server.update_context_pack(original["id"], changed_payload)
            self.assertEqual(status, 200)
            changed = updated["context_pack"]

        self.assertEqual(original["updated_at"], changed["updated_at"])
        self.assertNotEqual(original["revision"], changed["revision"])
        rejected, status = server.delete_context_pack(
            original["id"],
            {"confirmed": True, "expected_revision": original["revision"]},
        )
        self.assertEqual(status, 409)
        self.assertIn("changed", rejected["error"])

        deleted, status = server.delete_context_pack(
            original["id"],
            {"confirmed": True, "expected_revision": changed["revision"]},
        )
        self.assertEqual(status, 200)
        self.assertEqual(deleted["context_packs"], [])

    def test_stage_creates_private_snapshots_and_delegation_context_is_bounded(self):
        created, _ = server.create_context_pack(self.payload())
        pack = created["context_pack"]
        staged, status = server.stage_context_pack(pack["id"])
        self.assertEqual(status, 201)
        self.assertEqual(len(staged["attachments"]), 2)
        self.assertTrue(all(item["id"].startswith("attachment_") for item in staged["attachments"]))
        self.assertTrue(all("path" not in item for item in staged["attachments"]))

        resolved, context, error = server.context_pack_delegation_context(pack["id"])
        self.assertIsNone(error)
        self.assertEqual(resolved["id"], pack["id"])
        self.assertEqual(
            resolved["workspace_files"],
            [{"root_id": "workspace", "relative_path": "README.md"}],
        )
        self.assertIn("Ship the reviewed slice", context)
        self.assertIn("# Mentat", context)

    def test_rejects_missing_notes_images_and_more_than_eight_items(self):
        payload = self.payload()
        payload["note_paths"] = ["Missing.md"]
        response, status = server.create_context_pack(payload)
        self.assertEqual(status, 400)
        self.assertIn("unavailable", response["error"])


if __name__ == "__main__":
    unittest.main()
