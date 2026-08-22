"""Private loopback bridge used by the source-checkout Node preview.

The bridge exposes small fixed read-only capabilities. It is not a generic
proxy for ``server.py`` and it owns no durable state.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
import re
import signal
import socket
import threading
from urllib.parse import parse_qsl, unquote, urlsplit

from .version import DISPLAY_VERSION


BRIDGE_TOKEN_ENV = "MENTAT_BRIDGE_TOKEN"
BRIDGE_TOKEN_HEADER = "X-Mentat-Bridge-Token"
BRIDGE_HEALTH_PATH = "/bridge/v1/health"
BRIDGE_AGENTS_PATH = "/bridge/v1/agents"
BRIDGE_TASKS_PATH = "/bridge/v1/tasks"
BRIDGE_RUNS_PATH = "/bridge/v1/runs"
MINIMUM_TOKEN_LENGTH = 43
MAXIMUM_TOKEN_LENGTH = 256
SUPPORTED_BRIDGE_HOSTS = frozenset({"127.0.0.1", "::1"})
MAXIMUM_BRIDGE_AGENTS = 128
MAXIMUM_BRIDGE_TASKS = 2048
MAXIMUM_BRIDGE_RUNS = 50
MAXIMUM_BRIDGE_RUN_EVENTS = 100
MAXIMUM_BRIDGE_ACTION_BODY_BYTES = 512
MAXIMUM_BRIDGE_MESSAGE_BODY_BYTES = 24_576
MAXIMUM_BRIDGE_RESPONSE_BODY_BYTES = 24_576
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_RUNTIME_TYPE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_CAPABILITY = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_RUN_ID = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z")
_RUN_SOURCE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


class BridgeConfigurationError(ValueError):
    """Raised when the private bridge cannot start safely."""


class BridgeAgentProjectionError(ValueError):
    """Raised when canonical Agent data cannot cross this fixed capability."""


class BridgeTaskProjectionError(ValueError):
    """Raised when canonical Task data cannot cross this fixed capability."""


class BridgeRunProjectionError(ValueError):
    """Raised when canonical Run data cannot cross this fixed capability."""


class BridgeRunEventProjectionError(ValueError):
    """Raised when canonical Run events cannot cross this fixed capability."""


class IPv6BridgeHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], token: str):
        self.bridge_token = token
        super().__init__(address, BridgeRequestHandler)


class IPv6ConfiguredBridgeHTTPServer(IPv6BridgeHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], token: str):
        self.bridge_token = token
        super().__init__(address, BridgeRequestHandler)


def validate_bridge_host(host: str) -> str:
    normalized = str(host or "").strip().lower().strip("[]")
    if normalized not in SUPPORTED_BRIDGE_HOSTS:
        raise BridgeConfigurationError("bridge_host_must_be_loopback")
    return normalized


def validate_bridge_port(value: object, *, allow_zero: bool = True) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BridgeConfigurationError("bridge_port_invalid") from exc
    minimum = 0 if allow_zero else 1
    if not minimum <= port <= 65535:
        raise BridgeConfigurationError("bridge_port_invalid")
    return port


def validate_bridge_token(value: object) -> str:
    token = str(value or "")
    try:
        token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BridgeConfigurationError("bridge_token_invalid") from exc
    if (
        not MINIMUM_TOKEN_LENGTH <= len(token) <= MAXIMUM_TOKEN_LENGTH
        or token.strip() != token
        or any(character.isspace() for character in token)
    ):
        raise BridgeConfigurationError("bridge_token_invalid")
    return token


def bridge_server_class(host: str) -> type[BridgeHTTPServer] | type[IPv6ConfiguredBridgeHTTPServer]:
    return IPv6ConfiguredBridgeHTTPServer if validate_bridge_host(host) == "::1" else BridgeHTTPServer


def build_bridge_server(host: str, port: int, token: str):
    safe_host = validate_bridge_host(host)
    safe_port = validate_bridge_port(port)
    safe_token = validate_bridge_token(token)
    return bridge_server_class(safe_host)((safe_host, safe_port), safe_token)


def _normalized_ip(value: object) -> str | None:
    try:
        return str(ipaddress.ip_address(str(value or "").strip().strip("[]")))
    except ValueError:
        return None


def host_header_matches_binding(value: object, bound_host: str, bound_port: int) -> bool:
    raw = str(value or "").strip()
    if not raw or any(character.isspace() for character in raw):
        return False
    try:
        parsed = urlsplit(f"//{raw}")
        parsed_port = parsed.port
    except ValueError:
        return False
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed_port is None
    ):
        return False
    return (
        _normalized_ip(parsed.hostname) == _normalized_ip(bound_host)
        and parsed_port == int(bound_port)
    )


def client_is_loopback(value: object) -> bool:
    try:
        return ipaddress.ip_address(str(value or "").strip()).is_loopback
    except ValueError:
        return False


def _public_agent_record(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "name",
        "runtime_type",
        "runtime_config_id",
        "capabilities",
    }:
        raise BridgeAgentProjectionError("agent_projection_invalid")
    agent_id = value.get("id")
    name = value.get("name")
    runtime_type = value.get("runtime_type")
    runtime_config_id = value.get("runtime_config_id")
    capabilities = value.get("capabilities")
    if (
        not isinstance(agent_id, str)
        or not _OPAQUE_ID.fullmatch(agent_id)
        or not isinstance(name, str)
        or not name.strip()
        or name.strip() != name
        or "\x00" in name
        or len(name) > 120
        or not isinstance(runtime_type, str)
        or not _RUNTIME_TYPE.fullmatch(runtime_type)
        or not isinstance(runtime_config_id, str)
        or not _OPAQUE_ID.fullmatch(runtime_config_id)
        or not isinstance(capabilities, list)
        or len(capabilities) > 64
        or any(not isinstance(capability, str) or not _CAPABILITY.fullmatch(capability) for capability in capabilities)
        or capabilities != sorted(set(capabilities))
    ):
        raise BridgeAgentProjectionError("agent_projection_invalid")
    return {
        "id": agent_id,
        "name": name,
        "runtime_type": runtime_type,
        "runtime_config_id": runtime_config_id,
        "capabilities": capabilities,
    }


def _ready_agents_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "agents", "count"}:
        raise BridgeAgentProjectionError("agent_projection_invalid")
    agents = value.get("agents")
    count = value.get("count")
    if (
        value.get("schema_version") != 1
        or not isinstance(agents, list)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count != len(agents)
        or count < 0
        or count > MAXIMUM_BRIDGE_AGENTS
    ):
        raise BridgeAgentProjectionError("agent_projection_invalid")
    public_agents = [_public_agent_record(agent) for agent in agents]
    if len({agent["id"] for agent in public_agents}) != len(public_agents):
        raise BridgeAgentProjectionError("agent_projection_invalid")
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": "ready",
        "agents": public_agents,
        "count": count,
    }


def bridge_agents_payload() -> tuple[dict[str, object], int]:
    """Read the canonical Agent projection through one fixed local capability."""

    # The import stays server-side and lazy so the bridge owns no application
    # state and never gives Node generic access to server.py.
    try:
        from agent_registry import AgentRegistryError, AgentRegistryUnavailableError
        from server import mentat_agents_payload

        try:
            return _ready_agents_payload(mentat_agents_payload()), 200
        except AgentRegistryUnavailableError:
            status = "unavailable"
            code = 503
        except AgentRegistryError as exc:
            status = "unsupported" if exc.code == "agent_registry.unsupported" else "unavailable"
            code = 501 if status == "unsupported" else 503
        except OSError:
            status = "unavailable"
            code = 503
    except Exception:
        # Do not disclose registry, SQLite, or adapter details through this
        # private capability. Node will also reject malformed bridge output.
        status = "error"
        code = 500
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": status,
    }, code


def _valid_iso_date(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _public_task_record(value: object) -> dict[str, object]:
    required = {"id", "title", "project", "status", "priority", "due_date", "tags", "needs_attention", "review_required", "updated_at"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise BridgeTaskProjectionError("task_projection_invalid")
    task_id, title, project = value.get("id"), value.get("title"), value.get("project")
    status, priority, due_date, tags, updated_at = value.get("status"), value.get("priority"), value.get("due_date"), value.get("tags"), value.get("updated_at")
    valid_text = lambda item, maximum: isinstance(item, str) and bool(item.strip()) and item.strip() == item and "\x00" not in item and len(item) <= maximum
    if (
        not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id)
        or not valid_text(title, 160) or not valid_text(project, 120)
        or status not in {"todo", "in progress", "waiting", "needs attention", "completed"}
        or priority not in {"high", "medium", "low"}
        or due_date is not None and not _valid_iso_date(due_date)
        or not isinstance(tags, list) or len(tags) > 64 or any(not valid_text(tag, 48) for tag in tags) or len(set(tags)) != len(tags)
        or not isinstance(value.get("needs_attention"), bool) or not isinstance(value.get("review_required"), bool)
        or not _valid_timestamp(updated_at)
    ):
        raise BridgeTaskProjectionError("task_projection_invalid")
    return {"id": task_id, "title": title, "project": project, "status": status, "priority": priority, "due_date": due_date, "tags": sorted(tags), "needs_attention": value["needs_attention"], "review_required": value["review_required"], "updated_at": updated_at}


def bridge_tasks_payload() -> tuple[dict[str, object], int]:
    """Read one bounded public Task projection through a fixed capability."""
    try:
        from task_repository import TaskRepositoryError, TaskRepositoryUnavailable
        from server import mentat_tasks_payload
        try:
            source = mentat_tasks_payload()
            tasks = source.get("tasks") if isinstance(source, dict) else None
            if not isinstance(tasks, list) or len(tasks) > MAXIMUM_BRIDGE_TASKS:
                raise BridgeTaskProjectionError("task_projection_invalid")
            public_tasks = [_public_task_record(task) for task in tasks]
            if len({task["id"] for task in public_tasks}) != len(public_tasks):
                raise BridgeTaskProjectionError("task_projection_invalid")
            return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": "ready", "tasks": public_tasks, "count": len(public_tasks)}, 200
        except TaskRepositoryUnavailable:
            state, code = "unavailable", 503
        except TaskRepositoryError as exc:
            state, code = ("unsupported", 501) if exc.code in {"task_repository.schema_unsupported", "task_repository.schema_newer"} else ("error", 500)
        except (BridgeTaskProjectionError, OSError, ValueError):
            state, code = "error", 500
    except Exception:
        state, code = "error", 500
    return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": state}, code


def _public_run_record(value: object) -> dict[str, object]:
    required = {"id", "source", "task_id", "agent_id", "runtime_type", "status", "dispatch_state", "partial", "timeline", "created_at", "updated_at", "started_at", "completed_at"}
    if not isinstance(value, dict) or not required.issubset(value):
        raise BridgeRunProjectionError("run_projection_invalid")
    run_id, source, task_id, agent_id = value.get("id"), value.get("source"), value.get("task_id"), value.get("agent_id")
    runtime_type, status, dispatch_state = value.get("runtime_type"), value.get("status"), value.get("dispatch_state")
    timeline = value.get("timeline")
    if (
        not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id)
        or not isinstance(source, str) or not _RUN_SOURCE.fullmatch(source)
        or task_id is not None and (not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id))
        or agent_id is not None and (not isinstance(agent_id, str) or not _OPAQUE_ID.fullmatch(agent_id))
        or not isinstance(runtime_type, str) or not _RUNTIME_TYPE.fullmatch(runtime_type)
        or status not in {"reserved", "queued", "submitting", "starting", "running", "cancelling", "waiting", "waiting_for_approval", "waiting_for_clarification", "unknown", "completed", "failed", "cancelled", "stopped", "interrupted"}
        or dispatch_state not in {"legacy", "reserved", "submitting", "accepted", "rejected", "unknown"}
        or not isinstance(value.get("partial"), bool) or not isinstance(timeline, dict) or not isinstance(timeline.get("truncated"), bool)
        or not _valid_timestamp(value.get("created_at")) or not _valid_timestamp(value.get("updated_at"))
        or value.get("started_at") is not None and not _valid_timestamp(value.get("started_at"))
        or value.get("completed_at") is not None and not _valid_timestamp(value.get("completed_at"))
    ):
        raise BridgeRunProjectionError("run_projection_invalid")
    return {"id": run_id, "source": source, "task_id": task_id, "agent_id": agent_id, "runtime_type": runtime_type, "status": status, "dispatch_state": dispatch_state, "partial": value["partial"], "timeline_truncated": timeline["truncated"], "created_at": value["created_at"], "updated_at": value["updated_at"], "started_at": value["started_at"], "completed_at": value["completed_at"]}


def bridge_runs_payload() -> tuple[dict[str, object], int]:
    """Read one fixed bounded public Run projection through a local capability."""
    try:
        from run_repository import RunRepositoryError, RunRepositoryUnavailable
        from server import mentat_runs_payload
        try:
            source = mentat_runs_payload()
            runs = source.get("runs") if isinstance(source, dict) else None
            if not isinstance(runs, list) or len(runs) > MAXIMUM_BRIDGE_RUNS:
                raise BridgeRunProjectionError("run_projection_invalid")
            public_runs = [_public_run_record(run) for run in runs]
            if len({run["id"] for run in public_runs}) != len(public_runs):
                raise BridgeRunProjectionError("run_projection_invalid")
            return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": "ready", "runs": public_runs, "count": len(public_runs)}, 200
        except RunRepositoryUnavailable:
            state, code = "unavailable", 503
        except RunRepositoryError as exc:
            state, code = ("unsupported", 501) if exc.code == "run_repository.schema_unsupported" else ("error", 500)
        except (BridgeRunProjectionError, OSError, ValueError):
            state, code = "error", 500
    except Exception:
        state, code = "error", 500
    return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": state}, code


def _public_run_event_record(value: object, *, expected_run_id: str) -> dict[str, object]:
    required = {"id", "run_id", "sequence", "type", "occurred_at", "summary", "metrics"}
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeRunEventProjectionError("event_projection_invalid")
    event_id, run_id, sequence = value.get("id"), value.get("run_id"), value.get("sequence")
    event_type, occurred_at, summary, metrics = value.get("type"), value.get("occurred_at"), value.get("summary"), value.get("metrics")
    allowed_metrics = {"input_tokens", "output_tokens", "total_tokens", "context_tokens", "context_length"}
    if (
        not isinstance(event_id, str) or not _OPAQUE_ID.fullmatch(event_id)
        or run_id != expected_run_id
        or type(sequence) is not int or not 1 <= sequence <= 10**9
        or event_type not in {"run.created", "dispatch.reserved", "run.started", "submission.unknown", "run.interrupted", "tool.requested", "tool.completed", "approval.required", "artifact.created", "cost", "run.stopped", "run.completed", "run.failed", "message"}
        or not _valid_timestamp(occurred_at)
        or not isinstance(summary, str) or not summary or summary.strip() != summary or len(summary) > 500 or "\0" in summary
        or not isinstance(metrics, dict) or set(metrics) - allowed_metrics
        or any(type(metric) is not int or not 0 <= metric <= 10**9 for metric in metrics.values())
    ):
        raise BridgeRunEventProjectionError("event_projection_invalid")
    return {"id": event_id, "run_id": run_id, "sequence": sequence, "type": event_type, "occurred_at": occurred_at, "summary": summary, "metrics": dict(metrics)}


def bridge_run_events_payload(run_id: str, after_sequence: int) -> tuple[dict[str, object], int]:
    """Read one fixed bounded safe event projection through the local bridge."""
    try:
        from run_repository import RunRepositoryConflict, RunRepositoryError, RunRepositoryUnavailable
        from server import mentat_run_events_payload
        try:
            source = mentat_run_events_payload(run_id, after_sequence)
            events = source.get("events") if isinstance(source, dict) else None
            cursor = source.get("next_cursor") if isinstance(source, dict) else None
            reset = source.get("cursor_reset_required") if isinstance(source, dict) else None
            if (
                not isinstance(source, dict)
                or source.get("schema_version") != 1 or source.get("run_id") != run_id
                or source.get("after") != after_sequence or not isinstance(events, list)
                or len(events) > MAXIMUM_BRIDGE_RUN_EVENTS
                or type(cursor) is not int or not 0 <= cursor <= 10**9
                or type(reset) is not bool
            ):
                raise BridgeRunEventProjectionError("event_projection_invalid")
            public_events = [_public_run_event_record(event, expected_run_id=run_id) for event in events]
            sequences = [event["sequence"] for event in public_events]
            if len(set(sequences)) != len(sequences) or sequences != sorted(sequences):
                raise BridgeRunEventProjectionError("event_projection_invalid")
            if sequences and sequences[-1] != cursor:
                raise BridgeRunEventProjectionError("event_projection_invalid")
            if not reset and (cursor != after_sequence + len(sequences) or any(current != previous + 1 for previous, current in zip(sequences, sequences[1:]))):
                raise BridgeRunEventProjectionError("event_projection_invalid")
            return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": "ready", "run_id": run_id, "after": after_sequence, "next_cursor": cursor, "cursor_reset_required": reset, "events": public_events}, 200
        except RunRepositoryConflict:
            return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": "not_found"}, 404
        except RunRepositoryUnavailable:
            state, code = "unavailable", 503
        except RunRepositoryError as exc:
            state, code = ("unsupported", 501) if exc.code == "run_repository.schema_unsupported" else ("error", 500)
        except (BridgeRunEventProjectionError, OSError, ValueError):
            state, code = "error", 500
    except Exception:
        state, code = "error", 500
    return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": state}, code


def _run_action_failure(status: str) -> tuple[dict[str, object], int]:
    codes = {
        "not_found": 404,
        "unavailable": 503,
        "unsupported": 501,
        "conflict": 409,
        "invalid": 400,
        "partial": 500,
        "error": 500,
    }
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": status,
    }, codes[status]


def bridge_run_stop_preview_payload(run_id: str) -> tuple[dict[str, object], int]:
    try:
        from server import OrchestrationRunActionError, mentat_run_stop_preview_payload

        try:
            source = mentat_run_stop_preview_payload(run_id)
            if (
                not isinstance(source, dict)
                or set(source) != {"schema_version", "action", "run_id", "requires_confirmation", "confirmation_id"}
                or source.get("schema_version") != 1
                or source.get("action") != "stop"
                or source.get("run_id") != run_id
                or source.get("requires_confirmation") is not True
                or not isinstance(source.get("confirmation_id"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", source["confirmation_id"])
            ):
                raise BridgeRunProjectionError("run_action_projection_invalid")
            return {
                "schema_version": 1,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
                "action": "stop",
                "run_id": run_id,
                "requires_confirmation": True,
                "confirmation_id": source["confirmation_id"],
            }, 200
        except OrchestrationRunActionError as exc:
            if exc.code == "run.not_found":
                return _run_action_failure("not_found")
            if exc.code == "run.unavailable":
                return _run_action_failure("unavailable")
            if exc.code in {"run.stop_unavailable", "run.binding_changed"}:
                return _run_action_failure("unsupported")
            return _run_action_failure("error")
    except Exception:
        return _run_action_failure("error")


def bridge_confirm_run_stop(run_id: str, confirmation_id: object) -> tuple[dict[str, object], int]:
    try:
        from server import OrchestrationRunActionError, mentat_confirm_run_stop

        try:
            source = mentat_confirm_run_stop(run_id, confirmation_id)
            if (
                not isinstance(source, dict)
                or set(source) != {"schema_version", "action", "run_id", "disposition"}
                or source.get("schema_version") != 1
                or source.get("action") != "stop"
                or source.get("run_id") != run_id
                or source.get("disposition") != "requested"
            ):
                raise BridgeRunProjectionError("run_action_projection_invalid")
            return {
                "schema_version": 1,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
                "action": "stop",
                "run_id": run_id,
                "disposition": "requested",
            }, 202
        except OrchestrationRunActionError as exc:
            if exc.code == "run.not_found":
                return _run_action_failure("not_found")
            if exc.code == "run.unavailable":
                return _run_action_failure("unavailable")
            if exc.code in {"run.stop_unavailable", "run.binding_changed"}:
                return _run_action_failure("unsupported")
            if exc.code in {"run.confirmation_invalid", "run.confirmation_stale"}:
                return _run_action_failure("conflict")
            if exc.code in {"run.stop_failed", "run.stop_partial"}:
                return _run_action_failure("error")
            return _run_action_failure("error")
    except Exception:
        return _run_action_failure("error")


def bridge_run_message_preview_payload(
    run_id: str, text: object
) -> tuple[dict[str, object], int]:
    try:
        from server import OrchestrationRunActionError, mentat_run_message_preview_payload

        source = mentat_run_message_preview_payload(run_id, text)
        if (
            not isinstance(source, dict)
            or set(source) != {"schema_version", "action", "run_id", "requires_confirmation", "confirmation_id"}
            or source.get("schema_version") != 1
            or source.get("action") != "message"
            or source.get("run_id") != run_id
            or source.get("requires_confirmation") is not True
            or not isinstance(source.get("confirmation_id"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", source["confirmation_id"])
        ):
            raise BridgeRunProjectionError("run_action_projection_invalid")
        return {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "message", "run_id": run_id,
            "requires_confirmation": True, "confirmation_id": source["confirmation_id"],
        }, 200
    except OrchestrationRunActionError as exc:
        if exc.code == "run.not_found": return _run_action_failure("not_found")
        if exc.code == "run.unavailable": return _run_action_failure("unavailable")
        if exc.code in {"run.stop_unavailable", "run.message_unavailable", "run.binding_changed"}: return _run_action_failure("unsupported")
        if exc.code == "run.message_invalid": return _run_action_failure("invalid")
        return _run_action_failure("error")
    except Exception:
        return _run_action_failure("error")


def bridge_confirm_run_message(
    run_id: str, text: object, confirmation_id: object
) -> tuple[dict[str, object], int]:
    try:
        from server import OrchestrationRunActionError, mentat_confirm_run_message

        source = mentat_confirm_run_message(run_id, text, confirmation_id)
        if (
            not isinstance(source, dict)
            or set(source) != {"schema_version", "action", "run_id", "disposition"}
            or source.get("schema_version") != 1 or source.get("action") != "message"
            or source.get("run_id") != run_id or source.get("disposition") != "accepted"
        ):
            raise BridgeRunProjectionError("run_action_projection_invalid")
        return {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "message", "run_id": run_id, "disposition": "accepted",
        }, 202
    except OrchestrationRunActionError as exc:
        if exc.code == "run.not_found": return _run_action_failure("not_found")
        if exc.code == "run.unavailable": return _run_action_failure("unavailable")
        if exc.code in {"run.stop_unavailable", "run.message_unavailable", "run.binding_changed"}: return _run_action_failure("unsupported")
        if exc.code in {"run.confirmation_invalid", "run.confirmation_stale"}: return _run_action_failure("conflict")
        if exc.code == "run.message_invalid": return _run_action_failure("invalid")
        return _run_action_failure("error")
    except Exception:
        return _run_action_failure("error")


def _safe_pending_run_request(value: object) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        return False
    if value["kind"] == "approval":
        expected = {"kind", "title", "summary", "choices"}
        choices = value.get("choices")
        return (
            set(value) == expected
            and isinstance(value.get("title"), str)
            and isinstance(value.get("summary"), str)
            and len(value["title"]) <= 240
            and len(value["summary"]) <= 2_000
            and isinstance(choices, list)
            and 0 < len(choices) <= 16
            and all(
                isinstance(choice, dict)
                and set(choice) == {"id", "label"}
                and isinstance(choice.get("id"), str)
                and _OPAQUE_ID.fullmatch(choice["id"])
                and choice["id"] in {"once", "deny"}
                and isinstance(choice.get("label"), str)
                and 0 < len(choice["label"]) <= 240
                for choice in choices
            )
            and len({choice["id"] for choice in choices}) == len(choices)
        )
    if value["kind"] == "clarification":
        expected = {"kind", "prompt_type", "question", "choices"}
        choices = value.get("choices")
        if (
            set(value) != expected
            or value.get("prompt_type") not in {"choice", "text"}
            or not isinstance(value.get("question"), str)
            or not 0 < len(value["question"]) <= 2_000
            or not isinstance(choices, list)
            or len(choices) > 16
        ):
            return False
        if value["prompt_type"] == "choice" and not choices:
            return False
        if value["prompt_type"] == "text" and choices:
            return False
        return all(
            isinstance(choice, dict)
            and set(choice) == {"id", "label"}
            and isinstance(choice.get("id"), str)
            and _OPAQUE_ID.fullmatch(choice["id"])
            and isinstance(choice.get("label"), str)
            and 0 < len(choice["label"]) <= 240
            for choice in choices
        ) and len({choice["id"] for choice in choices}) == len(choices)
    return False


def _bridge_run_response_error(code: str) -> tuple[dict[str, object], int]:
    if code == "run.not_found":
        return _run_action_failure("not_found")
    if code == "run.unavailable":
        return _run_action_failure("unavailable")
    if code in {"run.stop_unavailable", "run.response_unavailable", "run.binding_changed"}:
        return _run_action_failure("unsupported")
    if code in {"run.confirmation_invalid", "run.confirmation_stale"}:
        return _run_action_failure("conflict")
    if code == "run.response_invalid":
        return _run_action_failure("invalid")
    if code == "run.response_partial":
        return _run_action_failure("partial")
    return _run_action_failure("error")


def bridge_run_response_request_payload(run_id: str) -> tuple[dict[str, object], int]:
    try:
        from server import OrchestrationRunActionError, mentat_run_response_request_payload

        source = mentat_run_response_request_payload(run_id)
        if (
            not isinstance(source, dict)
            or set(source) != {"schema_version", "action", "run_id", "request", "requires_confirmation"}
            or source.get("schema_version") != 1
            or source.get("action") != "respond"
            or source.get("run_id") != run_id
            or source.get("requires_confirmation") is not False
            or not _safe_pending_run_request(source.get("request"))
        ):
            raise BridgeRunProjectionError("run_action_projection_invalid")
        return {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "respond", "run_id": run_id,
            "request": source["request"], "requires_confirmation": False,
        }, 200
    except OrchestrationRunActionError as exc:
        return _bridge_run_response_error(exc.code)
    except Exception:
        return _run_action_failure("error")


def bridge_run_response_preview_payload(
    run_id: str, response: object
) -> tuple[dict[str, object], int]:
    try:
        from server import OrchestrationRunActionError, mentat_run_response_preview_payload

        source = mentat_run_response_preview_payload(run_id, response)
        if (
            not isinstance(source, dict)
            or set(source) != {"schema_version", "action", "run_id", "request", "requires_confirmation", "confirmation_id"}
            or source.get("schema_version") != 1
            or source.get("action") != "respond"
            or source.get("run_id") != run_id
            or source.get("requires_confirmation") is not True
            or not isinstance(source.get("confirmation_id"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", source["confirmation_id"])
            or not _safe_pending_run_request(source.get("request"))
        ):
            raise BridgeRunProjectionError("run_action_projection_invalid")
        return {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "respond", "run_id": run_id,
            "request": source["request"], "requires_confirmation": True,
            "confirmation_id": source["confirmation_id"],
        }, 200
    except OrchestrationRunActionError as exc:
        return _bridge_run_response_error(exc.code)
    except Exception:
        return _run_action_failure("error")


def bridge_confirm_run_response(
    run_id: str, response: object, confirmation_id: object
) -> tuple[dict[str, object], int]:
    try:
        from server import OrchestrationRunActionError, mentat_confirm_run_response

        source = mentat_confirm_run_response(run_id, response, confirmation_id)
        if (
            not isinstance(source, dict)
            or set(source) != {"schema_version", "action", "run_id", "disposition"}
            or source.get("schema_version") != 1 or source.get("action") != "respond"
            or source.get("run_id") != run_id or source.get("disposition") != "accepted"
        ):
            raise BridgeRunProjectionError("run_action_projection_invalid")
        return {
            "schema_version": 1, "service": "mentat-local-bridge", "runtime": "python",
            "status": "ready", "action": "respond", "run_id": run_id, "disposition": "accepted",
        }, 202
    except OrchestrationRunActionError as exc:
        return _bridge_run_response_error(exc.code)
    except Exception:
        return _run_action_failure("error")


class BridgeRequestHandler(BaseHTTPRequestHandler):
    server_version = "MentatLocalBridge"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        # Request metadata is intentionally not logged by this private surface.
        return

    def _send_json(self, payload: dict[str, object], status: int) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _request_is_private(self, *, reject_body_headers: bool = True) -> bool:
        if not client_is_loopback(self.client_address[0]):
            return False
        bound_host, bound_port = self.server.server_address[:2]
        host_headers = self.headers.get_all("Host", failobj=[]) or []
        if len(host_headers) != 1 or not host_header_matches_binding(
            host_headers[0], bound_host, int(bound_port)
        ):
            return False
        if self.headers.get_all("Origin", failobj=[]) or self.headers.get_all(
            "Cookie", failobj=[]
        ):
            return False
        # Browser requests carry Sec-Fetch-Site. Node's standards-based
        # server-side fetch may add Sec-Fetch-Mode, so rejecting every
        # Sec-Fetch header would also reject the intended BFF caller.
        if self.headers.get_all("Sec-Fetch-Site", failobj=[]):
            return False
        if reject_body_headers and (
            self.headers.get_all("Content-Length", failobj=[])
            or self.headers.get_all("Transfer-Encoding", failobj=[])
        ):
            return False
        supplied_tokens = self.headers.get_all(BRIDGE_TOKEN_HEADER, failobj=[]) or []
        if len(supplied_tokens) != 1:
            return False
        expected = getattr(self.server, "bridge_token", "")
        return bool(expected) and hmac.compare_digest(supplied_tokens[0], expected)

    def _reject_method(self) -> None:
        if not self._request_is_private(reject_body_headers=False):
            self._send_json({"error": "bridge_request_forbidden"}, 403)
            return
        self._send_json({"error": "method_not_allowed"}, 405)

    def _action_json_body(self, maximum_bytes: int = MAXIMUM_BRIDGE_ACTION_BODY_BYTES) -> dict[str, object] | None:
        content_type = self.headers.get("Content-Type", "")
        lengths = self.headers.get_all("Content-Length", failobj=[]) or []
        if len(lengths) != 1 or content_type.lower() != "application/json":
            return None
        maximum_digits = len(str(maximum_bytes))
        if not re.fullmatch(rf"[1-9][0-9]{{0,{maximum_digits - 1}}}", lengths[0]):
            return None
        size = int(lengths[0])
        if size > maximum_bytes:
            return None
        try:
            value = json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._request_is_private():
            self._send_json({"error": "bridge_request_forbidden"}, 403)
            return
        parsed = urlsplit(self.path)
        if parsed.path == BRIDGE_HEALTH_PATH and not parsed.query:
            self._send_json(
                {
                    "mentat_version": DISPLAY_VERSION,
                    "runtime": "python",
                    "schema_version": 1,
                    "service": "mentat-local-bridge",
                    "status": "ready",
                },
                200,
            )
            return
        if parsed.path == BRIDGE_AGENTS_PATH and not parsed.query:
            payload, status = bridge_agents_payload()
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_TASKS_PATH and not parsed.query:
            payload, status = bridge_tasks_payload()
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_RUNS_PATH and not parsed.query:
            payload, status = bridge_runs_payload()
            self._send_json(payload, status)
            return
        event_match = re.fullmatch(r"/bridge/v1/runs/([^/]+)/events", parsed.path)
        if event_match is not None:
            run_id = unquote(event_match.group(1))
            if _RUN_ID.fullmatch(run_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            try:
                pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            except ValueError:
                pairs = []
            if len(pairs) != 1 or pairs[0][0] != "after" or not re.fullmatch(r"[0-9]{1,10}", pairs[0][1]):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_run_events_payload(run_id, int(pairs[0][1]))
            self._send_json(payload, status)
            return
        else:
            self._send_json({"error": "bridge_route_not_found"}, 404)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._request_is_private(reject_body_headers=False):
            self._send_json({"error": "bridge_request_forbidden"}, 403)
            return
        parsed = urlsplit(self.path)
        match = re.fullmatch(r"/bridge/v1/runs/([^/]+)/(stop|message|response)(?:/(preview))?", parsed.path)
        if match is None or parsed.query:
            self._reject_method()
            return
        run_id = unquote(match.group(1))
        if _RUN_ID.fullmatch(run_id) is None:
            self._send_json({"error": "bridge_route_not_found"}, 404)
            return
        action = match.group(2)
        maximum = MAXIMUM_BRIDGE_ACTION_BODY_BYTES
        if action == "message":
            maximum = MAXIMUM_BRIDGE_MESSAGE_BODY_BYTES
        elif action == "response":
            maximum = MAXIMUM_BRIDGE_RESPONSE_BODY_BYTES
        body = self._action_json_body(maximum)
        if body is None:
            self._send_json({"error": "bridge_route_not_found"}, 404)
            return
        if match.group(3) == "preview":
            expected = {"text"} if action == "message" else ({"response"} if action == "response" else set())
            if set(body) != expected:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            if action == "message":
                payload, status = bridge_run_message_preview_payload(run_id, body["text"])
            elif action == "response":
                payload, status = bridge_run_response_preview_payload(run_id, body["response"])
            else:
                payload, status = bridge_run_stop_preview_payload(run_id)
            self._send_json(payload, status)
            return
        if action == "response" and set(body) == set():
            payload, status = bridge_run_response_request_payload(run_id)
            self._send_json(payload, status)
            return
        expected = {"confirmation_id", "text"} if action == "message" else ({"confirmation_id", "response"} if action == "response" else {"confirmation_id"})
        if set(body) != expected:
            self._send_json({"error": "bridge_route_not_found"}, 404)
            return
        if action == "message":
            payload, status = bridge_confirm_run_message(run_id, body["text"], body["confirmation_id"])
        elif action == "response":
            payload, status = bridge_confirm_run_response(run_id, body["response"], body["confirmation_id"])
        else:
            payload, status = bridge_confirm_run_stop(run_id, body["confirmation_id"])
        self._send_json(payload, status)

    do_DELETE = _reject_method
    do_HEAD = _reject_method
    do_OPTIONS = _reject_method
    do_PATCH = _reject_method
    do_PUT = _reject_method


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Mentat's private source-preview bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="0")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.pop(BRIDGE_TOKEN_ENV, "")
    try:
        bridge = build_bridge_server(args.host, validate_bridge_port(args.port), token)
    except (BridgeConfigurationError, OSError) as exc:
        code = str(exc) if isinstance(exc, BridgeConfigurationError) else "bridge_bind_failed"
        print(f"Mentat Local Bridge refused startup: {code}", flush=True)
        return 2

    stopped = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stopped.set()

    previous_handlers: dict[int, object] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[signum] = signal.signal(signum, request_stop)
        except (OSError, ValueError):
            continue

    bridge.timeout = 0.25
    bound_host, bound_port = bridge.server_address[:2]
    display_host = f"[{bound_host}]" if ":" in str(bound_host) else str(bound_host)
    print(f"Mentat Python Local Bridge ready on http://{display_host}:{bound_port}", flush=True)
    try:
        while not stopped.is_set():
            bridge.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.server_close()
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
