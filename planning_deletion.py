"""Verified, project-owned planning deletion.

This module is intentionally narrower than the ordinary Task/Project
repositories.  A planning deletion is a destructive, cross-authority
operation: it first freezes one exact dependency closure, lets the caller stop
active Runs through the fixed runtime boundary, and then removes only that
frozen closure in one SQLite transaction.  It never accepts a browser supplied
closure or performs runtime I/O while holding a database transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import sqlite3
from typing import Iterable

from private_state import private_state_lock
from task_repository import (
    TaskRepository,
    TaskRepositoryConflict,
    TaskRepositoryError,
    TaskRepositoryUnavailable,
    _guarded_transaction,
    _open_repository_database,
)
from project_repository import ProjectRepository


TASK_ID_MAX = 160
PROJECT_ID_MAX = 80
MAX_RECEIPTS = 256
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "stopped", "interrupted"})
ACTIVE_STATUSES = frozenset({
    "reserved", "queued", "submitting", "starting", "running", "cancelling",
    "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown",
})


class PlanningDeletionError(RuntimeError):
    """A bounded, public-safe deletion failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DeletionCounts:
    projects: int
    tasks: int
    conversations: int
    runs: int
    artifacts: int

    def public(self) -> dict[str, int]:
        return {
            "projects": self.projects,
            "tasks": self.tasks,
            "conversations": self.conversations,
            "runs": self.runs,
            "artifacts": self.artifacts,
        }


@dataclass(frozen=True)
class DeletionPlan:
    target_kind: str
    target_id: str
    confirmation_id: str
    target_digest: str
    closure_digest: str
    snapshot: dict
    counts: DeletionCounts
    active_run_ids: tuple[str, ...]
    run_ids: tuple[str, ...]
    conversation_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    project_ids: tuple[str, ...]
    artifact_binding_ids: tuple[str, ...]
    attachment_ids: tuple[str, ...]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _placeholders(values: Iterable[str]) -> tuple[str, tuple[str, ...]]:
    values_tuple = tuple(values)
    if not values_tuple:
        return "(NULL)", ()
    return "(" + ",".join("?" for _ in values_tuple) + ")", values_tuple


def _validate_target(kind: object, identifier: object) -> tuple[str, str]:
    if kind not in {"task", "project"} or not isinstance(identifier, str):
        raise PlanningDeletionError("planning.deletion_invalid")
    maximum = TASK_ID_MAX if kind == "task" else PROJECT_ID_MAX
    if not identifier or len(identifier) > maximum:
        raise PlanningDeletionError("planning.deletion_invalid")
    import re
    expression = r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}" if kind == "task" else r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}"
    if re.fullmatch(expression, identifier) is None:
        raise PlanningDeletionError("planning.deletion_invalid")
    return str(kind), identifier


def _rows(connection: sqlite3.Connection, query: str, args: tuple = ()) -> list[sqlite3.Row]:
    return list(connection.execute(query, args).fetchall())


def _require_authority(connection: sqlite3.Connection) -> None:
    try:
        TaskRepository(connection).authority_receipt(required=True)
        ProjectRepository(connection).authority_receipt(required=True)
    except Exception as exc:
        # ProjectRepository has a distinct exception hierarchy.  The public
        # caller must not distinguish an authority fault from a private layout.
        raise PlanningDeletionError("planning.deletion_unavailable") from exc


def _closure(connection: sqlite3.Connection, target_kind: str, target_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    tasks = _rows(connection, "SELECT id, project_id, revision FROM mentat_tasks ORDER BY id")
    task_ids = {str(row["id"]) for row in tasks}
    projects = _rows(connection, "SELECT id, revision FROM mentat_projects ORDER BY id")
    project_ids = {str(row["id"]) for row in projects}
    if target_kind == "task":
        if target_id not in task_ids:
            raise PlanningDeletionError("planning.deletion_not_found")
        roots = {target_id}
        selected_projects: set[str] = set()
    else:
        if target_id not in project_ids:
            raise PlanningDeletionError("planning.deletion_not_found")
        roots = {str(row["id"]) for row in tasks if str(row["project_id"]) == target_id}
        selected_projects = {target_id}

    edges = _rows(connection, "SELECT task_id, dependency_task_id FROM mentat_task_dependencies ORDER BY task_id, ordinal")
    reverse: dict[str, set[str]] = {identifier: set() for identifier in task_ids}
    forward: dict[str, set[str]] = {identifier: set() for identifier in task_ids}
    for edge in edges:
        child, parent = str(edge["task_id"]), str(edge["dependency_task_id"])
        if child not in task_ids or parent not in task_ids or child == parent:
            raise PlanningDeletionError("planning.deletion_graph_invalid")
        reverse[parent].add(child)
        forward[child].add(parent)

    # Storage corruption must never turn a destructive operation into an
    # arbitrary best-effort repair.  Validate the complete dependency graph.
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(node: str) -> None:
        if node in visiting:
            raise PlanningDeletionError("planning.deletion_graph_invalid")
        if node in visited:
            return
        visiting.add(node)
        for dependency in forward[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)
    for identifier in task_ids:
        visit(identifier)

    closure = set(roots)
    pending = list(roots)
    while pending:
        current = pending.pop()
        for dependent in reverse[current]:
            if dependent not in closure:
                closure.add(dependent)
                pending.append(dependent)
    return tuple(sorted(closure)), tuple(sorted(selected_projects))


def _snapshot(connection: sqlite3.Connection, target_kind: str, target_id: str) -> DeletionPlan:
    task_ids, project_ids = _closure(connection, target_kind, target_id)
    task_sql, task_args = _placeholders(task_ids)
    project_sql, project_args = _placeholders(project_ids)

    task_rows = _rows(connection, f"SELECT id, project_id, revision FROM mentat_tasks WHERE id IN {task_sql} ORDER BY id", task_args)
    project_rows = _rows(connection, f"SELECT id, revision FROM mentat_projects WHERE id IN {project_sql} ORDER BY id", project_args)
    if len(task_rows) != len(task_ids) or len(project_rows) != len(project_ids):
        raise PlanningDeletionError("planning.deletion_stale")
    incident_edges = _rows(
        connection,
        f"SELECT task_id, dependency_task_id FROM mentat_task_dependencies WHERE task_id IN {task_sql} OR dependency_task_id IN {task_sql} ORDER BY task_id, dependency_task_id",
        task_args + task_args,
    )
    conversation_rows = _rows(
        connection,
        f"SELECT c.id, c.revision FROM mentat_conversations c JOIN mentat_conversation_planning_context p ON p.conversation_id = c.id WHERE p.task_id IN {task_sql} OR p.project_id IN {project_sql} ORDER BY c.id",
        task_args + project_args,
    )
    conversation_ids = tuple(str(row["id"]) for row in conversation_rows)
    conversation_sql, conversation_args = _placeholders(conversation_ids)
    run_rows = _rows(
        connection,
        f"SELECT id, task_id, conversation_id, retry_of_run_id, resume_of_run_id, status, state_revision, partial, terminal_finalized FROM mentat_runs WHERE task_id IN {task_sql} OR conversation_id IN {conversation_sql} ORDER BY id",
        task_args + conversation_args,
    )
    # Preserve retry/resume evidence that otherwise would survive a deleted
    # conversation/run lineage.  Repeated expansion is bounded by the run cap.
    run_by_id = {str(row["id"]): row for row in run_rows}
    while True:
        known = tuple(sorted(run_by_id))
        known_sql, known_args = _placeholders(known)
        related = _rows(
            connection,
            f"SELECT id, task_id, conversation_id, retry_of_run_id, resume_of_run_id, status, state_revision, partial, terminal_finalized FROM mentat_runs WHERE retry_of_run_id IN {known_sql} OR resume_of_run_id IN {known_sql} ORDER BY id",
            known_args + known_args,
        ) if known else []
        additions = [row for row in related if str(row["id"]) not in run_by_id]
        if not additions:
            break
        if len(run_by_id) + len(additions) > 10000:
            raise PlanningDeletionError("planning.deletion_unavailable")
        run_by_id.update({str(row["id"]): row for row in additions})
    run_rows = [run_by_id[key] for key in sorted(run_by_id)]
    run_ids = tuple(str(row["id"]) for row in run_rows)
    run_sql, run_args = _placeholders(run_ids)

    artifact_rows = _rows(
        connection,
        f"SELECT mentat_task_id, binding_id, attachment_id FROM task_artifacts WHERE mentat_task_id IN {task_sql} ORDER BY mentat_task_id, binding_id, attachment_id",
        task_args,
    )
    artifact_binding_ids = tuple(sorted({str(row["binding_id"]) for row in artifact_rows}))
    binding_sql, binding_args = _placeholders(artifact_binding_ids)
    attachment_rows = _rows(
        connection,
        f"SELECT DISTINCT attachment_id FROM run_attachments WHERE run_id IN {run_sql} OR run_id IN {binding_sql} ORDER BY attachment_id",
        run_args + binding_args,
    )
    run_attachment_rows = _rows(
        connection,
        f"SELECT run_id, attachment_id, direction, ordinal FROM run_attachments WHERE run_id IN {run_sql} OR run_id IN {binding_sql} ORDER BY run_id, direction, ordinal, attachment_id",
        run_args + binding_args,
    )
    staged_rows = _rows(
        connection,
        f"SELECT conversation_id, attachment_id FROM mentat_conversation_staged_attachments WHERE conversation_id IN {conversation_sql} ORDER BY conversation_id, attachment_id",
        conversation_args,
    )
    attachment_ids = tuple(sorted(
        {str(row["attachment_id"]) for row in artifact_rows}
        | {str(row["attachment_id"]) for row in attachment_rows}
        | {str(row["attachment_id"]) for row in staged_rows}
    ))
    active_runs = tuple(sorted(
        str(row["id"]) for row in run_rows if str(row["status"]) in ACTIVE_STATUSES
    ))
    snapshot = {
        "target": [target_kind, target_id],
        "projects": [(str(row["id"]), int(row["revision"])) for row in project_rows],
        "tasks": [(str(row["id"]), str(row["project_id"]), int(row["revision"])) for row in task_rows],
        "edges": [(str(row["task_id"]), str(row["dependency_task_id"])) for row in incident_edges],
        "conversations": [(str(row["id"]), int(row["revision"])) for row in conversation_rows],
        "runs": [
            (str(row["id"]), str(row["task_id"] or ""), str(row["conversation_id"] or ""), str(row["retry_of_run_id"] or ""), str(row["resume_of_run_id"] or ""), str(row["status"]), int(row["state_revision"]), int(row["partial"]), int(row["terminal_finalized"]))
            for row in run_rows
        ],
        "artifacts": [(str(row["mentat_task_id"]), str(row["binding_id"]), str(row["attachment_id"])) for row in artifact_rows],
        "run_attachments": [(str(row["run_id"]), str(row["attachment_id"]), str(row["direction"]), int(row["ordinal"])) for row in run_attachment_rows],
        "staged_attachments": [(str(row["conversation_id"]), str(row["attachment_id"])) for row in staged_rows],
        "attachments": attachment_ids,
    }
    # A delegated artifact commonly has both its task mapping and a synthetic
    # run attachment. The public preview reports distinct affected items, not
    # internal relationship rows, so count its attachment only once.
    counts = DeletionCounts(len(project_ids), len(task_ids), len(conversation_ids), len(run_ids), len(attachment_ids))
    target_digest = _digest([target_kind, target_id])
    closure_digest = _digest(snapshot)
    confirmation_id = _digest(["mentat.planning.delete.v1", target_digest, closure_digest])
    return DeletionPlan(target_kind, target_id, confirmation_id, target_digest, closure_digest, snapshot, counts, active_runs, run_ids, conversation_ids, task_ids, project_ids, artifact_binding_ids, attachment_ids)


class PlanningDeletionService:
    """Private authority helper used by the named planning bridge capability."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def preview(self, target_kind: object, target_id: object) -> DeletionPlan:
        kind, identifier = _validate_target(target_kind, target_id)
        try:
            with private_state_lock(self.data_dir):
                with _open_repository_database(self.data_dir) as (connection, guard):
                    with _guarded_transaction(connection, guard):
                        _require_authority(connection)
                        return _snapshot(connection, kind, identifier)
        except PlanningDeletionError:
            raise
        except (TaskRepositoryError, sqlite3.Error, OSError, ValueError) as exc:
            raise PlanningDeletionError("planning.deletion_unavailable") from exc

    def begin_confirmation(self, target_kind: object, target_id: object, confirmation_id: object) -> DeletionPlan:
        if not isinstance(confirmation_id, str) or len(confirmation_id) != 64:
            raise PlanningDeletionError("planning.deletion_confirmation_invalid")
        plan = self.preview(target_kind, target_id)
        if not hmac.compare_digest(confirmation_id, plan.confirmation_id):
            raise PlanningDeletionError("planning.deletion_stale")
        return plan

    def completed_receipt(
        self, target_kind: object, target_id: object, confirmation_id: object
    ) -> DeletionCounts | None:
        """Return one matching terminal receipt without reopening deleted data."""

        kind, identifier = _validate_target(target_kind, target_id)
        if not isinstance(confirmation_id, str) or len(confirmation_id) != 64:
            raise PlanningDeletionError("planning.deletion_confirmation_invalid")
        try:
            with private_state_lock(self.data_dir):
                with _open_repository_database(self.data_dir) as (connection, guard):
                    with _guarded_transaction(connection, guard):
                        _require_authority(connection)
                        row = connection.execute(
                            "SELECT target_digest, project_count, task_count, conversation_count, run_count, artifact_count, state FROM mentat_planning_deletion_receipts WHERE confirmation_digest = ?",
                            (confirmation_id,),
                        ).fetchone()
                        if row is None:
                            return None
                        if (
                            str(row[0]) != _digest([kind, identifier])
                            or str(row[6]) != "deleted"
                        ):
                            raise PlanningDeletionError("planning.deletion_stale")
                        table = "mentat_tasks" if kind == "task" else "mentat_projects"
                        if connection.execute(
                            f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (identifier,)
                        ).fetchone() is not None:
                            raise PlanningDeletionError("planning.deletion_stale")
                        return DeletionCounts(*(int(row[index]) for index in range(1, 6)))
        except PlanningDeletionError:
            raise
        except (TaskRepositoryError, sqlite3.Error, OSError, ValueError) as exc:
            raise PlanningDeletionError("planning.deletion_unavailable") from exc

    def finalize(self, plan: DeletionPlan) -> DeletionCounts:
        """Commit one already-verified plan after the caller stopped active Runs."""
        try:
            with private_state_lock(self.data_dir):
                with _open_repository_database(self.data_dir) as (connection, guard):
                    with _guarded_transaction(connection, guard, immediate=True):
                        _require_authority(connection)
                        existing = connection.execute(
                            "SELECT project_count, task_count, conversation_count, run_count, artifact_count, state FROM mentat_planning_deletion_receipts WHERE confirmation_digest = ?",
                            (plan.confirmation_id,),
                        ).fetchone()
                        if existing is not None:
                            if str(existing[5]) != "deleted":
                                raise PlanningDeletionError("planning.deletion_unavailable")
                            counts = DeletionCounts(*(int(existing[index]) for index in range(5)))
                            if counts != plan.counts:
                                raise PlanningDeletionError("planning.deletion_stale")
                            return counts
                        current = _snapshot(connection, plan.target_kind, plan.target_id)
                        self._verify_post_stop(plan, current)
                        self._erase(connection, plan)
                        connection.execute(
                            "INSERT INTO mentat_planning_deletion_receipts (confirmation_digest, target_kind, target_digest, closure_digest, project_count, task_count, conversation_count, run_count, artifact_count, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'deleted', ?)",
                            (plan.confirmation_id, plan.target_kind, plan.target_digest, plan.closure_digest, plan.counts.projects, plan.counts.tasks, plan.counts.conversations, plan.counts.runs, plan.counts.artifacts, _now()),
                        )
                        connection.execute(
                            "DELETE FROM mentat_planning_deletion_receipts WHERE confirmation_digest IN (SELECT confirmation_digest FROM mentat_planning_deletion_receipts ORDER BY created_at DESC LIMIT -1 OFFSET ?)",
                            (MAX_RECEIPTS,),
                        )
                    return plan.counts
        except PlanningDeletionError:
            raise
        except (TaskRepositoryError, sqlite3.Error, OSError, ValueError) as exc:
            raise PlanningDeletionError("planning.deletion_unavailable") from exc

    @staticmethod
    def _verify_post_stop(plan: DeletionPlan, current: DeletionPlan) -> None:
        if current.task_ids != plan.task_ids or current.project_ids != plan.project_ids or current.conversation_ids != plan.conversation_ids or current.run_ids != plan.run_ids or current.attachment_ids != plan.attachment_ids:
            raise PlanningDeletionError("planning.deletion_stale")
        if current.counts != plan.counts:
            raise PlanningDeletionError("planning.deletion_stale")
        before = dict((row[0], row) for row in plan.snapshot["runs"])
        after = dict((row[0], row) for row in current.snapshot["runs"])
        if set(before) != set(after):
            raise PlanningDeletionError("planning.deletion_stale")
        for run_id, old in before.items():
            new = after[run_id]
            if run_id not in plan.active_run_ids:
                if new != old:
                    raise PlanningDeletionError("planning.deletion_stale")
                continue
            if old[:5] != new[:5] or new[5] not in TERMINAL_STATUSES or new[7] != 0 or new[8] != 1 or new[6] <= old[6]:
                raise PlanningDeletionError("planning.deletion_stop_unverified")
        stable_before = dict(plan.snapshot)
        stable_after = dict(current.snapshot)
        stable_before.pop("runs")
        stable_after.pop("runs")
        if stable_before != stable_after:
            raise PlanningDeletionError("planning.deletion_stale")

    @staticmethod
    def _erase(connection: sqlite3.Connection, plan: DeletionPlan) -> None:
        task_sql, task_args = _placeholders(plan.task_ids)
        project_sql, project_args = _placeholders(plan.project_ids)
        run_sql, run_args = _placeholders(plan.run_ids)
        conversation_sql, conversation_args = _placeholders(plan.conversation_ids)
        binding_sql, binding_args = _placeholders(plan.artifact_binding_ids)
        attachment_sql, attachment_args = _placeholders(plan.attachment_ids)
        # Tables that deliberately carry historical references have no complete
        # FK cascade. Remove their scoped rows before the owned authority rows.
        connection.execute(f"DELETE FROM mentat_task_dependencies WHERE task_id IN {task_sql} OR dependency_task_id IN {task_sql}", task_args + task_args)
        connection.execute(f"DELETE FROM mentat_task_delegation_action_receipts WHERE task_id IN {task_sql}", task_args)
        connection.execute(f"DELETE FROM mentat_task_execution_reviews WHERE task_id IN {task_sql} OR run_id IN {run_sql}", task_args + run_args)
        connection.execute(f"DELETE FROM mentat_task_execution_attempts WHERE task_id IN {task_sql} OR run_id IN {run_sql}", task_args + run_args)
        connection.execute(f"DELETE FROM mentat_task_dispatch_heads WHERE task_id IN {task_sql}", task_args)
        connection.execute(f"DELETE FROM mentat_dispatch_reservations WHERE task_id IN {task_sql} OR run_id IN {run_sql}", task_args + run_args)
        connection.execute(f"DELETE FROM mentat_codex_task_create_receipts WHERE origin_run_id IN {run_sql} OR origin_task_id IN {task_sql} OR created_task_id IN {task_sql}", run_args + task_args + task_args)
        connection.execute(f"DELETE FROM mentat_codex_task_create_grants WHERE run_id IN {run_sql} OR origin_task_id IN {task_sql}", run_args + task_args)
        connection.execute(f"DELETE FROM task_artifacts WHERE mentat_task_id IN {task_sql}", task_args)
        connection.execute(
            f"DELETE FROM run_attachments WHERE run_id IN {run_sql} OR run_id IN {binding_sql}",
            run_args + binding_args,
        )
        if plan.attachment_ids:
            connection.execute(
                f"UPDATE attachments SET state = 'orphaned', expires_at = NULL, delete_after = 0, updated_at = ? WHERE id IN {attachment_sql} AND state != 'missing' AND NOT EXISTS (SELECT 1 FROM run_attachments r WHERE r.attachment_id = attachments.id)",
                (_now(),) + attachment_args,
            )
        connection.execute(f"DELETE FROM mentat_conversation_run_attempts WHERE run_id IN {run_sql} OR conversation_id IN {conversation_sql}", run_args + conversation_args)
        connection.execute(f"DELETE FROM mentat_conversation_submission_results WHERE run_id IN {run_sql}", run_args)
        connection.execute(f"DELETE FROM mentat_runs WHERE id IN {run_sql}", run_args)
        connection.execute(f"DELETE FROM mentat_conversations WHERE id IN {conversation_sql}", conversation_args)
        connection.execute(f"DELETE FROM mentat_tasks WHERE id IN {task_sql}", task_args)
        connection.execute(f"DELETE FROM mentat_projects WHERE id IN {project_sql}", project_args)
        # Both authoritative repositories deliberately require contiguous
        # ordering.  Shift first so the UNIQUE constraint cannot collide while
        # compacting a deleted middle member.
        connection.execute("UPDATE mentat_tasks SET sort_order = sort_order + 2048")
        for ordinal, row in enumerate(connection.execute("SELECT id FROM mentat_tasks ORDER BY sort_order, id")):
            connection.execute("UPDATE mentat_tasks SET sort_order = ? WHERE id = ?", (ordinal, str(row[0])))
        connection.execute("UPDATE mentat_projects SET sort_order = sort_order + 256")
        for ordinal, row in enumerate(connection.execute("SELECT id FROM mentat_projects ORDER BY sort_order, id")):
            connection.execute("UPDATE mentat_projects SET sort_order = ? WHERE id = ?", (ordinal, str(row[0])))
