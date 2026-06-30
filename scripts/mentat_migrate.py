#!/usr/bin/env python
"""Project-owned local data migrations for Mentat."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


MENTAT_PROJECT_NAME = "Mentat"
MENTAT_PROJECT_ID = "project_mentat"
PREVIOUS_PROJECT_NAME = "Agent " "OS"
PREVIOUS_PROJECT_ID = "project_" "agent" "_os"
JSON_FILES = ("projects.json", "tasks.json", "agents.json", "agent_messages.json", "attention.json")


def read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fallback


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def normalize_project_name(value: Any) -> tuple[Any, bool]:
    if str(value or "").strip().lower() == PREVIOUS_PROJECT_NAME.lower():
        return MENTAT_PROJECT_NAME, True
    return value, False


def normalize_project_id(value: Any) -> tuple[Any, bool]:
    if str(value or "").strip().lower() == PREVIOUS_PROJECT_ID:
        return MENTAT_PROJECT_ID, True
    return value, False


def normalize_aliases(project: dict) -> bool:
    changed = False
    aliases = []
    for key in ("aliases", "legacy_names"):
        values = project.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            text = str(value or "").strip()
            if not text or text.lower() == PREVIOUS_PROJECT_NAME.lower():
                changed = True
                continue
            if text not in aliases:
                aliases.append(text)
    if aliases:
        if project.get("aliases") != aliases:
            project["aliases"] = aliases
            changed = True
    elif "aliases" in project:
        project.pop("aliases", None)
        changed = True
    if "legacy_names" in project:
        project.pop("legacy_names", None)
        changed = True
    return changed


def normalize_project(project: dict) -> bool:
    changed = False
    next_id, id_changed = normalize_project_id(project.get("id"))
    next_name, name_changed = normalize_project_name(project.get("name"))
    if id_changed:
        project["id"] = next_id
        changed = True
    if name_changed:
        project["name"] = next_name
        changed = True
    return normalize_aliases(project) or changed


def normalize_project_reference(item: dict) -> bool:
    next_project, changed = normalize_project_name(item.get("project"))
    if changed:
        item["project"] = next_project
    return changed


def normalize_payload(name: str, payload: Any) -> tuple[Any, bool]:
    if not isinstance(payload, list):
        return payload, False
    changed = False
    next_payload = []
    for item in payload:
        if not isinstance(item, dict):
            next_payload.append(item)
            continue
        candidate = dict(item)
        if name == "projects.json":
            changed = normalize_project(candidate) or changed
        else:
            changed = normalize_project_reference(candidate) or changed
        next_payload.append(candidate)
    return next_payload, changed


def backup_files(data_dir: Path, files: list[str]) -> Path:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup_dir = data_dir / "runtime" / "migrations" / f"mentat-rename-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for name in files:
        source = data_dir / name
        if source.exists():
            shutil.copy2(source, backup_dir / name)
    return backup_dir


def migrate_data(data_dir: Path, *, write: bool = False) -> dict:
    data_dir = data_dir.expanduser().resolve()
    updates: dict[str, Any] = {}
    changed_files: list[str] = []
    for name in JSON_FILES:
        path = data_dir / name
        payload = read_json(path, [])
        next_payload, changed = normalize_payload(name, payload)
        if changed:
            updates[name] = next_payload
            changed_files.append(name)

    backup_dir = None
    if write and changed_files:
        backup_dir = backup_files(data_dir, changed_files)
        for name, payload in updates.items():
            write_json(data_dir / name, payload)

    return {
        "ok": True,
        "data_dir": str(data_dir),
        "changed_files": changed_files,
        "backup_dir": str(backup_dir) if backup_dir else None,
        "dry_run": not write,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate local Mentat dashboard data")
    parser.add_argument("--data-dir", default="data", help="Project-owned data directory")
    parser.add_argument("--write", action="store_true", help="Write migrated JSON files after creating a local backup")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = migrate_data(Path(args.data_dir), write=args.write)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
