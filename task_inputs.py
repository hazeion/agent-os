"""Bounded owner Task-input selections; normalization grants no execution rights.

Storage/admission must additionally resolve exact live incarnations, membership,
grants, verified bytes and qualified runtime policy under the private root lock.
This module never resolves a browser-selected path or calls a runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import time
import uuid

from agent_console_attachments import MAX_IMAGE_BYTES, MAX_TEXT_BYTES, _TEXT_CONTENT_TYPES

MAX_INSTRUCTION_BYTES = 16 * 1024
MAX_INPUT_FILES = 8
MAX_INPUT_IMAGES = 1
MAX_INPUT_VERSIONS = 256
MAX_TASK_INPUT_VERSIONS = 32
MAX_REVISION = 9007199254740991
_PROJECT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z')
_TASK = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z')
_AGENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
_CONTEXT = re.compile(r'project_context_[0-9a-f]{32}\Z')
_ATTACHMENT = re.compile(r'attachment_[0-9a-f]{32}\Z')
_FIELDS = frozenset({'project_id', 'task_id', 'agent_id', 'expected_task_revision',
                     'expected_input_revision', 'context_id', 'expected_grant_revision',
                     'expected_task_token', 'instructions', 'attachment_ids'})


class TaskInputError(RuntimeError):
    """Fixed public-safe failure without file, credential or runtime details."""


def _fail(reason: str) -> None:
    raise TaskInputError(f'task_input.{reason}')


@dataclass(frozen=True)
class TaskInputSelection:
    project_id: str
    task_id: str
    agent_id: str
    expected_task_revision: int
    expected_input_revision: int
    context_id: str
    expected_grant_revision: int
    expected_task_token: str
    instructions: str
    attachment_ids: tuple[str, ...]


@dataclass(frozen=True)
class _RetainedSelection:
    attachment_ids: tuple[str, ...]


def normalize_input_selection(payload: object) -> TaskInputSelection:
    if not isinstance(payload, dict) or set(payload) != _FIELDS:
        _fail('invalid')
    for name, pattern in (('project_id', _PROJECT), ('task_id', _TASK),
                          ('agent_id', _AGENT), ('context_id', _CONTEXT)):
        value = payload[name]
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            _fail('invalid')
    for name in ('expected_task_revision', 'expected_input_revision', 'expected_grant_revision'):
        minimum = 0 if name == 'expected_input_revision' else 1
        if type(payload[name]) is not int or not minimum <= payload[name] <= MAX_REVISION:
            _fail('revision_invalid')
    if not isinstance(payload['expected_task_token'], str) or re.fullmatch(r'[0-9a-f]{64}', payload['expected_task_token']) is None:
        _fail('revision_invalid')
    instructions = payload['instructions']
    if not isinstance(instructions, str) or '\0' in instructions:
        _fail('instructions_invalid')
    try:
        if len(instructions.encode('utf-8')) > MAX_INSTRUCTION_BYTES:
            _fail('instructions_invalid')
    except UnicodeError:
        _fail('instructions_invalid')
    identifiers = payload['attachment_ids']
    if not isinstance(identifiers, list) or len(identifiers) > MAX_INPUT_FILES:
        _fail('files_invalid')
    if any(not isinstance(item, str) or _ATTACHMENT.fullmatch(item) is None for item in identifiers):
        _fail('files_invalid')
    if len(set(identifiers)) != len(identifiers):
        _fail('files_invalid')
    return TaskInputSelection(**{**payload, 'attachment_ids': tuple(identifiers)})


def task_has_saved_inputs(connection, task_id: str) -> bool:
    """Read one live Task incarnation, never a reused display ID or retired scope."""
    return connection.execute(
        'SELECT 1 FROM mentat_task_input_scopes s JOIN mentat_tasks t '
        'ON t.id=s.task_id AND t.input_incarnation=s.task_incarnation '
        'WHERE t.id=? AND s.retired_at IS NULL LIMIT 1', (task_id,),
    ).fetchone() is not None


def validate_selected_files(selection: TaskInputSelection | _RetainedSelection, metadata: object, *,
                            adapter_file_limit: int = MAX_INPUT_FILES,
                            adapter_image_limit: int = MAX_INPUT_IMAGES,
                            require_available: bool = True) -> None:
    """Reject whole selections outside fixed limits; this is not qualification.

    The caller supplies metadata from exact verified retained reads, in the
    selected order. This check cannot prove membership or content integrity and
    must never replace the storage/admission checks described above.
    """
    if (type(adapter_file_limit) is not int or not 0 <= adapter_file_limit <= MAX_INPUT_FILES
            or type(adapter_image_limit) is not int or not 0 <= adapter_image_limit <= MAX_INPUT_IMAGES):
        _fail('adapter_limits_invalid')
    if (not isinstance(metadata, (list, tuple)) or len(metadata) != len(selection.attachment_ids)
            or len(metadata) > adapter_file_limit):
        _fail('files_unavailable')
    images = 0
    for identifier, item in zip(selection.attachment_ids, metadata):
        if (not isinstance(item, dict) or item.get('id') != identifier
                or (item.get('state') != 'attached' and (require_available or item.get('state') != 'missing'))
                or not isinstance(item.get('kind'), str)
                or item['kind'] not in ('image', 'text')
                or type(item.get('byte_size')) is not int or item['byte_size'] < 0):
            _fail('files_unavailable')
        if item['kind'] == 'image':
            images += 1
            if (not isinstance(item.get('mime_type'), str)
                    or item['mime_type'] not in ('image/png','image/jpeg','image/webp','image/gif')
                    or item['byte_size'] > MAX_IMAGE_BYTES):
                _fail('files_unavailable')
        elif (not isinstance(item.get('mime_type'), str) or item['mime_type'] not in _TEXT_CONTENT_TYPES
              or item['byte_size'] > MAX_TEXT_BYTES):
            _fail('files_unavailable')
    if images > adapter_image_limit:
        _fail('image_limit')


def _encoded(value) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeError):
        _fail('invalid')


def _timestamp(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def validate_input_connection(connection, *, require_available=True) -> list[list]:
    """Validate retained input history; historical grants may be revoked/stale."""
    from task_repository import MAX_TASKS
    tasks = connection.execute('SELECT id,input_incarnation,project_id FROM mentat_tasks').fetchmany(MAX_TASKS + 1)
    if len(tasks) > MAX_TASKS:
        _fail('capacity')
    identities = {}
    for identifier, incarnation, project in tasks:
        if not isinstance(incarnation, str) or re.fullmatch(r'[0-9a-f]{32}', incarnation) is None:
            _fail('identity_invalid')
        identities[identifier] = (incarnation, project)
    scopes = connection.execute('SELECT id,task_id,task_incarnation,project_scope_id,revision,created_at,retired_at FROM mentat_task_input_scopes ORDER BY id').fetchmany(MAX_INPUT_VERSIONS + 1)
    versions = connection.execute('SELECT id,scope_id,revision,task_revision,agent_id,agent_incarnation,context_id,grant_revision,binding_digest,instructions,files_digest,created_at FROM mentat_task_input_versions ORDER BY scope_id,revision').fetchmany(MAX_INPUT_VERSIONS + 1)
    files = connection.execute('SELECT input_id,attachment_id,ordinal FROM mentat_task_input_files ORDER BY input_id,ordinal').fetchmany(MAX_INPUT_VERSIONS * MAX_INPUT_FILES + 1)
    if len(scopes) > MAX_INPUT_VERSIONS or len(versions) > MAX_INPUT_VERSIONS or len(files) > MAX_INPUT_VERSIONS * MAX_INPUT_FILES:
        _fail('capacity')
    project_scopes = {row[0]: (row[1], row[2]) for row in connection.execute('SELECT id,project_id,retired_at FROM mentat_project_context_scopes')}
    contexts = {row[0]: row[1] for row in connection.execute('SELECT id,scope_id FROM mentat_project_context_versions')}
    scope_map = {}
    for identifier, task, incarnation, project_scope, revision, created, retired in scopes:
        if (not isinstance(identifier, str) or re.fullmatch(r'task_input_scope_[0-9a-f]{32}', identifier) is None
                or not isinstance(task, str) or _TASK.fullmatch(task) is None
                or not isinstance(incarnation, str) or re.fullmatch(r'[0-9a-f]{32}', incarnation) is None
                or project_scope not in project_scopes or type(revision) is not int or not 1 <= revision <= MAX_REVISION
                or not _timestamp(created) or retired is not None and (not _timestamp(retired) or retired < created)):
            _fail('invalid')
        if retired is None and (identities.get(task) != (incarnation, project_scopes[project_scope][0]) or project_scopes[project_scope][1] is not None):
            _fail('identity_invalid')
        scope_map[identifier] = (project_scope, revision)
    revisions = {identifier: [] for identifier in scope_map}
    version_map = {}
    for row in versions:
        identifier, scope, revision, task_revision, agent, incarnation, context, grant_revision, binding, instructions, digest, created = row
        if (not isinstance(identifier, str) or re.fullmatch(r'task_input_[0-9a-f]{32}', identifier) is None
                or scope not in scope_map or contexts.get(context) != scope_map[scope][0]
                or any(type(value) is not int or not 1 <= value <= MAX_REVISION for value in (revision, task_revision, grant_revision))
                or not isinstance(agent, str) or _AGENT.fullmatch(agent) is None
                or not isinstance(incarnation, str) or re.fullmatch(r'[0-9a-f]{32}', incarnation) is None
                or any(not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None for value in (binding, digest))
                or not isinstance(instructions, str) or '\0' in instructions or not _timestamp(created)):
            _fail('invalid')
        try:
            if len(instructions.encode('utf-8')) > MAX_INSTRUCTION_BYTES:
                _fail('invalid')
        except UnicodeError:
            _fail('invalid')
        revisions[scope].append(revision)
        version_map[identifier] = (context, digest)
    for scope, values in revisions.items():
        if not values or len(values) > MAX_TASK_INPUT_VERSIONS or values[-1] != scope_map[scope][1]:
            _fail('invalid')
    selected = {identifier: [] for identifier in version_map}
    context_files = {(row[0], row[1]) for row in connection.execute('SELECT context_id,attachment_id FROM mentat_project_context_files')}
    for identifier, attachment, ordinal in files:
        if (identifier not in version_map or type(ordinal) is not int or ordinal != len(selected[identifier])
                or (version_map[identifier][0], attachment) not in context_files):
            _fail('files_invalid')
        selected[identifier].append(attachment)
    for identifier, attachments in selected.items():
        if len(attachments) > MAX_INPUT_FILES or hashlib.sha256(_encoded(attachments)).hexdigest() != version_map[identifier][1]:
            _fail('files_invalid')
        images = 0
        metadata = []
        for attachment in attachments:
            row = connection.execute('SELECT a.kind,a.mime_type,a.byte_size,a.state,b.state,b.byte_size FROM attachments a LEFT JOIN blobs b ON b.id=a.blob_id WHERE a.id=?', (attachment,)).fetchone()
            if row is None or row[2] != row[5] or (require_available and row[4] != 'ready'):
                _fail('files_unavailable')
            metadata.append({'id': attachment, 'kind': row[0], 'mime_type': row[1], 'byte_size': row[2], 'state': row[3]})
        validate_selected_files(_RetainedSelection(tuple(attachments)), metadata,
                                require_available=require_available)
    # Canonical Task creation is independent: reserve its entire bounded identity
    # occupancy rather than invalidating context quotas as more Tasks are added.
    charged_scopes = [list(row[:6]) + ['0' * 32] for row in scopes]
    return [charged_scopes, [list(row) for row in versions], [list(row) for row in files], [['x' * 160, '0' * 32] for _ in range(MAX_TASKS)]]


def publish_task_inputs(data_dir: Path, payload: object) -> dict:
    """Save a verified immutable input version, without approval or dispatch."""
    from agent_console_attachments import AttachmentError, read_attachment_bytes
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from project_context_access import _validated_context
    from task_repository import TaskRepository, _open_repository_database, _guarded_transaction
    selection = normalize_input_selection(payload)
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                validate_project_context_connection(connection, require_available=False)
                task = TaskRepository(connection).get(selection.task_id)
                if (task.revision != selection.expected_task_revision or task.document.get('project_id') != selection.project_id
                        or task.document.get('assigned_agent_id') != selection.agent_id):
                    _fail('task_changed')
                context, record, agent_identity, grant, allowed_files, _confirmation = _validated_context(connection, selection.project_id, selection.context_id, selection.agent_id)
                if not grant or grant[0] != agent_identity or grant[1] != selection.context_id or grant[2] != selection.expected_grant_revision or grant[3] != 'active':
                    _fail('grant_changed')
                if any(identifier not in allowed_files for identifier in selection.attachment_ids):
                    _fail('file_scope')
                metadata = []
                for identifier in selection.attachment_ids:
                    try:
                        item, _bytes = read_attachment_bytes(root, identifier)
                    except (AttachmentError, OSError):
                        _fail('files_unavailable')
                    metadata.append(item)
                validate_selected_files(selection, metadata)
                incarnation = connection.execute('SELECT input_incarnation FROM mentat_tasks WHERE id=?', (selection.task_id,)).fetchone()[0]
                if not hmac.compare_digest(selection.expected_task_token,
                                           _task_token(connection, selection.task_id, incarnation, task.revision, task.document)):
                    _fail('task_changed')
                scope = connection.execute('SELECT id,revision,task_incarnation,project_scope_id FROM mentat_task_input_scopes WHERE task_id=? AND retired_at IS NULL', (selection.task_id,)).fetchone()
                if (scope and (scope[2] != incarnation or scope[3] != context[0])) or selection.expected_input_revision != (scope[1] if scope else 0):
                    _fail('revision_conflict')
                now = time.time(); scope_id = scope[0] if scope else 'task_input_scope_' + uuid.uuid4().hex
                revision = selection.expected_input_revision + 1
                if revision > MAX_REVISION:
                    _fail('capacity')
                binding = connection.execute('SELECT * FROM agent_runtime_configs WHERE id=?', (record.agent.runtime_config_id,)).fetchone()
                if binding is None:
                    _fail('agent_unavailable')
                binding_digest = hashlib.sha256(_encoded([list(binding), record.revision, sorted(record.agent.capabilities)])).hexdigest()
                if scope:
                    connection.execute('UPDATE mentat_task_input_scopes SET revision=? WHERE id=?', (revision, scope_id))
                else:
                    connection.execute('INSERT INTO mentat_task_input_scopes VALUES(?,?,?,?,?,?,NULL)', (scope_id, selection.task_id, incarnation, context[0], revision, now))
                identifier = 'task_input_' + uuid.uuid4().hex
                connection.execute('INSERT INTO mentat_task_input_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', (identifier, scope_id, revision, task.revision, selection.agent_id, agent_identity, selection.context_id, selection.expected_grant_revision, binding_digest, selection.instructions, hashlib.sha256(_encoded(selection.attachment_ids)).hexdigest(), now))
                connection.executemany('INSERT INTO mentat_task_input_files VALUES(?,?,?)', [(identifier, attachment, ordinal) for ordinal, attachment in enumerate(selection.attachment_ids)])
                validate_project_context_connection(connection, require_available=False)
                return {'input_id': identifier, 'revision': revision}


def _version_projection(connection, identifier: str) -> dict:
    from project_context_editor import _file_metadata
    row = connection.execute(
        'SELECT id,revision,task_revision,agent_id,context_id,grant_revision,instructions,created_at '
        'FROM mentat_task_input_versions WHERE id=?', (identifier,)
    ).fetchone()
    if row is None:
        _fail('version_unavailable')
    context = connection.execute('SELECT revision,brief FROM mentat_project_context_versions WHERE id=?', (row[4],)).fetchone()
    if context is None:
        _fail('version_unavailable')
    files = [_file_metadata(connection, item[0]) for item in connection.execute(
        'SELECT attachment_id FROM mentat_task_input_files WHERE input_id=? ORDER BY ordinal', (identifier,)
    )]
    return {'id': row[0], 'revision': row[1], 'task_revision': row[2], 'agent_id': row[3],
            'context_id': row[4], 'grant_revision': row[5], 'instructions': row[6],
            'context_revision': context[0], 'project_brief': context[1],
            'created_at': row[7], 'files': files}


def _editor_snapshot(connection, task_id: str, version_id: str | None = None) -> dict:
    from project_context import validate_project_context_connection
    from project_context_editor import _version_detail
    from project_repository import ProjectRepository
    from task_repository import TaskRepository
    if not isinstance(task_id, str) or _TASK.fullmatch(task_id) is None:
        _fail('invalid')
    if version_id is not None and (not isinstance(version_id, str) or re.fullmatch(r'task_input_[0-9a-f]{32}', version_id) is None):
        _fail('invalid')
    validate_project_context_connection(connection, require_available=False)
    task = TaskRepository(connection).get(task_id)
    document = task.document
    incarnation = connection.execute('SELECT input_incarnation FROM mentat_tasks WHERE id=?', (task_id,)).fetchone()[0]
    task_token = _task_token(connection, task_id, incarnation, task.revision, document)
    scope = connection.execute('SELECT id,revision FROM mentat_task_input_scopes WHERE task_id=? AND task_incarnation=? AND retired_at IS NULL', (task_id, incarnation)).fetchone()
    rows = connection.execute(
        'SELECT id,revision,context_id,created_at FROM mentat_task_input_versions WHERE scope_id=? ORDER BY revision DESC',
        (scope[0],)
    ).fetchall() if scope else []
    versions = [{'id': row[0], 'revision': row[1], 'context_id': row[2], 'created_at': row[3]} for row in rows]
    selected = version_id if version_id is not None else (rows[0][0] if rows else None)
    if selected is not None and selected not in {row[0] for row in rows}:
        _fail('version_unavailable')
    current = _version_projection(connection, selected) if selected is not None else None
    agent_id = document.get('assigned_agent_id')
    project_id = document.get('project_id')
    project_status = ProjectRepository(connection).get(project_id).document['status'] if isinstance(project_id, str) else None
    eligible = []
    if isinstance(agent_id, str) and isinstance(project_id, str):
        agent = connection.execute('SELECT context_incarnation FROM mentat_agents WHERE id=?', (agent_id,)).fetchone()
        if agent:
            rows = connection.execute(
                "SELECT g.context_id,g.revision FROM mentat_project_context_grants g "
                "JOIN mentat_project_context_scopes s ON s.id=g.scope_id "
                "WHERE s.project_id=? AND s.retired_at IS NULL AND g.agent_id=? "
                "AND g.agent_incarnation=? AND g.state='active' ORDER BY g.context_id",
                (project_id, agent_id, agent[0]),
            ).fetchall()
            eligible = [{'context': _version_detail(connection, row[0]), 'grant_revision': row[1]} for row in rows]
    return {'task': {'id': task_id, 'title': document['title'], 'revision': task.revision,
                     'project_id': project_id, 'project_status': project_status,
                     'assigned_agent_id': agent_id},
            'input_revision': scope[1] if scope else 0, 'expected_task_token': task_token,
            'version': current,
            'versions': versions, 'eligible_contexts': eligible}


def read_task_input_editor(data_dir: Path, task_id: str, *, version_id: str | None = None) -> dict:
    """Safe owner view of one live Task incarnation; no private binding fields."""
    from private_state import private_state_lock
    from task_repository import _open_repository_database, _guarded_transaction
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                return _editor_snapshot(connection, task_id, version_id)


def _task_token(connection, identifier, incarnation, revision, document) -> str:
    secret = connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state WHERE singleton=1').fetchone()[0]
    return hmac.new(secret, _encoded([identifier, incarnation, revision,
        document.get('project_id'), document.get('assigned_agent_id')]), hashlib.sha256).hexdigest()


def read_retired_task_input_history(data_dir: Path) -> list[dict]:
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from task_repository import _open_repository_database, _guarded_transaction
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_project_context_connection(connection, require_available=False)
                rows = connection.execute(
                    'SELECT v.id,v.revision,v.created_at,v.instructions '
                    'FROM mentat_task_input_versions v JOIN mentat_task_input_scopes s ON s.id=v.scope_id '
                    'WHERE s.retired_at IS NOT NULL ORDER BY s.retired_at DESC,v.revision DESC LIMIT ?',
                    (MAX_INPUT_VERSIONS,),
                ).fetchall()
                return [{'id': row[0], 'revision': row[1], 'created_at': row[2],
                         'summary': ' '.join(row[3].split())[:120] or 'Saved Task input'} for row in rows]


def read_retired_task_input(data_dir: Path, input_id: str) -> dict:
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from task_repository import _open_repository_database, _guarded_transaction
    if not isinstance(input_id, str) or re.fullmatch(r'task_input_[0-9a-f]{32}', input_id) is None:
        _fail('invalid')
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_project_context_connection(connection, require_available=False)
                row = connection.execute('SELECT 1 FROM mentat_task_input_versions v JOIN mentat_task_input_scopes s ON s.id=v.scope_id WHERE v.id=? AND s.retired_at IS NOT NULL', (input_id,)).fetchone()
                if row is None:
                    _fail('version_unavailable')
                return _version_projection(connection, input_id)


def _prune_snapshot(connection, input_id: str):
    from project_context import validate_project_context_connection
    validate_project_context_connection(connection, require_available=False)
    row = connection.execute(
        'SELECT v.id,v.scope_id,v.revision,v.context_id,v.files_digest,s.revision,s.retired_at,'
        's.task_id,s.task_incarnation FROM mentat_task_input_versions v '
        'JOIN mentat_task_input_scopes s ON s.id=v.scope_id WHERE v.id=?', (input_id,)
    ).fetchone()
    if row is None:
        _fail('version_unavailable')
    if connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] >= 30:
        if connection.execute('SELECT 1 FROM mentat_run_input_receipts WHERE input_id=? LIMIT 1', (input_id,)).fetchone():
            _fail('retained_run')
    if connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] >= 33:
        if connection.execute('SELECT 1 FROM mentat_plan_input_refs WHERE input_id=? LIMIT 1', (input_id,)).fetchone():
            _fail('retained_plan')
    if row[6] is None and row[2] == row[5]:
        _fail('current_version')
    files = tuple(item[0] for item in connection.execute(
        'SELECT attachment_id FROM mentat_task_input_files WHERE input_id=? ORDER BY ordinal', (input_id,)
    ))
    references = []
    for identifier in files:
        references.append([identifier,
            [tuple(item) for item in connection.execute('SELECT run_id,direction,ordinal FROM run_attachments WHERE attachment_id=? ORDER BY run_id,direction', (identifier,))],
            [item[0] for item in connection.execute('SELECT context_id FROM mentat_project_context_files WHERE attachment_id=? ORDER BY context_id', (identifier,))],
            [item[0] for item in connection.execute('SELECT input_id FROM mentat_task_input_files WHERE attachment_id=? ORDER BY input_id', (identifier,))]])
    epoch = connection.execute('SELECT approval_epoch FROM mentat_project_context_access_state WHERE singleton=1').fetchone()[0]
    live = connection.execute('SELECT revision FROM mentat_tasks WHERE id=? AND input_incarnation=?', (row[7], row[8])).fetchone()
    claims = ['task-input-prune-v1', list(row), live[0] if live else None, references]
    token = hmac.new(epoch, _encoded(claims), hashlib.sha256).hexdigest()
    return row, files, token


def preview_task_input_prune(data_dir: Path, input_id: str) -> dict:
    from private_state import private_state_lock
    from task_repository import _open_repository_database, _guarded_transaction
    if not isinstance(input_id, str) or re.fullmatch(r'task_input_[0-9a-f]{32}', input_id) is None:
        _fail('invalid')
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                row, files, token = _prune_snapshot(connection, input_id)
                return {'input_id': input_id, 'revision': row[2], 'file_count': len(files), 'confirmation_id': token}


def confirm_task_input_prune(data_dir: Path, input_id: str, *, confirmation_id: str) -> None:
    from agent_console_attachments import DEFAULT_ORPHAN_GRACE
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from task_repository import _open_repository_database, _guarded_transaction
    if not isinstance(input_id, str) or re.fullmatch(r'task_input_[0-9a-f]{32}', input_id) is None or not isinstance(confirmation_id, str) or re.fullmatch(r'[0-9a-f]{64}', confirmation_id) is None:
        _fail('invalid')
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                row, files, expected = _prune_snapshot(connection, input_id)
                if not hmac.compare_digest(confirmation_id, expected):
                    _fail('stale')
                connection.execute('DELETE FROM mentat_task_input_files WHERE input_id=?', (input_id,))
                connection.execute('DELETE FROM mentat_task_input_versions WHERE id=?', (input_id,))
                if row[6] is not None:
                    remaining = connection.execute('SELECT MAX(revision) FROM mentat_task_input_versions WHERE scope_id=?', (row[1],)).fetchone()[0]
                    if remaining is None:
                        connection.execute('DELETE FROM mentat_task_input_scopes WHERE id=?', (row[1],))
                    else:
                        connection.execute('UPDATE mentat_task_input_scopes SET revision=? WHERE id=?', (remaining, row[1]))
                for identifier in files:
                    connection.execute(
                        "UPDATE attachments SET state='orphaned',expires_at=NULL,delete_after=?,updated_at=? WHERE id=? "
                        'AND NOT EXISTS(SELECT 1 FROM mentat_retained_attachments WHERE attachment_id=?)',
                        (time.time() + DEFAULT_ORPHAN_GRACE, time.time(), identifier, identifier),
                    )
                validate_project_context_connection(connection, require_available=False)
