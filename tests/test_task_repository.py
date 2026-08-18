from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mentat.cli import main as mentat_cli_main
from mentat_db import SCHEMA_VERSION, MentatDatabaseError, connect, database_path, transaction
from private_console_unit import (
    PrivateConsoleUnitError,
    capture_private_console_unit,
    materialize_private_console_unit,
)
from task_repository import (
    TaskRepository,
    TaskRepositoryConflict,
    TaskRepositoryError,
    TaskRepositoryUnavailable,
    TaskRepositoryValidationError,
    export_tasks,
    import_tasks_from_preview,
    normalize_task_collection,
    preview_task_sqlite_migration,
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


class TaskRepositoryTests(unittest.TestCase):
    def test_schema_five_is_additive_exact_and_forward_refusing(self):
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
            self.assertEqual(SCHEMA_VERSION, 5)
            self.assertTrue(
                {"mentat_tasks", "mentat_task_tags", "mentat_task_dependencies"}.issubset(tables)
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
                    connection.execute("DROP TABLE mentat_tasks")
                    connection.execute("DELETE FROM schema_migrations WHERE version = 5")
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
                    5,
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
            import_tasks_from_preview(source_root, preview_task_sqlite_migration(source_root))
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

    def test_no_production_import_confirmation_or_startup_reachability_exists(self):
        for source in (SERVER_SOURCE, RUNTIME_CONFIG_SOURCE, CLI_SOURCE):
            self.assertNotIn("import_tasks_from_preview", source)
            self.assertNotIn("confirm-task-sqlite-migration", source)
        self.assertIn("--preview-task-sqlite-migration", RUNTIME_CONFIG_SOURCE)
        self.assertIn('"task-migration"', CLI_SOURCE)

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
