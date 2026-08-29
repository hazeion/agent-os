from __future__ import annotations

from http.client import HTTPConnection
import json
import threading
import unittest
from unittest.mock import patch

from mentat import local_bridge


TOKEN = "bridge-token-that-is-long-enough-for-256-bits-of-entropy"
CONVERSATION_ID = "conv_preview"
MESSAGE_ID = "msg_preview"


def ready_payload():
    return {
        "schema_version": 1,
        "conversation_id": CONVERSATION_ID,
        "message_id": MESSAGE_ID,
        "message_revision": 2,
        "enabled": True,
        "previews": [
            {
                "candidate_ordinal": 1,
                "status": "ready",
                "title": "Safe title",
                "description": "Safe description",
                "site_name": "Python",
                "display_host": "python.org",
                "image_alt": "Preview",
                "image_id": "a" * 32,
            },
            {"candidate_ordinal": 2, "status": "blocked"},
        ],
    }


class LinkPreviewBridgeTests(unittest.TestCase):
    def setUp(self):
        self.server = local_bridge.build_bridge_server("127.0.0.1", 0, TOKEN)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = int(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method: str, path: str, body: object | None = None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}", local_bridge.BRIDGE_TOKEN_HEADER: TOKEN}
        encoded = None
        if body is not None:
            encoded = json.dumps(body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(encoded))
        try:
            connection.request(method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            data = response.read()
            return response.status, data, {name: value for name, value in response.getheaders()}
        finally:
            connection.close()

    def test_projection_is_exact_bounded_and_private_field_free(self):
        projected = local_bridge._ready_link_preview_payload(ready_payload())
        self.assertEqual(projected, ready_payload())
        self.assertNotIn("url", json.dumps(projected))
        self.assertNotIn("path", json.dumps(projected))
        malformed = ready_payload()
        malformed["previews"][0]["raw_html"] = "<secret>"
        with self.assertRaises(local_bridge.BridgeLinkPreviewProjectionError):
            local_bridge._ready_link_preview_payload(malformed)
        malformed = ready_payload()
        malformed["previews"][0]["title"] = "unsafe\u202e"
        with self.assertRaises(local_bridge.BridgeLinkPreviewProjectionError):
            local_bridge._ready_link_preview_payload(malformed)
        malformed = ready_payload()
        malformed["previews"].reverse()
        with self.assertRaises(local_bridge.BridgeLinkPreviewProjectionError):
            local_bridge._ready_link_preview_payload(malformed)
        ipv6 = ready_payload()
        ipv6["previews"][0]["display_host"] = "2606:4700:4700::1111"
        self.assertEqual(local_bridge._ready_link_preview_payload(ipv6)["previews"][0]["display_host"], "2606:4700:4700::1111")
        private_ipv6 = ready_payload()
        private_ipv6["previews"][0]["display_host"] = "fd00::1"
        with self.assertRaises(local_bridge.BridgeLinkPreviewProjectionError):
            local_bridge._ready_link_preview_payload(private_ipv6)

    def test_fixed_read_enqueue_retry_preference_and_clear_routes(self):
        preview_path = f"/bridge/v1/conversations/{CONVERSATION_ID}/messages/{MESSAGE_ID}/link-previews"
        wrapped = {**ready_payload(), "service": "mentat-local-bridge", "runtime": "python", "status": "ready"}
        with patch.object(local_bridge, "bridge_link_previews_payload", return_value=(wrapped, 200)) as read:
            status, body, _headers = self.request("GET", preview_path + "?revision=2")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), wrapped)
        read.assert_called_once_with(CONVERSATION_ID, MESSAGE_ID, 2)

        with patch.object(local_bridge, "bridge_link_previews_payload", return_value=(wrapped, 202)) as enqueue:
            status, _body, _headers = self.request("POST", preview_path, {"message_revision": 2, "action": "enqueue"})
        self.assertEqual(status, 202)
        enqueue.assert_called_once_with(CONVERSATION_ID, MESSAGE_ID, 2, action="enqueue")

        preference = {"schema_version": 1, "enabled": False, "revision": 2, "service": "mentat-local-bridge", "runtime": "python", "status": "ready"}
        with patch.object(local_bridge, "bridge_link_preview_preference_payload", return_value=(preference, 200)) as mutation:
            status, _body, _headers = self.request("POST", local_bridge.BRIDGE_LINK_PREVIEW_PREFERENCE_PATH, {"enabled": False, "expected_revision": 1})
        self.assertEqual(status, 200)
        mutation.assert_called_once_with({"enabled": False, "expected_revision": 1})

        cleared = {"schema_version": 1, "cleared": True, "service": "mentat-local-bridge", "runtime": "python", "status": "ready"}
        with patch.object(local_bridge, "bridge_clear_link_preview_cache", return_value=(cleared, 200)):
            status, _body, _headers = self.request("POST", local_bridge.BRIDGE_LINK_PREVIEW_CACHE_CLEAR_PATH, {})
        self.assertEqual(status, 200)

    def test_routes_reject_queries_extra_fields_and_browser_selected_urls(self):
        path = f"/bridge/v1/conversations/{CONVERSATION_ID}/messages/{MESSAGE_ID}/link-previews"
        cases = (
            ("GET", path, None),
            ("GET", path + "?revision=2&url=https%3A%2F%2Fpython.org", None),
            ("POST", path, {"message_revision": 2, "action": "enqueue", "url": "https://python.org"}),
            ("POST", path, {"message_revision": True, "action": "enqueue"}),
            ("POST", local_bridge.BRIDGE_LINK_PREVIEW_PREFERENCE_PATH, {"enabled": False, "expected_revision": 1, "url": "https://python.org"}),
            ("POST", local_bridge.BRIDGE_LINK_PREVIEW_CACHE_CLEAR_PATH, {"all": True}),
        )
        for method, target, body in cases:
            with self.subTest(method=method, target=target):
                status, response, _headers = self.request(method, target, body)
                self.assertEqual(status, 404)
                self.assertEqual(json.loads(response), {"error": "bridge_route_not_found"})

    def test_opaque_image_route_is_fixed_webp_and_never_accepts_url(self):
        image_id = "b" * 32
        with patch.object(local_bridge, "bridge_link_preview_image", return_value=(b"RIFF-safe-WEBP", 120)) as image:
            status, body, headers = self.request("GET", f"/bridge/v1/link-previews/images/{image_id}")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"RIFF-safe-WEBP")
        self.assertEqual(headers["Content-Type"], "image/webp")
        self.assertEqual(headers["Cache-Control"], "private, max-age=120, no-transform")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        image.assert_called_once_with(image_id)
        status, body, _headers = self.request("GET", "/bridge/v1/link-previews/images/https%3A%2F%2Fpython.org%2Fx")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "bridge_route_not_found"})


if __name__ == "__main__":
    unittest.main()
