from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import platform
from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from mentat import project_runtime_libraries as libraries
from mentat import project_worker_namespace as namespaces
from mentat.project_worker_scope import WorkerScopeError
from tests import test_project_runtime_elf as elf_tests


ROOTS = (PurePosixPath("/opt/mentat-source"), PurePosixPath("/opt/mentat-venv"), PurePosixPath("/opt/mentat-python"))


class RuntimeLibraryContractTests(unittest.TestCase):
    def test_unreachable_build_paths_are_exact_negative_mount_invariants(self):
        self.assertEqual(libraries.validate_unreachable_paths(["/tools/deps/lib"], ROOTS), ("/tools/deps/lib",))
        for values in (["/tmp/lib"], ["/exports"], ["/inputs/lib"], ["/worker"], ["/dev/lib"],
                       ["/proc"], ["/run/lib"], ["/sys/lib"], ["/opt"], ["/opt/mentat-python/lib"],
                       ["/usr/lib"], ["/usr"], ["relative"], ["/tools/../deps"], ["/tools/$LIB"],
                       ["/tools/deps/lib", "/tools/deps/lib"], [None], [[]]):
            with self.subTest(values=values), self.assertRaises(WorkerScopeError):
                libraries.validate_unreachable_paths(values, ROOTS)

    def test_double_slash_aliases_cannot_bypass_negative_mount_checks(self):
        for value in ("//tmp/lib", "//home/mentat/lib", "//usr/lib", "//proc", "//opt/mentat-python/lib", "//tools/deps/lib"):
            with self.subTest(value=value), self.assertRaises(WorkerScopeError):
                libraries.validate_unreachable_paths([value], ROOTS)
            with self.assertRaises(WorkerScopeError):
                libraries._normalized(value)

    def test_sealed_library_mode_cannot_fall_back_without_an_image(self):
        with patch.object(namespaces, "IS_LINUX", True), patch.object(namespaces, "_open_directory") as opened:
            with self.assertRaises(WorkerScopeError):
                namespaces.PreparedNamespace(object(), b"query", "0"*64, "test", sealed_libraries=True)
            opened.assert_not_called()

    def test_nonlinux_projection_refuses_before_opening(self):
        with (patch.object(libraries, "IS_LINUX", False), patch.object(libraries, "_open_directory") as opened,
              self.assertRaises(WorkerScopeError)):
            libraries.project_system_libraries(Path("unused"), ROOTS)
        opened.assert_not_called()


@unittest.skipUnless(libraries.IS_LINUX and platform.machine() == "x86_64", "x86-64 public system-library projection")
class LinuxRuntimeLibraryTests(unittest.TestCase):
    def stage(self, temporary, *, rpath="$ORIGIN/../lib", needed=("libc.so.6",)):
        root = Path(temporary)
        for name in ("source", "venv", "python"):
            (root/name).mkdir()
        (root/"python/bin").mkdir()
        (root/"python/bin/python").write_bytes(elf_tests.fixture(rpath=rpath, needed=needed))
        return root

    def test_static_projection_copies_only_selected_root_owned_library_bytes(self):
        with TemporaryDirectory(prefix="mentat-libraries-test-") as temporary:
            stage = self.stage(temporary)
            result = libraries.project_system_libraries(stage, ROOTS)
            self.assertLess(result["system_bytes"], libraries.MAX_SYSTEM_BYTES)
            self.assertTrue(any("libc.so.6" in name for name, _ in result["members"]))
            self.assertTrue(any("ld-linux-x86-64.so.2" in name for name, _ in result["members"]))
            self.assertEqual(json.loads((stage/"runtime-libraries.json").read_text()), result)
            self.assertLess(len(result["members"]), libraries.MAX_SYSTEM_FILES)
            self.assertFalse((stage/"system_lib/modules").exists())

    def test_unmounted_build_path_is_recorded_but_never_copied(self):
        with TemporaryDirectory(prefix="mentat-unreachable-test-") as temporary:
            stage = self.stage(temporary, rpath="/tools/deps/lib")
            result = libraries.project_system_libraries(stage, ROOTS)
            self.assertEqual(result["unreachable_paths"], ["/tools/deps/lib"])
            self.assertFalse((stage/"tools").exists())

    def test_unsafe_rpath_and_unresolved_dependency_refuse_no_fallback(self):
        for rpath, needed in (("/tmp/lib", ("libc.so.6",)), ("$ORIGIN/../../..", ("libc.so.6",)),
                              ("$ORIGIN/../lib", ("libmentat-nonexistent-qualification.so",))):
            with self.subTest(rpath=rpath), TemporaryDirectory(prefix="mentat-library-refusal-") as temporary:
                stage = self.stage(temporary, rpath=rpath, needed=needed)
                with self.assertRaises(WorkerScopeError):
                    libraries.project_system_libraries(stage, ROOTS)
                self.assertFalse((stage/"runtime-libraries.json").exists())

    def test_recursive_selected_system_library_paths_are_also_audited(self):
        original = libraries.inspect_elf
        for path, valid in (("/tmp/lib", False), ("/tools/deps/lib", True)):
            with self.subTest(path=path), TemporaryDirectory(prefix="mentat-recursive-library-") as temporary:
                stage = self.stage(temporary)
                def declared(data):
                    value = original(data)
                    return replace(value, rpath=(path,)) if len(data) > 1024 else value
                with patch.object(libraries, "inspect_elf", side_effect=declared):
                    if valid:
                        self.assertEqual(libraries.project_system_libraries(stage, ROOTS)["unreachable_paths"], [path])
                    else:
                        with self.assertRaises(WorkerScopeError):
                            libraries.project_system_libraries(stage, ROOTS)
                        self.assertFalse((stage/"runtime-libraries.json").exists())


if __name__ == "__main__":
    unittest.main()
