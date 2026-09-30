"""Private scope bookkeeping; no launch, signal, Run or provider authority."""

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time

import project_worker_journal as journal
from mentat.project_scope_evidence import witness_metadata
from mentat.project_worker_scope import WorkerScopeError

MAX_SCOPES = 128
METADATA_CHARGE = 8192
_UNIT = re.compile(r"mentat-project-worker-[0-9a-f]{32}\.scope\Z")
_PLAN = frozenset({'unit','boot_id','uid','memory_bytes','processes','cpu_percent','wall_seconds'})
_KERNEL = frozenset({'invocation','device','inode','pid','start_ticks'})
_EDGES = {'prepared': {'starting','cancelled'}, 'starting': {'owned','unknown','stopped'},
          'owned': {'unknown','stopped'}, 'unknown': {'stopped'}, 'stopped': set(), 'cancelled': set()}
_REVISIONS = {'prepared': {1}, 'starting': {2}, 'owned': {3}, 'unknown': {3,4},
              'cancelled': {2}, 'stopped': {3,4,5}}


class ScopeJournalError(journal.WorkerJournalError):
    pass


def _fail(code='invalid'):
    raise ScopeJournalError('scope_journal.' + code)


def _encoded(value):
    return journal._encoded(value)


def _digest(value):
    return journal._digest(value)


def _plan(value):
    if not isinstance(value, dict) or set(value) != _PLAN:
        _fail()
    if (not isinstance(value['unit'], str) or _UNIT.fullmatch(value['unit']) is None
            or not isinstance(value['boot_id'], str) or journal._HEX32.fullmatch(value['boot_id']) is None
            or value['boot_id'] == '0'*32):
        _fail()
    for key, ceiling in {'uid': 2**31-1, 'memory_bytes': 512*1024*1024, 'processes': 32,
                         'cpu_percent': 100, 'wall_seconds': 3600}.items():
        if type(value[key]) is not int or not 0 < value[key] <= ceiling:
            _fail()
    return _encoded(value)


def _identity(value, plan):
    if not isinstance(value, dict) or set(value) != _PLAN | _KERNEL:
        _fail()
    if {key: value[key] for key in _PLAN} != plan:
        _fail('identity')
    if not isinstance(value['invocation'], str) or journal._HEX32.fullmatch(value['invocation']) is None:
        _fail()
    for key in ('device','inode','pid','start_ticks'):
        if type(value[key]) is not int or not 0 < value[key] < 2**63:
            _fail()
    return _encoded(value)


def _row(connection, run_id):
    result = connection.execute('SELECT * FROM mentat_project_worker_scopes WHERE run_id=?', (run_id,)).fetchone()
    if result is None:
        _fail('unavailable')
    return tuple(result)


def _witness(value, kind):
    try:
        return witness_metadata(value,kind)
    except (ValueError, WorkerScopeError):
        _fail('identity')


def validate_scope_journal_connection(connection):
    """Historical graph and fixed worst-case accounting, not live OS evidence."""
    version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    if version < 44:
        return []
    journal.validate_worker_journal_connection(connection)
    rows = connection.execute('SELECT * FROM mentat_project_worker_scopes ORDER BY run_id').fetchmany(MAX_SCOPES+1)
    if len(rows) > MAX_SCOPES:
        _fail('capacity')
    charged = []
    for raw in rows:
        (run, generation, unit, epoch, plan_json, plan_hash, claim, token_hash, created,
         revision, state, identity_json, identity_hash, closure, intent, updated) = tuple(raw)
        if (not isinstance(run,str) or journal._RUN.fullmatch(run) is None
                or not isinstance(generation,str) or journal._HEX32.fullmatch(generation) is None
                or not isinstance(epoch,bytes) or len(epoch)!=32
                or type(revision) is not int or state not in _REVISIONS or revision not in _REVISIONS[state]
                or not journal._timestamp(created) or not journal._timestamp(updated) or updated < created
                or any(not isinstance(item,str) or journal._HEX64.fullmatch(item) is None
                       for item in (plan_hash,claim,token_hash))):
            _fail()
        try:
            plan = json.loads(plan_json)
            identity = json.loads(identity_json) if identity_json is not None else None
        except (TypeError, ValueError):
            _fail()
        if _plan(plan) != plan_json or _digest(plan) != plan_hash or unit != plan['unit']:
            _fail()
        parent = connection.execute('SELECT authority_epoch,policy_json,claim_digest,created_at '
                                    'FROM mentat_project_worker_generations WHERE run_id=? AND generation=?',
                                    (run,generation)).fetchone()
        if parent is None or parent[0] != epoch or created < parent[3]:
            _fail()
        policy = json.loads(parent[1])
        if any(plan[key] != policy[key] for key in ('memory_bytes','processes','cpu_percent','wall_seconds')):
            _fail()
        if claim != _digest([run,generation,epoch.hex(),parent[2],plan,token_hash,created]):
            _fail()
        if identity is None:
            if identity_hash is not None or state in {'owned','stopped'} or state == 'unknown' and revision != 3:
                _fail()
        elif (_identity(identity,plan) != identity_json or identity_hash != _digest(identity)
              or state in {'prepared','starting','cancelled'} or state == 'unknown' and revision != 4):
            _fail()
        if state == 'stopped':
            if closure != _digest(['closed',identity]):
                _fail()
        elif closure is not None:
            _fail()
        if state == 'prepared':
            if intent is not None or updated != created:
                _fail()
        elif intent != _digest([state,revision-1,identity if state in {'owned','stopped'} else None]):
            _fail()
        historical = [*tuple(raw[:3]),epoch.hex(),*tuple(raw[4:])]
        if len(_encoded(historical).encode('utf-8')) > METADATA_CHARGE-128:
            _fail('capacity')
        # The actual rows remain authoritative in SQLite. A fixed charge with
        # their digest reserves all later identity/closure representation now.
        charged.append([_digest(historical),'x'*(METADATA_CHARGE-128)])
    return charged


def require_archival_scopes(connection):
    validate_scope_journal_connection(connection)
    version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    if version >= 44 and connection.execute("SELECT 1 FROM mentat_project_worker_scopes WHERE state NOT IN "
                                           "('prepared','cancelled','stopped') LIMIT 1").fetchone():
        _fail('active_archival')


@dataclass(frozen=True)
class ScopeReceipt:
    run_id: str
    generation: str
    state: str
    revision: int
    changed: bool
    claim_token: str | None = field(default=None, repr=False)


def _receipt(row, changed=False, token=None):
    return ScopeReceipt(row[0],row[1],row[10],row[9],changed,token)


def read_scope(connection, run_id):
    """Historical private summary; never return a recovered claim token."""
    journal._validate_shared_graph(connection)
    return _receipt(_row(connection,run_id))


@journal._atomic_mutation
def prepare_scope(connection, *, run_id, generation, plan_witness, now=None):
    """Record private intent only. Commit before any separately admitted work."""
    journal._validate_shared_graph(connection)
    parent = journal._live_generation(connection,run_id,generation)
    plan = _witness(plan_witness,'planned')
    plan_json = _plan(plan)
    policy = json.loads(parent[6])
    if any(plan[key] != policy[key] for key in ('memory_bytes','processes','cpu_percent','wall_seconds')):
        _fail('policy')
    prior = connection.execute('SELECT * FROM mentat_project_worker_scopes WHERE run_id=?',(run_id,)).fetchone()
    if prior is not None:
        prior = tuple(prior)
        if prior[1] != generation or prior[4] != plan_json:
            _fail('conflict')
        return _receipt(prior)
    if connection.execute('SELECT COUNT(*) FROM mentat_project_worker_scopes').fetchone()[0] >= MAX_SCOPES:
        _fail('capacity')
    created = time.time() if now is None else now
    if not journal._timestamp(created) or created < parent[10]:
        _fail()
    created = float(created)
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode('ascii')).hexdigest()
    claim = _digest([run_id,generation,parent[3].hex(),parent[9],plan,token_hash,created])
    try:
        connection.execute('INSERT INTO mentat_project_worker_scopes VALUES(?,?,?,?,?,?,?,?,?,1,\'prepared\',NULL,NULL,NULL,NULL,?)',
                           (run_id,generation,plan['unit'],parent[3],plan_json,_digest(plan),claim,token_hash,created,created))
    except sqlite3.IntegrityError:
        _fail('conflict')
    journal._validate_shared_graph(connection)
    return _receipt(_row(connection,run_id),True,token)


@journal._atomic_mutation
def transition_scope(connection, *, run_id, generation, claim_token, expected_revision, target, witness=None, now=None):
    """One-way bookkeeping; changed=True never grants launch/signal authority."""
    journal._validate_shared_graph(connection)
    row = _row(connection,run_id)
    if (row[1] != generation or not isinstance(claim_token,str) or journal._HEX64.fullmatch(claim_token) is None
            or not hmac.compare_digest(row[7],hashlib.sha256(claim_token.encode('ascii')).hexdigest())):
        _fail('token')
    if type(expected_revision) is not int or expected_revision < 1 or not isinstance(target,str) or target not in _EDGES:
        _fail()
    plan = json.loads(row[4])
    supplied = None
    if target in {'owned','stopped'}:
        supplied = _witness(witness,'owned' if target == 'owned' else 'closed')
        _identity(supplied,plan)
    elif witness is not None:
        _fail()
    intent = _digest([target,expected_revision,supplied])
    if row[10] == target and row[14] == intent:
        return _receipt(row)
    if row[9] != expected_revision or target not in _EDGES[row[10]]:
        _fail('conflict')
    if target in {'starting','owned'}:
        journal._live_generation(connection,run_id,generation)
    identity_json, identity_hash = row[11:13]
    if supplied is not None:
        encoded = _identity(supplied,plan)
        if identity_json is not None and identity_json != encoded:
            _fail('identity')
        identity_json, identity_hash = encoded, _digest(supplied)
    updated = time.time() if now is None else now
    if not journal._timestamp(updated) or updated < row[15]:
        _fail()
    closure = _digest(['closed',supplied]) if target == 'stopped' else None
    connection.execute('UPDATE mentat_project_worker_scopes SET revision=revision+1,state=?,identity_json=?,identity_digest=?, '
                       'closure_digest=?,last_intent_digest=?,updated_at=? WHERE run_id=? AND revision=?',
                       (target,identity_json,identity_hash,closure,intent,float(updated),run_id,expected_revision))
    journal._validate_shared_graph(connection)
    return _receipt(_row(connection,run_id),True)
