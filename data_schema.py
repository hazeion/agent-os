"""Version and migrate Mentat's fixed durable JSON inventory.

The current schema migration is intentionally an identity migration: it records
the already-supported top-level shapes in one owner-only sidecar manifest. It
does not wrap or rewrite live operator documents. General backup/restore and
private SQLite evolution remain separate capabilities.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping
import zipfile

from data_layout import (
    MAX_PREFLIGHT_JSON_BYTES,
    SEED_FILE_NAMES,
    SEED_ROOT_TYPES,
    _absolute_without_following,
    _initialization_lock,
    _open_readonly_no_follow,
    _path_contains,
    _read_validated_seed_bytes,
    _root_is_too_broad,
    _root_issue,
    _same_path,
)
from data_migration import (
    _canonical_json,
    _digest,
    _guarded_mutation_directory,
    _owner_only_regular_descriptor,
    _pinned_target_matches,
    _publish_raw_missing,
    _read_exact_regular,
)


SCHEMA_FORMAT_VERSION = 1
CURRENT_DOCUMENT_VERSION = 1
LEGACY_DOCUMENT_VERSION = 0
SCHEMA_MANIFEST_NAME = "data-schema.json"
SCHEMA_BACKUP_PREFIX = "data-schema-v1-"
SCHEMA_STEP_ID = "durable-json-v0-to-v1"
FRESH_SCHEMA_RESERVATION_NAME = ".data-schema-fresh-v1.reservation"
MAX_SCHEMA_MANIFEST_BYTES = 1024 * 1024
MAX_SCHEMA_BACKUP_BYTES = (
    len(SEED_FILE_NAMES) * MAX_PREFLIGHT_JSON_BYTES + MAX_SCHEMA_MANIFEST_BYTES
)
_TOKEN_RE = re.compile(r"^[0-9a-f]{64}$")
_BACKUP_RE = re.compile(r"^data-schema-v1-([0-9a-f]{24})\.zip$")
_BACKUP_TEMP_RE = re.compile(
    r"^\.(data-schema-v1-[0-9a-f]{24}\.zip)\.mentat-init-[0-9a-f]{32}\.tmp$"
)
_MANIFEST_TEMP_RE = re.compile(
    r"^\.data-schema\.json\.mentat-init-[0-9a-f]{32}\.tmp$"
)
_FRESH_RESERVATION_TEMP_RE = re.compile(
    r"^\.\.data-schema-fresh-v1\.reservation\.mentat-init-[0-9a-f]{32}\.tmp$"
)
_FRESH_SEED_TEMP_RE = re.compile(
    r"^\.(" + "|".join(re.escape(name) for name in SEED_FILE_NAMES) +
    r")\.mentat-init-[0-9a-f]{32}\.tmp$"
)
_BOUNDARY_EXCEPTIONS = (
    OSError,
    ValueError,
    TypeError,
    OverflowError,
    UnicodeError,
    RuntimeError,
    NotImplementedError,
    RecursionError,
    MemoryError,
)


class _RecoveryStateChanged(OSError):
    """Confirmed recovery evidence changed before Mentat deleted anything."""
_EXCLUDED_ITEMS = (
    {
        "name": "private/",
        "classification": "deferred_private_schema",
        "action": "excluded",
    },
    {
        "name": "runtime/",
        "classification": "deferred_runtime_schema",
        "action": "excluded",
    },
)


@dataclass(frozen=True)
class _DocumentSnapshot:
    name: str
    raw: bytes = field(repr=False)
    digest: str

    @property
    def size(self) -> int:
        return len(self.raw)


@dataclass(frozen=True)
class _RecoveryArtifact:
    directory: str
    name: str
    kind: str
    size: int
    digest: str
    final_present: bool


@dataclass(frozen=True)
class SchemaItem:
    name: str
    from_version: int
    to_version: int
    action: str
    classification: str = "durable_operator"

    def public_summary(self) -> dict:
        return {
            "name": self.name,
            "classification": self.classification,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "action": self.action,
        }


@dataclass(frozen=True)
class SchemaPreview:
    status: str
    items: tuple[SchemaItem, ...]
    issues: tuple[str, ...] = ()
    confirmation_token: str | None = field(default=None, repr=False)
    _snapshots: tuple[_DocumentSnapshot, ...] = field(default=(), repr=False)
    _recovery: _RecoveryArtifact | None = field(default=None, repr=False)

    def public_summary(self) -> dict:
        summary = {
            "status": self.status,
            "items": [item.public_summary() for item in self.items],
            "excluded": [dict(item) for item in _EXCLUDED_ITEMS],
            "issues": list(self.issues),
        }
        if self.confirmation_token is not None:
            summary["confirmation_token"] = self.confirmation_token
        return summary


@dataclass(frozen=True)
class SchemaResult:
    status: str
    items: tuple[SchemaItem, ...]
    issues: tuple[str, ...] = ()

    def public_summary(self) -> dict:
        return {
            "status": self.status,
            "items": [item.public_summary() for item in self.items],
            "excluded": [dict(item) for item in _EXCLUDED_ITEMS],
            "issues": list(self.issues),
        }


def _items(action: str, from_version: int = 0, to_version: int = 1) -> tuple[SchemaItem, ...]:
    return tuple(
        SchemaItem(
            name=name,
            from_version=from_version,
            to_version=to_version,
            action=action,
        )
        for name in SEED_FILE_NAMES
    )


def _blocked(status: str, *issues: str) -> SchemaPreview:
    return SchemaPreview(status=status, items=_items("blocked"), issues=tuple(issues))


def _manifest_path(target: Path) -> Path:
    return target / "config" / SCHEMA_MANIFEST_NAME


def _backup_name(token: str) -> str:
    return f"{SCHEMA_BACKUP_PREFIX}{token[:24]}.zip"


def _reserved_temporary_lookalike(name: str, *, directory: str) -> bool:
    if directory == "config":
        return (
            name.startswith(".data-schema.json.mentat-init-")
            and _MANIFEST_TEMP_RE.fullmatch(name) is None
        )
    if directory == "backups":
        return (
            name.startswith(".data-schema-v1-")
            and ".mentat-init-" in name
            and _BACKUP_TEMP_RE.fullmatch(name) is None
        )
    return False


def _classify_schema_artifact_names(
    root_names: tuple[str, ...],
    config_names: tuple[str, ...],
    backup_names: tuple[str, ...],
) -> str | None:
    reservation = FRESH_SCHEMA_RESERVATION_NAME in root_names
    reservation_temporaries = tuple(
        name for name in root_names if _FRESH_RESERVATION_TEMP_RE.fullmatch(name)
    )
    seed_temporaries = tuple(name for name in root_names if _FRESH_SEED_TEMP_RE.fullmatch(name))
    fresh_present = reservation or bool(reservation_temporaries)
    reservation_prefix = f".{FRESH_SCHEMA_RESERVATION_NAME}.mentat-init-"
    reservation_lookalike = any(
        name.startswith(reservation_prefix)
        and _FRESH_RESERVATION_TEMP_RE.fullmatch(name) is None
        for name in root_names
    )
    seed_lookalike = any(
        any(name.startswith(f".{seed}.mentat-init-") for seed in SEED_FILE_NAMES)
        and _FRESH_SEED_TEMP_RE.fullmatch(name) is None
        for name in root_names
    )
    manifest_temporaries = tuple(
        name for name in config_names if _MANIFEST_TEMP_RE.fullmatch(name)
    )
    backup_temporaries = tuple(
        name for name in backup_names if _BACKUP_TEMP_RE.fullmatch(name)
    )
    backups = tuple(name for name in backup_names if _BACKUP_RE.fullmatch(name))
    invalid = (
        reservation_lookalike
        or (fresh_present and seed_lookalike)
        or any(_reserved_temporary_lookalike(name, directory="config") for name in config_names)
        or any(_reserved_temporary_lookalike(name, directory="backups") for name in backup_names)
    )
    exact_temporaries = (
        *reservation_temporaries,
        *seed_temporaries,
        *manifest_temporaries,
        *backup_temporaries,
    )
    if invalid or len(exact_temporaries) > 1:
        return "invalid_schema_artifacts"
    if fresh_present:
        if backups or backup_temporaries:
            return "invalid_schema_artifacts"
        return "fresh_schema_initialization_incomplete"
    if reservation_temporaries or seed_temporaries:
        return "invalid_schema_artifacts"
    if manifest_temporaries:
        return "incomplete_schema_manifest_temporary"
    if backup_temporaries:
        return "incomplete_schema_backup_temporary"
    if backups:
        return "schema_backup_present"
    return None


def _schema_artifact_issue(target: Path) -> str | None:
    config_root = target / "config"
    backup_root = target / "backups"
    try:
        root_entries = list(target.iterdir())
        config_entries: list[Path] = []
        backup_entries: list[Path] = []
        if os.path.lexists(os.fspath(config_root)):
            metadata = os.lstat(config_root)
            if not stat.S_ISDIR(metadata.st_mode):
                return "invalid_schema_artifacts"
            config_entries = list(config_root.iterdir())
        if os.path.lexists(os.fspath(backup_root)):
            metadata = os.lstat(backup_root)
            if not stat.S_ISDIR(metadata.st_mode):
                return "invalid_schema_artifacts"
            backup_entries = list(backup_root.iterdir())
        return _classify_schema_artifact_names(
            tuple(entry.name for entry in root_entries),
            tuple(entry.name for entry in config_entries),
            tuple(entry.name for entry in backup_entries),
        )
    except _BOUNDARY_EXCEPTIONS:
        return "invalid_schema_artifacts"


def _read_manifest(target: Path) -> tuple[str, dict | None]:
    path = _manifest_path(target)
    if not os.path.lexists(os.fspath(path)):
        return "legacy", None
    try:
        raw = _read_exact_regular(path, MAX_SCHEMA_MANIFEST_BYTES)
        descriptor = _open_readonly_no_follow(path)
        try:
            if not _owner_only_regular_descriptor(descriptor):
                return "invalid", None
        finally:
            os.close(descriptor)
        payload = json.loads(raw.decode("utf-8"))
    except _BOUNDARY_EXCEPTIONS:
        return "invalid", None
    return _manifest_payload_status(payload)


def _manifest_payload_status(payload) -> tuple[str, dict | None]:
    if type(payload) is not dict:
        return "invalid", None
    format_version = payload.get("format_version")
    documents = payload.get("documents")
    if type(format_version) is int and format_version > SCHEMA_FORMAT_VERSION:
        return "newer", payload
    if isinstance(documents, list) and any(
        type(item) is dict
        and type(item.get("version")) is int
        and item["version"] > CURRENT_DOCUMENT_VERSION
        for item in documents
    ):
        return "newer", payload
    return "current" if _manifest_semantics_valid(payload) else "invalid", payload


def _manifest_semantics_valid(payload: Mapping) -> bool:
    if set(payload) != {
        "format_version",
        "inventory",
        "documents",
        "origin",
        "applied_steps",
        "backup",
    }:
        return False
    if type(payload.get("format_version")) is not int or payload["format_version"] != SCHEMA_FORMAT_VERSION:
        return False
    if payload.get("inventory") != "durable-json":
        return False
    documents = payload.get("documents")
    if not isinstance(documents, list) or len(documents) != len(SEED_FILE_NAMES):
        return False
    if [item.get("name") for item in documents if type(item) is dict] != list(SEED_FILE_NAMES):
        return False
    if any(
        type(item) is not dict
        or set(item) != {"name", "version"}
        or type(item.get("version")) is not int
        or item["version"] != CURRENT_DOCUMENT_VERSION
        for item in documents
    ):
        return False
    origin = payload.get("origin")
    steps = payload.get("applied_steps")
    backup = payload.get("backup")
    if origin == "fresh_seed":
        return steps == [] and backup is None
    if origin != "schema_migration":
        return False
    expected_step = {
        "id": SCHEMA_STEP_ID,
        "from_version": LEGACY_DOCUMENT_VERSION,
        "to_version": CURRENT_DOCUMENT_VERSION,
    }
    if steps != [expected_step]:
        return False
    if (
        type(steps[0].get("from_version")) is not int
        or type(steps[0].get("to_version")) is not int
    ):
        return False
    return (
        type(backup) is dict
        and set(backup) == {"name", "sha256"}
        and isinstance(backup.get("name"), str)
        and _BACKUP_RE.fullmatch(backup["name"]) is not None
        and isinstance(backup.get("sha256"), str)
        and _TOKEN_RE.fullmatch(backup["sha256"]) is not None
    )


def _load_snapshots(target: Path, *, private: bool) -> tuple[_DocumentSnapshot, ...]:
    snapshots: list[_DocumentSnapshot] = []
    for name in SEED_FILE_NAMES:
        path = target / name
        raw = _read_validated_seed_bytes(path, name, require_single_link=private)
        if private:
            descriptor = _open_readonly_no_follow(path)
            try:
                if not _owner_only_regular_descriptor(descriptor):
                    raise OSError(f"schema_live_file_unsafe:{name}")
            finally:
                os.close(descriptor)
        snapshots.append(_DocumentSnapshot(name=name, raw=raw, digest=_digest(raw)))
    return tuple(snapshots)


def _manifest_document(
    *,
    origin: str,
    backup_name: str | None = None,
    backup_sha256: str | None = None,
) -> dict:
    migrated = origin == "schema_migration"
    return {
        "format_version": SCHEMA_FORMAT_VERSION,
        "inventory": "durable-json",
        "documents": [
            {"name": name, "version": CURRENT_DOCUMENT_VERSION}
            for name in SEED_FILE_NAMES
        ],
        "origin": origin,
        "applied_steps": (
            [
                {
                    "id": SCHEMA_STEP_ID,
                    "from_version": LEGACY_DOCUMENT_VERSION,
                    "to_version": CURRENT_DOCUMENT_VERSION,
                }
            ]
            if migrated
            else []
        ),
        "backup": (
            {"name": backup_name, "sha256": backup_sha256}
            if migrated
            else None
        ),
    }


def _fresh_manifest_raw() -> bytes:
    return _canonical_json(_manifest_document(origin="fresh_seed"))


def _fresh_reservation_valid(target: Path) -> bool:
    path = target / FRESH_SCHEMA_RESERVATION_NAME
    if not os.path.lexists(os.fspath(path)):
        return False
    try:
        return _read_exact_regular(path, MAX_SCHEMA_MANIFEST_BYTES) == _fresh_manifest_raw()
    except _BOUNDARY_EXCEPTIONS:
        return False


def _fresh_reservation_valid_at(target: Path, root_descriptor: int | None) -> bool:
    path = target / FRESH_SCHEMA_RESERVATION_NAME
    if not _entry_exists_at(path, root_descriptor):
        return False
    try:
        raw, _metadata = _read_private_artifact_at(
            path,
            root_descriptor,
            maximum=MAX_SCHEMA_MANIFEST_BYTES,
            maximum_links=1,
        )
        return raw == _fresh_manifest_raw()
    except _BOUNDARY_EXCEPTIONS:
        return False


def _read_private_artifact(
    path: Path,
    *,
    maximum: int,
    maximum_links: int,
) -> tuple[bytes, os.stat_result]:
    descriptor = _open_readonly_no_follow(path)
    return _read_private_artifact_descriptor(
        descriptor,
        maximum=maximum,
        maximum_links=maximum_links,
    )


def _read_private_artifact_descriptor(
    descriptor: int,
    *,
    maximum: int,
    maximum_links: int,
) -> tuple[bytes, os.stat_result]:
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not 1 <= metadata.st_nlink <= maximum_links
            or metadata.st_size > maximum
        ):
            raise OSError("unsafe fresh schema artifact")
        if os.name == "posix":
            if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
                raise OSError("unowned fresh schema artifact")
            if stat.S_IMODE(metadata.st_mode) != 0o600:
                raise OSError("broad fresh schema artifact")
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
            raise OSError("fresh schema artifact too large")
        return raw, metadata
    finally:
        os.close(descriptor)


def _read_private_artifact_at(
    path: Path,
    parent_descriptor: int | None,
    *,
    maximum: int,
    maximum_links: int,
) -> tuple[bytes, os.stat_result]:
    if parent_descriptor is None:
        return _read_private_artifact(
            path,
            maximum=maximum,
            maximum_links=maximum_links,
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    flags |= getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
    return _read_private_artifact_descriptor(
        descriptor,
        maximum=maximum,
        maximum_links=maximum_links,
    )


def _entry_exists_at(path: Path, parent_descriptor: int | None) -> bool:
    if parent_descriptor is None:
        return os.path.lexists(os.fspath(path))
    try:
        os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _load_snapshots_at(
    target: Path,
    root_descriptor: int | None,
) -> tuple[_DocumentSnapshot, ...]:
    snapshots: list[_DocumentSnapshot] = []
    for name in SEED_FILE_NAMES:
        raw, _metadata = _read_private_artifact_at(
            target / name,
            root_descriptor,
            maximum=MAX_PREFLIGHT_JSON_BYTES,
            maximum_links=1,
        )
        document = json.loads(raw.decode("utf-8"))
        if type(document) is not SEED_ROOT_TYPES[name]:
            raise OSError("schema live document shape changed")
        snapshots.append(_DocumentSnapshot(name=name, raw=raw, digest=_digest(raw)))
    return tuple(snapshots)


def _snapshots_match(
    actual: tuple[_DocumentSnapshot, ...],
    expected: tuple[_DocumentSnapshot, ...],
) -> bool:
    return tuple((item.name, item.raw) for item in actual) == tuple(
        (item.name, item.raw) for item in expected
    )


def _manifest_declares_newer(target: Path) -> bool:
    path = _manifest_path(target)
    if not os.path.lexists(os.fspath(path)):
        return False
    try:
        raw, _metadata = _read_private_artifact(
            path,
            maximum=MAX_SCHEMA_MANIFEST_BYTES,
            maximum_links=2,
        )
        payload = json.loads(raw.decode("utf-8"))
        if type(payload) is not dict:
            return False
        if type(payload.get("format_version")) is int and payload["format_version"] > SCHEMA_FORMAT_VERSION:
            return True
        documents = payload.get("documents")
        return isinstance(documents, list) and any(
            type(item) is dict
            and type(item.get("version")) is int
            and item["version"] > CURRENT_DOCUMENT_VERSION
            for item in documents
        )
    except _BOUNDARY_EXCEPTIONS:
        return False


def _fresh_initialization_recoverable(target: Path) -> bool:
    try:
        reservation_temporaries = [
            entry for entry in target.iterdir() if _FRESH_RESERVATION_TEMP_RE.fullmatch(entry.name)
        ]
        seed_temporaries = [
            entry for entry in target.iterdir() if _FRESH_SEED_TEMP_RE.fullmatch(entry.name)
        ]
        manifest_temporaries = (
            [
                entry
                for entry in (target / "config").iterdir()
                if _MANIFEST_TEMP_RE.fullmatch(entry.name)
            ]
            if (target / "config").is_dir()
            else []
        )
        if len(reservation_temporaries) + len(seed_temporaries) + len(manifest_temporaries) > 1:
            return False
        backup_root = target / "backups"
        if backup_root.is_dir() and any(
            _BACKUP_RE.fullmatch(entry.name) or _BACKUP_TEMP_RE.fullmatch(entry.name)
            for entry in backup_root.iterdir()
        ):
            return False
        reservation = target / FRESH_SCHEMA_RESERVATION_NAME
        reservation_present = os.path.lexists(os.fspath(reservation))
        reservation_state = None
        if reservation_present:
            raw, reservation_state = _read_private_artifact(
                reservation,
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=2 if reservation_temporaries else 1,
            )
            if raw != _fresh_manifest_raw():
                return False
        if reservation_temporaries:
            _raw, temporary_state = _read_private_artifact(
                reservation_temporaries[0],
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=2,
            )
            if reservation_state is None:
                return (
                    temporary_state.st_nlink == 1
                    and not seed_temporaries
                    and not manifest_temporaries
                    and not any((target / name).exists() for name in SEED_FILE_NAMES)
                )
            return (
                temporary_state.st_dev == reservation_state.st_dev
                and temporary_state.st_ino == reservation_state.st_ino
                and temporary_state.st_nlink == 2
            )
        if not reservation_present:
            return False
        if seed_temporaries:
            match = _FRESH_SEED_TEMP_RE.fullmatch(seed_temporaries[0].name)
            if match is None:
                return False
            _raw, temporary_state = _read_private_artifact(
                seed_temporaries[0],
                maximum=MAX_PREFLIGHT_JSON_BYTES,
                maximum_links=2,
            )
            destination = target / match.group(1)
            if not os.path.lexists(os.fspath(destination)):
                return temporary_state.st_nlink == 1
            _destination_raw, destination_state = _read_private_artifact(
                destination,
                maximum=MAX_PREFLIGHT_JSON_BYTES,
                maximum_links=2,
            )
            return (
                temporary_state.st_dev == destination_state.st_dev
                and temporary_state.st_ino == destination_state.st_ino
                and temporary_state.st_nlink == 2
            )
        manifest = _manifest_path(target)
        if manifest_temporaries:
            _raw, temporary_state = _read_private_artifact(
                manifest_temporaries[0],
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=2,
            )
            if not os.path.lexists(os.fspath(manifest)):
                return temporary_state.st_nlink == 1
            manifest_raw, manifest_state = _read_private_artifact(
                manifest,
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=2,
            )
            return (
                manifest_raw == _fresh_manifest_raw()
                and temporary_state.st_dev == manifest_state.st_dev
                and temporary_state.st_ino == manifest_state.st_ino
                and temporary_state.st_nlink == 2
            )
        if os.path.lexists(os.fspath(manifest)):
            manifest_raw, _state = _read_private_artifact(
                manifest,
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=1,
            )
            return manifest_raw == _fresh_manifest_raw()
        return True
    except _BOUNDARY_EXCEPTIONS:
        return False


def _reconcile_fresh_temporary(target: Path, root_descriptor: int | None) -> None:
    if _schema_artifact_issue_pinned(target, root_descriptor) not in {
        None,
        "fresh_schema_initialization_incomplete",
    }:
        raise OSError("invalid fresh schema inventory")
    names = tuple(os.listdir(root_descriptor)) if root_descriptor is not None else tuple(
        entry.name for entry in target.iterdir()
    )
    temporary_names = tuple(name for name in names if _FRESH_RESERVATION_TEMP_RE.fullmatch(name))
    if not temporary_names:
        return
    if len(temporary_names) != 1:
        raise OSError("invalid fresh schema temporary")
    temporary = target / temporary_names[0]
    temporary_raw, temporary_state = _read_private_artifact_at(
        temporary,
        root_descriptor,
        maximum=MAX_SCHEMA_MANIFEST_BYTES,
        maximum_links=2,
    )
    reservation = target / FRESH_SCHEMA_RESERVATION_NAME
    if _entry_exists_at(reservation, root_descriptor):
        reservation_raw, reservation_state = _read_private_artifact_at(
            reservation,
            root_descriptor,
            maximum=MAX_SCHEMA_MANIFEST_BYTES,
            maximum_links=2,
        )
        if (
            reservation_raw != _fresh_manifest_raw()
            or temporary_raw != reservation_raw
            or temporary_state.st_dev != reservation_state.st_dev
            or temporary_state.st_ino != reservation_state.st_ino
            or temporary_state.st_nlink != 2
        ):
            raise OSError("invalid fresh reservation promotion pair")
    elif temporary_state.st_nlink != 1:
        raise OSError("invalid fresh reservation temporary")
    if _schema_artifact_issue_pinned(target, root_descriptor) != "fresh_schema_initialization_incomplete":
        raise OSError("fresh schema inventory changed")
    if root_descriptor is not None and os.unlink in os.supports_dir_fd:
        os.unlink(temporary.name, dir_fd=root_descriptor)
        os.fsync(root_descriptor)
    else:
        temporary.unlink()


def _unlink_relative(path: Path, parent_descriptor: int | None) -> None:
    if parent_descriptor is not None and os.unlink in os.supports_dir_fd:
        os.unlink(path.name, dir_fd=parent_descriptor)
        os.fsync(parent_descriptor)
    else:
        path.unlink()


def _reconcile_fresh_seed_temporary(
    seeds: Path,
    target: Path,
    root_descriptor: int | None,
) -> None:
    if _schema_artifact_issue_pinned(target, root_descriptor) != "fresh_schema_initialization_incomplete":
        raise OSError("invalid fresh schema inventory")
    names = tuple(os.listdir(root_descriptor)) if root_descriptor is not None else tuple(
        entry.name for entry in target.iterdir()
    )
    temporary_names = tuple(name for name in names if _FRESH_SEED_TEMP_RE.fullmatch(name))
    if not temporary_names:
        return
    if len(temporary_names) != 1:
        raise OSError("multiple fresh seed temporaries")
    temporary = target / temporary_names[0]
    match = _FRESH_SEED_TEMP_RE.fullmatch(temporary.name)
    if match is None:
        raise OSError("invalid fresh seed temporary")
    name = match.group(1)
    temporary_raw, temporary_state = _read_private_artifact_at(
        temporary,
        root_descriptor,
        maximum=MAX_PREFLIGHT_JSON_BYTES,
        maximum_links=2,
    )
    destination = target / name
    if _entry_exists_at(destination, root_descriptor):
        destination_raw, destination_state = _read_private_artifact_at(
            destination,
            root_descriptor,
            maximum=MAX_PREFLIGHT_JSON_BYTES,
            maximum_links=2,
        )
        expected = _read_validated_seed_bytes(seeds / name, name, require_single_link=True)
        if (
            temporary_state.st_dev != destination_state.st_dev
            or temporary_state.st_ino != destination_state.st_ino
            or temporary_state.st_nlink != 2
            or temporary_raw != expected
            or destination_raw != expected
        ):
            raise OSError("fresh seed promotion pair invalid")
    elif temporary_state.st_nlink != 1:
        raise OSError("fresh seed temporary links invalid")
    if _schema_artifact_issue_pinned(target, root_descriptor) != "fresh_schema_initialization_incomplete":
        raise OSError("fresh schema inventory changed")
    _unlink_relative(temporary, root_descriptor)
    if _entry_exists_at(temporary, root_descriptor):
        raise OSError("fresh seed temporary removal unverified")


def _reconcile_fresh_manifest_temporary(
    target: Path,
    root_descriptor: int | None,
) -> None:
    if _schema_artifact_issue_pinned(target, root_descriptor) != "fresh_schema_initialization_incomplete":
        raise OSError("invalid fresh schema inventory")
    with _guarded_child_directory(target, root_descriptor, "config") as config_fd:
        config = target / "config"
        names = tuple(os.listdir(config_fd)) if config_fd is not None else tuple(
            entry.name for entry in config.iterdir()
        )
        temporary_names = tuple(name for name in names if _MANIFEST_TEMP_RE.fullmatch(name))
        if not temporary_names:
            return
        if len(temporary_names) != 1:
            raise OSError("multiple fresh manifest temporaries")
        temporary = config / temporary_names[0]
        temporary_raw, temporary_state = _read_private_artifact_at(
            temporary,
            config_fd,
            maximum=MAX_SCHEMA_MANIFEST_BYTES,
            maximum_links=2,
        )
        manifest = _manifest_path(target)
        if _entry_exists_at(manifest, config_fd):
            manifest_raw, manifest_state = _read_private_artifact_at(
                manifest,
                config_fd,
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=2,
            )
            if (
                temporary_state.st_dev != manifest_state.st_dev
                or temporary_state.st_ino != manifest_state.st_ino
                or temporary_state.st_nlink != 2
                or temporary_raw != _fresh_manifest_raw()
                or manifest_raw != _fresh_manifest_raw()
            ):
                raise OSError("fresh manifest promotion pair invalid")
        elif temporary_state.st_nlink != 1:
            raise OSError("fresh manifest temporary links invalid")
        if _schema_artifact_issue_pinned(target, root_descriptor) != "fresh_schema_initialization_incomplete":
            raise OSError("fresh schema inventory changed")
        _unlink_relative(temporary, config_fd)
        if _entry_exists_at(temporary, config_fd):
            raise OSError("fresh manifest temporary removal unverified")


@contextmanager
def _guarded_child_directory(target: Path, root_descriptor: int | None, name: str):
    """Create/open one mutation directory relative to the pinned root."""

    if os.name == "nt":
        with _guarded_mutation_directory(target / name) as descriptor:
            yield descriptor
        return
    if root_descriptor is None:
        raise OSError("schema root descriptor unavailable")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        os.mkdir(name, mode=0o700, dir_fd=root_descriptor)
    except FileExistsError:
        pass
    descriptor = os.open(name, flags, dir_fd=root_descriptor)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("schema mutation directory invalid")
        os.fchmod(descriptor, 0o700)
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o700:
            raise OSError("schema mutation directory permissions invalid")
        yield descriptor
    finally:
        os.close(descriptor)


def _pinned_child_names(
    target: Path,
    root_descriptor: int | None,
    name: str,
) -> tuple[str, ...]:
    if root_descriptor is None:
        child = target / name
        if not os.path.lexists(os.fspath(child)):
            return ()
        if not stat.S_ISDIR(os.lstat(child).st_mode):
            raise OSError("schema artifact directory invalid")
        return tuple(entry.name for entry in child.iterdir())
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=root_descriptor)
    except FileNotFoundError:
        return ()
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("schema artifact directory invalid")
        return tuple(os.listdir(descriptor))
    finally:
        os.close(descriptor)


def _pinned_schema_artifact_names(
    target: Path,
    root_descriptor: int | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if root_descriptor is None:
        root_names = tuple(sorted(entry.name for entry in target.iterdir()))
    else:
        root_names = tuple(sorted(os.listdir(root_descriptor)))
    return (
        root_names,
        tuple(sorted(_pinned_child_names(target, root_descriptor, "config"))),
        tuple(sorted(_pinned_child_names(target, root_descriptor, "backups"))),
    )


def _schema_artifact_issue_pinned(target: Path, root_descriptor: int | None) -> str | None:
    try:
        return _classify_schema_artifact_names(
            *_pinned_schema_artifact_names(target, root_descriptor),
        )
    except _BOUNDARY_EXCEPTIONS:
        return "invalid_schema_artifacts"


@contextmanager
def _pinned_existing_child_directory(
    target: Path,
    root_descriptor: int | None,
    name: str,
):
    path = target / name
    if root_descriptor is None:
        if not os.path.lexists(os.fspath(path)):
            yield None
            return
        with _guarded_mutation_directory(path) as descriptor:
            yield descriptor
        return
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=root_descriptor)
    except FileNotFoundError:
        yield None
        return
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("schema artifact directory invalid")
        yield descriptor
    finally:
        os.close(descriptor)


def _names_from_pinned_directory(path: Path, descriptor: int | None) -> tuple[str, ...]:
    if descriptor is not None:
        return tuple(sorted(os.listdir(descriptor)))
    if not os.path.lexists(os.fspath(path)):
        return ()
    return tuple(sorted(entry.name for entry in path.iterdir()))


def _schema_status_pinned(
    target: Path,
    root_descriptor: int | None,
    *,
    expected_snapshots: tuple[_DocumentSnapshot, ...] | None = None,
) -> str:
    if not _pinned_target_matches(target, root_descriptor):
        return "invalid"
    try:
        root_names = tuple(
            sorted(os.listdir(root_descriptor))
            if root_descriptor is not None
            else sorted(entry.name for entry in target.iterdir())
        )
        with ExitStack() as stack:
            config_fd = stack.enter_context(
                _pinned_existing_child_directory(target, root_descriptor, "config")
            )
            backup_fd = stack.enter_context(
                _pinned_existing_child_directory(target, root_descriptor, "backups")
            )
            config_names = _names_from_pinned_directory(target / "config", config_fd)
            backup_names = _names_from_pinned_directory(target / "backups", backup_fd)
            issue = _classify_schema_artifact_names(
                root_names,
                config_names,
                backup_names,
            )
            manifest_path = _manifest_path(target)
            if SCHEMA_MANIFEST_NAME not in config_names:
                if issue == "fresh_schema_initialization_incomplete":
                    return "fresh_incomplete"
                return "legacy" if issue is None else "invalid"
            manifest_raw, manifest_state = _read_private_artifact_at(
                manifest_path,
                config_fd,
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=2,
            )
            manifest_status, manifest = _manifest_payload_status(
                json.loads(manifest_raw.decode("utf-8"))
            )
            if manifest_status in {"newer", "invalid"}:
                return manifest_status
            if manifest is None:
                return "invalid"
            if issue == "fresh_schema_initialization_incomplete":
                return (
                    "fresh_incomplete"
                    if manifest.get("origin") == "fresh_seed"
                    else "invalid"
                )
            if manifest_state.st_nlink != 1:
                return "invalid"
            if issue not in {None, "schema_backup_present"}:
                return "invalid"
            live_snapshots = _load_snapshots_at(target, root_descriptor)
            if expected_snapshots is not None and not _snapshots_match(
                live_snapshots,
                expected_snapshots,
            ):
                return "invalid"
            backup = manifest.get("backup")
            backup_raw: bytes | None = None
            backup_state: os.stat_result | None = None
            schema_backups = tuple(
                name
                for name in backup_names
                if _BACKUP_RE.fullmatch(name) or _BACKUP_TEMP_RE.fullmatch(name)
            )
            if backup is None:
                if manifest.get("origin") != "fresh_seed" or schema_backups:
                    return "invalid"
            else:
                if schema_backups != (backup.get("name"),):
                    return "invalid"
                backup_path = target / "backups" / backup["name"]
                backup_raw, backup_state = _read_private_artifact_at(
                    backup_path,
                    backup_fd,
                    maximum=MAX_SCHEMA_BACKUP_BYTES,
                    maximum_links=1,
                )
                if (
                    _digest(backup_raw) != backup.get("sha256")
                    or not _backup_archive_self_valid(backup_raw, backup.get("name"))
                ):
                    return "invalid"
            verified_manifest_raw, verified_manifest_state = _read_private_artifact_at(
                manifest_path,
                config_fd,
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=1,
            )
            if (
                verified_manifest_raw != manifest_raw
                or verified_manifest_state.st_dev != manifest_state.st_dev
                or verified_manifest_state.st_ino != manifest_state.st_ino
            ):
                return "invalid"
            if backup is not None:
                assert backup_raw is not None and backup_state is not None
                verified_backup_raw, verified_backup_state = _read_private_artifact_at(
                    target / "backups" / backup["name"],
                    backup_fd,
                    maximum=MAX_SCHEMA_BACKUP_BYTES,
                    maximum_links=1,
                )
                if (
                    verified_backup_raw != backup_raw
                    or verified_backup_state.st_dev != backup_state.st_dev
                    or verified_backup_state.st_ino != backup_state.st_ino
                ):
                    return "invalid"
            if (
                root_names
                != (
                    tuple(sorted(os.listdir(root_descriptor)))
                    if root_descriptor is not None
                    else tuple(sorted(entry.name for entry in target.iterdir()))
                )
                or config_names
                != _names_from_pinned_directory(target / "config", config_fd)
                or backup_names
                != _names_from_pinned_directory(target / "backups", backup_fd)
                or not _pinned_target_matches(target, root_descriptor)
            ):
                return "invalid"
            return "current"
    except _BOUNDARY_EXCEPTIONS:
        return "invalid"


def _recognized_schema_temporaries(target: Path) -> tuple[tuple[str, Path, str], ...]:
    found: list[tuple[str, Path, str]] = []
    for directory, pattern, kind in (
        ("config", _MANIFEST_TEMP_RE, "manifest_temporary"),
        ("backups", _BACKUP_TEMP_RE, "backup_temporary"),
    ):
        root = target / directory
        if not os.path.lexists(os.fspath(root)):
            continue
        metadata = os.lstat(root)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("invalid schema temporary directory")
        found.extend(
            (directory, entry, kind)
            for entry in root.iterdir()
            if pattern.fullmatch(entry.name)
        )
    return tuple(found)


def _read_recovery_artifact(
    target: Path,
    directory: str,
    path: Path,
    kind: str,
    snapshots: tuple[_DocumentSnapshot, ...],
    token: str,
) -> _RecoveryArtifact | None:
    maximum = MAX_SCHEMA_MANIFEST_BYTES if kind == "manifest_temporary" else MAX_SCHEMA_BACKUP_BYTES
    try:
        raw, temporary_state = _read_private_artifact(
            path,
            maximum=maximum,
            maximum_links=2,
        )
        if kind == "manifest_temporary":
            final = _manifest_path(target)
            backup_raw = _build_backup(snapshots, token)
            expected_raw = _canonical_json(
                _manifest_document(
                    origin="schema_migration",
                    backup_name=_backup_name(token),
                    backup_sha256=_digest(backup_raw),
                )
            )
        else:
            match = _BACKUP_TEMP_RE.fullmatch(path.name)
            if match is None or match.group(1) != _backup_name(token):
                return None
            final = target / "backups" / match.group(1)
            expected_raw = _build_backup(snapshots, token)
        final_present = os.path.lexists(os.fspath(final))
        if final_present:
            final_raw, final_state = _read_private_artifact(
                final,
                maximum=maximum,
                maximum_links=2,
            )
            if (
                temporary_state.st_dev != final_state.st_dev
                or temporary_state.st_ino != final_state.st_ino
                or temporary_state.st_nlink != 2
                or raw != expected_raw
                or final_raw != expected_raw
            ):
                return None
        elif temporary_state.st_nlink != 1:
            return None
        return _RecoveryArtifact(
            directory=directory,
            name=path.name,
            kind=kind,
            size=len(raw),
            digest=_digest(raw),
            final_present=final_present,
        )
    except _BOUNDARY_EXCEPTIONS:
        return None


def _recovery_token(
    target: Path,
    snapshots: tuple[_DocumentSnapshot, ...],
    artifact: _RecoveryArtifact,
) -> str:
    return _digest(
        _canonical_json(
            {
                "protocol_version": SCHEMA_FORMAT_VERSION,
                "target": os.fspath(target),
                "step": "discard-orphan-schema-temporary",
                "artifact": {
                    "directory": artifact.directory,
                    "name": artifact.name,
                    "kind": artifact.kind,
                    "size": artifact.size,
                    "sha256": artifact.digest,
                    "promotion_state": (
                        "promoted_pair" if artifact.final_present else "temporary_only"
                    ),
                },
                "items": [
                    {
                        "name": item.name,
                        "size": item.size,
                        "sha256": item.digest,
                    }
                    for item in snapshots
                ],
            }
        )
    )


def _preview_token(target: Path, snapshots: tuple[_DocumentSnapshot, ...]) -> str:
    return _digest(
        _canonical_json(
            {
                "protocol_version": SCHEMA_FORMAT_VERSION,
                "target": os.fspath(target),
                "expected_manifest": "absent",
                "step": SCHEMA_STEP_ID,
                "items": [
                    {
                        "name": snapshot.name,
                        "from_version": LEGACY_DOCUMENT_VERSION,
                        "to_version": CURRENT_DOCUMENT_VERSION,
                        "size": snapshot.size,
                        "sha256": snapshot.digest,
                    }
                    for snapshot in snapshots
                ],
                "excluded": list(_EXCLUDED_ITEMS),
            }
        )
    )


def _backup_manifest(
    snapshots: tuple[_DocumentSnapshot, ...],
    token: str,
) -> dict:
    return {
        "format_version": SCHEMA_FORMAT_VERSION,
        "kind": "mentat-data-schema-backup",
        "token_sha256": token,
        "from_version": LEGACY_DOCUMENT_VERSION,
        "to_version": CURRENT_DOCUMENT_VERSION,
        "items": [
            {"name": item.name, "size": item.size, "sha256": item.digest}
            for item in snapshots
        ],
    }


def _zip_entry(name: str) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.compress_type = zipfile.ZIP_STORED
    entry.create_system = 3
    entry.external_attr = 0o600 << 16
    return entry


def _build_backup(snapshots: tuple[_DocumentSnapshot, ...], token: str) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(_zip_entry("manifest.json"), _canonical_json(_backup_manifest(snapshots, token)))
        for snapshot in snapshots:
            archive.writestr(_zip_entry(f"data/{snapshot.name}"), snapshot.raw)
    raw = output.getvalue()
    if len(raw) > MAX_SCHEMA_BACKUP_BYTES:
        raise OverflowError("schema_backup_too_large")
    return raw


def _backup_valid(
    path: Path,
    snapshots: tuple[_DocumentSnapshot, ...],
    token: str,
    *,
    expected_raw: bytes | None = None,
) -> bool:
    try:
        descriptor = _open_readonly_no_follow(path)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            metadata = os.fstat(handle.fileno())
            if (
                not _owner_only_regular_descriptor(handle.fileno())
                or metadata.st_size > MAX_SCHEMA_BACKUP_BYTES
            ):
                return False
            raw = handle.read(MAX_SCHEMA_BACKUP_BYTES + 1)
        if expected_raw is not None and raw != expected_raw:
            return False
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            expected_names = ["manifest.json", *(f"data/{name}" for name in SEED_FILE_NAMES)]
            if archive.namelist() != expected_names:
                return False
            if archive.getinfo("manifest.json").file_size > MAX_SCHEMA_MANIFEST_BYTES:
                return False
            manifest_raw = archive.read("manifest.json")
            if len(manifest_raw) > MAX_SCHEMA_MANIFEST_BYTES:
                return False
            if json.loads(manifest_raw.decode("utf-8")) != _backup_manifest(snapshots, token):
                return False
            by_name = {snapshot.name: snapshot for snapshot in snapshots}
            for name in SEED_FILE_NAMES:
                if archive.getinfo(f"data/{name}").file_size > MAX_PREFLIGHT_JSON_BYTES:
                    return False
                if archive.read(f"data/{name}") != by_name[name].raw:
                    return False
    except _BOUNDARY_EXCEPTIONS:
        return False
    return True


def _manifest_backup_valid(target: Path, manifest: Mapping) -> bool:
    backup = manifest.get("backup")
    if backup is None:
        return manifest.get("origin") == "fresh_seed"
    try:
        path = target / "backups" / backup["name"]
        descriptor = _open_readonly_no_follow(path)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            metadata = os.fstat(handle.fileno())
            if (
                not _owner_only_regular_descriptor(handle.fileno())
                or metadata.st_size > MAX_SCHEMA_BACKUP_BYTES
            ):
                return False
            raw = handle.read(MAX_SCHEMA_BACKUP_BYTES + 1)
    except _BOUNDARY_EXCEPTIONS:
        return False
    return (
        _digest(raw) == backup.get("sha256")
        and _backup_archive_self_valid(raw, backup.get("name"))
    )


def _backup_archive_self_valid(raw: bytes, backup_name: str | None) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            expected_names = ["manifest.json", *(f"data/{name}" for name in SEED_FILE_NAMES)]
            if archive.namelist() != expected_names:
                return False
            if archive.getinfo("manifest.json").file_size > MAX_SCHEMA_MANIFEST_BYTES:
                return False
            manifest_raw = archive.read("manifest.json")
            if len(manifest_raw) > MAX_SCHEMA_MANIFEST_BYTES:
                return False
            manifest = json.loads(manifest_raw.decode("utf-8"))
            if type(manifest) is not dict or set(manifest) != {
                "format_version",
                "kind",
                "token_sha256",
                "from_version",
                "to_version",
                "items",
            }:
                return False
            if (
                manifest.get("format_version") != SCHEMA_FORMAT_VERSION
                or type(manifest.get("format_version")) is not int
                or manifest.get("kind") != "mentat-data-schema-backup"
                or not isinstance(manifest.get("token_sha256"), str)
                or _TOKEN_RE.fullmatch(manifest["token_sha256"]) is None
                or manifest.get("from_version") != LEGACY_DOCUMENT_VERSION
                or manifest.get("to_version") != CURRENT_DOCUMENT_VERSION
                or type(manifest.get("from_version")) is not int
                or type(manifest.get("to_version")) is not int
            ):
                return False
            backup_match = _BACKUP_RE.fullmatch(str(backup_name or ""))
            if (
                backup_match is None
                or not manifest["token_sha256"].startswith(backup_match.group(1))
            ):
                return False
            items = manifest.get("items")
            if not isinstance(items, list) or len(items) != len(SEED_FILE_NAMES):
                return False
            if [item.get("name") for item in items if type(item) is dict] != list(SEED_FILE_NAMES):
                return False
            for item in items:
                if (
                    type(item) is not dict
                    or set(item) != {"name", "size", "sha256"}
                    or type(item.get("size")) is not int
                    or not 0 <= item["size"] <= MAX_PREFLIGHT_JSON_BYTES
                    or not isinstance(item.get("sha256"), str)
                    or _TOKEN_RE.fullmatch(item["sha256"]) is None
                ):
                    return False
                if archive.getinfo(f"data/{item['name']}").file_size > MAX_PREFLIGHT_JSON_BYTES:
                    return False
                content = archive.read(f"data/{item['name']}")
                if len(content) != item["size"] or _digest(content) != item["sha256"]:
                    return False
                document = json.loads(content.decode("utf-8"))
                if type(document) is not SEED_ROOT_TYPES[item["name"]]:
                    return False
    except _BOUNDARY_EXCEPTIONS:
        return False
    return True


def _current_artifacts_valid(target: Path, manifest: Mapping) -> bool:
    config_root = target / "config"
    backup_root = target / "backups"
    backup = manifest.get("backup")
    try:
        config_metadata = os.lstat(config_root)
        if not stat.S_ISDIR(config_metadata.st_mode):
            return False
        if any(_MANIFEST_TEMP_RE.fullmatch(entry.name) for entry in config_root.iterdir()):
            return False
        if not os.path.lexists(os.fspath(backup_root)):
            schema_backups = []
        else:
            backup_metadata = os.lstat(backup_root)
            if not stat.S_ISDIR(backup_metadata.st_mode):
                return False
            schema_backups = [
                entry.name
                for entry in backup_root.iterdir()
                if _BACKUP_RE.fullmatch(entry.name) or _BACKUP_TEMP_RE.fullmatch(entry.name)
            ]
    except _BOUNDARY_EXCEPTIONS:
        return False
    expected = [] if backup is None else [backup.get("name")]
    return schema_backups == expected


def _schema_status_guarded(target: Path) -> str:
    if _manifest_declares_newer(target):
        return "newer"
    artifact_issue = _schema_artifact_issue(target)
    if artifact_issue == "fresh_schema_initialization_incomplete":
        return "fresh_incomplete" if _fresh_initialization_recoverable(target) else "invalid"
    if artifact_issue == "invalid_schema_artifacts":
        return "invalid"
    manifest_status, manifest = _read_manifest(target)
    if manifest_status == "legacy":
        return "invalid" if artifact_issue is not None else "legacy"
    if manifest_status in {"invalid", "newer"}:
        return manifest_status
    try:
        _load_snapshots(target, private=True)
    except _BOUNDARY_EXCEPTIONS:
        return "invalid"
    if manifest is None or not _manifest_backup_valid(target, manifest):
        return "invalid"
    if not _current_artifacts_valid(target, manifest):
        return "invalid"
    if os.path.lexists(os.fspath(target / FRESH_SCHEMA_RESERVATION_NAME)):
        if manifest.get("origin") == "fresh_seed" and _fresh_initialization_recoverable(target):
            return "fresh_incomplete"
        return "invalid"
    return "current"


def schema_preflight_status(data_root: Path) -> str:
    """Read-only schema gate used before any startup lock or layout mutation."""

    target = _absolute_without_following(Path(data_root))
    if not os.path.lexists(os.fspath(target)):
        return "legacy"
    if _root_issue(target, "target_root", allow_missing=False) is not None:
        return "invalid"
    try:
        return _schema_status_guarded(target)
    except _BOUNDARY_EXCEPTIONS:
        return "invalid"


def schema_status_under_lock(target: Path, root_descriptor: int | None) -> str:
    if not _pinned_target_matches(target, root_descriptor):
        return "invalid"
    status = _schema_status_pinned(target, root_descriptor)
    return status if _pinned_target_matches(target, root_descriptor) else "invalid"


def schema_startup_status(data_root: Path) -> str:
    """Return legacy, current, newer, or invalid under the pinned shared lock."""

    target = _absolute_without_following(Path(data_root))
    if not os.path.lexists(os.fspath(target)):
        return "legacy"
    if _root_issue(target, "target_root", allow_missing=False) is not None:
        return "invalid"
    try:
        with _initialization_lock(target) as root_descriptor:
            if not _pinned_target_matches(target, root_descriptor):
                return "invalid"
            result = _schema_status_pinned(target, root_descriptor)
            if not _pinned_target_matches(target, root_descriptor):
                return "invalid"
            return result
    except _BOUNDARY_EXCEPTIONS:
        return "invalid"


def _preview_schema_migration_guarded(
    seed_root: Path,
    data_root: Path,
    *,
    home: Path | None = None,
) -> SchemaPreview:
    seeds = _absolute_without_following(Path(seed_root))
    target = _absolute_without_following(Path(data_root))
    home_path = _absolute_without_following(Path(home)) if home is not None else Path.home()
    if _same_path(seeds, target):
        return _blocked("development_override", "schema_development_override")
    if _path_contains(seeds, target) or _path_contains(target, seeds):
        return _blocked("unsafe", "schema_seed_target_overlap")
    issue = _root_issue(target, "target_root", allow_missing=False)
    if issue is not None or _root_is_too_broad(target, home_path):
        return _blocked("unsafe", issue or "schema_root_too_broad")
    if _manifest_declares_newer(target):
        return _blocked("newer_unsupported", "schema_version_newer_than_supported")
    manifest_status, _manifest = _read_manifest(target)
    if manifest_status == "newer":
        return _blocked("newer_unsupported", "schema_version_newer_than_supported")
    artifact_issue = _schema_artifact_issue(target)
    if artifact_issue == "fresh_schema_initialization_incomplete":
        return _blocked("unsafe", artifact_issue)
    if artifact_issue == "invalid_schema_artifacts":
        return _blocked("unsafe", artifact_issue)
    temporaries = _recognized_schema_temporaries(target)
    if temporaries:
        if len(temporaries) != 1:
            return _blocked("unsafe", "multiple_schema_temporaries")
        if manifest_status != "legacy" and temporaries[0][2] == "backup_temporary":
            return _blocked("unsafe", "schema_temporary_conflicts_with_manifest")
        if manifest_status == "invalid" and temporaries[0][2] != "manifest_temporary":
            return _blocked("unsafe", "invalid_schema_manifest")
        try:
            snapshots = _load_snapshots(target, private=True)
        except _BOUNDARY_EXCEPTIONS:
            return _blocked("unsafe", "schema_live_inventory_invalid")
        token = _preview_token(target, snapshots)
        directory, path, kind = temporaries[0]
        recovery = _read_recovery_artifact(
            target,
            directory,
            path,
            kind,
            snapshots,
            token,
        )
        if recovery is None:
            return _blocked("unsafe", "invalid_schema_temporary")
        return SchemaPreview(
            status="recovery_required",
            items=_items("reconcile_temporary"),
            issues=(artifact_issue or "incomplete_schema_temporary",),
            confirmation_token=_recovery_token(target, snapshots, recovery),
            _snapshots=snapshots,
            _recovery=recovery,
        )
    if manifest_status == "invalid":
        return _blocked("unsafe", "invalid_schema_manifest")
    if manifest_status == "current":
        if _schema_status_guarded(target) != "current":
            return _blocked("unsafe", "invalid_current_schema")
        return SchemaPreview(
            status="already_current",
            items=_items("verify_current", 1, 1),
        )
    try:
        snapshots = _load_snapshots(target, private=True)
    except _BOUNDARY_EXCEPTIONS:
        return _blocked("unsafe", "schema_live_inventory_invalid")
    token = _preview_token(target, snapshots)
    backup_path = target / "backups" / _backup_name(token)
    artifact_issue = _schema_artifact_issue(target)
    if artifact_issue is not None:
        if (
            artifact_issue == "schema_backup_present"
            and os.path.lexists(os.fspath(backup_path))
            and _backup_valid(
                backup_path,
                snapshots,
                token,
                expected_raw=_build_backup(snapshots, token),
            )
            and sorted(
                entry.name
                for entry in (target / "backups").iterdir()
                if _BACKUP_RE.fullmatch(entry.name)
            ) == [backup_path.name]
        ):
            return SchemaPreview(
                status="resume_required",
                items=_items("record_version"),
                confirmation_token=token,
                _snapshots=snapshots,
            )
        return _blocked("unsafe", artifact_issue)
    return SchemaPreview(
        status="ready",
        items=_items("record_version"),
        confirmation_token=token,
        _snapshots=snapshots,
    )


def preview_schema_migration(
    seed_root: Path,
    data_root: Path,
    *,
    home: Path | None = None,
) -> SchemaPreview:
    try:
        return _preview_schema_migration_guarded(seed_root, data_root, home=home)
    except _BOUNDARY_EXCEPTIONS:
        return _blocked("unsafe", "schema_preview_failed")


def _result_blocked(preview: SchemaPreview, issue: str | None = None) -> SchemaResult:
    issues = preview.issues if issue is None else (*preview.issues, issue)
    return SchemaResult(status="blocked", items=_items("blocked"), issues=issues)


def _discard_recovery_artifact(
    target: Path,
    root_descriptor: int | None,
    artifact: _RecoveryArtifact,
    mutation_state: list[bool],
) -> str:
    expected_issue = (
        "incomplete_schema_manifest_temporary"
        if artifact.kind == "manifest_temporary"
        else "incomplete_schema_backup_temporary"
    )
    if _schema_artifact_issue_pinned(target, root_descriptor) != expected_issue:
        raise OSError("schema recovery inventory changed")
    before_inventory = _pinned_schema_artifact_names(target, root_descriptor)
    with _guarded_child_directory(target, root_descriptor, artifact.directory) as parent_fd:
        path = target / artifact.directory / artifact.name
        names = tuple(os.listdir(parent_fd)) if parent_fd is not None else tuple(
            entry.name for entry in (target / artifact.directory).iterdir()
        )
        pattern = _MANIFEST_TEMP_RE if artifact.kind == "manifest_temporary" else _BACKUP_TEMP_RE
        if tuple(name for name in names if pattern.fullmatch(name)) != (artifact.name,):
            raise OSError("schema recovery inventory changed")
        maximum = (
            MAX_SCHEMA_MANIFEST_BYTES
            if artifact.kind == "manifest_temporary"
            else MAX_SCHEMA_BACKUP_BYTES
        )
        raw, temporary_state = _read_private_artifact_at(
            path,
            parent_fd,
            maximum=maximum,
            maximum_links=2,
        )
        if artifact.kind == "manifest_temporary":
            final = _manifest_path(target)
        else:
            match = _BACKUP_TEMP_RE.fullmatch(artifact.name)
            if match is None:
                raise OSError("invalid schema recovery artifact")
            final = target / "backups" / match.group(1)
        final_present = _entry_exists_at(final, parent_fd)
        if final_present != artifact.final_present:
            raise _RecoveryStateChanged("schema recovery promotion state changed")
        final_raw: bytes | None = None
        final_state: os.stat_result | None = None
        if final_present:
            final_raw, final_state = _read_private_artifact_at(
                final,
                parent_fd,
                maximum=maximum,
                maximum_links=2,
            )
            if (
                temporary_state.st_dev != final_state.st_dev
                or temporary_state.st_ino != final_state.st_ino
                or temporary_state.st_nlink != 2
                or final_raw != raw
            ):
                raise OSError("schema recovery promotion pair changed")
        elif temporary_state.st_nlink != 1:
            raise OSError("schema recovery temporary links changed")
        if len(raw) != artifact.size or _digest(raw) != artifact.digest:
            raise OSError("schema recovery artifact changed")
        if _schema_artifact_issue_pinned(target, root_descriptor) != expected_issue:
            raise OSError("schema recovery inventory changed")
        try:
            immediate_raw, immediate_temporary_state = _read_private_artifact_at(
                path,
                parent_fd,
                maximum=maximum,
                maximum_links=2,
            )
            immediate_final_present = _entry_exists_at(final, parent_fd)
            if immediate_final_present != artifact.final_present:
                raise _RecoveryStateChanged("schema recovery promotion state changed")
            if immediate_final_present:
                immediate_final_raw, immediate_final_state = _read_private_artifact_at(
                    final,
                    parent_fd,
                    maximum=maximum,
                    maximum_links=2,
                )
                immediate_valid = (
                    immediate_temporary_state.st_dev == immediate_final_state.st_dev
                    and immediate_temporary_state.st_ino == immediate_final_state.st_ino
                    and immediate_temporary_state.st_nlink == 2
                    and immediate_final_raw == immediate_raw
                )
            else:
                immediate_valid = immediate_temporary_state.st_nlink == 1
            if (
                not immediate_valid
                or len(immediate_raw) != artifact.size
                or _digest(immediate_raw) != artifact.digest
            ):
                raise _RecoveryStateChanged("schema recovery evidence changed")
        except _RecoveryStateChanged:
            raise
        except _BOUNDARY_EXCEPTIONS as exc:
            raise _RecoveryStateChanged("schema recovery evidence changed") from exc
        mutation_state[0] = True
        _unlink_relative(path, parent_fd)
        if _entry_exists_at(path, parent_fd):
            raise OSError("schema recovery artifact removal unverified")
        after_inventory = _pinned_schema_artifact_names(target, root_descriptor)
        expected_inventory = [list(names) for names in before_inventory]
        inventory_index = 1 if artifact.directory == "config" else 2
        expected_inventory[inventory_index].remove(artifact.name)
        if after_inventory != tuple(tuple(names) for names in expected_inventory):
            raise OSError("schema recovery post-inventory changed")
        if final_present:
            assert final_raw is not None and final_state is not None
            verified_raw, verified_state = _read_private_artifact_at(
                final,
                parent_fd,
                maximum=maximum,
                maximum_links=1,
            )
            if (
                verified_raw != final_raw
                or verified_state.st_dev != final_state.st_dev
                or verified_state.st_ino != final_state.st_ino
            ):
                raise OSError("schema recovery final changed")
        elif _entry_exists_at(final, parent_fd):
            raise OSError("schema recovery final appeared")
        backup_names = tuple(
            name for name in after_inventory[2] if _BACKUP_RE.fullmatch(name)
        )
        if artifact.kind == "manifest_temporary":
            return "already_current" if final_present else (
                "resume_required" if backup_names else "ready"
            )
        return "resume_required" if final_present else "ready"


def _recovery_post_state_pinned(
    target: Path,
    root_descriptor: int | None,
    snapshots: tuple[_DocumentSnapshot, ...],
    expected_status: str,
) -> bool:
    if expected_status == "already_current":
        return (
            _schema_status_pinned(
                target,
                root_descriptor,
                expected_snapshots=snapshots,
            )
            == "current"
        )
    try:
        inventory = _pinned_schema_artifact_names(target, root_descriptor)
        if SCHEMA_MANIFEST_NAME in inventory[1]:
            return False
        issue = _classify_schema_artifact_names(*inventory)
        if expected_status == "ready":
            return issue is None and _snapshots_match(
                _load_snapshots_at(target, root_descriptor),
                snapshots,
            ) and inventory == _pinned_schema_artifact_names(target, root_descriptor)
        if expected_status != "resume_required" or issue != "schema_backup_present":
            return False
        token = _preview_token(target, snapshots)
        backup_name = _backup_name(token)
        schema_backups = tuple(name for name in inventory[2] if _BACKUP_RE.fullmatch(name))
        if schema_backups != (backup_name,):
            return False
        with _pinned_existing_child_directory(
            target,
            root_descriptor,
            "backups",
        ) as backup_fd:
            raw, _state = _read_private_artifact_at(
                target / "backups" / backup_name,
                backup_fd,
                maximum=MAX_SCHEMA_BACKUP_BYTES,
                maximum_links=1,
            )
        return (
            raw == _build_backup(snapshots, token)
            and _snapshots_match(
                _load_snapshots_at(target, root_descriptor),
                snapshots,
            )
            and inventory == _pinned_schema_artifact_names(target, root_descriptor)
        )
    except _BOUNDARY_EXCEPTIONS:
        return False


def _pinned_confirmation_matches(
    target: Path,
    root_descriptor: int | None,
    preview: SchemaPreview,
) -> bool:
    """Revalidate a confirmed preview using only the retained root tree."""

    if (
        preview.status not in {"ready", "resume_required", "recovery_required"}
        or preview.confirmation_token is None
        or not _pinned_target_matches(target, root_descriptor)
    ):
        return False
    try:
        before_inventory = _pinned_schema_artifact_names(target, root_descriptor)
        snapshots = _load_snapshots_at(target, root_descriptor)
        if not _snapshots_match(snapshots, preview._snapshots):
            return False
        issue = _classify_schema_artifact_names(*before_inventory)
        if (
            preview.status != "recovery_required"
            and SCHEMA_MANIFEST_NAME in before_inventory[1]
        ):
            return False

        if preview.status == "ready":
            valid = (
                issue is None
                and preview.confirmation_token == _preview_token(target, snapshots)
            )
        elif preview.status == "resume_required":
            token = _preview_token(target, snapshots)
            backup_name = _backup_name(token)
            backup_names = tuple(
                name for name in before_inventory[2] if _BACKUP_RE.fullmatch(name)
            )
            valid = (
                issue == "schema_backup_present"
                and preview.confirmation_token == token
                and backup_names == (backup_name,)
            )
            if valid:
                with _pinned_existing_child_directory(
                    target,
                    root_descriptor,
                    "backups",
                ) as backup_fd:
                    raw, _state = _read_private_artifact_at(
                        target / "backups" / backup_name,
                        backup_fd,
                        maximum=MAX_SCHEMA_BACKUP_BYTES,
                        maximum_links=1,
                    )
                valid = raw == _build_backup(snapshots, token)
        else:
            artifact = preview._recovery
            if artifact is None:
                return False
            expected_issue = (
                "incomplete_schema_manifest_temporary"
                if artifact.kind == "manifest_temporary"
                else "incomplete_schema_backup_temporary"
            )
            inventory_index = 1 if artifact.directory == "config" else 2
            pattern = (
                _MANIFEST_TEMP_RE
                if artifact.kind == "manifest_temporary"
                else _BACKUP_TEMP_RE
            )
            temporary_names = tuple(
                name for name in before_inventory[inventory_index] if pattern.fullmatch(name)
            )
            valid = issue == expected_issue and temporary_names == (artifact.name,)
            if valid:
                maximum = (
                    MAX_SCHEMA_MANIFEST_BYTES
                    if artifact.kind == "manifest_temporary"
                    else MAX_SCHEMA_BACKUP_BYTES
                )
                with _pinned_existing_child_directory(
                    target,
                    root_descriptor,
                    artifact.directory,
                ) as parent_fd:
                    path = target / artifact.directory / artifact.name
                    raw, temporary_state = _read_private_artifact_at(
                        path,
                        parent_fd,
                        maximum=maximum,
                        maximum_links=2,
                    )
                    if artifact.kind == "manifest_temporary":
                        final = _manifest_path(target)
                    else:
                        match = _BACKUP_TEMP_RE.fullmatch(artifact.name)
                        if match is None:
                            return False
                        final = target / "backups" / match.group(1)
                    final_present = _entry_exists_at(final, parent_fd)
                    if final_present:
                        final_raw, final_state = _read_private_artifact_at(
                            final,
                            parent_fd,
                            maximum=maximum,
                            maximum_links=2,
                        )
                        valid = (
                            temporary_state.st_dev == final_state.st_dev
                            and temporary_state.st_ino == final_state.st_ino
                            and temporary_state.st_nlink == 2
                            and final_raw == raw
                        )
                    else:
                        valid = temporary_state.st_nlink == 1
                actual_artifact = _RecoveryArtifact(
                    directory=artifact.directory,
                    name=artifact.name,
                    kind=artifact.kind,
                    size=len(raw),
                    digest=_digest(raw),
                    final_present=final_present,
                )
                valid = (
                    valid
                    and actual_artifact == artifact
                    and preview.confirmation_token
                    == _recovery_token(target, snapshots, actual_artifact)
                )

        return (
            valid
            and before_inventory == _pinned_schema_artifact_names(target, root_descriptor)
            and _snapshots_match(
                _load_snapshots_at(target, root_descriptor),
                snapshots,
            )
            and _pinned_target_matches(target, root_descriptor)
        )
    except _BOUNDARY_EXCEPTIONS:
        return False


def migrate_data_schema(
    seed_root: Path,
    data_root: Path,
    *,
    confirmation_token: str,
    home: Path | None = None,
) -> SchemaResult:
    seeds = _absolute_without_following(Path(seed_root))
    target = _absolute_without_following(Path(data_root))
    initial = preview_schema_migration(seeds, target, home=home)
    if initial.status not in {"ready", "resume_required", "recovery_required"}:
        return _result_blocked(initial)
    if (
        _TOKEN_RE.fullmatch(str(confirmation_token)) is None
        or confirmation_token != initial.confirmation_token
    ):
        return _result_blocked(initial, "confirmation_mismatch")
    backup_existed = initial.status == "resume_required"
    backup_published = backup_existed
    recovery_mutated = [False]

    def mark_backup_published() -> None:
        nonlocal backup_published
        backup_published = True

    try:
        with _initialization_lock(target) as root_descriptor:
            if not _pinned_target_matches(target, root_descriptor):
                return _result_blocked(initial, "schema_target_changed")
            if not _pinned_confirmation_matches(target, root_descriptor, initial):
                return _result_blocked(initial, "schema_state_changed")
            current = initial
            if current.status == "recovery_required":
                if current._recovery is None or not _pinned_target_matches(target, root_descriptor):
                    return _result_blocked(current, "schema_target_changed")
                try:
                    expected_post_status = _discard_recovery_artifact(
                        target,
                        root_descriptor,
                        current._recovery,
                        recovery_mutated,
                    )
                except _RecoveryStateChanged:
                    return _result_blocked(current, "schema_state_changed")
                if (
                    not _recovery_post_state_pinned(
                        target,
                        root_descriptor,
                        current._snapshots,
                        expected_post_status,
                    )
                    or not _recovery_post_state_pinned(
                        target,
                        root_descriptor,
                        current._snapshots,
                        expected_post_status,
                    )
                    or not _pinned_target_matches(target, root_descriptor)
                ):
                    raise OSError("schema recovery post-state invalid")
                return SchemaResult(
                    status="reconciled",
                    items=_items("reconciled_temporary"),
                )
            backup_name = _backup_name(confirmation_token)
            backup_path = target / "backups" / backup_name
            backup_raw = _build_backup(current._snapshots, confirmation_token)
            if not _pinned_target_matches(target, root_descriptor):
                return _result_blocked(current, "schema_target_changed")
            with (
                _guarded_child_directory(target, root_descriptor, "backups") as backup_fd,
                _guarded_child_directory(target, root_descriptor, "config") as config_fd,
            ):
                if not _pinned_target_matches(target, root_descriptor):
                    return _result_blocked(current, "schema_target_changed")
                if _entry_exists_at(backup_path, backup_fd):
                    existing_raw, _existing_state = _read_private_artifact_at(
                        backup_path,
                        backup_fd,
                        maximum=MAX_SCHEMA_BACKUP_BYTES,
                        maximum_links=1,
                    )
                    if existing_raw != backup_raw:
                        return _result_blocked(current, "schema_backup_invalid")
                else:
                    _publish_raw_missing(
                        backup_path,
                        backup_raw,
                        parent_fd=backup_fd,
                        maximum=len(backup_raw),
                        on_published=mark_backup_published,
                    )
                    published_raw, _published_state = _read_private_artifact_at(
                        backup_path,
                        backup_fd,
                        maximum=MAX_SCHEMA_BACKUP_BYTES,
                        maximum_links=1,
                    )
                    if published_raw != backup_raw:
                        raise OSError("published schema backup changed")
                final_backup_raw, _final_backup_state = _read_private_artifact_at(
                    backup_path,
                    backup_fd,
                    maximum=MAX_SCHEMA_BACKUP_BYTES,
                    maximum_links=1,
                )
                if final_backup_raw != backup_raw:
                    if backup_published:
                        raise OSError("schema backup changed before manifest publication")
                    return _result_blocked(current, "schema_backup_invalid")
                if not _pinned_target_matches(target, root_descriptor):
                    return SchemaResult(
                        status="partial_failure" if backup_published else "blocked",
                        items=_items("unverified"),
                        issues=("schema_target_changed",),
                    )
                manifest_raw = _canonical_json(
                    _manifest_document(
                        origin="schema_migration",
                        backup_name=backup_name,
                        backup_sha256=_digest(backup_raw),
                    )
                )
                _publish_raw_missing(
                    _manifest_path(target),
                    manifest_raw,
                    parent_fd=config_fd,
                    maximum=MAX_SCHEMA_MANIFEST_BYTES,
                )
            if (
                not _pinned_target_matches(target, root_descriptor)
                or _schema_status_pinned(
                    target,
                    root_descriptor,
                    expected_snapshots=current._snapshots,
                )
                != "current"
                or _schema_status_pinned(
                    target,
                    root_descriptor,
                    expected_snapshots=current._snapshots,
                )
                != "current"
                or not _pinned_target_matches(target, root_descriptor)
            ):
                return SchemaResult(
                    status="partial_failure",
                    items=_items("unverified"),
                    issues=("schema_verification_failed",),
                )
    except _BOUNDARY_EXCEPTIONS:
        partial = (
            backup_published
            or recovery_mutated[0]
            or _schema_artifact_issue(target) is not None
        )
        return SchemaResult(
            status="partial_failure" if partial else "blocked",
            items=_items("unverified"),
            issues=("schema_migration_failed",),
        )
    return SchemaResult(
        status="resumed" if backup_existed else "migrated",
        items=_items("recorded"),
    )


def prepare_fresh_schema_initialization(
    seed_root: Path,
    data_root: Path,
    root_descriptor: int | None,
    plan,
) -> str | None:
    """Reserve a genuinely clean initialization before its first seed copy."""

    seeds = _absolute_without_following(Path(seed_root))
    target = _absolute_without_following(Path(data_root))
    try:
        if not _pinned_target_matches(target, root_descriptor):
            return "fresh_schema_target_changed"
        _reconcile_fresh_temporary(target, root_descriptor)
        reservation = target / FRESH_SCHEMA_RESERVATION_NAME
        if _entry_exists_at(reservation, root_descriptor):
            if not _fresh_reservation_valid_at(target, root_descriptor):
                return "invalid_fresh_schema_reservation"
            _reconcile_fresh_seed_temporary(seeds, target, root_descriptor)
            _reconcile_fresh_manifest_temporary(target, root_descriptor)
            if _schema_artifact_issue_pinned(target, root_descriptor) != "fresh_schema_initialization_incomplete":
                return "invalid_fresh_schema_temporaries"
            for item in plan.items:
                if item.status != "existing":
                    continue
                name = item.name
                if _read_validated_seed_bytes(
                    seeds / name,
                    name,
                    require_single_link=True,
                ) != _read_validated_seed_bytes(
                    target / name,
                    name,
                    require_single_link=True,
                ):
                    return "fresh_schema_source_changed"
                descriptor = _open_readonly_no_follow(target / name)
                try:
                    if not _owner_only_regular_descriptor(descriptor):
                        return "fresh_schema_file_unsafe"
                finally:
                    os.close(descriptor)
            return None
        if any(item.status != "initialize" for item in plan.items):
            return None
        if _read_manifest(target)[0] != "legacy" or _schema_artifact_issue(target) is not None:
            return "invalid_schema_artifacts"
        for name in SEED_FILE_NAMES:
            _read_validated_seed_bytes(seeds / name, name, require_single_link=True)
        if not _pinned_target_matches(target, root_descriptor):
            return "fresh_schema_target_changed"
        _publish_raw_missing(
            reservation,
            _fresh_manifest_raw(),
            parent_fd=root_descriptor,
            maximum=MAX_SCHEMA_MANIFEST_BYTES,
        )
        if (
            not _pinned_target_matches(target, root_descriptor)
            or not _fresh_reservation_valid_at(target, root_descriptor)
            or _schema_artifact_issue_pinned(target, root_descriptor)
            != "fresh_schema_initialization_incomplete"
        ):
            return "fresh_schema_reservation_unverified"
    except _BOUNDARY_EXCEPTIONS:
        return "fresh_schema_reservation_failed"
    return None


def _discard_fresh_reservation(target: Path, root_descriptor: int | None) -> None:
    reservation = target / FRESH_SCHEMA_RESERVATION_NAME
    if (
        not _fresh_reservation_valid_at(target, root_descriptor)
        or _schema_artifact_issue_pinned(target, root_descriptor)
        != "fresh_schema_initialization_incomplete"
    ):
        raise OSError("invalid fresh schema reservation")
    if root_descriptor is not None and os.unlink in os.supports_dir_fd:
        os.unlink(FRESH_SCHEMA_RESERVATION_NAME, dir_fd=root_descriptor)
        os.fsync(root_descriptor)
    else:
        reservation.unlink()
    if _entry_exists_at(reservation, root_descriptor):
        raise OSError("fresh schema reservation removal unverified")


def _fresh_completion_valid(target: Path) -> bool:
    manifest_status, manifest = _read_manifest(target)
    if (
        manifest_status != "current"
        or manifest is None
        or manifest.get("origin") != "fresh_seed"
        or _recognized_schema_temporaries(target)
        or any(
            _FRESH_RESERVATION_TEMP_RE.fullmatch(entry.name)
            or _FRESH_SEED_TEMP_RE.fullmatch(entry.name)
            for entry in target.iterdir()
        )
    ):
        return False
    try:
        _load_snapshots(target, private=True)
    except _BOUNDARY_EXCEPTIONS:
        return False
    return _manifest_backup_valid(target, manifest) and _current_artifacts_valid(target, manifest)


def _fresh_completion_valid_pinned(
    seeds: Path,
    target: Path,
    root_descriptor: int | None,
) -> bool:
    try:
        inventory = _pinned_schema_artifact_names(target, root_descriptor)
        if (
            _classify_schema_artifact_names(*inventory)
            != "fresh_schema_initialization_incomplete"
            or not _fresh_reservation_valid_at(target, root_descriptor)
        ):
            return False
        with _pinned_existing_child_directory(
            target,
            root_descriptor,
            "config",
        ) as config_fd:
            manifest_raw, manifest_state = _read_private_artifact_at(
                _manifest_path(target),
                config_fd,
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=1,
            )
            if manifest_raw != _fresh_manifest_raw():
                return False
            expected = _load_snapshots(seeds, private=False)
            if not _snapshots_match(_load_snapshots_at(target, root_descriptor), expected):
                return False
            verified_raw, verified_state = _read_private_artifact_at(
                _manifest_path(target),
                config_fd,
                maximum=MAX_SCHEMA_MANIFEST_BYTES,
                maximum_links=1,
            )
            return (
                verified_raw == manifest_raw
                and verified_state.st_dev == manifest_state.st_dev
                and verified_state.st_ino == manifest_state.st_ino
                and inventory == _pinned_schema_artifact_names(target, root_descriptor)
                and _fresh_reservation_valid_at(target, root_descriptor)
                and _pinned_target_matches(target, root_descriptor)
            )
    except _BOUNDARY_EXCEPTIONS:
        return False


def initialize_fresh_schema_under_lock(
    seed_root: Path,
    data_root: Path,
    root_descriptor: int | None,
) -> str | None:
    """Complete a reserved clean schema while the caller retains the root lock."""

    seeds = _absolute_without_following(Path(seed_root))
    target = _absolute_without_following(Path(data_root))
    try:
        if not _pinned_target_matches(target, root_descriptor):
            return "fresh_schema_target_changed"
        if not _pinned_target_matches(target, root_descriptor):
            return "fresh_schema_target_changed"
        reservation = target / FRESH_SCHEMA_RESERVATION_NAME
        if not _entry_exists_at(reservation, root_descriptor):
            status = _schema_status_pinned(target, root_descriptor)
            return None if status in {"legacy", "current"} else "invalid_schema_manifest"
        if (
            not _fresh_reservation_valid_at(target, root_descriptor)
            or _schema_artifact_issue_pinned(target, root_descriptor)
            != "fresh_schema_initialization_incomplete"
        ):
            return "invalid_fresh_schema_reservation"
        manifest_status, manifest = _read_manifest(target)
        if manifest_status == "current":
            if manifest is None or manifest.get("origin") != "fresh_seed":
                return "invalid_schema_manifest"
        elif manifest_status != "legacy":
            return "invalid_schema_manifest"
        for name in SEED_FILE_NAMES:
            if _read_validated_seed_bytes(
                seeds / name,
                name,
                require_single_link=True,
            ) != _read_validated_seed_bytes(
                target / name,
                name,
                require_single_link=True,
            ):
                return "fresh_schema_source_changed"
            descriptor = _open_readonly_no_follow(target / name)
            try:
                if not _owner_only_regular_descriptor(descriptor):
                    return "fresh_schema_file_unsafe"
            finally:
                os.close(descriptor)
        if not _pinned_target_matches(target, root_descriptor):
            return "fresh_schema_target_changed"
        if manifest_status == "legacy":
            with _guarded_child_directory(target, root_descriptor, "config") as config_fd:
                _publish_raw_missing(
                    _manifest_path(target),
                    _fresh_manifest_raw(),
                    parent_fd=config_fd,
                    maximum=MAX_SCHEMA_MANIFEST_BYTES,
                )
        if not _pinned_target_matches(target, root_descriptor):
            return "fresh_schema_target_changed"
        if not _fresh_completion_valid_pinned(seeds, target, root_descriptor):
            return "fresh_schema_verification_failed"
        _discard_fresh_reservation(target, root_descriptor)
        expected_fresh = _load_snapshots(seeds, private=False)
        if (
            not _pinned_target_matches(target, root_descriptor)
            or _schema_status_pinned(
                target,
                root_descriptor,
                expected_snapshots=expected_fresh,
            )
            != "current"
            or _schema_status_pinned(
                target,
                root_descriptor,
                expected_snapshots=expected_fresh,
            )
            != "current"
            or not _pinned_target_matches(target, root_descriptor)
        ):
            return "fresh_schema_verification_failed"
    except _BOUNDARY_EXCEPTIONS:
        return "fresh_schema_initialization_failed"
    return None


def initialize_fresh_schema(seed_root: Path, data_root: Path) -> str | None:
    """Complete only a clean initialization that reserved version 1 first."""

    target = _absolute_without_following(Path(data_root))
    try:
        with _initialization_lock(target) as root_descriptor:
            return initialize_fresh_schema_under_lock(
                seed_root,
                target,
                root_descriptor,
            )
    except _BOUNDARY_EXCEPTIONS:
        return "fresh_schema_initialization_failed"
