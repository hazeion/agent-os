"""Capability-gated Hermes built-in skill discovery and profile selection."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable


SKILL_SCHEMA_VERSION = 1
SKILL_DISCOVERY_TIMEOUT_SECONDS = 20
SKILL_SELECTION_TIMEOUT_SECONDS = 30


HERMES_SKILL_CATALOG_SCRIPT = r"""
import json

from hermes_cli import __version__
from tools.skills_sync import _read_manifest
from tools.skills_tool import _find_all_skills

builtin = set(_read_manifest())
rows = []
for skill in _find_all_skills(skip_disabled=True):
    name = str(skill.get("name") or "").strip()
    if not name or name not in builtin:
        continue
    rows.append({
        "id": name,
        "name": name,
        "category": str(skill.get("category") or "uncategorized"),
        "description": str(skill.get("description") or ""),
    })
print(json.dumps({
    "schema_version": 1,
    "hermes_version": str(__version__),
    "capabilities": {
        "skills.catalog.read": True,
        "skills.selection.write": True,
    },
    "skills": sorted(rows, key=lambda row: (row["category"], row["name"])),
}))
""".strip()


HERMES_SKILL_SELECTION_SCRIPT = r"""
import json
import sys

from hermes_cli import profiles as profiles_module
from hermes_cli.config import load_config
from hermes_cli.skills_config import get_disabled_skills, save_disabled_skills
from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools.skills_sync import _read_manifest

profile_name = profiles_module.normalize_profile_name(sys.argv[1])
profiles_module.validate_profile_name(profile_name)
profile_dir = profiles_module.get_profile_dir(profile_name)
if not profile_dir.is_dir():
    raise FileNotFoundError("profile does not exist")

enabled = set(json.loads(sys.argv[2]))
builtin = set(_read_manifest())
unknown = sorted(enabled - builtin)
if unknown:
    raise ValueError("unknown built-in skills")

token = set_hermes_home_override(str(profile_dir))
try:
    config = load_config()
    disabled = get_disabled_skills(config)
    disabled = (disabled - builtin) | (builtin - enabled)
    save_disabled_skills(config, disabled)
finally:
    reset_hermes_home_override(token)

print(json.dumps({
    "schema_version": 1,
    "profile_id": profile_name,
    "enabled_builtin_skills": sorted(enabled),
    "disabled_builtin_skills": sorted(builtin - enabled),
}))
""".strip()


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _error_payload(code: str, message: str) -> dict:
    return {
        "schema_version": SKILL_SCHEMA_VERSION,
        "status": "unavailable",
        "source": "hermes_runtime",
        "capabilities": {
            "skills.catalog.read": False,
            "skills.selection.write": False,
        },
        "skills": [],
        "error": {"code": code, "message": _text(message, 1_000)},
    }


def normalize_skill_catalog(payload) -> dict:
    if not isinstance(payload, dict) or payload.get("schema_version") != SKILL_SCHEMA_VERSION:
        return _error_payload("invalid_payload", "Hermes returned an unsupported skill catalog.")
    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, list):
        return _error_payload("invalid_payload", "Hermes returned an invalid skill list.")
    skills = []
    seen = set()
    for value in raw_skills[:500]:
        if not isinstance(value, dict):
            continue
        skill_id = _text(value.get("id") or value.get("name"), 120)
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        skills.append({
            "id": skill_id,
            "name": _text(value.get("name") or skill_id, 120),
            "category": _text(value.get("category") or "uncategorized", 120),
            "description": _text(value.get("description"), 500),
            "source": "builtin",
        })
    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    return {
        "schema_version": SKILL_SCHEMA_VERSION,
        "status": "available" if capabilities.get("skills.catalog.read") else "unsupported",
        "source": "hermes_runtime",
        "hermes_version": _text(payload.get("hermes_version"), 80),
        "capabilities": {
            "skills.catalog.read": bool(capabilities.get("skills.catalog.read")),
            "skills.selection.write": bool(capabilities.get("skills.selection.write")),
        },
        "skills": skills,
        "error": None,
    }


def discover_builtin_skills(
    runtime_python: str | None,
    hermes_home: str | Path,
    *,
    cwd: str | Path | None = None,
    runner: Callable = subprocess.run,
    timeout: int = SKILL_DISCOVERY_TIMEOUT_SECONDS,
) -> dict:
    if not runtime_python:
        return _error_payload("runtime_unavailable", "Hermes runtime was not found for skill discovery.")
    try:
        result = runner(
            [runtime_python, "-c", HERMES_SKILL_CATALOG_SCRIPT],
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
        return _error_payload("runtime_timeout", "Hermes skill discovery timed out.")
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return _error_payload("runtime_failed", "Hermes skill discovery could not be started.")
    if result.returncode != 0:
        return _error_payload("runtime_failed", f"Hermes skill discovery exited with status {result.returncode}.")
    try:
        return normalize_skill_catalog(json.loads(result.stdout))
    except (TypeError, json.JSONDecodeError):
        return _error_payload("invalid_payload", "Hermes skill discovery returned invalid JSON.")


def apply_builtin_skill_selection(
    runtime_python: str | None,
    hermes_home: str | Path,
    profile_id: str,
    enabled_skill_ids: list[str],
    *,
    cwd: str | Path | None = None,
    runner: Callable = subprocess.run,
    timeout: int = SKILL_SELECTION_TIMEOUT_SECONDS,
) -> dict:
    if not runtime_python:
        return _error_payload("runtime_unavailable", "Hermes runtime was not found for skill selection.")
    try:
        result = runner(
            [
                runtime_python,
                "-c",
                HERMES_SKILL_SELECTION_SCRIPT,
                profile_id,
                json.dumps(sorted(set(enabled_skill_ids))),
            ],
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
        return _error_payload("runtime_timeout", "Hermes skill selection timed out.")
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return _error_payload("runtime_failed", "Hermes skill selection could not be started.")
    if result.returncode != 0:
        return _error_payload("runtime_failed", f"Hermes skill selection exited with status {result.returncode}.")
    try:
        payload = json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        return _error_payload("invalid_payload", "Hermes skill selection returned invalid JSON.")
    if not isinstance(payload, dict) or payload.get("schema_version") != SKILL_SCHEMA_VERSION:
        return _error_payload("invalid_payload", "Hermes skill selection returned an unsupported response.")
    return {
        "schema_version": SKILL_SCHEMA_VERSION,
        "status": "applied",
        "profile_id": _text(payload.get("profile_id"), 80),
        "enabled_builtin_skills": [
            _text(value, 120) for value in payload.get("enabled_builtin_skills") or [] if _text(value, 120)
        ],
        "disabled_builtin_skills": [
            _text(value, 120) for value in payload.get("disabled_builtin_skills") or [] if _text(value, 120)
        ],
        "error": None,
    }
