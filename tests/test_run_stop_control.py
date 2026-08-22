from __future__ import annotations

from dataclasses import replace
import unittest
from unittest.mock import patch

from agent_runtime import RuntimeCapability
from run_repository import RunRecord
import server


def run_fixture(*, revision: int = 4, status: str = "running") -> RunRecord:
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
    def __init__(self, capabilities=frozenset({RuntimeCapability.STOP.value})):
        self.capabilities = capabilities
        self.stop_calls = []

    def capabilities_for_run(self, run_id, *, context=None):
        self.last_capability_call = (run_id, context)
        return self.capabilities

    def stop(self, run_id, *, context=None):
        self.stop_calls.append((run_id, context))


class RunStopControlTests(unittest.TestCase):
    def test_stop_accepts_active_waiting_states(self):
        for status in ("waiting", "waiting_for_approval", "waiting_for_clarification"):
            with self.subTest(status=status), patch.object(
                server, "_load_run_for_action", return_value=run_fixture(status=status)
            ):
                self.assertEqual(server._current_run_for_stop("run_current").status, status)

    def test_preview_is_exact_and_requires_current_stop_capability(self):
        run = run_fixture()
        runtime = FakeRuntime()
        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
        ):
            payload = server.mentat_run_stop_preview_payload(run.id)
        self.assertEqual(payload["action"], "stop")
        self.assertEqual(payload["run_id"], run.id)
        self.assertTrue(payload["requires_confirmation"])
        self.assertRegex(payload["confirmation_id"], r"^[0-9a-f]{64}$")

        runtime = FakeRuntime(frozenset())
        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, object())),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.stop_unavailable"),
        ):
            server.mentat_run_stop_preview_payload(run.id)

    def test_confirm_requires_matching_state_bound_preview_and_readback(self):
        run = run_fixture()
        updated = replace(run, status="cancelling", state_revision=5)
        runtime = FakeRuntime()
        context = object()
        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
        ):
            preview = server.mentat_run_stop_preview_payload(run.id)

        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.confirmation_stale"),
        ):
            server.mentat_confirm_run_stop(run.id, "0" * 64)
        self.assertEqual(runtime.stop_calls, [])

        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_load_run_for_action", return_value=updated),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
        ):
            result = server.mentat_confirm_run_stop(run.id, preview["confirmation_id"])
        self.assertEqual(result, {"schema_version": 1, "action": "stop", "run_id": run.id, "disposition": "requested"})
        self.assertEqual(runtime.stop_calls, [(run.id, context)])

    def test_confirm_rejects_a_run_that_changed_after_preview_revalidation(self):
        run = run_fixture()
        changed = replace(run, state_revision=5)
        runtime = FakeRuntime()
        context = object()
        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
        ):
            preview = server.mentat_run_stop_preview_payload(run.id)
        with (
            patch.object(server, "_current_run_for_stop", side_effect=(run, changed)),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.confirmation_stale"),
        ):
            server.mentat_confirm_run_stop(run.id, preview["confirmation_id"])
        self.assertEqual(runtime.stop_calls, [])

    def test_confirm_fails_closed_when_durable_readback_did_not_advance(self):
        run = run_fixture()
        runtime = FakeRuntime()
        context = object()
        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
        ):
            preview = server.mentat_run_stop_preview_payload(run.id)
        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_load_run_for_action", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.stop_partial"),
        ):
            server.mentat_confirm_run_stop(run.id, preview["confirmation_id"])

    def test_confirm_fails_closed_when_readback_only_changes_revision(self):
        run = run_fixture()
        updated = replace(run, state_revision=5)
        runtime = FakeRuntime()
        context = object()
        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
        ):
            preview = server.mentat_run_stop_preview_payload(run.id)
        with (
            patch.object(server, "_current_run_for_stop", return_value=run),
            patch.object(server, "_load_run_for_action", return_value=updated),
            patch.object(server, "_run_stop_context", return_value=(runtime, context)),
            self.assertRaisesRegex(server.OrchestrationRunActionError, "run.stop_partial"),
        ):
            server.mentat_confirm_run_stop(run.id, preview["confirmation_id"])
