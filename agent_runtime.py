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
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable


_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,159}\Z")
_RUNTIME_TYPE = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_CAPABILITY = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
_VERCEL_MESSAGE_EVENT_ID = re.compile(r"vercel_message_[0-9a-f]{24}\Z")
_VERCEL_COST_EVENT_ID = re.compile(r"vercel_usage_[0-9a-f]{24}\Z")
_CANONICAL_EVENT_BYTES = 32_768


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
    RESUME = "run.resume"
    MODEL_GENERATE = "model.generate"


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
    if (
        not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
        or any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    ):
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
class PendingRunAction:
    """One runtime-neutral approval or clarification awaiting an operator."""

    kind: str
    request_id: str
    title: str | None = None
    summary: str | None = None
    prompt_type: str | None = None
    question: str | None = None
    choices: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in {"approval", "clarification"}:
            raise ValueError("pending action kind is invalid")
        object.__setattr__(self, "request_id", _require_id(self.request_id, "request id"))
        for name, maximum in (("title", 240), ("summary", 2_000), ("question", 2_000)):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _bounded_text(value, name, maximum=maximum))
        if self.kind == "approval":
            if self.prompt_type is not None or self.question is not None:
                raise ValueError("approval action prompt is invalid")
        elif self.prompt_type not in {"choice", "text"} or self.question is None:
            raise ValueError("clarification action prompt is invalid")
        choices: list[tuple[str, str]] = []
        for item in self.choices:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("pending action choices are invalid")
            choice_id, label = item
            choices.append((_require_id(choice_id, "choice id"), _bounded_text(label, "choice label", maximum=240)))
        if len(choices) > 16 or len({choice_id for choice_id, _label in choices}) != len(choices):
            raise ValueError("pending action choices are invalid")
        if self.kind == "approval":
            if not choices or {choice_id for choice_id, _label in choices} - {"once", "deny"}:
                raise ValueError("approval choices are invalid")
        if self.kind == "clarification" and self.prompt_type == "choice" and not choices:
            raise ValueError("clarification choices are required")
        if self.kind == "clarification" and self.prompt_type == "text" and choices:
            raise ValueError("text clarification choices are invalid")
        object.__setattr__(self, "choices", tuple(choices))


@dataclass(frozen=True)
class RunActionResponse:
    """A normalized answer to one pending runtime action."""

    kind: str
    choice_id: str | None = None
    text: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"approval", "clarification"}:
            raise ValueError("response kind is invalid")
        if self.choice_id is not None:
            object.__setattr__(self, "choice_id", _require_id(self.choice_id, "choice id"))
        if self.text is not None:
            object.__setattr__(self, "text", _bounded_text(self.text, "response text", maximum=2_000))
        if (self.choice_id is None) == (self.text is None):
            raise ValueError("response must contain exactly one value")
        if self.kind == "approval" and self.choice_id not in {"once", "deny"}:
            raise ValueError("approval response is invalid")


@dataclass(frozen=True)
class SubmissionOutcome:
    """Typed result of one and only one runtime submission attempt."""

    disposition: SubmissionDisposition
    run: AgentRun | None = None
    runtime_run_ref: str | None = None
    failure_code: str | None = None
    initial_events: tuple[AgentEvent, ...] = ()
    execution_identity: Mapping[str, str | None] | None = None

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
        identity = self.execution_identity
        if identity is not None:
            if self.disposition == SubmissionDisposition.REJECTED:
                raise ValueError("rejected submission cannot include execution identity")
            if not isinstance(identity, Mapping) or set(identity) != {
                "model",
                "provider",
                "reasoning_effort",
                "verification",
            }:
                raise ValueError("submission execution identity is invalid")
            normalized_identity: dict[str, str | None] = {}
            for name, maximum in (("model", 160), ("provider", 160)):
                value = identity[name]
                if not isinstance(value, str):
                    raise ValueError("submission execution identity is invalid")
                normalized_identity[name] = _bounded_text(
                    value,
                    f"execution {name}",
                    maximum=maximum,
                )
            effort = identity["reasoning_effort"]
            if effort is not None:
                if not isinstance(effort, str):
                    raise ValueError("submission execution identity is invalid")
                effort = _bounded_text(
                    effort,
                    "execution reasoning effort",
                    maximum=64,
                )
            verification = identity["verification"]
            if verification not in {"runtime_response", "runtime_launch_snapshot"}:
                raise ValueError("submission execution identity is invalid")
            normalized_identity["reasoning_effort"] = effort
            normalized_identity["verification"] = str(verification)
            object.__setattr__(
                self,
                "execution_identity",
                MappingProxyType(normalized_identity),
            )
        events = tuple(self.initial_events)
        if events and self.disposition != SubmissionDisposition.ACCEPTED:
            raise ValueError("only accepted submissions can include initial events")
        if len(events) > 16:
            raise ValueError("too many initial submission events")
        if events:
            if self.run is None:
                raise ValueError("initial submission events require a run")
            if [event.sequence for event in events] != list(range(1, len(events) + 1)):
                raise ValueError("initial submission event sequence is invalid")
            if len({event.id for event in events}) != len(events):
                raise ValueError("initial submission events must be unique")
            if any(
                event.run_id != self.run.id
                or event.type not in {AgentEventType.MESSAGE, AgentEventType.COST}
                for event in events
            ):
                raise ValueError("initial submission event is invalid")
            for event in events:
                _validate_initial_event_storage(self.run, event)
        if (
            self.disposition == SubmissionDisposition.ACCEPTED
            and self.run is not None
            and self.run.runtime_type == "vercel"
        ):
            message_events = [
                event for event in events if event.type == AgentEventType.MESSAGE
            ]
            cost_events = [
                event for event in events if event.type == AgentEventType.COST
            ]
            expected_message_id = "vercel_message_" + hashlib.sha256(
                (self.run.id + ":message").encode("utf-8")
            ).hexdigest()[:24]
            expected_cost_id = "vercel_usage_" + hashlib.sha256(
                (self.run.id + ":usage").encode("utf-8")
            ).hexdigest()[:24]
            if (
                len(message_events) != 1
                or len(cost_events) > 1
                or len(events) != len(message_events) + len(cost_events)
                or events[0] is not message_events[0]
                or not _VERCEL_MESSAGE_EVENT_ID.fullmatch(message_events[0].id)
                or message_events[0].id != expected_message_id
                or (
                    cost_events
                    and (
                        events[-1] is not cost_events[0]
                        or not _VERCEL_COST_EVENT_ID.fullmatch(cost_events[0].id)
                        or cost_events[0].id != expected_cost_id
                    )
                )
            ):
                raise ValueError("Vercel submission events are invalid")
        object.__setattr__(self, "initial_events", events)


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


def canonical_event_storage_fields(
    event: AgentEvent,
) -> tuple[str, str | None, str, str]:
    """Return the exact redacted fields used by durable event persistence."""

    # Import lazily so the runtime-neutral domain module does not create an
    # import cycle while the legacy history compatibility module initializes.
    from agent_run_history import bounded_excerpt

    summary = bounded_excerpt(event.summary, 500)[0]
    content = (
        bounded_excerpt(event.content, 20_000)[0]
        if event.content is not None
        else None
    )
    metrics_json = json.dumps(
        dict(event.metrics),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return summary, content, metrics_json, "{}"


def _validate_initial_event_storage(run: AgentRun, event: AgentEvent) -> None:
    """Keep accepted events within both exact SQLite canonical envelopes."""

    summary, content, metrics_json, data_json = canonical_event_storage_fields(
        event
    )
    common = {
        "run_id": event.run_id,
        "event_type": event.type.value,
        "source_type": event.type.value,
        "occurred_at": event.occurred_at,
        "summary": summary,
        "content": content,
        "metrics_json": metrics_json,
        "data_json": data_json,
    }
    envelopes = (
        {
            **common,
            "id": event.id,
            "sequence": event.sequence,
            "source_key": event.id,
        },
        {
            **common,
            "id": "event_"
            + hashlib.sha256(
                (run.id + ":" + event.id).encode("utf-8")
            ).hexdigest()[:24],
            # Task dispatch reserves sequence 1 and records acceptance at 2.
            "sequence": event.sequence + 2,
            "source_key": f"submission:{event.id}",
        },
    )
    for envelope in envelopes:
        encoded = json.dumps(
            envelope,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
        if len(encoded) > _CANONICAL_EVENT_BYTES:
            raise ValueError("initial submission event exceeds durable storage")


@dataclass(frozen=True)
class RuntimeCapacity:
    """One private adapter-owned admission scope and its bounded ceiling."""

    scope: str
    limit: int

    def __post_init__(self) -> None:
        scope = self.scope
        if (
            not isinstance(scope, str)
            or not scope
            or scope.strip() != scope
            or "\x00" in scope
            or len(scope.encode("utf-8")) > 512
        ):
            raise ValueError("runtime capacity scope is invalid")
        if type(self.limit) is not int or not 1 <= self.limit <= 32:
            raise ValueError("runtime capacity limit is invalid")


@dataclass(frozen=True)
class RuntimeContext:
    """Private adapter context; runtime references are never domain IDs."""

    agent_id: str
    runtime_agent_ref: str
    task_id: str | None = None
    mentat_run_id: str | None = None
    dispatch_id: str | None = None
    runtime_run_ref: str | None = None
    continuation_runtime_run_ref: str | None = None

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
        if self.continuation_runtime_run_ref is not None:
            object.__setattr__(
                self,
                "continuation_runtime_run_ref",
                _require_id(
                    self.continuation_runtime_run_ref,
                    "runtime continuation reference",
                ),
            )


@runtime_checkable
class AgentRuntime(Protocol):
    runtime_type: str
    capabilities: frozenset[str]

    def capacity_for_binding(self, runtime_agent_ref: str) -> RuntimeCapacity: ...

    def submit_task(
        self, task: MentatTask, context: RuntimeContext
    ) -> SubmissionOutcome: ...

    def send_message(
        self, run_id: str, message: str, *, context: RuntimeContext | None = None
    ) -> None: ...

    def pending_action(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> PendingRunAction: ...

    def respond_to_action(
        self,
        run_id: str,
        action: PendingRunAction,
        response: RunActionResponse,
        *,
        context: RuntimeContext | None = None,
    ) -> None: ...

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
        # Process-backed adapters may need a live probe before they can
        # truthfully advertise capabilities. Registration validates their
        # closed, static vocabulary without forcing that process to start.
        registration_capabilities = getattr(
            runtime, "registration_capabilities", None
        )
        _capabilities(
            runtime.capabilities
            if registration_capabilities is None
            else registration_capabilities
        )
        self._runtimes[runtime_type] = runtime

    def require(self, runtime_type: str) -> AgentRuntime:
        normalized = _require_runtime_type(runtime_type)
        try:
            return self._runtimes[normalized]
        except KeyError as exc:
            raise AgentRuntimeError("runtime.unavailable") from exc

    @property
    def runtime_types(self) -> tuple[str, ...]:
        """Return registered type names without probing live adapters."""

        return tuple(sorted(self._runtimes))

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
    "RuntimeCapacity",
    "RuntimeContext",
    "TaskStatus",
]
