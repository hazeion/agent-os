"""Validated snapshots of Mentat's durable private Agent Console unit.

The unit is deliberately limited to retained run history, a SQLite snapshot
containing only rows reachable from that history, and the ready blobs those
rows reference.  Runtime scratch and future private credentials are outside
this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import shutil
from functools import lru_cache
from tempfile import TemporaryDirectory
from typing import Iterable

from agent_run_history import (
    DEFAULT_RETENTION,
    LEGACY_SCHEMA_VERSIONS,
    SCHEMA_VERSION as HISTORY_SCHEMA_VERSION,
    _hydrate,
    summarize_run,
)
from mentat_db import MIGRATIONS, SCHEMA_VERSION as DATABASE_SCHEMA_VERSION
from private_state import blobs_root, console_root, database_path, ensure_console_root, history_path


MAX_HISTORY_BYTES = 4 * 1024 * 1024
MAX_DATABASE_BYTES = 32 * 1024 * 1024
MAX_BLOB_BYTES = 10 * 1024 * 1024
MAX_BLOBS = 100
MAX_PRIVATE_UNIT_BYTES = 64 * 1024 * 1024
STORAGE_KEY_RE = re.compile(r"([0-9a-f]{2})/([0-9a-f]{64})\Z")
RUN_ID_RE = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")


class PrivateConsoleUnitError(OSError):
    """A private snapshot is missing, unsafe, inconsistent, or unsupported."""


@dataclass(frozen=True)
class PrivateBlob:
    storage_key: str
    raw: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.raw).hexdigest()


@dataclass(frozen=True)
class PrivateConsoleUnit:
    history_raw: bytes
    database_raw: bytes
    blobs: tuple[PrivateBlob, ...]

    @property
    def run_count(self) -> int:
        return len(_history_run_ids(self.history_raw))


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def _safe_regular(path: Path, *, maximum: int, required_mode: int = 0o600) -> bytes:
    lexical = os.lstat(path)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(lexical.st_mode) or (
        reparse_flag and getattr(lexical, "st_file_attributes", 0) & reparse_flag
    ):
        raise PrivateConsoleUnitError("private_unit_unsafe")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > maximum:
            raise PrivateConsoleUnitError("private_unit_unsafe")
        if os.name == "posix" and stat.S_IMODE(before.st_mode) != required_mode:
            raise PrivateConsoleUnitError("private_unit_permissions_invalid")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        raw = b"".join(chunks)
        if (
            len(raw) > maximum
            or len(raw) != before.st_size
            or (lexical.st_dev, lexical.st_ino) != (before.st_dev, before.st_ino)
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise PrivateConsoleUnitError("private_unit_changed")
        return raw
    finally:
        os.close(descriptor)


def _history_run_ids(raw: bytes) -> tuple[str, ...]:
    if len(raw) > MAX_HISTORY_BYTES:
        raise PrivateConsoleUnitError("private_history_too_large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PrivateConsoleUnitError("private_history_invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "runs"}:
        raise PrivateConsoleUnitError("private_history_invalid")
    if payload["schema_version"] != HISTORY_SCHEMA_VERSION or not isinstance(payload["runs"], list):
        raise PrivateConsoleUnitError("private_history_unsupported")
    identifiers: list[str] = []
    for run in payload["runs"]:
        if not isinstance(run, dict) or not RUN_ID_RE.fullmatch(str(run.get("id") or "")):
            raise PrivateConsoleUnitError("private_history_invalid")
        identifier = str(run["id"])
        if identifier in identifiers:
            raise PrivateConsoleUnitError("private_history_invalid")
        identifiers.append(identifier)
    if raw != _canonical_json(payload):
        # Persisted history uses pretty JSON today; normalize it in the archive
        # while still rejecting non-JSON or unsupported content.
        return tuple(identifiers)
    return tuple(identifiers)


def _history_reference_pairs(raw: bytes) -> set[tuple[str, str]]:
    payload = json.loads(raw.decode("utf-8"))
    references: set[tuple[str, str]] = set()
    for run in payload["runs"]:
        run_id = str(run["id"])
        for field in ("attachments", "artifacts"):
            values = run.get(field, [])
            if not isinstance(values, list):
                raise PrivateConsoleUnitError("private_history_invalid")
            for item in values:
                attachment_id = str(item.get("id") or "") if isinstance(item, dict) else ""
                if not re.fullmatch(r"attachment_[0-9a-f]{32}", attachment_id):
                    raise PrivateConsoleUnitError("private_history_invalid")
                references.add((run_id, attachment_id))
    return references


def _normalized_history(path: Path) -> bytes:
    raw = _safe_regular(path, maximum=MAX_HISTORY_BYTES)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PrivateConsoleUnitError("private_history_invalid") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") not in (LEGACY_SCHEMA_VERSIONS | {HISTORY_SCHEMA_VERSION})
        or not isinstance(payload.get("runs"), list)
    ):
        raise PrivateConsoleUnitError("private_history_unsupported")
    runs = [
        run
        for item in payload["runs"]
        if isinstance(item, dict)
        if (run := _hydrate(item)) is not None
    ]
    runs.sort(
        key=lambda run: (str(run.get("created_at") or ""), str(run.get("id") or "")),
        reverse=True,
    )
    runs = runs[:DEFAULT_RETENTION]
    if payload["runs"] and not runs:
        raise PrivateConsoleUnitError("private_history_invalid")
    summaries = [summarize_run(run) for run in runs]
    summaries.sort(key=lambda run: (str(run.get("created_at") or ""), str(run.get("id") or "")), reverse=True)
    return _canonical_json({"schema_version": HISTORY_SCHEMA_VERSION, "runs": summaries})


def _empty_history() -> bytes:
    return _canonical_json({"schema_version": HISTORY_SCHEMA_VERSION, "runs": []})


def empty_private_console_unit() -> PrivateConsoleUnit:
    """Return the canonical empty unit without touching operator storage."""

    with TemporaryDirectory(prefix="mentat-private-empty-") as temporary:
        database = Path(temporary) / "mentat.sqlite3"
        _initialize_database(database)
        rows = _validate_and_filter_database(database, ())
        if rows:
            raise PrivateConsoleUnitError("private_database_invalid")
        return PrivateConsoleUnit(
            history_raw=_empty_history(),
            database_raw=database.read_bytes(),
            blobs=(),
        )


def _initialize_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        for _version, script in MIGRATIONS:
            connection.executescript(script)
        for version, _script in MIGRATIONS:
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                (version,),
            )
        connection.commit()
    finally:
        connection.close()
    if os.name != "nt":
        path.chmod(0o600)


def _sqlite_backup(
    source: Path | None,
    destination: Path,
    *,
    copy_source: bool = False,
) -> None:
    if source is None:
        _initialize_database(destination)
        return
    source_raw = _safe_regular(source, maximum=MAX_DATABASE_BYTES)
    before = source.lstat()
    wal = Path(f"{source}-wal")
    wal_raw = (
        _safe_regular(wal, maximum=MAX_PRIVATE_UNIT_BYTES)
        if copy_source and os.path.lexists(os.fspath(wal))
        else None
    )
    shm = Path(f"{source}-shm")
    shm_raw = (
        _safe_regular(shm, maximum=MAX_PRIVATE_UNIT_BYTES)
        if copy_source and os.path.lexists(os.fspath(shm))
        else None
    )
    source_for_sqlite = source
    source_temporary = None
    if copy_source:
        source_temporary = TemporaryDirectory(prefix="mentat-sqlite-source-")
        source_for_sqlite = Path(source_temporary.name) / source.name
        _write_private_file(source_for_sqlite, source_raw)
        if wal_raw is not None:
            _write_private_file(Path(f"{source_for_sqlite}-wal"), wal_raw)
    source_connection = None
    destination_connection = None
    try:
        source_connection = sqlite3.connect(f"file:{source_for_sqlite}?mode=ro", uri=True)
        destination_connection = sqlite3.connect(destination)
        source_connection.backup(destination_connection)
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()
        if source_temporary is not None:
            source_temporary.cleanup()
    after_raw = _safe_regular(source, maximum=MAX_DATABASE_BYTES)
    after = source.lstat()
    if source.is_symlink() or (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
    ) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ) or after_raw != source_raw:
        raise PrivateConsoleUnitError("private_database_changed")
    if wal_raw is not None and _safe_regular(wal, maximum=MAX_PRIVATE_UNIT_BYTES) != wal_raw:
        raise PrivateConsoleUnitError("private_database_changed")
    if shm_raw is not None and _safe_regular(shm, maximum=MAX_PRIVATE_UNIT_BYTES) != shm_raw:
        raise PrivateConsoleUnitError("private_database_changed")
    if wal_raw is None and os.path.lexists(os.fspath(wal)):
        raise PrivateConsoleUnitError("private_database_changed")
    if shm_raw is None and os.path.lexists(os.fspath(shm)):
        raise PrivateConsoleUnitError("private_database_changed")
    if os.name != "nt":
        destination.chmod(0o600)


def _schema_signature(connection: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            str(row[0]),
            str(row[1]),
            str(row[2]),
            re.sub(r"\s+", "", str(row[3] or "")),
        )
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_autoindex_%' ORDER BY type, name"
        )
    )


@lru_cache(maxsize=1)
def _expected_schema_signature() -> tuple[tuple[str, str, str, str], ...]:
    with TemporaryDirectory(prefix="mentat-schema-signature-") as temporary:
        database = Path(temporary) / "mentat.sqlite3"
        _initialize_database(database)
        connection = sqlite3.connect(database)
        try:
            return _schema_signature(connection)
        finally:
            connection.close()


def _validate_and_filter_database(path: Path, run_ids: Iterable[str]) -> tuple[tuple[str, str, int], ...]:
    retained = tuple(run_ids)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise PrivateConsoleUnitError("private_database_invalid")
        versions = [int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")]
        if not versions or max(versions) != DATABASE_SCHEMA_VERSION:
            raise PrivateConsoleUnitError("private_database_unsupported")
        if _schema_signature(connection) != _expected_schema_signature():
            raise PrivateConsoleUnitError("private_database_schema_invalid")
        placeholders = ",".join("?" for _ in retained)
        if retained:
            connection.execute(
                f"DELETE FROM run_attachments WHERE run_id NOT IN ({placeholders})",
                retained,
            )
        else:
            connection.execute("DELETE FROM run_attachments")
        connection.execute(
            "DELETE FROM attachments WHERE id NOT IN (SELECT attachment_id FROM run_attachments)"
        )
        connection.execute(
            "DELETE FROM blobs WHERE id NOT IN (SELECT blob_id FROM attachments WHERE blob_id IS NOT NULL)"
        )
        dangling = connection.execute(
            "SELECT COUNT(*) FROM run_attachments r "
            "LEFT JOIN attachments a ON a.id = r.attachment_id "
            "LEFT JOIN blobs b ON b.id = a.blob_id "
            "WHERE a.id IS NULL OR b.id IS NULL OR a.state != 'attached' OR b.state != 'ready'"
        ).fetchone()[0]
        if dangling:
            raise PrivateConsoleUnitError("private_references_invalid")
        rows = tuple(
            (str(row[0]), str(row[1]), int(row[2]))
            for row in connection.execute(
                "SELECT storage_key, sha256, byte_size FROM blobs ORDER BY storage_key"
            )
        )
        if len(rows) > MAX_BLOBS:
            raise PrivateConsoleUnitError("private_blob_count_exceeded")
        connection.commit()
        connection.execute("VACUUM")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PrivateConsoleUnitError("private_database_invalid")
    except sqlite3.Error as exc:
        raise PrivateConsoleUnitError("private_database_invalid") from exc
    finally:
        connection.close()
    return rows


def _inspect_filtered_database(path: Path, run_ids: Iterable[str]) -> tuple[tuple[str, str, int], ...]:
    retained = set(run_ids)
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PrivateConsoleUnitError("private_database_invalid")
        versions = [int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")]
        if not versions or max(versions) != DATABASE_SCHEMA_VERSION:
            raise PrivateConsoleUnitError("private_database_unsupported")
        if _schema_signature(connection) != _expected_schema_signature():
            raise PrivateConsoleUnitError("private_database_schema_invalid")
        database_runs = {str(row[0]) for row in connection.execute("SELECT DISTINCT run_id FROM run_attachments")}
        if not database_runs.issubset(retained):
            raise PrivateConsoleUnitError("private_database_not_filtered")
        extra_attachments = connection.execute(
            "SELECT COUNT(*) FROM attachments WHERE id NOT IN (SELECT attachment_id FROM run_attachments)"
        ).fetchone()[0]
        extra_blobs = connection.execute(
            "SELECT COUNT(*) FROM blobs WHERE id NOT IN (SELECT blob_id FROM attachments WHERE blob_id IS NOT NULL)"
        ).fetchone()[0]
        dangling = connection.execute(
            "SELECT COUNT(*) FROM run_attachments r "
            "LEFT JOIN attachments a ON a.id = r.attachment_id "
            "LEFT JOIN blobs b ON b.id = a.blob_id "
            "WHERE a.id IS NULL OR b.id IS NULL OR a.state != 'attached' OR b.state != 'ready'"
        ).fetchone()[0]
        if extra_attachments or extra_blobs or dangling:
            raise PrivateConsoleUnitError("private_database_not_filtered")
        rows = tuple(
            (str(row[0]), str(row[1]), int(row[2]))
            for row in connection.execute(
                "SELECT storage_key, sha256, byte_size FROM blobs ORDER BY storage_key"
            )
        )
        if len(rows) > MAX_BLOBS:
            raise PrivateConsoleUnitError("private_blob_count_exceeded")
        return rows
    except sqlite3.Error as exc:
        raise PrivateConsoleUnitError("private_database_invalid") from exc
    finally:
        connection.close()


def _blob_path(root: Path, storage_key: str) -> Path:
    match = STORAGE_KEY_RE.fullmatch(storage_key)
    if match is None or match.group(1) != match.group(2)[:2]:
        raise PrivateConsoleUnitError("private_blob_key_invalid")
    path = root / match.group(1) / match.group(2)
    if path.parent.is_symlink() or path.is_symlink():
        raise PrivateConsoleUnitError("private_blob_unsafe")
    return path


def capture_private_console_unit(
    data_root: Path,
    *,
    source_console: Path | None = None,
    copy_sqlite_source: bool = True,
) -> PrivateConsoleUnit:
    """Capture one validated, filtered private unit while the caller holds its lock."""

    requested = console_root(data_root)
    if source_console is None and not os.path.lexists(os.fspath(requested)):
        return empty_private_console_unit()
    canonical = ensure_console_root(data_root) if source_console is None else requested
    source = Path(source_console) if source_console is not None else canonical
    if source.is_symlink() or (source.exists() and not source.is_dir()):
        raise PrivateConsoleUnitError("private_console_unsafe")
    history = source / history_path(data_root).name
    history_raw = _normalized_history(history) if history.exists() else _empty_history()
    run_ids = _history_run_ids(history_raw)
    history_payload = json.loads(history_raw.decode("utf-8"))
    history_raw = _canonical_json(history_payload)
    database = source / database_path(data_root).name
    database_source = database if database.exists() else None
    with TemporaryDirectory(prefix="mentat-console-capture-") as temporary:
        snapshot_path = Path(temporary) / "mentat.sqlite3"
        _sqlite_backup(database_source, snapshot_path, copy_source=copy_sqlite_source)
        blob_rows = _validate_and_filter_database(snapshot_path, run_ids)
        connection = sqlite3.connect(f"file:{snapshot_path}?mode=ro", uri=True)
        try:
            database_references = {
                (str(row[0]), str(row[1]))
                for row in connection.execute("SELECT run_id, attachment_id FROM run_attachments")
            }
        finally:
            connection.close()
        if database_references != _history_reference_pairs(history_raw):
            raise PrivateConsoleUnitError("private_history_database_mismatch")
        database_raw = _safe_regular(snapshot_path, maximum=MAX_DATABASE_BYTES)
    source_blobs = source / "blobs" / "sha256"
    blobs: list[PrivateBlob] = []
    for storage_key, expected_digest, expected_size in blob_rows:
        raw = _safe_regular(_blob_path(source_blobs, storage_key), maximum=MAX_BLOB_BYTES)
        if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_digest:
            raise PrivateConsoleUnitError("private_blob_content_invalid")
        blobs.append(PrivateBlob(storage_key=storage_key, raw=raw))
    if len(history_raw) + len(database_raw) + sum(len(blob.raw) for blob in blobs) > MAX_PRIVATE_UNIT_BYTES:
        raise PrivateConsoleUnitError("private_unit_too_large")
    return PrivateConsoleUnit(history_raw=history_raw, database_raw=database_raw, blobs=tuple(blobs))


def validate_private_console_stage_inventory(
    data_root: Path,
    stage: Path,
    unit: PrivateConsoleUnit,
    *,
    allow_canonical: bool = False,
) -> None:
    """Require a staging tree to contain only the exact materialized unit."""

    private = (Path(data_root) / "private").absolute()
    root = Path(stage).absolute()
    if (
        root.parent != private
        or (root.name == "console" and not allow_canonical)
        or root.is_symlink()
        or not root.is_dir()
    ):
        raise PrivateConsoleUnitError("private_stage_inventory_invalid")
    root_details = os.lstat(root)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        (reparse_flag and getattr(root_details, "st_file_attributes", 0) & reparse_flag)
        or (os.name == "posix" and stat.S_IMODE(root_details.st_mode) != 0o700)
    ):
        raise PrivateConsoleUnitError("private_stage_inventory_invalid")
    expected_files = {history_path(data_root).name, database_path(data_root).name}
    expected_directories = {"blobs", "blobs/sha256"}
    for blob in unit.blobs:
        match = STORAGE_KEY_RE.fullmatch(blob.storage_key)
        if match is None:
            raise PrivateConsoleUnitError("private_stage_inventory_invalid")
        expected_directories.add(f"blobs/sha256/{match.group(1)}")
        expected_files.add(f"blobs/sha256/{match.group(1)}/{match.group(2)}")
    actual_files: set[str] = set()
    actual_directories: set[str] = set()
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            path = current_path / name
            details = os.lstat(path)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if (
                stat.S_ISLNK(details.st_mode)
                or (reparse_flag and getattr(details, "st_file_attributes", 0) & reparse_flag)
                or not stat.S_ISDIR(details.st_mode)
                or (os.name == "posix" and stat.S_IMODE(details.st_mode) != 0o700)
            ):
                raise PrivateConsoleUnitError("private_stage_inventory_invalid")
            actual_directories.add(path.relative_to(root).as_posix())
        for name in files:
            path = current_path / name
            details = os.lstat(path)
            reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            if (
                stat.S_ISLNK(details.st_mode)
                or (reparse_flag and getattr(details, "st_file_attributes", 0) & reparse_flag)
                or not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or (os.name == "posix" and stat.S_IMODE(details.st_mode) != 0o600)
            ):
                raise PrivateConsoleUnitError("private_stage_inventory_invalid")
            actual_files.add(path.relative_to(root).as_posix())
    if not actual_files.issubset(expected_files) or not actual_directories.issubset(expected_directories):
        raise PrivateConsoleUnitError("private_stage_inventory_invalid")
    if actual_files != expected_files or actual_directories != expected_directories:
        raise PrivateConsoleUnitError("private_stage_incomplete")


def validate_private_console_unit(unit: PrivateConsoleUnit) -> PrivateConsoleUnit:
    """Validate archive-supplied bytes and their complete relationship graph."""

    if len(unit.history_raw) + len(unit.database_raw) + sum(len(blob.raw) for blob in unit.blobs) > MAX_PRIVATE_UNIT_BYTES:
        raise PrivateConsoleUnitError("private_unit_too_large")
    run_ids = _history_run_ids(unit.history_raw)
    with TemporaryDirectory(prefix="mentat-private-validate-") as temporary:
        database = Path(temporary) / "mentat.sqlite3"
        database.write_bytes(unit.database_raw)
        if os.name != "nt":
            database.chmod(0o600)
        rows = _inspect_filtered_database(database, run_ids)
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            database_references = {
                (str(row[0]), str(row[1]))
                for row in connection.execute("SELECT run_id, attachment_id FROM run_attachments")
            }
        finally:
            connection.close()
        if database_references != _history_reference_pairs(unit.history_raw):
            raise PrivateConsoleUnitError("private_history_database_mismatch")
    expected = {key: (digest, size) for key, digest, size in rows}
    supplied = {blob.storage_key: blob for blob in unit.blobs}
    if len(supplied) != len(unit.blobs) or set(supplied) != set(expected):
        raise PrivateConsoleUnitError("private_blob_inventory_invalid")
    for key, blob in supplied.items():
        digest, size = expected[key]
        if len(blob.raw) != size or blob.sha256 != digest:
            raise PrivateConsoleUnitError("private_blob_content_invalid")
    return unit


def private_console_unit_digest(unit: PrivateConsoleUnit) -> str:
    validate_private_console_unit(unit)
    with TemporaryDirectory(prefix="mentat-private-identity-") as temporary:
        database = Path(temporary) / "mentat.sqlite3"
        database.write_bytes(unit.database_raw)
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            logical_database = "\n".join(connection.iterdump()).encode("utf-8")
        finally:
            connection.close()
    identity = {
        "history": hashlib.sha256(unit.history_raw).hexdigest(),
        "database": hashlib.sha256(logical_database).hexdigest(),
        "blobs": [(blob.storage_key, blob.sha256, len(blob.raw)) for blob in unit.blobs],
    }
    return hashlib.sha256(_canonical_json(identity)).hexdigest()


def _write_private_file(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise PrivateConsoleUnitError("private_stage_write_failed")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def materialize_private_console_unit(
    data_root: Path,
    unit: PrivateConsoleUnit,
    destination: Path,
) -> Path:
    """Publish a complete unit into one missing owner-only staging directory."""

    validate_private_console_unit(unit)
    private = Path(data_root) / "private"
    if private.is_symlink() or not private.is_dir():
        raise PrivateConsoleUnitError("private_root_unsafe")
    destination = Path(destination)
    if destination.parent != private or os.path.lexists(os.fspath(destination)):
        raise PrivateConsoleUnitError("private_stage_conflict")
    destination.mkdir(mode=0o700)
    try:
        _write_private_file(destination / history_path(data_root).name, unit.history_raw)
        _write_private_file(destination / database_path(data_root).name, unit.database_raw)
        blob_root = destination / "blobs" / "sha256"
        blob_root.mkdir(parents=True, mode=0o700)
        if os.name != "nt":
            (destination / "blobs").chmod(0o700)
            blob_root.chmod(0o700)
        for blob in unit.blobs:
            path = _blob_path(blob_root, blob.storage_key)
            path.parent.mkdir(mode=0o700, exist_ok=True)
            if os.name != "nt":
                path.parent.chmod(0o700)
            _write_private_file(path, blob.raw)
        staged_unit = PrivateConsoleUnit(
            history_raw=_safe_regular(destination / history_path(data_root).name, maximum=MAX_HISTORY_BYTES),
            database_raw=_safe_regular(destination / database_path(data_root).name, maximum=MAX_DATABASE_BYTES),
            blobs=tuple(
                PrivateBlob(
                    storage_key=blob.storage_key,
                    raw=_safe_regular(_blob_path(blob_root, blob.storage_key), maximum=MAX_BLOB_BYTES),
                )
                for blob in unit.blobs
            ),
        )
        validate_private_console_unit(staged_unit)
        if private_console_unit_digest(staged_unit) != private_console_unit_digest(unit):
            raise PrivateConsoleUnitError("private_stage_verification_failed")
        if os.name == "posix":
            parent_descriptor = os.open(private, os.O_RDONLY)
            try:
                os.fsync(parent_descriptor)
            finally:
                os.close(parent_descriptor)
        return destination
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def remove_private_console_tree(data_root: Path, path: Path) -> None:
    """Remove only a validated direct private-root restore staging tree."""

    private = (Path(data_root) / "private").absolute()
    candidate = Path(path).absolute()
    if candidate.parent != private or candidate.name == "console" or candidate.is_symlink():
        raise PrivateConsoleUnitError("private_stage_unsafe")
    if candidate.exists():
        for descendant in candidate.rglob("*"):
            if descendant.is_symlink():
                raise PrivateConsoleUnitError("private_stage_unsafe")
        shutil.rmtree(candidate)
