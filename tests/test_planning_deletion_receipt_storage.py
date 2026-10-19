"""Current planning deletion receipts remain content-free and bounded."""
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from mentat_db import SCHEMA_VERSION, connect, schema_signature_state
from private_console_unit import PrivateConsoleUnitError, _validate_planning_deletion_receipts


class PlanningDeletionReceiptStorageTests(unittest.TestCase):
    def test_current_content_free_deletion_receipt_validates(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = connect(root)
            try:
                self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(schema_signature_state(connection, SCHEMA_VERSION), "expected")
                connection.execute(
                    "INSERT INTO mentat_planning_deletion_receipts (confirmation_digest, target_kind, target_digest, closure_digest, project_count, task_count, conversation_count, run_count, artifact_count, state, created_at) VALUES (?, 'task', ?, ?, 0, 1, 0, 0, 0, 'deleted', ?)",
                    ("a" * 64, "b" * 64, "c" * 64, "2026-09-02T12:00:00Z"),
                )
                connection.commit()
                _validate_planning_deletion_receipts(connection)
            finally:
                connection.close()

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


if __name__ == '__main__':
    unittest.main()
