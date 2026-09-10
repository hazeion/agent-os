"""Name-only canonical Agent creation for one server-owned local Hermes binding."""

from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Callable
import unicodedata
from uuid import uuid4

from agent_registry import AgentRegistry, INTERACTIVE_AGENT_CAPABILITIES, MAX_AGENTS, authority_receipt, _canonical_agent_records
from mentat_db import connect_existing_readonly
from private_state import private_state_lock


SETUP_STATES = frozenset({"available", "already_configured", "hermes_missing", "hermes_unconfigured", "remote_selected", "registry_full", "unavailable"})


class AgentSetupError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class LocalHermesSetup:
    state: str
    fingerprint: str = ""


def valid_name(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 120 and value == value.strip() and not any(unicodedata.category(char).startswith("C") for char in value)


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _public(agent) -> dict:
    return {"id": agent.id, "name": agent.name}


class AgentSetupService:
    """Caller also holds the existing durable recovery and Hermes operation locks."""

    def __init__(self, data_dir: Path, registry: AgentRegistry, probe: Callable[[], LocalHermesSetup]):
        self.data_dir, self.registry, self.probe = Path(data_dir), registry, probe

    def _snapshot(self):
        with connect_existing_readonly(self.data_dir) as connection:
            authority_receipt(connection, required=True)
            records = _canonical_agent_records(connection, supported_runtime_types=self.registry.supported_runtime_types)
            bindings = {str(row["id"]): (str(row["runtime_type"]), str(row["runtime_agent_ref"])) for row in connection.execute("SELECT id, runtime_type, runtime_agent_ref FROM agent_runtime_configs")}
        rows = []
        existing = None
        for record in records:
            binding = bindings[record.agent.runtime_config_id]
            rows.append([record.agent.id, record.revision, *binding, record.agent.runtime_config_id, sorted(record.agent.capabilities)])
            if binding == ("hermes", "default"):
                existing = record.agent
        if existing is not None:
            return "already_configured", _public(existing), None
        if len(records) >= MAX_AGENTS:
            return "registry_full", None, None
        target = self.probe()
        if target.state not in SETUP_STATES - {"already_configured", "registry_full"}:
            raise AgentSetupError("unavailable")
        if target.state == "available" and not target.fingerprint:
            raise AgentSetupError("unavailable")
        return target.state, None, [sorted(rows), target.fingerprint, list(INTERACTIVE_AGENT_CAPABILITIES)]

    def check(self) -> dict:
        with private_state_lock(self.data_dir):
            state, agent, _snapshot = self._snapshot()
            return {"schema_version": 1, "state": state, "agent": agent}

    def preview(self, name: object) -> dict:
        if not valid_name(name):
            raise AgentSetupError("invalid")
        with private_state_lock(self.data_dir):
            state, _agent, snapshot = self._snapshot()
            if state != "available":
                raise AgentSetupError("conflict" if state == "already_configured" else "unavailable")
            return {"schema_version": 1, "name": name, "confirmation_id": _digest(["mentat.agent-setup.v1", name, snapshot])}

    def confirm(self, name: object, confirmation_id: object) -> dict:
        if not valid_name(name) or not isinstance(confirmation_id, str) or re.fullmatch(r"[0-9a-f]{64}", confirmation_id) is None:
            raise AgentSetupError("invalid")
        with private_state_lock(self.data_dir):
            preview = self.preview(name)
            if not hmac.compare_digest(confirmation_id, preview["confirmation_id"]):
                raise AgentSetupError("conflict")
            agent = self.registry.create_agent(
                agent_id=f"agent_{uuid4().hex}", name=name,
                runtime_config_id=f"runtime_config_{uuid4().hex}",
                runtime_type="hermes", runtime_agent_ref="default",
                capabilities=INTERACTIVE_AGENT_CAPABILITIES,
            )
            # A lost response is resolved by Check setup returning this binding,
            # never by claiming a second creation or retrying an unknown write.
            readback = next((row.agent for row in self.registry.list_agent_records() if row.agent.id == agent.id), None)
            binding = self.registry.get_runtime_binding(agent.id)
            if readback != agent or binding.runtime_type != "hermes" or binding.runtime_agent_ref != "default":
                raise AgentSetupError("unavailable")
            return {"schema_version": 1, "agent": _public(agent)}
