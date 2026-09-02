"""Small SQLite foundation for private, project-owned Mentat runtime state."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterator

from private_state import (
    console_root,
    database_path as private_database_path,
    ensure_console_root,
)


DATABASE_NAME = "mentat.sqlite3"
LEGACY_AGENT_REGISTRY_DATABASE_NAME = "agent-registry.sqlite3"
SCHEMA_VERSION = 23
AGENT_REGISTRY_AUTHORITY_CONTRACT = "mentat-agent-registry-convergence-v1"
EMPTY_AGENT_REGISTRY_SOURCE_SHA256 = hashlib.sha256(b"").hexdigest()
MAX_READONLY_DATABASE_BYTES = 64 * 1024 * 1024
MAX_READONLY_WAL_BYTES = 32 * 1024 * 1024
MAX_READONLY_SHM_BYTES = 4 * 1024 * 1024
MAX_READONLY_SNAPSHOT_BYTES = 96 * 1024 * 1024
# Connection validation, WAL configuration, migration, and identity checks
# must not overlap a webhook delivery transaction on Windows. Ordinary queries
# release this process-wide boundary as soon as their connection is ready.
DATABASE_OPEN_BARRIER = threading.RLock()
DATABASE_OPEN_ATTEMPTS = 3
DATABASE_OPEN_RETRY_SECONDS = 0.01


def legacy_agent_registry_artifacts_present_at(parent: Path) -> bool:
    """Fail closed when a Console directory holds any retired-registry artifact."""

    parent = Path(parent)
    prefix = f"{LEGACY_AGENT_REGISTRY_DATABASE_NAME}-"
    try:
        with os.scandir(parent) as entries:
            return any(
                entry.name == LEGACY_AGENT_REGISTRY_DATABASE_NAME
                or entry.name.startswith(prefix)
                for entry in entries
            )
    except FileNotFoundError:
        return False
    except OSError:
        return True


def legacy_agent_registry_artifacts_present(data_dir: Path) -> bool:
    return legacy_agent_registry_artifacts_present_at(console_root(Path(data_dir)))


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
    (
        8,
        """
        CREATE TABLE agent_runtime_configs (
            id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
            runtime_type TEXT NOT NULL CHECK (length(runtime_type) BETWEEN 1 AND 32),
            runtime_agent_ref TEXT NOT NULL CHECK (
                length(runtime_agent_ref) BETWEEN 1 AND 160
            ),
            created_at REAL NOT NULL CHECK (created_at >= 0),
            updated_at REAL NOT NULL CHECK (updated_at >= 0),
            UNIQUE (runtime_type, runtime_agent_ref)
        );

        CREATE TABLE mentat_agents (
            id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
            runtime_config_id TEXT NOT NULL UNIQUE
                REFERENCES agent_runtime_configs(id) ON DELETE RESTRICT,
            capabilities_json TEXT NOT NULL CHECK (
                length(capabilities_json) BETWEEN 2 AND 8192
            ),
            created_at REAL NOT NULL CHECK (created_at >= 0),
            updated_at REAL NOT NULL CHECK (updated_at >= 0)
        );

        CREATE TABLE mentat_agent_registry_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            authority TEXT NOT NULL CHECK (authority = 'sqlite'),
            migration_contract TEXT NOT NULL CHECK (
                migration_contract = 'mentat-agent-registry-convergence-v1'
            ),
            source_kind TEXT NOT NULL CHECK (source_kind IN ('fresh', 'legacy')),
            source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
            source_agent_count INTEGER NOT NULL CHECK (
                source_agent_count BETWEEN 0 AND 128
            ),
            cutover_at REAL NOT NULL CHECK (cutover_at > 0)
        );

        CREATE INDEX idx_mentat_agents_name
            ON mentat_agents(name COLLATE NOCASE, id);
        """,
    ),
    (
        9,
        """
        CREATE TABLE provider_connections (
            id TEXT PRIMARY KEY CHECK (id = 'connection_vercel'),
            provider TEXT NOT NULL CHECK (provider = 'vercel'),
            label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 80),
            state TEXT NOT NULL CHECK (state IN ('configured', 'disconnected')),
            auth_kind TEXT NOT NULL CHECK (auth_kind IN ('api_key', 'oidc')),
            model TEXT NOT NULL CHECK (length(model) BETWEEN 3 AND 160),
            team_id TEXT CHECK (
                team_id IS NULL OR length(team_id) BETWEEN 1 AND 128
            ),
            project_id TEXT CHECK (
                project_id IS NULL OR length(project_id) BETWEEN 1 AND 128
            ),
            connector TEXT CHECK (
                connector IS NULL OR length(connector) BETWEEN 1 AND 200
            ),
            connect_scopes_json TEXT NOT NULL DEFAULT '[]' CHECK (
                length(connect_scopes_json) BETWEEN 2 AND 4096
            ),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            created_at REAL NOT NULL CHECK (created_at >= 0),
            updated_at REAL NOT NULL CHECK (updated_at >= created_at),
            CHECK ((team_id IS NULL) = (project_id IS NULL))
        );

        CREATE UNIQUE INDEX idx_provider_connections_provider
            ON provider_connections(provider);
        """,
    ),
    (
        10,
        """
        ALTER TABLE mentat_agents
            ADD COLUMN revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1);

        ALTER TABLE mentat_agents
            ADD COLUMN system_role TEXT CHECK (
                system_role IS NULL OR system_role = 'direct'
            );

        CREATE UNIQUE INDEX idx_mentat_agents_system_role
            ON mentat_agents(system_role)
            WHERE system_role IS NOT NULL;

        CREATE TABLE mentat_conversations (
            id TEXT PRIMARY KEY CHECK (
                length(id) BETWEEN 1 AND 128
            ),
            agent_id TEXT NOT NULL CHECK (
                length(agent_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_agents(id) ON DELETE RESTRICT,
            title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
            title_source TEXT NOT NULL CHECK (
                title_source IN ('default', 'first_prompt')
            ),
            state TEXT NOT NULL CHECK (state IN ('active', 'archived')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            next_message_sequence INTEGER NOT NULL DEFAULT 1 CHECK (
                next_message_sequence >= 1
            ),
            next_turn_ordinal INTEGER NOT NULL DEFAULT 1 CHECK (
                next_turn_ordinal >= 1
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            archived_at TEXT CHECK (
                archived_at IS NULL OR length(archived_at) BETWEEN 1 AND 64
            )
        );

        CREATE TABLE mentat_conversation_messages (
            id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
            conversation_id TEXT NOT NULL REFERENCES mentat_conversations(id)
                ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence >= 1),
            role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            state TEXT NOT NULL CHECK (state IN ('accepted', 'cancelled')),
            content_json TEXT NOT NULL CHECK (length(content_json) <= 65536),
            content_bytes INTEGER NOT NULL CHECK (
                content_bytes BETWEEN 0 AND 65536
            ),
            run_id TEXT REFERENCES mentat_runs(id) ON DELETE SET NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            source_key TEXT NOT NULL CHECK (
                length(source_key) BETWEEN 1 AND 160
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            UNIQUE (conversation_id, sequence),
            UNIQUE (conversation_id, source_key)
        );

        CREATE TABLE mentat_conversation_turns (
            id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
            conversation_id TEXT NOT NULL REFERENCES mentat_conversations(id)
                ON DELETE CASCADE,
            user_message_id TEXT NOT NULL UNIQUE
                REFERENCES mentat_conversation_messages(id) ON DELETE RESTRICT,
            queue_ordinal INTEGER NOT NULL CHECK (queue_ordinal >= 1),
            state TEXT NOT NULL CHECK (
                state IN ('pending', 'dispatching', 'consumed', 'blocked', 'cancelled')
            ),
            blocked_reason TEXT CHECK (
                blocked_reason IS NULL OR blocked_reason IN (
                    'capacity', 'failed', 'stopped', 'interrupted', 'unknown', 'partial'
                )
            ),
            latest_run_id TEXT REFERENCES mentat_runs(id) ON DELETE SET NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            idempotency_key_digest TEXT NOT NULL CHECK (
                length(idempotency_key_digest) = 64
            ),
            request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            UNIQUE (conversation_id, queue_ordinal)
        );

        ALTER TABLE mentat_runs
            ADD COLUMN conversation_id TEXT CHECK (
                conversation_id IS NULL OR length(conversation_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_conversations(id) ON DELETE SET NULL;

        ALTER TABLE mentat_runs
            ADD COLUMN turn_id TEXT CHECK (
                turn_id IS NULL OR length(turn_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_conversation_turns(id) ON DELETE SET NULL;

        ALTER TABLE mentat_runs
            ADD COLUMN retry_of_run_id TEXT CHECK (
                retry_of_run_id IS NULL OR length(retry_of_run_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_runs(id) ON DELETE SET NULL;

        ALTER TABLE mentat_runs
            ADD COLUMN resume_of_run_id TEXT CHECK (
                resume_of_run_id IS NULL OR length(resume_of_run_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_runs(id) ON DELETE SET NULL;

        ALTER TABLE mentat_runs
            ADD COLUMN agent_revision INTEGER CHECK (
                agent_revision IS NULL OR agent_revision >= 1
            );

        ALTER TABLE mentat_runs
            ADD COLUMN runtime_config_revision INTEGER CHECK (
                runtime_config_revision IS NULL OR runtime_config_revision >= 1
            );

        ALTER TABLE mentat_runs
            ADD COLUMN execution_config_json TEXT CHECK (
                execution_config_json IS NULL OR length(execution_config_json) <= 16384
            );

        ALTER TABLE mentat_runs
            ADD COLUMN execution_config_digest TEXT CHECK (
                execution_config_digest IS NULL OR length(execution_config_digest) = 64
            );

        ALTER TABLE mentat_runs
            ADD COLUMN capacity_scope_digest TEXT CHECK (
                capacity_scope_digest IS NULL OR length(capacity_scope_digest) = 64
            );

        ALTER TABLE mentat_runs
            ADD COLUMN admitted_capacity_limit INTEGER CHECK (
                admitted_capacity_limit IS NULL OR admitted_capacity_limit BETWEEN 1 AND 32
            );

        CREATE INDEX idx_mentat_conversations_activity
            ON mentat_conversations(state, updated_at DESC, id);
        CREATE INDEX idx_mentat_conversations_agent_activity
            ON mentat_conversations(agent_id, state, updated_at DESC, id);
        CREATE INDEX idx_mentat_conversation_messages_page
            ON mentat_conversation_messages(conversation_id, sequence DESC, id);
        CREATE INDEX idx_mentat_conversation_messages_run
            ON mentat_conversation_messages(run_id, conversation_id, sequence);
        CREATE INDEX idx_mentat_conversation_turns_state
            ON mentat_conversation_turns(conversation_id, state, queue_ordinal);
        CREATE UNIQUE INDEX idx_mentat_runs_one_active_conversation
            ON mentat_runs(conversation_id)
            WHERE conversation_id IS NOT NULL AND status IN (
                'reserved', 'queued', 'submitting', 'starting', 'running',
                'cancelling', 'waiting', 'waiting_for_approval',
                'waiting_for_clarification', 'unknown'
            );

        CREATE TRIGGER mentat_conversations_agent_immutable
        BEFORE UPDATE OF agent_id ON mentat_conversations
        WHEN OLD.agent_id IS NOT NEW.agent_id
        BEGIN
            SELECT RAISE(ABORT, 'conversation_agent_immutable');
        END;

        CREATE TRIGGER mentat_conversation_turns_queue_capacity_insert
        BEFORE INSERT ON mentat_conversation_turns
        WHEN NEW.state IN ('pending', 'blocked', 'dispatching')
            AND (
                SELECT COUNT(*) FROM mentat_conversation_turns
                WHERE conversation_id = NEW.conversation_id
                  AND state IN ('pending', 'blocked', 'dispatching')
            ) >= 8
        BEGIN
            SELECT RAISE(ABORT, 'conversation_turn_capacity');
        END;

        CREATE TRIGGER mentat_conversation_turns_queue_capacity_update
        BEFORE UPDATE OF conversation_id, state ON mentat_conversation_turns
        WHEN NEW.state IN ('pending', 'blocked', 'dispatching')
            AND (
                SELECT COUNT(*) FROM mentat_conversation_turns
                WHERE conversation_id = NEW.conversation_id
                  AND state IN ('pending', 'blocked', 'dispatching')
                  AND id IS NOT OLD.id
            ) >= 8
        BEGIN
            SELECT RAISE(ABORT, 'conversation_turn_capacity');
        END;

        CREATE TRIGGER mentat_conversation_turns_conversation_immutable
        BEFORE UPDATE OF conversation_id, user_message_id, queue_ordinal
            ON mentat_conversation_turns
        WHEN OLD.conversation_id IS NOT NEW.conversation_id
            OR OLD.user_message_id IS NOT NEW.user_message_id
            OR OLD.queue_ordinal IS NOT NEW.queue_ordinal
        BEGIN
            SELECT RAISE(ABORT, 'conversation_turn_identity_immutable');
        END;

        CREATE TRIGGER mentat_runs_conversation_identity_immutable
        BEFORE UPDATE OF conversation_id, turn_id, retry_of_run_id,
            resume_of_run_id, agent_revision, runtime_config_revision,
            execution_config_json, execution_config_digest,
            capacity_scope_digest, admitted_capacity_limit ON mentat_runs
        WHEN OLD.conversation_id IS NOT NEW.conversation_id
            OR OLD.turn_id IS NOT NEW.turn_id
            OR OLD.retry_of_run_id IS NOT NEW.retry_of_run_id
            OR OLD.resume_of_run_id IS NOT NEW.resume_of_run_id
            OR OLD.agent_revision IS NOT NEW.agent_revision
            OR OLD.runtime_config_revision IS NOT NEW.runtime_config_revision
            OR OLD.execution_config_json IS NOT NEW.execution_config_json
            OR OLD.execution_config_digest IS NOT NEW.execution_config_digest
            OR OLD.capacity_scope_digest IS NOT NEW.capacity_scope_digest
            OR OLD.admitted_capacity_limit IS NOT NEW.admitted_capacity_limit
        BEGIN
            SELECT RAISE(ABORT, 'conversation_run_identity_immutable');
        END;
        """,
    ),
    (
        11,
        """
        ALTER TABLE mentat_runs
            ADD COLUMN runtime_execution_json TEXT CHECK (
                runtime_execution_json IS NULL
                OR length(runtime_execution_json) <= 2048
            );

        ALTER TABLE mentat_runs
            ADD COLUMN runtime_execution_digest TEXT CHECK (
                runtime_execution_digest IS NULL
                OR length(runtime_execution_digest) = 64
            );

        CREATE TRIGGER mentat_runs_runtime_execution_immutable
        BEFORE UPDATE OF runtime_execution_json, runtime_execution_digest
            ON mentat_runs
        WHEN OLD.runtime_execution_json IS NOT NULL
            OR OLD.runtime_execution_digest IS NOT NULL
            OR (NEW.runtime_execution_json IS NULL)
                IS NOT (NEW.runtime_execution_digest IS NULL)
        BEGIN
            SELECT RAISE(ABORT, 'runtime_execution_immutable');
        END;

        CREATE TABLE mentat_conversation_submission_results (
            turn_id TEXT PRIMARY KEY CHECK (
                length(turn_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_conversation_turns(id) ON DELETE CASCADE,
            run_id TEXT NOT NULL UNIQUE CHECK (
                length(run_id) BETWEEN 1 AND 128
            ),
            runtime_binding_digest TEXT NOT NULL CHECK (
                length(runtime_binding_digest) = 64
            ),
            dispatch_state TEXT NOT NULL CHECK (
                dispatch_state IN (
                    'reserved', 'submitting', 'accepted', 'rejected', 'unknown'
                )
            ),
            status TEXT NOT NULL CHECK (
                status IN (
                    'reserved', 'queued', 'submitting', 'starting', 'running',
                    'cancelling', 'waiting', 'waiting_for_approval',
                    'waiting_for_clarification', 'unknown', 'completed',
                    'failed', 'cancelled', 'stopped', 'interrupted'
                )
            ),
            partial INTEGER NOT NULL CHECK (partial IN (0, 1)),
            updated_at TEXT NOT NULL CHECK (
                length(updated_at) BETWEEN 1 AND 64
            )
        );

        INSERT INTO mentat_conversation_submission_results (
            turn_id, run_id, runtime_binding_digest, dispatch_state,
            status, partial, updated_at
        )
        SELECT t.id, r.id, r.runtime_binding_digest, r.dispatch_state,
               r.status, r.partial, r.updated_at
        FROM mentat_conversation_turns AS t
        JOIN mentat_runs AS r ON r.id = t.latest_run_id
        WHERE r.source = 'console'
          AND r.conversation_id = t.conversation_id
          AND r.turn_id = t.id;

        CREATE TRIGGER mentat_conversation_submission_result_insert
        AFTER INSERT ON mentat_runs
        WHEN NEW.source = 'console'
          AND NEW.conversation_id IS NOT NULL
          AND NEW.turn_id IS NOT NULL
        BEGIN
            INSERT INTO mentat_conversation_submission_results (
                turn_id, run_id, runtime_binding_digest, dispatch_state,
                status, partial, updated_at
            ) VALUES (
                NEW.turn_id, NEW.id, NEW.runtime_binding_digest,
                NEW.dispatch_state, NEW.status, NEW.partial, NEW.updated_at
            );
        END;

        CREATE TRIGGER mentat_conversation_submission_result_update
        AFTER UPDATE OF status, dispatch_state, partial,
            runtime_binding_digest, updated_at ON mentat_runs
        WHEN NEW.source = 'console'
          AND NEW.conversation_id IS NOT NULL
          AND NEW.turn_id IS NOT NULL
        BEGIN
            UPDATE mentat_conversation_submission_results
            SET dispatch_state = NEW.dispatch_state,
                status = NEW.status,
                partial = NEW.partial,
                updated_at = NEW.updated_at
            WHERE turn_id = NEW.turn_id
              AND run_id = NEW.id
              AND runtime_binding_digest = NEW.runtime_binding_digest;
            SELECT CASE WHEN changes() != 1
                THEN RAISE(ABORT, 'conversation_submission_result_missing')
            END;
        END;
        """,
    ),
    (
        12,
        """
        DROP TRIGGER IF EXISTS mentat_conversations_agent_immutable;
        DROP TRIGGER IF EXISTS mentat_conversation_turns_queue_capacity_insert;
        DROP TRIGGER IF EXISTS mentat_conversation_turns_queue_capacity_update;
        DROP TRIGGER IF EXISTS mentat_conversation_turns_conversation_immutable;

        CREATE TABLE mentat_conversation_turns_v12 (
            id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
            conversation_id TEXT NOT NULL REFERENCES mentat_conversations(id)
                ON DELETE CASCADE,
            user_message_id TEXT NOT NULL UNIQUE
                REFERENCES mentat_conversation_messages(id) ON DELETE RESTRICT,
            queue_ordinal INTEGER NOT NULL CHECK (queue_ordinal >= 1),
            state TEXT NOT NULL CHECK (
                state IN ('pending', 'dispatching', 'consumed', 'blocked', 'cancelled')
            ),
            blocked_reason TEXT CHECK (
                blocked_reason IS NULL OR blocked_reason IN (
                    'capacity', 'failed', 'stopped', 'interrupted', 'unknown', 'partial'
                )
            ),
            latest_run_id TEXT REFERENCES mentat_runs(id) ON DELETE SET NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            idempotency_key_digest TEXT NOT NULL CHECK (
                length(idempotency_key_digest) = 64
            ),
            request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            UNIQUE (conversation_id, queue_ordinal)
        );

        INSERT INTO mentat_conversation_turns_v12 (
            id, conversation_id, user_message_id, queue_ordinal, state,
            blocked_reason, latest_run_id, revision, attempt_count,
            idempotency_key_digest, request_digest, created_at, updated_at
        )
        SELECT id, conversation_id, user_message_id, queue_ordinal, state,
               blocked_reason, latest_run_id, revision, attempt_count,
               idempotency_key_digest, request_digest, created_at, updated_at
        FROM mentat_conversation_turns;

        DROP TABLE mentat_conversation_turns;
        ALTER TABLE mentat_conversation_turns_v12
            RENAME TO mentat_conversation_turns;

        CREATE INDEX idx_mentat_conversation_turns_state
            ON mentat_conversation_turns(conversation_id, state, queue_ordinal);

        CREATE TRIGGER mentat_conversations_agent_immutable
        BEFORE UPDATE OF agent_id ON mentat_conversations
        WHEN OLD.agent_id IS NOT NEW.agent_id
        BEGIN
            SELECT RAISE(ABORT, 'conversation_agent_immutable');
        END;

        CREATE TRIGGER mentat_conversation_turns_queue_capacity_insert
        BEFORE INSERT ON mentat_conversation_turns
        WHEN NEW.state IN ('pending', 'blocked', 'dispatching')
            AND (
                SELECT COUNT(*) FROM mentat_conversation_turns
                WHERE conversation_id = NEW.conversation_id
                  AND state IN ('pending', 'blocked', 'dispatching')
            ) >= 8
        BEGIN
            SELECT RAISE(ABORT, 'conversation_turn_capacity');
        END;

        CREATE TRIGGER mentat_conversation_turns_queue_capacity_update
        BEFORE UPDATE OF conversation_id, state ON mentat_conversation_turns
        WHEN NEW.state IN ('pending', 'blocked', 'dispatching')
            AND (
                SELECT COUNT(*) FROM mentat_conversation_turns
                WHERE conversation_id = NEW.conversation_id
                  AND state IN ('pending', 'blocked', 'dispatching')
                  AND id IS NOT OLD.id
            ) >= 8
        BEGIN
            SELECT RAISE(ABORT, 'conversation_turn_capacity');
        END;

        CREATE TRIGGER mentat_conversation_turns_conversation_immutable
        BEFORE UPDATE OF conversation_id, user_message_id, queue_ordinal
            ON mentat_conversation_turns
        WHEN OLD.conversation_id IS NOT NEW.conversation_id
            OR OLD.user_message_id IS NOT NEW.user_message_id
            OR OLD.queue_ordinal IS NOT NEW.queue_ordinal
        BEGIN
            SELECT RAISE(ABORT, 'conversation_turn_identity_immutable');
        END;
        """,
    ),
    (
        13,
        """
        DROP TRIGGER mentat_runs_conversation_identity_immutable;

        UPDATE mentat_runs
        SET resume_of_run_id = NULL
        WHERE resume_of_run_id IS NOT NULL
          AND NOT (
              status = 'reserved'
              AND dispatch_state = 'reserved'
          );

        CREATE TRIGGER mentat_runs_conversation_identity_immutable
        BEFORE UPDATE OF conversation_id, turn_id, retry_of_run_id,
            resume_of_run_id, agent_revision, runtime_config_revision,
            execution_config_json, execution_config_digest,
            capacity_scope_digest, admitted_capacity_limit ON mentat_runs
        WHEN OLD.conversation_id IS NOT NEW.conversation_id
            OR OLD.turn_id IS NOT NEW.turn_id
            OR OLD.retry_of_run_id IS NOT NEW.retry_of_run_id
            OR (
                OLD.resume_of_run_id IS NOT NEW.resume_of_run_id
                AND NOT (
                    OLD.resume_of_run_id IS NOT NULL
                    AND NEW.resume_of_run_id IS NULL
                    AND OLD.status = 'reserved'
                    AND OLD.dispatch_state = 'reserved'
                    AND (
                        (
                            NEW.status = 'submitting'
                            AND NEW.dispatch_state = 'submitting'
                        )
                        OR (
                            NEW.dispatch_state = 'rejected'
                            AND NEW.terminal_finalized = 1
                            AND NEW.completed_at IS NOT NULL
                            AND (
                                (NEW.status = 'failed' AND NEW.partial = 0)
                                OR (
                                    NEW.status = 'interrupted'
                                    AND NEW.partial = 1
                                )
                            )
                        )
                    )
                )
            )
            OR OLD.agent_revision IS NOT NEW.agent_revision
            OR OLD.runtime_config_revision IS NOT NEW.runtime_config_revision
            OR OLD.execution_config_json IS NOT NEW.execution_config_json
            OR OLD.execution_config_digest IS NOT NEW.execution_config_digest
            OR OLD.capacity_scope_digest IS NOT NEW.capacity_scope_digest
            OR OLD.admitted_capacity_limit IS NOT NEW.admitted_capacity_limit
        BEGIN
            SELECT RAISE(ABORT, 'conversation_run_identity_immutable');
        END;

        ALTER TABLE mentat_runs
            ADD COLUMN terminal_finalized INTEGER NOT NULL DEFAULT 0 CHECK (
                terminal_finalized IN (0, 1)
                AND (
                    terminal_finalized = 0
                    OR status IN (
                        'completed', 'failed', 'cancelled', 'stopped', 'interrupted'
                    )
                )
            );

        UPDATE mentat_runs
        SET terminal_finalized = 1
        WHERE status IN (
            'completed', 'failed', 'cancelled', 'stopped', 'interrupted'
        )
          AND (
              runtime_type != 'hermes'
              OR source != 'console'
              OR conversation_id IS NULL
              OR EXISTS (
                  SELECT 1
                  FROM mentat_agent_events AS e
                  WHERE e.run_id = mentat_runs.id
                    AND (
                        e.source_type = 'runtime.finalized'
                        OR (
                            e.source_key LIKE 'runtime:%'
                            AND e.source_type = e.event_type
                            AND (
                                (mentat_runs.status = 'completed'
                                    AND e.event_type = 'run.completed')
                                OR (mentat_runs.status = 'failed'
                                    AND e.event_type = 'run.failed')
                                OR (mentat_runs.status IN ('cancelled', 'stopped')
                                    AND e.event_type = 'run.stopped')
                                OR (mentat_runs.status = 'interrupted'
                                    AND e.event_type = 'run.interrupted')
                            )
                        )
                    )
              )
          );
        """,
    ),
    (
        14,
        """
        DROP TRIGGER mentat_conversation_submission_result_insert;

        CREATE TRIGGER mentat_conversation_submission_result_insert
        AFTER INSERT ON mentat_runs
        WHEN NEW.source = 'console'
          AND NEW.conversation_id IS NOT NULL
          AND NEW.turn_id IS NOT NULL
        BEGIN
            INSERT INTO mentat_conversation_submission_results (
                turn_id, run_id, runtime_binding_digest, dispatch_state,
                status, partial, updated_at
            ) VALUES (
                NEW.turn_id, NEW.id, NEW.runtime_binding_digest,
                NEW.dispatch_state, NEW.status, NEW.partial, NEW.updated_at
            )
            ON CONFLICT(turn_id) DO UPDATE SET
                run_id = excluded.run_id,
                runtime_binding_digest = excluded.runtime_binding_digest,
                dispatch_state = excluded.dispatch_state,
                status = excluded.status,
                partial = excluded.partial,
                updated_at = excluded.updated_at;
        END;

        CREATE TABLE mentat_conversation_run_attempts (
            key_digest TEXT PRIMARY KEY CHECK (length(key_digest) = 64),
            request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
            action TEXT NOT NULL CHECK (action IN ('retry', 'resume')),
            conversation_id TEXT NOT NULL
                REFERENCES mentat_conversations(id) ON DELETE CASCADE,
            turn_id TEXT NOT NULL
                REFERENCES mentat_conversation_turns(id) ON DELETE CASCADE,
            source_run_id TEXT NOT NULL CHECK (
                length(source_run_id) BETWEEN 1 AND 128
            ),
            run_id TEXT NOT NULL UNIQUE CHECK (
                length(run_id) BETWEEN 1 AND 128
            ),
            runtime_binding_digest TEXT NOT NULL CHECK (
                length(runtime_binding_digest) = 64
            ),
            dispatch_state TEXT NOT NULL CHECK (
                dispatch_state IN (
                    'reserved', 'submitting', 'accepted', 'rejected', 'unknown'
                )
            ),
            status TEXT NOT NULL CHECK (
                status IN (
                    'reserved', 'queued', 'submitting', 'starting', 'running',
                    'cancelling', 'waiting', 'waiting_for_approval',
                    'waiting_for_clarification', 'unknown', 'completed',
                    'failed', 'cancelled', 'stopped', 'interrupted'
                )
            ),
            partial INTEGER NOT NULL CHECK (partial IN (0, 1)),
            created_at TEXT NOT NULL CHECK (
                length(created_at) BETWEEN 1 AND 64
            ),
            updated_at TEXT NOT NULL CHECK (
                length(updated_at) BETWEEN 1 AND 64
            )
        );

        CREATE INDEX idx_mentat_conversation_run_attempts_turn
            ON mentat_conversation_run_attempts(turn_id, created_at, run_id);

        CREATE TRIGGER mentat_conversation_run_attempts_capacity
        BEFORE INSERT ON mentat_conversation_run_attempts
        WHEN (
            SELECT COUNT(*) FROM mentat_conversation_run_attempts
            WHERE turn_id = NEW.turn_id
        ) >= 7
        BEGIN
            SELECT RAISE(ABORT, 'conversation_attempt_capacity');
        END;

        CREATE TRIGGER mentat_conversation_run_attempt_result_update
        AFTER UPDATE OF status, dispatch_state, partial,
            runtime_binding_digest, updated_at ON mentat_runs
        WHEN NEW.source = 'console'
          AND NEW.conversation_id IS NOT NULL
          AND NEW.turn_id IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM mentat_conversation_run_attempts
              WHERE run_id = NEW.id
          )
        BEGIN
            UPDATE mentat_conversation_run_attempts
            SET runtime_binding_digest = NEW.runtime_binding_digest,
                dispatch_state = NEW.dispatch_state,
                status = NEW.status,
                partial = NEW.partial,
                updated_at = NEW.updated_at
            WHERE run_id = NEW.id;
            SELECT CASE WHEN changes() != 1
                THEN RAISE(ABORT, 'conversation_attempt_result_missing')
            END;
        END;
        """,
    ),
    (
        15,
        """
        CREATE TABLE mentat_conversation_staged_contexts (
            conversation_id TEXT PRIMARY KEY
                REFERENCES mentat_conversations(id) ON DELETE CASCADE,
            context_pack_id TEXT CHECK (
                context_pack_id IS NULL OR length(context_pack_id) BETWEEN 1 AND 128
            ),
            context_pack_revision TEXT CHECK (
                context_pack_revision IS NULL OR length(context_pack_revision) BETWEEN 1 AND 96
            ),
            context_pack_name TEXT CHECK (
                context_pack_name IS NULL OR length(context_pack_name) BETWEEN 1 AND 80
            ),
            context_pack_source_digests_json TEXT CHECK (
                context_pack_source_digests_json IS NULL
                OR length(context_pack_source_digests_json) BETWEEN 2 AND 600
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            CHECK (
                (context_pack_id IS NULL AND context_pack_revision IS NULL
                    AND context_pack_name IS NULL
                    AND context_pack_source_digests_json IS NULL)
                OR
                (context_pack_id IS NOT NULL AND context_pack_revision IS NOT NULL
                    AND context_pack_name IS NOT NULL
                    AND context_pack_source_digests_json IS NOT NULL)
            )
        );

        CREATE TABLE mentat_conversation_staged_attachments (
            conversation_id TEXT NOT NULL
                REFERENCES mentat_conversations(id) ON DELETE CASCADE,
            attachment_id TEXT NOT NULL UNIQUE
                REFERENCES attachments(id) ON DELETE CASCADE,
            source TEXT NOT NULL CHECK (
                source IN ('upload', 'workspace', 'context_pack')
            ),
            ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 7),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            PRIMARY KEY (conversation_id, attachment_id),
            UNIQUE (conversation_id, ordinal)
        );

        CREATE TABLE mentat_conversation_run_contexts (
            run_id TEXT PRIMARY KEY
                REFERENCES mentat_runs(id) ON DELETE CASCADE,
            context_digest TEXT NOT NULL CHECK (length(context_digest) = 64),
            context_pack_id TEXT CHECK (
                context_pack_id IS NULL OR length(context_pack_id) BETWEEN 1 AND 128
            ),
            context_pack_revision TEXT CHECK (
                context_pack_revision IS NULL OR length(context_pack_revision) BETWEEN 1 AND 96
            ),
            context_pack_name TEXT CHECK (
                context_pack_name IS NULL OR length(context_pack_name) BETWEEN 1 AND 80
            ),
            context_pack_source_digests_json TEXT CHECK (
                context_pack_source_digests_json IS NULL
                OR length(context_pack_source_digests_json) BETWEEN 2 AND 600
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            CHECK (
                (context_pack_id IS NULL AND context_pack_revision IS NULL
                    AND context_pack_name IS NULL
                    AND context_pack_source_digests_json IS NULL)
                OR
                (context_pack_id IS NOT NULL AND context_pack_revision IS NOT NULL
                    AND context_pack_name IS NOT NULL
                    AND context_pack_source_digests_json IS NOT NULL)
            )
        );

        CREATE INDEX idx_mentat_conversation_staged_attachments_order
            ON mentat_conversation_staged_attachments(conversation_id, ordinal);
        CREATE INDEX idx_mentat_conversation_run_context_pack
            ON mentat_conversation_run_contexts(context_pack_id, context_pack_revision);

        CREATE TRIGGER mentat_conversation_staged_context_idle_insert
        BEFORE INSERT ON mentat_conversation_staged_contexts
        WHEN EXISTS (
            SELECT 1 FROM mentat_runs AS r
            WHERE r.conversation_id = NEW.conversation_id
              AND (
                r.status IN (
                    'reserved', 'queued', 'submitting', 'starting', 'running',
                    'cancelling', 'waiting', 'waiting_for_approval',
                    'waiting_for_clarification', 'unknown'
                )
                OR (r.runtime_type = 'hermes'
                    AND r.status IN (
                        'completed', 'failed', 'cancelled', 'stopped', 'interrupted'
                    ) AND r.terminal_finalized = 0)
              )
        ) OR EXISTS (
            SELECT 1 FROM mentat_conversation_turns AS t
            WHERE t.conversation_id = NEW.conversation_id
              AND t.state IN ('pending', 'blocked', 'dispatching')
        )
        BEGIN
            SELECT RAISE(ABORT, 'conversation_context_requires_idle');
        END;

        CREATE TRIGGER mentat_conversation_staged_attachment_idle_insert
        BEFORE INSERT ON mentat_conversation_staged_attachments
        WHEN EXISTS (
            SELECT 1 FROM mentat_runs AS r
            WHERE r.conversation_id = NEW.conversation_id
              AND (
                r.status IN (
                    'reserved', 'queued', 'submitting', 'starting', 'running',
                    'cancelling', 'waiting', 'waiting_for_approval',
                    'waiting_for_clarification', 'unknown'
                )
                OR (r.runtime_type = 'hermes'
                    AND r.status IN (
                        'completed', 'failed', 'cancelled', 'stopped', 'interrupted'
                    ) AND r.terminal_finalized = 0)
              )
        ) OR EXISTS (
            SELECT 1 FROM mentat_conversation_turns AS t
            WHERE t.conversation_id = NEW.conversation_id
              AND t.state IN ('pending', 'blocked', 'dispatching')
        )
        BEGIN
            SELECT RAISE(ABORT, 'conversation_context_requires_idle');
        END;

        CREATE TRIGGER mentat_conversation_staged_attachment_capacity
        BEFORE INSERT ON mentat_conversation_staged_attachments
        WHEN (
            SELECT COUNT(*) FROM mentat_conversation_staged_attachments
            WHERE conversation_id = NEW.conversation_id
        ) >= 8
        OR (
            NEW.source != 'context_pack'
            AND (
                SELECT COUNT(*) FROM mentat_conversation_staged_attachments
                WHERE conversation_id = NEW.conversation_id
                  AND source != 'context_pack'
            ) >= 5
        )
        OR (
            (SELECT kind FROM attachments WHERE id = NEW.attachment_id) = 'image'
            AND EXISTS (
                SELECT 1
                FROM mentat_conversation_staged_attachments AS s
                JOIN attachments AS a ON a.id = s.attachment_id
                WHERE s.conversation_id = NEW.conversation_id
                  AND a.kind = 'image'
            )
        )
        OR (
            NEW.source = 'context_pack'
            AND NOT EXISTS (
                SELECT 1 FROM mentat_conversation_staged_contexts
                WHERE conversation_id = NEW.conversation_id
                  AND context_pack_id IS NOT NULL
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'conversation_context_capacity');
        END;

        CREATE TRIGGER mentat_conversation_staged_context_cleanup
        AFTER DELETE ON mentat_conversation_staged_contexts
        BEGIN
            DELETE FROM mentat_conversation_staged_attachments
            WHERE conversation_id = OLD.conversation_id
              AND source = 'context_pack';
        END;
        """,
    ),
    (
        16,
        """
        DROP INDEX idx_mentat_conversations_activity;
        DROP INDEX idx_mentat_conversations_agent_activity;
        DROP TRIGGER mentat_conversations_agent_immutable;

        CREATE TABLE mentat_conversations_v16 (
            id TEXT PRIMARY KEY CHECK (
                length(id) BETWEEN 1 AND 128
            ),
            agent_id TEXT NOT NULL CHECK (
                length(agent_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_agents(id) ON DELETE RESTRICT,
            title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
            title_source TEXT NOT NULL CHECK (
                title_source IN ('default', 'first_prompt', 'manual')
            ),
            state TEXT NOT NULL CHECK (state IN ('active', 'archived')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            next_message_sequence INTEGER NOT NULL DEFAULT 1 CHECK (
                next_message_sequence >= 1
            ),
            next_turn_ordinal INTEGER NOT NULL DEFAULT 1 CHECK (
                next_turn_ordinal >= 1
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            archived_at TEXT CHECK (
                archived_at IS NULL OR length(archived_at) BETWEEN 1 AND 64
            )
        );

        INSERT INTO mentat_conversations_v16 (
            id, agent_id, title, title_source, state, revision,
            next_message_sequence, next_turn_ordinal,
            created_at, updated_at, archived_at
        )
        SELECT id, agent_id, title, title_source, state, revision,
               next_message_sequence, next_turn_ordinal,
               created_at, updated_at, archived_at
        FROM mentat_conversations;

        DROP TABLE mentat_conversations;
        ALTER TABLE mentat_conversations_v16 RENAME TO mentat_conversations;

        CREATE INDEX idx_mentat_conversations_activity
            ON mentat_conversations(state, updated_at DESC, id);
        CREATE INDEX idx_mentat_conversations_agent_activity
            ON mentat_conversations(agent_id, state, updated_at DESC, id);

        CREATE TRIGGER mentat_conversations_agent_immutable
        BEFORE UPDATE OF agent_id ON mentat_conversations
        WHEN OLD.agent_id IS NOT NEW.agent_id
        BEGIN
            SELECT RAISE(ABORT, 'conversation_agent_immutable');
        END;
        """,
    ),
    (
        17,
        """
        CREATE TABLE mentat_conversation_planning_context (
            conversation_id TEXT PRIMARY KEY REFERENCES mentat_conversations(id) ON DELETE CASCADE,
            project_id TEXT NOT NULL CHECK (
                length(project_id) BETWEEN 1 AND 80
                AND substr(project_id, 1, 1) GLOB '[A-Za-z0-9]'
                AND project_id NOT GLOB '*[^A-Za-z0-9_.:-]*'
            ),
            task_id TEXT CHECK (
                task_id IS NULL OR (
                    length(task_id) BETWEEN 1 AND 160
                    AND substr(task_id, 1, 1) GLOB '[A-Za-z0-9]'
                    AND task_id NOT GLOB '*[^A-Za-z0-9_.:@-]*'
                )
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64)
        );

        CREATE INDEX idx_mentat_conversation_planning_project
            ON mentat_conversation_planning_context(project_id, conversation_id);
        CREATE INDEX idx_mentat_conversation_planning_task
            ON mentat_conversation_planning_context(task_id, conversation_id)
            WHERE task_id IS NOT NULL;
        """,
    ),
    (
        18,
        """
        CREATE TABLE mentat_projects (
            id TEXT PRIMARY KEY CHECK (
                length(id) BETWEEN 1 AND 80
                AND substr(id, 1, 1) GLOB '[A-Za-z0-9]'
                AND id NOT GLOB '*[^A-Za-z0-9_.:-]*'
            ),
            sort_order INTEGER NOT NULL UNIQUE CHECK (sort_order >= 0),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
            name_key TEXT NOT NULL UNIQUE CHECK (length(name_key) BETWEEN 1 AND 240),
            type TEXT NOT NULL CHECK (length(type) BETWEEN 1 AND 80),
            status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'archived')),
            description TEXT NOT NULL CHECK (length(description) <= 16777216),
            obsidian_note TEXT,
            aliases_json TEXT NOT NULL DEFAULT '[]' CHECK (length(aliases_json) <= 4096),
            extensions_json TEXT NOT NULL DEFAULT '{}' CHECK (length(extensions_json) <= 16777216),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64)
        );

        CREATE TABLE mentat_project_store_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            authority TEXT NOT NULL CHECK (authority = 'sqlite'),
            migration_contract TEXT NOT NULL CHECK (
                migration_contract = 'mentat-project-sqlite-cutover-v1'
            ),
            source_sha256 TEXT NOT NULL CHECK (length(source_sha256) = 64),
            source_project_count INTEGER NOT NULL CHECK (
                source_project_count BETWEEN 0 AND 256
            ),
            task_source_sha256 TEXT NOT NULL CHECK (length(task_source_sha256) = 64),
            cutover_at REAL NOT NULL CHECK (cutover_at > 0)
        );

        ALTER TABLE mentat_tasks ADD COLUMN project_id TEXT CHECK (
            project_id IS NULL OR (
                length(project_id) BETWEEN 1 AND 80
                AND substr(project_id, 1, 1) GLOB '[A-Za-z0-9]'
                AND project_id NOT GLOB '*[^A-Za-z0-9_.:-]*'
            )
        );

        CREATE INDEX idx_mentat_projects_status_order
            ON mentat_projects(status, sort_order);
        CREATE INDEX idx_mentat_tasks_project_id_order
            ON mentat_tasks(project_id, sort_order);
        """,
    ),
    (
        19,
        """
        CREATE TABLE mentat_task_execution_attempts (
            run_id TEXT PRIMARY KEY REFERENCES mentat_runs(id) ON DELETE RESTRICT,
            task_id TEXT NOT NULL CHECK (length(task_id) BETWEEN 1 AND 160),
            task_revision INTEGER NOT NULL CHECK (task_revision >= 1),
            agent_id TEXT NOT NULL CHECK (length(agent_id) BETWEEN 1 AND 128),
            state TEXT NOT NULL CHECK (
                state IN ('dispatched', 'review_ready', 'completion_blocked',
                          'accepted', 'changes_requested')
            ),
            review_task_revision INTEGER CHECK (
                review_task_revision IS NULL OR review_task_revision >= 1
            ),
            completion_reason TEXT CHECK (
                completion_reason IS NULL OR length(completion_reason) BETWEEN 1 AND 64
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64)
        );

        CREATE TABLE mentat_task_execution_reviews (
            key_digest TEXT PRIMARY KEY CHECK (length(key_digest) = 64),
            request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
            task_id TEXT NOT NULL CHECK (length(task_id) BETWEEN 1 AND 160),
            task_revision INTEGER NOT NULL CHECK (task_revision >= 1),
            run_id TEXT NOT NULL UNIQUE REFERENCES mentat_runs(id) ON DELETE RESTRICT,
            action TEXT NOT NULL CHECK (action IN ('accept', 'request_changes')),
            note TEXT CHECK (note IS NULL OR length(note) <= 2000),
            result_task_revision INTEGER NOT NULL CHECK (result_task_revision >= 1),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64)
        );

        CREATE INDEX idx_mentat_task_execution_attempts_task
            ON mentat_task_execution_attempts(task_id, task_revision, created_at DESC);
        CREATE INDEX idx_mentat_task_execution_attempts_review
            ON mentat_task_execution_attempts(task_id, review_task_revision, state);
        CREATE INDEX idx_mentat_task_execution_reviews_task
            ON mentat_task_execution_reviews(task_id, created_at DESC);
        """,
    ),
    (
        20,
        """
        CREATE TABLE mentat_task_delegation_action_receipts (
            key_digest TEXT PRIMARY KEY CHECK (length(key_digest) = 64),
            request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
            task_id TEXT NOT NULL CHECK (length(task_id) BETWEEN 1 AND 160),
            task_revision INTEGER NOT NULL CHECK (task_revision >= 1),
            action TEXT NOT NULL CHECK (
                action IN (
                    'delegate', 'accept', 'reply', 'retry', 'stop',
                    'request_revision', 'mark_blocked'
                )
            ),
            confirmation_digest TEXT NOT NULL CHECK (length(confirmation_digest) = 64),
            delegation_binding_digest TEXT NOT NULL CHECK (
                length(delegation_binding_digest) = 64
            ),
            remote_revision_digest TEXT NOT NULL CHECK (
                length(remote_revision_digest) = 64
            ),
            state TEXT NOT NULL CHECK (
                state IN (
                    'reserved', 'submitting', 'accepted', 'rejected',
                    'unknown', 'partial'
                )
            ),
            result_task_revision INTEGER CHECK (
                result_task_revision IS NULL OR result_task_revision >= 1
            ),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            expires_at REAL CHECK (
                (state IN ('accepted', 'rejected') AND expires_at IS NOT NULL AND expires_at > 0)
                OR (state IN ('reserved', 'submitting', 'unknown', 'partial') AND expires_at IS NULL)
            )
        );

        CREATE UNIQUE INDEX idx_mentat_task_delegation_action_receipts_active_task
            ON mentat_task_delegation_action_receipts(task_id)
            WHERE state IN ('reserved', 'submitting', 'unknown', 'partial');
        CREATE INDEX idx_mentat_task_delegation_action_receipts_expires
            ON mentat_task_delegation_action_receipts(expires_at)
            WHERE expires_at IS NOT NULL;
        CREATE INDEX idx_mentat_task_delegation_action_receipts_task
            ON mentat_task_delegation_action_receipts(task_id, created_at DESC);
        """,
    ),
    (
        21,
        """
        ALTER TABLE mentat_task_delegation_action_receipts
            ADD COLUMN result_proof_digest TEXT CHECK (
                result_proof_digest IS NULL OR length(result_proof_digest) = 64
            );
        """,
    ),
    (
        22,
        """
        CREATE TABLE mentat_codex_task_create_grants (
            run_id TEXT PRIMARY KEY REFERENCES mentat_runs(id) ON DELETE RESTRICT,
            origin_task_id TEXT NOT NULL CHECK (length(origin_task_id) BETWEEN 1 AND 160),
            origin_task_revision INTEGER NOT NULL CHECK (origin_task_revision >= 1),
            project_id TEXT NOT NULL CHECK (length(project_id) BETWEEN 1 AND 80),
            agent_id TEXT NOT NULL CHECK (length(agent_id) BETWEEN 1 AND 128),
            runtime_binding_digest TEXT NOT NULL CHECK (length(runtime_binding_digest) = 64),
            state TEXT NOT NULL CHECK (state IN ('preauthorized', 'thread_bound', 'armed')),
            thread_id TEXT CHECK (thread_id IS NULL OR length(thread_id) BETWEEN 1 AND 128),
            turn_id TEXT CHECK (turn_id IS NULL OR length(turn_id) BETWEEN 1 AND 128),
            runtime_run_ref TEXT CHECK (runtime_run_ref IS NULL OR length(runtime_run_ref) BETWEEN 1 AND 128),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            updated_at TEXT NOT NULL CHECK (length(updated_at) BETWEEN 1 AND 64),
            CHECK (
                (state = 'preauthorized' AND thread_id IS NULL AND turn_id IS NULL AND runtime_run_ref IS NULL)
                OR (state = 'thread_bound' AND thread_id IS NOT NULL AND turn_id IS NULL AND runtime_run_ref IS NULL)
                OR (state = 'armed' AND thread_id IS NOT NULL AND turn_id IS NOT NULL AND runtime_run_ref IS NOT NULL)
            )
        );

        CREATE UNIQUE INDEX idx_mentat_codex_task_create_grants_thread
            ON mentat_codex_task_create_grants(thread_id)
            WHERE thread_id IS NOT NULL;

        CREATE TABLE mentat_codex_task_create_receipts (
            origin_run_id TEXT PRIMARY KEY REFERENCES mentat_runs(id) ON DELETE RESTRICT,
            thread_id TEXT NOT NULL CHECK (length(thread_id) BETWEEN 1 AND 128),
            turn_id TEXT NOT NULL CHECK (length(turn_id) BETWEEN 1 AND 128),
            call_id TEXT NOT NULL CHECK (length(call_id) BETWEEN 1 AND 128),
            request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
            origin_task_id TEXT NOT NULL CHECK (length(origin_task_id) BETWEEN 1 AND 160),
            project_id TEXT NOT NULL CHECK (length(project_id) BETWEEN 1 AND 80),
            agent_id TEXT NOT NULL CHECK (length(agent_id) BETWEEN 1 AND 128),
            created_task_id TEXT NOT NULL CHECK (length(created_task_id) BETWEEN 1 AND 160),
            created_task_revision INTEGER NOT NULL CHECK (created_task_revision >= 1),
            result_proof_digest TEXT NOT NULL CHECK (length(result_proof_digest) = 64),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64),
            UNIQUE (thread_id, turn_id, call_id)
        );

        CREATE INDEX idx_mentat_codex_task_create_receipts_task
            ON mentat_codex_task_create_receipts(created_task_id, created_at DESC);
        """,
    ),
    (
        23,
        """
        -- This is a tombstone, not a historical copy of deleted planning data.
        -- It deliberately carries only a confirmation proof and count-only result.
        CREATE TABLE mentat_planning_deletion_receipts (
            confirmation_digest TEXT PRIMARY KEY CHECK (length(confirmation_digest) = 64),
            target_kind TEXT NOT NULL CHECK (target_kind IN ('task', 'project')),
            target_digest TEXT NOT NULL CHECK (length(target_digest) = 64),
            closure_digest TEXT NOT NULL CHECK (length(closure_digest) = 64),
            project_count INTEGER NOT NULL CHECK (project_count BETWEEN 0 AND 256),
            task_count INTEGER NOT NULL CHECK (task_count BETWEEN 0 AND 2048),
            conversation_count INTEGER NOT NULL CHECK (conversation_count BETWEEN 0 AND 1024),
            run_count INTEGER NOT NULL CHECK (run_count BETWEEN 0 AND 10000),
            artifact_count INTEGER NOT NULL CHECK (artifact_count BETWEEN 0 AND 10000),
            state TEXT NOT NULL CHECK (state = 'deleted'),
            created_at TEXT NOT NULL CHECK (length(created_at) BETWEEN 1 AND 64)
        );

        CREATE INDEX idx_mentat_planning_deletion_receipts_created
            ON mentat_planning_deletion_receipts(created_at DESC);
        """,
    ),
)

MIGRATIONS_REQUIRING_DISABLED_FOREIGN_KEYS = frozenset({12, 16})

_LEGACY_SCHEMA_11_MISSING_CONVERSATION_OBJECTS = frozenset(
    {
        ("trigger", "mentat_conversations_agent_immutable"),
        ("trigger", "mentat_conversation_turns_queue_capacity_insert"),
        ("trigger", "mentat_conversation_turns_queue_capacity_update"),
        ("trigger", "mentat_conversation_turns_conversation_immutable"),
    }
)
_CURRENT_BLOCKED_REASON_SQL = """blocked_reason TEXT CHECK (
                blocked_reason IS NULL OR blocked_reason IN (
                    'capacity', 'failed', 'stopped', 'interrupted', 'unknown', 'partial'
                )
            ),"""
_LEGACY_BLOCKED_REASON_SQL = """blocked_reason TEXT CHECK (
                blocked_reason IS NULL OR length(blocked_reason) BETWEEN 1 AND 64
            ),"""

_SQL_TOKEN = re.compile(
    r"""
    (?P<whitespace>\s+)
    |(?P<line_comment>--[^\r\n]*)
    |(?P<block_comment>/\*.*?\*/)
    |(?P<blob>[xX]'(?:''|[^'])*')
    |(?P<string>'(?:''|[^'])*')
    |(?P<quoted_identifier>"(?:""|[^"])*"|`(?:``|[^`])*`|\[(?:\]\]|[^\]])*\])
    |(?P<parameter>\?(?:\d+)?|[:@$][A-Za-z_][A-Za-z0-9_$]*)
    |(?P<number>(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?)
    |(?P<identifier>[A-Za-z_][A-Za-z0-9_$]*)
    |(?P<operator>->>|->|==|!=|<>|<=|>=|<<|>>|\|\||.)
    """,
    re.DOTALL | re.VERBOSE,
)


def _sql_token_signature(sql: str) -> str:
    """Canonicalize layout while preserving every meaningful SQL token."""

    tokens: list[str] = []
    for match in _SQL_TOKEN.finditer(sql.strip()):
        kind = str(match.lastgroup)
        if kind in {"whitespace", "line_comment", "block_comment"}:
            continue
        value = match.group(0)
        tokens.append(f"{kind}:{len(value)}:{value}")
    return "".join(f"{len(token)}:{token}" for token in tokens)


@lru_cache(maxsize=1)
def _known_legacy_schema_10_script() -> str:
    """Recreate the sole pre-release Conversation schema drift exactly."""

    script = dict(MIGRATIONS)[10]
    if script.count(_CURRENT_BLOCKED_REASON_SQL) != 1:
        raise RuntimeError("known schema-11 drift constraint is stale")
    script = script.replace(
        _CURRENT_BLOCKED_REASON_SQL,
        _LEGACY_BLOCKED_REASON_SQL,
    )
    for _object_type, name in _LEGACY_SCHEMA_11_MISSING_CONVERSATION_OBJECTS:
        script, count = re.subn(
            rf"\n\s*CREATE TRIGGER {name}\b.*?\n\s*END;\n",
            "\n",
            script,
            count=1,
            flags=re.DOTALL,
        )
        if count != 1:
            raise RuntimeError(f"known schema-11 drift trigger is stale: {name}")
    return script


def schema_signature(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str, str], ...]:
    """Return the token-exact SQLite object graph for upgrade gating."""

    return tuple(
        (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            _sql_token_signature(str(row[3] or "")),
        )
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_autoindex_%' ORDER BY type, name"
        )
    )


@lru_cache(maxsize=None)
def expected_schema_signature(
    schema_version: int,
) -> tuple[tuple[str, str, str, str], ...]:
    """Build the exact schema emitted by this code through one version."""

    connection = sqlite3.connect(":memory:")
    try:
        for version, script in MIGRATIONS:
            if version > schema_version:
                break
            connection.executescript(script)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                (version,),
            )
        return schema_signature(connection)
    finally:
        connection.close()


@lru_cache(maxsize=1)
def known_legacy_schema_11_signature(
) -> tuple[tuple[str, str, str, str], ...]:
    """Return the sole pre-release schema-11 shape eligible for upgrade."""

    connection = sqlite3.connect(":memory:")
    try:
        for version, script in MIGRATIONS:
            if version > 11:
                break
            connection.executescript(
                _known_legacy_schema_10_script() if version == 10 else script
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                (version,),
            )
        return schema_signature(connection)
    finally:
        connection.close()


def schema_signature_state(
    connection: sqlite3.Connection,
    schema_version: int,
) -> str:
    """Classify an exact released schema or the one approved upgrade drift."""

    actual = schema_signature(connection)
    if actual == expected_schema_signature(schema_version):
        return "expected"
    if (
        schema_version == 11
        and actual == known_legacy_schema_11_signature()
    ):
        return "known_legacy_conversation_drift"
    return "invalid"


class MentatDatabaseError(RuntimeError):
    """Raised when Mentat's private database boundary is unsafe."""


class _TransientDatabaseSidecarRace(MentatDatabaseError):
    """A SQLite sidecar disappeared after its initial safe inspection."""


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
    identity = int(details.st_dev), int(details.st_ino)
    unsafe = (
        stat.S_ISLNK(details.st_mode)
        or _is_reparse_point(details)
        or not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or (
            os.name == "posix"
            and (
                details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o600
            )
        )
    )
    if unsafe:
        if path.name in {f"{DATABASE_NAME}-wal", f"{DATABASE_NAME}-shm"}:
            try:
                path.lstat()
            except FileNotFoundError as exc:
                raise _TransientDatabaseSidecarRace(
                    "Mentat database sidecar changed during validation"
                ) from exc
        raise MentatDatabaseError("Mentat database path is not a safe regular file")
    try:
        resolved_parent = path.resolve(strict=True).parent
    except FileNotFoundError:
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        raise MentatDatabaseError("Mentat database path changed during validation")
    except PermissionError as exc:
        if path.name in {f"{DATABASE_NAME}-wal", f"{DATABASE_NAME}-shm"}:
            try:
                latest = path.lstat()
            except FileNotFoundError as missing:
                raise _TransientDatabaseSidecarRace(
                    "Mentat database sidecar changed during validation"
                ) from missing
            if (int(latest.st_dev), int(latest.st_ino)) == identity:
                raise _TransientDatabaseSidecarRace(
                    "Mentat database sidecar changed during validation"
                ) from exc
        raise MentatDatabaseError("Mentat database path changed during validation") from exc
    if resolved_parent != runtime:
        if path.name in {f"{DATABASE_NAME}-wal", f"{DATABASE_NAME}-shm"}:
            try:
                path.lstat()
            except FileNotFoundError as exc:
                raise _TransientDatabaseSidecarRace(
                    "Mentat database sidecar changed during validation"
                ) from exc
        raise MentatDatabaseError("Mentat database path is not a safe regular file")
    return identity


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


def _execute_script_in_active_transaction(
    connection: sqlite3.Connection,
    script: str,
) -> None:
    """Execute a fixed migration script without sqlite3's implicit commit."""

    pending: list[str] = []
    for character in script:
        pending.append(character)
        if character != ";":
            continue
        statement = "".join(pending)
        if not sqlite3.complete_statement(statement):
            continue
        connection.execute(statement)
        pending.clear()
    if "".join(pending).strip():
        raise MentatDatabaseError("Mentat database migration script is incomplete")


def migrate(
    connection: sqlite3.Connection,
    *,
    claim_fresh_agent_authority: bool = True,
    fresh_agent_authority_allowed: Callable[[], bool] | None = None,
) -> float | None:
    fresh_agent_cutover_at: float | None = None
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
    )
    applied = {
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    existing_tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    }
    fresh_database = not applied and existing_tables == {"schema_migrations"}
    if applied and max(applied) > SCHEMA_VERSION:
        raise MentatDatabaseError("Mentat database schema is newer than this application")
    for version, script in MIGRATIONS:
        if version in applied:
            continue
        requires_disabled_foreign_keys = (
            version in MIGRATIONS_REQUIRING_DISABLED_FOREIGN_KEYS
        )
        requires_exact_source_gate = version in {12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
        if requires_exact_source_gate and connection.in_transaction:
            raise MentatDatabaseError(
                "Mentat database migration started inside a transaction"
            )
        foreign_keys_row = connection.execute("PRAGMA foreign_keys").fetchone()
        foreign_keys_were_enabled = bool(
            foreign_keys_row is not None and int(foreign_keys_row[0]) == 1
        )
        if requires_disabled_foreign_keys and foreign_keys_were_enabled:
            connection.execute("PRAGMA foreign_keys = OFF")
            disabled_row = connection.execute("PRAGMA foreign_keys").fetchone()
            if disabled_row is None or int(disabled_row[0]) != 0:
                raise MentatDatabaseError(
                    "Mentat database migration could not disable foreign keys"
                )
        try:
            if requires_exact_source_gate:
                # The exact source gate, rewrite, and receipt share this write
                # transaction so no competing schema writer can race the gate.
                connection.execute("BEGIN IMMEDIATE")
                if (
                    version == 12
                    and schema_signature_state(connection, 11) == "invalid"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 11 cannot be safely upgraded"
                    )
                if (
                    version == 13
                    and schema_signature_state(connection, 12) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 12 cannot be safely upgraded"
                    )
                if (
                    version == 14
                    and schema_signature_state(connection, 13) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 13 cannot be safely upgraded"
                    )
                if (
                    version == 15
                    and schema_signature_state(connection, 14) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 14 cannot be safely upgraded"
                    )
                if (
                    version == 16
                    and schema_signature_state(connection, 15) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 15 cannot be safely upgraded"
                    )
                if (
                    version == 17
                    and schema_signature_state(connection, 16) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 16 cannot be safely upgraded"
                    )
                if (
                    version == 18
                    and schema_signature_state(connection, 17) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 17 cannot be safely upgraded"
                    )
                if (
                    version == 19
                    and schema_signature_state(connection, 18) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 18 cannot be safely upgraded"
                    )
                if (
                    version == 20
                    and schema_signature_state(connection, 19) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 19 cannot be safely upgraded"
                    )
                if (
                    version == 21
                    and schema_signature_state(connection, 20) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 20 cannot be safely upgraded"
                    )
                if (
                    version == 22
                    and schema_signature_state(connection, 21) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 21 cannot be safely upgraded"
                    )
                if (
                    version == 23
                    and schema_signature_state(connection, 22) != "expected"
                ):
                    raise MentatDatabaseError(
                        "Mentat schema 22 cannot be safely upgraded"
                    )
                _execute_script_in_active_transaction(connection, script)
            else:
                # executescript otherwise commits before running its statements.
                # Open the transaction inside the script and leave it active so
                # the schema rewrite and its version receipt commit together.
                connection.executescript("BEGIN IMMEDIATE;\n" + script)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, time.time()),
            )
            should_claim_fresh_agent_authority = (
                version == SCHEMA_VERSION
                and fresh_database
                and claim_fresh_agent_authority
                and (
                    fresh_agent_authority_allowed is None
                    or fresh_agent_authority_allowed()
                )
            )
            if should_claim_fresh_agent_authority:
                cutover_at = time.time()
                connection.execute(
                    "INSERT INTO mentat_agent_registry_state ("
                    "singleton, authority, migration_contract, source_kind, "
                    "source_sha256, source_agent_count, cutover_at"
                    ") VALUES (1, 'sqlite', ?, 'fresh', ?, 0, ?)",
                    (
                        AGENT_REGISTRY_AUTHORITY_CONTRACT,
                        EMPTY_AGENT_REGISTRY_SOURCE_SHA256,
                        cutover_at,
                    ),
                )
                if (
                    fresh_agent_authority_allowed is not None
                    and not fresh_agent_authority_allowed()
                ):
                    raise MentatDatabaseError(
                        "Retired Agent registry state changed during authority claim"
                    )
                fresh_agent_cutover_at = cutover_at
            if requires_disabled_foreign_keys:
                foreign_key_issue = connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchone()
                if foreign_key_issue is not None:
                    raise MentatDatabaseError(
                        "Mentat database migration produced invalid foreign keys"
                    )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if requires_disabled_foreign_keys and foreign_keys_were_enabled:
                connection.execute("PRAGMA foreign_keys = ON")
                restored_row = connection.execute("PRAGMA foreign_keys").fetchone()
                if restored_row is None or int(restored_row[0]) != 1:
                    raise MentatDatabaseError(
                        "Mentat database migration could not restore foreign keys"
                    )
    return fresh_agent_cutover_at


def _remove_exact_fresh_authority_if_unchanged(
    connection: sqlite3.Connection,
    data_dir: Path,
    cutover_at: float,
) -> bool:
    """Remove a raced fresh receipt only while its empty state remains exact."""

    connection.execute("BEGIN IMMEDIATE")
    try:
        if not legacy_agent_registry_artifacts_present(data_dir):
            connection.commit()
            return False
        receipt_rows = connection.execute(
            "SELECT authority, migration_contract, source_kind, source_sha256, "
            "source_agent_count, cutover_at FROM mentat_agent_registry_state"
        ).fetchall()
        agent_count = int(
            connection.execute("SELECT COUNT(*) FROM mentat_agents").fetchone()[0]
        )
        config_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM agent_runtime_configs"
            ).fetchone()[0]
        )
        expected_receipt = [
            (
                "sqlite",
                AGENT_REGISTRY_AUTHORITY_CONTRACT,
                "fresh",
                EMPTY_AGENT_REGISTRY_SOURCE_SHA256,
                0,
                cutover_at,
            )
        ]
        if (
            [tuple(row) for row in receipt_rows] != expected_receipt
            or agent_count
            or config_count
        ):
            connection.rollback()
            raise MentatDatabaseError(
                "Mentat Agent authority changed during fresh-state verification"
            )
        deleted = connection.execute(
            "DELETE FROM mentat_agent_registry_state WHERE singleton = 1 "
            "AND authority = 'sqlite' AND migration_contract = ? "
            "AND source_kind = 'fresh' AND source_sha256 = ? "
            "AND source_agent_count = 0 AND cutover_at = ?",
            (
                AGENT_REGISTRY_AUTHORITY_CONTRACT,
                EMPTY_AGENT_REGISTRY_SOURCE_SHA256,
                cutover_at,
            ),
        )
        if deleted.rowcount != 1:
            raise MentatDatabaseError(
                "Mentat Agent authority cleanup target changed"
            )
        connection.commit()
        remaining = sum(
            int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "mentat_agent_registry_state",
                "mentat_agents",
                "agent_runtime_configs",
            )
        )
        if remaining:
            raise MentatDatabaseError(
                "Mentat Agent authority cleanup could not be verified"
            )
        return True
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise


def _connect_with_identity_locked(
    data_dir: Path,
    *,
    claim_fresh_agent_authority: bool = True,
) -> tuple[sqlite3.Connection, dict[Path, tuple[int, int] | None]]:
    for attempt in range(DATABASE_OPEN_ATTEMPTS):
        try:
            return _connect_with_identity_once(
                data_dir,
                claim_fresh_agent_authority=claim_fresh_agent_authority,
            )
        except _TransientDatabaseSidecarRace as exc:
            if attempt + 1 == DATABASE_OPEN_ATTEMPTS:
                raise MentatDatabaseError(
                    "Mentat database sidecar changed during validation"
                ) from exc
            time.sleep(DATABASE_OPEN_RETRY_SECONDS)
    raise AssertionError("database open retry loop exhausted")


def _connect_with_identity_once(
    data_dir: Path,
    *,
    claim_fresh_agent_authority: bool = True,
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
        fresh_agent_cutover_at = migrate(
            connection,
            claim_fresh_agent_authority=claim_fresh_agent_authority,
            fresh_agent_authority_allowed=lambda: not legacy_agent_registry_artifacts_present(
                data_dir
            ),
        )
        if (
            fresh_agent_cutover_at is not None
            and legacy_agent_registry_artifacts_present(data_dir)
        ):
            if _remove_exact_fresh_authority_if_unchanged(
                connection,
                data_dir,
                fresh_agent_cutover_at,
            ):
                raise MentatDatabaseError(
                    "Retired Agent registry state changed during authority claim"
                )
        _secure_database_files(path)
        verified = _validate_database_set(path, private)
        if identities.get(path) is not None and verified.get(path) != identities[path]:
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


def connect_for_agent_registry_migration(data_dir: Path) -> sqlite3.Connection:
    """Open a destination without claiming empty authority before legacy import."""

    with DATABASE_OPEN_BARRIER:
        connection, _identities = _connect_with_identity_locked(
            data_dir,
            claim_fresh_agent_authority=False,
        )
    return connection


def _existing_console_dir(data_dir: Path) -> Path:
    """Validate the private Console hierarchy without creating any directory."""

    root_path = Path(data_dir)
    try:
        if root_path.is_symlink():
            raise MentatDatabaseError("Mentat data root must not be a symlink")
        root = root_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise MentatDatabaseError("Mentat private Console directory is unavailable") from exc
    if not root.is_dir():
        raise MentatDatabaseError("Mentat data root is not a directory")

    private = root / "private"
    console = private / "console"
    for directory, parent in ((private, root), (console, private)):
        try:
            details = directory.lstat()
            resolved = directory.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise MentatDatabaseError("Mentat private Console directory is unavailable") from exc
        if (
            stat.S_ISLNK(details.st_mode)
            or _is_reparse_point(details)
            or not stat.S_ISDIR(details.st_mode)
            or resolved.parent != parent
            or (
                os.name == "posix"
                and (details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700)
            )
        ):
            raise MentatDatabaseError("Mentat private Console directory is unsafe")
    return console


def _read_existing_database_file(
    path: Path,
    identity: tuple[int, int],
    maximum: int,
    remaining_total: int | None = None,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise MentatDatabaseError("Mentat database is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        ceiling = min(maximum, remaining_total) if remaining_total is not None else maximum
        if (
            (int(before.st_dev), int(before.st_ino)) != identity
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > ceiling
        ):
            raise MentatDatabaseError("Mentat database is unavailable")
        chunks: list[bytes] = []
        remaining = ceiling + 1
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
            if remaining <= 0:
                raise MentatDatabaseError("Mentat database is unavailable")
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(raw) != before.st_size
        ):
            raise MentatDatabaseError("Mentat database file changed while reading")
        return raw
    except OSError as exc:
        raise MentatDatabaseError("Mentat database is unavailable") from exc
    finally:
        os.close(descriptor)


@contextmanager
def connect_existing_readonly(data_dir: Path) -> Iterator[sqlite3.Connection]:
    """Read an existing database without migrations or source writes."""

    with DATABASE_OPEN_BARRIER:
        private = _existing_console_dir(data_dir)
        path = private / DATABASE_NAME
        identities = _validate_database_set(path, private)
        if identities[path] is None:
            raise MentatDatabaseError("Mentat database is unavailable")
        wal = Path(f"{path}-wal")
        shm = Path(f"{path}-shm")
        if (identities[wal] is None) != (identities[shm] is None):
            raise MentatDatabaseError("Mentat database sidecars are unavailable")
        snapshot = None
        captured: dict[Path, bytes] = {}
        connection = None
        try:
            if identities[wal] is None:
                uri = f"{path.resolve(strict=True).as_uri()}?mode=ro&immutable=1"
                connection = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
            else:
                snapshot = TemporaryDirectory(prefix="mentat-readonly-snapshot-")
                snapshot_path = Path(snapshot.name) / path.name
                files = (
                    (path, snapshot_path, MAX_READONLY_DATABASE_BYTES),
                    (wal, Path(f"{snapshot_path}-wal"), MAX_READONLY_WAL_BYTES),
                    (shm, Path(f"{snapshot_path}-shm"), MAX_READONLY_SHM_BYTES),
                )
                if sum(source.stat().st_size for source, _destination, _maximum in files) > MAX_READONLY_SNAPSHOT_BYTES:
                    raise MentatDatabaseError("Mentat database is unavailable")
                remaining_total = MAX_READONLY_SNAPSHOT_BYTES
                for source, destination, maximum in files:
                    captured[source] = _read_existing_database_file(
                        source,
                        identities[source],
                        maximum,
                        remaining_total,
                    )
                    remaining_total -= len(captured[source])
                    destination.write_bytes(captured[source])
                    if os.name != "nt":
                        destination.chmod(0o600)
                connection = sqlite3.connect(snapshot_path, timeout=5.0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA query_only = ON")
            if _validate_database_set(path, private) != identities:
                raise MentatDatabaseError("Mentat database file identity changed while opening")
            yield connection
        finally:
            if connection is not None:
                connection.close()
            if snapshot is not None:
                snapshot.cleanup()
            if captured:
                for source, raw in captured.items():
                    maximum = (
                        MAX_READONLY_DATABASE_BYTES if source == path
                        else MAX_READONLY_WAL_BYTES if source == wal
                        else MAX_READONLY_SHM_BYTES
                    )
                    if _read_existing_database_file(source, identities[source], maximum) != raw:
                        raise MentatDatabaseError("Mentat database file changed while reading")


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
