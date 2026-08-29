from __future__ import annotations

from io import BytesIO
import gzip
import unittest
from unittest.mock import Mock, patch

import link_preview_transport
from link_preview_policy import normalize_preview_url
from link_preview_transport import LinkPreviewTransportError, fetch_public_resource


def response(body: bytes, *, status=200, headers: tuple[tuple[str, str], ...] = ()) -> bytes:
    fields = list(headers)
    if not any(name.lower() in {"content-length", "transfer-encoding"} for name, _ in fields):
        fields.append(("Content-Length", str(len(body))))
    block = "".join(f"{name}: {value}\r\n" for name, value in fields)
    return f"HTTP/1.1 {status} Test\r\n{block}\r\n".encode("ascii") + body


class FakeConnection:
    def __init__(self, address: str, payload: bytes):
        self.address = address
        self.payload = payload
        self.request = b""
        self.closed = False
        self.timeout = None

    def close(self):
        self.closed = True

    def getpeername(self):
        return self.address, 443

    def makefile(self, mode: str, buffering: int = 0):
        self.assertions = (mode, buffering)
        return BytesIO(self.payload)

    def sendall(self, data: bytes):
        self.request += data

    def settimeout(self, value: float):
        self.timeout = value


class FixtureNetwork:
    def __init__(self, answers: dict[str, tuple[str, ...]], payloads: list[bytes]):
        self.answers = answers
        self.payloads = list(payloads)
        self.resolved: list[str] = []
        self.dials: list[tuple[str, str, float]] = []
        self.connections: list[FakeConnection] = []

    def resolver(self, host: str):
        self.resolved.append(host)
        return self.answers[host]

    def dialer(self, address: str, host: str, timeout: float):
        self.dials.append((address, host, timeout))
        connection = FakeConnection(address, self.payloads.pop(0))
        self.connections.append(connection)
        return connection


class LinkPreviewTransportTests(unittest.TestCase):
    def test_deadline_stream_rechecks_total_time_after_each_progress_read(self):
        current = [0.0]
        raw_stream = Mock()
        raw_stream.read.side_effect = lambda _amount=-1: (current.__setitem__(0, 5.1) or b"x")
        connection = Mock()
        stream = link_preview_transport._DeadlineStream(raw_stream, connection, 5.0, lambda: current[0])
        with self.assertRaises(LinkPreviewTransportError) as raised:
            stream.read(1)
        self.assertEqual(raised.exception.code, "link_preview.timeout")
        connection.settimeout.assert_called_once_with(1.0)

    def test_default_dialer_connects_numeric_ip_with_hostname_sni_and_peer_check(self):
        raw = Mock()
        raw.getpeername.return_value = ("8.8.8.8", 443)
        secured = Mock()
        secured.getpeername.return_value = ("8.8.8.8", 443)
        context = Mock()
        context.wrap_socket.return_value = secured
        with patch.object(link_preview_transport.socket, "socket", return_value=raw) as socket_factory, patch.object(link_preview_transport.ssl, "create_default_context", return_value=context):
            result = link_preview_transport._default_dialer("8.8.8.8", "python.org", 1.5)
        self.assertIs(result, secured)
        socket_factory.assert_called_once_with(link_preview_transport.socket.AF_INET, link_preview_transport.socket.SOCK_STREAM, link_preview_transport.socket.IPPROTO_TCP)
        raw.connect.assert_called_once_with(("8.8.8.8", 443))
        context.wrap_socket.assert_called_once_with(raw, server_hostname="python.org")

    def test_numeric_pin_sni_host_and_fixed_credential_free_request(self):
        network = FixtureNetwork(
            {"python.org": ("2606:4700:4700::1111", "8.8.8.8")},
            [response(b"<title>Python</title>", headers=(("Content-Type", "text/html; charset=utf-8"),))],
        )
        phases: list[str] = []
        result = fetch_public_resource(
            normalize_preview_url("https://python.org/docs?q=1"),
            kind="page",
            resolver=network.resolver,
            dialer=network.dialer,
            phase=phases.append,
        )
        self.assertEqual(result.body, b"<title>Python</title>")
        self.assertEqual(network.resolved, ["python.org"])
        self.assertEqual(network.dials[0][0:2], ("2606:4700:4700::1111", "python.org"))
        request = network.connections[0].request
        self.assertIn(b"GET /docs?q=1 HTTP/1.1\r\n", request)
        self.assertIn(b"Host: python.org\r\n", request)
        self.assertIn(b"User-Agent: MentatLinkPreview/1\r\n", request)
        for forbidden in (b"Cookie:", b"Authorization:", b"Proxy-Authorization:", b"Referer:", b"Origin:", b"Accept-Language:"):
            self.assertNotIn(forbidden, request)
        self.assertEqual(phases, ["dns", "connect", "transfer"])
        self.assertTrue(network.connections[0].closed)

    def test_mixed_or_private_answers_block_before_dial(self):
        network = FixtureNetwork({"python.org": ("8.8.8.8", "127.0.0.1")}, [])
        with self.assertRaises(LinkPreviewTransportError) as raised:
            fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=network.resolver, dialer=network.dialer)
        self.assertEqual(raised.exception.code, "link_preview.blocked")
        self.assertEqual(network.dials, [])

    def test_redirects_are_revalidated_and_private_or_loops_fail_closed(self):
        first = response(b"", status=302, headers=(("Location", "https://www.python.org/final"),))
        final = response(b"done", headers=(("Content-Type", "text/html"),))
        network = FixtureNetwork(
            {"python.org": ("8.8.8.8",), "www.python.org": ("8.8.4.4",)},
            [first, final],
        )
        fetched = fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=network.resolver, dialer=network.dialer)
        self.assertEqual(fetched.final_url.canonical_url, "https://www.python.org/final")
        self.assertEqual([item[:2] for item in network.dials], [("8.8.8.8", "python.org"), ("8.8.4.4", "www.python.org")])

        private = FixtureNetwork({"python.org": ("8.8.8.8",)}, [response(b"", status=302, headers=(("Location", "https://127.0.0.1/private"),))])
        with self.assertRaises(LinkPreviewTransportError) as raised:
            fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=private.resolver, dialer=private.dialer)
        self.assertEqual(raised.exception.code, "link_preview.blocked")

        loop = FixtureNetwork({"python.org": ("8.8.8.8",)}, [response(b"", status=302, headers=(("Location", "/"),))])
        with self.assertRaises(LinkPreviewTransportError) as raised:
            fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=loop.resolver, dialer=loop.dialer)
        self.assertEqual(raised.exception.code, "link_preview.redirect_limit")

    def test_gzip_chunked_and_content_bounds(self):
        compressed = gzip.compress(b"<title>gzip</title>", mtime=0)
        network = FixtureNetwork(
            {"python.org": ("8.8.8.8",)},
            [response(compressed, headers=(("Content-Type", "text/html"), ("Content-Encoding", "gzip")))],
        )
        self.assertEqual(fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=network.resolver, dialer=network.dialer).body, b"<title>gzip</title>")

        chunks = b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
        chunked = FixtureNetwork(
            {"python.org": ("8.8.8.8",)},
            [response(chunks, headers=(("Content-Type", "text/html"), ("Transfer-Encoding", "chunked")))],
        )
        self.assertEqual(fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=chunked.resolver, dialer=chunked.dialer).body, b"hello world")

        oversized = FixtureNetwork(
            {"python.org": ("8.8.8.8",)},
            [b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 9999999\r\n\r\n"],
        )
        with self.assertRaises(LinkPreviewTransportError):
            fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=oversized.resolver, dialer=oversized.dialer)

        for content_encoding, body in (
            ("br", b"html"),
            ("gzip, br", compressed),
            ("gzip", b"not-gzip"),
            ("gzip", gzip.compress(b"x" * (1024 * 1024 + 1), mtime=0)),
        ):
            hostile = FixtureNetwork(
                {"python.org": ("8.8.8.8",)},
                [response(body, headers=(("Content-Type", "text/html"), ("Content-Encoding", content_encoding)))],
            )
            with self.subTest(content_encoding=content_encoding, size=len(body)), self.assertRaises(LinkPreviewTransportError):
                fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=hostile.resolver, dialer=hostile.dialer)

    def test_header_mime_peer_and_encoding_confusion_fail_closed(self):
        headers = b"".join(f"X-{index}: value\r\n".encode() for index in range(65))
        too_many = FixtureNetwork({"python.org": ("8.8.8.8",)}, [b"HTTP/1.1 200 OK\r\n" + headers + b"\r\n"])
        with self.assertRaises(LinkPreviewTransportError):
            fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=too_many.resolver, dialer=too_many.dialer)

        missing_mime = FixtureNetwork({"python.org": ("8.8.8.8",)}, [response(b"html")])
        with self.assertRaises(LinkPreviewTransportError) as raised:
            fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=missing_mime.resolver, dialer=missing_mime.dialer)
        self.assertEqual(raised.exception.code, "link_preview.mime_unsupported")

        encoded_image = FixtureNetwork({"images.python.org": ("8.8.8.8",)}, [response(b"image", headers=(("Content-Type", "image/png"), ("Content-Encoding", "gzip")))])
        with self.assertRaises(LinkPreviewTransportError):
            fetch_public_resource(normalize_preview_url("https://images.python.org/x"), kind="image", resolver=encoded_image.resolver, dialer=encoded_image.dialer)

        class WrongPeerNetwork(FixtureNetwork):
            def dialer(self, address: str, host: str, timeout: float):
                connection = FakeConnection("1.1.1.1", response(b"x", headers=(("Content-Type", "text/html"),)))
                self.connections.append(connection)
                return connection

        wrong = WrongPeerNetwork({"python.org": ("8.8.8.8",)}, [])
        with self.assertRaises(LinkPreviewTransportError) as raised:
            fetch_public_resource(normalize_preview_url("https://python.org/"), kind="page", resolver=wrong.resolver, dialer=wrong.dialer)
        self.assertEqual(raised.exception.code, "link_preview.blocked")

    def test_deadline_is_total_and_errors_do_not_echo_targets(self):
        current = [0.0]

        def clock():
            return current[0]

        def resolver(_host: str):
            current[0] = 6.0
            return ("8.8.8.8",)

        with self.assertRaises(LinkPreviewTransportError) as raised:
            fetch_public_resource(normalize_preview_url("https://python.org/private?q=value"), kind="page", resolver=resolver, dialer=lambda *_args: self.fail("dialed"), clock=clock)
        self.assertEqual(raised.exception.code, "link_preview.timeout")
        self.assertNotIn("python", str(raised.exception))
        self.assertNotIn("8.8.8.8", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
