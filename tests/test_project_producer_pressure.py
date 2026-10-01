"""Synthetic SQL pressure gates; no provider, worker launch or production admission."""
from contextlib import closing
import hashlib
import json
import threading
import unittest
from unittest.mock import patch

import agent_console_attachments as files
import mentat_db
import project_context as context
import project_context_editor as editor
import project_inference_broker as broker
import project_output_reservations as holds
import project_producers as producers
import project_scope_journal as scopes
import project_worker_journal as journal
import run_repository as runs
from private_state import console_root, private_state_lock
from mentat.project_scope_evidence import _issue as issue_scope
from tests import test_project_worker_journal as fixtures
from tests import test_project_proposal_input_receipts as input_fixtures
from tests import test_project_scope_journal as scope_fixtures
from tests import test_run_repository as run_fixtures
from tests import test_task_inputs as task_fixtures
from agent_registry import AgentRegistry

_RETAINED_PRESSURE_FIXTURES = []


def insert_row(connection, table, row):
    connection.execute('INSERT INTO '+table+'('+','.join(row)+') VALUES('+','.join('?' for _ in row)+')', tuple(row.values()))


class ProducerPressureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProjectWorkerJournalTests()
        class HermesRegistry:
            def __init__(self, root, **_):
                self.registry=AgentRegistry(root,supported_runtime_types=("hermes",))
            def create_agent(self, **kwargs):
                kwargs["runtime_type"]="hermes"
                return self.registry.create_agent(**kwargs)
        with patch.object(task_fixtures,"AgentRegistry",HermesRegistry):
            self.fixture.setUp()
        self.retained = False
        self.addCleanup(lambda: self.fixture.doCleanups() if not self.retained else None)
        original = input_fixtures.ProjectProposalInputReceiptTests._insert_consistent_receipt
        def prepared_capacity(instance, connection):
            binding = connection.execute('SELECT binding_digest FROM mentat_project_planning_input_versions WHERE id=?', (instance.input_id,)).fetchone()[0]
            instance.producer_capacity = runs.default_runtime_capacity_evidence(runtime_type='hermes', binding_digest=binding)
            return original(instance, connection)
        with patch.object(input_fixtures.ProjectProposalInputReceiptTests, '_insert_consistent_receipt', prepared_capacity):
            self.run = self.fixture._prepare()
        self.root = self.fixture.root
        self.holder = self.fixture.output_reservation.holder_token
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            inputs, _, _ = broker._derive_inputs(self.root, connection, self.run, fixtures.GENERATION)
            parent = connection.execute('SELECT * FROM mentat_project_worker_generations').fetchone()
            receipt = connection.execute('SELECT qualification_digest,authorization_digest FROM mentat_project_proposal_input_receipts').fetchone()
            incarnation = connection.execute('SELECT incarnation FROM mentat_run_identities').fetchone()[0]
            identity = console_root(self.root).stat()
            capacity, limit = runs.default_runtime_capacity_evidence(runtime_type='hermes', binding_digest=parent[5])
            body = {'format':1, 'purpose':'qualification', 'run_id':self.run, 'generation':fixtures.GENERATION,
                'run_incarnation':incarnation, 'authority_epoch':parent[3].hex(), 'input_manifest':parent[4],
                'qualification_digest':receipt[0], 'authorization_digest':receipt[1],
                'query_digest':hashlib.sha256(inputs.query).hexdigest(), 'image_digest':inputs.image_digest,
                'runtime_image_digest':'d'*64, 'model_digest':journal._digest(json.loads(parent[8])),
                'capacity_scope_digest':capacity, 'capacity_limit':limit, 'root_identity':[identity.st_dev,identity.st_ino]}
            # A historical SQL fixture only: the runtime digest is inert and
            # makes no assertion that image/loader/provider qualification occurred.
            created = connection.execute('SELECT created_at FROM mentat_project_output_reservations').fetchone()[0]
            connection.execute('INSERT INTO mentat_project_producer_bindings VALUES(?,?,?,?,?)',
                (self.run,fixtures.GENERATION,journal._encoded(body),journal._digest(body),created))
            producers.producer_ids(connection)
            connection.commit()

    def cancel(self, connection):
        producers.request_stop(connection,run_id=self.run,generation=fixtures.GENERATION,holder_token=self.holder,expected_revision=1)
        return producers.settle_without_output(connection,run_id=self.run,generation=fixtures.GENERATION,
            holder_token=self.holder,expected_revision=2,disposition='cancelled')

    def owned(self, connection):
        scope = scope_fixtures.planned_fixture()
        token, revision = producers.record_start_intent(connection,run_id=self.run,generation=fixtures.GENERATION,
            holder_token=self.holder,expected_revision=1,plan_witness=scope.journal_plan())
        values = scope.journal_plan().private_metadata() | {'invocation':'e'*32,'device':1,'inode':2,'pid':3,'start_ticks':4}
        witness = issue_scope('owned',scope,values)
        scope.journal_owned_identity = lambda: witness
        revision = producers.record_owned_scope(connection,run_id=self.run,generation=fixtures.GENERATION,
            holder_token=self.holder,scope_token=token,scope_revision=revision,witness=witness,expected_revision=2)
        scope._closed = True
        scope._closed_witness = issue_scope('closed',scope,values)
        return scope, token, revision

    def test_128_retained_producers_survive_ordinary_terminal_and_event_pressure(self):
        with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            self.cancel(connection)
            tables = ('mentat_runs','mentat_project_proposal_input_receipts','mentat_project_worker_generations',
                      'mentat_project_output_reservations','mentat_project_producer_bindings','mentat_project_producer_outputs')
            templates = {table:dict(connection.execute('SELECT * FROM '+table+' WHERE '+('id' if table=='mentat_runs' else 'run_id')+'=?',(self.run,)).fetchone()) for table in tables}
            file_rows = [tuple(row) for row in connection.execute('SELECT * FROM mentat_project_proposal_input_files')]
            brief = connection.execute('SELECT brief FROM mentat_project_context_versions WHERE id=?',(templates[tables[1]]['context_id'],)).fetchone()[0]
            instructions = connection.execute('SELECT instructions FROM mentat_project_planning_input_versions WHERE id=?',(templates[tables[1]]['input_id'],)).fetchone()[0]
            trigger = connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_runs_project_proposal_closed_insert'").fetchone()[0]
            connection.execute('DROP TRIGGER mentat_runs_project_proposal_closed_insert')
            try:
                for index in range(1,128):
                    run = 'run_pressure_'+str(index)
                    generation_id=f'{index:032x}'
                    row = dict(templates['mentat_runs']); row.update(id=run,status='reserved',dispatch_state='reserved',state_revision=1,
                        last_event_sequence=0,completed_at=None,terminal_finalized=0,updated_at=row['created_at'])
                    insert_row(connection,'mentat_runs',row)
                    receipt = dict(templates['mentat_project_proposal_input_receipts']); receipt['run_id']=run
                    ordered = list(receipt.values()); ordered[21]=input_fixtures._digest([*ordered[:21],ordered[22],brief,instructions,[list(item[2:]) for item in file_rows]])
                    receipt['manifest_digest']=ordered[21]; insert_row(connection,'mentat_project_proposal_input_receipts',receipt)
                    for item in file_rows: connection.execute('INSERT INTO mentat_project_proposal_input_files VALUES(?,?,?,?,?,?,?,?)',(run,*item[1:]))
                    generation = dict(templates['mentat_project_worker_generations']); generation.update(run_id=run,generation=generation_id,input_manifest_digest=receipt['manifest_digest'])
                    generation['claim_digest']=journal._digest([run,generation['source'],generation['generation'],generation['authority_epoch'].hex(),generation['input_manifest_digest'],generation['runtime_binding_digest'],json.loads(generation['policy_json']),json.loads(generation['model_snapshot_json']),generation['created_at']])
                    insert_row(connection,'mentat_project_worker_generations',generation)
                    hold = dict(templates['mentat_project_output_reservations']); hold.update(run_id=run,generation=generation_id,input_manifest_digest=receipt['manifest_digest'])
                    hold['reservation_digest']=journal._digest([run,hold['generation'],hold['authority_epoch'].hex(),hold['input_manifest_digest'],hold['policy_digest'],hold['blob_slots'],hold['max_bytes'],hold['metadata_charge'],hold['holder_token_hash'],generation['claim_digest'],hold['created_at']])
                    insert_row(connection,'mentat_project_output_reservations',hold)
                    binding = dict(templates['mentat_project_producer_bindings']); binding['run_id']=run; binding['generation']=generation_id
                    body=json.loads(binding['body_json']); body.update(run_id=run,generation=generation_id,input_manifest=receipt['manifest_digest'],run_incarnation=connection.execute('SELECT incarnation FROM mentat_run_identities WHERE run_id=?',(run,)).fetchone()[0])
                    binding.update(body_json=journal._encoded(body),receipt_digest=journal._digest(body)); insert_row(connection,'mentat_project_producer_bindings',binding)
                    created = binding['created_at']
                    connection.execute('INSERT INTO mentat_project_producer_stops VALUES(?,?,?,?)',(run,1,journal._digest([run,generation_id,'owner_stop',1,created]),created))
                    producers._append_state(connection,run,'unknown','unknown')
                    output = dict(templates['mentat_project_producer_outputs']); output['run_id']=run
                    body=json.loads(output['body_json']); body.update(run_id=run,generation=generation_id,binding_digest=binding['receipt_digest'],reservation_digest=hold['reservation_digest'],request_digest=journal._digest([run,generation_id,'settlement',2,'cancelled',hold['holder_token_hash'],None]))
                    output.update(body_json=journal._encoded(body),receipt_digest=journal._digest(body)); insert_row(connection,'mentat_project_producer_outputs',output)
                    producers._append_state(connection,run,'cancelled','rejected')
            finally: connection.execute(trigger)
            repository = runs.RunRepository(connection)
            repository.validate(private_producer_proposals=True)
            expected = {row[0] for row in connection.execute("SELECT id FROM mentat_runs WHERE source='project_proposal'")}
            before = [tuple(row) for row in connection.execute("SELECT e.* FROM mentat_agent_events e JOIN mentat_runs r ON r.id=e.run_id WHERE r.source='project_proposal' ORDER BY e.run_id,e.sequence")]
            self.assertEqual(len(expected),128)
            self.assertEqual(len(before),256)
            for index in range(265):
                run='run_noise_'+str(index)
                source=run_fixtures.run_fixture(run,bound=False,offset=index)
                details,_=runs._details_for_run(source)
                connection.execute("INSERT INTO mentat_runs(id,source,runtime_type,capabilities_json,status,dispatch_state,details_json,created_at,updated_at,started_at,completed_at,terminal_finalized) VALUES(?,'console','hermes','[]','completed','legacy',?,?,?,?,?,1)",
                    (run,journal._encoded(details),source['created_at'],source['updated_at'],source['started_at'],source['completed_at']))
                event=runs._event_record(run,'completed',{'id':'noise_'+str(index),'sequence':1,'timestamp':source['updated_at'],'type':'run.completed','display_text':'Ordinary completion','data':{}})
                repository._append_event_record(event)
            with patch.object(runs,'GLOBAL_EVENT_COUNT_RETENTION',272): report=repository._apply_retention()
            self.assertEqual(len(report.removed_run_ids),15)
            self.assertTrue(report.truncated_run_ids)
            self.assertFalse(expected.intersection(report.removed_run_ids+report.truncated_run_ids))
            self.assertEqual({row[0] for row in connection.execute("SELECT id FROM mentat_runs WHERE source='project_proposal'")},expected)
            self.assertEqual([tuple(row) for row in connection.execute("SELECT e.* FROM mentat_agent_events e JOIN mentat_runs r ON r.id=e.run_id WHERE r.source='project_proposal' ORDER BY e.run_id,e.sequence")],before)
            repository.validate(private_producer_proposals=True)
            self.assertEqual(holds.pending_capacity(connection),(0,0))
            connection.commit()

    def test_malformed_conversion_refuses_independent_console_and_staging_writers(self):
        with closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE'); self.cancel(connection); connection.commit()
            row=connection.execute('SELECT body_json FROM mentat_project_producer_outputs').fetchone()
            body=json.loads(row[0]); body['request_digest']='f'*64
            trigger=connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_project_producer_output_immutable'").fetchone()[0]
            connection.execute('DROP TRIGGER mentat_project_producer_output_immutable')
            connection.execute('UPDATE mentat_project_producer_outputs SET body_json=?,receipt_digest=?',(journal._encoded(body),journal._digest(body)))
            connection.execute(trigger); connection.commit()
            before=connection.execute('SELECT COUNT(*) FROM mentat_retained_attachments').fetchone()[0]
        candidate=files.create_attachment(self.root,original_name='candidate.txt',content=b'new bytes')['id']
        with self.assertRaises(files.AttachmentUnavailable): files.bind_run_attachment(self.root,candidate,'run_candidate')
        with self.assertRaises(editor.ProjectContextEditorError):
            editor.stage_project_file(self.root,'project_mentat',expected_project_revision=1,original_name='stage.txt',content=b'staged bytes')
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_retained_attachments').fetchone()[0],before)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM run_attachments').fetchone()[0],0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_context_staged').fetchone()[0],0)
        self.assertEqual(files.get_attachment(self.root,candidate)['state'],'staged')

    def test_unknown_provider_call_keeps_hold_even_with_original_closed_scope(self):
        with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            scope,token,revision=self.owned(connection)
            call=journal.reserve_call(connection,run_id=self.run,generation=fixtures.GENERATION,request_digest=fixtures.REQUEST)
            journal.record_submission(connection,call_id=call.call_id,generation=fixtures.GENERATION,request_digest=fixtures.REQUEST,settlement_token=call.settlement_token)
            producers.request_stop(connection,run_id=self.run,generation=fixtures.GENERATION,holder_token=self.holder,expected_revision=3)
            before=list(connection.iterdump())
            with self.assertRaisesRegex(producers.ProducerError,'uncertain'):
                producers.settle_without_output(connection,run_id=self.run,generation=fixtures.GENERATION,holder_token=self.holder,
                    expected_revision=4,disposition='stopped',scope_token=token,scope_revision=revision,closure_witness=scope._closed_witness)
            self.assertEqual(list(connection.iterdump()),before)
            self.assertEqual(holds.pending_capacity(connection),(1,32768))
            self.assertEqual(connection.execute('SELECT state FROM mentat_project_worker_calls').fetchone()[0],'unknown')
            self.assertEqual(connection.execute('SELECT status FROM mentat_runs').fetchone()[0],'unknown')
            runs.RunRepository(connection).validate(private_producer_proposals=True)
            connection.commit()

    def test_two_stop_requests_race_to_one_intent_without_refunding_capacity(self):
        barrier=threading.Barrier(2)
        results,errors=[],[]
        def stop():
            try:
                barrier.wait(timeout=5)
                with private_state_lock(self.root),closing(mentat_db.connect(self.root)) as connection:
                    connection.execute('BEGIN IMMEDIATE')
                    result=producers.request_stop(connection,run_id=self.run,generation=fixtures.GENERATION,holder_token=self.holder,expected_revision=1)
                    connection.commit(); results.append(result)
            except BaseException as error: errors.append(error)
        threads=[threading.Thread(target=stop) for _ in range(2)]
        try:
            for thread in threads: thread.start()
            for thread in threads: thread.join(20)
        finally:
            barrier.abort()
            for thread in threads:
                if thread.ident is not None: thread.join(20)
            if any(thread.is_alive() for thread in threads):
                self.retained=True; _RETAINED_PRESSURE_FIXTURES.append((self.fixture,threads))
        self.assertFalse(self.retained)
        self.assertEqual(len(results),2)
        self.assertEqual(results[0],results[1])
        self.assertEqual(errors,[])
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_project_producer_stops').fetchone()[0],1)
            self.assertEqual(holds.pending_capacity(connection),(1,32768))
            runs.RunRepository(connection).validate(private_producer_proposals=True)


    def completed_fixture(self, text):
        # Inert trusted-Python witnesses are SQL-history fixtures only. They do
        # not prove kernel isolation, provider execution or runtime qualification.
        with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            scope, token, revision = self.owned(connection)
            call = journal.reserve_call(connection,run_id=self.run,generation=fixtures.GENERATION,request_digest=fixtures.REQUEST)
            journal.record_submission(connection,call_id=call.call_id,generation=fixtures.GENERATION,
                request_digest=fixtures.REQUEST,settlement_token=call.settlement_token)
            journal.settle_call(connection,call_id=call.call_id,generation=fixtures.GENERATION,
                request_digest=fixtures.REQUEST,settlement_token=call.settlement_token,response_text=text)
            connection.commit()
        candidate=files.create_attachment(self.root,original_name='project-proposal.json',content=text.encode(),content_type='application/json')['id']
        with private_state_lock(self.root), closing(mentat_db.connect(self.root)) as connection:
            sizes=[]
            original=context._encoded
            def measured(value):
                data=original(value); sizes.append(len(data)); return data
            with patch.object(context,'_encoded',side_effect=measured): context.validate_project_context_connection(connection)
            before=max(sizes)
            connection.execute('BEGIN IMMEDIATE')
            scopes.transition_scope(connection,run_id=self.run,generation=fixtures.GENERATION,
                claim_token=token,expected_revision=revision,target='stopped',witness=scope._closed_witness,
                producer_context=producers._SCOPE_MUTATION)
            connection.execute("UPDATE attachments SET state='attached',expires_at=NULL WHERE id=?",(candidate,))
            blob=connection.execute('SELECT blob_id FROM attachments WHERE id=?',(candidate,)).fetchone()[0]
            binding,body=producers._binding(connection,self.run)
            hold=connection.execute('SELECT * FROM mentat_project_output_reservations').fetchone()
            scope_row=connection.execute('SELECT * FROM mentat_project_worker_scopes').fetchone()
            result=connection.execute('SELECT * FROM mentat_project_worker_calls').fetchone()
            from project_proposal_artifact import parse_proposal_artifact,proposal_snapshot_digest
            parsed=parse_proposal_artifact(text.encode())
            metadata={'query_digest':body['query_digest'],'image_digest':body['image_digest'],
                'runtime_image_digest':body['runtime_image_digest'],'scope':scope._closed_witness.private_metadata(),
                'terminal_digest':journal._digest({'text':text,'output_bytes':len(text.encode())})}
            output={'format':1,'purpose':'qualification','run_id':self.run,'generation':fixtures.GENERATION,
                'binding_digest':binding[3],'reservation_digest':hold[9],'disposition':'completed',
                'call_id':result[0],'result_digest':result[9],'closure_digest':scope_row[13],
                'terminal_digest':metadata['terminal_digest'],'output_bytes':len(text.encode()),
                'blob_sha256':hashlib.sha256(text.encode()).hexdigest(),'byte_size':len(text.encode()),
                'parser_version':1,'snapshot':parsed,'snapshot_digest':proposal_snapshot_digest(parsed),
                'request_digest':producers._capture_request(self.run,fixtures.GENERATION,self.holder,token,revision,3,metadata)}
            connection.execute('INSERT INTO mentat_project_producer_outputs VALUES(?,?,?,?,?,?,?,?)',
                (self.run,result[0],self.run,candidate,blob,journal._encoded(output),journal._digest(output),result[11]))
            producers._append_state(connection,self.run,'completed','accepted')
            sizes.clear()
            with patch.object(context,'_encoded',side_effect=measured): context.validate_project_context_connection(connection)
            after=max(sizes)
            runs.RunRepository(connection).validate(private_producer_proposals=True)
            connection.commit()
        return before,after

    def test_large_escaped_parser_snapshot_fits_original_hold_without_extra_charge(self):
        from project_proposal_artifact import parse_proposal_artifact,_snapshot_bytes
        value={'version':1,'summary':'Garage goals','questions':[],
            'tasks':[{'title':str(index),'description':'start'+('\\\n'*1020),
                      'agent_id':None,'due_date':None,'after':[]} for index in range(7)]}
        text=json.dumps(value,ensure_ascii=False,separators=(',',':'))
        canonical=_snapshot_bytes(parse_proposal_artifact(text.encode()))
        self.assertGreater(len(canonical),28*1024)
        self.assertLessEqual(len(text.encode()),32768)
        before,after=self.completed_fixture(text)
        self.assertEqual(before,after)
        with closing(mentat_db.connect(self.root)) as connection:
            charge=connection.execute('SELECT metadata_charge FROM mentat_project_output_reservations').fetchone()[0]
            retained=[item for group in producers.validate_producer_graph(connection) for item in group]
            self.assertLess(len(journal._encoded(retained).encode()),charge)
            self.assertEqual(charge,128*1024)
            self.assertEqual(holds.pending_capacity(connection),(0,0))

    def test_corrupt_scope_cannot_refund_a_self_consistent_completed_conversion(self):
        text=json.dumps({'version':1,'summary':'Garage','questions':[],
            'tasks':[{'title':'Research','description':'','agent_id':None,'due_date':None,'after':[]}]},separators=(',',':'))
        self.completed_fixture(text)
        with closing(mentat_db.connect(self.root)) as connection:
            trigger=connection.execute("SELECT sql FROM sqlite_master WHERE name='mentat_project_worker_scope_immutable'").fetchone()[0]
            connection.execute('DROP TRIGGER mentat_project_worker_scope_immutable')
            connection.execute("UPDATE mentat_project_worker_scopes SET claim_digest=?",('f'*64,))
            connection.execute(trigger); connection.commit()
            with self.assertRaises(journal.WorkerJournalError): holds.pending_capacity(connection)
            before=connection.execute('SELECT COUNT(*) FROM mentat_retained_attachments').fetchone()[0]
        candidate=files.create_attachment(self.root,original_name='extra.txt',content=b'extra')['id']
        with self.assertRaises(files.AttachmentUnavailable): files.bind_run_attachment(self.root,candidate,'run_extra')
        with closing(mentat_db.connect(self.root)) as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_retained_attachments').fetchone()[0],before)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM run_attachments').fetchone()[0],0)


if __name__=='__main__': unittest.main()
