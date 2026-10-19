"""Bounded private summary and event projections for canonical SQL Runs."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 3
EVENT_SCHEMA_VERSION = 1
EVENT_RETENTION = 40
PROMPT_EXCERPT_LIMIT = 500
RESPONSE_EXCERPT_LIMIT = 2_000
ERROR_EXCERPT_LIMIT = 1_000
EVENT_TEXT_LIMIT = 500
ATTACHMENT_LIMIT = 25
ATTACHMENT_STATES = {
    "staged", "attached", "orphaned", "pending_delete", "deleting", "missing"
}

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+"),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?token|token|password|secret|credential)\s*([:=])\s*([^\s,;]+)"
    ),
    re.compile(r"(?i)\b(gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{12,})\b"),
    re.compile(r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(
        r"-----BEGIN [^-\n]+ PRIVATE KEY-----.*?(?:-----END [^-\n]+ PRIVATE KEY-----|\Z)",
        re.I | re.S,
    ),
)
_SECRET_KEY_PATTERN = re.compile(r"(?i)(api[_-]?key|token|password|secret|credential|authorization|auth)")
_PRIVATE_PATH_PATTERNS = (
    re.compile(r"(?<!:)\/(?:Users|home|root|private|tmp|var|opt|etc)\/[^\s\"'<>]+"),
    re.compile(r"\b[A-Za-z]:\\[^\r\n\"'<>]+"),
)
_ORCHESTRATION_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}")


def _valid_binding_identifier(name: str, value: Any) -> bool:
    pattern = _TASK_ID_PATTERN if name == "task_id" else _ORCHESTRATION_ID_PATTERN
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _valid_runtime_binding_event(item: Any) -> bool:
    if not isinstance(item, dict) or item.get("type") != "runtime.bound":
        return False
    data = item.get("data")
    return isinstance(data, dict) and all(
        _valid_binding_identifier(name, data.get(name))
        for name in ("mentat_agent_id", "task_id")
    )


def retained_event_window(raw_events: Any) -> list[dict]:
    """Retain newest events while pinning one valid runtime binding."""
    if not isinstance(raw_events, list):
        return []
    events = [item for item in raw_events if isinstance(item, dict)]
    if len(events) <= EVENT_RETENTION:
        return events
    newest = events[-EVENT_RETENTION:]
    if any(_valid_runtime_binding_event(item) for item in newest):
        return newest
    binding = next(
        (item for item in reversed(events[:-EVENT_RETENTION]) if _valid_runtime_binding_event(item)),
        None,
    )
    return ([binding] + events[-(EVENT_RETENTION - 1):]) if binding else newest


def redact_sensitive_text(value: Any) -> str:
    """Return text with common credentials and private-key material removed."""
    text = str(value or "")
    text = _SECRET_PATTERNS[0].sub(r"\1[REDACTED]", text)
    text = _SECRET_PATTERNS[1].sub("[REDACTED]", text)
    text = _SECRET_PATTERNS[2].sub(r"\1\2[REDACTED]", text)
    for pattern in _SECRET_PATTERNS[3:]:
        text = pattern.sub("[REDACTED]", text)
    return text


def _redact(value: Any) -> str:
    """Backward-compatible private alias for the shared redaction helper."""
    return redact_sensitive_text(value)


def bounded_excerpt(value: Any, limit: int) -> tuple[str, bool]:
    text = _redact(value).strip()
    truncated = len(text) > limit
    return (text[:limit].rstrip(), truncated)


def bounded_public_excerpt(value: Any, limit: int) -> tuple[str, bool]:
    """Return bounded text with credentials and private local paths removed."""

    text = redact_sensitive_text(value)
    for pattern in _PRIVATE_PATH_PATTERNS:
        text = pattern.sub("[redacted-path]", text)
    text = text.strip()
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
    for item in retained_event_window(raw_events):
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


def normalize_attachments(raw_attachments: Any) -> list[dict]:
    """Keep only path-free attachment metadata suitable for retained history."""
    if not isinstance(raw_attachments, list):
        return []
    normalized: list[dict] = []
    seen: set[str] = set()
    for item in raw_attachments[:ATTACHMENT_LIMIT]:
        if not isinstance(item, dict):
            continue
        attachment_id = str(item.get("id") or "")
        if not re.fullmatch(r"attachment_[a-f0-9]{32}", attachment_id) or attachment_id in seen:
            continue
        kind = str(item.get("kind") or "")
        if kind not in {"image", "text"}:
            continue
        mime_type = bounded_excerpt(item.get("mime_type") or "", 160)[0]
        if not mime_type or any(character in mime_type for character in "\r\n"):
            continue
        try:
            byte_size = max(0, int(item.get("byte_size") or 0))
        except (TypeError, ValueError):
            continue
        name = bounded_excerpt(item.get("name") or "attachment", 255)[0]
        if "/" in name or "\\" in name:
            continue
        name = Path(name).name
        if not name:
            name = "attachment"
        state = item.get("state") or "attached"
        if not isinstance(state, str) or state not in ATTACHMENT_STATES:
            continue
        timestamps: dict[str, str | None] = {}
        for field in ("created_at", "expires_at"):
            value = item.get(field)
            if value is None:
                timestamps[field] = None
                continue
            if not isinstance(value, str) or len(value) > 64:
                timestamps = {}
                break
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                timestamps = {}
                break
            if parsed.tzinfo is None:
                timestamps = {}
                break
            timestamps[field] = value
        if len(timestamps) != 2:
            continue
        normalized.append({
            "id": attachment_id,
            "name": name,
            "mime_type": mime_type,
            "kind": kind,
            "byte_size": byte_size,
            "state": state,
            "created_at": timestamps["created_at"],
            "expires_at": timestamps["expires_at"],
            "content_url": f"/api/agent-console/attachments/{attachment_id}/content",
        })
        seen.add(attachment_id)
    return normalized


def normalize_artifacts(raw_artifacts: Any) -> list[dict]:
    """Normalize retained generated files, including the display-only code kind."""
    normalized: list[dict] = []
    if not isinstance(raw_artifacts, list):
        return normalized
    for item in raw_artifacts[:ATTACHMENT_LIMIT]:
        if not isinstance(item, dict):
            continue
        storage_kind = "text" if item.get("kind") == "code" else item.get("kind")
        safe = normalize_attachments([{**item, "kind": storage_kind}])
        if not safe:
            continue
        artifact = safe[0]
        if item.get("kind") == "code":
            artifact["kind"] = "code"
        normalized.append(artifact)
    return normalized


def normalize_transport_binding(
    mode: Any,
    binding_id: Any,
    *,
    legacy_default: bool,
) -> tuple[str, str] | None:
    if mode is None and binding_id is None and legacy_default:
        return "local", "local-default"
    if mode not in ("local", "remote") or not isinstance(binding_id, str):
        return None
    if not re.fullmatch(r"(?:local-default|[0-9a-f]{32})", binding_id):
        return None
    if mode == "remote" and binding_id == "local-default":
        return None
    return mode, binding_id


def normalize_usage(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if type(value) is not dict:
        return None
    normalized: dict[str, int] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        item = value.get(name)
        if type(item) is not int or not (0 <= item <= 10**9):
            return None
        normalized[name] = item
    context_tokens = value.get("context_tokens")
    context_length = value.get("context_length")
    if context_tokens is not None or context_length is not None:
        if (
            type(context_tokens) is not int
            or type(context_length) is not int
            or not (0 < context_tokens <= context_length <= 10**9)
        ):
            context_tokens = None
            context_length = None
        else:
            normalized["context_tokens"] = context_tokens
            normalized["context_length"] = context_length
    return normalized


def summarize_run(run: dict) -> dict:
    prompt, prompt_truncated = bounded_excerpt(run.get("prompt"), PROMPT_EXCERPT_LIMIT)
    response, response_truncated = bounded_excerpt(run.get("response"), RESPONSE_EXCERPT_LIMIT)
    error, error_truncated = bounded_excerpt(run.get("error"), ERROR_EXCERPT_LIMIT)
    events = normalize_events(str(run.get("id") or ""), run.get("events"))
    transport = normalize_transport_binding(
        run.get("transport_mode"),
        run.get("connection_binding_id"),
        legacy_default=True,
    )
    if transport is None:
        raise ValueError("Invalid Agent Console transport binding")
    if run.get("runtime_type", "hermes") != "hermes":
        raise ValueError("Invalid Agent Console runtime type")
    summary = {
        "id": str(run.get("id") or ""),
        "runtime_type": "hermes",
        "agent_id": str(run.get("agent_id") or "hermes"),
        "agent_name": str(run.get("agent_name") or "Hermes"),
        "model": str(run.get("model") or ""),
        "status": str(run.get("status") or "failed"),
        "session_id": run.get("session_id") or None,
        "starts_new_session": bool(run.get("starts_new_session")),
        "new_session_state": (
            run.get("new_session_state")
            if run.get("new_session_state") in {"pending", "started", "failed"}
            else None
        ),
        "transport_mode": transport[0],
        "connection_binding_id": transport[1],
        "usage": normalize_usage(run.get("usage")),
        "partial": bool(run.get("partial")),
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
        "attachments": normalize_attachments(run.get("attachments")),
        "artifacts": normalize_artifacts(run.get("artifacts")),
    }
    for name in ("mentat_agent_id", "task_id"):
        value = run.get(name)
        if _valid_binding_identifier(name, value):
            summary[name] = value
    return summary


def _hydrate(summary: dict) -> dict | None:
    run_id = summary.get("id")
    if not isinstance(run_id, str) or not run_id:
        return None
    transport = normalize_transport_binding(
        summary.get("transport_mode"),
        summary.get("connection_binding_id"),
        legacy_default=True,
    )
    if transport is None:
        return None
    if summary.get("runtime_type", "hermes") != "hermes":
        return None
    events = normalize_events(run_id, summary.get("events"))
    run = {
        "id": run_id,
        "runtime_type": "hermes",
        "agent_id": str(summary.get("agent_id") or "hermes"),
        "agent_name": str(summary.get("agent_name") or "Hermes"),
        "model": str(summary.get("model") or ""),
        "status": str(summary.get("status") or "failed"),
        "session_id": summary.get("session_id") or None,
        "starts_new_session": bool(summary.get("starts_new_session")),
        "new_session_state": (
            summary.get("new_session_state")
            if summary.get("new_session_state") in {"pending", "started", "failed"}
            else None
        ),
        "transport_mode": transport[0],
        "connection_binding_id": transport[1],
        "usage": normalize_usage(summary.get("usage")),
        "partial": bool(summary.get("partial")),
        "prompt": str(summary.get("prompt_excerpt") or ""),
        "prompt_truncated": bool(summary.get("prompt_truncated")),
        "response": str(summary.get("response_excerpt") or ""),
        "response_truncated": bool(summary.get("response_truncated")),
        "error": str(summary.get("error_excerpt") or ""),
        "error_truncated": bool(summary.get("error_truncated")),
        "events": events,
        "event_cursor": events[-1]["cursor"] if events else 0,
        "attachments": normalize_attachments(summary.get("attachments")),
        "artifacts": normalize_artifacts(summary.get("artifacts")),
        "created_at": summary.get("created_at"),
        "updated_at": summary.get("updated_at"),
        "started_at": summary.get("started_at"),
        "completed_at": summary.get("completed_at"),
        "duration_seconds": summary.get("duration_seconds"),
        "persisted_summary": True,
    }
    binding: dict[str, str] = {}
    for name in ("mentat_agent_id", "task_id"):
        value = summary.get(name)
        if _valid_binding_identifier(name, value):
            binding[name] = value
    if len(binding) != 2:
        for event in reversed(events):
            if event.get("type") != "runtime.bound":
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            candidate = {
                name: data.get(name) for name in ("mentat_agent_id", "task_id")
            }
            if all(
                _valid_binding_identifier(name, value)
                for name, value in candidate.items()
            ):
                binding = candidate
                break
    if len(binding) == 2:
        run.update(binding)
    return run
