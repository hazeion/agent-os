"""Thread-safe JSON file helpers for Mentat project-owned data.

The dashboard runs on ThreadingHTTPServer, so read-modify-write routes must
serialize per file and write through unique temp files before atomic replace.
These helpers intentionally know nothing about Hermes core paths; server.py
keeps the allowlist and data-directory boundary checks.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
import stat
import threading
import time
from pathlib import Path
from uuid import uuid4
from typing import Any, Callable, TypeVar

from data_layout import (
    _absolute_without_following,
    _initialization_lock,
    _is_redirecting_entry,
    _open_readonly_no_follow,
)

T = TypeVar("T")
R = TypeVar("R")

NO_WRITE = object()


class JsonCommitVerificationError(OSError):
    """The atomic replace occurred but exact post-commit verification failed."""
_LOCKS_GUARD = threading.Lock()
_FILE_LOCKS: dict[Path, threading.RLock] = {}
_ROOT_LOCKS: dict[Path, threading.RLock] = {}
_MUTATION_DEPTH = threading.local()


def lock_for(path: Path) -> threading.RLock:
    """Return a stable re-entrant lock without following the selected path."""
    resolved = _absolute_without_following(path)
    with _LOCKS_GUARD:
        lock = _FILE_LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _FILE_LOCKS[resolved] = lock
        return lock


def _root_lock_for(path: Path) -> threading.RLock:
    resolved = _absolute_without_following(path)
    with _LOCKS_GUARD:
        lock = _ROOT_LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _ROOT_LOCKS[resolved] = lock
        return lock


@contextmanager
def _durable_mutation_lock(data_root: Path, *, cross_process_lock: bool = True):
    """Take the process-reentrant root lock before any per-file lock."""

    resolved = _absolute_without_following(data_root)
    root_lock = _root_lock_for(resolved)
    with root_lock:
        depths = getattr(_MUTATION_DEPTH, "depths", None)
        if depths is None:
            depths = {}
            _MUTATION_DEPTH.depths = depths
        descriptors = getattr(_MUTATION_DEPTH, "descriptors", None)
        if descriptors is None:
            descriptors = {}
            _MUTATION_DEPTH.descriptors = descriptors
        modes = getattr(_MUTATION_DEPTH, "modes", None)
        if modes is None:
            modes = {}
            _MUTATION_DEPTH.modes = modes
        depth = depths.get(resolved, 0)
        depths[resolved] = depth + 1
        try:
            if depth:
                if cross_process_lock and not modes.get(resolved, False):
                    raise OSError("cannot escalate nested durable JSON lock mode")
                yield descriptors.get(resolved)
            else:
                with _initialization_lock(
                    resolved,
                    cross_process_lock=cross_process_lock,
                ) as root_descriptor:
                    descriptors[resolved] = root_descriptor
                    modes[resolved] = cross_process_lock
                    yield root_descriptor
        finally:
            if depth:
                depths[resolved] = depth
            else:
                depths.pop(resolved, None)
                descriptors.pop(resolved, None)
                modes.pop(resolved, None)


def _pinned_root_matches(data_root: Path, root_descriptor: int | None) -> bool:
    if os.name == "nt":
        # The initialization-lock context retains no-delete-sharing handles for
        # the full root chain on Windows.
        return True
    if root_descriptor is None:
        return False
    try:
        pinned = os.fstat(root_descriptor)
        current = os.stat(data_root, follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISDIR(pinned.st_mode)
        and stat.S_ISDIR(current.st_mode)
        and pinned.st_dev == current.st_dev
        and pinned.st_ino == current.st_ino
    )


def _validate_private_descriptor(
    descriptor: int,
    *,
    required_mode: int | None,
    maximum_bytes: int | None,
) -> os.stat_result:
    metadata = os.fstat(descriptor)
    if (
        _is_redirecting_entry(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or (maximum_bytes is not None and metadata.st_size > maximum_bytes)
    ):
        raise OSError("unsafe durable JSON file")
    if os.name == "posix":
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise OSError("unowned durable JSON file")
        if required_mode is not None and stat.S_IMODE(metadata.st_mode) != required_mode:
            raise OSError("broad durable JSON file")
    return metadata


def read_json(
    path: Path,
    default: T,
    *,
    parent_fd: int | None = None,
    maximum_bytes: int | None = None,
    required_mode: int | None = None,
    expected_type: type | None = None,
    require_existing: bool = False,
) -> T | Any:
    """Read JSON from path, returning default when the file is absent."""
    if parent_fd is not None:
        flags = (
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        try:
            descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            if require_existing:
                raise
            return default
        try:
            _validate_private_descriptor(
                descriptor,
                required_mode=required_mode,
                maximum_bytes=maximum_bytes,
            )
            chunks: list[bytes] = []
            remaining = (maximum_bytes + 1) if maximum_bytes is not None else None
            while remaining is None or remaining > 0:
                chunk = os.read(descriptor, 64 * 1024 if remaining is None else min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
            raw = b"".join(chunks)
            if maximum_bytes is not None and len(raw) > maximum_bytes:
                raise OSError("durable JSON file too large")
            payload = json.loads(raw.decode("utf-8"))
            if expected_type is not None and type(payload) is not expected_type:
                raise ValueError("durable JSON file has invalid top-level type")
            return payload
        finally:
            os.close(descriptor)
    try:
        descriptor = _open_readonly_no_follow(path)
    except FileNotFoundError:
        if require_existing:
            raise
        return default
    try:
        _validate_private_descriptor(
            descriptor,
            required_mode=required_mode,
            maximum_bytes=maximum_bytes,
        )
        chunks: list[bytes] = []
        remaining = (maximum_bytes + 1) if maximum_bytes is not None else None
        while remaining is None or remaining > 0:
            chunk = os.read(descriptor, 64 * 1024 if remaining is None else min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            if remaining is not None:
                remaining -= len(chunk)
        raw = b"".join(chunks)
        if maximum_bytes is not None and len(raw) > maximum_bytes:
            raise OSError("durable JSON file too large")
        payload = json.loads(raw.decode("utf-8"))
        if expected_type is not None and type(payload) is not expected_type:
            raise ValueError("durable JSON file has invalid top-level type")
        return payload
    finally:
        os.close(descriptor)


def read_json_guarded(
    path: Path,
    default: T,
    *,
    mutation_lock: bool = True,
    maximum_bytes: int | None = None,
    expected_type: type | None = None,
    required_mode: int | None = None,
    require_existing: bool = False,
) -> T | Any:
    """Read one durable JSON file through the same pinned root boundary as writes."""

    with _durable_mutation_lock(
        path.parent,
        cross_process_lock=mutation_lock,
    ) as root_descriptor:
        if not _pinned_root_matches(path.parent, root_descriptor):
            raise OSError("durable JSON root changed before read")
        with lock_for(path):
            payload = read_json(
                path,
                default,
                parent_fd=root_descriptor,
                maximum_bytes=maximum_bytes,
                required_mode=required_mode,
                expected_type=expected_type,
                require_existing=require_existing,
            )
        if not _pinned_root_matches(path.parent, root_descriptor):
            raise OSError("durable JSON root changed during read")
        return payload


def write_json_atomic(
    path: Path,
    payload: Any,
    *,
    mode: int | None = None,
    parent_fd: int | None = None,
    maximum_bytes: int | None = None,
) -> None:
    """Atomically write JSON with a unique temp filename beside the target.

    Windows can transiently deny ``os.replace``/``Path.replace`` while another
    local process (indexer, antivirus, file watcher) has a short-lived handle on
    the target. Keep the operation atomic, but retry briefly before surfacing the
    error so high-frequency dashboard writes do not fail spuriously.
    """
    serialized_bytes = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if maximum_bytes is not None and len(serialized_bytes) > maximum_bytes:
        raise ValueError("durable JSON payload too large")
    if parent_fd is None:
        path.parent.mkdir(parents=True, exist_ok=True)
    effective_mode = mode
    if effective_mode is None:
        try:
            metadata = (
                os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
                if parent_fd is not None
                else os.lstat(path)
            )
        except FileNotFoundError:
            effective_mode = 0o600
        else:
            effective_mode = (
                stat.S_IMODE(metadata.st_mode)
                if stat.S_ISREG(metadata.st_mode)
                else 0o600
            )
    if mode is not None:
        if parent_fd is not None and hasattr(os, "fchmod"):
            os.fchmod(parent_fd, 0o700)
            parent_state = os.fstat(parent_fd)
            if not stat.S_ISDIR(parent_state.st_mode) or stat.S_IMODE(parent_state.st_mode) != 0o700:
                raise OSError("durable JSON parent permissions invalid")
        else:
            path.parent.chmod(0o700)
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    committed = False
    try:
        descriptor = (
            os.open(tmp.name, flags, effective_mode, dir_fd=parent_fd)
            if parent_fd is not None
            else os.open(tmp, flags, effective_mode)
        )
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, effective_mode)
        offset = 0
        while offset < len(serialized_bytes):
            written = os.write(descriptor, serialized_bytes[offset:])
            if written <= 0:
                raise OSError("durable JSON temporary write incomplete")
            offset += written
        os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        verified = bytearray()
        while len(verified) <= len(serialized_bytes):
            chunk = os.read(descriptor, min(64 * 1024, len(serialized_bytes) + 1 - len(verified)))
            if not chunk:
                break
            verified.extend(chunk)
        if bytes(verified) != serialized_bytes:
            raise OSError("durable JSON temporary content changed")
        temp_state = _validate_private_descriptor(
            descriptor,
            required_mode=effective_mode,
            maximum_bytes=maximum_bytes,
        )
        named_state = (
            os.stat(tmp.name, dir_fd=parent_fd, follow_symlinks=False)
            if parent_fd is not None
            else os.lstat(tmp)
        )
        if (
            _is_redirecting_entry(named_state)
            or named_state.st_dev != temp_state.st_dev
            or named_state.st_ino != temp_state.st_ino
        ):
            raise OSError("durable JSON temporary identity changed")
        if os.name == "nt":
            os.close(descriptor)
            descriptor = -1
        delays = (0.01, 0.025, 0.05, 0.1)
        for attempt in range(len(delays) + 1):
            try:
                if parent_fd is not None:
                    os.replace(
                        tmp.name,
                        path.name,
                        src_dir_fd=parent_fd,
                        dst_dir_fd=parent_fd,
                    )
                else:
                    tmp.replace(path)
                committed = True
                break
            except PermissionError:
                if attempt == len(delays):
                    raise
                time.sleep(delays[attempt])
        if parent_fd is not None:
            os.fsync(parent_fd)
        committed_descriptor = (
            os.open(
                path.name,
                os.O_RDONLY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=parent_fd,
            )
            if parent_fd is not None
            else _open_readonly_no_follow(path)
        )
        try:
            committed_state = _validate_private_descriptor(
                committed_descriptor,
                required_mode=effective_mode,
                maximum_bytes=maximum_bytes,
            )
            if os.name != "nt" and (
                committed_state.st_dev != temp_state.st_dev
                or committed_state.st_ino != temp_state.st_ino
            ):
                raise JsonCommitVerificationError("durable JSON committed identity changed")
            os.lseek(committed_descriptor, 0, os.SEEK_SET)
            committed_raw = bytearray()
            while len(committed_raw) <= len(serialized_bytes):
                chunk = os.read(
                    committed_descriptor,
                    min(64 * 1024, len(serialized_bytes) + 1 - len(committed_raw)),
                )
                if not chunk:
                    break
                committed_raw.extend(chunk)
            if bytes(committed_raw) != serialized_bytes:
                raise JsonCommitVerificationError("durable JSON committed content changed")
        finally:
            os.close(committed_descriptor)
    except JsonCommitVerificationError:
        raise
    except Exception as exc:
        if committed:
            raise JsonCommitVerificationError(
                "durable JSON commit could not be verified"
            ) from exc
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not committed:
            try:
                if parent_fd is not None:
                    os.unlink(tmp.name, dir_fd=parent_fd)
                else:
                    tmp.unlink()
            except FileNotFoundError:
                pass


def update_json(
    path: Path,
    default: T,
    mutator: Callable[[T | Any], tuple[Any, R]],
    *,
    mutation_lock: bool = True,
    maximum_bytes: int | None = None,
    expected_type: type | None = None,
    required_mode: int | None = None,
    require_existing: bool = False,
) -> R:
    """Serialize a read-modify-write cycle for one JSON file.

    The mutator receives the decoded payload (or default if missing) and returns
    ``(new_payload, result)``. The new payload is written before result is
    returned. Installed durable roots also share the cross-process data mutation
    lock with migration operations. ``mutation_lock=False`` omits only that
    on-disk cross-process lock for the source development override; root
    component validation, process-local ordering, and pinned I/O remain active.
    Returning the original object (or
    ``NO_WRITE``) skips the disk write, which lets validation/not-found responses
    avoid reformatting files or
    bumping mtimes. JSON decode errors intentionally propagate to the caller so
    route handlers can preserve existing error semantics.
    """
    with _durable_mutation_lock(
        path.parent,
        cross_process_lock=mutation_lock,
    ) as root_descriptor:
        if not _pinned_root_matches(path.parent, root_descriptor):
            raise OSError("durable JSON root changed before mutation")
        with lock_for(path):
            current = read_json(
                path,
                default,
                parent_fd=root_descriptor,
                maximum_bytes=maximum_bytes,
                required_mode=required_mode,
                expected_type=expected_type,
                require_existing=require_existing,
            )
            new_payload, result = mutator(current)
            if new_payload is not NO_WRITE and new_payload is not current:
                if expected_type is not None and type(new_payload) is not expected_type:
                    raise ValueError("durable JSON payload has invalid top-level type")
                if not _pinned_root_matches(path.parent, root_descriptor):
                    raise OSError("durable JSON root changed before commit")
                write_json_atomic(
                    path,
                    new_payload,
                    mode=required_mode,
                    parent_fd=root_descriptor,
                    maximum_bytes=maximum_bytes,
                )
            if not _pinned_root_matches(path.parent, root_descriptor):
                raise OSError("durable JSON root changed during mutation")
            return result
