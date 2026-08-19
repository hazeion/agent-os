from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
import unittest
from unittest.mock import Mock, patch

import server
import data_backup_restore
import private_console_unit
import remote_hermes
import task_repository
from agent_console_attachments import bind_run_attachment, create_attachment
from mentat.cli import main as mentat_cli_main
from mentat_db import SCHEMA_VERSION, MentatDatabaseError, connect, database_path, transaction
from private_console_unit import (
    PrivateConsoleUnitError,
    capture_private_console_unit,
    materialize_private_console_unit,
)
from private_state import history_path
from run_repository import save_authoritative_run_summaries
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from task_repository import (
    TaskRepository,
    TaskRepositoryConflict,
    TaskRepositoryError,
    TaskRepositoryUnavailable,
    TaskRepositoryValidationError,
    confirm_task_compatible_export,
    confirm_task_legacy_export,
    ensure_task_sqlite_authority,
    export_tasks,
    import_tasks_from_preview,
    normalize_legacy_task_collection,
    normalize_task_collection,
    preview_task_compatible_export,
    preview_task_legacy_export,
    preview_task_sqlite_migration,
    read_authoritative_tasks,
    mutate_authoritative_tasks,
)


ROOT = Path(__file__).resolve().parent.parent
SERVER_SOURCE = (ROOT / "server.py").read_text(encoding="utf-8")
RUNTIME_CONFIG_SOURCE = (ROOT / "runtime_config.py").read_text(encoding="utf-8")
CLI_SOURCE = (ROOT / "mentat" / "cli.py").read_text(encoding="utf-8")


def task(
    identifier: str,
    *,
    status: str = "todo",
    dependencies: list[str] | None = None,
) -> dict:
    result = {
        "id": identifier,
        "title": f"Task {identifier}",
        "description": "A bounded migration fixture.",
        "project": "Mentat",
        "status": status,
        "priority": "medium",
        "assignee": None,
        "due_date": None,
        "source": "test",
        "tags": ["sqlite", "migration"],
        "review_required": False,
        "needs_attention": False,
        "created_at": "2026-08-18T09:00:00-07:00",
        "updated_at": "2026-08-18T09:05:00-07:00",
        "completed_at": "2026-08-18T09:05:00-07:00" if status == "completed" else None,
    }
    if dependencies is not None:
        result["depends_on"] = dependencies
    return result


def full_task() -> dict:
    result = task("task_full", dependencies=["task_parent"])
    result.update(
        {
            "assigned_agent_id": None,
            "planned_for_today": False,
            "manual_rank": 7,
            "estimated_minutes": 45,
            "scheduled_block": {
                "start": "2026-08-18T10:00:00-07:00",
                "end": "2026-08-18T10:45:00-07:00",
                "label": "Focus",
                "timezone": "America/Los_Angeles",
            },
            "recurrence": {
                "frequency": "weekly",
                "interval": 1,
                "weekdays": ["tue"],
                "count": 8,
            },
            "recurrence_parent_id": "task_parent",
            "reminders": [
                {
                    "id": "reminder_one",
                    "at": "2026-08-18T09:50:00-07:00",
                    "channel": "browser",
                    "enabled": True,
                }
            ],
            "subtasks": [
                {"id": "step_one", "title": "First step", "completed": False, "rank": 0}
            ],
            "calendar_links": [{"calendar_id": "primary", "event_id": "event_1"}],
            "note_links": [{"path": "Projects/Mentat.md", "title": "Mentat"}],
            "planning_state": "planned",
            "delegation": {
                "profile_id": "researcher",
                "state": "queued",
                "sync_state": "pending",
                "attempts": 0,
                "summary": "",
                "audit": [
                    {
                        "at": "2026-08-18T09:05:00-07:00",
                        "actor": "dashboard",
                        "event": "queued",
                    }
                ],
            },
            "compatibility_note": {"preserved": True, "labels": ["one", "two"]},
        }
    )
    return result


def write_tasks(root: Path, tasks: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "tasks.json"
    path.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    return path


def write_seed_root(root: Path, tasks: list[dict]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for fixture in (ROOT / "data").glob("*.json"):
        destination = root / fixture.name
        destination.write_bytes(fixture.read_bytes())
        if os.name != "nt":
            destination.chmod(0o600)
    return write_tasks(root, tasks)


def task_with_export_size(size: int) -> dict:
    candidate = task("task_size_boundary")
    candidate["description"] = ""
    base = task_repository._json_bytes(
        normalize_task_collection([candidate]),
        code="test.task_size_boundary",
    )
    padding = size - len(base)
    if padding < 0:
        raise ValueError("requested Task export size is too small")
    candidate["description"] = "x" * padding
    raw = task_repository._json_bytes(
        normalize_task_collection([candidate]),
        code="test.task_size_boundary",
    )
    if len(raw) != size:
        raise AssertionError("Task export boundary fixture is not exact")
    return candidate


class TaskRepositoryTests(unittest.TestCase):
    def test_legacy_timestamp_eras_upgrade_deterministically(self):
        fixtures = (
            ({"id": "sparse", "title": "Sparse"}, "1970-01-01T00:00:00+00:00"),
            (
                {
                    "id": "naive",
                    "title": "Naive",
                    "created_at": "2025-02-03T04:05:06",
                    "updated_at": "2025-02-03 04:06:07",
                    "completed_at": "2025-02-03T04:07:08.123456",
                    "status": "done",
                },
                "2025-02-03T04:05:06+00:00",
            ),
            (
                {
                    "id": "aware",
                    "title": "Aware",
                    "created_at": "2026-08-18T09:00:00-07:00",
                    "updated_at": "2026-08-18T09:05:00Z",
                },
                "2026-08-18T09:00:00-07:00",
            ),
        )
        for source, expected_created_at in fixtures:
            with self.subTest(task_id=source["id"]):
                normalized = normalize_legacy_task_collection([source])[0]
                self.assertEqual(normalized["created_at"], expected_created_at)
                self.assertIsNotNone(normalized["updated_at"])
                if source["id"] == "naive":
                    self.assertEqual(
                        normalized["completed_at"],
                        "2025-02-03T04:07:08.123456+00:00",
                    )

    def test_schema_seven_preserves_task_tables_and_refuses_forward_schema(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = connect(root)
            try:
                version = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                dependency_fks = connection.execute(
                    "PRAGMA foreign_key_list(mentat_task_dependencies)"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(SCHEMA_VERSION, 7)
            self.assertTrue(
                {
                    "mentat_tasks",
                    "mentat_task_tags",
                    "mentat_task_dependencies",
                    "mentat_task_store_state",
                }.issubset(tables)
            )
            self.assertEqual(
                {row[2] for row in dependency_fks},
                {"mentat_tasks"},
            )

            raw = sqlite3.connect(database_path(root))
            raw.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                (SCHEMA_VERSION + 1,),
            )
            raw.commit()
            raw.close()
            with self.assertRaisesRegex(MentatDatabaseError, "newer"):
                connect(root)

    def test_deferred_foreign_key_commit_failure_rolls_back_transaction(self):
        with TemporaryDirectory() as tmpdir:
            connection = connect(Path(tmpdir))
            try:
                TaskRepository(connection).insert_collection([task("task_a")])
                with self.assertRaises(sqlite3.IntegrityError):
                    with transaction(connection, immediate=True):
                        connection.execute(
                            "INSERT INTO mentat_task_dependencies("
                            "task_id, dependency_task_id, ordinal) VALUES (?, ?, ?)",
                            ("task_a", "task_missing", 0),
                        )
                self.assertFalse(connection.in_transaction)
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_task_dependencies"
                    ).fetchone()[0],
                    0,
                )
            finally:
                connection.close()

    def test_schema_four_preview_is_read_only_and_normal_open_migrates_once(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = connect(root)
            try:
                with transaction(connection, immediate=True):
                    for name in (
                        "idx_mentat_task_dependencies_target",
                        "idx_mentat_tasks_assigned_agent",
                        "idx_mentat_tasks_project_order",
                        "idx_mentat_tasks_status_order",
                    ):
                        connection.execute(f"DROP INDEX {name}")
                    connection.execute("DROP TABLE mentat_task_dependencies")
                    connection.execute("DROP TABLE mentat_task_tags")
                    connection.execute("DROP TABLE mentat_agent_events")
                    connection.execute("DROP TABLE mentat_dispatch_reservations")
                    connection.execute("DROP TABLE mentat_task_dispatch_heads")
                    connection.execute("DROP TABLE mentat_runs")
                    connection.execute("DROP TABLE mentat_run_store_state")
                    connection.execute("DROP TABLE mentat_tasks")
                    connection.execute("DROP TABLE mentat_task_store_state")
                    connection.execute("DELETE FROM schema_migrations WHERE version IN (5, 6, 7)")
            finally:
                connection.close()
            path = database_path(root)
            before = path.read_bytes()
            write_tasks(root, [task("task_a")])
            sidecars_before = {
                suffix: (
                    Path(f"{path}{suffix}").stat().st_ino,
                    Path(f"{path}{suffix}").read_bytes(),
                )
                if os.path.lexists(f"{path}{suffix}")
                else None
                for suffix in ("-wal", "-shm")
            }
            preview = preview_task_sqlite_migration(root)
            self.assertEqual(preview.destination.state, "requires_schema_migration")
            self.assertEqual(preview.destination.schema_version, 4)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(
                {
                    suffix: (
                        Path(f"{path}{suffix}").stat().st_ino,
                        Path(f"{path}{suffix}").read_bytes(),
                    )
                    if os.path.lexists(f"{path}{suffix}")
                    else None
                    for suffix in ("-wal", "-shm")
                },
                sidecars_before,
            )

            migrated = connect(root)
            try:
                self.assertEqual(
                    migrated.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                    SCHEMA_VERSION,
                )
                self.assertEqual(TaskRepository(migrated).count(), 0)
            finally:
                migrated.close()
            reopened = connect(root)
            reopened.close()

            tampered = sqlite3.connect(path)
            tampered.execute("DROP INDEX idx_mentat_tasks_status_order")
            tampered.commit()
            tampered.close()
            with self.assertRaisesRegex(TaskRepositoryError, "schema_unsupported"):
                preview_task_sqlite_migration(root)

    def test_task_schema_fingerprint_preserves_whitespace_inside_literals(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = connect(root)
            connection.execute("PRAGMA writable_schema = ON")
            connection.execute(
                "UPDATE sqlite_master SET sql = replace(sql, ?, ?) WHERE name = ?",
                ("'in progress'", "'inprogress'", "mentat_tasks"),
            )
            connection.execute("PRAGMA writable_schema = OFF")
            connection.commit()
            connection.close()
            reopened = sqlite3.connect(database_path(root))
            try:
                with self.assertRaisesRegex(TaskRepositoryError, "schema_unsupported"):
                    TaskRepository(reopened)
            finally:
                reopened.close()

    def test_repository_round_trips_full_planning_order_nulls_and_extensions(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            expected = [task("task_parent"), full_task()]
            connection = connect(root)
            try:
                with transaction(connection, immediate=True):
                    repository = TaskRepository(connection)
                    repository.insert_collection(expected)
                reopened = TaskRepository(connection)
                self.assertEqual(reopened.list_tasks(), list(normalize_task_collection(expected)))
                self.assertEqual(reopened.count(), 2)
                export_one = reopened.export()
                export_two = reopened.export()
                self.assertEqual(export_one.raw, export_two.raw)
                self.assertEqual(export_one.sha256, export_two.sha256)
                self.assertNotIn(b'"revision"', export_one.raw)
            finally:
                connection.close()

            reopened_connection = connect(root)
            try:
                self.assertEqual(
                    TaskRepository(reopened_connection).export().raw,
                    export_one.raw,
                )
            finally:
                reopened_connection.close()

    def test_repository_revisions_reject_stale_replacement_without_partial_writes(self):
        with TemporaryDirectory() as tmpdir:
            connection = connect(Path(tmpdir))
            try:
                repository = TaskRepository(connection)
                repository.insert_collection([task("task_parent"), full_task()])
                initial = repository.get("task_full")
                self.assertEqual(initial.revision, 1)

                replacement = deepcopy(initial.document)
                replacement["title"] = "Revised Task"
                replacement["updated_at"] = "2026-08-18T09:10:00-07:00"
                revised = repository.replace(replacement, expected_revision=1)
                self.assertEqual(revised.revision, 2)
                self.assertEqual(revised.document["title"], "Revised Task")

                stale = deepcopy(revised.document)
                stale["description"] = "This stale write must not land."
                with self.assertRaisesRegex(TaskRepositoryConflict, "revision_conflict"):
                    repository.replace(stale, expected_revision=1)
                self.assertEqual(repository.get("task_full"), revised)

                invalid_graph = deepcopy(revised.document)
                invalid_graph["depends_on"] = ["task_missing"]
                with self.assertRaises(TaskRepositoryValidationError):
                    repository.replace(invalid_graph, expected_revision=2)
                self.assertEqual(repository.get("task_full"), revised)
            finally:
                connection.close()

    def test_get_keeps_revision_and_document_in_one_read_snapshot(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first_connection = connect(root)
            second_connection = connect(root)
            try:
                first = TaskRepository(first_connection)
                second = TaskRepository(second_connection)
                first.insert_collection([task("task_a")])
                original_list = first._list_tasks

                def concurrent_update():
                    replacement = deepcopy(second.get("task_a").document)
                    replacement["title"] = "Concurrent revision"
                    replacement["updated_at"] = "2026-08-18T09:11:00-07:00"
                    second.replace(replacement, expected_revision=1)
                    return original_list()

                with patch.object(first, "_list_tasks", side_effect=concurrent_update):
                    snapshot = first.get("task_a")
                self.assertEqual(snapshot.revision, 1)
                self.assertEqual(snapshot.document["title"], "Task task_a")
                self.assertEqual(second.get("task_a").revision, 2)
            finally:
                second_connection.close()
                first_connection.close()

    def test_replace_returns_its_own_committed_revision_after_later_writer(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first_connection = connect(root)
            second_connection = connect(root)
            try:
                first = TaskRepository(first_connection)
                second = TaskRepository(second_connection)
                first.insert_collection([task("task_a")])
                original_mutation = first._mutation

                @contextmanager
                def delayed_return():
                    with original_mutation():
                        yield
                    later = deepcopy(second.get("task_a").document)
                    later["title"] = "Later writer"
                    later["updated_at"] = "2026-08-18T09:12:00-07:00"
                    second.replace(later, expected_revision=2)

                replacement = deepcopy(first.get("task_a").document)
                replacement["title"] = "First writer"
                replacement["updated_at"] = "2026-08-18T09:11:00-07:00"
                with patch.object(first, "_mutation", delayed_return):
                    result = first.replace(replacement, expected_revision=1)
                self.assertEqual(result.revision, 2)
                self.assertEqual(result.document["title"], "First writer")
                self.assertEqual(second.get("task_a").revision, 3)
                self.assertEqual(second.get("task_a").document["title"], "Later writer")
            finally:
                second_connection.close()
                first_connection.close()

    def test_collection_validation_rejects_graph_duplicates_bounds_and_private_extensions(self):
        invalid = (
            [task("task_a"), task("task_a")],
            [task("task_a", dependencies=["task_missing"])],
            [task("task_a", dependencies=["task_b"]), task("task_b", dependencies=["task_a"])],
            [{**task("task_a"), "tags": ["same", "same"]}],
            [{**task("task_a"), "credential_path": "/tmp/key"}],
            [{**task("task_a"), "compatibility_note": {"token": "secret"}}],
            [{**task("task_a"), "created_at": "not-a-time"}],
        )
        for tasks in invalid:
            with self.subTest(tasks=tasks), self.assertRaises(TaskRepositoryValidationError):
                normalize_task_collection(tasks)

    def test_collection_accepts_live_tag_date_edges_and_deep_acyclic_graph(self):
        many_tags = [f"tag-{index}" for index in range(101)]
        edge = {**task("task_edge"), "tags": many_tags, "due_date": "2026-99-99"}
        self.assertEqual(normalize_task_collection([edge])[0]["tags"], many_tags)
        with TemporaryDirectory() as tmpdir:
            connection = connect(Path(tmpdir))
            try:
                repository = TaskRepository(connection)
                repository.insert_collection([edge])
                self.assertEqual(repository.list_tasks(), [edge])
            finally:
                connection.close()
        chain = [
            task(
                f"task_{index}",
                dependencies=[] if index == 0 else [f"task_{index - 1}"],
            )
            for index in range(1_200)
        ]
        self.assertEqual(len(normalize_task_collection(chain)), 1_200)

    def test_failed_insert_rolls_back_every_table(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = connect(root)
            try:
                with self.assertRaises(sqlite3.IntegrityError):
                    with transaction(connection, immediate=True):
                        repository = TaskRepository(connection)
                        repository.insert_collection([task("task_a")])
                        connection.execute(
                            "INSERT INTO mentat_task_tags(task_id, ordinal, tag) "
                            "VALUES ('task_a', 99, 'sqlite')"
                        )
                self.assertEqual(TaskRepository(connection).count(), 0)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_task_tags").fetchone()[0],
                    0,
                )
            finally:
                connection.close()

    def test_repository_insert_is_atomic_without_caller_transaction(self):
        with TemporaryDirectory() as tmpdir:
            connection = connect(Path(tmpdir))
            try:
                repository = TaskRepository(connection)
                with (
                    patch.object(
                        repository,
                        "_insert_children",
                        side_effect=RuntimeError("injected failure"),
                    ),
                    self.assertRaises(RuntimeError),
                ):
                    repository.insert_collection([task("task_a"), task("task_b")])
                self.assertEqual(repository.count(), 0)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_task_tags").fetchone()[0],
                    0,
                )
            finally:
                connection.close()

    def test_repository_rejects_unexpected_task_trigger_before_mutation(self):
        with TemporaryDirectory() as tmpdir:
            connection = connect(Path(tmpdir))
            try:
                repository = TaskRepository(connection)
                connection.execute(
                    "CREATE TRIGGER unexpected_task_trigger "
                    "BEFORE INSERT ON mentat_tasks "
                    "BEGIN DELETE FROM blobs; END"
                )
                with self.assertRaisesRegex(TaskRepositoryError, "schema_unsupported"):
                    repository.insert_collection([task("task_a")])
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_tasks").fetchone()[0],
                    0,
                )
            finally:
                connection.close()

    def test_preview_is_exact_bounded_and_creates_no_database_or_sidecars(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("task_a")])
            before = source.read_bytes()
            inventory_before = {path.name for path in root.iterdir()}
            preview_one = preview_task_sqlite_migration(root)
            preview_two = preview_task_sqlite_migration(root)
            summary = preview_one.public_summary()
            self.assertEqual(preview_one, preview_two)
            self.assertEqual(summary["status"], "ready")
            self.assertEqual(summary["source"]["task_ids"], ["task_a"])
            self.assertEqual(summary["destination"]["state"], "missing")
            self.assertFalse(summary["writes_performed"])
            self.assertNotIn(os.fspath(root), json.dumps(summary))
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual({path.name for path in root.iterdir()}, inventory_before)
            self.assertFalse(os.path.lexists(database_path(root)))
            self.assertFalse(os.path.lexists(f"{database_path(root)}-wal"))
            self.assertFalse(os.path.lexists(f"{database_path(root)}-shm"))

    def test_preview_supports_uri_special_characters_without_writes(self):
        with TemporaryDirectory() as tmpdir:
            segment = "data # % segment" if os.name == "nt" else "data ?# % segment"
            root = Path(tmpdir) / segment
            write_tasks(root, [task("task_uri")])
            connection = connect(root)
            connection.close()
            before = {
                path.name: path.read_bytes()
                for path in database_path(root).parent.iterdir()
                if path.is_file()
            }
            preview = preview_task_sqlite_migration(root)
            after = {
                path.name: path.read_bytes()
                for path in database_path(root).parent.iterdir()
                if path.is_file()
            }
            self.assertEqual(preview.destination.state, "empty")
            self.assertEqual(after, before)

    @unittest.skipIf(
        os.name == "nt",
        "Windows does not permit replacing an open source file",
    )
    def test_preview_rejects_atomic_source_replacement_during_read(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("task_old")])
            original_read = os.read
            replaced = False

            def replace_after_read(descriptor, maximum):
                nonlocal replaced
                chunk = original_read(descriptor, maximum)
                if not replaced:
                    replaced = True
                    replacement = root / "replacement.json"
                    replacement.write_text(
                        json.dumps([task("task_new")]) + "\n",
                        encoding="utf-8",
                    )
                    if os.name != "nt":
                        replacement.chmod(0o600)
                    os.replace(replacement, source)
                return chunk

            with (
                patch("task_repository.os.read", side_effect=replace_after_read),
                self.assertRaises(TaskRepositoryUnavailable),
            ):
                preview_task_sqlite_migration(root)
            self.assertEqual(json.loads(source.read_text(encoding="utf-8"))[0]["id"], "task_new")
            self.assertFalse(os.path.lexists(database_path(root)))

    def test_preview_reads_committed_live_wal_without_mutating_database_files(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("task_a")])
            connection = connect(root)
            try:
                with transaction(connection, immediate=True):
                    TaskRepository(connection).insert_collection([task("task_a")])
                path = database_path(root)
                candidates = (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
                before = {
                    candidate.name: (
                        candidate.stat().st_ino,
                        candidate.read_bytes(),
                    )
                    for candidate in candidates
                    if candidate.exists()
                }
                preview = preview_task_sqlite_migration(root)
                after = {
                    candidate.name: (
                        candidate.stat().st_ino,
                        candidate.read_bytes(),
                    )
                    for candidate in candidates
                    if candidate.exists()
                }
                self.assertEqual(preview.status, "blocked")
                self.assertEqual(preview.destination.state, "occupied")
                self.assertEqual(preview.destination.task_count, 1)
                self.assertEqual(after, before)
            finally:
                connection.close()

    @unittest.skipIf(os.name == "nt", "POSIX link and mode contract")
    def test_preview_rejects_broad_and_linked_sources_without_writes(self):
        for kind in ("broad", "symlink", "hardlink"):
            with self.subTest(kind=kind), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                source = write_tasks(root, [task("task_a")])
                if kind == "broad":
                    source.chmod(0o644)
                else:
                    original = root / "original.json"
                    source.rename(original)
                    if kind == "symlink":
                        source.symlink_to(original)
                    else:
                        os.link(original, source)
                with self.assertRaises(TaskRepositoryUnavailable):
                    preview_task_sqlite_migration(root)
                self.assertFalse(os.path.lexists(database_path(root)))

    def test_import_binds_exact_source_and_requires_empty_destination(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("task_a")])
            preview = preview_task_sqlite_migration(root)
            source.write_text(source.read_text(encoding="utf-8") + " ", encoding="utf-8")
            if os.name != "nt":
                source.chmod(0o600)
            with self.assertRaisesRegex(TaskRepositoryConflict, "source_changed"):
                import_tasks_from_preview(root, preview)
            connection = connect(root)
            try:
                self.assertEqual(TaskRepository(connection).count(), 0)
            finally:
                connection.close()

            write_tasks(root, [task("task_a")])
            current = preview_task_sqlite_migration(root)
            exported = import_tasks_from_preview(root, current)
            self.assertEqual(exported.task_count, 1)
            occupied_preview = preview_task_sqlite_migration(root)
            self.assertEqual(occupied_preview.status, "blocked")
            with self.assertRaises(TaskRepositoryConflict):
                import_tasks_from_preview(root, occupied_preview)

    def test_import_binds_exact_destination_preview(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("task_a")])
            missing_preview = preview_task_sqlite_migration(root)
            connection = connect(root)
            connection.close()
            with self.assertRaisesRegex(TaskRepositoryConflict, "destination_changed"):
                import_tasks_from_preview(root, missing_preview)
            current = preview_task_sqlite_migration(root)
            self.assertEqual(current.destination.state, "empty")
            self.assertEqual(import_tasks_from_preview(root, current).task_count, 1)

    def test_export_is_deterministic_read_only_and_stable_across_reopen(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("task_a"), task("task_b", dependencies=[])])
            preview = preview_task_sqlite_migration(root)
            imported = import_tasks_from_preview(root, preview)
            before = database_path(root).stat()
            exported = export_tasks(root)
            after = database_path(root).stat()
            self.assertEqual(imported.raw, exported.raw)
            self.assertEqual(imported.sha256, exported.sha256)
            self.assertEqual(json.loads(exported.raw), [task("task_a"), task("task_b", dependencies=[])])
            self.assertEqual((before.st_dev, before.st_ino), (after.st_dev, after.st_ino))

    def test_private_snapshot_round_trip_retains_tasks_and_rejects_semantic_corruption(self):
        with TemporaryDirectory() as tmpdir:
            source_root = Path(tmpdir) / "source"
            write_tasks(source_root, [task("task_parent"), full_task()])
            ensure_task_sqlite_authority(source_root)
            unit = capture_private_console_unit(source_root)
            self.assertEqual(unit.task_count, 2)

            restored = Path(tmpdir) / "restored"
            (restored / "private").mkdir(parents=True, mode=0o700)
            stage = materialize_private_console_unit(
                restored,
                unit,
                restored / "private" / "restore-stage",
            )
            stage.rename(restored / "private" / "console")
            connection = connect(restored)
            try:
                self.assertEqual(
                    TaskRepository(connection).list_tasks(),
                    list(normalize_task_collection([task("task_parent"), full_task()])),
                )
            finally:
                connection.close()

            corrupt_path = database_path(restored)
            corrupt = sqlite3.connect(corrupt_path)
            corrupt.execute("PRAGMA foreign_keys = ON")
            corrupt.execute(
                "INSERT INTO mentat_task_dependencies("
                "task_id, dependency_task_id, ordinal) VALUES (?, ?, ?)",
                ("task_parent", "task_full", 0),
            )
            corrupt.commit()
            corrupt.close()
            with self.assertRaises(PrivateConsoleUnitError):
                capture_private_console_unit(restored)

            corrupt = sqlite3.connect(corrupt_path)
            corrupt.execute(
                "DELETE FROM mentat_task_dependencies WHERE task_id = ?",
                ("task_parent",),
            )
            corrupt.execute(
                "UPDATE mentat_tasks SET nested_planning_json = ? WHERE id = ?",
                ('{"unknown":true}', "task_full"),
            )
            corrupt.commit()
            corrupt.close()
            with self.assertRaises(PrivateConsoleUnitError):
                capture_private_console_unit(restored)

    def test_production_cutover_is_reachable_without_a_confirmation_passthrough(self):
        for source in (SERVER_SOURCE, RUNTIME_CONFIG_SOURCE, CLI_SOURCE):
            self.assertNotIn("import_tasks_from_preview", source)
            self.assertNotIn("confirm-task-sqlite-migration", source)
        self.assertIn("--preview-task-sqlite-migration", RUNTIME_CONFIG_SOURCE)
        self.assertIn('"task-migration"', CLI_SOURCE)
        self.assertIn("ensure_task_sqlite_authority", SERVER_SOURCE)

    def test_cutover_imports_and_receipts_atomically_then_ignores_stale_source(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("task_a")])
            receipt = ensure_task_sqlite_authority(root)
            self.assertEqual(receipt.source_task_count, 1)
            self.assertEqual([item["id"] for item in read_authoritative_tasks(root)], ["task_a"])

            source.write_text("not json\n", encoding="utf-8")
            if os.name != "nt":
                source.chmod(0o600)
            second = ensure_task_sqlite_authority(root)
            self.assertEqual(second, receipt)
            self.assertEqual([item["id"] for item in read_authoritative_tasks(root)], ["task_a"])
            preview = preview_task_sqlite_migration(root)
            self.assertEqual(preview.status, "already_cut_over")
            self.assertIsNone(preview.source)

    def test_empty_cutover_never_reimports_a_later_seed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [])
            ensure_task_sqlite_authority(root)
            write_tasks(root, [task("stale")])
            ensure_task_sqlite_authority(root)
            self.assertEqual(read_authoritative_tasks(root), [])

    def test_collection_mutation_preserves_revisions_and_rolls_back_invalid_state(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("task_a"), task("task_b")])
            ensure_task_sqlite_authority(root)

            def change(tasks):
                tasks[1] = {**tasks[1], "title": "Changed"}
                tasks.append(task("task_c"))
                return list(tasks), "done"

            self.assertEqual(mutate_authoritative_tasks(root, change), "done")
            connection = connect(root)
            try:
                revisions = {
                    row["id"]: row["revision"]
                    for row in connection.execute(
                        "SELECT id, revision FROM mentat_tasks ORDER BY id"
                    )
                }
            finally:
                connection.close()
            self.assertEqual(revisions, {"task_a": 1, "task_b": 2, "task_c": 1})

            mutate_authoritative_tasks(
                root,
                lambda tasks: ([tasks[1], tasks[0], tasks[2]], None),
            )
            connection = connect(root)
            try:
                reordered_revisions = {
                    row["id"]: row["revision"]
                    for row in connection.execute(
                        "SELECT id, revision FROM mentat_tasks ORDER BY id"
                    )
                }
            finally:
                connection.close()
            self.assertEqual(
                reordered_revisions,
                {"task_a": 2, "task_b": 3, "task_c": 1},
            )

            with self.assertRaises(TaskRepositoryValidationError):
                mutate_authoritative_tasks(
                    root,
                    lambda tasks: ([{**tasks[0], "id": tasks[1]["id"]}, *tasks[1:]], None),
                )
            self.assertEqual(
                [item["id"] for item in read_authoritative_tasks(root)],
                ["task_b", "task_a", "task_c"],
            )

    def test_cutover_failure_rolls_back_tasks_and_authority_receipt_together(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("task_a")])
            with patch.object(
                TaskRepository,
                "claim_authority",
                side_effect=TaskRepositoryError("injected_failure"),
            ):
                with self.assertRaisesRegex(TaskRepositoryError, "injected_failure"):
                    ensure_task_sqlite_authority(root)
            connection = connect(root)
            try:
                repository = TaskRepository(connection)
                self.assertEqual(repository.count(), 0)
                self.assertIsNone(repository.authority_receipt())
            finally:
                connection.close()

    def test_server_task_helpers_never_use_json_after_cutover(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("task_a")])
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "CONFIGURED_DATA_DIR", root),
            ):
                server.ensure_task_authority()
                stale = source.read_bytes()
                source.write_bytes(b"not json\n")
                if os.name != "nt":
                    source.chmod(0o600)
                with (
                    patch.object(
                        server,
                        "store_read_json",
                        side_effect=AssertionError("legacy Task JSON read"),
                    ),
                    patch.object(
                        server,
                        "store_update_json",
                        side_effect=AssertionError("legacy Task JSON write"),
                    ),
                ):
                    self.assertEqual(server.read_json_file("tasks.json", [])[0]["id"], "task_a")
                    result = server.update_json_file(
                        "tasks.json",
                        [],
                        lambda tasks: ([{**tasks[0], "title": "SQLite only"}], "ok"),
                    )
                    self.assertEqual(result, "ok")
                    self.assertEqual(
                        server.read_json_file("tasks.json", [])[0]["title"],
                        "SQLite only",
                    )
                self.assertNotEqual(source.read_bytes(), stale)
                self.assertEqual(source.read_bytes(), b"not json\n")

    def test_live_server_helpers_fail_closed_without_invoking_cutover(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("stale")])
            with (
                patch.object(server, "DATA_DIR", root),
                patch.object(server, "CONFIGURED_DATA_DIR", root),
                patch.object(
                    task_repository,
                    "_read_source_snapshot",
                    side_effect=AssertionError("live fallback read"),
                ),
            ):
                read_result = server.read_json_file("tasks.json", [])
                write_result, status = server.update_json_file(
                    "tasks.json",
                    [],
                    lambda tasks: (tasks, None),
                )
            self.assertIn("authority_missing", read_result["error"])
            self.assertEqual(status, 503)
            self.assertIn("authority_missing", write_result["error"])

    def test_cutover_rechecks_source_adjacent_to_receipt_commit(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("task_a")])
            read_snapshot = task_repository._read_source_snapshot
            calls = 0

            def replace_after_first_read(*args, **kwargs):
                nonlocal calls
                snapshot = read_snapshot(*args, **kwargs)
                calls += 1
                if calls == 1:
                    source.write_text(
                        json.dumps([task("task_changed")]),
                        encoding="utf-8",
                    )
                    if os.name != "nt":
                        source.chmod(0o600)
                return snapshot

            with patch.object(
                task_repository,
                "_read_source_snapshot",
                side_effect=replace_after_first_read,
            ):
                with self.assertRaisesRegex(TaskRepositoryConflict, "source_changed"):
                    ensure_task_sqlite_authority(root)
            connection = connect(root)
            try:
                repository = TaskRepository(connection)
                self.assertEqual(repository.count(), 0)
                self.assertIsNone(repository.authority_receipt())
            finally:
                connection.close()

    @unittest.skipIf(os.name == "nt", "Windows prevents replacing an open database")
    def test_cutover_rejects_database_path_replacement_before_commit(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("task_a")])
            path = database_path(root)
            original_verify = task_repository._DatabaseIdentityGuard.verify
            replaced = False

            def replace_then_verify(guard, expected):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    raw = path.read_bytes()
                    displaced = path.with_name("displaced.sqlite3")
                    os.replace(path, displaced)
                    path.write_bytes(raw)
                    path.chmod(0o600)
                return original_verify(guard, expected)

            with patch.object(
                task_repository._DatabaseIdentityGuard,
                "verify",
                autospec=True,
                side_effect=replace_then_verify,
            ):
                with self.assertRaisesRegex(
                    TaskRepositoryUnavailable,
                    "database_changed",
                ):
                    ensure_task_sqlite_authority(root)
            self.assertTrue(replaced)
            with self.assertRaises(TaskRepositoryError):
                read_authoritative_tasks(root)

    @unittest.skipIf(os.name == "nt", "Windows prevents replacing an open database")
    def test_cutover_rejects_database_replacement_during_open_handoff(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("task_a")])
            path = database_path(root)
            real_open = task_repository.connect_database_with_identity
            displaced = path.with_name("handoff-displaced.sqlite3")

            def replace_after_open(data_root):
                connection, identities = real_open(data_root)
                raw = path.read_bytes()
                os.replace(path, displaced)
                path.write_bytes(raw)
                path.chmod(0o600)
                return connection, identities

            with patch.object(
                task_repository,
                "connect_database_with_identity",
                side_effect=replace_after_open,
            ):
                with self.assertRaisesRegex(
                    TaskRepositoryUnavailable,
                    "database_changed",
                ):
                    ensure_task_sqlite_authority(root)
            self.assertTrue(displaced.exists())
            with self.assertRaises(TaskRepositoryError):
                read_authoritative_tasks(root)

    def test_connection_boundary_translates_unsafe_database_failures(self):
        for kind in ("newer", "malformed", "redirected"):
            with self.subTest(kind=kind), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                write_tasks(root, [])
                path = database_path(root)
                if kind == "newer":
                    connection = connect(root)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (999, 1)"
                    )
                    connection.commit()
                    connection.close()
                elif kind == "malformed":
                    connection = connect(root)
                    connection.close()
                    path.write_bytes(b"not a sqlite database")
                    if os.name != "nt":
                        path.chmod(0o600)
                else:
                    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    outside = root / "outside.sqlite3"
                    outside.write_bytes(b"not a sqlite database")
                    if os.name != "nt":
                        outside.chmod(0o600)
                    try:
                        path.symlink_to(outside)
                    except OSError as exc:
                        self.skipTest(f"database symlink unavailable: {exc}")
                with self.assertRaisesRegex(
                    TaskRepositoryUnavailable,
                    "task_repository.unavailable",
                ):
                    ensure_task_sqlite_authority(root)

    def test_concurrent_collection_mutations_do_not_lose_tasks(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [])
            ensure_task_sqlite_authority(root)
            barrier = Barrier(8)
            errors: list[BaseException] = []

            def append_task(index: int) -> None:
                try:
                    barrier.wait(timeout=5)
                    mutate_authoritative_tasks(
                        root,
                        lambda tasks: ([*tasks, task(f"task_{index}")], None),
                    )
                except BaseException as exc:  # pragma: no cover - asserted below
                    errors.append(exc)

            threads = [Thread(target=append_task, args=(index,)) for index in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=10)
            self.assertFalse(errors)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(
                {item["id"] for item in read_authoritative_tasks(root)},
                {f"task_{index}" for index in range(8)},
            )

    def test_authoritative_repository_remains_deterministically_exportable(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            exported = export_tasks(root)
            self.assertEqual(exported.task_count, 1)
            self.assertEqual(exported.payload(), [task("task_a")])

    def test_offline_legacy_export_is_state_bound_and_cli_accessible(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            mutate_authoritative_tasks(
                root,
                lambda tasks: ([*tasks, task("task_b")], None),
            )
            preview = preview_task_legacy_export(root)
            self.assertEqual(preview.export.task_count, 2)
            self.assertFalse(preview.public_summary()["writes_performed"])
            source.write_text("[]\n", encoding="utf-8")
            if os.name != "nt":
                source.chmod(0o600)
            with self.assertRaisesRegex(
                TaskRepositoryConflict,
                "confirmation_invalid",
            ):
                confirm_task_legacy_export(root, preview.confirmation_token)

            source.write_bytes(b"{malformed stale json\n")
            if os.name != "nt":
                source.chmod(0o600)
            current = preview_task_legacy_export(root)
            result = confirm_task_legacy_export(root, current.confirmation_token)
            self.assertEqual(result["status"], "exported")
            self.assertEqual(
                [item["id"] for item in json.loads(source.read_text(encoding="utf-8"))],
                ["task_a", "task_b"],
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = mentat_cli_main(
                    ["task-export", "--data-dir", str(root)]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["task_count"], 2)
            self.assertNotIn(os.fspath(root), output.getvalue())

            with patch("private_state.mentat_server_active", return_value=True):
                with self.assertRaisesRegex(
                    TaskRepositoryConflict,
                    "server_active",
                ):
                    preview_task_legacy_export(root)

            if os.name != "nt":
                outside = root / "outside.json"
                outside.write_text("[]\n", encoding="utf-8")
                outside.chmod(0o600)
                source.unlink()
                source.symlink_to(outside)
                with self.assertRaisesRegex(
                    TaskRepositoryUnavailable,
                    "destination_unavailable",
                ):
                    preview_task_legacy_export(root)
                self.assertEqual(outside.read_text(encoding="utf-8"), "[]\n")

    def test_offline_export_requires_committed_sqlite_authority(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("legacy_task")])
            before = source.read_bytes()
            connection = connect(root)
            connection.close()
            with self.assertRaisesRegex(
                TaskRepositoryUnavailable,
                "authority_missing",
            ):
                preview_task_legacy_export(root)
            self.assertEqual(source.read_bytes(), before)

    def test_compatible_export_creates_runnable_schema_five_sibling(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            source = write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            mutate_authoritative_tasks(
                root,
                lambda tasks: ([*tasks, task("task_b")], None),
            )
            source_before = source.read_bytes()
            preview = preview_task_compatible_export(root)
            self.assertEqual(preview.target_name, "data-schema5-downgrade")
            self.assertFalse(preview.public_summary()["writes_performed"])
            mutate_authoritative_tasks(
                root,
                lambda tasks: ([*tasks, task("task_c")], None),
            )
            with self.assertRaisesRegex(
                TaskRepositoryConflict,
                "confirmation_invalid",
            ):
                confirm_task_compatible_export(root, preview.confirmation_token)
            self.assertFalse(root.with_name(preview.target_name).exists())
            preview = preview_task_compatible_export(root)
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = mentat_cli_main(
                    [
                        "task-export",
                        "--data-dir",
                        str(root),
                        "--compatible-root",
                        "--confirm",
                        preview.confirmation_token,
                    ]
                )
            result = json.loads(output.getvalue())
            target = root.with_name(preview.target_name)
            self.assertEqual(exit_code, 0)
            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "exported")
            self.assertTrue(target.is_dir())
            self.assertEqual(source.read_bytes(), source_before)
            self.assertEqual(
                [
                    item["id"]
                    for item in json.loads(
                        (target / "tasks.json").read_text(encoding="utf-8")
                    )
                ],
                ["task_a", "task_b", "task_c"],
            )
            downgraded = sqlite3.connect(database_path(target))
            try:
                version = downgraded.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                self.assertEqual(version, 5)
                self.assertIsNone(
                    downgraded.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE name = 'mentat_task_store_state'"
                    ).fetchone()
                )
                self.assertEqual(
                    TaskRepository(
                        downgraded,
                        allow_pre_authority_schema=True,
                    ).count(),
                    0,
                )
            finally:
                downgraded.close()

            legacy_tasks = json.loads(
                (target / "tasks.json").read_text(encoding="utf-8")
            )
            legacy_tasks.append(task("task_d"))
            write_tasks(target, legacy_tasks)
            ensure_task_sqlite_authority(target)
            self.assertEqual(
                [item["id"] for item in read_authoritative_tasks(target)],
                ["task_a", "task_b", "task_c", "task_d"],
            )
            self.assertEqual(
                read_authoritative_tasks(root)[-1]["id"],
                "task_c",
            )
            with self.assertRaisesRegex(
                TaskRepositoryConflict,
                "compatible_target_exists",
            ):
                preview_task_compatible_export(root)

    def test_schema_five_downgrade_filters_blobs_for_runs_omitted_from_projection(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            ensure_run_sqlite_authority(root, history_path(root))
            attachment = create_attachment(
                root, original_name="older.txt", content=b"older run attachment"
            )
            bind_run_attachment(root, attachment["id"], "run_older_projection")
            save_authoritative_run_summaries(
                root,
                [
                    {
                        "id": "run_newer_projection",
                        "runtime_type": "hermes",
                        "transport_mode": "local",
                        "connection_binding_id": "local-default",
                        "status": "completed",
                        "response": "newer",
                        "created_at": "2026-08-18T13:00:00+00:00",
                        "updated_at": "2026-08-18T13:01:00+00:00",
                        "completed_at": "2026-08-18T13:01:00+00:00",
                        "events": [],
                    },
                    {
                        "id": "run_older_projection",
                        "runtime_type": "hermes",
                        "transport_mode": "local",
                        "connection_binding_id": "local-default",
                        "status": "completed",
                        "response": "older",
                        "created_at": "2026-08-18T12:00:00+00:00",
                        "updated_at": "2026-08-18T12:01:00+00:00",
                        "completed_at": "2026-08-18T12:01:00+00:00",
                        "attachments": [attachment],
                        "events": [],
                    },
                ],
            )
            with patch.object(private_console_unit, "MAX_HISTORY_BYTES", 128):
                unit = capture_private_console_unit(root)
            self.assertEqual(json.loads(unit.history_raw)["runs"], [])

            downgraded = task_repository._schema5_private_unit(unit)

        self.assertEqual(downgraded.blobs, ())

    def test_export_modes_preserve_the_exact_maximum_document_size(self):
        maximum = task_repository.MAX_EXPORT_BYTES
        maximum_task = task_with_export_size(maximum)
        almost_maximum = task_with_export_size(maximum - 1)
        self.assertEqual(
            len(
                task_repository._json_bytes(
                    normalize_task_collection([almost_maximum]),
                    code="test.task_size_boundary",
                )
            ),
            maximum - 1,
        )
        oversized = deepcopy(maximum_task)
        oversized["description"] += "x"
        with self.assertRaisesRegex(
            TaskRepositoryValidationError,
            "tasks.too_large",
        ):
            normalize_task_collection([oversized])

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            source = write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            mutate_authoritative_tasks(root, lambda _tasks: ([maximum_task], None))
            exported = export_tasks(root, require_authority=True)
            self.assertEqual(len(exported.raw), maximum)

            plain = preview_task_legacy_export(root)
            confirm_task_legacy_export(root, plain.confirmation_token)
            self.assertEqual(source.read_bytes(), exported.raw)
            self.assertEqual(source.stat().st_size, maximum)

            compatible = preview_task_compatible_export(root)
            confirm_task_compatible_export(root, compatible.confirmation_token)
            target = root.with_name(compatible.target_name)
            task_document = next(
                item
                for item in data_backup_restore._load_live_documents(target, None)
                if item.name == "tasks.json"
            )
            self.assertEqual(task_document.raw, exported.raw)
            self.assertEqual(len(task_document.raw), maximum)

            ensure_task_sqlite_authority(target)
            upgraded = export_tasks(target, require_authority=True)
            self.assertEqual(upgraded.raw, exported.raw)
            self.assertEqual(len(upgraded.raw), maximum)

    def test_plain_export_rejects_post_write_trailing_byte_drift(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            source = write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            preview = preview_task_legacy_export(root)
            expected = preview.export.raw
            original_write = task_repository.write_json_bytes_atomic

            def write_then_append_newline(*args, **kwargs):
                original_write(*args, **kwargs)
                descriptor = os.open(
                    args[0],
                    os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0),
                )
                try:
                    os.write(descriptor, b"\n")
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)

            output = io.StringIO()
            with (
                patch.object(
                    task_repository,
                    "write_json_bytes_atomic",
                    side_effect=write_then_append_newline,
                ),
                redirect_stdout(output),
            ):
                exit_code = mentat_cli_main(
                    [
                        "task-export",
                        "--data-dir",
                        str(root),
                        "--confirm",
                        preview.confirmation_token,
                    ]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "partial")
            self.assertTrue(payload["writes_performed"])
            self.assertEqual(
                payload["error_code"],
                "task_export.verification_failed",
            )
            self.assertEqual(source.read_bytes(), expected + b"\n")

    def test_compatible_export_ignores_obsolete_task_json_state(self):
        cases = ["malformed", "missing"]
        if os.name == "posix":
            cases.append("linked")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir) / "data"
                source = write_seed_root(root, [task("task_a")])
                ensure_task_sqlite_authority(root)
                outside = root / "outside-task.json"
                if case == "malformed":
                    source.write_bytes(b"{obsolete malformed task json\n")
                elif case == "missing":
                    source.unlink()
                else:
                    outside.write_text("[]\n", encoding="utf-8")
                    outside.chmod(0o600)
                    source.unlink()
                    source.symlink_to(outside)
                preview = preview_task_compatible_export(root)
                self.assertEqual(preview.public_summary()["status"], "ready")
                self.assertEqual(preview.export.task_count, 1)
                if case == "linked":
                    self.assertEqual(outside.read_text(encoding="utf-8"), "[]\n")

    def test_compatible_export_capture_failures_are_bounded(self):
        cases = ["missing", "malformed"]
        if os.name == "posix":
            cases.append("linked")
        for case in cases:
            with self.subTest(case=case), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir) / "data"
                write_seed_root(root, [task("task_a")])
                ensure_task_sqlite_authority(root)
                source = root / "projects.json"
                outside = root / "outside-projects.json"
                if case == "missing":
                    source.unlink()
                elif case == "malformed":
                    source.write_bytes(b"{malformed projects\n")
                else:
                    outside.write_text("[]\n", encoding="utf-8")
                    outside.chmod(0o600)
                    source.unlink()
                    source.symlink_to(outside)
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = mentat_cli_main(
                        ["task-export", "--data-dir", str(root), "--compatible-root"]
                    )
                payload = json.loads(output.getvalue())
                self.assertEqual(exit_code, 2)
                self.assertEqual(payload["status"], "blocked")
                self.assertFalse(payload["writes_performed"])
                self.assertEqual(
                    payload["error_code"],
                    "task_export.capture_unavailable",
                )
                self.assertNotIn(os.fspath(root), output.getvalue())
                if case == "linked":
                    self.assertEqual(outside.read_text(encoding="utf-8"), "[]\n")

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            history = root / "private" / "console" / "agent-console-runs.json"
            history.write_bytes(b"{malformed private history\n")
            if os.name != "nt":
                history.chmod(0o600)
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = mentat_cli_main(
                    ["task-export", "--data-dir", str(root), "--compatible-root"]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertFalse(payload["writes_performed"])
            self.assertEqual(
                payload["error_code"],
                "task_export.capture_unavailable",
            )

    def test_export_cli_bounds_interrupted_private_restore_before_lock_entry(self):
        cases = [
            (False, False),
            (False, True),
            (True, False),
            (True, True),
        ]
        for compatible, confirmation in cases:
            with (
                self.subTest(compatible=compatible, confirmation=confirmation),
                TemporaryDirectory() as tmpdir,
            ):
                root = Path(tmpdir) / "data"
                source = write_seed_root(root, [task("task_a")])
                ensure_task_sqlite_authority(root)
                arguments = ["task-export", "--data-dir", str(root)]
                if compatible:
                    arguments.append("--compatible-root")
                if confirmation:
                    preview = (
                        preview_task_compatible_export(root)
                        if compatible
                        else preview_task_legacy_export(root)
                    )
                    arguments.extend(["--confirm", preview.confirmation_token])
                source_before = source.read_bytes()
                control = root / "config" / "private-console-restore-v1.reservation.json"
                control.parent.mkdir(mode=0o700, exist_ok=True)
                control.write_text("{}\n", encoding="utf-8")
                if os.name != "nt":
                    control.chmod(0o600)
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = mentat_cli_main(arguments)
                payload = json.loads(output.getvalue())
                self.assertEqual(exit_code, 2)
                self.assertEqual(payload["status"], "blocked")
                self.assertFalse(payload["writes_performed"])
                self.assertEqual(
                    payload["error_code"],
                    "task_export.capture_unavailable",
                )
                self.assertEqual(source.read_bytes(), source_before)
                self.assertFalse(root.with_name("data-schema5-downgrade").exists())

    def test_compatible_export_digest_and_target_failures_are_bounded(self):
        for confirmation in (False, True):
            with self.subTest(confirmation=confirmation), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir) / "data"
                write_seed_root(root, [task("task_a")])
                ensure_task_sqlite_authority(root)
                arguments = [
                    "task-export",
                    "--data-dir",
                    str(root),
                    "--compatible-root",
                ]
                if confirmation:
                    preview = preview_task_compatible_export(root)
                    arguments.extend(["--confirm", preview.confirmation_token])
                output = io.StringIO()
                with (
                    patch(
                        "private_console_unit.private_console_unit_digest",
                        side_effect=sqlite3.OperationalError("temporary storage unavailable"),
                    ),
                    redirect_stdout(output),
                ):
                    exit_code = mentat_cli_main(arguments)
                payload = json.loads(output.getvalue())
                self.assertEqual(exit_code, 2)
                self.assertEqual(payload["status"], "blocked")
                self.assertFalse(payload["writes_performed"])
                self.assertEqual(
                    payload["error_code"],
                    "task_export.capture_unavailable",
                )

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            output = io.StringIO()
            with (
                patch.object(
                    task_repository,
                    "_compatible_downgrade_target",
                    side_effect=OSError("target unavailable"),
                ),
                redirect_stdout(output),
            ):
                exit_code = mentat_cli_main(
                    ["task-export", "--data-dir", str(root), "--compatible-root"]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertFalse(payload["writes_performed"])
            self.assertEqual(
                payload["error_code"],
                "task_export.capture_unavailable",
            )

    def test_compatible_export_refuses_active_remote_connection(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            connection = remote_hermes.connection_path(root)
            if os.name == "nt":
                remote_hermes._windows_set_owner_only(
                    connection.parent,
                    directory=True,
                )
            remote_hermes._write_connection_record(
                connection,
                remote_hermes.ConnectionState(
                    mode="remote",
                    local_label="Local Hermes",
                    remote=remote_hermes.RememberedRemote(
                        label="Workshop remote",
                        endpoint="https://hermes.example",
                        credential=remote_hermes.CredentialSource(
                            "environment",
                            "MENTAT_REMOTE_HERMES_API_KEY",
                        ),
                    ),
                    binding_id="a" * 32,
                ),
                parent_fd=None,
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = mentat_cli_main(
                    ["task-export", "--data-dir", str(root), "--compatible-root"]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertFalse(payload["writes_performed"])
            self.assertEqual(
                payload["error_code"],
                "task_export.compatible_remote_reconfigure_required",
            )
            self.assertNotIn("hermes.example", output.getvalue())
            self.assertFalse(root.with_name("data-schema5-downgrade").exists())

    def test_compatible_export_never_replaces_racing_destination(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            preview = preview_task_compatible_export(root)
            target = root.with_name(preview.target_name)
            original_publish = task_repository._publish_directory_noreplace
            raced_identity = {}

            def race_destination(source, destination, parent_descriptor):
                destination.mkdir()
                metadata = destination.stat()
                raced_identity["value"] = (metadata.st_dev, metadata.st_ino)
                return original_publish(source, destination, parent_descriptor)

            output = io.StringIO()
            with (
                patch.object(
                    task_repository,
                    "_publish_directory_noreplace",
                    side_effect=race_destination,
                ),
                redirect_stdout(output),
            ):
                exit_code = mentat_cli_main(
                    [
                        "task-export",
                        "--data-dir",
                        str(root),
                        "--compatible-root",
                        "--confirm",
                        preview.confirmation_token,
                    ]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "blocked")
            self.assertFalse(payload["writes_performed"])
            self.assertEqual(
                payload["error_code"],
                "task_export.compatible_write_failed",
            )
            metadata = target.stat()
            self.assertEqual(
                (metadata.st_dev, metadata.st_ino),
                raced_identity["value"],
            )
            self.assertEqual(list(target.iterdir()), [])

    def test_windows_publication_requests_write_through_without_replace(self):
        source = Path("C:/mentat/.compatible-stage")
        target = Path("C:/mentat/data-schema5-downgrade")
        move_file = Mock(return_value=1)
        kernel32 = Mock()
        kernel32.MoveFileExW = move_file
        with (
            patch.object(task_repository.os, "name", "nt"),
            patch.object(
                task_repository.ctypes,
                "WinDLL",
                return_value=kernel32,
                create=True,
            ),
        ):
            task_repository._publish_directory_noreplace(source, target, None)
        move_file.assert_called_once_with(
            os.fspath(source),
            os.fspath(target),
            0x00000008,
        )
        self.assertEqual(move_file.call_args.args[2] & 0x00000001, 0)

        move_file.reset_mock(return_value=True)
        move_file.return_value = 0
        with (
            patch.object(task_repository.os, "name", "nt"),
            patch.object(
                task_repository.ctypes,
                "WinDLL",
                return_value=kernel32,
                create=True,
            ),
            patch.object(
                task_repository.ctypes,
                "get_last_error",
                return_value=5,
                create=True,
            ),
            self.assertRaises(OSError),
        ):
            task_repository._publish_directory_noreplace(source, target, None)

    @unittest.skipIf(os.name != "posix", "POSIX directory durability contract")
    def test_compatible_export_fsyncs_tree_and_reports_parent_fsync_failure(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            preview = preview_task_compatible_export(root)
            private_directories = []
            original_private_fsync = private_console_unit._fsync_private_directory

            def record_private_fsync(path):
                private_directories.append(Path(path).name)
                return original_private_fsync(path)

            with (
                patch.object(
                    private_console_unit,
                    "_fsync_private_directory",
                    side_effect=record_private_fsync,
                ),
                patch.object(
                    task_repository,
                    "_fsync_staged_directory",
                    wraps=task_repository._fsync_staged_directory,
                ) as stage_fsync,
                patch.object(
                    task_repository,
                    "_fsync_publication_parent",
                    wraps=task_repository._fsync_publication_parent,
                ) as parent_fsync,
            ):
                confirm_task_compatible_export(root, preview.confirmation_token)
            self.assertEqual(
                private_directories[-4:],
                ["sha256", "blobs", "console", "private"],
            )
            stage_fsync.assert_called_once()
            parent_fsync.assert_called_once()

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            write_seed_root(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            preview = preview_task_compatible_export(root)
            target = root.with_name(preview.target_name)
            output = io.StringIO()
            with (
                patch.object(
                    task_repository,
                    "_fsync_publication_parent",
                    side_effect=OSError("publication parent fsync failed"),
                ),
                redirect_stdout(output),
            ):
                exit_code = mentat_cli_main(
                    [
                        "task-export",
                        "--data-dir",
                        str(root),
                        "--compatible-root",
                        "--confirm",
                        preview.confirmation_token,
                    ]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "partial")
            self.assertTrue(payload["writes_performed"])
            self.assertEqual(
                payload["error_code"],
                "task_export.compatible_write_failed",
            )
            self.assertTrue(target.is_dir())
            self.assertTrue((target / "tasks.json").is_file())

    @unittest.skipIf(os.name != "posix", "POSIX packaged-mode compatibility")
    def test_offline_export_accepts_packaged_mode_then_publishes_private_file(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("task_a")])
            source.chmod(0o644)
            ensure_task_sqlite_authority(root, required_source_mode=None)
            preview = preview_task_legacy_export(
                root,
                required_destination_mode=None,
            )
            self.assertEqual(preview.destination_identity[-1], 0o644)
            confirm_task_legacy_export(
                root,
                preview.confirmation_token,
                required_destination_mode=None,
            )
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o600)

    def test_offline_export_cli_reports_uncertain_and_post_write_failures(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("task_a")])
            ensure_task_sqlite_authority(root)
            preview = preview_task_legacy_export(root)
            output = io.StringIO()
            with (
                patch.object(
                    task_repository,
                    "write_json_bytes_atomic",
                    side_effect=OSError("disk full"),
                ),
                redirect_stdout(output),
            ):
                exit_code = mentat_cli_main(
                    [
                        "task-export",
                        "--data-dir",
                        str(root),
                        "--confirm",
                        preview.confirmation_token,
                    ]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "partial")
            self.assertIsNone(payload["writes_performed"])
            self.assertEqual(payload["error_code"], "task_export.write_uncertain")

            current = preview_task_legacy_export(root)
            output = io.StringIO()
            with (
                patch.object(
                    task_repository,
                    "_read_source_snapshot",
                    side_effect=TaskRepositoryUnavailable("verification unavailable"),
                ),
                redirect_stdout(output),
            ):
                exit_code = mentat_cli_main(
                    [
                        "task-export",
                        "--data-dir",
                        str(root),
                        "--confirm",
                        current.confirmation_token,
                    ]
                )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "partial")
            self.assertTrue(payload["writes_performed"])
            self.assertEqual(
                payload["error_code"],
                "task_export.verification_failed",
            )

    def test_occupied_schema_five_preview_is_blocked_with_exact_count(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_tasks(root, [task("source")])
            connection = connect(root)
            try:
                TaskRepository(connection).insert_collection([task("occupied")])
                with transaction(connection, immediate=True):
                    connection.execute("DROP TABLE mentat_agent_events")
                    connection.execute("DROP TABLE mentat_dispatch_reservations")
                    connection.execute("DROP TABLE mentat_task_dispatch_heads")
                    connection.execute("DROP TABLE mentat_runs")
                    connection.execute("DROP TABLE mentat_run_store_state")
                    connection.execute("DROP TABLE mentat_task_store_state")
                    connection.execute(
                        "DELETE FROM schema_migrations WHERE version IN (6, 7)"
                    )
            finally:
                connection.close()
            preview = preview_task_sqlite_migration(root)
            self.assertEqual(preview.status, "blocked")
            self.assertEqual(preview.destination.state, "occupied")
            self.assertEqual(preview.destination.schema_version, 5)
            self.assertEqual(preview.destination.task_count, 1)

    def test_unified_cli_runs_bounded_read_only_preview(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = write_tasks(root, [task("task_cli")])
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = mentat_cli_main(["task-migration", "--data-dir", str(root)])
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["source"]["task_ids"], ["task_cli"])
            self.assertFalse(payload["writes_performed"])
            self.assertNotIn(os.fspath(root), output.getvalue())
            self.assertTrue(source.exists())
            self.assertFalse(os.path.lexists(database_path(root)))


if __name__ == "__main__":
    unittest.main()
