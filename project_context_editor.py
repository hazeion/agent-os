"""Owner-only context preparation and history, independent of Agent execution."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
import re
import time

import agent_console_attachments as attachments
from private_state import private_state_lock
import project_context as context
from project_context_access import MAX_GRANT_REVISION, MAX_STAGED_FILES
from project_repository import ProjectRepository
from task_repository import _guarded_transaction, _open_repository_database


class ProjectContextEditorError(RuntimeError):
    pass


def _fail(reason):
    raise ProjectContextEditorError(f'project_context_editor.{reason}')


def _project(connection, project_id, expected_revision=None, *, active=False):
    repository = ProjectRepository(connection)
    repository.authority_receipt(required=True)
    project = repository.get(project_id)
    if expected_revision is not None and (type(expected_revision) is not int or project.revision != expected_revision):
        _fail('project_changed')
    if active and project.document['status'] != 'active':
        _fail('project_unavailable')
    return project


def _staging_capacity(connection):
    counts = connection.execute('SELECT project_id,COUNT(*) FROM mentat_project_context_staged GROUP BY project_id').fetchall()
    if sum(row[1] for row in counts) > MAX_STAGED_FILES or any(row[1] > context.MAX_FILES for row in counts):
        _fail('capacity')
    row = connection.execute(
        'SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM blobs WHERE id IN '
        '(SELECT a.blob_id FROM attachments a JOIN '
        '(SELECT attachment_id FROM mentat_retained_attachments UNION SELECT attachment_id FROM mentat_project_context_staged) r '
        'ON r.attachment_id=a.id)'
    ).fetchone()
    if row[0] > attachments.MAX_RETAINED_BLOBS or row[1] > attachments.MAX_RETAINED_BLOB_BYTES:
        _fail('capacity')


def _file_metadata(connection, identifier):
    row = connection.execute(
        'SELECT a.*,b.state AS blob_state FROM attachments a LEFT JOIN blobs b ON b.id=a.blob_id WHERE a.id=?', (identifier,)
    ).fetchone()
    if row is None:
        _fail('file_unavailable')
    metadata = attachments._public_metadata(row)
    metadata['available'] = row['state'] in {'attached','staged'} and row['blob_state'] == 'ready' and (row['expires_at'] is None or row['expires_at'] > time.time())
    return metadata


def _version_detail(connection, context_id):
    row = connection.execute(
        'SELECT v.id,v.revision,v.brief,v.created_at,s.project_id,s.retired_at,s.revision '
        'FROM mentat_project_context_versions v JOIN mentat_project_context_scopes s ON s.id=v.scope_id WHERE v.id=?', (context_id,)
    ).fetchone()
    if row is None:
        _fail('version_unavailable')
    files = [_file_metadata(connection, item[0]) for item in connection.execute(
        'SELECT attachment_id FROM mentat_project_context_files WHERE context_id=? ORDER BY ordinal', (context_id,)
    )]
    granted = connection.execute("SELECT 1 FROM mentat_project_context_grants WHERE context_id=? AND state='active'", (context_id,)).fetchone() is not None
    current = row[5] is None and row[1] == row[6]
    return {'id': row[0], 'revision': row[1], 'brief': row[2], 'created_at': row[3], 'project_id': row[4],
            'retired': row[5] is not None, 'current': current, 'files': files,
            'prune_blocked': 'current_version' if current else 'granted_version' if granted else None}


def read_context_version(data_dir: Path, context_id: str) -> dict:
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard):
                context.validate_project_context_connection(connection, require_available=False)
                return _version_detail(connection, context_id)


def read_project_editor(data_dir: Path, project_id: str) -> dict:
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard):
                project = _project(connection, project_id)
                context.validate_project_context_connection(connection, require_available=False)
                rows = connection.execute(
                    'SELECT v.id,v.revision,v.created_at,s.id FROM mentat_project_context_versions v '
                    'JOIN mentat_project_context_scopes s ON s.id=v.scope_id WHERE s.project_id=? AND s.retired_at IS NULL ORDER BY v.revision DESC', (project_id,)
                ).fetchall()
                versions = [{'id': row[0], 'revision': row[1], 'created_at': row[2]} for row in rows]
                current = _version_detail(connection, rows[0][0]) if rows else None
                staged = [_file_metadata(connection, row[0]) for row in connection.execute(
                    'SELECT attachment_id FROM mentat_project_context_staged WHERE project_id=? ORDER BY attachment_id', (project_id,)
                )]
                grants = [dict(zip(('agent_id','context_id','revision','state','reason'), tuple(row))) for row in connection.execute(
                    'SELECT g.agent_id,g.context_id,g.revision,g.state,g.reason FROM mentat_project_context_grants g '
                    'JOIN mentat_project_context_scopes s ON s.id=g.scope_id '
                    'JOIN mentat_agents a ON a.id=g.agent_id AND a.context_incarnation=g.agent_incarnation '
                    'WHERE s.project_id=? AND s.retired_at IS NULL ORDER BY g.agent_id LIMIT 128', (project_id,)
                )]
                return {'project': {'id': project_id, 'name': project.document['name'], 'revision': project.revision, 'status': project.document['status']},
                        'current': current, 'versions': versions, 'staged': staged, 'grants': grants}


def read_retired_context_history(data_dir: Path) -> list[dict]:
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard):
                context.validate_project_context_connection(connection, require_available=False)
                return [{'id': row[0], 'revision': row[1], 'created_at': row[2], 'summary': ' '.join(row[3].split())[:120] or 'Saved context'} for row in connection.execute(
                    'SELECT v.id,v.revision,v.created_at,v.brief FROM mentat_project_context_versions v '
                    'JOIN mentat_project_context_scopes s ON s.id=v.scope_id WHERE s.retired_at IS NOT NULL ORDER BY s.retired_at DESC,v.revision DESC LIMIT 256'
                )]



def stage_project_file(data_dir: Path, project_id: str, *, expected_project_revision: int,
                       original_name: str, content: bytes, content_type: str | None = None) -> dict:
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                _project(connection, project_id, expected_project_revision, active=True)
                connection.execute(
                    "DELETE FROM mentat_project_context_staged WHERE attachment_id IN "
                    "(SELECT id FROM attachments WHERE state!='staged' OR expires_at<=?)", (time.time(),)
                )
                count = connection.execute('SELECT COUNT(*) FROM mentat_project_context_staged').fetchone()[0]
                project_count = connection.execute('SELECT COUNT(*) FROM mentat_project_context_staged WHERE project_id=?', (project_id,)).fetchone()[0]
                if count >= MAX_STAGED_FILES or project_count >= context.MAX_FILES:
                    _fail('capacity')
        # Blob creation owns its own transaction. Keep the shared root lock,
        # but never nest it inside a second SQLite writer transaction.
        metadata = attachments.create_attachment(root, original_name=original_name, content=content, content_type=content_type)
        try:
            with _open_repository_database(root) as (connection, guard):
                with _guarded_transaction(connection, guard, immediate=True):
                    _project(connection, project_id, expected_project_revision, active=True)
                    connection.execute(
                        "DELETE FROM mentat_project_context_staged WHERE attachment_id IN "
                        "(SELECT id FROM attachments WHERE expires_at IS NOT NULL AND expires_at<=?)", (time.time(),)
                    )
                    connection.execute('INSERT INTO mentat_project_context_staged VALUES(?,?,?)', (metadata['id'], project_id, time.time()))
                    _staging_capacity(connection)
                    context.validate_project_context_connection(connection, require_available=False)
            return metadata
        except Exception:
            attachments.release_attachment(root, metadata['id'], grace_seconds=0)
            attachments.garbage_collect(root)
            raise


def discard_project_file(data_dir: Path, project_id: str, attachment_id: str, *, expected_project_revision: int) -> None:
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                _project(connection, project_id, expected_project_revision)
                removed = connection.execute('DELETE FROM mentat_project_context_staged WHERE project_id=? AND attachment_id=?', (project_id, attachment_id))
                if removed.rowcount != 1:
                    _fail('file_unavailable')
                connection.execute(
                    "UPDATE attachments SET state='orphaned',expires_at=NULL,delete_after=?,updated_at=? WHERE id=? "
                    'AND NOT EXISTS (SELECT 1 FROM mentat_retained_attachments WHERE attachment_id=?)',
                    (time.time()+attachments.DEFAULT_ORPHAN_GRACE, time.time(), attachment_id, attachment_id),
                )


def read_project_file(data_dir: Path, *, attachment_id: str, project_id: str | None = None, context_id: str | None = None) -> tuple[dict, bytes]:
    """Trusted owner read through exact staging or immutable-version membership."""
    if (project_id is None) == (context_id is None):
        _fail('file_scope')
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                context.validate_project_context_connection(connection, require_available=False)
                if project_id is not None:
                    _project(connection, project_id)
                    allowed = connection.execute(
                        "SELECT 1 FROM mentat_project_context_staged s JOIN attachments a ON a.id=s.attachment_id "
                        "WHERE s.project_id=? AND s.attachment_id=? AND a.state='staged' AND a.expires_at>?",
                        (project_id, attachment_id, time.time()),
                    ).fetchone()
                else:
                    allowed = connection.execute('SELECT 1 FROM mentat_project_context_files WHERE context_id=? AND attachment_id=?', (context_id, attachment_id)).fetchone()
                if allowed is None:
                    _fail('file_scope')
                return attachments.read_attachment_bytes(root, attachment_id)


def _prune_snapshot(connection, context_id):
    context.validate_project_context_connection(connection, require_available=False)
    row = connection.execute(
        'SELECT v.scope_id,v.revision,v.brief,v.files_digest,s.revision,s.retired_at FROM mentat_project_context_versions v '
        'JOIN mentat_project_context_scopes s ON s.id=v.scope_id WHERE v.id=?', (context_id,)
    ).fetchone()
    if row is None:
        _fail('version_unavailable')
    if row[5] is None and row[1] == row[4]:
        _fail('current_version')
    grants = [tuple(item) for item in connection.execute(
        'SELECT agent_id,agent_incarnation,revision,state,context_id FROM mentat_project_context_grants WHERE scope_id=? ORDER BY agent_id', (row[0],)
    )]
    if any(item[3] == 'active' and item[4] == context_id for item in grants):
        _fail('granted_version')
    files = tuple(item[0] for item in connection.execute('SELECT attachment_id FROM mentat_project_context_files WHERE context_id=? ORDER BY ordinal', (context_id,)))
    references = []
    for identifier in files:
        references.append([identifier,
            [tuple(item) for item in connection.execute('SELECT run_id,direction,ordinal FROM run_attachments WHERE attachment_id=? ORDER BY run_id,direction', (identifier,))],
            [item[0] for item in connection.execute('SELECT context_id FROM mentat_project_context_files WHERE attachment_id=? ORDER BY context_id', (identifier,))]])
    epoch = connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state').fetchone()[0].hex()
    claims = ['prune', epoch, context_id, list(row), grants, references]
    confirmation = hashlib.sha256(json.dumps(claims, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return row, files, confirmation


def preview_context_prune(data_dir: Path, context_id: str) -> dict:
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard):
                row, files, confirmation = _prune_snapshot(connection, context_id)
                return {'context_id': context_id, 'revision': row[1], 'file_count': len(files), 'confirmation_id': confirmation}


def confirm_context_prune(data_dir: Path, context_id: str, *, confirmation_id: str) -> None:
    if not isinstance(confirmation_id, str) or not re.fullmatch(r'[0-9a-f]{64}', confirmation_id):
        _fail('confirmation_invalid')
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                row, files, expected = _prune_snapshot(connection, context_id)
                if not hmac.compare_digest(confirmation_id, expected):
                    _fail('stale')
                # Keep the grant tombstone: deleting it would reset revisions
                # and could revive a pre-grant preview after an ABA cycle.
                connection.execute(
                    "UPDATE mentat_project_context_grants SET context_id=NULL,reason='context_pruned',"
                    'revision=MIN(revision+1,?),updated_at=? WHERE context_id=? AND state=\'revoked\'',
                    (MAX_GRANT_REVISION, time.time(), context_id),
                )
                connection.execute('DELETE FROM mentat_project_context_files WHERE context_id=?', (context_id,))
                connection.execute('DELETE FROM mentat_project_context_versions WHERE id=?', (context_id,))
                remaining = connection.execute('SELECT MAX(revision) FROM mentat_project_context_versions WHERE scope_id=?', (row[0],)).fetchone()[0]
                if row[5] is not None:
                    if remaining is None:
                        connection.execute('DELETE FROM mentat_project_context_grants WHERE scope_id=?', (row[0],))
                        connection.execute('DELETE FROM mentat_project_context_scopes WHERE id=?', (row[0],))
                    else:
                        connection.execute('UPDATE mentat_project_context_scopes SET revision=? WHERE id=?', (remaining,row[0]))
                for identifier in files:
                    connection.execute(
                        "UPDATE attachments SET state='orphaned',expires_at=NULL,delete_after=?,updated_at=? WHERE id=? "
                        'AND NOT EXISTS (SELECT 1 FROM mentat_retained_attachments WHERE attachment_id=?)',
                        (time.time()+attachments.DEFAULT_ORPHAN_GRACE, time.time(), identifier, identifier),
                    )
                context.validate_project_context_connection(connection, require_available=False)
