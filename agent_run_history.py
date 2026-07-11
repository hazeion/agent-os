"""Privacy-aware persistence for Mentat Agent Console run summaries."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from json_store import lock_for, write_json_atomic

SCHEMA_VERSION = 1
DEFAULT_RETENTION = 24
PROMPT_EXCERPT_LIMIT = 500
RESPONSE_EXCERPT_LIMIT = 2_000
ERROR_EXCERPT_LIMIT = 1_000
ACTIVE_STATUSES = {"queued", "running", "cancelling"}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\s*([:=])\s*([^\s,;]+)"),
)


def _redact(value: Any) -> str:
    text = str(value or "")
    text = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub("[REDACTED]", text)
    return _SECRET_PATTERNS[2].sub(r"\1\2[REDACTED]", text)


def bounded_excerpt(value: Any, limit: int) -> tuple[str, bool]:
    text = _redact(value).strip()
    truncated = len(text) > limit
    return (text[:limit].rstrip(), truncated)


def summarize_run(run: dict) -> dict:
    prompt, prompt_truncated = bounded_excerpt(run.get("prompt"), PROMPT_EXCERPT_LIMIT)
    response, response_truncated = bounded_excerpt(run.get("response"), RESPONSE_EXCERPT_LIMIT)
    error, error_truncated = bounded_excerpt(run.get("error"), ERROR_EXCERPT_LIMIT)
    return {
        "id": str(run.get("id") or ""),
        "agent_id": str(run.get("agent_id") or "hermes"),
        "agent_name": str(run.get("agent_name") or "Hermes"),
        "model": str(run.get("model") or ""),
        "status": str(run.get("status") or "failed"),
        "session_id": run.get("session_id") or None,
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "started_at": run.get("started_at"),
        "completed_at": run.get("completed_at"),
        "duration_seconds": run.get("duration_seconds"),
        "prompt_excerpt": prompt,
        "prompt_truncated": bool(run.get("prompt_truncated")) or prompt_truncated,
        "response_excerpt": response,
        "response_truncated": bool(run.get("response_truncated")) or response_truncated,
        "error_excerpt": error,
        "error_truncated": bool(run.get("error_truncated")) or error_truncated,
    }


def _sort_key(run: dict) -> tuple[str, str]:
    return str(run.get("created_at") or ""), str(run.get("id") or "")


def save_run_summaries(path: Path, runs: list[dict], *, retention: int = DEFAULT_RETENTION) -> None:
    summaries = [summarize_run(run) for run in runs if isinstance(run, dict) and run.get("id")]
    summaries.sort(key=_sort_key, reverse=True)
    payload = {"schema_version": SCHEMA_VERSION, "runs": summaries[:retention]}
    with lock_for(path):
        write_json_atomic(path, payload)


def _hydrate(summary: dict) -> dict | None:
    run_id = summary.get("id")
    if not isinstance(run_id, str) or not run_id:
        return None
    return {
        "id": run_id,
        "agent_id": str(summary.get("agent_id") or "hermes"),
        "agent_name": str(summary.get("agent_name") or "Hermes"),
        "model": str(summary.get("model") or ""),
        "status": str(summary.get("status") or "failed"),
        "session_id": summary.get("session_id") or None,
        "prompt": str(summary.get("prompt_excerpt") or ""),
        "prompt_truncated": bool(summary.get("prompt_truncated")),
        "response": str(summary.get("response_excerpt") or ""),
        "response_truncated": bool(summary.get("response_truncated")),
        "error": str(summary.get("error_excerpt") or ""),
        "error_truncated": bool(summary.get("error_truncated")),
        "events": [],
        "created_at": summary.get("created_at"),
        "updated_at": summary.get("updated_at"),
        "started_at": summary.get("started_at"),
        "completed_at": summary.get("completed_at"),
        "duration_seconds": summary.get("duration_seconds"),
        "persisted_summary": True,
    }


def load_run_summaries(
    path: Path,
    *,
    now: Callable[[], str] | None = None,
    retention: int = DEFAULT_RETENTION,
) -> tuple[list[dict], bool]:
    """Load summaries, returning an empty history for absent/corrupt/unknown data.

    The boolean indicates whether recovered active runs were marked interrupted.
    """
    try:
        with lock_for(path):
            payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return [], False
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return [], False
    raw_runs = payload.get("runs")
    if not isinstance(raw_runs, list):
        return [], False

    runs = [run for item in raw_runs if isinstance(item, dict) if (run := _hydrate(item))]
    runs.sort(key=_sort_key, reverse=True)
    runs = runs[:retention]
    recovered = False
    interrupted_at = (now or (lambda: datetime.now().astimezone().isoformat(timespec="seconds")))()
    for run in runs:
        if run["status"] in ACTIVE_STATUSES:
            recovered = True
            run["status"] = "interrupted"
            run["updated_at"] = interrupted_at
            run["completed_at"] = interrupted_at
            run["error"] = "Mentat restarted before this run finished."
            run["events"] = [{
                "id": f"event_recovered_{run['id']}",
                "kind": "error",
                "message": "Run interrupted by Mentat restart",
                "timestamp": interrupted_at,
            }]
    return runs, recovered
