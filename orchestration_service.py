"""Runtime-neutral Task dispatch over Mentat's durable orchestration store."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
from pathlib import Path
import sqlite3
from typing import Callable
from uuid import uuid4

from agent_registry import AgentRegistry, AgentRegistryError, RuntimeBinding
from agent_runtime import (
    AgentRuntime,
    AgentRuntimeError,
    AgentRuntimeRegistry,
    MentatAgent,
    MentatTask,
    RuntimeCapability,
    RuntimeContext,
    SubmissionDisposition,
    SubmissionOutcome,
    TaskStatus,
)
from mentat_db import MentatDatabaseError, connect
from private_state import private_state_lock
from run_repository import (
    DispatchReservation,
    RunRecord,
    RunRepository,
    RunRepositoryConflict,
    RunRepositoryError,
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
    def _require_capabilities(
        task: MentatTask,
        agent: MentatAgent,
        runtime: AgentRuntime,
    ) -> None:
        runtime_capabilities = frozenset(runtime.capabilities)
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
                agent, binding = self._agent_and_binding(task.assigned_agent_id or "")
                try:
                    runtime = self.runtime_registry.require(binding.runtime_type)
                except AgentRuntimeError as exc:
                    raise OrchestrationServiceError(exc.code) from exc
                self._require_capabilities(task, agent, runtime)
                digest = self._binding_digest(agent, binding)
                reservation = repository.reserve_dispatch(
                    idempotency_key=idempotency_key,
                    dispatch_id=self.id_factory("dispatch"),
                    run_id=self.id_factory("run"),
                    task=snapshot.document,
                    task_revision=snapshot.revision,
                    agent_id=agent.id,
                    runtime_type=binding.runtime_type,
                    runtime_config_id=binding.id,
                    binding_digest=digest,
                    capabilities=agent.capabilities,
                )
                return reservation, task, agent, binding, runtime
            except OrchestrationServiceError:
                raise
            except (TaskRepositoryError, AgentRegistryError, RunRepositoryError) as exc:
                code = self._dispatch_error_code(
                    getattr(exc, "code", "dispatch.unavailable")
                )
                raise OrchestrationServiceError(code) from exc
            finally:
                connection.close()

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
            try:
                if run.agent_id is None or run.runtime_binding_digest is None:
                    raise OrchestrationServiceError("reconcile.binding_unavailable")
                agent, binding = self._agent_and_binding(run.agent_id)
                if self._binding_digest(agent, binding) != run.runtime_binding_digest:
                    raise OrchestrationServiceError("reconcile.binding_changed")
                runtime = self.runtime_registry.require(run.runtime_type)

                runtime_run_id = run.runtime_run_ref or run.id
                context = RuntimeContext(
                    agent_id=agent.id,
                    runtime_agent_ref=binding.runtime_agent_ref,
                    task_id=run.task_id,
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
                        )
                    finally:
                        connection.close()
                reconciled.append(run.id)
            except Exception:
                # Missing or conflicting evidence never proves progress and
                # never causes submission retry. Release only our exact lease.
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
    "DispatchResult",
    "OrchestrationService",
    "OrchestrationServiceError",
    "ReconciliationReport",
]
