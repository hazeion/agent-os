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
from private_state import ensure_console_root, fresh_console_storage_issue
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

    def test_only_current_empty_history_is_a_fresh_source(self):
        for payload, allowed in ((b'{"schema_version":3,"runs":[]}', True),
                                 (b'{"schema_version":2,"runs":[]}', False),
                                 (b'{"schema_version":3,"runs":[{"id":"run_existing"}]}', False)):
            with self.subTest(payload=payload), TemporaryDirectory() as temporary:
                root = Path(temporary)
                console = ensure_console_root(root)
                history = console / "agent-console-runs.json"
                history.write_bytes(payload)
                history.chmod(0o600)
                if allowed:
                    unit = units.capture_private_console_unit(root)
                    self.assertEqual(unit.run_count, 0)
                else:
                    with self.assertRaises(units.PrivateConsoleUnitError):
                        units.capture_private_console_unit(root)
                self.assertEqual(history.read_bytes(), payload)
                self.assertFalse((console / "mentat.sqlite3").exists())

    def test_fresh_admission_refuses_ambiguous_history_and_unknown_storage_readonly(self):
        histories = (
            b'{"schema_version":3,"schema_version":3,"runs":[]}',
            b'{"schema_version":true,"runs":[]}',
            b'{"schema_version":3,"runs":[],"extra":0}',
            b'{"schema_version":4,"runs":[]}',
        )
        for raw in histories:
            with self.subTest(raw=raw), TemporaryDirectory() as temporary:
                root = Path(temporary)
                console = ensure_console_root(root)
                history = console / "agent-console-runs.json"
                history.write_bytes(raw)
                history.chmod(0o600)
                before = history.stat()
                self.assertIsNotNone(fresh_console_storage_issue(root))
                self.assertEqual(history.read_bytes(), raw)
                self.assertEqual((history.stat().st_mode, history.stat().st_mtime_ns),
                                 (before.st_mode, before.st_mtime_ns))
                self.assertFalse((console / "mentat.sqlite3").exists())
        for name in ("agent-registry.sqlite3", "agent-registry.sqlite3-wal", "unknown", "blobs"):
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                root = Path(temporary)
                console = ensure_console_root(root)
                evidence = console / name
                evidence.write_bytes(b"retained evidence")
                self.assertIsNotNone(fresh_console_storage_issue(root))
                self.assertEqual(evidence.read_bytes(), b"retained evidence")
                self.assertFalse((console / "mentat.sqlite3").exists())

    def test_fresh_admission_refuses_runtime_sidecar_evidence_without_hardening(self):
        for name in ("mentat.sqlite3-wal", "agent-registry.sqlite3-shm", "agent-console-runs.json"):
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                root = Path(temporary)
                runtime = root / "runtime"
                runtime.mkdir(mode=0o755)
                evidence = runtime / name
                evidence.write_bytes(b"retained evidence")
                before = (runtime.stat().st_mode, evidence.stat().st_mode, evidence.stat().st_mtime_ns)
                self.assertEqual(fresh_console_storage_issue(root), "private_database_unsupported")
                self.assertEqual(evidence.read_bytes(), b"retained evidence")
                self.assertEqual((runtime.stat().st_mode, evidence.stat().st_mode, evidence.stat().st_mtime_ns), before)
                self.assertFalse((root / "private").exists())

    @unittest.skipUnless(os.name == "posix", "POSIX link and permission metadata")
    def test_fresh_history_rechecks_link_count_and_mode_after_read(self):
        for change in ("link", "mode"):
            with self.subTest(change=change), TemporaryDirectory() as temporary:
                root = Path(temporary)
                console = ensure_console_root(root)
                history = console / "agent-console-runs.json"
                raw = b'{"schema_version":3,"runs":[]}'
                history.write_bytes(raw)
                history.chmod(0o600)
                real_read = os.read
                changed = False
                def mutate_after_read(descriptor, size):
                    nonlocal changed
                    data = real_read(descriptor, size)
                    if data and not changed:
                        changed = True
                        if change == "link":
                            os.link(history, root / "outside-history")
                        else:
                            history.chmod(0o644)
                    return data
                with patch("private_state.os.read", side_effect=mutate_after_read):
                    self.assertEqual(fresh_console_storage_issue(root), "private_history_invalid")
                self.assertTrue(changed)
                self.assertEqual(history.read_bytes(), raw)
                self.assertFalse((console / "mentat.sqlite3").exists())

    def test_fresh_capture_rechecks_storage_after_empty_template_construction(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            console = ensure_console_root(root)
            unit = units.empty_private_console_unit()
            def appeared():
                (console / "mentat.sqlite3").write_bytes(b"appearing authority")
                return unit
            with patch.object(units, "empty_private_console_unit", side_effect=appeared):
                with self.assertRaisesRegex(units.PrivateConsoleUnitError, "private_console_changed"):
                    units.capture_private_console_unit(root)
            self.assertEqual((console / "mentat.sqlite3").read_bytes(), b"appearing authority")

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
