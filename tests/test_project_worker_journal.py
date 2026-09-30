from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch

import mentat_db
import private_console_unit
import project_context
import project_context_access
import project_worker_journal as journal
from private_state import private_state_lock, history_path
from task_repository import _schema5_private_unit
from run_repository import RunRepository, RunRepositoryError, ensure_run_sqlite_authority
import run_attention
from tests import test_project_proposal_input_receipts as receipts


POLICY = {"format": 1, "inference_calls": 1, "max_output_tokens": 8192,
          "max_response_bytes": 32768, "max_request_bytes": 16 * 1024 * 1024,
          "wall_seconds": 20, "memory_bytes": 512 * 1024 * 1024,
          "processes": 32, "cpu_percent": 100}
SNAPSHOT = {"provider": "custom", "model": "mentat-probe", "supports_vision": False}
GENERATION = "a" * 32
REQUEST = "b" * 64


class ProjectWorkerJournalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = receipts.ProjectProposalInputReceiptTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def _prepare(self):
        # Temporary historical fixture only: source INSERT guard is restored by
        # the existing helper. No production Run/admission or model is invoked.
        ensure_run_sqlite_authority(self.root, history_path(self.root))
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            run_id = self.fixture._insert_consistent_receipt(connection)
            row = list(connection.execute("SELECT * FROM mentat_project_proposal_input_receipts WHERE run_id=?", (run_id,)).fetchone())
            row[20] = journal._digest(POLICY)
            context = connection.execute("SELECT brief FROM mentat_project_context_versions WHERE id=?", (row[13],)).fetchone()[0]
            instructions = connection.execute("SELECT instructions FROM mentat_project_planning_input_versions WHERE id=?", (row[1],)).fetchone()[0]
            files = connection.execute("SELECT attachment_id,blob_id,sha256,byte_size,kind,mime_type "
                                       "FROM mentat_project_proposal_input_files WHERE run_id=? ORDER BY ordinal", (run_id,)).fetchall()
            row[21] = receipts._digest([*row[:21], row[22], context, instructions, [list(item) for item in files]])
            sql = connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_project_proposal_input_receipt_immutable'").fetchone()[0]
            connection.execute("DROP TRIGGER mentat_project_proposal_input_receipt_immutable")
            connection.execute("UPDATE mentat_project_proposal_input_receipts SET limits_digest=?,manifest_digest=? WHERE run_id=?",
                               (row[20], row[21], run_id))
            connection.execute(sql)
            journal.create_generation(connection, run_id=run_id, generation=GENERATION, policy=POLICY, model_snapshot=SNAPSHOT)
            connection.commit()
        return run_id

    def test_integer_controller_timestamp_is_canonicalized_before_digest(self):
        captured = {}
        original = journal.create_generation
        def integer_creation(connection, **kwargs):
            kwargs["now"] = int(time.time()) + 10
            captured["now"] = kwargs["now"]
            return original(connection, **kwargs)
        with patch.object(journal, "create_generation", side_effect=integer_creation):
            self._prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            row = connection.execute("SELECT created_at FROM mentat_project_worker_generations").fetchone()
            self.assertEqual(row[0], float(captured["now"]))
            journal.validate_worker_journal_connection(connection)

    def _reserve(self, run_id, digest=REQUEST):
        with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            result = journal.reserve_call(connection, run_id=run_id, generation=GENERATION, request_digest=digest)
            if result.newly_reserved:
                self.assertTrue(journal.record_submission(connection, call_id=result.call_id, generation=GENERATION,
                    request_digest=digest, settlement_token=result.settlement_token))
            connection.commit()
        return result

    def _settle(self, connection, receipt, **kwargs):
        journal.settle_call(connection, call_id=receipt.call_id, generation=GENERATION,
                            request_digest=REQUEST, settlement_token=receipt.settlement_token, **kwargs)

    def test_crash_reopen_duplicate_keeps_one_unknown_debit(self):
        run_id = self._prepare()
        first = self._reserve(run_id)
        self.assertTrue(first.newly_reserved)
        self.assertEqual(first.state, "reserved")
        repeated = self._reserve(run_id)
        self.assertFalse(repeated.newly_reserved)
        self.assertEqual(repeated.call_id, first.call_id)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(tuple(connection.execute("SELECT SUM(work_debit),COUNT(*) FROM mentat_project_worker_calls").fetchone()), (1, 1))
            self.assertEqual(len(journal.validate_worker_journal_connection(connection)[1]), 1)
        with self.assertRaisesRegex(journal.WorkerJournalError, "conflict"):
            self._reserve(run_id, "c" * 64)

    def test_known_result_replays_exactly_and_cannot_be_replaced(self):
        run_id = self._prepare()
        first = self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._settle(connection, first, response_text='{"tasks":[]}')
            connection.commit()
        replay = self._reserve(run_id)
        self.assertFalse(replay.newly_reserved)
        self.assertEqual((replay.state, replay.response_text), ("succeeded", '{"tasks":[]}'))
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            with self.assertRaisesRegex(journal.WorkerJournalError, "conflict"):
                self._settle(connection, first, response_text="different")
            connection.rollback()

    def test_failures_and_oversize_are_fixed_replay_not_truncation_or_new_work(self):
        run_id = self._prepare()
        first = self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._settle(connection, first, response_text="x" * 32769)
            connection.commit()
        replay = self._reserve(run_id)
        self.assertEqual((replay.state, replay.disposition, replay.response_text, replay.newly_reserved),
                         ("failed", "oversized", None, False))

    def test_concurrent_reservations_mint_only_one_call_identity(self):
        run_id = self._prepare()
        results, errors = [], []
        def worker():
            try:
                results.append(self._reserve(run_id))
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=worker) for _ in range(2)]
        try:
            for thread in threads:
                thread.start()
        finally:
            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(sum(item.newly_reserved for item in results), 1)
        self.assertEqual(len({item.call_id for item in results}), 1)

    def test_grant_revocation_blocks_first_reservation_without_epoch_rotation(self):
        run_id = self._prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            epoch = connection.execute("SELECT approval_epoch FROM mentat_project_context_access_state").fetchone()[0]
            connection.execute("UPDATE mentat_project_context_grants SET state='revoked',reason='owner',revision=revision+1,updated_at=?",
                               (time.time(),))
            connection.commit()
            self.assertEqual(connection.execute("SELECT approval_epoch FROM mentat_project_context_access_state").fetchone()[0], epoch)
        with self.assertRaisesRegex(journal.WorkerJournalError, "fenced"):
            self._reserve(run_id)

    def test_restore_fences_replay_but_preserves_late_truthful_history_and_spent_work(self):
        run_id = self._prepare()
        first = self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            project_context_access.revoke_after_restore(connection)
            connection.commit()
        with self.assertRaisesRegex(journal.WorkerJournalError, "fenced"):
            self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._settle(connection, first, response_text="late historical result")
            connection.commit()
            self.assertEqual(tuple(connection.execute("SELECT state,work_debit FROM mentat_project_worker_calls").fetchone()), ("succeeded", 1))
            journal.validate_worker_journal_connection(connection)
        with self.assertRaisesRegex(journal.WorkerJournalError, "fenced"):
            self._reserve(run_id)

    def test_sql_budget_identity_and_retention_cannot_be_reset(self):
        run_id = self._prepare()
        first = self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            for statement in ("UPDATE mentat_project_worker_calls SET work_debit=0", "DELETE FROM mentat_project_worker_calls",
                              "DELETE FROM mentat_project_worker_generations", "DELETE FROM mentat_runs WHERE id=?"):
                with self.subTest(statement=statement), self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement, (run_id,) if "?" in statement else ())
                connection.rollback()
            connection.execute("DROP TRIGGER mentat_project_worker_call_no_new_identity")
            connection.execute("UPDATE mentat_project_worker_calls SET request_digest=? WHERE call_id=?", ("z" * 64, first.call_id))
            with self.assertRaises(journal.WorkerJournalError):
                journal.validate_worker_journal_connection(connection)
            connection.rollback()

    def test_sql_source_relation_rejects_console_even_with_borrowed_input_fields(self):
        run_id = self._prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,status,dispatch_state,created_at,updated_at) "
                               "VALUES('run_console_borrow','console','hermes','[]','reserved','reserved',?,?)",
                               (receipts.CREATED, receipts.CREATED))
            receipt = list(connection.execute("SELECT * FROM mentat_project_proposal_input_receipts WHERE run_id=?", (run_id,)).fetchone())
            receipt[0] = "run_console_borrow"
            connection.execute("INSERT INTO mentat_project_proposal_input_receipts VALUES(" + ",".join("?" for _ in receipt) + ")", receipt)
            claim = list(connection.execute("SELECT * FROM mentat_project_worker_generations WHERE run_id=?", (run_id,)).fetchone())
            claim[0], claim[2] = "run_console_borrow", "f" * 32
            with self.assertRaisesRegex(sqlite3.IntegrityError, "FOREIGN KEY"):
                connection.execute("INSERT INTO mentat_project_worker_generations VALUES(" + ",".join("?" for _ in claim) + ")", claim)
            connection.rollback()

    def test_shared_budget_failure_rolls_back_the_call_and_work_debit(self):
        run_id = self._prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            original = journal._validate_shared_graph
            checks = 0
            def late_failure(handle):
                nonlocal checks
                checks += 1
                if checks == 2:
                    raise project_context.ProjectContextError("project_context.capacity")
                original(handle)
            with patch.object(journal, "_validate_shared_graph", side_effect=late_failure), self.assertRaisesRegex(
                project_context.ProjectContextError, "capacity"
            ):
                journal.reserve_call(connection, run_id=run_id, generation=GENERATION, request_digest=REQUEST)
            # An outer caller that catches the failure and commits must not
            # publish the tentative call or its irreversible debit.
            connection.commit()
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_project_worker_calls").fetchone()[0], 0)

    def test_result_requires_original_host_token_and_recorded_submission(self):
        run_id = self._prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            call = journal.reserve_call(connection, run_id=run_id, generation=GENERATION, request_digest=REQUEST)
            with self.assertRaisesRegex(journal.WorkerJournalError, "not_submitted"):
                self._settle(connection, call, response_text="not a submitted result")
            self.assertTrue(journal.record_submission(connection, call_id=call.call_id, generation=GENERATION,
                            request_digest=REQUEST, settlement_token=call.settlement_token))
            self.assertFalse(journal.record_submission(connection, call_id=call.call_id, generation=GENERATION,
                             request_digest=REQUEST, settlement_token=call.settlement_token))
            with self.assertRaisesRegex(journal.WorkerJournalError, "result_owner"):
                journal.settle_call(connection, call_id=call.call_id, generation=GENERATION,
                                    request_digest=REQUEST, settlement_token="f" * 64, response_text="forged")
            connection.commit()
        replay = self._reserve(run_id)
        self.assertIsNone(replay.settlement_token)
        self.assertNotIn(call.settlement_token, repr(call))
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute("SELECT state FROM mentat_project_worker_calls").fetchone()[0], "unknown")

    def test_large_response_is_classified_without_encoding_it(self):
        class HugeText(str):
            def encode(self, *args, **kwargs):
                raise AssertionError("oversized text must not be encoded")
        run_id = self._prepare()
        first = self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._settle(connection, first, response_text=HugeText("x" * 32769))
            connection.commit()
        self.assertEqual(self._reserve(run_id).disposition, "oversized")

    def test_unknown_reservation_charges_terminal_result_capacity_in_advance(self):
        run_id = self._prepare()
        first = self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            charged_before = journal.validate_worker_journal_connection(connection)
            self.assertEqual(len(charged_before[1][0][8]), 65536)
            connection.execute("BEGIN IMMEDIATE")
            self._settle(connection, first, response_text="\n" * 32768)
            connection.commit()
            charged_after = journal.validate_worker_journal_connection(connection)
            self.assertEqual(charged_before, charged_after)

    def test_failed_and_non_text_outcomes_replay_without_extra_work(self):
        run_id = self._prepare()
        first = self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._settle(connection, first, response_text={"tool_calls": []})

            connection.commit()
        repeated = self._reserve(run_id)
        self.assertEqual((repeated.newly_reserved, repeated.state, repeated.disposition), (False, "failed", "non_text"))

    def test_empty_schema43_backup_restore_and_schema5_projection(self):
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target / "private").mkdir(parents=True, mode=0o700)
            private_console_unit.materialize_private_console_unit(
                target, private_console_unit.sanitize_owner_auth_restore_unit(unit), target / "private" / "console")
            with closing(mentat_db.connect(target)) as connection:
                self.assertEqual(mentat_db.schema_signature_state(connection, 43), "expected")
                self.assertEqual(journal.validate_worker_journal_connection(connection), [[], []])
            compatible = _schema5_private_unit(unit)
            with closing(sqlite3.connect(":memory:")) as connection:
                connection.deserialize(compatible.database_raw)
                self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='mentat_project_worker_calls'").fetchone())

    def test_populated_known_journal_survives_validated_restore_without_live_authority(self):
        run_id = self._prepare()
        first = self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._settle(connection, first, response_text="retained broker text")
            connection.commit()
            with self.assertRaises(run_attention.RunAttentionError):
                run_attention.validate_run_attention_connection(connection)
            with self.assertRaises(RunRepositoryError):
                RunRepository(connection).validate()
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target / "private").mkdir(parents=True, mode=0o700)
            restored = private_console_unit.sanitize_owner_auth_restore_unit(unit)
            private_console_unit.materialize_private_console_unit(target, restored, target / "private" / "console")
            with closing(mentat_db.connect(target)) as connection:
                self.assertEqual(tuple(connection.execute("SELECT state,response_text,work_debit FROM mentat_project_worker_calls").fetchone()),
                                 ("succeeded", "retained broker text", 1))
                connection.execute("BEGIN IMMEDIATE")
                with self.assertRaisesRegex(journal.WorkerJournalError, "fenced"):
                    journal.reserve_call(connection, run_id=run_id, generation=GENERATION, request_digest=REQUEST)
                connection.rollback()

    def test_populated_unknown_and_token_hash_survive_restore_without_reissue(self):
        run_id = self._prepare()
        first = self._reserve(run_id)
        with closing(mentat_db.connect(self.root)) as connection:
            expected_hash = connection.execute("SELECT result_token_hash FROM mentat_project_worker_calls").fetchone()[0]
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        self.assertNotIn(first.settlement_token.encode(), unit.database_raw)
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target / "private").mkdir(parents=True, mode=0o700)
            private_console_unit.materialize_private_console_unit(
                target, private_console_unit.sanitize_owner_auth_restore_unit(unit), target / "private" / "console")
            with closing(mentat_db.connect(target)) as connection:
                self.assertEqual(tuple(connection.execute("SELECT state,work_debit,result_token_hash FROM mentat_project_worker_calls").fetchone()),
                                 ("unknown", 1, expected_hash))
                connection.execute("BEGIN IMMEDIATE")
                with self.assertRaisesRegex(journal.WorkerJournalError, "fenced"):
                    journal.record_submission(connection, call_id=first.call_id, generation=GENERATION,
                                              request_digest=REQUEST, settlement_token=first.settlement_token)
                connection.rollback()

    def test_private_archive_rejects_unbound_or_live_proposal_state(self):
        run_id = self._prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE mentat_runs SET status='starting',state_revision=state_revision+1 WHERE id=?", (run_id,))
            with self.assertRaises(journal.WorkerJournalError):
                journal.archival_proposal_ids(connection)
            connection.rollback()

    def test_archive_rejects_reconciliation_lease_without_granting_live_visibility(self):
        run_id = self._prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE mentat_runs SET reconcile_lease_owner='synthetic-lease',reconcile_lease_until=? WHERE id=?",
                               (time.time() + 60, run_id))
            with self.assertRaises(journal.WorkerJournalError):
                journal.archival_proposal_ids(connection)
            connection.rollback()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DROP TRIGGER mentat_project_worker_generation_retained")
            connection.execute("DELETE FROM mentat_project_worker_generations")
            with self.assertRaises(journal.WorkerJournalError):
                journal.archival_proposal_ids(connection)
            connection.rollback()

    def test_exact_schema42_upgrade_preserves_closed_dispatch_and_fk_integrity(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "mentat.sqlite3"
            private_console_unit._initialize_database(path, schema_version=42)
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("PRAGMA foreign_keys=ON")
                mentat_db.migrate(connection)
                self.assertEqual(mentat_db.schema_signature_state(connection, 43), "expected")
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(journal.validate_worker_journal_connection(connection), [[], []])
                with self.assertRaisesRegex(sqlite3.IntegrityError, "proposal_unqualified"):
                    connection.execute("INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,status,dispatch_state,created_at,updated_at) "
                                       "VALUES('run_closed','project_proposal','hermes','[]','reserved','reserved',?,?)",
                                       (receipts.CREATED, receipts.CREATED))

    def test_policy_and_transaction_are_not_caller_chosen_work_or_implicit_authority(self):
        with self.assertRaises(journal.WorkerJournalError):
            journal.normalize_policy({**POLICY, "inference_calls": 2})
        with self.assertRaises(journal.WorkerJournalError):
            journal.normalize_policy({**POLICY, "max_request_bytes": 16 * 1024 * 1024 + 1})
        with closing(mentat_db.connect(self.root)) as connection:
            with self.assertRaisesRegex(journal.WorkerJournalError, "transaction_required"):
                journal.reserve_call(connection, run_id="run_missing", generation=GENERATION, request_digest=REQUEST)


if __name__ == "__main__":
    unittest.main()
