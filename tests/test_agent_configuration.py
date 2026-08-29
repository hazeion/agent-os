from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from agent_registry import AgentRegistry
from mentat import local_bridge
from private_state import history_path
import server
from tests.sqlite_authority_support import ensure_run_sqlite_authority


class AgentConfigurationTests(unittest.TestCase):
    def prepare(self, root: Path, *, shared: bool = False) -> AgentRegistry:
        ensure_run_sqlite_authority(root, history_path(root))
        registry = AgentRegistry(root, supported_runtime_types=("hermes", "codex", "vercel"))
        registry.create_agent(
            agent_id="agent_builder",
            name="Builder",
            runtime_config_id="config_builder",
            runtime_type="hermes",
            runtime_agent_ref="private-builder-profile",
            capabilities=("run.start",),
        )
        if shared:
            registry.create_agent(
                agent_id="agent_shared",
                name="Shared",
                runtime_config_id="config_shared",
                runtime_type="hermes",
                runtime_agent_ref="private-builder-profile",
                capabilities=("run.start",),
            )
        return registry

    @staticmethod
    def inventory() -> dict:
        return {
            "profile_id": "private-builder-profile",
            "current_provider": "openai",
            "current_model": "gpt-current",
            "providers": [
                {"id": "openai", "name": "OpenAI", "authenticated": True, "current": True, "models": ["gpt-current"]},
                {"id": "anthropic", "name": "Anthropic", "authenticated": True, "current": False, "models": ["claude-next"]},
                {"id": "hidden", "name": "Hidden", "authenticated": False, "models": ["secret-model"]},
                {"id": "missing-auth", "name": "Missing", "models": ["missing-model"]},
                {"id": "null-auth", "name": "Null", "authenticated": None, "models": ["null-model"]},
                {"id": "string-auth", "name": "String", "authenticated": "true", "models": ["string-model"]},
                {"id": "numeric-auth", "name": "Numeric", "authenticated": 1, "models": ["numeric-model"]},
            ],
            "capabilities": {"providers.switch": True},
            "credential_source": "must-not-cross",
        }

    def test_configuration_projects_authenticated_inventory_without_private_binding(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "_agent_configuration_inventory_locked", return_value=(self.inventory(), "", "")),
                patch.object(server, "_provider_mutation_active_run", return_value=(None, None)),
            ):
                payload = server.mentat_agent_configuration_payload("agent_builder")

        self.assertEqual(payload["agent_id"], "agent_builder")
        self.assertTrue(payload["mutable"])
        self.assertEqual([item["id"] for item in payload["providers"]], ["openai", "anthropic"])
        rendered = str(payload)
        self.assertNotIn("private-builder-profile", rendered)
        self.assertNotIn("credential_source", rendered)
        self.assertNotIn("secret-model", rendered)
        self.assertNotIn("missing-model", rendered)
        self.assertNotIn("null-model", rendered)
        self.assertNotIn("string-model", rendered)
        self.assertNotIn("numeric-model", rendered)

    def test_codex_is_read_only(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = self.prepare(root)
            registry.create_agent(
                agent_id="agent_codex",
                name="Codex",
                runtime_config_id="config_codex",
                runtime_type="codex",
                runtime_agent_ref="default",
                capabilities=("run.start",),
            )
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "_agent_configuration_inventory_locked", return_value=(self.inventory(), "", "")),
                patch.object(server, "_provider_mutation_active_run", return_value=(None, None)),
            ):
                codex = server.mentat_agent_configuration_payload("agent_codex")
                rejected, status = server.preview_mentat_agent_configuration(
                    "agent_codex", {"provider": "anthropic", "model": "claude-next"}
                )

        self.assertEqual(codex["state"], "read_only")
        self.assertEqual(codex["providers"], [])
        self.assertNotIn("runtime_agent_ref", str(codex))
        self.assertEqual(status, 409)
        self.assertEqual(rejected["error_code"], "agent_configuration.read_only")

    def test_preview_and_confirm_bind_canonical_agent_to_private_profile(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            preview_source = {
                "ok": True,
                "requires_confirmation": True,
                "confirmation_id": "provider_switch_" + "a" * 24,
                "profile_id": "private-builder-profile",
                "current": {"provider": "openai", "model": "gpt-current"},
                "target": {"provider": "anthropic", "provider_name": "Anthropic", "model": "claude-next"},
                "effects": [],
                "warnings": [],
            }
            confirmed_inventory = {
                **self.inventory(),
                "current_provider": "anthropic",
                "current_model": "claude-next",
            }
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "_preview_agent_console_provider_switch_locked", return_value=(preview_source, 200)) as preview_call,
                patch.object(server, "_switch_agent_console_provider_locked", return_value=({"provider": "anthropic", "model": "claude-next"}, 200)) as confirm_call,
                patch.object(server, "_agent_configuration_inventory_locked", return_value=(confirmed_inventory, "", "")),
                patch.object(server, "_provider_mutation_active_run", return_value=(None, None)),
            ):
                preview, preview_status = server.preview_mentat_agent_configuration(
                    "agent_builder", {"provider": "anthropic", "model": "claude-next"}
                )
                result, result_status = server.confirm_mentat_agent_configuration(
                    "agent_builder",
                    {"provider": "anthropic", "model": "claude-next", "confirmation_id": preview["confirmation_id"]},
                )

        self.assertEqual(preview_status, 200)
        self.assertEqual(result_status, 200)
        self.assertEqual(preview["agent_id"], "agent_builder")
        self.assertNotIn("private-builder-profile", str(preview))
        self.assertEqual(result["configuration"]["agent_id"], "agent_builder")
        self.assertEqual(preview_call.call_args.args[0]["agent_id"], "private-builder-profile")
        self.assertEqual(confirm_call.call_args.args[0]["agent_id"], "private-builder-profile")

    def test_remote_hermes_is_visible_but_never_browser_mutable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.prepare(root)
            remote = SimpleNamespace(mode="remote")
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "_agent_configuration_inventory_locked", return_value=(self.inventory(), "", "Remote Hermes configuration is read-only.")),
                patch.object(server, "_provider_mutation_active_run", return_value=(None, None)),
                patch.object(server, "_provider_mutation_transport_locked", return_value=(remote, None, 200)),
                patch.object(server, "_preview_agent_console_provider_switch_locked") as forbidden_preview,
                patch.object(server, "_switch_agent_console_provider_locked") as forbidden_confirm,
            ):
                projected = server.mentat_agent_configuration_payload("agent_builder")
                preview, preview_status = server.preview_mentat_agent_configuration(
                    "agent_builder", {"provider": "anthropic", "model": "claude-next"}
                )
                confirmed, confirm_status = server.confirm_mentat_agent_configuration(
                    "agent_builder", {"provider": "anthropic", "model": "claude-next", "confirmation_id": "provider_switch_" + "a" * 24}
                )

        self.assertEqual(projected["state"], "read_only")
        self.assertFalse(projected["mutable"])
        self.assertIn("Remote Hermes", projected["explanation"])
        self.assertEqual(projected["providers"], [])
        self.assertNotIn("claude-next", str(projected))
        self.assertEqual((preview_status, confirm_status), (409, 409))
        self.assertEqual(preview["error_code"], "agent_configuration.read_only")
        self.assertEqual(confirmed["error_code"], "agent_configuration.read_only")
        forbidden_preview.assert_not_called()
        forbidden_confirm.assert_not_called()

    def test_bridge_rejects_private_or_malformed_configuration(self):
        safe = {
            "schema_version": 1,
            "agent_id": "agent_builder",
            "runtime_type": "hermes",
            "state": "ready",
            "mutable": True,
            "active_run": False,
            "current": {"provider": "openai", "model": "gpt", "effort": "runtime_default"},
            "providers": [{"id": "openai", "name": "OpenAI", "current": True, "models": ["gpt"]}],
            "efforts": [{"id": "runtime_default", "name": "Runtime default"}],
            "explanation": "",
        }
        self.assertEqual(local_bridge._public_agent_configuration(safe)["agent_id"], "agent_builder")
        with self.assertRaises(local_bridge.BridgeAgentConfigurationProjectionError):
            local_bridge._public_agent_configuration({**safe, "runtime_agent_ref": "private"})
        with self.assertRaises(local_bridge.BridgeAgentConfigurationProjectionError):
            local_bridge._public_agent_configuration({**safe, "providers": [{**safe["providers"][0], "token": "secret"}]})


if __name__ == "__main__":
    unittest.main()
