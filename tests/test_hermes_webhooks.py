import hashlib
import hmac
import io
import json
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone

from hermes_webhooks import ALLOWED_EVENTS, PerBindingRateLimiter, WebhookBinding, WebhookValidationError, verify_and_normalize
from scripts.hermes_webhook_live_validation import _parse_args


class HermesWebhookLiveQualificationTests(unittest.TestCase):
    def test_legacy_runtime_is_required_for_qualification(self):
        required = ["--hermes-source", "stock", "--hermes-python", "python"]
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                _parse_args(required)
        self.assertEqual(raised.exception.code, 2)

        args = _parse_args([*required, "--legacy-hermes", "legacy-hermes"])
        self.assertEqual(str(args.legacy_hermes), "legacy-hermes")


class HermesWebhookTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        self.binding = WebhookBinding("local-default", b"test-secret")

    def request(self, payload, *, event="on_session_end", delivery="delivery-1"):
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(self.binding.secret, body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Hermes-Signature-256": "sha256=" + signature,
            "X-Hermes-Event": event,
            "X-Hermes-Delivery": delivery,
        }
        return body, headers

    def payload(self, **overrides):
        value = {"hook_event_name": "on_session_end", "delivery_id": "delivery-1", "timestamp": self.now.isoformat()}
        value.update(overrides)
        return value

    def test_verifies_raw_body_and_normalizes_only_routing_envelope(self):
        body, headers = self.request(self.payload(completed=True, platform="cli", ignored={"secret": "no"}))
        event = verify_and_normalize(body, headers, self.binding, now=self.now)
        self.assertEqual(event.event_name, "on_session_end")
        self.assertEqual(len(event.delivery_digest), 64)
        self.assertEqual(
            set(vars(event)),
            {"binding_id", "event_name", "delivery_digest", "occurred_at", "received_at"},
        )

    def test_every_native_event_is_explicitly_allowlisted_and_payload_minimized(self):
        expected = {
            "on_session_start", "on_session_end", "on_session_finalize",
            "on_session_reset", "subagent_start", "subagent_stop",
            "post_api_request", "api_request_error", "post_tool_call",
            "kanban_task_claimed", "kanban_task_completed",
            "kanban_task_blocked", "on_kanban_worker_spawned",
            "on_kanban_worker_exited", "on_kanban_worker_stale_claim",
            "on_kanban_task_updated", "on_kanban_dispatch_tick",
        }
        self.assertEqual(ALLOWED_EVENTS, frozenset(expected))
        private_values = {
            "prompt": "POISON_PROMPT",
            "args": {"token": "POISON_ARGUMENT"},
            "result": "POISON_RESULT",
            "summary": "POISON_SUMMARY",
            "reason": "POISON_REASON",
            "workspace_path": "/POISON/PATH",
            "model": "POISON_MODEL",
            "usage": {"total_tokens": 999},
        }
        for index, event_name in enumerate(sorted(expected)):
            with self.subTest(event_name=event_name):
                delivery = f"native-{index}"
                body, headers = self.request(
                    self.payload(
                        hook_event_name=event_name,
                        delivery_id=delivery,
                        tool_input=private_values["args"],
                        cwd=private_values["workspace_path"],
                        completed=True,
                        interrupted=False,
                        platform="cli",
                        extra={
                            **private_values,
                            "completed": True,
                            "interrupted": False,
                            "platform": "gateway",
                        },
                    ),
                    event=event_name,
                    delivery=delivery,
                )
                normalized = verify_and_normalize(body, headers, self.binding, now=self.now)
                self.assertEqual(
                    set(vars(normalized)),
                    {
                        "binding_id", "event_name", "delivery_digest",
                        "occurred_at", "received_at",
                    },
                )
                rendered = repr(normalized)
                for poison in ("POISON_PROMPT", "POISON_ARGUMENT", "POISON_RESULT",
                               "POISON_SUMMARY", "POISON_REASON", "/POISON/PATH",
                               "POISON_MODEL", "total_tokens"):
                    self.assertNotIn(poison, rendered)

    def test_discards_stock_020_lifecycle_fields_from_top_level_and_extra(self):
        body, headers = self.request(
            self.payload(
                completed=False,
                interrupted=True,
                platform="cli",
                extra={
                    "completed": True,
                    "interrupted": False,
                    "platform": "gateway",
                    "child_summary": "must not be retained",
                }
            )
        )
        event = verify_and_normalize(body, headers, self.binding, now=self.now)
        for field in ("completed", "interrupted", "platform", "child_summary"):
            self.assertFalse(hasattr(event, field))
            self.assertNotIn(field, repr(event))

    def test_duplicate_security_headers_fail_closed(self):
        class DuplicateHeaders(dict):
            def get_all(self, name):
                if name == "X-Hermes-Delivery":
                    return [self[name], "different"]
                return [self[name]] if name in self else []

        body, headers = self.request(self.payload())
        duplicate_headers = DuplicateHeaders(headers)
        with self.assertRaisesRegex(WebhookValidationError, "duplicate_header"):
            verify_and_normalize(body, duplicate_headers, self.binding, now=self.now)

    def test_rejects_tampering_after_signature_creation(self):
        body, headers = self.request(self.payload())
        with self.assertRaisesRegex(WebhookValidationError, "invalid_signature"):
            verify_and_normalize(body + b" ", headers, self.binding, now=self.now)

    def test_rejects_header_body_mismatch(self):
        body, headers = self.request(self.payload())
        headers["X-Hermes-Delivery"] = "other"
        with self.assertRaisesRegex(WebhookValidationError, "delivery_header_mismatch"):
            verify_and_normalize(body, headers, self.binding, now=self.now)

    def test_rejects_stale_events_and_unknown_events(self):
        body, headers = self.request(self.payload(timestamp=(self.now - timedelta(minutes=6)).isoformat()))
        with self.assertRaisesRegex(WebhookValidationError, "stale_timestamp"):
            verify_and_normalize(body, headers, self.binding, now=self.now)
        body, headers = self.request(self.payload(hook_event_name="made_up"), event="made_up")
        with self.assertRaisesRegex(WebhookValidationError, "unsupported_event"):
            verify_and_normalize(body, headers, self.binding, now=self.now)

        body, headers = self.request(self.payload(timestamp="2026-08-10T13:00:00+01:00"))
        with self.assertRaisesRegex(WebhookValidationError, "invalid_timestamp"):
            verify_and_normalize(body, headers, self.binding, now=self.now)

    def test_per_binding_rate_limiter_is_bounded_and_refills(self):
        now = [100.0]
        limiter = PerBindingRateLimiter(
            capacity=2,
            refill_per_second=1,
            clock=lambda: now[0],
        )
        self.assertTrue(limiter.allow("first"))
        self.assertTrue(limiter.allow("first"))
        self.assertFalse(limiter.allow("first"))
        self.assertTrue(limiter.allow("second"))
        now[0] += 1
        self.assertTrue(limiter.allow("first"))
        self.assertFalse(limiter.allow("first"))

    def test_one_thousand_event_storm_is_bounded_per_binding(self):
        limiter = PerBindingRateLimiter(
            capacity=120,
            refill_per_second=2,
            clock=lambda: 100.0,
        )
        outcomes = [limiter.allow("local-default") for _ in range(1_000)]
        self.assertEqual(outcomes.count(True), 120)
        self.assertEqual(outcomes.count(False), 880)
        self.assertEqual(set(limiter._buckets), {"local-default"})

    def test_rate_limiter_rejects_invalid_configuration(self):
        with self.assertRaises(ValueError):
            PerBindingRateLimiter(capacity=0)
        with self.assertRaises(ValueError):
            PerBindingRateLimiter(refill_per_second=0)


if __name__ == "__main__":
    unittest.main()
