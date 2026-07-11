"""Capability-gated Hermes provider inventory and switching.

Mentat never reads credentials itself.  Both discovery and mutation execute in
the installed Hermes runtime and return only provider/model metadata.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Callable


HERMES_PROVIDER_INVENTORY_SCRIPT = r"""
import json
import os
import sys

from hermes_cli.profiles import resolve_profile_env

profile_id = sys.argv[1]
os.environ["HERMES_HOME"] = resolve_profile_env(profile_id)

from hermes_cli.inventory import build_models_payload, load_picker_context

ctx = load_picker_context()
payload = build_models_payload(
    ctx,
    explicit_only=True,
    picker_hints=True,
    include_unconfigured=False,
    refresh=sys.argv[2] == "refresh",
    probe_custom_providers=False,
    probe_current_custom_provider=True,
    max_models=None,
)
providers = []
for row in payload.get("providers") or []:
    if not isinstance(row, dict) or row.get("authenticated") is not True:
        continue
    slug = str(row.get("slug") or "").strip()
    if not slug:
        continue
    models = []
    for item in row.get("models") or []:
        model = str(item or "").strip()
        if model and model not in models:
            models.append(model)
    providers.append({
        "id": slug,
        "name": str(row.get("name") or slug).strip(),
        "authenticated": True,
        "current": bool(row.get("is_current")) or slug.lower() == str(ctx.current_provider or "").strip().lower(),
        "models": models,
    })
print(json.dumps({
    "profile_id": profile_id,
    "current_provider": str(ctx.current_provider or "").strip(),
    "current_model": str(ctx.current_model or "").strip(),
    "providers": providers,
}))
""".strip()


HERMES_PROVIDER_SWITCH_SCRIPT = r"""
import json
import os
import sys
from pathlib import Path

from hermes_cli.profiles import resolve_profile_env

profile_id, provider, model = sys.argv[1:4]
profile_home = resolve_profile_env(profile_id)
os.environ["HERMES_HOME"] = profile_home

from hermes_cli.web_server import _write_profile_model

_write_profile_model(Path(profile_home), provider, model)
print(json.dumps({"ok": True, "profile_id": profile_id, "provider": provider, "model": model}))
""".strip()


def _run_json(
    python_path: str | None,
    script: str,
    arguments: list[str],
    hermes_home: str | Path,
    *,
    cwd: str | Path,
    timeout: int,
    runner: Callable = subprocess.run,
) -> tuple[dict, str]:
    if not python_path:
        return {}, "Hermes runtime is unavailable."
    try:
        result = runner(
            [python_path, "-c", script, *arguments],
            cwd=str(cwd),
            env={**os.environ, "HERMES_HOME": str(hermes_home)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        return {}, str(exc)[:2_000]
    if result.returncode != 0:
        return {}, str(result.stderr or result.stdout or "Hermes operation failed.").strip()[:2_000]
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return {}, "Hermes returned an invalid response."
    return (payload, "") if isinstance(payload, dict) else ({}, "Hermes returned an invalid response.")


def provider_inventory(
    python_path: str | None,
    hermes_home: str | Path,
    profile_id: str,
    *,
    cwd: str | Path,
    refresh: bool = False,
    runner: Callable = subprocess.run,
) -> dict:
    payload, error = _run_json(
        python_path,
        HERMES_PROVIDER_INVENTORY_SCRIPT,
        [profile_id, "refresh" if refresh else "cached"],
        hermes_home,
        cwd=cwd,
        timeout=30,
        runner=runner,
    )
    if error:
        return {"profile_id": profile_id, "current_provider": "", "current_model": "", "providers": [], "error": error}
    providers = []
    for row in payload.get("providers") or []:
        if not isinstance(row, dict) or row.get("authenticated") is not True:
            continue
        provider_id = str(row.get("id") or "").strip()[:120]
        if not provider_id:
            continue
        models = []
        for value in row.get("models") or []:
            model = str(value or "").strip()[:160]
            if model and model not in models:
                models.append(model)
        providers.append({
            "id": provider_id,
            "name": str(row.get("name") or provider_id).strip()[:160],
            "authenticated": True,
            "current": bool(row.get("current")),
            "models": models,
        })
    return {
        "profile_id": profile_id,
        "current_provider": str(payload.get("current_provider") or "").strip()[:120],
        "current_model": str(payload.get("current_model") or "").strip()[:160],
        "providers": providers,
        "capabilities": {"providers.switch": True},
        "error": "" if providers else "Hermes reported no explicitly configured, authenticated providers for this profile.",
    }


def provider_switch_confirmation(profile_id: str, current_provider: str, current_model: str, provider: str, model: str) -> str:
    bound = "\0".join([profile_id, current_provider, current_model, provider, model])
    return "provider_switch_" + hashlib.sha256(bound.encode("utf-8")).hexdigest()[:24]


def preview_provider_switch(profile_id: str, provider: str, model: str, inventory: dict) -> tuple[dict, int]:
    target = next((row for row in inventory.get("providers") or [] if row.get("id") == provider and row.get("authenticated") is True), None)
    if target is None:
        return {"error": "Choose a provider Hermes reports as explicitly configured and authenticated."}, 400
    if model not in (target.get("models") or []):
        return {"error": f"Choose a model Hermes reports for {target.get('name') or provider}."}, 400
    current_provider = str(inventory.get("current_provider") or "")
    current_model = str(inventory.get("current_model") or "")
    confirmation_id = provider_switch_confirmation(profile_id, current_provider, current_model, provider, model)
    return {
        "ok": True,
        "requires_confirmation": True,
        "confirmation_id": confirmation_id,
        "profile_id": profile_id,
        "current": {"provider": current_provider, "model": current_model},
        "target": {"provider": provider, "provider_name": target.get("name") or provider, "model": model},
        "effects": [f"Change {profile_id} from {current_provider or 'no provider'} / {current_model or 'no model'} to {target.get('name') or provider} / {model}."],
        "warnings": ["New Agent Console runs for this profile will use this provider and model."],
    }, 200


def apply_provider_switch(
    python_path: str | None,
    hermes_home: str | Path,
    profile_id: str,
    provider: str,
    model: str,
    *,
    cwd: str | Path,
    runner: Callable = subprocess.run,
) -> tuple[dict, str]:
    return _run_json(
        python_path,
        HERMES_PROVIDER_SWITCH_SCRIPT,
        [profile_id, provider, model],
        hermes_home,
        cwd=cwd,
        timeout=20,
        runner=runner,
    )
