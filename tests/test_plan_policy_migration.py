"""Schema-37 plan-policy storage must retain exact format-1 evidence."""

from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import mentat_db
import private_console_unit
from project_plans import publish_owner_plan, validate_plan_connection
from task_inputs import publish_task_inputs
from tests import test_task_inputs


class PlanPolicyMigrationTests(unittest.TestCase):
    def test_schema36_plan_rows_refs_and_backup_upgrade_exactly(self):
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
        # Recreate the exact released schema-36 table around real saved data.
        # All other authority rows remain the fixture's original values.
        with closing(sqlite3.connect(":memory:")) as old_schema:
            for version, script in mentat_db.MIGRATIONS:
                if version > 36:
                    break
                old_schema.executescript(script)
            source_sql = [row[0] for row in old_schema.execute(
                "SELECT sql FROM sqlite_master WHERE name IN "
                "('mentat_plan_versions','mentat_plan_version_immutable',"
                "'mentat_plan_version_no_delete') "
                "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END,name"
            )]
        with closing(sqlite3.connect(mentat_db.database_path(fixture.root))) as connection:
            connection.execute("PRAGMA foreign_keys=OFF")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TRIGGER mentat_plan_version_immutable")
            connection.execute("DROP TRIGGER mentat_plan_version_no_delete")
            connection.execute("DROP TABLE mentat_plan_versions")
            for statement in source_sql:
                connection.execute(statement)
            connection.executemany("INSERT INTO mentat_plan_versions VALUES(?,?,?,?,?,?,?,?,?)", old_rows)
            connection.execute("DELETE FROM schema_migrations WHERE version=37")
            connection.commit()
            self.assertEqual(mentat_db.schema_signature_state(connection, 36), "expected")
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        prior_unit = private_console_unit.capture_private_console_unit(fixture.root)
        private_console_unit.validate_private_console_unit(prior_unit)

        with closing(mentat_db.connect(fixture.root)) as connection:
            self.assertEqual(mentat_db.schema_signature_state(connection, 37), "expected")
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
            (destination / "private").mkdir()
            private_console_unit.materialize_private_console_unit(
                destination, restored, destination / "private" / "console"
            )
            with closing(mentat_db.connect(destination)) as connection:
                self.assertEqual(mentat_db.schema_signature_state(connection, 37), "expected")
                self.assertEqual(connection.execute("SELECT * FROM mentat_plan_versions ORDER BY id").fetchall(), old_rows)

    def test_schema36_drift_rolls_back_without_upgrade_receipt(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite3"
            private_console_unit._initialize_database(path, schema_version=36)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("DROP TRIGGER mentat_plan_version_immutable")
                with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "schema 36"):
                    mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 36)

    def test_schema37_format2_sql_limit_counts_utf8_bytes(self):
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

    def test_schema36_upgrade_requires_temporary_headroom(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite3"
            private_console_unit._initialize_database(path, schema_version=36)
            with closing(sqlite3.connect(path)) as connection:
                with patch.object(mentat_db.shutil, "disk_usage", return_value=SimpleNamespace(free=0)):
                    with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "headroom"):
                        mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 36)

    def test_schema36_upgrade_respects_private_database_ceiling(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite3"
            private_console_unit._initialize_database(path, schema_version=36)
            with closing(sqlite3.connect(path)) as connection:
                with patch.object(mentat_db, "MAX_READONLY_DATABASE_BYTES", 1024):
                    with self.assertRaisesRegex(mentat_db.MentatDatabaseError, "database headroom"):
                        mentat_db.migrate(connection)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 36)

    def test_interrupted_shadow_copy_rolls_back_table_and_receipt(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite3"
            private_console_unit._initialize_database(path, schema_version=36)
            execute = mentat_db._execute_script_in_active_transaction

            def interrupted(connection, script):
                if "CREATE TABLE mentat_plan_versions_next" in script:
                    execute(connection, script.split("DROP TRIGGER mentat_plan_version_immutable;")[0])
                    raise RuntimeError("injected interruption")
                execute(connection, script)

            with closing(sqlite3.connect(path)) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                with patch.object(mentat_db, "_execute_script_in_active_transaction", side_effect=interrupted):
                    with self.assertRaisesRegex(RuntimeError, "injected interruption"):
                        mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 36), "expected")
                self.assertIsNone(connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='mentat_plan_versions_next'"
                ).fetchone())
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 36)


if __name__ == "__main__":
    unittest.main()
