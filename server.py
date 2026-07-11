#!/usr/bin/env python
"""Mentat local dashboard server.

Hermes state is read directly only for observation. Mutations are limited to
typed, capability-gated Hermes adapter operations; project-owned write-back
remains allowlisted.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import mimetypes
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from uuid import uuid4
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from health_checks import HEALTH_STATUS_RANK, HealthContext, health as build_health_payload
from agent_run_history import (
    EVENT_RETENTION,
    EVENT_SCHEMA_VERSION,
    load_run_summaries,
    save_run_summaries,
    secure_history_permissions,
)
from command_manifest import command_manifest_payload
from json_store import read_json as store_read_json, update_json as store_update_json
from hermes_profile_creation import preview_profile_creation, profile_creation_arguments
from hermes_profile_deletion import delete_hermes_profile, preview_profile_deletion
from hermes_provider_switching import (
    apply_provider_switch,
    preview_provider_switch,
    provider_inventory,
)
from hermes_profiles import discover_hermes_profiles
from hermes_skills import apply_builtin_skill_selection, discover_builtin_skills
from runtime_config import (
    AppConfig,
    DEFAULT_APP_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    default_hermes_home,
    default_obsidian_vault,
    env_value,
    load_app_config,
    parse_cli_args,
)

BASE_DIR = Path(__file__).resolve().parent


class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server with an IPv6 socket for the ::1 loopback."""

    address_family = socket.AF_INET6


def server_class_for_host(host: str):
    return IPv6ThreadingHTTPServer if host.strip().lower() == "::1" else ThreadingHTTPServer


def browser_url(host: str, port: int) -> str:
    display_host = f"[{host}]" if ":" in host else host
    return f"http://{display_host}:{port}"

def apply_runtime_config(config: AppConfig) -> AppConfig:
    global APP_CONFIG, HOST, PORT, DATA_DIR, PUBLIC_DIR, HERMES_HOME, OBSIDIAN_VAULT, STATE_DB, CRON_JOBS, CONFIG_PATH, GOOGLE_TOKEN
    global CONFIG_DISPLAY_NAME, CONFIG_GREETING_PREFIX, CONFIG_APP_NAME

    APP_CONFIG = config
    HOST = config.host
    PORT = config.port
    DATA_DIR = config.data_dir
    PUBLIC_DIR = config.public_dir
    HERMES_HOME = config.hermes_home
    OBSIDIAN_VAULT = config.obsidian_vault
    STATE_DB = HERMES_HOME / "state.db"
    CRON_JOBS = HERMES_HOME / "cron" / "jobs.json"
    CONFIG_PATH = HERMES_HOME / "config.yaml"
    GOOGLE_TOKEN = HERMES_HOME / "google_token.json"
    CONFIG_DISPLAY_NAME = config.display_name
    CONFIG_GREETING_PREFIX = config.greeting_prefix
    CONFIG_APP_NAME = config.app_name
    return config


def runtime_config_summary() -> dict:
    return {
        "config_files": [str(path) for path in APP_CONFIG.config_files],
        "server": {"host": HOST, "port": PORT},
        "paths": {
            "data_dir": str(DATA_DIR),
            "public_dir": str(PUBLIC_DIR),
            "hermes_home": str(HERMES_HOME),
            "obsidian_vault": str(OBSIDIAN_VAULT),
        },
        "dashboard": {
            "display_name": CONFIG_DISPLAY_NAME,
            "greeting_prefix": CONFIG_GREETING_PREFIX,
            "app_name": CONFIG_APP_NAME,
        },
    }


def managed_server_ports(primary_port: int | None = None) -> list[int]:
    port = int(primary_port or PORT)
    return sorted({port, 8888, 8890})


def runtime_state_path() -> Path:
    return DATA_DIR / "runtime" / "server-state.json"


def runtime_state_payload() -> dict:
    return {
        "pid": os.getpid(),
        "host": HOST,
        "port": PORT,
        "managed_ports": managed_server_ports(PORT),
        "started_at": now_iso(),
        "cwd": str(BASE_DIR),
        "config_files": [str(path) for path in APP_CONFIG.config_files],
        "launcher_pid": configured_launcher_pid(),
    }


def write_runtime_state() -> Path:
    path = runtime_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(runtime_state_payload(), indent=2) + "\n", encoding="utf-8")
    return path


def clear_runtime_state() -> None:
    path = runtime_state_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def configured_launcher_pid() -> int | None:
    raw = (env_value("LAUNCHER_PID") or "").strip()
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 and pid != os.getpid() else None


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    ctypes.set_last_error(0)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    return ctypes.get_last_error() == 5


def start_launcher_watch(http_server: ThreadingHTTPServer) -> int | None:
    launcher_pid = configured_launcher_pid()
    if launcher_pid is None:
        return None

    def watch() -> None:
        while True:
            time.sleep(2)
            if not process_exists(launcher_pid):
                print(f"Launcher PID {launcher_pid} is gone; stopping Mentat.")
                try:
                    http_server.shutdown()
                except Exception:
                    pass
                break

    threading.Thread(target=watch, daemon=True, name="mentat-launcher-watch").start()
    return launcher_pid


HOST = DEFAULT_HOST
PORT = DEFAULT_PORT
DATA_DIR = BASE_DIR / "data"
PUBLIC_DIR = BASE_DIR / "public"
HERMES_HOME = default_hermes_home()
OBSIDIAN_VAULT = default_obsidian_vault()
STATE_DB = HERMES_HOME / "state.db"
CRON_JOBS = HERMES_HOME / "cron" / "jobs.json"
CONFIG_PATH = HERMES_HOME / "config.yaml"
GOOGLE_TOKEN = HERMES_HOME / "google_token.json"
CONFIG_DISPLAY_NAME = None
CONFIG_GREETING_PREFIX = None
CONFIG_APP_NAME = DEFAULT_APP_NAME
APP_CONFIG = AppConfig(tuple(), HOST, PORT, DATA_DIR, PUBLIC_DIR, HERMES_HOME, OBSIDIAN_VAULT)
ALLOWED_DATA_WRITES = {"attention.json", "projects.json", "tasks.json", "dashboard.json", "calendar.json", "agents.json", "agent_messages.json"}
CALENDAR_CACHE_TTL_SECONDS = 300
CALENDAR_CACHE = {"key": None, "payload": None, "fetched_at": None}
OBSIDIAN_NOTES_CACHE = {"key": None, "payload": None}
SESSION_DETAIL_CACHE: dict[tuple, tuple[dict, int]] = {}
SESSION_REPLAY_CACHE: dict[tuple, tuple[dict, int]] = {}
TASK_STATUS_VALUES = {"todo", "in progress", "waiting", "needs attention", "completed"}
TASK_PRIORITY_VALUES = {"high", "medium", "low"}
PROJECT_STATUS_VALUES = {"active", "paused", "archived"}
MESSAGE_STATUS_VALUES = {"queued", "acknowledged", "delivered", "failed", "cancelled", "needs user input"}
MESSAGE_PRIORITY_VALUES = {"normal", "high", "urgent"}
AGENT_STATUS_VALUES = {"running", "idle", "blocked", "done", "failed"}
AGENT_ACTIVE_STATUSES = {"running", "idle", "blocked"}
AGENT_STALE_AFTER_SECONDS = 60
AGENT_DERIVED_SESSIONS_LIMIT = 12
AGENT_DERIVED_SESSION_MAX_AGE_SECONDS = 24 * 60 * 60
AGENT_CONSOLE_RUN_LIMIT = 24
AGENT_CONSOLE_PROMPT_LIMIT = 20_000
MAX_JSON_BODY_BYTES = 256_000
AGENT_CONSOLE_ACTIVE_STATUSES = {"queued", "running", "cancelling"}
AGENT_MODEL_CATALOG_TTL_SECONDS = 120
AGENT_MODEL_CATALOG_CACHE = {"key": None, "payload": None, "fetched_at": 0.0}
AGENT_CONSOLE_RUNS: dict[str, dict] = {}
AGENT_CONSOLE_PROCESSES: dict[str, subprocess.Popen] = {}
AGENT_CONSOLE_LOCK = threading.RLock()
HERMES_PROFILE_CREATION_LOCK = threading.Lock()
# Profile creation and deletion share one mutation lock. The existing name is
# retained for compatibility with the initial creator contract and tests.
AGENT_CONSOLE_HISTORY_LOADED = False
MENTAT_PROJECT_NAME = "Mentat"
MENTAT_PROJECT_ID = "project_mentat"
PREVIOUS_PROJECT_NAME = "Agent " "OS"
PREVIOUS_PROJECT_ID = "project_" "agent" "_os"

apply_runtime_config(load_app_config())

def note_sort_key(path: Path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def agent_console_history_path() -> Path:
    return DATA_DIR / "runtime" / "agent-console-runs.json"


def persist_agent_console_runs() -> bool:
    """Persist bounded run summaries; callers may already hold the re-entrant lock."""
    if not AGENT_CONSOLE_HISTORY_LOADED:
        return True
    try:
        with AGENT_CONSOLE_LOCK:
            save_run_summaries(
                agent_console_history_path(),
                list(AGENT_CONSOLE_RUNS.values()),
                retention=AGENT_CONSOLE_RUN_LIMIT,
                data_root=DATA_DIR,
            )
        return True
    except OSError as exc:
        print(f"Agent Console history could not be persisted: {compact_text(exc, max_length=500)}")
        return False


def load_agent_console_runs() -> None:
    """Restore prior summaries and fail closed to an empty history on corruption."""
    global AGENT_CONSOLE_HISTORY_LOADED
    history_path = agent_console_history_path()
    if not secure_history_permissions(history_path, data_root=DATA_DIR):
        print("Agent Console history permissions could not be restricted on this platform.")
        with AGENT_CONSOLE_LOCK:
            AGENT_CONSOLE_RUNS.clear()
            AGENT_CONSOLE_HISTORY_LOADED = True
        return
    with AGENT_CONSOLE_LOCK:
        runs, recovered = load_run_summaries(
            history_path, now=now_iso, retention=AGENT_CONSOLE_RUN_LIMIT
        )
        AGENT_CONSOLE_RUNS.clear()
        AGENT_CONSOLE_RUNS.update((run["id"], run) for run in runs)
        AGENT_CONSOLE_HISTORY_LOADED = True
        # Rewrite every retained valid history through the current redactor and
        # private atomic writer. Corrupt/unsupported files remain untouched but
        # are still permission-restricted above for safe manual recovery.
        if runs or recovered:
            persist_agent_console_runs()


def compact_text(value, *, max_length: int | None = None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if max_length and len(text) > max_length:
        text = text[:max_length].rstrip()
    return text


def task_id_value() -> str:
    return f"task_{uuid4().hex[:12]}"


def task_tags_value(value) -> list[str]:
    if not isinstance(value, list):
        return []
    tags = []
    for item in value:
        tag = compact_text(item, max_length=48)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def task_due_date_value(value):
    raw = compact_text(value, max_length=32)
    if not raw:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    return None


def slug_id(prefix: str, value: str) -> str:
    base = compact_text(value, max_length=120).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return f"{prefix}_{slug}" if slug else f"{prefix}_{uuid4().hex[:12]}"


def project_id_value(value) -> str:
    return slug_id("project", value)


def message_id_value() -> str:
    return f"msg_{uuid4().hex[:12]}"


def text_list_value(value, *, max_items: int = 12, max_length: int = 80) -> list[str]:
    if not isinstance(value, list):
        return []
    items = []
    for item in value[:max_items]:
        text = compact_text(item, max_length=max_length)
        if text and text not in items:
            items.append(text)
    return items


def project_aliases(project: dict) -> list[str]:
    aliases = []
    for key in ("aliases", "legacy_names"):
        for item in text_list_value(project.get(key), max_items=12, max_length=120):
            if item not in aliases:
                aliases.append(item)
    return aliases


def project_name_lookup() -> dict[str, str]:
    projects = read_json_file("projects.json", [])
    lookup: dict[str, str] = {}
    if isinstance(projects, list):
        for project in projects:
            if not isinstance(project, dict):
                continue
            name = compact_text(project.get("name"), max_length=120)
            if not name:
                continue
            lookup[name.lower()] = name
            for alias in project_aliases(project):
                lookup[alias.lower()] = name
    if MENTAT_PROJECT_NAME.lower() in lookup or not lookup:
        lookup.setdefault(PREVIOUS_PROJECT_NAME.lower(), MENTAT_PROJECT_NAME)
    return lookup


def canonical_project_name(value: str) -> str:
    name = compact_text(value, max_length=120)
    if not name:
        return ""
    return project_name_lookup().get(name.lower(), name)


def project_names() -> set[str]:
    projects = read_json_file("projects.json", [])
    if not isinstance(projects, list):
        return set()
    return {compact_text(project.get("name"), max_length=120) for project in projects if isinstance(project, dict) and compact_text(project.get("name"), max_length=120)}


def validate_task_payload(payload, *, existing: dict | None = None):
    if not isinstance(payload, dict):
        return None, "Task payload must be a JSON object"

    title = compact_text(payload.get("title"), max_length=160)
    if not title:
        return None, "Task title is required"

    project = canonical_project_name(payload.get("project"))
    if not project:
        return None, "Task project is required"

    if project not in project_names():
        return None, f"Unknown project: {project}"

    status = compact_text(payload.get("status") or "todo", max_length=32).lower().replace("_", " ") or "todo"
    if status not in TASK_STATUS_VALUES:
        return None, f"Invalid task status: {status}"

    priority = compact_text(payload.get("priority") or "medium", max_length=16).lower() or "medium"
    if priority not in TASK_PRIORITY_VALUES:
        return None, f"Invalid task priority: {priority}"

    due_date = task_due_date_value(payload.get("due_date"))
    if payload.get("due_date") not in (None, "") and due_date is None:
        return None, "Task due_date must be YYYY-MM-DD or empty"

    tags = task_tags_value(payload.get("tags"))
    source = compact_text(payload.get("source") or (existing or {}).get("source") or "dashboard", max_length=32) or "dashboard"
    assignee = compact_text(payload.get("assignee"), max_length=120) or None
    description = str(payload.get("description") or "").strip()
    created_at = existing.get("created_at") if isinstance(existing, dict) else None
    completed_at = existing.get("completed_at") if isinstance(existing, dict) else None
    timestamp = now_iso()

    normalized = {
        "id": compact_text((existing or {}).get("id"), max_length=80) or task_id_value(),
        "title": title,
        "description": description,
        "project": project,
        "status": status,
        "priority": priority,
        "assignee": assignee,
        "due_date": due_date,
        "source": source,
        "tags": tags,
        "review_required": bool(payload.get("review_required")),
        "needs_attention": bool(payload.get("needs_attention")),
        "created_at": created_at or timestamp,
        "updated_at": timestamp,
        "completed_at": completed_at,
    }
    if status == "completed" and not normalized["completed_at"]:
        normalized["completed_at"] = timestamp
    if status != "completed":
        normalized["completed_at"] = None
    return normalized, None


def validate_project_payload(payload, *, existing: dict | None = None):
    if not isinstance(payload, dict):
        return None, "Project payload must be a JSON object"

    name = compact_text(payload.get("name"), max_length=120)
    if not name:
        return None, "Project name is required"

    status = compact_text(payload.get("status") or (existing or {}).get("status") or "active", max_length=32).lower().replace("_", " ")
    if status not in PROJECT_STATUS_VALUES:
        return None, f"Invalid project status: {status}"

    timestamp = now_iso()
    aliases = text_list_value(payload.get("aliases"), max_items=12, max_length=120)
    if not aliases:
        aliases = text_list_value(payload.get("legacy_names"), max_items=12, max_length=120)

    normalized = {
        "id": compact_text((existing or {}).get("id"), max_length=80) or project_id_value(name),
        "name": name,
        "type": compact_text(payload.get("type") or (existing or {}).get("type") or "project", max_length=80) or "project",
        "status": status,
        "description": str(payload.get("description") or "").strip(),
        "obsidian_note": compact_text(payload.get("obsidian_note"), max_length=160) or None,
        "created_at": (existing or {}).get("created_at") or timestamp,
        "updated_at": timestamp,
        "aliases": aliases,
    }
    return normalized, None


def default_message_project() -> str:
    names = sorted(project_names())
    if MENTAT_PROJECT_NAME in names:
        return MENTAT_PROJECT_NAME
    return names[0] if names else "General"


def message_audit_event(event: str, *, actor: str = "dashboard", note: str | None = None) -> dict:
    payload = {"at": now_iso(), "actor": compact_text(actor, max_length=80) or "dashboard", "event": event}
    cleaned_note = compact_text(note, max_length=240)
    if cleaned_note:
        payload["note"] = cleaned_note
    return payload


def normalize_message_status(value) -> str:
    status = compact_text(value or "queued", max_length=32).lower().replace("_", " ").replace("-", " ") or "queued"
    return status


def validate_agent_message_payload(payload, *, existing: dict | None = None):
    if not isinstance(payload, dict):
        return None, "Agent message payload must be a JSON object"

    body = str(payload.get("message") or payload.get("body") or "").strip()
    if not body:
        return None, "Agent message body is required"
    if len(body) > 2000:
        return None, "Agent message body must be 2000 characters or fewer"

    status = normalize_message_status(payload.get("status") or (existing or {}).get("status") or "queued")
    if status not in MESSAGE_STATUS_VALUES:
        return None, f"Invalid agent message status: {status}"

    priority = compact_text(payload.get("priority") or (existing or {}).get("priority") or "normal", max_length=16).lower() or "normal"
    if priority not in MESSAGE_PRIORITY_VALUES:
        return None, f"Invalid agent message priority: {priority}"

    project = compact_text(payload.get("project") or (existing or {}).get("project") or default_message_project(), max_length=120)
    recipient = compact_text(payload.get("recipient") or payload.get("agent") or (existing or {}).get("recipient") or "Hermes", max_length=120) or "Hermes"
    source = compact_text(payload.get("source") or (existing or {}).get("source") or "dashboard", max_length=40) or "dashboard"
    timestamp = now_iso()
    audit = list((existing or {}).get("audit") or []) if isinstance((existing or {}).get("audit"), list) else []

    normalized = {
        "id": compact_text((existing or {}).get("id"), max_length=80) or message_id_value(),
        "recipient": recipient,
        "project": project,
        "message": body,
        "status": status,
        "priority": priority,
        "source": source,
        "related_task_id": compact_text(payload.get("related_task_id") or (existing or {}).get("related_task_id"), max_length=80) or None,
        "created_at": (existing or {}).get("created_at") or timestamp,
        "updated_at": timestamp,
        "delivered_at": (existing or {}).get("delivered_at"),
        "resolved_at": (existing or {}).get("resolved_at"),
        "safety": {
            "local_only": True,
            "shell_execution": "forbidden",
            "writes": "project-owned agent_messages.json only",
        },
        "audit": audit,
    }
    if status == "delivered" and not normalized["delivered_at"]:
        normalized["delivered_at"] = timestamp
    if status in {"delivered", "failed", "cancelled"} and not normalized["resolved_at"]:
        normalized["resolved_at"] = timestamp
    if status not in {"delivered", "failed", "cancelled"}:
        normalized["resolved_at"] = None
    return normalized, None


def agent_id_value(value) -> str:
    base = compact_text(value, max_length=120).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return f"agent_{slug}" if slug else f"agent_{uuid4().hex[:12]}"


def agent_status_value(value) -> str:
    status = compact_text(value or "idle", max_length=24).lower().replace("_", " ").replace("-", " ")
    if status == "active":
        return "running"
    return status


def normalize_agent_payload(payload, *, existing: dict | None = None, agent_id: str | None = None):
    if not isinstance(payload, dict):
        return None, "Agent payload must be a JSON object"

    name = compact_text(payload.get("name") or payload.get("agent") or payload.get("title"), max_length=120)
    if not name:
        return None, "Agent name is required"

    status = agent_status_value(payload.get("status"))
    if status not in AGENT_STATUS_VALUES:
        return None, f"Invalid agent status: {status}"

    current_task = compact_text(payload.get("current_task"), max_length=160)
    project = compact_text(payload.get("project"), max_length=120)
    cwd = compact_text(payload.get("cwd"), max_length=240)
    model = compact_text(payload.get("model"), max_length=120)
    source = compact_text(payload.get("source") or (existing or {}).get("source") or "dashboard", max_length=32) or "dashboard"
    latest_output = compact_text(payload.get("latest_output"), max_length=280)
    related_task_id = compact_text(payload.get("related_task_id"), max_length=80)
    needs_user_input = bool(payload.get("needs_user_input"))
    timestamp = datetime.now().astimezone().isoformat(timespec="microseconds")

    created_at = existing.get("created_at") if isinstance(existing, dict) else None
    started_at = existing.get("started_at") if isinstance(existing, dict) else None
    resolved_at = existing.get("resolved_at") if isinstance(existing, dict) else None
    if status in {"done", "failed"} and not resolved_at:
        resolved_at = timestamp
    if status not in {"done", "failed"}:
        resolved_at = None

    normalized = {
        "id": compact_text(agent_id or (existing or {}).get("id"), max_length=80) or agent_id_value(name),
        "name": name,
        "status": status,
        "current_task": current_task or None,
        "project": project or None,
        "cwd": cwd or None,
        "model": model or None,
        "source": source,
        "latest_output": latest_output or None,
        "needs_user_input": needs_user_input,
        "related_task_id": related_task_id or None,
        "created_at": created_at or timestamp,
        "started_at": started_at or created_at or timestamp,
        "updated_at": timestamp,
        "last_heartbeat": timestamp,
        "resolved_at": resolved_at,
    }
    return normalized, None


def agent_summary(agents: list[dict]) -> dict:
    summary = {status: 0 for status in AGENT_STATUS_VALUES}
    needs_user_input = 0
    live = 0
    stale = 0
    resolved = 0
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        status = compact_text(agent.get("status"), max_length=24).lower()
        if status in summary:
            summary[status] += 1
        if agent.get("needs_user_input"):
            needs_user_input += 1
        freshness = compact_text(agent.get("freshness") or "live", max_length=24).lower()
        if freshness == "stale":
            stale += 1
        elif freshness == "resolved":
            resolved += 1
        else:
            live += 1
    summary["needs_user_input"] = needs_user_input
    summary["live"] = live
    summary["stale"] = stale
    summary["resolved"] = resolved
    summary["total"] = sum(summary[status] for status in AGENT_STATUS_VALUES)
    return summary


def agent_record_with_freshness(agent: dict, *, now: datetime | None = None) -> dict:
    record = dict(agent) if isinstance(agent, dict) else {}
    status = compact_text(record.get("status") or "idle", max_length=24).lower()
    now = now or datetime.now().astimezone()
    last_seen = parse_iso(record.get("last_heartbeat") or record.get("updated_at") or record.get("started_at") or record.get("created_at"))
    heartbeat_age_seconds = None
    stale = False
    freshness = "resolved" if status in {"done", "failed"} else "live"

    if last_seen is not None:
        heartbeat_age_seconds = max(int((now - last_seen).total_seconds()), 0)
        stale = status in AGENT_ACTIVE_STATUSES and heartbeat_age_seconds >= AGENT_STALE_AFTER_SECONDS
    elif status in AGENT_ACTIVE_STATUSES:
        stale = True

    if stale:
        freshness = "stale"

    record["heartbeat_age_seconds"] = heartbeat_age_seconds
    record["stale"] = stale
    record["freshness"] = freshness
    return record


def agent_guidance() -> dict:
    base_host = HOST if HOST not in {"0.0.0.0", "::"} else "127.0.0.1"
    base_url = f"http://{base_host}:{PORT}"
    return {
        "base_url": base_url,
        "stale_after_seconds": AGENT_STALE_AFTER_SECONDS,
        "examples_command": "python scripts/agent_heartbeat.py examples",
        "beat_command": f'python scripts/agent_heartbeat.py beat --base-url {base_url} --name "Hermes" --project Mentat --current-task "Working on Mentat"',
        "run_command": f'python scripts/agent_heartbeat.py run --base-url {base_url} --name "Hermes Worker" --project Mentat --current-task "Implement feature" --interval 15 -- python worker.py',
    }


def synthesize_live_session_agents(session_payload, *, now: datetime | None = None, limit: int = AGENT_DERIVED_SESSIONS_LIMIT) -> list[dict]:
    if not isinstance(session_payload, dict):
        return []

    if not session_payload.get("exists", False):
        return []

    sessions = session_payload.get("sessions")
    if not isinstance(sessions, list):
        return []

    now = now or datetime.now().astimezone()
    cutoff = now - timedelta(seconds=AGENT_DERIVED_SESSION_MAX_AGE_SECONDS)
    session_agents: list[dict] = []
    timestamp = now.isoformat(timespec="microseconds")

    for session in sessions[:limit]:
        if not isinstance(session, dict):
            continue

        session_id = compact_text(session.get("id"), max_length=80)
        if not session_id:
            continue

        started_at = parse_iso(session.get("started_at"))
        ended_at = parse_iso(session.get("ended_at"))
        if ended_at is not None:
            continue

        if started_at is not None and started_at < cutoff:
            continue

        title = compact_text(session.get("title"), max_length=120)
        if not title:
            title = f"Session {session_id[:8]}"

        started_iso = (started_at or now).isoformat(timespec="microseconds")
        session_agents.append(
            {
                "id": f"session_{session_id}",
                "name": title,
                "status": "running",
                "current_task": compact_text(session.get("title"), max_length=140),
                "project": compact_text(session.get("source"), max_length=120) or None,
                "cwd": None,
                "model": compact_text(session.get("model"), max_length=120),
                "source": "hermes-session",
                "latest_output": "No heartbeat yet; session derived from active Hermes sessions.",
                "needs_user_input": False,
                "related_task_id": None,
                "created_at": started_iso,
                "started_at": started_iso,
                "updated_at": timestamp,
                "last_heartbeat": timestamp,
                "resolved_at": None,
                "session_id": session_id,
            }
        )

    return session_agents


def merge_agents_with_session_observations(registered_agents: list[dict], observed_agents: list[dict]) -> list[dict]:
    existing_ids = {compact_text(agent.get("id"), max_length=80) for agent in registered_agents if isinstance(agent, dict) and compact_text(agent.get("id"), max_length=80)}
    observed_session_ids = {
        compact_text(agent.get("session_id"), max_length=80): True
        for agent in registered_agents
        if isinstance(agent, dict) and compact_text(agent.get("session_id"), max_length=80)
    }

    merged = list(registered_agents)
    for agent in observed_agents:
        if not isinstance(agent, dict):
            continue

        agent_id = compact_text(agent.get("id"), max_length=80)
        session_id = compact_text(agent.get("session_id"), max_length=80)

        if session_id and session_id in observed_session_ids:
            continue
        if agent_id in existing_ids:
            continue

        merged.append(agent)

    return merged


def agents_payload():
    agents = read_json_file("agents.json", [])
    if isinstance(agents, dict) and agents.get("error"):
        return agents
    if not isinstance(agents, list):
        return {"error": "agents.json must contain a list"}

    now = datetime.now().astimezone()
    session_payload = recent_sessions(limit=AGENT_DERIVED_SESSIONS_LIMIT)
    session_agents = synthesize_live_session_agents(session_payload, now=now)
    merged = merge_agents_with_session_observations([agent for agent in agents if isinstance(agent, dict)], session_agents)

    ordered = [agent_record_with_freshness(agent, now=now) for agent in merged if isinstance(agent, dict)]
    ordered.sort(key=lambda agent: agent.get("last_heartbeat") or agent.get("updated_at") or agent.get("started_at") or "", reverse=True)

    if isinstance(session_payload, dict) and session_payload.get("sessions") and not isinstance(session_payload.get("sessions"), list):
        sessions = []
    else:
        sessions = session_payload.get("sessions") if isinstance(session_payload, dict) else []

    return {
        "agents": ordered,
        "sessions": sessions or [],
        "summary": agent_summary(ordered),
        "guidance": agent_guidance(),
    }


def upsert_agent_heartbeat(payload):
    def mutator(agents):
        if isinstance(agents, dict) and agents.get("error"):
            return agents, (agents, 500)
        if not isinstance(agents, list):
            return agents, ({"error": "agents.json must contain a list"}, 500)

        agent_id = compact_text((payload or {}).get("id") or (payload or {}).get("agent_id"), max_length=80)
        if not agent_id:
            agent_name = compact_text((payload or {}).get("name") or (payload or {}).get("agent") or (payload or {}).get("title"), max_length=120)
            agent_id = agent_id_value(agent_name)

        next_agents = [agent for agent in agents if isinstance(agent, dict)]
        existing_index = None
        existing_agent = None
        for index, agent in enumerate(next_agents):
            if str(agent.get("id") or "") == agent_id:
                existing_index = index
                existing_agent = agent
                break

        normalized, error = normalize_agent_payload(payload, existing=existing_agent, agent_id=agent_id)
        if error:
            return agents, ({"error": error}, 400)

        if existing_index is None:
            next_agents.append(normalized)
            status = 201
        else:
            next_agents[existing_index] = normalized
            status = 200

        return next_agents, ({"ok": True, "agent": normalized, "agents": next_agents, "summary": agent_summary(next_agents)}, status)

    return update_json_file("agents.json", [], mutator)


def file_mtime_iso(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None


def human_bytes(n: int | float | None) -> str | None:
    if n is None:
        return None
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"



def dashboard_data_path(name: str) -> Path:
    """Resolve an allowlisted project-owned data file under DATA_DIR."""
    if name not in ALLOWED_DATA_WRITES or "/" in name or "\\" in name:
        raise ValueError(f"Refusing to access non-allowlisted dashboard data file: {name}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_root = DATA_DIR.resolve()
    path = (DATA_DIR / name).resolve()
    if path.parent != data_root:
        raise ValueError(f"Refusing to access outside dashboard data directory: {name}")
    return path


def read_json_file(name: str, default):
    path = DATA_DIR / name
    try:
        return store_read_json(path, default)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON in {path}: {exc}"}


def update_json_file(name: str, default, mutator):
    """Run a locked project-owned JSON read/modify/write cycle."""
    path = dashboard_data_path(name)
    try:
        return store_update_json(path, default, mutator)
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON in {path}: {exc}"}, 500


def google_credentials(scopes: list[str]):
    try:
        google_token_exists = GOOGLE_TOKEN.exists()
    except OSError as exc:
        return None, f"Google OAuth token is not accessible: {exc}"
    if not google_token_exists:
        return None, "Google OAuth token not found"
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), scopes=scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds.valid:
            return None, "Google OAuth token is invalid"
        return creds, None
    except Exception as exc:
        return None, str(exc)


def clean_snippet(text: str | None, limit: int = 180) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", str(text)).strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def epoch_to_iso(value):
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except Exception:
        return None


def parse_iso(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return dt
    except Exception:
        return None


def calendar_sort_key(item: dict):
    dt = parse_iso(item.get("start")) if isinstance(item, dict) else None
    return dt or datetime.max.replace(tzinfo=datetime.now().astimezone().tzinfo)


def calendar_payload(items, source: str, auth: str, *, days: int = 7, error: str | None = None, calendar: str | None = None, fallback_available: bool | None = None):
    """Normalize calendar responses for the Today preview and 7-day agenda."""
    safe_items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    safe_items = sorted(safe_items, key=calendar_sort_key)
    now = datetime.now().astimezone()
    window_end = now + timedelta(days=days)
    today = now.date()
    today_count = 0
    next_event = None
    dated_count = 0
    for item in safe_items:
        start_dt = parse_iso(item.get("start"))
        if start_dt:
            dated_count += 1
        if start_dt and start_dt.date() == today:
            today_count += 1
        if start_dt and start_dt >= now and next_event is None:
            next_event = {"title": item.get("title") or "Untitled event", "start": item.get("start"), "type": item.get("type") or source}

    local_updated = file_mtime_iso(DATA_DIR / "calendar.json")
    local_updated_dt = parse_iso(local_updated)
    local_stale = source == "local" and (
        local_updated_dt is None
        or local_updated_dt < now - timedelta(hours=24)
        or dated_count == 0
    )

    payload = {
        "items": safe_items,
        "source": source,
        "auth": auth,
        "calendar": calendar,
        "range_days": days,
        "updated_at": now_iso(),
        "data_updated_at": local_updated if source == "local" else None,
        "read_only": True,
        "window": {
            "start": now.isoformat(timespec="seconds"),
            "end": window_end.isoformat(timespec="seconds"),
            "label": f"Today + next {days - 1} days" if days > 1 else "Today",
        },
        "summary": {
            "count": len(safe_items),
            "today_count": today_count,
            "next_event": next_event,
            "fallback_available": bool(fallback_available) if fallback_available is not None else bool(read_json_file("calendar.json", [])),
            "stale": local_stale,
        },
    }
    if error:
        payload["error"] = clean_snippet(error, 240)
    return payload


def calendar_cache_key(days: int, limit: int):
    return {
        "days": days,
        "limit": limit,
        "token_mtime": file_mtime_iso(GOOGLE_TOKEN),
    }


def copy_calendar_payload(payload: dict, *, cached: bool, fetched_at: datetime | None = None) -> dict:
    clone = json.loads(json.dumps(payload, default=str))
    fetched = fetched_at or datetime.now(timezone.utc)
    clone["cache"] = {
        "enabled": True,
        "cached": cached,
        "ttl_seconds": CALENDAR_CACHE_TTL_SECONDS,
        "fetched_at": fetched.astimezone().isoformat(timespec="seconds"),
    }
    return clone


def cached_calendar_payload(key: dict) -> dict | None:
    fetched_at = CALENDAR_CACHE.get("fetched_at")
    payload = CALENDAR_CACHE.get("payload")
    if CALENDAR_CACHE.get("key") != key or payload is None or fetched_at is None:
        return None
    age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
    if age >= CALENDAR_CACHE_TTL_SECONDS:
        return None
    return copy_calendar_payload(payload, cached=True, fetched_at=fetched_at)


def store_calendar_cache(key: dict, payload: dict) -> dict:
    fetched_at = datetime.now(timezone.utc)
    CALENDAR_CACHE["key"] = key
    CALENDAR_CACHE["payload"] = json.loads(json.dumps(payload, default=str))
    CALENDAR_CACHE["fetched_at"] = fetched_at
    return copy_calendar_payload(payload, cached=False, fetched_at=fetched_at)


def google_calendar_events(days: int = 7, limit: int = 50):
    """Read upcoming Google Calendar events with local JSON fallback metadata."""
    scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    fallback = read_json_file("calendar.json", [])
    fallback_available = bool(fallback)
    cache_key = calendar_cache_key(days, limit)
    cached = cached_calendar_payload(cache_key)
    if cached:
        return cached

    creds, auth_error = google_credentials(scopes)
    if creds is None:
        return calendar_payload(fallback, "local", "not_connected", days=days, error=auth_error, fallback_available=fallback_available)

    try:
        from googleapiclient.discovery import build

        start = datetime.now(timezone.utc)
        end = start + timedelta(days=days)
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        response = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=start.isoformat().replace("+00:00", "Z"),
                timeMax=end.isoformat().replace("+00:00", "Z"),
                singleEvents=True,
                orderBy="startTime",
                maxResults=limit,
            )
            .execute()
        )
        items = []
        for event in response.get("items", []):
            start_value = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            end_value = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
            items.append(
                {
                    "id": event.get("id"),
                    "title": event.get("summary") or "Untitled event",
                    "start": start_value,
                    "end": end_value,
                    "type": "google",
                    "description": clean_snippet(event.get("description"), 180),
                    "location": event.get("location") or "",
                    "status": event.get("status"),
                    "htmlLink": event.get("htmlLink"),
                }
            )
        payload = calendar_payload(items, "google", "connected", days=days, calendar="primary", fallback_available=fallback_available)
        return store_calendar_cache(cache_key, payload)
    except Exception:
        return calendar_payload(
            fallback,
            "local",
            "error",
            days=days,
            error="Google Calendar could not be refreshed; showing the local fallback.",
            fallback_available=fallback_available,
        )


def hermes_config():
    """Return a small public-safe summary without parsing raw credential config."""
    try:
        config_exists = CONFIG_PATH.exists()
    except OSError:
        return {"exists": None, "summary": {}, "masked_config": "", "error": "Hermes configuration could not be inspected."}
    if not config_exists:
        return {"exists": False, "summary": {}, "masked_config": ""}
    try:
        discovery = hermes_profiles_payload()
        if discovery.get("status") != "available":
            return {
                "exists": True,
                "size": human_bytes(CONFIG_PATH.stat().st_size),
                "modified_at": file_mtime_iso(CONFIG_PATH),
                "summary": {},
                "masked_config": "",
                "error": "Hermes configuration summary is unavailable.",
            }
        profiles = discovery.get("profiles") or []
        default_profile = next(
            (
                profile
                for profile in profiles or []
                if isinstance(profile, dict) and (profile.get("is_default") or profile.get("id") == "default")
            ),
            None,
        )
        safe_summary = {}
        if default_profile:
            model = compact_text(default_profile.get("model"), max_length=160)
            provider = compact_text(default_profile.get("provider"), max_length=120)
            if model:
                safe_summary["default_model"] = model
            if provider:
                safe_summary["provider"] = provider
        return {
            "exists": True,
            "size": human_bytes(CONFIG_PATH.stat().st_size),
            "modified_at": file_mtime_iso(CONFIG_PATH),
            "summary": safe_summary,
            "masked_config": json.dumps(safe_summary, indent=2),
        }
    except Exception:
        return {"exists": True, "error": "Hermes configuration summary is unavailable.", "summary": {}, "masked_config": ""}


def fts_query(query: str) -> str | None:
    terms = re.findall(r"[A-Za-z0-9_]+", query or "")[:8]
    if not terms:
        return None
    return " ".join(f"{term}*" for term in terms)


def message_excerpt(content: str | None, query: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", content or "").strip()
    if not text:
        return ""
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_]+", query or "")]
    lower = text.lower()
    hits = [lower.find(term) for term in terms if term and lower.find(term) >= 0]
    start = max(0, min(hits) - 80) if hits else 0
    excerpt = text[start : start + limit]
    if start > 0:
        excerpt = "…" + excerpt
    if start + limit < len(text):
        excerpt += "…"
    return excerpt


def search_messages(query: str, limit: int = 20):
    query = clean_snippet(query, 120)
    if len(query.strip()) < 2:
        return {"query": query, "results": [], "count": 0, "source": str(STATE_DB)}
    if not STATE_DB.exists():
        return {"query": query, "results": [], "count": 0, "source": str(STATE_DB), "error": "Hermes state.db not found"}

    try:
        con = sqlite_connect()
        if con is None:
            return {"query": query, "results": [], "count": 0, "source": str(STATE_DB), "error": "Hermes state.db unavailable"}
        con.row_factory = sqlite3.Row
        table_rows = con.execute("select name from sqlite_master where type in ('table','virtual table')").fetchall()
        tables = {row["name"] for row in table_rows}
        rows = []
        fts = fts_query(query)
        if "messages_fts" in tables and fts:
            try:
                rows = con.execute(
                    """
                    select m.id as message_id, m.session_id, m.role, m.content, m.timestamp,
                           s.title, s.source, s.model
                    from messages_fts
                    join messages m on messages_fts.rowid = m.id
                    join sessions s on s.id = m.session_id
                    where messages_fts match ?
                      and coalesce(m.active, 1) = 1
                      and length(trim(coalesce(m.content, ''))) > 0
                      and coalesce(s.archived, 0) = 0
                      and m.role in ('user', 'assistant')
                      and (m.role != 'assistant' or length(trim(coalesce(m.content, ''))) > 0)
                    order by bm25(messages_fts)
                    limit ?
                    """,
                    (fts, limit),
                ).fetchall()
            except sqlite3.Error:
                rows = []

        if not rows:
            like = f"%{query}%"
            rows = con.execute(
                """
                select m.id as message_id, m.session_id, m.role, m.content, m.timestamp,
                       s.title, s.source, s.model
                from messages m
                join sessions s on s.id = m.session_id
                where m.content like ?
                  and coalesce(m.active, 1) = 1
                  and length(trim(coalesce(m.content, ''))) > 0
                  and coalesce(s.archived, 0) = 0
                  and m.role in ('user', 'assistant')
                      and (m.role != 'assistant' or length(trim(coalesce(m.content, ''))) > 0)
                order by m.timestamp desc
                limit ?
                """,
                (like, limit),
            ).fetchall()
        con.close()
        results = [
            {
                "message_id": row["message_id"],
                "session_id": row["session_id"],
                "title": row["title"] or "Untitled session",
                "source": row["source"],
                "model": row["model"],
                "role": row["role"],
                "timestamp": epoch_to_iso(row["timestamp"]),
                "snippet": message_excerpt(row["content"], query),
            }
            for row in rows
        ]
        return {"query": query, "results": results, "count": len(results), "source": str(STATE_DB)}
    except Exception as exc:
        return {"query": query, "results": [], "count": 0, "source": str(STATE_DB), "error": str(exc)}


def cron_schedule_display(job: dict) -> str:
    display = compact_text(job.get("schedule_display"), max_length=200)
    if display:
        return display
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        for key in ("display", "value", "expr", "run_at"):
            display = compact_text(schedule.get(key), max_length=200)
            if display:
                return display
        kind = compact_text(schedule.get("kind"), max_length=40).lower()
        seconds = schedule.get("seconds")
        if kind == "interval" and isinstance(seconds, (int, float)) and seconds > 0:
            return f"every {seconds:g}s"
        return kind or "unknown"
    return compact_text(
        schedule or job.get("cron") or job.get("interval"),
        max_length=200,
    ) or "unknown"


def cron_job_revision(job: dict) -> str:
    canonical = json.dumps(job, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_cron_jobs():
    try:
        cron_jobs_exists = CRON_JOBS.exists()
    except OSError as exc:
        return {
            "exists": None,
            "source": str(CRON_JOBS),
            "error": str(exc),
            "count": 0,
            "enabled_count": 0,
            "jobs": [],
        }
    if not cron_jobs_exists:
        return {
            "exists": False,
            "source": str(CRON_JOBS),
            "count": 0,
            "enabled_count": 0,
            "jobs": [],
        }
    try:
        raw = json.loads(CRON_JOBS.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "exists": True,
            "source": str(CRON_JOBS),
            "error": str(exc),
            "count": 0,
            "enabled_count": 0,
            "jobs": [],
        }

    if isinstance(raw, dict):
        jobs = raw.get("jobs") or raw.get("data") or []
    elif isinstance(raw, list):
        jobs = raw
    else:
        jobs = []

    normalized = []
    for idx, job in enumerate(jobs):
        if not isinstance(job, dict):
            continue
        enabled = bool(job.get("enabled", not job.get("disabled", False)))
        normalized.append(
            {
                "id": job.get("id") or job.get("job_id") or f"cron_{idx}",
                "name": job.get("name") or job.get("title") or "Untitled cron job",
                "schedule": cron_schedule_display(job),
                "enabled": enabled,
                "last_run": job.get("last_run") or job.get("lastRunAt") or job.get("last_run_at"),
                "next_run": job.get("next_run") or job.get("nextRunAt") or job.get("next_run_at"),
                "last_status": job.get("last_status") or job.get("status") or job.get("lastStatus") or "unknown",
                "configuration_revision": cron_job_revision(job),
            }
        )
    return {
        "exists": True,
        "source": str(CRON_JOBS),
        "count": len(normalized),
        "enabled_count": sum(1 for j in normalized if j["enabled"]),
        "jobs": normalized,
    }


CRON_QUEUE_UNAVAILABLE = (
    "This Hermes runtime does not expose an atomic queue operation that can "
    "reject disabled or changed jobs. Cron inventory remains read-only."
)


def cron_jobs_payload():
    """Expose cron inventory while failing closed on unsupported mutations."""
    payload = read_cron_jobs()
    return {
        **payload,
        "capabilities": {"crons.queue_enabled": False},
        "queue_error": CRON_QUEUE_UNAVAILABLE,
    }


def preview_cron_trigger(job_id: str, payload=None):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", job_id or ""):
        return {"error": "Invalid cron job id"}, 400
    return {
        "error": CRON_QUEUE_UNAVAILABLE,
        "error_code": "atomic_queue_unsupported",
        "capabilities": {"crons.queue_enabled": False},
    }, 503


def trigger_confirmed_cron(job_id: str, payload):
    if not isinstance(payload, dict) or payload.get("confirmed") is not True:
        return {"error": "Cron triggering requires explicit confirmation."}, 400
    if not compact_text(payload.get("confirmation_id"), max_length=80):
        return {"error": "Cron triggering requires a confirmation_id from preview."}, 400
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", job_id or ""):
        return {"error": "Invalid cron job id"}, 400
    return {
        "error": CRON_QUEUE_UNAVAILABLE,
        "error_code": "atomic_queue_unsupported",
        "capabilities": {"crons.queue_enabled": False},
    }, 503


def sqlite_connect():
    if not STATE_DB.exists():
        return None
    uri = f"file:{STATE_DB.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def safe_json_loads(text: str | None, fallback=None):
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


def tool_action_category(tool_name: str, arguments: dict | None = None) -> str:
    name = (tool_name or "tool").lower()
    args = arguments or {}
    command = str(args.get("command") or "").lower()
    if name == "terminal" and any(token in command for token in ["test", "unittest", "pytest", "node --check", "py_compile", "curl", "health"]):
        return "verification"
    if name in {"terminal", "process"}:
        return "terminal"
    if name in {"patch", "write_file", "skill_manage"}:
        return "file-change"
    if name in {"read_file", "search_files", "skill_view"}:
        return "inspection"
    if name.startswith("browser"):
        return "browser"
    if name.startswith("web") or name in {"session_search"}:
        return "research"
    if name in {"todo", "memory"}:
        return "planning"
    if name in {"image_generate", "vision_analyze"}:
        return "media"
    return "tool"


def tool_action_detail(tool_name: str, arguments: dict | None = None) -> str:
    args = arguments or {}
    name = tool_name or "tool"
    if name == "terminal":
        return clean_snippet(args.get("command"), 220) or "Ran a shell command"
    if name in {"read_file", "write_file", "patch"}:
        return clean_snippet(args.get("path") or args.get("file_path") or args.get("mode"), 220) or f"Used {name}"
    if name == "search_files":
        pattern = args.get("pattern") or ""
        path = args.get("path") or ""
        return clean_snippet(f"{pattern} in {path}".strip(), 220) or "Searched project files"
    if name.startswith("browser"):
        return clean_snippet(args.get("url") or args.get("question") or args.get("ref"), 220) or "Used the browser"
    if name.startswith("web"):
        return clean_snippet(args.get("query") or ", ".join(args.get("urls") or []), 220) or "Used web tools"
    if name == "todo":
        todos = args.get("todos") or []
        return clean_snippet(f"Updated {len(todos)} checklist item(s)", 220) if todos else "Read the active checklist"
    if name == "skill_view":
        return clean_snippet(args.get("name"), 220) or "Loaded a skill"
    return clean_snippet(json.dumps(args, ensure_ascii=False), 220) if args else f"Used {name}"


def tool_result_status(content: str | None) -> tuple[str, str]:
    if not content:
        return "unknown", "No tool output captured."
    parsed = safe_json_loads(content, None)
    if isinstance(parsed, dict):
        if parsed.get("success") is False or parsed.get("ok") is False:
            return "error", clean_snippet(parsed.get("error") or parsed.get("message") or content, 220)
        if parsed.get("exit_code") not in (None, 0):
            return "error", clean_snippet(parsed.get("error") or parsed.get("output") or content, 220)
        if parsed.get("error"):
            return "error", clean_snippet(parsed.get("error"), 220)
        output = parsed.get("output") or parsed.get("content") or parsed.get("summary") or content
        return "ok", clean_snippet(output, 220)
    lowered = content.lower()
    if any(token in lowered for token in ["traceback", "exception", "returned 500", "exit_code\": 1", "failed", "error:"]):
        return "error", clean_snippet(content, 220)
    return "ok", clean_snippet(content, 220)


def extract_tool_calls(raw_tool_calls: str | None) -> list[dict]:
    parsed = safe_json_loads(raw_tool_calls, [])
    if not isinstance(parsed, list):
        return []
    calls = []
    for call in parsed:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        name = function.get("name") or call.get("name") or "tool"
        args = safe_json_loads(function.get("arguments") or call.get("arguments"), {})
        if not isinstance(args, dict):
            args = {}
        call_id = call.get("call_id") or call.get("id") or call.get("tool_call_id")
        calls.append({"id": call_id, "tool": name, "arguments": args})
    return calls


def infer_run_status(session: sqlite3.Row, final_text: str, blockers: list[dict]) -> str:
    lowered = (final_text or "").lower()
    if session["ended_at"] is None:
        return "unknown"
    if any(token in lowered for token in ["done", "completed", "verified", "passed", "ok"]):
        return "completed"
    if any(token in lowered for token in ["blocked", "could not", "can't complete", "cannot complete"]):
        return "blocked"
    if any(token in lowered for token in ["failed", "failure"]):
        return "failed"
    if any(token in lowered for token in ["needs review", "review required"]):
        return "needs_review"
    if any(token in lowered for token in ["partial", "partially", "not fully"]):
        return "partial"
    if blockers:
        return "needs_review"
    return "unknown"


def infer_related_tasks(text: str, limit: int = 5) -> list[dict]:
    tasks = read_json_file("tasks.json", [])
    if not isinstance(tasks, list) or not text:
        return []
    haystack = text.lower()
    related = []
    for task in tasks:
        task_id = str(task.get("id") or "")
        title = str(task.get("title") or "")
        if task_id and task_id.lower() in haystack:
            score = 3
        else:
            words = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 3]
            score = sum(1 for word in words if word in haystack)
        if score >= 2 or (task_id and task_id.lower() in haystack):
            related.append({
                "id": task_id,
                "title": title,
                "status": task.get("status"),
                "priority": task.get("priority"),
                "score": score,
            })
    related.sort(key=lambda item: item.get("score", 0), reverse=True)
    return related[:limit]


def session_usage_summary(session: sqlite3.Row) -> dict:
    input_tokens = int(session["input_tokens"] or 0)
    output_tokens = int(session["output_tokens"] or 0)
    total_tokens = input_tokens + output_tokens
    estimated_cost = session["estimated_cost_usd"]
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": estimated_cost,
    }


def build_session_replay(session: sqlite3.Row, rows: list[sqlite3.Row]) -> dict:
    messages = [dict(row) for row in rows]
    user_messages = [m for m in messages if m.get("role") == "user" and clean_snippet(m.get("content"), 240)]
    assistant_messages = [m for m in messages if m.get("role") == "assistant" and clean_snippet(m.get("content"), 240)]
    first_intent = clean_snippet(user_messages[0].get("content"), 320) if user_messages else "No initiating user message captured."
    steering = [clean_snippet(m.get("content"), 220) for m in user_messages[1:4]]

    actions_by_call_id: dict[str, dict] = {}
    actions: list[dict] = []
    files: dict[str, dict] = {}
    verification: list[dict] = []
    all_text_parts = [session["title"] or "", first_intent]

    for message in messages:
        role = message.get("role")
        content = message.get("content") or ""
        if content:
            all_text_parts.append(content[:1200])
        if role == "assistant":
            for call in extract_tool_calls(message.get("tool_calls")):
                tool = call["tool"]
                args = call["arguments"]
                category = tool_action_category(tool, args)
                action = {
                    "id": call.get("id") or f"action-{len(actions) + 1}",
                    "tool": tool,
                    "category": category,
                    "title": tool.replace("_", " ").replace(".", " / ").title(),
                    "detail": tool_action_detail(tool, args),
                    "timestamp": epoch_to_iso(message.get("timestamp")),
                    "status": "pending",
                    "result": "Waiting for result in transcript window.",
                }
                actions.append(action)
                if action["id"]:
                    actions_by_call_id[action["id"]] = action
                path = args.get("path") or args.get("file_path")
                if isinstance(path, str) and path:
                    mode = "changed" if category == "file-change" else "read"
                    files[path] = {"path": path, "mode": mode, "tool": tool}
                if category == "verification":
                    verification.append(action)
        elif role == "tool":
            action = actions_by_call_id.get(message.get("tool_call_id") or "")
            status, result = tool_result_status(content)
            if action:
                action["status"] = status
                action["result"] = result
                if action["category"] == "verification" and action not in verification:
                    verification.append(action)

    for action in actions:
        if action["status"] == "pending":
            action["status"] = "unknown"

    blockers = [
        {
            "title": action["title"],
            "detail": action["detail"],
            "result": action["result"],
            "timestamp": action["timestamp"],
        }
        for action in actions
        if action.get("status") == "error"
    ][:8]
    for message in messages:
        content = message.get("content") or ""
        lowered = content.lower()
        if message.get("role") == "assistant" and any(token in lowered for token in ["blocked", "failed", "traceback", "error:", "could not", "stale server"]):
            blockers.append({
                "title": f"{message.get('role', 'message').title()} noted a blocker",
                "detail": clean_snippet(content, 260),
                "result": "Mentioned in conversation text.",
                "timestamp": epoch_to_iso(message.get("timestamp")),
            })
            if len(blockers) >= 8:
                break

    outcome_candidates = [clean_snippet(m.get("content"), 480) for m in assistant_messages]
    substantive_outcomes = [
        text for text in outcome_candidates
        if len(text) > 160 or any(token in text.lower() for token in ["done", "completed", "verified", "passed", "blocked", "failed"])
    ]
    final_text = substantive_outcomes[-1] if substantive_outcomes else (outcome_candidates[-1] if outcome_candidates else "No final assistant outcome captured yet.")
    status = infer_run_status(session, final_text, blockers)
    related_tasks = infer_related_tasks("\n".join(all_text_parts))
    action_counts: dict[str, int] = {}
    for action in actions:
        action_counts[action["category"]] = action_counts.get(action["category"], 0) + 1

    return {
        "status": status,
        "purpose": "review_debugging",
        "read_only": True,
        "summary": {
            "title": session["title"] or "Untitled session",
            "source": session["source"],
            "model": session["model"],
            "started_at": epoch_to_iso(session["started_at"]),
            "ended_at": epoch_to_iso(session["ended_at"]),
            "message_count": session["message_count"],
            "tool_call_count": session["tool_call_count"],
            "usage": session_usage_summary(session),
            "actions_detected": len(actions),
            "blockers_detected": len(blockers),
        },
        "user_intent": {
            "initial": first_intent,
            "steering": steering,
        },
        "actions": actions[:80],
        "action_counts": action_counts,
        "blockers": blockers,
        "outcome": {
            "status": status,
            "summary": final_text,
        },
        "files": list(files.values())[:40],
        "verification": verification[:12],
        "related_tasks": related_tasks,
        "suggestions": [
            "Review inferred status before updating any task state.",
            "Use this replay as a read-only trace; task write-back can come later behind an explicit action.",
        ],
    }


def session_replay(session_id: str, _target_message_id: str | None = None):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", session_id or ""):
        return {"error": "Invalid session id"}, 400
    if not STATE_DB.exists():
        return {"error": "Hermes state.db not found", "source": str(STATE_DB)}, 404
    cache_key = ("replay", str(STATE_DB.resolve()), file_mtime_iso(STATE_DB), session_id)
    cached = SESSION_REPLAY_CACHE.get(cache_key)
    if cached:
        payload, status = cached
        return json.loads(json.dumps(payload, default=str)), status
    try:
        con = sqlite_connect()
        if con is None:
            return {"error": "Hermes state.db not available", "source": str(STATE_DB)}, 404
        con.row_factory = sqlite3.Row
        session = con.execute(
            """
            select id, title, source, model, started_at, ended_at,
                   message_count, tool_call_count, input_tokens, output_tokens,
                   estimated_cost_usd
            from sessions
            where id = ? and coalesce(archived, 0) = 0
            """,
            (session_id,),
        ).fetchone()
        if session is None:
            con.close()
            return {"error": f"Session not found: {session_id}"}, 404
        rows = con.execute(
            """
            select id, role, content, tool_name, tool_call_id, tool_calls, timestamp, finish_reason
            from messages
            where session_id = ?
              and coalesce(active, 1) = 1
            order by id asc
            limit 1000
            """,
            (session_id,),
        ).fetchall()
        con.close()
        replay = build_session_replay(session, rows)
        payload = {"session_id": session_id, "source": str(STATE_DB), "replay": replay}
        SESSION_REPLAY_CACHE[cache_key] = (json.loads(json.dumps(payload, default=str)), 200)
        return payload, 200
    except Exception as exc:
        return {"error": str(exc), "source": str(STATE_DB)}, 500


def recent_sessions(limit: int = 8):
    try:
        state_db_exists = STATE_DB.exists()
    except OSError as exc:
        return {"exists": None, "source": str(STATE_DB), "sessions": [], "error": str(exc)}
    if not state_db_exists:
        return {"exists": False, "source": str(STATE_DB), "sessions": []}
    try:
        con = sqlite_connect()
        if con is None:
            return {"exists": False, "source": str(STATE_DB), "sessions": []}
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            select id, title, source, model, started_at, ended_at,
                   message_count, tool_call_count, input_tokens, output_tokens,
                   estimated_cost_usd, archived
            from sessions
            where coalesce(archived, 0) = 0
            order by coalesce(ended_at, started_at, 0) desc
            limit ?
            """,
            (limit,),
        ).fetchall()
        con.close()
        return {
            "exists": True,
            "source": str(STATE_DB),
            "sessions": [
                {
                    "id": r["id"],
                    "title": r["title"] or "Untitled session",
                    "source": r["source"],
                    "model": r["model"],
                    "started_at": epoch_to_iso(r["started_at"]),
                    "ended_at": epoch_to_iso(r["ended_at"]),
                    "message_count": r["message_count"],
                    "tool_call_count": r["tool_call_count"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                    "estimated_cost_usd": r["estimated_cost_usd"],
                }
                for r in rows
            ],
        }
    except Exception as exc:
        return {"exists": True, "source": str(STATE_DB), "error": str(exc), "sessions": []}


def session_detail(session_id: str, target_message_id: str | None = None):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", session_id or ""):
        return {"error": "Invalid session id"}, 400
    if target_message_id and not re.fullmatch(r"\d+", str(target_message_id)):
        return {"error": "Invalid target message id"}, 400
    if not STATE_DB.exists():
        return {"error": "Hermes state.db not found", "source": str(STATE_DB)}, 404

    cache_key = ("detail", str(STATE_DB.resolve()), file_mtime_iso(STATE_DB), session_id, str(target_message_id or ""))
    cached = SESSION_DETAIL_CACHE.get(cache_key)
    if cached:
        payload, status = cached
        return json.loads(json.dumps(payload, default=str)), status

    try:
        con = sqlite_connect()
        if con is None:
            return {"error": "Hermes state.db not available", "source": str(STATE_DB)}, 404
        con.row_factory = sqlite3.Row
        session = con.execute(
            """
            select id, title, source, model, started_at, ended_at,
                   message_count, tool_call_count, input_tokens, output_tokens,
                   estimated_cost_usd
            from sessions
            where id = ? and coalesce(archived, 0) = 0
            """,
            (session_id,),
        ).fetchone()
        if session is None:
            con.close()
            return {"error": f"Session not found: {session_id}"}, 404

        total_visible = con.execute(
            """
            select count(*)
            from messages
            where session_id = ?
              and coalesce(active, 1) = 1
              and role in ('user', 'assistant')
              and (role != 'assistant' or length(trim(coalesce(content, ''))) > 0)
            """,
            (session_id,),
        ).fetchone()[0]

        target_id = int(target_message_id) if target_message_id else None
        target_found = False
        if target_id:
            before = con.execute(
                """
                select id, role, content, tool_name, timestamp, token_count, finish_reason
                from messages
                where session_id = ?
                  and coalesce(active, 1) = 1
                  and role in ('user', 'assistant')
              and (role != 'assistant' or length(trim(coalesce(content, ''))) > 0)
                  and id <= ?
                order by id desc
                limit 160
                """,
                (session_id, target_id),
            ).fetchall()
            after = con.execute(
                """
                select id, role, content, tool_name, timestamp, token_count, finish_reason
                from messages
                where session_id = ?
                  and coalesce(active, 1) = 1
                  and role in ('user', 'assistant')
              and (role != 'assistant' or length(trim(coalesce(content, ''))) > 0)
                  and id > ?
                order by id asc
                limit 220
                """,
                (session_id, target_id),
            ).fetchall()
            rows = list(reversed(before)) + list(after)
            target_found = any(row["id"] == target_id for row in rows)
        else:
            rows = con.execute(
                """
                select id, role, content, tool_name, timestamp, token_count, finish_reason
                from messages
                where session_id = ?
                  and coalesce(active, 1) = 1
                  and role in ('user', 'assistant')
              and (role != 'assistant' or length(trim(coalesce(content, ''))) > 0)
                order by id asc
                limit 500
                """,
                (session_id,),
            ).fetchall()

        if target_id and not target_found:
            rows = con.execute(
                """
                select id, role, content, tool_name, timestamp, token_count, finish_reason
                from messages
                where session_id = ?
                  and coalesce(active, 1) = 1
                  and role in ('user', 'assistant')
              and (role != 'assistant' or length(trim(coalesce(content, ''))) > 0)
                order by id asc
                limit 500
                """,
                (session_id,),
            ).fetchall()

        con.close()
        payload = {
            "session": {
                "id": session["id"],
                "title": session["title"] or "Untitled session",
                "source": session["source"],
                "model": session["model"],
                "started_at": epoch_to_iso(session["started_at"]),
                "ended_at": epoch_to_iso(session["ended_at"]),
                "message_count": session["message_count"],
                "tool_call_count": session["tool_call_count"],
                "input_tokens": session["input_tokens"],
                "output_tokens": session["output_tokens"],
                "estimated_cost_usd": session["estimated_cost_usd"],
            },
            "message_window": {
                "mode": "around_target" if target_id and target_found else "from_start",
                "target_message_id": target_id if target_found else None,
                "returned": len(rows),
                "total_visible": total_visible,
                "truncated": len(rows) < total_visible,
            },
            "messages": [
                {
                    "id": row["id"],
                    "role": row["role"],
                    "content": row["content"] or "",
                    "tool_name": row["tool_name"],
                    "timestamp": epoch_to_iso(row["timestamp"]),
                    "token_count": row["token_count"],
                    "finish_reason": row["finish_reason"],
                }
                for row in rows
            ],
        }
        SESSION_DETAIL_CACHE[cache_key] = (json.loads(json.dumps(payload, default=str)), 200)
        return payload, 200
    except Exception as exc:
        return {"error": str(exc), "source": str(STATE_DB)}, 500


def obsidian_notes():
    notes = []
    if not OBSIDIAN_VAULT.exists():
        return {"vault": str(OBSIDIAN_VAULT), "exists": False, "note_count": 0, "notes": notes, "cache": {"enabled": True, "cached": False}}

    vault_root = OBSIDIAN_VAULT.resolve()
    markdown_files = []
    for candidate in OBSIDIAN_VAULT.rglob("*.md"):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if candidate.is_symlink() or (resolved != vault_root and vault_root not in resolved.parents):
            continue
        markdown_files.append(candidate)
    markdown_files.sort(key=note_sort_key, reverse=True)
    signature = tuple((path.relative_to(OBSIDIAN_VAULT).as_posix(), path.stat().st_mtime_ns, path.stat().st_size) for path in markdown_files)
    cache_key = (str(OBSIDIAN_VAULT.resolve()), signature)
    if OBSIDIAN_NOTES_CACHE.get("key") == cache_key and OBSIDIAN_NOTES_CACHE.get("payload") is not None:
        cached = json.loads(json.dumps(OBSIDIAN_NOTES_CACHE["payload"], default=str))
        cached["cache"] = {"enabled": True, "cached": True, "strategy": "vault file mtime/size signature"}
        return cached

    for path in markdown_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        excerpt = clean_snippet(re.sub(r"[#>*`\-\[\]()_]", " ", text), 260)
        relative_path = path.relative_to(OBSIDIAN_VAULT).as_posix()
        notes.append(
            {
                "name": path.name,
                "title": path.stem,
                "exists": True,
                "path": str(path),
                "relative_path": relative_path,
                "modified_at": file_mtime_iso(path),
                "size": human_bytes(path.stat().st_size),
                "excerpt": excerpt,
            }
        )
    payload = {
        "vault": str(OBSIDIAN_VAULT),
        "exists": True,
        "note_count": len(notes),
        "returned_count": len(notes),
        "notes": notes,
        "cache": {"enabled": True, "cached": False, "strategy": "vault file mtime/size signature"},
    }
    OBSIDIAN_NOTES_CACHE["key"] = cache_key
    OBSIDIAN_NOTES_CACHE["payload"] = json.loads(json.dumps(payload, default=str))
    return payload


def health_context() -> HealthContext:
    return HealthContext(
        base_dir=BASE_DIR,
        hermes_home=HERMES_HOME,
        state_db=STATE_DB,
        sqlite_connect=sqlite_connect,
        hermes_config=hermes_config,
        read_cron_jobs=read_cron_jobs,
        google_calendar_events=google_calendar_events,
        now_iso=now_iso,
        file_mtime_iso=file_mtime_iso,
        human_bytes=human_bytes,
        clean_snippet=clean_snippet,
    )


def health():
    return build_health_payload(health_context())



def task_status_area(task: dict) -> str:
    status = str(task.get("status") or "").strip().lower().replace("_", " ")
    if status == "completed":
        return "completed"
    if status == "in progress":
        return "in progress"
    if status == "waiting":
        return "waiting"
    if status == "needs attention":
        return "needs attention"
    return "todo"


def task_has_attention_tag(task: dict) -> bool:
    tags = task.get("tags")
    if not isinstance(tags, list):
        return False
    return any(str(tag).strip().lower().replace("_", " ") == "needs attention" for tag in tags)


def task_needs_attention(task: dict) -> bool:
    if not isinstance(task, dict):
        return False
    if task_status_area(task) == "completed":
        return False
    return bool(task.get("needs_attention")) or bool(task.get("review_required")) or task_status_area(task) == "needs attention" or task_has_attention_tag(task)


def task_attention_items(tasks) -> list[dict]:
    if not isinstance(tasks, list):
        return []
    items = []
    for task in tasks:
        if not task_needs_attention(task):
            continue
        task_id = str(task.get("id") or task.get("title") or "untitled")
        priority = str(task.get("priority") or "medium").lower()
        items.append(
            {
                "id": f"task:{task_id}",
                "task_id": task_id,
                "title": task.get("title") or "Untitled task",
                "description": task.get("description") or "Task is tagged as needing attention.",
                "type": "task_needs_attention",
                "source": "task",
                "project": task.get("project") or "General",
                "severity": "high" if priority == "high" else "medium",
                "status": "open",
                "created_at": task.get("updated_at") or task.get("created_at") or now_iso(),
                "link": task_id,
                "tags": task.get("tags") if isinstance(task.get("tags"), list) else [],
            }
        )
    return items


def open_attention_items(attention=None, tasks=None) -> list[dict]:
    if attention is None:
        attention = read_json_file("attention.json", [])
    if tasks is None:
        tasks = read_json_file("tasks.json", [])
    manual = [a for a in attention if isinstance(a, dict) and a.get("status", "open") == "open"] if isinstance(attention, list) else []
    return manual + task_attention_items(tasks)


def attention_payload():
    return {"attention": open_attention_items()}


def overview():
    projects = read_json_file("projects.json", [])
    tasks = read_json_file("tasks.json", [])
    attention = read_json_file("attention.json", [])
    crons = read_cron_jobs()
    sessions = recent_sessions(limit=5)
    dashboard = read_json_file("dashboard.json", {})

    if not isinstance(dashboard, dict):
        dashboard = {}

    greeting_name = clean_snippet(
        CONFIG_DISPLAY_NAME
        or dashboard.get("display_name")
        or "Operator",
        40,
    ) or "Operator"
    app_name = clean_snippet(
        CONFIG_APP_NAME
        or dashboard.get("app_name")
        or DEFAULT_APP_NAME,
        40,
    ) or DEFAULT_APP_NAME
    greeting_prefix = clean_snippet(
        CONFIG_GREETING_PREFIX
        or dashboard.get("greeting_prefix")
        or "Hello",
        16,
    ) or "Hello"

    open_attention = open_attention_items(attention, tasks)
    active_tasks = [t for t in tasks if isinstance(t, dict) and task_status_area(t) != "completed"] if isinstance(tasks, list) else []
    active_projects = [p for p in projects if isinstance(p, dict) and str(p.get("status") or "").strip().lower() == "active"] if isinstance(projects, list) else []
    week_ago = datetime.now().astimezone() - timedelta(days=7)
    completed_this_week = []
    if isinstance(tasks, list):
        for task in tasks:
            completed_at = parse_iso(task.get("completed_at"))
            if task.get("status") == "completed" and completed_at and completed_at >= week_ago:
                completed_this_week.append(task)

    return {
        "generated_at": now_iso(),
        "identity": {
            "display_name": greeting_name,
            "greeting_prefix": greeting_prefix,
            "app_name": app_name,
        },
        "cards": {
            "needs_attention": len(open_attention),
            "active_tasks": len(active_tasks),
            "completed_this_week": len(completed_this_week),
            "scheduled_crons": crons.get("count", 0),
            "recent_sessions": len(sessions.get("sessions", [])),
            "active_projects": len(active_projects),
        },
    }


def resolve_attention_item(attention_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", attention_id or ""):
        return {"error": "Invalid attention item id"}, 400

    def mutator(attention):
        if not isinstance(attention, list):
            return attention, ({"error": "attention.json must contain a list"}, 500)

        next_attention = [dict(item) if isinstance(item, dict) else item for item in attention]
        resolved_item = None
        for item in next_attention:
            if not isinstance(item, dict):
                continue
            if item.get("id") == attention_id:
                item["status"] = "resolved"
                item["resolved_at"] = now_iso()
                resolved_item = item
                break

        if resolved_item is None:
            return attention, ({"error": f"Attention item not found: {attention_id}"}, 404)

        tasks = read_json_file("tasks.json", [])
        return next_attention, ({"ok": True, "resolved": resolved_item, "attention": next_attention, "open_count": len(open_attention_items(next_attention, tasks))}, 200)

    return update_json_file("attention.json", [], mutator)


def create_task(payload):
    def mutator(tasks):
        if not isinstance(tasks, list):
            return tasks, ({"error": "tasks.json must contain a list"}, 500)
        normalized, error = validate_task_payload(payload)
        if error:
            return tasks, ({"error": error}, 400)
        next_tasks = [task for task in tasks if isinstance(task, dict)]
        next_tasks.append(normalized)
        return next_tasks, ({"ok": True, "task": normalized, "tasks": next_tasks}, 201)

    return update_json_file("tasks.json", [], mutator)


def update_task(task_id: str, payload):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", task_id or ""):
        return {"error": "Invalid task id"}, 400

    def mutator(tasks):
        if not isinstance(tasks, list):
            return tasks, ({"error": "tasks.json must contain a list"}, 500)
        next_tasks = [task for task in tasks if isinstance(task, dict)]
        for index, task in enumerate(next_tasks):
            if str(task.get("id") or "") != task_id:
                continue
            normalized, error = validate_task_payload(payload, existing=task)
            if error:
                return tasks, ({"error": error}, 400)
            next_tasks[index] = normalized
            return next_tasks, ({"ok": True, "task": normalized, "tasks": next_tasks}, 200)
        return tasks, ({"error": f"Task not found: {task_id}"}, 404)

    return update_json_file("tasks.json", [], mutator)


def _task_delete_confirmation(task: dict) -> str:
    bound = json.dumps(task, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "task_delete_" + hashlib.sha256(bound.encode("utf-8")).hexdigest()[:24]


def preview_task_deletion(task_id: str, payload=None):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", task_id or ""):
        return {"error": "Invalid task id"}, 400
    tasks = read_json_file("tasks.json", [])
    if not isinstance(tasks, list):
        return {"error": "tasks.json must contain a list"}, 500
    matches = [
        item
        for item in tasks
        if isinstance(item, dict) and str(item.get("id") or "") == task_id
    ]
    if not matches:
        return {"error": f"Task not found: {task_id}"}, 404
    if len(matches) != 1:
        return {
            "error": "Task deletion is blocked because the task id is duplicated. Repair tasks.json before retrying."
        }, 409
    task = matches[0]
    return {
        "ok": True,
        "requires_confirmation": True,
        "confirmation_id": _task_delete_confirmation(task),
        "task": task,
        "effects": [f"Permanently remove the Mentat task '{task.get('title') or task_id}'."],
        "warnings": ["This removes project-owned task data and cannot be undone from Mentat."],
    }, 200


def delete_confirmed_task(task_id: str, payload):
    if not isinstance(payload, dict) or payload.get("confirmed") is not True:
        return {"error": "Task deletion requires explicit confirmation."}, 400
    confirmation_id = compact_text(payload.get("confirmation_id"), max_length=80)
    if not confirmation_id:
        return {"error": "Task deletion requires a confirmation_id from preview."}, 400
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", task_id or ""):
        return {"error": "Invalid task id"}, 400

    def mutator(tasks):
        if not isinstance(tasks, list):
            return tasks, ({"error": "tasks.json must contain a list"}, 500)
        matches = [
            item
            for item in tasks
            if isinstance(item, dict) and str(item.get("id") or "") == task_id
        ]
        if not matches:
            return tasks, ({"error": f"Task not found: {task_id}"}, 404)
        if len(matches) != 1:
            return tasks, ({
                "error": "Task deletion is blocked because the task id is duplicated. Repair tasks.json before retrying."
            }, 409)
        task = matches[0]
        if confirmation_id != _task_delete_confirmation(task):
            return tasks, ({"error": "Task changed after preview; preview deletion again."}, 409)
        remaining = [
            item for item in tasks
            if not (isinstance(item, dict) and str(item.get("id") or "") == task_id)
        ]
        return remaining, ({"ok": True, "deleted_task_id": task_id, "task": task, "tasks": remaining}, 200)

    return update_json_file("tasks.json", [], mutator)


def create_project(payload):
    def mutator(projects):
        if not isinstance(projects, list):
            return projects, ({"error": "projects.json must contain a list"}, 500)
        normalized, error = validate_project_payload(payload)
        if error:
            return projects, ({"error": error}, 400)
        next_projects = [project for project in projects if isinstance(project, dict)]
        name_key = normalized["name"].strip().lower()
        id_key = normalized["id"]
        for project in next_projects:
            if str(project.get("id") or "") == id_key or str(project.get("name") or "").strip().lower() == name_key:
                return projects, ({"error": f"Project already exists: {normalized['name']}"}, 409)
        next_projects.append(normalized)
        return next_projects, ({"ok": True, "project": normalized, "projects": next_projects}, 201)

    return update_json_file("projects.json", [], mutator)


def update_project(project_id: str, payload):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", project_id or ""):
        return {"error": "Invalid project id"}, 400

    def mutator(projects):
        if not isinstance(projects, list):
            return projects, ({"error": "projects.json must contain a list"}, 500)
        next_projects = [project for project in projects if isinstance(project, dict)]
        for index, project in enumerate(next_projects):
            if str(project.get("id") or "") != project_id:
                continue
            normalized, error = validate_project_payload(payload, existing=project)
            if error:
                return projects, ({"error": error}, 400)
            normalized["id"] = project_id
            name_key = normalized["name"].strip().lower()
            for other in next_projects:
                if other is project:
                    continue
                if str(other.get("name") or "").strip().lower() == name_key:
                    return projects, ({"error": f"Project already exists: {normalized['name']}"}, 409)
            next_projects[index] = normalized
            return next_projects, ({"ok": True, "project": normalized, "projects": next_projects}, 200)
        return projects, ({"error": f"Project not found: {project_id}"}, 404)

    return update_json_file("projects.json", [], mutator)


def agent_message_summary(messages: list[dict]) -> dict:
    counts = {status: 0 for status in MESSAGE_STATUS_VALUES}
    pending = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        status = normalize_message_status(message.get("status"))
        if status in counts:
            counts[status] += 1
        if status in {"queued", "needs user input"}:
            pending += 1
    counts["pending"] = pending
    counts["total"] = sum(counts[status] for status in MESSAGE_STATUS_VALUES)
    return counts


def agent_messages_payload():
    messages = read_json_file("agent_messages.json", [])
    if isinstance(messages, dict) and messages.get("error"):
        return messages
    if not isinstance(messages, list):
        return {"error": "agent_messages.json must contain a list"}
    ordered = [message for message in messages if isinstance(message, dict)]
    ordered.sort(key=lambda item: item.get("updated_at") or item.get("created_at") or "", reverse=True)
    return {
        "messages": ordered,
        "summary": agent_message_summary(ordered),
        "read_only_agent_execution": True,
        "safety": {
            "local_only": True,
            "browser_to_shell_execution": "forbidden",
            "writes": "project-owned data/agent_messages.json only",
        },
    }


def create_agent_message(payload):
    request = dict(payload or {})
    request["status"] = "queued"

    def mutator(messages):
        if not isinstance(messages, list):
            return messages, ({"error": "agent_messages.json must contain a list"}, 500)
        normalized, error = validate_agent_message_payload(request)
        if error:
            return messages, ({"error": error}, 400)
        normalized["audit"].append(message_audit_event("queued", actor=normalized.get("source") or "dashboard", note="Queued from dashboard compose surface"))
        next_messages = [message for message in messages if isinstance(message, dict)]
        next_messages.append(normalized)
        return next_messages, ({"ok": True, "message": normalized, "messages": next_messages, "summary": agent_message_summary(next_messages)}, 201)

    return update_json_file("agent_messages.json", [], mutator)


def update_agent_message_state(message_id: str, payload):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", message_id or ""):
        return {"error": "Invalid agent message id"}, 400
    requested_status = normalize_message_status((payload or {}).get("status"))
    if requested_status not in MESSAGE_STATUS_VALUES:
        return {"error": f"Invalid agent message status: {requested_status}"}, 400

    def mutator(messages):
        if not isinstance(messages, list):
            return messages, ({"error": "agent_messages.json must contain a list"}, 500)
        next_messages = [message for message in messages if isinstance(message, dict)]
        for index, message in enumerate(next_messages):
            if str(message.get("id") or "") != message_id:
                continue
            candidate = {**message, "status": requested_status}
            normalized, error = validate_agent_message_payload(candidate, existing=message)
            if error:
                return messages, ({"error": error}, 400)
            normalized["audit"].append(
                message_audit_event(
                    requested_status,
                    actor=compact_text((payload or {}).get("actor"), max_length=80) or "agent",
                    note=(payload or {}).get("note"),
                )
            )
            next_messages[index] = normalized
            return next_messages, ({"ok": True, "message": normalized, "messages": next_messages, "summary": agent_message_summary(next_messages)}, 200)
        return messages, ({"error": f"Agent message not found: {message_id}"}, 404)

    return update_json_file("agent_messages.json", [], mutator)


def email_payload():
    items = read_json_file("email.json", [])
    if isinstance(items, dict) and items.get("error"):
        return items
    safe_items = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    safe_items.sort(key=lambda item: item.get("received_at") or item.get("date") or "", reverse=True)
    return {
        "source": "local",
        "configured": False,
        "read_only": True,
        "count": len(safe_items),
        "items": safe_items[:25],
        "guidance": "Read-only email pane is ready for a future Himalaya/Gmail source. No send/delete/archive actions are exposed.",
    }


def hermes_command_path() -> str | None:
    configured = compact_text(os.environ.get("HERMES_COMMAND"), max_length=1000)
    if configured:
        candidate = Path(os.path.expandvars(os.path.expanduser(configured)))
        if candidate.is_file():
            return str(candidate)
        resolved = shutil.which(configured)
        if resolved:
            return resolved

    resolved = shutil.which("hermes")
    if resolved:
        return resolved

    for candidate in (Path.home() / ".local" / "bin" / "hermes", Path.home() / ".local" / "bin" / "hermes.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


def agent_console_profile(profile_id: str | None, discovery: dict | None = None) -> dict | None:
    """Resolve a public profile id without exposing or reading its filesystem path."""
    normalized = compact_text(profile_id, max_length=64).lower() or "default"
    if normalized == "hermes":  # Backward-compatible API alias.
        normalized = "default"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", normalized):
        return None
    discovery = discovery or hermes_profiles_payload()
    return next((profile for profile in discovery.get("profiles") or [] if profile.get("id") == normalized), None)


def agent_console_model(profile_id: str = "default", discovery: dict | None = None) -> str:
    profile = agent_console_profile(profile_id, discovery)
    if profile and compact_text(profile.get("model"), max_length=160):
        return compact_text(profile.get("model"), max_length=160)
    summary = hermes_config().get("summary") or {}
    return compact_text(summary.get("default_model"), max_length=160) or "configured default"


def hermes_python_path() -> str | None:
    candidates = (
        HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python3",
        HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python",
        HERMES_HOME / "hermes-agent" / "venv" / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def hermes_profiles_payload() -> dict:
    """Return normalized profile capabilities without exposing Hermes paths or secrets."""
    return discover_hermes_profiles(
        hermes_python_path(),
        HERMES_HOME,
        cwd=BASE_DIR,
    )


def hermes_skill_catalog_payload() -> dict:
    """Return the normalized Hermes built-in skill catalog without skill contents."""
    return discover_builtin_skills(
        hermes_python_path(),
        HERMES_HOME,
        cwd=BASE_DIR,
    )


def preview_hermes_profile_creation(payload):
    skill_catalog = (
        hermes_skill_catalog_payload()
        if isinstance(payload, dict) and compact_text(payload.get("skill_mode"), max_length=40).lower() == "custom"
        else None
    )
    return preview_profile_creation(
        payload,
        hermes_profiles_payload(),
        skill_catalog,
    )


def create_hermes_profile(payload):
    """Create one confirmed Hermes profile through fixed CLI arguments."""
    if not isinstance(payload, dict):
        return {"error": "Profile creation payload must be a JSON object."}, 400
    if payload.get("confirmed") is not True:
        return {"error": "Profile creation requires explicit confirmation."}, 400
    confirmation_id = compact_text(payload.get("confirmation_id"), max_length=80)
    if not confirmation_id:
        return {"error": "Profile creation requires a confirmation_id from the preview endpoint."}, 400
    if not HERMES_PROFILE_CREATION_LOCK.acquire(blocking=False):
        return {"error": "Another Hermes profile creation is already in progress."}, 409

    try:
        with AGENT_CONSOLE_LOCK:
            active = next(
                (item for item in AGENT_CONSOLE_RUNS.values() if item.get("status") in AGENT_CONSOLE_ACTIVE_STATUSES),
                None,
            )
            if active:
                return {
                    "error": "Stop the active Hermes run before creating a profile.",
                    "active_run_id": active["id"],
                }, 409

        skill_catalog = (
            hermes_skill_catalog_payload()
            if compact_text(payload.get("skill_mode"), max_length=40).lower() == "custom"
            else None
        )
        preview, preview_status = preview_profile_creation(
            payload,
            hermes_profiles_payload(),
            skill_catalog,
        )
        if preview_status != 200:
            return preview, preview_status
        if confirmation_id != preview.get("confirmation_id"):
            return {"error": "Profile creation inputs changed after preview; preview them again."}, 409

        command = hermes_command_path()
        if not command:
            return {"error": "Hermes CLI was not found in the Mentat server environment."}, 503
        normalized = preview["normalized"]
        try:
            result = subprocess.run(
                [command, *profile_creation_arguments(normalized)],
                cwd=str(BASE_DIR),
                env={**os.environ, "HERMES_HOME": str(HERMES_HOME)},
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "error": "Hermes profile creation timed out. Refresh profiles before retrying.",
                "partial": True,
            }, 504
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return {"error": "Hermes profile creation could not be started."}, 500

        skill_selection = None
        if result.returncode == 0 and normalized.get("skill_mode") == "custom":
            skill_selection = apply_builtin_skill_selection(
                hermes_python_path(),
                HERMES_HOME,
                normalized["name"],
                normalized.get("enabled_builtin_skills") or [],
                cwd=BASE_DIR,
            )

        refreshed = hermes_profiles_payload()
        created = next(
            (item for item in refreshed.get("profiles") or [] if item.get("id") == normalized["name"]),
            None,
        )
        if result.returncode != 0:
            return {
                "error": f"Hermes profile creation exited with status {result.returncode}.",
                "partial": created is not None,
                "profile": created,
                "profiles": refreshed,
            }, 500
        if skill_selection and skill_selection.get("status") != "applied":
            return {
                "error": "Hermes created the profile, but its built-in skill selection could not be applied.",
                "partial": True,
                "profile": created,
                "profiles": refreshed,
                "skill_selection": skill_selection,
            }, 500
        if created is None:
            return {
                "error": "Hermes reported success, but the new profile was not found after refresh.",
                "partial": True,
                "profiles": refreshed,
            }, 500
        return {
            "ok": True,
            "profile": created,
            "profiles": refreshed,
            "skill_selection": skill_selection,
            "message": f"Hermes profile '{normalized['name']}' created.",
        }, 201
    finally:
        HERMES_PROFILE_CREATION_LOCK.release()


def _active_agent_console_run() -> dict | None:
    with AGENT_CONSOLE_LOCK:
        return next(
            (item for item in AGENT_CONSOLE_RUNS.values() if item.get("status") in AGENT_CONSOLE_ACTIVE_STATUSES),
            None,
        )


def preview_hermes_profile_deletion(profile_id, payload):
    """Return exact destructive effects only when deletion is currently safe."""
    active = _active_agent_console_run()
    if active:
        return {
            "error": "Stop the active Hermes run before deleting a profile.",
            "active_run_id": active["id"],
        }, 409
    return preview_profile_deletion(profile_id, payload or {}, hermes_profiles_payload())


def delete_confirmed_hermes_profile(profile_id, payload):
    """Delete one confirmed non-default, non-active profile through Hermes."""
    if not isinstance(payload, dict):
        return {"error": "Profile deletion payload must be a JSON object."}, 400
    if payload.get("confirmed") is not True:
        return {"error": "Profile deletion requires explicit confirmation."}, 400
    confirmation_id = compact_text(payload.get("confirmation_id"), max_length=80)
    if not confirmation_id:
        return {"error": "Profile deletion requires a confirmation_id from the preview endpoint."}, 400
    if not HERMES_PROFILE_CREATION_LOCK.acquire(blocking=False):
        return {"error": "Another Hermes profile change is already in progress."}, 409

    try:
        active = _active_agent_console_run()
        if active:
            return {
                "error": "Stop the active Hermes run before deleting a profile.",
                "active_run_id": active["id"],
            }, 409

        before = hermes_profiles_payload()
        preview, preview_status = preview_profile_deletion(profile_id, payload, before)
        if preview_status != 200:
            return preview, preview_status
        if confirmation_id != preview.get("confirmation_id"):
            return {"error": "Profile deletion inputs or profile state changed after preview; preview again."}, 409

        normalized_id = preview["normalized"]["profile_id"]
        result = delete_hermes_profile(
            hermes_python_path(),
            HERMES_HOME,
            normalized_id,
            cwd=BASE_DIR,
        )
        refreshed = hermes_profiles_payload()
        refresh_available = refreshed.get("status") == "available"
        remains = next(
            (item for item in refreshed.get("profiles") or [] if item.get("id") == normalized_id),
            None,
        )
        if refresh_available and remains is None and result.get("status") == "deleted":
            return {
                "ok": True,
                "deleted_profile_id": normalized_id,
                "profiles": refreshed,
                "message": f"Hermes profile '{normalized_id}' deleted.",
            }, 200
        if refresh_available and remains is None:
            return {
                "ok": True,
                "deleted_profile_id": normalized_id,
                "profiles": refreshed,
                "warning": "Hermes did not return a clean result, but refresh verified that the profile was deleted.",
            }, 200
        if not refresh_available:
            return {
                "error": "Hermes profile deletion could not be verified because profile discovery is unavailable. Review the profile in Hermes before retrying.",
                "error_code": "verification_unavailable",
                "profiles": refreshed,
            }, 503
        error_code = result.get("error_code") or "runtime_failed"
        messages = {
            "runtime_timeout": "Hermes profile deletion timed out and the profile still exists.",
            "profile_missing": "Hermes could not find the profile, but it remains visible after refresh.",
            "capability_unavailable": "This Hermes runtime no longer exposes profile deletion.",
        }
        return {
            "error": messages.get(error_code, "Hermes could not delete the profile."),
            "error_code": error_code,
            "profile": remains,
            "profiles": refreshed,
        }, 504 if error_code == "runtime_timeout" else 500
    finally:
        HERMES_PROFILE_CREATION_LOCK.release()


HERMES_MODEL_CATALOG_SCRIPT = """
import json
import os
import sys

from hermes_cli.profiles import resolve_profile_env

profile_id = sys.argv[2]
os.environ["HERMES_HOME"] = resolve_profile_env(profile_id)

from hermes_cli.inventory import build_models_payload, load_picker_context

ctx = load_picker_context()
payload = build_models_payload(
    ctx,
    explicit_only=True,
    refresh=sys.argv[1] == "refresh",
    probe_custom_providers=False,
    probe_current_custom_provider=True,
    max_models=None,
)
provider = str(ctx.current_provider or "").strip()
provider_key = provider.lower()
rows = payload.get("providers") or []
selected = next(
    (row for row in rows if str(row.get("slug") or "").strip().lower() == provider_key),
    next((row for row in rows if row.get("is_current")), None),
)
models = []
if isinstance(selected, dict):
    for item in selected.get("models") or []:
        value = str(item or "").strip()
        if value and value not in models:
            models.append(value)
print(json.dumps({
    "profile_id": profile_id,
    "provider": provider,
    "provider_label": str((selected or {}).get("name") or provider),
    "models": models,
    "current_model": str(ctx.current_model or "").strip(),
    "source": str((selected or {}).get("source") or ""),
}))
""".strip()


def agent_console_model_catalog(profile_id: str = "default", *, refresh: bool = False) -> dict:
    discovery = hermes_profiles_payload()
    profile = agent_console_profile(profile_id, discovery)
    normalized_profile_id = compact_text(profile.get("id") if profile else profile_id, max_length=64).lower()
    provider = compact_text(profile.get("provider") if profile else "", max_length=120)
    current_model = compact_text(profile.get("model") if profile else "", max_length=160)
    if profile is None:
        return {
            "profile_id": normalized_profile_id,
            "provider": "",
            "provider_label": "",
            "models": [],
            "current_model": "",
            "error": f"Hermes profile '{normalized_profile_id}' is unavailable.",
        }
    key = f"{normalized_profile_id}|{provider}|{current_model}"
    now = time.monotonic()
    cached = AGENT_MODEL_CATALOG_CACHE.get("payload")
    if (
        not refresh
        and AGENT_MODEL_CATALOG_CACHE.get("key") == key
        and isinstance(cached, dict)
        and now - float(AGENT_MODEL_CATALOG_CACHE.get("fetched_at") or 0) < AGENT_MODEL_CATALOG_TTL_SECONDS
    ):
        return dict(cached)

    python_path = hermes_python_path()
    if not python_path:
        return {
            "profile_id": normalized_profile_id,
            "provider": provider,
            "provider_label": provider,
            "models": [],
            "current_model": current_model,
            "error": "Hermes runtime was not found for provider model discovery.",
        }
    try:
        result = subprocess.run(
            [python_path, "-c", HERMES_MODEL_CATALOG_SCRIPT, "refresh" if refresh else "cached", normalized_profile_id],
            cwd=str(BASE_DIR),
            env={**os.environ, "HERMES_HOME": str(HERMES_HOME)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        return {
            "profile_id": normalized_profile_id,
            "provider": provider,
            "provider_label": provider,
            "models": [],
            "current_model": current_model,
            "error": "Hermes provider model discovery could not be started.",
        }
    if result.returncode != 0:
        return {
            "profile_id": normalized_profile_id,
            "provider": provider,
            "provider_label": provider,
            "models": [],
            "current_model": current_model,
            "error": "Hermes could not load provider models.",
        }
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    models = []
    for value in payload.get("models") or []:
        model = compact_text(value, max_length=160)
        if model and model not in models:
            models.append(model)
    catalog = {
        "profile_id": normalized_profile_id,
        "provider": compact_text(payload.get("provider"), max_length=120) or provider,
        "provider_label": compact_text(payload.get("provider_label"), max_length=160) or provider,
        "models": models,
        "current_model": compact_text(payload.get("current_model"), max_length=160) or current_model,
        "source": compact_text(payload.get("source"), max_length=80),
        "error": "" if models else "No active models were returned for the current Hermes provider.",
    }
    AGENT_MODEL_CATALOG_CACHE.update({"key": key, "payload": catalog, "fetched_at": now})
    return dict(catalog)


def agent_console_provider_inventory(profile_id: str = "default", *, refresh: bool = False) -> dict:
    requested = compact_text(profile_id, max_length=64).lower() or "default"
    if requested == "hermes":
        requested = "default"
    profile = agent_console_profile(requested)
    if profile is None:
        return {
            "profile_id": requested,
            "current_provider": "",
            "current_model": "",
            "providers": [],
            "capabilities": {"providers.switch": False},
            "error": f"Hermes profile '{requested}' is unavailable.",
        }
    return provider_inventory(
        hermes_python_path(), HERMES_HOME, requested, cwd=BASE_DIR, refresh=refresh
    )


def agent_console_event(run: dict, message: str, kind: str = "status", data: dict | None = None) -> None:
    events = run.setdefault("events", [])
    sequence_candidates = []
    for value in [run.get("event_cursor")] + [
        item.get("sequence") or item.get("cursor") for item in events if isinstance(item, dict)
    ]:
        try:
            sequence_candidates.append(max(0, int(value or 0)))
        except (TypeError, ValueError):
            continue
    sequence = max(sequence_candidates or [0]) + 1
    display_text = compact_text(message, max_length=500) or "Agent run updated"
    events.append({
        "schema_version": EVENT_SCHEMA_VERSION,
        "id": f"event_{uuid4().hex[:10]}",
        "run_id": str(run.get("id") or ""),
        "sequence": sequence,
        "cursor": sequence,
        "type": kind,
        "kind": kind,
        "data": dict(data) if isinstance(data, dict) else {},
        "display_text": display_text,
        "message": display_text,
        "timestamp": now_iso(),
    })
    if len(events) > EVENT_RETENTION:
        del events[:-EVENT_RETENTION]
    run["event_cursor"] = sequence
    run["updated_at"] = now_iso()


def agent_console_snapshot(run: dict) -> dict:
    return {
        key: value
        for key, value in run.items()
        if key not in {"process"}
    }


def agent_console_payload():
    command = hermes_command_path()
    discovery = hermes_profiles_payload()
    profiles = discovery.get("profiles") or []
    selected_profile_id = discovery.get("active_profile") or "default"
    if not any(profile.get("id") == selected_profile_id for profile in profiles):
        selected_profile_id = profiles[0].get("id") if profiles else "default"
    catalog = agent_console_model_catalog(selected_profile_id)
    provider_payload = agent_console_provider_inventory(selected_profile_id)
    with AGENT_CONSOLE_LOCK:
        runs = sorted(AGENT_CONSOLE_RUNS.values(), key=lambda item: item.get("created_at") or "", reverse=True)
        snapshots = [agent_console_snapshot(run) for run in runs[:12]]
    return {
        "agents": [
            {
                "id": profile.get("id"),
                "name": profile.get("name") or profile.get("id"),
                "description": profile.get("description") or "",
                "available": bool(command),
                "model": profile.get("model") or "configured default",
                "provider": profile.get("provider") or "",
                "is_default": bool(profile.get("is_default")),
            }
            for profile in profiles
            if profile.get("id")
        ] or [{
            "id": "default",
            "name": "Hermes · default",
            "description": "",
            "available": bool(command),
            "model": catalog.get("current_model") or agent_console_model("default", discovery),
            "provider": catalog.get("provider") or "",
            "is_default": True,
        }],
        "selected_agent_id": selected_profile_id,
        "model_catalog": catalog,
        "provider_inventory": provider_payload,
        "runs": snapshots,
        "active_run_id": next((run["id"] for run in snapshots if run.get("status") in AGENT_CONSOLE_ACTIVE_STATUSES), None),
        "local_only": True,
        "error": None if command else "Hermes CLI was not found in the Mentat server environment.",
    }


def agent_console_run_payload(run_id: str, after_cursor: str | None = None):
    with AGENT_CONSOLE_LOCK:
        run = AGENT_CONSOLE_RUNS.get(run_id)
        if not run:
            return {"error": "Agent run not found"}, 404
        snapshot = agent_console_snapshot(run)
        if after_cursor is None:
            # Existing clients keep receiving the complete run representation.
            return {"run": snapshot}, 200
        if not re.fullmatch(r"\d{1,10}", str(after_cursor)):
            return {"error": "Event cursor must be a non-negative integer"}, 400
        cursor = int(after_cursor)
        retained = [item for item in snapshot.get("events", []) if isinstance(item, dict)]
        current_cursor = int(snapshot.get("event_cursor") or (retained[-1].get("cursor") if retained else 0) or 0)
        if cursor > current_cursor:
            return {"error": "Event cursor is ahead of this run", "current_cursor": current_cursor}, 409
        events = [item for item in retained if int(item.get("cursor") or 0) > cursor]
        oldest_cursor = int(retained[0].get("cursor") or 0) if retained else current_cursor
        cursor_reset_required = bool(retained and cursor < oldest_cursor - 1)
        snapshot["events"] = events
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "run_id": run_id,
            "after_cursor": cursor,
            "next_cursor": current_cursor,
            "cursor_reset_required": cursor_reset_required,
            "events": events,
            "run": snapshot,
        }, 200


def parse_hermes_session_id(stderr: str) -> str | None:
    matches = re.findall(r"(?im)^\s*session_id:\s*([A-Za-z0-9_.:-]+)\s*$", stderr or "")
    return matches[-1] if matches else None


ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def clean_agent_output(value: str, *, max_length: int = 200_000) -> str:
    output = ANSI_ESCAPE_RE.sub("", str(value or "")).replace("\r\n", "\n").strip()
    if len(output) > max_length:
        output = output[:max_length].rstrip() + "\n\n[Output truncated by Mentat]"
    return output


def run_hermes_agent(run_id: str, command_path: str) -> None:
    with AGENT_CONSOLE_LOCK:
        run = AGENT_CONSOLE_RUNS.get(run_id)
        if not run:
            return
        if run.get("status") == "cancelling":
            run["status"] = "cancelled"
            run["completed_at"] = now_iso()
            run["error"] = "Run stopped by operator."
            agent_console_event(run, "Run stopped", "cancelled", {"reason": "operator_cancelled"})
            persist_agent_console_runs()
            return
        run["status"] = "running"
        run["started_at"] = now_iso()
        agent_console_event(run, "Starting Hermes CLI", "status", {"phase": "launch"})
        persist_agent_console_runs()
        prompt = run["prompt"]
        session_id = run.get("session_id")
        profile_id = run.get("agent_id") or "default"

    command = [command_path, "-p", profile_id, "chat", "-q", prompt, "-Q", "--source", "mentat"]
    if session_id:
        command.extend(["--resume", session_id])

    env = os.environ.copy()
    env["HERMES_HOME"] = str(HERMES_HOME)
    env["PYTHONUNBUFFERED"] = "1"
    started = time.monotonic()
    next_update = 2
    try:
        process = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with AGENT_CONSOLE_LOCK:
            AGENT_CONSOLE_PROCESSES[run_id] = process
            current = AGENT_CONSOLE_RUNS.get(run_id)
            if current:
                agent_console_event(current, "Model is working", "status", {"phase": "inference"})
                persist_agent_console_runs()

        while True:
            try:
                stdout, stderr = process.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                elapsed = int(time.monotonic() - started)
                if elapsed < next_update:
                    continue
                with AGENT_CONSOLE_LOCK:
                    current = AGENT_CONSOLE_RUNS.get(run_id)
                    if not current:
                        process.terminate()
                        return
                    if current.get("status") == "cancelling":
                        process.terminate()
                    elif elapsed >= 45:
                        agent_console_event(current, f"Hermes is still working ({elapsed}s)", "status", {"elapsed_seconds": elapsed})
                    elif elapsed >= 12:
                        agent_console_event(current, "Agent is processing the request and may be using tools", "status", {"elapsed_seconds": elapsed})
                    persist_agent_console_runs()
                next_update = 12 if elapsed < 12 else elapsed + 30

        with AGENT_CONSOLE_LOCK:
            current = AGENT_CONSOLE_RUNS.get(run_id)
            if not current:
                return
            current["completed_at"] = now_iso()
            current["duration_seconds"] = round(time.monotonic() - started, 1)
            parsed_session_id = parse_hermes_session_id(stderr)
            if parsed_session_id:
                current["session_id"] = parsed_session_id
            response = clean_agent_output(stdout)
            if current.get("status") == "cancelling":
                current["status"] = "cancelled"
                current["error"] = "Run stopped by operator."
                agent_console_event(current, "Run stopped", "cancelled", {"reason": "operator_cancelled"})
            elif process.returncode == 0 and response:
                current["status"] = "completed"
                current["response"] = response
                agent_console_event(current, "Response complete", "complete", {"duration_seconds": current["duration_seconds"]})
            else:
                error_text = re.sub(r"(?im)^\s*session_id:.*$", "", clean_agent_output(stderr, max_length=4_000)).strip()
                current["status"] = "failed"
                current["error"] = error_text or response or f"Hermes exited with status {process.returncode}."
                agent_console_event(current, "Hermes run failed", "error", {"return_code": process.returncode})
            persist_agent_console_runs()
    except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
        with AGENT_CONSOLE_LOCK:
            current = AGENT_CONSOLE_RUNS.get(run_id)
            if current:
                current["status"] = "failed"
                current["completed_at"] = now_iso()
                current["error"] = compact_text(exc, max_length=2_000)
                agent_console_event(current, "Hermes could not be started", "error", {"phase": "launch"})
                persist_agent_console_runs()
    finally:
        with AGENT_CONSOLE_LOCK:
            AGENT_CONSOLE_PROCESSES.pop(run_id, None)


def start_agent_console_run(payload):
    if not isinstance(payload, dict):
        return {"error": "Agent prompt payload must be a JSON object"}, 400
    requested_agent_id = compact_text(payload.get("agent_id"), max_length=64).lower() or "default"
    if requested_agent_id == "hermes":
        requested_agent_id = "default"
    discovery = hermes_profiles_payload()
    profile = agent_console_profile(requested_agent_id, discovery)
    if profile is None:
        return {"error": f"Unknown or unavailable Hermes profile: {requested_agent_id}"}, 400
    agent_id = profile["id"]
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return {"error": "Prompt is required"}, 400
    if len(prompt) > AGENT_CONSOLE_PROMPT_LIMIT:
        return {"error": f"Prompt must be {AGENT_CONSOLE_PROMPT_LIMIT:,} characters or fewer"}, 400
    session_id = compact_text(payload.get("session_id"), max_length=200)
    if session_id and not re.fullmatch(r"[A-Za-z0-9_.:-]+", session_id):
        return {"error": "Invalid Hermes session ID"}, 400
    command = hermes_command_path()
    if not command:
        return {"error": "Hermes CLI was not found in the Mentat server environment."}, 503

    with AGENT_CONSOLE_LOCK:
        if HERMES_PROFILE_CREATION_LOCK.locked():
            return {"error": "A Hermes profile is currently being changed."}, 409
        active = next((item for item in AGENT_CONSOLE_RUNS.values() if item.get("status") in AGENT_CONSOLE_ACTIVE_STATUSES), None)
        if active:
            return {"error": "Hermes is already working on another prompt", "active_run_id": active["id"]}, 409
        if session_id:
            session_runs = [
                item for item in AGENT_CONSOLE_RUNS.values()
                if item.get("session_id") == session_id
            ]
            conflicting_session = next(
                (item for item in session_runs if item.get("agent_id", "default") != agent_id),
                None,
            )
            if conflicting_session:
                return {
                    "error": "A Hermes session cannot be resumed by a different profile.",
                    "session_profile_id": conflicting_session.get("agent_id") or "default",
                }, 409
            if not session_runs:
                return {
                    "error": "This Hermes session is not present in retained Mentat history, so its profile ownership cannot be verified. Start a new session instead."
                }, 409
        run_id = f"run_{uuid4().hex[:14]}"
        run = {
            "id": run_id,
            "agent_id": agent_id,
            "agent_name": profile.get("name") or agent_id,
            "model": profile.get("model") or agent_console_model(agent_id, discovery),
            "prompt": prompt,
            "status": "queued",
            "session_id": session_id or None,
            "response": "",
            "error": "",
            "events": [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "started_at": None,
            "completed_at": None,
        }
        agent_console_event(
            run,
            f"Prompt queued for {profile.get('name') or agent_id}",
            "queued",
            {"agent_id": agent_id},
        )
        AGENT_CONSOLE_RUNS[run_id] = run
        if len(AGENT_CONSOLE_RUNS) > AGENT_CONSOLE_RUN_LIMIT:
            removable = sorted(
                (item for item in AGENT_CONSOLE_RUNS.values() if item.get("status") not in AGENT_CONSOLE_ACTIVE_STATUSES),
                key=lambda item: (item.get("created_at") or "", item.get("id") or ""),
            )
            for old_run in removable[: len(AGENT_CONSOLE_RUNS) - AGENT_CONSOLE_RUN_LIMIT]:
                AGENT_CONSOLE_RUNS.pop(old_run["id"], None)
        persist_agent_console_runs()

    with AGENT_CONSOLE_LOCK:
        snapshot = agent_console_snapshot(run)
    worker = threading.Thread(target=run_hermes_agent, args=(run_id, command), daemon=True, name=f"mentat-{run_id}")
    worker.start()
    return {"ok": True, "run": snapshot}, 202


def preview_agent_console_provider_switch(payload):
    if not isinstance(payload, dict):
        return {"error": "Provider switch payload must be a JSON object"}, 400
    requested = compact_text(payload.get("agent_id"), max_length=64).lower() or "default"
    if requested == "hermes":
        requested = "default"
    if agent_console_profile(requested) is None:
        return {"error": f"Unknown or unavailable Hermes profile: {requested}"}, 400
    provider = compact_text(payload.get("provider"), max_length=120)
    model = compact_text(payload.get("model"), max_length=160)
    if not provider or not model:
        return {"error": "Provider and model are required"}, 400
    with AGENT_CONSOLE_LOCK:
        active = next((item for item in AGENT_CONSOLE_RUNS.values() if item.get("status") in AGENT_CONSOLE_ACTIVE_STATUSES), None)
        if active:
            return {"error": "Stop the active Hermes run before changing provider configuration", "active_run_id": active["id"]}, 409
    inventory = agent_console_provider_inventory(requested, refresh=True)
    if inventory.get("error") and not inventory.get("providers"):
        return {"error": inventory["error"]}, 503
    return preview_provider_switch(requested, provider, model, inventory)


def switch_agent_console_provider(payload):
    if not isinstance(payload, dict):
        return {"error": "Provider switch payload must be a JSON object"}, 400
    if payload.get("confirmed") is not True:
        return {"error": "Provider switching requires explicit confirmation."}, 400
    confirmation_id = compact_text(payload.get("confirmation_id"), max_length=80)
    requested = compact_text(payload.get("agent_id"), max_length=64).lower() or "default"
    if requested == "hermes":
        requested = "default"
    provider = compact_text(payload.get("provider"), max_length=120)
    model = compact_text(payload.get("model"), max_length=160)
    if not confirmation_id or not provider or not model:
        return {"error": "Provider, model, and preview confirmation are required."}, 400
    if agent_console_profile(requested) is None:
        return {"error": f"Unknown or unavailable Hermes profile: {requested}"}, 400

    if not HERMES_PROFILE_CREATION_LOCK.acquire(blocking=False):
        return {"error": "Another Hermes profile change is already in progress."}, 409
    try:
        with AGENT_CONSOLE_LOCK:
            active = next((item for item in AGENT_CONSOLE_RUNS.values() if item.get("status") in AGENT_CONSOLE_ACTIVE_STATUSES), None)
            if active:
                return {"error": "Stop the active Hermes run before changing provider configuration", "active_run_id": active["id"]}, 409
        before = agent_console_provider_inventory(requested, refresh=True)
        preview, preview_status = preview_provider_switch(requested, provider, model, before)
        if preview_status != 200:
            return preview, preview_status
        if confirmation_id != preview.get("confirmation_id"):
            return {"error": "Provider or profile state changed after preview; preview the change again."}, 409

        _, apply_error = apply_provider_switch(
            hermes_python_path(), HERMES_HOME, requested, provider, model, cwd=BASE_DIR
        )
        if apply_error:
            return {"error": apply_error or "Hermes could not change the provider."}, 500

        verified = agent_console_provider_inventory(requested, refresh=True)
        if verified.get("current_provider") == provider and verified.get("current_model") == model:
            AGENT_MODEL_CATALOG_CACHE.update({"key": None, "payload": None, "fetched_at": 0.0})
            return {
                "ok": True,
                "agent_id": requested,
                "provider": provider,
                "model": model,
                "provider_inventory": verified,
                "model_catalog": agent_console_model_catalog(requested, refresh=True),
                "message": "Hermes provider and default model updated and verified.",
            }, 200

        prior_provider = compact_text(before.get("current_provider"), max_length=120)
        prior_model = compact_text(before.get("current_model"), max_length=160)
        rollback_ok = False
        if prior_provider and prior_model:
            _, rollback_error = apply_provider_switch(
                hermes_python_path(), HERMES_HOME, requested, prior_provider, prior_model, cwd=BASE_DIR
            )
            if not rollback_error:
                rolled_back = agent_console_provider_inventory(requested, refresh=True)
                rollback_ok = rolled_back.get("current_provider") == prior_provider and rolled_back.get("current_model") == prior_model
        return {
            "error": "Hermes did not verify the requested provider change; the prior configuration was restored." if rollback_ok else "Hermes did not verify the requested provider change, and Mentat could not verify rollback. Review this profile in Hermes before running it.",
            "error_code": "verification_failed_rolled_back" if rollback_ok else "verification_failed_rollback_unverified",
        }, 500
    finally:
        HERMES_PROFILE_CREATION_LOCK.release()


def refresh_agent_console_models(payload=None):
    payload = payload if isinstance(payload, dict) else {}
    requested_agent_id = compact_text(payload.get("agent_id"), max_length=64).lower() or "default"
    if requested_agent_id == "hermes":
        requested_agent_id = "default"
    if agent_console_profile(requested_agent_id) is None:
        return {"error": f"Unknown or unavailable Hermes profile: {requested_agent_id}"}, 400
    return {
        "ok": True,
        "agent_id": requested_agent_id,
        "model_catalog": agent_console_model_catalog(requested_agent_id, refresh=True),
        "provider_inventory": agent_console_provider_inventory(requested_agent_id, refresh=True),
    }, 200


def cancel_agent_console_run(run_id: str):
    with AGENT_CONSOLE_LOCK:
        run = AGENT_CONSOLE_RUNS.get(run_id)
        if not run:
            return {"error": "Agent run not found"}, 404
        if run.get("status") not in AGENT_CONSOLE_ACTIVE_STATUSES:
            return {"error": "Agent run is no longer active", "run": agent_console_snapshot(run)}, 409
        run["status"] = "cancelling"
        agent_console_event(run, "Stopping Hermes", "status", {"phase": "cancelling"})
        process = AGENT_CONSOLE_PROCESSES.get(run_id)
        if process and process.poll() is None:
            process.terminate()
        persist_agent_console_runs()
        return {"ok": True, "run": agent_console_snapshot(run)}, 202


def stop_agent_console_processes() -> None:
    with AGENT_CONSOLE_LOCK:
        active = list(AGENT_CONSOLE_PROCESSES.items())
        for run_id, _process in active:
            run = AGENT_CONSOLE_RUNS.get(run_id)
            if run and run.get("status") in AGENT_CONSOLE_ACTIVE_STATUSES:
                run["status"] = "cancelling"
                agent_console_event(run, "Mentat is shutting down", "status", {"phase": "shutdown"})
        persist_agent_console_runs()
    for _run_id, process in active:
        try:
            if process.poll() is None:
                process.terminate()
        except OSError:
            pass


def handle_post_route(path: str, payload=None):
    for pattern, handler, accepts_payload in POST_ROUTES:
        match = pattern.match(path)
        if not match:
            continue
        args = [unquote(part) for part in match.groups()]
        if accepts_payload:
            return handler(*args, payload)
        return handler(*args)
    return {"error": "Not found"}, 404


POST_ROUTES = [
    (re.compile(r"^/api/attention/([^/]+)/resolve$"), resolve_attention_item, False),
    (re.compile(r"^/api/agents/heartbeat$"), upsert_agent_heartbeat, True),
    (re.compile(r"^/api/tasks$"), create_task, True),
    (re.compile(r"^/api/tasks/([^/]+)/delete/preview$"), preview_task_deletion, True),
    (re.compile(r"^/api/tasks/([^/]+)/delete$"), delete_confirmed_task, True),
    (re.compile(r"^/api/tasks/([^/]+)$"), update_task, True),
    (re.compile(r"^/api/projects$"), create_project, True),
    (re.compile(r"^/api/projects/([^/]+)$"), update_project, True),
    (re.compile(r"^/api/agent-messages$"), create_agent_message, True),
    (re.compile(r"^/api/agent-messages/([^/]+)/state$"), update_agent_message_state, True),
    (re.compile(r"^/api/agent-console/runs$"), start_agent_console_run, True),
    (re.compile(r"^/api/agent-console/models/refresh$"), refresh_agent_console_models, True),
    (re.compile(r"^/api/agent-console/provider/preview$"), preview_agent_console_provider_switch, True),
    (re.compile(r"^/api/agent-console/provider$"), switch_agent_console_provider, True),
    (re.compile(r"^/api/agent-console/runs/([^/]+)/cancel$"), cancel_agent_console_run, False),
    (re.compile(r"^/api/hermes/profiles/preview$"), preview_hermes_profile_creation, True),
    (re.compile(r"^/api/hermes/profiles/([^/]+)/delete/preview$"), preview_hermes_profile_deletion, True),
    (re.compile(r"^/api/hermes/profiles/([^/]+)/delete$"), delete_confirmed_hermes_profile, True),
    (re.compile(r"^/api/hermes/profiles$"), create_hermes_profile, True),
    (re.compile(r"^/api/hermes/crons/([^/]+)/trigger/preview$"), preview_cron_trigger, True),
    (re.compile(r"^/api/hermes/crons/([^/]+)/trigger$"), trigger_confirmed_cron, True),
]


API_ROUTES = {
    "/api/overview": overview,
    "/api/projects": lambda: {"projects": read_json_file("projects.json", [])},
    "/api/tasks": lambda: {"tasks": read_json_file("tasks.json", [])},
    "/api/agents": agents_payload,
    "/api/agent-messages": agent_messages_payload,
    "/api/attention": attention_payload,
    "/api/calendar": google_calendar_events,
    "/api/email": email_payload,
    "/api/agent-console": agent_console_payload,
    "/api/agent-console/commands": command_manifest_payload,
    "/api/obsidian-notes": obsidian_notes,
    "/api/hermes/crons": cron_jobs_payload,
    "/api/hermes/sessions": lambda: recent_sessions(limit=12),
    "/api/hermes/config": hermes_config,
    "/api/hermes/profiles": hermes_profiles_payload,
    "/api/hermes/skills/catalog": hermes_skill_catalog_payload,
    "/api/health": health,
}


GET_ROUTES = {
    re.compile(r"^/api/agent-console/runs/([^/]+)$"): agent_console_run_payload,
    re.compile(r"^/api/hermes/sessions/([^/]+)/replay$"): session_replay,
    re.compile(r"^/api/hermes/sessions/([^/]+)$"): session_detail,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "Mentat/0.1"

    def log_message(self, fmt, *args):
        """Log requests without ever breaking HTTP responses.

        BaseHTTPRequestHandler calls log_message() inside send_response(). If
        stdout/stderr is unavailable or a format string is unexpected, raising
        here causes clients to see "Remote end closed connection without
        response". Logging is useful, but it must never take the dashboard down.
        """
        try:
            print(f"[{now_iso()}] {self.client_address[0]} {fmt % args}", flush=True)
        except Exception:
            pass

    def log_internal_error(self, context: str, exc: BaseException) -> None:
        """Record an unexpected failure without exposing its message to HTTP clients.

        Exception messages can contain provider output or other sensitive values,
        so diagnostics include the exception type and stack frames only.  That is
        enough to locate the failing code path while preserving the generic public
        error boundary.
        """
        try:
            frames = []
            current = exc.__traceback__
            while current is not None:
                code = current.tb_frame.f_code
                frames.append(f"{code.co_filename}:{current.tb_lineno} in {code.co_name}")
                current = current.tb_next
            stack = "\n".join(frames)
            self.log_error(
                "%s failed (%s)%s",
                context,
                type(exc).__name__,
                f"\n{stack}" if stack else "",
            )
        except Exception:
            pass

    def send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def control_request_is_local(self) -> bool:
        return self.client_address[0] in {"127.0.0.1", "::1"}

    def request_host_origin(self) -> tuple[str, str, int] | None:
        host_header = str(self.headers.get("Host") or "").strip()
        if not host_header:
            return None
        try:
            parsed = urlparse(f"//{host_header}")
            hostname = (parsed.hostname or "").lower()
            port = parsed.port or 80
        except ValueError:
            return None
        if parsed.username or parsed.password or parsed.path not in {"", "/"}:
            return None
        if hostname not in {"localhost", "127.0.0.1", "::1"}:
            return None
        bound_port = getattr(self.server, "server_port", port)
        server_port = bound_port if isinstance(bound_port, int) else port
        if port != server_port:
            return None
        return "http", hostname, port

    def request_host_is_local(self) -> bool:
        return self.request_host_origin() is not None

    def request_origin_is_local(self) -> bool:
        fetch_site = str(self.headers.get("Sec-Fetch-Site") or "").strip().lower()
        if fetch_site == "cross-site":
            return False
        origin = str(self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        if origin.lower() == "null":
            return False
        try:
            parsed = urlparse(origin)
        except ValueError:
            return False
        try:
            origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            return False
        if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return False
        expected = self.request_host_origin()
        return expected is not None and (
            parsed.scheme.lower(),
            (parsed.hostname or "").lower(),
            origin_port,
        ) == expected

    def local_api_request_is_allowed(self) -> bool:
        return self.control_request_is_local() and self.request_host_is_local() and self.request_origin_is_local()

    def send_static(self, path: str):
        parsed = urlparse(path)
        route_path = parsed.path
        if route_path == "/":
            file_path = PUBLIC_DIR / "index.html"
        else:
            rel = route_path.lstrip("/")
            file_path = PUBLIC_DIR / rel
        try:
            resolved = file_path.resolve()
            if PUBLIC_DIR.resolve() not in resolved.parents and resolved != PUBLIC_DIR.resolve():
                self.send_error(403)
                return
            if not resolved.exists() or not resolved.is_file():
                self.send_error(404)
                return
            body = resolved.read_bytes()
            content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.log_internal_error("static asset response", exc)
            self.send_error(500, "Static asset could not be loaded")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not self.local_api_request_is_allowed():
            self.send_json({"error": "Mentat APIs are available only from this local dashboard origin."}, status=403)
            return
        if parsed.path == "/api/hermes/search":
            try:
                query = parse_qs(parsed.query).get("q", [""])[0]
                self.send_json(search_messages(query))
            except Exception as exc:
                self.log_internal_error("Hermes search", exc)
                self.send_json({"error": "Hermes search is unavailable."}, status=500)
            return
        if parsed.path in API_ROUTES:
            try:
                self.send_json(API_ROUTES[parsed.path]())
            except Exception as exc:
                self.log_internal_error(f"dashboard route {parsed.path}", exc)
                self.send_json({"error": "Mentat could not load this dashboard response."}, status=500)
            return
        for pattern, handler in GET_ROUTES.items():
            match = pattern.match(parsed.path)
            if not match:
                continue
            try:
                query = parse_qs(parsed.query)
                route_query_value = (
                    query.get("after", [None])[0]
                    if parsed.path.startswith("/api/agent-console/runs/")
                    else query.get("message_id", [None])[0]
                )
                payload, status = handler(*[unquote(part) for part in match.groups()], route_query_value)
                self.send_json(payload, status=status)
            except Exception as exc:
                self.log_internal_error(f"resource route {parsed.path}", exc)
                self.send_json({"error": "Mentat could not load this requested resource."}, status=500)
            return
        self.send_static(self.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not self.local_api_request_is_allowed():
            self.send_json({"error": "Mentat mutations are available only from this local dashboard origin."}, status=403)
            return
        payload = None
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_json({"error": "Invalid Content-Length header"}, status=400)
            return
        if length < 0 or length > MAX_JSON_BODY_BYTES:
            self.send_json({"error": f"Request body must be {MAX_JSON_BODY_BYTES:,} bytes or fewer"}, status=413)
            return
        if length and str(self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower() != "application/json":
            self.send_json({"error": "JSON requests require Content-Type: application/json"}, status=415)
            return
        if length:
            try:
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8")) if raw else None
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON body"}, status=400)
                return
            except Exception as exc:
                self.log_internal_error("request body decoding", exc)
                self.send_json({"error": "Request body could not be decoded."}, status=400)
                return
        try:
            payload, status = handle_post_route(parsed.path, payload)
            self.send_json(payload, status=status)
        except Exception as exc:
            self.log_internal_error(f"mutation route {parsed.path}", exc)
            self.send_json({"error": "Mentat could not complete this mutation."}, status=500)


if __name__ == "__main__":
    cli_args = parse_cli_args()
    apply_runtime_config(load_app_config(cli_args))
    if cli_args.print_config:
        print(json.dumps(runtime_config_summary(), indent=2))
        raise SystemExit(0)
    if HOST.lower() not in {"127.0.0.1", "::1", "localhost"}:
        print("Mentat refuses non-loopback binds until authenticated remote access is implemented.")
        raise SystemExit(2)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    load_agent_console_runs()
    server = server_class_for_host(HOST)((HOST, PORT), Handler)
    launcher_pid = start_launcher_watch(server)
    state_path = write_runtime_state()
    print(f"Mentat listening on {HOST}:{PORT}")
    print(f"Browser URL: {browser_url(HOST, PORT)}")
    print(f"Config files: {[str(path) for path in APP_CONFIG.config_files] or ['built-in defaults only']}")
    print(f"Data dir: {DATA_DIR}")
    print(f"Runtime state: {state_path}")
    if launcher_pid is not None:
        print(f"Launcher PID watch: {launcher_pid}")
    print(f"Managed ports: {managed_server_ports(PORT)}")
    print(f"Hermes home: {HERMES_HOME}")
    print(f"Obsidian vault: {OBSIDIAN_VAULT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Mentat.")
    finally:
        stop_agent_console_processes()
        server.server_close()
        clear_runtime_state()
