from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from mentat_db import connect
from task_delegation_receipts import (
    DelegationActionReceiptRepository,
    DelegationReceiptConflict,
    DelegationReceiptUnavailable,
    DelegationReceiptValidationError,
    idempotency_key_digest,
)


def _digest(character: str) -> str:
    return character * 64


class DelegationActionReceiptRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.connection = connect(Path(self.temporary.name))
        self.repository = DelegationActionReceiptRepository(self.connection)

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary.cleanup()

    @staticmethod
    def _arguments(*, key: str = "a", request: str = "b", task_id: str = "task_without_a_foreign_key") -> dict[str, object]:
        return {
            "key_digest": _digest(key),
            "request_digest": _digest(request),
            "task_id": task_id,
            "task_revision": 1,
            "action": "delegate",
            "confirmation_digest": _digest("c"),
            "delegation_binding_digest": _digest("d"),
            "remote_revision_digest": _digest("e"),
            "now": "2026-09-02T12:00:00Z",
            "epoch": 1_000.0,
        }

    def test_reserve_is_exact_idempotent_and_does_not_require_a_task_foreign_key(self) -> None:
        first = self.repository.reserve(**self._arguments())
        replay = self.repository.reserve(**self._arguments())

        self.assertEqual(first.state, "reserved")
        self.assertEqual(first.task_id, "task_without_a_foreign_key")
        self.assertFalse(first.duplicate)
        self.assertTrue(replay.duplicate)
        self.assertEqual(replay, first.__class__(**{**first.__dict__, "duplicate": True}))
        self.assertEqual(self.repository.get(key_digest=_digest("a")), first)

    def test_conflicting_key_reuse_and_active_task_are_rejected(self) -> None:
        self.repository.reserve(**self._arguments())
        conflicting = self._arguments(request="f")
        with self.assertRaisesRegex(DelegationReceiptConflict, "idempotency_conflict"):
            self.repository.reserve(**conflicting)

        active_task = self._arguments(key="f")
        with self.assertRaisesRegex(DelegationReceiptConflict, "action_active"):
            self.repository.reserve(**active_task)

    def test_lifecycle_allows_verified_reconciliation_but_never_replays_uncertain_work(self) -> None:
        reserved = self.repository.reserve(**self._arguments())
        submitting = self.repository.mark_submitting(
            key_digest=reserved.key_digest, now="2026-09-02T12:01:00Z"
        )
        self.repository.stage_verified_result(
            key_digest=reserved.key_digest,
            result_task_revision=2,
            result_proof_digest=_digest("f"),
            now="2026-09-02T12:01:30Z",
        )
        unknown = self.repository.mark_outcome(
            key_digest=reserved.key_digest,
            state="unknown",
            result_task_revision=None,
            now="2026-09-02T12:02:00Z",
            epoch=2_000.0,
        )
        accepted = self.repository.mark_outcome(
            key_digest=reserved.key_digest,
            state="accepted",
            result_task_revision=2,
            now="2026-09-02T12:03:00Z",
            epoch=2_000.0,
            retention_seconds=60,
        )

        self.assertEqual(submitting.state, "submitting")
        self.assertEqual(unknown.state, "unknown")
        self.assertIsNone(unknown.expires_at)
        self.assertEqual(accepted.state, "accepted")
        self.assertEqual(accepted.result_task_revision, 2)
        self.assertEqual(accepted.expires_at, 2_060.0)
        with self.assertRaisesRegex(DelegationReceiptConflict, "state_conflict"):
            self.repository.mark_submitting(key_digest=reserved.key_digest)

    def test_expiry_is_bounded_to_terminal_receipts_and_uncertain_receipts_are_retained(self) -> None:
        terminal = self.repository.reserve(**self._arguments())
        self.repository.mark_outcome(
            key_digest=terminal.key_digest,
            state="rejected",
            now="2026-09-02T12:01:00Z",
            epoch=5_000.0,
            retention_seconds=10,
        )
        uncertain = self.repository.reserve(**self._arguments(key="f", task_id="task_uncertain"))
        self.repository.mark_outcome(
            key_digest=uncertain.key_digest,
            state="unknown",
            now="2026-09-02T12:01:00Z",
            epoch=5_000.0,
        )

        self.assertEqual(self.repository.prune_expired(epoch=5_009.0), 0)
        self.assertEqual(self.repository.prune_expired(epoch=5_010.0), 1)
        self.assertIsNone(self.repository.get(key_digest=terminal.key_digest))
        retained = self.repository.get(key_digest=uncertain.key_digest)
        self.assertIsNotNone(retained)
        self.assertEqual(retained.state, "unknown")
        self.assertIsNone(retained.expires_at)

    def test_mutation_joins_a_caller_transaction_and_rolls_back_with_it(self) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        self.repository.reserve(**self._arguments())
        self.connection.rollback()

        self.assertIsNone(self.repository.get(key_digest=_digest("a")))

    def test_raw_key_and_receipt_inputs_are_strictly_validated(self) -> None:
        self.assertEqual(len(idempotency_key_digest("a" * 16)), 64)
        with self.assertRaises(DelegationReceiptValidationError):
            idempotency_key_digest("short")
        invalid = self._arguments()
        invalid["confirmation_digest"] = "not-a-digest"
        with self.assertRaisesRegex(DelegationReceiptValidationError, "confirmation_invalid"):
            self.repository.reserve(**invalid)

    def test_receipt_repository_rejects_current_schema_index_drift(self) -> None:
        self.connection.execute(
            "DROP INDEX idx_mentat_task_delegation_action_receipts_active_task"
        )
        with self.assertRaisesRegex(DelegationReceiptUnavailable, "schema_unsupported"):
            DelegationActionReceiptRepository(self.connection)

    def test_accepted_outcome_requires_the_verified_task_revision(self) -> None:
        receipt = self.repository.reserve(**self._arguments())
        self.repository.mark_submitting(key_digest=receipt.key_digest)
        with self.assertRaisesRegex(
            DelegationReceiptValidationError, "result_revision_required"
        ):
            self.repository.mark_outcome(
                key_digest=receipt.key_digest,
                state="accepted",
            )

    def test_accepted_outcome_requires_a_staged_exact_result_proof(self) -> None:
        receipt = self.repository.reserve(**self._arguments())
        self.repository.mark_submitting(key_digest=receipt.key_digest)
        with self.assertRaisesRegex(
            DelegationReceiptValidationError, "result_proof_required"
        ):
            self.repository.mark_outcome(
                key_digest=receipt.key_digest,
                state="accepted",
                result_task_revision=2,
            )

    def test_reject_unsubmitted_never_terminalizes_a_submitting_receipt(self) -> None:
        receipt = self.repository.reserve(**self._arguments())
        self.repository.mark_submitting(key_digest=receipt.key_digest)

        with self.assertRaisesRegex(DelegationReceiptConflict, "state_conflict"):
            self.repository.reject_unsubmitted(key_digest=receipt.key_digest)

        self.assertEqual(
            self.repository.get(key_digest=receipt.key_digest).state, "submitting"
        )

    def test_corrupt_accepted_receipt_without_result_revision_fails_closed(self) -> None:
        receipt = self.repository.reserve(**self._arguments())
        self.connection.execute(
            "UPDATE mentat_task_delegation_action_receipts "
            "SET state = 'accepted', expires_at = 2000 WHERE key_digest = ?",
            (receipt.key_digest,),
        )

        with self.assertRaisesRegex(DelegationReceiptUnavailable, "corrupt"):
            self.repository.get(key_digest=receipt.key_digest)


if __name__ == "__main__":
    unittest.main()
