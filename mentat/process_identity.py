"""Small, runtime-neutral helpers for binding a Linux PID to one process."""

from __future__ import annotations

from pathlib import Path
import sys

IS_LINUX = sys.platform.startswith("linux")


def parse_linux_process_start_ticks(payload: str, expected_pid: int) -> int | None:
    """Return field 22 from a bounded Linux /proc/<pid>/stat payload."""

    if isinstance(expected_pid, bool) or not isinstance(expected_pid, int) or expected_pid <= 0:
        return None
    text = str(payload or "")
    if not text or len(text) > 4096:
        return None
    closing_parenthesis = text.rfind(")")
    if closing_parenthesis <= 0 or not text.startswith(f"{expected_pid} ("):
        return None
    fields = text[closing_parenthesis + 1 :].strip().split()
    if len(fields) <= 19:
        return None
    try:
        start_ticks = int(fields[19])
    except ValueError:
        return None
    return start_ticks if start_ticks > 0 else None


def linux_process_start_ticks(pid: int) -> int | None:
    """Read one Linux process start identity, or fail closed elsewhere."""

    if (
        not IS_LINUX
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
    ):
        return None
    try:
        payload = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
    except (OSError, UnicodeError, ValueError):
        return None
    return parse_linux_process_start_ticks(payload, pid)
