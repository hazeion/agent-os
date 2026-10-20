"""Current-only retries use real retained resources; archival reads stay strict."""
from contextlib import closing
import ctypes
import os
from pathlib import Path
import stat
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import data_layout
import mentat_db as db


class CurrentSnapshotRetryTests(unittest.TestCase):
    def current(self, root):
        connection = db.connect(root)
        connection.execute('PRAGMA wal_autocheckpoint=0')
        connection.execute("UPDATE mentat_project_context_access_state SET approval_epoch=?", (b'x' * 32,))
        return connection

    def checkpoint_read(self, root, writer, original, observed):
        identity = db.database_path(root).stat()
        def read(descriptor, count):
            raw = original(descriptor, count)
            held = os.fstat(descriptor)
            if raw and not observed and (held.st_dev, held.st_ino) == (identity.st_dev, identity.st_ino):
                before = db.database_path(root).read_bytes()
                result = writer.execute('PRAGMA wal_checkpoint(FULL)').fetchone()
                self.assertEqual(result[0], 0)
                self.assertNotEqual(db.database_path(root).read_bytes(), before)
                self.assertEqual((held.st_dev, held.st_ino), (db.database_path(root).stat().st_dev, db.database_path(root).stat().st_ino))
                observed.append(descriptor)
            return raw
        return read

    def test_real_checkpoint_during_main_read_retries_each_current_entry(self):
        for entry in ('validate', 'connect', 'readonly'):
            with self.subTest(entry=entry), TemporaryDirectory() as temporary:
                root = Path(temporary) / 'data'
                with closing(self.current(root)) as writer:
                    observed = []
                    read = self.checkpoint_read(root, writer, os.read, observed)
                    with patch.object(db.os, 'read', side_effect=read), patch.object(db.time, 'sleep') as pause:
                        if entry == 'validate':
                            self.assertTrue(db.validate_current_database_root(root))
                        elif entry == 'connect':
                            with closing(db.connect(root)) as connection:
                                self.assertEqual(connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state').fetchone()[0], b'x' * 32)
                        else:
                            with db.connect_current_readonly(root) as connection:
                                self.assertEqual(connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state').fetchone()[0], b'x' * 32)
                    self.assertEqual(len(observed), 1)
                    self.assertEqual(pause.call_count, 1)
                    with self.assertRaises(OSError):
                        os.fstat(observed[0])

    def test_archival_raw_read_does_not_retry_the_same_real_checkpoint(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'
            with closing(self.current(root)) as writer:
                path = db.database_path(root); details = path.stat(); observed = []
                read = self.checkpoint_read(root, writer, os.read, observed)
                with patch.object(db.os, 'read', side_effect=read), patch.object(db.time, 'sleep') as pause:
                    with self.assertRaises(db.MentatDatabaseError) as refused:
                        db._read_existing_database_file(path, (details.st_dev, details.st_ino), db.MAX_READONLY_DATABASE_BYTES)
                self.assertNotIsInstance(refused.exception, db._TransientCurrentSnapshotRace)
                pause.assert_not_called()
                self.assertEqual(len(observed), 1)

    @unittest.skipUnless(os.name == 'posix', 'Actual POSIX hostile rename/mode/link fixtures')
    def test_unsafe_metadata_and_directory_changes_never_retry(self):
        for change in ('mode', 'hardlink', 'replacement', 'root', 'private', 'console', 'directory_mode'):
            with self.subTest(change=change), TemporaryDirectory() as temporary:
                root = Path(temporary) / 'data'
                with closing(self.current(root)) as writer:
                    path = db.database_path(root); identity = path.stat(); changed = []
                    original = os.read
                    def read(descriptor, count):
                        raw = original(descriptor, count)
                        held = os.fstat(descriptor)
                        if raw and not changed and (held.st_dev, held.st_ino) == (identity.st_dev, identity.st_ino):
                            changed.append(True)
                            # A simultaneous safe content change must not mask hostile metadata.
                            writer.execute('PRAGMA wal_checkpoint(FULL)').fetchone()
                            if change == 'mode': path.chmod(0o640)
                            elif change == 'hardlink': os.link(path, root / 'outside-link')
                            elif change == 'replacement':
                                replacement = root / 'new-main'; replacement.write_bytes(path.read_bytes()); replacement.chmod(0o600); replacement.replace(path)
                            elif change == 'directory_mode': path.parent.chmod(0o750)
                            else:
                                directory = {'root': root, 'private': root / 'private', 'console': path.parent}[change]
                                moved = Path(temporary) / 'moved'; directory.rename(moved); directory.mkdir(mode=0o700)
                                for child in list(moved.iterdir()): child.rename(directory / child.name)
                        return raw
                    with patch.object(db.os, 'read', side_effect=read), patch.object(db.time, 'sleep') as pause:
                        with self.assertRaises(db.MentatDatabaseError) as refused:
                            db.validate_current_database_root(root)
                    self.assertNotIsInstance(refused.exception, db._TransientCurrentSnapshotRace)
                    pause.assert_not_called()
                    self.assertTrue(changed)

    @unittest.skipUnless(os.name == 'posix', 'Actual POSIX replacement while pins remain held')
    def test_replacement_during_original_retry_pause_cannot_rebind(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'
            with closing(self.current(root)) as writer:
                observed = []; read = self.checkpoint_read(root, writer, os.read, observed)
                def replace(_seconds):
                    for descriptor in observed: self.assertGreaterEqual(os.fstat(descriptor).st_nlink, 1)
                    moved = Path(temporary) / 'old-console'; console = db.database_path(root).parent
                    console.rename(moved); console.mkdir(mode=0o700)
                    for child in list(moved.iterdir()): child.rename(console / child.name)
                with patch.object(db.os, 'read', side_effect=read), patch.object(db.time, 'sleep', side_effect=replace) as pause:
                    with self.assertRaises(db.MentatDatabaseError) as refused: db.validate_current_database_root(root)
                self.assertNotIsInstance(refused.exception, db._TransientCurrentSnapshotRace)
                self.assertEqual(pause.call_count, 1)

    @unittest.skipUnless(os.name == 'posix', 'Actual POSIX removal while main descriptor remains pinned')
    def test_main_removed_during_pause_never_becomes_fresh_or_bootstraps(self):
        for entry in ('validate', 'connect'):
            with self.subTest(entry=entry), TemporaryDirectory() as temporary:
                root = Path(temporary) / 'data'
                with closing(self.current(root)) as writer:
                    observed = []; read = self.checkpoint_read(root, writer, os.read, observed)
                    def remove(_seconds):
                        path = db.database_path(root)
                        for selected in (path, Path(str(path) + '-wal'), Path(str(path) + '-shm')):
                            selected.unlink(missing_ok=True)
                    with patch.object(db.os, 'read', side_effect=read), patch.object(db.time, 'sleep', side_effect=remove) as pause:
                        with self.assertRaises(db.MentatDatabaseError):
                            if entry == 'validate': db.validate_current_database_root(root)
                            else: db.connect(root)
                    self.assertEqual(pause.call_count, 1)
                    self.assertFalse(db.database_path(root).exists())

    def test_safe_content_churn_exhausts_existing_three_attempts_only(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'
            with closing(self.current(root)):
                original = db._read_existing_database_file; captures = []
                def unstable(path, *args, **kwargs):
                    raw = original(path, *args, **kwargs)
                    resources = kwargs['current_resources']; self.assertIsNotNone(resources.main)
                    details = path.stat(); os.utime(path, ns=(details.st_atime_ns, details.st_mtime_ns + 1))
                    captures.append(resources.main[1]); return raw
                with patch.object(db, '_read_existing_database_file', side_effect=unstable), patch.object(db.time, 'sleep') as pause:
                    with self.assertRaisesRegex(db.MentatDatabaseError, 'content changed'): db.validate_current_database_root(root)
                self.assertEqual(len(captures), 3); self.assertEqual(len(set(captures)), 1)
                self.assertEqual(pause.call_args_list, [unittest.mock.call(db.DATABASE_OPEN_RETRY_SECONDS)] * 2)
                with self.assertRaises(OSError): os.fstat(captures[0])

    def test_combined_quota_is_permanent_even_with_safe_main_change(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'
            with closing(self.current(root)) as writer:
                original = db._read_wal_prefix
                def checkpoint(*args):
                    raw = original(*args); writer.execute('PRAGMA wal_checkpoint(FULL)').fetchone(); return raw
                with patch.object(db, '_read_wal_prefix', side_effect=checkpoint), patch.object(db, 'MAX_READONLY_SNAPSHOT_BYTES', 1), patch.object(db.time, 'sleep') as pause:
                    with self.assertRaises(db.MentatDatabaseError) as refused: db.validate_current_database_root(root)
                self.assertNotIsInstance(refused.exception, db._TransientCurrentSnapshotRace); pause.assert_not_called()

    def test_consumer_transient_after_yield_is_never_replayed(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'
            with closing(self.current(root)), patch.object(db, '_read_existing_database_file', wraps=db._read_existing_database_file) as capture, patch.object(db.time, 'sleep') as pause:
                with self.assertRaisesRegex(db._TransientDatabaseMainFileRace, 'consumer'):
                    with db.connect_current_readonly(root): raise db._TransientDatabaseMainFileRace('consumer')
                self.assertEqual(capture.call_count, 1); pause.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', 'Actual POSIX directory permissions')
    def test_data_root_keeps_existing_permission_policy(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'
            with closing(self.current(root)):
                root.chmod(0o755)
                self.assertTrue(db.validate_current_database_root(root))
                self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o755)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Actual FIFO substitution requires mkfifo')
    def test_real_fifo_substitution_is_nonblocking_and_never_read(self):
        for current in (False, True):
            with self.subTest(current=current), TemporaryDirectory() as temporary:
                root = Path(temporary) / 'data'; self.current(root).close()
                path = db.database_path(root); details = path.stat(); original = os.open; swapped = []
                def replace(selected, flags, *args, **kwargs):
                    if Path(selected).name == db.DATABASE_NAME and not swapped:
                        self.assertTrue(flags & os.O_NONBLOCK)
                        swapped.append(True); path.unlink(); os.mkfifo(path, 0o600)
                    return original(selected, flags, *args, **kwargs)
                with patch.object(db.os, 'open', side_effect=replace), patch.object(db.os, 'read') as read, patch.object(db.time, 'sleep') as pause:
                    with self.assertRaises(db.MentatDatabaseError) as refused:
                        if current: db.validate_current_database_root(root)
                        else: db._read_existing_database_file(path, (details.st_dev, details.st_ino), db.MAX_READONLY_DATABASE_BYTES)
                self.assertNotIsInstance(refused.exception, db._TransientCurrentSnapshotRace)
                read.assert_not_called(); pause.assert_not_called(); self.assertTrue(swapped)

    @unittest.skipUnless(os.name == 'posix', 'Actual POSIX privacy mutation at saved fstat')
    def test_unsafe_saved_before_fstat_refuses_before_any_read(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'; self.current(root).close()
            path = db.database_path(root); identity = path.stat()
            original_stat, original_read = os.fstat, db._read_existing_database_file
            inside = [False]; main_stats = []
            def raw(*args, **kwargs):
                inside[0] = True
                try: return original_read(*args, **kwargs)
                finally: inside[0] = False
            def fstat(descriptor):
                details = original_stat(descriptor)
                if inside[0] and (details.st_dev,details.st_ino) == (identity.st_dev,identity.st_ino):
                    main_stats.append(descriptor)
                    if len(main_stats) == 2:
                        path.chmod(0o640)
                        return original_stat(descriptor)
                return details
            with patch.object(db,'_read_existing_database_file',side_effect=raw), patch.object(db.os,'fstat',side_effect=fstat), patch.object(db.os,'read') as read, patch.object(db.time,'sleep') as pause:
                with self.assertRaises(db.MentatDatabaseError) as refused: db.validate_current_database_root(root)
            self.assertNotIsInstance(refused.exception,db._TransientCurrentSnapshotRace)
            self.assertEqual(len(main_stats),2); read.assert_not_called(); pause.assert_not_called()

    def test_main_safety_rejects_owner_reparse_size_and_unlinked_metadata(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'file'; path.write_bytes(b'x'); path.chmod(0o600); actual = path.stat()
            metadata = {key: getattr(actual, key) for key in ('st_dev','st_ino','st_mode','st_nlink','st_size','st_uid')}
            changes = [{'st_file_attributes': 0x400}, {'st_nlink': 0}, {'st_nlink': 2}, {'st_size': 2}, {'st_ino': actual.st_ino + 1}]
            if os.name == 'posix': changes += [{'st_uid': os.getuid() + 1}, {'st_mode': stat.S_IFREG | 0o640}]
            for change in changes:
                with self.subTest(change=change), self.assertRaises(db.MentatDatabaseError) as refused:
                    db._current_main_metadata(SimpleNamespace(**(metadata | change)), (actual.st_dev, actual.st_ino), 1)
                self.assertNotIsInstance(refused.exception, db._TransientCurrentSnapshotRace)

    def test_uncertain_owned_close_attempts_all_resources_once_and_fails(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'; self.current(root).close()
            pins = db._CurrentAdmissionResources(); path = db.database_path(root); details = path.stat(); pins.bind(path, (details.st_dev, details.st_ino))
            descriptors = [pins.main[1], *(fd for _path,fd,_private in reversed(pins.directories))]
            original = os.close; attempted = []
            def close(descriptor):
                attempted.append(descriptor); original(descriptor)
                if descriptor == descriptors[0]: raise OSError('private cleanup failure')
            with patch.object(db.os, 'close', side_effect=close):
                with self.assertRaisesRegex(db.MentatDatabaseError, 'cleanup is unverified'): pins.__exit__(None,None,None)
            self.assertEqual(attempted, descriptors)
            for descriptor in descriptors:
                with self.assertRaises(OSError): os.fstat(descriptor)

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows no-delete directory and main handles')
    def test_native_windows_resources_deny_rename_until_context_exit(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / 'data'; self.current(root).close()
            with db.connect_current_readonly(root):
                with self.assertRaises(OSError): db.database_path(root).parent.rename(root / 'moved')
                with self.assertRaises(OSError): db.database_path(root).rename(root / 'moved-main')
            db.database_path(root).parent.rename(root / 'moved')


class CheckedWindowsAcquisitionTests(unittest.TestCase):
    def test_checked_close_attempts_all_partial_handles_once(self):
        attempted = []
        def close(handle):
            attempted.append(handle)
            if handle == 2: raise OSError('private close failure')
        with patch.object(data_layout, '_windows_close_handle_checked', side_effect=close):
            with self.assertRaisesRegex(OSError, 'cleanup is unverified'): data_layout._windows_close_handles_checked([1,2,3])
        self.assertEqual(attempted, [3,2,1])

    def test_partial_directory_acquisition_uses_checked_unwind_at_every_index(self):
        for failed_index in range(3):
            with self.subTest(failed_index=failed_index):
                def open_entry(*_args, **kwargs):
                    self.assertTrue(kwargs['checked_cleanup'])
                    if len(acquired) == failed_index: raise OSError('acquisition failed')
                    acquired.append(len(acquired) + 10); return acquired[-1]
                acquired = []
                with patch.object(data_layout, '_windows_open_handle', side_effect=open_entry), patch.object(data_layout, '_windows_close_handles_checked') as close:
                    with self.assertRaises(OSError): data_layout._windows_open_directory_chain(Path('/owned/path'), checked_cleanup=True)
                close.assert_called_once_with(acquired)

    def test_failed_crt_transfer_has_checked_single_owner_cleanup(self):
        crt = SimpleNamespace(open_osfhandle=Mock(side_effect=OSError('private transfer failure')))
        with patch.dict(sys.modules, {'msvcrt':crt}), patch.object(data_layout, '_windows_open_handle', return_value=17) as opened, patch.object(data_layout, '_windows_close_handle_checked') as close:
            with self.assertRaises(OSError): data_layout._windows_open_file_descriptor(Path('/owned/file'), disposition=3, writable=False, checked_cleanup=True)
        self.assertTrue(opened.call_args.kwargs['checked_cleanup']); close.assert_called_once_with(17)

    def test_metadata_and_reparse_rejection_check_close_without_changing_open_flags(self):
        for metadata_failure in (True, False):
            with self.subTest(metadata_failure=metadata_failure):
                kernel = SimpleNamespace(CreateFileW=Mock(return_value=17), CloseHandle=Mock(return_value=0))
                def metadata(_handle,_kind,pointer,_size):
                    pointer._obj.file_attributes = 0x400
                    return not metadata_failure
                kernel.GetFileInformationByHandleEx = Mock(side_effect=metadata)
                with patch.object(data_layout, '_windows_kernel32', return_value=kernel), patch.object(ctypes,'WinError',lambda *_:OSError('fixed'),create=True), patch.object(ctypes,'get_last_error',return_value=1,create=True):
                    with self.assertRaisesRegex(OSError,'cleanup is unverified'): data_layout._windows_open_handle(Path('/owned/file'),directory=False,checked_cleanup=True)
                self.assertEqual(kernel.CloseHandle.call_count,1)
                arguments=kernel.CreateFileW.call_args.args
                self.assertEqual(arguments[2],3)  # Existing SHARE_READ|SHARE_WRITE; never SHARE_DELETE.
                self.assertEqual(arguments[4],3)
                self.assertEqual(arguments[5],0x00200000|0x00000080)


if __name__ == '__main__':
    unittest.main()
