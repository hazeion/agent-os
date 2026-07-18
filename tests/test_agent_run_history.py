from __future__ import annotations

import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import agent_run_history
import server


def sample_run(run_id: str, created_at: str, **overrides) -> dict:
    run = {
        "id": run_id,
        "agent_id": "hermes",
        "agent_name": "Hermes",
        "model": "test/model",
        "status": "completed",
        "session_id": None,
        "prompt": "short prompt",
        "response": "short response",
        "error": "",
        "created_at": created_at,
        "updated_at": created_at,
        "started_at": created_at,
        "completed_at": created_at,
        "duration_seconds": 1.5,
    }
    run.update(overrides)
    return run


class AgentRunHistoryTests(unittest.TestCase):
    def test_persisted_summaries_are_bounded_and_redact_common_secrets(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            prompt = "api_key=very-secret-value " + ("p" * 800)
            response = "Authorization: Bearer hidden-token\n" + ("r" * 2_500)
            agent_run_history.save_run_summaries(
                path,
                [sample_run("run_private", "2026-07-10T12:00:00-07:00", prompt=prompt, response=response)],
            )

            raw = path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            stored = payload["runs"][0]

        self.assertEqual(payload["schema_version"], agent_run_history.SCHEMA_VERSION)
        self.assertNotIn("very-secret-value", raw)
        self.assertNotIn("hidden-token", raw)
        self.assertNotIn("prompt\"", raw)
        self.assertLessEqual(len(stored["prompt_excerpt"]), agent_run_history.PROMPT_EXCERPT_LIMIT)
        self.assertLessEqual(len(stored["response_excerpt"]), agent_run_history.RESPONSE_EXCERPT_LIMIT)
        self.assertTrue(stored["prompt_truncated"])
        self.assertTrue(stored["response_truncated"])

    def test_private_history_redacts_extended_credentials_and_uses_private_modes(self):
        private_key = """-----BEGIN TEST PRIVATE KEY-----
super-private-material
-----END TEST PRIVATE KEY-----"""
        github_token = "github_" + "pat_1234567890abcdefghijklmnop"
        slack_token = "xox" + "b-123456789012-abcdefghijklmnop"
        secrets = " ".join(
            [
                github_token,
                slack_token,
                "abcdefghij.klmnopqrst.uvwxyz1234",
                private_key,
            ]
        )
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runtime" / "history.json"
            agent_run_history.save_run_summaries(
                path,
                [
                    sample_run(
                        "run_secrets",
                        "2026-07-10T12:00:00-07:00",
                        prompt=secrets,
                        response=secrets,
                    )
                ],
            )
            raw = path.read_text(encoding="utf-8")
            file_mode = stat.S_IMODE(path.stat().st_mode)
            directory_mode = stat.S_IMODE(path.parent.stat().st_mode)

        self.assertNotIn("github_" + "pat_", raw)
        self.assertNotIn("xox" + "b-", raw)
        self.assertNotIn("abcdefghij.klmnopqrst.uvwxyz1234", raw)
        self.assertNotIn("super-private-material", raw)
        if os.name != "nt":
            self.assertEqual(file_mode, 0o600)
            self.assertEqual(directory_mode, 0o700)

    def test_truncated_legacy_private_key_is_redacted_through_end_of_input(self):
        fragment = (
            "before\n-----BEGIN RSA PRIVATE KEY-----\n"
            "legacy-private-material-without-an-end-marker"
        )

        redacted, _ = agent_run_history.bounded_excerpt(fragment, 500)

        self.assertEqual(redacted, "before\n[REDACTED]")
        self.assertNotIn("legacy-private-material", redacted)

    def test_retention_is_newest_first_with_id_as_deterministic_tiebreaker(self):
        runs = [
            sample_run("run_a", "2026-07-10T12:00:00-07:00"),
            sample_run("run_c", "2026-07-10T12:00:00-07:00"),
            sample_run("run_b", "2026-07-10T13:00:00-07:00"),
        ]
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            agent_run_history.save_run_summaries(path, runs, retention=2)
            stored = json.loads(path.read_text(encoding="utf-8"))["runs"]

        self.assertEqual([item["id"] for item in stored], ["run_b", "run_c"])

    def test_load_marks_previously_active_run_interrupted(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            agent_run_history.save_run_summaries(
                path,
                [sample_run("run_active", "2026-07-10T12:00:00-07:00", status="running")],
            )
            runs, recovered = agent_run_history.load_run_summaries(
                path, now=lambda: "2026-07-10T14:00:00-07:00"
            )

        self.assertTrue(recovered)
        self.assertEqual(runs[0]["status"], "interrupted")
        self.assertEqual(runs[0]["completed_at"], "2026-07-10T14:00:00-07:00")
        self.assertIn("restarted", runs[0]["error"])

    def test_corrupt_and_unknown_schema_history_fall_back_to_empty(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(agent_run_history.load_run_summaries(path), ([], False))
            path.write_text(json.dumps({"schema_version": 99, "runs": []}), encoding="utf-8")
            self.assertEqual(agent_run_history.load_run_summaries(path), ([], False))

    def test_server_load_rewrites_recovered_status_and_uses_runtime_directory(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            path = data_dir / "runtime" / "agent-console-runs.json"
            agent_run_history.save_run_summaries(
                path,
                [sample_run("run_queued", "2026-07-10T12:00:00-07:00", status="queued")],
            )
            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                server.load_agent_console_runs()
                stored = json.loads(path.read_text(encoding="utf-8"))["runs"]

        self.assertEqual(server.AGENT_CONSOLE_RUNS["run_queued"]["status"], "interrupted")
        self.assertEqual(stored[0]["status"], "interrupted")
        server.AGENT_CONSOLE_RUNS.clear()

    def test_server_load_migrates_completed_history_to_current_redaction_and_modes(self):
        legacy_secret = "github_" + "pat_1234567890abcdefghijklmnop"
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            path = data_dir / "runtime" / "agent-console-runs.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": agent_run_history.SCHEMA_VERSION,
                        "runs": [
                            {
                                "id": "run_completed",
                                "agent_id": "default",
                                "agent_name": "default",
                                "model": "test/model",
                                "status": "completed",
                                "session_id": None,
                                "created_at": "2026-07-10T12:00:00-07:00",
                                "updated_at": "2026-07-10T12:01:00-07:00",
                                "completed_at": "2026-07-10T12:01:00-07:00",
                                "prompt_excerpt": legacy_secret,
                                "response_excerpt": legacy_secret,
                                "error_excerpt": "",
                                "events": [],
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            path.parent.chmod(0o755)
            path.chmod(0o644)

            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                server.load_agent_console_runs()
                raw = path.read_text(encoding="utf-8")
                file_mode = stat.S_IMODE(path.stat().st_mode)
                directory_mode = stat.S_IMODE(path.parent.stat().st_mode)

        self.assertNotIn(legacy_secret, raw)
        self.assertIn("[REDACTED]", raw)
        if os.name != "nt":
            self.assertEqual(file_mode, 0o600)
            self.assertEqual(directory_mode, 0o700)
        server.AGENT_CONSOLE_RUNS.clear()

    def test_server_load_restricts_corrupt_history_without_overwriting_it(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            path = data_dir / "runtime" / "agent-console-runs.json"
            path.parent.mkdir(parents=True)
            path.write_text("{broken", encoding="utf-8")
            path.parent.chmod(0o755)
            path.chmod(0o644)

            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                server.load_agent_console_runs()
                raw = path.read_text(encoding="utf-8")
                file_mode = stat.S_IMODE(path.stat().st_mode)
                directory_mode = stat.S_IMODE(path.parent.stat().st_mode)

        self.assertEqual(raw, "{broken")
        if os.name != "nt":
            self.assertEqual(file_mode, 0o600)
            self.assertEqual(directory_mode, 0o700)
        self.assertEqual(server.AGENT_CONSOLE_RUNS, {})

    @unittest.skipIf(os.name == "nt", "Symlink creation is not reliably available on Windows")
    def test_server_skips_history_file_symlink_without_changing_external_target(self):
        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as outside_dir:
            data_dir = Path(tmpdir)
            runtime_dir = data_dir / "runtime"
            runtime_dir.mkdir()
            outside = Path(outside_dir) / "external-history.json"
            outside.write_text(
                json.dumps(
                    {
                        "schema_version": agent_run_history.SCHEMA_VERSION,
                        "runs": [
                            {
                                "id": "external_run",
                                "status": "completed",
                                "created_at": "2026-07-11T12:00:00-07:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            outside.chmod(0o644)
            (runtime_dir / "agent-console-runs.json").symlink_to(outside)

            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                server.AGENT_CONSOLE_RUNS["existing"] = {"id": "existing"}
                server.load_agent_console_runs()

            self.assertEqual(server.AGENT_CONSOLE_RUNS, {})
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o644)
            self.assertIn("external_run", outside.read_text(encoding="utf-8"))

    @unittest.skipIf(os.name == "nt", "Symlink creation is not reliably available on Windows")
    def test_server_skips_symlinked_runtime_directory_outside_data_root(self):
        with TemporaryDirectory() as tmpdir, TemporaryDirectory() as outside_dir:
            data_dir = Path(tmpdir)
            outside = Path(outside_dir)
            outside_history = outside / "agent-console-runs.json"
            outside_history.write_text(
                json.dumps({"schema_version": agent_run_history.SCHEMA_VERSION, "runs": []}),
                encoding="utf-8",
            )
            outside.chmod(0o755)
            outside_history.chmod(0o644)
            (data_dir / "runtime").symlink_to(outside, target_is_directory=True)

            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                server.load_agent_console_runs()

            self.assertEqual(server.AGENT_CONSOLE_RUNS, {})
            self.assertEqual(stat.S_IMODE(outside.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(outside_history.stat().st_mode), 0o644)

    def test_starting_console_run_persists_summary_without_full_prompt(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "CONFIGURED_DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ), patch.object(
                server,
                "hermes_profiles_payload",
                return_value={"status": "available", "profiles": [{"id": "default"}]},
            ), patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
                server, "agent_console_model", return_value="test/model"
            ), patch.object(server.threading, "Thread"):
                server.load_agent_console_runs()
                payload, status = server.start_agent_console_run({
                    "agent_id": "hermes",
                    "prompt": "x" * (agent_run_history.PROMPT_EXCERPT_LIMIT + 25),
                })
                stored = json.loads(
                    (data_dir / "runtime" / "agent-console-runs.json").read_text(encoding="utf-8")
                )["runs"][0]

        self.assertEqual(status, 202)
        self.assertEqual(stored["id"], payload["run"]["id"])
        self.assertNotIn("prompt", stored)
        self.assertEqual(len(stored["prompt_excerpt"]), agent_run_history.PROMPT_EXCERPT_LIMIT)
        self.assertTrue(stored["prompt_truncated"])
        server.AGENT_CONSOLE_RUNS.clear()


if __name__ == "__main__":
    unittest.main()
