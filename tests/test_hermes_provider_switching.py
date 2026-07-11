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
            ]
        }
        _, unauthenticated = switching.preview_provider_switch("default", "anthropic", "claude", inventory)
        _, unlisted = switching.preview_provider_switch("default", "openai-codex", "other", inventory)
        self.assertEqual(unauthenticated, 400)
        self.assertEqual(unlisted, 400)

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


if __name__ == "__main__":
    unittest.main()
