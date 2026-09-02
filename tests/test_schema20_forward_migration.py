from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from mentat_db import (
    MIGRATIONS,
    MentatDatabaseError,
    SCHEMA_VERSION,
    connect,
    database_path,
    ensure_private_console_dir,
    schema_signature_state,
)
from private_console_unit import (
    PrivateConsoleUnitError,
    _validate_task_delegation_action_receipts,
)


def _digest(character: str) -> str:
    return character * 64


class Schema20ForwardMigrationTests(unittest.TestCase):
    def _schema19(self, root: Path) -> Path:
        ensure_private_console_dir(root)
        path = database_path(root)
        connection = sqlite3.connect(path)
        try:
            for version, script in MIGRATIONS:
                if version > 19:
                    break
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                    (version,),
                )
            connection.commit()
        finally:
            connection.close()
        path.chmod(0o600)
        return path

    @staticmethod
    def _insert_receipt(
        connection: sqlite3.Connection,
        *,
        key: str,
        task_id: str = "task_without_a_foreign_key",
        state: str = "accepted",
        expires_at: float | None = 30 * 24 * 60 * 60,
    ) -> None:
        connection.execute(
            "INSERT INTO mentat_task_delegation_action_receipts ("
            "key_digest, request_digest, task_id, task_revision, action, "
            "confirmation_digest, delegation_binding_digest, remote_revision_digest, "
            "state, result_task_revision, result_proof_digest, created_at, updated_at, expires_at"
            ") VALUES (?, ?, ?, 1, 'delegate', ?, ?, ?, ?, 2, ?, ?, ?, ?)",
            (
                _digest(key),
                _digest("b"),
                task_id,
                _digest("c"),
                _digest("d"),
                _digest("e"),
                state,
                _digest("f"),
                "2026-09-02T12:00:00Z",
                "2026-09-02T12:00:00Z",
                expires_at,
            ),
        )

    def test_exact_schema19_upgrades_to_no_foreign_key_receipt_ledger(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._schema19(root)
            connection = connect(root)
            try:
                self.assertEqual(SCHEMA_VERSION, 23)
                self.assertEqual(schema_signature_state(connection, 23), "expected")
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_list(mentat_task_delegation_action_receipts)").fetchall(),
                    [],
                )
                index_names = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA index_list(mentat_task_delegation_action_receipts)"
                    )
                }
                self.assertTrue(
                    {
                        "idx_mentat_task_delegation_action_receipts_active_task",
                        "idx_mentat_task_delegation_action_receipts_expires",
                        "idx_mentat_task_delegation_action_receipts_task",
                    }.issubset(index_names)
                )
                self._insert_receipt(connection, key="a")
                connection.commit()
            finally:
                connection.close()

    def test_receipt_constraints_keep_only_terminal_receipts_expirable(self):
        with TemporaryDirectory() as temporary:
            connection = connect(Path(temporary))
            try:
                self._insert_receipt(
                    connection,
                    key="a",
                    task_id="task_active",
                    state="unknown",
                    expires_at=None,
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_receipt(
                        connection,
                        key="f",
                        task_id="task_active",
                        state="partial",
                        expires_at=None,
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_receipt(
                        connection,
                        key="g",
                        task_id="task_invalid_expiry",
                        state="accepted",
                        expires_at=None,
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    self._insert_receipt(
                        connection,
                        key="h",
                        task_id="task_invalid_uncertain_expiry",
                        state="unknown",
                        expires_at=1,
                    )
                self._insert_receipt(
                    connection,
                    key="i",
                    task_id="task_active",
                    state="rejected",
                )
                connection.commit()
            finally:
                connection.close()

    def test_schema19_drift_fails_before_receipt_table_creation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._schema19(root)
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                connection.execute("DROP INDEX idx_mentat_task_execution_reviews_task")
            finally:
                connection.close()
            with self.assertRaisesRegex(MentatDatabaseError, "schema 19 cannot be safely upgraded"):
                connect(root)
            check = sqlite3.connect(path)
            try:
                self.assertEqual(
                    check.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                    19,
                )
                self.assertIsNone(
                    check.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE name = 'mentat_task_delegation_action_receipts'"
                    ).fetchone()
                )
            finally:
                check.close()

    def test_private_backup_validation_rejects_a_corrupt_receipt_row(self):
        with TemporaryDirectory() as temporary:
            connection = connect(Path(temporary))
            try:
                self._insert_receipt(connection, key="Z")
                connection.commit()
                with self.assertRaisesRegex(
                    PrivateConsoleUnitError, "delegation_receipt_invalid"
                ):
                    _validate_task_delegation_action_receipts(connection)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
