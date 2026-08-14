"""Browser-safe health projection and signed probe construction for Hermes.

The refresh coordinator owns process-local operational evidence.  This module
turns that evidence into a small allowlisted public schema and builds the one
fixed synthetic delivery used by Mentat's operator probe.  It performs no I/O.
The public projector never returns a secret, signature, delivery identifier,
or raw timestamp; the private probe builder returns signed request material
only to the server-side loopback caller.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from typing import Any, Mapping

from hermes_webhooks import ALLOWED_EVENTS


SCHEMA_VERSION = 1
MAX_PUBLIC_COUNTER = 1_000_000
MAX_PUBLIC_AGE_SECONDS = 31 * 24 * 60 * 60
RECENT_EVENT_SECONDS = 5 * 60
MAX_RECONCILIATION_AGE_SECONDS = 3 * 60
TARGET_PATH = "/api/integrations/hermes/webhooks/v1/local-default"
PROBE_EVENT = "on_session_start"

_COUNTER_KEYS = {
    "accepted": "accepted_hint_count",
    "coalesced": "coalesced_hint_count",
    "dropped": "queue_drop_count",
    "refresh_successes": "refresh_success_count",
    "refresh_failures": "refresh_failure_count",
    "degraded_projections": "degraded_projection_count",
    "reconciliations": "reconciliation_count",
}
_AGE_KEYS = {
    "last_event": "last_event_at",
    "last_refresh": "last_refresh_at",
    "last_reconciliation": "last_reconciled_at",
}
_REQUIRED_SNAPSHOT_KEYS = frozenset(
    {
        *_COUNTER_KEYS.values(),
        *_AGE_KEYS.values(),
        "backoff_skip_count",
        "coordinator_started_at",
        "last_event_name",
        "last_error_code",
        "unresolved_drop_count",
    }
)
_STATE_LABELS = {
    "off": "Off",
    "ready": "Ready",
    "receiving": "Receiving",
    "degraded": "Degraded",
}
_STATE_SUMMARIES = {
    "off": "The signed receiver is off until a private shared secret is configured.",
    "ready": "The signed receiver is ready and waiting for a recent verified event.",
    "receiving": "The signed receiver has accepted verified Hermes events.",
    "degraded": "The receiver is configured, but refresh health needs attention.",
}


def _counter(value: Any) -> tuple[int, int, bool]:
    if type(value) is not int or value < 0:
        return 0, 0, True
    return min(value, MAX_PUBLIC_COUNTER), value, False


def _age(value: Any, now: datetime) -> tuple[int | None, bool]:
    if value is None:
        return None, False
    if not isinstance(value, str) or len(value) > 64:
        return None, True
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None, True
        normalized = parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None, True
    if normalized > now + timedelta(seconds=5):
        return None, True
    age = max(0, int((now - normalized).total_seconds()))
    return min(age, MAX_PUBLIC_AGE_SECONDS), False


def public_health_payload(
    *,
    configured: bool,
    coordinator_available: bool,
    snapshot: Mapping[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the exact payload-safe receiver health schema."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not configured:
        state = "off"
        counters = {key: 0 for key in _COUNTER_KEYS}
        ages = {key: None for key in _AGE_KEYS}
        probe_available = False
    else:
        malformed = (
            snapshot is None
            or not isinstance(snapshot, Mapping)
            or not _REQUIRED_SNAPSHOT_KEYS.issubset(snapshot)
        )
        source: Mapping[str, Any] = snapshot if isinstance(snapshot, Mapping) else {}
        counters = {}
        raw_counters = {}
        for public_key, internal_key in _COUNTER_KEYS.items():
            counters[public_key], raw_counters[public_key], invalid = _counter(
                source.get(internal_key, 0)
            )
            malformed = malformed or invalid
        ages = {}
        for public_key, internal_key in _AGE_KEYS.items():
            ages[public_key], invalid = _age(source.get(internal_key), current)
            malformed = malformed or invalid
        _backoff_skips, _raw_backoff_skips, invalid = _counter(
            source.get("backoff_skip_count", 0)
        )
        malformed = malformed or invalid
        _public_unresolved_drops, unresolved_drops, invalid = _counter(
            source.get("unresolved_drop_count", 0)
        )
        malformed = malformed or invalid or unresolved_drops > raw_counters["dropped"]
        coordinator_age, invalid = _age(source.get("coordinator_started_at"), current)
        malformed = malformed or invalid or (coordinator_available and coordinator_age is None)
        accepted = raw_counters["accepted"]
        event_name = source.get("last_event_name")
        if accepted > 0:
            malformed = malformed or ages["last_event"] is None or event_name not in ALLOWED_EVENTS
        else:
            malformed = malformed or ages["last_event"] is not None or event_name is not None
        if raw_counters["coalesced"] > accepted:
            malformed = True
        reconciliations = raw_counters["reconciliations"]
        malformed = malformed or ((reconciliations > 0) != (ages["last_reconciliation"] is not None))
        refresh_successes = raw_counters["refresh_successes"]
        malformed = malformed or ((refresh_successes > 0) != (ages["last_refresh"] is not None))
        last_error_code = source.get("last_error_code")
        if last_error_code not in (None, "webhook_refresh_failed"):
            malformed = True
        malformed = malformed or (
            (raw_counters["degraded_projections"] > 0)
            != (last_error_code is not None)
        )
        recent_event = (
            accepted > 0
            and ages["last_event"] is not None
            and ages["last_event"] <= RECENT_EVENT_SECONDS
        )
        stale_reconciliation = (
            ages["last_reconciliation"] is not None
            and ages["last_reconciliation"] > MAX_RECONCILIATION_AGE_SECONDS
        ) or (
            ages["last_reconciliation"] is None
            and (
                (ages["last_event"] is not None and ages["last_event"] > MAX_RECONCILIATION_AGE_SECONDS)
                or (coordinator_age is not None and coordinator_age > MAX_RECONCILIATION_AGE_SECONDS)
            )
        )
        degraded = (
            malformed
            or not coordinator_available
            or unresolved_drops > 0
            or raw_counters["degraded_projections"] > 0
            or last_error_code is not None
            or stale_reconciliation
        )
        if degraded:
            state = "degraded"
        elif recent_event:
            state = "receiving"
        else:
            state = "ready"
        probe_available = coordinator_available

    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "state_label": _STATE_LABELS[state],
        "summary": _STATE_SUMMARIES[state],
        "probe_available": probe_available,
        "target_path": TARGET_PATH,
        "events": sorted(ALLOWED_EVENTS),
        "ages_seconds": ages,
        "counters": counters,
    }


def build_probe_request(
    secret: bytes,
    *,
    delivery_id: str,
    now: datetime | None = None,
) -> tuple[bytes, dict[str, str]]:
    """Build one fixed signed delivery for Mentat's private loopback probe."""
    if not isinstance(secret, bytes) or not secret:
        raise ValueError("probe secret is unavailable")
    if not isinstance(delivery_id, str) or not delivery_id.startswith("mentat-probe-"):
        raise ValueError("probe delivery identifier is invalid")
    if len(delivery_id) > 96 or not delivery_id.isascii() or not delivery_id.replace("-", "").isalnum():
        raise ValueError("probe delivery identifier is invalid")
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    body = json.dumps(
        {
            "delivery_id": delivery_id,
            "hook_event_name": PROBE_EVENT,
            "platform": "cli",
            "timestamp": timestamp.isoformat(timespec="seconds"),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "X-Hermes-Event": PROBE_EVENT,
        "X-Hermes-Delivery": delivery_id,
        "X-Hermes-Signature-256": f"sha256={signature}",
    }
