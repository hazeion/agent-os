from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from mentat_db import (
    AGENT_REGISTRY_AUTHORITY_CONTRACT,
    EMPTY_AGENT_REGISTRY_SOURCE_SHA256,
    MIGRATIONS,
    MentatDatabaseError,
    SCHEMA_VERSION,
    connect,
    database_path,
    ensure_private_console_dir,
    migrate,
    schema_signature_state,
)
from private_console_unit import PrivateConsoleUnit, validate_private_console_unit


class Schema16ForwardMigrationTests(unittest.TestCase):
    def _schema15(self, root: Path) -> Path:
        ensure_private_console_dir(root)
        path = database_path(root)
        connection = sqlite3.connect(path)
        try:
            for version, script in MIGRATIONS:
                if version > 15:
                    break
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                    (version,),
                )
            connection.execute(
                "INSERT INTO mentat_agent_registry_state (singleton, authority, "
                "migration_contract, source_kind, source_sha256, "
                "source_agent_count, cutover_at) "
                "VALUES (1, 'sqlite', ?, 'fresh', ?, 1, 1)",
                (
                    AGENT_REGISTRY_AUTHORITY_CONTRACT,
                    EMPTY_AGENT_REGISTRY_SOURCE_SHA256,
                ),
            )
            connection.execute(
                "INSERT INTO agent_runtime_configs (id, runtime_type, "
                "runtime_agent_ref, created_at, updated_at) "
                "VALUES ('config_schema16', 'hermes', 'profile-schema16', 1, 1)"
            )
            connection.execute(
                "INSERT INTO mentat_agents (id, name, runtime_config_id, "
                "capabilities_json, created_at, updated_at, revision, system_role) "
                "VALUES ('agent_schema16', 'Schema Agent', 'config_schema16', "
                "'[\"run.start\"]', 1, 1, 1, NULL)"
            )
            timestamp = "2026-08-29T12:00:00.000Z"
            connection.execute(
                "INSERT INTO mentat_conversations (id, agent_id, title, "
                "title_source, state, revision, next_message_sequence, "
                "next_turn_ordinal, created_at, updated_at, archived_at) "
                "VALUES ('conv_schema16', 'agent_schema16', 'Original', "
                "'first_prompt', 'active', 3, 2, 2, ?, ?, NULL)",
                (timestamp, timestamp),
            )
            content = json.dumps(
                {"parts": [{"text": "First request", "type": "text"}], "schema_version": 1},
                separators=(",", ":"),
                sort_keys=True,
            )
            connection.execute(
                "INSERT INTO mentat_conversation_messages (id, conversation_id, "
                "sequence, role, state, content_json, content_bytes, run_id, "
                "revision, source_key, created_at, updated_at) "
                "VALUES ('msg_schema16', 'conv_schema16', 1, 'user', 'accepted', "
                "?, ?, NULL, 1, 'source_schema16', ?, ?)",
                (content, len(content.encode("utf-8")), timestamp, timestamp),
            )
            digest = hashlib.sha256(b"schema16").hexdigest()
            connection.execute(
                "INSERT INTO mentat_conversation_turns (id, conversation_id, "
                "user_message_id, queue_ordinal, state, blocked_reason, "
                "latest_run_id, revision, attempt_count, idempotency_key_digest, "
                "request_digest, created_at, updated_at) "
                "VALUES ('turn_schema16', 'conv_schema16', 'msg_schema16', 1, "
                "'pending', NULL, NULL, 1, 0, ?, ?, ?, ?)",
                (digest, digest, timestamp, timestamp),
            )
            blob_digest = hashlib.sha256(b"schema16 attachment").hexdigest()
            connection.execute(
                "INSERT INTO blobs (id, sha256, storage_key, byte_size, state, "
                "created_at, updated_at) VALUES ('blob_schema16', ?, ?, 19, "
                "'ready', 1, 1)",
                (blob_digest, f"{blob_digest[:2]}/{blob_digest}"),
            )
            connection.execute(
                "INSERT INTO attachments (id, blob_id, original_name, mime_type, "
                "kind, state, byte_size, created_at, updated_at) VALUES "
                "('attachment_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'blob_schema16', "
                "'context.txt', 'text/plain', 'text', 'attached', 19, 1, 1)"
            )
            connection.execute(
                "INSERT INTO mentat_runs (id, source, agent_id, runtime_type, "
                "runtime_config_id, runtime_binding_digest, capabilities_json, "
                "status, dispatch_state, details_json, created_at, updated_at, "
                "conversation_id, turn_id, agent_revision, "
                "runtime_config_revision, capacity_scope_digest, "
                "admitted_capacity_limit) VALUES ('run_schema16', 'console', "
                "'agent_schema16', 'hermes', 'config_schema16', ?, "
                "'[\"run.start\"]', 'running', 'accepted', '{}', ?, ?, "
                "'conv_schema16', 'turn_schema16', 1, 1, ?, 1)",
                (digest, timestamp, timestamp, digest),
            )
            connection.execute(
                "UPDATE mentat_conversation_messages SET run_id = 'run_schema16' "
                "WHERE id = 'msg_schema16'"
            )
            connection.execute(
                "UPDATE mentat_conversation_turns SET state = 'consumed', "
                "latest_run_id = 'run_schema16' WHERE id = 'turn_schema16'"
            )
            connection.execute(
                "INSERT INTO run_attachments (run_id, attachment_id, direction, "
                "ordinal, created_at) VALUES ('run_schema16', "
                "'attachment_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'input', 0, 1)"
            )
            connection.commit()
        finally:
            connection.close()
        if os.name != "nt":
            path.chmod(0o600)
        return path

    def test_exact_schema15_graph_upgrades_atomically_and_accepts_manual(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._schema15(root)
            connection = connect(root)
            try:
                version = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                self.assertEqual(version, 16)
                self.assertEqual(SCHEMA_VERSION, 16)
                self.assertEqual(schema_signature_state(connection, 16), "expected")
                self.assertIsNone(connection.execute("PRAGMA foreign_key_check").fetchone())
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_conversation_messages"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_conversation_turns"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_runs WHERE id = 'run_schema16'"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM run_attachments WHERE "
                        "run_id = 'run_schema16'"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM mentat_conversation_submission_results "
                        "WHERE turn_id = 'turn_schema16'"
                    ).fetchone()[0],
                    1,
                )
                connection.execute(
                    "UPDATE mentat_conversations SET title_source = 'manual' "
                    "WHERE id = 'conv_schema16'"
                )
                connection.commit()
            finally:
                connection.close()
            self.assertTrue(path.exists())

    def test_schema15_drift_and_active_transaction_fail_before_rewrite(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._schema15(root)
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                connection.execute("DROP INDEX idx_mentat_conversations_activity")
            finally:
                connection.close()
            with self.assertRaisesRegex(
                MentatDatabaseError,
                "schema 15 cannot be safely upgraded",
            ):
                connect(root)
            check = sqlite3.connect(path)
            try:
                self.assertEqual(
                    check.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                    15,
                )
                self.assertIsNone(
                    check.execute(
                        "SELECT name FROM sqlite_master WHERE name = "
                        "'mentat_conversations_v16'"
                    ).fetchone()
                )
            finally:
                check.close()

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._schema15(root)
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                connection.execute("BEGIN")
                with self.assertRaisesRegex(
                    MentatDatabaseError,
                    "started inside a transaction",
                ):
                    migrate(connection)
                connection.rollback()
            finally:
                connection.close()

    def test_released_schema15_remains_a_valid_private_recovery_input(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._schema15(root)
            connection = sqlite3.connect(path)
            try:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("DELETE FROM run_attachments")
                connection.execute("DELETE FROM mentat_runs")
                connection.execute("DELETE FROM mentat_conversations")
                connection.execute("DELETE FROM attachments")
                connection.execute("DELETE FROM blobs")
                connection.execute("DELETE FROM mentat_agents")
                connection.execute("DELETE FROM agent_runtime_configs")
                connection.execute(
                    "UPDATE mentat_agent_registry_state SET source_sha256 = ?, "
                    "source_agent_count = 0",
                    (EMPTY_AGENT_REGISTRY_SOURCE_SHA256,),
                )
                connection.commit()
            finally:
                connection.close()
            unit = PrivateConsoleUnit(
                history_raw=b'{"runs":[],"schema_version":3}\n',
                database_raw=path.read_bytes(),
                registry_database_raw=None,
                blobs=(),
            )
            validated = validate_private_console_unit(unit)
            self.assertEqual(validated.database_raw, unit.database_raw)


if __name__ == "__main__":
    unittest.main()
