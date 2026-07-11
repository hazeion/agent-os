import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import hermes_provider_switching as switching


class HermesProviderSwitchingTests(unittest.TestCase):
    def test_inventory_returns_only_safe_authenticated_metadata(self):
        raw = {
            "profile_id": "builder",
            "current_provider": "openai-codex",
            "current_model": "gpt-5.6-luna",
            "providers": [
                {"id": "openai-codex", "name": "OpenAI Codex", "authenticated": True, "current": True, "models": ["gpt-5.6-luna"]},
                {"id": "anthropic", "name": "Anthropic", "authenticated": False, "models": ["claude"]},
            ],
            "token": "must-not-pass-through",
        }

        def runner(*args, **kwargs):
            return SimpleNamespace(returncode=0, stdout=json.dumps(raw), stderr="")

        payload = switching.provider_inventory("/opt/hermes/python", "/home/user/.hermes", "builder", cwd="/app", runner=runner)

        self.assertEqual([row["id"] for row in payload["providers"]], ["openai-codex"])
        self.assertNotIn("token", json.dumps(payload).lower())
        self.assertEqual(payload["current_model"], "gpt-5.6-luna")

    def test_preview_binds_profile_and_current_and_target_state(self):
        inventory = {
            "current_provider": "openai-codex",
            "current_model": "gpt-5.6-luna",
            "providers": [{"id": "anthropic", "name": "Anthropic", "authenticated": True, "models": ["claude-sonnet"]}],
            "capabilities": {"providers.switch": True},
        }
        preview, status = switching.preview_provider_switch("builder", "anthropic", "claude-sonnet", inventory)
        changed, _ = switching.preview_provider_switch("reviewer", "anthropic", "claude-sonnet", inventory)

        self.assertEqual(status, 200)
        self.assertTrue(preview["requires_confirmation"])
        self.assertNotEqual(preview["confirmation_id"], changed["confirmation_id"])

    def test_preview_rejects_unauthenticated_provider_or_unlisted_model(self):
        inventory = {
            "providers": [
                {"id": "anthropic", "name": "Anthropic", "authenticated": False, "models": ["claude"]},
                {"id": "openai-codex", "name": "OpenAI Codex", "authenticated": True, "models": ["gpt"]},
            ],
            "capabilities": {"providers.switch": True},
        }
        _, unauthenticated = switching.preview_provider_switch("default", "anthropic", "claude", inventory)
        _, unlisted = switching.preview_provider_switch("default", "openai-codex", "other", inventory)
        self.assertEqual(unauthenticated, 400)
        self.assertEqual(unlisted, 400)

    def test_preview_fails_closed_when_runtime_switch_capability_is_unavailable(self):
        inventory = {
            "providers": [
                {
                    "id": "openai-codex",
                    "name": "OpenAI Codex",
                    "authenticated": True,
                    "models": ["gpt"],
                }
            ],
            "capabilities": {"providers.switch": False},
        }

        payload, status = switching.preview_provider_switch(
            "default", "openai-codex", "gpt", inventory
        )

        self.assertEqual(status, 503)
        self.assertIn("does not expose", payload["error"])

    def test_switch_executes_fixed_hermes_runtime_helper(self):
        calls = []

        def runner(args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout=json.dumps({"ok": True}), stderr="")

        payload, error = switching.apply_provider_switch(
            "/opt/hermes/python", "/home/user/.hermes", "builder", "anthropic", "claude-sonnet", cwd=Path("/app"), runner=runner
        )
        self.assertEqual(error, "")
        self.assertTrue(payload["ok"])
        self.assertEqual(calls[0][0][:2], ["/opt/hermes/python", "-c"])
        self.assertEqual(calls[0][0][-3:], ["builder", "anthropic", "claude-sonnet"])
        self.assertNotIn("shell", calls[0][1])

    def test_runtime_failure_logs_metadata_without_untrusted_stderr_contents(self):
        private_key_fragment = "-----BEGIN RSA PRIVATE KEY-----\nprivate-material-without-end"
        secrets = (
            '{"token":"ordinary-secret-value","api_key":"another-secret"} '
            "Authorization: Basic dXNlcjpwYXNz "
            f"token=hidden-value sk-secret-value {private_key_fragment}"
        )

        def runner(*args, **kwargs):
            return SimpleNamespace(
                returncode=2,
                stdout="",
                stderr=secrets,
            )

        with self.assertLogs(switching.LOGGER, level="WARNING") as captured:
            payload = switching.provider_inventory(
                "/opt/hermes/python",
                "/home/user/.hermes",
                "builder",
                cwd="/app",
                runner=runner,
            )

        rendered = "\n".join(captured.output)
        self.assertIn("status 2", rendered)
        self.assertIn(f"stderr suppressed ({len(secrets)} characters)", rendered)
        self.assertNotIn("ordinary-secret-value", rendered)
        self.assertNotIn("another-secret", rendered)
        self.assertNotIn("dXNlcjpwYXNz", rendered)
        self.assertNotIn("hidden-value", rendered)
        self.assertNotIn("sk-secret-value", rendered)
        self.assertNotIn("private-material", rendered)
        self.assertNotIn("hidden-value", json.dumps(payload))


if __name__ == "__main__":
    unittest.main()
