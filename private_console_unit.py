"""Validated snapshots of Mentat's durable private Agent Console unit.

Schema 10 preserves private provider connections and Conversation foundation
alongside embedded Agents,
canonical SQLite Runs, events, Tasks, attachments, and ready blobs even when
the bounded legacy-history projection omits older detail. Schema 4-8 recovery
units remain supported. Runtime scratch and credential values are outside this
boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import shutil
from tempfile import TemporaryDirectory
from typing import Iterable

from agent_registry import (
    AgentRegistryError,
    REGISTRY_DATABASE_NAME,
    authority_receipt,
    initialize_registry_file,
    validate_registry_connection,
)
from codex_runtime import codex_binding_is_valid
from conversation_repository import (
    ConversationRepositoryError,
    validate_repository_connection as validate_conversation_repository_connection,
)
from agent_run_history import (
    DEFAULT_RETENTION,
    LEGACY_SCHEMA_VERSIONS,
    SCHEMA_VERSION as HISTORY_SCHEMA_VERSION,
    _hydrate,
    summarize_run,
)
from agent_console_attachments import MAX_RETAINED_BLOB_BYTES, MAX_RETAINED_BLOBS
from mentat_db import (
    AGENT_REGISTRY_AUTHORITY_CONTRACT,
    EMPTY_AGENT_REGISTRY_SOURCE_SHA256,
    MIGRATIONS,
    SCHEMA_VERSION as DATABASE_SCHEMA_VERSION,
    expected_schema_signature as _expected_schema_signature,
    legacy_agent_registry_artifacts_present_at,
    schema_signature as _schema_signature,
    schema_signature_state as _schema_signature_state,
)
from private_state import (
    blobs_root,
    console_root,
    database_path,
    ensure_console_root,
    history_path,
    inspect_console_root,
)
from run_repository import MAX_SOURCE_RUNS, RunRepository, RunRepositoryError
from task_repository import TaskRepositoryError, validate_repository_connection
from project_repository import ProjectRepositoryError, validate_project_repository_connection
from vercel_connections import (
    VercelConnectionError,
    validate_provider_connections,
    vercel_binding_is_valid,
)


MAX_HISTORY_BYTES = 4 * 1024 * 1024
MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_REGISTRY_DATABASE_BYTES = 4 * 1024 * 1024
MAX_BLOB_BYTES = 10 * 1024 * 1024
MAX_BLOBS = MAX_RETAINED_BLOBS
MAX_PRIVATE_UNIT_BYTES = 96 * 1024 * 1024
LEGACY_DATABASE_SCHEMA_VERSION = 4
PREVIOUS_DATABASE_SCHEMA_VERSION = 5
TASK_DATABASE_SCHEMA_VERSION = 6
RUN_DATABASE_SCHEMA_VERSION = 7
AGENT_DATABASE_SCHEMA_VERSION = 8
PROVIDER_DATABASE_SCHEMA_VERSION = 9
CONVERSATION_DATABASE_SCHEMA_VERSION = 10
SUBMISSION_DATABASE_SCHEMA_VERSION = 11
CONVERSATION_REPAIR_DATABASE_SCHEMA_VERSION = 12
TERMINAL_FINALIZATION_DATABASE_SCHEMA_VERSION = 13
ATTEMPT_DATABASE_SCHEMA_VERSION = 14
ATTACHMENT_DATABASE_SCHEMA_VERSION = 15
PLANNING_CONTEXT_DATABASE_SCHEMA_VERSION = 17
PROJECT_DATABASE_SCHEMA_VERSION = 18
TASK_EXECUTION_DATABASE_SCHEMA_VERSION = 19
TASK_DELEGATION_ACTION_RECEIPT_DATABASE_SCHEMA_VERSION = 21
CODEX_TASK_CREATION_DATABASE_SCHEMA_VERSION = 22
PLANNING_DELETION_DATABASE_SCHEMA_VERSION = 23
SUPPORTED_DATABASE_SCHEMA_VERSIONS = {
    LEGACY_DATABASE_SCHEMA_VERSION,
    PREVIOUS_DATABASE_SCHEMA_VERSION,
    TASK_DATABASE_SCHEMA_VERSION,
    RUN_DATABASE_SCHEMA_VERSION,
    AGENT_DATABASE_SCHEMA_VERSION,
    PROVIDER_DATABASE_SCHEMA_VERSION,
    CONVERSATION_DATABASE_SCHEMA_VERSION,
    SUBMISSION_DATABASE_SCHEMA_VERSION,
    CONVERSATION_REPAIR_DATABASE_SCHEMA_VERSION,
    TERMINAL_FINALIZATION_DATABASE_SCHEMA_VERSION,
    ATTEMPT_DATABASE_SCHEMA_VERSION,
    ATTACHMENT_DATABASE_SCHEMA_VERSION,
    16,
    PLANNING_CONTEXT_DATABASE_SCHEMA_VERSION,
    PROJECT_DATABASE_SCHEMA_VERSION,
    TASK_EXECUTION_DATABASE_SCHEMA_VERSION,
    TASK_DELEGATION_ACTION_RECEIPT_DATABASE_SCHEMA_VERSION,
    CODEX_TASK_CREATION_DATABASE_SCHEMA_VERSION,
    PLANNING_DELETION_DATABASE_SCHEMA_VERSION,
}
STORAGE_KEY_RE = re.compile(r"([0-9a-f]{2})/([0-9a-f]{64})\Z")
RUN_ID_RE = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z")
TASK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
DELEGATION_RECEIPT_ACTIONS = frozenset(
    {
        "delegate",
        "accept",
        "reply",
        "retry",
        "stop",
        "request_revision",
        "mark_blocked",
    }
)
DELEGATION_RECEIPT_STATES = frozenset(
    {"reserved", "submitting", "accepted", "rejected", "unknown", "partial"}
)


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
    registry_database_raw: bytes | None
    blobs: tuple[PrivateBlob, ...]

    @property
    def run_count(self) -> int:
        count = _database_run_count(self.database_raw)
        return count if count is not None else len(_history_run_ids(self.history_raw))

    @property
    def agent_count(self) -> int:
        embedded = _database_agent_count(self.database_raw)
        if embedded is not None:
            if self.registry_database_raw is not None:
                raise PrivateConsoleUnitError("private_agent_registry_duplicate")
            return embedded
        if self.registry_database_raw is None:
            raise PrivateConsoleUnitError("private_agent_registry_missing")
        return _registry_agent_count(self.registry_database_raw)

    @property
    def task_count(self) -> int:
        return _database_task_count(self.database_raw)


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
            registry_database_raw=None,
            blobs=(),
        )


def empty_preconvergence_private_console_unit() -> PrivateConsoleUnit:
    """Return the canonical empty schema-7 unit used by old backup formats."""

    with TemporaryDirectory(prefix="mentat-private-empty-v3-") as temporary:
        database = Path(temporary) / "mentat.sqlite3"
        _initialize_database(database, schema_version=RUN_DATABASE_SCHEMA_VERSION)
        rows = _validate_and_filter_database(database, ())
        if rows:
            raise PrivateConsoleUnitError("private_database_invalid")
        unit = PrivateConsoleUnit(
            history_raw=_empty_history(),
            database_raw=database.read_bytes(),
            registry_database_raw=empty_legacy_registry_raw(),
            blobs=(),
        )
    return validate_private_console_unit(unit)


def empty_legacy_registry_raw() -> bytes:
    """Return the canonical empty standalone registry used by old backups."""

    with TemporaryDirectory(prefix="mentat-empty-legacy-registry-") as temporary:
        path = Path(temporary) / REGISTRY_DATABASE_NAME
        initialize_registry_file(path)
        return path.read_bytes()


def _initialize_database(
    path: Path,
    *,
    schema_version: int = DATABASE_SCHEMA_VERSION,
) -> None:
    if schema_version not in SUPPORTED_DATABASE_SCHEMA_VERSIONS:
        raise PrivateConsoleUnitError("private_database_unsupported")
    connection = sqlite3.connect(path)
    try:
        for version, script in MIGRATIONS:
            if version > schema_version:
                continue
            connection.executescript(script)
        for version, _script in MIGRATIONS:
            if version > schema_version:
                continue
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                (version,),
            )
        if schema_version >= AGENT_DATABASE_SCHEMA_VERSION:
            connection.execute(
                "INSERT OR IGNORE INTO mentat_agent_registry_state ("
                "singleton, authority, migration_contract, source_kind, "
                "source_sha256, source_agent_count, cutover_at"
                ") VALUES (1, 'sqlite', ?, 'fresh', ?, 0, 1)",
                (
                    AGENT_REGISTRY_AUTHORITY_CONTRACT,
                    EMPTY_AGENT_REGISTRY_SOURCE_SHA256,
                ),
            )
        connection.commit()
    finally:
        connection.close()
    if os.name != "nt":
        path.chmod(0o600)


def _sqlite_readonly_uri(path: Path) -> str:
    """Return a platform-correct absolute SQLite URI for one local file."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    return f"{absolute.as_uri()}?mode=ro"


def _validate_registry_snapshot(path: Path) -> int:
    connection = sqlite3.connect(_sqlite_readonly_uri(path), uri=True)
    connection.row_factory = sqlite3.Row
    try:
        agents = validate_registry_connection(
            connection,
            supported_runtime_types=("codex", "hermes"),
            runtime_binding_validator=lambda agent, runtime_agent_ref: (
                codex_binding_is_valid(runtime_agent_ref, agent.capabilities)
                if agent.runtime_type == "codex"
                else True
            ),
        )
        return len(agents)
    except AgentRegistryError as exc:
        raise PrivateConsoleUnitError("private_agent_registry_invalid") from exc
    finally:
        connection.close()


def _validate_embedded_registry(connection: sqlite3.Connection) -> int | None:
    connection.row_factory = sqlite3.Row
    try:
        versions = [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        schema_version = max(versions, default=0)
        provider_ids: frozenset[str] = frozenset()
        if schema_version >= PROVIDER_DATABASE_SCHEMA_VERSION:
            provider_ids = frozenset(
                record.id for record in validate_provider_connections(connection)
            )
        receipt = authority_receipt(connection)
        if receipt is None:
            total = sum(
                int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in ("mentat_agents", "agent_runtime_configs")
            )
            if total:
                raise PrivateConsoleUnitError("private_agent_registry_invalid")
            return None
        return len(
            validate_registry_connection(
                connection,
                supported_runtime_types=(
                    ("codex", "hermes", "vercel")
                    if schema_version >= PROVIDER_DATABASE_SCHEMA_VERSION
                    else ("codex", "hermes")
                ),
                runtime_binding_validator=lambda agent, runtime_agent_ref: (
                    codex_binding_is_valid(runtime_agent_ref, agent.capabilities)
                    if agent.runtime_type == "codex"
                    else vercel_binding_is_valid(
                        runtime_agent_ref,
                        agent.capabilities,
                        provider_ids,
                    )
                    if agent.runtime_type == "vercel"
                    else True
                ),
            )
        )
    except (AgentRegistryError, VercelConnectionError) as exc:
        raise PrivateConsoleUnitError("private_agent_registry_invalid") from exc


def _registry_agent_count(raw: bytes) -> int:
    if len(raw) > MAX_REGISTRY_DATABASE_BYTES:
        raise PrivateConsoleUnitError("private_agent_registry_invalid")
    with TemporaryDirectory(prefix="mentat-agent-count-") as temporary:
        path = Path(temporary) / REGISTRY_DATABASE_NAME
        path.write_bytes(raw)
        if os.name != "nt":
            path.chmod(0o600)
        return _validate_registry_snapshot(path)


def _database_agent_count(raw: bytes) -> int | None:
    if len(raw) > MAX_DATABASE_BYTES:
        raise PrivateConsoleUnitError("private_database_invalid")
    with TemporaryDirectory(prefix="mentat-embedded-agent-count-") as temporary:
        path = Path(temporary) / "mentat.sqlite3"
        path.write_bytes(raw)
        connection = sqlite3.connect(_sqlite_readonly_uri(path), uri=True)
        connection.row_factory = sqlite3.Row
        try:
            versions = [
                int(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            if max(versions, default=0) < AGENT_DATABASE_SCHEMA_VERSION:
                return None
            if authority_receipt(connection) is None:
                return None
            count = _validate_embedded_registry(connection)
            return 0 if count is None else count
        except (sqlite3.Error, AgentRegistryError, PrivateConsoleUnitError) as exc:
            raise PrivateConsoleUnitError(
                "private_agent_registry_invalid"
            ) from exc
        finally:
            connection.close()


def _database_task_count(raw: bytes) -> int:
    if len(raw) > MAX_DATABASE_BYTES:
        raise PrivateConsoleUnitError("private_database_invalid")
    with TemporaryDirectory(prefix="mentat-task-count-") as temporary:
        path = Path(temporary) / "mentat.sqlite3"
        path.write_bytes(raw)
        connection = sqlite3.connect(_sqlite_readonly_uri(path), uri=True)
        connection.row_factory = sqlite3.Row
        try:
            versions = [
                int(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
            version = max(versions, default=0)
            if version not in SUPPORTED_DATABASE_SCHEMA_VERSIONS:
                raise PrivateConsoleUnitError("private_database_unsupported")
            signature_state = _schema_signature_state(connection, version)
            if signature_state == "invalid":
                raise PrivateConsoleUnitError("private_database_schema_invalid")
            if version == LEGACY_DATABASE_SCHEMA_VERSION:
                return 0
            task_count = validate_repository_connection(
                connection,
                require_authority_consistency=version >= TASK_DATABASE_SCHEMA_VERSION,
            )
            if version >= PROJECT_DATABASE_SCHEMA_VERSION:
                validate_project_repository_connection(connection)
            _validate_conversation_repository(
                connection,
                version,
                allow_known_legacy_drift=(
                    signature_state == "known_legacy_conversation_drift"
                ),
            )
            return task_count
        except TaskRepositoryError as exc:
            raise PrivateConsoleUnitError("private_task_repository_invalid") from exc
        except ProjectRepositoryError as exc:
            raise PrivateConsoleUnitError("private_project_repository_invalid") from exc
        except ConversationRepositoryError as exc:
            raise PrivateConsoleUnitError("private_conversation_repository_invalid") from exc
        finally:
            connection.close()


def _validate_conversation_repository(
    connection: sqlite3.Connection,
    schema_version: int,
    *,
    allow_known_legacy_drift: bool = False,
) -> None:
    if schema_version < CONVERSATION_DATABASE_SCHEMA_VERSION:
        return
    try:
        validate_conversation_repository_connection(
            connection,
            schema_version=schema_version,
            allow_known_legacy_drift=allow_known_legacy_drift,
        )
    except ConversationRepositoryError as exc:
        raise PrivateConsoleUnitError("private_conversation_repository_invalid") from exc


def _database_schema_version(path: Path) -> int:
    connection = sqlite3.connect(_sqlite_readonly_uri(path), uri=True)
    try:
        versions = [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
        return max(versions, default=0)
    except sqlite3.Error as exc:
        raise PrivateConsoleUnitError("private_database_invalid") from exc
    finally:
        connection.close()


def _sqlite_run_history(path: Path) -> tuple[bytes, tuple[str, ...]]:
    """Derive a bounded compatibility projection from authoritative Runs."""

    connection = sqlite3.connect(_sqlite_readonly_uri(path), uri=True)
    connection.row_factory = sqlite3.Row
    try:
        run_count = int(connection.execute("SELECT COUNT(*) FROM mentat_runs").fetchone()[0])
        authority_count = int(
            connection.execute("SELECT COUNT(*) FROM mentat_run_store_state").fetchone()[0]
        )
        if authority_count == 0 and run_count == 0:
            return _empty_history(), ()
        if authority_count != 1:
            raise PrivateConsoleUnitError("private_run_repository_invalid")
        repository = RunRepository(connection)
        repository.validate()
        canonical_identifiers = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT id FROM mentat_runs ORDER BY created_at DESC, id DESC"
            )
        )
        if (
            len(canonical_identifiers) != run_count
            or len(set(canonical_identifiers)) != len(canonical_identifiers)
        ):
            raise PrivateConsoleUnitError("private_run_repository_invalid")
        summaries = repository.list_summaries(limit=MAX_SOURCE_RUNS)
        projected = [summarize_run(item) for item in summaries]
        history = _canonical_json(
            {"schema_version": HISTORY_SCHEMA_VERSION, "runs": projected}
        )
        if len(history) > MAX_HISTORY_BYTES:
            # SQLite is canonical. The JSON member exists only for older-build
            # compatibility, so first remove replay-heavy event arrays while
            # preserving every Run and attachment reference that still fits.
            eventless = []
            for item in projected:
                compact = dict(item)
                compact["events"] = []
                compact["event_cursor"] = 0
                eventless.append(compact)
            history = _canonical_json(
                {"schema_version": HISTORY_SCHEMA_VERSION, "runs": eventless}
            )
            if len(history) > MAX_HISTORY_BYTES:
                retained: list[dict] = []
                for item in eventless:
                    candidate = _canonical_json(
                        {
                            "schema_version": HISTORY_SCHEMA_VERSION,
                            "runs": [*retained, item],
                        }
                    )
                    if len(candidate) > MAX_HISTORY_BYTES:
                        break
                    retained.append(item)
                    history = candidate
                if not retained:
                    history = _empty_history()
        return history, canonical_identifiers
    except (sqlite3.Error, RunRepositoryError) as exc:
        raise PrivateConsoleUnitError("private_run_repository_invalid") from exc
    finally:
        connection.close()


def _sqlite_run_authority_claimed(path: Path) -> bool:
    connection = sqlite3.connect(_sqlite_readonly_uri(path), uri=True)
    try:
        return int(
            connection.execute("SELECT COUNT(*) FROM mentat_run_store_state").fetchone()[0]
        ) == 1
    except sqlite3.Error as exc:
        raise PrivateConsoleUnitError("private_database_invalid") from exc
    finally:
        connection.close()


def _sqlite_agent_authority_claimed(path: Path) -> bool:
    connection = sqlite3.connect(_sqlite_readonly_uri(path), uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "mentat_agent_registry_state" not in tables:
            return False
        return authority_receipt(connection) is not None
    except (sqlite3.Error, AgentRegistryError) as exc:
        raise PrivateConsoleUnitError("private_agent_registry_invalid") from exc
    finally:
        connection.close()


def _require_empty_unclaimed_run_store(path: Path) -> None:
    connection = sqlite3.connect(_sqlite_readonly_uri(path), uri=True)
    try:
        total = sum(
            int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
            for name in (
                "mentat_runs",
                "mentat_agent_events",
                "mentat_dispatch_reservations",
                "mentat_task_dispatch_heads",
            )
        )
        if total:
            raise PrivateConsoleUnitError("private_run_repository_invalid")
    except sqlite3.Error as exc:
        raise PrivateConsoleUnitError("private_database_invalid") from exc
    finally:
        connection.close()


def _database_run_count(raw: bytes) -> int | None:
    if len(raw) > MAX_DATABASE_BYTES:
        raise PrivateConsoleUnitError("private_database_invalid")
    with TemporaryDirectory(prefix="mentat-run-count-") as temporary:
        path = Path(temporary) / "mentat.sqlite3"
        path.write_bytes(raw)
        version = _database_schema_version(path)
        if version >= RUN_DATABASE_SCHEMA_VERSION and _sqlite_run_authority_claimed(path):
            _history, run_ids = _sqlite_run_history(path)
            return len(run_ids)
        return None


def _reject_unrecognized_sqlite_artifacts(source: Path) -> None:
    allowed = {
        source.name,
        f"{source.name}-wal",
        f"{source.name}-shm",
    }
    prefix = f"{source.name}-"
    try:
        names = {entry.name for entry in os.scandir(source.parent)}
    except OSError as exc:
        raise PrivateConsoleUnitError("private_database_invalid") from exc
    if any(name.startswith(prefix) and name not in allowed for name in names):
        raise PrivateConsoleUnitError("private_database_unsafe")


def _sqlite_backup(
    source: Path | None,
    destination: Path,
    *,
    copy_source: bool = False,
) -> None:
    if source is None:
        _initialize_database(destination)
        return
    _reject_unrecognized_sqlite_artifacts(source)
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
        # The captured main/WAL set belongs to a private temporary, so SQLite
        # may safely rebuild a fresh SHM cache and recover it without touching
        # the operator source. The backup API produces the standalone snapshot
        # that is subsequently integrity- and schema-validated.
        source_connection = (
            sqlite3.connect(source_for_sqlite)
            if source_temporary is not None
            else sqlite3.connect(_sqlite_readonly_uri(source_for_sqlite), uri=True)
        )
        destination_connection = sqlite3.connect(destination)
        source_connection.backup(destination_connection)
    finally:
        if destination_connection is not None:
            destination_connection.close()
        if source_connection is not None:
            source_connection.close()
        if source_temporary is not None:
            source_temporary.cleanup()
    _reject_unrecognized_sqlite_artifacts(source)
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


def _valid_receipt_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 64:
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _validate_task_delegation_action_receipts(connection: sqlite3.Connection) -> None:
    """Reject corrupt schema-21 receipts before backup or restore accepts them."""

    rows = connection.execute(
        "SELECT key_digest, request_digest, task_id, task_revision, action, "
        "confirmation_digest, delegation_binding_digest, remote_revision_digest, "
        "state, result_task_revision, result_proof_digest, created_at, updated_at, expires_at "
        "FROM mentat_task_delegation_action_receipts"
    ).fetchall()
    for row in rows:
        (
            key_digest,
            request_digest,
            task_id,
            task_revision,
            action,
            confirmation_digest,
            binding_digest,
            remote_revision_digest,
            state,
            result_revision,
            result_proof_digest,
            created_at,
            updated_at,
            expires_at,
        ) = row
        digests = (
            key_digest,
            request_digest,
            confirmation_digest,
            binding_digest,
            remote_revision_digest,
        )
        terminal = state in {"accepted", "rejected"}
        if (
            not all(isinstance(value, str) and SHA256_RE.fullmatch(value) for value in digests)
            or not isinstance(task_id, str)
            or TASK_ID_RE.fullmatch(task_id) is None
            or type(task_revision) is not int
            or task_revision < 1
            or action not in DELEGATION_RECEIPT_ACTIONS
            or state not in DELEGATION_RECEIPT_STATES
            or result_revision is not None
            and (type(result_revision) is not int or result_revision < 1)
            or state == "accepted" and result_revision is None
            or result_proof_digest is not None
            and (
                not isinstance(result_proof_digest, str)
                or SHA256_RE.fullmatch(result_proof_digest) is None
            )
            or state == "accepted" and result_proof_digest is None
            or not _valid_receipt_timestamp(created_at)
            or not _valid_receipt_timestamp(updated_at)
            or terminal
            and (
                isinstance(expires_at, bool)
                or not isinstance(expires_at, (int, float))
                or not math.isfinite(float(expires_at))
                or not float(expires_at) > 0
            )
            or not terminal and expires_at is not None
        ):
            raise PrivateConsoleUnitError("private_delegation_receipt_invalid")


def _validate_codex_task_creation_records(connection: sqlite3.Connection) -> None:
    """Keep schema-22 transient tool grants and receipts backup-safe."""

    grants = connection.execute(
        "SELECT run_id, origin_task_id, origin_task_revision, project_id, agent_id, "
        "runtime_binding_digest, state, thread_id, turn_id, runtime_run_ref, created_at, updated_at "
        "FROM mentat_codex_task_create_grants"
    ).fetchall()
    for row in grants:
        (
            run_id, task_id, revision, project_id, agent_id, digest, state,
            thread_id, turn_id, runtime_ref, created_at, updated_at,
        ) = row
        valid_ids = all(
            isinstance(value, str) and 1 <= len(value) <= 160
            for value in (run_id, task_id, project_id, agent_id)
        )
        valid_digest = isinstance(digest, str) and SHA256_RE.fullmatch(digest)
        valid_time = _valid_receipt_timestamp(created_at) and _valid_receipt_timestamp(updated_at)
        bound = (
            state == "preauthorized" and thread_id is None and turn_id is None and runtime_ref is None
        ) or (
            state == "thread_bound" and isinstance(thread_id, str) and turn_id is None and runtime_ref is None
        ) or (
            state == "armed" and isinstance(thread_id, str) and isinstance(turn_id, str)
            and isinstance(runtime_ref, str) and runtime_ref == f"{thread_id}:{turn_id}"
        )
        if not (
            valid_ids and type(revision) is int and revision >= 1 and valid_digest
            and bound and valid_time
        ):
            raise PrivateConsoleUnitError("private_codex_task_creation_invalid")


    receipts = connection.execute(
        "SELECT origin_run_id, thread_id, turn_id, call_id, request_digest, origin_task_id, "
        "project_id, agent_id, created_task_id, created_task_revision, result_proof_digest, created_at "
        "FROM mentat_codex_task_create_receipts"
    ).fetchall()
    for row in receipts:
        text_values = (row[0], row[1], row[2], row[3], row[5], row[6], row[7], row[8])
        if (
            not all(isinstance(value, str) and 1 <= len(value) <= 160 for value in text_values)
            or type(row[9]) is not int or row[9] < 1
            or not isinstance(row[4], str) or SHA256_RE.fullmatch(row[4]) is None
            or not isinstance(row[10], str) or SHA256_RE.fullmatch(row[10]) is None
            or not _valid_receipt_timestamp(row[11])
        ):
            raise PrivateConsoleUnitError("private_codex_task_creation_invalid")


def _validate_planning_deletion_receipts(connection: sqlite3.Connection) -> None:
    """Accept only the bounded content-free schema-23 deletion tombstones."""

    rows = connection.execute(
        "SELECT confirmation_digest, target_kind, target_digest, closure_digest, "
        "project_count, task_count, conversation_count, run_count, artifact_count, state, created_at "
        "FROM mentat_planning_deletion_receipts"
    ).fetchall()
    if len(rows) > 256:
        raise PrivateConsoleUnitError("private_planning_deletion_receipt_invalid")
    for row in rows:
        confirmation, kind, target, closure, projects, tasks, conversations, runs, artifacts, state, created_at = row
        if (
            not all(isinstance(value, str) and SHA256_RE.fullmatch(value) for value in (confirmation, target, closure))
            or kind not in {"task", "project"}
            or type(projects) is not int or not 0 <= projects <= 256
            or type(tasks) is not int or not 0 <= tasks <= 2048
            or type(conversations) is not int or not 0 <= conversations <= 1024
            or type(runs) is not int or not 0 <= runs <= 10000
            or type(artifacts) is not int or not 0 <= artifacts <= 10000
            or state != "deleted"
            or not _valid_receipt_timestamp(created_at)
        ):
            raise PrivateConsoleUnitError("private_planning_deletion_receipt_invalid")


def _validate_and_filter_database(path: Path, run_ids: Iterable[str]) -> tuple[tuple[str, str, int], ...]:
    retained = tuple(run_ids)
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise PrivateConsoleUnitError("private_database_invalid")
        versions = [int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")]
        schema_version = max(versions, default=0)
        if schema_version not in SUPPORTED_DATABASE_SCHEMA_VERSIONS:
            raise PrivateConsoleUnitError("private_database_unsupported")
        signature_state = _schema_signature_state(connection, schema_version)
        if signature_state == "invalid":
            raise PrivateConsoleUnitError("private_database_schema_invalid")
        if schema_version >= TASK_DELEGATION_ACTION_RECEIPT_DATABASE_SCHEMA_VERSION:
            _validate_task_delegation_action_receipts(connection)
        if schema_version >= CODEX_TASK_CREATION_DATABASE_SCHEMA_VERSION:
            _validate_codex_task_creation_records(connection)
        if schema_version >= PLANNING_DELETION_DATABASE_SCHEMA_VERSION:
            _validate_planning_deletion_receipts(connection)
        if schema_version >= AGENT_DATABASE_SCHEMA_VERSION:
            _validate_embedded_registry(connection)
        if schema_version >= PREVIOUS_DATABASE_SCHEMA_VERSION:
            try:
                validate_repository_connection(
                    connection,
                    require_authority_consistency=(
                        schema_version >= TASK_DATABASE_SCHEMA_VERSION
                    ),
                )
                if schema_version >= PROJECT_DATABASE_SCHEMA_VERSION:
                    validate_project_repository_connection(connection)
            except TaskRepositoryError as exc:
                raise PrivateConsoleUnitError("private_task_repository_invalid") from exc
            except ProjectRepositoryError as exc:
                raise PrivateConsoleUnitError("private_project_repository_invalid") from exc
            _validate_conversation_repository(
                connection,
                schema_version,
                allow_known_legacy_drift=(
                    signature_state == "known_legacy_conversation_drift"
                ),
            )
        if schema_version >= RUN_DATABASE_SCHEMA_VERSION:
            if _sqlite_run_authority_claimed(path):
                _derived_history, derived_ids = _sqlite_run_history(path)
                if set(retained) != set(derived_ids):
                    raise PrivateConsoleUnitError("private_run_repository_invalid")
            else:
                _require_empty_unclaimed_run_store(path)
        placeholders = ",".join("?" for _ in retained)
        if schema_version >= 15:
            connection.execute(
                "DELETE FROM mentat_conversation_staged_attachments"
            )
            connection.execute(
                "DELETE FROM mentat_conversation_staged_contexts"
            )
            if retained:
                connection.execute(
                    f"DELETE FROM mentat_conversation_run_contexts "
                    f"WHERE run_id NOT IN ({placeholders})",
                    retained,
                )
            else:
                connection.execute(
                    "DELETE FROM mentat_conversation_run_contexts"
                )
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
        if sum(row[2] for row in rows) > MAX_RETAINED_BLOB_BYTES:
            raise PrivateConsoleUnitError("private_blob_bytes_exceeded")
        connection.commit()
        connection.execute("VACUUM")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PrivateConsoleUnitError("private_database_invalid")
        if schema_version >= PREVIOUS_DATABASE_SCHEMA_VERSION:
            try:
                validate_repository_connection(
                    connection,
                    require_authority_consistency=(
                        schema_version >= TASK_DATABASE_SCHEMA_VERSION
                    ),
                )
                if schema_version >= PROJECT_DATABASE_SCHEMA_VERSION:
                    validate_project_repository_connection(connection)
            except TaskRepositoryError as exc:
                raise PrivateConsoleUnitError("private_task_repository_invalid") from exc
            except ProjectRepositoryError as exc:
                raise PrivateConsoleUnitError("private_project_repository_invalid") from exc
            _validate_conversation_repository(
                connection,
                schema_version,
                allow_known_legacy_drift=(
                    signature_state == "known_legacy_conversation_drift"
                ),
            )
        if schema_version >= AGENT_DATABASE_SCHEMA_VERSION:
            _validate_embedded_registry(connection)
        if schema_version >= TASK_DELEGATION_ACTION_RECEIPT_DATABASE_SCHEMA_VERSION:
            _validate_task_delegation_action_receipts(connection)
        if schema_version >= CODEX_TASK_CREATION_DATABASE_SCHEMA_VERSION:
            _validate_codex_task_creation_records(connection)
        if schema_version >= PLANNING_DELETION_DATABASE_SCHEMA_VERSION:
            _validate_planning_deletion_receipts(connection)
        if schema_version >= RUN_DATABASE_SCHEMA_VERSION:
            if _sqlite_run_authority_claimed(path):
                _sqlite_run_history(path)
            else:
                _require_empty_unclaimed_run_store(path)
    except sqlite3.Error as exc:
        raise PrivateConsoleUnitError("private_database_invalid") from exc
    finally:
        connection.close()
    return rows


def _inspect_filtered_database(path: Path, run_ids: Iterable[str]) -> tuple[tuple[str, str, int], ...]:
    retained = set(run_ids)
    connection = sqlite3.connect(_sqlite_readonly_uri(path), uri=True)
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise PrivateConsoleUnitError("private_database_invalid")
        versions = [int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")]
        schema_version = max(versions, default=0)
        if schema_version not in SUPPORTED_DATABASE_SCHEMA_VERSIONS:
            raise PrivateConsoleUnitError("private_database_unsupported")
        signature_state = _schema_signature_state(connection, schema_version)
        if signature_state == "invalid":
            raise PrivateConsoleUnitError("private_database_schema_invalid")
        if schema_version >= TASK_DELEGATION_ACTION_RECEIPT_DATABASE_SCHEMA_VERSION:
            _validate_task_delegation_action_receipts(connection)
        if schema_version >= CODEX_TASK_CREATION_DATABASE_SCHEMA_VERSION:
            _validate_codex_task_creation_records(connection)
        if schema_version >= PLANNING_DELETION_DATABASE_SCHEMA_VERSION:
            _validate_planning_deletion_receipts(connection)
        if schema_version >= AGENT_DATABASE_SCHEMA_VERSION:
            _validate_embedded_registry(connection)
        if schema_version >= PREVIOUS_DATABASE_SCHEMA_VERSION:
            try:
                validate_repository_connection(
                    connection,
                    require_authority_consistency=(
                        schema_version >= TASK_DATABASE_SCHEMA_VERSION
                    ),
                )
                if schema_version >= PROJECT_DATABASE_SCHEMA_VERSION:
                    validate_project_repository_connection(connection)
            except TaskRepositoryError as exc:
                raise PrivateConsoleUnitError("private_task_repository_invalid") from exc
            except ProjectRepositoryError as exc:
                raise PrivateConsoleUnitError("private_project_repository_invalid") from exc
            _validate_conversation_repository(
                connection,
                schema_version,
                allow_known_legacy_drift=(
                    signature_state == "known_legacy_conversation_drift"
                ),
            )
        if schema_version >= RUN_DATABASE_SCHEMA_VERSION:
            if _sqlite_run_authority_claimed(path):
                _derived_history, derived_ids = _sqlite_run_history(path)
                if retained != set(derived_ids):
                    raise PrivateConsoleUnitError("private_run_repository_invalid")
            else:
                _require_empty_unclaimed_run_store(path)
        database_runs = {str(row[0]) for row in connection.execute("SELECT DISTINCT run_id FROM run_attachments")}
        if not database_runs.issubset(retained):
            raise PrivateConsoleUnitError("private_database_not_filtered")
        if schema_version >= 15:
            staged_count = int(connection.execute(
                "SELECT (SELECT COUNT(*) FROM mentat_conversation_staged_attachments) "
                "+ (SELECT COUNT(*) FROM mentat_conversation_staged_contexts)"
            ).fetchone()[0])
            context_runs = {
                str(row[0])
                for row in connection.execute(
                    "SELECT run_id FROM mentat_conversation_run_contexts"
                )
            }
            context_digests_valid = True
            for row in connection.execute(
                "SELECT context_pack_id, context_pack_source_digests_json "
                "FROM mentat_conversation_run_contexts"
            ):
                encoded = row[1]
                if row[0] is None:
                    context_digests_valid = encoded is None
                else:
                    try:
                        values = json.loads(encoded)
                    except (TypeError, json.JSONDecodeError):
                        context_digests_valid = False
                    else:
                        context_digests_valid = (
                            isinstance(values, list)
                            and len(values) <= 8
                            and all(
                                isinstance(value, str)
                                and re.fullmatch(r"[0-9a-f]{64}", value)
                                for value in values
                            )
                            and encoded
                            == json.dumps(values, ensure_ascii=True, separators=(",", ":"))
                        )
                if not context_digests_valid:
                    break
            if staged_count or not context_runs.issubset(retained) or not context_digests_valid:
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
        if sum(row[2] for row in rows) > MAX_RETAINED_BLOB_BYTES:
            raise PrivateConsoleUnitError("private_blob_bytes_exceeded")
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
    harden_source: bool = True,
) -> PrivateConsoleUnit:
    """Capture one validated, filtered private unit while the caller holds its lock."""

    requested = console_root(data_root)
    readonly_identity: tuple[tuple[int, int], ...] | None = None
    if source_console is None and harden_source:
        if not os.path.lexists(os.fspath(requested)):
            return empty_private_console_unit()
        canonical = ensure_console_root(data_root)
    elif source_console is None:
        inspected = inspect_console_root(data_root, allow_missing=True)
        if inspected is None:
            return empty_private_console_unit()
        canonical, readonly_identity = inspected
    else:
        canonical = requested
    source = Path(source_console) if source_console is not None else canonical
    if source.is_symlink() or (source.exists() and not source.is_dir()):
        raise PrivateConsoleUnitError("private_console_unsafe")
    database = source / database_path(data_root).name
    database_source = (
        database if os.path.lexists(os.fspath(database)) else None
    )
    with TemporaryDirectory(prefix="mentat-console-capture-") as temporary:
        snapshot_path = Path(temporary) / "mentat.sqlite3"
        registry_database = source / REGISTRY_DATABASE_NAME
        legacy_registry_exists = False
        if database_source is None:
            legacy_registry_exists = os.path.lexists(
                os.fspath(registry_database)
            )
            if (
                not legacy_registry_exists
                and legacy_agent_registry_artifacts_present_at(source)
            ):
                raise PrivateConsoleUnitError("private_agent_registry_unsafe")
            if legacy_registry_exists:
                _initialize_database(
                    snapshot_path,
                    schema_version=RUN_DATABASE_SCHEMA_VERSION,
                )
            else:
                _sqlite_backup(
                    None,
                    snapshot_path,
                    copy_source=copy_sqlite_source,
                )
        else:
            _sqlite_backup(
                database_source,
                snapshot_path,
                copy_source=copy_sqlite_source,
            )
        schema_version = _database_schema_version(snapshot_path)
        run_authority = (
            schema_version >= RUN_DATABASE_SCHEMA_VERSION
            and _sqlite_run_authority_claimed(snapshot_path)
        )
        embedded_agent_authority = (
            schema_version >= AGENT_DATABASE_SCHEMA_VERSION
            and _sqlite_agent_authority_claimed(snapshot_path)
        )
        if run_authority:
            history_raw, run_ids = _sqlite_run_history(snapshot_path)
        else:
            history = source / history_path(data_root).name
            history_raw = (
                _normalized_history(history) if history.exists() else _empty_history()
            )
            run_ids = _history_run_ids(history_raw)
            history_payload = json.loads(history_raw.decode("utf-8"))
            history_raw = _canonical_json(history_payload)
        blob_rows = _validate_and_filter_database(snapshot_path, run_ids)
        connection = sqlite3.connect(_sqlite_readonly_uri(snapshot_path), uri=True)
        try:
            database_references = {
                (str(row[0]), str(row[1]))
                for row in connection.execute("SELECT run_id, attachment_id FROM run_attachments")
            }
        finally:
            connection.close()
        history_references = _history_reference_pairs(history_raw)
        if (
            run_authority
        ):
            if not history_references.issubset(database_references):
                raise PrivateConsoleUnitError("private_history_database_mismatch")
        elif database_references != history_references:
            raise PrivateConsoleUnitError("private_history_database_mismatch")
        database_raw = _safe_regular(snapshot_path, maximum=MAX_DATABASE_BYTES)
        registry_database_raw = None
        if not embedded_agent_authority:
            if database_source is not None:
                legacy_registry_exists = os.path.lexists(
                    os.fspath(registry_database)
                )
                if (
                    not legacy_registry_exists
                    and legacy_agent_registry_artifacts_present_at(source)
                ):
                    raise PrivateConsoleUnitError(
                        "private_agent_registry_unsafe"
                    )
            registry_source = (
                registry_database if legacy_registry_exists else None
            )
            registry_snapshot = Path(temporary) / REGISTRY_DATABASE_NAME
            if registry_source is None:
                initialize_registry_file(registry_snapshot)
            else:
                _sqlite_backup(
                    registry_source,
                    registry_snapshot,
                    copy_source=copy_sqlite_source,
                )
            _validate_registry_snapshot(registry_snapshot)
            registry_database_raw = _safe_regular(
                registry_snapshot,
                maximum=MAX_REGISTRY_DATABASE_BYTES,
            )
    source_blobs = source / "blobs" / "sha256"
    blobs: list[PrivateBlob] = []
    for storage_key, expected_digest, expected_size in blob_rows:
        raw = _safe_regular(_blob_path(source_blobs, storage_key), maximum=MAX_BLOB_BYTES)
        if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_digest:
            raise PrivateConsoleUnitError("private_blob_content_invalid")
        blobs.append(PrivateBlob(storage_key=storage_key, raw=raw))
    if (
        len(history_raw)
        + len(database_raw)
        + len(registry_database_raw or b"")
        + sum(len(blob.raw) for blob in blobs)
        > MAX_PRIVATE_UNIT_BYTES
    ):
        raise PrivateConsoleUnitError("private_unit_too_large")
    unit = PrivateConsoleUnit(
        history_raw=history_raw,
        database_raw=database_raw,
        registry_database_raw=registry_database_raw,
        blobs=tuple(blobs),
    )
    if readonly_identity is not None:
        inspected = inspect_console_root(data_root)
        if inspected is None or inspected[1] != readonly_identity:
            raise PrivateConsoleUnitError("private_console_changed")
    return unit


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
    expected_files = {
        history_path(data_root).name,
        database_path(data_root).name,
    }
    if unit.registry_database_raw is not None:
        expected_files.add(REGISTRY_DATABASE_NAME)
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

    if (
        len(unit.history_raw)
        + len(unit.database_raw)
        + len(unit.registry_database_raw or b"")
        + sum(len(blob.raw) for blob in unit.blobs)
        > MAX_PRIVATE_UNIT_BYTES
    ):
        raise PrivateConsoleUnitError("private_unit_too_large")
    run_ids = _history_run_ids(unit.history_raw)
    with TemporaryDirectory(prefix="mentat-private-validate-") as temporary:
        database = Path(temporary) / "mentat.sqlite3"
        database.write_bytes(unit.database_raw)
        if os.name != "nt":
            database.chmod(0o600)
        schema_version = _database_schema_version(database)
        if (
            schema_version >= RUN_DATABASE_SCHEMA_VERSION
            and _sqlite_run_authority_claimed(database)
        ):
            derived_history, derived_ids = _sqlite_run_history(database)
            if unit.history_raw != derived_history:
                raise PrivateConsoleUnitError("private_history_database_mismatch")
            run_ids = derived_ids
        rows = _inspect_filtered_database(database, run_ids)
        connection = sqlite3.connect(_sqlite_readonly_uri(database), uri=True)
        try:
            database_references = {
                (str(row[0]), str(row[1]))
                for row in connection.execute("SELECT run_id, attachment_id FROM run_attachments")
            }
        finally:
            connection.close()
        history_references = _history_reference_pairs(unit.history_raw)
        if (
            schema_version >= RUN_DATABASE_SCHEMA_VERSION
            and _sqlite_run_authority_claimed(database)
        ):
            if not history_references.issubset(database_references):
                raise PrivateConsoleUnitError("private_history_database_mismatch")
        elif database_references != history_references:
            raise PrivateConsoleUnitError("private_history_database_mismatch")
        embedded_agents = (
            schema_version >= AGENT_DATABASE_SCHEMA_VERSION
            and _sqlite_agent_authority_claimed(database)
        )
        if embedded_agents:
            if unit.registry_database_raw is not None:
                raise PrivateConsoleUnitError("private_agent_registry_duplicate")
        else:
            if unit.registry_database_raw is None:
                raise PrivateConsoleUnitError("private_agent_registry_missing")
            registry_database = Path(temporary) / REGISTRY_DATABASE_NAME
            registry_database.write_bytes(unit.registry_database_raw)
            if os.name != "nt":
                registry_database.chmod(0o600)
            _validate_registry_snapshot(registry_database)
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
        connection = sqlite3.connect(_sqlite_readonly_uri(database), uri=True)
        try:
            logical_database = "\n".join(connection.iterdump()).encode("utf-8")
        finally:
            connection.close()
    if unit.registry_database_raw is None:
        registry_identity = agent_registry_digest(unit)
    else:
        with TemporaryDirectory(
            prefix="mentat-private-registry-identity-"
        ) as temporary:
            registry = Path(temporary) / REGISTRY_DATABASE_NAME
            registry.write_bytes(unit.registry_database_raw)
            connection = sqlite3.connect(
                _sqlite_readonly_uri(registry),
                uri=True,
            )
            try:
                logical_registry = "\n".join(connection.iterdump()).encode(
                    "utf-8"
                )
            finally:
                connection.close()
        registry_identity = hashlib.sha256(logical_registry).hexdigest()
    identity = {
        "history": hashlib.sha256(unit.history_raw).hexdigest(),
        "database": hashlib.sha256(logical_database).hexdigest(),
        "agent_registry": registry_identity,
        "blobs": [(blob.storage_key, blob.sha256, len(blob.raw)) for blob in unit.blobs],
    }
    return hashlib.sha256(_canonical_json(identity)).hexdigest()


def legacy_private_console_unit_digest(unit: PrivateConsoleUnit) -> str:
    """Reproduce the format-2 private-unit receipt used before Agent registry data."""

    validate_private_console_unit(unit)
    with TemporaryDirectory(prefix="mentat-private-legacy-identity-") as temporary:
        database = Path(temporary) / "mentat.sqlite3"
        database.write_bytes(unit.database_raw)
        connection = sqlite3.connect(_sqlite_readonly_uri(database), uri=True)
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


def agent_registry_digest(unit: PrivateConsoleUnit) -> str:
    """Return a storage-neutral digest of validated canonical Agent rows."""

    with TemporaryDirectory(prefix="mentat-agent-registry-identity-") as temporary:
        embedded = unit.registry_database_raw is None
        database = Path(temporary) / (
            "mentat.sqlite3" if embedded else REGISTRY_DATABASE_NAME
        )
        database.write_bytes(
            unit.database_raw if embedded else unit.registry_database_raw or b""
        )
        if os.name != "nt":
            database.chmod(0o600)
        connection = sqlite3.connect(_sqlite_readonly_uri(database), uri=True)
        connection.row_factory = sqlite3.Row
        try:
            if embedded:
                _validate_embedded_registry(connection)
            else:
                validate_registry_connection(
                    connection,
                    supported_runtime_types=("codex", "hermes"),
                    runtime_binding_validator=lambda agent, runtime_agent_ref: (
                        codex_binding_is_valid(
                            runtime_agent_ref,
                            agent.capabilities,
                        )
                        if agent.runtime_type == "codex"
                        else True
                    ),
                )
            rows = [
                {
                    "agent_id": str(row[0]),
                    "name": str(row[1]),
                    "runtime_config_id": str(row[2]),
                    "capabilities": sorted(json.loads(str(row[3]))),
                    "agent_created_at": float(row[4]),
                    "agent_updated_at": float(row[5]),
                    "runtime_type": str(row[6]),
                    "runtime_agent_ref": str(row[7]),
                    "config_created_at": float(row[8]),
                    "config_updated_at": float(row[9]),
                }
                for row in connection.execute(
                    "SELECT a.id, a.name, a.runtime_config_id, "
                    "a.capabilities_json, a.created_at, a.updated_at, "
                    "c.runtime_type, c.runtime_agent_ref, c.created_at, "
                    "c.updated_at FROM mentat_agents AS a JOIN "
                    "agent_runtime_configs AS c ON c.id = a.runtime_config_id "
                    "ORDER BY a.name COLLATE NOCASE, a.id"
                )
            ]
        finally:
            connection.close()
    return hashlib.sha256(_canonical_json(rows)).hexdigest()


def standalone_agent_registry_raw(unit: PrivateConsoleUnit) -> bytes:
    """Materialize Agents as an explicit pre-convergence recovery artifact."""

    if unit.registry_database_raw is not None:
        _registry_agent_count(unit.registry_database_raw)
        return unit.registry_database_raw
    with TemporaryDirectory(prefix="mentat-agent-registry-export-") as temporary:
        source_path = Path(temporary) / "mentat.sqlite3"
        source_path.write_bytes(unit.database_raw)
        destination_path = Path(temporary) / REGISTRY_DATABASE_NAME
        initialize_registry_file(destination_path)
        source = sqlite3.connect(_sqlite_readonly_uri(source_path), uri=True)
        source.row_factory = sqlite3.Row
        destination = sqlite3.connect(destination_path)
        try:
            if _validate_embedded_registry(source) is None:
                raise PrivateConsoleUnitError("private_agent_registry_missing")
            rows = source.execute(
                "SELECT a.id AS agent_id, a.name, a.runtime_config_id, "
                "a.capabilities_json, a.created_at AS agent_created_at, "
                "a.updated_at AS agent_updated_at, c.runtime_type, "
                "c.runtime_agent_ref, c.created_at AS config_created_at, "
                "c.updated_at AS config_updated_at FROM mentat_agents AS a "
                "JOIN agent_runtime_configs AS c ON c.id = a.runtime_config_id "
                "WHERE c.runtime_type IN ('codex', 'hermes') "
                "ORDER BY a.name COLLATE NOCASE, a.id"
            ).fetchall()
            destination.execute("BEGIN IMMEDIATE")
            for row in rows:
                destination.execute(
                    "INSERT INTO agent_runtime_configs (id, runtime_type, "
                    "runtime_agent_ref, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        row["runtime_config_id"],
                        row["runtime_type"],
                        row["runtime_agent_ref"],
                        row["config_created_at"],
                        row["config_updated_at"],
                    ),
                )
                destination.execute(
                    "INSERT INTO mentat_agents (id, name, runtime_config_id, "
                    "capabilities_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        row["agent_id"],
                        row["name"],
                        row["runtime_config_id"],
                        row["capabilities_json"],
                        row["agent_created_at"],
                        row["agent_updated_at"],
                    ),
                )
            destination.commit()
            destination.row_factory = sqlite3.Row
            _validate_registry_snapshot(destination_path)
        except Exception:
            destination.rollback()
            raise
        finally:
            destination.close()
            source.close()
        if os.name != "nt":
            destination_path.chmod(0o600)
        return destination_path.read_bytes()


def schema5_excluded_agent_ids(unit: PrivateConsoleUnit) -> frozenset[str]:
    """Return Agent IDs that the schema-5 compatibility registry cannot carry."""

    if unit.registry_database_raw is not None:
        _registry_agent_count(unit.registry_database_raw)
        return frozenset()
    with TemporaryDirectory(prefix="mentat-schema5-agent-check-") as temporary:
        source_path = Path(temporary) / "mentat.sqlite3"
        source_path.write_bytes(unit.database_raw)
        source = sqlite3.connect(_sqlite_readonly_uri(source_path), uri=True)
        source.row_factory = sqlite3.Row
        try:
            if _validate_embedded_registry(source) is None:
                return frozenset()
            return frozenset(
                str(row[0])
                for row in source.execute(
                    "SELECT a.id FROM mentat_agents AS a JOIN "
                    "agent_runtime_configs AS c ON c.id = a.runtime_config_id "
                    "WHERE c.runtime_type = 'vercel' ORDER BY a.id"
                )
            )
        finally:
            source.close()


def _write_private_file(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
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


def _fsync_private_directory(path: Path) -> None:
    if os.name != "posix":
        return
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise PrivateConsoleUnitError("private_stage_directory_invalid")
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
        if unit.registry_database_raw is not None:
            _write_private_file(
                destination / REGISTRY_DATABASE_NAME,
                unit.registry_database_raw,
            )
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
            registry_database_raw=(
                _safe_regular(
                    destination / REGISTRY_DATABASE_NAME,
                    maximum=MAX_REGISTRY_DATABASE_BYTES,
                )
                if unit.registry_database_raw is not None
                else None
            ),
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
            blob_directories = {
                _blob_path(blob_root, blob.storage_key).parent for blob in unit.blobs
            }
            for directory in sorted(
                blob_directories,
                key=lambda item: len(item.parts),
                reverse=True,
            ):
                _fsync_private_directory(directory)
            for directory in (
                blob_root,
                destination / "blobs",
                destination,
                private,
            ):
                _fsync_private_directory(directory)
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
