"""Validation and command construction for safe Hermes profile creation."""

from __future__ import annotations

import hashlib
import json
import re


PROFILE_CREATION_SCHEMA_VERSION = 1
PROFILE_DESCRIPTION_LIMIT = 500
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
PROFILE_CREATION_MODES = {"fresh", "clone_config"}
PROFILE_SKILL_MODES = {"default", "custom", "none"}
RESERVED_PROFILE_NAMES = {
    "hermes", "default", "test", "tmp", "root", "sudo",
    "chat", "model", "gateway", "setup", "whatsapp", "login", "logout",
    "status", "cron", "doctor", "dump", "config", "pairing", "skills",
    "tools", "mcp", "sessions", "insights", "version", "update",
    "uninstall", "profile", "plugins", "honcho", "acp",
}
PROFILE_CREATION_FIELDS = {
    "name",
    "description",
    "mode",
    "source_profile",
    "seed_skills",
    "skill_mode",
    "enabled_builtin_skills",
    "confirmed",
    "confirmation_id",
}


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _error(message: str, *, code: str = "invalid_request", status: int = 400):
    return {
        "schema_version": PROFILE_CREATION_SCHEMA_VERSION,
        "valid": False,
        "error": {"code": code, "message": message},
    }, status


def _profile_ids(discovery: dict) -> set[str]:
    return {
        _text(item.get("id"), 80).lower()
        for item in discovery.get("profiles") or []
        if isinstance(item, dict) and _text(item.get("id"), 80)
    }


def _confirmation_id(normalized: dict) -> str:
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "profile_create_" + hashlib.sha256(encoded).hexdigest()[:20]


def profile_creation_arguments(normalized: dict) -> list[str]:
    """Return fixed Hermes arguments; the executable path is supplied separately."""
    arguments = ["profile", "create", normalized["name"], "--no-alias"]
    if normalized["description"]:
        arguments.append(f"--description={normalized['description']}")
    if normalized["mode"] == "clone_config":
        arguments.append(f"--clone-from={normalized['source_profile']}")
    elif not normalized["seed_skills"]:
        arguments.append("--no-skills")
    return arguments


def preview_profile_creation(payload, discovery: dict, skill_catalog: dict | None = None):
    """Validate a creation request and return its exact, confirmable effects."""
    if not isinstance(payload, dict):
        return _error("Profile creation payload must be a JSON object.")
    unknown = sorted(set(payload) - PROFILE_CREATION_FIELDS)
    if unknown:
        return _error(f"Unsupported profile creation fields: {', '.join(unknown)}.")
    if not isinstance(discovery, dict) or discovery.get("status") != "available":
        return _error(
            "Hermes profile discovery is unavailable.",
            code="profile_discovery_unavailable",
            status=503,
        )
    capabilities = discovery.get("capabilities") if isinstance(discovery.get("capabilities"), dict) else {}
    if not capabilities.get("profiles.create"):
        return _error(
            "This Hermes runtime does not expose profile creation.",
            code="capability_unavailable",
            status=503,
        )
    if not capabilities.get("profiles.identity.write"):
        return _error(
            "This Hermes runtime cannot synchronize the new profile's runtime identity.",
            code="identity_capability_unavailable",
            status=503,
        )

    name = _text(payload.get("name"), 80).lower()
    if not name:
        return _error("Profile name is required.")
    if not PROFILE_NAME_RE.fullmatch(name):
        return _error("Profile name must match [a-z0-9][a-z0-9_-]{0,63}.")
    if name in RESERVED_PROFILE_NAMES:
        return _error(f"Profile name '{name}' is reserved.")

    existing = _profile_ids(discovery)
    if name in existing:
        return _error(
            f"Hermes profile '{name}' already exists.",
            code="profile_exists",
            status=409,
        )

    description_raw = str(payload.get("description") or "")
    description = _text(description_raw, PROFILE_DESCRIPTION_LIMIT)
    if len(" ".join(description_raw.split())) > PROFILE_DESCRIPTION_LIMIT:
        return _error(f"Profile description must be {PROFILE_DESCRIPTION_LIMIT} characters or fewer.")

    mode = _text(payload.get("mode") or "fresh", 40).lower()
    if mode not in PROFILE_CREATION_MODES:
        return _error("Creation mode must be 'fresh' or 'clone_config'.")
    source_profile = _text(payload.get("source_profile"), 80).lower()
    requested_skill_mode = _text(payload.get("skill_mode"), 40).lower()
    raw_seed_skills = payload.get("seed_skills", True)
    if not isinstance(raw_seed_skills, bool):
        return _error("seed_skills must be true or false.")
    skill_mode = requested_skill_mode or ("default" if raw_seed_skills else "none")
    if skill_mode not in PROFILE_SKILL_MODES:
        return _error("skill_mode must be 'default', 'custom', or 'none'.")
    if requested_skill_mode and "seed_skills" in payload:
        implied_seed_skills = skill_mode != "none"
        if raw_seed_skills != implied_seed_skills:
            return _error("seed_skills conflicts with skill_mode.")
    seed_skills = skill_mode != "none"

    raw_enabled_skills = payload.get("enabled_builtin_skills", [])
    if not isinstance(raw_enabled_skills, list):
        return _error("enabled_builtin_skills must be a list.")
    enabled_builtin_skills = sorted({
        _text(value, 120) for value in raw_enabled_skills if _text(value, 120)
    })
    if skill_mode != "custom" and enabled_builtin_skills:
        return _error("enabled_builtin_skills is only allowed when skill_mode is 'custom'.")
    if skill_mode == "custom":
        if not isinstance(skill_catalog, dict) or skill_catalog.get("status") != "available":
            return _error(
                "Hermes built-in skill discovery is unavailable.",
                code="skill_catalog_unavailable",
                status=503,
            )
        skill_capabilities = (
            skill_catalog.get("capabilities")
            if isinstance(skill_catalog.get("capabilities"), dict)
            else {}
        )
        if not skill_capabilities.get("skills.selection.write"):
            return _error(
                "This Hermes runtime does not expose profile skill selection.",
                code="skill_selection_unavailable",
                status=503,
            )
        available_skill_ids = {
            _text(item.get("id"), 120)
            for item in skill_catalog.get("skills") or []
            if isinstance(item, dict) and _text(item.get("id"), 120)
        }
        unknown_skills = sorted(set(enabled_builtin_skills) - available_skill_ids)
        if unknown_skills:
            return _error(f"Unknown built-in skills: {', '.join(unknown_skills)}.")

    if mode == "clone_config":
        if not source_profile:
            return _error("source_profile is required for clone_config mode.")
        if source_profile not in existing:
            return _error(
                f"Source profile '{source_profile}' does not exist.",
                code="source_profile_missing",
                status=404,
            )
        if skill_mode == "none":
            return _error("clone_config always copies the source profile's skills; skill_mode cannot be 'none'.")
    elif source_profile:
        return _error("source_profile is only allowed for clone_config mode.")

    normalized = {
        "name": name,
        "description": description,
        "mode": mode,
        "source_profile": source_profile,
        "seed_skills": seed_skills,
        "skill_mode": skill_mode,
        "enabled_builtin_skills": enabled_builtin_skills,
    }
    arguments = profile_creation_arguments(normalized)
    effects = [
        f"Create Hermes profile '{name}'.",
        "Do not create a shell wrapper alias; Mentat will address the profile explicitly.",
    ]
    warnings = []
    if mode == "clone_config":
        effects.append(
            f"Ask Hermes to clone config, .env, SOUL.md, skills, and supported identity files from '{source_profile}'."
        )
        effects.append("Place the new profile's managed name and role above inherited SOUL.md content.")
        warnings.append("The source profile's credentials file is copied by Hermes without Mentat reading its contents.")
    elif skill_mode == "default":
        effects.append("Ask Hermes to seed its bundled skills into the fresh profile.")
    else:
        if skill_mode == "none":
            effects.append("Opt the fresh profile out of bundled skill seeding.")
    if skill_mode == "custom":
        effects.append(
            f"Enable {len(enabled_builtin_skills)} selected built-in skills and disable the remaining built-in skills."
        )
    if description:
        effects.append("Store the supplied profile description through Hermes.")
    effects.append("Synchronize the profile name and role into Mentat's versioned SOUL.md identity block.")

    return {
        "schema_version": PROFILE_CREATION_SCHEMA_VERSION,
        "valid": True,
        "operation": "profiles.create",
        "requires_confirmation": True,
        "confirmation_id": _confirmation_id(normalized),
        "normalized": normalized,
        "effects": effects,
        "warnings": warnings,
        "command": {"program": "hermes", "arguments": arguments},
        "error": None,
    }, 200
