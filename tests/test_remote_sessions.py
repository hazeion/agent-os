from __future__ import annotations

import json
from pathlib import Path
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

    def test_remote_message_search_never_reads_local_hermes(self):
        adapter = RemoteHermesConsoleTransport(
            TransportBinding("remote", "Remote workshop", "b" * 32),
            client=FakeSessionClient(),
        )
        with patch.object(server, "hermes_console_transport", return_value=adapter), patch.object(
            server,
            "search_messages",
            side_effect=AssertionError("remote mode must not search local state.db"),
        ):
            payload = server.selected_message_search("release")
        self.assertEqual(payload["results"], [])
        self.assertIn("not available", payload["error"])

    def test_sessions_ui_displays_bounded_remote_unavailable_state(self):
        app_js = (Path(__file__).parents[1] / "public" / "app.js").read_text(encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
