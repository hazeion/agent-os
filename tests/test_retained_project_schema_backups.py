from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

import mentat_db
import private_console_unit as units


class RetainedProjectSchemaBackupTests(unittest.TestCase):
    def test_retained_project_schemas_preserve_nonempty_agent_registry(self):
        for version in (38, 39, 40, 41, 42):
            with self.subTest(version=version), TemporaryDirectory() as temporary:
                database = Path(temporary) / "mentat.sqlite3"
                units._initialize_database(database, schema_version=version)
                connection = sqlite3.connect(database)
                try:
                    connection.execute(
                        "INSERT INTO agent_runtime_configs "
                        "(id, runtime_type, runtime_agent_ref, created_at, updated_at) "
                        "VALUES ('runtime-retained', 'hermes', 'fixture', 1, 1)"
                    )
                    connection.execute(
                        "INSERT INTO mentat_agents "
                        "(id, name, runtime_config_id, capabilities_json, created_at, updated_at) "
                        "VALUES ('agent-retained', 'Retained Agent', 'runtime-retained', '[]', 1, 1)"
                    )
                    connection.commit()
                    agents_before = connection.execute(
                        "SELECT * FROM mentat_agents ORDER BY id"
                    ).fetchall()
                    configs_before = connection.execute(
                        "SELECT * FROM agent_runtime_configs ORDER BY id"
                    ).fetchall()
                finally:
                    connection.close()
                self.assertEqual(units._validate_and_filter_database(database, ()), ())
                raw = database.read_bytes()
                unit = units.PrivateConsoleUnit(units._empty_history(), raw, None, ())
                self.assertEqual(units.validate_private_console_unit(unit), unit)
                self.assertEqual(database.read_bytes(), raw)
                connection = sqlite3.connect(database)
                try:
                    self.assertEqual(
                        connection.execute("SELECT * FROM mentat_agents ORDER BY id").fetchall(),
                        agents_before,
                    )
                    self.assertEqual(
                        connection.execute("SELECT * FROM agent_runtime_configs ORDER BY id").fetchall(),
                        configs_before,
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT a.id, a.name, a.capabilities_json, c.runtime_agent_ref "
                            "FROM mentat_agents a JOIN agent_runtime_configs c "
                            "ON a.runtime_config_id = c.id"
                        ).fetchall(),
                        [("agent-retained", "Retained Agent", "[]", "fixture")],
                    )
                finally:
                    connection.close()
                self.assertEqual(units._database_schema_version(database), version)

    def test_retained_project_schemas_filter_and_validate_complete_empty_units(self):
        for version in (38, 39, 40, 41, 42):
            with self.subTest(version=version), TemporaryDirectory() as temporary:
                self.assertLess(version, mentat_db.SCHEMA_VERSION)
                self.assertIn(version, units.SUPPORTED_DATABASE_SCHEMA_VERSIONS)
                database = Path(temporary) / "mentat.sqlite3"
                units._initialize_database(database, schema_version=version)
                self.assertEqual(units._validate_and_filter_database(database, ()), ())
                self.assertEqual(units._database_schema_version(database), version)
                raw = database.read_bytes()
                unit = units.PrivateConsoleUnit(units._empty_history(), raw, None, ())
                self.assertEqual(units.validate_private_console_unit(unit), unit)
                self.assertEqual(database.read_bytes(), raw)

    def test_future_schema_remains_unsupported(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "mentat.sqlite3"
            units._initialize_database(database)
            self.assertEqual(units._validate_and_filter_database(database, ()), ())
            baseline = units.PrivateConsoleUnit(
                units._empty_history(), database.read_bytes(), None, ()
            )
            self.assertEqual(units.validate_private_console_unit(baseline), baseline)
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                    (mentat_db.SCHEMA_VERSION + 1,),
                )
                connection.commit()
            finally:
                connection.close()
            unit = units.PrivateConsoleUnit(
                units._empty_history(), database.read_bytes(), None, ()
            )
            with self.assertRaises(units.PrivateConsoleUnitError):
                units.validate_private_console_unit(unit)

    def test_retained_version_does_not_bypass_exact_schema_validation(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "mentat.sqlite3"
            units._initialize_database(database, schema_version=38)
            self.assertEqual(units._validate_and_filter_database(database, ()), ())
            baseline = units.PrivateConsoleUnit(
                units._empty_history(), database.read_bytes(), None, ()
            )
            self.assertEqual(units.validate_private_console_unit(baseline), baseline)
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    "ALTER TABLE agent_runtime_configs ADD COLUMN unexpected TEXT"
                )
                connection.commit()
            finally:
                connection.close()
            unit = units.PrivateConsoleUnit(
                units._empty_history(), database.read_bytes(), None, ()
            )
            with self.assertRaises(units.PrivateConsoleUnitError):
                units.validate_private_console_unit(unit)
