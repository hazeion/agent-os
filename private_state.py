"""Shared storage and lock boundary for durable private Agent Console state."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path
import stat
from typing import Callable, Iterator, TypeVar

from data_layout import (
    _absolute_without_following,
    _is_redirecting_entry,
    _redirected_component_issue,
    _secure_directory,
)
from json_store import _durable_mutation_lock


CONSOLE_DIRECTORY_NAME = "console"
HISTORY_NAME = "agent-console-runs.json"
DATABASE_NAME = "mentat.sqlite3"
BLOB_DIRECTORY_PARTS = ("blobs", "sha256")
MIGRATION_RESERVATION_NAME = "private-console-migration-v1.reservation.json"
RESTORE_RESERVATION_NAME = "private-console-restore-v1.reservation.json"
GENERAL_RESTORE_STATE_NAME = "restore-state-v1.json"
CONNECTION_SERVER_RESERVATION_NAME = "connection-server-reservation-v1.json"

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


def inspect_console_root(
    data_root: Path,
    *,
    allow_missing: bool = False,
) -> tuple[Path, tuple[tuple[int, int], ...]] | None:
    """Inspect the Console directory chain without creating or hardening it."""

    root = _absolute_without_following(Path(data_root))
    target = console_root(root)
    if _redirected_component_issue(target, "private_console") is not None:
        raise PrivateStateError("Mentat private Console directory is unsafe")
    identities: list[tuple[int, int]] = []
    for directory in (root, private_root(root), target):
        try:
            details = os.lstat(directory)
        except FileNotFoundError:
            if allow_missing:
                return None
            raise PrivateStateError("Mentat private Console directory is missing")
        except OSError as exc:
            raise PrivateStateError("Mentat private Console directory is unsafe") from exc
        if (
            _is_redirecting_entry(details)
            or not stat.S_ISDIR(details.st_mode)
            or (os.name == "posix" and details.st_uid != os.getuid())
        ):
            raise PrivateStateError("Mentat private Console directory is unsafe")
        identities.append((int(details.st_dev), int(details.st_ino)))
    resolved_root = root.resolve(strict=True)
    resolved_console = target.resolve(strict=True)
    if resolved_console.parent.parent != resolved_root:
        raise PrivateStateError("Mentat private Console directory escapes the data root")
    return resolved_console, tuple(identities)



def fresh_console_storage_issue(data_root: Path) -> str | None:
    """Inspect missing-database storage without creating or hardening anything.

    Only an absent/empty Console or the current empty summary document can be
    fresh. Existing SQLite authority is outside this helper's contract.
    """
    import json

    root = Path(data_root)
    runtime = root / "runtime"
    maximum = 4 * 1024 * 1024
    try:
        if os.path.lexists(runtime):
            runtime_details = os.lstat(runtime)
            if (_is_redirecting_entry(runtime_details) or not stat.S_ISDIR(runtime_details.st_mode)
                    or (os.name == "posix" and runtime_details.st_uid != os.getuid())):
                return "private_console_unsafe"
            with os.scandir(runtime) as entries:
                if any(entry.name in {DATABASE_NAME, HISTORY_NAME, "blobs", "agent-registry.sqlite3"}
                       or entry.name.startswith((DATABASE_NAME + "-", "agent-registry.sqlite3-"))
                       for entry in entries):
                    return "private_database_unsupported"
        inspected = inspect_console_root(root, allow_missing=True)
        if inspected is None:
            return None
        source, identity = inspected
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(source, flags) if os.name == "posix" else None
        try:
            opened = os.fstat(descriptor) if descriptor is not None else os.lstat(source)
            if (int(opened.st_dev), int(opened.st_ino)) != identity[-1]:
                return "private_console_changed"
            def inventory():
                return tuple(os.listdir(descriptor if descriptor is not None else source))
            def history_stat():
                return (os.stat(HISTORY_NAME, dir_fd=descriptor, follow_symlinks=False)
                        if descriptor is not None else os.lstat(source / HISTORY_NAME))
            entries = inventory()
            if not entries:
                return None if not inventory() and inspect_console_root(root)[1] == identity else "private_console_changed"
            if entries != (HISTORY_NAME,):
                return "private_database_missing"
            def history_safe(details):
                return (stat.S_ISREG(details.st_mode) and not _is_redirecting_entry(details)
                        and details.st_nlink == 1 and details.st_size <= maximum
                        and (os.name != "posix" or (details.st_uid == os.getuid()
                             and stat.S_IMODE(details.st_mode) == 0o600)))
            lexical = history_stat()
            if not history_safe(lexical):
                return "private_history_invalid"
            history_flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0)
                             | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
            history_descriptor = (os.open(HISTORY_NAME, history_flags, dir_fd=descriptor)
                                  if descriptor is not None else os.open(source / HISTORY_NAME, history_flags))
            try:
                before = os.fstat(history_descriptor)
                if not history_safe(before):
                    return "private_history_invalid"
                if (before.st_dev, before.st_ino) != (lexical.st_dev, lexical.st_ino):
                    return "private_console_changed"
                raw = bytearray()
                while len(raw) <= maximum:
                    chunk = os.read(history_descriptor, min(65536, maximum + 1 - len(raw)))
                    if not chunk:
                        break
                    raw.extend(chunk)
                after = os.fstat(history_descriptor)
                if not history_safe(after):
                    return "private_history_invalid"
                if (len(raw) > maximum or len(raw) != before.st_size
                        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)):
                    return "private_console_changed"
            finally:
                os.close(history_descriptor)
            def unique_pairs(items):
                result = {}
                for key, value in items:
                    if key in result:
                        raise ValueError("duplicate history key")
                    result[key] = value
                return result
            document = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
            if (not isinstance(document, dict) or set(document) != {"schema_version", "runs"}
                    or type(document["schema_version"]) is not int or document["schema_version"] != 3
                    or document["runs"] != []):
                return "private_history_invalid"
            current = history_stat()
            if not history_safe(current):
                return "private_history_invalid"
            if (inventory() != entries
                    or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                    or inspect_console_root(root)[1] != identity):
                return "private_console_changed"
            return None
        finally:
            if descriptor is not None:
                os.close(descriptor)
    except (OSError, ValueError, UnicodeError, RecursionError, TypeError):
        return "private_console_unsafe"


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
    """Fail closed when a recorded or starting Mentat server PID is still alive."""

    runtime = Path(data_root) / "runtime"
    for state in (
        runtime / CONNECTION_SERVER_RESERVATION_NAME,
        runtime / "server-state.json",
    ):
        active = _pid_record_active(state)
        if active is True:
            return True
    return False


def _pid_record_active(state: Path) -> bool | None:
    """Return None for absence, false for a dead PID, and true for unsafe/live state."""

    try:
        if state.is_symlink() or not state.is_file():
            return True if os.path.lexists(os.fspath(state)) else None
        import json

        payload = json.loads(state.read_text(encoding="utf-8"))
        pid = payload.get("pid") if isinstance(payload, dict) else None
        if not isinstance(pid, int) or pid <= 0:
            return True
        return _pid_is_running(pid)
    except FileNotFoundError:
        return None
    except ProcessLookupError:
        return False
    except (OSError, UnicodeError, ValueError, TypeError):
        return True


def _pid_is_running(pid: int) -> bool:
    """Check PID liveness without relying on os.kill(pid, 0) on Windows."""

    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    import ctypes
    from ctypes import wintypes

    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    error_invalid_parameter = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return False
        raise ctypes.WinError(error)
    try:
        wait_result = kernel32.WaitForSingleObject(handle, 0)
        if wait_result == wait_timeout:
            return True
        if wait_result == wait_object_0:
            return False
        raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel32.CloseHandle(handle)


def connection_server_reservation_path(data_root: Path) -> Path:
    return Path(data_root) / "runtime" / CONNECTION_SERVER_RESERVATION_NAME


def reserve_mentat_server(data_root: Path) -> None:
    """Publish a live startup reservation under the private-state mutation lock."""

    root = Path(data_root)
    with private_state_lock(root):
        if mentat_server_active(root):
            raise PrivateStateError("Mentat server is already active")
        runtime = root / "runtime"
        if not _secure_directory(runtime):
            raise PrivateStateError("Mentat runtime directory is unsafe")
        from json_store import write_json_atomic

        write_json_atomic(
            connection_server_reservation_path(root),
            {"schema_version": 1, "pid": os.getpid()},
            mode=0o600,
            maximum_bytes=1024,
        )


def release_mentat_server(data_root: Path) -> None:
    """Remove only this process's startup/lifetime reservation."""

    root = Path(data_root)
    path = connection_server_reservation_path(root)
    with private_state_lock(root):
        try:
            if path.is_symlink() or not path.is_file():
                return
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {"schema_version", "pid"} or payload.get("pid") != os.getpid():
                return
            path.unlink()
        except (FileNotFoundError, OSError, UnicodeError, ValueError, TypeError):
            return


def private_control_issue(data_root: Path) -> str | None:
    """Return a bounded issue when private mutation must remain blocked."""

    root = _absolute_without_following(Path(data_root))
    for path, issue in (
        (migration_reservation_path(root), "unsupported_legacy_private_storage"),
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
                    return "unsupported_legacy_private_storage"
                if entry.name.startswith(".console-restore-"):
                    return "private_restore_incomplete"
    except OSError:
        return "private_control_invalid"
    return None


def _require_current_or_fresh_database(data_root: Path) -> None:
    from mentat_db import (
        MentatDatabaseError, validate_current_database_root,
    )

    try:
        current = validate_current_database_root(data_root)
    except (MentatDatabaseError, OSError) as exc:
        raise PrivateStateError("unsupported_or_invalid_current_database") from exc
    if not current:
        issue = fresh_console_storage_issue(data_root)
        if issue is not None:
            from mentat_db import MentatDatabaseError
            raise PrivateStateError(issue) from MentatDatabaseError(issue)


@contextmanager
def private_state_lock(
    data_root: Path,
    *,
    allow_control: bool = False,
) -> Iterator[int | None]:
    """Serialize the complete private Console unit with durable root mutation."""

    root = _absolute_without_following(Path(data_root))
    _require_current_or_fresh_database(root)
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
