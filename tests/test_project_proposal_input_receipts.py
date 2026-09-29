"""Schema-42 proposal receipt evidence is retained while dispatch stays closed."""

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest

import mentat_db
import private_console_unit
from task_repository import _schema5_private_unit
from project_proposal_input_receipts import (
    ProjectProposalInputReceiptError, _digest,
    validate_project_proposal_input_connection,
)
from tests import test_project_planning_inputs


CREATED = "2026-09-29T12:00:00+00:00"


class ProjectProposalInputReceiptTests(unittest.TestCase):
    def test_exact_schema41_upgrade_keeps_proposal_dispatch_closed(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mentat.sqlite3"
            private_console_unit._initialize_database(path, schema_version=41)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                self.assertEqual(mentat_db.schema_signature_state(connection, 41), "expected")
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 42), "expected")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(validate_project_proposal_input_connection(connection), [[], []])
                with self.assertRaisesRegex(sqlite3.IntegrityError, "proposal_unqualified"):
                    connection.execute(
                        "INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,"
                        "status,dispatch_state,created_at,updated_at) VALUES"
                        "('run_guarded','project_proposal','hermes','[]','reserved',"
                        "'reserved',?,?)", (CREATED, CREATED),
                    )

    def test_source_schema_drift_blocks_upgrade_without_receipt(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mentat.sqlite3"
            private_console_unit._initialize_database(path, schema_version=41)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP TRIGGER mentat_runs_project_proposal_closed_insert")
                connection.commit()
                with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "schema 41"):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0], 41)

    def setUp(self):
        self.fixture = test_project_planning_inputs.ProjectPlanningInputStorageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.input_id = self.fixture.insert_version()

    def _insert_consistent_receipt(self, connection: sqlite3.Connection) -> str:
        selected = connection.execute(
            "SELECT project_id,project_incarnation,project_revision,lead_role_id,"
            "lead_revision,agent_id,agent_incarnation,agent_revision,binding_digest,"
            "context_id,grant_revision,instructions,created_at "
            "FROM mentat_project_planning_input_versions WHERE id=?", (self.input_id,),
        ).fetchone()
        context = connection.execute(
            "SELECT revision,brief FROM mentat_project_context_versions WHERE id=?",
            (selected[9],),
        ).fetchone()
        runtime = connection.execute(
            "SELECT c.runtime_type,c.id FROM mentat_agents a "
            "JOIN agent_runtime_configs c ON c.id=a.runtime_config_id WHERE a.id=?",
            (selected[5],),
        ).fetchone()
        files = connection.execute(
            "SELECT attachment_id,blob_id,sha256,byte_size,kind,mime_type "
            "FROM mentat_project_planning_input_files WHERE input_id=? ORDER BY ordinal",
            (self.input_id,),
        ).fetchall()
        run_id = "run_project_proposal_test"
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='mentat_runs_project_proposal_closed_insert'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER mentat_runs_project_proposal_closed_insert")
        connection.execute(
            "INSERT INTO mentat_runs(id,source,agent_id,runtime_type,runtime_config_id,"
            "runtime_binding_digest,capabilities_json,status,dispatch_state,created_at,updated_at) "
            "VALUES(?,'project_proposal',?,?,?,?,'[]','reserved','reserved',?,?)",
            (run_id, selected[5], runtime[0], runtime[1], selected[8], CREATED, CREATED),
        )
        connection.execute(trigger)
        created_at = max(time.time(), selected[12])
        manifest = _digest([
            run_id, self.input_id, selected[0], selected[1], selected[2],
            selected[3], selected[4], selected[5], selected[6], selected[7],
            runtime[0], runtime[1], selected[8], selected[9], context[0],
            selected[10], _digest([]), "1" * 64, "2" * 64, "3" * 64,
            "4" * 64, created_at, context[1], selected[11],
            [list(item) for item in files],
        ])
        row = (run_id, self.input_id, selected[0], selected[1], selected[2],
               selected[3], selected[4], selected[5], selected[6], selected[7],
               runtime[0], runtime[1], selected[8], selected[9], context[0],
               selected[10], _digest([]), "1" * 64, "2" * 64, "3" * 64,
               "4" * 64, manifest, created_at)
        connection.execute(
            "INSERT INTO mentat_project_proposal_input_receipts VALUES("
            + ",".join("?" for _ in row) + ")", row,
        )
        for ordinal, item in enumerate(files):
            connection.execute(
                "INSERT INTO mentat_project_proposal_input_files VALUES(?,?,?,?,?,?,?,?)",
                (run_id, ordinal, *item),
            )
        return run_id

    def test_exact_historical_graph_and_file_pin(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_id = self._insert_consistent_receipt(connection)
            self.assertEqual(len(validate_project_proposal_input_connection(connection)[0]), 1)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_retained_attachments WHERE attachment_id=?",
                (self.fixture.fixture.attachment,),
            ).fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            connection.rollback()  # The forged Run never becomes usable runtime state.

    def test_empty_receipt_backup_restore_and_schema5_compatibility(self):
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target / "private").mkdir(parents=True, mode=0o700)
            private_console_unit.materialize_private_console_unit(
                target, private_console_unit.sanitize_owner_auth_restore_unit(unit),
                target / "private" / "console",
            )
            with closing(mentat_db.connect(target)) as connection:
                self.assertEqual(mentat_db.schema_signature_state(connection, 42), "expected")
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM mentat_project_proposal_input_receipts"
                ).fetchone()[0], 0)
            compatible = _schema5_private_unit(unit)
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.deserialize(compatible.database_raw)
                self.assertEqual(connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0], 5)
                self.assertIsNone(connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='mentat_project_proposal_input_receipts'"
                ).fetchone())

    def test_modified_receipt_or_ordered_file_is_rejected(self):
        for target in ("manifest", "authorization", "qualification", "operations", "limits", "file"):
            with self.subTest(target=target), closing(mentat_db.connect(self.root)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._insert_consistent_receipt(connection)
                if target != "file":
                    connection.execute("DROP TRIGGER mentat_project_proposal_input_receipt_immutable")
                    connection.execute(
                        "UPDATE mentat_project_proposal_input_receipts SET "
                        + {"manifest": "manifest_digest", "authorization": "authorization_digest",
                           "qualification": "qualification_digest", "operations": "operations_digest",
                           "limits": "limits_digest"}[target] + "=?", ("0" * 64,),
                    )
                else:
                    connection.execute("DROP TRIGGER mentat_project_proposal_input_file_immutable")
                    connection.execute(
                        "UPDATE mentat_project_proposal_input_files SET sha256=?",
                        ("0" * 64,),
                    )
                with self.assertRaises(ProjectProposalInputReceiptError):
                    validate_project_proposal_input_connection(connection)
                connection.rollback()


if __name__ == "__main__":
    unittest.main()
