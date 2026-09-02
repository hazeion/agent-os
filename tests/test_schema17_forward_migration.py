from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from mentat_db import (
    MIGRATIONS,
    MentatDatabaseError,
    SCHEMA_VERSION,
    connect,
    database_path,
    ensure_private_console_dir,
    schema_signature_state,
)


class Schema17ForwardMigrationTests(unittest.TestCase):
    def _schema16(self, root: Path) -> Path:
        ensure_private_console_dir(root)
        path = database_path(root)
        connection = sqlite3.connect(path)
        try:
            for version, script in MIGRATIONS:
                if version > 16:
                    break
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                    (version,),
                )
            connection.execute(
                "INSERT INTO agent_runtime_configs (id, runtime_type, runtime_agent_ref, created_at, updated_at) "
                "VALUES ('config_17', 'hermes', 'profile-17', 1, 1)"
            )
            connection.execute(
                "INSERT INTO mentat_agents (id, name, runtime_config_id, capabilities_json, created_at, updated_at, revision, system_role) "
                "VALUES ('agent_17', 'Agent 17', 'config_17', '[\"run.start\"]', 1, 1, 1, NULL)"
            )
            timestamp = "2026-08-30T12:00:00Z"
            connection.execute(
                "INSERT INTO mentat_conversations (id, agent_id, title, title_source, state, revision, next_message_sequence, next_turn_ordinal, created_at, updated_at, archived_at) "
                "VALUES ('conv_17', 'agent_17', 'Manual', 'manual', 'active', 4, 1, 1, ?, ?, NULL)",
                (timestamp, timestamp),
            )
            connection.commit()
        finally:
            connection.close()
        path.chmod(0o600)
        return path

    def _schema17(self, root: Path) -> Path:
        ensure_private_console_dir(root)
        path = database_path(root)
        connection = sqlite3.connect(path)
        try:
            for version, script in MIGRATIONS:
                if version > 17:
                    break
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                    (version,),
                )
            connection.commit()
        finally:
            connection.close()
        path.chmod(0o600)
        return path

    def test_exact_schema16_upgrades_and_stores_nonowning_references(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._schema16(root)
            connection = connect(root)
            try:
                self.assertEqual(SCHEMA_VERSION, 23)
                self.assertEqual(schema_signature_state(connection, 23), "expected")
                self.assertIsNone(connection.execute("PRAGMA foreign_key_check").fetchone())
                connection.execute(
                    "INSERT INTO mentat_conversation_planning_context "
                    "(conversation_id, project_id, task_id, created_at, updated_at) "
                    "VALUES ('conv_17', 'project_mentat', 'task@wide', ?, ?)",
                    ("2026-08-30T12:01:00Z", "2026-08-30T12:01:00Z"),
                )
                connection.commit()
                self.assertEqual(
                    connection.execute(
                        "SELECT task_id FROM mentat_conversation_planning_context"
                    ).fetchone()[0],
                    "task@wide",
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE mentat_conversation_planning_context SET project_id = '../bad'"
                    )
                for column, invalid in (("project_id", ".bad"), ("task_id", "@bad")):
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute(
                            f"UPDATE mentat_conversation_planning_context SET {column} = ?",
                            (invalid,),
                        )
            finally:
                connection.close()

    def test_schema16_drift_fails_before_planning_table_creation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._schema16(root)
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                connection.execute("DROP INDEX idx_mentat_conversations_activity")
            finally:
                connection.close()
            with self.assertRaisesRegex(MentatDatabaseError, "schema 16 cannot be safely upgraded"):
                connect(root)
            check = sqlite3.connect(path)
            try:
                self.assertEqual(
                    check.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                    16,
                )
                self.assertIsNone(
                    check.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'mentat_conversation_planning_context'"
                    ).fetchone()
                )
            finally:
                check.close()

    def test_schema17_drift_fails_before_project_authority_tables_are_created(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._schema17(root)
            connection = sqlite3.connect(path, isolation_level=None)
            try:
                connection.execute("CREATE TABLE unexpected_schema17_drift (id INTEGER)")
            finally:
                connection.close()
            with self.assertRaisesRegex(MentatDatabaseError, "schema 17 cannot be safely upgraded"):
                connect(root)
            check = sqlite3.connect(path)
            try:
                self.assertEqual(
                    check.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                    17,
                )
                self.assertIsNone(
                    check.execute(
                        "SELECT name FROM sqlite_master WHERE name = 'mentat_projects'"
                    ).fetchone()
                )
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
