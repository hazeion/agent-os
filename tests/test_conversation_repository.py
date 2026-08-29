from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

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
    ConversationRepositoryValidationError,
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

            with closing(sqlite3.connect(database_path(root))) as connection:
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

    def test_history_search_pages_all_1024_titles_and_binds_cursor(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ConversationRepository(root)
            first = repository.create().conversation
            with closing(connect(root)) as connection:
                for index in range(1, 1024):
                    state = "archived" if index % 2 else "active"
                    timestamp = f"2026-08-{1 + index % 28:02d}T12:{index % 60:02d}:00.000Z"
                    connection.execute(
                        "INSERT INTO mentat_conversations (id, agent_id, title, "
                        "title_source, state, revision, next_message_sequence, "
                        "next_turn_ordinal, created_at, updated_at, archived_at) "
                        "VALUES (?, ?, ?, 'manual', ?, 1, 1, 1, ?, ?, ?)",
                        (
                            f"conv_history_{index:04d}",
                            first.agent_id,
                            f"Straße record {index:04d}",
                            state,
                            timestamp,
                            timestamp,
                            timestamp if state == "archived" else None,
                        ),
                    )
                connection.commit()

            seen = []
            cursor = None
            while True:
                page, cursor = repository.history_page(
                    state="all",
                    cursor=cursor,
                )
                self.assertLessEqual(len(page), 50)
                seen.extend(record.id for record in page)
                if cursor is None:
                    break
            self.assertEqual(len(seen), 1024)
            self.assertEqual(len(set(seen)), 1024)

            matches, cursor = repository.history_page(
                state="active",
                query="STRASSE",
            )
            self.assertTrue(matches)
            self.assertTrue(all(record.state == "active" for record in matches))
            self.assertTrue(all("strasse" in record.title.casefold() for record in matches))
            self.assertIsNotNone(cursor)
            with self.assertRaisesRegex(
                ConversationRepositoryValidationError,
                "conversation.cursor_invalid",
            ):
                repository.history_page(
                    state="archived",
                    query="STRASSE",
                    cursor=cursor,
                )
            with self.assertRaisesRegex(
                ConversationRepositoryValidationError,
                "conversation.cursor_invalid",
            ):
                repository.history_page(
                    state="active",
                    query="record",
                    cursor=cursor,
                )
            repository.append_message_for_test(
                first.id,
                role="user",
                text="message-only-private-needle",
            )
            message_only, _cursor = repository.history_page(
                state="all",
                query="private-needle",
            )
            self.assertEqual(message_only, ())
            for invalid_query in ("", " padded ", "line\nbreak", "x" * 161):
                with self.assertRaisesRegex(
                    ConversationRepositoryValidationError,
                    "conversation.query_invalid",
                ):
                    repository.history_page(state="all", query=invalid_query)

    def test_manual_rename_is_exact_archived_safe_and_private(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ConversationRepository(root)
            created = repository.create().conversation
            archived = repository.set_archived(
                created.id,
                expected_revision=created.revision,
                archived=True,
            )
            renamed = repository.rename(
                created.id,
                expected_revision=archived.revision,
                title="Manual title",
            )
            self.assertEqual(renamed.title, "Manual title")
            self.assertEqual(renamed.title_source, "manual")
            self.assertEqual(renamed.state, "archived")
            self.assertEqual(
                ConversationRepository(root).read(created.id).conversation.title,
                "Manual title",
            )
            with self.assertRaisesRegex(Exception, "conversation.changed"):
                repository.rename(
                    created.id,
                    expected_revision=archived.revision,
                    title="Stale",
                )
            for invalid in ("", " padded ", "line\nbreak", "unsafe\u202e"):
                with self.assertRaisesRegex(Exception, "conversation.title_invalid"):
                    repository.rename(
                        created.id,
                        expected_revision=renamed.revision,
                        title=invalid,
                    )

            with patch.object(server, "DATA_DIR", root):
                history, status = local_bridge.bridge_conversation_history_payload(
                    state="archived",
                    query="MANUAL",
                )
                self.assertEqual(status, 200)
                self.assertEqual(len(history["conversations"]), 1)
                serialized = json.dumps(history)
                for private in ("messages", "runs", "runtime_config", "snippet"):
                    self.assertNotIn(private, serialized)
                renamed_again, status = local_bridge.bridge_rename_conversation_payload(
                    created.id,
                    {
                        "expected_revision": renamed.revision,
                        "title": "Renamed again",
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(renamed_again["action"], "rename")
                self.assertEqual(renamed_again["conversation"]["title_source"], "manual")

    def test_history_bridge_rejects_private_or_extra_fields(self):
        safe = {
            "schema_version": 1,
            "conversations": [],
            "count": 0,
            "next_cursor": None,
            "messages": [],
        }
        with patch.object(server, "mentat_conversation_history_payload", return_value=safe):
            payload, status = local_bridge.bridge_conversation_history_payload(state="all")
        self.assertEqual(status, 500)
        self.assertEqual(payload["status"], "error")

        wrong_selection = {
            "schema_version": 1,
            "conversations": [{
                "id": "conv_wrong_history",
                "agent_id": "agent_direct",
                "title": "Different title",
                "title_source": "manual",
                "state": "active",
                "revision": 1,
                "created_at": "2026-08-29T12:00:00Z",
                "updated_at": "2026-08-29T12:00:00Z",
                "archived_at": None,
            }],
            "count": 1,
            "next_cursor": None,
        }
        with patch.object(
            server,
            "mentat_conversation_history_payload",
            return_value=wrong_selection,
        ):
            payload, status = local_bridge.bridge_conversation_history_payload(
                state="archived",
                query="Manual",
            )
        self.assertEqual(status, 500)
        self.assertEqual(payload["status"], "error")

    def test_archive_is_exact_reversible_and_does_not_touch_runs(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = ConversationRepository(root)
            created = repository.create()

            archived = repository.set_archived(
                created.conversation.id,
                expected_revision=created.conversation.revision,
                archived=True,
            )
            self.assertEqual(archived.state, "archived")
            self.assertEqual(archived.revision, created.conversation.revision + 1)
            self.assertIsNotNone(archived.archived_at)

            with self.assertRaisesRegex(Exception, "conversation.changed"):
                repository.set_archived(
                    created.conversation.id,
                    expected_revision=created.conversation.revision,
                    archived=False,
                )

            restored = repository.set_archived(
                created.conversation.id,
                expected_revision=archived.revision,
                archived=False,
            )
            self.assertEqual(restored.state, "active")
            self.assertEqual(restored.revision, archived.revision + 1)
            self.assertIsNone(restored.archived_at)

            with closing(sqlite3.connect(database_path(root))) as connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0],
                    0,
                )

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
            with closing(sqlite3.connect(database_path(root))) as connection:
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
                self.assertEqual(created["queued_turns"], [])
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

                archived, status = local_bridge.bridge_archive_conversation_payload(
                    conversation_id,
                    {"archived": True, "expected_revision": 1},
                )
                self.assertEqual(status, 200)
                self.assertEqual(archived["action"], "archive")
                self.assertEqual(archived["conversation"]["state"], "archived")

                conflict, status = local_bridge.bridge_archive_conversation_payload(
                    conversation_id,
                    {"archived": False, "expected_revision": 1},
                )
                self.assertEqual(status, 409)
                self.assertEqual(conflict["status"], "conflict")

                restored, status = local_bridge.bridge_archive_conversation_payload(
                    conversation_id,
                    {
                        "archived": False,
                        "expected_revision": archived["conversation"]["revision"],
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(restored["action"], "restore")
                self.assertEqual(restored["conversation"]["state"], "active")

                with closing(sqlite3.connect(database_path(root))) as connection:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0],
                        0,
                    )

    def test_codex_readiness_projection_contains_no_account_or_credential_material(self):
        runtime = Mock()
        runtime.command = ("/trusted/codex", "app-server", "--stdio")
        runtime.readiness_status.return_value = "sign_in_required"
        with patch.object(server, "CODEX_RUNTIME", runtime):
            source = server.mentat_codex_readiness_payload()
        self.assertEqual(
            source,
            {
                "schema_version": 1,
                "state": "sign_in_required",
                "setup_command": "codex login",
            },
        )
        with patch.object(server, "mentat_codex_readiness_payload", return_value=source):
            payload, status = local_bridge.bridge_codex_readiness_payload()
        self.assertEqual(status, 200)
        self.assertEqual(payload["state"], "sign_in_required")
        serialized = json.dumps(payload, sort_keys=True)
        for private in ("account", "credential", "access_token", "refresh_token"):
            self.assertNotIn(private, serialized)

    def test_local_bridge_allows_only_the_exact_finalizing_projection(self):
        current = {
            "id": "run_finalizing",
            "status": "finalizing",
            "partial": False,
            "updated_at": "2026-08-27T12:00:00+00:00",
        }
        self.assertEqual(local_bridge._public_current_run(current), current)
        for invalid in ("finalized", "artifact_pending"):
            with self.assertRaisesRegex(
                local_bridge.BridgeConversationProjectionError,
                "conversation_run_invalid",
            ):
                local_bridge._public_current_run({**current, "status": invalid})


if __name__ == "__main__":
    unittest.main()
