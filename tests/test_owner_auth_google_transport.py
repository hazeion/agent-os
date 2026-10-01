from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from requests.structures import CaseInsensitiveDict

import owner_auth_google as verifier
import owner_auth_google_transport as transport
import owner_auth_google_worker as worker
from tests import test_owner_auth_google as signed


class Response:
    def __init__(self, value=None, *, status=200, headers=None, chunks=None):
        self.status_code = status
        self.headers = CaseInsensitiveDict({"Content-Type": "application/json", "Cache-Control": "public, max-age=120", **(headers or {})})
        self.chunks = [json.dumps(value).encode()] if chunks is None else chunks
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def iter_content(self, chunk_size):
        assert chunk_size == 4096
        yield from self.chunks


class Session:
    def __init__(self, response):
        self.response = response
        self.headers = {"Unexpected": "must be cleared"}
        self.calls = []
        self.mounts = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def mount(self, prefix, adapter):
        self.mounts.append((prefix, adapter.max_retries.total))

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response


class Runner:
    def __init__(self, token, keys):
        self.token, self.keys = token, keys
        self.calls = []
        self.closed = False

    def __call__(self, payload, deadline):
        self.calls.append(payload.copy())
        if payload["operation"] == "exchange":
            return {"ok": True, "id_token": self.token}
        return {"ok": True, "jwks": self.keys, "max_age": 120}

    def close(self):
        self.closed = True
        return True


class GoogleTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        signed.GoogleIdentityVerificationTests.setUpClass()

    def setUp(self):
        self.fixture = signed.GoogleIdentityVerificationTests()
        self.fixture.setUp()
        self.arguments = {
            "client_id": self.fixture.client_id, "origin": "https://mentat.example.test",
            "code": secrets.token_urlsafe(32), "code_verifier": self.fixture.login.code_verifier,
            "client_secret": secrets.token_urlsafe(32), "expected_nonce": self.fixture.login.nonce,
        }

    def exchange_payload(self):
        return {"operation": "exchange", **{key: value for key, value in self.arguments.items() if key != "expected_nonce"}}

    def test_worker_post_is_fixed_nonretrying_and_discards_extra_provider_tokens(self):
        token = self.fixture.token()
        response = Response({"id_token": token, "access_token": secrets.token_urlsafe(32), "refresh_token": secrets.token_urlsafe(32)})
        session = Session(response)
        with patch.object(worker.requests, "Session", return_value=session):
            result = worker.perform(self.exchange_payload())
        self.assertEqual(result, {"ok": True, "id_token": token})
        self.assertTrue(session.closed and response.closed)
        self.assertFalse(session.trust_env)
        self.assertTrue(session.verify)
        self.assertEqual(session.headers, {})
        self.assertEqual(session.mounts, [("https://", 0)])
        self.assertEqual(len(session.calls), 1)
        args, kwargs = session.calls[0]
        self.assertEqual(args, ("POST", worker.TOKEN_ENDPOINT))
        self.assertEqual(kwargs, {
            "data": {"grant_type": "authorization_code", "client_id": self.fixture.client_id,
                     "redirect_uri": self.arguments["origin"] + verifier.CALLBACK_PATH,
                     "code": self.arguments["code"], "code_verifier": self.arguments["code_verifier"], "client_secret": self.arguments["client_secret"]},
            "headers": {"Accept": "application/json", "Accept-Encoding": "identity"},
            "allow_redirects": False, "stream": True, "timeout": (3, 3),
        })
        self.assertNotIn(self.arguments["code"], args[1])

    def test_worker_keys_validate_shape_and_honor_cache_controls(self):
        for header, age, expected in (("public, max-age=120", "20", 100), ("max-age=999999", "0", 3600), ("max-age=120, no-store", "0", 0), ("no-cache, max-age=120", "0", 0), ("max-age=120, max-age=30", "0", 30), ("max-age=120", "bad", 0), ("", "0", 0)):
            response = Response(self.fixture.jwks, headers={"Cache-Control": header, "Age": age})
            session = Session(response)
            with patch.object(worker.requests, "Session", return_value=session):
                result = worker.perform({"operation": "keys"})
            self.assertEqual(result, {"ok": True, "jwks": self.fixture.jwks, "max_age": expected})
            self.assertEqual(session.calls[0][0], ("GET", worker.JWKS_ENDPOINT))
            self.assertIsNone(session.calls[0][1]["data"])

    def test_hostile_http_responses_fail_once_and_close_without_forwarding_body(self):
        cases = [
            Response({}, status=302, headers={"Location": "https://attacker.example.test"}),
            Response({"error_description": self.arguments["client_secret"]}, status=400),
            Response({}, headers={"Content-Type": "text/html"}),
            Response({}, headers={"Content-Encoding": "gzip"}),
            Response({}, headers={"Content-Length": str(worker.MAX_TOKEN_RESPONSE_BYTES + 1)}),
            Response({}, headers={"Content-Length": "1,1"}),
            Response({}, headers={"Content-Length": "99"}),
            Response({}, chunks=[b"x" * (worker.MAX_TOKEN_RESPONSE_BYTES + 1)]),
            Response({}, chunks=[b'{"id_token":"a","id_token":"b"}']),
            Response({}, chunks=[b"\xff"]),
            Response({}, headers={"X-Long": "x" * 16385}),
        ]
        for response in cases:
            session = Session(response)
            with self.subTest(headers=dict(response.headers)), patch.object(worker.requests, "Session", return_value=session), self.assertRaises(ValueError):
                worker.perform(self.exchange_payload())
            self.assertEqual(len(session.calls), 1)
            self.assertTrue(session.closed and response.closed)
        with patch.object(worker.requests, "Session") as factory:
            for request in ({"operation": "keys", "url": worker.JWKS_ENDPOINT}, {"operation": "shell"}, {**self.exchange_payload(), "origin": "http://mentat.example.test"}):
                with self.assertRaises(ValueError):
                    worker.perform(request)
            factory.assert_not_called()

    def test_transport_integrates_real_signature_and_cached_keys_without_repeating_exchange(self):
        runner = Runner(self.fixture.token(), self.fixture.jwks)
        client = transport.GoogleOidcTransport(_runner=runner)
        result = client.authenticate_code(**self.arguments)
        self.assertEqual(result.subject, self.fixture.claims["sub"])
        client.authenticate_code(**{**self.arguments, "code": secrets.token_urlsafe(32)})
        self.assertEqual([call["operation"] for call in runner.calls], ["exchange", "keys", "exchange"])
        self.assertTrue(client.close())
        with self.assertRaises(transport.GoogleOidcTransportError):
            client.authenticate_code(**self.arguments)
        self.assertEqual(len(runner.calls), 3)

    def test_invalid_token_or_key_reply_cannot_return_identity_or_retry_the_code(self):
        for token in (self.fixture.token(key=self.fixture.other_key), self.fixture.token({**self.fixture.claims, "nonce": verifier.new_login_secrets().nonce}), "not-a-jwt"):
            runner = Runner(token, self.fixture.jwks)
            with self.assertRaisesRegex(transport.GoogleOidcTransportError, "^unavailable$"):
                transport.GoogleOidcTransport(_runner=runner).authenticate_code(**self.arguments)
            self.assertEqual(sum(call["operation"] == "exchange" for call in runner.calls), 1)

    def test_key_cache_expiry_rotation_and_unknown_key_backoff(self):
        cache = transport.GoogleSigningKeyCache()
        tick = [100.0]
        calls = []
        keys = self.fixture.jwks
        def fetch(deadline):
            calls.append(deadline)
            return json.dumps(keys).encode(), 120
        with patch.object(transport.time, "monotonic", side_effect=lambda: tick[0]):
            cache.keys("key-one", fetch, 110)
            cache.keys("key-one", fetch, 110)
            self.assertEqual(len(calls), 1)
            tick[0] = 130
            with self.assertRaises(transport.GoogleOidcTransportError):
                cache.keys("key-two", fetch, 140)
            self.assertEqual(len(calls), 1)
            tick[0] = 161
            keys = {"keys": [*keys["keys"], self.fixture.jwk(self.fixture.other_key, "key-two")]}
            cache.keys("key-two", fetch, 171)
            self.assertEqual(len(calls), 2)
            tick[0] = 282
            cache.keys("key-two", fetch, 292)
            self.assertEqual(len(calls), 3)

    def test_no_store_key_miss_does_not_allow_repeated_rotation_fetches(self):
        cache = transport.GoogleSigningKeyCache()
        calls = []
        def fetch(_deadline):
            calls.append(1)
            return json.dumps(self.fixture.jwks).encode(), 0
        with patch.object(transport.time, "monotonic", return_value=100):
            for _ in range(3):
                with self.assertRaises(transport.GoogleOidcTransportError):
                    cache.keys("missing", fetch, 110)
        self.assertEqual(len(calls), 1)

    def test_worker_environment_and_command_have_no_inherited_credentials_or_request_secrets(self):
        marker = secrets.token_urlsafe(32)
        with patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": marker, "HTTPS_PROXY": marker, "SSL_CERT_FILE": marker, "MENTAT_GOOGLE_CLIENT_SECRET": marker, "PYTHONPATH": marker, "HOME": marker}):
            environment = transport.worker_environment()
            command = transport.worker_command()
        self.assertLessEqual(set(environment), {"SYSTEMROOT", "WINDIR", "LANG"})
        self.assertNotIn(marker, repr(environment) + repr(command))
        self.assertIn("-I", command)
        with patch.object(sys, "frozen", True, create=True), self.assertRaises(transport.GoogleOidcTransportError):
            transport.worker_command()

    def test_real_worker_rejects_unknown_operations_and_is_reaped(self):
        processes = []
        def spawn(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            processes.append(process)
            return process
        runner = transport.GoogleWorkerRunner(_spawn=spawn)
        try:
            result = runner({"operation": "never-network"}, time.monotonic() + 10)
            self.assertEqual(result, {"ok": False, "error": "unavailable"})
            self.assertEqual(len(processes), 1)
            self.assertIsNotNone(processes[0].poll())
        finally:
            self.assertTrue(runner.close())

    def test_timed_out_worker_is_killed_without_retry_and_capacity_is_reusable(self):
        processes = []
        def spawn(_command, **kwargs):
            process = subprocess.Popen((sys.executable, "-I", "-c", "import sys,time;sys.stdin.buffer.read();time.sleep(30)"), **kwargs)
            processes.append(process)
            return process
        runner = transport.GoogleWorkerRunner(_spawn=spawn)
        try:
            for _ in range(3):
                with self.assertRaises(transport.GoogleOidcTransportError):
                    runner({"operation": "keys"}, time.monotonic() + 0.1)
                self.assertIsNotNone(processes[-1].poll())
            self.assertEqual(len(processes), 3)
        finally:
            self.assertTrue(runner.close())

    def test_capacity_is_shared_and_close_drains_active_workers(self):
        processes = []
        both_started = threading.Event()
        def spawn(_command, **kwargs):
            process = subprocess.Popen((sys.executable, "-I", "-c", "import sys,time;sys.stdin.buffer.read();time.sleep(30)"), **kwargs)
            processes.append(process)
            if len(processes) == 2:
                both_started.set()
            return process
        runner = transport.GoogleWorkerRunner(_spawn=spawn)
        failures = []
        def run():
            try:
                runner({"operation": "keys"}, time.monotonic() + 5)
            except transport.GoogleOidcTransportError:
                failures.append(1)
        threads = [threading.Thread(target=run) for _ in range(2)]
        try:
            for thread in threads:
                thread.start()
            self.assertTrue(both_started.wait(3))
            with self.assertRaisesRegex(transport.GoogleOidcTransportError, "capacity_unavailable"):
                transport.GoogleWorkerRunner(_spawn=spawn)({"operation": "keys"}, time.monotonic() + 5)
        finally:
            runner.close()
            for thread in threads:
                thread.join(4)
            self.assertTrue(runner.close())
        self.assertEqual(len(processes), 2)
        self.assertTrue(all(process.poll() is not None for process in processes))
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(failures), 2)


if __name__ == "__main__":
    unittest.main()
