"""Validation primitives for the local Hermes 0.20 webhook boundary.

This module deliberately has no HTTP or filesystem side effects.  The server
can use it to verify the exact request bytes before parsing untrusted JSON.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
from typing import Any, Mapping
import threading
import time

MAX_BODY_BYTES = 64 * 1024
MAX_DELIVERY_ID_LENGTH = 128
MAX_EVENT_AGE_SECONDS = 5 * 60
ALLOWED_EVENTS = frozenset(
    {
        "on_session_start",
        "on_session_end",
        "on_session_finalize",
        "on_session_reset",
        "subagent_start",
        "subagent_stop",
        "post_api_request",
        "api_request_error",
        "post_tool_call",
        "kanban_task_claimed",
        "kanban_task_completed",
        "kanban_task_blocked",
        "on_kanban_worker_spawned",
        "on_kanban_worker_exited",
        "on_kanban_worker_stale_claim",
        "on_kanban_task_updated",
        "on_kanban_dispatch_tick",
    }
)
_SIGNATURE_RE = re.compile(r"^sha256=[0-9a-f]{64}$")
_DELIVERY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class WebhookValidationError(ValueError):
    """A secret-free, user-actionable validation failure."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WebhookBinding:
    binding_id: str
    secret: bytes
    enabled_events: frozenset[str] = ALLOWED_EVENTS


@dataclass(frozen=True)
class VerifiedHermesEvent:
    binding_id: str
    event_name: str
    delivery_digest: str
    occurred_at: datetime
    received_at: datetime


class PerBindingRateLimiter:
    """Small process-local token bucket keyed only by safe binding ID."""

    def __init__(
        self,
        *,
        capacity: int = 120,
        refill_per_second: float = 2.0,
        clock=time.monotonic,
    ) -> None:
        if capacity <= 0 or refill_per_second <= 0:
            raise ValueError("rate limiter capacity and refill must be positive")
        self.capacity = int(capacity)
        self.refill_per_second = float(refill_per_second)
        self._clock = clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, binding_id: str) -> bool:
        now = float(self._clock())
        with self._lock:
            tokens, updated_at = self._buckets.get(
                binding_id, (float(self.capacity), now)
            )
            elapsed = max(0.0, now - updated_at)
            tokens = min(
                float(self.capacity),
                tokens + elapsed * self.refill_per_second,
            )
            if tokens < 1.0:
                self._buckets[binding_id] = (tokens, now)
                return False
            self._buckets[binding_id] = (tokens - 1.0, now)
            return True


def _header_values(headers: Mapping[str, str], name: str) -> list[str]:
    getter = getattr(headers, "get_all", None) or getattr(headers, "getall", None)
    if getter is not None:
        return [str(value).strip() for value in (getter(name) or [])]
    return [str(value).strip() for key, value in headers.items() if key.lower() == name.lower()]


def _header(headers: Mapping[str, str], name: str) -> str:
    values = _header_values(headers, name)
    return values[0] if values else ""


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise WebhookValidationError("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WebhookValidationError("invalid_timestamp") from exc
    if parsed.tzinfo is None:
        raise WebhookValidationError("invalid_timestamp")
    if parsed.utcoffset() != timedelta(0):
        raise WebhookValidationError("invalid_timestamp")
    return parsed.astimezone(timezone.utc)


def verify_and_normalize(
    raw_body: bytes,
    headers: Mapping[str, str],
    binding: WebhookBinding,
    *,
    now: datetime | None = None,
) -> VerifiedHermesEvent:
    """Verify a signed Hermes delivery and return only bounded safe fields."""
    if not binding.binding_id or not binding.secret:
        raise WebhookValidationError("binding_not_ready")
    if len(raw_body) > MAX_BODY_BYTES:
        raise WebhookValidationError("body_too_large")
    for header_name in (
        "Content-Type",
        "X-Hermes-Signature-256",
        "X-Hermes-Event",
        "X-Hermes-Delivery",
    ):
        if len(_header_values(headers, header_name)) > 1:
            raise WebhookValidationError("duplicate_header")
    if _header(headers, "Content-Type").lower() != "application/json":
        raise WebhookValidationError("unsupported_content_type")
    signature = _header(headers, "X-Hermes-Signature-256")
    expected = "sha256=" + hmac.new(binding.secret, raw_body, hashlib.sha256).hexdigest()
    if not _SIGNATURE_RE.fullmatch(signature) or not hmac.compare_digest(signature, expected):
        raise WebhookValidationError("invalid_signature")
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise WebhookValidationError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise WebhookValidationError("invalid_payload")

    event_name = payload.get("hook_event_name")
    delivery_id = payload.get("delivery_id")
    if not isinstance(event_name, str):
        raise WebhookValidationError("invalid_event")
    if event_name not in ALLOWED_EVENTS or event_name not in binding.enabled_events:
        raise WebhookValidationError("unsupported_event")
    if not isinstance(delivery_id, str) or not _DELIVERY_RE.fullmatch(delivery_id):
        raise WebhookValidationError("invalid_delivery_id")
    if _header(headers, "X-Hermes-Event") != event_name:
        raise WebhookValidationError("event_header_mismatch")
    if _header(headers, "X-Hermes-Delivery") != delivery_id:
        raise WebhookValidationError("delivery_header_mismatch")

    occurred_at = _timestamp(payload.get("timestamp"))
    received_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if abs((received_at - occurred_at).total_seconds()) > MAX_EVENT_AGE_SECONDS:
        raise WebhookValidationError("stale_timestamp")

    digest = hmac.new(binding.secret, (binding.binding_id + "\0" + delivery_id).encode(), hashlib.sha256).hexdigest()
    return VerifiedHermesEvent(
        binding_id=binding.binding_id,
        event_name=event_name,
        delivery_digest=digest,
        occurred_at=occurred_at,
        received_at=received_at,
    )
