"""Runtime-neutral Task dispatch over Mentat's durable orchestration store."""

from __future__ import annotations

from contextlib import nullcontext
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
from run_repository import (
    ConversationDispatchReservation,
    ConversationRunAdmission,
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


class OrchestrationService:
    """Commit durable intent, invoke one adapter once, then record its outcome."""

    def __init__(
        self,
        data_dir: Path,
        *,
        runtime_registry: AgentRuntimeRegistry,
        agent_registry: AgentRegistry | None = None,
        id_factory: Callable[[str], str] | None = None,
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

    def _reserve(
        self,
        *,
        task_id: str,
        expected_revision: int,
        idempotency_key: str,
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
    ) -> RuntimeBinding:
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
                try:
                    repository.claim_dispatch_attempt(
                        dispatch_id=reservation.dispatch_id,
                        expected_binding_digest=current_digest,
                    )
                except RunRepositoryConflict as exc:
                    if exc.code == "dispatch.task_changed":
                        run = repository.reject_reserved_dispatch(
                            dispatch_id=reservation.dispatch_id,
                            failure_code="dispatch.task_changed",
                        )
                        raise OrchestrationServiceError(exc.code, run=run) from exc
                    raise OrchestrationServiceError(exc.code) from exc
                except RunRepositoryError as exc:
                    raise OrchestrationServiceError(
                        self._dispatch_error_code(exc.code)
                    ) from exc
            finally:
                connection.close()
            return current_binding

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

        reservation, task, agent, binding, runtime = self._reserve(
            task_id=task_id,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
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

        current_binding = self._claim_after_binding_revalidation(
            reservation, agent, binding
        )
        context = RuntimeContext(
            agent_id=agent.id,
            runtime_agent_ref=current_binding.runtime_agent_ref,
            task_id=task.id,
            mentat_run_id=reservation.run_id,
            dispatch_id=reservation.dispatch_id,
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
    ) -> tuple[str, ConversationDispatchReservation | None]:
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
                retry = repository.lookup_conversation_turn_retry(
                    idempotency_key=idempotency_key,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    text=text,
                )
                return agent_id, retry
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

        agent_id, retry = self._conversation_retry(
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
        binding_digest = self._binding_digest(record.agent, binding)
        capacity_scope_digest, capacity_limit = self._capacity_evidence(
            runtime, binding, binding_digest
        )

        guard_factory = getattr(runtime, "submission_guard", None)
        guard = guard_factory() if callable(guard_factory) else nullcontext()
        with guard:
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
            context = RuntimeContext(
                agent_id=record.agent.id,
                runtime_agent_ref=current_binding.runtime_agent_ref,
                task_id=reservation.turn_id,
                mentat_run_id=reservation.run_id,
                dispatch_id=reservation.turn_id,
                continuation_runtime_run_ref=continuation_runtime_run_ref,
            )
            try:
                # No SQLite or private-state lock crosses this external call.
                outcome = runtime.submit_task(turn_task, context)
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
                )
        recorded_run, recorded_outcome, continued = self._record_conversation_outcome(
            reservation,
            outcome,
            continuation=continuation,
            require_continuation_for_completed=continuation_required,
        )
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
                    with private_state_lock(self.data_dir):
                        connection = self._connect()
                        try:
                            RunRepository(connection).apply_reconciliation(
                                run_id=recorded_run.id,
                                owner=owner,
                                expected_revision=leased.state_revision,
                                observed=observed,
                                events=(),
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
        if continued is not None:
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
    ) -> ConversationTurnDispatchResult:
        """Reserve, submit once, and persist while holding an adapter guard."""

        with private_state_lock(self.data_dir):
            connection = self._connect()
            try:
                reservation = RunRepository(connection).reserve_conversation_turn(
                    idempotency_key=idempotency_key,
                    conversation_id=conversation_id,
                    message_id=self.id_factory("msg"),
                    turn_id=self.id_factory("turn"),
                    run_id=self.id_factory("run"),
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
        if reservation.duplicate:
            return self._conversation_result(reservation, duplicate=True)
        if reservation.run_id is None:
            return self._conversation_result(
                reservation,
                duplicate=False,
                disposition=reservation.state,
            )

        return self._execute_reserved_conversation_turn(
            reservation=reservation,
            text=text,
            record=record,
            binding=binding,
            runtime=runtime,
        )

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
    "ConversationTurnDispatchResult",
    "DispatchResult",
    "OrchestrationService",
    "OrchestrationServiceError",
    "ReconciliationReport",
]
