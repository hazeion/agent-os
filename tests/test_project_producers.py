"""Actual stock-Hermes qualification producer, never production admission."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import threading
import unittest

import mentat_db
import project_inference_broker as broker
import project_producers as producers
import project_scope_journal as scopes
import project_output_reservations as holds
from private_state import private_state_lock
from run_repository import RunRepository,RunRepositoryError
from mentat.project_runtime_image import ImmutableRuntimeImage
from mentat.project_worker_namespace import PreparedNamespace,RuntimeRoots
from mentat.project_worker_scope import LinuxWorkerScope,WorkerScopeLimits
from tests import test_project_inference_broker as fixtures
from tests.test_project_worker_journal import GENERATION

PROPOSAL={'version':1,'summary':'Organize supplied garage goals','questions':[],
          'tasks':[{'title':'Research garage storage','description':'Compare safe storage options',
                    'agent_id':None,'due_date':None,'after':[]}]}
_RETAINED_PRODUCER_FIXTURES=[]


@unittest.skipUnless(sys.platform=='linux','Actual Linux scoped producer required')
class ProducerIntegrationTests(unittest.TestCase):
    def setUp(self):
        required=('MENTAT_TEST_RUNTIME_IMAGE','MENTAT_TEST_RUNTIME_IMAGE_SHA256')
        if not all(os.environ.get(key) for key in required): self.skipTest('Public sealed candidate unavailable')
        self.fixture=fixtures.ProjectInferenceBrokerTests()
        self._retain=False
        from unittest.mock import patch
        from tests import test_project_proposal_input_receipts as input_fixtures
        original=input_fixtures.ProjectProposalInputReceiptTests._insert_consistent_receipt
        def with_capacity(instance,connection):
            from run_repository import default_runtime_capacity_evidence
            binding=connection.execute('SELECT binding_digest FROM mentat_project_planning_input_versions WHERE id=?',(instance.input_id,)).fetchone()[0]
            instance.producer_capacity=default_runtime_capacity_evidence(runtime_type='hermes',binding_digest=binding)
            return original(instance,connection)
        with patch.object(input_fixtures.ProjectProposalInputReceiptTests,'_insert_consistent_receipt',with_capacity):
            self.fixture.setUp()
        self.addCleanup(lambda: self.fixture.doCleanups() if not self._retain else None)
        self.root,self.run=self.fixture.root,self.fixture.run
        self.image=ImmutableRuntimeImage(Path(os.environ[required[0]]),os.environ[required[1]])
        self.addCleanup(self.image.close)
        from mentat.project_runtime_origin import VIRTUAL
        roots=RuntimeRoots(*(Path(VIRTUAL)/kind for kind in ('source','venv','python')))
        self.prepared=PreparedNamespace(roots,self.fixture.inputs.query,hashlib.sha256(self.fixture.inputs.query).hexdigest(),
            'mentat-probe',runtime_image=self.image,sealed_libraries=True)
        self.addCleanup(self.prepared.close)
        self.holder=self.fixture.fixture.output_reservation.holder_token
        with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            producers.bind_qualification_producer(connection,self.root,run_id=self.run,generation=GENERATION,
                prepared=self.prepared,holder_token=self.holder)
            connection.commit()

    def execute(self,text,*,before_capture=None):
        scope=LinuxWorkerScope(WorkerScopeLimits(wall_seconds=20))
        host,worker=socket.socketpair()
        actual=None
        thread=None
        receipt=None
        try:
            with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                token,revision=producers.record_start_intent(connection,run_id=self.run,generation=GENERATION,
                    holder_token=self.holder,expected_revision=1,plan_witness=scope.journal_plan())
                connection.commit()
            scope.start_inert()
            with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                owned_revision=producers.record_owned_scope(connection,run_id=self.run,generation=GENERATION,
                    holder_token=self.holder,scope_token=token,scope_revision=revision,
                    witness=scope.journal_owned_identity(),expected_revision=2)
                connection.commit()
            receipt=(token,owned_revision)
            backend=broker.SyntheticCompletionBackend(text)
            actual=broker.QualificationInferenceBroker(self.root,self.run,GENERATION,backend,scope)
            thread=threading.Thread(target=actual.serve,args=(host,))
            thread.start()
            handle=scope.handoff_namespace(self.prepared,worker)
            self.prepared.close()
            self.assertEqual(handle.wait()['text'],text)
            scope.close_verified()
            witness=handle.completion_witness()
            if before_capture is not None:
                before_capture(witness,receipt)
            digest=producers.register_output(self.root,run_id=self.run,generation=GENERATION,
                holder_token=self.holder,scope_token=receipt[0],scope_revision=receipt[1],expected_revision=3,witness=witness)
            self.assertEqual(backend.calls,1)
            return digest,witness,receipt
        finally:
            errors=[]
            if actual is not None:
                try: actual.stop()
                except BaseException as error: errors.append(error)
            try:
                if not scope._closed: scope.close_verified()
                if receipt is not None:
                    with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                        state=scopes.read_scope(connection,self.run)
                        if state.state!='stopped':
                            connection.execute('BEGIN IMMEDIATE')
                            scopes.transition_scope(connection,run_id=self.run,generation=GENERATION,
                                claim_token=receipt[0],expected_revision=state.revision,target='stopped',witness=scope.journal_closed_identity(),
                                producer_context=producers._SCOPE_MUTATION)
                            connection.commit()
            except BaseException as error: errors.append(error)
            finally:
                host.close()
                worker.close()
                if thread is not None: thread.join(5)
                if not scope._closed or thread is not None and thread.is_alive():
                    self._retain=True
                    _RETAINED_PRODUCER_FIXTURES.append((self.fixture,scope,actual,thread))
            if errors: raise errors[0]
            self.assertFalse(self._retain)

    def test_natural_completion_registers_blob_parser_run_and_capacity_atomically(self):
        text=json.dumps(PROPOSAL,separators=(',',':'))
        digest,witness,receipt=self.execute(text)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(tuple(connection.execute('SELECT status,dispatch_state,terminal_finalized FROM mentat_runs WHERE id=?',(self.run,)).fetchone()),('completed','accepted',1))
            RunRepository(connection).validate(private_producer_proposals=True)
            with self.assertRaises(RunRepositoryError): RunRepository(connection).validate()
            self.assertEqual(holds.pending_capacity(connection),(0,0))
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_retained_attachments').fetchone()[0],2)
            self.assertEqual(connection.execute('SELECT receipt_digest FROM mentat_project_producer_outputs').fetchone()[0],digest)
        self.assertEqual(producers.register_output(self.root,run_id=self.run,generation=GENERATION,
            holder_token=self.holder,scope_token=receipt[0],scope_revision=receipt[1],expected_revision=3,witness=witness),digest)

    def test_committed_capture_refuses_changed_generation_holder_scope_or_revision(self):
        digest,witness,receipt=self.execute(json.dumps(PROPOSAL,separators=(',',':')))
        base={'run_id':self.run,'generation':GENERATION,'holder_token':self.holder,
              'scope_token':receipt[0],'scope_revision':receipt[1],'expected_revision':3,'witness':witness}
        for change in ({'generation':'d'*32},{'holder_token':'f'*64},{'scope_token':'e'*64},
                       {'scope_revision':4},{'expected_revision':2}):
            with self.subTest(change=change),self.assertRaises(producers.journal.WorkerJournalError):
                producers.register_output(self.root,**{**base,**change})
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT receipt_digest FROM mentat_project_producer_outputs').fetchone()[0],digest)

    def test_prelaunch_stop_and_cancel_release_no_execution_and_no_result(self):
        with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            producers.request_stop(connection,run_id=self.run,generation=GENERATION,holder_token=self.holder,expected_revision=1)
            connection.commit()
            RunRepository(connection).validate(private_producer_proposals=True)
            self.assertEqual(holds.pending_capacity(connection),(1,32768))
            connection.execute('BEGIN IMMEDIATE')
            producers.settle_without_output(connection,run_id=self.run,generation=GENERATION,
                holder_token=self.holder,expected_revision=2,disposition='cancelled')
            connection.commit()
            RunRepository(connection).validate(private_producer_proposals=True)
            self.assertEqual(holds.pending_capacity(connection),(0,0))
            self.assertEqual(connection.execute('SELECT status FROM mentat_runs').fetchone()[0],'cancelled')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_worker_calls').fetchone()[0],0)

    def test_stop_survives_grant_revocation_and_epoch_rotation(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute("UPDATE mentat_project_context_grants SET state='revoked',reason='owner',revision=revision+1,updated_at=updated_at+1")
            connection.execute('UPDATE mentat_project_context_access_state SET approval_epoch=?',(b'z'*32,))
            connection.commit()
        with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            producers.request_stop(connection,run_id=self.run,generation=GENERATION,holder_token=self.holder,expected_revision=1)
            connection.commit()
            self.assertEqual(connection.execute('SELECT status FROM mentat_runs').fetchone()[0],'unknown')
            self.assertEqual(holds.pending_capacity(connection),(1,32768))

    def test_completed_source_survives_private_backup_and_schema5_omission(self):
        self.execute(json.dumps(PROPOSAL,separators=(',',':')))
        import private_console_unit as backups
        from task_repository import _schema5_private_unit
        unit=backups.capture_private_console_unit(self.root)
        backups.validate_private_console_unit(unit)
        self.assertEqual(json.loads(unit.history_raw)['runs'],[])
        self.assertEqual(len(unit.blobs),2)
        compatible=_schema5_private_unit(unit)
        self.assertEqual(compatible.blobs,())
        readback=producers.read_registered_output(self.root,run_id=self.run,generation=GENERATION)
        self.assertEqual(readback['snapshot'],PROPOSAL)
        self.assertEqual(producers.read_registered_output(self.root,run_id=self.run,generation=GENERATION,
            request_digest=readback['request_digest']),readback)
        with self.assertRaises(producers.ProducerError):
            producers.read_registered_output(self.root,run_id=self.run,generation=GENERATION,request_digest='f'*64)

    def test_start_intent_is_atomic_and_scope_only_mutation_is_refused(self):
        scope=LinuxWorkerScope(WorkerScopeLimits(wall_seconds=20))
        try:
            with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                with self.assertRaises(scopes.ScopeJournalError):
                    scopes.prepare_scope(connection,run_id=self.run,generation=GENERATION,plan_witness=scope.journal_plan())
                connection.commit()
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_worker_scopes').fetchone()[0],0)
                connection.execute('BEGIN IMMEDIATE')
                producers.record_start_intent(connection,run_id=self.run,generation=GENERATION,
                    holder_token=self.holder,expected_revision=1,plan_witness=scope.journal_plan())
                connection.commit()
                RunRepository(connection).validate(private_producer_proposals=True)
            import private_console_unit as backups
            unit=backups.capture_private_console_unit(self.root)
            backups.validate_private_console_unit(unit)
            with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                producers.mark_uncertain(connection,run_id=self.run,generation=GENERATION,
                    holder_token=self.holder,expected_revision=2)
                connection.commit()
                RunRepository(connection).validate(private_producer_proposals=True)
                self.assertEqual(holds.pending_capacity(connection),(1,32768))
        finally: scope.close_verified()

    def test_starting_scope_closes_without_inventing_an_owned_run_or_provider_call(self):
        scope=LinuxWorkerScope(WorkerScopeLimits(wall_seconds=20))
        try:
            with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                token,revision=producers.record_start_intent(connection,run_id=self.run,generation=GENERATION,
                    holder_token=self.holder,expected_revision=1,plan_witness=scope.journal_plan())
                connection.commit()
            scope.start_inert()
            with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                producers.request_stop(connection,run_id=self.run,generation=GENERATION,
                    holder_token=self.holder,expected_revision=2)
                connection.commit()
            scope.close_verified()
            with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                producers.settle_without_output(connection,run_id=self.run,generation=GENERATION,
                    holder_token=self.holder,expected_revision=3,disposition='stopped',scope_token=token,
                    scope_revision=revision,closure_witness=scope.journal_closed_identity())
                connection.commit()
                RunRepository(connection).validate(private_producer_proposals=True)
                self.assertEqual(tuple(connection.execute('SELECT status,started_at FROM mentat_runs').fetchone()),('stopped',None))
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_worker_calls').fetchone()[0],0)
                self.assertEqual(holds.pending_capacity(connection),(0,0))
        finally:
            if not scope._closed: scope.close_verified()

    def test_bound_producer_cannot_debit_before_owned_phase(self):
        from tests.test_project_worker_journal import REQUEST
        with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            with self.assertRaises(producers.ProducerError):
                producers.journal.reserve_call(connection,run_id=self.run,generation=GENERATION,request_digest=REQUEST)
            connection.commit()
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_worker_calls').fetchone()[0],0)

    def test_valid_questions_complete_run_but_remain_in_retained_snapshot(self):
        value={'version':1,'summary':'Need supplied measurements','questions':[
            {'kind':'measurement','text':'What are the usable garage dimensions?'}],'tasks':[]}
        self.execute(json.dumps(value,separators=(',',':')))
        with closing(mentat_db.connect(self.root)) as connection:
            body=json.loads(connection.execute('SELECT body_json FROM mentat_project_producer_outputs').fetchone()[0])
            self.assertEqual(body['snapshot']['questions'],value['questions'])
            self.assertEqual(connection.execute('SELECT status FROM mentat_runs').fetchone()[0],'completed')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_plan_versions').fetchone()[0],0)

    def test_invalid_artifact_is_retained_as_failure_without_parser_authority(self):
        self.execute('not a proposal')
        with closing(mentat_db.connect(self.root)) as connection:
            body=json.loads(connection.execute('SELECT body_json FROM mentat_project_producer_outputs').fetchone()[0])
            self.assertEqual((body['disposition'],body['snapshot']),('invalid_artifact',None))
            self.assertEqual(connection.execute('SELECT status FROM mentat_runs').fetchone()[0],'failed')
            self.assertEqual(holds.pending_capacity(connection),(0,0))

    def test_stop_wins_before_late_natural_result_conversion(self):
        def stopped(witness,receipt):
            with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                producers.request_stop(connection,run_id=self.run,generation=GENERATION,
                    holder_token=self.holder,expected_revision=3)
                connection.commit()
        with self.assertRaises(producers.journal.WorkerJournalError):
            self.execute(json.dumps(PROPOSAL,separators=(',',':')),before_capture=stopped)
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT status FROM mentat_runs').fetchone()[0],'unknown')
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_producer_outputs').fetchone()[0],0)
            self.assertEqual(holds.pending_capacity(connection),(1,32768))

    def test_output_and_run_roll_back_if_last_precommit_guard_consumes_deadline(self):
        from unittest.mock import patch
        from task_repository import _DatabaseIdentityGuard,TaskRepositoryUnavailable
        witness_holder={}
        original=_DatabaseIdentityGuard.verify
        def expired_after_verify(guard,expected):
            original(guard,expected)
            if 'witness' in witness_holder:
                from mentat import project_namespace_evidence as evidence
                witness=witness_holder['witness']
                # Only the final conversion transaction reaches this check with
                # uncommitted output rows. Opening/cleanup guards stay normal.
                if guard.connection.in_transaction and guard.connection.execute('SELECT COUNT(*) FROM mentat_project_producer_outputs').fetchone()[0]:
                    witness_holder['clock']=patch.object(evidence.time,'monotonic',return_value=witness._deadline)
                    witness_holder['clock'].start()
        try:
            with patch.object(_DatabaseIdentityGuard,'verify',expired_after_verify):
                with self.assertRaises(TaskRepositoryUnavailable):
                    self.execute(json.dumps(PROPOSAL,separators=(',',':')),
                        before_capture=lambda witness,receipt:witness_holder.update(witness=witness))
        finally:
            if 'clock' in witness_holder: witness_holder['clock'].stop()
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_producer_outputs').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT status FROM mentat_runs').fetchone()[0],'running')

    def test_active_restore_preserves_hold_and_refuses_original_forward_authority(self):
        import private_console_unit as backups
        from tempfile import TemporaryDirectory
        from private_state import history_path
        from run_repository import ensure_run_sqlite_authority
        scope=LinuxWorkerScope(WorkerScopeLimits(wall_seconds=20))
        try:
            with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                connection.execute('BEGIN IMMEDIATE')
                producers.record_start_intent(connection,run_id=self.run,generation=GENERATION,
                    holder_token=self.holder,expected_revision=1,plan_witness=scope.journal_plan())
                connection.commit()
            unit=backups.capture_private_console_unit(self.root)
            restored=backups.sanitize_owner_auth_restore_unit(unit)
            with TemporaryDirectory() as temporary:
                target=Path(temporary)
                (target/'private').mkdir(mode=0o700)
                backups.materialize_private_console_unit(target,restored,target/'private'/'console')
                with closing(mentat_db.connect(target)) as connection:
                    RunRepository(connection).validate(private_producer_proposals=True)
                    self.assertEqual(holds.pending_capacity(connection),(1,32768))
                    connection.execute('BEGIN IMMEDIATE')
                    with self.assertRaises(producers.journal.WorkerJournalError):
                        producers.record_start_intent(connection,run_id=self.run,generation=GENERATION,
                            holder_token=self.holder,expected_revision=1,plan_witness=scope.journal_plan())
                    connection.rollback()
                    connection.execute('BEGIN IMMEDIATE')
                    producers.request_stop(connection,run_id=self.run,generation=GENERATION,
                        holder_token=self.holder,expected_revision=2)
                    connection.commit()
                    connection.execute('BEGIN IMMEDIATE')
                    with self.assertRaises(producers.ProducerError):
                        producers.settle_without_output(connection,run_id=self.run,generation=GENERATION,
                            holder_token=self.holder,expected_revision=3,disposition='cancelled')
                    connection.rollback()
                    self.assertEqual(holds.pending_capacity(connection),(1,32768))
                with self.assertRaises(RunRepositoryError): ensure_run_sqlite_authority(target,history_path(target))
        finally: scope.close_verified()

    def test_tampered_self_consistent_query_binding_fails_private_byte_provenance(self):
        import private_console_unit as backups
        from dataclasses import replace
        from tempfile import TemporaryDirectory
        import sqlite3
        unit=backups.capture_private_console_unit(self.root)
        with TemporaryDirectory() as temporary:
            path=Path(temporary)/'tampered.sqlite'
            path.write_bytes(unit.database_raw)
            with closing(sqlite3.connect(path)) as connection:
                body=json.loads(connection.execute('SELECT body_json FROM mentat_project_producer_bindings').fetchone()[0])
                body['query_digest']='f'*64
                trigger=connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_project_producer_binding_immutable'").fetchone()[0]
                connection.execute('DROP TRIGGER mentat_project_producer_binding_immutable')
                connection.execute('UPDATE mentat_project_producer_bindings SET body_json=?,receipt_digest=?',
                    (producers.journal._encoded(body),producers.journal._digest(body)))
                connection.execute(trigger)
                connection.commit()
            with self.assertRaises(backups.PrivateConsoleUnitError):
                backups.validate_private_console_unit(replace(unit,database_raw=path.read_bytes()))


if __name__=='__main__': unittest.main()
