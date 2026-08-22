import unittest

from agent_runtime import (
    AgentEventType,
    AgentRuntimeError,
    AgentRuntimeRegistry,
    AgentStatus,
    MentatAgent,
    MentatTask,
    RunStatus,
    RuntimeCapability,
    RuntimeContext,
    TaskStatus,
)
from hermes_runtime import (
    HermesCompatibilityHandlers,
    HermesRuntime,
    normalize_hermes_event,
    normalize_hermes_run,
)


class FakeRuntime:
    runtime_type = "codex"
    capabilities = frozenset({RuntimeCapability.STATUS.value})

    def start_task(self, task, context):  # pragma: no cover - protocol fixture
        raise NotImplementedError

    def send_message(self, run_id, message):  # pragma: no cover
        raise NotImplementedError

    def pending_action(self, run_id):  # pragma: no cover
        raise NotImplementedError

    def respond_to_action(self, run_id, action, response):  # pragma: no cover
        raise NotImplementedError

    def stop(self, run_id):  # pragma: no cover
        raise NotImplementedError

    def get_status(self, run_id):  # pragma: no cover
        raise NotImplementedError

    def stream_events(self, run_id, after_sequence=0):  # pragma: no cover
        return ()

    def capabilities_for_run(self, run_id):  # pragma: no cover
        return self.capabilities


class AgentRuntimeContractTests(unittest.TestCase):
    def test_domain_types_keep_mentat_identity_separate_from_runtime_refs(self):
        agent = MentatAgent(
            id="agent_researcher",
            name="Researcher",
            runtime_type="hermes",
            runtime_config_id="runtime_config_primary",
            capabilities=frozenset({"research.web"}),
            status=AgentStatus.WORKING,
        )
        task = MentatTask(
            id="task_market_scan",
            title="Market scan",
            objective="Compare the current options.",
            status=TaskStatus.ASSIGNED,
            assigned_agent_id=agent.id,
            required_capabilities=("research.web",),
            acceptance_criteria=("Cite each recommendation.",),
        )
        context = RuntimeContext(
            agent_id=agent.id,
            runtime_agent_ref="researcher-main",
            task_id=task.id,
            runtime_run_ref="hermes-run-7",
        )

        self.assertEqual(context.agent_id, "agent_researcher")
        self.assertEqual(context.runtime_agent_ref, "researcher-main")
        self.assertNotEqual(context.agent_id, context.runtime_agent_ref)

    def test_domain_types_reject_unknown_states_and_malformed_ids(self):
        with self.assertRaises(ValueError):
            MentatAgent(id="bad id", name="Agent", runtime_type="hermes")
        with self.assertRaises(ValueError):
            MentatTask(id="task_1", title="Task", objective="Work", status="paused")
        with self.assertRaises(ValueError):
            RuntimeContext(agent_id="agent_1", runtime_agent_ref="../profile")

    def test_registry_is_deterministic_and_rejects_duplicates(self):
        runtime = FakeRuntime()
        registry = AgentRuntimeRegistry((runtime,))

        self.assertIs(registry.require("codex"), runtime)
        self.assertEqual(
            [dict(item) for item in registry.public_inventory()],
            [{"runtime_type": "codex", "capabilities": ["run.status"]}],
        )
        with self.assertRaises(ValueError):
            registry.register(runtime)
        with self.assertRaises(AgentRuntimeError) as raised:
            registry.require("claude")
        self.assertEqual(raised.exception.code, "runtime.unavailable")

    def test_hermes_run_projection_uses_only_mentat_ids(self):
        projected = normalize_hermes_run(
            {
                "id": "run_123",
                "status": "waiting_for_approval",
                "agent_id": "private-hermes-profile",
                "_remote_run_id": "private-upstream-run",
            },
            agent_id="agent_researcher",
            task_id="task_123",
        )

        self.assertEqual(projected.status, RunStatus.WAITING)
        self.assertEqual(projected.agent_id, "agent_researcher")
        self.assertEqual(projected.task_id, "task_123")
        self.assertFalse(hasattr(projected, "runtime_run_ref"))

    def test_hermes_event_projection_uses_closed_vocabulary_and_discards_data(self):
        projected = normalize_hermes_event(
            {
                "id": "event_1",
                "run_id": "run_1",
                "sequence": 3,
                "type": "tool.started",
                "timestamp": "2026-08-17T12:00:00+00:00",
                "display_text": "Tool started",
                "data": {"token": "secret", "path": "/private/file"},
            }
        )
        unknown = normalize_hermes_event(
            {
                "id": "event_2",
                "run_id": "run_1",
                "sequence": 4,
                "type": "hermes.future.event",
                "timestamp": "2026-08-17T12:00:01+00:00",
                "message": "Run updated",
            }
        )

        self.assertEqual(projected.type, AgentEventType.TOOL_REQUESTED)
        self.assertEqual(unknown.type, AgentEventType.MESSAGE)
        self.assertFalse(hasattr(projected, "data"))

    def test_hermes_runtime_delegates_generic_start_and_cursor_events(self):
        calls = []

        def start(payload):
            calls.append(("start", payload))
            return {
                "ok": True,
                "run": {"id": "run_42", "status": "queued"},
            }, 202

        def status(run_id, cursor=None):
            calls.append(("status", run_id, cursor))
            return {
                "run": {
                    "id": run_id,
                    "status": "completed",
                    "mentat_agent_id": "agent_42",
                    "task_id": "task_42",
                },
                "events": [{
                    "id": "event_42",
                    "run_id": run_id,
                    "sequence": 1,
                    "type": "runtime.finalized",
                    "timestamp": "2026-08-17T12:00:00+00:00",
                    "display_text": "Run completed",
                }]
            }, 200

        runtime = HermesRuntime(
            transport_factory=lambda: object(),
            compatibility_handlers=HermesCompatibilityHandlers(
                start=start,
                start_task=lambda task, context: start({
                    "agent_id": context.runtime_agent_ref,
                    "prompt": task.objective,
                    "task_id": task.id,
                }),
                message=lambda run_id, payload: ({"ok": True}, 200),
                response=lambda run_id, payload: ({"ok": True}, 200),
                stop=lambda run_id: ({"ok": True}, 202),
                status=status,
            ),
        )
        task = MentatTask(id="task_42", title="Task", objective="Do the work")
        context = RuntimeContext(
            agent_id="agent_42",
            runtime_agent_ref="hermes-profile",
            task_id=task.id,
        )

        run = runtime.start_task(task, context)
        events = tuple(runtime.stream_events(run.id))

        self.assertEqual(run.agent_id, "agent_42")
        self.assertEqual(run.runtime_type, "hermes")
        self.assertEqual(events[0].type, AgentEventType.RUN_COMPLETED)
        self.assertEqual(calls[0][1]["agent_id"], "hermes-profile")
        self.assertEqual(calls[1], ("status", "run_42", "0"))

    def test_actual_console_event_vocabulary_and_terminal_state_are_normalized(self):
        fixtures = (
            ("approval", RunStatus.WAITING, AgentEventType.APPROVAL_REQUIRED),
            ("clarification", RunStatus.WAITING, AgentEventType.APPROVAL_REQUIRED),
            ("artifact", RunStatus.COMPLETED, AgentEventType.ARTIFACT_CREATED),
            ("complete", RunStatus.COMPLETED, AgentEventType.RUN_COMPLETED),
            ("cancelled", RunStatus.STOPPED, AgentEventType.RUN_STOPPED),
            ("error", RunStatus.RUNNING, AgentEventType.MESSAGE),
            ("error", RunStatus.FAILED, AgentEventType.RUN_FAILED),
            ("session.started", RunStatus.RUNNING, AgentEventType.MESSAGE),
        )
        for sequence, (kind, status, expected) in enumerate(fixtures, start=1):
            with self.subTest(kind=kind, status=status):
                projected = normalize_hermes_event(
                    {
                        "id": f"event_{sequence}",
                        "run_id": "run_actual",
                        "sequence": sequence,
                        "type": kind,
                        "timestamp": "2026-08-17T12:00:00+00:00",
                        "display_text": "token=private /private/path",
                    },
                    run_status=status,
                )
                self.assertEqual(projected.type, expected)
                self.assertNotIn("private", projected.summary)
                self.assertNotIn("/", projected.summary)

    def test_generic_status_message_and_continuity_are_fail_closed(self):
        calls = []
        snapshot = {
            "id": "run_generic",
            "status": "running",
            "agent_id": "researcher-main",
            "mentat_agent_id": "agent_researcher",
            "task_id": "task_research",
            "controls": {"steer": {"available": True, "revision": 7}},
            "events": [],
        }

        def status(run_id, cursor=None):
            if cursor == "0" and calls and calls[-1] == "gap":
                return {"run": snapshot, "events": [], "cursor_reset_required": True}, 200
            return {"run": snapshot, "events": []}, 200

        runtime = HermesRuntime(
            transport_factory=lambda: object(),
            compatibility_handlers=HermesCompatibilityHandlers(
                start=lambda payload: ({"error": "unused"}, 409),
                start_task=lambda task, context: ({"error": "unused"}, 409),
                message=lambda run_id, payload: calls.append((run_id, payload)) or ({"ok": True}, 200),
                response=lambda run_id, payload: ({"error": "unused"}, 409),
                stop=lambda run_id: ({"ok": True}, 202),
                status=status,
            ),
        )

        projected = runtime.get_status("run_generic")
        runtime.send_message("run_generic", "Focus on sources")
        self.assertEqual(projected.agent_id, "agent_researcher")
        self.assertEqual(projected.task_id, "task_research")
        self.assertEqual(calls[-1][1], {
            "text": "Focus on sources",
            "control_revision": 7,
            "agent_id": "researcher-main",
        })
        self.assertIn(
            RuntimeCapability.SEND_MESSAGE.value,
            runtime.capabilities_for_run("run_generic"),
        )

        calls.append("gap")
        with self.assertRaises(AgentRuntimeError) as raised:
            tuple(runtime.stream_events("run_generic"))
        self.assertEqual(raised.exception.code, "runtime.event_continuity_lost")

    def test_start_rejects_mismatched_task_and_agent_before_side_effect(self):
        calls = []
        runtime = HermesRuntime(
            transport_factory=lambda: object(),
            compatibility_handlers=HermesCompatibilityHandlers(
                start=lambda payload: ({"error": "unused"}, 409),
                start_task=lambda task, context: calls.append((task, context)) or ({"ok": True}, 202),
                message=lambda run_id, payload: ({"error": "unused"}, 409),
                response=lambda run_id, payload: ({"error": "unused"}, 409),
                stop=lambda run_id: ({"error": "unused"}, 409),
                status=lambda run_id, cursor=None: ({"error": "unused"}, 404),
            ),
        )
        task = MentatTask(
            id="task_bound",
            title="Bound",
            objective="Work",
            assigned_agent_id="agent_expected",
        )
        with self.assertRaises(AgentRuntimeError) as wrong_task:
            runtime.start_task(
                task,
                RuntimeContext(
                    agent_id="agent_expected",
                    runtime_agent_ref="profile",
                    task_id="task_other",
                ),
            )
        with self.assertRaises(AgentRuntimeError) as wrong_agent:
            runtime.start_task(
                task,
                RuntimeContext(
                    agent_id="agent_other",
                    runtime_agent_ref="profile",
                    task_id=task.id,
                ),
            )
        self.assertEqual(wrong_task.exception.code, "runtime.task_binding_invalid")
        self.assertEqual(wrong_agent.exception.code, "runtime.agent_binding_invalid")
        self.assertEqual(calls, [])

    def test_stream_projects_one_terminal_event_plus_bounded_message_and_usage(self):
        events = [
            {
                "id": "event_1",
                "run_id": "run_1",
                "sequence": 1,
                "type": "error",
                "timestamp": "2026-08-17T12:00:00+00:00",
                "display_text": "Nonterminal replay warning",
            },
            {
                "id": "event_2",
                "run_id": "run_1",
                "sequence": 2,
                "type": "error",
                "timestamp": "2026-08-17T12:00:01+00:00",
                "display_text": "Terminal failure",
            },
        ]

        events.append({
            "id": "event_3",
            "run_id": "run_1",
            "sequence": 3,
            "type": "runtime.finalized",
            "timestamp": "2026-08-17T12:00:02+00:00",
            "display_text": "Run finalized",
        })

        def failed_status(run_id, cursor=None):
            return {
                "run": {
                    "id": run_id,
                    "status": "failed",
                    "mentat_agent_id": "agent_1",
                    "task_id": "task_1",
                },
                "events": events,
            }, 200

        runtime = HermesRuntime(
            transport_factory=lambda: object(),
            compatibility_handlers=HermesCompatibilityHandlers(
                start=lambda payload: ({"error": "unused"}, 409),
                start_task=lambda task, context: ({"error": "unused"}, 409),
                message=lambda run_id, payload: ({"error": "unused"}, 409),
                response=lambda run_id, payload: ({"error": "unused"}, 409),
                stop=lambda run_id: ({"error": "unused"}, 409),
                status=failed_status,
            ),
        )
        projected = tuple(runtime.stream_events("run_1"))
        self.assertEqual([event.type for event in projected].count(AgentEventType.RUN_FAILED), 1)
        self.assertEqual(projected[0].type, AgentEventType.MESSAGE)

        completed = {
            "id": "run_2",
            "status": "completed",
            "mentat_agent_id": "agent_2",
            "task_id": "task_2",
            "response": "Answer with api_key=secret-value",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        complete_event = [{
            "id": "event_3",
            "run_id": "run_2",
            "sequence": 3,
            "type": "runtime.finalized",
            "timestamp": "2026-08-17T12:00:02+00:00",
            "display_text": "Reconciled",
        }]
        runtime._compatibility_handlers = HermesCompatibilityHandlers(
            start=lambda payload: ({"error": "unused"}, 409),
            start_task=lambda task, context: ({"error": "unused"}, 409),
            message=lambda run_id, payload: ({"error": "unused"}, 409),
            response=lambda run_id, payload: ({"error": "unused"}, 409),
            stop=lambda run_id: ({"error": "unused"}, 409),
            status=lambda run_id, cursor=None: ({"run": completed, "events": complete_event}, 200),
        )
        projected = tuple(runtime.stream_events("run_2"))
        self.assertEqual(
            [event.type for event in projected],
            [AgentEventType.MESSAGE, AgentEventType.COST, AgentEventType.RUN_COMPLETED],
        )
        self.assertNotIn("secret-value", projected[0].content)
        self.assertEqual(projected[1].metrics["total_tokens"], 15)
        self.assertEqual([event.sequence for event in projected], [10, 11, 12])

    def test_terminal_projection_waits_for_stable_finalized_marker(self):
        full_events = [{
            "id": "event_complete",
            "run_id": "run_incremental",
            "sequence": 1,
            "type": "complete",
            "timestamp": "2026-08-17T12:00:00+00:00",
            "display_text": "Response complete",
        }]
        snapshot = {
            "id": "run_incremental",
            "status": "completed",
            "mentat_agent_id": "agent_incremental",
            "task_id": "task_incremental",
            "response": "Done",
        }

        def status(run_id, cursor=None):
            legacy_cursor = int(cursor or 0)
            return {
                "run": snapshot,
                "events": [item for item in full_events if item["sequence"] > legacy_cursor],
            }, 200

        runtime = HermesRuntime(
            transport_factory=lambda: object(),
            compatibility_handlers=HermesCompatibilityHandlers(
                start=lambda payload: ({"error": "unused"}, 409),
                start_task=lambda task, context: ({"error": "unused"}, 409),
                message=lambda run_id, payload: ({"error": "unused"}, 409),
                response=lambda run_id, payload: ({"error": "unused"}, 409),
                stop=lambda run_id: ({"error": "unused"}, 409),
                status=status,
            ),
        )

        first = tuple(runtime.stream_events("run_incremental"))
        self.assertNotIn(AgentEventType.RUN_COMPLETED, [event.type for event in first])
        full_events.extend([
            {
                "id": "event_artifact",
                "run_id": "run_incremental",
                "sequence": 2,
                "type": "artifact",
                "timestamp": "2026-08-17T12:00:01+00:00",
                "display_text": "Artifact created",
            },
            {
                "id": "event_finalized",
                "run_id": "run_incremental",
                "sequence": 3,
                "type": "runtime.finalized",
                "timestamp": "2026-08-17T12:00:02+00:00",
                "display_text": "Run finalized",
            },
        ])
        second = tuple(runtime.stream_events("run_incremental", after_sequence=4))
        third = tuple(runtime.stream_events("run_incremental", after_sequence=12))

        self.assertEqual(
            [event.type for event in second],
            [AgentEventType.ARTIFACT_CREATED, AgentEventType.MESSAGE, AgentEventType.RUN_COMPLETED],
        )
        self.assertEqual(third, ())

    def test_unbound_legacy_runs_cannot_use_runtime_neutral_controls(self):
        runtime = HermesRuntime(
            transport_factory=lambda: object(),
            compatibility_handlers=HermesCompatibilityHandlers(
                start=lambda payload: ({"error": "unused"}, 409),
                start_task=lambda task, context: ({"error": "unused"}, 409),
                message=lambda run_id, payload: ({"ok": True}, 200),
                response=lambda run_id, payload: ({"error": "unused"}, 409),
                stop=lambda run_id: ({"ok": True}, 202),
                status=lambda run_id, cursor=None: ({
                    "run": {
                        "id": run_id,
                        "status": "running",
                        "agent_id": "legacy-profile",
                        "controls": {"steer": {"available": True, "revision": 1}},
                    },
                    "events": [],
                }, 200),
            ),
        )
        for operation in (
            lambda: runtime.get_status("run_legacy"),
            lambda: runtime.send_message("run_legacy", "steer"),
            lambda: runtime.stop("run_legacy"),
            lambda: tuple(runtime.stream_events("run_legacy")),
            lambda: runtime.capabilities_for_run("run_legacy"),
        ):
            with self.assertRaises(AgentRuntimeError) as raised:
                operation()
            self.assertEqual(raised.exception.code, "runtime.identity_context_required")

    def test_stop_rejects_a_context_with_a_different_run_identity(self):
        calls = []
        runtime = HermesRuntime(
            transport_factory=lambda: object(),
            compatibility_handlers=HermesCompatibilityHandlers(
                start=lambda payload: ({"error": "unused"}, 409),
                start_task=lambda task, context: ({"error": "unused"}, 409),
                message=lambda run_id, payload: ({"error": "unused"}, 409),
                response=lambda run_id, payload: ({"error": "unused"}, 409),
                stop=lambda run_id: (calls.append(run_id) or {"ok": True}, 202),
                status=lambda run_id, cursor=None: ({
                    "run": {
                        "id": "run_other",
                        "status": "running",
                        "mentat_agent_id": "agent_current",
                        "task_id": "task_current",
                    },
                    "events": [],
                }, 200),
            ),
        )
        context = RuntimeContext(
            agent_id="agent_current",
            runtime_agent_ref="profile_current",
            task_id="task_current",
            mentat_run_id="run_current",
        )
        with self.assertRaises(AgentRuntimeError) as raised:
            runtime.stop("run_current", context=context)
        self.assertEqual(raised.exception.code, "runtime.identity_context_invalid")
        self.assertEqual(calls, [])
        with self.assertRaises(AgentRuntimeError) as raised:
            runtime.stop("run_other", context=context)
        self.assertEqual(raised.exception.code, "runtime.identity_context_invalid")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
