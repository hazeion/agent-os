from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from agent_registry import AgentRegistry
from agent_runtime import AgentRuntimeRegistry
from conversation_repository import ConversationRepository
from conversation_planning import project_registry, validate_association_targets
from mentat_db import connect
from orchestration_service import OrchestrationService
from planning_deletion import PlanningDeletionError, PlanningDeletionService
from private_state import history_path
from project_repository import ensure_project_sqlite_authority, read_authoritative_projects
from task_repository import ensure_task_sqlite_authority, read_authoritative_tasks
from run_repository import RunRepository
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from tests.test_orchestration_service import FakeRuntime
import server


def project(identifier: str, name: str) -> dict:
    return {
        "id": identifier, "name": name, "type": "software", "status": "active",
        "description": "", "obsidian_note": "", "aliases": [],
        "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00",
    }


def task(identifier: str, name: str, *, depends_on: list[str] | None = None) -> dict:
    return {
        "id": identifier, "title": identifier, "description": "", "project": name,
        "status": "todo", "priority": "medium", "assignee": None, "due_date": None,
        "source": "test", "tags": [], "review_required": False, "needs_attention": False,
        "created_at": "2026-09-01T00:00:00+00:00", "updated_at": "2026-09-01T00:00:00+00:00",
        "completed_at": None, "depends_on": depends_on or [],
    }


class PlanningDeletionTests(unittest.TestCase):
    def executed_root(self, temporary: str, *, retry_count: int = 1):
        """Build the reported cascade using public repositories and orchestration."""
        root = Path(temporary)
        (root / "projects.json").write_text(json.dumps([
            project("project_one", "One"), project("project_keep", "Keep"),
        ]), encoding="utf-8")
        assigned = task("task_run", "One")
        assigned.update(source="dashboard", assigned_agent_id="agent_delete", planning_state="planned", workflow_stage="planned")
        (root / "tasks.json").write_text(json.dumps([
            assigned, task("task_other", "One"), task("task_keep", "Keep"),
        ]), encoding="utf-8")
        ensure_task_sqlite_authority(root, required_source_mode=None)
        ensure_project_sqlite_authority(root, required_source_mode=None)
        ensure_run_sqlite_authority(root, history_path(root))
        runtime = FakeRuntime(root)
        runtime.runtime_type = "codex"
        runtime.runtime_agent_ref = "default"
        runtime.capacity_scope = "codex-app-server:" + "a" * 64
        runtime.rejects = True
        registry = AgentRegistry(root, supported_runtime_types=("codex",))
        registry.create_agent(
            agent_id="agent_delete", name="Deletion test Agent",
            runtime_config_id="config_delete", runtime_type="codex",
            runtime_agent_ref="default", capabilities=("run.start", "run.message"),
        )
        service = OrchestrationService(root, runtime_registry=AgentRuntimeRegistry((runtime,)), agent_registry=registry)
        conversations = ConversationRepository(root, supported_runtime_types=("codex",))
        conversation = conversations.create(agent_id="agent_delete").conversation
        keep = conversations.create(agent_id="agent_delete").conversation
        projects = project_registry(read_authoritative_projects(root))
        conversations.set_planning_association(
            conversation.id, expected_revision=conversation.revision,
            project_id="project_one", task_id="task_run",
            validate_targets=lambda connection, project_id, task_id: validate_association_targets(connection, projects, project_id, task_id),
        )
        service.dispatch_task(task_id="task_run", expected_revision=1, idempotency_key="deletion-task-run-key", planning_execution=True)
        # IDs deliberately put the predecessor first in SQLite key order.
        service.id_factory = lambda prefix: f"{prefix}_aaa_initial"
        first = service.submit_conversation_turn(conversation_id=conversation.id, text="A bounded question", idempotency_key="deletion-first-turn-key")
        source_run_id = first.run.id
        for attempt in range(retry_count):
            service.id_factory = lambda prefix: f"{prefix}_zzz_retry_{attempt}"
            retried = service.retry_conversation_run(conversation_id=conversation.id, source_run_id=source_run_id, idempotency_key=f"deletion-retry-turn-key-{attempt}")
            source_run_id = retried.attempt.run_id
        service.id_factory = lambda prefix: f"{prefix}_{uuid4().hex}"
        service.submit_conversation_turn(conversation_id=keep.id, text="Retain this separate history", idempotency_key="deletion-keep-turn-key")
        with closing(connect(root)) as connection:
            RunRepository(connection).validate()
        return root, conversation.id, keep.id

    def test_project_with_task_execution_and_conversation_retry_deletes_exact_closure(self):
        for retry_count in (0, 1, 2):
            with self.subTest(retry_count=retry_count), TemporaryDirectory() as temporary:
                root, deleted_conversation, kept_conversation = self.executed_root(temporary, retry_count=retry_count)
                service = PlanningDeletionService(root)
                plan = service.preview("project", "project_one")
                self.assertEqual(plan.counts.public(), {"projects": 1, "tasks": 2, "conversations": 1, "runs": 2 + retry_count, "artifacts": 0})
                self.assertEqual(plan.active_run_ids, ())
                confirmed = service.begin_confirmation("project", "project_one", plan.confirmation_id)
                self.assertEqual(service.finalize(confirmed), plan.counts)
                self.assertEqual(service.completed_receipt("project", "project_one", plan.confirmation_id), plan.counts)
                with closing(connect(root)) as connection:
                    self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                    self.assertEqual([row[0] for row in connection.execute("SELECT id FROM mentat_conversations")], [kept_conversation])
                    for table in ("mentat_conversation_turns", "mentat_conversation_messages", "mentat_runs"):
                        self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE conversation_id = ?", (deleted_conversation,)).fetchone()[0], 0)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_conversation_run_attempts").fetchone()[0], 0)
                    RunRepository(connection).validate()
                self.assertEqual([row["id"] for row in read_authoritative_tasks(root)], ["task_keep"])
                self.assertEqual([row["id"] for row in read_authoritative_projects(root)], ["project_keep"])

    def test_retry_cascade_rolls_back_all_evidence_and_receipt_on_late_failure(self):
        with TemporaryDirectory() as temporary:
            root, _deleted_conversation, _kept_conversation = self.executed_root(temporary)
            service = PlanningDeletionService(root)
            plan = service.preview("task", "task_run")
            original_erase = PlanningDeletionService._erase

            def fail_after_erase(connection, selected):
                original_erase(connection, selected)
                raise sqlite3.IntegrityError("injected late transaction failure")

            with patch.object(PlanningDeletionService, "_erase", side_effect=fail_after_erase):
                with self.assertRaisesRegex(PlanningDeletionError, "deletion_unavailable"):
                    service.finalize(plan)
            self.assertEqual(service.preview("task", "task_run"), plan)
            self.assertIsNone(service.completed_receipt("task", "task_run", plan.confirmation_id))
            with closing(connect(root)) as connection:
                RunRepository(connection).validate()
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            # The exact original confirmation still works after the rollback.
            self.assertEqual(service.finalize(plan), plan.counts)
            self.assertEqual([row["id"] for row in read_authoritative_tasks(root)], ["task_other", "task_keep"])
            self.assertEqual([row["id"] for row in read_authoritative_projects(root)], ["project_one", "project_keep"])

    def root(self, temporary: str) -> Path:
        root = Path(temporary)
        (root / "projects.json").write_text(json.dumps([
            project("project_one", "One"), project("project_two", "Two"),
        ]), encoding="utf-8")
        (root / "tasks.json").write_text(json.dumps([
            task("task_root", "One"), task("task_child", "Two", depends_on=["task_root"]),
            task("task_keep", "Two"),
        ]), encoding="utf-8")
        ensure_task_sqlite_authority(root, required_source_mode=None)
        ensure_project_sqlite_authority(root, required_source_mode=None)
        return root

    def test_task_deletion_cascades_transitive_cross_project_dependents(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            service = PlanningDeletionService(root)
            plan = service.preview("task", "task_root")
            counts = service.finalize(plan)
            rows = read_authoritative_tasks(root)
            projects = read_authoritative_projects(root)

        self.assertEqual(plan.task_ids, ("task_child", "task_root"))
        self.assertEqual(counts.tasks, 2)
        self.assertEqual([row["id"] for row in rows], ["task_keep"])
        self.assertEqual([row["id"] for row in projects], ["project_one", "project_two"])

    def test_project_deletion_includes_cross_project_dependents_but_not_their_project(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            service = PlanningDeletionService(root)
            plan = service.preview("project", "project_one")
            service.finalize(plan)
            rows = read_authoritative_tasks(root)
            projects = read_authoritative_projects(root)

        self.assertEqual(plan.task_ids, ("task_child", "task_root"))
        self.assertEqual(plan.project_ids, ("project_one",))
        self.assertEqual([row["id"] for row in rows], ["task_keep"])
        self.assertEqual([row["id"] for row in projects], ["project_two"])

    def test_changed_dependency_invalidates_the_frozen_plan(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            service = PlanningDeletionService(root)
            plan = service.preview("task", "task_root")
            connection = connect(root)
            try:
                connection.execute("UPDATE mentat_tasks SET revision = revision + 1 WHERE id = 'task_child'")
            finally:
                connection.close()
            with self.assertRaisesRegex(PlanningDeletionError, "deletion_stale"):
                service.finalize(plan)
            rows = read_authoritative_tasks(root)

        self.assertEqual({row["id"] for row in rows}, {"task_root", "task_child", "task_keep"})

    def test_active_run_requires_verified_terminal_transition_before_erase(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            connection = connect(root)
            try:
                connection.execute(
                    "INSERT INTO mentat_runs (id, source, task_id, runtime_type, status, dispatch_state, details_json, created_at, updated_at) VALUES (?, 'task_dispatch', 'task_root', 'hermes', 'running', 'accepted', '{}', ?, ?)",
                    ("run_delete_active", "2026-09-01T00:00:00+00:00", "2026-09-01T00:00:00+00:00"),
                )
            finally:
                connection.close()
            service = PlanningDeletionService(root)
            plan = service.preview("task", "task_root")
            self.assertEqual(plan.active_run_ids, ("run_delete_active",))
            with self.assertRaisesRegex(PlanningDeletionError, "deletion_stop_unverified"):
                service.finalize(plan)
            connection = connect(root)
            try:
                connection.execute("UPDATE mentat_runs SET status = 'stopped', terminal_finalized = 1, state_revision = state_revision + 1 WHERE id = 'run_delete_active'")
            finally:
                connection.close()
            service.finalize(plan)
            remaining = read_authoritative_tasks(root)

        self.assertEqual([row["id"] for row in remaining], ["task_keep"])

    def test_receipt_replay_is_idempotent_after_the_target_is_gone(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            service = PlanningDeletionService(root)
            plan = service.preview("task", "task_root")
            self.assertEqual(service.finalize(plan).tasks, 2)
            # Duplicate confirmation must be resolved from the bounded receipt,
            # not by attempting to reconstruct an absent task closure.
            self.assertEqual(service.finalize(plan).tasks, 2)
            remaining = read_authoritative_tasks(root)

        self.assertEqual([row["id"] for row in remaining], ["task_keep"])

    def test_deletion_releases_delegated_artifact_bindings_before_orphaning(self):
        """Synthetic delegation bindings must not retain a deleted Task blob."""

        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            connection = connect(root)
            try:
                connection.execute(
                    "INSERT INTO blobs (id, sha256, storage_key, byte_size, state, created_at, updated_at) VALUES (?, ?, ?, 1, 'ready', 1, 1)",
                    ("blob_delete", "a" * 64, "blob-delete"),
                )
                connection.execute(
                    "INSERT INTO attachments (id, blob_id, original_name, mime_type, kind, state, byte_size, created_at, updated_at) VALUES (?, ?, 'result.txt', 'text/plain', 'text', 'attached', 1, 1, 1)",
                    ("attachment_delete", "blob_delete"),
                )
                connection.execute(
                    "INSERT INTO task_artifacts (mentat_task_id, connection_binding_id, board_id, remote_task_id, remote_artifact_id, attachment_id, binding_id, ordinal, created_at) VALUES ('task_root', 'binding', 'board', 'remote', 'artifact', 'attachment_delete', 'delegation_delete', 0, 1)"
                )
                connection.execute(
                    "INSERT INTO run_attachments (run_id, attachment_id, direction, ordinal, created_at) VALUES ('delegation_delete', 'attachment_delete', 'output', 0, 1)"
                )
            finally:
                connection.close()
            service = PlanningDeletionService(root)
            plan = service.preview("task", "task_root")
            service.finalize(plan)
            connection = connect(root)
            try:
                mappings = connection.execute("SELECT 1 FROM task_artifacts").fetchall()
                bindings = connection.execute("SELECT 1 FROM run_attachments").fetchall()
                state = connection.execute("SELECT state FROM attachments WHERE id = 'attachment_delete'").fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(plan.artifact_binding_ids, ("delegation_delete",))
        self.assertEqual(plan.counts.artifacts, 1)
        self.assertEqual(mappings, [])
        self.assertEqual(bindings, [])
        self.assertEqual(state, "orphaned")

    def test_server_preview_and_confirm_expose_only_counted_effects(self):
        with TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root), patch.object(server, "CONFIGURED_DATA_DIR", root):
                preview, preview_status = server.preview_mentat_planning_deletion({
                    "target_kind": "task", "target_id": "task_root",
                })
                result, result_status = server.confirm_mentat_planning_deletion({
                    "target_kind": "task", "target_id": "task_root", "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                })
                replay, replay_status = server.confirm_mentat_planning_deletion({
                    "target_kind": "task", "target_id": "task_root", "confirmed": True,
                    "confirmation_id": preview["confirmation_id"],
                })

        self.assertEqual(preview_status, 200)
        self.assertEqual(set(preview), {"schema_version", "target_kind", "target_id", "confirmation_id", "affected", "has_active_runs"})
        self.assertEqual(result_status, 200)
        self.assertEqual(result, {
            "schema_version": 1, "action": "delete", "target_kind": "task", "target_id": "task_root",
            "deletion": {"projects": 0, "tasks": 2, "conversations": 0, "runs": 0, "artifacts": 0},
        })
        self.assertEqual((replay_status, replay), (result_status, result))


if __name__ == "__main__":
    unittest.main()
