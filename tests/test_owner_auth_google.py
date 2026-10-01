from __future__ import annotations

import base64
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import socket
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import owner_auth_google as google

_UNSET = object()


def encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def integer(value: int) -> str:
    return encoded(value.to_bytes((value.bit_length() + 7) // 8, "big"))


class GoogleIdentityVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.now = int(time.time())
        self.login = google.new_login_secrets()
        self.client_id = "1234567890-test.apps.googleusercontent.com"
        self.header = {"alg": "RS256", "kid": "key-one", "typ": "JWT"}
        self.claims = {
            "iss": google.GOOGLE_ISSUER, "aud": self.client_id,
            "azp": self.client_id, "sub": "case-sensitive-subject",
            "email": "owner@example.test", "email_verified": True,
            "iat": self.now - 60, "exp": self.now + 3600,
            "nonce": self.login.nonce,
        }
        self.jwks = {"keys": [self.jwk(self.key, "key-one")]}

    def jwk(self, key, kid):
        numbers = key.public_key().public_numbers()
        return {"alg": "RS256", "e": integer(numbers.e), "kid": kid, "kty": "RSA", "n": integer(numbers.n), "use": "sig"}

    def token(self, claims=None, header=None, key=None, raw_header=None, raw_claims=None):
        header_bytes = raw_header if raw_header is not None else json.dumps(self.header if header is None else header).encode()
        claim_bytes = raw_claims if raw_claims is not None else json.dumps(self.claims if claims is None else claims).encode()
        section = encoded(header_bytes) + "." + encoded(claim_bytes)
        signature = (key or self.key).sign(section.encode(), padding.PKCS1v15(), hashes.SHA256())
        return section + "." + encoded(signature)

    def verify(self, token=_UNSET, jwks=_UNSET, **changes):
        arguments = {"client_id": self.client_id, "expected_nonce": self.login.nonce, "jwks": json.dumps(self.jwks).encode() if jwks is _UNSET else jwks, **changes}
        with patch("google.auth._helpers.utcnow", return_value=datetime.fromtimestamp(self.now, timezone.utc)), patch.object(google.time, "time", return_value=self.now):
            return google.verify_id_token(self.token() if token is _UNSET else token, **arguments)

    def rejects(self, token=_UNSET, jwks=_UNSET, **changes):
        with self.assertRaises(google.GoogleOidcVerificationError) as failure:
            self.verify(token, jwks, **changes)
        self.assertEqual(str(failure.exception), "invalid")
        self.assertIsNone(failure.exception.__cause__)

    def test_valid_signature_yields_only_private_identity_and_no_network_or_session(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            result = self.verify()
        self.assertEqual(asdict(result), {"issuer": google.GOOGLE_ISSUER, "subject": self.claims["sub"], "email": self.claims["email"]})
        self.assertNotIn(self.claims["email"], repr(result))
        self.assertNotIn(self.claims["sub"], repr(result))
        self.assertFalse(hasattr(result, "cookie_value"))
        for issuer in (google.GOOGLE_ISSUER, "accounts.google.com"):
            for verified in (True, "true"):
                result = self.verify(self.token({**self.claims, "iss": issuer, "email_verified": verified}))
                self.assertEqual(result.issuer, google.GOOGLE_ISSUER)

    def test_private_subject_is_opaque_case_sensitive_and_not_derived_from_email(self):
        other = self.verify(self.token({**self.claims, "email": "renamed@example.test"}))
        self.assertEqual(other.subject, self.claims["sub"])
        changed = self.verify(self.token({**self.claims, "sub": self.claims["sub"].upper()}))
        self.assertNotEqual(changed.subject, other.subject)
        self.verify(self.token({**self.claims, "amr": ["mfa"], "auth_time": self.now - 10, "picture": "https://untrusted.example.test/image"}))

    def test_signature_tampering_and_untrusted_key_material_never_prove_identity(self):
        self.rejects(self.token(key=self.other_key))
        parts = self.token().split(".")
        parts[1] = encoded(json.dumps({**self.claims, "sub": "attacker"}).encode())
        self.rejects(".".join(parts))
        self.rejects(jwks=json.dumps({"keys": [self.jwk(self.other_key, "key-one")]}).encode())
        self.rejects(self.token(header={**self.header, "kid": "missing"}))

    def test_jose_algorithms_and_key_selection_are_fixed(self):
        for changes in ({"alg": "none"}, {"alg": "HS256"}, {"alg": "ES256"}, {"kid": ""}, {"kid": None}, {"typ": "at+jwt"}, {"jku": "https://attacker.example.test/keys"}, {"jwk": self.jwk(self.key, "injected")}, {"crit": []}, {"b64": False}):
            with self.subTest(changes=changes):
                self.rejects(self.token(header={**self.header, **changes}))
        self.rejects(self.token(header={"alg": "RS256", "typ": "JWT"}))
        self.verify(self.token(header={"alg": "RS256", "kid": "key-one"}))

    def test_claim_binding_rejects_wrong_and_malformed_values(self):
        cases = {
            "iss": ["https://accounts.google.com/", "https://attacker.example.test", [], None],
            "aud": ["other.apps.googleusercontent.com", [self.client_id], None],
            "azp": ["other.apps.googleusercontent.com", [], None],
            "nonce": [google.new_login_secrets().nonce, "", None, "\ud800"],
            "sub": ["", "x" * 256, " leading", "line\nbreak", "unicode-\u00e9", 123],
            "email": ["", "invalid", "a@@b", "@example.test", "a@", "line\nbreak@example.test", "x" * 255],
            "email_verified": [False, "false", "True", 1, None],
            "iat": [True, self.now + 1, "0", -1, float(self.now)],
            "exp": [False, self.now - 1, self.now, "9999999999", 2**53, float(self.now + 100)],
            "nbf": [True, self.now + 1, "0", -1, 2**53],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=repr(value)):
                    self.rejects(self.token({**self.claims, field: value}))
        for field in ("iss", "aud", "nonce", "sub", "email", "email_verified", "iat", "exp"):
            with self.subTest(missing=field):
                self.rejects(self.token({key: value for key, value in self.claims.items() if key != field}))
        self.verify(self.token({**self.claims, "nbf": self.now}))

    def test_duplicate_and_structurally_hostile_json_is_rejected_even_when_signed(self):
        duplicate_header = b'{"alg":"none","alg":"RS256","kid":"key-one","typ":"JWT"}'
        self.rejects(self.token(raw_header=duplicate_header))
        duplicate_claims = json.dumps(self.claims)[:-1] + ',"sub":"other"}'
        self.rejects(self.token(raw_claims=duplicate_claims.encode()))
        for extra in ('"unknown":NaN', '"unknown":1e999', '"unknown":{"x":1,"x":2}', '"unknown":' + '[' * 10 + '0' + ']' * 10, '"unknown":[' + ','.join('0' for _ in range(257)) + ']'):
            self.rejects(self.token(raw_claims=(json.dumps(self.claims)[:-1] + ',' + extra + '}').encode()))
        self.rejects(self.token(raw_claims=b'[]'))
        self.rejects(self.token(raw_header=b'[]'))

    def test_size_encoding_and_wrong_input_types_fail_with_generic_errors(self):
        for token in (None, b"bytes", "", "x" * (google.MAX_TOKEN_BYTES + 1), "a.b.c.d", "a.b", "\u00e9.b.c", "===.===.==="):
            with self.subTest(token_type=type(token).__name__):
                self.rejects(token)
        parts = self.token().split(".")
        self.rejects(".".join([parts[0] + "=", *parts[1:]]))
        self.rejects(self.token({**self.claims, "unknown": "x" * google.MAX_TOKEN_BYTES}))
        self.rejects(expected_nonce="a" * 42)
        self.rejects(client_id="not-a-google-client")

    def test_keyset_rotation_is_exact_and_bounded(self):
        keys = [self.jwk(self.other_key, "key-two"), self.jwk(self.key, "key-one")]
        self.verify(jwks=json.dumps({"keys": keys}).encode())
        self.rejects(jwks=json.dumps({"keys": [keys[1], keys[1]]}).encode())
        self.rejects(jwks=json.dumps({"keys": []}).encode())
        self.rejects(jwks=json.dumps({"keys": [self.jwk(self.key, str(i)) for i in range(17)]}).encode())
        self.rejects(jwks=b" " * (google.MAX_JWKS_BYTES + 1))
        self.rejects(jwks=b'{"keys":[],"keys":[]}')
        for changes in ({"kty": "EC"}, {"alg": "HS256"}, {"use": "enc"}, {"n": "AQ"}, {"n": "A" * 684}, {"e": "Aw"}, {"e": "AAEAAQ"}, {"kid": "\n"}, {"jku": "https://attacker.example.test"}):
            self.rejects(jwks=json.dumps({"keys": [{**self.jwks["keys"][0], **changes}]}).encode())

    def test_request_has_fixed_scope_callback_and_s256_without_private_verifier(self):
        url = google.authorization_url(client_id=self.client_id, origin="https://mentat.example.test", login=self.login)
        parsed = urlsplit(url)
        self.assertEqual(parsed.scheme + "://" + parsed.netloc + parsed.path, google.AUTHORIZATION_ENDPOINT)
        parameters = parse_qs(parsed.query, strict_parsing=True)
        self.assertEqual(parameters, {
            "client_id": [self.client_id], "redirect_uri": ["https://mentat.example.test" + google.CALLBACK_PATH],
            "response_type": ["code"], "scope": ["openid email"], "state": [self.login.state], "nonce": [self.login.nonce],
            "code_challenge_method": ["S256"], "code_challenge": [encoded(hashlib.sha256(self.login.code_verifier.encode()).digest())], "prompt": ["select_account"],
        })
        self.assertNotIn(self.login.code_verifier, url)
        self.assertNotIn(self.login.browser_binding, url)
        self.assertNotIn(self.login.nonce, repr(self.login))
        self.assertEqual(len(set(asdict(self.login).values())), 4)
        for value in asdict(self.login).values():
            self.assertEqual(len(value), 43)

    def test_request_rejects_noncanonical_origins_clients_and_secrets(self):
        for origin in ("http://mentat.example.test", "https://mentat.example.test/", "https://mentat.example.test:443", "https://mentat.example.test/callback", "https://user@mentat.example.test", "https://127.0.0.1", "https://localhost", "https://MENTAT.example.test"):
            with self.subTest(origin=origin), self.assertRaisesRegex(google.GoogleOidcVerificationError, "^invalid$"):
                google.authorization_url(client_id=self.client_id, origin=origin, login=self.login)
        for field in asdict(self.login):
            with self.subTest(field=field), self.assertRaises(google.GoogleOidcVerificationError):
                google.authorization_url(client_id=self.client_id, origin="https://mentat.example.test", login=replace(self.login, **{field: "invalid"}))
        with self.assertRaises(google.GoogleOidcVerificationError):
            google.authorization_url(client_id=self.client_id, origin="https://mentat.example.test", login=replace(self.login, code_verifier=self.login.nonce))


if __name__ == "__main__":
    unittest.main()
