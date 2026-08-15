from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from hermes_webhook_store import WebhookDeliveryStore
from hermes_webhooks import VerifiedHermesEvent
from mentat_db import connect, database_path, schema_version


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
        completed=True,
        interrupted=False,
        platform="cli",
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
        self.assertEqual(schema_version(self.data_dir), 3)
        self.assertEqual(len(self.rows()), 1)

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
