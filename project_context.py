"""Immutable owner-authored Project context; no Agent grant or dispatch authority."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import uuid

from agent_console_attachments import (
    AttachmentError, MAX_RETAINED_BLOBS, MAX_RETAINED_BLOB_BYTES,
    read_attachment_bytes,
)
from private_state import private_state_lock
from project_repository import ProjectRepository, ProjectRepositoryError
from task_repository import _guarded_transaction, _open_repository_database

MAX_BRIEF_BYTES = 16 * 1024
MAX_FILES = 16
MAX_PROJECT_VERSIONS = 32
MAX_VERSIONS = 256
LEGACY_MAX_METADATA_BYTES = 4 * 1024 * 1024
# Schema 28 reserves bounded migration/control overhead for 128 Agent
# incarnations, up to 256 scope retirement fields, and the approval epoch.
ACCESS_MAX_METADATA_BYTES = LEGACY_MAX_METADATA_BYTES + 64 * 1024
# Schema 29 reserves every supported Task identity slot plus empty input graph
# framing. Full schema-28 roots must remain valid after the identity migration.
MAX_METADATA_BYTES = ACCESS_MAX_METADATA_BYTES + 512 * 1024
# Schema 30 charges immutable Run-input receipts and exact file identities in
# the same bounded graph. Empty migration overhead is intentionally small.
RUN_INPUT_MAX_METADATA_BYTES = MAX_METADATA_BYTES + 512 * 1024
# Schema 31 shares the same graph with bounded typed deliverable versions.
DELIVERABLE_MAX_METADATA_BYTES = RUN_INPUT_MAX_METADATA_BYTES + 2 * 1024 * 1024
# Schema 32 adds bounded immutable owner review decisions for exact result heads.
DELIVERABLE_REVIEW_MAX_METADATA_BYTES = DELIVERABLE_MAX_METADATA_BYTES + 1024 * 1024
# Schema 33 reserves immutable bounded plan versions and protected input refs.
PLAN_MAX_METADATA_BYTES = DELIVERABLE_REVIEW_MAX_METADATA_BYTES + 8 * 1024 * 1024
_SCOPE = re.compile(r"project_scope_[0-9a-f]{32}\Z")
_VERSION = re.compile(r"project_context_[0-9a-f]{32}\Z")
_ATTACHMENT = re.compile(r"attachment_[0-9a-f]{32}\Z")


class ProjectContextError(RuntimeError):
    """A fixed, non-sensitive context failure."""


def _fail(code: str) -> None:
    raise ProjectContextError(f"project_context.{code}")


def _brief(value: object) -> str:
    if not isinstance(value, str) or "\0" in value:
        _fail("brief_invalid")
    try:
        length = len(value.encode("utf-8"))
    except UnicodeError:
        _fail("brief_invalid")
    if length > MAX_BRIEF_BYTES:
        _fail("brief_invalid")
    return value


def _file_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > MAX_FILES:
        _fail("files_invalid")
    if any(not isinstance(item, str) or not _ATTACHMENT.fullmatch(item) for item in value):
        _fail("files_invalid")
    if len(set(value)) != len(value):
        _fail("files_invalid")
    return tuple(value)


def _encoded(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        _fail("invalid")


def validate_project_context_connection(connection: sqlite3.Connection, *, require_available: bool = True) -> None:
    """Validate the complete bounded retained graph, including backup snapshots."""
    # No row_factory mutation: backup validators and repositories share this handle.
    scopes = connection.execute(
        "SELECT id,project_id,revision,created_at,retired_at FROM mentat_project_context_scopes ORDER BY id"
    ).fetchmany(MAX_VERSIONS + 1)
    versions = connection.execute(
        "SELECT id,scope_id,revision,brief,files_digest,created_at FROM mentat_project_context_versions ORDER BY scope_id,revision"
    ).fetchmany(MAX_VERSIONS + 1)
    files = connection.execute(
        "SELECT context_id,attachment_id,ordinal FROM mentat_project_context_files ORDER BY context_id,ordinal"
    ).fetchmany(MAX_VERSIONS * MAX_FILES + 1)
    if len(scopes) > MAX_VERSIONS or len(versions) > MAX_VERSIONS or len(files) > MAX_VERSIONS * MAX_FILES:
        _fail("capacity")
    schema_version = connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0]
    metadata = [[list(row) for row in rows] for rows in (scopes, versions, files)]
    budget = LEGACY_MAX_METADATA_BYTES
    if schema_version >= 28:
        budget = ACCESS_MAX_METADATA_BYTES
        metadata[0] = [list(row[:4]) + ['0' * 32] for row in scopes]
        from project_context_access import ProjectContextAccessError, validate_access_connection
        try:
            metadata.extend(validate_access_connection(connection))
        except ProjectContextAccessError as exc:
            if str(exc) == 'project_context_access.capacity':
                _fail('capacity')
            _fail('invalid')
    if schema_version >= 29:
        budget = MAX_METADATA_BYTES
        from task_inputs import TaskInputError, validate_input_connection
        try:
            metadata.extend(validate_input_connection(connection, require_available=require_available))
        except TaskInputError as exc:
            if str(exc) == 'task_input.capacity':
                _fail('capacity')
            _fail('task_inputs_invalid')
    if schema_version >= 30:
        budget = RUN_INPUT_MAX_METADATA_BYTES
        from run_input_receipts import RunInputReceiptError, validate_run_input_connection
        try:
            metadata.extend(validate_run_input_connection(connection, require_available=require_available))
        except RunInputReceiptError as exc:
            if str(exc) == 'run_input.capacity':
                _fail('capacity')
            _fail('run_inputs_invalid')
    if schema_version >= 31:
        budget = DELIVERABLE_MAX_METADATA_BYTES
        from project_deliverables import DeliverableError, validate_deliverable_connection
        try:
            metadata.extend(validate_deliverable_connection(connection, require_available=require_available))
        except DeliverableError as exc:
            if str(exc) == 'deliverable.capacity':
                _fail('capacity')
            _fail('deliverables_invalid')
    if schema_version >= 32:
        budget = DELIVERABLE_REVIEW_MAX_METADATA_BYTES
        from project_deliverable_review import DeliverableReviewError, validate_review_connection
        try:
            metadata.extend(validate_review_connection(connection))
        except DeliverableReviewError as exc:
            if str(exc) == 'deliverable_review.capacity':
                _fail('capacity')
            _fail('deliverable_review_invalid')
    if schema_version >= 33:
        budget = PLAN_MAX_METADATA_BYTES
        from project_plans import ProjectPlanError, validate_plan_connection
        try:
            metadata.extend(validate_plan_connection(connection))
        except ProjectPlanError as exc:
            if str(exc) == 'project_plan.capacity':
                _fail('capacity')
            _fail('plans_invalid')
    if len(_encoded(metadata)) > budget:
        _fail("capacity")
    projects = {str(row[0]) for row in connection.execute("SELECT id FROM mentat_projects")}
    scope_map = {}
    for identifier, project_id, revision, created_at, retired_at in scopes:
        if (not isinstance(identifier, str) or not _SCOPE.fullmatch(identifier)
                or (retired_at is None and project_id not in projects)
                or not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", project_id)
                or type(revision) is not int or revision < 1
                or not isinstance(created_at, (int, float)) or not math.isfinite(created_at) or created_at <= 0
                or (retired_at is not None and (not isinstance(retired_at, (int, float)) or not math.isfinite(retired_at) or retired_at < created_at))):
            _fail("invalid")
        scope_map[identifier] = revision
    if scopes:
        original_factory = connection.row_factory
        try:
            ProjectRepository(connection).authority_receipt(required=True)
        except ProjectRepositoryError:
            _fail("invalid")
        finally:
            connection.row_factory = original_factory
    versions_by_scope = {identifier: [] for identifier in scope_map}
    version_ids = set()
    file_digests = {}
    for identifier, scope_id, revision, brief, files_digest, created_at in versions:
        if (not isinstance(identifier, str) or not _VERSION.fullmatch(identifier) or scope_id not in scope_map
                or type(revision) is not int or revision < 1
                or not isinstance(created_at, (int, float)) or not math.isfinite(created_at) or created_at <= 0):
            _fail("invalid")
        _brief(brief)
        versions_by_scope[scope_id].append(revision)
        version_ids.add(identifier)
        file_digests[identifier] = files_digest
    for identifier, revisions in versions_by_scope.items():
        if not revisions or len(revisions) > MAX_PROJECT_VERSIONS or revisions[-1] != scope_map[identifier]:
            _fail("invalid")
    ordinals = {identifier: [] for identifier in version_ids}
    attachment_lists = {identifier: [] for identifier in version_ids}
    for context_id, attachment_id, ordinal in files:
        if context_id not in version_ids or not isinstance(attachment_id, str) or not _ATTACHMENT.fullmatch(attachment_id):
            _fail("invalid")
        ordinals[context_id].append(ordinal)
        attachment_lists[context_id].append(attachment_id)
    for values in ordinals.values():
        if len(values) > MAX_FILES or values != list(range(len(values))):
            _fail("invalid")
    for identifier, identifiers in attachment_lists.items():
        if hashlib.sha256(_encoded(identifiers)).hexdigest() != file_digests[identifier]:
            _fail("invalid")
    availability = " OR a.state!='attached' OR b.state!='ready'" if require_available else ''
    dangling = connection.execute(
        "SELECT COUNT(*) FROM mentat_project_context_files r "
        "LEFT JOIN attachments a ON a.id=r.attachment_id LEFT JOIN blobs b ON b.id=a.blob_id "
        "WHERE a.id IS NULL OR b.id IS NULL OR a.byte_size!=b.byte_size" + availability
    ).fetchone()[0]
    if dangling:
        _fail("file_unavailable")
    validate_retained_capacity(connection)


def validate_retained_capacity(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT COUNT(*),COALESCE(SUM(byte_size),0) FROM blobs WHERE id IN "
        "(SELECT a.blob_id FROM attachments a JOIN mentat_retained_attachments r ON r.attachment_id=a.id)"
    ).fetchone()
    if row[0] > MAX_RETAINED_BLOBS or row[1] > MAX_RETAINED_BLOB_BYTES:
        _fail("blob_capacity")


def _snapshot(connection: sqlite3.Connection, project_id: str, revision: int | None) -> dict | None:
    scope = connection.execute(
        "SELECT id,revision FROM mentat_project_context_scopes WHERE project_id=? AND retired_at IS NULL", (project_id,)
    ).fetchone()
    if scope is None:
        return None
    selected = scope[1] if revision is None else revision
    row = connection.execute(
        "SELECT id,revision,brief,created_at FROM mentat_project_context_versions WHERE scope_id=? AND revision=?",
        (scope[0], selected),
    ).fetchone()
    if row is None:
        _fail("version_unavailable")
    files = [str(item[0]) for item in connection.execute(
        "SELECT attachment_id FROM mentat_project_context_files WHERE context_id=? ORDER BY ordinal", (row[0],)
    )]
    return {"id": row[0], "project_id": project_id, "revision": row[1], "brief": row[2],
            "attachment_ids": files, "created_at": row[3]}


def read_project_context(data_dir: Path, project_id: str, *, revision: int | None = None) -> dict | None:
    """Trusted owner read. Future routes must separately enforce owner admission."""
    if revision is not None and (type(revision) is not int or revision < 1):
        _fail("revision_invalid")
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard):
                repository = ProjectRepository(connection)
                repository.authority_receipt(required=True)
                repository.get(project_id)
                validate_project_context_connection(connection, require_available=False)
                return _snapshot(connection, project_id, revision)


def publish_project_context(
    data_dir: Path, project_id: str, *, expected_project_revision: int,
    expected_revision: int, brief: str, attachment_ids: tuple[str, ...] | list[str],
    expected_staged_ids: tuple[str, ...] | list[str] | None = None,
) -> dict:
    """Publish one exact revision, retaining every selected file or none."""
    if (type(expected_revision) is not int or expected_revision < 0
            or type(expected_project_revision) is not int or expected_project_revision < 1):
        _fail("revision_invalid")
    brief = _brief(brief)
    identifiers = _file_ids(attachment_ids)
    staged = None if expected_staged_ids is None else _file_ids(expected_staged_ids)
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                repository = ProjectRepository(connection)
                repository.authority_receipt(required=True)
                project = repository.get(project_id)
                if project.revision != expected_project_revision:
                    _fail("project_changed")
                if project.document["status"] != "active":
                    _fail("project_unavailable")
                validate_project_context_connection(connection, require_available=False)
                if staged is not None:
                    current_staged = tuple(row[0] for row in connection.execute(
                        'SELECT attachment_id FROM mentat_project_context_staged WHERE project_id=? ORDER BY attachment_id', (project_id,)
                    ))
                    if tuple(sorted(staged)) != current_staged:
                        _fail('staging_changed')
                    for attachment in identifiers:
                        retained_here = connection.execute(
                            'SELECT 1 FROM mentat_project_context_files f JOIN mentat_project_context_versions v ON v.id=f.context_id '
                            'JOIN mentat_project_context_scopes s ON s.id=v.scope_id '
                            'WHERE s.project_id=? AND s.retired_at IS NULL AND f.attachment_id=?', (project_id, attachment)
                        ).fetchone()
                        if attachment not in staged and retained_here is None:
                            _fail('file_scope')
                scope = connection.execute(
                    "SELECT id,revision FROM mentat_project_context_scopes WHERE project_id=? AND retired_at IS NULL", (project_id,)
                ).fetchone()
                if (scope[1] if scope else 0) != expected_revision:
                    _fail("revision_conflict")
                now = time.time()
                for identifier in identifiers:
                    row = connection.execute("SELECT state,expires_at FROM attachments WHERE id=?", (identifier,)).fetchone()
                    if row is None or row[0] not in {"staged", "attached"} or (
                        row[0] == "staged" and (row[1] is None or row[1] <= now)
                    ):
                        _fail("file_unavailable")
                    try:
                        read_attachment_bytes(root, identifier)
                    except (AttachmentError, OSError):
                        _fail("file_unavailable")
                scope_id = scope[0] if scope else "project_scope_" + uuid.uuid4().hex
                if connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] >= 28:
                    connection.execute(
                        'UPDATE mentat_project_context_access_state SET approval_epoch=randomblob(32) '
                        'WHERE singleton=1 AND approval_epoch=zeroblob(32)'
                    )
                revision = expected_revision + 1
                identifier = "project_context_" + uuid.uuid4().hex
                if scope:
                    connection.execute("UPDATE mentat_project_context_scopes SET revision=? WHERE id=?", (revision, scope_id))
                else:
                    connection.execute(
                        "INSERT INTO mentat_project_context_scopes(id,project_id,revision,created_at) VALUES(?,?,?,?)", (scope_id, project_id, revision, now)
                    )
                connection.execute(
                    "INSERT INTO mentat_project_context_versions VALUES(?,?,?,?,?,?)",
                    (identifier, scope_id, revision, brief, hashlib.sha256(_encoded(identifiers)).hexdigest(), now)
                )
                for ordinal, attachment in enumerate(identifiers):
                    connection.execute("INSERT INTO mentat_project_context_files VALUES(?,?,?)", (identifier, attachment, ordinal))
                    connection.execute(
                        "UPDATE attachments SET state='attached',expires_at=NULL,delete_after=NULL,updated_at=? WHERE id=?",
                        (now, attachment),
                    )
                    if staged is not None:
                        connection.execute('DELETE FROM mentat_project_context_staged WHERE project_id=? AND attachment_id=?', (project_id, attachment))
                validate_project_context_connection(connection, require_available=False)
                return _snapshot(connection, project_id, revision)


def retire_project_contexts(connection: sqlite3.Connection, project_ids: tuple[str, ...]) -> None:
    """Called only by exact confirmed deletion inside its guarded transaction."""
    if not connection.in_transaction:
        _fail("transaction_required")
    for project_id in project_ids:
        connection.execute(
            "UPDATE mentat_project_context_scopes SET retired_at=? WHERE project_id=? AND retired_at IS NULL",
            (time.time(), project_id),
        )


def read_retired_project_context(data_dir: Path, context_id: str) -> dict:
    """Trusted owner history read; never resolve a retired scope by reused Project ID."""
    if not isinstance(context_id, str) or not _VERSION.fullmatch(context_id):
        _fail("version_unavailable")
    with private_state_lock(Path(data_dir)):
        with _open_repository_database(Path(data_dir)) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_project_context_connection(connection, require_available=False)
                row = connection.execute(
                    "SELECT v.id,v.revision,v.brief,v.created_at,s.project_id FROM mentat_project_context_versions v "
                    "JOIN mentat_project_context_scopes s ON s.id=v.scope_id WHERE v.id=? AND s.retired_at IS NOT NULL",
                    (context_id,),
                ).fetchone()
                if row is None:
                    _fail("version_unavailable")
                identifiers = [str(item[0]) for item in connection.execute(
                    "SELECT attachment_id FROM mentat_project_context_files WHERE context_id=? ORDER BY ordinal", (context_id,)
                )]
                return {"id": row[0], "project_id": row[4], "revision": row[1], "brief": row[2],
                        "created_at": row[3], "attachment_ids": identifiers, "retired": True}
