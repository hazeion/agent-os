"""Bounded signed-library fixtures; mocked primitives are not Linux provenance."""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tarfile
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from mentat import project_library_origin as library
from mentat import project_system_origin as origin
from mentat import project_runtime_host_trust as host
from tests.test_project_runtime_elf import fixture
from tests.test_project_system_origin import package, signed


def elf(soname=None, *, needed=(), executable=False):
    raw = bytearray(fixture(needed=needed, rpath=soname or "unused"))
    position = 320 + 16 * (2 + len(needed))
    _tag, offset = struct.unpack_from("<qQ", raw, position)
    struct.pack_into("<qQ", raw, position, 14 if soname else 21, offset if soname else 0)
    if not executable:
        struct.pack_into("<I", raw, 176, 0)
    return bytes(raw)


def archive(entries):
    target = io.BytesIO()
    with tarfile.open(fileobj=target, mode="w", format=tarfile.USTAR_FORMAT) as writer:
        for name, payload in entries:
            info = tarfile.TarInfo(name)
            if type(payload) is str:
                info.type = tarfile.SYMTYPE
                info.linkname = payload
            else:
                info.size = len(payload)
            writer.addfile(info, io.BytesIO(payload) if type(payload) is bytes else None)
    return target.getvalue()


class LibraryOriginTests(unittest.TestCase):
    def deadline(self):
        return time.monotonic() + 10

    def one_pin(self):
        return replace(library.PINS[0], roots=(library.LIB + "libc.so.6",))

    def complete_fixture(self, directory, *, custody_layout=False):
        """Real FD capture, tar/ELF/graph parsing; only OS signature/decoder mocked."""
        root = Path(directory).resolve() / "public"
        root.mkdir(mode=0o700)
        pins = []
        decoded = {}
        for n, pin in enumerate(library.PINS):
            entries = []
            for target in pin.roots:
                if target == library.LOADER:
                    entries.extend([(target.lstrip("/"), "../lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"),
                                    (library.LIB.lstrip("/") + "ld-linux-x86-64.so.2", elf())])
                else:
                    real_names = {
                        'libcap.so.2': 'libcap.so.2.75', 'libfuse3.so.4': 'libfuse3.so.3.18.2',
                        'liblz4.so.1': 'liblz4.so.1.10.0', 'liblzma.so.5': 'liblzma.so.5.8.3',
                        'liblzo2.so.2': 'liblzo2.so.2.0.0', 'libpcre2-8.so.0': 'libpcre2-8.so.0.14.0',
                        'libzstd.so.1': 'libzstd.so.1.5.7', 'libxxhash.so.0': 'libxxhash.so.0.8.3',
                        'libz.so.1': 'libz.so.1.3.1',
                    }
                    canonical = (library.LIB + real_names[Path(target).name]
                                 if custody_layout and Path(target).name in real_names else target)
                    if canonical != target:
                        entries.append((target.lstrip('/'), Path(canonical).name))
                    entries.append((canonical.lstrip("/"), elf(Path(target).name)))
            raw = ("public archive fixture " + str(n)).encode()
            pins.append(replace(pin, size=len(raw), archive_digest=library._sha(raw)))
            decoded[raw] = archive(entries)
            (root / Path(pin.filename).name).write_bytes(raw)
        helpers = []
        names = [Path(r).name for p in pins for r in p.roots if r != library.LOADER]
        for n, pin in enumerate(origin.PINS):
            raw = elf(needed=tuple(names[n::4]), executable=True)
            helpers.append(replace(pin, member_size=len(raw), member_digest=library._sha(raw)))
            (root / (Path(pin.member).name + ".elf")).write_bytes(raw)
        snapshots = {}
        for suite, original in library.SNAPSHOTS.items():
            index = b"".join(package(p) for p in pins if p.suite == suite)
            body = (f"Origin: Ubuntu\nLabel: Ubuntu\nVersion: 26.04\nCodename: resolute\nSuite: {suite}\n"
                    f"Date: {original[4]}\nArchitectures: amd64 arm64\nSHA256:\n "
                    f"{library._sha(index)} {len(index)} main/binary-amd64/Packages\n").encode()
            release = signed(body)
            snapshots[suite] = (len(release), library._sha(release), len(index), library._sha(index), original[4])
            (root / (suite + ".InRelease")).write_bytes(release)
            (root / (suite + "-main.Packages")).write_bytes(index)
        for path in root.iterdir():
            path.chmod(0o600)
        stack = ExitStack()
        stack.enter_context(patch.object(library, "PINS", tuple(pins)))
        stack.enter_context(patch.object(library, "SNAPSHOTS", snapshots))
        stack.enter_context(patch.object(origin, "PINS", tuple(helpers)))
        stack.enter_context(patch.dict(host._HELPERS, {Path(p.member).name: p for p in helpers}))
        def signature(raw, suite, deadline):
            return origin._release_fields(origin._signed_text(raw), suite)
        stack.enter_context(patch.object(origin, "_verify_release", side_effect=signature))
        def sealed(raw):
            path = next(root / Path(p.filename).name for p in pins if p.archive_digest == library._sha(raw))
            return os.open(path, os.O_RDONLY)
        stack.enter_context(patch.object(origin, "_sealed", side_effect=sealed))
        def decode(command, descriptor, deadline, maximum):
            self.assertEqual(command[:2], ["/usr/bin/dpkg-deb", "--fsys-tarfile"])
            self.assertEqual(command[2], f"/proc/self/fd/{descriptor}")
            self.assertEqual(maximum, library.MAX_TAR_BYTES)
            return decoded[os.read(descriptor, 4 * 1024 * 1024)]
        stack.enter_context(patch.object(origin, "_command", side_effect=decode))
        return root, stack

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor/private-mode fixture boundary")
    def test_complete_private_core_uses_real_capture_tar_elf_and_four_closures(self):
        with TemporaryDirectory() as temporary:
            root, stack = self.complete_fixture(temporary)
            before = {p.name: (library._identity(p.stat()), p.read_bytes()) for p in root.iterdir()}
            with stack:
                report = library._verify_core(root, self.deadline())
                self.assertTrue(library._valid_report(report, 0, time.time() + 1))
                self.assertEqual(len(report['helper_closures']), 4)
                self.assertEqual(len(report['packages']), 11)
                self.assertFalse(report['freshness_qualified'])
                self.assertIn('sealed-hermes-python-library-image', report['required_qualification'])
            self.assertEqual(before, {p.name: (library._identity(p.stat()), p.read_bytes()) for p in root.iterdir()})

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor/private-mode fixture boundary")
    def test_changed_archive_refuses_before_signature_or_decoder(self):
        with TemporaryDirectory() as temporary:
            root, stack = self.complete_fixture(temporary)
            with stack:
                path = root / Path(library.PINS[0].filename).name
                path.write_bytes(b"changed archive")
                with patch.object(origin, '_verify_release') as signature, patch.object(origin, '_command') as decoder:
                    with self.assertRaises(origin.SystemOriginError):
                        library._verify_core(root, self.deadline())
                    signature.assert_not_called(); decoder.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor/private-mode fixture boundary")
    def test_raw_metadata_capture_refuses_other_signed_snapshots_without_tool(self):
        with TemporaryDirectory() as temporary:
            root, stack = self.complete_fixture(temporary)
            with stack:
                path = root / 'resolute.InRelease'
                path.write_bytes(path.read_bytes().replace(b'26.04', b'26.05'))
                with patch.object(origin, '_verify_release') as signature:
                    with self.assertRaises(origin.SystemOriginError):
                        with library._capture(root, self.deadline()):
                            self.fail('changed snapshot accepted')
                    signature.assert_not_called()

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor/private-mode fixture boundary")
    def test_exact_snapshot_dates_architecture_and_expiry_are_closed(self):
        with TemporaryDirectory() as temporary:
            root, stack = self.complete_fixture(temporary)
            with stack, library._capture(root, self.deadline()) as captured:
                library._verify_metadata(captured, self.deadline())
                for old, new in [(b'Date: Thu, 23 Apr 2026', b'Date: Thu, 24 Apr 2026'),
                                 (b'Version: 26.04', b'Version: 25.10'),
                                 (b'Architectures: amd64 arm64', b'Architectures: amd64v3 arm64'),
                                 (b'Architectures:', b'Valid-Until: tomorrow\nArchitectures:')]:
                    changed = dict(captured)
                    changed['resolute.InRelease'] = captured['resolute.InRelease'].replace(old, new)
                    with self.subTest(new=new), self.assertRaises(origin.SystemOriginError):
                        library._verify_metadata(changed, self.deadline())

    def test_wrong_or_duplicate_package_tuple_and_epoch_are_refused(self):
        pin = library.PINS[1]
        raw = package(pin)
        origin._package_stanzas(raw, [pin])
        for altered in [raw + raw, raw.replace(pin.version.encode(), b'wrong'),
                        raw.replace(b'Architecture: amd64', b'Architecture: all'), raw[:-1],
                        raw.replace(pin.archive_digest.encode(), b'0' * 64)]:
            with self.assertRaises(origin.SystemOriginError):
                origin._package_stanzas(altered, [pin])
        ignored = b'Package: ignored\n' + b' x\n' * 32769 + b'\n' + raw
        with self.assertRaises(origin.SystemOriginError):
            origin._package_stanzas(ignored, [pin])

    def test_whole_index_grammar_accepts_complete_selected_and_ignored_utf8_stanzas(self):
        ignored = ("Package: ignored\nDescription: public\n continuation café\n .\n\tfinal line\n"
                   "X-Review: first\n second\n\n").encode("utf-8")
        library._package_index_grammar(ignored + package(library.PINS[0]), self.deadline())
        library._package_index_grammar(b"Package: ignored\nDescription:\n valid multiline value\n\n", self.deadline())

    def test_ignored_malformed_duplicate_continuation_and_termination_refuse_below_hash_guard(self):
        good = package(library.PINS[0])
        malformed = [
            b"Package: ignored\nmalformed field\n\n",
            b"Package: ignored\nDescription: one\nDescription: two\n\n",
            b"Package: ignored\nDescription: one\ndescription: two\n\n",
            b" orphan continuation\n\n",
            b"Package: ignored\n folded simple coordinate\n\n",
            b"Package: ignored\nDescription: one\n \t\n\n",
            b"Package: ignored\n# invalid binary-index comment\n\n",
            b"Package: ignored\nBad Name: value\n\n",
            b"Package: ignored\n-Invalid: value\n\n",
            b"Package: ignored\n: value\n\n",
            b"Package: ignored\nDescription: \xff\n\n",
            b"Package: ignored\nDescription: bad\x00control\n\n",
            b"Package: ignored\nDescription: empty-next\nEmpty:\n\n",
        ]
        for ignored in malformed:
            with self.subTest(ignored=ignored), self.assertRaises(library.LibraryOriginError):
                library._package_index_grammar(ignored + good, self.deadline())
        for truncated in [good[:-1], good[:-2], b"\n\n"]:
            with self.assertRaises(library.LibraryOriginError):
                library._package_index_grammar(truncated, self.deadline())
        for oversized in [b"Package: ignored\nDescription: " + b"x" * 65536 + b"\n\n",
                          b"Package: ignored\nDescription: start\n" + b" continuation\n" * 6000 + b"\n"]:
            with self.assertRaises(library.LibraryOriginError):
                library._package_index_grammar(oversized, self.deadline())

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor/private-mode fixture boundary")
    def test_authenticated_ignored_grammar_failure_stops_before_decoder_or_profile(self):
        with TemporaryDirectory() as temporary:
            root, stack = self.complete_fixture(temporary)
            with stack:
                path = root / 'resolute-main.Packages'
                old = path.read_bytes()
                altered = b"Package: ignored\nDescription: one\ndescription: duplicate\n\n" + old
                release_path = root / 'resolute.InRelease'
                release = release_path.read_bytes().replace(library._sha(old).encode(), library._sha(altered).encode()).replace(
                    (str(len(old)) + ' main/binary-amd64/Packages').encode(),
                    (str(len(altered)) + ' main/binary-amd64/Packages').encode())
                path.write_bytes(altered); release_path.write_bytes(release)
                selected = dict(library.SNAPSHOTS)
                selected['resolute'] = (len(release), library._sha(release), len(altered), library._sha(altered), selected['resolute'][4])
                with patch.object(library, 'SNAPSHOTS', selected), patch.object(origin, '_command') as decoder, patch.object(
                    library, '_inspect_origin_member') as profile, patch.object(
                    library, '_package_index_grammar', wraps=library._package_index_grammar) as grammar:
                    with self.assertRaises(library.LibraryOriginError):
                        library._verify_core(root, self.deadline())
                    self.assertGreater(grammar.call_count, 0)
                    decoder.assert_not_called(); profile.assert_not_called()

    def test_selected_regular_and_authenticated_alias_are_not_extracted(self):
        pin = self.one_pin()
        root = pin.roots[0]
        target = root + '.fixture'
        raw = archive([(root.lstrip('/'), Path(target).name), (target.lstrip('/'), elf('libc.so.6'))])
        with patch('builtins.open', side_effect=AssertionError('host extraction')):
            selected = library._tar_members(raw, pin, self.deadline())
        self.assertEqual(selected[root], Path(target).name)
        self.assertEqual(selected[target], elf('libc.so.6'))

    def test_selected_link_cycles_escapes_and_hardlinks_refuse(self):
        pin = self.one_pin(); name = pin.roots[0].lstrip('/')
        for target in [Path(name).name, '/tmp/host.so', '../../../../tmp/host.so', '$ORIGIN/libc.so.6']:
            with self.subTest(target=target), self.assertRaises(origin.SystemOriginError):
                library._tar_members(archive([(name, target)]), pin, self.deadline())
        raw = bytearray(archive([(name, elf('libc.so.6'))])); raw[156] = ord('1')
        raw[148:156] = b'        '; checksum = sum(raw[:512]); raw[148:156] = f'{checksum:06o}\0 '.encode()
        with self.assertRaises(origin.SystemOriginError): library._tar_members(bytes(raw), pin, self.deadline())

    def test_tar_rejects_extensions_duplicate_paths_traversal_and_bombs(self):
        pin = self.one_pin(); name = pin.roots[0].lstrip('/'); payload = elf('libc.so.6')
        for entries in [[(name, payload)] * 2, [('../' + name, payload)], [('/' + name, payload)],
                        [(name.replace('usr/', 'usr//'), payload)], [(name, b'')]]:
            with self.subTest(entries=entries[:1]), self.assertRaises(origin.SystemOriginError):
                library._tar_members(archive(entries), pin, self.deadline())
        for kind in [b'x', b'g', b'L', b'S', b'3', b'6']:
            raw = bytearray(archive([(name, payload)])); raw[156:157] = kind
            raw[148:156] = b'        '; raw[148:156] = f'{sum(raw[:512]):06o}\0 '.encode()
            with self.subTest(kind=kind), self.assertRaises(origin.SystemOriginError):
                library._tar_members(bytes(raw), pin, self.deadline())
        raw = bytearray(archive([(name, payload)])); raw[124:136] = b'77777777777\0'
        raw[148:156] = b'        '; raw[148:156] = f'{sum(raw[:512]):06o}\0 '.encode()
        with self.assertRaises(origin.SystemOriginError): library._tar_members(bytes(raw), pin, self.deadline())

    def test_strict_selected_elf_soname_and_architecture_cannot_drift(self):
        pin = self.one_pin(); name = pin.roots[0].lstrip('/')
        wrong = bytearray(elf('libc.so.6')); struct.pack_into('<H', wrong, 18, 183)
        for payload in [bytes(wrong), elf('libother.so.6'), fixture(rpath='/tmp/lib'), b'not ELF']:
            with self.assertRaises(origin.SystemOriginError):
                library._tar_members(archive([(name, payload)]), pin, self.deadline())

    def test_extra_flat_shadow_member_is_not_silently_ignored(self):
        pin = self.one_pin(); name = pin.roots[0].lstrip('/')
        with self.assertRaises(origin.SystemOriginError):
            library._tar_members(archive([(name, elf('libc.so.6')), ('usr/lib/libc.so.6', elf('libc.so.6'))]), pin, self.deadline())

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor/private-mode fixture boundary")
    def test_private_capture_refuses_extra_files_redirects_hardlinks_and_modes(self):
        for change in ['extra', 'symlink', 'hardlink', 'mode', 'root_mode']:
            with self.subTest(change=change), TemporaryDirectory() as temporary:
                root, stack = self.complete_fixture(temporary)
                with stack:
                    path = root / 'bwrap.elf'
                    if change == 'extra': (root / 'extra').write_bytes(b'public')
                    elif change == 'symlink': path.unlink(); path.symlink_to(root / 'squashfuse.elf')
                    elif change == 'hardlink': os.link(path, Path(temporary) / 'extra-link')
                    elif change == 'mode': path.chmod(0o644)
                    else: root.chmod(0o755)
                    with self.assertRaises((origin.SystemOriginError, OSError)):
                        with library._capture(root, self.deadline()): self.fail('unsafe capture accepted')

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor/private-mode fixture boundary")
    def test_capture_rechecks_same_inode_mode_hardlink_bytes_and_directory(self):
        for change in ['mode', 'hardlink', 'bytes', 'root']:
            with self.subTest(change=change), TemporaryDirectory() as temporary:
                root, stack = self.complete_fixture(temporary)
                with stack, self.assertRaises(origin.SystemOriginError):
                    with library._capture(root, self.deadline()):
                        path = root / 'bwrap.elf'
                        if change == 'mode': path.chmod(0o644)
                        elif change == 'hardlink': os.link(path, Path(temporary) / 'extra-link')
                        elif change == 'bytes': path.write_bytes(b'changed')
                        else: root.rename(Path(temporary) / 'replaced'); root.mkdir(mode=0o700)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'POSIX FIFO boundary')
    def test_capture_nonblocking_open_refuses_regular_to_fifo_before_read(self):
        with TemporaryDirectory() as temporary:
            root, stack = self.complete_fixture(temporary)
            with stack:
                original = os.open
                def replace_then_open(path, flags, **kwargs):
                    if path == 'resolute.InRelease':
                        self.assertTrue(flags & os.O_NONBLOCK)
                        self.assertTrue(flags & os.O_NOFOLLOW)
                        (root / path).unlink(); os.mkfifo(root / path, 0o600)
                    return original(path, flags, **kwargs)
                with patch.object(library.os, 'open', side_effect=replace_then_open), patch.object(library.os, 'read', side_effect=AssertionError('unsafe read')):
                    with self.assertRaises(origin.SystemOriginError):
                        with library._capture(root, self.deadline()): self.fail('FIFO accepted')

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor/private-mode fixture boundary")
    def test_report_rejects_freshness_ready_or_caller_report_fields(self):
        with TemporaryDirectory() as temporary:
            root, stack = self.complete_fixture(temporary)
            with stack:
                report = library._verify_core(root, self.deadline())
                for key, value in [('freshness_qualified', True), ('ready', True), ('packages', []), ('members', []), ('sampled_at', float('nan'))]:
                    invalid = deepcopy(report); invalid[key] = value
                    self.assertFalse(library._valid_report(invalid, 0, time.time() + 1))
                invalid = deepcopy(report); invalid['helper_closures'][0][1] = 'not a digest'
                self.assertFalse(library._valid_report(invalid, 0, time.time() + 1))

    def test_public_api_rejects_non_linux_or_invalid_root_before_worker(self):
        with patch.object(library.sys, 'platform', 'darwin'):
            with self.assertRaises(library.LibraryOriginError): library.verify_fixed_helper_library_origins(Path('/owned'))
        with patch.object(library.sys, 'platform', 'linux'):
            for root in ['not a Path', Path('relative')]:
                with self.assertRaises(library.LibraryOriginError): library.verify_fixed_helper_library_origins(root)

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor/private-mode fixture boundary")
    def test_parent_accepts_only_after_verified_cleanup_and_absolute_deadline(self):
        # Load native-platform dependencies before mocking only the API guard.
        import mentat.project_scope_inspector
        with TemporaryDirectory() as temporary:
            root, stack = self.complete_fixture(temporary)
            with stack:
                report = library._verify_core(root, self.deadline())
                class Slot:
                    def __init__(self, *args, **kwargs): self.closed = False
                    def execute(self, **kwargs):
                        result = deepcopy(report); result["sampled_at"] = time.time(); return result
                    def close(self): self.closed = True
                with patch.object(library.sys, 'platform', 'linux'), patch.object(origin, '_helper_slot_type', return_value=Slot):
                    candidate = library.verify_fixed_helper_library_origins(root)
                    self.assertFalse(candidate.freshness_qualified)
                    with self.assertRaises(FrozenInstanceError): candidate.members = ()
                class Unclosed(Slot):
                    def close(self): raise origin.SystemOriginError('owned cleanup unresolved')
                with patch.object(library.sys, 'platform', 'linux'), patch.object(origin, '_helper_slot_type', return_value=Unclosed), self.assertRaises(origin.SystemOriginError):
                    library.verify_fixed_helper_library_origins(root)
                with patch.object(library.sys, 'platform', 'linux'), patch.object(origin, '_helper_slot_type', return_value=Slot), patch.object(library.time, 'monotonic', side_effect=[0, 1, 31]):
                    with self.assertRaises(origin.SystemOriginError): library.verify_fixed_helper_library_origins(root)

    @unittest.skipUnless(sys.platform == 'linux', 'Actual fixed Linux signature/decoder primitives required')
    def test_actual_signed_public_packages_and_fixed_worker_preserve_sources(self):
        supplied = os.environ.get('MENTAT_TEST_HELPER_LIBRARY_ORIGIN')
        if not supplied: self.skipTest('Operator-staged fixed public library artifacts unavailable')
        root = Path(supplied)
        before = {p.name: (library._identity(p.stat()), library._sha(p.read_bytes())) for p in root.iterdir()}
        candidate = library.verify_fixed_helper_library_origins(root)
        self.assertEqual(len(candidate.packages), 11)
        self.assertEqual(len(candidate.helper_closures), 4)
        self.assertFalse(candidate.freshness_qualified)
        self.assertEqual(before, {p.name: (library._identity(p.stat()), library._sha(p.read_bytes())) for p in root.iterdir()})


if __name__ == '__main__':
    unittest.main()
