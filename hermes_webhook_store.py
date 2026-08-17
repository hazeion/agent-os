"""Durable replay protection for verified Hermes webhook deliveries."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading
from typing import Callable, Literal

from hermes_webhooks import VerifiedHermesEvent
from mentat_db import connect, transaction


DELIVERY_RETENTION_SECONDS = 24 * 60 * 60
DEFAULT_CLEANUP_BATCH = 256


class WebhookDeliveryStore:
    """Atomically claim keyed delivery digests in Mentat's private database."""

    def __init__(
        self,
        data_dir: Path | Callable[[], Path],
        *,
        retention_seconds: int = DELIVERY_RETENTION_SECONDS,
        cleanup_batch: int = DEFAULT_CLEANUP_BATCH,
        connection_factory: Callable[[Path], sqlite3.Connection] = connect,
    ) -> None:
        if retention_seconds <= 0:
            raise ValueError("retention_seconds must be positive")
        if cleanup_batch <= 0:
            raise ValueError("cleanup_batch must be positive")
        self._data_dir = data_dir
        self.retention_seconds = int(retention_seconds)
        self.cleanup_batch = int(cleanup_batch)
        self._connect = connection_factory
        # Opening a migrated Mentat database configures WAL mode. Serialize that
        # setup for concurrent receiver threads before SQLite's transaction-level
        # locking takes over.
        self._connection_lock = threading.RLock()

    @property
    def data_dir(self) -> Path:
        value = self._data_dir() if callable(self._data_dir) else self._data_dir
        return Path(value)

    @staticmethod
    def _epoch(value: datetime | None) -> float:
        current = value or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("webhook store timestamps must be timezone-aware")
        return current.astimezone(timezone.utc).timestamp()

    def _cleanup_locked(self, connection: sqlite3.Connection, now_epoch: float) -> int:
        cursor = connection.execute(
            """
            DELETE FROM hermes_webhook_deliveries
            WHERE rowid IN (
                SELECT rowid
                FROM hermes_webhook_deliveries
                WHERE expires_at <= ?
                ORDER BY expires_at
                LIMIT ?
            )
            """,
            (now_epoch, self.cleanup_batch),
        )
        return max(0, int(cursor.rowcount))

    def claim(self, event: VerifiedHermesEvent) -> bool:
        """Return true exactly once for an unexpired binding/delivery digest."""
        return self.claim_and_admit(event, lambda: True) == "accepted"

    def claim_and_admit(
        self,
        event: VerifiedHermesEvent,
        admit: Callable[[], bool],
    ) -> Literal["accepted", "admitted_unrecorded", "duplicate", "rejected"]:
        """Retain a claim when admitted, distinguishing a failed final commit."""
        now_epoch = self._epoch(event.received_at)
        with self._connection_lock:
            connection = self._connect(self.data_dir)
            preserve_admitted_result = False
            try:
                connection.execute("BEGIN IMMEDIATE")
                admitted = False
                try:
                    connection.execute(
                        """
                        DELETE FROM hermes_webhook_deliveries
                        WHERE binding_id = ? AND delivery_digest = ? AND expires_at <= ?
                        """,
                        (event.binding_id, event.delivery_digest, now_epoch),
                    )
                    self._cleanup_locked(connection, now_epoch)
                    try:
                        connection.execute(
                            """
                            INSERT INTO hermes_webhook_deliveries (
                                binding_id, delivery_digest, event_name,
                                received_at, expires_at, outcome
                            ) VALUES (?, ?, ?, ?, ?, 'accepted')
                            """,
                            (
                                event.binding_id,
                                event.delivery_digest,
                                event.event_name,
                                now_epoch,
                                now_epoch + self.retention_seconds,
                            ),
                        )
                    except sqlite3.IntegrityError:
                        existing = connection.execute(
                            """
                            SELECT 1 FROM hermes_webhook_deliveries
                            WHERE binding_id = ? AND delivery_digest = ?
                            """,
                            (event.binding_id, event.delivery_digest),
                        ).fetchone()
                        if existing is None:
                            raise
                        connection.commit()
                        return "duplicate"
                    if not admit():
                        connection.rollback()
                        return "rejected"
                    admitted = True
                    try:
                        connection.commit()
                    except Exception:
                        preserve_admitted_result = True
                        try:
                            connection.rollback()
                        except Exception:
                            pass
                        return "admitted_unrecorded"
                    return "accepted"
                except Exception:
                    if not admitted:
                        connection.rollback()
                    raise
            finally:
                if preserve_admitted_result:
                    try:
                        connection.close()
                    except Exception:
                        pass
                else:
                    connection.close()

    def cleanup(self, *, now: datetime | None = None) -> int:
        """Delete at most one bounded batch of expired replay records."""
        with self._connection_lock:
            connection = self._connect(self.data_dir)
            try:
                with transaction(connection, immediate=True):
                    return self._cleanup_locked(connection, self._epoch(now))
            finally:
                connection.close()
