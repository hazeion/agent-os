from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server


PNG = b"\x89PNG\r\n\x1a\n" + b"safe-image-payload"


class AgentConsoleAttachmentRunTests(unittest.TestCase):
    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()

    def test_uploaded_image_binds_to_run_without_exposing_its_path(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            with patch.object(server, "DATA_DIR", data_dir):
                upload, upload_status = server.create_agent_console_attachment(
                    original_name="diagram.png",
                    content_type="image/png",
                    content=PNG,
                )
                attachment = upload["attachment"]
                with patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
                    server, "agent_console_model", return_value="test/model"
                ), patch.object(server.threading, "Thread") as worker:
                    payload, status = server.start_agent_console_run(
                        {
                            "agent_id": "hermes",
                            "prompt": "Explain this diagram",
                            "attachment_ids": [attachment["id"]],
                        }
                    )

                public_run = payload["run"]
                private_run = server.AGENT_CONSOLE_RUNS[public_run["id"]]

            self.assertEqual(upload_status, 201)
            self.assertEqual(status, 202)
            self.assertEqual(public_run["attachments"][0]["id"], attachment["id"])
            self.assertTrue(public_run["attachments"][0]["content_url"].startswith("/api/"))
            self.assertNotIn("_image_path", public_run)
            self.assertNotIn("_execution_prompt", public_run)
            self.assertIsInstance(private_run["_image_path"], Path)
            self.assertEqual(private_run["_image_path"].suffix, ".png")
            self.assertTrue(private_run["_image_path"].is_file())
            worker.return_value.start.assert_called_once_with()

    def test_text_attachment_adds_fixed_execution_context_but_keeps_display_prompt(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            with patch.object(server, "DATA_DIR", data_dir):
                upload, _ = server.create_agent_console_attachment(
                    original_name="context.py",
                    content_type="text/x-python",
                    content=b"print('hello')\n",
                )
                with patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
                    server.threading, "Thread"
                ):
                    payload, status = server.start_agent_console_run(
                        {
                            "agent_id": "hermes",
                            "prompt": "Review this",
                            "attachment_ids": [upload["attachment"]["id"]],
                        }
                    )
                private_run = server.AGENT_CONSOLE_RUNS[payload["run"]["id"]]

            self.assertEqual(status, 202)
            self.assertEqual(payload["run"]["prompt"], "Review this")
            self.assertIn("[Mentat attachment context v1]", private_run["_execution_prompt"])
            self.assertIn("read_file", private_run["_execution_prompt"])
            self.assertNotIn("_execution_prompt", payload["run"])


if __name__ == "__main__":
    unittest.main()
