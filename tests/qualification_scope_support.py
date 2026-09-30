"""Disposable real-scope fixtures; no production admission or provider calls."""
from contextlib import closing

import mentat_db
import project_scope_journal as journal
from project_output_reservations import require_output_reservation
from private_state import private_state_lock


def start_recorded_scope(root, run_id, generation, scope):
    with private_state_lock(root), closing(mentat_db.connect(root)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        # A separate committed read must precede any scope intent or launch.
        require_output_reservation(connection, run_id, generation)
        prepared = journal.prepare_scope(connection, run_id=run_id, generation=generation,
                                         plan_witness=scope.journal_plan())
        starting = journal.transition_scope(connection, run_id=run_id, generation=generation,
            claim_token=prepared.claim_token, expected_revision=prepared.revision, target='starting')
        connection.commit()
        readback = journal.read_scope(connection, run_id)
        if readback.generation != generation or readback.state != 'starting' or readback.revision != starting.revision:
            raise AssertionError('Qualification scope starting commit unavailable')
    scope.start_inert()
    with private_state_lock(root), closing(mentat_db.connect(root)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        owned = journal.transition_scope(connection, run_id=run_id, generation=generation,
            claim_token=prepared.claim_token, expected_revision=starting.revision,
            target='owned', witness=scope.journal_owned_identity())
        connection.commit()
    return prepared.claim_token, owned.revision


def close_recorded_scope(root, run_id, generation, scope, receipt):
    if not scope._closed:
        scope.close_verified()
    with private_state_lock(root), closing(mentat_db.connect(root)) as connection:
        connection.execute('BEGIN IMMEDIATE')
        journal.transition_scope(connection, run_id=run_id, generation=generation,
            claim_token=receipt[0], expected_revision=receipt[1], target='stopped',
            witness=scope.journal_closed_identity())
        connection.commit()
