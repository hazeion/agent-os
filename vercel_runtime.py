"""Runtime-neutral Vercel AI Gateway adapter."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import threading
from pathlib import Path
from typing import Callable, Iterable, Mapping

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
from vercel_connections import (
    VERCEL_CONNECTION_ID,
    VercelConnection,
    VercelConnectionError,
    credential_for_gateway,
    load_vercel_connection,
)
from vercel_infrastructure import (
    RequestFunction,
    VercelCapabilityResult,
    VercelHttpResponse,
    VercelInfrastructureError,
    fixed_https_request,
)


AI_GATEWAY_CHAT_COMPLETIONS_URL = "https://ai-gateway.vercel.sh/v1/chat/completions"
MAX_GATEWAY_RESPONSE_BYTES = 1024 * 1024
MAX_CACHED_OBSERVATIONS = 128
_SYSTEM_PROMPT = (
    "You are an Agent running one exact Mentat Task. Complete the objective, "
    "follow the acceptance criteria, and return a concise final result."
)


class VercelRuntime:
    """Perform one bounded synchronous generation per exact Task dispatch."""

    runtime_type = "vercel"
    capabilities = frozenset(
        {
            RuntimeCapability.START_TASK.value,
            RuntimeCapability.STATUS.value,
            RuntimeCapability.EVENTS.value,
            RuntimeCapability.MODEL_GENERATE.value,
        }
    )

    def __init__(
        self,
        data_dir: Path,
        *,
        requester: RequestFunction = fixed_https_request,
        environment: Mapping[str, str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.requester = requester
        self.environment = environment
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._observations: OrderedDict[
            str, tuple[AgentRun, tuple[AgentEvent, ...]]
        ] = OrderedDict()
        self._lock = threading.RLock()

    def _environment(self) -> Mapping[str, str]:
        if self.environment is not None:
            return self.environment
        import os

        return os.environ

    @staticmethod
    def _rejected(code: str) -> SubmissionOutcome:
        return SubmissionOutcome(
            SubmissionDisposition.REJECTED,
            failure_code=code,
        )

    @staticmethod
    def _unknown(code: str) -> SubmissionOutcome:
        return SubmissionOutcome(
            SubmissionDisposition.UNKNOWN,
            failure_code=code,
        )

    def _connection(self, context: RuntimeContext) -> VercelConnection:
        try:
            record = load_vercel_connection(self.data_dir)
        except VercelConnectionError as exc:
            raise AgentRuntimeError("vercel.connection_unavailable") from exc
        if (
            record is None
            or record.id != context.runtime_agent_ref
            or record.id != VERCEL_CONNECTION_ID
            or record.state != "configured"
        ):
            raise AgentRuntimeError("vercel.connection_not_ready")
        return record

    @staticmethod
    def _prompt(task: MentatTask) -> str:
        sections = [f"Task: {task.title}", f"Objective: {task.objective}"]
        if task.acceptance_criteria:
            sections.append(
                "Acceptance criteria:\n"
                + "\n".join(f"- {criterion}" for criterion in task.acceptance_criteria)
            )
        prompt = "\n\n".join(sections)
        if len(prompt) > 24_000:
            raise AgentRuntimeError("vercel.task_too_large")
        return prompt

    @staticmethod
    def _headers(credential: str) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "User-Agent": "mentat-vercel-runtime/1",
        }

    def _completion_request(
        self,
        record: VercelConnection,
        credential: str,
        *,
        prompt: str,
        maximum_tokens: int,
    ) -> VercelHttpResponse:
        return self.requester(
            "POST",
            AI_GATEWAY_CHAT_COMPLETIONS_URL,
            headers=self._headers(credential),
            json_body={
                "model": record.model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": maximum_tokens,
                "stream": False,
            },
            params=None,
            timeout=(5.0, 120.0),
            maximum_bytes=MAX_GATEWAY_RESPONSE_BYTES,
        )

    @staticmethod
    def _parse_completion(
        response: VercelHttpResponse,
    ) -> tuple[str, dict[str, int], str]:
        if not 200 <= response.status_code < 300:
            raise VercelInfrastructureError("vercel.gateway_response_failed")
        payload = response.json_object()
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise VercelInfrastructureError("vercel.gateway_response_invalid")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if (
            not isinstance(content, str)
            or not content.strip()
            or "\x00" in content
            or any(0xD800 <= ord(character) <= 0xDFFF for character in content)
            or len(content.strip()) > 20_000
        ):
            raise VercelInfrastructureError("vercel.gateway_response_invalid")
        usage: dict[str, int] = {}
        raw_usage = payload.get("usage")
        if raw_usage is not None:
            if not isinstance(raw_usage, dict):
                raise VercelInfrastructureError("vercel.gateway_response_invalid")
            mapping = {
                "prompt_tokens": "input_tokens",
                "completion_tokens": "output_tokens",
                "total_tokens": "total_tokens",
            }
            for source, target in mapping.items():
                value = raw_usage.get(source)
                if value is not None:
                    if type(value) is not int or not 0 <= value <= 10**9:
                        raise VercelInfrastructureError(
                            "vercel.gateway_response_invalid"
                        )
                    usage[target] = value
            if (
                {"input_tokens", "output_tokens", "total_tokens"} <= usage.keys()
                and usage["input_tokens"] + usage["output_tokens"]
                != usage["total_tokens"]
            ):
                raise VercelInfrastructureError("vercel.gateway_response_invalid")
        provider_id = payload.get("id")
        if (
            not isinstance(provider_id, str)
            or not 1 <= len(provider_id) <= 512
            or not provider_id.isascii()
            or provider_id.strip() != provider_id
            or any(
                ord(character) <= 32 or ord(character) == 127
                for character in provider_id
            )
        ):
            raise VercelInfrastructureError("vercel.gateway_response_invalid")
        return content.strip(), usage, provider_id

    @staticmethod
    def _definitive_rejection(status: int) -> bool:
        return 400 <= status < 500 and status not in {408, 409, 425, 429}

    def _submission_result(
        self,
        task: MentatTask,
        context: RuntimeContext,
    ) -> tuple[
        SubmissionOutcome,
        tuple[AgentRun, tuple[AgentEvent, ...]] | None,
    ]:
        """Contain every credential and raw provider response in one frame."""

        record: VercelConnection | None = None
        credential: str | None = None
        prompt: str | None = None
        response: VercelHttpResponse | None = None
        content: str | None = None
        provider_id: str | None = None
        run: AgentRun | None = None
        events: list[AgentEvent] | None = None
        outcome: SubmissionOutcome | None = None
        try:
            try:
                record = self._connection(context)
                credential = credential_for_gateway(record, self._environment())
                if credential is None:
                    return self._rejected("vercel.gateway_auth_required"), None
                prompt = self._prompt(task)
            except AgentRuntimeError as exc:
                return self._rejected(exc.code), None
            except Exception:
                return self._rejected("vercel.connection_unavailable"), None

            try:
                response = self._completion_request(
                    record,
                    credential,
                    prompt=prompt,
                    maximum_tokens=4096,
                )
            except Exception:
                return self._unknown("vercel.gateway_submission_unknown"), None

            try:
                status_code = response.status_code
                if type(status_code) is not int or not 100 <= status_code <= 599:
                    return self._unknown("vercel.gateway_response_unknown"), None
                if not 200 <= status_code < 300:
                    return (
                        self._rejected("vercel.gateway_rejected")
                        if self._definitive_rejection(status_code)
                        else self._unknown("vercel.gateway_submission_unknown")
                    ), None

                content, usage, provider_id = self._parse_completion(response)
                run = AgentRun(
                    id=context.mentat_run_id,
                    task_id=task.id,
                    agent_id=context.agent_id,
                    runtime_type=self.runtime_type,
                    status=RunStatus.COMPLETED,
                )
                occurred_at = (
                    self.clock()
                    .astimezone(timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                events = [
                    AgentEvent(
                        id="vercel_message_"
                        + hashlib.sha256(
                            (context.mentat_run_id + ":message").encode("utf-8")
                        ).hexdigest()[:24],
                        run_id=context.mentat_run_id,
                        sequence=1,
                        type=AgentEventType.MESSAGE,
                        occurred_at=occurred_at,
                        summary="Vercel AI Gateway returned a response",
                        content=content,
                    )
                ]
                if usage:
                    events.append(
                        AgentEvent(
                            id="vercel_usage_"
                            + hashlib.sha256(
                                (context.mentat_run_id + ":usage").encode(
                                    "utf-8"
                                )
                            ).hexdigest()[:24],
                            run_id=context.mentat_run_id,
                            sequence=2,
                            type=AgentEventType.COST,
                            occurred_at=occurred_at,
                            summary="Vercel AI Gateway reported token usage",
                            metrics=usage,
                        )
                    )
                runtime_reference = "vercel_" + hashlib.sha256(
                    (context.mentat_run_id + ":" + provider_id).encode("utf-8")
                ).hexdigest()[:32]
                outcome = SubmissionOutcome(
                    SubmissionDisposition.ACCEPTED,
                    run=run,
                    runtime_run_ref=runtime_reference,
                    initial_events=tuple(events),
                )
                return outcome, (run, tuple(events))
            except Exception:
                return self._unknown("vercel.gateway_response_unknown"), None
        finally:
            # If an injected dependency retains a caught exception object, its
            # traceback frame still contains only scrubbed references.
            self = None  # type: ignore[assignment]
            record = None
            credential = None
            prompt = None
            response = None
            content = None
            provider_id = None
            run = None
            events = None
            outcome = None

    def submit_task(
        self,
        task: MentatTask,
        context: RuntimeContext,
    ) -> SubmissionOutcome:
        if (
            context.mentat_run_id is None
            or context.task_id != task.id
            or context.agent_id != task.assigned_agent_id
        ):
            return self._rejected("vercel.context_invalid")
        try:
            outcome, observation = self._submission_result(task, context)
        except Exception:
            return self._unknown("vercel.gateway_response_unknown")
        if observation is None:
            return outcome
        run, events = observation
        try:
            with self._lock:
                self._observations[run.id] = (run, events)
                self._observations.move_to_end(run.id)
                while len(self._observations) > MAX_CACHED_OBSERVATIONS:
                    self._observations.popitem(last=False)
        except Exception:
            # The provider call completed, so a local observation failure is
            # unknown and must never cause an automatic resubmission.
            return self._unknown("vercel.gateway_response_unknown")
        return outcome

    def test_readiness(self) -> VercelCapabilityResult:
        result: VercelCapabilityResult | None = None
        failure_code: str | None = None
        try:
            context = RuntimeContext(
                agent_id="agent_vercel_readiness",
                runtime_agent_ref=VERCEL_CONNECTION_ID,
                mentat_run_id="run_vercel_readiness",
            )
            record = self._connection(context)
            credential = credential_for_gateway(record, self._environment())
            if credential is None:
                failure_code = "vercel.gateway_auth_required"
            else:
                response = self._completion_request(
                    record,
                    credential,
                    prompt="Reply with READY.",
                    maximum_tokens=8,
                )
                self._parse_completion(response)
                result = VercelCapabilityResult(
                    capability="ai.gateway",
                    status="ready",
                )
        except (AgentRuntimeError, VercelInfrastructureError) as exc:
            failure_code = exc.code
        except Exception:
            failure_code = "vercel.gateway_response_unknown"
        # Do not let an escaping exception retain this runtime's environment,
        # credential, request headers, or provider response through frame locals.
        self = None  # type: ignore[assignment]
        context = None
        record = None
        credential = None
        response = None
        if failure_code is not None:
            raise VercelInfrastructureError(failure_code)
        if result is None:
            raise VercelInfrastructureError("vercel.gateway_response_unknown")
        return result

    def _observation(self, run_id: str) -> tuple[AgentRun, tuple[AgentEvent, ...]]:
        with self._lock:
            try:
                value = self._observations[run_id]
            except KeyError as exc:
                raise AgentRuntimeError("vercel.run_unavailable") from exc
            self._observations.move_to_end(run_id)
            return value

    def get_status(
        self,
        run_id: str,
        *,
        context: RuntimeContext | None = None,
    ) -> AgentRun:
        run, _events = self._observation(run_id)
        if context is not None and (
            context.mentat_run_id not in {None, run.id}
            or context.agent_id != run.agent_id
            or context.task_id not in {None, run.task_id}
            or context.runtime_agent_ref != VERCEL_CONNECTION_ID
        ):
            raise AgentRuntimeError("vercel.context_invalid")
        return run

    def stream_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        *,
        context: RuntimeContext | None = None,
    ) -> Iterable[AgentEvent]:
        self.get_status(run_id, context=context)
        _run, events = self._observation(run_id)
        return tuple(event for event in events if event.sequence > after_sequence)

    def capabilities_for_run(
        self,
        run_id: str,
        *,
        context: RuntimeContext | None = None,
    ) -> frozenset[str]:
        self.get_status(run_id, context=context)
        return self.capabilities

    def send_message(
        self,
        run_id: str,
        message: str,
        *,
        context: RuntimeContext | None = None,
    ) -> None:
        raise AgentRuntimeError("runtime.capability_unavailable")

    def pending_action(
        self,
        run_id: str,
        *,
        context: RuntimeContext | None = None,
    ) -> PendingRunAction:
        raise AgentRuntimeError("runtime.capability_unavailable")

    def respond_to_action(
        self,
        run_id: str,
        action: PendingRunAction,
        response: RunActionResponse,
        *,
        context: RuntimeContext | None = None,
    ) -> None:
        raise AgentRuntimeError("runtime.capability_unavailable")

    def stop(
        self,
        run_id: str,
        *,
        context: RuntimeContext | None = None,
    ) -> None:
        raise AgentRuntimeError("runtime.capability_unavailable")


__all__ = [
    "AI_GATEWAY_CHAT_COMPLETIONS_URL",
    "MAX_GATEWAY_RESPONSE_BYTES",
    "VercelRuntime",
]
