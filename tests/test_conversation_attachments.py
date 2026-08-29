from __future__ import annotations

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import sqlite3

from conversation_attachments import (
    ConversationAttachmentError,
    associate_staged_attachment,
    conversation_staged_context,
    open_conversation_attachment_stream,
    reconcile_staged_contexts,
    release_staged_attachment,
    clear_staged_context_pack,
    replace_context_pack_stage,
    stage_uploaded_attachment,
)
from agent_console_attachments import create_attachment, get_attachment
from agent_registry import AgentRegistry
from conversation_repository import ConversationRepository
from mentat_db import SCHEMA_VERSION, connect, schema_version
from private_console_unit import capture_private_console_unit


class ConversationAttachmentTests(unittest.TestCase):
    def conversations(self, root: Path) -> tuple[str, str]:
        agent_id = "agent_conversation_attachments"
        AgentRegistry(root, supported_runtime_types=("hermes",)).create_agent(
            agent_id=agent_id,
            name="Conversation attachments",
            runtime_config_id="runtime_conversation_attachments",
            runtime_type="hermes",
            runtime_agent_ref="conversation-attachments",
            capabilities=("run.message", "run.start"),
        )
        repository = ConversationRepository(
            root,
            supported_runtime_types=("hermes",),
        )
        return (
            repository.create(agent_id=agent_id).conversation.id,
            repository.create(agent_id=agent_id).conversation.id,
        )

    def test_schema_15_staging_is_exact_conversation_owned_and_refreshable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = self.conversations(root)
            staged = stage_uploaded_attachment(
                root,
                first,
                original_name="notes.txt",
                content=b"reviewed context",
                content_type="text/plain",
            )
            item = staged["attachments"][0]

            self.assertEqual(schema_version(root), SCHEMA_VERSION)
            self.assertEqual(SCHEMA_VERSION, 16)
            self.assertEqual(staged["conversation_id"], first)
            self.assertEqual(item["source"], "upload")
            self.assertTrue(item["available"])
            self.assertNotIn("path", repr(staged))
            self.assertNotIn("sha256", repr(staged))
            self.assertEqual(conversation_staged_context(root, first), staged)
            self.assertEqual(conversation_staged_context(root, second)["attachments"], [])

            metadata, stream = open_conversation_attachment_stream(root, first, item["id"])
            try:
                self.assertEqual(stream.read(), b"reviewed context")
            finally:
                stream.close()
            self.assertEqual(metadata["id"], item["id"])
            with self.assertRaises(ConversationAttachmentError):
                open_conversation_attachment_stream(root, second, item["id"])

    def test_direct_total_and_image_limits_fail_without_cross_conversation_binding(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first, second = self.conversations(root)
            for index in range(5):
                stage_uploaded_attachment(
                    root,
                    first,
                    original_name=f"item-{index}.txt",
                    content=f"item {index}".encode(),
                )
            with self.assertRaises(ConversationAttachmentError) as capacity:
                stage_uploaded_attachment(
                    root,
                    first,
                    original_name="sixth.txt",
                    content=b"sixth",
                )
            self.assertEqual(capacity.exception.code, "conversation_context.capacity")
            self.assertEqual(len(conversation_staged_context(root, first)["attachments"]), 5)
            self.assertEqual(conversation_staged_context(root, second)["attachments"], [])

    def test_expired_staging_is_unavailable_before_periodic_collection(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            conversation, _other = self.conversations(root)
            staged = stage_uploaded_attachment(
                root,
                conversation,
                original_name="expired.txt",
                content=b"expired",
            )
            attachment_id = staged["attachments"][0]["id"]
            with closing(connect(root)) as connection:
                connection.execute(
                    "UPDATE attachments SET expires_at = ? WHERE id = ?",
                    (0, attachment_id),
                )

            projected = conversation_staged_context(root, conversation)

            self.assertFalse(projected["attachments"][0]["available"])
            with self.assertRaises(ConversationAttachmentError):
                open_conversation_attachment_stream(
                    root,
                    conversation,
                    attachment_id,
                )

    def test_context_pack_replacement_preserves_direct_items_and_releases_old_snapshots(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            conversation, _other = self.conversations(root)
            direct = stage_uploaded_attachment(
                root,
                conversation,
                original_name="direct.txt",
                content=b"direct",
            )["attachments"][0]
            old = create_attachment(root, original_name="old.md", content=b"old")
            first = replace_context_pack_stage(
                root,
                conversation,
                pack_id="pack_" + "a" * 16,
                pack_revision="sha256:" + "b" * 64,
                pack_name="Old pack",
                attachment_ids=[old["id"]],
                source_digests=["1" * 64],
            )
            self.assertEqual([item["source"] for item in first["attachments"]], ["upload", "context_pack"])

            new = create_attachment(root, original_name="new.md", content=b"new")
            replaced = replace_context_pack_stage(
                root,
                conversation,
                pack_id="pack_" + "c" * 16,
                pack_revision="sha256:" + "d" * 64,
                pack_name="New pack",
                attachment_ids=[new["id"]],
                source_digests=["2" * 64],
            )
            self.assertEqual(replaced["context_pack"]["name"], "New pack")
            self.assertEqual([item["id"] for item in replaced["attachments"]], [direct["id"], new["id"]])
            self.assertEqual(get_attachment(root, old["id"])["state"], "orphaned")
            cleared = release_staged_attachment(root, conversation, new["id"])
            self.assertIsNone(cleared["context_pack"])
            self.assertEqual([item["id"] for item in cleared["attachments"]], [direct["id"]])
            self.assertEqual(get_attachment(root, new["id"])["state"], "orphaned")

    def test_instructions_only_context_pack_can_be_cleared(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            conversation, _other = self.conversations(root)
            staged = replace_context_pack_stage(
                root,
                conversation,
                pack_id="pack_0123456789abcdef",
                pack_revision="sha256:" + "1" * 64,
                pack_name="Instructions only",
                attachment_ids=(),
                source_digests=(),
            )
            self.assertEqual(staged["attachments"], [])
            self.assertIsNotNone(staged["context_pack"])

            cleared = clear_staged_context_pack(root, conversation)

            self.assertEqual(cleared["attachments"], [])
            self.assertIsNone(cleared["context_pack"])

    def test_release_and_reconciliation_remove_only_staged_authority(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            conversation, _other = self.conversations(root)
            item = stage_uploaded_attachment(
                root,
                conversation,
                original_name="temporary.txt",
                content=b"temporary",
            )["attachments"][0]
            released = release_staged_attachment(root, conversation, item["id"])
            self.assertEqual(released["attachments"], [])
            self.assertEqual(get_attachment(root, item["id"])["state"], "orphaned")

            stale = create_attachment(root, original_name="stale.txt", content=b"stale")
            associate_staged_attachment(root, conversation, stale["id"], source="workspace")
            with closing(connect(root)) as connection:
                connection.execute(
                    "UPDATE attachments SET state = 'missing' WHERE id = ?",
                    (stale["id"],),
                )
            report = reconcile_staged_contexts(root)
            self.assertEqual(report["staged_references_removed"], 1)
            self.assertEqual(conversation_staged_context(root, conversation)["attachments"], [])

    def test_reconciliation_drops_an_entire_changed_context_pack_snapshot(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            conversation, _other = self.conversations(root)
            first = create_attachment(root, original_name="first.md", content=b"first")
            second = create_attachment(root, original_name="second.md", content=b"second")
            replace_context_pack_stage(
                root,
                conversation,
                pack_id="pack_0123456789abcdef",
                pack_revision="sha256:" + "2" * 64,
                pack_name="Exact pack",
                attachment_ids=(first["id"], second["id"]),
                source_digests=("3" * 64, "4" * 64),
            )
            with closing(connect(root)) as connection:
                connection.execute(
                    "UPDATE attachments SET state = 'missing' WHERE id = ?",
                    (first["id"],),
                )

            report = reconcile_staged_contexts(root)

            self.assertEqual(report["staged_references_removed"], 2)
            self.assertEqual(report["context_packs_removed"], 1)
            staged = conversation_staged_context(root, conversation)
            self.assertIsNone(staged["context_pack"])
            self.assertEqual(staged["attachments"], [])
            self.assertEqual(get_attachment(root, second["id"])["state"], "orphaned")

    def test_private_backup_snapshot_excludes_unsent_staging_and_its_blob(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            conversation, _other = self.conversations(root)
            stage_uploaded_attachment(
                root,
                conversation,
                original_name="unsent.txt",
                content=b"not backup authority",
            )
            unit = capture_private_console_unit(root)
            snapshot = Path(temporary) / "snapshot.sqlite3"
            snapshot.write_bytes(unit.database_raw)
            connection = sqlite3.connect(snapshot)
            try:
                counts = tuple(
                    int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                    for table in (
                        "mentat_conversation_staged_attachments",
                        "mentat_conversation_staged_contexts",
                        "attachments",
                        "blobs",
                    )
                )
            finally:
                connection.close()
            self.assertEqual(counts, (0, 0, 0, 0))
            self.assertEqual(unit.blobs, ())


if __name__ == "__main__":
    unittest.main()
