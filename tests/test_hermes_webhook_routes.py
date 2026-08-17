import hashlib
import hmac
import io
import json
import os
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from http.client import HTTPConnection
from threading import Thread

import server
from hermes_event_refresh import HermesRefreshCoordinator
from hermes_webhooks import WebhookDeliveryCache


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


class HermesWebhookRouteTests(unittest.TestCase):
    binding_id = "local-default"
    secret = b"route-secret"

    def setUp(self):
        self.original_cache = server.HERMES_WEBHOOK_DELIVERIES
        self.original_coordinator = server.HERMES_EVENT_REFRESH
        self.original_capacity = server.HERMES_WEBHOOK_HINT_CAPACITY
        server.HERMES_WEBHOOK_DELIVERIES = WebhookDeliveryCache(capacity=16)
        server.HERMES_EVENT_REFRESH = HermesRefreshCoordinator({}, capacity=16)

    def tearDown(self):
        if server.HERMES_EVENT_REFRESH is not None:
            server.HERMES_EVENT_REFRESH.stop(timeout=1)
        server.HERMES_WEBHOOK_DELIVERIES = self.original_cache
        server.HERMES_EVENT_REFRESH = self.original_coordinator
        server.HERMES_WEBHOOK_HINT_CAPACITY = self.original_capacity

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

        def slow_refresh(_binding):
            entered.set()
            release.wait(2)
            return {"sessions": []}

        server.HERMES_EVENT_REFRESH = HermesRefreshCoordinator(
            {"sessions": slow_refresh},
            coalesce_window=0,
            reconciliation_interval=60,
        )
        server.HERMES_EVENT_REFRESH.start()
        body, headers = self.request(delivery="slow-adapter")
        started = time.monotonic()
        harness = self.invoke(body, headers)
        elapsed = time.monotonic() - started
        self.assertEqual(self.status(harness), 202)
        self.assertLess(elapsed, 0.1)
        self.assertTrue(entered.wait(1))
        release.set()
        self.assertTrue(server.HERMES_EVENT_REFRESH.wait_idle(1))

    def test_duplicate_delivery_returns_no_content_and_is_not_requeued(self):
        body, headers = self.request()
        self.assertEqual(self.status(self.invoke(body, headers)), 202)
        duplicate = self.invoke(body, headers)
        self.assertEqual(self.status(duplicate), 204)
        self.assertEqual(server.HERMES_EVENT_REFRESH.pending_count, 1)

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
