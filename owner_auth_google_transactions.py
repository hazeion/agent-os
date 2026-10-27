"""Private ordinary-login attempts. No routes, enrollment or session issuance."""

from __future__ import annotations

import hashlib
import hmac
import math
import sqlite3
from dataclasses import dataclass

from mentat_db import transaction
from owner_auth import AUTHENTICATION_START_LIMIT, OwnerAuthAuthority, OwnerAuthError, _google_principal, _id, google_principal_digest
from owner_auth_google import GOOGLE_ISSUER, VerifiedGoogleIdentity, _secret, authorization_url, new_login_secrets
from owner_auth_google_transport import GoogleOidcTransport

LIFETIME_SECONDS = 300
MAX_PENDING = 16
MAX_TERMINAL = 64


@dataclass(frozen=True, repr=False)
class LoginStart:
    authorization_url: str
    browser_binding: str
    expires_at: float


@dataclass(frozen=True, repr=False)
class LoginReceipt:
    """Private lookup reference only. Not a session or reusable identity proof."""
    transaction_id: str


def _digest_secret(value: str) -> bytes:
    return hashlib.sha256(_secret(value).encode("ascii")).digest()


def _snapshot(connection: sqlite3.Connection) -> dict:
    owner = connection.execute("SELECT * FROM mentat_owner_auth_state WHERE singleton=1").fetchone()
    if owner is None or owner["auth_method"] != "google":
        raise OwnerAuthError("invalid")
    principal = _google_principal(connection, owner)
    configuration = connection.execute("SELECT * FROM mentat_owner_google_configuration WHERE singleton=1").fetchone()
    if configuration["requires_reconciliation"]:
        raise OwnerAuthError("invalid")
    return dict(owner_generation=owner["owner_generation"], configuration_revision=configuration["revision"],
                principal_digest=bytes(principal["principal_digest"]), client_id=configuration["client_id"],
                canonical_origin=configuration["canonical_origin"])


def _matches(row, snapshot: dict) -> bool:
    return all(hmac.compare_digest(row[key], value) if isinstance(value, bytes) else row[key] == value
               for key, value in snapshot.items())


def _cleanup(connection: sqlite3.Connection, now: float) -> None:
    connection.execute("UPDATE mentat_owner_google_transactions SET state='cancelled',nonce=NULL,code_verifier=NULL,terminal_at=? WHERE state='pending' AND expires_at<=?", (now, now))
    connection.execute("DELETE FROM mentat_owner_google_transactions WHERE transaction_id IN (SELECT transaction_id FROM mentat_owner_google_transactions WHERE state!='pending' ORDER BY terminal_at DESC,transaction_id DESC LIMIT -1 OFFSET ?)", (MAX_TERMINAL,))


def discard_transactions(connection: sqlite3.Connection) -> None:
    """Called only for startup/restore or filtering the private snapshot copy."""
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mentat_owner_google_transactions'").fetchone():
        connection.execute("DELETE FROM mentat_owner_google_transactions")


def validate_transactions(connection: sqlite3.Connection) -> None:
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mentat_owner_google_transactions'").fetchone():
        return  # Historical schema; exact graph validation belongs to the caller.
    previous = connection.row_factory
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("SELECT * FROM mentat_owner_google_transactions LIMIT ?", (MAX_PENDING + MAX_TERMINAL + 1,)).fetchall()
        pending = sum(row["state"] == "pending" for row in rows)
        if pending > MAX_PENDING or len(rows) - pending > MAX_TERMINAL:
            raise ValueError("invalid")
        for row in rows:
            for field in ("created_at", "expires_at"):
                if not isinstance(row[field], (int, float)) or not math.isfinite(row[field]) or row[field] < 0:
                    raise ValueError("invalid")
            if row["state"] == "pending":
                _secret(row["nonce"]); _secret(row["code_verifier"])
            elif not isinstance(row["terminal_at"], (int, float)) or not math.isfinite(row["terminal_at"]):
                raise ValueError("invalid")
    finally:
        connection.row_factory = previous


class GoogleLoginTransactions:
    def __init__(self, authority: OwnerAuthAuthority, *, _transport=None):
        self._authority = authority
        self._transport = GoogleOidcTransport() if _transport is None else _transport

    def begin(self) -> LoginStart:
        if not self._authority._admit_durable("authentication_start", b"\0" * 32, AUTHENTICATION_START_LIMIT):
            raise OwnerAuthError("limited")
        connection = self._authority._open()
        try:
            with transaction(connection, immediate=True):
                now = self._authority._clock()
                _cleanup(connection, now)
                snapshot = _snapshot(connection)
                if connection.execute("SELECT COUNT(*) FROM mentat_owner_google_transactions WHERE state='pending'").fetchone()[0] >= MAX_PENDING:
                    raise OwnerAuthError("limited")
                login = new_login_secrets()
                url = authorization_url(client_id=snapshot["client_id"], origin=snapshot["canonical_origin"], login=login)
                connection.execute("INSERT INTO mentat_owner_google_transactions(transaction_id,state_digest,browser_digest,owner_generation,configuration_revision,principal_digest,client_id,canonical_origin,nonce,code_verifier,state,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,'pending',?,?)",
                    (_id(), _digest_secret(login.state), _digest_secret(login.browser_binding), snapshot["owner_generation"], snapshot["configuration_revision"], snapshot["principal_digest"], snapshot["client_id"], snapshot["canonical_origin"], login.nonce, login.code_verifier, now, now + LIFETIME_SECONDS))
                return LoginStart(url, login.browser_binding, now + LIFETIME_SECONDS)
        except (ValueError, TypeError, sqlite3.Error):
            raise OwnerAuthError("invalid") from None
        finally:
            connection.close()

    def verify_callback(self, *, state: str, browser_binding: str, code: str, client_secret: str) -> LoginReceipt:
        """Consume first, exchange once, then record exact-owner verification.

        Future session issuance must atomically claim this receipt and recheck
        the browser binding and complete current owner/configuration snapshot.
        Neither this object nor a provider identity grants session authority.
        """
        connection = None
        attempt = None
        consumed = False
        try:
            state_digest, browser_digest = _digest_secret(state), _digest_secret(browser_binding)
            connection = self._authority._open()
            with transaction(connection, immediate=True):
                now = self._authority._clock()
                row = connection.execute("SELECT * FROM mentat_owner_google_transactions WHERE state_digest=?", (state_digest,)).fetchone()
                if row is None or row["state"] != "pending" or row["expires_at"] <= now or not hmac.compare_digest(bytes(row["browser_digest"]), browser_digest) or not _matches(row, _snapshot(connection)):
                    raise OwnerAuthError("invalid")
                attempt = dict(row)
                connection.execute("UPDATE mentat_owner_google_transactions SET state='consumed',nonce=NULL,code_verifier=NULL,terminal_at=? WHERE transaction_id=?", (now, row["transaction_id"]))
                _cleanup(connection, now)
            consumed = True
            connection.close()
            connection = None
            # A crash from here onward cannot reopen or replay the code.
            evidence = self._transport.authenticate_code(client_id=attempt["client_id"], origin=attempt["canonical_origin"], code=code, code_verifier=attempt["code_verifier"], client_secret=client_secret, expected_nonce=attempt["nonce"])
            attempt["code_verifier"] = attempt["nonce"] = None
            if not isinstance(evidence, VerifiedGoogleIdentity) or evidence.issuer != GOOGLE_ISSUER or not hmac.compare_digest(google_principal_digest(evidence.issuer, evidence.subject), attempt["principal_digest"]):
                raise OwnerAuthError("invalid")
            connection = self._authority._open()
            with transaction(connection, immediate=True):
                now = self._authority._clock()
                row = connection.execute("SELECT * FROM mentat_owner_google_transactions WHERE transaction_id=?", (attempt["transaction_id"],)).fetchone()
                if row is None or row["state"] != "consumed" or row["expires_at"] <= now or not _matches(row, _snapshot(connection)) or not _matches(attempt, _snapshot(connection)):
                    raise OwnerAuthError("invalid")
                connection.execute("UPDATE mentat_owner_google_transactions SET state='verified',terminal_at=? WHERE transaction_id=?", (now, row["transaction_id"]))
                self._authority._audit(connection, "authentication_succeeded", "owner", None, now)
                return LoginReceipt(row["transaction_id"])
        except Exception:
            # Consumption is already committed; failures never re-enable it.
            if connection is not None:
                connection.close()
                connection = None
            if consumed and attempt is not None:
                self._fail(attempt["transaction_id"])
            raise OwnerAuthError("invalid") from None
        finally:
            code = client_secret = ""
            if attempt is not None:
                attempt["code_verifier"] = attempt["nonce"] = None
            if connection is not None:
                connection.close()

    def _fail(self, transaction_id: str) -> None:
        connection = None
        try:
            connection = self._authority._open()
            with transaction(connection, immediate=True):
                now = self._authority._clock()
                changed = connection.execute("UPDATE mentat_owner_google_transactions SET state='failed',terminal_at=? WHERE transaction_id=? AND state='consumed'", (now, transaction_id)).rowcount
                if changed:
                    self._authority._audit(connection, "authentication_failed", "owner", None, now)
                _cleanup(connection, now)
        except Exception:
            pass  # The already committed consumed marker is fail-closed.
        finally:
            if connection is not None:
                connection.close()
