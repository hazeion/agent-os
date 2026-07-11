"""Validated preview and fixed-runtime execution for Hermes profile deletion."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable


PROFILE_DELETION_SCHEMA_VERSION = 1
PROFILE_DELETION_TIMEOUT_SECONDS = 60
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PROFILE_DELETION_FIELDS = {"confirmed", "confirmation_id"}


HERMES_PROFILE_DELETION_SCRIPT = r"""
import io
import json
import sys
from contextlib import redirect_stdout

from hermes_cli import profiles as profiles_module

name = sys.argv[1]
if not callable(getattr(profiles_module, "delete_profile", None)):
    print(json.dumps({"schema_version": 1, "ok": False, "error_code": "capability_unavailable"}))
    raise SystemExit(0)

try:
    with redirect_stdout(io.StringIO()):
        profiles_module.delete_profile(name, yes=True)
except FileNotFoundError:
    print(json.dumps({"schema_version": 1, "ok": False, "error_code": "profile_missing"}))
except ValueError:
    print(json.dumps({"schema_version": 1, "ok": False, "error_code": "invalid_profile"}))
except Exception:
    print(json.dumps({"schema_version": 1, "ok": False, "error_code": "runtime_failed"}))
else:
    print(json.dumps({"schema_version": 1, "ok": True}))
""".strip()


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _error(message: str, *, code: str = "invalid_request", status: int = 400):
    return {
        "schema_version": PROFILE_DELETION_SCHEMA_VERSION,
        "valid": False,
        "error": {"code": code, "message": message},
    }, status


def _profile(discovery: dict, profile_id: str) -> dict | None:
    return next(
        (
            item for item in discovery.get("profiles") or []
            if isinstance(item, dict) and _text(item.get("id"), 80).lower() == profile_id
        ),
        None,
    )


def _confirmation_id(normalized: dict) -> str:
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "profile_delete_" + hashlib.sha256(encoded).hexdigest()[:20]


def preview_profile_deletion(profile_id, payload, discovery: dict):
    """Validate deletion and return a profile-bound confirmation contract."""
    if not isinstance(payload, dict):
        return _error("Profile deletion payload must be a JSON object.")
    unknown = sorted(set(payload) - PROFILE_DELETION_FIELDS)
    if unknown:
        return _error(f"Unsupported profile deletion fields: {', '.join(unknown)}.")
    if not isinstance(discovery, dict) or discovery.get("status") != "available":
        return _error(
            "Hermes profile discovery is unavailable.",
            code="profile_discovery_unavailable",
            status=503,
        )
    capabilities = discovery.get("capabilities") if isinstance(discovery.get("capabilities"), dict) else {}
    if not capabilities.get("profiles.delete"):
        return _error(
            "This Hermes runtime does not expose profile deletion.",
            code="capability_unavailable",
            status=503,
        )

    name = _text(profile_id, 80).lower()
    if not PROFILE_NAME_RE.fullmatch(name):
        return _error("Profile name must match [a-z0-9][a-z0-9_-]{0,63}.")
    profile = _profile(discovery, name)
    if profile is None:
        return _error(f"Hermes profile '{name}' does not exist.", code="profile_missing", status=404)
    active_profile = _text(discovery.get("active_profile"), 80).lower()
    if profile.get("is_default") or name == "default":
        return _error("The default Hermes profile cannot be deleted.", code="default_profile", status=409)
    if name == active_profile:
        return _error("The active Hermes profile cannot be deleted.", code="active_profile", status=409)

    normalized = {
        "operation": "profiles.delete",
        "profile_id": name,
        "active_profile": active_profile,
        "is_default": bool(profile.get("is_default")),
    }
    return {
        "schema_version": PROFILE_DELETION_SCHEMA_VERSION,
        "valid": True,
        "operation": "profiles.delete",
        "requires_confirmation": True,
        "confirmation_id": _confirmation_id(normalized),
        "normalized": normalized,
        "profile": {
            "id": name,
            "name": _text(profile.get("name") or name, 80),
            "description": _text(profile.get("description"), 500),
        },
        "effects": [
            f"Permanently delete Hermes profile '{name}'.",
            "Hermes will remove this profile's configuration, credentials, memories, sessions, skills, cron jobs, and gateway service.",
            "Mentat will refresh Managed Agents after Hermes confirms deletion.",
        ],
        "warnings": ["This cannot be undone by Mentat."],
        "error": None,
    }, 200


def delete_hermes_profile(
    runtime_python: str | None,
    hermes_home: str | Path,
    profile_id: str,
    *,
    cwd: str | Path | None = None,
    runner: Callable = subprocess.run,
    timeout: int = PROFILE_DELETION_TIMEOUT_SECONDS,
) -> dict:
    """Delete through Hermes' supported API using fixed, shell-free argv."""
    if not runtime_python:
        return {"status": "failed", "error_code": "runtime_unavailable"}
    try:
        result = runner(
            [runtime_python, "-c", HERMES_PROFILE_DELETION_SCRIPT, profile_id],
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
        return {"status": "failed", "error_code": "runtime_timeout", "partial": True}
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return {"status": "failed", "error_code": "runtime_failed"}
    if result.returncode != 0:
        return {"status": "failed", "error_code": "runtime_failed"}
    try:
        result_payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        return {"status": "failed", "error_code": "invalid_payload"}
    if not isinstance(result_payload, dict) or result_payload.get("schema_version") != PROFILE_DELETION_SCHEMA_VERSION:
        return {"status": "failed", "error_code": "invalid_payload"}
    if result_payload.get("ok") is not True:
        code = _text(result_payload.get("error_code"), 80) or "runtime_failed"
        return {"status": "failed", "error_code": code}
    return {"status": "deleted", "profile_id": profile_id}
