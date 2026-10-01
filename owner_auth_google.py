"""Google-only OIDC request and identity verification, without login authority.

Inputs come from private server configuration and a future fixed-host exchange.
This module opens no sockets, reads no credentials, and issues no sessions.
An identity result is not owner enrollment or proof of fresh reauthentication.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import jwt
from google.auth.exceptions import GoogleAuthError

from owner_auth_webauthn import canonical_origin


GOOGLE_ISSUER = "https://accounts.google.com"
AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
CALLBACK_PATH = "/auth/google/callback"
MAX_TOKEN_BYTES = 16 * 1024
MAX_JWKS_BYTES = 256 * 1024
MAX_KEYS = 16
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+\Z", re.ASCII)
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z", re.ASCII)
_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com\Z", re.ASCII)


class GoogleOidcVerificationError(ValueError):
    """Fixed failure only; do not return provider values or decoder errors."""


@dataclass(frozen=True, repr=False)
class GoogleLoginSecrets:
    state: str
    nonce: str
    code_verifier: str
    browser_binding: str


@dataclass(frozen=True, repr=False)
class VerifiedGoogleIdentity:
    issuer: str
    subject: str
    email: str


def new_login_secrets() -> GoogleLoginSecrets:
    """Create independent ephemeral values; storage/one-use policy is external."""
    return GoogleLoginSecrets(*(secrets.token_urlsafe(32) for _ in range(4)))


def _decode_base64url(value: str, maximum: int) -> bytes:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or not _BASE64URL.fullmatch(value):
        raise GoogleOidcVerificationError("invalid")
    raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value:
        raise GoogleOidcVerificationError("invalid")
    return raw


def _secret(value: str) -> str:
    if len(_decode_base64url(value, 43)) != 32:
        raise GoogleOidcVerificationError("invalid")
    return value


def _client_id(value: str) -> str:
    if not isinstance(value, str) or not _CLIENT_ID.fullmatch(value):
        raise GoogleOidcVerificationError("invalid")
    return value


def authorization_url(*, client_id: str, origin: str, login: GoogleLoginSecrets) -> str:
    """Build only the approved code flow; no return URL or extra scopes."""
    try:
        client_id = _client_id(client_id)
        origin, hostname = canonical_origin(origin)
        if "." not in hostname or not any(character.isalpha() for character in hostname.rsplit(".", 1)[-1]):
            raise GoogleOidcVerificationError("invalid")
        if not isinstance(login, GoogleLoginSecrets):
            raise GoogleOidcVerificationError("invalid")
        values = (login.state, login.nonce, login.code_verifier, login.browser_binding)
        for value in values:
            _secret(value)
        if len(set(values)) != 4:
            raise GoogleOidcVerificationError("invalid")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(login.code_verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        return AUTHORIZATION_ENDPOINT + "?" + urlencode({
            "client_id": client_id,
            "redirect_uri": origin + CALLBACK_PATH,
            "response_type": "code",
            "scope": "openid email",
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": login.state,
            "nonce": login.nonce,
            "prompt": "select_account",
        })
    except (ValueError, TypeError, UnicodeError, OverflowError):
        raise GoogleOidcVerificationError("invalid") from None


def _object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise GoogleOidcVerificationError("invalid")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise GoogleOidcVerificationError("invalid")


def _json_object(raw: bytes, maximum: int) -> dict:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= maximum:
        raise GoogleOidcVerificationError("invalid")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    if not isinstance(value, dict):
        raise GoogleOidcVerificationError("invalid")
    pending = [(value, 0)]
    nodes = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if depth > 8 or nodes > 256:
            raise GoogleOidcVerificationError("invalid")
        if isinstance(item, dict):
            if len(item) > 64:
                raise GoogleOidcVerificationError("invalid")
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            if len(item) > 256:
                raise GoogleOidcVerificationError("invalid")
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise GoogleOidcVerificationError("invalid")
    return value


def _public_key(jwks: bytes, key_id: str) -> bytes:
    document = _json_object(jwks, MAX_JWKS_BYTES)
    keys = document.get("keys")
    if set(document) != {"keys"} or not isinstance(keys, list) or not 1 <= len(keys) <= MAX_KEYS:
        raise GoogleOidcVerificationError("invalid")
    seen = set()
    selected = None
    for key in keys:
        if (
            not isinstance(key, dict)
            or set(key) != {"alg", "e", "kid", "kty", "n", "use"}
            or key.get("kty") != "RSA" or key.get("alg") != "RS256" or key.get("use") != "sig"
            or not isinstance(key.get("kid"), str) or not _KEY_ID.fullmatch(key["kid"])
            or key["kid"] in seen
        ):
            raise GoogleOidcVerificationError("invalid")
        seen.add(key["kid"])
        modulus = _decode_base64url(key["n"], 683)
        exponent = _decode_base64url(key["e"], 6)
        if not modulus or modulus[0] == 0 or not exponent or exponent[0] == 0:
            raise GoogleOidcVerificationError("invalid")
        n, e = int.from_bytes(modulus, "big"), int.from_bytes(exponent, "big")
        if n.bit_length() not in {2048, 3072, 4096} or n % 2 == 0 or e != 65537:
            raise GoogleOidcVerificationError("invalid")
        if key["kid"] == key_id:
            selected = rsa.RSAPublicNumbers(e, n).public_key()
    if selected is None:
        raise GoogleOidcVerificationError("invalid")
    return selected.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def verify_id_token(token: str, *, client_id: str, expected_nonce: str, jwks: bytes) -> VerifiedGoogleIdentity:
    """Verify a private Google assertion using issuer-owned keys, never JWT URLs.

The caller must obtain JWKS through the fixed trusted Google transport and bind
the nonce to a live one-use transaction. This function deliberately cannot do
owner enrollment, replay accounting, session issuance or reauthentication.
"""
    try:
        client_id = _client_id(client_id)
        _secret(expected_nonce)
        if not isinstance(token, str) or not token.isascii() or not 1 <= len(token) <= MAX_TOKEN_BYTES:
            raise GoogleOidcVerificationError("invalid")
        parts = token.split(".")
        if len(parts) != 3:
            raise GoogleOidcVerificationError("invalid")
        header = _json_object(_decode_base64url(parts[0], 2048), 1536)
        claims = _json_object(_decode_base64url(parts[1], MAX_TOKEN_BYTES), MAX_TOKEN_BYTES)
        signature = _decode_base64url(parts[2], 683)
        if (
            set(header) - {"alg", "kid", "typ"}
            or header.get("alg") != "RS256"
            or "typ" in header and header["typ"] != "JWT"
            or not isinstance(header.get("kid"), str) or not _KEY_ID.fullmatch(header["kid"])
            or len(signature) not in {256, 384, 512}
        ):
            raise GoogleOidcVerificationError("invalid")
        if (
            claims.get("iss") not in {GOOGLE_ISSUER, "accounts.google.com"}
            or claims.get("aud") != client_id
            or "azp" in claims and claims["azp"] != client_id
            or type(claims.get("iat")) is not int or type(claims.get("exp")) is not int
            or not 0 <= claims["iat"] < claims["exp"] <= 2**53 - 1
            or "nbf" in claims and (type(claims["nbf"]) is not int or not 0 <= claims["nbf"] <= 2**53 - 1)
            or not isinstance(claims.get("nonce"), str)
            or not hmac.compare_digest(claims["nonce"].encode("utf-8"), expected_nonce.encode("ascii"))
        ):
            raise GoogleOidcVerificationError("invalid")
        # Use the maintained dependency for cryptographic verification. The
        # strict parse above prevents duplicate-claim/JOSE confusion beforehand.
        public_key = _public_key(jwks, header["kid"])
        verified = jwt.decode(token, certs={header["kid"]: public_key}, audience=client_id, clock_skew_in_seconds=0)
        now = time.time()
        if verified != claims or not claims["iat"] <= now < claims["exp"] or claims.get("nbf", 0) > now:
            raise GoogleOidcVerificationError("invalid")
        subject, email = claims.get("sub"), claims.get("email")
        if (
            not isinstance(subject, str) or not 1 <= len(subject) <= 255
            or any(not 33 <= ord(character) <= 126 for character in subject)
            or not isinstance(email, str) or not 3 <= len(email) <= 254
            or email.count("@") != 1 or not all(email.split("@"))
            or any(not 33 <= ord(character) <= 126 for character in email)
            or not (claims.get("email_verified") is True or claims.get("email_verified") == "true")
        ):
            raise GoogleOidcVerificationError("invalid")
        return VerifiedGoogleIdentity(GOOGLE_ISSUER, subject, email)
    except (GoogleAuthError, ValueError, TypeError, KeyError, UnicodeError, OverflowError, RecursionError):
        raise GoogleOidcVerificationError("invalid") from None
