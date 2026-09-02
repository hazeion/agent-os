"""Durable, exact-idempotency ledger for Hermes delegation actions.

This module deliberately owns only the receipt ledger.  It does not read a
Task or a Hermes board, and its table has no Task foreign key: a receipt must
remain available to reconcile an ambiguous remote action after a task is
deleted, restored, or otherwise changes locally.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import math
import re
import sqlite3
import time
from typing import Any, Iterator

from mentat_db import SCHEMA_VERSION as DATABASE_SCHEMA_VERSION, schema_signature_state


IDEMPOTENCY_RETENTION_SECONDS = 30 * 24 * 60 * 60
MAX_PRUNE_PER_MUTATION = 256

_TABLE = "mentat_task_delegation_action_receipts"
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ACTIONS = frozenset(
    {"delegate", "accept", "reply", "retry", "stop", "request_revision", "mark_blocked"}
)
_TERMINAL = frozenset({"accepted", "rejected"})
_UNCERTAIN = frozenset({"unknown", "partial"})
_ALL_STATES = frozenset({"reserved", "submitting"}) | _TERMINAL | _UNCERTAIN
_TRANSITIONS = {
    "reserved": frozenset({"submitting", "rejected", "unknown", "partial"}),
    "submitting": frozenset({"accepted", "rejected", "unknown", "partial"}),
    "unknown": frozenset({"accepted", "rejected", "partial"}),
    "partial": frozenset({"accepted", "rejected", "unknown"}),
    "accepted": frozenset(),
    "rejected": frozenset(),
}


class DelegationReceiptError(RuntimeError):
    """A bounded durable delegation receipt failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class DelegationReceiptValidationError(DelegationReceiptError):
    pass


class DelegationReceiptConflict(DelegationReceiptError):
    pass


class DelegationReceiptUnavailable(DelegationReceiptError):
    pass


@dataclass(frozen=True)
class DelegationActionReceipt:
    key_digest: str
    request_digest: str
    task_id: str
    task_revision: int
    action: str
    confirmation_digest: str
    delegation_binding_digest: str
    remote_revision_digest: str
    state: str
    result_task_revision: int | None
    result_proof_digest: str | None
    created_at: str
    updated_at: str
    expires_at: float | None
    duplicate: bool = False


def idempotency_key_digest(value: Any) -> str:
    """Validate a browser idempotency key without persisting its raw value."""

    try:
        encoded = value.encode("utf-8")
    except (AttributeError, UnicodeEncodeError):
        encoded = b""
    if not 16 <= len(encoded) <= 256 or not isinstance(value, str) or "\x00" in value:
        raise DelegationReceiptValidationError("delegation_receipt.idempotency_key_invalid")
    return hashlib.sha256(encoded).hexdigest()


def _digest(value: Any, *, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DelegationReceiptValidationError(code)
    return value


def _task_id(value: Any) -> str:
    if not isinstance(value, str) or _TASK_ID.fullmatch(value) is None:
        raise DelegationReceiptValidationError("delegation_receipt.task_invalid")
    return value


def _revision(value: Any, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if type(value) is not int or value < 1:
        raise DelegationReceiptValidationError("delegation_receipt.revision_invalid")
    return value


def _timestamp(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise DelegationReceiptValidationError("delegation_receipt.timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DelegationReceiptValidationError("delegation_receipt.timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise DelegationReceiptValidationError("delegation_receipt.timestamp_invalid")
    return value


def _epoch(value: Any, *, code: str) -> float:
    if isinstance(value, bool):
        raise DelegationReceiptValidationError(code)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DelegationReceiptValidationError(code) from exc
    if not math.isfinite(result) or result <= 0:
        raise DelegationReceiptValidationError(code)
    return result


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DelegationActionReceiptRepository:
    """Transaction-capable repository for the current receipt rows.

    The caller may put receipt mutations in its own SQLite transaction.  When
    it does not, each mutating operation obtains a short ``BEGIN IMMEDIATE``
    transaction so an action key and per-task active receipt cannot race.
    """

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self._require_schema()

    def _require_schema(self) -> None:
        try:
            rows = self.connection.execute(f"PRAGMA table_info({_TABLE})").fetchall()
        except sqlite3.Error as exc:
            raise DelegationReceiptUnavailable("delegation_receipt.schema_unsupported") from exc
        required = {
            "key_digest", "request_digest", "task_id", "task_revision", "action",
            "confirmation_digest", "delegation_binding_digest", "remote_revision_digest",
            "state", "result_task_revision", "result_proof_digest", "created_at", "updated_at", "expires_at",
        }
        if {str(row[1]) for row in rows} != required:
            raise DelegationReceiptUnavailable("delegation_receipt.schema_unsupported")
        # A current database is not revalidated by ``connect()`` after its
        # migrations have already been applied.  This ledger's per-Task
        # partial unique index is the serialization boundary for an external
        # Hermes mutation, so accepting a merely column-compatible table
        # would allow two concurrent actions.  Require the complete current
        # database shape before touching any receipt.
        if (
            DATABASE_SCHEMA_VERSION != 22
            or schema_signature_state(self.connection, DATABASE_SCHEMA_VERSION)
            != "expected"
        ):
            raise DelegationReceiptUnavailable("delegation_receipt.schema_unsupported")

    @contextmanager
    def mutation(self) -> Iterator[None]:
        nested = self.connection.in_transaction
        if nested:
            self.connection.execute("SAVEPOINT mentat_task_delegation_receipt")
        else:
            self.connection.execute("BEGIN IMMEDIATE")
        try:
            self._require_schema()
            yield
        except Exception:
            if nested:
                self.connection.execute("ROLLBACK TO mentat_task_delegation_receipt")
                self.connection.execute("RELEASE mentat_task_delegation_receipt")
            else:
                self.connection.rollback()
            raise
        else:
            if nested:
                self.connection.execute("RELEASE mentat_task_delegation_receipt")
            else:
                self.connection.commit()

    @staticmethod
    def _record(row: sqlite3.Row, *, duplicate: bool = False) -> DelegationActionReceipt:
        try:
            record = DelegationActionReceipt(
                key_digest=_digest(row["key_digest"], code="delegation_receipt.corrupt"),
                request_digest=_digest(row["request_digest"], code="delegation_receipt.corrupt"),
                task_id=_task_id(row["task_id"]),
                task_revision=int(_revision(row["task_revision"])),
                action=str(row["action"]),
                confirmation_digest=_digest(row["confirmation_digest"], code="delegation_receipt.corrupt"),
                delegation_binding_digest=_digest(row["delegation_binding_digest"], code="delegation_receipt.corrupt"),
                remote_revision_digest=_digest(row["remote_revision_digest"], code="delegation_receipt.corrupt"),
                state=str(row["state"]),
                result_task_revision=_revision(row["result_task_revision"], nullable=True),
                result_proof_digest=(
                    None
                    if row["result_proof_digest"] is None
                    else _digest(
                        row["result_proof_digest"],
                        code="delegation_receipt.corrupt",
                    )
                ),
                created_at=_timestamp(row["created_at"]),
                updated_at=_timestamp(row["updated_at"]),
                expires_at=(None if row["expires_at"] is None else _epoch(row["expires_at"], code="delegation_receipt.corrupt")),
                duplicate=duplicate,
            )
            if (
                record.action not in _ACTIONS
                or record.state not in _ALL_STATES
                or (record.state in _TERMINAL) != (record.expires_at is not None)
                or (record.state in _UNCERTAIN and record.expires_at is not None)
                or (
                    record.state == "accepted"
                    and record.result_task_revision is None
                )
                or (
                    record.state == "accepted"
                    and record.result_proof_digest is None
                )
                or datetime.fromisoformat(record.created_at.replace("Z", "+00:00"))
                > datetime.fromisoformat(record.updated_at.replace("Z", "+00:00"))
            ):
                raise DelegationReceiptUnavailable("delegation_receipt.corrupt")
            return record
        except (KeyError, TypeError, ValueError, DelegationReceiptValidationError) as exc:
            raise DelegationReceiptUnavailable("delegation_receipt.corrupt") from exc

    def get(self, *, key_digest: str) -> DelegationActionReceipt | None:
        key = _digest(key_digest, code="delegation_receipt.key_invalid")
        row = self.connection.execute(
            f"SELECT * FROM {_TABLE} WHERE key_digest = ?", (key,)
        ).fetchone()
        return None if row is None else self._record(row)

    def reserve(
        self,
        *,
        key_digest: str,
        request_digest: str,
        task_id: str,
        task_revision: int,
        action: str,
        confirmation_digest: str,
        delegation_binding_digest: str,
        remote_revision_digest: str,
        now: str | None = None,
        epoch: float | None = None,
    ) -> DelegationActionReceipt:
        """Reserve one exact action, or return its identical durable replay."""

        key = _digest(key_digest, code="delegation_receipt.key_invalid")
        request = _digest(request_digest, code="delegation_receipt.request_invalid")
        task = _task_id(task_id)
        revision = _revision(task_revision)
        if action not in _ACTIONS:
            raise DelegationReceiptValidationError("delegation_receipt.action_invalid")
        confirmation = _digest(confirmation_digest, code="delegation_receipt.confirmation_invalid")
        binding = _digest(delegation_binding_digest, code="delegation_receipt.binding_invalid")
        remote = _digest(remote_revision_digest, code="delegation_receipt.remote_revision_invalid")
        occurred_at = _timestamp(now or _now_timestamp())
        prune_before = time.time() if epoch is None else _epoch(epoch, code="delegation_receipt.epoch_invalid")
        with self.mutation():
            self._prune_expired_in_transaction(prune_before)
            existing = self.connection.execute(
                f"SELECT * FROM {_TABLE} WHERE key_digest = ?", (key,)
            ).fetchone()
            if existing is not None:
                record = self._record(existing)
                if (
                    record.request_digest != request
                    or record.task_id != task
                    or record.task_revision != revision
                    or record.action != action
                    or record.confirmation_digest != confirmation
                    or record.delegation_binding_digest != binding
                    or record.remote_revision_digest != remote
                ):
                    raise DelegationReceiptConflict("delegation_receipt.idempotency_conflict")
                return replace(record, duplicate=True)
            try:
                self.connection.execute(
                    f"INSERT INTO {_TABLE} ("
                    "key_digest, request_digest, task_id, task_revision, action, "
                    "confirmation_digest, delegation_binding_digest, remote_revision_digest, "
                    "state, result_task_revision, result_proof_digest, created_at, updated_at, expires_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'reserved', NULL, NULL, ?, ?, NULL)",
                    (key, request, task, revision, action, confirmation, binding, remote, occurred_at, occurred_at),
                )
            except sqlite3.IntegrityError as exc:
                active = self.connection.execute(
                    f"SELECT key_digest FROM {_TABLE} WHERE task_id = ? "
                    "AND state IN ('reserved', 'submitting', 'unknown', 'partial') LIMIT 1",
                    (task,),
                ).fetchone()
                if active is not None:
                    raise DelegationReceiptConflict("delegation_receipt.action_active") from exc
                raise DelegationReceiptUnavailable("delegation_receipt.write_failed") from exc
            return DelegationActionReceipt(
                key_digest=key, request_digest=request, task_id=task, task_revision=revision,
                action=action, confirmation_digest=confirmation,
                delegation_binding_digest=binding, remote_revision_digest=remote,
                state="reserved", result_task_revision=None, created_at=occurred_at,
                result_proof_digest=None,
                updated_at=occurred_at, expires_at=None,
            )

    def stage_verified_result(
        self,
        *,
        key_digest: str,
        result_task_revision: int,
        result_proof_digest: str,
        now: str | None = None,
    ) -> DelegationActionReceipt:
        """Durably bind a successful effect before terminalizing its receipt."""

        key = _digest(key_digest, code="delegation_receipt.key_invalid")
        revision = _revision(result_task_revision)
        proof = _digest(result_proof_digest, code="delegation_receipt.result_proof_invalid")
        occurred_at = _timestamp(now or _now_timestamp())
        with self.mutation():
            row = self.connection.execute(
                f"SELECT * FROM {_TABLE} WHERE key_digest = ?", (key,)
            ).fetchone()
            if row is None:
                raise DelegationReceiptConflict("delegation_receipt.not_found")
            existing = self._record(row)
            if existing.state != "submitting":
                raise DelegationReceiptConflict("delegation_receipt.state_conflict")
            if (
                existing.result_task_revision is not None
                and (
                    existing.result_task_revision != revision
                    or existing.result_proof_digest != proof
                )
            ):
                raise DelegationReceiptConflict("delegation_receipt.result_conflict")
            changed = self.connection.execute(
                f"UPDATE {_TABLE} SET result_task_revision = ?, result_proof_digest = ?, updated_at = ? "
                "WHERE key_digest = ? AND state = 'submitting'",
                (revision, proof, occurred_at, key),
            ).rowcount
            if changed != 1:
                raise DelegationReceiptConflict("delegation_receipt.state_conflict")
            return replace(
                existing,
                result_task_revision=revision,
                result_proof_digest=proof,
                updated_at=occurred_at,
            )

    def mark_submitting(self, *, key_digest: str, now: str | None = None) -> DelegationActionReceipt:
        return self._transition(
            key_digest=key_digest, state="submitting", result_task_revision=None, now=now, epoch=None
        )

    def reject_unsubmitted(
        self,
        *,
        key_digest: str,
        now: str | None = None,
        epoch: float | None = None,
        retention_seconds: float = IDEMPOTENCY_RETENTION_SECONDS,
    ) -> DelegationActionReceipt:
        """Terminalize only a reservation which could not have reached Hermes."""

        key = _digest(key_digest, code="delegation_receipt.key_invalid")
        if (
            not isinstance(retention_seconds, (int, float))
            or isinstance(retention_seconds, bool)
            or retention_seconds <= 0
            or not math.isfinite(float(retention_seconds))
        ):
            raise DelegationReceiptValidationError(
                "delegation_receipt.retention_invalid"
            )
        occurred_at = _timestamp(now or _now_timestamp())
        effective_epoch = time.time() if epoch is None else _epoch(
            epoch, code="delegation_receipt.epoch_invalid"
        )
        expiry = effective_epoch + float(retention_seconds)
        with self.mutation():
            row = self.connection.execute(
                f"SELECT * FROM {_TABLE} WHERE key_digest = ?", (key,)
            ).fetchone()
            if row is None:
                raise DelegationReceiptConflict("delegation_receipt.not_found")
            existing = self._record(row)
            if existing.state != "reserved":
                raise DelegationReceiptConflict("delegation_receipt.state_conflict")
            changed = self.connection.execute(
                f"UPDATE {_TABLE} SET state = 'rejected', updated_at = ?, expires_at = ? "
                "WHERE key_digest = ? AND state = 'reserved'",
                (occurred_at, expiry, key),
            ).rowcount
            if changed != 1:
                raise DelegationReceiptConflict("delegation_receipt.state_conflict")
            return replace(
                existing,
                state="rejected",
                updated_at=occurred_at,
                expires_at=expiry,
            )

    def mark_outcome(
        self,
        *,
        key_digest: str,
        state: str,
        result_task_revision: int | None = None,
        now: str | None = None,
        epoch: float | None = None,
        retention_seconds: float = IDEMPOTENCY_RETENTION_SECONDS,
    ) -> DelegationActionReceipt:
        """Persist a verified terminal or explicitly uncertain outcome.

        Only verified ``accepted`` and ``rejected`` records receive an expiry.
        Ambiguous ``unknown`` and ``partial`` outcomes deliberately retain their
        exact key forever until an explicit later reconciliation resolves them.
        """

        if state not in _TERMINAL | _UNCERTAIN:
            raise DelegationReceiptValidationError("delegation_receipt.state_invalid")
        if state == "accepted" and result_task_revision is None:
            raise DelegationReceiptValidationError(
                "delegation_receipt.result_revision_required"
            )
        if not isinstance(retention_seconds, (int, float)) or isinstance(retention_seconds, bool) or retention_seconds <= 0 or not math.isfinite(float(retention_seconds)):
            raise DelegationReceiptValidationError("delegation_receipt.retention_invalid")
        effective_epoch = time.time() if epoch is None else _epoch(epoch, code="delegation_receipt.epoch_invalid")
        expiry = effective_epoch + float(retention_seconds) if state in _TERMINAL else None
        return self._transition(
            key_digest=key_digest,
            state=state,
            result_task_revision=_revision(result_task_revision, nullable=True),
            now=now,
            epoch=expiry,
        )

    def _transition(
        self,
        *,
        key_digest: str,
        state: str,
        result_task_revision: int | None,
        now: str | None,
        epoch: float | None,
    ) -> DelegationActionReceipt:
        key = _digest(key_digest, code="delegation_receipt.key_invalid")
        occurred_at = _timestamp(now or _now_timestamp())
        with self.mutation():
            row = self.connection.execute(
                f"SELECT * FROM {_TABLE} WHERE key_digest = ?", (key,)
            ).fetchone()
            if row is None:
                raise DelegationReceiptConflict("delegation_receipt.not_found")
            existing = self._record(row)
            if state not in _TRANSITIONS.get(existing.state, frozenset()):
                raise DelegationReceiptConflict("delegation_receipt.state_conflict")
            effective_result_revision = (
                existing.result_task_revision
                if result_task_revision is None
                else _revision(result_task_revision)
            )
            if state == "accepted" and (
                effective_result_revision is None
                or existing.result_proof_digest is None
                or effective_result_revision != existing.result_task_revision
            ):
                raise DelegationReceiptValidationError(
                    "delegation_receipt.result_proof_required"
                )
            changed = self.connection.execute(
                f"UPDATE {_TABLE} SET state = ?, result_task_revision = ?, updated_at = ?, expires_at = ? "
                "WHERE key_digest = ? AND state = ?",
                (state, effective_result_revision, occurred_at, epoch, key, existing.state),
            ).rowcount
            if changed != 1:
                raise DelegationReceiptConflict("delegation_receipt.state_conflict")
            return replace(
                existing,
                state=state,
                result_task_revision=effective_result_revision,
                updated_at=occurred_at,
                expires_at=epoch,
            )

    def prune_expired(self, *, epoch: float | None = None, limit: int = MAX_PRUNE_PER_MUTATION) -> int:
        cutoff = time.time() if epoch is None else _epoch(epoch, code="delegation_receipt.epoch_invalid")
        if type(limit) is not int or not 1 <= limit <= MAX_PRUNE_PER_MUTATION:
            raise DelegationReceiptValidationError("delegation_receipt.prune_limit_invalid")
        with self.mutation():
            return self._prune_expired_in_transaction(cutoff, limit=limit)

    def _prune_expired_in_transaction(self, epoch: float, *, limit: int = MAX_PRUNE_PER_MUTATION) -> int:
        rows = self.connection.execute(
            f"SELECT key_digest FROM {_TABLE} WHERE state IN ('accepted', 'rejected') "
            "AND expires_at IS NOT NULL AND expires_at <= ? "
            "ORDER BY expires_at, key_digest LIMIT ?",
            (epoch, limit),
        ).fetchall()
        if not rows:
            return 0
        keys = tuple(str(row[0]) for row in rows)
        placeholders = ",".join("?" for _ in keys)
        deleted = self.connection.execute(
            f"DELETE FROM {_TABLE} WHERE key_digest IN ({placeholders}) "
            "AND state IN ('accepted', 'rejected') AND expires_at IS NOT NULL AND expires_at <= ?",
            (*keys, epoch),
        ).rowcount
        if deleted != len(keys):
            raise DelegationReceiptConflict("delegation_receipt.prune_conflict")
        return deleted


__all__ = [
    "DelegationActionReceipt",
    "DelegationActionReceiptRepository",
    "DelegationReceiptConflict",
    "DelegationReceiptError",
    "DelegationReceiptUnavailable",
    "DelegationReceiptValidationError",
    "IDEMPOTENCY_RETENTION_SECONDS",
    "MAX_PRUNE_PER_MUTATION",
    "idempotency_key_digest",
]
