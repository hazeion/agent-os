"""Bounded read-only refresh coordination for verified Hermes webhook hints.

Webhook deliveries are best-effort notifications.  This module deliberately
does not project state from their payloads: an accepted event only selects
existing read adapters, and adapter results become the in-memory projection.
Periodic reconciliation remains the correctness backstop.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import queue
import threading
import time
from typing import Any, Callable, Iterable, Mapping

from hermes_webhooks import VerifiedHermesEvent


ProjectionAdapter = Callable[[str], Any]

PROJECTION_KINDS = frozenset({"sessions", "agents", "attention", "kanban"})
EVENT_PROJECTIONS: dict[str, frozenset[str]] = {
    "on_session_start": frozenset({"sessions", "agents"}),
    "on_session_end": frozenset({"sessions", "agents", "attention"}),
    "subagent_start": frozenset({"agents"}),
    "subagent_stop": frozenset({"agents", "attention", "kanban"}),
}


def projection_kinds_for_event(event_name: str) -> frozenset[str]:
    """Return the fixed read-only refresh set for one allowlisted event."""
    return EVENT_PROJECTIONS.get(event_name, frozenset())


@dataclass(frozen=True)
class RefreshHint:
    binding_id: str
    event_name: str
    projections: frozenset[str]

    @classmethod
    def from_event(cls, event: VerifiedHermesEvent) -> "RefreshHint":
        return cls(
            binding_id=event.binding_id,
            event_name=event.event_name,
            projections=projection_kinds_for_event(event.event_name),
        )


def _health_record() -> dict[str, Any]:
    return {
        "accepted_hint_count": 0,
        "coalesced_hint_count": 0,
        "queue_drop_count": 0,
        "unresolved_drop_count": 0,
        "refresh_success_count": 0,
        "refresh_failure_count": 0,
        "degraded_projection_count": 0,
        "backoff_skip_count": 0,
        "reconciliation_count": 0,
        "last_event_name": None,
        "last_event_at": None,
        "last_refresh_at": None,
        "last_reconciled_at": None,
        "last_error_code": None,
    }


class HermesRefreshCoordinator:
    """Consume webhook hints off-request and refresh bounded projections.

    One daemon worker owns all adapter calls.  That is stricter than the
    required one-read-per-binding limit and avoids overlapping Hermes reads in
    this first coordinator slice.  The finite binding/projection key space also
    bounds snapshots, backoff state, and health evidence.
    """

    def __init__(
        self,
        adapters: Mapping[str, ProjectionAdapter],
        *,
        binding_ids: Iterable[str] = (),
        capacity: int = 256,
        coalesce_window: float = 0.25,
        reconciliation_interval: float = 60.0,
        base_backoff: float = 1.0,
        max_backoff: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        if coalesce_window < 0 or reconciliation_interval <= 0:
            raise ValueError("refresh timing must be non-negative")
        invalid = set(adapters) - PROJECTION_KINDS
        if invalid:
            raise ValueError("unsupported projection adapter")

        self._adapters = dict(adapters)
        self._queue: queue.Queue[RefreshHint] = queue.Queue(maxsize=capacity)
        self._coalesce_window = coalesce_window
        self._reconciliation_interval = reconciliation_interval
        self._base_backoff = max(0.01, base_backoff)
        self._max_backoff = max(self._base_backoff, max_backoff)
        self._clock = clock
        self._known_bindings = set(binding_ids)
        self._health: dict[str, dict[str, Any]] = {}
        self._snapshots: dict[tuple[str, str], Any] = {}
        self._failures: dict[tuple[str, str], int] = {}
        self._retry_after: dict[tuple[str, str], float] = {}
        self._state_lock = threading.RLock()
        self._stop = threading.Event()
        self._accepting = True
        self._thread: threading.Thread | None = None
        self._started_at: str | None = None

    @property
    def capacity(self) -> int:
        return self._queue.maxsize

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def is_running(self) -> bool:
        """Whether the coordinator can currently accept and process hints."""
        with self._state_lock:
            thread = self._thread
            return bool(
                self._accepting
                and not self._stop.is_set()
                and thread is not None
                and thread.is_alive()
            )

    def start(self) -> None:
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._stop.is_set():
                raise RuntimeError("stopped coordinators cannot be restarted")
            self._started_at = _utc_now()
            thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="mentat-hermes-refresh",
            )
            thread.start()
            self._thread = thread

    def enqueue(self, event: VerifiedHermesEvent) -> bool:
        """Queue a minimal hint without waiting for any adapter read."""
        hint = RefreshHint.from_event(event)
        if not hint.projections:
            return False
        with self._state_lock:
            health = self._health.setdefault(hint.binding_id, _health_record())
            self._known_bindings.add(hint.binding_id)
            if not self._accepting:
                health["queue_drop_count"] += 1
                health["unresolved_drop_count"] += 1
                return False
            try:
                self._queue.put_nowait(hint)
            except queue.Full:
                health["queue_drop_count"] += 1
                health["unresolved_drop_count"] += 1
                return False
            health["accepted_hint_count"] += 1
            health["last_event_name"] = hint.event_name
            health["last_event_at"] = _utc_now()
            return True

    def wait_idle(self, timeout: float) -> bool:
        """Wait until every accepted hint has completed its adapter work."""
        deadline = self._clock() + max(0, timeout)
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = deadline - self._clock()
                if remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
            return True

    def stop(self, *, timeout: float = 2.0) -> bool:
        """Stop accepting hints and bound the caller's shutdown wait."""
        with self._state_lock:
            self._accepting = False
            thread = self._thread
        self._stop.set()
        if thread is None or not thread.is_alive():
            return True
        thread.join(max(0, timeout))
        return not thread.is_alive()

    def health_snapshot(self, binding_id: str) -> dict[str, Any]:
        """Return bounded, payload-free process health for tests and future 9D."""
        with self._state_lock:
            snapshot = dict(self._health.get(binding_id, _health_record()))
            snapshot["coordinator_started_at"] = self._started_at
            return snapshot

    def projection_snapshot(self, binding_id: str, projection: str) -> Any:
        """Return the last authoritative adapter result, never webhook fields."""
        with self._state_lock:
            value = self._snapshots.get((binding_id, projection))
            return deepcopy(value)

    def _run(self) -> None:
        next_reconciliation = self._clock() + self._reconciliation_interval
        while True:
            if self._stop.is_set() and self._queue.empty():
                return

            now = self._clock()
            timeout = max(0.0, min(0.1, next_reconciliation - now))
            if self._stop.is_set():
                timeout = 0.0
            try:
                first = self._queue.get(timeout=timeout)
            except queue.Empty:
                if not self._stop.is_set() and self._clock() >= next_reconciliation:
                    self._reconcile()
                    next_reconciliation = self._clock() + self._reconciliation_interval
                continue

            hints = [first]
            deadline = self._clock() + self._coalesce_window
            while True:
                if self._stop.is_set():
                    remaining = 0.0
                else:
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        break
                try:
                    if self._stop.is_set():
                        hints.append(self._queue.get_nowait())
                    else:
                        hints.append(self._queue.get(timeout=remaining))
                except queue.Empty:
                    break
            try:
                self._process_hints(hints)
            finally:
                for _hint in hints:
                    self._queue.task_done()

            if not self._stop.is_set() and self._clock() >= next_reconciliation:
                self._reconcile()
                next_reconciliation = self._clock() + self._reconciliation_interval

    def _process_hints(self, hints: list[RefreshHint]) -> None:
        pending: dict[str, set[str]] = {}
        counts: dict[str, int] = {}
        for hint in hints:
            pending.setdefault(hint.binding_id, set()).update(hint.projections)
            counts[hint.binding_id] = counts.get(hint.binding_id, 0) + 1
        with self._state_lock:
            for binding_id, count in counts.items():
                self._health.setdefault(binding_id, _health_record())[
                    "coalesced_hint_count"
                ] += max(0, count - 1)
        for binding_id in sorted(pending):
            for projection in sorted(pending[binding_id]):
                self._refresh_projection(binding_id, projection)

    def _reconcile(self) -> None:
        with self._state_lock:
            bindings = tuple(sorted(self._known_bindings))
        for binding_id in bindings:
            with self._state_lock:
                unresolved_before_sweep = self._health.setdefault(
                    binding_id, _health_record()
                )["unresolved_drop_count"]
            for projection in sorted(self._adapters):
                self._refresh_projection(binding_id, projection)
            with self._state_lock:
                health = self._health.setdefault(binding_id, _health_record())
                health["reconciliation_count"] += 1
                health["last_reconciled_at"] = _utc_now()
                if not any(failed_binding == binding_id for failed_binding, _ in self._failures):
                    health["unresolved_drop_count"] = max(
                        0,
                        health["unresolved_drop_count"] - unresolved_before_sweep,
                    )

    def _refresh_projection(self, binding_id: str, projection: str) -> None:
        adapter = self._adapters.get(projection)
        if adapter is None:
            return
        key = (binding_id, projection)
        now = self._clock()
        with self._state_lock:
            health = self._health.setdefault(binding_id, _health_record())
            if now < self._retry_after.get(key, 0):
                health["backoff_skip_count"] += 1
                return
        try:
            snapshot = deepcopy(adapter(binding_id))
        except Exception:
            with self._state_lock:
                failures = self._failures.get(key, 0) + 1
                self._failures[key] = failures
                delay = min(
                    self._max_backoff,
                    self._base_backoff * (2 ** min(failures - 1, 30)),
                )
                self._retry_after[key] = self._clock() + delay
                health = self._health.setdefault(binding_id, _health_record())
                health["refresh_failure_count"] += 1
                health["degraded_projection_count"] = sum(
                    1 for failed_binding, _projection in self._failures
                    if failed_binding == binding_id
                )
                health["last_error_code"] = "webhook_refresh_failed"
            return

        with self._state_lock:
            if self._stop.is_set():
                return
            self._snapshots[key] = snapshot
            self._failures.pop(key, None)
            self._retry_after.pop(key, None)
            health = self._health.setdefault(binding_id, _health_record())
            health["refresh_success_count"] += 1
            health["last_refresh_at"] = _utc_now()
            health["degraded_projection_count"] = sum(
                1 for failed_binding, _projection in self._failures
                if failed_binding == binding_id
            )
            health["last_error_code"] = (
                "webhook_refresh_failed"
                if health["degraded_projection_count"]
                else None
            )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
