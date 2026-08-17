import http.client
import io
import json
import threading
import time
import unittest
from unittest.mock import patch

import server
from hermes_browser_events import ALLOWED_PROJECTIONS, HermesBrowserEventBroker


class HermesBrowserEventBrokerTests(unittest.TestCase):
    def test_publish_exposes_only_fixed_projection_names(self):
        broker = HermesBrowserEventBroker()
        self.assertEqual(
            broker.publish("private-binding", {"sessions", "kanban", "private"}),
            1,
        )
        event = broker.wait_after(0, timeout=0)
        self.assertEqual(event.projections, ("kanban", "sessions"))
        payload = event.public_payload()
        self.assertEqual(
            set(payload),
            {"schema_version", "sequence", "generated_at", "projections"},
        )
        self.assertNotIn("binding", repr(payload))
        self.assertNotIn("private", repr(payload))

    def test_reconnect_coalesces_history_and_overflow_forces_full_refresh(self):
        broker = HermesBrowserEventBroker(history_size=2)
        broker.publish("one", {"sessions"})
        broker.publish("one", {"agents"})
        broker.publish("one", {"kanban"})
        overflow = broker.wait_after(0, timeout=0)
        self.assertEqual(overflow.projections, tuple(sorted(ALLOWED_PROJECTIONS)))
        recent = broker.wait_after(1, timeout=0)
        self.assertEqual(recent.projections, ("agents", "kanban"))
        self.assertEqual(recent.sequence, 3)

    def test_wait_wakes_after_publish_and_times_out_without_data(self):
        broker = HermesBrowserEventBroker()
        result = []
        waiter = threading.Thread(
            target=lambda: result.append(broker.wait_after(0, timeout=1)),
            daemon=True,
        )
        waiter.start()
        time.sleep(0.02)
        broker.publish("one", {"attention"})
        waiter.join(1)
        self.assertEqual(result[0].projections, ("attention",))
        self.assertIsNone(broker.wait_after(1, timeout=0.01))

    def test_cursor_ahead_after_process_restart_forces_full_projection_reset(self):
        broker = HermesBrowserEventBroker()
        reset = broker.wait_after(47, timeout=0)
        self.assertEqual(reset.sequence, 0)
        self.assertEqual(reset.projections, tuple(sorted(ALLOWED_PROJECTIONS)))
        broker.publish("local-default", {"kanban"})
        resumed = broker.wait_after(reset.sequence, timeout=0)
        self.assertEqual(resumed.sequence, 1)
        self.assertEqual(resumed.projections, ("kanban",))

    def test_client_count_is_bounded_and_release_is_idempotent(self):
        broker = HermesBrowserEventBroker(max_clients=1)
        self.assertTrue(broker.acquire_client())
        self.assertFalse(broker.acquire_client())
        broker.release_client()
        broker.release_client()
        self.assertEqual(broker.active_clients, 0)
        self.assertTrue(broker.acquire_client())


class _StreamHarness:
    def __init__(self, headers=None):
        self.headers = headers or {"Accept": "text/event-stream"}
        self.wfile = io.BytesIO()
        self.responses = []
        self.close_connection = False

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


class HermesBrowserEventRouteTests(unittest.TestCase):
    def test_live_loopback_stream_admits_resets_delivers_and_releases(self):
        broker = HermesBrowserEventBroker(max_clients=1)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            rejected = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            rejected.request(
                "GET",
                "/api/hermes/events",
                headers={
                    "Accept": "text/event-stream",
                    "Origin": "http://example.invalid",
                },
            )
            rejected_response = rejected.getresponse()
            self.assertEqual(rejected_response.status, 403)
            rejected_response.read()
            rejected.close()

            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            with patch("server.HERMES_BROWSER_EVENTS", broker):
                connection.request(
                    "GET",
                    "/api/hermes/events",
                    headers={
                        "Accept": "text/event-stream",
                        "Last-Event-ID": "47",
                        "Origin": f"http://127.0.0.1:{port}",
                    },
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                lines = [response.fp.readline().decode("utf-8") for _ in range(6)]
                self.assertEqual(lines[:2], [": connected\n", "\n"])
                self.assertEqual(lines[2], "id: 0\n")
                self.assertEqual(lines[3], "event: projections\n")
                payload = json.loads(lines[4].removeprefix("data: "))
                self.assertEqual(payload["projections"], sorted(ALLOWED_PROJECTIONS))
                self.assertEqual(lines[5], "\n")
                self.assertEqual(broker.active_clients, 1)
                response.close()
                connection.close()

                # Wake the handler after the peer closes so its next write
                # observes the disconnect and releases the bounded slot.
                deadline = time.monotonic() + 2
                while broker.active_clients and time.monotonic() < deadline:
                    broker.publish("local-default", {"sessions"})
                    time.sleep(0.02)
                self.assertEqual(broker.active_clients, 0)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(2)

    def test_stream_frame_has_fixed_event_contract_and_security_headers(self):
        broker = HermesBrowserEventBroker()
        broker.publish("secret-binding", {"sessions", "private"})
        harness = _StreamHarness()
        with patch("server.HERMES_BROWSER_EVENTS", broker):
            server.Handler.send_hermes_browser_events(harness, max_frames=1)
        self.assertIn(("status", 200), harness.responses)
        self.assertIn(("Content-Type", "text/event-stream; charset=utf-8"), harness.responses)
        self.assertIn(("Cache-Control", "no-store"), harness.responses)
        frame = harness.wfile.getvalue().decode("utf-8")
        self.assertTrue(frame.startswith(": connected\n\n"))
        self.assertIn("event: projections", frame)
        payload = json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
        self.assertEqual(payload["projections"], ["sessions"])
        self.assertNotIn("secret-binding", frame)
        self.assertNotIn("private", frame)
        self.assertEqual(broker.active_clients, 0)

    def test_stream_rejects_wrong_accept_and_invalid_cursor(self):
        wrong_accept = _StreamHarness({"Accept": "application/json"})
        server.Handler.send_hermes_browser_events(wrong_accept, max_frames=1)
        self.assertIn(("error", 406), wrong_accept.responses)

        bad_cursor = _StreamHarness(
            {"Accept": "text/event-stream", "Last-Event-ID": "private"}
        )
        server.Handler.send_hermes_browser_events(bad_cursor, max_frames=1)
        self.assertIn(("error", 400), bad_cursor.responses)

    def test_stream_returns_retryable_busy_without_exceeding_client_cap(self):
        broker = HermesBrowserEventBroker(max_clients=1)
        self.assertTrue(broker.acquire_client())
        harness = _StreamHarness()
        with patch("server.HERMES_BROWSER_EVENTS", broker):
            server.Handler.send_hermes_browser_events(harness, max_frames=1)
        self.assertIn(("status", 503), harness.responses)
        self.assertIn(("Retry-After", "5"), harness.responses)
        self.assertEqual(broker.active_clients, 1)
        broker.release_client()


if __name__ == "__main__":
    unittest.main()
