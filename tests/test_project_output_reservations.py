"""Prelaunch holds survive uncertainty and protect shared retained capacity."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

import agent_console_attachments as files
import mentat_db
import private_console_unit as backups
from private_state import private_state_lock
import project_context as context
import project_context_editor as editor
import project_output_reservations as outputs
import project_scope_journal as scopes
import project_worker_journal as journal
from run_repository import RunRepository, RunRepositoryError
from task_repository import _schema5_private_unit
from tests import test_project_worker_journal as fixtures
from tests import test_project_scope_journal as scope_fixtures

_RETAINED_STALLED_FIXTURES = []


class OutputReservationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProjectWorkerJournalTests()
        self.fixture.setUp()
        fixture = self.fixture
        self.addCleanup(lambda: fixture.doCleanups() if not any(fixture is item for item in _RETAINED_STALLED_FIXTURES) else None)
        self.root = self.fixture.root
        self.run = self.fixture._prepare(reserve_output=False)

    def reserve(self):
        with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            result = outputs.reserve_output(connection, run_id=self.run, generation=fixtures.GENERATION)
            connection.commit()
            return result

    def _row(self):
        with closing(mentat_db.connect(self.root)) as connection:
            row = connection.execute('SELECT * FROM mentat_project_output_reservations').fetchone()
            return tuple(row) if row else None

    def test_original_holder_is_secret_and_duplicate_cannot_reissue_or_release(self):
        first = self.reserve()
        repeated = self.reserve()
        self.assertTrue(first.changed)
        self.assertFalse(repeated.changed)
        self.assertIsNone(repeated.holder_token)
        self.assertNotIn(first.holder_token, repr(first))
        row = self._row()
        self.assertNotIn(first.holder_token, repr(row))
        self.assertEqual(row[8], hashlib.sha256(first.holder_token.encode()).hexdigest())
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(outputs.pending_capacity(connection), (1, 32768))
            charged = outputs.validate_output_reservations_connection(connection)
            self.assertEqual(len(charged[0][1]), outputs.METADATA_CHARGE - 128)
            for sql in ('UPDATE mentat_project_output_reservations SET max_bytes=1',
                        'DELETE FROM mentat_project_output_reservations'):
                with self.assertRaises(sqlite3.IntegrityError): connection.execute(sql)
            with self.assertRaises(RunRepositoryError): RunRepository(connection).validate()
            RunRepository(connection).validate(private_archival_proposals=True)
            self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='mentat_runs_project_proposal_closed_insert'").fetchone())
        self.assertEqual(self._row(), row)

    def test_no_scope_or_call_can_begin_without_precharged_capacity(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            with self.assertRaises(outputs.OutputReservationError):
                scopes.prepare_scope(connection, run_id=self.run, generation=fixtures.GENERATION,
                                     plan_witness=scope_fixtures.planned_fixture().journal_plan())
            with self.assertRaises(outputs.OutputReservationError):
                journal.reserve_call(connection, run_id=self.run, generation=fixtures.GENERATION, request_digest=fixtures.REQUEST)
            connection.commit()
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_worker_scopes').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_worker_calls').fetchone()[0], 0)
        self.reserve()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            scopes.prepare_scope(connection, run_id=self.run, generation=fixtures.GENERATION,
                                 plan_witness=scope_fixtures.planned_fixture().journal_plan())
            journal.reserve_call(connection, run_id=self.run, generation=fixtures.GENERATION, request_digest=fixtures.REQUEST)
            connection.commit()

    def test_late_reservation_cannot_retrofit_old_work(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            # Exact historical schema44 graph: omit the later reservation, then
            # restore version45. No production operation bypass is introduced.
            with patch.object(outputs, 'require_output_reservation', return_value=(None,)*10+(0,)):
                scopes.prepare_scope(connection, run_id=self.run, generation=fixtures.GENERATION,
                                     plan_witness=scope_fixtures.planned_fixture().journal_plan())
            connection.commit()
        with self.assertRaisesRegex(outputs.OutputReservationError, 'late'): self.reserve()
        self.assertIsNone(self._row())

    def test_concurrent_same_generation_has_one_holder_and_one_hold(self):
        results, errors = [], []
        def attempt():
            try: results.append(self.reserve())
            except BaseException as exc: errors.append(exc)
        threads = [threading.Thread(target=attempt) for _ in range(2)]
        try:
            for thread in threads: thread.start()
        finally:
            for thread in threads:
                if thread.ident is not None: thread.join(20)
            if any(thread.is_alive() for thread in threads):
                _RETAINED_STALLED_FIXTURES.append(self.fixture)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sum(item.changed for item in results), 1)
        self.assertEqual(sum(item.holder_token is not None for item in results), 1)

    def test_late_capacity_failure_rolls_back_even_if_caller_commits(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            original = journal._validate_shared_graph
            def fail_after_insert(handle):
                original(handle)
                if handle.execute('SELECT 1 FROM mentat_project_output_reservations').fetchone():
                    raise context.ProjectContextError('project_context.capacity')
            with patch.object(journal, '_validate_shared_graph', side_effect=fail_after_insert):
                with self.assertRaises(context.ProjectContextError):
                    outputs.reserve_output(connection, run_id=self.run, generation=fixtures.GENERATION)
            connection.commit()
        self.assertIsNone(self._row())

    def test_separately_committed_equal_tick_work_is_valid_but_earlier_work_is_rejected(self):
        self.reserve()
        retained = self._row()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            outputs.require_output_reservation(connection,self.run,fixtures.GENERATION)
            scopes.prepare_scope(connection,run_id=self.run,generation=fixtures.GENERATION,
                plan_witness=scope_fixtures.planned_fixture().journal_plan(),now=retained[10])
            journal.reserve_call(connection,run_id=self.run,generation=fixtures.GENERATION,
                                 request_digest=fixtures.REQUEST,now=retained[10])
            outputs.validate_output_reservations_connection(connection)
            connection.commit()
            connection.execute('BEGIN IMMEDIATE')
            parent=connection.execute('SELECT claim_digest FROM mentat_project_worker_generations').fetchone()[0]
            created=retained[10]+1
            digest=journal._digest([*retained[:2],retained[2].hex(),*retained[3:9],parent,created])
            trigger=connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_project_output_reservation_immutable'").fetchone()[0]
            connection.execute('DROP TRIGGER mentat_project_output_reservation_immutable')
            connection.execute('UPDATE mentat_project_output_reservations SET created_at=?,reservation_digest=?',(created,digest))
            connection.execute(trigger)
            with self.assertRaisesRegex(outputs.OutputReservationError,'late'):
                outputs.validate_output_reservations_connection(connection)
            connection.rollback()

    def test_maximum_parser_snapshot_escape_representation_fits_precharge(self):
        import project_proposal_artifact as parser
        value={'version':1,'summary':'界'+('\\\n'*900),'questions':[],
               'tasks':[{'title':str(index),'description':'start'+('\t\\'*1400),
                         'agent_id':None,'due_date':None,'after':[]} for index in range(5)]}
        canonical=parser._snapshot_bytes(parser.parse_proposal_artifact(parser._snapshot_bytes(value)))
        self.assertGreater(len(canonical),28*1024)
        embedded=json.dumps(canonical.decode('utf-8'),ensure_ascii=False).encode('utf-8')
        self.assertLessEqual(len(embedded),2*parser.MAX_ARTIFACT_BYTES+2)
        self.assertLess(len(embedded)+48*1024,outputs.METADATA_CHARGE)

    def test_failed_first_hold_preserves_full_retained_store(self):
        with closing(mentat_db.connect(self.root)) as connection:
            retained=connection.execute('SELECT COUNT(DISTINCT a.blob_id) FROM attachments a JOIN mentat_retained_attachments r ON r.attachment_id=a.id').fetchone()[0]
        with patch.object(context,'MAX_RETAINED_BLOBS',retained):
            with self.assertRaisesRegex(context.ProjectContextError,'blob_capacity'): self.reserve()
        self.assertIsNone(self._row())

    def test_revoked_grant_fences_new_hold_without_releasing_existing_charges(self):
        self.reserve()
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("UPDATE mentat_project_context_grants SET state='revoked',reason='owner',revision=revision+1,updated_at=updated_at+1")
            connection.commit()
            self.assertEqual(outputs.pending_capacity(connection),(1,32768))
        with self.assertRaises(journal.WorkerJournalError): self.reserve()

    def _retain_files(self, count, size=32):
        ids = [files.create_attachment(self.root, original_name='capacity.txt',
                                      content=(str(index).encode() + b'x' * size))['id'] for index in range(count)]
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            for index, identifier in enumerate(ids):
                connection.execute("INSERT INTO run_attachments VALUES('run_capacity_fixture',?,'input',?,1)", (identifier,index))
                connection.execute("UPDATE attachments SET state='attached',expires_at=NULL WHERE id=?", (identifier,))
            context.validate_retained_capacity(connection)
            connection.commit()
        return ids

    def test_last_blob_slot_protects_console_project_and_staging_writers_but_allows_dedup(self):
        # The planning fixture already retains one file. Keep 99 distinct blobs
        # and one pending output slot, then attempt each other retention path.
        ids = self._retain_files(98)
        self.reserve()
        candidate = files.create_attachment(self.root, original_name='extra.txt', content=b'new distinct blob')['id']
        with self.assertRaises(files.AttachmentUnavailable):
            files.bind_run_attachment(self.root,candidate,'run_capacity_extra')
        with closing(mentat_db.connect(self.root)) as connection:
            current = connection.execute('SELECT revision FROM mentat_project_context_scopes WHERE retired_at IS NULL').fetchone()[0]
        with self.assertRaisesRegex(context.ProjectContextError,'blob_capacity'):
            context.publish_project_context(self.root,'project_mentat',expected_project_revision=1,
                expected_revision=current,brief='new',attachment_ids=[candidate])
        with self.assertRaises(editor.ProjectContextEditorError):
            editor.stage_project_file(self.root,'project_mentat',expected_project_revision=1,
                                      original_name='staged.txt',content=b'another distinct blob')
        files.bind_run_attachment(self.root,ids[0],'run_capacity_dedup')
        self.assertEqual(files.get_attachment(self.root,candidate)['state'],'staged')
        with closing(mentat_db.connect(self.root)) as connection:
            context.validate_retained_capacity(connection)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_context_staged').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT COUNT(DISTINCT a.blob_id) FROM attachments a JOIN mentat_retained_attachments r ON r.attachment_id=a.id').fetchone()[0],99)

    def test_byte_hold_prevents_consume_last_bytes_and_reservation_refuses_full_store(self):
        self.reserve()
        candidate = files.create_attachment(self.root, original_name='large.txt',content=b'z'*1024)['id']
        with closing(mentat_db.connect(self.root)) as connection:
            retained = connection.execute('SELECT SUM(byte_size) FROM blobs WHERE id IN (SELECT a.blob_id FROM attachments a JOIN mentat_retained_attachments r ON r.attachment_id=a.id)').fetchone()[0]
        # Exercise the byte edge without writing a 24MiB fixture; slot capacity
        # above is tested against the actual public limit with real blob bytes.
        with patch.object(files,'MAX_RETAINED_BLOB_BYTES',retained+32768+1023):
            with self.assertRaises(files.AttachmentUnavailable): files.bind_run_attachment(self.root,candidate,'run_bytes')
        with closing(mentat_db.connect(self.root)) as connection:
            with patch.object(context,'MAX_RETAINED_BLOB_BYTES',retained+32767):
                with self.assertRaisesRegex(context.ProjectContextError,'blob_capacity'):
                    context.validate_retained_capacity(connection)

    def test_backup_restore_preserves_hold_hash_and_fences_original_epoch(self):
        first = self.reserve()
        original = self._row()
        source_tasks = (self.root/'tasks.json').read_bytes()
        unit = backups.capture_private_console_unit(self.root)
        backups.validate_private_console_unit(unit)
        restored = backups.sanitize_owner_auth_restore_unit(unit)
        with TemporaryDirectory() as temporary:
            target=Path(temporary)
            (target/'private').mkdir(mode=0o700)
            backups.materialize_private_console_unit(target,restored,target/'private'/'console')
            with closing(mentat_db.connect(target)) as connection:
                self.assertEqual(tuple(connection.execute('SELECT * FROM mentat_project_output_reservations').fetchone()),original)
                self.assertEqual(outputs.pending_capacity(connection),(1,32768))
                with self.assertRaises(outputs.OutputReservationError):
                    outputs.require_output_reservation(connection,self.run,fixtures.GENERATION)
                connection.execute('BEGIN IMMEDIATE')
                with self.assertRaises(journal.WorkerJournalError):
                    outputs.reserve_output(connection,run_id=self.run,generation=fixtures.GENERATION)
                connection.rollback()
            compatible=_schema5_private_unit(unit)
            with closing(sqlite3.connect(':memory:')) as connection:
                connection.deserialize(compatible.database_raw)
                self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='mentat_project_output_reservations'").fetchone())
        self.assertEqual(self._row(),original)
        self.assertNotIn(first.holder_token,repr(unit))
        self.assertEqual((self.root/'tasks.json').read_bytes(),source_tasks)

    def test_exact_schema44_migrates_empty_without_invented_holders_and_ddl_failure_rolls_back(self):
        for drift in (False,True):
            with self.subTest(drift=drift), TemporaryDirectory() as temporary:
                path=Path(temporary)/'old.sqlite'
                backups._initialize_database(path,schema_version=44)
                with closing(sqlite3.connect(path)) as connection:
                    if drift:
                        connection.execute('ALTER TABLE mentat_runs ADD COLUMN invalid_extra TEXT')
                        connection.commit()
                    before=list(connection.iterdump())
                    execute=mentat_db._execute_script_in_active_transaction
                    def fail_after_ddl(active,script):
                        execute(active,script)
                        if script==dict(mentat_db.MIGRATIONS)[45]: raise RuntimeError('after output DDL')
                    if drift:
                        with self.assertRaises(mentat_db.MentatDatabaseError): mentat_db.migrate(connection)
                    else:
                        with patch.object(mentat_db,'_execute_script_in_active_transaction',side_effect=fail_after_ddl):
                            with self.assertRaisesRegex(RuntimeError,'after output DDL'): mentat_db.migrate(connection)
                    self.assertEqual(list(connection.iterdump()),before)
                    self.assertFalse(connection.in_transaction)
                    if not drift:
                        mentat_db.migrate(connection)
                        self.assertEqual(mentat_db.schema_signature_state(connection,45),'expected')
                        self.assertEqual(outputs.pending_capacity(connection),(0,0))
                        self.assertIn('mentat_project_output_reservations',{row[0] for row in mentat_db._run_source_migration_snapshot(connection)})

    def test_populated_historical_schema44_backup_retains_work_without_inventing_a_hold(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            # Reproduce the previously supported dormant source graph, without
            # launching a process or submitting any synthetic/provider work.
            with patch.object(outputs,'require_output_reservation',return_value=(None,)*10+(0,)):
                scopes.prepare_scope(connection,run_id=self.run,generation=fixtures.GENERATION,
                                     plan_witness=scope_fixtures.planned_fixture().journal_plan())
                call=journal.reserve_call(connection,run_id=self.run,generation=fixtures.GENERATION,request_digest=fixtures.REQUEST)
                journal.record_submission(connection,call_id=call.call_id,generation=fixtures.GENERATION,
                    request_digest=fixtures.REQUEST,settlement_token=call.settlement_token)
            connection.execute('DROP TRIGGER mentat_project_output_reservation_immutable')
            connection.execute('DROP TRIGGER mentat_project_output_reservation_retained')
            connection.execute('DROP TABLE mentat_project_output_reservations')
            connection.execute('DELETE FROM schema_migrations WHERE version=45')
            connection.commit()
            self.assertEqual(mentat_db.schema_signature_state(connection,44),'expected')
            prior_call=tuple(connection.execute('SELECT * FROM mentat_project_worker_calls').fetchone())
            prior_scope=tuple(connection.execute('SELECT * FROM mentat_project_worker_scopes').fetchone())
        from private_state import database_path
        before={item.name:item.read_bytes() for item in database_path(self.root).parent.glob('mentat.sqlite3*')}
        unit=backups.capture_private_console_unit(self.root,harden_source=False,copy_sqlite_source=True)
        backups.validate_private_console_unit(unit)
        self.assertEqual({item.name:item.read_bytes() for item in database_path(self.root).parent.glob('mentat.sqlite3*')},before)
        with TemporaryDirectory() as temporary:
            copied=Path(temporary)/'old44.sqlite'
            copied.write_bytes(unit.database_raw)
            with closing(sqlite3.connect(copied)) as connection:
                self.assertEqual(mentat_db.schema_signature_state(connection,44),'expected')
                self.assertEqual(tuple(connection.execute('SELECT * FROM mentat_project_worker_calls').fetchone()),prior_call)
                self.assertEqual(tuple(connection.execute('SELECT * FROM mentat_project_worker_scopes').fetchone()),prior_scope)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(mentat_db.schema_signature_state(connection,45),'expected')
            self.assertEqual(outputs.pending_capacity(connection),(0,0))
            self.assertEqual(tuple(connection.execute('SELECT * FROM mentat_project_worker_calls').fetchone()),prior_call)
            self.assertEqual(tuple(connection.execute('SELECT * FROM mentat_project_worker_scopes').fetchone()),prior_scope)
            connection.execute('BEGIN IMMEDIATE')
            with self.assertRaisesRegex(outputs.OutputReservationError,'late'):
                outputs.reserve_output(connection,run_id=self.run,generation=fixtures.GENERATION)
            connection.rollback()


if __name__=='__main__': unittest.main()
