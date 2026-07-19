from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server
from agent_console_artifacts import prepare_export_directory
from agent_console_attachments import resolve_blob_path


class CompletedHermesProcess:
    returncode = 0

    def communicate(self, timeout=None):
        return "Created the requested file.", ""


class AgentConsoleArtifactIntegrationTests(unittest.TestCase):
    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()

    def test_workspace_search_and_selection_return_only_safe_relative_metadata(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace = root / "workspace"
            data_dir = root / "data"
            workspace.mkdir()
            (workspace / "visible.py").write_text("print('safe')\n", encoding="utf-8")
            (workspace / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
            with patch.object(server, "BASE_DIR", workspace), patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir):
                search, search_status = server.workspace_files_payload("visible")
                selected, selected_status = server.create_workspace_attachment(
                    {"root_id": "workspace", "relative_path": "visible.py"}
                )
                blocked, blocked_status = server.create_workspace_attachment(
                    {"root_id": "workspace", "relative_path": "../.env"}
                )

            self.assertEqual(search_status, 200)
            self.assertEqual(search["files"][0]["path"], "visible.py")
            self.assertNotIn(str(workspace), json.dumps(search))
            self.assertEqual(selected_status, 201)
            self.assertEqual(selected["attachment"]["name"], "visible.py")
            self.assertNotIn("path", selected["attachment"])
            self.assertEqual(blocked_status, 400)
            self.assertIn("relative", blocked["error"].lower())

    def test_completed_run_discovers_binds_and_persists_owned_artifact(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            profile = {"id": "default", "name": "Hermes", "model": "test/model", "available": True}
            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", True
            ), patch.object(
                server, "hermes_profiles_payload", return_value={"profiles": [profile]}
            ), patch.object(server, "agent_console_profile", return_value=profile), patch.object(
                server, "hermes_command_path", return_value="/tmp/hermes"
            ), patch.object(server.threading, "Thread"):
                payload, status = server.start_agent_console_run(
                    {"agent_id": "default", "prompt": "Create a small Python example"}
                )

            run_id = payload["run"]["id"]
            export_dir = prepare_export_directory(data_dir, run_id)
            (export_dir / "example.py").write_text("print('artifact')\n", encoding="utf-8")

            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", True
            ), patch.object(
                server.subprocess, "Popen", return_value=CompletedHermesProcess()
            ) as popen:
                server.run_hermes_agent(run_id, "/tmp/hermes")

            run = server.agent_console_snapshot(server.AGENT_CONSOLE_RUNS[run_id])
            artifact = run["artifacts"][0]
            stored_history = json.loads(
                (data_dir / "private" / "console" / "agent-console-runs.json").read_text(encoding="utf-8")
            )["runs"][0]

            self.assertEqual(status, 202)
            self.assertEqual(run["status"], "completed")
            self.assertEqual(artifact["kind"], "code")
            self.assertEqual(artifact["name"], "example.py")
            self.assertTrue(artifact["content_url"].startswith("/api/agent-console/attachments/"))
            self.assertEqual(resolve_blob_path(data_dir, artifact["id"]).read_text(), "print('artifact')\n")
            self.assertFalse(export_dir.exists())
            self.assertEqual(stored_history["artifacts"][0]["id"], artifact["id"])
            self.assertNotIn(str(data_dir), json.dumps(run))
            self.assertIn("export_directory", popen.call_args.args[0][5])


if __name__ == "__main__":
    unittest.main()
