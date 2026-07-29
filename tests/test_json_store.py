from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import json_store


class JsonStoreTests(unittest.TestCase):
    def test_exact_json_byte_restore_validates_type_and_preserves_bytes(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tasks.json"
            path.write_text("[]\n", encoding="utf-8")
            restored = b'[ { "id" : "format-preserved" } ]\n'

            json_store.write_json_bytes_atomic(
                path,
                restored,
                expected_type=list,
                mode=0o600,
                maximum_bytes=128,
            )

            self.assertEqual(path.read_bytes(), restored)
            with self.assertRaises(ValueError):
                json_store.write_json_bytes_atomic(
                    path,
                    b'{"wrong":true}\n',
                    expected_type=list,
                    maximum_bytes=128,
                )
            with self.assertRaises(ValueError):
                json_store.write_json_bytes_atomic(
                    path,
                    b"not-json",
                    expected_type=list,
                    maximum_bytes=128,
                )
            self.assertEqual(path.read_bytes(), restored)

    def test_atomic_temporary_requests_binary_mode_when_available(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tasks.json"
            path.write_text("[]\n", encoding="utf-8")
            native_binary_flag = getattr(os, "O_BINARY", 0)
            binary_flag = native_binary_flag or (1 << 29)
            synthetic_binary_flag = 0 if native_binary_flag else binary_flag
            real_open = os.open
            temporary_flags: list[int] = []

            def record_open(selected, flags, *args, **kwargs):
                name = Path(os.fspath(selected)).name
                if name.startswith(".tasks.json.") and name.endswith(".tmp"):
                    temporary_flags.append(flags)
                return real_open(
                    selected,
                    flags & ~synthetic_binary_flag,
                    *args,
                    **kwargs,
                )

            with ExitStack() as stack:
                if not native_binary_flag:
                    stack.enter_context(
                        patch.object(os, "O_BINARY", binary_flag, create=True)
                    )
                stack.enter_context(patch.object(os, "open", side_effect=record_open))
                json_store.write_json_atomic(path, [{"id": "binary-exact"}])

            self.assertTrue(temporary_flags)
            self.assertTrue(all(flags & binary_flag for flags in temporary_flags))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [{"id": "binary-exact"}])

    def test_mode_is_established_before_atomic_replace_commit(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tasks.json"
            path.write_text("[]\n", encoding="utf-8")
            if os.name == "posix":
                path.chmod(0o600)
            events: list[tuple[str, str]] = []
            real_chmod = Path.chmod
            real_replace = Path.replace

            def record_chmod(selected, *args, **kwargs):
                events.append(("chmod", selected.name))
                return real_chmod(selected, *args, **kwargs)

            def record_replace(selected, target):
                events.append(("replace", selected.name))
                return real_replace(selected, target)

            with patch.object(Path, "chmod", new=record_chmod), patch.object(
                Path,
                "replace",
                new=record_replace,
            ):
                json_store.write_json_atomic(path, [{"id": "committed-once"}])

            replace_index = next(
                index for index, event in enumerate(events) if event[0] == "replace"
            )
            self.assertFalse(any(event[0] == "chmod" for event in events[replace_index + 1 :]))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [{"id": "committed-once"}])
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_update_rejects_unsafe_linked_input(self):
        if os.name != "posix":
            self.skipTest("POSIX hard-link regression")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outside = root / "outside.json"
            path = root / "tasks.json"
            outside.write_text("[]\n", encoding="utf-8")
            os.link(outside, path)
            with self.assertRaises(OSError):
                json_store.update_json(path, [], lambda current: (current, None))
            self.assertEqual(outside.read_text(encoding="utf-8"), "[]\n")

    def test_update_rejects_invalid_type_and_oversized_serialization(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "tasks.json"
            path.write_text("[]\n", encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                json_store.update_json(
                    path,
                    [],
                    lambda _current: ({"wrong": "shape"}, None),
                    expected_type=list,
                    maximum_bytes=64,
                )
            with self.assertRaises(ValueError):
                json_store.update_json(
                    path,
                    [],
                    lambda _current: (["x" * 128], None),
                    expected_type=list,
                    maximum_bytes=64,
                )
            self.assertEqual(path.read_bytes(), before)

    def test_nested_lock_mode_escalation_fails_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outer = root / "projects.json"
            inner = root / "tasks.json"
            outer.write_text("[]\n", encoding="utf-8")
            inner.write_text("[]\n", encoding="utf-8")

            def outer_mutator(current):
                json_store.update_json(inner, [], lambda value: (value, None))
                return current, None

            with self.assertRaises(OSError):
                json_store.update_json(
                    outer,
                    [],
                    outer_mutator,
                    mutation_lock=False,
                )
            self.assertFalse((root / ".mentat-initialization.lock").exists())

    def test_precommit_failure_cleans_temporary(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "tasks.json"
            path.write_text("[]\n", encoding="utf-8")
            real_validate = json_store._validate_private_descriptor
            calls = 0

            def fail_temporary(descriptor, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("verification failure")
                return real_validate(descriptor, **kwargs)

            with patch.object(
                json_store,
                "_validate_private_descriptor",
                side_effect=fail_temporary,
            ):
                with self.assertRaises(OSError):
                    json_store.update_json(path, [], lambda _current: ([{"id": "new"}], None))
            self.assertEqual(path.read_text(encoding="utf-8"), "[]\n")
            self.assertFalse(any(entry.name.startswith(".tasks.json.") for entry in root.iterdir()))

    def test_substituted_temporary_cannot_return_commit_success(self):
        if os.name == "nt":
            self.skipTest("POSIX held-descriptor substitution regression")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "tasks.json"
            path.write_text("[]\n", encoding="utf-8")
            real_replace = os.replace

            def substitute_before_replace(source, destination, **kwargs):
                source_path = root / source if isinstance(source, str) else Path(source)
                source_path.unlink()
                source_path.write_text('{"wrong":true}\n', encoding="utf-8")
                return real_replace(source, destination, **kwargs)

            with patch.object(json_store.os, "replace", side_effect=substitute_before_replace):
                with self.assertRaises(json_store.JsonCommitVerificationError):
                    json_store.update_json(path, [], lambda _current: ([{"id": "approved"}], None))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"wrong": True})
            self.assertFalse(any(entry.name.startswith(".tasks.json.") for entry in root.iterdir()))

    def test_descriptor_relative_committed_reopen_is_nonblocking(self):
        if os.name != "posix":
            self.skipTest("descriptor-relative POSIX reopen regression")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "tasks.json"
            path.write_text("[]\n", encoding="utf-8")
            path.chmod(0o600)
            real_replace = os.replace
            errors: list[Exception] = []

            def substitute_with_fifo(*args, **kwargs):
                result = real_replace(*args, **kwargs)
                path.unlink()
                os.mkfifo(path, mode=0o600)
                return result

            def mutate() -> None:
                try:
                    json_store.update_json(
                        path,
                        [],
                        lambda _current: ([{"id": "nonblocking"}], None),
                        required_mode=0o600,
                    )
                except Exception as exc:
                    errors.append(exc)

            with patch.object(json_store.os, "replace", side_effect=substitute_with_fifo):
                worker = __import__("threading").Thread(target=mutate, daemon=True)
                worker.start()
                worker.join(1)
                blocked = worker.is_alive()
                if blocked:
                    writer = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
                    os.close(writer)
                    worker.join(1)
            self.assertFalse(blocked, "committed verification blocked opening a FIFO")
            self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
