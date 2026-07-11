"""Capability-gated Hermes profile discovery for Mentat.

Hermes profile reads run inside the Hermes-managed Python runtime. This keeps
Mentat independent from the user's system Python environment and contains the
use of Hermes' Python API behind one versioned, fail-closed adapter.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable


PROFILE_SCHEMA_VERSION = 1
PROFILE_DISCOVERY_TIMEOUT_SECONDS = 20
PROFILE_LIMIT = 100
CAPABILITY_KEYS = (
    "profiles.read",
    "profiles.create",
    "profiles.describe",
    "profiles.rename",
    "profiles.delete",
)


HERMES_PROFILE_DISCOVERY_SCRIPT = r"""
import json

from hermes_cli import __release_date__, __version__
from hermes_cli import profiles as profiles_module

try:
    from hermes_cli.config import load_config
    from hermes_cli.skills_config import get_disabled_skills
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from tools.skills_sync import _read_manifest
    builtin_skills = set(_read_manifest())
except Exception:
    builtin_skills = None


def enabled_builtin_skill_count(profile_name):
    if builtin_skills is None:
        return None
    profile_dir = profiles_module.get_profile_dir(profile_name)
    token = set_hermes_home_override(str(profile_dir))
    try:
        config = load_config()
        disabled = set(get_disabled_skills(config))
        return len(builtin_skills - disabled)
    except Exception:
        return None
    finally:
        reset_hermes_home_override(token)

rows = profiles_module.list_profiles()
capabilities = {
    "profiles.read": callable(getattr(profiles_module, "list_profiles", None)),
    "profiles.create": callable(getattr(profiles_module, "create_profile", None)),
    "profiles.describe": callable(getattr(profiles_module, "write_profile_meta", None)),
    "profiles.rename": callable(getattr(profiles_module, "rename_profile", None)),
    "profiles.delete": callable(getattr(profiles_module, "delete_profile", None)),
}
payload = {
    "schema_version": 1,
    "hermes": {
        "version": str(__version__),
        "release_date": str(__release_date__),
    },
    "active_profile": str(profiles_module.get_active_profile()),
    "capabilities": capabilities,
    "profiles": [
        {
            "id": str(row.name),
            "name": str(row.name),
            "is_default": bool(row.is_default),
            "description": str(row.description or ""),
            "description_auto": bool(row.description_auto),
            "provider": str(row.provider or ""),
            "model": str(row.model or ""),
            "skill_count": int(row.skill_count or 0),
            "enabled_builtin_skill_count": enabled_builtin_skill_count(row.name),
            "gateway_running": bool(row.gateway_running),
            "alias": str(row.alias_name or ""),
            "distribution": {
                "name": str(row.distribution_name or ""),
                "version": str(row.distribution_version or ""),
                "source": str(row.distribution_source or ""),
            },
        }
        for row in rows
    ],
}
print(json.dumps(payload))
""".strip()


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _error_payload(code: str, message: str) -> dict:
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "status": "unavailable",
        "source": "hermes_runtime",
        "read_only": True,
        "hermes": {"version": "", "release_date": ""},
        "active_profile": "",
        "capabilities": {key: False for key in CAPABILITY_KEYS},
        "profiles": [],
        "error": {"code": code, "message": _text(message, 2_000)},
    }


def _normalize_distribution(value) -> dict:
    value = value if isinstance(value, dict) else {}
    return {
        "name": _text(value.get("name"), 120),
        "version": _text(value.get("version"), 80),
        "source": _text(value.get("source"), 240),
    }


def _normalize_profile(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    profile_id = _text(value.get("id") or value.get("name"), 80).lower()
    if not profile_id:
        return None
    try:
        skill_count = max(0, int(value.get("skill_count") or 0))
    except (TypeError, ValueError):
        skill_count = 0
    try:
        enabled_builtin_skill_count = (
            max(0, int(value.get("enabled_builtin_skill_count")))
            if value.get("enabled_builtin_skill_count") is not None
            else None
        )
    except (TypeError, ValueError):
        enabled_builtin_skill_count = None
    return {
        "id": profile_id,
        "name": _text(value.get("name") or profile_id, 80),
        "is_default": bool(value.get("is_default")),
        "description": _text(value.get("description"), 500),
        "description_auto": bool(value.get("description_auto")),
        "provider": _text(value.get("provider"), 120),
        "model": _text(value.get("model"), 160),
        "skill_count": skill_count,
        "enabled_builtin_skill_count": enabled_builtin_skill_count,
        "gateway_running": bool(value.get("gateway_running")),
        "alias": _text(value.get("alias"), 80),
        "distribution": _normalize_distribution(value.get("distribution")),
    }


def normalize_profile_payload(payload) -> dict:
    """Validate and normalize the helper response into Mentat's public schema."""
    if not isinstance(payload, dict):
        return _error_payload("invalid_payload", "Hermes profile discovery did not return an object.")
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        return _error_payload("unsupported_schema", "Hermes profile discovery returned an unsupported schema.")

    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    normalized_capabilities = {key: bool(capabilities.get(key)) for key in CAPABILITY_KEYS}
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list):
        return _error_payload("invalid_payload", "Hermes profile discovery returned an invalid profile list.")

    profiles = []
    seen = set()
    for value in raw_profiles[:PROFILE_LIMIT]:
        profile = _normalize_profile(value)
        if profile is None or profile["id"] in seen:
            continue
        seen.add(profile["id"])
        profiles.append(profile)

    hermes = payload.get("hermes") if isinstance(payload.get("hermes"), dict) else {}
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "status": "available" if normalized_capabilities["profiles.read"] else "unsupported",
        "source": "hermes_runtime",
        "read_only": True,
        "hermes": {
            "version": _text(hermes.get("version"), 80),
            "release_date": _text(hermes.get("release_date"), 80),
        },
        "active_profile": _text(payload.get("active_profile"), 80).lower(),
        "capabilities": normalized_capabilities,
        "profiles": profiles,
        "error": None,
    }


def discover_hermes_profiles(
    runtime_python: str | None,
    hermes_home: str | Path,
    *,
    cwd: str | Path | None = None,
    runner: Callable = subprocess.run,
    timeout: int = PROFILE_DISCOVERY_TIMEOUT_SECONDS,
) -> dict:
    """Read Hermes profiles through the Hermes runtime and fail closed."""
    if not runtime_python:
        return _error_payload("runtime_unavailable", "Hermes runtime was not found for profile discovery.")

    try:
        result = runner(
            [runtime_python, "-c", HERMES_PROFILE_DISCOVERY_SCRIPT],
            cwd=str(cwd) if cwd is not None else None,
            env={**os.environ, "HERMES_HOME": str(hermes_home)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _error_payload("runtime_timeout", "Hermes profile discovery timed out.")
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        return _error_payload("runtime_failed", str(exc))

    if result.returncode != 0:
        return _error_payload(
            "runtime_failed",
            f"Hermes profile discovery exited with status {result.returncode}.",
        )
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        return _error_payload("invalid_payload", "Hermes profile discovery returned invalid JSON.")
    return normalize_profile_payload(payload)
