"""Bounded private Google exchange; no callback or session authority."""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable

from codex_runtime import _attach_windows_kill_job, _close_windows_job
from owner_auth_google import (
    MAX_JWKS_BYTES, MAX_TOKEN_BYTES, VerifiedGoogleIdentity,
    _KEY_ID, _client_id, _decode_base64url, _json_object, _public_key, _secret,
    verify_id_token,
)
from owner_auth_google_worker import MAX_CACHE_SECONDS, MAX_INPUT_BYTES, MAX_OUTPUT_BYTES, WORK_SECONDS, _opaque
from owner_auth_webauthn import canonical_origin

_CAPACITY = threading.BoundedSemaphore(2)


class GoogleOidcTransportError(RuntimeError):
    def __init__(self, code: str = "unavailable"):
        super().__init__(code if code in {"invalid", "unavailable", "capacity_unavailable"} else "unavailable")


def worker_environment() -> dict[str, str]:
    return {name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR") if os.environ.get(name)} | {"LANG": "C.UTF-8"}


def worker_command() -> tuple[str, ...]:
    if getattr(sys, "frozen", False):
        raise GoogleOidcTransportError()
    root = str(Path(__file__).resolve().parent)
    bootstrap = f"import runpy,sys;sys.path.insert(0,{root!r});runpy.run_module('owner_auth_google_worker',run_name='__main__')"
    return sys.executable, "-I", "-c", bootstrap


class _OwnedWorker:
    def __init__(self, process):
        self.process = process
        self.job = None
        self._lock = threading.Lock()
        self.released = False

    def stop(self) -> bool:
        with self._lock:
            if self.released:
                return True
            try:
                if os.name == "nt":
                    if self.job is not None:
                        _close_windows_job(self.job)
                        self.job = None
                    elif self.process.poll() is None:
                        self.process.kill()
                else:
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                self.process.wait(timeout=2)
                for stream in (self.process.stdin, self.process.stdout):
                    if stream is not None:
                        stream.close()
            except (OSError, subprocess.TimeoutExpired):
                # A worker whose death is unverified continues to occupy its
                # global slot. close() may try cleanup again; never oversubscribe.
                return False
            self.released = True
            _CAPACITY.release()
            return True


class GoogleWorkerRunner:
    """Own replaceable workers and their capacity until verified process exit."""
    def __init__(self, *, _spawn: Callable = subprocess.Popen):
        self._spawn = _spawn
        self._lock = threading.Lock()
        self._workers: set[_OwnedWorker] = set()
        self._closed = False
        self._starting = 0

    def close(self) -> bool:
        with self._lock:
            self._closed = True
            workers = tuple(self._workers)
        for worker in workers:
            if worker.stop():
                with self._lock:
                    self._workers.discard(worker)
        with self._lock:
            return not self._workers and self._starting == 0

    def __call__(self, payload: dict, deadline_at: float) -> dict:
        result = None
        failure = "unavailable"
        try:
            encoded = json.dumps(payload, separators=(",", ":")).encode()
            remaining = deadline_at - time.monotonic()
            if not 0 < remaining <= WORK_SECONDS or len(encoded) > MAX_INPUT_BYTES:
                raise ValueError("invalid")
            command = worker_command()
        except Exception:
            payload = {}; encoded = b""
            raise GoogleOidcTransportError("invalid") from None
        if not _CAPACITY.acquire(blocking=False):
            payload = {}; encoded = b""
            raise GoogleOidcTransportError("capacity_unavailable")
        worker = None
        starting = False
        try:
            with self._lock:
                if self._closed:
                    raise ValueError("closed")
                self._starting += 1
                starting = True
            options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
            process = self._spawn(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=worker_environment(), cwd=tempfile.gettempdir(), close_fds=True, **options)
            worker = _OwnedWorker(process)
            if os.name == "nt":
                worker.job = _attach_windows_kill_job(process)
            with self._lock:
                self._workers.add(worker)
                self._starting -= 1
                starting = False
                if self._closed:
                    raise ValueError("closed")
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                raise ValueError("expired")
            output, _ = process.communicate(encoded, timeout=remaining)
            if process.returncode != 0 or not isinstance(output, bytes) or len(output) > MAX_OUTPUT_BYTES:
                raise ValueError("unavailable")
            result = _json_object(output, MAX_OUTPUT_BYTES)
        except Exception:
            result = None
        finally:
            payload = {}; encoded = b""; output = b""
            if starting:
                with self._lock:
                    self._starting -= 1
            if worker is None:
                _CAPACITY.release()
            elif worker.stop():
                with self._lock:
                    self._workers.discard(worker)
            else:
                with self._lock:
                    self._workers.add(worker)
                result = None
        with self._lock:
            if self._closed:
                result = None
        if result is None:
            raise GoogleOidcTransportError(failure) from None
        return result


class GoogleSigningKeyCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._jwks: bytes | None = None
        self._key_ids: frozenset[str] = frozenset()
        self._expires_at = 0.0
        self._unknown_refresh_at = 0.0
        self._missing_key_backoff = 0.0

    def keys(self, key_id: str, fetch: Callable[[float], tuple[bytes, int]], deadline_at: float) -> bytes:
        if not self._lock.acquire(timeout=max(0, deadline_at - time.monotonic())):
            raise GoogleOidcTransportError()
        try:
            now = time.monotonic()
            if now >= deadline_at:
                raise GoogleOidcTransportError()
            if self._jwks is not None and now < self._expires_at:
                if key_id in self._key_ids:
                    return self._jwks
                if now < self._unknown_refresh_at:
                    raise GoogleOidcTransportError("invalid")
            if now < self._missing_key_backoff:
                raise GoogleOidcTransportError("invalid")
            # This timestamp also limits retries after an unknown-key refresh
            # fails while a valid cached snapshot remains usable for other keys.
            self._unknown_refresh_at = now + 60
            data, seconds = fetch(deadline_at)
            document = _json_object(data, MAX_JWKS_BYTES)
            _public_key(data, document["keys"][0]["kid"])
            ids = frozenset(key["kid"] for key in document["keys"])
            if type(seconds) is not int or not 0 <= seconds <= MAX_CACHE_SECONDS:
                raise GoogleOidcTransportError()
            self._jwks = data if seconds else None
            self._key_ids = ids if seconds else frozenset()
            self._expires_at = time.monotonic() + seconds
            if key_id not in ids:
                self._missing_key_backoff = time.monotonic() + 60
                raise GoogleOidcTransportError("invalid")
            self._missing_key_backoff = 0.0
            return data
        finally:
            self._lock.release()


class GoogleOidcTransport:
    def __init__(self, *, _runner=None, _keys=None):
        self._runner = GoogleWorkerRunner() if _runner is None else _runner
        self._keys = GoogleSigningKeyCache() if _keys is None else _keys
        self._closed = threading.Event()

    def close(self) -> bool:
        self._closed.set()
        return self._runner.close()

    def _fetch_keys(self, deadline_at: float) -> tuple[bytes, int]:
        response = self._runner({"operation": "keys"}, deadline_at)
        if set(response) != {"ok", "jwks", "max_age"} or response["ok"] is not True:
            raise GoogleOidcTransportError()
        return json.dumps(response["jwks"], separators=(",", ":")).encode(), response["max_age"]

    def authenticate_code(self, *, client_id: str, origin: str, code: str, code_verifier: str, client_secret: str, expected_nonce: str) -> VerifiedGoogleIdentity:
        """Exchange once after the caller has consumed a durable transaction.

        No failure may retry this code. The caller owns owner-subject matching
        and must never interpret this private identity as an issued session.
        """
        result = None
        try:
            if self._closed.is_set():
                raise ValueError("closed")
            deadline_at = time.monotonic() + WORK_SECONDS
            _client_id(client_id); _secret(code_verifier); _secret(expected_nonce)
            _opaque(code, 4096); _opaque(client_secret, 4096)
            _, hostname = canonical_origin(origin)
            if "." not in hostname or not any(character.isalpha() for character in hostname.rsplit(".", 1)[-1]):
                raise ValueError("invalid")
            response = self._runner({"operation": "exchange", "client_id": client_id, "origin": origin, "code": code, "code_verifier": code_verifier, "client_secret": client_secret}, deadline_at)
            if set(response) != {"ok", "id_token"} or response["ok"] is not True:
                raise ValueError("unavailable")
            token = _opaque(response["id_token"], MAX_TOKEN_BYTES)
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError("invalid")
            header = _json_object(_decode_base64url(parts[0], 2048), 1536)
            key_id = header.get("kid")
            if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id) or set(header) - {"alg", "kid", "typ"} or header.get("alg") != "RS256" or "typ" in header and header["typ"] != "JWT":
                raise ValueError("invalid")
            keys = self._keys.keys(key_id, self._fetch_keys, deadline_at)
            result = verify_id_token(token, client_id=client_id, expected_nonce=expected_nonce, jwks=keys)
            if self._closed.is_set() or time.monotonic() >= deadline_at:
                result = None
        except Exception:
            result = None
        finally:
            code = code_verifier = client_secret = expected_nonce = ""
            response = {}; token = ""
        if result is None:
            raise GoogleOidcTransportError() from None
        return result
