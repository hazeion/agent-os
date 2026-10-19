"""Private nonexecuting fixed-byte custody. No launch or readiness capability."""
from __future__ import annotations

import array
import hashlib
import json
import os
from pathlib import Path
import secrets
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
import threading
import time

from mentat import project_library_origin as library
from mentat import project_system_origin as origin
from mentat import project_runtime_host_trust as host
from mentat.project_runtime_elf import inspect_host_elf
from mentat.process_identity import linux_process_start_ticks

_LIBRARY_NAMES = (
    "libc.so.6", "libm.so.6", "ld-linux-x86-64.so.2", "libcap.so.2.75",
    "libfuse3.so.3.18.2", "liblz4.so.1.10.0", "liblzma.so.5.8.3",
    "liblzo2.so.2.0.0", "libpcre2-8.so.0.14.0", "libselinux.so.1",
    "libzstd.so.1.5.7", "libxxhash.so.0.8.3", "libz.so.1.3.1",
)
_CLASSES = {library.LIB + name: "signed-library-archive" for name in _LIBRARY_NAMES}
_CLASSES.update(("/" + pin.member, "compiled-helper-pin") for pin in origin.PINS)
_SEALS = 15


class ByteCustodyError(RuntimeError):
    def __init__(self):
        super().__init__("helper_byte_custody.unverified")


def _fail():
    raise ByteCustodyError()


def _close_fds(descriptors):
    """Attempt each owned number once; an error never permits numeric retry."""
    failures = []
    for descriptor in descriptors:
        try:
            os.close(descriptor)
        except BaseException as error:
            failures.append(("descriptor", descriptor, error))
    return failures


def _cleanup_failure(failures, owner):
    error = ByteCustodyError()
    error._mentat_custody_cleanup = tuple(failures)
    error._mentat_custody_owner = owner
    error.__cause__ = sys.exc_info()[1]
    return error


def _remaining(deadline):
    left = deadline - time.monotonic()
    if left <= 0:
        _fail()
    return left


def _supported():
    return (sys.platform == "linux" and os.getuid() > 0
            and os.getuid() == os.geteuid() and os.getgid() == os.getegid()
            and all(hasattr(os, name) for name in ("memfd_create", "pidfd_open", "waitid", "WNOWAIT"))
            and all(hasattr(socket, name) for name in ("SOCK_SEQPACKET", "SO_PASSCRED", "SCM_CREDENTIALS", "MSG_CMSG_CLOEXEC")))


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                _fail()
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _value: _fail())
    except (ValueError, UnicodeError):
        _fail()


def _wire(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")


class _Channel:
    """Exactly one operation's private endpoint, never a caller transport API."""
    def __init__(self, endpoint, peer, nonce, deadline):
        self.endpoint, self.peer = endpoint, peer
        self.nonce, self.deadline = nonce, deadline
        self.sent = self.received = 0
        endpoint.setblocking(False)

    def send(self, kind, value, descriptor=None):
        raw = _wire({"version": 1, "nonce": self.nonce, "sequence": self.sent,
                     "kind": kind, "value": value})
        if len(raw) > library.MAX_RESULT_BYTES:
            _fail()
        ancillary = [] if descriptor is None else [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                                   array.array("i", [descriptor]))]
        while True:
            _remaining(self.deadline)
            try:
                if self.endpoint.sendmsg([raw], ancillary) != len(raw):
                    _fail()
                self.sent += 1
                return
            except BlockingIOError:
                select.select([], [self.endpoint], [], _remaining(self.deadline))

    def receive(self, kind, *, rights=False, eof=False):
        descriptors = []
        try:
            while True:
                _remaining(self.deadline)
                try:
                    raw, controls, flags, _address = self.endpoint.recvmsg(
                        library.MAX_RESULT_BYTES, socket.CMSG_SPACE(struct.calcsize("3i"))
                        + socket.CMSG_SPACE(array.array("i").itemsize), socket.MSG_CMSG_CLOEXEC)
                    break
                except BlockingIOError:
                    select.select([self.endpoint], [], [], _remaining(self.deadline))
            credentials = []
            invalid = False
            for level, tag, data in controls:
                if level == socket.SOL_SOCKET and tag == socket.SCM_RIGHTS:
                    values = array.array("i")
                    if len(data) % values.itemsize:
                        invalid = True
                    values.frombytes(data[:len(data) // values.itemsize * values.itemsize])
                    descriptors.extend(values)
                elif level == socket.SOL_SOCKET and tag == socket.SCM_CREDENTIALS:
                    if len(data) != struct.calcsize("3i"):
                        invalid = True
                    else:
                        credentials.append(struct.unpack("3i", data))
                else:
                    invalid = True
            if eof:
                if raw or controls or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                    _fail()
                return None
            if (not raw or flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or invalid
                    or credentials != [self.peer] or len(descriptors) != int(rights)
                    or sum(level == socket.SOL_SOCKET and tag == socket.SCM_RIGHTS
                           for level, tag, _data in controls) != int(rights)):
                _fail()
            frame = _json(raw)
            if (type(frame) is not dict or set(frame) != {"version", "nonce", "sequence", "kind", "value"}
                    or type(frame["version"]) is not int or frame["version"] != 1
                    or frame["nonce"] != self.nonce or frame["kind"] != kind
                    or type(frame["sequence"]) is not int or frame["sequence"] != self.received):
                _fail()
            self.received += 1
            result = (frame["value"], descriptors[0]) if rights else frame["value"]
            descriptors = []
            return result
        finally:
            failures = _close_fds(descriptors)
            if failures:
                raise _cleanup_failure(failures, self)


def _read(descriptor, size, deadline):
    chunks = []
    count = 0
    while count <= size:
        _remaining(deadline)
        raw = os.pread(descriptor, min(1024 * 1024, size + 1 - count), count)
        if not raw:
            break
        chunks.append(raw)
        count += len(raw)
    if count != size:
        _fail()
    return b"".join(chunks)


def _object(descriptor, row, deadline):
    import fcntl
    details = os.fstat(descriptor)
    if (type(row) is not list or len(row) != 6 or type(row[0]) is not str
            or row[0] not in _CLASSES or row[5] != _CLASSES[row[0]]
            or any(type(row[index]) is not int for index in (1, 3, 4))
            or not 1 <= row[1] <= 16 * 1024 * 1024
            or type(row[2]) is not str or origin._HEX.fullmatch(row[2]) is None
            or not stat.S_ISREG(details.st_mode)
            or (details.st_size, details.st_dev, details.st_ino) != (row[1], row[3], row[4])
            or fcntl.fcntl(descriptor, 1034) & _SEALS != _SEALS):
        _fail()
    raw = _read(descriptor, row[1], deadline)
    if hashlib.sha256(raw).hexdigest() != row[2]:
        _fail()
    return raw


class FixedByteCustody:
    """Private byte reads/close only; metadata preserves distinct trust classes."""
    def __init__(self, descriptors, rows, aliases):
        self._descriptors = descriptors
        self._members = tuple(tuple(row[:3] + [row[5]]) for row in rows)
        self._aliases = tuple(tuple(row) for row in aliases)
        self._lock = threading.RLock()
        self._uncertain = ()

    @property
    def members(self):
        return self._members

    @property
    def aliases(self):
        return self._aliases

    def read(self, member):
        with self._lock:
            if type(member) is not str or member not in self._descriptors:
                _fail()
            descriptor, size = self._descriptors[member]
            return _read(descriptor, size, time.monotonic() + 1)

    def close(self):
        with self._lock:
            values, self._descriptors = self._descriptors, {}
            failures = _close_fds(descriptor for descriptor, _size in values.values())
            self._uncertain += tuple(failures)
            if self._uncertain:
                raise _cleanup_failure(self._uncertain, self)


def _manifest(value):
    if (type(value) is not dict or set(value) != {"report", "rows", "aliases"}
            or type(value["rows"]) is not list or len(value["rows"]) != 17
            or [row[0] for row in value["rows"] if type(row) is list and len(row) == 6] != sorted(_CLASSES)
            or type(value["aliases"]) is not list or len(value["aliases"]) != 10
            or type(value["report"]) is not dict
            or value["report"].get("aliases") != value["aliases"]
            or not library._valid_report(value["report"], 0, time.time())):
        _fail()
    expected = {row[0]: (row[2], row[1]) for row in value["report"]["members"]}
    expected.update(("/" + pin.member, (pin.member_size, pin.member_digest)) for pin in origin.PINS)
    if set(expected) != set(_CLASSES):
        _fail()
    for row in value["rows"]:
        if row[5] != _CLASSES[row[0]] or (row[1], row[2]) != expected[row[0]]:
            _fail()
    names = set()
    for path, target in value["aliases"]:
        if type(path) is not str or path in names or path in _CLASSES or type(target) is not str:
            _fail()
        library._library_path(target, origin_path=path)
        names.add(path)
    if value["aliases"] != sorted(value["aliases"]):
        _fail()
    return value["rows"]


def _worker_body(endpoint):
    """One trusted verification worker; no helper ELF execution or library load."""
    import resource
    for name, maximum in ((resource.RLIMIT_AS, 512 * 1024 * 1024), (resource.RLIMIT_CPU, 15),
                          (resource.RLIMIT_NOFILE, 64), (resource.RLIMIT_CORE, 0)):
        _soft, hard = resource.getrlimit(name)
        limit = maximum if hard == resource.RLIM_INFINITY else min(hard, maximum)
        resource.setrlimit(name, (limit, limit))
    # Parent embeds nonce/deadline in its fixed bootstrap; no external wire peer.
    parent, nonce, deadline = int(sys.argv[2]), sys.argv[3], float(sys.argv[4])
    if (not _supported() or os.getppid() != parent or origin._HEX.fullmatch(nonce) is None
            or not time.monotonic() < deadline <= time.monotonic() + 30):
        _fail()
    channel = _Channel(endpoint, (parent, os.getuid(), os.getgid()), nonce, deadline)
    request = channel.receive("START")
    if (type(request) is not dict or set(request) != {"root", "deadline"}
            or request["deadline"] != deadline or type(request["root"]) is not str
            or not Path(request["root"]).is_absolute() or len(request["root"].encode()) > 1024):
        _fail()
    descriptors = []
    try:
        with library._verified_selection(Path(request["root"]), deadline) as (report, members, owners):
            if (sorted(path for path, raw in members.items() if type(raw) is bytes) != sorted(_CLASSES)
                    or len([raw for raw in members.values() if type(raw) is str]) != 10):
                _fail()
            sealed = {path: raw for path, raw in members.items() if type(raw) is str}
            parsed = {}
            rows = []
            for path in sorted(_CLASSES):
                _remaining(deadline)
                descriptor = origin._sealed(members[path])
                descriptors.append(descriptor)
                details = os.fstat(descriptor)
                row = [path, len(members[path]), library._sha(members[path]), details.st_dev,
                       details.st_ino, _CLASSES[path]]
                raw = _object(descriptor, row, deadline)
                sealed[path] = raw
                elf = (library._inspect_origin_member(owners[path], path, raw)
                       if path in owners else inspect_host_elf(raw))
                parsed[path] = host._ParsedElf(library._sha(raw), len(raw), elf)
                rows.append(row)
            comparisons = []
            used = set()
            for pin in origin.PINS:
                path = "/" + pin.member
                graph = {name: raw for name, raw in sealed.items()
                         if name not in _CLASSES or _CLASSES[name] != "compiled-helper-pin" or name == path}
                subset = {name: item for name, item in parsed.items() if name in graph}
                consumed, comparison = library._subgraph(Path(path).name, graph, subset)
                comparisons.append(comparison)
                used.update(consumed)
            if used != set(sealed) or comparisons != report["helper_closures"]:
                _fail()
            manifest = {"report": report, "rows": rows, "aliases": report["aliases"]}
            _manifest(manifest)
            digest = library._sha(_wire(manifest))
            channel.send("MANIFEST", manifest)
            for index, descriptor in enumerate(descriptors):
                channel.send("MEMBER", index, descriptor)
                ack = channel.receive("MEMBER_ACK")
                if type(ack) is not int or ack != index:
                    _fail()
                descriptors[index] = None
                failures = _close_fds([descriptor])
                if failures:
                    raise _cleanup_failure(failures, endpoint)
        origin._drain_children()
        _remaining(deadline)
        channel.send("READY", digest)
        if channel.receive("RELEASE") != digest:
            _fail()
        _remaining(deadline)
    finally:
        failures = _close_fds(descriptor for descriptor in descriptors if descriptor is not None)
        if failures:
            raise _cleanup_failure(failures, endpoint)


def _worker(endpoint):
    try:
        _worker_body(endpoint)
    finally:
        # One socket-object close, independent of any member close error.
        try:
            endpoint.close()
        except BaseException as error:
            raise _cleanup_failure([('socket', endpoint, error)], endpoint)


class _OwnedWorker:
    """Signal authority exists only while the exact original leader is unreaped."""
    def __init__(self, process):
        self.process, self.pidfd = process, None
        self.reaped = False
        self.ticks = None
        self._uncertain = ()

    def pin(self):
        process = self.process
        self.ticks = linux_process_start_ticks(process.pid)
        self.pidfd = os.pidfd_open(process.pid, 0)
        if self.ticks is None or linux_process_start_ticks(process.pid) != self.ticks:
            _fail()

    def terminal(self, deadline):
        while True:
            status = os.waitid(os.P_PID, self.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if status is not None:
                return status
            select.select([self.pidfd], [], [], min(0.02, _remaining(deadline)))

    def _reap(self):
        pid, status = os.waitpid(self.process.pid, 0)
        self.reaped = True
        self.process.returncode = os.waitstatus_to_exitcode(status)
        if pid != self.process.pid:
            _fail()

    def absent(self):
        try:
            os.killpg(self.process.pid, 0)  # Read-only after reap; never signal here.
        except ProcessLookupError:
            return
        _fail()

    def normal(self, deadline):
        status = self.terminal(deadline)
        if status.si_code != os.CLD_EXITED or status.si_status != 0:
            _fail()
        self._reap()
        self.absent()
        _remaining(deadline)

    def close(self):
        if getattr(self, '_uncertain', ()):
            raise _cleanup_failure(self._uncertain, self)
        try:
            if not self.reaped:
                # Do not call Popen.poll/wait: either would end signal authority.
                if (self.pidfd is None or self.ticks is None
                        or linux_process_start_ticks(self.process.pid) != self.ticks
                        or os.getpgid(self.process.pid) != self.process.pid):
                    _fail()
                for kind in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(self.process.pid, kind)
                    except ProcessLookupError:
                        pass
                    cutoff = time.monotonic() + 0.5
                    try:
                        self.terminal(cutoff)
                    except ByteCustodyError:
                        if kind == signal.SIGKILL:
                            raise
                self._reap()
            self.absent()
        except BaseException as error:
            error._mentat_worker_owner = self
            raise
        if self.pidfd is not None:
            descriptor = self.pidfd
            self.pidfd = None
            failures = _close_fds([descriptor])
            if failures:
                self._uncertain = tuple(failures)
                raise _cleanup_failure(failures, self)


def acquire_fixed_helper_bytes(root):
    """Own fixed bytes only. Unsupported platforms refuse before any work."""
    if not _supported():
        _fail()
    if not isinstance(root, Path) or not root.is_absolute() or len(str(root).encode()) > 1024:
        _fail()
    from link_preview_workers import minimal_worker_environment
    deadline = time.monotonic() + 30
    nonce = secrets.token_hex(32)
    endpoint = child = None
    owner = None
    received = {}
    success = False
    try:
        endpoint, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
        for item in (endpoint, child):
            item.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        module_root = Path(__file__).resolve().parents[1]
        bootstrap = (f"import runpy,sys;sys.path.insert(0,{str(module_root)!r});"
                     "runpy.run_module('mentat.project_helper_byte_custody',run_name='__main__')")
        process = subprocess.Popen(
            [sys.executable, "-I", "-c", bootstrap, str(child.fileno()), str(os.getpid()), nonce, str(deadline)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=minimal_worker_environment(), cwd="/tmp", close_fds=True,
            pass_fds=(child.fileno(),), start_new_session=True)
        # Retain the process even if pidfd/start capture or endpoint close fails.
        owner = _OwnedWorker(process)
        owner.pin()
        child.close()
        child = None
        channel = _Channel(endpoint, (process.pid, os.getuid(), os.getgid()), nonce, deadline)
        channel.send("START", {"root": str(root), "deadline": deadline})
        manifest = channel.receive("MANIFEST")
        rows = _manifest(manifest)
        identities = set()
        for index, row in enumerate(rows):
            value, descriptor = channel.receive("MEMBER", rights=True)
            # Ownership starts before validating index or any object property.
            try:
                if type(value) is not int or value != index:
                    _fail()
                _object(descriptor, row, deadline)
                identity = tuple(row[3:5])
                if identity in identities:
                    _fail()
                identities.add(identity)
                received[row[0]] = (descriptor, row[1])
                descriptor = None
                channel.send("MEMBER_ACK", index)
            finally:
                if descriptor is not None:
                    failures = _close_fds([descriptor])
                    if failures:
                        raise _cleanup_failure(failures, owner)
        digest = library._sha(_wire(manifest))
        if channel.receive("READY") != digest:
            _fail()
        channel.send("RELEASE", digest)
        endpoint.shutdown(socket.SHUT_WR)
        channel.receive(None, eof=True)
        owner.normal(deadline)
        owner.close()
        _remaining(deadline)
        lease = FixedByteCustody(received, rows, manifest["aliases"])
        success = True
        return lease
    except BaseException as error:
        if not isinstance(error, ByteCustodyError):
            failure = ByteCustodyError()
            failure.__cause__ = error
            error = failure
        raise error
    finally:
        failures = []
        if not success:
            failures.extend(_close_fds(descriptor for descriptor, _size in received.values()))
        for item in (endpoint, child):
            if item is not None:
                try:
                    item.close()
                except BaseException as error:
                    failures.append(('socket', item, error))
        if owner is not None and (not success or owner.pidfd is not None):
            try:
                owner.close()
            except BaseException as error:
                failures.append(('worker', owner, error))
        if failures:
            if success:
                # A final socket/owner close failure cancels publication too.
                try:
                    lease.close()
                except BaseException as error:
                    failures.append(('lease', lease, error))
            raise _cleanup_failure(failures, owner)


def _main():
    if not _supported() or len(sys.argv) != 5:
        return 1
    endpoint = socket.socket(fileno=int(sys.argv[1]))
    endpoint.set_inheritable(False)
    try:
        _worker(endpoint)
        return 0
    except BaseException:
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
