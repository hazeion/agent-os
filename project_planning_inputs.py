"""Validate retained owner-prepared Project planning inputs, without Run authority."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3

from agent_console_attachments import MAX_IMAGE_BYTES, MAX_TEXT_BYTES, _TEXT_CONTENT_TYPES


MAX_PROJECT_INPUT_VERSIONS = 256
MAX_PROJECT_INPUT_VERSIONS_PER_INCARNATION = 32
MAX_PROJECT_INPUT_FILES = 8
MAX_PROJECT_INPUT_IMAGES = 1
MAX_PROJECT_INPUT_INSTRUCTION_BYTES = 16 * 1024
MAX_REVISION = 9007199254740991
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_INPUT = re.compile(r"project_input_[0-9a-f]{32}\Z")
_INCARNATION = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class ProjectPlanningInputError(RuntimeError):
    """A fixed failure that never discloses retained private input content."""


def _fail(code: str) -> None:
    raise ProjectPlanningInputError(f"project_input.{code}")


def _encoded(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _fail("invalid")


def _timestamp(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def validate_project_planning_input_connection(
    connection: sqlite3.Connection, *, require_available: bool = True,
) -> list[list]:
    """Validate the bounded immutable history, including restore snapshots.

    This proves historical identity and file-graph integrity. It does not
    qualify a runtime, check current grants, or authorize proposal admission.
    """
    versions = connection.execute(
        "SELECT id,project_id,project_incarnation,revision,project_revision,"
        "lead_role_id,lead_revision,agent_id,agent_incarnation,agent_revision,"
        "binding_digest,context_id,grant_revision,instructions,files_digest,created_at "
        "FROM mentat_project_planning_input_versions ORDER BY project_incarnation,revision"
    ).fetchmany(MAX_PROJECT_INPUT_VERSIONS + 1)
    files = connection.execute(
        "SELECT input_id,ordinal,attachment_id,blob_id,sha256,byte_size,kind,mime_type "
        "FROM mentat_project_planning_input_files ORDER BY input_id,ordinal"
    ).fetchmany(MAX_PROJECT_INPUT_VERSIONS * MAX_PROJECT_INPUT_FILES + 1)
    if (len(versions) > MAX_PROJECT_INPUT_VERSIONS or
            len(files) > MAX_PROJECT_INPUT_VERSIONS * MAX_PROJECT_INPUT_FILES):
        _fail("capacity")

    roles = {row[0]: tuple(row) for row in connection.execute(
        "SELECT id,project_id,project_incarnation,revision,action,agent_id,"
        "agent_incarnation,agent_revision,binding_digest,context_id,grant_revision,created_at "
        "FROM mentat_project_lead_versions"
    )}
    contexts = {row[0]: tuple(row[1:]) for row in connection.execute(
        "SELECT v.id,s.project_id,s.created_at,s.retired_at,v.created_at "
        "FROM mentat_project_context_versions v "
        "JOIN mentat_project_context_scopes s ON s.id=v.scope_id"
    )}
    context_files = {(row[0], row[1]) for row in connection.execute(
        "SELECT context_id,attachment_id FROM mentat_project_context_files"
    )}
    live_incarnations = {row[1]: row[0] for row in connection.execute(
        "SELECT id,deliverable_incarnation FROM mentat_projects"
    )}
    revisions: dict[str, list[int]] = {}
    retained: dict[str, tuple[str, str]] = {}
    for row in versions:
        (identifier, project_id, incarnation, revision, project_revision,
         role_id, lead_revision, agent_id, agent_incarnation, agent_revision,
         binding, context_id, grant_revision, instructions, digest, created_at) = tuple(row)
        role = roles.get(role_id)
        context_scope = contexts.get(context_id)
        if (not isinstance(identifier, str) or _INPUT.fullmatch(identifier) is None
                or not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None
                or not isinstance(incarnation, str) or _INCARNATION.fullmatch(incarnation) is None
                or live_incarnations.get(incarnation, project_id) != project_id
                or any(type(value) is not int or not 1 <= value <= MAX_REVISION
                       for value in (revision, project_revision, lead_revision,
                                     agent_revision, grant_revision))
                or revision > MAX_PROJECT_INPUT_VERSIONS_PER_INCARNATION
                or not isinstance(agent_id, str) or _AGENT.fullmatch(agent_id) is None
                or not isinstance(agent_incarnation, str)
                or _INCARNATION.fullmatch(agent_incarnation) is None
                or not isinstance(binding, str) or _HEX64.fullmatch(binding) is None
                or not isinstance(digest, str) or _HEX64.fullmatch(digest) is None
                or not isinstance(instructions, str) or "\0" in instructions
                or not _timestamp(created_at)
                or context_scope is None or context_scope[0] != project_id
                or not _timestamp(context_scope[1]) or context_scope[1] > created_at
                or (context_scope[2] is not None and context_scope[2] < created_at)
                or not _timestamp(context_scope[3]) or context_scope[3] > created_at
                or role is None or role[1:5] != (project_id, incarnation, lead_revision, "select")
                or role[5:11] != (agent_id, agent_incarnation, agent_revision,
                                  binding, context_id, grant_revision)
                or not _timestamp(role[11]) or role[11] > created_at
                or context_scope[3] > role[11]):
            _fail("invalid")
        try:
            if len(instructions.encode("utf-8")) > MAX_PROJECT_INPUT_INSTRUCTION_BYTES:
                _fail("invalid")
        except UnicodeError:
            _fail("invalid")
        revisions.setdefault(incarnation, []).append(revision)
        retained[identifier] = (context_id, digest)
    if any(values != list(range(1, len(values) + 1)) or
           len(values) > MAX_PROJECT_INPUT_VERSIONS_PER_INCARNATION
           for values in revisions.values()):
        _fail("invalid")

    selected: dict[str, list[list]] = {identifier: [] for identifier in retained}
    image_counts: dict[str, int] = {identifier: 0 for identifier in retained}
    for row in files:
        input_id, ordinal, attachment_id, blob_id, sha256, byte_size, kind, mime_type = tuple(row)
        if (input_id not in retained or type(ordinal) is not int
                or ordinal != len(selected[input_id]) or ordinal >= MAX_PROJECT_INPUT_FILES
                or (retained[input_id][0], attachment_id) not in context_files
                or not isinstance(sha256, str) or _HEX64.fullmatch(sha256) is None
                or type(byte_size) is not int or byte_size < 0
                or kind not in ("image", "text") or not isinstance(mime_type, str)):
            _fail("files_invalid")
        metadata = connection.execute(
            "SELECT a.blob_id,a.byte_size,a.kind,a.mime_type,a.state,"
            "b.sha256,b.byte_size,b.state FROM attachments a "
            "LEFT JOIN blobs b ON b.id=a.blob_id WHERE a.id=?", (attachment_id,),
        ).fetchone()
        if (metadata is None or tuple(metadata[:4]) != (blob_id, byte_size, kind, mime_type)
                or metadata[5] != sha256 or metadata[6] != byte_size
                or metadata[4] not in ({"attached"} if require_available else {"attached", "missing"})
                or require_available and metadata[7] != "ready"):
            _fail("files_unavailable")
        if kind == "image":
            image_counts[input_id] += 1
            if (image_counts[input_id] > MAX_PROJECT_INPUT_IMAGES
                    or mime_type not in ("image/png", "image/jpeg", "image/webp", "image/gif")
                    or byte_size > MAX_IMAGE_BYTES):
                _fail("files_invalid")
        elif mime_type not in _TEXT_CONTENT_TYPES or byte_size > MAX_TEXT_BYTES:
            _fail("files_invalid")
        selected[input_id].append([attachment_id, blob_id, sha256, byte_size,
                                   kind, mime_type])
    for identifier, entries in selected.items():
        if hashlib.sha256(_encoded(entries)).hexdigest() != retained[identifier][1]:
            _fail("files_invalid")
    return [[list(row) for row in versions], [list(row) for row in files]]
