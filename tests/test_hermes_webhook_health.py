from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
import json
import os
import threading
import unittest
from unittest.mock import patch

import server
from hermes_event_refresh import HermesRefreshCoordinator
from hermes_webhook_health import (
    MAX_RECONCILIATION_AGE_SECONDS,
    MAX_PUBLIC_AGE_SECONDS,
    MAX_PUBLIC_COUNTER,
    RECENT_EVENT_SECONDS,
    build_probe_request,
    public_health_payload,
)
from hermes_webhooks import WebhookBinding, verify_and_normalize


NOW = datetime(2026, 8, 14, 20, 0, tzinfo=timezone.utc)


def health_record(**overrides):
    record = {
        "accepted_hint_count": 0,
        "coalesced_hint_count": 0,
        "queue_drop_count": 0,
        "unresolved_drop_count": 0,
        "refresh_success_count": 0,
        "refresh_failure_count": 0,
        "degraded_projection_count": 0,
        "backoff_skip_count": 0,
        "reconciliation_count": 0,
        "last_event_name": None,
        "last_event_at": None,
        "last_refresh_at": None,
        "last_reconciled_at": None,
        "last_error_code": None,
        "coordinator_started_at": NOW.isoformat(),
    }
    record.update(overrides)
    return record


class HermesWebhookHealthTests(unittest.TestCase):
    def setUp(self):
        self.original_coordinator = server.HERMES_EVENT_REFRESH
        self.original_deliveries = server.HERMES_WEBHOOK_DELIVERIES
        self.original_port = server.PORT
        self.original_host = server.HOST
        server.HERMES_WEBHOOK_DELIVERIES = server.WebhookDeliveryCache(capacity=32)

    def install_coordinator(self):
        coordinator = HermesRefreshCoordinator({}, binding_ids=("local-default",))
        coordinator.start()
        server.HERMES_EVENT_REFRESH = coordinator
        return coordinator

    def tearDown(self):
        coordinator = server.HERMES_EVENT_REFRESH
        if coordinator is not None and coordinator is not self.original_coordinator:
            coordinator.stop(timeout=1)
        server.HERMES_EVENT_REFRESH = self.original_coordinator
        server.HERMES_WEBHOOK_DELIVERIES = self.original_deliveries
        server.PORT = self.original_port
        server.HOST = self.original_host

    def test_public_health_state_matrix(self):
        off = public_health_payload(configured=False, coordinator_available=False, snapshot=None, now=NOW)
        self.assertEqual(off["state"], "off")
        self.assertFalse(off["probe_available"])

        ready = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(),
            now=NOW,
        )
        self.assertEqual(ready["state"], "ready")
        self.assertTrue(ready["probe_available"])

        receiving = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(
                accepted_hint_count=2,
                refresh_success_count=1,
                reconciliation_count=1,
                last_event_name="on_session_start",
                last_event_at=(NOW - timedelta(seconds=8)).isoformat(),
                last_refresh_at=(NOW - timedelta(seconds=5)).isoformat(),
                last_reconciled_at=(NOW - timedelta(seconds=3)).isoformat(),
            ),
            now=NOW,
        )
        self.assertEqual(receiving["state"], "receiving")
        self.assertEqual(receiving["ages_seconds"]["last_event"], 8)

        degraded = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(
                accepted_hint_count=1,
                last_event_name="on_session_start",
                degraded_projection_count=1,
                last_error_code="webhook_refresh_failed",
                last_event_at=NOW.isoformat(),
            ),
            now=NOW,
        )
        self.assertEqual(degraded["state"], "degraded")
        self.assertTrue(degraded["probe_available"])

    def test_public_health_requires_complete_fresh_fail_closed_evidence(self):
        for partial in ({}, {"accepted_hint_count": 0}, {"last_error_code": None}):
            with self.subTest(partial=partial):
                payload = public_health_payload(
                    configured=True,
                    coordinator_available=True,
                    snapshot=partial,
                    now=NOW,
                )
                self.assertEqual(payload["state"], "degraded")

        dropped = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(queue_drop_count=1, unresolved_drop_count=1),
            now=NOW,
        )
        self.assertEqual(dropped["state"], "degraded")

        repaired_drop = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(
                queue_drop_count=1,
                unresolved_drop_count=0,
                reconciliation_count=1,
                last_reconciled_at=(NOW - timedelta(seconds=1)).isoformat(),
            ),
            now=NOW,
        )
        self.assertEqual(repaired_drop["state"], "ready")

        stale = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(
                accepted_hint_count=1,
                last_event_name="on_session_end",
                last_event_at=(NOW - timedelta(seconds=RECENT_EVENT_SECONDS + 1)).isoformat(),
                reconciliation_count=1,
                last_reconciled_at=(
                    NOW - timedelta(seconds=MAX_RECONCILIATION_AGE_SECONDS + 1)
                ).isoformat(),
            ),
            now=NOW,
        )
        self.assertEqual(stale["state"], "degraded")

        old_but_reconciled = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(
                accepted_hint_count=1,
                last_event_name="on_session_end",
                last_event_at=(NOW - timedelta(seconds=RECENT_EVENT_SECONDS + 1)).isoformat(),
                reconciliation_count=1,
                last_reconciled_at=(NOW - timedelta(seconds=10)).isoformat(),
            ),
            now=NOW,
        )
        self.assertEqual(old_but_reconciled["state"], "ready")

        stopped = public_health_payload(
            configured=True,
            coordinator_available=False,
            snapshot=health_record(),
            now=NOW,
        )
        self.assertEqual(stopped["state"], "degraded")
        self.assertFalse(stopped["probe_available"])

    def test_public_health_rejects_inconsistent_snapshot_invariants(self):
        inconsistent = (
            health_record(last_event_at=NOW.isoformat()),
            health_record(reconciliation_count=1),
            health_record(last_reconciled_at=NOW.isoformat()),
            health_record(refresh_success_count=1),
            health_record(last_refresh_at=NOW.isoformat()),
            health_record(accepted_hint_count=1, last_event_name="on_session_start"),
            health_record(coalesced_hint_count=1),
            health_record(degraded_projection_count=1),
            health_record(last_error_code="webhook_refresh_failed"),
            health_record(queue_drop_count=0, unresolved_drop_count=1),
            health_record(
                accepted_hint_count=MAX_PUBLIC_COUNTER + 1,
                coalesced_hint_count=MAX_PUBLIC_COUNTER + 2,
                last_event_name="on_session_start",
                last_event_at=NOW.isoformat(),
            ),
        )
        for snapshot in inconsistent:
            with self.subTest(snapshot=snapshot):
                payload = public_health_payload(
                    configured=True,
                    coordinator_available=True,
                    snapshot=snapshot,
                    now=NOW,
                )
                self.assertEqual(payload["state"], "degraded")

    def test_missing_reconciliation_degrades_at_its_own_deadline(self):
        at_limit = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(
                accepted_hint_count=1,
                last_event_name="on_session_start",
                last_event_at=(NOW - timedelta(seconds=MAX_RECONCILIATION_AGE_SECONDS)).isoformat(),
                coordinator_started_at=(NOW - timedelta(seconds=MAX_RECONCILIATION_AGE_SECONDS)).isoformat(),
            ),
            now=NOW,
        )
        self.assertEqual(at_limit["state"], "receiving")
        overdue = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(
                accepted_hint_count=1,
                last_event_name="on_session_start",
                last_event_at=(NOW - timedelta(seconds=MAX_RECONCILIATION_AGE_SECONDS + 1)).isoformat(),
                coordinator_started_at=(NOW - timedelta(seconds=MAX_RECONCILIATION_AGE_SECONDS + 1)).isoformat(),
            ),
            now=NOW,
        )
        self.assertEqual(overdue["state"], "degraded")

    def test_extreme_timezone_ages_fail_closed_without_raising(self):
        for timestamp in ("0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"):
            with self.subTest(timestamp=timestamp):
                payload = public_health_payload(
                    configured=True,
                    coordinator_available=True,
                    snapshot=health_record(coordinator_started_at=timestamp),
                    now=NOW,
                )
                self.assertEqual(payload["state"], "degraded")

    def test_public_health_clamps_values_and_fails_closed_on_malformed_state(self):
        payload = public_health_payload(
            configured=True,
            coordinator_available=True,
            snapshot=health_record(
                accepted_hint_count=MAX_PUBLIC_COUNTER + 50,
                queue_drop_count=-1,
                last_event_at=(NOW - timedelta(days=90)).isoformat(),
                last_refresh_at="private/path/that-must-not-escape",
            ),
            now=NOW,
        )
        self.assertEqual(payload["state"], "degraded")
        self.assertEqual(payload["counters"]["accepted"], MAX_PUBLIC_COUNTER)
        self.assertEqual(payload["counters"]["dropped"], 0)
        self.assertEqual(payload["ages_seconds"]["last_event"], MAX_PUBLIC_AGE_SECONDS)
        self.assertIsNone(payload["ages_seconds"]["last_refresh"])
        serialized = json.dumps(payload)
        self.assertNotIn("private/path", serialized)
        self.assertNotIn("last_error_code", serialized)
        self.assertNotIn("last_event_name", serialized)

    def test_probe_request_passes_the_real_verifier_without_private_output(self):
        secret = b"probe-secret-value"
        body, headers = build_probe_request(
            secret,
            delivery_id="mentat-probe-public-test",
            now=NOW,
        )
        event = verify_and_normalize(
            body,
            headers,
            WebhookBinding("local-default", secret),
            now=NOW,
        )
        self.assertEqual(event.event_name, "on_session_start")
        self.assertEqual(headers["Content-Length"], str(len(body)))
        serialized_headers = json.dumps(headers)
        self.assertNotIn(secret.decode(), serialized_headers)

    def test_server_health_payload_never_returns_secret_reference_or_private_keys(self):
        self.install_coordinator()
        secret_name = server.HERMES_WEBHOOK_SECRET_ENV_BY_BINDING["local-default"]
        with patch.dict(os.environ, {secret_name: "private-value"}, clear=False):
            payload = server.hermes_webhook_health_payload()
        serialized = json.dumps(payload)
        self.assertEqual(payload["state"], "ready")
        self.assertEqual(payload["target_path"], "/api/integrations/hermes/webhooks/v1/local-default")
        for forbidden in (
            "private-value",
            secret_name,
            "signature",
            "delivery_id",
            "session_id",
            "payload",
            "profile",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_probe_is_rejected_safely_when_receiver_is_off(self):
        self.install_coordinator()
        with patch.dict(os.environ, {}, clear=True):
            payload, status = server.run_hermes_webhook_probe(8888)
        self.assertEqual(status, 409)
        self.assertEqual(payload, {"error": "webhook_receiver_off"})

    def test_signed_probe_traverses_the_real_loopback_receiver(self):
        self.install_coordinator()
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        server.PORT = httpd.server_port
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        secret_name = server.HERMES_WEBHOOK_SECRET_ENV_BY_BINDING["local-default"]
        try:
            with patch.dict(os.environ, {secret_name: "private-probe-secret"}, clear=False):
                payload, status = server.run_hermes_webhook_probe(httpd.server_port)
                self.assertEqual(status, 200)
                self.assertEqual(payload, {"ok": True, "result": "webhook_probe_accepted"})
                health = server.hermes_webhook_health_payload()
            self.assertEqual(health["state"], "receiving")
            self.assertEqual(health["counters"]["accepted"], 1)
            self.assertNotIn("private-probe-secret", json.dumps(payload))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    def test_signed_probe_targets_an_ipv6_bound_receiver(self):
        self.install_coordinator()
        server.HOST = "::1"
        try:
            httpd = server.IPv6ThreadingHTTPServer(("::1", 0), server.Handler)
        except OSError as exc:
            self.skipTest(f"IPv6 loopback unavailable: {type(exc).__name__}")
        server.PORT = httpd.server_port
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        secret_name = server.HERMES_WEBHOOK_SECRET_ENV_BY_BINDING["local-default"]
        try:
            with patch.dict(os.environ, {secret_name: "private-ipv6-probe"}, clear=False):
                payload, status = server.run_hermes_webhook_probe(httpd.server_port)
            self.assertEqual(status, 200)
            self.assertEqual(payload, {"ok": True, "result": "webhook_probe_accepted"})
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    def test_browser_probe_route_uses_fixed_empty_payload_contract(self):
        with patch.object(
            server,
            "run_hermes_webhook_probe",
            return_value=({"ok": True, "result": "webhook_probe_accepted"}, 200),
        ) as probe:
            payload, status = server.handle_post_route("/api/hermes/webhooks/probe", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        probe.assert_called_once_with(server.PORT)

        payload, status = server.handle_post_route(
            "/api/hermes/webhooks/probe",
            {"secret": "must-not-be-accepted"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload, {"error": "webhook_probe_payload_invalid"})

    def test_live_browser_probe_route_preserves_same_origin_boundary(self):
        self.install_coordinator()
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        server.PORT = httpd.server_port
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        secret_name = server.HERMES_WEBHOOK_SECRET_ENV_BY_BINDING["local-default"]
        try:
            with patch.dict(os.environ, {secret_name: "private-browser-probe"}, clear=False):
                connection = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
                body = b"{}"
                connection.request(
                    "POST",
                    "/api/hermes/webhooks/probe",
                    body,
                    {
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body)),
                        "Origin": f"http://127.0.0.1:{httpd.server_port}",
                        "Sec-Fetch-Site": "same-origin",
                    },
                )
                response = connection.getresponse()
                payload = json.loads(response.read())
                connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(payload, {"ok": True, "result": "webhook_probe_accepted"})
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)

    def test_live_health_get_has_an_exact_private_free_schema(self):
        self.install_coordinator()
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        server.PORT = httpd.server_port
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        secret_name = server.HERMES_WEBHOOK_SECRET_ENV_BY_BINDING["local-default"]
        try:
            with patch.dict(os.environ, {secret_name: "private-health-get"}, clear=False):
                connection = HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
                connection.request(
                    "GET",
                    "/api/hermes/webhooks/health",
                    headers={
                        "Origin": f"http://127.0.0.1:{httpd.server_port}",
                        "Sec-Fetch-Site": "same-origin",
                    },
                )
                response = connection.getresponse()
                payload = json.loads(response.read())
                headers = dict(response.getheaders())
                connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertSetEqual(
                set(payload),
                {
                    "schema_version",
                    "state",
                    "state_label",
                    "summary",
                    "probe_available",
                    "target_path",
                    "events",
                    "ages_seconds",
                    "counters",
                },
            )
            self.assertSetEqual(
                set(payload["ages_seconds"]),
                {"last_event", "last_refresh", "last_reconciliation"},
            )
            self.assertSetEqual(
                set(payload["counters"]),
                {
                    "accepted",
                    "coalesced",
                    "dropped",
                    "refresh_successes",
                    "refresh_failures",
                    "degraded_projections",
                    "reconciliations",
                },
            )
            serialized = json.dumps(payload)
            for forbidden in ("private-health-get", secret_name, "delivery_id", "session_id"):
                self.assertNotIn(forbidden, serialized)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
