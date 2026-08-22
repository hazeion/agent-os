"""Runtime-neutral orchestration contracts for Mentat's strangler migration.

The current dashboard still exposes legacy Hermes Console payloads.  These
types are the new internal boundary: Mentat identifiers stay separate from
runtime-owned references, and adapters project runtime activity into a small,
stable vocabulary before new orchestration consumers see it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable


_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_RUNTIME_TYPE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_CAPABILITY = re.compile(r"[a-z][a-z0-9_.-]{0,63}")


class AgentStatus(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    FAILED = "failed"
    OFFLINE = "offline"


class TaskStatus(StrEnum):
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"


class RunStatus(StrEnum):
    RESERVED = "reserved"
    QUEUED = "queued"
    SUBMITTING = "submitting"
    STARTING = "starting"
    RUNNING = "running"
    CANCELLING = "cancelling"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class SubmissionDisposition(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class AgentEventType(StrEnum):
    RUN_CREATED = "run.created"
    DISPATCH_RESERVED = "dispatch.reserved"
    RUN_STARTED = "run.started"
    SUBMISSION_UNKNOWN = "submission.unknown"
    RUN_INTERRUPTED = "run.interrupted"
    MESSAGE = "message"
    TOOL_REQUESTED = "tool.requested"
    TOOL_COMPLETED = "tool.completed"
    APPROVAL_REQUIRED = "approval.required"
    ARTIFACT_CREATED = "artifact.created"
    COST = "cost"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_STOPPED = "run.stopped"


class RuntimeCapability(StrEnum):
    START_TASK = "run.start"
    SEND_MESSAGE = "run.message"
    STOP = "run.stop"
    STATUS = "run.status"
    EVENTS = "run.events"
    ATTACHMENTS = "run.attachments"
    APPROVAL_RESPONSE = "run.approval_response"


class AgentRuntimeError(RuntimeError):
    """A bounded runtime-neutral failure."""

    def __init__(self, code: str):
        if not _CAPABILITY.fullmatch(code):
            code = "runtime.error"
        super().__init__(code)
        self.code = code


def _require_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
        raise ValueError(f"{label} must be an opaque identifier")
    return value


def _require_task_id(value: str, label: str = "task id") -> str:
    if not isinstance(value, str) or not _TASK_ID.fullmatch(value):
        raise ValueError(f"{label} must be a task identifier")
    return value


def _require_runtime_type(value: str) -> str:
    if not isinstance(value, str) or not _RUNTIME_TYPE.fullmatch(value):
        raise ValueError("runtime_type is invalid")
    return value


def _bounded_text(value: str, label: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{label} is required")
    result = value.strip()
    if len(result) > maximum:
        raise ValueError(f"{label} is too long")
    return result


def _capabilities(values: Iterable[str | RuntimeCapability]) -> frozenset[str]:
    result = frozenset(str(value) for value in values)
    if any(not _CAPABILITY.fullmatch(value) for value in result):
        raise ValueError("runtime capability is invalid")
    return result


@dataclass(frozen=True)
class MentatAgent:
    id: str
    name: str
    runtime_type: str
    runtime_config_id: str | None = None
    capabilities: frozenset[str] = field(default_factory=frozenset)
    status: AgentStatus = AgentStatus.IDLE

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_id(self.id, "agent id"))
        object.__setattr__(self, "name", _bounded_text(self.name, "agent name", maximum=120))
        object.__setattr__(self, "runtime_type", _require_runtime_type(self.runtime_type))
        if self.runtime_config_id is not None:
            object.__setattr__(
                self,
                "runtime_config_id",
                _require_id(self.runtime_config_id, "runtime config id"),
            )
        object.__setattr__(self, "capabilities", _capabilities(self.capabilities))
        object.__setattr__(self, "status", AgentStatus(self.status))


@dataclass(frozen=True)
class MentatTask:
    id: str
    title: str
    objective: str
    status: TaskStatus = TaskStatus.QUEUED
    assigned_agent_id: str | None = None
    required_capabilities: tuple[str, ...] = ()
    acceptance_criteria: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_task_id(self.id))
        object.__setattr__(self, "title", _bounded_text(self.title, "task title", maximum=240))
        object.__setattr__(self, "objective", _bounded_text(self.objective, "task objective", maximum=20_000))
        object.__setattr__(self, "status", TaskStatus(self.status))
        if self.assigned_agent_id is not None:
            object.__setattr__(
                self,
                "assigned_agent_id",
                _require_id(self.assigned_agent_id, "assigned agent id"),
            )
        object.__setattr__(
            self,
            "required_capabilities",
            tuple(sorted(_capabilities(self.required_capabilities))),
        )
        criteria = tuple(
            _bounded_text(item, "acceptance criterion", maximum=1_000)
            for item in self.acceptance_criteria
        )
        object.__setattr__(self, "acceptance_criteria", criteria)


@dataclass(frozen=True)
class AgentRun:
    id: str
    task_id: str | None
    agent_id: str
    runtime_type: str
    status: RunStatus

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_id(self.id, "run id"))
        if self.task_id is not None:
            object.__setattr__(self, "task_id", _require_task_id(self.task_id))
        object.__setattr__(self, "agent_id", _require_id(self.agent_id, "agent id"))
        object.__setattr__(self, "runtime_type", _require_runtime_type(self.runtime_type))
        object.__setattr__(self, "status", RunStatus(self.status))


@dataclass(frozen=True)
class SubmissionOutcome:
    """Typed result of one and only one runtime submission attempt."""

    disposition: SubmissionDisposition
    run: AgentRun | None = None
    runtime_run_ref: str | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "disposition", SubmissionDisposition(self.disposition))
        if self.disposition == SubmissionDisposition.ACCEPTED and self.run is None:
            raise ValueError("accepted submission requires a run")
        if self.runtime_run_ref is not None:
            object.__setattr__(
                self,
                "runtime_run_ref",
                _require_id(self.runtime_run_ref, "runtime run reference"),
            )
        if self.failure_code is not None:
            if not isinstance(self.failure_code, str) or not _CAPABILITY.fullmatch(
                self.failure_code
            ):
                raise ValueError("submission failure code is invalid")
        if self.disposition == SubmissionDisposition.ACCEPTED and self.failure_code is not None:
            raise ValueError("accepted submission cannot include a failure code")


@dataclass(frozen=True)
class AgentEvent:
    id: str
    run_id: str
    sequence: int
    type: AgentEventType
    occurred_at: str
    summary: str
    content: str | None = None
    metrics: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_id(self.id, "event id"))
        object.__setattr__(self, "run_id", _require_id(self.run_id, "run id"))
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("event sequence must be a positive integer")
        object.__setattr__(self, "type", AgentEventType(self.type))
        timestamp = self.occurred_at
        if not isinstance(timestamp, str):
            raise ValueError("event timestamp is invalid")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("event timestamp is invalid") from exc
        if parsed.tzinfo is None:
            raise ValueError("event timestamp must include a timezone")
        object.__setattr__(self, "summary", _bounded_text(self.summary, "event summary", maximum=500))
        if self.content is not None:
            object.__setattr__(
                self,
                "content",
                _bounded_text(self.content, "event content", maximum=20_000),
            )
        allowed_metrics = {
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "context_tokens",
            "context_length",
        }
        normalized_metrics: dict[str, int] = {}
        for name, value in dict(self.metrics).items():
            if name not in allowed_metrics or type(value) is not int or not (0 <= value <= 10**9):
                raise ValueError("event metrics are invalid")
            normalized_metrics[name] = value
        object.__setattr__(self, "metrics", MappingProxyType(normalized_metrics))


@dataclass(frozen=True)
class RuntimeContext:
    """Private adapter context; runtime references are never domain IDs."""

    agent_id: str
    runtime_agent_ref: str
    task_id: str | None = None
    mentat_run_id: str | None = None
    dispatch_id: str | None = None
    runtime_run_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_id", _require_id(self.agent_id, "agent id"))
        object.__setattr__(
            self,
            "runtime_agent_ref",
            _require_id(self.runtime_agent_ref, "runtime agent reference"),
        )
        if self.task_id is not None:
            object.__setattr__(self, "task_id", _require_task_id(self.task_id))
        if self.mentat_run_id is not None:
            object.__setattr__(
                self,
                "mentat_run_id",
                _require_id(self.mentat_run_id, "Mentat run id"),
            )
        if self.dispatch_id is not None:
            object.__setattr__(
                self,
                "dispatch_id",
                _require_id(self.dispatch_id, "dispatch id"),
            )
        if self.runtime_run_ref is not None:
            object.__setattr__(
                self,
                "runtime_run_ref",
                _require_id(self.runtime_run_ref, "runtime run reference"),
            )


@runtime_checkable
class AgentRuntime(Protocol):
    runtime_type: str
    capabilities: frozenset[str]

    def submit_task(
        self, task: MentatTask, context: RuntimeContext
    ) -> SubmissionOutcome: ...

    def send_message(self, run_id: str, message: str) -> None: ...

    def stop(self, run_id: str, *, context: RuntimeContext | None = None) -> None: ...

    def get_status(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> AgentRun: ...

    def stream_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        *,
        context: RuntimeContext | None = None,
    ) -> Iterable[AgentEvent]: ...

    def capabilities_for_run(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> frozenset[str]: ...


class AgentRuntimeRegistry:
    """Small deterministic registry; it contains adapters, never credentials."""

    def __init__(self, runtimes: Iterable[AgentRuntime] = ()):
        self._runtimes: dict[str, AgentRuntime] = {}
        for runtime in runtimes:
            self.register(runtime)

    def register(self, runtime: AgentRuntime) -> None:
        runtime_type = _require_runtime_type(runtime.runtime_type)
        if runtime_type in self._runtimes:
            raise ValueError(f"runtime already registered: {runtime_type}")
        _capabilities(runtime.capabilities)
        self._runtimes[runtime_type] = runtime

    def require(self, runtime_type: str) -> AgentRuntime:
        normalized = _require_runtime_type(runtime_type)
        try:
            return self._runtimes[normalized]
        except KeyError as exc:
            raise AgentRuntimeError("runtime.unavailable") from exc

    def public_inventory(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(
            MappingProxyType(
                {
                    "runtime_type": name,
                    "capabilities": sorted(runtime.capabilities),
                }
            )
            for name, runtime in sorted(self._runtimes.items())
        )


__all__ = [
    "AgentEvent",
    "AgentEventType",
    "AgentRun",
    "AgentRuntime",
    "AgentRuntimeError",
    "AgentRuntimeRegistry",
    "AgentStatus",
    "MentatAgent",
    "MentatTask",
    "RunStatus",
    "SubmissionDisposition",
    "SubmissionOutcome",
    "RuntimeCapability",
    "RuntimeContext",
    "TaskStatus",
]
