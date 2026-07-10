from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "public" / "index.html").read_text(encoding="utf-8")
import health_checks
import server


class HealthSignalUpgradeTests(unittest.TestCase):
    def test_health_payload_reports_subsystems_and_overall_status(self):
        payload = server.health()
        self.assertIn("status", payload)
        self.assertIn(payload["status"], {"healthy", "degraded", "error"})
        self.assertIsInstance(payload.get("subsystems"), list)
        self.assertGreaterEqual(len(payload["subsystems"]), 5)
        self.assertIn("summary", payload)
        subsystem_keys = {item["key"] for item in payload["subsystems"]}
        self.assertEqual(
            subsystem_keys,
            {"state_db", "config", "calendar", "cron", "host_resources"},
        )

    def test_overall_health_matches_worst_subsystem(self):
        payload = server.health()
        worst = max(
            payload["subsystems"],
            key=lambda item: server.HEALTH_STATUS_RANK[item["status"]],
        )
        self.assertEqual(payload["status"], worst["status"])


    def test_health_logic_lives_in_dedicated_module(self):
        server_text = (ROOT / "server.py").read_text(encoding="utf-8")
        health_text = (ROOT / "health_checks.py").read_text(encoding="utf-8")
        self.assertIn("class HealthContext", health_text)
        self.assertIn("def health(ctx: HealthContext)", health_text)
        self.assertIn("def state_db_health(ctx: HealthContext)", health_text)
        self.assertIn("def calendar_health(ctx: HealthContext)", health_text)
        self.assertIn("return build_health_payload(health_context())", server_text)
        self.assertNotIn("def state_db_health():", server_text)
        self.assertNotIn("def windows_memory():", server_text)

    def test_health_status_helpers_remain_available_through_server_import(self):
        self.assertEqual(server.HEALTH_STATUS_RANK, health_checks.HEALTH_STATUS_RANK)
        self.assertEqual(health_checks.worst_health_status("healthy", "degraded"), "degraded")
        self.assertEqual(health_checks.status_label("error"), "Error")

    def test_sidebar_and_settings_render_real_health_sections(self):
        self.assertNotIn("id=\"health-status-pill\"", INDEX_HTML)
        self.assertIn("id=\"health-summary\"", INDEX_HTML)
        self.assertIn("function renderHealth(payload = {})", APP_JS)
        self.assertIn("payload.subsystems", APP_JS)
        self.assertIn("payload.summary", APP_JS)


if __name__ == "__main__":
    unittest.main()
