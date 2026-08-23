"""Fixed Vercel Sandbox and Connect readiness capabilities."""

from __future__ import annotations

from dataclasses import dataclass
import http.client
import json
import re
import socket
import ssl
import threading
import time
from typing import Callable, Mapping
from urllib.parse import quote, urlencode, urlsplit

from vercel_connections import (
    VercelConnection,
    credential_for_connect,
    credential_for_vercel_api,
)


SANDBOX_API_BASE = "https://api.vercel.com"
CONNECT_API_BASE = "https://api.vercel.com/v1/connect/token"
MAX_JSON_RESPONSE_BYTES = 256 * 1024
MAX_SANDBOX_STREAM_BYTES = 256 * 1024
SANDBOX_TIMEOUT_MILLISECONDS = 60_000
COMMAND_TIMEOUT_MILLISECONDS = 15_000
FIXED_SANDBOX_COMMAND = "node"
FIXED_SANDBOX_ARGUMENTS = (
    "-e",
    "process.stdout.write('mentat-sandbox-ready:'+process.versions.node)",
)
_SAFE_REMOTE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")
_NODE_24_READY = re.compile(r"mentat-sandbox-ready:24\.[0-9]+\.[0-9]+\Z")
_ALLOWED_HOSTS = frozenset({"api.vercel.com", "ai-gateway.vercel.sh"})


class VercelInfrastructureError(RuntimeError):
    """A bounded infrastructure failure that never includes provider payloads."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class VercelHttpResponse:
    status_code: int
    body: bytes
    content_type: str

    def json_object(self) -> dict[str, object]:
        value, failure_code = _decode_json_object(self.content_type, self.body)
        # Rebind the response before raising so traceback-frame locals cannot
        # retain raw provider bytes.
        self = None  # type: ignore[assignment]
        if failure_code is not None:
            raise VercelInfrastructureError(failure_code)
        if value is None:
            raise VercelInfrastructureError("vercel.response_invalid")
        return value


RequestFunction = Callable[..., VercelHttpResponse]


class _DeadlineSSLContext:
    """Publish the TLS socket before its handshake can block."""

    def __init__(
        self,
        delegate: ssl.SSLContext,
        published_socket: list[object | None],
        expired: threading.Event,
        deadline_at: float,
    ):
        self._delegate = delegate
        self._published_socket = published_socket
        self._expired = expired
        self._deadline_at = deadline_at

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)

    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        setattr(self._delegate, name, value)

    def wrap_socket(
        self,
        sock: socket.socket,
        server_side: bool = False,
        do_handshake_on_connect: bool = True,
        suppress_ragged_eofs: bool = True,
        server_hostname: str | None = None,
        session: ssl.SSLSession | None = None,
    ) -> ssl.SSLSocket:
        del do_handshake_on_connect
        wrapped = self._delegate.wrap_socket(
            sock,
            server_side=server_side,
            do_handshake_on_connect=False,
            suppress_ragged_eofs=suppress_ragged_eofs,
            server_hostname=server_hostname,
            session=session,
        )
        self._published_socket[0] = wrapped
        remaining = self._deadline_at - time.monotonic()
        if self._expired.is_set() or remaining <= 0:
            try:
                wrapped.close()
            except Exception:
                pass
            raise TimeoutError("Vercel TLS deadline expired")
        wrapped.settimeout(max(0.001, remaining))
        wrapped.do_handshake()
        return wrapped


def _decode_json_object(
    content_type: str,
    body: bytes,
) -> tuple[dict[str, object] | None, str | None]:
    if not content_type.lower().startswith("application/json"):
        return None, "vercel.response_invalid"
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "vercel.response_invalid"
    if not isinstance(value, dict):
        return None, "vercel.response_invalid"
    return value, None


def _resolve_before_deadline(
    host: str,
    port: int,
    *,
    deadline_at: float,
    maximum_seconds: float,
) -> tuple[tuple[tuple[object, ...], ...] | None, str | None]:
    """Resolve only; a timed-out worker can never continue into TCP or TLS."""

    done = threading.Event()
    cancelled = threading.Event()
    result: dict[str, object] = {"addresses": None, "failure": None}

    def resolve() -> None:
        failure: str | None = None
        addresses: tuple[tuple[object, ...], ...] | None = None
        try:
            resolved = socket.getaddrinfo(
                host,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
            addresses = tuple(tuple(item) for item in resolved[:16])
            if not addresses:
                failure = "vercel.request_unknown"
        except Exception:
            failure = (
                "vercel.request_timeout"
                if time.monotonic() >= deadline_at
                else "vercel.request_unknown"
            )
        if not cancelled.is_set():
            result["addresses"] = addresses
            result["failure"] = failure
        done.set()

    worker = threading.Thread(target=resolve, daemon=True)
    worker.start()
    remaining = min(maximum_seconds, deadline_at - time.monotonic())
    if remaining <= 0 or not done.wait(remaining):
        cancelled.set()
        return None, "vercel.request_timeout"
    failure = result["failure"]
    addresses = result["addresses"]
    if failure is not None:
        return None, str(failure)
    if not isinstance(addresses, tuple) or not addresses:
        return None, "vercel.request_unknown"
    return addresses, None


def _connect_resolved_before_deadline(
    connection: http.client.HTTPSConnection,
    addresses: tuple[tuple[object, ...], ...],
    *,
    deadline_at: float,
) -> str | None:
    """Connect/TLS only to the completed DNS result within the same deadline."""

    original_create_connection = getattr(connection, "_create_connection", None)

    def create_connection(
        _address,
        timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
        source_address=None,
    ):
        last_error: OSError | None = None
        for address in addresses:
            if len(address) != 5:
                continue
            family, socket_type, protocol, _canonical_name, socket_address = address
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Vercel connect deadline expired")
            candidate = socket.socket(int(family), int(socket_type), int(protocol))
            try:
                candidate.settimeout(max(0.001, remaining))
                if source_address:
                    candidate.bind(source_address)
                candidate.connect(socket_address)
                return candidate
            except OSError as exc:
                last_error = exc
                candidate.close()
        if time.monotonic() >= deadline_at:
            raise TimeoutError("Vercel connect deadline expired")
        if last_error is not None:
            raise last_error
        raise OSError("Vercel address resolution was unusable")

    try:
        setattr(connection, "_create_connection", create_connection)
        connection.connect()
    except (TimeoutError, socket.timeout):
        return "vercel.request_timeout"
    except Exception:
        return (
            "vercel.request_timeout"
            if time.monotonic() >= deadline_at
            else "vercel.request_unknown"
        )
    finally:
        if original_create_connection is None:
            try:
                delattr(connection, "_create_connection")
            except AttributeError:
                pass
        else:
            setattr(connection, "_create_connection", original_create_connection)
    return None


def _fixed_https_request_result(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    json_body: object,
    params: Mapping[str, str] | None,
    timeout: tuple[float, float],
    maximum_bytes: int,
) -> tuple[VercelHttpResponse | None, str | None]:
    """Return only a bounded response or code from the secret-bearing frame."""

    connection: http.client.HTTPSConnection | None = None
    response: http.client.HTTPResponse | None = None
    timer: threading.Timer | None = None
    active_socket: object | None = None
    published_tls_socket: list[object | None] = [None]
    result: VercelHttpResponse | None = None
    failure_code: str | None = None
    expired = threading.Event()
    deadline_at: float | None = None

    def close_active_socket() -> None:
        socket_to_close = active_socket
        if socket_to_close is None:
            socket_to_close = published_tls_socket[0]
        if socket_to_close is None and connection is not None:
            socket_to_close = getattr(connection, "sock", None)
        if socket_to_close is not None:
            try:
                socket_to_close.shutdown(socket.SHUT_RDWR)  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                socket_to_close.close()  # type: ignore[attr-defined]
            except Exception:
                pass

    try:
        parsed = urlsplit(url)
        if (
            method not in {"GET", "POST"}
            or parsed.scheme != "https"
            or parsed.hostname not in _ALLOWED_HOSTS
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not isinstance(timeout, tuple)
            or len(timeout) != 2
            or any(
                not isinstance(value, (int, float))
                or not 0 < float(value) <= 300
                for value in timeout
            )
            or not 1 <= maximum_bytes <= 1024 * 1024
        ):
            return None, "vercel.request_invalid"
        try:
            body = json.dumps(
                json_body,
                ensure_ascii=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("ascii")
        except (TypeError, ValueError, RecursionError):
            return None, "vercel.request_invalid"
        request_headers = dict(headers)
        if any(
            name.lower()
            in {"host", "content-length", "transfer-encoding", "connection"}
            for name in request_headers
        ):
            return None, "vercel.request_invalid"
        query = parsed.query
        if params:
            encoded = urlencode(dict(params), doseq=False, safe="")
            query = f"{query}&{encoded}" if query else encoded
        target = parsed.path or "/"
        if query:
            target = f"{target}?{query}"

        total_seconds = float(timeout[0]) + float(timeout[1])
        deadline_at = time.monotonic() + total_seconds
        addresses, failure_code = _resolve_before_deadline(
            str(parsed.hostname),
            443,
            deadline_at=deadline_at,
            maximum_seconds=float(timeout[0]),
        )
        if failure_code is not None or addresses is None:
            return None, failure_code or "vercel.request_unknown"
        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            return None, "vercel.request_timeout"
        tls_context = _DeadlineSSLContext(
            ssl.create_default_context(),
            published_tls_socket,
            expired,
            deadline_at,
        )
        connection = http.client.HTTPSConnection(
            parsed.hostname,
            443,
            timeout=max(0.001, min(float(timeout[0]), remaining)),
            context=tls_context,  # type: ignore[arg-type]
        )

        def expire_request() -> None:
            expired.set()
            # HTTP/1.1 ``Connection: close`` responses transfer ownership to
            # HTTPResponse and clear ``connection.sock``. Keep the connected
            # socket itself so a stalled body read is still interruptible.
            close_active_socket()
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            try:
                connection.close()
            except Exception:
                pass

        remaining = deadline_at - time.monotonic()
        if remaining <= 0:
            return None, "vercel.request_timeout"
        timer = threading.Timer(remaining, expire_request)
        timer.daemon = True
        timer.start()
        failure_code = _connect_resolved_before_deadline(
            connection,
            addresses,
            deadline_at=deadline_at,
        )
        if expired.is_set():
            return None, "vercel.request_timeout"
        if failure_code is not None:
            return None, failure_code
        active_socket = connection.sock
        remaining = deadline_at - time.monotonic()
        if expired.is_set() or remaining <= 0:
            return None, "vercel.request_timeout"
        if active_socket is not None:
            active_socket.settimeout(  # type: ignore[attr-defined]
                max(0.001, min(float(timeout[1]), remaining))
            )
        connection.request(
            method,
            target,
            body=body,
            headers={**request_headers, "Content-Length": str(len(body))},
        )
        remaining = deadline_at - time.monotonic()
        if expired.is_set() or remaining <= 0:
            return None, "vercel.request_timeout"
        if active_socket is not None:
            active_socket.settimeout(  # type: ignore[attr-defined]
                max(0.001, min(float(timeout[1]), remaining))
            )
        response = connection.getresponse()
        declared = response.headers.get("content-length")
        if declared is not None and (
            not re.fullmatch(r"[0-9]{1,10}", declared)
            or int(declared) > maximum_bytes
        ):
            failure_code = "vercel.response_too_large"
        else:
            chunks: list[bytes] = []
            total = 0
            while failure_code is None:
                remaining = deadline_at - time.monotonic()
                if expired.is_set() or remaining <= 0:
                    failure_code = "vercel.request_timeout"
                    break
                if active_socket is not None:
                    active_socket.settimeout(  # type: ignore[attr-defined]
                        max(0.001, min(float(timeout[1]), remaining))
                    )
                chunk = response.read(min(16 * 1024, maximum_bytes + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    failure_code = "vercel.response_too_large"
                    break
                chunks.append(chunk)
            if failure_code is None and expired.is_set():
                failure_code = "vercel.request_timeout"
            if failure_code is None:
                result = VercelHttpResponse(
                    status_code=int(response.status),
                    body=b"".join(chunks),
                    content_type=str(response.headers.get("content-type") or ""),
                )
    except (TimeoutError, socket.timeout):
        failure_code = "vercel.request_timeout"
    except Exception:
        failure_code = (
            "vercel.request_timeout"
            if expired.is_set()
            or (deadline_at is not None and time.monotonic() >= deadline_at)
            else "vercel.request_unknown"
        )
    finally:
        if timer is not None:
            timer.cancel()
        # Every provider operation is one-shot. Closing the retained socket
        # here also covers a deadline firing just before the connect phase
        # publishes that socket to the timer callback.
        close_active_socket()
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    if failure_code is not None:
        return None, failure_code
    if result is None:
        return None, "vercel.request_unknown"
    return result, None


def fixed_https_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    json_body: object,
    params: Mapping[str, str] | None,
    timeout: tuple[float, float],
    maximum_bytes: int,
) -> VercelHttpResponse:
    """Make one bounded request to a fixed Vercel host without redirects."""

    result, failure_code = _fixed_https_request_result(
        method,
        url,
        headers=headers,
        json_body=json_body,
        params=params,
        timeout=timeout,
        maximum_bytes=maximum_bytes,
    )
    # Rebind secret-bearing arguments before raising from this public frame.
    headers = {}
    json_body = None
    params = None
    if failure_code is not None:
        raise VercelInfrastructureError(failure_code)
    if result is None:
        raise VercelInfrastructureError("vercel.request_unknown")
    return result


@dataclass(frozen=True)
class VercelCapabilityResult:
    capability: str
    status: str
    cleanup: str | None = None

    def public_summary(self) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": 1,
            "capability": self.capability,
            "status": self.status,
        }
        if self.cleanup is not None:
            result["cleanup"] = self.cleanup
        return result


def _bearer_headers(value: str, *, accept: str = "application/json") -> dict[str, str]:
    return {
        "Accept": accept,
        "Authorization": f"Bearer {value}",
        "Content-Type": "application/json",
        "User-Agent": "mentat-vercel-adapter/1",
    }


def _require_success(response: VercelHttpResponse, code: str) -> None:
    if not 200 <= response.status_code < 300:
        raise VercelInfrastructureError(code)


def _remote_id(value: object, code: str) -> str:
    if not isinstance(value, str) or not _SAFE_REMOTE_ID.fullmatch(value):
        raise VercelInfrastructureError(code)
    return value


def _sandbox_readiness_result(
    requester: RequestFunction,
    connection: VercelConnection,
    environment: Mapping[str, str],
) -> tuple[VercelCapabilityResult | None, str | None]:
    """Perform the secret-bearing Sandbox flow without escaping exceptions."""

    if (
        connection.state != "configured"
        or connection.team_id is None
        or connection.project_id is None
    ):
        return None, "vercel.sandbox_not_configured"
    try:
        credential = credential_for_vercel_api(connection, environment)
    except Exception:
        return None, "vercel.sandbox_auth_required"
    if credential is None:
        return None, "vercel.sandbox_auth_required"
    headers = _bearer_headers(credential)
    params = {"teamId": connection.team_id}
    session_id: str | None = None
    probe_ready = False
    cleanup_ready = False
    probe_error: str | None = None
    try:
        created = requester(
            "POST",
            f"{SANDBOX_API_BASE}/v2/sandboxes",
            headers=headers,
            json_body={
                "projectId": connection.project_id,
                "runtime": "node24",
                "timeout": SANDBOX_TIMEOUT_MILLISECONDS,
                "persistent": False,
            },
            params=params,
            timeout=(5.0, 30.0),
            maximum_bytes=MAX_JSON_RESPONSE_BYTES,
        )
        _require_success(created, "vercel.sandbox_create_failed")
        payload = created.json_object()
        sandbox = payload.get("sandbox")
        if not isinstance(sandbox, dict):
            raise VercelInfrastructureError("vercel.sandbox_response_invalid")
        # Preserve this validated cleanup handle even when later fields fail.
        session_id = _remote_id(
            sandbox.get("currentSessionId"),
            "vercel.sandbox_response_invalid",
        )
        if sandbox.get("persistent") is not False:
            raise VercelInfrastructureError("vercel.sandbox_response_invalid")
        session = payload.get("session")
        if not isinstance(session, dict) or session.get("id") != session_id:
            raise VercelInfrastructureError("vercel.sandbox_response_invalid")

        command = requester(
            "POST",
            f"{SANDBOX_API_BASE}/v2/sandboxes/sessions/{quote(session_id, safe='')}/cmd",
            headers=_bearer_headers(
                credential,
                accept="application/x-ndjson",
            ),
            json_body={
                "command": FIXED_SANDBOX_COMMAND,
                "args": list(FIXED_SANDBOX_ARGUMENTS),
                "sudo": False,
                "wait": True,
                "logs": True,
                "timeout": COMMAND_TIMEOUT_MILLISECONDS,
            },
            params={**params, "wait": "true", "logs": "true"},
            timeout=(5.0, 25.0),
            maximum_bytes=MAX_SANDBOX_STREAM_BYTES,
        )
        _require_success(command, "vercel.sandbox_probe_failed")
        VercelSandboxAdapter._validate_command_stream(
            command,
            session_id=session_id,
        )
        probe_ready = True
    except VercelInfrastructureError as exc:
        probe_error = exc.code
    except Exception:
        probe_error = "vercel.sandbox_probe_failed"
    finally:
        if session_id is not None:
            try:
                stopped = requester(
                    "POST",
                    f"{SANDBOX_API_BASE}/v2/sandboxes/sessions/{quote(session_id, safe='')}/stop",
                    headers=headers,
                    json_body={},
                    params=params,
                    timeout=(5.0, 20.0),
                    maximum_bytes=MAX_JSON_RESPONSE_BYTES,
                )
                _require_success(stopped, "vercel.sandbox_cleanup_failed")
                stopped_payload = stopped.json_object()
                stopped_session = stopped_payload.get("session")
                cleanup_ready = (
                    set(stopped_payload).issubset(
                        {"session", "sandbox", "snapshot"}
                    )
                    and isinstance(stopped_session, dict)
                    and stopped_session.get("id") == session_id
                    and stopped_session.get("status") == "stopped"
                )
            except Exception:
                cleanup_ready = False
    if session_id is not None and not cleanup_ready:
        return None, "vercel.sandbox_cleanup_failed"
    if probe_error is not None:
        return None, probe_error
    if not probe_ready:
        return None, "vercel.sandbox_probe_failed"
    return (
        VercelCapabilityResult(
            capability="sandbox.readiness",
            status="ready",
            cleanup="verified",
        ),
        None,
    )


class VercelSandboxAdapter:
    """Expose only a non-persistent Node 24 readiness probe."""

    def __init__(self, requester: RequestFunction = fixed_https_request):
        self.requester = requester

    def test_readiness(
        self,
        connection: VercelConnection,
        *,
        environment: Mapping[str, str],
    ) -> VercelCapabilityResult:
        result, failure_code = _sandbox_readiness_result(
            self.requester,
            connection,
            environment,
        )
        # The implementation frame has already returned. Rebind the remaining
        # references before raising a public bounded error.
        self = None  # type: ignore[assignment]
        connection = None  # type: ignore[assignment]
        environment = {}
        if failure_code is not None:
            raise VercelInfrastructureError(failure_code)
        if result is None:
            raise VercelInfrastructureError("vercel.sandbox_probe_failed")
        return result

    @staticmethod
    def _validate_command_stream(
        response: VercelHttpResponse,
        *,
        session_id: str,
    ) -> None:
        if not (
            response.content_type.lower().startswith("application/x-ndjson")
            or response.content_type.lower().startswith("application/jsonl")
        ):
            raise VercelInfrastructureError("vercel.sandbox_response_invalid")
        invalid = False
        try:
            lines = response.body.decode("utf-8").splitlines()
            records = [json.loads(line) for line in lines if line]
        except (UnicodeDecodeError, json.JSONDecodeError):
            invalid = True
            records = []
        if invalid:
            raise VercelInfrastructureError("vercel.sandbox_response_invalid")
        if not records or any(not isinstance(record, dict) for record in records):
            raise VercelInfrastructureError("vercel.sandbox_response_invalid")
        metadata: list[dict[str, object]] = []
        stdout: list[str] = []
        stderr: list[str] = []
        for record in records:
            if isinstance(record.get("command"), dict):
                metadata.append(record["command"])
                continue
            stream = record.get("stream")
            data = record.get("data")
            if stream == "stdout" and isinstance(data, str):
                stdout.append(data)
            elif stream == "stderr" and isinstance(data, str):
                stderr.append(data)
            else:
                raise VercelInfrastructureError("vercel.sandbox_response_invalid")
        if len(metadata) != 2:
            raise VercelInfrastructureError("vercel.sandbox_response_invalid")
        initial, final = metadata
        command_id = _remote_id(initial.get("id"), "vercel.sandbox_response_invalid")
        if (
            final.get("id") != command_id
            or initial.get("sessionId") != session_id
            or final.get("sessionId") != session_id
            or final.get("exitCode") != 0
            or "".join(stderr)
            or not _NODE_24_READY.fullmatch("".join(stdout))
        ):
            raise VercelInfrastructureError("vercel.sandbox_probe_failed")


def _connect_readiness_result(
    requester: RequestFunction,
    connection: VercelConnection,
    environment: Mapping[str, str],
) -> tuple[VercelCapabilityResult | None, str | None]:
    """Perform the secret-bearing Connect canary without escaping exceptions."""

    if connection.state != "configured" or connection.connector is None:
        return None, "vercel.connect_not_configured"
    try:
        credential = credential_for_connect(environment)
    except Exception:
        return None, "vercel.connect_auth_required"
    if credential is None:
        return None, "vercel.connect_auth_required"
    body: dict[str, object] = {"subject": {"type": "app"}}
    if connection.connect_scopes:
        body["scopes"] = list(connection.connect_scopes)
    connector_path = quote(connection.connector, safe="/._-")
    try:
        response = requester(
            "POST",
            f"{CONNECT_API_BASE}/{connector_path}",
            headers=_bearer_headers(credential),
            json_body=body,
            params=None,
            timeout=(5.0, 20.0),
            maximum_bytes=MAX_JSON_RESPONSE_BYTES,
        )
        _require_success(response, "vercel.connect_request_failed")
        payload = response.json_object()
        issued_token = payload.get("token")
        if (
            not isinstance(issued_token, str)
            or not 1 <= len(issued_token) <= 65_536
            or not issued_token.isascii()
            or issued_token.strip() != issued_token
            or any(
                ord(character) <= 32 or ord(character) == 127
                for character in issued_token
            )
        ):
            return None, "vercel.connect_response_invalid"
    except VercelInfrastructureError as exc:
        return None, exc.code
    except Exception:
        return None, "vercel.connect_request_failed"
    # Deliberately return no token or provider metadata.
    return VercelCapabilityResult(capability="connect.token", status="ready"), None


class VercelConnectAdapter:
    """Request one app-scoped token canary, validate it, and discard it."""

    def __init__(self, requester: RequestFunction = fixed_https_request):
        self.requester = requester

    def test_readiness(
        self,
        connection: VercelConnection,
        *,
        environment: Mapping[str, str],
    ) -> VercelCapabilityResult:
        result, failure_code = _connect_readiness_result(
            self.requester,
            connection,
            environment,
        )
        self = None  # type: ignore[assignment]
        connection = None  # type: ignore[assignment]
        environment = {}
        if failure_code is not None:
            raise VercelInfrastructureError(failure_code)
        if result is None:
            raise VercelInfrastructureError("vercel.connect_response_invalid")
        return result


__all__ = [
    "COMMAND_TIMEOUT_MILLISECONDS",
    "CONNECT_API_BASE",
    "FIXED_SANDBOX_ARGUMENTS",
    "FIXED_SANDBOX_COMMAND",
    "RequestFunction",
    "SANDBOX_API_BASE",
    "SANDBOX_TIMEOUT_MILLISECONDS",
    "VercelCapabilityResult",
    "VercelConnectAdapter",
    "VercelHttpResponse",
    "VercelInfrastructureError",
    "VercelSandboxAdapter",
    "fixed_https_request",
]
