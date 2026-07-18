"""Explicit source-preserving migration of legacy Console runtime state."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

from json_store import write_json_atomic
from private_console_unit import (
    MAX_PRIVATE_UNIT_BYTES,
    PrivateConsoleUnit,
    PrivateConsoleUnitError,
    capture_private_console_unit,
    materialize_private_console_unit,
    private_console_unit_digest,
    remove_private_console_tree,
    validate_private_console_stage_inventory,
)
from private_state import (
    console_root,
    ensure_private_root,
    legacy_private_entries,
    migration_receipt_path,
    migration_reservation_path,
    mentat_server_active,
    private_state_lock,
)


TOKEN_RE = re.compile(r"[0-9a-f]{64}\Z")
PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class PrivateMigrationPreview:
    status: str
    confirmation_token: str | None = None
    run_count: int = 0
    blob_count: int = 0
    issues: tuple[str, ...] = ()
    _unit: PrivateConsoleUnit | None = None
    _source_binding: str | None = None

    def public_summary(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": self.status,
            "items": [
                {
                    "name": "private_console",
                    "classification": "durable_private_consistency_unit",
                    "run_count": self.run_count,
                    "blob_count": self.blob_count,
                    "action": "migrate" if self.status in {"ready", "resume_required"} else "unchanged",
                }
            ] if self.status not in {"not_required", "blocked"} else [],
            "issues": list(self.issues),
        }
        if self.confirmation_token:
            result["confirmation_token"] = self.confirmation_token
        return result


@dataclass(frozen=True)
class PrivateMigrationResult:
    status: str
    run_count: int = 0
    blob_count: int = 0
    issues: tuple[str, ...] = ()

    def public_summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "items": ([{
                "name": "private_console",
                "classification": "durable_private_consistency_unit",
                "run_count": self.run_count,
                "blob_count": self.blob_count,
                "action": "migrated" if self.status in {"migrated", "resumed"} else "unchanged",
            }] if self.status not in {"blocked", "not_required"} else []),
            "issues": list(self.issues),
        }


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def _token(unit: PrivateConsoleUnit, source_binding: str) -> str:
    return hashlib.sha256(_canonical({
        "protocol_version": PROTOCOL_VERSION,
        "operation": "migrate_private_console",
        "source": private_console_unit_digest(unit),
        "source_binding": source_binding,
        "run_count": unit.run_count,
        "blob_count": len(unit.blobs),
    })).hexdigest()


def _read_control(path: Path) -> dict[str, Any] | None:
    if not os.path.lexists(os.fspath(path)):
        return None
    if path.is_symlink() or not path.is_file():
        raise OSError("private_migration_control_invalid")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OSError("private_migration_control_invalid")
    return payload


def _control_document(token: str, unit: PrivateConsoleUnit, source_binding: str) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "confirmation_token": token,
        "unit_sha256": private_console_unit_digest(unit),
        "source_binding": source_binding,
        "run_count": unit.run_count,
        "blob_count": len(unit.blobs),
    }


def _legacy_source_binding(data_root: Path) -> str:
    runtime = Path(data_root) / "runtime"
    paths = [runtime / "agent-console-runs.json"]
    blob_root = runtime / "blobs" / "sha256"
    if os.path.lexists(os.fspath(blob_root)):
        if blob_root.is_symlink() or not blob_root.is_dir():
            raise OSError("private_migration_source_invalid")
        for current, directories, files in os.walk(blob_root, followlinks=False):
            current_path = Path(current)
            for name in directories:
                if (current_path / name).is_symlink():
                    raise OSError("private_migration_source_invalid")
            paths.extend(current_path / name for name in files)
    evidence: list[dict[str, Any]] = []
    total = 0
    for path in sorted(paths, key=lambda item: os.fspath(item.relative_to(runtime))):
        if not os.path.lexists(os.fspath(path)):
            continue
        if path.is_symlink():
            raise OSError("private_migration_source_invalid")
        lexical = os.lstat(path)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(lexical.st_mode) or (
            reparse_flag and getattr(lexical, "st_file_attributes", 0) & reparse_flag
        ):
            raise OSError("private_migration_source_invalid")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or (lexical.st_dev, lexical.st_ino) != (details.st_dev, details.st_ino)
            ):
                raise OSError("private_migration_source_invalid")
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(descriptor, 64 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                total += len(chunk)
                if total > MAX_PRIVATE_UNIT_BYTES:
                    raise OSError("private_migration_source_too_large")
            after = os.fstat(descriptor)
            if (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
            ) or size != details.st_size:
                raise OSError("private_migration_source_changed")
            evidence.append({
                "name": os.fspath(path.relative_to(runtime)).replace(os.sep, "/"),
                "size": size,
                "sha256": digest.hexdigest(),
                "device": int(details.st_dev),
                "inode": int(details.st_ino),
                "mtime_ns": int(details.st_mtime_ns),
            })
        finally:
            os.close(descriptor)
    return hashlib.sha256(_canonical(evidence)).hexdigest()


def preview_private_console_migration(data_root: Path) -> PrivateMigrationPreview:
    root = Path(data_root)
    try:
        entries = legacy_private_entries(root)
        if not entries:
            return PrivateMigrationPreview(status="not_required")
        if mentat_server_active(root):
            return PrivateMigrationPreview(status="blocked", issues=("private_migration_server_active",))
        legacy_database = root / "runtime" / "mentat.sqlite3"
        legacy_blobs = root / "runtime" / "blobs" / "sha256"
        if (
            any(os.path.lexists(os.fspath(Path(f"{legacy_database}{suffix}"))) for suffix in ("-wal", "-shm"))
            and not os.path.lexists(os.fspath(legacy_database))
        ) or (
            os.path.lexists(os.fspath(legacy_blobs))
            and not os.path.lexists(os.fspath(legacy_database))
        ):
            return PrivateMigrationPreview(status="blocked", issues=("private_migration_source_invalid",))
        unit = capture_private_console_unit(
            root,
            source_console=root / "runtime",
            copy_sqlite_source=True,
        )
        source_binding = _legacy_source_binding(root)
        token = _token(unit, source_binding)
        expected = _control_document(token, unit, source_binding)
        receipt = _read_control(migration_receipt_path(root))
        reservation = _read_control(migration_reservation_path(root))
        destination = console_root(root)
        destination_present = os.path.lexists(os.fspath(destination))
        if receipt is not None:
            if receipt != expected or not destination_present:
                return PrivateMigrationPreview(status="blocked", issues=("private_migration_receipt_invalid",))
            migrated = capture_private_console_unit(root)
            if reservation is not None:
                if reservation != receipt:
                    return PrivateMigrationPreview(status="blocked", issues=("private_migration_reservation_invalid",))
                if private_console_unit_digest(migrated) != private_console_unit_digest(unit):
                    return PrivateMigrationPreview(status="blocked", issues=("private_migration_destination_changed",))
                return PrivateMigrationPreview(
                    status="resume_required",
                    confirmation_token=token,
                    run_count=migrated.run_count,
                    blob_count=len(migrated.blobs),
                    _unit=unit,
                    _source_binding=source_binding,
                )
            return PrivateMigrationPreview(
                status="already_migrated",
                run_count=migrated.run_count,
                blob_count=len(migrated.blobs),
            )
        if reservation is not None:
            if reservation != expected:
                return PrivateMigrationPreview(status="blocked", issues=("private_migration_reservation_invalid",))
            if destination_present:
                migrated = capture_private_console_unit(root)
                if private_console_unit_digest(migrated) != private_console_unit_digest(unit):
                    return PrivateMigrationPreview(status="blocked", issues=("private_migration_destination_changed",))
            return PrivateMigrationPreview(status="resume_required", confirmation_token=token, run_count=unit.run_count, blob_count=len(unit.blobs), _unit=unit, _source_binding=source_binding)
        if destination_present:
            return PrivateMigrationPreview(status="blocked", issues=("private_migration_destination_conflict",))
        return PrivateMigrationPreview(status="ready", confirmation_token=token, run_count=unit.run_count, blob_count=len(unit.blobs), _unit=unit, _source_binding=source_binding)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return PrivateMigrationPreview(status="blocked", issues=("private_migration_invalid",))


def migrate_private_console(data_root: Path, *, confirmation_token: str) -> PrivateMigrationResult:
    initial = preview_private_console_migration(data_root)
    if initial.status not in {"ready", "resume_required"} or initial.confirmation_token != confirmation_token:
        return PrivateMigrationResult(status="blocked", issues=("private_migration_confirmation_invalid",))
    root = Path(data_root)
    unit = initial._unit
    assert unit is not None
    source_binding = initial._source_binding
    assert source_binding is not None
    token = _token(unit, source_binding)
    control = _control_document(token, unit, source_binding)
    stage = root / "private" / f".console-migration-{token[:24]}"
    try:
        with private_state_lock(root, allow_control=True):
            current = preview_private_console_migration(root)
            if current.status not in {"ready", "resume_required"} or current.confirmation_token != token:
                return PrivateMigrationResult(status="blocked", issues=("private_migration_changed",))
            if mentat_server_active(root):
                return PrivateMigrationResult(status="blocked", issues=("private_migration_server_active",))
            ensure_private_root(root)
            reservation = migration_reservation_path(root)
            reservation.parent.mkdir(mode=0o700, exist_ok=True)
            if os.name == "posix":
                reservation.parent.chmod(0o700)
            if not reservation.exists():
                write_json_atomic(reservation, control, mode=0o600)
            destination = console_root(root)
            if not destination.exists():
                rebuild_stage = False
                if stage.exists():
                    try:
                        validate_private_console_stage_inventory(root, stage, unit)
                        staged = capture_private_console_unit(root, source_console=stage)
                        rebuild_stage = (
                            private_console_unit_digest(staged)
                            != private_console_unit_digest(unit)
                        )
                    except PrivateConsoleUnitError as exc:
                        if str(exc) != "private_stage_incomplete":
                            raise
                        rebuild_stage = True
                    except (ValueError, TypeError):
                        rebuild_stage = True
                if rebuild_stage:
                    remove_private_console_tree(root, stage)
                if not stage.exists():
                    materialize_private_console_unit(root, unit, stage)
                validate_private_console_stage_inventory(root, stage, unit)
                staged = capture_private_console_unit(root, source_console=stage)
                if private_console_unit_digest(staged) != private_console_unit_digest(unit):
                    raise OSError("private migration stage invalid")
                os.rename(stage, destination)
                try:
                    validate_private_console_stage_inventory(
                        root, destination, unit, allow_canonical=True
                    )
                except Exception:
                    if (
                        os.path.lexists(os.fspath(destination))
                        and not os.path.lexists(os.fspath(stage))
                    ):
                        os.rename(destination, stage)
                    raise
            migrated = capture_private_console_unit(root)
            validate_private_console_stage_inventory(
                root, destination, migrated, allow_canonical=True
            )
            if private_console_unit_digest(migrated) != private_console_unit_digest(unit):
                raise OSError("private migration verification failed")
            receipt = migration_receipt_path(root)
            if not receipt.exists():
                write_json_atomic(receipt, control, mode=0o600)
            if _read_control(receipt) != control:
                raise OSError("private migration receipt invalid")
            reservation.unlink()
            if stage.exists():
                remove_private_console_tree(root, stage)
        return PrivateMigrationResult(
            status="resumed" if initial.status == "resume_required" else "migrated",
            run_count=unit.run_count,
            blob_count=len(unit.blobs),
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return PrivateMigrationResult(status="partial_failure", run_count=unit.run_count, blob_count=len(unit.blobs), issues=("private_migration_failed",))
