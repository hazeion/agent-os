import hashlib
import hmac
import io
import json
import os
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from http.client import HTTPConnection
from threading import Thread
from concurrent.futures import ThreadPoolExecutor

import server
from hermes_browser_events import HermesBrowserEventBroker
from hermes_event_refresh import HermesRefreshCoordinator
from hermes_webhook_store import WebhookDeliveryStore
from hermes_webhooks import PerBindingRateLimiter
from task_repository import ensure_task_sqlite_authority


class _WebhookHandlerHarness:
    def __init__(self, body: bytes, headers: dict[str, str]):
        self.rfile = io.BytesIO(body)
        self.headers = headers
        self.responses: list[tuple[str, object]] = []

    def send_response(self, status):
        self.responses.append(("status", status))

    def send_header(self, name, value):
        self.responses.append((name, value))

    def end_headers(self):
        self.responses.append(("ended", True))

    def send_error_once(self, status, message=None):
        self.responses.append(("error", status))
        return True

    def log_internal_error(self, context, exc):
        self.responses.append(("internal_error", context))

    def log_webhook_error(self, code):
        self.responses.append(("webhook_error", code))


class HermesWebhookRouteTests(unittest.TestCase):
    binding_id = "local-default"
    secret = b"route-secret"

    def setUp(self):
        self.original_cache = server.HERMES_WEBHOOK_DELIVERIES
        self.original_coordinator = server.HERMES_EVENT_REFRESH
        self.original_capacity = server.HERMES_WEBHOOK_HINT_CAPACITY
        self.original_limiter = server.HERMES_WEBHOOK_RATE_LIMITER
        self.temporary = TemporaryDirectory()
        self.data_dir = Path(self.temporary.name) / "data"
        server.HERMES_WEBHOOK_DELIVERIES = WebhookDeliveryStore(self.data_dir)
        server.HERMES_WEBHOOK_RATE_LIMITER = PerBindingRateLimiter()
        server.HERMES_EVENT_REFRESH = HermesRefreshCoordinator({}, capacity=16)

    def tearDown(self):
        if server.HERMES_EVENT_REFRESH is not None:
            server.HERMES_EVENT_REFRESH.stop(timeout=1)
        server.HERMES_WEBHOOK_DELIVERIES = self.original_cache
        server.HERMES_WEBHOOK_RATE_LIMITER = self.original_limiter
        server.HERMES_EVENT_REFRESH = self.original_coordinator
        server.HERMES_WEBHOOK_HINT_CAPACITY = self.original_capacity
        self.temporary.cleanup()

    def request(self, *, event="on_session_end", delivery="delivery-1", body_overrides=None, content_type="application/json"):
        payload = {
            "hook_event_name": event,
            "delivery_id": delivery,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        payload.update(body_overrides or {})
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "X-Hermes-Signature-256": "sha256=" + signature,
            "X-Hermes-Event": event,
            "X-Hermes-Delivery": delivery,
        }
        return body, headers

    def invoke(self, body, headers):
        harness = _WebhookHandlerHarness(body, headers)
        with patch.dict(os.environ, {"MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT": self.secret.decode()}, clear=False):
            server.Handler.handle_hermes_webhook(harness, self.binding_id)
        return harness

    def status(self, harness):
        return next(value for kind, value in harness.responses if kind == "status")

    def test_new_signed_delivery_is_accepted_and_queued_without_refresh(self):
        body, headers = self.request()
        harness = self.invoke(body, headers)
        self.assertEqual(self.status(harness), 202)
        self.assertEqual(server.HERMES_EVENT_REFRESH.pending_count, 1)

    def test_acknowledgement_does_not_wait_for_slow_refresh_adapter(self):
        entered = threading.Event()
        release = threading.Event()
        completed = threading.Event()

        def slow_refresh(_binding):
            entered.set()
            release.wait(2)
            completed.set()
            return {"sessions": []}

        server.HERMES_EVENT_REFRESH = HermesRefreshCoordinator(
            {"sessions": slow_refresh},
            coalesce_window=0,
            reconciliation_interval=60,
        )
        server.HERMES_EVENT_REFRESH.start()
        body, headers = self.request(delivery="slow-adapter")
        try:
            harness = self.invoke(body, headers)
            self.assertEqual(self.status(harness), 202)
            self.assertTrue(entered.wait(1))
            self.assertFalse(completed.is_set())
        finally:
            release.set()
        self.assertTrue(server.HERMES_EVENT_REFRESH.wait_idle(1))

    def test_signed_local_kanban_event_wakes_verified_task_synchronization(self):
        task = {
            "id": "local-kanban-task",
            "title": "Local Kanban work",
            "description": "",
            "project": "Mentat",
            "status": "open",
            "priority": "medium",
            "source": "test",
            "tags": [],
            "review_required": False,
            "needs_attention": False,
            "created_at": "2026-08-14T20:00:00+00:00",
            "updated_at": "2026-08-14T20:00:00+00:00",
            "delegation": {
                "connection_binding_id": "local-default",
                "board_id": "default",
                "kanban_task_id": "kanban-local-1",
                "profile_id": "default",
                "state": "running",
                "sync_state": "synced",
                "review_state": "pending",
                "attempts": 0,
                "created_at": "2026-08-14T20:00:00+00:00",
                "updated_at": "2026-08-14T20:00:00+00:00",
            },
        }
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        tasks_path = self.data_dir / "tasks.json"
        tasks_path.write_text(json.dumps([task]), encoding="utf-8")
        tasks_path.chmod(0o600)
        ensure_task_sqlite_authority(self.data_dir)
        remote = {
            "ok": True,
            "task": {
                "id": "kanban-local-1",
                "status": "done",
                "session_id": "session-local-1",
            },
            "runs": [],
            "comments": [],
        }
        adapter = MagicMock()
        adapter.get_task.return_value = remote
        broker = HermesBrowserEventBroker()
        server.HERMES_EVENT_REFRESH = HermesRefreshCoordinator(
            {"kanban": server._refresh_webhook_kanban},
            coalesce_window=0,
            reconciliation_interval=60,
            on_refresh=broker.publish,
        )
        server.HERMES_EVENT_REFRESH.start()

        with (
            patch.object(server, "DATA_DIR", self.data_dir),
            patch.object(server, "HERMES_HOME", Path(self.temporary.name) / "hermes"),
            patch.object(server, "HermesKanbanAdapter", return_value=adapter),
            patch.object(server, "kanban_adapter", return_value=adapter),
            patch.object(
                server,
                "load_remote_hermes_connection",
                return_value=SimpleNamespace(
                    mode="local",
                    binding_id="local-default",
                ),
            ),
        ):
            body, headers = self.request(
                event="kanban_task_completed",
                delivery="kanban-local-completed",
            )
            accepted = self.invoke(body, headers)
            self.assertEqual(self.status(accepted), 202)
            self.assertTrue(server.HERMES_EVENT_REFRESH.wait_idle(2))
            wakeup = broker.wait_after(0, timeout=0)
            self.assertEqual(wakeup.projections, ("kanban",))

            refreshed, status = server.refresh_home_delegations()
            self.assertEqual(status, 200)
            self.assertEqual(refreshed["refreshed"], 1)
            visible = server.tasks_payload()["tasks"]

        self.assertEqual(visible[0]["delegation"]["state"], "ready_for_review")
        self.assertEqual(visible[0]["planning_state"], "review")
        self.assertTrue(visible[0]["needs_attention"])

    def test_duplicate_delivery_returns_no_content_and_is_not_requeued(self):
        body, headers = self.request()
        self.assertEqual(self.status(self.invoke(body, headers)), 202)
        duplicate = self.invoke(body, headers)
        self.assertEqual(self.status(duplicate), 204)
        self.assertEqual(server.HERMES_EVENT_REFRESH.pending_count, 1)

    def test_duplicate_delivery_remains_deduplicated_after_store_restart(self):
        body, headers = self.request(delivery="restart-safe")
        self.assertEqual(self.status(self.invoke(body, headers)), 202)
        server.HERMES_WEBHOOK_DELIVERIES = WebhookDeliveryStore(self.data_dir)
        duplicate = self.invoke(body, headers)
        self.assertEqual(self.status(duplicate), 204)
        self.assertEqual(server.HERMES_EVENT_REFRESH.pending_count, 1)

    def test_simultaneous_http_duplicates_accept_exactly_once(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        body, headers = self.request(delivery="concurrent-http")

        def deliver(_):
            connection = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/integrations/hermes/webhooks/v1/local-default",
                body,
                headers,
            )
            response = connection.getresponse()
            status = response.status
            response.read()
            connection.close()
            return status

        try:
            with patch.dict(
                os.environ,
                {"MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT": self.secret.decode()},
                clear=False,
            ):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    statuses = list(pool.map(deliver, range(8)))
            self.assertEqual(statuses.count(202), 1)
            self.assertEqual(statuses.count(204), 7)
            self.assertEqual(server.HERMES_EVENT_REFRESH.pending_count, 1)
            self.assertNotIn(b"concurrent-http", (self.data_dir / "private" / "console" / "mentat.sqlite3").read_bytes())
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    def test_rate_limit_returns_429_without_deduplicating_retry(self):
        server.HERMES_WEBHOOK_RATE_LIMITER = PerBindingRateLimiter(
            capacity=1,
            refill_per_second=0.000001,
        )
        first_body, first_headers = self.request(delivery="rate-first")
        self.assertEqual(self.status(self.invoke(first_body, first_headers)), 202)
        second_body, second_headers = self.request(delivery="rate-second")
        limited = self.invoke(second_body, second_headers)
        self.assertEqual(
            next(value for kind, value in limited.responses if kind == "error"),
            429,
        )
        server.HERMES_WEBHOOK_RATE_LIMITER = PerBindingRateLimiter()
        self.assertEqual(self.status(self.invoke(second_body, second_headers)), 202)

    def test_store_failure_returns_503_and_does_not_enqueue(self):
        server.HERMES_WEBHOOK_DELIVERIES = WebhookDeliveryStore(
            Path(self.temporary.name) / "unsafe-data"
        )
        unsafe_console = Path(self.temporary.name) / "unsafe-data" / "private" / "console"
        unsafe_console.mkdir(parents=True)
        (unsafe_console / "mentat.sqlite3").mkdir()
        body, headers = self.request(delivery="store-failure")
        failed = self.invoke(body, headers)
        self.assertEqual(
            next(value for kind, value in failed.responses if kind == "error"),
            503,
        )
        self.assertEqual(server.HERMES_EVENT_REFRESH.pending_count, 0)
        self.assertIn(("webhook_error", "webhook_store_unavailable"), failed.responses)

    def test_commit_failure_after_queue_admission_is_acknowledged_once(self):
        class AdmittedUnrecordedStore:
            def claim_and_admit(self, _event, admit):
                self.admitted = admit()
                return "admitted_unrecorded"

        store = AdmittedUnrecordedStore()
        server.HERMES_WEBHOOK_DELIVERIES = store
        body, headers = self.request(delivery="commit-after-admission")
        result = self.invoke(body, headers)
        self.assertTrue(store.admitted)
        self.assertEqual(self.status(result), 202)
        self.assertEqual(server.HERMES_EVENT_REFRESH.pending_count, 1)
        self.assertIn(("webhook_error", "webhook_store_unavailable"), result.responses)

    def test_real_loopback_http_lifecycle_dispatches_and_checks_host(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT": self.secret.decode()}, clear=False):
                body, headers = self.request(delivery="http-delivery")
                connection = HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
                connection.request("POST", "/api/integrations/hermes/webhooks/v1/local-default", body, headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 202)
                response.read()
                connection.close()

                duplicate = HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
                duplicate.request("POST", "/api/integrations/hermes/webhooks/v1/local-default", body, headers)
                duplicate_response = duplicate.getresponse()
                self.assertEqual(duplicate_response.status, 204)
                self.assertEqual(duplicate_response.read(), b"")
                duplicate.close()

                rejected = HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
                rejected.request(
                    "POST",
                    "/api/integrations/hermes/webhooks/v1/local-default",
                    body,
                    {**headers, "Host": "evil.example"},
                )
                rejected_response = rejected.getresponse()
                self.assertEqual(rejected_response.status, 403)
                rejected_response.read()
                rejected.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    def test_rejections_map_to_bounded_statuses(self):
        body, headers = self.request()
        headers["X-Hermes-Signature-256"] = "sha256=" + ("0" * 64)
        self.assertEqual(next(value for kind, value in self.invoke(body, headers).responses if kind == "error"), 401)

        body, headers = self.request(content_type="text/plain")
        self.assertEqual(next(value for kind, value in self.invoke(body, headers).responses if kind == "error"), 415)

        body, headers = self.request(event="unknown")
        self.assertEqual(next(value for kind, value in self.invoke(body, headers).responses if kind == "error"), 400)

        body, headers = self.request(body_overrides={"timestamp": (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()})
        self.assertEqual(next(value for kind, value in self.invoke(body, headers).responses if kind == "error"), 422)

        body, headers = self.request()
        headers["X-Hermes-Delivery"] = "other"
        self.assertEqual(next(value for kind, value in self.invoke(body, headers).responses if kind == "error"), 400)

        oversized = b"x" * (server.HERMES_WEBHOOK_MAX_BODY_BYTES + 1)
        oversized_headers = {"Content-Length": str(len(oversized))}
        self.assertEqual(next(value for kind, value in self.invoke(oversized, oversized_headers).responses if kind == "error"), 413)

        body, headers = self.request()
        headers["Content-Length"] = str(len(body) + 1)
        self.assertEqual(next(value for kind, value in self.invoke(body, headers).responses if kind == "error"), 400)

        class DuplicateContentLengthHeaders(dict):
            def get_all(self, name):
                if name.lower() == "content-length":
                    return [str(len(body)), str(len(body))]
                return [self[name]] if name in self else []

        body, headers = self.request()
        headers["Content-Length"] = str(len(body))
        duplicate_headers = DuplicateContentLengthHeaders(headers)
        self.assertEqual(next(value for kind, value in self.invoke(body, duplicate_headers).responses if kind == "error"), 400)

        body, headers = self.request()
        headers["Transfer-Encoding"] = "chunked"
        self.assertEqual(next(value for kind, value in self.invoke(body, headers).responses if kind == "error"), 400)

        class DuplicateTransferEncodingHeaders(dict):
            def get_all(self, name):
                if name.lower() == "transfer-encoding":
                    return ["", "chunked"]
                return [self[name]] if name in self else []

        body, headers = self.request()
        duplicate_transfer_headers = DuplicateTransferEncodingHeaders(headers)
        self.assertEqual(next(value for kind, value in self.invoke(body, duplicate_transfer_headers).responses if kind == "error"), 400)

        body, headers = self.request()
        headers["Content-Length"] = "-1"
        self.assertEqual(next(value for kind, value in self.invoke(body, headers).responses if kind == "error"), 400)

        body, headers = self.request(body_overrides={"hook_event_name": []})
        self.assertEqual(next(value for kind, value in self.invoke(body, headers).responses if kind == "error"), 400)

        with patch.dict(os.environ, {"MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT": self.secret.decode()}, clear=False):
            alias = _WebhookHandlerHarness(body, headers)
            server.Handler.handle_hermes_webhook(alias, "LOCAL-DEFAULT")
        self.assertEqual(next(value for kind, value in alias.responses if kind == "error"), 404)

    def test_real_loopback_http_rejections_are_bounded(self):
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(os.environ, {"MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT": self.secret.decode()}, clear=False):
                cases = []
                body, headers = self.request(delivery="bad-signature")
                headers["X-Hermes-Signature-256"] = "sha256=" + ("0" * 64)
                cases.append((body, headers, 401))
                body, headers = self.request(delivery="bad-event-header")
                headers["X-Hermes-Event"] = "on_session_start"
                cases.append((body, headers, 400))
                body, headers = self.request(event="unknown", delivery="unknown-event")
                cases.append((body, headers, 400))
                body, headers = self.request(delivery="bad-type", content_type="text/plain")
                cases.append((body, headers, 415))
                body, headers = self.request(
                    delivery="bad-time",
                    body_overrides={"timestamp": (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat()},
                )
                cases.append((body, headers, 422))
                body, headers = self.request(delivery="too-large")
                body = body + (b"x" * (server.HERMES_WEBHOOK_MAX_BODY_BYTES + 1 - len(body)))
                headers["Content-Length"] = str(len(body))
                cases.append((body, headers, 413))

                for body, headers, expected in cases:
                    connection = HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
                    connection.request("POST", "/api/integrations/hermes/webhooks/v1/local-default", body, headers)
                    response = connection.getresponse()
                    self.assertEqual(response.status, expected)
                    self.assertLessEqual(len(response.read()), 512)
                    connection.close()
            self.assertEqual(server.HERMES_EVENT_REFRESH.pending_count, 0)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    def test_queue_saturation_retries_without_deduplicating_delivery(self):
        server.HERMES_WEBHOOK_HINT_CAPACITY = 1
        server.HERMES_EVENT_REFRESH = HermesRefreshCoordinator({}, capacity=1)
        first_body, first_headers = self.request(delivery="first")
        self.assertEqual(self.status(self.invoke(first_body, first_headers)), 202)
        second_body, second_headers = self.request(delivery="second")
        second = self.invoke(second_body, second_headers)
        self.assertEqual(next(value for kind, value in second.responses if kind == "error"), 503)
        server.HERMES_EVENT_REFRESH = HermesRefreshCoordinator({}, capacity=1)
        retried = self.invoke(second_body, second_headers)
        self.assertEqual(self.status(retried), 202)

    def test_unconfigured_binding_is_not_accepted(self):
        body, headers = self.request()
        harness = _WebhookHandlerHarness(body, headers)
        with patch.dict(os.environ, {}, clear=True):
            server.Handler.handle_hermes_webhook(harness, self.binding_id)
        self.assertEqual(next(value for kind, value in harness.responses if kind == "error"), 404)
        self.assertEqual(server.HERMES_EVENT_REFRESH.pending_count, 0)


if __name__ == "__main__":
    unittest.main()
