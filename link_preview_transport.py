"""Credential-free pinned HTTPS transport for replaceable preview workers."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import socket
import ssl
import time
from typing import BinaryIO, Callable, Iterable, Protocol
from urllib.parse import urljoin, urlsplit
import zlib

from link_preview_policy import (
    LinkPreviewPolicyError,
    NormalizedPreviewURL,
    normalize_preview_url,
    validate_public_addresses,
)


MAXIMUM_REDIRECTS = 3
MAXIMUM_HEADER_BYTES = 32 * 1024
MAXIMUM_HEADER_FIELDS = 64
MAXIMUM_HEADER_FIELD_BYTES = 8 * 1024
MAXIMUM_PAGE_ENCODED_BYTES = 512 * 1024
MAXIMUM_PAGE_DECODED_BYTES = 1024 * 1024
MAXIMUM_IMAGE_ENCODED_BYTES = 2 * 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 2.0
IDLE_TIMEOUT_SECONDS = 1.0
OPERATION_TIMEOUT_SECONDS = 5.0
_PAGE_ACCEPT = "text/html, application/xhtml+xml;q=0.9"
_IMAGE_ACCEPT = "image/webp, image/png;q=0.9, image/jpeg;q=0.9"
_REDIRECTS = {301, 302, 303, 307, 308}
_HEADER_NAME = frozenset(b"!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


class LinkPreviewTransportError(RuntimeError):
    def __init__(self, code: str):
        safe = code if code in {
            "link_preview.blocked",
            "link_preview.invalid_response",
            "link_preview.mime_unsupported",
            "link_preview.redirect_limit",
            "link_preview.timeout",
            "link_preview.unavailable",
        } else "link_preview.unavailable"
        super().__init__(safe)
        self.code = safe


class PreviewConnection(Protocol):
    def close(self) -> None: ...
    def getpeername(self): ...
    def makefile(self, mode: str, buffering: int = 0) -> BinaryIO: ...
    def sendall(self, data: bytes) -> None: ...
    def settimeout(self, value: float) -> None: ...


Resolver = Callable[[str], Iterable[str]]
Dialer = Callable[[str, str, float], PreviewConnection]
Clock = Callable[[], float]
Phase = Callable[[str], None]


class _DeadlineStream:
    def __init__(self, stream: BinaryIO, connection: PreviewConnection, deadline: float, clock: Clock):
        self._stream = stream
        self._connection = connection
        self._deadline = deadline
        self._clock = clock

    def _timeout(self) -> None:
        self._connection.settimeout(min(IDLE_TIMEOUT_SECONDS, _remaining(self._deadline, self._clock)))

    def read(self, amount: int = -1) -> bytes:
        self._timeout()
        value = self._stream.read(amount)
        _remaining(self._deadline, self._clock)
        return value

    def readline(self, amount: int = -1) -> bytes:
        self._timeout()
        value = self._stream.readline(amount)
        _remaining(self._deadline, self._clock)
        return value

    def close(self) -> None:
        self._stream.close()


@dataclass(frozen=True)
class FetchedResource:
    body: bytes
    cache_control: tuple[str, ...]
    content_type: str
    final_url: NormalizedPreviewURL
    vary: tuple[str, ...]


def _remaining(deadline: float, clock: Clock) -> float:
    value = deadline - clock()
    if value <= 0:
        raise LinkPreviewTransportError("link_preview.timeout")
    return value


def _default_resolver(host: str) -> tuple[str, ...]:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise LinkPreviewTransportError("link_preview.unavailable") from exc
    return tuple(answer[4][0] for answer in answers)


def _default_dialer(address: str, hostname: str, timeout: float) -> PreviewConnection:
    parsed = ipaddress.ip_address(address)
    family = socket.AF_INET6 if parsed.version == 6 else socket.AF_INET
    raw = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    try:
        raw.settimeout(timeout)
        target = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
        raw.connect(target)
        peer = ipaddress.ip_address(raw.getpeername()[0]).compressed
        if peer != parsed.compressed:
            raise LinkPreviewTransportError("link_preview.blocked")
        context = ssl.create_default_context()
        secured = context.wrap_socket(raw, server_hostname=hostname)
        secured.settimeout(timeout)
        secured_peer = ipaddress.ip_address(secured.getpeername()[0]).compressed
        if secured_peer != parsed.compressed:
            secured.close()
            raise LinkPreviewTransportError("link_preview.blocked")
        return secured
    except Exception:
        raw.close()
        raise


def _line(stream: BinaryIO, maximum: int) -> bytes:
    try:
        value = stream.readline(maximum + 1)
    except (OSError, TimeoutError) as exc:
        raise LinkPreviewTransportError("link_preview.timeout") from exc
    if len(value) > maximum or not value.endswith(b"\r\n"):
        raise LinkPreviewTransportError("link_preview.invalid_response")
    return value


def _headers(stream: BinaryIO) -> tuple[int, dict[str, list[str]]]:
    status_line = _line(stream, MAXIMUM_HEADER_FIELD_BYTES)
    total = len(status_line)
    parts = status_line.rstrip(b"\r\n").split(b" ", 2)
    if len(parts) < 2 or parts[0] not in {b"HTTP/1.0", b"HTTP/1.1"} or len(parts[1]) != 3 or not parts[1].isdigit():
        raise LinkPreviewTransportError("link_preview.invalid_response")
    status = int(parts[1])
    headers: dict[str, list[str]] = {}
    count = 0
    while True:
        line = _line(stream, MAXIMUM_HEADER_FIELD_BYTES)
        total += len(line)
        if total > MAXIMUM_HEADER_BYTES:
            raise LinkPreviewTransportError("link_preview.invalid_response")
        if line in {b"\n", b"\r\n"}:
            return status, headers
        count += 1
        if count > MAXIMUM_HEADER_FIELDS or line[:1] in {b" ", b"\t"}:
            raise LinkPreviewTransportError("link_preview.invalid_response")
        name, separator, raw_value = line.rstrip(b"\r\n").partition(b":")
        if not separator or not name or any(byte not in _HEADER_NAME for byte in name):
            raise LinkPreviewTransportError("link_preview.invalid_response")
        value_bytes = raw_value.strip(b" \t")
        if any(byte < 32 and byte != 9 or byte == 127 for byte in value_bytes):
            raise LinkPreviewTransportError("link_preview.invalid_response")
        try:
            value = value_bytes.decode("latin-1")
        except UnicodeDecodeError as exc:
            raise LinkPreviewTransportError("link_preview.invalid_response") from exc
        headers.setdefault(name.decode("ascii").lower(), []).append(value)


def _exact_header(headers: dict[str, list[str]], name: str) -> str | None:
    values = headers.get(name, [])
    if len(values) > 1:
        raise LinkPreviewTransportError("link_preview.invalid_response")
    return values[0] if values else None


def _read_exact(stream: BinaryIO, amount: int) -> bytes:
    chunks: list[bytes] = []
    remaining = amount
    while remaining:
        try:
            chunk = stream.read(min(64 * 1024, remaining))
        except (OSError, TimeoutError) as exc:
            raise LinkPreviewTransportError("link_preview.timeout") from exc
        if not chunk:
            raise LinkPreviewTransportError("link_preview.invalid_response")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _chunked(stream: BinaryIO, maximum: int) -> bytes:
    result = bytearray()
    while True:
        raw_size = _line(stream, 128).strip()
        size_token = raw_size.split(b";", 1)[0]
        try:
            size = int(size_token, 16)
        except ValueError as exc:
            raise LinkPreviewTransportError("link_preview.invalid_response") from exc
        if size < 0 or len(result) + size > maximum:
            raise LinkPreviewTransportError("link_preview.invalid_response")
        if size == 0:
            if _line(stream, MAXIMUM_HEADER_FIELD_BYTES) not in {b"\n", b"\r\n"}:
                raise LinkPreviewTransportError("link_preview.invalid_response")
            return bytes(result)
        result.extend(_read_exact(stream, size))
        if _read_exact(stream, 2) != b"\r\n":
            raise LinkPreviewTransportError("link_preview.invalid_response")


def _body(stream: BinaryIO, headers: dict[str, list[str]], maximum: int) -> bytes:
    transfer = _exact_header(headers, "transfer-encoding")
    length = _exact_header(headers, "content-length")
    if transfer is not None and length is not None:
        raise LinkPreviewTransportError("link_preview.invalid_response")
    if transfer is not None:
        if transfer.strip().lower() != "chunked":
            raise LinkPreviewTransportError("link_preview.invalid_response")
        return _chunked(stream, maximum)
    if length is not None:
        if not length.isascii() or not length.isdecimal():
            raise LinkPreviewTransportError("link_preview.invalid_response")
        amount = int(length)
        if amount > maximum:
            raise LinkPreviewTransportError("link_preview.invalid_response")
        return _read_exact(stream, amount)
    result = bytearray()
    while len(result) <= maximum:
        try:
            chunk = stream.read(min(64 * 1024, maximum + 1 - len(result)))
        except (OSError, TimeoutError) as exc:
            raise LinkPreviewTransportError("link_preview.timeout") from exc
        if not chunk:
            return bytes(result)
        result.extend(chunk)
    raise LinkPreviewTransportError("link_preview.invalid_response")


def _decode_page(body: bytes, headers: dict[str, list[str]]) -> bytes:
    encoding = (_exact_header(headers, "content-encoding") or "identity").strip().lower()
    if encoding == "identity":
        return body
    if encoding != "gzip":
        raise LinkPreviewTransportError("link_preview.invalid_response")
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        result = decoder.decompress(body, MAXIMUM_PAGE_DECODED_BYTES + 1)
        if len(result) > MAXIMUM_PAGE_DECODED_BYTES:
            raise LinkPreviewTransportError("link_preview.invalid_response")
        result += decoder.flush(MAXIMUM_PAGE_DECODED_BYTES + 1 - len(result))
    except zlib.error as exc:
        raise LinkPreviewTransportError("link_preview.invalid_response") from exc
    if len(result) > MAXIMUM_PAGE_DECODED_BYTES or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise LinkPreviewTransportError("link_preview.invalid_response")
    return result


def fetch_public_resource(
    initial: NormalizedPreviewURL,
    *,
    kind: str,
    resolver: Resolver = _default_resolver,
    dialer: Dialer = _default_dialer,
    clock: Clock = time.monotonic,
    phase: Phase = lambda _value: None,
) -> FetchedResource:
    """Fetch one page or image through fully revalidated pinned connections."""

    if kind not in {"page", "image"}:
        raise LinkPreviewTransportError("link_preview.unavailable")
    deadline = clock() + OPERATION_TIMEOUT_SECONDS
    current = initial
    visited: set[str] = set()
    for hop in range(MAXIMUM_REDIRECTS + 1):
        _remaining(deadline, clock)
        if current.canonical_url in visited:
            raise LinkPreviewTransportError("link_preview.redirect_limit")
        visited.add(current.canonical_url)
        if current.is_ip_literal:
            addresses = validate_public_addresses((current.host,))
        else:
            phase("dns")
            _remaining(deadline, clock)
            try:
                resolved = tuple(resolver(current.host))
                addresses = validate_public_addresses(resolved)
            except LinkPreviewPolicyError as exc:
                raise LinkPreviewTransportError("link_preview.blocked" if exc.code == "link_preview.blocked" else "link_preview.unavailable") from exc
        connection: PreviewConnection | None = None
        last_error: Exception | None = None
        for address in addresses.connection_candidates:
            phase("connect")
            timeout = min(CONNECT_TIMEOUT_SECONDS, _remaining(deadline, clock))
            try:
                connection = dialer(address, current.host, timeout)
                peer = ipaddress.ip_address(connection.getpeername()[0]).compressed
                if peer != ipaddress.ip_address(address).compressed:
                    connection.close()
                    connection = None
                    raise LinkPreviewTransportError("link_preview.blocked")
                break
            except LinkPreviewTransportError:
                raise
            except Exception as exc:
                last_error = exc
                connection = None
        if connection is None:
            raise LinkPreviewTransportError("link_preview.unavailable") from last_error
        try:
            connection.settimeout(min(IDLE_TIMEOUT_SECONDS, _remaining(deadline, clock)))
            authority = urlsplit(current.canonical_url).netloc
            accept = _PAGE_ACCEPT if kind == "page" else _IMAGE_ACCEPT
            encoding = "gzip" if kind == "page" else "identity"
            request = (
                f"GET {current.request_target} HTTP/1.1\r\n"
                f"Host: {authority}\r\n"
                "User-Agent: MentatLinkPreview/1\r\n"
                f"Accept: {accept}\r\n"
                f"Accept-Encoding: {encoding}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            phase("transfer")
            connection.sendall(request)
            stream = _DeadlineStream(
                connection.makefile("rb", buffering=0),
                connection,
                deadline,
                clock,
            )
            try:
                status, headers = _headers(stream)
                if status in _REDIRECTS:
                    location = _exact_header(headers, "location")
                    if location is None or hop == MAXIMUM_REDIRECTS:
                        raise LinkPreviewTransportError("link_preview.redirect_limit")
                    try:
                        current = normalize_preview_url(urljoin(current.canonical_url, location))
                    except LinkPreviewPolicyError as exc:
                        raise LinkPreviewTransportError("link_preview.blocked") from exc
                    continue
                if status != 200:
                    raise LinkPreviewTransportError("link_preview.unavailable")
                content_type = _exact_header(headers, "content-type")
                if content_type is None:
                    raise LinkPreviewTransportError("link_preview.mime_unsupported")
                encoded_body = _body(
                    stream,
                    headers,
                    MAXIMUM_PAGE_ENCODED_BYTES if kind == "page" else MAXIMUM_IMAGE_ENCODED_BYTES,
                )
                if kind == "page":
                    decoded = _decode_page(encoded_body, headers)
                else:
                    content_encoding = (_exact_header(headers, "content-encoding") or "identity").strip().lower()
                    if content_encoding != "identity":
                        raise LinkPreviewTransportError("link_preview.invalid_response")
                    decoded = encoded_body
                _remaining(deadline, clock)
                return FetchedResource(
                    body=decoded,
                    cache_control=tuple(headers.get("cache-control", ())),
                    content_type=content_type,
                    final_url=current,
                    vary=tuple(headers.get("vary", ())),
                )
            finally:
                stream.close()
        except LinkPreviewTransportError:
            raise
        except (OSError, TimeoutError) as exc:
            raise LinkPreviewTransportError("link_preview.unavailable") from exc
        finally:
            connection.close()
    raise LinkPreviewTransportError("link_preview.redirect_limit")


__all__ = [
    "FetchedResource",
    "LinkPreviewTransportError",
    "fetch_public_resource",
]
