from pathlib import Path
import unittest
from unittest.mock import patch

from command_manifest import command_manifest_payload
from mentat import local_bridge
import server


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")


class CommandManifestTests(unittest.TestCase):
    def test_manifest_is_versioned_mentat_allowlist(self):
        payload = command_manifest_payload()

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["source"], "mentat")
        self.assertTrue(payload["capabilities"]["commands.manifest.read"])
        self.assertFalse(payload["capabilities"]["commands.external_source"])
        self.assertFalse(payload["capabilities"]["commands.hermes_cli_passthrough"])
        self.assertEqual([item["command"] for item in payload["commands"]], ["/model", "/new", "/steer", "/help"])
        for command in payload["commands"]:
            self.assertIn("handler", command)
            self.assertIsInstance(command["arguments"], list)
            self.assertTrue(command["description"])
            self.assertIn(command["safety"], {"read_only", "local_state", "remote_control"})

        steer = next(item for item in payload["commands"] if item["command"] == "/steer")
        self.assertEqual(steer["handler"], "agent_console.steer_active_run")
        self.assertTrue(steer["arguments"][0]["variadic"])

    def test_payload_is_not_mutable_shared_state(self):
        first = command_manifest_payload()
        first["commands"].append({"command": "/unsafe"})
        self.assertNotIn("/unsafe", [item["command"] for item in command_manifest_payload()["commands"]])

    def test_private_bridge_accepts_only_the_exact_complete_manifest(self):
        payload, status = local_bridge.bridge_command_manifest_payload()
        self.assertEqual(status, 200)
        self.assertEqual(payload["source"], "mentat")
        self.assertEqual(
            [item["command"] for item in payload["commands"]],
            ["/model", "/new", "/steer", "/help"],
        )

        original = server.command_manifest_payload
        for invalid in (
            lambda: {**original(), "private": True},
            lambda: {**original(), "commands": original()["commands"][:-1]},
            lambda: {**original(), "commands": list(reversed(original()["commands"]))},
        ):
            with patch.object(
                server,
                "command_manifest_payload",
                side_effect=invalid,
            ):
                rejected, rejected_status = local_bridge.bridge_command_manifest_payload()
            self.assertEqual(rejected_status, 500)
            self.assertEqual(rejected["status"], "error")

    def test_manifest_has_local_only_api_route(self):
        self.assertIs(server.API_ROUTES["/api/agent-console/commands"], command_manifest_payload)

    def test_frontend_suggestions_help_and_dispatch_use_manifest(self):
        self.assertIn("agentConsoleCommands: '/api/agent-console/commands'", CORE_JS)
        self.assertIn("fetchAgentConsoleCommandManifest", CORE_JS)
        self.assertIn("function normalizeAgentConsoleCommandManifest", APP_JS)
        self.assertIn("agentConsoleCommands().filter", APP_JS)
        self.assertIn("const definition = agentConsoleCommands().find", APP_JS)
        self.assertIn(".filter((item) => !activeRun || agentConsoleCommandAllowedDuringRun(item))", APP_JS)
        self.assertIn(".map((item) => `${item.command} — ${item.description}`)", APP_JS)
        self.assertNotIn("const agentConsoleCommands = [", APP_JS)

    def test_frontend_fails_closed_to_fixed_handler_registry(self):
        self.assertIn("const agentConsoleCommandHandlers = new Set", APP_JS)
        self.assertIn("agentConsoleCommandHandlers.has(item.handler)", APP_JS)
        self.assertIn("args.length > definition.arguments.length", APP_JS)
        self.assertIn("payload.schema_version !== 1", APP_JS)
        self.assertIn("payload.source !== 'mentat'", APP_JS)
        self.assertIn("is not supported by the Mentat dashboard", APP_JS)
        self.assertNotIn("available in the interactive Hermes CLI", APP_JS)


if __name__ == "__main__":
    unittest.main()
