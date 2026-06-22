#!/usr/bin/env python
"""Agent OS local dashboard server.

Read-only toward Hermes core files. Dashboard write-back is limited to
project-owned data/*.json files.
"""

from __future__ import annotations

import ctypes
import json
import mimetypes
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from health_checks import HEALTH_STATUS_RANK, HealthContext, health as build_health_payload
from runtime_config import (
    AppConfig,
    DEFAULT_APP_NAME,
    DEFAULT_HOST,
    DEFAULT_PORT,
    default_hermes_home,
    default_obsidian_vault,
    load_app_config,
    parse_cli_args,
)

BASE_DIR = Path(__file__).resolve().parent

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
    raw = (os.environ.get("AGENT_OS_LAUNCHER_PID") or "").strip()
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
                print(f"Launcher PID {launcher_pid} is gone; stopping Agent OS.")
                try:
                    http_server.shutdown()
                except Exception:
                    pass
                break

    threading.Thread(target=watch, daemon=True, name="agent-os-launcher-watch").start()
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
ALLOWED_DATA_WRITES = {"attention.json", "projects.json", "tasks.json", "dashboard.json", "calendar.json"}
CALENDAR_CACHE_TTL_SECONDS = 300
CALENDAR_CACHE = {"key": None, "payload": None, "fetched_at": None}

apply_runtime_config(load_app_config())

def note_sort_key(path: Path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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



def read_json_file(name: str, default):
    path = DATA_DIR / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON in {path}: {exc}"}


def google_credentials(scopes: list[str]):

    if not GOOGLE_TOKEN.exists():
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


def write_json_file(name: str, payload):
    """Write only explicitly allowlisted dashboard-owned JSON files under data/."""
    if name not in ALLOWED_DATA_WRITES or "/" in name or "\\" in name:
        raise ValueError(f"Refusing to write non-allowlisted dashboard data file: {name}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data_root = DATA_DIR.resolve()
    path = (DATA_DIR / name).resolve()
    if path.parent != data_root:
        raise ValueError(f"Refusing to write outside dashboard data directory: {name}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


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
    except Exception as exc:
        return calendar_payload(fallback, "local", "error", days=days, error=str(exc), fallback_available=fallback_available)


SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|password|secret|credential|auth)", re.I)
SECRET_VALUE_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{12,})")


def mask_config_text(text: str) -> str:
    """Return config text safe to render in the browser."""
    masked_lines = []
    for line in text.splitlines():
        if SECRET_KEY_RE.search(line):
            if ":" in line:
                masked_lines.append(re.sub(r":.*$", ": ***", line))
            elif "=" in line:
                masked_lines.append(re.sub(r"=.*$", "=***", line))
            else:
                masked_lines.append("***")
            continue
        masked_lines.append(SECRET_VALUE_RE.sub("***", line))
    return "\n".join(masked_lines)


def first_config_value(masked_text: str, key: str) -> str | None:
    match = re.search(rf"^[ \t]*{re.escape(key)}[ \t]*:[ \t]*([^#\n]+)", masked_text, re.M)
    if not match:
        return None
    value = match.group(1).strip().strip("'\"")
    if value in {"", "***", "{}", "[]"}:
        return None
    return value


def hermes_config():
    if not CONFIG_PATH.exists():
        return {"exists": False, "path": str(CONFIG_PATH), "summary": {}, "masked_config": ""}
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
        masked = mask_config_text(raw)
        lines = masked.splitlines()
        if len(lines) > 360:
            masked = "\n".join(lines[:360] + ["# … truncated for dashboard display …"])
        summary = {
            "default_model": first_config_value(masked, "default"),
            "provider": first_config_value(masked, "provider"),
            "max_turns": first_config_value(masked, "max_turns"),
            "reasoning_effort": first_config_value(masked, "reasoning_effort"),
        }
        return {
            "exists": True,
            "path": str(CONFIG_PATH),
            "size": human_bytes(CONFIG_PATH.stat().st_size),
            "modified_at": file_mtime_iso(CONFIG_PATH),
            "summary": {k: v for k, v in summary.items() if v},
            "masked_config": masked,
        }
    except Exception as exc:
        return {"exists": True, "path": str(CONFIG_PATH), "error": str(exc), "summary": {}, "masked_config": ""}


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


def read_cron_jobs():
    if not CRON_JOBS.exists():
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
                "schedule": job.get("schedule") or job.get("cron") or job.get("interval") or "unknown",
                "enabled": enabled,
                "last_run": job.get("last_run") or job.get("lastRunAt") or job.get("last_run_at"),
                "next_run": job.get("next_run") or job.get("nextRunAt") or job.get("next_run_at"),
                "last_status": job.get("last_status") or job.get("status") or job.get("lastStatus") or "unknown",
            }
        )
    return {
        "exists": True,
        "source": str(CRON_JOBS),
        "count": len(normalized),
        "enabled_count": sum(1 for j in normalized if j["enabled"]),
        "jobs": normalized,
    }


def sqlite_connect():
    if not STATE_DB.exists():
        return None
    uri = f"file:{STATE_DB.as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def recent_sessions(limit: int = 8):
    if not STATE_DB.exists():
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
        return {
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
        }, 200
    except Exception as exc:
        return {"error": str(exc), "source": str(STATE_DB)}, 500


def obsidian_notes():
    notes = []
    if not OBSIDIAN_VAULT.exists():
        return {"vault": str(OBSIDIAN_VAULT), "exists": False, "note_count": 0, "notes": notes}

    markdown_files = sorted(OBSIDIAN_VAULT.rglob("*.md"), key=note_sort_key, reverse=True)
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
    return {"vault": str(OBSIDIAN_VAULT), "exists": True, "note_count": len(notes), "notes": notes}


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

    attention = read_json_file("attention.json", [])
    if not isinstance(attention, list):
        return {"error": "attention.json must contain a list"}, 500

    resolved_item = None
    for item in attention:
        if not isinstance(item, dict):
            continue
        if item.get("id") == attention_id:
            item["status"] = "resolved"
            item["resolved_at"] = now_iso()
            resolved_item = item
            break

    if resolved_item is None:
        return {"error": f"Attention item not found: {attention_id}"}, 404

    write_json_file("attention.json", attention)
    tasks = read_json_file("tasks.json", [])
    return {"ok": True, "resolved": resolved_item, "attention": attention, "open_count": len(open_attention_items(attention, tasks))}, 200


POST_ROUTES = {
    re.compile(r"^/api/attention/([^/]+)/resolve$"): resolve_attention_item,
}


API_ROUTES = {
    "/api/overview": overview,
    "/api/projects": lambda: {"projects": read_json_file("projects.json", [])},
    "/api/tasks": lambda: {"tasks": read_json_file("tasks.json", [])},
    "/api/attention": attention_payload,
    "/api/calendar": google_calendar_events,
    "/api/obsidian-notes": obsidian_notes,
    "/api/hermes/crons": read_cron_jobs,
    "/api/hermes/sessions": lambda: recent_sessions(limit=12),
    "/api/hermes/config": hermes_config,
    "/api/health": health,
}


GET_ROUTES = {
    re.compile(r"^/api/hermes/sessions/([^/]+)$"): session_detail,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentOS/0.1"

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

    def send_json(self, payload, status=200):
        body = json.dumps(payload, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.send_error(500, str(exc))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/hermes/search":
            try:
                query = parse_qs(parsed.query).get("q", [""])[0]
                self.send_json(search_messages(query))
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        if parsed.path in API_ROUTES:
            try:
                self.send_json(API_ROUTES[parsed.path]())
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        for pattern, handler in GET_ROUTES.items():
            match = pattern.match(parsed.path)
            if not match:
                continue
            try:
                message_id = parse_qs(parsed.query).get("message_id", [None])[0]
                payload, status = handler(*[unquote(part) for part in match.groups()], message_id)
                self.send_json(payload, status=status)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        self.send_static(self.path)

    def do_POST(self):
        parsed = urlparse(self.path)
        for pattern, handler in POST_ROUTES.items():
            match = pattern.match(parsed.path)
            if not match:
                continue
            try:
                payload, status = handler(*[unquote(part) for part in match.groups()])
                self.send_json(payload, status=status)
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        self.send_json({"error": "Not found"}, status=404)


if __name__ == "__main__":
    cli_args = parse_cli_args()
    apply_runtime_config(load_app_config(cli_args))
    if cli_args.print_config:
        print(json.dumps(runtime_config_summary(), indent=2))
        raise SystemExit(0)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    launcher_pid = start_launcher_watch(server)
    state_path = write_runtime_state()
    print(f"Mentat listening on {HOST}:{PORT}")
    if HOST in {"0.0.0.0", "::"}:
        print(f"Local browser URL: http://localhost:{PORT}")
    else:
        print(f"Browser URL: http://{HOST}:{PORT}")
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
        print("\nStopping Agent OS.")
    finally:
        server.server_close()
        clear_runtime_state()
