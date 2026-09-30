"""Fixed, opt-in observations for frozen Windows CI startup only."""

import os
import sys
import time


_PHASES = frozenset({
    "native-entry", "native-verifiers-done", "native-imports-done",
    "preflight", "preflight-done", "lifecycle-import", "lifecycle-import-done",
    "data-preflight", "data-preflight-done", "listener-preflight",
    "listener-preflight-done", "node-check", "node-check-done",
    "authority", "startup-cleanup", "startup-cleanup-done", "task-authority",
    "project-authority", "run-authority", "authority-done", "private-bridge",
    "private-bridge-ready", "node-launch", "node-gateway-ready", "node-bridge-ready",
})
_seen: set[str] = set()
_started_at: float | None = None


def mark_native_startup_phase(phase: str) -> None:
    """Emit at most one short fixed line per phase; never accept diagnostic data."""

    global _started_at
    if (
        os.environ.get("MENTAT_CI_NATIVE_STARTUP_DIAGNOSTICS") != "1"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or not bool(getattr(sys, "frozen", False))
        or sys.platform != "win32"
        or sys.stderr is None
        or not isinstance(phase, str)
        or phase not in _PHASES
        or phase in _seen
    ):
        return
    _seen.add(phase)
    try:
        now = time.monotonic()
        if _started_at is None:
            _started_at = now
        elapsed_ms = min(999_999_999, max(0, int((now - _started_at) * 1000)))
        utc_ms = min(9_999_999_999_999, max(0, int(time.time() * 1000)))
        role = "private-bridge" if sys.argv[1:2] == ["--mentat-private-bridge"] else "launcher"
        print(f"Mentat CI startup role={role} phase={phase} utc_ms={utc_ms} elapsed_ms={elapsed_ms}", file=sys.stderr, flush=True)
    except (OSError, ValueError, OverflowError):
        # Optional observations must not turn a closed GUI/redirect stream into
        # a startup failure or change any runtime readiness deadline.
        return
