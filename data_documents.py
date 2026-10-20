"""Bounded private document I/O shared by current initialization and backups."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Mapping

from data_layout import (
    _open_directory_no_follow,
    _open_readonly_no_follow,
    _promote_seed_copy,
    _root_issue,
    _secure_directory,
    _temporary_seed_path,
    _windows_close_handle,
    _windows_open_directory_chain,
    _write_seed_temporary,
)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(document: Mapping | list) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _owner_only_regular_descriptor(descriptor: int) -> bool:
    """Validate a private published file without changing it during preview."""

    try:
        metadata = os.fstat(descriptor)
    except OSError:
        return False
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        return False
    if os.name == "posix":
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            return False
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            return False
    return True


def _pinned_target_matches(target: Path, root_descriptor: int | None) -> bool:
    if os.name == "nt":
        # The initialization lock retains a no-delete-sharing handle chain for
        # every target component on Windows until this check completes.
        return _root_issue(target, "target_root", allow_missing=False) is None
    if root_descriptor is None:
        return False
    try:
        pinned = os.fstat(root_descriptor)
        current = os.stat(target, follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISDIR(pinned.st_mode)
        and stat.S_ISDIR(current.st_mode)
        and pinned.st_dev == current.st_dev
        and pinned.st_ino == current.st_ino
    )


@contextmanager
def _guarded_mutation_directory(path: Path):
    if not _secure_directory(path):
        raise OSError("migration directory permissions could not be verified")
    if os.name == "nt":
        handles = _windows_open_directory_chain(path)
        try:
            yield None
        finally:
            for handle in reversed(handles):
                _windows_close_handle(handle)
        return
    descriptor = _open_directory_no_follow(path)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _read_exact_regular(path: Path, maximum: int) -> bytes:
    descriptor = _open_readonly_no_follow(path)
    try:
        metadata = os.fstat(descriptor)
        if (
            not _owner_only_regular_descriptor(descriptor)
            or metadata.st_size > maximum
        ):
            raise OSError("invalid published file")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum:
            raise OSError("published file too large")
        return raw
    finally:
        os.close(descriptor)


def _read_exact_regular_at(
    path: Path,
    maximum: int,
    *,
    parent_fd: int | None,
) -> bytes:
    if parent_fd is None:
        return _read_exact_regular(path, maximum)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptor = os.open(path.name, flags, dir_fd=parent_fd)
    try:
        metadata = os.fstat(descriptor)
        if (
            not _owner_only_regular_descriptor(descriptor)
            or metadata.st_size > maximum
        ):
            raise OSError("invalid published file")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum:
            raise OSError("published file too large")
        return raw
    finally:
        os.close(descriptor)


def _publish_raw_missing(
    destination: Path,
    raw: bytes,
    *,
    parent_fd: int | None,
    maximum: int,
    on_published=None,
) -> None:
    temp_path = _temporary_seed_path(destination)
    temp_present = True
    try:
        _write_seed_temporary(temp_path, raw, data_root_fd=parent_fd)
        _promote_seed_copy(temp_path, destination, data_root_fd=parent_fd)
        if on_published is not None:
            on_published()
        if parent_fd is not None:
            os.fsync(parent_fd)
        if parent_fd is not None and os.unlink in os.supports_dir_fd:
            os.unlink(temp_path.name, dir_fd=parent_fd)
        else:
            temp_path.unlink()
        temp_present = False
        if parent_fd is not None:
            os.fsync(parent_fd)
        if _read_exact_regular_at(destination, maximum, parent_fd=parent_fd) != raw:
            raise OSError("published file verification failed")
    finally:
        if temp_present:
            try:
                if parent_fd is not None and os.unlink in os.supports_dir_fd:
                    os.unlink(temp_path.name, dir_fd=parent_fd)
                else:
                    temp_path.unlink()
            except FileNotFoundError:
                pass
