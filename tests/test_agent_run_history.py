from __future__ import annotations

import json
from pathlib import Path
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
            with patch.object(server, "DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
            ):
                server.load_agent_console_runs()
                stored = json.loads(path.read_text(encoding="utf-8"))["runs"]

        self.assertEqual(server.AGENT_CONSOLE_RUNS["run_queued"]["status"], "interrupted")
        self.assertEqual(stored[0]["status"], "interrupted")
        server.AGENT_CONSOLE_RUNS.clear()

    def test_starting_console_run_persists_summary_without_full_prompt(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            with patch.object(server, "DATA_DIR", data_dir), patch.object(
                server, "AGENT_CONSOLE_HISTORY_LOADED", False
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
