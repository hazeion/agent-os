"""Runtime-neutral Task dispatch over Mentat's durable orchestration store."""

from __future__ import annotations

from contextlib import ExitStack, nullcontext
from dataclasses import dataclass, replace
from itertools import islice
from pathlib import Path
import hashlib
import re
import sqlite3
from typing import Callable
from uuid import uuid4

from agent_registry import (
    AgentRegistry,
    AgentRegistryError,
    CanonicalAgentRecord,
    RuntimeBinding,
)
from agent_runtime import (
    AgentEventType,
    AgentRuntime,
    AgentRuntimeError,
    AgentRuntimeRegistry,
    MentatAgent,
    MentatTask,
    RuntimeCapability,
    RuntimeCapacity,
    RuntimeContext,
    RunStatus,
    SubmissionDisposition,
    SubmissionOutcome,
    TaskStatus,
)
from mentat_db import MentatDatabaseError, connect
from private_state import private_state_lock
from conversation_repository import (
    ConversationMessageRecord,
    ConversationRecord,
    ConversationRepository,
    ConversationRepositoryError,
    ConversationTurnRecord,
)
from conversation_attachments import (
    ConversationAttachmentError,
    run_input_context,
    staged_context_evidence,
)
from run_repository import (
    ConversationDispatchReservation,
    ConversationRunAdmission,
    ConversationRunAttemptResult,
    ConversationSubmissionResult,
    DispatchReservation,
    RunRecord,
    RunRepository,
    RunRepositoryConflict,
    RunRepositoryError,
    declared_runtime_capacity_evidence,
    default_runtime_capacity_evidence,
    runtime_binding_digest,
)
from task_repository import TaskRepository, TaskRepositoryError
from task_planning import task_is_deferred, workflow_stage
from codex_task_creation import CodexTaskCreationService


class OrchestrationServiceError(RuntimeError):
    """A bounded dispatch failure that does not expose private adapter state."""

    def __init__(self, code: str, *, run: RunRecord | None = None):
        super().__init__(code)
        self.code = code
        self.run = run


@dataclass(frozen=True)
class DispatchResult:
    run: RunRecord
    duplicate: bool
    disposition: str


@dataclass(frozen=True)
class ConversationTurnDispatchResult:
    conversation: ConversationRecord
    message: ConversationMessageRecord
    turn: ConversationTurnRecord
    run: RunRecord | ConversationSubmissionResult | None
    duplicate: bool
    disposition: str


@dataclass(frozen=True)
class ConversationQueueMutationResult:
    conversation: ConversationRecord
    message: ConversationMessageRecord
    turn: ConversationTurnRecord
    disposition: str


@dataclass(frozen=True)
class ConversationRunActionResult:
    attempt: ConversationRunAttemptResult
    duplicate: bool


@dataclass(frozen=True)
class ReconciliationReport:
    leased: int
    reconciled: tuple[str, ...]
    unavailable: tuple[str, ...]


_TASK_STATUS = {
    "todo": TaskStatus.QUEUED,
    "in progress": TaskStatus.RUNNING,
    "waiting": TaskStatus.BLOCKED,
    "needs attention": TaskStatus.BLOCKED,
    "completed": TaskStatus.COMPLETED,
}

_TERMINAL_EVENT_STATUS = {
    AgentEventType.RUN_COMPLETED: RunStatus.COMPLETED,
    AgentEventType.RUN_FAILED: RunStatus.FAILED,
    AgentEventType.RUN_STOPPED: RunStatus.STOPPED,
    AgentEventType.RUN_INTERRUPTED: RunStatus.INTERRUPTED,
}
_TERMINAL_RUN_STATUSES = frozenset(_TERMINAL_EVENT_STATUS.values())


def _cohere_runtime_observation(
    observed,
    events,
    *,
    has_more_events: bool,
):
    """Bind a split status/event read to one exact terminal observation."""

    terminal_events = tuple(
        event for event in events if event.type in _TERMINAL_EVENT_STATUS
    )
    if not terminal_events:
        return observed
    if (
        len(terminal_events) != 1
        or has_more_events
        or terminal_events[0].sequence
        != max(event.sequence for event in events)
    ):
        raise OrchestrationServiceError("reconcile.terminal_event_conflict")
    terminal_status = _TERMINAL_EVENT_STATUS[terminal_events[0].type]
    if (
        observed.status in _TERMINAL_RUN_STATUSES
        and observed.status != terminal_status
    ):
        raise OrchestrationServiceError("reconcile.terminal_event_conflict")
    return (
        observed
        if observed.status == terminal_status
        else replace(observed, status=terminal_status)
    )


class OrchestrationService:
    """Commit durable intent, invoke one adapter once, then record its outcome."""

    def __init__(
        self,
        data_dir: Path,
        *,
        runtime_registry: AgentRuntimeRegistry,
        agent_registry: AgentRegistry | None = None,
        id_factory: Callable[[str], str] | None = None,
        conversation_continuation_handler: Callable[[str, str], None] | None = None,
        conversation_context_validator: Callable[[dict[str, str], tuple[str, ...]], bool] | None = None,
        conversation_context_guard: object | None = None,
        conversation_attachment_preparer: Callable[[str, tuple[str, ...]], None] | None = None,
        conversation_attachment_cleanup: Callable[[str], None] | None = None,
        task_creation_service: CodexTaskCreationService | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.runtime_registry = runtime_registry
        self.agent_registry = agent_registry or AgentRegistry(
            self.data_dir,
            supported_runtime_types=runtime_registry.runtime_types,
        )
        self.id_factory = id_factory or (
            lambda prefix: f"{prefix}_{uuid4().hex}"
        )
        self.conversation_continuation_handler = conversation_continuation_handler
        self.conversation_context_validator = conversation_context_validator
        self.conversation_context_guard = conversation_context_guard
        self.conversation_attachment_preparer = conversation_attachment_preparer
        self.conversation_attachment_cleanup = conversation_attachment_cleanup
        self.task_creation_service = task_creation_service or CodexTaskCreationService(self.data_dir)

    def _conversation_context_is_current(
        self,
        binding: dict[str, str],
        source_digests: tuple[str, ...],
    ) -> bool:
        if self.conversation_context_validator is None:
            return False
        try:
            return bool(self.conversation_context_validator(binding, source_digests))
        except Exception:
            return False

    @staticmethod
    def _runtime_supports_attachments(
        runtime: AgentRuntime,
        binding: RuntimeBinding,
    ) -> bool:
        supports_attachments = getattr(runtime, "supports_attachments", None)
        try:
            return bool(
                callable(supports_attachments)
                and supports_attachments(binding.runtime_agent_ref)
            )
        except Exception:
            return False

    def _connect(self):
        try:
            return connect(self.data_dir)
        except (MentatDatabaseError, sqlite3.Error) as exc:
            raise OrchestrationServiceError("dispatch.unavailable") from exc

    @staticmethod
    def _dispatch_error_code(code: str) -> str:
        return {
            "task_repository.not_found": "dispatch.task_not_found",
            "task.id.invalid": "dispatch.task_id_invalid",
            "run.identifier_invalid": "dispatch.task_id_invalid",
        }.get(code, code)

    def _agent_and_binding(self, agent_id: str) -> tuple[MentatAgent, RuntimeBinding]:
        agents = self.agent_registry.list_agents()
        agent = next((item for item in agents if item.id == agent_id), None)
        if agent is None:
            raise OrchestrationServiceError("dispatch.agent_not_found")
        binding = self.agent_registry.get_runtime_binding(agent_id)
        if agent.runtime_config_id != binding.id or agent.runtime_type != binding.runtime_type:
            raise OrchestrationServiceError("dispatch.binding_invalid")
        return agent, binding

    def _agent_record_and_binding(
        self,
        agent_id: str,
    ) -> tuple[CanonicalAgentRecord, RuntimeBinding]:
        record = next(
            (
                item
                for item in self.agent_registry.list_agent_records()
                if item.agent.id == agent_id
            ),
            None,
        )
        if record is None:
            raise OrchestrationServiceError("conversation.agent_not_found")
        binding = self.agent_registry.get_runtime_binding(agent_id)
        if (
            record.agent.runtime_config_id != binding.id
            or record.agent.runtime_type != binding.runtime_type
        ):
            raise OrchestrationServiceError("conversation.binding_invalid")
        return record, binding

    @staticmethod
    def _task_contract(document: dict, revision: int) -> MentatTask:
        assigned_agent_id = document.get("assigned_agent_id")
        if not isinstance(assigned_agent_id, str) or not assigned_agent_id:
            raise OrchestrationServiceError("dispatch.agent_required")
        required = document.get("required_capabilities", ())
        criteria = document.get("acceptance_criteria", ())
        if not isinstance(required, (list, tuple)) or not isinstance(criteria, (list, tuple)):
            raise OrchestrationServiceError("dispatch.task_invalid")
        objective = str(document.get("description") or document.get("title") or "").strip()
        try:
            return MentatTask(
                id=str(document.get("id") or ""),
                title=str(document.get("title") or ""),
                objective=objective,
                status=_TASK_STATUS.get(str(document.get("status") or ""), TaskStatus.QUEUED),
                assigned_agent_id=assigned_agent_id,
                required_capabilities=tuple(str(value) for value in required),
                acceptance_criteria=tuple(str(value) for value in criteria),
            )
        except (TypeError, ValueError) as exc:
            raise OrchestrationServiceError("dispatch.task_invalid") from exc

    @staticmethod
    def _binding_digest(agent: MentatAgent, binding: RuntimeBinding) -> str:
        return runtime_binding_digest(
            agent_id=agent.id,
            runtime_type=binding.runtime_type,
            runtime_config_id=binding.id,
            runtime_agent_ref=binding.runtime_agent_ref,
            capabilities=agent.capabilities,
        )

    @staticmethod
    def _capacity_evidence(
        runtime: AgentRuntime,
        binding: RuntimeBinding,
        binding_digest: str,
    ) -> tuple[str, int]:
        """Reduce an optional adapter declaration to private durable evidence."""

        declaration_method = getattr(runtime, "capacity_for_binding", None)
        if callable(declaration_method):
            try:
                declaration = declaration_method(binding.runtime_agent_ref)
                if not isinstance(declaration, RuntimeCapacity):
                    raise ValueError("runtime capacity declaration is invalid")
                if (
                    binding.runtime_type != "codex"
                    or binding.runtime_agent_ref != "default"
                    or declaration.limit > 2
                    or re.fullmatch(
                        r"codex-app-server:[0-9a-f]{64}", declaration.scope
                    )
                    is None
                ):
                    raise ValueError("runtime capacity declaration is unqualified")
                return declared_runtime_capacity_evidence(
                    runtime_type=binding.runtime_type,
                    private_scope=declaration.scope,
                    limit=declaration.limit,
                )
            except Exception:
                # Missing, invalid, or unavailable declarations deliberately
                # collapse to one private binding-scoped slot.
                pass
        return default_runtime_capacity_evidence(
            runtime_type=binding.runtime_type,
            binding_digest=binding_digest,
        )

    def _conversation_admission(
        self,
        *,
        record: CanonicalAgentRecord,
        binding: RuntimeBinding,
        runtime: AgentRuntime,
        binding_digest: str,
        run_id: str,
        predecessor_run_id: str | None = None,
    ) -> ConversationRunAdmission:
        capacity_scope_digest, capacity_limit = self._capacity_evidence(
            runtime,
            binding,
            binding_digest,
        )
        return ConversationRunAdmission(
            run_id=run_id,
            agent_id=record.agent.id,
            agent_name=record.agent.name,
            agent_revision=record.revision,
            runtime_type=binding.runtime_type,
            runtime_config_id=binding.id,
            runtime_config_revision=binding.revision,
            runtime_binding_digest=binding_digest,
            capabilities=tuple(sorted(record.agent.capabilities)),
            capacity_scope_digest=capacity_scope_digest,
            capacity_limit=capacity_limit,
            predecessor_run_id=predecessor_run_id,
        )

    @staticmethod
    def _require_capabilities(
        task: MentatTask,
        agent: MentatAgent,
        runtime_capabilities: frozenset[str],
    ) -> None:
        if RuntimeCapability.START_TASK.value not in runtime_capabilities:
            raise OrchestrationServiceError("dispatch.runtime_capability_missing")
        if not frozenset(task.required_capabilities).issubset(agent.capabilities):
            raise OrchestrationServiceError("dispatch.agent_capability_missing")
        if not frozenset(task.required_capabilities).issubset(runtime_capabilities):
            raise OrchestrationServiceError("dispatch.runtime_capability_missing")

    @staticmethod
    def _require_planning_execution_eligibility(document: dict) -> None:
        """Keep PT-3A execution scoped to an operator-owned planned Task."""

        try:
            nested = document.get("delegation")
            eligible = (
                document.get("source") == "dashboard"
                and workflow_stage(document) == "planned"
                and not task_is_deferred(document)
                and nested is None
            )
        except Exception as exc:
            raise OrchestrationServiceError("dispatch.task_unavailable") from exc
        if not eligible:
            raise OrchestrationServiceError("dispatch.task_unavailable")

    def _reserve(
        self,
        *,
        task_id: str,
        expected_revision: int,
        idempotency_key: str,
        planning_execution: bool = False,
    ) -> tuple[
        DispatchReservation,
        MentatTask | None,
        MentatAgent | None,
        RuntimeBinding | None,
        AgentRuntime | None,
    ]:
        try:
            with private_state_lock(self.data_dir):
                connection = self._connect()
                try:
                    repository = RunRepository(connection)
                    retry = repository.lookup_dispatch_retry(
                        idempotency_key=idempotency_key,
                        task_id=task_id,
                        task_revision=expected_revision,
                    )
                    if retry is not None:
                        return retry, None, None, None, None
                    snapshot = TaskRepository(connection).get(task_id)
                    if snapshot.revision != expected_revision:
                        raise OrchestrationServiceError("dispatch.task_changed")
                    task = self._task_contract(snapshot.document, snapshot.revision)
                    if planning_execution:
                        self._require_planning_execution_eligibility(snapshot.document)
                    agent, binding = self._agent_and_binding(
                        task.assigned_agent_id or ""
                    )
                    try:
                        runtime = self.runtime_registry.require(binding.runtime_type)
                    except AgentRuntimeError as exc:
                        raise OrchestrationServiceError(exc.code) from exc
                    digest = self._binding_digest(agent, binding)
                finally:
                    connection.close()

            # Adapter-owned capability and capacity discovery are external to
            # SQLite and the process-wide private-state lock. Their evidence
            # is accepted only after the exact Task and binding snapshots are
            # revalidated below.
            runtime_capabilities = frozenset(runtime.capabilities)
            self._require_capabilities(task, agent, runtime_capabilities)
            capacity_scope_digest, capacity_limit = self._capacity_evidence(
                runtime, binding, digest
            )

            with private_state_lock(self.data_dir):
                connection = self._connect()
                try:
                    repository = RunRepository(connection)
                    retry = repository.lookup_dispatch_retry(
                        idempotency_key=idempotency_key,
                        task_id=task_id,
                        task_revision=expected_revision,
                    )
                    if retry is not None:
                        return retry, None, None, None, None
                    current_snapshot = TaskRepository(connection).get(task_id)
                    if (
                        current_snapshot.revision != snapshot.revision
                        or current_snapshot.document != snapshot.document
                    ):
                        raise OrchestrationServiceError("dispatch.task_changed")
                    current_task = self._task_contract(
                        current_snapshot.document,
                        current_snapshot.revision,
                    )
                    if planning_execution:
                        self._require_planning_execution_eligibility(
                            current_snapshot.document
                        )
                    current_agent, current_binding = self._agent_and_binding(
                        current_task.assigned_agent_id or ""
                    )
                    try:
                        current_runtime = self.runtime_registry.require(
                            current_binding.runtime_type
                        )
                    except AgentRuntimeError as exc:
                        raise OrchestrationServiceError(exc.code) from exc
                    current_digest = self._binding_digest(
                        current_agent, current_binding
                    )
                    if (
                        current_task != task
                        or current_agent != agent
                        or current_binding != binding
                        or current_runtime is not runtime
                        or current_digest != digest
                    ):
                        raise OrchestrationServiceError("dispatch.binding_changed")
                    self._require_capabilities(
                        current_task,
                        current_agent,
                        runtime_capabilities,
                    )
                    reservation = repository.reserve_dispatch(
                        idempotency_key=idempotency_key,
                        dispatch_id=self.id_factory("dispatch"),
                        run_id=self.id_factory("run"),
                        task=current_snapshot.document,
                        task_revision=current_snapshot.revision,
                        agent_id=current_agent.id,
                        runtime_type=current_binding.runtime_type,
                        runtime_config_id=current_binding.id,
                        binding_digest=current_digest,
                        capabilities=current_agent.capabilities,
                        capacity_scope_digest=capacity_scope_digest,
                        capacity_limit=capacity_limit,
                        planning_execution=planning_execution,
                    )
                    return (
                        reservation,
                        current_task,
                        current_agent,
                        current_binding,
                        current_runtime,
                    )
                finally:
                    connection.close()
        except OrchestrationServiceError:
            raise
        except (TaskRepositoryError, AgentRegistryError, RunRepositoryError) as exc:
            code = self._dispatch_error_code(
                getattr(exc, "code", "dispatch.unavailable")
            )
            raise OrchestrationServiceError(code) from exc

    def _claim_after_binding_revalidation(
        self,
        reservation: DispatchReservation,
        expected_agent: MentatAgent,
        expected_binding: RuntimeBinding,
    ) -> tuple[RuntimeBinding, bool]:
        with private_state_lock(self.data_dir):
            try:
                current_agent, current_binding = self._agent_and_binding(expected_agent.id)
                current_digest = self._binding_digest(current_agent, current_binding)
            except (AgentRegistryError, OrchestrationServiceError) as exc:
                connection = self._connect()
                try:
                    run = RunRepository(connection).reject_reserved_dispatch(
                        dispatch_id=reservation.dispatch_id,
                        failure_code="dispatch.binding_unavailable",
                    )
                finally:
                    connection.close()
                raise OrchestrationServiceError("dispatch.binding_unavailable", run=run) from exc
            if (
                current_digest != reservation.runtime_binding_digest
                or current_agent != expected_agent
                or current_binding != expected_binding
            ):
                connection = self._connect()
                try:
                    run = RunRepository(connection).reject_reserved_dispatch(
                        dispatch_id=reservation.dispatch_id,
                        failure_code="dispatch.binding_changed",
                    )
                finally:
                    connection.close()
                raise OrchestrationServiceError("dispatch.binding_changed", run=run)
            connection = self._connect()
            try:
                repository = RunRepository(connection)
                task_creation_enabled = RuntimeCapability.TASK_CREATE.value in current_agent.capabilities
                if task_creation_enabled and (
                    current_binding.runtime_type != "codex"
                    or current_binding.runtime_agent_ref != "default"
                ):
                    run = repository.reject_reserved_dispatch(
                        dispatch_id=reservation.dispatch_id,
                        failure_code="dispatch.task_creation_unavailable",
                    )
                    raise OrchestrationServiceError(
                        "dispatch.task_creation_unavailable", run=run
                    )
                grant_preparer = None
                if task_creation_enabled:
                    snapshot = TaskRepository(connection).get(reservation.task_id)
                    project_id = snapshot.document.get("project_id")
                    if not isinstance(project_id, str):
                        run = repository.reject_reserved_dispatch(
                            dispatch_id=reservation.dispatch_id,
                            failure_code="dispatch.task_creation_unavailable",
                        )
                        raise OrchestrationServiceError(
                            "dispatch.task_creation_unavailable", run=run
                        )

                    def grant_preparer(claimed: DispatchReservation) -> bool:
                        return self.task_creation_service.preauthorize_claimed(
                            connection=connection,
                            run_id=claimed.run_id,
                            task_id=claimed.task_id,
                            task_revision=claimed.task_revision,
                            project_id=project_id,
                            agent_id=current_agent.id,
                            runtime_binding_digest=current_digest,
                        )

                try:
                    repository.claim_dispatch_attempt(
                        dispatch_id=reservation.dispatch_id,
                        expected_binding_digest=current_digest,
                        grant_preparer=grant_preparer,
                    )
                except RunRepositoryConflict as exc:
                    if exc.code in {"dispatch.task_changed", "dispatch.task_creation_unavailable"}:
                        run = repository.reject_reserved_dispatch(
                            dispatch_id=reservation.dispatch_id,
                            failure_code=exc.code,
                        )
                        raise OrchestrationServiceError(exc.code, run=run) from exc
                    raise OrchestrationServiceError(exc.code) from exc
                except RunRepositoryError as exc:
                    raise OrchestrationServiceError(
                        self._dispatch_error_code(exc.code)
                    ) from exc
            finally:
                connection.close()
            return current_binding, task_creation_enabled

    def _record_outcome(
        self,
        reservation: DispatchReservation,
        outcome: SubmissionOutcome,
        *,
        task: MentatTask,
        agent: MentatAgent,
        runtime: AgentRuntime,
    ) -> tuple[RunRecord, SubmissionOutcome]:
        if (
            outcome.disposition == SubmissionDisposition.ACCEPTED
            and (
                outcome.run is None
                or outcome.run.id != reservation.run_id
                or outcome.run.task_id != task.id
                or outcome.run.agent_id != agent.id
                or outcome.run.runtime_type != runtime.runtime_type
            )
        ):
            outcome = SubmissionOutcome(
                SubmissionDisposition.UNKNOWN,
                failure_code="runtime.identity_mismatch",
            )
        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                repository = RunRepository(connection)
                persistence_failed = False
                try:
                    recorded = repository.record_submission_outcome(
                        dispatch_id=reservation.dispatch_id,
                        outcome=outcome,
                    )
                except Exception:
                    persistence_failed = True
                    recorded = None
                if not persistence_failed and recorded is not None:
                    return recorded, outcome
                if outcome.disposition != SubmissionDisposition.ACCEPTED:
                    raise OrchestrationServiceError(
                        "dispatch.outcome_persistence_failed"
                    )
                # The runtime may have accepted work even though its normalized
                # evidence could not be persisted. Never leave the durable Run
                # in `submitting`, and never retry the provider request.
                fallback = SubmissionOutcome(
                    SubmissionDisposition.UNKNOWN,
                    failure_code="runtime.outcome_persistence_unknown",
                )
                try:
                    recorded = repository.record_submission_outcome(
                        dispatch_id=reservation.dispatch_id,
                        outcome=fallback,
                    )
                except Exception as exc:
                    raise OrchestrationServiceError(
                        "dispatch.outcome_persistence_failed"
                    ) from exc
                return recorded, fallback
            finally:
                connection.close()

    def dispatch_task(
        self,
        *,
        task_id: str,
        expected_revision: int,
        idempotency_key: str,
        planning_execution: bool = False,
    ) -> DispatchResult:
        """Dispatch one exact Task revision with at most one adapter invocation."""

        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                repository = RunRepository(connection)
                try:
                    retry = repository.lookup_dispatch_retry(
                        idempotency_key=idempotency_key,
                        task_id=task_id,
                        task_revision=expected_revision,
                    )
                except RunRepositoryError as exc:
                    raise OrchestrationServiceError(
                        self._dispatch_error_code(exc.code)
                    ) from exc
                if retry is not None:
                    try:
                        run = repository.get_run(retry.run_id)
                    except RunRepositoryConflict as exc:
                        raise OrchestrationServiceError(
                            "dispatch.idempotency_expired"
                        ) from exc
                    return DispatchResult(run, True, retry.state)
            finally:
                connection.close()

        if type(planning_execution) is not bool:
            raise OrchestrationServiceError("dispatch.task_invalid")
        reservation, task, agent, binding, runtime = self._reserve(
            task_id=task_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            planning_execution=planning_execution,
        )
        if reservation.duplicate:
            with private_state_lock(self.data_dir):
                connection = self._connect()
                try:
                    try:
                        run = RunRepository(connection).get_run(reservation.run_id)
                    except RunRepositoryConflict as exc:
                        raise OrchestrationServiceError("dispatch.idempotency_expired") from exc
                finally:
                    connection.close()
            return DispatchResult(run, True, reservation.state)

        if any(value is None for value in (task, agent, binding, runtime)):
            raise OrchestrationServiceError("dispatch.unavailable")

        current_binding, task_creation_enabled = self._claim_after_binding_revalidation(
            reservation, agent, binding
        )
        context = RuntimeContext(
            agent_id=agent.id,
            runtime_agent_ref=current_binding.runtime_agent_ref,
            task_id=task.id,
            mentat_run_id=reservation.run_id,
            dispatch_id=reservation.dispatch_id,
            task_creation_enabled=task_creation_enabled,
        )
        try:
            outcome = runtime.submit_task(task, context)
            if not isinstance(outcome, SubmissionOutcome):
                outcome = SubmissionOutcome(
                    SubmissionDisposition.UNKNOWN,
                    failure_code="runtime.submission_invalid",
                )
        except Exception:
            # The attempt was durably claimed before the adapter call. Even a
            # seemingly local exception may follow external acceptance, so it
            # is always unknown and must never trigger automatic resubmission.
            outcome = SubmissionOutcome(
                SubmissionDisposition.UNKNOWN,
                failure_code="runtime.submission_unknown",
            )
        run, recorded_outcome = self._record_outcome(
            reservation,
            outcome,
            task=task,
            agent=agent,
            runtime=runtime,
        )
        return DispatchResult(run, False, recorded_outcome.disposition.value)

    def _conversation_retry(
        self,
        *,
        conversation_id: str,
        text: str,
        idempotency_key: str,
    ) -> tuple[
        str,
        ConversationDispatchReservation | None,
        dict[str, object] | None,
    ]:
        if (
            not isinstance(conversation_id, str)
            or re.fullmatch(
                r"conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}",
                conversation_id,
            )
            is None
        ):
            raise OrchestrationServiceError("conversation.id_invalid")
        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                repository = RunRepository(connection)
                conversation = connection.execute(
                    "SELECT agent_id FROM mentat_conversations WHERE id = ?",
                    (conversation_id,),
                ).fetchone()
                if conversation is None:
                    raise OrchestrationServiceError("conversation.not_found")
                agent_id = str(conversation["agent_id"])
                context = staged_context_evidence(
                    connection,
                    conversation_id,
                )
                retry = repository.lookup_conversation_turn_retry(
                    idempotency_key=idempotency_key,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    text=text,
                    context_digest=(
                        None if context is None else str(context["context_digest"])
                    ),
                )
                return agent_id, retry, context
            except OrchestrationServiceError:
                raise
            except RunRepositoryError as exc:
                raise OrchestrationServiceError(exc.code) from exc
            finally:
                connection.close()

    def _conversation_result(
        self,
        reservation: ConversationDispatchReservation,
        *,
        duplicate: bool,
        disposition: str | None = None,
    ) -> ConversationTurnDispatchResult:
        repository = ConversationRepository(
            self.data_dir,
            supported_runtime_types=self.runtime_registry.runtime_types,
        )
        try:
            conversation = repository.read(reservation.conversation_id).conversation
            message = repository.read_message(reservation.message_id)
            turn = repository.read_turn(reservation.turn_id)
        except ConversationRepositoryError as exc:
            raise OrchestrationServiceError("conversation.unavailable") from exc
        run: RunRecord | ConversationSubmissionResult | None = None
        run_compacted = False
        if reservation.run_id is not None:
            with private_state_lock(self.data_dir):
                connection = self._connect()
                try:
                    run_repository = RunRepository(connection)
                    try:
                        run = run_repository.get_run(reservation.run_id)
                    except RunRepositoryConflict as exc:
                        if exc.code != "run.not_found":
                            raise
                        run = run_repository.get_conversation_submission_result(
                            reservation.turn_id
                        )
                        run_compacted = True
                        if run.id != reservation.run_id:
                            raise RunRepositoryError("run_repository.corrupt")
                except RunRepositoryError as exc:
                    raise OrchestrationServiceError("conversation.unavailable") from exc
                finally:
                    connection.close()
        if run_compacted and run is not None:
            message = replace(message, run_id=run.id)
            turn = replace(turn, latest_run_id=run.id)
        return ConversationTurnDispatchResult(
            conversation=conversation,
            message=message,
            turn=turn,
            run=run,
            duplicate=duplicate,
            disposition=disposition or reservation.state,
        )

    @staticmethod
    def _conversation_runtime_ready(runtime: AgentRuntime) -> None:
        readiness = getattr(runtime, "readiness_status", None)
        if callable(readiness):
            state = readiness(force=True)
            if state != "ready":
                code = {
                    "cli_missing": "codex.cli_missing",
                    "sign_in_required": "codex.sign_in_required",
                    "unavailable": "codex.unavailable",
                }.get(str(state), "runtime.unavailable")
                raise OrchestrationServiceError(code)
        if RuntimeCapability.START_TASK.value not in frozenset(runtime.capabilities):
            raise OrchestrationServiceError("conversation.runtime_capability_missing")

    def _conversation_rejected_result(
        self,
        reservation: ConversationDispatchReservation,
        *,
        failure_code: str,
    ) -> ConversationTurnDispatchResult:
        outcome = SubmissionOutcome(
            SubmissionDisposition.REJECTED,
            failure_code=failure_code,
        )
        _run, recorded, _continuation = self._record_conversation_outcome(
            reservation,
            outcome,
        )
        return self._conversation_result(
            reservation,
            duplicate=False,
            disposition=recorded.disposition.value,
        )

    def _claim_conversation_after_binding_revalidation(
        self,
        reservation: ConversationDispatchReservation,
        expected_record: CanonicalAgentRecord,
        expected_binding: RuntimeBinding,
    ) -> RuntimeBinding:
        with private_state_lock(self.data_dir):
            try:
                current_record, current_binding = self._agent_record_and_binding(
                    expected_record.agent.id
                )
                current_digest = self._binding_digest(
                    current_record.agent,
                    current_binding,
                )
            except (AgentRegistryError, OrchestrationServiceError) as exc:
                connection = self._connect()
                try:
                    run = RunRepository(connection).reject_reserved_conversation_turn(
                        turn_id=reservation.turn_id,
                        failure_code="conversation.binding_unavailable",
                    )
                finally:
                    connection.close()
                raise OrchestrationServiceError(
                    "conversation.binding_unavailable",
                    run=run,
                ) from exc
            if (
                current_record != expected_record
                or current_binding != expected_binding
                or current_digest != reservation.runtime_binding_digest
            ):
                connection = self._connect()
                try:
                    run = RunRepository(connection).reject_reserved_conversation_turn(
                        turn_id=reservation.turn_id,
                        failure_code="conversation.binding_changed",
                    )
                finally:
                    connection.close()
                raise OrchestrationServiceError(
                    "conversation.binding_changed",
                    run=run,
                )
            connection = self._connect()
            try:
                RunRepository(connection).claim_conversation_turn_attempt(
                    turn_id=reservation.turn_id,
                    expected_binding_digest=current_digest,
                )
            except RunRepositoryError as exc:
                raise OrchestrationServiceError(exc.code) from exc
            finally:
                connection.close()
            return current_binding

    def _record_conversation_outcome(
        self,
        reservation: ConversationDispatchReservation,
        outcome: SubmissionOutcome,
        *,
        continuation: ConversationRunAdmission | None = None,
        require_continuation_for_completed: bool = False,
    ) -> tuple[
        RunRecord,
        SubmissionOutcome,
        ConversationDispatchReservation | None,
    ]:
        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                repository = RunRepository(connection)
                try:
                    recorded = repository.record_conversation_submission_outcome(
                        turn_id=reservation.turn_id,
                        outcome=outcome,
                        continuation=continuation,
                        require_continuation_for_completed=(
                            require_continuation_for_completed
                        ),
                    )
                    continued = None
                    if continuation is not None:
                        try:
                            next_run = repository.get_run(continuation.run_id)
                        except RunRepositoryConflict as exc:
                            if exc.code != "run.not_found":
                                raise
                        else:
                            if next_run.turn_id is None:
                                raise RunRepositoryError("run_repository.corrupt")
                            continued = repository.conversation_turn_reservation(
                                next_run.turn_id
                            )
                    return recorded, outcome, continued
                except Exception as first_error:
                    if outcome.disposition != SubmissionDisposition.ACCEPTED:
                        raise OrchestrationServiceError(
                            "conversation.outcome_persistence_failed"
                        ) from first_error
                    fallback = SubmissionOutcome(
                        SubmissionDisposition.UNKNOWN,
                        failure_code="runtime.outcome_persistence_unknown",
                    )
                    try:
                        recorded = repository.record_conversation_submission_outcome(
                            turn_id=reservation.turn_id,
                            outcome=fallback,
                            require_continuation_for_completed=(
                                require_continuation_for_completed
                            ),
                        )
                    except Exception as exc:
                        raise OrchestrationServiceError(
                            "conversation.outcome_persistence_failed"
                        ) from exc
                    return recorded, fallback, None
            finally:
                connection.close()

    def submit_conversation_turn(
        self,
        *,
        conversation_id: str,
        text: str,
        idempotency_key: str,
    ) -> ConversationTurnDispatchResult:
        """Submit one exact text Turn with at most one unlocked adapter call."""

        agent_id, retry, staged_context = self._conversation_retry(
            conversation_id=conversation_id,
            text=text,
            idempotency_key=idempotency_key,
        )
        if retry is not None:
            return self._conversation_result(retry, duplicate=True)

        try:
            record, binding = self._agent_record_and_binding(agent_id)
            runtime = self.runtime_registry.require(binding.runtime_type)
        except AgentRegistryError as exc:
            raise OrchestrationServiceError("conversation.binding_unavailable") from exc
        except AgentRuntimeError as exc:
            raise OrchestrationServiceError(exc.code) from exc
        if RuntimeCapability.START_TASK.value not in record.agent.capabilities:
            raise OrchestrationServiceError("conversation.agent_capability_missing")
        if staged_context is not None:
            if RuntimeCapability.ATTACHMENTS.value not in record.agent.capabilities:
                raise OrchestrationServiceError(
                    "conversation_context.capability_missing"
                )
            if not self._runtime_supports_attachments(runtime, binding):
                raise OrchestrationServiceError(
                    "conversation_context.runtime_unsupported"
                )
        binding_digest = self._binding_digest(record.agent, binding)
        capacity_scope_digest, capacity_limit = self._capacity_evidence(
            runtime, binding, binding_digest
        )

        guard_factory = getattr(runtime, "submission_guard", None)
        guard = guard_factory() if callable(guard_factory) else nullcontext()
        context_guard = (
            self.conversation_context_guard
            if staged_context is not None
            and staged_context.get("context_pack") is not None
            and self.conversation_context_guard is not None
            else nullcontext()
        )
        with guard, context_guard:
            fresh_agent_id, guarded_retry, guarded_context = self._conversation_retry(
                conversation_id=conversation_id,
                text=text,
                idempotency_key=idempotency_key,
            )
            if guarded_retry is not None:
                return self._conversation_result(guarded_retry, duplicate=True)
            if fresh_agent_id != agent_id or (
                None if guarded_context is None else guarded_context["context_digest"]
            ) != (
                None if staged_context is None else staged_context["context_digest"]
            ):
                raise OrchestrationServiceError("conversation_context.conflict")
            staged_context = guarded_context
            attachment_ids: tuple[str, ...] = ()
            if staged_context is not None:
                if not self._runtime_supports_attachments(runtime, binding):
                    raise OrchestrationServiceError(
                        "conversation_context.runtime_unsupported"
                    )
                with private_state_lock(self.data_dir):
                    connection = self._connect()
                    try:
                        current_context = staged_context_evidence(
                            connection,
                            conversation_id,
                        )
                    finally:
                        connection.close()
                if (
                    current_context is None
                    or current_context["context_digest"]
                    != staged_context["context_digest"]
                ):
                    raise OrchestrationServiceError(
                        "conversation_context.conflict"
                    )
                pack = current_context.get("context_pack")
                if pack is not None and not self._conversation_context_is_current(
                    pack,
                    tuple(current_context["context_pack_source_digests"]),
                ):
                    raise OrchestrationServiceError(
                        "conversation_context.pack_changed"
                    )
                attachment_ids = tuple(current_context["attachment_ids"])
            return self._submit_new_conversation_turn(
                conversation_id=conversation_id,
                text=text,
                idempotency_key=idempotency_key,
                record=record,
                binding=binding,
                binding_digest=binding_digest,
                capacity_scope_digest=capacity_scope_digest,
                capacity_limit=capacity_limit,
                runtime=runtime,
                attachment_ids=attachment_ids,
            )

    def _conversation_run_action(
        self,
        *,
        action: str,
        conversation_id: str,
        source_run_id: str,
        idempotency_key: str,
    ) -> ConversationRunActionResult:
        """Create and submit one explicit same-Turn Retry or Resume Run."""

        if (
            action not in {"retry", "resume"}
            or
            re.fullmatch(
                r"conv_[A-Za-z0-9][A-Za-z0-9_.:-]{0,122}",
                str(conversation_id),
            ) is None
            or re.fullmatch(
                r"run_[A-Za-z0-9][A-Za-z0-9_.:-]{0,123}",
                str(source_run_id),
            ) is None
        ):
            raise OrchestrationServiceError("conversation.attempt_invalid")
        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                repository = RunRepository(connection)
                replay = repository.lookup_conversation_run_attempt(
                    action=action,
                    idempotency_key=idempotency_key,
                    conversation_id=conversation_id,
                    source_run_id=source_run_id,
                )
                if replay is not None:
                    return ConversationRunActionResult(replay, True)
                source = repository.get_run(source_run_id)
                if (
                    source.conversation_id != conversation_id
                    or source.agent_id is None
                ):
                    raise OrchestrationServiceError(
                        "conversation.attempt_stale"
                    )
                agent_id = source.agent_id
                source_runtime_run_ref = source.runtime_run_ref
            except RunRepositoryError as exc:
                raise OrchestrationServiceError(exc.code) from exc
            finally:
                connection.close()
        try:
            source_input_context = run_input_context(
                self.data_dir,
                source_run_id,
            )
        except ConversationAttachmentError as exc:
            raise OrchestrationServiceError(exc.code) from exc
        source_pack = (
            None
            if source_input_context is None
            else source_input_context.get("context_pack")
        )
        try:
            record, binding = self._agent_record_and_binding(agent_id)
            runtime = self.runtime_registry.require(binding.runtime_type)
        except AgentRegistryError as exc:
            raise OrchestrationServiceError(
                "conversation.binding_unavailable"
            ) from exc
        except AgentRuntimeError as exc:
            raise OrchestrationServiceError(exc.code) from exc
        required_capability = (
            RuntimeCapability.START_TASK.value
            if action == "retry"
            else RuntimeCapability.RESUME.value
        )
        if required_capability not in record.agent.capabilities:
            raise OrchestrationServiceError(
                "conversation.agent_capability_missing"
            )
        if source_input_context is not None:
            if RuntimeCapability.ATTACHMENTS.value not in record.agent.capabilities:
                raise OrchestrationServiceError(
                    "conversation_context.capability_missing"
                )
            if not self._runtime_supports_attachments(runtime, binding):
                raise OrchestrationServiceError(
                    "conversation_context.runtime_unsupported"
                )
        if action == "resume":
            if source_runtime_run_ref is None:
                raise OrchestrationServiceError(
                    "conversation.resume_unavailable"
                )
            context = RuntimeContext(
                agent_id=record.agent.id,
                runtime_agent_ref=binding.runtime_agent_ref,
                task_id=source_run_id,
                mentat_run_id=source_run_id,
                runtime_run_ref=source_runtime_run_ref,
            )
            try:
                live_capabilities = runtime.capabilities_for_run(
                    source_runtime_run_ref,
                    context=context,
                )
            except Exception as exc:
                raise OrchestrationServiceError(
                    "conversation.resume_unavailable"
                ) from exc
            if (
                RuntimeCapability.RESUME.value not in live_capabilities
                or not callable(getattr(runtime, "resume_task", None))
            ):
                raise OrchestrationServiceError(
                    "conversation.resume_unavailable"
                )
        binding_digest = self._binding_digest(record.agent, binding)
        admission = self._conversation_admission(
            record=record,
            binding=binding,
            runtime=runtime,
            binding_digest=binding_digest,
            run_id=f"run_{action}_{uuid4().hex}",
        )
        guard_factory = getattr(runtime, "submission_guard", None)
        guard = guard_factory() if callable(guard_factory) else nullcontext()
        context_guard = (
            self.conversation_context_guard
            if source_pack is not None and self.conversation_context_guard is not None
            else nullcontext()
        )
        with ExitStack() as stack:
            stack.enter_context(guard)
            stack.enter_context(context_guard)
            if source_input_context is not None and not self._runtime_supports_attachments(
                runtime,
                binding,
            ):
                raise OrchestrationServiceError(
                    "conversation_context.runtime_unsupported"
                )
            if source_pack is not None and not self._conversation_context_is_current(
                source_pack,
                tuple(source_input_context["context_pack_source_digests"]),
            ):
                raise OrchestrationServiceError(
                    "conversation_context.pack_changed"
                )
            source_attachment_ids = (
                ()
                if source_input_context is None
                else tuple(source_input_context["attachment_ids"])
            )
            if source_attachment_ids:
                if self.conversation_attachment_preparer is None:
                    raise OrchestrationServiceError(
                        "conversation_context.runtime_unsupported"
                    )
                try:
                    self.conversation_attachment_preparer(
                        admission.run_id,
                        source_attachment_ids,
                    )
                except Exception as exc:
                    raise OrchestrationServiceError(
                        "conversation_context.attachment_unavailable"
                    ) from exc
                if self.conversation_attachment_cleanup is not None:
                    stack.callback(
                        self.conversation_attachment_cleanup,
                        admission.run_id,
                    )
            with private_state_lock(self.data_dir):
                connection = self._connect()
                try:
                    reservation = RunRepository(
                        connection
                    ).reserve_conversation_run_attempt(
                        action=action,
                        idempotency_key=idempotency_key,
                        conversation_id=conversation_id,
                        source_run_id=source_run_id,
                        admission=admission,
                    )
                except RunRepositoryError as exc:
                    raise OrchestrationServiceError(exc.code) from exc
                finally:
                    connection.close()
            if not reservation.duplicate:
                result = self._conversation_result(
                    reservation,
                    duplicate=False,
                )
                self._execute_reserved_conversation_turn(
                    reservation=reservation,
                    text=result.message.content["parts"][0]["text"],
                    record=record,
                    binding=binding,
                    runtime=runtime,
                    resume_runtime_run_ref=(
                        source_runtime_run_ref if action == "resume" else None
                    ),
                )
            with private_state_lock(self.data_dir):
                connection = self._connect()
                try:
                    attempt = RunRepository(
                        connection
                    ).get_conversation_run_attempt_result(
                        idempotency_key=idempotency_key,
                    )
                finally:
                    connection.close()
        return ConversationRunActionResult(
            attempt=attempt,
            duplicate=reservation.duplicate,
        )

    def retry_conversation_run(
        self,
        *,
        conversation_id: str,
        source_run_id: str,
        idempotency_key: str,
    ) -> ConversationRunActionResult:
        return self._conversation_run_action(
            action="retry",
            conversation_id=conversation_id,
            source_run_id=source_run_id,
            idempotency_key=idempotency_key,
        )

    def resume_conversation_run(
        self,
        *,
        conversation_id: str,
        source_run_id: str,
        idempotency_key: str,
    ) -> ConversationRunActionResult:
        return self._conversation_run_action(
            action="resume",
            conversation_id=conversation_id,
            source_run_id=source_run_id,
            idempotency_key=idempotency_key,
        )

    def _execute_reserved_conversation_turn(
        self,
        *,
        reservation: ConversationDispatchReservation,
        text: str,
        record: CanonicalAgentRecord,
        binding: RuntimeBinding,
        runtime: AgentRuntime,
        continuation_runtime_run_ref: str | None = None,
        resume_runtime_run_ref: str | None = None,
    ) -> ConversationTurnDispatchResult:
        """Claim and invoke one already-reserved Turn exactly once."""

        if reservation.run_id is None:
            raise OrchestrationServiceError("conversation.run_required")
        try:
            current_binding = self._claim_conversation_after_binding_revalidation(
                reservation,
                record,
                binding,
            )
        except OrchestrationServiceError as exc:
            if exc.run is None:
                raise
            return self._conversation_result(
                reservation,
                duplicate=False,
                disposition="rejected",
            )

        # The claim is durable before any adapter-owned readiness or binding
        # operation. A failure from this point forward is canonical and is
        # never converted into an admission rollback or automatic retry.
        try:
            self._conversation_runtime_ready(runtime)
            validator = getattr(runtime, "validate_agent_binding", None)
            if callable(validator):
                validator(
                    current_binding.runtime_agent_ref,
                    tuple(sorted(record.agent.capabilities)),
                )
        except OrchestrationServiceError as exc:
            return self._conversation_rejected_result(
                reservation,
                failure_code=exc.code,
            )
        except AgentRuntimeError as exc:
            return self._conversation_rejected_result(
                reservation,
                failure_code=exc.code,
            )
        title = " ".join(text.split())[:240]
        try:
            turn_task = MentatTask(
                id=reservation.turn_id,
                title=title,
                objective=text,
                status=TaskStatus.QUEUED,
                assigned_agent_id=record.agent.id,
            )
        except (TypeError, ValueError):
            outcome = SubmissionOutcome(
                SubmissionDisposition.REJECTED,
                failure_code="runtime.task_invalid",
            )
        else:
            try:
                input_context = run_input_context(
                    self.data_dir,
                    reservation.run_id,
                )
            except ConversationAttachmentError as exc:
                return self._conversation_rejected_result(
                    reservation,
                    failure_code=exc.code,
                )
            pack = (
                None
                if input_context is None
                else input_context.get("context_pack")
            )
            context = RuntimeContext(
                agent_id=record.agent.id,
                runtime_agent_ref=current_binding.runtime_agent_ref,
                task_id=reservation.turn_id,
                mentat_run_id=reservation.run_id,
                dispatch_id=reservation.turn_id,
                continuation_runtime_run_ref=continuation_runtime_run_ref,
                attachment_ids=(
                    ()
                    if input_context is None
                    else tuple(input_context["attachment_ids"])
                ),
                context_pack_id=(
                    None if pack is None else str(pack["id"])
                ),
                context_pack_revision=(
                    None if pack is None else str(pack["revision"])
                ),
            )
            try:
                # No SQLite or private-state lock crosses this external call.
                resume_task = getattr(runtime, "resume_task", None)
                outcome = (
                    resume_task(turn_task, resume_runtime_run_ref, context)
                    if resume_runtime_run_ref is not None
                    else runtime.submit_task(turn_task, context)
                )
                if not isinstance(outcome, SubmissionOutcome):
                    outcome = SubmissionOutcome(
                        SubmissionDisposition.UNKNOWN,
                        failure_code="runtime.submission_invalid",
                    )
            except Exception:
                outcome = SubmissionOutcome(
                    SubmissionDisposition.UNKNOWN,
                    failure_code="runtime.submission_unknown",
                )
        if (
            binding.runtime_type == "codex"
            and outcome.disposition == SubmissionDisposition.ACCEPTED
            and outcome.runtime_run_ref is None
        ):
            outcome = SubmissionOutcome(
                SubmissionDisposition.UNKNOWN,
                failure_code="runtime.continuation_reference_missing",
            )
        continuation = None
        continuation_required = False
        if (
            outcome.disposition == SubmissionDisposition.ACCEPTED
            and outcome.run is not None
            and outcome.run.status == RunStatus.COMPLETED
            and reservation.run_id is not None
            and binding.runtime_type != "hermes"
        ):
            continuation_required = (
                binding.runtime_type == "codex"
                and outcome.runtime_run_ref is None
            )
            if not continuation_required:
                continuation = self._conversation_admission(
                    record=record,
                    binding=binding,
                    runtime=runtime,
                    binding_digest=self._binding_digest(record.agent, binding),
                    run_id=(
                        "run_auto_"
                        + hashlib.sha256(
                            (reservation.run_id + ":accepted-continuation").encode("utf-8")
                        ).hexdigest()[:32]
                    ),
                    predecessor_run_id=reservation.run_id,
                )
        recorded_run, recorded_outcome, continued = self._record_conversation_outcome(
            reservation,
            outcome,
            continuation=continuation,
            require_continuation_for_completed=continuation_required,
        )
        post_acceptance_continued = None
        if (
            recorded_outcome.disposition == SubmissionDisposition.ACCEPTED
            and recorded_run.runtime_run_ref is None
            and recorded_run.status
            in {
                "queued",
                "starting",
                "running",
                "cancelling",
                "waiting",
                "waiting_for_approval",
                "waiting_for_clarification",
            }
        ):
            owner = "acceptance_" + hashlib.sha256(
                recorded_run.id.encode("utf-8")
            ).hexdigest()[:24]
            leased = None
            try:
                with private_state_lock(self.data_dir):
                    connection = self._connect()
                    try:
                        leased = RunRepository(
                            connection
                        ).lease_transient_conversation_run(
                            run_id=recorded_run.id,
                            owner=owner,
                        )
                    finally:
                        connection.close()
                if leased is not None:
                    transient_context = RuntimeContext(
                        agent_id=record.agent.id,
                        runtime_agent_ref=current_binding.runtime_agent_ref,
                        task_id=recorded_run.turn_id,
                        mentat_run_id=recorded_run.id,
                    )
                    observed = runtime.get_status(
                        recorded_run.id,
                        context=transient_context,
                    )
                    observed_batch = tuple(
                        islice(
                            runtime.stream_events(
                                recorded_run.id,
                                after_sequence=leased.runtime_event_cursor,
                                context=transient_context,
                            ),
                            1_001,
                        )
                    )
                    has_more_events = len(observed_batch) > 1_000
                    observed_events = observed_batch[:1_000]
                    observed = _cohere_runtime_observation(
                        observed,
                        observed_events,
                        has_more_events=has_more_events,
                    )
                    expected_terminal_event = {
                        RunStatus.COMPLETED: AgentEventType.RUN_COMPLETED,
                        RunStatus.FAILED: AgentEventType.RUN_FAILED,
                        RunStatus.STOPPED: AgentEventType.RUN_STOPPED,
                        RunStatus.INTERRUPTED: AgentEventType.RUN_INTERRUPTED,
                    }.get(observed.status)
                    finalized_terminal = bool(
                        expected_terminal_event is not None
                        and any(
                            event.type == expected_terminal_event
                            for event in observed_events
                        )
                    )
                    post_acceptance_admission = None
                    if (
                        not has_more_events
                        and observed.status == RunStatus.COMPLETED
                        and finalized_terminal
                        and not leased.partial
                    ):
                        post_acceptance_admission = self._conversation_admission(
                            record=record,
                            binding=binding,
                            runtime=runtime,
                            binding_digest=self._binding_digest(
                                record.agent,
                                binding,
                            ),
                            run_id=(
                                "run_auto_"
                                + hashlib.sha256(
                                    (
                                        recorded_run.id
                                        + ":accepted-continuation"
                                    ).encode("utf-8")
                                ).hexdigest()[:32]
                            ),
                            predecessor_run_id=recorded_run.id,
                        )
                    with private_state_lock(self.data_dir):
                        connection = self._connect()
                        try:
                            repository = RunRepository(connection)
                            repository.apply_reconciliation(
                                run_id=recorded_run.id,
                                owner=owner,
                                expected_revision=leased.state_revision,
                                observed=observed,
                                events=observed_events,
                                defer_terminal=(
                                    has_more_events
                                    or expected_terminal_event is not None
                                    and not finalized_terminal
                                ),
                                continuation=post_acceptance_admission,
                            )
                            if post_acceptance_admission is not None:
                                try:
                                    continued_run = repository.get_run(
                                        post_acceptance_admission.run_id
                                    )
                                except RunRepositoryConflict as exc:
                                    if exc.code != "run.not_found":
                                        raise
                                else:
                                    if continued_run.turn_id is None:
                                        raise RunRepositoryError(
                                            "run_repository.corrupt"
                                        )
                                    post_acceptance_continued = (
                                        repository.conversation_turn_reservation(
                                            continued_run.turn_id
                                        )
                                    )
                        finally:
                            connection.close()
            except Exception:
                try:
                    if leased is not None:
                        with private_state_lock(self.data_dir):
                            connection = self._connect()
                            try:
                                RunRepository(
                                    connection
                                ).release_reconciliation_lease(
                                    run_id=leased.id,
                                    owner=owner,
                                    expected_revision=leased.state_revision,
                                )
                            finally:
                                connection.close()
                except Exception:
                    pass
        result = self._conversation_result(
            reservation,
            duplicate=False,
            disposition=recorded_outcome.disposition.value,
        )
        if continued is None:
            continued = post_acceptance_continued
        if continued is not None:
            if self.conversation_continuation_handler is not None:
                try:
                    self.conversation_continuation_handler(
                        recorded_run.id,
                        continued.turn_id,
                    )
                except Exception:
                    # The exact reservation remains durable and unattempted.
                    # Never turn the preceding verified result into a retryable
                    # browser failure.
                    pass
            else:
                queued = self._conversation_result(continued, duplicate=False)
                try:
                    self._execute_reserved_conversation_turn(
                        reservation=continued,
                        text=queued.message.content["parts"][0]["text"],
                        record=record,
                        binding=binding,
                        runtime=runtime,
                        continuation_runtime_run_ref=recorded_run.runtime_run_ref,
                    )
                except OrchestrationServiceError:
                    # The next Turn is already durably claimed. Never turn the
                    # preceding verified result into a retryable browser failure.
                    pass
        return result

    def _submit_new_conversation_turn(
        self,
        *,
        conversation_id: str,
        text: str,
        idempotency_key: str,
        record: CanonicalAgentRecord,
        binding: RuntimeBinding,
        binding_digest: str,
        capacity_scope_digest: str,
        capacity_limit: int,
        runtime: AgentRuntime,
        attachment_ids: tuple[str, ...] = (),
    ) -> ConversationTurnDispatchResult:
        """Reserve, submit once, and persist while holding an adapter guard."""

        message_id = self.id_factory("msg")
        turn_id = self.id_factory("turn")
        run_id = self.id_factory("run")
        prepared = False
        if attachment_ids:
            if self.conversation_attachment_preparer is None:
                raise OrchestrationServiceError("conversation_context.runtime_unsupported")
            try:
                self.conversation_attachment_preparer(run_id, attachment_ids)
                prepared = True
            except Exception as exc:
                raise OrchestrationServiceError(
                    "conversation_context.attachment_unavailable"
                ) from exc
        try:
            with private_state_lock(self.data_dir):
                connection = self._connect()
                try:
                    reservation = RunRepository(connection).reserve_conversation_turn(
                        idempotency_key=idempotency_key,
                        conversation_id=conversation_id,
                        message_id=message_id,
                        turn_id=turn_id,
                        run_id=run_id,
                        text=text,
                        agent_id=record.agent.id,
                        agent_name=record.agent.name,
                        agent_revision=record.revision,
                        runtime_type=binding.runtime_type,
                        runtime_config_id=binding.id,
                        runtime_config_revision=binding.revision,
                        binding_digest=binding_digest,
                        capabilities=record.agent.capabilities,
                        capacity_scope_digest=capacity_scope_digest,
                        capacity_limit=capacity_limit,
                    )
                except RunRepositoryError as exc:
                    raise OrchestrationServiceError(exc.code) from exc
                finally:
                    connection.close()
        except Exception:
            if prepared and self.conversation_attachment_cleanup is not None:
                self.conversation_attachment_cleanup(run_id)
            raise
        if reservation.duplicate:
            if prepared and self.conversation_attachment_cleanup is not None:
                self.conversation_attachment_cleanup(run_id)
            return self._conversation_result(reservation, duplicate=True)
        if reservation.run_id is None:
            if prepared and self.conversation_attachment_cleanup is not None:
                self.conversation_attachment_cleanup(run_id)
            return self._conversation_result(
                reservation,
                duplicate=False,
                disposition=reservation.state,
            )

        try:
            return self._execute_reserved_conversation_turn(
                reservation=reservation,
                text=text,
                record=record,
                binding=binding,
                runtime=runtime,
            )
        finally:
            if prepared and self.conversation_attachment_cleanup is not None:
                self.conversation_attachment_cleanup(run_id)

    def _reject_reserved_conversation_continuation(
        self,
        reservation: ConversationDispatchReservation,
        *,
        failure_code: str,
    ) -> ConversationTurnDispatchResult:
        """Terminalize a continuation that cannot be safely submitted."""

        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                RunRepository(connection).reject_reserved_conversation_turn(
                    turn_id=reservation.turn_id,
                    failure_code=failure_code,
                )
            except RunRepositoryError as exc:
                raise OrchestrationServiceError(exc.code) from exc
            finally:
                connection.close()
        return self._conversation_result(
            reservation,
            duplicate=False,
            disposition="rejected",
        )

    def execute_reserved_conversation_turn(
        self,
        turn_id: str,
        *,
        source_run_id: str | None = None,
    ) -> ConversationTurnDispatchResult:
        """Execute one exact worker-reserved FIFO continuation at most once."""

        continuation_reference = None
        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                repository = RunRepository(connection)
                reservation = repository.conversation_turn_reservation(turn_id)
                if (
                    reservation.run_id is None
                    or reservation.state != "reserved"
                    or reservation.attempt_count != 0
                ):
                    raise RunRepositoryConflict("conversation.state_changed")
                run = repository.get_run(reservation.run_id)
                if (
                    run.source != "console"
                    or run.conversation_id != reservation.conversation_id
                    or run.turn_id != reservation.turn_id
                    or run.status != "reserved"
                    or run.dispatch_state != "reserved"
                    or run.agent_id is None
                    or run.runtime_binding_digest
                    != reservation.runtime_binding_digest
                ):
                    raise RunRepositoryError("run_repository.corrupt")
                predecessor = repository.conversation_continuation_predecessor(
                    run_id=run.id,
                    expected_source_run_id=source_run_id,
                )
                if predecessor is not None and run.runtime_type == "codex":
                    if not predecessor.runtime_run_ref:
                        raise RunRepositoryConflict(
                            "conversation.continuation_changed"
                        )
                    continuation_reference = predecessor.runtime_run_ref
            except RunRepositoryError as exc:
                raise OrchestrationServiceError(exc.code) from exc
            finally:
                connection.close()

        queued = self._conversation_result(reservation, duplicate=False)
        try:
            record, binding = self._agent_record_and_binding(run.agent_id)
            runtime = self.runtime_registry.require(binding.runtime_type)
        except (
            AgentRegistryError,
            AgentRuntimeError,
            OrchestrationServiceError,
        ):
            return self._reject_reserved_conversation_continuation(
                reservation,
                failure_code="conversation.binding_unavailable",
            )
        if (
            binding.runtime_type != run.runtime_type
            or self._binding_digest(record.agent, binding)
            != reservation.runtime_binding_digest
        ):
            return self._reject_reserved_conversation_continuation(
                reservation,
                failure_code="conversation.binding_changed",
            )
        guard_factory = getattr(runtime, "submission_guard", None)
        try:
            guard = guard_factory() if callable(guard_factory) else nullcontext()
            with guard:
                return self._execute_reserved_conversation_turn(
                    reservation=reservation,
                    text=queued.message.content["parts"][0]["text"],
                    record=record,
                    binding=binding,
                    runtime=runtime,
                    continuation_runtime_run_ref=continuation_reference,
                )
        except OrchestrationServiceError:
            raise
        except Exception:
            # A guard failure before claim is known not to have reached the
            # adapter. Once claimed, _execute_reserved_conversation_turn owns
            # the durable accepted/rejected/unknown outcome instead.
            refreshed = self._conversation_result(reservation, duplicate=False)
            if (
                refreshed.run is not None
                and refreshed.run.status == "reserved"
                and getattr(refreshed.run, "dispatch_state", None) == "reserved"
            ):
                return self._reject_reserved_conversation_continuation(
                    reservation,
                    failure_code="conversation.binding_unavailable",
                )
            raise OrchestrationServiceError("conversation.unavailable")

    def _queue_mutation_result(
        self,
        *,
        conversation_id: str,
        message: ConversationMessageRecord,
        turn: ConversationTurnRecord,
        disposition: str,
    ) -> ConversationQueueMutationResult:
        try:
            conversation = ConversationRepository(
                self.data_dir,
                supported_runtime_types=self.runtime_registry.runtime_types,
            ).read(conversation_id).conversation
        except ConversationRepositoryError as exc:
            raise OrchestrationServiceError("conversation.unavailable") from exc
        return ConversationQueueMutationResult(
            conversation=conversation,
            message=message,
            turn=turn,
            disposition=disposition,
        )

    def edit_conversation_turn(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        expected_revision: int,
        expected_message_revision: int,
        text: str,
    ) -> ConversationQueueMutationResult:
        """Edit one exact undispatched queue item under Turn and Message CAS."""

        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                turn, message = RunRepository(
                    connection
                ).edit_queued_conversation_turn(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    expected_revision=expected_revision,
                    expected_message_revision=expected_message_revision,
                    text=text,
                )
            except RunRepositoryError as exc:
                raise OrchestrationServiceError(exc.code) from exc
            finally:
                connection.close()
        return self._queue_mutation_result(
            conversation_id=conversation_id,
            message=message,
            turn=turn,
            disposition="edited",
        )

    def cancel_conversation_turn(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        expected_revision: int,
        expected_message_revision: int,
    ) -> ConversationQueueMutationResult:
        """Cancel one exact undispatched queue item under Turn and Message CAS."""

        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                turn, message = RunRepository(
                    connection
                ).cancel_queued_conversation_turn(
                    conversation_id=conversation_id,
                    turn_id=turn_id,
                    expected_revision=expected_revision,
                    expected_message_revision=expected_message_revision,
                )
            except RunRepositoryError as exc:
                raise OrchestrationServiceError(exc.code) from exc
            finally:
                connection.close()
        return self._queue_mutation_result(
            conversation_id=conversation_id,
            message=message,
            turn=turn,
            disposition="cancelled",
        )

    def continue_conversation_turn(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        expected_revision: int,
        expected_message_revision: int,
    ) -> ConversationTurnDispatchResult:
        """Explicitly revalidate and invoke the exact blocked FIFO head."""

        try:
            detail = ConversationRepository(
                self.data_dir,
                supported_runtime_types=self.runtime_registry.runtime_types,
            ).read(conversation_id)
        except ConversationRepositoryError as exc:
            raise OrchestrationServiceError(exc.code) from exc
        try:
            record, binding = self._agent_record_and_binding(
                detail.conversation.agent_id
            )
            runtime = self.runtime_registry.require(binding.runtime_type)
        except AgentRegistryError as exc:
            raise OrchestrationServiceError(
                "conversation.binding_unavailable"
            ) from exc
        except AgentRuntimeError as exc:
            raise OrchestrationServiceError(exc.code) from exc
        if RuntimeCapability.START_TASK.value not in record.agent.capabilities:
            raise OrchestrationServiceError(
                "conversation.agent_capability_missing"
            )
        binding_digest = self._binding_digest(record.agent, binding)
        admission = self._conversation_admission(
            record=record,
            binding=binding,
            runtime=runtime,
            binding_digest=binding_digest,
            run_id=self.id_factory("run"),
        )
        guard_factory = getattr(runtime, "submission_guard", None)
        guard = guard_factory() if callable(guard_factory) else nullcontext()
        with guard:
            continuation_reference = None
            continuity_blocked = False
            with private_state_lock(self.data_dir):
                connection = self._connect()
                try:
                    repository = RunRepository(connection)
                    if binding.runtime_type == "codex":
                        (
                            blocked_reservation,
                            continuity_allowed,
                            continuation_reference,
                            continuation_source_run_id,
                        ) = repository.codex_continuation_for_blocked_turn(
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            expected_revision=expected_revision,
                            expected_message_revision=expected_message_revision,
                            binding_digest=binding_digest,
                        )
                        if not continuity_allowed:
                            reservation = blocked_reservation
                            continuity_blocked = True
                        elif continuation_source_run_id is not None:
                            admission = replace(
                                admission,
                                predecessor_run_id=continuation_source_run_id,
                            )
                    if not continuity_blocked:
                        reservation = repository.continue_blocked_conversation_turn(
                            conversation_id=conversation_id,
                            turn_id=turn_id,
                            expected_revision=expected_revision,
                            expected_message_revision=expected_message_revision,
                            admission=admission,
                        )
                except RunRepositoryError as exc:
                    raise OrchestrationServiceError(exc.code) from exc
                finally:
                    connection.close()
            if continuity_blocked or reservation.run_id is None:
                return self._conversation_result(
                    reservation,
                    duplicate=False,
                    disposition="blocked",
                )
            queued = self._conversation_result(reservation, duplicate=False)
            return self._execute_reserved_conversation_turn(
                reservation=reservation,
                text=queued.message.content["parts"][0]["text"],
                record=record,
                binding=binding,
                runtime=runtime,
                continuation_runtime_run_ref=continuation_reference,
            )

    def reconcile_runs(
        self,
        *,
        owner: str,
        limit: int = 20,
    ) -> ReconciliationReport:
        """Read authoritative runtime state under short SQLite CAS leases."""

        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                leased = RunRepository(connection).lease_reconcilable_runs(
                    owner=owner,
                    limit=limit,
                )
            finally:
                connection.close()
        return self._reconcile_leased_runs(leased, owner=owner)

    def reconcile_run(self, *, run_id: str, owner: str) -> ReconciliationReport:
        """Reconcile one exact Run after a capability-scoped action."""

        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                leased = RunRepository(connection).lease_reconcilable_run(
                    run_id=run_id,
                    owner=owner,
                )
            finally:
                connection.close()
        return self._reconcile_leased_runs(
            () if leased is None else (leased,),
            owner=owner,
        )

    def _reconcile_leased_runs(
        self,
        leased: tuple[RunRecord, ...],
        *,
        owner: str,
    ) -> ReconciliationReport:
        reconciled: list[str] = []
        unavailable: list[str] = []
        for run in leased:
            applied = False
            try:
                if run.agent_id is None or run.runtime_binding_digest is None:
                    raise OrchestrationServiceError("reconcile.binding_unavailable")
                # The canonical Agent registry shares the private SQLite
                # authority. Keep its short snapshot read serialized with
                # competing lease writers, but release the lock before any
                # adapter operation.
                with private_state_lock(self.data_dir):
                    record, binding = self._agent_record_and_binding(run.agent_id)
                    agent = record.agent
                    binding_digest = self._binding_digest(agent, binding)
                    if binding_digest != run.runtime_binding_digest:
                        raise OrchestrationServiceError("reconcile.binding_changed")
                    runtime = self.runtime_registry.require(run.runtime_type)

                runtime_run_id = run.runtime_run_ref or run.id
                context = RuntimeContext(
                    agent_id=agent.id,
                    runtime_agent_ref=binding.runtime_agent_ref,
                    task_id=run.task_id or run.turn_id,
                    mentat_run_id=run.id,
                    runtime_run_ref=run.runtime_run_ref,
                )
                # No SQLite/private-state lock crosses either adapter read.
                observed = runtime.get_status(runtime_run_id, context=context)
                observed_batch = tuple(
                    islice(
                        runtime.stream_events(
                            runtime_run_id,
                            after_sequence=run.runtime_event_cursor,
                            context=context,
                        ),
                        1_001,
                    )
                )
                has_more_events = len(observed_batch) > 1_000
                observed_events = observed_batch[:1_000]
                observed = _cohere_runtime_observation(
                    observed,
                    observed_events,
                    has_more_events=has_more_events,
                )
                continuation = None
                continuation_reference = None
                continuation_required = False
                if (
                    run.conversation_id is not None
                    and not has_more_events
                    and observed.status == RunStatus.COMPLETED
                ):
                    codex_continuable = (
                        run.runtime_type == "codex"
                        and run.status != "unknown"
                        and not run.partial
                    )
                    continuation_required = (
                        codex_continuable and run.runtime_run_ref is None
                    )
                    if not continuation_required:
                        continuation = self._conversation_admission(
                            record=record,
                            binding=binding,
                            runtime=runtime,
                            binding_digest=binding_digest,
                            run_id=(
                                "run_auto_"
                                + hashlib.sha256(
                                    (
                                        run.id
                                        + ":"
                                        + str(run.state_revision)
                                        + ":continuation"
                                    ).encode("utf-8")
                                ).hexdigest()[:32]
                            ),
                            predecessor_run_id=run.id,
                        )
                    if codex_continuable:
                        continuation_reference = run.runtime_run_ref
                with private_state_lock(self.data_dir):
                    connection = self._connect()
                    try:
                        RunRepository(connection).apply_reconciliation(
                            run_id=run.id,
                            owner=owner,
                            expected_revision=run.state_revision,
                            observed=observed,
                            events=observed_events,
                            defer_terminal=has_more_events,
                            continuation=continuation,
                            require_continuation_for_completed=(
                                continuation_required
                            ),
                        )
                    finally:
                        connection.close()
                applied = True
                reconciled.append(run.id)
                if continuation is not None:
                    reservation = None
                    with private_state_lock(self.data_dir):
                        connection = self._connect()
                        try:
                            repository = RunRepository(connection)
                            try:
                                continued_run = repository.get_run(
                                    continuation.run_id
                                )
                            except RunRepositoryConflict as exc:
                                if exc.code != "run.not_found":
                                    raise
                            else:
                                if continued_run.turn_id is None:
                                    raise RunRepositoryError(
                                        "run_repository.corrupt"
                                    )
                                reservation = (
                                    repository.conversation_turn_reservation(
                                        continued_run.turn_id
                                    )
                                )
                        finally:
                            connection.close()
                    if reservation is not None:
                        if self.conversation_continuation_handler is not None:
                            self.conversation_continuation_handler(
                                run.id,
                                reservation.turn_id,
                            )
                        else:
                            queued = self._conversation_result(
                                reservation,
                                duplicate=False,
                            )
                            queued_text = queued.message.content["parts"][0]["text"]
                            guard_factory = getattr(runtime, "submission_guard", None)
                            guard = (
                                guard_factory()
                                if callable(guard_factory)
                                else nullcontext()
                            )
                            with guard:
                                self._execute_reserved_conversation_turn(
                                    reservation=reservation,
                                    text=queued_text,
                                    record=record,
                                    binding=binding,
                                    runtime=runtime,
                                    continuation_runtime_run_ref=continuation_reference,
                                )
            except Exception:
                # Missing or conflicting evidence never proves progress and
                # never causes submission retry. Release only our exact lease.
                if not applied:
                    with private_state_lock(self.data_dir):
                        connection = self._connect()
                        try:
                            RunRepository(connection).release_reconciliation_lease(
                                run_id=run.id,
                                owner=owner,
                                expected_revision=run.state_revision,
                            )
                        finally:
                            connection.close()
                    unavailable.append(run.id)
        return ReconciliationReport(
            leased=len(leased),
            reconciled=tuple(reconciled),
            unavailable=tuple(unavailable),
        )


__all__ = [
    "ConversationQueueMutationResult",
    "ConversationRunActionResult",
    "ConversationTurnDispatchResult",
    "DispatchResult",
    "OrchestrationService",
    "OrchestrationServiceError",
    "ReconciliationReport",
]
