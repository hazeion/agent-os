"""Capability-gated Hermes profile identity synchronization.

Mentat keeps Hermes profiles canonical.  This adapter updates only a versioned,
Mentat-managed block at the top of a profile's ``SOUL.md`` and synchronizes the
profile description that Hermes uses for routing.  It never returns the rest of
the soul document to Mentat or the browser.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Callable


IDENTITY_SCHEMA_VERSION = 1
IDENTITY_TIMEOUT_SECONDS = 20
IDENTITY_ROLE_LIMIT = 500
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
IDENTITY_START_MARKER = "<!-- mentat-profile-identity:v1:start -->"
IDENTITY_END_MARKER = "<!-- mentat-profile-identity:v1:end -->"
IDENTITY_STATUSES = {"missing", "synced", "drifted", "conflict", "unsafe"}
IDENTITY_REQUEST_FIELDS = {"role", "confirmed", "confirmation_id"}


HERMES_PROFILE_IDENTITY_SCRIPT = r'''
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

from hermes_cli import profiles as profiles_module

START = "<!-- mentat-profile-identity:v1:start -->"
END = "<!-- mentat-profile-identity:v1:end -->"
NAME_PREFIX = "Name: "
ROLE_PREFIX = "Role: "
PROFILE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False))


def revision(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_managed(content, profile_id, description):
    start_count = content.count(START)
    end_count = content.count(END)
    base = {
        "schema_version": 1,
        "profile_id": profile_id,
        "revision": revision(content),
        "name": "",
        "role": "",
        "role_description": str(description or "")[:500],
        "error": None,
    }
    if start_count == 0 and end_count == 0:
        return {**base, "status": "missing"}
    if start_count != 1 or end_count != 1:
        return {**base, "status": "conflict", "error": {"code": "managed_block_conflict"}}
    start = content.find(START)
    end = content.find(END, start + len(START))
    if start < 0 or end < start:
        return {**base, "status": "conflict", "error": {"code": "managed_block_conflict"}}
    body = content[start + len(START):end]
    name = ""
    role = ""
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith(NAME_PREFIX):
            name = line[len(NAME_PREFIX):].strip()[:64]
        elif line.startswith(ROLE_PREFIX):
            role = line[len(ROLE_PREFIX):].strip()[:500]
    status_value = "synced" if name == profile_id and role == str(description or "").strip() else "drifted"
    return {**base, "status": status_value, "name": name, "role": role}


def render_block(profile_id, role):
    role_text = role or "No specialized role has been assigned."
    return "\n".join([
        START,
        "# Mentat Managed Profile Identity",
        f"Name: {profile_id}",
        f"Role: {role}",
        "",
        f'You are the Hermes profile named "{profile_id}". {role_text}',
        "This managed identity overrides conflicting name or role statements elsewhere in this document.",
        END,
    ])


def replace_managed(content, block):
    start_count = content.count(START)
    end_count = content.count(END)
    if start_count == 0 and end_count == 0:
        remainder = content.strip()
    elif start_count == 1 and end_count == 1:
        start = content.find(START)
        end = content.find(END, start + len(START))
        if start < 0 or end < start:
            raise ValueError("managed_block_conflict")
        remainder = (content[:start] + content[end + len(END):]).strip()
    else:
        raise ValueError("managed_block_conflict")
    return block + (("\n\n" + remainder) if remainder else "") + "\n"


def atomic_write(path, content, previous_mode=None):
    mode = previous_mode if previous_mode is not None else 0o600
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=".mentat-soul-",
        dir=str(path.parent),
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, stat.S_IMODE(mode))
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


try:
    request = json.load(sys.stdin)
    action = str(request.get("action") or "inspect")
    profile_id = str(request.get("profile_id") or "").strip().lower()
    if profile_id != "default" and not PROFILE_RE.fullmatch(profile_id):
        emit({"schema_version": 1, "status": "unsafe", "error": {"code": "invalid_profile"}})
        raise SystemExit(0)
    if not profiles_module.profile_exists(profile_id):
        emit({"schema_version": 1, "status": "unsafe", "error": {"code": "profile_missing"}})
        raise SystemExit(0)
    profile_dir = profiles_module.get_profile_dir(profile_id)
    soul_path = profile_dir / "SOUL.md"
    if soul_path.is_symlink() or not profile_dir.is_dir():
        emit({"schema_version": 1, "status": "unsafe", "error": {"code": "unsafe_identity_path"}})
        raise SystemExit(0)
    old_exists = soul_path.is_file()
    old_content = soul_path.read_text(encoding="utf-8") if old_exists else ""
    old_mode = soul_path.stat().st_mode if old_exists else None
    old_meta = profiles_module.read_profile_meta(profile_dir)
    current = parse_managed(old_content, profile_id, old_meta.get("description", ""))
    if action == "inspect":
        emit(current)
        raise SystemExit(0)
    if action != "apply":
        emit({"schema_version": 1, "status": "unsafe", "error": {"code": "invalid_action"}})
        raise SystemExit(0)
    if current.get("status") in {"conflict", "unsafe"}:
        emit(current)
        raise SystemExit(0)
    expected_revision = str(request.get("expected_revision") or "")
    if expected_revision != current.get("revision"):
        emit({**current, "error": {"code": "stale_identity"}})
        raise SystemExit(0)
    role = " ".join(str(request.get("role") or "").split())
    if len(role) > 500 or START in role or END in role or "\x00" in role:
        emit({**current, "status": "unsafe", "error": {"code": "invalid_role"}})
        raise SystemExit(0)
    next_content = replace_managed(old_content, render_block(profile_id, role))
    old_meta_exists = (profile_dir / "profile.yaml").is_file()
    try:
        atomic_write(soul_path, next_content, old_mode)
        profiles_module.write_profile_meta(
            profile_dir,
            description=role,
            description_auto=False,
        )
        verified_meta = profiles_module.read_profile_meta(profile_dir)
        verified_content = soul_path.read_text(encoding="utf-8")
        verified = parse_managed(verified_content, profile_id, verified_meta.get("description", ""))
        if verified.get("status") != "synced" or verified.get("name") != profile_id or verified.get("role") != role:
            raise RuntimeError("verification_failed")
        emit(verified)
    except Exception:
        try:
            if old_exists:
                atomic_write(soul_path, old_content, old_mode)
            else:
                soul_path.unlink(missing_ok=True)
            if old_meta_exists:
                profiles_module.write_profile_meta(
                    profile_dir,
                    description=old_meta.get("description", ""),
                    description_auto=old_meta.get("description_auto", False),
                )
            else:
                (profile_dir / "profile.yaml").unlink(missing_ok=True)
        except Exception:
            pass
        emit({**current, "error": {"code": "identity_write_failed"}})
except SystemExit:
    raise
except Exception:
    emit({"schema_version": 1, "status": "unsafe", "error": {"code": "identity_runtime_failed"}})
'''.strip()


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _error(message: str, *, code: str = "invalid_request", status: int = 400):
    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "valid": False,
        "error": {"code": code, "message": message},
    }, status


def _normalize_result(payload, profile_id: str) -> dict:
    if not isinstance(payload, dict) or payload.get("schema_version") != IDENTITY_SCHEMA_VERSION:
        return {
            "schema_version": IDENTITY_SCHEMA_VERSION,
            "profile_id": profile_id,
            "status": "unsafe",
            "revision": "",
            "name": "",
            "role": "",
            "role_description": "",
            "error": {"code": "invalid_runtime_payload"},
        }
    status = payload.get("status") if payload.get("status") in IDENTITY_STATUSES else "unsafe"
    revision = str(payload.get("revision") or "")
    if not re.fullmatch(r"[a-f0-9]{64}", revision):
        revision = ""
    error = payload.get("error") if isinstance(payload.get("error"), dict) else None
    error_code = _text((error or {}).get("code"), 80)
    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "profile_id": profile_id,
        "status": status,
        "revision": revision,
        "name": _text(payload.get("name"), 64),
        "role": _text(payload.get("role"), IDENTITY_ROLE_LIMIT),
        "role_description": _text(payload.get("role_description"), IDENTITY_ROLE_LIMIT),
        "error": {"code": error_code} if error_code else None,
    }


def _runtime_operation(
    runtime_python: str | None,
    hermes_home: str | Path,
    request: dict,
    *,
    cwd: str | Path | None = None,
    runner: Callable = subprocess.run,
    timeout: int = IDENTITY_TIMEOUT_SECONDS,
) -> dict:
    profile_id = _text(request.get("profile_id"), 64).lower()
    if not runtime_python:
        return _normalize_result(
            {"schema_version": 1, "status": "unsafe", "error": {"code": "runtime_unavailable"}},
            profile_id,
        )
    try:
        result = runner(
            [runtime_python, "-c", HERMES_PROFILE_IDENTITY_SCRIPT],
            cwd=str(cwd) if cwd is not None else None,
            env={**os.environ, "HERMES_HOME": str(hermes_home)},
            input=json.dumps(request, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _normalize_result(
            {"schema_version": 1, "status": "unsafe", "error": {"code": "runtime_timeout"}},
            profile_id,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return _normalize_result(
            {"schema_version": 1, "status": "unsafe", "error": {"code": "runtime_failed"}},
            profile_id,
        )
    if result.returncode != 0:
        return _normalize_result(
            {"schema_version": 1, "status": "unsafe", "error": {"code": "runtime_failed"}},
            profile_id,
        )
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        payload = {"schema_version": 1, "status": "unsafe", "error": {"code": "invalid_runtime_payload"}}
    return _normalize_result(payload, profile_id)


def inspect_profile_identity(runtime_python, hermes_home, profile_id, **kwargs) -> dict:
    """Return only the managed identity fields and revision, never SOUL contents."""
    return _runtime_operation(
        runtime_python,
        hermes_home,
        {"action": "inspect", "profile_id": _text(profile_id, 64).lower()},
        **kwargs,
    )


def apply_profile_identity(
    runtime_python,
    hermes_home,
    profile_id,
    role,
    expected_revision,
    **kwargs,
) -> dict:
    """Apply a validated managed identity block through the Hermes runtime."""
    return _runtime_operation(
        runtime_python,
        hermes_home,
        {
            "action": "apply",
            "profile_id": _text(profile_id, 64).lower(),
            "role": _text(role, IDENTITY_ROLE_LIMIT),
            "expected_revision": str(expected_revision or ""),
        },
        **kwargs,
    )


def _profile(discovery: dict, profile_id: str) -> dict | None:
    return next(
        (
            item
            for item in discovery.get("profiles") or []
            if isinstance(item, dict) and _text(item.get("id"), 64).lower() == profile_id
        ),
        None,
    )


def _confirmation_id(normalized: dict, inspection: dict) -> str:
    bound = {
        "normalized": normalized,
        "current": {
            "revision": inspection.get("revision"),
            "status": inspection.get("status"),
            "name": inspection.get("name"),
            "role": inspection.get("role"),
            "role_description": inspection.get("role_description"),
        },
    }
    encoded = json.dumps(bound, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "profile_identity_" + hashlib.sha256(encoded).hexdigest()[:24]


def preview_profile_identity(profile_id, payload, discovery: dict, inspection: dict):
    """Validate and bind an exact profile identity synchronization preview."""
    if not isinstance(payload, dict):
        return _error("Profile identity payload must be a JSON object.")
    unknown = sorted(set(payload) - IDENTITY_REQUEST_FIELDS)
    if unknown:
        return _error(f"Unsupported profile identity fields: {', '.join(unknown)}.")
    normalized_profile_id = _text(profile_id, 64).lower()
    if normalized_profile_id != "default" and not PROFILE_NAME_RE.fullmatch(normalized_profile_id):
        return _error("Invalid Hermes profile id.")
    if not isinstance(discovery, dict) or discovery.get("status") != "available":
        return _error("Hermes profile discovery is unavailable.", code="profile_discovery_unavailable", status=503)
    capabilities = discovery.get("capabilities") if isinstance(discovery.get("capabilities"), dict) else {}
    if not capabilities.get("profiles.identity.write"):
        return _error(
            "This Hermes runtime does not expose the profile identity adapter requirements.",
            code="capability_unavailable",
            status=503,
        )
    profile = _profile(discovery, normalized_profile_id)
    if profile is None:
        return _error(f"Hermes profile '{normalized_profile_id}' was not found.", code="profile_missing", status=404)
    if not isinstance(inspection, dict) or inspection.get("profile_id") != normalized_profile_id:
        return _error("Profile identity inspection is unavailable.", code="identity_inspection_unavailable", status=503)
    if inspection.get("status") in {"conflict", "unsafe"} or not inspection.get("revision"):
        return _error(
            "The profile identity block is malformed or unsafe and requires manual Hermes review.",
            code="identity_conflict",
            status=409,
        )
    raw_role = str(payload.get("role") or "")
    role = _text(raw_role, IDENTITY_ROLE_LIMIT)
    if len(" ".join(raw_role.split())) > IDENTITY_ROLE_LIMIT:
        return _error(f"Profile role must be {IDENTITY_ROLE_LIMIT} characters or fewer.")
    if IDENTITY_START_MARKER in role or IDENTITY_END_MARKER in role or "\x00" in raw_role:
        return _error("Profile role contains reserved identity markup.")
    normalized = {
        "profile_id": normalized_profile_id,
        "name": normalized_profile_id,
        "role": role,
    }
    current_role = _text(inspection.get("role_description"), IDENTITY_ROLE_LIMIT)
    effects = [
        f"Set the runtime identity name for Hermes profile '{normalized_profile_id}'.",
        "Create or replace only Mentat's versioned identity block at the top of SOUL.md.",
        "Synchronize the Hermes profile description used for task routing.",
        "Preserve all SOUL.md content outside the managed identity block.",
    ]
    warnings = []
    if inspection.get("status") == "missing":
        warnings.append("This profile does not yet have a Mentat-managed identity block; confirmation will add one.")
    elif inspection.get("status") == "drifted":
        warnings.append("The managed runtime identity and Hermes routing description have drifted; confirmation will synchronize them.")
    return {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "valid": True,
        "operation": "profiles.identity.write",
        "requires_confirmation": True,
        "confirmation_id": _confirmation_id(normalized, inspection),
        "normalized": normalized,
        "current": {
            "status": inspection.get("status"),
            "name": _text(inspection.get("name"), 64),
            "role": current_role,
        },
        "effects": effects,
        "warnings": warnings,
        "error": None,
    }, 200
