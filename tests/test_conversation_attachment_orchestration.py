from __future__ import annotations

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from agent_console_attachments import create_attachment
from conversation_attachments import (
    associate_staged_attachment,
    conversation_media,
    conversation_staged_context,
    replace_context_pack_stage,
    stage_uploaded_attachment,
)
from mentat_db import connect
from orchestration_service import OrchestrationServiceError
from tests import test_orchestration_service as orchestration_test_support


class ConversationAttachmentOrchestrationTests(unittest.TestCase):
    def prepare(self, root: Path, *, capable: bool = True, runtime_supported: bool = True):
        runtime = orchestration_test_support.FakeRuntime(root)
        runtime.supports_attachments = lambda _binding: runtime_supported
        helper = orchestration_test_support.OrchestrationServiceTests()
        service, conversation_id = helper.prepare_conversation(
            root,
            runtime,
            agent_capabilities=(
                ("run.start", "run.message", "run.attachments")
                if capable
                else ("run.start", "run.message")
            ),
        )
        service.conversation_attachment_preparer = lambda _run_id, _attachments: None
        service.conversation_attachment_cleanup = lambda _run_id: None
        return runtime, service, conversation_id

    def test_idle_send_binds_exact_staged_context_before_one_runtime_call(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime, service, conversation_id = self.prepare(root)
            staged = stage_uploaded_attachment(
                root,
                conversation_id,
                original_name="context.txt",
                content=b"context",
            )
            attachment_id = staged["attachments"][0]["id"]

            result = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Use the staged context",
                idempotency_key="attachment-submit-key-1",
            )

            self.assertEqual(result.disposition, "accepted")
            self.assertEqual(len(runtime.calls), 1)
            self.assertEqual(runtime.calls[0][1].attachment_ids, (attachment_id,))
            self.assertEqual(conversation_staged_context(root, conversation_id)["attachments"], [])
            media = conversation_media(root, conversation_id)
            self.assertEqual(media["runs"][0]["inputs"][0]["id"], attachment_id)
            with closing(connect(root)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_conversation_run_contexts WHERE run_id = ?",
                        (result.run.id,),
                    ).fetchone()[0],
                    1,
                )

    def test_exact_replay_survives_consumption_but_changed_new_context_conflicts(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            _runtime, service, conversation_id = self.prepare(root)
            stage_uploaded_attachment(
                root,
                conversation_id,
                original_name="first.txt",
                content=b"first",
            )
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Review this",
                idempotency_key="attachment-replay-key-1",
            )
            replay = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Review this",
                idempotency_key="attachment-replay-key-1",
            )
            self.assertTrue(replay.duplicate)
            self.assertEqual(replay.run.id, first.run.id)

            with closing(connect(root)) as connection:
                connection.execute(
                    "UPDATE mentat_runs SET status = 'completed', dispatch_state = 'accepted', "
                    "terminal_finalized = 1, completed_at = updated_at WHERE id = ?",
                    (first.run.id,),
                )
                connection.execute(
                    "UPDATE mentat_conversation_turns SET state = 'consumed' WHERE latest_run_id = ?",
                    (first.run.id,),
                )
            staged = create_attachment(root, original_name="changed.txt", content=b"changed")
            associate_staged_attachment(root, conversation_id, staged["id"], source="upload")
            with self.assertRaises(OrchestrationServiceError) as conflict:
                service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Review this",
                    idempotency_key="attachment-replay-key-1",
                )
            self.assertEqual(conflict.exception.code, "conversation.idempotency_conflict")

    def test_simultaneous_exact_context_send_replays_the_winner(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime, service, conversation_id = self.prepare(root)
            runtime.submission_lock = threading.Lock()
            stage_uploaded_attachment(
                root,
                conversation_id,
                original_name="shared.txt",
                content=b"shared",
            )
            barrier = threading.Barrier(3)
            results = []
            errors = []

            def submit():
                barrier.wait()
                try:
                    results.append(service.submit_conversation_turn(
                        conversation_id=conversation_id,
                        text="Use this once",
                        idempotency_key="attachment-simultaneous-key",
                    ))
                except Exception as exc:
                    errors.append(exc)

            workers = [threading.Thread(target=submit) for _ in range(2)]
            for worker in workers:
                worker.start()
            barrier.wait()
            for worker in workers:
                worker.join(timeout=5)

            self.assertTrue(all(not worker.is_alive() for worker in workers))
            self.assertEqual(errors, [])
            self.assertEqual(sorted(result.duplicate for result in results), [False, True])
            self.assertEqual(len(runtime.calls), 1)

    def test_agent_and_runtime_attachment_capability_fail_before_turn_or_adapter(self):
        for capable, runtime_supported, expected in (
            (False, True, "conversation_context.capability_missing"),
            (True, False, "conversation_context.runtime_unsupported"),
        ):
            with self.subTest(capable=capable, runtime_supported=runtime_supported), TemporaryDirectory() as temporary:
                root = Path(temporary)
                runtime, service, conversation_id = self.prepare(
                    root,
                    capable=capable,
                    runtime_supported=runtime_supported,
                )
                stage_uploaded_attachment(
                    root,
                    conversation_id,
                    original_name="context.txt",
                    content=b"context",
                )
                with self.assertRaises(OrchestrationServiceError) as rejected:
                    service.submit_conversation_turn(
                        conversation_id=conversation_id,
                        text="Do not drop the file",
                        idempotency_key="attachment-capability-key-1",
                    )
                self.assertEqual(rejected.exception.code, expected)
                self.assertEqual(runtime.calls, [])
                with closing(connect(root)) as connection:
                    self.assertEqual(
                        connection.execute(
                            "SELECT COUNT(*) FROM mentat_conversation_turns"
                        ).fetchone()[0],
                        0,
                    )
                self.assertEqual(
                    len(conversation_staged_context(root, conversation_id)["attachments"]),
                    1,
                )

    def test_runtime_support_loss_under_submission_guard_preserves_staging(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime, service, conversation_id = self.prepare(root)
            calls = 0

            def supports(_binding):
                nonlocal calls
                calls += 1
                return calls == 1

            class Guard:
                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            runtime.supports_attachments = supports
            runtime.submission_guard = lambda: Guard()
            stage_uploaded_attachment(
                root,
                conversation_id,
                original_name="preserve.txt",
                content=b"preserve",
            )

            with self.assertRaises(OrchestrationServiceError) as rejected:
                service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Do not consume this file",
                    idempotency_key="attachment-support-race-key",
                )

            self.assertEqual(
                rejected.exception.code,
                "conversation_context.runtime_unsupported",
            )
            self.assertEqual(runtime.calls, [])
            self.assertEqual(
                len(conversation_staged_context(root, conversation_id)["attachments"]),
                1,
            )
            with closing(connect(root)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_conversation_turns"
                    ).fetchone()[0],
                    0,
                )

    def test_changed_context_pack_fails_before_binding_and_preserves_staging(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime, service, conversation_id = self.prepare(root)
            attachment = create_attachment(
                root,
                original_name="pack.md",
                content=b"pack",
            )
            replace_context_pack_stage(
                root,
                conversation_id,
                pack_id="pack_0123456789abcdef",
                pack_revision="sha256:" + "a" * 64,
                pack_name="Changed pack",
                attachment_ids=(attachment["id"],),
                source_digests=("b" * 64,),
            )
            service.conversation_context_validator = lambda _pack, _digests: False

            with self.assertRaises(OrchestrationServiceError) as rejected:
                service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Do not bind stale context",
                    idempotency_key="attachment-pack-change-key",
                )

            self.assertEqual(
                rejected.exception.code,
                "conversation_context.pack_changed",
            )
            self.assertEqual(runtime.calls, [])
            staged = conversation_staged_context(root, conversation_id)
            self.assertEqual(staged["context_pack"]["name"], "Changed pack")
            self.assertEqual(len(staged["attachments"]), 1)
            with closing(connect(root)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_conversation_turns"
                    ).fetchone()[0],
                    0,
                )

    def test_input_preparation_failure_preserves_staging_and_creates_no_turn(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime, service, conversation_id = self.prepare(root)
            service.conversation_attachment_preparer = (
                lambda _run_id, _attachments: (_ for _ in ()).throw(
                    RuntimeError("tampered")
                )
            )
            stage_uploaded_attachment(
                root,
                conversation_id,
                original_name="tampered.txt",
                content=b"tampered",
            )

            with self.assertRaises(OrchestrationServiceError) as rejected:
                service.submit_conversation_turn(
                    conversation_id=conversation_id,
                    text="Preserve the staged file",
                    idempotency_key="attachment-preparation-failure-key",
                )

            self.assertEqual(
                rejected.exception.code,
                "conversation_context.attachment_unavailable",
            )
            self.assertEqual(runtime.calls, [])
            self.assertEqual(
                len(conversation_staged_context(root, conversation_id)["attachments"]),
                1,
            )
            with closing(connect(root)) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_conversation_turns"
                    ).fetchone()[0],
                    0,
                )

    def test_retry_clones_exact_retained_inputs_and_never_becomes_text_only(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime, service, conversation_id = self.prepare(root)
            runtime.rejects = True
            attachment_id = stage_uploaded_attachment(
                root,
                conversation_id,
                original_name="retry.txt",
                content=b"retain me",
            )["attachments"][0]["id"]
            first = service.submit_conversation_turn(
                conversation_id=conversation_id,
                text="Retry with the same context",
                idempotency_key="attachment-initial-retry-key",
            )
            self.assertEqual(first.run.status, "failed")
            runtime.rejects = False
            runtime.supports_attachments = lambda _binding: False
            with self.assertRaises(OrchestrationServiceError) as unsupported:
                service.retry_conversation_run(
                    conversation_id=conversation_id,
                    source_run_id=first.run.id,
                    idempotency_key="attachment-unsupported-retry-key",
                )
            self.assertEqual(
                unsupported.exception.code,
                "conversation_context.runtime_unsupported",
            )
            runtime.supports_attachments = lambda _binding: True
            retried = service.retry_conversation_run(
                conversation_id=conversation_id,
                source_run_id=first.run.id,
                idempotency_key="attachment-explicit-retry-key",
            )

            self.assertEqual(len(runtime.calls), 2)
            self.assertEqual(runtime.calls[1][1].attachment_ids, (attachment_id,))
            with closing(connect(root)) as connection:
                bindings = connection.execute(
                    "SELECT run_id, attachment_id FROM run_attachments "
                    "WHERE direction = 'input' ORDER BY run_id"
                ).fetchall()
            self.assertEqual(
                {tuple(row) for row in bindings},
                {
                    (first.run.id, attachment_id),
                    (retried.attempt.run_id, attachment_id),
                },
            )


if __name__ == "__main__":
    unittest.main()
