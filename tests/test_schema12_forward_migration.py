from __future__ import annotations

from contextlib import closing
import re
import sqlite3
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from conversation_repository import canonical_message_content, validate_repository_connection
from agent_registry import validate_registry_connection
from vercel_connections import validate_provider_connections
import mentat_db
from mentat_db import (
    AGENT_REGISTRY_AUTHORITY_CONTRACT,
    EMPTY_AGENT_REGISTRY_SOURCE_SHA256,
    MIGRATIONS,
    SCHEMA_VERSION,
    connect,
    database_path,
    ensure_private_console_dir,
)
import private_console_unit
from private_console_unit import capture_private_console_unit
from run_repository import RUN_AUTHORITY_CONTRACT, RunRepository
from task_repository import TASK_AUTHORITY_CONTRACT


LEGACY_TRIGGER_NAMES = (
    "mentat_conversations_agent_immutable",
    "mentat_conversation_turns_queue_capacity_insert",
    "mentat_conversation_turns_queue_capacity_update",
    "mentat_conversation_turns_conversation_immutable",
)


def _legacy_schema_10_script() -> str:
    script = dict(MIGRATIONS)[10]
    current_constraint = """blocked_reason TEXT CHECK (
                blocked_reason IS NULL OR blocked_reason IN (
                    'capacity', 'failed', 'stopped', 'interrupted', 'unknown', 'partial'
                )
            ),"""
    legacy_constraint = """blocked_reason TEXT CHECK (
                blocked_reason IS NULL OR length(blocked_reason) BETWEEN 1 AND 64
            ),"""
    script, count = script.replace(current_constraint, legacy_constraint), script.count(
        current_constraint
    )
    if count != 1:
        raise AssertionError("schema-10 blocked-reason fixture is stale")
    for name in LEGACY_TRIGGER_NAMES:
        script, count = re.subn(
            rf"\n\s*CREATE TRIGGER {name}\b.*?\n\s*END;\n",
            "\n",
            script,
            count=1,
            flags=re.DOTALL,
        )
        if count != 1:
            raise AssertionError(f"schema-10 trigger fixture is stale: {name}")
    return script


def _apply_schema_11(
    connection: sqlite3.Connection,
    *,
    legacy_conversation_drift: bool,
) -> None:
    for version, original in MIGRATIONS:
        if version > 11:
            break
        script = (
            _legacy_schema_10_script()
            if version == 10 and legacy_conversation_drift
            else original
        )
        connection.executescript(script)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, float(version)),
        )


def _apply_schema_12(
    connection: sqlite3.Connection,
    *,
    legacy_conversation_drift: bool = False,
) -> None:
    _apply_schema_11(
        connection,
        legacy_conversation_drift=legacy_conversation_drift,
    )
    foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    if foreign_keys:
        connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(dict(MIGRATIONS)[12])
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (12, 12)"
        )
    finally:
        if foreign_keys:
            connection.execute("PRAGMA foreign_keys = ON")


def _apply_schema_13(connection: sqlite3.Connection) -> None:
    _apply_schema_12(connection)
    connection.executescript(dict(MIGRATIONS)[13])
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (13, 13)"
    )


def _apply_schema_14(connection: sqlite3.Connection) -> None:
    _apply_schema_13(connection)
    connection.executescript(dict(MIGRATIONS)[14])
    connection.execute(
        "INSERT INTO schema_migrations(version, applied_at) VALUES (14, 14)"
    )


def _seed_conversation_turn(
    connection: sqlite3.Connection,
    *,
    blocked_reason: str,
) -> None:
    timestamp = "2026-08-27T12:00:00+00:00"
    _content, content_json, content_bytes = canonical_message_content(
        "Queued work",
        role="user",
    )
    connection.execute(
        "INSERT INTO agent_runtime_configs(id, runtime_type, runtime_agent_ref, "
        "created_at, updated_at) VALUES ('config_test', 'codex', 'default', 1, 1)"
    )
    connection.execute(
        "INSERT INTO mentat_agents(id, name, runtime_config_id, capabilities_json, "
        "created_at, updated_at, revision, system_role) "
        "VALUES ('agent_test', 'Test Agent', 'config_test', '[\"run.start\"]', "
        "1, 1, 1, NULL)"
    )
    connection.execute(
        "INSERT INTO mentat_conversations(id, agent_id, title, title_source, state, "
        "revision, next_message_sequence, next_turn_ordinal, created_at, updated_at) "
        "VALUES ('conversation_test', 'agent_test', 'Test', 'default', 'active', "
        "1, 2, 2, ?, ?)",
        (timestamp, timestamp),
    )
    connection.execute(
        "INSERT INTO mentat_conversation_messages(id, conversation_id, sequence, "
        "role, state, content_json, content_bytes, revision, source_key, created_at, "
        "updated_at) VALUES ('message_test', 'conversation_test', 1, 'user', "
        "'accepted', ?, ?, 1, 'source-test', ?, ?)",
        (content_json, content_bytes, timestamp, timestamp),
    )
    connection.execute(
        "INSERT INTO mentat_conversation_turns(id, conversation_id, user_message_id, "
        "queue_ordinal, state, blocked_reason, revision, attempt_count, "
        "idempotency_key_digest, request_digest, created_at, updated_at) "
        "VALUES ('turn_test', 'conversation_test', 'message_test', 1, 'blocked', ?, "
        "1, 0, ?, ?, ?, ?)",
        (blocked_reason, "a" * 64, "b" * 64, timestamp, timestamp),
    )


def _seed_authoritative_graph(connection: sqlite3.Connection) -> None:
    timestamp = "2026-08-27T12:00:00+00:00"
    connection.execute(
        "INSERT INTO mentat_agent_registry_state(singleton, authority, "
        "migration_contract, source_kind, source_sha256, source_agent_count, "
        "cutover_at) VALUES (1, 'sqlite', ?, 'legacy', ?, 1, 1)",
        (AGENT_REGISTRY_AUTHORITY_CONTRACT, "c" * 64),
    )
    connection.execute(
        "INSERT INTO mentat_task_store_state(singleton, authority, "
        "migration_contract, source_sha256, source_task_count, cutover_at) "
        "VALUES (1, 'sqlite', ?, ?, 1, 1)",
        (TASK_AUTHORITY_CONTRACT, "d" * 64),
    )
    connection.execute(
        "INSERT INTO mentat_tasks(id, sort_order, revision, title, description, "
        "project, status, priority, assigned_agent_id_present, source, "
        "review_required, needs_attention, depends_on_present, nested_planning_json, "
        "extensions_json, created_at, updated_at) VALUES "
        "('task_test', 0, 3, 'Preserve task', 'Migration fixture', 'Mentat', "
        "'in progress', 'high', 0, 'test', 1, 0, 0, '{}', '{}', ?, ?)",
        (timestamp, timestamp),
    )
    connection.execute(
        "INSERT INTO mentat_task_tags(task_id, ordinal, tag) "
        "VALUES ('task_test', 0, 'schema-12')"
    )
    connection.execute(
        "INSERT INTO mentat_run_store_state(singleton, authority, "
        "migration_contract, source_sha256, source_run_count, cutover_at) "
        "VALUES (1, 'sqlite', ?, ?, 1, 1)",
        (RUN_AUTHORITY_CONTRACT, "e" * 64),
    )
    connection.execute(
        "INSERT INTO mentat_runs(id, source, agent_id, runtime_type, "
        "runtime_config_id, runtime_binding_digest, capabilities_json, status, "
        "dispatch_state, details_json, created_at, updated_at, started_at, "
        "completed_at, conversation_id, turn_id) VALUES "
        "('run_test', 'console', 'agent_test', 'codex', 'config_test', ?, "
        "'[\"run.start\"]', 'completed', 'accepted', '{}', ?, ?, ?, ?, "
        "'conversation_test', 'turn_test')",
        ("f" * 64, timestamp, timestamp, timestamp, timestamp),
    )
    connection.execute(
        "UPDATE mentat_conversation_turns SET latest_run_id = 'run_test' "
        "WHERE id = 'turn_test'"
    )


PRESERVED_GRAPH_TABLES = (
    "agent_runtime_configs",
    "mentat_agents",
    "mentat_agent_registry_state",
    "mentat_tasks",
    "mentat_task_tags",
    "mentat_task_store_state",
    "mentat_conversations",
    "mentat_conversation_messages",
    "mentat_conversation_turns",
    "mentat_runs",
    "mentat_run_store_state",
    "mentat_conversation_submission_results",
)


def _graph_snapshot(
    connection: sqlite3.Connection,
    *,
    columns: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, list[tuple[object, ...]]]:
    result: dict[str, list[tuple[object, ...]]] = {}
    for table in PRESERVED_GRAPH_TABLES:
        selected = (
            columns[table]
            if columns is not None
            else tuple(
                str(row[1])
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            )
        )
        quoted = ", ".join(f'"{column}"' for column in selected)
        result[table] = [
            tuple(row)
            for row in connection.execute(f'SELECT {quoted} FROM "{table}"')
        ]
    return result


class Schema12ForwardMigrationTests(unittest.TestCase):
    def _connection(self, path: Path, *, legacy: bool) -> sqlite3.Connection:
        connection = sqlite3.connect(path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        _apply_schema_11(connection, legacy_conversation_drift=legacy)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _schema_12_connection(self, path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        _apply_schema_12(connection)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _seed_terminal_evidence(
        connection: sqlite3.Connection,
        *,
        source_type: str,
        source_key: str,
    ) -> None:
        connection.execute(
            "INSERT INTO mentat_agent_events(run_id, sequence, id, event_type, "
            "source_type, source_key, occurred_at, summary, content, metrics_json, "
            "data_json, content_bytes, payload_digest) VALUES "
            "('run_test', 1, 'event_terminal', 'run.completed', ?, ?, "
            "'2026-08-27T12:00:00+00:00', 'Run completed', NULL, '{}', '{}', 0, ?)",
            (source_type, source_key, "0" * 64),
        )
        connection.execute(
            "UPDATE mentat_runs SET last_event_sequence = 1 WHERE id = 'run_test'"
        )

    def test_exact_schema_12_migrates_atomically_and_preserves_its_graph(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema-12.sqlite3"
            with closing(self._schema_12_connection(path)) as connection:
                _seed_conversation_turn(connection, blocked_reason="failed")
                _seed_authoritative_graph(connection)
                columns = {
                    table: tuple(
                        str(column[1])
                        for column in connection.execute(
                            f'PRAGMA table_info("{table}")'
                        )
                    )
                    for table in PRESERVED_GRAPH_TABLES
                }
                before = _graph_snapshot(connection)

                mentat_db.migrate(connection)

                after = _graph_snapshot(connection, columns=columns)
                version = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                finalized = connection.execute(
                    "SELECT terminal_finalized FROM mentat_runs WHERE id = 'run_test'"
                ).fetchone()[0]

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertEqual(after, before)
        self.assertEqual(finalized, 1)

    def test_schema_12_drift_is_rejected_before_column_or_receipt(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema-12-drift.sqlite3"
            with closing(self._schema_12_connection(path)) as connection:
                connection.execute(
                    "ALTER TABLE mentat_runs ADD COLUMN unauthorized_payload TEXT"
                )

                with self.assertRaisesRegex(
                    mentat_db.MentatDatabaseError,
                    "schema 12 cannot be safely upgraded",
                ):
                    mentat_db.migrate(connection)

                version = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(mentat_runs)")
                }

        self.assertEqual(version, 12)
        self.assertNotIn("terminal_finalized", columns)

    def test_schema_12_terminal_evidence_backfills_only_exact_finalization(self):
        cases = (
            (None, None, 0),
            ("runtime.finalized", "console:event_terminal", 1),
            ("run.completed", "runtime:event_terminal", 1),
            ("run.completed", "runtime-status:run_test:completed", 0),
        )
        for source_type, source_key, expected in cases:
            with self.subTest(source_type=source_type, source_key=source_key), TemporaryDirectory() as temporary:
                path = Path(temporary) / "terminal.sqlite3"
                with closing(self._schema_12_connection(path)) as connection:
                    _seed_conversation_turn(connection, blocked_reason="failed")
                    _seed_authoritative_graph(connection)
                    connection.execute(
                        "UPDATE agent_runtime_configs SET runtime_type = 'hermes', "
                        "runtime_agent_ref = 'default' WHERE id = 'config_test'"
                    )
                    connection.execute(
                        "UPDATE mentat_runs SET runtime_type = 'hermes' "
                        "WHERE id = 'run_test'"
                    )
                    if source_type is not None and source_key is not None:
                        self._seed_terminal_evidence(
                            connection,
                            source_type=source_type,
                            source_key=source_key,
                        )

                    mentat_db.migrate(connection)
                    finalized = connection.execute(
                        "SELECT terminal_finalized FROM mentat_runs "
                        "WHERE id = 'run_test'"
                    ).fetchone()[0]

            self.assertEqual(finalized, expected)

    def test_schema_12_claimed_continuation_pins_canonicalize_before_recovery(self):
        cases = (
            ("submitting", "submitting", "dispatching"),
            ("running", "accepted", "consumed"),
        )
        for status, dispatch_state, turn_state in cases:
            with self.subTest(dispatch_state=dispatch_state), TemporaryDirectory() as temporary:
                path = Path(temporary) / f"claimed-{dispatch_state}.sqlite3"
                with closing(self._schema_12_connection(path)) as connection:
                    _seed_conversation_turn(connection, blocked_reason="failed")
                    _seed_authoritative_graph(connection)
                    timestamp = "2026-08-27T12:00:01+00:00"
                    _content, content_json, content_bytes = canonical_message_content(
                        "Continue the exact prior thread",
                        role="user",
                    )
                    connection.execute(
                        "UPDATE mentat_conversations SET next_message_sequence = 3, "
                        "next_turn_ordinal = 3 WHERE id = 'conversation_test'"
                    )
                    connection.execute(
                        "INSERT INTO mentat_conversation_messages("
                        "id, conversation_id, sequence, role, state, content_json, "
                        "content_bytes, revision, source_key, created_at, updated_at) "
                        "VALUES ('message_resume', 'conversation_test', 2, 'user', "
                        "'accepted', ?, ?, 1, 'source-resume', ?, ?)",
                        (content_json, content_bytes, timestamp, timestamp),
                    )
                    connection.execute(
                        "INSERT INTO mentat_conversation_turns("
                        "id, conversation_id, user_message_id, queue_ordinal, state, "
                        "blocked_reason, revision, attempt_count, idempotency_key_digest, "
                        "request_digest, created_at, updated_at) VALUES ("
                        "'turn_resume', 'conversation_test', 'message_resume', 2, ?, "
                        "NULL, 1, 1, ?, ?, ?, ?)",
                        (turn_state, "1" * 64, "2" * 64, timestamp, timestamp),
                    )
                    connection.execute(
                        "INSERT INTO mentat_runs("
                        "id, source, agent_id, runtime_type, runtime_config_id, "
                        "runtime_binding_digest, capabilities_json, status, "
                        "dispatch_state, details_json, created_at, updated_at, "
                        "started_at, completed_at, conversation_id, turn_id, "
                        "resume_of_run_id) VALUES ("
                        "'run_resume', 'console', 'agent_test', 'codex', "
                        "'config_test', ?, '[\"run.start\"]', ?, ?, '{}', ?, ?, ?, "
                        "NULL, 'conversation_test', 'turn_resume', 'run_test')",
                        ("f" * 64, status, dispatch_state, timestamp, timestamp, timestamp),
                    )
                    connection.execute(
                        "UPDATE mentat_conversation_turns SET latest_run_id = 'run_resume' "
                        "WHERE id = 'turn_resume'"
                    )
                    self.assertEqual(
                        private_console_unit._schema_signature_state(connection, 12),
                        "expected",
                    )

                    mentat_db.migrate(connection)
                    after_migration = connection.execute(
                        "SELECT status, dispatch_state, resume_of_run_id "
                        "FROM mentat_runs WHERE id = 'run_resume'"
                    ).fetchone()
                    repository = RunRepository(connection)
                    recovered = repository.recover_conversation_submissions(
                        now="2028-01-01T00:00:00+00:00",
                    )
                    repeated = repository.recover_conversation_submissions(
                        now="2028-01-01T00:00:01+00:00",
                    )
                    after_recovery = connection.execute(
                        "SELECT status, dispatch_state, partial, resume_of_run_id "
                        "FROM mentat_runs WHERE id = 'run_resume'"
                    ).fetchone()
                    foreign_key_issues = connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall()

            self.assertEqual(
                tuple(after_migration),
                (status, dispatch_state, None),
            )
            self.assertEqual(recovered, ("run_resume",))
            self.assertEqual(repeated, ())
            self.assertEqual(
                tuple(after_recovery),
                ("unknown", "unknown", 1, None),
            )
            self.assertEqual(foreign_key_issues, [])

    def test_exact_legacy_schema_11_can_be_captured_before_upgrade(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            ensure_private_console_dir(root)
            path = database_path(root)
            with closing(self._connection(path, legacy=True)) as connection:
                self.assertEqual(
                    private_console_unit._schema_signature_state(connection, 11),
                    "known_legacy_conversation_drift",
                )
                connection.execute(
                    "INSERT INTO mentat_agent_registry_state(singleton, authority, "
                    "migration_contract, source_kind, source_sha256, source_agent_count, "
                    "cutover_at) VALUES (1, 'sqlite', ?, 'fresh', ?, 0, 1)",
                    (
                        AGENT_REGISTRY_AUTHORITY_CONTRACT,
                        EMPTY_AGENT_REGISTRY_SOURCE_SHA256,
                    ),
                )
                connection.execute(
                    "INSERT INTO mentat_run_store_state(singleton, authority, "
                    "migration_contract, source_sha256, source_run_count, cutover_at) "
                    "VALUES (1, 'sqlite', ?, ?, 0, 1)",
                    (RUN_AUTHORITY_CONTRACT, EMPTY_AGENT_REGISTRY_SOURCE_SHA256),
                )
            if hasattr(path, "chmod"):
                path.chmod(0o600)

            captured = capture_private_console_unit(root)
            source_after_capture = sqlite3.connect(
                f"{path.absolute().as_uri()}?mode=ro",
                uri=True,
            )
            try:
                source_version_after_capture = source_after_capture.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
            finally:
                source_after_capture.close()
            migrated = connect(root)
            try:
                version = migrated.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
            finally:
                migrated.close()

        self.assertEqual(captured.run_count, 0)
        self.assertEqual(source_version_after_capture, 11)
        self.assertEqual(version, SCHEMA_VERSION)

    def test_schema_14_upgrades_only_the_exact_schema_13_attempt_boundary(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            ensure_private_console_dir(root)
            path = database_path(root)
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                _apply_schema_13(connection)
            finally:
                connection.close()
            path.chmod(0o600)

            migrated = connect(root)
            try:
                version = int(
                    migrated.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                )
                attempt_table = migrated.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'mentat_conversation_run_attempts'"
                ).fetchone()
            finally:
                migrated.close()

            drift_root = Path(temporary) / "drift"
            ensure_private_console_dir(drift_root)
            drift_path = database_path(drift_root)
            drift = sqlite3.connect(drift_path, isolation_level=None)
            try:
                _apply_schema_13(drift)
                drift.execute(
                    "DROP TRIGGER mentat_conversation_submission_result_insert"
                )
                drift.executescript(
                    """
                    CREATE TRIGGER mentat_conversation_submission_result_insert
                    AFTER INSERT ON mentat_runs
                    BEGIN
                        SELECT NULL;
                    END;
                    """
                )
            finally:
                drift.close()
            drift_path.chmod(0o600)
            with self.assertRaisesRegex(
                mentat_db.MentatDatabaseError,
                "schema 13 cannot be safely upgraded",
            ):
                connect(drift_root)
            read_only = sqlite3.connect(drift_path)
            try:
                drift_version = int(
                    read_only.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                )
                drift_attempt_table = read_only.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'mentat_conversation_run_attempts'"
                ).fetchone()
            finally:
                read_only.close()

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertIsNotNone(attempt_table)
        self.assertEqual(drift_version, 13)
        self.assertIsNone(drift_attempt_table)

    def test_schema_15_adds_conversation_staging_without_granting_agent_permission(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            ensure_private_console_dir(root)
            path = database_path(root)
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                _apply_schema_14(connection)
                connection.execute(
                    "INSERT INTO agent_runtime_configs(id, runtime_type, runtime_agent_ref, created_at, updated_at) "
                    "VALUES ('config_hermes', 'hermes', 'default', 1, 1)"
                )
                connection.execute(
                    "INSERT INTO mentat_agents(id, name, runtime_config_id, capabilities_json, "
                    "created_at, updated_at, revision, system_role) "
                    "VALUES ('agent_hermes', 'Hermes', 'config_hermes', '[\"run.start\"]', 1, 1, 1, NULL)"
                )
                connection.execute(
                    "INSERT INTO mentat_agent_registry_state(singleton, authority, "
                    "migration_contract, source_kind, source_sha256, source_agent_count, cutover_at) "
                    "VALUES (1, 'sqlite', ?, 'legacy', ?, 1, 1)",
                    (AGENT_REGISTRY_AUTHORITY_CONTRACT, "c" * 64),
                )
                connection.row_factory = sqlite3.Row
                validate_repository_connection(connection, schema_version=14)
                RunRepository(connection)
                validate_registry_connection(
                    connection,
                    supported_runtime_types=("codex", "hermes", "vercel"),
                    runtime_binding_validator=lambda _agent, _reference: True,
                )
                validate_provider_connections(connection)
            finally:
                connection.close()
            path.chmod(0o600)

            migrated = connect(root)
            try:
                version = int(migrated.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0])
                tables = {
                    str(row[0])
                    for row in migrated.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                agent = migrated.execute(
                    "SELECT capabilities_json, revision FROM mentat_agents WHERE id = 'agent_hermes'"
                ).fetchone()
            finally:
                migrated.close()

        self.assertEqual(version, SCHEMA_VERSION)
        self.assertTrue({
            "mentat_conversation_staged_contexts",
            "mentat_conversation_staged_attachments",
            "mentat_conversation_run_contexts",
        }.issubset(tables))
        self.assertEqual(tuple(agent), ('["run.start"]', 1))

    def test_schema_15_rejects_schema_14_drift_before_staging_tables(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            ensure_private_console_dir(root)
            path = database_path(root)
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                _apply_schema_14(connection)
                connection.execute(
                    "DROP INDEX idx_mentat_conversation_run_attempts_turn"
                )
            finally:
                connection.close()
            path.chmod(0o600)

            with self.assertRaisesRegex(
                mentat_db.MentatDatabaseError,
                "schema 14 cannot be safely upgraded",
            ):
                connect(root)

            read_only = sqlite3.connect(path)
            try:
                version = int(
                    read_only.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                )
                staging_table = read_only.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'mentat_conversation_staged_contexts'"
                ).fetchone()
            finally:
                read_only.close()

        self.assertEqual(version, 14)
        self.assertIsNone(staging_table)

    def test_upgrade_preserves_turn_rows_and_restores_exact_constraints(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "legacy.sqlite3"
            with closing(self._connection(path, legacy=True)) as connection:
                _seed_conversation_turn(connection, blocked_reason="failed")
                _seed_authoritative_graph(connection)
                columns = {
                    table: tuple(
                        str(column[1])
                        for column in connection.execute(
                            f'PRAGMA table_info("{table}")'
                        )
                    )
                    for table in PRESERVED_GRAPH_TABLES
                }
                before = _graph_snapshot(connection)
                mentat_db.migrate(connection)
                after = _graph_snapshot(connection, columns=columns)

                row = connection.execute(
                    "SELECT state, blocked_reason, revision FROM mentat_conversation_turns "
                    "WHERE id = 'turn_test'"
                ).fetchone()
                trigger_names = {
                    str(item[0])
                    for item in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                    )
                }
                foreign_key_issues = connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE mentat_conversation_turns SET blocked_reason = 'future' "
                        "WHERE id = 'turn_test'"
                    )

        self.assertEqual(tuple(row), ("blocked", "failed", 1))
        self.assertEqual(after, before)
        self.assertTrue(set(LEGACY_TRIGGER_NAMES).issubset(trigger_names))
        self.assertEqual(foreign_key_issues, [])
        self.assertEqual(foreign_keys, 1)

    def test_invalid_legacy_blocked_reason_rolls_back_schema_and_receipt(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.sqlite3"
            with closing(self._connection(path, legacy=True)) as connection:
                _seed_conversation_turn(connection, blocked_reason="future")

                with self.assertRaises(sqlite3.IntegrityError):
                    mentat_db.migrate(connection)

                version = connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                table_sql = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'mentat_conversation_turns'"
                ).fetchone()[0]
                temporary_table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = "
                    "'mentat_conversation_turns_v12'"
                ).fetchone()
                foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

        self.assertEqual(version, 11)
        self.assertIn("length(blocked_reason) BETWEEN 1 AND 64", table_sql)
        self.assertIsNone(temporary_table)
        self.assertEqual(foreign_keys, 1)

    def test_unrecognized_schema_11_near_misses_are_rejected_before_rewrite(self):
        for mutation in (
            "missing_trigger",
            "modified_trigger",
            "modified_table",
            "extra_table",
        ):
            with self.subTest(mutation=mutation), TemporaryDirectory() as temporary:
                path = Path(temporary) / f"{mutation}.sqlite3"
                with closing(self._connection(path, legacy=False)) as connection:
                    if mutation == "missing_trigger":
                        connection.execute(
                            "DROP TRIGGER "
                            "mentat_conversation_turns_queue_capacity_insert"
                        )
                    elif mutation == "modified_trigger":
                        connection.execute(
                            "DROP TRIGGER "
                            "mentat_conversation_turns_queue_capacity_insert"
                        )
                        connection.execute(
                            "CREATE TRIGGER "
                            "mentat_conversation_turns_queue_capacity_insert "
                            "BEFORE INSERT ON mentat_conversation_turns "
                            "BEGIN SELECT NULL; END"
                        )
                    elif mutation == "modified_table":
                        connection.execute(
                            "ALTER TABLE mentat_conversation_turns "
                            "ADD COLUMN unauthorized TEXT"
                        )
                    else:
                        connection.execute(
                            "CREATE TABLE unexpected_schema_object(value TEXT)"
                        )

                    self.assertEqual(
                        private_console_unit._schema_signature_state(
                            connection,
                            11,
                        ),
                        "invalid",
                    )
                    with self.assertRaisesRegex(
                        mentat_db.MentatDatabaseError,
                        "cannot be safely upgraded",
                    ):
                        mentat_db.migrate(connection)

                    version = connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                    temporary_table = connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE name = "
                        "'mentat_conversation_turns_v12'"
                    ).fetchone()
                    foreign_keys = connection.execute(
                        "PRAGMA foreign_keys"
                    ).fetchone()[0]

                self.assertEqual(version, 11)
                self.assertIsNone(temporary_table)
                self.assertEqual(foreign_keys, 1)

    def test_literal_whitespace_drift_is_rejected_before_rewrite(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "literal-whitespace.sqlite3"
            with closing(self._connection(path, legacy=True)) as connection:
                connection.execute("PRAGMA writable_schema = ON")
                connection.execute(
                    "UPDATE sqlite_master SET sql = replace(sql, ?, ?) "
                    "WHERE name = 'mentat_conversation_turns'",
                    ("'pending'", "'pen ding'"),
                )
                connection.execute("PRAGMA writable_schema = OFF")

                self.assertEqual(
                    private_console_unit._schema_signature_state(connection, 11),
                    "invalid",
                )
                with self.assertRaisesRegex(
                    mentat_db.MentatDatabaseError,
                    "cannot be safely upgraded",
                ):
                    mentat_db.migrate(connection)

                self.assertEqual(
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0],
                    11,
                )
                self.assertIsNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE name = "
                        "'mentat_conversation_turns_v12'"
                    ).fetchone()
                )

    def test_schema_writer_cannot_race_exact_gate_and_rewrite(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema-race.sqlite3"
            connection = sqlite3.connect(path, isolation_level=None)
            connection.row_factory = sqlite3.Row
            _apply_schema_12(connection)
            connection.execute("PRAGMA foreign_keys = ON")
            with closing(connection):
                original_classifier = mentat_db.schema_signature_state
                racer_outcomes: list[str] = []

                def classify_with_racer(
                    gated_connection: sqlite3.Connection,
                    schema_version: int,
                ) -> str:
                    state = original_classifier(gated_connection, schema_version)
                    completed = threading.Event()

                    def race_schema_writer() -> None:
                        racer = sqlite3.connect(path, timeout=0, isolation_level=None)
                        try:
                            racer.execute(
                                "ALTER TABLE mentat_runs "
                                "ADD COLUMN raced_payload TEXT"
                            )
                            racer_outcomes.append("succeeded")
                        except sqlite3.OperationalError as exc:
                            racer_outcomes.append(str(exc))
                        finally:
                            racer.close()
                            completed.set()

                    writer = threading.Thread(target=race_schema_writer)
                    writer.start()
                    self.assertTrue(completed.wait(timeout=2))
                    writer.join(timeout=2)
                    return state

                with mock.patch.object(
                    mentat_db,
                    "schema_signature_state",
                    side_effect=classify_with_racer,
                ):
                    mentat_db.migrate(connection)

                columns = {
                    str(row[1])
                    for row in connection.execute(
                        "PRAGMA table_info(mentat_runs)"
                    )
                }

        self.assertEqual(len(racer_outcomes), SCHEMA_VERSION - 12)
        self.assertTrue(
            all("locked" in outcome.lower() for outcome in racer_outcomes)
        )
        self.assertNotIn("raced_payload", columns)

    def test_active_caller_transaction_is_never_committed_by_schema_rewrite(self):
        for foreign_keys in (0, 1):
            with self.subTest(foreign_keys=foreign_keys), TemporaryDirectory() as temporary:
                path = Path(temporary) / f"transaction-{foreign_keys}.sqlite3"
                with closing(self._connection(path, legacy=False)) as connection:
                    connection.execute(f"PRAGMA foreign_keys = {foreign_keys}")
                    connection.execute("BEGIN")
                    connection.execute(
                        "UPDATE schema_migrations SET applied_at = 4242 "
                        "WHERE version = 1"
                    )

                    with self.assertRaisesRegex(
                        mentat_db.MentatDatabaseError,
                        "inside a transaction",
                    ):
                        mentat_db.migrate(connection)

                    self.assertTrue(connection.in_transaction)
                    self.assertEqual(
                        connection.execute(
                            "SELECT applied_at FROM schema_migrations WHERE version = 1"
                        ).fetchone()[0],
                        4242,
                    )
                    self.assertEqual(
                        connection.execute(
                            "SELECT MAX(version) FROM schema_migrations"
                        ).fetchone()[0],
                        11,
                    )
                    connection.rollback()
                    self.assertEqual(
                        connection.execute(
                            "SELECT applied_at FROM schema_migrations WHERE version = 1"
                        ).fetchone()[0],
                        1.0,
                    )

    def test_released_and_legacy_schema_11_converge_to_current_schema(self):
        with TemporaryDirectory() as temporary:
            base = Path(temporary)
            with closing(self._connection(base / "released.sqlite3", legacy=False)) as released:
                mentat_db.migrate(released)
                released_signature = private_console_unit._schema_signature(released)
            with closing(self._connection(base / "legacy.sqlite3", legacy=True)) as legacy:
                mentat_db.migrate(legacy)
                legacy_signature = private_console_unit._schema_signature(legacy)

        self.assertEqual(released_signature, legacy_signature)
        self.assertEqual(
            released_signature,
            private_console_unit._expected_schema_signature(SCHEMA_VERSION),
        )


if __name__ == "__main__":
    unittest.main()
