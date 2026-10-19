"""Historical signed Ubuntu helper-library byte comparison; no launch authority.

Only fixed public snapshots, package tuples and four existing helper identities
are accepted. No download, package install, executable/library load, installed
host comparison or production readiness state is provided by this module.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile
import time

from mentat import project_system_origin as origin
from mentat import project_runtime_host_trust as host
from mentat.project_runtime_elf import RuntimeElfError, inspect_host_elf
from mentat import project_library_plt as plt

MAX_INPUT_BYTES = 80 * 1024 * 1024
MAX_SELECTED_BYTES = 32 * 1024 * 1024
MAX_SELECTED_MEMBERS = 64
MAX_RESULT_BYTES = 16 * 1024
MAX_TAR_BYTES = 32 * 1024 * 1024
MAX_SCAN_BYTES = 320 * 1024 * 1024
SCOPE = "ubuntu-26.04-amd64-fixed-helper-library-historical-origin"
REQUIRED = ("security-current-packages", "sealed-hermes-python-library-image",
            "actual-loader-behavior", "glibc-plt-rewrite-and-ifunc-execution", "immutable-helper-execution",
            "fuse-privilege-and-verified-teardown", "production-runtime-qualification")
LIB = "/usr/lib/x86_64-linux-gnu/"
LOADER = "/usr/lib64/ld-linux-x86-64.so.2"


class LibraryOriginError(origin.SystemOriginError):
    pass


def _fail():
    raise LibraryOriginError("library_origin.unverified")


@dataclass(frozen=True)
class PackagePin:
    package: str
    version: str
    suite: str
    filename: str
    size: int
    archive_digest: str
    roots: tuple[str, ...]


PINS = (
    PackagePin('libc6', '2.43-2ubuntu2.4', 'resolute-updates',
        'pool/main/g/glibc/libc6_2.43-2ubuntu2.4_amd64.deb', 2104056,
        'a613b457f3ff9c84ebd28af8a05afdec22605ad9aed87c71e3a6ae5170aeb9ca', ('/usr/lib/x86_64-linux-gnu/libc.so.6', '/usr/lib/x86_64-linux-gnu/libm.so.6', '/usr/lib64/ld-linux-x86-64.so.2')),
    PackagePin('libcap2', '1:2.75-10ubuntu2', 'resolute',
        'pool/main/libc/libcap2/libcap2_2.75-10ubuntu2_amd64.deb', 29264,
        '150603a0792b1d22aa0bde0a26c27b413018c799284003e4b43cba587a5b3a18', ('/usr/lib/x86_64-linux-gnu/libcap.so.2',)),
    PackagePin('libfuse3-4', '3.18.2-1', 'resolute',
        'pool/main/f/fuse3/libfuse3-4_3.18.2-1_amd64.deb', 92984,
        '59ae972173e389eb981aaeae874b3d6aafe7eceff284f94e5c21ee1d049548c6', ('/usr/lib/x86_64-linux-gnu/libfuse3.so.4',)),
    PackagePin('liblz4-1', '1.10.0-8', 'resolute',
        'pool/main/l/lz4/liblz4-1_1.10.0-8_amd64.deb', 73784,
        '28fe729f69be0fa950618f0ee02e479218fd60b11e86c1aa6026c87632ed2aa4', ('/usr/lib/x86_64-linux-gnu/liblz4.so.1',)),
    PackagePin('liblzma5', '5.8.3-1', 'resolute',
        'pool/main/x/xz-utils/liblzma5_5.8.3-1_amd64.deb', 145410,
        '38ad8500817a9159db210fecfb8c50fa82d7a8829730fcdf8ae60e3523676d41', ('/usr/lib/x86_64-linux-gnu/liblzma.so.5',)),
    PackagePin('liblzo2-2', '2.10-3build2', 'resolute',
        'pool/main/l/lzo2/liblzo2-2_2.10-3build2_amd64.deb', 55968,
        'ffc9f1fea544f200b7b47a77e0ec89f70d493b5393ea2f7a43f6b9685b3341b8', ('/usr/lib/x86_64-linux-gnu/liblzo2.so.2',)),
    PackagePin('libpcre2-8-0', '10.46-1build1', 'resolute',
        'pool/main/p/pcre2/libpcre2-8-0_10.46-1build1_amd64.deb', 256534,
        '3e116766f1a7b149994d4745556023d993d26401223d1595520a991d4ba737fb', ('/usr/lib/x86_64-linux-gnu/libpcre2-8.so.0',)),
    PackagePin('libselinux1', '3.9-4build1', 'resolute',
        'pool/main/libs/libselinux/libselinux1_3.9-4build1_amd64.deb', 90316,
        '3ce3aea44b2ec00780c48b1b8e1f7e672166ec3ccac14b0eae8890e55983061e', ('/usr/lib/x86_64-linux-gnu/libselinux.so.1',)),
    PackagePin('libzstd1', '1.5.7+dfsg-3', 'resolute',
        'pool/main/libz/libzstd/libzstd1_1.5.7+dfsg-3_amd64.deb', 308174,
        '34365d611ccf1f717f90a92fbe52ed96ae1829ab9be363c68a83563322797f8f', ('/usr/lib/x86_64-linux-gnu/libzstd.so.1',)),
    PackagePin('libxxhash0', '0.8.3-2build1', 'resolute',
        'pool/main/x/xxhash/libxxhash0_0.8.3-2build1_amd64.deb', 25802,
        '4fff119ba9018fbe2eddfa7759bb4c7b6132ed38dcfa7fc58750c586d1d155a1', ('/usr/lib/x86_64-linux-gnu/libxxhash.so.0',)),
    PackagePin('zlib1g', '1:1.3.dfsg+really1.3.1-1ubuntu3.1', 'resolute-updates',
        'pool/main/z/zlib/zlib1g_1.3.dfsg+really1.3.1-1ubuntu3.1_amd64.deb', 61612,
        '450d9322ac4e9baea0f9a74548a20fde73b078235c1f5d1fb7084c2638e33cdd', ('/usr/lib/x86_64-linux-gnu/libz.so.1',)),
 )
# Raw release, raw main/binary-amd64 index, exact authenticated Date.
SNAPSHOTS = {
    "resolute": (135549, "45f95ce276cdba3e41870516a130e03c58b8b7a79e9546b0efe9e526d255740c",
        7581722, "92eb335c0ed27983d41a5a0efdf0edce3e67bfa34e8e987af9df260ca72d9bf9",
        "Thu, 23 Apr 2026 17:07:15 UTC"),
    "resolute-updates": (137401, "e5b34d880415a65eb1412e2580a72696937f30d754d312fdbd26e25283f0b4e2",
        3927317, "adbe8cefb6ae705c354c8d88b7e303738266d6a213c75a1426887ab99f0f49f1",
        "Mon, 19 Oct 2026 18:03:58 UTC"),
}


@dataclass(frozen=True)
class LibraryOriginCandidate:
    """Public static comparison data, freely constructible and never authority."""
    snapshots: tuple
    packages: tuple
    members: tuple
    aliases: tuple
    helper_closures: tuple
    freshness_qualified: bool = False
    required_qualification: tuple[str, ...] = REQUIRED


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _expected_inputs():
    expected = {}
    for suite, (size, digest, index_size, index_digest, _date) in SNAPSHOTS.items():
        expected[suite + ".InRelease"] = (size, digest)
        expected[suite + "-main.Packages"] = (index_size, index_digest)
    for pin in PINS:
        expected[PurePosixPath(pin.filename).name] = (pin.size, pin.archive_digest)
    for pin in origin.PINS:
        expected[PurePosixPath(pin.member).name + ".elf"] = (pin.member_size, pin.member_digest)
    return expected


def _identity(details):
    return (details.st_dev, details.st_ino, details.st_uid, details.st_mode,
            details.st_nlink, details.st_size, details.st_mtime_ns, details.st_ctime_ns)


def _private(details, *, directory=False):
    if (not (stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(details.st_mode))
            or getattr(details, "st_file_attributes", 0) & 0x400
            or details.st_uid != os.getuid()
            or stat.S_IMODE(details.st_mode) != (0o700 if directory else 0o600)
            or not directory and details.st_nlink != 1):
        _fail()


@contextmanager
def _capture(root, deadline):
    """Retain exact public input descriptors until terminal source revalidation."""
    expected = _expected_inputs()
    if len(expected) != 19 or sum(size for size, _ in expected.values()) > MAX_INPUT_BYTES:
        _fail()
    directory = origin._open_directory(root)
    retained = []
    try:
        details = os.fstat(directory)
        _private(details, directory=True)
        root_identity = _identity(details)
        if set(os.listdir(directory)) != set(expected):
            _fail()
        captured = {}
        for name, (size, digest) in expected.items():
            origin._remaining(deadline)
            lexical = os.stat(name, dir_fd=directory, follow_symlinks=False)
            _private(lexical)
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                 dir_fd=directory)
            retained.append((name, descriptor, _identity(lexical)))
            before = os.fstat(descriptor)
            _private(before)
            if _identity(before) != _identity(lexical) or before.st_size != size:
                _fail()
            chunks = []
            count = 0
            while True:
                origin._remaining(deadline)
                block = os.read(descriptor, min(1024 * 1024, size + 1 - count))
                if not block:
                    break
                count += len(block)
                if count > size:
                    _fail()
                chunks.append(block)
            raw = b"".join(chunks)
            if len(raw) != size or _sha(raw) != digest or _identity(os.fstat(descriptor)) != _identity(before):
                _fail()
            captured[name] = raw
        yield captured
        origin._remaining(deadline)
        reopened = origin._open_directory(root)
        try:
            _private(os.fstat(reopened), directory=True)
            if _identity(os.fstat(reopened)) != root_identity:
                _fail()
        finally:
            os.close(reopened)
        for name, descriptor, before in retained:
            for details in (os.fstat(descriptor), os.stat(name, dir_fd=directory, follow_symlinks=False)):
                _private(details)
                if _identity(details) != before:
                    _fail()
    finally:
        for _name, descriptor, _before in retained:
            os.close(descriptor)
        os.close(directory)


def _package_index_grammar(raw, deadline):
    """Validate every deb822 stanza, including unselected packages.

    This private binary-index grammar does not change the existing helper
    selector. Names are ASCII/case-insensitive; values are strict UTF-8. Only
    empty physical lines separate stanzas; continuation content is not reparsed
    as fields and cannot fold any fixed simple coordinate field.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= 16 * 1024 * 1024 or not raw.endswith(b"\n\n"):
        _fail()
    names = set()
    previous = None
    content = False
    stanza_bytes = 0
    stanzas = 0
    simple = {b"package", b"version", b"architecture", b"filename", b"size", b"sha256"}
    for line in io.BytesIO(raw):
        origin._remaining(deadline)
        stanza_bytes += len(line)
        if len(line) > origin.MAX_LINE or stanza_bytes > origin.MAX_LINE or not line.endswith(b"\n"):
            _fail()
        payload = line[:-1]
        try:
            payload.decode("utf-8", "strict")
        except UnicodeError:
            _fail()
        if any(byte < 32 and byte != 9 or byte == 127 for byte in payload):
            _fail()
        if not payload:
            if previous is not None and not content:
                _fail()
            if names:
                stanzas += 1
            names, previous, content, stanza_bytes = set(), None, False, 0
            continue
        if payload.startswith((b" ", b"\t")):
            if previous is None or previous in simple or not payload.strip(b" \t"):
                _fail()
            content = True
            continue
        if previous is not None and not content:
            _fail()
        name, separator, value = payload.partition(b":")
        if (not separator or not name or name[:1] in {b"#", b"-"}
                or any(byte < 33 or byte > 126 or byte == 58 for byte in name)):
            _fail()
        previous = name.lower()
        if previous in names:
            _fail()
        names.add(previous)
        content = bool(value.strip(b" \t"))
    if previous is not None or not stanzas:
        _fail()


def _verify_metadata(captured, deadline):
    for suite, (_size, _digest, index_size, index_digest, date) in SNAPSHOTS.items():
        raw = captured[suite + ".InRelease"]
        # _verify_release authenticates exactly one frame with the existing
        # full primary signer before any fields or hashes are used as authority.
        hashes = origin._verify_release(raw, suite, deadline)
        plaintext = origin._signed_text(raw)
        fields = {}
        for line in plaintext.decode("ascii").splitlines():
            if not line.startswith(" "):
                key, separator, value = line.partition(":")
                if not separator or key in fields:
                    _fail()
                fields[key] = value.strip()
        if (fields.get("Version") != "26.04" or fields.get("Date") != date
                or "Valid-Until" in fields
                or "amd64" not in fields.get("Architectures", "").split()
                or hashes.get("main/binary-amd64/Packages") != (index_digest, index_size)):
            _fail()
        index = captured[suite + "-main.Packages"]
        if len(index) != index_size or _sha(index) != index_digest:
            _fail()
        _package_index_grammar(index, deadline)
        origin._package_stanzas(index, [pin for pin in PINS if pin.suite == suite])


def _library_path(path, *, origin_path=None):
    try:
        return host._library_path(path, origin=origin_path)
    except host.HostClosureError:
        _fail()


def _inspect_origin_member(pin, path, raw):
    # Called only within the fixed authenticated-archive path. Other objects
    # retain ordinary parsing; there is no caller extra-tag policy input.
    profile = plt._PROFILES.get(path)
    if (pin.package == "libc6" and pin.version == "2.43-2ubuntu2.4"
            and pin.archive_digest == "a613b457f3ff9c84ebd28af8a05afdec22605ad9aed87c71e3a6ae5170aeb9ca"
            and profile is not None and len(raw) == profile.size and _sha(raw) == profile.digest):
        return plt._inspect_fixed_member(path, raw)
    return inspect_host_elf(raw)


def _tar_members(raw, pin, deadline):
    """Scan bounded raw tar; only selected links are resolved, never extracted."""
    if type(raw) is not bytes or len(raw) > MAX_TAR_BYTES:
        _fail()
    entries = {}
    position = 0
    while True:
        origin._remaining(deadline)
        header = raw[position:position + 512]
        if len(header) != 512:
            _fail()
        if header == bytes(512):
            tail = raw[position + 512:]
            if not 512 <= len(tail) <= 65536 or any(tail):
                _fail()
            break
        try:
            item = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        except (tarfile.TarError, ValueError, UnicodeError):
            _fail()
        if item.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE,
                             tarfile.SYMTYPE, tarfile.LNKTYPE}:
            _fail()
        leaf = header[:100].split(b"\0", 1)[0]
        if leaf.endswith(b"//"):
            _fail()
        name = "" if item.name in {".", "./"} and item.isdir() else item.name.removeprefix("./").rstrip("/")
        if (len(entries) >= 4096 or len(name.encode()) > 512 or "\\" in name
                or name.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or name and any(not part or part in {".", ".."} or len(part) > 255 for part in name.split("/"))
                or not name and not item.isdir() or not item.isdir() and item.name.endswith("/")
                or not 0 <= item.size <= 16 * 1024 * 1024 or not item.isfile() and item.size
                or len(item.linkname.encode()) > 512
                or any(ord(c) < 32 or ord(c) == 127 for c in item.linkname)):
            _fail()
        # Only the existing fixed usrmerge spellings are normalized.
        path = "/" + name
        if path.startswith(("/lib/", "/lib64/")):
            path = "/usr" + path
        if path in entries:
            _fail()
        end = position + 512 + ((item.size + 511) // 512) * 512
        if end > len(raw):
            _fail()
        entries[path] = (item.type, position + 512, item.size, item.linkname)
        position = end
    selected = {}
    def resolve(path):
        chain = set()
        while True:
            if path in chain or len(chain) >= 16 or path not in entries:
                _fail()
            chain.add(path)
            kind, offset, size, target = entries[path]
            if kind in {tarfile.REGTYPE, tarfile.AREGTYPE}:
                payload = raw[offset:offset + size]
                if not payload:
                    _fail()
                selected[path] = payload
                return path
            if kind != tarfile.SYMTYPE or not target:
                _fail()
            selected[path] = target
            path = _library_path(target, origin_path=path)
    for root in pin.roots:
        target = resolve(root)
        try:
            elf = _inspect_origin_member(pin, target, selected[target])
        except RuntimeElfError:
            _fail()
        expected = PurePosixPath(root).name
        if elf.soname != expected and not (root == LOADER and elf.soname is None):
            _fail()
    # No unselected alternate flat search-root object may shadow a closed root.
    sonames = {PurePosixPath(root).name for item in PINS for root in item.roots}
    for root in host._LIBRARY_ROOTS:
        for soname in sonames:
            path = root + "/" + soname
            if path in entries and path not in selected:
                _fail()
    return selected


def _subgraph(helper, members, parsed):
    try:
        captured = host._prepare_members(helper, tuple(sorted(members.items())))
        comparison, used = host._audit_graph(helper, captured, parsed)
    except host.HostClosureError:
        _fail()
    data = {"helper": comparison.helper, "members": comparison.members,
            "aliases": comparison.aliases, "edges": comparison.edges,
            "required_qualification": comparison.required_qualification}
    digest = _sha(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())
    return used, [helper, digest, len(comparison.members), len(comparison.aliases), len(comparison.edges)]


def _package_rows():
    return [[p.package, p.version, p.suite, p.archive_digest, p.size] for p in PINS]


def _snapshot_rows():
    return [[suite, pin[4], pin[1], pin[3]] for suite, pin in SNAPSHOTS.items()]


def _verify_core(root, deadline):
    with _capture(root, deadline) as captured:
        _verify_metadata(captured, deadline)
        members = {}
        parsed = {}
        scanned = 0
        for pin in PINS:
            descriptor = origin._sealed(captured[PurePosixPath(pin.filename).name])
            try:
                raw = origin._command(["/usr/bin/dpkg-deb", "--fsys-tarfile", f"/proc/self/fd/{descriptor}"],
                                      descriptor, deadline, MAX_TAR_BYTES)
            finally:
                os.close(descriptor)
            scanned += len(raw)
            if scanned > MAX_SCAN_BYTES:
                _fail()
            selected = _tar_members(raw, pin, deadline)
            if set(members) & set(selected):
                _fail()
            members.update(selected)
            for path, raw in selected.items():
                if type(raw) is bytes:
                    parsed[path] = host._ParsedElf(_sha(raw), len(raw), _inspect_origin_member(pin, path, raw))
            if (len(members) > MAX_SELECTED_MEMBERS
                    or sum(len(raw) for raw in members.values() if type(raw) is bytes) > MAX_SELECTED_BYTES):
                _fail()
        all_used = set()
        closures = []
        for pin in origin.PINS:
            helper = PurePosixPath(pin.member).name
            raw = captured[helper + ".elf"]
            path = "/" + pin.member
            graph = dict(members)
            graph[path] = raw
            helper_parsed = dict(parsed)
            helper_parsed[path] = host._ParsedElf(_sha(raw), len(raw), inspect_host_elf(raw))
            used, comparison = _subgraph(helper, graph, helper_parsed)
            all_used.update(used - {path})
            closures.append(comparison)
        if all_used != set(members):
            _fail()
        regular = [[name, _sha(raw), len(raw)] for name, raw in sorted(members.items()) if type(raw) is bytes]
        aliases = [[name, raw] for name, raw in sorted(members.items()) if type(raw) is str]
        result = {"format": 1, "scope": SCOPE, "snapshots": _snapshot_rows(),
                  "packages": _package_rows(), "members": regular, "aliases": aliases,
                  "helper_closures": closures, "freshness_qualified": False,
                  "required_qualification": list(REQUIRED), "sampled_at": time.time()}
        if len(json.dumps(result, separators=(",", ":")).encode()) > MAX_RESULT_BYTES:
            _fail()
    # The context has revalidated and closed every source descriptor.
    origin._remaining(deadline)
    return result


def _valid_report(value, start, end):
    if (type(value) is not dict or set(value) != {"format", "scope", "snapshots", "packages", "members",
            "aliases", "helper_closures", "freshness_qualified", "required_qualification", "sampled_at"}
            or type(value["format"]) is not int or value["format"] != 1 or value["scope"] != SCOPE
            or value["snapshots"] != _snapshot_rows() or value["packages"] != _package_rows()
            or value["freshness_qualified"] is not False or value["required_qualification"] != list(REQUIRED)
            or type(value["sampled_at"]) not in (int, float) or not math.isfinite(value["sampled_at"])
            or not start <= value["sampled_at"] <= end):
        return False
    try:
        regular, aliases, closures = value["members"], value["aliases"], value["helper_closures"]
        if (type(regular) is not list or not 1 <= len(regular) <= MAX_SELECTED_MEMBERS
                or type(aliases) is not list or len(regular) + len(aliases) > MAX_SELECTED_MEMBERS
                or type(closures) is not list or len(closures) != len(origin.PINS)):
            return False
        names = set()
        total = 0
        for item in regular:
            if (type(item) is not list or len(item) != 3 or type(item[0]) is not str
                    or _library_path(item[0]) != item[0] or item[0] in names
                    or type(item[1]) is not str or origin._HEX.fullmatch(item[1]) is None
                    or type(item[2]) is not int or not 1 <= item[2] <= 16 * 1024 * 1024):
                return False
            names.add(item[0]); total += item[2]
        if total > MAX_SELECTED_BYTES:
            return False
        for item in aliases:
            if (type(item) is not list or len(item) != 2 or type(item[0]) is not str
                    or _library_path(item[0]) != item[0] or item[0] in names
                    or type(item[1]) is not str or not 1 <= len(item[1]) <= 512):
                return False
            _library_path(item[1], origin_path=item[0]); names.add(item[0])
        for pin, item in zip(origin.PINS, closures):
            if (type(item) is not list or len(item) != 5 or item[0] != PurePosixPath(pin.member).name
                    or type(item[1]) is not str or origin._HEX.fullmatch(item[1]) is None
                    or any(type(n) is not int or not 0 <= n <= 256 for n in item[2:]) or item[2] < 2):
                return False
        return True
    except (ValueError, TypeError, KeyError, IndexError, LibraryOriginError):
        return False


def verify_fixed_helper_library_origins(root):
    """Fixed private Linux comparison; no ready flag, launch or persistent grant."""
    if (sys.platform != "linux" or not isinstance(root, Path) or not root.is_absolute()
            or len(str(root).encode()) > 1024):
        _fail()
    from mentat.project_scope_inspector import _InspectionSlot
    from link_preview_workers import minimal_worker_environment
    Slot = origin._helper_slot_type(_InspectionSlot)
    module_root = Path(__file__).resolve().parents[1]
    bootstrap = f"import runpy,sys;sys.path.insert(0,{str(module_root)!r});runpy.run_module('mentat.project_library_origin_worker',run_name='__main__')"
    deadline = time.monotonic() + 30
    started = time.time()
    slot = None
    value = None
    try:
        slot = Slot((sys.executable, "-I", "-c", bootstrap), deadline=deadline,
                    clock=time.monotonic, environment=minimal_worker_environment(),
                    operation_watchdog_seconds=30, maximum_line_bytes=MAX_RESULT_BYTES)
        slot._operation_watchdog_seconds = origin._remaining(deadline)
        value = slot.execute(kind="helper_library_origin", url=json.dumps({"root": str(root), "deadline": deadline}))
        if not _valid_report(value, started, time.time()):
            value = None
    except Exception:
        value = None
    finally:
        if slot is not None:
            # Existing owned-group teardown retains errors/ownership; do not
            # turn uncertain cleanup into an ordinary empty successful result.
            slot.close()
    if value is None or time.monotonic() >= deadline:
        _fail()
    return LibraryOriginCandidate(
        tuple(tuple(row) for row in value["snapshots"]), tuple(tuple(row) for row in value["packages"]),
        tuple(tuple(row) for row in value["members"]), tuple(tuple(row) for row in value["aliases"]),
        tuple(tuple(row) for row in value["helper_closures"]),
    )
