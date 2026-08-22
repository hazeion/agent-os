from __future__ import annotations

from http.client import HTTPConnection
import json
import threading
import unittest

from mentat import local_bridge


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

    def request(
        self,
        method: str = "GET",
        path: str = local_bridge.BRIDGE_HEALTH_PATH,
        *,
        token: str | None = TOKEN,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict, dict[str, str]]:
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        request_headers = {"Host": f"127.0.0.1:{self.port}"}
        if token is not None:
            request_headers[local_bridge.BRIDGE_TOKEN_HEADER] = token
        request_headers.update(headers or {})
        connection.request(method, path, headers=request_headers)
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


if __name__ == "__main__":
    unittest.main()
