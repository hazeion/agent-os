from contextlib import ExitStack
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from mentat import native_startup_diagnostics as diagnostics
from mentat.package_data import PUBLIC_DATA_FILES
from scripts.archive_native_windows import INVENTORY_NAME, archive_windows_bundle, write_windows_bundle_inventory
from scripts import archive_native_windows as bundles


class NativeStartupDiagnosticsTests(unittest.TestCase):
    def enabled(self, stream, **overrides):
        stack = ExitStack()
        stack.enter_context(patch.dict(diagnostics.os.environ, {
            "MENTAT_CI_NATIVE_STARTUP_DIAGNOSTICS": "1", "GITHUB_ACTIONS": "true",
            "MENTAT_BRIDGE_TOKEN": "private-token", "MENTAT_DATA_DIR": "/private/owner-data",
            **overrides,
        }, clear=True))
        stack.enter_context(patch.object(diagnostics.sys, "frozen", True, create=True))
        stack.enter_context(patch.object(diagnostics.sys, "platform", "win32"))
        stack.enter_context(patch.object(diagnostics.sys, "stderr", stream))
        stack.enter_context(patch.object(diagnostics.sys, "argv", ["private-owner-executable", "start", "private-draft"]))
        stack.enter_context(patch.object(diagnostics, "_seen", set()))
        stack.enter_context(patch.object(diagnostics, "_started_at", None))
        stack.enter_context(patch.object(diagnostics.time, "time", return_value=1_700_000_000))
        return stack

    def test_only_explicit_frozen_windows_github_ci_flag_emits(self):
        for changes in (
            {"MENTAT_CI_NATIVE_STARTUP_DIAGNOSTICS": ""},
            {"MENTAT_CI_NATIVE_STARTUP_DIAGNOSTICS": "true"},
            {"MENTAT_CI_NATIVE_STARTUP_DIAGNOSTICS": "1\n"},
            {"GITHUB_ACTIONS": ""}, {"GITHUB_ACTIONS": "True"},
        ):
            stream = io.StringIO()
            with self.subTest(changes=changes), self.enabled(stream, **changes), patch.object(
                diagnostics.time, "monotonic"
            ) as clock:
                diagnostics.mark_native_startup_phase("native-entry")
                clock.assert_not_called()
            self.assertEqual(stream.getvalue(), "")
        for name, value in (("frozen", False), ("platform", "darwin")):
            stream = io.StringIO()
            with self.subTest(name=name), self.enabled(stream), patch.object(diagnostics.sys, name, value):
                diagnostics.mark_native_startup_phase("native-entry")
            self.assertEqual(stream.getvalue(), "")

    def test_fixed_phases_are_flushed_bounded_and_do_not_include_private_values(self):
        stream = Mock()
        with self.enabled(stream), patch.object(diagnostics.time, "monotonic", side_effect=[10, 10.25]):
            diagnostics.mark_native_startup_phase("native-entry")
            diagnostics.mark_native_startup_phase("native-entry")
            diagnostics.mark_native_startup_phase("/private/owner-data private-token")
            diagnostics.mark_native_startup_phase("node-gateway-ready")
        output = "".join(call.args[0] for call in stream.write.call_args_list)
        self.assertEqual(output, "Mentat CI startup role=launcher phase=native-entry utc_ms=1700000000000 elapsed_ms=0\nMentat CI startup role=launcher phase=node-gateway-ready utc_ms=1700000000000 elapsed_ms=250\n")
        self.assertEqual(stream.flush.call_count, 2)
        stream = io.StringIO()
        with self.enabled(stream), patch.object(diagnostics.time, "monotonic", return_value=10):
            for _ in range(100):
                for phase in diagnostics._PHASES:
                    diagnostics.mark_native_startup_phase(phase)
        self.assertEqual(len(stream.getvalue().splitlines()), len(diagnostics._PHASES))
        self.assertLess(len(stream.getvalue().encode()), 4096)

    def test_bridge_role_is_fixed_and_gui_or_closed_stream_is_harmless(self):
        stream = io.StringIO()
        with self.enabled(stream), patch.object(diagnostics.sys, "argv", ["private-path", "--mentat-private-bridge", "--port", "49152"]):
            diagnostics.mark_native_startup_phase("native-entry")
        self.assertRegex(stream.getvalue(), r"^Mentat CI startup role=private-bridge phase=native-entry utc_ms=1700000000000 elapsed_ms=0\n$")
        for stream in (None, io.StringIO()):
            if stream is not None:
                stream.close()
            with self.enabled(stream):
                diagnostics.mark_native_startup_phase("native-entry")


class PublicWindowsBundleTests(unittest.TestCase):
    def fixture(self, root):
        dist = root / "dist"
        bundle = dist / "Mentat"
        internal = bundle / "_internal"
        internal.mkdir(parents=True)
        toc = []
        for name in ("mentat.exe", "Mentat Launcher.exe"):
            (bundle / name).write_bytes(b"public native fixture")
            toc.append((name, "unused-public-source", "EXECUTABLE"))
        for surface in ("data", "public"):
            directory = internal / surface
            directory.mkdir()
            for name in PUBLIC_DATA_FILES[f"share/mentat/{surface}"]:
                (directory / Path(name).name).write_bytes(b"public fixture")
                toc.append((surface + "/" + Path(name).name, "unused-public-source", "DATA"))
        web = internal / "web"
        web.mkdir()
        (web / "server.js").write_bytes(b"public standalone fixture")
        toc.append(("web/server.js", "unused-public-source", "DATA"))
        (internal / "mentat").mkdir()
        (internal / "mentat" / "__init__.py").write_bytes(b"public module fixture")
        toc.append(("mentat/__init__.py", "unused-public-source", "DATA"))
        write_windows_bundle_inventory(bundle, toc, "_internal")
        return dist

    def test_archive_contains_only_validated_bundle_and_ignores_adjacent_private_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = self.fixture(root)
            (root / "owner-runtime").mkdir()
            (root / "owner-runtime" / "private-history.json").write_bytes(b"private message")
            (dist / "private-log.txt").write_bytes(b"private token")
            output = archive_windows_bundle(dist)
            with zipfile.ZipFile(output) as archive:
                self.assertTrue(archive.namelist())
                self.assertTrue(all(name.startswith("Mentat/") for name in archive.namelist()))
                self.assertNotIn(b"private", b"".join(archive.read(name) for name in archive.namelist()))
                self.assertIn("Mentat/_internal/web/server.js", archive.namelist())

    def test_private_payloads_and_links_are_refused_before_archive_publication(self):
        for name in ("_internal/data/runtime", "_internal/data/private", "_internal/data/untracked.json", "_internal/web/.env.local", "_internal/mentat.local.toml", "_internal/credentials.json", "_internal/agent-console-runs.json", "_internal/web/private-notes.json", "_internal/mentat/session-cache.txt"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                dist = self.fixture(Path(temporary))
                (dist / "Mentat" / name).write_bytes(b"private token")
                with self.assertRaises(ValueError):
                    archive_windows_bundle(dist)
                self.assertFalse((dist / "mentat-windows-x64-bundle.zip").exists())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = self.fixture(root)
            target = root / "private-owner-content"
            target.write_bytes(b"private token")
            link = dist / "Mentat" / "_internal" / "linked.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("symlink unavailable")
            with self.assertRaises(ValueError):
                archive_windows_bundle(dist)
            self.assertFalse((dist / "mentat-windows-x64-bundle.zip").exists())

    def test_archive_never_replaces_existing_output_or_keeps_partial_zip(self):
        with tempfile.TemporaryDirectory() as temporary:
            dist = self.fixture(Path(temporary))
            output = dist / "mentat-windows-x64-bundle.zip"
            output.write_bytes(b"previous artifact")
            with self.assertRaises(FileExistsError):
                archive_windows_bundle(dist)
            self.assertEqual(output.read_bytes(), b"previous artifact")
            output.unlink()
            with patch.object(zipfile.ZipFile, "open", side_effect=OSError("fixture failure")), self.assertRaises(OSError):
                archive_windows_bundle(dist)
            self.assertFalse(output.exists())

    def test_unknown_file_is_rejected_without_reading_its_private_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            dist = self.fixture(Path(temporary))
            injected = dist / "Mentat/_internal/web/private-notes.json"
            injected.write_bytes(b"owner notes and secret token")
            original_open = Path.open

            def guarded_open(path, *args, **kwargs):
                if path == injected:
                    raise AssertionError("private file read")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", guarded_open), self.assertRaisesRegex(ValueError, "unlisted entry"):
                archive_windows_bundle(dist)
            self.assertFalse((dist / "mentat-windows-x64-bundle.zip").exists())

    def test_missing_inventory_and_changed_or_missing_intended_file_fail_closed(self):
        for change in ("inventory", "content", "missing"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                dist = self.fixture(Path(temporary))
                if change == "inventory":
                    (dist / INVENTORY_NAME).unlink()
                elif change == "content":
                    (dist / "Mentat/_internal/web/server.js").write_bytes(b"private replacement")
                else:
                    (dist / "Mentat/_internal/web/server.js").unlink()
                with self.assertRaises((ValueError, FileNotFoundError)):
                    archive_windows_bundle(dist)
                self.assertFalse((dist / "mentat-windows-x64-bundle.zip").exists())

    def test_inventory_is_derived_from_collect_not_arbitrary_existing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            dist = self.fixture(Path(temporary))
            sealed = json.loads((dist / INVENTORY_NAME).read_text())
            toc = [(name if not name.startswith("_internal/") else name[len("_internal/"):], "unused-source", "EXECUTABLE" if not name.startswith("_internal/") else "DATA") for name in sealed["files"]]
            (dist / INVENTORY_NAME).unlink()
            (dist / "Mentat/_internal/web/private-notes.json").write_bytes(b"private notes")
            with self.assertRaisesRegex(ValueError, "unlisted entry"):
                write_windows_bundle_inventory(dist / "Mentat", toc, "_internal")
            self.assertFalse((dist / INVENTORY_NAME).exists())

    def test_content_change_during_archive_removes_owned_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            dist = self.fixture(Path(temporary))
            original_hash = bundles._hash_file

            def change_after_check(path):
                digest = original_hash(path)
                if path.name == "server.js":
                    path.write_bytes(b"private replacement after validation")
                return digest

            with patch.object(bundles, "_hash_file", side_effect=change_after_check), self.assertRaisesRegex(ValueError, "changed during archive"):
                archive_windows_bundle(dist)
            self.assertFalse((dist / "mentat-windows-x64-bundle.zip").exists())


if __name__ == "__main__":
    unittest.main()
