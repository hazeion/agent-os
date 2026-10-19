"""Named owner-only Python bridge for preparing Task inputs; no dispatch."""
from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from agent_registry import AgentRegistryError
from project_context import ProjectContextError
from project_context_access import ProjectContextAccessError
from project_repository import ProjectRepositoryError
from task_repository import TaskRepositoryError
from task_inputs import (
    TaskInputError, normalize_input_selection, publish_task_inputs,
    read_task_input_editor, read_retired_task_input_history, read_retired_task_input,
    preview_task_input_prune, confirm_task_input_prune,
)

READ_OPERATIONS = frozenset({'task', 'version', 'retired-history', 'retired-version'})
WRITE_OPERATIONS = frozenset({'publish', 'prune-preview', 'prune-confirm'})
MAX_ACTION_BYTES = 128 * 1024
_TASK = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z')
_VERSION = re.compile(r'task_input_[0-9a-f]{32}\Z')
_SAFE_ERRORS = frozenset({'invalid', 'revision_invalid', 'instructions_invalid', 'files_invalid',
    'task_changed', 'grant_changed', 'file_scope', 'files_unavailable', 'revision_conflict',
    'capacity', 'image_limit', 'version_unavailable', 'adapter_limits_invalid',
    'project_unavailable', 'context_unavailable', 'agent_unavailable', 'file_unavailable',
    'current_version', 'stale'})


def _failure(status: str, code: int) -> tuple[dict, int]:
    return {'schema_version': 1, 'status': status}, code


def dispatch_task_inputs(data_dir: Path, operation: str, body: object) -> tuple[dict, int]:
    if operation not in READ_OPERATIONS | WRITE_OPERATIONS or not isinstance(body, dict):
        return _failure('invalid', 400)
    if operation == 'task' and (set(body) != {'task_id'} or not isinstance(body['task_id'], str) or _TASK.fullmatch(body['task_id']) is None):
        return _failure('invalid', 400)
    if operation == 'version' and (set(body) != {'task_id', 'input_id'} or not isinstance(body['task_id'], str)
            or not isinstance(body['input_id'], str) or _TASK.fullmatch(body['task_id']) is None
            or _VERSION.fullmatch(body['input_id']) is None):
        return _failure('invalid', 400)
    if operation == 'publish':
        try:
            normalize_input_selection(body)
        except TaskInputError:
            return _failure('invalid', 400)
    if operation == 'retired-history' and body:
        return _failure('invalid', 400)
    if operation in {'retired-version', 'prune-preview'} and (set(body) != {'input_id'}
            or not isinstance(body['input_id'], str) or _VERSION.fullmatch(body['input_id']) is None):
        return _failure('invalid', 400)
    if operation == 'prune-confirm' and (set(body) != {'input_id', 'confirmation_id', 'confirmed'}
            or not isinstance(body['input_id'], str) or _VERSION.fullmatch(body['input_id']) is None
            or not isinstance(body['confirmation_id'], str) or re.fullmatch(r'[0-9a-f]{64}', body['confirmation_id']) is None
            or body['confirmed'] is not True):
        return _failure('invalid', 400)
    try:
        if operation == 'task':
            data = read_task_input_editor(data_dir, body['task_id'])
        elif operation == 'version':
            data = read_task_input_editor(data_dir, body['task_id'], version_id=body['input_id'])
        elif operation == 'retired-history':
            data = {'versions': read_retired_task_input_history(data_dir)}
        elif operation == 'retired-version':
            data = read_retired_task_input(data_dir, body['input_id'])
        elif operation == 'prune-preview':
            data = preview_task_input_prune(data_dir, body['input_id'])
        elif operation == 'prune-confirm':
            confirm_task_input_prune(data_dir, body['input_id'], confirmation_id=body['confirmation_id'])
            data = {'pruned': True}
        else:
            data = publish_task_inputs(data_dir, body)
        return {'schema_version': 1, 'service': 'mentat-local-bridge', 'runtime': 'python', 'status': 'ready', 'data': data}, 200
    except TaskInputError as exc:
        code = str(exc).rsplit('.', 1)[-1]
        return _failure(code if code in _SAFE_ERRORS else 'unavailable', 409)
    except ProjectContextAccessError as exc:
        code = str(exc).rsplit('.', 1)[-1]
        return _failure(code, 409) if code in _SAFE_ERRORS else _failure('unavailable', 503)
    except (ProjectContextError, AgentRegistryError, TaskRepositoryError, ProjectRepositoryError, sqlite3.Error, OSError):
        return _failure('unavailable', 503)
