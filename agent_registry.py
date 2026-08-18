"""Durable Mentat-owned Agent identities and private runtime bindings."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import time
from tempfile import TemporaryDirectory
from typing import Iterable, Mapping

from agent_runtime import MentatAgent, RuntimeContext
from private_state import ensure_console_root


REGISTRY_DATABASE_NAME = "agent-registry.sqlite3"
REGISTRY_SCHEMA_VERSION = 1
MAX_AGENTS = 128

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


def registry_database_path(data_dir: Path) -> Path:
    return ensure_console_root(Path(data_dir)) / REGISTRY_DATABASE_NAME


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


def _validate_database_set(
    path: Path,
    *,
    parent: Path,
    require_mode: bool = True,
) -> dict[Path, tuple[int, int]]:
    identities: dict[Path, tuple[int, int]] = {}
    for candidate in _database_files(path):
        identity = _secure_file(candidate, parent=parent, require_mode=require_mode)
        if identity is not None:
            identities[candidate] = identity
    return identities


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
    """Open the independently versioned, owner-private Agent registry."""

    path = registry_database_path(data_dir)
    parent = path.parent
    _validate_database_set(path, parent=parent)
    if not path.exists():
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        finally:
            if descriptor is not None:
                os.close(descriptor)
    opened = _validate_database_set(path, parent=parent)
    identity = opened.get(path)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        if identity is None or _secure_file(path, parent=parent) != identity:
            raise AgentRegistryError("agent_registry.unsafe")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        _initialize(connection)
        observed = _validate_database_set(path, parent=parent, require_mode=False)
        if any(observed.get(candidate) != value for candidate, value in opened.items()):
            raise AgentRegistryError("agent_registry.unsafe")
        if os.name != "nt":
            for candidate in observed:
                candidate.chmod(0o600)
        secured = _validate_database_set(path, parent=parent)
        if any(secured.get(candidate) != value for candidate, value in observed.items()):
            raise AgentRegistryError("agent_registry.unsafe")
        return connection
    except sqlite3.Error as exc:
        if connection is not None:
            connection.close()
        raise _translate_sqlite_error(exc) from exc
    except Exception:
        if connection is not None:
            connection.close()
        raise


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


def _validate_agent_row(row: Mapping[str, object], supported_runtime_types: Iterable[str]) -> MentatAgent:
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
        RuntimeContext(agent_id=agent.id, runtime_agent_ref=str(row["runtime_agent_ref"]))
        if agent.runtime_type not in frozenset(supported_runtime_types) or len(agent.capabilities) > 64:
            raise ValueError("unsupported registry row")
        for key in ("agent_created_at", "agent_updated_at", "config_created_at", "config_updated_at"):
            value = row[key]
            if not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError("invalid timestamp")
        return agent
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AgentRegistryError("agent_registry.corrupt") from exc


def validate_registry_connection(
    connection: sqlite3.Connection,
    *,
    supported_runtime_types: Iterable[str] = ("hermes",),
) -> tuple[MentatAgent, ...]:
    """Validate schema, relationships, bounds, and every persisted value."""

    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise AgentRegistryError("agent_registry.corrupt")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise AgentRegistryError("agent_registry.corrupt")
        versions = [int(row[0]) for row in connection.execute("SELECT version FROM registry_schema")]
        if versions != [REGISTRY_SCHEMA_VERSION]:
            raise AgentRegistryError("agent_registry.unsupported")
        if _schema_signature(connection) != _expected_schema_signature():
            raise AgentRegistryError("agent_registry.schema_invalid")
        config_count = int(connection.execute("SELECT COUNT(*) FROM agent_runtime_configs").fetchone()[0])
        agent_count = int(connection.execute("SELECT COUNT(*) FROM mentat_agents").fetchone()[0])
        if config_count != agent_count or agent_count > MAX_AGENTS:
            raise AgentRegistryError("agent_registry.corrupt")
        rows = connection.execute(
            """
            SELECT a.id, a.name, a.runtime_config_id, a.capabilities_json,
                   a.created_at AS agent_created_at, a.updated_at AS agent_updated_at,
                   c.runtime_type, c.runtime_agent_ref,
                   c.created_at AS config_created_at, c.updated_at AS config_updated_at
            FROM mentat_agents AS a
            JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id
            ORDER BY a.name COLLATE NOCASE, a.id
            """
        ).fetchall()
        if len(rows) != agent_count:
            raise AgentRegistryError("agent_registry.corrupt")
        return tuple(_validate_agent_row(row, supported_runtime_types) for row in rows)
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
            )
            if binding.runtime_type not in self.supported_runtime_types:
                raise ValueError("unsupported runtime")
            return binding
        except (TypeError, ValueError) as exc:
            raise AgentRegistryError("agent_registry.corrupt") from exc


__all__ = [
    "AgentRegistry",
    "AgentRegistryConflict",
    "AgentRegistryError",
    "AgentRegistryLimitError",
    "AgentRegistryUnavailableError",
    "AgentRegistryValidationError",
    "MAX_AGENTS",
    "REGISTRY_DATABASE_NAME",
    "connect_registry",
    "initialize_registry_file",
    "registry_database_path",
    "validate_registry_connection",
    "RuntimeBinding",
    "public_agent_record",
]
