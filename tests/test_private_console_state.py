from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import io
import os
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import patch
import zipfile

import data_backup_restore
import agent_console_attachments
import data_layout
import data_schema
import json_store
import private_console_migration
import private_console_unit
import run_repository
from agent_registry import AgentRegistry
from agent_console_attachments import (
    AttachmentError,
    AttachmentUnavailable,
    MAX_RETAINED_BLOBS,
    bind_run_attachment,
    create_attachment,
    resolve_blob_path,
)
from agent_runtime import AgentEvent, AgentEventType
from agent_run_history import save_run_summaries
from private_console_migration import migrate_private_console, preview_private_console_migration
from private_console_unit import capture_private_console_unit
from private_state import history_path, private_state_lock
from mentat_db import SCHEMA_VERSION as DATABASE_SCHEMA_VERSION, MentatDatabaseError, connect
from run_repository import (
    RunRepository,
    runtime_binding_digest,
    save_authoritative_run_summaries,
)
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from runtime_config import AppConfig, prepare_data_root_for_startup
from task_repository import TaskRepository, TaskSourceSnapshot


THREAD_TIMEOUT_SECONDS = 15


class PrivateConsoleStateTests(unittest.TestCase):
    def make_current(self, base: Path, name: str, marker: str) -> Path:
        seeds = base / f"{name}-seeds"
        target = base / name
        for root, value in ((seeds, "seed"), (target, marker)):
            root.mkdir()
            for filename in data_layout.SEED_FILE_NAMES:
                payload = {"theme": "midnight"} if filename == "dashboard.json" else []
                if filename == "tasks.json":
                    payload = [{"id": f"task-{value}"}]
                path = root / filename
                path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
                if os.name == "posix":
                    path.chmod(0o600)
            for directory in data_layout.DATA_ROOT_DIRECTORY_NAMES:
                (root / directory).mkdir()
                if os.name == "posix":
                    (root / directory).chmod(0o700)
        preview = data_schema.preview_schema_migration(seeds, target, home=base / "home")
        result = data_schema.migrate_data_schema(
            seeds,
            target,
            confirmation_token=preview.confirmation_token or "",
            home=base / "home",
        )
        self.assertEqual(result.status, "migrated")
        return target

    def schema_four_unit(
        self,
        unit: private_console_unit.PrivateConsoleUnit,
    ) -> private_console_unit.PrivateConsoleUnit:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mentat.sqlite3"
            path.write_bytes(unit.database_raw)
            connection = sqlite3.connect(path)
            try:
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
                connection.commit()
            finally:
                connection.close()
            return private_console_unit.PrivateConsoleUnit(
                history_raw=unit.history_raw,
                database_raw=path.read_bytes(),
                registry_database_raw=unit.registry_database_raw,
                blobs=unit.blobs,
            )

    def schema_six_unit(
        self,
        unit: private_console_unit.PrivateConsoleUnit,
    ) -> private_console_unit.PrivateConsoleUnit:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mentat.sqlite3"
            path.write_bytes(unit.database_raw)
            connection = sqlite3.connect(path)
            try:
                connection.execute("DROP TABLE mentat_agent_events")
                connection.execute("DROP TABLE mentat_dispatch_reservations")
                connection.execute("DROP TABLE mentat_task_dispatch_heads")
                connection.execute("DROP TABLE mentat_runs")
                connection.execute("DROP TABLE mentat_run_store_state")
                connection.execute("DELETE FROM schema_migrations WHERE version = 7")
                connection.commit()
            finally:
                connection.close()
            return private_console_unit.PrivateConsoleUnit(
                history_raw=unit.history_raw,
                database_raw=path.read_bytes(),
                registry_database_raw=unit.registry_database_raw,
                blobs=unit.blobs,
            )

    def add_retained_attachment(self, root: Path, run_id: str, content: bytes) -> dict:
        attachment = create_attachment(root, original_name="note.txt", content=content)
        bind_run_attachment(root, attachment["id"], run_id)
        save_run_summaries(
            history_path(root),
            [{
                "id": run_id,
                "status": "completed",
                "created_at": "2026-07-18T00:00:00+00:00",
                "attachments": [attachment],
            }],
            data_root=root,
        )
        return attachment

    def move_console_to_legacy_runtime(self, root: Path) -> None:
        runtime = root / "runtime"
        runtime.mkdir(exist_ok=True)
        console = root / "private" / "console"
        for name in ("agent-console-runs.json", "mentat.sqlite3", "blobs"):
            shutil.move(os.fspath(console / name), os.fspath(runtime / name))
        for suffix in ("-wal", "-shm"):
            path = console / f"mentat.sqlite3{suffix}"
            if path.exists():
                shutil.move(os.fspath(path), os.fspath(runtime / path.name))
        console.rmdir()

    def config(self, target: Path) -> AppConfig:
        return AppConfig(
            config_files=(), host="127.0.0.1", port=8888,
            data_dir=target, public_dir=target.parent / "public",
            hermes_home=target.parent / "hermes", obsidian_vault=target.parent / "vault",
            data_dir_source="cli",
        )

    def test_private_paths_are_durable_while_execution_scratch_stays_runtime(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            attachment = create_attachment(root, original_name="x.txt", content=b"x")
            self.assertTrue((root / "private" / "console" / "mentat.sqlite3").is_file())
            self.assertIn((root / "private" / "console").resolve(), resolve_blob_path(root, attachment["id"]).parents)
            self.assertTrue((root / "runtime" / "uploads").is_dir())
            if os.name == "posix":
                self.assertEqual((root / "private").stat().st_mode & 0o777, 0o700)

    def test_private_raw_writer_requests_windows_binary_mode(self):
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "snapshot.sqlite3"
            real_open = os.open
            real_binary = getattr(os, "O_BINARY", 0)
            synthetic_binary = 1 << 29
            observed_flags: list[int] = []

            def open_without_synthetic_flag(path, flags, mode=0o777):
                observed_flags.append(flags)
                return real_open(path, (flags & ~synthetic_binary) | real_binary, mode)

            with patch.object(private_console_unit.os, "O_BINARY", synthetic_binary, create=True), patch.object(
                private_console_unit.os,
                "open",
                side_effect=open_without_synthetic_flag,
            ):
                private_console_unit._write_private_file(destination, b"SQLite\n\x1a\x00")

            self.assertEqual(destination.read_bytes(), b"SQLite\n\x1a\x00")
            self.assertTrue(observed_flags[0] & synthetic_binary)

    def test_previewed_private_migration_preserves_source_and_is_idempotent(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            attachment = self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            before = {
                path.relative_to(root / "runtime").as_posix(): path.read_bytes()
                for path in (root / "runtime").rglob("*")
                if path.is_file()
            }
            preview = preview_private_console_migration(root)
            self.assertEqual(preview.status, "ready")
            after = {
                path.relative_to(root / "runtime").as_posix(): path.read_bytes()
                for path in (root / "runtime").rglob("*")
                if path.is_file()
            }
            self.assertEqual(after, before)
            result = migrate_private_console(root, confirmation_token=preview.confirmation_token or "")
            self.assertEqual(result.status, "migrated")
            self.assertEqual(resolve_blob_path(root, attachment["id"]).read_bytes(), b"legacy")
            self.assertTrue((root / "runtime" / "agent-console-runs.json").is_file())
            self.assertEqual(preview_private_console_migration(root).status, "already_migrated")

    def test_changed_legacy_source_invalidates_migration_confirmation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            preview = preview_private_console_migration(root)
            (root / "runtime" / "agent-console-runs.json").write_text(
                json.dumps({"schema_version": 3, "runs": []}, sort_keys=True, separators=(",", ":")) + "\n"
            )
            result = migrate_private_console(root, confirmation_token=preview.confirmation_token or "")
            self.assertEqual(result.status, "blocked")
            self.assertFalse((root / "private" / "console").exists())

    def test_private_migration_creates_missing_root_and_rebuilds_partial_stage(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            (root / "private").rmdir()
            preview = preview_private_console_migration(root)

            def leave_partial(_root, _unit, destination):
                destination.mkdir(parents=True, mode=0o700)
                partial = destination / "agent-console-runs.json"
                partial.write_text("{}\n")
                if os.name == "posix":
                    destination.chmod(0o700)
                    partial.chmod(0o600)
                raise OSError("injected interruption")

            with patch.object(
                private_console_migration,
                "materialize_private_console_unit",
                side_effect=leave_partial,
            ):
                first = migrate_private_console(
                    root, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            resumed_preview = preview_private_console_migration(root)
            self.assertEqual(resumed_preview.status, "resume_required")
            resumed = migrate_private_console(
                root, confirmation_token=resumed_preview.confirmation_token or ""
            )
            self.assertEqual(resumed.status, "resumed")

    def test_private_migration_receipt_crash_resumes_without_recopy(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            preview = preview_private_console_migration(root)
            real_unlink = Path.unlink

            def interrupt_reservation(path, *args, **kwargs):
                if path.name.endswith("reservation.json"):
                    raise OSError("injected interruption")
                return real_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", interrupt_reservation):
                first = migrate_private_console(
                    root, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            resumed_preview = preview_private_console_migration(root)
            self.assertEqual(resumed_preview.status, "resume_required")
            resumed = migrate_private_console(
                root, confirmation_token=resumed_preview.confirmation_token or ""
            )
            self.assertEqual(resumed.status, "resumed")

    def test_private_migration_receipt_crash_rejects_changed_destination(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            preview = preview_private_console_migration(root)
            real_unlink = Path.unlink

            def interrupt_reservation(path, *args, **kwargs):
                if path.name.endswith("reservation.json"):
                    raise OSError("injected interruption")
                return real_unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", interrupt_reservation):
                first = migrate_private_console(
                    root, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            database = root / "private" / "console" / "mentat.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "UPDATE schema_migrations SET applied_at = applied_at + 1 WHERE version = 1"
                )
                connection.commit()
            finally:
                connection.close()
            changed = preview_private_console_migration(root)
            self.assertEqual(changed.status, "blocked")
            self.assertEqual(changed.issues, ("private_migration_destination_changed",))

    def test_private_migration_never_promotes_extra_stage_entries(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            preview = preview_private_console_migration(root)
            real_materialize = private_console_migration.materialize_private_console_unit

            def leave_extra(data_root, unit, destination):
                real_materialize(data_root, unit, destination)
                (destination / "unknown.private").write_bytes(b"unknown")
                raise OSError("injected interruption")

            with patch.object(
                private_console_migration,
                "materialize_private_console_unit",
                side_effect=leave_extra,
            ):
                first = migrate_private_console(
                    root, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            resumed_preview = preview_private_console_migration(root)
            resumed = migrate_private_console(
                root, confirmation_token=resumed_preview.confirmation_token or ""
            )
            self.assertEqual(resumed.status, "partial_failure")
            self.assertFalse((root / "private" / "console").exists())
            self.assertTrue(any((root / "private").glob(".console-migration-*/unknown.private")))

    @unittest.skipIf(os.name == "nt", "POSIX nested-symlink staging test")
    def test_private_migration_never_promotes_nested_stage_symlink(self):
        with TemporaryDirectory() as temporary, TemporaryDirectory() as outside:
            root = Path(temporary) / "data"
            self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            preview = preview_private_console_migration(root)
            real_materialize = private_console_migration.materialize_private_console_unit

            def leave_symlink(data_root, unit, destination):
                real_materialize(data_root, unit, destination)
                (destination / "blobs" / "sha256" / "linked").symlink_to(
                    outside, target_is_directory=True
                )
                raise OSError("injected interruption")

            with patch.object(
                private_console_migration,
                "materialize_private_console_unit",
                side_effect=leave_symlink,
            ):
                first = migrate_private_console(
                    root, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            resumed_preview = preview_private_console_migration(root)
            resumed = migrate_private_console(
                root, confirmation_token=resumed_preview.confirmation_token or ""
            )
            self.assertEqual(resumed.status, "partial_failure")
            self.assertFalse((root / "private" / "console").exists())

    def test_private_migration_revalidates_inventory_after_rename(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            preview = preview_private_console_migration(root)
            real_rename = private_console_migration.os.rename
            injected = False

            def inject_inside_rename(source, destination):
                nonlocal injected
                source_path = Path(source)
                if not injected and source_path.name.startswith(".console-migration-"):
                    injected = True
                    extra = source_path / "injected-after-validation.private"
                    extra.write_bytes(b"unknown")
                    if os.name == "posix":
                        extra.chmod(0o600)
                return real_rename(source, destination)

            with patch.object(
                private_console_migration.os, "rename", side_effect=inject_inside_rename
            ):
                result = migrate_private_console(
                    root, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(result.status, "partial_failure")
            self.assertFalse((root / "private" / "console").exists())
            self.assertTrue(any(
                (root / "private").glob(
                    ".console-migration-*/injected-after-validation.private"
                )
            ))

    def test_already_migrated_summary_uses_current_canonical_counts(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            legacy = self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            preview = preview_private_console_migration(root)
            result = migrate_private_console(
                root, confirmation_token=preview.confirmation_token or ""
            )
            self.assertEqual(result.status, "migrated")
            current = create_attachment(root, original_name="current.txt", content=b"current")
            bind_run_attachment(root, current["id"], "run_current")
            save_run_summaries(
                history_path(root),
                [
                    {
                        "id": "run_legacy",
                        "status": "completed",
                        "created_at": "2026-07-18T00:00:00+00:00",
                        "attachments": [legacy],
                    },
                    {
                        "id": "run_current",
                        "status": "completed",
                        "created_at": "2026-07-18T01:00:00+00:00",
                        "attachments": [current],
                    },
                ],
                data_root=root,
            )
            completed = preview_private_console_migration(root)
            self.assertEqual(completed.status, "already_migrated")
            self.assertEqual(completed.run_count, 2)
            self.assertEqual(completed.blob_count, 2)

    def test_startup_refuses_legacy_private_state_until_migrated(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_current(base, "target", "target")
            self.add_retained_attachment(root, "run_legacy", b"legacy")
            self.move_console_to_legacy_runtime(root)
            error = prepare_data_root_for_startup(self.config(root))
            self.assertIn("private_console_migration_required", error or "")

    def test_backup_filters_unretained_rows_and_includes_only_referenced_blob(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_current(base, "source", "source")
            retained = self.add_retained_attachment(root, "run_kept", b"kept")
            staged = create_attachment(root, original_name="staged.txt", content=b"not-backed-up")
            result = data_backup_restore.create_durable_backup(root)
            self.assertEqual(result.status, "created")
            archive_path = root / "backups" / str(result.backup_name)
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertEqual(len([name for name in names if name.startswith("private/blobs/")]), 1)
                database = archive.read("private/mentat.sqlite3")
                self.assertNotIn(b"not-backed-up", archive_path.read_bytes())
            database_path = base / "snapshot.sqlite3"
            database_path.write_bytes(database)
            connection = sqlite3.connect(database_path)
            try:
                ids = {row[0] for row in connection.execute("SELECT id FROM attachments")}
            finally:
                connection.close()
            self.assertIn(retained["id"], ids)
            self.assertNotIn(staged["id"], ids)

    def test_missing_referenced_blob_blocks_backup(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_current(base, "source", "source")
            retained = self.add_retained_attachment(root, "run_kept", b"kept")
            resolve_blob_path(root, retained["id"]).unlink()
            result = data_backup_restore.create_durable_backup(root)
            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.issues, ("backup_failed",))

    def test_backup_uses_sqlite_snapshot_semantics_with_live_wal(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_current(base, "source", "source")
            connection = connect(root)
            try:
                connection.execute("UPDATE schema_migrations SET applied_at = 4242 WHERE version = 1")
                connection.commit()
                result = data_backup_restore.create_durable_backup(root)
            finally:
                connection.close()
            self.assertEqual(result.status, "created")
            with zipfile.ZipFile(root / "backups" / str(result.backup_name)) as archive:
                snapshot = base / "wal-snapshot.sqlite3"
                snapshot.write_bytes(archive.read("private/mentat.sqlite3"))
            restored = sqlite3.connect(snapshot)
            try:
                value = restored.execute(
                    "SELECT applied_at FROM schema_migrations WHERE version = 1"
                ).fetchone()[0]
                self.assertEqual(value, 4242)
                self.assertEqual(restored.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                restored.close()

    def test_private_capture_preserves_active_run_status_and_timestamps(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            connection = connect(root)
            connection.close()
            save_run_summaries(
                history_path(root),
                [{
                    "id": "run_active",
                    "status": "running",
                    "created_at": "2026-07-18T01:00:00+00:00",
                    "updated_at": "2026-07-18T01:01:00+00:00",
                    "started_at": "2026-07-18T01:00:10+00:00",
                }],
                data_root=root,
            )
            unit = capture_private_console_unit(root)
            run = json.loads(unit.history_raw)["runs"][0]
            self.assertEqual(run["status"], "running")
            self.assertEqual(run["updated_at"], "2026-07-18T01:01:00+00:00")
            self.assertEqual(run["started_at"], "2026-07-18T01:00:10+00:00")
            self.assertIsNone(run["completed_at"])

    def test_schema_seven_backup_derives_runs_from_sqlite_and_rejects_event_corruption(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            connection = connect(root)
            connection.close()
            save_run_summaries(
                history_path(root),
                [{
                    "id": "run_sqlite_backup",
                    "status": "completed",
                    "created_at": "2026-08-18T01:00:00+00:00",
                    "updated_at": "2026-08-18T01:01:00+00:00",
                    "completed_at": "2026-08-18T01:01:00+00:00",
                }],
                data_root=root,
            )
            ensure_run_sqlite_authority(root, history_path(root))
            connection = connect(root)
            try:
                RunRepository(connection).append_event(
                    AgentEvent(
                        id="event-backup-corrupt",
                        run_id="run_sqlite_backup",
                        sequence=1,
                        type=AgentEventType.MESSAGE,
                        occurred_at="2026-08-18T01:00:30+00:00",
                        summary="Valid event",
                    )
                )
            finally:
                connection.close()
            history_path(root).write_text(
                json.dumps({"schema_version": 3, "runs": []}), encoding="utf-8"
            )

            unit = capture_private_console_unit(root)
            history = json.loads(unit.history_raw)
            self.assertEqual(unit.run_count, 1)
            self.assertEqual([item["id"] for item in history["runs"]], ["run_sqlite_backup"])

            database = Path(temporary) / "corrupt.sqlite3"
            database.write_bytes(unit.database_raw)
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                row = connection.execute(
                    "SELECT * FROM mentat_agent_events WHERE id = 'event-backup-corrupt'"
                ).fetchone()
                record = {
                    key: row[key]
                    for key in (
                        "id", "run_id", "sequence", "event_type", "source_type",
                        "source_key", "occurred_at", "summary", "content", "metrics_json",
                        "data_json",
                    )
                }
                record["source_type"] = "cost"
                payload_digest = hashlib.sha256(
                    run_repository._canonical_json(
                        record, maximum=32_768, code="event.invalid"
                    ).encode("ascii")
                ).hexdigest()
                connection.execute(
                    "UPDATE mentat_agent_events SET source_type = 'cost', payload_digest = ? "
                    "WHERE id = 'event-backup-corrupt'",
                    (payload_digest,),
                )
                connection.commit()
            finally:
                connection.close()
            corrupted = private_console_unit.PrivateConsoleUnit(
                history_raw=unit.history_raw,
                database_raw=database.read_bytes(),
                registry_database_raw=unit.registry_database_raw,
                blobs=unit.blobs,
            )
            with self.assertRaisesRegex(
                private_console_unit.PrivateConsoleUnitError,
                "private_run_repository_invalid",
            ):
                private_console_unit.validate_private_console_unit(corrupted)

    def test_schema_seven_backup_bounds_legacy_projection_without_dropping_canonical_runs(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            ensure_run_sqlite_authority(root, history_path(root))
            runs = []
            for run_number in range(120):
                run_id = f"run_backup_bound_{run_number:03d}"
                runs.append(
                    {
                        "id": run_id,
                        "runtime_type": "hermes",
                        "agent_id": "default",
                        "agent_name": "Hermes",
                        "status": "completed",
                        "response": "R" * 1_000,
                        "created_at": f"2026-08-18T01:{run_number // 60:02d}:{run_number % 60:02d}+00:00",
                        "updated_at": f"2026-08-18T02:{run_number // 60:02d}:{run_number % 60:02d}+00:00",
                        "completed_at": f"2026-08-18T02:{run_number // 60:02d}:{run_number % 60:02d}+00:00",
                        "events": [
                            {
                                "id": f"event_backup_{run_number}_{sequence}",
                                "run_id": run_id,
                                "sequence": sequence,
                                "cursor": sequence,
                                "type": "status",
                                "kind": "status",
                                "timestamp": f"2026-08-18T03:{sequence // 60:02d}:{sequence % 60:02d}+00:00",
                                "display_text": "Progress " + ("x" * 480),
                                "message": "Progress " + ("x" * 480),
                                "data": {},
                            }
                            for sequence in range(1, 41)
                        ],
                    }
                )
            save_authoritative_run_summaries(root, runs)

            unit = capture_private_console_unit(root)
            validated = private_console_unit.validate_private_console_unit(unit)
            projected = json.loads(unit.history_raw)

        self.assertEqual(validated.run_count, 120)
        self.assertLessEqual(len(unit.history_raw), private_console_unit.MAX_HISTORY_BYTES)
        self.assertEqual(len(projected["runs"]), 120)
        self.assertTrue(all(item["events"] == [] for item in projected["runs"]))

    def test_schema_seven_capture_ignores_malformed_stale_legacy_history(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_current(base, "source", "source")
            connection = connect(root)
            try:
                raw = b"[]\n"
                connection.execute("BEGIN IMMEDIATE")
                TaskRepository(
                    connection, allow_pre_authority_schema=True
                ).claim_authority(
                    TaskSourceSnapshot(
                        raw=raw,
                        tasks=(),
                        sha256=hashlib.sha256(raw).hexdigest(),
                        identity=(1, 1, len(raw), 1),
                    )
                )
                connection.commit()
            finally:
                connection.close()
            ensure_run_sqlite_authority(root, history_path(root))
            stale = history_path(root)
            stale.write_text("{malformed stale history", encoding="utf-8")
            if os.name != "nt":
                stale.chmod(0o600)

            unit = capture_private_console_unit(root)
            payload = json.loads(unit.history_raw)

        self.assertEqual(payload, {"runs": [], "schema_version": 3})

    def test_maximum_terminal_dispatch_retention_remains_backup_capable(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_current(base, "source", "source")
            (root / "tasks.json").write_text("[]\n", encoding="utf-8")
            if os.name == "posix":
                (root / "tasks.json").chmod(0o600)
            ensure_run_sqlite_authority(root, history_path(root))
            connection = connect(root)
            try:
                repository = RunRepository(connection)
                tasks = [
                    {
                        "id": f"task-backup-boundary-{index:03d}",
                        "title": f"Boundary task {index}",
                        "description": "x" * 20_000,
                        "project": "Mentat",
                        "status": "todo",
                        "priority": "medium",
                        "assignee": None,
                        "assigned_agent_id": "agent-main",
                        "due_date": None,
                        "source": "test",
                        "tags": [],
                        "review_required": False,
                        "needs_attention": False,
                        "created_at": "2026-08-18T12:00:00+00:00",
                        "updated_at": "2026-08-18T12:00:00+00:00",
                        "completed_at": None,
                        "required_capabilities": ["run.start"],
                        "acceptance_criteria": ["Retain exact execution input"],
                    }
                    for index in range(251)
                ]
                connection.execute("DELETE FROM mentat_task_dependencies")
                connection.execute("DELETE FROM mentat_task_tags")
                connection.execute("DELETE FROM mentat_tasks")
                connection.commit()
                task_repository = TaskRepository(
                    connection, allow_pre_authority_schema=True
                )
                task_repository.insert_collection(tasks)
                normalized_tasks = tuple(task_repository.list_tasks())
                stored_tasks = {task["id"]: task for task in normalized_tasks}
                digest = runtime_binding_digest(
                    agent_id="agent-main",
                    runtime_type="hermes",
                    runtime_config_id="config-main",
                    runtime_agent_ref="profile-main",
                    capabilities=("run.start",),
                )
                for index in range(251):
                    task_id = f"task-backup-boundary-{index:03d}"
                    task = stored_tasks[task_id]
                    reservation = repository.reserve_dispatch(
                        idempotency_key=f"boundary-idempotency-key-{index:03d}",
                        dispatch_id=f"dispatch-boundary-{index:03d}",
                        run_id=f"run_boundary_{index:03d}",
                        task=task,
                        task_revision=1,
                        agent_id="agent-main",
                        runtime_type="hermes",
                        runtime_config_id="config-main",
                        binding_digest=digest,
                        capabilities=("run.start",),
                    )
                    repository.reject_reserved_dispatch(
                        dispatch_id=reservation.dispatch_id,
                        failure_code="dispatch.test_rejection",
                    )
                repository.validate()
            finally:
                connection.close()

            unit = capture_private_console_unit(root)
            retained_path = Path(temporary) / "retained-boundary.sqlite3"
            retained_path.write_bytes(unit.database_raw)
            retained_connection = sqlite3.connect(retained_path)
            try:
                retained_counts = (
                    retained_connection.execute(
                        "SELECT COUNT(*) FROM mentat_runs"
                    ).fetchone()[0],
                    retained_connection.execute(
                        "SELECT COUNT(*) FROM mentat_dispatch_reservations"
                    ).fetchone()[0],
                    retained_connection.execute(
                        "SELECT COUNT(*) FROM mentat_dispatch_reservations d "
                        "WHERE NOT EXISTS (SELECT 1 FROM mentat_runs r WHERE r.id = d.run_id)"
                    ).fetchone()[0],
                )
            finally:
                retained_connection.close()
            corrupted_path = Path(temporary) / "corrupt-run.sqlite3"
            corrupted_path.write_bytes(unit.database_raw)
            corrupted_connection = sqlite3.connect(corrupted_path)
            try:
                corrupted_connection.execute(
                    "UPDATE mentat_runs SET runtime_type = '../invalid' "
                    "WHERE id = 'run_boundary_250'"
                )
                corrupted_connection.commit()
            finally:
                corrupted_connection.close()
            corrupted_unit = private_console_unit.PrivateConsoleUnit(
                history_raw=unit.history_raw,
                database_raw=corrupted_path.read_bytes(),
                registry_database_raw=unit.registry_database_raw,
                blobs=unit.blobs,
            )
            with self.assertRaisesRegex(
                private_console_unit.PrivateConsoleUnitError,
                "private_run_repository_invalid",
            ):
                private_console_unit.validate_private_console_unit(corrupted_unit)

            capability_path = Path(temporary) / "corrupt-capability.sqlite3"
            capability_path.write_bytes(unit.database_raw)
            capability_connection = sqlite3.connect(capability_path)
            capability_connection.row_factory = sqlite3.Row
            try:
                run_row = capability_connection.execute(
                    "SELECT * FROM mentat_runs WHERE id = 'run_boundary_250'"
                ).fetchone()
                snapshot = json.loads(run_row["task_snapshot_json"])
                snapshot["required_capabilities"] = ["capability.not_bound"]
                snapshot_json = run_repository._canonical_json(
                    snapshot,
                    maximum=run_repository.TASK_SNAPSHOT_LIMIT,
                    code="dispatch.task_invalid",
                )
                request_digest = run_repository.dispatch_request_digest(
                    task=snapshot,
                    task_revision=int(run_row["task_revision"]),
                    agent_id=str(run_row["agent_id"]),
                    runtime_type=str(run_row["runtime_type"]),
                    runtime_config_id=str(run_row["runtime_config_id"]),
                    capabilities=("run.start",),
                )
                capability_connection.execute(
                    "UPDATE mentat_runs SET task_snapshot_json = ? WHERE id = ?",
                    (snapshot_json, run_row["id"]),
                )
                capability_connection.execute(
                    "UPDATE mentat_dispatch_reservations SET request_digest = ? WHERE run_id = ?",
                    (request_digest, run_row["id"]),
                )
                capability_connection.execute(
                    "UPDATE mentat_task_dispatch_heads SET request_digest = ? WHERE run_id = ?",
                    (request_digest, run_row["id"]),
                )
                capability_connection.commit()
            finally:
                capability_connection.close()
            capability_unit = private_console_unit.PrivateConsoleUnit(
                history_raw=unit.history_raw,
                database_raw=capability_path.read_bytes(),
                registry_database_raw=unit.registry_database_raw,
                blobs=unit.blobs,
            )
            with self.assertRaisesRegex(
                private_console_unit.PrivateConsoleUnitError,
                "private_run_repository_invalid",
            ):
                private_console_unit.validate_private_console_unit(capability_unit)

        self.assertEqual(unit.run_count, 250)
        self.assertEqual(retained_counts, (250, 251, 1))
        self.assertLessEqual(
            len(unit.database_raw), private_console_unit.MAX_DATABASE_BYTES
        )

    def test_referenced_blob_count_boundary_remains_backup_capable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            ensure_run_sqlite_authority(root, history_path(root))
            runs = [
                {
                    "id": f"run_blob_count_{index:03d}",
                    "status": "completed",
                    "created_at": f"2026-08-18T12:{index // 60:02d}:{index % 60:02d}+00:00",
                    "completed_at": f"2026-08-18T12:{index // 60:02d}:{index % 60:02d}+00:00",
                }
                for index in range(MAX_RETAINED_BLOBS + 1)
            ]
            save_authoritative_run_summaries(root, runs)
            for index in range(MAX_RETAINED_BLOBS):
                attachment = create_attachment(
                    root,
                    original_name=f"count-{index}.txt",
                    content=f"blob-{index}".encode(),
                )
                bind_run_attachment(root, attachment["id"], runs[index]["id"])
            unit = capture_private_console_unit(root)
            overflow = create_attachment(
                root, original_name="count-overflow.txt", content=b"overflow"
            )
            with self.assertRaisesRegex(AttachmentUnavailable, "capacity"):
                bind_run_attachment(
                    root, overflow["id"], runs[MAX_RETAINED_BLOBS]["id"]
                )

        self.assertEqual(len(unit.blobs), MAX_RETAINED_BLOBS)

    def test_referenced_blob_byte_boundary_remains_backup_capable(self):
        with TemporaryDirectory() as temporary, patch.object(
            agent_console_attachments, "MAX_RETAINED_BLOB_BYTES", 10
        ), patch.object(private_console_unit, "MAX_RETAINED_BLOB_BYTES", 10):
            root = Path(temporary) / "data"
            ensure_run_sqlite_authority(root, history_path(root))
            blob_count = 2
            runs = [
                {
                    "id": f"run_blob_bytes_{index:02d}",
                    "status": "completed",
                    "created_at": f"2026-08-18T13:00:{index:02d}+00:00",
                    "completed_at": f"2026-08-18T13:00:{index:02d}+00:00",
                }
                for index in range(blob_count + 1)
            ]
            save_authoritative_run_summaries(root, runs)
            for index in range(blob_count):
                attachment = create_attachment(
                    root,
                    original_name=f"bytes-{index}.txt",
                    content=bytes((65 + index,)) * 5,
                )
                bind_run_attachment(root, attachment["id"], runs[index]["id"])
            unit = capture_private_console_unit(root)
            overflow = create_attachment(
                root, original_name="bytes-overflow.txt", content=b"x"
            )
            with self.assertRaisesRegex(AttachmentUnavailable, "capacity"):
                bind_run_attachment(root, overflow["id"], runs[-1]["id"])

        self.assertEqual(sum(len(blob.raw) for blob in unit.blobs), 10)

    def test_v2_restore_replaces_private_unit_and_v1_preserves_it(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            source_attachment = self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            backup_path = source / "backups" / str(backup.backup_name)
            target = self.make_current(base, "target", "target")
            target_attachment = self.add_retained_attachment(target, "run_target", b"target")
            preview = data_backup_restore.preview_durable_restore(target, backup_path)
            private_item = next(
                item for item in preview.items if item["name"] == "private_console"
            )
            self.assertEqual(private_item["action"], "replace")
            restored = data_backup_restore.restore_durable_backup(
                target, backup_path, confirmation_token=preview.confirmation_token or ""
            )
            self.assertEqual(restored.status, "restored")
            self.assertIn("private_console", {item["name"] for item in restored.items})
            self.assertEqual(resolve_blob_path(target, source_attachment["id"]).read_bytes(), b"source")
            with self.assertRaises(AttachmentError):
                resolve_blob_path(target, target_attachment["id"])

            legacy_target = self.make_current(base, "legacy-target", "legacy")
            preserved = self.add_retained_attachment(legacy_target, "run_preserved", b"preserved")
            documents = data_backup_restore._load_live_documents(source, None)
            legacy_raw = data_backup_restore._build_backup(documents, format_version=1)
            legacy_name = data_backup_restore._backup_name(documents, format_version=1)
            legacy_path = base / legacy_name
            legacy_path.write_bytes(legacy_raw)
            if os.name == "posix":
                legacy_path.chmod(0o600)
            legacy_preview = data_backup_restore.preview_durable_restore(legacy_target, legacy_path)
            legacy_result = data_backup_restore.restore_durable_backup(
                legacy_target, legacy_path, confirmation_token=legacy_preview.confirmation_token or ""
            )
            self.assertEqual(legacy_result.status, "restored")
            self.assertEqual(resolve_blob_path(legacy_target, preserved["id"]).read_bytes(), b"preserved")

    def test_pre_registry_v2_backup_restores_with_an_empty_registry(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            documents = data_backup_restore._load_live_documents(source, None)
            source_unit = capture_private_console_unit(source)
            v2_raw = data_backup_restore._build_backup(
                documents,
                source_unit,
                format_version=2,
            )
            v2_name = data_backup_restore._backup_name(
                documents,
                source_unit,
                format_version=2,
            )
            v2_path = base / v2_name
            v2_path.write_bytes(v2_raw)
            if os.name == "posix":
                v2_path.chmod(0o600)

            target = self.make_current(base, "target", "target")
            AgentRegistry(target, supported_runtime_types={"hermes"}).create_agent(
                agent_id="agent_target",
                name="Target Agent",
                runtime_config_id="runtime_config_target",
                runtime_type="hermes",
                runtime_agent_ref="target-profile",
                capabilities=(),
            )
            preview = data_backup_restore.preview_durable_restore(target, v2_path)
            self.assertEqual(preview.status, "ready")
            private_item = next(
                item for item in preview.items if item["name"] == "private_console"
            )
            self.assertEqual(private_item["agent_count"], 0)
            self.assertEqual(private_item["target_agent_count"], 1)
            self.assertEqual(private_item["agent_registry_action"], "clear")
            result = data_backup_restore.restore_durable_backup(
                target,
                v2_path,
                confirmation_token=preview.confirmation_token or "",
            )
            self.assertEqual(result.status, "restored")
            self.assertEqual(
                AgentRegistry(target, supported_runtime_types={"hermes"}).list_agents(),
                (),
            )

    def test_released_schema_four_v2_and_v3_backups_restore_and_migrate(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            documents = data_backup_restore._load_live_documents(source, None)
            schema_four = self.schema_four_unit(capture_private_console_unit(source))
            self.assertEqual(schema_four.task_count, 0)

            for format_version in (2, 3):
                with self.subTest(format_version=format_version):
                    raw = data_backup_restore._build_backup(
                        documents,
                        schema_four,
                        format_version=format_version,
                    )
                    name = data_backup_restore._backup_name(
                        documents,
                        schema_four,
                        format_version=format_version,
                    )
                    path = base / name
                    path.write_bytes(raw)
                    if os.name == "posix":
                        path.chmod(0o600)
                    target = self.make_current(
                        base,
                        f"target-{format_version}",
                        f"target-{format_version}",
                    )
                    preview = data_backup_restore.preview_durable_restore(target, path)
                    self.assertEqual(preview.status, "ready")
                    private_item = next(
                        item for item in preview.items if item["name"] == "private_console"
                    )
                    self.assertEqual(private_item["task_count"], 0)
                    result = data_backup_restore.restore_durable_backup(
                        target,
                        path,
                        confirmation_token=preview.confirmation_token or "",
                    )
                    self.assertEqual(result.status, "restored")
                    migrated = connect(target)
                    try:
                        self.assertEqual(
                            migrated.execute(
                                "SELECT MAX(version) FROM schema_migrations"
                            ).fetchone()[0],
                            DATABASE_SCHEMA_VERSION,
                        )
                    finally:
                        migrated.close()

    def test_schema_six_backup_restores_and_migrates_to_schema_seven(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source-six", "source")
            documents = data_backup_restore._load_live_documents(source, None)
            schema_six = self.schema_six_unit(capture_private_console_unit(source))
            private_console_unit.validate_private_console_unit(schema_six)
            raw = data_backup_restore._build_backup(documents, schema_six, format_version=3)
            path = base / data_backup_restore._backup_name(
                documents, schema_six, format_version=3
            )
            path.write_bytes(raw)
            if os.name == "posix":
                path.chmod(0o600)
            target = self.make_current(base, "target-six", "target")
            preview = data_backup_restore.preview_durable_restore(target, path)
            result = data_backup_restore.restore_durable_backup(
                target,
                path,
                confirmation_token=preview.confirmation_token or "",
            )
            self.assertEqual(result.status, "restored")
            migrated = connect(target)
            try:
                self.assertEqual(
                    migrated.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0],
                    7,
                )
            finally:
                migrated.close()

    def test_upgrade_resumes_genuine_protocol_2_restore_receipts(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            source_documents = data_backup_restore._load_live_documents(source, None)
            source_unit = capture_private_console_unit(source)
            source_raw = data_backup_restore._build_backup(
                source_documents,
                source_unit,
                format_version=2,
            )
            source_name = data_backup_restore._backup_name(
                source_documents,
                source_unit,
                format_version=2,
            )
            source_path = base / source_name
            source_path.write_bytes(source_raw)
            if os.name == "posix":
                source_path.chmod(0o600)

            target = self.make_current(base, "target", "target")
            real_build = data_backup_restore._build_backup

            def protocol_2_build(documents, private_unit=None, **kwargs):
                kwargs.setdefault("format_version", 2)
                return real_build(documents, private_unit, **kwargs)

            with (
                patch.object(data_backup_restore, "RESTORE_PROTOCOL_VERSION", 2),
                patch.object(data_backup_restore, "_build_backup", side_effect=protocol_2_build),
            ):
                preview = data_backup_restore.preview_durable_restore(target, source_path)
                with patch.object(
                    data_backup_restore,
                    "_restore_private_console_under_lock",
                    side_effect=OSError("simulated legacy interruption"),
                ):
                    partial = data_backup_restore.restore_durable_backup(
                        target,
                        source_path,
                        confirmation_token=preview.confirmation_token or "",
                    )
            self.assertEqual(partial.status, "partial_failure")
            state = json.loads(
                (target / "config" / data_backup_restore.RESTORE_STATE_NAME).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(state["protocol_version"], 2)
            self.assertTrue(state["source_backup_name"].startswith("mentat-backup-v2-"))
            self.assertTrue(state["recovery_backup_name"].startswith("mentat-backup-v2-"))

            resume = data_backup_restore.preview_durable_restore(target, source_path)
            self.assertEqual(resume.status, "resume_required")
            completed = data_backup_restore.restore_durable_backup(
                target,
                source_path,
                confirmation_token=resume.confirmation_token or "",
            )
            self.assertEqual(completed.status, "resumed")

    def test_restore_preview_does_not_create_or_change_live_sqlite_sidecars(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            target = self.make_current(base, "target", "target")
            self.add_retained_attachment(target, "run_target", b"target")
            console = target / "private" / "console"
            before = {
                path.name: path.read_bytes()
                for path in console.iterdir()
                if path.is_file()
            }
            preview = data_backup_restore.preview_durable_restore(
                target, source / "backups" / str(backup.backup_name)
            )
            self.assertEqual(preview.status, "ready")
            after = {
                path.name: path.read_bytes()
                for path in console.iterdir()
                if path.is_file()
            }
            self.assertEqual(after, before)

    def test_interrupted_private_directory_exchange_resumes_exact_state(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            backup_path = source / "backups" / str(backup.backup_name)
            target = self.make_current(base, "target", "target")
            self.add_retained_attachment(target, "run_target", b"target")
            preview = data_backup_restore.preview_durable_restore(target, backup_path)
            real_rename = data_backup_restore.os.rename
            calls = 0

            def interrupt_after_old(source_path, destination_path):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected interruption")
                return real_rename(source_path, destination_path)

            with patch.object(data_backup_restore.os, "rename", side_effect=interrupt_after_old):
                first = data_backup_restore.restore_durable_backup(
                    target, backup_path, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            resumed_preview = data_backup_restore.preview_durable_restore(target, backup_path)
            self.assertEqual(resumed_preview.status, "resume_required")
            resumed = data_backup_restore.restore_durable_backup(
                target, backup_path, confirmation_token=resumed_preview.confirmation_token or ""
            )
            self.assertEqual(resumed.status, "resumed")

    def test_partial_private_restore_stage_is_rebuilt_on_resume(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            backup_path = source / "backups" / str(backup.backup_name)
            target = self.make_current(base, "target", "target")
            self.add_retained_attachment(target, "run_target", b"target")
            preview = data_backup_restore.preview_durable_restore(target, backup_path)

            def leave_partial(_root, _unit, destination):
                destination.mkdir(parents=True, mode=0o700)
                partial = destination / "agent-console-runs.json"
                partial.write_text("{}\n")
                if os.name == "posix":
                    destination.chmod(0o700)
                    partial.chmod(0o600)
                raise OSError("injected interruption")

            with patch.object(
                data_backup_restore,
                "materialize_private_console_unit",
                side_effect=leave_partial,
            ):
                first = data_backup_restore.restore_durable_backup(
                    target, backup_path, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            resumed_preview = data_backup_restore.preview_durable_restore(target, backup_path)
            self.assertEqual(resumed_preview.status, "resume_required")
            resumed = data_backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=resumed_preview.confirmation_token or "",
            )
            self.assertEqual(resumed.status, "resumed")

    def test_private_restore_keeps_state_through_old_tree_cleanup(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            backup_path = source / "backups" / str(backup.backup_name)
            target = self.make_current(base, "target", "target")
            self.add_retained_attachment(target, "run_target", b"target")
            preview = data_backup_restore.preview_durable_restore(target, backup_path)
            real_unlink = data_backup_restore._unlink_relative

            def interrupt_state_unlink(path, parent_fd):
                if path.name == data_backup_restore.RESTORE_STATE_NAME:
                    raise OSError("injected interruption")
                return real_unlink(path, parent_fd)

            with patch.object(
                data_backup_restore, "_unlink_relative", side_effect=interrupt_state_unlink
            ):
                first = data_backup_restore.restore_durable_backup(
                    target, backup_path, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            self.assertFalse(any((target / "private").glob(".console-restore-*-old")))
            resumed_preview = data_backup_restore.preview_durable_restore(target, backup_path)
            self.assertEqual(resumed_preview.status, "resume_required")
            resumed = data_backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=resumed_preview.confirmation_token or "",
            )
            self.assertEqual(resumed.status, "resumed")

    def test_private_restore_resumes_after_partial_old_tree_cleanup(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            backup_path = source / "backups" / str(backup.backup_name)
            target = self.make_current(base, "target", "target")
            self.add_retained_attachment(target, "run_target", b"target")
            preview = data_backup_restore.preview_durable_restore(target, backup_path)
            real_remove = data_backup_restore.remove_private_console_tree
            interrupted = False

            def interrupt_old_cleanup(data_root, path):
                nonlocal interrupted
                if not interrupted and path.name.endswith("-old"):
                    interrupted = True
                    (path / "agent-console-runs.json").unlink()
                    raise OSError("injected partial cleanup")
                return real_remove(data_root, path)

            with patch.object(
                data_backup_restore,
                "remove_private_console_tree",
                side_effect=interrupt_old_cleanup,
            ):
                first = data_backup_restore.restore_durable_backup(
                    target, backup_path, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            resumed_preview = data_backup_restore.preview_durable_restore(target, backup_path)
            self.assertEqual(resumed_preview.status, "resume_required")
            resumed = data_backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=resumed_preview.confirmation_token or "",
            )
            self.assertEqual(resumed.status, "resumed")

    def test_private_restore_detects_same_shape_mutation_during_cleanup(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            backup_path = source / "backups" / str(backup.backup_name)
            target = self.make_current(base, "target", "target")
            self.add_retained_attachment(target, "run_target", b"target")
            preview = data_backup_restore.preview_durable_restore(target, backup_path)
            real_remove = data_backup_restore.remove_private_console_tree
            changed = False

            def mutate_after_old_cleanup(data_root, path):
                nonlocal changed
                real_remove(data_root, path)
                if not changed and path.name.endswith("-old"):
                    changed = True
                    live_history = history_path(target)
                    payload = json.loads(live_history.read_text())
                    payload["runs"][0]["status"] = "failed"
                    live_history.write_bytes(data_backup_restore._canonical_json(payload))
                    if os.name == "posix":
                        live_history.chmod(0o600)

            with patch.object(
                data_backup_restore,
                "remove_private_console_tree",
                side_effect=mutate_after_old_cleanup,
            ):
                result = data_backup_restore.restore_durable_backup(
                    target, backup_path, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(result.status, "partial_failure")
            self.assertTrue((target / "config" / "restore-state-v1.json").is_file())

    def test_private_restore_never_promotes_extra_stage_entries(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            backup_path = source / "backups" / str(backup.backup_name)
            target = self.make_current(base, "target", "target")
            self.add_retained_attachment(target, "run_target", b"target")
            preview = data_backup_restore.preview_durable_restore(target, backup_path)
            real_materialize = data_backup_restore.materialize_private_console_unit

            def leave_extra(data_root, unit, destination):
                real_materialize(data_root, unit, destination)
                (destination / "blobs" / "sha256" / "extra").write_bytes(b"unknown")
                raise OSError("injected interruption")

            with patch.object(
                data_backup_restore,
                "materialize_private_console_unit",
                side_effect=leave_extra,
            ):
                first = data_backup_restore.restore_durable_backup(
                    target, backup_path, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(first.status, "partial_failure")
            resumed_preview = data_backup_restore.preview_durable_restore(target, backup_path)
            resumed = data_backup_restore.restore_durable_backup(
                target,
                backup_path,
                confirmation_token=resumed_preview.confirmation_token or "",
            )
            self.assertEqual(resumed.status, "partial_failure")
            self.assertTrue(any((target / "private").glob(".console-restore-*-new/blobs/sha256/extra")))

    def test_private_restore_revalidates_inventory_after_rename(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            backup_path = source / "backups" / str(backup.backup_name)
            target = self.make_current(base, "target", "target")
            target_attachment = self.add_retained_attachment(
                target, "run_target", b"target"
            )
            target_before = capture_private_console_unit(target)
            preview = data_backup_restore.preview_durable_restore(target, backup_path)
            real_rename = data_backup_restore.os.rename
            injected = False

            def inject_inside_rename(source_path, destination_path):
                nonlocal injected
                candidate = Path(source_path)
                if not injected and candidate.name.endswith("-new"):
                    injected = True
                    extra = candidate / "injected-after-validation.private"
                    extra.write_bytes(b"unknown")
                    if os.name == "posix":
                        extra.chmod(0o600)
                return real_rename(source_path, destination_path)

            with patch.object(
                data_backup_restore.os, "rename", side_effect=inject_inside_rename
            ):
                result = data_backup_restore.restore_durable_backup(
                    target, backup_path, confirmation_token=preview.confirmation_token or ""
                )
            self.assertEqual(result.status, "partial_failure")
            with private_state_lock(target, allow_control=True):
                target_after = capture_private_console_unit(target)
            self.assertEqual(
                private_console_unit.private_console_unit_digest(target_after),
                private_console_unit.private_console_unit_digest(target_before),
            )
            self.assertTrue(any(
                (target / "private").glob(
                    ".console-restore-*-new/injected-after-validation.private"
                )
            ))

    def test_sqlite_capture_rechecks_main_database_bytes(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "data"
            connection = connect(root)
            connection.close()
            source = root / "private" / "console" / "mentat.sqlite3"
            destination = base / "snapshot.sqlite3"
            real_safe_regular = private_console_unit._safe_regular
            changed = False

            def change_after_first_read(path, **kwargs):
                nonlocal changed
                raw = real_safe_regular(path, **kwargs)
                if Path(path) == source and not changed:
                    changed = True
                    details = source.stat()
                    replacement = bytearray(raw)
                    replacement[-1] ^= 1
                    source.write_bytes(replacement)
                    os.utime(source, ns=(details.st_atime_ns, details.st_mtime_ns))
                    if os.name == "posix":
                        source.chmod(0o600)
                return raw

            with patch.object(
                private_console_unit, "_safe_regular", side_effect=change_after_first_read
            ):
                with self.assertRaisesRegex(
                    private_console_unit.PrivateConsoleUnitError,
                    "private_database_changed",
                ):
                    private_console_unit._sqlite_backup(
                        source, destination, copy_source=True
                    )

    def test_malformed_v2_manifest_items_fail_closed(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            archive_path = source / "backups" / str(backup.backup_name)
            output = io.BytesIO()
            with zipfile.ZipFile(archive_path) as original, zipfile.ZipFile(
                output, "w", compression=zipfile.ZIP_STORED
            ) as malformed:
                for name in original.namelist():
                    raw = original.read(name)
                    if name == "manifest.json":
                        manifest = json.loads(raw)
                        manifest["items"] = ["bad"]
                        raw = data_backup_restore._canonical_json(manifest)
                    malformed.writestr(data_backup_restore._zip_entry(name), raw)
            with self.assertRaisesRegex(ValueError, "backup_manifest_invalid"):
                data_backup_restore._contents_from_backup(output.getvalue())

    def test_v2_restore_is_blocked_while_recorded_server_is_active(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = self.make_current(base, "source", "source")
            self.add_retained_attachment(source, "run_source", b"source")
            backup = data_backup_restore.create_durable_backup(source)
            target = self.make_current(base, "target", "target")
            state = target / "runtime" / "server-state.json"
            state.write_text(json.dumps({"pid": os.getpid()}) + "\n")
            if os.name == "posix":
                state.chmod(0o600)
            preview = data_backup_restore.preview_durable_restore(
                target, source / "backups" / str(backup.backup_name)
            )
            self.assertEqual(preview.status, "unsafe")
            self.assertEqual(preview.issues, ("private_restore_server_active",))

    @unittest.skipUnless(hasattr(os, "link"), "hardlinks unavailable")
    def test_sqlite_rejects_hardlinked_database_and_sidecar(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "data"
            connection = connect(root)
            connection.close()
            database = root / "private" / "console" / "mentat.sqlite3"
            outside_database = base / "database-link"
            os.link(database, outside_database)
            with self.assertRaises(MentatDatabaseError):
                connect(root)

            outside_database.unlink()
            wal = Path(f"{database}-wal")
            wal.write_bytes(b"unsafe-sidecar")
            if os.name == "posix":
                wal.chmod(0o600)
            os.link(wal, base / "wal-link")
            with self.assertRaises(MentatDatabaseError):
                connect(root)

    def test_waiting_private_writer_rechecks_restore_reservation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            entered = Event()
            attempt_write = Event()
            attempting = Event()
            lock_was_busy = Event()
            writer_done = Event()
            errors: list[Exception] = []

            def writer():
                entered.set()
                attempt_write.wait()
                try:
                    create_attachment(root, original_name="blocked.txt", content=b"blocked")
                except Exception as exc:
                    errors.append(exc)
                writer_done.set()

            thread = Thread(target=writer)
            try:
                thread.start()
                self.assertTrue(entered.wait(THREAD_TIMEOUT_SECONDS))
                with private_state_lock(root, allow_control=True):
                    real_root_lock_for = json_store._root_lock_for

                    def observed_root_lock(path):
                        root_lock = real_root_lock_for(path)

                        @contextmanager
                        def observed():
                            acquired = root_lock.acquire(blocking=False)
                            if acquired:
                                root_lock.release()
                            else:
                                lock_was_busy.set()
                            attempting.set()
                            with root_lock:
                                yield root_lock

                        return observed()

                    with patch.object(
                        json_store, "_root_lock_for", side_effect=observed_root_lock
                    ):
                        attempt_write.set()
                        self.assertTrue(attempting.wait(THREAD_TIMEOUT_SECONDS))
                        self.assertTrue(lock_was_busy.is_set())
                        config = root / "config"
                        config.mkdir(mode=0o700)
                        (config / "restore-state-v1.json").write_text("{}\n")
                        if os.name == "posix":
                            (config / "restore-state-v1.json").chmod(0o600)
                        self.assertFalse(writer_done.wait(0.1))
            finally:
                attempt_write.set()
                if thread.ident is not None:
                    thread.join(THREAD_TIMEOUT_SECONDS)
            self.assertFalse(thread.is_alive())
            self.assertTrue(writer_done.is_set())
            self.assertTrue(errors)
            self.assertFalse((root / "private" / "console" / "mentat.sqlite3").exists())

    def test_public_summaries_do_not_expose_storage_keys_or_paths(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = self.make_current(base, "source", "source")
            self.add_retained_attachment(root, "run_kept", b"private-content")
            summary = data_backup_restore.create_durable_backup(root).public_summary()
            encoded = json.dumps(summary)
            self.assertNotIn(str(base), encoded)
            self.assertNotIn("sha256", encoded)
            self.assertNotIn("storage_key", encoded)
            self.assertNotIn("private-content", encoded)


if __name__ == "__main__":
    unittest.main()
