"""Shared storage and lock boundary for durable private Agent Console state."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path
import stat
from typing import Callable, Iterator, TypeVar

from data_layout import _absolute_without_following, _secure_directory
from json_store import _durable_mutation_lock


CONSOLE_DIRECTORY_NAME = "console"
HISTORY_NAME = "agent-console-runs.json"
DATABASE_NAME = "mentat.sqlite3"
BLOB_DIRECTORY_PARTS = ("blobs", "sha256")
MIGRATION_RECEIPT_NAME = "private-console-migration-v1.json"
MIGRATION_RESERVATION_NAME = "private-console-migration-v1.reservation.json"
RESTORE_RESERVATION_NAME = "private-console-restore-v1.reservation.json"
GENERAL_RESTORE_STATE_NAME = "restore-state-v1.json"

R = TypeVar("R")


class PrivateStateError(OSError):
    """The durable private-state boundary is unsafe or unavailable."""


def private_root(data_root: Path) -> Path:
    return Path(data_root) / "private"


def console_root(data_root: Path) -> Path:
    return private_root(data_root) / CONSOLE_DIRECTORY_NAME


def history_path(data_root: Path) -> Path:
    return console_root(data_root) / HISTORY_NAME


def database_path(data_root: Path) -> Path:
    return console_root(data_root) / DATABASE_NAME


def blobs_root(data_root: Path) -> Path:
    path = console_root(data_root)
    for part in BLOB_DIRECTORY_PARTS:
        path /= part
    return path


def legacy_history_path(data_root: Path) -> Path:
    return Path(data_root) / "runtime" / HISTORY_NAME


def legacy_database_path(data_root: Path) -> Path:
    return Path(data_root) / "runtime" / DATABASE_NAME


def legacy_blobs_root(data_root: Path) -> Path:
    return Path(data_root) / "runtime" / "blobs" / "sha256"


def migration_receipt_path(data_root: Path) -> Path:
    return Path(data_root) / "config" / MIGRATION_RECEIPT_NAME


def migration_reservation_path(data_root: Path) -> Path:
    return Path(data_root) / "config" / MIGRATION_RESERVATION_NAME


def restore_reservation_path(data_root: Path) -> Path:
    return Path(data_root) / "config" / RESTORE_RESERVATION_NAME


def _private_directory_valid(path: Path) -> bool:
    try:
        details = os.lstat(path)
        return (
            stat.S_ISDIR(details.st_mode)
            and not stat.S_ISLNK(details.st_mode)
            and (os.name != "posix" or stat.S_IMODE(details.st_mode) == 0o700)
        )
    except OSError:
        return False


def ensure_console_root(data_root: Path) -> Path:
    """Create and verify the owner-only durable Console directory chain."""

    root = _absolute_without_following(Path(data_root))
    if not _secure_directory(root):
        raise PrivateStateError("Mentat data root is unsafe")
    for directory in (private_root(root), console_root(root)):
        if not _secure_directory(directory) or not _private_directory_valid(directory):
            raise PrivateStateError("Mentat private Console directory is unsafe")
    resolved_root = root.resolve(strict=True)
    resolved_console = console_root(root).resolve(strict=True)
    if resolved_console.parent.parent != resolved_root:
        raise PrivateStateError("Mentat private Console directory escapes the data root")
    return resolved_console


def ensure_private_root(data_root: Path) -> Path:
    """Create and verify only the owner-private root, not the Console destination."""

    root = _absolute_without_following(Path(data_root))
    if not _secure_directory(root) or not _secure_directory(private_root(root)):
        raise PrivateStateError("Mentat private root is unsafe")
    private = private_root(root)
    if not _private_directory_valid(private):
        raise PrivateStateError("Mentat private root is unsafe")
    resolved_root = root.resolve(strict=True)
    resolved_private = private.resolve(strict=True)
    if resolved_private.parent != resolved_root:
        raise PrivateStateError("Mentat private root escapes the data root")
    return resolved_private


def mentat_server_active(data_root: Path) -> bool:
    """Fail closed when a recorded Mentat server PID is still alive."""

    state = Path(data_root) / "runtime" / "server-state.json"
    try:
        if state.is_symlink() or not state.is_file():
            return os.path.lexists(os.fspath(state))
        import json

        payload = json.loads(state.read_text(encoding="utf-8"))
        pid = payload.get("pid") if isinstance(payload, dict) else None
        if not isinstance(pid, int) or pid <= 0:
            return True
        os.kill(pid, 0)
        return True
    except FileNotFoundError:
        return False
    except ProcessLookupError:
        return False
    except (OSError, UnicodeError, ValueError, TypeError):
        return True


def private_control_issue(data_root: Path) -> str | None:
    """Return a bounded issue when private mutation must remain blocked."""

    root = _absolute_without_following(Path(data_root))
    for path, issue in (
        (migration_reservation_path(root), "private_migration_incomplete"),
        (restore_reservation_path(root), "private_restore_incomplete"),
        (root / "config" / GENERAL_RESTORE_STATE_NAME, "private_restore_incomplete"),
    ):
        try:
            if os.path.lexists(os.fspath(path)):
                details = os.lstat(path)
                if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode):
                    return "private_control_invalid"
                return issue
        except OSError:
            return "private_control_invalid"
    private = private_root(root)
    try:
        if os.path.lexists(os.fspath(private)):
            details = os.lstat(private)
            if not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode):
                return "private_control_invalid"
            for entry in os.scandir(private):
                if entry.name.startswith(".console-migration-"):
                    return "private_migration_incomplete"
                if entry.name.startswith(".console-restore-"):
                    return "private_restore_incomplete"
    except OSError:
        return "private_control_invalid"
    return None


@contextmanager
def private_state_lock(
    data_root: Path,
    *,
    allow_control: bool = False,
) -> Iterator[int | None]:
    """Serialize the complete private Console unit with durable root mutation."""

    root = _absolute_without_following(Path(data_root))
    if not _secure_directory(root):
        raise PrivateStateError("Mentat data root is unsafe")
    with _durable_mutation_lock(root) as root_descriptor:
        if not allow_control:
            issue = private_control_issue(root)
            if issue is not None:
                raise PrivateStateError(issue)
        yield root_descriptor


def synchronized_private_state(function: Callable[..., R]) -> Callable[..., R]:
    """Wrap a data-root-first operation in the shared private-state lock."""

    @wraps(function)
    def wrapped(data_root: Path, *args, **kwargs):
        with private_state_lock(data_root):
            return function(data_root, *args, **kwargs)

    return wrapped


def legacy_private_entries(data_root: Path) -> tuple[Path, ...]:
    """Return only recognized legacy durable Console entries that exist."""

    entries = (
        legacy_history_path(data_root),
        legacy_database_path(data_root),
        Path(f"{legacy_database_path(data_root)}-wal"),
        Path(f"{legacy_database_path(data_root)}-shm"),
        legacy_blobs_root(data_root),
    )
    return tuple(path for path in entries if os.path.lexists(os.fspath(path)))
