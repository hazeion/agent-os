from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from agent_runtime import AgentRun, PendingRunAction, RunActionResponse, RunStatus, RuntimeCapability
from run_repository import RunRecord
import server


def run_fixture(*, revision: int = 4, status: str = "waiting_for_approval") -> RunRecord:
    return RunRecord(
        id="run_current", source="console", task_id="task_current", task_revision=1,
        agent_id="agent_current", runtime_type="hermes", runtime_config_id="runtime_current",
        runtime_binding_digest="a" * 64, runtime_run_ref=None, runtime_event_cursor=0,
        status=status, dispatch_state="accepted", state_revision=revision, partial=False,
        timeline_truncated=False, first_retained_sequence=1, last_removed_sequence=0,
        last_event_sequence=1, created_at="2026-08-22T00:00:00+00:00",
        updated_at="2026-08-22T00:00:00+00:00", started_at="2026-08-22T00:00:00+00:00",
        completed_at=None,
    )


class FakeRuntime:
    def __init__(self, action: PendingRunAction):
        self.action = action
        self.capabilities = frozenset({RuntimeCapability.APPROVAL_RESPONSE.value})
        self.responses = []
        self.response_clears_request = True
        self.post_response_error = None

    def capabilities_for_run(self, _run_id, *, context=None):
        return self.capabilities

    def pending_action(self, _run_id, *, context=None):
        if self.responses and self.post_response_error is not None:
            raise server.AgentRuntimeError(self.post_response_error)
        if self.responses and self.response_clears_request:
            raise server.AgentRuntimeError("runtime.action_unavailable")
        return self.action

    def respond_to_action(self, run_id, action, response, *, context=None):
        self.responses.append((run_id, action, response, context))

    def get_status(self, run_id, *, context=None):
        return AgentRun(id=run_id, task_id="task_current", agent_id="agent_current", runtime_type="hermes", status=RunStatus.RUNNING)


class RunResponseControlTests(unittest.TestCase):
    def test_approval_request_preview_confirmation_and_response_are_bound(self):
        run = run_fixture()
        runtime = FakeRuntime(PendingRunAction(kind="approval", request_id="request_current", title="Use a tool", summary="Read project data", choices=(("once", "Allow once"), ("deny", "Deny"))))
        context = object()
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
        ):
            request = server.mentat_run_response_request_payload(run.id)
            preview = server.mentat_run_response_preview_payload(run.id, {"kind": "approval", "choice": "once"})
        self.assertFalse(request["requires_confirmation"])
        self.assertEqual(request["request"]["kind"], "approval")
        self.assertTrue(preview["requires_confirmation"])
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
        ):
            result = server.mentat_confirm_run_response(run.id, {"kind": "approval", "choice": "once"}, preview["confirmation_id"])
        self.assertEqual(result["disposition"], "accepted")
        self.assertEqual(runtime.responses, [(run.id, runtime.action, RunActionResponse(kind="approval", choice_id="once"), context)])

    def test_response_fails_closed_when_request_or_run_changes(self):
        run = run_fixture()
        changed = replace(run, state_revision=5)
        runtime = FakeRuntime(PendingRunAction(kind="clarification", request_id="request_current", prompt_type="text", question="Which scope?"))
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
        ):
            preview = server.mentat_run_response_preview_payload(run.id, {"kind": "clarification", "text": "Use the current project."})
        with (
            patch.object(server, "_current_run_for_response", side_effect=(run, changed)),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.confirmation_stale"),
        ):
            server.mentat_confirm_run_response(run.id, {"kind": "clarification", "text": "Use the current project."}, preview["confirmation_id"])
        self.assertEqual(runtime.responses, [])

    def test_response_rejects_invalid_kind_choice_and_oversized_text(self):
        with self.assertRaisesRegex(server.OrchestrationRunActionError, "run.response_invalid"):
            server.mentat_run_response_preview_payload("run_current", {"kind": "approval", "text": "no"})
        with self.assertRaisesRegex(server.OrchestrationRunActionError, "run.response_invalid"):
            server.mentat_run_response_preview_payload("run_current", {"kind": "clarification", "text": "x" * 2_001})

    def test_preview_rejects_response_values_not_offered_by_the_request(self):
        run = run_fixture(status="waiting_for_clarification")
        runtime = FakeRuntime(PendingRunAction(kind="clarification", request_id="request_current", prompt_type="choice", question="Which scope?", choices=(("current", "Current project"),)))
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.response_invalid"),
        ):
            server.mentat_run_response_preview_payload(run.id, {"kind": "clarification", "choice": "other"})
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.response_invalid"),
        ):
            server.mentat_run_response_preview_payload(run.id, {"kind": "clarification", "text": "Current project"})

    def test_response_is_partial_when_the_same_request_remains_after_success(self):
        run = run_fixture()
        runtime = FakeRuntime(PendingRunAction(kind="approval", request_id="request_current", choices=(("once", "Allow once"),)))
        runtime.response_clears_request = False
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
        ):
            preview = server.mentat_run_response_preview_payload(run.id, {"kind": "approval", "choice": "once"})
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.response_partial"),
        ):
            server.mentat_confirm_run_response(run.id, {"kind": "approval", "choice": "once"}, preview["confirmation_id"])

    def test_confirmation_rejects_changed_prompt_with_the_same_request_id(self):
        run = run_fixture()
        runtime = FakeRuntime(PendingRunAction(kind="approval", request_id="request_current", title="First action", choices=(("once", "Allow once"),)))
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
        ):
            preview = server.mentat_run_response_preview_payload(run.id, {"kind": "approval", "choice": "once"})
        runtime.action = PendingRunAction(kind="approval", request_id="request_current", title="Changed action", choices=(("once", "Allow once"),))
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.confirmation_stale"),
        ):
            server.mentat_confirm_run_response(run.id, {"kind": "approval", "choice": "once"}, preview["confirmation_id"])

    def test_response_is_partial_when_post_response_verification_fails(self):
        run = run_fixture()
        runtime = FakeRuntime(PendingRunAction(kind="approval", request_id="request_current", choices=(("once", "Allow once"),)))
        runtime.post_response_error = "runtime.status_failed"
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
        ):
            preview = server.mentat_run_response_preview_payload(run.id, {"kind": "approval", "choice": "once"})
        with (
            patch.object(server, "_current_run_for_response", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.response_partial"),
        ):
            server.mentat_confirm_run_response(run.id, {"kind": "approval", "choice": "once"}, preview["confirmation_id"])
