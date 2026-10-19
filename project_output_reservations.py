"""Conserved prelaunch output capacity, never output or execution authority."""
from dataclasses import dataclass, field
import hashlib
import json
import secrets
import sqlite3
import time

import project_worker_journal as journal

MAX_RESERVATIONS = journal.MAX_GENERATIONS
METADATA_CHARGE = 128 * 1024


class OutputReservationError(journal.WorkerJournalError):
    pass


def _fail(code='invalid'):
    raise OutputReservationError('output_reservation.' + code)


def validate_output_reservations_connection(connection):
    """Historical exact graph and future representation charge, no permission."""
    version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    if version < 45:
        return []
    journal.validate_worker_journal_connection(connection)
    rows = connection.execute('SELECT * FROM mentat_project_output_reservations ORDER BY run_id').fetchmany(MAX_RESERVATIONS + 1)
    if len(rows) > MAX_RESERVATIONS:
        _fail('capacity')
    charged = []
    for row in rows:
        run, generation, epoch, manifest, policy_digest, slots, maximum, metadata, token_hash, digest, created = tuple(row)
        if (not isinstance(run, str) or journal._RUN.fullmatch(run) is None
                or not isinstance(generation, str) or journal._HEX32.fullmatch(generation) is None
                or not isinstance(epoch, bytes) or len(epoch) != 32
                or any(not isinstance(value, str) or journal._HEX64.fullmatch(value) is None
                       for value in (manifest, policy_digest, token_hash, digest))
                or type(slots) is not int or slots != 1
                or type(maximum) is not int or not 0 < maximum <= journal.MAX_RESPONSE_BYTES
                or type(metadata) is not int or metadata != METADATA_CHARGE
                or not journal._timestamp(created)):
            _fail()
        parent = connection.execute('SELECT * FROM mentat_project_worker_generations WHERE run_id=? AND generation=?',
                                    (run, generation)).fetchone()
        if (parent is None or tuple(parent[3:5]) != (epoch, manifest)
                or parent[7] != policy_digest or created < parent[10]
                or json.loads(parent[6])['max_response_bytes'] != maximum
                or digest != journal._digest([run, generation, epoch.hex(), manifest, policy_digest,
                                             slots, maximum, metadata, token_hash, parent[9], created])):
            _fail()
        for table in ('mentat_project_worker_scopes', 'mentat_project_worker_calls'):
            work = connection.execute(f'SELECT created_at FROM {table} WHERE run_id=?', (run,)).fetchone()
            if work is not None and work[0] < created:
                _fail('late')
        historical = [run, generation, epoch.hex(), *tuple(row[3:])]
        if len(journal._encoded(historical).encode('utf-8')) > METADATA_CHARGE - 128:
            _fail('capacity')
        charged.append([journal._digest(historical), 'x' * (METADATA_CHARGE - 128)])
    return charged


def pending_capacity(connection):
    """Return conserved slot/byte charges even after authority rotation."""
    validate_output_reservations_connection(connection)
    version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    if version < 45:
        return 0, 0
    if version >= 46:
        from project_producers import producer_ids
        producer_ids(connection,consumed_only=True)
        return tuple(connection.execute('SELECT COALESCE(SUM(blob_slots),0),COALESCE(SUM(max_bytes),0) '
            'FROM mentat_project_output_reservations h WHERE NOT EXISTS '
            '(SELECT 1 FROM mentat_project_producer_outputs o WHERE o.run_id=h.run_id)').fetchone())
    return tuple(connection.execute('SELECT COALESCE(SUM(blob_slots),0),COALESCE(SUM(max_bytes),0) '
                                    'FROM mentat_project_output_reservations').fetchone())


def require_output_reservation(connection, run_id, generation):
    """Require current precharged evidence, not a holder or launch grant."""
    validate_output_reservations_connection(connection)
    version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    if version < 45:
        _fail('unavailable')
    row = connection.execute('SELECT * FROM mentat_project_output_reservations WHERE run_id=? AND generation=?',
                             (run_id, generation)).fetchone()
    if row is None or row[2] != journal._epoch(connection):
        _fail('unavailable')
    return tuple(row)


@dataclass(frozen=True)
class OutputReservation:
    run_id: str
    generation: str
    max_bytes: int
    changed: bool
    holder_token: str | None = field(default=None, repr=False)


@journal._atomic_mutation
def reserve_output(connection, *, run_id, generation, now=None):
    """Reserve before any scope/call; caller must commit before launch."""
    journal._validate_shared_graph(connection)
    parent = journal._live_generation(connection, run_id, generation)
    version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    if version < 45:
        _fail('unavailable')
    prior = connection.execute('SELECT * FROM mentat_project_output_reservations WHERE run_id=?', (run_id,)).fetchone()
    if prior is not None:
        if prior[1] != generation:
            _fail('conflict')
        return OutputReservation(run_id, generation, prior[6], False)
    for table in ('mentat_project_worker_scopes', 'mentat_project_worker_calls'):
        if connection.execute(f'SELECT 1 FROM {table} WHERE run_id=?', (run_id,)).fetchone():
            _fail('late')
    if run_id not in journal.qualification_proposal_ids(connection):
        _fail('unavailable')
    created = time.time() if now is None else now
    if not journal._timestamp(created) or created < parent[10]:
        _fail()
    created = float(created)
    maximum = json.loads(parent[6])['max_response_bytes']
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode('ascii')).hexdigest()
    prefix = [run_id, generation, parent[3], parent[4], parent[7], 1, maximum, METADATA_CHARGE, token_hash]
    digest = journal._digest([*prefix[:2], parent[3].hex(), *prefix[3:], parent[9], created])
    try:
        connection.execute('INSERT INTO mentat_project_output_reservations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (*prefix, digest, created))
    except sqlite3.IntegrityError:
        _fail('conflict')
    journal._validate_shared_graph(connection)
    return OutputReservation(run_id, generation, maximum, True, token)
