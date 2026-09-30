"""Historical storage fixtures; no production admission or provider calls."""

from contextlib import closing
import json
import sqlite3
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import mentat_db
import project_scope_journal as scopes
import project_worker_journal as journal
import private_console_unit
import project_context
from project_repository import mutate_authoritative_projects
from tests.test_project_repository import project
from task_repository import _schema5_private_unit
from mentat.project_worker_scope import LinuxWorkerScope, WorkerScopeLimits
from tests import test_project_worker_journal as fixtures

_RETAINED_STALLED_FIXTURES = []


def planned_fixture():
    # Deliberately inert historical fixture, not a qualified Linux scope.
    scope = LinuxWorkerScope.__new__(LinuxWorkerScope)
    scope._uid = 1000
    scope._unit = 'mentat-project-worker-' + 'c'*32 + '.scope'
    scope._boot_id = 'b'*32
    scope._limits = WorkerScopeLimits()
    scope._closed = False
    scope._process = scope._deadline = None
    scope._lock = threading.RLock()
    return scope


class _ScopeJournalFixture:
    def setUp(self):
        self.fixture = fixtures.ProjectWorkerJournalTests()
        self.fixture.setUp()
        fixture = self.fixture
        self.addCleanup(lambda: fixture.doCleanups() if not any(fixture is item for item in _RETAINED_STALLED_FIXTURES) else None)
        self.root = self.fixture.root
        self.run = self.fixture._prepare()
        self.scope = planned_fixture()

    def prepare(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            result = scopes.prepare_scope(connection,run_id=self.run,generation=fixtures.GENERATION,
                                          plan_witness=self.scope.journal_plan())
            connection.commit()
            return result

    def move(self, receipt, target, **changes):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            result = scopes.transition_scope(connection,run_id=self.run,generation=fixtures.GENERATION,
                claim_token=receipt.claim_token,expected_revision=receipt.revision,target=target,**changes)
            connection.commit()
            return result

class ScopeJournalTests(_ScopeJournalFixture, unittest.TestCase):
    def test_duplicate_preparation_never_recovers_token_or_changes_intent(self):
        first = self.prepare()
        repeated = self.prepare()
        self.assertTrue(first.changed)
        self.assertFalse(repeated.changed)
        self.assertIsNone(repeated.claim_token)
        self.assertNotIn(first.claim_token,repr(first))
        self.scope._unit = 'mentat-project-worker-' + 'd'*32 + '.scope'
        with self.assertRaises(scopes.ScopeJournalError):
            self.prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_worker_scopes').fetchone()[0],1)
            self.assertNotIn(first.claim_token,str(tuple(connection.execute('SELECT * FROM mentat_project_worker_scopes').fetchone())))

    def test_unknown_cannot_relaunch_reacquire_or_be_archived(self):
        first = self.prepare()
        started = self.move(first,'starting')
        duplicate = self.move(first,'starting')
        self.assertFalse(duplicate.changed)
        self.assertEqual(duplicate.revision,started.revision)
        unknown = self.move(scopes.ScopeReceipt(first.run_id,first.generation,started.state,started.revision,False,first.claim_token),'unknown')
        with self.assertRaises(scopes.ScopeJournalError):
            self.move(scopes.ScopeReceipt(first.run_id,first.generation,unknown.state,unknown.revision,False,first.claim_token),'starting')
        with closing(mentat_db.connect(self.root)) as connection:
            with self.assertRaises(scopes.ScopeJournalError):
                journal.archival_proposal_ids(connection)
            self.assertEqual(connection.execute('SELECT state FROM mentat_project_worker_scopes').fetchone()[0],'unknown')
        self.assertIsNone(self.prepare().claim_token)

    def test_raw_stop_metadata_and_wrong_token_leave_receipt_unchanged(self):
        first = self.prepare()
        started = self.move(first,'starting')
        for witness in (True,{},self.scope.journal_plan()):
            with self.subTest(witness=witness), self.assertRaises(scopes.ScopeJournalError):
                self.move(scopes.ScopeReceipt(first.run_id,first.generation,started.state,started.revision,False,first.claim_token),'stopped',witness=witness)
        with self.assertRaises(scopes.ScopeJournalError):
            self.move(scopes.ScopeReceipt(first.run_id,first.generation,started.state,started.revision,False,'f'*64),'unknown')
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(tuple(connection.execute('SELECT state,revision FROM mentat_project_worker_scopes').fetchone()),('starting',2))

    def test_restore_epoch_blocks_forward_work_but_allows_original_token_cancel(self):
        first = self.prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('UPDATE mentat_project_context_access_state SET approval_epoch=? WHERE singleton=1',(b'z'*32,))
            connection.commit()
        with self.assertRaises(journal.WorkerJournalError):
            self.move(first,'starting')
        cancelled = self.move(first,'cancelled')
        self.assertEqual(cancelled.state,'cancelled')
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertIn(self.run,journal.archival_proposal_ids(connection))

    def test_sql_immutability_and_source_guard_remain(self):
        self.prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            for statement in ("DELETE FROM mentat_project_worker_scopes", "UPDATE mentat_project_worker_scopes SET state='owned'",
                              "UPDATE mentat_project_worker_scopes SET unit='changed'"):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(statement)
                connection.rollback()
            self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='mentat_runs_project_proposal_closed_insert'").fetchone())
            scopes.validate_scope_journal_connection(connection)

    def test_prepared_backup_restore_retains_hash_and_fences_work(self):
        first = self.prepare()
        unit = private_console_unit.capture_private_console_unit(self.root)
        self.assertNotIn(first.claim_token.encode(),unit.database_raw)
        private_console_unit.validate_private_console_unit(unit)
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target/'private').mkdir(mode=0o700)
            private_console_unit.materialize_private_console_unit(target,
                private_console_unit.sanitize_owner_auth_restore_unit(unit),target/'private'/'console')
            with closing(mentat_db.connect(target)) as connection:
                self.assertEqual(scopes.read_scope(connection,self.run).state,'prepared')
                connection.execute('BEGIN IMMEDIATE')
                with self.assertRaises(journal.WorkerJournalError):
                    scopes.transition_scope(connection,run_id=self.run,generation=fixtures.GENERATION,
                        claim_token=first.claim_token,expected_revision=1,target='starting')
                connection.rollback()
                self.assertEqual(scopes.read_scope(connection,self.run).revision,1)
            compatible = _schema5_private_unit(unit)
            with closing(sqlite3.connect(':memory:')) as connection:
                connection.deserialize(compatible.database_raw)
                self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='mentat_project_worker_scopes'").fetchone())

    def test_active_private_capture_refuses_without_source_change(self):
        first = self.prepare()
        self.move(first,'starting')
        with closing(mentat_db.connect(self.root)) as connection:
            before = list(connection.iterdump())
        with self.assertRaises(private_console_unit.PrivateConsoleUnitError):
            private_console_unit.capture_private_console_unit(self.root,harden_source=False,copy_sqlite_source=True)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(list(connection.iterdump()),before)

    def test_source43_drift_and_post_ddl_failure_roll_back(self):
        for tamper in ('ALTER TABLE mentat_runs ADD COLUMN injected_drift TEXT',None):
            with self.subTest(tamper=tamper), TemporaryDirectory() as temporary:
                path = Path(temporary)/'mentat.sqlite3'
                private_console_unit._initialize_database(path,schema_version=43)
                with closing(sqlite3.connect(path)) as connection:
                    if tamper:
                        connection.execute(tamper)
                        connection.commit()
                    before = list(connection.iterdump())
                    execute = mentat_db._execute_script_in_active_transaction
                    def fail_after_ddl(active,script):
                        execute(active,script)
                        if script == dict(mentat_db.MIGRATIONS)[44]:
                            self.assertIsNotNone(active.execute("SELECT 1 FROM sqlite_master WHERE name='mentat_project_worker_scopes'").fetchone())
                            raise RuntimeError('after scope DDL fixture')
                    if tamper:
                        with self.assertRaisesRegex(mentat_db.MentatDatabaseError,'schema 43'):
                            mentat_db.migrate(connection)
                    else:
                        with patch.object(mentat_db,'_execute_script_in_active_transaction',side_effect=fail_after_ddl):
                            with self.assertRaisesRegex(RuntimeError,'after scope DDL'):
                                mentat_db.migrate(connection)
                    self.assertEqual(list(connection.iterdump()),before)
                    self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0],43)
                    self.assertFalse(connection.in_transaction)

    def test_exact_schema43_private_capture_validates_then_upgrades_without_losing_graph(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DROP TRIGGER mentat_project_output_reservation_immutable')
            connection.execute('DROP TRIGGER mentat_project_output_reservation_retained')
            connection.execute('DROP TABLE mentat_project_output_reservations')
            connection.execute('DROP TRIGGER mentat_project_worker_scope_immutable')
            connection.execute('DROP TRIGGER mentat_project_worker_scope_retained')
            connection.execute('DROP TABLE mentat_project_worker_scopes')
            connection.execute('DELETE FROM schema_migrations WHERE version>=44')
            connection.commit()
            self.assertEqual(mentat_db.schema_signature_state(connection,43),'expected')
            before = journal.validate_worker_journal_connection(connection)
        unit = private_console_unit.capture_private_console_unit(self.root)
        private_console_unit.validate_private_console_unit(unit)
        with TemporaryDirectory() as temporary:
            copied = Path(temporary)/'old43.sqlite'
            copied.write_bytes(unit.database_raw)
            with closing(sqlite3.connect(copied)) as connection:
                self.assertEqual(mentat_db.schema_signature_state(connection,43),'expected')
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(mentat_db.schema_signature_state(connection,45),'expected')
            self.assertEqual(journal.validate_worker_journal_connection(connection),before)
            self.assertEqual(scopes.validate_scope_journal_connection(connection),[])

    def test_competing_connections_mint_one_token_and_transition_once(self):
        barrier = threading.Barrier(2)
        results, errors = [], []
        def prepare():
            try:
                barrier.wait()
                results.append(self.prepare())
            except BaseException as exc:
                errors.append(exc)
        workers = [threading.Thread(target=prepare) for _ in range(2)]
        def run_owned_workers(workers):
            started_workers = []
            try:
                for worker in workers:
                    worker.start()
                    started_workers.append(worker)
                for worker in started_workers: worker.join(10)
            finally:
                for worker in started_workers:
                    if worker.is_alive(): worker.join(10)
                if any(worker.is_alive() for worker in started_workers):
                    # Keep the exact disposable graph alive; never remove its
                    # temporary files beneath a still-running SQLite writer.
                    _RETAINED_STALLED_FIXTURES.append(self.fixture)
        run_owned_workers(workers)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors,[])
        self.assertEqual(sum(item.changed for item in results),1)
        first = next(item for item in results if item.claim_token)
        results.clear()
        barrier = threading.Barrier(2)
        def start():
            try:
                barrier.wait()
                results.append(self.move(first,'starting'))
            except BaseException as exc:
                errors.append(exc)
        workers = [threading.Thread(target=start) for _ in range(2)]
        run_owned_workers(workers)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(errors,[])
        self.assertEqual(sum(item.changed for item in results),1)
        self.assertEqual({item.revision for item in results},{2})

    def test_stale_intents_and_tampered_identity_are_not_retained(self):
        first = self.prepare()
        started = self.move(first,'starting')
        unknown = self.move(scopes.ScopeReceipt(first.run_id,first.generation,'starting',started.revision,False,first.claim_token),'unknown')
        with self.assertRaises(scopes.ScopeJournalError): self.move(first,'starting')
        with self.assertRaises(scopes.ScopeJournalError): self.move(first,'cancelled')
        with closing(mentat_db.connect(self.root)) as connection:
            before = list(connection.iterdump())
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('DROP TRIGGER mentat_project_worker_scope_immutable')
            connection.execute("UPDATE mentat_project_worker_scopes SET plan_digest=?",('f'*64,))
            with self.assertRaises(scopes.ScopeJournalError): scopes.validate_scope_journal_connection(connection)
            connection.rollback()
            self.assertEqual(list(connection.iterdump()),before)
            self.assertEqual(scopes.read_scope(connection,self.run).revision,unknown.revision)


@unittest.skipUnless(sys.platform == 'linux','Actual held Linux scope required')
class LinuxScopeJournalTests(_ScopeJournalFixture, unittest.TestCase):
    def test_actual_owned_closure_retains_unknown_inference_and_fixed_charge(self):
        self.scope = LinuxWorkerScope()
        self.addCleanup(lambda: self.scope.close_verified() if not self.scope._closed else None)
        first = self.prepare()
        with closing(mentat_db.connect(self.root)) as connection:
            before = len(json.dumps(scopes.validate_scope_journal_connection(connection)))
        started = self.move(first,'starting')
        self.scope.start_inert()
        owned = self.move(scopes.ScopeReceipt(first.run_id,first.generation,started.state,started.revision,False,first.claim_token),
                          'owned',witness=self.scope.journal_owned_identity())
        self.fixture._reserve(self.run)
        self.scope.close_verified()
        stopped = self.move(scopes.ScopeReceipt(first.run_id,first.generation,owned.state,owned.revision,False,first.claim_token),
                            'stopped',witness=self.scope.journal_closed_identity())
        self.assertEqual(stopped.state,'stopped')
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(len(json.dumps(scopes.validate_scope_journal_connection(connection))),before)
            self.assertEqual(connection.execute('SELECT state FROM mentat_project_worker_calls').fetchone()[0],'unknown')
            self.assertIn(self.run,journal.archival_proposal_ids(connection))
        unit = private_console_unit.capture_private_console_unit(self.root)
        with TemporaryDirectory() as temporary:
            target = Path(temporary)
            (target/'private').mkdir(mode=0o700)
            private_console_unit.materialize_private_console_unit(target,
                private_console_unit.sanitize_owner_auth_restore_unit(unit),target/'private'/'console')
            with closing(mentat_db.connect(target)) as connection:
                self.assertEqual(scopes.read_scope(connection,self.run).state,'stopped')
                self.assertEqual(connection.execute('SELECT state FROM mentat_project_worker_calls').fetchone()[0],'unknown')

    def test_unknown_to_stop_with_or_without_retained_identity(self):
        for owned_first in (False,True):
            with self.subTest(owned_first=owned_first):
                if owned_first:
                    self.fixture.doCleanups()
                    self.setUp()
                scope = self.scope = LinuxWorkerScope()
                try:
                    first = self.prepare()
                    last = self.move(first,'starting')
                    scope.start_inert()
                    if owned_first:
                        last = self.move(scopes.ScopeReceipt(first.run_id,first.generation,last.state,last.revision,False,first.claim_token),
                            'owned',witness=scope.journal_owned_identity())
                    last = self.move(scopes.ScopeReceipt(first.run_id,first.generation,last.state,last.revision,False,first.claim_token),'unknown')
                    with closing(mentat_db.connect(self.root)) as connection:
                        saved = connection.execute('SELECT identity_json FROM mentat_project_worker_scopes').fetchone()[0]
                        self.assertEqual(saved is not None,owned_first)
                    scope.close_verified()
                    last = self.move(scopes.ScopeReceipt(first.run_id,first.generation,last.state,last.revision,False,first.claim_token),
                        'stopped',witness=scope.journal_closed_identity())
                    with closing(mentat_db.connect(self.root)) as connection:
                        self.assertIn(self.run,journal.archival_proposal_ids(connection))
                        if saved: self.assertEqual(connection.execute('SELECT identity_json FROM mentat_project_worker_scopes').fetchone()[0],saved)
                finally:
                    if not scope._closed: scope.close_verified()

    def test_shared_headroom_after_other_owner_write_still_allows_closure(self):
        self.scope = LinuxWorkerScope()
        self.addCleanup(lambda: self.scope.close_verified() if not self.scope._closed else None)
        first = self.prepare()
        self.fixture._reserve(self.run)
        mutate_authoritative_projects(self.root,lambda rows: ([*rows,project('Other','project_other')],None))
        project_context.publish_project_context(self.root,'project_other',expected_project_revision=1,
            expected_revision=0,brief='Unrelated owner context. '*150,attachment_ids=[])
        with closing(mentat_db.connect(self.root)) as connection:
            encoded_sizes = []
            encode = project_context._encoded
            def measured(value):
                data = encode(value)
                encoded_sizes.append(len(data))
                return data
            with patch.object(project_context,'_encoded',side_effect=measured):
                project_context.validate_project_context_connection(connection)
            exact_budget = max(encoded_sizes)
        with patch.object(project_context,'OUTPUT_RESERVATION_MAX_METADATA_BYTES',exact_budget):
            started = self.move(first,'starting')
            self.scope.start_inert()
            owned = self.move(scopes.ScopeReceipt(first.run_id,first.generation,started.state,started.revision,False,first.claim_token),
                'owned',witness=self.scope.journal_owned_identity())
            self.scope.close_verified()
            stopped = self.move(scopes.ScopeReceipt(first.run_id,first.generation,owned.state,owned.revision,False,first.claim_token),
                'stopped',witness=self.scope.journal_closed_identity())
            self.assertEqual(stopped.state,'stopped')
            with closing(mentat_db.connect(self.root)) as connection:
                project_context.validate_project_context_connection(connection)
                self.assertEqual(connection.execute('SELECT state FROM mentat_project_worker_calls').fetchone()[0],'unknown')
