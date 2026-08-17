from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
CORE = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")


class HermesNativeEventUiContractTests(unittest.TestCase):
    def test_same_origin_event_source_uses_fixed_endpoint(self):
        self.assertIn("hermesEvents: '/api/hermes/events'", CORE)
        self.assertIn("new EventSource(endpoints.hermesEvents)", APP)
        self.assertIn("source.addEventListener('projections'", APP)
        self.assertIn("void runHermesFetchStream()", APP)
        self.assertIn("Accept: 'text/event-stream'", APP)
        self.assertIn("credentials: 'same-origin'", APP)
        self.assertIn('parsed.path == "/api/hermes/events"', SERVER)

    def test_browser_validates_and_coalesces_projection_frames(self):
        self.assertIn("payload?.schema_version !== 1", APP)
        self.assertIn("HERMES_EVENT_PROJECTIONS.has(projection)", APP)
        self.assertIn("hermesPendingProjections: new Set()", CORE)
        self.assertIn("}, 150);", APP)
        self.assertIn("if (buffer.length > 16_384)", APP)
        self.assertIn("/^[0-9]{1,16}$/.test(eventId)", APP)

    def test_kanban_wakeup_uses_existing_verified_readback_and_polling_remains(self):
        self.assertIn("await refreshHomeDelegations()", APP)
        self.assertIn("schedulePendingHermesProjectionRefresh()", APP)
        self.assertIn("setInterval(refresh, REFRESH_MS)", APP)
        self.assertIn("reconciliation_interval=60.0", SERVER)

    def test_overlapping_kanban_hint_is_drained_after_active_readback(self):
        contract = Path(__file__).with_name("hermes_projection_refresh_contract.mjs")
        result = subprocess.run(
            ["node", str(contract)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_stream_does_not_expose_webhook_payload_fields(self):
        stream = SERVER[
            SERVER.index("def send_hermes_browser_events"):
            SERVER.index("def send_attachment_content")
        ]
        for private_name in (
            "tool_input", "workspace_path", "summary", "reason", "task_id",
            "session_id", "model", "provider", "usage", "binding_id",
        ):
            self.assertNotIn(private_name, stream)


if __name__ == "__main__":
    unittest.main()
