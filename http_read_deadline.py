"""Absolute deadlines for a private, fixed-purpose HTTP GET client.

Only DNS runs in a worker. Two process-wide slots bound stuck resolvers, and
those workers never receive headers or continue into a connection. Socket work
stays on the caller; a scoped timer shuts down its exact socket at the deadline.
"""

from __future__ import annotations

import http.client
import socket
import threading
import time


_DNS_SLOTS = threading.BoundedSemaphore(2)


def _resolve(host: str, port: int, deadline: float):
    if not _DNS_SLOTS.acquire(blocking=False):
        raise TimeoutError("HTTP read resolver unavailable")
    done = threading.Event()
    result: list[object] = []

    def resolve() -> None:
        try:
            result.append(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[:16])
        except Exception:
            result.append(None)
        finally:
            _DNS_SLOTS.release()
            done.set()

    worker = threading.Thread(target=resolve, daemon=True)
    try:
        worker.start()
    except Exception:
        _DNS_SLOTS.release()
        raise
    if not done.wait(max(0, deadline - time.monotonic())):
        raise TimeoutError("HTTP read DNS deadline expired")
    if not result or not result[0]:
        raise OSError("HTTP read DNS unavailable")
    return result[0]


class _DeadlineTLSContext:
    def __init__(self, context, owner):
        self._context = context
        self._owner = owner

    def __getattr__(self, name):
        return getattr(self._context, name)

    def wrap_socket(self, sock, **kwargs):
        handshake = kwargs.pop("do_handshake_on_connect", True)
        secured = self._context.wrap_socket(sock, do_handshake_on_connect=False, **kwargs)
        self._owner._active_socket = secured
        self._owner._check()
        secured.settimeout(self._owner._remaining())
        if handshake:
            secured.do_handshake()
        self._owner._check()
        return secured


class _DeadlineResponse:
    def __init__(self, response, owner):
        self._response = response
        self._owner = owner

    def __getattr__(self, name):
        return getattr(self._response, name)

    def read(self, amount):
        return self._owner._call(self._response.read, amount)


class DeadlineReadConnection:
    """Wrap an owned HTTP connection without adding request authority."""

    def __init__(self, connection, *, deadline_at: float):
        self._connection = connection
        self._deadline = deadline_at
        self._expired = threading.Event()
        self._active_socket = None
        self._response = None
        self._timer = None

    def _remaining(self):
        remaining = self._deadline - time.monotonic()
        if self._expired.is_set() or remaining <= 0:
            raise TimeoutError("HTTP read deadline expired")
        return remaining

    def _check(self):
        self._remaining()

    def _expire(self):
        self._expired.set()
        active = self._active_socket or getattr(self._connection, "sock", None)
        if active is not None:
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                active.close()
            except OSError:
                pass

    def _call(self, operation, *args, **kwargs):
        self._check()
        try:
            if self._active_socket is not None:
                self._active_socket.settimeout(self._remaining())
            result = operation(*args, **kwargs)
        except Exception:
            self._check()
            raise
        self._check()
        return result

    def request(self, method, path, **kwargs):
        if method != "GET":
            raise ValueError("Deadline discovery connections permit only GET")
        self._timer = threading.Timer(self._remaining(), self._expire)
        self._timer.daemon = True
        self._timer.start()
        connection = self._connection
        if isinstance(connection, http.client.HTTPConnection):
            addresses = _resolve(connection.host, connection.port, self._deadline)
            original_create = connection._create_connection
            original_context = getattr(connection, "_context", None)

            def create_connection(_address, timeout=None, source_address=None):
                last_error = None
                for family, sock_type, protocol, _name, address in addresses:
                    self._check()
                    candidate = socket.socket(family, sock_type, protocol)
                    self._active_socket = candidate
                    try:
                        candidate.settimeout(self._remaining())
                        if source_address:
                            candidate.bind(source_address)
                        candidate.connect(address)
                        self._check()
                        return candidate
                    except OSError as exc:
                        candidate.close()
                        last_error = exc
                self._check()
                raise last_error or OSError("HTTP read connection unavailable")

            try:
                connection._create_connection = create_connection
                if original_context is not None:
                    connection._context = _DeadlineTLSContext(original_context, self)
                self._call(connection.connect)
                self._active_socket = connection.sock
            finally:
                connection._create_connection = original_create
                if original_context is not None:
                    connection._context = original_context
        self._call(connection.request, method, path, **kwargs)

    def getresponse(self):
        self._response = self._call(self._connection.getresponse)
        return _DeadlineResponse(self._response, self)

    def close(self):
        if self._timer is not None:
            self._timer.cancel()
        self._expire()
        try:
            if self._response is not None:
                self._response.close()
        finally:
            self._connection.close()
