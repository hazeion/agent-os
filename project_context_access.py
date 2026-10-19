"""Exact owner-approved context grants. These records never dispatch an Agent."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from agent_console_attachments import read_attachment_bytes, AttachmentError
from agent_registry import _canonical_agent_records, AgentRegistryError
from private_state import private_state_lock
from project_repository import ProjectRepository
from task_repository import _guarded_transaction, _open_repository_database

MAX_GRANTS = 256 * 128
MAX_STAGED_FILES = 64
MAX_GRANT_REVISION = 9007199254740991
_IDENTITY = re.compile(r"[0-9a-f]{32}\Z")
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class ProjectContextAccessError(RuntimeError):
    pass


def _fail(reason):
    raise ProjectContextAccessError(f"project_context_access.{reason}")


def validate_access_connection(connection: sqlite3.Connection) -> list[list]:
    """Validate the full grant graph and return bounded rows for shared quotas."""
    epochs = connection.execute('SELECT singleton,approval_epoch FROM mentat_project_context_access_state').fetchall()
    if len(epochs) != 1 or epochs[0][0] != 1 or not isinstance(epochs[0][1], bytes) or len(epochs[0][1]) != 32:
        _fail('invalid')
    agents = {}
    agent_rows = connection.execute('SELECT id,context_incarnation FROM mentat_agents ORDER BY id').fetchmany(129)
    if len(agent_rows) > 128:
        _fail('invalid')
    for identifier, incarnation in agent_rows:
        if not isinstance(identifier, str) or not _AGENT.fullmatch(identifier) or not isinstance(incarnation, str) or not _IDENTITY.fullmatch(incarnation):
            _fail('invalid')
        agents[identifier] = incarnation
    rows = connection.execute(
        'SELECT scope_id,agent_id,agent_incarnation,context_id,revision,state,reason,updated_at '
        'FROM mentat_project_context_grants ORDER BY scope_id,agent_id'
    ).fetchmany(MAX_GRANTS + 1)
    if len(rows) > MAX_GRANTS:
        _fail('capacity')
    scopes = {row[0]: row[1] for row in connection.execute('SELECT id,retired_at FROM mentat_project_context_scopes')}
    contexts = {row[0]: row[1] for row in connection.execute('SELECT id,scope_id FROM mentat_project_context_versions')}
    if epochs[0][1] == bytes(32) and (contexts or rows):
        _fail('invalid')
    for scope, agent, incarnation, context, revision, state, reason, updated in rows:
        if (scope not in scopes or not isinstance(agent, str) or not _AGENT.fullmatch(agent)
                or not isinstance(incarnation, str) or not _IDENTITY.fullmatch(incarnation)
                or type(revision) is not int or not 1 <= revision <= MAX_GRANT_REVISION
                or not isinstance(updated, (int, float)) or not math.isfinite(updated) or updated <= 0
                or (context is not None and contexts.get(context) != scope)):
            _fail('invalid')
        if state == 'active':
            if context is None or scopes[scope] is not None or agents.get(agent) != incarnation or reason is not None or revision >= MAX_GRANT_REVISION:
                _fail('invalid')
        elif state != 'revoked' or reason not in {'owner','project_deleted','agent_deleted','restored','context_pruned'}:
            _fail('invalid')
    staged = connection.execute(
        'SELECT attachment_id,project_id,created_at FROM mentat_project_context_staged ORDER BY attachment_id'
    ).fetchmany(MAX_STAGED_FILES + 1)
    if len(staged) > MAX_STAGED_FILES:
        _fail('capacity')
    projects = {row[0] for row in connection.execute('SELECT id FROM mentat_projects')}
    for attachment, project_id, created in staged:
        if (not isinstance(attachment, str) or not re.fullmatch(r'attachment_[0-9a-f]{32}', attachment)
                or project_id not in projects or not isinstance(created, (int, float))
                or not math.isfinite(created) or created <= 0
                or connection.execute('SELECT 1 FROM attachments WHERE id=?', (attachment,)).fetchone() is None):
            _fail('invalid')
    # Reserve terminal representation and counter/timestamp growth up front.
    # A valid live backup must remain within the same budget after revocation.
    charged = [list(row[:4]) + [MAX_GRANT_REVISION, 'revoked', 'project_deleted', '0' * 32] for row in rows]
    # Agent creation is a separate authority operation. Reserve its entire
    # supported identity projection so adding/replacing an Agent cannot make
    # an already admitted context graph invalid or unbackuppable.
    agent_reservation = [['x' * 128, '0' * 32] for _ in range(128)]
    return [charged, [list(row) for row in staged], [[1, epochs[0][1].hex()]], agent_reservation]


def revoke_after_restore(connection: sqlite3.Connection, *, now: float | None = None, epoch_seed: bytes | None = None) -> None:
    timestamp = time.time() if now is None else now
    if epoch_seed is None:
        connection.execute('UPDATE mentat_project_context_access_state SET approval_epoch=randomblob(32) WHERE singleton=1')
    else:
        if not isinstance(epoch_seed, bytes) or len(epoch_seed) != 32:
            _fail('restore_invalid')
        original = connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state WHERE singleton=1').fetchone()[0]
        epoch = hmac.new(original, b'mentat-project-context-restore-v1\0' + epoch_seed, hashlib.sha256).digest()
        connection.execute('UPDATE mentat_project_context_access_state SET approval_epoch=? WHERE singleton=1', (epoch,))
    connection.execute(
        "UPDATE mentat_project_context_grants SET state='revoked',reason='restored',revision=revision+1,updated_at=? WHERE state='active'",
        (timestamp,),
    )
    connection.execute('DELETE FROM mentat_project_context_staged')


def _validated_context(connection, project_id, context_id, agent_id):
    from project_context import validate_project_context_connection
    validate_project_context_connection(connection, require_available=False)
    project = ProjectRepository(connection).get(project_id)
    if project.document['status'] != 'active':
        _fail('project_unavailable')
    row = connection.execute(
        'SELECT s.id,s.revision,v.revision,v.brief,v.files_digest FROM mentat_project_context_scopes s '
        'JOIN mentat_project_context_versions v ON v.scope_id=s.id '
        'WHERE s.project_id=? AND s.retired_at IS NULL AND v.id=?', (project_id, context_id)
    ).fetchone()
    if row is None:
        _fail('context_unavailable')
    try:
        records = _canonical_agent_records(connection, supported_runtime_types=('hermes','codex','vercel'))
    except AgentRegistryError:
        _fail('agent_unavailable')
    record = next((item for item in records if item.agent.id == agent_id), None)
    if record is None:
        _fail('agent_unavailable')
    identity = connection.execute('SELECT context_incarnation FROM mentat_agents WHERE id=?', (agent_id,)).fetchone()[0]
    grant = connection.execute(
        'SELECT agent_incarnation,context_id,revision,state,reason FROM mentat_project_context_grants WHERE scope_id=? AND agent_id=?',
        (row[0], agent_id),
    ).fetchone()
    identifiers = [item[0] for item in connection.execute(
        'SELECT attachment_id FROM mentat_project_context_files WHERE context_id=? ORDER BY ordinal', (context_id,)
    )]
    epoch = connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state WHERE singleton=1').fetchone()[0].hex()
    claims = [epoch, row[0], row[1], project_id, project.revision, context_id, row[2], row[3], row[4],
              agent_id, identity, record.revision, record.agent.runtime_config_id, list(grant) if grant else None]
    confirmation = hashlib.sha256(json.dumps(claims, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return row, record, identity, grant, identifiers, confirmation


def preview_context_grant(data_dir: Path, project_id: str, context_id: str, agent_id: str) -> dict:
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard):
                row, record, _identity, grant, identifiers, confirmation = _validated_context(connection, project_id, context_id, agent_id)
                files = []
                for identifier in identifiers:
                    try:
                        metadata, _ = read_attachment_bytes(data_dir, identifier)
                    except (AttachmentError, OSError):
                        _fail('file_unavailable')
                    files.append(metadata)
                return {'project_id': project_id, 'context_id': context_id, 'context_revision': row[2],
                        'brief': row[3], 'files': files, 'agent_id': agent_id, 'agent_name': record.agent.name,
                        'grant_revision': grant[2] if grant else 0, 'confirmation_id': confirmation}


def confirm_context_grant(data_dir: Path, project_id: str, context_id: str, agent_id: str, *, confirmation_id: str) -> dict:
    if not isinstance(confirmation_id, str) or not re.fullmatch(r'[0-9a-f]{64}', confirmation_id):
        _fail('confirmation_invalid')
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                row, _record, identity, grant, identifiers, expected = _validated_context(connection, project_id, context_id, agent_id)
                if not hmac.compare_digest(expected, confirmation_id):
                    _fail('stale')
                for identifier in identifiers:
                    try:
                        read_attachment_bytes(data_dir, identifier)
                    except (AttachmentError, OSError):
                        _fail('file_unavailable')
                revision = (grant[2] if grant else 0) + 1
                if revision >= MAX_GRANT_REVISION:
                    _fail('capacity')
                connection.execute(
                    "INSERT INTO mentat_project_context_grants VALUES(?,?,?,?,?,'active',NULL,?) "
                    "ON CONFLICT(scope_id,agent_id) DO UPDATE SET agent_incarnation=excluded.agent_incarnation,"
                    "context_id=excluded.context_id,revision=excluded.revision,state='active',reason=NULL,updated_at=excluded.updated_at",
                    (row[0], agent_id, identity, context_id, revision, time.time()),
                )
                from project_context import validate_project_context_connection
                validate_project_context_connection(connection, require_available=False)
                return {'project_id': project_id, 'context_id': context_id, 'agent_id': agent_id, 'revision': revision, 'state': 'active'}


def revoke_context_grant(data_dir: Path, project_id: str, context_id: str, agent_id: str, *, expected_revision: int) -> dict:
    if type(expected_revision) is not int or expected_revision < 1:
        _fail('revision_invalid')
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                from project_context import validate_project_context_connection
                validate_project_context_connection(connection, require_available=False)
                row = connection.execute(
                    'SELECT g.scope_id,g.revision,g.context_id,g.state FROM mentat_project_context_grants g '
                    'JOIN mentat_project_context_scopes s ON s.id=g.scope_id '
                    'WHERE s.project_id=? AND s.retired_at IS NULL AND g.agent_id=?', (project_id, agent_id)
                ).fetchone()
                if row is None or row[1] != expected_revision or row[2] != context_id:
                    _fail('stale')
                revision = row[1]
                if row[3] == 'active':
                    revision += 1
                    connection.execute(
                        "UPDATE mentat_project_context_grants SET revision=?,state='revoked',reason='owner',updated_at=? WHERE scope_id=? AND agent_id=?",
                        (revision, time.time(), row[0], agent_id),
                    )
                return {'project_id': project_id, 'context_id': row[2], 'agent_id': agent_id, 'revision': revision, 'state': 'revoked'}
