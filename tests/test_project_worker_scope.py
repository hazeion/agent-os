from __future__ import annotations

import os
import errno
from pathlib import Path
import signal
import subprocess
import sys
import threading
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import MagicMock, patch

from mentat import project_worker_scope as scopes


class WorkerScopeContractTests(unittest.TestCase):
    def test_limits_refuse_unbounded_noninteger_or_excessive_values(self):
        for field, values in {
            "memory_bytes": [0, -1, True, 512 * 1024 * 1024 + 1],
            "processes": [0, True, 33], "cpu_percent": [0, 101, 1.5],
            "wall_seconds": [0, 3601, float("inf")],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(scopes.WorkerScopeError):
                    scopes.WorkerScopeLimits(**{field: value})

    def test_unlimited_or_ineffective_kernel_limits_fail_before_handoff(self):
        baseline = {"memory.max": "536870912", "pids.max": "32", "cpu.max": "100000 100000"}
        invalid = [("memory.max", "max"), ("memory.max", "536870913"),
                   ("pids.max", "max"), ("pids.max", "33"),
                   ("cpu.max", "max 100000"), ("cpu.max", "100001 100000"),
                   ("cpu.max", "1 0"), ("cpu.max", "1 2 3")]
        for field, value in invalid:
            values = {**baseline, field: value}
            with self.subTest(field=field, value=value), patch.object(
                scopes, "_read_control", side_effect=lambda _fd, name: values[name]
            ), self.assertRaises(scopes.WorkerScopeError):
                scopes._effective_limits(99, scopes.WorkerScopeLimits())
        with patch.object(scopes, "_read_control", side_effect=lambda _fd, name: baseline[name]):
            self.assertEqual(scopes._effective_limits(99, scopes.WorkerScopeLimits()).cpu_quota, 100000)

    def test_unsupported_platform_fails_before_any_subprocess_or_file_operation(self):
        with patch.object(scopes, "IS_LINUX", False), patch.object(scopes.subprocess, "run") as run, patch.object(
            scopes.os, "open"
        ) as opened, self.assertRaises(scopes.WorkerScopeError):
            scopes.LinuxWorkerScope()
        run.assert_not_called()
        opened.assert_not_called()

    def test_relative_or_parent_path_is_rejected_before_open(self):
        with patch.object(scopes.os, "open") as opened:
            for path in (Path("relative"), Path("/sys/fs/cgroup/../other")):
                with self.assertRaises(scopes.WorkerScopeError):
                    scopes._open_directory(path)
        opened.assert_not_called()


@unittest.skipUnless(scopes.IS_LINUX, "Descriptor path checks require Linux")
class LinuxScopeDescriptorTests(unittest.TestCase):
    def test_removed_control_node_requires_held_cgroup_and_original_inactive_unit(self):
        scope = scopes.LinuxWorkerScope()
        scope._descriptor, scope._invocation = 9999, "f" * 32
        inactive = {"ActiveState": "inactive", "ControlGroup": "", "InvocationID": "f" * 32, "LoadState": "loaded"}
        try:
            for error in (errno.ENOENT, errno.ENODEV):
                with patch.object(scopes, "_read_control", side_effect=OSError(error, "controlled")), patch.object(
                    scopes, "_require_cgroup2"
                ) as filesystem, patch.object(scope, "_state", return_value=inactive):
                    self.assertTrue(scope._empty())
                    filesystem.assert_called_once_with(9999)
                for changed in ({**inactive, "ActiveState": "active"}, {**inactive, "InvocationID": "a" * 32},
                                {**inactive, "ControlGroup": scope._relative}):
                    with patch.object(scopes, "_read_control", side_effect=OSError(error, "controlled")), patch.object(
                        scopes, "_require_cgroup2"
                    ), patch.object(scope, "_state", return_value=changed):
                        self.assertFalse(scope._empty())
            with patch.object(scopes, "_read_control", side_effect=OSError(errno.EIO, "controlled")), patch.object(
                scopes, "_require_cgroup2"
            ) as filesystem, self.assertRaises(OSError):
                scope._empty()
            filesystem.assert_not_called()
        finally:
            scope._descriptor = None  # Fake descriptor is never an actual close target.

    def test_symlink_parent_cannot_replace_the_pinned_kernel_path(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            real = root / "real"
            real.mkdir()
            (root / "redirect").symlink_to(real, target_is_directory=True)
            with self.assertRaises(OSError):
                scopes._open_directory(root / "redirect")

    def test_ordinary_directory_cannot_masquerade_as_kernel_cgroup(self):
        with TemporaryDirectory() as temporary:
            descriptor = scopes._open_directory(Path(temporary))
            try:
                with self.assertRaisesRegex(scopes.WorkerScopeError, "filesystem"):
                    scopes._require_cgroup2(descriptor)
            finally:
                os.close(descriptor)

@unittest.skipUnless(scopes.IS_LINUX, "Project scope integration requires Linux")
class LinuxWorkerScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not callable(getattr(os, "pidfd_open", None)) or not callable(getattr(signal, "pidfd_send_signal", None)):
            raise unittest.SkipTest("PID-fenced signaling unavailable")
        if os.getuid() <= 0 or not Path(f"/run/user/{os.getuid()}/bus").exists():
            raise unittest.SkipTest("Unprivileged systemd user manager unavailable")
        try:
            scope = scopes.LinuxWorkerScope()
            state = scope._state()
        except (OSError, scopes.WorkerScopeError, subprocess.SubprocessError):
            raise unittest.SkipTest("Systemd user scope operations unavailable")
        if state["LoadState"] != "not-found":
            raise AssertionError("Generated scope unexpectedly already exists")

    def _start(self, *, wall=10):
        scope = scopes.LinuxWorkerScope(scopes.WorkerScopeLimits(wall_seconds=wall))
        try:
            effective = scope.start_inert()
            scope.qualification_detach()
        except BaseException:
            scope.close_verified()
            raise
        process = scope._process
        self.addCleanup(self._finish, scope, process)
        return scope, process, effective

    @staticmethod
    def _finish(scope, process):
        try:
            scope.close_verified()
        finally:
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    stream.close()

    def test_exact_kernel_scope_stop_removes_detached_descendant(self):
        scope, process, effective = self._start()
        self.assertEqual(effective.processes, 32)
        self.assertEqual(effective.memory_bytes, 512 * 1024 * 1024)
        self.assertTrue(scope.stop_local_and_verify())
        self.assertIsNotNone(process.returncode)
        self.assertTrue(scope._empty())

    def test_watchdog_enforces_local_deadline_independently_of_stock_agent(self):
        scope, process, _ = self._start(wall=10)
        # Stock/systemd/bootstrap deadlines remain ten seconds away. Force the
        # actual parent timer earlier and require its pinned cgroup kill.
        scope._timer.cancel()
        scope._timer.join(timeout=1)
        self.assertFalse(scope._timer.is_alive())
        scope._timer = threading.Timer(.05, scope._deadline_stop)
        with patch.object(scopes.os, "write", wraps=scopes.os.write) as wrote:
            scope._timer.start()
            scope._timer.join(timeout=6)
            self.assertFalse(scope._timer.is_alive())
            self.assertTrue(any(call.args[1] == b"1\n" for call in wrote.call_args_list))
        self.assertTrue(scope.deadline_hit)
        self.assertTrue(scope.deadline_cleanup_verified)
        self.assertIsNotNone(process.returncode)
        self.assertTrue(scope._empty())

    def test_exception_cleanup_preserves_only_owned_scope_and_handles(self):
        scope, process, _ = self._start()
        with self.assertRaisesRegex(ValueError, "controlled"):
            try:
                raise ValueError("controlled")
            finally:
                self.assertTrue(scope.stop_local_and_verify())
        self.assertIsNotNone(process.returncode)
        self.assertTrue(scope._empty())

    def test_scope_configuration_and_environment_cannot_be_rewritten(self):
        scope, _process, _ = self._start()
        with self.assertRaises(AttributeError):
            scope.unit = "other.scope"
        with self.assertRaises(AttributeError):
            scope.limits = scopes.WorkerScopeLimits(wall_seconds=30)
        with self.assertRaises(TypeError):
            scope.environment["PATH"] = "/untrusted"

    def test_unpinned_named_unit_is_never_a_signal_target(self):
        scope = scopes.LinuxWorkerScope()
        with patch.object(scope, "_state", return_value={"ActiveState": "active", "ControlGroup": scope._relative,
                                                         "InvocationID": "f" * 32, "LoadState": "loaded"}), patch.object(
            scopes.signal, "pidfd_send_signal"
        ) as signal_call, patch.object(scopes.os, "open") as opened:
            self.assertFalse(scope.stop_local_and_verify())
        signal_call.assert_not_called()
        opened.assert_not_called()

    def test_startup_verification_failures_deliver_no_capability_and_exit_on_eof(self):
        cases = [(scopes.os, "pidfd_open", PermissionError("controlled")),
                 (scopes, "_effective_limits", scopes.WorkerScopeError("controlled")),
                 (scopes, "_require_cgroup2", scopes.WorkerScopeError("controlled")),
                 (scopes.threading.Timer, "start", RuntimeError("controlled"))]
        for owner, method, failure in cases:
            with self.subTest(method=method):
                scope = scopes.LinuxWorkerScope(scopes.WorkerScopeLimits(wall_seconds=5))
                try:
                    with patch.object(owner, method, side_effect=failure), self.assertRaises(
                        (scopes.WorkerScopeError, PermissionError, RuntimeError)
                    ):
                        scope.start_inert()
                    self.assertIsNone(scope._control)
                    self.assertIsNotNone(scope._process.poll())
                    self.assertTrue(scope.stop_local_and_verify())
                finally:
                    scope.close_verified()

    def test_deadline_expired_between_verification_and_command_refuses_handoff(self):
        scope, _process, _ = self._start()
        original = scope._state
        def expiry_after_readback():
            value = original()
            scope._deadline = time.monotonic() - 1
            return value
        control = MagicMock(wraps=scope._control)
        with patch.object(scope, "_state", side_effect=expiry_after_readback), patch.object(
            scope, "_control", control
        ), self.assertRaisesRegex(scopes.WorkerScopeError, "deadline"):
            scope.qualification_detach()
        control.sendall.assert_not_called()


if __name__ == "__main__":
    unittest.main()
