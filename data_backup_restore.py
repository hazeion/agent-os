"""Bounded backup and restore for Mentat durable operator and Console state."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import struct
from typing import Any, Mapping
import zipfile

from data_layout import (
    MAX_PREFLIGHT_JSON_BYTES,
    SEED_FILE_NAMES,
    SEED_ROOT_TYPES,
    _absolute_without_following,
    _open_readonly_no_follow,
    _pinned_root_identity,
)
from data_migration import _publish_raw_missing
from data_schema import (
    CURRENT_DOCUMENT_VERSION,
    SCHEMA_FORMAT_VERSION,
    _entry_exists_at,
    _guarded_child_directory,
    _names_from_pinned_directory,
    _pinned_existing_child_directory,
    _pinned_existing_child_directory_state,
    _read_private_artifact_at,
    _unlink_relative,
    schema_preflight_status,
    schema_status_under_lock,
)
from json_store import (
    _durable_mutation_lock,
    _pinned_root_matches,
    _validate_private_descriptor,
    write_json_bytes_atomic,
)
from private_console_unit import (
    MAX_BLOB_BYTES,
    MAX_BLOBS,
    MAX_DATABASE_BYTES,
    MAX_HISTORY_BYTES,
    MAX_PRIVATE_UNIT_BYTES,
    PrivateBlob,
    PrivateConsoleUnit,
    PrivateConsoleUnitError,
    capture_private_console_unit,
    empty_private_console_unit,
    materialize_private_console_unit,
    private_console_unit_digest,
    remove_private_console_tree,
    validate_private_console_unit,
    validate_private_console_stage_inventory,
)
from private_state import mentat_server_active, private_control_issue
from private_state import console_root as private_console_root


BACKUP_FORMAT_VERSION = 2
BACKUP_KIND = "mentat-general-backup"
BACKUP_PREFIX = "mentat-backup-v2-"
LEGACY_BACKUP_PREFIX = "mentat-backup-v1-"
RESTORE_STATE_NAME = "restore-state-v1.json"
MAX_BACKUP_MANIFEST_BYTES = 1024 * 1024
MAX_BACKUP_CENTRAL_DIRECTORY_BYTES = 64 * 1024
MAX_GENERAL_BACKUP_BYTES = (
    len(SEED_FILE_NAMES) * MAX_PREFLIGHT_JSON_BYTES
    + MAX_BACKUP_MANIFEST_BYTES
    + MAX_HISTORY_BYTES
    + MAX_DATABASE_BYTES
    + MAX_PRIVATE_UNIT_BYTES
    + 2 * 1024 * 1024
)
_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
_BACKUP_RE = re.compile(r"^mentat-backup-v([12])-([0-9a-f]{24})\.zip$")
_STATE_TEMP_RE = re.compile(
    r"^\.(restore-state-v1\.json)\.mentat-init-[0-9a-f]{32}\.tmp$"
)
_BACKUP_TEMP_RE = re.compile(
    r"^\.(mentat-backup-v[12]-[0-9a-f]{24}\.zip)\.mentat-init-[0-9a-f]{32}\.tmp$"
)

_EXCLUDED_CLASSES: tuple[dict[str, str], ...] = (
    {"name": "runtime", "classification": "excluded_ephemeral"},
    {"name": "backups", "classification": "excluded_recursive"},
    {"name": "cache", "classification": "excluded_rebuildable"},
    {"name": "logs", "classification": "excluded_local_logs"},
    {"name": "browser", "classification": "excluded_browser_owned"},
    {"name": "external", "classification": "excluded_external_state"},
    {"name": "credentials", "classification": "excluded_secrets"},
    {"name": "config", "classification": "deferred_supported_config"},
)

_BOUNDARY_EXCEPTIONS = (
    OSError,
    ValueError,
    TypeError,
    OverflowError,
    UnicodeError,
    RecursionError,
    MemoryError,
    NotImplementedError,
    zipfile.BadZipFile,
    RuntimeError,
    KeyError,
)


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_json(document: Mapping | list) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


@dataclass(frozen=True)
class _Document:
    name: str
    raw: bytes

    @property
    def size(self) -> int:
        return len(self.raw)

    @property
    def digest(self) -> str:
        return _digest(self.raw)


@dataclass(frozen=True)
class BackupResult:
    status: str
    backup_name: str | None = None
    items: tuple[dict[str, Any], ...] = ()
    issues: tuple[str, ...] = ()

    def public_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "status": self.status,
            "items": [dict(item) for item in self.items],
            "excluded": [dict(item) for item in _EXCLUDED_CLASSES],
            "issues": list(self.issues),
        }
        if self.backup_name is not None:
            summary["backup_name"] = self.backup_name
        return summary


@dataclass(frozen=True)
class RestorePreview:
    status: str
    backup_name: str | None = None
    items: tuple[dict[str, Any], ...] = ()
    confirmation_token: str | None = None
    issues: tuple[str, ...] = ()
    _backup_raw: bytes | None = None
    _backup_documents: tuple[_Document, ...] = ()
    _backup_private: PrivateConsoleUnit | None = None
    _backup_format_version: int = 1
    _target_documents: tuple[_Document, ...] = ()
    _target_private: PrivateConsoleUnit | None = None
    _target_binding: str | None = None
    _state: Mapping[str, Any] | None = None

    def public_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "status": self.status,
            "items": [dict(item) for item in self.items],
            "excluded": [dict(item) for item in _EXCLUDED_CLASSES],
            "issues": list(self.issues),
        }
        if self.backup_name is not None:
            summary["backup_name"] = self.backup_name
        if self.confirmation_token is not None:
            summary["confirmation_token"] = self.confirmation_token
        return summary


@dataclass(frozen=True)
class RestoreResult:
    status: str
    items: tuple[dict[str, Any], ...] = ()
    recovery_backup_name: str | None = None
    issues: tuple[str, ...] = ()

    def public_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "status": self.status,
            "items": [dict(item) for item in self.items],
            "excluded": [dict(item) for item in _EXCLUDED_CLASSES],
            "issues": list(self.issues),
        }
        if self.recovery_backup_name is not None:
            summary["recovery_backup_name"] = self.recovery_backup_name
        return summary


@dataclass(frozen=True)
class _RecoveryArtifact:
    directory: str
    temporary_name: str
    final_name: str
    raw: bytes
    device: int
    inode: int
    links: int
    final_present: bool


def _blocked_backup(*issues: str) -> BackupResult:
    return BackupResult(status="blocked", issues=tuple(issues))


def _blocked_preview(status: str, *issues: str) -> RestorePreview:
    return RestorePreview(status=status, issues=tuple(issues))


def _blocked_result(preview: RestorePreview, *issues: str) -> RestoreResult:
    return RestoreResult(
        status="blocked",
        items=preview.items,
        issues=tuple(issues),
    )


def _document_from_raw(name: str, raw: bytes) -> _Document:
    if name not in SEED_ROOT_TYPES or len(raw) > MAX_PREFLIGHT_JSON_BYTES:
        raise ValueError("durable document invalid")
    payload = json.loads(raw.decode("utf-8"))
    expected_type = SEED_ROOT_TYPES[name]
    if type(payload) is not expected_type:
        raise ValueError("durable document invalid")
    return _Document(name=name, raw=raw)


def _load_live_documents(
    target: Path,
    root_descriptor: int | None,
) -> tuple[_Document, ...]:
    documents: list[_Document] = []
    for name in SEED_FILE_NAMES:
        raw, state = _read_private_artifact_at(
            target / name,
            root_descriptor,
            maximum=MAX_PREFLIGHT_JSON_BYTES,
            maximum_links=1,
        )
        if state.st_nlink != 1:
            raise OSError("durable document links invalid")
        documents.append(_document_from_raw(name, raw))
    return tuple(documents)


def _document_identity(documents: tuple[_Document, ...]) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "classification": "durable_operator",
            "schema_version": CURRENT_DOCUMENT_VERSION,
            "size": item.size,
            "sha256": item.digest,
        }
        for item in documents
    ]


def _private_identity(unit: PrivateConsoleUnit) -> dict[str, Any]:
    return {
        "name": "private_console",
        "classification": "durable_private_consistency_unit",
        "history_schema_version": 3,
        "database_schema_version": 1,
        "history_size": len(unit.history_raw),
        "history_sha256": _digest(unit.history_raw),
        "database_size": len(unit.database_raw),
        "database_sha256": _digest(unit.database_raw),
        "blob_count": len(unit.blobs),
        "blobs": [
            {
                "entry": f"private/blobs/{index:04d}",
                "storage_key": blob.storage_key,
                "size": len(blob.raw),
                "sha256": blob.sha256,
            }
            for index, blob in enumerate(unit.blobs)
        ],
    }


def _backup_id(
    documents: tuple[_Document, ...],
    private_unit: PrivateConsoleUnit | None = None,
    *,
    format_version: int = BACKUP_FORMAT_VERSION,
) -> str:
    if format_version == 1:
        private_items: list[dict[str, Any]] = []
        excluded = [
            {"name": "private_console", "classification": "deferred_private_consistency_unit"},
            *[dict(item) for item in _EXCLUDED_CLASSES],
        ]
    else:
        unit = private_unit or empty_private_console_unit()
        private_items = [_private_identity(unit)]
        excluded = [dict(item) for item in _EXCLUDED_CLASSES]
    identity = {
        "format_version": format_version,
        "kind": BACKUP_KIND,
        "data_schema_format_version": SCHEMA_FORMAT_VERSION,
        "document_version": CURRENT_DOCUMENT_VERSION,
        "items": [*_document_identity(documents), *private_items],
        "excluded": excluded,
    }
    return _digest(_canonical_json(identity))[:24]


def _backup_manifest(
    documents: tuple[_Document, ...],
    private_unit: PrivateConsoleUnit | None = None,
    *,
    format_version: int = BACKUP_FORMAT_VERSION,
) -> dict[str, Any]:
    unit = private_unit or (empty_private_console_unit() if format_version == 2 else None)
    excluded = [dict(item) for item in _EXCLUDED_CLASSES]
    items = _document_identity(documents)
    if format_version == 1:
        excluded.insert(0, {"name": "private_console", "classification": "deferred_private_consistency_unit"})
    else:
        assert unit is not None
        items.append(_private_identity(unit))
    return {
        "format_version": format_version,
        "kind": BACKUP_KIND,
        "backup_id": _backup_id(documents, unit, format_version=format_version),
        "data_schema_format_version": SCHEMA_FORMAT_VERSION,
        "document_version": CURRENT_DOCUMENT_VERSION,
        "items": items,
        "excluded": excluded,
    }


def _backup_name(
    documents: tuple[_Document, ...],
    private_unit: PrivateConsoleUnit | None = None,
    *,
    format_version: int = BACKUP_FORMAT_VERSION,
) -> str:
    prefix = BACKUP_PREFIX if format_version == 2 else LEGACY_BACKUP_PREFIX
    return f"{prefix}{_backup_id(documents, private_unit, format_version=format_version)}.zip"


def _zip_entry(name: str) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_STORED
    entry.create_system = 3
    entry.external_attr = 0o600 << 16
    return entry


def _build_backup(
    documents: tuple[_Document, ...],
    private_unit: PrivateConsoleUnit | None = None,
    *,
    format_version: int = BACKUP_FORMAT_VERSION,
) -> bytes:
    unit = private_unit or (empty_private_console_unit() if format_version == 2 else None)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            _zip_entry("manifest.json"),
            _canonical_json(_backup_manifest(documents, unit, format_version=format_version)),
        )
        for document in documents:
            archive.writestr(_zip_entry(f"data/{document.name}"), document.raw)
        if unit is not None:
            archive.writestr(_zip_entry("private/history.json"), unit.history_raw)
            archive.writestr(_zip_entry("private/mentat.sqlite3"), unit.database_raw)
            for index, blob in enumerate(unit.blobs):
                archive.writestr(_zip_entry(f"private/blobs/{index:04d}"), blob.raw)
    raw = output.getvalue()
    if len(raw) > MAX_GENERAL_BACKUP_BYTES:
        raise OverflowError("general backup too large")
    return raw


def _contents_from_backup(
    raw: bytes,
) -> tuple[tuple[_Document, ...], PrivateConsoleUnit | None, int]:
    if len(raw) > MAX_GENERAL_BACKUP_BYTES:
        raise ValueError("backup_too_large")
    if len(raw) < 22:
        raise ValueError("backup_container_invalid")
    (
        signature,
        disk_number,
        central_disk,
        entries_on_disk,
        entry_count,
        central_size,
        central_offset,
        comment_size,
    ) = struct.unpack("<4s4H2LH", raw[-22:])
    if raw[-22:-18] != b"PK\x05\x06":
        raise ValueError("backup_container_invalid")
    if (
        signature != b"PK\x05\x06"
        or disk_number != 0
        or central_disk != 0
        or entries_on_disk != entry_count
        or entry_count < 1 + len(SEED_FILE_NAMES)
        or entry_count > 1 + len(SEED_FILE_NAMES) + 2 + MAX_BLOBS
        or central_size > MAX_BACKUP_CENTRAL_DIRECTORY_BYTES
        or comment_size != 0
        or central_offset + central_size != len(raw) - 22
    ):
        raise ValueError("backup_container_invalid")
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        names = archive.namelist()
        base_names = ["manifest.json", *(f"data/{name}" for name in SEED_FILE_NAMES)]
        if archive.comment or names[: len(base_names)] != base_names:
            raise ValueError("backup_inventory_invalid")
        for info in archive.infolist():
            maximum = (
                MAX_BACKUP_MANIFEST_BYTES
                if info.filename == "manifest.json"
                else (
                    MAX_HISTORY_BYTES
                    if info.filename == "private/history.json"
                    else MAX_DATABASE_BYTES
                    if info.filename == "private/mentat.sqlite3"
                    else MAX_BLOB_BYTES
                    if info.filename.startswith("private/blobs/")
                    else MAX_PREFLIGHT_JSON_BYTES
                )
            )
            if (
                info.is_dir()
                or info.flag_bits & 0x1
                or info.compress_type != zipfile.ZIP_STORED
                or info.file_size > maximum
                or info.compress_size != info.file_size
            ):
                raise ValueError("backup_entry_invalid")
        manifest_raw = archive.read("manifest.json")
        if len(manifest_raw) > MAX_BACKUP_MANIFEST_BYTES:
            raise ValueError("backup_manifest_invalid")
        manifest = json.loads(manifest_raw.decode("utf-8"))
        format_version = manifest.get("format_version") if isinstance(manifest, dict) else None
        if isinstance(manifest, dict):
            schema_version = manifest.get("data_schema_format_version")
            document_version = manifest.get("document_version")
            if type(format_version) is int and format_version > BACKUP_FORMAT_VERSION:
                raise ValueError("backup_format_newer")
            if type(schema_version) is int and schema_version > SCHEMA_FORMAT_VERSION:
                raise ValueError("backup_schema_newer")
            if type(document_version) is int and document_version > CURRENT_DOCUMENT_VERSION:
                raise ValueError("backup_schema_newer")
        documents = tuple(
            _document_from_raw(name, archive.read(f"data/{name}"))
            for name in SEED_FILE_NAMES
        )
        private_unit: PrivateConsoleUnit | None = None
        if format_version == 1:
            if names != base_names:
                raise ValueError("backup_inventory_invalid")
        elif format_version == 2:
            manifest_items = manifest.get("items") if isinstance(manifest, dict) else None
            if not isinstance(manifest_items, list) or not all(
                isinstance(item, dict) for item in manifest_items
            ):
                raise ValueError("backup_manifest_invalid")
            private_items = [item for item in manifest_items if item.get("name") == "private_console"]
            if len(private_items) != 1 or not isinstance(private_items[0].get("blobs"), list):
                raise ValueError("backup_manifest_invalid")
            blob_items = private_items[0]["blobs"]
            if not all(isinstance(item, dict) for item in blob_items):
                raise ValueError("backup_manifest_invalid")
            expected_private = ["private/history.json", "private/mentat.sqlite3", *[f"private/blobs/{index:04d}" for index in range(len(blob_items))]]
            if names != [*base_names, *expected_private]:
                raise ValueError("backup_inventory_invalid")
            blobs = tuple(
                PrivateBlob(storage_key=str(item.get("storage_key") or ""), raw=archive.read(f"private/blobs/{index:04d}"))
                for index, item in enumerate(blob_items)
            )
            private_unit = validate_private_console_unit(
                PrivateConsoleUnit(
                    history_raw=archive.read("private/history.json"),
                    database_raw=archive.read("private/mentat.sqlite3"),
                    blobs=blobs,
                )
            )
        else:
            raise ValueError("backup_format_newer" if isinstance(format_version, int) and format_version > BACKUP_FORMAT_VERSION else "backup_manifest_invalid")
    if (
        manifest != _backup_manifest(documents, private_unit, format_version=format_version)
        or raw != _build_backup(documents, private_unit, format_version=format_version)
    ):
        raise ValueError("backup_integrity_invalid")
    return documents, private_unit, int(format_version)


def _documents_from_backup(raw: bytes) -> tuple[_Document, ...]:
    return _contents_from_backup(raw)[0]


def _read_backup_file(
    path: Path,
) -> tuple[bytes, tuple[_Document, ...], PrivateConsoleUnit | None, int, str, str]:
    selected = _absolute_without_following(Path(path))
    name_match = _BACKUP_RE.fullmatch(selected.name)
    if name_match is None:
        raise ValueError("backup_name_invalid")
    descriptor = _open_readonly_no_follow(selected)
    try:
        metadata = _validate_private_descriptor(
            descriptor,
            required_mode=0o600,
            maximum_bytes=MAX_GENERAL_BACKUP_BYTES,
        )
        if metadata.st_nlink != 1:
            raise OSError("backup links invalid")
        chunks: list[bytes] = []
        remaining = MAX_GENERAL_BACKUP_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_GENERAL_BACKUP_BYTES:
        raise ValueError("backup_too_large")
    documents, private_unit, format_version = _contents_from_backup(raw)
    expected_name = _backup_name(documents, private_unit, format_version=format_version)
    if (
        selected.name != expected_name
        or int(name_match.group(1)) != format_version
        or name_match.group(2) != _backup_id(documents, private_unit, format_version=format_version)
    ):
        raise ValueError("backup_name_invalid")
    binding = _digest(
        _canonical_json(
            {
                "path": os.path.normcase(os.path.abspath(os.fspath(selected))),
                "device": int(metadata.st_dev),
                "inode": int(metadata.st_ino),
                "size": int(metadata.st_size),
            }
        )
    )
    return raw, documents, private_unit, format_version, expected_name, binding


def _read_internal_backup(
    target: Path,
    name: str,
    root_descriptor: int | None,
) -> tuple[bytes, tuple[_Document, ...], PrivateConsoleUnit | None, int, str]:
    if _BACKUP_RE.fullmatch(name) is None:
        raise ValueError("backup_name_invalid")
    path = target / "backups" / name
    if root_descriptor is None:
        raw, metadata = _read_private_artifact_at(
            path,
            None,
            maximum=MAX_GENERAL_BACKUP_BYTES,
            maximum_links=1,
        )
    else:
        with _guarded_child_directory(target, root_descriptor, "backups") as backups_fd:
            raw, metadata = _read_private_artifact_at(
                path,
                backups_fd,
                maximum=MAX_GENERAL_BACKUP_BYTES,
                maximum_links=1,
            )
    if metadata.st_nlink != 1:
        raise OSError("backup links invalid")
    documents, private_unit, format_version = _contents_from_backup(raw)
    if _backup_name(documents, private_unit, format_version=format_version) != name:
        raise ValueError("backup_name_invalid")
    binding = _digest(
        _canonical_json(
            {
                "name": name,
                "device": int(metadata.st_dev),
                "inode": int(metadata.st_ino),
                "size": int(metadata.st_size),
            }
        )
    )
    return raw, documents, private_unit, format_version, binding


def _item_summaries(
    source: tuple[_Document, ...],
    target: tuple[_Document, ...] | None = None,
) -> tuple[dict[str, Any], ...]:
    target_by_name = {item.name: item for item in target or ()}
    return tuple(
        {
            "name": item.name,
            "classification": "durable_operator",
            "schema_version": CURRENT_DOCUMENT_VERSION,
            "action": (
                "include"
                if target is None
                else "unchanged"
                if target_by_name[item.name].raw == item.raw
                else "replace"
            ),
        }
        for item in source
    )


def _backup_item_summaries(
    documents: tuple[_Document, ...],
    private_unit: PrivateConsoleUnit | None,
    target: tuple[_Document, ...] | None = None,
    target_private: PrivateConsoleUnit | None = None,
) -> tuple[dict[str, Any], ...]:
    items = list(_item_summaries(documents, target))
    if private_unit is not None:
        items.append(
            {
                "name": "private_console",
                "classification": "durable_private_consistency_unit",
                "run_count": private_unit.run_count,
                "blob_count": len(private_unit.blobs),
                "action": (
                    "include"
                    if target is None
                    else "unchanged"
                    if target_private is not None
                    and private_console_unit_digest(private_unit)
                    == private_console_unit_digest(target_private)
                    else "replace"
                ),
            }
        )
    return tuple(items)


def _classify_restore_artifact_names(
    config_names: tuple[str, ...],
    backup_names: tuple[str, ...],
    *,
    unsafe_directory: bool = False,
) -> str | None:
    state_present = RESTORE_STATE_NAME in config_names
    state_temporaries = tuple(name for name in config_names if _STATE_TEMP_RE.fullmatch(name))
    backup_temporaries = tuple(name for name in backup_names if _BACKUP_TEMP_RE.fullmatch(name))
    state_lookalike = any(
        name.startswith(".restore-state-v1.json.mentat-init-")
        and _STATE_TEMP_RE.fullmatch(name) is None
        for name in config_names
    )
    backup_lookalike = any(
        re.match(r"^\.mentat-backup-v[12]-", name) is not None
        and ".mentat-init-" in name
        and _BACKUP_TEMP_RE.fullmatch(name) is None
        for name in backup_names
    )
    temporary_count = len(state_temporaries) + len(backup_temporaries)
    restore_artifact_present = (
        state_present
        or temporary_count > 0
        or state_lookalike
        or backup_lookalike
    )
    if not restore_artifact_present:
        return None
    if unsafe_directory or state_lookalike or backup_lookalike or temporary_count > 1:
        return "restore_artifacts_invalid"
    if temporary_count == 1:
        return "restore_recovery_required"
    return "restore_incomplete" if state_present else None


def _restore_artifact_issue(target: Path) -> str | None:
    config = target / "config"
    backups = target / "backups"
    try:
        names: list[tuple[str, ...]] = []
        unsafe_directory = False
        for directory in (config, backups):
            if not os.path.lexists(os.fspath(directory)):
                names.append(())
                continue
            metadata = os.lstat(directory)
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                unsafe_directory = True
                names.append(())
                continue
            if os.name == "posix" and stat.S_IMODE(metadata.st_mode) != 0o700:
                unsafe_directory = True
            names.append(tuple(entry.name for entry in directory.iterdir()))
        config_names, backup_names = names
        return _classify_restore_artifact_names(
            config_names,
            backup_names,
            unsafe_directory=unsafe_directory,
        )
    except OSError:
        return "restore_artifacts_invalid"


def _restore_artifact_issue_under_lock(
    data_root: Path,
    root_descriptor: int | None,
) -> str | None:
    """Classify restore reservations through the caller's pinned root lock."""

    target = _absolute_without_following(Path(data_root))
    if not _pinned_root_matches(target, root_descriptor):
        return "restore_artifacts_invalid"
    try:
        names: list[tuple[str, ...]] = []
        unsafe_directory = False
        for directory_name in ("config", "backups"):
            directory = target / directory_name
            with _pinned_existing_child_directory_state(
                target,
                root_descriptor,
                directory_name,
            ) as (directory_present, directory_descriptor):
                if not directory_present:
                    names.append(())
                    if os.path.lexists(os.fspath(directory)):
                        return "restore_artifacts_invalid"
                    continue
                if directory_descriptor is None:
                    metadata = os.lstat(directory)
                else:
                    metadata = os.fstat(directory_descriptor)
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or stat.S_ISLNK(metadata.st_mode)
                    or (os.name == "posix" and stat.S_IMODE(metadata.st_mode) != 0o700)
                ):
                    if directory_descriptor is None:
                        return "restore_artifacts_invalid"
                    unsafe_directory = True
                names.append(
                    _names_from_pinned_directory(directory, directory_descriptor)
                )
        return _classify_restore_artifact_names(
            names[0],
            names[1],
            unsafe_directory=unsafe_directory,
        )
    except _BOUNDARY_EXCEPTIONS:
        return "restore_artifacts_invalid"


def restore_status_under_lock(
    data_root: Path,
    root_descriptor: int | None,
) -> str:
    """Return clear or invalid through the caller's pinned root lock."""

    issue = _restore_artifact_issue_under_lock(data_root, root_descriptor)
    return "clear" if issue is None else "invalid"


def restore_startup_status(data_root: Path) -> str:
    """Return clear or invalid without mutating the selected root."""

    target = _absolute_without_following(Path(data_root))
    return "clear" if _restore_artifact_issue(target) is None else "invalid"


def _target_binding(target: Path, root_descriptor: int | None) -> str:
    identity = _pinned_root_identity(target, root_descriptor)
    if identity is None:
        raise OSError("restore target identity unavailable")
    return _digest(
        _canonical_json(
            {
                "target": os.path.normcase(os.path.abspath(os.fspath(target))),
                "device": int(identity[0]),
                "inode": int(identity[1]),
            }
        )
    )


def _recovery_artifact(
    target: Path,
    root_descriptor: int | None,
) -> _RecoveryArtifact | None:
    candidates: list[tuple[str, str, str]] = []
    for directory, pattern in (("config", _STATE_TEMP_RE), ("backups", _BACKUP_TEMP_RE)):
        path = target / directory
        if root_descriptor is None:
            if not os.path.lexists(os.fspath(path)):
                continue
            metadata = os.lstat(path)
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
                raise OSError("restore artifact directory invalid")
            names = tuple(entry.name for entry in path.iterdir())
        else:
            with _guarded_child_directory(target, root_descriptor, directory) as descriptor:
                names = tuple(os.listdir(descriptor))
        for name in names:
            match = pattern.fullmatch(name)
            if match is not None:
                candidates.append((directory, name, match.group(1)))
    if not candidates:
        return None
    if len(candidates) != 1:
        raise OSError("restore recovery artifacts ambiguous")
    directory, temporary_name, final_name = candidates[0]
    temporary = target / directory / temporary_name
    final = target / directory / final_name
    maximum = (
        MAX_BACKUP_MANIFEST_BYTES if directory == "config" else MAX_GENERAL_BACKUP_BYTES
    )
    if root_descriptor is None:
        raw, metadata = _read_private_artifact_at(
            temporary,
            None,
            maximum=maximum,
            maximum_links=2,
        )
        final_present = os.path.lexists(os.fspath(final))
        final_raw = None
        final_metadata = None
        if final_present:
            final_raw, final_metadata = _read_private_artifact_at(
                final,
                None,
                maximum=maximum,
                maximum_links=2,
            )
    else:
        with _guarded_child_directory(target, root_descriptor, directory) as descriptor:
            raw, metadata = _read_private_artifact_at(
                temporary,
                descriptor,
                maximum=maximum,
                maximum_links=2,
            )
            final_present = _entry_exists_at(final, descriptor)
            final_raw = None
            final_metadata = None
            if final_present:
                final_raw, final_metadata = _read_private_artifact_at(
                    final,
                    descriptor,
                    maximum=maximum,
                    maximum_links=2,
                )
    if final_present:
        assert final_metadata is not None and final_raw is not None
        if (
            metadata.st_nlink != 2
            or final_metadata.st_nlink != 2
            or metadata.st_dev != final_metadata.st_dev
            or metadata.st_ino != final_metadata.st_ino
            or raw != final_raw
        ):
            raise OSError("restore recovery promotion invalid")
    elif metadata.st_nlink != 1:
        raise OSError("restore recovery links invalid")
    return _RecoveryArtifact(
        directory=directory,
        temporary_name=temporary_name,
        final_name=final_name,
        raw=raw,
        device=int(metadata.st_dev),
        inode=int(metadata.st_ino),
        links=int(metadata.st_nlink),
        final_present=final_present,
    )


def _recovery_token(
    target_binding: str,
    artifact: _RecoveryArtifact,
    *,
    source_binding: str,
    backup_raw: bytes,
    backup_documents: tuple[_Document, ...],
    target_documents: tuple[_Document, ...],
    restore_state_evidence: Mapping[str, Any] | None,
) -> str:
    return _digest(
        _canonical_json(
            {
                "protocol_version": BACKUP_FORMAT_VERSION,
                "operation": "discard_non_authoritative_restore_temporary",
                "target_binding": target_binding,
                "source_binding": source_binding,
                "backup_name": _backup_name(backup_documents),
                "backup_sha256": _digest(backup_raw),
                "source_items": _document_identity(backup_documents),
                "target_items": _document_identity(target_documents),
                "restore_state_evidence": restore_state_evidence,
                "actions": [
                    dict(item)
                    for item in _item_summaries(
                        backup_documents,
                        target_documents,
                    )
                ],
                "directory": artifact.directory,
                "temporary_name": artifact.temporary_name,
                "final_name": artifact.final_name,
                "sha256": _digest(artifact.raw),
                "size": len(artifact.raw),
                "device": artifact.device,
                "inode": artifact.inode,
                "links": artifact.links,
                "promotion_state": (
                    "promoted_pair" if artifact.final_present else "temporary_only"
                ),
            }
        )
    )


def _restore_state_evidence(
    target: Path,
    root_descriptor: int | None,
) -> dict[str, Any] | None:
    """Bind exact restore-state presence without interpreting its contents."""

    path = target / "config" / RESTORE_STATE_NAME
    if root_descriptor is None:
        if not os.path.lexists(os.fspath(path)):
            return None
        raw, metadata = _read_private_artifact_at(
            path,
            None,
            maximum=MAX_BACKUP_MANIFEST_BYTES,
            maximum_links=2,
        )
    else:
        with _guarded_child_directory(target, root_descriptor, "config") as config_fd:
            if not _entry_exists_at(path, config_fd):
                return None
            raw, metadata = _read_private_artifact_at(
                path,
                config_fd,
                maximum=MAX_BACKUP_MANIFEST_BYTES,
                maximum_links=2,
            )
    return {
        "sha256": _digest(raw),
        "size": len(raw),
        "device": int(metadata.st_dev),
        "inode": int(metadata.st_ino),
        "links": int(metadata.st_nlink),
    }


def _preview_token(
    target_binding: str,
    source_binding: str,
    backup_raw: bytes,
    backup_documents: tuple[_Document, ...],
    target_documents: tuple[_Document, ...],
    *,
    backup_private: PrivateConsoleUnit | None = None,
    backup_format_version: int = BACKUP_FORMAT_VERSION,
    target_private: PrivateConsoleUnit | None = None,
) -> str:
    return _digest(
        _canonical_json(
            {
                "protocol_version": BACKUP_FORMAT_VERSION,
                "target_binding": target_binding,
                "source_binding": source_binding,
                "backup_sha256": _digest(backup_raw),
                "backup_name": _backup_name(
                    backup_documents,
                    backup_private,
                    format_version=backup_format_version,
                ),
                "source_items": _document_identity(backup_documents),
                "target_items": _document_identity(target_documents),
                "source_private": (
                    private_console_unit_digest(backup_private)
                    if backup_private is not None
                    else "excluded"
                ),
                "target_private": (
                    private_console_unit_digest(target_private)
                    if target_private is not None
                    else "absent"
                ),
            }
        )
    )


def _capture_target_read_only(target: Path) -> tuple[tuple[_Document, ...], str]:
    if schema_preflight_status(target) != "current":
        raise ValueError("restore_target_schema_not_current")
    before_state = os.lstat(target)
    if not stat.S_ISDIR(before_state.st_mode):
        raise OSError("restore target invalid")
    first = _load_live_documents(target, None)
    first_identity = _document_identity(first)
    del first
    second = _load_live_documents(target, None)
    after_state = os.lstat(target)
    if (
        schema_preflight_status(target) != "current"
        or first_identity != _document_identity(second)
        or before_state.st_dev != after_state.st_dev
        or before_state.st_ino != after_state.st_ino
    ):
        raise OSError("restore target changed during preview")
    binding = _digest(
        _canonical_json(
            {
                "target": os.path.normcase(os.path.abspath(os.fspath(target))),
                "device": int(after_state.st_dev),
                "inode": int(after_state.st_ino),
            }
        )
    )
    return second, binding


def create_durable_backup(data_root: Path) -> BackupResult:
    """Create or verify the deterministic backup for the current documents."""

    target = _absolute_without_following(Path(data_root))
    try:
        with _durable_mutation_lock(target) as root_descriptor:
            if (
                not _pinned_root_matches(target, root_descriptor)
                or schema_status_under_lock(target, root_descriptor) != "current"
                or _restore_artifact_issue_under_lock(target, root_descriptor) is not None
                or private_control_issue(target) is not None
            ):
                return _blocked_backup("backup_source_invalid")
            documents = _load_live_documents(target, root_descriptor)
            private_unit = capture_private_console_unit(target)
            raw = _build_backup(documents, private_unit)
            name = _backup_name(documents, private_unit)
            path = target / "backups" / name
            with _guarded_child_directory(target, root_descriptor, "backups") as backups_fd:
                if _entry_exists_at(path, backups_fd):
                    existing, state = _read_private_artifact_at(
                        path,
                        backups_fd,
                        maximum=MAX_GENERAL_BACKUP_BYTES,
                        maximum_links=1,
                    )
                    if state.st_nlink != 1 or existing != raw:
                        return _blocked_backup("backup_conflict")
                    status = "existing"
                else:
                    _publish_raw_missing(
                        path,
                        raw,
                        parent_fd=backups_fd,
                        maximum=len(raw),
                    )
                    status = "created"
                verified, verified_state = _read_private_artifact_at(
                    path,
                    backups_fd,
                    maximum=MAX_GENERAL_BACKUP_BYTES,
                    maximum_links=1,
                )
                if verified_state.st_nlink != 1 or verified != raw:
                    raise OSError("backup publication verification failed")
            terminal = _load_live_documents(target, root_descriptor)
            terminal_private = capture_private_console_unit(target)
            if (
                schema_status_under_lock(target, root_descriptor) != "current"
                or [(item.name, item.raw) for item in terminal]
                != [(item.name, item.raw) for item in documents]
                or private_console_unit_digest(terminal_private)
                != private_console_unit_digest(private_unit)
                or _restore_artifact_issue_under_lock(target, root_descriptor) is not None
                or not _pinned_root_matches(target, root_descriptor)
            ):
                raise OSError("backup source changed")
        return BackupResult(
            status=status,
            backup_name=name,
            items=_backup_item_summaries(documents, private_unit),
        )
    except _BOUNDARY_EXCEPTIONS:
        return _blocked_backup("backup_failed")


def _read_restore_state(
    target: Path,
    root_descriptor: int | None = None,
) -> Mapping[str, Any] | None:
    path = target / "config" / RESTORE_STATE_NAME
    if root_descriptor is None:
        if not os.path.lexists(os.fspath(path)):
            return None
        raw, state = _read_private_artifact_at(
            path,
            None,
            maximum=MAX_BACKUP_MANIFEST_BYTES,
            maximum_links=1,
        )
    else:
        with _guarded_child_directory(target, root_descriptor, "config") as config_fd:
            if not _entry_exists_at(path, config_fd):
                return None
            raw, state = _read_private_artifact_at(
                path,
                config_fd,
                maximum=MAX_BACKUP_MANIFEST_BYTES,
                maximum_links=1,
            )
    if state.st_nlink != 1:
        raise OSError("restore state links invalid")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or raw != _canonical_json(payload):
        raise ValueError("restore state invalid")
    return payload


def _capture_private_for_restore_state(
    target: Path,
    state: Mapping[str, Any] | None,
) -> PrivateConsoleUnit:
    console = private_console_root(target)
    if os.path.lexists(os.fspath(console)):
        return capture_private_console_unit(target)
    token = state.get("preview_token") if isinstance(state, Mapping) else None
    if isinstance(token, str) and _TOKEN_RE.fullmatch(token):
        old = target / "private" / f".console-restore-{token[:24]}-old"
        if os.path.lexists(os.fspath(old)):
            return capture_private_console_unit(target, source_console=old)
    return capture_private_console_unit(target)


def _restore_state_document(
    *,
    token: str,
    target_binding: str,
    source_raw: bytes,
    source_binding: str,
    source_evidence_binding: str,
    source_documents: tuple[_Document, ...],
    source_private: PrivateConsoleUnit | None,
    source_format_version: int,
    old_documents: tuple[_Document, ...],
    old_private: PrivateConsoleUnit,
    recovery_raw: bytes,
    recovery_evidence_binding: str,
) -> dict[str, Any]:
    old_by_name = {item.name: item for item in old_documents}
    return {
        "protocol_version": BACKUP_FORMAT_VERSION,
        "restore_id": token[:24],
        "preview_token": token,
        "target_binding": target_binding,
        "source_binding": source_binding,
        "source_evidence_binding": source_evidence_binding,
        "source_backup_name": _backup_name(
            source_documents,
            source_private,
            format_version=source_format_version,
        ),
        "source_backup_sha256": _digest(source_raw),
        "source_private_sha256": (
            private_console_unit_digest(source_private)
            if source_private is not None
            else "excluded"
        ),
        "recovery_backup_name": _backup_name(old_documents, old_private),
        "recovery_backup_sha256": _digest(recovery_raw),
        "recovery_private_sha256": private_console_unit_digest(old_private),
        "recovery_evidence_binding": recovery_evidence_binding,
        "items": [
            {
                "name": item.name,
                "old_size": old_by_name[item.name].size,
                "old_sha256": old_by_name[item.name].digest,
                "new_size": item.size,
                "new_sha256": item.digest,
            }
            for item in source_documents
        ],
    }


def _validated_resume(
    target: Path,
    state: Mapping[str, Any],
    *,
    source_raw: bytes,
    source_binding: str,
    source_documents: tuple[_Document, ...],
    source_private: PrivateConsoleUnit | None,
    source_format_version: int,
    live_documents: tuple[_Document, ...],
    live_private: PrivateConsoleUnit,
    target_binding: str,
    root_descriptor: int | None = None,
) -> tuple[bool, tuple[_Document, ...], bytes]:
    expected_keys = {
        "protocol_version",
        "restore_id",
        "preview_token",
        "target_binding",
        "source_binding",
        "source_evidence_binding",
        "source_backup_name",
        "source_backup_sha256",
        "source_private_sha256",
        "recovery_backup_name",
        "recovery_backup_sha256",
        "recovery_private_sha256",
        "recovery_evidence_binding",
        "items",
    }
    token = state.get("preview_token")
    if (
        set(state) != expected_keys
        or state.get("protocol_version") != BACKUP_FORMAT_VERSION
        or not isinstance(token, str)
        or _TOKEN_RE.fullmatch(token) is None
        or state.get("restore_id") != token[:24]
        or state.get("target_binding") != target_binding
        or state.get("source_binding") != source_binding
        or state.get("source_backup_name") != _backup_name(
            source_documents,
            source_private,
            format_version=source_format_version,
        )
        or state.get("source_backup_sha256") != _digest(source_raw)
        or state.get("source_private_sha256") != (
            private_console_unit_digest(source_private)
            if source_private is not None
            else "excluded"
        )
        or not isinstance(state.get("items"), list)
    ):
        return False, (), b""
    recovery_name = state.get("recovery_backup_name")
    recovery_digest = state.get("recovery_backup_sha256")
    source_evidence_binding = state.get("source_evidence_binding")
    recovery_evidence_binding = state.get("recovery_evidence_binding")
    if (
        not isinstance(recovery_name, str)
        or _BACKUP_RE.fullmatch(recovery_name) is None
        or not isinstance(recovery_digest, str)
        or _TOKEN_RE.fullmatch(recovery_digest) is None
        or not isinstance(source_evidence_binding, str)
        or _TOKEN_RE.fullmatch(source_evidence_binding) is None
        or not isinstance(recovery_evidence_binding, str)
        or _TOKEN_RE.fullmatch(recovery_evidence_binding) is None
    ):
        return False, (), b""
    internal_source_raw, internal_source_documents, internal_source_private, internal_source_version, internal_source_binding = (
        _read_internal_backup(
            target,
            str(state["source_backup_name"]),
            root_descriptor,
        )
    )
    recovery_raw, recovery_documents, recovery_private, _recovery_version, internal_recovery_binding = _read_internal_backup(
        target,
        recovery_name,
        root_descriptor,
    )
    if (
        internal_source_raw != source_raw
        or internal_source_documents != source_documents
        or internal_source_private != source_private
        or internal_source_version != source_format_version
        or internal_source_binding != source_evidence_binding
        or internal_recovery_binding != recovery_evidence_binding
        or _digest(recovery_raw) != recovery_digest
        or recovery_private is None
        or state.get("recovery_private_sha256") != private_console_unit_digest(recovery_private)
        or state.get("items")
        != _restore_state_document(
            token=token,
            target_binding=target_binding,
            source_raw=source_raw,
            source_binding=source_binding,
            source_evidence_binding=source_evidence_binding,
            source_documents=source_documents,
            source_private=source_private,
            source_format_version=source_format_version,
            old_documents=recovery_documents,
            old_private=recovery_private,
            recovery_raw=recovery_raw,
            recovery_evidence_binding=recovery_evidence_binding,
        )["items"]
    ):
        return False, (), b""
    source_by_name = {item.name: item for item in source_documents}
    recovery_by_name = {item.name: item for item in recovery_documents}
    for live in live_documents:
        if live.raw not in {
            source_by_name[live.name].raw,
            recovery_by_name[live.name].raw,
        }:
            return False, (), b""
    allowed_private = {private_console_unit_digest(recovery_private)}
    if source_private is not None:
        allowed_private.add(private_console_unit_digest(source_private))
    if private_console_unit_digest(live_private) not in allowed_private:
        return False, (), b""
    return True, recovery_documents, recovery_raw


def preview_durable_restore(data_root: Path, backup_file: Path) -> RestorePreview:
    """Return a bounded, side-effect-free restore plan."""

    target = _absolute_without_following(Path(data_root))
    try:
        (
            backup_raw,
            backup_documents,
            backup_private,
            backup_format_version,
            backup_name,
            source_binding,
        ) = _read_backup_file(Path(backup_file))
        if backup_private is not None and mentat_server_active(target):
            return _blocked_preview("unsafe", "private_restore_server_active")
        target_documents, binding = _capture_target_read_only(target)
        state_hint = _read_restore_state(target)
        target_private = _capture_private_for_restore_state(target, state_hint)
        artifact_issue = _restore_artifact_issue(target)
        if artifact_issue == "restore_artifacts_invalid":
            return _blocked_preview("unsafe", artifact_issue)
        if artifact_issue == "restore_recovery_required":
            artifact = _recovery_artifact(target, None)
            if artifact is None:
                return _blocked_preview("unsafe", "restore_recovery_changed")
            state_evidence = _restore_state_evidence(target, None)
            verified_documents, verified_binding = _capture_target_read_only(target)
            verified_private = _capture_private_for_restore_state(target, state_hint)
            if (
                verified_binding != binding
                or [(item.name, item.raw) for item in verified_documents]
                != [(item.name, item.raw) for item in target_documents]
                or _recovery_artifact(target, None) != artifact
                or _restore_state_evidence(target, None) != state_evidence
                or private_console_unit_digest(verified_private)
                != private_console_unit_digest(target_private)
            ):
                return _blocked_preview("unsafe", "restore_recovery_changed")
            return RestorePreview(
                status="recovery_required",
                backup_name=backup_name,
                items=_backup_item_summaries(
                    backup_documents, backup_private, target_documents, target_private
                ),
                confirmation_token=_recovery_token(
                    binding,
                    artifact,
                    source_binding=source_binding,
                    backup_raw=backup_raw,
                    backup_documents=backup_documents,
                    target_documents=target_documents,
                    restore_state_evidence=state_evidence,
                ),
                _backup_raw=backup_raw,
                _backup_documents=backup_documents,
                _backup_private=backup_private,
                _backup_format_version=backup_format_version,
                _target_documents=target_documents,
                _target_private=target_private,
                _target_binding=binding,
            )
        state = state_hint
        if state is not None:
            valid, _recovery_documents, _recovery_raw = _validated_resume(
                target,
                state,
                source_raw=backup_raw,
                source_binding=source_binding,
                source_documents=backup_documents,
                source_private=backup_private,
                source_format_version=backup_format_version,
                live_documents=target_documents,
                live_private=target_private,
                target_binding=binding,
            )
            if not valid:
                return _blocked_preview("unsafe", "restore_state_invalid")
            verified_documents, verified_binding = _capture_target_read_only(target)
            verified_private = _capture_private_for_restore_state(target, state)
            if (
                verified_binding != binding
                or [(item.name, item.raw) for item in verified_documents]
                != [(item.name, item.raw) for item in target_documents]
                or _read_restore_state(target) != state
                or private_console_unit_digest(verified_private)
                != private_console_unit_digest(target_private)
            ):
                return _blocked_preview("unsafe", "restore_state_changed")
            token = str(state["preview_token"])
            return RestorePreview(
                status="resume_required",
                backup_name=backup_name,
                items=_backup_item_summaries(
                    backup_documents, backup_private, target_documents, target_private
                ),
                confirmation_token=token,
                _backup_raw=backup_raw,
                _backup_documents=backup_documents,
                _backup_private=backup_private,
                _backup_format_version=backup_format_version,
                _target_documents=target_documents,
                _target_private=target_private,
                _target_binding=binding,
                _state=state,
            )
        verified_private = _capture_private_for_restore_state(target, None)
        if private_console_unit_digest(verified_private) != private_console_unit_digest(target_private):
            return _blocked_preview("unsafe", "restore_state_changed")
        token = _preview_token(
            binding,
            source_binding,
            backup_raw,
            backup_documents,
            target_documents,
            backup_private=backup_private,
            backup_format_version=backup_format_version,
            target_private=target_private,
        )
        items = _backup_item_summaries(
            backup_documents, backup_private, target_documents, target_private
        )
        private_unchanged = (
            backup_private is None
            or private_console_unit_digest(backup_private)
            == private_console_unit_digest(target_private)
        )
        if all(item["action"] in {"unchanged", "included"} for item in items) and private_unchanged:
            return RestorePreview(
                status="not_required",
                backup_name=backup_name,
                items=items,
            )
        return RestorePreview(
            status="ready",
            backup_name=backup_name,
            items=items,
            confirmation_token=token,
            _backup_raw=backup_raw,
            _backup_documents=backup_documents,
            _backup_private=backup_private,
            _backup_format_version=backup_format_version,
            _target_documents=target_documents,
            _target_private=target_private,
            _target_binding=binding,
        )
    except ValueError as exc:
        issue = str(exc)
        status = "unsupported" if issue in {
            "backup_format_newer",
            "backup_schema_newer",
        } else "unsafe"
        return _blocked_preview(status, issue if len(issue) <= 80 else "backup_invalid")
    except _BOUNDARY_EXCEPTIONS:
        return _blocked_preview("unsafe", "backup_or_target_invalid")


def _publish_verified_backup(
    target: Path,
    root_descriptor: int | None,
    documents: tuple[_Document, ...],
    raw: bytes,
) -> str:
    parsed_documents, private_unit, format_version = _contents_from_backup(raw)
    if parsed_documents != documents:
        raise OSError("restore backup document mismatch")
    name = _backup_name(documents, private_unit, format_version=format_version)
    path = target / "backups" / name
    with _guarded_child_directory(target, root_descriptor, "backups") as backups_fd:
        if _entry_exists_at(path, backups_fd):
            existing, existing_state = _read_private_artifact_at(
                path,
                backups_fd,
                maximum=MAX_GENERAL_BACKUP_BYTES,
                maximum_links=1,
            )
            if existing_state.st_nlink != 1 or existing != raw:
                raise OSError("restore backup conflict")
        else:
            _publish_raw_missing(
                path,
                raw,
                parent_fd=backups_fd,
                maximum=len(raw),
            )
        verified, verified_state = _read_private_artifact_at(
            path,
            backups_fd,
            maximum=MAX_GENERAL_BACKUP_BYTES,
            maximum_links=1,
        )
        if verified_state.st_nlink != 1 or verified != raw:
            raise OSError("restore backup verification failed")
    return name


def _publish_restore_state(
    target: Path,
    root_descriptor: int | None,
    document: Mapping[str, Any],
) -> None:
    raw = _canonical_json(document)
    path = target / "config" / RESTORE_STATE_NAME
    with _guarded_child_directory(target, root_descriptor, "config") as config_fd:
        if _entry_exists_at(path, config_fd):
            existing, existing_state = _read_private_artifact_at(
                path,
                config_fd,
                maximum=MAX_BACKUP_MANIFEST_BYTES,
                maximum_links=1,
            )
            if existing_state.st_nlink != 1 or existing != raw:
                raise OSError("restore state conflict")
        else:
            _publish_raw_missing(
                path,
                raw,
                parent_fd=config_fd,
                maximum=len(raw),
            )
        verified, verified_state = _read_private_artifact_at(
            path,
            config_fd,
            maximum=MAX_BACKUP_MANIFEST_BYTES,
            maximum_links=1,
        )
        if verified_state.st_nlink != 1 or verified != raw:
            raise OSError("restore state verification failed")


def _restore_private_console_under_lock(
    target: Path,
    *,
    token: str,
    source: PrivateConsoleUnit,
    recovery: PrivateConsoleUnit,
) -> Path | None:
    """Resume an exact directory exchange; return old tree pending cleanup."""

    private = target / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    if private.is_symlink() or not private.is_dir():
        raise OSError("private restore root invalid")
    if os.name == "posix":
        private.chmod(0o700)
    restore_id = token[:24]
    console = private_console_root(target)
    staged = private / f".console-restore-{restore_id}-new"
    old = private / f".console-restore-{restore_id}-old"
    source_digest = private_console_unit_digest(source)
    recovery_digest = private_console_unit_digest(recovery)

    def captured(path: Path) -> str | None:
        if not os.path.lexists(os.fspath(path)):
            return None
        if path.is_symlink() or not path.is_dir():
            raise OSError("private restore tree invalid")
        return private_console_unit_digest(
            capture_private_console_unit(target, source_console=path)
        )

    live_digest = captured(console)
    try:
        old_digest = captured(old)
    except (OSError, ValueError, TypeError):
        if live_digest != source_digest or old.is_symlink() or not old.is_dir():
            raise OSError("private restore staging conflict")
        remove_private_console_tree(target, old)
        old_digest = None
    if live_digest not in {None, recovery_digest, source_digest}:
        raise OSError("private restore live conflict")
    if old_digest not in {None, recovery_digest}:
        if live_digest != source_digest:
            raise OSError("private restore staging conflict")
        remove_private_console_tree(target, old)
        old_digest = None
    try:
        if os.path.lexists(os.fspath(staged)):
            validate_private_console_stage_inventory(target, staged, source)
        staged_digest = captured(staged)
    except PrivateConsoleUnitError as exc:
        if str(exc) != "private_stage_incomplete":
            raise OSError("private restore staging conflict") from exc
        remove_private_console_tree(target, staged)
        staged_digest = None
    except (OSError, ValueError, TypeError):
        if staged.is_symlink() or not staged.is_dir():
            raise OSError("private restore staging conflict")
        remove_private_console_tree(target, staged)
        staged_digest = None
    if staged_digest not in {None, source_digest}:
        remove_private_console_tree(target, staged)
        staged_digest = None

    if live_digest == source_digest:
        try:
            validate_private_console_stage_inventory(
                target, console, source, allow_canonical=True
            )
        except PrivateConsoleUnitError:
            if old_digest == recovery_digest and staged_digest is None:
                os.rename(console, staged)
                os.rename(old, console)
            raise OSError("private restore live inventory conflict")
        if staged_digest is not None:
            remove_private_console_tree(target, staged)
        return old if old_digest is not None else None

    if staged_digest is None:
        materialize_private_console_unit(target, source, staged)
        validate_private_console_stage_inventory(target, staged, source)
        staged_digest = source_digest
    if live_digest is None:
        if old_digest is None and recovery_digest == private_console_unit_digest(empty_private_console_unit()):
            pass
        elif old_digest != recovery_digest:
            raise OSError("private restore recovery tree missing")
    else:
        if live_digest != recovery_digest or old_digest is not None:
            raise OSError("private restore transition conflict")
        os.rename(console, old)
        old_digest = captured(old)
        if old_digest != recovery_digest or os.path.lexists(os.fspath(console)):
            raise OSError("private restore recovery promotion failed")
    os.rename(staged, console)
    try:
        validate_private_console_stage_inventory(
            target, console, source, allow_canonical=True
        )
    except Exception:
        if (
            os.path.lexists(os.fspath(console))
            and not os.path.lexists(os.fspath(staged))
        ):
            os.rename(console, staged)
        if old_digest == recovery_digest and not os.path.lexists(os.fspath(console)):
            os.rename(old, console)
        raise
    if captured(console) != source_digest or os.path.lexists(os.fspath(staged)):
        raise OSError("private restore source promotion failed")
    return old


def restore_durable_backup(
    data_root: Path,
    backup_file: Path,
    *,
    confirmation_token: str,
) -> RestoreResult:
    """Confirm and execute one exact restore plan."""

    initial = preview_durable_restore(data_root, backup_file)
    if (
        initial.status not in {"ready", "resume_required", "recovery_required"}
        or initial.confirmation_token is None
        or confirmation_token != initial.confirmation_token
    ):
        return _blocked_result(initial, "restore_confirmation_invalid")
    target = _absolute_without_following(Path(data_root))
    mutation_started = False
    recovery_name: str | None = None
    try:
        with _durable_mutation_lock(target) as root_descriptor:
            if initial._backup_private is not None and mentat_server_active(target):
                return _blocked_result(initial, "private_restore_server_active")
            if (
                not _pinned_root_matches(target, root_descriptor)
                or schema_status_under_lock(target, root_descriptor) != "current"
            ):
                return _blocked_result(initial, "restore_target_invalid")
            expected_artifact_issue = {
                "ready": None,
                "resume_required": "restore_incomplete",
                "recovery_required": "restore_recovery_required",
            }[initial.status]
            if (
                _restore_artifact_issue_under_lock(target, root_descriptor)
                != expected_artifact_issue
            ):
                return _blocked_result(initial, "restore_artifacts_changed")
            if initial.status == "recovery_required":
                (
                    source_raw,
                    source_documents,
                    _source_private,
                    _source_format_version,
                    _source_name,
                    source_binding,
                ) = _read_backup_file(Path(backup_file))
                live_documents = _load_live_documents(target, root_descriptor)
                artifact = _recovery_artifact(target, root_descriptor)
                state_evidence = _restore_state_evidence(target, root_descriptor)
                binding = _target_binding(target, root_descriptor)
                if (
                    artifact is None
                    or _recovery_token(
                        binding,
                        artifact,
                        source_binding=source_binding,
                        backup_raw=source_raw,
                        backup_documents=source_documents,
                        target_documents=live_documents,
                        restore_state_evidence=state_evidence,
                    )
                    != confirmation_token
                ):
                    return _blocked_result(initial, "restore_recovery_changed")
                temporary = target / artifact.directory / artifact.temporary_name
                with _guarded_child_directory(
                    target,
                    root_descriptor,
                    artifact.directory,
                ) as parent_fd:
                    maximum = (
                        MAX_BACKUP_MANIFEST_BYTES
                        if artifact.directory == "config"
                        else MAX_GENERAL_BACKUP_BYTES
                    )
                    immediate_raw, immediate_state = _read_private_artifact_at(
                        temporary,
                        parent_fd,
                        maximum=maximum,
                        maximum_links=2,
                    )
                    final = target / artifact.directory / artifact.final_name
                    final_present = _entry_exists_at(final, parent_fd)
                    if (
                        immediate_raw != artifact.raw
                        or int(immediate_state.st_dev) != artifact.device
                        or int(immediate_state.st_ino) != artifact.inode
                        or int(immediate_state.st_nlink) != artifact.links
                        or final_present != artifact.final_present
                    ):
                        return _blocked_result(initial, "restore_recovery_changed")
                    if final_present:
                        final_raw, final_state = _read_private_artifact_at(
                            final,
                            parent_fd,
                            maximum=maximum,
                            maximum_links=2,
                        )
                        if (
                            final_raw != immediate_raw
                            or final_state.st_dev != immediate_state.st_dev
                            or final_state.st_ino != immediate_state.st_ino
                            or final_state.st_nlink != immediate_state.st_nlink
                        ):
                            return _blocked_result(initial, "restore_recovery_changed")
                    immediate_raw, immediate_state = _read_private_artifact_at(
                        temporary,
                        parent_fd,
                        maximum=maximum,
                        maximum_links=2,
                    )
                    if (
                        immediate_raw != artifact.raw
                        or int(immediate_state.st_dev) != artifact.device
                        or int(immediate_state.st_ino) != artifact.inode
                        or int(immediate_state.st_nlink) != artifact.links
                        or _entry_exists_at(final, parent_fd) != artifact.final_present
                    ):
                        return _blocked_result(initial, "restore_recovery_changed")
                    if artifact.final_present:
                        adjacent_final_raw, adjacent_final_state = _read_private_artifact_at(
                            final,
                            parent_fd,
                            maximum=maximum,
                            maximum_links=2,
                        )
                        if (
                            adjacent_final_raw != immediate_raw
                            or adjacent_final_state.st_dev != immediate_state.st_dev
                            or adjacent_final_state.st_ino != immediate_state.st_ino
                            or adjacent_final_state.st_nlink != immediate_state.st_nlink
                        ):
                            return _blocked_result(initial, "restore_recovery_changed")
                    if (
                        _restore_state_evidence(target, root_descriptor)
                        != state_evidence
                    ):
                        return _blocked_result(initial, "restore_recovery_changed")
                    mutation_started = True
                    _unlink_relative(temporary, parent_fd)
                    if _entry_exists_at(temporary, parent_fd):
                        raise OSError("restore recovery removal unverified")
                expected_remaining_issue = (
                    "restore_incomplete" if state_evidence is not None else None
                )
                if (
                    _recovery_artifact(target, root_descriptor) is not None
                    or _restore_artifact_issue_under_lock(target, root_descriptor)
                    != expected_remaining_issue
                ):
                    raise OSError("restore recovery inventory unverified")
                return RestoreResult(
                    status="recovered",
                    items=initial.items,
                    issues=("restore_preview_required",),
                )
            (
                source_raw,
                source_documents,
                source_private,
                source_format_version,
                _source_name,
                source_binding,
            ) = _read_backup_file(Path(backup_file))
            live_documents = _load_live_documents(target, root_descriptor)
            binding = _target_binding(target, root_descriptor)
            state = _read_restore_state(target, root_descriptor)
            live_private = _capture_private_for_restore_state(target, state)
            if state is None:
                expected_token = _preview_token(
                    binding,
                    source_binding,
                    source_raw,
                    source_documents,
                    live_documents,
                    backup_private=source_private,
                    backup_format_version=source_format_version,
                    target_private=live_private,
                )
                if expected_token != confirmation_token:
                    return _blocked_result(initial, "restore_state_changed")
                recovery_documents = live_documents
                recovery_private = live_private
                recovery_raw = _build_backup(recovery_documents, recovery_private)
                mutation_started = True
                internal_source_name = _publish_verified_backup(
                    target,
                    root_descriptor,
                    source_documents,
                    source_raw,
                )
                recovery_name = _publish_verified_backup(
                    target,
                    root_descriptor,
                    recovery_documents,
                    recovery_raw,
                )
                (
                    verified_source_raw,
                    verified_source_documents,
                    _verified_source_private,
                    _verified_source_version,
                    source_evidence_binding,
                ) = _read_internal_backup(
                    target,
                    internal_source_name,
                    root_descriptor,
                )
                (
                    verified_recovery_raw,
                    verified_recovery_documents,
                    _verified_recovery_private,
                    _verified_recovery_version,
                    recovery_evidence_binding,
                ) = _read_internal_backup(
                    target,
                    recovery_name,
                    root_descriptor,
                )
                if (
                    verified_source_raw != source_raw
                    or verified_source_documents != source_documents
                    or verified_recovery_raw != recovery_raw
                    or verified_recovery_documents != recovery_documents
                ):
                    raise OSError("restore evidence changed before reservation")
                state = _restore_state_document(
                    token=confirmation_token,
                    target_binding=binding,
                    source_raw=source_raw,
                    source_binding=source_binding,
                    source_evidence_binding=source_evidence_binding,
                    source_documents=source_documents,
                    source_private=source_private,
                    source_format_version=source_format_version,
                    old_documents=recovery_documents,
                    old_private=recovery_private,
                    recovery_raw=recovery_raw,
                    recovery_evidence_binding=recovery_evidence_binding,
                )
                _publish_restore_state(target, root_descriptor, state)
            else:
                mutation_started = True
                valid, recovery_documents, recovery_raw = _validated_resume(
                    target,
                    state,
                    source_raw=source_raw,
                    source_binding=source_binding,
                    source_documents=source_documents,
                    source_private=source_private,
                    source_format_version=source_format_version,
                    live_documents=live_documents,
                    live_private=live_private,
                    target_binding=binding,
                    root_descriptor=root_descriptor,
                )
                if not valid or state.get("preview_token") != confirmation_token:
                    return _blocked_result(initial, "restore_state_changed")
                recovery_name = str(state["recovery_backup_name"])
                (
                    _recovery_archive_raw,
                    _recovery_archive_documents,
                    recovery_private,
                    _recovery_archive_version,
                    _recovery_archive_binding,
                ) = _read_internal_backup(target, recovery_name, root_descriptor)
                if recovery_private is None:
                    raise OSError("restore recovery private unit missing")
            source_by_name = {item.name: item for item in source_documents}
            recovery_by_name = {item.name: item for item in recovery_documents}
            current = _load_live_documents(target, root_descriptor)
            for live in current:
                source = source_by_name[live.name]
                recovery = recovery_by_name[live.name]
                if live.raw == source.raw:
                    continue
                if live.raw != recovery.raw:
                    return _blocked_result(initial, "restore_live_document_conflict")
                write_json_bytes_atomic(
                    target / live.name,
                    source.raw,
                    expected_type=SEED_ROOT_TYPES[live.name],
                    mode=0o600,
                    parent_fd=root_descriptor,
                    maximum_bytes=MAX_PREFLIGHT_JSON_BYTES,
                )
            terminal = _load_live_documents(target, root_descriptor)
            old_private_tree: Path | None = None
            if source_private is not None:
                old_private_tree = _restore_private_console_under_lock(
                    target,
                    token=confirmation_token,
                    source=source_private,
                    recovery=recovery_private,
                )
            terminal_private = capture_private_console_unit(target)
            if source_private is not None:
                validate_private_console_stage_inventory(
                    target,
                    private_console_root(target),
                    terminal_private,
                    allow_canonical=True,
                )
            if (
                [(item.name, item.raw) for item in terminal]
                != [(item.name, item.raw) for item in source_documents]
                or (
                    source_private is not None
                    and private_console_unit_digest(terminal_private)
                    != private_console_unit_digest(source_private)
                )
                or schema_status_under_lock(target, root_descriptor) != "current"
                or not _pinned_root_matches(target, root_descriptor)
            ):
                raise OSError("restore terminal verification failed")
            if old_private_tree is not None:
                remove_private_console_tree(target, old_private_tree)
            if source_private is not None:
                validate_private_console_stage_inventory(
                    target,
                    private_console_root(target),
                    source_private,
                    allow_canonical=True,
                )
                post_cleanup_private = capture_private_console_unit(target)
                if (
                    private_console_unit_digest(post_cleanup_private)
                    != private_console_unit_digest(source_private)
                ):
                    raise OSError("restore private content changed during cleanup")
            with _guarded_child_directory(target, root_descriptor, "config") as config_fd:
                if (
                    _restore_artifact_issue_under_lock(target, root_descriptor)
                    != "restore_incomplete"
                ):
                    raise OSError("restore artifact inventory changed before completion")
                state_path = target / "config" / RESTORE_STATE_NAME
                state_raw, state_metadata = _read_private_artifact_at(
                    state_path,
                    config_fd,
                    maximum=MAX_BACKUP_MANIFEST_BYTES,
                    maximum_links=1,
                )
                if (
                    state_metadata.st_nlink != 1
                    or state_raw != _canonical_json(state)
                ):
                    raise OSError("restore state changed before completion")
                _unlink_relative(state_path, config_fd)
                if _entry_exists_at(state_path, config_fd):
                    raise OSError("restore state removal unverified")
            completion_private = capture_private_console_unit(target)
            if source_private is not None:
                validate_private_console_stage_inventory(
                    target,
                    private_console_root(target),
                    completion_private,
                    allow_canonical=True,
                )
            if (
                schema_status_under_lock(target, root_descriptor) != "current"
                or _load_live_documents(target, root_descriptor) != terminal
                or (
                    source_private is not None
                    and private_console_unit_digest(completion_private)
                    != private_console_unit_digest(source_private)
                )
                or _restore_artifact_issue_under_lock(target, root_descriptor) is not None
                or not _pinned_root_matches(target, root_descriptor)
            ):
                raise OSError("restore completion verification failed")
        return RestoreResult(
            status="resumed" if initial.status == "resume_required" else "restored",
            items=_backup_item_summaries(
                source_documents,
                source_private,
                source_documents,
                source_private,
            ),
            recovery_backup_name=recovery_name,
        )
    except _BOUNDARY_EXCEPTIONS:
        return RestoreResult(
            status="partial_failure" if mutation_started else "blocked",
            items=initial.items,
            recovery_backup_name=recovery_name,
            issues=("restore_failed",),
        )
