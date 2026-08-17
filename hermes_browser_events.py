"""Bounded, payload-free browser wakeups after authoritative Hermes reads."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import threading
import time
from typing import Callable, Iterable


SCHEMA_VERSION = 1
ALLOWED_PROJECTIONS = frozenset({"sessions", "agents", "attention", "kanban"})


@dataclass(frozen=True)
class BrowserProjectionEvent:
    sequence: int
    generated_at: str
    projections: tuple[str, ...]

    def public_payload(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "sequence": self.sequence,
            "generated_at": self.generated_at,
            "projections": list(self.projections),
        }


class HermesBrowserEventBroker:
    """Keep a small reconnect history and cap long-lived browser clients."""

    def __init__(
        self,
        *,
        history_size: int = 64,
        max_clients: int = 8,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if history_size < 1 or max_clients < 1:
            raise ValueError("browser event bounds must be positive")
        self._history: deque[BrowserProjectionEvent] = deque(maxlen=history_size)
        self._max_clients = int(max_clients)
        self._clock = clock
        self._sequence = 0
        self._active_clients = 0
        self._condition = threading.Condition(threading.RLock())

    @property
    def active_clients(self) -> int:
        with self._condition:
            return self._active_clients

    @property
    def sequence(self) -> int:
        with self._condition:
            return self._sequence

    def acquire_client(self) -> bool:
        with self._condition:
            if self._active_clients >= self._max_clients:
                return False
            self._active_clients += 1
            return True

    def release_client(self) -> None:
        with self._condition:
            self._active_clients = max(0, self._active_clients - 1)

    def publish(self, _binding_id: str, projections: Iterable[str]) -> int | None:
        safe = tuple(sorted(set(projections) & ALLOWED_PROJECTIONS))
        if not safe:
            return None
        with self._condition:
            self._sequence += 1
            event = BrowserProjectionEvent(
                sequence=self._sequence,
                generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                projections=safe,
            )
            self._history.append(event)
            self._condition.notify_all()
            return event.sequence

    def wait_after(
        self,
        after_sequence: int,
        *,
        timeout: float = 15.0,
    ) -> BrowserProjectionEvent | None:
        """Return one coalesced event newer than the caller's safe cursor."""
        after = max(0, int(after_sequence))
        deadline = self._clock() + max(0.0, timeout)
        with self._condition:
            if after > self._sequence:
                # Browser cursors can survive a Mentat process restart while
                # this process-local sequence restarts at zero. Reset that
                # advisory cursor immediately and force a complete readback;
                # otherwise push could remain silent until enough new events
                # happened to overtake the stale sequence.
                return BrowserProjectionEvent(
                    sequence=self._sequence,
                    generated_at=datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    projections=tuple(sorted(ALLOWED_PROJECTIONS)),
                )
            while self._sequence <= after:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if not self._history:
                return None
            oldest = self._history[0].sequence
            if after < oldest - 1:
                projections = tuple(sorted(ALLOWED_PROJECTIONS))
            else:
                projections = tuple(
                    sorted(
                        {
                            projection
                            for event in self._history
                            if event.sequence > after
                            for projection in event.projections
                        }
                    )
                )
            latest = self._history[-1]
            return BrowserProjectionEvent(
                sequence=latest.sequence,
                generated_at=latest.generated_at,
                projections=projections,
            )
