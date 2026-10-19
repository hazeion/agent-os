"""Private owned lease for a digest-pinned kernel-immutable runtime image.

This proves image bytes/mount immutability, not source/dependency origin,
provider/model readiness or Run admission. Host system libraries remain a
separate input until their exact closure is included and qualified.
"""
from __future__ import annotations

import ctypes
import array
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid
try:
    import fcntl
except ImportError:
    fcntl = None

from mentat.process_identity import linux_process_start_ticks
from mentat.project_worker_scope import IS_LINUX, WorkerScopeError, _open_directory

MAX_IMAGE_BYTES = 384 * 1024 * 1024
_IMAGE_SLOTS = threading.BoundedSemaphore(2)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_FUSE_MAGIC = 0x65735546
_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/nonexistent"}


def _fail(code):
    raise WorkerScopeError("runtime_image." + code)


def _mount_id(descriptor):
    descriptor_info = os.open("/proc/self/fdinfo/" + str(descriptor), os.O_RDONLY | os.O_CLOEXEC)
    try:
        data = os.read(descriptor_info, 4097)
        if len(data) > 4096:
            _fail("identity")
        for line in data.decode("ascii").splitlines():
            if line.startswith("mnt_id:"):
                value = int(line.split(":", 1)[1])
                if value > 0:
                    return value
        _fail("identity")
    finally:
        os.close(descriptor_info)


def _seal_file(path, digest):
    if (not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts
            or not isinstance(digest, str) or _HEX64.fullmatch(digest) is None):
        _fail("input")
    parent = _open_directory(path.parent)
    source = image = None
    try:
        source = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        details = os.fstat(source)
        if not stat.S_ISREG(details.st_mode) or not 96 <= details.st_size <= MAX_IMAGE_BYTES:
            _fail("input")
        image = os.memfd_create("mentat-runtime-image", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        hashed = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(source, 1024 * 1024)
            if not chunk:
                break
            if total == 0 and not chunk.startswith(b"hsqs"):
                _fail("format")
            total += len(chunk)
            if total > details.st_size:
                _fail("changed")
            hashed.update(chunk)
            offset = 0
            while offset < len(chunk):
                amount = os.write(image, chunk[offset:])
                if amount <= 0:
                    _fail("write")
                offset += amount
        if total != details.st_size or hashed.hexdigest() != digest:
            _fail("changed")
        fcntl.fcntl(image, 1033, 0x000f)
        if fcntl.fcntl(image, 1034) & 0x000f != 0x000f:
            _fail("seals")
        # Re-read the actual sealed bytes, not a saved pre-seal digest.
        os.lseek(image, 0, os.SEEK_SET)
        verified = hashlib.sha256()
        while chunk := os.read(image, 1024 * 1024):
            verified.update(chunk)
        if verified.hexdigest() != digest:
            _fail("seals")
        os.lseek(image, 0, os.SEEK_SET)
        result, image = image, None
        return result
    finally:
        for descriptor in (source, image, parent):
            if descriptor is not None:
                os.close(descriptor)


class ImmutableRuntimeImage:
    """Own exactly one fixed foreground mount; callers close workers first."""
    def __init__(self, path: Path, expected_sha256: str):
        if (not IS_LINUX or ctypes.sizeof(ctypes.c_long) != 8 or os.getuid() <= 0
                or fcntl is None or not callable(getattr(os, "memfd_create", None))
                or not callable(getattr(os, "pidfd_open", None))
                or not callable(getattr(signal, "pidfd_send_signal", None))):
            _fail("unsupported")
        for name in ("/usr/bin/squashfuse", "/usr/bin/fusermount3"):
            details = os.stat(name, follow_symlinks=False)
            if (not stat.S_ISREG(details.st_mode) or details.st_uid != 0
                    or details.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
                _fail("helper")
        if not _IMAGE_SLOTS.acquire(blocking=False):
            _fail("capacity")
        self._slot = True
        self._lock = threading.RLock()
        self._image = self._parent_fd = self._base_fd = self._root_fd = self._pidfd = None
        self._process = self._ticks = self._mount = self._identity = None
        self._references = 0
        self._workers = set()
        self._pending_probes = []
        self._closed = False
        self._name = "mentat-runtime-image-" + uuid.uuid4().hex
        self._parent = Path("/tmp")
        self._directory = self._parent / self._name
        self._target = self._directory / "mount"
        self._image_sha256 = expected_sha256
        try:
            self._image = _seal_file(path, expected_sha256)
            self._parent_fd = _open_directory(self._parent)
            os.mkdir(self._name, mode=0o700, dir_fd=self._parent_fd)
            self._base_fd = _open_directory(self._directory)
            os.mkdir("mount", mode=0o700, dir_fd=self._base_fd)
            original = os.stat("mount", dir_fd=self._base_fd, follow_symlinks=False)
            self._underlying = (original.st_dev, original.st_ino)
            self._process = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).with_name("project_runtime_mount_bootstrap.py")),
                 str(self._image), str(self._target)], env=_ENV, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(self._image,), close_fds=True,
            )
            self._ticks = linux_process_start_ticks(self._process.pid)
            self._pidfd = os.pidfd_open(self._process.pid, 0)
            if self._ticks is None or linux_process_start_ticks(self._process.pid) != self._ticks:
                _fail("daemon")
            cutoff = time.monotonic() + 3
            while time.monotonic() < cutoff:
                self._discover_mount()
                if self._mount is None:
                    if self._process.poll() is not None:
                        _fail("daemon")
                    time.sleep(.02)
                    continue
                try:
                    descriptors, identity = self._probe("root")
                except WorkerScopeError:
                    if self._pending_probes:
                        _fail("probe_unknown")
                    if self._process.poll() is not None:
                        _fail("daemon")
                    time.sleep(.02)
                    continue
                if identity[0] != self._mount:
                    for descriptor in descriptors:
                        os.close(descriptor)
                    _fail("replaced")
                self._root_fd = descriptors[0]
                _, device, inode = identity
                self._identity = (device, inode)
                self.verify()
                return
                if self._process.poll() is not None:
                    _fail("daemon")
                time.sleep(.02)
            _fail("startup")
        except BaseException as startup_error:
            # Retain ownership if an actually mounted filesystem cannot be
            # safely removed. No recursive path cleanup or lazy detach.
            try:
                self.close()
            except (OSError, WorkerScopeError, subprocess.SubprocessError):
                # Keep the ownership object attached to the active exception
                # rather than losing an ambiguous mounted resource on startup.
                startup_error.runtime_image_owner = self
            raise

    def _probe(self, mode):
        if any(process.poll() is None for process in self._pending_probes):
            _fail("probe_unknown")
        for process in self._pending_probes:
            process.wait(timeout=0)
        self._pending_probes.clear()
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        parent.settimeout(1)
        try:
            process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("project_runtime_image_probe.py")),
                                    str(child.fileno()), str(self._base_fd), mode], env=_ENV,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   pass_fds=(child.fileno(), self._base_fd), close_fds=True)
        except BaseException:
            parent.close()
            child.close()
            raise
        child.close()
        descriptors = []
        try:
            data, ancillary, flags, _ = parent.recvmsg(1024, socket.CMSG_SPACE(4 * 4), socket.MSG_CMSG_CLOEXEC)
            for level, kind, contents in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    values = array.array("i")
                    values.frombytes(contents[:len(contents) - len(contents) % values.itemsize])
                    descriptors.extend(values)
            payload = json.loads(data)
            expected = 1 if mode == "root" else 3
            if (flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or len(descriptors) != expected
                    or not isinstance(payload, dict) or set(payload) != {"version", "identity"}
                    or payload["version"] != 1 or not isinstance(payload["identity"], list)
                    or len(payload["identity"]) != 3 or any(type(value) is not int or value < 0 for value in payload["identity"])
                    or any(_mount_id(descriptor) != payload["identity"][0] for descriptor in descriptors)):
                _fail("probe")
            process.wait(timeout=1)
            if process.returncode != 0:
                _fail("probe")
            output = tuple(descriptors)
            descriptors.clear()
            return output, payload["identity"]
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise WorkerScopeError("runtime_image.probe") from exc
        finally:
            for descriptor in descriptors:
                os.close(descriptor)  # O_PATH handles have no FUSE release RPC.
            parent.close()
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._pending_probes.append(process)
                _fail("probe_unknown")

    def _base_current(self):
        held = os.fstat(self._base_fd)
        named = os.stat(self._name, dir_fd=self._parent_fd, follow_symlinks=False)
        if ((held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)
                or named.st_uid != os.getuid() or not stat.S_ISDIR(named.st_mode)
                or stat.S_IMODE(named.st_mode) != 0o700):
            _fail("replaced")

    @property
    def image_sha256(self):
        return self._image_sha256

    def _mount_current(self):
        """Kernel-only identity readback, including a disconnected FUSE daemon."""
        self._base_current()
        with open("/proc/self/mountinfo", "rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            _fail("identity")
        found = []
        target = str(self._target)
        for line in data.decode("utf-8").splitlines():
            fields = line.split()
            if len(fields) < 10 or "-" not in fields:
                _fail("identity")
            path = fields[4]
            if path == target:
                separator = fields.index("-")
                found.append((int(fields[0]), fields[separator + 1], fields[separator + 2], fields[5]))
            elif path.startswith(target + "/"):
                _fail("nested_mount")
        if (len(found) != 1 or found[0][0] != self._mount
                or not found[0][1].startswith("fuse.squashfuse") or "ro" not in found[0][3].split(",")):
            _fail("replaced")

    def _discover_mount(self):
        """Recover only the factory's exact owned target from kernel metadata."""
        if self._base_fd is None:
            return
        self._base_current()
        with open("/proc/self/mountinfo", "rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            _fail("identity")
        found = []
        for line in data.decode("utf-8").splitlines():
            fields = line.split()
            if len(fields) < 10 or "-" not in fields:
                _fail("identity")
            if fields[4] == str(self._target):
                separator = fields.index("-")
                if (not fields[separator + 1].startswith("fuse.squashfuse")
                        or fields[separator + 2] != "squashfuse"
                        or "ro" not in fields[5].split(",")):
                    _fail("replaced")
                found.append(int(fields[0]))
        if len(found) > 1:
            _fail("replaced")
        if found:
            if self._mount is not None and self._mount != found[0]:
                _fail("replaced")
            self._mount = found[0]

    def verify(self):
        with self._lock:
            if self._closed or self._root_fd is None or self._process is None or self._process.poll() is not None:
                _fail("daemon")
            if linux_process_start_ticks(self._process.pid) != self._ticks:
                _fail("daemon")
            if fcntl.fcntl(self._image, 1034) & 0x000f != 0x000f:
                _fail("seals")
            self._mount_current()
            descriptors, identity = self._probe("root")
            try:
                if identity != [self._mount, *self._identity]:
                    _fail("replaced")
            finally:
                os.close(descriptors[0])

    def acquire_roots(self, *, check_bootstrap=False):
        with self._lock:
            if type(check_bootstrap) is not bool:
                _fail("probe")
            self.verify()
            descriptors, identity = self._probe("namespace" if check_bootstrap else "roots")
            if identity != [self._mount, *self._identity]:
                for descriptor in descriptors:
                    os.close(descriptor)
                _fail("replaced")
            self._references += 1
            return descriptors

    def release_roots(self):
        with self._lock:
            if self._references <= 0:
                _fail("references")
            self._references -= 1

    def retain_worker(self, scope):
        from mentat.project_worker_scope import LinuxWorkerScope
        with self._lock:
            if type(scope) is not LinuxWorkerScope or scope._closed or scope._descriptor is None:
                _fail("worker")
            self.verify()
            if scope in self._workers:
                _fail("worker")
            self._workers.add(scope)

    def release_worker(self, scope):
        with self._lock:
            if (scope not in self._workers or not scope._closed or scope._descriptor is not None
                    or scope._pidfd is not None or scope._process is None or scope._process.poll() is None):
                _fail("worker")
            self._workers.remove(scope)

    def _mount_absent(self):
        with open("/proc/self/mountinfo", "rb") as stream:
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            _fail("identity")
        for line in data.decode("utf-8").splitlines():
            fields = line.split()
            if (len(fields) < 10 or int(fields[0]) == self._mount or fields[4] == str(self._target)
                    or fields[4].startswith(str(self._target) + "/")):
                _fail("cleanup_unknown")

    def close(self):
        with self._lock:
            if self._closed:
                return
            if self._references or self._workers:
                _fail("busy")
            if any(process.poll() is None for process in self._pending_probes):
                _fail("probe_unknown")
            self._pending_probes.clear()
            if self._mount is None:
                self._discover_mount()
            if self._mount is not None:
                # Verify exact owned mounted inode before releasing our own
                # busy directory handle and asking the fixed helper to unmount.
                self._mount_current()
                if self._root_fd is not None:
                    os.close(self._root_fd)
                    self._root_fd = None
                result = subprocess.run(["/usr/bin/fusermount3", "-u", str(self._target)], env=_ENV,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, timeout=3, check=False)
                if result.returncode != 0:
                    self._root_fd = os.open("mount", os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                            dir_fd=self._base_fd)
                    self._mount_current()
                    _fail("busy")
                self._mount_absent()
                current = os.stat("mount", dir_fd=self._base_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != self._underlying:
                    _fail("cleanup_unknown")
                self._mount = None
            if self._process is not None:
                if self._process.poll() is None:
                    if self._pidfd is None or linux_process_start_ticks(self._process.pid) != self._ticks:
                        _fail("daemon")
                    signal.pidfd_send_signal(self._pidfd, signal.SIGTERM)
                self._process.wait(timeout=3)
                # A failed-start helper may have mounted between the initial
                # lookup and termination. Reconcile that exact target before
                # deleting the underlying directory or releasing the slot.
                if self._mount is None:
                    self._discover_mount()
                    if self._mount is not None:
                        return self.close()
            if self._base_fd is not None:
                os.rmdir("mount", dir_fd=self._base_fd)
                os.close(self._base_fd)
                self._base_fd = None
                os.rmdir(self._name, dir_fd=self._parent_fd)
            for attribute in ("_root_fd", "_parent_fd", "_pidfd", "_image"):
                descriptor = getattr(self, attribute)
                if descriptor is not None:
                    os.close(descriptor)
                    setattr(self, attribute, None)
            self._closed = True
            if self._slot:
                _IMAGE_SLOTS.release()
                self._slot = False
