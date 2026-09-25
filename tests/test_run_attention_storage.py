"""Canonical Run transitions reserve and retain owner attention atomically."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mentat_db
import private_console_unit
from private_state import history_path
from run_attention import validate_run_attention_connection
from run_repository import save_authoritative_run_summaries
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from tests.test_run_repository import run_fixture


_CREATED = "2026-09-24T12:00:00+00:00"
_UPDATED = "2026-09-24T12:00:01+00:00"


def _insert(connection: sqlite3.Connection, run_id: str, status: str,
            *, dispatch: str = "legacy", partial: int = 0, finalized: int = 0) -> None:
    connection.execute(
        "INSERT INTO mentat_runs "
        "(id,source,runtime_type,capabilities_json,status,dispatch_state,partial,"
        "terminal_finalized,created_at,updated_at,completed_at) "
        "VALUES(?,'console','hermes','[]',?,?,?,?,?,?,?)",
        (run_id, status, dispatch, partial, finalized, _CREATED, _UPDATED,
         _UPDATED if status in ("completed", "failed", "cancelled", "stopped", "interrupted") else None),
    )


class RunAttentionStorageTests(unittest.TestCase):
    def test_hidden_admission_then_unknown_then_verified_completion_reopens_one_item(self):
        connection = sqlite3.connect(":memory:")
        try:
            mentat_db.migrate(connection)
            _insert(connection, "run_outcome", "running", dispatch="accepted")
            hidden = connection.execute(
                "SELECT item_id,revision FROM mentat_run_attention WHERE run_id='run_outcome'"
            ).fetchone()
            self.assertEqual(hidden, (None, 0))
            connection.execute(
                "UPDATE mentat_runs SET status='unknown',dispatch_state='unknown',"
                "state_revision=state_revision+1 WHERE id='run_outcome'"
            )
            visible = connection.execute(
                "SELECT item_id,revision FROM mentat_run_attention WHERE run_id='run_outcome'"
            ).fetchone()
            self.assertRegex(visible[0], r"^inbox_item_[0-9a-f]{32}$")
            self.assertEqual(visible[1], 1)
            connection.execute(
                "UPDATE mentat_run_attention SET read_at=created_at,acknowledged_at=created_at "
                "WHERE run_id='run_outcome'"
            )
            connection.execute(
                "UPDATE mentat_runs SET status='completed',dispatch_state='accepted',"
                "terminal_finalized=1,state_revision=state_revision+1,completed_at=?,updated_at=? "
                "WHERE id='run_outcome'", (_UPDATED, _UPDATED),
            )
            reopened = connection.execute(
                "SELECT item_id,revision,read_at,acknowledged_at FROM mentat_run_attention "
                "WHERE run_id='run_outcome'"
            ).fetchone()
            self.assertEqual(reopened, (visible[0], 2, None, None))
            validate_run_attention_connection(connection)
        finally:
            connection.close()

    def test_delete_freezes_exact_receipt_and_reused_run_id_gets_new_identity(self):
        connection = sqlite3.connect(":memory:")
        try:
            mentat_db.migrate(connection)
            connection.execute("PRAGMA foreign_keys=ON")
            _insert(connection, "run_reused", "failed", dispatch="rejected", finalized=1)
            old = connection.execute(
                "SELECT incarnation,item_id FROM mentat_run_attention WHERE run_id='run_reused'"
            ).fetchone()
            self.assertIsNotNone(old[1])
            connection.execute("DELETE FROM mentat_runs WHERE id='run_reused'")
            receipt = connection.execute(
                "SELECT retired_status,retired_dispatch_state,retired_terminal_finalized,"
                "retired_at FROM mentat_run_attention WHERE run_id='run_reused' AND incarnation=?",
                (old[0],),
            ).fetchone()
            self.assertEqual(receipt[:3], ("failed", "rejected", 1))
            self.assertGreater(receipt[3], 0)
            _insert(connection, "run_reused", "running", dispatch="accepted")
            current = connection.execute(
                "SELECT incarnation,item_id FROM mentat_run_attention WHERE run_id='run_reused' "
                "AND retired_at IS NULL"
            ).fetchone()
            self.assertNotEqual(current[0], old[0])
            self.assertIsNone(current[1])
            validate_run_attention_connection(connection)
        finally:
            connection.close()

    def test_same_status_result_change_reopens_but_timestamp_only_event_does_not(self):
        connection = sqlite3.connect(":memory:")
        try:
            mentat_db.migrate(connection)
            _insert(connection, "run_result_change", "completed", finalized=1)
            # A direct historical terminal insert is quiet. A timestamp-only
            # event stays quiet, while a canonical result change creates notice.
            self.assertIsNone(connection.execute(
                "SELECT item_id FROM mentat_run_attention WHERE run_id='run_result_change'"
            ).fetchone()[0])
            connection.execute(
                "UPDATE mentat_runs SET updated_at='2026-09-24T12:00:02+00:00' "
                "WHERE id='run_result_change'"
            )
            self.assertIsNone(connection.execute(
                "SELECT item_id FROM mentat_run_attention WHERE run_id='run_result_change'"
            ).fetchone()[0])
            connection.execute(
                "UPDATE mentat_runs SET details_json=? WHERE id='run_result_change'",
                ('{"result":"first"}',),
            )
            first = connection.execute(
                "SELECT item_id,revision FROM mentat_run_attention WHERE run_id='run_result_change'"
            ).fetchone()
            connection.execute(
                "UPDATE mentat_run_attention SET read_at=created_at,acknowledged_at=created_at "
                "WHERE run_id='run_result_change'"
            )
            connection.execute(
                "UPDATE mentat_runs SET updated_at='2026-09-24T12:00:02+00:00' "
                "WHERE id='run_result_change'"
            )
            self.assertEqual(connection.execute(
                "SELECT revision FROM mentat_run_attention WHERE run_id='run_result_change'"
            ).fetchone()[0], first[1])
            connection.execute(
                "UPDATE mentat_runs SET details_json=?,state_revision=state_revision+1 "
                "WHERE id='run_result_change'", ('{"result":"revised"}',),
            )
            revised = connection.execute(
                "SELECT item_id,revision,read_at,acknowledged_at FROM mentat_run_attention "
                "WHERE run_id='run_result_change'"
            ).fetchone()
            self.assertEqual(revised, (first[0], first[1] + 1, None, None))
            validate_run_attention_connection(connection)
        finally:
            connection.close()

    def test_active_run_cannot_be_deleted_through_sql(self):
        connection = sqlite3.connect(":memory:")
        try:
            mentat_db.migrate(connection)
            _insert(connection, "run_active", "running", dispatch="accepted")
            with self.assertRaisesRegex(sqlite3.IntegrityError, "active_retirement"):
                connection.execute("DELETE FROM mentat_runs WHERE id='run_active'")
            validate_run_attention_connection(connection)
        finally:
            connection.close()

    def test_schema_35_upgrade_surfaces_uncertain_and_failed_but_quiets_verified_history(self):
        connection = sqlite3.connect(":memory:")
        try:
            for version, script in mentat_db.MIGRATIONS:
                if version > 35:
                    break
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version,applied_at) VALUES(?,1)", (version,),
                )
            _insert(connection, "run_unknown", "unknown", dispatch="accepted")
            _insert(connection, "run_failed", "failed", dispatch="rejected", finalized=1)
            _insert(connection, "run_incomplete", "completed", dispatch="accepted", finalized=0)
            _insert(connection, "run_quiet", "completed", dispatch="accepted", finalized=1)
            connection.commit()
            mentat_db.migrate(connection)
            notices = dict(connection.execute(
                "SELECT run_id,item_id FROM mentat_run_attention ORDER BY run_id"
            ).fetchall())
            self.assertEqual(set(notices), {"run_unknown", "run_failed", "run_incomplete", "run_quiet"})
            self.assertIsNone(notices["run_quiet"])
            for identifier in ("run_unknown", "run_failed", "run_incomplete"):
                self.assertIsNotNone(notices[identifier])
            validate_run_attention_connection(connection)
        finally:
            connection.close()

    def test_repository_retention_keeps_retired_failure_notice(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            ensure_run_sqlite_authority(root, history_path(root))
            runs = [run_fixture(f"run_retention_{index}", status="failed", offset=index,
                                bound=False) for index in range(251)]
            save_authoritative_run_summaries(root, runs)
            with closing(mentat_db.connect(root)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0], 250)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM mentat_run_attention WHERE item_id IS NOT NULL"
                ).fetchone()[0], 251)
                self.assertEqual(connection.execute(
                    "SELECT COUNT(*) FROM mentat_run_attention WHERE retired_at IS NOT NULL"
                ).fetchone()[0], 1)
                validate_run_attention_connection(connection)

    def test_full_attention_capacity_blocks_admission_until_retired_notice_is_resolved(self):
        connection = sqlite3.connect(":memory:")
        try:
            mentat_db.migrate(connection)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executemany(
                "INSERT INTO mentat_runs "
                "(id,source,runtime_type,capabilities_json,status,dispatch_state,"
                "terminal_finalized,created_at,updated_at,completed_at) "
                "VALUES(?,'console','hermes','[]','failed','legacy',1,?,?,?)",
                ((f"run_full_{index:05d}", _CREATED, _UPDATED, _UPDATED)
                 for index in range(10_000)),
            )
            connection.execute("DELETE FROM mentat_runs")
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_run_attention"
            ).fetchone()[0], 10_000)
            with self.assertRaisesRegex(sqlite3.IntegrityError, "run_attention.capacity"):
                _insert(connection, "run_one_more", "running")
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM mentat_runs WHERE id='run_one_more'"
            ).fetchone())
            connection.execute(
                "UPDATE mentat_run_attention SET read_at=created_at,"
                "acknowledged_at=created_at,resolved_at=created_at "
                "WHERE run_id='run_full_00000'"
            )
            _insert(connection, "run_one_more", "running")
            self.assertIsNone(connection.execute(
                "SELECT 1 FROM mentat_run_attention WHERE run_id='run_full_00000'"
            ).fetchone())
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_run_attention"
            ).fetchone()[0], 10_000)
            validate_run_attention_connection(connection)
        finally:
            connection.close()

    def test_maximum_schema_35_upgrade_fits_database_and_private_unit_headroom(self):
        connection = sqlite3.connect(":memory:")
        try:
            for version, script in mentat_db.MIGRATIONS:
                if version > 35:
                    break
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version,applied_at) VALUES(?,1)", (version,),
                )
            connection.executemany(
                "INSERT INTO mentat_runs "
                "(id,source,runtime_type,capabilities_json,status,dispatch_state,created_at,updated_at) "
                "VALUES(?,'console','hermes','[]','completed','legacy',?,?)",
                (("run_" + f"{index:05d}" + "x" * 119, _CREATED, _UPDATED)
                 for index in range(10_000)),
            )
            connection.commit()
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            before = page_size * connection.execute("PRAGMA page_count").fetchone()[0]
            mentat_db.migrate(connection)
            after = page_size * connection.execute("PRAGMA page_count").fetchone()[0]
            added = after - before
            self.assertLess(added, 7 * 1024 * 1024)
            self.assertLess(56 * 1024 * 1024 + added, 63 * 1024 * 1024)
            self.assertLess(63 * 1024 * 1024 + 24 * 1024 * 1024
                            + 4 * 1024 * 1024 + 4 * 1024 * 1024,
                            96 * 1024 * 1024)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_run_attention WHERE item_id IS NOT NULL"
            ).fetchone()[0], 10_000)
        finally:
            connection.close()

    def test_private_backup_retains_exact_run_notice_and_receipt(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            ensure_run_sqlite_authority(root, history_path(root))
            save_authoritative_run_summaries(root, [
                run_fixture("run_backup_notice", status="failed", bound=False)
            ])
            with closing(mentat_db.connect(root)) as connection:
                before = connection.execute(
                    "SELECT incarnation,item_id FROM mentat_run_attention "
                    "WHERE run_id='run_backup_notice'"
                ).fetchone()
            self.assertIsNotNone(before[1])
            unit = private_console_unit.capture_private_console_unit(root)
            private_console_unit.validate_private_console_unit(unit)
            snapshot = Path(temporary) / "snapshot.sqlite3"
            snapshot.write_bytes(unit.database_raw)
            with closing(sqlite3.connect(snapshot)) as connection:
                after = connection.execute(
                    "SELECT incarnation,item_id FROM mentat_run_attention "
                    "WHERE run_id='run_backup_notice'"
                ).fetchone()
            self.assertEqual(after, tuple(before))
            target = Path(temporary) / "restored"
            (target / "private").mkdir(parents=True)
            private_console_unit.materialize_private_console_unit(
                target, unit, target / "private" / "console"
            )
            with closing(mentat_db.connect(target)) as connection:
                restored = connection.execute(
                    "SELECT incarnation,item_id FROM mentat_run_attention "
                    "WHERE run_id='run_backup_notice'"
                ).fetchone()
                self.assertEqual(tuple(restored), tuple(before))
                validate_run_attention_connection(connection)

    def test_schema_35_private_unit_restores_and_materializes_failure_once(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            old_migrations = tuple(item for item in mentat_db.MIGRATIONS if item[0] <= 35)
            with patch.object(mentat_db, "MIGRATIONS", old_migrations), patch.object(mentat_db, "SCHEMA_VERSION", 35):
                ensure_run_sqlite_authority(root, history_path(root))
                save_authoritative_run_summaries(root, [
                    run_fixture("run_schema35_failure", status="failed", bound=False)
                ])
                unit = private_console_unit.capture_private_console_unit(root)
            private_console_unit.validate_private_console_unit(unit)
            target = Path(temporary) / "target"
            (target / "private").mkdir(parents=True)
            private_console_unit.materialize_private_console_unit(
                target, unit, target / "private" / "console"
            )
            with closing(mentat_db.connect(target)) as connection:
                self.assertEqual(mentat_db.schema_signature_state(connection, 37), "expected")
                first = connection.execute(
                    "SELECT item_id,revision FROM mentat_run_attention "
                    "WHERE run_id='run_schema35_failure'"
                ).fetchone()
                self.assertIsNotNone(first[0])
                mentat_db.migrate(connection)
                second = connection.execute(
                    "SELECT item_id,revision FROM mentat_run_attention "
                    "WHERE run_id='run_schema35_failure'"
                ).fetchone()
                self.assertEqual(tuple(first), tuple(second))

    def test_unclaimed_backup_rejects_orphan_attention_reservation(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mentat.sqlite3"
            private_console_unit._initialize_database(path)
            with closing(sqlite3.connect(path)) as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO mentat_run_attention(run_id,incarnation) VALUES(?,?)",
                        ("run_orphan_attention", "a" * 32),
                    )
            with self.assertRaisesRegex(private_console_unit.PrivateConsoleUnitError,
                                        "private_run_repository_invalid"):
                private_console_unit._require_empty_unclaimed_run_store(path)


if __name__ == "__main__":
    unittest.main()
