"""Schema 41 reserves a distinct proposal source while all admission is closed."""

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import mentat_db
import owner_inbox
import private_console_unit
import run_attention


CREATED = "2026-09-29T12:00:00+00:00"
UPDATED = "2026-09-29T12:00:01+00:00"


def _schema40_with_runs(path: Path) -> sqlite3.Connection:
    private_console_unit._initialize_database(path, schema_version=40)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        "INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,status,"
        "dispatch_state,created_at,updated_at) "
        "VALUES('run_console','console','hermes','[]','reserved','reserved',?,?)",
        (CREATED, UPDATED),
    )
    connection.execute(
        "INSERT INTO mentat_runs(id,source,task_id,task_revision,runtime_type,"
        "capabilities_json,status,dispatch_state,created_at,updated_at) "
        "VALUES('run_task','task_dispatch','task_garage',1,'hermes','[]',"
        "'reserved','reserved',?,?)",
        (CREATED, UPDATED),
    )
    connection.execute(
        "INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,status,"
        "dispatch_state,retry_of_run_id,created_at,updated_at) "
        "VALUES('run_retry','console','hermes','[]','reserved','reserved',"
        "'run_console',?,?)", (CREATED, UPDATED),
    )
    connection.execute(
        "INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,status,"
        "dispatch_state,resume_of_run_id,created_at,updated_at) "
        "VALUES('run_resume','console','hermes','[]','reserved','reserved',"
        "'run_console',?,?)", (CREATED, UPDATED),
    )
    connection.execute(
        "INSERT INTO mentat_agent_events(run_id,sequence,id,event_type,source_type,"
        "source_key,occurred_at,summary,payload_digest) "
        "VALUES('run_console',1,'event_created','run.created','run.created',"
        "'source_event',?,'Run reserved',?)",
        (CREATED, "a" * 64),
    )
    connection.execute(
        "UPDATE mentat_runs SET status='unknown',dispatch_state='unknown',"
        "state_revision=state_revision+1 WHERE id='run_console'"
    )
    connection.commit()
    return connection


class ProjectProposalSourceMigrationTests(unittest.TestCase):
    def test_populated_exact_upgrade_preserves_run_and_dependent_evidence(self):
        with TemporaryDirectory() as temporary:
            with closing(_schema40_with_runs(Path(temporary) / "old.sqlite3")) as connection:
                before = mentat_db._run_source_migration_snapshot(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 40), "expected")
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
                self.assertEqual(mentat_db._run_source_migration_snapshot(connection), before)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(connection.execute(
                    "SELECT id,source,retry_of_run_id,resume_of_run_id "
                    "FROM mentat_runs ORDER BY id"
                ).fetchall(), [
                    ("run_console", "console", None, None),
                    ("run_resume", "console", None, "run_console"),
                    ("run_retry", "console", "run_console", None),
                    ("run_task", "task_dispatch", None, None),
                ])
                self.assertEqual(connection.execute(
                    "SELECT source_key FROM mentat_agent_events WHERE run_id='run_console'"
                ).fetchone()[0], "source_event")
                self.assertIsNotNone(connection.execute(
                    "SELECT item_id FROM mentat_run_attention WHERE run_id='run_console'"
                ).fetchone()[0])

    def test_direct_sql_proposal_insert_and_update_abort_before_attention(self):
        with TemporaryDirectory() as temporary:
            with closing(_schema40_with_runs(Path(temporary) / "old.sqlite3")) as connection:
                mentat_db.migrate(connection)
                with self.assertRaisesRegex(sqlite3.IntegrityError, "proposal_unqualified"):
                    connection.execute(
                        "INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,"
                        "status,dispatch_state,created_at,updated_at) "
                        "VALUES('run_forged','project_proposal','hermes','[]',"
                        "'reserved','reserved',?,?)", (CREATED, UPDATED),
                    )
                with self.assertRaisesRegex(sqlite3.IntegrityError, "proposal_unqualified"):
                    connection.execute(
                        "UPDATE mentat_runs SET source='project_proposal' WHERE id='run_console'"
                    )
                self.assertIsNone(connection.execute(
                    "SELECT 1 FROM mentat_runs WHERE id='run_forged'"
                ).fetchone())
                self.assertEqual(connection.execute(
                    "SELECT source FROM mentat_runs WHERE id='run_console'"
                ).fetchone()[0], "console")

    def test_tampered_proposal_row_cannot_cross_owner_inbox_boundary(self):
        with TemporaryDirectory() as temporary:
            with closing(_schema40_with_runs(Path(temporary) / "old.sqlite3")) as connection:
                mentat_db.migrate(connection)
                owner_inbox._validate_all_connection(connection)
                trigger = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name='mentat_runs_project_proposal_closed_update'"
                ).fetchone()[0]
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DROP TRIGGER mentat_runs_project_proposal_closed_update")
                connection.execute(
                    "UPDATE mentat_runs SET source='project_proposal' WHERE id='run_console'"
                )
                connection.execute(trigger)
                connection.commit()
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
                with self.assertRaises(run_attention.RunAttentionError):
                    run_attention.validate_run_attention_connection(connection)
                with self.assertRaises(owner_inbox.OwnerInboxError):
                    owner_inbox._validate_all_connection(connection)

    def test_postcopy_failure_rolls_back_to_exact_schema40(self):
        with TemporaryDirectory() as temporary:
            with closing(_schema40_with_runs(Path(temporary) / "old.sqlite3")) as connection:
                before = mentat_db._run_source_migration_snapshot(connection)
                original = mentat_db._run_source_migration_snapshot
                calls = 0
                def changed(handle):
                    nonlocal calls
                    calls += 1
                    result = original(handle)
                    return result if calls == 1 else (*result, ("injected", 1, "0" * 64, 1))
                with patch.object(mentat_db, "_run_source_migration_snapshot", side_effect=changed):
                    with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "changed retained evidence"):
                        mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 40), "expected")
                self.assertEqual(mentat_db._run_source_migration_snapshot(connection), before)
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("PRAGMA legacy_alter_table").fetchone()[0], 0)

    def test_copy_rename_and_trigger_failures_roll_back_complete_old_run_graph(self):
        class FailingConnection(sqlite3.Connection):
            fail_prefix = ""
            def execute(self, sql, *args, **kwargs):
                if self.fail_prefix and str(sql).lstrip().startswith(self.fail_prefix):
                    raise sqlite3.OperationalError("injected_run_migration_failure")
                return super().execute(sql, *args, **kwargs)

        for marker in ("INSERT INTO mentat_runs_next SELECT *", "ALTER TABLE mentat_runs_next RENAME",
                       "CREATE TRIGGER mentat_runs_conversation_identity_immutable"):
            with self.subTest(marker=marker), TemporaryDirectory() as temporary:
                path = Path(temporary) / "old.sqlite3"
                with closing(_schema40_with_runs(path)) as source:
                    before = mentat_db._run_source_migration_snapshot(source)
                with closing(sqlite3.connect(path, factory=FailingConnection)) as connection:
                    connection.execute("PRAGMA foreign_keys=ON")
                    connection.fail_prefix = marker
                    with self.assertRaisesRegex(sqlite3.OperationalError,
                                                "injected_run_migration_failure"):
                        mentat_db.migrate(connection)
                    connection.fail_prefix = ""
                    self.assertEqual(mentat_db.schema_signature_state(connection, 40), "expected")
                    self.assertEqual(mentat_db._run_source_migration_snapshot(connection), before)
                    self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                    self.assertEqual(connection.execute("PRAGMA legacy_alter_table").fetchone()[0], 0)

    def test_drift_and_headroom_fail_before_schema41_receipt(self):
        with TemporaryDirectory() as temporary:
            with closing(_schema40_with_runs(Path(temporary) / "drift.sqlite3")) as connection:
                connection.execute("DROP TRIGGER mentat_project_planning_input_legacy_sealed")
                with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "schema 40"):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0], 40)
        with TemporaryDirectory() as temporary:
            with closing(_schema40_with_runs(Path(temporary) / "small.sqlite3")) as connection:
                with patch.object(mentat_db.shutil, "disk_usage",
                                  return_value=SimpleNamespace(free=0)):
                    with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "disk headroom"):
                        mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 40), "expected")

    def test_large_run_documents_use_bounded_batches_and_full_wal_reservation(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.sqlite3"
            with closing(_schema40_with_runs(path)) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                document = "{}" + " " * (1024 * 1024 - 2)
                connection.executemany(
                    "INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,"
                    "status,dispatch_state,task_snapshot_json,details_json,created_at,updated_at) "
                    "VALUES(?,'console','hermes','[]','reserved','reserved',?,?,?,?)",
                    ((f"run_large_{index:03d}", document, document, CREATED, UPDATED)
                     for index in range(20)),
                )
                connection.commit()
                with patch.object(mentat_db.shutil, "disk_usage",
                                  return_value=SimpleNamespace(free=64 * 1024 * 1024)):
                    with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "disk headroom"):
                        mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 40), "expected")
                before = mentat_db._run_source_migration_snapshot(connection)
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
                self.assertEqual(mentat_db._run_source_migration_snapshot(connection), before)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_multibyte_run_row_is_charged_by_bytes_before_shadow_copy(self):
        with TemporaryDirectory() as temporary:
            with closing(_schema40_with_runs(Path(temporary) / "unicode.sqlite3")) as connection:
                document = '"' + "🚲" * 700_000 + '"'
                connection.execute(
                    "INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,"
                    "status,dispatch_state,task_snapshot_json,details_json,created_at,updated_at) "
                    "VALUES('run_unicode','console','hermes','[]','reserved','reserved',?,?,?,?)",
                    (document, document, CREATED, UPDATED),
                )
                connection.commit()
                before = mentat_db._run_source_migration_snapshot(connection)
                page_size = connection.execute("PRAGMA page_size").fetchone()[0]
                page_count = connection.execute("PRAGMA page_count").fetchone()[0]
                with patch.object(mentat_db, "MAX_READONLY_DATABASE_BYTES",
                                  page_size * page_count + 4 * 1024 * 1024):
                    with self.assertRaisesRegex(mentat_db.MentatDatabaseError,
                                                "database headroom"):
                        mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 40), "expected")
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
                self.assertEqual(mentat_db._run_source_migration_snapshot(connection), before)

    def test_schema41_virtual_backup_and_schema5_export_remain_supported(self):
        from task_repository import _schema5_private_unit
        unit = private_console_unit.empty_private_console_unit()
        private_console_unit.validate_private_console_unit(unit)
        compatible = _schema5_private_unit(unit)
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.deserialize(compatible.database_raw)
            self.assertEqual(connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0], 5)
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name='mentat_runs_project_proposal_closed_insert'"
            ).fetchone())

    def test_populated_console_and_task_run_backup_restore_and_schema5_export(self):
        from agent_console_attachments import create_attachment, bind_run_attachment
        from run_repository import RunRepository, save_authoritative_run_summaries
        from task_repository import _schema5_private_unit
        from tests.test_run_repository import RunRepositoryTests, run_fixture

        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            task, binding = RunRepositoryTests().prepare_dispatch_root(root)
            console_run = run_fixture("run_console_backup", status="failed", bound=False)
            event_run = run_fixture("run_event_backup", status="completed", bound=False)
            event_run["events"] = [{
                "id": "event_backup_complete", "run_id": "run_event_backup",
                "sequence": 1, "cursor": 1, "type": "complete", "kind": "complete",
                "timestamp": UPDATED, "display_text": "Response complete",
                "message": "Response complete", "data": {},
            }]
            save_authoritative_run_summaries(root, [console_run, event_run])
            with closing(mentat_db.connect(root)) as connection:
                RunRepository(connection).reserve_dispatch(
                    idempotency_key="schema41-populated-backup-request",
                    dispatch_id="schema41-populated-backup-dispatch",
                    run_id="run_task_backup", task=task, task_revision=1,
                    agent_id="agent-main", runtime_type="hermes",
                    runtime_config_id="config-main", binding_digest=binding,
                    capabilities=("run.start",),
                )
            attachment = create_attachment(
                root, original_name="evidence.md", content=b"Synthetic retained evidence"
            )
            bound = bind_run_attachment(root, attachment["id"], "run_console_backup")
            console_run["attachments"] = [bound]
            save_authoritative_run_summaries(root, [console_run, event_run])
            with closing(mentat_db.connect(root)) as connection:
                sources = [tuple(row) for row in connection.execute(
                    "SELECT id,source FROM mentat_runs ORDER BY id"
                )]
            self.assertEqual(sources, [
                ("run_console_backup", "console"),
                ("run_event_backup", "console"),
                ("run_task_backup", "task_dispatch"),
            ])
            unit = private_console_unit.capture_private_console_unit(root)
            private_console_unit.validate_private_console_unit(unit)
            target = Path(temporary) / "restored"
            (target / "private").mkdir(parents=True)
            private_console_unit.materialize_private_console_unit(
                target, unit, target / "private" / "console",
            )
            with closing(mentat_db.connect(target)) as connection:
                self.assertEqual([tuple(row) for row in connection.execute(
                    "SELECT id,source FROM mentat_runs ORDER BY id"
                )], sources)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM run_attachments WHERE run_id='run_console_backup'"
                ).fetchone()[0], 1)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM mentat_agent_events WHERE run_id='run_event_backup'"
                ).fetchone()[0], 1)
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
            compatible = _schema5_private_unit(unit)
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.deserialize(compatible.database_raw)
                self.assertEqual(connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0], 5)
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='mentat_runs_project_proposal_closed_insert'"
                ).fetchone())


if __name__ == "__main__":
    unittest.main()
