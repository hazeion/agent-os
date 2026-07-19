import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_console_attachments as attachments
from agent_console_attachments import (
    AttachmentStorageError,
    AttachmentUnavailable,
    AttachmentValidationError,
    bind_run_attachment,
    create_attachment,
    garbage_collect,
    get_attachment,
    list_run_attachments,
    reconcile_startup,
    release_attachment,
    resolve_blob_path,
    unbind_run_attachments,
)
from mentat_db import connect, database_path, schema_version


PNG = b"\x89PNG\r\n\x1a\n" + b"safe-image-payload"


class AgentConsoleAttachmentTests(unittest.TestCase):
    def make_data_dir(self, root: str) -> Path:
        return Path(root) / "data"

    def test_database_migrates_privately_and_stages_safe_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            metadata = create_attachment(
                data_dir,
                original_name="diagram.png",
                content=PNG,
                content_type="image/png",
                now=1_000,
            )

            self.assertEqual(schema_version(data_dir), 1)
            self.assertEqual(metadata["kind"], "image")
            self.assertEqual(metadata["mime_type"], "image/png")
            self.assertEqual(metadata["state"], "staged")
            self.assertNotIn("path", metadata)
            self.assertNotIn("storage_key", metadata)
            self.assertNotIn("sha256", metadata)
            self.assertEqual(get_attachment(data_dir, metadata["id"]), metadata)
            self.assertEqual(resolve_blob_path(data_dir, metadata["id"]).read_bytes(), PNG)

            if os.name != "nt":
                self.assertEqual(database_path(data_dir).stat().st_mode & 0o777, 0o600)
                self.assertEqual((data_dir / "private" / "console").stat().st_mode & 0o777, 0o700)
                self.assertEqual(resolve_blob_path(data_dir, metadata["id"]).stat().st_mode & 0o777, 0o600)

    def test_streaming_text_validation_and_content_addressed_deduplication(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            first = create_attachment(
                data_dir,
                original_name="example.py",
                stream=io.BytesIO(b"print('hello')\n"),
                content_type="text/x-python; charset=utf-8",
            )
            second = create_attachment(
                data_dir,
                original_name="copy.py",
                content=b"print('hello')\n",
            )
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(first["kind"], "text")
            self.assertEqual(resolve_blob_path(data_dir, first["id"]), resolve_blob_path(data_dir, second["id"]))

            connection = connect(data_dir)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM blobs").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0], 2)
            finally:
                connection.close()

    def test_rejects_paths_secrets_svg_archives_executables_and_mismatched_content(self):
        cases = (
            ("../escape.txt", b"hello", "text/plain"),
            (".env", b"TOKEN=value", "text/plain"),
            ("private.pem", b"hello", "text/plain"),
            ("drawing.svg", b"<svg></svg>", "image/svg+xml"),
            ("drawing.xml", b"<?xml version='1.0'?><svg></svg>", "application/xml"),
            ("archive.txt", b"PK\x03\x04payload", "text/plain"),
            ("program.txt", b"\x7fELFpayload", "text/plain"),
            ("not-really.png", b"plain text", "image/png"),
            ("wrong.jpg", PNG, "image/jpeg"),
            ("token.txt", b"sk-abcdefghijklmnopqrstuvwxyz123456", "text/plain"),
            ("settings.yaml", b"api_key: abcdefghijklmnopqrstuvwxyz", "application/yaml"),
            ("binary.txt", b"hello\x00world", "text/plain"),
        )
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            for name, payload, content_type in cases:
                with self.subTest(name=name):
                    with self.assertRaises(AttachmentValidationError):
                        create_attachment(
                            data_dir,
                            original_name=name,
                            content=payload,
                            content_type=content_type,
                        )

    def test_size_limit_is_enforced_while_streaming(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            with patch.object(attachments, "MAX_TEXT_BYTES", 8):
                with self.assertRaises(AttachmentValidationError):
                    create_attachment(
                        data_dir,
                        original_name="large.txt",
                        stream=io.BytesIO(b"123456789"),
                    )
            connection = connect(data_dir)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM attachments").fetchone()[0], 0)
            finally:
                connection.close()

    def test_promotion_fallback_never_overwrites_an_existing_blob(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            with patch("agent_console_attachments.os.link", side_effect=OSError("unsupported")):
                item = create_attachment(data_dir, original_name="fallback.txt", content=b"fallback")
            self.assertEqual(resolve_blob_path(data_dir, item["id"]).read_bytes(), b"fallback")

            connection = connect(data_dir)
            try:
                row = connection.execute("SELECT storage_key FROM blobs").fetchone()
            finally:
                connection.close()
            path = data_dir / "private" / "console" / "blobs" / "sha256" / row["storage_key"]
            path.write_bytes(b"unrelated")
            with self.assertRaises(AttachmentStorageError):
                create_attachment(data_dir, original_name="again.txt", content=b"fallback")
            self.assertEqual(path.read_bytes(), b"unrelated")

    def test_run_references_protect_then_release_blobs_after_grace(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            item = create_attachment(data_dir, original_name="context.txt", content=b"context", now=1_000)
            bound = bind_run_attachment(data_dir, item["id"], "run_123", now=1_010)
            self.assertEqual(bound["state"], "attached")
            retained = list_run_attachments(data_dir, "run_123", direction="input")
            self.assertEqual(retained[0]["id"], item["id"])
            self.assertEqual(retained[0]["direction"], "input")
            self.assertNotIn("path", retained[0])

            report = garbage_collect(data_dir, active_run_ids={"run_123"}, now=20_000)
            self.assertEqual(report["deleted"], 0)
            self.assertTrue(resolve_blob_path(data_dir, item["id"]).exists())
            with self.assertRaises(AttachmentUnavailable):
                unbind_run_attachments(data_dir, "run_123", active_run_ids={"run_123"}, now=20_000)

            self.assertEqual(unbind_run_attachments(data_dir, "run_123", now=20_000), 1)
            self.assertEqual(get_attachment(data_dir, item["id"])["state"], "orphaned")
            self.assertEqual(garbage_collect(data_dir, now=23_599)["deleted"], 0)
            report = garbage_collect(data_dir, now=23_600)
            self.assertEqual(report["pending_delete"], 1)
            self.assertEqual(report["deleted"], 1)
            self.assertIsNone(get_attachment(data_dir, item["id"]))

    def test_composer_release_uses_grace_and_refuses_retained_attachment(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            unused = create_attachment(data_dir, original_name="unused.txt", content=b"unused", now=100)
            released = release_attachment(data_dir, unused["id"], now=200, grace_seconds=30)
            self.assertEqual(released["state"], "orphaned")
            self.assertEqual(garbage_collect(data_dir, now=229)["deleted"], 0)
            self.assertEqual(garbage_collect(data_dir, now=230)["deleted"], 1)

            retained = create_attachment(data_dir, original_name="kept.txt", content=b"kept", now=300)
            bind_run_attachment(data_dir, retained["id"], "run_kept", now=301)
            with self.assertRaises(AttachmentUnavailable):
                release_attachment(data_dir, retained["id"], now=302)

    def test_expired_staged_attachment_cannot_be_bound_to_a_run(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            item = create_attachment(
                data_dir,
                original_name="context.txt",
                content=b"context",
                now=1_000,
                staged_ttl=10,
            )
            with self.assertRaises(AttachmentUnavailable):
                bind_run_attachment(data_dir, item["id"], "run_late", now=1_011)

    def test_shared_blob_survives_until_final_attachment_is_collected(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            first = create_attachment(data_dir, original_name="one.txt", content=b"same", now=100)
            second = create_attachment(data_dir, original_name="two.txt", content=b"same", now=100)
            shared_path = resolve_blob_path(data_dir, first["id"])
            bind_run_attachment(data_dir, second["id"], "run_kept", now=101)
            garbage_collect(data_dir, now=10_000, orphan_grace=0)
            self.assertIsNone(get_attachment(data_dir, first["id"]))
            self.assertTrue(shared_path.exists())
            self.assertEqual(resolve_blob_path(data_dir, second["id"]), shared_path)

    def test_delete_failure_is_retried_with_backoff(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            item = create_attachment(data_dir, original_name="retry.txt", content=b"retry", now=100)
            with patch.object(Path, "unlink", side_effect=OSError("busy")):
                report = garbage_collect(data_dir, now=10_000, orphan_grace=0)
            self.assertEqual(report["failed"], 1)
            self.assertEqual(get_attachment(data_dir, item["id"])["state"], "deleting")
            self.assertEqual(garbage_collect(data_dir, now=10_029)["deleted"], 0)
            self.assertEqual(garbage_collect(data_dir, now=10_030)["deleted"], 1)

    def test_startup_reconciliation_flags_missing_and_removes_old_orphans(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            item = create_attachment(data_dir, original_name="missing.txt", content=b"missing", now=100)
            resolve_blob_path(data_dir, item["id"]).unlink()

            orphan_dir = data_dir / "private" / "console" / "blobs" / "sha256" / "aa"
            orphan_dir.mkdir(mode=0o700)
            orphan = orphan_dir / ("a" * 64)
            orphan.write_bytes(b"orphan")
            os.utime(orphan, (100, 100))
            upload = data_dir / "runtime" / "uploads" / "crashed.upload"
            upload.write_bytes(b"partial")
            os.utime(upload, (100, 100))

            report = reconcile_startup(data_dir, now=100 + attachments.FILESYSTEM_ORPHAN_MIN_AGE + 1)
            self.assertEqual(report["missing"], 1)
            self.assertEqual(report["filesystem_orphans_deleted"], 1)
            self.assertEqual(report["temporary_deleted"], 1)
            self.assertEqual(get_attachment(data_dir, item["id"])["state"], "missing")
            with self.assertRaises(AttachmentUnavailable):
                resolve_blob_path(data_dir, item["id"])

    def test_startup_reconciliation_releases_refs_missing_from_retained_history(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            kept = create_attachment(data_dir, original_name="kept.txt", content=b"kept", now=100)
            stale = create_attachment(data_dir, original_name="stale.txt", content=b"stale", now=100)
            bind_run_attachment(data_dir, kept["id"], "run_kept", now=101)
            bind_run_attachment(data_dir, stale["id"], "run_crashed", now=101)

            report = reconcile_startup(
                data_dir,
                retained_run_ids={"run_kept"},
                now=200,
            )

            self.assertEqual(report["run_references_released"], 1)
            self.assertEqual(get_attachment(data_dir, kept["id"])["state"], "attached")
            self.assertEqual(get_attachment(data_dir, stale["id"])["state"], "orphaned")

    def test_startup_reconciliation_finalizes_interrupted_deletion_and_upload(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = self.make_data_dir(root)
            item = create_attachment(data_dir, original_name="old.txt", content=b"old", now=100)
            blob_path = resolve_blob_path(data_dir, item["id"])
            connection = connect(data_dir)
            try:
                connection.execute(
                    "UPDATE attachments SET state = 'deleting', delete_after = 100 WHERE id = ?",
                    (item["id"],),
                )
                connection.execute(
                    "INSERT INTO attachments "
                    "(id, original_name, mime_type, kind, state, created_at, updated_at, expires_at) "
                    "VALUES (?, 'crashed.txt', 'text/plain', 'text', 'uploading', 100, 100, 200)",
                    ("attachment_" + "f" * 32,),
                )
            finally:
                connection.close()
            blob_path.unlink()

            report = reconcile_startup(data_dir, now=100 + attachments.UPLOAD_MAX_AGE + 1)
            self.assertEqual(report["deletions_finalized"], 1)
            self.assertEqual(report["uploading_records_deleted"], 1)
            self.assertIsNone(get_attachment(data_dir, item["id"]))

    @unittest.skipIf(os.name == "nt", "POSIX symlink boundary test")
    def test_private_and_blob_symlinks_fail_closed(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            data_dir = self.make_data_dir(root)
            data_dir.mkdir()
            (data_dir / "private").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(Exception):
                create_attachment(data_dir, original_name="safe.txt", content=b"safe")


if __name__ == "__main__":
    unittest.main()
