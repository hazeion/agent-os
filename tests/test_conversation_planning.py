from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import server
from agent_registry import AgentRegistry

from conversation_planning import (
    ConversationPlanningError,
    planning_context_projection,
    planning_overview,
    planning_task_locator,
    planning_task_page,
    project_registry,
    validate_association_targets,
)
from conversation_repository import (
    ConversationRepository,
    ConversationRepositoryConflict,
)
from mentat_db import connect
from task_repository import TaskRepository, ensure_task_sqlite_authority, read_authoritative_tasks
from project_repository import ensure_project_sqlite_authority


NOW = "2026-08-30T12:00:00Z"


def task(identifier: str, *, project: str = "Mentat", due: str | None = None, **extra):
    value = {
        "id": identifier,
        "title": f"Task {identifier}",
        "description": "private description",
        "project": project,
        "status": "todo",
        "priority": "medium",
        "assignee": None,
        "due_date": due,
        "source": "dashboard",
        "tags": [],
        "review_required": False,
        "needs_attention": False,
        "created_at": NOW,
        "updated_at": NOW,
        "completed_at": None,
    }
    value.update(extra)
    return value


PROJECTS = [
    {
        "id": "project_mentat",
        "name": "Mentat",
        "status": "active",
        "aliases": ["Agent OS"],
        "description": "must not cross",
        "obsidian_note": "Private/Path.md",
    },
    {"id": "project_other", "name": "Other", "status": "paused"},
]


def create_test_agent(root: Path) -> str:
    agent_id = "agent_planner"
    AgentRegistry(root, supported_runtime_types={"hermes"}).create_agent(
        agent_id=agent_id,
        name="Planner",
        runtime_config_id="config_planner",
        runtime_type="hermes",
        runtime_agent_ref="planner-profile",
        capabilities={"run.start"},
    )
    return agent_id


class ConversationPlanningTests(unittest.TestCase):
    def test_exact_global_task_locator_reads_non_attention_task_without_private_fields(self):
        with TemporaryDirectory() as temporary:
            connection = connect(Path(temporary))
            try:
                TaskRepository(connection).insert_collection([
                    task("task_quiet", project="Agent OS"),
                ])
                located = planning_task_locator(
                    connection,
                    PROJECTS,
                    task_id="task_quiet",
                    today=date(2026, 8, 30),
                )
                self.assertEqual(located["project"], {"id": "project_mentat", "name": "Mentat", "status": "active", "revision": 1})
                self.assertEqual(located["task"]["id"], "task_quiet")
                self.assertEqual(located["task"]["attention_reasons"], [])
                for private in ("private description", "description", "assignee", "source", "tags"):
                    self.assertNotIn(private, str(located))
                with self.assertRaisesRegex(ConversationPlanningError, "planning.task_not_found"):
                    planning_task_locator(
                        connection,
                        PROJECTS,
                        task_id="task_missing",
                        today=date(2026, 8, 30),
                    )
            finally:
                connection.close()
        with TemporaryDirectory() as temporary:
            connection = connect(Path(temporary))
            try:
                TaskRepository(connection).insert_collection([task("task_ambiguous", project="Shared")])
                with self.assertRaisesRegex(ConversationPlanningError, "planning.projects_ambiguous"):
                    planning_task_locator(
                        connection,
                        [
                            {"id": "project_a", "name": "A", "status": "active", "aliases": ["Shared"]},
                            {"id": "project_b", "name": "B", "status": "active", "aliases": ["shared"]},
                        ],
                        task_id="task_ambiguous",
                        today=date(2026, 8, 30),
                    )
            finally:
                connection.close()

    def test_named_minimal_create_helpers_use_only_canonical_authorities(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("projects.json", "tasks.json"):
                path = root / name
                path.write_text("[]", encoding="utf-8")
                path.chmod(0o600)
            ensure_task_sqlite_authority(root)
            ensure_project_sqlite_authority(root)
            AgentRegistry(root, supported_runtime_types={"hermes"}).create_agent(
                agent_id="agent_planner",
                name="Planner",
                runtime_config_id="config_planner",
                runtime_type="hermes",
                runtime_agent_ref="planner-profile",
                capabilities={"run.start"},
            )
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "CONFIGURED_DATA_DIR", root),
                patch.object(server, "DATA_MUTATION_LOCK", True),
            ):
                project_result, project_status = server.create_mentat_project(
                    {"name": "Alpha"}
                )
                self.assertEqual(project_status, 201)
                self.assertEqual(
                    project_result["project"],
                    {"id": "project_alpha", "name": "Alpha", "status": "active", "revision": 1},
                )
                duplicate, duplicate_status = server.create_mentat_project(
                    {"name": "Alpha"}
                )
                self.assertEqual(duplicate_status, 409)
                self.assertNotIn("projects", duplicate)
                task_result, task_status = server.create_mentat_project_task(
                    "project_alpha",
                    {
                        "title": "First task",
                        "assigned_agent_id": None,
                        "due_date": "2026-08-30",
                    },
                )
                self.assertEqual(task_status, 201)
                self.assertEqual(task_result["task"]["project_id"], "project_alpha")
                assigned_result, assigned_status = server.create_mentat_project_task(
                    "project_alpha",
                    {
                        "title": "Assigned task",
                        "assigned_agent_id": "agent_planner",
                        "due_date": None,
                    },
                )
                self.assertEqual(assigned_status, 201)
                self.assertEqual(assigned_result["task"]["title"], "Assigned task")
                missing, missing_status = server.create_mentat_project_task(
                    "project_alpha",
                    {
                        "title": "Assigned",
                        "assigned_agent_id": "agent_missing",
                        "due_date": None,
                    },
                )
                self.assertEqual(
                    (missing_status, missing),
                    (404, {"error_code": "planning.agent_not_found"}),
                )
            stored = read_authoritative_tasks(root)
            self.assertEqual(len(stored), 2)
            self.assertEqual(stored[0]["assignee"], "Operator")
            self.assertNotIn("assigned_agent_id", stored[0])
            self.assertEqual(stored[1]["assignee"], "Planner")
            self.assertEqual(stored[1]["assigned_agent_id"], "agent_planner")

    def test_overview_is_bounded_safe_and_uses_fixed_attention_rules(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = connect(root)
            try:
                TaskRepository(connection).insert_collection([
                    task("task_overdue", due="2026-08-29"),
                    task("task_today", due="2026-08-30"),
                    task("task_review", review_required=True),
                    task("task_completed", due="2026-08-01", status="completed", completed_at=NOW),
                    task("task_orphan", project="Missing", needs_attention=True),
                ])
                payload = planning_overview(connection, PROJECTS, today=date(2026, 8, 30))
            finally:
                connection.close()
            self.assertEqual(payload["project_count"], 2)
            self.assertEqual(
                [item["id"] for item in payload["attention"]],
                ["task_overdue", "task_today", "task_review"],
            )
            self.assertEqual(payload["attention"][0]["attention_reasons"], ["overdue"])
            serialized = str(payload)
            for private in ("private description", "Private/Path.md", "obsidian_note", "description"):
                self.assertNotIn(private, serialized)
            self.assertNotIn("task_completed", serialized)
            self.assertNotIn("task_orphan", serialized)

    def test_task_page_exposes_only_a_bounded_plain_text_description_preview(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = connect(root)
            try:
                TaskRepository(connection).insert_collection([
                    task(
                        "task_preview",
                        description=("Detailed\nplanning description " + "x" * 400),
                    )
                ])
                page = planning_task_page(
                    connection,
                    PROJECTS,
                    project_id="project_mentat",
                    cursor=None,
                    today=date(2026, 8, 30),
                )
                overview = planning_overview(connection, PROJECTS, today=date(2026, 8, 30))
            finally:
                connection.close()
        preview = page["tasks"][0]["description_preview"]
        self.assertEqual(preview[:31], "Detailed planning description x")
        self.assertLessEqual(len(preview), 280)
        self.assertTrue(preview.endswith("…"))
        self.assertNotIn("description_preview", str(overview))

    def test_project_bound_cursor_and_alias_resolution_fail_closed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = connect(root)
            try:
                TaskRepository(connection).insert_collection([
                    task(f"task_{index:03d}", project="Agent OS")
                    for index in range(51)
                ])
                first = planning_task_page(
                    connection,
                    PROJECTS,
                    project_id="project_mentat",
                    cursor=None,
                    today=date(2026, 8, 30),
                )
                self.assertEqual(first["count"], 50)
                self.assertIsNotNone(first["next_cursor"])
                second = planning_task_page(
                    connection,
                    PROJECTS,
                    project_id="project_mentat",
                    cursor=first["next_cursor"],
                    today=date(2026, 8, 30),
                )
                self.assertEqual(second["count"], 1)
                with self.assertRaisesRegex(ConversationPlanningError, "planning.cursor_invalid"):
                    planning_task_page(
                        connection,
                        PROJECTS,
                        project_id="project_other",
                        cursor=first["next_cursor"],
                        today=date(2026, 8, 30),
                    )
            finally:
                connection.close()
        with self.assertRaisesRegex(ConversationPlanningError, "planning.projects_ambiguous"):
            project_registry([
                {"id": "project_a", "name": "A", "status": "active", "aliases": ["Shared"]},
                {"id": "project_b", "name": "B", "status": "active", "aliases": ["shared"]},
            ])

    def test_exact_association_stays_stale_and_clearable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ConversationRepository(root)
            created = repository.create(agent_id=create_test_agent(root)).conversation
            connection = connect(root)
            try:
                TaskRepository(connection).insert_collection([task("task_context")])
            finally:
                connection.close()
            registry = project_registry(PROJECTS)
            updated, association = repository.set_planning_association(
                created.id,
                expected_revision=created.revision,
                project_id="project_mentat",
                task_id="task_context",
                validate_targets=lambda connection, project_id, task_id: validate_association_targets(
                    connection, registry, project_id, task_id
                ),
            )
            self.assertEqual(association.task_id, "task_context")
            ready = repository.resolve_planning_context(
                created.id,
                lambda connection, conversation, stored: planning_context_projection(
                    connection, PROJECTS, conversation, stored, today=date(2026, 8, 30)
                ),
            )
            self.assertEqual(ready["state"], "ready")

            connection = connect(root)
            try:
                snapshot = TaskRepository(connection).get("task_context")
                moved = dict(snapshot.document)
                moved["project"] = "Other"
                TaskRepository(connection).replace(moved, expected_revision=snapshot.revision)
            finally:
                connection.close()
            stale = repository.resolve_planning_context(
                created.id,
                lambda connection, conversation, stored: planning_context_projection(
                    connection, PROJECTS, conversation, stored, today=date(2026, 8, 30)
                ),
            )
            self.assertEqual(stale["state"], "project_mismatch")
            self.assertIsNone(stale["task"])
            cleared, association = repository.set_planning_association(
                created.id,
                expected_revision=updated.revision,
                project_id=None,
                task_id=None,
                validate_targets=lambda *_args: self.fail("clear must not resolve targets"),
            )
            self.assertIsNone(association)
            self.assertEqual(cleared.revision, updated.revision + 1)

    def test_association_guards_archived_and_queue_active_state(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ConversationRepository(root)
            created = repository.create(agent_id=create_test_agent(root)).conversation
            archived = repository.set_archived(
                created.id, expected_revision=created.revision, archived=True
            )
            with self.assertRaisesRegex(ConversationRepositoryConflict, "conversation.archived"):
                repository.set_planning_association(
                    created.id,
                    expected_revision=archived.revision,
                    project_id="project_mentat",
                    task_id=None,
                    validate_targets=lambda *_args: None,
                )
            cleared, association = repository.set_planning_association(
                created.id,
                expected_revision=archived.revision,
                project_id=None,
                task_id=None,
                validate_targets=lambda *_args: None,
            )
            self.assertIsNone(association)
            self.assertEqual(cleared.state, "archived")

            active = repository.set_archived(
                created.id, expected_revision=cleared.revision, archived=False
            )
            connection = connect(root)
            try:
                content = json.dumps(
                    {"schema_version": 1, "parts": [{"type": "text", "text": "Queued"}]},
                    separators=(",", ":"),
                    sort_keys=True,
                )
                digest = hashlib.sha256(b"queued-planning-guard").hexdigest()
                connection.execute(
                    "INSERT INTO mentat_conversation_messages "
                    "(id, conversation_id, sequence, role, state, content_json, content_bytes, run_id, revision, source_key, created_at, updated_at) "
                    "VALUES ('msg_planning_guard', ?, 1, 'user', 'accepted', ?, ?, NULL, 1, 'planning_guard', ?, ?)",
                    (created.id, content, len(content.encode("utf-8")), NOW, NOW),
                )
                connection.execute(
                    "INSERT INTO mentat_conversation_turns "
                    "(id, conversation_id, user_message_id, queue_ordinal, state, blocked_reason, latest_run_id, revision, attempt_count, idempotency_key_digest, request_digest, created_at, updated_at) "
                    "VALUES ('turn_planning_guard', ?, 'msg_planning_guard', 1, 'pending', NULL, NULL, 1, 0, ?, ?, ?, ?)",
                    (created.id, digest, digest, NOW, NOW),
                )
                connection.execute(
                    "UPDATE mentat_conversations SET next_message_sequence = 2, next_turn_ordinal = 2 WHERE id = ?",
                    (created.id,),
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaisesRegex(ConversationRepositoryConflict, "conversation.queue_active"):
                repository.set_planning_association(
                    created.id,
                    expected_revision=active.revision,
                    project_id="project_mentat",
                    task_id=None,
                    validate_targets=lambda *_args: None,
                )


if __name__ == "__main__":
    unittest.main()
