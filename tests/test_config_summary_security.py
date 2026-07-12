from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from health_checks import config_health
import server


class ConfigSummarySecurityTests(unittest.TestCase):
    def test_summary_reads_only_allowlisted_semantic_paths(self):
        config = """
credentials:
  default: password=hunter2
  provider: private-provider-token
model:
  default: openai/gpt-safe
provider: openrouter
agent:
  max_turns: 42
reasoning_effort: high
""".lstrip()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            path.write_text(config, encoding="utf-8")
            discovery = {
                "status": "available",
                "profiles": [
                    {
                        "id": "default",
                        "is_default": True,
                        "model": "openai/gpt-safe",
                        "provider": "openrouter",
                    }
                ],
            }
            with patch.object(server, "CONFIG_PATH", path), patch.object(
                server, "hermes_profiles_payload", return_value=discovery
            ):
                payload = server.hermes_config()

        serialized = json.dumps(payload)
        self.assertTrue(payload["exists"])
        self.assertEqual(payload["summary"].get("default_model"), "openai/gpt-safe")
        self.assertEqual(payload["summary"].get("provider"), "openrouter")
        self.assertNotIn("hunter2", serialized)
        self.assertNotIn("private-provider-token", serialized)
        self.assertNotIn(str(path), serialized)

    def test_unknown_secret_shapes_never_pass_through_the_browser_payload(self):
        config = """
credentials:
  arbitrary: ordinary-looking-secret-value
model:
  default: safe/model
""".lstrip()
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            path.write_text(config, encoding="utf-8")
            with patch.object(server, "CONFIG_PATH", path), patch.object(
                server,
                "hermes_profiles_payload",
                return_value={"status": "available", "profiles": []},
            ):
                payload = server.hermes_config()

        self.assertNotIn("ordinary-looking-secret-value", json.dumps(payload))

    def test_unavailable_profile_discovery_does_not_report_a_healthy_summary(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            path.write_text("credential: must-not-leak\n", encoding="utf-8")
            with patch.object(server, "CONFIG_PATH", path), patch.object(
                server,
                "hermes_profiles_payload",
                return_value={"status": "unavailable", "profiles": []},
            ):
                payload = server.hermes_config()
                subsystem = config_health(server.health_context())

        self.assertTrue(payload["exists"])
        self.assertIn("unavailable", payload["error"].lower())
        self.assertEqual(subsystem["status"], "error")
        self.assertNotIn("must-not-leak", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
