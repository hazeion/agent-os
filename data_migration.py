"""Preview and execute bounded legacy durable-JSON migration.

This module intentionally migrates only the fixed public-safe JSON inventory.
Schema evolution, general backup/restore, private runtime movement, and legacy
cleanup remain separate reviewed capabilities.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping
import zipfile

from data_layout import (
    DATA_ROOT_DIRECTORY_NAMES,
    INITIALIZATION_LOCK_NAME,
    MAX_PREFLIGHT_JSON_BYTES,
    SEED_FILE_NAMES,
    _DestinationExistsError,
    _absolute_without_following,
    _initialization_lock,
    _json_file_state,
    _open_directory_no_follow,
    _open_readonly_no_follow,
    _path_contains,
    _promote_seed_copy,
    _read_validated_seed_bytes,
    _redirected_component_issue,
    _root_is_too_broad,
    _root_issue,
    _same_path,
    _secure_directory,
    _temporary_seed_path,
    _windows_close_handle,
    _windows_input_root_guards,
    _windows_open_directory_chain,
    _write_seed_temporary,
)


MIGRATION_PROTOCOL_VERSION = 1
MIGRATION_SCHEMA_VERSION = "unversioned-json-v1"
MIGRATION_STATE_NAME = "legacy-migration-state-v1.json"
MIGRATION_RECEIPT_NAME = "legacy-migration-receipt-v1.json"
MIGRATION_BACKUP_PREFIX = "legacy-migration-v1-"
MAX_MIGRATION_CONTROL_BYTES = 1024 * 1024
MAX_MIGRATION_BACKUP_BYTES = (
    len(SEED_FILE_NAMES) * MAX_PREFLIGHT_JSON_BYTES
    + MAX_MIGRATION_CONTROL_BYTES
)
_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
_BACKUP_RE = re.compile(r"^legacy-migration-v1-([0-9a-f]{24})\.zip$")
_BACKUP_TEMP_RE = re.compile(
    r"^\.legacy-migration-v1-[0-9a-f]{24}\.zip\.mentat-init-[0-9a-f]{32}\.tmp$"
)
_CONTROL_TEMP_RE = re.compile(
    r"^\.legacy-migration-(?:state|receipt)-v1\.json\.mentat-init-[0-9a-f]{32}\.tmp$"
)
_JSON_STORE_TEMP_RE = re.compile(
    r"^\.(?:"
    + "|".join(re.escape(name) for name in SEED_FILE_NAMES)
    + r")\.[0-9a-f]{32}\.tmp$"
)
_BOUNDED_SOURCE_ISSUES = {
    f"{label}_{reason}:{name}"
    for label in ("seed", "legacy")
    for reason in (
        "missing",
        "unreadable",
        "symlink",
        "not_regular",
        "too_large",
        "invalid_json",
        "invalid_shape",
    )
    for name in SEED_FILE_NAMES
}
_EXCLUDED_ITEMS = (
    {
        "name": "runtime/",
        "classification": "deferred_private_runtime",
        "action": "excluded",
    },
)


@dataclass(frozen=True)
class LegacyMigrationItem:
    name: str
    source: str
    destination: str
    classification: str = "durable_operator"
    schema_version: str = MIGRATION_SCHEMA_VERSION
    action: str = "migrate"

    def public_summary(self) -> dict[str, str]:
        return {
            "name": self.name,
            "source": self.source,
            "destination": self.destination,
            "classification": self.classification,
            "schema_version": self.schema_version,
            "action": self.action,
        }


@dataclass(frozen=True)
class _MigrationSnapshot:
    name: str
    source: str
    raw: bytes = field(repr=False)
    digest: str

    @property
    def size(self) -> int:
        return len(self.raw)


@dataclass(frozen=True)
class LegacyMigrationPreview:
    status: str
    items: tuple[LegacyMigrationItem, ...]
    excluded: tuple[dict[str, str], ...] = _EXCLUDED_ITEMS
    issues: tuple[str, ...] = ()
    confirmation_token: str | None = None
    _snapshots: tuple[_MigrationSnapshot, ...] = field(default=(), repr=False)

    def public_summary(self) -> dict:
        return {
            "status": self.status,
            "items": [item.public_summary() for item in self.items],
            "excluded": [dict(item) for item in self.excluded],
            "issues": list(self.issues),
            "confirmation_token": self.confirmation_token,
        }


@dataclass(frozen=True)
class LegacyMigrationResultItem:
    name: str
    status: str

    def public_summary(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status}


@dataclass(frozen=True)
class LegacyMigrationResult:
    status: str
    items: tuple[LegacyMigrationResultItem, ...]
    issues: tuple[str, ...] = ()

    def public_summary(self) -> dict:
        return {
            "status": self.status,
            "items": [item.public_summary() for item in self.items],
            "issues": list(self.issues),
        }


def _blocked_items() -> tuple[LegacyMigrationItem, ...]:
    return tuple(
        LegacyMigrationItem(
            name=name,
            source="unavailable",
            destination=name,
            action="blocked",
        )
        for name in SEED_FILE_NAMES
    )


def _blocked_preview(status: str, *issues: str) -> LegacyMigrationPreview:
    return LegacyMigrationPreview(status=status, items=_blocked_items(), issues=tuple(issues))


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


def _migration_items(
    snapshots: tuple[_MigrationSnapshot, ...],
    actions: Mapping[str, str],
) -> tuple[LegacyMigrationItem, ...]:
    return tuple(
        LegacyMigrationItem(
            name=snapshot.name,
            source=snapshot.source,
            destination=snapshot.name,
            action=actions.get(snapshot.name, "migrate"),
        )
        for snapshot in snapshots
    )


def _preview_token(
    seed_root: Path,
    legacy_root: Path,
    data_root: Path,
    snapshots: tuple[_MigrationSnapshot, ...],
) -> str:
    bound = {
        "protocol_version": MIGRATION_PROTOCOL_VERSION,
        "seed_root": os.fspath(seed_root),
        "legacy_root": os.fspath(legacy_root),
        "data_root": os.fspath(data_root),
        "expected_target_state": "empty",
        "items": [
            {
                "name": snapshot.name,
                "source": snapshot.source,
                "destination": snapshot.name,
                "classification": "durable_operator",
                "schema_version": MIGRATION_SCHEMA_VERSION,
                "action": "migrate",
                "size": snapshot.size,
                "digest": snapshot.digest,
            }
            for snapshot in snapshots
        ],
        "excluded": list(_EXCLUDED_ITEMS),
    }
    return _digest(_canonical_json(bound))


def _read_control_json(path: Path) -> dict | None:
    if not os.path.lexists(os.fspath(path)):
        return None
    if _redirected_component_issue(path, "migration_control") is not None:
        raise OSError("unsafe migration control file")
    descriptor = _open_readonly_no_follow(path)
    try:
        metadata = os.fstat(descriptor)
        if (
            not _owner_only_regular_descriptor(descriptor)
            or metadata.st_size > MAX_MIGRATION_CONTROL_BYTES
        ):
            raise OSError("invalid migration control file")
        raw = b""
        while len(raw) <= MAX_MIGRATION_CONTROL_BYTES:
            chunk = os.read(descriptor, min(64 * 1024, MAX_MIGRATION_CONTROL_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw += chunk
        if len(raw) > MAX_MIGRATION_CONTROL_BYTES:
            raise OSError("migration control file too large")
        document = json.loads(raw.decode("utf-8"))
        if type(document) is not dict:
            raise OSError("invalid migration control document")
        return document
    except (UnicodeError, ValueError, RecursionError, MemoryError) as exc:
        raise OSError("invalid migration control document") from exc
    finally:
        os.close(descriptor)


def _legacy_inventory_issue(legacy_root: Path) -> str | None:
    try:
        entries = {entry.name: entry for entry in legacy_root.iterdir()}
    except OSError:
        return "legacy_root_unreadable"
    allowed = set(SEED_FILE_NAMES) | {"runtime"}
    if set(entries) - allowed:
        return "unsupported_legacy_entries"
    runtime = entries.get("runtime")
    if runtime is not None:
        if _redirected_component_issue(runtime, "legacy_runtime") is not None:
            return "legacy_runtime_linked"
        try:
            metadata = os.lstat(runtime)
        except OSError:
            return "legacy_runtime_unreadable"
        if not stat.S_ISDIR(metadata.st_mode):
            return "legacy_runtime_not_directory"
    return None


def _load_snapshots(seed_root: Path, legacy_root: Path) -> tuple[_MigrationSnapshot, ...]:
    snapshots: list[_MigrationSnapshot] = []
    legacy_count = 0
    for name in SEED_FILE_NAMES:
        seed_present, seed_issue = _json_file_state(
            seed_root / name,
            "seed",
            name,
            required=True,
        )
        if not seed_present or seed_issue is not None:
            raise OSError(seed_issue or f"seed_missing:{name}")
        legacy_present, legacy_issue = _json_file_state(
            legacy_root / name,
            "legacy",
            name,
            required=False,
        )
        if legacy_issue is not None:
            raise OSError(legacy_issue)
        source = "legacy" if legacy_present else "packaged_seed"
        source_path = legacy_root / name if legacy_present else seed_root / name
        if legacy_present:
            legacy_count += 1
        raw = _read_validated_seed_bytes(
            source_path,
            name,
            require_single_link=True,
        )
        snapshots.append(_MigrationSnapshot(name, source, raw, _digest(raw)))
    if not legacy_count:
        raise LookupError("no_legacy_data")
    return tuple(snapshots)


def _safe_json_store_temporary(path: Path) -> bool:
    if _JSON_STORE_TEMP_RE.fullmatch(path.name) is None:
        return False
    try:
        descriptor = _open_readonly_no_follow(path)
    except OSError:
        return False
    try:
        metadata = os.fstat(descriptor)
        return (
            _owner_only_regular_descriptor(descriptor)
            and metadata.st_size <= MAX_PREFLIGHT_JSON_BYTES
        )
    finally:
        os.close(descriptor)


def _target_entries_issue(
    target: Path,
    *,
    allow_safe_json_store_temporaries: bool = False,
) -> str | None:
    if not target.exists():
        return None
    allowed = set(SEED_FILE_NAMES) | set(DATA_ROOT_DIRECTORY_NAMES) | {INITIALIZATION_LOCK_NAME}
    try:
        unsupported = [entry for entry in target.iterdir() if entry.name not in allowed]
    except OSError:
        return "target_root_unreadable"
    if allow_safe_json_store_temporaries:
        unsupported = [
            entry for entry in unsupported if not _safe_json_store_temporary(entry)
        ]
    return "unsupported_target_entries" if unsupported else None


def _target_actions_and_issues(
    target: Path,
    snapshots: tuple[_MigrationSnapshot, ...],
) -> tuple[dict[str, str], tuple[str, ...]]:
    actions = {name: "migrate" for name in SEED_FILE_NAMES}
    issues: list[str] = []
    if not target.exists():
        return actions, ()
    by_name = {snapshot.name: snapshot for snapshot in snapshots}
    for name in SEED_FILE_NAMES:
        exists, issue = _json_file_state(target / name, "target", name, required=False)
        if issue is not None:
            actions[name] = "blocked"
            issues.append(issue)
            continue
        if not exists:
            continue
        try:
            raw = _read_validated_seed_bytes(target / name, name)
        except (OSError, ValueError, TypeError, OverflowError, UnicodeError):
            actions[name] = "blocked"
            issues.append(f"target_unreadable:{name}")
            continue
        if raw != by_name[name].raw:
            actions[name] = "conflict"
            issues.append(f"legacy_destination_conflict:{name}")
            continue
        actions[name] = "verify_existing"
        try:
            descriptor = _open_readonly_no_follow(target / name)
            try:
                if not _owner_only_regular_descriptor(descriptor):
                    actions[name] = "blocked"
                    issues.append(f"target_permissions_unverified:{name}")
            finally:
                os.close(descriptor)
        except OSError:
            actions[name] = "blocked"
            issues.append(f"target_unreadable:{name}")
    return actions, tuple(issues)


def _manifest_document(preview: LegacyMigrationPreview) -> dict:
    token = preview.confirmation_token or ""
    return {
        "protocol_version": MIGRATION_PROTOCOL_VERSION,
        "migration_id": token[:24],
        "schema_version": MIGRATION_SCHEMA_VERSION,
        "items": [
            {
                "name": snapshot.name,
                "source": snapshot.source,
                "classification": "durable_operator",
                "schema_version": MIGRATION_SCHEMA_VERSION,
                "size": snapshot.size,
                "sha256": snapshot.digest,
            }
            for snapshot in preview._snapshots
        ],
        "excluded": list(_EXCLUDED_ITEMS),
    }


def _backup_name(token: str) -> str:
    return f"{MIGRATION_BACKUP_PREFIX}{token[:24]}.zip"


def _control_document(preview: LegacyMigrationPreview, *, complete: bool) -> dict:
    token = preview.confirmation_token or ""
    manifest_raw = _canonical_json(_manifest_document(preview))
    document = {
        "protocol_version": MIGRATION_PROTOCOL_VERSION,
        "migration_id": token[:24],
        "backup_name": _backup_name(token),
        "manifest_sha256": _digest(manifest_raw),
        "items": [
            {
                "name": snapshot.name,
                "source": snapshot.source,
                "size": snapshot.size,
                "sha256": snapshot.digest,
            }
            for snapshot in preview._snapshots
        ],
    }
    if complete:
        document["complete"] = True
    else:
        document["preview_token"] = token
    return document


def _control_matches_preview(document: dict, preview: LegacyMigrationPreview, *, complete: bool) -> bool:
    return document == _control_document(preview, complete=complete)


def _build_backup(preview: LegacyMigrationPreview) -> bytes:
    buffer = io.BytesIO()
    manifest_raw = _canonical_json(_manifest_document(preview))
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for name, raw in (
            ("manifest.json", manifest_raw),
            *((f"data/{snapshot.name}", snapshot.raw) for snapshot in preview._snapshots),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            archive.writestr(info, raw)
    return buffer.getvalue()


def _validated_backup_matches(path: Path, preview: LegacyMigrationPreview) -> bool:
    try:
        descriptor = _open_readonly_no_follow(path)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            metadata = os.fstat(handle.fileno())
            if (
                not _owner_only_regular_descriptor(handle.fileno())
                or metadata.st_size > MAX_MIGRATION_BACKUP_BYTES
            ):
                return False
            with zipfile.ZipFile(handle, "r") as archive:
                expected = ["manifest.json", *(f"data/{name}" for name in SEED_FILE_NAMES)]
                if archive.namelist() != expected:
                    return False
                expected_sizes = {
                    "manifest.json": len(_canonical_json(_manifest_document(preview))),
                    **{
                        f"data/{snapshot.name}": snapshot.size
                        for snapshot in preview._snapshots
                    },
                }
                if archive.comment:
                    return False
                for info in archive.infolist():
                    if (
                        info.flag_bits & 0x1
                        or info.compress_type != zipfile.ZIP_STORED
                        or info.file_size != expected_sizes.get(info.filename)
                        or info.compress_size != info.file_size
                    ):
                        return False
                manifest_raw = archive.read("manifest.json")
                if manifest_raw != _canonical_json(_manifest_document(preview)):
                    return False
                for snapshot in preview._snapshots:
                    if archive.read(f"data/{snapshot.name}") != snapshot.raw:
                        return False
        return True
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError):
        return False


def _receipt_matches_target(target: Path, receipt: dict) -> bool:
    expected_keys = {
        "protocol_version",
        "migration_id",
        "backup_name",
        "manifest_sha256",
        "items",
        "complete",
    }
    if set(receipt) != expected_keys or receipt.get("protocol_version") != MIGRATION_PROTOCOL_VERSION:
        return False
    if receipt.get("complete") is not True:
        return False
    migration_id = receipt.get("migration_id")
    backup_name = receipt.get("backup_name")
    if not isinstance(migration_id, str) or not isinstance(backup_name, str):
        return False
    match = _BACKUP_RE.fullmatch(backup_name)
    if match is None or match.group(1) != migration_id:
        return False
    manifest_sha256 = receipt.get("manifest_sha256")
    if not isinstance(manifest_sha256, str) or not _TOKEN_RE.fullmatch(manifest_sha256):
        return False
    items = receipt.get("items")
    if not isinstance(items, list) or len(items) != len(SEED_FILE_NAMES):
        return False
    by_name: dict[str, dict] = {}
    for item in items:
        if type(item) is not dict or set(item) != {"name", "source", "size", "sha256"}:
            return False
        name = item.get("name")
        if name not in SEED_FILE_NAMES or name in by_name:
            return False
        if item.get("source") not in {"legacy", "packaged_seed"}:
            return False
        if not isinstance(item.get("size"), int) or not 0 <= item["size"] <= MAX_PREFLIGHT_JSON_BYTES:
            return False
        if not isinstance(item.get("sha256"), str) or not _TOKEN_RE.fullmatch(item["sha256"]):
            return False
        by_name[name] = item
    if [item.get("name") for item in items] != list(SEED_FILE_NAMES):
        return False
    if _root_issue(target, "target_root", allow_missing=False) is not None:
        return False
    if _target_entries_issue(
        target,
        allow_safe_json_store_temporaries=True,
    ) is not None:
        return False
    for name in SEED_FILE_NAMES:
        try:
            present, issue = _json_file_state(
                target / name,
                "target",
                name,
                required=True,
            )
            if not present or issue is not None:
                return False
            descriptor = _open_readonly_no_follow(target / name)
            try:
                if not _owner_only_regular_descriptor(descriptor):
                    return False
            finally:
                os.close(descriptor)
        except (OSError, ValueError, TypeError, OverflowError, UnicodeError):
            return False
    backup = target / "backups" / backup_name
    try:
        descriptor = _open_readonly_no_follow(backup)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            metadata = os.fstat(handle.fileno())
            if (
                not _owner_only_regular_descriptor(handle.fileno())
                or metadata.st_size > MAX_MIGRATION_BACKUP_BYTES
            ):
                return False
            with zipfile.ZipFile(handle, "r") as archive:
                expected_names = [
                    "manifest.json",
                    *(f"data/{name}" for name in SEED_FILE_NAMES),
                ]
                if archive.namelist() != expected_names or archive.comment:
                    return False
                manifest_raw = archive.read("manifest.json")
                expected_manifest = {
                    "protocol_version": MIGRATION_PROTOCOL_VERSION,
                    "migration_id": migration_id,
                    "schema_version": MIGRATION_SCHEMA_VERSION,
                    "items": [
                        {
                            "name": item["name"],
                            "source": item["source"],
                            "classification": "durable_operator",
                            "schema_version": MIGRATION_SCHEMA_VERSION,
                            "size": item["size"],
                            "sha256": item["sha256"],
                        }
                        for item in items
                    ],
                    "excluded": list(_EXCLUDED_ITEMS),
                }
                if (
                    manifest_raw != _canonical_json(expected_manifest)
                    or _digest(manifest_raw) != manifest_sha256
                ):
                    return False
                expected_sizes = {
                    "manifest.json": len(manifest_raw),
                    **{f"data/{name}": item["size"] for name, item in by_name.items()},
                }
                for info in archive.infolist():
                    if (
                        info.flag_bits & 0x1
                        or info.compress_type != zipfile.ZIP_STORED
                        or info.file_size != expected_sizes.get(info.filename)
                        or info.compress_size != info.file_size
                    ):
                        return False
                for name in SEED_FILE_NAMES:
                    item = by_name[name]
                    raw = archive.read(f"data/{name}")
                    if len(raw) != item["size"] or _digest(raw) != item["sha256"]:
                        return False
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, RuntimeError):
        return False
    return True


def migration_receipt_valid(data_root: Path) -> bool:
    target = _absolute_without_following(Path(data_root))
    receipt_path = target / "config" / MIGRATION_RECEIPT_NAME
    try:
        receipt = _read_control_json(receipt_path)
    except OSError:
        return False
    return receipt is not None and _receipt_matches_target(target, receipt)


def migration_startup_issue(data_root: Path) -> str | None:
    """Return a bounded issue when migration artifacts are not completed safely."""

    target = _absolute_without_following(Path(data_root))
    state_path = target / "config" / MIGRATION_STATE_NAME
    receipt_path = target / "config" / MIGRATION_RECEIPT_NAME
    state_present = os.path.lexists(os.fspath(state_path))
    receipt_present = os.path.lexists(os.fspath(receipt_path))
    artifact_present = state_present or receipt_present
    config_root = target / "config"
    if os.path.lexists(os.fspath(config_root)):
        try:
            if _redirected_component_issue(config_root, "migration_config") is not None:
                return "invalid_migration_artifacts"
            metadata = os.lstat(config_root)
            if not stat.S_ISDIR(metadata.st_mode):
                return "invalid_migration_artifacts"
            artifact_present = artifact_present or any(
                _CONTROL_TEMP_RE.fullmatch(entry.name) is not None
                for entry in config_root.iterdir()
            )
        except OSError:
            return "invalid_migration_artifacts"
    backup_root = target / "backups"
    if os.path.lexists(os.fspath(backup_root)):
        try:
            if _redirected_component_issue(backup_root, "migration_backups") is not None:
                return "invalid_migration_artifacts"
            metadata = os.lstat(backup_root)
            if not stat.S_ISDIR(metadata.st_mode):
                return "invalid_migration_artifacts"
            artifact_present = artifact_present or any(
                _BACKUP_RE.fullmatch(entry.name) is not None
                or _BACKUP_TEMP_RE.fullmatch(entry.name) is not None
                for entry in backup_root.iterdir()
            )
        except OSError:
            return "invalid_migration_artifacts"
    if not artifact_present:
        return None
    if state_present:
        try:
            if _read_control_json(state_path) is None:
                return "invalid_migration_artifacts"
        except OSError:
            return "invalid_migration_artifacts"
    if migration_receipt_valid(target):
        return None
    return "migration_incomplete_or_invalid"


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


def migration_startup_status(data_root: Path) -> str:
    """Return absent, complete, or invalid under the shared pinned-root lock."""

    target = _absolute_without_following(Path(data_root))
    receipt_path = target / "config" / MIGRATION_RECEIPT_NAME
    if not os.path.lexists(os.fspath(receipt_path)):
        return "invalid" if migration_startup_issue(target) is not None else "absent"
    if _root_issue(target, "target_root", allow_missing=False) is not None:
        return "invalid"
    try:
        with _initialization_lock(target) as root_descriptor:
            if not _pinned_target_matches(target, root_descriptor):
                return "invalid"
            if migration_startup_issue(target) is not None:
                return "invalid"
            if not migration_receipt_valid(target):
                return "invalid"
            if not _pinned_target_matches(target, root_descriptor):
                return "invalid"
            for directory in (target, *(target / name for name in DATA_ROOT_DIRECTORY_NAMES)):
                if not _secure_directory(directory):
                    return "invalid"
            if not _pinned_target_matches(target, root_descriptor):
                return "invalid"
            if not migration_receipt_valid(target):
                return "invalid"
    except (OSError, ValueError, TypeError, OverflowError, UnicodeError):
        return "invalid"
    return "complete"


def migration_status_under_lock(data_root: Path, root_descriptor: int | None) -> str:
    """Recheck migration state while the caller holds the shared root lock."""

    target = _absolute_without_following(Path(data_root))
    receipt_path = target / "config" / MIGRATION_RECEIPT_NAME
    if not _pinned_target_matches(target, root_descriptor):
        return "invalid"
    issue = migration_startup_issue(target)
    if issue is not None:
        return "invalid"
    if not _pinned_target_matches(target, root_descriptor):
        return "invalid"
    if os.path.lexists(os.fspath(receipt_path)):
        if not migration_receipt_valid(target):
            return "invalid"
        if not _pinned_target_matches(target, root_descriptor):
            return "invalid"
        return "complete"
    return "absent"


def _preview_guarded(
    seed_root: Path,
    legacy_root: Path,
    data_root: Path,
    *,
    home: Path | None,
) -> LegacyMigrationPreview:
    home_path = _absolute_without_following(Path(home)) if home is not None else Path.home()
    for root, label, allow_missing in (
        (seed_root, "seed_root", False),
        (legacy_root, "legacy_root", False),
        (data_root, "target_root", True),
    ):
        issue = _root_issue(root, label, allow_missing=allow_missing)
        if issue is not None:
            return _blocked_preview("unsafe", issue)
    if _root_is_too_broad(legacy_root, home_path) or _root_is_too_broad(data_root, home_path):
        return _blocked_preview("unsafe", "migration_root_too_broad")
    if _same_path(legacy_root, data_root) or _path_contains(legacy_root, data_root) or _path_contains(data_root, legacy_root):
        return _blocked_preview("unsafe", "legacy_target_overlap")
    if _same_path(seed_root, data_root) or _path_contains(seed_root, data_root) or _path_contains(data_root, seed_root):
        return _blocked_preview("unsafe", "seed_target_overlap")
    inventory_issue = _legacy_inventory_issue(legacy_root)
    if inventory_issue is not None:
        return _blocked_preview("unsafe", inventory_issue)
    receipt_path = data_root / "config" / MIGRATION_RECEIPT_NAME
    target_entry_issue = _target_entries_issue(
        data_root,
        allow_safe_json_store_temporaries=os.path.lexists(os.fspath(receipt_path)),
    )
    if target_entry_issue is not None:
        return _blocked_preview("unsafe", target_entry_issue)
    try:
        snapshots = _load_snapshots(seed_root, legacy_root)
    except LookupError:
        return _blocked_preview("not_required", "no_legacy_data")
    except (OSError, ValueError, TypeError, OverflowError, UnicodeError) as exc:
        issue = str(exc)
        if issue not in _BOUNDED_SOURCE_ISSUES:
            issue = "migration_source_changed_or_invalid"
        return _blocked_preview("unsafe", issue)

    try:
        receipt = _read_control_json(receipt_path)
    except OSError:
        return _blocked_preview("unsafe", "invalid_migration_receipt")
    if receipt is not None:
        if not _receipt_matches_target(data_root, receipt):
            return _blocked_preview("unsafe", "invalid_migration_receipt")
        return LegacyMigrationPreview(
            status="already_migrated",
            items=_migration_items(
                snapshots,
                {name: "verify_existing" for name in SEED_FILE_NAMES},
            ),
            _snapshots=snapshots,
        )

    target_actions, target_issues = _target_actions_and_issues(data_root, snapshots)
    token = _preview_token(seed_root, legacy_root, data_root, snapshots)
    preview = LegacyMigrationPreview(
        status="ready",
        items=_migration_items(snapshots, target_actions),
        confirmation_token=token,
        _snapshots=snapshots,
    )
    state_path = data_root / "config" / MIGRATION_STATE_NAME
    try:
        state = _read_control_json(state_path)
    except OSError:
        return _blocked_preview("unsafe", "invalid_migration_reservation")
    if state is None:
        if any(action == "blocked" for action in target_actions.values()):
            return LegacyMigrationPreview(
                status="unsafe",
                items=preview.items,
                issues=target_issues,
                _snapshots=snapshots,
            )
        existing_names = {
            name
            for name, action in target_actions.items()
            if action in {"conflict", "verify_existing"}
        }
        if existing_names:
            conflict_actions = dict(target_actions)
            conflict_issues = list(target_issues)
            for name in SEED_FILE_NAMES:
                if name not in existing_names:
                    continue
                conflict_actions[name] = "conflict"
                issue = f"legacy_destination_conflict:{name}"
                if issue not in conflict_issues:
                    conflict_issues.append(issue)
            return LegacyMigrationPreview(
                status="conflict",
                items=_migration_items(snapshots, conflict_actions),
                issues=tuple(conflict_issues),
                _snapshots=snapshots,
            )
        backup = data_root / "backups" / _backup_name(token)
        if os.path.lexists(os.fspath(backup)) and not _validated_backup_matches(
            backup,
            preview,
        ):
            return LegacyMigrationPreview(
                status="unsafe",
                items=preview.items,
                issues=("migration_backup_invalid",),
                _snapshots=snapshots,
            )
        return preview
    if target_issues:
        normalized_issues = tuple(
            issue.replace("legacy_destination_conflict:", "partial_destination_mismatch:", 1)
            for issue in target_issues
        )
        return LegacyMigrationPreview(
            status="unsafe",
            items=preview.items,
            issues=normalized_issues,
            _snapshots=snapshots,
        )
    if not _control_matches_preview(state, preview, complete=False):
        return _blocked_preview("unsafe", "invalid_migration_reservation")
    backup = data_root / "backups" / _backup_name(token)
    if not _validated_backup_matches(backup, preview):
        return _blocked_preview("unsafe", "migration_backup_invalid")
    return LegacyMigrationPreview(
        status="resume_required",
        items=preview.items,
        confirmation_token=token,
        _snapshots=snapshots,
    )


def preview_legacy_migration(
    seed_root: Path,
    legacy_root: Path,
    data_root: Path,
    *,
    home: Path | None = None,
) -> LegacyMigrationPreview:
    seeds = _absolute_without_following(Path(seed_root))
    legacy = _absolute_without_following(Path(legacy_root))
    target = _absolute_without_following(Path(data_root))
    try:
        with _windows_input_root_guards(seeds, legacy):
            return _preview_guarded(seeds, legacy, target, home=home)
    except (OSError, ValueError, TypeError, OverflowError, UnicodeError):
        return _blocked_preview("unsafe", "migration_input_guard_failed")


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


def _publish_destination(
    snapshot: _MigrationSnapshot,
    destination: Path,
    *,
    data_root_fd: int | None,
) -> str:
    if os.path.lexists(os.fspath(destination)):
        if _read_validated_seed_bytes(destination, snapshot.name) != snapshot.raw:
            raise OSError("existing destination mismatch")
        return "verified_existing"
    try:
        _publish_raw_missing(
            destination,
            snapshot.raw,
            parent_fd=data_root_fd,
            maximum=MAX_PREFLIGHT_JSON_BYTES,
        )
    except _DestinationExistsError as exc:
        raise OSError("destination appeared during migration") from exc
    if _read_validated_seed_bytes(destination, snapshot.name) != snapshot.raw:
        raise OSError("destination verification failed")
    descriptor = _open_readonly_no_follow(destination)
    try:
        if not _owner_only_regular_descriptor(descriptor):
            raise OSError("destination permissions unverified")
    finally:
        os.close(descriptor)
    return "migrated"


def _result_blocked(preview: LegacyMigrationPreview, issue: str | None = None) -> LegacyMigrationResult:
    issues = preview.issues if issue is None else (*preview.issues, issue)
    return LegacyMigrationResult(
        status="blocked",
        items=tuple(LegacyMigrationResultItem(name, "blocked") for name in SEED_FILE_NAMES),
        issues=issues,
    )


def migrate_legacy_data(
    seed_root: Path,
    legacy_root: Path,
    data_root: Path,
    *,
    confirmation_token: str,
    home: Path | None = None,
) -> LegacyMigrationResult:
    seeds = _absolute_without_following(Path(seed_root))
    legacy = _absolute_without_following(Path(legacy_root))
    target = _absolute_without_following(Path(data_root))
    initial = preview_legacy_migration(seeds, legacy, target, home=home)
    if initial.status == "already_migrated":
        return _result_blocked(initial, "migration_already_complete")
    if initial.status not in {"ready", "resume_required"}:
        return _result_blocked(initial)
    if not _TOKEN_RE.fullmatch(str(confirmation_token)) or confirmation_token != initial.confirmation_token:
        return _result_blocked(initial, "confirmation_mismatch")

    reservation_written = initial.status == "resume_required"
    result_items: list[LegacyMigrationResultItem] = []
    try:
        with _windows_input_root_guards(seeds, legacy):
            if not _secure_directory(target):
                return _result_blocked(initial, "directory_permissions_unverified")
            with _initialization_lock(target) as data_root_fd:
                for name in DATA_ROOT_DIRECTORY_NAMES:
                    if not _secure_directory(target / name):
                        return _result_blocked(initial, "directory_permissions_unverified")
                with (
                    _guarded_mutation_directory(target / "backups") as backup_fd,
                    _guarded_mutation_directory(target / "config") as config_fd,
                ):
                    current = _preview_guarded(seeds, legacy, target, home=home)
                    if current.status == "already_migrated":
                        return _result_blocked(current, "migration_already_complete")
                    if (
                        current.status not in {"ready", "resume_required"}
                        or current.confirmation_token != confirmation_token
                    ):
                        return _result_blocked(current, "migration_state_changed")

                    backup_path = target / "backups" / _backup_name(confirmation_token)
                    if os.path.lexists(os.fspath(backup_path)):
                        if not _validated_backup_matches(backup_path, current):
                            return _result_blocked(current, "migration_backup_invalid")
                    else:
                        backup_raw = _build_backup(current)
                        _publish_raw_missing(
                            backup_path,
                            backup_raw,
                            parent_fd=backup_fd,
                            maximum=len(backup_raw),
                        )
                        if not _validated_backup_matches(backup_path, current):
                            return _result_blocked(current, "migration_backup_invalid")

                    state_path = target / "config" / MIGRATION_STATE_NAME
                    state_raw = _canonical_json(_control_document(current, complete=False))
                    if os.path.lexists(os.fspath(state_path)):
                        if _read_exact_regular(state_path, MAX_MIGRATION_CONTROL_BYTES) != state_raw:
                            return _result_blocked(current, "invalid_migration_reservation")
                    else:
                        _publish_raw_missing(
                            state_path,
                            state_raw,
                            parent_fd=config_fd,
                            maximum=MAX_MIGRATION_CONTROL_BYTES,
                        )
                    reservation_written = True

                    for snapshot in current._snapshots:
                        status = _publish_destination(
                            snapshot,
                            target / snapshot.name,
                            data_root_fd=data_root_fd,
                        )
                        result_items.append(LegacyMigrationResultItem(snapshot.name, status))

                    for snapshot in current._snapshots:
                        if _read_validated_seed_bytes(target / snapshot.name, snapshot.name) != snapshot.raw:
                            raise OSError("final destination verification failed")

                    receipt_path = target / "config" / MIGRATION_RECEIPT_NAME
                    receipt_raw = _canonical_json(_control_document(current, complete=True))
                    if os.path.lexists(os.fspath(receipt_path)):
                        if _read_exact_regular(receipt_path, MAX_MIGRATION_CONTROL_BYTES) != receipt_raw:
                            raise OSError("migration receipt conflict")
                    else:
                        _publish_raw_missing(
                            receipt_path,
                            receipt_raw,
                            parent_fd=config_fd,
                            maximum=MAX_MIGRATION_CONTROL_BYTES,
                        )
                    if not migration_receipt_valid(target):
                        raise OSError("migration receipt verification failed")
                    return LegacyMigrationResult(
                        "resumed" if initial.status == "resume_required" else "migrated",
                        tuple(result_items),
                    )
    except (OSError, ValueError, TypeError, OverflowError, UnicodeError, zipfile.BadZipFile):
        completed = {item.name for item in result_items}
        return LegacyMigrationResult(
            "partial_failure" if reservation_written else "blocked",
            tuple(
                LegacyMigrationResultItem(
                    name,
                    "published_unverified" if name in completed else "blocked",
                )
                for name in SEED_FILE_NAMES
            ),
            ("migration_incomplete" if reservation_written else "migration_failed",),
        )
