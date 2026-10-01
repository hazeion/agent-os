"""Immutable Project plan preparation; no approval, scheduler or dispatch authority."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
import uuid

from private_state import private_state_lock
from project_repository import ProjectRepository
from task_repository import TaskRepository, _guarded_transaction, _open_repository_database


MAX_SCOPES = 256
MAX_VERSIONS = 256
MAX_SCOPE_VERSIONS = 32
MAX_NODES = 32
MAX_CONTENT_BYTES = 16 * 1024
_PROJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_INPUT = re.compile(r"task_input_[0-9a-f]{32}\Z")
_SCOPE = re.compile(r"plan_scope_[0-9a-f]{32}\Z")
_VERSION = re.compile(r"plan_version_[0-9a-f]{32}\Z")
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_PUBLIC_NODE_KEYS = frozenset({"task_id", "expected_task_revision", "agent_id", "input_version_id", "after", "segment", "max_attempts", "max_wall_seconds", "max_work_units"})
_STORED_NODE_KEYS = (_PUBLIC_NODE_KEYS - {"expected_task_revision"}) | {"task_revision", "task_incarnation", "agent_incarnation"}


class ProjectPlanError(RuntimeError):
    pass


def _fail(code: str) -> None:
    raise ProjectPlanError(f"project_plan.{code}")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _fail("invalid")


def _number(value: object, lower: int, upper: int) -> int:
    if type(value) is not int or not lower <= value <= upper:
        _fail("invalid")
    return value


def _title(value: object) -> str:
    if not isinstance(value, str) or any(unicodedata.category(char).startswith("C") for char in value):
        _fail("invalid")
    title = value.strip()
    try:
        size = len(title.encode("utf-8"))
    except UnicodeError:
        _fail("invalid")
    if not 1 <= size <= 120:
        _fail("invalid")
    return title


def _nodes(value: object, *, stored: bool) -> list[dict]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_NODES:
        _fail("invalid")
    result: list[dict] = []
    seen: set[str] = set()
    segments: set[int] = set()
    positions: dict[str, int] = {}
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != (_STORED_NODE_KEYS if stored else _PUBLIC_NODE_KEYS):
            _fail("invalid")
        task_id, agent_id, input_id = raw["task_id"], raw["agent_id"], raw["input_version_id"]
        if (not isinstance(task_id, str) or _TASK.fullmatch(task_id) is None or task_id in seen
                or not isinstance(agent_id, str) or _AGENT.fullmatch(agent_id) is None
                or not isinstance(input_id, str) or _INPUT.fullmatch(input_id) is None):
            _fail("invalid")
        seen.add(task_id)
        segment = _number(raw["segment"], 0, MAX_NODES - 1)
        if result and segment < result[-1]["segment"]:
            _fail("invalid")
        segments.add(segment)
        after = raw["after"]
        if (not isinstance(after, list) or len(after) > MAX_NODES - 1
                or any(not isinstance(item, str) or item not in positions for item in after)
                or len(set(after)) != len(after)
                or any(positions[item] > segment for item in after)):
            _fail("invalid")
        attempts = _number(raw["max_attempts"], 1, 3)
        wall = _number(raw["max_wall_seconds"], 60, 86400)
        work = _number(raw["max_work_units"], 1, 1000)
        revision_key = "task_revision" if stored else "expected_task_revision"
        revision = _number(raw[revision_key], 1, 9007199254740991)
        node = {"task_id": task_id, revision_key: revision, "agent_id": agent_id,
                "input_version_id": input_id, "after": list(after), "segment": segment,
                "max_attempts": attempts, "max_wall_seconds": wall, "max_work_units": work}
        if stored:
            for key in ("task_incarnation", "agent_incarnation"):
                item = raw[key]
                if not isinstance(item, str) or _HEX32.fullmatch(item) is None:
                    _fail("invalid")
                node[key] = item
        result.append(node)
        positions[task_id] = segment
    if segments != set(range(max(segments) + 1)) or result[0]["segment"] != 0:
        _fail("invalid")
    return result


def normalize_owner_plan(title: object, nodes: object) -> dict:
    content = {"title": _title(title), "nodes": _nodes(nodes, stored=False)}
    if len(_canonical(content)) > MAX_CONTENT_BYTES:
        _fail("capacity")
    return content


def _dependency_comparison(connection: sqlite3.Connection, content: dict) -> dict:
    planned_tasks = {node["task_id"] for node in content["nodes"]}
    planned = {(node["task_id"], predecessor) for node in content["nodes"] for predecessor in node["after"]}
    selected = sorted(planned_tasks)
    placeholders = ",".join("?" for _ in selected)
    rows = connection.execute(
        f"SELECT task_id,dependency_task_id FROM mentat_task_dependencies "
        f"WHERE task_id IN ({placeholders}) LIMIT ?", (*selected, MAX_NODES * 100 + 1),
    ).fetchall()
    if len(rows) > MAX_NODES * 100:
        _fail("capacity")
    canonical = {(task_id, predecessor) for task_id, predecessor in rows}
    missing = sorted(canonical - planned)
    additional = sorted(planned - canonical)
    def projected(edges: list[tuple[str, str]]) -> list[dict]:
        return [{"task_id": task_id, "prerequisite_id": prerequisite} for task_id, prerequisite in edges[:128]]
    return {"missing_from_plan": projected(missing), "additional_in_plan": projected(additional),
            "missing_count": len(missing), "additional_count": len(additional),
            "truncated": len(missing) > 128 or len(additional) > 128}


def _stale_reasons(connection: sqlite3.Connection, project_id: str, project_status: str,
                   project_revision: int, plan_project_revision: int,
                   context_scope_id: str, content: dict, comparison: dict) -> list[str]:
    """Safe advisory only; this never grants approval or execution authority."""
    from agent_registry import AgentRegistryError, _canonical_agent_records
    reasons: set[str] = set()
    if project_status != "active":
        reasons.add("project_inactive")
    if project_revision != plan_project_revision:
        reasons.add("project_changed")
    try:
        records = _canonical_agent_records(connection, supported_runtime_types=("hermes", "codex", "vercel"))
        agents = {record.agent.id: record for record in records}
    except AgentRegistryError:
        agents = {}
        reasons.add("agent_changed")
    if comparison["missing_count"] or comparison["additional_count"]:
        reasons.add("dependency_mismatch")
    for node in content["nodes"]:
        task = connection.execute(
            "SELECT revision,project_id,assigned_agent_id,input_incarnation FROM mentat_tasks WHERE id=?",
            (node["task_id"],),
        ).fetchone()
        if (task is None or tuple(task) != (node["task_revision"], project_id,
                                             node["agent_id"], node["task_incarnation"])):
            reasons.add("task_changed")
        agent = connection.execute(
            "SELECT context_incarnation FROM mentat_agents WHERE id=?", (node["agent_id"],),
        ).fetchone()
        if agent is None or agent[0] != node["agent_incarnation"]:
            reasons.add("agent_changed")
        input_row = connection.execute(
            "SELECT s.project_scope_id,s.retired_at,s.revision,v.revision,v.context_id,"
            "v.grant_revision,v.binding_digest FROM mentat_task_input_versions v "
            "JOIN mentat_task_input_scopes s ON s.id=v.scope_id WHERE v.id=?",
            (node["input_version_id"],),
        ).fetchone()
        if (input_row is None or input_row[0] != context_scope_id or input_row[1] is not None
                or input_row[2] != input_row[3]):
            reasons.add("input_changed")
            continue
        grant = connection.execute(
            "SELECT agent_incarnation,context_id,revision,state FROM mentat_project_context_grants "
            "WHERE scope_id=? AND agent_id=?", (context_scope_id, node["agent_id"]),
        ).fetchone()
        if grant is None or tuple(grant) != (
                node["agent_incarnation"], input_row[4], input_row[5], "active"):
            reasons.add("grant_changed")
        record = agents.get(node["agent_id"])
        binding = connection.execute(
            "SELECT * FROM agent_runtime_configs WHERE id=?", (record.agent.runtime_config_id,),
        ).fetchone() if record else None
        digest = hashlib.sha256(_canonical([list(binding), record.revision, sorted(record.agent.capabilities)])).hexdigest() if binding else None
        if digest != input_row[6]:
            reasons.add("agent_changed")
    order = ("project_inactive", "project_changed", "task_changed", "dependency_mismatch", "agent_changed", "input_changed", "grant_changed")
    return [reason for reason in order if reason in reasons]


def validate_plan_connection(connection: sqlite3.Connection) -> list[list]:
    """Validate live/retired immutable plan history in normal and backup DBs."""
    scopes = connection.execute(
        "SELECT id,project_id,project_incarnation,context_scope_id,head_revision,created_at,retired_at "
        "FROM mentat_plan_scopes ORDER BY id"
    ).fetchmany(MAX_SCOPES + 1)
    versions = connection.execute(
        "SELECT id,scope_id,revision,project_revision,format,content_json,content_digest,origin,created_at "
        "FROM mentat_plan_versions ORDER BY scope_id,revision"
    ).fetchmany(MAX_VERSIONS + 1)
    refs = connection.execute(
        "SELECT version_id,input_id FROM mentat_plan_input_refs ORDER BY version_id,input_id"
    ).fetchmany(MAX_VERSIONS * MAX_NODES + 1)
    input_rows = connection.execute(
        "SELECT v.id,s.task_id,s.task_incarnation,s.project_scope_id,v.task_revision,v.agent_id,v.agent_incarnation "
        "FROM mentat_task_input_versions v JOIN mentat_task_input_scopes s ON s.id=v.scope_id"
    ).fetchmany(257)
    if len(scopes) > MAX_SCOPES or len(versions) > MAX_VERSIONS or len(refs) > MAX_VERSIONS * MAX_NODES:
        _fail("capacity")
    if len(input_rows) > 256:
        _fail("capacity")
    input_map = {row[0]: tuple(row)[1:] for row in input_rows}
    current = {row[0]: row[1] for row in connection.execute("SELECT id,deliverable_incarnation FROM mentat_projects")}
    context = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT id,project_id,retired_at FROM mentat_project_context_scopes"
    )}
    scope_map: dict[str, tuple] = {}
    revisions: dict[str, list[int]] = {}
    for row in scopes:
        identifier, project_id, incarnation, context_id, head, created, retired = tuple(row)
        bound = context.get(context_id)
        if (not isinstance(identifier, str) or _SCOPE.fullmatch(identifier) is None
                or not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None
                or not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None
                or bound is None or bound[0] != project_id
                or type(head) is not int or not 1 <= head <= MAX_SCOPE_VERSIONS
                or type(created) not in (int, float) or not math.isfinite(created) or created <= 0
                or retired is None and (current.get(project_id) != incarnation or bound[1] is not None)
                or retired is not None and (type(retired) not in (int, float) or not math.isfinite(retired)
                                                or retired < created or current.get(project_id) == incarnation
                                                or bound[1] is None)):
            _fail("invalid")
        scope_map[identifier] = (project_id, incarnation, context_id, head)
        revisions[identifier] = []
    ref_map: dict[str, set[str]] = {}
    for version_id, input_id in refs:
        if (not isinstance(version_id, str) or not isinstance(input_id, str)
                or _INPUT.fullmatch(input_id) is None):
            _fail("invalid")
        ref_map.setdefault(version_id, set()).add(input_id)
    for row in versions:
        identifier, scope_id, revision, project_revision, format_version, raw, digest, origin, created = tuple(row)
        if (not isinstance(identifier, str) or _VERSION.fullmatch(identifier) is None
                or scope_id not in scope_map or type(revision) is not int
                or not 1 <= revision <= MAX_SCOPE_VERSIONS
                or type(project_revision) is not int or project_revision < 1
                or format_version != 1 or origin != "owner_edit"
                or not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_CONTENT_BYTES
                or not isinstance(digest, str) or _HEX64.fullmatch(digest) is None
                or type(created) not in (int, float) or not math.isfinite(created) or created <= 0):
            _fail("invalid")
        try:
            content = json.loads(raw)
        except (ValueError, TypeError):
            _fail("invalid")
        if not isinstance(content, dict) or set(content) != {"title", "nodes"}:
            _fail("invalid")
        title = _title(content["title"])
        nodes = _nodes(content["nodes"], stored=True)
        normalized = {"title": title, "nodes": nodes}
        encoded = _canonical(normalized)
        if encoded.decode("utf-8") != raw or hashlib.sha256(encoded).hexdigest() != digest:
            _fail("invalid")
        expected_refs = {node["input_version_id"] for node in nodes}
        if expected_refs != ref_map.pop(identifier, set()) or len(expected_refs) != len(nodes):
            _fail("invalid")
        for node in nodes:
            input_row = input_map.get(node["input_version_id"])
            if (input_row is None or input_row != (
                    node["task_id"], node["task_incarnation"], scope_map[scope_id][2],
                    node["task_revision"], node["agent_id"], node["agent_incarnation"])):
                _fail("invalid")
        revisions[scope_id].append(revision)
    if ref_map or any(values != list(range(1, scope_map[scope_id][3] + 1)) for scope_id, values in revisions.items()):
        _fail("invalid")
    charged_scopes = [list(row[:4]) + [MAX_SCOPE_VERSIONS, row[5], "0" * 32] for row in scopes]
    return [charged_scopes, [list(row) for row in versions], [list(row) for row in refs]]


def publish_owner_plan(data_dir: Path, project_id: str, title: object, nodes: object, *,
                       expected_project_revision: int, expected_plan_revision: int) -> dict:
    """Publish one owner plan version after exact current authority checks."""
    from agent_registry import AgentRegistryError, _canonical_agent_records
    from project_context import validate_project_context_connection

    if (not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None
            or type(expected_project_revision) is not int or expected_project_revision < 1
            or type(expected_plan_revision) is not int or not 0 <= expected_plan_revision <= MAX_SCOPE_VERSIONS):
        _fail("request_invalid")
    requested = normalize_owner_plan(title, nodes)
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard, immediate=True):
                validate_project_context_connection(connection, require_available=False)
                project = ProjectRepository(connection).get(project_id)
                if project.revision != expected_project_revision or project.document["status"] != "active":
                    _fail("project_changed")
                project_row = connection.execute(
                    "SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (project_id,),
                ).fetchone()
                incarnation = project_row[0] if project_row else None
                context = connection.execute(
                    "SELECT id FROM mentat_project_context_scopes WHERE project_id=? AND retired_at IS NULL",
                    (project_id,),
                ).fetchone()
                if (not isinstance(incarnation, str) or _HEX32.fullmatch(incarnation) is None
                        or context is None):
                    _fail("context_unavailable")
                context_id = context[0]
                existing = connection.execute(
                    "SELECT id,head_revision,context_scope_id FROM mentat_plan_scopes "
                    "WHERE project_id=? AND retired_at IS NULL", (project_id,),
                ).fetchone()
                if (existing[1] if existing else 0) != expected_plan_revision:
                    _fail("revision_conflict")
                if expected_plan_revision >= MAX_SCOPE_VERSIONS:
                    _fail("capacity")
                if existing and existing[2] != context_id:
                    _fail("context_changed")
                if (connection.execute("SELECT COUNT(*) FROM mentat_plan_versions").fetchone()[0] >= MAX_VERSIONS
                        or not existing and connection.execute("SELECT COUNT(*) FROM mentat_plan_scopes").fetchone()[0] >= MAX_SCOPES):
                    _fail("capacity")
                try:
                    records = _canonical_agent_records(connection, supported_runtime_types=("hermes", "codex", "vercel"))
                except AgentRegistryError:
                    _fail("agent_unavailable")
                agents = {record.agent.id: record for record in records}
                stored = []
                for node in requested["nodes"]:
                    task_id, agent_id, input_id = node["task_id"], node["agent_id"], node["input_version_id"]
                    task = TaskRepository(connection).get(task_id)
                    if (task.revision != node["expected_task_revision"] or task.document.get("project_id") != project_id
                            or task.document.get("assigned_agent_id") != agent_id):
                        _fail("task_changed")
                    identity = connection.execute(
                        "SELECT input_incarnation FROM mentat_tasks WHERE id=?", (task_id,),
                    ).fetchone()[0]
                    record = agents.get(agent_id)
                    if record is None:
                        _fail("agent_unavailable")
                    agent_row = connection.execute(
                        "SELECT context_incarnation FROM mentat_agents WHERE id=?", (agent_id,),
                    ).fetchone()
                    agent_identity = agent_row[0] if agent_row else None
                    input_row = connection.execute(
                        "SELECT s.task_id,s.task_incarnation,s.project_scope_id,s.revision,s.retired_at,"
                        "v.revision,v.task_revision,v.agent_id,v.agent_incarnation,v.context_id,v.grant_revision,v.binding_digest "
                        "FROM mentat_task_input_versions v JOIN mentat_task_input_scopes s ON s.id=v.scope_id "
                        "WHERE v.id=?", (input_id,),
                    ).fetchone()
                    if (input_row is None or input_row[0] != task_id or input_row[1] != identity
                            or input_row[2] != context_id or input_row[4] is not None
                            or input_row[3] != input_row[5] or input_row[6] != task.revision
                            or input_row[7] != agent_id or input_row[8] != agent_identity):
                        _fail("input_changed")
                    grant = connection.execute(
                        "SELECT agent_incarnation,context_id,revision,state FROM mentat_project_context_grants "
                        "WHERE scope_id=? AND agent_id=?", (context_id, agent_id),
                    ).fetchone()
                    if (grant is None or tuple(grant) != (agent_identity, input_row[9], input_row[10], "active")):
                        _fail("grant_changed")
                    binding = connection.execute(
                        "SELECT * FROM agent_runtime_configs WHERE id=?", (record.agent.runtime_config_id,),
                    ).fetchone()
                    digest = hashlib.sha256(_canonical([list(binding), record.revision, sorted(record.agent.capabilities)])).hexdigest() if binding else None
                    if digest != input_row[11]:
                        _fail("agent_changed")
                    stored.append({"task_id": task_id, "task_incarnation": identity,
                                   "task_revision": task.revision, "agent_id": agent_id,
                                   "agent_incarnation": agent_identity, "input_version_id": input_id,
                                   "after": node["after"], "segment": node["segment"],
                                   "max_attempts": node["max_attempts"],
                                   "max_wall_seconds": node["max_wall_seconds"],
                                   "max_work_units": node["max_work_units"]})
                content = {"title": requested["title"], "nodes": stored}
                encoded = _canonical(content)
                if len(encoded) > MAX_CONTENT_BYTES:
                    _fail("capacity")
                now = time.time()
                scope_id = existing[0] if existing else f"plan_scope_{uuid.uuid4().hex}"
                version_id = f"plan_version_{uuid.uuid4().hex}"
                revision = expected_plan_revision + 1
                if existing:
                    connection.execute("UPDATE mentat_plan_scopes SET head_revision=? WHERE id=?", (revision, scope_id))
                else:
                    connection.execute("INSERT INTO mentat_plan_scopes VALUES(?,?,?,?,?,?,NULL)",
                                       (scope_id, project_id, incarnation, context_id, revision, now))
                connection.execute("INSERT INTO mentat_plan_versions VALUES(?,?,?,?,?,?,?,?,?)",
                                   (version_id, scope_id, revision, project.revision, 1, encoded.decode("utf-8"),
                                    hashlib.sha256(encoded).hexdigest(), "owner_edit", now))
                connection.executemany("INSERT INTO mentat_plan_input_refs VALUES(?,?)",
                                       [(version_id, node["input_version_id"]) for node in stored])
                validate_project_context_connection(connection, require_available=False)
                return {"id": version_id, "revision": revision, "project_id": project_id,
                        "status": "unapproved"}


def read_project_plan(data_dir: Path, project_id: str) -> dict:
    """Read safe current plan and bounded version metadata without private incarnations."""
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
                scope = connection.execute(
                    "SELECT id,head_revision FROM mentat_plan_scopes WHERE project_id=? "
                    "AND project_incarnation=? AND retired_at IS NULL", (project_id, incarnation),
                ).fetchone()
                versions = []
                if scope:
                    for identifier, revision, raw, created in connection.execute(
                        "SELECT id,revision,content_json,created_at FROM mentat_plan_versions "
                        "WHERE scope_id=? ORDER BY revision DESC LIMIT ?", (scope[0], MAX_SCOPE_VERSIONS),
                    ):
                        content = json.loads(raw)
                        versions.append({"id": identifier, "revision": revision, "title": content["title"],
                                         "node_count": len(content["nodes"]), "created_at": created})
                    current_row = connection.execute(
                        "SELECT content_json,project_revision FROM mentat_plan_versions WHERE scope_id=? AND revision=?",
                        (scope[0], scope[1]),
                    ).fetchone()
                    current = json.loads(current_row[0])
                    dependency_comparison = _dependency_comparison(connection, current)
                    stale_reasons = _stale_reasons(connection, project_id, project.document["status"],
                                                   project.revision, current_row[1],
                                                   connection.execute("SELECT context_scope_id FROM mentat_plan_scopes WHERE id=?", (scope[0],)).fetchone()[0], current,
                                                   dependency_comparison)
                    current["nodes"] = [{key: value for key, value in node.items()
                                         if key not in {"task_incarnation", "agent_incarnation"}}
                                        for node in current["nodes"]]
                else:
                    current = None
                    stale_reasons = []
                    dependency_comparison = {"missing_from_plan": [], "additional_in_plan": [],
                                             "missing_count": 0, "additional_count": 0, "truncated": False}
                return {"project": {"id": project_id, "name": project.document["name"],
                                    "revision": project.revision, "status": project.document["status"]},
                        "plan_revision": scope[1] if scope else 0, "current": current,
                        "versions": versions, "stale_reasons": stale_reasons,
                        "dependency_comparison": dependency_comparison,
                        "execution_available": False}


def read_plan_version(data_dir: Path, project_id: str, version_id: str) -> dict:
    """Read one immutable version of the current Project incarnation only."""
    from project_context import validate_project_context_connection
    if (not isinstance(project_id, str) or _PROJECT.fullmatch(project_id) is None
            or not isinstance(version_id, str) or _VERSION.fullmatch(version_id) is None):
        _fail("request_invalid")
    root = Path(data_dir)
    with private_state_lock(root):
        with _open_repository_database(root) as (connection, guard):
            with _guarded_transaction(connection, guard):
                validate_project_context_connection(connection, require_available=False)
                ProjectRepository(connection).get(project_id)
                row = connection.execute(
                    "SELECT v.revision,v.project_revision,v.content_json,v.created_at,s.head_revision "
                    "FROM mentat_plan_versions v JOIN mentat_plan_scopes s ON s.id=v.scope_id "
                    "JOIN mentat_projects p ON p.id=s.project_id "
                    "AND p.deliverable_incarnation=s.project_incarnation "
                    "WHERE v.id=? AND s.project_id=? AND s.retired_at IS NULL",
                    (version_id, project_id),
                ).fetchone()
                if row is None:
                    _fail("version_unavailable")
                content = json.loads(row[2])
                nodes = []
                for node in content["nodes"]:
                    task = connection.execute(
                        "SELECT title,revision,project_id,input_incarnation FROM mentat_tasks WHERE id=?",
                        (node["task_id"],),
                    ).fetchone()
                    agent = connection.execute(
                        "SELECT name,context_incarnation FROM mentat_agents WHERE id=?",
                        (node["agent_id"],),
                    ).fetchone()
                    task_state = "unavailable" if task is None else "current" if (
                        task[1] == node["task_revision"] and task[2] == project_id
                        and task[3] == node["task_incarnation"]) else "changed"
                    agent_state = "unavailable" if agent is None else "current" if (
                        agent[1] == node["agent_incarnation"]) else "changed"
                    nodes.append({**{key: value for key, value in node.items()
                                     if key not in {"task_incarnation", "agent_incarnation"}},
                                  "task_state": task_state, "task_title": task[0] if task_state == "current" else None,
                                  "agent_state": agent_state, "agent_name": agent[0] if agent_state == "current" else None})
                return {"id": version_id, "project_id": project_id,
                        "revision": row[0], "project_revision": row[1],
                        "title": content["title"], "nodes": nodes,
                        "created_at": row[3], "current": row[0] == row[4],
                        "status": "unapproved"}
