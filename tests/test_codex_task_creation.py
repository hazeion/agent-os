from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from agent_registry import AgentRegistry
from agent_runtime import AgentRun, RunStatus, SubmissionDisposition, SubmissionOutcome
from codex_task_creation import CodexTaskCreationService
from mentat_db import connect
from private_state import history_path, private_state_lock
from private_console_unit import (
    PrivateConsoleUnitError,
    capture_private_console_unit,
    materialize_private_console_unit,
    validate_private_console_unit,
)
from project_repository import ProjectRepository, ensure_project_sqlite_authority
from run_repository import RunRepository, runtime_binding_digest
from task_repository import TaskRepository, ensure_task_sqlite_authority
from tests.sqlite_authority_support import ensure_run_sqlite_authority


NOW = "2026-09-02T12:00:00Z"
AGENT_ID = "agent_codex_tool"
TASK_ID = "task_codex_origin"
PROJECT_ID = "project_codex"
RUN_ID = "run_codex_task_create"
DISPATCH_ID = "dispatch_codex_task_create"
THREAD_ID = "thread_codex_task_create"
TURN_ID = "turn_codex_task_create"
CALL_ID = "call_codex_task_create"


class CodexTaskCreationServiceTests(unittest.TestCase):
    def _prepare(self, root: Path) -> tuple[CodexTaskCreationService, str]:
        task = {
            "id": TASK_ID,
            "title": "Review the migration",
            "description": "Review the current migration before creating follow-up work.",
            "project": "Codex Tools",
            "status": "todo",
            "priority": "medium",
            "assignee": "Codex Tool",
            "assigned_agent_id": AGENT_ID,
            "due_date": None,
            "source": "dashboard",
            "tags": [],
            "review_required": False,
            "needs_attention": False,
            "created_at": NOW,
            "updated_at": NOW,
            "completed_at": None,
        }
        project = {
            "id": PROJECT_ID,
            "name": "Codex Tools",
            "type": "project",
            "status": "active",
            "description": "A disposable Codex callback test project.",
            "obsidian_note": None,
            "aliases": [],
            "created_at": NOW,
            "updated_at": NOW,
        }
        (root / "tasks.json").write_text(json.dumps([task]) + "\n", encoding="utf-8")
        (root / "projects.json").write_text(json.dumps([project]) + "\n", encoding="utf-8")
        (root / "tasks.json").chmod(0o600)
        (root / "projects.json").chmod(0o600)
        ensure_task_sqlite_authority(root, required_source_mode=None)
        ensure_project_sqlite_authority(root, required_source_mode=None)
        ensure_run_sqlite_authority(root, history_path(root))

        capabilities = ("run.start", "task.create")
        AgentRegistry(root, supported_runtime_types=("codex",)).create_agent(
            agent_id=AGENT_ID,
            name="Codex Tool",
            runtime_config_id="codex-default-tool",
            runtime_type="codex",
            runtime_agent_ref="default",
            capabilities=capabilities,
        )
        digest = runtime_binding_digest(
            agent_id=AGENT_ID,
            runtime_type="codex",
            runtime_config_id="codex-default-tool",
            runtime_agent_ref="default",
            capabilities=capabilities,
        )
        service = CodexTaskCreationService(root)
        with private_state_lock(root):
            connection = connect(root)
            try:
                origin = TaskRepository(connection).get(TASK_ID)
                repository = RunRepository(connection)
                reservation = repository.reserve_dispatch(
                    idempotency_key="codex-task-create-test-key",
                    dispatch_id=DISPATCH_ID,
                    run_id=RUN_ID,
                    task=origin.document,
                    task_revision=origin.revision,
                    agent_id=AGENT_ID,
                    runtime_type="codex",
                    runtime_config_id="codex-default-tool",
                    binding_digest=digest,
                    capabilities=capabilities,
                )
                def prepare(claimed):
                    return service.preauthorize_claimed(
                        connection=connection,
                        run_id=claimed.run_id,
                        task_id=claimed.task_id,
                        task_revision=claimed.task_revision,
                        project_id=PROJECT_ID,
                        agent_id=AGENT_ID,
                        runtime_binding_digest=digest,
                    )
                repository.claim_dispatch_attempt(
                    dispatch_id=reservation.dispatch_id,
                    expected_binding_digest=digest,
                    grant_preparer=prepare,
                )
            finally:
                connection.close()
        self.assertTrue(service.bind_thread(run_id=RUN_ID, thread_id=THREAD_ID))
        self.assertTrue(service.arm(run_id=RUN_ID, thread_id=THREAD_ID, turn_id=TURN_ID))
        with private_state_lock(root):
            connection = connect(root)
            try:
                RunRepository(connection).record_submission_outcome(
                    dispatch_id=DISPATCH_ID,
                    outcome=SubmissionOutcome(
                        SubmissionDisposition.ACCEPTED,
                        run=AgentRun(
                            id=RUN_ID,
                            task_id=TASK_ID,
                            agent_id=AGENT_ID,
                            runtime_type="codex",
                            status=RunStatus.STARTING,
                        ),
                        runtime_run_ref=f"{THREAD_ID}:{TURN_ID}",
                    ),
                )
            finally:
                connection.close()
        return service, digest

    @staticmethod
    def _request(*, arguments: str) -> dict[str, object]:
        return {
            "thread_id": THREAD_ID,
            "turn_id": TURN_ID,
            "call_id": CALL_ID,
            "tool": "mentat_tasks_create_inbox",
            "arguments": arguments,
        }

    @staticmethod
    def _created_counts(root: Path) -> tuple[int, int]:
        with private_state_lock(root):
            connection = connect(root)
            try:
                tasks = len(TaskRepository(connection).list_tasks())
                receipts = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_codex_task_create_receipts"
                    ).fetchone()[0]
                )
            finally:
                connection.close()
        return tasks, receipts

    @staticmethod
    def _replace_origin(root: Path, transform, *, allow_project_move: bool = False) -> None:
        """Apply a real Task revision change after the durable grant was armed."""

        with private_state_lock(root):
            connection = connect(root)
            try:
                connection.execute("BEGIN IMMEDIATE")
                repository = TaskRepository(connection)
                current = repository.get(TASK_ID)
                replacement = dict(current.document)
                transform(replacement)
                repository.replace(
                    replacement,
                    expected_revision=current.revision,
                    allow_project_move=allow_project_move,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @staticmethod
    def _add_other_project(root: Path) -> None:
        with private_state_lock(root):
            connection = connect(root)
            try:
                connection.execute("BEGIN IMMEDIATE")
                repository = ProjectRepository(connection)
                current = repository.list_projects()
                other = {
                    "id": "project_codex_other",
                    "name": "Codex Tools Other",
                    "type": "project",
                    "status": "active",
                    "description": "A second disposable callback test project.",
                    "obsidian_note": None,
                    "aliases": [],
                    "created_at": NOW,
                    "updated_at": NOW,
                }
                repository.mutate_collection(lambda projects: ([*projects, other], None))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    @staticmethod
    def _mutate_database(root: Path, callback) -> None:
        with private_state_lock(root):
            connection = connect(root)
            try:
                callback(connection)
                connection.commit()
            finally:
                connection.close()

    def test_malformed_callback_is_rejected_without_creation(self):
        with TemporaryDirectory() as temporary:
            service = CodexTaskCreationService(Path(temporary))
            invalid_requests = (
                {},
                {**self._request(arguments="{}"), "unexpected": True},
                self._request(arguments="not-json"),
                self._request(arguments=json.dumps({"title": "Follow up", "project_id": PROJECT_ID})),
                self._request(arguments=json.dumps({"title": "Follow up", "assign_to_self": "yes"})),
            )
            for request in invalid_requests:
                with self.subTest(request=request):
                    self.assertEqual(
                        service.handle(request),
                        {"success": False, "message": "Task creation request is invalid."},
                    )

    def test_accepted_callback_and_exact_replay_create_one_inbox_task(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, _digest = self._prepare(root)
            request = self._request(
                arguments=json.dumps(
                    {
                        "title": "Capture review findings",
                        "description": "Record the bounded findings from the migration review.",
                        "acceptance_criteria": ["Findings are recorded."],
                        "assign_to_self": True,
                        "depends_on_origin": True,
                    }
                )
            )

            self.assertEqual(service.handle(request), {"success": True, "message": "Inbox Task created."})
            self.assertEqual(service.handle(request), {"success": True, "message": "Inbox Task created."})

            with private_state_lock(root):
                connection = connect(root)
                try:
                    tasks = TaskRepository(connection).list_tasks()
                    receipts = connection.execute(
                        "SELECT created_task_id, created_task_revision FROM mentat_codex_task_create_receipts"
                    ).fetchall()
                finally:
                    connection.close()
            self.assertEqual(len(tasks), 2)
            self.assertEqual(len(receipts), 1)
            created = next(task for task in tasks if task["id"] != TASK_ID)
            self.assertEqual(created["title"], "Capture review findings")
            self.assertEqual(created["project_id"], PROJECT_ID)
            self.assertEqual(created["assigned_agent_id"], AGENT_ID)
            self.assertEqual(created["workflow_stage"], "inbox")
            self.assertEqual(created["planning_state"], "inbox")
            self.assertEqual(created["status"], "todo")
            self.assertEqual(created["priority"], "medium")
            self.assertEqual(created["depends_on"], [TASK_ID])
            self.assertEqual(int(receipts[0]["created_task_revision"]), 1)

    def test_armed_callback_rejects_wrong_runtime_binding_without_creation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, _digest = self._prepare(root)
            arguments = json.dumps({"title": "Capture review findings"})
            for request in (
                {**self._request(arguments=arguments), "thread_id": "other_thread"},
                {**self._request(arguments=arguments), "turn_id": "other_turn"},
            ):
                with self.subTest(request=request):
                    self.assertEqual(
                        service.handle(request),
                        {"success": False, "message": "Task creation is not available for this Run."},
                    )
                    self.assertEqual(self._created_counts(root), (1, 0))

    def test_callback_revalidates_changed_origin_revision_assignment_and_project(self):
        variants = (
            (
                "origin revision",
                lambda root: self._replace_origin(
                    root,
                    lambda task: task.update(description="Changed after dispatch."),
                ),
            ),
            (
                "origin assignment",
                lambda root: self._replace_origin(
                    root,
                    lambda task: task.update(
                        assignee="Other Agent", assigned_agent_id="agent_other"
                    ),
                ),
            ),
            (
                "origin moved project",
                lambda root: (
                    self._add_other_project(root),
                    self._replace_origin(
                        root,
                        lambda task: task.update(
                            project="Codex Tools Other",
                            project_id="project_codex_other",
                        ),
                        allow_project_move=True,
                    ),
                ),
            ),
        )
        for label, invalidate in variants:
            with self.subTest(label=label), TemporaryDirectory() as temporary:
                root = Path(temporary)
                service, _digest = self._prepare(root)
                invalidate(root)
                self.assertEqual(
                    service.handle(self._request(arguments=json.dumps({"title": "Follow up"}))),
                    {"success": False, "message": "Task creation is not available for this Run."},
                )
                self.assertEqual(self._created_counts(root), (1, 0))

    def test_callback_rejects_removed_origin_task_without_creation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, _digest = self._prepare(root)

            def remove_origin(connection):
                # This simulates an external authority loss after the grant. The
                # test database is intentionally made stale only long enough to
                # prove the callback fails closed rather than creating a task.
                connection.execute("PRAGMA foreign_keys = OFF")
                connection.execute("DELETE FROM mentat_tasks WHERE id = ?", (TASK_ID,))

            self._mutate_database(root, remove_origin)
            self.assertEqual(
                service.handle(self._request(arguments=json.dumps({"title": "Follow up"}))),
                {"success": False, "message": "Task creation is not available for this Run."},
            )
            self.assertEqual(self._created_counts(root), (0, 0))

    def test_callback_revalidates_agent_capability_and_binding(self):
        variants = (
            (
                "capability removed",
                lambda connection: connection.execute(
                    "UPDATE mentat_agents SET capabilities_json = ?, revision = revision + 1 WHERE id = ?",
                    (json.dumps(["run.start"]), AGENT_ID),
                ),
            ),
            (
                "binding changed",
                lambda connection: connection.execute(
                    "UPDATE agent_runtime_configs SET runtime_agent_ref = ? WHERE id = ?",
                    ("other", "codex-default-tool"),
                ),
            ),
        )
        for label, invalidate in variants:
            with self.subTest(label=label), TemporaryDirectory() as temporary:
                root = Path(temporary)
                service, _digest = self._prepare(root)
                self._mutate_database(root, invalidate)
                self.assertEqual(
                    service.handle(self._request(arguments=json.dumps({"title": "Follow up"}))),
                    {"success": False, "message": "Task creation is not available for this Run."},
                )
                self.assertEqual(self._created_counts(root), (1, 0))

    def test_callback_revalidates_inactive_and_nonaccepted_or_terminal_run(self):
        variants = (
            (
                "project inactive",
                lambda root: self._replace_project_status(root, "paused"),
            ),
            (
                "run no longer accepted",
                lambda root: self._mutate_database(
                    root,
                    lambda connection: connection.execute(
                        "UPDATE mentat_runs SET dispatch_state = 'unknown' WHERE id = ?",
                        (RUN_ID,),
                    ),
                ),
            ),
            (
                "run terminal",
                lambda root: self._mutate_database(
                    root,
                    lambda connection: connection.execute(
                        "UPDATE mentat_runs SET status = 'completed' WHERE id = ?",
                        (RUN_ID,),
                    ),
                ),
            ),
        )
        for label, invalidate in variants:
            with self.subTest(label=label), TemporaryDirectory() as temporary:
                root = Path(temporary)
                service, _digest = self._prepare(root)
                invalidate(root)
                self.assertEqual(
                    service.handle(self._request(arguments=json.dumps({"title": "Follow up"}))),
                    {"success": False, "message": "Task creation is not available for this Run."},
                )
                self.assertEqual(self._created_counts(root), (1, 0))

    @staticmethod
    def _replace_project_status(root: Path, status: str) -> None:
        with private_state_lock(root):
            connection = connect(root)
            try:
                connection.execute("BEGIN IMMEDIATE")
                repository = ProjectRepository(connection)
                current = repository.get(PROJECT_ID)
                repository.replace(
                    {**current.document, "status": status},
                    expected_revision=current.revision,
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def test_distinct_callback_id_cannot_create_second_task(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, _digest = self._prepare(root)
            request = self._request(arguments=json.dumps({"title": "Capture review findings"}))
            self.assertEqual(service.handle(request)["success"], True)
            self.assertEqual(
                service.handle({**request, "call_id": "call_codex_task_create_other"}),
                {"success": False, "message": "Task creation is not available for this Run."},
            )
            self.assertEqual(self._created_counts(root), (2, 1))

    def test_reconstructed_service_replay_and_concurrent_duplicates_are_one_time(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, _digest = self._prepare(root)
            request = self._request(arguments=json.dumps({"title": "Capture review findings"}))

            with ThreadPoolExecutor(max_workers=4) as workers:
                results = list(workers.map(service.handle, [request] * 4))
            self.assertEqual(
                results,
                [{"success": True, "message": "Inbox Task created."}] * 4,
            )
            reconstructed = CodexTaskCreationService(root)
            self.assertEqual(
                reconstructed.handle(request),
                {"success": True, "message": "Inbox Task created."},
            )
            self.assertEqual(self._created_counts(root), (2, 1))

    def test_receipt_insert_failure_rolls_back_created_task(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, _digest = self._prepare(root)
            request = self._request(arguments=json.dumps({"title": "Follow up"}))
            original_insert = TaskRepository.insert

            def insert_then_fail(repository, task):
                original_insert(repository, task)
                raise sqlite3.OperationalError("forced receipt failure")

            with patch("codex_task_creation.TaskRepository.insert", new=insert_then_fail):
                self.assertEqual(
                    service.handle(request),
                    {"success": False, "message": "Task creation is not available for this Run."},
                )
            self.assertEqual(self._created_counts(root), (1, 0))
            self.assertEqual(
                service.handle(request),
                {"success": True, "message": "Inbox Task created."},
            )
            self.assertEqual(self._created_counts(root), (2, 1))

    def test_capture_materialize_restore_preserves_one_time_callback_receipt(self):
        with TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            service, _digest = self._prepare(source)
            request = self._request(arguments=json.dumps({"title": "Follow up"}))
            self.assertEqual(
                service.handle(request),
                {"success": True, "message": "Inbox Task created."},
            )
            unit = capture_private_console_unit(source)

            restored = Path(temporary) / "restored"
            (restored / "private").mkdir(parents=True, mode=0o700)
            stage = materialize_private_console_unit(
                restored,
                unit,
                restored / "private" / "restore-stage",
            )
            stage.rename(restored / "private" / "console")

            reopened = CodexTaskCreationService(restored)
            self.assertEqual(
                reopened.handle(request),
                {"success": True, "message": "Inbox Task created."},
            )
            self.assertEqual(self._created_counts(restored), (2, 1))

    def test_private_capture_rejects_malformed_schema_twenty_two_receipt(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service, _digest = self._prepare(root)
            self.assertTrue(service.handle(self._request(arguments=json.dumps({"title": "Capture review findings"})))["success"])
            unit = capture_private_console_unit(root)
            self.assertIs(validate_private_console_unit(unit), unit)

            with private_state_lock(root):
                connection = connect(root)
                try:
                    connection.execute(
                        "UPDATE mentat_codex_task_create_receipts SET created_at = 'invalid'"
                    )
                    connection.commit()
                finally:
                    connection.close()
            with self.assertRaisesRegex(PrivateConsoleUnitError, "private_codex_task_creation_invalid"):
                capture_private_console_unit(root)


if __name__ == "__main__":
    unittest.main()
