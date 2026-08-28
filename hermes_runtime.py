"""Hermes adapter for Mentat's runtime-neutral orchestration boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import Any

from agent_runtime import (
    AgentEvent,
    AgentEventType,
    AgentRun,
    AgentRuntimeError,
    MentatTask,
    PendingRunAction,
    RunActionResponse,
    RunStatus,
    RuntimeCapability,
    RuntimeContext,
    SubmissionDisposition,
    SubmissionOutcome,
)
from agent_run_history import bounded_excerpt, bounded_public_excerpt, normalize_usage


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
        submission_lock: Any | None = None,
    ):
        self._transport_factory = transport_factory
        self._compatibility_handlers = compatibility_handlers
        self._submission_lock = submission_lock

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

    def submission_guard(self):
        """Serialize reservation-through-launch with Hermes configuration changes."""

        return self._submission_lock if self._submission_lock is not None else nullcontext()

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
        snapshot = body["run"]
        run = normalize_hermes_run(
            snapshot,
            agent_id=context.agent_id,
            task_id=task.id,
        )
        if run.id != context.mentat_run_id:
            return SubmissionOutcome(
                SubmissionDisposition.UNKNOWN,
                failure_code="runtime.identity_mismatch",
            )
        provider = snapshot.get("provider")
        model = snapshot.get("model")
        execution_identity = None
        if (
            isinstance(provider, str)
            and provider
            and provider.strip() == provider
            and len(provider) <= 160
            and "\x00" not in provider
            and isinstance(model, str)
            and model
            and model.strip() == model
            and len(model) <= 160
            and "\x00" not in model
        ):
            execution_identity = {
                "model": model,
                "provider": provider,
                "reasoning_effort": None,
                "verification": "runtime_launch_snapshot",
            }
        return SubmissionOutcome(
            SubmissionDisposition.ACCEPTED,
            run=run,
            execution_identity=execution_identity,
        )

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
        if response_status == 502 and response.get("partial") is True:
            raise AgentRuntimeError("runtime.message_partial")
        if response_status != 200 or response.get("ok") is not True:
            raise AgentRuntimeError("runtime.message_failed")

    @staticmethod
    def _pending_action_from_snapshot(snapshot: Mapping[str, Any]) -> PendingRunAction:
        status = str(snapshot.get("status") or "")
        action = snapshot.get("action_required")
        if status not in {"waiting_for_approval", "waiting_for_clarification"} or not isinstance(action, Mapping):
            raise AgentRuntimeError("runtime.action_unavailable")
        kind = action.get("kind")
        request_id = action.get("request_id")
        if not isinstance(kind, str) or not isinstance(request_id, str):
            raise AgentRuntimeError("runtime.action_invalid")
        if (status == "waiting_for_approval") != (kind == "approval"):
            raise AgentRuntimeError("runtime.action_invalid")
        if (status == "waiting_for_clarification") != (kind == "clarification"):
            raise AgentRuntimeError("runtime.action_invalid")
        try:
            if kind == "approval":
                raw_choices = action.get("choices")
                if not isinstance(raw_choices, list):
                    raise ValueError("approval choices are invalid")
                labels = {"once": "Allow once", "deny": "Deny"}
                choices = tuple(
                    (choice, labels[choice])
                    for choice in raw_choices
                    if isinstance(choice, str) and choice in labels
                )
                if len(choices) != len(raw_choices):
                    raise ValueError("approval choices are invalid")
                preview = action.get("preview") if isinstance(action.get("preview"), Mapping) else {}
                return PendingRunAction(
                    kind="approval",
                    request_id=request_id,
                    title=preview.get("title") if isinstance(preview.get("title"), str) else None,
                    summary=preview.get("summary") if isinstance(preview.get("summary"), str) else None,
                    choices=choices,
                )
            if kind == "clarification":
                prompt = action.get("prompt")
                if not isinstance(prompt, Mapping):
                    raise ValueError("clarification prompt is invalid")
                prompt_type = prompt.get("type")
                question = prompt.get("question")
                if not isinstance(prompt_type, str) or not isinstance(question, str):
                    raise ValueError("clarification prompt is invalid")
                raw_choices = prompt.get("choices", [])
                if not isinstance(raw_choices, list):
                    raise ValueError("clarification choices are invalid")
                choices = tuple(
                    (item.get("id"), item.get("label"))
                    for item in raw_choices
                    if isinstance(item, Mapping)
                    and isinstance(item.get("id"), str)
                    and isinstance(item.get("label"), str)
                )
                if len(choices) != len(raw_choices):
                    raise ValueError("clarification choices are invalid")
                return PendingRunAction(
                    kind="clarification",
                    request_id=request_id,
                    prompt_type=prompt_type,
                    question=question,
                    choices=choices,
                )
            raise ValueError("pending action kind is invalid")
        except ValueError as exc:
            raise AgentRuntimeError("runtime.action_invalid") from exc

    def pending_action(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> PendingRunAction:
        return self._pending_action_from_snapshot(self._bound_snapshot(run_id, context=context))

    def respond_to_action(
        self,
        run_id: str,
        action: PendingRunAction,
        response: RunActionResponse,
        *,
        context: RuntimeContext | None = None,
    ) -> None:
        current = self.pending_action(run_id, context=context)
        if current != action or response.kind != current.kind:
            raise AgentRuntimeError("runtime.action_stale")
        if current.kind == "approval":
            if response.choice_id not in {choice_id for choice_id, _label in current.choices}:
                raise AgentRuntimeError("runtime.action_invalid")
            payload = {
                "confirmed": True,
                "kind": "approval",
                "request_id": current.request_id,
                "choice": response.choice_id,
            }
        elif current.prompt_type == "choice":
            if response.choice_id not in {choice_id for choice_id, _label in current.choices}:
                raise AgentRuntimeError("runtime.action_invalid")
            payload = {
                "confirmed": True,
                "kind": "clarification",
                "request_id": current.request_id,
                "response": {"type": "choice", "choice_id": response.choice_id},
            }
        elif current.prompt_type == "text" and response.text is not None:
            payload = {
                "confirmed": True,
                "kind": "clarification",
                "request_id": current.request_id,
                "response": {"type": "text", "text": response.text},
            }
        else:
            raise AgentRuntimeError("runtime.action_invalid")
        body, status = self._handlers().response(run_id, payload)
        if status != 200 or body.get("ok") is not True:
            raise AgentRuntimeError("runtime.action_failed")

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
        snapshot = body.get("run")
        if not isinstance(snapshot, Mapping):
            raise AgentRuntimeError("runtime.status_failed")
        snapshot_id = snapshot.get("id")
        snapshot_agent_id = snapshot.get("mentat_agent_id")
        snapshot_task_id = snapshot.get("task_id")
        expected_snapshot_id = context.mentat_run_id if context is not None else run_id
        if (
            not isinstance(snapshot_agent_id, str)
            or not isinstance(snapshot_task_id, str)
        ):
            raise AgentRuntimeError("runtime.identity_context_required")
        if snapshot_id != expected_snapshot_id:
            raise AgentRuntimeError("runtime.identity_context_invalid")
        if context is not None and (
            snapshot_agent_id != context.agent_id
            or snapshot_task_id != context.task_id
        ):
            raise AgentRuntimeError("runtime.identity_context_invalid")
        normalized_status = None
        normalized_status = _RUN_STATUS.get(str(snapshot.get("status") or ""))
        retained = [item for item in events if isinstance(item, Mapping)]
        if any(item.get("run_id") != expected_snapshot_id for item in retained):
            raise AgentRuntimeError("runtime.identity_context_invalid")
        if body.get("cursor_reset_required") is True:
            # A preallocated Console Run reserves source cursor 1 for its
            # durable dispatch event.  The first compatibility event is the
            # exact binding marker at cursor 2.  Accept only that one
            # identity-bound, fully contiguous initial gap; retention or any
            # other discontinuity remains fail closed.
            sequences = [
                item.get("sequence")
                if type(item.get("sequence")) is int
                else item.get("cursor")
                for item in retained
            ]
            first = retained[0] if retained else None
            first_data = first.get("data") if isinstance(first, Mapping) else None
            expected_initial_gap = (
                after_sequence == 0
                and context is not None
                and sequences == list(range(2, 2 + len(sequences)))
                and isinstance(first, Mapping)
                and str(first.get("type") or first.get("kind") or "")
                == "runtime.bound"
                and isinstance(first_data, Mapping)
                and first_data.get("mentat_agent_id") == context.agent_id
                and first_data.get("task_id") == context.task_id
            )
            if not expected_initial_gap:
                raise AgentRuntimeError("runtime.event_continuity_lost")
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
                    content = bounded_public_excerpt(response, 20_000)[0]
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
        try:
            self._pending_action_from_snapshot(snapshot)
        except AgentRuntimeError:
            pass
        else:
            capabilities.add(RuntimeCapability.APPROVAL_RESPONSE.value)
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
