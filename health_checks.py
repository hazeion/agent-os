"""Subsystem health checks for the local Mentat dashboard.

This module owns the `/api/health` diagnostic logic. It receives live server
callbacks and paths through `HealthContext` so the main HTTP server keeps its
runtime ownership while health logic stays independently testable.
"""

from __future__ import annotations

import ctypes
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

HEALTH_STATUS_RANK = {"healthy": 0, "degraded": 1, "error": 2}


@dataclass(frozen=True)
class HealthContext:
    base_dir: Path
    hermes_home: Path
    state_db: Path
    sqlite_connect: Callable[[], Any]
    hermes_config: Callable[[], dict]
    read_cron_jobs: Callable[[], dict]
    google_calendar_events: Callable[..., dict]
    now_iso: Callable[[], str]
    file_mtime_iso: Callable[[Path], str | None]
    human_bytes: Callable[[int | float | None], str | None]
    clean_snippet: Callable[[str | None, int], str]


def normalize_health_status(status: str | None) -> str:
    value = str(status or "healthy").strip().lower()
    return value if value in HEALTH_STATUS_RANK else "healthy"


def worst_health_status(*statuses: str | None) -> str:
    normalized = [normalize_health_status(status) for status in statuses if status is not None]
    if not normalized:
        return "healthy"
    return max(normalized, key=lambda status: HEALTH_STATUS_RANK.get(status, 0))


def status_label(status: str | None) -> str:
    normalized = normalize_health_status(status)
    return {
        "healthy": "Healthy",
        "degraded": "Degraded",
        "error": "Error",
    }.get(normalized, "Healthy")


def make_health_subsystem(ctx: HealthContext, key: str, name: str, status: str, summary: str, **extra):
    payload = {
        "key": key,
        "name": name,
        "status": normalize_health_status(status),
        "summary": ctx.clean_snippet(summary, 220),
    }
    payload.update(extra)
    return payload


def windows_memory(ctx: HealthContext):
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
        "total_human": ctx.human_bytes(stat.ullTotalPhys),
        "available_human": ctx.human_bytes(stat.ullAvailPhys),
    }


def disk_details(path: str, ctx: HealthContext):
    drive = Path(path)
    if not drive.exists():
        return None
    usage = shutil.disk_usage(path)
    used_percent = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
    return {
        "total": ctx.human_bytes(usage.total),
        "used": ctx.human_bytes(usage.used),
        "free": ctx.human_bytes(usage.free),
        "used_percent": used_percent,
    }


def disk_status(info: dict | None) -> str:
    if not info:
        return "healthy"
    used_percent = float(info.get("used_percent") or 0)
    if used_percent >= 95:
        return "error"
    if used_percent >= 85:
        return "degraded"
    return "healthy"


def memory_status(info: dict | None) -> str:
    if not info:
        return "healthy"
    load = float(info.get("load_percent") or 0)
    if load >= 95:
        return "error"
    if load >= 85:
        return "degraded"
    return "healthy"


def state_db_health(ctx: HealthContext):
    if not ctx.state_db.exists():
        return make_health_subsystem(
            ctx,
            "state_db",
            "Hermes state.db",
            "error",
            "Hermes state.db is missing.",
            path=str(ctx.state_db),
            exists=False,
            size=None,
            modified_at=None,
        )
    try:
        con = ctx.sqlite_connect()
        if con is None:
            raise RuntimeError("state.db could not be opened in read-only mode")
        row = con.execute("select count(*) from sqlite_master").fetchone()
        con.close()
        return make_health_subsystem(
            ctx,
            "state_db",
            "Hermes state.db",
            "healthy",
            f"Readable SQLite store ({row[0]} schema entries).",
            path=str(ctx.state_db),
            exists=True,
            size=ctx.human_bytes(ctx.state_db.stat().st_size),
            modified_at=ctx.file_mtime_iso(ctx.state_db),
        )
    except Exception as exc:
        return make_health_subsystem(
            ctx,
            "state_db",
            "Hermes state.db",
            "error",
            f"Unreadable SQLite store: {exc}",
            path=str(ctx.state_db),
            exists=True,
            size=ctx.human_bytes(ctx.state_db.stat().st_size),
            modified_at=ctx.file_mtime_iso(ctx.state_db),
            error=ctx.clean_snippet(str(exc), 220),
        )


def config_health(ctx: HealthContext):
    payload = ctx.hermes_config()
    if not payload.get("exists"):
        return make_health_subsystem(
            ctx,
            "config",
            "Hermes config",
            "degraded",
            "Hermes config file not found.",
            path=payload.get("path"),
            exists=False,
            modified_at=None,
            summary_fields=[],
        )
    if payload.get("error"):
        return make_health_subsystem(
            ctx,
            "config",
            "Hermes config",
            "error",
            f"Config exists but could not be read: {payload['error']}",
            path=payload.get("path"),
            exists=True,
            modified_at=payload.get("modified_at"),
            size=payload.get("size"),
            error=ctx.clean_snippet(payload.get("error"), 220),
            summary_fields=sorted((payload.get("summary") or {}).keys()),
        )
    summary_fields = sorted((payload.get("summary") or {}).keys())
    summary = "Masked config is readable"
    if summary_fields:
        summary += f" ({', '.join(summary_fields)} visible in summary)."
    else:
        summary += "."
    return make_health_subsystem(
        ctx,
        "config",
        "Hermes config",
        "healthy",
        summary,
        path=payload.get("path"),
        exists=True,
        modified_at=payload.get("modified_at"),
        size=payload.get("size"),
        summary_fields=summary_fields,
    )


def cron_health(ctx: HealthContext):
    payload = ctx.read_cron_jobs()
    if payload.get("error"):
        return make_health_subsystem(
            ctx,
            "cron",
            "Cron jobs",
            "error",
            f"Cron job store exists but could not be read: {payload['error']}",
            path=payload.get("source"),
            exists=True,
            count=0,
            enabled_count=0,
            error=ctx.clean_snippet(payload.get("error"), 220),
        )
    if not payload.get("exists"):
        return make_health_subsystem(
            ctx,
            "cron",
            "Cron jobs",
            "degraded",
            "Cron job store not initialized yet.",
            path=payload.get("source"),
            exists=False,
            count=0,
            enabled_count=0,
        )
    return make_health_subsystem(
        ctx,
        "cron",
        "Cron jobs",
        "healthy",
        f"{payload.get('enabled_count', 0)} enabled of {payload.get('count', 0)} scheduled jobs.",
        path=payload.get("source"),
        exists=True,
        count=payload.get("count", 0),
        enabled_count=payload.get("enabled_count", 0),
    )


def calendar_health(ctx: HealthContext):
    payload = ctx.google_calendar_events(days=7, limit=50)
    fallback_available = bool((payload.get("summary") or {}).get("fallback_available"))
    stale = bool((payload.get("summary") or {}).get("stale"))
    source = payload.get("source") or "unknown"
    auth = payload.get("auth") or "unknown"
    error_text = ctx.clean_snippet(payload.get("error"), 220) if payload.get("error") else None
    next_event = (payload.get("summary") or {}).get("next_event") or {}

    if source == "google" and auth == "connected" and not error_text:
        summary = "Google Calendar is connected and serving live read-only data."
        if next_event.get("title"):
            summary = f"Google Calendar connected; next event: {next_event['title']}."
        status = "healthy"
    elif fallback_available:
        status = "degraded"
        summary = "Using local calendar.json fallback instead of live Google data."
        if stale:
            summary = "Using stale local calendar.json fallback; live Google data unavailable."
        if error_text:
            summary = f"Calendar fell back to local data: {error_text}"
    else:
        status = "error"
        summary = error_text or "Calendar has no live Google data and no local fallback available."

    return make_health_subsystem(
        ctx,
        "calendar",
        "Calendar",
        status,
        summary,
        source=source,
        auth=auth,
        read_only=bool(payload.get("read_only")),
        stale=stale,
        fallback_available=fallback_available,
        item_count=(payload.get("summary") or {}).get("count", 0),
        next_event=next_event,
        error=error_text,
        cache=payload.get("cache"),
    )


def host_health(ctx: HealthContext, memory: dict | None, disk: dict):
    memory_state = memory_status(memory)
    disk_states = [disk_status(info) for info in disk.values() if info]
    status = worst_health_status(memory_state, *disk_states)
    highlights = []
    if memory and memory_state != "healthy":
        highlights.append(f"memory {memory.get('load_percent')}% used")
    for path, info in disk.items():
        if info and disk_status(info) != "healthy":
            highlights.append(f"{path} {info.get('used_percent')}% used")
    summary = "Memory and disk usage are within thresholds."
    if highlights:
        summary = "Host pressure detected: " + ", ".join(highlights)
    return make_health_subsystem(
        ctx,
        "host_resources",
        "Host resources",
        status,
        summary,
        memory=memory,
        disk=disk,
    )


def health(ctx: HealthContext):
    disk = {
        "E:/": disk_details("E:/", ctx) or disk_details(str(ctx.base_dir.anchor or "."), ctx),
        "C:/": disk_details("C:/", ctx),
    }
    memory = windows_memory(ctx)
    subsystems = [
        state_db_health(ctx),
        config_health(ctx),
        calendar_health(ctx),
        cron_health(ctx),
        host_health(ctx, memory, disk),
    ]
    status = worst_health_status(*(subsystem.get("status") for subsystem in subsystems))
    degraded_items = [item for item in subsystems if item.get("status") == "degraded"]
    error_items = [item for item in subsystems if item.get("status") == "error"]
    if error_items:
        summary = "; ".join(item.get("summary", item.get("name", "Subsystem error")) for item in error_items[:2])
    elif degraded_items:
        summary = "; ".join(item.get("summary", item.get("name", "Subsystem degraded")) for item in degraded_items[:2])
    else:
        summary = "All monitored dashboard subsystems are healthy."
    state_db_item = next((item for item in subsystems if item.get("key") == "state_db"), {})
    return {
        "now": ctx.now_iso(),
        "status": status,
        "status_label": status_label(status),
        "summary": ctx.clean_snippet(summary, 240),
        "hermes_home": str(ctx.hermes_home),
        "state_db_exists": bool(state_db_item.get("exists")),
        "state_db_size": state_db_item.get("size"),
        "memory": memory,
        "disk": disk,
        "status_counts": {
            "healthy": sum(1 for item in subsystems if item.get("status") == "healthy"),
            "degraded": len(degraded_items),
            "error": len(error_items),
        },
        "subsystems": subsystems,
    }
