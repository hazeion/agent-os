from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_registry import (
    DIRECT_AGENT_CAPABILITIES,
    DIRECT_AGENT_ID,
    DIRECT_AGENT_ROLE,
    DIRECT_RUNTIME_AGENT_REF,
    DIRECT_RUNTIME_CONFIG_ID,
    DIRECT_RUNTIME_TYPE,
    AgentRegistry,
)
from conversation_repository import (
    ConversationRepository,
    ConversationRepositoryUnavailable,
    conversations_public,
)
from mentat_db import connect, database_path
from mentat import local_bridge
import server


class ConversationRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._codex_command = patch(
            "codex_runtime.find_codex_command",
            return_value="/usr/bin/codex",
        )
        self._codex_binding = patch(
            "codex_runtime.codex_binding_is_valid",
            return_value=True,
        )
        self._codex_command.start()
        self._codex_binding.start()

    def tearDown(self) -> None:
        self._codex_binding.stop()
        self._codex_command.stop()

    def test_create_seeds_one_fixed_direct_agent_without_creating_a_run(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ConversationRepository(root)

            created = repository.create()
            repeated = repository.create()

            self.assertNotEqual(created.conversation.id, repeated.conversation.id)
            self.assertEqual(created.conversation.agent_id, DIRECT_AGENT_ID)
            self.assertEqual(created.agent.system_role, DIRECT_AGENT_ROLE)
            self.assertEqual(created.agent.agent.runtime_type, DIRECT_RUNTIME_TYPE)
            self.assertEqual(created.agent.agent.runtime_config_id, DIRECT_RUNTIME_CONFIG_ID)
            self.assertEqual(
                created.agent.agent.capabilities,
                frozenset(DIRECT_AGENT_CAPABILITIES),
            )
            self.assertEqual(created.agent.agent.id, DIRECT_AGENT_ID)

            records = AgentRegistry(
                root,
                supported_runtime_types={"codex", "hermes", "vercel"},
            ).list_agent_records()
            self.assertEqual(
                [record.agent.id for record in records],
                [DIRECT_AGENT_ID],
            )
            self.assertEqual(
                records[0].system_role,
                DIRECT_AGENT_ROLE,
            )

            with sqlite3.connect(database_path(root)) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0],
                    0,
                )
                binding = connection.execute(
                    "SELECT runtime_agent_ref FROM agent_runtime_configs WHERE id = ?",
                    (DIRECT_RUNTIME_CONFIG_ID,),
                ).fetchone()
            self.assertEqual(binding[0], DIRECT_RUNTIME_AGENT_REF)

    def test_message_reads_are_bounded_and_cursorable(self):
        with TemporaryDirectory() as temporary:
            repository = ConversationRepository(Path(temporary))
            created = repository.create()
            for sequence in range(101):
                repository.append_message_for_test(
                    created.conversation.id,
                    role="user" if sequence % 2 == 0 else "assistant",
                    text=f"Message {sequence + 1}",
                )

            latest = repository.read(created.conversation.id)
            self.assertEqual(len(latest.messages), 100)
            self.assertEqual(latest.messages[0].sequence, 2)
            self.assertEqual(latest.messages[-1].sequence, 101)
            self.assertEqual(latest.next_message_cursor, "2")

            first_page = repository.read(
                created.conversation.id,
                before_sequence=int(latest.next_message_cursor),
            )
            self.assertEqual([message.sequence for message in first_page.messages], [1])
            self.assertIsNone(first_page.next_message_cursor)
            self.assertEqual(first_page.current_run, None)

            public = conversations_public(repository)
            self.assertEqual(public["count"], 1)
            self.assertEqual(public["direct_agent_id"], DIRECT_AGENT_ID)
            self.assertNotIn("runtime_agent_ref", json.dumps(public))
            self.assertNotIn("runtime_config_id", json.dumps(public))

    def test_conversation_list_is_stably_cursorable(self):
        with TemporaryDirectory() as temporary:
            repository = ConversationRepository(Path(temporary))
            created = [repository.create().conversation.id for _ in range(51)]

            first, cursor = repository.list_page(limit=50)
            self.assertEqual(len(first), 50)
            self.assertIsNotNone(cursor)
            second, next_cursor = repository.list_page(limit=50, cursor=cursor)
            self.assertEqual(len(second), 1)
            self.assertIsNone(next_cursor)
            self.assertEqual({item.id for item in first} | {item.id for item in second}, set(created))

    def test_direct_agent_is_setup_required_when_codex_binding_is_unavailable(self):
        with TemporaryDirectory() as temporary:
            with patch("codex_runtime.find_codex_command", return_value=None):
                repository = ConversationRepository(Path(temporary))
                with self.assertRaisesRegex(Exception, "conversation.agent_required"):
                    repository.create()

    def test_schema_validation_rejects_replaced_conversation_trigger(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = connect(root)
            connection.close()
            with sqlite3.connect(database_path(root)) as connection:
                connection.execute("DROP TRIGGER mentat_conversations_agent_immutable")
                connection.execute(
                    """
                    CREATE TRIGGER mentat_conversations_agent_immutable
                    BEFORE UPDATE OF agent_id ON mentat_conversations
                    BEGIN
                        SELECT NULL;
                    END
                    """
                )
            with self.assertRaisesRegex(
                ConversationRepositoryUnavailable,
                "conversation.schema_unsupported",
            ):
                ConversationRepository(root)._connection()

    def test_bridge_reads_and_creates_only_the_canonical_conversation_projection(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(server, "DATA_DIR", root):
                empty, status = local_bridge.bridge_conversations_payload()
                self.assertEqual(status, 200)
                self.assertEqual(empty["status"], "ready")
                self.assertEqual(empty["conversations"], [])
                self.assertEqual(empty["direct_agent_id"], DIRECT_AGENT_ID)

                created, status = local_bridge.bridge_create_conversation_payload({})
                self.assertEqual(status, 201)
                self.assertEqual(created["status"], "ready")
                conversation_id = created["conversation"]["id"]
                self.assertEqual(created["conversation"]["state"], "active")
                self.assertEqual(created["messages"], [])
                self.assertEqual(created["current_run"], None)
                self.assertNotIn("runtime_agent_ref", json.dumps(created))
                self.assertNotIn("runtime_config_id", json.dumps(created))

                detail, status = local_bridge.bridge_conversation_payload(conversation_id)
                self.assertEqual(status, 200)
                self.assertEqual(detail["conversation"]["id"], conversation_id)
                self.assertEqual(detail["agent"]["id"], DIRECT_AGENT_ID)

                listed, status = local_bridge.bridge_conversations_payload()
                self.assertEqual(status, 200)
                self.assertEqual(listed["count"], 1)
                self.assertEqual(listed["conversations"][0]["id"], conversation_id)

                with sqlite3.connect(database_path(root)) as connection:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0],
                        0,
                    )


if __name__ == "__main__":
    unittest.main()
