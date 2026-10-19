"""Current-only SQLite admission and fresh initialization contracts."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import threading
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import mentat_db


class MentatDatabaseCurrentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def snapshot(self):
        return {
            str(path.relative_to(self.root)): (
                stat.S_IMODE(path.lstat().st_mode),
                path.read_bytes() if path.is_file() and not path.is_symlink() else None,
            )
            for path in self.root.rglob('*')
        }

    def current(self):
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 46)
        return mentat_db.database_path(self.root)

    def refuse_unchanged(self):
        before = self.snapshot()
        with patch.object(mentat_db, 'ensure_private_console_dir', side_effect=AssertionError('mutable setup reached')):
            with self.assertRaises(mentat_db.MentatDatabaseError):
                mentat_db.connect(self.root)
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(mentat_db.MentatDatabaseError):
            mentat_db.validate_current_database_root(self.root)
        self.assertEqual(self.snapshot(), before)
        with self.assertRaises(mentat_db.MentatDatabaseError):
            with mentat_db.connect_current_readonly(self.root):
                self.fail('unsupported root yielded a current connection')
        self.assertEqual(self.snapshot(), before)

    def test_missing_admission_does_not_create_storage(self):
        missing = self.root / 'missing'
        self.assertFalse(mentat_db.validate_current_database_root(missing))
        self.assertFalse(missing.exists())
        self.assertFalse(mentat_db.validate_current_database_root(self.root))
        self.assertEqual(self.snapshot(), {})

    def test_exact_original_current_object_graph_and_structural_journal(self):
        with closing(mentat_db.connect(self.root)) as connection:
            signature = mentat_db.schema_signature(connection)
            self.assertEqual(len(signature), 256)
            self.assertEqual(hashlib.sha256(json.dumps(signature, separators=(',', ':')).encode()).hexdigest(),
                             '2962a6b78b5f94ea0d5ae01cdbcba36a1f577e419bed287feb81ee5c98ae6218')
            self.assertEqual([row[0] for row in connection.execute('SELECT version FROM schema_migrations ORDER BY version')], list(range(1, 47)))
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual([v for v, _ in mentat_db.MIGRATIONS], [46])
            self.assertGreater(connection.execute('SELECT MIN(applied_at) FROM schema_migrations').fetchone()[0], 0)
        self.assertTrue(mentat_db.validate_current_database_root(self.root))

    def test_virtual_recipe_cutoffs_stay_zero_while_live_initialization_is_dated(self):
        with closing(sqlite3.connect(':memory:', isolation_level=None)) as connection:
            connection.executescript(mentat_db.CURRENT_BOOTSTRAP_SQL)
            self.assertEqual(connection.execute('SELECT applied_at FROM schema_migrations WHERE version=40').fetchone()[0], 0)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertGreater(connection.execute('SELECT applied_at FROM schema_migrations WHERE version=40').fetchone()[0], 0)

    def test_fresh_random_epochs_and_owner_state_are_preserved_on_reopen(self):
        with closing(mentat_db.connect(self.root)) as connection:
            approval = connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state').fetchone()[0]
            confirmation = connection.execute('SELECT confirmation_epoch FROM mentat_deliverable_review_state').fetchone()[0]
            self.assertEqual(len(approval), 32)
            self.assertEqual(len(confirmation), 32)
            self.assertNotEqual(approval, confirmation)
            state = tuple(connection.execute('SELECT state,revision,updated_at,auth_method,owner_generation FROM mentat_owner_auth_state').fetchone())
            self.assertEqual(state, ('unbootstrapped', 1, 0.0, 'passkey', 0))
            receipt = tuple(connection.execute('SELECT * FROM mentat_agent_registry_state').fetchone())
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state').fetchone()[0], approval)
            self.assertEqual(connection.execute('SELECT confirmation_epoch FROM mentat_deliverable_review_state').fetchone()[0], confirmation)
            self.assertEqual(tuple(connection.execute('SELECT * FROM mentat_agent_registry_state').fetchone()), receipt)
        with TemporaryDirectory() as other:
            with closing(mentat_db.connect(Path(other))) as connection:
                self.assertNotEqual(connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state').fetchone()[0], approval)
                self.assertNotEqual(connection.execute('SELECT confirmation_epoch FROM mentat_deliverable_review_state').fetchone()[0], confirmation)

    def test_current_reopen_runs_no_ddl_or_row_conversion(self):
        path = self.current()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('UPDATE mentat_deliverable_review_state SET revision=3')
            connection.commit()
        before = path.read_bytes()
        statements = []
        original = sqlite3.connect
        def traced(*args, **kwargs):
            connection = original(*args, **kwargs)
            if args and str(args[0]) == str(path.resolve()):
                connection.set_trace_callback(statements.append)
            return connection
        with patch.object(mentat_db.sqlite3, 'connect', side_effect=traced):
            with closing(mentat_db.connect(self.root)) as connection:
                self.assertEqual(connection.execute('SELECT revision FROM mentat_deliverable_review_state').fetchone()[0], 3)
        self.assertFalse(any(sql.lstrip().upper().startswith(('CREATE ', 'ALTER ', 'DROP ', 'INSERT ', 'UPDATE ', 'DELETE ')) for sql in statements), statements)
        self.assertEqual(path.read_bytes(), before)

    def test_old_and_future_versions_are_refused_without_source_changes(self):
        path = self.current()
        for version in (1, 33, 38, 43, 45, 47):
            with self.subTest(version=version):
                with closing(sqlite3.connect(path)) as connection:
                    connection.execute('DELETE FROM schema_migrations')
                    connection.executemany('INSERT INTO schema_migrations VALUES (?,0)', ((v,) for v in range(1, version + 1)))
                    connection.commit()
                self.refuse_unchanged()

    def test_missing_structural_receipt_is_refused_unchanged(self):
        path = self.current()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('DELETE FROM schema_migrations WHERE version=12')
            connection.commit()
        self.refuse_unchanged()

    def test_schema_drift_is_refused_unchanged(self):
        path = self.current()
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('DROP TRIGGER mentat_project_output_reservation_immutable')
            connection.commit()
        self.refuse_unchanged()

    def test_malformed_and_empty_existing_files_are_not_reinitialized(self):
        mentat_db.ensure_private_console_dir(self.root)
        path = mentat_db.database_path(self.root)
        for raw in (b'', b'not a sqlite database'):
            with self.subTest(raw=raw):
                path.write_bytes(raw)
                path.chmod(0o600)
                self.refuse_unchanged()

    def test_unsupported_wal_state_is_refused_without_sidecar_changes(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('DELETE FROM schema_migrations WHERE version=46')
            self.assertTrue(Path(str(mentat_db.database_path(self.root)) + '-wal').exists())
            self.refuse_unchanged()

    @unittest.skipUnless(os.name == 'posix', 'POSIX permission contract')
    def test_unsafe_existing_permissions_are_refused_without_hardening(self):
        path = self.current()
        path.chmod(0o644)
        self.refuse_unchanged()

    @unittest.skipUnless(os.name == 'posix', 'POSIX permission contract')
    def test_unsafe_existing_directory_is_refused_without_hardening(self):
        self.current()
        mentat_db.private_console_dir(self.root).chmod(0o755)
        self.refuse_unchanged()

    def test_symlink_and_hardlink_database_are_refused(self):
        path = self.current()
        other = path.with_name('owned-original.sqlite3')
        path.rename(other)
        try:
            path.symlink_to(other.name)
        except OSError:
            self.skipTest('symlink unavailable')
        self.refuse_unchanged()
        path.unlink()
        os.link(other, path)
        self.refuse_unchanged()

    def test_current_only_expected_schema_api(self):
        for version in (11, 45, 47, True, '46'):
            with self.subTest(version=version):
                with self.assertRaises(mentat_db.MentatDatabaseError):
                    mentat_db.expected_schema_signature(version)
        self.assertEqual(mentat_db.expected_schema_signature.cache_info().maxsize, 1)

    def test_virtual_recipe_has_no_authority_and_raced_live_gates_roll_back(self):
        with closing(sqlite3.connect(':memory:', isolation_level=None)) as connection:
            connection.executescript(mentat_db.CURRENT_BOOTSTRAP_SQL)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_agent_registry_state').fetchone()[0], 0)
        for gates in ((False,), (True, False), (True, True, False)):
            with self.subTest(gates=gates), closing(sqlite3.connect(':memory:', isolation_level=None)) as connection:
                with self.assertRaisesRegex(mentat_db.MentatDatabaseError, 'changed during authority claim'):
                    mentat_db.migrate(connection, fresh_agent_authority_allowed=iter(gates).__next__)
                self.assertEqual(connection.execute('SELECT name FROM sqlite_master').fetchall(), [])

    def test_missing_database_rejects_retired_registry_without_root_changes(self):
        mentat_db.ensure_private_console_dir(self.root)
        private = mentat_db.private_console_dir(self.root)
        for suffix in ('', '-wal', '-shm', '-journal'):
            with self.subTest(suffix=suffix):
                artifact = private / (mentat_db.LEGACY_AGENT_REGISTRY_DATABASE_NAME + suffix)
                artifact.write_bytes(b'synthetic retired storage, never parsed')
                artifact.chmod(0o644)
                if os.name == 'posix':
                    private.chmod(0o755)
                before = self.snapshot()
                with patch.object(mentat_db, 'ensure_private_console_dir', side_effect=AssertionError('mutable setup reached')):
                    with self.assertRaisesRegex(mentat_db.MentatDatabaseError, 'Retired Agent registry'):
                        mentat_db.connect(self.root)
                self.assertEqual(self.snapshot(), before)
                with self.assertRaisesRegex(mentat_db.MentatDatabaseError, 'Retired Agent registry'):
                    mentat_db.validate_current_database_root(self.root)
                self.assertEqual(self.snapshot(), before)
                artifact.unlink()

    def test_postclaim_cleanup_removes_only_the_exact_empty_fresh_receipt(self):
        with closing(mentat_db.connect(self.root)) as connection:
            cutover = connection.execute('SELECT cutover_at FROM mentat_agent_registry_state').fetchone()[0]
            artifact = mentat_db.private_console_dir(self.root) / (mentat_db.LEGACY_AGENT_REGISTRY_DATABASE_NAME + '-wal')
            artifact.write_bytes(b'owned postclaim race')
            artifact.chmod(0o600)
            self.assertTrue(mentat_db._remove_exact_fresh_authority_if_unchanged(connection, self.root, cutover))
            for table in ('mentat_agent_registry_state', 'mentat_agents', 'agent_runtime_configs'):
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
            self.assertEqual(artifact.read_bytes(), b'owned postclaim race')

    def test_postclaim_cleanup_preserves_supported_agent_state(self):
        with closing(mentat_db.connect(self.root)) as connection:
            cutover = connection.execute('SELECT cutover_at FROM mentat_agent_registry_state').fetchone()[0]
            connection.execute("INSERT INTO agent_runtime_configs(id,runtime_type,runtime_agent_ref,created_at,updated_at) VALUES('config_concurrent','hermes','synthetic-test',1,1)")
            connection.execute("INSERT INTO mentat_agents(id,name,runtime_config_id,capabilities_json,created_at,updated_at) VALUES('agent_concurrent','Concurrent','config_concurrent','[]',1,1)")
            artifact = mentat_db.private_console_dir(self.root) / (mentat_db.LEGACY_AGENT_REGISTRY_DATABASE_NAME + '-wal')
            artifact.write_bytes(b'owned postclaim race')
            artifact.chmod(0o600)
            before = list(connection.iterdump())
            with self.assertRaisesRegex(mentat_db.MentatDatabaseError, 'Agent authority changed'):
                mentat_db._remove_exact_fresh_authority_if_unchanged(connection, self.root, cutover)
            self.assertEqual(list(connection.iterdump()), before)
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_database_appearing_after_missing_admission_never_opens_sqlite(self):
        for version in (45, 46):
            with TemporaryDirectory() as source_root:
                source = Path(source_root)
                with closing(mentat_db.connect(source)) as connection:
                    if version == 45:
                        connection.execute('DELETE FROM schema_migrations WHERE version=46')
                raw = mentat_db.database_path(source).read_bytes()
            for phase in ('ensure', 'exclusive_create'):
                with self.subTest(version=version, phase=phase), TemporaryDirectory() as target_root:
                    target = Path(target_root)
                    path = mentat_db.database_path(target)
                    ensure = mentat_db.ensure_private_console_dir
                    original_open = os.open
                    def appearing_ensure(root):
                        private = ensure(root)
                        if phase == 'ensure':
                            path.write_bytes(raw)
                            path.chmod(0o600)
                        return private
                    def appearing_open(candidate, flags, *args, **kwargs):
                        if phase == 'exclusive_create' and Path(candidate) == path.resolve() and flags & os.O_EXCL:
                            descriptor = original_open(candidate, flags, *args, **kwargs)
                            try:
                                os.write(descriptor, raw)
                            finally:
                                os.close(descriptor)
                            raise FileExistsError('owned appearing fixture')
                        return original_open(candidate, flags, *args, **kwargs)
                    with patch.object(mentat_db, 'ensure_private_console_dir', side_effect=appearing_ensure), \
                         patch.object(mentat_db.os, 'open', side_effect=appearing_open), \
                         patch.object(mentat_db.sqlite3, 'connect', side_effect=AssertionError('unadmitted SQLite opened')):
                        with self.assertRaisesRegex(mentat_db.MentatDatabaseError, 'identity changed'):
                            mentat_db.connect(target)
                    self.assertEqual(path.read_bytes(), raw)
                    self.assertFalse(Path(str(path) + '-wal').exists())
                    self.assertFalse(Path(str(path) + '-shm').exists())

    def test_current_initialization_api_does_not_commit_a_callers_transaction(self):
        with closing(sqlite3.connect(':memory:', isolation_level=None)) as connection:
            mentat_db.migrate(connection)
            connection.execute('BEGIN')
            connection.execute('UPDATE mentat_deliverable_review_state SET revision=4')
            with self.assertRaisesRegex(mentat_db.MentatDatabaseError, 'inside a transaction'):
                mentat_db.migrate(connection)
            self.assertTrue(connection.in_transaction)
            self.assertEqual(connection.execute('SELECT revision FROM mentat_deliverable_review_state').fetchone()[0], 4)
            connection.rollback()
            self.assertEqual(connection.execute('SELECT revision FROM mentat_deliverable_review_state').fetchone()[0], 0)

    def test_wal_prefix_append_is_allowed_but_rewrite_and_reset_refuse(self):
        path = self.root / 'owned-wal'
        for mutation, accepted in (('append', True), ('rewrite', False), ('reset', False)):
            with self.subTest(mutation=mutation):
                path.write_bytes(b'fixed captured prefix')
                identity = (path.stat().st_dev, path.stat().st_ino)
                original_read = os.read
                changed = False
                def mutating_read(descriptor, size):
                    nonlocal changed
                    raw = original_read(descriptor, size)
                    if not changed:
                        changed = True
                        if mutation == 'append':
                            with path.open('ab') as output:
                                output.write(b'later append')
                        else:
                            path.write_bytes(b'changed stable prefix' if mutation == 'rewrite' else b'')
                    return raw
                with patch.object(mentat_db.os, 'read', side_effect=mutating_read):
                    if accepted:
                        self.assertEqual(mentat_db._read_wal_prefix(path, identity), b'fixed captured prefix')
                    else:
                        with self.assertRaises(mentat_db.MentatDatabaseError):
                            mentat_db._read_wal_prefix(path, identity)

    def test_main_mutation_across_wal_capture_refuses_and_cleans_temp(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('UPDATE mentat_deliverable_review_state SET revision=1')
            path = mentat_db.database_path(self.root)
            original = mentat_db._read_wal_prefix
            def changed_main(*args):
                result = original(*args)
                with path.open('r+b') as target:
                    target.seek(-1, os.SEEK_END)
                    target.write(b'!')
                return result
            with patch.object(mentat_db, '_read_wal_prefix', side_effect=changed_main):
                with self.assertRaisesRegex(mentat_db.MentatDatabaseError, 'changed while reading'):
                    mentat_db.validate_current_database_root(self.root)

    def test_unsupported_wal_and_absent_shm_do_not_create_or_modify_source(self):
        for version in (45, 47):
            with self.subTest(version=version):
                with TemporaryDirectory() as source_root:
                    with closing(mentat_db.connect(Path(source_root))) as connection:
                        connection.execute('DELETE FROM schema_migrations WHERE version=46')
                        if version == 47:
                            connection.execute('INSERT INTO schema_migrations VALUES (46,0),(47,0)')
                        source = mentat_db.database_path(Path(source_root))
                        mentat_db.ensure_private_console_dir(self.root)
                        destination = mentat_db.database_path(self.root)
                        for suffix in ('', '-wal'):
                            target = Path(str(destination) + suffix)
                            target.write_bytes(Path(str(source) + suffix).read_bytes())
                            target.chmod(0o600)
                self.assertFalse(Path(str(destination) + '-shm').exists())
                self.refuse_unchanged()

    def test_current_wal_without_shm_recovers_only_in_owned_copy(self):
        with TemporaryDirectory() as source_root:
            with closing(mentat_db.connect(Path(source_root))) as connection:
                connection.execute('UPDATE mentat_deliverable_review_state SET revision=7')
                source = mentat_db.database_path(Path(source_root))
                mentat_db.ensure_private_console_dir(self.root)
                destination = mentat_db.database_path(self.root)
                for suffix in ('', '-wal'):
                    target = Path(str(destination) + suffix)
                    target.write_bytes(Path(str(source) + suffix).read_bytes())
                    target.chmod(0o600)
        before = self.snapshot()
        self.assertTrue(mentat_db.validate_current_database_root(self.root))
        with mentat_db.connect_current_readonly(self.root) as connection:
            self.assertIs(connection.row_factory, sqlite3.Row)
            self.assertEqual(connection.execute('SELECT revision FROM mentat_deliverable_review_state').fetchone()['revision'], 7)
            self.assertEqual(connection.execute('PRAGMA query_only').fetchone()[0], 1)
            copied = Path(connection.execute('PRAGMA database_list').fetchone()[2])
            self.assertNotEqual(copied, destination)
            self.assertTrue(copied.exists())
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute('UPDATE mentat_deliverable_review_state SET revision=8')
        self.assertFalse(copied.exists())
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(Path(str(destination) + '-shm').exists())

    def test_current_readonly_requires_existing_storage_without_creating_it(self):
        with self.assertRaises(mentat_db.MentatDatabaseError):
            with mentat_db.connect_current_readonly(self.root):
                self.fail('missing root yielded a connection')
        self.assertEqual(self.snapshot(), {})

    def test_current_readonly_survives_source_sidecar_turnover_after_capture(self):
        connection = mentat_db.connect(self.root)
        try:
            connection.execute('UPDATE mentat_deliverable_review_state SET revision=9')
            with mentat_db.connect_current_readonly(self.root) as snapshot:
                self.assertEqual(snapshot.execute('SELECT revision FROM mentat_deliverable_review_state').fetchone()[0], 9)
                connection.close()
                connection = None
                self.assertFalse(Path(str(mentat_db.database_path(self.root)) + '-wal').exists())
                self.assertEqual(snapshot.execute('SELECT revision FROM mentat_deliverable_review_state').fetchone()[0], 9)
            with mentat_db.connect_current_readonly(self.root) as snapshot:
                connection = sqlite3.connect(mentat_db.database_path(self.root), isolation_level=None)
                connection.execute('UPDATE mentat_deliverable_review_state SET revision=10')
                self.assertTrue(Path(str(mentat_db.database_path(self.root)) + '-wal').exists())
                self.assertEqual(snapshot.execute('SELECT revision FROM mentat_deliverable_review_state').fetchone()[0], 9)
        finally:
            if connection is not None:
                connection.close()

    def test_owned_snapshot_storage_is_removed_on_refusal(self):
        self.current()
        path = mentat_db.database_path(self.root)
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('DELETE FROM schema_migrations WHERE version=46')
            connection.commit()
        names = []
        def owned_temporary(*args, **kwargs):
            temporary = TemporaryDirectory(*args, **kwargs)
            names.append(Path(temporary.name))
            return temporary
        with patch.object(mentat_db, 'TemporaryDirectory', side_effect=owned_temporary):
            self.refuse_unchanged()
        self.assertTrue(names)
        self.assertTrue(all(not name.exists() for name in names))

    def test_current_admission_allows_owned_append_only_writer(self):
        self.current()
        ready = threading.Event()
        stop = threading.Event()
        errors = []
        def writer():
            try:
                with closing(sqlite3.connect(mentat_db.database_path(self.root), isolation_level=None)) as connection:
                    connection.execute('PRAGMA wal_autocheckpoint=0')
                    connection.execute('UPDATE mentat_deliverable_review_state SET revision=revision+1')
                    ready.set()
                    while not stop.wait(0.003):
                        connection.execute('UPDATE mentat_deliverable_review_state SET revision=revision+1')
            except BaseException as exc:
                errors.append(exc)
                ready.set()
        thread = threading.Thread(target=writer)
        thread.start()
        try:
            self.assertTrue(ready.wait(5))
            self.assertEqual(errors, [])
            for _ in range(5):
                with mentat_db.connect_current_readonly(self.root) as connection:
                    self.assertGreater(connection.execute('SELECT revision FROM mentat_deliverable_review_state').fetchone()[0], 0)
                with closing(mentat_db.connect(self.root)) as connection:
                    self.assertGreater(connection.execute('SELECT revision FROM mentat_deliverable_review_state').fetchone()[0], 0)
        finally:
            stop.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])


if __name__ == '__main__':
    unittest.main()
