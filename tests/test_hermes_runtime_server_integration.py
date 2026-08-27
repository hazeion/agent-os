import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import server
from agent_registry import AgentRegistry
from agent_runtime import (
    AgentRuntimeRegistry,
    MentatTask,
    RuntimeContext,
    SubmissionDisposition,
)
from hermes_runtime import HermesCompatibilityHandlers, HermesRuntime
from hermes_transport import HermesConsoleTransport, TransportBinding
from mentat import local_bridge
from mentat_db import connect
from conversation_repository import ConversationRepository
from orchestration_service import OrchestrationService
from run_repository import (
    RunRepository,
    ensure_run_sqlite_authority,
    runtime_binding_digest,
)
from task_repository import TaskRepository, ensure_task_sqlite_authority


class HermesRuntimeServerIntegrationTests(unittest.TestCase):
    def _runtime(self, calls):
        return HermesRuntime(
            transport_factory=lambda: HermesConsoleTransport(
                TransportBinding("local", "Local Hermes", "local-default")
            ),
            compatibility_handlers=HermesCompatibilityHandlers(
                start=lambda payload: calls.append(("start", payload)) or ({"start": True}, 202),
                start_task=lambda task, context: calls.append(("start_task", task.id, context.agent_id)) or ({"start_task": True}, 202),
                message=lambda run_id, payload: calls.append(("message", run_id, payload)) or ({"message": True}, 200),
                response=lambda run_id, payload: calls.append(("response", run_id, payload)) or ({"response": True}, 200),
                stop=lambda run_id: calls.append(("stop", run_id)) or ({"stop": True}, 202),
                status=lambda run_id, cursor=None: calls.append(("status", run_id, cursor)) or ({"status": True}, 200),
            ),
        )

    def test_legacy_routes_dispatch_through_registered_hermes_runtime(self):
        calls = []
        runtime = self._runtime(calls)
        registry = AgentRuntimeRegistry((runtime,))

        with patch.object(server, "AGENT_RUNTIME_REGISTRY", registry):
            self.assertEqual(server.start_agent_console_run({"prompt": "hello"}), ({"start": True}, 202))
            self.assertEqual(server.steer_remote_console_run("run_1", {"text": "focus"}), ({"message": True}, 200))
            self.assertEqual(server.respond_to_remote_console_action("run_1", {"confirmed": True}), ({"response": True}, 200))
            self.assertEqual(server.cancel_agent_console_run("run_1"), ({"stop": True}, 202))
            self.assertEqual(server.agent_console_run_payload("run_1", "4"), ({"status": True}, 200))

        self.assertEqual([item[0] for item in calls], ["start", "message", "response", "stop", "status"])

    def test_console_transport_selection_crosses_runtime_registry(self):
        calls = []
        runtime = self._runtime(calls)
        registry = AgentRuntimeRegistry((runtime,))

        with patch.object(server, "AGENT_RUNTIME_REGISTRY", registry):
            transport = server.hermes_console_transport()

        self.assertIsInstance(transport, HermesConsoleTransport)
        self.assertEqual(transport.binding.binding_id, "local-default")

    def test_console_finalization_preserves_maximum_length_task_binding(self):
        run_id = "run_wide_finalize"
        task_id = "task@" + ("f" * 155)
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "status": "completed",
            "mentat_agent_id": "agent_researcher",
            "task_id": task_id,
            "events": [],
        }
        try:
            with patch.object(server, "persist_agent_console_runs", return_value=True):
                server.finalize_agent_console_runtime_event(run_id)
            stored = server.AGENT_CONSOLE_RUNS[run_id]
        finally:
            server.AGENT_CONSOLE_RUNS.clear()

        self.assertEqual(stored["task_id"], task_id)
        self.assertEqual(stored["events"][-1]["type"], "runtime.finalized")

    def test_production_generic_submit_reuses_private_preallocated_identity(self):
        task_id = "task@" + ("p" * 155)
        with TemporaryDirectory() as tmpdir, patch.object(
            server, "DATA_DIR", Path(tmpdir)
        ), patch.object(
            server, "CONFIGURED_DATA_DIR", Path(tmpdir)
        ), patch.object(
            server, "AGENT_CONSOLE_HISTORY_LOADED", False
        ), patch.object(
            server,
            "hermes_profiles_payload",
            return_value={"status": "available", "profiles": [{"id": "researcher-main"}]},
        ), patch.object(
            server, "hermes_command_path", return_value="/tmp/hermes"
        ), patch.object(
            server, "agent_console_model", return_value="test/model"
        ), patch.object(server.threading, "Thread"):
            server.AGENT_CONSOLE_RUNS.clear()
            task_source = Path(tmpdir) / "tasks.json"
            task_source.write_text("[]\n", encoding="utf-8")
            task_source.chmod(0o600)
            ensure_task_sqlite_authority(Path(tmpdir), required_source_mode=None)
            server.load_agent_console_runs()
            connection = connect(Path(tmpdir))
            try:
                task_document = {
                    "id": task_id,
                    "title": "Research",
                    "description": "Find primary sources.",
                    "project": "Mentat",
                    "status": "todo",
                    "priority": "medium",
                    "assignee": None,
                    "assigned_agent_id": "agent_researcher",
                    "due_date": None,
                    "source": "test",
                    "tags": [],
                    "review_required": False,
                    "needs_attention": False,
                    "created_at": "2026-08-18T12:00:00+00:00",
                    "updated_at": "2026-08-18T12:00:00+00:00",
                    "completed_at": None,
                }
                TaskRepository(
                    connection, allow_pre_authority_schema=True
                ).insert_collection([task_document])
                digest = runtime_binding_digest(
                    agent_id="agent_researcher",
                    runtime_type="hermes",
                    runtime_config_id="config-test",
                    runtime_agent_ref="researcher-main",
                    capabilities=("run.start",),
                )
                reservation = RunRepository(connection).reserve_dispatch(
                    idempotency_key="production-bridge-request-key",
                    dispatch_id="dispatch_private",
                    run_id="run_preallocated",
                    task=TaskRepository(
                        connection, allow_pre_authority_schema=True
                    ).get(task_id).document,
                    task_revision=1,
                    agent_id="agent_researcher",
                    runtime_type="hermes",
                    runtime_config_id="config-test",
                    binding_digest=digest,
                    capabilities=("run.start",),
                )
                RunRepository(connection).claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=digest,
                )
            finally:
                connection.close()
            task = MentatTask(
                id=task_id,
                title="Research",
                objective="Find primary sources.",
                assigned_agent_id="agent_researcher",
            )
            context = RuntimeContext(
                agent_id="agent_researcher",
                runtime_agent_ref="researcher-main",
                task_id=task.id,
                mentat_run_id="run_preallocated",
                dispatch_id="dispatch_private",
            )

            outcome = server.HERMES_RUNTIME.submit_task(task, context)
            self.assertEqual(outcome.disposition, SubmissionDisposition.ACCEPTED)
            started = outcome.run
            self.assertIsNotNone(started)
            current = server.HERMES_RUNTIME.get_status(started.id)
            stored = server.AGENT_CONSOLE_RUNS[started.id]
            public = server.agent_console_snapshot(stored)

        self.assertEqual(started.id, "run_preallocated")
        self.assertEqual(started.agent_id, "agent_researcher")
        self.assertEqual(current.task_id, task_id)
        self.assertEqual(stored["agent_id"], "researcher-main")
        self.assertEqual(stored["mentat_agent_id"], "agent_researcher")
        self.assertEqual(stored["task_id"], task_id)
        self.assertEqual(stored["_dispatch_id"], "dispatch_private")
        self.assertNotIn("dispatch_id", public)
        self.assertNotIn("_dispatch_id", public)
        self.assertNotIn("dispatch_private", repr(public))
        server.AGENT_CONSOLE_RUNS.clear()

    def test_nextjs_conversation_submit_reuses_canonical_run_without_legacy_collision(self):
        class ImmediateThread:
            def __init__(self, *, target, args, **_kwargs):
                self.target = target
                self.args = args

            def start(self):
                self.target(*self.args)

        def complete_immediately(run_id, _transport):
            with server.AGENT_CONSOLE_LOCK:
                run = server.AGENT_CONSOLE_RUNS[run_id]
                run["status"] = "completed"
                run["started_at"] = server.now_iso()
                run["completed_at"] = server.now_iso()
                run["response"] = "Immediate Hermes result"
                server.agent_console_event(
                    run,
                    "Response complete",
                    "complete",
                    {"duration_seconds": 0},
                )
                self.assertTrue(server.persist_agent_console_runs())
            server.finalize_agent_console_runtime_event(run_id)

        with TemporaryDirectory() as tmpdir, patch.object(
            server, "DATA_DIR", Path(tmpdir)
        ), patch.object(
            server, "CONFIGURED_DATA_DIR", Path(tmpdir)
        ), patch.object(
            server, "AGENT_CONSOLE_HISTORY_LOADED", False
        ), patch.object(
            server,
            "hermes_profiles_payload",
            return_value={
                "status": "available",
                "profiles": [{
                    "id": "researcher-main",
                    "model": "research-model",
                    "name": "Researcher",
                    "provider": "research-provider",
                }],
            },
        ), patch.object(
            server, "hermes_command_path", return_value="/tmp/hermes"
        ), patch.object(
            server, "agent_console_model", return_value="test/model"
        ), patch.object(
            server, "run_hermes_agent", side_effect=complete_immediately
        ), patch.object(server.threading, "Thread", ImmediateThread):
            root = Path(tmpdir)
            server.AGENT_CONSOLE_RUNS.clear()
            task_source = root / "tasks.json"
            task_source.write_text("[]\n", encoding="utf-8")
            task_source.chmod(0o600)
            ensure_task_sqlite_authority(root, required_source_mode=None)
            registry = AgentRegistry(root, supported_runtime_types=("hermes",))
            registry.create_agent(
                agent_id="agent_researcher",
                name="Researcher",
                runtime_config_id="config-researcher",
                runtime_type="hermes",
                runtime_agent_ref="researcher-main",
                capabilities=("run.start",),
            )
            conversation = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).create(agent_id="agent_researcher")
            ensure_run_sqlite_authority(root, server.agent_console_history_path())
            local_bridge._recover_bridge_runs_before_ready()
            identifiers = iter(
                ("msg_nextjs", "turn_nextjs", "run_nextjs_conversation")
            )
            service = OrchestrationService(
                root,
                runtime_registry=AgentRuntimeRegistry((server.HERMES_RUNTIME,)),
                agent_registry=registry,
                id_factory=lambda _prefix: next(identifiers),
            )

            with patch.object(
                server,
                "load_agent_console_runs",
                side_effect=AssertionError(
                    "live Hermes submission must not rerun startup recovery"
                ),
            ):
                result = service.submit_conversation_turn(
                    conversation_id=conversation.conversation.id,
                    text="Research the primary sources",
                    idempotency_key="nextjs-hermes-conversation-key",
                )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                stored_run = repository.get_run("run_nextjs_conversation")
                repository.validate()
            finally:
                connection.close()
            compatibility_run = server.AGENT_CONSOLE_RUNS["run_nextjs_conversation"]

        self.assertEqual(result.disposition, "accepted")
        self.assertEqual(result.run.id, "run_nextjs_conversation")
        self.assertEqual(result.run.status, "completed")
        self.assertEqual(stored_run.source, "console")
        self.assertEqual(stored_run.conversation_id, conversation.conversation.id)
        self.assertEqual(stored_run.turn_id, "turn_nextjs")
        self.assertEqual(stored_run.dispatch_state, "accepted")
        self.assertEqual(stored_run.status, "completed")
        self.assertEqual(len(stored_run.runtime_execution_digest), 64)
        self.assertEqual(compatibility_run["mentat_agent_id"], "agent_researcher")
        self.assertEqual(compatibility_run["task_id"], "turn_nextjs")
        self.assertEqual(compatibility_run["_dispatch_id"], "turn_nextjs")
        self.assertEqual(compatibility_run["status"], "completed")
        server.AGENT_CONSOLE_RUNS.clear()


if __name__ == "__main__":
    unittest.main()
