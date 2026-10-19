"""Portable ownership tests. Credentials and Linux seals are explicitly substituted.

No helper, decoder, signature utility, library or production worker is executed.
"""
import array
from dataclasses import replace
from copy import deepcopy
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import socket
import struct
from tempfile import TemporaryFile, TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mentat import project_helper_byte_custody as custody
from mentat import project_library_origin as library
from mentat import project_system_origin as origin

posix_descriptors = unittest.skipUnless(
    os.name == 'posix' and hasattr(os, 'pread'),
    'Actual POSIX descriptor reads/private capture fixture required')


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
                            ("SCM_RIGHTS", 1), ("MSG_TRUNC", 32), ("MSG_CTRUNC", 8),
                            ("SOCK_CLOEXEC", 0x80000),
                            ("MSG_CMSG_CLOEXEC", 0x40000000)):
            stack.enter_context(patch.object(socket, name, getattr(socket, name, value), create=True))
        if not hasattr(socket, 'CMSG_SPACE'):
            stack.enter_context(patch.object(socket, 'CMSG_SPACE', lambda size: size + 16, create=True))
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

    @posix_descriptors
    def test_actual_parent_flow_publishes_only_after_normal_closure_and_closes_partial_handoff(self):
        for fail_at in (None, 7, 'normal', 'close-before', 'close-after'):
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
                            wrong = index == fail_at or (isinstance(fail_at, str) and fail_at.startswith('close-') and index == 7)
                            return (-1 if wrong else index), descriptor
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
                real_close = os.close
                close_calls = []
                def close(descriptor):
                    if isinstance(fail_at, str) and fail_at.startswith('close-') and delivered and descriptor == delivered[0]:
                        close_calls.append(descriptor)
                        if fail_at == 'close-after':
                            real_close(descriptor)
                        raise OSError('injected ambiguous close')
                    real_close(descriptor)
                if isinstance(fail_at, str) and fail_at.startswith('close-'):
                    stack.enter_context(patch.object(os, 'close', side_effect=close))
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
                self.assertEqual(events[-1], 'CLOSED')
                for descriptor in delivered:
                    if fail_at == 'close-before' and descriptor == delivered[0]:
                        os.fstat(descriptor)
                        real_close(descriptor)
                        continue
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)
                if isinstance(fail_at, str) and fail_at.startswith('close-'):
                    self.assertEqual(close_calls, [delivered[0]])

    @posix_descriptors
    def test_fixed_manifest_wrong_class_is_refused_before_any_transfer(self):
        with ExitStack() as stack:
            manifest, _files = self.parent_fixture(stack)
            custody._manifest(manifest)
            changed = deepcopy(manifest)
            changed['rows'][0][5] = ('compiled-helper-pin' if changed['rows'][0][5] == 'signed-library-archive'
                                     else 'signed-library-archive')
            with self.assertRaises(custody.ByteCustodyError):
                custody._manifest(changed)

    @posix_descriptors
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

    @posix_descriptors
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
            peer = (123, 1000, 1000)  # Substituted kernel credentials, not host IDs.
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

    @posix_descriptors
    def test_lease_close_uncertainty_keeps_evidence_and_never_retries_reused_number(self):
        for after in (False, True):
            with self.subTest(after=after), TemporaryFile() as source, TemporaryFile() as replacement:
                source.write(b'public'); source.flush()
                first, second = os.dup(source.fileno()), os.dup(source.fileno())
                row = self.row(first)
                other = list(row); other[0] = 'other'
                lease = custody.FixedByteCustody({row[0]: (first, row[1]), 'other': (second, row[1])}, [row, other], [])
                real_close = os.close
                calls = []
                def close(descriptor):
                    calls.append(descriptor)
                    if descriptor == first:
                        if after:
                            real_close(descriptor)
                            os.dup2(replacement.fileno(), descriptor)
                        raise OSError('injected before/after close')
                    real_close(descriptor)
                with patch.object(os, 'close', side_effect=close):
                    for _attempt in range(2):
                        with self.assertRaises(custody.ByteCustodyError) as failure:
                            lease.close()
                        self.assertIs(failure.exception._mentat_custody_owner, lease)
                    self.assertEqual(calls, [first, second])
                os.fstat(first)  # Still owned or numerically reused; never retried.
                with self.assertRaises(OSError):
                    os.fstat(second)
                real_close(first)

    def test_channel_close_error_attempts_later_rights_and_preserves_uncertainty(self):
        with self.kernel_substitutions(), TemporaryFile() as source:
            first, second = os.dup(source.fileno()), os.dup(source.fileno())
            controls = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [first, second]).tobytes())]
            channel = custody._Channel(Endpoint((b'bad', controls, socket.MSG_CTRUNC, None)), (1, 2, 3), 'n', time.monotonic()+1)
            real_close = os.close
            def close(descriptor):
                if descriptor == first:
                    real_close(descriptor)
                    raise OSError('injected after close')
                real_close(descriptor)
            with patch.object(os, 'close', side_effect=close):
                with self.assertRaises(custody.ByteCustodyError) as failure:
                    channel.receive('MEMBER', rights=True)
            self.assertIs(failure.exception._mentat_custody_owner, channel)
            for descriptor in (first, second):
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_pidfd_close_error_cannot_retry_reused_descriptor(self):
        with TemporaryFile() as replacement, TemporaryFile() as source:
            descriptor = os.dup(source.fileno())
            owner = custody._OwnedWorker(SimpleNamespace(pid=123))
            owner.reaped, owner.pidfd = True, descriptor
            real_close = os.close
            calls = []
            def close(number):
                calls.append(number)
                real_close(number)
                os.dup2(replacement.fileno(), number)
                raise OSError('injected reused pidfd')
            with patch.object(owner, 'absent'), patch.object(os, 'close', side_effect=close):
                for _attempt in range(2):
                    with self.assertRaises(custody.ByteCustodyError):
                        owner.close()
            self.assertEqual(calls, [descriptor])
            os.fstat(descriptor)
            real_close(descriptor)

    def test_normal_exit_reap_group_absence_order_without_any_signal(self):
        owner = custody._OwnedWorker.__new__(custody._OwnedWorker)
        owner.process = SimpleNamespace(pid=123, returncode=None)
        owner.pidfd, owner.reaped, owner.ticks = 10, False, 77
        terminal = SimpleNamespace(si_code=getattr(os, 'CLD_EXITED', 1), si_status=0)
        with patch.object(owner, 'terminal', return_value=terminal), patch.object(os, 'waitpid', return_value=(123, 0)), \
                patch.object(os, 'CLD_EXITED', terminal.si_code, create=True), \
                patch.object(os, 'killpg', side_effect=ProcessLookupError, create=True) as group:
            owner.normal(time.monotonic()+1)
            self.assertTrue(owner.reaped)
            group.assert_called_once_with(123, 0)

    def test_ready_then_crash_or_nonzero_never_reaps_as_success(self):
        owner = custody._OwnedWorker.__new__(custody._OwnedWorker)
        for code, status in ((getattr(os, 'CLD_KILLED', 2), 9), (getattr(os, 'CLD_EXITED', 1), 1)):
            with patch.object(owner, 'terminal', return_value=SimpleNamespace(si_code=code, si_status=status)), \
                    patch.object(os, 'CLD_EXITED', getattr(os, 'CLD_EXITED', 1), create=True), \
                    patch.object(owner, '_reap') as reap:
                with self.assertRaises(custody.ByteCustodyError):
                    owner.normal(time.monotonic()+1)
                reap.assert_not_called()

    def test_descendant_or_reused_group_after_normal_exit_retains_uncertainty_no_signals(self):
        owner = custody._OwnedWorker.__new__(custody._OwnedWorker)
        owner.process = SimpleNamespace(pid=123, returncode=0)
        owner.pidfd, owner.reaped, owner.ticks = 10, True, 77
        with patch.object(os, 'killpg', return_value=None, create=True) as group, patch.object(os, 'close') as close:
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
        with patch.object(custody.signal, 'SIGKILL', getattr(custody.signal, 'SIGKILL', 9), create=True), \
                patch.object(custody, 'linux_process_start_ticks', return_value=77), \
                patch.object(os, 'getpgid', return_value=123, create=True), \
                patch.object(owner, 'terminal', return_value=object()), \
                patch.object(os, 'waitpid', return_value=(123, 0)), patch.object(os, 'killpg', side_effect=group, create=True), \
                patch.object(os, 'close'):
            owner.close()
        self.assertEqual(signals, [custody.signal.SIGTERM, 9])
        owner.process.poll.assert_not_called()
        owner.process.wait.assert_not_called()

    def test_changed_leader_identity_has_no_signal_authority(self):
        owner = custody._OwnedWorker.__new__(custody._OwnedWorker)
        owner.process, owner.pidfd, owner.reaped, owner.ticks = SimpleNamespace(pid=123), 10, False, 77
        with patch.object(custody, 'linux_process_start_ticks', return_value=78), patch.object(os, 'killpg', create=True) as group:
            with self.assertRaises(custody.ByteCustodyError):
                owner.close()
            group.assert_not_called()

    @posix_descriptors
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

    @posix_descriptors
    def test_worker_real_capture_sealed_reads_graph_ack_cleanup_and_descriptor_peak(self):
        """OS signature/decoder, seals, credentials and limits are substituted.

        The complete existing fixture still performs real private capture,
        signed-text/index grammar, tar/ELF/shared graph checks and FD reads.
        """
        import fcntl
        import resource
        from tests.test_project_library_origin import LibraryOriginTests
        for failure in (None, 'graph', 'partial-ack', False, 0.0, 'close-before', 'close-after'):
            with self.subTest(failure=repr(failure)), TemporaryDirectory() as temporary, ExitStack() as stack:
                root, complete = LibraryOriginTests().complete_fixture(temporary, custody_layout=True)
                stack.enter_context(complete)
                deadline = time.monotonic() + 10
                endpoint, events, descriptors, peaks = Endpoint(), [], [], []
                # One real reserved descriptor represents the substituted channel.
                stack.enter_context(TemporaryFile())
                fd_directory = '/dev/fd' if os.path.isdir('/dev/fd') else '/proc/self/fd'
                baseline = len(os.listdir(fd_directory))
                original_seal = origin._sealed
                archive_hashes = {pin.archive_digest for pin in library.PINS}
                def sealed(raw):
                    if library._sha(raw) in archive_hashes:
                        return original_seal(raw)
                    with TemporaryFile() as source:
                        source.write(raw); source.flush()
                        descriptor = os.dup(source.fileno())
                    descriptors.append(descriptor)
                    peaks.append(len(os.listdir(fd_directory)))
                    return descriptor
                original_selection = library._verified_selection
                @contextmanager
                def selected(*args):
                    with original_selection(*args) as value:
                        if failure == 'graph':
                            value[0]['helper_closures'][0][1] = '0' * 64
                        yield value
                    events.append('SOURCE_REVALIDATED')
                test = self
                class Channel:
                    def __init__(self, *_args):
                        self.index = 0
                    def receive(self, kind):
                        if kind == 'START':
                            return {'root': str(root), 'deadline': deadline}
                        if kind == 'MEMBER_ACK':
                            index = self.index
                            self.index += 1
                            if failure == 'partial-ack' and index == 7:
                                return -1
                            if (type(failure) is bool or type(failure) is float) and index == 0:
                                return failure
                            return index
                        return self.digest
                    def send(self, kind, value, descriptor=None):
                        events.append(kind)
                        if kind == 'MANIFEST':
                            self.digest = library._sha(custody._wire(value))
                            test.assertEqual(sum(row[5] == 'signed-library-archive' for row in value['rows']), 13)
                            test.assertEqual(sum(row[5] == 'compiled-helper-pin' for row in value['rows']), 4)
                        if kind == 'READY':
                            test.assertEqual(events[-2], 'SOURCE_REVALIDATED')
                stack.enter_context(patch.object(origin, '_sealed', side_effect=sealed))
                stack.enter_context(patch.object(library, '_verified_selection', side_effect=selected))
                stack.enter_context(patch.object(fcntl, 'fcntl', return_value=15))
                stack.enter_context(patch.object(resource, 'setrlimit'))
                stack.enter_context(patch.object(custody, '_supported', return_value=True))
                stack.enter_context(patch.object(custody, '_Channel', Channel))
                stack.enter_context(patch.object(os, 'getppid', return_value=123))
                stack.enter_context(patch.object(custody.sys, 'argv', ['worker', '100', '123', 'a'*64, str(deadline)]))
                real_close = os.close
                failed_closes = []
                def close(descriptor):
                    if isinstance(failure, str) and failure.startswith('close-') and descriptors and descriptor == descriptors[0]:
                        failed_closes.append(descriptor)
                        if failure == 'close-after':
                            real_close(descriptor)
                        raise OSError('injected worker close uncertainty')
                    real_close(descriptor)
                if isinstance(failure, str) and failure.startswith('close-'):
                    stack.enter_context(patch.object(os, 'close', side_effect=close))
                if failure is None:
                    custody._worker(endpoint)
                    self.assertIn('READY', events)
                else:
                    with self.assertRaises(custody.ByteCustodyError):
                        custody._worker(endpoint)
                    self.assertNotIn('READY', events)
                self.assertTrue(endpoint.closed)
                self.assertEqual(len(descriptors), 17)
                # Real private capture contributes20 FD and sealing adds17.
                # Four represents worker stdio plus the reserved channel.
                self.assertGreaterEqual(max(peaks) - baseline, 37)
                self.assertLessEqual(max(peaks) - baseline + 4, 64)
                for descriptor in descriptors:
                    if failure == 'close-before' and descriptor == descriptors[0]:
                        os.fstat(descriptor)
                        real_close(descriptor)
                        continue
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)
                if isinstance(failure, str) and failure.startswith('close-'):
                    self.assertEqual(failed_closes, [descriptors[0]])
