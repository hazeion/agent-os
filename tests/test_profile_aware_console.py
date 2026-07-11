from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch

import server


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
        with patch.object(server.subprocess, "Popen", return_value=CompletedHermesProcess()) as popen:
            server.run_hermes_agent(run_id, "/tmp/hermes")

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

    def test_named_profile_model_update_is_profile_scoped(self):
        catalog = {
            "profile_id": "randy",
            "provider": "openrouter",
            "provider_label": "OpenRouter",
            "models": ["openai/gpt-5.5"],
            "current_model": "openai/gpt-5.5",
        }
        with patch.object(server, "agent_console_profile", return_value={"id": "randy", "name": "randy"}), patch.object(
            server, "agent_console_model_catalog", return_value=catalog
        ), patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
            server.subprocess, "run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = "updated"
            run.return_value.stderr = ""
            payload, status = server.set_agent_console_model({"agent_id": "randy", "model": "openai/gpt-5.5"})

        self.assertEqual(status, 200)
        self.assertEqual(payload["agent_id"], "randy")
        self.assertEqual(
            run.call_args.args[0],
            ["/tmp/hermes", "-p", "randy", "config", "set", "model.default", "openai/gpt-5.5"],
        )

    def test_frontend_routes_managed_profile_to_console(self):
        self.assertIn("data-use-hermes-profile", APP_JS)
        self.assertIn("state.agentConsoleSelectedAgentId", APP_JS)
        self.assertIn("async function refreshAgentConsoleModels(agentId", CORE_JS)
        self.assertIn("setAgentConsoleModel(model, agentId", CORE_JS)


if __name__ == "__main__":
    unittest.main()
