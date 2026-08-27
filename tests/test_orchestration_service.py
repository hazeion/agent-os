from __future__ import annotations

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

import server
import run_repository
import orchestration_service
from agent_registry import AgentRegistry
from agent_runtime import (
    AgentEvent,
    AgentEventType,
    AgentRun,
    AgentRuntimeRegistry,
    RunStatus,
    SubmissionDisposition,
    SubmissionOutcome,
)
from mentat_db import MentatDatabaseError, connect
from mentat import local_bridge
from orchestration_service import OrchestrationService, OrchestrationServiceError
from conversation_repository import ConversationRepository
from private_state import history_path
from private_console_unit import capture_private_console_unit
from run_repository import (
    RunRepository,
    RunRepositoryConflict,
    RunRepositoryValidationError,
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


class FakeRuntime:
    runtime_type = "hermes"
    capabilities = frozenset({"run.start"})

    def __init__(self, root: Path, *, raises: bool = False):
        self.root = root
        self.raises = raises
        self.calls = []
        self.status_queries = []
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
        return SubmissionOutcome(
            SubmissionDisposition.ACCEPTED,
            run=AgentRun(
                id=context.mentat_run_id,
                task_id=task.id,
                agent_id="agent-mismatch" if self.return_identity_mismatch else context.agent_id,
                runtime_type=self.runtime_type,
                status=RunStatus.STARTING,
            ),
            runtime_run_ref="runtime-service-ref",
            execution_identity={
                "model": "test-model",
                "provider": "test-provider",
                "reasoning_effort": "medium",
                "verification": "runtime_response",
            },
        )

    def get_status(self, run_id, *, context=None):
        task, submission_context, _state, _attempts = self.calls[-1]
        expected = context.runtime_run_ref or context.mentat_run_id
        if run_id != expected:
            raise AssertionError("runtime-owned Run reference was not used")
        self.status_queries.append(run_id)
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
        if self.events is not None:
            return tuple(
                event
                for event in self.events
                if not self.honor_after_sequence or event.sequence > after_sequence
            )
        return (
            AgentEvent(
                id="runtime_event_progress",
                run_id=context.mentat_run_id,
                sequence=1,
                type=AgentEventType.MESSAGE,
                occurred_at="2026-08-18T13:00:00+00:00",
                summary="Runtime progress observed",
            ),
        )


class OrchestrationServiceTests(unittest.TestCase):
    def prepare(
        self, root: Path, runtime: FakeRuntime, *, task_id: str = "task-service"
    ) -> OrchestrationService:
        task = task_fixture()
        task["id"] = task_id
        source = root / "tasks.json"
        source.write_text(json.dumps([task], sort_keys=True) + "\n", encoding="utf-8")
        source.chmod(0o600)
        ensure_run_sqlite_authority(root, history_path(root))
        registry = AgentRegistry(root, supported_runtime_types=("hermes",))
        registry.create_agent(
            agent_id="agent-service",
            name="Service Agent",
            runtime_config_id="config-service",
            runtime_type="hermes",
            runtime_agent_ref="profile-service",
            capabilities=("run.start",),
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
    ) -> tuple[OrchestrationService, str]:
        task_service = self.prepare(root, runtime)
        conversation = ConversationRepository(
            root,
            supported_runtime_types=("hermes",),
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

    def test_conversation_unknown_blocks_a_second_turn_without_partial_rows(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runtime = FakeRuntime(root, raises=True)
            service, conversation_id = self.prepare_conversation(root, runtime)
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Ambiguous request",
                idempotency_key="conversation-request-key-3",
            )
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.active_run",
            ):
                service.submit_conversation_turn(
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
        self.assertEqual(tuple(counts), (1, 1, 1))
        self.assertEqual(len(runtime.calls), 1)

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

    def test_conservative_runtime_capacity_rejects_another_conversation_before_writes(self):
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
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.capacity_unavailable",
            ):
                service.submit_conversation_turn(
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

        self.assertEqual(tuple(counts), (0, 0, 0))
        self.assertEqual(len(runtime.calls), 1)

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
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.capacity_unavailable",
            ):
                conversation_service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="This Turn must wait for the Task Run",
                    idempotency_key="cross-capacity-conversation-second",
                )

        self.assertEqual(task_result.run.status, "unknown")
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
            with self.assertRaisesRegex(
                OrchestrationServiceError,
                "conversation.active_run",
            ):
                service.submit_conversation_turn(
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
            calls = 0

            def fail_outcome_connection(data_dir):
                nonlocal calls
                calls += 1
                if calls == 4:
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
        self.assertEqual(run.runtime_event_cursor, 1001)
        self.assertEqual(runtime.event_queries[-1], ("runtime-service-ref", 1000))


if __name__ == "__main__":
    unittest.main()
