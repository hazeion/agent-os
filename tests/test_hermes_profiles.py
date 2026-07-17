from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import hermes_profiles
import server


class CompletedResult:
    def __init__(self, payload=None, *, returncode=0, stdout=None, stderr=""):
        self.returncode = returncode
        self.stdout = json.dumps(payload) if stdout is None and payload is not None else (stdout or "")
        self.stderr = stderr


class HermesProfileDiscoveryTests(unittest.TestCase):
    def sample_payload(self):
        return {
            "schema_version": 1,
            "hermes": {"version": "0.18.2", "release_date": "2026.7.7.2"},
            "active_profile": "default",
            "capabilities": {
                "profiles.read": True,
                "profiles.create": True,
                "profiles.describe": True,
                "profiles.identity.read": True,
                "profiles.identity.write": True,
                "profiles.rename": True,
                "profiles.delete": True,
                "unexpected": True,
            },
            "profiles": [
                {
                    "id": "default",
                    "name": "default",
                    "is_default": True,
                    "description": "General Hermes profile",
                    "provider": "openai-codex",
                    "model": "gpt-5.6-luna",
                    "skill_count": 75,
                    "enabled_builtin_skill_count": 1,
                    "gateway_running": True,
                    "path": "/private/secret/path",
                    "distribution": {},
                }
            ],
        }

    def test_discovery_uses_hermes_runtime_and_normalizes_public_fields(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return CompletedResult(self.sample_payload())

        payload = hermes_profiles.discover_hermes_profiles(
            "/opt/hermes/python",
            Path("/home/user/.hermes"),
            cwd="/app",
            runner=runner,
        )

        self.assertEqual(payload["status"], "available")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["profiles"][0]["id"], "default")
        self.assertEqual(payload["profiles"][0]["enabled_builtin_skill_count"], 1)
        self.assertNotIn("path", payload["profiles"][0])
        self.assertNotIn("unexpected", payload["capabilities"])
        self.assertEqual(calls[0][0][:2], ["/opt/hermes/python", "-c"])
        self.assertEqual(calls[0][1]["env"]["HERMES_HOME"], str(Path("/home/user/.hermes")))
        self.assertFalse(calls[0][1]["check"])

    def test_missing_runtime_fails_closed(self):
        payload = hermes_profiles.discover_hermes_profiles(None, "/home/user/.hermes")

        self.assertEqual(payload["status"], "unavailable")
        self.assertEqual(payload["error"]["code"], "runtime_unavailable")
        self.assertTrue(all(value is False for value in payload["capabilities"].values()))

    def test_timeout_fails_closed(self):
        def runner(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))

        payload = hermes_profiles.discover_hermes_profiles(
            "/opt/hermes/python", "/home/user/.hermes", runner=runner
        )

        self.assertEqual(payload["error"]["code"], "runtime_timeout")
        self.assertEqual(payload["profiles"], [])

    def test_invalid_json_and_unsupported_schema_fail_closed(self):
        invalid = hermes_profiles.discover_hermes_profiles(
            "/opt/hermes/python",
            "/home/user/.hermes",
            runner=lambda *args, **kwargs: CompletedResult(stdout="not-json"),
        )
        unsupported = hermes_profiles.discover_hermes_profiles(
            "/opt/hermes/python",
            "/home/user/.hermes",
            runner=lambda *args, **kwargs: CompletedResult({"schema_version": 99}),
        )

        self.assertEqual(invalid["error"]["code"], "invalid_payload")
        self.assertEqual(unsupported["error"]["code"], "unsupported_schema")

    def test_malformed_profile_list_and_runtime_stderr_do_not_leak(self):
        malformed = hermes_profiles.discover_hermes_profiles(
            "/opt/hermes/python",
            "/home/user/.hermes",
            runner=lambda *args, **kwargs: CompletedResult(
                {"schema_version": 1, "capabilities": {"profiles.read": True}, "profiles": {}}
            ),
        )
        failed = hermes_profiles.discover_hermes_profiles(
            "/opt/hermes/python",
            "/home/user/.hermes",
            runner=lambda *args, **kwargs: CompletedResult(
                returncode=2,
                stderr="provider token sk-secret-value",
            ),
        )

        self.assertEqual(malformed["error"]["code"], "invalid_payload")
        self.assertEqual(failed["error"]["code"], "runtime_failed")
        self.assertNotIn("sk-secret-value", json.dumps(failed))

    def test_server_exposes_profile_discovery_route_through_adapter(self):
        expected = {"schema_version": 1, "status": "available", "profiles": []}
        with patch.object(server, "hermes_python_path", return_value="/opt/hermes/python"), patch.object(
            server, "discover_hermes_profiles", return_value=expected
        ) as discover:
            payload = server.API_ROUTES["/api/hermes/profiles"]()

        self.assertEqual(payload, expected)
        discover.assert_called_once_with("/opt/hermes/python", server.HERMES_HOME, cwd=server.BASE_DIR)

    def test_helper_uses_profile_api_not_human_formatted_cli_output(self):
        self.assertIn("profiles_module.list_profiles()", hermes_profiles.HERMES_PROFILE_DISCOVERY_SCRIPT)
        self.assertIn("get_disabled_skills(config)", hermes_profiles.HERMES_PROFILE_DISCOVERY_SCRIPT)
        self.assertNotIn("profile list", hermes_profiles.HERMES_PROFILE_DISCOVERY_SCRIPT)


if __name__ == "__main__":
    unittest.main()
