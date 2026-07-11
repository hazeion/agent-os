from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import agent_run_history
import server


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


class AgentRunEventTests(unittest.TestCase):
    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()

    def make_run(self, run_id: str = "run_events") -> dict:
        return {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "default",
            "status": "running",
            "prompt": "Test events",
            "response": "",
            "error": "",
            "events": [],
            "created_at": "2026-07-10T12:00:00-07:00",
            "updated_at": "2026-07-10T12:00:00-07:00",
        }

    def test_events_have_versioned_structured_monotonic_contract(self):
        run = self.make_run()
        server.agent_console_event(run, "Queued", "queued", {"phase": "queue"})
        server.agent_console_event(run, "Working", "status", {"elapsed_seconds": 2})

        first, second = run["events"]
        self.assertEqual(first["schema_version"], 1)
        self.assertEqual(first["run_id"], run["id"])
        self.assertEqual(first["type"], "queued")
        self.assertEqual(first["kind"], "queued")
        self.assertEqual(first["display_text"], "Queued")
        self.assertEqual(first["message"], "Queued")
        self.assertEqual(first["data"], {"phase": "queue"})
        self.assertEqual([first["cursor"], second["cursor"]], [1, 2])
        self.assertEqual(run["event_cursor"], 2)

    def test_full_run_api_remains_compatible_and_cursor_api_is_incremental(self):
        run = self.make_run()
        server.agent_console_event(run, "One")
        server.agent_console_event(run, "Two")
        server.agent_console_event(run, "Three", "complete")
        server.AGENT_CONSOLE_RUNS[run["id"]] = run

        full, full_status = server.agent_console_run_payload(run["id"])
        delta, delta_status = server.agent_console_run_payload(run["id"], "1")

        self.assertEqual(full_status, 200)
        self.assertEqual(len(full["run"]["events"]), 3)
        self.assertNotIn("next_cursor", full)
        self.assertEqual(delta_status, 200)
        self.assertEqual([event["cursor"] for event in delta["events"]], [2, 3])
        self.assertEqual([event["cursor"] for event in delta["run"]["events"]], [2, 3])
        self.assertEqual(delta["next_cursor"], 3)
        self.assertFalse(delta["cursor_reset_required"])

    def test_cursor_validation_fails_safe_and_reports_retention_gap(self):
        run = self.make_run()
        for index in range(agent_run_history.EVENT_RETENTION + 3):
            server.agent_console_event(run, f"Update {index}")
        server.AGENT_CONSOLE_RUNS[run["id"]] = run

        malformed, malformed_status = server.agent_console_run_payload(run["id"], "nope")
        ahead, ahead_status = server.agent_console_run_payload(run["id"], "999")
        stale, stale_status = server.agent_console_run_payload(run["id"], "0")

        self.assertEqual(malformed_status, 400)
        self.assertIn("cursor", malformed["error"].lower())
        self.assertEqual(ahead_status, 409)
        self.assertEqual(ahead["current_cursor"], agent_run_history.EVENT_RETENTION + 3)
        self.assertEqual(stale_status, 200)
        self.assertTrue(stale["cursor_reset_required"])
        self.assertEqual(len(stale["events"]), agent_run_history.EVENT_RETENTION)

    def test_v1_history_migrates_and_v2_round_trip_preserves_events(self):
        legacy = {
            "schema_version": 1,
            "runs": [{
                "id": "run_legacy",
                "status": "completed",
                "prompt_excerpt": "hello",
                "response_excerpt": "done",
                "error_excerpt": "",
                "created_at": "2026-07-10T12:00:00-07:00",
                "events": [{
                    "id": "old_event",
                    "kind": "status",
                    "message": "api_key=secret-value",
                    "timestamp": "2026-07-10T12:00:01-07:00",
                }],
            }],
        }
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "runs.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            runs, recovered = agent_run_history.load_run_summaries(path)
            agent_run_history.save_run_summaries(path, runs)
            stored_text = path.read_text(encoding="utf-8")
            stored = json.loads(stored_text)

        self.assertFalse(recovered)
        self.assertEqual(runs[0]["events"][0]["sequence"], 1)
        self.assertEqual(runs[0]["events"][0]["run_id"], "run_legacy")
        self.assertEqual(stored["schema_version"], 2)
        self.assertNotIn("secret-value", stored_text)
        self.assertEqual(stored["runs"][0]["event_cursor"], 1)

    def test_malformed_persisted_events_are_skipped_or_normalized(self):
        events = agent_run_history.normalize_events("run_safe", [
            "bad",
            {"timestamp": "2026-07-10T12:00:00-07:00", "type": "INVALID TYPE", "message": "ok"},
            {"timestamp": None, "message": "missing timestamp"},
        ])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "status")

    def test_structured_event_data_redacts_secret_key_values(self):
        events = agent_run_history.normalize_events("run_private", [{
            "timestamp": "2026-07-10T12:00:00-07:00",
            "message": "Configured provider",
            "data": {
                "api_key": "plain-secret-value",
                "nested": {"access_token": "another-secret", "phase": "setup"},
            },
        }])

        serialized = json.dumps(events)
        self.assertNotIn("plain-secret-value", serialized)
        self.assertNotIn("another-secret", serialized)
        self.assertEqual(events[0]["data"]["api_key"], "[REDACTED]")
        self.assertEqual(events[0]["data"]["nested"]["phase"], "setup")

    def test_frontend_uses_cursor_polling_and_merges_events(self):
        self.assertIn("async function fetchAgentConsoleRun(runId, afterCursor", CORE_JS)
        self.assertIn("?after=${encodeURIComponent(afterCursor)}", CORE_JS)
        self.assertIn("function mergeAgentConsoleRunUpdate", APP_JS)
        self.assertIn("payload.cursor_reset_required", APP_JS)
        self.assertIn("event.display_text || event.message", APP_JS)
        self.assertIn('query.get("after", [None])[0]', SERVER)


if __name__ == "__main__":
    unittest.main()
