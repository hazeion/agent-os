"""Portable boundary tests only; OS/API substitutions are not Linux qualification."""
import errno
import importlib.util
import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

_PATH = Path(__file__).resolve().parents[1] / 'scripts/qualify_helper_byte_custody.py'
_SPEC = importlib.util.spec_from_file_location('custody_qualification_driver', _PATH)
driver = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(driver)


class CustodyQualificationDriverTests(unittest.TestCase):
    def attempt(self):
        with patch.object(driver.time, 'monotonic', return_value=100):
            return driver.QualificationAttempt(Path('/fixed-public-inputs'))

    def test_fixed_production_pins_exclude_tests_and_reviews(self):
        self.assertEqual(driver.SOURCE_COMMIT, 'fc4e572b17ea9032fadae867743e6f0b05562aeb')
        names = [row[0] for row in driver.SOURCE_BLOBS]
        self.assertEqual(len(names), len(set(names)))
        self.assertIn('mentat/project_helper_byte_custody.py', names)
        self.assertIn('mentat/project_library_origin.py', names)
        self.assertIn('mentat.toml', names)
        self.assertTrue(all(not name.startswith(('tests/', 'reviews/')) for name in names))
        self.assertTrue(all(type(size) is int and size > 0 and len(blob) == 40
                            for _name, size, blob in driver.SOURCE_BLOBS))

    def test_clock_starts_before_source_path_observation(self):
        observations = []
        with patch.object(driver.time, 'monotonic', side_effect=lambda: observations.append('clock') or 1), \
             patch.object(driver.Path, 'absolute', side_effect=lambda: observations.append('path') or Path('/a/b')):
            driver.QualificationAttempt(Path('/inputs'))
        self.assertEqual(observations, ['clock', 'path'])

    def test_one_use_retained_attempt_is_not_replaced(self):
        sentinel = object()
        with patch.object(driver, 'active_attempt', sentinel):
            with self.assertRaises(driver.QualificationRefused):
                driver.begin(Path('/inputs'))
            self.assertIs(driver.active_attempt, sentinel)

    def test_unsupported_host_refuses_without_source_or_api(self):
        attempt = self.attempt()
        with patch.object(driver.sys, 'platform', 'unsupported'), \
             patch.object(driver.time, 'monotonic', return_value=101), \
             patch.object(attempt, '_sources') as sources:
            report = json.loads(attempt.run())
        sources.assert_not_called()
        self.assertFalse(report['qualification'])
        self.assertTrue(report['cleanup_verified'])
        self.assertFalse(report['session_must_remain_open'])

    def test_deadline_expiry_before_preflight_does_not_observe_source(self):
        attempt = self.attempt()
        with patch.object(driver.time, 'monotonic', return_value=130), \
             patch.object(attempt, '_sources') as sources:
            self.assertFalse(json.loads(attempt.run())['qualification'])
        sources.assert_not_called()

    def test_second_run_refuses(self):
        attempt = self.attempt()
        attempt.used = True
        with self.assertRaises(driver.QualificationRefused):
            attempt.run()

    def test_inventory_checks_exactly_sixty_four_slots(self):
        with patch.object(driver, '_slot', side_effect=lambda fd: ('present',) if fd in (0, 63) else None) as slot:
            self.assertEqual(driver._inventory(), {0: ('present',), 63: ('present',)})
        self.assertEqual([call.args[0] for call in slot.call_args_list], list(range(64)))

    def test_only_ebadf_is_absent(self):
        fake_fcntl = SimpleNamespace(F_GETFD=1, fcntl=lambda *_args: 1)
        with patch.dict(sys.modules, {'fcntl': fake_fcntl}), \
             patch.object(driver.os, 'fstat', side_effect=OSError(errno.EBADF, 'private')):
            self.assertIsNone(driver._slot(3))
        with patch.dict(sys.modules, {'fcntl': fake_fcntl}), \
             patch.object(driver.os, 'fstat', side_effect=OSError(errno.EPERM, 'private')):
            with self.assertRaises(OSError):
                driver._slot(3)

    def test_failed_duplicate_close_does_not_skip_lease_or_retry_number(self):
        attempt = self.attempt()
        attempt.duplicate = 7
        lease = SimpleNamespace(close=lambda: None)
        attempt.lease = lease
        with patch.object(driver.os, 'close', side_effect=OSError(errno.EIO, 'private')) as close, \
             patch.object(lease, 'close') as lease_close:
            attempt._close()
        close.assert_called_once_with(7)
        lease_close.assert_called_once_with()
        self.assertIsNone(attempt.duplicate)
        self.assertEqual(attempt.uncertain_resources[0][:2], ('duplicate-close', 7))
        # The integer loses retry authority, while the actual error stays referenced.
        self.assertIsInstance(attempt.uncertain_resources[0][2], OSError)

    def test_failed_lease_close_does_not_skip_former_slot_checks(self):
        attempt = self.attempt()
        error = OSError(errno.EIO, 'private')
        attempt.lease = SimpleNamespace(close=lambda: (_ for _ in ()).throw(error))
        attempt.former_slots = (5, 6)
        with patch.object(driver, '_slot', return_value=None) as slot:
            attempt._close()
        self.assertEqual([call.args[0] for call in slot.call_args_list], [5, 6])
        self.assertIs(attempt.uncertain_resources[0][1], attempt.lease)
        self.assertIs(attempt.uncertain_resources[0][2], error)

    def test_live_former_slot_is_retained_and_never_closed(self):
        attempt = self.attempt()
        attempt.former_slots = (5,)
        with patch.object(driver, '_slot', return_value=('reused',)), patch.object(driver.os, 'close') as close:
            attempt._close()
        close.assert_not_called()
        self.assertIn(('live-former-slot', 5), attempt.uncertain_resources)

    def test_unknown_inventory_slot_is_uncertainty_not_ignored(self):
        attempt = self.attempt()
        attempt.baseline = {0: ('stdio',)}
        with patch.object(driver, '_inventory', return_value={0: ('stdio',), 63: ('unknown',)}):
            attempt._close()
        self.assertEqual(attempt.uncertain_resources[0][0], 'inventory')

    def test_api_error_and_live_owner_remain_strongly_referenced(self):
        attempt = self.attempt()
        owner = object()
        error = RuntimeError('private message not reportable')
        error._mentat_worker_owner = owner
        attempt.errors.append(error)
        attempt.acquisition_started = True
        with patch.object(driver.sys, 'platform', 'unsupported'), \
             patch.object(driver.time, 'monotonic', return_value=101):
            raw = attempt.run()
        report = json.loads(raw)
        self.assertIs(attempt.errors[0]._mentat_worker_owner, owner)
        self.assertTrue(report['owner_retained'])
        self.assertTrue(report['session_must_remain_open'])
        self.assertFalse(report['cleanup_verified'])
        self.assertNotIn(b'private', raw)
        self.assertNotIn(b'/fixed-public-inputs', raw)

    def test_retained_uncertain_lease_prevents_success(self):
        attempt = self.attempt()
        owner = object()
        attempt.uncertain_resources.append(('lease', owner))
        with patch.object(driver.sys, 'platform', 'unsupported'), \
             patch.object(driver.time, 'monotonic', return_value=101):
            result = json.loads(attempt.run())
        self.assertFalse(result['qualification'])
        self.assertTrue(result['owner_retained'])
        self.assertIs(attempt.uncertain_resources[0][1], owner)

    def test_source_pin_wrong_size_refuses_before_read(self):
        attempt = self.attempt()
        value = SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1,
                                st_file_attributes=0, st_size=2)
        with patch.object(driver.time, 'monotonic', return_value=101), \
             patch.object(driver.Path, 'lstat', return_value=value), \
             patch.object(driver.os, 'open') as opened:
            with self.assertRaises(driver.QualificationRefused):
                attempt._read_pinned_file(Path('/fixed'), 3, expected_size=1)
        opened.assert_not_called()

    def inspected_candidate(self):
        # All kernel and API objects here are deliberate portable substitutes.
        raw = b'abc'
        digest = driver.hashlib.sha256(raw).hexdigest()
        helpers = ['usr/bin/bwrap', 'usr/bin/squashfuse', 'usr/bin/fusermount3', 'usr/bin/mksquashfs']
        paths = sorted(['/usr/lib/x86_64-linux-gnu/lib' + str(i) for i in range(13)]
                       + ['/' + value for value in helpers])
        classes = {name: 'compiled-helper-pin' if name.startswith('/usr/bin/')
                   else 'signed-library-archive' for name in paths}
        rows = tuple((name, 3, digest, classes[name]) for name in paths)
        class Lease:
            def __init__(self):
                self._descriptors = {name: (i + 3, 3) for i, name in enumerate(paths)}
                self.members = rows
                self.aliases = tuple(('/usr/lib/x86_64-linux-gnu/alias' + str(i),
                                      '/usr/lib/x86_64-linux-gnu/lib0') for i in range(10))
            def read(self, _member):
                return raw
        lease = Lease()
        custody = SimpleNamespace(FixedByteCustody=Lease, _CLASSES=classes)
        library = SimpleNamespace(plt=SimpleNamespace(_PROFILES={}),
                                  _library_path=lambda value, **_kwargs: value)
        origin = SimpleNamespace(PINS=tuple(SimpleNamespace(member=name, member_size=3,
                                                           member_digest=digest) for name in helpers))
        fake_fcntl = SimpleNamespace(F_GETFD=1, FD_CLOEXEC=1, F_DUPFD_CLOEXEC=2,
                                     fcntl=lambda _fd, command, *_args:
                                     15 if command == 1034 else 20 if command == 2 else 1)
        attempt = self.attempt()
        attempt.lease = lease
        attempt.baseline = {i: ('stdio',) for i in range(3)}
        offsets = [0]
        def seek(_fd, offset, operation):
            if operation == driver.os.SEEK_SET:
                offsets[0] = offset
            return offsets[0]
        return attempt, custody, library, origin, fake_fcntl, seek

    def test_positive_fixed_candidate_observation_with_explicit_os_substitutes(self):
        attempt, custody, library, origin, fcntl, seek = self.inspected_candidate()
        with patch.dict(sys.modules, {'fcntl': fcntl}), \
             patch.object(driver.time, 'monotonic', return_value=101), \
             patch.object(driver.os, 'fstat', side_effect=lambda fd: SimpleNamespace(
                 st_mode=stat.S_IFREG, st_size=3, st_dev=1, st_ino=fd)), \
             patch.object(driver.os, 'lseek', side_effect=seek), \
             patch.object(driver, '_slot', side_effect=lambda fd: ('stdio',) if fd < 3 else ('member', fd)), \
             patch.object(driver, '_inventory', return_value=attempt.baseline | {
                 fd: ('member', fd) for fd in range(3, 20)}):
            attempt._inspect(custody, library, origin)
        self.assertEqual(attempt.former_slots, tuple(range(3, 20)))
        self.assertEqual(attempt.duplicate, 20)

    def test_missing_kernel_seal_refuses_before_byte_read(self):
        attempt, custody, library, origin, fcntl, _seek = self.inspected_candidate()
        fcntl.fcntl = lambda _fd, command, *_args: 7 if command == 1034 else 1
        with patch.dict(sys.modules, {'fcntl': fcntl}), \
             patch.object(driver.time, 'monotonic', return_value=101), \
             patch.object(driver.os, 'fstat', return_value=SimpleNamespace(
                 st_mode=stat.S_IFREG, st_size=3, st_dev=1, st_ino=1)), \
             patch.object(attempt.lease, 'read') as read:
            with self.assertRaises(driver.QualificationRefused):
                attempt._inspect(custody, library, origin)
        read.assert_not_called()

    def test_wrong_fixed_trust_class_refuses(self):
        attempt, custody, library, origin, fcntl, _seek = self.inspected_candidate()
        rows = list(attempt.lease.members)
        row = rows[0]
        rows[0] = row[:3] + ('signed-library-archive',)
        attempt.lease.members = tuple(rows)
        with patch.dict(sys.modules, {'fcntl': fcntl}), \
             patch.object(driver.time, 'monotonic', return_value=101):
            with self.assertRaises(driver.QualificationRefused):
                attempt._inspect(custody, library, origin)

    def test_digest_mismatch_refuses(self):
        attempt, custody, library, origin, fcntl, _seek = self.inspected_candidate()
        with patch.dict(sys.modules, {'fcntl': fcntl}), \
             patch.object(driver.time, 'monotonic', return_value=101), \
             patch.object(driver.os, 'fstat', side_effect=lambda fd: SimpleNamespace(
                 st_mode=stat.S_IFREG, st_size=3, st_dev=1, st_ino=fd)), \
             patch.object(attempt.lease, 'read', return_value=b'abd'):
            with self.assertRaises(driver.QualificationRefused):
                attempt._inspect(custody, library, origin)

    def test_writable_prepared_source_directory_refuses(self):
        attempt = self.attempt()
        directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0)
        with patch.object(driver.time, 'monotonic', return_value=101), \
             patch.object(driver.Path, 'lstat', return_value=directory):
            with self.assertRaises(driver.QualificationRefused):
                attempt._source_layout()

    def test_cache_and_extension_shadow_refuse_without_loading_project_code(self):
        attempt = self.attempt()
        directory = SimpleNamespace(st_dev=1, st_ino=1, st_mode=stat.S_IFDIR | 0o555,
                                    st_uid=1, st_nlink=1, st_size=0, st_mtime_ns=0,
                                    st_ctime_ns=0, st_file_attributes=0)
        pins = (('mentat/__init__.py', 1, 'a' * 40),)
        for suffix in ('__pycache__', '__init__.pyc', '__init__.pyo', '__init__.so', 'mentat.so'):
            with self.subTest(forbidden=suffix):
                def details(path):
                    if path == attempt.source_root / 'mentat':
                        return directory
                    if path.name == suffix:
                        return directory
                    raise FileNotFoundError()
                with patch.object(driver, 'SOURCE_BLOBS', pins), \
                     patch.object(driver.time, 'monotonic', return_value=101), \
                     patch('importlib.machinery.EXTENSION_SUFFIXES', ['.so']), \
                     patch.object(driver.Path, 'lstat', details):
                    with self.assertRaises(driver.QualificationRefused):
                        attempt._source_layout()
