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
from urllib.parse import urlsplit

from .version import DISPLAY_VERSION


BRIDGE_TOKEN_ENV = "MENTAT_BRIDGE_TOKEN"
BRIDGE_TOKEN_HEADER = "X-Mentat-Bridge-Token"
BRIDGE_HEALTH_PATH = "/bridge/v1/health"
BRIDGE_AGENTS_PATH = "/bridge/v1/agents"
BRIDGE_TASKS_PATH = "/bridge/v1/tasks"
MINIMUM_TOKEN_LENGTH = 43
MAXIMUM_TOKEN_LENGTH = 256
SUPPORTED_BRIDGE_HOSTS = frozenset({"127.0.0.1", "::1"})
MAXIMUM_BRIDGE_AGENTS = 128
MAXIMUM_BRIDGE_TASKS = 2048
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_RUNTIME_TYPE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_CAPABILITY = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")


class BridgeConfigurationError(ValueError):
    """Raised when the private bridge cannot start safely."""


class BridgeAgentProjectionError(ValueError):
    """Raised when canonical Agent data cannot cross this fixed capability."""


class BridgeTaskProjectionError(ValueError):
    """Raised when canonical Task data cannot cross this fixed capability."""


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

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if not self._request_is_private():
            self._send_json({"error": "bridge_request_forbidden"}, 403)
            return
        if self.path == BRIDGE_HEALTH_PATH:
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
        if self.path == BRIDGE_AGENTS_PATH:
            payload, status = bridge_agents_payload()
            self._send_json(payload, status)
            return
        if self.path == BRIDGE_TASKS_PATH:
            payload, status = bridge_tasks_payload()
            self._send_json(payload, status)
            return
        else:
            self._send_json({"error": "bridge_route_not_found"}, 404)

    do_DELETE = _reject_method
    do_HEAD = _reject_method
    do_OPTIONS = _reject_method
    do_PATCH = _reject_method
    do_POST = _reject_method
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
