from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
import time
import unittest
from unittest.mock import patch

from vercel_connections import VercelConnection
from vercel_infrastructure import (
    FIXED_SANDBOX_ARGUMENTS,
    VercelConnectAdapter,
    VercelHttpResponse,
    VercelInfrastructureError,
    VercelSandboxAdapter,
    _DeadlineSSLContext,
    fixed_https_request,
)


AUTHORIZATION_SECRET_CANARY = "authorization-secret-canary"  # pragma: allowlist secret
MANAGEMENT_SECRET_CANARY = "management-secret-canary"  # pragma: allowlist secret
OIDC_SECRET_CANARY = "oidc-secret-canary"  # pragma: allowlist secret
PROVIDER_TOKEN_SECRET_CANARY = "provider-token-secret-canary"  # pragma: allowlist secret
RAW_PROVIDER_SECRET_CANARY = "raw-provider-secret-canary"  # pragma: allowlist secret
TEST_ADDRESSES = (
    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
)


def connection(**overrides) -> VercelConnection:
    values = {
        "id": "connection_vercel",
        "label": "Vercel",
        "state": "configured",
        "auth_kind": "api_key",
        "model": "openai/gpt-5.4",
        "team_id": "team_mentat",
        "project_id": "prj_mentat",
        "connector": "github/mentat",
        "connect_scopes": ("contents:read",),
        "revision": 1,
        "created_at": 1.0,
        "updated_at": 1.0,
    }
    values.update(overrides)
    return VercelConnection(**values)


class SequenceRequester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def json_response(payload, status=200):
    return VercelHttpResponse(
        status_code=status,
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )


def command_response(*, output="mentat-sandbox-ready:24.19.0", exit_code=0):
    rows = [
        {"command": {"id": "cmd_ready", "sessionId": "session_ready"}},
        {"stream": "stdout", "data": output},
        {
            "command": {
                "id": "cmd_ready",
                "sessionId": "session_ready",
                "exitCode": exit_code,
            }
        },
    ]
    return VercelHttpResponse(
        status_code=200,
        body=("\n".join(json.dumps(row) for row in rows) + "\n").encode("utf-8"),
        content_type="application/x-ndjson",
    )


def exception_graph_text(error: BaseException) -> str:
    seen: set[int] = set()
    pending: list[object] = [error]
    values: list[str] = []
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        values.append(repr(value))
        if isinstance(value, BaseException):
            pending.extend([value.__cause__, value.__context__, value.args])
            pending.extend(vars(value).values())
            traceback = value.__traceback__
            while traceback is not None:
                pending.append(traceback.tb_frame.f_locals)
                traceback = traceback.tb_next
        elif isinstance(value, dict):
            pending.extend(value.items())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
    return "\n".join(values)


def capture_vercel_error(operation) -> VercelInfrastructureError:
    """Catch below the test frame so only product traceback locals are inspected."""

    try:
        operation()
    except VercelInfrastructureError as error:
        operation = None
        return error
    raise AssertionError("Vercel failure was required")


class VercelInfrastructureTests(unittest.TestCase):
    def test_deadline_ssl_context_preserves_https_constructor_contract(self):
        delegate = ssl.create_default_context()
        published_socket = [None]
        context = _DeadlineSSLContext(
            delegate,
            published_socket,
            threading.Event(),
            time.monotonic() + 1,
        )

        connection = http.client.HTTPSConnection(
            "api.vercel.com",
            443,
            context=context,  # type: ignore[arg-type]
        )

        self.assertIs(connection._context, context)
        self.assertEqual(context.verify_mode, delegate.verify_mode)
        self.assertEqual(context.check_hostname, delegate.check_hostname)
        context.check_hostname = False
        self.assertFalse(delegate.check_hostname)
        connection.close()

    def test_sandbox_probe_is_fixed_nonpersistent_node_24_and_cleanup_is_verified(self):
        requester = SequenceRequester(
            [
                json_response(
                    {
                        "sandbox": {
                            "name": "sandbox_ready",
                            "currentSessionId": "session_ready",
                            "persistent": False,
                        },
                        "session": {"id": "session_ready"},
                    }
                ),
                command_response(),
                json_response(
                    {"session": {"id": "session_ready", "status": "stopped"}}
                ),
            ]
        )
        result = VercelSandboxAdapter(requester).test_readiness(
            connection(), environment={"VERCEL_TOKEN": "management-secret-canary"}  # pragma: allowlist secret
        )
        self.assertEqual(
            result.public_summary(),
            {
                "schema_version": 1,
                "capability": "sandbox.readiness",
                "status": "ready",
                "cleanup": "verified",
            },
        )
        self.assertEqual(len(requester.calls), 3)
        create = requester.calls[0]
        self.assertEqual(create[1], "https://api.vercel.com/v2/sandboxes")
        self.assertEqual(
            create[2]["json_body"],
            {
                "projectId": "prj_mentat",
                "runtime": "node24",
                "timeout": 60_000,
                "persistent": False,
            },
        )
        command = requester.calls[1]
        self.assertEqual(command[2]["json_body"]["command"], "node")
        self.assertEqual(tuple(command[2]["json_body"]["args"]), FIXED_SANDBOX_ARGUMENTS)
        self.assertIs(command[2]["json_body"]["sudo"], False)
        self.assertTrue(requester.calls[2][1].endswith("/session_ready/stop"))

    def test_transport_rejects_non_api_sandbox_host(self):
        with self.assertRaisesRegex(
            VercelInfrastructureError,
            "vercel.request_invalid",
        ):
            fixed_https_request(
                "POST",
                "https://vercel.com/v2/sandboxes",
                headers={"Accept": "application/json"},
                json_body={},
                params=None,
                timeout=(1.0, 1.0),
                maximum_bytes=1024,
            )

    def test_sandbox_malformed_probe_still_attempts_cleanup(self):
        requester = SequenceRequester(
            [
                json_response(
                    {
                        "sandbox": {
                            "currentSessionId": "session_ready",
                            "persistent": False,
                        },
                        "session": {"id": "session_ready"},
                    }
                ),
                command_response(output="injected-output"),
                json_response(
                    {"session": {"id": "session_ready", "status": "stopped"}}
                ),
            ]
        )
        with self.assertRaisesRegex(VercelInfrastructureError, "vercel.sandbox_probe_failed"):
            VercelSandboxAdapter(requester).test_readiness(
                connection(), environment={"VERCEL_TOKEN": "management-secret-canary"}  # pragma: allowlist secret
            )
        self.assertEqual(len(requester.calls), 3)
        self.assertTrue(requester.calls[-1][1].endswith("/stop"))

    def test_sandbox_cleanup_failure_never_claims_readiness(self):
        requester = SequenceRequester(
            [
                json_response(
                    {
                        "sandbox": {
                            "currentSessionId": "session_ready",
                            "persistent": False,
                        },
                        "session": {"id": "session_ready"},
                    }
                ),
                command_response(),
                json_response(
                    {"session": {"id": "different", "status": "stopped"}}
                ),
            ]
        )
        with self.assertRaisesRegex(VercelInfrastructureError, "vercel.sandbox_cleanup_failed"):
            VercelSandboxAdapter(requester).test_readiness(
                connection(), environment={"VERCEL_TOKEN": "management-secret-canary"}  # pragma: allowlist secret
            )

    def test_sandbox_cleanup_requires_stopped_and_overrides_probe_failure(self):
        for stopped in (
            {"session": {"id": "session_ready"}},
            {"session": {"id": "session_ready", "status": "stopping"}},
        ):
            requester = SequenceRequester(
                [
                    json_response(
                        {
                            "sandbox": {
                                "currentSessionId": "session_ready",
                                "persistent": False,
                            },
                            "session": {"id": "session_ready"},
                        }
                    ),
                    command_response(output="wrong-runtime"),
                    json_response(stopped),
                ]
            )
            with self.assertRaisesRegex(
                VercelInfrastructureError,
                "vercel.sandbox_cleanup_failed",
            ):
                VercelSandboxAdapter(requester).test_readiness(
                    connection(),
                    environment={"VERCEL_TOKEN": "management-secret-canary"},  # pragma: allowlist secret
                )

    def test_sandbox_requires_temporary_state_and_exact_session_then_cleans_up(self):
        malformed = (
            {
                "sandbox": {"currentSessionId": "session_ready"},
                "session": {"id": "session_ready"},
            },
            {
                "sandbox": {
                    "currentSessionId": "session_ready",
                    "persistent": True,
                },
                "session": {"id": "session_ready"},
            },
            {
                "sandbox": {
                    "currentSessionId": "session_ready",
                    "persistent": False,
                },
            },
            {
                "sandbox": {
                    "currentSessionId": "session_ready",
                    "persistent": False,
                },
                "session": {"id": "session_other"},
            },
        )
        for payload in malformed:
            with self.subTest(payload=payload):
                requester = SequenceRequester(
                    [
                        json_response(payload),
                        json_response(
                            {
                                "session": {
                                    "id": "session_ready",
                                    "status": "stopped",
                                }
                            }
                        ),
                    ]
                )
                with self.assertRaisesRegex(
                    VercelInfrastructureError,
                    "vercel.sandbox_response_invalid",
                ):
                    VercelSandboxAdapter(requester).test_readiness(
                        connection(),
                        environment={"VERCEL_TOKEN": "management-secret-canary"},  # pragma: allowlist secret
                    )
                self.assertEqual(len(requester.calls), 2)
                self.assertTrue(requester.calls[-1][1].endswith("/session_ready/stop"))

    def test_sandbox_rejects_non_string_session_identifiers(self):
        for supplied in (True, 7):
            with self.subTest(supplied=supplied):
                requester = SequenceRequester(
                    [
                        json_response(
                            {
                                "sandbox": {
                                    "currentSessionId": supplied,
                                    "persistent": False,
                                },
                                "session": {"id": str(supplied)},
                            }
                        )
                    ]
                )
                with self.assertRaisesRegex(
                    VercelInfrastructureError,
                    "vercel.sandbox_response_invalid",
                ):
                    VercelSandboxAdapter(requester).test_readiness(
                        connection(),
                        environment={"VERCEL_TOKEN": MANAGEMENT_SECRET_CANARY},
                    )
                self.assertEqual(len(requester.calls), 1)

    def test_connect_requests_only_app_subject_and_configured_scopes_then_discards_token(self):
        token = "provider-token-secret-canary"  # pragma: allowlist secret
        requester = SequenceRequester(
            [
                json_response(
                    {
                        "token": token,
                        "connector": {
                            "id": "provider-private-connector",
                            "name": "Private connector metadata",
                        },
                    }
                )
            ]
        )
        result = VercelConnectAdapter(requester).test_readiness(
            connection(), environment={"VERCEL_OIDC_TOKEN": "oidc-secret-canary"}  # pragma: allowlist secret
        )
        self.assertEqual(
            result.public_summary(),
            {"schema_version": 1, "capability": "connect.token", "status": "ready"},
        )
        call = requester.calls[0]
        self.assertEqual(
            call[1],
            "https://api.vercel.com/v1/connect/token/github/mentat",
        )
        self.assertEqual(
            call[2]["json_body"],
            {"subject": {"type": "app"}, "scopes": ["contents:read"]},
        )
        self.assertNotIn(token, json.dumps(result.public_summary()))

    def test_connect_failures_and_missing_auth_are_bounded_without_token_text(self):
        with self.assertRaisesRegex(VercelInfrastructureError, "vercel.connect_auth_required"):
            VercelConnectAdapter(SequenceRequester([])).test_readiness(
                connection(), environment={}
            )
        token = PROVIDER_TOKEN_SECRET_CANARY
        requester = SequenceRequester([json_response({"token": token, "extra": token}, 500)])
        try:
            VercelConnectAdapter(requester).test_readiness(
                connection(), environment={"VERCEL_OIDC_TOKEN": "oidc"}
            )
        except VercelInfrastructureError as exc:
            self.assertEqual(exc.code, "vercel.connect_request_failed")
            self.assertNotIn(token, str(exc))
        else:  # pragma: no cover - failure is required
            self.fail("Connect failure was not raised")

    def test_transport_rejects_non_vercel_hosts_before_network(self):
        with self.assertRaisesRegex(VercelInfrastructureError, "vercel.request_invalid"):
            fixed_https_request(
                "POST",
                "https://example.com/operator-input",
                headers={},
                json_body={},
                params=None,
                timeout=(1.0, 1.0),
                maximum_bytes=1024,
            )

    def test_transport_dns_phase_obeys_the_absolute_deadline(self):
        release = threading.Event()
        resolved = threading.Event()
        network_actions = []

        def slow_dns(*_args, **_kwargs):
            release.wait(1)
            resolved.set()
            return list(TEST_ADDRESSES)

        class ForbiddenConnection:
            def __init__(self, *_args, **_kwargs):
                network_actions.append("connection-created")

        started = time.monotonic()
        try:
            with patch.object(
                socket, "getaddrinfo", side_effect=slow_dns
            ), patch(
                "vercel_infrastructure.http.client.HTTPSConnection",
                ForbiddenConnection,
            ):
                error = capture_vercel_error(
                    lambda: fixed_https_request(
                        "POST",
                        "https://api.vercel.com/v1/connect/token/github/mentat",
                        headers={
                            "Authorization": f"Bearer {AUTHORIZATION_SECRET_CANARY}"
                        },
                        json_body={"subject": {"type": "app"}},
                        params=None,
                        timeout=(0.02, 0.03),
                        maximum_bytes=1024,
                    )
                )
        finally:
            release.set()
            self.assertTrue(resolved.wait(1))
        self.assertEqual(error.code, "vercel.request_timeout")
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(network_actions, [])
        self.assertNotIn(AUTHORIZATION_SECRET_CANARY, exception_graph_text(error))

    def test_transport_connect_phase_obeys_the_absolute_deadline(self):
        class SlowConnection:
            def __init__(self, *_args, **_kwargs):
                self.sock = None
                self.closed = threading.Event()

            def connect(self):
                self.closed.wait(1)
                raise OSError(AUTHORIZATION_SECRET_CANARY)

            def request(self, *_args, **_kwargs):
                raise AssertionError("credentials must not be sent before connect")

            def close(self):
                self.closed.set()

        started = time.monotonic()
        with patch(
            "vercel_infrastructure.http.client.HTTPSConnection",
            SlowConnection,
        ), patch(
            "vercel_infrastructure._resolve_before_deadline",
            return_value=(TEST_ADDRESSES, None),
        ):
            error = capture_vercel_error(
                lambda: fixed_https_request(
                    "POST",
                    "https://api.vercel.com/v1/connect/token/github/mentat",
                    headers={
                        "Authorization": f"Bearer {AUTHORIZATION_SECRET_CANARY}"
                    },
                    json_body={"subject": {"type": "app"}},
                    params=None,
                    timeout=(0.02, 0.03),
                    maximum_bytes=1024,
                )
            )
        self.assertEqual(error.code, "vercel.request_timeout")
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertNotIn(AUTHORIZATION_SECRET_CANARY, exception_graph_text(error))

    def test_expired_timer_overrides_connect_unknown_classification(self):
        class ImmediateTimer:
            daemon = False

            def __init__(self, _interval, callback):
                self.callback = callback

            def start(self):
                self.callback()

            def cancel(self):
                return None

        class InterruptedConnection:
            def __init__(self, *_args, **_kwargs):
                self.sock = None

            def request(self, *_args, **_kwargs):
                raise AssertionError("request must not run after deadline expiry")

            def close(self):
                return None

        with patch(
            "vercel_infrastructure.http.client.HTTPSConnection",
            InterruptedConnection,
        ), patch(
            "vercel_infrastructure.threading.Timer",
            ImmediateTimer,
        ), patch(
            "vercel_infrastructure._resolve_before_deadline",
            return_value=(TEST_ADDRESSES, None),
        ), patch(
            "vercel_infrastructure._connect_resolved_before_deadline",
            return_value="vercel.request_unknown",
        ):
            error = capture_vercel_error(
                lambda: fixed_https_request(
                    "POST",
                    "https://api.vercel.com/v1/connect/token/github/mentat",
                    headers={
                        "Authorization": f"Bearer {AUTHORIZATION_SECRET_CANARY}"
                    },
                    json_body={"subject": {"type": "app"}},
                    params=None,
                    timeout=(0.02, 0.03),
                    maximum_bytes=1024,
                )
            )
        self.assertEqual(error.code, "vercel.request_timeout")
        self.assertNotIn(AUTHORIZATION_SECRET_CANARY, exception_graph_text(error))

    def test_transport_publishes_tls_socket_before_blocking_handshake(self):
        raw_sockets = []
        tls_sockets = []

        class DetachedRawSocket:
            def __init__(self):
                self.closed = threading.Event()

            def shutdown(self, _how):
                self.closed.set()

            def close(self):
                self.closed.set()

        class BlockingTLSSocket:
            def __init__(self):
                self.closed = threading.Event()

            def settimeout(self, _value):
                return None

            def do_handshake(self):
                self.closed.wait(1)
                raise OSError(AUTHORIZATION_SECRET_CANARY)

            def shutdown(self, _how):
                self.closed.set()

            def close(self):
                self.closed.set()

        class BlockingContext:
            def wrap_socket(self, _raw_socket, **kwargs):
                self.assertions = kwargs
                tls_socket = BlockingTLSSocket()
                tls_sockets.append(tls_socket)
                return tls_socket

        class HandshakeConnection:
            def __init__(self, host, _port, **kwargs):
                self.host = host
                self._context = kwargs["context"]
                self.sock = DetachedRawSocket()
                raw_sockets.append(self.sock)

            def connect(self):
                raw_socket = self.sock
                self.sock = self._context.wrap_socket(
                    raw_socket,
                    server_hostname=self.host,
                )

            def request(self, *_args, **_kwargs):
                raise AssertionError("request must not run after a TLS timeout")

            def close(self):
                # Model HTTPSConnection.sock still referencing the detached
                # raw socket while SSLContext.wrap_socket blocks.
                return None

        context = BlockingContext()
        started = time.monotonic()
        with patch(
            "vercel_infrastructure.http.client.HTTPSConnection",
            HandshakeConnection,
        ), patch(
            "vercel_infrastructure.ssl.create_default_context",
            return_value=context,
        ), patch(
            "vercel_infrastructure._resolve_before_deadline",
            return_value=(TEST_ADDRESSES, None),
        ):
            error = capture_vercel_error(
                lambda: fixed_https_request(
                    "POST",
                    "https://api.vercel.com/v1/connect/token/github/mentat",
                    headers={
                        "Authorization": f"Bearer {AUTHORIZATION_SECRET_CANARY}"
                    },
                    json_body={"subject": {"type": "app"}},
                    params=None,
                    timeout=(0.02, 0.03),
                    maximum_bytes=1024,
                )
            )
        self.assertEqual(error.code, "vercel.request_timeout")
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(len(raw_sockets), 1)
        self.assertEqual(len(tls_sockets), 1)
        self.assertFalse(raw_sockets[0].closed.is_set())
        self.assertTrue(tls_sockets[0].closed.is_set())
        self.assertFalse(context.assertions["do_handshake_on_connect"])
        self.assertEqual(context.assertions["server_hostname"], "api.vercel.com")
        self.assertNotIn(AUTHORIZATION_SECRET_CANARY, exception_graph_text(error))

    def test_transport_write_and_header_phases_obey_the_absolute_deadline(self):
        class SocketStub:
            def settimeout(self, _value):
                return None

        for phase in ("write", "headers"):
            with self.subTest(phase=phase):
                class SlowConnection:
                    def __init__(self, *_args, **_kwargs):
                        self.sock = SocketStub()
                        self.closed = threading.Event()

                    def connect(self):
                        return None

                    def request(self, *_args, **_kwargs):
                        if phase == "write":
                            self.closed.wait(1)
                            raise OSError(AUTHORIZATION_SECRET_CANARY)

                    def getresponse(self):
                        self.closed.wait(1)
                        raise OSError(AUTHORIZATION_SECRET_CANARY)

                    def close(self):
                        self.closed.set()

                started = time.monotonic()
                with patch(
                    "vercel_infrastructure.http.client.HTTPSConnection",
                    SlowConnection,
                ), patch(
                    "vercel_infrastructure._resolve_before_deadline",
                    return_value=(TEST_ADDRESSES, None),
                ):
                    error = capture_vercel_error(
                        lambda: fixed_https_request(
                            "POST",
                            "https://api.vercel.com/v1/connect/token/github/mentat",
                            headers={
                                "Authorization": (
                                    f"Bearer {AUTHORIZATION_SECRET_CANARY}"
                                )
                            },
                            json_body={"subject": {"type": "app"}},
                            params=None,
                            timeout=(0.02, 0.03),
                            maximum_bytes=1024,
                        )
                    )
                self.assertEqual(error.code, "vercel.request_timeout")
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertNotIn(
                    AUTHORIZATION_SECRET_CANARY,
                    exception_graph_text(error),
                )

    def test_transport_body_phase_obeys_deadline_and_errors_drop_secret_locals(self):
        class SlowResponse:
            status = 200
            headers = {
                "content-type": "application/json",
                "content-length": "2",
            }

            def __init__(self, closed: threading.Event):
                self.closed = closed

            def read(self, _size):
                self.closed.wait(1)
                raise OSError(AUTHORIZATION_SECRET_CANARY)

            def close(self):
                return None

        class SlowConnection:
            def __init__(self, *_args, **_kwargs):
                self.sock = None
                self.closed = threading.Event()

            def connect(self):
                return None

            def request(self, *_args, **_kwargs):
                return None

            def getresponse(self):
                return SlowResponse(self.closed)

            def close(self):
                self.closed.set()

        started = time.monotonic()
        with patch(
            "vercel_infrastructure.http.client.HTTPSConnection",
            SlowConnection,
        ), patch(
            "vercel_infrastructure._resolve_before_deadline",
            return_value=(TEST_ADDRESSES, None),
        ):
            error = capture_vercel_error(
                lambda: fixed_https_request(
                    "POST",
                    "https://api.vercel.com/v1/connect/token/github/mentat",
                    headers={
                        "Authorization": f"Bearer {AUTHORIZATION_SECRET_CANARY}"
                    },
                    json_body={"subject": {"type": "app"}},
                    params=None,
                    timeout=(0.02, 0.03),
                    maximum_bytes=1024,
                )
            )
        self.assertEqual(error.code, "vercel.request_timeout")
        self.assertNotIn(
            AUTHORIZATION_SECRET_CANARY,
            exception_graph_text(error),
        )
        self.assertLess(time.monotonic() - started, 0.5)

        class DetachedSocket:
            def __init__(self):
                self.closed = threading.Event()

            def settimeout(self, _value):
                return None

            def shutdown(self, _how):
                self.closed.set()

            def close(self):
                self.closed.set()

        class DetachedSlowResponse:
            status = 200
            headers = {
                "content-type": "application/json",
                "content-length": "2",
            }

            def __init__(self, transport: DetachedSocket):
                self.transport = transport

            def read(self, _size):
                self.transport.closed.wait(1)
                raise OSError(AUTHORIZATION_SECRET_CANARY)

            def close(self):
                # Model HTTPResponse owning a socket that is not released by
                # HTTPSConnection.close(), and require direct socket closure.
                return None

        detached_transports = []

        class DetachedSlowConnection:
            def __init__(self, *_args, **_kwargs):
                self.sock = DetachedSocket()
                detached_transports.append(self.sock)

            def connect(self):
                return None

            def request(self, *_args, **_kwargs):
                return None

            def getresponse(self):
                response = DetachedSlowResponse(self.sock)
                self.sock = None
                return response

            def close(self):
                # HTTP/1.1 Connection: close has already detached the socket.
                return None

        started = time.monotonic()
        with patch(
            "vercel_infrastructure.http.client.HTTPSConnection",
            DetachedSlowConnection,
        ), patch(
            "vercel_infrastructure._resolve_before_deadline",
            return_value=(TEST_ADDRESSES, None),
        ):
            detached_error = capture_vercel_error(
                lambda: fixed_https_request(
                    "POST",
                    "https://api.vercel.com/v1/connect/token/github/mentat",
                    headers={
                        "Authorization": f"Bearer {AUTHORIZATION_SECRET_CANARY}"
                    },
                    json_body={"subject": {"type": "app"}},
                    params=None,
                    timeout=(0.02, 0.03),
                    maximum_bytes=1024,
                )
            )
        self.assertEqual(detached_error.code, "vercel.request_timeout")
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(len(detached_transports), 1)
        self.assertTrue(detached_transports[0].closed.is_set())
        self.assertNotIn(
            AUTHORIZATION_SECRET_CANARY,
            exception_graph_text(detached_error),
        )

        malformed_error = capture_vercel_error(
            lambda: VercelHttpResponse(
                status_code=200,
                body=(
                    "{\"token\":\"" + RAW_PROVIDER_SECRET_CANARY
                ).encode("utf-8"),
                content_type="application/json",
            ).json_object()
        )
        self.assertNotIn(
            RAW_PROVIDER_SECRET_CANARY,
            exception_graph_text(malformed_error),
        )

        connect_error = capture_vercel_error(
            lambda: VercelConnectAdapter(
                SequenceRequester(
                    [
                        json_response(
                            {
                                "token": PROVIDER_TOKEN_SECRET_CANARY,
                                "provider": RAW_PROVIDER_SECRET_CANARY,
                            },
                            500,
                        )
                    ]
                )
            ).test_readiness(
                connection(),
                environment={"VERCEL_OIDC_TOKEN": OIDC_SECRET_CANARY},
            )
        )
        connect_graph = exception_graph_text(connect_error)
        self.assertNotIn(PROVIDER_TOKEN_SECRET_CANARY, connect_graph)
        self.assertNotIn(RAW_PROVIDER_SECRET_CANARY, connect_graph)
        self.assertNotIn(OIDC_SECRET_CANARY, connect_graph)

        sandbox_error = capture_vercel_error(
            lambda: VercelSandboxAdapter(
                SequenceRequester(
                    [
                        json_response(
                            {
                                "sandbox": {
                                    "currentSessionId": "session_ready",
                                    "persistent": True,
                                },
                                "session": {"id": "session_ready"},
                                "provider": RAW_PROVIDER_SECRET_CANARY,
                            }
                        ),
                        json_response(
                            {
                                "session": {
                                    "id": "session_ready",
                                    "status": "stopped",
                                }
                            }
                        ),
                    ]
                )
            ).test_readiness(
                connection(),
                environment={"VERCEL_TOKEN": MANAGEMENT_SECRET_CANARY},
            )
        )
        sandbox_graph = exception_graph_text(sandbox_error)
        self.assertNotIn(RAW_PROVIDER_SECRET_CANARY, sandbox_graph)
        self.assertNotIn(MANAGEMENT_SECRET_CANARY, sandbox_graph)


if __name__ == "__main__":
    unittest.main()
