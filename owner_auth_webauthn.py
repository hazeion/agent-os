"""Pinned, server-side-only WebAuthn parsing boundary for owner auth.

The public edge may transport bounded JSON, but it must never decide whether a
credential is valid.  This module intentionally has no HTTP or bridge imports.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature


# Mentat deliberately has one portable, reviewed credential algorithm.  Do not
# silently inherit whatever algorithms a particular fido2 build happens to
# support: that would turn a dependency upgrade into an authentication-policy
# change.
ALLOWED_COSE_ALGORITHMS = frozenset({-7})  # ES256 / P-256 / SHA-256


class WebAuthnVerificationError(ValueError):
    """A deliberately generic verification failure."""


@dataclass(frozen=True)
class RegistrationEvidence:
    credential_id: bytes
    cose_public_key: bytes
    sign_count: int
    backup_eligible: bool
    backup_state: bool


@dataclass(frozen=True)
class AssertionEvidence:
    credential_id: bytes
    sign_count: int
    backup_eligible: bool
    backup_state: bool


def _b64url(value: str) -> bytes:
    if not isinstance(value, str) or len(value) > 8192 or "=" in value:
        raise WebAuthnVerificationError("invalid")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeError) as exc:
        raise WebAuthnVerificationError("invalid") from exc


def _client_data(raw: bytes, *, challenge_digest: bytes, origin: str, typ: str) -> None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise WebAuthnVerificationError("invalid") from exc
    if not isinstance(data, dict) or set(data) - {"type", "challenge", "origin", "crossOrigin", "tokenBinding"}:
        raise WebAuthnVerificationError("invalid")
    challenge = data.get("challenge")
    if data.get("type") != typ or data.get("origin") != origin or not isinstance(challenge, str):
        raise WebAuthnVerificationError("invalid")
    if hashlib.sha256(_b64url(challenge)).digest() != challenge_digest:
        raise WebAuthnVerificationError("invalid")
    if data.get("crossOrigin") not in (None, False):
        raise WebAuthnVerificationError("invalid")


def canonical_origin(value: str) -> tuple[str, str]:
    """Accept only a canonical HTTPS DNS origin and return origin/RP ID."""

    if not isinstance(value, str) or len(value) > 253 or value != value.strip():
        raise WebAuthnVerificationError("invalid")
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    labels = hostname.split(".")
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or not hostname
        or len(hostname) > 253
        or any(
            not label
            or len(label) > 63
            or label[0] == "-"
            or label[-1] == "-"
            or not all(character.isascii() and (character.isalnum() or character == "-") for character in label)
            for label in labels
        )
    ):
        raise WebAuthnVerificationError("invalid")
    canonical = f"https://{hostname}"
    if value != canonical:
        raise WebAuthnVerificationError("invalid")
    return canonical, hostname


def _require_fido2() -> tuple[Any, Any, Any, Any]:
    """Import the exact maintained verifier only on a verification path."""

    try:
        from fido2 import cbor
        from fido2.cose import CoseKey
        from fido2.webauthn import AttestationObject, AuthenticatorData
        return cbor, CoseKey, AttestationObject, AuthenticatorData
    except ImportError as exc:  # never replace this with a permissive fallback
        raise WebAuthnVerificationError("unavailable") from exc


def assertion_credential_id(payload: Mapping[str, Any]) -> bytes:
    """Extract the asserted discoverable credential identifier before lookup.

    Authentication ceremonies intentionally do not carry a browser-selected
    allowCredentials list.  The only credential identifier is therefore the
    one returned after the challenge, which is bounded and parsed here before
    the private authority looks up a stored public key.
    """

    try:
        if not isinstance(payload, Mapping) or set(payload) != {
            "credentialId", "clientDataJSON", "authenticatorData", "signature"
        }:
            raise ValueError
        credential_id = _b64url(str(payload["credentialId"]))
        if not 1 <= len(credential_id) <= 1023:
            raise ValueError
        return credential_id
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise WebAuthnVerificationError("invalid") from exc


def _fixed_cose_key(cbor: Any, CoseKey: Any, encoded: bytes) -> Any:
    """Parse and constrain a stored/public WebAuthn key to the fixed policy."""

    decoded = cbor.decode(encoded)
    if not isinstance(decoded, Mapping) or type(decoded.get(3)) is not int:
        raise ValueError
    if decoded[3] not in ALLOWED_COSE_ALGORITHMS:
        raise ValueError
    key = CoseKey.parse(decoded)
    if type(getattr(key, "ALGORITHM", None)) is not int or key.ALGORITHM not in ALLOWED_COSE_ALGORITHMS:
        raise ValueError
    return key


def verify_registration(
    payload: Mapping[str, Any], *, challenge_digest: bytes, origin: str, rp_id: str,
) -> RegistrationEvidence:
    """Verify fixed registration evidence with fido2's WebAuthn structures.

    Attestation is intentionally rejected unless it is the WebAuthn ``none``
    format.  Credential public-key and authenticator-data extraction remain in
    the maintained fido2 parser rather than browser-controlled JSON fields.
    """

    cbor, CoseKey, AttestationObject, _AuthenticatorData = _require_fido2()
    try:
        if set(payload) != {"clientDataJSON", "attestationObject", "clientExtensionResults"}:
            raise ValueError
        extensions = payload["clientExtensionResults"]
        # The fixed creation options require a discoverable credential.  The
        # browser reports the resulting credProps extension; absence or a
        # non-discoverable result is fail-closed.
        if (
            not isinstance(extensions, Mapping)
            or set(extensions) != {"credProps"}
            or not isinstance(extensions["credProps"], Mapping)
            or set(extensions["credProps"]) != {"rk"}
            or extensions["credProps"]["rk"] is not True
        ):
            raise ValueError
        client_data = _b64url(str(payload["clientDataJSON"]))
        _client_data(client_data, challenge_digest=challenge_digest, origin=origin, typ="webauthn.create")
        attestation = AttestationObject(_b64url(str(payload["attestationObject"])))
        if attestation.fmt != "none":
            raise ValueError
        auth_data = attestation.auth_data
        if (
            not auth_data.is_user_present()
            or not auth_data.is_user_verified()
            or auth_data.is_backup_eligible()
            or auth_data.is_backed_up()
        ):
            raise ValueError
        if auth_data.rp_id_hash != hashlib.sha256(rp_id.encode("ascii")).digest() or auth_data.credential_data is None:
            raise ValueError
        credential_data = auth_data.credential_data
        cose = cbor.encode(credential_data.public_key)
        _fixed_cose_key(cbor, CoseKey, cose)
        credential_id = bytes(credential_data.credential_id)
        if not 1 <= len(credential_id) <= 1023:
            raise ValueError
        return RegistrationEvidence(credential_id, cose, int(auth_data.counter), False, False)
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise WebAuthnVerificationError("invalid") from exc


def verify_assertion(
    payload: Mapping[str, Any], *, challenge_digest: bytes, origin: str, rp_id: str,
    cose_public_key: bytes,
) -> AssertionEvidence:
    """Verify assertion origin/RP/UP/UV/BE/BS/signature using fido2."""

    cbor, CoseKey, _AttestationObject, AuthenticatorData = _require_fido2()
    try:
        credential_id = assertion_credential_id(payload)
        client_data = _b64url(str(payload["clientDataJSON"]))
        _client_data(client_data, challenge_digest=challenge_digest, origin=origin, typ="webauthn.get")
        auth_data = AuthenticatorData(_b64url(str(payload["authenticatorData"])))
        if not auth_data.is_user_present() or not auth_data.is_user_verified() or auth_data.is_backup_eligible() or auth_data.is_backed_up():
            raise ValueError
        if auth_data.rp_id_hash != hashlib.sha256(rp_id.encode("ascii")).digest():
            raise ValueError
        _fixed_cose_key(cbor, CoseKey, cose_public_key).verify(auth_data + hashlib.sha256(client_data).digest(), _b64url(str(payload["signature"])))
        return AssertionEvidence(credential_id, int(auth_data.counter), False, False)
    except (ValueError, TypeError, KeyError, UnicodeError, InvalidSignature) as exc:
        # Signature failure shares the generic verifier result; it is never
        # a browser-visible credential or signing oracle.
        raise WebAuthnVerificationError("invalid") from exc
