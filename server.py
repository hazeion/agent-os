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
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PUBLIC_DIR = BASE_DIR / "public"
PORT = int(os.environ.get("AGENT_OS_PORT", "8888"))


def default_hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        return Path.home() / "AppData" / "Local" / "hermes"
    return Path.home() / ".hermes"


HERMES_HOME = default_hermes_home()
OBSIDIAN_VAULT = Path(os.environ.get("OBSIDIAN_VAULT_PATH", "E:/Obsidian Notes"))
STATE_DB = HERMES_HOME / "state.db"
CRON_JOBS = HERMES_HOME / "cron" / "jobs.json"
CONFIG_PATH = HERMES_HOME / "config.yaml"
GOOGLE_TOKEN = HERMES_HOME / "google_token.json"

PROJECT_NOTES = [
    "Agentic OS Project Home.md",
    "Agent OS - Research Summary & Prompt Stack.md",
    "Agent OS - Implementation Spec.md",
]


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
    """Return Google OAuth credentials if the local Hermes token exists."""
    if not GOOGLE_TOKEN.exists():
        return None, "Google OAuth token not found"
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN), scopes=scopes)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            payload = json.loads(creds.to_json())
            payload.setdefault("type", "authorized_user")
            GOOGLE_TOKEN.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if not creds.valid:
            return None, "Google OAuth token is invalid"
        return creds, None
    except Exception as exc:
        return None, str(exc)


def write_json_file(name: str, payload):
    """Write only dashboard-owned local JSON files under data/."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / name
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


def google_calendar_events(days: int = 14, limit: int = 20):
    """Read upcoming Google Calendar events with local JSON fallback metadata."""
    scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    creds, auth_error = google_credentials(scopes)
    fallback = read_json_file("calendar.json", [])
    if creds is None:
        return {
            "items": fallback if isinstance(fallback, list) else [],
            "source": "local",
            "auth": "not_connected",
            "error": auth_error,
        }

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
        return {
            "items": items,
            "source": "google",
            "auth": "connected",
            "calendar": "primary",
            "range_days": days,
            "updated_at": now_iso(),
        }
    except Exception as exc:
        return {
            "items": fallback if isinstance(fallback, list) else [],
            "source": "local",
            "auth": "error",
            "error": str(exc),
        }


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
    for name in PROJECT_NOTES:
        path = OBSIDIAN_VAULT / name
        if not path.exists():
            notes.append({"name": name, "exists": False, "path": str(path)})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        excerpt = clean_snippet(re.sub(r"[#>*`\-\[\]()_]", " ", text), 260)
        notes.append(
            {
                "name": name,
                "title": name.removesuffix(".md"),
                "exists": True,
                "path": str(path),
                "modified_at": file_mtime_iso(path),
                "size": human_bytes(path.stat().st_size),
                "excerpt": excerpt,
            }
        )
    return {"vault": str(OBSIDIAN_VAULT), "notes": notes}


def windows_memory():
    if not sys.platform.startswith("win"):
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    return {
        "load_percent": int(stat.dwMemoryLoad),
        "total": int(stat.ullTotalPhys),
        "available": int(stat.ullAvailPhys),
        "total_human": human_bytes(stat.ullTotalPhys),
        "available_human": human_bytes(stat.ullAvailPhys),
    }


def health():
    disk_e = shutil.disk_usage("E:/") if Path("E:/").exists() else shutil.disk_usage(str(BASE_DIR.anchor or "."))
    disk_c = shutil.disk_usage("C:/") if Path("C:/").exists() else None
    return {
        "now": now_iso(),
        "status": "healthy",
        "hermes_home": str(HERMES_HOME),
        "state_db_exists": STATE_DB.exists(),
        "state_db_size": human_bytes(STATE_DB.stat().st_size) if STATE_DB.exists() else None,
        "memory": windows_memory(),
        "disk": {
            "E:/": {
                "total": human_bytes(disk_e.total),
                "used": human_bytes(disk_e.used),
                "free": human_bytes(disk_e.free),
                "used_percent": round(disk_e.used / disk_e.total * 100, 1),
            },
            "C:/": None
            if disk_c is None
            else {
                "total": human_bytes(disk_c.total),
                "used": human_bytes(disk_c.used),
                "free": human_bytes(disk_c.free),
                "used_percent": round(disk_c.used / disk_c.total * 100, 1),
            },
        },
    }


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
    calendar = read_json_file("calendar.json", [])
    crons = read_cron_jobs()
    sessions = recent_sessions(limit=5)

    open_attention = open_attention_items(attention, tasks)
    active_tasks = [t for t in tasks if t.get("status") in {"todo", "in_progress", "waiting", "needs_attention"}] if isinstance(tasks, list) else []
    active_projects = [p for p in projects if p.get("status") == "active"] if isinstance(projects, list) else []
    week_ago = datetime.now().astimezone() - timedelta(days=7)
    completed_this_week = []
    if isinstance(tasks, list):
        for task in tasks:
            completed_at = parse_iso(task.get("completed_at"))
            if task.get("status") == "completed" and completed_at and completed_at >= week_ago:
                completed_this_week.append(task)

    return {
        "generated_at": now_iso(),
        "cards": {
            "needs_attention": len(open_attention),
            "active_tasks": len(active_tasks),
            "completed_this_week": len(completed_this_week),
            "scheduled_crons": crons.get("count", 0),
            "recent_sessions": len(sessions.get("sessions", [])),
            "active_projects": len(active_projects),
            "calendar_items": len(calendar) if isinstance(calendar, list) else 0,
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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Agent OS running at http://localhost:{PORT}")
    print(f"Hermes home: {HERMES_HOME}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Agent OS.")
        server.server_close()
