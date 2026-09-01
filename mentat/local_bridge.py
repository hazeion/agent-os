"""Private loopback bridge used by the source-checkout Node preview.

The bridge exposes small fixed read and narrowly-scoped create capabilities. It
is not a generic proxy for ``server.py`` and it owns no durable state.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
import re
import signal
import socket
from socketserver import TCPServer
import sys
import threading
import time
from urllib.parse import parse_qsl, quote, unquote, unquote_to_bytes, urlsplit

from conversation_repository import (
    ConversationRepositoryConflict,
    ConversationRepositoryError,
)
from agent_registry import AgentRegistryError, AgentRegistryValidationError
from orchestration_service import OrchestrationServiceError
from link_preview_cache import LinkPreviewCacheError, LinkPreviewPreferenceConflict
from link_preview_service import LinkPreviewServiceError
from link_preview_webp import valid_transformed_webp
from .version import DISPLAY_VERSION


BRIDGE_TOKEN_ENV = "MENTAT_BRIDGE_TOKEN"
BRIDGE_TOKEN_HEADER = "X-Mentat-Bridge-Token"
BRIDGE_HEALTH_PATH = "/bridge/v1/health"
BRIDGE_AGENTS_PATH = "/bridge/v1/agents"
BRIDGE_PROVIDER_CONNECTIONS_PATH = "/bridge/v1/provider-connections"
BRIDGE_TASKS_PATH = "/bridge/v1/tasks"
BRIDGE_RUNS_PATH = "/bridge/v1/runs"
BRIDGE_CONVERSATIONS_PATH = "/bridge/v1/conversations"
BRIDGE_CONVERSATION_HISTORY_PATH = "/bridge/v1/conversation-history"
BRIDGE_COMMAND_MANIFEST_PATH = "/bridge/v1/agent-console/commands"
BRIDGE_PLANNING_OVERVIEW_PATH = "/bridge/v1/agent-console/planning-overview"
BRIDGE_PLANNING_TASKS_PATH = "/bridge/v1/agent-console/planning-tasks"
BRIDGE_PLANNING_TASK_PATH = "/bridge/v1/agent-console/planning-task"
BRIDGE_PROJECTS_PATH = "/bridge/v1/projects"
BRIDGE_AGENT_ACTIVITY_PATH = "/bridge/v1/agent-activity"
BRIDGE_CODEX_READINESS_PATH = "/bridge/v1/codex-readiness"
BRIDGE_LINK_PREVIEW_PREFERENCE_PATH = "/bridge/v1/link-previews/preference"
BRIDGE_LINK_PREVIEW_CACHE_CLEAR_PATH = "/bridge/v1/link-previews/cache/clear"
BRIDGE_WORKSPACE_FILES_PATH = "/bridge/v1/workspace-files"
BRIDGE_CONTEXT_PACKS_PATH = "/bridge/v1/context-packs"
BRIDGE_UPLOAD_FILENAME_HEADER = "X-Mentat-Filename"
MINIMUM_TOKEN_LENGTH = 43
MAXIMUM_TOKEN_LENGTH = 256
SUPPORTED_BRIDGE_HOSTS = frozenset({"127.0.0.1", "::1"})
MAXIMUM_BRIDGE_AGENTS = 128
MAXIMUM_BRIDGE_PROVIDER_CONNECTIONS = 1
MAXIMUM_BRIDGE_TASKS = 2048
MAXIMUM_BRIDGE_RUNS = 50
MAXIMUM_BRIDGE_RUN_EVENTS = 100
MAXIMUM_BRIDGE_CONVERSATIONS = 50
MAXIMUM_BRIDGE_CONVERSATION_MESSAGES = 100
MAXIMUM_BRIDGE_QUEUED_TURNS = 8
MAXIMUM_BRIDGE_CONVERSATION_RESPONSE_BYTES = 3_000_000
MAXIMUM_BRIDGE_ACTION_BODY_BYTES = 512
MAXIMUM_BRIDGE_PLANNING_MUTATION_BODY_BYTES = 64 * 1024
MAXIMUM_BRIDGE_RENAME_BODY_BYTES = 2_048
MAXIMUM_BRIDGE_MESSAGE_BODY_BYTES = 24_576
MAXIMUM_BRIDGE_CONVERSATION_TURN_BODY_BYTES = 96 * 1024
MAXIMUM_BRIDGE_RESPONSE_BODY_BYTES = 24_576
MAXIMUM_BRIDGE_UPLOAD_BODY_BYTES = 10 * 1024 * 1024
MAXIMUM_BRIDGE_WORKSPACE_BODY_BYTES = 8_192
MAXIMUM_BRIDGE_AGENT_CAPABILITY_BODY_BYTES = 8_192
BRIDGE_BODY_READ_TIMEOUT_SECONDS = 5.0
BRIDGE_BODY_READ_CHUNK_BYTES = 8_192
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_RUNTIME_TYPE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_CAPABILITY = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_RUN_ID = re.compile(r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}\Z")
_RUN_SOURCE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_CONVERSATION_ID = re.compile(r"conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
_MESSAGE_ID = re.compile(r"msg_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
_TURN_ID = re.compile(r"turn_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}\Z")
_LINK_PREVIEW_IMAGE_ID = re.compile(r"[0-9a-f]{32}\Z")
_ATTACHMENT_ID = re.compile(r"attachment_[0-9a-f]{32}\Z")
_CONTEXT_PACK_ID = re.compile(r"pack_[0-9a-f]{16}\Z")
_CONTEXT_PACK_REVISION = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SAFE_UPLOAD_CONTENT_TYPES = frozenset({
    "application/json",
    "application/javascript",
    "application/octet-stream",
    "application/sql",
    "application/toml",
    "application/x-ndjson",
    "application/x-javascript",
    "application/xml",
    "application/yaml",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/css",
    "text/csv",
    "text/html",
    "text/javascript",
    "text/markdown",
    "text/plain",
    "text/tab-separated-values",
    "text/typescript",
    "text/x-c",
    "text/x-c++",
    "text/x-csharp",
    "text/x-diff",
    "text/x-go",
    "text/x-java-source",
    "text/x-kotlin",
    "text/x-php",
    "text/x-python",
    "text/x-ruby",
    "text/x-rust",
    "text/x-swift",
})
_SAFE_IMAGE_CONTENT_TYPES = frozenset({
    "image/gif", "image/jpeg", "image/png", "image/webp",
})
_CONVERSATION_FILE_SEQUENCE = threading.Condition()
_CONVERSATION_FILE_NEXT: dict[str, int] = {}
_CONVERSATION_FILE_SERVING: dict[str, int] = {}


@contextmanager
def _conversation_file_sequence(conversation_id: str):
    """Serialize accepted file operations in bridge-arrival order."""

    with _CONVERSATION_FILE_SEQUENCE:
        ticket = _CONVERSATION_FILE_NEXT.get(conversation_id, 0)
        _CONVERSATION_FILE_NEXT[conversation_id] = ticket + 1
        _CONVERSATION_FILE_SERVING.setdefault(conversation_id, 0)
        while _CONVERSATION_FILE_SERVING[conversation_id] != ticket:
            _CONVERSATION_FILE_SEQUENCE.wait()
    try:
        yield
    finally:
        with _CONVERSATION_FILE_SEQUENCE:
            _CONVERSATION_FILE_SERVING[conversation_id] = ticket + 1
            if _CONVERSATION_FILE_SERVING[conversation_id] == _CONVERSATION_FILE_NEXT[conversation_id]:
                _CONVERSATION_FILE_SERVING.pop(conversation_id, None)
                _CONVERSATION_FILE_NEXT.pop(conversation_id, None)
            _CONVERSATION_FILE_SEQUENCE.notify_all()


class BridgeConfigurationError(ValueError):
    """Raised when the private bridge cannot start safely."""


class BridgeAgentProjectionError(ValueError):
    """Raised when canonical Agent data cannot cross this fixed capability."""


class BridgeAgentConfigurationProjectionError(ValueError):
    """Raised when Agent configuration cannot cross the private bridge."""


class BridgeProviderConnectionProjectionError(ValueError):
    """Raised when safe provider status cannot cross this fixed capability."""


class BridgeTaskProjectionError(ValueError):
    """Raised when canonical Task data cannot cross this fixed capability."""


class BridgeRunProjectionError(ValueError):
    """Raised when canonical Run data cannot cross this fixed capability."""


class BridgeRunEventProjectionError(ValueError):
    """Raised when canonical Run events cannot cross this fixed capability."""


class BridgeConversationProjectionError(ValueError):
    """Raised when canonical Conversation data cannot cross this capability."""


class BridgeLinkPreviewProjectionError(ValueError):
    """Raised when link-preview data cannot cross the private bridge."""


class BridgeConversationFileProjectionError(ValueError):
    """Raised when Conversation file data cannot cross the private bridge."""


class _LoopbackBridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        """Bind the validated literal loopback address without reverse DNS."""

        TCPServer.server_bind(self)
        bound_host, bound_port = self.server_address[:2]
        self.server_name = str(bound_host)
        self.server_port = int(bound_port)


class IPv6BridgeHTTPServer(_LoopbackBridgeHTTPServer):
    address_family = socket.AF_INET6


class BridgeHTTPServer(_LoopbackBridgeHTTPServer):
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


def configured_launcher_pid() -> int | None:
    raw = str(os.environ.get("MENTAT_LAUNCHER_PID", "") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 and value != os.getpid() else None


def launcher_is_running(pid: int | None) -> bool:
    if pid is None:
        return True
    if os.name == "nt":
        from private_state import _pid_is_running

        return _pid_is_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


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


def _ready_agent_attachment_payload(
    value: object,
    expected_agent_id: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "agent"}:
        raise BridgeAgentProjectionError("agent_projection_invalid")
    agent = value.get("agent")
    if not isinstance(agent, dict) or set(agent) != {
        "id", "name", "runtime_type", "system_role", "capabilities",
    }:
        raise BridgeAgentProjectionError("agent_projection_invalid")
    agent_id = agent.get("id")
    name = agent.get("name")
    runtime_type = agent.get("runtime_type")
    system_role = agent.get("system_role")
    capabilities = agent.get("capabilities")
    if (
        value.get("schema_version") != 1
        or agent_id != expected_agent_id
        or not isinstance(agent_id, str)
        or _OPAQUE_ID.fullmatch(agent_id) is None
        or not isinstance(name, str)
        or not name
        or name.strip() != name
        or len(name) > 120
        or re.search(
            r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]",
            name,
        )
        or runtime_type != "hermes"
        or system_role not in {None, "direct"}
        or not isinstance(capabilities, list)
        or len(capabilities) > 64
        or capabilities != sorted(set(capabilities))
        or "run.attachments" not in capabilities
        or any(
            not isinstance(capability, str)
            or _CAPABILITY.fullmatch(capability) is None
            for capability in capabilities
        )
    ):
        raise BridgeAgentProjectionError("agent_projection_invalid")
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": "ready",
        "agent": {
            "id": agent_id,
            "name": name,
            "runtime_type": "hermes",
            "system_role": system_role,
            "capabilities": list(capabilities),
        },
    }


def bridge_enable_agent_attachments(
    agent_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    try:
        from server import enable_mentat_agent_attachments

        source, status = enable_mentat_agent_attachments(agent_id, payload)
        if status != 200:
            return _conversation_file_failure(status)
        return _ready_agent_attachment_payload(source, agent_id), 200
    except Exception:
        return _conversation_file_failure(500)


def bridge_agent_attachment_enable_status(
    agent_id: str,
) -> tuple[dict[str, object], int]:
    try:
        from server import mentat_agent_attachment_enable_status

        source, status = mentat_agent_attachment_enable_status(agent_id)
        if status != 200:
            return _conversation_file_failure(status)
        if (
            not isinstance(source, dict)
            or set(source) != {"schema_version", "agent_id", "state"}
            or source.get("schema_version") != 1
            or source.get("agent_id") != agent_id
            or source.get("state") not in {
                "active_run", "available", "enabled", "unsupported",
            }
        ):
            raise BridgeAgentProjectionError("agent_projection_invalid")
        return {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "agent_id": agent_id,
            "state": source["state"],
        }, 200
    except Exception:
        return _conversation_file_failure(500)


def _configuration_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and value.strip() == value
        and bool(value)
        and len(value) <= maximum
        and "\x00" not in value
    )


def _public_agent_configuration(value: object) -> dict[str, object]:
    required = {
        "schema_version", "agent_id", "runtime_type", "state", "mutable",
        "active_run", "current", "providers", "efforts", "explanation",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeAgentConfigurationProjectionError("configuration_invalid")
    current = value.get("current")
    providers = value.get("providers")
    efforts = value.get("efforts")
    if (
        value.get("schema_version") != 1
        or not isinstance(value.get("agent_id"), str)
        or not _OPAQUE_ID.fullmatch(value["agent_id"])
        or not isinstance(value.get("runtime_type"), str)
        or not _RUNTIME_TYPE.fullmatch(value["runtime_type"])
        or value.get("state") not in {"ready", "read_only", "unavailable"}
        or not isinstance(value.get("mutable"), bool)
        or not isinstance(value.get("active_run"), bool)
        or value.get("mutable") is not (value.get("state") == "ready")
        or not isinstance(current, dict)
        or set(current) != {"provider", "model", "effort"}
        or current.get("provider") is not None
        and not _configuration_text(current.get("provider"), 120)
        or current.get("model") is not None
        and not _configuration_text(current.get("model"), 160)
        or current.get("effort") != "runtime_default"
        or not isinstance(providers, list)
        or len(providers) > 32
        or not isinstance(efforts, list)
        or efforts != [{"id": "runtime_default", "name": "Runtime default"}]
        or not isinstance(value.get("explanation"), str)
        or len(value["explanation"]) > 300
        or "\x00" in value["explanation"]
    ):
        raise BridgeAgentConfigurationProjectionError("configuration_invalid")
    public_providers = []
    for provider in providers:
        if not isinstance(provider, dict) or set(provider) != {
            "id", "name", "current", "models"
        }:
            raise BridgeAgentConfigurationProjectionError("configuration_invalid")
        models = provider.get("models")
        if (
            not _configuration_text(provider.get("id"), 120)
            or not _configuration_text(provider.get("name"), 160)
            or not isinstance(provider.get("current"), bool)
            or not isinstance(models, list)
            or len(models) > 256
            or any(not _configuration_text(model, 160) for model in models)
            or models != list(dict.fromkeys(models))
        ):
            raise BridgeAgentConfigurationProjectionError("configuration_invalid")
        public_providers.append(dict(provider))
    if len({row["id"] for row in public_providers}) != len(public_providers):
        raise BridgeAgentConfigurationProjectionError("configuration_invalid")
    return {
        **{key: value[key] for key in required - {"providers", "current", "efforts"}},
        "current": dict(current),
        "providers": public_providers,
        "efforts": [dict(efforts[0])],
    }


def bridge_agent_configuration_payload(agent_id: str) -> tuple[dict[str, object], int]:
    try:
        from server import mentat_agent_configuration_payload

        configuration = _public_agent_configuration(
            mentat_agent_configuration_payload(agent_id)
        )
        return {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "configuration": configuration,
        }, 200
    except AgentRegistryValidationError:
        return _conversation_failure("invalid")
    except AgentRegistryError as exc:
        return _conversation_failure(
            "not_found" if exc.code == "agent.not_found" else "unavailable"
        )
    except (BridgeAgentConfigurationProjectionError, OSError, ValueError):
        return _conversation_failure("error")


def _public_configuration_preview(value: object, agent_id: str) -> dict[str, object]:
    required = {
        "schema_version", "action", "agent_id", "requires_confirmation",
        "confirmation_id", "current", "target", "message",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeAgentConfigurationProjectionError("configuration_invalid")
    current = value.get("current")
    target = value.get("target")
    if (
        value.get("schema_version") != 1
        or value.get("action") != "configure"
        or value.get("agent_id") != agent_id
        or value.get("requires_confirmation") is not True
        or not _configuration_text(value.get("confirmation_id"), 80)
        or not isinstance(current, dict)
        or set(current) != {"provider", "model"}
        or not isinstance(target, dict)
        or set(target) != {"provider", "provider_name", "model", "effort"}
        or target.get("effort") != "runtime_default"
        or any(
            not _configuration_text(item, limit)
            for item, limit in (
                (target.get("provider"), 120),
                (target.get("provider_name"), 160),
                (target.get("model"), 160),
                (value.get("message"), 300),
            )
        )
        or any(
            item is not None and not _configuration_text(item, limit)
            for item, limit in (
                (current.get("provider"), 120),
                (current.get("model"), 160),
            )
        )
    ):
        raise BridgeAgentConfigurationProjectionError("configuration_invalid")
    return dict(value)


def bridge_agent_configuration_mutation(
    agent_id: str,
    payload: object,
    *,
    preview: bool,
) -> tuple[dict[str, object], int]:
    try:
        from server import (
            confirm_mentat_agent_configuration,
            preview_mentat_agent_configuration,
        )

        operation = (
            preview_mentat_agent_configuration
            if preview
            else confirm_mentat_agent_configuration
        )
        source, status = operation(agent_id, payload)
        if status != 200:
            fixed = {
                400: "invalid",
                404: "not_found",
                409: "conflict",
                422: "invalid",
                500: "partial",
                502: "partial",
                503: "unavailable",
            }.get(status, "error")
            return _conversation_failure(fixed)
        if preview:
            result = _public_configuration_preview(source, agent_id)
        else:
            if not isinstance(source, dict) or set(source) != {
                "schema_version", "action", "agent_id", "configuration", "message"
            } or source.get("schema_version") != 1 or source.get("action") != "configure" or source.get("agent_id") != agent_id or not _configuration_text(source.get("message"), 300):
                raise BridgeAgentConfigurationProjectionError("configuration_invalid")
            result = {
                "schema_version": 1,
                "action": "configure",
                "agent_id": agent_id,
                "configuration": _public_agent_configuration(source["configuration"]),
                "message": source["message"],
            }
        return {
            **result,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
        }, 200
    except AgentRegistryValidationError:
        return _conversation_failure("invalid")
    except AgentRegistryError as exc:
        return _conversation_failure(
            "not_found" if exc.code == "agent.not_found" else "unavailable"
        )
    except (BridgeAgentConfigurationProjectionError, OSError, ValueError):
        return _conversation_failure("error")


def _conversation_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and value.strip() == value
        and bool(value)
        and len(value) <= maximum
        and "\x00" not in value
    )


def _conversation_timestamp(value: object) -> bool:
    return isinstance(value, str) and len(value) <= 40 and _valid_timestamp(value)


def _public_conversation_agent(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "id", "name", "runtime_type", "system_role", "capabilities"
    }:
        raise BridgeConversationProjectionError("conversation_agent_invalid")
    if (
        not isinstance(value.get("id"), str)
        or not _OPAQUE_ID.fullmatch(value["id"])
        or not _conversation_text(value.get("name"), 120)
        or not isinstance(value.get("runtime_type"), str)
        or not _RUNTIME_TYPE.fullmatch(value["runtime_type"])
        or value.get("system_role") not in {None, "direct"}
        or not isinstance(value.get("capabilities"), list)
        or len(value["capabilities"]) > 64
        or any(
            not isinstance(capability, str)
            or not _CAPABILITY.fullmatch(capability)
            for capability in value["capabilities"]
        )
        or value["capabilities"] != sorted(set(value["capabilities"]))
    ):
        raise BridgeConversationProjectionError("conversation_agent_invalid")
    return {
        "id": value["id"],
        "name": value["name"],
        "runtime_type": value["runtime_type"],
        "system_role": value["system_role"],
        "capabilities": list(value["capabilities"]),
    }


def _public_conversation_summary(value: object) -> dict[str, object]:
    required = {
        "id", "agent_id", "title", "title_source", "state", "revision",
        "created_at", "updated_at", "archived_at",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("conversation_projection_invalid")
    if (
        not isinstance(value.get("id"), str)
        or not _CONVERSATION_ID.fullmatch(value["id"])
        or not isinstance(value.get("agent_id"), str)
        or not _OPAQUE_ID.fullmatch(value["agent_id"])
        or not _conversation_text(value.get("title"), 160)
        or value.get("title_source") not in {"default", "first_prompt", "manual"}
        or value.get("state") not in {"active", "archived"}
        or type(value.get("revision")) is not int
        or value["revision"] < 1
        or not _conversation_timestamp(value.get("created_at"))
        or not _conversation_timestamp(value.get("updated_at"))
        or (
            value.get("archived_at") is not None
            and not _conversation_timestamp(value.get("archived_at"))
        )
        or value.get("state") == "active" and value.get("archived_at") is not None
        or value.get("state") == "archived" and value.get("archived_at") is None
    ):
        raise BridgeConversationProjectionError("conversation_projection_invalid")
    return dict(value)


def _public_conversation_content(value: object, role: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "parts"}:
        raise BridgeConversationProjectionError("conversation_message_invalid")
    parts = value.get("parts")
    if (
        value.get("schema_version") != 1
        or not isinstance(parts, list)
        or len(parts) != 1
        or not isinstance(parts[0], dict)
        or set(parts[0]) != {"type", "text"}
        or parts[0].get("type") != "text"
        or not _conversation_text(
            parts[0].get("text"), 6_000 if role == "user" else 20_000
        )
    ):
        raise BridgeConversationProjectionError("conversation_message_invalid")
    return {
        "schema_version": 1,
        "parts": [{"type": "text", "text": parts[0]["text"]}],
    }


def _public_conversation_message(value: object) -> dict[str, object]:
    required = {
        "id", "conversation_id", "sequence", "role", "state", "content",
        "run_id", "revision", "created_at", "updated_at",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("conversation_message_invalid")
    run_id = value.get("run_id")
    if (
        not isinstance(value.get("id"), str)
        or not _MESSAGE_ID.fullmatch(value["id"])
        or not isinstance(value.get("conversation_id"), str)
        or not _CONVERSATION_ID.fullmatch(value["conversation_id"])
        or type(value.get("sequence")) is not int
        or not 1 <= value["sequence"] <= 10**9
        or value.get("role") not in {"user", "assistant"}
        or value.get("state") not in {"accepted", "cancelled"}
        or run_id is not None
        and (
            not isinstance(run_id, str)
            or not _RUN_ID.fullmatch(run_id)
        )
        or type(value.get("revision")) is not int
        or value["revision"] < 1
        or not _conversation_timestamp(value.get("created_at"))
        or not _conversation_timestamp(value.get("updated_at"))
    ):
        raise BridgeConversationProjectionError("conversation_message_invalid")
    return {
        "id": value["id"],
        "conversation_id": value["conversation_id"],
        "sequence": value["sequence"],
        "role": value["role"],
        "state": value["state"],
        "content": _public_conversation_content(value["content"], value["role"]),
        "run_id": run_id,
        "revision": value["revision"],
        "created_at": value["created_at"],
        "updated_at": value["updated_at"],
    }


def _public_current_run(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) not in (
        {"id", "status", "partial", "updated_at"},
        {"id", "status", "partial", "updated_at", "configuration"},
    ):
        raise BridgeConversationProjectionError("conversation_run_invalid")
    if (
        not isinstance(value.get("id"), str)
        or not _RUN_ID.fullmatch(value["id"])
        or value.get("status") not in {
            "reserved", "queued", "submitting", "starting", "running",
            "cancelling", "waiting", "waiting_for_approval",
            "waiting_for_clarification", "unknown", "finalizing", "completed", "failed",
            "cancelled", "stopped", "interrupted",
        }
        or not isinstance(value.get("partial"), bool)
        or not _conversation_timestamp(value.get("updated_at"))
    ):
        raise BridgeConversationProjectionError("conversation_run_invalid")
    configuration = value.get("configuration")
    if configuration is not None and (
        not isinstance(configuration, dict)
        or set(configuration) != {"provider", "model", "effort"}
        or not _configuration_text(configuration.get("provider"), 160)
        or not _configuration_text(configuration.get("model"), 160)
        or not _configuration_text(configuration.get("effort"), 64)
    ):
        raise BridgeConversationProjectionError("conversation_run_invalid")
    return dict(value)


def _public_queued_conversation_turn(value: object) -> dict[str, object]:
    required = {
        "id", "conversation_id", "user_message_id", "queue_ordinal", "state",
        "blocked_reason", "revision", "message_revision", "text",
        "created_at", "updated_at",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("conversation_turn_invalid")
    blocked_reason = value.get("blocked_reason")
    if (
        not isinstance(value.get("id"), str)
        or _TURN_ID.fullmatch(value["id"]) is None
        or not isinstance(value.get("conversation_id"), str)
        or _CONVERSATION_ID.fullmatch(value["conversation_id"]) is None
        or not isinstance(value.get("user_message_id"), str)
        or _MESSAGE_ID.fullmatch(value["user_message_id"]) is None
        or type(value.get("queue_ordinal")) is not int
        or value["queue_ordinal"] < 1
        or value.get("state") not in {"pending", "blocked"}
        or (value.get("state") == "blocked") != (blocked_reason is not None)
        or blocked_reason is not None
        and blocked_reason
        not in {"capacity", "failed", "stopped", "interrupted", "unknown", "partial"}
        or type(value.get("revision")) is not int
        or value["revision"] < 1
        or type(value.get("message_revision")) is not int
        or value["message_revision"] < 1
        or not _conversation_text(value.get("text"), 6_000)
        or not _conversation_timestamp(value.get("created_at"))
        or not _conversation_timestamp(value.get("updated_at"))
    ):
        raise BridgeConversationProjectionError("conversation_turn_invalid")
    return dict(value)


def _ready_conversation_list(value: object) -> dict[str, object]:
    required = {
        "schema_version", "conversations", "agents", "direct_agent_id",
        "count", "next_cursor",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("conversation_projection_invalid")
    conversations = value.get("conversations")
    agents = value.get("agents")
    direct_agent_id = value.get("direct_agent_id")
    if (
        value.get("schema_version") != 1
        or not isinstance(conversations, list)
        or len(conversations) > MAXIMUM_BRIDGE_CONVERSATIONS
        or not isinstance(agents, list)
        or len(agents) > MAXIMUM_BRIDGE_AGENTS
        or type(value.get("count")) is not int
        or value["count"] != len(conversations)
        or value["next_cursor"] is not None
        and (
            not isinstance(value["next_cursor"], str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value["next_cursor"]) is None
        )
        or direct_agent_id is not None
        and (
            not isinstance(direct_agent_id, str)
            or not _OPAQUE_ID.fullmatch(direct_agent_id)
        )
    ):
        raise BridgeConversationProjectionError("conversation_projection_invalid")
    public_agents = [_public_conversation_agent(agent) for agent in agents]
    public_conversations = [
        _public_conversation_summary(conversation) for conversation in conversations
    ]
    if (
        len({agent["id"] for agent in public_agents}) != len(public_agents)
        or len({conversation["id"] for conversation in public_conversations})
        != len(public_conversations)
        or direct_agent_id is not None
        and not any(
            agent["id"] == direct_agent_id and agent["system_role"] == "direct"
            for agent in public_agents
        )
        or any(
            conversation["agent_id"] not in {agent["id"] for agent in public_agents}
            for conversation in public_conversations
        )
    ):
        raise BridgeConversationProjectionError("conversation_projection_invalid")
    return {
        "schema_version": 1,
        "conversations": public_conversations,
        "agents": public_agents,
        "direct_agent_id": direct_agent_id,
        "count": len(public_conversations),
        "next_cursor": value["next_cursor"],
    }


def _ready_conversation_history(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "conversations", "count", "next_cursor",
    }:
        raise BridgeConversationProjectionError("conversation_history_invalid")
    conversations = value.get("conversations")
    next_cursor = value.get("next_cursor")
    if (
        value.get("schema_version") != 1
        or not isinstance(conversations, list)
        or len(conversations) > MAXIMUM_BRIDGE_CONVERSATIONS
        or type(value.get("count")) is not int
        or value["count"] != len(conversations)
        or next_cursor is not None
        and (
            not isinstance(next_cursor, str)
            or re.fullmatch(r"[A-Za-z0-9_-]{1,512}", next_cursor) is None
        )
    ):
        raise BridgeConversationProjectionError("conversation_history_invalid")
    public = [_public_conversation_summary(item) for item in conversations]
    if len({item["id"] for item in public}) != len(public):
        raise BridgeConversationProjectionError("conversation_history_invalid")
    return {
        "schema_version": 1,
        "conversations": public,
        "count": len(public),
        "next_cursor": next_cursor,
    }


def _conversation_history_matches_request(
    conversations: list[dict[str, object]],
    *,
    state: str,
    query: str | None,
) -> bool:
    normalized_query = "" if query is None else query.casefold()
    for conversation in conversations:
        if state != "all" and conversation["state"] != state:
            return False
        if normalized_query not in str(conversation["title"]).casefold():
            return False
    for left, right in zip(conversations, conversations[1:]):
        left_rank = 0 if left["state"] == "active" else 1
        right_rank = 0 if right["state"] == "active" else 1
        if left_rank > right_rank or (
            left_rank == right_rank
            and (str(left["updated_at"]), str(left["id"]))
            < (str(right["updated_at"]), str(right["id"]))
        ):
            return False
    return True


def _ready_conversation_detail(value: object) -> dict[str, object]:
    required = {
        "schema_version", "conversation", "agent", "messages",
        "next_message_cursor", "current_run", "queued_turns",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("conversation_projection_invalid")
    messages = value.get("messages")
    queued_turns = value.get("queued_turns")
    if (
        value.get("schema_version") != 1
        or not isinstance(messages, list)
        or len(messages) > MAXIMUM_BRIDGE_CONVERSATION_MESSAGES
        or not isinstance(queued_turns, list)
        or len(queued_turns) > MAXIMUM_BRIDGE_QUEUED_TURNS
        or value.get("next_message_cursor") is not None
        and not re.fullmatch(r"[1-9][0-9]{0,9}", str(value["next_message_cursor"]))
    ):
        raise BridgeConversationProjectionError("conversation_projection_invalid")
    conversation = _public_conversation_summary(value.get("conversation"))
    agent = _public_conversation_agent(value.get("agent"))
    public_messages = [_public_conversation_message(message) for message in messages]
    public_queued_turns = [
        _public_queued_conversation_turn(turn) for turn in queued_turns
    ]
    if (
        conversation["agent_id"] != agent["id"]
        or any(
            message["conversation_id"] != conversation["id"]
            for message in public_messages
        )
        or [message["sequence"] for message in public_messages]
        != sorted(message["sequence"] for message in public_messages)
        or any(
            turn["conversation_id"] != conversation["id"]
            for turn in public_queued_turns
        )
        or [turn["queue_ordinal"] for turn in public_queued_turns]
        != sorted(turn["queue_ordinal"] for turn in public_queued_turns)
        or len({turn["id"] for turn in public_queued_turns})
        != len(public_queued_turns)
        or len({turn["user_message_id"] for turn in public_queued_turns})
        != len(public_queued_turns)
    ):
        raise BridgeConversationProjectionError("conversation_projection_invalid")
    return {
        "schema_version": 1,
        "conversation": conversation,
        "agent": agent,
        "messages": public_messages,
        "next_message_cursor": value["next_message_cursor"],
        "current_run": _public_current_run(value.get("current_run")),
        "queued_turns": public_queued_turns,
    }


def _conversation_failure(status: str) -> tuple[dict[str, object], int]:
    codes = {
        "active_run": 409,
        "capacity_unavailable": 409,
        "cli_missing": 409,
        "conflict": 409,
        "idempotency_conflict": 409,
        "invalid": 400,
        "not_found": 404,
        "sign_in_required": 409,
        "partial": 500,
        "unavailable": 503,
        "unsupported": 501,
        "error": 500,
    }
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": status,
    }, codes[status]


def _bounded_conversation_response(
    payload: dict[str, object], status: int
) -> tuple[dict[str, object], int]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if len(body) > MAXIMUM_BRIDGE_CONVERSATION_RESPONSE_BYTES:
        return _conversation_failure("error")
    return payload, status


def bridge_conversations_payload(cursor: str | None = None) -> tuple[dict[str, object], int]:
    """Read durable Conversation summaries and safe Agent choices."""

    try:
        from server import mentat_conversations_payload

        try:
            source = _ready_conversation_list(mentat_conversations_payload(cursor))
            return _bounded_conversation_response(
                {
                    **source,
                    "service": "mentat-local-bridge",
                    "runtime": "python",
                    "status": "ready",
                },
                200,
            )
        except ConversationRepositoryError as exc:
            if exc.code == "conversation.cursor_invalid":
                return _conversation_failure("error")
            if exc.code == "conversation.schema_unsupported":
                return _conversation_failure("unsupported")
            return _conversation_failure("unavailable")
        except (BridgeConversationProjectionError, OSError, ValueError):
            return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def bridge_conversation_history_payload(
    *,
    state: str,
    query: str | None = None,
    cursor: str | None = None,
) -> tuple[dict[str, object], int]:
    """Read one query-bound title-only history page."""

    try:
        from server import mentat_conversation_history_payload

        source = _ready_conversation_history(
            mentat_conversation_history_payload(
                state=state,
                query=query,
                cursor=cursor,
            )
        )
        if not _conversation_history_matches_request(
            source["conversations"],
            state=state,
            query=query,
        ):
            raise BridgeConversationProjectionError("conversation_history_invalid")
        return _bounded_conversation_response(
            {
                **source,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
            },
            200,
        )
    except ConversationRepositoryError as exc:
        if exc.code.endswith("invalid"):
            return _conversation_failure("invalid")
        if exc.code == "conversation.schema_unsupported":
            return _conversation_failure("unsupported")
        return _conversation_failure("unavailable")
    except (BridgeConversationProjectionError, OSError, ValueError):
        return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def bridge_command_manifest_payload() -> tuple[dict[str, object], int]:
    """Return only the exact project-owned version-one command manifest."""

    try:
        from command_manifest import command_manifest_payload as expected_manifest
        from server import command_manifest_payload as server_manifest

        expected = expected_manifest()
        source = server_manifest()
        if source != expected:
            raise BridgeConversationProjectionError("command_manifest_invalid")
        return {
            **source,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
        }, 200
    except Exception:
        return _conversation_failure("error")


def _planning_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value.strip() == value
        and len(value) <= maximum
        and re.search(r"[\x00-\x1f\x7f]", value) is None
    )


def _planning_project(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"id", "name", "status", "revision"}:
        raise BridgeConversationProjectionError("planning_project_invalid")
    if (
        not isinstance(value.get("id"), str)
        or _PROJECT_ID.fullmatch(value["id"]) is None
        or not _planning_text(value.get("name"), 120)
        or value.get("status") not in {"active", "paused", "archived"}
        or type(value.get("revision")) is not int
        or value["revision"] < 1
    ):
        raise BridgeConversationProjectionError("planning_project_invalid")
    return {"id": value["id"], "name": value["name"], "status": value["status"], "revision": value["revision"]}


def _planning_task(value: object) -> dict[str, object]:
    required = {
        "attention_reasons", "due_date", "id", "needs_attention",
        "planned_for_today", "planning_state", "priority", "project_id",
        "project_name", "review_required", "status", "title", "updated_at",
        "workflow_stage", "deferred", "blocked", "revision",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("planning_task_invalid")
    reasons = value.get("attention_reasons")
    attention_order = [
        "overdue", "due_today", "review", "needs_attention",
        "planned_today", "due_soon",
    ]
    if (
        not isinstance(value.get("id"), str)
        or _TASK_ID.fullmatch(value["id"]) is None
        or not _planning_text(value.get("title"), 160)
        or not isinstance(value.get("project_id"), str)
        or _PROJECT_ID.fullmatch(value["project_id"]) is None
        or not _planning_text(value.get("project_name"), 120)
        or value.get("status") not in {"todo", "in progress", "waiting", "needs attention", "completed"}
        or value.get("priority") not in {"high", "medium", "low"}
        or value.get("due_date") is not None
        and not _valid_iso_date(value["due_date"])
        or type(value.get("planned_for_today")) is not bool
        or value.get("planning_state") is not None
        and value["planning_state"] not in {"inbox", "planned", "in_progress", "waiting", "review", "someday", "blocked", "done"}
        or value.get("workflow_stage") not in {"inbox", "planned", "in_progress", "waiting", "review", "done"}
        or type(value.get("deferred")) is not bool
        or type(value.get("blocked")) is not bool
        or type(value.get("revision")) is not int
        or value["revision"] < 1
        or type(value.get("needs_attention")) is not bool
        or type(value.get("review_required")) is not bool
        or not isinstance(reasons, list)
        or len(reasons) > 6
        or len(set(reasons)) != len(reasons)
        or any(reason not in {"overdue", "due_today", "review", "needs_attention", "planned_today", "due_soon"} for reason in reasons)
        or reasons != sorted(reasons, key=attention_order.index)
        or not _valid_timestamp(value.get("updated_at"))
    ):
        raise BridgeConversationProjectionError("planning_task_invalid")
    return {key: value[key] for key in sorted(required)}


def _planning_task_list_item(value: object) -> dict[str, object]:
    """Validate the Task-list-only, bounded description preview."""

    required = {
        "attention_reasons", "blocked", "deferred", "description_preview", "due_date",
        "id", "needs_attention", "planned_for_today", "planning_state", "priority",
        "project_id", "project_name", "review_required", "revision", "status", "title",
        "updated_at", "workflow_stage",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("planning_task_invalid")
    preview = value.get("description_preview")
    if (
        not isinstance(preview, str)
        or preview.strip() != preview
        or len(preview) > 280
        or re.search(r"[\x00-\x1f\x7f]", preview) is not None
    ):
        raise BridgeConversationProjectionError("planning_task_invalid")
    task = _planning_task({key: value[key] for key in value if key != "description_preview"})
    return {**task, "description_preview": preview}


def _planning_failure(state: str, status: int) -> tuple[dict[str, object], int]:
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": state,
    }, status


def bridge_planning_overview_payload() -> tuple[dict[str, object], int]:
    try:
        from server import mentat_planning_overview_payload

        source = mentat_planning_overview_payload()
        if not isinstance(source, dict) or set(source) != {
            "schema_version", "today", "projects", "project_count",
            "attention", "attention_count", "truncated",
        }:
            raise BridgeConversationProjectionError("planning_overview_invalid")
        projects = source.get("projects")
        attention = source.get("attention")
        if (
            source.get("schema_version") != 1
            or not _valid_iso_date(source.get("today"))
            or not isinstance(projects, list)
            or len(projects) > 256
            or type(source.get("project_count")) is not int
            or source["project_count"] != len(projects)
            or not isinstance(attention, list)
            or len(attention) > 50
            or type(source.get("attention_count")) is not int
            or source["attention_count"] < len(attention)
            or type(source.get("truncated")) is not bool
            or source["truncated"] != (source["attention_count"] > len(attention))
        ):
            raise BridgeConversationProjectionError("planning_overview_invalid")
        public_projects = [_planning_project(project) for project in projects]
        public_attention = [_planning_task(task) for task in attention]
        if len({item["id"] for item in public_projects}) != len(public_projects):
            raise BridgeConversationProjectionError("planning_overview_invalid")
        return {
            **source,
            "projects": public_projects,
            "attention": public_attention,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
        }, 200
    except Exception:
        return _planning_failure("error", 500)


def bridge_planning_tasks_payload(
    project_id: str,
    cursor: str | None = None,
) -> tuple[dict[str, object], int]:
    try:
        from server import mentat_planning_tasks_payload

        source = mentat_planning_tasks_payload(project_id=project_id, cursor=cursor)
        if not isinstance(source, dict) or set(source) != {
            "schema_version", "project", "tasks", "count", "next_cursor",
        }:
            raise BridgeConversationProjectionError("planning_tasks_invalid")
        project = _planning_project(source.get("project"))
        tasks = source.get("tasks")
        next_cursor = source.get("next_cursor")
        if (
            source.get("schema_version") != 1
            or project["id"] != project_id
            or not isinstance(tasks, list)
            or len(tasks) > 50
            or type(source.get("count")) is not int
            or source["count"] != len(tasks)
            or next_cursor is not None
            and (not isinstance(next_cursor, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,512}", next_cursor) is None)
        ):
            raise BridgeConversationProjectionError("planning_tasks_invalid")
        public_tasks = [_planning_task_list_item(task) for task in tasks]
        if any(task["project_id"] != project_id for task in public_tasks):
            raise BridgeConversationProjectionError("planning_tasks_invalid")
        return {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "project": project,
            "tasks": public_tasks,
            "count": len(public_tasks),
            "next_cursor": next_cursor,
        }, 200
    except Exception:
        return _planning_failure("error", 500)


def bridge_planning_task_payload(task_id: str) -> tuple[dict[str, object], int]:
    """Return one exact safe Task and its canonical Project."""

    from conversation_planning import ConversationPlanningError

    try:
        from server import mentat_planning_task_payload

        source = mentat_planning_task_payload(task_id)
        if not isinstance(source, dict) or set(source) != {
            "schema_version", "project", "task",
        }:
            raise BridgeConversationProjectionError("planning_task_locator_invalid")
        project = _planning_project(source.get("project"))
        task = _planning_task(source.get("task"))
        if (
            source.get("schema_version") != 1
            or task["id"] != task_id
            or task["project_id"] != project["id"]
        ):
            raise BridgeConversationProjectionError("planning_task_locator_invalid")
        return {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "project": project,
            "task": task,
        }, 200
    except ConversationPlanningError as exc:
        if exc.code == "planning.task_not_found":
            return _planning_failure("not_found", 404)
        if exc.code.endswith("_invalid"):
            return _planning_failure("invalid", 400)
        if exc.code in {"planning.unavailable", "planning.tasks_unavailable"}:
            return _planning_failure("unavailable", 503)
        return _planning_failure("error", 500)
    except Exception:
        return _planning_failure("error", 500)


def _planning_context(source: object, conversation_id: str) -> dict[str, object]:
    required = {
        "schema_version", "conversation_id", "conversation_revision",
        "association", "project", "task", "state",
    }
    if not isinstance(source, dict) or set(source) != required:
        raise BridgeConversationProjectionError("planning_context_invalid")
    association = source.get("association")
    project = source.get("project")
    task = source.get("task")
    state = source.get("state")
    if (
        source.get("schema_version") != 1
        or source.get("conversation_id") != conversation_id
        or type(source.get("conversation_revision")) is not int
        or source["conversation_revision"] < 1
        or state not in {"empty", "ready", "project_unavailable", "task_unavailable", "project_mismatch"}
    ):
        raise BridgeConversationProjectionError("planning_context_invalid")
    public_association = None
    if association is not None:
        if not isinstance(association, dict) or set(association) != {"project_id", "task_id"}:
            raise BridgeConversationProjectionError("planning_context_invalid")
        project_id = association.get("project_id")
        task_id = association.get("task_id")
        if (
            not isinstance(project_id, str)
            or _PROJECT_ID.fullmatch(project_id) is None
            or task_id is not None
            and (not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None)
        ):
            raise BridgeConversationProjectionError("planning_context_invalid")
        public_association = {"project_id": project_id, "task_id": task_id}
    public_project = None if project is None else _planning_project(project)
    public_task = None if task is None else _planning_task(task)
    if (
        state == "empty" and (public_association is not None or public_project is not None or public_task is not None)
        or state == "ready" and (public_association is None or public_project is None)
        or state == "ready" and public_association is not None
        and ((public_association["task_id"] is None) != (public_task is None))
        or state != "ready" and state != "empty" and public_association is None
        or public_project is not None and public_association is not None
        and public_project["id"] != public_association["project_id"]
        or public_task is not None and public_association is not None
        and public_task["id"] != public_association["task_id"]
        or public_task is not None and public_project is not None
        and public_task["project_id"] != public_project["id"]
        or state == "project_unavailable" and (public_project is not None or public_task is not None)
        or state in {"task_unavailable", "project_mismatch"}
        and (
            public_project is None
            or public_task is not None
            or public_association is None
            or public_association["task_id"] is None
        )
    ):
        raise BridgeConversationProjectionError("planning_context_invalid")
    return {
        "schema_version": 1,
        "conversation_id": conversation_id,
        "conversation_revision": source["conversation_revision"],
        "association": public_association,
        "project": public_project,
        "task": public_task,
        "state": state,
    }


def bridge_conversation_planning_context_payload(
    conversation_id: str,
) -> tuple[dict[str, object], int]:
    try:
        from server import mentat_conversation_planning_context_payload

        return {
            **_planning_context(
                mentat_conversation_planning_context_payload(conversation_id),
                conversation_id,
            ),
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
        }, 200
    except ConversationRepositoryConflict as exc:
        return _planning_failure("not_found" if exc.code == "conversation.not_found" else "conflict", 404 if exc.code == "conversation.not_found" else 409)
    except Exception:
        return _planning_failure("error", 500)


def bridge_set_conversation_planning_context_payload(
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    try:
        from server import set_mentat_conversation_planning_context

        source, status = set_mentat_conversation_planning_context(conversation_id, payload)
        if status != 200:
            return _planning_failure(
                "invalid" if status == 400 else "not_found" if status == 404 else "conflict" if status == 409 else "unavailable" if status == 503 else "error",
                status if status in {400, 404, 409, 503} else 500,
            )
        if not isinstance(source, dict) or set(source) != {
            "schema_version", "action", "conversation", "conversation_id",
            "conversation_revision", "association", "project", "task", "state",
        }:
            raise BridgeConversationProjectionError("planning_context_invalid")
        context = _planning_context(
            {key: source[key] for key in {
                "schema_version", "conversation_id", "conversation_revision",
                "association", "project", "task", "state",
            }},
            conversation_id,
        )
        conversation = _public_conversation_summary(source.get("conversation"))
        if (
            source.get("action") not in {"set", "clear"}
            or conversation["id"] != conversation_id
            or conversation["revision"] != context["conversation_revision"]
        ):
            raise BridgeConversationProjectionError("planning_context_invalid")
        return {
            **context,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "action": source["action"],
            "conversation": conversation,
        }, 200
    except ConversationRepositoryConflict as exc:
        states = {
            "conversation.not_found": ("not_found", 404),
            "conversation.changed": ("conflict", 409),
            "conversation.archived": ("conflict", 409),
            "conversation.active_run": ("active_run", 409),
            "conversation.queue_active": ("queue_active", 409),
            "conversation.project_unavailable": ("not_found", 404),
            "conversation.task_unavailable": ("not_found", 404),
            "conversation.project_mismatch": ("conflict", 409),
        }
        state, code = states.get(exc.code, ("conflict", 409))
        return _planning_failure(state, code)
    except ConversationRepositoryError as exc:
        return _planning_failure("invalid" if exc.code.endswith("invalid") else "unavailable", 400 if exc.code.endswith("invalid") else 503)
    except Exception:
        return _planning_failure("error", 500)


def bridge_create_project_payload(payload: object) -> tuple[dict[str, object], int]:
    try:
        from server import create_mentat_project

        source, status = create_mentat_project(payload)
        if status != 201 or not isinstance(source, dict) or set(source) != {"schema_version", "action", "project"}:
            if status in {400, 404, 409, 503}:
                return _planning_failure("conflict" if status == 409 else "invalid" if status == 400 else "not_found" if status == 404 else "unavailable", status)
            raise BridgeConversationProjectionError("planning_project_invalid")
        project = _planning_project(source.get("project"))
        return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": "ready", "action": "create", "project": project}, 201
    except Exception:
        return _planning_failure("error", 500)


def bridge_create_project_task_payload(
    project_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    try:
        from server import create_mentat_project_task

        source, status = create_mentat_project_task(project_id, payload)
        if status != 201 or not isinstance(source, dict) or set(source) != {"schema_version", "action", "project", "task"}:
            if status in {400, 404, 409, 503}:
                return _planning_failure("conflict" if status == 409 else "invalid" if status == 400 else "not_found" if status == 404 else "unavailable", status)
            raise BridgeConversationProjectionError("planning_task_invalid")
        project = _planning_project(source.get("project"))
        task = _planning_task(source.get("task"))
        if project["id"] != project_id or task["project_id"] != project_id:
            raise BridgeConversationProjectionError("planning_task_invalid")
        return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": "ready", "action": "create", "project": project, "task": task}, 201
    except Exception:
        return _planning_failure("error", 500)


def bridge_update_planning_project_payload(
    project_id: str, payload: object
) -> tuple[dict[str, object], int]:
    try:
        from server import update_mentat_planning_project

        source, status = update_mentat_planning_project(project_id, payload)
        if status != 200 or not isinstance(source, dict) or set(source) != {"schema_version", "action", "project"}:
            if status in {400, 404, 409, 503}:
                return _planning_failure("conflict" if status == 409 else "invalid" if status == 400 else "not_found" if status == 404 else "unavailable", status)
            raise BridgeConversationProjectionError("planning_project_invalid")
        project = _planning_project(source.get("project"))
        if project["id"] != project_id or source.get("action") not in {"rename", "archive", "restore"}:
            raise BridgeConversationProjectionError("planning_project_invalid")
        return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": "ready", "action": source["action"], "project": project}, 200
    except Exception:
        return _planning_failure("error", 500)


def _bridge_planning_task_mutation(
    action: str, task_id: str, source: object, status: int
) -> tuple[dict[str, object], int]:
    if status != 200 or not isinstance(source, dict) or set(source) != {"schema_version", "action", "project", "task"}:
        if status in {400, 404, 409, 503}:
            return _planning_failure("conflict" if status == 409 else "invalid" if status == 400 else "not_found" if status == 404 else "unavailable", status)
        raise BridgeConversationProjectionError("planning_task_invalid")
    project = _planning_project(source.get("project"))
    task = _planning_task(source.get("task"))
    if source.get("action") != action or task["id"] != task_id or task["project_id"] != project["id"]:
        raise BridgeConversationProjectionError("planning_task_invalid")
    return {"schema_version": 1, "service": "mentat-local-bridge", "runtime": "python", "status": "ready", "action": action, "project": project, "task": task}, 200


def bridge_update_planning_task_payload(task_id: str, payload: object) -> tuple[dict[str, object], int]:
    try:
        from server import update_mentat_planning_task
        source, status = update_mentat_planning_task(task_id, payload)
        return _bridge_planning_task_mutation("edit", task_id, source, status)
    except Exception:
        return _planning_failure("error", 500)


def bridge_move_planning_task_payload(task_id: str, payload: object) -> tuple[dict[str, object], int]:
    try:
        from server import move_mentat_planning_task
        source, status = move_mentat_planning_task(task_id, payload)
        return _bridge_planning_task_mutation("move", task_id, source, status)
    except Exception:
        return _planning_failure("error", 500)


def bridge_conversation_payload(
    conversation_id: str,
    before_sequence: int | None = None,
) -> tuple[dict[str, object], int]:
    """Read one bounded Conversation page."""

    try:
        from server import mentat_conversation_payload

        try:
            source = _ready_conversation_detail(
                mentat_conversation_payload(conversation_id, before_sequence)
            )
            if source["conversation"]["id"] != conversation_id:
                raise BridgeConversationProjectionError(
                    "conversation_target_invalid"
                )
            return _bounded_conversation_response(
                {
                    **source,
                    "service": "mentat-local-bridge",
                    "runtime": "python",
                    "status": "ready",
                },
                200,
            )
        except ConversationRepositoryError as exc:
            if exc.code == "conversation.not_found":
                return _conversation_failure("not_found")
            if exc.code == "conversation.schema_unsupported":
                return _conversation_failure("unsupported")
            if exc.code.endswith("invalid"):
                return _conversation_failure("error")
            return _conversation_failure("unavailable")
        except (BridgeConversationProjectionError, OSError, ValueError):
            return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def _conversation_file_failure(status_code: int) -> tuple[dict[str, object], int]:
    names = {
        400: "invalid",
        404: "not_found",
        409: "conflict",
        410: "gone",
        413: "too_large",
        415: "unsupported",
        500: "error",
        503: "unavailable",
    }
    status = names.get(status_code, "error")
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": status,
    }, status_code if status_code in names else 500


def _safe_file_text(value: object, maximum: int, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or re.search(
            r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]",
            value,
        )
    ):
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    return value


def _safe_attachment_item(value: object, *, staged: bool) -> dict[str, object]:
    common = {
        "id", "name", "mime_type", "kind", "byte_size", "state",
        "available", "created_at", "expires_at",
    }
    expected = common | ({"source", "ordinal"} if staged else set())
    if not isinstance(value, dict) or set(value) != expected:
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    attachment_id = value.get("id")
    name = _safe_file_text(value.get("name"), 255)
    mime_type = value.get("mime_type")
    kind = value.get("kind")
    byte_size = value.get("byte_size")
    state = value.get("state")
    available = value.get("available")
    created_at = _safe_file_text(value.get("created_at"), 64)
    expires_at = _safe_file_text(value.get("expires_at"), 64, optional=True)
    if (
        not isinstance(attachment_id, str)
        or _ATTACHMENT_ID.fullmatch(attachment_id) is None
        or name in {".", ".."}
        or "/" in str(name)
        or "\\" in str(name)
        or not isinstance(mime_type, str)
        or mime_type not in _SAFE_UPLOAD_CONTENT_TYPES - {"application/octet-stream"}
        or kind not in {"image", "text"}
        or type(byte_size) is not int
        or not 1 <= byte_size <= MAXIMUM_BRIDGE_UPLOAD_BODY_BYTES
        or state not in {
            "staged", "attached", "orphaned", "pending_delete", "missing",
        }
        or type(available) is not bool
    ):
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    if kind == "image" and mime_type not in _SAFE_IMAGE_CONTENT_TYPES:
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    if kind != "image" and mime_type in _SAFE_IMAGE_CONTENT_TYPES:
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    result: dict[str, object] = {
        "id": attachment_id,
        "name": name,
        "mime_type": mime_type,
        "kind": kind,
        "byte_size": byte_size,
        "state": state,
        "available": available,
        "created_at": created_at,
        "expires_at": expires_at,
    }
    if staged:
        source = value.get("source")
        ordinal = value.get("ordinal")
        if (
            source not in {"upload", "workspace", "context_pack"}
            or type(ordinal) is not int
            or not 0 <= ordinal <= 7
        ):
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        result.update({"source": source, "ordinal": ordinal})
    return result


def _ready_staged_context(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "conversation_id", "attachments", "context_pack", "limits",
    }:
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    conversation_id = value.get("conversation_id")
    attachments = value.get("attachments")
    limits = value.get("limits")
    context_pack = value.get("context_pack")
    if (
        value.get("schema_version") != 1
        or not isinstance(conversation_id, str)
        or _CONVERSATION_ID.fullmatch(conversation_id) is None
        or not isinstance(attachments, list)
        or len(attachments) > 8
        or limits != {"direct": 5, "total": 8, "images": 1}
    ):
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    public_attachments = [
        _safe_attachment_item(item, staged=True) for item in attachments
    ]
    if (
        len({item["id"] for item in public_attachments}) != len(public_attachments)
        or [item["ordinal"] for item in public_attachments]
        != sorted(item["ordinal"] for item in public_attachments)
        or len([item for item in public_attachments if item["source"] != "context_pack"]) > 5
        or len([item for item in public_attachments if item["kind"] == "image"]) > 1
    ):
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    safe_pack = None
    if context_pack is not None:
        if not isinstance(context_pack, dict) or set(context_pack) != {
            "id", "name", "revision",
        }:
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        pack_id = context_pack.get("id")
        revision = context_pack.get("revision")
        name = _safe_file_text(context_pack.get("name"), 80)
        if (
            not isinstance(pack_id, str)
            or _CONTEXT_PACK_ID.fullmatch(pack_id) is None
            or not isinstance(revision, str)
            or _CONTEXT_PACK_REVISION.fullmatch(revision) is None
        ):
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        safe_pack = {"id": pack_id, "name": name, "revision": revision}
    if any(
        item["source"] == "context_pack" for item in public_attachments
    ) and safe_pack is None:
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    return {
        "schema_version": 1,
        "conversation_id": conversation_id,
        "attachments": public_attachments,
        "context_pack": safe_pack,
        "limits": {"direct": 5, "total": 8, "images": 1},
    }


def _ready_workspace_files(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "query", "files",
    }:
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    query = value.get("query")
    files = value.get("files")
    if (
        value.get("schema_version") != 1
        or not isinstance(query, str)
        or len(query) > 200
        or query.strip() != query
        or re.search(
            r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]",
            query,
        )
        or not isinstance(files, list)
        or len(files) > 50
    ):
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    result = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {
            "root_id", "path", "name", "kind", "mime_type", "byte_size",
        }:
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        root_id = item.get("root_id")
        relative_path = _safe_file_text(item.get("path"), 1000)
        name = _safe_file_text(item.get("name"), 160)
        kind = item.get("kind")
        mime_type = item.get("mime_type")
        byte_size = item.get("byte_size")
        parts = str(relative_path).split("/")
        if (
            not isinstance(root_id, str)
            or _OPAQUE_ID.fullmatch(root_id) is None
            or str(relative_path).startswith("/")
            or "\\" in str(relative_path)
            or any(part in {"", ".", ".."} for part in parts)
            or "/" in str(name)
            or "\\" in str(name)
            or kind not in {"image", "text"}
            or not isinstance(mime_type, str)
            or mime_type not in _SAFE_UPLOAD_CONTENT_TYPES - {"application/octet-stream"}
            or type(byte_size) is not int
            or not 1 <= byte_size <= MAXIMUM_BRIDGE_UPLOAD_BODY_BYTES
        ):
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        result.append(dict(item))
    return {"schema_version": 1, "query": query, "files": result}


def _ready_context_pack_summaries(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "context_packs", "max_items",
    }:
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    packs = value.get("context_packs")
    if value.get("schema_version") != 1 or value.get("max_items") != 8 or not isinstance(packs, list) or len(packs) > 256:
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    result = []
    for pack in packs:
        if not isinstance(pack, dict) or set(pack) != {
            "id", "name", "description", "revision", "item_count",
        }:
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        pack_id = pack.get("id")
        name = _safe_file_text(pack.get("name"), 80)
        description = pack.get("description")
        revision = pack.get("revision")
        item_count = pack.get("item_count")
        if (
            not isinstance(pack_id, str)
            or _CONTEXT_PACK_ID.fullmatch(pack_id) is None
            or not isinstance(description, str)
            or len(description) > 500
            or re.search(
                r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]",
                description,
            )
            or not isinstance(revision, str)
            or _CONTEXT_PACK_REVISION.fullmatch(revision) is None
            or type(item_count) is not int
            or not 0 <= item_count <= 8
        ):
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        result.append({
            "id": pack_id,
            "name": name,
            "description": description,
            "revision": revision,
            "item_count": item_count,
        })
    if len({pack["id"] for pack in result}) != len(result):
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    return {"schema_version": 1, "context_packs": result, "max_items": 8}


def _ready_conversation_media(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "conversation_id", "runs",
    }:
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    conversation_id = value.get("conversation_id")
    runs = value.get("runs")
    if (
        value.get("schema_version") != 1
        or not isinstance(conversation_id, str)
        or _CONVERSATION_ID.fullmatch(conversation_id) is None
        or not isinstance(runs, list)
        or len(runs) > 50
    ):
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    public_runs = []
    attachment_count = 0
    for run in runs:
        if not isinstance(run, dict) or set(run) != {"run_id", "created_at", "inputs", "outputs"}:
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        run_id = run.get("run_id")
        created_at = run.get("created_at")
        inputs = run.get("inputs")
        outputs = run.get("outputs")
        if (
            not isinstance(run_id, str)
            or _RUN_ID.fullmatch(run_id) is None
            or not _conversation_timestamp(created_at)
            or not isinstance(inputs, list)
            or not isinstance(outputs, list)
            or len(inputs) > 8
            or len(outputs) > 20
        ):
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        safe_inputs = [_safe_attachment_item(item, staged=False) for item in inputs]
        safe_outputs = [_safe_attachment_item(item, staged=False) for item in outputs]
        combined_ids = [
            item["id"] for item in (*safe_inputs, *safe_outputs)
        ]
        if len(set(combined_ids)) != len(combined_ids):
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        attachment_count += len(safe_inputs) + len(safe_outputs)
        if attachment_count > 1_400:
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        public_runs.append({
            "run_id": run_id,
            "created_at": created_at,
            "inputs": safe_inputs,
            "outputs": safe_outputs,
        })
    if len({run["run_id"] for run in public_runs}) != len(public_runs):
        raise BridgeConversationFileProjectionError(
            "conversation_file_projection_invalid"
        )
    return {
        "schema_version": 1,
        "conversation_id": conversation_id,
        "runs": public_runs,
    }


def _bridge_ready_file_payload(
    source: object,
    source_status: int,
    expected_status: int,
    validator,
) -> tuple[dict[str, object], int]:
    if source_status != expected_status:
        return _conversation_file_failure(source_status)
    ready = validator(source)
    return {
        **ready,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": "ready",
    }, expected_status


def bridge_conversation_staged_context_payload(
    conversation_id: str,
) -> tuple[dict[str, object], int]:
    try:
        from server import mentat_conversation_staged_context_payload

        return _bridge_ready_file_payload(
            *mentat_conversation_staged_context_payload(conversation_id),
            200,
            _ready_staged_context,
        )
    except Exception:
        return _conversation_file_failure(500)


def bridge_stage_conversation_upload(
    conversation_id: str,
    *,
    original_name: str,
    content_type: str,
    content: bytes,
) -> tuple[dict[str, object], int]:
    try:
        from server import stage_mentat_conversation_upload

        return _bridge_ready_file_payload(
            *stage_mentat_conversation_upload(
                conversation_id,
                original_name=original_name,
                content_type=content_type,
                content=content,
            ),
            201,
            _ready_staged_context,
        )
    except Exception:
        return _conversation_file_failure(500)


def bridge_release_conversation_attachment(
    conversation_id: str,
    attachment_id: str,
) -> tuple[dict[str, object], int]:
    try:
        from server import release_mentat_conversation_attachment

        return _bridge_ready_file_payload(
            *release_mentat_conversation_attachment(conversation_id, attachment_id),
            200,
            _ready_staged_context,
        )
    except Exception:
        return _conversation_file_failure(500)


def bridge_workspace_files_payload(query: str) -> tuple[dict[str, object], int]:
    try:
        from server import mentat_workspace_files_payload

        return _bridge_ready_file_payload(
            *mentat_workspace_files_payload(query),
            200,
            _ready_workspace_files,
        )
    except Exception:
        return _conversation_file_failure(500)


def bridge_stage_workspace_file(
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    try:
        from server import stage_mentat_workspace_file

        return _bridge_ready_file_payload(
            *stage_mentat_workspace_file(conversation_id, payload),
            201,
            _ready_staged_context,
        )
    except Exception:
        return _conversation_file_failure(500)


def bridge_context_pack_summaries_payload() -> tuple[dict[str, object], int]:
    try:
        from server import mentat_context_pack_summaries_payload

        return _bridge_ready_file_payload(
            *mentat_context_pack_summaries_payload(),
            200,
            _ready_context_pack_summaries,
        )
    except Exception:
        return _conversation_file_failure(500)


def bridge_apply_conversation_context_pack(
    conversation_id: str,
    pack_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    try:
        from server import apply_mentat_conversation_context_pack

        return _bridge_ready_file_payload(
            *apply_mentat_conversation_context_pack(
                conversation_id,
                pack_id,
                payload,
            ),
            201,
            _ready_staged_context,
        )
    except Exception:
        return _conversation_file_failure(500)


def bridge_clear_conversation_context_pack(
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    try:
        from server import clear_mentat_conversation_context_pack

        return _bridge_ready_file_payload(
            *clear_mentat_conversation_context_pack(conversation_id, payload),
            200,
            _ready_staged_context,
        )
    except Exception:
        return _conversation_file_failure(500)


def bridge_conversation_media_payload(
    conversation_id: str,
) -> tuple[dict[str, object], int]:
    try:
        from server import mentat_conversation_media_payload

        return _bridge_ready_file_payload(
            *mentat_conversation_media_payload(conversation_id),
            200,
            _ready_conversation_media,
        )
    except Exception:
        return _conversation_file_failure(500)


def bridge_conversation_attachment_content(
    conversation_id: str,
    attachment_id: str,
) -> tuple[dict[str, object] | None, object | None, int]:
    try:
        from server import mentat_conversation_attachment_content

        metadata, stream, status = mentat_conversation_attachment_content(
            conversation_id,
            attachment_id,
        )
        if status != 200:
            if stream is not None and callable(getattr(stream, "close", None)):
                stream.close()
            return _conversation_file_failure(status)[0], None, status
        safe = _safe_attachment_item(metadata, staged=False)
        if not safe["available"]:
            raise BridgeConversationFileProjectionError(
                "conversation_file_projection_invalid"
            )
        return safe, stream, 200
    except Exception:
        if "stream" in locals() and stream is not None and callable(getattr(stream, "close", None)):
            stream.close()
        return _conversation_file_failure(500)[0], None, 500


def _link_preview_failure(status: str) -> tuple[dict[str, object], int]:
    codes = {
        "capacity_unavailable": 429,
        "conflict": 409,
        "error": 500,
        "invalid": 400,
        "not_found": 404,
        "unavailable": 503,
    }
    safe = status if status in codes else "error"
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": safe,
    }, codes[safe]


def _safe_link_preview_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > maximum
        or re.search(r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]", value)
    ):
        raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
    return value


def _ready_link_preview_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "conversation_id", "message_id", "message_revision",
        "enabled", "previews",
    }:
        raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
    previews = value.get("previews")
    if (
        value.get("schema_version") != 1
        or _CONVERSATION_ID.fullmatch(str(value.get("conversation_id") or "")) is None
        or _MESSAGE_ID.fullmatch(str(value.get("message_id") or "")) is None
        or type(value.get("message_revision")) is not int
        or value["message_revision"] < 1
        or type(value.get("enabled")) is not bool
        or not isinstance(previews, list)
        or len(previews) > 3
    ):
        raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
    result: list[dict[str, object]] = []
    ordinals: list[int] = []
    for preview in previews:
        if not isinstance(preview, dict):
            raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
        ordinal = preview.get("candidate_ordinal")
        status = preview.get("status")
        if type(ordinal) is not int or not 1 <= ordinal <= 3 or status not in {"pending", "ready", "unavailable", "blocked", "disabled"}:
            raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
        ordinals.append(ordinal)
        if status != "ready":
            if set(preview) != {"candidate_ordinal", "status"}:
                raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
            result.append({"candidate_ordinal": ordinal, "status": status})
            continue
        if set(preview) - {"candidate_ordinal", "status", "title", "description", "site_name", "display_host", "image_alt", "image_id"}:
            raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
        title = _safe_link_preview_text(preview.get("title"), 200)
        description = _safe_link_preview_text(preview.get("description"), 500)
        display_host = _safe_link_preview_text(preview.get("display_host"), 253)
        valid_display_host = display_host is not None and re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", display_host) is not None
        if display_host is not None and not valid_display_host:
            try:
                address = ipaddress.ip_address(display_host)
                valid_display_host = address.is_global and str(address) == display_host
            except ValueError:
                valid_display_host = False
        if (title is None and description is None) or not valid_display_host:
            raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
        item: dict[str, object] = {
            "candidate_ordinal": ordinal,
            "status": "ready",
            "display_host": display_host,
        }
        for key, maximum in (("title", 200), ("description", 500), ("site_name", 120), ("image_alt", 200)):
            text = _safe_link_preview_text(preview.get(key), maximum)
            if text is not None:
                item[key] = text
        image_id = preview.get("image_id")
        if image_id is not None:
            if not isinstance(image_id, str) or _LINK_PREVIEW_IMAGE_ID.fullmatch(image_id) is None:
                raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
            item["image_id"] = image_id
        result.append(item)
    if ordinals != sorted(set(ordinals)):
        raise BridgeLinkPreviewProjectionError("link_preview_projection_invalid")
    return {
        "schema_version": 1,
        "conversation_id": value["conversation_id"],
        "message_id": value["message_id"],
        "message_revision": value["message_revision"],
        "enabled": value["enabled"],
        "previews": result,
    }


def _bounded_link_preview_response(payload: dict[str, object], status: int) -> tuple[dict[str, object], int]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return (payload, status) if len(body) <= MAXIMUM_BRIDGE_RESPONSE_BODY_BYTES else _link_preview_failure("error")


def bridge_link_previews_payload(
    conversation_id: str,
    message_id: str,
    message_revision: int,
    *,
    action: str = "read",
) -> tuple[dict[str, object], int]:
    try:
        from server import mentat_link_previews_payload

        source, source_status = mentat_link_previews_payload(
            conversation_id,
            message_id,
            message_revision,
            action=action,
        )
        expected_status = 200 if action == "read" else 202
        if source_status != expected_status:
            return _link_preview_failure("error")
        ready = _ready_link_preview_payload(source)
        if ready["conversation_id"] != conversation_id or ready["message_id"] != message_id or ready["message_revision"] != message_revision:
            raise BridgeLinkPreviewProjectionError("link_preview_target_invalid")
        return _bounded_link_preview_response(
            {**ready, "service": "mentat-local-bridge", "runtime": "python", "status": "ready"},
            expected_status,
        )
    except LinkPreviewPreferenceConflict:
        return _link_preview_failure("conflict")
    except LinkPreviewServiceError as exc:
        return _link_preview_failure(exc.code.removeprefix("link_preview."))
    except (BridgeLinkPreviewProjectionError, LinkPreviewCacheError, OSError, ValueError):
        return _link_preview_failure("error")
    except Exception:
        return _link_preview_failure("error")


def bridge_link_preview_preference_payload(payload: object | None = None) -> tuple[dict[str, object], int]:
    try:
        if payload is None:
            from server import mentat_link_preview_preference_payload

            source = mentat_link_preview_preference_payload()
            status_code = 200
        else:
            from server import update_mentat_link_preview_preference

            source, status_code = update_mentat_link_preview_preference(payload)
        if (
            status_code != 200
            or not isinstance(source, dict)
            or set(source) != {"schema_version", "enabled", "revision"}
            or source.get("schema_version") != 1
            or type(source.get("enabled")) is not bool
            or type(source.get("revision")) is not int
            or source["revision"] < 1
        ):
            raise BridgeLinkPreviewProjectionError("link_preview_preference_invalid")
        return _bounded_link_preview_response(
            {**source, "service": "mentat-local-bridge", "runtime": "python", "status": "ready"},
            200,
        )
    except LinkPreviewPreferenceConflict:
        return _link_preview_failure("conflict")
    except LinkPreviewServiceError as exc:
        return _link_preview_failure(exc.code.removeprefix("link_preview."))
    except (BridgeLinkPreviewProjectionError, LinkPreviewCacheError, OSError, ValueError):
        return _link_preview_failure("error")
    except Exception:
        return _link_preview_failure("error")


def bridge_clear_link_preview_cache(payload: object) -> tuple[dict[str, object], int]:
    try:
        from server import clear_mentat_link_preview_cache

        source, status = clear_mentat_link_preview_cache(payload)
        if status != 200 or source != {"schema_version": 1, "cleared": True}:
            raise BridgeLinkPreviewProjectionError("link_preview_clear_invalid")
        return {
            **source,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
        }, 200
    except LinkPreviewServiceError as exc:
        return _link_preview_failure(exc.code.removeprefix("link_preview."))
    except (BridgeLinkPreviewProjectionError, LinkPreviewCacheError, OSError, ValueError):
        return _link_preview_failure("error")
    except Exception:
        return _link_preview_failure("error")


def bridge_link_preview_image(image_id: str) -> tuple[bytes, int] | None:
    try:
        from server import mentat_link_preview_image

        value = mentat_link_preview_image(image_id)
        if value is None:
            return None
        body, max_age = value
        if not valid_transformed_webp(body) or type(max_age) is not int or not 0 <= max_age <= 300:
            raise BridgeLinkPreviewProjectionError("link_preview_image_invalid")
        return body, max_age
    except Exception:
        return None


def bridge_create_conversation_payload(payload: object) -> tuple[dict[str, object], int]:
    """Create an empty durable Conversation through the one fixed write."""

    try:
        from server import create_mentat_conversation

        try:
            source, status = create_mentat_conversation(payload)
            if status != 201:
                return _conversation_failure("error")
            detail = _ready_conversation_detail(source)
            requested_agent_id = (
                payload.get("agent_id") if isinstance(payload, dict) else None
            )
            if (
                requested_agent_id is not None
                and detail["conversation"]["agent_id"] != requested_agent_id
            ):
                raise BridgeConversationProjectionError(
                    "conversation_agent_target_invalid"
                )
            return _bounded_conversation_response(
                {
                    **detail,
                    "service": "mentat-local-bridge",
                    "runtime": "python",
                    "status": "ready",
                },
                201,
            )
        except ConversationRepositoryError as exc:
            if exc.code == "conversation.agent_not_found":
                return _conversation_failure("not_found")
            if exc.code == "conversation.schema_unsupported":
                return _conversation_failure("unsupported")
            return _conversation_failure("unavailable")
        except (BridgeConversationProjectionError, OSError, ValueError):
            return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def bridge_archive_conversation_payload(
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    """Archive or restore one exact Conversation through the private bridge."""

    try:
        from server import archive_mentat_conversation

        source, status = archive_mentat_conversation(conversation_id, payload)
        if status != 200:
            return _conversation_failure("invalid")
        if (
            not isinstance(source, dict)
            or set(source) != {"schema_version", "action", "conversation"}
            or source.get("schema_version") != 1
            or source.get("action") not in {"archive", "restore"}
        ):
            raise BridgeConversationProjectionError(
                "conversation_archive_invalid"
            )
        conversation = _public_conversation_summary(source.get("conversation"))
        requested_archived = (
            payload.get("archived") if isinstance(payload, dict) else None
        )
        if (
            conversation["id"] != conversation_id
            or requested_archived is True
            and (
                source["action"] != "archive"
                or conversation["state"] != "archived"
            )
            or requested_archived is False
            and (
                source["action"] != "restore"
                or conversation["state"] != "active"
            )
        ):
            raise BridgeConversationProjectionError(
                "conversation_archive_invalid"
            )
        return _bounded_conversation_response(
            {
                "schema_version": 1,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
                "action": source["action"],
                "conversation": conversation,
            },
            200,
        )
    except ConversationRepositoryConflict as exc:
        if exc.code == "conversation.not_found":
            return _conversation_failure("not_found")
        return _conversation_failure("conflict")
    except ConversationRepositoryError as exc:
        if exc.code.endswith("invalid"):
            return _conversation_failure("invalid")
        return _conversation_failure("unavailable")
    except (BridgeConversationProjectionError, OSError, ValueError):
        return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def bridge_rename_conversation_payload(
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    """Rename one exact Conversation through the private bridge."""

    try:
        from server import rename_mentat_conversation

        source, status = rename_mentat_conversation(conversation_id, payload)
        if status != 200:
            return _conversation_failure("invalid")
        if (
            not isinstance(source, dict)
            or set(source) != {"schema_version", "action", "conversation"}
            or source.get("schema_version") != 1
            or source.get("action") != "rename"
        ):
            raise BridgeConversationProjectionError("conversation_rename_invalid")
        conversation = _public_conversation_summary(source.get("conversation"))
        if conversation["id"] != conversation_id or conversation["title_source"] != "manual":
            raise BridgeConversationProjectionError("conversation_rename_invalid")
        return _bounded_conversation_response(
            {
                "schema_version": 1,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
                "action": "rename",
                "conversation": conversation,
            },
            200,
        )
    except ConversationRepositoryConflict as exc:
        return _conversation_failure(
            "not_found" if exc.code == "conversation.not_found" else "conflict"
        )
    except ConversationRepositoryError as exc:
        if exc.code.endswith("invalid"):
            return _conversation_failure("invalid")
        return _conversation_failure("unavailable")
    except (BridgeConversationProjectionError, OSError, ValueError):
        return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def bridge_conversation_run_attempt_payload(
    action: str,
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    """Create one exact same-Turn Retry or Resume through the bridge."""

    try:
        from server import (
            resume_mentat_conversation_run,
            retry_mentat_conversation_run,
        )

        operation = (
            retry_mentat_conversation_run
            if action == "retry"
            else resume_mentat_conversation_run
        )
        source, status = operation(
            conversation_id,
            payload,
        )
        if status not in {200, 202}:
            return _conversation_submission_error(
                str(source.get("error_code") or "conversation.request_invalid")
            )
        if (
            not isinstance(source, dict)
            or set(source) != {
                "schema_version", "action", "conversation_id",
                "source_run_id", "duplicate", "run",
            }
            or source.get("schema_version") != 1
            or source.get("action") != action
            or source.get("conversation_id") != conversation_id
            or not isinstance(source.get("duplicate"), bool)
            or not isinstance(payload, dict)
            or source.get("source_run_id") != payload.get("source_run_id")
        ):
            raise BridgeConversationProjectionError(
                "conversation_retry_invalid"
            )
        run = _public_current_run(source.get("run"))
        if run is None:
            raise BridgeConversationProjectionError(
                "conversation_retry_invalid"
            )
        return _bounded_conversation_response(
            {
                **source,
                "run": run,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
            },
            status,
        )
    except OrchestrationServiceError as exc:
        return _conversation_submission_error(exc.code)
    except (BridgeConversationProjectionError, ConversationRepositoryError):
        return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def bridge_retry_conversation_run_payload(
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    return bridge_conversation_run_attempt_payload(
        "retry", conversation_id, payload
    )


def bridge_resume_conversation_run_payload(
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    return bridge_conversation_run_attempt_payload(
        "resume", conversation_id, payload
    )


def _public_conversation_turn(value: object) -> dict[str, object]:
    required = {
        "id", "conversation_id", "user_message_id", "queue_ordinal", "state",
        "blocked_reason", "latest_run_id", "revision", "attempt_count",
        "created_at", "updated_at",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("conversation_turn_invalid")
    latest_run_id = value.get("latest_run_id")
    if (
        not isinstance(value.get("id"), str)
        or _TURN_ID.fullmatch(value["id"]) is None
        or not isinstance(value.get("conversation_id"), str)
        or _CONVERSATION_ID.fullmatch(value["conversation_id"]) is None
        or not isinstance(value.get("user_message_id"), str)
        or _MESSAGE_ID.fullmatch(value["user_message_id"]) is None
        or type(value.get("queue_ordinal")) is not int
        or value["queue_ordinal"] < 1
        or value.get("state")
        not in {"pending", "dispatching", "consumed", "blocked", "cancelled"}
        or (value.get("state") == "blocked")
        != (value.get("blocked_reason") is not None)
        or value.get("blocked_reason") is not None
        and value["blocked_reason"]
        not in {"capacity", "failed", "stopped", "interrupted", "unknown", "partial"}
        or latest_run_id is not None
        and (
            not isinstance(latest_run_id, str)
            or _RUN_ID.fullmatch(latest_run_id) is None
        )
        or type(value.get("revision")) is not int
        or value["revision"] < 1
        or type(value.get("attempt_count")) is not int
        or not 0 <= value["attempt_count"] <= 8
        or not _conversation_timestamp(value.get("created_at"))
        or not _conversation_timestamp(value.get("updated_at"))
    ):
        raise BridgeConversationProjectionError("conversation_turn_invalid")
    return dict(value)


def _ready_conversation_turn_submission(value: object) -> dict[str, object]:
    required = {
        "schema_version", "duplicate", "disposition", "conversation",
        "message", "turn", "run",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("conversation_submission_invalid")
    if (
        value.get("schema_version") != 1
        or not isinstance(value.get("duplicate"), bool)
        or value.get("disposition")
        not in {
            "pending", "blocked", "reserved", "submitting", "accepted",
            "rejected", "unknown",
        }
    ):
        raise BridgeConversationProjectionError("conversation_submission_invalid")
    conversation = _public_conversation_summary(value.get("conversation"))
    message = _public_conversation_message(value.get("message"))
    turn = _public_conversation_turn(value.get("turn"))
    run = _public_current_run(value.get("run"))
    if (
        message["conversation_id"] != conversation["id"]
        or turn["conversation_id"] != conversation["id"]
        or turn["user_message_id"] != message["id"]
        or message["run_id"] != turn["latest_run_id"]
        or run is not None and run["id"] != turn["latest_run_id"]
    ):
        raise BridgeConversationProjectionError("conversation_submission_invalid")
    return {
        "schema_version": 1,
        "duplicate": value["duplicate"],
        "disposition": value["disposition"],
        "conversation": conversation,
        "message": message,
        "turn": turn,
        "run": run,
    }


def _conversation_submission_error(code: str) -> tuple[dict[str, object], int]:
    if code in {"conversation.not_found", "conversation.agent_not_found"}:
        return _conversation_failure("not_found")
    if code == "conversation.active_run":
        return _conversation_failure("active_run")
    if code in {
        "conversation.capacity_unavailable",
        "conversation.turn_capacity",
        "conversation.attempt_capacity",
    }:
        return _conversation_failure("capacity_unavailable")
    if code in {
        "conversation.idempotency_conflict",
        "conversation.attempt_idempotency_conflict",
    }:
        return _conversation_failure("idempotency_conflict")
    if code in {
        "conversation.active_run",
        "conversation.agent_changed",
        "conversation.binding_changed",
        "conversation.state_changed",
        "conversation.turn_changed",
        "conversation.turn_not_cancellable",
        "conversation.turn_not_continuable",
        "conversation.turn_not_editable",
        "conversation.turn_not_found",
        "conversation.attempt_stale",
    }:
        return _conversation_failure("conflict")
    if code == "codex.cli_missing":
        return _conversation_failure("cli_missing")
    if code == "codex.sign_in_required":
        return _conversation_failure("sign_in_required")
    if code in {
        "conversation.agent_capability_missing",
        "conversation.runtime_capability_missing",
        "conversation.resume_unavailable",
        "runtime.binding_invalid",
    }:
        return _conversation_failure("unsupported")
    if code.endswith("invalid"):
        return _conversation_failure("invalid")
    if code in {
        "codex.unavailable",
        "conversation.unavailable",
        "run_repository.unavailable",
    }:
        return _conversation_failure("unavailable")
    return _conversation_failure("error")


def bridge_submit_conversation_turn_payload(
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    """Submit one text Turn through the fixed private capability."""

    try:
        from server import submit_mentat_conversation_turn

        source, status = submit_mentat_conversation_turn(conversation_id, payload)
        if status not in {200, 202}:
            return _conversation_submission_error(
                str(source.get("error_code") or "conversation.request_invalid")
            )
        ready = _ready_conversation_turn_submission(source)
        requested_text = payload.get("text") if isinstance(payload, dict) else None
        if (
            ready["conversation"]["id"] != conversation_id
            or ready["message"]["content"]["parts"][0]["text"]
            != requested_text
        ):
            raise BridgeConversationProjectionError(
                "conversation_submission_target_invalid"
            )
        return _bounded_conversation_response(
            {
                **ready,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
            },
            status,
        )
    except OrchestrationServiceError as exc:
        return _conversation_submission_error(exc.code)
    except (BridgeConversationProjectionError, ConversationRepositoryError):
        return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def _ready_conversation_queue_mutation(value: object) -> dict[str, object]:
    required = {
        "schema_version", "disposition", "conversation", "message", "turn",
    }
    if (
        not isinstance(value, dict)
        or set(value) != required
        or value.get("schema_version") != 1
        or value.get("disposition") not in {"edited", "cancelled"}
    ):
        raise BridgeConversationProjectionError("conversation_mutation_invalid")
    conversation = _public_conversation_summary(value.get("conversation"))
    message = _public_conversation_message(value.get("message"))
    turn = _public_conversation_turn(value.get("turn"))
    if (
        message["conversation_id"] != conversation["id"]
        or turn["conversation_id"] != conversation["id"]
        or turn["user_message_id"] != message["id"]
        or message["run_id"] != turn["latest_run_id"]
        or value["disposition"] == "edited"
        and (turn["state"] not in {"pending", "blocked"} or message["state"] != "accepted")
        or value["disposition"] == "cancelled"
        and (turn["state"] != "cancelled" or message["state"] != "cancelled")
    ):
        raise BridgeConversationProjectionError("conversation_mutation_invalid")
    return {
        "schema_version": 1,
        "disposition": value["disposition"],
        "conversation": conversation,
        "message": message,
        "turn": turn,
    }


def bridge_mutate_conversation_turn_payload(
    conversation_id: str,
    turn_id: str,
    action: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    """Apply one fixed queue mutation through the private bridge."""

    try:
        from server import mutate_mentat_conversation_turn

        source, status = mutate_mentat_conversation_turn(
            conversation_id,
            turn_id,
            action,
            payload,
        )
        if status not in {200, 202}:
            return _conversation_submission_error(
                str(source.get("error_code") or "conversation.request_invalid")
            )
        ready = (
            _ready_conversation_turn_submission(source)
            if action == "continue"
            else _ready_conversation_queue_mutation(source)
        )
        if (
            ready["conversation"]["id"] != conversation_id
            or ready["turn"]["id"] != turn_id
            or action == "edit"
            and (
                not isinstance(payload, dict)
                or ready["message"]["content"]["parts"][0]["text"]
                != payload.get("text")
            )
        ):
            raise BridgeConversationProjectionError(
                "conversation_mutation_target_invalid"
            )
        return _bounded_conversation_response(
            {
                **ready,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
            },
            status,
        )
    except OrchestrationServiceError as exc:
        return _conversation_submission_error(exc.code)
    except (BridgeConversationProjectionError, ConversationRepositoryError):
        return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def bridge_steer_conversation_payload(
    conversation_id: str,
    payload: object,
) -> tuple[dict[str, object], int]:
    """Steer one exact active Conversation Run without queue writes."""

    try:
        from server import OrchestrationRunActionError, steer_mentat_conversation

        try:
            source, status = steer_mentat_conversation(conversation_id, payload)
            if status != 200:
                return _conversation_failure("invalid")
            if (
                not isinstance(source, dict)
                or set(source)
                != {
                    "schema_version", "action", "conversation_id", "run_id",
                    "disposition",
                }
                or source.get("schema_version") != 1
                or source.get("action") != "steer"
                or source.get("conversation_id") != conversation_id
                or not isinstance(source.get("run_id"), str)
                or _RUN_ID.fullmatch(source["run_id"]) is None
                or not isinstance(payload, dict)
                or source.get("run_id") != payload.get("run_id")
                or source.get("disposition") != "accepted"
            ):
                raise BridgeConversationProjectionError(
                    "conversation_steer_invalid"
                )
            return {
                **source,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
            }, 200
        except OrchestrationRunActionError as exc:
            if exc.code in {"run.not_found", "conversation.not_found"}:
                return _conversation_failure("not_found")
            if exc.code in {
                "conversation.steer_invalid",
            }:
                return _conversation_failure("invalid")
            if exc.code in {
                "conversation.steer_stale",
                "run.binding_changed",
            }:
                return _conversation_failure("conflict")
            if exc.code == "conversation.steer_unsupported":
                return _conversation_failure("unsupported")
            if exc.code == "conversation.steer_partial":
                return _conversation_failure("partial")
            if exc.code in {"conversation.steer_unavailable", "run.unavailable"}:
                return _conversation_failure("unavailable")
            return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def bridge_codex_readiness_payload() -> tuple[dict[str, object], int]:
    """Project only the four approved Codex readiness states."""

    try:
        from server import mentat_codex_readiness_payload

        source = mentat_codex_readiness_payload()
        if not isinstance(source, dict) or set(source) != {
            "schema_version",
            "setup_command",
            "state",
        }:
            raise BridgeConversationProjectionError("codex_readiness_invalid")
        state = source.get("state")
        setup_command = source.get("setup_command")
        if (
            source.get("schema_version") != 1
            or state not in {
                "cli_missing",
                "sign_in_required",
                "ready",
                "unavailable",
            }
            or setup_command not in {None, "codex login"}
            or (state == "sign_in_required") != (setup_command == "codex login")
        ):
            raise BridgeConversationProjectionError("codex_readiness_invalid")
        return {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
            "state": state,
            "setup_command": setup_command,
        }, 200
    except Exception:
        return _conversation_failure("error")


def _public_activity_agent(value: object) -> dict[str, object]:
    return _public_conversation_agent(value)


def _public_activity_item(value: object) -> dict[str, object]:
    required = {"agent", "state", "summary", "attention", "updated_at", "conversations"}
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeConversationProjectionError("activity_projection_invalid")
    conversations = value.get("conversations")
    if (
        value.get("state") not in {
            "checking", "working", "waiting", "failed", "stopped", "interrupted", "idle"
        }
        or not _conversation_text(value.get("summary"), 160)
        or not isinstance(value.get("attention"), bool)
        or value.get("updated_at") is not None
        and not _conversation_timestamp(value.get("updated_at"))
        or not isinstance(conversations, list)
        or len(conversations) > 8
    ):
        raise BridgeConversationProjectionError("activity_projection_invalid")
    public_conversations = []
    for conversation in conversations:
        if not isinstance(conversation, dict) or set(conversation) != {
            "id", "title", "run_id", "run_status", "attention", "updated_at"
        }:
            raise BridgeConversationProjectionError("activity_projection_invalid")
        if (
            not isinstance(conversation.get("id"), str)
            or not _CONVERSATION_ID.fullmatch(conversation["id"])
            or not _conversation_text(conversation.get("title"), 160)
            or not isinstance(conversation.get("run_id"), str)
            or not _RUN_ID.fullmatch(conversation["run_id"])
            or conversation.get("run_status") not in {
                "reserved", "queued", "submitting", "starting", "running",
                "cancelling", "waiting", "waiting_for_approval",
                "waiting_for_clarification", "unknown", "finalizing", "reconciling", "failed", "completed",
                "stopped", "interrupted",
            }
            or not isinstance(conversation.get("attention"), bool)
            or not _conversation_timestamp(conversation.get("updated_at"))
        ):
            raise BridgeConversationProjectionError("activity_projection_invalid")
        public_conversations.append(dict(conversation))
    return {
        "agent": _public_activity_agent(value["agent"]),
        "state": value["state"],
        "summary": value["summary"],
        "attention": value["attention"],
        "updated_at": value["updated_at"],
        "conversations": public_conversations,
    }


def _ready_activity_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "activity", "direct_agent_id"
    }:
        raise BridgeConversationProjectionError("activity_projection_invalid")
    activity = value.get("activity")
    direct_agent_id = value.get("direct_agent_id")
    if (
        value.get("schema_version") != 1
        or not isinstance(activity, list)
        or len(activity) > MAXIMUM_BRIDGE_AGENTS
        or direct_agent_id is not None
        and (
            not isinstance(direct_agent_id, str)
            or not _OPAQUE_ID.fullmatch(direct_agent_id)
        )
    ):
        raise BridgeConversationProjectionError("activity_projection_invalid")
    public = [_public_activity_item(item) for item in activity]
    agent_ids = [item["agent"]["id"] for item in public]
    if len(set(agent_ids)) != len(agent_ids):
        raise BridgeConversationProjectionError("activity_projection_invalid")
    if direct_agent_id is not None and direct_agent_id not in agent_ids:
        raise BridgeConversationProjectionError("activity_projection_invalid")
    return {
        "schema_version": 1,
        "activity": public,
        "direct_agent_id": direct_agent_id,
    }


def bridge_agent_activity_payload() -> tuple[dict[str, object], int]:
    """Read bounded global Agent activity hints from canonical Runs."""

    try:
        from server import mentat_agent_activity_payload

        try:
            source = _ready_activity_payload(mentat_agent_activity_payload())
            return {
                **source,
                "service": "mentat-local-bridge",
                "runtime": "python",
                "status": "ready",
            }, 200
        except ConversationRepositoryError as exc:
            if exc.code == "conversation.schema_unsupported":
                return _conversation_failure("unsupported")
            return _conversation_failure("unavailable")
        except (BridgeConversationProjectionError, OSError, ValueError):
            return _conversation_failure("error")
    except Exception:
        return _conversation_failure("error")


def _public_provider_connection(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "id", "provider", "label", "state", "model", "capabilities"
    }:
        raise BridgeProviderConnectionProjectionError(
            "provider_connection_projection_invalid"
        )
    label = value.get("label")
    model = value.get("model")
    capabilities = value.get("capabilities")
    if (
        value.get("id") != "connection_vercel"
        or value.get("provider") != "vercel"
        or not isinstance(label, str)
        or not label.strip()
        or label.strip() != label
        or len(label) > 80
        or any(ord(character) < 32 or ord(character) == 127 for character in label)
        or value.get("state") not in {"configured", "needs_auth", "disconnected"}
        or not isinstance(model, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:+@/-]{1,159}", model)
        or "/" not in model
        or "//" in model
        or not isinstance(capabilities, list)
        or not 1 <= len(capabilities) <= 3
    ):
        raise BridgeProviderConnectionProjectionError(
            "provider_connection_projection_invalid"
        )
    allowed_ids = ("ai.gateway", "sandbox.readiness", "connect.token")
    public_capabilities: list[dict[str, str]] = []
    seen: set[str] = set()
    last_index = -1
    for capability in capabilities:
        if not isinstance(capability, dict) or set(capability) != {"id", "status"}:
            raise BridgeProviderConnectionProjectionError(
                "provider_connection_projection_invalid"
            )
        identifier = capability.get("id")
        status = capability.get("status")
        if identifier not in allowed_ids or status not in {
            "credential_present", "needs_auth", "disconnected"
        }:
            raise BridgeProviderConnectionProjectionError(
                "provider_connection_projection_invalid"
            )
        index = allowed_ids.index(identifier)
        if identifier in seen or index <= last_index:
            raise BridgeProviderConnectionProjectionError(
                "provider_connection_projection_invalid"
            )
        seen.add(identifier)
        last_index = index
        public_capabilities.append({"id": identifier, "status": status})
    state = value["state"]
    gateway = public_capabilities[0]
    if (
        gateway["id"] != "ai.gateway"
        or state == "configured" and gateway["status"] != "credential_present"
        or state == "needs_auth" and gateway["status"] != "needs_auth"
        or state == "disconnected"
        and any(item["status"] != "disconnected" for item in public_capabilities)
    ):
        raise BridgeProviderConnectionProjectionError(
            "provider_connection_projection_invalid"
        )
    return {
        "id": "connection_vercel",
        "provider": "vercel",
        "label": label,
        "state": state,
        "model": model,
        "capabilities": public_capabilities,
    }


def _ready_provider_connections_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "connections", "count"
    }:
        raise BridgeProviderConnectionProjectionError(
            "provider_connection_projection_invalid"
        )
    connections = value.get("connections")
    count = value.get("count")
    if (
        value.get("schema_version") != 1
        or not isinstance(connections, list)
        or type(count) is not int
        or count != len(connections)
        or not 0 <= count <= MAXIMUM_BRIDGE_PROVIDER_CONNECTIONS
    ):
        raise BridgeProviderConnectionProjectionError(
            "provider_connection_projection_invalid"
        )
    public = [_public_provider_connection(item) for item in connections]
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": "ready",
        "connections": public,
        "count": count,
    }


def bridge_provider_connections_payload() -> tuple[dict[str, object], int]:
    """Read one secret-free provider projection through a fixed capability."""

    try:
        from server import mentat_provider_connections_payload
        from vercel_connections import VercelConnectionError

        try:
            return _ready_provider_connections_payload(
                mentat_provider_connections_payload()
            ), 200
        except VercelConnectionError as exc:
            if exc.code == "vercel.connection_unsupported":
                state, code = "unsupported", 501
            elif exc.code == "vercel.connection_unavailable":
                state, code = "unavailable", 503
            else:
                state, code = "error", 500
        except (BridgeProviderConnectionProjectionError, OSError, ValueError):
            state, code = "error", 500
    except Exception:
        state, code = "error", 500
    return {
        "schema_version": 1,
        "service": "mentat-local-bridge",
        "runtime": "python",
        "status": state,
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
    required = {
        "id",
        "run_id",
        "sequence",
        "type",
        "occurred_at",
        "summary",
        "message",
        "metrics",
        "presentation",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise BridgeRunEventProjectionError("event_projection_invalid")
    event_id, run_id, sequence = value.get("id"), value.get("run_id"), value.get("sequence")
    event_type, occurred_at = value.get("type"), value.get("occurred_at")
    summary, message, metrics, presentation = (
        value.get("summary"),
        value.get("message"),
        value.get("metrics"),
        value.get("presentation"),
    )
    allowed_metrics = {"input_tokens", "output_tokens", "total_tokens", "context_tokens", "context_length"}
    if (
        not isinstance(event_id, str) or not _OPAQUE_ID.fullmatch(event_id)
        or run_id != expected_run_id
        or type(sequence) is not int or not 1 <= sequence <= 10**9
        or event_type not in {"run.created", "dispatch.reserved", "run.started", "submission.unknown", "run.interrupted", "tool.requested", "tool.completed", "approval.required", "artifact.created", "cost", "run.stopped", "run.completed", "run.failed", "message"}
        or not _valid_timestamp(occurred_at)
        or not isinstance(summary, str) or not summary or summary.strip() != summary or len(summary) > 500 or "\0" in summary
        or message is not None and (
            event_type != "message"
            or not isinstance(message, str)
            or not message
            or message.strip() != message
            or len(message) > 20_000
            or "\0" in message
        )
        or not isinstance(metrics, dict) or set(metrics) - allowed_metrics
        or any(type(metric) is not int or not 0 <= metric <= 10**9 for metric in metrics.values())
        or not _safe_run_event_presentation(
            presentation,
            event_type=event_type,
            summary=summary,
        )
    ):
        raise BridgeRunEventProjectionError("event_projection_invalid")
    return {
        "id": event_id,
        "run_id": run_id,
        "sequence": sequence,
        "type": event_type,
        "occurred_at": occurred_at,
        "summary": summary,
        "message": message,
        "metrics": dict(metrics),
        "presentation": None if presentation is None else dict(presentation),
    }


def _safe_run_event_presentation(
    value: object,
    *,
    event_type: object,
    summary: object,
) -> bool:
    if value is None:
        return event_type not in {"tool.requested", "tool.completed"}
    if not isinstance(value, dict) or set(value) != {"kind", "phase", "label"}:
        return False
    kind, phase, label = value.get("kind"), value.get("phase"), value.get("label")
    if label != summary:
        return False
    allowed = {
        ("tool", "requested", "Tool activity requested", "tool.requested"),
        ("tool", "started", "Tool activity started", "tool.requested"),
        ("tool", "completed", "Tool activity completed", "tool.completed"),
        ("reasoning", "available", "Reasoning summary available", "message"),
    }
    return (kind, phase, label, event_type) in allowed


def _trusted_vercel_message_event_id(run_id: str) -> str:
    source_event_id = "vercel_message_" + hashlib.sha256(
        (run_id + ":message").encode("utf-8")
    ).hexdigest()[:24]
    return "event_" + hashlib.sha256(
        (run_id + ":" + source_event_id).encode("utf-8")
    ).hexdigest()[:24]


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
            message_count = sum(
                event["message"] is not None for event in public_events
            )
            trusted_message_id = _trusted_vercel_message_event_id(run_id)
            if (
                len(set(sequences)) != len(sequences)
                or sequences != sorted(sequences)
                or message_count > 1
                or any(
                    event["message"] is not None
                    and event["id"] != trusted_message_id
                    for event in public_events
                )
            ):
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


def bridge_refresh_run_payload(run_id: str) -> tuple[dict[str, object], int]:
    """Reconcile only the exact Run selected by the browser stream."""

    try:
        from run_repository import RunRepositoryConflict
        from server import refresh_mentat_run_payload

        source = refresh_mentat_run_payload(run_id)
        if (
            not isinstance(source, dict)
            or set(source) != {"schema_version", "run_id", "disposition"}
            or source.get("schema_version") != 1
            or source.get("run_id") != run_id
            or source.get("disposition") not in {"reconciled", "idle"}
        ):
            raise BridgeRunEventProjectionError("run_refresh_invalid")
        return {
            **source,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "ready",
        }, 200
    except OrchestrationServiceError:
        return {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "unavailable",
        }, 503
    except RunRepositoryConflict:
        return {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "not_found",
        }, 404
    except Exception:
        return {
            "schema_version": 1,
            "service": "mentat-local-bridge",
            "runtime": "python",
            "status": "error",
        }, 500


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

    def _send_webp(self, body: bytes, max_age: int) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "image/webp")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", f"private, max-age={max_age}, no-transform")
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _send_attachment_content(self, metadata: dict[str, object], stream: object) -> None:
        expected_size = metadata.get("byte_size")
        mime_type = metadata.get("mime_type")
        kind = metadata.get("kind")
        if (
            type(expected_size) is not int
            or not 1 <= expected_size <= MAXIMUM_BRIDGE_UPLOAD_BODY_BYTES
            or not callable(getattr(stream, "read", None))
            or not callable(getattr(stream, "close", None))
        ):
            if callable(getattr(stream, "close", None)):
                stream.close()
            self._send_json({"error": "bridge_route_not_found"}, 404)
            return
        content_type = (
            str(mime_type)
            if kind == "image" and mime_type in _SAFE_IMAGE_CONTENT_TYPES
            else "text/plain; charset=utf-8"
        )
        try:
            stream.seek(0, 2)
            actual_size = stream.tell()
            stream.seek(0)
        except (AttributeError, OSError, ValueError):
            stream.close()
            self._send_json({"error": "bridge_route_not_found"}, 404)
            return
        if actual_size != expected_size:
            stream.close()
            self._send_json({"error": "bridge_route_not_found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(expected_size))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("Content-Security-Policy", "default-src 'none'; sandbox")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        remaining = expected_size
        try:
            while remaining:
                chunk = stream.read(min(64 * 1024, remaining))
                if (
                    not isinstance(chunk, bytes)
                    or not chunk
                    or len(chunk) > remaining
                ):
                    self.close_connection = True
                    return
                self.wfile.write(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                self.close_connection = True
        finally:
            stream.close()

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
        content_types = self.headers.get_all("Content-Type", failobj=[]) or []
        lengths = self.headers.get_all("Content-Length", failobj=[]) or []
        transfer_encodings = self.headers.get_all("Transfer-Encoding", failobj=[]) or []
        if (
            len(content_types) != 1
            or content_types[0].lower() != "application/json"
            or len(lengths) != 1
            or transfer_encodings
        ):
            return None
        maximum_digits = len(str(maximum_bytes))
        if not re.fullmatch(rf"[1-9][0-9]{{0,{maximum_digits - 1}}}", lengths[0]):
            return None
        size = int(lengths[0])
        if size > maximum_bytes:
            return None
        try:
            body = self._read_exact_body(size)
            if body is None:
                return None
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, TimeoutError):
            return None
        return value if isinstance(value, dict) else None

    def _raw_upload_body(self) -> tuple[str, str, bytes] | None:
        """Read one exact bounded upload with fixed metadata headers."""

        content_types = self.headers.get_all("Content-Type", failobj=[]) or []
        lengths = self.headers.get_all("Content-Length", failobj=[]) or []
        filenames = self.headers.get_all(
            BRIDGE_UPLOAD_FILENAME_HEADER, failobj=[]
        ) or []
        if (
            len(content_types) != 1
            or len(lengths) != 1
            or len(filenames) != 1
            or self.headers.get_all("Transfer-Encoding", failobj=[])
            or self.headers.get_all("Content-Encoding", failobj=[])
            or self.headers.get_all("Content-Range", failobj=[])
            or self.headers.get_all("Trailer", failobj=[])
            or self.headers.get_all("Expect", failobj=[])
        ):
            return None
        content_type = content_types[0].strip().lower()
        if content_type not in _SAFE_UPLOAD_CONTENT_TYPES:
            return None
        maximum_digits = len(str(MAXIMUM_BRIDGE_UPLOAD_BODY_BYTES))
        if re.fullmatch(
            rf"[1-9][0-9]{{0,{maximum_digits - 1}}}", lengths[0]
        ) is None:
            return None
        size = int(lengths[0])
        if size > MAXIMUM_BRIDGE_UPLOAD_BODY_BYTES:
            return None
        encoded_name = filenames[0]
        if (
            not 1 <= len(encoded_name) <= 1024
            or re.fullmatch(r"(?:[A-Za-z0-9_.!~*'()-]|%[0-9A-F]{2})+", encoded_name)
            is None
        ):
            return None
        try:
            original_name = unquote_to_bytes(encoded_name).decode("utf-8")
        except UnicodeDecodeError:
            return None
        if (
            quote(original_name, safe="-_.!~*'()") != encoded_name
            or not 1 <= len(original_name) <= 255
            or re.search(
                r"[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]",
                original_name,
            )
        ):
            return None
        try:
            content = self._read_exact_body(size)
        except (OSError, TimeoutError):
            return None
        if content is None or len(content) != size:
            return None
        return original_name, content_type, content

    def _read_exact_body(self, size: int) -> bytes | None:
        """Read one declared body exactly within a total wall-clock deadline."""

        deadline = time.monotonic() + BRIDGE_BODY_READ_TIMEOUT_SECONDS
        previous_timeout = self.connection.gettimeout()
        chunks: list[bytes] = []
        remaining = size
        try:
            while remaining:
                timeout = deadline - time.monotonic()
                if timeout <= 0:
                    return None
                self.connection.settimeout(timeout)
                chunk = self.rfile.read1(
                    min(remaining, BRIDGE_BODY_READ_CHUNK_BYTES)
                )
                if not chunk:
                    return None
                chunks.append(chunk)
                remaining -= len(chunk)
        finally:
            self.connection.settimeout(previous_timeout)
        return b"".join(chunks)

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
        agent_attachment_status_match = re.fullmatch(
            r"/bridge/v1/agents/([^/]+)/attachments/enable",
            parsed.path,
        )
        if agent_attachment_status_match is not None and not parsed.query:
            agent_id = unquote(agent_attachment_status_match.group(1))
            if _OPAQUE_ID.fullmatch(agent_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_agent_attachment_enable_status(agent_id)
            self._send_json(payload, status)
            return
        agent_configuration_match = re.fullmatch(
            r"/bridge/v1/agents/([^/]+)/configuration", parsed.path
        )
        if agent_configuration_match is not None and not parsed.query:
            agent_id = unquote(agent_configuration_match.group(1))
            if _OPAQUE_ID.fullmatch(agent_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_agent_configuration_payload(agent_id)
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_PROVIDER_CONNECTIONS_PATH and not parsed.query:
            payload, status = bridge_provider_connections_payload()
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
        if parsed.path == BRIDGE_COMMAND_MANIFEST_PATH and not parsed.query:
            payload, status = bridge_command_manifest_payload()
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_PLANNING_OVERVIEW_PATH and not parsed.query:
            payload, status = bridge_planning_overview_payload()
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_PLANNING_TASKS_PATH:
            try:
                pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            except ValueError:
                pairs = []
            values = {key: value for key, value in pairs}
            if (
                not pairs
                or len(values) != len(pairs)
                or set(values) - {"project_id", "cursor"}
                or _PROJECT_ID.fullmatch(values.get("project_id", "")) is None
                or "cursor" in values
                and re.fullmatch(r"[A-Za-z0-9_-]{1,512}", values["cursor"]) is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_planning_tasks_payload(
                values["project_id"], values.get("cursor")
            )
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_PLANNING_TASK_PATH:
            try:
                pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            except ValueError:
                pairs = []
            if (
                len(pairs) != 1
                or pairs[0][0] != "task_id"
                or _TASK_ID.fullmatch(pairs[0][1]) is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_planning_task_payload(pairs[0][1])
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_CONVERSATION_HISTORY_PATH:
            try:
                pairs = parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                    strict_parsing=True,
                )
            except ValueError:
                pairs = []
            values = {key: value for key, value in pairs}
            if (
                not pairs
                or len(values) != len(pairs)
                or set(values) - {"state", "q", "cursor"}
                or values.get("state") not in {"all", "active", "archived"}
                or "q" in values
                and (
                    not values["q"]
                    or values["q"].strip() != values["q"]
                    or len(values["q"]) > 160
                    or re.search(r"[\x00-\x1f\x7f]", values["q"])
                )
                or "cursor" in values
                and re.fullmatch(r"[A-Za-z0-9_-]{1,512}", values["cursor"])
                is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_conversation_history_payload(
                state=values["state"],
                query=values.get("q"),
                cursor=values.get("cursor"),
            )
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_CONVERSATIONS_PATH:
            try:
                pairs = parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                    strict_parsing=True,
                )
            except ValueError:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            if len(pairs) > 1 or pairs and (
                pairs[0][0] != "cursor"
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", pairs[0][1]) is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            cursor = pairs[0][1] if pairs else None
            payload, status = bridge_conversations_payload(cursor)
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_AGENT_ACTIVITY_PATH and not parsed.query:
            payload, status = bridge_agent_activity_payload()
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_CODEX_READINESS_PATH and not parsed.query:
            payload, status = bridge_codex_readiness_payload()
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_LINK_PREVIEW_PREFERENCE_PATH and not parsed.query:
            payload, status = bridge_link_preview_preference_payload()
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_WORKSPACE_FILES_PATH:
            try:
                pairs = parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                    strict_parsing=True,
                )
            except ValueError:
                pairs = []
            if (
                len(pairs) != 1
                or pairs[0][0] != "query"
                or len(pairs[0][1]) > 200
                or re.search(r"[\x00-\x1f\x7f]", pairs[0][1])
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_workspace_files_payload(pairs[0][1])
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_CONTEXT_PACKS_PATH and not parsed.query:
            payload, status = bridge_context_pack_summaries_payload()
            self._send_json(payload, status)
            return
        link_preview_image_match = re.fullmatch(
            r"/bridge/v1/link-previews/images/([^/]+)", parsed.path
        )
        if link_preview_image_match is not None and not parsed.query:
            image_id = unquote(link_preview_image_match.group(1))
            if _LINK_PREVIEW_IMAGE_ID.fullmatch(image_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            image = bridge_link_preview_image(image_id)
            if image is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
            else:
                self._send_webp(*image)
            return
        link_preview_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/messages/([^/]+)/link-previews",
            parsed.path,
        )
        if link_preview_match is not None:
            conversation_id = unquote(link_preview_match.group(1))
            message_id = unquote(link_preview_match.group(2))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None or _MESSAGE_ID.fullmatch(message_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            try:
                pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
            except ValueError:
                pairs = []
            if len(pairs) != 1 or pairs[0][0] != "revision" or re.fullmatch(r"[1-9][0-9]{0,9}", pairs[0][1]) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_link_previews_payload(
                conversation_id,
                message_id,
                int(pairs[0][1]),
            )
            self._send_json(payload, status)
            return
        conversation_content_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/attachments/([^/]+)/content",
            parsed.path,
        )
        if conversation_content_match is not None and not parsed.query:
            conversation_id = unquote(conversation_content_match.group(1))
            attachment_id = unquote(conversation_content_match.group(2))
            if (
                _CONVERSATION_ID.fullmatch(conversation_id) is None
                or _ATTACHMENT_ID.fullmatch(attachment_id) is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            metadata, stream, status = bridge_conversation_attachment_content(
                conversation_id,
                attachment_id,
            )
            if status != 200 or metadata is None or stream is None:
                self._send_json(
                    metadata or _conversation_file_failure(status)[0],
                    status,
                )
            else:
                self._send_attachment_content(metadata, stream)
            return
        staged_context_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/staged-context",
            parsed.path,
        )
        if staged_context_match is not None and not parsed.query:
            conversation_id = unquote(staged_context_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            with _conversation_file_sequence(conversation_id):
                payload, status = bridge_conversation_staged_context_payload(
                    conversation_id
                )
            self._send_json(payload, status)
            return
        conversation_media_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/media",
            parsed.path,
        )
        if conversation_media_match is not None and not parsed.query:
            conversation_id = unquote(conversation_media_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_conversation_media_payload(conversation_id)
            self._send_json(payload, status)
            return
        conversation_planning_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/planning-context", parsed.path
        )
        if conversation_planning_match is not None and not parsed.query:
            conversation_id = unquote(conversation_planning_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_conversation_planning_context_payload(
                conversation_id
            )
            self._send_json(payload, status)
            return
        conversation_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)", parsed.path
        )
        if conversation_match is not None:
            conversation_id = unquote(conversation_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            try:
                pairs = parse_qsl(
                    parsed.query,
                    keep_blank_values=True,
                    strict_parsing=True,
                )
            except ValueError:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            if len(pairs) > 1 or pairs and (
                pairs[0][0] != "before"
                or re.fullmatch(r"[1-9][0-9]{0,9}", pairs[0][1]) is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            before = int(pairs[0][1]) if pairs else None
            payload, status = bridge_conversation_payload(conversation_id, before)
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
        if parsed.path == BRIDGE_PROJECTS_PATH and not parsed.query:
            body = self._action_json_body(MAXIMUM_BRIDGE_ACTION_BODY_BYTES)
            if body is None or set(body) != {"name"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_create_project_payload(body)
            self._send_json(payload, status)
            return
        project_task_match = re.fullmatch(
            r"/bridge/v1/projects/([^/]+)/tasks", parsed.path
        )
        if project_task_match is not None and not parsed.query:
            project_id = unquote(project_task_match.group(1))
            if _PROJECT_ID.fullmatch(project_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(MAXIMUM_BRIDGE_ACTION_BODY_BYTES)
            if body is None or set(body) != {"title", "assigned_agent_id", "due_date"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_create_project_task_payload(project_id, body)
            self._send_json(payload, status)
            return
        planning_project_match = re.fullmatch(
            r"/bridge/v1/planning/projects/([^/]+)", parsed.path
        )
        if planning_project_match is not None and not parsed.query:
            project_id = unquote(planning_project_match.group(1))
            if _PROJECT_ID.fullmatch(project_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(MAXIMUM_BRIDGE_ACTION_BODY_BYTES)
            if body is None or set(body) != {"expected_revision", "action", "name"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_update_planning_project_payload(project_id, body)
            self._send_json(payload, status)
            return
        planning_task_match = re.fullmatch(
            r"/bridge/v1/planning/tasks/([^/]+)/(edit|move)", parsed.path
        )
        if planning_task_match is not None and not parsed.query:
            task_id = unquote(planning_task_match.group(1))
            action = planning_task_match.group(2)
            if _TASK_ID.fullmatch(task_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(MAXIMUM_BRIDGE_PLANNING_MUTATION_BODY_BYTES)
            required = (
                {"expected_revision", "changes"}
                if action == "edit"
                else {"expected_task_revision", "project_id", "expected_project_revision"}
            )
            if body is None or set(body) != required:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = (
                bridge_update_planning_task_payload(task_id, body)
                if action == "edit"
                else bridge_move_planning_task_payload(task_id, body)
            )
            self._send_json(payload, status)
            return
        conversation_planning_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/planning-context", parsed.path
        )
        if conversation_planning_match is not None and not parsed.query:
            conversation_id = unquote(conversation_planning_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(MAXIMUM_BRIDGE_ACTION_BODY_BYTES)
            if body is None or set(body) != {"expected_revision", "project_id", "task_id"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_set_conversation_planning_context_payload(
                conversation_id, body
            )
            self._send_json(payload, status)
            return
        conversation_upload_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/attachments",
            parsed.path,
        )
        if conversation_upload_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_upload_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            upload = self._raw_upload_body()
            if upload is None:
                lengths = self.headers.get_all("Content-Length", failobj=[]) or []
                content_types = self.headers.get_all("Content-Type", failobj=[]) or []
                if (
                    len(lengths) == 1
                    and re.fullmatch(r"[1-9][0-9]{0,15}", lengths[0])
                    and int(lengths[0]) > MAXIMUM_BRIDGE_UPLOAD_BODY_BYTES
                ):
                    payload, status = _conversation_file_failure(413)
                    self._send_json(payload, status)
                elif (
                    len(content_types) == 1
                    and content_types[0].strip().lower()
                    not in _SAFE_UPLOAD_CONTENT_TYPES
                ):
                    payload, status = _conversation_file_failure(415)
                    self._send_json(payload, status)
                else:
                    self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            original_name, content_type, content = upload
            with _conversation_file_sequence(conversation_id):
                payload, status = bridge_stage_conversation_upload(
                    conversation_id,
                    original_name=original_name,
                    content_type=content_type,
                    content=content,
                )
            self._send_json(payload, status)
            return
        conversation_release_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/attachments/([^/]+)/release",
            parsed.path,
        )
        if conversation_release_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_release_match.group(1))
            attachment_id = unquote(conversation_release_match.group(2))
            if (
                _CONVERSATION_ID.fullmatch(conversation_id) is None
                or _ATTACHMENT_ID.fullmatch(attachment_id) is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body()
            if body != {}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            with _conversation_file_sequence(conversation_id):
                payload, status = bridge_release_conversation_attachment(
                    conversation_id,
                    attachment_id,
                )
            self._send_json(payload, status)
            return
        conversation_workspace_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/workspace-files",
            parsed.path,
        )
        if conversation_workspace_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_workspace_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(MAXIMUM_BRIDGE_WORKSPACE_BODY_BYTES)
            if body is None or set(body) != {"root_id", "relative_path"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            with _conversation_file_sequence(conversation_id):
                payload, status = bridge_stage_workspace_file(conversation_id, body)
            self._send_json(payload, status)
            return
        conversation_context_pack_clear_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/context-packs/release",
            parsed.path,
        )
        if conversation_context_pack_clear_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_context_pack_clear_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body()
            if body != {}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            with _conversation_file_sequence(conversation_id):
                payload, status = bridge_clear_conversation_context_pack(
                    conversation_id,
                    body,
                )
            self._send_json(payload, status)
            return
        conversation_context_pack_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/context-packs/([^/]+)",
            parsed.path,
        )
        if conversation_context_pack_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_context_pack_match.group(1))
            pack_id = unquote(conversation_context_pack_match.group(2))
            if (
                _CONVERSATION_ID.fullmatch(conversation_id) is None
                or _CONTEXT_PACK_ID.fullmatch(pack_id) is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body()
            if (
                body is None
                or set(body) != {"expected_revision"}
                or not isinstance(body.get("expected_revision"), str)
                or _CONTEXT_PACK_REVISION.fullmatch(body["expected_revision"])
                is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            with _conversation_file_sequence(conversation_id):
                payload, status = bridge_apply_conversation_context_pack(
                    conversation_id,
                    pack_id,
                    body,
                )
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_LINK_PREVIEW_PREFERENCE_PATH and not parsed.query:
            body = self._action_json_body()
            if body is None or set(body) != {"enabled", "expected_revision"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_link_preview_preference_payload(body)
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_LINK_PREVIEW_CACHE_CLEAR_PATH and not parsed.query:
            body = self._action_json_body()
            if body != {}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_clear_link_preview_cache(body)
            self._send_json(payload, status)
            return
        link_preview_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/messages/([^/]+)/link-previews",
            parsed.path,
        )
        if link_preview_match is not None and not parsed.query:
            conversation_id = unquote(link_preview_match.group(1))
            message_id = unquote(link_preview_match.group(2))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None or _MESSAGE_ID.fullmatch(message_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body()
            if body is None or set(body) != {"message_revision", "action"} or body.get("action") not in {"enqueue", "retry"} or type(body.get("message_revision")) is not int or body["message_revision"] < 1:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_link_previews_payload(
                conversation_id,
                message_id,
                body.get("message_revision"),
                action=str(body["action"]),
            )
            self._send_json(payload, status)
            return
        agent_attachment_match = re.fullmatch(
            r"/bridge/v1/agents/([^/]+)/attachments/enable",
            parsed.path,
        )
        if agent_attachment_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            agent_id = unquote(agent_attachment_match.group(1))
            if _OPAQUE_ID.fullmatch(agent_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(
                MAXIMUM_BRIDGE_AGENT_CAPABILITY_BODY_BYTES
            )
            expected = None if body is None else body.get("expected_capabilities")
            if (
                body is None
                or set(body) != {"expected_capabilities"}
                or not isinstance(expected, list)
                or len(expected) > 64
                or expected != sorted(set(expected))
                or any(
                    not isinstance(capability, str)
                    or _CAPABILITY.fullmatch(capability) is None
                    for capability in expected
                )
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_enable_agent_attachments(agent_id, body)
            self._send_json(payload, status)
            return
        agent_configuration_match = re.fullmatch(
            r"/bridge/v1/agents/([^/]+)/configuration(?:/(preview))?",
            parsed.path,
        )
        if agent_configuration_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            agent_id = unquote(agent_configuration_match.group(1))
            preview = agent_configuration_match.group(2) == "preview"
            if _OPAQUE_ID.fullmatch(agent_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(MAXIMUM_BRIDGE_ACTION_BODY_BYTES)
            required = (
                {"provider", "model"}
                if preview
                else {"provider", "model", "confirmation_id"}
            )
            if body is None or set(body) != required:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_agent_configuration_mutation(
                agent_id,
                body,
                preview=preview,
            )
            self._send_json(payload, status)
            return
        if parsed.path == BRIDGE_CONVERSATIONS_PATH and not parsed.query:
            body = self._action_json_body()
            if body is None or set(body) - {"agent_id"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_create_conversation_payload(body)
            self._send_json(payload, status)
            return
        conversation_retry_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/(retry|resume)",
            parsed.path,
        )
        if conversation_retry_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_retry_match.group(1))
            action = conversation_retry_match.group(2)
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(
                MAXIMUM_BRIDGE_CONVERSATION_TURN_BODY_BYTES
            )
            if body is None or set(body) != {
                "idempotency_key",
                "source_run_id",
            }:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            operation = (
                bridge_retry_conversation_run_payload
                if action == "retry"
                else bridge_resume_conversation_run_payload
            )
            payload, status = operation(conversation_id, body)
            self._send_json(payload, status)
            return
        conversation_archive_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/(archive|restore)",
            parsed.path,
        )
        if conversation_archive_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_archive_match.group(1))
            action = conversation_archive_match.group(2)
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(MAXIMUM_BRIDGE_ACTION_BODY_BYTES)
            if body is None or set(body) != {"expected_revision"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_archive_conversation_payload(
                conversation_id,
                {
                    "archived": action == "archive",
                    "expected_revision": body["expected_revision"],
                },
            )
            self._send_json(payload, status)
            return
        conversation_rename_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/rename",
            parsed.path,
        )
        if conversation_rename_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_rename_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(MAXIMUM_BRIDGE_RENAME_BODY_BYTES)
            if (
                body is None
                or set(body) != {"expected_revision", "title"}
                or type(body.get("expected_revision")) is not int
                or body["expected_revision"] < 1
                or not isinstance(body.get("title"), str)
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_rename_conversation_payload(
                conversation_id,
                body,
            )
            self._send_json(payload, status)
            return
        conversation_queue_action_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/turns/([^/]+)/(edit|cancel|continue)",
            parsed.path,
        )
        if conversation_queue_action_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_queue_action_match.group(1))
            turn_id = unquote(conversation_queue_action_match.group(2))
            action = conversation_queue_action_match.group(3)
            if (
                _CONVERSATION_ID.fullmatch(conversation_id) is None
                or _TURN_ID.fullmatch(turn_id) is None
            ):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(
                MAXIMUM_BRIDGE_CONVERSATION_TURN_BODY_BYTES
            )
            required = {
                "edit": {"expected_revision", "expected_message_revision", "text"},
                "cancel": {"expected_revision", "expected_message_revision"},
                "continue": {"expected_revision", "expected_message_revision"},
            }[action]
            if body is None or set(body) != required:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_mutate_conversation_turn_payload(
                conversation_id,
                turn_id,
                action,
                body,
            )
            self._send_json(payload, status)
            return
        conversation_steer_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/steer",
            parsed.path,
        )
        if conversation_steer_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_steer_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(
                MAXIMUM_BRIDGE_CONVERSATION_TURN_BODY_BYTES
            )
            if body is None or set(body) != {"run_id", "text"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_steer_conversation_payload(
                conversation_id,
                body,
            )
            self._send_json(payload, status)
            return
        conversation_turn_match = re.fullmatch(
            r"/bridge/v1/conversations/([^/]+)/turns",
            parsed.path,
        )
        if conversation_turn_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            conversation_id = unquote(conversation_turn_match.group(1))
            if _CONVERSATION_ID.fullmatch(conversation_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(
                MAXIMUM_BRIDGE_CONVERSATION_TURN_BODY_BYTES
            )
            if body is None or set(body) != {"idempotency_key", "text"}:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_submit_conversation_turn_payload(
                conversation_id,
                body,
            )
            self._send_json(payload, status)
            return
        run_refresh_match = re.fullmatch(
            r"/bridge/v1/runs/([^/]+)/refresh",
            parsed.path,
        )
        if run_refresh_match is not None:
            if parsed.query:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            run_id = unquote(run_refresh_match.group(1))
            if _RUN_ID.fullmatch(run_id) is None:
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            body = self._action_json_body(MAXIMUM_BRIDGE_ACTION_BODY_BYTES)
            if body is None or set(body):
                self._send_json({"error": "bridge_route_not_found"}, 404)
                return
            payload, status = bridge_refresh_run_payload(run_id)
            self._send_json(payload, status)
            return
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


def _recover_bridge_runs_before_ready() -> None:
    """Classify pre-start crash states before the bridge serves admission."""

    from server import (
        load_agent_console_runs_after_startup_recovery,
        recover_orchestration_crash_states_at_startup,
    )

    recover_orchestration_crash_states_at_startup(
        recover_legacy_console_runs=True,
    )
    load_agent_console_runs_after_startup_recovery()


def _reconcile_bridge_runs_at_startup() -> None:
    """Best-effort readback for durable Runs owned by the Node gateway."""

    try:
        from server import reconcile_orchestration_runtime_references_at_startup

        reconcile_orchestration_runtime_references_at_startup()
    except Exception:
        # The listener remains available when a runtime or its evidence cannot
        # be read. Durable leases expire and a later reconciliation can retry;
        # startup must never resubmit a Run.
        return


def start_bridge_startup_reconciliation() -> threading.Thread:
    """Start reconciliation after bridge bind without delaying readiness."""

    worker = threading.Thread(
        target=_reconcile_bridge_runs_at_startup,
        daemon=True,
        name="mentat-bridge-startup-reconciler",
    )
    worker.start()
    return worker


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.pop(BRIDGE_TOKEN_ENV, "")
    try:
        bridge = build_bridge_server(args.host, validate_bridge_port(args.port), token)
    except (BridgeConfigurationError, OSError) as exc:
        code = str(exc) if isinstance(exc, BridgeConfigurationError) else "bridge_bind_failed"
        print(f"Mentat Local Bridge refused startup: {code}", flush=True)
        return 2

    try:
        _recover_bridge_runs_before_ready()
    except Exception:
        bridge.server_close()
        print(
            "Mentat Local Bridge refused startup: startup_recovery_unavailable",
            flush=True,
        )
        return 2

    stopped = threading.Event()
    launcher_pid = configured_launcher_pid()

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
    start_bridge_startup_reconciliation()
    try:
        while not stopped.is_set() and launcher_is_running(launcher_pid):
            bridge.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.server_close()
        loaded_server = sys.modules.get("server")
        shutdown_runtimes = getattr(loaded_server, "shutdown_agent_runtimes", None)
        if callable(shutdown_runtimes):
            try:
                shutdown_runtimes()
            except Exception:
                pass
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
