"""Privacy-aware persistence for Mentat Agent Console run summaries."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from json_store import lock_for, write_json_atomic

SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
EVENT_SCHEMA_VERSION = 1
DEFAULT_RETENTION = 24
EVENT_RETENTION = 40
PROMPT_EXCERPT_LIMIT = 500
RESPONSE_EXCERPT_LIMIT = 2_000
ERROR_EXCERPT_LIMIT = 1_000
EVENT_TEXT_LIMIT = 500
ACTIVE_STATUSES = {"queued", "running", "cancelling"}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|password|secret)\s*([:=])\s*([^\s,;]+)"),
)
_SECRET_KEY_PATTERN = re.compile(r"(?i)(api[_-]?key|token|password|secret|credential|authorization|auth)")


def _redact(value: Any) -> str:
    text = str(value or "")
    text = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub("[REDACTED]", text)
    return _SECRET_PATTERNS[2].sub(r"\1\2[REDACTED]", text)


def bounded_excerpt(value: Any, limit: int) -> tuple[str, bool]:
    text = _redact(value).strip()
    truncated = len(text) > limit
    return (text[:limit].rstrip(), truncated)


def _safe_event_data(value: Any, *, depth: int = 0) -> Any:
    """Return a small JSON-safe, redacted event payload or an empty object."""
    if depth > 3:
        return None
    if isinstance(value, dict):
        return {
            str(key)[:80]: (
                "[REDACTED]"
                if _SECRET_KEY_PATTERN.search(str(key))
                else _safe_event_data(item, depth=depth + 1)
            )
            for key, item in list(value.items())[:20]
        }
    if isinstance(value, list):
        return [_safe_event_data(item, depth=depth + 1) for item in value[:20]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return bounded_excerpt(value, EVENT_TEXT_LIMIT)[0]


def normalize_events(run_id: str, raw_events: Any) -> list[dict]:
    """Validate/migrate retained events into the stable public event contract."""
    if not isinstance(raw_events, list):
        return []
    normalized: list[dict] = []
    last_sequence = 0
    for item in raw_events[-EVENT_RETENTION:]:
        if not isinstance(item, dict):
            continue
        try:
            candidate = int(item.get("sequence") or item.get("cursor") or 0)
        except (TypeError, ValueError):
            candidate = 0
        sequence = candidate if candidate > last_sequence else last_sequence + 1
        event_type = str(item.get("type") or item.get("kind") or "status")
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", event_type):
            event_type = "status"
        display_text = bounded_excerpt(
            item.get("display_text") or item.get("message") or "Agent run updated",
            EVENT_TEXT_LIMIT,
        )[0]
        timestamp = item.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp:
            continue
        normalized.append({
            "schema_version": EVENT_SCHEMA_VERSION,
            "id": str(item.get("id") or f"event_{run_id}_{sequence}"),
            "run_id": run_id,
            "sequence": sequence,
            "cursor": sequence,
            "type": event_type,
            # Compatibility aliases for existing clients.
            "kind": event_type,
            "timestamp": timestamp,
            "data": _safe_event_data(item.get("data")) if isinstance(item.get("data"), dict) else {},
            "display_text": display_text,
            "message": display_text,
        })
        last_sequence = sequence
    return normalized


def summarize_run(run: dict) -> dict:
    prompt, prompt_truncated = bounded_excerpt(run.get("prompt"), PROMPT_EXCERPT_LIMIT)
    response, response_truncated = bounded_excerpt(run.get("response"), RESPONSE_EXCERPT_LIMIT)
    error, error_truncated = bounded_excerpt(run.get("error"), ERROR_EXCERPT_LIMIT)
    events = normalize_events(str(run.get("id") or ""), run.get("events"))
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
        "events": events,
        "event_cursor": events[-1]["cursor"] if events else 0,
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
    events = normalize_events(run_id, summary.get("events"))
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
        "events": events,
        "event_cursor": events[-1]["cursor"] if events else 0,
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
    if not isinstance(payload, dict) or payload.get("schema_version") not in {
        LEGACY_SCHEMA_VERSION,
        SCHEMA_VERSION,
    }:
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
            next_sequence = int(run.get("event_cursor") or 0) + 1
            run["events"].append({
                "schema_version": EVENT_SCHEMA_VERSION,
                "id": f"event_recovered_{run['id']}",
                "run_id": run["id"],
                "sequence": next_sequence,
                "cursor": next_sequence,
                "type": "error",
                "kind": "error",
                "data": {"reason": "server_restart"},
                "display_text": "Run interrupted by Mentat restart",
                "message": "Run interrupted by Mentat restart",
                "timestamp": interrupted_at,
            })
            run["event_cursor"] = next_sequence
    return runs, recovered
