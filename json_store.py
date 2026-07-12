"""Thread-safe JSON file helpers for Mentat project-owned data.

The dashboard runs on ThreadingHTTPServer, so read-modify-write routes must
serialize per file and write through unique temp files before atomic replace.
These helpers intentionally know nothing about Hermes core paths; server.py
keeps the allowlist and data-directory boundary checks.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from uuid import uuid4
from typing import Any, Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

NO_WRITE = object()
_LOCKS_GUARD = threading.Lock()
_FILE_LOCKS: dict[Path, threading.RLock] = {}


def lock_for(path: Path) -> threading.RLock:
    """Return a stable re-entrant lock for a resolved JSON path."""
    resolved = path.resolve()
    with _LOCKS_GUARD:
        lock = _FILE_LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _FILE_LOCKS[resolved] = lock
        return lock


def read_json(path: Path, default: T) -> T | Any:
    """Read JSON from path, returning default when the file is absent."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json_atomic(path: Path, payload: Any, *, mode: int | None = None) -> None:
    """Atomically write JSON with a unique temp filename beside the target.

    Windows can transiently deny ``os.replace``/``Path.replace`` while another
    local process (indexer, antivirus, file watcher) has a short-lived handle on
    the target. Keep the operation atomic, but retry briefly before surfacing the
    error so high-frequency dashboard writes do not fail spuriously.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is not None:
        path.parent.chmod(0o700)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if mode is not None:
        tmp.chmod(mode)
    delays = (0.01, 0.025, 0.05, 0.1)
    for attempt in range(len(delays) + 1):
        try:
            tmp.replace(path)
            if mode is not None:
                path.chmod(mode)
            return
        except PermissionError:
            if attempt == len(delays):
                try:
                    tmp.unlink(missing_ok=True)
                finally:
                    raise
            time.sleep(delays[attempt])


def update_json(path: Path, default: T, mutator: Callable[[T | Any], tuple[Any, R]]) -> R:
    """Serialize a read-modify-write cycle for one JSON file.

    The mutator receives the decoded payload (or default if missing) and returns
    ``(new_payload, result)``. The new payload is written before result is
    returned. Returning the original object (or ``NO_WRITE``) skips the disk
    write, which lets validation/not-found responses avoid reformatting files or
    bumping mtimes. JSON decode errors intentionally propagate to the caller so
    route handlers can preserve existing error semantics.
    """
    with lock_for(path):
        current = read_json(path, default)
        new_payload, result = mutator(current)
        if new_payload is not NO_WRITE and new_payload is not current:
            write_json_atomic(path, new_payload)
        return result
