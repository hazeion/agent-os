"""Hermes adapter for Mentat's runtime-neutral orchestration boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from agent_runtime import (
    AgentEvent,
    AgentEventType,
    AgentRun,
    AgentRuntimeError,
    MentatTask,
    RunStatus,
    RuntimeCapability,
    RuntimeContext,
    SubmissionDisposition,
    SubmissionOutcome,
)
from agent_run_history import bounded_excerpt, normalize_usage


LegacyResponse = tuple[dict[str, Any], int]


@dataclass(frozen=True)
class HermesCompatibilityHandlers:
    start: Callable[[dict[str, Any]], LegacyResponse]
    start_task: Callable[[MentatTask, RuntimeContext], LegacyResponse]
    message: Callable[[str, dict[str, Any]], LegacyResponse]
    response: Callable[[str, dict[str, Any]], LegacyResponse]
    stop: Callable[[str], LegacyResponse]
    status: Callable[[str, str | None], LegacyResponse]


_RUN_STATUS = {
    "queued": RunStatus.STARTING,
    "starting": RunStatus.STARTING,
    "running": RunStatus.RUNNING,
    "cancelling": RunStatus.RUNNING,
    "waiting_for_approval": RunStatus.WAITING,
    "waiting_for_clarification": RunStatus.WAITING,
    "completed": RunStatus.COMPLETED,
    "failed": RunStatus.FAILED,
    "interrupted": RunStatus.FAILED,
    "cancelled": RunStatus.STOPPED,
    "stopped": RunStatus.STOPPED,
}

_EVENT_TYPES = {
    "queued": AgentEventType.RUN_STARTED,
    "run.started": AgentEventType.RUN_STARTED,
    "message": AgentEventType.MESSAGE,
    "assistant.message": AgentEventType.MESSAGE,
    "tool.requested": AgentEventType.TOOL_REQUESTED,
    "tool.started": AgentEventType.TOOL_REQUESTED,
    "tool.completed": AgentEventType.TOOL_COMPLETED,
    "tool.finished": AgentEventType.TOOL_COMPLETED,
    "approval": AgentEventType.APPROVAL_REQUIRED,
    "approval.required": AgentEventType.APPROVAL_REQUIRED,
    "clarification": AgentEventType.APPROVAL_REQUIRED,
    "clarification.required": AgentEventType.APPROVAL_REQUIRED,
    "artifact": AgentEventType.ARTIFACT_CREATED,
    "artifact.created": AgentEventType.ARTIFACT_CREATED,
    "cost": AgentEventType.COST,
    "usage": AgentEventType.COST,
}

_TERMINAL_EVENT_TYPES = {
    ("complete", RunStatus.COMPLETED): AgentEventType.RUN_COMPLETED,
    ("completed", RunStatus.COMPLETED): AgentEventType.RUN_COMPLETED,
    ("run.completed", RunStatus.COMPLETED): AgentEventType.RUN_COMPLETED,
    ("error", RunStatus.FAILED): AgentEventType.RUN_FAILED,
    ("failed", RunStatus.FAILED): AgentEventType.RUN_FAILED,
    ("run.failed", RunStatus.FAILED): AgentEventType.RUN_FAILED,
    ("cancelled", RunStatus.STOPPED): AgentEventType.RUN_STOPPED,
    ("stopped", RunStatus.STOPPED): AgentEventType.RUN_STOPPED,
    ("run.stopped", RunStatus.STOPPED): AgentEventType.RUN_STOPPED,
}

_EVENT_SUMMARIES = {
    AgentEventType.RUN_CREATED: "Run created",
    AgentEventType.DISPATCH_RESERVED: "Dispatch reserved",
    AgentEventType.RUN_STARTED: "Run started",
    AgentEventType.SUBMISSION_UNKNOWN: "Submission outcome unknown",
    AgentEventType.RUN_INTERRUPTED: "Run interrupted",
    AgentEventType.MESSAGE: "Run updated",
    AgentEventType.TOOL_REQUESTED: "Tool requested",
    AgentEventType.TOOL_COMPLETED: "Tool completed",
    AgentEventType.APPROVAL_REQUIRED: "Operator input required",
    AgentEventType.ARTIFACT_CREATED: "Artifact created",
    AgentEventType.COST: "Usage updated",
    AgentEventType.RUN_COMPLETED: "Run completed",
    AgentEventType.RUN_FAILED: "Run failed",
    AgentEventType.RUN_STOPPED: "Run stopped",
}


def normalize_hermes_run(
    snapshot: Mapping[str, Any],
    *,
    agent_id: str,
    task_id: str | None,
) -> AgentRun:
    """Project a legacy Console snapshot without exporting Hermes references."""

    status = _RUN_STATUS.get(str(snapshot.get("status") or ""))
    if status is None:
        raise AgentRuntimeError("runtime.status_invalid")
    return AgentRun(
        id=str(snapshot.get("id") or ""),
        task_id=task_id,
        agent_id=agent_id,
        runtime_type="hermes",
        status=status,
    )


def normalize_hermes_event(
    event: Mapping[str, Any],
    *,
    run_status: RunStatus | None = None,
) -> AgentEvent:
    """Reduce one Console event to bounded Mentat vocabulary and display text."""

    raw_type = str(event.get("type") or event.get("kind") or "")
    event_type = _TERMINAL_EVENT_TYPES.get(
        (raw_type, run_status),
        _EVENT_TYPES.get(raw_type, AgentEventType.MESSAGE),
    )
    return AgentEvent(
        id=str(event.get("id") or ""),
        run_id=str(event.get("run_id") or ""),
        sequence=event.get("sequence") if type(event.get("sequence")) is int else -1,
        type=event_type,
        occurred_at=str(event.get("timestamp") or ""),
        summary=_EVENT_SUMMARIES[event_type],
    )


class HermesRuntime:
    """First runtime adapter; mature execution remains in the Python bridge."""

    runtime_type = "hermes"

    def __init__(
        self,
        *,
        transport_factory: Callable[[], Any],
        compatibility_handlers: HermesCompatibilityHandlers | None = None,
    ):
        self._transport_factory = transport_factory
        self._compatibility_handlers = compatibility_handlers

    @property
    def capabilities(self) -> frozenset[str]:
        capabilities: set[str] = set()
        if self._compatibility_handlers is not None:
            capabilities.add(RuntimeCapability.START_TASK.value)
        return frozenset(capabilities)

    def bind_compatibility_handlers(self, handlers: HermesCompatibilityHandlers) -> None:
        if self._compatibility_handlers is not None:
            raise RuntimeError("Hermes compatibility handlers are already bound")
        self._compatibility_handlers = handlers

    def console_transport(self) -> Any:
        return self._transport_factory()

    def _handlers(self) -> HermesCompatibilityHandlers:
        if self._compatibility_handlers is None:
            raise AgentRuntimeError("runtime.unavailable")
        return self._compatibility_handlers

    # Runtime-neutral methods are deliberately fail-closed until durable Mentat
    # Task/Agent records invoke them.  Compatibility routes below preserve the
    # current Console semantics during this first strangler slice.
    @staticmethod
    def _validate_task_context(task: MentatTask, context: RuntimeContext) -> None:
        if context.task_id != task.id:
            raise AgentRuntimeError("runtime.task_binding_invalid")
        if (
            task.assigned_agent_id is not None
            and task.assigned_agent_id != context.agent_id
        ):
            raise AgentRuntimeError("runtime.agent_binding_invalid")

    def submit_task(
        self, task: MentatTask, context: RuntimeContext
    ) -> SubmissionOutcome:
        self._validate_task_context(task, context)
        if context.mentat_run_id is None or context.dispatch_id is None:
            raise AgentRuntimeError("runtime.identity_context_required")
        body, status = self._handlers().start_task(task, context)
        if 400 <= status < 500:
            return SubmissionOutcome(
                SubmissionDisposition.REJECTED,
                failure_code="runtime.start_rejected",
            )
        if status != 202 or not isinstance(body.get("run"), Mapping):
            return SubmissionOutcome(
                SubmissionDisposition.UNKNOWN,
                failure_code="runtime.start_unverified",
            )
        run = normalize_hermes_run(
            body["run"],
            agent_id=context.agent_id,
            task_id=task.id,
        )
        if run.id != context.mentat_run_id:
            return SubmissionOutcome(
                SubmissionDisposition.UNKNOWN,
                failure_code="runtime.identity_mismatch",
            )
        return SubmissionOutcome(SubmissionDisposition.ACCEPTED, run=run)

    def start_task(self, task: MentatTask, context: RuntimeContext) -> AgentRun:
        """Compatibility helper; new orchestration callers use ``submit_task``."""
        self._validate_task_context(task, context)
        body, status = self._handlers().start_task(task, context)
        if status != 202 or not isinstance(body.get("run"), Mapping):
            raise AgentRuntimeError("runtime.start_failed")
        return normalize_hermes_run(
            body["run"],
            agent_id=context.agent_id,
            task_id=task.id,
        )

    def send_message(
        self, run_id: str, message: str, *, context: RuntimeContext | None = None
    ) -> None:
        if not isinstance(message, str) or not message.strip() or "\x00" in message:
            raise AgentRuntimeError("runtime.message_invalid")
        snapshot = self._bound_snapshot(run_id, context=context)
        controls = snapshot.get("controls") if isinstance(snapshot, Mapping) else None
        steer = controls.get("steer") if isinstance(controls, Mapping) else None
        runtime_agent_ref = snapshot.get("agent_id") if isinstance(snapshot, Mapping) else None
        revision = steer.get("revision") if isinstance(steer, Mapping) else None
        if (
            not isinstance(steer, Mapping)
            or steer.get("available") is not True
            or type(revision) is not int
            or not isinstance(runtime_agent_ref, str)
        ):
            raise AgentRuntimeError("runtime.message_unavailable")
        response, response_status = self._handlers().message(
            run_id,
            {
                "text": message.strip(),
                "control_revision": revision,
                "agent_id": runtime_agent_ref,
            },
        )
        if response_status != 200 or response.get("ok") is not True:
            raise AgentRuntimeError("runtime.message_failed")

    def stop(self, run_id: str, *, context: RuntimeContext | None = None) -> None:
        self._bound_snapshot(run_id, context=context)
        body, status = self._handlers().stop(run_id)
        if status not in {200, 202} or body.get("ok") is not True:
            raise AgentRuntimeError("runtime.stop_failed")

    def get_status(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> AgentRun:
        if context is not None and run_id not in {
            context.mentat_run_id,
            context.runtime_run_ref,
        }:
            raise AgentRuntimeError("runtime.identity_context_invalid")
        snapshot = self._bound_snapshot(run_id, context=context)
        return normalize_hermes_run(
            snapshot,
            agent_id=str(snapshot["mentat_agent_id"]),
            task_id=str(snapshot["task_id"]),
        )

    def _bound_snapshot(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> Mapping[str, Any]:
        if context is not None:
            expected_run_ref = context.runtime_run_ref or context.mentat_run_id
            if (
                expected_run_ref is None
                or context.mentat_run_id is None
                or run_id != expected_run_ref
            ):
                raise AgentRuntimeError("runtime.identity_context_invalid")
        body, status = self._handlers().status(run_id, None)
        snapshot = body.get("run") if status == 200 else None
        if not isinstance(snapshot, Mapping):
            raise AgentRuntimeError("runtime.status_failed")
        agent_id = snapshot.get("mentat_agent_id")
        task_id = snapshot.get("task_id")
        if not isinstance(agent_id, str) or not isinstance(task_id, str):
            raise AgentRuntimeError("runtime.identity_context_required")
        if context is not None:
            if (
                agent_id != context.agent_id
                or task_id != context.task_id
                or snapshot.get("id") != context.mentat_run_id
            ):
                raise AgentRuntimeError("runtime.identity_context_invalid")
        return snapshot

    def stream_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        *,
        context: RuntimeContext | None = None,
    ) -> Iterable[AgentEvent]:
        if context is not None and run_id not in {
            context.mentat_run_id,
            context.runtime_run_ref,
        }:
            raise AgentRuntimeError("runtime.identity_context_invalid")
        if type(after_sequence) is not int or after_sequence < 0:
            raise AgentRuntimeError("runtime.cursor_invalid")
        legacy_cursor = after_sequence // 4
        body, status = self._handlers().status(run_id, str(legacy_cursor))
        if status != 200:
            raise AgentRuntimeError("runtime.status_failed")
        events = body.get("events")
        if not isinstance(events, list):
            raise AgentRuntimeError("runtime.events_invalid")
        if body.get("cursor_reset_required") is True:
            raise AgentRuntimeError("runtime.event_continuity_lost")
        snapshot = body.get("run")
        if not isinstance(snapshot, Mapping):
            raise AgentRuntimeError("runtime.status_failed")
        if not isinstance(snapshot.get("mentat_agent_id"), str) or not isinstance(
            snapshot.get("task_id"), str
        ):
            raise AgentRuntimeError("runtime.identity_context_required")
        normalized_status = None
        normalized_status = _RUN_STATUS.get(str(snapshot.get("status") or ""))
        retained = [item for item in events if isinstance(item, Mapping)]
        terminal_index = None
        terminal_kinds = {"runtime.finalized"}
        for index, item in enumerate(retained):
            if str(item.get("type") or item.get("kind") or "") in terminal_kinds:
                terminal_index = index
        projected: list[AgentEvent] = []
        for index, item in enumerate(retained):
            base = normalize_hermes_event(
                item,
                run_status=normalized_status if index == terminal_index else None,
            )
            sequence = base.sequence * 4
            if index == terminal_index and normalized_status == RunStatus.COMPLETED:
                response = snapshot.get("response") if isinstance(snapshot, Mapping) else None
                if isinstance(response, str) and response.strip():
                    content = bounded_excerpt(response, 20_000)[0]
                    if content:
                        projected.append(
                            AgentEvent(
                                id=f"{base.id}:message",
                                run_id=base.run_id,
                                sequence=sequence - 2,
                                type=AgentEventType.MESSAGE,
                                occurred_at=base.occurred_at,
                                summary="Assistant message",
                                content=content,
                            )
                        )
            if index == terminal_index and isinstance(snapshot, Mapping):
                usage = normalize_usage(snapshot.get("usage"))
                if usage:
                    projected.append(
                        AgentEvent(
                            id=f"{base.id}:cost",
                            run_id=base.run_id,
                            sequence=sequence - 1,
                            type=AgentEventType.COST,
                            occurred_at=base.occurred_at,
                            summary="Usage updated",
                            metrics=usage,
                        )
                    )
            if index == terminal_index and normalized_status in {
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.STOPPED,
            }:
                terminal_type = {
                    RunStatus.COMPLETED: AgentEventType.RUN_COMPLETED,
                    RunStatus.FAILED: AgentEventType.RUN_FAILED,
                    RunStatus.STOPPED: AgentEventType.RUN_STOPPED,
                }[normalized_status]
                base = replace(
                    base,
                    type=terminal_type,
                    summary=_EVENT_SUMMARIES[terminal_type],
                )
            projected.append(replace(base, sequence=sequence))
        return tuple(event for event in projected if event.sequence > after_sequence)

    def capabilities_for_run(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> frozenset[str]:
        snapshot = self._bound_snapshot(run_id, context=context)
        capabilities = {
            RuntimeCapability.STATUS.value,
            RuntimeCapability.EVENTS.value,
        }
        if str(snapshot.get("status") or "") in {
            "queued",
            "running",
            "waiting_for_approval",
            "waiting_for_clarification",
        }:
            capabilities.add(RuntimeCapability.STOP.value)
        controls = snapshot.get("controls")
        steer = controls.get("steer") if isinstance(controls, Mapping) else None
        if isinstance(steer, Mapping) and steer.get("available") is True:
            capabilities.add(RuntimeCapability.SEND_MESSAGE.value)
        return frozenset(capabilities)

    # Compatibility methods return the exact legacy response.  New callers use
    # the runtime-neutral methods above and never receive these dictionaries.
    def start_compatibility(self, payload: dict[str, Any]) -> LegacyResponse:
        return self._handlers().start(payload)

    def message_compatibility(self, run_id: str, payload: dict[str, Any]) -> LegacyResponse:
        return self._handlers().message(run_id, payload)

    def response_compatibility(self, run_id: str, payload: dict[str, Any]) -> LegacyResponse:
        return self._handlers().response(run_id, payload)

    def stop_compatibility(self, run_id: str) -> LegacyResponse:
        return self._handlers().stop(run_id)

    def status_compatibility(self, run_id: str, after_cursor: str | None = None) -> LegacyResponse:
        return self._handlers().status(run_id, after_cursor)


__all__ = [
    "HermesCompatibilityHandlers",
    "HermesRuntime",
    "normalize_hermes_event",
    "normalize_hermes_run",
]
