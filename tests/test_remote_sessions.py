from __future__ import annotations

import json
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

from hermes_transport import (
    LocalHermesConsoleTransport,
    RemoteHermesConsoleTransport,
    TransportBinding,
)
import remote_hermes
import server


SECRET = "remote-session-secret-NEVER-RETURN"
ENDPOINT = "https://remote-sessions.example"
UPSTREAM_ID = "session_upstream_123"


def fully_percent_encoded(value):
    return "".join(f"%{byte:02X}" for byte in value.encode("utf-8"))


class FakeResponse:
    def __init__(self, status, payload, *, content_type="application/json"):
        self.status = status
        self.raw = json.dumps(payload).encode("utf-8")
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(self.raw)),
        }

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, amount):
        return self.raw[:amount]


class FakeConnection:
    def __init__(self, response, calls):
        self.response = response
        self.calls = calls

    def request(self, method, path, body=None, headers=None):
        self.calls.append({"method": method, "path": path, "body": body, "headers": dict(headers or {})})

    def getresponse(self):
        return self.response

    def close(self):
        pass


class ResponseQueue:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, _scheme, _host, _port, _timeout):
        return FakeConnection(self.responses.pop(0), self.calls)


def health_payload():
    return {
        "status": "ok",
        "platform": "hermes-agent",
        "version": "0.18.2",
        "readiness": {"status": "ok", "checks": {"config": {"status": "ok"}}},
    }


def capability_payload():
    return {
        "object": "hermes.api_server.capabilities",
        "platform": "hermes-agent",
        "model": "anthropic/claude-test",
        "auth": {"type": "bearer", "required": True},
        "runtime": {"mode": "server_agent", "tool_execution": "server", "split_runtime": False},
        "features": {"session_resources": True},
        "endpoints": {
            "health": {"method": "GET", "path": "/health"},
            "health_detailed": {"method": "GET", "path": "/health/detailed"},
            "sessions": {"method": "GET", "path": "/api/sessions"},
            "session": {"method": "GET", "path": "/api/sessions/{session_id}"},
            "session_messages": {"method": "GET", "path": "/api/sessions/{session_id}/messages"},
        },
    }


def session_record(session_id=UPSTREAM_ID):
    return {
        "id": session_id,
        "title": "Plan the release",
        "model": "anthropic/claude-test",
        "started_at": 1_721_000_000.0,
        "ended_at": 1_721_000_100.0,
        "last_active": 1_721_000_100.0,
        "message_count": 3,
        "tool_call_count": 1,
        "input_tokens": 10,
        "output_tokens": 20,
        "estimated_cost_usd": 0.12,
        "has_system_prompt": True,
        "preview": "Release planning preview",
    }


class FakeSessionClient:
    def __init__(self):
        self.listed = 0
        self.requested = []
        self.message_structural_ids = []

    def require_session_resource_capabilities(self):
        return {"capabilities": ["session_resources"]}

    def list_sessions(self):
        self.listed += 1
        return {"sessions": [{**session_record(), "upstream_id": UPSTREAM_ID}], "truncated": False}

    def get_session(self, session_id):
        self.requested.append(("detail", session_id))
        return {**session_record(), "upstream_id": session_id}

    def get_session_messages(self, session_id, *, structural_ids=()):
        self.requested.append(("messages", session_id))
        self.message_structural_ids.append(tuple(structural_ids))
        return [
            {"role": "user", "content": "Please plan it", "timestamp": 1_721_000_001.0},
            {"role": "assistant", "content": "Plan complete", "timestamp": 1_721_000_099.0},
        ]


class RemoteSessionTests(unittest.TestCase):
    def setUp(self):
        server.REMOTE_SESSION_ALIASES.clear()
        server.REMOTE_SESSION_ALIAS_INDEX.clear()

    def tearDown(self):
        server.REMOTE_SESSION_ALIASES.clear()
        server.REMOTE_SESSION_ALIAS_INDEX.clear()

    def test_exact_capability_and_fixed_authenticated_reads(self):
        queue = ResponseQueue([
            FakeResponse(200, {"status": "ok"}),
            FakeResponse(200, health_payload()),
            FakeResponse(200, capability_payload()),
            FakeResponse(200, {
                "object": "list",
                "data": [session_record()],
                "limit": 12,
                "offset": 0,
                "has_more": False,
            }),
            FakeResponse(200, {"object": "hermes.session", "session": session_record()}),
            FakeResponse(200, {
                "object": "list",
                "session_id": UPSTREAM_ID,
                "data": [
                    {"id": 1, "session_id": UPSTREAM_ID, "role": "user", "content": "Hello", "timestamp": 1.0},
                    {"id": 2, "session_id": UPSTREAM_ID, "role": "tool", "content": SECRET, "tool_calls": ["private"]},
                    {"id": 3, "session_id": UPSTREAM_ID, "role": "assistant", "content": "Hi", "timestamp": 2.0, "reasoning": "private"},
                ],
            }),
        ])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)

        discovery = client.require_session_resource_capabilities()
        listed = client.list_sessions()
        detail = client.get_session(UPSTREAM_ID)
        messages = client.get_session_messages(UPSTREAM_ID)

        self.assertIn("session_resources", discovery["capabilities"])
        self.assertEqual(listed["sessions"][0]["upstream_id"], UPSTREAM_ID)
        self.assertEqual(listed["sessions"][0]["status"], "ended")
        self.assertEqual(listed["sessions"][0]["preview"], "Release planning preview")
        self.assertEqual(detail["title"], "Plan the release")
        self.assertEqual(messages, [
            {"role": "user", "content": "Hello", "timestamp": 1.0},
            {"role": "assistant", "content": "Hi", "timestamp": 2.0},
        ])
        self.assertEqual(
            [call["path"] for call in queue.calls[-3:]],
            [
                "/api/sessions?limit=12&offset=0&include_children=false",
                f"/api/sessions/{UPSTREAM_ID}",
                f"/api/sessions/{UPSTREAM_ID}/messages",
            ],
        )
        self.assertTrue(all(call["headers"]["Authorization"] == f"Bearer {SECRET}" for call in queue.calls[-3:]))

    def test_changed_capabilities_pagination_identity_and_reflection_fail_closed(self):
        mutations = []
        wrong_capabilities = capability_payload()
        wrong_capabilities["endpoints"]["session_messages"]["path"] = "/api/messages/{session_id}"
        mutations.append(([
            FakeResponse(200, {"status": "ok"}),
            FakeResponse(200, health_payload()),
            FakeResponse(200, wrong_capabilities),
        ], "capability"))
        mutations.append(([FakeResponse(200, {
            "object": "list", "data": [session_record()], "limit": 12, "offset": 0, "has_more": "yes",
        })], "pagination"))
        mutations.append(([FakeResponse(200, {
            "object": "hermes.session", "session": session_record("session_other"),
        })], "identity"))
        mutations.append(([FakeResponse(200, {
            "object": "list", "session_id": UPSTREAM_ID,
            "data": [{"role": "assistant", "content": f"Connected to {ENDPOINT}", "timestamp": 2.0}],
        })], "reflection"))

        for responses, operation in mutations:
            with self.subTest(operation=operation):
                client = remote_hermes.RemoteHermesClient(
                    ENDPOINT,
                    SECRET,
                    connection_factory=ResponseQueue(responses),
                )
                with self.assertRaises(remote_hermes.RemoteHermesError):
                    if operation == "capability":
                        client.require_session_resource_capabilities()
                    elif operation == "pagination":
                        client.list_sessions()
                    elif operation == "identity":
                        client.get_session(UPSTREAM_ID)
                    else:
                        client.get_session_messages(UPSTREAM_ID)

    def test_changed_resolved_message_identity_fails_closed(self):
        leaf_id = "session_leaf_456"
        queue = ResponseQueue([
            FakeResponse(200, {
                "object": "list",
                "session_id": leaf_id,
                "data": [{"session_id": leaf_id, "role": "assistant", "content": "Changed branch", "timestamp": 3.0}],
            }),
        ])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_session_binding_changed"):
            client.get_session_messages(UPSTREAM_ID)

    def test_list_accepts_branches_and_blocks_cross_record_identity_reflection(self):
        parent_id = "session_parent_123"
        branch = {**session_record(), "parent_session_id": parent_id}
        valid_queue = ResponseQueue([FakeResponse(200, {
            "object": "list", "data": [branch], "limit": 12, "offset": 0, "has_more": False,
        })])
        valid = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=valid_queue)
        self.assertEqual(valid.list_sessions()["sessions"][0]["parent_session_id"], parent_id)

        second_id = "session_beta_456"
        reflected = {**session_record(), "title": f"Continue {second_id}"}
        reflected_queue = ResponseQueue([FakeResponse(200, {
            "object": "list",
            "data": [reflected, session_record(second_id)],
            "limit": 12,
            "offset": 0,
            "has_more": False,
        })])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=reflected_queue)
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_private_reflection"):
            client.list_sessions()

        parent_reflection = ResponseQueue([FakeResponse(200, {
            "object": "hermes.session",
            "session": {**branch, "title": f"Parent {parent_id}"},
        })])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=parent_reflection)
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_private_reflection"):
            client.get_session(UPSTREAM_ID)

        message_reflection = ResponseQueue([FakeResponse(200, {
            "object": "list",
            "session_id": UPSTREAM_ID,
            "data": [{
                "session_id": UPSTREAM_ID,
                "role": "assistant",
                "content": f"Continue {second_id}",
                "timestamp": 3.0,
            }],
        })])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=message_reflection)
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_private_reflection"):
            client.get_session_messages(UPSTREAM_ID, structural_ids=(second_id, parent_id))

    def test_server_replaces_upstream_ids_and_rejects_stale_aliases(self):
        other_id = "session_other_456"
        client = FakeSessionClient()
        client.list_sessions = Mock(return_value={
            "sessions": [
                {**session_record(), "upstream_id": UPSTREAM_ID},
                {**session_record(other_id), "upstream_id": other_id},
            ],
            "truncated": False,
        })
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", "b" * 32),
            client=client,
        )
        with patch.object(adapter, "revalidate"), patch.object(server, "hermes_console_transport", return_value=adapter):
            listing = server.sessions_payload()
            alias = listing["sessions"][0]["id"]
            detail, detail_status = server.selected_session_detail(alias)
            replay, replay_status = server.selected_session_replay(alias)

        self.assertRegex(alias, r"remote_session_[0-9a-f]{32}")
        self.assertEqual((detail_status, replay_status), (200, 200))
        self.assertEqual(detail["source"], "remote")
        self.assertTrue(detail["plain_text"])
        public = json.dumps({"listing": listing, "detail": detail, "replay": replay})
        for private in (UPSTREAM_ID, other_id, ENDPOINT, SECRET, "has_system_prompt"):
            self.assertNotIn(private, public)
        self.assertNotIn("reasoning", public)
        self.assertEqual(client.requested.count(("detail", UPSTREAM_ID)), 2)
        self.assertEqual(client.requested.count(("messages", UPSTREAM_ID)), 2)
        self.assertTrue(all({UPSTREAM_ID, other_id}.issubset(set(item)) for item in client.message_structural_ids))

        changed_client = FakeSessionClient()
        changed = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Other workshop", "c" * 32),
            client=changed_client,
        )
        with patch.object(changed, "revalidate"), patch.object(server, "hermes_console_transport", return_value=changed):
            payload, status = server.selected_session_detail(alias)
        self.assertEqual(status, 404)
        self.assertEqual(payload["error_code"], "remote_session_alias_invalid")
        self.assertEqual(changed_client.requested, [])

    def test_alias_refresh_prioritizes_complete_current_identity_set(self):
        binding_id = "b" * 32
        old_ids = tuple(f"session_old_{index:02d}" for index in range(36))
        current_ids = tuple(f"session_new_{index:02d}" for index in range(36))
        alias = server._remote_session_alias(
            binding_id,
            UPSTREAM_ID,
            structural_ids=old_ids,
            replace_structural_ids=True,
        )
        refreshed_alias = server._remote_session_alias(
            binding_id,
            UPSTREAM_ID,
            structural_ids=current_ids,
            replace_structural_ids=True,
        )

        self.assertEqual(refreshed_alias, alias)
        _, _, structural_ids = server._remote_session_id_for_alias(binding_id, alias)
        self.assertIn(current_ids[-1], structural_ids)
        self.assertNotIn(old_ids[-1], structural_ids)

        reflected_queue = ResponseQueue([FakeResponse(200, {
            "object": "list",
            "session_id": UPSTREAM_ID,
            "data": [{
                "session_id": UPSTREAM_ID,
                "role": "assistant",
                "content": f"Continue {current_ids[-1]}",
                "timestamp": 3.0,
            }],
        })])
        client = remote_hermes.RemoteHermesClient(
            ENDPOINT,
            SECRET,
            connection_factory=reflected_queue,
        )
        with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_private_reflection"):
            client.get_session_messages(UPSTREAM_ID, structural_ids=structural_ids)

    def test_saturated_alias_fails_before_current_detail_identity_can_be_dropped(self):
        binding_id = "b" * 32
        retained_ids = tuple(f"session_retained_{index:02d}" for index in range(39))
        current_parent_id = "session_current_parent"
        alias = server._remote_session_alias(
            binding_id,
            UPSTREAM_ID,
            structural_ids=retained_ids,
            replace_structural_ids=True,
        )
        client = FakeSessionClient()
        client.get_session = Mock(return_value={
            **session_record(),
            "upstream_id": UPSTREAM_ID,
            "parent_session_id": current_parent_id,
        })
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", binding_id),
            client=client,
        )

        with patch.object(adapter, "revalidate"), patch.object(
            server,
            "hermes_console_transport",
            return_value=adapter,
        ):
            payload, status = server.selected_session_detail(alias)

        self.assertEqual(status, 502)
        self.assertEqual(payload["error_code"], "remote_session_schema_invalid")
        self.assertEqual(client.message_structural_ids, [])

    def test_compressed_projection_is_explicitly_partial(self):
        root_id = "session_compression_root"
        client = FakeSessionClient()
        client.list_sessions = Mock(return_value={
            "sessions": [{
                **session_record(),
                "upstream_id": UPSTREAM_ID,
                "lineage_root_id": root_id,
                "status": "ended",
                "preview": "Latest visible request",
            }],
            "truncated": False,
        })
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", "b" * 32),
            client=client,
        )
        with patch.object(adapter, "revalidate"), patch.object(server, "hermes_console_transport", return_value=adapter):
            listing = server.sessions_payload()
            alias = listing["sessions"][0]["id"]
            detail, status = server.selected_session_detail(alias)
            replay, replay_status = server.selected_session_replay(alias)
        self.assertEqual((status, replay_status), (200, 200))
        self.assertTrue(listing["sessions"][0]["history_partial"])
        self.assertEqual(detail["message_window"]["mode"], "latest_segment")
        self.assertTrue(detail["message_window"]["truncated"])
        self.assertIn("compacted", detail["message_window"]["partial_reason"])
        self.assertIn("Earlier turns were compacted", replay["replay"]["user_intent"]["initial"])
        self.assertNotIn(root_id, json.dumps({"listing": listing, "detail": detail, "replay": replay}))
        self.assertTrue(all(root_id in item for item in client.message_structural_ids))

    def test_local_session_routes_keep_existing_handlers(self):
        local = LocalHermesConsoleTransport(
            TransportBinding("local", "Local Hermes", "local-default"),
            command_path="/fixed/hermes",
            hermes_home=server.HERMES_HOME,
            cwd=server.BASE_DIR,
        )
        with patch.object(server, "hermes_console_transport", return_value=local), patch.object(
            server, "recent_sessions", return_value={"sessions": [{"id": "local"}]}
        ) as recent, patch.object(
            server, "session_detail", return_value=({"session": {"id": "local"}}, 200)
        ) as detail, patch.object(
            server, "session_replay", return_value=({"session_id": "local"}, 200)
        ) as replay:
            self.assertEqual(server.sessions_payload()["sessions"][0]["id"], "local")
            self.assertEqual(server.selected_session_detail("local")[1], 200)
            self.assertEqual(server.selected_session_replay("local")[1], 200)
            with patch.object(
                server,
                "search_messages",
                return_value={"query": "release", "results": [{"session_id": "local"}]},
            ) as search:
                self.assertEqual(
                    server.selected_message_search("release")["results"][0]["session_id"],
                    "local",
                )
            search.assert_called_once_with("release")
        recent.assert_called_once_with(limit=12)
        detail.assert_called_once_with("local", None)
        replay.assert_called_once_with("local", None)

    def test_remote_continuation_remains_rejected_before_submission(self):
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", "b" * 32),
            client=FakeSessionClient(),
        )
        with patch.object(server, "hermes_console_transport", return_value=adapter):
            payload, status = server.start_agent_console_run({
                "agent_id": "default",
                "prompt": "Continue",
                "session_id": "remote_session_" + ("a" * 32),
            })
        self.assertEqual(status, 409)
        self.assertIn("session", payload["error"].lower())

    def test_remote_message_search_uses_public_aliases_and_never_reads_local_hermes(self):
        other_id = "session_other_456"
        root_id = "session_compacted_root"
        client = FakeSessionClient()
        client.list_sessions = Mock(return_value={
            "sessions": [
                {
                    **session_record(),
                    "upstream_id": UPSTREAM_ID,
                    "lineage_root_id": root_id,
                },
                {**session_record(other_id), "upstream_id": other_id, "title": "Second session"},
            ],
            "truncated": True,
        })
        structural_ids_seen = []

        def messages(session_id, *, structural_ids=()):
            structural_ids_seen.append(tuple(structural_ids))
            if session_id == UPSTREAM_ID:
                return [
                    {"role": "user", "content": "Please plan the release", "timestamp": 1.0},
                    {"role": "assistant", "content": "Release plan complete", "timestamp": 2.0},
                ]
            return [{"role": "assistant", "content": "No matching text", "timestamp": 3.0}]

        client.get_session_messages = Mock(side_effect=messages)
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", "b" * 32),
            client=client,
        )
        with patch.object(adapter, "revalidate") as revalidate, patch.object(
            server, "hermes_console_transport", return_value=adapter
        ), patch.object(
            server,
            "search_messages",
            side_effect=AssertionError("remote mode must not search local state.db"),
        ):
            payload = server.selected_message_search("release")

        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["source"], "remote")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["coverage"], {
            "scope": "recent_sessions",
            "session_limit": 12,
            "sessions_scanned": 2,
            "messages_scanned": 3,
            "list_truncated": True,
            "compacted_sessions": 1,
            "result_limit": 20,
            "results_truncated": False,
        })
        self.assertTrue(all(result["source"] == "Remote Hermes" for result in payload["results"]))
        self.assertEqual([result["match_text"].casefold() for result in payload["results"]], ["release", "release"])
        self.assertTrue(all(result["session_id"].startswith("remote_session_") for result in payload["results"]))
        self.assertEqual([result["message_id"] for result in payload["results"]], [1, 2])
        serialized = json.dumps(payload)
        for private in (UPSTREAM_ID, other_id, root_id, SECRET, ENDPOINT):
            self.assertNotIn(private, serialized)
        self.assertTrue(all({UPSTREAM_ID, other_id, root_id}.issubset(set(ids)) for ids in structural_ids_seen))
        self.assertEqual(revalidate.call_count, 2)

    def test_server_remote_search_uses_exact_authenticated_requests(self):
        other_id = "session_other_456"
        queue = ResponseQueue([
            FakeResponse(200, {"status": "ok"}),
            FakeResponse(200, health_payload()),
            FakeResponse(200, capability_payload()),
            FakeResponse(200, {
                "object": "list",
                "data": [session_record(), session_record(other_id)],
                "limit": 12,
                "offset": 0,
                "has_more": False,
            }),
            FakeResponse(200, {
                "object": "list",
                "session_id": UPSTREAM_ID,
                "data": [{
                    "session_id": UPSTREAM_ID,
                    "role": "assistant",
                    "content": "Release checklist ready",
                    "timestamp": 2.0,
                }],
            }),
            FakeResponse(200, {
                "object": "list",
                "session_id": other_id,
                "data": [{
                    "session_id": other_id,
                    "role": "user",
                    "content": "Unrelated work",
                    "timestamp": 3.0,
                }],
            }),
        ])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", "b" * 32),
            client=client,
        )
        with patch.object(adapter, "revalidate"), patch.object(
            server, "hermes_console_transport", return_value=adapter
        ):
            payload = server.selected_message_search("release")

        self.assertEqual(payload["count"], 1)
        self.assertEqual(
            [call["path"] for call in queue.calls[-3:]],
            [
                "/api/sessions?limit=12&offset=0&include_children=false",
                f"/api/sessions/{UPSTREAM_ID}/messages",
                f"/api/sessions/{other_id}/messages",
            ],
        )
        self.assertTrue(all(call["method"] == "GET" for call in queue.calls[-3:]))
        self.assertTrue(all(
            call["headers"]["Authorization"] == f"Bearer {SECRET}"
            for call in queue.calls[-3:]
        ))

    def test_remote_message_endpoint_skips_non_text_and_extracts_text_parts(self):
        queue = ResponseQueue([FakeResponse(200, {
            "object": "list",
            "session_id": UPSTREAM_ID,
            "data": [
                {
                    "session_id": UPSTREAM_ID,
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{"id": "call-1", "function": {"name": "read", "arguments": "{}"}}],
                    "timestamp": 1.0,
                },
                {
                    "session_id": UPSTREAM_ID,
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Release image attached"},
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,private"}},
                    ],
                    "timestamp": 2.0,
                },
                {
                    "session_id": UPSTREAM_ID,
                    "role": "assistant",
                    "content": {"type": "output_text", "text": "Release output ready"},
                    "timestamp": 3.0,
                },
                {
                    "session_id": UPSTREAM_ID,
                    "role": "user",
                    "content": [
                        "Release raw text",
                        {"type": "input_text", "text": "Release input text"},
                    ],
                    "timestamp": 4.0,
                },
            ],
        })])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)

        messages = client.get_session_messages(UPSTREAM_ID)
        self.assertEqual(messages, [
            {
                "role": "user",
                "content": "Release image attached",
                "timestamp": 2.0,
            },
            {
                "role": "assistant",
                "content": "Release output ready",
                "timestamp": 3.0,
            },
            {
                "role": "user",
                "content": "Release raw text\nRelease input text",
                "timestamp": 4.0,
            },
        ])
        self.assertNotIn("image/png", json.dumps(messages))

    def test_remote_message_endpoint_rejects_partial_or_unknown_envelopes(self):
        for extra in ({"has_more": True}, {"next_cursor": "private-cursor"}, {"truncated": True}):
            with self.subTest(extra=extra):
                queue = ResponseQueue([FakeResponse(200, {
                    "object": "list",
                    "session_id": UPSTREAM_ID,
                    "data": [{
                        "session_id": UPSTREAM_ID,
                        "role": "assistant",
                        "content": "Release result",
                        "timestamp": 1.0,
                    }],
                    **extra,
                })])
                client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)
                with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_session_schema_invalid"):
                    client.get_session_messages(UPSTREAM_ID)

    def test_remote_search_rejects_path_and_secret_shaped_public_text_end_to_end(self):
        private_values = (
            ("title", "Release /Users/alice/private/plan.md"),
            ("root_path", "Release output at /etc"),
            ("labeled_path", "Release saved at path:/Users/alice/private/plan.md"),
            ("windows_relative", r"Release saved at .\private\plan.md"),
            ("env_key", "Release used OPENAI_API_KEY=sk-proj-private"),
            ("spaced_key", "Release used API Key: ordinary-private-value"),
            ("credentials_label", "Release credentials: ordinary-private-value"),
            ("access_key", "Release access key: ABCDEFGHIJKL"),
            ("private_key", "Release private key: ordinary-private-value"),
            ("pem_key", "Release -----BEGIN PRIVATE KEY----- MIIEvQIBADANBgkqhkiG9w0BA"),
            ("openssh_key", "Release -----BEGIN OPENSSH PRIVATE KEY----- b3BlbnNzaC1rZXktdjEAAAAA"),
            ("json_token", 'Release payload contains "token":"private-value"'),
            ("localhost_url", "Release http://localhost/private/path"),
            ("loopback_url", "Release https://127.0.0.1/etc/passwd"),
            ("short_loopback_url", "Release http://127.1/private/path"),
            ("short_loopback_url_2", "Release http://127.0.1/etc/passwd"),
            ("octal_loopback_url", "Release http://0177.0.0.1/private/path"),
            ("hex_loopback_url", "Release http://0x7f.0.0.1/private/path"),
            ("metadata_url", "Release http://169.254.169.254/latest/meta-data/"),
            ("multicast_url", "Release http://224.0.0.1/private/path"),
            ("multicast_v6_url", "Release http://[ff02::1]/private/path"),
            ("local_name_url", "Release [docs](http://service.local/private)"),
            ("localdomain_url", "Release http://service.localdomain/private"),
            ("localdomain4_url", "Release http://localhost.localdomain4/private"),
            ("localdomain6_url", "Release http://localhost.localdomain6/private"),
            ("home_arpa_url", "Release https://router.home.arpa/private"),
            ("example_suffix_url", "Release https://service.example/private"),
            ("onion_url", "Release https://hidden.onion/private"),
            ("userinfo_url", "Release https://user:pass@example.com/private"),
            ("hybrid_windows_url", r"Release https://example.com/docs\C:\Users\alice\private.txt"),
            ("wrapped_hybrid_url", r"Release [docs](https://example.com/docs)C:\Users\alice\private.txt"),
            ("adjacent_markdown_path", "Release [docs](https://example.com/docs)[file](/Users/alice/private/plan.md)"),
            ("wrapped_forward_path", "Release [docs](https://example.com/docs)/Users/alice/private.txt"),
            ("wrapped_traversal", "Release [docs](https://example.com/docs)../../private.txt"),
            ("bold_forward_path", "Release **https://example.com/docs**/Users/alice/private.txt"),
            ("nested_local_url", "Release https://example.com/docs/http://localhost/private/path"),
            ("encoded_nested_local_url", "Release https://example.com/http%3A%2F%2Flocalhost%2Fprivate%2Fpath"),
            ("double_encoded_nested_local_url", "Release https://example.com/http%253A%252F%252Flocalhost%252Fprivate"),
            ("encoded_path_parameter", "Release [docs](https://example.com/docs;credentials%3Dordinary-private-value)"),
            ("double_encoded_path_parameter", "Release https://example.com/docs;credentials%253Dordinary-private-value"),
            ("encoded_adjacent_path", "Release [docs](https://example.com/docs)%2FUsers%2Falice%2Fprivate%2Fplan.md"),
            ("double_encoded_path", "Release https://example.com/%252FUsers%252Falice%252Fprivate%252Fplan.md"),
            ("double_encoded_query_path", "Release https://example.com/?next=%252FUsers%252Falice"),
            ("standalone_encoded_path", "Release path=%2FUsers%2Falice%2Fprivate%2Fplan.md"),
            ("standalone_encoded_file_url", "Release file%3A%2F%2F%2Fetc%2Fpasswd"),
            ("standalone_encoded_local_url", "Release http%3A%2F%2Flocalhost%2Fprivate%2Fpath"),
            ("standalone_encoded_token", "Release token%3Dordinary-private-value"),
            ("standalone_encoded_private_key", "Release -----BEGIN%20PRIVATE%20KEY----- MIIEvQIBADAN"),
            ("encoded_actual_key", f"Release {fully_percent_encoded(SECRET)}"),
            ("encoded_actual_session_id", f"Release {fully_percent_encoded(UPSTREAM_ID)}"),
            ("encoded_actual_endpoint", f"Release {fully_percent_encoded(ENDPOINT)}"),
            ("encoded_title_id", fully_percent_encoded(UPSTREAM_ID)),
            ("encoded_preview_endpoint", fully_percent_encoded(ENDPOINT)),
            ("normalized_api_key", "Release API  Key: ordinary-private-value"),
            ("normalized_private_key", "Release private\tkey: ordinary-private-value"),
            ("normalized_private_key_header", "Release -----BEGIN\tPRIVATE KEY----- MIIEvQIBADAN"),
            ("url_normalized_api_key", "Release https://example.com/?API%20%20Key=ordinary-private-value"),
            ("url_normalized_path_key", "Release https://example.com/docs/API%20%20Key%3Aordinary-private-value"),
            ("url_normalized_private_header", "Release https://example.com/?note=-----BEGIN%09PRIVATE%20KEY-----MIIEvQIBADAN"),
            ("fragment_normalized_private_key", "Release https://example.com/#private%20%20key%3Aordinary-private-value"),
            ("fragment_private_path", "Release https://example.com/#path=/Users/alice/private"),
            ("scoped_global_ipv6", "Release [docs](https://[2606:4700:4700::1111%25token=ordinary-private-value]/dns)"),
            ("markdown_api_key", "Release API **Key**: ordinary-private-value"),
            ("markdown_private_header", "Release -----BEGIN **PRIVATE KEY**----- MIIEvQIBADAN"),
            ("markdown_actual_key", "Release remote-session-secret-NEVER-**RETURN**"),
            ("markdown_actual_session_id", "Release session_**upstream**_123"),
            ("markdown_code_key", "Release API `Key`: ordinary-private-value"),
            ("invisible_actual_key", "Release " + SECRET.replace("NEVER", "NEVER\u200b")),
            ("invisible_actual_session_id", "Release " + UPSTREAM_ID.replace("upstream", "upstream\u2060")),
            ("invisible_api_key", "Release API\u200b Key: ordinary-private-value"),
            ("invisible_private_header", "Release -----BEGIN PRIVATE\u200b KEY----- MIIEvQIBADAN"),
            ("invisible_title_id", UPSTREAM_ID.replace("upstream", "upstream\u202e")),
            ("invisible_preview_endpoint", ENDPOINT.replace("sessions", "sessions\u00ad")),
            ("mongolian_invisible_key", "Release " + SECRET.replace("NEVER", "NEVER\u180b")),
            ("hangul_filler_id", "Release " + UPSTREAM_ID.replace("upstream", "upstream\u115f")),
            ("compatibility_filler_label", "Release API\u3164Key: ordinary-private-value"),
            ("halfwidth_filler_header", "Release -----BEGIN PRIVATE\uffa0KEY----- MIIEvQIBADAN"),
            ("url_encoded_invisible_query", "Release https://example.com/?API%E2%80%8BKey=ordinary-private-value"),
            ("url_encoded_invisible_path", "Release https://example.com/docs/private%E2%80%8Bkey%3Aordinary-private-value"),
            ("url_encoded_invisible_fragment", "Release https://example.com/#private%E2%80%8Bkey%3Aordinary-private-value"),
            ("standalone_encoded_invisible_label", "Release API%E2%80%8BKey=ordinary-private-value"),
            ("standalone_encoded_invisible_header", "Release -----BEGIN%20PRIVATE%E2%80%8BKEY----- MIIEvQIBADAN"),
            ("reserved_ignorable_actual_key", "Release " + SECRET.replace("NEVER", "NEVER\ufff0")),
            ("credential_suffix_json", "Release OPENAI_API_KEY_JSON=ordinary-private-value"),
            ("credential_suffix_value", "Release auth_token_value=ordinary-private-value"),
            ("credential_suffix_pem", "Release service_private_key_pem=ordinary-private-value"),
            ("plural_credential_value", "Release credentials_value=ordinary-private-value"),
            ("plural_credential_json", "Release credentials_json=ordinary-private-value"),
            ("overlong_credential_identifier", f"Release token{'x' * 156}=ordinary-private-value"),
            ("camel_openai_api_key", "Release openaiApiKey=ordinary-private-value"),
            ("camel_aws_access_key", "Release awsAccessKeyId=ordinary-private-value"),
            ("camel_private_key", "Release privateKeyPem=ordinary-private-value"),
            ("camel_refresh_token", "Release refreshToken=ordinary-private-value"),
            ("camel_access_token", "Release accessToken=ordinary-private-value"),
            ("camel_client_secret", "Release clientSecret=ordinary-private-value"),
            ("camel_credentials_value", "Release credentialsValue=ordinary-private-value"),
            ("camel_password_hash", "Release passwordHash=ordinary-private-value"),
            ("encoded_camel_token", "Release refresh%54oken=ordinary-private-value"),
            ("url_camel_token", "Release https://example.com/?refreshToken=ordinary-private-value"),
            ("mixed_case_token", "Release toKen=ordinary-private-value"),
            ("mixed_case_api_key", "Release apiKeY=ordinary-private-value"),
            ("uniform_openai_api_key", "Release OPENAIAPIKEY=ordinary-private-value"),
            ("uniform_aws_access_key", "Release AWSACCESSKEYID=ordinary-private-value"),
            ("uniform_refresh_token", "Release refreshtoken=ordinary-private-value"),
            ("uniform_client_secret", "Release CLIENTSECRET=ordinary-private-value"),
            ("uniform_private_key", "Release PRIVATEKEYPEM=ordinary-private-value"),
            ("encoded_uniform_token", "Release REFRESH%54OKEN=ordinary-private-value"),
            ("url_uniform_secret", "Release https://example.com/?CLIENTSECRET=ordinary-private-value"),
            ("uniform_openai_token", "Release OPENAITOKEN=ordinary-private-value"),
            ("uniform_password_hash", "Release PASSWORDHASH=ordinary-private-value"),
            ("uniform_webhook_secret", "Release WEBHOOKSECRET=ordinary-private-value"),
            ("uniform_credentials_value", "Release CREDENTIALSVALUE=ordinary-private-value"),
            ("adversarial_mixed_token", "Release openAiToKenValue=ordinary-private-value"),
            ("encoded_uniform_openai_token", "Release OPENAI%54OKEN=ordinary-private-value"),
            ("url_uniform_openai_token", "Release https://example.com/?OPENAITOKEN=ordinary-private-value"),
            ("versioned_refresh_token", "Release refreshToken2=ordinary-private-value"),
            ("versioned_api_key", "Release apiKeyV2=ordinary-private-value"),
            ("versioned_client_secret", "Release CLIENTSECRETV2=ordinary-private-value"),
            ("encoded_versioned_secret", "Release refresh%54oken2=ordinary-private-value"),
            ("url_versioned_secret", "Release https://example.com/?apiKeyV2=ordinary-private-value"),
            ("cross_label_tokenless", "Release tokenless=ordinary-private-value"),
            ("cross_label_passwordary", "Release passwordary=ordinary-private-value"),
            ("cross_label_secreted", "Release secreted=ordinary-private-value"),
            ("human_api_key_value", "Release API Key Value: ordinary-private-value"),
            ("human_client_secret_value", "Release Client Secret Value: ordinary-private-value"),
            ("human_password_hash", "Release Password Hash: ordinary-private-value"),
            ("human_private_key_pem", "Release Private Key PEM: ordinary-private-value"),
            ("human_credentials_json", "Release Credentials JSON: ordinary-private-value"),
            ("human_authorization_header", "Release Authorization Header: ordinary-private-value"),
            ("encoded_human_key_value", "Release API%20Key%20Value%3Aordinary-private-value"),
            ("url_human_key_value", "Release https://example.com/?API%20Key%20Value=ordinary-private-value"),
            ("human_aws_access_key_id", "Release AWS Access Key ID: ordinary-private-value"),
            ("human_access_token_id", "Release Access Token ID: ordinary-private-value"),
            ("human_credential_id", "Release Credential ID: ordinary-private-value"),
            ("encoded_human_access_id", "Release Access%20Token%20ID%3Aordinary-private-value"),
            ("url_human_access_id", "Release https://example.com/?Access%20Token%20ID=ordinary-private-value"),
            ("dotted_api_key", "Release api.key=ordinary-private-value"),
            ("dotted_openai_api_key", "Release openai.api.key=ordinary-private-value"),
            ("dotted_access_key_id", "Release access.key.id=ordinary-private-value"),
            ("dotted_client_secret_value", "Release client.secret.value=ordinary-private-value"),
            ("dotted_refresh_token_value", "Release refresh.token.value=ordinary-private-value"),
            ("encoded_dotted_api_key", "Release api%2Ekey%3Dordinary-private-value"),
            ("url_dotted_access_key_id", "Release https://example.com/?access.key.id=ordinary-private-value"),
            ("bracket_api_key", 'Release config["apiKey"] = ordinary-private-value'),
            ("bracket_access_token", "Release config['accessToken'] = ordinary-private-value"),
            ("bracket_authorization", 'Release headers["Authorization"]: ordinary-private-value'),
            ("encoded_bracket_api_key", "Release config%5B%22apiKey%22%5D%3Dordinary-private-value"),
            ("url_bracket_access_token", "Release https://example.com/?config%5B%27accessToken%27%5D=ordinary-private-value"),
            ("nested_client_secret_value", "Release client.secret.current.value=ordinary-private-value"),
            ("nested_refresh_token_value", "Release refresh.token.production.value=ordinary-private-value"),
            ("nested_credentials_value", "Release credentials.production.value=ordinary-private-value"),
            ("nested_password_hash", "Release password.user.hash=ordinary-private-value"),
            ("nested_authorization_header", "Release authorization.request.header=ordinary-private-value"),
            ("bracket_nested_secret", 'Release config["client.secret.current.value"]=ordinary-private-value'),
            ("encoded_nested_secret", "Release client%2Esecret%2Ecurrent%2Evalue%3Dordinary-private-value"),
            ("url_nested_secret", "Release https://example.com/?refresh.token.production.value=ordinary-private-value"),
            ("unquoted_bracket_key", "Release config[apiKey]=ordinary-private-value"),
            ("malformed_bracket_key", 'Release config["apiKey]=ordinary-private-value'),
            ("encoded_unquoted_bracket_key", "Release config%5BapiKey%5D%3Dordinary-private-value"),
            ("url_unquoted_bracket_key", "Release https://example.com/?config%5BapiKey%5D=ordinary-private-value"),
            ("overlong_bracket_key", f'Release config["apiKey{"x" * 155}"]=ordinary-private-value'),
            ("chained_bracket_secret", 'Release config["client"]["secret"]["current"]["value"]=ordinary-private-value'),
            ("mixed_bracket_secret", 'Release config.client["secret"][current][value]=ordinary-private-value'),
            ("encoded_chained_bracket_secret", "Release config%5B%22access%22%5D%5B%22token%22%5D%5B%22value%22%5D%3Dordinary-private-value"),
            ("url_chained_bracket_secret", "Release https://example.com/?config%5B%22password%22%5D%5Buser%5D%5Bhash%5D=ordinary-private-value"),
            ("credential_shaped_hostport", "Release openai.api.key:443"),
            ("credential_descriptor_hostport", "Release client.secret.value:1234"),
            ("private_internal_hostport", "Release service.internal:443"),
            ("private_home_arpa_hostport", "Release router.home.arpa:443"),
            ("private_onion_hostport", "Release hidden.onion:80"),
            ("loopback_ipv4_hostport", "Release 127.0.0.1:8000"),
            ("private_ipv4_hostport", "Release 10.0.0.1:443"),
            ("link_local_ipv4_hostport", "Release 169.254.169.254:80"),
            ("mixed_terminal_api_key_value", 'Release config["apiKey"].value=ordinary-private-value'),
            ("mixed_terminal_unquoted_value", "Release config[apiKey].current.value=ordinary-private-value"),
            ("mixed_terminal_client_secret", 'Release config["client"]["secret"].current.value=ordinary-private-value'),
            ("mixed_terminal_refresh_token", 'Release settings["refresh"]["token"].production.value=ordinary-private-value'),
            ("encoded_mixed_terminal_secret", "Release config%5B%22apiKey%22%5D%2Evalue%3Dordinary-private-value"),
            ("url_mixed_terminal_secret", "Release https://example.com/?config%5BapiKey%5D.current.value=ordinary-private-value"),
            ("quoted_space_credential_key", 'Release labels["api key"] = ordinary-private-value'),
            ("generic_credential_type", "Release mapping[apiKey, str] = ordinary-private-value"),
            ("nested_generic_credential", "Release mapping[str, list[apiKey]] = ordinary-private-value"),
            ("overdepth_generic", "Release list[list[list[list[str]]]] = ordinary-private-value"),
            ("malformed_mixed_bracket", 'Release config["apiKey].current.value=ordinary-private-value'),
            ("overlong_mixed_bracket", f'Release config["apiKey{"x" * 155}"].current.value=ordinary-private-value'),
            ("encoded_malformed_mixed", "Release config%5B%22apiKey%5D%2Ecurrent%2Evalue%3Dordinary-private-value"),
            ("url_malformed_mixed", "Release https://example.com/?config%5B%22apiKey%5D.current.value=ordinary-private-value"),
            ("over_window_mixed", 'Release config["apiKey"]' + (".segment" * 70) + ".value=ordinary-private-value"),
            ("bracketed_colon_api_key", "Release [apiKey: ordinary-private-value]"),
            ("quoted_bracketed_colon_token", 'Release ["accessToken": ordinary-private-value]'),
            ("encoded_bracketed_colon_secret", "Release %5BclientSecret%3Aordinary-private-value%5D"),
            ("url_bracketed_colon_secret", "Release https://example.com/?data=%5BpasswordHash%3Aordinary-private-value%5D"),
            ("spaced_dot_bracket_secret", 'Release config["client"] . secret . current . value=ordinary-private-value'),
            ("encoded_spaced_dot_secret", "Release config%5B%22apiKey%22%5D%20%2E%20value%3Dordinary-private-value"),
            ("url_spaced_dot_secret", "Release https://example.com/?config%5BapiKey%5D%20.%20current.value=ordinary-private-value"),
            ("bracketed_human_api_key", 'Release ["API Key": ordinary-private-value]'),
            ("bracketed_human_private_key", 'Release ["Private Key PEM": ordinary-private-value]'),
            ("bracketed_human_access_id", 'Release ["Access Key ID": ordinary-private-value]'),
            ("bracketed_human_password_hash", 'Release ["Password Hash": ordinary-private-value]'),
            ("bracketed_human_authorization_header", 'Release ["Authorization Header": ordinary-private-value]'),
            ("bracketed_human_credentials_json", 'Release ["Credentials JSON": ordinary-private-value]'),
            ("encoded_bracketed_human_key", "Release %5B%22API%20Key%22%3Aordinary-private-value%5D"),
            ("url_bracketed_human_key", "Release https://example.com/?data=%5B%22Password%20Hash%22%3Aordinary-private-value%5D"),
            ("quoted_comma_api_key", 'Release ["API, Key": ordinary-private-value]'),
            ("encoded_quoted_comma_key", "Release %5B%22Access%2C%20Key%20ID%22%3Aordinary-private-value%5D"),
            ("url_quoted_comma_key", "Release https://example.com/?data=%5B%22Password%2C%20Hash%22%3Aordinary-private-value%5D"),
            ("over_window_spaced_mixed", 'Release config["apiKey"]' + (" . segment" * 70) + " . value=ordinary-private-value"),
            ("compact_division_path_ambiguity", "Release average=total/count"),
            ("compact_index_division_path_ambiguity", "Release items[index/2] = ready"),
            ("compact_floor_division_path_ambiguity", "Release mid=(low+high)//2"),
            ("human_api_key_environment", "Release API Key Production=ordinary-private-value"),
            ("human_client_secret_environment", "Release Client Secret Current=ordinary-private-value"),
            ("human_refresh_token_environment", "Release Refresh Token Production=ordinary-private-value"),
            ("quoted_human_key_environment", 'Release config["API Key Production"]=ordinary-private-value'),
            ("encoded_human_compound_environment", "Release Client%20Secret%20Current%3Dordinary-private-value"),
            ("url_human_compound_environment", "Release https://example.com/?Refresh%20Token%20Production=ordinary-private-value"),
            ("quoted_punctuation_credential", 'Release labels["api,key"] = ordinary-private-value'),
            ("human_password_environment", "Release Password Production=ordinary-private-value"),
            ("quoted_password_environment", 'Release config["Password Production"]=ordinary-private-value'),
            ("long_human_api_key_scope", "Release API Key Team Production Primary Current=ordinary-private-value"),
            ("quoted_long_human_api_key_scope", 'Release config["API Key Team Production Primary Current"]=ordinary-private-value'),
            ("metadata_then_environment_scope", "Release API Key Scope Production=ordinary-private-value"),
            ("parenthesized_api_scope", "Release API Key (Production)=ordinary-private-value"),
            ("quoted_fullwidth_api_key", 'Release config["ＡＰＩ Ｋｅｙ"]=ordinary-private-value'),
            ("hyphenated_human_api_scope", "Release API-Key Production=ordinary-private-value"),
            ("underscored_human_api_scope", "Release API_Key Production=ordinary-private-value"),
            ("dotted_human_api_scope", "Release API.Key Production=ordinary-private-value"),
            ("comma_human_api_scope", "Release API,Key Production=ordinary-private-value"),
            ("pipe_human_api_scope", "Release API|Key Production=ordinary-private-value"),
            ("plus_human_api_scope", "Release API+Key Production=ordinary-private-value"),
            ("middle_dot_human_api_scope", "Release API·Key Production=ordinary-private-value"),
            ("slash_human_api_scope", "Release API/Key Production=ordinary-private-value"),
            ("colon_human_api_scope", "Release API:Key Production=ordinary-private-value"),
            ("em_dash_human_api_scope", "Release API—Key Production=ordinary-private-value"),
            ("bang_private_key_scope", "Release Private!Key Production=ordinary-private-value"),
            ("colon_aws_key_scope", "Release AWS:Access:Key Production=ordinary-private-value"),
            ("unicode_prefixed_pipe_api_scope", "Release 服务API|Key Production=ordinary-private-value"),
            ("greek_prefixed_plus_api_scope", "Release πAPI+Key Production=ordinary-private-value"),
            ("encoded_unicode_prefixed_pipe_api_scope", "Release %E6%9C%8D%E5%8A%A1API%7CKey%20Production%3Dordinary-private-value"),
            ("query_unicode_prefixed_pipe_api_scope", "Release https://example.com/?label=%E6%9C%8D%E5%8A%A1API%7CKey%20Production%3Dordinary-private-value"),
            ("uppercase_openai_token_scope", "Release OPENAITOKEN Production=ordinary-private-value"),
            ("uppercase_webhook_secret_scope", "Release WEBHOOKSECRET Production=ordinary-private-value"),
            ("uppercase_user_password_scope", "Release USERPASSWORD Current=ordinary-private-value"),
            ("ascii_prefixed_pipe_api_scope", "Release OpenAIAPI|Key Production=ordinary-private-value"),
            ("ascii_prefixed_access_key_scope", "Release ServiceAccess|Key Production=ordinary-private-value"),
            ("ascii_prefixed_private_key_scope", "Release VendorPrivate—Key Production=ordinary-private-value"),
            ("pretoken_scope", "Release PreToken Production=ordinary-private-value"),
            ("uppercase_pretoken_scope", "Release PRETOKEN Production=ordinary-private-value"),
            ("prepassword_scope", "Release PrePassword Current=ordinary-private-value"),
            ("preauthorization_scope", "Release PreAuthorization Production=ordinary-private-value"),
            ("encoded_pretoken_scope", "Release PreToken%20Production%3Dordinary-private-value"),
            ("query_pretoken_scope", "Release https://example.com/?label=PreToken%20Production%3Dordinary-private-value"),
            ("nonterminal_parenthesized_scope", "Release API Key (Production) Current=ordinary-private-value"),
            ("hyphenated_password_scope", "Release Password-Production=ordinary-private-value"),
            ("underscored_password_scope", "Release Password_Production=ordinary-private-value"),
            ("later_punctuated_compound", "Release API Key Format: JWT; Client-Secret Production=ordinary-private-value"),
            ("credentials_metadata_json_assignment", "Release Credentials Status JSON=ordinary-private-value"),
            ("api_key_metadata_json_assignment", "Release API Key Status JSON=ordinary-private-value"),
            ("compact_api_key_spaced_scope", "Release apiKey Production=ordinary-private-value"),
            ("compact_client_secret_spaced_scope", "Release clientSecret Production=ordinary-private-value"),
            ("punctuated_secret_scope", "Release Secret-Production=ordinary-private-value"),
            ("punctuated_token_scope", "Release Token-Production=ordinary-private-value"),
            ("later_parenthesized_compound", "Release API Key docs; Private Key (Production) Current=ordinary-private-value"),
            ("spaced_secret_scope", "Release Secret Production=ordinary-private-value"),
            ("spaced_token_scope", "Release Token Production=ordinary-private-value"),
            ("parenthesized_secret_scope", "Release Secret (Production) Current=ordinary-private-value"),
            ("compact_api_parenthesized_scope", "Release apiKey (Production) Current=ordinary-private-value"),
            ("compact_client_parenthesized_scope", "Release clientSecret (Production) Current=ordinary-private-value"),
            ("prefixed_openai_api_key_scope", "Release OpenAIApiKey Production=ordinary-private-value"),
            ("prefixed_my_api_key_scope", "Release MyApiKey Production=ordinary-private-value"),
            ("prefixed_access_token_scope", "Release ServiceAccessToken Production=ordinary-private-value"),
            ("prefixed_client_secret_scope", "Release GitHubClientSecret Production=ordinary-private-value"),
            ("prefixed_api_parenthesized_scope", "Release openaiApiKey (Production) Current=ordinary-private-value"),
            ("parenthesized_comma_scope", "Release API Key (Production, Primary)=ordinary-private-value"),
            ("parenthesized_semicolon_scope", "Release Private Key (Production; Primary)=ordinary-private-value"),
            ("parenthesized_client_scope", "Release Client Secret (Production, Primary)=ordinary-private-value"),
            ("compact_parenthesized_comma_scope", "Release apiKey (Production, Primary) Current=ordinary-private-value"),
            ("overlong_human_lhs", "Release API Key " + ("scope" * 35) + " Production=ordinary-private-value"),
            ("nested_parenthesized_scope", "Release API Key (Production, (Primary))=ordinary-private-value"),
            ("nested_private_key_scope", "Release Private Key ((Production), Primary)=ordinary-private-value"),
            ("nested_client_scope", "Release Client Secret (Production (Primary), Blue)=ordinary-private-value"),
            ("nested_compact_scope", "Release apiKey (Production, (Primary)) Current=ordinary-private-value"),
            ("unclosed_parenthesized_scope", "Release API Key (Production, Primary=ordinary-private-value"),
            ("unicode_prefixed_api_key", "Release 服务ApiKey Production=ordinary-private-value"),
            ("greek_prefixed_api_key", "Release πApiKey Production=ordinary-private-value"),
            ("unicode_prefixed_client_secret", "Release ΩClientSecret Production=ordinary-private-value"),
            ("unicode_prefixed_parenthesized", "Release 服务ApiKey (Production) Current=ordinary-private-value"),
            ("unicode_prefixed_overlong", "Release 服务ApiKey " + ("scope" * 35) + " Production=ordinary-private-value"),
            ("encoded_unicode_prefixed_key", "Release %E6%9C%8D%E5%8A%A1ApiKey%20Production%3Dordinary-private-value"),
            ("url_unicode_prefixed_key", "Release https://example.com/?%E6%9C%8D%E5%8A%A1ApiKey%20Production=ordinary-private-value"),
            ("prefixed_openai_token", "Release OpenAIToken Production=ordinary-private-value"),
            ("prefixed_webhook_secret", "Release WebhookSecret (Production) Current=ordinary-private-value"),
            ("prefixed_user_password", "Release UserPassword Production=ordinary-private-value"),
            ("unicode_prefixed_token", "Release 服务Token Production=ordinary-private-value"),
            ("encoded_prefixed_secret", "Release WebhookSecret%20Production%3Dordinary-private-value"),
            ("url_prefixed_password", "Release https://example.com/?UserPassword%20Production=ordinary-private-value"),
            ("overlength_topic_later_scope", "Release API Key format is documented " + ("x " * 110) + " Production=ordinary-private-value"),
            ("overlength_password_later_scope", "Release Password requirements were documented " + ("x " * 110) + " Current=ordinary-private-value"),
            ("overlength_token_later_scope", "Release Token format is documented " + ("x " * 110) + " Production=ordinary-private-value"),
            ("overlength_api_colon_scope", "Release API Key format is documented " + ("x " * 110) + " Production: ordinary-private-value"),
            ("overlength_password_colon_scope", "Release Password requirements were documented " + ("x " * 110) + " Current: ordinary-private-value"),
            ("overlength_token_colon_scope", "Release Token format is documented " + ("x " * 110) + " Production: ordinary-private-value"),
            ("overlength_topic_option_assignment", "Release API Key format is documented " + ("documentation " * 18) + " option=ordinary-private-value"),
            ("earlier_sensitive_later_safe_topic", "Release API Key Production " + ("x " * 90) + " Token format is documented " + ("documentation " * 18) + " status=ordinary-private-value"),
            ("earlier_password_later_safe_topic", "Release Password Current " + ("x " * 90) + " API Key status is documented " + ("documentation " * 18) + " count=ordinary-private-value"),
            ("overlength_cjk_colon_scope", "Release API Key format is documented " + ("生产环境" * 45) + ": ordinary-private-value"),
            ("overlength_japanese_scope", "Release Password requirements are documented " + ("本番環境" * 45) + "=ordinary-private-value"),
            ("overlength_greek_scope", "Release Token format is documented " + ("παραγωγή" * 30) + ": ordinary-private-value"),
            ("overlength_short_cjk_scope", "Release API Key format is documented " + ("documentation " * 18) + "生产环境=ordinary-private-value"),
            ("overlength_short_japanese_scope", "Release Password requirements are documented " + ("documentation " * 18) + "本番環境=ordinary-private-value"),
            ("overlength_short_greek_scope", "Release Token format is documented " + ("documentation " * 18) + "παραγωγή: ordinary-private-value"),
            ("overlength_short_localized_value", "Release API Key format is documented " + ("documentation " * 18) + "值=ordinary-private-value"),
            ("overlength_key_symbol_scope", "Release API Key format is documented " + ("documentation " * 18) + "status 🔑=ordinary-private-value"),
            ("overlength_lock_symbol_scope", "Release API Key format is documented " + ("documentation " * 18) + "status 🔐: ordinary-private-value"),
            ("pipe_forward_path", "Release https://example.com/docs|/Users/alice/private"),
            ("pipe_drive_path", "Release https://example.com/docs|C:/Users/alice/private"),
            ("path_query", "Release https://example.com/?path=/Users/alice/private"),
            ("encoded_path_query", "Release https://example.com/?path=%2FUsers%2Falice%2Fprivate"),
            ("model", "sk-proj-private-model-value"),
        )
        for field, private_text in private_values:
            with self.subTest(field=field):
                record = session_record()
                if field in {"title", "encoded_title_id", "invisible_title_id"}:
                    record["title"] = private_text
                    message = "Release checklist ready"
                elif field in {"encoded_preview_endpoint", "invisible_preview_endpoint"}:
                    record["preview"] = private_text
                    message = "Release checklist ready"
                elif field == "model":
                    record["model"] = private_text
                    message = "Release checklist ready"
                else:
                    message = private_text
                queue = ResponseQueue([
                    FakeResponse(200, {"status": "ok"}),
                    FakeResponse(200, health_payload()),
                    FakeResponse(200, capability_payload()),
                    FakeResponse(200, {
                        "object": "list",
                        "data": [record],
                        "limit": 12,
                        "offset": 0,
                        "has_more": False,
                    }),
                    FakeResponse(200, {
                        "object": "list",
                        "session_id": UPSTREAM_ID,
                        "data": [{
                            "session_id": UPSTREAM_ID,
                            "role": "assistant",
                            "content": message,
                            "timestamp": 2.0,
                        }],
                    }),
                ])
                client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)
                adapter = RemoteHermesConsoleTransport(
                    TransportBinding("remote", "Remote workshop", "b" * 32),
                    client=client,
                )
                with patch.object(adapter, "revalidate"), patch.object(
                    server, "hermes_console_transport", return_value=adapter
                ):
                    payload = server.selected_message_search("release")

                self.assertEqual(payload["results"], [])
                self.assertEqual(payload["count"], 0)
                self.assertIn("error", payload)
                serialized = json.dumps(payload)
                self.assertNotIn(private_text, serialized)

    def test_remote_search_preserves_safe_slash_prose_and_public_web_urls(self):
        safe_text = (
            "Release A/B decision on 7/20 is 1/2 complete; see https://example.com, "
            "[docs](https://example.com/docs), `https://example.com/guide`, and "
            "**https://example.com/release**; calendar https://example.com/calendar?date=7/20, "
            "fraction https://example.com/progress?value=1/2, https://example.com/?q=A%2FB, "
            "punctuation https://example.com/a(b)/c, https://example.com/a,b/c, "
            "wrapped [paren](https://example.com/a(b)/c), "
            "[IPv4](https://8.8.8.8/a(b)/c), "
            "[IPv6](https://[2606:4700:4700::1111]/a(b)/c), "
            "https://example.com/a;b/c, encoded https://example.com/files/a%2Fb/details, "
            "apostrophe https://example.com/people/o'reilly/books, asterisk "
            "https://example.com/a*b/c, [encoded](https://example.com/files/a%2Fb), "
            "percent https://example.com/100%25, https://example.com/?value=100%25, "
            "https://example.com/#progress%25, delimiters https://example.com/a%23b/c, "
            "https://example.com/a%3Fb/c, fragments https://example.com/#date=7/20, "
            "https://example.com/#progress=1/2, https://example.com/#choice=A/B, "
            "encoded prose https%3A%2F%2Fexample.com%2Fdocs, "
            "double https%253A%252F%252Fexample.com%252Fdocs, "
            "IPv4 http%3A%2F%2F8.8.8.8%2Fdocs, "
            "IPv6 https%3A%2F%2F%5B2606%3A4700%3A4700%3A%3A1111%5D%2Fdns, "
            "emoji 👩‍💻, "
            "ordinary prose: The password requirements are documented: twelve characters minimum. "
            "Release notes explain the token format: documentation follows. "
            "This secret sauce is delicious: serve warm. "
            "Metadata token_format: JWT, password_requirements: twelve characters, "
            "access_key_rotation_days=90, authorization_method: PKCE, credential_count=0, "
            "and https://example.com/docs?topic=token-format:overview. "
            "Plural metadata credentials_count=0, credentials_status=missing, "
            "credentials_source=environment, credentials_rotation_days=90, "
            "and https://example.com/?credentials_count=0. "
            "Lexical metadata tokenizer_name=gpt2, tokenization_method=BPE, "
            "passwordless_enabled=true, secretary_name=Alice, credentialed_status=true, "
            "and https://example.com/?tokenizer_name=gpt2. "
            "Camel metadata tokenFormat=JWT, passwordRequirements=twelve, "
            "accessKeyRotationDays=90, authorizationMethod=PKCE, credentialCount=0, "
            "tokenizerName=gpt2, passwordlessEnabled=true, secretaryName=Alice, "
            "credentialedStatus=true, and https://example.com/?tokenizerName=gpt2. "
            "Versioned metadata tokenFormatV2=JWT, passwordRequirementsV2=twelve, "
            "credentialCount64=0, and https://example.com/?tokenFormatV2=JWT. "
            "Extended metadata passwordMinLength=12, tokenExpiresAt=2026-07-20T00:00:00Z, "
            "apiKeyConfigured=false, refreshTokenSupported=true, "
            "token_endpoint_auth_methods_supported=client_secret_basic, "
            "and https://example.com/?passwordMinLength=12. "
            "Neighbor continuations tokenizerModelName=gpt2, secretaryEmail=alice@example.com, "
            "passwordlessLoginEnabled=true, credentialedUserCount=4, "
            "and https://example.com/?tokenizerModelName=gpt2. "
            "Human metadata API Key Format: JWT, Password Requirements: twelve characters, "
            "Credentials Count: zero, and Authorization Method: PKCE. "
            "Descriptor prose Secret Sauce Value: savory, Token Count Value: 12, "
            "and Password Policy Value: strong. "
            "Dotted metadata token.format=JWT, password.requirements=twelve, "
            "token.cache.enabled=true, password.reset.enabled=true, "
            "credentials.provider.name=default, service.token.example.com:443, "
            "8.8.8.8:443, [2606:4700:4700::1111]:443, "
            'items[0] = ready, items[index] = ready, items[i] = ready, '
            'list[str] = values, mapping[user_id] = value, items[-1] = ready, '
            'items[1:4] = ready, matrix[i][j] = ready, '
            'items[index].status = ready, labels["display name"] = Alice, '
            'dict[str, int] = values, '
            'items: dict[str, list[int]] = values, list[dict[str, int]] = values, '
            'Mapping[str, Sequence[int]] = source, '
            'items: dict[str, list[int | None]] = values, items[index + 1] = ready, '
            'labels["owner\'s name"] = Alice, labels["owner\\\"s name"] = Alice, '
            'items[index / 2] = ready, items[index // 2] = ready, '
            'average = total / count, '
            '["API Key Format": JWT, "Password Requirements": twelve], '
            '["API, Key Format": JWT, "Password, Requirements": twelve], '
            'API Key Scope: project, Client Secret Status: missing, '
            'labels["display,name"] = ready, labels["owner@example.com"] = ready, '
            'labels["x[y]"] = ready, labels["feature(flag)"] = ready, '
            'API Key docs. option=enabled, Client Secret guide; retries=3, '
            'Refresh Token docs, status=ready, '
            'labels["café"] = ready, labels["状态"] = ready, '
            '配置["状态"] = ready, 設定["状態"] = ready, '
            'Access Token docs? option=enabled, Client Secret guide! retries=3, '
            'Authorization guide — option=enabled, API Key docs (see guide) option=enabled, '
            'len(token) == 0, parse(password) == expected, '
            'Password requirements should be documented: soon, '
            'Password requirements will be documented: soon, '
            'Token format can be JSON: yes, API Key status will be shown: soon, '
            'API. Key concepts option=enabled, API, key concepts option=enabled, '
            'Client. Secret guide retries=3, '
            'secretion rate is normal: yes, secretive design status: ready, '
            'secretariat status: ready, tokenism is discouraged: yes, '
            'tokenomics status: stable, '
            'These signs betoken success: yes, The change may betoken progress: yes, '
            'Nonsecret data status: ready, An unsecret ballot status: valid, '
            'THESE SIGNS BETOKEN SUCCESS: YES, NONSECRET DATA STATUS: READY, '
            'AN UNSECRET BALLOT STATUS: VALID, PRETOKEN STAGE STATUS: READY, '
            'NonSecret data status: ready, UnSecret ballot status: valid, '
            'PreToken stage status: ready, BeToken success status: true, '
            f'Capital planning {"x" * 220} option=enabled, '
            f'Accessibility guidance {"x" * 220} option=enabled, '
            f'The secretary prepared {"x" * 220} option=enabled, '
            f'Tokenizer documentation {"x" * 220} option=enabled, '
            f'Token format is documented {"documentation " * 18} status=enabled, '
            '服务Token format is documented status=enabled, '
            f'服务Token format is documented {"documentation " * 18} status=enabled, '
            'ΩSecret status is documented status=enabled, '
            f'利用者Password requirements are documented {"documentation " * 18} status=enabled, '
            f'Password requirements are documented {"documentation " * 18} method=enabled, '
            f'API Key status will be shown {"documentation " * 18} count=enabled, '
            f'token {"x " * 110} == expected, '
            f'token {"x " * 110} <= expected, token {"x " * 110} >= expected, '
            f'token {"x " * 110} != expected, '
            f'Password requirements were documented {"documentation " * 18} enabled=ready, '
            'config["tokenFormat"] = JWT, config["token"]["format"] = JWT, '
            'config.token["format"] = JWT, '
            "and https://example.com/?token.format=JWT. "
            "separate lines https://example.com/one\nhttps://example.com/two, "
            "separate tabs https://example.com/three\thttps://example.com/four, "
            "and https://[2606:4700:4700::1111]/dns"
        )
        record = session_record()
        record["title"] = "Release A/B decision 7/20"
        record["preview"] = "See https://example.com"
        queue = ResponseQueue([
            FakeResponse(200, {"status": "ok"}),
            FakeResponse(200, health_payload()),
            FakeResponse(200, capability_payload()),
            FakeResponse(200, {
                "object": "list",
                "data": [record],
                "limit": 12,
                "offset": 0,
                "has_more": False,
            }),
            FakeResponse(200, {
                "object": "list",
                "session_id": UPSTREAM_ID,
                "data": [{
                    "session_id": UPSTREAM_ID,
                    "role": "assistant",
                    "content": safe_text,
                    "timestamp": 2.0,
                }],
            }),
        ])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", "b" * 32),
            client=client,
        )
        with patch.object(adapter, "revalidate"), patch.object(
            server, "hermes_console_transport", return_value=adapter
        ):
            payload = server.selected_message_search("release")

        self.assertEqual(payload["count"], 1)
        self.assertIn("A/B", payload["results"][0]["snippet"])
        self.assertIn("https://example.com", payload["results"][0]["snippet"])
        self.assertIn("[docs](https://example.com/docs)", payload["results"][0]["snippet"])

    def test_public_url_validation_caps_spans_and_handles_the_limit_linearly(self):
        allowed = "".join(
            "[x](https://example.com/a)"
            for _ in range(remote_hermes.MAX_PUBLIC_URL_SPANS)
        )
        rejected = allowed + "[x](https://example.com/a)"

        self.assertFalse(remote_hermes._contains_private_public_text(allowed))
        self.assertTrue(remote_hermes._contains_private_public_text(rejected))

    def test_public_url_query_field_count_is_bounded(self):
        allowed_query = "&".join(
            f"option_{index}=enabled"
            for index in range(remote_hermes.MAX_PUBLIC_URL_QUERY_FIELDS)
        )
        rejected_query = f"{allowed_query}&extra=enabled"
        self.assertFalse(remote_hermes._contains_private_public_text(
            f"Release https://example.com/?{allowed_query}"
        ))
        self.assertTrue(remote_hermes._contains_private_public_text(
            f"Release https://example.com/?{rejected_query}"
        ))

        oversized_query = "&".join(
            f"field_{index}=%2525252525252525"
            for index in range(2_500)
        )
        started = time.perf_counter()
        self.assertTrue(remote_hermes._contains_private_public_text(
            f"Release https://example.com/?{oversized_query}"
        ))
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_public_text_validation_is_bounded_for_maximum_slash_free_text(self):
        safe_then_sensitive = (
            ("x" * 140)
            + " Secret sauce=ok\n"
            + ("y" * 140)
            + " Secret admin=ordinary-private-value"
        )
        self.assertTrue(remote_hermes._contains_private_public_text(safe_then_sensitive))

        for value in (
            "x" * remote_hermes.SESSION_CONTENT_LIMIT,
            ("token" * remote_hermes.SESSION_CONTENT_LIMIT)[:remote_hermes.SESSION_CONTENT_LIMIT],
        ):
            with self.subTest(prefix=value[:8]):
                started = time.perf_counter()
                self.assertFalse(remote_hermes._contains_private_public_text(value))
                self.assertLess(time.perf_counter() - started, 1.0)

        delimiter_dense = ":" * remote_hermes.SESSION_CONTENT_LIMIT
        started = time.perf_counter()
        self.assertFalse(remote_hermes._contains_private_public_text(delimiter_dense))
        self.assertLess(time.perf_counter() - started, 1.0)

        for delimiter_value in (
            ("a:" * (remote_hermes.SESSION_CONTENT_LIMIT // 2)),
            ("a=" * (remote_hermes.SESSION_CONTENT_LIMIT // 2)),
            ("api:" * (remote_hermes.SESSION_CONTENT_LIMIT // 4)),
            ("api=" * (remote_hermes.SESSION_CONTENT_LIMIT // 4)),
        ):
            started = time.perf_counter()
            self.assertFalse(remote_hermes._contains_private_public_text(delimiter_value))
            self.assertLess(time.perf_counter() - started, 1.0)

        normalization_expansion = "\ufdfa" * remote_hermes.SESSION_CONTENT_LIMIT
        started = time.perf_counter()
        self.assertTrue(remote_hermes._contains_private_public_text(normalization_expansion))
        # Windows Python 3.11 normalizes this pathological maximum-size input
        # more slowly; keep a bounded cross-platform budget without flaking.
        self.assertLess(time.perf_counter() - started, 2.0)

        varied_stem_dense = " ".join(f"api:{index:05d}" for index in range(10_000))
        started = time.perf_counter()
        self.assertFalse(remote_hermes._contains_private_public_text(varied_stem_dense))
        self.assertLess(time.perf_counter() - started, 1.0)

        varied_alpha_stems = " ".join(
            f"api:{chr(97 + (index // 26) % 26)}{chr(97 + index % 26)}"
            for index in range(14_000)
        )
        started = time.perf_counter()
        self.assertFalse(remote_hermes._contains_private_public_text(varied_alpha_stems))
        self.assertLess(time.perf_counter() - started, 1.0)

        punctuation = ("!", "?", ";", ", ")
        varied_punctuation_stems = "".join(
            f"api:{chr(97 + (index // 26) % 26)}{chr(97 + index % 26)}"
            f"{punctuation[index % len(punctuation)]}"
            for index in range(10_000)
        )
        started = time.perf_counter()
        self.assertFalse(remote_hermes._contains_private_public_text(
            varied_punctuation_stems
        ))
        self.assertLess(time.perf_counter() - started, 1.0)

        varied_api_words = "".join(
            f"api{chr(97 + (index // 26) % 26)}{chr(97 + index % 26)}:ok;"
            for index in range(10_000)
        )
        started = time.perf_counter()
        self.assertFalse(remote_hermes._contains_private_public_text(varied_api_words))
        self.assertLess(time.perf_counter() - started, 1.0)

        dotted_host_like = ("segment." * 12_499) + "com:443"
        started = time.perf_counter()
        self.assertTrue(remote_hermes._contains_private_public_text(dotted_host_like))
        self.assertLess(time.perf_counter() - started, 1.0)

        benign_config = "\n".join(f"option_{index}=enabled" for index in range(600))
        self.assertFalse(remote_hermes._contains_private_public_text(benign_config))
        self.assertFalse(remote_hermes._contains_private_public_text(f"{'x' * 160}=enabled"))
        self.assertTrue(remote_hermes._contains_private_public_text(f"{'x' * 161}=enabled"))
        exact_bracket_key = "option" + ("x" * 154)
        overlong_bracket_key = exact_bracket_key + "x"
        self.assertFalse(remote_hermes._contains_private_public_text(
            f'config["{exact_bracket_key}"]=enabled'
        ))
        self.assertTrue(remote_hermes._contains_private_public_text(
            f'config["{overlong_bracket_key}"]=enabled'
        ))
        self.assertTrue(remote_hermes._contains_private_public_text(
            'config["apiKey]=ordinary-private-value'
        ))

    def test_remote_search_keeps_context_for_matches_inside_long_public_urls(self):
        content = "Release https://example.com/" + ("segment/" * 60) + "needle"
        record = session_record()
        queue = ResponseQueue([
            FakeResponse(200, {"status": "ok"}),
            FakeResponse(200, health_payload()),
            FakeResponse(200, capability_payload()),
            FakeResponse(200, {
                "object": "list",
                "data": [record],
                "limit": 12,
                "offset": 0,
                "has_more": False,
            }),
            FakeResponse(200, {
                "object": "list",
                "session_id": UPSTREAM_ID,
                "data": [{
                    "session_id": UPSTREAM_ID,
                    "role": "assistant",
                    "content": content,
                    "timestamp": 2.0,
                }],
            }),
        ])
        client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", "b" * 32),
            client=client,
        )
        with patch.object(adapter, "revalidate"), patch.object(
            server, "hermes_console_transport", return_value=adapter
        ):
            payload = server.selected_message_search("needle")

        self.assertEqual(payload["count"], 1)
        self.assertNotIn("error", payload)

    def test_remote_session_list_rejects_unknown_partial_envelope_fields(self):
        for extra in ({"truncated": True}, {"next_cursor": "more"}):
            with self.subTest(extra=extra):
                queue = ResponseQueue([FakeResponse(200, {
                    "object": "list",
                    "data": [session_record()],
                    "limit": 12,
                    "offset": 0,
                    "has_more": False,
                    **extra,
                })])
                client = remote_hermes.RemoteHermesClient(ENDPOINT, SECRET, connection_factory=queue)
                with self.assertRaisesRegex(remote_hermes.RemoteHermesError, "remote_session_schema_invalid"):
                    client.list_sessions()

    def test_remote_message_search_truncates_matches_and_reports_partial_history(self):
        root_id = "session_compacted_root"
        client = FakeSessionClient()
        client.list_sessions = Mock(return_value={
            "sessions": [{
                **session_record(),
                "upstream_id": UPSTREAM_ID,
                "lineage_root_id": root_id,
            }],
            "truncated": False,
        })
        client.get_session_messages = Mock(return_value=[
            {"role": "assistant", "content": f"Release match {index}", "timestamp": float(index)}
            for index in range(21)
        ])
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", "b" * 32),
            client=client,
        )
        with patch.object(adapter, "revalidate"), patch.object(
            server, "hermes_console_transport", return_value=adapter
        ):
            payload = server.selected_message_search("release")

        self.assertEqual(payload["count"], 20)
        self.assertEqual(payload["coverage"]["messages_scanned"], 21)
        self.assertEqual(payload["coverage"]["compacted_sessions"], 1)
        self.assertTrue(payload["coverage"]["results_truncated"])

    def test_remote_message_search_fails_closed_on_partial_read_or_binding_change(self):
        other_id = "session_other_456"
        for failure in ("partial_read", "binding_change"):
            with self.subTest(failure=failure):
                client = FakeSessionClient()
                client.list_sessions = Mock(return_value={
                    "sessions": [
                        {**session_record(), "upstream_id": UPSTREAM_ID},
                        {**session_record(other_id), "upstream_id": other_id},
                    ],
                    "truncated": False,
                })
                if failure == "partial_read":
                    client.get_session_messages = Mock(side_effect=[
                        [{"role": "assistant", "content": "release result", "timestamp": 1.0}],
                        remote_hermes.RemoteHermesError("remote_session_schema_invalid"),
                    ])
                    revalidate_effect = None
                else:
                    client.get_session_messages = Mock(return_value=[
                        {"role": "assistant", "content": "release result", "timestamp": 1.0},
                    ])
                    revalidate_effect = [None, server.HermesTransportError("transport_binding_changed")]
                adapter = RemoteHermesConsoleTransport(
                    TransportBinding("remote", "Remote workshop", "b" * 32),
                    client=client,
                )
                with patch.object(adapter, "revalidate", side_effect=revalidate_effect), patch.object(
                    server, "hermes_console_transport", return_value=adapter
                ):
                    payload = server.selected_message_search("release")

                self.assertEqual(payload["results"], [])
                self.assertEqual(payload["count"], 0)
                self.assertIn("error", payload)
                self.assertNotIn("release result", json.dumps(payload))

    def test_short_message_search_does_not_open_a_transport(self):
        for query, normalized in ((" r ", "r"), ("🔥", "🔥")):
            with self.subTest(query=query), patch.object(
                server,
                "hermes_console_transport",
                side_effect=AssertionError("short query must not inspect Hermes"),
            ):
                self.assertEqual(
                    server.selected_message_search(query),
                    {"query": normalized, "results": [], "count": 0},
                )

    def test_message_excerpt_centers_unicode_and_punctuation_literal_matches(self):
        for query in ("发布", "🔥🔥", "?!"):
            with self.subTest(query=query):
                content = ("Earlier context without the match. " * 20) + f"Found {query} here"
                excerpt = server.message_excerpt(content, query)
                self.assertIn(query, excerpt)
                self.assertTrue(excerpt.startswith("…"))
        self.assertEqual(server.message_match_text("The Straße release", "STRASSE"), "Straße")
        self.assertEqual(server.message_match_text("The ß release", "ss"), "ß")
        self.assertEqual(server.message_match_text("A foo\nbar release", "foo bar"), "foo\nbar")

    def test_sessions_ui_displays_bounded_remote_unavailable_state(self):
        app_js = (Path(__file__).parents[1] / "public" / "app.js").read_text(encoding="utf-8")
        index_html = (Path(__file__).parents[1] / "public" / "index.html").read_text(encoding="utf-8")
        render_start = app_js.index("function renderSessions(payload = {})")
        render_end = app_js.index("function renderMessageSearchResults", render_start)
        renderer = app_js[render_start:render_end]
        self.assertIn("if (payload.error)", renderer)
        self.assertIn("escapeHtml(payload.error)", renderer)
        self.assertIn("select.disabled = true", renderer)
        self.assertIn("selectedStillAvailable", renderer)
        self.assertIn("state.sessionDetailRequestGeneration += 1", renderer)
        loader_start = app_js.index("async function loadSessionDetail")
        loader_end = app_js.index("function agentCreatorForm", loader_start)
        loader = app_js[loader_start:loader_end]
        self.assertIn("requestGeneration !== state.sessionDetailRequestGeneration", loader)
        self.assertIn("state.selectedSessionId !== sessionId", loader)
        self.assertIn("latest_segment", app_js)
        search_start = app_js.index("function renderMessageSearchResults")
        search_end = app_js.index("function renderHermesCapabilityInventory", search_start)
        search_renderer = app_js[search_start:search_end]
        self.assertIn("Remote coverage:", search_renderer)
        self.assertIn("older sessions may not be included", search_renderer)
        self.assertIn("'transcript may' : 'transcripts may'", search_renderer)
        self.assertIn("omit earlier turns", search_renderer)
        self.assertIn("results_truncated", search_renderer)
        self.assertIn("escapeHtml(coverageParts.join", search_renderer)
        self.assertIn("messageSearchRequestGeneration", app_js)
        self.assertIn("request.generation !== state.messageSearchRequestGeneration", app_js)
        self.assertIn("async function runMessageSearchRequest(request)", app_js)
        self.assertIn("if (state.messageSearchInFlight)", app_js)
        self.assertIn("state.messageSearchPending = request", app_js)
        self.assertIn("const pendingRequest = state.messageSearchPending", app_js)
        core_js = (Path(__file__).parents[1] / "public" / "core.js").read_text(encoding="utf-8")
        self.assertIn("messageSearchInFlight: false", core_js)
        self.assertIn("messageSearchPending: null", core_js)
        self.assertIn("text.matchAll", core_js)
        self.assertIn("Array.from(String(value)).length", core_js)
        self.assertIn("result.match_text || term", search_renderer)
        self.assertIn("results.length === 1 ? 'message match'", search_renderer)
        self.assertIn('data-match-text="${escapeHtml(result.match_text', search_renderer)
        self.assertIn("result.dataset.matchText || result.dataset.query", app_js)
        self.assertIn("Remote search stays read-only", index_html)


if __name__ == "__main__":
    unittest.main()
