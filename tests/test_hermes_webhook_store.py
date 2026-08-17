from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mentat_db
from hermes_webhook_store import WebhookDeliveryStore
from hermes_webhooks import ALLOWED_EVENTS, VerifiedHermesEvent
from mentat_db import (
    MIGRATIONS,
    SCHEMA_VERSION,
    connect,
    database_path,
    ensure_private_console_dir,
    schema_version,
)


NOW = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)


def event(
    digest: str,
    *,
    binding_id: str = "local-default",
    received_at: datetime = NOW,
) -> VerifiedHermesEvent:
    return VerifiedHermesEvent(
        binding_id=binding_id,
        event_name="on_session_end",
        delivery_digest=digest,
        occurred_at=received_at,
        received_at=received_at,
    )


class HermesWebhookStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.data_dir = Path(self.temporary.name) / "data"
        self.store = WebhookDeliveryStore(self.data_dir)

    def tearDown(self):
        self.temporary.cleanup()

    def rows(self):
        connection = sqlite3.connect(database_path(self.data_dir))
        try:
            return connection.execute(
                """
                SELECT binding_id, delivery_digest, event_name,
                       received_at, expires_at, outcome
                FROM hermes_webhook_deliveries
                ORDER BY delivery_digest
                """
            ).fetchall()
        finally:
            connection.close()

    def test_first_claim_wins_and_survives_store_restart(self):
        delivery = event("a" * 64)
        self.assertTrue(self.store.claim(delivery))
        self.assertFalse(self.store.claim(delivery))
        restarted = WebhookDeliveryStore(self.data_dir)
        self.assertFalse(restarted.claim(delivery))
        self.assertEqual(schema_version(self.data_dir), SCHEMA_VERSION)
        self.assertEqual(len(self.rows()), 1)

    def test_every_allowlisted_native_event_satisfies_database_constraint(self):
        for index, event_name in enumerate(sorted(ALLOWED_EVENTS), start=1):
            delivery = replace(
                event(f"{index:064x}"),
                event_name=event_name,
            )
            with self.subTest(event_name=event_name):
                self.assertTrue(self.store.claim(delivery))
        self.assertEqual(len(self.rows()), len(ALLOWED_EVENTS))

    def test_non_duplicate_constraint_failure_is_not_misreported_as_duplicate(self):
        unsupported = replace(event("f" * 64), event_name="future_private_event")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.claim_and_admit(unsupported, lambda: True)
        self.assertEqual(self.rows(), [])

    def test_v3_replay_rows_are_preserved_by_native_event_migration(self):
        legacy_root = Path(self.temporary.name) / "legacy-data"
        private = ensure_private_console_dir(legacy_root)
        path = database_path(legacy_root)
        connection = sqlite3.connect(path)
        try:
            for version, script in MIGRATIONS[:3]:
                connection.executescript(script)
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, float(version)),
                )
            connection.execute(
                """
                INSERT INTO hermes_webhook_deliveries (
                    binding_id, delivery_digest, event_name,
                    received_at, expires_at, outcome
                ) VALUES ('local-default', ?, 'on_session_end', 1, 9999999999, 'accepted')
                """,
                ("a" * 64,),
            )
            connection.commit()
        finally:
            connection.close()
        if os.name != "nt":
            path.chmod(0o600)

        migrated = connect(legacy_root)
        try:
            row = migrated.execute(
                "SELECT event_name FROM hermes_webhook_deliveries"
            ).fetchone()
        finally:
            migrated.close()
        self.assertEqual(schema_version(legacy_root), SCHEMA_VERSION)
        self.assertEqual(row[0], "on_session_end")

    def test_failed_v4_rebuild_rolls_back_and_reopens_cleanly(self):
        legacy_root = Path(self.temporary.name) / "interrupted-data"
        ensure_private_console_dir(legacy_root)
        path = database_path(legacy_root)
        connection = sqlite3.connect(path, isolation_level=None)
        try:
            for version, script in MIGRATIONS[:3]:
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, float(version)),
                )
            connection.execute(
                """
                INSERT INTO hermes_webhook_deliveries (
                    binding_id, delivery_digest, event_name,
                    received_at, expires_at, outcome
                ) VALUES ('local-default', ?, 'on_session_end', 1, 9999999999, 'accepted')
                """,
                ("b" * 64,),
            )
            failing_migrations = MIGRATIONS[:3] + (
                (4, MIGRATIONS[3][1] + "\nSELECT * FROM injected_missing_table;"),
            )
            with patch.object(mentat_db, "MIGRATIONS", failing_migrations):
                with self.assertRaises(sqlite3.OperationalError):
                    mentat_db.migrate(connection)
            self.assertEqual(
                connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT event_name FROM hermes_webhook_deliveries"
                ).fetchone()[0],
                "on_session_end",
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'hermes_webhook_deliveries_v3'"
                ).fetchone()
            )
        finally:
            connection.close()
        if os.name != "nt":
            path.chmod(0o600)

        reopened = connect(legacy_root)
        reopened.close()
        self.assertEqual(schema_version(legacy_root), SCHEMA_VERSION)

    def test_two_simultaneous_claims_accept_exactly_once(self):
        delivery = event("b" * 64)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.store.claim(delivery), range(2)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(len(self.rows()), 1)

    def test_digest_is_binding_scoped_and_raw_delivery_is_never_stored(self):
        raw_delivery = "private-delivery-id"
        first = event("c" * 64, binding_id="first")
        second = event("d" * 64, binding_id="second")
        self.assertTrue(self.store.claim(first))
        self.assertTrue(self.store.claim(second))
        raw_database = database_path(self.data_dir).read_bytes()
        self.assertNotIn(raw_delivery.encode(), raw_database)
        self.assertEqual({row[0] for row in self.rows()}, {"first", "second"})

    def test_rejected_admission_rolls_back_claim_for_retry(self):
        delivery = event("1" * 64)
        self.assertEqual(
            self.store.claim_and_admit(delivery, lambda: False),
            "rejected",
        )
        self.assertEqual(self.rows(), [])
        self.assertEqual(
            self.store.claim_and_admit(delivery, lambda: True),
            "accepted",
        )

    def test_admission_exception_rolls_back_claim_for_retry(self):
        delivery = event("2" * 64)

        def fail():
            raise RuntimeError("queue unavailable")

        with self.assertRaisesRegex(RuntimeError, "queue unavailable"):
            self.store.claim_and_admit(delivery, fail)
        self.assertEqual(self.rows(), [])
        self.assertTrue(self.store.claim(delivery))

    def test_commit_failure_after_admission_is_explicit_and_not_retried(self):
        delivery = event("3" * 64)
        admitted = []
        underlying = connect(self.data_dir)

        class CommitFailingConnection:
            def execute(self, *args, **kwargs):
                return underlying.execute(*args, **kwargs)

            def commit(self):
                raise sqlite3.OperationalError("commit failed")

            def rollback(self):
                return underlying.rollback()

            def close(self):
                return underlying.close()

        store = WebhookDeliveryStore(
            self.data_dir,
            connection_factory=lambda _path: CommitFailingConnection(),
        )
        self.assertEqual(
            store.claim_and_admit(delivery, lambda: admitted.append(True) or True),
            "admitted_unrecorded",
        )
        self.assertEqual(admitted, [True])
        self.assertEqual(self.rows(), [])
        self.assertTrue(WebhookDeliveryStore(self.data_dir).claim(delivery))

    def test_admitted_result_survives_rollback_and_close_failures(self):
        for index, failure in enumerate(("rollback", "close"), start=4):
            with self.subTest(failure=failure):
                delivery = event(f"{index:064x}")
                underlying = connect(self.data_dir)

                class CompoundFailingConnection:
                    def execute(self, *args, **kwargs):
                        return underlying.execute(*args, **kwargs)

                    def commit(self):
                        raise sqlite3.OperationalError("commit failed")

                    def rollback(self):
                        if failure == "rollback":
                            raise sqlite3.OperationalError("rollback failed")
                        return underlying.rollback()

                    def close(self):
                        underlying.close()
                        if failure == "close":
                            raise sqlite3.OperationalError("close failed")

                store = WebhookDeliveryStore(
                    self.data_dir,
                    connection_factory=lambda _path: CompoundFailingConnection(),
                )
                admitted = []
                self.assertEqual(
                    store.claim_and_admit(
                        delivery,
                        lambda: admitted.append(True) or True,
                    ),
                    "admitted_unrecorded",
                )
                self.assertEqual(admitted, [True])
                self.assertTrue(WebhookDeliveryStore(self.data_dir).claim(delivery))

    def test_expired_claim_can_be_reused_and_cleanup_is_bounded(self):
        store = WebhookDeliveryStore(
            self.data_dir,
            retention_seconds=10,
            cleanup_batch=2,
        )
        for index in range(4):
            self.assertTrue(store.claim(event(f"{index:064x}")))
        later = NOW + timedelta(seconds=11)
        cleaned = store.cleanup(now=later)
        self.assertEqual(cleaned, 2)
        self.assertEqual(len(self.rows()), 2)
        reused = event("0" * 64, received_at=later)
        self.assertTrue(store.claim(reused))

    @unittest.skipIf(os.name != "posix", "POSIX mode contract")
    def test_database_and_private_directory_are_owner_only(self):
        self.assertTrue(self.store.claim(event("f" * 64)))
        path = database_path(self.data_dir)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
