"""Build a small, redacted, user-initiated Mentat diagnostics bundle."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import platform
import re
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


DIAGNOSTICS_SCHEMA_VERSION = 1
MAX_DIAGNOSTICS_BYTES = 128 * 1024
MAX_DIAGNOSTICS_ENTRY_BYTES = 16 * 1024
MAX_DIAGNOSTICS_UNCOMPRESSED_BYTES = 64 * 1024
SAFE_HEALTH_KEYS = frozenset(
    {
        "calendar",
        "config",
        "cron",
        "host_resources",
        "remote_hermes",
        "state_db",
    }
)
SAFE_STATUSES = frozenset({"healthy", "degraded", "error", "unavailable"})
STATUS_RANK = {"healthy": 0, "unavailable": 1, "degraded": 2, "error": 3}


def _safe_status(value: object) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if candidate in SAFE_STATUSES else "unavailable"


def _safe_platform(value: object) -> str:
    candidate = str(value or "").strip().lower()
    return {
        "darwin": "macos",
        "windows": "windows",
        "linux": "linux",
    }.get(candidate, "other")


def _safe_architecture(value: object) -> str:
    candidate = str(value or "").strip().lower()
    return {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(candidate, "other")


def _safe_python_version(value: object) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
    return ".".join(match.groups()) if match else "unknown"


def _safe_product_version(value: object, *, display: bool = False) -> str:
    pattern = r"v\d+\.\d+\.\d+(?:-beta\.\d+)?" if display else r"\d+\.\d+\.\d+(?:[abrc]\d+)?"
    candidate = str(value or "").strip()
    return candidate if re.fullmatch(pattern, candidate) else "unknown"


def _safe_timestamp(value: datetime | None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def redact_health_payload(payload: dict | None) -> dict:
    """Project a health response into the fixed diagnostics-safe shape."""
    source = payload if isinstance(payload, dict) else {}
    by_key: dict[str, str] = {}
    for item in source.get("subsystems") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key not in SAFE_HEALTH_KEYS:
            continue
        status = _safe_status(item.get("status"))
        previous = by_key.get(key)
        if previous is None or STATUS_RANK[status] > STATUS_RANK[previous]:
            by_key[key] = status
    items = [{"key": key, "status": by_key[key]} for key in sorted(by_key)]
    return {
        "overall": _safe_status(source.get("overall", source.get("status"))),
        "subsystems": items,
    }


def build_diagnostics_bundle(
    *,
    version: str,
    display_version: str,
    health: dict | None,
    generated_at: datetime | None = None,
    platform_name: str | None = None,
    architecture: str | None = None,
    python_version: str | None = None,
    packaged: bool | None = None,
) -> bytes:
    """Return an in-memory ZIP containing only fixed, allowlisted metadata."""

    entries = {
        "manifest.json": {
            "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
            "product": "Mentat",
            "version": _safe_product_version(version),
            "display_version": _safe_product_version(display_version, display=True),
            "generated_at": _safe_timestamp(generated_at),
            "files": ["environment.json", "health.json", "privacy.json"],
        },
        "environment.json": {
            "platform": _safe_platform(platform_name if platform_name is not None else platform.system()),
            "architecture": _safe_architecture(architecture if architecture is not None else platform.machine()),
            "python": _safe_python_version(python_version if python_version is not None else platform.python_version()),
            "install_type": "packaged" if (getattr(sys, "frozen", False) if packaged is None else packaged) else "python",
        },
        "health.json": redact_health_payload(health),
        "privacy.json": {
            "telemetry": "off",
            "server_boundary": "loopback_only",
            "calendar": "read_only",
            "obsidian": "read_only",
            "contents": "redacted_allowlist_only",
        },
    }

    encoded_entries = {
        name: (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
        for name, payload in entries.items()
    }
    if any(len(content) > MAX_DIAGNOSTICS_ENTRY_BYTES for content in encoded_entries.values()):
        raise ValueError("diagnostics entry exceeded its fixed size limit")
    if sum(map(len, encoded_entries.values())) > MAX_DIAGNOSTICS_UNCOMPRESSED_BYTES:
        raise ValueError("diagnostics bundle exceeded its uncompressed size limit")

    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in encoded_entries.items():
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100600 & 0xFFFF) << 16
            archive.writestr(info, content, compresslevel=9)
    result = output.getvalue()
    if len(result) > MAX_DIAGNOSTICS_BYTES:
        raise ValueError("diagnostics bundle exceeded its fixed size limit")
    return result
