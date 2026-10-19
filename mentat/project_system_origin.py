"""Private fixed Ubuntu helper provenance inspection; no readiness authority."""

from dataclasses import dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

from mentat.project_worker_scope import _open_directory

FINGERPRINT = 'F6ECB3762474EDA9D21B7022871920D1991BC93C'
MAX_INDEX = 128 * 1024 * 1024
MAX_TAR = 32 * 1024 * 1024
MAX_MEMBER = 16 * 1024 * 1024
MAX_LINE = 64 * 1024
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_ENV = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/nonexistent'}
_COORDINATES = (('resolute', 'main'), ('resolute', 'universe'), ('resolute-updates', 'main'))
_UNREAPED_CHILDREN = []


class SystemOriginError(RuntimeError):
    pass


def _drain_children():
    """Worker retains exact Popen ownership; its parent bounds this wait."""
    while _UNREAPED_CHILDREN:
        for process in tuple(_UNREAPED_CHILDREN):
            if process.poll() is not None:
                _UNREAPED_CHILDREN.remove(process)
        if _UNREAPED_CHILDREN:
            time.sleep(0.02)


def _fail():
    raise SystemOriginError('system_origin.unverified')


@dataclass(frozen=True)
class HelperPin:
    package: str
    version: str
    suite: str
    component: str
    filename: str
    size: int
    archive_digest: str
    member: str
    member_size: int
    member_digest: str


PINS = (
    HelperPin('bubblewrap', '0.11.1-1ubuntu0.3', 'resolute-updates', 'main',
        'pool/main/b/bubblewrap/bubblewrap_0.11.1-1ubuntu0.3_amd64.deb', 51032,
        'd3a6c1b6b0e0474eaed6dbd055c0d601fd875af153976a0dc4aae75f4ea10868',
        'usr/bin/bwrap', 80424, '523da3e7399044be5163aee6f57a77a6bef7454376e28f0a0627920bae1b76b6'),
    HelperPin('squashfuse', '0.5.2-0.3', 'resolute', 'universe',
        'pool/universe/s/squashfuse/squashfuse_0.5.2-0.3_amd64.deb', 27560,
        '1aa60b77401d0c8c34eac9e70db57789797a348ad91b6c57cf372667dda2b330',
        'usr/bin/squashfuse', 39376, '091c5856b7cc0968f1ec7d4993b9ee7c2d468cd35e121fbda873511237190419'),
    HelperPin('fuse3', '3.18.2-1', 'resolute', 'main',
        'pool/main/f/fuse3/fuse3_3.18.2-1_amd64.deb', 27490,
        'a867fe3be1cbca271df70748b003232592c052233be5976d2a590f02327158db',
        'usr/bin/fusermount3', 39376, '2e69c3228b399df1f047d26c590ec820dbd8cd4108ee4d66ab903eac627594b2'),
    HelperPin('squashfs-tools', '1:4.7.5-1', 'resolute', 'main',
        'pool/main/s/squashfs-tools/squashfs-tools_4.7.5-1_amd64.deb', 228228,
        '3d4bf31f24105c4cc44da6b69ec130ed1784236059185f6d85bdd592c37a7bca',
        'usr/bin/mksquashfs', 387976, '41c82ab9270c08f5716b7143f264151d2895d153ce3c224d2d3d9269a75bc3ff'),
)
_NAMES = frozenset({'resolute.InRelease', 'resolute-updates.InRelease',
    *(f'{suite}-{component}.Packages' for suite, component in _COORDINATES),
    *(Path(pin.filename).name for pin in PINS)})


def _remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        _fail()
    return value


def _identity(details):
    return (details.st_dev, details.st_ino, details.st_uid, details.st_mode,
            details.st_size, details.st_mtime_ns, details.st_ctime_ns)


class _Snapshots:
    def __init__(self, root):
        self.root = root
        self.directory = _open_directory(root)
        self.members = []
        self.parents = []
        try:
            details = os.fstat(self.directory)
            if details.st_uid != os.getuid() or details.st_mode & 0o077 or set(os.listdir(self.directory)) != _NAMES:
                _fail()
            self.root_identity = _identity(details)
        except BaseException:
            os.close(self.directory)
            raise

    def read(self, name, maximum, deadline, *, installed=False):
        _remaining(deadline)
        parent = self.directory
        if installed:
            parent = _open_directory(Path('/usr/bin'))
            details = os.fstat(parent)
            self.parents.append((parent, _identity(details)))
            if details.st_uid != 0 or details.st_mode & 0o022:
                _fail()
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        before = os.fstat(descriptor)
        self.members.append((parent, name, descriptor, _identity(before)))
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != (0 if installed else os.getuid())
                or before.st_mode & (0o022 if installed else 0o077) or before.st_size > maximum):
            _fail()
        chunks = []
        count = 0
        while True:
            _remaining(deadline)
            block = os.read(descriptor, min(1024 * 1024, maximum + 1 - count))
            if not block:
                break
            count += len(block)
            if count > maximum:
                _fail()
            chunks.append(block)
        if _identity(os.fstat(descriptor)) != _identity(before):
            _fail()
        return b''.join(chunks)

    def close(self):
        try:
            reopened = _open_directory(self.root)
            try:
                if _identity(os.fstat(reopened)) != self.root_identity:
                    _fail()
            finally:
                os.close(reopened)
            for parent, name, descriptor, before in self.members:
                if (_identity(os.fstat(descriptor)) != before
                        or _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)) != before):
                    _fail()
            for descriptor, before in self.parents:
                reopened = _open_directory(Path('/usr/bin'))
                try:
                    if _identity(os.fstat(descriptor)) != before or _identity(os.fstat(reopened)) != before:
                        _fail()
                finally:
                    os.close(reopened)
        finally:
            for _, _, descriptor, _ in self.members:
                os.close(descriptor)
            for descriptor, _ in self.parents:
                os.close(descriptor)
            os.close(self.directory)


def _sealed(raw):
    import fcntl
    descriptor = os.memfd_create('mentat-public-origin', os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                _fail()
            offset += written
        fcntl.fcntl(descriptor, 1033, 0x000f)
        if fcntl.fcntl(descriptor, 1034) & 0x000f != 0x000f:
            _fail()
        os.lseek(descriptor, 0, os.SEEK_SET)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _command(command, descriptor, deadline, maximum):
    """Worker-only fixed commands; allocation is bounded while reading."""
    details = os.stat(command[0], follow_symlinks=False)
    if not stat.S_ISREG(details.st_mode) or details.st_uid != 0 or details.st_mode & 0o022:
        _fail()
    end = time.monotonic() + min(3, _remaining(deadline))
    process = subprocess.Popen(command, env=_ENV, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=(descriptor,), close_fds=True)
    output = {process.stdout: bytearray(), process.stderr: bytearray()}
    ceilings = {process.stdout: maximum, process.stderr: 16 * 1024}
    try:
        with selectors.DefaultSelector() as selector:
            for pipe in output:
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ)
            while selector.get_map():
                for key, _ in selector.select(_remaining(end)):
                    buffer = output[key.fileobj]
                    block = os.read(key.fd, min(65536, ceilings[key.fileobj] + 1 - len(buffer)))
                    buffer.extend(block)
                    if len(buffer) > ceilings[key.fileobj]:
                        _fail()
                    if not block:
                        selector.unregister(key.fileobj)
            if process.wait(timeout=_remaining(end)) != 0:
                _fail()
        return bytes(output[process.stdout])
    finally:
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=0.5)
        except BaseException as error:
            if process not in _UNREAPED_CHILDREN:
                _UNREAPED_CHILDREN.append(process)
            error._mentat_command_owner = process
            raise
        finally:
            process.stdout.close()
            process.stderr.close()


def _signed_text(raw):
    prefix = b'-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\n'
    marker = b'-----BEGIN PGP SIGNATURE-----\n'
    if (not isinstance(raw, bytes) or len(raw) > 256 * 1024 or not raw.startswith(prefix)
            or not raw.endswith(b'-----END PGP SIGNATURE-----\n')
            or raw.count(b'-----BEGIN PGP SIGNED MESSAGE-----') != 1
            or raw.count(b'-----BEGIN PGP SIGNATURE-----') != 1
            or raw.count(b'-----END PGP SIGNATURE-----') != 1):
        _fail()
    body = raw[len(prefix):raw.index(marker)]
    if not body.endswith(b'\n') or b'\r' in body:
        _fail()
    result = []
    for line in body.splitlines():
        if len(line) > MAX_LINE or line.startswith(b'-') and not line.startswith(b'- '):
            _fail()
        result.append(line[2:] if line.startswith(b'- ') else line)
    return b'\n'.join(result)


def _signature_status(raw):
    if len(raw) > 16 * 1024:
        _fail()
    try:
        lines = raw.decode('ascii').splitlines()
    except UnicodeError:
        _fail()
    signatures = []
    for line in lines:
        if not line.startswith('[GNUPG:] '):
            _fail()
        fields = line[9:].split()
        if not fields or fields[0] not in {'NEWSIG', 'KEY_CONSIDERED', 'SIG_ID', 'GOODSIG', 'VALIDSIG'}:
            _fail()
        if fields[0] == 'VALIDSIG':
            signatures.append(fields)
    if (len(signatures) != 1 or len(signatures[0]) != 11
            or signatures[0][1] != FINGERPRINT or signatures[0][-1] != FINGERPRINT
            or signatures[0][5:10] != ['4', '0', '1', '10', '01']):
        _fail()


def _release_fields(plaintext, suite):
    fields = {}
    entries = {}
    section = None
    try:
        for line in plaintext.decode('ascii').splitlines():
            if line.startswith(' '):
                if section == 'SHA256':
                    digest, size, name = line.split()
                    if (name in entries or _HEX.fullmatch(digest) is None or not size.isdigit()
                            or len(size) > 10 or '..' in name.split('/') or name.startswith('/')):
                        _fail()
                    entries[name] = (digest, int(size))
                continue
            key, separator, value = line.partition(':')
            if not separator or key in fields:
                _fail()
            fields[key] = value.strip()
            section = key
        if (fields.get('Origin') != 'Ubuntu' or fields.get('Label') != 'Ubuntu'
                or fields.get('Codename') != 'resolute' or fields.get('Suite') != suite):
            _fail()
    except (UnicodeError, ValueError):
        _fail()
    return entries


def _verify_release(raw, suite, deadline):
    plaintext = _signed_text(raw)
    descriptor = _sealed(raw)
    try:
        with tempfile.TemporaryDirectory(prefix='mentat-public-signature-') as home:
            status = _command(['/usr/bin/gpgv', '--homedir', home, '--status-fd', '1',
                '--keyring', '/usr/share/keyrings/ubuntu-archive-keyring.gpg', f'/proc/self/fd/{descriptor}'],
                descriptor, deadline, 16 * 1024)
        _signature_status(status)
        return _release_fields(plaintext, suite)
    finally:
        os.close(descriptor)


def _package_stanzas(raw, pins):
    wanted = {pin.package: pin for pin in pins}
    found = {}
    fields = {}
    chosen = None
    size = 0
    first = True
    for line in io.BytesIO(raw):
        if len(line) > MAX_LINE:
            _fail()
        if first and line.startswith(b'Package: '):
            try:
                name = line[9:].strip().decode('ascii')
            except UnicodeError:
                _fail()
            chosen = name if name in wanted else None
        first = False
        size += len(line)
        if size > MAX_LINE:
            _fail()
        if chosen:
            if line != b'\n' and not line[:1].isspace():
                key, separator, value = line.rstrip(b'\n').partition(b': ')
                if not separator or key in fields:
                    _fail()
                fields[key] = value
        if line == b'\n':
            if chosen:
                pin = wanted[chosen]
                if fields.get(b'Version') == pin.version.encode() and fields.get(b'Architecture') == b'amd64':
                    expected = {b'Package': pin.package.encode(), b'Filename': pin.filename.encode(),
                        b'Size': str(pin.size).encode(), b'SHA256': pin.archive_digest.encode()}
                    if chosen in found or any(fields.get(key) != value for key, value in expected.items()):
                        _fail()
                    found[chosen] = True
            first, fields, chosen, size = True, {}, None, 0
    if not first or set(found) != set(wanted):
        _fail()


def _member(raw, selected):
    """Narrow raw tar decoder; extension metadata is deliberately unsupported."""
    if not isinstance(raw, bytes) or len(raw) > MAX_TAR:
        _fail()
    position = 0
    names = set()
    result = None
    while True:
        header = raw[position:position + 512]
        if len(header) != 512:
            _fail()
        if header == bytes(512):
            tail = raw[position + 512:]
            if len(tail) < 512 or len(tail) > 65536 or any(tail):
                _fail()
            if result is None:
                _fail()
            return result
        try:
            item = tarfile.TarInfo.frombuf(header, 'utf-8', 'strict')
        except (tarfile.TarError, ValueError, UnicodeError):
            _fail()
        if item.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE, tarfile.LNKTYPE}:
            _fail()
        name = '' if item.name == '.' and item.isdir() else item.name.removeprefix('./').rstrip('/')
        if not item.isdir() and item.name.endswith('/'):
            _fail()
        if (name in names or len(names) >= 4096 or len(name.encode()) > 1024
                or any(ord(value) < 32 or ord(value) == 127 for value in name)
                or '\\' in name or name.startswith('/') or any(part in {'', '.', '..'} for part in name.split('/'))):
            if not (name == '' and item.isdir() and '' not in names):
                _fail()
        names.add(name)
        if not 0 <= item.size <= MAX_MEMBER or not item.isfile() and item.size:
            _fail()
        end = position + 512 + ((item.size + 511) // 512) * 512
        if end > len(raw):
            _fail()
        if name == selected:
            if not item.isfile():
                _fail()
            result = raw[position + 512:position + 512 + item.size]
        position = end


def _expected_helpers():
    return [{'name': pin.member, 'package': pin.package, 'version': pin.version,
             'archive_digest': pin.archive_digest, 'member_digest': pin.member_digest,
             'size': pin.member_size, 'suite': pin.suite, 'component': pin.component} for pin in PINS]


def _valid_report(candidate, started_at, ended_at):
    if (not isinstance(candidate, dict) or set(candidate) != {'format', 'scope', 'helpers', 'sampled_at'}
            or type(candidate['format']) is not int or candidate['format'] != 1
            or candidate['scope'] != 'ubuntu-26.04-amd64-public-helper-bytes'
            or type(candidate['sampled_at']) not in (int, float) or not math.isfinite(candidate['sampled_at'])
            or not started_at <= candidate['sampled_at'] <= ended_at
            or not isinstance(candidate['helpers'], list) or len(candidate['helpers']) != len(PINS)):
        return False
    for actual, expected in zip(candidate['helpers'], _expected_helpers()):
        if (not isinstance(actual, dict) or set(actual) != set(expected)
                or any(type(actual[key]) is not type(value) or actual[key] != value for key, value in expected.items())):
            return False
    return True


def _verify_core(root, deadline):
    if sys.platform != 'linux' or os.getuid() <= 0:
        _fail()
    snapshots = _Snapshots(root)
    try:
        releases = {suite: _verify_release(snapshots.read(suite + '.InRelease', 256 * 1024, deadline), suite, deadline)
                    for suite in ('resolute', 'resolute-updates')}
        for suite, component in _COORDINATES:
            raw = snapshots.read(f'{suite}-{component}.Packages', MAX_INDEX, deadline)
            expected, size = releases[suite][f'{component}/binary-amd64/Packages']
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected:
                _fail()
            _package_stanzas(raw, [pin for pin in PINS if (pin.suite, pin.component) == (suite, component)])
        for pin in PINS:
            raw = snapshots.read(Path(pin.filename).name, MAX_MEMBER, deadline)
            if len(raw) != pin.size or hashlib.sha256(raw).hexdigest() != pin.archive_digest:
                _fail()
            descriptor = _sealed(raw)
            try:
                expanded = _command(['/usr/bin/dpkg-deb', '--fsys-tarfile', f'/proc/self/fd/{descriptor}'],
                                    descriptor, deadline, MAX_TAR)
            finally:
                os.close(descriptor)
            member = _member(expanded, pin.member)
            local = snapshots.read(Path(pin.member).name, MAX_MEMBER, deadline, installed=True)
            if (local != member or len(member) != pin.member_size
                    or hashlib.sha256(member).hexdigest() != pin.member_digest):
                _fail()
        _remaining(deadline)
        return {'format': 1, 'scope': 'ubuntu-26.04-amd64-public-helper-bytes',
                'helpers': _expected_helpers(), 'sampled_at': time.time()}
    finally:
        snapshots.close()


def _helper_slot_type(base):
    class HelperSlot(base):
        def __init__(self, *args, **kwargs):
            self._unverified_group = None
            self._retained_process = None
            super().__init__(*args, **kwargs)

        def _terminate_owned(self):
            if self._unverified_group is None:
                process = self._process
                if process is None:
                    return
                group = getattr(process, '_mentat_process_group', None)
                self._retained_process = process
                self._unverified_group = group
                try:
                    super()._terminate_owned()
                except BaseException as error:
                    self._process = process
                    error._mentat_worker_owner = self
                    raise
            # Fixed trusted verifier descendants inherit this owned group.
            # On unresolved cleanup, subsequent calls only observe it; they
            # never send another signal to a potentially reused numeric ID.
            end = time.monotonic() + 0.5
            try:
                while True:
                    # Reap only the exact original leader; never signal again
                    # after inherited teardown has started or failed.
                    terminal = self._retained_process.poll() is not None
                    try:
                        os.killpg(self._unverified_group, 0)
                    except ProcessLookupError:
                        if not terminal:
                            _fail()
                        for pipe in (self._retained_process.stdin, self._retained_process.stdout):
                            if pipe is not None:
                                pipe.close()
                        reader = self._reader
                        if reader is not None:
                            reader.join(timeout=0.5)
                            if reader.is_alive():
                                _fail()
                        self._reader = None
                        self._unverified_group = self._retained_process = None
                        self._process = None
                        return
                    if time.monotonic() >= end:
                        _fail()
                    time.sleep(0.02)
            except BaseException as error:
                self._process = self._retained_process
                error._mentat_worker_owner = self
                raise
    return HelperSlot


def verify_helpers(root):
    """Fixed private qualification operation; no credential or execution grant."""
    if sys.platform != 'linux' or not isinstance(root, Path) or not root.is_absolute() or len(str(root).encode()) > 1024:
        _fail()
    from mentat.project_scope_inspector import _InspectionSlot
    from link_preview_workers import minimal_worker_environment
    HelperSlot = _helper_slot_type(_InspectionSlot)
    module_root = Path(__file__).resolve().parents[1]
    bootstrap = f"import runpy,sys;sys.path.insert(0,{str(module_root)!r});runpy.run_module('mentat.project_system_origin_worker',run_name='__main__')"
    deadline = time.monotonic() + 30
    started_at = time.time()
    slot = None
    candidate = None
    try:
        slot = HelperSlot((sys.executable, '-I', '-c', bootstrap), deadline=deadline,
            clock=time.monotonic, environment=minimal_worker_environment(),
            operation_watchdog_seconds=30, maximum_line_bytes=4096)
        slot._operation_watchdog_seconds = _remaining(deadline)
        candidate = slot.execute(kind='helper_origin', url=json.dumps({'root': str(root), 'deadline': deadline}))
        if not _valid_report(candidate, started_at, time.time()):
            _fail()
    except Exception:
        candidate = None
    finally:
        if slot is not None:
            slot.close()
    if candidate is None or time.monotonic() >= deadline:
        _fail()
    return candidate
