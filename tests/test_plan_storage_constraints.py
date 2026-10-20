"""Current plan evidence, immutability, backup and UTF8 storage bounds."""
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

import mentat_db
import private_console_unit
from project_plans import publish_owner_plan, validate_plan_connection
from task_inputs import publish_task_inputs
from tests import test_task_inputs


class PlanStorageConstraintTests(unittest.TestCase):
    def test_current_plan_rows_refs_and_validated_restore_remain_exact(self):
        fixture = test_task_inputs.TaskInputStorageTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        prepared = publish_task_inputs(fixture.root, fixture.payload)
        publish_owner_plan(fixture.root, "project_mentat", "Garage organization", [{
            "task_id": "task_research", "expected_task_revision": 1,
            "agent_id": "agent_research", "input_version_id": prepared["input_id"],
            "after": [], "segment": 0, "max_attempts": 1,
            "max_wall_seconds": 900, "max_work_units": 100,
        }], expected_project_revision=1, expected_plan_revision=0)
        with closing(mentat_db.connect(fixture.root)) as connection:
            old_rows = connection.execute("SELECT * FROM mentat_plan_versions ORDER BY id").fetchall()
            old_refs = connection.execute("SELECT * FROM mentat_plan_input_refs ORDER BY version_id,input_id").fetchall()
        prior_unit = private_console_unit.capture_private_console_unit(fixture.root)
        private_console_unit.validate_private_console_unit(prior_unit)

        with closing(mentat_db.connect(fixture.root)) as connection:
            self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), "expected")
            self.assertEqual(connection.execute("SELECT * FROM mentat_plan_versions ORDER BY id").fetchall(), old_rows)
            self.assertEqual(connection.execute("SELECT * FROM mentat_plan_input_refs ORDER BY version_id,input_id").fetchall(), old_refs)
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            validate_plan_connection(connection)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE mentat_plan_versions SET format=2")
            connection.rollback()
        current_unit = private_console_unit.capture_private_console_unit(fixture.root)
        private_console_unit.validate_private_console_unit(current_unit)
        with TemporaryDirectory() as temporary:
            restored = private_console_unit.sanitize_owner_auth_restore_unit(prior_unit)
            destination = Path(temporary)
            (destination / "private").mkdir(mode=0o700)
            private_console_unit.materialize_private_console_unit(
                destination, restored, destination / "private" / "console"
            )
            with closing(mentat_db.connect(destination)) as connection:
                self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), "expected")
                self.assertEqual(connection.execute("SELECT * FROM mentat_plan_versions ORDER BY id").fetchall(), old_rows)

    def test_format2_sql_limit_counts_utf8_bytes(self):
        with closing(sqlite3.connect(":memory:")) as connection:
            for _, script in mentat_db.MIGRATIONS:
                connection.executescript(script)
            values = ("plan_version_" + "a" * 32, "plan_scope_" + "a" * 32,
                      1, 1, 2, '"' + "é" * 12287 + '"', "a" * 64, "owner_edit", 1.0)
            connection.execute("INSERT INTO mentat_plan_versions VALUES(?,?,?,?,?,?,?,?,?)", values)
            self.assertEqual(connection.execute(
                "SELECT length(CAST(content_json AS BLOB)) FROM mentat_plan_versions"
            ).fetchone()[0], 24576)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO mentat_plan_versions VALUES(?,?,?,?,?,?,?,?,?)",
                                   ("plan_version_" + "b" * 32, *values[1:5],
                                    '"' + "é" * 12288 + '"', *values[6:]))


if __name__ == '__main__':
    unittest.main()
