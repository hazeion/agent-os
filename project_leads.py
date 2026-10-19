"""Owner-selected Project lead identity, never a Run or context grant."""

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

from agent_registry import AgentRegistryError, _canonical_agent_records
from private_state import private_state_lock
from project_repository import ProjectRepository
from task_repository import _guarded_transaction, _open_repository_database


MAX_LEAD_VERSIONS = 256
MAX_SCOPE_VERSIONS = 32
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_ROLE = re.compile(r"lead_role_[0-9a-f]{32}\Z")
_CONTEXT = re.compile(r"project_context_[0-9a-f]{32}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class ProjectLeadError(RuntimeError):
    pass


def _fail(code: str) -> None:
    raise ProjectLeadError(f"project_lead.{code}")


def _encoded(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _fail("invalid")


def _binding_digest(connection: sqlite3.Connection, record: object) -> str | None:
    row = connection.execute(
        "SELECT * FROM agent_runtime_configs WHERE id=?", (record.agent.runtime_config_id,),
    ).fetchone()
    if row is None:
        return None
    return hashlib.sha256(_encoded([list(row), record.revision,
                                    sorted(record.agent.capabilities)])).hexdigest()


def validate_lead_connection(connection: sqlite3.Connection) -> list[list]:
    """Validate immutable role history, including Project/Agent ID reuse."""
    rows = connection.execute(
        "SELECT id,project_id,project_incarnation,revision,action,agent_id,"
        "agent_incarnation,agent_revision,binding_digest,context_id,grant_revision,created_at "
        "FROM mentat_project_lead_versions ORDER BY project_incarnation,revision"
    ).fetchmany(MAX_LEAD_VERSIONS + 1)
    if len(rows) > MAX_LEAD_VERSIONS:
        _fail("capacity")
    projects = {row[0]: row[1] for row in connection.execute(
        "SELECT id,deliverable_incarnation FROM mentat_projects"
    )}
    revisions: dict[str, list[int]] = {}
    scope_projects: dict[str, str] = {}
    identifiers: set[str] = set()
    for row in rows:
        (identifier, project_id, incarnation, revision, action, agent_id,
         agent_incarnation, agent_revision, digest, context_id, grant_revision,
         created_at) = tuple(row)
        if (not isinstance(identifier, str) or _ROLE.fullmatch(identifier) is None
                or identifier in identifiers or not isinstance(project_id, str)
                or _PROJECT.fullmatch(project_id) is None
                or not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None
                or type(revision) is not int or not 1 <= revision <= MAX_SCOPE_VERSIONS
                or type(created_at) not in (int, float) or not math.isfinite(created_at)
                or created_at <= 0 or action not in {"select", "clear"}):
            _fail("invalid")
        identifiers.add(identifier)
        if action == "clear":
            if any(item is not None for item in (agent_id, agent_incarnation,
                    agent_revision, digest, context_id, grant_revision)):
                _fail("invalid")
        elif (not isinstance(agent_id, str) or _AGENT.fullmatch(agent_id) is None
              or not isinstance(agent_incarnation, str)
              or _HEX32.fullmatch(agent_incarnation) is None
              or type(agent_revision) is not int or agent_revision < 1
              or not isinstance(digest, str) or _HEX64.fullmatch(digest) is None
              or ((context_id is None) != (grant_revision is None))
              or (context_id is not None and
                  (not isinstance(context_id, str) or _CONTEXT.fullmatch(context_id) is None
                   or type(grant_revision) is not int or grant_revision < 1))):
            _fail("invalid")
        if incarnation in scope_projects and scope_projects[incarnation] != project_id:
            _fail("invalid")
        scope_projects[incarnation] = project_id
        revisions.setdefault(incarnation, []).append(revision)
    if any(values != list(range(1, len(values) + 1)) for values in revisions.values()):
        _fail("invalid")
    current_by_incarnation = {incarnation: project_id for project_id, incarnation in projects.items()}
    for incarnation, project_id in scope_projects.items():
        # Historical incarnations remain after confirmed Project deletion.
        # They may not impersonate another currently live Project.
        if current_by_incarnation.get(incarnation, project_id) != project_id:
            _fail("invalid")
    # Charge terminal representation and the full bounded identity space so
    # a valid backup remains within the same budget after owner changes.
    return [[list(row[:5]) + ["x" * 128, "0" * 32, 9007199254740991,
                               "0" * 64, "project_context_" + "0" * 32,
                               9007199254740991, row[11]] for row in rows]]


def _current_context(connection: sqlite3.Connection, project_id: str) -> tuple[str, str] | None:
    row = connection.execute(
        "SELECT s.id,v.id FROM mentat_project_context_scopes s "
        "JOIN mentat_project_context_versions v ON v.scope_id=s.id AND v.revision=s.revision "
        "WHERE s.project_id=? AND s.retired_at IS NULL", (project_id,),
    ).fetchone()
    return tuple(row) if row else None


def _selection_snapshot(connection: sqlite3.Connection, project_id: str,
                        project: object, incarnation: str, revision: int,
                        record: object | None) -> tuple[str, bool]:
    context = _current_context(connection, project_id)
    agent_row = connection.execute(
        "SELECT context_incarnation FROM mentat_agents WHERE id=?", (record.agent.id,),
    ).fetchone() if record else None
    digest = _binding_digest(connection, record) if record else None
    grant = connection.execute(
        "SELECT agent_incarnation,context_id,revision,state FROM mentat_project_context_grants "
        "WHERE scope_id=? AND agent_id=?", (context[0], record.agent.id),
    ).fetchone() if context and record else None
    bound = bool(record and agent_row and digest and context and grant and tuple(grant) == (
        agent_row[0], context[1], grant[2], "active"))
    epoch = connection.execute(
        "SELECT approval_epoch FROM mentat_project_context_access_state WHERE singleton=1"
    ).fetchone()
    if epoch is None or not isinstance(epoch[0], bytes) or len(epoch[0]) != 32:
        _fail("unavailable")
    claims = [project_id, incarnation, project.revision, project.document["status"], revision,
              list(context) if context else None,
              record.agent.id if record else None, agent_row[0] if agent_row else None,
              record.revision if record else None, digest,
              list(grant) if grant else None]
    return hmac.new(epoch[0], b"mentat-project-lead-selection-v1\0" + _encoded(claims),
                    hashlib.sha256).hexdigest(), bound


def _projection(connection: sqlite3.Connection, project_id: str, project: object,
                incarnation: str) -> dict:
    row = connection.execute(
        "SELECT id,revision,action,agent_id,agent_incarnation,agent_revision,"
        "binding_digest,context_id,grant_revision "
        "FROM mentat_project_lead_versions WHERE project_id=? AND project_incarnation=? "
        "ORDER BY revision DESC LIMIT 1", (project_id, incarnation),
    ).fetchone()
    base = {"project_id": project_id, "project_revision": project.revision,
            "revision": row[1] if row else 0, "id": row[0] if row else None,
            "agent_id": row[3] if row and row[2] == "select" else None,
            "agent_name": None, "status": "unassigned", "reasons": [],
            "proposal_available": False, "choices": [], "clear_token": ""}
    try:
        records = {item.agent.id: item for item in _canonical_agent_records(
            connection, supported_runtime_types=("hermes", "codex", "vercel"))}
    except AgentRegistryError:
        records = {}
    base["clear_token"] = _selection_snapshot(connection, project_id, project,
                                               incarnation, base["revision"], None)[0]
    if project.document["status"] == "active":
        for item in sorted(records.values(), key=lambda item: item.agent.id):
            if _binding_digest(connection, item) is None:
                continue
            token, bound = _selection_snapshot(connection, project_id, project,
                                               incarnation, base["revision"], item)
            base["choices"].append({"id": item.agent.id, "name": item.agent.name,
                                    "context_bound": bound, "selection_token": token})
    if row is None or row[2] == "clear":
        return base
    reasons: list[str] = []
    if project.document["status"] != "active":
        reasons.append("project_inactive")
    record = records.get(row[3])
    agent = connection.execute("SELECT context_incarnation,name FROM mentat_agents WHERE id=?",
                               (row[3],)).fetchone()
    if (record is None or agent is None or agent[0] != row[4]
            or record.revision != row[5] or _binding_digest(connection, record) != row[6]):
        reasons.append("agent_changed")
    else:
        base["agent_name"] = agent[1]
    context = _current_context(connection, project_id)
    if row[7] is None:
        reasons.append("context_grant_needed")
    elif context is None or context[1] != row[7]:
        reasons.append("context_changed")
    else:
        grant = connection.execute(
            "SELECT agent_incarnation,context_id,revision,state FROM mentat_project_context_grants "
            "WHERE scope_id=? AND agent_id=?", (context[0], row[3]),
        ).fetchone()
        if grant is None or tuple(grant) != (row[4], row[7], row[8], "active"):
            reasons.append("grant_changed")
    base["reasons"] = reasons
    base["status"] = "context_bound" if not reasons else "unready" if reasons == ["context_grant_needed"] else "stale"
    return base


def read_project_lead(data_dir: Path, project_id: str) -> dict:
    from project_context import validate_project_context_connection
    if not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None:
        _fail("request_invalid")
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_project_context_connection(connection, require_available=False)
                project = ProjectRepository(connection).get(project_id)
                incarnation = connection.execute(
                    "SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (project_id,),
                ).fetchone()[0]
                return _projection(connection, project_id, project, incarnation)


def select_project_lead(data_dir: Path, project_id: str, agent_id: str | None, *,
                        expected_project_revision: int, expected_lead_revision: int,
                        selection_token: str) -> dict:
    """Append one exact owner selection; do not grant or dispatch anything."""
    from project_context import validate_project_context_connection
    if (not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None
            or agent_id is not None and (not isinstance(agent_id, str) or _AGENT.fullmatch(agent_id) is None)
            or type(expected_project_revision) is not int or expected_project_revision < 1
            or type(expected_lead_revision) is not int or not 0 <= expected_lead_revision <= MAX_SCOPE_VERSIONS
            or not isinstance(selection_token, str) or _HEX64.fullmatch(selection_token) is None):
        _fail("request_invalid")
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                validate_project_context_connection(connection, require_available=False)
                project = ProjectRepository(connection).get(project_id)
                if project.revision != expected_project_revision or project.document["status"] != "active":
                    _fail("project_changed")
                incarnation = connection.execute(
                    "SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (project_id,),
                ).fetchone()[0]
                if not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None:
                    _fail("project_changed")
                head = connection.execute(
                    "SELECT MAX(revision) FROM mentat_project_lead_versions WHERE project_incarnation=?",
                    (incarnation,),
                ).fetchone()[0] or 0
                if head != expected_lead_revision:
                    _fail("revision_conflict")
                if head >= MAX_SCOPE_VERSIONS or connection.execute(
                    "SELECT COUNT(*) FROM mentat_project_lead_versions"
                ).fetchone()[0] >= MAX_LEAD_VERSIONS:
                    _fail("capacity")
                action = "clear" if agent_id is None else "select"
                agent_identity = agent_revision = binding_digest = context_id = grant_revision = None
                record = None
                if agent_id is not None:
                    try:
                        records = _canonical_agent_records(
                            connection, supported_runtime_types=("hermes", "codex", "vercel"))
                    except AgentRegistryError:
                        _fail("agent_unavailable")
                    record = next((item for item in records if item.agent.id == agent_id), None)
                    agent = connection.execute(
                        "SELECT context_incarnation FROM mentat_agents WHERE id=?", (agent_id,),
                    ).fetchone()
                    if record is None or agent is None or _binding_digest(connection, record) is None:
                        _fail("agent_unavailable")
                expected, context_bound = _selection_snapshot(
                    connection, project_id, project, incarnation, head, record,
                )
                if not hmac.compare_digest(expected, selection_token):
                    _fail("selection_changed")
                if record is not None:
                    agent_identity, agent_revision = agent[0], record.revision
                    binding_digest = _binding_digest(connection, record)
                    context = _current_context(connection, project_id) if context_bound else None
                    if context is not None:
                        grant = connection.execute(
                            "SELECT agent_incarnation,context_id,revision,state "
                            "FROM mentat_project_context_grants WHERE scope_id=? AND agent_id=?",
                            (context[0], agent_id),
                        ).fetchone()
                        if grant is not None and tuple(grant) == (
                                agent_identity, context[1], grant[2], "active"):
                            context_id, grant_revision = context[1], grant[2]
                identifier = f"lead_role_{uuid.uuid4().hex}"
                connection.execute(
                    "INSERT INTO mentat_project_lead_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (identifier, project_id, incarnation, head + 1, action, agent_id,
                     agent_identity, agent_revision, binding_digest, context_id,
                     grant_revision, time.time()),
                )
                validate_project_context_connection(connection, require_available=False)
                return _projection(connection, project_id, project, incarnation)
