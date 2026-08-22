"""Private loopback bridge used by the source-checkout Node preview.

The bridge intentionally exposes one fixed, read-only health capability. It is
not a generic proxy for ``server.py`` and it owns no durable state.
"""

from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
import signal
import socket
import threading
from urllib.parse import urlsplit

from .version import DISPLAY_VERSION


BRIDGE_TOKEN_ENV = "MENTAT_BRIDGE_TOKEN"
BRIDGE_TOKEN_HEADER = "X-Mentat-Bridge-Token"
BRIDGE_HEALTH_PATH = "/bridge/v1/health"
MINIMUM_TOKEN_LENGTH = 43
MAXIMUM_TOKEN_LENGTH = 256
SUPPORTED_BRIDGE_HOSTS = frozenset({"127.0.0.1", "::1"})


class BridgeConfigurationError(ValueError):
    """Raised when the private bridge cannot start safely."""


class IPv6BridgeHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], token: str):
        self.bridge_token = token
        super().__init__(address, BridgeRequestHandler)


class IPv6ConfiguredBridgeHTTPServer(IPv6BridgeHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], token: str):
        self.bridge_token = token
        super().__init__(address, BridgeRequestHandler)


def validate_bridge_host(host: str) -> str:
    normalized = str(host or "").strip().lower().strip("[]")
    if normalized not in SUPPORTED_BRIDGE_HOSTS:
        raise BridgeConfigurationError("bridge_host_must_be_loopback")
    return normalized


def validate_bridge_port(value: object, *, allow_zero: bool = True) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BridgeConfigurationError("bridge_port_invalid") from exc
    minimum = 0 if allow_zero else 1
    if not minimum <= port <= 65535:
        raise BridgeConfigurationError("bridge_port_invalid")
    return port


def validate_bridge_token(value: object) -> str:
    token = str(value or "")
    try:
        token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BridgeConfigurationError("bridge_token_invalid") from exc
    if (
        not MINIMUM_TOKEN_LENGTH <= len(token) <= MAXIMUM_TOKEN_LENGTH
        or token.strip() != token
        or any(character.isspace() for character in token)
    ):
        raise BridgeConfigurationError("bridge_token_invalid")
    return token


def bridge_server_class(host: str) -> type[BridgeHTTPServer] | type[IPv6ConfiguredBridgeHTTPServer]:
    return IPv6ConfiguredBridgeHTTPServer if validate_bridge_host(host) == "::1" else BridgeHTTPServer


def build_bridge_server(host: str, port: int, token: str):
    safe_host = validate_bridge_host(host)
    safe_port = validate_bridge_port(port)
    safe_token = validate_bridge_token(token)
    return bridge_server_class(safe_host)((safe_host, safe_port), safe_token)


def _normalized_ip(value: object) -> str | None:
    try:
        return str(ipaddress.ip_address(str(value or "").strip().strip("[]")))
    except ValueError:
        return None


def host_header_matches_binding(value: object, bound_host: str, bound_port: int) -> bool:
    raw = str(value or "").strip()
    if not raw or any(character.isspace() for character in raw):
        return False
    try:
        parsed = urlsplit(f"//{raw}")
        parsed_port = parsed.port
    except ValueError:
        return False
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed_port is None
    ):
        return False
    return (
        _normalized_ip(parsed.hostname) == _normalized_ip(bound_host)
        and parsed_port == int(bound_port)
    )


def client_is_loopback(value: object) -> bool:
    try:
        return ipaddress.ip_address(str(value or "").strip()).is_loopback
    except ValueError:
        return False


class BridgeRequestHandler(BaseHTTPRequestHandler):
    server_version = "MentatLocalBridge"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        # Request metadata is intentionally not logged by this private surface.
        return

    def _send_json(self, payload: dict[str, object], status: int) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _request_is_private(self, *, reject_body_headers: bool = True) -> bool:
        if not client_is_loopback(self.client_address[0]):
            return False
        bound_host, bound_port = self.server.server_address[:2]
        host_headers = self.headers.get_all("Host", failobj=[]) or []
        if len(host_headers) != 1 or not host_header_matches_binding(
            host_headers[0], bound_host, int(bound_port)
        ):
            return False
        if self.headers.get_all("Origin", failobj=[]) or self.headers.get_all(
            "Cookie", failobj=[]
        ):
            return False
        # Browser requests carry Sec-Fetch-Site. Node's standards-based
        # server-side fetch may add Sec-Fetch-Mode, so rejecting every
        # Sec-Fetch header would also reject the intended BFF caller.
        if self.headers.get_all("Sec-Fetch-Site", failobj=[]):
            return False
        if reject_body_headers and (
            self.headers.get_all("Content-Length", failobj=[])
            or self.headers.get_all("Transfer-Encoding", failobj=[])
        ):
            return False
        supplied_tokens = self.headers.get_all(BRIDGE_TOKEN_HEADER, failobj=[]) or []
        if len(supplied_tokens) != 1:
            return False
        expected = getattr(self.server, "bridge_token", "")
        return bool(expected) and hmac.compare_digest(supplied_tokens[0], expected)

    def _reject_method(self) -> None:
        if not self._request_is_private(reject_body_headers=False):
            self._send_json({"error": "bridge_request_forbidden"}, 403)
            return
        self._send_json({"error": "method_not_allowed"}, 405)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._request_is_private():
            self._send_json({"error": "bridge_request_forbidden"}, 403)
            return
        if self.path != BRIDGE_HEALTH_PATH:
            self._send_json({"error": "bridge_route_not_found"}, 404)
            return
        self._send_json(
            {
                "mentat_version": DISPLAY_VERSION,
                "runtime": "python",
                "schema_version": 1,
                "service": "mentat-local-bridge",
                "status": "ready",
            },
            200,
        )

    do_DELETE = _reject_method
    do_HEAD = _reject_method
    do_OPTIONS = _reject_method
    do_PATCH = _reject_method
    do_POST = _reject_method
    do_PUT = _reject_method


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Mentat's private source-preview bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="0")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.pop(BRIDGE_TOKEN_ENV, "")
    try:
        bridge = build_bridge_server(args.host, validate_bridge_port(args.port), token)
    except (BridgeConfigurationError, OSError) as exc:
        code = str(exc) if isinstance(exc, BridgeConfigurationError) else "bridge_bind_failed"
        print(f"Mentat Local Bridge refused startup: {code}", flush=True)
        return 2

    stopped = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stopped.set()

    previous_handlers: dict[int, object] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[signum] = signal.signal(signum, request_stop)
        except (OSError, ValueError):
            continue

    bridge.timeout = 0.25
    bound_host, bound_port = bridge.server_address[:2]
    display_host = f"[{bound_host}]" if ":" in str(bound_host) else str(bound_host)
    print(f"Mentat Python Local Bridge ready on http://{display_host}:{bound_port}", flush=True)
    try:
        while not stopped.is_set():
            bridge.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.server_close()
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
