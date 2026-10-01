"""Historical Project proposal Run-input evidence; no admission or dispatch API."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3


MAX_PROJECT_PROPOSAL_INPUT_RECEIPTS = 128
MAX_PROJECT_PROPOSAL_INPUT_FILES = 8
_RUN = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z")
_INPUT = re.compile(r"project_input_[0-9a-f]{32}\Z")
_INCARNATION = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class ProjectProposalInputReceiptError(ValueError):
    pass


def _fail() -> None:
    raise ProjectProposalInputReceiptError("project_proposal_input.invalid")


def _digest(value: object) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _fail()
    return hashlib.sha256(encoded).hexdigest()


def validate_project_proposal_input_connection(
    connection: sqlite3.Connection, *, require_available: bool = True,
) -> list[list]:
    """Validate retained evidence, never current authorization or qualification.

    Schema 41 keeps proposal Run insertion closed. This validator prepares the
    exact backup/restore boundary for the later separately reviewed admission
    capability; it does not permit a proposal Run to be created.
    """
    receipts = connection.execute(
        "SELECT run_id,input_id,project_id,project_incarnation,project_revision,"
        "lead_role_id,lead_revision,agent_id,agent_incarnation,agent_revision,"
        "runtime_type,runtime_config_id,runtime_binding_digest,context_id,"
        "context_revision,grant_revision,capabilities_digest,qualification_digest,"
        "authorization_digest,operations_digest,limits_digest,manifest_digest,created_at "
        "FROM mentat_project_proposal_input_receipts ORDER BY run_id"
    ).fetchmany(MAX_PROJECT_PROPOSAL_INPUT_RECEIPTS + 1)
    files = connection.execute(
        "SELECT run_id,ordinal,attachment_id,blob_id,sha256,byte_size,kind,mime_type "
        "FROM mentat_project_proposal_input_files ORDER BY run_id,ordinal"
    ).fetchmany(MAX_PROJECT_PROPOSAL_INPUT_RECEIPTS * MAX_PROJECT_PROPOSAL_INPUT_FILES + 1)
    if (len(receipts) > MAX_PROJECT_PROPOSAL_INPUT_RECEIPTS
            or len(files) > MAX_PROJECT_PROPOSAL_INPUT_RECEIPTS * MAX_PROJECT_PROPOSAL_INPUT_FILES):
        raise ProjectProposalInputReceiptError("project_proposal_input.capacity")
    by_run: dict[str, list[tuple]] = {str(row[0]): [] for row in receipts}
    for row in files:
        run_id, ordinal, attachment_id, blob_id, sha256, byte_size, kind, mime_type = tuple(row)
        if (run_id not in by_run or type(ordinal) is not int
                or ordinal != len(by_run[run_id]) or ordinal >= MAX_PROJECT_PROPOSAL_INPUT_FILES
                or not isinstance(attachment_id, str) or not isinstance(blob_id, str)
                or not isinstance(sha256, str) or _HEX64.fullmatch(sha256) is None
                or type(byte_size) is not int or byte_size < 0
                or kind not in ("text", "image") or not isinstance(mime_type, str)):
            _fail()
        by_run[run_id].append(tuple(row))

    for row in receipts:
        (run_id, input_id, project_id, incarnation, project_revision,
         lead_role_id, lead_revision, agent_id, agent_incarnation, agent_revision,
         runtime_type, runtime_config_id, binding, context_id, context_revision,
         grant_revision, capabilities, qualification, authorization, operations,
         limits, manifest, created_at) = tuple(row)
        if (not isinstance(run_id, str) or _RUN.fullmatch(run_id) is None
                or not isinstance(input_id, str) or _INPUT.fullmatch(input_id) is None
                or not isinstance(project_id, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}", project_id) is None
                or not isinstance(incarnation, str) or _INCARNATION.fullmatch(incarnation) is None
                or not isinstance(agent_incarnation, str)
                or _INCARNATION.fullmatch(agent_incarnation) is None
                or any(type(value) is not int or value < 1 for value in
                       (project_revision, lead_revision, agent_revision,
                        context_revision, grant_revision))
                or any(not isinstance(value, str) or _HEX64.fullmatch(value) is None
                       for value in (binding, capabilities, qualification,
                                     authorization, operations, limits, manifest))
                or type(created_at) not in (int, float) or not math.isfinite(created_at)
                or created_at <= 0):
            _fail()
        run = connection.execute(
            "SELECT source,task_id,task_revision,agent_id,runtime_type,"
            "runtime_config_id,runtime_binding_digest,capabilities_json "
            "FROM mentat_runs WHERE id=?", (run_id,),
        ).fetchone()
        selected = connection.execute(
            "SELECT project_id,project_incarnation,project_revision,lead_role_id,"
            "lead_revision,agent_id,agent_incarnation,agent_revision,binding_digest,"
            "context_id,grant_revision,instructions,created_at "
            "FROM mentat_project_planning_input_versions WHERE id=?", (input_id,),
        ).fetchone()
        context = connection.execute(
            "SELECT revision,brief FROM mentat_project_context_versions WHERE id=?",
            (context_id,),
        ).fetchone()
        try:
            run_capabilities = _digest(json.loads(run[7])) if run is not None else None
        except (TypeError, ValueError, json.JSONDecodeError):
            _fail()
        if (run is None or selected is None or context is None
                or tuple(run[:7]) != ("project_proposal", None, None, agent_id,
                                      runtime_type, runtime_config_id, binding)
                or run_capabilities != capabilities
                or tuple(selected[:11]) != (project_id, incarnation, project_revision,
                                            lead_role_id, lead_revision, agent_id,
                                            agent_incarnation, agent_revision, binding,
                                            context_id, grant_revision)
                or context[0] != context_revision or created_at < selected[12]):
            _fail()
        ordered = connection.execute(
            "SELECT attachment_id,blob_id,sha256,byte_size,kind,mime_type "
            "FROM mentat_project_planning_input_files WHERE input_id=? ORDER BY ordinal",
            (input_id,),
        ).fetchall()
        retained = by_run[run_id]
        if [tuple(item) for item in ordered] != [item[2:] for item in retained]:
            _fail()
        for item in retained:
            attachment = connection.execute(
                "SELECT a.blob_id,a.byte_size,a.kind,a.mime_type,a.state,"
                "b.sha256,b.byte_size,b.state FROM attachments a "
                "JOIN blobs b ON b.id=a.blob_id WHERE a.id=?", (item[2],),
            ).fetchone()
            if (attachment is None or tuple(attachment[:4]) !=
                    (item[3], item[5], item[6], item[7])
                    or attachment[5] != item[4] or attachment[6] != item[5]
                    or require_available and (attachment[4] != "attached"
                                              or attachment[7] != "ready")):
                _fail()
        expected_manifest = _digest([
            run_id, input_id, project_id, incarnation, project_revision,
            lead_role_id, lead_revision, agent_id, agent_incarnation,
            agent_revision, runtime_type, runtime_config_id, binding,
            context_id, context_revision, grant_revision, capabilities,
            qualification, authorization, operations, limits, created_at,
            context[1], selected[11], [list(item[2:]) for item in retained],
        ])
        if manifest != expected_manifest:
            _fail()
    return [[list(row) for row in receipts], [list(row) for row in files]]
