#!/usr/bin/env python3
"""Opt-in, loopback-only real-Caddy integration gates.

This runner never downloads or installs Caddy, requests ACME, creates TLS
material, changes firewall state, or binds a public address. A caller must
supply the already-verified binary and disposable test certificate/key.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import http.client
import ipaddress
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import re
import shutil
from urllib.parse import parse_qs, urlsplit

from deploy.caddy.profile import canonical_caddy_host, caddy_subprocess_environment


LOOPBACK = "127.0.0.1"
SPOOFED_HEADERS = {
    "Forwarded": "for=203.0.113.77;host=evil.example;proto=http",
    "X-Forwarded-For": "203.0.113.77",
    "X-Forwarded-Host": "evil.example",
    "X-Forwarded-Proto": "http",
    "X-Real-IP": "203.0.113.77",
}
MAX_RESPONSE_BYTES = 1_048_576
MAX_SSE_BLOCK_BYTES = 16_384


class DisposableIntegrationError(RuntimeError):
    """A real loopback gate failed without exposing a remote service."""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind((LOOPBACK, 0))
        return int(candidate.getsockname()[1])


def _regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DisposableIntegrationError(f"{label} is missing") from exc
    if path.is_symlink() or not path.is_file() or metadata.st_size == 0:
        raise DisposableIntegrationError(f"{label} must be a non-link regular file")


def _caddyfile_path(path: Path, label: str) -> str:
    _regular_file(path, label)
    value = str(path)
    if (
        not path.is_absolute()
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise DisposableIntegrationError(f"{label} path is unsafe for the Caddyfile")
    return json.dumps(value, ensure_ascii=True)


def render_disposable_caddyfile(*, host: str, http_port: int, https_port: int, admin_port: int, upstream_port: int, certificate: Path, key: Path, maintenance: bool = False) -> str:
    """Render a non-deployable derivative which binds only ephemeral loopback ports."""

    try:
        host = canonical_caddy_host(host)
    except ValueError as exc:
        raise DisposableIntegrationError("disposable host is invalid") from exc
    ports = (http_port, https_port, admin_port, upstream_port)
    if len(set(ports)) != 4 or any(not isinstance(port, int) or not 1024 <= port <= 65535 for port in ports):
        raise DisposableIntegrationError("disposable ports must be distinct and unprivileged")
    certificate_value = _caddyfile_path(certificate, "test certificate")
    key_value = _caddyfile_path(key, "test key")
    handler = '''header Cache-Control "no-store"
\trespond 503''' if maintenance else f'''@timeline path /api/runs/*/events
\theader @timeline {{
\t\tCache-Control "private, no-store, no-transform"
\t\tX-Accel-Buffering "no"
\t}}
\treverse_proxy {LOOPBACK}:{upstream_port} {{
\t\theader_up -Forwarded
\t\theader_up -X-Real-IP
\t\theader_up Host {host}
\t}}'''
    return f'''# Disposable fixture only. Not a production deployment config.
{{
\tadmin {LOOPBACK}:{admin_port}
\tpersist_config off
\tgrace_period 35s
\tauto_https off
\tservers {{
\t\tstrict_sni_host on
\t\tprotocols h1 h2
\t}}
}}

http://:{http_port} {{
\tbind {LOOPBACK}
\t@canonical host {host}
\tredir @canonical https://{host}:{https_port}{{uri}} 308
\trespond 404
}}

https://{host}:{https_port} {{
\tbind {LOOPBACK}
\ttls {certificate_value} {key_value}
\theader {{
\t\t-Server
\t\tStrict-Transport-Security "max-age=86400"
\t}}
\t{handler}
}}
'''


@dataclass
class _StreamSession:
    mode: str
    request_headers: dict[str, str]
    started: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    closed: threading.Event = field(default_factory=threading.Event)


class _CaptureServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, port: int) -> None:
        super().__init__((LOOPBACK, port), _CaptureHandler)
        self.captures: list[dict[str, str]] = []
        self.captured = threading.Event()
        self.streams: list[_StreamSession] = []
        self.stream_lock = threading.Lock()

    def register_stream(self, mode: str, headers: dict[str, str]) -> _StreamSession:
        session = _StreamSession(mode=mode, request_headers=headers)
        with self.stream_lock:
            self.streams.append(session)
        return session

    def wait_for_stream(self, index: int, timeout: float = 3) -> _StreamSession:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.stream_lock:
                if len(self.streams) > index:
                    session = self.streams[index]
                    break
            time.sleep(0.01)
        else:
            raise DisposableIntegrationError("upstream SSE session did not start")
        if not session.started.wait(max(0.0, deadline - time.monotonic())):
            raise DisposableIntegrationError("upstream SSE session was not ready")
        return session


class _CaptureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _write_stream_block(self, block: bytes) -> bool:
        try:
            self.wfile.write(block)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False
        return True

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback
        server = self.server
        assert isinstance(server, _CaptureServer)
        request_headers = {name.lower(): value for name, value in self.headers.items()}
        server.captures.append(request_headers)
        server.captured.set()
        parsed = urlsplit(self.path)
        if parsed.path == "/api/runs/checked/events":
            mode = parse_qs(parsed.query).get("mode", ["persistent"])[0]
            if mode not in {"persistent", "finite", "expiry", "revocation"}:
                self.send_error(400)
                return
            session = server.register_stream(mode, request_headers)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "private, no-store, no-transform")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            session.started.set()
            try:
                last_event_id = request_headers.get("last-event-id")
                if mode == "finite":
                    blocks = (
                        (b"id: 2\nevent: reset\ndata: {\"status\":\"reconnected\"}\n\n",)
                        if last_event_id == "1"
                        else (
                            b": keepalive\n\n",
                            b"id: 1\nevent: refresh\ndata: {\"status\":\"ready\"}\n\n",
                        )
                    )
                    for block in blocks:
                        if not self._write_stream_block(block):
                            return
                    return
                if mode in {"expiry", "revocation"}:
                    reason = mode.encode("ascii")
                    self._write_stream_block(
                        b"event: close\ndata: {\"reason\":\"" + reason + b"\"}\n\n"
                    )
                    return
                if not self._write_stream_block(b": keepalive\n\n"):
                    return
                while not session.release.wait(0.1):
                    if not self._write_stream_block(b": keepalive\n\n"):
                        return
                self._write_stream_block(
                    b"event: close\ndata: {\"reason\":\"drain\"}\n\n"
                )
            finally:
                session.closed.set()
            return
        body = json.dumps({"ok": True}, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _start_backend(port: int) -> _CaptureServer:
    backend = _CaptureServer(port)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    return backend


def _stop_backend(backend: _CaptureServer | None) -> None:
    if backend is not None:
        backend.shutdown()
        backend.server_close()


def _open_response(
    port: int,
    host: str,
    path: str,
    *,
    secure: bool = False,
    sni: str | None = None,
    extra_headers: dict[str, str] | None = None,
    trust_certificate: Path | None = None,
    allow_unverified_tls: bool = False,
) -> tuple[socket.socket, http.client.HTTPResponse]:
    raw = socket.create_connection((LOOPBACK, port), timeout=3)
    try:
        if secure:
            if trust_certificate is not None:
                _regular_file(trust_certificate, "TLS trust certificate")
                context = ssl.create_default_context(cafile=str(trust_certificate))
            elif allow_unverified_tls:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
            else:
                raise DisposableIntegrationError("verified TLS requires the disposable trust certificate")
            connection: socket.socket = context.wrap_socket(raw, server_hostname=sni or host)
        else:
            connection = raw
        headers = {"Host": host, "Connection": "close", **(extra_headers or {})}
        wire = "".join(
            [
                f"GET {path} HTTP/1.1\r\n",
                *(f"{name}: {value}\r\n" for name, value in headers.items()),
                "\r\n",
            ]
        )
        connection.sendall(wire.encode("ascii"))
        response = http.client.HTTPResponse(connection)
        response.begin()
        return connection, response
    except BaseException:
        raw.close()
        raise


def request_http(port: int, host: str, path: str, *, secure: bool = False, sni: str | None = None, extra_headers: dict[str, str] | None = None, trust_certificate: Path | None = None, allow_unverified_tls: bool = False) -> tuple[int, dict[str, str], bytes]:
    connection, response = _open_response(
        port,
        host,
        path,
        secure=secure,
        sni=sni,
        extra_headers=extra_headers,
        trust_certificate=trust_certificate,
        allow_unverified_tls=allow_unverified_tls,
    )
    try:
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise DisposableIntegrationError("HTTP response exceeded the disposable bound")
        return response.status, {name.lower(): value for name, value in response.getheaders()}, body
    finally:
        response.close()
        connection.close()


class _SseClient:
    def __init__(self, connection: socket.socket, response: http.client.HTTPResponse) -> None:
        self.connection = connection
        self.response = response

    @property
    def status(self) -> int:
        return self.response.status

    @property
    def headers(self) -> dict[str, str]:
        return {name.lower(): value for name, value in self.response.getheaders()}

    def read_block(self, timeout: float = 3) -> bytes:
        self.connection.settimeout(timeout)
        lines: list[bytes] = []
        size = 0
        while True:
            line = self.response.readline(MAX_SSE_BLOCK_BYTES + 1)
            if line == b"":
                return b"" if not lines else b"".join(lines)
            size += len(line)
            if size > MAX_SSE_BLOCK_BYTES:
                raise DisposableIntegrationError("SSE block exceeded the disposable bound")
            lines.append(line)
            if line in (b"\n", b"\r\n"):
                return b"".join(lines)

    def close(self) -> None:
        self.response.close()
        self.connection.close()


def open_sse(
    port: int,
    host: str,
    path: str,
    *,
    extra_headers: dict[str, str] | None = None,
    trust_certificate: Path,
) -> _SseClient:
    connection, response = _open_response(
        port,
        host,
        path,
        secure=True,
        extra_headers=extra_headers,
        trust_certificate=trust_certificate,
    )
    return _SseClient(connection, response)


def _wait_ready(port: int, host: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            request_http(port, host, "/")
            return
        except OSError:
            time.sleep(0.05)
    raise DisposableIntegrationError("Caddy did not become reachable on loopback")


def _reload(
    caddy: Path,
    admin_port: int,
    config: Path,
    expect_success: bool,
    *,
    child_env: dict[str, str],
) -> None:
    result = subprocess.run(
        [
            str(caddy),
            "reload",
            "--address",
            f"{LOOPBACK}:{admin_port}",
            "--config",
            str(config),
            "--adapter",
            "caddyfile",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
        env=child_env,
    )
    if (result.returncode == 0) != expect_success:
        raise DisposableIntegrationError("Caddy reload outcome was unexpected")


def _atomic_publish(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _reload_with_rollback(
    caddy: Path,
    admin_port: int,
    published: Path,
    candidate: bytes,
    *,
    child_env: dict[str, str],
) -> None:
    known_good = published.read_bytes()
    _atomic_publish(published, candidate)
    _reload(caddy, admin_port, published, False, child_env=child_env)
    _atomic_publish(published, known_good)
    _reload(caddy, admin_port, published, True, child_env=child_env)
    if published.read_bytes() != known_good:
        raise DisposableIntegrationError("known-good disk configuration was not restored")


def _listener_rows(*, udp: bool = False) -> list[str]:
    ss = shutil.which("ss", path=os.defpath)
    if ss is None:
        raise DisposableIntegrationError("Linux listener inventory command is unavailable")
    arguments = [ss, "-H", "-lunp" if udp else "-ltnp"]
    with tempfile.TemporaryDirectory(prefix="mentat-caddy-inventory-") as temporary:
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=caddy_subprocess_environment(Path(temporary)),
        )
    if result.returncode:
        raise DisposableIntegrationError("Linux listener inventory command failed")
    return result.stdout.splitlines()


def assert_loopback_listener_inventory(
    ports: tuple[int, int, int],
    *,
    caddy_pid: int | None = None,
) -> None:
    """Prove Caddy owns exactly the expected loopback TCP listeners and no UDP listener."""

    rows = _listener_rows()
    for port in ports:
        marker = re.compile(rf":{port}(?:\s|$)")
        matching = [line for line in rows if marker.search(line)]
        if not matching or any(f"{LOOPBACK}:{port}" not in row for row in matching):
            raise DisposableIntegrationError("Caddy listener is missing or not loopback-only")
    if caddy_pid is not None:
        process_marker = re.compile(rf"pid={caddy_pid}(?:,|\))")
        owned = [line for line in rows if process_marker.search(line)]
        if len(owned) != len(ports) or any(
            not any(f"{LOOPBACK}:{port}" in row for port in ports) for row in owned
        ):
            raise DisposableIntegrationError("Caddy opened an unexpected TCP listener")
        if any(process_marker.search(line) for line in _listener_rows(udp=True)):
            raise DisposableIntegrationError("Caddy opened an unexpected UDP listener")


def assert_external_address_isolation(ports: tuple[int, int, int]) -> None:
    """Probe Caddy ports through every non-loopback address in the disposable namespace."""

    ip = shutil.which("ip", path=os.defpath)
    if ip is None:
        raise DisposableIntegrationError("Linux namespace address inventory is unavailable")
    with tempfile.TemporaryDirectory(prefix="mentat-caddy-addresses-") as temporary:
        result = subprocess.run(
            [ip, "-j", "-4", "address", "show", "up"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=caddy_subprocess_environment(Path(temporary)),
        )
    if result.returncode:
        raise DisposableIntegrationError("Linux namespace address inventory failed")
    try:
        inventory = json.loads(result.stdout)
        addresses = {
            str(item["local"])
            for interface in inventory
            for item in interface.get("addr_info", [])
            if item.get("family") == "inet"
            and not ipaddress.ip_address(str(item["local"])).is_loopback
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DisposableIntegrationError("Linux namespace address inventory is invalid") from exc
    if not addresses:
        raise DisposableIntegrationError("disposable namespace has no external probe address")
    for address in addresses:
        for port in ports:
            try:
                connection = socket.create_connection((address, port), timeout=0.25)
            except OSError:
                continue
            connection.close()
            raise DisposableIntegrationError("Caddy listener was reachable through an external address")


def _assert_sse_headers(client: _SseClient) -> None:
    headers = client.headers
    if (
        client.status != 200
        or headers.get("content-type", "").split(";", 1)[0] != "text/event-stream"
        or headers.get("cache-control") != "private, no-store, no-transform"
        or headers.get("x-accel-buffering") != "no"
        or headers.get("content-security-policy") != "default-src 'none'; frame-ancestors 'none'"
        or headers.get("referrer-policy") != "no-referrer"
        or headers.get("x-content-type-options") != "nosniff"
        or headers.get("x-frame-options") != "DENY"
    ):
        raise DisposableIntegrationError("SSE security/no-buffering gate failed")


def _expect_sse_block(client: _SseClient, expected: bytes, label: str) -> None:
    if client.read_block() != expected:
        raise DisposableIntegrationError(f"SSE {label} gate failed")


def _expect_sse_eof(client: _SseClient, label: str) -> None:
    if client.read_block() != b"":
        raise DisposableIntegrationError(f"SSE {label} did not close exactly")


def run_disposable_integration(*, caddy: Path, certificate: Path, key: Path, host: str) -> None:
    """Exercise actual Caddy on loopback: headers, TLS, redirect, SSE, and recovery."""

    _regular_file(caddy, "Caddy binary")
    ports = [_free_port() for _ in range(4)]
    while len(set(ports)) != 4:
        ports = [_free_port() for _ in range(4)]
    http_port, https_port, admin_port, upstream_port = ports
    backend: _CaptureServer | None = None
    process: subprocess.Popen[str] | None = None
    try:
        backend = _start_backend(upstream_port)
        with tempfile.TemporaryDirectory(prefix="mentat-caddy-disposable-") as temporary:
            root = Path(temporary)
            common = dict(host=host, http_port=http_port, https_port=https_port, admin_port=admin_port, upstream_port=upstream_port, certificate=certificate, key=key)
            normal_bytes = render_disposable_caddyfile(**common).encode("utf-8")
            maintenance_bytes = render_disposable_caddyfile(**common, maintenance=True).encode("utf-8")
            malformed_bytes = b"not a Caddyfile {{{"
            published = root / "Caddyfile"
            _atomic_publish(published, normal_bytes)
            state = root / "caddy-state"
            state.mkdir(mode=0o700)
            child_env = caddy_subprocess_environment(state)
            process = subprocess.Popen(
                [str(caddy), "run", "--config", str(published), "--adapter", "caddyfile"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=child_env,
            )
            _wait_ready(http_port, host)
            assert_loopback_listener_inventory(
                (http_port, https_port, admin_port),
                caddy_pid=process.pid,
            )
            assert_external_address_isolation(
                (http_port, https_port, admin_port, upstream_port)
            )
            status, headers, _ = request_http(http_port, host, "/deep/link")
            if status != 308 or headers.get("location") != f"https://{host}:{https_port}/deep/link":
                raise DisposableIntegrationError("canonical HTTP redirect gate failed")
            if request_http(http_port, "evil.example", "/")[0] != 404:
                raise DisposableIntegrationError("unknown HTTP host did not receive fixed 404")
            status, headers, _ = request_http(
                https_port,
                host,
                "/headers",
                secure=True,
                extra_headers=SPOOFED_HEADERS,
                trust_certificate=certificate,
            )
            if status != 200 or headers.get("strict-transport-security") != "max-age=86400" or not backend.captured.wait(3):
                raise DisposableIntegrationError("TLS/HSTS/capture gate failed")
            observed = backend.captures[-1]
            expected_forwarding = {
                "host": host,
                "x-forwarded-for": LOOPBACK,
                "x-forwarded-host": host,
                "x-forwarded-proto": "https",
            }
            if (
                any(observed.get(name) != value for name, value in expected_forwarding.items())
                or "forwarded" in observed
                or "x-real-ip" in observed
                or any(value in set(SPOOFED_HEADERS.values()) for value in observed.values())
            ):
                safe_projection = {
                    name: observed.get(name)
                    for name in (
                        "host",
                        "forwarded",
                        "x-forwarded-for",
                        "x-forwarded-host",
                        "x-forwarded-proto",
                        "x-real-ip",
                    )
                }
                raise DisposableIntegrationError(
                    "upstream header re-authoring gate failed: "
                    + json.dumps(safe_projection, sort_keys=True)
                )
            if request_http(
                https_port,
                "evil.example",
                "/",
                secure=True,
                sni=host,
                trust_certificate=certificate,
            )[0] != 421:
                raise DisposableIntegrationError("HTTPS Host mismatch reached the backend")
            captured_before_unknown_sni = len(backend.captures)
            try:
                unknown_status = request_http(
                    https_port,
                    "evil.example",
                    "/",
                    secure=True,
                    allow_unverified_tls=True,
                )[0]
            except ssl.SSLError:
                pass
            else:
                if unknown_status not in (404, 421) or len(backend.captures) != captured_before_unknown_sni:
                    raise DisposableIntegrationError("unknown SNI reached the backend")

            finite = open_sse(
                https_port,
                host,
                "/api/runs/checked/events?mode=finite",
                trust_certificate=certificate,
            )
            try:
                _assert_sse_headers(finite)
                _expect_sse_block(finite, b": keepalive\n\n", "keepalive")
                _expect_sse_block(
                    finite,
                    b"id: 1\nevent: refresh\ndata: {\"status\":\"ready\"}\n\n",
                    "bounded frame",
                )
                _expect_sse_eof(finite, "finite stream")
            finally:
                finite.close()
            first_stream = backend.wait_for_stream(0)
            if not first_stream.closed.wait(3):
                raise DisposableIntegrationError("finite SSE stream did not close")

            reconnect = open_sse(
                https_port,
                host,
                "/api/runs/checked/events?mode=finite",
                extra_headers={"Last-Event-ID": "1"},
                trust_certificate=certificate,
            )
            try:
                _assert_sse_headers(reconnect)
                _expect_sse_block(
                    reconnect,
                    b"id: 2\nevent: reset\ndata: {\"status\":\"reconnected\"}\n\n",
                    "reconnect/reset",
                )
                _expect_sse_eof(reconnect, "reconnect stream")
            finally:
                reconnect.close()
            reconnect_stream = backend.wait_for_stream(1)
            if reconnect_stream.request_headers.get("last-event-id") != "1":
                raise DisposableIntegrationError("SSE reconnect cursor did not reach the upstream")

            for index, mode in enumerate(("expiry", "revocation"), start=2):
                closing = open_sse(
                    https_port,
                    host,
                    f"/api/runs/checked/events?mode={mode}",
                    trust_certificate=certificate,
                )
                try:
                    _assert_sse_headers(closing)
                    _expect_sse_block(
                        closing,
                        f'event: close\ndata: {{"reason":"{mode}"}}\n\n'.encode("ascii"),
                        mode,
                    )
                    _expect_sse_eof(closing, mode)
                finally:
                    closing.close()
                if not backend.wait_for_stream(index).closed.wait(3):
                    raise DisposableIntegrationError(f"SSE {mode} stream did not close")

            cancelled = open_sse(
                https_port,
                host,
                "/api/runs/checked/events",
                trust_certificate=certificate,
            )
            _assert_sse_headers(cancelled)
            _expect_sse_block(cancelled, b": keepalive\n\n", "disconnect keepalive")
            cancelled_stream = backend.wait_for_stream(4)
            cancelled.close()
            if not cancelled_stream.closed.wait(5):
                raise DisposableIntegrationError("downstream SSE disconnect did not cancel the upstream")

            _reload_with_rollback(
                caddy,
                admin_port,
                published,
                malformed_bytes,
                child_env=child_env,
            )
            if request_http(
                https_port,
                host,
                "/",
                secure=True,
                trust_certificate=certificate,
            )[0] != 200:
                raise DisposableIntegrationError("failed reload did not retain known-good config")

            draining = open_sse(
                https_port,
                host,
                "/api/runs/checked/events",
                trust_certificate=certificate,
            )
            _assert_sse_headers(draining)
            _expect_sse_block(draining, b": keepalive\n\n", "pre-drain keepalive")
            draining_stream = backend.wait_for_stream(5)
            drain_started = time.monotonic()
            _atomic_publish(published, maintenance_bytes)
            _reload(caddy, admin_port, published, True, child_env=child_env)
            maintenance_status, maintenance_headers, _ = request_http(
                https_port,
                host,
                "/",
                secure=True,
                trust_certificate=certificate,
            )
            if maintenance_status != 503 or maintenance_headers.get("cache-control") != "no-store":
                raise DisposableIntegrationError("maintenance reload/drain gate failed")
            _expect_sse_block(draining, b": keepalive\n\n", "stream continuity during drain")
            draining_stream.release.set()
            _expect_sse_block(
                draining,
                b"event: close\ndata: {\"reason\":\"drain\"}\n\n",
                "drain closure",
            )
            _expect_sse_eof(draining, "drained stream")
            draining.close()
            if (
                not draining_stream.closed.wait(3)
                or time.monotonic() - drain_started > 35
            ):
                raise DisposableIntegrationError("SSE drain exceeded the 35-second bound")

            _atomic_publish(published, normal_bytes)
            _reload(caddy, admin_port, published, True, child_env=child_env)
            if request_http(
                https_port,
                host,
                "/",
                secure=True,
                trust_certificate=certificate,
            )[0] != 200:
                raise DisposableIntegrationError("known-good reload recovery gate failed")
            _stop_backend(backend)
            backend = None
            if request_http(
                https_port,
                host,
                "/",
                secure=True,
                trust_certificate=certificate,
            )[0] != 502:
                raise DisposableIntegrationError("backend crash did not fail closed")
            backend = _start_backend(upstream_port)
            if request_http(
                https_port,
                host,
                "/",
                secure=True,
                trust_certificate=certificate,
            )[0] != 200:
                raise DisposableIntegrationError("recovered backend did not become reachable")
    finally:
        _stop_backend(backend)
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-disposable", action="store_true")
    parser.add_argument("--caddy-bin", type=Path, required=True)
    parser.add_argument("--test-cert", type=Path, required=True, help="caller-supplied; never generated here")
    parser.add_argument("--test-key", type=Path, required=True, help="caller-supplied; never generated here")
    parser.add_argument("--host", required=True)
    args = parser.parse_args(argv)
    if not args.run_disposable:
        parser.error("--run-disposable is required; this runner never executes implicitly")
    if sys.platform != "linux":
        parser.error("disposable Caddy integration is Linux-only")
    try:
        run_disposable_integration(caddy=args.caddy_bin, certificate=args.test_cert, key=args.test_key, host=args.host)
    except (DisposableIntegrationError, OSError, subprocess.SubprocessError) as exc:
        print(f"disposable Caddy integration failed: {exc}", file=sys.stderr)
        return 1
    print("disposable Caddy integration passed; no public listener or ACME certificate was used")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
