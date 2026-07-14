"""Small SQLite foundation for private, project-owned Mentat runtime state."""

from __future__ import annotations

import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DATABASE_NAME = "mentat.sqlite3"
SCHEMA_VERSION = 1


MIGRATIONS: tuple[tuple[int, str], ...] = (
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS blobs (
            id TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL UNIQUE,
            storage_key TEXT NOT NULL UNIQUE,
            byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
            state TEXT NOT NULL CHECK (state IN ('ready', 'deleting', 'missing')),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            delete_attempts INTEGER NOT NULL DEFAULT 0 CHECK (delete_attempts >= 0)
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id TEXT PRIMARY KEY,
            blob_id TEXT REFERENCES blobs(id) ON DELETE RESTRICT,
            original_name TEXT NOT NULL,
            mime_type TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('image', 'text')),
            state TEXT NOT NULL CHECK (
                state IN (
                    'uploading', 'staged', 'attached', 'orphaned',
                    'pending_delete', 'deleting', 'missing'
                )
            ),
            byte_size INTEGER NOT NULL DEFAULT 0 CHECK (byte_size >= 0),
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            expires_at REAL,
            delete_after REAL
        );

        CREATE TABLE IF NOT EXISTS run_attachments (
            run_id TEXT NOT NULL,
            attachment_id TEXT NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
            direction TEXT NOT NULL CHECK (direction IN ('input', 'output')),
            ordinal INTEGER NOT NULL DEFAULT 0 CHECK (ordinal >= 0),
            created_at REAL NOT NULL,
            PRIMARY KEY (run_id, attachment_id, direction)
        );

        CREATE INDEX IF NOT EXISTS idx_attachments_state_expiry
            ON attachments(state, expires_at, delete_after);
        CREATE INDEX IF NOT EXISTS idx_attachments_blob
            ON attachments(blob_id);
        CREATE INDEX IF NOT EXISTS idx_run_attachments_attachment
            ON run_attachments(attachment_id);
        CREATE INDEX IF NOT EXISTS idx_run_attachments_run
            ON run_attachments(run_id);
        """,
    ),
)


class MentatDatabaseError(RuntimeError):
    """Raised when Mentat's private database boundary is unsafe."""


def runtime_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "runtime"


def database_path(data_dir: Path) -> Path:
    return runtime_dir(data_dir) / DATABASE_NAME


def _chmod(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode, follow_symlinks=False)


def ensure_private_runtime_dir(data_dir: Path) -> Path:
    """Create and validate the owner-only runtime directory without symlinks."""
    root_path = Path(data_dir)
    if root_path.is_symlink():
        raise MentatDatabaseError("Mentat data root must not be a symlink")
    root_path.mkdir(parents=True, exist_ok=True)
    root = root_path.resolve(strict=True)
    if not root.is_dir():
        raise MentatDatabaseError("Mentat data root is not a directory")

    target = root_path / "runtime"
    if target.is_symlink():
        raise MentatDatabaseError("Mentat runtime directory must not be a symlink")
    target.mkdir(mode=0o700, exist_ok=True)
    resolved = target.resolve(strict=True)
    if resolved.parent != root or not resolved.is_dir():
        raise MentatDatabaseError("Mentat runtime directory escapes the data root")
    _chmod(resolved, 0o700)
    return resolved


def _validate_database_file(path: Path, runtime: Path) -> None:
    if path.is_symlink():
        raise MentatDatabaseError("Mentat database must not be a symlink")
    try:
        details = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISREG(details.st_mode) or path.resolve(strict=True).parent != runtime:
        raise MentatDatabaseError("Mentat database path is not a safe regular file")


def _secure_database_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            _chmod(candidate, 0o600)
        except OSError:
            continue


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
    )
    applied = {
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
    }
    if applied and max(applied) > SCHEMA_VERSION:
        raise MentatDatabaseError("Mentat database schema is newer than this application")
    for version, script in MIGRATIONS:
        if version in applied:
            continue
        connection.executescript(script)
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, time.time()),
        )
    connection.commit()


def connect(data_dir: Path) -> sqlite3.Connection:
    """Open a migrated SQLite connection with Mentat's local concurrency defaults."""
    runtime = ensure_private_runtime_dir(data_dir)
    path = runtime / DATABASE_NAME
    _validate_database_file(path, runtime)
    if not path.exists():
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
    _validate_database_file(path, runtime)
    _chmod(path, 0o600)
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        migrate(connection)
        _secure_database_files(path)
        return connection
    except Exception:
        connection.close()
        raise


@contextmanager
def transaction(connection: sqlite3.Connection, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """Run a transaction, rolling it back when the caller raises."""
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def schema_version(data_dir: Path) -> int:
    connection = connect(data_dir)
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0)
    finally:
        connection.close()
