"""Private durable proposal-worker evidence and one-call submission fencing.

No function creates a Run, grants inputs, qualifies an adapter or calls a
provider. Live admission stays guarded. Future broker callers must use the
guarded private transaction and their separately qualified credential boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
import hashlib
import hmac
import json
import math
import re
import secrets
import sqlite3
import time
import uuid

MAX_GENERATIONS = 128
MAX_RESPONSE_BYTES = 32 * 1024
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z")
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}\Z")
_POLICY_FIELDS = frozenset({"format", "inference_calls", "max_output_tokens", "max_response_bytes",
                            "max_request_bytes", "wall_seconds", "memory_bytes", "processes", "cpu_percent"})


class WorkerJournalError(RuntimeError):
    pass


def _fail(code: str = "invalid") -> None:
    raise WorkerJournalError("worker_journal." + code)


def _encoded(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, UnicodeError):
        _fail()


def _digest(value: object) -> str:
    try:
        return hashlib.sha256(_encoded(value).encode("utf-8")).hexdigest()
    except UnicodeError:
        _fail()


def normalize_policy(value: object) -> str:
    if not isinstance(value, dict) or set(value) != _POLICY_FIELDS:
        _fail("policy")
    if type(value["format"]) is not int or value["format"] != 1 or type(value["inference_calls"]) is not int or value["inference_calls"] != 1:
        _fail("policy")
    ceilings = {"max_output_tokens": 8192, "max_response_bytes": MAX_RESPONSE_BYTES,
                "max_request_bytes": 16 * 1024 * 1024,
                "wall_seconds": 3600, "memory_bytes": 512 * 1024 * 1024,
                "processes": 32, "cpu_percent": 100}
    if any(type(value[key]) is not int or not 0 < value[key] <= ceiling for key, ceiling in ceilings.items()):
        _fail("policy")
    return _encoded(value)


def _snapshot(value: object) -> str:
    if not isinstance(value, dict) or set(value) != {"provider", "model", "supports_vision"}:
        _fail("snapshot")
    if type(value["supports_vision"]) is not bool:
        _fail("snapshot")
    for key in ("provider", "model"):
        text = value[key]
        if not isinstance(text, str) or _LABEL.fullmatch(text) is None or "://" in text:
            _fail("snapshot")
    return _encoded(value)


def _timestamp(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and 0 < value < 1e12


def _transaction(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        _fail("transaction_required")


def _atomic_mutation(function):
    @wraps(function)
    def guarded(connection, *args, **kwargs):
        _transaction(connection)
        savepoint = "worker_journal_" + uuid.uuid4().hex
        connection.execute("SAVEPOINT " + savepoint)
        try:
            result = function(connection, *args, **kwargs)
        except BaseException:
            connection.execute("ROLLBACK TO " + savepoint)
            connection.execute("RELEASE " + savepoint)
            raise
        connection.execute("RELEASE " + savepoint)
        return result
    return guarded


def _epoch(connection: sqlite3.Connection) -> bytes:
    row = connection.execute("SELECT approval_epoch FROM mentat_project_context_access_state WHERE singleton=1").fetchone()
    if row is None or not isinstance(row[0], bytes) or len(row[0]) != 32 or row[0] == bytes(32):
        _fail("unavailable")
    return row[0]


def validate_worker_journal_connection(connection: sqlite3.Connection) -> list[list]:
    """Historical graph validation, never current execution permission."""
    claims = connection.execute("SELECT * FROM mentat_project_worker_generations ORDER BY run_id").fetchmany(MAX_GENERATIONS + 1)
    calls = connection.execute("SELECT * FROM mentat_project_worker_calls ORDER BY run_id").fetchmany(MAX_GENERATIONS + 1)
    if len(claims) > MAX_GENERATIONS or len(calls) > MAX_GENERATIONS:
        _fail("capacity")
    generations = {}
    metadata = []
    for row in claims:
        run_id, source, generation, epoch, manifest, binding, policy_json, policy_digest, snapshot_json, claim_digest, created = tuple(row)
        if (not isinstance(run_id, str) or _RUN.fullmatch(run_id) is None or source != "project_proposal"
                or not isinstance(generation, str) or _HEX32.fullmatch(generation) is None
                or not isinstance(epoch, bytes) or len(epoch) != 32 or not _timestamp(created)
                or any(not isinstance(value, str) or _HEX64.fullmatch(value) is None
                       for value in (manifest, binding, policy_digest, claim_digest))):
            _fail()
        try:
            policy = json.loads(policy_json)
            snapshot = json.loads(snapshot_json)
        except (TypeError, ValueError):
            _fail()
        if normalize_policy(policy) != policy_json or _snapshot(snapshot) != snapshot_json or _digest(policy) != policy_digest:
            _fail()
        selected = connection.execute("SELECT manifest_digest,runtime_binding_digest,limits_digest,created_at "
                                      "FROM mentat_project_proposal_input_receipts WHERE run_id=?", (run_id,)).fetchone()
        run = connection.execute("SELECT source,runtime_binding_digest FROM mentat_runs WHERE id=?", (run_id,)).fetchone()
        if (selected is None or run is None or tuple(selected[:3]) != (manifest, binding, policy_digest)
                or tuple(run) != (source, binding) or created < selected[3]
                or _digest([run_id, source, generation, epoch.hex(), manifest, binding, policy, snapshot, created]) != claim_digest):
            _fail()
        generations[run_id] = (generation, policy["max_response_bytes"], created)
        metadata.append([*list(row[:3]), epoch.hex(), *list(row[4:])])
    call_metadata = []
    for row in calls:
        call_id, run_id, generation, request, token_hash, debit, state, disposition, text, result, created, settled = tuple(row)
        owner = generations.get(run_id)
        if (owner is None or owner[0] != generation or _HEX32.fullmatch(str(call_id)) is None
                or _HEX64.fullmatch(str(request)) is None or _HEX64.fullmatch(str(token_hash)) is None
                or type(debit) is not int or debit != 1
                or not _timestamp(created) or created < owner[2] or state not in {"reserved", "unknown", "succeeded", "failed"}):
            _fail()
        if state in {"reserved", "unknown"}:
            if any(value is not None for value in (disposition, text, result, settled)):
                _fail()
        elif not _timestamp(settled) or settled < created:
            _fail()
        elif state == "succeeded":
            if disposition is not None or _valid_text(text, owner[1]) is not True or result != _digest(["succeeded", text]):
                _fail()
        elif disposition not in {"rejected", "non_text", "oversized"} or text is not None or result != _digest(["failed", disposition]):
            _fail()
        # Reserve terminal cache/accounting representation now. A response or
        # late settlement cannot make an admitted unknown graph unbackuppable
        # merely because another owner write consumed its remaining budget.
        charged = list(row)
        charged[6:10] = ["succeeded", "oversized", "x" * (owner[1] * 2), "0" * 64]
        charged[11] = "999999999999.9999999999"
        call_metadata.append(charged)
    return [metadata, call_metadata]


def _validate_shared_graph(connection: sqlite3.Connection) -> None:
    from project_context import validate_project_context_connection
    validate_project_context_connection(connection)


def _dormant_proposal_ids(connection: sqlite3.Connection) -> frozenset[str]:
    """Exact historical fixture shape, never admitted Run/source authority."""
    version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    if version < 43:
        return frozenset()
    _validate_shared_graph(connection)
    runs = {str(row[0]) for row in connection.execute("SELECT id FROM mentat_runs WHERE source='project_proposal'")}
    claims = {str(row[0]) for row in connection.execute("SELECT run_id FROM mentat_project_worker_generations")}
    if runs != claims or len(runs) > MAX_GENERATIONS:
        _fail()
    # This slice records no execution handoff. Accept only exact dormant Run
    # shape, not arbitrary planted live/terminal proposal state or runtime refs.
    for row in connection.execute("SELECT * FROM mentat_runs WHERE source='project_proposal'"):
        if (row["status"] != "reserved" or row["dispatch_state"] != "reserved"
                or row["details_json"] != "{}" or row["state_revision"] != 1
                or row["partial"] != 0 or row["terminal_finalized"] != 0
                or row["first_retained_sequence"] != 1
                or any(row[name] != 0 for name in (
                    "runtime_event_cursor", "last_removed_sequence", "last_event_sequence",
                    "timeline_truncated", "discarded_event_count", "discarded_content_bytes"))
                or any(row[name] is not None for name in (
                    "task_id", "task_revision", "task_snapshot_json", "conversation_id", "turn_id",
                    "runtime_run_ref", "started_at", "completed_at", "truncation_reason",
                    "reconcile_lease_owner", "reconcile_lease_until", "retry_of_run_id", "resume_of_run_id",
                    "capacity_scope_digest", "admitted_capacity_limit", "agent_revision", "runtime_config_revision",
                    "execution_config_json", "execution_config_digest", "runtime_execution_json", "runtime_execution_digest"))):
            _fail()
        identifier = row["id"]
        for table, column in (("mentat_agent_events", "run_id"), ("mentat_dispatch_reservations", "run_id"),
                              ("mentat_task_dispatch_heads", "run_id"), ("run_attachments", "run_id")):
            if connection.execute(f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (identifier,)).fetchone() is not None:
                _fail()
        attention = connection.execute("SELECT item_id,revision FROM mentat_run_attention WHERE run_id=?", (identifier,)).fetchall()
        if len(attention) != 1 or tuple(attention[0]) != (None, 0):
            _fail()
    return frozenset(runs)


def archival_proposal_ids(connection: sqlite3.Connection) -> frozenset[str]:
    """Private backup eligibility remains separately closed for active scopes."""
    identifiers = _dormant_proposal_ids(connection)
    from project_scope_journal import require_archival_scopes
    if connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0] >= 44:
        require_archival_scopes(connection)
    return identifiers


def qualification_proposal_ids(connection: sqlite3.Connection) -> frozenset[str]:
    """Synthetic-only source consistency; grants no archival/live eligibility."""
    return _dormant_proposal_ids(connection)


def _valid_text(value: object, ceiling: int) -> bool:
    if not isinstance(value, str) or len(value) > ceiling or any(ord(char) < 32 and char not in "\t\r\n" for char in value):
        return False
    try:
        return len(value.encode("utf-8")) <= ceiling
    except UnicodeError:
        return False


@_atomic_mutation
def create_generation(connection: sqlite3.Connection, *, run_id: str, generation: str,
                      policy: dict, model_snapshot: dict, now: float | None = None) -> None:
    """Bind retained evidence; this does not create/admit a Run or dispatch."""
    _transaction(connection)
    policy_json, snapshot_json = normalize_policy(policy), _snapshot(model_snapshot)
    if _RUN.fullmatch(str(run_id)) is None or _HEX32.fullmatch(str(generation)) is None:
        _fail()
    created = time.time() if now is None else now
    if not _timestamp(created):
        _fail()
    created = float(created)
    selected = connection.execute("SELECT manifest_digest,runtime_binding_digest,limits_digest,created_at "
                                  "FROM mentat_project_proposal_input_receipts WHERE run_id=?", (run_id,)).fetchone()
    if selected is None or selected[2] != _digest(policy) or created < selected[3]:
        _fail("input_mismatch")
    if connection.execute("SELECT COUNT(*) FROM mentat_project_worker_generations").fetchone()[0] >= MAX_GENERATIONS:
        _fail("capacity")
    epoch = _epoch(connection)
    claim = _digest([run_id, "project_proposal", generation, epoch.hex(), selected[0], selected[1], policy, model_snapshot, created])
    connection.execute("INSERT INTO mentat_project_worker_generations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (run_id, "project_proposal", generation, epoch, selected[0], selected[1],
                        policy_json, selected[2], snapshot_json, claim, created))
    _validate_shared_graph(connection)


def _live_generation(connection: sqlite3.Connection, run_id: str, generation: str) -> tuple:
    """Exact current grant/binding gate; not an adapter qualification claim."""
    original = connection.row_factory
    try:
        return _check_live_generation(connection, run_id, generation)
    except (LookupError, ValueError, RuntimeError, OSError) as exc:
        if isinstance(exc, WorkerJournalError):
            raise
        _fail("fenced")
    finally:
        connection.row_factory = original


def _check_live_generation(connection: sqlite3.Connection, run_id: str, generation: str) -> tuple:
    from agent_registry import _canonical_agent_records
    from project_leads import _binding_digest, _current_context
    from project_repository import ProjectRepository
    row = connection.execute("SELECT * FROM mentat_project_worker_generations WHERE run_id=? AND generation=?",
                             (run_id, generation)).fetchone()
    if row is None or row[3] != _epoch(connection):
        _fail("fenced")
    receipt = connection.execute("SELECT project_id,project_incarnation,project_revision,lead_role_id,lead_revision,"
                                 "agent_id,agent_incarnation,agent_revision,context_id,grant_revision,input_id "
                                 "FROM mentat_project_proposal_input_receipts WHERE run_id=?", (run_id,)).fetchone()
    if receipt is None:
        _fail("fenced")
    project = ProjectRepository(connection).get(receipt[0])
    incarnation = connection.execute("SELECT deliverable_incarnation FROM mentat_projects WHERE id=?", (receipt[0],)).fetchone()
    lead = connection.execute("SELECT id,revision,action FROM mentat_project_lead_versions WHERE project_incarnation=? "
                              "ORDER BY revision DESC LIMIT 1", (receipt[1],)).fetchone()
    head = connection.execute("SELECT id FROM mentat_project_planning_input_versions WHERE project_incarnation=? "
                              "ORDER BY revision DESC LIMIT 1", (receipt[1],)).fetchone()
    context = _current_context(connection, receipt[0])
    records = {item.agent.id: item for item in _canonical_agent_records(connection, supported_runtime_types=("hermes", "codex", "vercel"))}
    agent = records.get(receipt[5])
    identity = connection.execute("SELECT context_incarnation FROM mentat_agents WHERE id=?", (receipt[5],)).fetchone()
    grant = connection.execute("SELECT agent_incarnation,context_id,revision,state FROM mentat_project_context_grants "
                               "WHERE scope_id=? AND agent_id=?", (context[0], receipt[5])).fetchone() if context else None
    if (project.document["status"] != "active" or project.revision != receipt[2]
            or incarnation is None or incarnation[0] != receipt[1]
            or lead is None or tuple(lead) != (receipt[3], receipt[4], "select")
            or head is None or head[0] != receipt[10] or context is None or context[1] != receipt[8]
            or agent is None or agent.revision != receipt[7] or identity is None or identity[0] != receipt[6]
            or _binding_digest(connection, agent) != row[5]
            or grant is None or tuple(grant) != (receipt[6], receipt[8], receipt[9], "active")):
        _fail("fenced")
    return tuple(row)


@dataclass(frozen=True)
class CallReceipt:
    call_id: str
    state: str
    newly_reserved: bool
    response_text: str | None = None
    disposition: str | None = None
    settlement_token: str | None = field(default=None, repr=False)


@_atomic_mutation
def reserve_call(connection: sqlite3.Connection, *, run_id: str, generation: str,
                 request_digest: str, now: float | None = None) -> CallReceipt:
    """Return bookkeeping only, never provider submission permission.

    The caller commits before using newly_reserved evidence. Future live broker
    admission must separately prove exact Run state, qualification, Stop fence
    and generation capability. Historical data plus epoch is not that authority.
    """
    _transaction(connection)
    _validate_shared_graph(connection)
    if _HEX64.fullmatch(str(request_digest)) is None:
        _fail()
    claim = _live_generation(connection, run_id, generation)
    prior = connection.execute("SELECT call_id,generation,request_digest,state,response_text,disposition "
                               "FROM mentat_project_worker_calls WHERE run_id=?", (run_id,)).fetchone()
    if prior is not None:
        if prior[1] != generation or prior[2] != request_digest:
            _fail("conflict")
        return CallReceipt(prior[0], prior[3], False, prior[4], prior[5])
    created = time.time() if now is None else now
    if not _timestamp(created) or created < claim[10]:
        _fail()
    created = float(created)
    call_id = uuid.uuid4().hex
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    connection.execute("INSERT INTO mentat_project_worker_calls VALUES(?,?,?,?,?,1,'reserved',NULL,NULL,NULL,?,NULL)",
                       (call_id, run_id, generation, request_digest, token_hash, created))
    _validate_shared_graph(connection)
    return CallReceipt(call_id, "reserved", True, settlement_token=token)


def _exact_result_owner(connection, call_id, generation, request_digest, settlement_token):
    row = connection.execute("SELECT c.*,g.policy_json FROM mentat_project_worker_calls c "
                             "JOIN mentat_project_worker_generations g ON g.run_id=c.run_id WHERE c.call_id=?", (call_id,)).fetchone()
    if (row is None or row[2] != generation or row[3] != request_digest
            or not isinstance(settlement_token, str) or _HEX64.fullmatch(settlement_token) is None
            or not hmac.compare_digest(row[4], hashlib.sha256(settlement_token.encode("ascii")).hexdigest())):
        _fail("result_owner")
    return row


@_atomic_mutation
def record_submission(connection: sqlite3.Connection, *, call_id: str, generation: str,
                      request_digest: str, settlement_token: str) -> bool:
    """Commit unknown before network send; no submission or grant occurs here."""
    _validate_shared_graph(connection)
    row = _exact_result_owner(connection, call_id, generation, request_digest, settlement_token)
    _live_generation(connection, row[1], generation)
    if row[6] != "reserved":
        return False
    connection.execute("UPDATE mentat_project_worker_calls SET state='unknown' WHERE call_id=?", (call_id,))
    _validate_shared_graph(connection)
    return True


@_atomic_mutation
def settle_call(connection: sqlite3.Connection, *, call_id: str, generation: str,
                request_digest: str, settlement_token: str, response_text: object = None,
                failure: str | None = None, now: float | None = None) -> None:
    """Trusted exact host outcome recording, including fenced historical calls."""
    _transaction(connection)
    _validate_shared_graph(connection)
    row = _exact_result_owner(connection, call_id, generation, request_digest, settlement_token)
    if row[6] == "reserved":
        _fail("not_submitted")
    ceiling = json.loads(row[12])["max_response_bytes"]
    if failure is not None and failure not in {"rejected", "non_text", "oversized"}:
        _fail()
    if failure is None and not _valid_text(response_text, ceiling):
        if isinstance(response_text, str) and len(response_text) > ceiling:
            failure = "oversized"
        elif isinstance(response_text, str):
            try:
                failure = "oversized" if len(response_text.encode("utf-8")) > ceiling else "non_text"
            except UnicodeError:
                failure = "non_text"
        else:
            failure = "non_text"
    state, text = ("failed", None) if failure is not None else ("succeeded", response_text)
    digest = _digest([state, failure if failure is not None else text])
    if row[6] != "unknown":
        if (row[6], row[7], row[8], row[9]) != (state, failure, text, digest):
            _fail("conflict")
        return
    settled = time.time() if now is None else now
    if not _timestamp(settled) or settled < row[10]:
        _fail()
    settled = float(settled)
    connection.execute("UPDATE mentat_project_worker_calls SET state=?,disposition=?,response_text=?,result_digest=?,settled_at=? "
                       "WHERE call_id=? AND state='unknown'", (state, failure, text, digest, settled, call_id))
    _validate_shared_graph(connection)
