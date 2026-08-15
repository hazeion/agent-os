from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import agent_run_history
from hermes_transport import RemoteHermesConsoleTransport, TransportBinding
import remote_hermes
import server


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
CORE_JS = (ROOT / "public" / "core.js").read_text(encoding="utf-8")
REMOTE_RUN_ID = "run_" + ("a" * 32)
BINDING_ID = "b" * 32


class SteerClient:
    def __init__(self, *, statuses=None, steer_error=None, enabled=True):
        self.statuses = list(statuses or [{"status": "running"}, {"status": "running"}])
        self.steer_error = steer_error
        self.steered: list[str] = []
        capabilities = ["run_submission", "run_status", "run_events_sse", "run_stop"]
        if enabled:
            capabilities.append("run_steer")
        self.discovery = {
            "model": "anthropic/claude-test",
            "capabilities": capabilities,
        }

    def require_console_run_capabilities(self):
        return self.discovery

    def get_run(self, run_id):
        if run_id != REMOTE_RUN_ID:
            raise AssertionError("unexpected remote run id")
        result = self.statuses.pop(0)
        if isinstance(result, Exception):
            raise result
        if callable(result):
            result = result()
        return result

    def steer_run(self, run_id, text):
        if run_id != REMOTE_RUN_ID:
            raise AssertionError("unexpected remote run id")
        if self.steer_error is not None:
            raise self.steer_error
        self.steered.append(text)
        return {"accepted": True}


class ActiveRunSteerTests(unittest.TestCase):
    def setUp(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()
        server.AGENT_CONSOLE_REMOTE_WORKERS.clear()

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()
        server.AGENT_CONSOLE_REMOTE_WORKERS.clear()

    def adapter(self, client=None):
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", BINDING_ID),
            client=client or SteerClient(),
        )
        adapter.prepare_console()
        return adapter

    def active_run(self, adapter, *, status="running"):
        run = {
            "id": "run_mentat_steer",
            "agent_id": "default",
            "agent_name": "default",
            "transport_mode": "remote",
            "connection_binding_id": BINDING_ID,
            "prompt": "Original prompt",
            "status": status,
            "events": [],
            "event_cursor": 0,
            "created_at": "2026-08-14T12:00:00-07:00",
            "updated_at": "2026-08-14T12:00:00-07:00",
            "_remote_run_id": REMOTE_RUN_ID,
            "_remote_transport": adapter,
        }
        server.AGENT_CONSOLE_RUNS[run["id"]] = run
        return run

    def test_success_is_revision_bound_verified_and_text_free(self):
        client = SteerClient()
        adapter = self.adapter(client)
        run = self.active_run(adapter)
        before = server.agent_console_snapshot(run)
        self.assertTrue(before["controls"]["steer"]["available"])
        self.assertEqual(before["controls"]["steer"]["revision"], 0)

        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            payload, status = server.handle_post_route(
                "/api/agent-console/runs/run_mentat_steer/steer",
                {
                    "text": "Focus on the safe migration",
                    "control_revision": 0,
                    "agent_id": "default",
                },
            )

        self.assertEqual(status, 200)
        self.assertTrue(payload["accepted"])
        self.assertEqual(client.steered, ["Focus on the safe migration"])
        self.assertEqual(payload["run"]["controls"]["steer"]["revision"], 1)
        public = json.dumps(payload)
        self.assertNotIn("Focus on the safe migration", public)
        self.assertNotIn(REMOTE_RUN_ID, public)
        persisted = json.dumps(agent_run_history.summarize_run(run))
        self.assertNotIn("Focus on the safe migration", persisted)
        self.assertNotIn(REMOTE_RUN_ID, persisted)
        route_event_count = len(run["events"])
        with patch.object(server, "persist_agent_console_runs"):
            server._apply_remote_console_event(
                run["id"],
                {"type": "run.steered", "accepted": True},
            )
        self.assertEqual(len(run["events"]), route_event_count)
        self.assertNotIn("_remote_steer_event_suppress", run)

    def test_stale_profile_state_concurrency_and_capability_fail_closed(self):
        cases = (
            ({"control_revision": 1, "agent_id": "default"}, None),
            ({"control_revision": 0, "agent_id": "researcher"}, None),
            ({"control_revision": 0, "agent_id": "default"}, "inflight"),
            ({"control_revision": 0, "agent_id": "default"}, "waiting"),
            ({"control_revision": 0, "agent_id": "default"}, "disabled"),
        )
        for overrides, mutation in cases:
            with self.subTest(mutation=mutation, overrides=overrides):
                client = SteerClient(enabled=mutation != "disabled")
                adapter = self.adapter(client)
                run = self.active_run(adapter)
                if mutation == "inflight":
                    run["_steer_inflight"] = True
                elif mutation == "waiting":
                    run["status"] = "waiting_for_approval"
                request = {
                    "text": "Do not send this",
                    "control_revision": overrides["control_revision"],
                    "agent_id": overrides["agent_id"],
                }
                with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
                    payload, status = server.steer_remote_console_run(run["id"], request)
                self.assertEqual(status, 409)
                self.assertIn("error", payload)
                self.assertEqual(client.steered, [])
                server.AGENT_CONSOLE_RUNS.clear()

    def test_local_terminal_malformed_and_oversized_requests_fail_before_transport(self):
        adapter = self.adapter()
        run = self.active_run(adapter, status="completed")
        requests = (
            {"text": "late", "control_revision": 0, "agent_id": "default"},
            {"text": "", "control_revision": 0, "agent_id": "default"},
            {"text": "x" * 20_001, "control_revision": 0, "agent_id": "default"},
            {"text": "unsafe\x00text", "control_revision": 0, "agent_id": "default"},
            {"text": "missing binding"},
        )
        for request in requests:
            with self.subTest(request_keys=tuple(request)):
                payload, status = server.steer_remote_console_run(run["id"], request)
                self.assertIn(status, {400, 409})
                self.assertIn("error", payload)
        run["status"] = "running"
        run["transport_mode"] = "local"
        payload, status = server.steer_remote_console_run(
            run["id"],
            {"text": "local", "control_revision": 0, "agent_id": "default"},
        )
        self.assertEqual(status, 409)
        self.assertIn("error", payload)

    def test_accepted_but_failed_readback_is_explicit_partial_failure(self):
        client = SteerClient(statuses=[
            {"status": "running"},
            remote_hermes.RemoteHermesError("remote_timeout"),
        ])
        adapter = self.adapter(client)
        run = self.active_run(adapter)
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            payload, status = server.steer_remote_console_run(
                run["id"],
                {"text": "May have landed", "control_revision": 0, "agent_id": "default"},
            )
        self.assertEqual(status, 502)
        self.assertTrue(payload["partial"])
        self.assertEqual(payload["error_code"], "remote_steer_unverified")
        self.assertEqual(client.steered, ["May have landed"])
        self.assertTrue(run["partial"])
        self.assertEqual(run["_steer_revision"], 1)
        self.assertNotIn("May have landed", json.dumps(payload))

    def test_stop_cannot_race_an_inflight_steer(self):
        stop_result = {}
        client = SteerClient()
        adapter = self.adapter(client)
        run = self.active_run(adapter)

        def attempt_stop():
            stop_payload, stop_status = server.cancel_agent_console_run(run["id"])
            stop_result.update(payload=stop_payload, status=stop_status)
            return {"status": "running"}

        client.statuses = [attempt_stop, {"status": "running"}]
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            payload, status = server.steer_remote_console_run(
                run["id"],
                {"text": "Finish this check", "control_revision": 0, "agent_id": "default"},
            )
        self.assertEqual(status, 200)
        self.assertTrue(payload["accepted"])
        self.assertEqual(stop_result["status"], 409)
        self.assertEqual(run["status"], "running")
        self.assertNotIn("_remote_control_claim", run)

    def test_authority_change_after_acceptance_is_partial_not_success(self):
        client = SteerClient()
        adapter = self.adapter(client)
        run = self.active_run(adapter)

        def change_authority():
            run["status"] = "cancelling"
            return {"status": "running"}

        client.statuses = [{"status": "running"}, change_authority]
        with patch.object(adapter, "revalidate"), patch.object(server, "persist_agent_console_runs"):
            payload, status = server.steer_remote_console_run(
                run["id"],
                {"text": "This may land", "control_revision": 0, "agent_id": "default"},
            )
        self.assertEqual(status, 502)
        self.assertTrue(payload["partial"])
        self.assertEqual(payload["error_code"], "remote_steer_unverified")
        self.assertEqual(client.steered, ["This may land"])
        self.assertNotIn("_remote_control_claim", run)

    def test_server_rejects_all_input_staging_while_a_run_is_active(self):
        adapter = self.adapter()
        self.active_run(adapter)
        with (
            patch.object(server, "create_attachment") as create_attachment,
            patch.object(server, "snapshot_workspace_file") as snapshot_workspace_file,
            patch.object(server, "context_pack_record") as context_pack_record,
        ):
            responses = (
                server.create_agent_console_attachment(
                    original_name="note.txt",
                    content_type="text/plain",
                    content=b"private context",
                ),
                server.create_workspace_attachment({"root_id": "workspace", "relative_path": "note.txt"}),
                server.stage_context_pack("pack-test"),
            )
        self.assertEqual([status for _payload, status in responses], [409, 409, 409])
        create_attachment.assert_not_called()
        snapshot_workspace_file.assert_not_called()
        context_pack_record.assert_not_called()

    def test_upstream_steer_event_is_bounded_and_does_not_duplicate_route_text(self):
        adapter = self.adapter()
        run = self.active_run(adapter)
        self.assertFalse(server._apply_remote_console_event(
            run["id"],
            {"type": "run.steered", "accepted": True},
        ))
        self.assertEqual(run["_remote_steer_event_counter"], 1)
        self.assertEqual(run["events"][-1]["type"], "run.steered")
        self.assertEqual(run["events"][-1]["data"], {"phase": "steer"})
        self.assertNotIn("text", run["events"][-1]["data"])


class ActiveRunSteerFrontendTests(unittest.TestCase):
    def test_console_switches_existing_composer_into_explicit_steer_mode(self):
        self.assertIn("const boundActiveRun = runs", APP_JS)
        self.assertIn("const requestedAgentId = boundActiveRun?.agent_id", APP_JS)
        self.assertIn("const steerMode = Boolean(", APP_JS)
        self.assertIn("prompt.disabled = !available || composerBlocked", APP_JS)
        self.assertIn("send.textContent = steerMode ? 'Steer' : 'Send'", APP_JS)
        self.assertIn("Guide the active Hermes run…", APP_JS)
        self.assertIn("attach.disabled = !available || Boolean(activeRun)", APP_JS)
        self.assertIn("form.dataset.mode = steerMode ? 'steer' : 'send'", APP_JS)

    def test_plain_active_input_and_slash_command_share_one_guarded_operation(self):
        self.assertIn("async function submitAgentConsoleSteer(run, text)", APP_JS)
        self.assertIn("await submitAgentConsoleSteer(activeRun, value)", APP_JS)
        self.assertIn("if (!activeRun && agentConsoleRuntimeBlocked())", APP_JS)
        self.assertIn("agent_console.steer_active_run", APP_JS)
        self.assertIn("await submitAgentConsoleSteer(activeRun, argument)", APP_JS)
        self.assertIn("activeRun && !agentConsoleCommandAllowedDuringRun(definition)", APP_JS)
        self.assertIn("agentConsoleAttachmentMutationBlocked(status)", APP_JS)
        self.assertIn("agentConsoleHasActiveRun() || agentConsoleRuntimeBlocked()", APP_JS)
        self.assertIn("async function steerAgentConsoleRun", CORE_JS)
        self.assertIn("/steer`, {", CORE_JS)
        self.assertIn("control_revision: controlRevision", CORE_JS)

    def test_inflight_staging_and_managed_profile_paths_recheck_active_state(self):
        workspace = APP_JS[
            APP_JS.index("async function addAgentConsoleWorkspaceFile"):
            APP_JS.index("async function addAgentConsoleFiles")
        ]
        awaited_workspace = workspace.index("await createAgentConsoleWorkspaceAttachment")
        self.assertGreater(
            workspace.index("agentConsoleAttachmentMutationBlocked(status)", awaited_workspace),
            awaited_workspace,
        )
        uploads = APP_JS[
            APP_JS.index("async function addAgentConsoleFiles"):
            APP_JS.index("function agentConsoleOutstandingToolCount")
        ]
        self.assertIn("if (agentConsoleHasActiveRun()) return;", uploads)
        awaited_uploads = uploads.index("await uploadAgentConsoleAttachments")
        self.assertGreater(
            uploads.index("agentConsoleAttachmentMutationBlocked(status)", awaited_uploads),
            awaited_uploads,
        )
        context_pack = APP_JS[
            APP_JS.index("async function applyContextPackToConsole"):
            APP_JS.index("function renderContextPackEditor")
        ]
        awaited_pack = context_pack.index("await stageContextPack")
        self.assertGreater(context_pack.index("agentConsoleHasActiveRun()", awaited_pack), awaited_pack)
        self.assertIn("activeRun && (state.agentConsoleAttachments.length || state.agentConsoleRemoteContext)", APP_JS)
        self.assertIn("async function useHermesProfileInConsole", APP_JS)
        self.assertIn("Stop the active Hermes run before changing Console profiles.", APP_JS)
        self.assertIn("Stop the active Hermes run before testing an agent.", APP_JS)
        self.assertIn("data-use-hermes-profile=\"${escapeHtml(selectedProfile.id)}\" ${consoleBusy ? 'disabled' : ''}", APP_JS)
        self.assertIn(".filter((item) => !activeRun || agentConsoleCommandAllowedDuringRun(item))", APP_JS)


if __name__ == "__main__":
    unittest.main()
