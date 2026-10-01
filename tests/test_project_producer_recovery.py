"""Private producer recovery boundaries; no live provider or owner service."""

from contextlib import closing
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import mentat_db
import private_console_unit as backups
import project_output_reservations as holds
import project_producers as producers
from mentat.project_worker_scope import LinuxWorkerScope, WorkerScopeLimits
from private_state import private_state_lock
from run_repository import RunRepositoryError
from tests import test_project_producers as producer_fixtures
from tests.test_project_worker_journal import GENERATION


@unittest.skipUnless(sys.platform == "linux", "Actual scoped Linux fixture required")
class ProducerRecoveryTests(unittest.TestCase):
    def setUp(self):
        # Reuse the reviewed disposable stock-Hermes fixture without inheriting
        # its test methods or touching an operator data root.
        self.source = producer_fixtures.ProducerIntegrationTests(
            "test_natural_completion_registers_blob_parser_run_and_capacity_atomically"
        )
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.root = self.source.root
        self.run = self.source.run
        self.holder = self.source.holder

    def _complete(self):
        return self.source.execute(json.dumps(producer_fixtures.PROPOSAL, separators=(",", ":")))

    def test_stop_lost_response_replays_exact_intent_without_new_event(self):
        with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            first = producers.request_stop(
                connection, run_id=self.run, generation=GENERATION,
                holder_token=self.holder, expected_revision=1,
            )
            connection.commit()
            before = tuple(connection.execute(
                "SELECT status,state_revision,last_event_sequence FROM mentat_runs WHERE id=?",
                (self.run,),
            ).fetchone())
            connection.execute("BEGIN IMMEDIATE")
            repeated = producers.request_stop(
                connection, run_id=self.run, generation=GENERATION,
                holder_token=self.holder, expected_revision=1,
            )
            connection.commit()
            self.assertEqual(repeated, first)
            self.assertEqual(tuple(connection.execute(
                "SELECT status,state_revision,last_event_sequence FROM mentat_runs WHERE id=?",
                (self.run,),
            ).fetchone()), before)
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM mentat_project_producer_stops WHERE run_id=?",
                (self.run,),
            ).fetchone()[0], 1)
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaises(producers.ProducerError):
                producers.request_stop(
                    connection, run_id=self.run, generation=GENERATION,
                    holder_token=self.holder, expected_revision=2,
                )
            connection.rollback()

    def test_unknown_owned_scope_can_record_stop_and_close_without_provider_replay(self):
        scope = LinuxWorkerScope(WorkerScopeLimits(wall_seconds=20))
        try:
            with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                scope_token, starting_revision = producers.record_start_intent(
                    connection, run_id=self.run, generation=GENERATION,
                    holder_token=self.holder, expected_revision=1,
                    plan_witness=scope.journal_plan(),
                )
                connection.commit()
            scope.start_inert()
            with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                owned_revision = producers.record_owned_scope(
                    connection, run_id=self.run, generation=GENERATION,
                    holder_token=self.holder, scope_token=scope_token,
                    scope_revision=starting_revision,
                    witness=scope.journal_owned_identity(), expected_revision=2,
                )
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                producers.mark_uncertain(
                    connection, run_id=self.run, generation=GENERATION,
                    holder_token=self.holder, expected_revision=3,
                )
                connection.commit()
                # Revocation and restore epoch cannot create new work, but the
                # original holder must retain the ability to fence local work.
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "UPDATE mentat_project_context_grants SET state='revoked',"
                    "reason='owner',revision=revision+1,updated_at=updated_at+1"
                )
                connection.execute(
                    "UPDATE mentat_project_context_access_state SET approval_epoch=? WHERE singleton=1",
                    (b"z" * 32,),
                )
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                producers.request_stop(
                    connection, run_id=self.run, generation=GENERATION,
                    holder_token=self.holder, expected_revision=4,
                )
                connection.commit()
                self.assertEqual(
                    tuple(connection.execute(
                        "SELECT status,state_revision FROM mentat_runs WHERE id=?", (self.run,)
                    ).fetchone()), ("unknown", 5),
                )
                self.assertEqual(holds.pending_capacity(connection), (1, 32768))
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_project_worker_calls").fetchone()[0], 0
                )
            scope.close_verified()
            with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                producers.settle_without_output(
                    connection, run_id=self.run, generation=GENERATION,
                    holder_token=self.holder, expected_revision=5,
                    disposition="stopped", scope_token=scope_token,
                    scope_revision=owned_revision,
                    closure_witness=scope.journal_closed_identity(),
                )
                connection.commit()
                self.assertEqual(
                    tuple(connection.execute(
                        "SELECT status,terminal_finalized FROM mentat_runs WHERE id=?", (self.run,)
                    ).fetchone()), ("stopped", 1),
                )
                self.assertEqual(holds.pending_capacity(connection), (0, 0))
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_project_worker_calls").fetchone()[0], 0
                )
        finally:
            if not scope._closed:
                scope.close_verified()

    def test_missing_canonical_run_authority_refuses_registered_readback(self):
        self._complete()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("DELETE FROM mentat_run_store_state")
            connection.commit()
        with self.assertRaises(RunRepositoryError):
            producers.read_registered_output(self.root, run_id=self.run, generation=GENERATION)

    def test_changed_event_refuses_registered_readback(self):
        self._complete()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute(
                "UPDATE mentat_agent_events SET summary='tampered' WHERE run_id=? AND sequence=1",
                (self.run,),
            )
            connection.commit()
        with self.assertRaises(RunRepositoryError):
            producers.read_registered_output(self.root, run_id=self.run, generation=GENERATION)

    def test_missing_attention_refuses_registered_readback(self):
        self._complete()
        with closing(mentat_db.connect(self.root)) as connection:
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='mentat_run_attention_protect'"
            ).fetchone()[0]
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TRIGGER mentat_run_attention_protect")
            connection.execute("DELETE FROM mentat_run_attention WHERE run_id=?", (self.run,))
            connection.execute(trigger)
            connection.commit()
        with self.assertRaises(RunRepositoryError):
            producers.read_registered_output(self.root, run_id=self.run, generation=GENERATION)

    def test_committed_readback_survives_deadline_and_restore_without_witness(self):
        digest, witness, _scope_receipt = self._complete()
        with patch("mentat.project_namespace_evidence.time.monotonic", return_value=witness._deadline):
            readback = producers.read_registered_output(
                self.root, run_id=self.run, generation=GENERATION
            )
        self.assertEqual(readback["receipt_digest"], digest)
        self.assertEqual(readback["snapshot"], producer_fixtures.PROPOSAL)
        unit = backups.capture_private_console_unit(self.root)
        restored = backups.sanitize_owner_auth_restore_unit(unit)
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target / "private").mkdir(mode=0o700)
            backups.materialize_private_console_unit(
                target, restored, target / "private" / "console"
            )
            self.assertEqual(
                producers.read_registered_output(
                    target, run_id=self.run, generation=GENERATION,
                    request_digest=readback["request_digest"],
                )["receipt_digest"], digest,
            )
            with self.assertRaises(producers.ProducerError):
                producers.read_registered_output(
                    target, run_id=self.run, generation=GENERATION,
                    request_digest="f" * 64,
                )


if __name__ == "__main__":
    unittest.main()
