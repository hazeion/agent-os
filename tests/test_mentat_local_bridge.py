from __future__ import annotations

import hashlib
from contextlib import closing
from http.client import HTTPConnection
import inspect
import json
from pathlib import Path
import socket
import sqlite3
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent_registry import AgentRegistryError, AgentRegistryUnavailableError
from mentat_db import connect as connect_mentat_database, database_path as mentat_database_path
import mentat_db
from run_repository import RunRepository, RunRepositoryConflict, RunRepositoryError, RunRepositoryUnavailable
from task_repository import TaskRepositoryError
from mentat import local_bridge
import server
from vercel_connections import VercelConnectionError, VercelConnectionUnavailable


TOKEN = "bridge-token-that-is-long-enough-for-256-bits-of-entropy"
BRIDGE_REQUEST_TIMEOUT_SECONDS = 30


def trusted_vercel_message_event_id(run_id: str) -> str:
    source_event_id = "vercel_message_" + hashlib.sha256(
        (run_id + ":message").encode("utf-8")
    ).hexdigest()[:24]
    return "event_" + hashlib.sha256(
        (run_id + ":" + source_event_id).encode("utf-8")
    ).hexdigest()[:24]


class LocalBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = local_bridge.build_bridge_server("127.0.0.1", 0, TOKEN)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def test_bridge_startup_remains_read_only_for_task_authority(self):
        source = Path(local_bridge.__file__).read_text(encoding="utf-8")

        self.assertNotIn("ensure_task_authority", source)
        self.assertNotIn("prepare_task_authority", source)

    def test_bridge_binding_uses_the_validated_literal_without_reverse_dns(self):
        with patch.object(
            local_bridge.socket,
            "getfqdn",
            side_effect=AssertionError("reverse DNS must not run"),
        ):
            bridge = local_bridge.build_bridge_server("127.0.0.1", 0, TOKEN)
        try:
            self.assertEqual(bridge.server_name, "127.0.0.1")
            self.assertGreater(int(bridge.server_port), 0)
            self.assertTrue(
                issubclass(
                    local_bridge.IPv6ConfiguredBridgeHTTPServer,
                    local_bridge._LoopbackBridgeHTTPServer,
                )
            )
        finally:
            bridge.server_close()

    def request(
        self,
        method: str = "GET",
        path: str = local_bridge.BRIDGE_HEALTH_PATH,
        *,
        token: str | None = TOKEN,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> tuple[int, dict, dict[str, str]]:
        connection = HTTPConnection(
            "127.0.0.1",
            self.port,
            timeout=BRIDGE_REQUEST_TIMEOUT_SECONDS,
        )
        request_headers = {"Host": f"127.0.0.1:{self.port}"}
        if token is not None:
            request_headers[local_bridge.BRIDGE_TOKEN_HEADER] = token
        request_headers.update(headers or {})
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            body = response.read()
            response_headers = {name: value for name, value in response.getheaders()}
            return response.status, json.loads(body), response_headers
        finally:
            connection.close()

    def test_health_requires_one_exact_token_and_returns_a_fixed_projection(self):
        status, payload, headers = self.request()

        self.assertEqual(status, 200)
        self.assertEqual(
            payload,
            {
                "mentat_version": local_bridge.DISPLAY_VERSION,
                "runtime": "python",
                "schema_version": 1,
                "service": "mentat-local-bridge",
                "status": "ready",
            },
        )
        self.assertEqual(headers["Cache-Control"], "private, no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertNotIn(TOKEN, json.dumps(payload))

        for supplied in (None, "wrong-token-that-is-still-long-enough-to-compare"):
            with self.subTest(token=supplied):
                rejected_status, rejected, _headers = self.request(token=supplied)
                self.assertEqual(rejected_status, 403)
                self.assertEqual(rejected, {"error": "bridge_request_forbidden"})

    def test_browser_and_forged_host_requests_fail_closed(self):
        rejected_headers = (
            {"Origin": f"http://127.0.0.1:{self.port}"},
            {"Sec-Fetch-Site": "same-origin"},
            {"Cookie": "session=not-accepted"},
            {"Host": "attacker.example"},
            {"Host": f"127.0.0.1:{self.port + 1}"},
        )
        for headers in rejected_headers:
            with self.subTest(headers=headers):
                status, payload, _response_headers = self.request(headers=headers)
                self.assertEqual(status, 403)
                self.assertEqual(payload, {"error": "bridge_request_forbidden"})

        status, payload, _response_headers = self.request(
            headers={"Sec-Fetch-Mode": "cors"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")

    def test_agents_is_a_fixed_private_projection(self):
        canonical = {
            "schema_version": 1,
            "count": 1,
            "agents": [{
                "id": "agent_researcher",
                "name": "Researcher",
                "runtime_type": "hermes",
                "runtime_config_id": "runtime_config_researcher",
                "capabilities": ["browser-use", "research.web"],
            }],
        }
        with patch.object(local_bridge, "bridge_agents_payload", return_value=(
            local_bridge._ready_agents_payload(canonical), 200,
        )):
            status, payload, _headers = self.request(path=local_bridge.BRIDGE_AGENTS_PATH)

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["agents"], canonical["agents"])
        self.assertNotIn("runtime_agent_ref", json.dumps(payload))
        self.assertNotIn("agents.json", json.dumps(payload))

    def test_agents_rejects_private_or_malformed_canonical_data(self):
        malformed = (
            {"schema_version": 1, "count": 1, "agents": [{"id": "agent_a"}]},
            {"schema_version": 1, "count": 1, "agents": [{
                "id": "agent_a",
                "name": "Agent",
                "runtime_type": "hermes",
                "runtime_config_id": "runtime_a",
                "capabilities": [],
                "runtime_agent_ref": "private-canary",
            }]},
            {"schema_version": 1, "count": 1, "agents": [{
                "id": "agent_a",
                "name": "Agent",
                "runtime_type": "hermes",
                "runtime_config_id": "runtime_a",
                "capabilities": ["z", "a"],
            }]},
        )
        for candidate in malformed:
            with self.subTest(candidate=candidate):
                with self.assertRaises(local_bridge.BridgeAgentProjectionError):
                    local_bridge._ready_agents_payload(candidate)

    def test_agents_capability_reads_only_the_canonical_projection_and_maps_failures(self):
        canonical = {
            "schema_version": 1,
            "count": 1,
            "agents": [{
                "id": "agent_researcher",
                "name": "Researcher",
                "runtime_type": "hermes",
                "runtime_config_id": "runtime_config_researcher",
                "capabilities": ["research.web"],
            }],
        }
        cases = (
            (canonical, "ready", 200),
            (AgentRegistryUnavailableError("agent_registry.unavailable"), "unavailable", 503),
            (AgentRegistryError("agent_registry.unsupported"), "unsupported", 501),
            (ValueError("private database detail"), "error", 500),
        )
        for outcome, expected_status, expected_code in cases:
            with self.subTest(expected_status=expected_status):
                with patch.object(server, "mentat_agents_payload", side_effect=(
                    outcome if isinstance(outcome, Exception) else None
                ), return_value=(None if isinstance(outcome, Exception) else outcome)):
                    payload, status = local_bridge.bridge_agents_payload()
                self.assertEqual(status, expected_code)
                self.assertEqual(payload["status"], expected_status)
                self.assertNotIn("private", json.dumps(payload))

    def test_agents_projects_unavailable_unsupported_and_internal_failures_without_details(self):
        expected = (("unavailable", 503), ("unsupported", 501), ("error", 500))
        for state, response_status in expected:
            with self.subTest(state=state):
                with patch.object(local_bridge, "bridge_agents_payload", return_value=({
                    "schema_version": 1,
                    "service": "mentat-local-bridge",
                    "runtime": "python",
                    "status": state,
                }, response_status)):
                    status, payload, _headers = self.request(path=local_bridge.BRIDGE_AGENTS_PATH)
                self.assertEqual(status, response_status)
                self.assertEqual(payload["status"], state)
                self.assertNotIn("private", json.dumps(payload))

    @patch("codex_runtime.codex_binding_is_valid", return_value=True)
    @patch("codex_runtime.find_codex_command", return_value="/usr/bin/codex")
    def test_conversation_routes_create_read_and_list_without_creating_a_run(
        self, _find_codex_command, _codex_binding_is_valid
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(server, "DATA_DIR", root):
                status, payload, _headers = self.request(
                    path=local_bridge.BRIDGE_CONVERSATIONS_PATH,
                )
                self.assertEqual(status, 200)
                self.assertEqual(payload["status"], "ready")
                self.assertEqual(payload["conversations"], [])
                self.assertEqual(payload["direct_agent_id"], "agent_direct")

                status, created, _headers = self.request(
                    method="POST",
                    path=local_bridge.BRIDGE_CONVERSATIONS_PATH,
                    headers={"Content-Type": "application/json"},
                    body=b"{}",
                )
                self.assertEqual(status, 201)
                self.assertEqual(created["messages"], [])
                self.assertIsNone(created["current_run"])
                self.assertEqual(created["queued_turns"], [])
                conversation_id = created["conversation"]["id"]
                self.assertNotIn("runtime_agent_ref", json.dumps(created))
                self.assertNotIn("runtime_config_id", json.dumps(created))

                status, detail, _headers = self.request(
                    path=f"{local_bridge.BRIDGE_CONVERSATIONS_PATH}/{conversation_id}?before=1",
                )
                self.assertEqual(status, 200)
                self.assertEqual(detail["conversation"]["id"], conversation_id)
                self.assertEqual(detail["agent"]["id"], "agent_direct")

                status, activity, _headers = self.request(
                    path=local_bridge.BRIDGE_AGENT_ACTIVITY_PATH,
                )
                self.assertEqual(status, 200)
                self.assertEqual(activity["status"], "ready")
                self.assertEqual(activity["direct_agent_id"], "agent_direct")

                status, listed, _headers = self.request(
                    path=f"{local_bridge.BRIDGE_CONVERSATIONS_PATH}/{conversation_id}?after=1",
                )
                self.assertEqual(status, 404)
                self.assertEqual(listed, {"error": "bridge_route_not_found"})

                with closing(sqlite3.connect(mentat_database_path(root))) as connection:
                    self.assertEqual(
                        connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0],
                        0,
                    )

    def test_conversation_list_preserves_valid_cursor(self):
        canonical = {
            "schema_version": 1,
            "conversations": [],
            "agents": [],
            "direct_agent_id": None,
            "count": 0,
            "next_cursor": "cursor_133",
        }
        with patch.object(server, "mentat_conversations_payload", return_value=canonical):
            status, payload, _headers = self.request(
                path=local_bridge.BRIDGE_CONVERSATIONS_PATH,
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["next_cursor"], "cursor_133")

    def test_conversation_turn_route_is_fixed_authenticated_and_body_bounded(self):
        response = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "duplicate": False,
            "disposition": "accepted",
            "conversation": {},
            "message": {},
            "turn": {},
            "run": {},
        }
        body = b'{"idempotency_key":"conversation-route-key","text":"Start work"}'
        with patch.object(
            local_bridge,
            "bridge_submit_conversation_turn_payload",
            return_value=(response, 202),
        ) as capability:
            status, payload, _headers = self.request(
                method="POST",
                path="/bridge/v1/conversations/conv_current/turns",
                headers={"Content-Type": "application/json"},
                body=body,
            )
        self.assertEqual((status, payload), (202, response))
        capability.assert_called_once_with(
            "conv_current",
            {"idempotency_key": "conversation-route-key", "text": "Start work"},
        )

        for path, invalid_body in (
            (
                "/bridge/v1/conversations/conv_current/turns?retry=1",
                body,
            ),
            (
                "/bridge/v1/conversations/conv_current/turns",
                b'{"text":"Start work"}',
            ),
            (
                "/bridge/v1/conversations/bad%2Fid/turns",
                body,
            ),
        ):
            with self.subTest(path=path):
                status, payload, _headers = self.request(
                    method="POST",
                    path=path,
                    headers={"Content-Type": "application/json"},
                    body=invalid_body,
                )
                self.assertEqual((status, payload), (404, {"error": "bridge_route_not_found"}))

    def test_conversation_queue_steer_and_selected_refresh_routes_are_exact(self):
        queue_response = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "disposition": "edited",
        }
        with patch.object(
            local_bridge,
            "bridge_mutate_conversation_turn_payload",
            return_value=(queue_response, 200),
        ) as mutate:
            for action, body in (
                (
                    "edit",
                    b'{"expected_message_revision":2,"expected_revision":3,"text":"Edited"}',
                ),
                (
                    "cancel",
                    b'{"expected_message_revision":2,"expected_revision":3}',
                ),
                (
                    "continue",
                    b'{"expected_message_revision":2,"expected_revision":3}',
                ),
            ):
                status, payload, _headers = self.request(
                    method="POST",
                    path=(
                        "/bridge/v1/conversations/conv_current/turns/"
                        f"turn_current/{action}"
                    ),
                    headers={"Content-Type": "application/json"},
                    body=body,
                )
                self.assertEqual((status, payload), (200, queue_response))
        self.assertEqual(
            [call.args[:3] for call in mutate.call_args_list],
            [
                ("conv_current", "turn_current", "edit"),
                ("conv_current", "turn_current", "cancel"),
                ("conv_current", "turn_current", "continue"),
            ],
        )
        self.assertEqual(
            mutate.call_args_list[0].args[3],
            {
                "expected_message_revision": 2,
                "expected_revision": 3,
                "text": "Edited",
            },
        )

        steer_response = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "action": "steer",
            "conversation_id": "conv_current",
            "run_id": "run_current",
            "disposition": "accepted",
        }
        with patch.object(
            local_bridge,
            "bridge_steer_conversation_payload",
            return_value=(steer_response, 200),
        ) as steer:
            status, payload, _headers = self.request(
                method="POST",
                path="/bridge/v1/conversations/conv_current/steer",
                headers={"Content-Type": "application/json"},
                body=b'{"run_id":"run_current","text":"Use this guidance"}',
            )
        self.assertEqual((status, payload), (200, steer_response))
        steer.assert_called_once_with(
            "conv_current",
            {"run_id": "run_current", "text": "Use this guidance"},
        )

        archive_response = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "action": "archive",
        }
        with patch.object(
            local_bridge,
            "bridge_archive_conversation_payload",
            return_value=(archive_response, 200),
        ) as archive:
            status, payload, _headers = self.request(
                method="POST",
                path="/bridge/v1/conversations/conv_current/archive",
                headers={"Content-Type": "application/json"},
                body=b'{"expected_revision":4}',
            )
        self.assertEqual((status, payload), (200, archive_response))
        archive.assert_called_once_with(
            "conv_current",
            {"archived": True, "expected_revision": 4},
        )

        attempt_response = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "action": "retry",
        }
        attempt_body = {
            "idempotency_key": "conversation-attempt-key",
            "source_run_id": "run_current",
        }
        for action, capability_name in (
            ("retry", "bridge_retry_conversation_run_payload"),
            ("resume", "bridge_resume_conversation_run_payload"),
        ):
            response = {**attempt_response, "action": action}
            with patch.object(
                local_bridge,
                capability_name,
                return_value=(response, 202),
            ) as capability:
                status, payload, _headers = self.request(
                    method="POST",
                    path=f"/bridge/v1/conversations/conv_current/{action}",
                    headers={"Content-Type": "application/json"},
                    body=json.dumps(attempt_body).encode("utf-8"),
                )
            self.assertEqual((status, payload), (202, response))
            capability.assert_called_once_with("conv_current", attempt_body)

        refresh_response = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "run_id": "run_current",
            "disposition": "reconciled",
        }
        with patch.object(
            local_bridge,
            "bridge_refresh_run_payload",
            return_value=(refresh_response, 200),
        ) as refresh:
            status, payload, _headers = self.request(
                method="POST",
                path="/bridge/v1/runs/run_current/refresh",
                headers={"Content-Type": "application/json"},
                body=b"{}",
            )
        self.assertEqual((status, payload), (200, refresh_response))
        refresh.assert_called_once_with("run_current")

        for path, body in (
            (
                "/bridge/v1/conversations/conv_current/turns/turn_current/edit",
                b'{"expected_message_revision":2,"expected_revision":3}',
            ),
            (
                "/bridge/v1/conversations/conv_current/steer?retry=1",
                b'{"run_id":"run_current","text":"No"}',
            ),
            ("/bridge/v1/runs/run_current/refresh", b'{"extra":true}'),
        ):
            status, payload, _headers = self.request(
                method="POST",
                path=path,
                headers={"Content-Type": "application/json"},
                body=body,
            )
            self.assertEqual((status, payload), (404, {"error": "bridge_route_not_found"}))

    def test_conversation_private_projections_reject_cross_target_successes(self):
        wrong_submission = {
            "conversation": {"id": "conv_other"},
            "message": {
                "content": {"parts": [{"text": "Exact text"}]},
            },
            "turn": {"id": "turn_other"},
        }
        with (
            patch.object(
                server,
                "submit_mentat_conversation_turn",
                return_value=({}, 202),
            ),
            patch.object(
                local_bridge,
                "_ready_conversation_turn_submission",
                return_value=wrong_submission,
            ),
        ):
            payload, status = local_bridge.bridge_submit_conversation_turn_payload(
                "conv_current",
                {"idempotency_key": "cross-target-key-1", "text": "Exact text"},
            )
        self.assertEqual(status, 500)
        self.assertEqual(payload["status"], "error")

        wrong_mutation = {
            "conversation": {"id": "conv_current"},
            "message": {
                "content": {"parts": [{"text": "Edited text"}]},
            },
            "turn": {"id": "turn_other"},
        }
        with (
            patch.object(
                server,
                "mutate_mentat_conversation_turn",
                return_value=({}, 200),
            ),
            patch.object(
                local_bridge,
                "_ready_conversation_queue_mutation",
                return_value=wrong_mutation,
            ),
        ):
            payload, status = local_bridge.bridge_mutate_conversation_turn_payload(
                "conv_current",
                "turn_current",
                "edit",
                {
                    "expected_message_revision": 2,
                    "expected_revision": 3,
                    "text": "Edited text",
                },
            )
        self.assertEqual(status, 500)
        self.assertEqual(payload["status"], "error")

        with patch.object(
            server,
            "steer_mentat_conversation",
            return_value=(
                {
                    "schema_version": 1,
                    "action": "steer",
                    "conversation_id": "conv_current",
                    "run_id": "run_other",
                    "disposition": "accepted",
                },
                200,
            ),
        ):
            payload, status = local_bridge.bridge_steer_conversation_payload(
                "conv_current",
                {"run_id": "run_current", "text": "Stay exact"},
            )
        self.assertEqual(status, 500)
        self.assertEqual(payload["status"], "error")

    def test_conversation_steer_unavailability_remains_retryable(self):
        with patch.object(
            server,
            "steer_mentat_conversation",
            side_effect=server.OrchestrationRunActionError(
                "conversation.steer_unavailable"
            ),
        ):
            payload, status = local_bridge.bridge_steer_conversation_payload(
                "conv_current",
                {"run_id": "run_current", "text": "Stay exact"},
            )
        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "unavailable")

        with patch.object(
            server,
            "steer_mentat_conversation",
            side_effect=server.OrchestrationRunActionError(
                "conversation.steer_unsupported"
            ),
        ):
            payload, status = local_bridge.bridge_steer_conversation_payload(
                "conv_current",
                {"run_id": "run_current", "text": "Stay exact"},
            )
        self.assertEqual(status, 501)
        self.assertEqual(payload["status"], "unsupported")

    def test_conversation_turn_route_accepts_worst_case_json_escaped_text(self):
        response = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "duplicate": False,
            "disposition": "accepted",
            "conversation": {},
            "message": {},
            "turn": {},
            "run": {},
        }
        text = "\x01" * 6_000
        body = json.dumps(
            {
                "idempotency_key": "conversation-control-character-key",
                "text": text,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        self.assertGreater(len(body), local_bridge.MAXIMUM_BRIDGE_MESSAGE_BODY_BYTES)
        self.assertLessEqual(
            len(body),
            local_bridge.MAXIMUM_BRIDGE_CONVERSATION_TURN_BODY_BYTES,
        )
        with patch.object(
            local_bridge,
            "bridge_submit_conversation_turn_payload",
            return_value=(response, 202),
        ) as capability:
            status, payload, _headers = self.request(
                method="POST",
                path="/bridge/v1/conversations/conv_current/turns",
                headers={"Content-Type": "application/json"},
                body=body,
            )
        self.assertEqual((status, payload), (202, response))
        capability.assert_called_once_with(
            "conv_current",
            {
                "idempotency_key": "conversation-control-character-key",
                "text": text,
            },
        )

    def test_conversation_turn_rejects_transfer_encoding_and_short_bodies(self):
        body = b'{"idempotency_key":"conversation-route-key","text":"Start work"}'
        base_headers = (
            "POST /bridge/v1/conversations/conv_current/turns HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            f"{local_bridge.BRIDGE_TOKEN_HEADER}: {TOKEN}\r\n"
            "Content-Type: application/json\r\n"
        ).encode("ascii")
        requests = (
            base_headers
            + b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
            + f"{len(body):x}\r\n".encode("ascii")
            + body
            + b"\r\n0\r\n\r\n",
            base_headers
            + f"Content-Length: {len(body) + 5}\r\nConnection: close\r\n\r\n".encode("ascii")
            + body,
        )
        with patch.object(
            local_bridge,
            "bridge_submit_conversation_turn_payload",
        ) as capability:
            for index, request in enumerate(requests):
                with self.subTest(index=index), socket.create_connection(
                    ("127.0.0.1", self.port), timeout=2
                ) as client:
                    client.sendall(request)
                    if index == 1:
                        client.shutdown(socket.SHUT_WR)
                    response = b""
                    while True:
                        chunk = client.recv(4096)
                        if not chunk:
                            break
                        response += chunk
                    self.assertIn(b" 404 ", response.split(b"\r\n", 1)[0])

        capability.assert_not_called()

    def test_conversation_turn_body_read_has_a_total_deadline(self):
        body = b'{"idempotency_key":"conversation-route-key","text":"Start work"}'
        headers = (
            "POST /bridge/v1/conversations/conv_current/turns HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            f"{local_bridge.BRIDGE_TOKEN_HEADER}: {TOKEN}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii")
        with patch.object(
            local_bridge,
            "BRIDGE_BODY_READ_TIMEOUT_SECONDS",
            0.1,
        ), patch.object(
            local_bridge,
            "bridge_submit_conversation_turn_payload",
        ) as capability, socket.create_connection(
            ("127.0.0.1", self.port), timeout=2
        ) as client:
            started = time.monotonic()
            client.sendall(headers + body[:1])
            response = b""
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response += chunk
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 1.0)
        self.assertIn(b" 404 ", response.split(b"\r\n", 1)[0])
        capability.assert_not_called()

    def test_codex_readiness_route_has_no_request_body_or_secret_fields(self):
        response = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "state": "sign_in_required",
            "setup_command": "codex login",
        }
        with patch.object(
            local_bridge,
            "bridge_codex_readiness_payload",
            return_value=(response, 200),
        ):
            status, payload, _headers = self.request(
                path=local_bridge.BRIDGE_CODEX_READINESS_PATH,
            )
        self.assertEqual((status, payload), (200, response))
        self.assertNotIn("account", json.dumps(payload))
        self.assertNotIn("token", json.dumps(payload))
        status, payload, _headers = self.request(
            path=f"{local_bridge.BRIDGE_CODEX_READINESS_PATH}?refresh=1",
        )
        self.assertEqual((status, payload), (404, {"error": "bridge_route_not_found"}))

    def test_provider_connections_is_a_fixed_secret_free_projection(self):
        canonical = {
            "schema_version": 1,
            "count": 1,
            "connections": [{
                "id": "connection_vercel",
                "provider": "vercel",
                "label": "Vercel",
                "state": "configured",
                "model": "openai/gpt-5.4",
                "capabilities": [
                    {"id": "ai.gateway", "status": "credential_present"},
                    {"id": "sandbox.readiness", "status": "needs_auth"},
                    {"id": "connect.token", "status": "credential_present"},
                ],
            }],
        }
        ready = local_bridge._ready_provider_connections_payload(canonical)
        with patch.object(
            local_bridge,
            "bridge_provider_connections_payload",
            return_value=(ready, 200),
        ):
            status, payload, _headers = self.request(
                path=local_bridge.BRIDGE_PROVIDER_CONNECTIONS_PATH
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload["connections"], canonical["connections"])
        encoded = json.dumps(payload)
        for private_name in (
            "auth_kind",
            "team_id",
            "project_id",
            "connector",
            "connect_scopes",
            "credential_ref",
        ):
            self.assertNotIn(private_name, encoded)
        self.assertNotIn('"credential":', encoded)
        self.assertNotIn("secret-canary", encoded)

    def test_provider_connections_rejects_private_fields_and_inconsistent_state(self):
        base = {
            "schema_version": 1,
            "count": 1,
            "connections": [{
                "id": "connection_vercel",
                "provider": "vercel",
                "label": "Vercel",
                "state": "needs_auth",
                "model": "openai/gpt-5.4",
                "capabilities": [{"id": "ai.gateway", "status": "needs_auth"}],
            }],
        }
        candidates = (
            {
                **base,
                "connections": [{**base["connections"][0], "token": "secret-canary"}],
            },
            {
                **base,
                "connections": [{
                    **base["connections"][0],
                    "state": "configured",
                }],
            },
            {
                **base,
                "connections": [{
                    **base["connections"][0],
                    "capabilities": [
                        {"id": "connect.token", "status": "needs_auth"},
                        {"id": "ai.gateway", "status": "needs_auth"},
                    ],
                }],
            },
        )
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(
                    local_bridge.BridgeProviderConnectionProjectionError
                ):
                    local_bridge._ready_provider_connections_payload(candidate)

    def test_provider_connection_capability_maps_failures_without_details(self):
        empty = {"schema_version": 1, "connections": [], "count": 0}
        cases = (
            (empty, "ready", 200),
            (
                VercelConnectionUnavailable("vercel.connection_unavailable"),
                "unavailable",
                503,
            ),
            (
                VercelConnectionError("vercel.connection_unsupported"),
                "unsupported",
                501,
            ),
            (VercelConnectionError("private-canary"), "error", 500),
        )
        for outcome, expected_state, expected_status in cases:
            with self.subTest(expected_state=expected_state):
                with patch.object(
                    server,
                    "mentat_provider_connections_payload",
                    side_effect=outcome if isinstance(outcome, Exception) else None,
                    return_value=None if isinstance(outcome, Exception) else outcome,
                ):
                    payload, status = local_bridge.bridge_provider_connections_payload()
                self.assertEqual(status, expected_status)
                self.assertEqual(payload["status"], expected_state)
                self.assertNotIn("private-canary", json.dumps(payload))

    def test_tasks_is_a_fixed_sqlite_projection_without_descriptions(self):
        canonical = {"schema_version": 1, "count": 1, "tasks": [{"id": "task_1", "title": "Current task", "project": "Mentat", "status": "todo", "priority": "medium", "due_date": None, "tags": ["planning"], "needs_attention": False, "review_required": False, "updated_at": "2026-08-22T00:00:00Z", "description": "private"}]}
        with (
            patch.object(
                server,
                "ensure_task_authority",
                side_effect=AssertionError("bridge_must_not_start_task_authority"),
            ) as ensure_authority,
            patch.object(server, "mentat_tasks_payload", return_value=canonical),
        ):
            payload, status = local_bridge.bridge_tasks_payload()
        self.assertEqual(status, 200)
        ensure_authority.assert_not_called()
        self.assertEqual(payload["tasks"][0]["title"], "Current task")
        self.assertNotIn("description", json.dumps(payload))
        self.assertNotIn("tasks.json", json.dumps(payload))

    def test_tasks_accept_canonical_wide_task_ids_and_map_corruption_to_error(self):
        identifier = "task@" + "x" * 155
        canonical = {"schema_version": 1, "count": 1, "tasks": [{"id": identifier, "title": "Task", "project": "Mentat", "status": "todo", "priority": "medium", "due_date": None, "tags": [], "needs_attention": False, "review_required": False, "updated_at": "2026-08-22T00:00:00Z"}]}
        with patch.object(server, "mentat_tasks_payload", return_value=canonical):
            payload, status = local_bridge.bridge_tasks_payload()
        self.assertEqual((status, payload["tasks"][0]["id"]), (200, identifier))
        with patch.object(server, "mentat_tasks_payload", side_effect=TaskRepositoryError("task_repository.corrupt")):
            payload, status = local_bridge.bridge_tasks_payload()
        self.assertEqual((status, payload["status"]), (500, "error"))

    def test_runs_is_a_fixed_sqlite_projection_without_runtime_references(self):
        canonical = {
            "schema_version": 1,
            "count": 1,
            "runs": [{
                "id": "run_current",
                "source": "task_dispatch",
                "task_id": "task_1",
                "agent_id": "agent_researcher",
                "runtime_type": "hermes",
                "status": "running",
                "dispatch_state": "accepted",
                "partial": False,
                "timeline": {"truncated": False, "last_sequence": 4},
                "created_at": "2026-08-22T00:00:00Z",
                "updated_at": "2026-08-22T00:01:00Z",
                "started_at": "2026-08-22T00:00:01Z",
                "completed_at": None,
                "runtime_run_ref": "private-canary",
                "state_revision": 4,
                "events": [{"summary": "private-canary"}],
            }],
        }
        with (
            patch.object(
                server,
                "ensure_run_sqlite_authority",
                side_effect=AssertionError("bridge_must_not_start_run_authority"),
            ) as ensure_authority,
            patch.object(server, "mentat_runs_payload", return_value=canonical),
        ):
            payload, status = local_bridge.bridge_runs_payload()
        self.assertEqual(status, 200)
        ensure_authority.assert_not_called()
        self.assertEqual(payload["runs"][0]["id"], "run_current")
        self.assertEqual(payload["runs"][0]["timeline_truncated"], False)
        for private_name in ("runtime_run_ref", "state_revision", "events", "last_sequence"):
            self.assertNotIn(private_name, json.dumps(payload))

    def test_runs_reject_malformed_data_and_map_fixed_failures(self):
        malformed = {
            "id": "run_current",
            "source": "task_dispatch",
            "task_id": "task_1",
            "agent_id": "agent_researcher",
            "runtime_type": "hermes",
            "status": "running",
            "dispatch_state": "accepted",
            "partial": False,
            "timeline": {"truncated": "false"},
            "created_at": "2026-08-22T00:00:00Z",
            "updated_at": "2026-08-22T00:01:00Z",
            "started_at": None,
            "completed_at": None,
        }
        with self.assertRaises(local_bridge.BridgeRunProjectionError):
            local_bridge._public_run_record(malformed)

        cases = (
            (RunRepositoryUnavailable("run_repository.unavailable"), "unavailable", 503),
            (RunRepositoryError("run_repository.schema_unsupported"), "unsupported", 501),
            (RunRepositoryError("run_repository.corrupt"), "error", 500),
            (ValueError("private database detail"), "error", 500),
        )
        for outcome, expected_state, expected_status in cases:
            with self.subTest(expected_state=expected_state):
                with patch.object(server, "mentat_runs_payload", side_effect=outcome):
                    payload, status = local_bridge.bridge_runs_payload()
                self.assertEqual((status, payload["status"]), (expected_status, expected_state))
                self.assertNotIn("private", json.dumps(payload))

    def test_runs_private_route_returns_only_the_fixed_projection(self):
        response = {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "runs": [],
            "count": 0,
        }
        with patch.object(local_bridge, "bridge_runs_payload", return_value=(response, 200)):
            status, payload, _headers = self.request(path=local_bridge.BRIDGE_RUNS_PATH)
        self.assertEqual((status, payload), (200, response))

    def test_run_events_are_a_fixed_bounded_projection_with_safe_vercel_messages(self):
        canonical = {
            "schema_version": 1,
            "run_id": "run_current",
            "after": 3,
            "next_cursor": 5,
            "cursor_reset_required": False,
            "events": [{
                "id": "event_current",
                "run_id": "run_current",
                "sequence": 4,
                "type": "run.started",
                "occurred_at": "2026-08-22T00:01:00Z",
                "summary": "Runtime accepted dispatch",
                "message": None,
                "metrics": {"total_tokens": 12},
            }, {
                "id": trusted_vercel_message_event_id("run_current"),
                "run_id": "run_current",
                "sequence": 5,
                "type": "message",
                "occurred_at": "2026-08-22T00:01:01Z",
                "summary": "Vercel AI Gateway returned a response",
                "message": "A bounded result from Vercel.",
                "metrics": {},
            }],
        }
        with patch.object(server, "mentat_run_events_payload", return_value=canonical):
            payload, status = local_bridge.bridge_run_events_payload("run_current", 3)
        self.assertEqual((status, payload["next_cursor"]), (200, 5))
        self.assertEqual(payload["events"][0]["summary"], "Runtime accepted dispatch")
        self.assertEqual(payload["events"][1]["message"], "A bounded result from Vercel.")
        for private_name in ("content", "runtime_run_ref", "payload", "data"):
            self.assertNotIn(private_name, json.dumps(payload))

    def test_run_events_reject_invalid_data_and_map_fixed_failures(self):
        malformed = {
            "schema_version": 1,
            "run_id": "run_current",
            "after": 0,
            "next_cursor": 1,
            "cursor_reset_required": False,
            "events": [{
                "id": "event_current", "run_id": "run_current", "sequence": 1,
                "type": "run.started", "occurred_at": "2026-08-22T00:01:00Z",
                "summary": "Event", "message": "not allowed", "metrics": {},
            }],
        }
        with patch.object(server, "mentat_run_events_payload", return_value=malformed):
            payload, status = local_bridge.bridge_run_events_payload("run_current", 0)
        self.assertEqual((status, payload["status"]), (500, "error"))
        wrong_provenance = {
            **malformed,
            "events": [{
                **malformed["events"][0],
                "id": "event_result",
                "type": "message",
                "message": "A result without trusted provenance.",
            }],
        }
        with patch.object(
            server,
            "mentat_run_events_payload",
            return_value=wrong_provenance,
        ):
            payload, status = local_bridge.bridge_run_events_payload(
                "run_current", 0
            )
        self.assertEqual((status, payload["status"]), (500, "error"))
        duplicate_results = {
            **malformed,
            "next_cursor": 2,
            "events": [
                {
                    **malformed["events"][0],
                    "id": "event_result_one",
                    "type": "message",
                    "message": "First result.",
                },
                {
                    **malformed["events"][0],
                    "id": "event_result_two",
                    "sequence": 2,
                    "type": "message",
                    "message": "Second result.",
                },
            ],
        }
        with patch.object(
            server,
            "mentat_run_events_payload",
            return_value=duplicate_results,
        ):
            payload, status = local_bridge.bridge_run_events_payload("run_current", 0)
        self.assertEqual((status, payload["status"]), (500, "error"))
        cases = (
            (RunRepositoryConflict("run.not_found"), "not_found", 404),
            (RunRepositoryUnavailable("run_repository.unavailable"), "unavailable", 503),
            (RunRepositoryError("run_repository.schema_unsupported"), "unsupported", 501),
            (ValueError("private detail"), "error", 500),
        )
        for outcome, expected_state, expected_status in cases:
            with self.subTest(expected_state=expected_state):
                with patch.object(server, "mentat_run_events_payload", side_effect=outcome):
                    payload, status = local_bridge.bridge_run_events_payload("run_current", 0)
                self.assertEqual((status, payload["status"]), (expected_status, expected_state))
                self.assertNotIn("private", json.dumps(payload))

    def test_run_events_private_route_has_one_validated_cursor(self):
        response = {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "run_id": "run_current", "after": 0,
            "next_cursor": 0, "cursor_reset_required": False, "events": [],
        }
        with patch.object(local_bridge, "bridge_run_events_payload", return_value=(response, 200)):
            status, payload, _headers = self.request(path="/bridge/v1/runs/run_current/events?after=0")
        self.assertEqual((status, payload), (200, response))
        colon_run_id = "run_current:child"
        colon_response = {**response, "run_id": colon_run_id}
        with patch.object(local_bridge, "bridge_run_events_payload", return_value=(colon_response, 200)) as capability:
            status, payload, _headers = self.request(path="/bridge/v1/runs/run_current%3Achild/events?after=0")
        self.assertEqual((status, payload), (200, colon_response))
        capability.assert_called_once_with(colon_run_id, 0)
        status, payload, _headers = self.request(path="/bridge/v1/runs/run_current/events?after=0&after=1")
        self.assertEqual((status, payload), (404, {"error": "bridge_route_not_found"}))
        for invalid_path in (
            "/bridge/v1/runs/run_current%2Fchild/events?after=0",
            "/bridge/v1/runs/run_current%252Fchild/events?after=0",
            "/bridge/v1/runs/%2E%2E/events?after=0",
            "/bridge/v1/runs/run_current/extra/events?after=0",
        ):
            with self.subTest(path=invalid_path):
                status, payload, _headers = self.request(path=invalid_path)
                self.assertEqual((status, payload), (404, {"error": "bridge_route_not_found"}))

    def test_run_stop_actions_are_fixed_authenticated_and_body_bounded(self):
        preview = {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "stop", "run_id": "run_current",
            "requires_confirmation": True, "confirmation_id": "a" * 64,
        }
        with patch.object(local_bridge, "bridge_run_stop_preview_payload", return_value=(preview, 200)):
            status, payload, _headers = self.request(
                method="POST", path="/bridge/v1/runs/run_current/stop/preview",
                headers={"Content-Type": "application/json"}, body=b"{}",
            )
        self.assertEqual((status, payload), (200, preview))
        result = {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "stop", "run_id": "run_current",
            "disposition": "requested",
        }
        with patch.object(local_bridge, "bridge_confirm_run_stop", return_value=(result, 202)) as confirmed:
            status, payload, _headers = self.request(
                method="POST", path="/bridge/v1/runs/run_current/stop",
                headers={"Content-Type": "application/json"}, body=(b'{"confirmation_id":"' + b"a" * 64 + b'"}'),
            )
        self.assertEqual((status, payload), (202, result))
        confirmed.assert_called_once_with("run_current", "a" * 64)
        status, payload, _headers = self.request(
            method="POST", path="/bridge/v1/runs/run_current/stop",
            headers={"Content-Type": "application/json"}, body=b'{"action":"stop"}',
        )
        self.assertEqual((status, payload), (404, {"error": "bridge_route_not_found"}))

    def test_run_message_actions_are_fixed_authenticated_and_body_bounded(self):
        preview = {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "message", "run_id": "run_current",
            "requires_confirmation": True, "confirmation_id": "a" * 64,
        }
        with patch.object(local_bridge, "bridge_run_message_preview_payload", return_value=(preview, 200)) as capability:
            status, payload, _headers = self.request(
                method="POST", path="/bridge/v1/runs/run_current/message/preview",
                headers={"Content-Type": "application/json"}, body=b'{"text":"Stay focused"}',
            )
        self.assertEqual((status, payload), (200, preview))
        capability.assert_called_once_with("run_current", "Stay focused")
        unicode_text = "€" * 4_000
        unicode_preview_body = json.dumps(
            {"text": unicode_text}, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        with patch.object(local_bridge, "bridge_run_message_preview_payload", return_value=(preview, 200)) as unicode_capability:
            status, payload, _headers = self.request(
                method="POST", path="/bridge/v1/runs/run_current/message/preview",
                headers={"Content-Type": "application/json"}, body=unicode_preview_body,
            )
        self.assertGreater(len(unicode_preview_body), 9_999)
        self.assertLessEqual(len(unicode_preview_body), local_bridge.MAXIMUM_BRIDGE_MESSAGE_BODY_BYTES)
        self.assertEqual((status, payload), (200, preview))
        unicode_capability.assert_called_once_with("run_current", unicode_text)
        result = {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "message", "run_id": "run_current",
            "disposition": "accepted",
        }
        with patch.object(local_bridge, "bridge_confirm_run_message", return_value=(result, 202)) as confirmed:
            status, payload, _headers = self.request(
                method="POST", path="/bridge/v1/runs/run_current/message",
                headers={"Content-Type": "application/json"},
                body=(b'{"text":"Stay focused","confirmation_id":"' + b"a" * 64 + b'"}'),
            )
        self.assertEqual((status, payload), (202, result))
        confirmed.assert_called_once_with("run_current", "Stay focused", "a" * 64)
        unicode_confirmation_body = json.dumps(
            {"text": unicode_text, "confirmation_id": "a" * 64},
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")
        with patch.object(local_bridge, "bridge_confirm_run_message", return_value=(result, 202)) as unicode_confirmed:
            status, payload, _headers = self.request(
                method="POST", path="/bridge/v1/runs/run_current/message",
                headers={"Content-Type": "application/json"}, body=unicode_confirmation_body,
            )
        self.assertGreater(len(unicode_confirmation_body), 9_999)
        self.assertLessEqual(len(unicode_confirmation_body), local_bridge.MAXIMUM_BRIDGE_MESSAGE_BODY_BYTES)
        self.assertEqual((status, payload), (202, result))
        unicode_confirmed.assert_called_once_with("run_current", unicode_text, "a" * 64)
        for path, body in (
            ("/bridge/v1/runs/run_current/message/preview", b"{}"),
            ("/bridge/v1/runs/run_current/message", b'{"confirmation_id":"' + b"a" * 64 + b'"}'),
            ("/bridge/v1/runs/run_current/message/preview", b'{"text":"x","extra":true}'),
            ("/bridge/v1/runs/run_current/message/preview", b'{"text":"' + b"x" * 24_600 + b'"}'),
        ):
            with self.subTest(path=path, body_length=len(body)):
                status, payload, _headers = self.request(
                    method="POST", path=path, headers={"Content-Type": "application/json"}, body=body,
                )
                self.assertEqual((status, payload), (404, {"error": "bridge_route_not_found"}))

    def test_run_events_authority_reader_never_initializes_sqlite(self):
        implementation = inspect.getsource(server.mentat_run_events_payload)
        self.assertIn("connect_existing_mentat_database", implementation)
        self.assertNotIn("connect_mentat_database(", implementation)

    def test_runs_payload_requires_existing_authority_without_initializing_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch.object(server, "DATA_DIR", Path(temporary)),
                patch.object(
                    server,
                    "ensure_run_sqlite_authority",
                    side_effect=AssertionError("bridge_must_not_start_run_authority"),
                ) as ensure_authority,
            ):
                with self.assertRaises(RunRepositoryUnavailable):
                    server.mentat_runs_payload()
            ensure_authority.assert_not_called()
            self.assertFalse((Path(temporary) / "private" / "console" / "mentat.sqlite3").exists())

    def test_runs_payload_reads_existing_authority_without_changing_database_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = connect_mentat_database(root)
            try:
                repository = RunRepository(connection)
                with repository.mutation():
                    repository.claim_authority(source_sha256="a" * 64, source_run_count=0)
                database = mentat_database_path(root)
                paths = (database, Path(f"{database}-wal"), Path(f"{database}-shm"))
                self.assertTrue(all(path.exists() for path in paths))
                before = tuple(path.read_bytes() for path in paths)
                with patch.object(server, "DATA_DIR", root):
                    self.assertEqual(server.mentat_runs_payload()["runs"], [])
                self.assertEqual(tuple(path.read_bytes() for path in paths), before)
                with (
                    patch.object(mentat_db, "MAX_READONLY_DATABASE_BYTES", 1),
                    patch.object(server, "DATA_DIR", root),
                ):
                    with self.assertRaises(RunRepositoryUnavailable):
                        server.mentat_runs_payload()
            finally:
                connection.close()

    def test_duplicate_or_body_headers_fail_closed(self):
        header_sets = (
            [
                ("Host", f"127.0.0.1:{self.port}"),
                ("Host", f"127.0.0.1:{self.port}"),
                (local_bridge.BRIDGE_TOKEN_HEADER, TOKEN),
            ],
            [
                ("Host", f"127.0.0.1:{self.port}"),
                (local_bridge.BRIDGE_TOKEN_HEADER, TOKEN),
                ("Origin", ""),
            ],
            [
                ("Host", f"127.0.0.1:{self.port}"),
                (local_bridge.BRIDGE_TOKEN_HEADER, TOKEN),
                ("Content-Length", "0"),
            ],
        )
        for headers in header_sets:
            with self.subTest(headers=headers):
                connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
                connection.putrequest("GET", local_bridge.BRIDGE_HEALTH_PATH, skip_host=True)
                for name, value in headers:
                    connection.putheader(name, value)
                connection.endheaders()
                response = connection.getresponse()
                payload = json.loads(response.read())
                connection.close()
                self.assertEqual(response.status, 403)
                self.assertEqual(payload, {"error": "bridge_request_forbidden"})

    def test_run_response_actions_are_fixed_authenticated_and_body_bounded(self):
        request = {
            "kind": "approval", "title": "Use a tool", "summary": "Read project data",
            "choices": [{"id": "once", "label": "Allow once"}, {"id": "deny", "label": "Deny"}],
        }
        pending = {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "respond", "run_id": "run_current",
            "request": request, "requires_confirmation": False,
        }
        with patch.object(local_bridge, "bridge_run_response_request_payload", return_value=(pending, 200)) as capability:
            status, payload, _headers = self.request(
                method="POST", path="/bridge/v1/runs/run_current/response",
                headers={"Content-Type": "application/json"}, body=b"{}",
            )
        self.assertEqual((status, payload), (200, pending))
        capability.assert_called_once_with("run_current")
        preview = {**pending, "requires_confirmation": True, "confirmation_id": "a" * 64}
        body = b'{"response":{"kind":"approval","choice":"once"}}'
        with patch.object(local_bridge, "bridge_run_response_preview_payload", return_value=(preview, 200)) as capability:
            status, payload, _headers = self.request(
                method="POST", path="/bridge/v1/runs/run_current/response/preview",
                headers={"Content-Type": "application/json"}, body=body,
            )
        self.assertEqual((status, payload), (200, preview))
        capability.assert_called_once_with("run_current", {"kind": "approval", "choice": "once"})
        result = {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "respond", "run_id": "run_current", "disposition": "accepted",
        }
        with patch.object(local_bridge, "bridge_confirm_run_response", return_value=(result, 202)) as confirmed:
            status, payload, _headers = self.request(
                method="POST", path="/bridge/v1/runs/run_current/response",
                headers={"Content-Type": "application/json"},
                body=(b'{"response":{"kind":"approval","choice":"once"},"confirmation_id":"' + b"a" * 64 + b'"}'),
            )
        self.assertEqual((status, payload), (202, result))
        confirmed.assert_called_once_with("run_current", {"kind": "approval", "choice": "once"}, "a" * 64)
        status, payload, _headers = self.request(
            method="POST", path="/bridge/v1/runs/run_current/response",
            headers={"Content-Type": "application/json"}, body=b'{"response":{"kind":"approval","choice":"once"}}',
        )
        self.assertEqual((status, payload), (404, {"error": "bridge_route_not_found"}))

    def test_unknown_routes_and_unsupported_methods_are_fixed(self):
        status, payload, _headers = self.request(path="/bridge/v1/other")
        self.assertEqual(status, 404)
        self.assertEqual(payload, {"error": "bridge_route_not_found"})

        status, payload, _headers = self.request(method="POST")
        self.assertEqual(status, 405)
        self.assertEqual(payload, {"error": "method_not_allowed"})

        status, payload, _headers = self.request(method="POST", token=None)
        self.assertEqual(status, 403)
        self.assertEqual(payload, {"error": "bridge_request_forbidden"})

    def test_configuration_rejects_nonloopback_hosts_ports_and_weak_tokens(self):
        for host in ("localhost", "0.0.0.0", "example.test", ""):
            with self.subTest(host=host):
                with self.assertRaises(local_bridge.BridgeConfigurationError):
                    local_bridge.validate_bridge_host(host)

        for port in (-1, 65536, "not-a-port"):
            with self.subTest(port=port):
                with self.assertRaises(local_bridge.BridgeConfigurationError):
                    local_bridge.validate_bridge_port(port)

        for token in ("", "short", "x" * 257, "x" * 42 + " ", "é" * 50):
            with self.subTest(token=token):
                with self.assertRaises(local_bridge.BridgeConfigurationError):
                    local_bridge.validate_bridge_token(token)

    def test_host_header_parser_requires_the_exact_bound_ip_and_port(self):
        self.assertTrue(
            local_bridge.host_header_matches_binding(
                f"127.0.0.1:{self.port}", "127.0.0.1", self.port
            )
        )
        self.assertFalse(
            local_bridge.host_header_matches_binding(
                f"localhost:{self.port}", "127.0.0.1", self.port
            )
        )
        self.assertFalse(
            local_bridge.host_header_matches_binding(
                f"user@127.0.0.1:{self.port}", "127.0.0.1", self.port
            )
        )


class LocalBridgeMainTests(unittest.TestCase):
    def test_startup_crash_recovery_finishes_before_any_request_is_served(self):
        bridge = SimpleNamespace(
            server_address=("127.0.0.1", 43210),
            timeout=None,
            handle_request=Mock(),
            server_close=Mock(),
        )
        recovery_started = threading.Event()
        release_recovery = threading.Event()

        def recover() -> None:
            recovery_started.set()
            release_recovery.wait(timeout=2)

        with patch.object(
            local_bridge, "build_bridge_server", return_value=bridge
        ), patch.object(
            local_bridge, "_recover_bridge_runs_before_ready", side_effect=recover
        ), patch.object(
            local_bridge, "configured_launcher_pid", return_value=123
        ), patch.object(
            local_bridge, "launcher_is_running", side_effect=(True, False)
        ), patch.object(
            local_bridge, "start_bridge_startup_reconciliation"
        ), patch.object(
            server, "shutdown_agent_runtimes"
        ):
            result: list[int] = []
            worker = threading.Thread(
                target=lambda: result.append(
                    local_bridge.main(["--host", "127.0.0.1", "--port", "0"])
                )
            )
            worker.start()
            self.assertTrue(recovery_started.wait(timeout=1))
            self.assertFalse(bridge.handle_request.called)
            release_recovery.set()
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [0])
        bridge.handle_request.assert_called_once_with()

    def test_startup_reconciliation_uses_the_runtime_neutral_service(self):
        with patch.object(
            server, "reconcile_orchestration_runtime_references_at_startup"
        ) as reconcile:
            local_bridge._reconcile_bridge_runs_at_startup()

        reconcile.assert_called_once_with()

        with patch.object(
            server,
            "reconcile_orchestration_runtime_references_at_startup",
            side_effect=RuntimeError("private detail"),
        ):
            local_bridge._reconcile_bridge_runs_at_startup()

        with patch.object(
            server, "recover_orchestration_crash_states_at_startup"
        ) as recover, patch.object(
            server, "load_agent_console_runs_after_startup_recovery"
        ) as load_history:
            local_bridge._recover_bridge_runs_before_ready()
        recover.assert_called_once_with(recover_legacy_console_runs=True)
        load_history.assert_called_once_with()

    def test_main_closes_loaded_process_owning_runtimes(self):
        bridge = SimpleNamespace(
            server_address=("127.0.0.1", 43210),
            timeout=None,
            handle_request=Mock(),
            server_close=Mock(),
        )
        with patch.object(
            local_bridge, "build_bridge_server", return_value=bridge
        ), patch.object(
            local_bridge, "_recover_bridge_runs_before_ready"
        ), patch.object(
            local_bridge, "configured_launcher_pid", return_value=None
        ), patch.object(
            local_bridge, "launcher_is_running", return_value=False
        ), patch.object(
            local_bridge, "start_bridge_startup_reconciliation"
        ) as reconcile, patch.object(
            server, "shutdown_agent_runtimes"
        ) as shutdown:
            result = local_bridge.main(["--host", "127.0.0.1", "--port", "0"])

        self.assertEqual(result, 0)
        bridge.server_close.assert_called_once_with()
        reconcile.assert_called_once_with()
        shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
