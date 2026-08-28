from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import server
import run_repository
import orchestration_service
from agent_registry import AgentRegistry
from agent_runtime import (
    AgentEvent,
    AgentEventType,
    AgentRun,
    AgentRuntimeError,
    AgentRuntimeRegistry,
    RunStatus,
    RuntimeCapacity,
    SubmissionDisposition,
    SubmissionOutcome,
)
from mentat_db import MentatDatabaseError, connect
from mentat import local_bridge
from orchestration_service import OrchestrationService, OrchestrationServiceError
from conversation_repository import ConversationRepository
from private_state import history_path, private_state_lock
from private_console_unit import capture_private_console_unit
from run_repository import (
    RunRepository,
    RunRepositoryConflict,
    RunRepositoryValidationError,
    save_authoritative_run_summaries,
)
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from task_repository import TaskRepository


def task_fixture() -> dict:
    return {
        "id": "task-service",
        "title": "Service dispatch",
        "description": "Prove durable dispatch ordering.",
        "project": "Mentat",
        "status": "todo",
        "priority": "medium",
        "assignee": None,
        "assigned_agent_id": "agent-service",
        "due_date": None,
        "source": "test",
        "tags": ["dispatch"],
        "review_required": False,
        "needs_attention": False,
        "created_at": "2026-08-18T12:00:00+00:00",
        "updated_at": "2026-08-18T12:00:00+00:00",
        "completed_at": None,
    }


def preacceptance_worker_snapshot(
    root: Path,
    task,
    context,
    *,
    partial: bool,
    finalized: bool,
) -> dict:
    connection = connect(root)
    try:
        run = RunRepository(connection).get_run(context.mentat_run_id)
    finally:
        connection.close()
    events = []
    if finalized:
        events.append(
            {
                "schema_version": 1,
                "id": f"event_finalized_{context.mentat_run_id}",
                "run_id": context.mentat_run_id,
                "sequence": 1,
                "cursor": 1,
                "type": "runtime.finalized",
                "kind": "runtime.finalized",
                "timestamp": run.updated_at,
                "data": {},
                "display_text": "Runtime finalized",
                "message": "Runtime finalized",
            }
        )
    return {
        "id": context.mentat_run_id,
        "runtime_type": "hermes",
        "agent_id": "profile-service",
        "agent_name": "Service Agent",
        "model": "provider/model",
        "provider": "provider",
        "transport_mode": "local",
        "connection_binding_id": "local-default",
        "status": "completed",
        "partial": partial,
        "prompt": task.objective,
        "response": f"Completed {task.objective}",
        "error": "",
        "events": events,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "completed_at": run.updated_at,
        "attachments": [],
        "artifacts": [],
        "mentat_agent_id": context.agent_id,
        "task_id": task.id,
        "_dispatch_id": context.dispatch_id,
    }


class FakeRuntime:
    runtime_type = "hermes"

    def __init__(self, root: Path, *, raises: bool = False):
        self.root = root
        self.raises = raises
        self.calls = []
        self.status_queries = []
        self.status_entered = None
        self.status_release = None
        self.event_queries = []
        self.observed_status = RunStatus.RUNNING
        self.events = None
        self.honor_after_sequence = False
        self.submit_entered = None
        self.submit_release = None
        self.complete_before_return = False
        self.return_identity_mismatch = False
        self.rejects = False
        self.submission_lock = None
        self.guard_observed = False
        self.capacity_limit = 1
        self.capacity_scope = None
        self.runtime_agent_ref = "profile-service"
        self.capacity_entered = None
        self.capacity_release = None
        self.capabilities_entered = None
        self.capabilities_release = None
        self.steer_calls = []
        self.return_completed = False
        self.return_runtime_run_ref = "runtime-service-ref"
        self.resume_supported = False
        self.resume_calls = []

    @property
    def capabilities(self):
        if self.capabilities_entered is not None:
            self.capabilities_entered.set()
        if (
            self.capabilities_release is not None
            and not self.capabilities_release.wait(timeout=5)
        ):
            raise TimeoutError("test capability gate timed out")
        capabilities = {"run.start"}
        if self.resume_supported:
            capabilities.add("run.resume")
        return frozenset(capabilities)

    def capacity_for_binding(self, runtime_agent_ref):
        if self.capacity_entered is not None:
            self.capacity_entered.set()
        if self.capacity_release is not None and not self.capacity_release.wait(timeout=5):
            raise TimeoutError("test capacity gate timed out")
        return RuntimeCapacity(
            scope=self.capacity_scope or f"fake-runtime:{runtime_agent_ref}",
            limit=self.capacity_limit,
        )

    def submission_guard(self):
        return self.submission_lock or nullcontext()

    def submit_task(self, task, context):
        if self.submission_lock is not None:
            acquired = self.submission_lock.acquire(blocking=False)
            self.guard_observed = not acquired
            if acquired:
                self.submission_lock.release()
        # A second connection can obtain an immediate write transaction here,
        # proving dispatch released its SQLite transaction before adapter work.
        connection = connect(self.root)
        try:
            if str(context.dispatch_id).startswith("turn_"):
                row = connection.execute(
                    "SELECT state, attempt_count FROM mentat_conversation_turns "
                    "WHERE id = ?",
                    (context.dispatch_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT state, attempt_count FROM mentat_dispatch_reservations "
                    "WHERE dispatch_id = ?",
                    (context.dispatch_id,),
                ).fetchone()
            self.calls.append((task, context, str(row["state"]), int(row["attempt_count"])))
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        finally:
            connection.close()
        if self.submit_entered is not None:
            self.submit_entered.set()
        if self.submit_release is not None:
            if not self.submit_release.wait(timeout=5):
                raise TimeoutError("test submission gate timed out")
        if self.raises:
            raise TimeoutError("acceptance may be unknown")
        if self.rejects:
            return SubmissionOutcome(
                SubmissionDisposition.REJECTED,
                failure_code="runtime.start_rejected",
            )
        if self.complete_before_return:
            failure = []

            def complete_run():
                try:
                    worker_connection = connect(self.root)
                    try:
                        updated_at = worker_connection.execute(
                            "SELECT updated_at FROM mentat_runs WHERE id = ?",
                            (context.mentat_run_id,),
                        ).fetchone()[0]
                        worker_connection.execute(
                            "UPDATE mentat_runs SET status = 'completed', "
                            "completed_at = ?, "
                            "state_revision = state_revision + 1 WHERE id = ?",
                            (updated_at, context.mentat_run_id),
                        )
                    finally:
                        worker_connection.close()
                except Exception as exc:  # pragma: no cover - surfaced below
                    failure.append(exc)

            worker = threading.Thread(target=complete_run)
            worker.start()
            worker.join(timeout=5)
            if worker.is_alive():
                raise TimeoutError("test worker did not finish")
            if failure:
                raise failure[0]
        run_status = RunStatus.COMPLETED if self.return_completed else RunStatus.STARTING
        initial_events = ()
        if self.return_completed:
            initial_events = (
                AgentEvent(
                    id=f"runtime_answer_{context.mentat_run_id}",
                    run_id=context.mentat_run_id,
                    sequence=1,
                    type=AgentEventType.MESSAGE,
                    occurred_at="2026-08-18T13:00:00+00:00",
                    summary="Assistant answer completed",
                    content=f"Completed {task.objective}",
                ),
            )
        return SubmissionOutcome(
            SubmissionDisposition.ACCEPTED,
            run=AgentRun(
                id=context.mentat_run_id,
                task_id=task.id,
                agent_id="agent-mismatch" if self.return_identity_mismatch else context.agent_id,
                runtime_type=self.runtime_type,
                status=run_status,
            ),
            runtime_run_ref=self.return_runtime_run_ref,
            initial_events=initial_events,
            execution_identity={
                "model": "test-model",
                "provider": "test-provider",
                "reasoning_effort": "medium",
                "verification": "runtime_response",
            },
        )

    def get_status(self, run_id, *, context=None):
        matching_calls = [
            call
            for call in self.calls
            if call[1].mentat_run_id == context.mentat_run_id
        ]
        if len(matching_calls) != 1:
            raise AssertionError("runtime status target was not unique")
        task, submission_context, _state, _attempts = matching_calls[0]
        expected = context.runtime_run_ref or context.mentat_run_id
        if run_id != expected:
            raise AssertionError("runtime-owned Run reference was not used")
        self.status_queries.append(run_id)
        if self.status_entered is not None:
            self.status_entered.set()
        if self.status_release is not None and not self.status_release.wait(timeout=5):
            raise TimeoutError("test status gate timed out")
        return AgentRun(
            id=context.mentat_run_id,
            task_id=task.id,
            agent_id=submission_context.agent_id,
            runtime_type=self.runtime_type,
            status=self.observed_status,
        )

    def stream_events(self, run_id, after_sequence=0, *, context=None):
        expected = context.runtime_run_ref or context.mentat_run_id
        if run_id != expected:
            raise AssertionError("runtime-owned Run reference was not used")
        self.event_queries.append((run_id, after_sequence))
        events = list(self.events) if self.events is not None else [
            AgentEvent(
                id="runtime_event_progress",
                run_id=context.mentat_run_id,
                sequence=1,
                type=AgentEventType.MESSAGE,
                occurred_at="2026-08-18T13:00:00+00:00",
                summary="Runtime progress observed",
            )
        ]
        terminal_type = {
            RunStatus.COMPLETED: AgentEventType.RUN_COMPLETED,
            RunStatus.FAILED: AgentEventType.RUN_FAILED,
            RunStatus.STOPPED: AgentEventType.RUN_STOPPED,
            RunStatus.INTERRUPTED: AgentEventType.RUN_INTERRUPTED,
        }.get(self.observed_status)
        if terminal_type is not None and not any(
            event.type == terminal_type for event in events
        ):
            events.append(
                AgentEvent(
                    id=f"runtime_finalized_{context.mentat_run_id}",
                    run_id=context.mentat_run_id,
                    sequence=max((event.sequence for event in events), default=0) + 1,
                    type=terminal_type,
                    occurred_at="2026-08-18T13:00:01+00:00",
                    summary=f"Run {self.observed_status.value}",
                )
            )
        return tuple(
            event
            for event in events
            if not self.honor_after_sequence or event.sequence > after_sequence
        )

    def capabilities_for_run(self, run_id, *, context=None):
        expected = context.runtime_run_ref or context.mentat_run_id
        if run_id != expected:
            raise AssertionError("runtime-owned Run reference was not used")
        capabilities = {"run.message", "run.status"}
        if self.resume_supported:
            capabilities.add("run.resume")
        return frozenset(capabilities)

    def resume_task(self, task, source_run_ref, context):
        if not self.resume_supported:
            raise AssertionError("Resume was not advertised")
        self.resume_calls.append((source_run_ref, context))
        return self.submit_task(task, context)

    def send_message(self, run_id, message, *, context=None):
        expected = context.runtime_run_ref or context.mentat_run_id
        if run_id != expected:
            raise AssertionError("runtime-owned Run reference was not used")
        self.steer_calls.append((run_id, message, context))


class OrchestrationServiceTests(unittest.TestCase):
    @staticmethod
    def qualify_codex_capacity(runtime: FakeRuntime) -> None:
        runtime.runtime_type = "codex"
        runtime.runtime_agent_ref = "default"
        runtime.capacity_scope = "codex-app-server:" + "a" * 64

    def prepare(
        self,
        root: Path,
        runtime: FakeRuntime,
        *,
        task_id: str = "task-service",
        agent_capabilities: tuple[str, ...] = ("run.start", "run.message"),
    ) -> OrchestrationService:
        task = task_fixture()
        task["id"] = task_id
        source = root / "tasks.json"
        source.write_text(json.dumps([task], sort_keys=True) + "\n", encoding="utf-8")
        source.chmod(0o600)
        ensure_run_sqlite_authority(root, history_path(root))
        registry = AgentRegistry(root, supported_runtime_types=(runtime.runtime_type,))
        registry.create_agent(
            agent_id="agent-service",
            name="Service Agent",
            runtime_config_id="config-service",
            runtime_type=runtime.runtime_type,
            runtime_agent_ref=runtime.runtime_agent_ref,
            capabilities=agent_capabilities,
        )
        identifiers = iter(
            (
                "dispatch_service_1",
                "run_service_1",
                "dispatch_unused_1",
                "run_unused_1",
                "dispatch_unused_2",
                "run_unused_2",
                "dispatch_unused_3",
                "run_unused_3",
            )
        )
        return OrchestrationService(
            root,
            runtime_registry=AgentRuntimeRegistry((runtime,)),
            agent_registry=registry,
            id_factory=lambda _prefix: next(identifiers),
        )

    def prepare_conversation(
        self,
        root: Path,
        runtime: FakeRuntime,
        *,
        agent_capabilities: tuple[str, ...] = ("run.start", "run.message"),
    ) -> tuple[OrchestrationService, str]:
        task_service = self.prepare(
            root,
            runtime,
            agent_capabilities=agent_capabilities,
        )
        conversation = ConversationRepository(
            root,
            supported_runtime_types=(runtime.runtime_type,),
        ).create(agent_id="agent-service")
        identifiers = iter(
            (
                "msg_service_1",
                "turn_service_1",
                "run_conversation_1",
                "msg_service_2",
                "turn_service_2",
                "run_conversation_2",
            )
        )
        service = OrchestrationService(
            root,
            runtime_registry=task_service.runtime_registry,
            agent_registry=task_service.agent_registry,
            id_factory=lambda _prefix: next(identifiers),
        )
        return service, conversation.conversation.id

    @staticmethod
    def worker_snapshot(
        submitted: ConversationTurnDispatchResult,
        *,
        status: str,
        partial: bool,
        response: str = "",
        finalized: bool = True,
    ) -> dict:
        events = []
        if finalized:
            events.append(
                {
                    "schema_version": 1,
                    "id": f"event_finalized_{submitted.run.id}",
                    "run_id": submitted.run.id,
                    "sequence": 1,
                    "cursor": 1,
                    "type": "runtime.finalized",
                    "kind": "runtime.finalized",
                    "timestamp": submitted.run.updated_at,
                    "data": {},
                    "display_text": "Runtime finalized",
                    "message": "Runtime finalized",
                }
            )
        return {
            "id": submitted.run.id,
            "runtime_type": "hermes",
            "agent_id": "profile-service",
            "agent_name": "Service Agent",
            "model": "provider/model",
            "provider": "provider",
            "transport_mode": "local",
            "connection_binding_id": "local-default",
            "status": status,
            "partial": partial,
            "prompt": submitted.message.content["parts"][0]["text"],
            "response": response,
            "error": "" if status == "completed" else "Runtime did not complete.",
            "events": events,
            "created_at": submitted.run.created_at,
            "updated_at": submitted.run.updated_at,
            "started_at": submitted.run.started_at,
            "completed_at": submitted.run.updated_at,
            "attachments": [],
            "artifacts": [],
            "mentat_agent_id": "agent-service",
            "task_id": submitted.turn.id,
            "_dispatch_id": submitted.turn.id,
        }

    def test_dispatch_commits_attempt_before_one_unlocked_runtime_call(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)

            result = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-request-key-1",
            )

        self.assertFalse(result.duplicate)
        self.assertEqual(result.disposition, "accepted")
        self.assertEqual(result.run.status, "starting")
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(runtime.calls[0][2:], ("submitting", 1))
        self.assertEqual(runtime.calls[0][1].mentat_run_id, "run_service_1")
        self.assertEqual(runtime.calls[0][1].dispatch_id, "dispatch_service_1")

    def test_task_capacity_discovery_never_holds_the_private_state_lock(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.capacity_entered = threading.Event()
            runtime.capacity_release = threading.Event()
            service = self.prepare(root, runtime)
            failures = []

            def dispatch():
                try:
                    service.dispatch_task(
                        task_id="task-service",
                        expected_revision=1,
                        idempotency_key="capacity-lock-probe-key-1",
                    )
                except Exception as exc:  # pragma: no cover - surfaced below
                    failures.append(exc)

            worker = threading.Thread(target=dispatch)
            worker.start()
            self.assertTrue(runtime.capacity_entered.wait(timeout=2))
            acquired = threading.Event()

            def probe_lock():
                with private_state_lock(root):
                    acquired.set()

            probe = threading.Thread(target=probe_lock)
            probe.start()
            try:
                self.assertTrue(acquired.wait(timeout=1))
            finally:
                runtime.capacity_release.set()
            worker.join(timeout=5)
            probe.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertFalse(probe.is_alive())
        self.assertEqual(failures, [])

    def test_task_capability_discovery_never_holds_the_private_state_lock(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            runtime.capabilities_entered = threading.Event()
            runtime.capabilities_release = threading.Event()
            failures = []

            def dispatch():
                try:
                    service.dispatch_task(
                        task_id="task-service",
                        expected_revision=1,
                        idempotency_key="capability-lock-probe-key-1",
                    )
                except Exception as exc:  # pragma: no cover - surfaced below
                    failures.append(exc)

            worker = threading.Thread(target=dispatch)
            worker.start()
            self.assertTrue(runtime.capabilities_entered.wait(timeout=2))
            acquired = threading.Event()

            def probe_lock():
                with private_state_lock(root):
                    acquired.set()

            probe = threading.Thread(target=probe_lock)
            probe.start()
            try:
                self.assertTrue(acquired.wait(timeout=1))
            finally:
                runtime.capabilities_release.set()
            worker.join(timeout=5)
            probe.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertFalse(probe.is_alive())
        self.assertEqual(failures, [])

    def test_conversation_turn_commits_authority_before_one_unlocked_runtime_call(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)

            result = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Prove the Conversation Turn path.",
                idempotency_key="conversation-request-key-1",
            )

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                row = connection.execute(
                    "SELECT execution_config_json, execution_config_digest, "
                    "runtime_execution_json, runtime_execution_digest, "
                    "runtime_config_revision, capacity_scope_digest, "
                    "admitted_capacity_limit "
                    "FROM mentat_runs WHERE id = ?",
                    (result.run.id,),
                ).fetchone()
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE mentat_runs SET admitted_capacity_limit = 2 WHERE id = ?",
                        (result.run.id,),
                    )
                connection.rollback()
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE mentat_runs SET runtime_execution_json = '{}' "
                        "WHERE id = ?",
                        (result.run.id,),
                    )
                connection.rollback()
                repository.validate()
                self.assertEqual(repository.list_summaries(), [])
                with self.assertRaisesRegex(
                    RunRepositoryConflict,
                    "run.console_authority_conflict",
                ):
                    repository.sync_summaries(
                        [
                            {
                                "id": result.run.id,
                                "runtime_type": "hermes",
                                "status": "completed",
                                "created_at": "2026-08-18T12:00:00+00:00",
                                "updated_at": "2026-08-18T12:00:01+00:00",
                                "started_at": "2026-08-18T12:00:00+00:00",
                                "completed_at": "2026-08-18T12:00:01+00:00",
                                "events": [],
                            }
                        ]
                    )
            finally:
                connection.close()
            unit = capture_private_console_unit(root)

        self.assertFalse(result.duplicate)
        self.assertEqual(result.disposition, "accepted")
        self.assertEqual(result.message.content["parts"][0]["text"], "Prove the Conversation Turn path.")
        self.assertEqual(result.turn.state, "consumed")
        self.assertEqual(result.turn.attempt_count, 1)
        self.assertEqual(result.run.status, "starting")
        self.assertEqual(result.run.conversation_id, conversation_id)
        self.assertEqual(result.run.turn_id, result.turn.id)
        self.assertEqual(runtime.calls[0][2:], ("dispatching", 1))
        self.assertEqual(len(row["execution_config_digest"]), 64)
        self.assertEqual(len(row["runtime_execution_digest"]), 64)
        self.assertEqual(row["runtime_config_revision"], 1)
        self.assertEqual(
            json.loads(row["runtime_execution_json"]),
            {
                "contract": "mentat-runtime-execution-identity-v1",
                "model": "test-model",
                "provider": "test-provider",
                "reasoning_effort": "medium",
                "verification": "runtime_response",
            },
        )
        self.assertEqual(len(row["capacity_scope_digest"]), 64)
        self.assertEqual(row["admitted_capacity_limit"], 1)
        self.assertNotIn("profile-service", row["execution_config_json"])
        self.assertEqual(unit.run_count, 1)

    def test_conversation_submission_guard_covers_reservation_through_adapter_call(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.submission_lock = threading.Lock()
            service, conversation_id = self.prepare_conversation(root, runtime)
            result = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Hold the adapter configuration boundary",
                idempotency_key="conversation-submission-guard-key",
            )

        self.assertEqual(result.disposition, "accepted")
        self.assertTrue(runtime.guard_observed)

    def test_conversation_turn_crosses_only_the_safe_private_bridge_projection(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "AGENT_RUNTIME_REGISTRY",
                service.runtime_registry,
            ), patch.object(
                server,
                "AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED",
                True,
            ):
                payload, status = local_bridge.bridge_submit_conversation_turn_payload(
                    conversation_id,
                    {
                        "idempotency_key": "conversation-bridge-key-1",
                        "text": "Cross the safe bridge",
                    },
                )

        self.assertEqual(status, 202)
        self.assertEqual(
            set(payload),
            {
                "schema_version", "service", "runtime", "status", "duplicate",
                "disposition", "conversation", "message", "turn", "run",
            },
        )
        serialized = json.dumps(payload, sort_keys=True)
        for private in (
            "profile-service",
            "runtime_config_id",
            "runtime_binding_digest",
            "execution_config",
            "capacity_scope",
        ):
            self.assertNotIn(private, serialized)
        self.assertEqual(len(runtime.calls), 1)

    def test_browser_submission_takes_shutdown_gate_before_runtime_guard(self):
        class ObservedRLock:
            def __init__(self):
                self.lock = threading.RLock()
                self.waiting = threading.Event()

            def acquire(self, *args, **kwargs):
                self.waiting.set()
                return self.lock.acquire(*args, **kwargs)

            def release(self):
                self.lock.release()

            def __enter__(self):
                self.acquire()
                return self

            def __exit__(self, *_args):
                self.release()

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.submission_lock = server.HERMES_CONNECTION_OPERATION_LOCK
            service, conversation_id = self.prepare_conversation(root, runtime)
            drain = ObservedRLock()
            responses = []
            errors = []

            def submit_from_browser():
                try:
                    responses.append(
                        server.submit_mentat_conversation_turn(
                            conversation_id,
                            {
                                "idempotency_key": "conversation-lock-order-key",
                                "text": "Do not launch during shutdown",
                            },
                        )
                    )
                except Exception as exc:  # pragma: no cover - surfaced below
                    errors.append(exc)

            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "AGENT_RUNTIME_REGISTRY",
                service.runtime_registry,
            ), patch.object(
                server,
                "_mentat_agent_registry",
                return_value=service.agent_registry,
            ), patch.object(
                server,
                "AGENT_CONSOLE_CONTINUATION_DRAIN_LOCK",
                drain,
            ), patch.object(
                server,
                "AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED",
                True,
            ):
                drain.acquire()
                drain.waiting.clear()
                worker = threading.Thread(target=submit_from_browser)
                worker.start()
                self.assertTrue(drain.waiting.wait(timeout=5))
                acquired_runtime = server.HERMES_CONNECTION_OPERATION_LOCK.acquire(
                    timeout=1
                )
                self.assertTrue(acquired_runtime)
                if acquired_runtime:
                    server.HERMES_CONNECTION_OPERATION_LOCK.release()
                server.AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED = False
                drain.release()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

            connection = connect(root)
            try:
                turn_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_conversation_turns "
                        "WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()[0]
                )
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(errors, [])
        self.assertEqual(
            responses,
            [({"error_code": "conversation.unavailable"}, 503)],
        )
        self.assertEqual(turn_count, 0)
        self.assertEqual(runtime.calls, [])

    def test_conversation_turn_retry_is_exact_and_never_calls_runtime_twice(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="One exact request",
                idempotency_key="conversation-request-key-2",
            )
            duplicate = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="One exact request",
                idempotency_key="conversation-request-key-2",
            )
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.idempotency_conflict",
            ):
                service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Changed request",
                    idempotency_key="conversation-request-key-2",
                )

        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.message.id, first.message.id)
        self.assertEqual(duplicate.turn.id, first.turn.id)
        self.assertEqual(duplicate.run.id, first.run.id)
        self.assertEqual(len(runtime.calls), 1)

    def test_explicit_conversation_retry_creates_one_new_run_and_replays_exactly(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.rejects = True
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Retry this exact failed Turn",
                idempotency_key="conversation-initial-retry-key",
            )
            self.assertEqual(first.run.status, "failed")
            runtime.rejects = False

            retried = service.retry_conversation_run(
                conversation_id=conversation_id,
                source_run_id=first.run.id,
                idempotency_key="conversation-explicit-retry-key",
            )
            replay = service.retry_conversation_run(
                conversation_id=conversation_id,
                source_run_id=first.run.id,
                idempotency_key="conversation-explicit-retry-key",
            )
            runtime.observed_status = RunStatus.FAILED
            service.reconcile_run(
                run_id=retried.attempt.run_id,
                owner="retry_chain_reconciler",
            )
            second_retry = service.retry_conversation_run(
                conversation_id=conversation_id,
                source_run_id=retried.attempt.run_id,
                idempotency_key="conversation-second-retry-key",
            )
            old_replay = service.retry_conversation_run(
                conversation_id=conversation_id,
                source_run_id=first.run.id,
                idempotency_key="conversation-explicit-retry-key",
            )

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                old_run = repository.get_run(first.run.id)
                new_run = repository.get_run(retried.attempt.run_id)
                turn = connection.execute(
                    "SELECT latest_run_id, attempt_count FROM "
                    "mentat_conversation_turns WHERE id = ?",
                    (first.turn.id,),
                ).fetchone()
                run_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_runs WHERE turn_id = ?",
                        (first.turn.id,),
                    ).fetchone()[0]
                )
                old_event_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_agent_events WHERE run_id = ?",
                        (first.run.id,),
                    ).fetchone()[0]
                )
                repository.validate()
            finally:
                connection.close()

        self.assertFalse(retried.duplicate)
        self.assertTrue(replay.duplicate)
        self.assertEqual(replay.attempt.run_id, retried.attempt.run_id)
        self.assertEqual(old_run.status, "failed")
        self.assertEqual(new_run.retry_of_run_id, first.run.id)
        self.assertEqual(new_run.turn_id, first.turn.id)
        self.assertEqual(turn["latest_run_id"], second_retry.attempt.run_id)
        self.assertEqual(int(turn["attempt_count"]), 3)
        self.assertEqual(run_count, 3)
        self.assertGreater(old_event_count, 0)
        self.assertTrue(old_replay.duplicate)
        self.assertEqual(old_replay.attempt.run_id, retried.attempt.run_id)
        self.assertEqual(len(runtime.calls), 3)

    def test_conversation_resume_requires_exact_advertised_private_continuity(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.resume_supported = True
            service, conversation_id = self.prepare_conversation(
                root,
                runtime,
                agent_capabilities=("run.start", "run.message", "run.resume"),
            )
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Resume this exact stopped Turn",
                idempotency_key="conversation-resume-source-key",
            )
            runtime.observed_status = RunStatus.STOPPED
            reconciled = service.reconcile_run(
                run_id=first.run.id,
                owner="resume_source_reconciler",
            )
            self.assertEqual(reconciled.reconciled, (first.run.id,))

            resumed = service.resume_conversation_run(
                conversation_id=conversation_id,
                source_run_id=first.run.id,
                idempotency_key="conversation-explicit-resume-key",
            )
            replay = service.resume_conversation_run(
                conversation_id=conversation_id,
                source_run_id=first.run.id,
                idempotency_key="conversation-explicit-resume-key",
            )

            connection = connect(root)
            try:
                stored = RunRepository(connection).get_run(
                    resumed.attempt.run_id
                )
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(stored.resume_of_run_id, first.run.id)
        self.assertIsNone(stored.retry_of_run_id)
        self.assertEqual(runtime.resume_calls[0][0], "runtime-service-ref")
        self.assertTrue(replay.duplicate)
        self.assertEqual(len(runtime.resume_calls), 1)

    def test_conversation_resume_is_absent_without_declared_capability(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Do not fabricate Resume",
                idempotency_key="conversation-no-resume-source-key",
            )
            runtime.observed_status = RunStatus.STOPPED
            service.reconcile_run(
                run_id=first.run.id,
                owner="no_resume_source_reconciler",
            )
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.agent_capability_missing",
            ):
                service.resume_conversation_run(
                    conversation_id=conversation_id,
                    source_run_id=first.run.id,
                    idempotency_key="conversation-no-resume-action-key",
                )

        self.assertEqual(runtime.resume_calls, [])

    def test_archiving_an_active_conversation_never_stops_its_run(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep running while the tab is archived",
                idempotency_key="conversation-active-archive-key",
            )
            repository = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            )
            current = repository.read(conversation_id).conversation
            archived = repository.set_archived(
                conversation_id,
                expected_revision=current.revision,
                archived=True,
            )
            runtime.observed_status = RunStatus.COMPLETED
            reconciled = service.reconcile_run(
                run_id=submitted.run.id,
                owner="archived_completion_reconciler",
            )
            connection = connect(root)
            try:
                run_after_archive = RunRepository(connection).get_run(
                    submitted.run.id
                )
            finally:
                connection.close()
            restored = repository.set_archived(
                conversation_id,
                expected_revision=archived.revision,
                archived=False,
            )

        self.assertEqual(archived.state, "archived")
        self.assertEqual(restored.state, "active")
        self.assertEqual(reconciled.reconciled, (submitted.run.id,))
        self.assertEqual(run_after_archive.status, "completed")
        self.assertEqual(len(runtime.calls), 1)

    def test_activity_marks_unverified_restart_state_as_reconciling(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Do not present stale restart state as live",
                idempotency_key="conversation-activity-reconcile-key",
            )
            runtime.status_entered = threading.Event()
            runtime.status_release = threading.Event()
            server._clear_agent_console_verified_runs()
            started = time.monotonic()
            with patch.object(server, "DATA_DIR", root):
                payload, status = local_bridge.bridge_agent_activity_payload()
            elapsed = time.monotonic() - started
            server._clear_agent_console_verified_runs()

        self.assertEqual(status, 200)
        self.assertLess(elapsed, 1.0)
        self.assertFalse(runtime.status_entered.is_set())
        projected = next(
            item for item in payload["activity"]
            if item["agent"]["id"] == submitted.conversation.agent_id
        )
        exact = next(
            item for item in projected["conversations"]
            if item["id"] == conversation_id
        )
        self.assertEqual(projected["state"], "checking")
        self.assertEqual(projected["summary"], "Checking exact runtime state")
        self.assertFalse(projected["attention"])
        self.assertEqual(exact["run_status"], "reconciling")
        self.assertFalse(exact["attention"])

    def test_activity_claims_working_only_after_exact_readback(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Verify this exact active Run",
                idempotency_key="conversation-activity-verified-key",
            )
            server._clear_agent_console_verified_runs()
            server._mark_agent_console_runs_verified(submitted.run.id)
            with patch.object(server, "DATA_DIR", root):
                payload = server.mentat_agent_activity_payload()
            server._clear_agent_console_verified_runs()

        projected = next(
            item for item in payload["activity"]
            if item["agent"]["id"] == submitted.conversation.agent_id
        )
        exact = next(
            item for item in projected["conversations"]
            if item["id"] == conversation_id
        )
        self.assertEqual(projected["state"], "working")
        self.assertEqual(exact["run_status"], submitted.run.status)

    def test_duplicate_turn_replay_cannot_recreate_a_liveness_receipt(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            key = "conversation-duplicate-liveness-key"
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Replay this exact accepted Turn after restart",
                idempotency_key=key,
            )
            server._clear_agent_console_verified_runs()
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "AGENT_RUNTIME_REGISTRY", service.runtime_registry),
                patch.object(server, "_mentat_agent_registry", return_value=service.agent_registry),
                patch.object(server, "AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED", True),
                patch.object(server, "agent_console_storage_degraded", return_value=False),
            ):
                replay, status = server.submit_mentat_conversation_turn(
                    conversation_id,
                    {"idempotency_key": key, "text": "Replay this exact accepted Turn after restart"},
                )
                activity = server.mentat_agent_activity_payload()
            server._clear_agent_console_verified_runs()

        self.assertEqual(status, 200)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["run"]["id"], first.run.id)
        self.assertEqual(len(runtime.calls), 1)
        projected = next(
            item for item in activity["activity"]
            if item["agent"]["id"] == first.conversation.agent_id
        )
        self.assertEqual(projected["state"], "checking")
        self.assertEqual(projected["conversations"][0]["run_status"], "reconciling")

    def test_duplicate_retry_replay_cannot_recreate_a_liveness_receipt(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Fail before the exact Retry",
                idempotency_key="conversation-duplicate-retry-source",
            )
            runtime.observed_status = RunStatus.FAILED
            service.reconcile_run(
                run_id=first.run.id,
                owner="duplicate_retry_source_reconciler",
            )
            key = "conversation-duplicate-retry-action"
            retried = service.retry_conversation_run(
                conversation_id=conversation_id,
                source_run_id=first.run.id,
                idempotency_key=key,
            )
            server._clear_agent_console_verified_runs()
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "AGENT_RUNTIME_REGISTRY", service.runtime_registry),
                patch.object(server, "_mentat_agent_registry", return_value=service.agent_registry),
                patch.object(server, "AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED", True),
                patch.object(server, "agent_console_storage_degraded", return_value=False),
            ):
                replay, status = server.retry_mentat_conversation_run(
                    conversation_id,
                    {"idempotency_key": key, "source_run_id": first.run.id},
                )
                activity = server.mentat_agent_activity_payload()
            server._clear_agent_console_verified_runs()

        self.assertEqual(status, 200)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["run"]["id"], retried.attempt.run_id)
        self.assertEqual(len(runtime.calls), 2)
        projected = next(
            item for item in activity["activity"]
            if item["agent"]["id"] == first.conversation.agent_id
        )
        self.assertEqual(projected["state"], "checking")
        self.assertEqual(projected["conversations"][0]["run_status"], "reconciling")

    def test_archived_completion_preserves_a_queued_turn_without_dispatching_it(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Finish the active archived Run",
                idempotency_key="conversation-archived-queue-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep this queued until the Conversation is restored",
                idempotency_key="conversation-archived-queue-key-2",
            )
            repository = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            )
            current = repository.read(conversation_id).conversation
            repository.set_archived(
                conversation_id,
                expected_revision=current.revision,
                archived=True,
            )
            runtime.observed_status = RunStatus.COMPLETED
            reconciled = service.reconcile_run(
                run_id=submitted.run.id,
                owner="archived_queued_completion_reconciler",
            )
            detail = repository.read(conversation_id)
            restored = repository.set_archived(
                conversation_id,
                expected_revision=detail.conversation.revision,
                archived=False,
            )
            service.id_factory = lambda prefix: f"{prefix}_archived_continued"
            continued = service.continue_conversation_turn(
                conversation_id=conversation_id,
                turn_id=detail.queued_turns[0].id,
                expected_revision=detail.queued_turns[0].revision,
                expected_message_revision=detail.queued_turns[0].message_revision,
            )

        self.assertEqual(reconciled.reconciled, (submitted.run.id,))
        self.assertEqual(detail.current_run["status"], "completed")
        self.assertEqual(len(detail.queued_turns), 1)
        self.assertEqual(detail.queued_turns[0].id, queued.turn.id)
        self.assertEqual(detail.queued_turns[0].state, "blocked")
        self.assertEqual(detail.queued_turns[0].blocked_reason, "partial")
        self.assertEqual(restored.state, "active")
        self.assertIsNotNone(continued.run)
        self.assertEqual(continued.turn.id, queued.turn.id)
        self.assertEqual(len(runtime.calls), 2)

    def test_immediate_completion_commits_when_conversation_is_archived_in_flight(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_completed = True
            runtime.submit_entered = threading.Event()
            runtime.submit_release = threading.Event()
            service, conversation_id = self.prepare_conversation(root, runtime)
            results = []
            failures = []

            def submit_first():
                try:
                    results.append(service.submit_conversation_turn(
                        conversation_id=conversation_id,
                        text="Complete after this Conversation is archived",
                        idempotency_key="conversation-archive-immediate-key",
                    ))
                except Exception as exc:  # pragma: no cover - surfaced below
                    failures.append(exc)

            worker = threading.Thread(target=submit_first)
            worker.start()
            self.assertTrue(runtime.submit_entered.wait(timeout=5))
            repository = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            )
            current = repository.read(conversation_id).conversation
            repository.set_archived(
                conversation_id,
                expected_revision=current.revision,
                archived=True,
            )
            runtime.submit_release.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            if failures:
                raise failures[0]
            detail = repository.read(conversation_id)

        self.assertEqual(failures, [])
        self.assertEqual(results[0].run.status, "completed")
        self.assertEqual(detail.conversation.state, "archived")
        self.assertEqual(detail.current_run["status"], "finalizing")
        self.assertEqual(len(runtime.calls), 1)

    def test_restart_interrupts_an_unattempted_retry_without_resubmission(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.rejects = True
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Do not resubmit this reserved Retry after restart",
                idempotency_key="conversation-restart-retry-source",
            )
            runtime.rejects = False
            record, binding = service._agent_record_and_binding(first.conversation.agent_id)
            admission = service._conversation_admission(
                record=record,
                binding=binding,
                runtime=runtime,
                binding_digest=service._binding_digest(record.agent, binding),
                run_id="run_retry_restart_reserved",
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_conversation_run_attempt(
                    action="retry",
                    idempotency_key="conversation-restart-retry-action",
                    conversation_id=conversation_id,
                    source_run_id=first.run.id,
                    admission=admission,
                )
                recovered = repository.recover_conversation_submissions()
                retry_run = repository.get_run(reservation.run_id)
                receipt = repository.get_conversation_run_attempt_result(
                    idempotency_key="conversation-restart-retry-action"
                )
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(recovered, (reservation.run_id,))
        self.assertEqual(retry_run.status, "interrupted")
        self.assertTrue(retry_run.partial)
        self.assertEqual(receipt.status, "interrupted")
        self.assertEqual(len(runtime.calls), 1)

    def test_conversation_turn_accepts_exactly_six_thousand_astral_code_points(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            text = "😀" * 6_000
            result = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text=text,
                idempotency_key="conversation-unicode-key-6000",
            )

        self.assertEqual(result.message.content["parts"][0]["text"], text)
        self.assertEqual(result.disposition, "accepted")
        self.assertEqual(len(runtime.calls), 1)

    def test_conversation_turn_rejects_six_thousand_and_one_code_points_before_writes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.request_invalid",
            ):
                service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="😀" * 6_001,
                    idempotency_key="conversation-unicode-key-6001",
                )
            connection = connect(root)
            try:
                counts = connection.execute(
                    "SELECT (SELECT COUNT(*) FROM mentat_conversation_messages), "
                    "(SELECT COUNT(*) FROM mentat_conversation_turns), "
                    "(SELECT COUNT(*) FROM mentat_runs WHERE conversation_id IS NOT NULL)"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(tuple(counts), (0, 0, 0))
        self.assertEqual(runtime.calls, [])

    def test_conversation_retry_survives_full_run_retention_without_resubmission(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.rejects = True
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Retain the exact idempotency result",
                idempotency_key="conversation-retention-key-1",
            )
            terminal_runs = [
                {
                    "id": f"run_retention_{index:03d}",
                    "runtime_type": "hermes",
                    "agent_id": "profile-service",
                    "agent_name": "Hermes",
                    "model": "provider/model",
                    "transport_mode": "local",
                    "connection_binding_id": "local-default",
                    "status": "completed",
                    "prompt": "Retention fixture",
                    "response": "Done",
                    "error": "",
                    "events": [],
                    "created_at": "2027-01-01T00:00:00+00:00",
                    "updated_at": "2027-01-01T00:00:01+00:00",
                    "started_at": "2027-01-01T00:00:00+00:00",
                    "completed_at": "2027-01-01T00:00:01+00:00",
                    "attachments": [],
                    "artifacts": [],
                }
                for index in range(run_repository.TERMINAL_RUN_RETENTION + 1)
            ]
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                repository.sync_summaries(terminal_runs)
                with self.assertRaisesRegex(RunRepositoryConflict, "run.not_found"):
                    repository.get_run(first.run.id)
                retained = repository.get_conversation_submission_result(first.turn.id)
                repository.validate()
            finally:
                connection.close()
            duplicate = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Retain the exact idempotency result",
                idempotency_key="conversation-retention-key-1",
            )

        self.assertEqual(retained.id, first.run.id)
        self.assertEqual(retained.status, "failed")
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.disposition, "rejected")
        self.assertEqual(duplicate.run.id, first.run.id)
        self.assertEqual(duplicate.message.run_id, first.run.id)
        self.assertEqual(duplicate.turn.latest_run_id, first.run.id)
        self.assertEqual(len(runtime.calls), 1)

    def test_conversation_unknown_accepts_a_blocked_followup_without_another_run(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Ambiguous request",
                idempotency_key="conversation-request-key-3",
            )
            blocked = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Competing request",
                idempotency_key="conversation-request-key-4",
            )
            connection = connect(root)
            try:
                counts = connection.execute(
                    "SELECT (SELECT COUNT(*) FROM mentat_conversation_messages), "
                    "(SELECT COUNT(*) FROM mentat_conversation_turns), "
                    "(SELECT COUNT(*) FROM mentat_runs WHERE conversation_id = ?)",
                    (conversation_id,),
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(first.run.status, "unknown")
        self.assertEqual(blocked.disposition, "blocked")
        self.assertEqual(blocked.turn.state, "blocked")
        self.assertEqual(blocked.turn.blocked_reason, "unknown")
        self.assertIsNone(blocked.run)
        self.assertEqual(tuple(counts), (2, 2, 1))
        self.assertEqual(len(runtime.calls), 1)

    def test_active_conversation_accepts_ordinary_followup_as_pending(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep this Run active",
                idempotency_key="conversation-active-queue-key-1",
            )
            pending = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Queue this exact follow-up",
                idempotency_key="conversation-active-queue-key-2",
            )
            connection = connect(root)
            try:
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(first.disposition, "accepted")
        self.assertEqual(pending.disposition, "pending")
        self.assertEqual(pending.turn.state, "pending")
        self.assertIsNone(pending.turn.latest_run_id)
        self.assertIsNone(pending.message.run_id)
        self.assertIsNone(pending.run)
        self.assertEqual(len(runtime.calls), 1)

    def test_conversation_queue_caps_at_eight_without_partial_ninth_rows(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            counters = {"msg": 0, "turn": 0, "run": 0}

            def next_identifier(prefix):
                counters[prefix] += 1
                return f"{prefix}_queue_cap_{counters[prefix]}"

            service.id_factory = next_identifier
            service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep one Run active for the queue cap",
                idempotency_key="conversation-queue-cap-active-key",
            )
            queued = [
                service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text=f"Queued request {index}",
                    idempotency_key=f"conversation-queue-cap-key-{index:02d}",
                )
                for index in range(1, 9)
            ]
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.turn_capacity",
            ):
                service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="This ninth queued request must not persist",
                    idempotency_key="conversation-queue-cap-key-09",
                )
            detail = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).read(conversation_id)
            connection = connect(root)
            try:
                counts = connection.execute(
                    "SELECT (SELECT COUNT(*) FROM mentat_conversation_messages), "
                    "(SELECT COUNT(*) FROM mentat_conversation_turns), "
                    "(SELECT COUNT(*) FROM mentat_runs WHERE conversation_id = ?)",
                    (conversation_id,),
                ).fetchone()
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual([item.disposition for item in queued], ["pending"] * 8)
        self.assertEqual(len(detail.queued_turns), 8)
        self.assertEqual([item.queue_ordinal for item in detail.queued_turns], list(range(2, 10)))
        self.assertEqual(tuple(counts), (9, 9, 1))
        self.assertEqual(len(runtime.calls), 1)

    def test_blocked_fifo_head_prevents_a_new_send_from_bypassing_it(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.rejects = True
            runtime.submit_entered = threading.Event()
            runtime.submit_release = threading.Event()
            service, conversation_id = self.prepare_conversation(root, runtime)
            counters = {"msg": 0, "turn": 0, "run": 0}

            def next_identifier(prefix):
                counters[prefix] += 1
                return f"{prefix}_blocked_fifo_{counters[prefix]}"

            service.id_factory = next_identifier
            failures = []

            def submit_rejected():
                try:
                    service.submit_conversation_turn(
                        conversation_id=conversation_id,
                        text="Reject after a follow-up becomes pending",
                        idempotency_key="conversation-blocked-fifo-key-1",
                    )
                except Exception as exc:  # pragma: no cover - surfaced below
                    failures.append(exc)

            worker = threading.Thread(target=submit_rejected)
            worker.start()
            self.assertTrue(runtime.submit_entered.wait(timeout=5))
            blocked = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="This exact head must stay first",
                idempotency_key="conversation-blocked-fifo-key-2",
            )
            runtime.submit_release.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            if failures:
                raise failures[0]
            appended = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Append without bypassing the blocked head",
                idempotency_key="conversation-blocked-fifo-key-3",
            )
            detail = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).read(conversation_id)

        self.assertEqual(blocked.turn.id, detail.queued_turns[0].id)
        self.assertEqual(detail.queued_turns[0].state, "blocked")
        self.assertEqual(detail.queued_turns[0].blocked_reason, "failed")
        self.assertEqual(appended.disposition, "pending")
        self.assertIsNone(appended.run)
        self.assertEqual([item.id for item in detail.queued_turns], [blocked.turn.id, appended.turn.id])
        self.assertEqual(len(runtime.calls), 1)

    def test_immediate_codex_completion_claims_one_concurrent_pending_head(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            self.qualify_codex_capacity(runtime)
            runtime.return_completed = True
            runtime.submit_entered = threading.Event()
            runtime.submit_release = threading.Event()
            service, conversation_id = self.prepare_conversation(root, runtime)
            results = []
            failures = []

            def submit_first():
                try:
                    results.append(service.submit_conversation_turn(
                        conversation_id=conversation_id,
                        text="Complete immediately after a follow-up arrives",
                        idempotency_key="conversation-immediate-complete-key-1",
                    ))
                except Exception as exc:  # pragma: no cover - surfaced below
                    failures.append(exc)

            worker = threading.Thread(target=submit_first)
            worker.start()
            self.assertTrue(runtime.submit_entered.wait(timeout=5))
            pending = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Claim this concurrent follow-up exactly once",
                idempotency_key="conversation-immediate-complete-key-2",
            )
            runtime.submit_release.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            if failures:
                raise failures[0]
            detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)
            connection = connect(root)
            try:
                turn = connection.execute(
                    "SELECT state, attempt_count, latest_run_id "
                    "FROM mentat_conversation_turns WHERE id = ?",
                    (pending.turn.id,),
                ).fetchone()
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(failures, [])
        self.assertEqual(results[0].run.status, "completed")
        self.assertEqual(pending.disposition, "pending")
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(runtime.calls[-1][0].objective, "Claim this concurrent follow-up exactly once")
        self.assertEqual(tuple(turn)[:2], ("consumed", 1))
        self.assertTrue(str(turn["latest_run_id"]).startswith("run_auto_"))
        self.assertEqual(detail.queued_turns, ())
        self.assertEqual([message.role for message in detail.messages], ["user", "user", "assistant", "assistant"])

    def test_queued_turn_edit_and_cancel_require_both_exact_revisions(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep this request active",
                idempotency_key="conversation-queue-cas-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Edit this queued request",
                idempotency_key="conversation-queue-cas-key-2",
            )

            edited = service.edit_conversation_turn(
                conversation_id=conversation_id,
                turn_id=queued.turn.id,
                expected_revision=queued.turn.revision,
                expected_message_revision=queued.message.revision,
                text="Use this exact edited request",
            )
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.turn_changed",
            ):
                service.cancel_conversation_turn(
                    conversation_id=conversation_id,
                    turn_id=queued.turn.id,
                    expected_revision=queued.turn.revision,
                    expected_message_revision=queued.message.revision,
                )
            cancelled = service.cancel_conversation_turn(
                conversation_id=conversation_id,
                turn_id=queued.turn.id,
                expected_revision=edited.turn.revision,
                expected_message_revision=edited.message.revision,
            )
            detail = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).read(conversation_id)

        self.assertEqual(edited.disposition, "edited")
        self.assertEqual(
            edited.message.content["parts"][0]["text"],
            "Use this exact edited request",
        )
        self.assertEqual(edited.turn.revision, queued.turn.revision + 1)
        self.assertEqual(edited.message.revision, queued.message.revision + 1)
        self.assertEqual(cancelled.disposition, "cancelled")
        self.assertEqual(cancelled.turn.state, "cancelled")
        self.assertEqual(cancelled.message.state, "cancelled")
        self.assertEqual(detail.queued_turns, ())

    def test_reconciliation_projects_one_exact_assistant_message(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Return one durable answer",
                idempotency_key="conversation-assistant-projection-key",
            )
            runtime.observed_status = RunStatus.COMPLETED
            runtime.events = (
                AgentEvent(
                    id="runtime_assistant_answer",
                    run_id=submitted.run.id,
                    sequence=1,
                    type=AgentEventType.MESSAGE,
                    occurred_at="2026-08-18T13:00:00+00:00",
                    summary="Assistant answer completed",
                    content="The durable answer is ready.",
                ),
            )

            first = service.reconcile_run(
                run_id=submitted.run.id,
                owner="assistant_projection_owner",
            )
            second = service.reconcile_run(
                run_id=submitted.run.id,
                owner="assistant_projection_replay_owner",
            )
            detail = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).read(conversation_id)
            connection = connect(root)
            try:
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(first.reconciled, (submitted.run.id,))
        self.assertEqual(second.leased, 0)
        self.assertEqual([message.role for message in detail.messages], ["user", "assistant"])
        self.assertEqual(
            detail.messages[-1].content["parts"][0]["text"],
            "The durable answer is ready.",
        )
        self.assertEqual(detail.messages[-1].run_id, submitted.run.id)

    def test_verified_success_claims_and_submits_only_the_oldest_pending_turn(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Run the first request",
                idempotency_key="conversation-fifo-success-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Run this follow-up next",
                idempotency_key="conversation-fifo-success-key-2",
            )
            runtime.observed_status = RunStatus.COMPLETED

            report = service.reconcile_run(
                run_id=first.run.id,
                owner="conversation_fifo_success_owner",
            )
            detail = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).read(conversation_id)
            connection = connect(root)
            try:
                queue_row = connection.execute(
                    "SELECT state, attempt_count, latest_run_id "
                    "FROM mentat_conversation_turns WHERE id = ?",
                    (queued.turn.id,),
                ).fetchone()
                run_count = connection.execute(
                    "SELECT COUNT(*) FROM mentat_runs WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(report.reconciled, (first.run.id,))
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(runtime.calls[-1][0].objective, "Run this follow-up next")
        self.assertEqual(tuple(queue_row)[:2], ("consumed", 1))
        self.assertTrue(str(queue_row["latest_run_id"]).startswith("run_auto_"))
        self.assertEqual(run_count, 2)
        self.assertEqual(detail.queued_turns, ())

    def test_terminal_event_closes_split_status_read_and_executes_fifo_successor(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.honor_after_sequence = True
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Finish while the status snapshot is stale",
                idempotency_key="conversation-split-observation-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Run after the exact terminal event",
                idempotency_key="conversation-split-observation-key-2",
            )
            runtime.observed_status = RunStatus.RUNNING
            runtime.events = (
                AgentEvent(
                    id="runtime_split_terminal",
                    run_id=first.run.id,
                    sequence=1,
                    type=AgentEventType.RUN_COMPLETED,
                    occurred_at="2026-08-18T13:00:01+00:00",
                    summary="Run completed after the status read",
                ),
            )

            first_report = service.reconcile_run(
                run_id=first.run.id,
                owner="split_observation_owner",
            )
            # A later status read could now be terminal with no newer event.
            # The exact terminal event already committed above must prevent
            # that split snapshot from leaving the canonical Run active.
            runtime.observed_status = RunStatus.COMPLETED
            runtime.events = ()
            replay_report = service.reconcile_run(
                run_id=first.run.id,
                owner="split_observation_replay_owner",
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                source = repository.get_run(first.run.id)
                successor = repository.conversation_turn_reservation(
                    queued.turn.id
                )
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(first_report.reconciled, (first.run.id,))
        self.assertEqual(replay_report.leased, 0)
        self.assertEqual(source.status, "completed")
        self.assertTrue(source.terminal_finalized)
        self.assertEqual(successor.state, "accepted")
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(
            runtime.calls[-1][0].objective,
            "Run after the exact terminal event",
        )
        self.assertEqual(runtime.status_queries, ["runtime-service-ref"])
        self.assertEqual(runtime.event_queries, [("runtime-service-ref", 0)])

    def test_competing_reconcilers_claim_one_pending_head_once(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Complete under a reconciliation race",
                idempotency_key="conversation-reconcile-race-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Claim this head once under the race",
                idempotency_key="conversation-reconcile-race-key-2",
            )
            runtime.observed_status = RunStatus.COMPLETED
            runtime.status_entered = threading.Event()
            runtime.status_release = threading.Event()
            barrier = threading.Barrier(3)
            reports = []
            failures = []

            def reconcile(owner):
                try:
                    barrier.wait(timeout=5)
                    reports.append(service.reconcile_run(run_id=first.run.id, owner=owner))
                except Exception as exc:  # pragma: no cover - surfaced below
                    failures.append(exc)

            workers = [
                threading.Thread(target=reconcile, args=(f"queue_race_owner_{index}",))
                for index in range(2)
            ]
            for worker in workers:
                worker.start()
            barrier.wait(timeout=5)
            status_read_started = runtime.status_entered.wait(timeout=10)
            runtime.status_release.set()
            for worker in workers:
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())
            if failures:
                raise failures[0]
            connection = connect(root)
            try:
                row = connection.execute(
                    "SELECT state, attempt_count, latest_run_id "
                    "FROM mentat_conversation_turns WHERE id = ?",
                    (queued.turn.id,),
                ).fetchone()
                run_count = connection.execute(
                    "SELECT COUNT(*) FROM mentat_runs WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(failures, [])
        self.assertTrue(
            status_read_started,
            (
                f"status read did not start; reports={reports!r}, "
                f"failures={failures!r}, status_queries={runtime.status_queries!r}"
            ),
        )
        self.assertEqual(sum(report.leased for report in reports), 1)
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(tuple(row)[:2], ("consumed", 1))
        self.assertTrue(str(row["latest_run_id"]).startswith("run_auto_"))
        self.assertEqual(run_count, 2)

    def test_non_successful_terminal_reconciliation_blocks_the_queue_head(self):
        for status, reason in (
            (RunStatus.FAILED, "failed"),
            (RunStatus.STOPPED, "stopped"),
            (RunStatus.INTERRUPTED, "interrupted"),
        ):
            with self.subTest(status=status.value), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                runtime = FakeRuntime(root)
                service, conversation_id = self.prepare_conversation(root, runtime)
                first = service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Run the active request",
                    idempotency_key=f"conversation-block-{reason}-key-1",
                )
                queued = service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Pause this queued request",
                    idempotency_key=f"conversation-block-{reason}-key-2",
                )
                runtime.observed_status = status

                report = service.reconcile_run(
                    run_id=first.run.id,
                    owner=f"conversation_block_{reason}_owner",
                )
                detail = ConversationRepository(
                    root,
                    supported_runtime_types=("hermes",),
                ).read(conversation_id)

            self.assertEqual(report.reconciled, (first.run.id,))
            self.assertEqual(len(runtime.calls), 1)
            self.assertEqual(len(detail.queued_turns), 1)
            self.assertEqual(detail.queued_turns[0].id, queued.turn.id)
            self.assertEqual(detail.queued_turns[0].state, "blocked")
            self.assertEqual(detail.queued_turns[0].blocked_reason, reason)

    def test_stopped_run_pauses_only_its_exact_conversation_queue(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            self.qualify_codex_capacity(runtime)
            runtime.capacity_limit = 2
            service, first_id = self.prepare_conversation(root, runtime)
            second_id = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).create(agent_id="agent-service").conversation.id
            counters = {"msg": 20, "turn": 20, "run": 20}

            def identifier(prefix):
                counters[prefix] += 1
                return f"{prefix}_stop_isolation_{counters[prefix]}"

            service.id_factory = identifier
            first = service.submit_conversation_turn(
                conversation_id=first_id,
                text="Run work in the first Conversation",
                idempotency_key="conversation-stop-isolation-key-1",
            )
            first_queued = service.submit_conversation_turn(
                conversation_id=first_id,
                text="Pause only this first queue",
                idempotency_key="conversation-stop-isolation-key-2",
            )
            second = service.submit_conversation_turn(
                conversation_id=second_id,
                text="Run work in the second Conversation",
                idempotency_key="conversation-stop-isolation-key-3",
            )
            second_queued = service.submit_conversation_turn(
                conversation_id=second_id,
                text="Keep this second queue pending",
                idempotency_key="conversation-stop-isolation-key-4",
            )
            runtime.observed_status = RunStatus.STOPPED

            report = service.reconcile_run(
                run_id=first.run.id,
                owner="conversation_stop_isolation_owner",
            )
            first_detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(first_id)
            second_detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(second_id)

        self.assertEqual(report.reconciled, (first.run.id,))
        self.assertEqual(first_detail.queued_turns[0].id, first_queued.turn.id)
        self.assertEqual(first_detail.queued_turns[0].state, "blocked")
        self.assertEqual(first_detail.queued_turns[0].blocked_reason, "stopped")
        self.assertEqual(second_detail.current_run["id"], second.run.id)
        self.assertEqual(second_detail.queued_turns[0].id, second_queued.turn.id)
        self.assertEqual(second_detail.queued_turns[0].state, "pending")
        self.assertIsNone(second_detail.queued_turns[0].blocked_reason)

    def test_explicit_continue_revalidates_and_dispatches_one_blocked_head(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Fail this active request",
                idempotency_key="conversation-explicit-continue-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Continue this request explicitly",
                idempotency_key="conversation-explicit-continue-key-2",
            )
            runtime.observed_status = RunStatus.FAILED
            service.reconcile_run(
                run_id=first.run.id,
                owner="conversation_explicit_continue_block_owner",
            )
            blocked = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).read(conversation_id).queued_turns[0]
            service.id_factory = lambda prefix: f"{prefix}_explicit_continue_1"

            continued = service.continue_conversation_turn(
                conversation_id=conversation_id,
                turn_id=blocked.id,
                expected_revision=blocked.revision,
                expected_message_revision=blocked.message_revision,
            )
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.turn_changed",
            ):
                service.continue_conversation_turn(
                    conversation_id=conversation_id,
                    turn_id=blocked.id,
                    expected_revision=blocked.revision,
                    expected_message_revision=blocked.message_revision,
                )

        self.assertEqual(queued.turn.id, blocked.id)
        self.assertEqual(continued.disposition, "accepted")
        self.assertEqual(continued.turn.state, "consumed")
        self.assertEqual(continued.run.id, "run_explicit_continue_1")
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(
            runtime.calls[-1][0].objective,
            "Continue this request explicitly",
        )

    def test_cancelling_a_blocked_head_leaves_its_successor_continuable(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            counters = {"msg": 30, "turn": 30, "run": 30}

            def identifier(prefix):
                counters[prefix] += 1
                return f"{prefix}_cancelled_head_{counters[prefix]}"

            service.id_factory = identifier
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Fail the active Turn",
                idempotency_key="cancelled-blocked-head-key-1",
            )
            service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Cancel this blocked head",
                idempotency_key="cancelled-blocked-head-key-2",
            )
            service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep this successor continuable",
                idempotency_key="cancelled-blocked-head-key-3",
            )
            runtime.observed_status = RunStatus.FAILED
            service.reconcile_run(
                run_id=first.run.id,
                owner="cancelled_blocked_head_owner",
            )
            repository = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            )
            before = repository.read(conversation_id).queued_turns
            service.cancel_conversation_turn(
                conversation_id=conversation_id,
                turn_id=before[0].id,
                expected_revision=before[0].revision,
                expected_message_revision=before[0].message_revision,
            )
            successor = repository.read(conversation_id).queued_turns[0]
            continued = service.continue_conversation_turn(
                conversation_id=conversation_id,
                turn_id=successor.id,
                expected_revision=successor.revision,
                expected_message_revision=successor.message_revision,
            )

        self.assertEqual(before[0].state, "blocked")
        self.assertEqual(before[1].state, "pending")
        self.assertEqual(successor.id, before[1].id)
        self.assertEqual(successor.state, "blocked")
        self.assertEqual(successor.blocked_reason, "failed")
        self.assertGreater(successor.revision, before[1].revision)
        self.assertEqual(continued.disposition, "accepted")
        self.assertEqual(len(runtime.calls), 2)

    def test_cancelling_a_non_head_blocked_turn_preserves_the_blocked_head(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            service, conversation_id = self.prepare_conversation(root, runtime)
            counters = {"msg": 40, "turn": 40, "run": 40}

            def identifier(prefix):
                counters[prefix] += 1
                return f"{prefix}_cancelled_blocked_tail_{counters[prefix]}"

            service.id_factory = identifier
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Leave runtime acceptance unknown",
                idempotency_key="cancelled-blocked-tail-key-1",
            )
            service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep this blocked head",
                idempotency_key="cancelled-blocked-tail-key-2",
            )
            service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Cancel this blocked tail",
                idempotency_key="cancelled-blocked-tail-key-3",
            )
            repository = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            )
            before = repository.read(conversation_id).queued_turns
            cancelled = service.cancel_conversation_turn(
                conversation_id=conversation_id,
                turn_id=before[1].id,
                expected_revision=before[1].revision,
                expected_message_revision=before[1].message_revision,
            )
            after = repository.read(conversation_id).queued_turns
            connection = connect(root)
            try:
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(first.disposition, "unknown")
        self.assertEqual([turn.state for turn in before], ["blocked", "blocked"])
        self.assertEqual(cancelled.disposition, "cancelled")
        self.assertEqual(cancelled.turn.id, before[1].id)
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0].id, before[0].id)
        self.assertEqual(after[0].state, "blocked")
        self.assertEqual(after[0].blocked_reason, "unknown")
        self.assertEqual(after[0].revision, before[0].revision)

    def test_cancelling_a_blocked_head_preserves_an_already_blocked_successor(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            service, conversation_id = self.prepare_conversation(root, runtime)
            counters = {"msg": 50, "turn": 50, "run": 50}

            def identifier(prefix):
                counters[prefix] += 1
                return f"{prefix}_cancelled_blocked_head_{counters[prefix]}"

            service.id_factory = identifier
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Leave this acceptance unknown too",
                idempotency_key="cancelled-already-blocked-head-key-1",
            )
            service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Cancel this blocked head",
                idempotency_key="cancelled-already-blocked-head-key-2",
            )
            service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Preserve this blocked successor exactly",
                idempotency_key="cancelled-already-blocked-head-key-3",
            )
            repository = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            )
            before = repository.read(conversation_id).queued_turns
            cancelled = service.cancel_conversation_turn(
                conversation_id=conversation_id,
                turn_id=before[0].id,
                expected_revision=before[0].revision,
                expected_message_revision=before[0].message_revision,
            )
            after = repository.read(conversation_id).queued_turns
            connection = connect(root)
            try:
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(first.disposition, "unknown")
        self.assertEqual([turn.state for turn in before], ["blocked", "blocked"])
        self.assertEqual(cancelled.disposition, "cancelled")
        self.assertEqual(cancelled.turn.id, before[0].id)
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0].id, before[1].id)
        self.assertEqual(after[0].state, "blocked")
        self.assertEqual(after[0].blocked_reason, before[1].blocked_reason)
        self.assertEqual(after[0].revision, before[1].revision)

    def test_codex_continue_requires_the_exact_prior_thread(self):
        for observed_status, runtime_reference, expected_reason, reconcile in (
            (RunStatus.FAILED, "runtime-service-ref", "failed", True),
            (RunStatus.COMPLETED, None, "unknown", False),
        ):
            with self.subTest(
                status=observed_status.value,
                runtime_reference=runtime_reference,
            ), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                runtime = FakeRuntime(root)
                self.qualify_codex_capacity(runtime)
                runtime.return_runtime_run_ref = runtime_reference
                service, conversation_id = self.prepare_conversation(root, runtime)
                first = service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Run the first Codex Turn",
                    idempotency_key=(
                        f"codex-continuity-{observed_status.value}-key-1"
                    ),
                )
                service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Do not start a fresh Codex thread",
                    idempotency_key=(
                        f"codex-continuity-{observed_status.value}-key-2"
                    ),
                )
                if reconcile:
                    runtime.observed_status = observed_status
                    report = service.reconcile_run(
                        run_id=first.run.id,
                        owner=f"codex_continuity_{observed_status.value}_owner",
                    )
                    self.assertEqual(report.unavailable, ())
                    self.assertEqual(report.reconciled, (first.run.id,))
                else:
                    self.assertEqual(first.disposition, "unknown")
                repository = ConversationRepository(
                    root,
                    supported_runtime_types=(runtime.runtime_type,),
                )
                blocked = repository.read(conversation_id).queued_turns[0]
                self.assertEqual(blocked.state, "blocked")
                self.assertEqual(blocked.blocked_reason, expected_reason)
                service.id_factory = lambda prefix: f"{prefix}_continuity_guard"

                continued = service.continue_conversation_turn(
                    conversation_id=conversation_id,
                    turn_id=blocked.id,
                    expected_revision=blocked.revision,
                    expected_message_revision=blocked.message_revision,
                )
                after = repository.read(conversation_id).queued_turns[0]

                self.assertEqual(continued.disposition, "blocked")
                self.assertIsNone(continued.run)
                self.assertEqual(after.id, blocked.id)
                self.assertEqual(after.revision, blocked.revision)
                self.assertEqual(len(runtime.calls), 1)

    def test_conversation_steer_targets_exact_run_without_message_or_turn_writes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep this Run steerable",
                idempotency_key="conversation-steer-key-1",
            )
            runtime.observed_status = RunStatus.RUNNING
            service.reconcile_run(
                run_id=submitted.run.id,
                owner="conversation_steer_running_owner",
            )
            connection = connect(root)
            try:
                before = connection.execute(
                    "SELECT (SELECT COUNT(*) FROM mentat_conversation_messages), "
                    "(SELECT COUNT(*) FROM mentat_conversation_turns)"
                ).fetchone()
            finally:
                connection.close()

            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(
                    server,
                    "AGENT_RUNTIME_REGISTRY",
                    service.runtime_registry,
                ),
            ):
                payload, status = server.steer_mentat_conversation(
                    conversation_id,
                    {
                        "run_id": submitted.run.id,
                        "text": "Use the revised priority now",
                    },
                )
                with self.assertRaisesRegex(
                    server.OrchestrationRunActionError,
                    "conversation.steer_stale",
                ):
                    server.steer_mentat_conversation(
                        "conv_another_conversation",
                        {
                            "run_id": submitted.run.id,
                            "text": "Cross the Conversation boundary",
                        },
                    )
            connection = connect(root)
            try:
                after = connection.execute(
                    "SELECT (SELECT COUNT(*) FROM mentat_conversation_messages), "
                    "(SELECT COUNT(*) FROM mentat_conversation_turns)"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(status, 200)
        self.assertEqual(payload["disposition"], "accepted")
        self.assertEqual(len(runtime.steer_calls), 1)
        self.assertEqual(runtime.steer_calls[0][1], "Use the revised priority now")
        self.assertEqual(tuple(before), tuple(after))

    def test_conversation_steer_preserves_ambiguous_runtime_delivery(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep this Run steerable",
                idempotency_key="conversation-steer-partial-key-1",
            )
            runtime.observed_status = RunStatus.RUNNING
            service.reconcile_run(
                run_id=submitted.run.id,
                owner="conversation_steer_partial_owner",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep this successor blocked if delivery is ambiguous",
                idempotency_key="conversation-steer-partial-key-2",
            )

            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(
                    server,
                    "AGENT_RUNTIME_REGISTRY",
                    service.runtime_registry,
                ),
                patch.object(
                    runtime,
                    "send_message",
                    side_effect=AgentRuntimeError("runtime.message_partial"),
                ),
                self.assertRaisesRegex(
                    server.OrchestrationRunActionError,
                    "conversation.steer_partial",
                ),
            ):
                server.steer_mentat_conversation(
                    conversation_id,
                    {
                        "run_id": submitted.run.id,
                        "text": "This guidance may already have landed",
                    },
                )

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                ambiguous = repository.get_run(submitted.run.id)
                blocked = repository.conversation_turn_reservation(queued.turn.id)
                blocked_reason = connection.execute(
                    "SELECT blocked_reason FROM mentat_conversation_turns WHERE id = ?",
                    (queued.turn.id,),
                ).fetchone()[0]
                repository.validate()
            finally:
                connection.close()

            completed_snapshot = self.worker_snapshot(
                submitted,
                status="completed",
                partial=False,
                response="The runtime later reported a completed answer.",
                finalized=True,
            )
            completed_snapshot["updated_at"] = ambiguous.updated_at
            completed_snapshot["completed_at"] = ambiguous.updated_at
            completed_report = save_authoritative_run_summaries(
                root,
                [completed_snapshot],
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                completed = repository.get_run(submitted.run.id)
                still_blocked = repository.conversation_turn_reservation(
                    queued.turn.id
                )
                repository.validate()
            finally:
                connection.close()

        self.assertTrue(ambiguous.partial)
        self.assertEqual(blocked.state, "blocked")
        self.assertEqual(blocked_reason, "partial")
        self.assertEqual(completed.status, "completed")
        self.assertTrue(completed.partial)
        self.assertTrue(completed.terminal_finalized)
        self.assertEqual(completed_report.conversation_continuations, ())
        self.assertEqual(still_blocked.state, "blocked")
        self.assertIsNone(still_blocked.run_id)
        self.assertEqual(len(runtime.calls), 1)

    def test_conversation_steer_requires_declared_agent_permission(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(
                root,
                runtime,
                agent_capabilities=("run.start",),
            )
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep this Run active without steering permission",
                idempotency_key="conversation-steer-permission-key-1",
            )
            runtime.observed_status = RunStatus.RUNNING
            service.reconcile_run(
                run_id=submitted.run.id,
                owner="conversation_steer_permission_owner",
            )

            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(
                    server,
                    "AGENT_RUNTIME_REGISTRY",
                    service.runtime_registry,
                ),
                patch.object(
                    runtime,
                    "capabilities_for_run",
                    return_value=frozenset(
                        {
                            "run.approval_response",
                            "run.message",
                            "run.status",
                            "run.stop",
                        }
                    ),
                ) as live_capabilities,
            ):
                with self.assertRaisesRegex(
                    server.OrchestrationRunActionError,
                    "conversation.steer_unsupported",
                ):
                    server.steer_mentat_conversation(
                        conversation_id,
                        {
                            "run_id": submitted.run.id,
                            "text": "Do not bypass declared permission",
                        },
                    )
                with self.assertRaisesRegex(
                    server.OrchestrationRunActionError,
                    "run.message_unavailable",
                ):
                    server.mentat_run_message_preview_payload(
                        submitted.run.id,
                        "Do not preview an undeclared message action",
                    )
                with self.assertRaisesRegex(
                    server.OrchestrationRunActionError,
                    "run.stop_unavailable",
                ):
                    server.mentat_run_stop_preview_payload(submitted.run.id)
                connection = connect(root)
                try:
                    connection.execute(
                        "UPDATE mentat_runs SET status = 'waiting_for_approval' "
                        "WHERE id = ?",
                        (submitted.run.id,),
                    )
                    connection.commit()
                finally:
                    connection.close()
                with self.assertRaisesRegex(
                    server.OrchestrationRunActionError,
                    "run.response_unavailable",
                ):
                    server.mentat_run_response_request_payload(submitted.run.id)

            live_capabilities.assert_not_called()
            self.assertEqual(runtime.steer_calls, [])

    def test_success_blocks_the_head_when_current_declared_capacity_is_full(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            self.qualify_codex_capacity(runtime)
            runtime.capacity_limit = 2
            service, first_conversation_id = self.prepare_conversation(root, runtime)
            second_conversation_id = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).create(agent_id="agent-service").conversation.id
            counters = {"msg": 0, "turn": 0, "run": 0}

            def next_identifier(prefix):
                counters[prefix] += 1
                return f"{prefix}_continuation_capacity_{counters[prefix]}"

            service.id_factory = next_identifier
            first = service.submit_conversation_turn(
                conversation_id=first_conversation_id,
                text="Complete this first Conversation",
                idempotency_key="conversation-continuation-capacity-key-1",
            )
            service.submit_conversation_turn(
                conversation_id=second_conversation_id,
                text="Keep the second capacity slot active",
                idempotency_key="conversation-continuation-capacity-key-2",
            )
            queued = service.submit_conversation_turn(
                conversation_id=first_conversation_id,
                text="Wait after the limit changes",
                idempotency_key="conversation-continuation-capacity-key-3",
            )
            runtime.capacity_limit = 1
            runtime.observed_status = RunStatus.COMPLETED

            report = service.reconcile_run(
                run_id=first.run.id,
                owner="conversation_capacity_change_owner",
            )
            detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(first_conversation_id)

        self.assertEqual(report.reconciled, (first.run.id,))
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(len(detail.queued_turns), 1)
        self.assertEqual(detail.queued_turns[0].id, queued.turn.id)
        self.assertEqual(detail.queued_turns[0].blocked_reason, "capacity")

    def test_conversation_runtime_rejection_is_durable_and_not_presented_as_accepted(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.rejects = True
            service, conversation_id = self.prepare_conversation(root, runtime)
            result = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Runtime may reject this",
                idempotency_key="conversation-rejected-key-1",
            )
            duplicate = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Runtime may reject this",
                idempotency_key="conversation-rejected-key-1",
            )

        self.assertEqual(result.disposition, "rejected")
        self.assertEqual(result.run.status, "failed")
        self.assertEqual(result.run.dispatch_state, "rejected")
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.disposition, "rejected")
        self.assertEqual(len(runtime.calls), 1)

    def test_conservative_runtime_capacity_accepts_blocked_turn_without_a_run(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            service, first_conversation_id = self.prepare_conversation(root, runtime)
            second_conversation_id = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).create(agent_id="agent-service").conversation.id
            service.submit_conversation_turn(
                conversation_id=first_conversation_id,
                text="Consume conservative capacity",
                idempotency_key="conversation-capacity-key-1",
            )
            blocked = service.submit_conversation_turn(
                conversation_id=second_conversation_id,
                text="Wait for capacity",
                idempotency_key="conversation-capacity-key-2",
            )
            connection = connect(root)
            try:
                counts = connection.execute(
                    "SELECT (SELECT COUNT(*) FROM mentat_conversation_messages WHERE conversation_id = ?), "
                    "(SELECT COUNT(*) FROM mentat_conversation_turns WHERE conversation_id = ?), "
                    "(SELECT COUNT(*) FROM mentat_runs WHERE conversation_id = ?)",
                    (second_conversation_id, second_conversation_id, second_conversation_id),
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(blocked.disposition, "blocked")
        self.assertEqual(blocked.turn.blocked_reason, "capacity")
        self.assertIsNone(blocked.run)
        self.assertEqual(tuple(counts), (1, 1, 0))
        self.assertEqual(len(runtime.calls), 1)

    def test_unqualified_adapter_capacity_above_two_remains_one(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.capacity_limit = 3
            service, first_id = self.prepare_conversation(root, runtime)
            repository = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            )
            second_id = repository.create(agent_id="agent-service").conversation.id
            first = service.submit_conversation_turn(
                conversation_id=first_id,
                text="Consume the only unqualified slot",
                idempotency_key="unqualified-capacity-key-1",
            )
            second = service.submit_conversation_turn(
                conversation_id=second_id,
                text="Do not trust an unqualified higher claim",
                idempotency_key="unqualified-capacity-key-2",
            )

        self.assertEqual(first.disposition, "accepted")
        self.assertEqual(second.disposition, "blocked")
        self.assertEqual(second.turn.blocked_reason, "capacity")
        self.assertEqual(len(runtime.calls), 1)

    def test_qualified_codex_limit_two_admits_two_and_blocks_the_third(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            self.qualify_codex_capacity(runtime)
            runtime.capacity_limit = 2
            service, first_id = self.prepare_conversation(root, runtime)
            repository = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            )
            second_id = repository.create(agent_id="agent-service").conversation.id
            third_id = repository.create(agent_id="agent-service").conversation.id
            counter = {"msg": 10, "turn": 10, "run": 10}

            def identifier(prefix):
                counter[prefix] += 1
                return f"{prefix}_capacity_{counter[prefix]}"

            service.id_factory = identifier
            first = service.submit_conversation_turn(
                conversation_id=first_id,
                text="Run in the first Conversation",
                idempotency_key="adapter-capacity-two-key-1",
            )
            second = service.submit_conversation_turn(
                conversation_id=second_id,
                text="Run in the second Conversation",
                idempotency_key="adapter-capacity-two-key-2",
            )
            third = service.submit_conversation_turn(
                conversation_id=third_id,
                text="Wait in the third Conversation",
                idempotency_key="adapter-capacity-two-key-3",
            )

        self.assertEqual(first.disposition, "accepted")
        self.assertEqual(second.disposition, "accepted")
        self.assertEqual(third.disposition, "blocked")
        self.assertEqual(third.turn.blocked_reason, "capacity")
        self.assertEqual(len(runtime.calls), 2)

    def test_gated_codex_continuation_carries_exact_predecessor_through_retention(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository,
            "TERMINAL_RUN_RETENTION",
            1,
        ):
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            self.qualify_codex_capacity(runtime)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Complete this Codex thread before the gated handoff",
                idempotency_key="conversation-codex-gated-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Continue on the exact prior Codex thread",
                idempotency_key="conversation-codex-gated-key-2",
            )
            newer_terminal = {
                "id": "run_codex_retention_pressure",
                "runtime_type": "hermes",
                "agent_id": "profile-service",
                "agent_name": "Hermes",
                "model": "provider/model",
                "transport_mode": "local",
                "connection_binding_id": "local-default",
                "status": "completed",
                "prompt": "Retention pressure fixture",
                "response": "Done",
                "error": "",
                "events": [],
                "created_at": "2027-01-01T00:00:00+00:00",
                "updated_at": "2027-01-01T00:00:01+00:00",
                "started_at": "2027-01-01T00:00:00+00:00",
                "completed_at": "2027-01-01T00:00:01+00:00",
                "attachments": [],
                "artifacts": [],
            }
            connection = connect(root)
            try:
                RunRepository(connection).sync_summaries([newer_terminal])
            finally:
                connection.close()
            runtime.observed_status = RunStatus.COMPLETED
            service.conversation_continuation_handler = (
                server._dispatch_reserved_agent_console_continuation
            )
            prior_gate = server.AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED
            try:
                with (
                    patch.object(server, "DATA_DIR", root),
                    patch.object(
                        server,
                        "AGENT_RUNTIME_REGISTRY",
                        service.runtime_registry,
                    ),
                    patch.object(
                        server,
                        "_mentat_agent_registry",
                        return_value=service.agent_registry,
                    ),
                    patch.object(
                        server,
                        "agent_console_storage_degraded",
                        return_value=False,
                    ),
                ):
                    server.AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED = True
                    report = service.reconcile_run(
                        run_id=first.run.id,
                        owner="codex_gated_retention_owner",
                    )
            finally:
                server.AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED = prior_gate

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.conversation_turn_reservation(
                    queued.turn.id
                )
                successor = repository.get_run(reservation.run_id)
                retained_source_result = (
                    repository.get_conversation_submission_result(first.turn.id)
                )
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(report.reconciled, (first.run.id,))
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(
            runtime.calls[1][1].continuation_runtime_run_ref,
            "runtime-service-ref",
        )
        self.assertEqual(reservation.state, "accepted")
        self.assertEqual(successor.dispatch_state, "accepted")
        self.assertIsNone(successor.resume_of_run_id)
        self.assertEqual(retained_source_result.id, first.run.id)

    def test_current_conversation_run_prefers_active_status_on_timestamp_tie(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.rejects = True
            service, conversation_id = self.prepare_conversation(root, runtime)
            terminal = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Finish the first Run",
                idempotency_key="conversation-current-terminal-key",
            )
            runtime.rejects = False
            active = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep the second Run active",
                idempotency_key="conversation-current-active-key",
            )
            connection = connect(root)
            try:
                connection.execute(
                    "UPDATE mentat_runs SET updated_at = ? WHERE id IN (?, ?)",
                    (
                        "2027-01-01T00:00:00+00:00",
                        terminal.run.id,
                        active.run.id,
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            current = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).read(conversation_id).current_run

        self.assertEqual(terminal.run.status, "failed")
        self.assertEqual(active.run.status, "starting")
        self.assertIsNotNone(current)
        self.assertEqual(current["id"], active.run.id)

    def test_active_task_dispatch_blocks_conversation_on_the_same_runtime_binding(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            task_service = self.prepare(root, runtime)
            conversation_id = ConversationRepository(
                root,
                supported_runtime_types=("hermes",),
            ).create(agent_id="agent-service").conversation.id
            task_result = task_service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="cross-capacity-task-first",
            )
            conversation_service = OrchestrationService(
                root,
                runtime_registry=task_service.runtime_registry,
                agent_registry=task_service.agent_registry,
                id_factory=lambda prefix: {
                    "msg": "msg_cross_capacity",
                    "turn": "turn_cross_capacity",
                    "run": "run_cross_capacity",
                }[prefix],
            )
            blocked = conversation_service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="This Turn must wait for the Task Run",
                idempotency_key="cross-capacity-conversation-second",
            )

        self.assertEqual(task_result.run.status, "unknown")
        self.assertEqual(blocked.disposition, "blocked")
        self.assertEqual(blocked.turn.blocked_reason, "capacity")
        self.assertEqual(len(runtime.calls), 1)

    def test_active_conversation_blocks_task_dispatch_on_the_same_runtime_binding(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            conversation_service, conversation_id = self.prepare_conversation(
                root,
                runtime,
            )
            conversation_result = conversation_service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Consume the shared runtime capacity",
                idempotency_key="cross-capacity-conversation-first",
            )
            task_identifiers = iter(("dispatch_cross_capacity", "run_cross_task"))
            task_service = OrchestrationService(
                root,
                runtime_registry=conversation_service.runtime_registry,
                agent_registry=conversation_service.agent_registry,
                id_factory=lambda _prefix: next(task_identifiers),
            )
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "dispatch.capacity_unavailable",
            ):
                task_service.dispatch_task(
                    task_id="task-service",
                    expected_revision=1,
                    idempotency_key="cross-capacity-task-second",
                )

        self.assertEqual(conversation_result.run.status, "unknown")
        self.assertEqual(len(runtime.calls), 1)

    def test_provider_mutation_gate_sees_canonical_nextjs_conversation_run(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            service, conversation_id = self.prepare_conversation(root, runtime)
            result = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Keep provider selection stable",
                idempotency_key="conversation-provider-gate-key",
            )
            with patch.object(server, "DATA_DIR", root):
                active, error = server._provider_mutation_active_run(
                    "profile-service",
                    target_only=True,
                )
                other, other_error = server._provider_mutation_active_run(
                    "profile-other",
                    target_only=True,
                )

        self.assertIsNone(error)
        self.assertEqual(active, {"id": result.run.id})
        self.assertIsNone(other_error)
        self.assertIsNone(other)

    def test_runtime_setup_rejection_is_durable_after_claimed_authority(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            readiness_evidence = []

            def readiness_status(*, force=True):
                connection = connect(root)
                try:
                    row = connection.execute(
                        "SELECT t.state, t.attempt_count, r.status, r.dispatch_state "
                        "FROM mentat_conversation_turns AS t "
                        "JOIN mentat_runs AS r ON r.id = t.latest_run_id"
                    ).fetchone()
                    readiness_evidence.append(tuple(row))
                finally:
                    connection.close()
                return "sign_in_required"

            runtime.readiness_status = readiness_status
            result = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Record the rejected sign-in check",
                idempotency_key="conversation-auth-key-1",
            )
            connection = connect(root)
            try:
                counts = connection.execute(
                    "SELECT (SELECT COUNT(*) FROM mentat_conversation_messages), "
                    "(SELECT COUNT(*) FROM mentat_conversation_turns), "
                    "(SELECT COUNT(*) FROM mentat_runs WHERE conversation_id IS NOT NULL)"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(readiness_evidence, [("dispatching", 1, "submitting", "submitting")])
        self.assertEqual(tuple(counts), (1, 1, 1))
        self.assertEqual(result.disposition, "rejected")
        self.assertEqual(result.run.status, "failed")
        self.assertEqual(runtime.calls, [])

    def test_post_reservation_binding_change_returns_canonical_rejected_result(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            original_reserve = RunRepository.reserve_conversation_turn

            def reserve_then_change(repository, *args, **kwargs):
                reservation = original_reserve(repository, *args, **kwargs)
                racing_connection = connect(root)
                try:
                    racing_connection.execute(
                        "UPDATE mentat_agents SET name = 'Changed Agent', "
                        "revision = revision + 1 WHERE id = 'agent-service'"
                    )
                    racing_connection.commit()
                finally:
                    racing_connection.close()
                return reservation

            with patch.object(
                RunRepository,
                "reserve_conversation_turn",
                reserve_then_change,
            ):
                result = service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Reconcile the durable rejection",
                    idempotency_key="conversation-binding-change-key",
                )

        self.assertEqual(result.disposition, "rejected")
        self.assertEqual(result.turn.state, "consumed")
        self.assertEqual(result.turn.attempt_count, 0)
        self.assertEqual(result.run.status, "failed")
        self.assertEqual(result.run.dispatch_state, "rejected")
        self.assertEqual(runtime.calls, [])

    def test_concurrent_conversation_replay_and_competing_key_call_runtime_once(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.submit_entered = threading.Event()
            runtime.submit_release = threading.Event()
            service, conversation_id = self.prepare_conversation(root, runtime)
            first_result = []
            first_error = []

            def first_send():
                try:
                    first_result.append(service.submit_conversation_turn(
                        conversation_id=conversation_id,
                        text="Concurrent Turn",
                        idempotency_key="conversation-concurrent-key-1",
                    ))
                except Exception as exc:  # pragma: no cover - surfaced below
                    first_error.append(exc)

            worker = threading.Thread(target=first_send)
            worker.start()
            self.assertTrue(runtime.submit_entered.wait(timeout=5))
            duplicate = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Concurrent Turn",
                idempotency_key="conversation-concurrent-key-1",
            )
            competing = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Competing Turn",
                idempotency_key="conversation-concurrent-key-2",
            )
            runtime.submit_release.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(first_error, [])
        self.assertEqual(len(first_result), 1)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.disposition, "submitting")
        self.assertEqual(competing.disposition, "pending")
        self.assertIsNone(competing.run)
        self.assertEqual(len(runtime.calls), 1)

    def test_conversation_restart_recovery_distinguishes_unattempted_and_uncertain(self):
        for claimed, expected_status, expected_dispatch in (
            (False, "interrupted", "rejected"),
            (True, "unknown", "unknown"),
        ):
            with self.subTest(claimed=claimed), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                runtime = FakeRuntime(root)
                service, conversation_id = self.prepare_conversation(root, runtime)
                record, binding = service._agent_record_and_binding("agent-service")
                digest = service._binding_digest(record.agent, binding)
                connection = connect(root)
                try:
                    repository = RunRepository(connection)
                    reservation = repository.reserve_conversation_turn(
                        idempotency_key=f"conversation-recovery-key-{claimed}",
                        conversation_id=conversation_id,
                        message_id="msg_recovery",
                        turn_id="turn_recovery",
                        run_id="run_recovery",
                        text="Recover exact state",
                        agent_id=record.agent.id,
                        agent_name=record.agent.name,
                        agent_revision=record.revision,
                        runtime_type=binding.runtime_type,
                        runtime_config_id=binding.id,
                        runtime_config_revision=binding.revision,
                        binding_digest=digest,
                        capabilities=record.agent.capabilities,
                    )
                    if claimed:
                        repository.claim_conversation_turn_attempt(
                            turn_id=reservation.turn_id,
                            expected_binding_digest=digest,
                        )
                finally:
                    connection.close()

                with patch.object(server, "DATA_DIR", root), patch.object(
                    server,
                    "AGENT_RUNTIME_REGISTRY",
                    service.runtime_registry,
                ), patch.object(
                    server,
                    "_mentat_agent_registry",
                    return_value=service.agent_registry,
                ):
                    server.reconcile_orchestration_runs_at_startup()

                connection = connect(root)
                try:
                    repository = RunRepository(connection)
                    repeated = repository.recover_conversation_submissions()
                    run = repository.get_run("run_recovery")
                    turn = connection.execute(
                        "SELECT state, attempt_count FROM mentat_conversation_turns "
                        "WHERE id = 'turn_recovery'"
                    ).fetchone()
                    repository.validate()
                finally:
                    connection.close()

            self.assertEqual(repeated, ())
            self.assertEqual(run.status, expected_status)
            self.assertEqual(run.dispatch_state, expected_dispatch)
            self.assertEqual(turn["state"], "consumed")
            self.assertEqual(turn["attempt_count"], 1 if claimed else 0)
            self.assertEqual(runtime.calls, [])

    def test_restart_recovery_clears_reserved_predecessor_pin_under_retention(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository,
            "TERMINAL_RUN_RETENTION",
            1,
        ):
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Finish before restart recovery",
                idempotency_key="conversation-restart-pin-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Classify this unattempted successor after restart",
                idempotency_key="conversation-restart-pin-key-2",
            )
            report = save_authoritative_run_summaries(
                root,
                [
                    self.worker_snapshot(
                        first,
                        status="completed",
                        partial=False,
                        response="Verified Hermes response before restart",
                    )
                ],
            )

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                before = repository.conversation_turn_reservation(queued.turn.id)
                pinned = repository.get_run(before.run_id)
                recovered = repository.recover_conversation_submissions(
                    now="2028-01-01T00:00:00+00:00",
                )
                after = repository.conversation_turn_reservation(queued.turn.id)
                interrupted = repository.get_run(after.run_id)
                source_result = repository.get_conversation_submission_result(
                    first.turn.id
                )
                with self.assertRaisesRegex(RunRepositoryConflict, "run.not_found"):
                    repository.get_run(first.run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(
            report.conversation_continuations,
            ((first.run.id, queued.turn.id),),
        )
        self.assertEqual(pinned.resume_of_run_id, first.run.id)
        self.assertEqual(recovered, (before.run_id,))
        self.assertEqual(after.state, "rejected")
        self.assertEqual(after.attempt_count, 0)
        self.assertEqual(interrupted.status, "interrupted")
        self.assertEqual(interrupted.dispatch_state, "rejected")
        self.assertTrue(interrupted.partial)
        self.assertTrue(interrupted.terminal_finalized)
        self.assertIsNone(interrupted.resume_of_run_id)
        self.assertEqual(source_result.id, first.run.id)
        self.assertEqual(len(runtime.calls), 1)

    def test_restart_recovery_enforces_retention_across_multiple_successors(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository,
            "TERMINAL_RUN_RETENTION",
            1,
        ):
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            self.qualify_codex_capacity(runtime)
            runtime.capacity_limit = 2
            service, first_conversation_id = self.prepare_conversation(
                root,
                runtime,
            )
            second_conversation_id = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).create(agent_id="agent-service").conversation.id
            counters = {"msg": 0, "turn": 0, "run": 0}

            def identifier(prefix):
                counters[prefix] += 1
                return f"{prefix}_multi_recovery_{counters[prefix]}"

            service.id_factory = identifier
            service.conversation_continuation_handler = lambda _source, _turn: None
            first_sources = (
                service.submit_conversation_turn(
                    conversation_id=first_conversation_id,
                    text="Complete first source before restart",
                    idempotency_key="conversation-multi-recovery-key-1",
                ),
                service.submit_conversation_turn(
                    conversation_id=second_conversation_id,
                    text="Complete second source before restart",
                    idempotency_key="conversation-multi-recovery-key-2",
                ),
            )
            queued = (
                service.submit_conversation_turn(
                    conversation_id=first_conversation_id,
                    text="Recover first reserved successor",
                    idempotency_key="conversation-multi-recovery-key-3",
                ),
                service.submit_conversation_turn(
                    conversation_id=second_conversation_id,
                    text="Recover second reserved successor",
                    idempotency_key="conversation-multi-recovery-key-4",
                ),
            )
            runtime.observed_status = RunStatus.COMPLETED
            for index, source in enumerate(first_sources, start=1):
                report = service.reconcile_run(
                    run_id=source.run.id,
                    owner=f"multi_recovery_owner_{index}",
                )
                self.assertEqual(report.reconciled, (source.run.id,))

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                before = tuple(
                    repository.conversation_turn_reservation(item.turn.id)
                    for item in queued
                )
                pinned = tuple(repository.get_run(item.run_id) for item in before)
                recovered = repository.recover_conversation_submissions(
                    now="2028-01-01T00:00:00+00:00",
                )
                retained_ids = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT id FROM mentat_runs WHERE status = 'interrupted'"
                    )
                }
                results = tuple(
                    repository.get_conversation_submission_result(item.turn.id)
                    for item in queued
                )
                terminal_count = connection.execute(
                    "SELECT COUNT(*) FROM mentat_runs WHERE status IN ("
                    "'completed', 'failed', 'cancelled', 'stopped', 'interrupted')"
                ).fetchone()[0]
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(
            tuple(item.resume_of_run_id for item in pinned),
            tuple(item.run.id for item in first_sources),
        )
        self.assertEqual(set(recovered), {item.run_id for item in before})
        self.assertEqual(len(retained_ids), 1)
        self.assertEqual(terminal_count, 1)
        self.assertEqual(tuple(item.status for item in results), ("interrupted",) * 2)
        self.assertEqual(tuple(item.partial for item in results), (True, True))
        self.assertEqual(len(runtime.calls), 2)

    def test_conversation_restart_marks_accepted_run_without_runtime_reference_unknown(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            record, binding = service._agent_record_and_binding("agent-service")
            digest = service._binding_digest(record.agent, binding)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_conversation_turn(
                    idempotency_key="conversation-accepted-no-ref-key",
                    conversation_id=conversation_id,
                    message_id="msg_accepted_no_ref",
                    turn_id="turn_accepted_no_ref",
                    run_id="run_accepted_no_ref",
                    text="Recover accepted state without a durable runtime reference",
                    agent_id=record.agent.id,
                    agent_name=record.agent.name,
                    agent_revision=record.revision,
                    runtime_type=binding.runtime_type,
                    runtime_config_id=binding.id,
                    runtime_config_revision=binding.revision,
                    binding_digest=digest,
                    capabilities=record.agent.capabilities,
                )
                repository.claim_conversation_turn_attempt(
                    turn_id=reservation.turn_id,
                    expected_binding_digest=digest,
                )
                repository.record_conversation_submission_outcome(
                    turn_id=reservation.turn_id,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.ACCEPTED,
                        run=AgentRun(
                            id=reservation.run_id,
                            task_id=reservation.turn_id,
                            agent_id=record.agent.id,
                            runtime_type=binding.runtime_type,
                            status=RunStatus.RUNNING,
                        ),
                    ),
                )
                recovered = repository.recover_conversation_submissions()
                repeated = repository.recover_conversation_submissions()
                run = repository.get_run(reservation.run_id)
                retained = repository.get_conversation_submission_result(
                    reservation.turn_id
                )
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(recovered, (reservation.run_id,))
        self.assertEqual(repeated, ())
        self.assertEqual(run.status, "unknown")
        self.assertEqual(run.dispatch_state, "unknown")
        self.assertTrue(run.partial)
        self.assertEqual(retained.status, "unknown")

    def test_still_owned_console_worker_atomically_reconciles_unknown_completion(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_runtime_run_ref = None
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Finish after a competing startup recovery",
                idempotency_key="conversation-late-worker-completion-key",
            )
            worker_snapshot = {
                "id": submitted.run.id,
                "runtime_type": "hermes",
                "agent_id": "profile-service",
                "agent_name": "Service Agent",
                "model": "provider/model",
                "transport_mode": "local",
                "connection_binding_id": "local-default",
                "status": "completed",
                "partial": False,
                "prompt": "Finish after a competing startup recovery",
                "response": (
                    "Verified late response. Saved /Users/alice/secret.txt "
                    "and /tmp/private-output.txt"
                ),
                "error": "",
                "events": [],
                "created_at": submitted.run.created_at,
                "updated_at": submitted.run.updated_at,
                "started_at": submitted.run.started_at,
                "completed_at": submitted.run.updated_at,
                "attachments": [],
                "artifacts": [],
                "mentat_agent_id": "agent-service",
                "task_id": submitted.turn.id,
                "_dispatch_id": submitted.turn.id,
            }

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                recovered = repository.recover_conversation_submissions()
                unknown = repository.get_run(submitted.run.id)
                # Reproduce the exact pre-fix partial write observed in the
                # operator database: terminal runtime status landed while the
                # admission state remained unknown.
                connection.execute(
                    "UPDATE mentat_runs SET status = 'completed', "
                    "completed_at = ?, updated_at = ? WHERE id = ?",
                    (
                        submitted.run.updated_at,
                        submitted.run.updated_at,
                        submitted.run.id,
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            save_authoritative_run_summaries(root, [worker_snapshot])
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                completed = repository.get_run(submitted.run.id)
                retained = repository.get_conversation_submission_result(
                    submitted.turn.id
                )
                repository.validate()
            finally:
                connection.close()

            detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)
            worker_snapshot["events"] = [
                {
                    "schema_version": 1,
                    "id": "event_runtime_finalized_late_worker",
                    "run_id": submitted.run.id,
                    "sequence": 1,
                    "cursor": 1,
                    "type": "runtime.finalized",
                    "kind": "runtime.finalized",
                    "timestamp": submitted.run.updated_at,
                    "data": {},
                    "display_text": "Runtime finalized",
                    "message": "Runtime finalized",
                }
            ]
            save_authoritative_run_summaries(root, [worker_snapshot])
            save_authoritative_run_summaries(root, [worker_snapshot])
            replayed_detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                replayed = repository.get_run(submitted.run.id)
                assistant_event_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_agent_events "
                        "WHERE run_id = ? AND event_type = 'message' AND content IS NOT NULL",
                        (submitted.run.id,),
                    ).fetchone()[0]
                )
                finalized_event_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_agent_events "
                        "WHERE run_id = ? AND source_type = 'runtime.finalized'",
                        (submitted.run.id,),
                    ).fetchone()[0]
                )
                repository.validate()
            finally:
                connection.close()

            worker_snapshot["partial"] = True
            connection = connect(root)
            try:
                # Repeat the exact pre-fix terminal/unknown shape while the
                # worker carries a separate partial condition.
                connection.execute(
                    "UPDATE mentat_runs SET dispatch_state = 'unknown', "
                    "partial = 1 WHERE id = ?",
                    (submitted.run.id,),
                )
                connection.commit()
            finally:
                connection.close()
            save_authoritative_run_summaries(root, [worker_snapshot])
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                partial_completed = repository.get_run(submitted.run.id)
                partial_retained = repository.get_conversation_submission_result(
                    submitted.turn.id
                )
                repository.validate()
            finally:
                connection.close()

            malformed_snapshot = {**worker_snapshot, "partial": 1}
            with self.assertRaisesRegex(
                RunRepositoryValidationError, "run.partial_invalid"
            ):
                save_authoritative_run_summaries(root, [malformed_snapshot])
            missing_status = dict(worker_snapshot)
            missing_status.pop("status")
            with self.assertRaisesRegex(
                RunRepositoryValidationError, "run.status_invalid"
            ):
                save_authoritative_run_summaries(root, [missing_status])
            missing_runtime = dict(worker_snapshot)
            missing_runtime.pop("runtime_type")
            with self.assertRaisesRegex(
                RunRepositoryConflict, "run.console_authority_conflict"
            ):
                save_authoritative_run_summaries(root, [missing_runtime])

        self.assertEqual(recovered, (submitted.run.id,))
        self.assertEqual(unknown.status, "unknown")
        self.assertEqual(unknown.dispatch_state, "unknown")
        self.assertTrue(unknown.partial)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.dispatch_state, "accepted")
        self.assertFalse(completed.partial)
        self.assertFalse(completed.terminal_finalized)
        self.assertEqual(detail.current_run["status"], "finalizing")
        self.assertEqual(retained.status, "completed")
        self.assertFalse(retained.partial)
        self.assertEqual([message.role for message in detail.messages], ["user"])
        self.assertTrue(replayed.terminal_finalized)
        self.assertEqual(replayed_detail.current_run["status"], "completed")
        self.assertEqual(
            [message.role for message in replayed_detail.messages],
            ["user", "assistant"],
        )
        self.assertEqual(
            replayed_detail.messages[1].content["parts"][0]["text"],
            "Verified late response. Saved [redacted-path] and [redacted-path]",
        )
        self.assertNotIn(
            "/Users/alice",
            replayed_detail.messages[1].content["parts"][0]["text"],
        )
        self.assertNotIn(
            "/tmp/private-output.txt",
            replayed_detail.messages[1].content["parts"][0]["text"],
        )
        self.assertEqual(replayed_detail.messages[1].run_id, submitted.run.id)
        self.assertEqual(replayed.status, "completed")
        self.assertEqual(replayed.dispatch_state, "accepted")
        self.assertEqual(assistant_event_count, 1)
        self.assertEqual(finalized_event_count, 1)
        self.assertEqual(len(replayed_detail.messages), 2)
        self.assertEqual(replayed_detail.messages[1].run_id, submitted.run.id)
        self.assertEqual(partial_completed.dispatch_state, "accepted")
        self.assertTrue(partial_completed.partial)
        self.assertEqual(partial_retained.status, "completed")
        self.assertTrue(partial_retained.partial)

    def test_worker_completion_atomically_reserves_and_executes_one_fifo_successor(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Finish the active Hermes request",
                idempotency_key="conversation-worker-continuation-key-1",
            )
            snapshot = self.worker_snapshot(
                first,
                status="completed",
                partial=False,
                response="Verified Hermes response",
                finalized=False,
            )

            prefinal_report = save_authoritative_run_summaries(root, [snapshot])
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Run this exact FIFO successor",
                idempotency_key="conversation-worker-continuation-key-2",
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                prefinal_source = repository.get_run(first.run.id)
                prefinal_turn = repository.conversation_turn_reservation(
                    queued.turn.id
                )
                repository.validate()
            finally:
                connection.close()
            prefinal_detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)
            prefinal_activity = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).activity()

            snapshot = self.worker_snapshot(
                first,
                status="completed",
                partial=False,
                response="Verified Hermes response",
                finalized=True,
            )
            report = save_authoritative_run_summaries(root, [snapshot])
            replay = save_authoritative_run_summaries(root, [snapshot])
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reserved = repository.conversation_turn_reservation(queued.turn.id)
                source = repository.get_run(first.run.id)
                repository.validate()
            finally:
                connection.close()

            continued = service.execute_reserved_conversation_turn(queued.turn.id)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                successor = repository.get_run(reserved.run_id)
                repository.validate()
            finally:
                connection.close()
            detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)

        self.assertEqual(
            report.conversation_continuations,
            ((first.run.id, queued.turn.id),),
        )
        self.assertEqual(prefinal_report.conversation_continuations, ())
        self.assertEqual(prefinal_source.status, "completed")
        self.assertFalse(prefinal_source.terminal_finalized)
        self.assertEqual(prefinal_turn.state, "pending")
        self.assertIsNone(prefinal_turn.run_id)
        self.assertEqual(prefinal_detail.current_run["status"], "finalizing")
        self.assertEqual(len(prefinal_activity), 1)
        self.assertEqual(prefinal_activity[0]["state"], "working")
        self.assertEqual(
            prefinal_activity[0]["conversations"][0]["run_status"],
            "finalizing",
        )
        self.assertFalse(prefinal_activity[0]["attention"])
        self.assertEqual(
            [message.role for message in prefinal_detail.messages],
            ["user", "user"],
        )
        self.assertEqual(replay.conversation_continuations, ())
        self.assertEqual(source.status, "completed")
        self.assertEqual(source.dispatch_state, "accepted")
        self.assertEqual(reserved.state, "reserved")
        self.assertEqual(reserved.attempt_count, 0)
        self.assertTrue(str(reserved.run_id).startswith("run_auto_"))
        self.assertEqual(continued.disposition, "accepted")
        self.assertEqual(successor.dispatch_state, "accepted")
        self.assertEqual(successor.turn_id, queued.turn.id)
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(detail.queued_turns, ())
        self.assertEqual(
            [message.role for message in detail.messages],
            ["user", "user", "assistant"],
        )

    def test_prefinal_hermes_conversation_run_is_pinned_until_finalized(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository,
            "TERMINAL_RUN_RETENTION",
            1,
        ):
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Remain durable through the finalization boundary",
                idempotency_key="conversation-prefinal-retention-key-1",
            )
            prefinal_snapshot = self.worker_snapshot(
                submitted,
                status="completed",
                partial=False,
                response="A response still awaiting runtime.finalized.",
                finalized=False,
            )
            save_authoritative_run_summaries(root, [prefinal_snapshot])

            newer_terminal = {
                "id": "run_newer_terminal",
                "runtime_type": "hermes",
                "agent_id": "profile-service",
                "agent_name": "Hermes",
                "model": "provider/model",
                "transport_mode": "local",
                "connection_binding_id": "local-default",
                "status": "completed",
                "prompt": "Retention pressure fixture",
                "response": "Done",
                "error": "",
                "events": [],
                "created_at": "2027-01-01T00:00:00+00:00",
                "updated_at": "2027-01-01T00:00:01+00:00",
                "started_at": "2027-01-01T00:00:00+00:00",
                "completed_at": "2027-01-01T00:00:01+00:00",
                "attachments": [],
                "artifacts": [],
            }
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                repository.sync_summaries([newer_terminal])
                pinned = repository.get_run(submitted.run.id)
                repository.validate()
            finally:
                connection.close()

            finalized_snapshot = self.worker_snapshot(
                submitted,
                status="completed",
                partial=False,
                response="The exact finalized response.",
                finalized=True,
            )
            final_report = save_authoritative_run_summaries(
                root,
                [finalized_snapshot],
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                with self.assertRaisesRegex(RunRepositoryConflict, "run.not_found"):
                    repository.get_run(submitted.run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(pinned.status, "completed")
        self.assertFalse(pinned.terminal_finalized)
        self.assertIn(submitted.run.id, final_report.removed_run_ids)

    def test_prelaunch_hermes_terminal_paths_finalize_and_block_fifo_head(self):
        cases = (
            ("cancelling", "local-default", "stopped", "stopped"),
            ("queued", "changed-binding", "failed", "failed"),
        )
        for initial_status, selected_binding, expected_status, reason in cases:
            with self.subTest(initial_status=initial_status), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                runtime = FakeRuntime(root)
                service, conversation_id = self.prepare_conversation(root, runtime)
                submitted = service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Reach the exact pre-launch terminal path",
                    idempotency_key=f"conversation-prelaunch-{reason}-key-1",
                )
                queued = service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Block this FIFO successor at finalization",
                    idempotency_key=f"conversation-prelaunch-{reason}-key-2",
                )
                worker_run = self.worker_snapshot(
                    submitted,
                    status="completed",
                    partial=False,
                    finalized=False,
                )
                worker_run.update(
                    {
                        "status": initial_status,
                        "response": "",
                        "error": "",
                        "completed_at": None,
                        "events": [],
                        "event_cursor": 0,
                        "new_session_state": "pending",
                        "session_id": None,
                    }
                )
                transport = SimpleNamespace(
                    mode="local",
                    binding=SimpleNamespace(binding_id=selected_binding),
                )
                with (
                    patch.object(server, "DATA_DIR", root),
                    patch.object(server, "AGENT_CONSOLE_HISTORY_LOADED", True),
                    patch.object(
                        server,
                        "AGENT_CONSOLE_HISTORY_DATA_DIR",
                        Path(os.path.abspath(os.fspath(root))),
                    ),
                    patch.object(
                        server,
                        "AGENT_CONSOLE_PERSISTENCE_DEGRADED",
                        False,
                    ),
                    patch.object(
                        server,
                        "AGENT_CONSOLE_PERSISTENCE_DEGRADED_DATA_DIR",
                        None,
                    ),
                    patch.object(
                        server,
                        "AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED",
                        False,
                    ),
                    patch.object(server, "cleanup_run_export_directory"),
                    patch.object(server, "cleanup_run_input_directory"),
                    patch.dict(
                        server.AGENT_CONSOLE_RUNS,
                        {submitted.run.id: worker_run},
                        clear=True,
                    ),
                ):
                    server.run_hermes_agent(submitted.run.id, transport)

                connection = connect(root)
                try:
                    repository = RunRepository(connection)
                    source = repository.get_run(submitted.run.id)
                    blocked = repository.conversation_turn_reservation(
                        queued.turn.id
                    )
                    blocked_reason = connection.execute(
                        "SELECT blocked_reason FROM mentat_conversation_turns "
                        "WHERE id = ?",
                        (queued.turn.id,),
                    ).fetchone()[0]
                    repository.validate()
                finally:
                    connection.close()

                self.assertEqual(worker_run["events"][-1]["type"], "runtime.finalized")
                self.assertEqual(source.status, expected_status)
                self.assertTrue(source.terminal_finalized)
                self.assertFalse(source.partial)
                self.assertEqual(blocked.state, "blocked")
                self.assertEqual(blocked_reason, reason)
                self.assertIsNone(blocked.run_id)
                self.assertEqual(len(runtime.calls), 1)

    def test_worker_completion_before_acceptance_replays_and_executes_fifo_successor(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_runtime_run_ref = None
            runtime.observed_status = RunStatus.COMPLETED
            runtime.submit_entered = threading.Event()
            runtime.submit_release = threading.Event()
            service, conversation_id = self.prepare_conversation(root, runtime)
            original_submit = runtime.submit_task
            suppressed_reports = []

            def complete_before_acceptance(task, context):
                outcome = original_submit(task, context)
                snapshot = preacceptance_worker_snapshot(
                    root,
                    task,
                    context,
                    partial=False,
                    finalized=True,
                )
                suppressed_reports.append(
                    save_authoritative_run_summaries(root, [snapshot])
                )
                suppressed_reports.append(
                    save_authoritative_run_summaries(root, [snapshot])
                )
                return outcome

            def completed_events(run_id, after_sequence=0, *, context=None):
                self.assertEqual(run_id, context.mentat_run_id)
                events = (
                    AgentEvent(
                        id=f"runtime_answer_{run_id}",
                        run_id=run_id,
                        sequence=1,
                        type=AgentEventType.MESSAGE,
                        occurred_at="2026-08-18T13:00:00+00:00",
                        summary="Assistant answer completed",
                        content=f"Verified answer for {context.task_id}",
                    ),
                    AgentEvent(
                        id=f"runtime_finalized_{run_id}",
                        run_id=run_id,
                        sequence=2,
                        type=AgentEventType.RUN_COMPLETED,
                        occurred_at="2026-08-18T13:00:01+00:00",
                        summary="Run completed",
                    ),
                )
                return tuple(
                    event for event in events if event.sequence > after_sequence
                )

            runtime.submit_task = complete_before_acceptance
            runtime.stream_events = completed_events
            first_results = []
            first_errors = []

            def submit_first():
                try:
                    first_results.append(
                        service.submit_conversation_turn(
                            conversation_id=conversation_id,
                            text="Finish before acceptance returns",
                            idempotency_key="conversation-fast-worker-key-1",
                        )
                    )
                except Exception as exc:  # pragma: no cover - surfaced below
                    first_errors.append(exc)

            worker = threading.Thread(target=submit_first)
            worker.start()
            self.assertTrue(runtime.submit_entered.wait(timeout=5))
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Run the queued successor after the fast worker",
                idempotency_key="conversation-fast-worker-key-2",
            )
            self.assertEqual(queued.turn.state, "pending")
            self.assertEqual(len(runtime.calls), 1)
            runtime.submit_release.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(first_errors, [])

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                first_run = repository.get_run(first_results[0].run.id)
                successor_reservation = repository.conversation_turn_reservation(
                    queued.turn.id
                )
                successor = repository.get_run(successor_reservation.run_id)
                repository.validate()
            finally:
                connection.close()
            detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)

        self.assertEqual(len(suppressed_reports), 4)
        self.assertTrue(
            all(report.conversation_continuations == () for report in suppressed_reports)
        )
        self.assertEqual(first_run.status, "completed")
        self.assertEqual(first_run.dispatch_state, "accepted")
        self.assertEqual(successor_reservation.state, "accepted")
        self.assertEqual(successor_reservation.attempt_count, 1)
        self.assertEqual(successor.status, "completed")
        self.assertEqual(successor.dispatch_state, "accepted")
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(len(runtime.status_queries), 2)
        self.assertEqual(detail.queued_turns, ())
        self.assertEqual(
            [message.role for message in detail.messages],
            ["user", "user", "assistant", "assistant"],
        )
        self.assertEqual(
            [message.run_id for message in detail.messages if message.role == "assistant"],
            [first_run.id, successor.id],
        )

    def test_preacceptance_partial_completion_blocks_fifo_successor(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_runtime_run_ref = None
            runtime.observed_status = RunStatus.COMPLETED
            runtime.submit_entered = threading.Event()
            runtime.submit_release = threading.Event()
            service, conversation_id = self.prepare_conversation(root, runtime)
            original_submit = runtime.submit_task
            suppressed_reports = []

            def complete_partially_before_acceptance(task, context):
                outcome = original_submit(task, context)
                snapshot = preacceptance_worker_snapshot(
                    root,
                    task,
                    context,
                    partial=True,
                    finalized=True,
                )
                suppressed_reports.append(
                    save_authoritative_run_summaries(root, [snapshot])
                )
                suppressed_reports.append(
                    save_authoritative_run_summaries(root, [snapshot])
                )
                return outcome

            def completed_events(run_id, after_sequence=0, *, context=None):
                event = AgentEvent(
                    id=f"runtime_finalized_{run_id}",
                    run_id=run_id,
                    sequence=1,
                    type=AgentEventType.RUN_COMPLETED,
                    occurred_at="2026-08-18T13:00:00+00:00",
                    summary="Run completed",
                )
                return (event,) if after_sequence < 1 else ()

            runtime.submit_task = complete_partially_before_acceptance
            runtime.stream_events = completed_events
            first_results = []
            first_errors = []

            def submit_first():
                try:
                    first_results.append(
                        service.submit_conversation_turn(
                            conversation_id=conversation_id,
                            text="Complete while steering is ambiguous",
                            idempotency_key="conversation-fast-partial-key-1",
                        )
                    )
                except Exception as exc:  # pragma: no cover - surfaced below
                    first_errors.append(exc)

            worker = threading.Thread(target=submit_first)
            worker.start()
            self.assertTrue(runtime.submit_entered.wait(timeout=5))
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Do not auto-run after ambiguous steering",
                idempotency_key="conversation-fast-partial-key-2",
            )
            runtime.submit_release.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(first_errors, [])

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                source = repository.get_run(first_results[0].run.id)
                blocked = repository.conversation_turn_reservation(queued.turn.id)
                blocked_reason = connection.execute(
                    "SELECT blocked_reason FROM mentat_conversation_turns WHERE id = ?",
                    (queued.turn.id,),
                ).fetchone()[0]
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(len(suppressed_reports), 2)
        self.assertTrue(
            all(report.conversation_continuations == () for report in suppressed_reports)
        )
        self.assertEqual(source.status, "completed")
        self.assertEqual(source.dispatch_state, "accepted")
        self.assertTrue(source.partial)
        self.assertEqual(blocked.state, "blocked")
        self.assertEqual(blocked_reason, "partial")
        self.assertIsNone(blocked.run_id)
        self.assertEqual(blocked.attempt_count, 0)
        self.assertEqual(len(runtime.calls), 1)

    def test_preacceptance_completion_waits_for_finalized_event_before_fifo(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_runtime_run_ref = None
            runtime.observed_status = RunStatus.COMPLETED
            runtime.submit_entered = threading.Event()
            runtime.submit_release = threading.Event()
            service, conversation_id = self.prepare_conversation(root, runtime)
            original_submit = runtime.submit_task
            prefinal_snapshots = []

            def complete_before_finalization(task, context):
                outcome = original_submit(task, context)
                snapshot = preacceptance_worker_snapshot(
                    root,
                    task,
                    context,
                    partial=False,
                    finalized=False,
                )
                prefinal_snapshots.append((task, context, snapshot))
                save_authoritative_run_summaries(root, [snapshot])
                return outcome

            runtime.submit_task = complete_before_finalization
            runtime.stream_events = lambda *_args, **_kwargs: ()
            first_results = []
            first_errors = []

            def submit_first():
                try:
                    first_results.append(
                        service.submit_conversation_turn(
                            conversation_id=conversation_id,
                            text="Finish response before artifact collection",
                            idempotency_key="conversation-prefinal-key-1",
                        )
                    )
                except Exception as exc:  # pragma: no cover - surfaced below
                    first_errors.append(exc)

            worker = threading.Thread(target=submit_first)
            worker.start()
            self.assertTrue(runtime.submit_entered.wait(timeout=5))
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Wait until source finalization",
                idempotency_key="conversation-prefinal-key-2",
            )
            runtime.submit_release.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(first_errors, [])

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                before_finalizer = repository.get_run(first_results[0].run.id)
                still_queued = repository.conversation_turn_reservation(
                    queued.turn.id
                )
                repository.validate()
            finally:
                connection.close()
            before_detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)

            first_task, first_context, _snapshot = prefinal_snapshots[0]
            finalized_snapshot = preacceptance_worker_snapshot(
                root,
                first_task,
                first_context,
                partial=False,
                finalized=True,
            )
            report = save_authoritative_run_summaries(root, [finalized_snapshot])
            continued = service.execute_reserved_conversation_turn(queued.turn.id)

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                after_finalizer = repository.get_run(first_results[0].run.id)
                successor = repository.get_run(continued.run.id)
                repository.validate()
            finally:
                connection.close()
            after_detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)

        self.assertEqual(before_finalizer.status, "starting")
        self.assertEqual(before_finalizer.dispatch_state, "accepted")
        self.assertEqual(still_queued.state, "pending")
        self.assertIsNone(still_queued.run_id)
        self.assertEqual(len(runtime.calls), 2)
        self.assertEqual(
            report.conversation_continuations,
            ((after_finalizer.id, queued.turn.id),),
        )
        self.assertEqual(after_finalizer.status, "completed")
        self.assertEqual(successor.dispatch_state, "accepted")
        self.assertEqual(
            [message.role for message in before_detail.messages],
            ["user", "user"],
        )
        self.assertEqual(
            [message.role for message in after_detail.messages],
            ["user", "user", "assistant"],
        )

    def test_shutdown_gate_leaves_fast_worker_successor_durably_unattempted(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_runtime_run_ref = None
            runtime.observed_status = RunStatus.COMPLETED
            runtime.submit_entered = threading.Event()
            runtime.submit_release = threading.Event()
            service, conversation_id = self.prepare_conversation(root, runtime)
            original_submit = runtime.submit_task
            handler_entered = threading.Event()

            def complete_before_acceptance(task, context):
                outcome = original_submit(task, context)
                snapshot = preacceptance_worker_snapshot(
                    root,
                    task,
                    context,
                    partial=False,
                    finalized=True,
                )
                save_authoritative_run_summaries(root, [snapshot])
                save_authoritative_run_summaries(root, [snapshot])
                return outcome

            def finalized_events(run_id, after_sequence=0, *, context=None):
                event = AgentEvent(
                    id=f"runtime_finalized_{run_id}",
                    run_id=run_id,
                    sequence=1,
                    type=AgentEventType.RUN_COMPLETED,
                    occurred_at="2026-08-18T13:00:00+00:00",
                    summary="Run completed",
                )
                return (event,) if after_sequence < 1 else ()

            def gated_handoff(source_run_id, turn_id):
                handler_entered.set()
                server._dispatch_reserved_agent_console_continuation(
                    source_run_id,
                    turn_id,
                )

            runtime.submit_task = complete_before_acceptance
            runtime.stream_events = finalized_events
            service.conversation_continuation_handler = gated_handoff
            first_results = []
            first_errors = []

            def submit_first():
                try:
                    first_results.append(
                        service.submit_conversation_turn(
                            conversation_id=conversation_id,
                            text="Complete immediately before shutdown",
                            idempotency_key="conversation-shutdown-gate-key-1",
                        )
                    )
                except Exception as exc:  # pragma: no cover - surfaced below
                    first_errors.append(exc)

            prior_gate = server.AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED
            try:
                with patch.object(server, "DATA_DIR", root), patch.object(
                    server,
                    "AGENT_RUNTIME_REGISTRY",
                    service.runtime_registry,
                ), patch.object(
                    server,
                    "_mentat_agent_registry",
                    return_value=service.agent_registry,
                ):
                    server.AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED = True
                    worker = threading.Thread(target=submit_first)
                    worker.start()
                    self.assertTrue(runtime.submit_entered.wait(timeout=5))
                    queued = service.submit_conversation_turn(
                        conversation_id=conversation_id,
                        text="Remain reserved if shutdown wins",
                        idempotency_key="conversation-shutdown-gate-key-2",
                    )
                    with server.AGENT_CONSOLE_CONTINUATION_DRAIN_LOCK:
                        runtime.submit_release.set()
                        self.assertTrue(handler_entered.wait(timeout=5))
                        # This is the exact state transition performed by
                        # stop_agent_console_processes while it owns the gate.
                        server.AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED = False
                    worker.join(timeout=5)
                    self.assertFalse(worker.is_alive())
            finally:
                runtime.submit_release.set()
                server.AGENT_CONSOLE_CONTINUATION_DRAIN_ENABLED = prior_gate

            self.assertEqual(first_errors, [])
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                source = repository.get_run(first_results[0].run.id)
                reservation = repository.conversation_turn_reservation(
                    queued.turn.id
                )
                successor = repository.get_run(reservation.run_id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(source.status, "completed")
        self.assertEqual(source.dispatch_state, "accepted")
        self.assertEqual(reservation.state, "reserved")
        self.assertEqual(reservation.attempt_count, 0)
        self.assertEqual(successor.status, "reserved")
        self.assertEqual(successor.dispatch_state, "reserved")
        self.assertEqual(len(runtime.calls), 1)

    def test_worker_reserved_successor_terminalizes_when_agent_binding_disappears(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository,
            "TERMINAL_RUN_RETENTION",
            1,
        ):
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Finish before the binding disappears",
                idempotency_key="conversation-worker-missing-binding-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Fail this reserved successor explicitly",
                idempotency_key="conversation-worker-missing-binding-key-2",
            )
            report = save_authoritative_run_summaries(
                root,
                [
                    self.worker_snapshot(
                        first,
                        status="completed",
                        partial=False,
                        response="Verified Hermes response",
                    )
                ],
            )

            with patch.object(
                service,
                "_agent_record_and_binding",
                side_effect=OrchestrationServiceError(
                    "conversation.agent_not_found"
                ),
            ):
                rejected = service.execute_reserved_conversation_turn(
                    queued.turn.id
                )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.conversation_turn_reservation(
                    queued.turn.id
                )
                failed = repository.get_run(reservation.run_id)
                with self.assertRaisesRegex(RunRepositoryConflict, "run.not_found"):
                    repository.get_run(first.run.id)
                turn_row = connection.execute(
                    "SELECT state, attempt_count FROM mentat_conversation_turns "
                    "WHERE id = ?",
                    (queued.turn.id,),
                ).fetchone()
                repository.validate()
            finally:
                connection.close()
            detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)

        self.assertEqual(
            report.conversation_continuations,
            ((first.run.id, queued.turn.id),),
        )
        self.assertEqual(rejected.disposition, "rejected")
        self.assertEqual(reservation.state, "rejected")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.dispatch_state, "rejected")
        self.assertIsNone(failed.resume_of_run_id)
        self.assertEqual(tuple(turn_row), ("consumed", 0))
        self.assertEqual(detail.queued_turns, ())
        self.assertEqual(len(runtime.calls), 1)

    def test_worker_unsafe_terminal_snapshots_block_the_fifo_head(self):
        for status, partial, expected_status, reason in (
            ("failed", False, "failed", "failed"),
            ("cancelled", False, "stopped", "stopped"),
            ("completed", True, "completed", "partial"),
        ):
            with self.subTest(status=status, partial=partial), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                runtime = FakeRuntime(root)
                service, conversation_id = self.prepare_conversation(root, runtime)
                first = service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Run the active Hermes request",
                    idempotency_key=f"conversation-worker-{reason}-key-1",
                )
                queued = service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Keep this exact FIFO head safe",
                    idempotency_key=f"conversation-worker-{reason}-key-2",
                )
                report = save_authoritative_run_summaries(
                    root,
                    [
                        self.worker_snapshot(
                            first,
                            status=status,
                            partial=partial,
                            response=(
                                "A partial completion must pause the queue"
                                if status == "completed"
                                else ""
                            ),
                        )
                    ],
                )
                detail = ConversationRepository(
                    root,
                    supported_runtime_types=(runtime.runtime_type,),
                ).read(conversation_id)
                connection = connect(root)
                try:
                    repository = RunRepository(connection)
                    source = repository.get_run(first.run.id)
                    repository.validate()
                finally:
                    connection.close()

            self.assertEqual(report.conversation_continuations, ())
            self.assertEqual(source.status, expected_status)
            self.assertEqual(len(detail.queued_turns), 1)
            self.assertEqual(detail.queued_turns[0].id, queued.turn.id)
            self.assertEqual(detail.queued_turns[0].state, "blocked")
            self.assertEqual(detail.queued_turns[0].blocked_reason, reason)
            self.assertEqual(len(runtime.calls), 1)

    def test_late_unknown_worker_completion_never_auto_submits_the_fifo_head(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_runtime_run_ref = None
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Recover this ambiguous Hermes request",
                idempotency_key="conversation-worker-unknown-key-1",
            )
            queued = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Do not retry this FIFO head automatically",
                idempotency_key="conversation-worker-unknown-key-2",
            )
            connection = connect(root)
            try:
                RunRepository(connection).recover_conversation_submissions()
            finally:
                connection.close()

            report = save_authoritative_run_summaries(
                root,
                [
                    self.worker_snapshot(
                        first,
                        status="completed",
                        partial=False,
                        response="Verified late Hermes response",
                    )
                ],
            )
            detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                source = repository.get_run(first.run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(report.conversation_continuations, ())
        self.assertEqual(source.status, "completed")
        self.assertEqual(source.dispatch_state, "accepted")
        self.assertEqual(len(detail.queued_turns), 1)
        self.assertEqual(detail.queued_turns[0].id, queued.turn.id)
        self.assertEqual(detail.queued_turns[0].state, "blocked")
        self.assertEqual(detail.queued_turns[0].blocked_reason, "unknown")
        self.assertEqual(len(runtime.calls), 1)

    def test_still_owned_console_worker_reconciles_empty_completed_response(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_runtime_run_ref = None
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Complete without response text",
                idempotency_key="conversation-empty-late-completion-key",
            )
            worker_snapshot = {
                "id": submitted.run.id,
                "runtime_type": "hermes",
                "agent_id": "profile-service",
                "agent_name": "Service Agent",
                "model": "provider/model",
                "transport_mode": "local",
                "connection_binding_id": "local-default",
                "status": "completed",
                "partial": False,
                "prompt": "Complete without response text",
                "response": "",
                "error": "",
                "events": [],
                "created_at": submitted.run.created_at,
                "updated_at": submitted.run.updated_at,
                "started_at": submitted.run.started_at,
                "completed_at": submitted.run.updated_at,
                "attachments": [],
                "artifacts": [],
                "mentat_agent_id": "agent-service",
                "task_id": submitted.turn.id,
                "_dispatch_id": submitted.turn.id,
            }
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                repository.recover_conversation_submissions()
                connection.execute(
                    "UPDATE mentat_runs SET status = 'completed', "
                    "completed_at = ?, updated_at = ? WHERE id = ?",
                    (
                        submitted.run.updated_at,
                        submitted.run.updated_at,
                        submitted.run.id,
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            save_authoritative_run_summaries(root, [worker_snapshot])
            detail = ConversationRepository(
                root,
                supported_runtime_types=(runtime.runtime_type,),
            ).read(conversation_id)
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                completed = repository.get_run(submitted.run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(completed.status, "completed")
        self.assertEqual(completed.dispatch_state, "accepted")
        self.assertFalse(completed.partial)
        self.assertEqual([message.role for message in detail.messages], ["user"])

    def test_unknown_console_worker_snapshot_preserves_fail_closed_authority(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_runtime_run_ref = None
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Remain unknown without stronger runtime evidence",
                idempotency_key="conversation-unknown-worker-noop-key",
            )
            snapshot = {
                "id": submitted.run.id,
                "runtime_type": "hermes",
                "agent_id": "profile-service",
                "agent_name": "Service Agent",
                "model": "provider/model",
                "transport_mode": "local",
                "connection_binding_id": "local-default",
                "status": "unknown",
                "partial": False,
                "prompt": "Remain unknown without stronger runtime evidence",
                "response": "",
                "error": "",
                "events": [],
                "created_at": submitted.run.created_at,
                "updated_at": submitted.run.updated_at,
                "started_at": submitted.run.started_at,
                "completed_at": None,
                "attachments": [],
                "artifacts": [],
                "mentat_agent_id": "agent-service",
                "task_id": submitted.turn.id,
                "_dispatch_id": submitted.turn.id,
            }
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                repository.recover_conversation_submissions()
                before = tuple(
                    connection.execute(
                        "SELECT status, dispatch_state, partial, details_json, "
                        "updated_at, last_event_sequence, state_revision "
                        "FROM mentat_runs WHERE id = ?",
                        (submitted.run.id,),
                    ).fetchone()
                )
                before_event_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_agent_events WHERE run_id = ?",
                        (submitted.run.id,),
                    ).fetchone()[0]
                )
                before_result = repository.get_conversation_submission_result(
                    submitted.turn.id
                )
            finally:
                connection.close()

            save_authoritative_run_summaries(root, [snapshot])
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                after = tuple(
                    connection.execute(
                        "SELECT status, dispatch_state, partial, details_json, "
                        "updated_at, last_event_sequence, state_revision "
                        "FROM mentat_runs WHERE id = ?",
                        (submitted.run.id,),
                    ).fetchone()
                )
                after_event_count = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_agent_events WHERE run_id = ?",
                        (submitted.run.id,),
                    ).fetchone()[0]
                )
                after_result = repository.get_conversation_submission_result(
                    submitted.turn.id
                )
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(before, after)
        self.assertEqual(before_event_count, after_event_count)
        self.assertEqual(before_result, after_result)

    def test_conversation_restart_reconciles_accepted_durable_runtime_reference(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service, conversation_id = self.prepare_conversation(root, runtime)
            submitted = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Reattach this accepted Conversation Run after restart",
                idempotency_key="conversation-restart-reattach-key",
            )
            runtime.observed_status = RunStatus.COMPLETED

            connection = connect(root)
            try:
                recovered = RunRepository(
                    connection
                ).recover_conversation_submissions()
            finally:
                connection.close()
            report = service.reconcile_runs(
                owner="conversation_restart_reconciler"
            )
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                stored = repository.get_run(submitted.run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(recovered, ())
        self.assertEqual(report.reconciled, (submitted.run.id,))
        self.assertEqual(stored.status, "completed")
        self.assertEqual(stored.dispatch_state, "accepted")
        self.assertEqual(runtime.status_queries, ["runtime-service-ref"])

    def test_dispatch_supports_canonical_wide_task_identifiers(self):
        for task_id in ("task@service", "t" * 160):
            with self.subTest(task_id=task_id), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                runtime = FakeRuntime(root)
                service = self.prepare(root, runtime, task_id=task_id)
                result = service.dispatch_task(
                    task_id=task_id,
                    expected_revision=1,
                    idempotency_key=f"wide-task-id-{hashlib.sha256(task_id.encode()).hexdigest()}",
                )

                self.assertEqual(result.run.task_id, task_id)

    def test_dispatch_reports_stable_missing_and_malformed_task_codes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            with self.assertRaisesRegex(
                OrchestrationServiceError, "dispatch.task_not_found"
            ):
                service.dispatch_task(
                    task_id="task-missing",
                    expected_revision=1,
                    idempotency_key="service-missing-task-key",
                )
            with self.assertRaisesRegex(
                OrchestrationServiceError, "dispatch.task_id_invalid"
            ):
                service.dispatch_task(
                    task_id="bad task id",
                    expected_revision=1,
                    idempotency_key="service-malformed-task-key",
                )
                self.assertEqual(runtime.calls[0][0].id, task_id)
                self.assertEqual(runtime.calls[0][1].task_id, task_id)

    def test_identical_retry_returns_existing_run_without_second_invocation(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)

            first = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-request-key-2",
            )
            duplicate = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-request-key-2",
            )

        self.assertFalse(first.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.run.id, first.run.id)
        self.assertEqual(len(runtime.calls), 1)

    def test_exact_retry_survives_task_revision_drift(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            first = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-request-key-revision-drift",
            )
            connection = connect(root)
            try:
                connection.execute(
                    "UPDATE mentat_tasks SET revision = 2 WHERE id = 'task-service'"
                )
                connection.commit()
            finally:
                connection.close()

            duplicate = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-request-key-revision-drift",
            )

        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.run.id, first.run.id)
        self.assertEqual(len(runtime.calls), 1)

    def test_reservation_retry_rechecks_durable_key_before_changed_task(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            first = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-reserve-race-key",
            )
            connection = connect(root)
            try:
                connection.execute(
                    "UPDATE mentat_tasks SET revision = 2 WHERE id = 'task-service'"
                )
                connection.commit()
            finally:
                connection.close()

            reservation, task, agent, binding, selected_runtime = service._reserve(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-reserve-race-key",
            )

        self.assertTrue(reservation.duplicate)
        self.assertEqual(reservation.run_id, first.run.id)
        self.assertIsNone(task)
        self.assertIsNone(agent)
        self.assertIsNone(binding)
        self.assertIsNone(selected_runtime)
        self.assertEqual(len(runtime.calls), 1)

    def test_new_revision_reports_bounded_conflict_while_unknown_run_is_active(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            service = self.prepare(root, runtime)
            first = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-request-key-active-revision-one",
            )
            connection = connect(root)
            try:
                connection.execute(
                    "UPDATE mentat_tasks SET revision = 2 WHERE id = 'task-service'"
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaisesRegex(
                OrchestrationServiceError, "dispatch.task_active"
            ):
                service.dispatch_task(
                    task_id="task-service",
                    expected_revision=2,
                    idempotency_key="service-request-key-active-revision-two",
                )

        self.assertEqual(first.run.status, "unknown")
        self.assertEqual(len(runtime.calls), 1)

    def test_concurrent_duplicate_and_competing_dispatches_invoke_runtime_once(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.submit_entered = threading.Event()
            runtime.submit_release = threading.Event()
            service = self.prepare(root, runtime)
            first_result = []
            first_error = []

            def first_dispatch():
                try:
                    first_result.append(
                        service.dispatch_task(
                            task_id="task-service",
                            expected_revision=1,
                            idempotency_key="concurrent-request-key-1",
                        )
                    )
                except Exception as exc:  # pragma: no cover - surfaced below
                    first_error.append(exc)

            worker = threading.Thread(target=first_dispatch)
            worker.start()
            self.assertTrue(runtime.submit_entered.wait(timeout=5))
            duplicate = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="concurrent-request-key-1",
            )
            with self.assertRaisesRegex(
                OrchestrationServiceError, "dispatch.task_revision_consumed"
            ):
                service.dispatch_task(
                    task_id="task-service",
                    expected_revision=1,
                    idempotency_key="concurrent-request-key-2",
                )
            runtime.submit_release.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertEqual(first_error, [])
        self.assertEqual(len(first_result), 1)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(len(runtime.calls), 1)

    def test_worker_completion_before_acceptance_record_does_not_regress_run(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.complete_before_return = True
            service = self.prepare(root, runtime)

            result = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="worker-before-outcome-key",
            )
            connection = connect(root)
            try:
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(result.run.status, "completed")
        self.assertEqual(result.run.dispatch_state, "accepted")

    def test_identity_mismatched_acceptance_reports_and_records_unknown(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.return_identity_mismatch = True
            service = self.prepare(root, runtime)

            result = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="identity-mismatch-outcome-key",
            )

        self.assertEqual(result.disposition, "unknown")
        self.assertEqual(result.run.status, "unknown")
        self.assertEqual(result.run.dispatch_state, "unknown")

    def test_task_change_between_reservation_and_claim_is_durably_rejected(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            original_claim = service._claim_after_binding_revalidation

            def mutate_then_claim(reservation, agent, binding):
                connection = connect(root)
                try:
                    repository = TaskRepository(connection)
                    snapshot = repository.get("task-service")
                    changed = dict(snapshot.document)
                    changed["title"] = "Changed before claim"
                    changed["updated_at"] = "2026-08-18T12:01:00+00:00"
                    repository.replace(changed, expected_revision=snapshot.revision)
                finally:
                    connection.close()
                return original_claim(reservation, agent, binding)

            with patch.object(
                service,
                "_claim_after_binding_revalidation",
                side_effect=mutate_then_claim,
            ), self.assertRaisesRegex(
                OrchestrationServiceError, "dispatch.task_changed"
            ) as raised:
                service.dispatch_task(
                    task_id="task-service",
                    expected_revision=1,
                    idempotency_key="task-change-before-claim-key",
                )

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                rejected = repository.get_run("run_service_1")
                state = connection.execute(
                    "SELECT state, attempt_count FROM mentat_dispatch_reservations "
                    "WHERE run_id = 'run_service_1'"
                ).fetchone()
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(runtime.calls, [])
        self.assertIsNotNone(raised.exception.run)
        self.assertEqual(rejected.status, "failed")
        self.assertEqual(rejected.dispatch_state, "rejected")
        self.assertEqual((state["state"], state["attempt_count"]), ("rejected", 0))

    def test_adapter_exception_is_durable_unknown_and_never_retried(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            service = self.prepare(root, runtime)

            first = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-request-key-3",
            )
            duplicate = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="service-request-key-3",
            )
            connection = connect(root)
            try:
                events, _reset, _cursor = RunRepository(connection).list_events(first.run.id)
            finally:
                connection.close()

        self.assertEqual(first.run.status, "unknown")
        self.assertTrue(first.run.partial)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(events[-1].type.value, "submission.unknown")

    def test_accepted_outcome_persistence_failure_becomes_durable_unknown(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            original = RunRepository.record_submission_outcome
            recorded_dispositions = []

            def reject_first_outcome(
                repository,
                *,
                dispatch_id,
                outcome,
                now=None,
            ):
                recorded_dispositions.append(outcome.disposition)
                if len(recorded_dispositions) == 1:
                    raise RunRepositoryValidationError("event.invalid")
                return original(
                    repository,
                    dispatch_id=dispatch_id,
                    outcome=outcome,
                    now=now,
                )

            with patch.object(
                RunRepository,
                "record_submission_outcome",
                new=reject_first_outcome,
            ):
                result = service.dispatch_task(
                    task_id="task-service",
                    expected_revision=1,
                    idempotency_key="accepted-persistence-failure-key",
                )

            connection = connect(root)
            try:
                repository = RunRepository(connection)
                events, _reset, _cursor = repository.list_events(result.run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(
            recorded_dispositions,
            [SubmissionDisposition.ACCEPTED, SubmissionDisposition.UNKNOWN],
        )
        self.assertEqual(result.disposition, "unknown")
        self.assertEqual(result.run.status, "unknown")
        self.assertEqual(result.run.dispatch_state, "unknown")
        self.assertTrue(result.run.partial)
        self.assertEqual(events[-1].type, AgentEventType.SUBMISSION_UNKNOWN)

    def test_public_dispatch_run_and_event_apis_are_cursor_based_and_private(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            self.prepare(root, runtime)
            registry = AgentRuntimeRegistry((runtime,))
            with patch.object(server, "DATA_DIR", root), patch.object(
                server, "AGENT_RUNTIME_REGISTRY", registry
            ):
                dispatched, status = server.dispatch_orchestration_task(
                    "task-service",
                    {
                        "expected_revision": 1,
                        "idempotency_key": "public-api-request-key",
                    },
                )
                listed, list_status = server.orchestration_runs_payload("limit=1")
                maximum_page, maximum_page_status = server.orchestration_runs_payload(
                    "limit=100"
                )
                detailed, detail_status = server.orchestration_run_payload(
                    dispatched["run"]["id"]
                )
                events, event_status = server.orchestration_run_events_payload(
                    dispatched["run"]["id"], "after=0"
                )

        self.assertEqual(status, 202)
        self.assertEqual((list_status, detail_status, event_status), (200, 200, 200))
        self.assertEqual(maximum_page_status, 200)
        self.assertEqual(maximum_page["runs"][0]["id"], dispatched["run"]["id"])
        self.assertEqual(listed["runs"][0]["id"], dispatched["run"]["id"])
        self.assertEqual(detailed["run"]["task_revision"], 1)
        self.assertEqual(events["next_cursor"], 2)
        serialized = json.dumps([dispatched, listed, detailed, events])
        for private_value in (
            "profile-service",
            "config-service",
            "runtime-service-ref",
            "runtime_binding_digest",
        ):
            self.assertNotIn(private_value, serialized)

    def test_public_run_api_rejects_invalid_cursors_and_unknown_run(self):
        invalid_page, page_status = server.orchestration_runs_payload("cursor=%2Fbad")
        invalid_event, event_status = server.orchestration_run_events_payload(
            "run_missing", "after=-1"
        )
        self.assertEqual(page_status, 400)
        self.assertEqual(event_status, 400)
        self.assertNotIn("/bad", repr(invalid_page))
        self.assertIn("invalid", invalid_event["error"].lower())

    def test_public_run_apis_fail_closed_on_event_window_loss(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            dispatched = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="public-gap-request-key",
            )
            connection = connect(root)
            try:
                connection.execute(
                    "DELETE FROM mentat_agent_events WHERE run_id = ? AND sequence = 1",
                    (dispatched.run.id,),
                )
                connection.commit()
            finally:
                connection.close()
            with patch.object(server, "DATA_DIR", root):
                listed, list_status = server.orchestration_runs_payload("limit=10")
                detailed, detail_status = server.orchestration_run_payload(
                    dispatched.run.id
                )

        self.assertEqual(list_status, 503)
        self.assertEqual(detail_status, 503)
        self.assertIn("unavailable", listed["error"].lower())
        self.assertIn("unavailable", detailed["error"].lower())

    def test_public_dispatch_rejects_malformed_idempotency_key_as_bad_request(self):
        payload, status = server.dispatch_orchestration_task(
            "task-service",
            {"expected_revision": 1, "idempotency_key": "short"},
        )

        self.assertEqual(status, 400)
        self.assertIn("invalid", payload["error"].lower())

    def test_dispatch_translates_database_setup_failure(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service = self.prepare(root, FakeRuntime(root))
            with patch.object(
                orchestration_service,
                "connect",
                side_effect=MentatDatabaseError("database unavailable"),
            ):
                with self.assertRaisesRegex(
                    OrchestrationServiceError, "dispatch.unavailable"
                ):
                    service.dispatch_task(
                        task_id="task-service",
                        expected_revision=1,
                        idempotency_key="database-setup-failure-key",
                    )

    def test_post_submission_database_failure_is_bounded_without_retry(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            real_connect = orchestration_service.connect
            outcome_failure_injected = False

            def fail_outcome_connection(data_dir):
                nonlocal outcome_failure_injected
                if runtime.calls and not outcome_failure_injected:
                    outcome_failure_injected = True
                    raise MentatDatabaseError("outcome database unavailable")
                return real_connect(data_dir)

            with patch.object(
                orchestration_service, "connect", side_effect=fail_outcome_connection
            ):
                with self.assertRaisesRegex(
                    OrchestrationServiceError, "dispatch.unavailable"
                ):
                    service.dispatch_task(
                        task_id="task-service",
                        expected_revision=1,
                        idempotency_key="post-submission-db-failure",
                    )
            connection = connect(root)
            try:
                status = connection.execute(
                    "SELECT status FROM mentat_runs"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(status, "submitting")

    def test_public_run_reads_translate_database_setup_failure(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            server, "DATA_DIR", Path(tmpdir)
        ), patch.object(
            server,
            "connect_mentat_database",
            side_effect=MentatDatabaseError("database unavailable"),
        ):
            list_payload, list_status = server.orchestration_runs_payload()
            run_payload, run_status = server.orchestration_run_payload("run_missing")
            event_payload, event_status = server.orchestration_run_events_payload(
                "run_missing"
            )

        self.assertEqual((list_status, run_status, event_status), (503, 503, 503))
        self.assertIn("unavailable", list_payload["error"])
        self.assertIn("unavailable", run_payload["error"])
        self.assertIn("unavailable", event_payload["error"])

    def test_task_deletion_preview_translates_database_setup_failure(self):
        task = task_fixture()
        with patch.object(server, "read_task_snapshot", return_value=[task]), patch.object(
            server,
            "connect_mentat_database",
            side_effect=MentatDatabaseError("database unavailable"),
        ):
            payload, status = server.preview_task_deletion(task["id"])

        self.assertEqual(status, 503)
        self.assertIn("could not be verified", payload["error"])

    def test_reconciliation_uses_cas_lease_and_never_resubmits(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            dispatched = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="reconcile-request-key",
            )
            runtime.observed_status = RunStatus.COMPLETED
            runtime_event_id = "e" * 128
            runtime.events = (AgentEvent(
                id=runtime_event_id,
                run_id=dispatched.run.id,
                sequence=1,
                type=AgentEventType.MESSAGE,
                occurred_at="2026-08-18T13:00:00+00:00",
                summary="Maximum-width runtime event identity",
            ),)

            report = service.reconcile_runs(owner="reconciler_one")
            second = service.reconcile_runs(owner="reconciler_two")
            connection = connect(root)
            try:
                run = RunRepository(connection).get_run(dispatched.run.id)
                events, _reset, _cursor = RunRepository(connection).list_events(run.id)
                source_key = connection.execute(
                    "SELECT source_key FROM mentat_agent_events WHERE source_key = ?",
                    ("runtime:" + runtime_event_id,),
                ).fetchone()[0]
                RunRepository(connection).validate()
            finally:
                connection.close()
            unit = capture_private_console_unit(root)

        self.assertEqual(report.reconciled, (dispatched.run.id,))
        self.assertEqual(second.leased, 0)
        self.assertEqual(run.status, "completed")
        self.assertEqual(len(runtime.calls), 1)
        self.assertEqual(
            [event.type.value for event in events[-2:]],
            ["message", "run.completed"],
        )
        self.assertEqual(runtime.status_queries, ["runtime-service-ref"])
        self.assertEqual(runtime.event_queries, [("runtime-service-ref", 0)])
        self.assertEqual(source_key, "runtime:" + runtime_event_id)
        self.assertEqual(unit.run_count, 1)

    def test_targeted_reconciliation_leases_only_the_requested_run(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            dispatched = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="targeted-reconciliation-key",
            )
            missing = service.reconcile_run(
                run_id="run_not_the_requested_run",
                owner="targeted_reconciler",
            )
            runtime.observed_status = RunStatus.STOPPED
            report = service.reconcile_run(
                run_id=dispatched.run.id,
                owner="targeted_reconciler",
            )
            connection = connect(root)
            try:
                stored = RunRepository(connection).get_run(dispatched.run.id)
                RunRepository(connection).validate()
            finally:
                connection.close()

        self.assertEqual(missing.leased, 0)
        self.assertEqual(report.reconciled, (dispatched.run.id,))
        self.assertEqual(stored.status, "stopped")
        self.assertEqual(runtime.status_queries, ["runtime-service-ref"])

    def test_startup_reconciliation_reads_durable_runtime_reference(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            dispatched = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="startup-reconciliation-key",
            )
            runtime.observed_status = RunStatus.COMPLETED

            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "AGENT_RUNTIME_REGISTRY",
                service.runtime_registry,
            ), patch.object(
                server,
                "_mentat_agent_registry",
                return_value=service.agent_registry,
            ):
                server.reconcile_orchestration_runs_at_startup()

            connection = connect(root)
            try:
                run = RunRepository(connection).get_run(dispatched.run.id)
            finally:
                connection.close()

        self.assertEqual(run.status, "completed")
        self.assertEqual(runtime.status_queries, ["runtime-service-ref"])
        self.assertEqual(len(runtime.calls), 1)

    def test_startup_reconciliation_uses_shutdown_gated_continuation_handler(self):
        reconciler = Mock()
        reconciler.reconcile_runs.return_value = SimpleNamespace(
            leased=0,
            reconciled=(),
            unavailable=(),
        )
        with patch.object(
            server,
            "_mentat_agent_registry",
            return_value=object(),
        ), patch.object(
            server,
            "OrchestrationService",
            return_value=reconciler,
        ) as service_factory:
            server.reconcile_orchestration_runtime_references_at_startup()

        reconciler.reconcile_runs.assert_called_once()
        self.assertIs(
            service_factory.call_args.kwargs[
                "conversation_continuation_handler"
            ],
            server._dispatch_reserved_agent_console_continuation,
        )

    def test_unknown_reconciliation_updates_reservation_and_remains_valid(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            service = self.prepare(root, runtime)
            dispatched = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="unknown-reconcile-key",
            )
            runtime.raises = False
            runtime.observed_status = RunStatus.RUNNING

            report = service.reconcile_runs(owner="unknown_reconciler")
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                run = repository.get_run(dispatched.run.id)
                reservation = connection.execute(
                    "SELECT state FROM mentat_dispatch_reservations WHERE run_id = ?",
                    (run.id,),
                ).fetchone()
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(report.reconciled, (dispatched.run.id,))
        self.assertEqual(run.status, "running")
        self.assertEqual(run.dispatch_state, "accepted")
        self.assertEqual(str(reservation["state"]), "accepted")
        self.assertEqual(len(runtime.calls), 1)

    def test_reconciliation_rejects_status_regression(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            dispatched = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="status-regression-key",
            )
            runtime.observed_status = RunStatus.RUNNING
            first = service.reconcile_runs(owner="forward_reconciler")
            runtime.observed_status = RunStatus.STARTING
            second = service.reconcile_runs(owner="stale_reconciler")
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                run = repository.get_run(dispatched.run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(first.reconciled, (run.id,))
        self.assertEqual(second.unavailable, (run.id,))
        self.assertEqual(run.status, "running")

    def test_runtime_cursor_survives_retention_and_redacted_retries(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            run_repository, "EVENT_COUNT_RETENTION", 1
        ):
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            dispatched = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="runtime-cursor-key",
            )
            connection = connect(root)
            try:
                committed_dispatch = RunRepository(connection).get_run(
                    dispatched.run.id
                )
            finally:
                connection.close()
            self.assertEqual(dispatched.run, committed_dispatch)
            runtime.observed_status = RunStatus.RUNNING
            runtime.events = (
                AgentEvent(
                    id="runtime-secret-1",
                    run_id=dispatched.run.id,
                    sequence=1,
                    type=AgentEventType.MESSAGE,
                    occurred_at="2026-08-18T13:00:00+00:00",
                    summary="token=abcdefghijklmnop",
                ),
                AgentEvent(
                    id="runtime-progress-2",
                    run_id=dispatched.run.id,
                    sequence=2,
                    type=AgentEventType.MESSAGE,
                    occurred_at="2026-08-18T13:00:01+00:00",
                    summary="Still working",
                ),
            )

            first = service.reconcile_runs(owner="cursor_reconciler_one")
            second = service.reconcile_runs(owner="cursor_reconciler_two")
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                run = repository.get_run(dispatched.run.id)
                events, reset, _cursor = repository.list_events(run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(first.reconciled, (run.id,))
        self.assertEqual(second.reconciled, (run.id,))
        self.assertEqual(run.runtime_event_cursor, 2)
        self.assertEqual(runtime.event_queries[-1], ("runtime-service-ref", 2))
        self.assertEqual(len(events), 1)
        self.assertTrue(reset)
        self.assertNotIn("abcdefghijklmnop", json.dumps(events, default=str))

    def test_duplicate_runtime_event_cannot_jump_the_durable_cursor(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            service = self.prepare(root, runtime)
            dispatched = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="runtime-duplicate-cursor-key",
            )
            runtime.observed_status = RunStatus.RUNNING
            original = AgentEvent(
                id="runtime-stable-event",
                run_id=dispatched.run.id,
                sequence=1,
                type=AgentEventType.MESSAGE,
                occurred_at="2026-08-18T13:00:00+00:00",
                summary="Stable event",
            )
            runtime.events = (original,)
            first = service.reconcile_runs(owner="cursor_original")
            runtime.events = (
                AgentEvent(
                    id=original.id,
                    run_id=original.run_id,
                    sequence=100,
                    type=original.type,
                    occurred_at=original.occurred_at,
                    summary=original.summary,
                ),
            )
            conflict = service.reconcile_runs(owner="cursor_conflict")
            connection = connect(root)
            try:
                after_conflict = RunRepository(connection).get_run(dispatched.run.id)
            finally:
                connection.close()
            runtime.events = (
                AgentEvent(
                    id="runtime-next-event",
                    run_id=dispatched.run.id,
                    sequence=2,
                    type=AgentEventType.MESSAGE,
                    occurred_at="2026-08-18T13:00:01+00:00",
                    summary="Next event",
                ),
            )
            final = service.reconcile_runs(owner="cursor_next")
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                stored = repository.get_run(dispatched.run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(first.reconciled, (stored.id,))
        self.assertEqual(conflict.unavailable, (stored.id,))
        self.assertEqual(after_conflict.runtime_event_cursor, 1)
        self.assertEqual(final.reconciled, (stored.id,))
        self.assertEqual(stored.runtime_event_cursor, 2)

    def test_reconciliation_pages_more_than_one_thousand_runtime_events(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root)
            runtime.honor_after_sequence = True
            service = self.prepare(root, runtime)
            dispatched = service.dispatch_task(
                task_id="task-service",
                expected_revision=1,
                idempotency_key="runtime-pagination-key",
            )
            runtime.observed_status = RunStatus.COMPLETED
            runtime.events = tuple(
                AgentEvent(
                    id=f"runtime-page-{sequence}",
                    run_id=dispatched.run.id,
                    sequence=sequence,
                    type=AgentEventType.MESSAGE,
                    occurred_at=f"2026-08-18T13:{(sequence // 60) % 60:02d}:{sequence % 60:02d}+00:00",
                    summary=f"Update {sequence}",
                )
                for sequence in range(1, 1002)
            )

            first = service.reconcile_runs(owner="page_reconciler_one")
            connection = connect(root)
            try:
                interim = RunRepository(connection).get_run(dispatched.run.id)
            finally:
                connection.close()
            second = service.reconcile_runs(owner="page_reconciler_two")
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                run = repository.get_run(dispatched.run.id)
                repository.validate()
            finally:
                connection.close()

        self.assertEqual(first.reconciled, (run.id,))
        self.assertEqual(second.reconciled, (run.id,))
        self.assertNotIn(interim.status, {"completed", "failed", "stopped", "interrupted"})
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.runtime_event_cursor, 1002)
        self.assertEqual(runtime.event_queries[-1], ("runtime-service-ref", 1000))


if __name__ == "__main__":
    unittest.main()
