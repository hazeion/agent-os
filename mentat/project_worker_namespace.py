"""Private, fixed descriptor handoff for the stock proposal-only worker.

Runtime roots must come from a host-qualified installation. This component
pins their inodes; it does not attest an installation's release or model.
No browser, generic command or Run-admission surface calls it.
"""
from __future__ import annotations

import array
import ctypes
from dataclasses import dataclass
try:
    import fcntl
except ImportError:  # Unsupported platforms fail before opening snapshots.
    fcntl = None
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import time

from mentat.project_worker_scope import IS_LINUX, WorkerScopeError, _open_directory

MAX_HANDOFF = 4096
MAX_DESCRIPTORS = 12
EXPORT_BYTES = 32 * 1024 * 1024
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WorkerScopeError("worker_namespace.deadline")
    return remaining


def _root_path(value):
    if (not isinstance(value, Path) or not value.is_absolute() or len(str(value)) > 512
            or any(part in {".", ".."} for part in value.parts)
            or len(value.parts) < 3 or str(value).startswith(("/proc/", "/sys/", "/dev/", "/run/", "/mnt/"))
            or any(ord(c) < 32 for c in str(value))):
        raise WorkerScopeError("worker_namespace.runtime")
    return value


@dataclass(frozen=True)
class RuntimeRoots:
    source: Path
    venv: Path
    python: Path

    def __post_init__(self):
        paths = tuple(_root_path(value) for value in (self.source, self.venv, self.python))
        for left in paths:
            for right in paths:
                if left != right and left in right.parents:
                    raise WorkerScopeError("worker_namespace.runtime")
        if len(set(paths)) != 3:
            raise WorkerScopeError("worker_namespace.runtime")


def _sealed(data, label):
    descriptor = os.memfd_create(label, os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        offset = 0
        while offset < len(data):
            wrote = os.write(descriptor, data[offset:])
            if wrote <= 0:
                raise WorkerScopeError("worker_namespace.snapshot")
            offset += wrote
        os.lseek(descriptor, 0, os.SEEK_SET)
        # Fixed Linux UAPI (linux/fcntl.h); some supported Python builds omit
        # these symbolic constants. Still require actual kernel readback.
        fcntl.fcntl(descriptor, 1033, 0x000f)  # F_ADD_SEALS, WRITE/GROW/SHRINK/SEAL
        if fcntl.fcntl(descriptor, 1034) & 0x000f != 0x000f:
            raise WorkerScopeError("worker_namespace.snapshot")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _snapshot(data, digest, ceiling):
    if (type(data) is not bytes or not 0 < len(data) <= ceiling or not isinstance(digest, str)
            or _DIGEST.fullmatch(digest) is None or hashlib.sha256(data).hexdigest() != digest):
        raise WorkerScopeError("worker_namespace.snapshot")


class PreparedNamespace:
    """Own sealed query/image/code/config snapshots and pinned runtime roots.

    Inference capability remains the separately supplied, host-owned socket.
    Supplying this object is not execution consent or producing-Run evidence.
    """
    def __init__(self, roots: RuntimeRoots, query: bytes, query_digest: str,
                 model: str, *, vision: bool = False, image: bytes | None = None,
                 image_digest: str | None = None, image_extension: str = ""):
        if (not IS_LINUX or not callable(getattr(os, "memfd_create", None))
                or type(roots) is not RuntimeRoots or type(vision) is not bool
                or not isinstance(model, str) or _MODEL.fullmatch(model) is None
                or "://" in model or model.startswith("-")):
            raise WorkerScopeError("worker_namespace.unsupported")
        _snapshot(query, query_digest, 1024 * 1024)
        try:
            query.decode("utf-8")
        except UnicodeError as exc:
            raise WorkerScopeError("worker_namespace.snapshot") from exc
        if image is not None:
            if not vision or image_extension not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise WorkerScopeError("worker_namespace.image")
            _snapshot(image, image_digest, 8 * 1024 * 1024)
        elif image_digest is not None or image_extension:
            raise WorkerScopeError("worker_namespace.image")
        self._paths = tuple(str(value) for value in (roots.source, roots.venv, roots.python))
        self._model, self._vision, self._extension = model, vision, image_extension
        self._image_digest = image_digest
        self._fds = []
        self._closed = False
        try:
            for path in (roots.source, roots.venv, roots.python, Path("/usr/lib"), Path("/usr/lib64")):
                self._fds.append(_open_directory(path))
            # Fixed installation sentinels; release/content qualification remains
            # a separate prerequisite owned by the trusted host controller.
            for root_fd, name in ((self._fds[0], "hermes_cli/main.py"), (self._fds[1], "pyvenv.cfg")):
                parent = os.dup(root_fd)
                try:
                    parts = name.split("/")
                    for part in parts[:-1]:
                        child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                        os.close(parent)
                        parent = child
                    child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                    try:
                        if not stat.S_ISREG(os.fstat(child).st_mode):
                            raise WorkerScopeError("worker_namespace.runtime")
                    finally:
                        os.close(child)
                finally:
                    os.close(parent)
            self._fds.append(_sealed(query, "mentat-query"))
            frontend = Path(__file__).with_name("project_worker_frontend.py").read_bytes()
            if not 0 < len(frontend) <= 65536:
                raise WorkerScopeError("worker_namespace.code")
            self._fds.append(_sealed(frontend, "mentat-frontend"))
            if image is not None:
                self._fds.append(_sealed(image, "mentat-image"))
        except BaseException:
            self.close()
            raise

    def handoff(self, control, broker, lifecycle, wall_seconds, deadline):
        if (self._closed or type(broker) is not socket.socket or type(lifecycle) is not socket.socket
                or broker.family != socket.AF_UNIX or broker.type != socket.SOCK_STREAM
                or lifecycle.family != socket.AF_UNIX or lifecycle.type != socket.SOCK_SEQPACKET
                or type(wall_seconds) is not int or not 0 < wall_seconds <= 3600
                or time.monotonic() >= deadline):
            raise WorkerScopeError("worker_namespace.handoff")
        config = {"model": self._model, "vision": self._vision, "venv": self._paths[1],
                  "image_extension": self._extension, "image_digest": self._image_digest,
                  "wall_seconds": wall_seconds}
        config_fd = _sealed(_encoded(config), "mentat-config")
        try:
            descriptors = (*self._fds, config_fd, broker.fileno(), lifecycle.fileno())
            wire = {"version": 1, "kind": "namespace", "paths": self._paths,
                    "image_extension": self._extension, "descriptor_count": len(descriptors)}
            data = _encoded(wire)
            if len(data) > MAX_HANDOFF or len(descriptors) > MAX_DESCRIPTORS:
                raise WorkerScopeError("worker_namespace.handoff")
            ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", descriptors))]
            if control.sendmsg([data], ancillary) != len(data):
                raise WorkerScopeError("worker_namespace.handoff")
        finally:
            os.close(config_fd)

    def close(self):
        if not self._closed:
            for descriptor in self._fds:
                os.close(descriptor)
            self._fds.clear()
            self._closed = True


def receive_handoff(control):
    """Bootstrap-only decode. Close every transferred FD on malformed input."""
    data, ancillary, flags, _ = control.recvmsg(MAX_HANDOFF + 1, socket.CMSG_SPACE(MAX_DESCRIPTORS * 4),
                                               socket.MSG_CMSG_CLOEXEC)
    descriptors = []
    try:
        invalid_ancillary = False
        for level, kind, contents in ancillary:
            if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                invalid_ancillary = True
                continue
            values = array.array("i")
            values.frombytes(contents[:len(contents) - len(contents) % values.itemsize])
            descriptors.extend(values)
            invalid_ancillary |= len(contents) % values.itemsize != 0
        if invalid_ancillary or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or len(data) > MAX_HANDOFF:
            raise WorkerScopeError("worker_namespace.handoff")
        if not descriptors:
            return data, None
        wire = json.loads(data)
        if (not isinstance(wire, dict) or set(wire) != {"version", "kind", "paths", "image_extension", "descriptor_count"}
                or wire["version"] != 1 or wire["kind"] != "namespace" or len(descriptors) != wire["descriptor_count"]
                or wire["image_extension"] not in {"", ".png", ".jpg", ".jpeg", ".webp"}
                or len(descriptors) != (11 if wire["image_extension"] else 10)
                or not isinstance(wire["paths"], list) or len(wire["paths"]) != 3):
            raise WorkerScopeError("worker_namespace.handoff")
        RuntimeRoots(*(Path(value) for value in wire["paths"]))
        return wire, tuple(descriptors)
    except BaseException:
        for descriptor in descriptors:
            os.close(descriptor)
        raise


def namespace_command(wire, descriptors, deadline):
    """Build only this package's fixed namespace/CLI frontend command."""
    if time.monotonic() >= deadline:
        raise WorkerScopeError("worker_namespace.deadline")
    source, venv, python = wire["paths"]
    image = wire["image_extension"]
    query_fd, frontend_fd = descriptors[5:7]
    config_fd, broker_fd, lifecycle_fd = descriptors[-3:]
    command = ["/usr/bin/bwrap", "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc",
               "--unshare-uts", "--unshare-cgroup", "--disable-userns", "--assert-userns-disabled",
               "--new-session", "--die-with-parent", "--cap-drop", "ALL", "--clearenv",
               "--setenv", "HOME", "/home/mentat", "--setenv", "HERMES_HOME", "/home/mentat/.hermes",
               "--setenv", "LANG", "C.UTF-8", "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
               "--setenv", "PYTHONNOUSERSITE", "1", "--proc", "/proc", "--dev", "/dev",
               "--dir", "/home", "--perms", "0700", "--size", "16777216", "--tmpfs", "/home/mentat",
               "--perms", "0700", "--size", "8388608", "--tmpfs", "/tmp",
               "--perms", "0700", "--size", str(EXPORT_BYTES), "--tmpfs", "/exports",
               "--dir", "/worker", "--dir", "/inputs"]
    for descriptor, target in zip(descriptors[:5], (source, venv, python, "/usr/lib", "/usr/lib64")):
        command += ["--ro-bind-fd", str(descriptor), target]
    command += ["--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64",
                "--ro-bind-data", str(query_fd), "/inputs/query.txt",
                "--ro-bind-data", str(frontend_fd), "/worker/frontend.py",
                "--ro-bind-data", str(config_fd), "/worker/config.json"]
    if image:
        command += ["--ro-bind-data", str(descriptors[7]), "/inputs/image" + image]
    command += ["--remount-ro", "/dev", "--remount-ro", "/proc", "--remount-ro", "/",
                "--chdir", "/worker", "--", venv + "/bin/python", "-I", "/worker/frontend.py",
                str(broker_fd), str(lifecycle_fd), str(deadline)]
    return command


def receive_ready(endpoint, deadline):
    endpoint.settimeout(_remaining(deadline))
    data, ancillary, flags, _ = endpoint.recvmsg(128, socket.CMSG_SPACE(4), socket.MSG_CMSG_CLOEXEC)
    descriptors = []
    try:
        invalid_ancillary = False
        for level, kind, contents in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array("i")
                values.frombytes(contents[:len(contents) - len(contents) % values.itemsize])
                descriptors.extend(values)
                invalid_ancillary |= len(contents) % values.itemsize != 0
            else:
                invalid_ancillary = True
        if (invalid_ancillary or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or len(descriptors) != 1
                or json.loads(data) != {"version": 1, "kind": "ready"}):
            raise WorkerScopeError("worker_namespace.ready")
        _remaining(deadline)
        descriptor = descriptors[0]
        if (not stat.S_ISDIR(os.fstat(descriptor).st_mode)
                or fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
            raise WorkerScopeError("worker_namespace.exports")
        buffer = ctypes.create_string_buffer(256)
        library = ctypes.CDLL(None, use_errno=True)
        library.fstatfs.argtypes = (ctypes.c_int, ctypes.c_void_p)
        library.fstatfs.restype = ctypes.c_int
        if library.fstatfs(descriptor, ctypes.byref(buffer)) or ctypes.c_long.from_buffer(buffer).value != 0x01021994:
            raise WorkerScopeError("worker_namespace.exports")
        details = os.fstatvfs(descriptor)
        if not 0 < details.f_blocks * details.f_frsize <= EXPORT_BYTES:
            raise WorkerScopeError("worker_namespace.exports")
        _remaining(deadline)
        return descriptor
    except BaseException:
        for descriptor in descriptors:
            os.close(descriptor)
        raise


class NamespaceWorker:
    """Private output evidence, never canonical Run completion authority."""
    def __init__(self, scope, lifecycle, exports):
        self._scope, self._lifecycle, self.exports_descriptor = scope, lifecycle, exports
        self._consumed = False

    def wait(self):
        from mentat.project_worker_frontend import MAX_OUTPUT, MAX_REPLY, _json, _text
        if self._consumed or self._scope._deadline is None:
            raise WorkerScopeError("worker_namespace.terminal")
        self._consumed = True  # Lost/malformed outcomes never trigger a new worker.
        deadline = self._scope._deadline
        self._lifecycle.settimeout(_remaining(deadline))
        data, ancillary, flags, _ = self._lifecycle.recvmsg(MAX_REPLY + 512, socket.CMSG_SPACE(MAX_DESCRIPTORS * 4),
                                                          socket.MSG_CMSG_CLOEXEC)
        # A terminal packet must transfer no additional capability.
        for level, kind, contents in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array("i")
                values.frombytes(contents[:len(contents) - len(contents) % values.itemsize])
                for descriptor in values:
                    os.close(descriptor)
        if ancillary or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
            raise WorkerScopeError("worker_namespace.terminal")
        _remaining(deadline)
        try:
            result = _json(data)
            if (not isinstance(result, dict) or set(result) != {"version", "kind", "exit_code", "text", "output_bytes"}
                    or result["version"] != 1 or result["kind"] != "terminal"
                    or type(result["exit_code"]) is not int or result["exit_code"] != 0
                    or type(result["output_bytes"]) is not int or not 0 <= result["output_bytes"] <= MAX_OUTPUT):
                raise WorkerScopeError("worker_namespace.terminal")
            _text(result["text"])
        except (ValueError, RuntimeError, UnicodeError) as exc:
            raise WorkerScopeError("worker_namespace.terminal") from exc
        self._scope._control.settimeout(_remaining(deadline))
        if self._scope._control.recv(64) != b"EXIT 0\n":
            raise WorkerScopeError("worker_namespace.terminal")
        self._scope._process.wait(timeout=_remaining(deadline))
        if self._scope._process.returncode != 0 or self._scope.deadline_hit:
            raise WorkerScopeError("worker_namespace.terminal")
        if not self._scope.stop_local_and_verify():
            raise WorkerScopeError("worker_namespace.cleanup_unknown")
        _remaining(deadline)
        return result
