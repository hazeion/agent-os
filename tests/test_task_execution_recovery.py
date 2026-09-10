from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_runtime import AgentRun, RunStatus, SubmissionDisposition, SubmissionOutcome
from mentat_db import connect
from private_state import history_path
from run_repository import RunRepository, RunRepositoryConflict, RunRepositoryValidationError, runtime_binding_digest
import server
from task_repository import TaskRepository
from task_delegation_receipts import DelegationActionReceiptRepository
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from tests.test_run_repository import task_fixture, timestamp


class TaskExecutionRecoveryTests(unittest.TestCase):
    @contextmanager
    def fixture(self, status=RunStatus.FAILED):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            task = {**task_fixture(), "source": "dashboard", "workflow_stage": "planned", "planning_state": "planned"}
            source = root / "tasks.json"
            source.write_text(json.dumps([task]), encoding="utf-8")
            source.chmod(0o600)
            ensure_run_sqlite_authority(root, history_path(root))
            digest = runtime_binding_digest(agent_id="agent-main", runtime_type="codex", runtime_config_id="default", runtime_agent_ref="default", capabilities=("run.start",))
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="recovery-original-key-0001", dispatch_id="dispatch_recovery_original",
                    run_id="run_recovery_original", task=task, task_revision=1, agent_id="agent-main",
                    runtime_type="codex", runtime_config_id="default", binding_digest=digest,
                    capabilities=("run.start",), planning_execution=True, now=timestamp(),
                )
                repository.claim_dispatch_attempt(dispatch_id=reservation.dispatch_id, expected_binding_digest=digest, now=timestamp(1))
                repository.record_submission_outcome(
                    dispatch_id=reservation.dispatch_id,
                    outcome=SubmissionOutcome(SubmissionDisposition.ACCEPTED, run=AgentRun(
                        id=reservation.run_id, task_id=task["id"], agent_id="agent-main", runtime_type="codex", status=status,
                    ), runtime_run_ref="private-runtime-reference"), now=timestamp(2),
                )
                yield root, connection, repository, task, digest
            finally:
                connection.close()

    def request(self, repository, task_id, **changes):
        candidate = repository.task_execution_recovery(task_id)
        current = TaskRepository(repository.connection).get(task_id)
        return {
            "task_id": task_id, "expected_revision": current.revision, "action": "request_changes",
            "note": "Updated the local CLI; plan another attempt.", "idempotency_key": "operator-recovery-key-0001",
            "recovery_run_id": candidate["run_id"], "expected_run_revision": candidate["run_revision"],
            "now": timestamp(5), **changes,
        }

    def test_failed_recovery_retains_evidence_replays_and_requires_separate_run_once(self):
        with self.fixture() as (_root, connection, repository, task, digest):
            request = self.request(repository, task["id"])
            before_run = repository.get_run(request["recovery_run_id"])
            before_events = repository.list_events(before_run.id)
            result = repository.review_task_execution(**request)
            replay = repository.review_task_execution(**request)
            planned = TaskRepository(connection).get(task["id"])
            self.assertFalse(result.duplicate)
            self.assertTrue(replay.duplicate)
            self.assertEqual(planned.document["workflow_stage"], "planned")
            self.assertEqual(repository.get_run(before_run.id), before_run)
            self.assertEqual(repository.list_events(before_run.id), before_events)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_task_execution_reviews").fetchone()[0], 1)
            self.assertEqual(repository.task_execution_attempts(task["id"])[0]["state"], "changes_requested")
            self.assertIsNone(repository.task_execution_recovery(task["id"]))
            public = server._planning_execution_public(planned.document, repository.task_execution_attempts(task["id"]), {})
            self.assertTrue(public["execution"]["available"])
            second = repository.reserve_dispatch(
                idempotency_key="recovery-second-key-0001", dispatch_id="dispatch_recovery_second", run_id="run_recovery_second",
                task=planned.document, task_revision=planned.revision, agent_id="agent-main", runtime_type="codex",
                runtime_config_id="default", binding_digest=digest, capabilities=("run.start",), planning_execution=True, now=timestamp(6),
            )
            self.assertNotEqual(second.run_id, before_run.id)
            self.assertEqual(repository.get_run(before_run.id), before_run)
            repository.validate()

    def test_recovery_requires_exact_task_run_and_request_and_never_accepts_failure(self):
        with self.fixture() as (_root, connection, repository, task, _digest):
            request = self.request(repository, task["id"])
            for changes in (
                {"expected_revision": request["expected_revision"] + 1},
                {"expected_run_revision": request["expected_run_revision"] + 1},
                {"recovery_run_id": "run_unrelated"},
                {"action": "accept", "note": None},
                {"expected_run_revision": True},
                {"recovery_run_id": None},
                {"note": ""},
            ):
                with self.subTest(changes=changes), self.assertRaises((RunRepositoryConflict, RunRepositoryValidationError)):
                    repository.review_task_execution(**{**request, **changes})
            repository.review_task_execution(**request)
            with self.assertRaisesRegex(RunRepositoryConflict, "idempotency_conflict"):
                repository.review_task_execution(**{**request, "note": "Changed receipt intent."})
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_task_execution_reviews").fetchone()[0], 1)

    def test_recovery_uses_current_edited_task_and_preserves_operator_changes(self):
        with self.fixture() as (_root, connection, repository, task, _digest):
            stale = self.request(repository, task["id"])
            current = TaskRepository(connection).get(task["id"])
            changed = {**current.document, "title": "Revised instructions", "workflow_stage": "planned", "planning_state": "planned", "status": "todo", "updated_at": timestamp(3)}
            TaskRepository(connection).replace(changed, expected_revision=current.revision)
            with self.assertRaisesRegex(RunRepositoryConflict, "task_changed"):
                repository.review_task_execution(**stale)
            repository.review_task_execution(**self.request(repository, task["id"]))
            self.assertEqual(TaskRepository(connection).get(task["id"]).document["title"], "Revised instructions")

    def test_recovery_rejects_unverified_success_and_changed_run(self):
        for status in (RunStatus.COMPLETED, RunStatus.RUNNING):
            with self.subTest(status=status), self.fixture(status) as (_root, _connection, repository, task, _digest):
                self.assertIsNone(repository.task_execution_recovery(task["id"]))
        with self.fixture() as (_root, connection, repository, task, _digest):
            request = self.request(repository, task["id"])
            for column, value in (("partial", 1), ("terminal_finalized", 0), ("dispatch_state", "unknown")):
                old = connection.execute(f"SELECT {column} FROM mentat_runs WHERE id = ?", (request["recovery_run_id"],)).fetchone()[0]
                connection.execute(f"UPDATE mentat_runs SET {column} = ? WHERE id = ?", (value, request["recovery_run_id"]))
                connection.commit()
                self.assertIsNone(repository.task_execution_recovery(task["id"]))
                with self.assertRaises(RunRepositoryConflict):
                    repository.review_task_execution(**request)
                connection.execute(f"UPDATE mentat_runs SET {column} = ? WHERE id = ?", (old, request["recovery_run_id"]))
                connection.commit()
            connection.execute("UPDATE mentat_runs SET status = 'unknown', terminal_finalized = 0 WHERE id = ?", (request["recovery_run_id"],))
            connection.commit()
            self.assertIsNone(repository.task_execution_recovery(task["id"]))
            with self.assertRaises(RunRepositoryConflict):
                repository.review_task_execution(**request)
            connection.execute("UPDATE mentat_runs SET status = 'failed', terminal_finalized = 1 WHERE id = ?", (request["recovery_run_id"],))
            connection.execute("UPDATE mentat_runs SET state_revision = state_revision + 1 WHERE id = ?", (request["recovery_run_id"],))
            connection.commit()
            with self.assertRaises(RunRepositoryConflict):
                repository.review_task_execution(**request)

    def test_recovery_preserves_nullable_attempt_review_revision(self):
        with self.fixture() as (_root, connection, repository, task, _digest):
            connection.execute("UPDATE mentat_task_execution_attempts SET review_task_revision = NULL")
            connection.commit()
            repository.review_task_execution(**self.request(repository, task["id"]))
            attempt = repository.task_execution_attempts(task["id"])[0]
            self.assertEqual(attempt["state"], "changes_requested")
            self.assertIsNone(attempt["review_task_revision"])

    def test_recovery_rejects_competing_active_run_and_delegation(self):
        with self.fixture() as (_root, connection, repository, task, digest):
            request = self.request(repository, task["id"])
            current = TaskRepository(connection).get(task["id"])
            delegated = replace(current, document={**current.document, "delegation": {"private": "runtime-reference"}})
            with patch.object(TaskRepository, "get", return_value=delegated):
                self.assertIsNone(repository.task_execution_recovery(task["id"]))
                with self.assertRaises(RunRepositoryConflict):
                    repository.review_task_execution(**request)
            repository.reserve_dispatch(
                idempotency_key="competing-active-run-key", dispatch_id="dispatch_competing_active", run_id="run_competing_active",
                task=current.document, task_revision=current.revision, agent_id="agent-main", runtime_type="codex",
                runtime_config_id="default", binding_digest=digest, capabilities=("run.start",), now=timestamp(3),
            )
            self.assertIsNone(repository.task_execution_recovery(task["id"]))
            with self.assertRaises(RunRepositoryConflict):
                repository.review_task_execution(**request)

    def test_server_rejects_wrong_branch_fields_before_mutation(self):
        valid = {"expected_revision": 2, "action": "request_changes", "note": "Fix configuration.", "idempotency_key": "recovery-server-key-0001", "recovery_run_id": "run_recovery_original", "expected_run_revision": 3}
        for patch_fields in ({"action": "accept"}, {"expected_run_revision": False}, {"recovery_run_id": "/private/path"}, {"extra": "private"}):
            with patch.object(server, "connect_mentat_database") as connect_database:
                _, status = server.mentat_planning_task_execution_review("task_example", {**valid, **patch_fields})
                self.assertEqual(status, 400)
                connect_database.assert_not_called()

    def test_recovery_blocks_a_reserved_or_ambiguous_delegation_before_metadata_exists(self):
        with self.fixture() as (_root, connection, repository, task, _digest):
            request = self.request(repository, task["id"])
            DelegationActionReceiptRepository(connection).reserve(
                key_digest="a" * 64, request_digest="b" * 64, task_id=task["id"], task_revision=request["expected_revision"],
                action="delegate", confirmation_digest="c" * 64, delegation_binding_digest="d" * 64,
                remote_revision_digest="e" * 64, now=timestamp(3),
            )
            for state in ("reserved", "submitting", "unknown", "partial"):
                connection.execute("UPDATE mentat_task_delegation_action_receipts SET state = ?", (state,))
                connection.commit()
                self.assertIsNone(repository.task_execution_recovery(task["id"]))
                with self.assertRaises(RunRepositoryConflict):
                    repository.review_task_execution(**request)

    def test_latest_attempt_uses_task_revision_when_timestamps_tie(self):
        tied_time = timestamp()
        with patch(__name__ + ".timestamp", return_value=tied_time), self.fixture() as (_root, connection, repository, task, digest):
            repository.review_task_execution(**self.request(repository, task["id"]))
            planned = TaskRepository(connection).get(task["id"])
            second = repository.reserve_dispatch(
                idempotency_key="same-second-second-key", dispatch_id="dispatch_same_second", run_id="run_aaa_second",
                task=planned.document, task_revision=planned.revision, agent_id="agent-main", runtime_type="codex",
                runtime_config_id="default", binding_digest=digest, capabilities=("run.start",), planning_execution=True, now=tied_time,
            )
            repository.claim_dispatch_attempt(dispatch_id=second.dispatch_id, expected_binding_digest=digest, now=tied_time)
            repository.record_submission_outcome(dispatch_id=second.dispatch_id, outcome=SubmissionOutcome(
                SubmissionDisposition.ACCEPTED, run=AgentRun(id=second.run_id, task_id=task["id"], agent_id="agent-main", runtime_type="codex", status=RunStatus.FAILED),
                runtime_run_ref="private-second-reference",
            ), now=tied_time)
            attempts = repository.task_execution_attempts(task["id"])
            self.assertEqual(attempts[0]["created_at"], attempts[1]["created_at"])
            self.assertEqual(attempts[0]["run_id"], second.run_id)
            self.assertEqual(repository.task_execution_recovery(task["id"])["run_id"], second.run_id)
            repository.validate()


if __name__ == "__main__":
    unittest.main()
