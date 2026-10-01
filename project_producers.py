"""Private canonical producer evidence; production admission remains guarded."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path
import time

import project_worker_journal as journal
from project_proposal_artifact import parse_proposal_artifact, proposal_snapshot_digest, ProjectProposalArtifactError

MAX_PRODUCERS = journal.MAX_GENERATIONS
_BIND_KEYS = frozenset({'format','purpose','run_id','generation','run_incarnation','authority_epoch',
    'input_manifest','qualification_digest','authorization_digest','query_digest','image_digest',
    'runtime_image_digest','model_digest','capacity_scope_digest','capacity_limit','root_identity'})
_OUTPUT_KEYS = frozenset({'format','purpose','run_id','generation','binding_digest','reservation_digest',
    'disposition','call_id','result_digest','closure_digest','terminal_digest','output_bytes',
    'blob_sha256','byte_size','parser_version','snapshot','snapshot_digest','request_digest'})
_EVENTS = {'starting':('dispatch.reserved','Project worker starting'),
           'running':('run.started','Project worker started'),
           'unknown':('submission.unknown','Project work requires reconciliation'),
           'completed':('run.completed','Project proposal returned'),
           'failed':('run.failed','Project proposal could not be accepted'),
           'cancelled':('run.stopped','Project proposal cancelled before launch'),
           'stopped':('run.stopped','Project proposal stopped')}
_TERMINAL = frozenset({'completed','failed','cancelled','stopped'})
_SCOPE_MUTATION = object()


class ProducerError(journal.WorkerJournalError):
    pass


def _fail(code='invalid'):
    raise ProducerError('producer.'+code)


def _version(connection):
    return connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]


def _json(raw, keys):
    try: value=json.loads(raw)
    except (ValueError,TypeError): _fail()
    if not isinstance(value,dict) or set(value)!=keys or journal._encoded(value)!=raw:
        _fail()
    return value


def _binding(connection,run_id):
    row=connection.execute('SELECT * FROM mentat_project_producer_bindings WHERE run_id=?',(run_id,)).fetchone()
    if row is None: _fail('unavailable')
    return tuple(row),_json(row[2],_BIND_KEYS)


def _holder(connection,run_id,generation,token,*,historical=False):
    from project_output_reservations import require_output_reservation,validate_output_reservations_connection
    if historical:
        validate_output_reservations_connection(connection)
        row=connection.execute('SELECT * FROM mentat_project_output_reservations WHERE run_id=? AND generation=?',(run_id,generation)).fetchone()
        if row is None: _fail('holder')
    else:
        row=require_output_reservation(connection,run_id,generation)
    if (not isinstance(token,str) or journal._HEX64.fullmatch(token) is None
            or not hmac.compare_digest(row[8],hashlib.sha256(token.encode('ascii')).hexdigest())):
        _fail('holder')
    return row


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')


def _capture_request(run,generation,holder_token,scope_token,scope_revision,revision,metadata):
    if (not isinstance(holder_token,str) or journal._HEX64.fullmatch(holder_token) is None
            or not isinstance(scope_token,str) or journal._HEX64.fullmatch(scope_token) is None
            or type(scope_revision) is not int or not 1<=scope_revision<=5
            or type(revision) is not int or not 1<=revision<=8): _fail('conflict')
    return journal._digest([run,generation,hashlib.sha256(holder_token.encode()).hexdigest(),
        hashlib.sha256(scope_token.encode()).hexdigest(),scope_revision,revision,
        metadata['query_digest'],metadata['image_digest'],metadata['runtime_image_digest'],
        metadata['scope'],metadata['terminal_digest']])


def _append_state(connection,run_id,status,dispatch):
    from run_repository import _event_record
    row=connection.execute('SELECT state_revision,last_event_sequence FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    sequence=row[1]+1
    occurred=_stamp()
    kind,summary=_EVENTS[status]
    event=_event_record(run_id,status,{'id':'project_producer_'+hashlib.sha256((run_id+':'+str(sequence)).encode()).hexdigest(),
        'sequence':sequence,'timestamp':occurred,'type':kind,'display_text':summary,'data':{}})
    fields=('run_id','sequence','id','event_type','source_type','source_key','occurred_at','summary',
            'content','metrics_json','data_json','content_bytes','payload_digest')
    connection.execute('INSERT INTO mentat_agent_events('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',
                       tuple(event[key] for key in fields))
    connection.execute('UPDATE mentat_runs SET status=?,dispatch_state=?,state_revision=state_revision+1,'
        'last_event_sequence=?,updated_at=?,started_at=CASE WHEN ?=\'running\' THEN ? ELSE started_at END,'
        'completed_at=?,terminal_finalized=? WHERE id=?',
        (status,dispatch,sequence,occurred,status,occurred,occurred if status in _TERMINAL else None,
         int(status in _TERMINAL),run_id))


def validate_producer_graph(connection):
    """Exact historical graph; neither current grant nor runtime qualification."""
    if _version(connection)<46: return []
    journal.validate_worker_journal_connection(connection)
    from project_scope_journal import validate_scope_journal_connection
    from project_proposal_input_receipts import validate_project_proposal_input_connection
    validate_scope_journal_connection(connection)
    validate_project_proposal_input_connection(connection,require_available=True)
    rows=connection.execute('SELECT * FROM mentat_project_producer_bindings ORDER BY run_id').fetchmany(MAX_PRODUCERS+1)
    if len(rows)>MAX_PRODUCERS: _fail('capacity')
    bindings={}
    metadata=[]
    for row in rows:
        run,generation,raw,digest,created=tuple(row)
        body=_json(raw,_BIND_KEYS)
        parent=connection.execute('SELECT * FROM mentat_project_worker_generations WHERE run_id=?',(run,)).fetchone()
        inputs=connection.execute('SELECT qualification_digest,authorization_digest,runtime_type FROM '
                                 'mentat_project_proposal_input_receipts WHERE run_id=?',(run,)).fetchone()
        identity=connection.execute('SELECT incarnation FROM mentat_run_identities WHERE run_id=?',(run,)).fetchone()
        hold=connection.execute('SELECT created_at FROM mentat_project_output_reservations WHERE run_id=?',(run,)).fetchone()
        if (parent is None or inputs is None or identity is None or hold is None
                or type(body['format']) is not int or body['format']!=1 or body['purpose']!='qualification'
                or body['run_id']!=run or body['generation']!=generation or parent[2]!=generation
                or body['run_incarnation']!=identity[0] or body['authority_epoch']!=parent[3].hex()
                or body['input_manifest']!=parent[4] or body['qualification_digest']!=inputs[0]
                or body['authorization_digest']!=inputs[1] or inputs[2]!='hermes'
                or body['model_digest']!=journal._digest(json.loads(parent[8]))
                or not journal._timestamp(created) or created<hold[0] or journal._digest(body)!=digest
                or type(body['capacity_limit']) is not int or body['capacity_limit']!=1):
            _fail()
        from run_repository import default_runtime_capacity_evidence
        capacity,_=default_runtime_capacity_evidence(runtime_type='hermes',binding_digest=parent[5])
        if body['capacity_scope_digest']!=capacity: _fail()
        for key in ('query_digest','runtime_image_digest'):
            if not isinstance(body[key],str) or journal._HEX64.fullmatch(body[key]) is None: _fail()
        if body['image_digest'] is not None and (not isinstance(body['image_digest'],str) or journal._HEX64.fullmatch(body['image_digest']) is None): _fail()
        root_identity=body['root_identity']
        if (not isinstance(root_identity,list) or len(root_identity)!=2
                or any(type(value) is not int or not 0<=value<2**64 for value in root_identity)
                or root_identity[1]==0): _fail()
        bindings[run]=(tuple(row),body)
        metadata.append(list(row))
    stops=[]
    for row in connection.execute('SELECT * FROM mentat_project_producer_stops ORDER BY run_id'):
        run,revision,digest,created=tuple(row)
        selected=bindings.get(run)
        if (selected is None or type(revision) is not int or not 1<=revision<=8
                or not journal._timestamp(created) or created<selected[0][4]
                or digest!=journal._digest([run,selected[1]['generation'],'owner_stop',revision,created])): _fail()
        stops.append(list(row))
    outputs=[]
    for row in connection.execute('SELECT * FROM mentat_project_producer_outputs ORDER BY run_id'):
        run,call_id,scope_run,attachment,blob_id,raw,digest,created=tuple(row)
        selected=bindings.get(run)
        body=_json(raw,_OUTPUT_KEYS)
        hold=connection.execute('SELECT reservation_digest,holder_token_hash FROM mentat_project_output_reservations WHERE run_id=?',(run,)).fetchone()
        if (selected is None or hold is None or body['format']!=1 or type(body['format']) is not int
                or body['purpose']!='qualification' or body['run_id']!=run
                or body['generation']!=selected[1]['generation'] or body['binding_digest']!=selected[0][3]
                or body['reservation_digest']!=hold[0] or body['call_id']!=call_id
                or not isinstance(body['request_digest'],str) or journal._HEX64.fullmatch(body['request_digest']) is None
                or not journal._timestamp(created) or created<selected[0][4] or journal._digest(body)!=digest): _fail()
        call=connection.execute('SELECT * FROM mentat_project_worker_calls WHERE run_id=?',(run,)).fetchone()
        scope=connection.execute('SELECT * FROM mentat_project_worker_scopes WHERE run_id=?',(run,)).fetchone()
        if (call is None)!=(call_id is None) or call is not None and call[0]!=call_id: _fail()
        if (scope is None)!=(scope_run is None) or scope is not None and scope_run!=run: _fail()
        if scope is not None and scope[10] not in {'stopped','cancelled'}: _fail()
        if call is not None and call[6] not in {'succeeded','failed'}: _fail()
        if body['result_digest']!=(call[9] if call else None) or body['closure_digest']!=(scope[13] if scope else None): _fail()
        disposition=body['disposition']
        if disposition in {'completed','invalid_artifact'}:
            if call is None or call[6]!='succeeded' or scope is None or scope[10]!='stopped' or attachment is None or blob_id is None: _fail()
            blob=connection.execute('SELECT a.blob_id,a.byte_size,a.kind,a.mime_type,a.state,b.sha256,b.byte_size,b.state '
                'FROM attachments a JOIN blobs b ON b.id=a.blob_id WHERE a.id=?',(attachment,)).fetchone()
            payload=call[8].encode('utf-8')
            if (blob is None or tuple(blob)!=(blob_id,len(payload),'text','application/json','attached',
                        hashlib.sha256(payload).hexdigest(),len(payload),'ready')
                    or body['blob_sha256']!=blob[5] or body['byte_size']!=len(payload)
                    or type(body['output_bytes']) is not int or not 0<=body['output_bytes']<=512*1024
                    or body['terminal_digest']!=journal._digest({'text':call[8],'output_bytes':body['output_bytes']})):
                _fail()
            try: parsed=parse_proposal_artifact(payload)
            except ProjectProposalArtifactError: parsed=None
            if disposition=='completed':
                if (parsed is None or body['parser_version']!=1 or type(body['parser_version']) is not int
                        or body['snapshot']!=parsed or body['snapshot_digest']!=proposal_snapshot_digest(parsed)): _fail()
            elif parsed is not None or any(body[key] is not None for key in ('parser_version','snapshot','snapshot_digest')): _fail()
        elif disposition in {'cancelled','stopped','failed'}:
            if attachment is not None or blob_id is not None or any(body[key] is not None for key in
                ('terminal_digest','output_bytes','blob_sha256','byte_size','parser_version','snapshot','snapshot_digest')): _fail()
            if disposition=='cancelled' and (call is not None or scope is not None and scope[10]!='cancelled'): _fail()
            if disposition!='cancelled' and (scope is None or scope[10]!='stopped'): _fail()
        else: _fail()
        finalized=connection.execute('SELECT status,dispatch_state,partial,terminal_finalized,completed_at FROM mentat_runs WHERE id=?',(run,)).fetchone()
        expected_status='failed' if disposition=='invalid_artifact' else disposition
        expected_dispatch='rejected' if disposition=='cancelled' else 'accepted'
        if (finalized is None or tuple(finalized[:4])!=(expected_status,expected_dispatch,0,1)
                or finalized[4] is None): _fail()
        final_revision=connection.execute('SELECT state_revision FROM mentat_runs WHERE id=?',(run,)).fetchone()[0]
        if disposition in {'completed','invalid_artifact'}:
            expected_request=journal._digest([run,body['generation'],hold[1],scope[7],scope[9]-1,final_revision-1,
                selected[1]['query_digest'],selected[1]['image_digest'],selected[1]['runtime_image_digest'],
                json.loads(scope[11]),body['terminal_digest']])
        else:
            expected_request=journal._digest([run,body['generation'],'settlement',final_revision-1,disposition,
                hold[1],scope[13] if scope else None])
        if body['request_digest']!=expected_request: _fail()
        outputs.append(list(row))
    for run in bindings:
        retained=[entry for group in (metadata,stops,outputs) for entry in group if entry[0]==run]
        charge=connection.execute('SELECT metadata_charge FROM mentat_project_output_reservations WHERE run_id=?',(run,)).fetchone()[0]
        if len(journal._encoded(retained).encode('utf-8'))>charge: _fail('capacity')
    return [metadata,stops,outputs]


def require_forward(connection,run_id,generation):
    """Supplementary Stop/terminal fence; never admission authority."""
    if _version(connection)<46: return
    row=connection.execute('SELECT generation FROM mentat_project_producer_bindings WHERE run_id=?',(run_id,)).fetchone()
    if row is None: return
    state=connection.execute('SELECT status FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    if (row[0]!=generation or state is None or state[0] not in {'reserved','starting','running'}
            or connection.execute('SELECT 1 FROM mentat_project_producer_stops WHERE run_id=?',(run_id,)).fetchone()):
        _fail('fenced')


def require_inference_phase(connection,run_id,generation):
    """Source bookkeeping phase, never a substitute for the owned broker."""
    if _version(connection)<46: return
    bound=connection.execute('SELECT 1 FROM mentat_project_producer_bindings WHERE run_id=?',(run_id,)).fetchone()
    if bound is None: return
    require_forward(connection,run_id,generation)
    run=connection.execute('SELECT status,dispatch_state FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    scope=connection.execute('SELECT generation,state FROM mentat_project_worker_scopes WHERE run_id=?',(run_id,)).fetchone()
    if tuple(run)!=('running','accepted') or scope is None or tuple(scope)!=(generation,'owned'):
        _fail('phase')


@journal._atomic_mutation
def mark_uncertain(connection, *, run_id,generation,holder_token,expected_revision):
    """Persist a lost local/registration outcome without releasing capacity."""
    _holder(connection,run_id,generation,holder_token,historical=True)
    _,body=_binding(connection,run_id)
    row=connection.execute('SELECT status,state_revision FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    if (body['generation']!=generation or type(expected_revision) is not int
            or row[1]!=expected_revision or row[0] not in {'reserved','starting','running'}): _fail('conflict')
    _append_state(connection,run_id,'unknown','unknown')
    producer_ids(connection)


def validate_input_bytes(connection,read_blob):
    """Recompute frozen query/image provenance from verified private-unit bytes."""
    if _version(connection)<46: return
    from project_inference_broker import _encode,_MIMES
    for run,raw in connection.execute('SELECT run_id,body_json FROM mentat_project_producer_bindings'):
        body=_json(raw,_BIND_KEYS)
        receipt=connection.execute('SELECT context_id,input_id,manifest_digest FROM mentat_project_proposal_input_receipts WHERE run_id=?',(run,)).fetchone()
        brief=connection.execute('SELECT brief FROM mentat_project_context_versions WHERE id=?',(receipt[0],)).fetchone()[0]
        instructions=connection.execute('SELECT instructions FROM mentat_project_planning_input_versions WHERE id=?',(receipt[1],)).fetchone()[0]
        texts=[]
        image=None
        rows=connection.execute('SELECT ordinal,sha256,byte_size,kind,mime_type FROM mentat_project_proposal_input_files WHERE run_id=? ORDER BY ordinal',(run,))
        for ordinal,digest,size,kind,mime in rows:
            payload=read_blob(digest)
            if type(payload) is not bytes or len(payload)!=size or hashlib.sha256(payload).hexdigest()!=digest: _fail('inputs')
            if kind=='image':
                if image is not None or mime not in _MIMES or not 0<len(payload)<=8*1024*1024: _fail('inputs')
                image=digest
            else:
                try: text=payload.decode('utf-8')
                except UnicodeError: _fail('inputs')
                texts.append({'ordinal':ordinal,'text':text})
        query=_encode({'format':1,'operation':'project_proposal','brief':brief,
                       'instructions':instructions,'files':texts,'has_native_image':image is not None})
        if len(query)>1024*1024 or body['query_digest']!=hashlib.sha256(query).hexdigest() or body['image_digest']!=image:
            _fail('inputs')


def producer_ids(connection, *, archival=False, consumed_only=False):
    original=connection.row_factory
    connection.row_factory=sqlite3.Row
    try:
        return _producer_ids(connection,archival=archival,consumed_only=consumed_only)
    finally:
        connection.row_factory=original


def _producer_ids(connection, *, archival=False, consumed_only=False):
    """Source-specific private acceptance; ordinary getters remain closed."""
    validate_producer_graph(connection)
    all_identifiers=frozenset(row[0] for row in connection.execute('SELECT run_id FROM mentat_project_producer_bindings'))
    identifiers=frozenset(row[0] for row in connection.execute('SELECT run_id FROM mentat_project_producer_outputs')) if consumed_only else all_identifiers
    legacy=frozenset() if consumed_only else journal._dormant_proposal_ids(connection,exclude_ids=all_identifiers)
    if archival:
        if connection.execute("SELECT 1 FROM mentat_project_worker_scopes s WHERE state IN ('starting','owned','unknown') "
            'AND NOT EXISTS(SELECT 1 FROM mentat_project_producer_bindings p WHERE p.run_id=s.run_id)').fetchone():
            from project_scope_journal import ScopeJournalError
            raise ScopeJournalError('scope_journal.active_archival')
    for run in identifiers:
        row=connection.execute('SELECT * FROM mentat_runs WHERE id=?',(run,)).fetchone()
        binding,body=_binding(connection,run)
        if (row['source']!='project_proposal' or row['details_json']!='{}' or row['partial']!=0
                or row['runtime_type']!='hermes' or row['capacity_scope_digest']!=body['capacity_scope_digest']
                or row['admitted_capacity_limit']!=1 or row['state_revision']!=row['last_event_sequence']+1
                or row['first_retained_sequence']!=1
                or any(row[key]!=0 for key in ('runtime_event_cursor','last_removed_sequence','timeline_truncated','discarded_event_count','discarded_content_bytes'))
                or any(row[key] is not None for key in ('task_id','task_revision','task_snapshot_json','conversation_id','turn_id',
                    'runtime_run_ref','reconcile_lease_owner','reconcile_lease_until','retry_of_run_id','resume_of_run_id','truncation_reason',
                    'agent_revision','runtime_config_revision','execution_config_json','execution_config_digest','runtime_execution_json','runtime_execution_digest'))): _fail()
        for table in ('mentat_dispatch_reservations','mentat_task_dispatch_heads','run_attachments'):
            if connection.execute(f'SELECT 1 FROM {table} WHERE run_id=?',(run,)).fetchone(): _fail()
        scope=connection.execute('SELECT state FROM mentat_project_worker_scopes WHERE run_id=?',(run,)).fetchone()
        call=connection.execute('SELECT state FROM mentat_project_worker_calls WHERE run_id=?',(run,)).fetchone()
        output=connection.execute('SELECT body_json FROM mentat_project_producer_outputs WHERE run_id=?',(run,)).fetchone()
        stop=connection.execute('SELECT 1 FROM mentat_project_producer_stops WHERE run_id=?',(run,)).fetchone()
        status,dispatch=row['status'],row['dispatch_state']
        if status=='reserved': legal=dispatch=='reserved' and call is None and (scope is None or scope[0]=='prepared') and output is None and stop is None
        elif status=='starting': legal=dispatch=='submitting' and scope is not None and scope[0]=='starting' and call is None and output is None and stop is None
        elif status=='running': legal=dispatch=='accepted' and scope is not None and scope[0] in {'owned','stopped'} and output is None and stop is None
        elif status=='unknown': legal=dispatch=='unknown' and output is None
        elif status in _TERMINAL:
            disposition=_json(output[0],_OUTPUT_KEYS)['disposition'] if output else None
            legal=output is not None and (status,dispatch,disposition) in {
                ('completed','accepted','completed'),('failed','accepted','invalid_artifact'),
                ('cancelled','rejected','cancelled'),('stopped','accepted','stopped'),('failed','accepted','failed')}
            if disposition in {'completed','invalid_artifact'} and stop is not None: legal=False
            if disposition in {'cancelled','stopped','failed'} and stop is None: legal=False
        else: legal=False
        if (not legal or row['terminal_finalized']!=int(status in _TERMINAL)
                or (row['completed_at'] is not None)!=(status in _TERMINAL)): _fail()
        events=connection.execute('SELECT sequence,event_type,summary,content,metrics_json,data_json,source_type '
                                 'FROM mentat_agent_events WHERE run_id=? ORDER BY sequence',(run,)).fetchall()
        if len(events)!=row['last_event_sequence'] or len(events)>8: _fail()
        for index,event in enumerate(events):
            kind=event[1]
            summaries={text for candidate,text in _EVENTS.values() if candidate==kind}
            if (event[0]!=index+1 or kind not in {value[0] for value in _EVENTS.values()}
                    or event[2] not in summaries or tuple(event[3:6])!=(None,'{}','{}') or event[6]!=kind): _fail()
        sequence=[event[1] for event in events]
        if (row['started_at'] is not None)!=('run.started' in sequence): _fail()
        prefixes={'reserved':[[]],'starting':[['dispatch.reserved']],
                  'running':[['dispatch.reserved','run.started']],
                  'unknown':[['submission.unknown'],['dispatch.reserved','submission.unknown'],
                             ['dispatch.reserved','run.started','submission.unknown']],
                  'completed':[['dispatch.reserved','run.started','run.completed']],
                  'failed':[['dispatch.reserved','run.started','run.failed'],
                            ['dispatch.reserved','run.started','submission.unknown','run.failed'],
                            ['dispatch.reserved','submission.unknown','run.failed']],
                  'cancelled':[['submission.unknown','run.stopped']],
                  'stopped':[['dispatch.reserved','run.started','submission.unknown','run.stopped'],
                             ['dispatch.reserved','submission.unknown','run.stopped']]}
        if status=='unknown':
            prefixes['unknown'] += [trace+['submission.unknown'] for trace in prefixes['unknown']]
        if status in {'cancelled','stopped','failed'}:
            prefixes[status] += [trace[:-1]+['submission.unknown']+trace[-1:] for trace in prefixes[status] if 'submission.unknown' in trace]
        if sequence not in prefixes[status]: _fail()
        stop_row=connection.execute('SELECT expected_revision FROM mentat_project_producer_stops WHERE run_id=?',(run,)).fetchone()
        if stop_row is not None:
            unknown=[event[0] for event in events if event[1]=='submission.unknown']
            if not unknown or unknown[-1]!=stop_row[0]: _fail()
        elif sequence.count('submission.unknown')>1:
            _fail()
    return identifiers|legacy


@journal._atomic_mutation
def bind_qualification_producer(connection, root, *, run_id, generation, prepared, holder_token):
    """Bind an inert qualification fixture; does not insert/admit or launch a Run."""
    from mentat.project_worker_namespace import PreparedNamespace
    from project_inference_broker import _derive_inputs
    from run_repository import default_runtime_capacity_evidence
    from private_state import console_root
    if type(prepared) is not PreparedNamespace or prepared._closed: _fail('binding')
    journal._validate_shared_graph(connection)
    _holder(connection,run_id,generation,holder_token)
    if connection.execute('SELECT 1 FROM mentat_project_producer_bindings WHERE run_id=?',(run_id,)).fetchone(): _fail('conflict')
    for table in ('mentat_project_worker_scopes','mentat_project_worker_calls'):
        if connection.execute(f'SELECT 1 FROM {table} WHERE run_id=?',(run_id,)).fetchone(): _fail('late')
    if run_id not in journal.qualification_proposal_ids(connection): _fail('binding')
    inputs,policy,model=_derive_inputs(Path(root),connection,run_id,generation)
    if model['provider']!='custom' or model['model'] not in {'mentat-probe','mentat-test'}: _fail('unqualified')
    query,image,runtime,libraries=prepared._handoff_context
    if (query!=hashlib.sha256(inputs.query).hexdigest() or image!=inputs.image_digest
            or runtime is None or libraries is not True or prepared._model!=model['model']
            or prepared._vision!=model['supports_vision']): _fail('binding')
    parent=journal._live_generation(connection,run_id,generation)
    receipt=connection.execute('SELECT qualification_digest,authorization_digest FROM mentat_project_proposal_input_receipts WHERE run_id=?',(run_id,)).fetchone()
    identity=connection.execute('SELECT incarnation FROM mentat_run_identities WHERE run_id=?',(run_id,)).fetchone()[0]
    run=connection.execute('SELECT agent_id FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    capacity,limit=default_runtime_capacity_evidence(runtime_type='hermes',binding_digest=parent[5])
    # The existing fixture already holds its canonical reserved slot. Require
    # that it is the only overlapping active Run; never create another slot.
    from run_repository import _ACTIVE_STATUSES
    active=connection.execute('SELECT id FROM mentat_runs WHERE status IN ('+','.join('?' for _ in _ACTIVE_STATUSES)+') '
        'AND (agent_id=? OR capacity_scope_digest=? OR (capacity_scope_digest IS NULL AND runtime_type=\'hermes\' '
        'AND (runtime_binding_digest=? OR runtime_binding_digest IS NULL)))',
        (*sorted(_ACTIVE_STATUSES),run[0],capacity,parent[5])).fetchall()
    if [item[0] for item in active]!=[run_id]: _fail('capacity')
    saved=connection.execute('SELECT capacity_scope_digest,admitted_capacity_limit FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    if tuple(saved)!=(capacity,limit): _fail('binding')
    private=os.stat(console_root(Path(root)),follow_symlinks=False)
    body={'format':1,'purpose':'qualification','run_id':run_id,'generation':generation,
        'run_incarnation':identity,'authority_epoch':parent[3].hex(),'input_manifest':parent[4],
        'qualification_digest':receipt[0],'authorization_digest':receipt[1],
        'query_digest':query,'image_digest':image,'runtime_image_digest':runtime,
        'model_digest':journal._digest(model),'capacity_scope_digest':capacity,'capacity_limit':limit,
        'root_identity':[private.st_dev,private.st_ino]}
    now=time.time()
    digest=journal._digest(body)
    connection.execute('INSERT INTO mentat_project_producer_bindings VALUES(?,?,?,?,?)',
                       (run_id,generation,journal._encoded(body),digest,now))
    journal._validate_shared_graph(connection)
    producer_ids(connection)
    return digest


@journal._atomic_mutation
def settle_without_output(connection, *, run_id,generation,holder_token,expected_revision,
                          disposition,scope_token=None,scope_revision=None,closure_witness=None):
    """Release only proven unused/closed work; unknown provider work stays held."""
    import project_scope_journal as scopes
    hold=_holder(connection,run_id,generation,holder_token,historical=True)
    binding,body=_binding(connection,run_id)
    if body['generation']!=generation or disposition not in {'cancelled','stopped','failed'}: _fail('conflict')
    # A restored snapshot cannot prove that its formerly-unused scope did not
    # launch later on the source host. The original bound root is required.
    main=next((row[2] for row in connection.execute('PRAGMA database_list') if row[1]=='main'),None)
    if not main: _fail('continuity')
    directory=os.stat(Path(main).parent,follow_symlinks=False)
    if body['root_identity']!=[directory.st_dev,directory.st_ino]: _fail('continuity')
    row=connection.execute('SELECT status,state_revision FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    if type(expected_revision) is not int or tuple(row)!=('unknown',expected_revision): _fail('conflict')
    stop=connection.execute('SELECT 1 FROM mentat_project_producer_stops WHERE run_id=?',(run_id,)).fetchone()
    if stop is None: _fail('conflict')
    call=connection.execute('SELECT * FROM mentat_project_worker_calls WHERE run_id=?',(run_id,)).fetchone()
    scope=connection.execute('SELECT * FROM mentat_project_worker_scopes WHERE run_id=?',(run_id,)).fetchone()
    if disposition=='cancelled':
        if call is not None or scope is not None and scope[10]!='prepared': _fail('uncertain')
        if scope is not None:
            scopes.transition_scope(connection,run_id=run_id,generation=generation,
                claim_token=scope_token,expected_revision=scope_revision,target='cancelled',producer_context=_SCOPE_MUTATION)
    else:
        if scope is None or call is not None and call[6] not in {'succeeded','failed'}: _fail('uncertain')
        scopes.transition_scope(connection,run_id=run_id,generation=generation,claim_token=scope_token,
            expected_revision=scope_revision,target='stopped',witness=closure_witness,producer_context=_SCOPE_MUTATION)
    scope=connection.execute('SELECT * FROM mentat_project_worker_scopes WHERE run_id=?',(run_id,)).fetchone()
    output={'format':1,'purpose':'qualification','run_id':run_id,'generation':generation,
        'binding_digest':binding[3],'reservation_digest':hold[9],'disposition':disposition,
        'call_id':call[0] if call else None,'result_digest':call[9] if call else None,
        'closure_digest':scope[13] if scope else None,'terminal_digest':None,'output_bytes':None,
        'blob_sha256':None,'byte_size':None,'parser_version':None,'snapshot':None,'snapshot_digest':None,
        'request_digest':journal._digest([run_id,generation,'settlement',expected_revision,disposition,
                                          hold[8],scope[13] if scope else None])}
    digest=journal._digest(output)
    connection.execute('INSERT INTO mentat_project_producer_outputs VALUES(?,?,?,?,?,?,?,?)',
        (run_id,call[0] if call else None,run_id if scope else None,None,None,journal._encoded(output),digest,time.time()))
    dispatch='rejected' if disposition=='cancelled' else 'accepted'
    _append_state(connection,run_id,disposition,dispatch)
    journal._validate_shared_graph(connection)
    producer_ids(connection)
    return digest


@journal._atomic_mutation
def mark_starting(connection, *, run_id, generation, holder_token, expected_revision):
    _holder(connection,run_id,generation,holder_token)
    journal._live_generation(connection,run_id,generation)
    row=connection.execute('SELECT status,state_revision FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    scope=connection.execute('SELECT state FROM mentat_project_worker_scopes WHERE run_id=?',(run_id,)).fetchone()
    if type(expected_revision) is not int or tuple(row)!=('reserved',expected_revision) or scope is None or scope[0]!='starting': _fail('conflict')
    _append_state(connection,run_id,'starting','submitting')
    producer_ids(connection)


@journal._atomic_mutation
def mark_owned(connection, *, run_id, generation, holder_token, expected_revision):
    _holder(connection,run_id,generation,holder_token)
    journal._live_generation(connection,run_id,generation)
    row=connection.execute('SELECT status,state_revision FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    scope=connection.execute('SELECT state FROM mentat_project_worker_scopes WHERE run_id=?',(run_id,)).fetchone()
    if type(expected_revision) is not int or tuple(row)!=('starting',expected_revision) or scope is None or scope[0]!='owned': _fail('conflict')
    _append_state(connection,run_id,'running','accepted')
    producer_ids(connection)


@journal._atomic_mutation
def request_stop(connection, *, run_id, generation, holder_token, expected_revision):
    """Persist intent before local signaling; no signal or provider call here."""
    _holder(connection,run_id,generation,holder_token,historical=True)
    _,binding=_binding(connection,run_id)
    if binding['generation']!=generation or type(expected_revision) is not int: _fail('conflict')
    prior=connection.execute('SELECT expected_revision,intent_digest FROM mentat_project_producer_stops WHERE run_id=?',(run_id,)).fetchone()
    if prior is not None:
        # Exact lost-response reconciliation returns the retained intent. It
        # never creates another event, signals a scope or refreshes authority.
        if prior[0]!=expected_revision: _fail('conflict')
        producer_ids(connection)
        return prior[1]
    row=connection.execute('SELECT status,state_revision FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
    if row[1]!=expected_revision or row[0] not in {'reserved','starting','running','unknown'}: _fail('conflict')
    now=time.time()
    intent=journal._digest([run_id,generation,'owner_stop',expected_revision,now])
    connection.execute('INSERT INTO mentat_project_producer_stops VALUES(?,?,?,?)',(run_id,expected_revision,intent,now))
    _append_state(connection,run_id,'unknown','unknown')
    producer_ids(connection)
    return intent


@journal._atomic_mutation
def record_start_intent(connection, *, run_id,generation,holder_token,plan_witness,expected_revision):
    """One scope/Run intent transaction, committed before external launch."""
    import project_scope_journal as scopes
    _holder(connection,run_id,generation,holder_token)
    prepared=scopes.prepare_scope(connection,run_id=run_id,generation=generation,
        plan_witness=plan_witness,producer_context=_SCOPE_MUTATION)
    started=scopes.transition_scope(connection,run_id=run_id,generation=generation,
        claim_token=prepared.claim_token,expected_revision=prepared.revision,target='starting',producer_context=_SCOPE_MUTATION)
    mark_starting(connection,run_id=run_id,generation=generation,holder_token=holder_token,expected_revision=expected_revision)
    return prepared.claim_token,started.revision


@journal._atomic_mutation
def record_owned_scope(connection, *, run_id,generation,holder_token,scope_token,scope_revision,witness,expected_revision):
    """Commit original ownership and canonical Run together."""
    import project_scope_journal as scopes
    owned=scopes.transition_scope(connection,run_id=run_id,generation=generation,
        claim_token=scope_token,expected_revision=scope_revision,target='owned',witness=witness,producer_context=_SCOPE_MUTATION)
    mark_owned(connection,run_id=run_id,generation=generation,holder_token=holder_token,expected_revision=expected_revision)
    return owned.revision


def register_output(root, *, run_id,generation,holder_token,scope_token,scope_revision,expected_revision,witness):
    """Exact qualification conversion; no production route or Apply grant."""
    from private_state import private_state_lock,console_root
    from task_repository import _open_repository_database,_guarded_transaction
    from mentat.project_namespace_evidence import completion_metadata,completion_acceptance_deadline
    from mentat.project_output_blob import publish_output_blob,_record_attachment
    import project_scope_journal as scopes
    with private_state_lock(Path(root)),_open_repository_database(Path(root)) as (connection,guard):
        conversion={'new':False}
        def before_commit():
            if conversion['new']: completion_acceptance_deadline(witness)
        with _guarded_transaction(connection,guard,immediate=True,
                                  before_commit=before_commit):
            producer_ids(connection)
            binding,body=_binding(connection,run_id)
            if body['generation']!=generation: _fail('conflict')
            historical_hold=_holder(connection,run_id,generation,holder_token,historical=True)
            prior=connection.execute('SELECT receipt_digest FROM mentat_project_producer_outputs WHERE run_id=?',(run_id,)).fetchone()
            if prior is not None:
                # Reconcile only the same original completed capture request.
                metadata=completion_metadata(witness)
                retained=connection.execute('SELECT body_json FROM mentat_project_producer_outputs WHERE run_id=?',(run_id,)).fetchone()
                prior_body=_json(retained[0],_OUTPUT_KEYS)
                expected=connection.execute('SELECT state_revision-1 FROM mentat_runs WHERE id=?',(run_id,)).fetchone()[0]
                if (prior_body['terminal_digest']!=metadata['terminal_digest']
                        or metadata['query_digest']!=body['query_digest']
                        or metadata['image_digest']!=body['image_digest']
                        or metadata['runtime_image_digest']!=body['runtime_image_digest']
                        or type(expected_revision) is not int or expected_revision!=expected
                        or prior_body['request_digest']!=_capture_request(run_id,generation,holder_token,scope_token,
                            scope_revision,expected_revision,metadata)): _fail('conflict')
                return prior[0]
            conversion['new']=True
            hold=_holder(connection,run_id,generation,holder_token)
            journal._live_generation(connection,run_id,generation)
            row=connection.execute('SELECT status,state_revision FROM mentat_runs WHERE id=?',(run_id,)).fetchone()
            private=os.stat(console_root(Path(root)),follow_symlinks=False)
            if (type(expected_revision) is not int or tuple(row)!=('running',expected_revision)
                    or body['root_identity']!=[private.st_dev,private.st_ino]): _fail('fenced')
            metadata=completion_metadata(witness)
            completion_acceptance_deadline(witness)
            if (metadata['query_digest']!=body['query_digest'] or metadata['image_digest']!=body['image_digest']
                    or metadata['runtime_image_digest']!=body['runtime_image_digest'] or metadata['sealed_libraries'] is not True): _fail('binding')
            call=connection.execute('SELECT * FROM mentat_project_worker_calls WHERE run_id=?',(run_id,)).fetchone()
            if call is None or call[2]!=generation or call[6]!='succeeded' or call[8]!=metadata['result']['text']: _fail('call')
            payload=call[8].encode('utf-8')
            if len(payload)>hold[6]: _fail('capacity')
            try: parsed=parse_proposal_artifact(payload)
            except ProjectProposalArtifactError: parsed=None
            publication=publish_output_blob(Path(root),witness)
            attachment,blob=_record_attachment(connection,Path(root),publication,identity_guard=guard)
            stopped=scopes.transition_scope(connection,run_id=run_id,generation=generation,
                claim_token=scope_token,expected_revision=scope_revision,target='stopped',witness=witness._scope_witness,
                producer_context=_SCOPE_MUTATION)
            scope=connection.execute('SELECT closure_digest FROM mentat_project_worker_scopes WHERE run_id=?',(run_id,)).fetchone()
            output={'format':1,'purpose':'qualification','run_id':run_id,'generation':generation,
                'binding_digest':binding[3],'reservation_digest':hold[9],
                'disposition':'completed' if parsed is not None else 'invalid_artifact',
                'call_id':call[0],'result_digest':call[9],'closure_digest':scope[0],
                'terminal_digest':metadata['terminal_digest'],'output_bytes':metadata['result']['output_bytes'],
                'blob_sha256':publication.sha256,'byte_size':publication.byte_size,
                'parser_version':1 if parsed is not None else None,'snapshot':parsed,
                'snapshot_digest':proposal_snapshot_digest(parsed) if parsed is not None else None}
            output['request_digest']=_capture_request(run_id,generation,holder_token,scope_token,
                scope_revision,expected_revision,metadata)
            digest=journal._digest(output)
            connection.execute('INSERT INTO mentat_project_producer_outputs VALUES(?,?,?,?,?,?,?,?)',
                (run_id,call[0],run_id,attachment,blob,journal._encoded(output),digest,time.time()))
            _append_state(connection,run_id,'completed' if parsed is not None else 'failed','accepted')
            journal._validate_shared_graph(connection)
            producer_ids(connection)
            from run_repository import RunRepository
            RunRepository(connection).validate(private_producer_proposals=True)
            guard.capture()
            completion_acceptance_deadline(witness)
        return digest


def read_registered_output(root, *, run_id,generation,request_digest=None):
    """Owner-private durable readback; no witness/token recovery or new work."""
    from private_state import private_state_lock
    from task_repository import _open_repository_database
    from agent_console_attachments import read_attachment_bytes
    from run_repository import RunRepository
    with private_state_lock(Path(root)),_open_repository_database(Path(root)) as (connection,guard):
        RunRepository(connection).validate(private_producer_proposals=True)
        producer_ids(connection,archival=True)
        _,binding=_binding(connection,run_id)
        if binding['generation']!=generation: _fail('conflict')
        row=connection.execute('SELECT attachment_id,body_json,receipt_digest FROM mentat_project_producer_outputs WHERE run_id=?',(run_id,)).fetchone()
        if row is None: return None
        body=_json(row[1],_OUTPUT_KEYS)
        if request_digest is not None and (not isinstance(request_digest,str)
                or journal._HEX64.fullmatch(request_digest) is None or request_digest!=body['request_digest']): _fail('conflict')
        if row[0] is not None:
            _,payload=read_attachment_bytes(Path(root),row[0])
            if len(payload)!=body['byte_size'] or hashlib.sha256(payload).hexdigest()!=body['blob_sha256']: _fail('blob')
        guard.capture()
        return {'receipt_digest':row[2],'request_digest':body['request_digest'],
                'purpose':body['purpose'],'disposition':body['disposition'],
                'snapshot':body['snapshot'],'attachment_id':row[0]}
