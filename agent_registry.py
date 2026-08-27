"""Durable Mentat-owned Agent identities and private runtime bindings."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from tempfile import TemporaryDirectory
from typing import Callable, Iterable, Mapping

from agent_runtime import MentatAgent, RuntimeContext
from mentat_db import (
    AGENT_REGISTRY_AUTHORITY_CONTRACT,
    LEGACY_AGENT_REGISTRY_DATABASE_NAME,
    MentatDatabaseError,
    MIGRATIONS,
    SCHEMA_VERSION as DATABASE_SCHEMA_VERSION,
    connect as connect_database,
)
from private_state import console_root, ensure_console_root


REGISTRY_DATABASE_NAME = LEGACY_AGENT_REGISTRY_DATABASE_NAME
REGISTRY_SCHEMA_VERSION = 1
MAX_AGENTS = 128
MAX_LEGACY_REGISTRY_BYTES = 4 * 1024 * 1024
DIRECT_AGENT_ROLE = "direct"
DIRECT_AGENT_ID = "agent_direct"
DIRECT_RUNTIME_CONFIG_ID = "runtime_config_direct"
DIRECT_RUNTIME_TYPE = "codex"
DIRECT_RUNTIME_AGENT_REF = "default"
DIRECT_AGENT_CAPABILITIES = (
    "run.events",
    "run.message",
    "run.start",
    "run.status",
    "run.stop",
)

_SCHEMA = """
CREATE TABLE registry_schema (
    version INTEGER PRIMARY KEY,
    applied_at REAL NOT NULL
);
CREATE TABLE agent_runtime_configs (
    id TEXT PRIMARY KEY,
    runtime_type TEXT NOT NULL,
    runtime_agent_ref TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (runtime_type, runtime_agent_ref)
);
CREATE TABLE mentat_agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    runtime_config_id TEXT NOT NULL UNIQUE
        REFERENCES agent_runtime_configs(id) ON DELETE RESTRICT,
    capabilities_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX idx_mentat_agents_name
    ON mentat_agents(name COLLATE NOCASE, id);
"""


class AgentRegistryError(RuntimeError):
    """A bounded Agent registry failure safe for adapter-level handling."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class AgentRegistryUnavailableError(AgentRegistryError):
    """The registry could not be opened or locked for an ordinary operation."""


class AgentRegistryValidationError(AgentRegistryError):
    """The requested Agent or runtime binding is invalid."""


class AgentRegistryConflict(AgentRegistryError):
    """The requested Agent identity or runtime binding already exists."""


class AgentRegistryLimitError(AgentRegistryError):
    """The bounded local Agent registry is full."""


@dataclass(frozen=True)
class RuntimeBinding:
    id: str
    runtime_type: str
    runtime_agent_ref: str
    revision: int


@dataclass(frozen=True)
class CanonicalAgentRecord:
    """The safe identity metadata needed by Conversation projections."""

    agent: MentatAgent
    revision: int
    system_role: str | None


@dataclass(frozen=True)
class AgentAuthorityReceipt:
    source_kind: str
    source_sha256: str
    source_agent_count: int
    cutover_at: float


@dataclass(frozen=True)
class LegacyAgentRecord:
    agent: MentatAgent
    binding: RuntimeBinding
    agent_created_at: float
    agent_updated_at: float
    config_created_at: float
    config_updated_at: float


@dataclass(frozen=True)
class LegacyRegistrySnapshot:
    raw: bytes
    sha256: str
    source_binding: str
    records: tuple[LegacyAgentRecord, ...]

    @property
    def agents(self) -> tuple[MentatAgent, ...]:
        return tuple(record.agent for record in self.records)


def _legacy_record_digest(records: Iterable[LegacyAgentRecord]) -> str:
    payload = [
        {
            "agent_id": record.agent.id,
            "name": record.agent.name,
            "runtime_config_id": record.binding.id,
            "capabilities": sorted(record.agent.capabilities),
            "agent_created_at": record.agent_created_at,
            "agent_updated_at": record.agent_updated_at,
            "runtime_type": record.binding.runtime_type,
            "runtime_agent_ref": record.binding.runtime_agent_ref,
            "config_created_at": record.config_created_at,
            "config_updated_at": record.config_updated_at,
        }
        for record in records
    ]
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def registry_database_path(data_dir: Path) -> Path:
    """Return the retired standalone-registry path without creating it."""

    return console_root(Path(data_dir)) / REGISTRY_DATABASE_NAME


def _secure_file(
    path: Path,
    *,
    parent: Path,
    require_mode: bool = True,
) -> tuple[int, int] | None:
    try:
        details = path.lstat()
    except FileNotFoundError:
        return None
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if (
        stat.S_ISLNK(details.st_mode)
        or bool(getattr(details, "st_file_attributes", 0) & reparse)
        or not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or (os.name == "posix" and details.st_uid != os.getuid())
        or path.parent.resolve() != parent.resolve()
    ):
        raise AgentRegistryError("agent_registry.unsafe")
    if require_mode and os.name != "nt" and stat.S_IMODE(details.st_mode) != 0o600:
        raise AgentRegistryError("agent_registry.unsafe")
    return int(details.st_dev), int(details.st_ino)


def _database_files(path: Path) -> tuple[Path, Path, Path]:
    return path, Path(f"{path}-wal"), Path(f"{path}-shm")


def _reject_unrecognized_database_artifacts(path: Path, *, parent: Path) -> None:
    allowed = {candidate.name for candidate in _database_files(path)}
    prefix = f"{path.name}-"
    try:
        names = {entry.name for entry in os.scandir(parent)}
    except FileNotFoundError:
        return
    except OSError as exc:
        raise AgentRegistryUnavailableError("agent_registry.unavailable") from exc
    if any(name.startswith(prefix) and name not in allowed for name in names):
        raise AgentRegistryError("agent_registry.unsafe")


def _validate_database_set(
    path: Path,
    *,
    parent: Path,
    require_mode: bool = True,
) -> dict[Path, tuple[int, int]]:
    _reject_unrecognized_database_artifacts(path, parent=parent)
    identities: dict[Path, tuple[int, int]] = {}
    for candidate in _database_files(path):
        identity = _secure_file(candidate, parent=parent, require_mode=require_mode)
        if identity is not None:
            identities[candidate] = identity
    _reject_unrecognized_database_artifacts(path, parent=parent)
    return identities


def _same_primary_database(
    before: Mapping[Path, tuple[int, int]],
    after: Mapping[Path, tuple[int, int]],
    *,
    path: Path,
) -> bool:
    """Require continuity for the durable file, not SQLite's transient sidecars."""

    identity = before.get(path)
    return identity is not None and after.get(path) == identity


def _translate_sqlite_error(exc: sqlite3.Error) -> AgentRegistryError:
    if isinstance(exc, sqlite3.OperationalError):
        return AgentRegistryUnavailableError("agent_registry.unavailable")
    return AgentRegistryError("agent_registry.corrupt")


def _schema_signature(connection: sqlite3.Connection) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (str(row[0]), str(row[1]), str(row[2]), "".join(str(row[3] or "").split()))
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_autoindex_%' ORDER BY type, name"
        )
    )


@lru_cache(maxsize=1)
def _expected_schema_signature() -> tuple[tuple[str, str, str, str], ...]:
    with TemporaryDirectory(prefix="mentat-agent-registry-schema-") as temporary:
        connection = sqlite3.connect(Path(temporary) / REGISTRY_DATABASE_NAME)
        try:
            connection.executescript(_SCHEMA)
            return _schema_signature(connection)
        finally:
            connection.close()


def _initialize(connection: sqlite3.Connection, *, applied_at: float | None = None) -> None:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'registry_schema'"
    ).fetchall()
    if not rows:
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA)
        connection.execute(
            "INSERT INTO registry_schema(version, applied_at) VALUES (?, ?)",
            (REGISTRY_SCHEMA_VERSION, time.time() if applied_at is None else applied_at),
        )
        connection.commit()
    versions = [int(row[0]) for row in connection.execute("SELECT version FROM registry_schema")]
    if versions != [REGISTRY_SCHEMA_VERSION]:
        raise AgentRegistryError("agent_registry.unsupported")
    if _schema_signature(connection) != _expected_schema_signature():
        raise AgentRegistryError("agent_registry.schema_invalid")


def connect_registry(data_dir: Path) -> sqlite3.Connection:
    """Open the converged Agent authority inside ``mentat.sqlite3``."""

    connection: sqlite3.Connection | None = None
    try:
        connection = connect_database(Path(data_dir))
        authority_receipt(connection, required=True)
        return connection
    except AgentRegistryError:
        if connection is not None:
            connection.close()
        raise
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise _translate_sqlite_error(exc) from exc
    except MentatDatabaseError as exc:
        if connection is not None:
            connection.close()
        message = str(exc).lower()
        if "newer" in message or "schema" in message:
            raise AgentRegistryError("agent_registry.unsupported") from exc
        raise AgentRegistryUnavailableError("agent_registry.unavailable") from exc


def initialize_registry_file(path: Path) -> None:
    """Create one canonical standalone registry snapshot file."""

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _initialize(connection, applied_at=0.0)
    finally:
        connection.close()
    if os.name != "nt":
        path.chmod(0o600)


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _read_legacy_file(
    path: Path,
    *,
    identity: tuple[int, int],
    parent: Path,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AgentRegistryUnavailableError("agent_registry.unavailable") from exc
    try:
        before = os.fstat(descriptor)
        if (
            (int(before.st_dev), int(before.st_ino)) != identity
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_size > MAX_LEGACY_REGISTRY_BYTES
        ):
            raise AgentRegistryError("agent_registry.unsafe")
        chunks: list[bytes] = []
        remaining = MAX_LEGACY_REGISTRY_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(raw) > MAX_LEGACY_REGISTRY_BYTES
            or len(raw) != before.st_size
            or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            or _secure_file(path, parent=parent) != identity
        ):
            raise AgentRegistryError("agent_registry.changed")
        return raw
    except OSError as exc:
        raise AgentRegistryUnavailableError("agent_registry.unavailable") from exc
    finally:
        os.close(descriptor)


def _legacy_records(
    connection: sqlite3.Connection,
    *,
    supported_runtime_types: Iterable[str],
    runtime_binding_validator: Callable[[MentatAgent, str], bool] | None,
) -> tuple[LegacyAgentRecord, ...]:
    agents = validate_registry_connection(
        connection,
        supported_runtime_types=supported_runtime_types,
        runtime_binding_validator=runtime_binding_validator,
    )
    rows = connection.execute(
        """
        SELECT a.id, a.created_at AS agent_created_at,
               a.updated_at AS agent_updated_at,
               c.id AS runtime_config_id, c.runtime_type,
               c.runtime_agent_ref, c.created_at AS config_created_at,
               c.updated_at AS config_updated_at
        FROM mentat_agents AS a
        JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id
        ORDER BY a.name COLLATE NOCASE, a.id
        """
    ).fetchall()
    if len(rows) != len(agents):
        raise AgentRegistryError("agent_registry.corrupt")
    records: list[LegacyAgentRecord] = []
    for agent, row in zip(agents, rows, strict=True):
        if str(row["id"]) != agent.id:
            raise AgentRegistryError("agent_registry.corrupt")
        records.append(
            LegacyAgentRecord(
                agent=agent,
                binding=RuntimeBinding(
                    id=str(row["runtime_config_id"]),
                    runtime_type=str(row["runtime_type"]),
                    runtime_agent_ref=str(row["runtime_agent_ref"]),
                    revision=1,
                ),
                agent_created_at=float(row["agent_created_at"]),
                agent_updated_at=float(row["agent_updated_at"]),
                config_created_at=float(row["config_created_at"]),
                config_updated_at=float(row["config_updated_at"]),
            )
        )
    return tuple(records)


def capture_legacy_registry_snapshot(
    data_dir: Path,
    *,
    supported_runtime_types: Iterable[str] = ("codex", "hermes"),
    runtime_binding_validator: Callable[[MentatAgent, str], bool] | None = None,
) -> LegacyRegistrySnapshot:
    """Capture the retired standalone registry without changing operator state."""

    path = registry_database_path(data_dir)
    parent = path.parent
    initial = _validate_database_set(path, parent=parent)
    if path not in initial:
        if initial:
            raise AgentRegistryError("agent_registry.unsafe")
        with TemporaryDirectory(prefix="mentat-empty-agent-source-") as temporary:
            snapshot = Path(temporary) / REGISTRY_DATABASE_NAME
            initialize_registry_file(snapshot)
            raw = snapshot.read_bytes()
            connection = sqlite3.connect(snapshot)
            connection.row_factory = sqlite3.Row
            try:
                records = _legacy_records(
                    connection,
                    supported_runtime_types=supported_runtime_types,
                    runtime_binding_validator=runtime_binding_validator,
                )
            finally:
                connection.close()
        binding = hashlib.sha256(
            _canonical_bytes(
                {
                    "path": os.path.normcase(os.path.abspath(os.fspath(path))),
                    "state": "absent",
                }
            )
        ).hexdigest()
        return LegacyRegistrySnapshot(
            raw=raw,
            sha256=_legacy_record_digest(records),
            source_binding=binding,
            records=records,
        )

    captured = {
        candidate: _read_legacy_file(
            candidate,
            identity=identity,
            parent=parent,
        )
        for candidate, identity in initial.items()
    }
    with TemporaryDirectory(prefix="mentat-agent-source-") as temporary:
        copied = Path(temporary) / REGISTRY_DATABASE_NAME
        copied.write_bytes(captured[path])
        if os.name != "nt":
            copied.chmod(0o600)
        wal = Path(f"{path}-wal")
        if wal in captured:
            copied_wal = Path(f"{copied}-wal")
            copied_wal.write_bytes(captured[wal])
            if os.name != "nt":
                copied_wal.chmod(0o600)
        snapshot = Path(temporary) / "snapshot.sqlite3"
        source = sqlite3.connect(copied)
        destination = sqlite3.connect(snapshot)
        try:
            source.backup(destination)
        except sqlite3.Error as exc:
            raise _translate_sqlite_error(exc) from exc
        finally:
            destination.close()
            source.close()
        connection = sqlite3.connect(snapshot)
        connection.row_factory = sqlite3.Row
        try:
            records = _legacy_records(
                connection,
                supported_runtime_types=supported_runtime_types,
                runtime_binding_validator=runtime_binding_validator,
            )
        finally:
            connection.close()
        raw = snapshot.read_bytes()
    terminal = _validate_database_set(path, parent=parent)
    if terminal != initial or set(terminal) != set(captured):
        raise AgentRegistryError("agent_registry.changed")
    for candidate, identity in terminal.items():
        if (
            _read_legacy_file(candidate, identity=identity, parent=parent)
            != captured[candidate]
        ):
            raise AgentRegistryError("agent_registry.changed")
    main_identity = initial[path]
    evidence = {
        "path": os.path.normcase(os.path.abspath(os.fspath(path))),
        "device": main_identity[0],
        "inode": main_identity[1],
    }
    return LegacyRegistrySnapshot(
        raw=raw,
        sha256=_legacy_record_digest(records),
        source_binding=hashlib.sha256(_canonical_bytes(evidence)).hexdigest(),
        records=records,
    )


@contextmanager
def _hold_legacy_registry_cutover_lock(data_dir: Path):
    """Prevent legacy-registry writers until the caller finishes cutover."""

    path = registry_database_path(data_dir)
    parent = path.parent
    opened = _validate_database_set(path, parent=parent)
    identity = opened.get(path)
    if identity is None:
        if opened:
            raise AgentRegistryError("agent_registry.unsafe")
        def validate_absent() -> None:
            if _validate_database_set(path, parent=parent):
                raise AgentRegistryError("agent_registry.changed")

        try:
            yield validate_absent
        finally:
            validate_absent()
        return
    connection: sqlite3.Connection | None = None
    try:
        resolved = path.resolve(strict=True)
        connection = sqlite3.connect(
            f"{resolved.as_uri()}?mode=rw",
            uri=True,
            timeout=5.0,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("PRAGMA query_only = ON")
        locked = _validate_database_set(path, parent=parent, require_mode=False)
        if not _same_primary_database(opened, locked, path=path):
            raise AgentRegistryError("agent_registry.changed")
        validate_registry_connection(
            connection,
            supported_runtime_types=("codex", "hermes"),
        )
        def validate_locked() -> None:
            terminal = _validate_database_set(
                path,
                parent=parent,
                require_mode=False,
            )
            if not _same_primary_database(locked, terminal, path=path):
                raise AgentRegistryError("agent_registry.changed")

        yield validate_locked
        validate_locked()
    except sqlite3.Error as exc:
        raise _translate_sqlite_error(exc) from exc
    finally:
        if connection is not None:
            try:
                connection.rollback()
            finally:
                connection.close()


def _validate_agent_row(
    row: Mapping[str, object],
    supported_runtime_types: Iterable[str],
    runtime_binding_validator: Callable[[MentatAgent, str], bool] | None = None,
) -> MentatAgent:
    try:
        capabilities = json.loads(str(row["capabilities_json"]))
        if not isinstance(capabilities, list) or any(not isinstance(value, str) for value in capabilities):
            raise ValueError("invalid capabilities")
        agent = MentatAgent(
            id=str(row["id"]),
            name=str(row["name"]),
            runtime_type=str(row["runtime_type"]),
            runtime_config_id=str(row["runtime_config_id"]),
            capabilities=frozenset(capabilities),
        )
        runtime_agent_ref = str(row["runtime_agent_ref"])
        RuntimeContext(agent_id=agent.id, runtime_agent_ref=runtime_agent_ref)
        if agent.runtime_type not in frozenset(supported_runtime_types) or len(agent.capabilities) > 64:
            raise ValueError("unsupported registry row")
        if runtime_binding_validator is not None and not runtime_binding_validator(
            agent, runtime_agent_ref
        ):
            raise ValueError("unsupported runtime binding")
        for key in ("agent_created_at", "agent_updated_at", "config_created_at", "config_updated_at"):
            value = row[key]
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError("invalid timestamp")
        row_keys = row.keys() if hasattr(row, "keys") else row
        revision = row["agent_revision"] if "agent_revision" in row_keys else 1
        if type(revision) is not int or revision < 1:
            raise ValueError("invalid Agent revision")
        system_role = row["system_role"] if "system_role" in row_keys else None
        if system_role not in {None, DIRECT_AGENT_ROLE}:
            raise ValueError("invalid Agent system role")
        return agent
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentRegistryError("agent_registry.corrupt") from exc


def _table_names(connection: sqlite3.Connection) -> frozenset[str]:
    try:
        return frozenset(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        )
    except sqlite3.Error as exc:
        raise _translate_sqlite_error(exc) from exc


def _embedded_schema_signature(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str, str], ...]:
    agent_tables = (
        "agent_runtime_configs",
        "mentat_agents",
        "mentat_agent_registry_state",
    )
    placeholders = ",".join("?" for _item in agent_tables)
    return tuple(
        (str(row[0]), str(row[1]), str(row[2]), "".join(str(row[3] or "").split()))
        for row in connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            f"WHERE tbl_name IN ({placeholders}) "
            "AND name NOT LIKE 'sqlite_autoindex_%' ORDER BY type, name",
            agent_tables,
        )
    )


@lru_cache(maxsize=1)
def _expected_embedded_schema_signature(
    schema_version: int = DATABASE_SCHEMA_VERSION,
) -> tuple[tuple[str, str, str, str], ...]:
    with TemporaryDirectory(prefix="mentat-embedded-agent-schema-") as temporary:
        connection = sqlite3.connect(Path(temporary) / "mentat.sqlite3")
        try:
            connection.execute(
                "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
            )
            for version, script in MIGRATIONS:
                if version > schema_version:
                    break
                connection.executescript(script)
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                    (version,),
                )
            return _embedded_schema_signature(connection)
        finally:
            connection.close()


def authority_receipt(
    connection: sqlite3.Connection,
    *,
    required: bool = False,
) -> AgentAuthorityReceipt | None:
    """Return and validate the embedded Agent-authority receipt."""

    if "mentat_agent_registry_state" not in _table_names(connection):
        if required:
            raise AgentRegistryUnavailableError("agent_registry.migration_required")
        return None
    try:
        rows = connection.execute(
            "SELECT authority, migration_contract, source_kind, source_sha256, "
            "source_agent_count, cutover_at FROM mentat_agent_registry_state "
            "WHERE singleton = 1"
        ).fetchall()
    except sqlite3.Error as exc:
        raise _translate_sqlite_error(exc) from exc
    if not rows:
        if required:
            raise AgentRegistryUnavailableError("agent_registry.migration_required")
        return None
    if len(rows) != 1:
        raise AgentRegistryError("agent_registry.corrupt")
    row = rows[0]
    try:
        source_kind = str(row["source_kind"])
        source_sha256 = str(row["source_sha256"])
        source_agent_count = int(row["source_agent_count"])
        cutover_at = float(row["cutover_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AgentRegistryError("agent_registry.corrupt") from exc
    if (
        row["authority"] != "sqlite"
        or row["migration_contract"] != AGENT_REGISTRY_AUTHORITY_CONTRACT
        or source_kind not in {"fresh", "legacy"}
        or not re.fullmatch(r"[0-9a-f]{64}", source_sha256)
        or not 0 <= source_agent_count <= MAX_AGENTS
        or not math.isfinite(cutover_at)
        or cutover_at <= 0
    ):
        raise AgentRegistryError("agent_registry.corrupt")
    return AgentAuthorityReceipt(
        source_kind=source_kind,
        source_sha256=source_sha256,
        source_agent_count=source_agent_count,
        cutover_at=cutover_at,
    )


def validate_registry_connection(
    connection: sqlite3.Connection,
    *,
    supported_runtime_types: Iterable[str] = ("hermes",),
    runtime_binding_validator: Callable[[MentatAgent, str], bool] | None = None,
) -> tuple[MentatAgent, ...]:
    """Validate schema, relationships, bounds, and every persisted value."""

    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise AgentRegistryError("agent_registry.corrupt")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise AgentRegistryError("agent_registry.corrupt")
        tables = _table_names(connection)
        standalone = "registry_schema" in tables
        schema_version = 0
        if standalone:
            versions = [
                int(row[0])
                for row in connection.execute("SELECT version FROM registry_schema")
            ]
            if versions != [REGISTRY_SCHEMA_VERSION]:
                raise AgentRegistryError("agent_registry.unsupported")
            if _schema_signature(connection) != _expected_schema_signature():
                raise AgentRegistryError("agent_registry.schema_invalid")
        else:
            required = {
                "schema_migrations",
                "mentat_agent_registry_state",
                "agent_runtime_configs",
                "mentat_agents",
            }
            if not required.issubset(tables):
                raise AgentRegistryUnavailableError(
                    "agent_registry.migration_required"
                )
            try:
                schema_version = int(
                    connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                    or 0
                )
            except (sqlite3.Error, TypeError, ValueError) as exc:
                raise AgentRegistryError("agent_registry.corrupt") from exc
            if schema_version not in {8, 9, 10, DATABASE_SCHEMA_VERSION}:
                raise AgentRegistryError("agent_registry.unsupported")
            if (
                _embedded_schema_signature(connection)
                != _expected_embedded_schema_signature(schema_version)
            ):
                raise AgentRegistryError("agent_registry.schema_invalid")
            authority_receipt(connection, required=True)
        config_count = int(connection.execute("SELECT COUNT(*) FROM agent_runtime_configs").fetchone()[0])
        agent_count = int(connection.execute("SELECT COUNT(*) FROM mentat_agents").fetchone()[0])
        if config_count != agent_count or agent_count > MAX_AGENTS:
            raise AgentRegistryError("agent_registry.corrupt")
        if not standalone and schema_version >= DATABASE_SCHEMA_VERSION:
            role_rows = connection.execute(
                "SELECT system_role FROM mentat_agents ORDER BY id"
            ).fetchall()
            if sum(row[0] == DIRECT_AGENT_ROLE for row in role_rows) > 1 or any(
                row[0] not in {None, DIRECT_AGENT_ROLE} for row in role_rows
            ):
                raise AgentRegistryError("agent_registry.corrupt")
        columns = (
            "a.id, a.name, a.runtime_config_id, a.capabilities_json, "
            "a.created_at AS agent_created_at, a.updated_at AS agent_updated_at, "
            "c.runtime_type, c.runtime_agent_ref, "
            "c.created_at AS config_created_at, c.updated_at AS config_updated_at"
        )
        if not standalone and schema_version >= DATABASE_SCHEMA_VERSION:
            columns = (
                "a.id, a.name, a.runtime_config_id, a.capabilities_json, "
                "a.revision AS agent_revision, a.system_role, "
                "a.created_at AS agent_created_at, a.updated_at AS agent_updated_at, "
                "c.runtime_type, c.runtime_agent_ref, "
                "c.created_at AS config_created_at, c.updated_at AS config_updated_at"
            )
        rows = connection.execute(
            f"""
            SELECT {columns}
            FROM mentat_agents AS a
            JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id
            ORDER BY a.name COLLATE NOCASE, a.id
            """
        ).fetchall()
        if len(rows) != agent_count:
            raise AgentRegistryError("agent_registry.corrupt")
        return tuple(
            _validate_agent_row(
                row,
                supported_runtime_types,
                runtime_binding_validator,
            )
            for row in rows
        )
    except sqlite3.Error as exc:
        raise _translate_sqlite_error(exc) from exc


def public_agent_record(agent: MentatAgent) -> dict:
    """Project a canonical Agent without its adapter-owned runtime reference."""

    return {
        "id": agent.id,
        "name": agent.name,
        "runtime_type": agent.runtime_type,
        "runtime_config_id": agent.runtime_config_id,
        "capabilities": sorted(agent.capabilities),
    }


def _canonical_agent_records(
    connection: sqlite3.Connection,
    *,
    supported_runtime_types: Iterable[str],
) -> tuple[CanonicalAgentRecord, ...]:
    """Return validated identity metadata without exposing runtime references."""

    agents = validate_registry_connection(
        connection,
        supported_runtime_types=supported_runtime_types,
    )
    versions = [
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations")
    ]
    schema_version = max(versions, default=0)
    if schema_version >= DATABASE_SCHEMA_VERSION:
        rows = connection.execute(
            "SELECT id, revision, system_role FROM mentat_agents ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
    else:
        rows = connection.execute(
            "SELECT id, 1 AS revision, NULL AS system_role FROM mentat_agents ORDER BY name COLLATE NOCASE, id"
        ).fetchall()
    if len(rows) != len(agents):
        raise AgentRegistryError("agent_registry.corrupt")
    records = tuple(
        CanonicalAgentRecord(
            agent=agent,
            revision=int(row["revision"]),
            system_role=str(row["system_role"]) if row["system_role"] is not None else None,
        )
        for agent, row in zip(agents, rows, strict=True)
    )
    if sum(record.system_role == DIRECT_AGENT_ROLE for record in records) > 1:
        raise AgentRegistryError("agent_registry.corrupt")
    return records


class AgentRegistry:
    """Small SQLite repository for canonical Agents and one-to-one bindings."""

    def __init__(self, data_dir: Path, *, supported_runtime_types: Iterable[str]):
        self.data_dir = Path(data_dir)
        self.supported_runtime_types = frozenset(supported_runtime_types)

    def _validated_agent(
        self,
        *,
        agent_id: str,
        name: str,
        runtime_config_id: str,
        runtime_type: str,
        runtime_agent_ref: str,
        capabilities: Iterable[str],
    ) -> MentatAgent:
        if runtime_type not in self.supported_runtime_types:
            raise AgentRegistryValidationError("agent.runtime_unsupported")
        if isinstance(capabilities, (str, bytes)):
            raise AgentRegistryValidationError("agent.invalid")
        try:
            agent = MentatAgent(
                id=agent_id,
                name=name,
                runtime_type=runtime_type,
                runtime_config_id=runtime_config_id,
                capabilities=frozenset(capabilities),
            )
            RuntimeContext(
                agent_id=agent.id,
                runtime_agent_ref=runtime_agent_ref,
            )
        except (TypeError, ValueError) as exc:
            raise AgentRegistryValidationError("agent.invalid") from exc
        if len(agent.capabilities) > 64:
            raise AgentRegistryValidationError("agent.invalid")
        return agent

    def create_agent(
        self,
        *,
        agent_id: str,
        name: str,
        runtime_config_id: str,
        runtime_type: str,
        runtime_agent_ref: str,
        capabilities: Iterable[str],
    ) -> MentatAgent:
        """Atomically create one Agent and its private runtime configuration."""

        agent = self._validated_agent(
            agent_id=agent_id,
            name=name,
            runtime_config_id=runtime_config_id,
            runtime_type=runtime_type,
            runtime_agent_ref=runtime_agent_ref,
            capabilities=capabilities,
        )
        now = time.time()
        encoded_capabilities = json.dumps(
            sorted(agent.capabilities),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        if len(encoded_capabilities) > 8_192:
            raise AgentRegistryValidationError("agent.invalid")
        connection = connect_registry(self.data_dir)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = validate_registry_connection(
                    connection,
                    supported_runtime_types=self.supported_runtime_types,
                )
                count = len(existing)
                if count >= MAX_AGENTS:
                    raise AgentRegistryLimitError("agent.limit")
                connection.execute(
                    """
                    INSERT INTO agent_runtime_configs (
                        id, runtime_type, runtime_agent_ref, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        runtime_config_id,
                        runtime_type,
                        runtime_agent_ref,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO mentat_agents (
                        id, name, runtime_config_id, capabilities_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent.id,
                        agent.name,
                        runtime_config_id,
                        encoded_capabilities,
                        now,
                        now,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        except sqlite3.IntegrityError as exc:
            raise AgentRegistryConflict("agent.conflict") from exc
        except sqlite3.Error as exc:
            raise _translate_sqlite_error(exc) from exc
        finally:
            connection.close()
        return agent

    def list_agents(self) -> tuple[MentatAgent, ...]:
        connection = connect_registry(self.data_dir)
        try:
            return validate_registry_connection(
                connection,
                supported_runtime_types=self.supported_runtime_types,
            )
        finally:
            connection.close()

    def list_agent_records(self) -> tuple[CanonicalAgentRecord, ...]:
        """Return canonical Agent identity metadata for safe Console joins."""

        connection = connect_registry(self.data_dir)
        try:
            return _canonical_agent_records(
                connection,
                supported_runtime_types=self.supported_runtime_types,
            )
        finally:
            connection.close()

    def ensure_direct_agent(self) -> CanonicalAgentRecord | None:
        """Idempotently seed the canonical Direct Agent when its binding is free."""

        if DIRECT_RUNTIME_TYPE not in self.supported_runtime_types:
            return None
        from codex_runtime import codex_binding_is_valid, find_codex_command

        if find_codex_command() is None or not codex_binding_is_valid(
            DIRECT_RUNTIME_AGENT_REF,
            DIRECT_AGENT_CAPABILITIES,
        ):
            return None
        try:
            direct = MentatAgent(
                id=DIRECT_AGENT_ID,
                name="Direct Agent",
                runtime_type=DIRECT_RUNTIME_TYPE,
                runtime_config_id=DIRECT_RUNTIME_CONFIG_ID,
                capabilities=DIRECT_AGENT_CAPABILITIES,
            )
            RuntimeContext(
                agent_id=direct.id,
                runtime_agent_ref=DIRECT_RUNTIME_AGENT_REF,
            )
        except (TypeError, ValueError):
            return None
        encoded_capabilities = json.dumps(
            sorted(direct.capabilities),
            ensure_ascii=True,
            separators=(",", ":"),
        )
        now = time.time()
        connection = connect_registry(self.data_dir)
        try:
            connection.execute("BEGIN IMMEDIATE")
            records = _canonical_agent_records(
                connection,
                supported_runtime_types=self.supported_runtime_types,
            )
            existing_direct = next(
                (
                    record
                    for record in records
                    if record.system_role == DIRECT_AGENT_ROLE
                ),
                None,
            )
            if existing_direct is not None:
                binding = connection.execute(
                    """
                    SELECT a.id, a.name, a.runtime_config_id, a.capabilities_json,
                           c.runtime_type, c.runtime_agent_ref
                    FROM mentat_agents AS a
                    JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id
                    WHERE a.id = ?
                    """,
                    (DIRECT_AGENT_ID,),
                ).fetchone()
                if (
                    binding is None
                    or binding["name"] != direct.name
                    or binding["runtime_config_id"] != DIRECT_RUNTIME_CONFIG_ID
                    or binding["runtime_type"] != DIRECT_RUNTIME_TYPE
                    or binding["runtime_agent_ref"] != DIRECT_RUNTIME_AGENT_REF
                    or json.loads(str(binding["capabilities_json"]))
                    != sorted(DIRECT_AGENT_CAPABILITIES)
                ):
                    connection.rollback()
                    raise AgentRegistryError("agent_registry.corrupt")
                connection.rollback()
                return existing_direct
            binding_in_use = connection.execute(
                """
                SELECT 1
                FROM agent_runtime_configs
                WHERE runtime_type = ? AND runtime_agent_ref = ?
                """,
                (DIRECT_RUNTIME_TYPE, DIRECT_RUNTIME_AGENT_REF),
            ).fetchone()
            if binding_in_use is not None or len(records) >= MAX_AGENTS:
                connection.rollback()
                return None
            connection.execute(
                """
                INSERT INTO agent_runtime_configs (
                    id, runtime_type, runtime_agent_ref, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    DIRECT_RUNTIME_CONFIG_ID,
                    DIRECT_RUNTIME_TYPE,
                    DIRECT_RUNTIME_AGENT_REF,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO mentat_agents (
                    id, name, runtime_config_id, capabilities_json,
                    revision, system_role, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    direct.id,
                    direct.name,
                    DIRECT_RUNTIME_CONFIG_ID,
                    encoded_capabilities,
                    DIRECT_AGENT_ROLE,
                    now,
                    now,
                ),
            )
            connection.commit()
            return CanonicalAgentRecord(agent=direct, revision=1, system_role=DIRECT_AGENT_ROLE)
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise AgentRegistryConflict("agent.conflict") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise _translate_sqlite_error(exc) from exc
        finally:
            connection.close()

    def get_runtime_binding(self, agent_id: str) -> RuntimeBinding:
        try:
            MentatAgent(
                id=agent_id,
                name="Binding lookup",
                runtime_type="hermes",
            )
        except (TypeError, ValueError) as exc:
            raise AgentRegistryValidationError("agent.invalid") from exc
        connection = connect_registry(self.data_dir)
        try:
            try:
                row = connection.execute(
                    """
                    SELECT c.id, c.runtime_type, c.runtime_agent_ref
                    FROM mentat_agents AS a
                    JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id
                    WHERE a.id = ?
                    """,
                    (agent_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise _translate_sqlite_error(exc) from exc
        finally:
            connection.close()
        if row is None:
            raise AgentRegistryError("agent.not_found")
        try:
            RuntimeContext(
                agent_id=agent_id,
                runtime_agent_ref=str(row["runtime_agent_ref"]),
            )
            binding = RuntimeBinding(
                id=str(row["id"]),
                runtime_type=str(row["runtime_type"]),
                runtime_agent_ref=str(row["runtime_agent_ref"]),
                revision=1,
            )
            if binding.runtime_type not in self.supported_runtime_types:
                raise ValueError("unsupported runtime")
            return binding
        except (TypeError, ValueError) as exc:
            raise AgentRegistryError("agent_registry.corrupt") from exc


__all__ = [
    "AgentAuthorityReceipt",
    "AgentRegistry",
    "AgentRegistryConflict",
    "AgentRegistryError",
    "AgentRegistryLimitError",
    "AgentRegistryUnavailableError",
    "AgentRegistryValidationError",
    "CanonicalAgentRecord",
    "DIRECT_AGENT_CAPABILITIES",
    "DIRECT_AGENT_ID",
    "DIRECT_AGENT_ROLE",
    "DIRECT_RUNTIME_AGENT_REF",
    "DIRECT_RUNTIME_CONFIG_ID",
    "DIRECT_RUNTIME_TYPE",
    "LegacyAgentRecord",
    "LegacyRegistrySnapshot",
    "MAX_LEGACY_REGISTRY_BYTES",
    "MAX_AGENTS",
    "REGISTRY_DATABASE_NAME",
    "authority_receipt",
    "capture_legacy_registry_snapshot",
    "connect_registry",
    "initialize_registry_file",
    "registry_database_path",
    "validate_registry_connection",
    "RuntimeBinding",
    "public_agent_record",
]
