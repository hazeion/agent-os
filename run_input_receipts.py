"""Immutable private Run-input evidence. No adapter or browser admission lives here."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3


MAX_RUN_INPUT_RECEIPTS = 128
MAX_RUN_INPUT_FILES = 8
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z")
_INPUT = re.compile(r"task_input_[0-9a-f]{32}\Z")


class RunInputReceiptError(ValueError):
    pass


def _fail() -> None:
    raise RunInputReceiptError("run_input.invalid")


def _digest(value: object) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _fail()
    return hashlib.sha256(raw).hexdigest()


def validate_run_input_connection(connection: sqlite3.Connection, *, require_available: bool = True) -> list[list]:
    """Validate bounded receipt provenance and exact ordered retained file bytes.

    This checks evidence already present in SQLite; it never qualifies a
    runtime, approves a plan, or creates a receipt.
    """
    receipts = connection.execute(
        "SELECT run_id,input_id,task_scope_id,task_id,task_incarnation,task_revision,"
        "project_scope_id,project_id,agent_id,agent_incarnation,runtime_type,runtime_config_id,context_id,context_revision,"
        "grant_revision,runtime_binding_digest,input_binding_digest,capabilities_digest,qualification_digest,"
        "approval_digest,objective_digest,allowed_tools_digest,limits_digest,manifest_digest,created_at "
        "FROM mentat_run_input_receipts ORDER BY run_id"
    ).fetchmany(MAX_RUN_INPUT_RECEIPTS + 1)
    files = connection.execute(
        "SELECT run_id,ordinal,attachment_id,blob_id,sha256,byte_size,kind,mime_type "
        "FROM mentat_run_input_files ORDER BY run_id,ordinal"
    ).fetchmany(MAX_RUN_INPUT_RECEIPTS * MAX_RUN_INPUT_FILES + 1)
    if len(receipts) > MAX_RUN_INPUT_RECEIPTS or len(files) > MAX_RUN_INPUT_RECEIPTS * MAX_RUN_INPUT_FILES:
        raise RunInputReceiptError("run_input.capacity")
    file_groups: dict[str, list[tuple]] = {str(row[0]): [] for row in receipts}
    for row in files:
        identifier = str(row[0])
        if identifier not in file_groups or type(row[1]) is not int or row[1] != len(file_groups[identifier]):
            _fail()
        if (not isinstance(row[2], str) or not isinstance(row[3], str)
                or not isinstance(row[4], str) or _SHA256.fullmatch(row[4]) is None
                or type(row[5]) is not int or row[5] < 0
                or row[6] not in {"text", "image"} or not isinstance(row[7], str)):
            _fail()
        file_groups[identifier].append(tuple(row))
    for row in receipts:
        (run_id, input_id, scope_id, task_id, task_incarnation, task_revision,
         project_scope_id, project_id, agent_id, agent_incarnation, runtime_type, runtime_config_id,
         context_id, context_revision,
         grant_revision, binding, input_binding, capabilities, qualification, approval, objective, tools,
         limits, manifest, created_at) = tuple(row)
        if (not isinstance(run_id, str) or _RUN.fullmatch(run_id) is None
                or not isinstance(input_id, str) or _INPUT.fullmatch(input_id) is None
                or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None
                       for value in (task_incarnation, agent_incarnation))
                or any(type(value) is not int or value < 1 for value in
                       (task_revision, context_revision, grant_revision))
                or any(not isinstance(value, str) or _SHA256.fullmatch(value) is None
                       for value in (binding, input_binding, capabilities, qualification, approval,
                                     objective, tools, limits, manifest))
                or type(created_at) not in (int, float) or not math.isfinite(created_at) or created_at <= 0):
            _fail()
        run = connection.execute(
            "SELECT source,task_id,task_revision,agent_id,runtime_type,runtime_config_id,"
            "runtime_binding_digest,capabilities_json "
            "FROM mentat_runs WHERE id=?", (run_id,),
        ).fetchone()
        selected = connection.execute(
            "SELECT v.scope_id,v.task_revision,v.agent_id,v.agent_incarnation,v.context_id,"
            "v.grant_revision,v.binding_digest,v.instructions,s.task_id,s.task_incarnation,"
            "s.project_scope_id,ps.project_id,c.revision,c.brief "
            "FROM mentat_task_input_versions v JOIN mentat_task_input_scopes s ON s.id=v.scope_id "
            "JOIN mentat_project_context_scopes ps ON ps.id=s.project_scope_id "
            "JOIN mentat_project_context_versions c ON c.id=v.context_id WHERE v.id=?", (input_id,),
        ).fetchone()
        try:
            run_capabilities_digest = _digest(json.loads(run[7])) if run is not None else None
        except (TypeError, ValueError, json.JSONDecodeError):
            _fail()
        if (run is None or selected is None or tuple(run[:7]) !=
                ("task_dispatch", task_id, task_revision, agent_id,
                 runtime_type, runtime_config_id, binding)
                or run_capabilities_digest != capabilities
                or tuple(selected[:7]) != (scope_id, task_revision, agent_id,
                                           agent_incarnation, context_id, grant_revision, input_binding)
                or tuple(selected[8:13]) != (task_id, task_incarnation, project_scope_id,
                                              project_id, context_revision)):
            _fail()
        ordered = connection.execute(
            "SELECT attachment_id FROM mentat_task_input_files WHERE input_id=? ORDER BY ordinal", (input_id,),
        ).fetchall()
        retained = file_groups[run_id]
        if len(ordered) != len(retained) or [str(item[0]) for item in ordered] != [item[2] for item in retained]:
            _fail()
        for item in retained:
            attachment = connection.execute(
                "SELECT a.blob_id,a.byte_size,a.kind,a.mime_type,a.state,b.sha256,b.byte_size,b.state "
                "FROM attachments a JOIN blobs b ON b.id=a.blob_id WHERE a.id=?", (item[2],),
            ).fetchone()
            if (attachment is None or tuple(attachment[:4]) != (item[3], item[5], item[6], item[7])
                    or attachment[5] != item[4] or attachment[6] != item[5]
                    or require_available and (attachment[4] != "attached" or attachment[7] != "ready")):
                _fail()
        expected_manifest = _digest([input_id, context_id, context_revision, selected[13],
                                     selected[7], [list(item[2:]) for item in retained]])
        if expected_manifest != manifest:
            _fail()
    return [[list(row) for row in receipts], [list(row) for row in files]]
