from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import server
from hermes_transport import HermesTransportError, TransportBinding


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
    def local_console(self):
        return server.local_hermes_console_transport(
            TransportBinding("local", "Local Hermes", "local-default"), command_path="/tmp/hermes"
        )

    def setUp(self):
        # Provider-switch tests own the transport and legacy active-run inputs.
        # Canonical Run storage is separately covered by its repository tests;
        # consulting a machine-local database here makes those transport
        # contracts depend on unrelated data-root readiness.
        canonical_active_run = patch.object(
            server, "_active_canonical_provider_run", return_value=None
        )
        canonical_active_run.start()
        self.addCleanup(canonical_active_run.stop)

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()
        server.AGENT_MODEL_CATALOG_CACHE.update({"key": None, "payload": None, "fetched_at": 0})

    def test_console_payload_exposes_normalized_profiles(self):
        with patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
            server, "hermes_profiles_payload", return_value=profile_discovery()
        ), patch.object(
            server, "hermes_console_transport", return_value=self.local_console()
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
            "starts_new_session": False,
            "new_session_state": "pending",
            "events": [],
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        transport = server.local_hermes_console_transport(
            TransportBinding("local", "Local Hermes", "local-default"),
            command_path="/tmp/hermes",
        )
        # This test owns the legacy CLI launch contract, not shared runtime
        # telemetry/artifact storage. Keep its fixed run ID isolated from
        # leftovers produced by other console tests on the same runner.
        with patch(
            "hermes_transport.local_control_dependencies_available", return_value=False
        ), patch.object(transport, "revalidate"), patch.object(
            server,
            "prepare_local_telemetry_paths",
            return_value=(ROOT / "unused-progress.jsonl", ROOT / "unused-usage.json"),
        ), patch.object(server, "collect_agent_console_artifacts"), patch.object(
            server.subprocess, "Popen", return_value=CompletedHermesProcess()
        ) as popen, patch.object(
            server, "persist_agent_console_runs", return_value=True
        ):
            server.run_hermes_agent(run_id, transport)

        command = popen.call_args.args[0]
        self.assertEqual(command[:6], ["/tmp/hermes", "-p", "randy", "chat", "-q", "Research this"])
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["session_id"], "session_randy_1")
        self.assertTrue(server.AGENT_CONSOLE_RUNS[run_id]["starts_new_session"])
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["new_session_state"], "started")
        self.assertEqual(
            sum(
                event["type"] == "session.started"
                for event in server.AGENT_CONSOLE_RUNS[run_id]["events"]
            ),
            1,
        )

    def test_start_rejects_cross_profile_session_resume(self):
        server.AGENT_CONSOLE_RUNS["run_default"] = {
            "id": "run_default",
            "agent_id": "default",
            "status": "completed",
            "session_id": "session_shared",
            "created_at": "2026-07-10T12:00:00-07:00",
        }
        transport = self.local_console()
        with patch.object(server, "hermes_profiles_payload", return_value=profile_discovery()), patch.object(
            server, "hermes_command_path", return_value="/tmp/hermes"
        ), patch.object(
            server, "hermes_console_transport", return_value=transport
        ), patch.object(
            transport, "revalidate"
        ), patch.object(
            server, "agent_console_history_is_current", return_value=True
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
        transport = self.local_console()
        with patch.object(
            server, "hermes_profiles_payload", return_value=profile_discovery()
        ), patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
            server, "hermes_console_transport", return_value=transport
        ), patch.object(
            transport, "revalidate"
        ), patch.object(
            server, "agent_console_history_is_current", return_value=True
        ), patch.object(
            server, "persist_agent_console_runs", return_value=True
        ), patch.object(
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
            server, "hermes_console_transport", return_value=self.local_console()
        ), patch.object(
            server, "_provider_mutation_active_run", return_value=(None, None)
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

    def remote_runtime(self, *, provider="openai-codex", model="gpt-5.6", revision="a"):
        return {
            "profile_id": "randy",
            "current_provider": provider,
            "current_model": model,
            "providers": [
                {
                    "id": "openai-codex",
                    "name": "openai-codex",
                    "authenticated": True,
                    "models": ["gpt-5.6"],
                },
                {
                    "id": "anthropic",
                    "name": "anthropic",
                    "authenticated": True,
                    "models": ["claude-sonnet-4"],
                },
            ],
            "revision": "runtime_rev_" + (revision * 64),
            "capabilities": {"providers.switch": True},
            "read_only": False,
            "error": "",
        }

    def remote_transport(self, *, binding_id="b" * 32):
        remote_transport = MagicMock()
        remote_transport.mode = "remote"
        remote_transport.binding = TransportBinding(
            "remote",
            "Remote workshop",
            binding_id,
        )
        remote_transport.read_profiles.return_value = [
            {
                "id": "randy",
                "is_default": False,
                "is_active": True,
                "served": True,
            }
        ]
        return remote_transport

    def test_remote_connection_remains_read_only_when_switch_capability_is_missing(self):
        remote_transport = self.remote_transport()
        remote_transport.read_profile_runtime.side_effect = HermesTransportError(
            "remote_profile_runtime_capability_unavailable"
        )
        payload = {
            "agent_id": "randy",
            "provider": "anthropic",
            "model": "claude-sonnet-4",
            "confirmed": True,
            "confirmation_id": "provider_switch_untrusted",
        }

        with patch.object(
            server,
            "hermes_console_transport",
            return_value=remote_transport,
        ), patch.object(
            server,
            "apply_provider_switch",
        ) as apply:
            preview, preview_status = (
                server.preview_agent_console_provider_switch(payload)
            )
            result, status = server.switch_agent_console_provider(payload)

        self.assertEqual(preview_status, 409)
        self.assertEqual(status, 409)
        self.assertEqual(
            preview["error_code"],
            "remote_profile_runtime_capability_unavailable",
        )
        self.assertEqual(
            result["error_code"],
            "remote_profile_runtime_capability_unavailable",
        )
        apply.assert_not_called()

    def test_remote_preview_rereads_runtime_and_binds_revision(self):
        transport = self.remote_transport()
        first = self.remote_runtime(revision="a")
        transport.read_profile_runtime.return_value = first
        with patch.object(
            server, "hermes_console_transport", return_value=transport
        ):
            preview, status = server.preview_agent_console_provider_switch(
                {
                    "agent_id": "randy",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                }
            )
        self.assertEqual(status, 200)
        self.assertEqual(preview["revision"], first["revision"])
        transport.read_profile_runtime.assert_called_once_with("randy")

    def test_remote_switch_is_revision_bound_idempotent_and_fresh_verified(self):
        transport = self.remote_transport()
        before = self.remote_runtime(revision="a")
        after = self.remote_runtime(
            provider="anthropic",
            model="claude-sonnet-4",
            revision="b",
        )
        transport.read_profile_runtime.side_effect = [before, after]
        preview, _ = server.preview_provider_switch(
            "randy",
            "anthropic",
            "claude-sonnet-4",
            before,
            binding_id=transport.binding.binding_id,
        )
        transport.switch_profile_runtime.return_value = after
        with patch.object(
            server, "hermes_console_transport", return_value=transport
        ):
            result, status = server.switch_agent_console_provider(
                {
                    "agent_id": "randy",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                }
            )
        self.assertEqual(status, 200)
        self.assertEqual(result["provider"], "anthropic")
        transport.switch_profile_runtime.assert_called_once()
        call = transport.switch_profile_runtime.call_args
        self.assertEqual(call.kwargs["revision"], before["revision"])
        self.assertRegex(
            call.kwargs["idempotency_key"],
            r"^mentat-provider-[0-9a-f]{32}$",
        )
        self.assertEqual(transport.read_profile_runtime.call_count, 2)

    def test_remote_switch_rejects_stale_confirmation_before_mutation(self):
        transport = self.remote_transport()
        original = self.remote_runtime(revision="a")
        changed = self.remote_runtime(revision="b")
        preview, _ = server.preview_provider_switch(
            "randy",
            "anthropic",
            "claude-sonnet-4",
            original,
            binding_id=transport.binding.binding_id,
        )
        transport.read_profile_runtime.return_value = changed
        with patch.object(
            server, "hermes_console_transport", return_value=transport
        ):
            result, status = server.switch_agent_console_provider(
                {
                    "agent_id": "randy",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                }
            )
        self.assertEqual(status, 409)
        self.assertIn("changed after preview", result["error"])
        transport.switch_profile_runtime.assert_not_called()

    def test_remote_switch_blocks_active_target_profile_only(self):
        transport = self.remote_transport()
        runtime = self.remote_runtime()
        transport.read_profile_runtime.return_value = runtime
        server.AGENT_CONSOLE_RUNS["run_randy"] = {
            "id": "run_randy",
            "agent_id": "randy",
            "status": "running",
        }
        with patch.object(
            server, "hermes_console_transport", return_value=transport
        ):
            result, status = server.preview_agent_console_provider_switch(
                {
                    "agent_id": "randy",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                }
            )
        self.assertEqual(status, 409)
        self.assertEqual(result["active_run_id"], "run_randy")
        transport.read_profile_runtime.assert_not_called()

    def test_remote_verification_mismatch_rolls_back_once_and_verifies(self):
        transport = self.remote_transport()
        before = self.remote_runtime(revision="a")
        mismatch = self.remote_runtime(
            provider="anthropic",
            model="claude-sonnet-4",
            revision="b",
        )
        mismatch["current_model"] = "unexpected-model"
        mismatch["providers"][1]["models"].append("unexpected-model")
        rolled_back = self.remote_runtime(revision="c")
        transport.read_profile_runtime.side_effect = [
            before,
            mismatch,
            rolled_back,
        ]
        acknowledged = self.remote_runtime(
            provider="anthropic",
            model="claude-sonnet-4",
            revision="b",
        )
        transport.switch_profile_runtime.side_effect = [
            acknowledged,
            rolled_back,
        ]
        preview, _ = server.preview_provider_switch(
            "randy",
            "anthropic",
            "claude-sonnet-4",
            before,
            binding_id=transport.binding.binding_id,
        )
        with patch.object(
            server, "hermes_console_transport", return_value=transport
        ):
            result, status = server.switch_agent_console_provider(
                {
                    "agent_id": "randy",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                }
            )
        self.assertEqual(status, 500)
        self.assertEqual(
            result["error_code"], "verification_failed_rolled_back"
        )
        self.assertEqual(transport.switch_profile_runtime.call_count, 2)
        rollback = transport.switch_profile_runtime.call_args_list[1]
        self.assertEqual(rollback.kwargs["provider"], "openai-codex")
        self.assertEqual(rollback.kwargs["revision"], mismatch["revision"])
        self.assertRegex(
            rollback.kwargs["idempotency_key"],
            r"^mentat-provider-rollback-[0-9a-f]{32}$",
        )

    def test_remote_verification_mismatch_reports_failed_rollback(self):
        transport = self.remote_transport()
        before = self.remote_runtime(revision="a")
        mismatch = self.remote_runtime(
            provider="anthropic",
            model="claude-sonnet-4",
            revision="b",
        )
        mismatch["current_model"] = "unexpected-model"
        mismatch["providers"][1]["models"].append("unexpected-model")
        transport.read_profile_runtime.side_effect = [before, mismatch]
        transport.switch_profile_runtime.side_effect = [
            self.remote_runtime(
                provider="anthropic",
                model="claude-sonnet-4",
                revision="b",
            ),
            HermesTransportError("remote_profile_runtime_changed"),
        ]
        preview, _ = server.preview_provider_switch(
            "randy",
            "anthropic",
            "claude-sonnet-4",
            before,
            binding_id=transport.binding.binding_id,
        )
        with patch.object(
            server, "hermes_console_transport", return_value=transport
        ):
            result, status = server.switch_agent_console_provider(
                {
                    "agent_id": "randy",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                }
            )
        self.assertEqual(status, 500)
        self.assertEqual(
            result["error_code"],
            "verification_failed_rollback_unverified",
        )
        self.assertEqual(transport.switch_profile_runtime.call_count, 2)

    def test_remote_confirmation_cannot_cross_connection_bindings(self):
        first = self.remote_transport(binding_id="b" * 32)
        second = self.remote_transport(binding_id="c" * 32)
        runtime = self.remote_runtime(revision="a")
        first.read_profile_runtime.return_value = runtime
        second.read_profile_runtime.return_value = runtime
        with patch.object(
            server,
            "hermes_console_transport",
            side_effect=[first, second],
        ):
            preview, preview_status = (
                server.preview_agent_console_provider_switch(
                    {
                        "agent_id": "randy",
                        "provider": "anthropic",
                        "model": "claude-sonnet-4",
                    }
                )
            )
            result, status = server.switch_agent_console_provider(
                {
                    "agent_id": "randy",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                }
            )

        self.assertEqual(preview_status, 200)
        self.assertEqual(status, 409)
        self.assertIn("changed after preview", result["error"])
        first.switch_profile_runtime.assert_not_called()
        second.switch_profile_runtime.assert_not_called()

    def test_remote_verification_advanced_revision_never_rolls_back(self):
        transport = self.remote_transport()
        before = self.remote_runtime(revision="a")
        acknowledged = self.remote_runtime(
            provider="anthropic",
            model="claude-sonnet-4",
            revision="b",
        )
        concurrent = self.remote_runtime(revision="c")
        transport.read_profile_runtime.side_effect = [before, concurrent]
        transport.switch_profile_runtime.return_value = acknowledged
        preview, _ = server.preview_provider_switch(
            "randy",
            "anthropic",
            "claude-sonnet-4",
            before,
            binding_id=transport.binding.binding_id,
        )
        with patch.object(
            server, "hermes_console_transport", return_value=transport
        ):
            result, status = server.switch_agent_console_provider(
                {
                    "agent_id": "randy",
                    "provider": "anthropic",
                    "model": "claude-sonnet-4",
                    "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                }
            )

        self.assertEqual(status, 409)
        self.assertEqual(
            result["error_code"],
            "verification_concurrent_change",
        )
        self.assertIn("did not roll it back", result["error"])
        self.assertEqual(transport.switch_profile_runtime.call_count, 1)

    def test_frontend_routes_managed_profile_to_console(self):
        self.assertIn("data-use-hermes-profile", APP_JS)
        self.assertIn("state.agentConsoleSelectedAgentId", APP_JS)
        self.assertIn("const consolePayload = await api(endpoints.agentConsole)", APP_JS)
        self.assertIn("async function refreshAgentConsoleModels(agentId", CORE_JS)
        self.assertIn("async function previewAgentConsoleProvider(provider, model, agentId", CORE_JS)
        self.assertIn("async function switchAgentConsoleProvider(provider, model, agentId", CORE_JS)

    def test_frontend_runtime_refresh_is_read_only_and_stale_response_safe(self):
        self.assertIn("agentConsoleRuntimeRequestGeneration", CORE_JS)
        self.assertIn("Checking Hermes runtime", APP_JS)
        self.assertIn(
            "requestGeneration !== state.agentConsoleRuntimeRequestGeneration",
            APP_JS,
        )
        self.assertIn(
            "requestedAgentId !== state.agentConsoleSelectedAgentId",
            APP_JS,
        )
        self.assertIn("providerInventory.read_only && runtimeProvider", APP_JS)
        self.assertIn(
            "const selectedActiveRun = selectedRuns.find(agentConsoleRunIsActive)",
            APP_JS,
        )
        self.assertIn(
            "selectedActiveRun?.provider && selectedActiveRun?.model",
            APP_JS,
        )
        self.assertNotIn("const runtimeRun = activeRun || latestRun", APP_JS)
        self.assertIn(
            "providerSelect.disabled = !available || !providerSwitchAvailable",
            APP_JS,
        )
        self.assertIn("silent: true", APP_JS)


if __name__ == "__main__":
    unittest.main()
