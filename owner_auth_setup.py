"""Foreground host-admin owner setup; private grants never grant a session."""

from __future__ import annotations

import os
import secrets
import time
import hashlib
import hmac
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from data_layout import _secure_directory
from json_store import read_json, write_json_atomic
from private_state import (
    PrivateStateError, _pid_record_active, connection_server_reservation_path,
    mentat_server_active, private_state_lock,
)
from mentat_db import transaction
from owner_auth import OwnerAuthAuthority, OwnerAuthError, google_principal_digest, validate_owner_auth_connection
from owner_auth_google import GOOGLE_ISSUER, VerifiedGoogleIdentity, _client_id, _secret, authorization_url, new_login_secrets
from owner_auth_google_transactions import LoginStart, _digest_secret, discard_transactions
from owner_auth_google_transport import GoogleOidcTransport
from owner_auth_webauthn import canonical_origin

SETUP_SECONDS = 600


@dataclass(frozen=True, repr=False)
class SetupReservation:
    nonce: str
    pid: int
    expires_at: float

    def _record(self) -> dict:
        return dict(schema_version=1, purpose='owner_setup', nonce=self.nonce,
                    pid=self.pid, expires_at=self.expires_at)


def reserve_owner_setup(data_root: Path, *, clock=time.time) -> SetupReservation:
    """Exclude normal startup using its shared, locked lifetime reservation."""
    root = Path(data_root)
    with private_state_lock(root):
        if mentat_server_active(root):
            raise PrivateStateError('Mentat server or setup is already active')
        if not _secure_directory(root / 'runtime'):
            raise PrivateStateError('Mentat runtime directory is unsafe')
        reservation = SetupReservation(secrets.token_urlsafe(32), os.getpid(), clock() + SETUP_SECONDS)
        write_json_atomic(connection_server_reservation_path(root), reservation._record(), mode=0o600, maximum_bytes=1024)
        return reservation


def _read_owned(root: Path, reservation: SetupReservation) -> bool:
    if not isinstance(reservation, SetupReservation) or reservation.pid != os.getpid():
        return False
    record = read_json(connection_server_reservation_path(root), None, maximum_bytes=1024,
                       required_mode=0o600, expected_type=dict, require_existing=True)
    return record == reservation._record()


def assert_owner_setup(data_root: Path, reservation: SetupReservation, *, clock=time.time) -> None:
    """Recheck exact live ownership under the mutation lock before a transition."""
    root = Path(data_root)
    with private_state_lock(root):
        try:
            if not _read_owned(root, reservation) or clock() >= reservation.expires_at or _pid_record_active(root / 'runtime' / 'server-state.json') is True:
                raise PrivateStateError('Owner setup reservation unavailable')
        except (OSError, ValueError, TypeError):
            raise PrivateStateError('Owner setup reservation unavailable') from None


def release_owner_setup(data_root: Path, reservation: SetupReservation) -> None:
    """Release only this exact ceremony, including after its deadline expires."""
    root = Path(data_root)
    with private_state_lock(root):
        try:
            if _read_owned(root, reservation):
                connection_server_reservation_path(root).unlink()
        except (OSError, ValueError, TypeError):
            return


@dataclass(frozen=True, repr=False)
class OwnerCandidate:
    candidate_id: str
    revision: int
    email: str
    purpose: str
    expires_at: float


@dataclass(frozen=True, repr=False)
class OwnerSetupResult:
    recovery_codes: tuple[str, ...]
    backup_name: str


def _authority_snapshot(connection) -> bytes:
    rows = []
    for table in ('mentat_owner_auth_state', 'mentat_owner_google_configuration', 'mentat_owner_google_principal'):
        rows.append([dict(row) for row in connection.execute(f'SELECT * FROM {table} ORDER BY singleton')])
    raw = json.dumps(rows, sort_keys=True, separators=(',', ':'), allow_nan=False,
                     default=lambda value: value.hex() if isinstance(value, bytes) else None)
    return hashlib.sha256(raw.encode()).digest()


class OwnerSetupCeremony:
    """One bounded process-owned intent. Restart discards proof and candidate.

    The CLI owns this object and its reservation. The setup gateway may call
    only begin_browser and verify_browser; only the host CLI may call confirm.
    No identity, owner choice, confirmation or recovery code crosses to Node.
    """

    def __init__(self, authority: OwnerAuthAuthority, *, purpose: str, client_id: str,
                 origin: str, client_secret: str, _transport=None, _backup=None):
        if purpose not in {'enroll', 'convert', 'recover'}:
            raise OwnerAuthError('invalid')
        self._client_id = _client_id(client_id)
        self._origin, self._host = canonical_origin(origin)
        if '.' not in self._host or not any(character.isalpha() for character in self._host.rsplit('.', 1)[-1]):
            raise OwnerAuthError('invalid')
        if not isinstance(client_secret, str) or not 1 <= len(client_secret) <= 4096 or any(ord(value) < 33 or ord(value) > 126 for value in client_secret):
            raise OwnerAuthError('invalid')
        self._authority = authority
        self._root = authority._data_dir
        self._clock = authority._clock
        self._purpose = purpose
        self._secret = client_secret
        self._transport = GoogleOidcTransport() if _transport is None else _transport
        if _backup is None:
            from data_backup_restore import create_durable_backup
            _backup = create_durable_backup
        self._backup = _backup
        self._lock = threading.RLock()
        self._phase = 'opening'
        self._attempts = 0
        self._login = None
        self._identity = None
        self._candidate = None
        self._grant = _secret(secrets.token_urlsafe(32))
        self._grant_digest = _digest_secret(self._grant)
        self._reservation = reserve_owner_setup(self._root, clock=self._clock)
        try:
            with private_state_lock(self._root):
                connection = authority._open()
                try:
                    validate_owner_auth_connection(connection)
                    state = authority._state(connection)
                    if not (
                        purpose == 'enroll' and state['state'] == 'unbootstrapped'
                        or purpose == 'convert' and state['state'] == 'active' and state['auth_method'] == 'passkey'
                        or purpose == 'recover' and state['state'] == 'active' and state['auth_method'] == 'google'
                    ):
                        raise OwnerAuthError('unavailable')
                    self._snapshot = _authority_snapshot(connection)
                finally:
                    connection.close()
            self._phase = 'ready'
        except BaseException:
            release_owner_setup(self._root, self._reservation)
            self._secret = self._grant = ''
            raise

    def take_terminal_grant(self) -> str:
        with self._lock:
            self._check()
            value, self._grant = self._grant, ''
            if not value:
                raise OwnerAuthError('invalid')
            return value

    def _check(self) -> None:
        if self._phase in {'closed', 'failed', 'committed'}:
            raise OwnerAuthError('unavailable')
        assert_owner_setup(self._root, self._reservation, clock=self._clock)

    def begin_browser(self, grant: str) -> LoginStart:
        with self._lock:
            self._check()
            if self._phase != 'ready' or self._attempts >= 5:
                raise OwnerAuthError('invalid')
            self._attempts += 1
            try:
                if not hmac.compare_digest(_digest_secret(grant), self._grant_digest):
                    raise OwnerAuthError('invalid')
            except (ValueError, TypeError):
                raise OwnerAuthError('invalid') from None
            self._login = new_login_secrets()
            self._phase = 'pending'
            self._grant_digest = b''
            return LoginStart(authorization_url(client_id=self._client_id, origin=self._origin, login=self._login),
                              self._login.browser_binding, self._reservation.expires_at)

    def verify_browser(self, *, state: str, browser_binding: str, code: str) -> None:
        with self._lock:
            self._check()
            login = self._login
            if self._phase != 'pending' or login is None:
                raise OwnerAuthError('invalid')
            try:
                if not hmac.compare_digest(_digest_secret(state), _digest_secret(login.state)) or not hmac.compare_digest(_digest_secret(browser_binding), _digest_secret(login.browser_binding)):
                    raise OwnerAuthError('invalid')
            except (ValueError, TypeError):
                raise OwnerAuthError('invalid') from None
            self._phase = 'exchanging'
            self._login = None
        try:
            identity = self._transport.authenticate_code(client_id=self._client_id, origin=self._origin,
                client_secret=self._secret, code=code, code_verifier=login.code_verifier, expected_nonce=login.nonce)
            if not isinstance(identity, VerifiedGoogleIdentity) or identity.issuer != GOOGLE_ISSUER:
                raise OwnerAuthError('invalid')
            with self._lock:
                self._check()
                if self._phase != 'exchanging':
                    raise OwnerAuthError('invalid')
                self._identity = identity
                self._candidate = OwnerCandidate(secrets.token_urlsafe(24), 1, identity.email, self._purpose, self._reservation.expires_at)
                self._phase = 'candidate'
        except Exception:
            with self._lock:
                if self._phase != 'closed':
                    self._phase = 'failed'
            raise OwnerAuthError('invalid') from None
        finally:
            login = None
            code = ''

    def terminal_candidate(self) -> OwnerCandidate:
        with self._lock:
            self._check()
            if self._phase != 'candidate':
                raise OwnerAuthError('unavailable')
            return self._candidate

    def terminal_status(self) -> str:
        with self._lock:
            if self._clock() >= self._reservation.expires_at:
                return 'expired'
            return self._phase

    def confirm(self, *, candidate_id: str, revision: int) -> OwnerSetupResult:
        with self._lock, private_state_lock(self._root):
            self._check()
            candidate = self._candidate
            if self._phase != 'candidate' or not isinstance(candidate_id, str) or type(revision) is not int or candidate.candidate_id != candidate_id or candidate.revision != revision:
                raise OwnerAuthError('invalid')
            connection = self._authority._open()
            try:
                if not hmac.compare_digest(_authority_snapshot(connection), self._snapshot):
                    raise OwnerAuthError('changed')
                backup = self._backup(self._root)
                if backup.status not in {'created', 'existing'} or not backup.backup_name:
                    raise OwnerAuthError('backup_required')
                with transaction(connection, immediate=True):
                    self._check()
                    if not hmac.compare_digest(_authority_snapshot(connection), self._snapshot):
                        raise OwnerAuthError('changed')
                    now = self._clock()
                    state = self._authority._state(connection)
                    generation = int(state['owner_generation']) + 1
                    cfg = connection.execute('SELECT revision FROM mentat_owner_google_configuration WHERE singleton=1').fetchone()
                    cfg_revision = 1 if cfg is None else int(cfg[0]) + 1
                    recovery_generation = int(connection.execute('SELECT COALESCE(MAX(generation),0) FROM mentat_owner_auth_recovery_codes').fetchone()[0]) + 1
                    connection.execute("UPDATE mentat_owner_auth_sessions SET state='revoked',revoked_at=?,revision=revision+1 WHERE state='active'", (now,))
                    connection.execute("UPDATE mentat_owner_auth_credentials SET state='revoked',revoked_at=?,revision=revision+1 WHERE state='active'", (now,))
                    connection.execute("UPDATE mentat_owner_auth_ceremonies SET state='cancelled',consumed_at=? WHERE state IN ('pending','consumed')", (now,))
                    connection.execute("UPDATE mentat_owner_auth_recovery_codes SET state='revoked',reserved_ceremony_id=NULL,updated_at=? WHERE state IN ('active','reserved')", (now,))
                    discard_transactions(connection)
                    connection.execute('DELETE FROM mentat_owner_auth_sse_reservations')
                    connection.execute("UPDATE mentat_owner_auth_state SET state='active',user_handle=?,canonical_origin=?,rp_id=?,bootstrap_verifier=NULL,bootstrap_user_handle=NULL,bootstrap_expires_at=NULL,configuration_revision=configuration_revision+1,revision=revision+1,updated_at=?,auth_method='google',owner_generation=? WHERE singleton=1", (secrets.token_bytes(32), self._origin, self._host, now, generation))
                    connection.execute("INSERT INTO mentat_owner_google_configuration VALUES(1,?,?,'environment',0,?) ON CONFLICT(singleton) DO UPDATE SET client_id=excluded.client_id,canonical_origin=excluded.canonical_origin,credential_source=excluded.credential_source,requires_reconciliation=0,revision=excluded.revision", (self._client_id, self._origin, cfg_revision))
                    identity = self._identity
                    connection.execute('INSERT INTO mentat_owner_google_principal VALUES(1,?,?,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET issuer=excluded.issuer,subject=excluded.subject,email=excluded.email,principal_digest=excluded.principal_digest,owner_generation=excluded.owner_generation,configuration_revision=excluded.configuration_revision', (identity.issuer, identity.subject, identity.email, google_principal_digest(identity.issuer, identity.subject), generation, cfg_revision))
                    codes = self._authority._new_recovery_codes(connection, recovery_generation, now)
                    self._authority._cleanup(connection, now)
                    self._authority._audit(connection, 'recovery_completed' if self._purpose == 'recover' else 'bootstrap_completed', 'owner', None, now)
                    validate_owner_auth_connection(connection)
                    self._check()
                self._phase = 'committed'
                self._identity = self._candidate = None
                self._secret = ''
                return OwnerSetupResult(codes, backup.backup_name)
            except (ValueError, TypeError, sqlite3.Error):
                raise OwnerAuthError('invalid') from None
            finally:
                connection.close()

    def close(self) -> bool:
        """Caller must first stop/reap the setup gateway, then close this owner."""
        with self._lock:
            self._phase = 'closed'
            self._secret = self._grant = ''
            self._login = self._identity = self._candidate = None
        stopped = self._transport.close()
        if stopped:
            release_owner_setup(self._root, self._reservation)
        return stopped
