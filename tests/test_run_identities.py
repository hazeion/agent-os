"""Current private identities for exact Run-bound owner attention."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import mentat_db
import private_console_unit
import run_repository
from private_state import history_path
from run_repository import RunRepository, RunRepositoryValidationError, save_authoritative_run_summaries
from tests.sqlite_authority_support import ensure_run_sqlite_authority


_CREATED = "2026-09-24T12:00:00+00:00"


def _insert_run(connection: sqlite3.Connection, identifier: str) -> None:
    connection.execute(
        "INSERT INTO mentat_runs "
        "(id,source,runtime_type,capabilities_json,status,dispatch_state,created_at,updated_at) "
        "VALUES(?,'console','hermes','[]','completed','legacy',?,?)",
        (identifier, _CREATED, _CREATED),
    )


class RunIdentityTests(unittest.TestCase):
    def test_current_insert_reserves_identity_and_preserves_existing_identity(self):
        connection = sqlite3.connect(":memory:")
        try:
            mentat_db.migrate(connection)
            _insert_run(connection, "run_existing")
            self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), "expected")
            connection.commit()
            mentat_db.migrate(connection)
            self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), "expected")
            original = connection.execute(
                "SELECT incarnation,created_at FROM mentat_run_identities WHERE run_id='run_existing'"
            ).fetchone()
            self.assertIsNotNone(original)
            self.assertRegex(original[0], r"^[0-9a-f]{32}$")
            self.assertEqual(original[1], _CREATED)
            _insert_run(connection, "run_new")
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM mentat_run_identities").fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT incarnation FROM mentat_run_identities WHERE run_id='run_existing'"
                ).fetchone()[0],
                original[0],
            )
        finally:
            connection.close()

    def test_deleted_and_reused_run_id_gets_a_new_identity(self):
        connection = sqlite3.connect(":memory:")
        try:
            mentat_db.migrate(connection)
            connection.execute("PRAGMA foreign_keys=ON")
            _insert_run(connection, "run_reused")
            first = connection.execute(
                "SELECT incarnation FROM mentat_run_identities WHERE run_id='run_reused'"
            ).fetchone()[0]
            connection.execute("DELETE FROM mentat_runs WHERE id='run_reused'")
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM mentat_run_identities WHERE run_id='run_reused'"
            ).fetchone())
            _insert_run(connection, "run_reused")
            second = connection.execute(
                "SELECT incarnation FROM mentat_run_identities WHERE run_id='run_reused'"
            ).fetchone()[0]
            self.assertNotEqual(first, second)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE mentat_run_identities SET incarnation=? WHERE run_id='run_reused'",
                    (first,),
                )
        finally:
            connection.close()

    def test_missing_slot_fails_repository_validation(self):
        connection = sqlite3.connect(":memory:")
        try:
            mentat_db.migrate(connection)
            _insert_run(connection, "run_missing")
            repository = RunRepository(connection)
            repository._validate_run_identities()
            connection.execute("DELETE FROM mentat_run_identities WHERE run_id='run_missing'")
            with self.assertRaisesRegex(RunRepositoryValidationError, "run.identity_invalid"):
                repository._validate_run_identities()
        finally:
            connection.close()


    def test_current_near_limit_store_keeps_budget_headroom(self):
        self.assertLessEqual(
            run_repository.RUN_STORE_DATABASE_BUDGET
            + private_console_unit.MAX_HISTORY_BYTES
            + private_console_unit.MAX_RETAINED_BLOB_BYTES,
            private_console_unit.MAX_PRIVATE_UNIT_BYTES,
        )
        with TemporaryDirectory() as temporary:
            connection = sqlite3.connect(Path(temporary) / "near-limit.sqlite3")
            try:
                mentat_db.migrate(connection)
                _insert_run(connection, "run_current_near_limit")
                connection.execute("CREATE TABLE padding(data BLOB)")
                connection.execute("INSERT INTO padding(data) VALUES(zeroblob(?))", (46 * 1024 * 1024,))
                connection.execute("DROP TABLE padding")
                connection.commit()
                page_bytes = lambda: connection.execute("PRAGMA page_size").fetchone()[0] * connection.execute("PRAGMA page_count").fetchone()[0]
                self.assertLessEqual(page_bytes(), 48 * 1024 * 1024)
                self.assertGreater(page_bytes(), 46 * 1024 * 1024)
                self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), "expected")
                mentat_db.migrate(connection)
                repository = RunRepository(connection)
                repository._validate_run_identities()
                repository._enforce_store_budget()
                self.assertLessEqual(page_bytes(), run_repository.RUN_STORE_DATABASE_BUDGET)
            finally:
                connection.close()

    def test_maximum_long_run_ids_keep_current_identity_capacity_and_store_budget(self):
        connection = sqlite3.connect(":memory:")
        try:
            mentat_db.migrate(connection)
            identifiers = (
                ("run_" + f"{index:05d}" + "x" * 119, _CREATED, _CREATED)
                for index in range(run_repository.MAX_SOURCE_RUNS)
            )
            connection.executemany(
                "INSERT INTO mentat_runs "
                "(id,source,runtime_type,capabilities_json,status,dispatch_state,created_at,updated_at) "
                "VALUES(?,'console','hermes','[]','completed','legacy',?,?)",
                identifiers,
            )
            connection.commit()
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            new_size = page_size * connection.execute("PRAGMA page_count").fetchone()[0]
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_run_identities"
            ).fetchone()[0], run_repository.MAX_SOURCE_RUNS)
            self.assertLessEqual(new_size, run_repository.RUN_STORE_DATABASE_BUDGET)
            RunRepository(connection)._validate_run_identities()
        finally:
            connection.close()

    def test_unclaimed_store_rejects_an_orphan_identity(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mentat.sqlite3"
            private_console_unit._initialize_database(path)
            with closing(sqlite3.connect(path)) as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO mentat_run_identities(run_id,incarnation,created_at) VALUES(?,?,?)",
                        ("run_orphan", "a" * 32, _CREATED),
                    )
            with self.assertRaisesRegex(private_console_unit.PrivateConsoleUnitError, "private_run_repository_invalid"):
                private_console_unit._require_empty_unclaimed_run_store(path)

    def test_private_backup_preserves_exact_run_identity(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(root, [{
                "id": "run_backup_identity",
                "runtime_type": "hermes",
                "status": "completed",
                "created_at": _CREATED,
                "updated_at": "2026-09-24T12:00:01+00:00",
                "completed_at": "2026-09-24T12:00:01+00:00",
            }])
            with closing(mentat_db.connect(root)) as connection:
                expected = connection.execute(
                    "SELECT incarnation FROM mentat_run_identities WHERE run_id='run_backup_identity'"
                ).fetchone()[0]
            unit = private_console_unit.capture_private_console_unit(root)
            private_console_unit.validate_private_console_unit(unit)
            snapshot = Path(temporary) / "snapshot.sqlite3"
            snapshot.write_bytes(unit.database_raw)
            with closing(sqlite3.connect(snapshot)) as connection:
                retained = connection.execute(
                    "SELECT incarnation FROM mentat_run_identities WHERE run_id='run_backup_identity'"
                ).fetchone()[0]
            self.assertEqual(retained, expected)



if __name__ == "__main__":
    unittest.main()
