"""Private Vercel connection authority and exact offline lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Iterable, Mapping

from agent_registry import (
    AgentRegistry,
    AgentRegistryConflict,
    AgentRegistryError,
)
from agent_runtime import MentatAgent
from mentat_db import (
    SCHEMA_VERSION,
    MentatDatabaseError,
    connect,
    connect_existing_readonly,
    database_path,
    transaction,
)
from private_state import mentat_server_active, private_state_lock


VERCEL_CONNECTION_ID = "connection_vercel"
VERCEL_RUNTIME_TYPE = "vercel"
VERCEL_AGENT_CAPABILITIES = frozenset(
    {"model.generate", "run.events", "run.start", "run.status"}
)
MAX_CONNECTIONS = 1
ACTIVE_RUN_STATUSES = frozenset(
    {
        "reserved",
        "queued",
        "submitting",
        "starting",
        "running",
        "cancelling",
        "waiting",
        "waiting_for_approval",
        "waiting_for_clarification",
        "unknown",
    }
)
_LABEL = re.compile(r"[^\x00-\x1f\x7f]{1,80}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+@/-]{1,159}\Z")
_VERCEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_CONNECTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}\Z")
_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_CONFIRMATION = re.compile(r"vercel_confirm_[0-9a-f]{64}\Z")


class VercelConnectionError(RuntimeError):
    """A bounded provider-connection failure safe for CLI and bridge handling."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class VercelConnectionUnavailable(VercelConnectionError):
    """The private provider authority cannot currently be read."""


@dataclass(frozen=True)
class VercelConnection:
    id: str
    label: str
    state: str
    auth_kind: str
    model: str
    team_id: str | None
    project_id: str | None
    connector: str | None
    connect_scopes: tuple[str, ...]
    revision: int
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class VercelConnectionPreview:
    action: str
    confirmation_token: str
    expected_revision: int | None
    desired: Mapping[str, object]
    _target_root_digest: str

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": "preview",
            "action": self.action,
            "connection_id": VERCEL_CONNECTION_ID,
            "expected_revision": self.expected_revision,
            "change": dict(self.desired),
            "confirmation_token": self.confirmation_token,
            "requires_confirmation": True,
        }


@dataclass(frozen=True)
class VercelRunRecoveryResult:
    run_id: str
    status: str
    partial: bool

    def public_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": self.status,
            "run_id": self.run_id,
            "partial": self.partial,
            "retried": False,
        }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _data_root_identity_digest(data_dir: Path) -> str:
    try:
        root = Path(os.path.abspath(os.fspath(data_dir)))
        details = os.lstat(root)
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise OSError("unsafe data root")
        resolved = root.resolve(strict=True)
    except OSError:
        raise VercelConnectionError("vercel.data_root_invalid")
    evidence = {
        "path": os.path.normcase(os.fspath(resolved)),
        "device": int(details.st_dev),
        "inode": int(details.st_ino),
    }
    return hashlib.sha256(_canonical_json(evidence).encode("ascii")).hexdigest()


def _confirmation(
    action: str,
    current: object,
    desired: object,
    *,
    target_root_digest: str,
) -> str:
    evidence = _canonical_json(
        {
            "contract": "mentat-vercel-connection-v1",
            "action": action,
            "current": current,
            "desired": desired,
            "target_root_digest": target_root_digest,
        }
    ).encode("ascii")
    return "vercel_confirm_" + hashlib.sha256(evidence).hexdigest()


def require_vercel_server_stopped(data_dir: Path) -> None:
    """Fail closed while called under the shared private-state lock."""

    if mentat_server_active(Path(data_dir)):
        raise VercelConnectionError("vercel.server_running")


def vercel_binding_is_valid(
    runtime_agent_ref: str,
    capabilities: Iterable[str],
    provider_ids: Iterable[str],
) -> bool:
    """Validate one schema-9 Agent binding without exposing provider settings."""

    return (
        runtime_agent_ref == VERCEL_CONNECTION_ID
        and runtime_agent_ref in frozenset(provider_ids)
        and frozenset(capabilities) == VERCEL_AGENT_CAPABILITIES
    )


def _validate_label(value: object) -> str:
    label = str(value or "").strip()
    if not _LABEL.fullmatch(label):
        raise VercelConnectionError("vercel.label_invalid")
    return label


def _validate_model(value: object) -> str:
    model = str(value or "").strip()
    if not _MODEL.fullmatch(model) or "/" not in model or "//" in model:
        raise VercelConnectionError("vercel.model_invalid")
    return model


def _validate_vercel_id(value: object, *, required: bool) -> str | None:
    if value is None or str(value).strip() == "":
        if required:
            raise VercelConnectionError("vercel.project_binding_invalid")
        return None
    result = str(value).strip()
    if not _VERCEL_ID.fullmatch(result):
        raise VercelConnectionError("vercel.project_binding_invalid")
    return result


def _validate_connector(value: object) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    connector = str(value).strip()
    if (
        not _CONNECTOR.fullmatch(connector)
        or "//" in connector
        or any(segment in {".", ".."} for segment in connector.split("/"))
    ):
        raise VercelConnectionError("vercel.connector_invalid")
    return connector


def _validate_scopes(values: Iterable[object], *, connector: str | None) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise VercelConnectionError("vercel.scopes_invalid")
    scopes = tuple(sorted({str(value).strip() for value in values}))
    if (
        len(scopes) > 16
        or any(not _SCOPE.fullmatch(scope) for scope in scopes)
        or (connector is None and scopes)
    ):
        raise VercelConnectionError("vercel.scopes_invalid")
    return scopes


def _record_state(record: VercelConnection | None) -> object:
    if record is None:
        return None
    return {
        "id": record.id,
        "label": record.label,
        "state": record.state,
        "auth_kind": record.auth_kind,
        "model": record.model,
        "team_id": record.team_id,
        "project_id": record.project_id,
        "connector": record.connector,
        "connect_scopes": list(record.connect_scopes),
        "revision": record.revision,
    }


def _schema_version(connection: sqlite3.Connection) -> int:
    try:
        versions = [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ]
    except sqlite3.Error as exc:
        raise VercelConnectionError("vercel.connection_corrupt") from exc
    if not versions or versions != list(range(1, versions[-1] + 1)) or versions[-1] not in {9, SCHEMA_VERSION}:
        raise VercelConnectionError("vercel.connection_unsupported")
    return versions[-1]


def validate_provider_connections(
    connection: sqlite3.Connection,
) -> tuple[VercelConnection, ...]:
    """Validate the schema-9 provider rows and return their private records."""

    _schema_version(connection)
    try:
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise VercelConnectionError("vercel.connection_corrupt")
        rows = connection.execute(
            "SELECT id, provider, label, state, auth_kind, model, team_id, "
            "project_id, connector, connect_scopes_json, revision, created_at, "
            "updated_at FROM provider_connections ORDER BY provider, id"
        ).fetchall()
    except sqlite3.Error as exc:
        raise VercelConnectionError("vercel.connection_corrupt") from exc
    if len(rows) > MAX_CONNECTIONS:
        raise VercelConnectionError("vercel.connection_corrupt")
    records: list[VercelConnection] = []
    for row in rows:
        try:
            scopes_value = json.loads(str(row["connect_scopes_json"]))
            if not isinstance(scopes_value, list):
                raise ValueError("scopes")
            connector = _validate_connector(row["connector"])
            scopes = _validate_scopes(scopes_value, connector=connector)
            encoded_scopes = _canonical_json(list(scopes))
            team_id = _validate_vercel_id(row["team_id"], required=False)
            project_id = _validate_vercel_id(row["project_id"], required=False)
            revision = int(row["revision"])
            created_at = float(row["created_at"])
            updated_at = float(row["updated_at"])
            record = VercelConnection(
                id=str(row["id"]),
                label=_validate_label(row["label"]),
                state=str(row["state"]),
                auth_kind=str(row["auth_kind"]),
                model=_validate_model(row["model"]),
                team_id=team_id,
                project_id=project_id,
                connector=connector,
                connect_scopes=scopes,
                revision=revision,
                created_at=created_at,
                updated_at=updated_at,
            )
            if (
                row["provider"] != "vercel"
                or record.id != VERCEL_CONNECTION_ID
                or record.state not in {"configured", "disconnected"}
                or record.auth_kind not in {"api_key", "oidc"}
                or (record.team_id is None) != (record.project_id is None)
                or encoded_scopes != row["connect_scopes_json"]
                or revision < 1
                or not math.isfinite(created_at)
                or not math.isfinite(updated_at)
                or created_at < 0
                or updated_at < created_at
            ):
                raise ValueError("record")
            records.append(record)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise VercelConnectionError("vercel.connection_corrupt") from exc
    return tuple(records)


def _load(connection: sqlite3.Connection) -> VercelConnection | None:
    records = validate_provider_connections(connection)
    return records[0] if records else None


def load_vercel_connection(data_dir: Path) -> VercelConnection | None:
    path = database_path(Path(data_dir))
    if not os.path.lexists(os.fspath(path)):
        return None
    try:
        with connect_existing_readonly(Path(data_dir)) as connection:
            return _load(connection)
    except VercelConnectionError:
        raise
    except (MentatDatabaseError, sqlite3.Error, OSError) as exc:
        raise VercelConnectionUnavailable("vercel.connection_unavailable") from exc


def _credential_present(environment: Mapping[str, str], name: str) -> bool:
    value = environment.get(name)
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 32_768
        and value.isascii()
        and value.strip() == value
        and all(32 < ord(character) < 127 for character in value)
    )


def credential_for_gateway(
    record: VercelConnection,
    environment: Mapping[str, str] = os.environ,
) -> str | None:
    name = "AI_GATEWAY_API_KEY" if record.auth_kind == "api_key" else "VERCEL_OIDC_TOKEN"
    return environment.get(name) if _credential_present(environment, name) else None


def credential_for_vercel_api(
    record: VercelConnection,
    environment: Mapping[str, str] = os.environ,
) -> str | None:
    name = "VERCEL_TOKEN" if record.auth_kind == "api_key" else "VERCEL_OIDC_TOKEN"
    return environment.get(name) if _credential_present(environment, name) else None


def credential_for_connect(
    environment: Mapping[str, str] = os.environ,
) -> str | None:
    name = "VERCEL_OIDC_TOKEN"
    return environment.get(name) if _credential_present(environment, name) else None


def _capability_status(
    record: VercelConnection,
    environment: Mapping[str, str],
) -> list[dict[str, str]]:
    capabilities = [
        {
            "id": "ai.gateway",
            "status": (
                "credential_present"
                if credential_for_gateway(record, environment)
                else "needs_auth"
            ),
        }
    ]
    if record.team_id is not None and record.project_id is not None:
        capabilities.append(
            {
                "id": "sandbox.readiness",
                "status": (
                    "credential_present"
                    if credential_for_vercel_api(record, environment)
                    else "needs_auth"
                ),
            }
        )
    if record.connector is not None:
        capabilities.append(
            {
                "id": "connect.token",
                "status": (
                    "credential_present"
                    if credential_for_connect(environment)
                    else "needs_auth"
                ),
            }
        )
    if record.state == "disconnected":
        return [{**capability, "status": "disconnected"} for capability in capabilities]
    return capabilities


def public_connection_record(
    record: VercelConnection,
    environment: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    capabilities = _capability_status(record, environment)
    gateway_status = capabilities[0]["status"]
    state = (
        "disconnected"
        if record.state == "disconnected"
        else "configured" if gateway_status == "credential_present" else "needs_auth"
    )
    return {
        "id": record.id,
        "provider": "vercel",
        "label": record.label,
        "state": state,
        "model": record.model,
        "capabilities": capabilities,
    }


def public_vercel_connections(
    data_dir: Path,
    environment: Mapping[str, str] = os.environ,
) -> dict[str, object]:
    """Return a fixed browser-safe projection without credential metadata."""

    path = database_path(Path(data_dir))
    if not os.path.lexists(os.fspath(path)):
        return {"schema_version": 1, "connections": [], "count": 0}
    try:
        with connect_existing_readonly(Path(data_dir)) as connection:
            records = validate_provider_connections(connection)
    except VercelConnectionError:
        raise
    except (MentatDatabaseError, sqlite3.Error, OSError) as exc:
        raise VercelConnectionUnavailable("vercel.connection_unavailable") from exc
    public = [public_connection_record(record, environment) for record in records]
    return {
        "schema_version": 1,
        "connections": public,
        "count": len(public),
    }


def preview_configure_vercel(
    data_dir: Path,
    *,
    label: object,
    auth_kind: object,
    model: object,
    team_id: object = None,
    project_id: object = None,
    connector: object = None,
    connect_scopes: Iterable[object] = (),
) -> VercelConnectionPreview:
    safe_auth_kind = str(auth_kind or "").strip()
    if safe_auth_kind not in {"api_key", "oidc"}:
        raise VercelConnectionError("vercel.auth_kind_invalid")
    safe_team = _validate_vercel_id(team_id, required=False)
    safe_project = _validate_vercel_id(project_id, required=False)
    if (safe_team is None) != (safe_project is None):
        raise VercelConnectionError("vercel.project_binding_invalid")
    safe_connector = _validate_connector(connector)
    safe_scopes = _validate_scopes(connect_scopes, connector=safe_connector)
    desired: dict[str, object] = {
        "label": _validate_label(label),
        "auth_kind": safe_auth_kind,
        "model": _validate_model(model),
        "team_id": safe_team,
        "project_id": safe_project,
        "connector": safe_connector,
        "connect_scopes": list(safe_scopes),
        "state": "configured",
    }
    current = load_vercel_connection(data_dir)
    target_root_digest = _data_root_identity_digest(data_dir)
    token = _confirmation(
        "configure",
        _record_state(current),
        desired,
        target_root_digest=target_root_digest,
    )
    return VercelConnectionPreview(
        action="configure",
        confirmation_token=token,
        expected_revision=None if current is None else current.revision,
        desired=desired,
        _target_root_digest=target_root_digest,
    )


def confirm_configure_vercel(
    data_dir: Path,
    preview: VercelConnectionPreview,
    confirmation_token: object,
) -> VercelConnection:
    if preview.action != "configure" or not isinstance(confirmation_token, str):
        raise VercelConnectionError("vercel.confirmation_invalid")
    with private_state_lock(Path(data_dir)):
        require_vercel_server_stopped(data_dir)
        target_root_digest = _data_root_identity_digest(data_dir)
        current = load_vercel_connection(data_dir)
        expected = _confirmation(
            "configure",
            _record_state(current),
            preview.desired,
            target_root_digest=target_root_digest,
        )
        if (
            not hmac.compare_digest(
                preview._target_root_digest,
                target_root_digest,
            )
            or
            not _CONFIRMATION.fullmatch(confirmation_token)
            or not hmac.compare_digest(confirmation_token, expected)
            or not hmac.compare_digest(preview.confirmation_token, expected)
        ):
            raise VercelConnectionError("vercel.confirmation_stale")
        now = time.time()
        connection = connect(Path(data_dir))
        try:
            with transaction(connection, immediate=True):
                if current is None:
                    connection.execute(
                        "INSERT INTO provider_connections (id, provider, label, state, "
                        "auth_kind, model, team_id, project_id, connector, "
                        "connect_scopes_json, revision, created_at, updated_at) "
                        "VALUES (?, 'vercel', ?, 'configured', ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                        (
                            VERCEL_CONNECTION_ID,
                            preview.desired["label"],
                            preview.desired["auth_kind"],
                            preview.desired["model"],
                            preview.desired["team_id"],
                            preview.desired["project_id"],
                            preview.desired["connector"],
                            _canonical_json(preview.desired["connect_scopes"]),
                            now,
                            now,
                        ),
                    )
                else:
                    updated = connection.execute(
                        "UPDATE provider_connections SET label = ?, state = 'configured', "
                        "auth_kind = ?, model = ?, team_id = ?, project_id = ?, "
                        "connector = ?, connect_scopes_json = ?, revision = revision + 1, "
                        "updated_at = ? WHERE id = ? AND revision = ?",
                        (
                            preview.desired["label"],
                            preview.desired["auth_kind"],
                            preview.desired["model"],
                            preview.desired["team_id"],
                            preview.desired["project_id"],
                            preview.desired["connector"],
                            _canonical_json(preview.desired["connect_scopes"]),
                            now,
                            VERCEL_CONNECTION_ID,
                            current.revision,
                        ),
                    ).rowcount
                    if updated != 1:
                        raise VercelConnectionError("vercel.confirmation_stale")
                stored = _load(connection)
                if stored is None:
                    raise VercelConnectionError("vercel.connection_corrupt")
            return stored
        except sqlite3.IntegrityError as exc:
            raise VercelConnectionError("vercel.connection_conflict") from exc
        finally:
            connection.close()


def preview_disconnect_vercel(data_dir: Path) -> VercelConnectionPreview:
    current = load_vercel_connection(data_dir)
    if current is None:
        raise VercelConnectionError("vercel.connection_not_found")
    desired = {"state": "disconnected"}
    target_root_digest = _data_root_identity_digest(data_dir)
    return VercelConnectionPreview(
        action="disconnect",
        confirmation_token=_confirmation(
            "disconnect",
            _record_state(current),
            desired,
            target_root_digest=target_root_digest,
        ),
        expected_revision=current.revision,
        desired=desired,
        _target_root_digest=target_root_digest,
    )


def preview_test_vercel(
    data_dir: Path,
    *,
    capability: object,
) -> VercelConnectionPreview:
    safe_capability = str(capability or "").strip()
    if safe_capability not in {"gateway", "sandbox", "connect"}:
        raise VercelConnectionError("vercel.capability_invalid")
    current = load_vercel_connection(data_dir)
    if current is None or current.state != "configured":
        raise VercelConnectionError("vercel.connection_not_ready")
    desired = {"capability": safe_capability, "operation": "readiness_test"}
    target_root_digest = _data_root_identity_digest(data_dir)
    return VercelConnectionPreview(
        action="test",
        confirmation_token=_confirmation(
            "test",
            _record_state(current),
            desired,
            target_root_digest=target_root_digest,
        ),
        expected_revision=current.revision,
        desired=desired,
        _target_root_digest=target_root_digest,
    )


def validate_test_vercel_confirmation(
    data_dir: Path,
    preview: VercelConnectionPreview,
    confirmation_token: object,
) -> VercelConnection:
    """Revalidate one exact test immediately before its external operation."""

    if preview.action != "test" or not isinstance(confirmation_token, str):
        raise VercelConnectionError("vercel.confirmation_invalid")
    target_root_digest = _data_root_identity_digest(data_dir)
    current = load_vercel_connection(data_dir)
    expected = _confirmation(
        "test",
        _record_state(current),
        preview.desired,
        target_root_digest=target_root_digest,
    )
    if (
        current is None
        or current.state != "configured"
        or not hmac.compare_digest(
            preview._target_root_digest,
            target_root_digest,
        )
        or not _CONFIRMATION.fullmatch(confirmation_token)
        or not hmac.compare_digest(confirmation_token, expected)
        or not hmac.compare_digest(preview.confirmation_token, expected)
    ):
        raise VercelConnectionError("vercel.confirmation_stale")
    return current


def _recoverable_vercel_run(data_dir: Path, run_id: object):
    from run_repository import (
        RunRepository,
        RunRepositoryConflict,
        RunRepositoryError,
    )

    try:
        with connect_existing_readonly(Path(data_dir)) as connection:
            repository = RunRepository(connection)
            repository.authority_receipt(required=True)
            run = repository.get_run(str(run_id or ""))
    except RunRepositoryConflict:
        raise VercelConnectionError("vercel.run_not_found")
    except (MentatDatabaseError, RunRepositoryError, sqlite3.Error, OSError):
        raise VercelConnectionError("vercel.run_unavailable")
    if (
        run.source != "task_dispatch"
        or run.runtime_type != "vercel"
        or run.status != "unknown"
        or run.dispatch_state != "unknown"
        or run.runtime_run_ref is not None
    ):
        raise VercelConnectionError("vercel.run_not_recoverable")
    return run


def _run_recovery_state(run) -> dict[str, object]:
    return {
        "id": run.id,
        "runtime_type": run.runtime_type,
        "status": run.status,
        "dispatch_state": run.dispatch_state,
        "state_revision": run.state_revision,
        "runtime_reference_present": run.runtime_run_ref is not None,
    }


def preview_abandon_vercel_run(
    data_dir: Path,
    *,
    run_id: object,
) -> VercelConnectionPreview:
    current = load_vercel_connection(data_dir)
    if current is None or current.state != "configured":
        raise VercelConnectionError("vercel.connection_not_ready")
    run = _recoverable_vercel_run(data_dir, run_id)
    desired = {
        "operation": "abandon_unknown_submission",
        "run_id": run.id,
        "expected_state_revision": run.state_revision,
        "next_status": "interrupted",
        "retry": False,
    }
    target_root_digest = _data_root_identity_digest(data_dir)
    current_state = {
        "connection": _record_state(current),
        "run": _run_recovery_state(run),
    }
    token = _confirmation(
        "abandon_run",
        current_state,
        desired,
        target_root_digest=target_root_digest,
    )
    return VercelConnectionPreview(
        action="abandon_run",
        confirmation_token=token,
        expected_revision=current.revision,
        desired=desired,
        _target_root_digest=target_root_digest,
    )


def confirm_abandon_vercel_run(
    data_dir: Path,
    preview: VercelConnectionPreview,
    confirmation_token: object,
) -> VercelRunRecoveryResult:
    from run_repository import (
        RunRepository,
        RunRepositoryConflict,
        RunRepositoryError,
    )

    if preview.action != "abandon_run" or not isinstance(confirmation_token, str):
        raise VercelConnectionError("vercel.confirmation_invalid")
    with private_state_lock(Path(data_dir)):
        require_vercel_server_stopped(data_dir)
        target_root_digest = _data_root_identity_digest(data_dir)
        current = load_vercel_connection(data_dir)
        if current is None or current.state != "configured":
            raise VercelConnectionError("vercel.connection_not_ready")
        run = _recoverable_vercel_run(data_dir, preview.desired.get("run_id"))
        current_state = {
            "connection": _record_state(current),
            "run": _run_recovery_state(run),
        }
        expected = _confirmation(
            "abandon_run",
            current_state,
            preview.desired,
            target_root_digest=target_root_digest,
        )
        if (
            not hmac.compare_digest(preview._target_root_digest, target_root_digest)
            or not _CONFIRMATION.fullmatch(confirmation_token)
            or not hmac.compare_digest(confirmation_token, expected)
            or not hmac.compare_digest(preview.confirmation_token, expected)
            or preview.desired.get("expected_state_revision") != run.state_revision
        ):
            raise VercelConnectionError("vercel.confirmation_stale")
        connection = connect(Path(data_dir))
        try:
            recovered = RunRepository(connection).abandon_unknown_vercel_run(
                run.id,
                expected_state_revision=run.state_revision,
            )
        except RunRepositoryConflict:
            raise VercelConnectionError("vercel.confirmation_stale")
        except (MentatDatabaseError, RunRepositoryError, sqlite3.Error, OSError):
            raise VercelConnectionError("vercel.run_recovery_failed")
        finally:
            connection.close()
        return VercelRunRecoveryResult(
            run_id=recovered.id,
            status=recovered.status,
            partial=recovered.partial,
        )


def _active_vercel_run_count(connection: sqlite3.Connection) -> int:
    placeholders = ",".join("?" for _status in ACTIVE_RUN_STATUSES)
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM mentat_runs WHERE runtime_type = 'vercel' "
            f"AND status IN ({placeholders})",
            tuple(sorted(ACTIVE_RUN_STATUSES)),
        ).fetchone()[0]
    )


def confirm_disconnect_vercel(
    data_dir: Path,
    preview: VercelConnectionPreview,
    confirmation_token: object,
) -> VercelConnection:
    if preview.action != "disconnect" or not isinstance(confirmation_token, str):
        raise VercelConnectionError("vercel.confirmation_invalid")
    with private_state_lock(Path(data_dir)):
        require_vercel_server_stopped(data_dir)
        target_root_digest = _data_root_identity_digest(data_dir)
        current = load_vercel_connection(data_dir)
        if current is None:
            raise VercelConnectionError("vercel.connection_not_found")
        expected = _confirmation(
            "disconnect",
            _record_state(current),
            preview.desired,
            target_root_digest=target_root_digest,
        )
        if (
            not hmac.compare_digest(
                preview._target_root_digest,
                target_root_digest,
            )
            or not _CONFIRMATION.fullmatch(confirmation_token)
            or not hmac.compare_digest(confirmation_token, expected)
            or not hmac.compare_digest(preview.confirmation_token, expected)
        ):
            raise VercelConnectionError("vercel.confirmation_stale")
        connection = connect(Path(data_dir))
        try:
            with transaction(connection, immediate=True):
                if _active_vercel_run_count(connection):
                    raise VercelConnectionError("vercel.active_run")
                updated = connection.execute(
                    "UPDATE provider_connections SET state = 'disconnected', "
                    "revision = revision + 1, updated_at = ? "
                    "WHERE id = ? AND revision = ?",
                    (time.time(), VERCEL_CONNECTION_ID, current.revision),
                ).rowcount
                if updated != 1:
                    raise VercelConnectionError("vercel.confirmation_stale")
                stored = _load(connection)
                if stored is None:
                    raise VercelConnectionError("vercel.connection_corrupt")
            return stored
        finally:
            connection.close()


def preview_create_vercel_agent(
    data_dir: Path,
    *,
    name: object,
) -> VercelConnectionPreview:
    current = load_vercel_connection(data_dir)
    if current is None or current.state != "configured":
        raise VercelConnectionError("vercel.connection_not_ready")
    safe_name = _validate_label(name)
    desired = {
        "name": safe_name,
        "runtime_type": VERCEL_RUNTIME_TYPE,
        "runtime_agent_ref": VERCEL_CONNECTION_ID,
        "capabilities": sorted(VERCEL_AGENT_CAPABILITIES),
    }
    target_root_digest = _data_root_identity_digest(data_dir)
    token = _confirmation(
        "create_agent",
        _record_state(current),
        desired,
        target_root_digest=target_root_digest,
    )
    return VercelConnectionPreview(
        action="create_agent",
        confirmation_token=token,
        expected_revision=current.revision,
        desired=desired,
        _target_root_digest=target_root_digest,
    )


def confirm_create_vercel_agent(
    data_dir: Path,
    preview: VercelConnectionPreview,
    confirmation_token: object,
) -> MentatAgent:
    if preview.action != "create_agent" or not isinstance(confirmation_token, str):
        raise VercelConnectionError("vercel.confirmation_invalid")
    with private_state_lock(Path(data_dir)):
        require_vercel_server_stopped(data_dir)
        target_root_digest = _data_root_identity_digest(data_dir)
        current = load_vercel_connection(data_dir)
        expected = _confirmation(
            "create_agent",
            _record_state(current),
            preview.desired,
            target_root_digest=target_root_digest,
        )
        if (
            current is None
            or current.state != "configured"
            or not hmac.compare_digest(
                preview._target_root_digest,
                target_root_digest,
            )
            or not _CONFIRMATION.fullmatch(confirmation_token)
            or not hmac.compare_digest(confirmation_token, expected)
            or not hmac.compare_digest(preview.confirmation_token, expected)
        ):
            raise VercelConnectionError("vercel.confirmation_stale")
        suffix = hashlib.sha256(confirmation_token.encode("ascii")).hexdigest()[:24]
        registry = AgentRegistry(
            Path(data_dir),
            supported_runtime_types=("codex", "hermes", "vercel"),
        )
        try:
            return registry.create_agent(
                agent_id=f"agent_vercel_{suffix}",
                name=str(preview.desired["name"]),
                runtime_config_id=f"runtime_config_vercel_{suffix}",
                runtime_type=VERCEL_RUNTIME_TYPE,
                runtime_agent_ref=VERCEL_CONNECTION_ID,
                capabilities=VERCEL_AGENT_CAPABILITIES,
            )
        except AgentRegistryConflict as exc:
            raise VercelConnectionError("vercel.agent_exists") from exc
        except AgentRegistryError as exc:
            raise VercelConnectionError("vercel.agent_create_failed") from exc


__all__ = [
    "ACTIVE_RUN_STATUSES",
    "VERCEL_AGENT_CAPABILITIES",
    "VERCEL_CONNECTION_ID",
    "VERCEL_RUNTIME_TYPE",
    "VercelConnection",
    "VercelConnectionError",
    "VercelConnectionPreview",
    "VercelConnectionUnavailable",
    "VercelRunRecoveryResult",
    "confirm_abandon_vercel_run",
    "confirm_configure_vercel",
    "confirm_create_vercel_agent",
    "confirm_disconnect_vercel",
    "credential_for_connect",
    "credential_for_gateway",
    "credential_for_vercel_api",
    "load_vercel_connection",
    "preview_abandon_vercel_run",
    "preview_configure_vercel",
    "preview_create_vercel_agent",
    "preview_disconnect_vercel",
    "preview_test_vercel",
    "public_connection_record",
    "public_vercel_connections",
    "require_vercel_server_stopped",
    "validate_provider_connections",
    "validate_test_vercel_confirmation",
    "vercel_binding_is_valid",
]
