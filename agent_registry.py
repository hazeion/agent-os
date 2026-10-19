"""Durable Mentat-owned Agent identities and private runtime bindings."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from threading import Lock
from typing import Callable, Iterable, Mapping

from agent_runtime import MentatAgent, RuntimeContext
from mentat_db import (
    AGENT_REGISTRY_AUTHORITY_CONTRACT,
    MentatDatabaseError,
    MIGRATIONS,
    SCHEMA_VERSION as DATABASE_SCHEMA_VERSION,
    connect as connect_database,
)


MAX_AGENTS = 128
DIRECT_AGENT_ROLE = "direct"
DIRECT_AGENT_ID = "agent_direct"
DIRECT_RUNTIME_CONFIG_ID = "runtime_config_direct"
DIRECT_RUNTIME_TYPE = "codex"
DIRECT_RUNTIME_AGENT_REF = "default"
INTERACTIVE_AGENT_CAPABILITIES = (
    "run.events",
    "run.message",
    "run.start",
    "run.status",
    "run.stop",
)
DIRECT_AGENT_CAPABILITIES = INTERACTIVE_AGENT_CAPABILITIES
CODEX_TASK_CREATE_CAPABILITY = "task.create"


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


def _translate_sqlite_error(exc: sqlite3.Error) -> AgentRegistryError:
    if isinstance(exc, sqlite3.OperationalError):
        return AgentRegistryUnavailableError("agent_registry.unavailable")
    return AgentRegistryError("agent_registry.corrupt")


def connect_registry(data_dir: Path) -> sqlite3.Connection:
    """Open the current Agent authority inside ``mentat.sqlite3``."""

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
        revision = row["agent_revision"]
        if type(revision) is not int or revision < 1:
            raise ValueError("invalid Agent revision")
        system_role = row["system_role"]
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


_EXPECTED_EMBEDDED_SCHEMA_LOCK = Lock()


def _embedded_schema_recipe(schema_version: int) -> tuple:
    if type(schema_version) is not int or schema_version != DATABASE_SCHEMA_VERSION:
        raise AgentRegistryError("agent_registry.unsupported")
    # Cache only a code-generated expected SQL signature. Actual databases,
    # rows, authority receipts and relationship evidence never enter this key.
    return (
        schema_version, tuple(MIGRATIONS), _embedded_schema_signature,
        sqlite3.connect, sqlite3.sqlite_version_info, DATABASE_SCHEMA_VERSION,
    )


@lru_cache(maxsize=1)
def _cached_expected_embedded_schema_signature(
    recipe: tuple,
) -> tuple[tuple[str, str, str, str], ...]:
    schema_version, migrations, normalizer = recipe[:3]
    # This database exists only to derive code-owned SQL definitions. No
    # operator bytes, rows or paths are loaded, and no database bytes escape.
    # Memory avoids filesystem/fsync latency even on the first cache miss.
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
        )
        for version, script in migrations:
            if version > schema_version:
                break
            connection.executescript(script)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                (version,),
            )
        signature = normalizer(connection)
        if recipe != _embedded_schema_recipe(schema_version):
            raise AgentRegistryError("agent_registry.schema_invalid")
        return signature
    finally:
        connection.close()


def _expected_embedded_schema_signature(
    schema_version: int = DATABASE_SCHEMA_VERSION,
) -> tuple[tuple[str, str, str, str], ...]:
    recipe = _embedded_schema_recipe(schema_version)
    # Avoid duplicate expensive synthetic builds on simultaneous misses. This
    # lock neither acquires a live data-root lock nor encloses actual validation.
    with _EXPECTED_EMBEDDED_SCHEMA_LOCK:
        signature = _cached_expected_embedded_schema_signature(recipe)
    if recipe != _embedded_schema_recipe(schema_version):
        raise AgentRegistryError("agent_registry.schema_invalid")
    return signature


def authority_receipt(
    connection: sqlite3.Connection,
    *,
    required: bool = False,
) -> AgentAuthorityReceipt | None:
    """Return and validate the embedded Agent-authority receipt."""

    if "mentat_agent_registry_state" not in _table_names(connection):
        if required:
            raise AgentRegistryUnavailableError("agent_registry.authority_missing")
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
            raise AgentRegistryUnavailableError("agent_registry.authority_missing")
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
        required = {
            "schema_migrations", "mentat_agent_registry_state",
            "agent_runtime_configs", "mentat_agents",
        }
        if "registry_schema" in tables or not required.issubset(tables):
            raise AgentRegistryError("agent_registry.unsupported")
        versions = [int(row[0]) for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )]
        if versions != list(range(1, DATABASE_SCHEMA_VERSION + 1)):
            raise AgentRegistryError("agent_registry.unsupported")
        if _embedded_schema_signature(connection) != _expected_embedded_schema_signature():
            raise AgentRegistryError("agent_registry.schema_invalid")
        authority_receipt(connection, required=True)
        config_count = int(connection.execute("SELECT COUNT(*) FROM agent_runtime_configs").fetchone()[0])
        agent_count = int(connection.execute("SELECT COUNT(*) FROM mentat_agents").fetchone()[0])
        if config_count != agent_count or agent_count > MAX_AGENTS:
            raise AgentRegistryError("agent_registry.corrupt")
        role_rows = connection.execute(
            "SELECT system_role FROM mentat_agents ORDER BY id"
        ).fetchall()
        if sum(row[0] == DIRECT_AGENT_ROLE for row in role_rows) > 1 or any(
            row[0] not in {None, DIRECT_AGENT_ROLE} for row in role_rows
        ):
            raise AgentRegistryError("agent_registry.corrupt")
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
    except (TypeError, ValueError) as exc:
        raise AgentRegistryError("agent_registry.corrupt") from exc
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
    rows = connection.execute(
        "SELECT id, revision, system_role FROM mentat_agents ORDER BY name COLLATE NOCASE, id"
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

    def enable_local_hermes_attachments(
        self,
        agent_id: str,
        *,
        expected_capabilities: Iterable[str],
    ) -> CanonicalAgentRecord:
        """Enable files only after one explicit, exact Agent-scoped action."""

        expected = tuple(sorted(set(str(value) for value in expected_capabilities)))
        if (
            not isinstance(agent_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", agent_id)
            or isinstance(expected_capabilities, (str, bytes))
            or len(expected) > 64
            or any(re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value) is None for value in expected)
        ):
            raise AgentRegistryValidationError("agent.invalid")
        connection = connect_registry(self.data_dir)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                records = _canonical_agent_records(
                    connection,
                    supported_runtime_types=self.supported_runtime_types,
                )
                current = next((record for record in records if record.agent.id == agent_id), None)
                if current is None:
                    raise AgentRegistryConflict("agent.not_found")
                if current.agent.runtime_type != "hermes":
                    raise AgentRegistryValidationError("agent.runtime_unsupported")
                if tuple(sorted(current.agent.capabilities)) != expected:
                    raise AgentRegistryConflict("agent.conflict")
                active = connection.execute(
                    "SELECT 1 FROM mentat_runs WHERE agent_id = ? AND ("
                    "status IN ('reserved','queued','submitting','starting','running',"
                    "'cancelling','waiting','waiting_for_approval','waiting_for_clarification','unknown') "
                    "OR (runtime_type = 'hermes' AND source = 'console' "
                    "AND status IN ('completed','failed','cancelled','stopped','interrupted') "
                    "AND terminal_finalized = 0)) LIMIT 1",
                    (agent_id,),
                ).fetchone()
                if active is not None:
                    raise AgentRegistryConflict("agent.active_run")
                if "run.attachments" not in current.agent.capabilities:
                    next_capabilities = tuple(sorted((*expected, "run.attachments")))
                    encoded = json.dumps(next_capabilities, ensure_ascii=True, separators=(",", ":"))
                    updated = connection.execute(
                        "UPDATE mentat_agents SET capabilities_json = ?, revision = revision + 1, "
                        "updated_at = ? WHERE id = ? AND capabilities_json = ?",
                        (
                            encoded,
                            time.time(),
                            agent_id,
                            json.dumps(expected, ensure_ascii=True, separators=(",", ":")),
                        ),
                    ).rowcount
                    if updated != 1:
                        raise AgentRegistryConflict("agent.conflict")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            records = _canonical_agent_records(
                connection,
                supported_runtime_types=self.supported_runtime_types,
            )
            enabled = next((record for record in records if record.agent.id == agent_id), None)
            if enabled is None or "run.attachments" not in enabled.agent.capabilities:
                raise AgentRegistryError("agent_registry.corrupt")
            return enabled
        except sqlite3.Error as exc:
            raise _translate_sqlite_error(exc) from exc
        finally:
            connection.close()

    def local_hermes_attachment_enable_state(self, agent_id: str) -> str:
        """Return one bounded eligibility state without changing Agent authority."""

        if not isinstance(agent_id, str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", agent_id
        ) is None:
            raise AgentRegistryValidationError("agent.invalid")
        connection = connect_registry(self.data_dir)
        try:
            records = _canonical_agent_records(
                connection,
                supported_runtime_types=self.supported_runtime_types,
            )
            current = next(
                (record for record in records if record.agent.id == agent_id),
                None,
            )
            if current is None:
                return "not_found"
            if "run.attachments" in current.agent.capabilities:
                return "enabled"
            if current.agent.runtime_type != "hermes":
                return "unsupported"
            active = connection.execute(
                "SELECT 1 FROM mentat_runs WHERE agent_id = ? AND ("
                "status IN ('reserved','queued','submitting','starting','running',"
                "'cancelling','waiting','waiting_for_approval','waiting_for_clarification','unknown') "
                "OR (runtime_type = 'hermes' AND source = 'console' "
                "AND status IN ('completed','failed','cancelled','stopped','interrupted') "
                "AND terminal_finalized = 0)) LIMIT 1",
                (agent_id,),
            ).fetchone()
            return "active_run" if active is not None else "available"
        except sqlite3.Error as exc:
            raise _translate_sqlite_error(exc) from exc
        finally:
            connection.close()

    def enable_codex_task_creation(
        self,
        agent_id: str,
        *,
        expected_capabilities: Iterable[str],
    ) -> CanonicalAgentRecord:
        """Opt one Codex Agent into the narrow Inbox-Task tool."""

        expected = tuple(sorted(set(str(value) for value in expected_capabilities)))
        if (
            not isinstance(agent_id, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", agent_id) is None
            or isinstance(expected_capabilities, (str, bytes))
            or len(expected) > 64
            or any(re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", value) is None for value in expected)
        ):
            raise AgentRegistryValidationError("agent.invalid")
        connection = connect_registry(self.data_dir)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                records = _canonical_agent_records(
                    connection, supported_runtime_types=self.supported_runtime_types
                )
                current = next((record for record in records if record.agent.id == agent_id), None)
                if current is None:
                    raise AgentRegistryConflict("agent.not_found")
                if current.agent.runtime_type != "codex":
                    raise AgentRegistryValidationError("agent.runtime_unsupported")
                if tuple(sorted(current.agent.capabilities)) != expected:
                    raise AgentRegistryConflict("agent.conflict")
                active = connection.execute(
                    "SELECT 1 FROM mentat_runs WHERE agent_id = ? AND status IN "
                    "('reserved','queued','submitting','starting','running','cancelling',"
                    "'waiting','waiting_for_approval','waiting_for_clarification','unknown') LIMIT 1",
                    (agent_id,),
                ).fetchone()
                if active is not None:
                    raise AgentRegistryConflict("agent.active_run")
                if CODEX_TASK_CREATE_CAPABILITY not in current.agent.capabilities:
                    next_capabilities = tuple(sorted((*expected, CODEX_TASK_CREATE_CAPABILITY)))
                    updated = connection.execute(
                        "UPDATE mentat_agents SET capabilities_json = ?, revision = revision + 1, "
                        "updated_at = ? WHERE id = ? AND capabilities_json = ?",
                        (
                            json.dumps(next_capabilities, ensure_ascii=True, separators=(",", ":")),
                            time.time(),
                            agent_id,
                            json.dumps(expected, ensure_ascii=True, separators=(",", ":")),
                        ),
                    ).rowcount
                    if updated != 1:
                        raise AgentRegistryConflict("agent.conflict")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            records = _canonical_agent_records(
                connection, supported_runtime_types=self.supported_runtime_types
            )
            enabled = next((record for record in records if record.agent.id == agent_id), None)
            if enabled is None or CODEX_TASK_CREATE_CAPABILITY not in enabled.agent.capabilities:
                raise AgentRegistryError("agent_registry.corrupt")
            return enabled
        except sqlite3.Error as exc:
            raise _translate_sqlite_error(exc) from exc
        finally:
            connection.close()

    def codex_task_creation_enable_state(self, agent_id: str) -> str:
        """Read the opt-in eligibility without launching the Codex runtime."""

        if not isinstance(agent_id, str) or re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", agent_id
        ) is None:
            raise AgentRegistryValidationError("agent.invalid")
        connection = connect_registry(self.data_dir)
        try:
            records = _canonical_agent_records(
                connection, supported_runtime_types=self.supported_runtime_types
            )
            current = next((record for record in records if record.agent.id == agent_id), None)
            if current is None:
                return "not_found"
            if CODEX_TASK_CREATE_CAPABILITY in current.agent.capabilities:
                return "enabled"
            if current.agent.runtime_type != "codex":
                return "unsupported"
            active = connection.execute(
                "SELECT 1 FROM mentat_runs WHERE agent_id = ? AND status IN "
                "('reserved','queued','submitting','starting','running','cancelling',"
                "'waiting','waiting_for_approval','waiting_for_clarification','unknown') LIMIT 1",
                (agent_id,),
            ).fetchone()
            return "active_run" if active is not None else "available"
        except sqlite3.Error as exc:
            raise _translate_sqlite_error(exc) from exc
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
                    or tuple(sorted(json.loads(str(binding["capabilities_json"])))) not in {
                        tuple(sorted(DIRECT_AGENT_CAPABILITIES)),
                        tuple(sorted((*DIRECT_AGENT_CAPABILITIES, CODEX_TASK_CREATE_CAPABILITY))),
                    }
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
    "INTERACTIVE_AGENT_CAPABILITIES",
    "DIRECT_AGENT_ID",
    "DIRECT_AGENT_ROLE",
    "DIRECT_RUNTIME_AGENT_REF",
    "DIRECT_RUNTIME_CONFIG_ID",
    "DIRECT_RUNTIME_TYPE",
    "MAX_AGENTS",
    "authority_receipt",
    "connect_registry",
    "validate_registry_connection",
    "RuntimeBinding",
    "public_agent_record",
]
