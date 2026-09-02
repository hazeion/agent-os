from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from mentat_db import MIGRATIONS, MentatDatabaseError, SCHEMA_VERSION, connect, database_path, ensure_private_console_dir, schema_signature_state
from private_console_unit import PrivateConsoleUnitError, _validate_planning_deletion_receipts


class Schema22ForwardMigrationTests(unittest.TestCase):
    def _schema22(self, root: Path) -> Path:
        ensure_private_console_dir(root)
        path = database_path(root)
        connection = sqlite3.connect(path)
        try:
            for version, script in MIGRATIONS:
                if version > 22:
                    break
                connection.executescript(script)
                connection.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)", (version,))
            connection.commit()
        finally:
            connection.close()
        path.chmod(0o600)
        return path

    def test_exact_schema22_upgrades_to_the_content_free_deletion_receipt(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._schema22(root)
            connection = connect(root)
            try:
                self.assertEqual(SCHEMA_VERSION, 23)
                self.assertEqual(schema_signature_state(connection, 23), "expected")
                connection.execute(
                    "INSERT INTO mentat_planning_deletion_receipts (confirmation_digest, target_kind, target_digest, closure_digest, project_count, task_count, conversation_count, run_count, artifact_count, state, created_at) VALUES (?, 'task', ?, ?, 0, 1, 0, 0, 0, 'deleted', ?)",
                    ("a" * 64, "b" * 64, "c" * 64, "2026-09-02T12:00:00Z"),
                )
                connection.commit()
                _validate_planning_deletion_receipts(connection)
            finally:
                connection.close()

    def test_schema22_drift_fails_before_the_receipt_table_is_created(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._schema22(root)
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                connection.execute("DROP TABLE mentat_codex_task_create_receipts")
            finally:
                connection.close()
            with self.assertRaisesRegex(MentatDatabaseError, "schema 22 cannot be safely upgraded"):
                connect(root)
            check = sqlite3.connect(path)
            try:
                self.assertEqual(check.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 22)
                self.assertIsNone(check.execute("SELECT name FROM sqlite_master WHERE name = 'mentat_planning_deletion_receipts'").fetchone())
            finally:
                check.close()

    def test_private_receipt_validator_rejects_content_or_invalid_counts(self):
        with TemporaryDirectory() as temporary:
            connection = connect(Path(temporary))
            try:
                connection.execute(
                    "INSERT INTO mentat_planning_deletion_receipts (confirmation_digest, target_kind, target_digest, closure_digest, project_count, task_count, conversation_count, run_count, artifact_count, state, created_at) VALUES (?, 'task', ?, ?, 0, 1, 0, 0, 0, 'deleted', ?)",
                    ("a" * 64, "b" * 64, "c" * 64, "2026-09-02T12:00:00Z"),
                )
                connection.commit()
                connection.execute("PRAGMA ignore_check_constraints = ON")
                connection.execute("UPDATE mentat_planning_deletion_receipts SET task_count = 2049")
                connection.execute("PRAGMA ignore_check_constraints = OFF")
                connection.commit()
                with self.assertRaisesRegex(PrivateConsoleUnitError, "planning_deletion_receipt"):
                    _validate_planning_deletion_receipts(connection)
            finally:
                connection.close()

    def test_private_receipt_validator_enforces_the_bounded_retention_cap(self):
        with TemporaryDirectory() as temporary:
            connection = connect(Path(temporary))
            try:
                rows = [
                    (
                        f"{index:064x}", "a" * 64, "b" * 64,
                        "2026-09-02T12:00:00Z",
                    )
                    for index in range(257)
                ]
                connection.executemany(
                    "INSERT INTO mentat_planning_deletion_receipts (confirmation_digest, target_kind, target_digest, closure_digest, project_count, task_count, conversation_count, run_count, artifact_count, state, created_at) VALUES (?, 'task', ?, ?, 0, 1, 0, 0, 0, 'deleted', ?)",
                    rows,
                )
                connection.commit()
                with self.assertRaisesRegex(PrivateConsoleUnitError, "planning_deletion_receipt"):
                    _validate_planning_deletion_receipts(connection)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
