"""Validate retained owner-prepared Project planning inputs, without Run authority."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

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
_ACTION = re.compile(r"project_input_action_[0-9a-f]{32}\Z")
_CONTEXT = re.compile(r"project_context_[0-9a-f]{32}\Z")
_ATTACHMENT = re.compile(r"attachment_[0-9a-f]{32}\Z")
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
    retained: dict[str, tuple[str, str, float]] = {}
    version_rows: dict[str, tuple] = {}
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
        retained[identifier] = (context_id, digest, created_at)
        version_rows[identifier] = tuple(row)
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
    metadata = [[list(row) for row in versions], [list(row) for row in files]]
    schema_version = connection.execute(
        "SELECT MAX(version) FROM schema_migrations"
    ).fetchone()[0]
    if schema_version >= 40:
        migration = connection.execute(
            "SELECT applied_at FROM schema_migrations WHERE version=40"
        ).fetchone()
        if (migration is None or
                not (_timestamp(migration[0]) or type(migration[0]) in (int, float) and migration[0] == 0)):
            _fail("invalid")
        cutoff = migration[0]
        if cutoff == 0 and retained:
            _fail("invalid")
        legacy_rows = connection.execute(
            "SELECT input_id FROM mentat_project_planning_input_legacy ORDER BY input_id"
        ).fetchmany(MAX_PROJECT_INPUT_VERSIONS + 1)
        if len(legacy_rows) > MAX_PROJECT_INPUT_VERSIONS:
            _fail("capacity")
        legacy_ids = {row[0] for row in legacy_rows}
        if len(legacy_ids) != len(legacy_rows) or not legacy_ids.issubset(retained):
            _fail("invalid")
        actions = connection.execute(
            "SELECT action_id,input_id,scope_token,selection_token,"
            "request_digest,source_kind,created_at "
            "FROM mentat_project_planning_input_actions ORDER BY action_id"
        ).fetchmany(MAX_PROJECT_INPUT_VERSIONS + 1)
        if len(actions) > MAX_PROJECT_INPUT_VERSIONS:
            _fail("capacity")
        seen_inputs: set[str] = set()
        for action_id, input_id, scope_token, selection_token, request_digest, source_kind, created_at in actions:
            if (not isinstance(action_id, str) or _ACTION.fullmatch(action_id) is None
                    or input_id not in retained or input_id in seen_inputs
                    or not isinstance(scope_token, str) or _HEX64.fullmatch(scope_token) is None
                    or not isinstance(selection_token, str) or _HEX64.fullmatch(selection_token) is None
                    or not isinstance(request_digest, str)
                    or _HEX64.fullmatch(request_digest) is None
                    or not _timestamp(created_at)
                    or created_at < retained[input_id][2]):
                _fail("invalid")
            seen_inputs.add(input_id)
            version = version_rows[input_id]
            if source_kind == "legacy":
                if (input_id not in legacy_ids
                        or version[15] > cutoff
                        or action_id != "project_input_action_" + input_id[14:]
                        or scope_token != "0" * 64 or selection_token != "0" * 64
                        or request_digest != version[14] or created_at != version[15]):
                    _fail("invalid")
            elif source_kind == "owner":
                if input_id in legacy_ids or version[15] < cutoff:
                    _fail("invalid")
                claims = [action_id, version[1], version[4], version[5], version[6],
                          version[11], version[12], version[3] - 1,
                          scope_token, selection_token, version[13],
                          [entry[0] for entry in selected[input_id]]]
                if hashlib.sha256(_encoded(claims)).hexdigest() != request_digest:
                    _fail("invalid")
            else:
                _fail("invalid")
        if seen_inputs != set(retained):
            _fail("invalid")
        metadata.extend([[list(row) for row in legacy_rows], [list(row) for row in actions]])
    return metadata


_SAVE_FIELDS = frozenset({
    "project_id", "expected_project_revision", "lead_role_id",
    "expected_lead_revision", "context_id", "expected_grant_revision",
    "expected_input_revision", "scope_token", "selection_token", "action_id",
    "instructions", "attachment_ids",
})


def normalize_project_input_request(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _SAVE_FIELDS:
        _fail("request_invalid")
    for key, pattern in (("project_id", _PROJECT), ("lead_role_id", re.compile(r"lead_role_[0-9a-f]{32}\Z")),
                         ("context_id", _CONTEXT), ("action_id", _ACTION)):
        if not isinstance(value[key], str) or pattern.fullmatch(value[key]) is None:
            _fail("request_invalid")
    for key in ("scope_token", "selection_token"):
        if not isinstance(value[key], str) or _HEX64.fullmatch(value[key]) is None:
            _fail("request_invalid")
    for key in ("expected_project_revision", "expected_lead_revision",
                "expected_grant_revision", "expected_input_revision"):
        minimum = 0 if key == "expected_input_revision" else 1
        maximum = MAX_PROJECT_INPUT_VERSIONS_PER_INCARNATION if key in (
            "expected_lead_revision", "expected_input_revision") else MAX_REVISION
        if type(value[key]) is not int or not minimum <= value[key] <= maximum:
            _fail("request_invalid")
    instructions = value["instructions"]
    if not isinstance(instructions, str) or "\0" in instructions:
        _fail("request_invalid")
    try:
        if len(instructions.encode("utf-8")) > MAX_PROJECT_INPUT_INSTRUCTION_BYTES:
            _fail("request_invalid")
    except UnicodeError:
        _fail("request_invalid")
    files = value["attachment_ids"]
    if (not isinstance(files, list) or len(files) > MAX_PROJECT_INPUT_FILES
            or any(not isinstance(item, str) or _ATTACHMENT.fullmatch(item) is None
                   for item in files) or len(set(files)) != len(files)):
        _fail("request_invalid")
    return value


def _owner_epoch(connection: sqlite3.Connection) -> bytes:
    row = connection.execute(
        "SELECT approval_epoch FROM mentat_project_context_access_state WHERE singleton=1"
    ).fetchone()
    if row is None or not isinstance(row[0], bytes) or len(row[0]) != 32:
        _fail("unavailable")
    return row[0]


def _scope_token(connection: sqlite3.Connection, project_id: str, incarnation: str) -> str:
    return hmac.new(_owner_epoch(connection), b"mentat-project-input-scope-v1\0" +
                    _encoded([project_id, incarnation]), hashlib.sha256).hexdigest()


def _input_head(connection: sqlite3.Connection, incarnation: str) -> tuple[int, str | None]:
    row = connection.execute(
        "SELECT revision,id FROM mentat_project_planning_input_versions "
        "WHERE project_incarnation=? ORDER BY revision DESC LIMIT 1", (incarnation,),
    ).fetchone()
    return (row[0], row[1]) if row else (0, None)


def _selection_state(connection: sqlite3.Connection, project_id: str) -> tuple:
    from project_leads import _current_context, _projection
    from project_repository import ProjectRepository
    project = ProjectRepository(connection).get(project_id)
    row = connection.execute(
        "SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (project_id,),
    ).fetchone()
    if row is None or not isinstance(row[0], str) or _INCARNATION.fullmatch(row[0]) is None:
        _fail("project_changed")
    incarnation = row[0]
    lead_view = _projection(connection, project_id, project, incarnation)
    role = connection.execute(
        "SELECT id,revision,agent_id,agent_incarnation,agent_revision,binding_digest,"
        "context_id,grant_revision FROM mentat_project_lead_versions "
        "WHERE project_id=? AND project_incarnation=? ORDER BY revision DESC LIMIT 1",
        (project_id, incarnation),
    ).fetchone()
    current_context = _current_context(connection, project_id)
    head_revision, head_id = _input_head(connection, incarnation)
    scope = _scope_token(connection, project_id, incarnation)
    claims = [project_id, incarnation, project.revision, project.document["status"],
              list(role) if role else None, lead_view["status"],
              list(current_context) if current_context else None,
              head_revision, head_id]
    selection = hmac.new(_owner_epoch(connection), b"mentat-project-input-save-v1\0" +
                         _encoded(claims), hashlib.sha256).hexdigest()
    return project, incarnation, lead_view, role, current_context, head_revision, scope, selection


def _version_detail(connection: sqlite3.Connection, identifier: str) -> dict:
    from project_context_editor import _file_metadata
    row = connection.execute(
        "SELECT id,revision,project_revision,lead_role_id,agent_id,context_id,"
        "grant_revision,instructions,created_at FROM mentat_project_planning_input_versions WHERE id=?",
        (identifier,),
    ).fetchone()
    if row is None:
        _fail("version_unavailable")
    context = connection.execute(
        "SELECT revision,brief FROM mentat_project_context_versions WHERE id=?", (row[5],),
    ).fetchone()
    if context is None:
        _fail("version_unavailable")
    files = [_file_metadata(connection, item[0]) for item in connection.execute(
        "SELECT attachment_id FROM mentat_project_planning_input_files "
        "WHERE input_id=? ORDER BY ordinal", (identifier,),
    )]
    return {"id": row[0], "revision": row[1], "project_revision": row[2],
            "lead_role_id": row[3], "agent_id": row[4], "context_id": row[5],
            "context_revision": context[0], "project_brief": context[1],
            "grant_revision": row[6], "instructions": row[7], "created_at": row[8],
            "files": files}


def _editor_snapshot(connection: sqlite3.Connection, project_id: str,
                     version_id: str | None = None) -> dict:
    from project_context_editor import _version_detail as context_detail
    from project_context import validate_project_context_connection
    if (not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None
            or version_id is not None and (not isinstance(version_id, str)
                or _INPUT.fullmatch(version_id) is None)):
        _fail("request_invalid")
    validate_project_context_connection(connection, require_available=False)
    (project, incarnation, lead, role, current_context, revision,
     scope_token, selection_token) = _selection_state(connection, project_id)
    versions = [{"id": row[0], "revision": row[1], "context_id": row[2],
                 "created_at": row[3]} for row in connection.execute(
        "SELECT id,revision,context_id,created_at FROM mentat_project_planning_input_versions "
        "WHERE project_incarnation=? ORDER BY revision DESC", (incarnation,),
    )]
    selected = version_id if version_id is not None else (versions[0]["id"] if versions else None)
    if selected is not None and selected not in {item["id"] for item in versions}:
        _fail("version_unavailable")
    current = context_detail(connection, current_context[1]) if current_context else None
    ready = (project.document["status"] == "active" and lead["status"] == "context_bound"
             and role is not None and current_context is not None
             and role[6] == current_context[1]
             and revision < MAX_PROJECT_INPUT_VERSIONS_PER_INCARNATION
             and connection.execute("SELECT COUNT(*) FROM mentat_project_planning_input_versions").fetchone()[0]
             < MAX_PROJECT_INPUT_VERSIONS)
    return {"project": {"id": project_id, "name": project.document["name"],
                        "revision": project.revision, "status": project.document["status"]},
            "lead": {key: lead[key] for key in ("id", "revision", "agent_id", "agent_name",
                                                  "status", "reasons")},
            "context": current, "grant_revision": role[7] if ready else None,
            "input_revision": revision, "scope_token": scope_token,
            "selection_token": selection_token, "save_available": bool(ready),
            "version": _version_detail(connection, selected) if selected else None,
            "versions": versions}


def read_project_input_editor(data_dir: Path, project_id: str, *,
                              version_id: str | None = None) -> dict:
    from private_state import private_state_lock
    from task_repository import _guarded_transaction, _open_repository_database
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                return _editor_snapshot(connection, project_id, version_id)


def publish_project_input(data_dir: Path, payload: object) -> dict:
    """Save one exact owner input and action receipt; never dispatch work."""
    from agent_console_attachments import AttachmentError, read_attachment_bytes
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from task_repository import _guarded_transaction, _open_repository_database
    value = normalize_project_input_request(payload)
    digest = hashlib.sha256(_encoded([
        value[key] for key in ("action_id", "project_id", "expected_project_revision", "lead_role_id",
                             "expected_lead_revision", "context_id", "expected_grant_revision",
                             "expected_input_revision", "scope_token", "selection_token",
                             "instructions", "attachment_ids")
    ])).hexdigest()
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                validate_project_context_connection(connection, require_available=False)
                prior = connection.execute(
                    "SELECT a.input_id,a.request_digest,v.revision FROM mentat_project_planning_input_actions a "
                    "JOIN mentat_project_planning_input_versions v ON v.id=a.input_id "
                    "WHERE a.action_id=?", (value["action_id"],),
                ).fetchone()
                if prior is not None:
                    if not hmac.compare_digest(prior[1], digest):
                        _fail("action_conflict")
                    return {"input_id": prior[0], "revision": prior[2],
                            "status": "committed_needs_review"}
                (project, incarnation, lead, role, current_context, head,
                 scope_token, selection_token) = _selection_state(connection, value["project_id"])
                if (project.revision != value["expected_project_revision"]
                        or project.document["status"] != "active"):
                    _fail("project_changed")
                if not hmac.compare_digest(scope_token, value["scope_token"]):
                    _fail("scope_changed")
                if (role is None or lead["status"] != "context_bound"
                        or role[0] != value["lead_role_id"]
                        or role[1] != value["expected_lead_revision"]):
                    _fail("lead_changed")
                if (current_context is None or current_context[1] != value["context_id"]
                        or role[6] != value["context_id"]
                        or role[7] != value["expected_grant_revision"]):
                    _fail("context_changed")
                if head != value["expected_input_revision"]:
                    _fail("revision_conflict")
                if not hmac.compare_digest(selection_token, value["selection_token"]):
                    _fail("selection_changed")
                if (head >= MAX_PROJECT_INPUT_VERSIONS_PER_INCARNATION or
                        connection.execute("SELECT COUNT(*) FROM mentat_project_planning_input_versions").fetchone()[0]
                        >= MAX_PROJECT_INPUT_VERSIONS):
                    _fail("capacity")
                allowed = {row[0] for row in connection.execute(
                    "SELECT attachment_id FROM mentat_project_context_files WHERE context_id=?",
                    (value["context_id"],),
                )}
                if any(item not in allowed for item in value["attachment_ids"]):
                    _fail("file_scope")
                entries = []
                images = 0
                for attachment_id in value["attachment_ids"]:
                    try:
                        metadata, _content = read_attachment_bytes(root, attachment_id)
                    except (AttachmentError, OSError):
                        _fail("files_unavailable")
                    if metadata["kind"] == "image":
                        images += 1
                        if images > MAX_PROJECT_INPUT_IMAGES:
                            _fail("image_limit")
                    row = connection.execute(
                        "SELECT a.id,a.blob_id,b.sha256,a.byte_size,a.kind,a.mime_type "
                        "FROM attachments a JOIN blobs b ON b.id=a.blob_id WHERE a.id=?",
                        (attachment_id,),
                    ).fetchone()
                    if (row is None or row[3] != metadata["byte_size"]
                            or row[4] != metadata["kind"] or row[5] != metadata["mime_type"]):
                        _fail("files_unavailable")
                    entries.append(list(row))
                now = time.time()
                cutoff = connection.execute(
                    "SELECT applied_at FROM schema_migrations WHERE version=40"
                ).fetchone()
                if cutoff is not None and type(cutoff[0]) in (int, float) and cutoff[0] == 0:
                    # An older backup may materialize the deterministic empty
                    # private unit. Activate its virtual schema-40 receipt in
                    # this same first publication transaction.
                    connection.execute(
                        "UPDATE schema_migrations SET applied_at=? WHERE version=40",
                        (now,),
                    )
                identifier = "project_input_" + uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO mentat_project_planning_input_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (identifier, value["project_id"], incarnation, head + 1,
                     project.revision, role[0], role[1], role[2], role[3], role[4],
                     role[5], role[6], role[7], value["instructions"],
                     hashlib.sha256(_encoded(entries)).hexdigest(), now),
                )
                connection.executemany(
                    "INSERT INTO mentat_project_planning_input_files VALUES(?,?,?,?,?,?,?,?)",
                    [(identifier, ordinal, *entry) for ordinal, entry in enumerate(entries)],
                )
                connection.execute(
                    "INSERT INTO mentat_project_planning_input_actions VALUES(?,?,?,?,?,?,?)",
                    (value["action_id"], identifier, value["scope_token"],
                     value["selection_token"], digest, "owner", now),
                )
                validate_project_context_connection(connection, require_available=False)
                return {"input_id": identifier, "revision": head + 1, "status": "saved"}


def reconcile_project_input_action(data_dir: Path, project_id: str,
                                   action_id: str, scope_token: str) -> dict:
    """Read one exact durable action receipt without resubmitting its write."""
    from private_state import private_state_lock
    from project_context import validate_project_context_connection
    from task_repository import _guarded_transaction, _open_repository_database
    if (not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None
            or not isinstance(action_id, str) or _ACTION.fullmatch(action_id) is None
            or not isinstance(scope_token, str) or _HEX64.fullmatch(scope_token) is None):
        _fail("request_invalid")
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_project_context_connection(connection, require_available=False)
                row = connection.execute(
                    "SELECT v.id,v.revision,v.project_id,v.project_incarnation "
                    "FROM mentat_project_planning_input_actions a "
                    "JOIN mentat_project_planning_input_versions v ON v.id=a.input_id "
                    "WHERE a.action_id=?", (action_id,),
                ).fetchone()
                if row is None:
                    return {"status": "not_found", "input_id": None, "revision": None}
                if (row[2] != project_id or not hmac.compare_digest(
                        _scope_token(connection, project_id, row[3]), scope_token)):
                    _fail("scope_changed")
                return {"status": "committed_needs_review", "input_id": row[0],
                        "revision": row[1]}
