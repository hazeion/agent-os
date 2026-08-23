"""Exact offline convergence of the legacy Agent registry into Mentat SQLite."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
from typing import Any

from agent_registry import (
    AgentRegistryError,
    LegacyRegistrySnapshot,
    _hold_legacy_registry_cutover_lock,
    authority_receipt,
    capture_legacy_registry_snapshot,
    public_agent_record,
    validate_registry_connection,
)
from codex_runtime import codex_binding_is_valid
from data_backup_restore import (
    _load_live_documents,
    _read_internal_backup,
    create_durable_backup,
)
from json_store import _durable_mutation_lock, _pinned_root_matches
from mentat_db import (
    AGENT_REGISTRY_AUTHORITY_CONTRACT,
    SCHEMA_VERSION as DATABASE_SCHEMA_VERSION,
    connect_for_agent_registry_migration,
)
from private_console_unit import (
    PrivateConsoleUnit,
    agent_registry_digest,
    capture_private_console_unit,
    private_console_unit_digest,
)
from private_state import mentat_server_active, private_control_issue


PROTOCOL_VERSION = 1


class AgentRegistryMigrationError(RuntimeError):
    def __init__(self, code: str, *, writes_performed: bool = False):
        super().__init__(code)
        self.code = code
        self.writes_performed = writes_performed


@dataclass(frozen=True)
class DestinationSnapshot:
    schema_version: int
    database_sha256: str
    private_digest: str
    authority: str
    agent_count: int


@dataclass(frozen=True)
class AgentRegistryMigrationPreview:
    status: str
    source: LegacyRegistrySnapshot | None
    destination: DestinationSnapshot
    confirmation_token: str | None = None
    issues: tuple[str, ...] = ()
    _unit: PrivateConsoleUnit | None = None

    def public_summary(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "source": None,
            "destination": {
                "schema_version": self.destination.schema_version,
                "authority": self.destination.authority,
                "agent_count": self.destination.agent_count,
            },
            "issues": list(self.issues),
            "writes_performed": False,
        }
        if self.source is not None:
            payload["source"] = {
                "sha256": self.source.sha256,
                "agent_count": len(self.source.records),
                "agents": [
                    public_agent_record(record.agent)
                    for record in self.source.records
                ],
            }
        if self.confirmation_token is not None:
            payload["confirmation_token"] = self.confirmation_token
            payload["backup_required"] = True
        return payload


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _destination_snapshot(unit: PrivateConsoleUnit) -> DestinationSnapshot:
    with TemporaryDirectory(prefix="mentat-agent-destination-") as temporary:
        path = Path(temporary) / "mentat.sqlite3"
        path.write_bytes(unit.database_raw)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        try:
            version = int(
                connection.execute(
                    "SELECT MAX(version) FROM schema_migrations"
                ).fetchone()[0]
                or 0
            )
            receipt = authority_receipt(connection) if version >= 8 else None
            if version >= 8 and receipt is None:
                occupied = sum(
                    int(
                        connection.execute(
                            f"SELECT COUNT(*) FROM {table}"
                        ).fetchone()[0]
                    )
                    for table in ("mentat_agents", "agent_runtime_configs")
                )
                if occupied:
                    raise AgentRegistryMigrationError(
                        "agent_registry_migration.destination_occupied"
                    )
            if receipt is not None:
                count = len(
                    validate_registry_connection(
                        connection,
                        supported_runtime_types=("codex", "hermes"),
                        runtime_binding_validator=lambda agent, runtime_ref: (
                            codex_binding_is_valid(runtime_ref, agent.capabilities)
                            if agent.runtime_type == "codex"
                            else True
                        ),
                    )
                )
                authority = "embedded"
            else:
                count = 0
                authority = "legacy"
        finally:
            connection.close()
    return DestinationSnapshot(
        schema_version=version,
        database_sha256=hashlib.sha256(unit.database_raw).hexdigest(),
        private_digest=private_console_unit_digest(unit),
        authority=authority,
        agent_count=count,
    )


def _confirmation_token(
    source: LegacyRegistrySnapshot,
    destination: DestinationSnapshot,
) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "protocol_version": PROTOCOL_VERSION,
                "operation": "converge_agent_registry",
                "source_sha256": source.sha256,
                "source_binding": source.source_binding,
                "source_agent_count": len(source.records),
                "source_agents": [
                    public_agent_record(record.agent)
                    for record in source.records
                ],
                "destination_schema_version": destination.schema_version,
                "destination_database_sha256": destination.database_sha256,
                "destination_private_digest": destination.private_digest,
                "destination_authority": destination.authority,
                "backup_required": True,
            }
        )
    ).hexdigest()


def preview_agent_registry_migration(
    data_root: Path,
) -> AgentRegistryMigrationPreview:
    root = Path(data_root)
    blocked_destination = DestinationSnapshot(0, "", "", "unknown", 0)
    try:
        if mentat_server_active(root):
            return AgentRegistryMigrationPreview(
                status="blocked",
                source=None,
                destination=blocked_destination,
                issues=("agent_registry_migration.server_active",),
            )
        if private_control_issue(root) is not None:
            return AgentRegistryMigrationPreview(
                status="blocked",
                source=None,
                destination=blocked_destination,
                issues=("agent_registry_migration.private_state_invalid",),
            )
        unit = capture_private_console_unit(root, harden_source=False)
        destination = _destination_snapshot(unit)
        if destination.authority == "embedded":
            return AgentRegistryMigrationPreview(
                status="already_converged",
                source=None,
                destination=destination,
                _unit=unit,
            )
        source = capture_legacy_registry_snapshot(
            root,
            runtime_binding_validator=lambda agent, runtime_ref: (
                codex_binding_is_valid(runtime_ref, agent.capabilities)
                if agent.runtime_type == "codex"
                else True
            ),
        )
        if destination.schema_version > DATABASE_SCHEMA_VERSION:
            raise AgentRegistryMigrationError(
                "agent_registry_migration.destination_newer"
            )
        if unit.registry_database_raw is None:
            raise AgentRegistryMigrationError(
                "agent_registry_migration.source_missing"
            )
        if not hmac.compare_digest(agent_registry_digest(unit), source.sha256):
            raise AgentRegistryMigrationError(
                "agent_registry_migration.source_changed"
            )
        token = _confirmation_token(source, destination)
        return AgentRegistryMigrationPreview(
            status="ready",
            source=source,
            destination=destination,
            confirmation_token=token,
            _unit=unit,
        )
    except (AgentRegistryError, AgentRegistryMigrationError, OSError, sqlite3.Error):
        return AgentRegistryMigrationPreview(
            status="blocked",
            source=None,
            destination=blocked_destination,
            issues=("agent_registry_migration.invalid",),
        )


def _verified_backup(
    root: Path,
    root_descriptor: int | None,
    *,
    backup_name: str,
    expected_unit: PrivateConsoleUnit,
) -> None:
    _raw, documents, private_unit, format_version, _binding = _read_internal_backup(
        root,
        backup_name,
        root_descriptor,
    )
    if (
        format_version != 3
        or private_unit is None
        or private_console_unit_digest(private_unit)
        != private_console_unit_digest(expected_unit)
    ):
        raise AgentRegistryMigrationError(
            "agent_registry_migration.backup_mismatch",
            writes_performed=True,
        )
    current_documents = _load_live_documents(root, root_descriptor)
    if [(item.name, item.raw) for item in documents] != [
        (item.name, item.raw) for item in current_documents
    ]:
        raise AgentRegistryMigrationError(
            "agent_registry_migration.backup_mismatch",
            writes_performed=True,
        )


def _insert_source(
    connection: sqlite3.Connection,
    source: LegacyRegistrySnapshot,
) -> float:
    if authority_receipt(connection) is not None:
        raise AgentRegistryMigrationError(
            "agent_registry_migration.already_converged",
            writes_performed=True,
        )
    occupied = sum(
        int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("mentat_agents", "agent_runtime_configs")
    )
    if occupied:
        raise AgentRegistryMigrationError(
            "agent_registry_migration.destination_occupied",
            writes_performed=True,
        )
    for record in source.records:
        connection.execute(
            "INSERT INTO agent_runtime_configs (id, runtime_type, "
            "runtime_agent_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                record.binding.id,
                record.binding.runtime_type,
                record.binding.runtime_agent_ref,
                record.config_created_at,
                record.config_updated_at,
            ),
        )
        connection.execute(
            "INSERT INTO mentat_agents (id, name, runtime_config_id, "
            "capabilities_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.agent.id,
                record.agent.name,
                record.binding.id,
                json.dumps(
                    sorted(record.agent.capabilities),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                record.agent_created_at,
                record.agent_updated_at,
            ),
        )
    cutover_at = time.time()
    if not math.isfinite(cutover_at) or cutover_at <= 0:
        raise AgentRegistryMigrationError(
            "agent_registry_migration.clock_invalid",
            writes_performed=True,
        )
    connection.execute(
        "INSERT INTO mentat_agent_registry_state (singleton, authority, "
        "migration_contract, source_kind, source_sha256, source_agent_count, "
        "cutover_at) VALUES (1, 'sqlite', ?, 'legacy', ?, ?, ?)",
        (
            AGENT_REGISTRY_AUTHORITY_CONTRACT,
            source.sha256,
            len(source.records),
            cutover_at,
        ),
    )
    agents = validate_registry_connection(
        connection,
        supported_runtime_types=("codex", "hermes"),
        runtime_binding_validator=lambda agent, runtime_ref: (
            codex_binding_is_valid(runtime_ref, agent.capabilities)
            if agent.runtime_type == "codex"
            else True
        ),
    )
    receipt = authority_receipt(connection, required=True)
    if (
        len(agents) != len(source.records)
        or receipt.source_sha256 != source.sha256
        or receipt.source_agent_count != len(source.records)
    ):
        raise AgentRegistryMigrationError(
            "agent_registry_migration.verification_failed",
            writes_performed=True,
        )
    return cutover_at


def _remove_exact_import_if_present(
    connection: sqlite3.Connection,
    source: LegacyRegistrySnapshot,
    cutover_at: float,
) -> bool:
    """Compensate an uncertain/invalid cutover only when its exact import exists."""

    if connection.in_transaction:
        connection.rollback()
    connection.execute("BEGIN IMMEDIATE")
    try:
        receipt_rows = connection.execute(
            "SELECT authority, migration_contract, source_kind, source_sha256, "
            "source_agent_count, cutover_at FROM mentat_agent_registry_state"
        ).fetchall()
        agent_rows = connection.execute(
            "SELECT id, name, runtime_config_id, capabilities_json, created_at, "
            "updated_at FROM mentat_agents ORDER BY id"
        ).fetchall()
        config_rows = connection.execute(
            "SELECT id, runtime_type, runtime_agent_ref, created_at, updated_at "
            "FROM agent_runtime_configs ORDER BY id"
        ).fetchall()
        if not receipt_rows and not agent_rows and not config_rows:
            connection.rollback()
            return False
        expected_receipt = [
            (
                "sqlite",
                AGENT_REGISTRY_AUTHORITY_CONTRACT,
                "legacy",
                source.sha256,
                len(source.records),
                cutover_at,
            )
        ]
        expected_agents = sorted(
            (
                record.agent.id,
                record.agent.name,
                record.binding.id,
                json.dumps(
                    sorted(record.agent.capabilities),
                    ensure_ascii=True,
                    separators=(",", ":"),
                ),
                record.agent_created_at,
                record.agent_updated_at,
            )
            for record in source.records
        )
        expected_configs = sorted(
            (
                record.binding.id,
                record.binding.runtime_type,
                record.binding.runtime_agent_ref,
                record.config_created_at,
                record.config_updated_at,
            )
            for record in source.records
        )
        if (
            [tuple(row) for row in receipt_rows] != expected_receipt
            or [tuple(row) for row in agent_rows] != expected_agents
            or [tuple(row) for row in config_rows] != expected_configs
        ):
            raise AgentRegistryMigrationError(
                "agent_registry_migration.partial_failure",
                writes_performed=True,
            )
        connection.execute("DELETE FROM mentat_agents")
        connection.execute("DELETE FROM agent_runtime_configs")
        connection.execute("DELETE FROM mentat_agent_registry_state")
        connection.commit()
        if any(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "mentat_agents",
                "agent_runtime_configs",
                "mentat_agent_registry_state",
            )
        ):
            raise AgentRegistryMigrationError(
                "agent_registry_migration.partial_failure",
                writes_performed=True,
            )
        return True
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise


def confirm_agent_registry_migration(
    data_root: Path,
    confirmation_token: str,
) -> dict[str, Any]:
    root = Path(data_root)
    initial = preview_agent_registry_migration(root)
    if (
        initial.status != "ready"
        or initial.confirmation_token is None
        or not hmac.compare_digest(initial.confirmation_token, confirmation_token)
        or initial.source is None
        or initial._unit is None
    ):
        raise AgentRegistryMigrationError(
            "agent_registry_migration.confirmation_invalid"
        )
    backup = create_durable_backup(root)
    if backup.status not in {"created", "existing"} or backup.backup_name is None:
        raise AgentRegistryMigrationError("agent_registry_migration.backup_failed")
    committed = False
    try:
        with _durable_mutation_lock(root) as root_descriptor:
            if (
                not _pinned_root_matches(root, root_descriptor)
                or mentat_server_active(root)
            ):
                raise AgentRegistryMigrationError(
                    "agent_registry_migration.server_active",
                    writes_performed=True,
                )
            connection: sqlite3.Connection | None = None
            source_for_cleanup: LegacyRegistrySnapshot | None = None
            cutover_for_cleanup: float | None = None
            try:
                with _hold_legacy_registry_cutover_lock(root) as validate_source:
                    current = preview_agent_registry_migration(root)
                    if (
                        current.status != "ready"
                        or current.confirmation_token is None
                        or not hmac.compare_digest(
                            current.confirmation_token,
                            confirmation_token,
                        )
                        or current.source is None
                        or current._unit is None
                    ):
                        raise AgentRegistryMigrationError(
                            "agent_registry_migration.changed",
                            writes_performed=True,
                        )
                    _verified_backup(
                        root,
                        root_descriptor,
                        backup_name=backup.backup_name,
                        expected_unit=current._unit,
                    )
                    connection = connect_for_agent_registry_migration(root)
                    connection.row_factory = sqlite3.Row
                    source_for_cleanup = current.source
                    connection.execute("BEGIN IMMEDIATE")
                    try:
                        cutover_for_cleanup = _insert_source(
                            connection,
                            current.source,
                        )
                        validate_source()
                        connection.commit()
                        committed = True
                        validate_source()
                    except Exception:
                        if connection.in_transaction:
                            connection.rollback()
                        raise
            except Exception:
                if (
                    connection is not None
                    and source_for_cleanup is not None
                    and cutover_for_cleanup is not None
                ):
                    if _remove_exact_import_if_present(
                        connection,
                        source_for_cleanup,
                        cutover_for_cleanup,
                    ):
                        committed = False
                raise
            finally:
                if connection is not None:
                    connection.close()
        migrated = capture_private_console_unit(root)
        if (
            migrated.registry_database_raw is not None
            or migrated.agent_count != len(initial.source.records)
            or not hmac.compare_digest(
                agent_registry_digest(migrated),
                initial.source.sha256,
            )
        ):
            raise AgentRegistryMigrationError(
                "agent_registry_migration.verification_failed",
                writes_performed=True,
            )
        return {
            "status": "migrated",
            "agent_count": migrated.agent_count,
            "backup_name": backup.backup_name,
            "writes_performed": True,
        }
    except AgentRegistryMigrationError:
        raise
    except Exception as exc:
        raise AgentRegistryMigrationError(
            "agent_registry_migration.partial_failure"
            if committed
            else "agent_registry_migration.failed",
            writes_performed=True,
        ) from exc


__all__ = [
    "AgentRegistryMigrationError",
    "AgentRegistryMigrationPreview",
    "confirm_agent_registry_migration",
    "preview_agent_registry_migration",
]
