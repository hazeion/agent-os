"""Small SQLite foundation for private, project-owned Mentat runtime state."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
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
SCHEMA_VERSION = 46
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


# This is the current format's complete DDL, not an upgrade sequence.
# Structural receipts 1..45 retain the existing format46 journal contract.
CURRENT_BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        );

CREATE TABLE blobs (
            id TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            storage_key TEXT NOT NULL UNIQUE,
            byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
            state TEXT NOT NULL CHECK (state IN ('ready', 'deleting', 'missing')),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            delete_attempts INTEGER NOT NULL DEFAULT 0 CHECK (delete_attempts >= 0)
        );

CREATE TABLE attachments (
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

CREATE TABLE run_attachments (
            run_id TEXT NOT NULL,
            attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            direction TEXT NOT NULL CHECK (direction IN ('input', 'output')),
            ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
            created_at REAL NOT NULL,
            PRIMARY KEY (run_id, attachment_id, direction)
        );

CREATE TABLE task_artifacts (
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
        , project_id TEXT CHECK (
            project_id IS NULL OR (
                length(project_id) BETWEEN 1 AND 80
                AND substr(project_id, 1, 1) GLOB '[A-Za-z0-9]'
                AND project_id NOT GLOB '*[^A-Za-z0-9_.:-]*'
            )
        ), input_incarnation TEXT NOT NULL DEFAULT ''
        CHECK(typeof(input_incarnation)='text' AND length(input_incarnation) IN (0,32)));

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
        , revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1), system_role TEXT CHECK (
                system_role IS NULL OR system_role = 'direct'
            ), context_incarnation TEXT NOT NULL DEFAULT ''
        CHECK (typeof(context_incarnation)='text' AND length(context_incarnation) IN (0,32)));

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

CREATE TABLE "mentat_conversation_turns" (
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

CREATE TABLE "mentat_conversations" (
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
        , deliverable_incarnation TEXT NOT NULL DEFAULT ''
        CHECK(typeof(deliverable_incarnation)='text' AND length(deliverable_incarnation) IN (0,32)));

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
        , result_proof_digest TEXT CHECK (
                result_proof_digest IS NULL OR length(result_proof_digest) = 64
            ));

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

CREATE TABLE mentat_owner_auth_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            state TEXT NOT NULL CHECK (state IN ('unbootstrapped', 'bootstrap_open', 'active')),
            user_handle BLOB CHECK (user_handle IS NULL OR length(user_handle) = 32),
            bootstrap_user_handle BLOB CHECK (bootstrap_user_handle IS NULL OR length(bootstrap_user_handle) = 32),
            canonical_origin TEXT CHECK (canonical_origin IS NULL OR length(canonical_origin) BETWEEN 8 AND 253),
            rp_id TEXT CHECK (rp_id IS NULL OR length(rp_id) BETWEEN 1 AND 253),
            configuration_revision INTEGER NOT NULL DEFAULT 0 CHECK (configuration_revision >= 0),
            bootstrap_verifier TEXT,
            bootstrap_generation INTEGER NOT NULL DEFAULT 0 CHECK (bootstrap_generation >= 0),
            bootstrap_expires_at REAL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            updated_at REAL NOT NULL, auth_method TEXT NOT NULL
            DEFAULT 'passkey' CHECK (auth_method IN ('passkey', 'google')), owner_generation INTEGER
            NOT NULL DEFAULT 0 CHECK (owner_generation >= 0),
            CHECK (
                (state = 'unbootstrapped' AND user_handle IS NULL AND canonical_origin IS NULL AND rp_id IS NULL AND bootstrap_verifier IS NULL AND bootstrap_user_handle IS NULL AND bootstrap_expires_at IS NULL)
                OR (state = 'bootstrap_open' AND user_handle IS NULL AND canonical_origin IS NOT NULL AND rp_id IS NOT NULL AND bootstrap_verifier IS NOT NULL AND bootstrap_user_handle IS NOT NULL AND bootstrap_expires_at IS NOT NULL)
                OR (state = 'active' AND user_handle IS NOT NULL AND canonical_origin IS NOT NULL AND rp_id IS NOT NULL AND bootstrap_verifier IS NULL AND bootstrap_user_handle IS NULL AND bootstrap_expires_at IS NULL)
            )
        );

CREATE TABLE mentat_owner_auth_credentials (
            device_id TEXT PRIMARY KEY CHECK (length(device_id) BETWEEN 22 AND 128),
            credential_lookup_digest BLOB NOT NULL UNIQUE CHECK (length(credential_lookup_digest) = 32),
            cose_public_key BLOB NOT NULL CHECK (length(cose_public_key) BETWEEN 1 AND 4096),
            sign_count INTEGER NOT NULL DEFAULT 0 CHECK (sign_count >= 0),
            backup_eligible INTEGER NOT NULL DEFAULT 0 CHECK (backup_eligible = 0),
            backup_state INTEGER NOT NULL DEFAULT 0 CHECK (backup_state = 0),
            state TEXT NOT NULL CHECK (state IN ('active', 'revoked', 'suspected_clone')),
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            created_at REAL NOT NULL,
            revoked_at REAL,
            CHECK ((state = 'active' AND revoked_at IS NULL) OR (state != 'active' AND revoked_at IS NOT NULL))
        );

CREATE TABLE mentat_owner_auth_ceremonies (
            ceremony_id TEXT PRIMARY KEY CHECK (length(ceremony_id) BETWEEN 22 AND 128),
            purpose TEXT NOT NULL CHECK (purpose IN ('bootstrap', 'authentication', 'reauthentication', 'device_add', 'recovery')),
            challenge_digest BLOB NOT NULL CHECK (length(challenge_digest) = 32),
            configuration_revision INTEGER NOT NULL CHECK (configuration_revision >= 1),
            session_digest BLOB CHECK (session_digest IS NULL OR length(session_digest) = 32),
            session_revision INTEGER,
            recovery_id TEXT,
            credential_lookup_digest BLOB CHECK (credential_lookup_digest IS NULL OR length(credential_lookup_digest) = 32),
            expires_at REAL NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('pending', 'consumed', 'expired', 'cancelled')),
            created_at REAL NOT NULL,
            consumed_at REAL, owner_generation INTEGER
            NOT NULL DEFAULT 0 CHECK (owner_generation >= 0),
            CHECK ((session_digest IS NULL AND session_revision IS NULL) OR (session_digest IS NOT NULL AND session_revision >= 1)),
            CHECK ((purpose = 'recovery') = (recovery_id IS NOT NULL)),
            CHECK ((state = 'pending' AND consumed_at IS NULL) OR (state != 'pending' AND consumed_at IS NOT NULL))
        );

CREATE TABLE mentat_owner_auth_recovery_codes (
            recovery_id TEXT PRIMARY KEY CHECK (length(recovery_id) BETWEEN 22 AND 128),
            verifier TEXT NOT NULL CHECK (length(verifier) BETWEEN 80 AND 512),
            generation INTEGER NOT NULL CHECK (generation >= 1),
            state TEXT NOT NULL CHECK (state IN ('active', 'reserved', 'consumed', 'revoked')),
            reserved_ceremony_id TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            CHECK ((state = 'reserved') = (reserved_ceremony_id IS NOT NULL))
        );

CREATE TABLE mentat_owner_auth_rate_buckets (
            scope TEXT NOT NULL CHECK (scope IN ('authentication_start', 'recovery_submission', 'unsafe_request', 'security_management')),
            subject_digest BLOB NOT NULL CHECK (length(subject_digest) = 32),
            window_started_at REAL NOT NULL,
            used INTEGER NOT NULL CHECK (used BETWEEN 0 AND 60),
            PRIMARY KEY (scope, subject_digest)
        );

CREATE TABLE mentat_owner_auth_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event TEXT NOT NULL CHECK (event IN ('bootstrap_opened', 'bootstrap_completed', 'authentication_failed', 'authentication_succeeded', 'recovery_reserved', 'recovery_completed', 'recovery_rotated', 'credential_revoked', 'credential_clone_suspected', 'session_revoked', 'session_reauthenticated', 'sessions_signed_out', 'restore_sanitized')),
            subject_kind TEXT NOT NULL CHECK (subject_kind IN ('owner', 'credential', 'session', 'ceremony', 'admission')),
            subject_digest BLOB CHECK (subject_digest IS NULL OR length(subject_digest) = 32),
            count INTEGER NOT NULL DEFAULT 1 CHECK (count BETWEEN 1 AND 2147483647),
            occurred_at REAL NOT NULL
        );

CREATE TABLE mentat_owner_auth_rejection_audit (
            admission_class TEXT NOT NULL CHECK (admission_class IN ('authentication_start', 'recovery_submission', 'unsafe_request', 'security_management', 'sse')),
            window_started_at REAL NOT NULL,
            count INTEGER NOT NULL CHECK (count BETWEEN 1 AND 2147483647),
            PRIMARY KEY (admission_class, window_started_at)
        );

CREATE TABLE mentat_owner_auth_sse_reservations (
            reservation_id TEXT PRIMARY KEY CHECK (length(reservation_id) BETWEEN 22 AND 128),
            session_digest BLOB NOT NULL REFERENCES mentat_owner_auth_sessions(session_digest) ON DELETE CASCADE CHECK (length(session_digest) = 32),
            session_revision INTEGER NOT NULL CHECK (session_revision >= 1),
            created_at REAL NOT NULL
        );

CREATE TABLE mentat_owner_auth_notices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            notice TEXT NOT NULL CHECK (notice IN ('restore_invalidated_sessions', 'restore_snapshot_credentials_restored')),
            created_at REAL NOT NULL,
            acknowledged_at REAL
        );

CREATE TABLE mentat_owner_google_configuration (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            client_id TEXT NOT NULL CHECK (length(client_id) BETWEEN 1 AND 255),
            canonical_origin TEXT NOT NULL CHECK (length(canonical_origin) BETWEEN 8 AND 253),
            credential_source TEXT NOT NULL CHECK (credential_source = 'environment'),
            requires_reconciliation INTEGER NOT NULL DEFAULT 1 CHECK (requires_reconciliation IN (0, 1)),
            revision INTEGER NOT NULL CHECK (revision >= 1)
        );

CREATE TABLE mentat_owner_google_principal (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            issuer TEXT NOT NULL CHECK (issuer = 'https://accounts.google.com'),
            subject TEXT NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
            email TEXT NOT NULL CHECK (length(email) BETWEEN 3 AND 254),
            principal_digest BLOB NOT NULL UNIQUE CHECK (length(principal_digest) = 32),
            owner_generation INTEGER NOT NULL CHECK (owner_generation >= 1),
            configuration_revision INTEGER NOT NULL CHECK (configuration_revision >= 1)
        );

CREATE TABLE "mentat_owner_auth_sessions" (
            session_digest BLOB PRIMARY KEY CHECK (length(session_digest) = 32),
            csrf_digest BLOB NOT NULL UNIQUE CHECK (length(csrf_digest) = 32),
            device_id TEXT REFERENCES mentat_owner_auth_credentials(device_id) ON DELETE RESTRICT,
            auth_method TEXT NOT NULL DEFAULT 'passkey' CHECK (auth_method IN ('passkey', 'google')),
            owner_generation INTEGER NOT NULL DEFAULT 0 CHECK (owner_generation >= 0),
            principal_digest BLOB CHECK (principal_digest IS NULL OR length(principal_digest) = 32),
            state TEXT NOT NULL CHECK (state IN ('active', 'revoked', 'expired')),
            created_at REAL NOT NULL,
            reauthenticated_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            idle_expires_at REAL NOT NULL,
            absolute_expires_at REAL NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
            revoked_at REAL,
            CHECK (idle_expires_at >= created_at AND absolute_expires_at >= created_at),
            CHECK ((state = 'active' AND revoked_at IS NULL) OR (state != 'active' AND revoked_at IS NOT NULL)),
            CHECK (
                (auth_method = 'passkey' AND device_id IS NOT NULL AND principal_digest IS NULL)
                OR (auth_method = 'google' AND device_id IS NULL AND principal_digest IS NOT NULL AND owner_generation >= 1 AND reauthenticated_at = 0)
            )
        );

CREATE TABLE mentat_owner_google_transactions (
        transaction_id TEXT PRIMARY KEY CHECK (length(transaction_id) = 32),
        state_digest BLOB NOT NULL UNIQUE CHECK (length(state_digest) = 32),
        browser_digest BLOB NOT NULL CHECK (length(browser_digest) = 32),
        owner_generation INTEGER NOT NULL CHECK (owner_generation >= 1),
        configuration_revision INTEGER NOT NULL CHECK (configuration_revision >= 1),
        principal_digest BLOB NOT NULL CHECK (length(principal_digest) = 32),
        client_id TEXT NOT NULL CHECK (length(client_id) BETWEEN 1 AND 255),
        canonical_origin TEXT NOT NULL CHECK (length(canonical_origin) BETWEEN 8 AND 253),
        nonce TEXT,
        code_verifier TEXT,
        state TEXT NOT NULL CHECK (state IN ('pending', 'consumed', 'verified', 'failed', 'cancelled')),
        created_at REAL NOT NULL,
        expires_at REAL NOT NULL CHECK (expires_at = created_at + 300),
        terminal_at REAL,
        CHECK ((state = 'pending' AND length(nonce) = 43 AND nonce IS NOT NULL
                AND length(code_verifier) = 43 AND code_verifier IS NOT NULL AND terminal_at IS NULL)
            OR (state != 'pending' AND nonce IS NULL AND code_verifier IS NULL AND terminal_at IS NOT NULL))
    );

CREATE TABLE mentat_project_context_scopes (
        id TEXT NOT NULL PRIMARY KEY CHECK (typeof(id) = 'text' AND length(id) = 46),
        project_id TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        created_at REAL NOT NULL CHECK (created_at > 0),
        retired_at REAL CHECK (retired_at IS NULL OR retired_at > 0)
    );

CREATE TABLE mentat_project_context_versions (
        id TEXT NOT NULL PRIMARY KEY CHECK (typeof(id) = 'text' AND length(id) = 48),
        scope_id TEXT NOT NULL REFERENCES mentat_project_context_scopes(id) ON DELETE RESTRICT,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        brief TEXT NOT NULL CHECK (length(CAST(brief AS BLOB)) <= 16384),
        files_digest TEXT NOT NULL CHECK (typeof(files_digest) = 'text' AND length(files_digest) = 64),
        created_at REAL NOT NULL CHECK (created_at > 0),
        UNIQUE(scope_id, revision)
    );

CREATE TABLE mentat_project_context_files (
        context_id TEXT NOT NULL REFERENCES mentat_project_context_versions(id) ON DELETE RESTRICT,
        attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 15),
        PRIMARY KEY(context_id, attachment_id),
        UNIQUE(context_id, ordinal)
    );

CREATE TABLE mentat_project_context_access_state (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        approval_epoch BLOB NOT NULL CHECK(typeof(approval_epoch)='blob' AND length(approval_epoch)=32)
    );

CREATE TABLE mentat_project_context_grants (
        scope_id TEXT NOT NULL REFERENCES mentat_project_context_scopes(id) ON DELETE RESTRICT,
        agent_id TEXT NOT NULL,
        agent_incarnation TEXT NOT NULL CHECK (typeof(agent_incarnation)='text' AND length(agent_incarnation)=32),
        context_id TEXT REFERENCES mentat_project_context_versions(id) ON DELETE RESTRICT,
        revision INTEGER NOT NULL CHECK (typeof(revision)='integer' AND revision BETWEEN 1 AND 9007199254740991),
        state TEXT NOT NULL CHECK (state IN ('active','revoked')),
        reason TEXT CHECK (reason IN ('owner','project_deleted','agent_deleted','restored','context_pruned')),
        updated_at REAL NOT NULL CHECK (updated_at>0),
        PRIMARY KEY(scope_id,agent_id),
        CHECK ((state='active' AND revision<9007199254740991 AND context_id IS NOT NULL AND reason IS NULL) OR (state='revoked' AND reason IS NOT NULL))
    );

CREATE TABLE mentat_project_context_staged (
        attachment_id TEXT NOT NULL PRIMARY KEY REFERENCES attachments(id) ON DELETE CASCADE,
        project_id TEXT NOT NULL,
        created_at REAL NOT NULL CHECK(created_at>0)
    );

CREATE TABLE mentat_task_input_scopes (
        id TEXT NOT NULL PRIMARY KEY CHECK(typeof(id)='text' AND length(id)=49),
        task_id TEXT NOT NULL,
        task_incarnation TEXT NOT NULL CHECK(length(task_incarnation)=32),
        project_scope_id TEXT NOT NULL REFERENCES mentat_project_context_scopes(id) ON DELETE RESTRICT,
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 9007199254740991),
        created_at REAL NOT NULL CHECK(created_at>0),
        retired_at REAL CHECK(retired_at IS NULL OR retired_at>=created_at)
    );

CREATE TABLE mentat_task_input_versions (
        id TEXT NOT NULL PRIMARY KEY CHECK(typeof(id)='text' AND length(id)=43),
        scope_id TEXT NOT NULL REFERENCES mentat_task_input_scopes(id) ON DELETE RESTRICT,
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 9007199254740991),
        task_revision INTEGER NOT NULL CHECK(typeof(task_revision)='integer' AND task_revision>0),
        agent_id TEXT NOT NULL,
        agent_incarnation TEXT NOT NULL CHECK(length(agent_incarnation)=32),
        context_id TEXT NOT NULL REFERENCES mentat_project_context_versions(id) ON DELETE RESTRICT,
        grant_revision INTEGER NOT NULL CHECK(typeof(grant_revision)='integer' AND grant_revision>0),
        binding_digest TEXT NOT NULL CHECK(length(binding_digest)=64),
        instructions TEXT NOT NULL,
        files_digest TEXT NOT NULL CHECK(length(files_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0),
        UNIQUE(scope_id,revision)
    );

CREATE TABLE mentat_task_input_files (
        input_id TEXT NOT NULL REFERENCES mentat_task_input_versions(id) ON DELETE RESTRICT,
        attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL CHECK(typeof(ordinal)='integer' AND ordinal BETWEEN 0 AND 7),
        PRIMARY KEY(input_id,ordinal), UNIQUE(input_id,attachment_id)
    );

CREATE TABLE mentat_run_input_receipts (
        run_id TEXT NOT NULL PRIMARY KEY REFERENCES mentat_runs(id) ON DELETE RESTRICT,
        input_id TEXT NOT NULL REFERENCES mentat_task_input_versions(id) ON DELETE RESTRICT,
        task_scope_id TEXT NOT NULL REFERENCES mentat_task_input_scopes(id) ON DELETE RESTRICT,
        task_id TEXT NOT NULL,
        task_incarnation TEXT NOT NULL CHECK(length(task_incarnation)=32),
        task_revision INTEGER NOT NULL CHECK(typeof(task_revision)='integer' AND task_revision>0),
        project_scope_id TEXT NOT NULL REFERENCES mentat_project_context_scopes(id) ON DELETE RESTRICT,
        project_id TEXT NOT NULL,
        agent_id TEXT NOT NULL,
        agent_incarnation TEXT NOT NULL CHECK(length(agent_incarnation)=32),
        runtime_type TEXT NOT NULL CHECK(length(runtime_type) BETWEEN 1 AND 32),
        runtime_config_id TEXT NOT NULL CHECK(length(runtime_config_id) BETWEEN 1 AND 128),
        context_id TEXT NOT NULL REFERENCES mentat_project_context_versions(id) ON DELETE RESTRICT,
        context_revision INTEGER NOT NULL CHECK(typeof(context_revision)='integer' AND context_revision>0),
        grant_revision INTEGER NOT NULL CHECK(typeof(grant_revision)='integer' AND grant_revision>0),
        runtime_binding_digest TEXT NOT NULL CHECK(length(runtime_binding_digest)=64),
        input_binding_digest TEXT NOT NULL CHECK(length(input_binding_digest)=64),
        capabilities_digest TEXT NOT NULL CHECK(length(capabilities_digest)=64),
        qualification_digest TEXT NOT NULL CHECK(length(qualification_digest)=64),
        approval_digest TEXT NOT NULL CHECK(length(approval_digest)=64),
        objective_digest TEXT NOT NULL CHECK(length(objective_digest)=64),
        allowed_tools_digest TEXT NOT NULL CHECK(length(allowed_tools_digest)=64),
        limits_digest TEXT NOT NULL CHECK(length(limits_digest)=64),
        manifest_digest TEXT NOT NULL CHECK(length(manifest_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0)
    );

CREATE TABLE mentat_run_input_files (
        run_id TEXT NOT NULL REFERENCES mentat_run_input_receipts(run_id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL CHECK(typeof(ordinal)='integer' AND ordinal BETWEEN 0 AND 7),
        attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE RESTRICT,
        blob_id TEXT NOT NULL REFERENCES blobs(id) ON DELETE RESTRICT,
        sha256 TEXT NOT NULL CHECK(length(sha256)=64),
        byte_size INTEGER NOT NULL CHECK(typeof(byte_size)='integer' AND byte_size>=0),
        kind TEXT NOT NULL CHECK(kind IN ('image','text')),
        mime_type TEXT NOT NULL,
        PRIMARY KEY(run_id,ordinal), UNIQUE(run_id,attachment_id)
    );

CREATE TABLE mentat_deliverable_slots (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=44),
        project_id TEXT NOT NULL,
        project_incarnation TEXT NOT NULL CHECK(length(project_incarnation)=32),
        slot TEXT NOT NULL CHECK(slot IN ('layout','products','steps')),
        head_revision INTEGER NOT NULL CHECK(typeof(head_revision)='integer' AND head_revision BETWEEN 1 AND 32),
        created_at REAL NOT NULL CHECK(created_at>0),
        retired_at REAL CHECK(retired_at IS NULL OR retired_at>=created_at),
        UNIQUE(project_incarnation,slot)
    );

CREATE TABLE mentat_deliverable_versions (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=52),
        slot_id TEXT NOT NULL REFERENCES mentat_deliverable_slots(id) ON DELETE RESTRICT,
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 32),
        origin TEXT NOT NULL CHECK(origin IN ('owner_edit','generated')),
        source_version_id TEXT REFERENCES mentat_deliverable_versions(id) ON DELETE RESTRICT,
        associated_task_id TEXT,
        associated_task_incarnation TEXT CHECK(associated_task_incarnation IS NULL OR length(associated_task_incarnation)=32),
        content_json TEXT NOT NULL CHECK(length(content_json) BETWEEN 2 AND 65536),
        content_digest TEXT NOT NULL CHECK(length(content_digest)=64),
        source_run_id TEXT,
        source_receipt_digest TEXT CHECK(source_receipt_digest IS NULL OR length(source_receipt_digest)=64),
        source_task_id TEXT,
        source_task_incarnation TEXT CHECK(source_task_incarnation IS NULL OR length(source_task_incarnation)=32),
        created_at REAL NOT NULL CHECK(created_at>0),
        UNIQUE(slot_id,revision),
        CHECK ((associated_task_id IS NULL AND associated_task_incarnation IS NULL)
            OR (associated_task_id IS NOT NULL AND associated_task_incarnation IS NOT NULL)),
        CHECK ((origin='owner_edit' AND source_run_id IS NULL AND source_receipt_digest IS NULL AND source_task_id IS NULL AND source_task_incarnation IS NULL)
            OR (origin='generated' AND source_run_id IS NOT NULL AND source_receipt_digest IS NOT NULL AND source_task_id IS NOT NULL AND source_task_incarnation IS NOT NULL))
    );

CREATE TABLE mentat_deliverable_files (
        version_id TEXT NOT NULL REFERENCES mentat_deliverable_versions(id) ON DELETE RESTRICT,
        attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE RESTRICT,
        role TEXT NOT NULL CHECK(role='preview'),
        blob_sha256 TEXT NOT NULL CHECK(length(blob_sha256)=64),
        PRIMARY KEY(version_id,role)
    );

CREATE TABLE mentat_deliverable_review_state (
        singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        confirmation_epoch BLOB NOT NULL CHECK(length(confirmation_epoch)=32),
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 0 AND 9007199254740991)
    );

CREATE TABLE mentat_deliverable_reviews (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=51),
        project_id TEXT NOT NULL,
        project_incarnation TEXT NOT NULL CHECK(length(project_incarnation)=32),
        project_revision INTEGER NOT NULL CHECK(typeof(project_revision)='integer' AND project_revision>0),
        revision INTEGER NOT NULL UNIQUE CHECK(typeof(revision)='integer' AND revision>0),
        action TEXT NOT NULL CHECK(action IN ('accept','request_changes')),
        note TEXT NOT NULL CHECK(length(note)<=2000),
        heads_digest TEXT NOT NULL CHECK(length(heads_digest)=64),
        request_digest TEXT NOT NULL CHECK(length(request_digest)=64),
        confirmation_digest TEXT NOT NULL UNIQUE CHECK(length(confirmation_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0)
    );

CREATE TABLE mentat_deliverable_review_versions (
        review_id TEXT NOT NULL REFERENCES mentat_deliverable_reviews(id) ON DELETE RESTRICT,
        slot TEXT NOT NULL CHECK(slot IN ('layout','products','steps')),
        version_id TEXT NOT NULL REFERENCES mentat_deliverable_versions(id) ON DELETE RESTRICT,
        affected INTEGER NOT NULL CHECK(affected IN (0,1)),
        PRIMARY KEY(review_id,slot), UNIQUE(review_id,version_id)
    );

CREATE TABLE mentat_plan_scopes (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=43),
        project_id TEXT NOT NULL,
        project_incarnation TEXT NOT NULL CHECK(length(project_incarnation)=32),
        context_scope_id TEXT NOT NULL UNIQUE REFERENCES mentat_project_context_scopes(id) ON DELETE RESTRICT,
        head_revision INTEGER NOT NULL CHECK(typeof(head_revision)='integer' AND head_revision BETWEEN 1 AND 32),
        created_at REAL NOT NULL CHECK(created_at>0),
        retired_at REAL CHECK(retired_at IS NULL OR retired_at>=created_at)
    );

CREATE TABLE mentat_plan_input_refs (
        version_id TEXT NOT NULL REFERENCES mentat_plan_versions(id) ON DELETE RESTRICT,
        input_id TEXT NOT NULL REFERENCES mentat_task_input_versions(id) ON DELETE RESTRICT,
        PRIMARY KEY(version_id,input_id)
    );

CREATE TABLE mentat_inbox_items (
        id TEXT PRIMARY KEY CHECK(length(id)=43 AND id GLOB 'inbox_item_[0-9a-f]*'),
        kind TEXT NOT NULL CHECK(kind='result_review'),
        source_id TEXT NOT NULL CHECK(length(source_id) BETWEEN 1 AND 80),
        source_incarnation TEXT NOT NULL CHECK(length(source_incarnation)=32),
        generation_digest TEXT NOT NULL CHECK(length(generation_digest)=64),
        heads_json TEXT NOT NULL CHECK(length(heads_json) BETWEEN 2 AND 256),
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 16),
        created_at REAL NOT NULL CHECK(created_at>0),
        updated_at REAL NOT NULL CHECK(updated_at>=created_at),
        read_at REAL CHECK(read_at IS NULL OR read_at>=created_at),
        acknowledged_at REAL CHECK(acknowledged_at IS NULL OR acknowledged_at>=created_at),
        resolved_at REAL CHECK(resolved_at IS NULL OR resolved_at>=created_at),
        last_action_digest TEXT CHECK(last_action_digest IS NULL OR length(last_action_digest)=64),
        last_expected_revision INTEGER CHECK(last_expected_revision IS NULL OR last_expected_revision BETWEEN 1 AND 15),
        UNIQUE(kind,source_id,source_incarnation,generation_digest)
    );

CREATE TABLE mentat_run_identities (
        run_id TEXT PRIMARY KEY REFERENCES mentat_runs(id) ON DELETE CASCADE,
        incarnation TEXT NOT NULL UNIQUE CHECK(
            length(incarnation)=32 AND incarnation NOT GLOB '*[^0-9a-f]*'
        ),
        created_at TEXT NOT NULL CHECK(length(created_at) BETWEEN 1 AND 64)
    );

CREATE TABLE mentat_run_attention (
        slot_id INTEGER PRIMARY KEY,
        run_id TEXT NOT NULL CHECK(length(run_id) BETWEEN 1 AND 128),
        incarnation TEXT NOT NULL CHECK(length(incarnation)=32 AND incarnation NOT GLOB '*[^0-9a-f]*'),
        item_id TEXT CHECK(item_id IS NULL OR length(item_id)=43 AND item_id GLOB 'inbox_item_[0-9a-f]*'),
        revision INTEGER NOT NULL DEFAULT 0 CHECK(typeof(revision)='integer' AND revision BETWEEN 0 AND 2147483647),
        created_at REAL CHECK(created_at IS NULL OR created_at>0),
        updated_at REAL CHECK(updated_at IS NULL OR updated_at>=created_at),
        read_at REAL CHECK(read_at IS NULL OR read_at>=created_at),
        acknowledged_at REAL CHECK(acknowledged_at IS NULL OR acknowledged_at>=created_at),
        resolved_at REAL CHECK(resolved_at IS NULL OR resolved_at>=created_at),
        last_action_digest TEXT CHECK(last_action_digest IS NULL OR length(last_action_digest)=64),
        last_expected_revision INTEGER CHECK(last_expected_revision IS NULL OR last_expected_revision BETWEEN 1 AND 2147483646),
        retired_at REAL CHECK(retired_at IS NULL OR retired_at>0),
        retired_source TEXT CHECK(retired_source IS NULL OR retired_source IN ('console','task_dispatch')),
        retired_status TEXT CHECK(retired_status IS NULL OR retired_status IN ('completed','failed','cancelled','stopped','interrupted')),
        retired_dispatch_state TEXT CHECK(retired_dispatch_state IS NULL OR retired_dispatch_state IN ('legacy','reserved','submitting','accepted','rejected','unknown')),
        retired_partial INTEGER CHECK(retired_partial IS NULL OR retired_partial IN (0,1)),
        retired_terminal_finalized INTEGER CHECK(retired_terminal_finalized IS NULL OR retired_terminal_finalized IN (0,1)),
        retired_state_revision INTEGER CHECK(retired_state_revision IS NULL OR retired_state_revision>=1),
        retired_task_id TEXT CHECK(retired_task_id IS NULL OR length(retired_task_id) BETWEEN 1 AND 160),
        retired_conversation_id TEXT CHECK(retired_conversation_id IS NULL OR length(retired_conversation_id) BETWEEN 1 AND 128),
        retired_agent_id TEXT CHECK(retired_agent_id IS NULL OR length(retired_agent_id) BETWEEN 1 AND 128),
        retired_run_created_at TEXT CHECK(retired_run_created_at IS NULL OR length(retired_run_created_at) BETWEEN 1 AND 64),
        retired_run_updated_at TEXT CHECK(retired_run_updated_at IS NULL OR length(retired_run_updated_at) BETWEEN 1 AND 64),
        retired_run_completed_at TEXT CHECK(retired_run_completed_at IS NULL OR length(retired_run_completed_at) BETWEEN 1 AND 64),
        CHECK((item_id IS NULL AND revision=0 AND created_at IS NULL AND updated_at IS NULL
               AND read_at IS NULL AND acknowledged_at IS NULL AND resolved_at IS NULL
               AND last_action_digest IS NULL AND last_expected_revision IS NULL AND retired_at IS NULL)
           OR (item_id IS NOT NULL AND revision>=1 AND created_at>0 AND updated_at>=created_at)),
        CHECK((retired_at IS NULL AND retired_source IS NULL AND retired_status IS NULL
               AND retired_dispatch_state IS NULL AND retired_partial IS NULL
               AND retired_terminal_finalized IS NULL AND retired_state_revision IS NULL
               AND retired_task_id IS NULL AND retired_conversation_id IS NULL
               AND retired_agent_id IS NULL AND retired_run_created_at IS NULL
               AND retired_run_updated_at IS NULL AND retired_run_completed_at IS NULL)
           OR (retired_at IS NOT NULL AND item_id IS NOT NULL AND retired_source IS NOT NULL
               AND retired_status IS NOT NULL AND retired_dispatch_state IS NOT NULL
               AND retired_partial IS NOT NULL AND retired_terminal_finalized IS NOT NULL
               AND retired_state_revision IS NOT NULL AND retired_run_created_at IS NOT NULL
               AND retired_run_updated_at IS NOT NULL))
    );

CREATE TABLE "mentat_plan_versions" (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=45),
        scope_id TEXT NOT NULL REFERENCES mentat_plan_scopes(id) ON DELETE RESTRICT,
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 32),
        project_revision INTEGER NOT NULL CHECK(typeof(project_revision)='integer' AND project_revision>0),
        format INTEGER NOT NULL CHECK(format IN (1,2)),
        content_json TEXT NOT NULL CHECK(
            (format=1 AND length(content_json) BETWEEN 2 AND 16384) OR
            (format=2 AND length(CAST(content_json AS BLOB)) BETWEEN 2 AND 24576)
        ),
        content_digest TEXT NOT NULL CHECK(length(content_digest)=64),
        origin TEXT NOT NULL CHECK(origin='owner_edit'),
        created_at REAL NOT NULL CHECK(created_at>0),
        UNIQUE(scope_id,revision)
    );

CREATE TABLE mentat_project_lead_versions (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=42 AND id GLOB 'lead_role_[0-9a-f]*'),
        project_id TEXT NOT NULL CHECK(length(project_id) BETWEEN 1 AND 80),
        project_incarnation TEXT NOT NULL CHECK(length(project_incarnation)=32),
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 32),
        action TEXT NOT NULL CHECK(action IN ('select','clear')),
        agent_id TEXT CHECK(agent_id IS NULL OR length(agent_id) BETWEEN 1 AND 128),
        agent_incarnation TEXT CHECK(agent_incarnation IS NULL OR length(agent_incarnation)=32),
        agent_revision INTEGER CHECK(agent_revision IS NULL OR typeof(agent_revision)='integer' AND agent_revision>=1),
        binding_digest TEXT CHECK(binding_digest IS NULL OR length(binding_digest)=64),
        context_id TEXT CHECK(context_id IS NULL OR length(context_id)=48),
        grant_revision INTEGER CHECK(grant_revision IS NULL OR typeof(grant_revision)='integer' AND grant_revision>=1),
        created_at REAL NOT NULL CHECK(created_at>0),
        UNIQUE(project_incarnation,revision),
        CHECK((action='clear' AND agent_id IS NULL AND agent_incarnation IS NULL
               AND agent_revision IS NULL AND binding_digest IS NULL
               AND context_id IS NULL AND grant_revision IS NULL)
           OR (action='select' AND agent_id IS NOT NULL AND agent_incarnation IS NOT NULL
               AND agent_revision IS NOT NULL AND binding_digest IS NOT NULL
               AND ((context_id IS NULL AND grant_revision IS NULL)
                    OR (context_id IS NOT NULL AND grant_revision IS NOT NULL))))
    );

CREATE TABLE mentat_project_planning_input_versions (
        id TEXT NOT NULL PRIMARY KEY CHECK(length(id)=46 AND id GLOB 'project_input_[0-9a-f]*'),
        project_id TEXT NOT NULL CHECK(length(project_id) BETWEEN 1 AND 80),
        project_incarnation TEXT NOT NULL CHECK(length(project_incarnation)=32),
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 32),
        project_revision INTEGER NOT NULL CHECK(typeof(project_revision)='integer' AND project_revision>0),
        lead_role_id TEXT NOT NULL REFERENCES mentat_project_lead_versions(id) ON DELETE RESTRICT,
        lead_revision INTEGER NOT NULL CHECK(typeof(lead_revision)='integer' AND lead_revision BETWEEN 1 AND 32),
        agent_id TEXT NOT NULL CHECK(length(agent_id) BETWEEN 1 AND 128),
        agent_incarnation TEXT NOT NULL CHECK(length(agent_incarnation)=32),
        agent_revision INTEGER NOT NULL CHECK(typeof(agent_revision)='integer' AND agent_revision>0),
        binding_digest TEXT NOT NULL CHECK(length(binding_digest)=64),
        context_id TEXT NOT NULL REFERENCES mentat_project_context_versions(id) ON DELETE RESTRICT,
        grant_revision INTEGER NOT NULL CHECK(typeof(grant_revision)='integer' AND grant_revision>0),
        instructions TEXT NOT NULL,
        files_digest TEXT NOT NULL CHECK(length(files_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0),
        UNIQUE(project_incarnation,revision)
    );

CREATE TABLE mentat_project_planning_input_files (
        input_id TEXT NOT NULL REFERENCES mentat_project_planning_input_versions(id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL CHECK(typeof(ordinal)='integer' AND ordinal BETWEEN 0 AND 7),
        attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE RESTRICT,
        blob_id TEXT NOT NULL REFERENCES blobs(id) ON DELETE RESTRICT,
        sha256 TEXT NOT NULL CHECK(length(sha256)=64),
        byte_size INTEGER NOT NULL CHECK(typeof(byte_size)='integer' AND byte_size>=0),
        kind TEXT NOT NULL CHECK(kind IN ('image','text')),
        mime_type TEXT NOT NULL,
        PRIMARY KEY(input_id,ordinal), UNIQUE(input_id,attachment_id)
    );

CREATE TABLE mentat_project_planning_input_legacy (
        input_id TEXT NOT NULL PRIMARY KEY REFERENCES mentat_project_planning_input_versions(id) ON DELETE RESTRICT
    );

CREATE TABLE mentat_project_planning_input_actions (
        action_id TEXT NOT NULL PRIMARY KEY CHECK(length(action_id)=53 AND action_id GLOB 'project_input_action_[0-9a-f]*'),
        input_id TEXT NOT NULL UNIQUE REFERENCES mentat_project_planning_input_versions(id) ON DELETE RESTRICT,
        scope_token TEXT NOT NULL CHECK(length(scope_token)=64),
        selection_token TEXT NOT NULL CHECK(length(selection_token)=64),
        request_digest TEXT NOT NULL CHECK(length(request_digest)=64),
        source_kind TEXT NOT NULL CHECK(source_kind IN ('legacy','owner')),
        created_at REAL NOT NULL CHECK(created_at>0)
    );

CREATE TABLE "mentat_runs" (
            id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 128),
            source TEXT NOT NULL CHECK (source IN ('console', 'task_dispatch', 'project_proposal')),
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
        , conversation_id TEXT CHECK (
                conversation_id IS NULL OR length(conversation_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_conversations(id) ON DELETE SET NULL, turn_id TEXT CHECK (
                turn_id IS NULL OR length(turn_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_conversation_turns(id) ON DELETE SET NULL, retry_of_run_id TEXT CHECK (
                retry_of_run_id IS NULL OR length(retry_of_run_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_runs(id) ON DELETE SET NULL, resume_of_run_id TEXT CHECK (
                resume_of_run_id IS NULL OR length(resume_of_run_id) BETWEEN 1 AND 128
            ) REFERENCES mentat_runs(id) ON DELETE SET NULL, agent_revision INTEGER CHECK (
                agent_revision IS NULL OR agent_revision >= 1
            ), runtime_config_revision INTEGER CHECK (
                runtime_config_revision IS NULL OR runtime_config_revision >= 1
            ), execution_config_json TEXT CHECK (
                execution_config_json IS NULL OR length(execution_config_json) <= 16384
            ), execution_config_digest TEXT CHECK (
                execution_config_digest IS NULL OR length(execution_config_digest) = 64
            ), capacity_scope_digest TEXT CHECK (
                capacity_scope_digest IS NULL OR length(capacity_scope_digest) = 64
            ), admitted_capacity_limit INTEGER CHECK (
                admitted_capacity_limit IS NULL OR admitted_capacity_limit BETWEEN 1 AND 32
            ), runtime_execution_json TEXT CHECK (
                runtime_execution_json IS NULL
                OR length(runtime_execution_json) <= 2048
            ), runtime_execution_digest TEXT CHECK (
                runtime_execution_digest IS NULL
                OR length(runtime_execution_digest) = 64
            ), terminal_finalized INTEGER NOT NULL DEFAULT 0 CHECK (
                terminal_finalized IN (0, 1)
                AND (
                    terminal_finalized = 0
                    OR status IN (
                        'completed', 'failed', 'cancelled', 'stopped', 'interrupted'
                    )
                )
            ));

CREATE TABLE mentat_project_proposal_input_receipts (
        run_id TEXT NOT NULL PRIMARY KEY REFERENCES mentat_runs(id) ON DELETE RESTRICT,
        input_id TEXT NOT NULL REFERENCES mentat_project_planning_input_versions(id) ON DELETE RESTRICT,
        project_id TEXT NOT NULL CHECK(length(project_id) BETWEEN 1 AND 80),
        project_incarnation TEXT NOT NULL CHECK(length(project_incarnation)=32),
        project_revision INTEGER NOT NULL CHECK(typeof(project_revision)='integer' AND project_revision>0),
        lead_role_id TEXT NOT NULL REFERENCES mentat_project_lead_versions(id) ON DELETE RESTRICT,
        lead_revision INTEGER NOT NULL CHECK(typeof(lead_revision)='integer' AND lead_revision>0),
        agent_id TEXT NOT NULL CHECK(length(agent_id) BETWEEN 1 AND 128),
        agent_incarnation TEXT NOT NULL CHECK(length(agent_incarnation)=32),
        agent_revision INTEGER NOT NULL CHECK(typeof(agent_revision)='integer' AND agent_revision>0),
        runtime_type TEXT NOT NULL CHECK(length(runtime_type) BETWEEN 1 AND 32),
        runtime_config_id TEXT NOT NULL CHECK(length(runtime_config_id) BETWEEN 1 AND 128),
        runtime_binding_digest TEXT NOT NULL CHECK(length(runtime_binding_digest)=64),
        context_id TEXT NOT NULL REFERENCES mentat_project_context_versions(id) ON DELETE RESTRICT,
        context_revision INTEGER NOT NULL CHECK(typeof(context_revision)='integer' AND context_revision>0),
        grant_revision INTEGER NOT NULL CHECK(typeof(grant_revision)='integer' AND grant_revision>0),
        capabilities_digest TEXT NOT NULL CHECK(length(capabilities_digest)=64),
        qualification_digest TEXT NOT NULL CHECK(length(qualification_digest)=64),
        authorization_digest TEXT NOT NULL CHECK(length(authorization_digest)=64),
        operations_digest TEXT NOT NULL CHECK(length(operations_digest)=64),
        limits_digest TEXT NOT NULL CHECK(length(limits_digest)=64),
        manifest_digest TEXT NOT NULL CHECK(length(manifest_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0)
    );

CREATE TABLE mentat_project_proposal_input_files (
        run_id TEXT NOT NULL REFERENCES mentat_project_proposal_input_receipts(run_id) ON DELETE RESTRICT,
        ordinal INTEGER NOT NULL CHECK(typeof(ordinal)='integer' AND ordinal BETWEEN 0 AND 7),
        attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE RESTRICT,
        blob_id TEXT NOT NULL REFERENCES blobs(id) ON DELETE RESTRICT,
        sha256 TEXT NOT NULL CHECK(length(sha256)=64),
        byte_size INTEGER NOT NULL CHECK(typeof(byte_size)='integer' AND byte_size>=0),
        kind TEXT NOT NULL CHECK(kind IN ('image','text')),
        mime_type TEXT NOT NULL,
        PRIMARY KEY(run_id,ordinal), UNIQUE(run_id,attachment_id)
    );

CREATE TABLE mentat_project_worker_generations (
        run_id TEXT NOT NULL PRIMARY KEY,
        source TEXT NOT NULL CHECK(source='project_proposal'),
        generation TEXT NOT NULL UNIQUE CHECK(length(generation)=32),
        authority_epoch BLOB NOT NULL CHECK(typeof(authority_epoch)='blob' AND length(authority_epoch)=32),
        input_manifest_digest TEXT NOT NULL CHECK(length(input_manifest_digest)=64),
        runtime_binding_digest TEXT NOT NULL CHECK(length(runtime_binding_digest)=64),
        policy_json TEXT NOT NULL CHECK(length(policy_json) BETWEEN 1 AND 4096),
        policy_digest TEXT NOT NULL CHECK(length(policy_digest)=64),
        model_snapshot_json TEXT NOT NULL CHECK(length(model_snapshot_json) BETWEEN 1 AND 1024),
        claim_digest TEXT NOT NULL CHECK(length(claim_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0 AND created_at<1000000000000),
        UNIQUE(run_id,generation),
        FOREIGN KEY(run_id,source) REFERENCES mentat_runs(id,source) ON DELETE RESTRICT,
        FOREIGN KEY(run_id) REFERENCES mentat_project_proposal_input_receipts(run_id) ON DELETE RESTRICT
    );

CREATE TABLE mentat_project_worker_calls (
        call_id TEXT NOT NULL PRIMARY KEY CHECK(length(call_id)=32),
        run_id TEXT NOT NULL UNIQUE,
        generation TEXT NOT NULL CHECK(length(generation)=32),
        request_digest TEXT NOT NULL CHECK(length(request_digest)=64),
        result_token_hash TEXT NOT NULL CHECK(length(result_token_hash)=64),
        work_debit INTEGER NOT NULL CHECK(typeof(work_debit)='integer' AND work_debit=1),
        state TEXT NOT NULL CHECK(state IN ('reserved','unknown','succeeded','failed')),
        disposition TEXT CHECK(disposition IN ('rejected','non_text','oversized')),
        response_text TEXT,
        result_digest TEXT CHECK(result_digest IS NULL OR length(result_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0 AND created_at<1000000000000),
        settled_at REAL CHECK(settled_at IS NULL OR settled_at>=created_at AND settled_at<1000000000000),
        FOREIGN KEY(run_id,generation) REFERENCES mentat_project_worker_generations(run_id,generation) ON DELETE RESTRICT,
        CHECK((state IN ('reserved','unknown') AND disposition IS NULL AND response_text IS NULL AND result_digest IS NULL AND settled_at IS NULL)
           OR (state='succeeded' AND disposition IS NULL AND response_text IS NOT NULL
               AND length(CAST(response_text AS BLOB))<=32768 AND result_digest IS NOT NULL AND settled_at IS NOT NULL)
           OR (state='failed' AND disposition IS NOT NULL AND response_text IS NULL
               AND result_digest IS NOT NULL AND settled_at IS NOT NULL))
    );

CREATE TABLE mentat_project_worker_scopes (
        run_id TEXT NOT NULL PRIMARY KEY,
        generation TEXT NOT NULL CHECK(length(generation)=32),
        unit TEXT NOT NULL UNIQUE CHECK(length(unit) BETWEEN 50 AND 80),
        authority_epoch BLOB NOT NULL CHECK(typeof(authority_epoch)='blob' AND length(authority_epoch)=32),
        plan_json TEXT NOT NULL CHECK(length(plan_json) BETWEEN 1 AND 2048),
        plan_digest TEXT NOT NULL CHECK(length(plan_digest)=64),
        claim_digest TEXT NOT NULL CHECK(length(claim_digest)=64),
        claim_token_hash TEXT NOT NULL CHECK(length(claim_token_hash)=64),
        created_at REAL NOT NULL CHECK(created_at>0 AND created_at<1000000000000),
        revision INTEGER NOT NULL CHECK(typeof(revision)='integer' AND revision BETWEEN 1 AND 5),
        state TEXT NOT NULL CHECK(state IN ('prepared','starting','owned','unknown','stopped','cancelled')),
        identity_json TEXT CHECK(identity_json IS NULL OR length(identity_json) BETWEEN 1 AND 2048),
        identity_digest TEXT CHECK(identity_digest IS NULL OR length(identity_digest)=64),
        closure_digest TEXT CHECK(closure_digest IS NULL OR length(closure_digest)=64),
        last_intent_digest TEXT CHECK(last_intent_digest IS NULL OR length(last_intent_digest)=64),
        updated_at REAL NOT NULL CHECK(updated_at>=created_at AND updated_at<1000000000000),
        FOREIGN KEY(run_id,generation) REFERENCES mentat_project_worker_generations(run_id,generation) ON DELETE RESTRICT,
        CHECK((identity_json IS NULL)=(identity_digest IS NULL)),
        CHECK((state='stopped' AND identity_json IS NOT NULL AND closure_digest IS NOT NULL)
           OR (state!='stopped' AND closure_digest IS NULL)),
        CHECK(state!='owned' OR identity_json IS NOT NULL),
        CHECK(state NOT IN ('prepared','starting','cancelled') OR identity_json IS NULL)
    );

CREATE TABLE mentat_project_output_reservations (
        run_id TEXT NOT NULL PRIMARY KEY,
        generation TEXT NOT NULL CHECK(length(generation)=32),
        authority_epoch BLOB NOT NULL CHECK(typeof(authority_epoch)='blob' AND length(authority_epoch)=32),
        input_manifest_digest TEXT NOT NULL CHECK(length(input_manifest_digest)=64),
        policy_digest TEXT NOT NULL CHECK(length(policy_digest)=64),
        blob_slots INTEGER NOT NULL CHECK(typeof(blob_slots)='integer' AND blob_slots=1),
        max_bytes INTEGER NOT NULL CHECK(typeof(max_bytes)='integer' AND max_bytes BETWEEN 1 AND 32768),
        metadata_charge INTEGER NOT NULL CHECK(typeof(metadata_charge)='integer' AND metadata_charge=131072),
        holder_token_hash TEXT NOT NULL CHECK(length(holder_token_hash)=64),
        reservation_digest TEXT NOT NULL CHECK(length(reservation_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0 AND created_at<1000000000000),
        FOREIGN KEY(run_id,generation) REFERENCES mentat_project_worker_generations(run_id,generation) ON DELETE RESTRICT
    );

CREATE TABLE mentat_project_producer_bindings (
        run_id TEXT NOT NULL PRIMARY KEY REFERENCES mentat_runs(id) ON DELETE RESTRICT,
        generation TEXT NOT NULL CHECK(length(generation)=32),
        body_json TEXT NOT NULL CHECK(length(CAST(body_json AS BLOB)) BETWEEN 1 AND 8192),
        receipt_digest TEXT NOT NULL CHECK(length(receipt_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0 AND created_at<1000000000000),
        FOREIGN KEY(run_id,generation) REFERENCES mentat_project_worker_generations(run_id,generation) ON DELETE RESTRICT,
        FOREIGN KEY(run_id) REFERENCES mentat_project_output_reservations(run_id) ON DELETE RESTRICT
    );

CREATE TABLE mentat_project_producer_stops (
        run_id TEXT NOT NULL PRIMARY KEY REFERENCES mentat_project_producer_bindings(run_id) ON DELETE RESTRICT,
        expected_revision INTEGER NOT NULL CHECK(typeof(expected_revision)='integer' AND expected_revision BETWEEN 1 AND 8),
        intent_digest TEXT NOT NULL CHECK(length(intent_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0 AND created_at<1000000000000)
    );

CREATE TABLE mentat_project_producer_outputs (
        run_id TEXT NOT NULL PRIMARY KEY REFERENCES mentat_project_producer_bindings(run_id) ON DELETE RESTRICT,
        call_id TEXT REFERENCES mentat_project_worker_calls(call_id) ON DELETE RESTRICT,
        scope_run_id TEXT REFERENCES mentat_project_worker_scopes(run_id) ON DELETE RESTRICT,
        attachment_id TEXT REFERENCES attachments(id) ON DELETE RESTRICT,
        blob_id TEXT REFERENCES blobs(id) ON DELETE RESTRICT,
        body_json TEXT NOT NULL CHECK(length(CAST(body_json AS BLOB)) BETWEEN 1 AND 98304),
        receipt_digest TEXT NOT NULL CHECK(length(receipt_digest)=64),
        created_at REAL NOT NULL CHECK(created_at>0 AND created_at<1000000000000),
        CHECK(scope_run_id IS NULL OR scope_run_id=run_id),
        CHECK((attachment_id IS NULL)=(blob_id IS NULL))
    );

CREATE INDEX idx_attachments_state_expiry
            ON attachments(state, expires_at, delete_after);

CREATE INDEX idx_attachments_blob
            ON attachments(blob_id);

CREATE INDEX idx_run_attachments_attachment
            ON run_attachments(attachment_id);

CREATE INDEX idx_run_attachments_run
            ON run_attachments(run_id);

CREATE INDEX idx_task_artifacts_task
            ON task_artifacts(
                mentat_task_id,
                connection_binding_id,
                board_id,
                remote_task_id,
                ordinal
            );

CREATE INDEX idx_task_artifacts_attachment
            ON task_artifacts(attachment_id);

CREATE INDEX idx_task_artifacts_binding
            ON task_artifacts(binding_id);

CREATE INDEX idx_hermes_webhook_deliveries_expiry
            ON hermes_webhook_deliveries(expires_at);

CREATE INDEX idx_mentat_tasks_status_order
            ON mentat_tasks(status, sort_order);

CREATE INDEX idx_mentat_tasks_project_order
            ON mentat_tasks(project, sort_order);

CREATE INDEX idx_mentat_tasks_assigned_agent
            ON mentat_tasks(assigned_agent_id, status, sort_order);

CREATE INDEX idx_mentat_task_dependencies_target
            ON mentat_task_dependencies(dependency_task_id, task_id);

CREATE INDEX idx_mentat_agent_events_run_sequence
            ON mentat_agent_events(run_id, sequence);

CREATE INDEX idx_mentat_dispatch_task
            ON mentat_dispatch_reservations(task_id, task_revision, created_at);

CREATE INDEX idx_mentat_agents_name
            ON mentat_agents(name COLLATE NOCASE, id);

CREATE UNIQUE INDEX idx_provider_connections_provider
            ON provider_connections(provider);

CREATE UNIQUE INDEX idx_mentat_agents_system_role
            ON mentat_agents(system_role)
            WHERE system_role IS NOT NULL;

CREATE INDEX idx_mentat_conversation_messages_page
            ON mentat_conversation_messages(conversation_id, sequence DESC, id);

CREATE INDEX idx_mentat_conversation_messages_run
            ON mentat_conversation_messages(run_id, conversation_id, sequence);

CREATE INDEX idx_mentat_conversation_turns_state
            ON mentat_conversation_turns(conversation_id, state, queue_ordinal);

CREATE INDEX idx_mentat_conversation_run_attempts_turn
            ON mentat_conversation_run_attempts(turn_id, created_at, run_id);

CREATE INDEX idx_mentat_conversation_staged_attachments_order
            ON mentat_conversation_staged_attachments(conversation_id, ordinal);

CREATE INDEX idx_mentat_conversation_run_context_pack
            ON mentat_conversation_run_contexts(context_pack_id, context_pack_revision);

CREATE INDEX idx_mentat_conversations_activity
            ON mentat_conversations(state, updated_at DESC, id);

CREATE INDEX idx_mentat_conversations_agent_activity
            ON mentat_conversations(agent_id, state, updated_at DESC, id);

CREATE INDEX idx_mentat_conversation_planning_project
            ON mentat_conversation_planning_context(project_id, conversation_id);

CREATE INDEX idx_mentat_conversation_planning_task
            ON mentat_conversation_planning_context(task_id, conversation_id)
            WHERE task_id IS NOT NULL;

CREATE INDEX idx_mentat_projects_status_order
            ON mentat_projects(status, sort_order);

CREATE INDEX idx_mentat_tasks_project_id_order
            ON mentat_tasks(project_id, sort_order);

CREATE INDEX idx_mentat_task_execution_attempts_task
            ON mentat_task_execution_attempts(task_id, task_revision, created_at DESC);

CREATE INDEX idx_mentat_task_execution_attempts_review
            ON mentat_task_execution_attempts(task_id, review_task_revision, state);

CREATE INDEX idx_mentat_task_execution_reviews_task
            ON mentat_task_execution_reviews(task_id, created_at DESC);

CREATE UNIQUE INDEX idx_mentat_task_delegation_action_receipts_active_task
            ON mentat_task_delegation_action_receipts(task_id)
            WHERE state IN ('reserved', 'submitting', 'unknown', 'partial');

CREATE INDEX idx_mentat_task_delegation_action_receipts_expires
            ON mentat_task_delegation_action_receipts(expires_at)
            WHERE expires_at IS NOT NULL;

CREATE INDEX idx_mentat_task_delegation_action_receipts_task
            ON mentat_task_delegation_action_receipts(task_id, created_at DESC);

CREATE UNIQUE INDEX idx_mentat_codex_task_create_grants_thread
            ON mentat_codex_task_create_grants(thread_id)
            WHERE thread_id IS NOT NULL;

CREATE INDEX idx_mentat_codex_task_create_receipts_task
            ON mentat_codex_task_create_receipts(created_task_id, created_at DESC);

CREATE INDEX idx_mentat_planning_deletion_receipts_created
            ON mentat_planning_deletion_receipts(created_at DESC);

CREATE INDEX idx_mentat_owner_auth_credentials_state
            ON mentat_owner_auth_credentials(state, created_at);

CREATE INDEX idx_mentat_owner_auth_ceremonies_pending ON mentat_owner_auth_ceremonies(state, expires_at, purpose);

CREATE INDEX idx_mentat_owner_auth_recovery_active ON mentat_owner_auth_recovery_codes(state, generation);

CREATE INDEX idx_mentat_owner_auth_audit_retention ON mentat_owner_auth_audit(occurred_at, id);

CREATE INDEX idx_mentat_owner_auth_sse_session
            ON mentat_owner_auth_sse_reservations(session_digest, created_at);

CREATE INDEX idx_mentat_owner_auth_sessions_device ON mentat_owner_auth_sessions(device_id, state, created_at);

CREATE INDEX idx_mentat_owner_auth_sessions_expiry ON mentat_owner_auth_sessions(state, idle_expires_at, absolute_expires_at);

CREATE INDEX idx_mentat_google_transaction_expiry
        ON mentat_owner_google_transactions(state, expires_at);

CREATE UNIQUE INDEX idx_mentat_project_context_live_project
        ON mentat_project_context_scopes(project_id) WHERE retired_at IS NULL;

CREATE INDEX idx_mentat_project_context_attachment
        ON mentat_project_context_files(attachment_id);

CREATE UNIQUE INDEX idx_mentat_agent_context_incarnation ON mentat_agents(context_incarnation)
        WHERE context_incarnation!='';

CREATE UNIQUE INDEX idx_mentat_task_input_incarnation ON mentat_tasks(input_incarnation)
        WHERE input_incarnation!='';

CREATE UNIQUE INDEX idx_mentat_task_input_live_scope ON mentat_task_input_scopes(task_id)
        WHERE retired_at IS NULL;

CREATE UNIQUE INDEX idx_mentat_project_deliverable_incarnation ON mentat_projects(deliverable_incarnation)
        WHERE deliverable_incarnation!='';

CREATE UNIQUE INDEX idx_mentat_deliverable_live_slot ON mentat_deliverable_slots(project_id,slot)
        WHERE retired_at IS NULL;

CREATE UNIQUE INDEX mentat_plan_live_project ON mentat_plan_scopes(project_id) WHERE retired_at IS NULL;

CREATE INDEX mentat_inbox_created ON mentat_inbox_items(created_at DESC,id DESC);

CREATE INDEX mentat_inbox_source ON mentat_inbox_items(kind,source_id,source_incarnation,resolved_at);

CREATE UNIQUE INDEX mentat_run_attention_source ON mentat_run_attention(run_id,incarnation);

CREATE UNIQUE INDEX mentat_run_attention_item ON mentat_run_attention(item_id)
        WHERE item_id IS NOT NULL;

CREATE INDEX mentat_project_lead_project ON mentat_project_lead_versions(project_id,project_incarnation,revision DESC);

CREATE INDEX mentat_project_planning_input_project
        ON mentat_project_planning_input_versions(project_id,project_incarnation,revision DESC);

CREATE INDEX idx_mentat_runs_agent_created
            ON mentat_runs(agent_id, created_at DESC, id);

CREATE UNIQUE INDEX idx_mentat_runs_one_active_conversation
            ON mentat_runs(conversation_id)
            WHERE conversation_id IS NOT NULL AND status IN (
                'reserved', 'queued', 'submitting', 'starting', 'running',
                'cancelling', 'waiting', 'waiting_for_approval',
                'waiting_for_clarification', 'unknown'
            );

CREATE UNIQUE INDEX idx_mentat_runs_one_active_task
            ON mentat_runs(task_id)
            WHERE source = 'task_dispatch' AND status IN (
                'reserved', 'queued', 'submitting', 'starting', 'running',
                'cancelling', 'waiting', 'waiting_for_approval',
                'waiting_for_clarification', 'unknown'
            );

CREATE INDEX idx_mentat_runs_status_updated
            ON mentat_runs(status, updated_at DESC, id);

CREATE INDEX idx_mentat_runs_task_created
            ON mentat_runs(task_id, created_at DESC, id);

CREATE UNIQUE INDEX mentat_runs_worker_source_key ON mentat_runs(id,source);

CREATE VIEW mentat_retained_attachments AS
        SELECT attachment_id FROM run_attachments
        UNION SELECT attachment_id FROM mentat_project_context_files
        UNION SELECT attachment_id FROM mentat_task_input_files
        UNION SELECT attachment_id FROM mentat_run_input_files
        UNION SELECT attachment_id FROM mentat_deliverable_files
        UNION SELECT attachment_id FROM mentat_project_planning_input_files
        UNION SELECT attachment_id FROM mentat_project_proposal_input_files
        UNION SELECT attachment_id FROM mentat_project_producer_outputs WHERE attachment_id IS NOT NULL;

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

CREATE TRIGGER mentat_conversation_run_attempts_capacity
        BEFORE INSERT ON mentat_conversation_run_attempts
        WHEN (
            SELECT COUNT(*) FROM mentat_conversation_run_attempts
            WHERE turn_id = NEW.turn_id
        ) >= 7
        BEGIN
            SELECT RAISE(ABORT, 'conversation_attempt_capacity');
        END;

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

CREATE TRIGGER mentat_conversations_agent_immutable
        BEFORE UPDATE OF agent_id ON mentat_conversations
        WHEN OLD.agent_id IS NOT NEW.agent_id
        BEGIN
            SELECT RAISE(ABORT, 'conversation_agent_immutable');
        END;

CREATE TRIGGER mentat_owner_auth_sse_release_on_session_terminal
        AFTER UPDATE OF state ON mentat_owner_auth_sessions
        WHEN NEW.state != 'active'
        BEGIN
            DELETE FROM mentat_owner_auth_sse_reservations
             WHERE session_digest = NEW.session_digest;
        END;

CREATE TRIGGER mentat_project_context_version_immutable
        BEFORE UPDATE ON mentat_project_context_versions
        BEGIN SELECT RAISE(ABORT, 'project_context.immutable'); END;

CREATE TRIGGER mentat_project_context_file_immutable
        BEFORE UPDATE ON mentat_project_context_files
        BEGIN SELECT RAISE(ABORT, 'project_context.immutable'); END;

CREATE TRIGGER mentat_project_context_scope_identity
        BEFORE UPDATE OF id, project_id, created_at ON mentat_project_context_scopes
        BEGIN SELECT RAISE(ABORT, 'project_context.immutable'); END;

CREATE TRIGGER mentat_project_context_retirement_terminal
        BEFORE UPDATE OF retired_at ON mentat_project_context_scopes
        WHEN OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL
        BEGIN SELECT RAISE(ABORT, 'project_context.retired'); END;

CREATE TRIGGER mentat_agent_context_incarnation_create AFTER INSERT ON mentat_agents
        WHEN NEW.context_incarnation=''
        BEGIN UPDATE mentat_agents SET context_incarnation=lower(hex(randomblob(16))) WHERE id=NEW.id; END;

CREATE TRIGGER mentat_agent_context_incarnation_immutable BEFORE UPDATE OF context_incarnation ON mentat_agents
        WHEN OLD.context_incarnation!=''
        BEGIN SELECT RAISE(ABORT,'agent.context_identity_immutable'); END;

CREATE TRIGGER mentat_project_context_retire_grants AFTER UPDATE OF retired_at ON mentat_project_context_scopes
        WHEN NEW.retired_at IS NOT NULL
        BEGIN UPDATE mentat_project_context_grants SET state='revoked',reason='project_deleted',revision=revision+1,
            updated_at=CAST(strftime('%s','now') AS REAL) WHERE scope_id=NEW.id AND state='active'; END;

CREATE TRIGGER mentat_agent_delete_context_grants BEFORE DELETE ON mentat_agents
        BEGIN UPDATE mentat_project_context_grants SET state='revoked',reason='agent_deleted',revision=revision+1,
            updated_at=CAST(strftime('%s','now') AS REAL)
            WHERE agent_id=OLD.id AND agent_incarnation=OLD.context_incarnation AND state='active'; END;

CREATE TRIGGER mentat_task_input_incarnation_create AFTER INSERT ON mentat_tasks
        WHEN NEW.input_incarnation=''
        BEGIN UPDATE mentat_tasks SET input_incarnation=lower(hex(randomblob(16))) WHERE id=NEW.id; END;

CREATE TRIGGER mentat_task_input_incarnation_immutable BEFORE UPDATE OF input_incarnation ON mentat_tasks
        WHEN OLD.input_incarnation!=''
        BEGIN SELECT RAISE(ABORT,'task.input_identity_immutable'); END;

CREATE TRIGGER mentat_task_input_scope_immutable
        BEFORE UPDATE OF id,task_id,task_incarnation,project_scope_id,created_at ON mentat_task_input_scopes
        BEGIN SELECT RAISE(ABORT,'task_input.immutable'); END;

CREATE TRIGGER mentat_task_input_retirement_terminal BEFORE UPDATE OF retired_at ON mentat_task_input_scopes
        WHEN OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL
        BEGIN SELECT RAISE(ABORT,'task_input.retired'); END;

CREATE TRIGGER mentat_task_input_version_immutable BEFORE UPDATE ON mentat_task_input_versions
        BEGIN SELECT RAISE(ABORT,'task_input.immutable'); END;

CREATE TRIGGER mentat_task_input_file_immutable BEFORE UPDATE ON mentat_task_input_files
        BEGIN SELECT RAISE(ABORT,'task_input.immutable'); END;

CREATE TRIGGER mentat_task_delete_input_scope BEFORE DELETE ON mentat_tasks
        BEGIN UPDATE mentat_task_input_scopes SET retired_at=MAX(created_at,CAST(strftime('%s','now') AS REAL))
            WHERE task_id=OLD.id AND task_incarnation=OLD.input_incarnation AND retired_at IS NULL; END;

CREATE TRIGGER mentat_task_move_input_scope AFTER UPDATE OF project_id ON mentat_tasks
        WHEN NEW.project_id IS NOT OLD.project_id
        BEGIN UPDATE mentat_task_input_scopes SET retired_at=MAX(created_at,CAST(strftime('%s','now') AS REAL))
            WHERE task_id=OLD.id AND task_incarnation=OLD.input_incarnation AND retired_at IS NULL; END;

CREATE TRIGGER mentat_project_retire_input_scopes AFTER UPDATE OF retired_at ON mentat_project_context_scopes
        WHEN NEW.retired_at IS NOT NULL
        BEGIN UPDATE mentat_task_input_scopes SET retired_at=MAX(created_at,NEW.retired_at)
            WHERE project_scope_id=NEW.id AND retired_at IS NULL; END;

CREATE TRIGGER mentat_run_input_receipt_immutable
        BEFORE UPDATE ON mentat_run_input_receipts
        BEGIN SELECT RAISE(ABORT,'run_input.immutable'); END;

CREATE TRIGGER mentat_run_input_receipt_no_delete
        BEFORE DELETE ON mentat_run_input_receipts
        BEGIN SELECT RAISE(ABORT,'run_input.retained'); END;

CREATE TRIGGER mentat_run_input_file_immutable
        BEFORE UPDATE ON mentat_run_input_files
        BEGIN SELECT RAISE(ABORT,'run_input.immutable'); END;

CREATE TRIGGER mentat_run_input_file_no_delete
        BEFORE DELETE ON mentat_run_input_files
        BEGIN SELECT RAISE(ABORT,'run_input.retained'); END;

CREATE TRIGGER mentat_project_deliverable_incarnation_create AFTER INSERT ON mentat_projects
        WHEN NEW.deliverable_incarnation=''
        BEGIN UPDATE mentat_projects SET deliverable_incarnation=lower(hex(randomblob(16))) WHERE id=NEW.id; END;

CREATE TRIGGER mentat_project_deliverable_incarnation_immutable BEFORE UPDATE OF deliverable_incarnation ON mentat_projects
        WHEN OLD.deliverable_incarnation!=''
        BEGIN SELECT RAISE(ABORT,'project.deliverable_identity_immutable'); END;

CREATE TRIGGER mentat_deliverable_slot_identity_immutable
        BEFORE UPDATE OF id,project_id,project_incarnation,slot,created_at ON mentat_deliverable_slots
        BEGIN SELECT RAISE(ABORT,'deliverable.immutable'); END;

CREATE TRIGGER mentat_deliverable_slot_no_delete BEFORE DELETE ON mentat_deliverable_slots
        BEGIN SELECT RAISE(ABORT,'deliverable.retained'); END;

CREATE TRIGGER mentat_deliverable_slot_retirement_terminal BEFORE UPDATE OF retired_at ON mentat_deliverable_slots
        WHEN OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL
        BEGIN SELECT RAISE(ABORT,'deliverable.retired'); END;

CREATE TRIGGER mentat_deliverable_version_immutable BEFORE UPDATE ON mentat_deliverable_versions
        BEGIN SELECT RAISE(ABORT,'deliverable.immutable'); END;

CREATE TRIGGER mentat_deliverable_version_no_delete BEFORE DELETE ON mentat_deliverable_versions
        BEGIN SELECT RAISE(ABORT,'deliverable.retained'); END;

CREATE TRIGGER mentat_deliverable_file_immutable BEFORE UPDATE ON mentat_deliverable_files
        BEGIN SELECT RAISE(ABORT,'deliverable.immutable'); END;

CREATE TRIGGER mentat_deliverable_file_no_delete BEFORE DELETE ON mentat_deliverable_files
        BEGIN SELECT RAISE(ABORT,'deliverable.retained'); END;

CREATE TRIGGER mentat_project_retire_deliverables BEFORE DELETE ON mentat_projects
        BEGIN UPDATE mentat_deliverable_slots SET retired_at=MAX(created_at,CAST(strftime('%s','now') AS REAL))
            WHERE project_id=OLD.id AND project_incarnation=OLD.deliverable_incarnation AND retired_at IS NULL; END;

CREATE TRIGGER mentat_deliverable_review_immutable BEFORE UPDATE ON mentat_deliverable_reviews
        BEGIN SELECT RAISE(ABORT,'deliverable_review.immutable'); END;

CREATE TRIGGER mentat_deliverable_review_no_delete BEFORE DELETE ON mentat_deliverable_reviews
        BEGIN SELECT RAISE(ABORT,'deliverable_review.retained'); END;

CREATE TRIGGER mentat_deliverable_review_version_immutable BEFORE UPDATE ON mentat_deliverable_review_versions
        BEGIN SELECT RAISE(ABORT,'deliverable_review.immutable'); END;

CREATE TRIGGER mentat_deliverable_review_version_no_delete BEFORE DELETE ON mentat_deliverable_review_versions
        BEGIN SELECT RAISE(ABORT,'deliverable_review.retained'); END;

CREATE TRIGGER mentat_plan_scope_identity_immutable BEFORE UPDATE OF id,project_id,project_incarnation,context_scope_id,created_at ON mentat_plan_scopes
        BEGIN SELECT RAISE(ABORT,'plan.immutable'); END;

CREATE TRIGGER mentat_plan_scope_retirement_terminal BEFORE UPDATE OF retired_at ON mentat_plan_scopes
        WHEN OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL
        BEGIN SELECT RAISE(ABORT,'plan.retired'); END;

CREATE TRIGGER mentat_project_plan_retire BEFORE DELETE ON mentat_projects
        BEGIN UPDATE mentat_plan_scopes SET retired_at=MAX(created_at,CAST(strftime('%s','now') AS REAL))
            WHERE project_id=OLD.id AND project_incarnation=OLD.deliverable_incarnation AND retired_at IS NULL; END;

CREATE TRIGGER mentat_plan_input_ref_immutable BEFORE UPDATE ON mentat_plan_input_refs
        BEGIN SELECT RAISE(ABORT,'plan.immutable'); END;

CREATE TRIGGER mentat_plan_input_ref_no_delete BEFORE DELETE ON mentat_plan_input_refs
        BEGIN SELECT RAISE(ABORT,'plan.retained'); END;

CREATE TRIGGER mentat_inbox_source_immutable
        BEFORE UPDATE OF id,kind,source_id,source_incarnation,generation_digest,heads_json,created_at ON mentat_inbox_items
        BEGIN SELECT RAISE(ABORT,'inbox.source_immutable'); END;

CREATE TRIGGER mentat_inbox_project_retire AFTER DELETE ON mentat_projects
        BEGIN UPDATE mentat_inbox_items SET resolved_at=MAX(updated_at,created_at,CAST(strftime('%s','now') AS REAL)),
            updated_at=MAX(updated_at,created_at,CAST(strftime('%s','now') AS REAL)),revision=revision+1
            WHERE source_id=OLD.id AND source_incarnation=OLD.deliverable_incarnation AND resolved_at IS NULL; END;

CREATE TRIGGER mentat_run_identity_immutable
        BEFORE UPDATE ON mentat_run_identities
        BEGIN SELECT RAISE(ABORT,'run.identity_immutable'); END;

CREATE TRIGGER mentat_run_attention_source_unique BEFORE INSERT ON mentat_run_attention
        WHEN EXISTS(SELECT 1 FROM mentat_run_attention
            WHERE run_id=NEW.run_id AND incarnation=NEW.incarnation)
        BEGIN SELECT RAISE(ABORT,'run_attention.source_collision'); END;

CREATE TRIGGER mentat_run_attention_identity_immutable BEFORE UPDATE ON mentat_run_attention
        WHEN NEW.slot_id IS NOT OLD.slot_id OR NEW.run_id IS NOT OLD.run_id
          OR NEW.incarnation IS NOT OLD.incarnation
          OR (OLD.item_id IS NOT NULL AND NEW.item_id IS NOT OLD.item_id)
          OR (OLD.retired_at IS NOT NULL AND (
              NEW.retired_at IS NOT OLD.retired_at OR
              NEW.retired_source IS NOT OLD.retired_source OR
              NEW.retired_status IS NOT OLD.retired_status OR
              NEW.retired_dispatch_state IS NOT OLD.retired_dispatch_state OR
              NEW.retired_partial IS NOT OLD.retired_partial OR
              NEW.retired_terminal_finalized IS NOT OLD.retired_terminal_finalized OR
              NEW.retired_state_revision IS NOT OLD.retired_state_revision OR
              NEW.retired_task_id IS NOT OLD.retired_task_id OR
              NEW.retired_conversation_id IS NOT OLD.retired_conversation_id OR
              NEW.retired_agent_id IS NOT OLD.retired_agent_id OR
              NEW.retired_run_created_at IS NOT OLD.retired_run_created_at OR
              NEW.retired_run_updated_at IS NOT OLD.retired_run_updated_at OR
              NEW.retired_run_completed_at IS NOT OLD.retired_run_completed_at))
        BEGIN SELECT RAISE(ABORT,'run_attention.source_immutable'); END;

CREATE TRIGGER mentat_run_attention_protect BEFORE DELETE ON mentat_run_attention
        WHEN OLD.item_id IS NOT NULL AND
             (OLD.retired_at IS NULL OR OLD.resolved_at IS NULL OR OLD.acknowledged_at IS NULL)
        BEGIN SELECT RAISE(ABORT,'run_attention.retained'); END;

CREATE TRIGGER mentat_run_attention_item_unique BEFORE UPDATE OF item_id ON mentat_run_attention
        WHEN NEW.item_id IS NOT NULL AND (
            EXISTS(SELECT 1 FROM mentat_inbox_items WHERE id=NEW.item_id) OR
            EXISTS(SELECT 1 FROM mentat_run_attention WHERE item_id=NEW.item_id AND slot_id!=OLD.slot_id))
        BEGIN SELECT RAISE(ABORT,'run_attention.item_collision'); END;

CREATE TRIGGER mentat_inbox_run_item_unique BEFORE INSERT ON mentat_inbox_items
        WHEN EXISTS(SELECT 1 FROM mentat_run_attention WHERE item_id=NEW.id)
        BEGIN SELECT RAISE(ABORT,'run_attention.item_collision'); END;

CREATE TRIGGER mentat_run_attention_initial AFTER INSERT ON mentat_run_attention
        WHEN EXISTS(SELECT 1 FROM mentat_runs r WHERE r.id=NEW.run_id AND
            (r.status='unknown' OR r.status IN ('failed','interrupted') OR
             (r.status IN ('completed','failed','cancelled','stopped','interrupted') AND
              (r.partial=1 OR r.terminal_finalized=0))))
        BEGIN UPDATE mentat_run_attention SET
            item_id='inbox_item_'||lower(hex(randomblob(16))),revision=1,
            created_at=CAST(strftime('%s','now') AS REAL),updated_at=CAST(strftime('%s','now') AS REAL)
            WHERE run_id=NEW.run_id AND incarnation=NEW.incarnation; END;

CREATE TRIGGER mentat_run_attention_reserve AFTER INSERT ON mentat_run_identities
        BEGIN
            DELETE FROM mentat_run_attention WHERE rowid IN
                (SELECT rowid FROM mentat_run_attention WHERE retired_at IS NOT NULL
                 AND resolved_at IS NOT NULL AND acknowledged_at IS NOT NULL
                 ORDER BY created_at,item_id LIMIT 1)
                AND (SELECT COUNT(*) FROM mentat_run_attention)>=10000;
            SELECT CASE WHEN (SELECT COUNT(*) FROM mentat_run_attention)>=10000
                THEN RAISE(ABORT,'run_attention.capacity') END;
            INSERT INTO mentat_run_attention(run_id,incarnation) VALUES(NEW.run_id,NEW.incarnation);
        END;

CREATE TRIGGER mentat_plan_version_immutable BEFORE UPDATE ON mentat_plan_versions
        BEGIN SELECT RAISE(ABORT,'plan.immutable'); END;

CREATE TRIGGER mentat_plan_version_no_delete BEFORE DELETE ON mentat_plan_versions
        BEGIN SELECT RAISE(ABORT,'plan.retained'); END;

CREATE TRIGGER mentat_project_lead_immutable BEFORE UPDATE ON mentat_project_lead_versions
        BEGIN SELECT RAISE(ABORT,'project_lead.immutable'); END;

CREATE TRIGGER mentat_project_lead_no_delete BEFORE DELETE ON mentat_project_lead_versions
        BEGIN SELECT RAISE(ABORT,'project_lead.retained'); END;

CREATE TRIGGER mentat_project_planning_input_immutable
        BEFORE UPDATE ON mentat_project_planning_input_versions
        BEGIN SELECT RAISE(ABORT,'project_input.immutable'); END;

CREATE TRIGGER mentat_project_planning_input_retained
        BEFORE DELETE ON mentat_project_planning_input_versions
        BEGIN SELECT RAISE(ABORT,'project_input.retained'); END;

CREATE TRIGGER mentat_project_planning_input_file_immutable
        BEFORE UPDATE ON mentat_project_planning_input_files
        BEGIN SELECT RAISE(ABORT,'project_input.immutable'); END;

CREATE TRIGGER mentat_project_planning_input_file_retained
        BEFORE DELETE ON mentat_project_planning_input_files
        BEGIN SELECT RAISE(ABORT,'project_input.retained'); END;

CREATE TRIGGER mentat_project_planning_input_legacy_sealed
        BEFORE INSERT ON mentat_project_planning_input_legacy
        BEGIN SELECT RAISE(ABORT,'project_input_legacy.sealed'); END;

CREATE TRIGGER mentat_project_planning_input_legacy_immutable
        BEFORE UPDATE ON mentat_project_planning_input_legacy
        BEGIN SELECT RAISE(ABORT,'project_input_legacy.immutable'); END;

CREATE TRIGGER mentat_project_planning_input_legacy_retained
        BEFORE DELETE ON mentat_project_planning_input_legacy
        BEGIN SELECT RAISE(ABORT,'project_input_legacy.retained'); END;

CREATE TRIGGER mentat_project_planning_input_action_immutable
        BEFORE UPDATE ON mentat_project_planning_input_actions
        BEGIN SELECT RAISE(ABORT,'project_input_action.immutable'); END;

CREATE TRIGGER mentat_project_planning_input_action_retained
        BEFORE DELETE ON mentat_project_planning_input_actions
        BEGIN SELECT RAISE(ABORT,'project_input_action.retained'); END;

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

CREATE TRIGGER mentat_run_attention_retire BEFORE DELETE ON mentat_runs
        BEGIN
            SELECT CASE WHEN OLD.status NOT IN ('completed','failed','cancelled','stopped','interrupted')
                THEN RAISE(ABORT,'run_attention.active_retirement') END;
            SELECT CASE WHEN NOT EXISTS(
                SELECT 1 FROM mentat_run_attention a JOIN mentat_run_identities i
                ON i.run_id=a.run_id AND i.incarnation=a.incarnation WHERE a.run_id=OLD.id)
                THEN RAISE(ABORT,'run_attention.identity_missing') END;
            UPDATE mentat_run_attention SET retired_at=CAST(strftime('%s','now') AS REAL),
                retired_source=OLD.source,retired_status=OLD.status,
                retired_dispatch_state=OLD.dispatch_state,retired_partial=OLD.partial,
                retired_terminal_finalized=OLD.terminal_finalized,
                retired_state_revision=OLD.state_revision,retired_task_id=OLD.task_id,
                retired_conversation_id=OLD.conversation_id,retired_agent_id=OLD.agent_id,
                retired_run_created_at=OLD.created_at,retired_run_updated_at=OLD.updated_at,
                retired_run_completed_at=OLD.completed_at
                WHERE run_id=OLD.id AND item_id IS NOT NULL AND retired_at IS NULL;
            DELETE FROM mentat_run_attention WHERE run_id=OLD.id AND item_id IS NULL;
        END;

CREATE TRIGGER mentat_run_attention_transition
        AFTER UPDATE OF status,dispatch_state,partial,terminal_finalized,details_json ON mentat_runs
        WHEN OLD.status IS NOT NEW.status OR OLD.dispatch_state IS NOT NEW.dispatch_state
          OR OLD.partial IS NOT NEW.partial OR OLD.terminal_finalized IS NOT NEW.terminal_finalized
          OR OLD.details_json IS NOT NEW.details_json
        BEGIN
            UPDATE mentat_run_attention SET revision=revision+1,
                updated_at=MAX(updated_at,CAST(strftime('%s','now') AS REAL)),
                read_at=NULL,acknowledged_at=NULL,resolved_at=NULL,
                last_action_digest=NULL,last_expected_revision=NULL
                WHERE run_id=NEW.id AND item_id IS NOT NULL AND retired_at IS NULL;
            UPDATE mentat_run_attention SET
                item_id='inbox_item_'||lower(hex(randomblob(16))),revision=1,
                created_at=CAST(strftime('%s','now') AS REAL),updated_at=CAST(strftime('%s','now') AS REAL)
                WHERE run_id=NEW.id AND item_id IS NULL AND retired_at IS NULL AND
                (NEW.status='unknown' OR NEW.status IN ('completed','failed','cancelled','stopped','interrupted'));
        END;

CREATE TRIGGER mentat_run_identity_insert AFTER INSERT ON mentat_runs
        BEGIN INSERT INTO mentat_run_identities(run_id,incarnation,created_at)
            VALUES(NEW.id,lower(hex(randomblob(16))),NEW.created_at); END;

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

CREATE TRIGGER mentat_runs_project_proposal_closed_insert BEFORE INSERT ON mentat_runs WHEN NEW.source='project_proposal' BEGIN SELECT RAISE(ABORT,'run.proposal_unqualified'); END;

CREATE TRIGGER mentat_runs_project_proposal_closed_update BEFORE UPDATE OF source ON mentat_runs WHEN NEW.source='project_proposal' BEGIN SELECT RAISE(ABORT,'run.proposal_unqualified'); END;

CREATE TRIGGER mentat_project_proposal_input_receipt_immutable
        BEFORE UPDATE ON mentat_project_proposal_input_receipts
        BEGIN SELECT RAISE(ABORT,'project_proposal_input.immutable'); END;

CREATE TRIGGER mentat_project_proposal_input_receipt_retained
        BEFORE DELETE ON mentat_project_proposal_input_receipts
        BEGIN SELECT RAISE(ABORT,'project_proposal_input.retained'); END;

CREATE TRIGGER mentat_project_proposal_input_file_immutable
        BEFORE UPDATE ON mentat_project_proposal_input_files
        BEGIN SELECT RAISE(ABORT,'project_proposal_input.immutable'); END;

CREATE TRIGGER mentat_project_proposal_input_file_retained
        BEFORE DELETE ON mentat_project_proposal_input_files
        BEGIN SELECT RAISE(ABORT,'project_proposal_input.retained'); END;

CREATE TRIGGER mentat_project_worker_generation_exact BEFORE INSERT ON mentat_project_worker_generations
        WHEN NOT EXISTS(SELECT 1 FROM mentat_project_proposal_input_receipts r WHERE
            r.run_id=NEW.run_id AND r.manifest_digest=NEW.input_manifest_digest
            AND r.runtime_binding_digest=NEW.runtime_binding_digest AND r.limits_digest=NEW.policy_digest)
        BEGIN SELECT RAISE(ABORT,'worker_journal.input_mismatch'); END;

CREATE TRIGGER mentat_project_worker_generation_immutable BEFORE UPDATE ON mentat_project_worker_generations
        BEGIN SELECT RAISE(ABORT,'worker_journal.immutable'); END;

CREATE TRIGGER mentat_project_worker_generation_retained BEFORE DELETE ON mentat_project_worker_generations
        BEGIN SELECT RAISE(ABORT,'worker_journal.retained'); END;

CREATE TRIGGER mentat_project_worker_call_no_new_identity BEFORE UPDATE ON mentat_project_worker_calls
        WHEN NEW.call_id IS NOT OLD.call_id OR NEW.run_id IS NOT OLD.run_id
          OR NEW.generation IS NOT OLD.generation OR NEW.request_digest IS NOT OLD.request_digest
          OR NEW.result_token_hash IS NOT OLD.result_token_hash
          OR NEW.work_debit IS NOT OLD.work_debit OR NEW.created_at IS NOT OLD.created_at
          OR NOT ((OLD.state='reserved' AND NEW.state='unknown')
               OR (OLD.state='unknown' AND NEW.state IN ('succeeded','failed')))
        BEGIN SELECT RAISE(ABORT,'worker_journal.immutable'); END;

CREATE TRIGGER mentat_project_worker_call_retained BEFORE DELETE ON mentat_project_worker_calls
        BEGIN SELECT RAISE(ABORT,'worker_journal.retained'); END;

CREATE TRIGGER mentat_project_worker_scope_immutable BEFORE UPDATE ON mentat_project_worker_scopes
        WHEN NEW.run_id IS NOT OLD.run_id OR NEW.generation IS NOT OLD.generation
          OR NEW.unit IS NOT OLD.unit OR NEW.authority_epoch IS NOT OLD.authority_epoch
          OR NEW.plan_json IS NOT OLD.plan_json OR NEW.plan_digest IS NOT OLD.plan_digest
          OR NEW.claim_digest IS NOT OLD.claim_digest OR NEW.claim_token_hash IS NOT OLD.claim_token_hash
          OR NEW.created_at IS NOT OLD.created_at OR NEW.revision!=OLD.revision+1
          OR NEW.updated_at<OLD.updated_at
          OR (OLD.identity_json IS NOT NULL AND (NEW.identity_json IS NOT OLD.identity_json
              OR NEW.identity_digest IS NOT OLD.identity_digest))
          OR NOT ((OLD.state='prepared' AND NEW.state IN ('starting','cancelled'))
               OR (OLD.state='starting' AND NEW.state IN ('owned','unknown','stopped'))
               OR (OLD.state='owned' AND NEW.state IN ('unknown','stopped'))
               OR (OLD.state='unknown' AND NEW.state='stopped'))
        BEGIN SELECT RAISE(ABORT,'scope_journal.immutable'); END;

CREATE TRIGGER mentat_project_worker_scope_retained BEFORE DELETE ON mentat_project_worker_scopes
        BEGIN SELECT RAISE(ABORT,'scope_journal.retained'); END;

CREATE TRIGGER mentat_project_output_reservation_immutable BEFORE UPDATE ON mentat_project_output_reservations
        BEGIN SELECT RAISE(ABORT,'output_reservation.immutable'); END;

CREATE TRIGGER mentat_project_output_reservation_retained BEFORE DELETE ON mentat_project_output_reservations
        BEGIN SELECT RAISE(ABORT,'output_reservation.retained'); END;

CREATE TRIGGER mentat_project_producer_binding_immutable BEFORE UPDATE ON mentat_project_producer_bindings
        BEGIN SELECT RAISE(ABORT,'producer.immutable'); END;

CREATE TRIGGER mentat_project_producer_binding_retained BEFORE DELETE ON mentat_project_producer_bindings
        BEGIN SELECT RAISE(ABORT,'producer.retained'); END;

CREATE TRIGGER mentat_project_producer_stop_immutable BEFORE UPDATE ON mentat_project_producer_stops
        BEGIN SELECT RAISE(ABORT,'producer.immutable'); END;

CREATE TRIGGER mentat_project_producer_stop_retained BEFORE DELETE ON mentat_project_producer_stops
        BEGIN SELECT RAISE(ABORT,'producer.retained'); END;

CREATE TRIGGER mentat_project_producer_output_immutable BEFORE UPDATE ON mentat_project_producer_outputs
        BEGIN SELECT RAISE(ABORT,'producer.immutable'); END;

CREATE TRIGGER mentat_project_producer_output_retained BEFORE DELETE ON mentat_project_producer_outputs
        BEGIN SELECT RAISE(ABORT,'producer.retained'); END;

INSERT INTO mentat_deliverable_review_state VALUES (1, randomblob(32), 0);

INSERT INTO mentat_owner_auth_state (singleton, state, updated_at) VALUES (1, 'unbootstrapped', 0);

INSERT INTO mentat_project_context_access_state VALUES (1, randomblob(32));

INSERT INTO schema_migrations VALUES (1, 0);

INSERT INTO schema_migrations VALUES (2, 0);

INSERT INTO schema_migrations VALUES (3, 0);

INSERT INTO schema_migrations VALUES (4, 0);

INSERT INTO schema_migrations VALUES (5, 0);

INSERT INTO schema_migrations VALUES (6, 0);

INSERT INTO schema_migrations VALUES (7, 0);

INSERT INTO schema_migrations VALUES (8, 0);

INSERT INTO schema_migrations VALUES (9, 0);

INSERT INTO schema_migrations VALUES (10, 0);

INSERT INTO schema_migrations VALUES (11, 0);

INSERT INTO schema_migrations VALUES (12, 0);

INSERT INTO schema_migrations VALUES (13, 0);

INSERT INTO schema_migrations VALUES (14, 0);

INSERT INTO schema_migrations VALUES (15, 0);

INSERT INTO schema_migrations VALUES (16, 0);

INSERT INTO schema_migrations VALUES (17, 0);

INSERT INTO schema_migrations VALUES (18, 0);

INSERT INTO schema_migrations VALUES (19, 0);

INSERT INTO schema_migrations VALUES (20, 0);

INSERT INTO schema_migrations VALUES (21, 0);

INSERT INTO schema_migrations VALUES (22, 0);

INSERT INTO schema_migrations VALUES (23, 0);

INSERT INTO schema_migrations VALUES (24, 0);

INSERT INTO schema_migrations VALUES (25, 0);

INSERT INTO schema_migrations VALUES (26, 0);

INSERT INTO schema_migrations VALUES (27, 0);

INSERT INTO schema_migrations VALUES (28, 0);

INSERT INTO schema_migrations VALUES (29, 0);

INSERT INTO schema_migrations VALUES (30, 0);

INSERT INTO schema_migrations VALUES (31, 0);

INSERT INTO schema_migrations VALUES (32, 0);

INSERT INTO schema_migrations VALUES (33, 0);

INSERT INTO schema_migrations VALUES (34, 0);

INSERT INTO schema_migrations VALUES (35, 0);

INSERT INTO schema_migrations VALUES (36, 0);

INSERT INTO schema_migrations VALUES (37, 0);

INSERT INTO schema_migrations VALUES (38, 0);

INSERT INTO schema_migrations VALUES (39, 0);

INSERT INTO schema_migrations VALUES (40, 0);

INSERT INTO schema_migrations VALUES (41, 0);

INSERT INTO schema_migrations VALUES (42, 0);

INSERT INTO schema_migrations VALUES (43, 0);

INSERT INTO schema_migrations VALUES (44, 0);

INSERT INTO schema_migrations VALUES (45, 0);
"""

MIGRATIONS: tuple[tuple[int, str], ...] = ((SCHEMA_VERSION, CURRENT_BOOTSTRAP_SQL),)


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

    # Every fixed current object is below this ceiling. Do not retain arbitrary
    # large SQL from a malformed source in a process-lifetime comparison cache.
    if len(sql) <= 8192:
        return _cached_sql_token_signature(sql)
    return _uncached_sql_token_signature(sql)


@lru_cache(maxsize=512)
def _cached_sql_token_signature(sql: str) -> str:
    return _uncached_sql_token_signature(sql)


def _uncached_sql_token_signature(sql: str) -> str:
    tokens: list[str] = []
    for match in _SQL_TOKEN.finditer(sql.strip()):
        kind = str(match.lastgroup)
        if kind in {"whitespace", "line_comment", "block_comment"}:
            continue
        value = match.group(0)
        tokens.append(f"{kind}:{len(value)}:{value}")
    return "".join(f"{len(token)}:{token}" for token in tokens)


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


@lru_cache(maxsize=1)
def expected_schema_signature(
    schema_version: int,
) -> tuple[tuple[str, str, str, str], ...]:
    """Return only the current format's exact SQLite object graph."""

    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        raise MentatDatabaseError("Mentat database schema is unsupported")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(CURRENT_BOOTSTRAP_SQL)
        return schema_signature(connection)
    finally:
        connection.close()


def schema_signature_state(
    connection: sqlite3.Connection,
    schema_version: int,
) -> str:
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        return "invalid"
    return (
        "expected" if schema_signature(connection) == expected_schema_signature(schema_version)
        else "invalid"
    )


class MentatDatabaseError(RuntimeError):
    """Raised when Mentat's private database boundary is unsafe."""


class _TransientCurrentSnapshotRace(MentatDatabaseError):
    """A safely pinned current capture must be discarded before use."""


class _TransientDatabaseMainFileRace(_TransientCurrentSnapshotRace):
    """Only content changed on the same retained, fully private main file."""


class _TransientDatabaseSidecarRace(_TransientCurrentSnapshotRace):
    """A SQLite sidecar disappeared after its initial safe inspection."""


def _current_main_metadata(details: os.stat_result, identity: tuple[int, int], maximum: int) -> None:
    if (
        (int(details.st_dev), int(details.st_ino)) != identity
        or not stat.S_ISREG(details.st_mode) or _is_reparse_point(details)
        or details.st_nlink != 1 or details.st_size > maximum
        or (os.name == "posix" and
            (details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o600))
    ):
        raise MentatDatabaseError("Mentat current database resource is unsafe")


class _CurrentAdmissionResources:
    """Retain actual owners across the existing retry/yield lifetime, read-only."""

    def __init__(self):
        self.directories: list[tuple[Path, int, bool]] = []
        self.main: tuple[Path, int, tuple[int, int]] | None = None
        self.windows_untransferred: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        validation_error = None
        if _error[0] is None:
            try:
                self.validate()
            except BaseException as exc:
                validation_error = exc
        failed = False
        descriptors = ([self.main[1]] if self.main is not None else [])
        descriptors += [fd for _path, fd, _private in reversed(self.directories)]
        self.main = None
        self.directories = []
        for descriptor in descriptors:
            try:
                os.close(descriptor)
            except OSError:
                failed = True
        handles, self.windows_untransferred = self.windows_untransferred, []
        if handles:
            from data_layout import _windows_close_handles_checked
            try:
                _windows_close_handles_checked(handles)
            except OSError:
                failed = True
        if failed:
            raise MentatDatabaseError("Mentat current resource cleanup is unverified") from validation_error
        if validation_error is not None:
            raise validation_error

    def bind(self, path: Path, identity: tuple[int, int]) -> None:
        try:
            self._bind(path, identity)
        except OSError as exc:
            raise MentatDatabaseError("Mentat current database resources are unavailable") from exc

    def _bind(self, path: Path, identity: tuple[int, int]) -> None:
        if self.main is not None:
            if self.main[0] != path or self.main[2] != identity:
                raise MentatDatabaseError("Mentat current database identity changed")
            self.validate()
            return
        # Acquire into this retained owner before any operation that can fail.
        root = path.parent.parent.parent
        paths = (root, root / "private", path.parent)
        if os.name == "nt":
            import msvcrt
            from data_layout import _windows_open_directory_chain, _windows_open_file_descriptor
            self.windows_untransferred = _windows_open_directory_chain(path.parent, checked_cleanup=True)
            absolute = path.parent
            chain = [Path(absolute.anchor)]
            for part in absolute.parts[1:]:
                chain.append(chain[-1] / part)
            while self.windows_untransferred:
                handle = self.windows_untransferred[0]
                descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY)
                self.windows_untransferred.pop(0)  # Ownership transferred only on success.
                directory = chain[len(self.directories)]
                self.directories.append((directory, descriptor, directory in paths[1:]))
            descriptor = _windows_open_file_descriptor(path, disposition=3, writable=False, checked_cleanup=True)
        else:
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
            for index, directory in enumerate(paths):
                descriptor = (os.open(directory, flags) if index == 0 else
                              os.open(directory.name, flags, dir_fd=self.directories[-1][1]))
                self.directories.append((directory, descriptor, index > 0))
                self._directory(self.directories[-1])
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
            descriptor = os.open(path.name, flags, dir_fd=self.directories[-1][1])
        self.main = (path, descriptor, identity)
        self.validate()

    @staticmethod
    def _directory(entry) -> None:
        path, descriptor, private = entry
        held, lexical = os.fstat(descriptor), path.lstat()
        for details in (held, lexical):
            if (not stat.S_ISDIR(details.st_mode) or _is_reparse_point(details)
                    or (private and os.name == "posix" and
                        (details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o700))):
                raise MentatDatabaseError("Mentat current database directory is unsafe")
        if (held.st_dev, held.st_ino) != (lexical.st_dev, lexical.st_ino):
            raise MentatDatabaseError("Mentat current database directory changed")

    def validate(self) -> None:
        try:
            self._validate()
        except OSError as exc:
            raise MentatDatabaseError("Mentat current database resources are unavailable") from exc

    def _validate(self) -> None:
        for entry in self.directories:
            self._directory(entry)
        if self.main is not None:
            path, descriptor, identity = self.main
            _current_main_metadata(os.fstat(descriptor), identity, MAX_READONLY_DATABASE_BYTES)
            _current_main_metadata(path.lstat(), identity, MAX_READONLY_DATABASE_BYTES)


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


def _validate_current_database(connection: sqlite3.Connection) -> None:
    """Read current format admission without changing schema or rows."""

    owns_snapshot = not connection.in_transaction
    try:
        if owns_snapshot:
            connection.execute("BEGIN")
        versions = tuple(row[0] for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ))
        if (
            any(type(version) is not int for version in versions)
            or versions != tuple(range(1, SCHEMA_VERSION + 1))
            or schema_signature_state(connection, SCHEMA_VERSION) != "expected"
        ):
            raise MentatDatabaseError("Mentat database schema is unsupported or malformed")
    except sqlite3.Error as exc:
        raise MentatDatabaseError("Mentat database schema is unsupported or malformed") from exc
    finally:
        if owns_snapshot and connection.in_transaction:
            connection.rollback()


def migrate(
    connection: sqlite3.Connection,
    *,
    fresh_agent_authority_allowed: Callable[[], bool] | None = None,
) -> float | None:
    """Initialize an empty connection or validate an existing current database."""

    if connection.in_transaction:
        raise MentatDatabaseError("Mentat database initialization started inside a transaction")
    if connection.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone() is not None:
        _validate_current_database(connection)
        return None
    fresh_agent_cutover_at = None
    try:
        if fresh_agent_authority_allowed is not None and not fresh_agent_authority_allowed():
            raise MentatDatabaseError("Retired Agent registry state changed during authority claim")
        connection.execute("BEGIN IMMEDIATE")
        for version, script in MIGRATIONS:
            _execute_script_in_active_transaction(connection, script)
            # Zero timestamps identify virtual empty recipes to row validators.
            # A real fresh database must retain the original live cutoffs before
            # any subsequently published planning evidence can become valid.
            connection.execute(
                "UPDATE schema_migrations SET applied_at = ? WHERE version < ?",
                (time.time(), version),
            )
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, time.time()),
            )
        if fresh_agent_authority_allowed is None or fresh_agent_authority_allowed():
            cutover_at = time.time()
            connection.execute(
                "INSERT INTO mentat_agent_registry_state ("
                "singleton, authority, migration_contract, source_kind, "
                "source_sha256, source_agent_count, cutover_at"
                ") VALUES (1, 'sqlite', ?, 'fresh', ?, 0, ?)",
                (AGENT_REGISTRY_AUTHORITY_CONTRACT, EMPTY_AGENT_REGISTRY_SOURCE_SHA256, cutover_at),
            )
            if fresh_agent_authority_allowed is not None and not fresh_agent_authority_allowed():
                raise MentatDatabaseError("Retired Agent registry state changed during authority claim")
            fresh_agent_cutover_at = cutover_at
        else:
            raise MentatDatabaseError("Retired Agent registry state changed during authority claim")
        _validate_current_database(connection)
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MentatDatabaseError("Mentat database initialization produced invalid foreign keys")
        connection.commit()
        return fresh_agent_cutover_at
    except Exception:
        connection.rollback()
        raise


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
) -> tuple[sqlite3.Connection, dict[Path, tuple[int, int] | None]]:
    result = None
    try:
        with _CurrentAdmissionResources() as resources:
            for attempt in range(DATABASE_OPEN_ATTEMPTS):
                try:
                    result = _connect_with_identity_once(data_dir, resources=resources)
                    return result
                except _TransientCurrentSnapshotRace as exc:
                    resources.validate()
                    _pause_or_raise_sidecar_race(attempt, exc)
        raise AssertionError("database open retry loop exhausted")
    except BaseException:
        if result is not None:
            result[0].close()
        raise


def _pause_or_raise_sidecar_race(attempt: int, error: _TransientCurrentSnapshotRace) -> None:
    if attempt + 1 == DATABASE_OPEN_ATTEMPTS:
        kind = "content" if isinstance(error, _TransientDatabaseMainFileRace) else "sidecar"
        raise MentatDatabaseError(f"Mentat database {kind} changed during validation") from error
    time.sleep(DATABASE_OPEN_RETRY_SECONDS)


def _connect_with_identity_once(
    data_dir: Path, *, resources: _CurrentAdmissionResources,
) -> tuple[sqlite3.Connection, dict[Path, tuple[int, int] | None]]:
    # Admission must precede directory hardening, writable SQLite and WAL setup.
    admitted_identity = _admit_current_database_root(data_dir, resources=resources)
    if admitted_identity is None and legacy_agent_registry_artifacts_present(data_dir):
        raise MentatDatabaseError("Retired Agent registry storage is unsupported")
    resources.validate()
    private = ensure_private_console_dir(data_dir)
    path = private / DATABASE_NAME
    _validate_database_set(path, private)
    created = False
    created_identity = None
    if not path.exists():
        if legacy_agent_registry_artifacts_present(data_dir):
            raise MentatDatabaseError("Retired Agent registry storage is unsupported")
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            created = True
            details = os.fstat(descriptor)
            created_identity = (int(details.st_dev), int(details.st_ino))
        except FileExistsError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
    identities = _validate_database_set(path, private)
    expected_identity = created_identity if created else admitted_identity
    if expected_identity is None or identities[path] != expected_identity:
        raise MentatDatabaseError("Mentat database file identity changed while opening")
    resources.validate()
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        if created:
            fresh_agent_cutover_at = migrate(
                connection,
                fresh_agent_authority_allowed=lambda: not legacy_agent_registry_artifacts_present(data_dir),
            )
        else:
            _validate_current_database(connection)
            fresh_agent_cutover_at = None
        if _validate_database_set(path, private)[path] != identities[path]:
            raise MentatDatabaseError("Mentat database file identity changed while opening")
        resources.validate()
        connection.execute("PRAGMA journal_mode = WAL")
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
        resources.validate()
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
    """Admit current SQLite or initialize a fresh database before WAL setup."""

    with DATABASE_OPEN_BARRIER:
        return _connect_with_identity_locked(data_dir)


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open current SQLite with Mentat's local concurrency defaults."""

    connection, _identities = connect_with_identity(data_dir)
    return connection


def validate_current_database_root(data_dir: Path) -> bool:
    """Read-only admission: False for missing SQLite, True for exact current.

    Unsupported, malformed or unsafe existing storage raises. Call before any
    startup initialization, locking or permission changes to the source root.
    """

    with _CurrentAdmissionResources() as resources:
        for attempt in range(DATABASE_OPEN_ATTEMPTS):
            try:
                return _admit_current_database_root(data_dir, resources=resources) is not None
            except _TransientCurrentSnapshotRace as exc:
                resources.validate()
                _pause_or_raise_sidecar_race(attempt, exc)
    raise AssertionError("database admission retry loop exhausted")


def _admit_current_database_root(data_dir: Path, *, resources: _CurrentAdmissionResources) -> tuple[int, int] | None:
    with DATABASE_OPEN_BARRIER:
        resources.validate()
        source = _current_database_files(data_dir)
        if source is None:
            if resources.main is not None:
                raise MentatDatabaseError("Mentat current database disappeared")
            return None
        path, identities = source
        resources.bind(path, identities[path])
        with _current_admission_snapshot(path, identities, resources=resources) as connection:
            _validate_current_database(connection)
        if _validate_database_file(path, path.parent) != identities[path]:
            raise MentatDatabaseError("Mentat database file identity changed while opening")
        return identities[path]


def _current_database_files(
    data_dir: Path,
) -> tuple[Path, dict[Path, tuple[int, int] | None]] | None:
    root = Path(data_dir)

    def fresh_only():
        from private_state import fresh_console_storage_issue
        issue = fresh_console_storage_issue(root)
        if issue is not None:
            raise MentatDatabaseError("Missing current database: " + issue)
        return None
    for directory in (root, root / "private", private_console_dir(root)):
        try:
            details = directory.lstat()
        except FileNotFoundError:
            return fresh_only()
        if stat.S_ISLNK(details.st_mode) or _is_reparse_point(details) or not stat.S_ISDIR(details.st_mode):
            raise MentatDatabaseError("Mentat private Console directory is unsafe")
    path = private_console_dir(root).resolve(strict=True) / DATABASE_NAME
    identities = _validate_database_set(path, path.parent)
    if identities[path] is None:
        if any(identity is not None for identity in identities.values()):
            raise MentatDatabaseError("Mentat database sidecars have no database")
        if legacy_agent_registry_artifacts_present(root):
            raise MentatDatabaseError("Retired Agent registry storage is unsupported")
        return fresh_only()
    _existing_console_dir(root)
    return path, identities


@contextmanager
def connect_current_readonly(data_dir: Path) -> Iterator[sqlite3.Connection]:
    """Yield only a validated current owned-copy read snapshot, never source SQL.

    Requires existing SQLite. Later source WAL appends do not alter the yielded
    snapshot. Consumers of monotonic receipts must recheck their real transaction;
    this context grants no write authority or archival consistency guarantee.
    """

    with DATABASE_OPEN_BARRIER, _CurrentAdmissionResources() as resources:
        yielded = False
        for attempt in range(DATABASE_OPEN_ATTEMPTS):
            try:
                resources.validate()
                source = _current_database_files(data_dir)
                if source is None:
                    raise MentatDatabaseError("Mentat database is unavailable")
                path, identities = source
                resources.bind(path, identities[path])
                with _current_admission_snapshot(path, identities, resources=resources) as connection:
                    _validate_current_database(connection)
                    yielded = True
                    yield connection
                return
            except _TransientCurrentSnapshotRace as exc:
                if yielded:
                    raise
                resources.validate()
                _pause_or_raise_sidecar_race(attempt, exc)


def _read_wal_prefix(path: Path, identity: tuple[int, int]) -> bytes:
    """Capture a stable bounded prefix while permitting later WAL appends."""

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise _TransientDatabaseSidecarRace(
            "Mentat database sidecar changed during validation"
        ) from exc
    try:
        before = os.fstat(descriptor)

        def validate_descriptor(details: os.stat_result) -> None:
            if (
                not stat.S_ISREG(details.st_mode)
                or _is_reparse_point(details)
                or details.st_nlink > 1
                or details.st_size > MAX_READONLY_WAL_BYTES
                or (
                    os.name == "posix"
                    and (details.st_uid != os.getuid() or stat.S_IMODE(details.st_mode) != 0o600)
                )
            ):
                raise MentatDatabaseError("Mentat database WAL is unavailable")

        validate_descriptor(before)
        if before.st_nlink == 0 or (int(before.st_dev), int(before.st_ino)) != identity:
            raise _TransientDatabaseSidecarRace(
                "Mentat database sidecar changed during validation"
            )

        def read_prefix() -> bytes:
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    raise MentatDatabaseError("Mentat database WAL changed while reading")
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)

        raw = read_prefix()
        repeated = read_prefix()
        after = os.fstat(descriptor)
        validate_descriptor(after)
        if after.st_nlink == 0:
            raise _TransientDatabaseSidecarRace(
                "Mentat database sidecar changed during validation"
            )
        if repeated != raw or after.st_size < before.st_size:
            raise MentatDatabaseError("Mentat database WAL changed while reading")
        return raw
    finally:
        os.close(descriptor)


@contextmanager
def _current_admission_snapshot(
    path: Path,
    identities: dict[Path, tuple[int, int] | None],
    *, resources: _CurrentAdmissionResources,
) -> Iterator[sqlite3.Connection]:
    """Read a pinned committed snapshot without touching source SQLite/SHM.

    Source WAL appends are safe: SQLite recovers only the captured prefix in a
    private copy. Safely pinned main-content changes discard this attempt;
    a WAL prefix reset still fails admission. Source SHM read marks are neither copied nor modified.
    """

    wal = Path(f"{path}-wal")
    try:
        resources.validate()
        before = os.fstat(resources.main[1])
        raw = _read_existing_database_file(path, identities[path], MAX_READONLY_DATABASE_BYTES,
                                           current_resources=resources)
        wal_raw = _read_wal_prefix(wal, identities[wal]) if identities[wal] is not None else b""
        resources.validate()
        after = os.fstat(resources.main[1])
        if len(raw) + len(wal_raw) > MAX_READONLY_SNAPSHOT_BYTES:
            raise MentatDatabaseError("Mentat database changed while reading")
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise _TransientDatabaseMainFileRace("Mentat database content changed during validation")
        with TemporaryDirectory(prefix="mentat-current-admission-") as temporary:
            copied = Path(temporary) / DATABASE_NAME
            copied.write_bytes(raw)
            _chmod(copied, 0o600)
            if wal_raw:
                copied_wal = Path(f"{copied}-wal")
                copied_wal.write_bytes(wal_raw)
                _chmod(copied_wal, 0o600)
            connection = sqlite3.connect(copied, timeout=5.0, isolation_level=None)
            try:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only = ON")
                yield connection
            finally:
                connection.close()
        resources.validate()
    except (OSError, sqlite3.Error) as exc:
        raise MentatDatabaseError("Mentat database is unavailable") from exc


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
    *, current_resources: _CurrentAdmissionResources | None = None,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    owned = current_resources is None
    try:
        if owned:
            descriptor = os.open(path, flags)
        else:
            current_resources.validate()
            descriptor = current_resources.main[1]
            os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as exc:
        raise MentatDatabaseError("Mentat database is unavailable") from exc
    try:
        before = os.fstat(descriptor)
        ceiling = min(maximum, remaining_total) if remaining_total is not None else maximum
        if current_resources is not None:
            _current_main_metadata(before, identity, ceiling)
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
        if current_resources is not None:
            current_resources.validate()
            _current_main_metadata(before, identity, ceiling)
            _current_main_metadata(after, identity, ceiling)
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or len(raw) != before.st_size
        ):
            if current_resources is not None:
                raise _TransientDatabaseMainFileRace("Mentat database content changed during validation")
            raise MentatDatabaseError("Mentat database file changed while reading")
        return raw
    except OSError as exc:
        raise MentatDatabaseError("Mentat database is unavailable") from exc
    finally:
        if owned:
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
