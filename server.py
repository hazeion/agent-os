#!/usr/bin/env python
"""Agent OS local dashboard server.

Read-only toward Hermes core files. Writes only happen manually to data/*.json
for now; this server currently exposes read endpoints only.
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
from urllib.parse import parse_qs, urlparse

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


def overview():
    projects = read_json_file("projects.json", [])
    tasks = read_json_file("tasks.json", [])
    attention = read_json_file("attention.json", [])
    calendar = read_json_file("calendar.json", [])
    crons = read_cron_jobs()
    sessions = recent_sessions(limit=5)

    open_attention = [a for a in attention if a.get("status", "open") == "open"] if isinstance(attention, list) else []
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


API_ROUTES = {
    "/api/overview": overview,
    "/api/projects": lambda: {"projects": read_json_file("projects.json", [])},
    "/api/tasks": lambda: {"tasks": read_json_file("tasks.json", [])},
    "/api/attention": lambda: {"attention": read_json_file("attention.json", [])},
    "/api/calendar": lambda: {"items": read_json_file("calendar.json", [])},
    "/api/obsidian-notes": obsidian_notes,
    "/api/hermes/crons": read_cron_jobs,
    "/api/hermes/sessions": lambda: recent_sessions(limit=12),
    "/api/health": health,
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
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.send_error(500, str(exc))

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in API_ROUTES:
            try:
                self.send_json(API_ROUTES[parsed.path]())
            except Exception as exc:
                self.send_json({"error": str(exc)}, status=500)
            return
        self.send_static(self.path)


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
