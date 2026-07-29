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

from mentat.version import DISPLAY_VERSION, __version__

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
    hermes_diagnostics: Callable[[], dict]


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


def path_size(ctx: HealthContext, path: Path) -> str | None:
    try:
        return ctx.human_bytes(path.stat().st_size)
    except OSError:
        return None


def state_db_health(ctx: HealthContext):
    try:
        state_db_exists = ctx.state_db.exists()
    except OSError as exc:
        return make_health_subsystem(
            ctx,
            "state_db",
            "Hermes state.db",
            "error",
            "Hermes state.db is not accessible.",
            exists=None,
            size=None,
            modified_at=None,
            error="state_db_not_accessible",
        )
    if not state_db_exists:
        return make_health_subsystem(
            ctx,
            "state_db",
            "Hermes state.db",
            "error",
            "Hermes state.db is missing.",
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
            exists=True,
            size=path_size(ctx, ctx.state_db),
            modified_at=ctx.file_mtime_iso(ctx.state_db),
        )
    except Exception as exc:
        return make_health_subsystem(
            ctx,
            "state_db",
            "Hermes state.db",
            "error",
            "Hermes state.db could not be read safely.",
            exists=True,
            size=path_size(ctx, ctx.state_db),
            modified_at=ctx.file_mtime_iso(ctx.state_db),
            error="state_db_unreadable",
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
            "Hermes config exists but could not be read safely.",
            exists=True,
            modified_at=payload.get("modified_at"),
            size=payload.get("size"),
            error="config_unreadable",
            summary_fields=sorted((payload.get("summary") or {}).keys()),
        )
    summary_fields = sorted((payload.get("summary") or {}).keys())
    summary = "Public-safe config summary is readable"
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
            "Cron job store exists but could not be read safely.",
            exists=True,
            count=0,
            enabled_count=0,
            error="cron_store_unreadable",
        )
    if not payload.get("exists"):
        return make_health_subsystem(
            ctx,
            "cron",
            "Cron jobs",
            "degraded",
            "Cron job store not initialized yet.",
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
    has_error = bool(payload.get("error"))
    next_event = (payload.get("summary") or {}).get("next_event") or {}

    if source == "google" and auth == "connected" and not has_error:
        summary = "Google Calendar is connected and serving live read-only data."
        if next_event.get("title"):
            summary = f"Google Calendar connected; next event: {next_event['title']}."
        status = "healthy"
    elif fallback_available:
        status = "degraded"
        summary = "Using local calendar.json fallback instead of live Google data."
        if stale:
            summary = "Using stale local calendar.json fallback; live Google data unavailable."
        if has_error:
            summary = "Calendar fell back to local data because live Google Calendar is unavailable."
    else:
        status = "error"
        summary = "Calendar has no live Google data and no local fallback available."

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


def remote_hermes_health(ctx: HealthContext, diagnostics: dict):
    status = diagnostics.get("status")
    if status not in HEALTH_STATUS_RANK:
        status = "error"
    readiness = diagnostics.get("readiness")
    if type(readiness) is not dict:
        readiness = {}
    capabilities = diagnostics.get("capabilities")
    if type(capabilities) is not list:
        capabilities = []
    return make_health_subsystem(
        ctx,
        "remote_hermes",
        "Remote Hermes",
        status,
        diagnostics.get("summary") or "Remote Hermes health is unavailable.",
        mode=diagnostics.get("mode") or "unavailable",
        category=diagnostics.get("category") or "unsupported",
        label=ctx.clean_snippet(diagnostics.get("label"), 80),
        liveness=diagnostics.get("liveness"),
        version=ctx.clean_snippet(diagnostics.get("version"), 80),
        model=ctx.clean_snippet(diagnostics.get("model"), 160),
        readiness=readiness,
        capabilities=capabilities,
    )


def health(ctx: HealthContext):
    if sys.platform.startswith("win"):
        disk = {
            path: details
            for path in ("C:/", "E:/")
            if (details := disk_details(path, ctx)) is not None
        }
        if not disk:
            root = str(ctx.base_dir.anchor or ".")
            disk[root] = disk_details(root, ctx)
    else:
        root = str(ctx.base_dir.anchor or "/")
        disk = {root: disk_details(root, ctx)}
    memory = windows_memory(ctx)
    try:
        hermes_diagnostics = ctx.hermes_diagnostics()
    except Exception:
        hermes_diagnostics = {
            "mode": "unavailable",
            "status": "error",
            "category": "unsupported",
            "summary": "Hermes connection health is unavailable.",
        }
    local_mode = hermes_diagnostics.get("mode") == "local"
    if local_mode:
        subsystems = [
            state_db_health(ctx),
            config_health(ctx),
            calendar_health(ctx),
            cron_health(ctx),
            host_health(ctx, memory, disk),
        ]
    else:
        subsystems = [
            remote_hermes_health(ctx, hermes_diagnostics),
            calendar_health(ctx),
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
    payload = {
        "version": __version__,
        "display_version": DISPLAY_VERSION,
        "now": ctx.now_iso(),
        "status": status,
        "status_label": status_label(status),
        "summary": ctx.clean_snippet(summary, 240),
        "memory": memory,
        "disk": disk,
        "status_counts": {
            "healthy": sum(1 for item in subsystems if item.get("status") == "healthy"),
            "degraded": len(degraded_items),
            "error": len(error_items),
        },
        "subsystems": subsystems,
    }
    return payload
