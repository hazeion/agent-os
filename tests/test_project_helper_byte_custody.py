"""Portable ownership tests. Credentials and Linux seals are explicitly substituted.

No helper, decoder, signature utility, library or production worker is executed.
"""
import array
from dataclasses import replace
from copy import deepcopy
from contextlib import ExitStack
import os
from pathlib import Path
import socket
import struct
from tempfile import TemporaryFile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mentat import project_helper_byte_custody as custody
from mentat import project_library_origin as library
from mentat import project_system_origin as origin


class Endpoint:
    def __init__(self, packet=None):
        self.packet = packet
        self.closed = False
    def setblocking(self, _value):
        pass
    def setsockopt(self, *_args):
        pass
    def fileno(self):
        return 100
    def recvmsg(self, *_args):
        return self.packet
    def close(self):
        self.closed = True
    def shutdown(self, _kind):
        pass


class CustodyTests(unittest.TestCase):
    def parent_fixture(self, stack):
        rows, library_rows, files, aliases = [], [], [], []
        helpers = []
        for path in sorted(custody._CLASSES):
            source = stack.enter_context(TemporaryFile())
            source.write(path.encode()); source.flush()
            row = self.row(source.fileno(), path)
            files.append(source)
            rows.append(row)
            if row[5] == 'signed-library-archive':
                library_rows.append([path, row[2], row[1]])
            else:
                pin = next(pin for pin in origin.PINS if '/' + pin.member == path)
                helpers.append(replace(pin, member_size=row[1], member_digest=row[2]))
        for index in range(10):
            aliases.append([library.LIB + 'alias' + str(index), 'libc.so.6'])
        report = {'members': library_rows, 'aliases': aliases}
        stack.enter_context(patch.object(origin, 'PINS', tuple(helpers)))
        # This fixture substitutes an authenticated worker report and kernel
        # seal observations; real descriptors, reads and parent ownership run.
        stack.enter_context(patch.object(library, '_valid_report', return_value=True))
        import fcntl
        stack.enter_context(patch.object(fcntl, 'fcntl', return_value=15))
        return {'report': report, 'rows': rows, 'aliases': aliases}, files

    def kernel_substitutions(self):
        stack = ExitStack()
        for name, value in (("SCM_CREDENTIALS", 2), ("SO_PASSCRED", 16),
                            ("SOCK_CLOEXEC", 0x80000),
                            ("MSG_CMSG_CLOEXEC", 0x40000000)):
            stack.enter_context(patch.object(socket, name, getattr(socket, name, value), create=True))
        return stack

    def row(self, descriptor, path=None):
        details = os.fstat(descriptor)
        path = path or next(iter(custody._CLASSES))
        raw = os.pread(descriptor, details.st_size, 0)
        return [path, len(raw), library._sha(raw), details.st_dev, details.st_ino, custody._CLASSES[path]]

    def test_unsupported_host_refuses_before_socket_or_spawn(self):
        with patch.object(custody, '_supported', return_value=False), patch.object(socket, 'socketpair') as pair:
            with self.assertRaises(custody.ByteCustodyError):
                custody.acquire_fixed_helper_bytes(Path('/public'))
            pair.assert_not_called()

    def test_actual_parent_flow_publishes_only_after_normal_closure_and_closes_partial_handoff(self):
        for fail_at in (None, 7, 'normal'):
            with self.subTest(fail_at=fail_at), ExitStack() as stack, self.kernel_substitutions():
                manifest, files = self.parent_fixture(stack)
                endpoint, child = Endpoint(), Endpoint()
                delivered = []
                events = []
                class Channel:
                    def __init__(self, *_args):
                        self.index = 0
                    def send(self, kind, _value):
                        events.append(kind)
                    def receive(self, kind, **_kwargs):
                        if kind == 'MANIFEST':
                            return manifest
                        if kind == 'MEMBER':
                            descriptor = os.dup(files[self.index].fileno())
                            delivered.append(descriptor)
                            index = self.index
                            self.index += 1
                            return (-1 if index == fail_at else index), descriptor
                        if kind == 'READY':
                            return library._sha(custody._wire(manifest))
                        return None
                class Owner:
                    def __init__(self, _process):
                        self.pidfd = 100
                    def pin(self):
                        pass
                    def normal(self, _deadline):
                        events.append('NORMAL')
                        if fail_at == 'normal':
                            raise custody.ByteCustodyError()
                    def close(self):
                        events.append('CLOSED')
                        self.pidfd = None
                for target, name, value in (
                        (custody, '_supported', True),
                        (custody, 'linux_process_start_ticks', 77),
                        (socket, 'socketpair', (endpoint, child)),
                        (custody.subprocess, 'Popen', SimpleNamespace(pid=123)),
                        (os, 'pidfd_open', 100)):
                    stack.enter_context(patch.object(target, name, return_value=value, create=True))
                stack.enter_context(patch.object(custody, '_Channel', Channel))
                stack.enter_context(patch.object(custody, '_OwnedWorker', Owner))
                if fail_at is None:
                    lease = custody.acquire_fixed_helper_bytes(Path('/public'))
                    self.assertEqual(events[-2:], ['NORMAL', 'CLOSED'])
                    self.assertEqual(len(lease.members), 17)
                    self.assertEqual(len(lease.aliases), 10)
                    self.assertEqual(lease.read(manifest['rows'][0][0]), manifest['rows'][0][0].encode())
                    lease.close()
                else:
                    with self.assertRaises(custody.ByteCustodyError):
                        custody.acquire_fixed_helper_bytes(Path('/public'))
                self.assertTrue(endpoint.closed and child.closed)
                for descriptor in delivered:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_fixed_manifest_wrong_class_is_refused_before_any_transfer(self):
        with ExitStack() as stack:
            manifest, _files = self.parent_fixture(stack)
            custody._manifest(manifest)
            changed = deepcopy(manifest)
            changed['rows'][0][5] = ('compiled-helper-pin' if changed['rows'][0][5] == 'signed-library-archive'
                                     else 'signed-library-archive')
            with self.assertRaises(custody.ByteCustodyError):
                custody._manifest(changed)

    def test_real_received_byte_read_ignores_shared_offset_and_close_is_idempotent(self):
        with TemporaryFile() as source:
            source.write(b'public fixed bytes'); source.flush()
            descriptor = os.dup(source.fileno())
            row = self.row(descriptor)
            lease = custody.FixedByteCustody({row[0]: (descriptor, row[1])}, [row], [])
            os.lseek(source.fileno(), 5, os.SEEK_SET)
            self.assertEqual(lease.read(row[0]), b'public fixed bytes')
            self.assertEqual(os.lseek(source.fileno(), 0, os.SEEK_CUR), 5)
            self.assertEqual(lease.members[0][-1], 'signed-library-archive')
            lease.close(); lease.close()
            with self.assertRaises(OSError):
                os.fstat(descriptor)
            with self.assertRaises(custody.ByteCustodyError):
                lease.read(row[0])

    def test_object_rejects_wrong_class_size_hash_identity_and_missing_substituted_seal(self):
        import fcntl
        with TemporaryFile() as source:
            source.write(b'public'); source.flush()
            row = self.row(source.fileno())
            with patch.object(fcntl, 'fcntl', return_value=15):
                self.assertEqual(custody._object(source.fileno(), row, time.monotonic()+1), b'public')
                for index, wrong in ((1, row[1]+1), (2, '0'*64), (4, row[4]+1), (5, 'compiled-helper-pin')):
                    changed = list(row); changed[index] = wrong
                    with self.subTest(index=index), self.assertRaises(custody.ByteCustodyError):
                        custody._object(source.fileno(), changed, time.monotonic()+1)
            with patch.object(fcntl, 'fcntl', return_value=7), self.assertRaises(custody.ByteCustodyError):
                custody._object(source.fileno(), row, time.monotonic()+1)
            with self.assertRaises(custody.ByteCustodyError):
                custody._read(source.fileno(), row[1], time.monotonic()-1)

    def test_received_right_is_closed_for_foreign_peer_truncation_extra_rights_and_bad_frame(self):
        with self.kernel_substitutions(), TemporaryFile() as source:
            peer = (123, os.getuid(), os.getgid())
            good = {'version': 1, 'nonce': 'n', 'sequence': 0, 'kind': 'MEMBER', 'value': 0}
            for failure in ('peer', 'truncated', 'extra', 'nonce', 'sequence', 'duplicate-json', 'kind'):
                descriptors = [os.dup(source.fileno()) for _ in range(2 if failure == 'extra' else 1)]
                frame = dict(good)
                if failure in ('nonce', 'sequence', 'kind'):
                    frame[failure] = 'wrong'
                raw = custody._wire(frame)
                if failure == 'duplicate-json':
                    raw = raw[:-1] + b',"kind":"MEMBER"}'
                controls = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', descriptors).tobytes()),
                            (socket.SOL_SOCKET, socket.SCM_CREDENTIALS,
                             struct.pack('3i', *((999, peer[1], peer[2]) if failure == 'peer' else peer)))]
                endpoint = Endpoint((raw, controls, socket.MSG_CTRUNC if failure == 'truncated' else 0, None))
                channel = custody._Channel(endpoint, peer, 'n', time.monotonic()+1)
                with self.subTest(failure=failure), self.assertRaises(custody.ByteCustodyError):
                    channel.receive('MEMBER', rights=True)
                for descriptor in descriptors:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_eof_rejects_extra_packet_or_right_and_closes_delivered_right(self):
        with self.kernel_substitutions(), TemporaryFile() as source:
            descriptor = os.dup(source.fileno())
            controls = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [descriptor]).tobytes())]
            channel = custody._Channel(Endpoint((b'late', controls, 0, None)), (1, 2, 3), 'n', time.monotonic()+1)
            with self.assertRaises(custody.ByteCustodyError):
                channel.receive(None, eof=True)
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_normal_exit_reap_group_absence_order_without_any_signal(self):
        owner = custody._OwnedWorker.__new__(custody._OwnedWorker)
        owner.process = SimpleNamespace(pid=123, returncode=None)
        owner.pidfd, owner.reaped, owner.ticks = 10, False, 77
        terminal = SimpleNamespace(si_code=getattr(os, 'CLD_EXITED', 1), si_status=0)
        with patch.object(owner, 'terminal', return_value=terminal), patch.object(os, 'waitpid', return_value=(123, 0)), \
                patch.object(os, 'killpg', side_effect=ProcessLookupError) as group:
            owner.normal(time.monotonic()+1)
            self.assertTrue(owner.reaped)
            group.assert_called_once_with(123, 0)

    def test_ready_then_crash_or_nonzero_never_reaps_as_success(self):
        owner = custody._OwnedWorker.__new__(custody._OwnedWorker)
        for code, status in ((getattr(os, 'CLD_KILLED', 2), 9), (getattr(os, 'CLD_EXITED', 1), 1)):
            with patch.object(owner, 'terminal', return_value=SimpleNamespace(si_code=code, si_status=status)), \
                    patch.object(owner, '_reap') as reap:
                with self.assertRaises(custody.ByteCustodyError):
                    owner.normal(time.monotonic()+1)
                reap.assert_not_called()

    def test_descendant_or_reused_group_after_normal_exit_retains_uncertainty_no_signals(self):
        owner = custody._OwnedWorker.__new__(custody._OwnedWorker)
        owner.process = SimpleNamespace(pid=123, returncode=0)
        owner.pidfd, owner.reaped, owner.ticks = 10, True, 77
        with patch.object(os, 'killpg', return_value=None) as group, patch.object(os, 'close') as close:
            with self.assertRaises(custody.ByteCustodyError) as failure:
                owner.close()
            self.assertIs(failure.exception._mentat_worker_owner, owner)
            group.assert_called_once_with(123, 0)
            close.assert_not_called()

    def test_failure_signals_only_while_original_leader_pinned_and_no_popen_poll(self):
        owner = custody._OwnedWorker.__new__(custody._OwnedWorker)
        owner.process = Mock(pid=123, returncode=None)
        owner.pidfd, owner.reaped, owner.ticks = 10, False, 77
        signals = []
        def group(_pid, kind):
            if kind:
                self.assertFalse(owner.reaped)
                signals.append(kind)
            else:
                self.assertTrue(owner.reaped)
                raise ProcessLookupError()
        with patch.object(custody, 'linux_process_start_ticks', return_value=77), \
                patch.object(os, 'getpgid', return_value=123), \
                patch.object(owner, 'terminal', return_value=object()), \
                patch.object(os, 'waitpid', return_value=(123, 0)), patch.object(os, 'killpg', side_effect=group), \
                patch.object(os, 'close'):
            owner.close()
        self.assertEqual(signals, [custody.signal.SIGTERM, custody.signal.SIGKILL])
        owner.process.poll.assert_not_called()
        owner.process.wait.assert_not_called()

    def test_changed_leader_identity_has_no_signal_authority(self):
        owner = custody._OwnedWorker.__new__(custody._OwnedWorker)
        owner.process, owner.pidfd, owner.reaped, owner.ticks = SimpleNamespace(pid=123), 10, False, 77
        with patch.object(custody, 'linux_process_start_ticks', return_value=78), patch.object(os, 'killpg') as group:
            with self.assertRaises(custody.ByteCustodyError):
                owner.close()
            group.assert_not_called()

    def test_retained_origin_context_is_same_bytes_and_revalidates_on_exit(self):
        from tests.test_project_library_origin import LibraryOriginTests
        from tempfile import TemporaryDirectory
        fixture = LibraryOriginTests()
        with TemporaryDirectory() as temporary:
            root, stack = fixture.complete_fixture(temporary)
            with stack, library._verified_selection(root, time.monotonic()+5) as (report, members, owners):
                for pin in origin.PINS:
                    path = '/' + pin.member
                    self.assertEqual(library._sha(members[path]), pin.member_digest)
                    self.assertNotIn(path, owners)
                self.assertEqual(len(report['helper_closures']), 4)
