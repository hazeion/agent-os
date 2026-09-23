"""Bounded owner Task-input selections; normalization grants no execution rights.

Storage/admission must additionally resolve exact live incarnations, membership,
grants, verified bytes and qualified runtime policy under the private root lock.
This module never resolves a browser-selected path or calls a runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from agent_console_attachments import MAX_IMAGE_BYTES, MAX_TEXT_BYTES

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
                     'instructions', 'attachment_ids'})


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
    instructions: str
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


def validate_selected_files(selection: TaskInputSelection, metadata: object, *,
                            adapter_file_limit: int = MAX_INPUT_FILES,
                            adapter_image_limit: int = MAX_INPUT_IMAGES) -> None:
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
                or item.get('state') != 'attached' or not isinstance(item.get('kind'), str)
                or item['kind'] not in ('image', 'text')
                or type(item.get('byte_size')) is not int or item['byte_size'] < 0):
            _fail('files_unavailable')
        if item['kind'] == 'image':
            images += 1
            if (not isinstance(item.get('mime_type'), str)
                    or item['mime_type'] not in ('image/png','image/jpeg','image/webp','image/gif')
                    or item['byte_size'] > MAX_IMAGE_BYTES):
                _fail('files_unavailable')
        elif item['byte_size'] > MAX_TEXT_BYTES:
            _fail('files_unavailable')
    if images > adapter_image_limit:
        _fail('image_limit')
