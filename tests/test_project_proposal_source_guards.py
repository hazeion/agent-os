"""Current proposal source stays closed across SQL, Inbox and private restore."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import mentat_db
import owner_inbox
import private_console_unit
import run_attention

CREATED = "2026-09-29T12:00:00+00:00"
UPDATED = "2026-09-29T12:00:01+00:00"


def _current_with_runs(path: Path) -> sqlite3.Connection:
    private_console_unit._initialize_database(path)
    connection = sqlite3.connect(path)
    try:
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
    except BaseException:
        connection.close()
        raise
    return connection


class ProjectProposalSourceGuardTests(unittest.TestCase):
    def test_fixture_sql_failure_closes_connection_before_returning(self):
        for operation in ("execute", "commit"):
            with self.subTest(operation=operation):
                connection = Mock()
                getattr(connection, operation).side_effect = sqlite3.OperationalError("fixture failure")
                with patch.object(private_console_unit, "_initialize_database"), patch.object(
                    sqlite3, "connect", return_value=connection
                ):
                    with self.assertRaisesRegex(sqlite3.OperationalError, "fixture failure"):
                        _current_with_runs(Path("unused.sqlite3"))
                connection.close.assert_called_once_with()

    def test_current_validation_preserves_run_and_dependent_evidence(self):
        with TemporaryDirectory() as temporary:
            with closing(_current_with_runs(Path(temporary) / "current.sqlite3")) as connection:
                before = list(connection.iterdump())
                self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), "expected")
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), "expected")
                self.assertEqual(list(connection.iterdump()), before)
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
            with closing(_current_with_runs(Path(temporary) / "current.sqlite3")) as connection:
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
            with closing(_current_with_runs(Path(temporary) / "current.sqlite3")) as connection:
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
                self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), "expected")
                with self.assertRaises(run_attention.RunAttentionError):
                    run_attention.validate_run_attention_connection(connection)
                with self.assertRaises(owner_inbox.OwnerInboxError):
                    owner_inbox._validate_all_connection(connection)

    def test_populated_console_and_task_run_current_backup_restore(self):
        from agent_console_attachments import create_attachment, bind_run_attachment
        from run_repository import RunRepository, save_authoritative_run_summaries
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
                    idempotency_key="current-populated-backup-request",
                    dispatch_id="current-populated-backup-dispatch",
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
            (target / "private").mkdir(parents=True, mode=0o700)
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
                self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), "expected")


if __name__ == '__main__':
    unittest.main()
