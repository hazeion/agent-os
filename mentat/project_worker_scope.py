"""Private Linux execution-scope ownership for the Project worker controller.

This component grants no Run, input, broker, or adapter authority. The trusted
controller must admit a Run and construct its fixed sandbox command separately.
No browser or bridge route accepts commands, units, cgroup paths, or PIDs here.
Local scope termination does not establish an external provider outcome.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from types import MappingProxyType
import uuid

from mentat.process_identity import IS_LINUX, linux_process_start_ticks

_CGROUP_ROOT = Path("/sys/fs/cgroup")
_CGROUP2_MAGIC = 0x63677270
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_DIRECTORY_FLAGS = getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)


class WorkerScopeError(RuntimeError):
    """A secret-free failure; callers retain unresolved Run/input evidence."""


@dataclass(frozen=True)
class WorkerScopeLimits:
    memory_bytes: int = 512 * 1024 * 1024
    processes: int = 32
    cpu_percent: int = 100
    wall_seconds: int = 20

    def __post_init__(self) -> None:
        for value, ceiling in ((self.memory_bytes, 512 * 1024 * 1024),
                               (self.processes, 32), (self.cpu_percent, 100),
                               (self.wall_seconds, 3600)):
            if type(value) is not int or not 0 < value <= ceiling:
                raise WorkerScopeError("worker_scope.limits")


@dataclass(frozen=True)
class KernelScopeLimits:
    memory_bytes: int
    processes: int
    cpu_quota: int
    cpu_period: int


def _read_control(descriptor: int, name: str) -> str:
    child = os.open(name, _FILE_FLAGS, dir_fd=descriptor)
    try:
        data = os.read(child, 4097)
        if len(data) > 4096:
            raise WorkerScopeError("worker_scope.control")
        return data.decode("ascii").strip()
    finally:
        os.close(child)


def _open_directory(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise WorkerScopeError("worker_scope.path")
    descriptor = os.open("/", os.O_RDONLY | _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            if part in (".", ".."):
                raise WorkerScopeError("worker_scope.path")
            child = os.open(part, os.O_RDONLY | _DIRECTORY_FLAGS, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _require_cgroup2(descriptor: int) -> None:
    # Linux statfs starts with a native long filesystem type. These supported
    # 64-bit Linux ABIs fit well inside the deliberately oversized buffer.
    buffer = ctypes.create_string_buffer(256)
    library = ctypes.CDLL(None, use_errno=True)
    function = library.fstatfs
    function.argtypes = (ctypes.c_int, ctypes.c_void_p)
    function.restype = ctypes.c_int
    if function(descriptor, ctypes.byref(buffer)) != 0 or ctypes.c_long.from_buffer(buffer).value != _CGROUP2_MAGIC:
        raise WorkerScopeError("worker_scope.filesystem")


def _effective_limits(descriptor: int, requested: WorkerScopeLimits) -> KernelScopeLimits:
    try:
        memory = int(_read_control(descriptor, "memory.max"))
        processes = int(_read_control(descriptor, "pids.max"))
        quota, period = map(int, _read_control(descriptor, "cpu.max").split())
    except (ValueError, UnicodeError) as exc:
        raise WorkerScopeError("worker_scope.effective_limits") from exc
    if (not 0 < memory <= requested.memory_bytes or not 0 < processes <= requested.processes
            or not 0 < quota or not 0 < period or quota * 100 > period * requested.cpu_percent):
        raise WorkerScopeError("worker_scope.effective_limits")
    return KernelScopeLimits(memory, processes, quota, period)


class LinuxWorkerScope:
    """Own one freshly generated user scope, pinned before worker handoff.

    start_inert owns the fixed bootstrap and its control socket. The bootstrap
    can receive no Agent, input or broker capability in this component; it
    exits on startup-refusal EOF. Production namespace/Run handoff is separate.
    All observations are private controller evidence, not browser projections.
    """

    def __init__(self, limits: WorkerScopeLimits = WorkerScopeLimits()) -> None:
        if (not IS_LINUX or not callable(getattr(os, "pidfd_open", None))
                or not callable(getattr(signal, "pidfd_send_signal", None))
                or ctypes.sizeof(ctypes.c_long) != 8):
            raise WorkerScopeError("worker_scope.unsupported")
        import pwd
        self._uid = os.getuid()
        if self._uid <= 0 or not isinstance(limits, WorkerScopeLimits):
            raise WorkerScopeError("worker_scope.unsupported")
        self._limits = limits
        self._unit = "mentat-project-worker-" + uuid.uuid4().hex + ".scope"
        self._relative = f"/user.slice/user-{self._uid}.slice/user@{self._uid}.service/app.slice/{self.unit}"
        self._path = _CGROUP_ROOT / self._relative.lstrip("/")
        self._environment = MappingProxyType({
            "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": pwd.getpwuid(self._uid).pw_dir,
            "XDG_RUNTIME_DIR": f"/run/user/{self._uid}",
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{self._uid}/bus",
        })
        self._launch_prefix = (
            "/usr/bin/systemd-run", "--user", "--scope", "--quiet", "--slice=app.slice",
            "--unit=" + self.unit, "--property=MemoryMax=" + str(limits.memory_bytes),
            "--property=TasksMax=" + str(limits.processes),
            "--property=CPUQuota=" + str(limits.cpu_percent) + "%",
            "--property=RuntimeMaxSec=" + str(limits.wall_seconds), "--property=TimeoutStopSec=2",
        )
        self._lock = threading.RLock()
        self._descriptor: int | None = None
        self._pidfd: int | None = None
        self._process: subprocess.Popen | None = None
        self._ticks: int | None = None
        self._invocation: str | None = None
        self._identity: tuple[int, int] | None = None
        self._timer: threading.Timer | None = None
        self._closed = False
        self._control: socket.socket | None = None
        self._deadline: float | None = None
        self.deadline_hit = False
        self.deadline_cleanup_verified = False

    @property
    def limits(self) -> WorkerScopeLimits:
        return self._limits

    @property
    def unit(self) -> str:
        return self._unit

    @property
    def environment(self):
        return self._environment

    @property
    def launch_prefix(self) -> tuple[str, ...]:
        return self._launch_prefix

    def _state(self) -> dict[str, str]:
        result = subprocess.run(
            ["/usr/bin/systemctl", "--user", "show", self.unit, "-p", "ActiveState",
             "-p", "ControlGroup", "-p", "InvocationID", "-p", "LoadState"],
            env=self.environment, stdin=subprocess.DEVNULL, capture_output=True, timeout=2, check=False,
        )
        if len(result.stdout) > 8192:
            raise WorkerScopeError("worker_scope.state")
        try:
            fields = dict(line.split("=", 1) for line in result.stdout.decode("ascii").splitlines() if "=" in line)
        except UnicodeError as exc:
            raise WorkerScopeError("worker_scope.state") from exc
        if set(fields) != {"ActiveState", "ControlGroup", "InvocationID", "LoadState"}:
            raise WorkerScopeError("worker_scope.state")
        return fields

    def start_inert(self) -> KernelScopeLimits:
        """Launch only the package-owned inert bootstrap, never caller argv."""
        with self._lock:
            if self._process is not None or self._closed:
                raise WorkerScopeError("worker_scope.launcher")
            parent, child = socket.socketpair()
            parent.settimeout(2)
            self._control = parent
            self._deadline = time.monotonic() + self.limits.wall_seconds
            try:
                process = subprocess.Popen(
                    [*self.launch_prefix, sys.executable, "-I",
                     str(Path(__file__).with_name("project_worker_bootstrap.py")),
                     str(child.fileno()), str(self._deadline)],
                    env=self.environment, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    pass_fds=(child.fileno(),),
                )
                self._process = process
            except BaseException:
                parent.close()
                self._control = None
                raise
            finally:
                child.close()
            # Timer starts before pinning. The bootstrap has no input or broker
            # capability and exits on control EOF even if startup verification fails.
            try:
                self._timer = threading.Timer(max(0, self._deadline - time.monotonic()), self._deadline_stop)
                self._timer.daemon = True
                self._timer.start()
                evidence = self._register_owned(process)
                if parent.recv(64) != b"READY\n" or time.monotonic() >= self._deadline:
                    raise WorkerScopeError("worker_scope.startup")
                return evidence
            except BaseException:
                parent.close()
                self._control = None
                # No command/input/broker handoff occurred. Wait for EOF-driven
                # inert bootstrap exit; unresolved cleanup is retained honestly.
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                raise

    def _register_owned(self, process: subprocess.Popen) -> KernelScopeLimits:
        with self._lock:
            if self._closed or process is not self._process:
                raise WorkerScopeError("worker_scope.launcher")
            self._ticks = linux_process_start_ticks(process.pid)
            if self._ticks is None or process.poll() is not None:
                raise WorkerScopeError("worker_scope.launcher")
            self._pidfd = os.pidfd_open(process.pid, 0)
            if linux_process_start_ticks(process.pid) != self._ticks:
                raise WorkerScopeError("worker_scope.launcher")
            cutoff = time.monotonic() + min(3, self.limits.wall_seconds)
            while time.monotonic() < cutoff:
                state = self._state()
                if state["ActiveState"] == "active" and state["ControlGroup"] == self._relative:
                    return self._pin(state)
                if process.poll() is not None:
                    break
                time.sleep(.02)
            raise WorkerScopeError("worker_scope.startup")

    def _pin(self, state: dict[str, str]) -> KernelScopeLimits:
        if _HEX32.fullmatch(state["InvocationID"]) is None:
            raise WorkerScopeError("worker_scope.identity")
        descriptor = _open_directory(self._path)
        try:
            _require_cgroup2(descriptor)
            details = os.fstat(descriptor)
            if details.st_uid != self._uid:
                raise WorkerScopeError("worker_scope.identity")
            members = _read_control(descriptor, "cgroup.procs").splitlines()
            if self._process is None or str(self._process.pid) not in members:
                raise WorkerScopeError("worker_scope.identity")
            current = self._state()
            if current["InvocationID"] != state["InvocationID"] or current["ControlGroup"] != self._relative:
                raise WorkerScopeError("worker_scope.identity")
            # Retain the verified generation even if its limits fail, so
            # exception cleanup can kill only this held kernel cgroup.
            self._descriptor = descriptor
            self._identity = (details.st_dev, details.st_ino)
            self._invocation = state["InvocationID"]
            descriptor = None
            limits = _effective_limits(self._descriptor, self.limits)
            if self.deadline_hit or self._deadline is None or time.monotonic() >= self._deadline:
                raise WorkerScopeError("worker_scope.deadline")
            return limits
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _empty(self) -> bool:
        if self._descriptor is None:
            return False
        try:
            fields = dict(line.split() for line in _read_control(self._descriptor, "cgroup.events").splitlines())
            if fields.get("populated") not in {"0", "1"}:
                raise WorkerScopeError("worker_scope.events")
            return fields["populated"] == "0"
        except FileNotFoundError:
            # Kernel cgroup directories do not expose POSIX unlink counts.
            # Removed control files on this held cgroup2 inode plus inactive
            # original-unit readback establish removal, never a signal target.
            _require_cgroup2(self._descriptor)
            state = self._state()
            return (state["ActiveState"] in {"inactive", "failed"}
                    and not state["ControlGroup"]
                    and state["InvocationID"] in {"", self._invocation})

    def stop_local_and_verify(self) -> bool:
        """Verify local emptiness only; never signal an unpinned named unit."""
        with self._lock:
            if self._closed:
                raise WorkerScopeError("worker_scope.closed")
            if self._control is not None:
                self._control.close()
                self._control = None
            if self._descriptor is None:
                # A startup failure can leave only the owned launcher. Fenced
                # client termination is not whole-scope termination evidence.
                if self._pidfd is not None and self._process is not None and self._process.poll() is None:
                    signal.pidfd_send_signal(self._pidfd, signal.SIGTERM)
                if self._process is not None:
                    try:
                        self._process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        return False
                state = self._state()
                return ((self._process is None or self._process.poll() is not None)
                        and state["ActiveState"] in {"inactive", "failed"} and not state["ControlGroup"])
            if not self._empty():
                try:
                    killer = os.open("cgroup.kill", os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=self._descriptor)
                except FileNotFoundError:
                    if not self._empty():
                        raise WorkerScopeError("worker_scope.stop")
                else:
                    try:
                        if os.write(killer, b"1\n") != 2:
                            raise WorkerScopeError("worker_scope.stop")
                    finally:
                        os.close(killer)
            if self._process is not None:
                self._process.wait(timeout=2)
            cutoff = time.monotonic() + 3
            while time.monotonic() < cutoff:
                if self._empty():
                    return True
                time.sleep(.02)
            return False

    def qualification_detach(self) -> None:
        """Fixed disposable-child probe; not a production Agent handoff."""
        with self._lock:
            if (self._descriptor is None or self._control is None or self.deadline_hit
                    or self._deadline is None or time.monotonic() >= self._deadline):
                raise WorkerScopeError("worker_scope.deadline")
            state = self._state()
            if (state["InvocationID"] != self._invocation or state["ControlGroup"] != self._relative
                    or state["ActiveState"] != "active" or self._empty()):
                raise WorkerScopeError("worker_scope.identity")
            if time.monotonic() >= self._deadline:
                raise WorkerScopeError("worker_scope.deadline")
            self._control.sendall(b"DETACH\n")
            if self._control.recv(64) != b"DETACHED\n":
                raise WorkerScopeError("worker_scope.handoff")

    def _deadline_stop(self) -> None:
        self.deadline_hit = True
        try:
            self.deadline_cleanup_verified = self.stop_local_and_verify()
        except (WorkerScopeError, OSError, subprocess.SubprocessError):
            self.deadline_cleanup_verified = False

    def close_verified(self) -> None:
        """Release ownership handles only after verified local cleanup."""
        if not self.stop_local_and_verify():
            raise WorkerScopeError("worker_scope.cleanup_unknown")
        if self._timer is not None:
            self._timer.cancel()
            if self._timer is not threading.current_thread() and self._timer.ident is not None:
                self._timer.join(timeout=6)
                if self._timer.is_alive():
                    raise WorkerScopeError("worker_scope.watchdog")
        with self._lock:
            for descriptor in (self._descriptor, self._pidfd):
                if descriptor is not None:
                    os.close(descriptor)
            self._descriptor = self._pidfd = None
            self._closed = True
