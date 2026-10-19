from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from mentat import project_runtime_image as images
from mentat.project_worker_scope import WorkerScopeError


class RuntimeImageContractTests(unittest.TestCase):
    def test_mount_bootstrap_refuses_windows_before_any_kernel_or_exec_call(self):
        from mentat import project_runtime_mount_bootstrap as bootstrap
        with (patch.object(bootstrap.sys, "platform", "win32"), patch.object(bootstrap.ctypes, "CDLL") as library,
              patch.object(bootstrap.os, "execve") as executed):
            self.assertEqual(bootstrap.main(), 1)
        library.assert_not_called()
        executed.assert_not_called()

    def test_unsupported_platform_refuses_before_files_or_processes(self):
        with patch.object(images, "IS_LINUX", False), patch.object(images.os, "stat") as inspected, patch.object(
            images.subprocess, "Popen"
        ) as launched, self.assertRaises(WorkerScopeError):
            images.ImmutableRuntimeImage(Path("not-used"), "0" * 64)
        inspected.assert_not_called()
        launched.assert_not_called()


@unittest.skipUnless(images.IS_LINUX, "Linux sealed image/FUSE checks")
class LinuxRuntimeImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getuid() <= 0 or not all(Path(value).exists() for value in
            ("/usr/bin/mksquashfs", "/usr/bin/squashfuse", "/usr/bin/fusermount3", "/dev/fuse")):
            raise unittest.SkipTest("Unprivileged read-only image tools unavailable")

    def setUp(self):
        self.temporary = TemporaryDirectory(prefix="mentat-image-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        stage = self.root / "stage"
        for name in ("source", "venv", "python"):
            (stage / name).mkdir(parents=True)
            (stage / name / "sentinel").write_bytes(b"frozen bytes")
        self.path = self.root / "runtime.squashfs"
        result = subprocess.run(["/usr/bin/mksquashfs", str(stage), str(self.path), "-noappend",
                                 "-processors", "1", "-no-progress", "-quiet", "-no-xattrs"],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=10, check=False)
        self.assertEqual(result.returncode, 0)
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def _lease(self):
        lease = images.ImmutableRuntimeImage(self.path, self.digest)
        self.addCleanup(lease.close)
        return lease

    def test_sealed_image_and_actual_readonly_mount_deny_writes(self):
        lease = self._lease()
        descriptors = lease.acquire_roots()
        try:
            for descriptor in descriptors:
                child = os.open("sentinel", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptor)
                try:
                    self.assertEqual(os.read(child, 100), b"frozen bytes")
                finally:
                    os.close(child)
                with self.assertRaises(OSError) as refusal:
                    os.open("new-file", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=descriptor)
                self.assertEqual(refusal.exception.errno, errno.EROFS)
            with self.assertRaises(OSError):
                os.write(lease._image, b"changed")
            with self.assertRaises(OSError):
                os.ftruncate(lease._image, 0)
            lease.verify()
        finally:
            for descriptor in descriptors:
                os.close(descriptor)
            lease.release_roots()
        lease.close()
        self.assertFalse(lease._directory.exists())

    def test_mutating_original_file_does_not_change_sealed_runtime(self):
        lease = self._lease()
        self.path.write_bytes(b"source replaced after sealing")
        lease.verify()
        descriptors = lease.acquire_roots()
        try:
            child = os.open("sentinel", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptors[0])
            with os.fdopen(child, "rb") as stream:
                self.assertEqual(stream.read(), b"frozen bytes")
        finally:
            for descriptor in descriptors:
                os.close(descriptor)
            lease.release_roots()

    def test_busy_reference_refuses_cleanup_and_preserves_daemon(self):
        lease = self._lease()
        descriptors = lease.acquire_roots()
        try:
            with self.assertRaisesRegex(WorkerScopeError, "busy"):
                lease.close()
            lease.verify()
            self.assertIsNone(lease._process.poll())
        finally:
            for descriptor in descriptors:
                os.close(descriptor)
            lease.release_roots()

    def test_worker_reference_survives_early_prepared_close_until_verified_stop(self):
        from mentat import project_worker_namespace as namespaces
        from mentat import project_worker_scope as scopes
        from tests import test_project_worker_namespace as namespace_tests
        # Tiny fake runtime still exercises the real scope and image handoff.
        stage = self.root / "stage"
        (stage / "source/hermes_cli").mkdir()
        (stage / "source/hermes_cli/main.py").write_text("# fixed synthetic entry\n")
        (stage / "venv/pyvenv.cfg").write_text("home = /missing\n")
        alias = namespaces.RuntimeRoots(Path("/opt/mentat-source"), Path("/opt/mentat-venv"), Path("/opt/mentat-python"))
        replacement = self.root / "worker.squashfs"
        subprocess.run(["/usr/bin/mksquashfs", str(stage), str(replacement), "-noappend", "-processors", "1", "-quiet",
                        "-no-progress", "-no-xattrs"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=10)
        lease = images.ImmutableRuntimeImage(replacement, hashlib.sha256(replacement.read_bytes()).hexdigest())
        self.addCleanup(lease.close)
        scope = scopes.LinuxWorkerScope(scopes.WorkerScopeLimits(wall_seconds=10))
        prepared = namespaces.PreparedNamespace(alias, b"query", hashlib.sha256(b"query").hexdigest(), "test", runtime_image=lease)
        try:
            scope.start_inert()
            # Exercise the same ownership transfer independently of a runnable
            # interpreter: namespace launch and its byte qualification differ.
            lease.retain_worker(scope)
            scope._runtime_image = lease
            prepared.close()
            with self.assertRaisesRegex(WorkerScopeError, "busy"):
                lease.close()
            lease.verify()
            scope.close_verified()
            lease.close()
            self.assertFalse(lease._directory.exists())
        finally:
            scope.close_verified() if not scope._closed else None
            prepared.close()

    def test_daemon_loss_refuses_use_and_exact_dead_mount_can_be_cleaned(self):
        lease = self._lease()
        signal.pidfd_send_signal(lease._pidfd, signal.SIGKILL)
        lease._process.wait(timeout=3)
        with self.assertRaisesRegex(WorkerScopeError, "daemon"):
            lease.verify()
        lease.close()
        self.assertFalse(lease._directory.exists())

    def test_stopped_owned_daemon_cannot_block_parent_verification(self):
        lease = self._lease()
        signal.pidfd_send_signal(lease._pidfd, signal.SIGSTOP)
        started = time.monotonic()
        try:
            with self.assertRaises(WorkerScopeError):
                lease.verify()
            self.assertLess(time.monotonic() - started, 3)
        finally:
            signal.pidfd_send_signal(lease._pidfd, signal.SIGCONT)
        lease.verify()
        lease.close()
        self.assertFalse(lease._directory.exists())

    def test_startup_failure_after_mount_before_fuse_probe_has_exact_cleanup(self):
        owned = []
        original = images.ImmutableRuntimeImage._probe
        def refused(lease, mode):
            owned.append(lease)
            raise WorkerScopeError("controlled FUSE identification failure")
        with patch.object(images.ImmutableRuntimeImage, "_probe", side_effect=refused, autospec=True), self.assertRaises(WorkerScopeError):
            images.ImmutableRuntimeImage(self.path, self.digest)
        self.assertTrue(owned)
        self.assertTrue(owned[0]._closed)
        self.assertFalse(owned[0]._directory.exists())
        self.assertIsNotNone(owned[0]._process.poll())

    def test_owned_decoder_has_finite_declared_resource_limits(self):
        lease = self._lease()
        with open("/proc/" + str(lease._process.pid) + "/limits") as stream:
            limits = stream.read(16384)
        for name, expected in (("Max address space", "805306368"), ("Max cpu time", "120"),
                               ("Max open files", "64"), ("Max core file size", "0")):
            line = next(line for line in limits.splitlines() if line.startswith(name))
            self.assertEqual(line.split()[len(name.split())], expected)

    def test_replaced_probe_mount_identity_is_never_adopted_at_startup(self):
        original = images.ImmutableRuntimeImage._probe
        owned = []
        def replaced(lease, mode):
            owned.append(lease)
            descriptors, identity = original(lease, mode)
            return descriptors, [identity[0] + 100000, *identity[1:]]
        with patch.object(images.ImmutableRuntimeImage, "_probe", side_effect=replaced, autospec=True), self.assertRaisesRegex(
            WorkerScopeError, "replaced"
        ):
            images.ImmutableRuntimeImage(self.path, self.digest)
        self.assertTrue(owned[0]._closed)
        self.assertFalse(owned[0]._directory.exists())

    def test_unresolved_probe_owner_prevents_new_probe_process(self):
        lease = self._lease()
        pending = MagicMock()
        pending.poll.return_value = None
        lease._pending_probes.append(pending)
        try:
            with patch.object(images.subprocess, "Popen") as spawned, self.assertRaisesRegex(WorkerScopeError, "probe_unknown"):
                lease.verify()
            spawned.assert_not_called()
        finally:
            lease._pending_probes.clear()  # Synthetic process has no OS authority.
        lease.verify()
        with self.assertRaises(AttributeError):
            lease.image_sha256 = "0" * 64

    def test_replaced_private_mount_name_is_never_an_unmount_target(self):
        lease = self._lease()
        moved = lease._directory.with_name(lease._name + "-moved")
        os.rename(lease._directory, moved)
        try:
            with patch.object(images.subprocess, "run") as unmount, self.assertRaises(OSError):
                lease.close()
            unmount.assert_not_called()
        finally:
            os.rename(moved, lease._directory)
        lease.verify()

    def test_external_busy_descriptor_retains_mount_for_exact_retry(self):
        lease = self._lease()
        descriptor = os.dup(lease._root_fd)
        try:
            with self.assertRaisesRegex(WorkerScopeError, "busy"):
                lease.close()
            lease.verify()
        finally:
            os.close(descriptor)
        lease.close()
        self.assertFalse(lease._directory.exists())

    def test_wrong_digest_format_and_symlink_refuse_before_mount(self):
        with self.assertRaises(WorkerScopeError):
            images.ImmutableRuntimeImage(self.path, "0" * 64)
        link = self.root / "redirect"
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            images.ImmutableRuntimeImage(link, self.digest)
        with self.assertRaises(WorkerScopeError):
            images.ImmutableRuntimeImage(Path("relative"), self.digest)

    def test_pinned_stock_image_runs_through_canonical_fake_broker(self):
        values = [os.environ.get(key) for key in ("MENTAT_TEST_HERMES_SOURCE", "MENTAT_TEST_HERMES_VENV",
                                                 "MENTAT_TEST_PYTHON_ROOT", "MENTAT_TEST_RUNTIME_IMAGE",
                                                 "MENTAT_TEST_RUNTIME_IMAGE_SHA256")]
        if not all(values):
            self.skipTest("Operator-supplied public runtime candidate image unavailable")
        from tests import test_project_inference_broker as broker_tests
        import project_inference_broker as broker
        from mentat import project_worker_namespace as namespaces
        from mentat import project_worker_scope as scopes
        fixture = broker_tests.ProjectInferenceBrokerTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture._prepare_image_fixture()
        inputs = fixture.inputs
        roots = namespaces.RuntimeRoots(*(Path(value) for value in values[:3]))
        lease = images.ImmutableRuntimeImage(Path(values[3]), values[4])
        self.addCleanup(lease.close)
        sealed_libraries = os.environ.get("MENTAT_TEST_SEALED_LIBRARIES") == "1"
        with patch.object(namespaces, "_open_directory", wraps=namespaces._open_directory) as opened:
            prepared = namespaces.PreparedNamespace(roots, inputs.query, hashlib.sha256(inputs.query).hexdigest(),
                        "mentat-probe", vision=True, image=inputs.image, image_digest=inputs.image_digest,
                        image_extension=inputs.image_extension, runtime_image=lease, sealed_libraries=sealed_libraries)
            if sealed_libraries:
                self.assertFalse(any(call.args[0] in (Path("/usr/lib"), Path("/usr/lib64")) for call in opened.call_args_list))
        scope = scopes.LinuxWorkerScope(scopes.WorkerScopeLimits(wall_seconds=20))
        host, worker = socket.socketpair()
        actual_broker = None
        thread = None
        try:
            scope.start_inert()
            actual_broker = broker.QualificationInferenceBroker(fixture.root, fixture.run, broker_tests.fixtures.GENERATION,
                                                               fixture.backend, scope)
            thread = threading.Thread(target=actual_broker.serve, args=(host,))
            thread.start()
            handle = scope.handoff_namespace(prepared, worker)
            prepared.close()
            with self.assertRaisesRegex(WorkerScopeError, "busy"):
                lease.close()
            self.assertEqual(handle.wait()["text"], "PROBE_OK")
            self.assertEqual(fixture.backend.calls, 1)
            self.assertEqual(tuple(fixture._call_state()[:3]), ("succeeded", 1, "PROBE_OK"))
            lease.verify()
        finally:
            if actual_broker is not None:
                actual_broker.stop()
            scope.close_verified()
            host.close()
            worker.close()
            if thread is not None:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
            prepared.close()
        lease.close()
        self.assertFalse(lease._directory.exists())


if __name__ == "__main__":
    unittest.main()
