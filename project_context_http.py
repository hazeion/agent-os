"""Fixed private bridge capabilities for owner Project context controls."""
from __future__ import annotations

import base64
import binascii
from pathlib import Path
import re
import sqlite3

from agent_console_attachments import AttachmentError, MAX_IMAGE_BYTES
from project_repository import ProjectRepositoryError
from task_repository import TaskRepositoryError
import project_context as context
import project_context_access as access
import project_context_editor as editor

READ_OPERATIONS = frozenset({'project','version','history','file'})
WRITE_OPERATIONS = frozenset({'publish','upload','discard','grant-preview','grant-confirm','revoke','prune-preview','prune-confirm'})
MAX_UPLOAD_JSON_BYTES = 14 * 1024 * 1024
_FIELDS = {
    'project': {'project_id'}, 'version': {'context_id'}, 'history': set(),
    'publish': {'project_id','expected_project_revision','expected_revision','brief','attachment_ids','expected_staged_ids'},
    'upload': {'project_id','expected_project_revision','name','content_type','content_base64'},
    'discard': {'project_id','expected_project_revision','attachment_id'},
    'grant-preview': {'project_id','context_id','agent_id'},
    'grant-confirm': {'project_id','context_id','agent_id','confirmation_id','confirmed'},
    'revoke': {'project_id','context_id','agent_id','expected_revision'},
    'prune-preview': {'context_id'}, 'prune-confirm': {'context_id','confirmation_id','confirmed'},
}
_IDS = {'project_id': r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}', 'agent_id': r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}',
        'context_id': r'project_context_[0-9a-f]{32}', 'attachment_id': r'attachment_[0-9a-f]{32}'}


def _failure(code, status):
    return {'schema_version': 1, 'status': code}, status


def dispatch_project_context(data_dir: Path, operation: str, body: object) -> tuple[dict, int]:
    if operation not in READ_OPERATIONS | WRITE_OPERATIONS or not isinstance(body, dict):
        return _failure('invalid', 400)
    fields = set(body)
    if operation == 'file':
        if fields not in ({'project_id','attachment_id'}, {'context_id','attachment_id'}):
            return _failure('invalid', 400)
    elif fields != _FIELDS[operation]:
        return _failure('invalid', 400)
    for key, value in body.items():
        if key in {'attachment_ids','expected_staged_ids'} and (
            not isinstance(value, list) or len(value) > context.MAX_FILES
            or any(not isinstance(item, str) or re.fullmatch(_IDS['attachment_id'], item) is None for item in value)
            or len(set(value)) != len(value)
        ):
            return _failure('invalid', 400)
        if key in _IDS and (not isinstance(value, str) or re.fullmatch(_IDS[key], value) is None):
            return _failure('invalid', 400)
        if key.startswith('expected_') and key != 'expected_staged_ids' and (type(value) is not int or not 0 <= value <= access.MAX_GRANT_REVISION):
            return _failure('invalid', 400)
        if key == 'confirmed' and value is not True:
            return _failure('invalid', 400)
    try:
        if operation == 'project':
            data = editor.read_project_editor(data_dir, **body)
        elif operation == 'version':
            data = editor.read_context_version(data_dir, **body)
        elif operation == 'history':
            data = {'versions': editor.read_retired_context_history(data_dir)}
        elif operation == 'file':
            metadata, content = editor.read_project_file(data_dir, **body)
            data = {'file': {**metadata, 'available': True}, 'content_base64': base64.b64encode(content).decode('ascii')}
        elif operation == 'publish':
            result = context.publish_project_context(data_dir, **body)
            data = {'context_id': result['id'], 'revision': result['revision']}
        elif operation == 'upload':
            encoded = body['content_base64']
            if (not isinstance(encoded, str) or len(encoded) > ((MAX_IMAGE_BYTES + 2)//3)*4
                    or not isinstance(body['name'], str) or len(body['name']) > 240
                    or not isinstance(body['content_type'], str) or len(body['content_type']) > 128):
                return _failure('invalid', 400)
            content = base64.b64decode(encoded, validate=True)
            if len(content) > MAX_IMAGE_BYTES or base64.b64encode(content).decode('ascii') != encoded:
                return _failure('invalid', 400)
            metadata = editor.stage_project_file(data_dir, body['project_id'], expected_project_revision=body['expected_project_revision'],
                original_name=body['name'], content=content, content_type=body['content_type'])
            data = {'file': {**metadata, 'available': True}}
        elif operation == 'discard':
            editor.discard_project_file(data_dir, **body)
            data = {'discarded': True}
        elif operation == 'grant-preview':
            data = access.preview_context_grant(data_dir, **body)
            data['files'] = [{**file, 'available': True} for file in data['files']]
        elif operation == 'grant-confirm':
            data = access.confirm_context_grant(data_dir, **{key: value for key,value in body.items() if key != 'confirmed'})
        elif operation == 'revoke':
            data = access.revoke_context_grant(data_dir, **body)
        elif operation == 'prune-preview':
            data = editor.preview_context_prune(data_dir, **body)
        else:
            editor.confirm_context_prune(data_dir, **{key: value for key,value in body.items() if key != 'confirmed'})
            data = {'pruned': True}
        return {'schema_version': 1, 'service': 'mentat-local-bridge', 'runtime': 'python', 'status': 'ready', 'data': data}, 200
    except (binascii.Error, ValueError, TypeError):
        return _failure('invalid', 400)
    except AttachmentError:
        return _failure('file_unavailable', 409)
    except (context.ProjectContextError, access.ProjectContextAccessError, editor.ProjectContextEditorError) as exc:
        reason = str(exc).rsplit('.', 1)[-1]
        allowed = {'stale','project_changed','project_unavailable','context_unavailable','agent_unavailable','file_unavailable',
                   'version_unavailable','current_version','granted_version','capacity','blob_capacity','staging_changed','revision_conflict',
                   'file_scope','files_invalid','brief_invalid','revision_invalid','confirmation_invalid','task_input'}
        return _failure(reason if reason in allowed else 'unavailable', 409)
    except (TaskRepositoryError, ProjectRepositoryError, OSError, sqlite3.Error):
        return _failure('unavailable', 503)
