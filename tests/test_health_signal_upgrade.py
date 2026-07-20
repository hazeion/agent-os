from pathlib import Path
import sys
import unittest
from unittest.mock import patch

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

    def test_remote_health_replaces_local_hermes_path_checks(self):
        diagnostics = {
            "mode": "remote",
            "status": "degraded",
            "category": "degraded",
            "label": "Workshop Hermes",
            "summary": "Remote Hermes is connected but reports degraded readiness.",
            "liveness": "ok",
            "version": "0.18.2",
            "model": "anthropic/claude-test",
            "readiness": {"config": "ok", "gateway": "degraded"},
            "capabilities": ["run_submission", "run_stop"],
        }
        with patch.object(server, "remote_hermes_diagnostics", return_value=diagnostics):
            payload = server.health()
        subsystem_keys = {item["key"] for item in payload["subsystems"]}
        self.assertEqual(subsystem_keys, {"remote_hermes", "calendar", "host_resources"})
        self.assertNotIn("hermes_home", payload)
        self.assertNotIn("state_db_exists", payload)
        remote = next(item for item in payload["subsystems"] if item["key"] == "remote_hermes")
        self.assertEqual(remote["category"], "degraded")
        self.assertEqual(remote["model"], "anthropic/claude-test")

    def test_remote_config_summary_does_not_read_local_config_metadata(self):
        class RejectingConfigPath:
            def exists(self):
                raise AssertionError("local config must not be inspected")

        connection = {
            "status": "configured",
            "selection": {
                "mode": "remote",
                "label": "Workshop Hermes",
                "configured": True,
            },
        }
        with patch.object(server, "public_connection_payload", return_value=connection), patch.object(
            server,
            "CONFIG_PATH",
            RejectingConfigPath(),
        ):
            payload = server.hermes_config()
        self.assertEqual(payload["mode"], "remote")
        self.assertEqual(payload["summary"], {"connection": "Workshop Hermes", "mode": "remote"})
        self.assertNotIn("size", payload)
        self.assertNotIn("modified_at", payload)

    def test_disk_labels_follow_the_host_platform(self):
        payload = server.health()
        if sys.platform.startswith("win"):
            self.assertTrue(set(payload["disk"]).issubset({"C:/", "E:/"}))
        else:
            self.assertEqual(set(payload["disk"]), {str(ROOT.anchor or "/")})


    def test_health_logic_lives_in_dedicated_module(self):
        server_text = (ROOT / "server.py").read_text(encoding="utf-8")
        health_text = (ROOT / "health_checks.py").read_text(encoding="utf-8")
        self.assertIn("class HealthContext", health_text)
        self.assertIn("def health(ctx: HealthContext)", health_text)
        self.assertIn("def state_db_health(ctx: HealthContext)", health_text)
        self.assertIn("def calendar_health(ctx: HealthContext)", health_text)
        self.assertIn("def remote_hermes_health(ctx: HealthContext", health_text)
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
        self.assertIn("item.key === 'remote_hermes'", APP_JS)
        self.assertIn("payload.mode === 'remote'", APP_JS)


if __name__ == "__main__":
    unittest.main()
