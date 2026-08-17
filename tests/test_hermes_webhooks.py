import hashlib
import hmac
import json
import unittest
from datetime import datetime, timedelta, timezone

from hermes_webhooks import WebhookBinding, WebhookDeliveryCache, WebhookValidationError, verify_and_normalize


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

    def test_verifies_raw_body_and_normalizes_allowlisted_fields(self):
        body, headers = self.request(self.payload(completed=True, platform="cli", ignored={"secret": "no"}))
        event = verify_and_normalize(body, headers, self.binding, now=self.now)
        self.assertEqual(event.event_name, "on_session_end")
        self.assertTrue(event.completed)
        self.assertEqual(event.platform, "cli")
        self.assertEqual(len(event.delivery_digest), 64)

    def test_platform_is_bounded_and_normalized(self):
        body, headers = self.request(self.payload(platform="unexpected-platform"))
        event = verify_and_normalize(body, headers, self.binding, now=self.now)
        self.assertEqual(event.platform, "other")
        body, headers = self.request(self.payload(platform="x" * 10_000))
        event = verify_and_normalize(body, headers, self.binding, now=self.now)
        self.assertEqual(event.platform, "other")

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

    def test_delivery_cache_deduplicates_and_bounds_hints(self):
        body, headers = self.request(self.payload())
        event = verify_and_normalize(body, headers, self.binding, now=self.now)
        cache = WebhookDeliveryCache(capacity=1)
        self.assertTrue(cache.remember(event))
        self.assertFalse(cache.remember(event))

        bounded = WebhookDeliveryCache(capacity=2)
        events = []
        for delivery in ("one", "two", "three"):
            body, headers = self.request(self.payload(delivery_id=delivery), delivery=delivery)
            events.append(verify_and_normalize(body, headers, self.binding, now=self.now))
        for event in events:
            bounded.remember(event)
        self.assertEqual(len(bounded._items), 2)
        self.assertFalse(bounded.contains(events[0]))


if __name__ == "__main__":
    unittest.main()
