import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import server
from agent_runtime import AgentRuntimeRegistry, MentatTask, RuntimeContext
from hermes_runtime import HermesCompatibilityHandlers, HermesRuntime
from hermes_transport import HermesConsoleTransport, TransportBinding


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

    def test_production_generic_start_persists_identity_and_supports_status(self):
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
            server.load_agent_console_runs()
            task = MentatTask(
                id="task_research",
                title="Research",
                objective="Find primary sources.",
            )
            context = RuntimeContext(
                agent_id="agent_researcher",
                runtime_agent_ref="researcher-main",
                task_id=task.id,
            )

            started = server.HERMES_RUNTIME.start_task(task, context)
            current = server.HERMES_RUNTIME.get_status(started.id)
            stored = server.AGENT_CONSOLE_RUNS[started.id]

        self.assertEqual(started.agent_id, "agent_researcher")
        self.assertEqual(current.task_id, "task_research")
        self.assertEqual(stored["agent_id"], "researcher-main")
        self.assertEqual(stored["mentat_agent_id"], "agent_researcher")
        server.AGENT_CONSOLE_RUNS.clear()


if __name__ == "__main__":
    unittest.main()
