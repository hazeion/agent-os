"""Durable, owner-private identity authority while remote access is disabled.

This service owns the security transaction state only.  It deliberately does
not open a listener, issue HTTP responses, or expose SQLite to Node.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Any

from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError

from mentat_db import connect, transaction
from private_state import mentat_server_active, private_state_lock
from owner_auth_webauthn import (
    AssertionEvidence as _AssertionEvidence,
    RegistrationEvidence as _RegistrationEvidence,
    WebAuthnVerificationError,
    assertion_credential_id,
    canonical_origin, verify_assertion, verify_registration,
)

BOOTSTRAP_SECONDS = 10 * 60
CEREMONY_SECONDS = 5 * 60
REAUTH_SECONDS = 10 * 60
SESSION_IDLE_SECONDS = 60 * 60
SESSION_ABSOLUTE_SECONDS = 24 * 60 * 60
RECOVERY_CODE_COUNT = 10
MAX_CEREMONIES = 32
MAX_UNAUTH_CEREMONIES = 5
MAX_DEVICE_SESSIONS = 8
MAX_OWNER_SESSIONS = 32
MAX_TERMINAL_SESSIONS = 128
TERMINAL_SESSION_GRACE_SECONDS = 24 * 60 * 60
MAX_AUDIT_ROWS = 512
MAX_CREDENTIALS = 128
MAX_TERMINAL_CEREMONIES = 32
AUTHENTICATION_START_LIMIT = 10
RECOVERY_SUBMISSION_LIMIT = 5
UNSAFE_REQUEST_LIMIT = 60
SECURITY_MANAGEMENT_LIMIT = 1
MAX_SSE_STREAMS = 2
COOKIE_NAME = "__Host-mentat"
_PHC_PREFIX = "$argon2id$v=19$m=65536,t=3,p=4$"
_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16, type=Type.ID)


class OwnerAuthError(RuntimeError):
    """Fixed public-safe failure; callers must not disclose its detail."""


@dataclass(frozen=True)
class BootstrapGrant:
    code: str
    expires_at: float


@dataclass(frozen=True)
class Ceremony:
    ceremony_id: str
    challenge: str
    origin: str
    rp_id: str
    expires_at: float
    public_key_options: Mapping[str, Any]


@dataclass(frozen=True)
class SessionGrant:
    cookie_value: str
    csrf_value: str
    recovery_codes: tuple[str, ...]


@dataclass(frozen=True)
class SseReservation:
    """A process-owned lease for one live session-bound SSE stream.

    The opaque identifier is never a browser credential.  The server keeps it
    only long enough to release this exact stream on disconnect.
    """

    reservation_id: str
    session_revision: int


def _digest(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def _token(bytes_count: int) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(bytes_count)).rstrip(b"=").decode("ascii")


def _token_bytes(value: str, expected: int) -> bytes:
    if not isinstance(value, str) or len(value) > 256 or "=" in value:
        raise OwnerAuthError("invalid")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeError) as exc:
        raise OwnerAuthError("invalid") from exc
    if len(raw) != expected:
        raise OwnerAuthError("invalid")
    return raw


def _id() -> str:
    return _token(24)


def _label(value: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or value != value.strip() or any(ord(character) < 32 for character in value):
        raise OwnerAuthError("invalid")
    # Labels are intentionally not persisted: this authority stores no browser-facing device material.
    return value


def _hash_recovery(value: str) -> str:
    if not isinstance(value, str) or not 16 <= len(value) <= 128:
        raise OwnerAuthError("invalid")
    return _HASHER.hash(value)


def _verify_recovery(value: str, verifier: str) -> bool:
    if not isinstance(value, str) or not 16 <= len(value) <= 128 or not verifier.startswith(_PHC_PREFIX):
        return False
    try:
        parameters = extract_parameters(verifier)
        if (
            parameters.type is not Type.ID
            or parameters.version != 19
            or parameters.memory_cost != 65536
            or parameters.time_cost != 3
            or parameters.parallelism != 4
            or parameters.salt_len != 16
            or parameters.hash_len != 32
        ):
            return False
        return bool(_HASHER.verify(verifier, value))
    except (InvalidHashError, VerificationError):
        return False


class OwnerAuthAuthority:
    """One Python-only transaction surface for the durable owner authority."""

    def __init__(
        self,
        data_dir: Path,
        *,
        clock: Callable[[], float] = time.time,
        _registration_verifier: Callable[..., _RegistrationEvidence] = verify_registration,
        _assertion_verifier: Callable[..., _AssertionEvidence] = verify_assertion,
        _assertion_credential_id: Callable[[Mapping[str, Any]], bytes] = assertion_credential_id,
    ):
        self._data_dir = Path(data_dir)
        self._clock = clock
        # These are process-private test seams.  Public completion methods
        # accept only browser payload mappings and always invoke this boundary.
        self._registration_verifier = _registration_verifier
        self._assertion_verifier = _assertion_verifier
        self._assertion_credential_id = _assertion_credential_id

    def _open(self) -> sqlite3.Connection:
        connection = connect(self._data_dir)
        connection.row_factory = sqlite3.Row
        return connection

    def _audit(self, connection: sqlite3.Connection, event: str, kind: str, subject: bytes | None, now: float) -> None:
        connection.execute("INSERT INTO mentat_owner_auth_audit(event, subject_kind, subject_digest, occurred_at) VALUES (?, ?, ?, ?)", (event, kind, subject, now))
        connection.execute("DELETE FROM mentat_owner_auth_audit WHERE id NOT IN (SELECT id FROM mentat_owner_auth_audit ORDER BY id DESC LIMIT ?)", (MAX_AUDIT_ROWS,))

    def _audit_admission_rejection(self, connection: sqlite3.Connection, scope: str, now: float) -> None:
        """Record only bounded aggregate rejection evidence, never subjects."""

        window = now - (now % 60)
        connection.execute(
            "INSERT INTO mentat_owner_auth_rejection_audit(admission_class, window_started_at, count) VALUES (?, ?, 1) "
            "ON CONFLICT(admission_class, window_started_at) DO UPDATE SET count = count + 1",
            (scope, window),
        )
        connection.execute(
            "DELETE FROM mentat_owner_auth_rejection_audit WHERE (window_started_at, admission_class) NOT IN "
            "(SELECT window_started_at, admission_class FROM mentat_owner_auth_rejection_audit "
            "ORDER BY window_started_at DESC, admission_class DESC LIMIT ?)",
            (MAX_AUDIT_ROWS,),
        )

    def _cleanup(
        self,
        connection: sqlite3.Connection,
        now: float,
        *,
        clear_sse: bool = False,
        terminalize_consumed_at_startup: bool = False,
    ) -> None:
        # An expired stopped-server bootstrap must not permanently strand the
        # authority in bootstrap_open.  Clearing it is atomic with ceremony and
        # grant cleanup, so a later bootstrap starts from a known blank state.
        connection.execute(
            "UPDATE mentat_owner_auth_state SET state = 'unbootstrapped', canonical_origin = NULL, rp_id = NULL, "
            "bootstrap_verifier = NULL, bootstrap_user_handle = NULL, bootstrap_expires_at = NULL, "
            "configuration_revision = configuration_revision + 1, revision = revision + 1, updated_at = ? "
            "WHERE singleton = 1 AND state = 'bootstrap_open' AND bootstrap_expires_at <= ?",
            (now, now),
        )
        connection.execute("UPDATE mentat_owner_auth_ceremonies SET state = 'expired', consumed_at = ? WHERE state = 'pending' AND expires_at <= ?", (now, now))
        connection.execute(
            "UPDATE mentat_owner_auth_recovery_codes SET state = 'active', reserved_ceremony_id = NULL, updated_at = ? "
            "WHERE state = 'reserved' AND reserved_ceremony_id IN ("
            "SELECT ceremony_id FROM mentat_owner_auth_ceremonies WHERE state IN ('expired', 'cancelled')"
            ")",
            (now,),
        )
        if terminalize_consumed_at_startup:
            # A process restart has no verifier in flight.  Every durable
            # consumed marker is therefore an interrupted completion, not a
            # live operation.  Terminalizing every purpose lets the shared
            # collector enforce its one global cap after a crash.  Recovery
            # codes are then released only because their exact recovery
            # ceremony is now terminal.
            connection.execute(
                "UPDATE mentat_owner_auth_ceremonies SET state = 'cancelled', consumed_at = ? "
                "WHERE state = 'consumed'",
                (now,),
            )
            connection.execute(
                "UPDATE mentat_owner_auth_recovery_codes SET state = 'active', reserved_ceremony_id = NULL, updated_at = ? "
                "WHERE state = 'reserved' AND reserved_ceremony_id IN ("
                "SELECT ceremony_id FROM mentat_owner_auth_ceremonies "
                "WHERE purpose = 'recovery' AND state = 'cancelled'"
                ")",
                (now,),
            )
        connection.execute("UPDATE mentat_owner_auth_sessions SET state = 'expired', revoked_at = ? WHERE state = 'active' AND (idle_expires_at <= ? OR absolute_expires_at <= ?)", (now, now, now))
        # A stream is never allowed to outlive the exact live session that
        # reserved it.  Startup has no surviving stream owner, so it clears
        # every durable reservation before publishing readiness.
        if clear_sse:
            connection.execute("DELETE FROM mentat_owner_auth_sse_reservations")
        else:
            connection.execute(
                "DELETE FROM mentat_owner_auth_sse_reservations WHERE session_digest IN "
                "(SELECT session_digest FROM mentat_owner_auth_sessions WHERE state != 'active')"
            )
        connection.execute("DELETE FROM mentat_owner_auth_sessions WHERE state != 'active' AND revoked_at < ?", (now - TERMINAL_SESSION_GRACE_SECONDS,))
        connection.execute("DELETE FROM mentat_owner_auth_sessions WHERE session_digest IN (SELECT session_digest FROM mentat_owner_auth_sessions WHERE state != 'active' ORDER BY revoked_at DESC, session_digest DESC LIMIT -1 OFFSET ?)", (MAX_TERMINAL_SESSIONS,))
        # Keep only a bounded amount of terminal protocol state.  Pending
        # ceremonies and active/reserved recovery codes are never collectors'
        # targets, so cleanup cannot turn an uncertain operation into success.
        connection.execute(
            "DELETE FROM mentat_owner_auth_ceremonies WHERE ceremony_id IN ("
            "SELECT ceremony_id FROM mentat_owner_auth_ceremonies WHERE state != 'pending' AND state != 'consumed' "
            "ORDER BY consumed_at DESC, ceremony_id DESC LIMIT -1 OFFSET ?) ",
            (MAX_TERMINAL_CEREMONIES,),
        )
        connection.execute(
            "DELETE FROM mentat_owner_auth_recovery_codes WHERE state IN ('consumed', 'revoked') "
            "AND updated_at < ?",
            (now - CEREMONY_SECONDS,),
        )
        connection.execute(
            "DELETE FROM mentat_owner_auth_credentials WHERE state != 'active' "
            "AND NOT EXISTS (SELECT 1 FROM mentat_owner_auth_sessions AS s "
            "WHERE s.device_id = mentat_owner_auth_credentials.device_id)"
        )
        connection.execute("DELETE FROM mentat_owner_auth_rate_buckets WHERE window_started_at < ?", (now - 60,))

    def _admit(self, connection: sqlite3.Connection, scope: str, subject: bytes, limit: int, now: float) -> bool:
        """Fixed one-minute admission before expensive verifier work."""

        window = now - (now % 60)
        row = connection.execute("SELECT window_started_at, used FROM mentat_owner_auth_rate_buckets WHERE scope = ? AND subject_digest = ?", (scope, subject)).fetchone()
        if row is None or float(row["window_started_at"]) != window:
            connection.execute("INSERT INTO mentat_owner_auth_rate_buckets(scope, subject_digest, window_started_at, used) VALUES (?, ?, ?, 1) ON CONFLICT(scope, subject_digest) DO UPDATE SET window_started_at = excluded.window_started_at, used = 1", (scope, subject, window))
            return True
        if int(row["used"]) >= limit:
            self._audit_admission_rejection(connection, scope, now)
            return False
        connection.execute("UPDATE mentat_owner_auth_rate_buckets SET used = used + 1 WHERE scope = ? AND subject_digest = ?", (scope, subject))
        return True

    def _admit_durable(self, scope: str, subject: bytes, limit: int) -> bool:
        """Commit admission (including a rejection) before verifier work.

        A rejected request must leave a durable, aggregate record even though
        the caller raises a generic failure.  Performing this compact
        transaction separately also prevents a later validation failure from
        rolling the rate bucket back.
        """

        now = self._clock()
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                self._cleanup(connection, now)
                return self._admit(connection, scope, subject, limit, now)
        finally:
            connection.close()

    @staticmethod
    def _registration_options(challenge: str, state: sqlite3.Row) -> Mapping[str, Any]:
        user_handle = state["user_handle"] if state["state"] == "active" else state["bootstrap_user_handle"]
        if not isinstance(user_handle, bytes) or len(user_handle) != 32:
            raise OwnerAuthError("invalid")
        return {
            "challenge": challenge,
            "rp": {"id": str(state["rp_id"]), "name": "Mentat"},
            "user": {
                "id": base64.urlsafe_b64encode(user_handle).rstrip(b"=").decode("ascii"),
                "name": "owner",
                "displayName": "Mentat owner",
            },
            "pubKeyCredParams": ({"type": "public-key", "alg": -7},),
            "timeout": CEREMONY_SECONDS * 1000,
            "attestation": "none",
            "authenticatorSelection": {
                "residentKey": "required",
                "requireResidentKey": True,
                "userVerification": "required",
            },
            "extensions": {"credProps": True},
        }

    @staticmethod
    def _authentication_options(challenge: str, state: sqlite3.Row) -> Mapping[str, Any]:
        return {
            "challenge": challenge,
            "rpId": str(state["rp_id"]),
            "timeout": CEREMONY_SECONDS * 1000,
            "userVerification": "required",
        }

    def open_bootstrap(self, origin: str) -> BootstrapGrant:
        """Create the sole local-terminal bootstrap grant while the server is stopped."""

        canonical, rp_id = canonical_origin(origin)
        now = self._clock()
        code = _token(16)
        with private_state_lock(self._data_dir):
            # The initial observation is deliberately made under the same
            # private-state lock as the state transition.  A server that wins
            # the race must make bootstrap fail closed rather than receiving a
            # usable terminal grant beside a live listener.
            if mentat_server_active(self._data_dir):
                raise OwnerAuthError("server_active")
            connection = self._open()
            try:
                with transaction(connection, immediate=True):
                    self._cleanup(connection, now)
                    state = connection.execute("SELECT state FROM mentat_owner_auth_state WHERE singleton = 1").fetchone()
                    if state is None or state[0] == "active":
                        raise OwnerAuthError("unavailable")
                    connection.execute("UPDATE mentat_owner_auth_state SET state = 'bootstrap_open', canonical_origin = ?, rp_id = ?, configuration_revision = configuration_revision + 1, bootstrap_verifier = ?, bootstrap_user_handle = ?, bootstrap_generation = bootstrap_generation + 1, bootstrap_expires_at = ?, revision = revision + 1, updated_at = ? WHERE singleton = 1", (canonical, rp_id, _hash_recovery(code), secrets.token_bytes(32), now + BOOTSTRAP_SECONDS, now))
                    self._audit(connection, "bootstrap_opened", "owner", None, now)
            finally:
                connection.close()
        return BootstrapGrant(code, now + BOOTSTRAP_SECONDS)

    def _state(self, connection: sqlite3.Connection) -> sqlite3.Row:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM mentat_owner_auth_state WHERE singleton = 1").fetchone()
        if row is None:
            raise OwnerAuthError("invalid")
        return row

    def _reserve_ceremony(self, connection: sqlite3.Connection, *, purpose: str, challenge: bytes, session: sqlite3.Row | None = None, recovery_id: str | None = None, credential_digest: bytes | None = None) -> Ceremony:
        now = self._clock()
        self._cleanup(connection, now)
        state = self._state(connection)
        if state["state"] not in {"bootstrap_open", "active"}:
            raise OwnerAuthError("invalid")
        count = int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_ceremonies WHERE state = 'pending'").fetchone()[0])
        unauthenticated = purpose in {"bootstrap", "authentication", "recovery"}
        unauthenticated_count = int(connection.execute(
            "SELECT COUNT(*) FROM mentat_owner_auth_ceremonies WHERE state = 'pending' "
            "AND purpose IN ('bootstrap', 'authentication', 'recovery')"
        ).fetchone()[0])
        if count >= MAX_CEREMONIES or (unauthenticated and unauthenticated_count >= MAX_UNAUTH_CEREMONIES):
            raise OwnerAuthError("limited")
        expires = min(now + CEREMONY_SECONDS, float(state["bootstrap_expires_at"])) if purpose == "bootstrap" else now + CEREMONY_SECONDS
        ceremony_id = _id()
        connection.execute("INSERT INTO mentat_owner_auth_ceremonies(ceremony_id, purpose, challenge_digest, configuration_revision, session_digest, session_revision, recovery_id, credential_lookup_digest, expires_at, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)", (ceremony_id, purpose, _digest(challenge), int(state["configuration_revision"]), None if session is None else session["session_digest"], None if session is None else session["revision"], recovery_id, credential_digest, expires, now))
        encoded_challenge = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode("ascii")
        options = (
            self._registration_options(encoded_challenge, state)
            if purpose in {"bootstrap", "device_add", "recovery"}
            else self._authentication_options(encoded_challenge, state)
        )
        return Ceremony(ceremony_id, encoded_challenge, str(state["canonical_origin"]), str(state["rp_id"]), expires, options)

    def start_bootstrap_registration(self, code: str, label: str) -> Ceremony:
        _label(label)
        now = self._clock()
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                state = self._state(connection)
                if state["state"] != "bootstrap_open" or float(state["bootstrap_expires_at"]) <= now or not _verify_recovery(code, str(state["bootstrap_verifier"])):
                    raise OwnerAuthError("invalid")
                return self._reserve_ceremony(connection, purpose="bootstrap", challenge=secrets.token_bytes(32))
        finally:
            connection.close()

    def _consume_ceremony_durable(self, ceremony_id: str, purpose: Iterable[str]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Terminally consume a ceremony *before* untrusted verification.

        WebAuthn and Argon2 verification may fail or be interrupted.  A
        failed completion is still terminal: rolling back the marker would
        make the same signed assertion or registration replayable.
        """
        now = self._clock()
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                self._cleanup(connection, now)
                row = connection.execute("SELECT * FROM mentat_owner_auth_ceremonies WHERE ceremony_id = ?", (ceremony_id,)).fetchone()
                state = self._state(connection)
                if row is None or row["state"] != "pending" or row["purpose"] not in set(purpose) or float(row["expires_at"]) <= now:
                    raise OwnerAuthError("invalid")
                updated = connection.execute("UPDATE mentat_owner_auth_ceremonies SET state = 'consumed', consumed_at = ? WHERE ceremony_id = ? AND state = 'pending'", (now, ceremony_id))
                if updated.rowcount != 1:
                    raise OwnerAuthError("invalid")
                return dict(row), dict(state)
        finally:
            connection.close()

    def _revoke_session_digest(self, connection: sqlite3.Connection, digest: bytes, now: float) -> None:
        connection.execute("UPDATE mentat_owner_auth_sessions SET state = 'revoked', revoked_at = ?, revision = revision + 1 WHERE session_digest = ? AND state = 'active'", (now, digest))

    def _release_failed_recovery(self, ceremony_id: str) -> None:
        """Return one code only after its consumed ceremony has failed."""

        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                now = self._clock()
                connection.execute(
                    "UPDATE mentat_owner_auth_ceremonies SET state = 'cancelled', consumed_at = ? "
                    "WHERE ceremony_id = ? AND purpose = 'recovery' AND state = 'consumed'",
                    (now, ceremony_id),
                )
                connection.execute(
                    "UPDATE mentat_owner_auth_recovery_codes SET state = 'active', reserved_ceremony_id = NULL, updated_at = ? "
                    "WHERE state = 'reserved' AND reserved_ceremony_id = ?",
                    (now, ceremony_id),
                )
                self._cleanup(connection, now)
        finally:
            connection.close()

    def _cancel_failed_ceremony(self, ceremony_id: str) -> None:
        """Record a failed consumed ceremony and run its bounded collector."""

        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                now = self._clock()
                self._terminate_ceremony(connection, ceremony_id, now)
        finally:
            connection.close()

    def _terminate_ceremony(self, connection: sqlite3.Connection, ceremony_id: str, now: float) -> None:
        """Finish an already-consumed ceremony so terminal retention is bounded."""

        connection.execute(
            "UPDATE mentat_owner_auth_ceremonies SET state = 'cancelled', consumed_at = ? "
            "WHERE ceremony_id = ? AND state = 'consumed'",
            (now, ceremony_id),
        )
        self._cleanup(connection, now)

    def _new_session(self, connection: sqlite3.Connection, device_id: str, now: float, *, reauthenticated: bool = False) -> SessionGrant:
        cookie = _token(32)
        csrf = _token(32)
        digest = _digest(_token_bytes(cookie, 32))
        csrf_digest = _digest(_token_bytes(csrf, 32))
        # Deterministic oldest-session eviction keeps both exact capacity limits.
        for sql, args, limit in (
            ("SELECT session_digest FROM mentat_owner_auth_sessions WHERE state = 'active' AND device_id = ? ORDER BY created_at, session_digest", (device_id,), MAX_DEVICE_SESSIONS - 1),
            ("SELECT session_digest FROM mentat_owner_auth_sessions WHERE state = 'active' ORDER BY created_at, session_digest", (), MAX_OWNER_SESSIONS - 1),
        ):
            rows = connection.execute(sql, args).fetchall()
            for row in rows[limit:]: self._revoke_session_digest(connection, row[0], now)
        connection.execute("INSERT INTO mentat_owner_auth_sessions(session_digest, csrf_digest, device_id, state, created_at, reauthenticated_at, last_seen_at, idle_expires_at, absolute_expires_at) VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?)", (digest, csrf_digest, device_id, now, now if reauthenticated else 0, now, now + SESSION_IDLE_SECONDS, now + SESSION_ABSOLUTE_SECONDS))
        return SessionGrant(cookie, csrf, ())

    def _new_recovery_codes(self, connection: sqlite3.Connection, generation: int, now: float) -> tuple[str, ...]:
        codes: list[str] = []
        for _ in range(RECOVERY_CODE_COUNT):
            code = _token(16)
            codes.append(code)
            connection.execute("INSERT INTO mentat_owner_auth_recovery_codes(recovery_id, verifier, generation, state, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)", (_id(), _hash_recovery(code), generation, now, now))
        return tuple(codes)

    def finish_registration(self, ceremony_id: str, payload: Mapping[str, Any]) -> SessionGrant:
        row, state_snapshot = self._consume_ceremony_durable(ceremony_id, ("bootstrap", "device_add", "recovery"))
        recovery_ceremony = row["purpose"] == "recovery"

        def reject() -> None:
            if recovery_ceremony:
                self._release_failed_recovery(ceremony_id)
            else:
                self._cancel_failed_ceremony(ceremony_id)
            raise OwnerAuthError("invalid")

        if not isinstance(payload, Mapping):
            reject()
        try:
            parsed = self._registration_verifier(
                payload,
                challenge_digest=bytes(row["challenge_digest"]),
                origin=str(state_snapshot["canonical_origin"]),
                rp_id=str(state_snapshot["rp_id"]),
            )
        except WebAuthnVerificationError as exc:
            if recovery_ceremony:
                self._release_failed_recovery(ceremony_id)
            else:
                self._cancel_failed_ceremony(ceremony_id)
            raise OwnerAuthError("invalid") from exc
        if parsed.backup_eligible or parsed.backup_state:
            reject()
        credential_digest = _digest(parsed.credential_id)
        now = self._clock()
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                state = self._state(connection)
                if (
                    int(row["configuration_revision"]) != int(state["configuration_revision"])
                    or str(state["canonical_origin"]) != str(state_snapshot["canonical_origin"])
                    or str(state["rp_id"]) != str(state_snapshot["rp_id"])
                ):
                    raise OwnerAuthError("invalid")
                consumed = connection.execute(
                    "SELECT 1 FROM mentat_owner_auth_ceremonies WHERE ceremony_id = ? AND state = 'consumed'",
                    (ceremony_id,),
                ).fetchone()
                if consumed is None:
                    raise OwnerAuthError("invalid")
                if connection.execute("SELECT 1 FROM mentat_owner_auth_credentials WHERE credential_lookup_digest = ?", (credential_digest,)).fetchone(): raise OwnerAuthError("invalid")
                if int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials WHERE state = 'active'").fetchone()[0]) >= MAX_CREDENTIALS:
                    raise OwnerAuthError("limited")
                if row["purpose"] == "bootstrap" and state["state"] != "bootstrap_open": raise OwnerAuthError("invalid")
                if row["purpose"] == "device_add":
                    authorizer = connection.execute("SELECT * FROM mentat_owner_auth_sessions WHERE session_digest = ?", (row["session_digest"],)).fetchone()
                    if authorizer is None or authorizer["state"] != "active" or int(authorizer["revision"]) != int(row["session_revision"]) or now - float(authorizer["reauthenticated_at"]) > REAUTH_SECONDS: raise OwnerAuthError("invalid")
                if row["purpose"] == "bootstrap":
                    bootstrap_user_handle = state["bootstrap_user_handle"]
                    if not isinstance(bootstrap_user_handle, bytes) or len(bootstrap_user_handle) != 32:
                        raise OwnerAuthError("invalid")
                    connection.execute("UPDATE mentat_owner_auth_state SET state = 'active', user_handle = ?, bootstrap_verifier = NULL, bootstrap_user_handle = NULL, bootstrap_expires_at = NULL, revision = revision + 1, updated_at = ? WHERE singleton = 1", (bootstrap_user_handle, now))
                    codes = self._new_recovery_codes(connection, 1, now)
                    self._audit(connection, "bootstrap_completed", "owner", None, now)
                elif row["purpose"] == "recovery":
                    recovery = connection.execute("SELECT * FROM mentat_owner_auth_recovery_codes WHERE recovery_id = ?", (row["recovery_id"],)).fetchone()
                    if recovery is None or recovery["state"] != "reserved" or recovery["reserved_ceremony_id"] != ceremony_id: raise OwnerAuthError("invalid")
                    connection.execute("UPDATE mentat_owner_auth_recovery_codes SET state = 'consumed', reserved_ceremony_id = NULL, updated_at = ? WHERE recovery_id = ? AND state = 'reserved'", (now, row["recovery_id"]))
                    connection.execute("UPDATE mentat_owner_auth_recovery_codes SET state = 'revoked', reserved_ceremony_id = NULL, updated_at = ? WHERE state IN ('active', 'reserved')", (now,))
                    connection.execute("UPDATE mentat_owner_auth_credentials SET state = 'revoked', revoked_at = ? WHERE state = 'active'", (now,))
                    connection.execute("UPDATE mentat_owner_auth_sessions SET state = 'revoked', revoked_at = ?, revision = revision + 1 WHERE state = 'active'", (now,))
                    generation = int(recovery["generation"]) + 1
                    codes = self._new_recovery_codes(connection, generation, now)
                    self._audit(connection, "recovery_completed", "owner", None, now)
                else: codes = ()
                device = _id()
                connection.execute("INSERT INTO mentat_owner_auth_credentials(device_id, credential_lookup_digest, cose_public_key, sign_count, state, created_at) VALUES (?, ?, ?, ?, 'active', ?)", (device, credential_digest, parsed.cose_public_key, parsed.sign_count, now))
                grant = self._new_session(connection, device, now)
                self._terminate_ceremony(connection, ceremony_id, now)
                return SessionGrant(grant.cookie_value, grant.csrf_value, codes)
        except OwnerAuthError:
            if recovery_ceremony:
                self._release_failed_recovery(ceremony_id)
            else:
                self._cancel_failed_ceremony(ceremony_id)
            raise
        finally:
            connection.close()

    def start_recovery_registration(self, code: str, label: str) -> Ceremony:
        _label(label)
        now = self._clock()
        if not self._admit_durable("recovery_submission", b"\0" * 32, RECOVERY_SUBMISSION_LIMIT):
            raise OwnerAuthError("limited")
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                self._cleanup(connection, now)
                state = self._state(connection)
                if state["state"] != "active": raise OwnerAuthError("invalid")
                match = None
                for row in connection.execute("SELECT * FROM mentat_owner_auth_recovery_codes WHERE state = 'active' ORDER BY recovery_id"):
                    if _verify_recovery(code, str(row["verifier"])): match = row; break
                if match is None: raise OwnerAuthError("invalid")
                ceremony = self._reserve_ceremony(connection, purpose="recovery", challenge=secrets.token_bytes(32), recovery_id=str(match["recovery_id"]))
                connection.execute("UPDATE mentat_owner_auth_recovery_codes SET state = 'reserved', reserved_ceremony_id = ?, updated_at = ? WHERE recovery_id = ? AND state = 'active'", (ceremony.ceremony_id, now, match["recovery_id"]))
                self._audit(connection, "recovery_reserved", "owner", None, now)
                return ceremony
        finally:
            connection.close()

    def start_authentication(self) -> Ceremony:
        """Start a discoverable-credential login without an identifier oracle."""

        if not self._admit_durable("authentication_start", b"\0" * 32, AUTHENTICATION_START_LIMIT):
            raise OwnerAuthError("limited")
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                # Discoverable credentials keep both known and unknown devices
                # outside the pre-challenge surface.
                if self._state(connection)["state"] != "active":
                    raise OwnerAuthError("invalid")
                return self._reserve_ceremony(connection, purpose="authentication", challenge=secrets.token_bytes(32))
        finally:
            connection.close()

    def finish_authentication(self, ceremony_id: str, payload: Mapping[str, Any]) -> SessionGrant:
        row, state_snapshot = self._consume_ceremony_durable(ceremony_id, ("authentication", "reauthentication"))
        if not isinstance(payload, Mapping):
            self._cancel_failed_ceremony(ceremony_id)
            raise OwnerAuthError("invalid")
        try:
            credential_digest = _digest(self._assertion_credential_id(payload))
        except WebAuthnVerificationError as exc:
            self._cancel_failed_ceremony(ceremony_id)
            raise OwnerAuthError("invalid") from exc
        connection = self._open()
        try:
            credential = connection.execute("SELECT * FROM mentat_owner_auth_credentials WHERE credential_lookup_digest = ?", (credential_digest,)).fetchone()
            if credential is None or credential["state"] != "active":
                raise OwnerAuthError("invalid")
            if row["purpose"] == "reauthentication" and not hmac.compare_digest(credential_digest, bytes(row["credential_lookup_digest"])):
                raise OwnerAuthError("invalid")
            parsed = self._assertion_verifier(
                payload,
                challenge_digest=bytes(row["challenge_digest"]),
                origin=str(state_snapshot["canonical_origin"]),
                rp_id=str(state_snapshot["rp_id"]),
                cose_public_key=bytes(credential["cose_public_key"]),
            )
        except WebAuthnVerificationError as exc:
            self._cancel_failed_ceremony(ceremony_id)
            raise OwnerAuthError("invalid") from exc
        except OwnerAuthError:
            self._cancel_failed_ceremony(ceremony_id)
            raise
        finally:
            connection.close()
        if _digest(parsed.credential_id) != credential_digest or parsed.backup_eligible or parsed.backup_state:
            self._cancel_failed_ceremony(ceremony_id)
            raise OwnerAuthError("invalid")
        now = self._clock()
        connection = self._open()
        suspected_clone = False
        try:
            with transaction(connection, immediate=True):
                state = self._state(connection)
                if (
                    state["state"] != "active"
                    or int(row["configuration_revision"]) != int(state["configuration_revision"])
                    or str(state["canonical_origin"]) != str(state_snapshot["canonical_origin"])
                    or str(state["rp_id"]) != str(state_snapshot["rp_id"])
                    or connection.execute("SELECT 1 FROM mentat_owner_auth_ceremonies WHERE ceremony_id = ? AND state = 'consumed'", (ceremony_id,)).fetchone() is None
                ):
                    raise OwnerAuthError("invalid")
                credential = connection.execute("SELECT * FROM mentat_owner_auth_credentials WHERE credential_lookup_digest = ?", (credential_digest,)).fetchone()
                if credential is None or credential["state"] != "active":
                    raise OwnerAuthError("invalid")
                stored_count = int(credential["sign_count"])
                if (stored_count != 0 or parsed.sign_count != 0) and parsed.sign_count <= stored_count:
                    connection.execute("UPDATE mentat_owner_auth_credentials SET state = 'suspected_clone', revoked_at = ?, revision = revision + 1 WHERE device_id = ?", (now, credential["device_id"]))
                    connection.execute("UPDATE mentat_owner_auth_sessions SET state = 'revoked', revoked_at = ?, revision = revision + 1 WHERE device_id = ? AND state = 'active'", (now, credential["device_id"]))
                    self._audit(connection, "credential_clone_suspected", "credential", _digest(str(credential["device_id"]).encode()), now)
                    suspected_clone = True
                else:
                    connection.execute("UPDATE mentat_owner_auth_credentials SET sign_count = ?, revision = revision + 1 WHERE device_id = ?", (parsed.sign_count, credential["device_id"]))
                    self._audit(connection, "authentication_succeeded", "credential", _digest(str(credential["device_id"]).encode()), now)
                    if row["purpose"] == "reauthentication":
                        authorizer = connection.execute("SELECT * FROM mentat_owner_auth_sessions WHERE session_digest = ?", (row["session_digest"],)).fetchone()
                        if authorizer is None or authorizer["state"] != "active" or int(authorizer["revision"]) != int(row["session_revision"]) or authorizer["device_id"] != credential["device_id"]:
                            raise OwnerAuthError("invalid")
                        self._revoke_session_digest(connection, bytes(row["session_digest"]), now)
                        self._audit(connection, "session_reauthenticated", "session", bytes(row["session_digest"]), now)
                    grant = self._new_session(connection, str(credential["device_id"]), now, reauthenticated=row["purpose"] == "reauthentication")
                self._terminate_ceremony(connection, ceremony_id, now)
            if suspected_clone:
                raise OwnerAuthError("invalid")
            return grant
        except WebAuthnVerificationError as exc:
            self._cancel_failed_ceremony(ceremony_id)
            raise OwnerAuthError("invalid") from exc
        except OwnerAuthError:
            self._cancel_failed_ceremony(ceremony_id)
            raise
        finally:
            connection.close()

    def authenticate_session(self, cookie_value: str, csrf_value: str | None = None, *, touch: bool = True) -> sqlite3.Row:
        now = self._clock()
        digest = _digest(_token_bytes(cookie_value, 32))
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                self._cleanup(connection, now)
                row = connection.execute("SELECT * FROM mentat_owner_auth_sessions WHERE session_digest = ?", (digest,)).fetchone()
                device = None if row is None else connection.execute("SELECT state FROM mentat_owner_auth_credentials WHERE device_id = ?", (row["device_id"],)).fetchone()
                if row is None or row["state"] != "active" or device is None or device["state"] != "active" or (csrf_value is not None and not hmac.compare_digest(bytes(row["csrf_digest"]), _digest(_token_bytes(csrf_value, 32)))): raise OwnerAuthError("invalid")
                if touch: connection.execute("UPDATE mentat_owner_auth_sessions SET last_seen_at = ?, idle_expires_at = ?, revision = revision + 1 WHERE session_digest = ?", (now, min(now + SESSION_IDLE_SECONDS, float(row["absolute_expires_at"])), digest))
                return row
        finally:
            connection.close()

    @staticmethod
    def _fresh_reauthentication(session: sqlite3.Row, now: float) -> bool:
        return float(session["reauthenticated_at"]) > 0 and now - float(session["reauthenticated_at"]) <= REAUTH_SECONDS

    def start_device_reauthentication(self, cookie_value: str, csrf_value: str) -> Ceremony:
        """Bind a distinct WebAuthn ceremony to the current session and device.

        A bootstrap, recovery, or ordinary login grant is intentionally not a
        security-management reauthentication.  Completion rotates this exact
        session into a fresh reauthenticated grant, invalidating its old CSRF
        token before device enrollment can proceed.
        """

        session = self.authenticate_session(cookie_value, csrf_value, touch=False)
        digest = _digest(_token_bytes(cookie_value, 32))
        if not self._admit_durable("unsafe_request", digest, UNSAFE_REQUEST_LIMIT):
            raise OwnerAuthError("limited")
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                now = self._clock()
                self._cleanup(connection, now)
                current = connection.execute("SELECT * FROM mentat_owner_auth_sessions WHERE session_digest = ?", (digest,)).fetchone()
                if current is None or current["state"] != "active" or int(current["revision"]) != int(session["revision"]) or not hmac.compare_digest(bytes(current["csrf_digest"]), _digest(_token_bytes(csrf_value, 32))):
                    raise OwnerAuthError("invalid")
                credential = connection.execute("SELECT * FROM mentat_owner_auth_credentials WHERE device_id = ?", (current["device_id"],)).fetchone()
                if credential is None or credential["state"] != "active":
                    raise OwnerAuthError("invalid")
                return self._reserve_ceremony(connection, purpose="reauthentication", challenge=secrets.token_bytes(32), session=current, credential_digest=bytes(credential["credential_lookup_digest"]))
        finally:
            connection.close()

    def reserve_sse(self, cookie_value: str) -> SseReservation:
        """Reserve one of exactly two durable live SSE slots for a session."""

        now = self._clock()
        digest = _digest(_token_bytes(cookie_value, 32))
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                self._cleanup(connection, now)
                session = connection.execute(
                    "SELECT * FROM mentat_owner_auth_sessions WHERE session_digest = ?", (digest,)
                ).fetchone()
                device = None if session is None else connection.execute(
                    "SELECT state FROM mentat_owner_auth_credentials WHERE device_id = ?", (session["device_id"],)
                ).fetchone()
                if session is None or session["state"] != "active" or device is None or device["state"] != "active":
                    raise OwnerAuthError("invalid")
                count = int(connection.execute(
                    "SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations WHERE session_digest = ?", (digest,)
                ).fetchone()[0])
                if count >= MAX_SSE_STREAMS:
                    self._audit_admission_rejection(connection, "sse", now)
                    raise OwnerAuthError("limited")
                reservation_id = _id()
                connection.execute(
                    "INSERT INTO mentat_owner_auth_sse_reservations(reservation_id, session_digest, session_revision, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (reservation_id, digest, int(session["revision"]), now),
                )
                # Opening a stream never extends session lifetime.  A stale
                # or revoked stream therefore cannot turn background traffic
                # into a session refresh; normal authenticated requests alone
                # may touch the session.
                return SseReservation(reservation_id, int(session["revision"]))
        finally:
            connection.close()

    def release_sse(self, reservation_id: str) -> None:
        """Release only the exact stream lease; repeat disconnects are safe."""

        if not isinstance(reservation_id, str) or not 22 <= len(reservation_id) <= 128:
            raise OwnerAuthError("invalid")
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                connection.execute(
                    "DELETE FROM mentat_owner_auth_sse_reservations WHERE reservation_id = ?", (reservation_id,)
                )
        finally:
            connection.close()

    def authenticate_sse(self, cookie_value: str) -> SseReservation:
        """Compatibility name for the reservation API; callers must release it."""

        return self.reserve_sse(cookie_value)

    def start_device_add(self, cookie_value: str, csrf_value: str, label: str) -> Ceremony:
        """Reserve a registration only from an exact, recently reauthenticated session."""

        _label(label)
        now = self._clock()
        digest = _digest(_token_bytes(cookie_value, 32))
        if not self._admit_durable("security_management", digest, SECURITY_MANAGEMENT_LIMIT):
            raise OwnerAuthError("limited")
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                self._cleanup(connection, now)
                session = connection.execute("SELECT * FROM mentat_owner_auth_sessions WHERE session_digest = ?", (digest,)).fetchone()
                if session is None or session["state"] != "active" or not self._fresh_reauthentication(session, now) or not hmac.compare_digest(bytes(session["csrf_digest"]), _digest(_token_bytes(csrf_value, 32))):
                    raise OwnerAuthError("invalid")
                return self._reserve_ceremony(connection, purpose="device_add", challenge=secrets.token_bytes(32), session=session)
        finally:
            connection.close()

    def revoke_device(self, cookie_value: str, csrf_value: str, device_id: str, expected_revision: int) -> None:
        """Revoke one exact device without ever removing the final recovery path."""

        if not isinstance(device_id, str) or not 22 <= len(device_id) <= 128 or type(expected_revision) is not int or expected_revision < 1:
            raise OwnerAuthError("invalid")
        now = self._clock()
        digest = _digest(_token_bytes(cookie_value, 32))
        if not self._admit_durable("security_management", digest, SECURITY_MANAGEMENT_LIMIT):
            raise OwnerAuthError("limited")
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                self._cleanup(connection, now)
                session = connection.execute("SELECT * FROM mentat_owner_auth_sessions WHERE session_digest = ?", (digest,)).fetchone()
                target = connection.execute("SELECT * FROM mentat_owner_auth_credentials WHERE device_id = ?", (device_id,)).fetchone()
                if session is None or session["state"] != "active" or not self._fresh_reauthentication(session, now) or not hmac.compare_digest(bytes(session["csrf_digest"]), _digest(_token_bytes(csrf_value, 32))) or target is None or target["state"] != "active" or int(target["revision"]) != expected_revision:
                    raise OwnerAuthError("invalid")
                active_credentials = int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials WHERE state = 'active'").fetchone()[0])
                active_recovery = int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state = 'active'").fetchone()[0])
                if active_credentials <= 1 and active_recovery == 0:
                    raise OwnerAuthError("invalid")
                connection.execute("UPDATE mentat_owner_auth_credentials SET state = 'revoked', revoked_at = ?, revision = revision + 1 WHERE device_id = ? AND state = 'active'", (now, device_id))
                connection.execute("UPDATE mentat_owner_auth_sessions SET state = 'revoked', revoked_at = ?, revision = revision + 1 WHERE device_id = ? AND state = 'active'", (now, device_id))
                self._audit(connection, "credential_revoked", "credential", _digest(device_id.encode("ascii")), now)
        finally:
            connection.close()

    def sign_out_all(self, cookie_value: str, csrf_value: str) -> None:
        """Revoke every live browser session, including the calling session."""

        digest = _digest(_token_bytes(cookie_value, 32))
        if not self._admit_durable("security_management", digest, SECURITY_MANAGEMENT_LIMIT):
            raise OwnerAuthError("limited")
        now = self._clock()
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                self._cleanup(connection, now)
                session = connection.execute("SELECT * FROM mentat_owner_auth_sessions WHERE session_digest = ?", (digest,)).fetchone()
                if session is None or session["state"] != "active" or not hmac.compare_digest(bytes(session["csrf_digest"]), _digest(_token_bytes(csrf_value, 32))):
                    raise OwnerAuthError("invalid")
                connection.execute("UPDATE mentat_owner_auth_sessions SET state = 'revoked', revoked_at = ?, revision = revision + 1 WHERE state = 'active'", (now,))
                self._audit(connection, "sessions_signed_out", "owner", None, now)
        finally:
            connection.close()

    def rotate_recovery_codes(self, cookie_value: str, csrf_value: str) -> tuple[str, ...]:
        """Replace every recovery code only after a distinct fresh reauth."""

        digest = _digest(_token_bytes(cookie_value, 32))
        if not self._admit_durable("security_management", digest, SECURITY_MANAGEMENT_LIMIT):
            raise OwnerAuthError("limited")
        now = self._clock()
        connection = self._open()
        try:
            with transaction(connection, immediate=True):
                self._cleanup(connection, now)
                session = connection.execute("SELECT * FROM mentat_owner_auth_sessions WHERE session_digest = ?", (digest,)).fetchone()
                if session is None or session["state"] != "active" or not self._fresh_reauthentication(session, now) or not hmac.compare_digest(bytes(session["csrf_digest"]), _digest(_token_bytes(csrf_value, 32))):
                    raise OwnerAuthError("invalid")
                state = self._state(connection)
                if state["state"] != "active":
                    raise OwnerAuthError("invalid")
                connection.execute("UPDATE mentat_owner_auth_ceremonies SET state = 'cancelled', consumed_at = ? WHERE purpose = 'recovery' AND state = 'pending'", (now,))
                connection.execute("UPDATE mentat_owner_auth_recovery_codes SET state = 'revoked', reserved_ceremony_id = NULL, updated_at = ? WHERE state IN ('active', 'reserved')", (now,))
                generation = int(connection.execute("SELECT COALESCE(MAX(generation), 0) FROM mentat_owner_auth_recovery_codes").fetchone()[0]) + 1
                codes = self._new_recovery_codes(connection, generation, now)
                self._audit(connection, "recovery_rotated", "owner", None, now)
                return codes
        finally:
            connection.close()


def bootstrap_owner_auth(data_dir: Path, origin: str) -> BootstrapGrant:
    """CLI-only bootstrap entry point; the returned code is terminal-only."""
    return OwnerAuthAuthority(data_dir).open_bootstrap(origin)


def validate_owner_auth_connection(connection: sqlite3.Connection) -> None:
    """Validate the bounded owner-auth graph while inspecting a private backup."""

    try:
        states = connection.execute("SELECT state, user_handle, canonical_origin, rp_id, bootstrap_verifier, bootstrap_user_handle, bootstrap_expires_at FROM mentat_owner_auth_state").fetchall()
        if len(states) != 1:
            raise ValueError
        state, user_handle, origin, rp_id, verifier, bootstrap_user_handle, expires = states[0]
        if state not in {"unbootstrapped", "bootstrap_open", "active"}:
            raise ValueError
        if state == "active" and (not isinstance(user_handle, bytes) or len(user_handle) != 32 or not isinstance(origin, str) or not isinstance(rp_id, str) or verifier is not None or bootstrap_user_handle is not None or expires is not None):
            raise ValueError
        if state == "bootstrap_open" and (user_handle is not None or not isinstance(verifier, str) or not verifier.startswith(_PHC_PREFIX) or not isinstance(bootstrap_user_handle, bytes) or len(bootstrap_user_handle) != 32 or expires is None):
            raise ValueError
        if state == "unbootstrapped" and any(value is not None for value in (user_handle, origin, rp_id, verifier, bootstrap_user_handle, expires)):
            raise ValueError
        if int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials WHERE state = 'active'").fetchone()[0]) > 128:
            raise ValueError
        if int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_ceremonies WHERE state = 'pending'").fetchone()[0]) > MAX_CEREMONIES:
            raise ValueError
        if int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_ceremonies WHERE state = 'pending' AND purpose IN ('bootstrap', 'authentication', 'recovery')").fetchone()[0]) > MAX_UNAUTH_CEREMONIES:
            raise ValueError
        if int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_ceremonies WHERE state NOT IN ('pending', 'consumed')").fetchone()[0]) > MAX_TERMINAL_CEREMONIES:
            raise ValueError
        sse_overflow = connection.execute(
            "SELECT 1 FROM mentat_owner_auth_sse_reservations GROUP BY session_digest HAVING COUNT(*) > ? LIMIT 1",
            (MAX_SSE_STREAMS,),
        ).fetchone()
        if sse_overflow is not None:
            raise ValueError
        if int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state = 'active'").fetchone()[0]) > RECOVERY_CODE_COUNT:
            raise ValueError
        if int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_audit").fetchone()[0]) > MAX_AUDIT_ROWS:
            raise ValueError
        if int(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_rejection_audit").fetchone()[0]) > MAX_AUDIT_ROWS:
            raise ValueError
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise OwnerAuthError("invalid") from exc


def sanitize_after_restore(connection: sqlite3.Connection, *, now: float | None = None) -> None:
    """Invalidate only live grants after a snapshot restore, never credentials/codes."""

    # Restored terminal sessions remain retained for the same fixed grace as
    # ordinary revocations.  Zero would make the first startup collector drop
    # all forensic/reconciliation evidence immediately.
    now = time.time() if now is None else now
    try:
        state = connection.execute("SELECT state FROM mentat_owner_auth_state WHERE singleton = 1").fetchone()
        if state is None:
            raise OwnerAuthError("invalid")
        if state[0] == "bootstrap_open":
            connection.execute("UPDATE mentat_owner_auth_state SET state = 'unbootstrapped', canonical_origin = NULL, rp_id = NULL, bootstrap_verifier = NULL, bootstrap_user_handle = NULL, bootstrap_expires_at = NULL, revision = revision + 1, updated_at = ? WHERE singleton = 1", (now,))
        connection.execute("UPDATE mentat_owner_auth_sessions SET state = 'revoked', revoked_at = ?, revision = revision + 1 WHERE state = 'active'", (now,))
        connection.execute("DELETE FROM mentat_owner_auth_sse_reservations")
        connection.execute("UPDATE mentat_owner_auth_ceremonies SET state = 'cancelled', consumed_at = ? WHERE state = 'pending'", (now,))
        connection.execute("UPDATE mentat_owner_auth_recovery_codes SET state = 'active', reserved_ceremony_id = NULL, updated_at = ? WHERE state = 'reserved'", (now,))
        connection.execute("INSERT INTO mentat_owner_auth_notices(notice, created_at) SELECT 'restore_invalidated_sessions', ? WHERE NOT EXISTS (SELECT 1 FROM mentat_owner_auth_notices WHERE notice = 'restore_invalidated_sessions')", (now,))
        connection.execute("INSERT INTO mentat_owner_auth_notices(notice, created_at) SELECT 'restore_snapshot_credentials_restored', ? WHERE NOT EXISTS (SELECT 1 FROM mentat_owner_auth_notices WHERE notice = 'restore_snapshot_credentials_restored')", (now,))
        connection.execute("INSERT INTO mentat_owner_auth_audit(event, subject_kind, subject_digest, occurred_at) SELECT 'restore_sanitized', 'owner', NULL, ? WHERE NOT EXISTS (SELECT 1 FROM mentat_owner_auth_audit WHERE event = 'restore_sanitized')", (now,))
        connection.execute("DELETE FROM mentat_owner_auth_audit WHERE id NOT IN (SELECT id FROM mentat_owner_auth_audit ORDER BY id DESC LIMIT ?)", (MAX_AUDIT_ROWS,))
    except sqlite3.Error as exc:
        raise OwnerAuthError("invalid") from exc


def cleanup_owner_auth_at_startup(data_dir: Path, *, clock: Callable[[], float] = time.time) -> None:
    """Commit expiry cleanup before either local dashboard publishes readiness."""

    now = clock()
    with private_state_lock(Path(data_dir)):
        connection = connect(Path(data_dir))
        connection.row_factory = sqlite3.Row
        try:
            with transaction(connection, immediate=True):
                OwnerAuthAuthority(data_dir, clock=clock)._cleanup(
                    connection,
                    now,
                    clear_sse=True,
                    terminalize_consumed_at_startup=True,
                )
        except sqlite3.Error as exc:
            raise OwnerAuthError("invalid") from exc
        finally:
            connection.close()
