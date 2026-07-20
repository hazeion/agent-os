from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch

import server
from hermes_transport import TransportBinding


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")


def profile_discovery() -> dict:
    return {
        "status": "available",
        "active_profile": "default",
        "profiles": [
            {
                "id": "default",
                "name": "default",
                "description": "",
                "provider": "openai-codex",
                "model": "gpt-5.6-luna",
                "is_default": True,
            },
            {
                "id": "randy",
                "name": "randy",
                "description": "Research agent",
                "provider": "openrouter",
                "model": "openai/gpt-5.5",
                "is_default": False,
            },
        ],
    }


class CompletedHermesProcess:
    returncode = 0

    def communicate(self, timeout=None):
        return "Profile response", "session_id: session_randy_1\n"


class ProfileAwareConsoleTests(unittest.TestCase):
    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()
        server.AGENT_MODEL_CATALOG_CACHE.update({"key": None, "payload": None, "fetched_at": 0})

    def test_console_payload_exposes_normalized_profiles(self):
        with patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
            server, "hermes_profiles_payload", return_value=profile_discovery()
        ), patch.object(server, "agent_console_model_catalog", return_value={"profile_id": "default", "models": []}):
            payload = server.agent_console_payload()

        self.assertEqual(payload["selected_agent_id"], "default")
        self.assertEqual([agent["id"] for agent in payload["agents"]], ["default", "randy"])
        self.assertEqual(payload["agents"][1]["model"], "openai/gpt-5.5")

    def test_named_profile_run_uses_fixed_profile_argv(self):
        run_id = "run_randy"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "randy",
            "agent_name": "randy",
            "prompt": "Research this",
            "session_id": None,
            "status": "queued",
            "events": [],
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        transport = server.local_hermes_console_transport(
            TransportBinding("local", "Local Hermes", "local-default"),
            command_path="/tmp/hermes",
        )
        with patch.object(server.subprocess, "Popen", return_value=CompletedHermesProcess()) as popen:
            server.run_hermes_agent(run_id, transport)

        command = popen.call_args.args[0]
        self.assertEqual(command[:6], ["/tmp/hermes", "-p", "randy", "chat", "-q", "Research this"])
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["session_id"], "session_randy_1")

    def test_start_rejects_cross_profile_session_resume(self):
        server.AGENT_CONSOLE_RUNS["run_default"] = {
            "id": "run_default",
            "agent_id": "default",
            "status": "completed",
            "session_id": "session_shared",
            "created_at": "2026-07-10T12:00:00-07:00",
        }
        with patch.object(server, "hermes_profiles_payload", return_value=profile_discovery()), patch.object(
            server, "hermes_command_path", return_value="/tmp/hermes"
        ):
            payload, status = server.start_agent_console_run({
                "agent_id": "randy",
                "prompt": "Continue",
                "session_id": "session_shared",
            })

        self.assertEqual(status, 409)
        self.assertIn("different profile", payload["error"])
        self.assertEqual(payload["session_profile_id"], "default")

    def test_start_rejects_unknown_session_and_allows_retained_profile_owned_session(self):
        server.AGENT_CONSOLE_RUNS["run_owned"] = {
            "id": "run_owned",
            "agent_id": "randy",
            "agent_name": "randy",
            "status": "completed",
            "session_id": "session_randy_owned",
            "created_at": "2026-07-11T12:00:00-07:00",
        }
        with patch.object(
            server, "hermes_profiles_payload", return_value=profile_discovery()
        ), patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
            server.threading, "Thread"
        ) as worker:
            unknown, unknown_status = server.start_agent_console_run(
                {
                    "agent_id": "randy",
                    "prompt": "Continue unknown",
                    "session_id": "session_not_retained",
                }
            )
            owned, owned_status = server.start_agent_console_run(
                {
                    "agent_id": "randy",
                    "prompt": "Continue owned",
                    "session_id": "session_randy_owned",
                }
            )

        self.assertEqual(unknown_status, 409)
        self.assertIn("retained", unknown["error"].lower())
        self.assertEqual(owned_status, 202)
        self.assertEqual(owned["run"]["session_id"], "session_randy_owned")
        worker.return_value.start.assert_called_once_with()

    def test_confirmed_provider_update_is_profile_scoped_and_verified(self):
        before = {
            "profile_id": "randy",
            "provider": "openrouter",
            "current_provider": "openrouter",
            "current_model": "openai/gpt-5.5",
            "providers": [
                {
                    "id": "anthropic",
                    "name": "Anthropic",
                    "authenticated": True,
                    "models": ["claude-sonnet-4"],
                }
            ],
            "capabilities": {"providers.switch": True},
        }
        verified = {
            **before,
            "current_provider": "anthropic",
            "current_model": "claude-sonnet-4",
        }
        with patch.object(
            server, "agent_console_profile", return_value={"id": "randy", "name": "randy"}
        ), patch.object(
            server, "agent_console_provider_inventory", side_effect=[before, verified]
        ), patch.object(
            server, "apply_provider_switch", return_value=({"ok": True}, "")
        ) as apply, patch.object(
            server, "agent_console_model_catalog", return_value={"profile_id": "randy"}
        ):
            preview, preview_status = server.preview_provider_switch(
                "randy", "anthropic", "claude-sonnet-4", before
            )
            self.assertEqual(preview_status, 200)
            payload, status = server.switch_agent_console_provider({
                "agent_id": "randy",
                "provider": "anthropic",
                "model": "claude-sonnet-4",
                "confirmed": True,
                "confirmation_id": preview["confirmation_id"],
            })

        self.assertEqual(status, 200)
        self.assertEqual(payload["agent_id"], "randy")
        self.assertEqual(payload["provider"], "anthropic")
        apply.assert_called_once_with(
            server.hermes_python_path(),
            server.HERMES_HOME,
            "randy",
            "anthropic",
            "claude-sonnet-4",
            cwd=server.BASE_DIR,
        )

    def test_frontend_routes_managed_profile_to_console(self):
        self.assertIn("data-use-hermes-profile", APP_JS)
        self.assertIn("state.agentConsoleSelectedAgentId", APP_JS)
        self.assertIn("const consolePayload = await api(endpoints.agentConsole)", APP_JS)
        self.assertIn("async function refreshAgentConsoleModels(agentId", CORE_JS)
        self.assertIn("async function previewAgentConsoleProvider(provider, model, agentId", CORE_JS)
        self.assertIn("async function switchAgentConsoleProvider(provider, model, agentId", CORE_JS)


if __name__ == "__main__":
    unittest.main()
