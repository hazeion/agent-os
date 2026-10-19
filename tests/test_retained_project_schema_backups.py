"""Current private backup authority and side-effect-free unsupported-root refusal."""
from pathlib import Path
import os
import sqlite3
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import data_backup_restore as backups
import mentat_db
import private_console_unit as units
from private_state import ensure_console_root
from tests import test_data_backup_restore as backup_tests


class CurrentProjectSchemaBackupTests(unittest.TestCase):
    def test_current_unit_preserves_embedded_agents_and_exact_schema(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "mentat.sqlite3"
            units._initialize_database(database)
            connection = sqlite3.connect(database)
            try:
                connection.execute("INSERT INTO agent_runtime_configs (id,runtime_type,runtime_agent_ref,created_at,updated_at) VALUES ('runtime-current','hermes','fixture',1,1)")
                connection.execute("INSERT INTO mentat_agents (id,name,runtime_config_id,capabilities_json,created_at,updated_at) VALUES ('agent-current','Current Agent','runtime-current','[]',1,1)")
                connection.commit()
            finally:
                connection.close()
            self.assertEqual(units._validate_and_filter_database(database, ()), ())
            raw = database.read_bytes()
            unit = units.PrivateConsoleUnit(units._empty_history(), raw, ())
            self.assertEqual(units.validate_private_console_unit(unit), unit)
            self.assertEqual(unit.agent_count, 1)
            self.assertEqual(database.read_bytes(), raw)
            self.assertEqual(units._database_schema_version(database), mentat_db.SCHEMA_VERSION)

    def test_old_and_future_source_schemas_refuse_before_hardening_or_lock(self):
        helper = backup_tests.DataBackupRestoreTests()
        for version in (mentat_db.SCHEMA_VERSION - 1, mentat_db.SCHEMA_VERSION + 1):
            with self.subTest(version=version), TemporaryDirectory() as temporary:
                base = Path(temporary)
                _seeds, root = helper.make_current(base, "source", "source")
                console = ensure_console_root(root)
                database = console / "mentat.sqlite3"
                units._initialize_database(database)
                connection = sqlite3.connect(database)
                try:
                    if version < mentat_db.SCHEMA_VERSION:
                        connection.execute("DELETE FROM schema_migrations WHERE version=?", (mentat_db.SCHEMA_VERSION,))
                    else:
                        connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (?,0)", (version,))
                    connection.commit()
                finally:
                    connection.close()
                if os.name == "posix":
                    console.chmod(0o755)
                    console.parent.chmod(0o755)
                def snapshot():
                    return {str(path.relative_to(root)): (stat.S_IMODE(path.stat().st_mode), path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None) for path in root.rglob("*")}
                before = snapshot()
                with patch.object(units, "ensure_console_root") as harden, patch.object(backups, "_durable_mutation_lock") as lock:
                    with self.assertRaisesRegex(units.PrivateConsoleUnitError, "private_database_unsupported"):
                        units.capture_private_console_unit(root)
                    result = backups.create_durable_backup(root)
                    self.assertEqual(result.status, "blocked")
                    harden.assert_not_called()
                    lock.assert_not_called()
                self.assertEqual(snapshot(), before)

    def test_retired_runtime_files_cannot_become_an_empty_current_unit(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            history = runtime / "agent-console-runs.json"
            history.write_bytes(b'{"schema_version":3,"runs":[]}')
            before = history.read_bytes()
            with patch.object(units, "empty_private_console_unit") as empty:
                with self.assertRaisesRegex(units.PrivateConsoleUnitError, "private_database_unsupported"):
                    units.capture_private_console_unit(root)
                empty.assert_not_called()
            self.assertEqual(history.read_bytes(), before)
            self.assertFalse((root / "private").exists())

    def test_current_version_does_not_bypass_exact_schema_validation(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "mentat.sqlite3"
            units._initialize_database(database)
            connection = sqlite3.connect(database)
            try:
                connection.execute("ALTER TABLE agent_runtime_configs ADD COLUMN unexpected TEXT")
                connection.commit()
            finally:
                connection.close()
            raw = database.read_bytes()
            with self.assertRaises(units.PrivateConsoleUnitError):
                units.validate_private_console_unit(units.PrivateConsoleUnit(units._empty_history(), raw, ()))
            self.assertEqual(database.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
