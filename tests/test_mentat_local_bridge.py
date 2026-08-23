from __future__ import annotations

from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
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


TOKEN = "bridge-token-that-is-long-enough-for-256-bits-of-entropy"


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
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        request_headers = {"Host": f"127.0.0.1:{self.port}"}
        if token is not None:
            request_headers[local_bridge.BRIDGE_TOKEN_HEADER] = token
        request_headers.update(headers or {})
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        body = response.read()
        response_headers = {name: value for name, value in response.getheaders()}
        connection.close()
        return response.status, json.loads(body), response_headers

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

    def test_run_events_are_a_fixed_bounded_projection_without_content(self):
        canonical = {
            "schema_version": 1,
            "run_id": "run_current",
            "after": 3,
            "next_cursor": 4,
            "cursor_reset_required": False,
            "events": [{
                "id": "event_current",
                "run_id": "run_current",
                "sequence": 4,
                "type": "run.started",
                "occurred_at": "2026-08-22T00:01:00Z",
                "summary": "Runtime accepted dispatch",
                "metrics": {"total_tokens": 12},
            }],
        }
        with patch.object(server, "mentat_run_events_payload", return_value=canonical):
            payload, status = local_bridge.bridge_run_events_payload("run_current", 3)
        self.assertEqual((status, payload["next_cursor"]), (200, 4))
        self.assertEqual(payload["events"][0]["summary"], "Runtime accepted dispatch")
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
                "type": "message", "occurred_at": "2026-08-22T00:01:00Z",
                "summary": "Event", "metrics": {}, "content": "private",
            }],
        }
        with patch.object(server, "mentat_run_events_payload", return_value=malformed):
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
        source = Path(server.__file__).read_text(encoding="utf-8")
        start = source.index("def mentat_run_events_payload")
        end = source.index("\ndef orchestration_run_payload", start)
        implementation = source[start:end]
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
            local_bridge, "configured_launcher_pid", return_value=None
        ), patch.object(
            local_bridge, "launcher_is_running", return_value=False
        ), patch.object(
            server, "shutdown_agent_runtimes"
        ) as shutdown:
            result = local_bridge.main(["--host", "127.0.0.1", "--port", "0"])

        self.assertEqual(result, 0)
        bridge.server_close.assert_called_once_with()
        shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
