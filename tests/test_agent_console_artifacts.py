from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import unittest

import agent_console_artifacts as artifacts


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + (b"safe-image" * 4)


class RecordingStore:
    def __init__(self):
        self.calls: list[tuple[Path, bytes, dict]] = []

    def __call__(self, path: Path, **metadata):
        source = Path(path)
        self.calls.append((source, source.read_bytes(), metadata))
        return {"id": f"att_{len(self.calls)}", "storage_path": "/private/must-not-leak"}


class AgentConsoleArtifactTests(unittest.TestCase):
    def test_low_level_snapshot_copies_request_binary_mode_when_available(self):
        for copier in (artifacts._copy_private_regular_file, artifacts._copy_validated_snapshot):
            source = inspect.getsource(copier)
            self.assertIn('getattr(os, "O_BINARY", 0)', source)
            self.assertIn("os.open", source)

    def test_export_directory_is_private_and_rejects_invalid_run_ids(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            export = artifacts.prepare_export_directory(root, "run_abc123")
            self.assertEqual(
                export,
                (root / "runtime" / "agent-console-exports" / "run_abc123").resolve(),
            )
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(export.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(export.parent.stat().st_mode), 0o700)
            with self.assertRaises(artifacts.ArtifactValidationError) as invalid:
                artifacts.prepare_export_directory(root, "../../escape")
            self.assertEqual(invalid.exception.code, "invalid_run_id")

    def test_execution_context_keeps_prompt_out_and_allows_owned_files_only(self):
        self.assertNotIn("prompt", inspect.signature(artifacts.build_execution_context).parameters)
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            owned = root / "runtime" / "blobs"
            owned.mkdir(parents=True)
            input_file = owned / "sha256.txt"
            input_file.write_text("review me", encoding="utf-8")

            context = artifacts.build_execution_context(
                root,
                "run_context",
                [{"id": "att_123", "kind": "code", "path": input_file}],
            )
            manifest = json.loads(context["instruction"].splitlines()[-1])

            self.assertEqual(context["attachments"], manifest["attachments"])
            self.assertEqual(manifest["attachments"][0]["path"], str(input_file.resolve()))
            self.assertTrue(Path(context["export_directory"]).is_dir())
            self.assertIn("untrusted data", context["instruction"])

            outside = Path(tmpdir) / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            with self.assertRaises(artifacts.ArtifactValidationError) as failure:
                artifacts.build_execution_context(
                    root,
                    "run_context",
                    [{"id": "att_outside", "kind": "text", "path": outside}],
                )
            self.assertEqual(failure.exception.code, "invalid_attachment_path")

    def test_execution_context_rejects_symlinked_owned_attachment(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            blobs = root / "runtime" / "blobs"
            blobs.mkdir(parents=True)
            target = blobs / "target.txt"
            target.write_text("content", encoding="utf-8")
            link = blobs / "link.txt"
            link.symlink_to(target)
            with self.assertRaises(artifacts.ArtifactValidationError):
                artifacts.build_execution_context(
                    root,
                    "run_links",
                    [{"id": "att_link", "kind": "text", "path": link}],
                )

    def test_image_execution_context_uses_private_extension_bearing_snapshot(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            blobs = root / "runtime" / "blobs"
            blobs.mkdir(parents=True)
            source = blobs / "extensionless-image"
            source.write_bytes(PNG_BYTES)

            context = artifacts.build_execution_context(
                root,
                "run_image",
                [{"id": "att_image", "kind": "image", "mime_type": "image/png", "path": source}],
            )
            image_path = context["_image_path"]

            self.assertEqual(image_path.suffix, ".png")
            self.assertEqual(image_path.read_bytes(), PNG_BYTES)
            self.assertEqual(Path(context["attachments"][0]["path"]), image_path)
            self.assertNotEqual(image_path, source)
            self.assertEqual(artifacts.cleanup_run_input_directory(root, "run_image"), 1)
            self.assertFalse(image_path.exists())

    def test_artifact_discovery_registers_only_owned_valid_files(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            export = artifacts.prepare_export_directory(root, "run_outputs")
            (export / "diagram.png").write_bytes(PNG_BYTES)
            (export / "answer.py").write_text("print('safe')\n", encoding="utf-8")
            (export / "fake.png").write_text("not an image", encoding="utf-8")
            (export / "bundle.zip").write_bytes(b"PK fake archive")
            (export / ".env").write_text("TOKEN=nope", encoding="utf-8")
            outside = Path(tmpdir) / "mentioned-in-response.txt"
            outside.write_text("must not be discovered", encoding="utf-8")
            if hasattr(os, "symlink"):
                (export / "outside-link.txt").symlink_to(outside)
            store = RecordingStore()

            found = artifacts.discover_run_artifacts(root, "run_outputs", store)

            self.assertEqual([item["name"] for item in found], ["answer.py", "diagram.png"])
            self.assertEqual({item["kind"] for item in found}, {"code", "image"})
            self.assertNotIn(str(export), json.dumps(found))
            self.assertNotIn("must-not-leak", json.dumps(found))
            self.assertEqual([call[2]["direction"] for call in store.calls], ["output", "output"])
            self.assertNotIn(outside, [call[0] for call in store.calls])

    def test_artifact_discovery_is_bounded_and_requires_safe_store_id(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            export = artifacts.prepare_export_directory(root, "run_bounded")
            for index in range(5):
                (export / f"output-{index}.txt").write_text(str(index), encoding="utf-8")
            store = RecordingStore()
            found = artifacts.discover_run_artifacts(root, "run_bounded", store, max_files=2)
            self.assertEqual(len(found), 2)

            with self.assertRaises(artifacts.ArtifactValidationError) as unsafe:
                artifacts.discover_run_artifacts(
                    root,
                    "run_bounded",
                    lambda *_args, **_kwargs: {"id": "../../private"},
                    max_files=1,
                )
            self.assertEqual(unsafe.exception.code, "storage_failed")

    def test_export_cleanup_is_explicit_and_never_follows_symlinks(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "data"
            export = artifacts.prepare_export_directory(root, "run_cleanup")
            nested = export / "nested"
            nested.mkdir()
            (nested / "answer.txt").write_text("answer", encoding="utf-8")
            outside = Path(tmpdir) / "outside.txt"
            outside.write_text("preserve", encoding="utf-8")
            if hasattr(os, "symlink"):
                (export / "outside-link.txt").symlink_to(outside)

            removed = artifacts.cleanup_run_export_directory(root, "run_cleanup")

            self.assertGreaterEqual(removed, 1)
            self.assertFalse(export.exists())
            self.assertEqual(outside.read_text(encoding="utf-8"), "preserve")

    def test_workspace_search_returns_relative_paths_and_excludes_private_content(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "workspace"
            (root / "src").mkdir(parents=True)
            (root / "src" / "main.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "README.md").write_text("hello", encoding="utf-8")
            (root / ".env").write_text("TOKEN=private", encoding="utf-8")
            (root / "api-token.txt").write_text("private", encoding="utf-8")
            (root / "archive.zip").write_bytes(b"PK")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("private", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "library.js").write_text("private", encoding="utf-8")
            (root / "data" / "runtime").mkdir(parents=True)
            (root / "data" / "runtime" / "history.json").write_text("{}", encoding="utf-8")
            executable = root / "src" / "run.sh"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)

            found = artifacts.search_workspace_files("", roots=[root])
            paths = [item["path"] for item in found]

            self.assertEqual(paths, ["README.md", "src/main.py"])
            self.assertTrue(all(not Path(item["path"]).is_absolute() for item in found))
            self.assertNotIn(str(root), json.dumps(found))
            self.assertEqual(
                artifacts.search_workspace_files("main", roots=[root], max_results=1)[0]["path"],
                "src/main.py",
            )

    def test_workspace_search_skips_symlinks_and_labels_explicit_roots(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with TemporaryDirectory() as tmpdir:
            first = Path(tmpdir) / "first"
            second = Path(tmpdir) / "second"
            outside = Path(tmpdir) / "outside.txt"
            first.mkdir()
            second.mkdir()
            outside.write_text("outside", encoding="utf-8")
            (first / "one.txt").write_text("one", encoding="utf-8")
            (second / "two.txt").write_text("two", encoding="utf-8")
            (first / "link.txt").symlink_to(outside)

            found = artifacts.search_workspace_files("", roots=[first, second])

            self.assertEqual(
                [(item["root_id"], item["path"]) for item in found],
                [("workspace", "one.txt"), ("workspace_2", "two.txt")],
            )

    def test_workspace_selection_uses_private_snapshot_and_blocks_traversal(self):
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            original = workspace / "review.py"
            original.write_bytes(b"print('snapshot')\n")
            data_dir = Path(tmpdir) / "data"
            store = RecordingStore()

            selected = artifacts.snapshot_workspace_file(
                data_dir,
                "workspace",
                "review.py",
                store,
                roots=[workspace],
            )

            callback_path, copied, metadata = store.calls[0]
            self.assertNotEqual(callback_path, original)
            self.assertFalse(callback_path.exists())
            self.assertEqual(copied, b"print('snapshot')\n")
            self.assertEqual(metadata["source"], "workspace")
            self.assertEqual(selected["name"], "review.py")
            self.assertNotIn(str(workspace), json.dumps(selected))

            with self.assertRaises(artifacts.ArtifactValidationError) as traversal:
                artifacts.snapshot_workspace_file(
                    data_dir,
                    "workspace",
                    "../outside.txt",
                    store,
                    roots=[workspace],
                )
            self.assertEqual(traversal.exception.code, "invalid_workspace_path")

    def test_workspace_selection_rejects_symlink_and_secret_file(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            outside = Path(tmpdir) / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            (workspace / "link.txt").symlink_to(outside)
            (workspace / ".env").write_text("TOKEN=private", encoding="utf-8")
            store = RecordingStore()
            for relative in ("link.txt", ".env"):
                with self.assertRaises(artifacts.ArtifactValidationError):
                    artifacts.snapshot_workspace_file(
                        Path(tmpdir) / "data",
                        "workspace",
                        relative,
                        store,
                        roots=[workspace],
                    )
            self.assertEqual(store.calls, [])


if __name__ == "__main__":
    unittest.main()
