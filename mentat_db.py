"""Small SQLite foundation for private, project-owned Mentat runtime state."""

from __future__ import annotations

import os
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from private_state import (
    console_root,
    database_path as private_database_path,
    ensure_console_root,
)


DATABASE_NAME = "mentat.sqlite3"
SCHEMA_VERSION = 7
# Connection validation, WAL configuration, migration, and identity checks
# must not overlap a webhook delivery transaction on Windows. Ordinary queries
# release this process-wide boundary as soon as their connection is ready.
DATABASE_OPEN_BARRIER = threading.RLock()


MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS blobs (
            id TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            storage_key TEXT NOT NULL UNIQUE,
            byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
            state TEXT NOT NULL CHECK (state IN ('ready', 'deleting', 'missing')),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            delete_attempts INTEGER NOT NULL DEFAULT 0 CHECK (delete_attempts >= 0)
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            blob_id TEXT REFERENCES blobs(id) ON DELETE RESTRICT,
            original_name TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('image', 'text')),
            state TEXT NOT NULL CHECK (
                state IN (
                    'uploading', 'staged', 'attached', 'orphaned',
                    'pending_delete', 'deleting', 'missing'
                )
            ),
            byte_size INTEGER NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            expires_at REAL,
            delete_after REAL
        );

        CREATE TABLE IF NOT EXISTS run_attachments (
            run_id TEXT NOT NULL,
            attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            direction TEXT NOT NULL CHECK (direction IN ('input', 'output')),
            ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
            created_at REAL NOT NULL,
            PRIMARY KEY (run_id, attachment_id, direction)
        );

        CREATE INDEX IF NOT EXISTS idx_attachments_state_expiry
            ON attachments(state, expires_at, delete_after);
        CREATE INDEX IF NOT EXISTS idx_attachments_blob
            ON attachments(blob_id);
        CREATE INDEX IF NOT EXISTS idx_run_attachments_attachment
            ON run_attachments(attachment_id);
        CREATE INDEX IF NOT EXISTS idx_run_attachments_run
            ON run_attachments(run_id);
        """,
    ),
    (
        2,
        """
        CREATE TABLE IF NOT EXISTS task_artifacts (
            mentat_task_id TEXT NOT NULL,
            connection_binding_id TEXT NOT NULL,
            board_id TEXT NOT NULL,
            remote_task_id TEXT NOT NULL,
            remote_artifact_id TEXT NOT NULL,
            attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            binding_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
            created_at REAL NOT NULL,
            PRIMARY KEY (
                mentat_task_id,
                connection_binding_id,
                board_id,
                remote_task_id,
                remote_artifact_id
            )
        );

        CREATE INDEX IF NOT EXISTS idx_task_artifacts_task
            ON task_artifacts(
                mentat_task_id,
                connection_binding_id,
                board_id,
                remote_task_id,
                ordinal
            );
        CREATE INDEX IF NOT EXISTS idx_task_artifacts_attachment
            ON task_artifacts(attachment_id);
        CREATE INDEX IF NOT EXISTS idx_task_artifacts_binding
            ON task_artifacts(binding_id);
        """,
    ),
    (
        3,
        """
        CREATE TABLE IF NOT EXISTS hermes_webhook_deliveries (
            binding_id TEXT NOT NULL,
            delivery_digest TEXT NOT NULL,
            event_name TEXT NOT NULL CHECK (
                event_name IN (
                    'on_session_start', 'on_session_end',
                    'subagent_start', 'subagent_stop'
                )
            ),
            received_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'duplicate')),
            PRIMARY KEY (binding_id, delivery_digest)
        );

        CREATE INDEX IF NOT EXISTS idx_hermes_webhook_deliveries_expiry
            ON hermes_webhook_deliveries(expires_at);
        """,
    ),
    (
        4,
        """
        ALTER TABLE hermes_webhook_deliveries
            RENAME TO hermes_webhook_deliveries_v3;
        DROP INDEX IF EXISTS idx_hermes_webhook_deliveries_expiry;

        CREATE TABLE hermes_webhook_deliveries (
            binding_id TEXT NOT NULL,
            delivery_digest TEXT NOT NULL,
            event_name TEXT NOT NULL CHECK (
                event_name IN (
                    'on_session_start', 'on_session_end',
                    'on_session_finalize', 'on_session_reset',
                    'subagent_start', 'subagent_stop',
                    'post_api_request', 'api_request_error', 'post_tool_call',
                    'kanban_task_claimed', 'kanban_task_completed',
                    'kanban_task_blocked', 'on_kanban_worker_spawned',
                    'on_kanban_worker_exited', 'on_kanban_worker_stale_claim',
                    'on_kanban_task_updated', 'on_kanban_dispatch_tick'
                )
            ),
            received_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'duplicate')),
            PRIMARY KEY (binding_id, delivery_digest)
        );

        INSERT INTO hermes_webhook_deliveries (
            binding_id, delivery_digest, event_name,
            received_at, expires_at, outcome
        )
        SELECT binding_id, delivery_digest, event_name,
               received_at, expires_at, outcome
        FROM hermes_webhook_deliveries_v3;

        DROP TABLE hermes_webhook_deliveries_v3;
        CREATE INDEX idx_hermes_webhook_deliveries_expiry
            ON hermes_webhook_deliveries(expires_at);
        """,
    ),
    (
        5,
        """
        CREATE TABLE mentat_tasks (
            id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 160),
            sort_order INTEGER NOT NULL UNIQUE CHECK (sort_order >= 0),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
            description TEXT NOT NULL CHECK (length(description) <= 16777216),
            project TEXT NOT NULL CHECK (length(project) BETWEEN 1 AND 120),
            status TEXT NOT NULL CHECK (
                status IN ('todo', 'in progress', 'waiting', 'needs attention', 'completed')
            ),
            priority TEXT NOT NULL CHECK (priority IN ('high', 'medium', 'low')),
            assignee TEXT CHECK (assignee IS NULL OR length(assignee) BETWEEN 1 AND 120),
            assigned_agent_id TEXT CHECK (
                assigned_agent_id IS NULL OR length(assigned_agent_id) BETWEEN 1 AND 160
            ),
            assigned_agent_id_present INTEGER NOT NULL DEFAULT 0 CHECK (
                assigned_agent_id_present IN (0, 1)
            ),
            due_date TEXT CHECK (due_date IS NULL OR length(due_date) = 10),
            source TEXT NOT NULL CHECK (length(source) BETWEEN 1 AND 32),
            review_required INTEGER NOT NULL CHECK (review_required IN (0, 1)),
            needs_attention INTEGER NOT NULL CHECK (needs_attention IN (0, 1)),
            planned_for_today INTEGER CHECK (planned_for_today IN (0, 1)),
            manual_rank INTEGER CHECK (manual_rank BETWEEN 0 AND 1000000),
            estimated_minutes INTEGER CHECK (estimated_minutes BETWEEN 1 AND 10080),
            recurrence_parent_id TEXT CHECK (
                recurrence_parent_id IS NULL OR length(recurrence_parent_id) BETWEEN 1 AND 160
            ),
            planning_state TEXT CHECK (
                planning_state IS NULL OR planning_state IN (
                    'inbox', 'planned', 'in_progress', 'waiting', 'review',
                    'someday', 'blocked', 'done'
                )
            ),
            depends_on_present INTEGER NOT NULL DEFAULT 0 CHECK (
                depends_on_present IN (0, 1)
            ),
            nested_planning_json TEXT NOT NULL DEFAULT '{}' CHECK (
                length(nested_planning_json) <= 16777216
            ),
            extensions_json TEXT NOT NULL DEFAULT '{}' CHECK (
                length(extensions_json) <= 16777216
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            completed_at TEXT CHECK (
                completed_at IS NULL OR length(completed_at) BETWEEN 1 AND 64
            )
        );

        CREATE TABLE mentat_task_tags (
            task_id TEXT NOT NULL REFERENCES mentat_tasks(id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            tag TEXT NOT NULL CHECK (length(tag) BETWEEN 1 AND 48),
            PRIMARY KEY (task_id, ordinal),
            UNIQUE (task_id, tag)
        );

        CREATE TABLE mentat_task_dependencies (
            task_id TEXT NOT NULL,
            dependency_task_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            PRIMARY KEY (task_id, ordinal),
            UNIQUE (task_id, dependency_task_id),
            CHECK (task_id != dependency_task_id),
            FOREIGN KEY (task_id) REFERENCES mentat_tasks(id)
                ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
            FOREIGN KEY (dependency_task_id) REFERENCES mentat_tasks(id)
                ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
        );

        CREATE INDEX idx_mentat_tasks_status_order
            ON mentat_tasks(status, sort_order);
        CREATE INDEX idx_mentat_tasks_project_order
            ON mentat_tasks(project, sort_order);
        CREATE INDEX idx_mentat_tasks_assigned_agent
            ON mentat_tasks(assigned_agent_id, status, sort_order);
        CREATE INDEX idx_mentat_task_dependencies_target
            ON mentat_task_dependencies(dependency_task_id, task_id);
        """,
    ),
    (
        6,
        """
        CREATE TABLE mentat_task_store_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            authority TEXT NOT NULL CHECK (authority = 'sqlite'),
            migration_contract TEXT NOT NULL CHECK (
                migration_contract = 'mentat-task-sqlite-cutover-v1'
            ),
            source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
            source_task_count INTEGER NOT NULL CHECK (
                source_task_count BETWEEN 0 AND 2048
            ),
            cutover_at REAL NOT NULL CHECK (cutover_at > 0)
        );
        """,
    ),
    (
        7,
        """
        CREATE TABLE mentat_run_store_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            authority TEXT NOT NULL CHECK (authority = 'sqlite'),
            migration_contract TEXT NOT NULL CHECK (
                migration_contract = 'mentat-run-sqlite-cutover-v1'
            ),
            source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
            source_run_count INTEGER NOT NULL CHECK (
                source_run_count BETWEEN 0 AND 10000
            ),
            cutover_at REAL NOT NULL CHECK (cutover_at > 0)
        );

        CREATE TABLE mentat_runs (
            id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
            source TEXT NOT NULL CHECK (source IN ('console', 'task_dispatch')),
            task_id TEXT CHECK (task_id IS NULL OR length(task_id) BETWEEN 1 AND 160),
            task_revision INTEGER CHECK (task_revision IS NULL OR task_revision >= 1),
            task_snapshot_json TEXT CHECK (
                task_snapshot_json IS NULL OR length(task_snapshot_json) <= 1048576
            ),
            agent_id TEXT CHECK (agent_id IS NULL OR length(agent_id) BETWEEN 1 AND 128),
            runtime_type TEXT NOT NULL CHECK (length(runtime_type) BETWEEN 1 AND 32),
            runtime_config_id TEXT CHECK (
                runtime_config_id IS NULL OR length(runtime_config_id) BETWEEN 1 AND 128
            ),
            runtime_binding_digest TEXT CHECK (
                runtime_binding_digest IS NULL OR length(runtime_binding_digest) = 64
            ),
            capabilities_json TEXT NOT NULL DEFAULT '[]' CHECK (
                length(capabilities_json) <= 8192
            ),
            runtime_run_ref TEXT CHECK (
                runtime_run_ref IS NULL OR length(runtime_run_ref) BETWEEN 1 AND 128
            ),
            runtime_event_cursor INTEGER NOT NULL DEFAULT 0 CHECK (
                runtime_event_cursor >= 0
            ),
            status TEXT NOT NULL CHECK (
                status IN (
                    'reserved', 'queued', 'submitting', 'starting', 'running',
                    'cancelling', 'waiting', 'waiting_for_approval',
                    'waiting_for_clarification', 'completed', 'failed',
                    'cancelled', 'stopped', 'interrupted', 'unknown'
                )
            ),
            dispatch_state TEXT NOT NULL CHECK (
                dispatch_state IN (
                    'legacy', 'reserved', 'submitting', 'accepted',
                    'rejected', 'unknown'
                )
            ),
            state_revision INTEGER NOT NULL DEFAULT 1 CHECK (state_revision >= 1),
            partial INTEGER NOT NULL DEFAULT 0 CHECK (partial IN (0, 1)),
            timeline_truncated INTEGER NOT NULL DEFAULT 0 CHECK (
                timeline_truncated IN (0, 1)
            ),
            first_retained_sequence INTEGER NOT NULL DEFAULT 1 CHECK (
                first_retained_sequence >= 1
            ),
            last_removed_sequence INTEGER NOT NULL DEFAULT 0 CHECK (
                last_removed_sequence >= 0
            ),
            discarded_event_count INTEGER NOT NULL DEFAULT 0 CHECK (
                discarded_event_count >= 0
            ),
            discarded_content_bytes INTEGER NOT NULL DEFAULT 0 CHECK (
                discarded_content_bytes >= 0
            ),
            truncation_reason TEXT CHECK (
                truncation_reason IS NULL OR truncation_reason IN (
                    'legacy_unverified', 'per_run_count', 'per_run_bytes',
                    'global_count', 'global_bytes'
                )
            ),
            last_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (
                last_event_sequence >= 0
            ),
            reconcile_lease_owner TEXT CHECK (
                reconcile_lease_owner IS NULL OR length(reconcile_lease_owner) BETWEEN 1 AND 128
            ),
            reconcile_lease_until REAL CHECK (
                reconcile_lease_until IS NULL OR reconcile_lease_until > 0
            ),
            details_json TEXT NOT NULL DEFAULT '{}' CHECK (
                length(details_json) <= 1048576
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            started_at TEXT CHECK (
                started_at IS NULL OR length(started_at) BETWEEN 1 AND 64
            ),
            completed_at TEXT CHECK (
                completed_at IS NULL OR length(completed_at) BETWEEN 1 AND 64
            )
        );

        CREATE TABLE mentat_agent_events (
            run_id TEXT NOT NULL REFERENCES mentat_runs(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence >= 1),
            id TEXT NOT NULL CHECK (length(id) BETWEEN 1 AND 128),
            event_type TEXT NOT NULL CHECK (
                event_type IN (
                    'run.created', 'dispatch.reserved', 'run.started',
                    'submission.unknown', 'run.interrupted', 'message',
                    'tool.requested',
                    'tool.completed', 'approval.required',
                    'artifact.created', 'cost', 'run.completed',
                    'run.failed', 'run.stopped'
                )
            ),
            source_type TEXT NOT NULL CHECK (length(source_type) BETWEEN 1 AND 64),
            source_key TEXT NOT NULL CHECK (length(source_key) BETWEEN 1 AND 160),
            occurred_at TEXT NOT NULL CHECK (length(occurred_at) BETWEEN 1 AND 64),
            summary TEXT NOT NULL CHECK (length(summary) BETWEEN 1 AND 500),
            content TEXT CHECK (content IS NULL OR length(content) <= 20000),
            metrics_json TEXT NOT NULL DEFAULT '{}' CHECK (
                length(metrics_json) <= 1024
            ),
            data_json TEXT NOT NULL DEFAULT '{}' CHECK (length(data_json) <= 16384),
            content_bytes INTEGER NOT NULL DEFAULT 0 CHECK (
                content_bytes BETWEEN 0 AND 4194304
            ),
            payload_digest TEXT NOT NULL CHECK (length(payload_digest) = 64),
            PRIMARY KEY (run_id, sequence),
            UNIQUE (run_id, id),
            UNIQUE (run_id, source_key)
        );

        CREATE TABLE mentat_dispatch_reservations (
            key_digest TEXT PRIMARY KEY CHECK (length(key_digest) = 64),
            dispatch_id TEXT NOT NULL UNIQUE CHECK (
                length(dispatch_id) BETWEEN 1 AND 128
            ),
            request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
            run_id TEXT NOT NULL UNIQUE CHECK (length(run_id) BETWEEN 1 AND 128),
            task_id TEXT NOT NULL CHECK (length(task_id) BETWEEN 1 AND 160),
            task_revision INTEGER NOT NULL CHECK (task_revision >= 1),
            runtime_binding_digest TEXT NOT NULL CHECK (
                length(runtime_binding_digest) = 64
            ),
            state TEXT NOT NULL CHECK (
                state IN ('reserved', 'submitting', 'accepted', 'rejected', 'unknown')
            ),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (
                attempt_count IN (0, 1)
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            expires_at REAL NOT NULL CHECK (expires_at > 0)
        );

        CREATE TABLE mentat_task_dispatch_heads (
            task_id TEXT PRIMARY KEY CHECK (length(task_id) BETWEEN 1 AND 160),
            task_revision INTEGER NOT NULL CHECK (task_revision >= 1),
            request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
            run_id TEXT NOT NULL CHECK (length(run_id) BETWEEN 1 AND 128),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64)
        );

        CREATE INDEX idx_mentat_runs_status_updated
            ON mentat_runs(status, updated_at DESC, id);
        CREATE INDEX idx_mentat_runs_task_created
            ON mentat_runs(task_id, created_at DESC, id);
        CREATE INDEX idx_mentat_runs_agent_created
            ON mentat_runs(agent_id, created_at DESC, id);
        CREATE UNIQUE INDEX idx_mentat_runs_one_active_task
            ON mentat_runs(task_id)
            WHERE source = 'task_dispatch' AND status IN (
                'reserved', 'queued', 'submitting', 'starting', 'running',
                'cancelling', 'waiting', 'waiting_for_approval',
                'waiting_for_clarification', 'unknown'
            );
        CREATE INDEX idx_mentat_agent_events_run_sequence
            ON mentat_agent_events(run_id, sequence);
        CREATE INDEX idx_mentat_dispatch_task
            ON mentat_dispatch_reservations(task_id, task_revision, created_at);
        """,
    ),
)


class MentatDatabaseError(RuntimeError):
    """Raised when Mentat's private database boundary is unsafe."""


def runtime_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "runtime"


def private_console_dir(data_dir: Path) -> Path:
    return console_root(data_dir)


def database_path(data_dir: Path) -> Path:
    return private_database_path(data_dir)


def _chmod(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode, follow_symlinks=False)


def ensure_private_runtime_dir(data_dir: Path) -> Path:
    """Create and validate the owner-only runtime directory without symlinks."""
    root_path = Path(data_dir)
    if root_path.is_symlink():
        raise MentatDatabaseError("Mentat data root must not be a symlink")
    root_path.mkdir(parents=True, exist_ok=True)
    root = root_path.resolve(strict=True)
    if not root.is_dir():
        raise MentatDatabaseError("Mentat data root is not a directory")

    target = root_path / "runtime"
    if target.is_symlink():
        raise MentatDatabaseError("Mentat runtime directory must not be a symlink")
    target.mkdir(mode=0o700, exist_ok=True)
    resolved = target.resolve(strict=True)
    if resolved.parent != root or not resolved.is_dir():
        raise MentatDatabaseError("Mentat runtime directory escapes the data root")
    _chmod(resolved, 0o700)
    return resolved


def ensure_private_console_dir(data_dir: Path) -> Path:
    return ensure_console_root(data_dir)


def _is_reparse_point(details: os.stat_result) -> bool:
    attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(getattr(details, "st_file_attributes", 0) & attribute)


def _validate_database_file(path: Path, runtime: Path) -> tuple[int, int] | None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return None
    if (
        stat.S_ISLNK(details.st_mode)
        or _is_reparse_point(details)
        or not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or path.resolve(strict=True).parent != runtime
        or (
            os.name == "posix"
            and (
                details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600
            )
        )
    ):
        raise MentatDatabaseError("Mentat database path is not a safe regular file")
    return int(details.st_dev), int(details.st_ino)


def _validate_database_set(path: Path, runtime: Path) -> dict[Path, tuple[int, int] | None]:
    return {
        candidate: _validate_database_file(candidate, runtime)
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
    }


def _secure_database_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            _chmod(candidate, 0o600)
        except OSError:
            continue


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
    )
    applied = {
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    if applied and max(applied) > SCHEMA_VERSION:
        raise MentatDatabaseError("Mentat database schema is newer than this application")
    for version, script in MIGRATIONS:
        if version in applied:
            continue
        try:
            # executescript otherwise commits before running its statements.
            # Open the transaction inside the script and leave it active so
            # the schema rewrite and its version receipt commit together.
            connection.executescript("BEGIN IMMEDIATE;\n" + script)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, time.time()),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def _connect_with_identity_locked(
    data_dir: Path,
) -> tuple[sqlite3.Connection, dict[Path, tuple[int, int] | None]]:
    private = ensure_private_console_dir(data_dir)
    path = private / DATABASE_NAME
    _validate_database_set(path, private)
    if not path.exists():
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
    identities = _validate_database_set(path, private)
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        migrate(connection)
        _secure_database_files(path)
        verified = _validate_database_set(path, private)
        for candidate, identity in identities.items():
            if identity is not None and verified.get(candidate) != identity:
                raise MentatDatabaseError("Mentat database file identity changed while opening")
        return connection, verified
    except Exception:
        connection.close()
        raise


def connect_with_identity(
    data_dir: Path,
) -> tuple[sqlite3.Connection, dict[Path, tuple[int, int] | None]]:
    """Open SQLite after serialized validation, WAL setup, and migration."""

    with DATABASE_OPEN_BARRIER:
        return _connect_with_identity_locked(data_dir)


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open a migrated SQLite connection with Mentat's local concurrency defaults."""

    connection, _identities = connect_with_identity(data_dir)
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """Run a transaction, rolling it back when the caller raises."""
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        try:
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def schema_version(data_dir: Path) -> int:
    connection = connect(data_dir)
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0)
    finally:
        connection.close()
