from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_console_attachments import (
    bind_run_attachment,
    create_attachment,
    get_attachment,
    resolve_blob_path,
)
from agent_run_history import load_run_summaries, save_run_summaries
import data_backup_restore
from data_layout import SEED_FILE_NAMES
from json_store import write_json_atomic
from private_console_unit import (
    capture_private_console_unit,
    private_console_unit_digest,
)
from private_state import history_path
import runtime_config
import server


class UpgradeUninstallPreservationTests(unittest.TestCase):
    def create_application_tree(self, base: Path, version: str) -> Path:
        application = base / f"mentat-{version}"
        seeds = application / "data"
        public = application / "public"
        seeds.mkdir(parents=True)
        public.mkdir()
        for name in SEED_FILE_NAMES:
            payload = (
                {"theme": f"packaged-{version}"}
                if name == "dashboard.json"
                else [{"packaged_default": version, "document": name}]
            )
            (seeds / name).write_text(
                json.dumps(payload, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        (public / "index.html").write_text(
            f"<!doctype html><title>Mentat {version}</title>\n",
            encoding="utf-8",
        )
        (application / "VERSION").write_text(f"{version}\n", encoding="utf-8")
        self.make_application_read_only(application)
        return application

    def make_application_read_only(self, application: Path) -> None:
        if os.name != "posix":
            return
        for path in application.rglob("*"):
            path.chmod(0o555 if path.is_dir() else 0o444)
        application.chmod(0o555)

    def remove_application_tree(self, application: Path, temporary_root: Path) -> None:
        self.assertEqual(application.parent, temporary_root)
        self.assertTrue(application.name.startswith("mentat-"))
        self.assertTrue((application / "VERSION").is_file())
        if os.name == "posix":
            application.chmod(0o700)
            for path in application.rglob("*"):
                path.chmod(0o700 if path.is_dir() else 0o600)
        shutil.rmtree(application)

    def tree_snapshot(
        self, root: Path
    ) -> dict[str, tuple[str, bytes | None, int, int]]:
        paths = (root, *sorted(root.rglob("*")))
        return {
            ("." if path == root else path.relative_to(root).as_posix()): (
                "directory" if path.is_dir() else "file",
                None if path.is_dir() else path.read_bytes(),
                path.stat(follow_symlinks=False).st_mode,
                path.stat(follow_symlinks=False).st_mtime_ns,
            )
            for path in paths
        }

    def config(self, application: Path, data_root: Path) -> runtime_config.AppConfig:
        return runtime_config.AppConfig(
            config_files=(),
            host="127.0.0.1",
            port=8888,
            data_dir=data_root,
            public_dir=application / "public",
            hermes_home=data_root.parent / "hermes",
            obsidian_vault=data_root.parent / "vault",
            data_dir_source="cli",
        )

    def start_installed(self, application: Path, data_root: Path) -> None:
        before = self.tree_snapshot(application)
        with patch.object(runtime_config, "PACKAGED_SEED_DIR", application / "data"):
            error = runtime_config.prepare_data_root_for_startup(
                self.config(application, data_root)
            )
        self.assertIsNone(error)
        self.assertEqual(self.tree_snapshot(application), before)

    def write_operator_state(self, data_root: Path) -> tuple[dict, bytes, dict]:
        operator_documents = {
            "tasks.json": [
                {
                    "id": "task-upgrade-preservation",
                    "title": "Keep this task through upgrade",
                    "status": "in_progress",
                }
            ],
            "dashboard.json": {
                "theme": "operator-midnight",
                "planning_view": "today",
            },
        }
        for name, payload in operator_documents.items():
            write_json_atomic(data_root / name, payload)

        with (
            patch.object(server, "DATA_DIR", data_root),
            patch.object(server, "CONFIGURED_DATA_DIR", data_root),
        ):
            created, status = server.create_context_pack(
                {
                    "name": "Release context",
                    "description": "Operator-owned upgrade context",
                    "instructions": "Preserve this operator-owned context.",
                    "note_paths": [],
                    "workspace_files": [],
                }
            )
        self.assertEqual(status, 201)
        context_pack = created["context_pack"]

        blob_bytes = b"operator attachment retained across application replacement\n"
        attachment = create_attachment(
            data_root,
            original_name="upgrade-notes.txt",
            content=blob_bytes,
            content_type="text/plain",
            now=1_721_260_800,
        )
        bound = bind_run_attachment(
            data_root,
            attachment["id"],
            "run_upgrade_preservation",
            now=1_721_260_801,
        )
        save_run_summaries(
            history_path(data_root),
            [
                {
                    "id": "run_upgrade_preservation",
                    "agent_id": "hermes",
                    "agent_name": "Hermes",
                    "model": "test-model",
                    "status": "completed",
                    "session_id": "session-upgrade-preservation",
                    "prompt": "Preserve operator state.",
                    "response": "State retained.",
                    "error": "",
                    "events": [],
                    "attachments": [bound],
                    "artifacts": [],
                    "created_at": "2026-07-18T00:00:00+00:00",
                    "updated_at": "2026-07-18T00:00:01+00:00",
                    "started_at": "2026-07-18T00:00:00+00:00",
                    "completed_at": "2026-07-18T00:00:01+00:00",
                    "duration_seconds": 1,
                }
            ],
            data_root=data_root,
        )
        return bound, blob_bytes, context_pack

    def assert_operator_state(
        self,
        data_root: Path,
        documents: dict[str, bytes],
        private_digest: str,
        attachment: dict,
        blob_bytes: bytes,
        context_pack: dict,
    ) -> None:
        self.assertEqual(
            {name: (data_root / name).read_bytes() for name in SEED_FILE_NAMES},
            documents,
        )
        self.assertEqual(
            private_console_unit_digest(capture_private_console_unit(data_root)),
            private_digest,
        )
        self.assertEqual(get_attachment(data_root, attachment["id"]), attachment)
        self.assertEqual(resolve_blob_path(data_root, attachment["id"]).read_bytes(), blob_bytes)
        history, recovered = load_run_summaries(
            history_path(data_root),
            data_root=data_root,
        )
        self.assertFalse(recovered)
        self.assertEqual([run["id"] for run in history], ["run_upgrade_preservation"])
        self.assertEqual(
            [item["id"] for item in history[0]["attachments"]],
            [attachment["id"]],
        )
        with (
            patch.object(server, "DATA_DIR", data_root),
            patch.object(server, "CONFIGURED_DATA_DIR", data_root),
        ):
            listed = server.context_packs_payload()["context_packs"]
            resolved, delegation_context, error = (
                server.context_pack_delegation_context(context_pack["id"])
            )
            staged, status = server.stage_context_pack(context_pack["id"])
        self.assertEqual(
            [item for item in listed if item.get("id") == context_pack["id"]],
            [context_pack],
        )
        self.assertIsNone(error)
        self.assertEqual(resolved, context_pack)
        self.assertEqual(delegation_context, "")
        self.assertEqual(status, 201)
        self.assertEqual(
            staged["instructions"],
            "Preserve this operator-owned context.",
        )
        self.assertEqual(staged["attachments"], [])

    def test_upgrade_uninstall_and_reinstall_preserve_external_operator_state(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            data_root = base / "operator-data"
            version_one = self.create_application_tree(base, "0.1.0b1")

            self.start_installed(version_one, data_root)
            attachment, blob_bytes, context_pack = self.write_operator_state(data_root)
            durable_documents = {
                name: (data_root / name).read_bytes() for name in SEED_FILE_NAMES
            }
            private_digest = private_console_unit_digest(
                capture_private_console_unit(data_root)
            )

            pre_upgrade = data_backup_restore.create_durable_backup(data_root)
            self.assertEqual(pre_upgrade.status, "created")
            self.assertIsNotNone(pre_upgrade.backup_name)
            private_item = next(
                item for item in pre_upgrade.items if item["name"] == "private_console"
            )
            self.assertEqual(private_item["classification"], "durable_private_consistency_unit")
            self.assertEqual(private_item["run_count"], 1)
            self.assertEqual(private_item["blob_count"], 1)
            backup_path = data_root / "backups" / str(pre_upgrade.backup_name)
            backup_bytes = backup_path.read_bytes()
            self.assertEqual(
                data_backup_restore.preview_durable_restore(
                    data_root, backup_path
                ).status,
                "not_required",
            )

            self.remove_application_tree(version_one, base)
            self.assertFalse(version_one.exists())
            version_two = self.create_application_tree(base, "0.1.0b2")
            self.start_installed(version_two, data_root)
            for name in SEED_FILE_NAMES:
                self.assertNotEqual(
                    (data_root / name).read_bytes(),
                    (version_two / "data" / name).read_bytes(),
                )
            self.assert_operator_state(
                data_root,
                durable_documents,
                private_digest,
                attachment,
                blob_bytes,
                context_pack,
            )
            self.assertEqual(backup_path.read_bytes(), backup_bytes)
            self.assertEqual(
                data_backup_restore.preview_durable_restore(
                    data_root, backup_path
                ).status,
                "not_required",
            )

            before_uninstall = self.tree_snapshot(data_root)
            self.remove_application_tree(version_two, base)
            self.assertFalse(version_two.exists())
            self.assertTrue(data_root.is_dir())
            self.assertEqual(self.tree_snapshot(data_root), before_uninstall)

            version_three = self.create_application_tree(base, "0.1.0b3")
            self.start_installed(version_three, data_root)
            for name in SEED_FILE_NAMES:
                self.assertNotEqual(
                    (data_root / name).read_bytes(),
                    (version_three / "data" / name).read_bytes(),
                )
            self.assert_operator_state(
                data_root,
                durable_documents,
                private_digest,
                attachment,
                blob_bytes,
                context_pack,
            )
            self.assertEqual(backup_path.read_bytes(), backup_bytes)
            self.assertEqual(
                data_backup_restore.create_durable_backup(data_root).status,
                "existing",
            )


if __name__ == "__main__":
    unittest.main()
