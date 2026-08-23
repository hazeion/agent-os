from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from agent_registry import AgentRegistry
from agent_runtime import (
    AgentEvent,
    AgentEventType,
    AgentRun,
    AgentRuntimeRegistry,
    RunStatus,
    RuntimeCapability,
    SubmissionDisposition,
    SubmissionOutcome,
)
from mentat_db import connect
from orchestration_service import OrchestrationService
from private_state import history_path
from run_repository import RunRepository
import server
from mentat import local_bridge
from task_repository import TaskRepository
from tests.sqlite_authority_support import ensure_run_sqlite_authority


_TIMESTAMP = "2026-08-22T12:00:00+00:00"


def _task_fixture(
    *,
    task_id: str,
    title: str,
    agent_id: str,
    required_capability: str,
) -> dict:
    return {
        "id": task_id,
        "title": title,
        "description": f"Exercise {title} through the canonical orchestration model.",
        "project": "Mentat",
        "status": "todo",
        "priority": "medium",
        "assignee": None,
        "assigned_agent_id": agent_id,
        "due_date": None,
        "source": "test",
        "tags": ["runtime-coexistence"],
        "review_required": False,
        "needs_attention": False,
        "created_at": _TIMESTAMP,
        "updated_at": _TIMESTAMP,
        "completed_at": None,
        "required_capabilities": [required_capability],
        "acceptance_criteria": ["The selected runtime handles only its assigned Run."],
    }


class _SubmissionGate:
    """Require every runtime submission to enter before any can return."""

    def __init__(self, expected: frozenset[str]) -> None:
        self.expected = expected
        self.barrier = threading.Barrier(len(expected))
        self.lock = threading.Lock()
        self.entered: set[str] = set()
        self.crossed: set[str] = set()

    def rendezvous(self, runtime_type: str) -> None:
        with self.lock:
            if runtime_type in self.entered:
                raise AssertionError(f"duplicate {runtime_type} submission")
            self.entered.add(runtime_type)
        try:
            self.barrier.wait(timeout=5)
        except threading.BrokenBarrierError as exc:
            raise AssertionError(
                "both runtime submissions did not enter concurrently"
            ) from exc
        with self.lock:
            if self.entered != self.expected:
                raise AssertionError("submission barrier released without every runtime")
            self.crossed.add(runtime_type)


class _StrictFakeRuntime:
    """A stateful runtime fake that rejects every cross-Run or private mismatch."""

    def __init__(
        self,
        *,
        runtime_type: str,
        agent_id: str,
        runtime_agent_ref: str,
        capabilities: frozenset[str],
        required_capability: str,
        gate: _SubmissionGate,
    ) -> None:
        self.runtime_type = runtime_type
        self.agent_id = agent_id
        self.runtime_agent_ref = runtime_agent_ref
        self.capabilities = capabilities
        self.required_capability = required_capability
        self.gate = gate
        self.submit_calls = []
        self.status_calls = []
        self.event_calls = []
        self.capability_calls = []
        self.message_calls = []
        self.stop_calls = []
        self._runs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit_task(self, task, context):
        if task.assigned_agent_id != self.agent_id:
            raise AssertionError("task reached the wrong runtime Agent")
        if task.required_capabilities != (self.required_capability,):
            raise AssertionError("task capability contract changed")
        if (
            context.agent_id != self.agent_id
            or context.runtime_agent_ref != self.runtime_agent_ref
            or context.task_id != task.id
            or context.mentat_run_id is None
            or context.dispatch_id is None
            or context.runtime_run_ref is not None
        ):
            raise AssertionError("submission context does not match the assigned Task")

        runtime_run_ref = f"{self.runtime_type}_ref_{context.mentat_run_id}"
        with self._lock:
            if self._runs or self.submit_calls:
                raise AssertionError("runtime received more than one submission")
            self.submit_calls.append((task, context, runtime_run_ref))

        self.gate.rendezvous(self.runtime_type)

        event_id = f"{self.runtime_type}_progress"
        if self.runtime_type == "vercel":
            event_id = "vercel_message_" + hashlib.sha256(
                (context.mentat_run_id + ":message").encode("utf-8")
            ).hexdigest()[:24]
        progress = AgentEvent(
            id=event_id,
            run_id=context.mentat_run_id,
            sequence=1,
            type=AgentEventType.MESSAGE,
            occurred_at=_TIMESTAMP,
            summary=f"{self.runtime_type} runtime is running",
            content=(
                "Vercel returned one bounded result."
                if self.runtime_type == "vercel"
                else None
            ),
        )
        initial_events = (progress,) if self.runtime_type == "vercel" else ()
        runtime_events = [] if self.runtime_type == "vercel" else [progress]
        with self._lock:
            self._runs[runtime_run_ref] = {
                "task_id": task.id,
                "agent_id": self.agent_id,
                "mentat_run_id": context.mentat_run_id,
                "status": RunStatus.RUNNING,
                "events": runtime_events,
            }
        return SubmissionOutcome(
            SubmissionDisposition.ACCEPTED,
            run=AgentRun(
                id=context.mentat_run_id,
                task_id=task.id,
                agent_id=self.agent_id,
                runtime_type=self.runtime_type,
                status=RunStatus.STARTING,
            ),
            runtime_run_ref=runtime_run_ref,
            initial_events=initial_events,
        )

    def _bound_run(self, run_id, context):
        if context is None:
            raise AssertionError("runtime action omitted its private context")
        with self._lock:
            state = self._runs.get(run_id)
            if state is None:
                raise AssertionError("runtime action targeted an unknown Run")
            snapshot = {
                "task_id": state["task_id"],
                "agent_id": state["agent_id"],
                "mentat_run_id": state["mentat_run_id"],
                "status": state["status"],
                "events": tuple(state["events"]),
            }
        if (
            context.agent_id != snapshot["agent_id"]
            or context.runtime_agent_ref != self.runtime_agent_ref
            or context.task_id != snapshot["task_id"]
            or context.mentat_run_id != snapshot["mentat_run_id"]
            or context.runtime_run_ref != run_id
        ):
            raise AssertionError("runtime action context crossed a Run binding")
        return snapshot

    def capabilities_for_run(self, run_id, *, context=None):
        self._bound_run(run_id, context)
        with self._lock:
            self.capability_calls.append((run_id, context))
        return self.capabilities

    def get_status(self, run_id, *, context=None):
        state = self._bound_run(run_id, context)
        with self._lock:
            self.status_calls.append((run_id, context))
        return AgentRun(
            id=state["mentat_run_id"],
            task_id=state["task_id"],
            agent_id=state["agent_id"],
            runtime_type=self.runtime_type,
            status=state["status"],
        )

    def stream_events(self, run_id, after_sequence=0, *, context=None):
        if type(after_sequence) is not int or after_sequence < 0:
            raise AssertionError("runtime event cursor is invalid")
        state = self._bound_run(run_id, context)
        with self._lock:
            self.event_calls.append((run_id, after_sequence, context))
        return tuple(
            event for event in state["events"] if event.sequence > after_sequence
        )

    def send_message(self, run_id, message, *, context=None):
        self._bound_run(run_id, context)
        if RuntimeCapability.SEND_MESSAGE.value not in self.capabilities:
            raise AssertionError("unsupported message action reached the runtime")
        with self._lock:
            self.message_calls.append((run_id, message, context))

    def stop(self, run_id, *, context=None):
        state = self._bound_run(run_id, context)
        if RuntimeCapability.STOP.value not in self.capabilities:
            raise AssertionError("unsupported Stop action reached the runtime")
        stopped = AgentEvent(
            id=f"{self.runtime_type}_stopped",
            run_id=state["mentat_run_id"],
            sequence=2,
            type=AgentEventType.RUN_STOPPED,
            occurred_at="2026-08-22T12:01:00+00:00",
            summary=f"{self.runtime_type} runtime stopped",
        )
        with self._lock:
            self.stop_calls.append((run_id, context))
            self._runs[run_id]["status"] = RunStatus.STOPPED
            self._runs[run_id]["events"].append(stopped)

    def pending_action(self, run_id, *, context=None):  # pragma: no cover
        raise AssertionError("pending_action is outside this test contract")

    def respond_to_action(  # pragma: no cover
        self, run_id, action, response, *, context=None
    ):
        raise AssertionError("respond_to_action is outside this test contract")


class RuntimeCoexistenceIntegrationTests(unittest.TestCase):
    def test_hermes_codex_and_vercel_dispatch_bridge_and_control_independently(self):
        with TemporaryDirectory(prefix="mentat-runtime-coexistence-") as tmpdir:
            root = Path(tmpdir)
            tasks = (
                _task_fixture(
                    task_id="task_hermes_research",
                    title="Hermes research",
                    agent_id="agent_hermes_researcher",
                    required_capability=RuntimeCapability.SEND_MESSAGE.value,
                ),
                _task_fixture(
                    task_id="task_codex_engineering",
                    title="Codex engineering",
                    agent_id="agent_codex_engineer",
                    required_capability=RuntimeCapability.STOP.value,
                ),
                _task_fixture(
                    task_id="task_vercel_generation",
                    title="Vercel generation",
                    agent_id="agent_vercel_generator",
                    required_capability=RuntimeCapability.MODEL_GENERATE.value,
                ),
            )
            source = root / "tasks.json"
            source.write_text(
                json.dumps(tasks, sort_keys=True) + "\n", encoding="utf-8"
            )
            source.chmod(0o600)
            ensure_run_sqlite_authority(root, history_path(root))

            start = RuntimeCapability.START_TASK.value
            status = RuntimeCapability.STATUS.value
            events = RuntimeCapability.EVENTS.value
            stop = RuntimeCapability.STOP.value
            message = RuntimeCapability.SEND_MESSAGE.value
            generate = RuntimeCapability.MODEL_GENERATE.value
            hermes_capabilities = frozenset({start, status, events, stop, message})
            codex_capabilities = frozenset({start, status, events, stop})
            vercel_capabilities = frozenset({start, status, events, generate})
            gate = _SubmissionGate(frozenset({"hermes", "codex", "vercel"}))
            hermes = _StrictFakeRuntime(
                runtime_type="hermes",
                agent_id="agent_hermes_researcher",
                runtime_agent_ref="profile_researcher",
                capabilities=hermes_capabilities,
                required_capability=message,
                gate=gate,
            )
            codex = _StrictFakeRuntime(
                runtime_type="codex",
                agent_id="agent_codex_engineer",
                runtime_agent_ref="default",
                capabilities=codex_capabilities,
                required_capability=stop,
                gate=gate,
            )
            vercel = _StrictFakeRuntime(
                runtime_type="vercel",
                agent_id="agent_vercel_generator",
                runtime_agent_ref="connection_vercel",
                capabilities=vercel_capabilities,
                required_capability=generate,
                gate=gate,
            )
            runtime_registry = AgentRuntimeRegistry((hermes, codex, vercel))
            agent_registry = AgentRegistry(
                root, supported_runtime_types=runtime_registry.runtime_types
            )
            agent_registry.create_agent(
                agent_id=hermes.agent_id,
                name="Hermes Researcher",
                runtime_config_id="config_hermes_researcher",
                runtime_type=hermes.runtime_type,
                runtime_agent_ref=hermes.runtime_agent_ref,
                capabilities=hermes_capabilities,
            )
            agent_registry.create_agent(
                agent_id=codex.agent_id,
                name="Codex Engineer",
                runtime_config_id="config_codex_engineer",
                runtime_type=codex.runtime_type,
                runtime_agent_ref=codex.runtime_agent_ref,
                capabilities=codex_capabilities,
            )
            agent_registry.create_agent(
                agent_id=vercel.agent_id,
                name="Vercel Generator",
                runtime_config_id="config_vercel_generator",
                runtime_type=vercel.runtime_type,
                runtime_agent_ref=vercel.runtime_agent_ref,
                capabilities=vercel_capabilities,
            )

            connection = connect(root)
            try:
                task_repository = TaskRepository(connection)
                task_repository.authority_receipt(required=True)
                revisions = {
                    task["id"]: task_repository.get(task["id"]).revision
                    for task in tasks
                }
            finally:
                connection.close()

            services = {
                "hermes": OrchestrationService(
                    root,
                    runtime_registry=runtime_registry,
                    agent_registry=agent_registry,
                    id_factory=lambda prefix: f"{prefix}_hermes_coexistence",
                ),
                "codex": OrchestrationService(
                    root,
                    runtime_registry=runtime_registry,
                    agent_registry=agent_registry,
                    id_factory=lambda prefix: f"{prefix}_codex_coexistence",
                ),
                "vercel": OrchestrationService(
                    root,
                    runtime_registry=runtime_registry,
                    agent_registry=agent_registry,
                    id_factory=lambda prefix: f"{prefix}_vercel_coexistence",
                ),
            }
            task_ids = {
                "hermes": "task_hermes_research",
                "codex": "task_codex_engineering",
                "vercel": "task_vercel_generation",
            }
            results = {}
            failures = []
            result_lock = threading.Lock()

            def dispatch(runtime_type: str) -> None:
                try:
                    task_id = task_ids[runtime_type]
                    result = services[runtime_type].dispatch_task(
                        task_id=task_id,
                        expected_revision=revisions[task_id],
                        idempotency_key=f"slice-3b-{runtime_type}-dispatch",
                    )
                    with result_lock:
                        results[runtime_type] = result
                except BaseException as exc:  # surfaced on the test thread below
                    with result_lock:
                        failures.append((runtime_type, exc))

            workers = [
                threading.Thread(
                    target=dispatch,
                    args=(runtime_type,),
                    name=f"slice-3b-{runtime_type}",
                )
                for runtime_type in ("hermes", "codex", "vercel")
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=8)
            if any(worker.is_alive() for worker in workers):
                gate.barrier.abort()
                for worker in workers:
                    worker.join(timeout=2)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(failures, [], msg=repr(failures))
            self.assertEqual(set(results), {"hermes", "codex", "vercel"})
            self.assertEqual(gate.entered, {"hermes", "codex", "vercel"})
            self.assertEqual(gate.crossed, {"hermes", "codex", "vercel"})
            self.assertEqual(len(hermes.submit_calls), 1)
            self.assertEqual(len(codex.submit_calls), 1)
            self.assertEqual(len(vercel.submit_calls), 1)
            self.assertTrue(all(result.disposition == "accepted" for result in results.values()))

            reconciler = OrchestrationService(
                root,
                runtime_registry=runtime_registry,
                agent_registry=agent_registry,
            )
            report = reconciler.reconcile_runs(owner="runtime_coexistence_reconciler")
            run_ids = {runtime_type: result.run.id for runtime_type, result in results.items()}
            self.assertEqual(report.leased, 3)
            self.assertEqual(set(report.reconciled), set(run_ids.values()))
            self.assertEqual(report.unavailable, ())

            expected_identity = {
                "hermes": (tasks[0]["id"], hermes.agent_id, hermes.runtime_type),
                "codex": (tasks[1]["id"], codex.agent_id, codex.runtime_type),
                "vercel": (tasks[2]["id"], vercel.agent_id, vercel.runtime_type),
            }
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                for runtime_type, run_id in run_ids.items():
                    run = repository.get_run(run_id)
                    run_events, reset, _cursor = repository.list_events(run_id)
                    self.assertEqual(
                        (run.task_id, run.agent_id, run.runtime_type),
                        expected_identity[runtime_type],
                    )
                    self.assertEqual(run.status, "running")
                    self.assertEqual(run.dispatch_state, "accepted")
                    self.assertFalse(reset)
                    self.assertTrue(run_events)
                    self.assertTrue(all(event.run_id == run.id for event in run_events))
                    self.assertTrue(
                        any(
                            event.summary == f"{runtime_type} runtime is running"
                            for event in run_events
                        )
                    )
                repository.validate()
            finally:
                connection.close()

            hermes_run_id = run_ids["hermes"]
            codex_run_id = run_ids["codex"]
            vercel_run_id = run_ids["vercel"]
            message_text = "Continue with the bounded research summary."
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "AGENT_RUNTIME_REGISTRY", runtime_registry),
                patch.object(
                    server, "_mentat_agent_registry", return_value=agent_registry
                ),
            ):
                message_preview = server.mentat_run_message_preview_payload(
                    hermes_run_id, message_text
                )
                message_result = server.mentat_confirm_run_message(
                    hermes_run_id,
                    message_text,
                    message_preview["confirmation_id"],
                )
                self.assertEqual(message_result["run_id"], hermes_run_id)
                self.assertEqual(message_result["disposition"], "accepted")

                stop_preview = server.mentat_run_stop_preview_payload(codex_run_id)
                with self.assertRaisesRegex(
                    server.OrchestrationRunActionError, "run.confirmation_stale"
                ):
                    server.mentat_confirm_run_stop(
                        hermes_run_id, stop_preview["confirmation_id"]
                    )
                self.assertEqual(hermes.stop_calls, [])
                self.assertEqual(codex.stop_calls, [])

                stop_result = server.mentat_confirm_run_stop(
                    codex_run_id, stop_preview["confirmation_id"]
                )
                self.assertEqual(stop_result["run_id"], codex_run_id)
                self.assertEqual(stop_result["disposition"], "requested")

                agents_payload = local_bridge._ready_agents_payload(
                    server.mentat_agents_payload()
                )
                runs_payload, runs_status = local_bridge.bridge_runs_payload()
                vercel_events, vercel_events_status = (
                    local_bridge.bridge_run_events_payload(vercel_run_id, 0)
                )
                self.assertEqual(runs_status, 200)
                self.assertEqual(vercel_events_status, 200)
                self.assertEqual(
                    {agent["runtime_type"] for agent in agents_payload["agents"]},
                    {"hermes", "codex", "vercel"},
                )
                self.assertEqual(
                    {run["runtime_type"] for run in runs_payload["runs"]},
                    {"hermes", "codex", "vercel"},
                )
                self.assertTrue(vercel_events["events"])
                messages = [
                    event["message"]
                    for event in vercel_events["events"]
                    if event["message"] is not None
                ]
                self.assertEqual(messages, ["Vercel returned one bounded result."])

            self.assertEqual(len(hermes.message_calls), 1)
            message_call = hermes.message_calls[0]
            self.assertEqual(message_call[0], results["hermes"].run.runtime_run_ref)
            self.assertEqual(message_call[1], message_text)
            self.assertEqual(message_call[2].mentat_run_id, hermes_run_id)
            self.assertEqual(codex.message_calls, [])
            self.assertEqual(vercel.message_calls, [])
            self.assertEqual(hermes.stop_calls, [])
            self.assertEqual(len(codex.stop_calls), 1)
            self.assertEqual(vercel.stop_calls, [])
            self.assertEqual(
                codex.stop_calls[0][0], results["codex"].run.runtime_run_ref
            )
            self.assertEqual(codex.stop_calls[0][1].mentat_run_id, codex_run_id)

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                hermes_run = repository.get_run(hermes_run_id)
                codex_run = repository.get_run(codex_run_id)
                vercel_run = repository.get_run(vercel_run_id)
                codex_events, reset, _cursor = repository.list_events(codex_run_id)
                self.assertEqual(hermes_run.status, "running")
                self.assertEqual(codex_run.status, "stopped")
                self.assertEqual(vercel_run.status, "running")
                self.assertFalse(reset)
                self.assertTrue(all(event.run_id == codex_run_id for event in codex_events))
                self.assertTrue(
                    any(event.type == AgentEventType.RUN_STOPPED for event in codex_events)
                )
                repository.validate()
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
