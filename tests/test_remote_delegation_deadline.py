from __future__ import annotations

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import http_read_deadline
from hermes_kanban import RemoteHermesKanbanAdapter
from remote_hermes import RemoteHermesClient, RemoteHermesError
import server


def capabilities(*, kanban=True):
    payload = {
        "object": "hermes.api_server.capabilities", "platform": "hermes-agent", "model": "test-model",
        "auth": {"type": "bearer", "required": True},
        "runtime": {"mode": "server_agent", "tool_execution": "server", "split_runtime": False},
        "features": {"profile_inventory": True, "profile_inventory_version": 1, "profile_inventory_complete": True, "profile_inventory_requires_api_key": True},
        "endpoints": {"health": {"method": "GET", "path": "/health"}, "health_detailed": {"method": "GET", "path": "/health/detailed"}, "profiles": {"method": "GET", "path": "/v1/profiles"}},
    }
    if kanban:
        payload["features"].update({"kanban_api": True, "kanban_api_version": 1, "kanban_api_revisioned": True, "kanban_api_idempotency": True, "kanban_api_requires_api_key": True})
        for name, method, path in (
            ("kanban_boards", "GET", "/v1/kanban/boards"), ("kanban_profiles", "GET", "/v1/kanban/profiles?board={board}"),
            ("kanban_tasks", "GET", "/v1/kanban/tasks?board={board}"), ("kanban_task", "GET", "/v1/kanban/tasks/{task_id}?board={board}"),
            ("kanban_task_create", "POST", "/v1/kanban/tasks?board={board}"), ("kanban_task_action", "POST", "/v1/kanban/tasks/{task_id}/actions?board={board}"),
        ):
            payload["endpoints"][name] = {"method": method, "path": path}
    return payload


@contextmanager
def remote_fixture(*, delay=0.0, trickle=None, kanban=True):
    paths = []
    disconnected = threading.Event()
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            paths.append(self.path)
            try:
                if trickle == "headers":
                    self.connection.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    for _ in range(200):
                        if stop.wait(0.02):
                            break
                        self.connection.sendall(b"a")
                    return
                if delay:
                    stop.wait(delay)
                payload = capabilities(kanban=kanban) if self.path == "/v1/capabilities" else (
                    {"object": "list", "version": 1, "complete": True, "active_profile": "default", "data": [{"id": "default", "object": "hermes.profile", "is_default": True, "is_active": True, "served": True}]}
                    if self.path == "/v1/profiles" else
                    {"object": "list", "version": 1, "complete": True, "data": [{"id": "default", "object": "hermes.kanban.board", "name": "Default", "archived": False, "is_current": True}]}
                )
                raw = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Connection", "close")
                self.end_headers()
                if trickle == "body":
                    for byte in raw:
                        if stop.wait(0.02):
                            break
                        self.wfile.write(bytes([byte])); self.wfile.flush()
                else:
                    self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, OSError):
                disconnected.set()

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}", paths, disconnected
    finally:
        stop.set(); http.shutdown(); http.server_close(); worker.join(timeout=1)


class RemoteDelegationDeadlineTests(unittest.TestCase):
    def options(self, endpoint, *, seconds=8.0):
        selection = SimpleNamespace(mode="remote", endpoint=endpoint, api_key="private-test-key", binding_id="remote-test")
        client = RemoteHermesClient(endpoint, selection.api_key)
        adapter = RemoteHermesKanbanAdapter(client, connection_binding_id=selection.binding_id)
        current = {"schema_version": 1, "task": {"id": "task_test", "revision": 1}, "delegation": {"available": False, "reason": "not_delegated"}}
        with patch.object(server, "_planning_delegation_current_payload", return_value=(current, 200)), patch.object(server, "load_remote_hermes_connection", return_value=selection), patch.object(server, "kanban_adapter", return_value=adapter), patch.object(server, "PLANNING_DELEGATION_DISCOVERY_SECONDS", seconds):
            return server.mentat_planning_task_delegation_options_payload("task_test")

    def test_real_remote_adapter_profiles_and_boards_share_one_absolute_budget(self):
        with remote_fixture(delay=0.08) as (endpoint, paths, _disconnected):
            started = time.monotonic()
            result, status = self.options(endpoint, seconds=0.33)
            elapsed = time.monotonic() - started
        self.assertEqual(status, 200)
        self.assertFalse(result["options"]["available"])
        self.assertLess(elapsed, 0.65)
        self.assertGreaterEqual(paths.count("/v1/capabilities"), 2)
        self.assertNotIn("private-test-key", json.dumps(result))

    def test_real_remote_adapter_still_discovers_supported_targets(self):
        with remote_fixture() as (endpoint, paths, _disconnected):
            result, status = self.options(endpoint)
        self.assertEqual(status, 200)
        self.assertTrue(result["options"]["available"])
        self.assertEqual(result["options"]["profiles"], [{"id": "default", "name": "default"}])
        self.assertEqual(result["options"]["boards"], [{"id": "default", "name": "Default"}])
        self.assertEqual(paths, ["/v1/capabilities", "/v1/capabilities", "/v1/profiles", "/v1/capabilities", "/v1/kanban/boards"])

    def test_healthy_remote_without_kanban_is_a_capability_gap(self):
        with remote_fixture(kanban=False) as (endpoint, paths, _disconnected):
            result, status = self.options(endpoint)
        self.assertEqual(status, 200)
        self.assertEqual(result["options"], {"available": False, "reason": "capability_missing"})
        self.assertEqual(paths, ["/v1/capabilities"])

    def test_header_and_detached_body_trickle_close_exact_socket_by_deadline(self):
        for phase in ("headers", "body"):
            with self.subTest(phase=phase), remote_fixture(trickle=phase) as (endpoint, _paths, disconnected):
                client = RemoteHermesClient(endpoint, "private-test-key", timeout_seconds=2, read_deadline_at=time.monotonic() + 0.2)
                started = time.monotonic()
                with self.assertRaisesRegex(RemoteHermesError, "remote_timeout"):
                    client.require_kanban_capabilities()
                self.assertLess(time.monotonic() - started, 0.65)
                self.assertTrue(disconnected.wait(0.5), "server did not observe deadline socket cleanup")

    def test_dns_timeouts_use_only_two_resolver_slots_and_never_connect_later(self):
        release = threading.Event(); calls = []
        def stalled_dns(*args, **kwargs):
            calls.append((args, kwargs)); release.wait(1)
            return []
        try:
            with patch.object(http_read_deadline.socket, "getaddrinfo", side_effect=stalled_dns):
                for _ in range(3):
                    with self.assertRaises(TimeoutError):
                        http_read_deadline._resolve("deadline.example", 443, time.monotonic() + 0.02)
                self.assertEqual(len(calls), 2)
                self.assertTrue(all(args == ("deadline.example", 443) for args, _kwargs in calls))
        finally:
            release.set()
            acquired = []
            try:
                for _ in range(2):
                    self.assertTrue(http_read_deadline._DNS_SLOTS.acquire(timeout=0.5))
                    acquired.append(True)
            finally:
                for _ in acquired:
                    http_read_deadline._DNS_SLOTS.release()

    def test_deadline_https_keeps_certificate_verification_and_refuses_mutations(self):
        client = RemoteHermesClient("https://deadline.example", "private-test-key", read_deadline_at=time.monotonic() + 1)
        connection = client._connection()
        try:
            self.assertEqual(connection._connection._context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(connection._connection._context.check_hostname)
            with self.assertRaisesRegex(ValueError, "only GET"):
                connection.request("POST", "/v1/runs", body=b"{}")
        finally:
            connection.close()
        ordinary = RemoteHermesClient("https://deadline.example", "private-test-key")
        default_connection = ordinary._connection()
        try:
            self.assertNotIsInstance(default_connection, http_read_deadline.DeadlineReadConnection)
            self.assertEqual(default_connection.timeout, ordinary.timeout_seconds)
        finally:
            default_connection.close()
