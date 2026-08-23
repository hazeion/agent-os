from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_registry import AgentRegistry
from agent_runtime import (
    AgentEvent,
    AgentEventType,
    AgentRun,
    AgentRuntimeError,
    AgentRuntimeRegistry,
    MentatTask,
    RunStatus,
    RuntimeContext,
    SubmissionDisposition,
    SubmissionOutcome,
    TaskStatus,
)
from orchestration_service import OrchestrationService
from private_state import history_path
from run_repository import RunRepository
import server
from tests.sqlite_authority_support import ensure_run_sqlite_authority
from vercel_connections import (
    confirm_abandon_vercel_run,
    confirm_configure_vercel,
    confirm_create_vercel_agent,
    confirm_disconnect_vercel,
    load_vercel_connection,
    preview_abandon_vercel_run,
    preview_configure_vercel,
    preview_create_vercel_agent,
    preview_disconnect_vercel,
)
from vercel_infrastructure import VercelHttpResponse, VercelInfrastructureError
from vercel_runtime import AI_GATEWAY_CHAT_COMPLETIONS_URL, VercelRuntime


GATEWAY_SECRET_CANARY = "gateway-secret-traceback-canary"  # pragma: allowlist secret
RAW_PROVIDER_SECRET_CANARY = "raw-provider-traceback-canary"  # pragma: allowlist secret


class Requester:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def response(payload, status=200):
    return VercelHttpResponse(
        status_code=status,
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )


def configure(root: Path):
    preview = preview_configure_vercel(
        root,
        label="Vercel",
        auth_kind="api_key",
        model="openai/gpt-5.4",
    )
    confirm_configure_vercel(root, preview, preview.confirmation_token)


def task(agent_id="agent_vercel"):
    return MentatTask(
        id="task_vercel",
        title="Vercel task",
        objective="Return the exact result.",
        status=TaskStatus.QUEUED,
        assigned_agent_id=agent_id,
        required_capabilities=("model.generate",),
        acceptance_criteria=("Return one result.",),
    )


def context(agent_id="agent_vercel"):
    return RuntimeContext(
        agent_id=agent_id,
        runtime_agent_ref="connection_vercel",
        task_id="task_vercel",
        mentat_run_id="run_vercel",
        dispatch_id="dispatch_vercel",
    )


def exception_graph_text(error: BaseException) -> str:
    seen: set[int] = set()
    pending: list[object] = [error]
    values: list[str] = []
    while pending:
        value = pending.pop()
        if value is None or id(value) in seen:
            continue
        seen.add(id(value))
        values.append(repr(value))
        if isinstance(value, BaseException):
            pending.extend([value.__cause__, value.__context__, value.args])
            pending.extend(vars(value).values())
            traceback = value.__traceback__
            while traceback is not None:
                pending.append(traceback.tb_frame.f_locals)
                traceback = traceback.tb_next
        elif isinstance(value, dict):
            pending.extend(value.items())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)
    return "\n".join(values)


class RetainingClock:
    def __init__(self):
        self.error: RuntimeError | None = None

    def __call__(self) -> datetime:
        try:
            raise RuntimeError("clock unavailable")
        except RuntimeError as exc:
            self.error = exc
            raise


class VercelRuntimeTests(unittest.TestCase):
    def test_vercel_acceptance_requires_one_exact_provenance_bound_message(self):
        run = AgentRun(
            id="run_vercel",
            task_id="task_vercel",
            agent_id="agent_vercel",
            runtime_type="vercel",
            status=RunStatus.COMPLETED,
        )
        expected_id = "vercel_message_" + hashlib.sha256(
            b"run_vercel:message"
        ).hexdigest()[:24]
        message = AgentEvent(
            id=expected_id,
            run_id=run.id,
            sequence=1,
            type=AgentEventType.MESSAGE,
            occurred_at="2026-08-23T00:00:00Z",
            summary="Vercel AI Gateway returned a response",
            content="Completed safely.",
        )
        accepted = SubmissionOutcome(
            SubmissionDisposition.ACCEPTED,
            run=run,
            runtime_run_ref="vercel_reference",
            initial_events=(message,),
        )
        self.assertEqual(accepted.initial_events, (message,))

        wrong_message = AgentEvent(
            id="vercel_message_" + "0" * 24,
            run_id=run.id,
            sequence=1,
            type=AgentEventType.MESSAGE,
            occurred_at="2026-08-23T00:00:00Z",
            summary="Wrong source",
            content="Untrusted result.",
        )
        extra_message = AgentEvent(
            id="vercel_message_" + "1" * 24,
            run_id=run.id,
            sequence=2,
            type=AgentEventType.MESSAGE,
            occurred_at="2026-08-23T00:00:01Z",
            summary="Extra result",
            content="A second result.",
        )
        for events in ((), (wrong_message,), (message, extra_message)):
            with self.subTest(event_count=len(events)), self.assertRaises(ValueError):
                SubmissionOutcome(
                    SubmissionDisposition.ACCEPTED,
                    run=run,
                    runtime_run_ref="vercel_reference",
                    initial_events=events,
                )

    def test_gateway_submission_is_one_fixed_request_with_normalized_events(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            configure(root)
            requester = Requester(
                response(
                    {
                        "id": "provider_private_identifier",
                        "choices": [{"message": {"content": "Completed safely."}}],
                        "usage": {
                            "prompt_tokens": 12,
                            "completion_tokens": 3,
                            "total_tokens": 15,
                        },
                        "provider_private": "must-not-persist",
                    }
                )
            )
            runtime = VercelRuntime(
                root,
                requester=requester,
                environment={"AI_GATEWAY_API_KEY": "gateway-secret-canary"},  # pragma: allowlist secret
                clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc),
            )
            outcome = runtime.submit_task(task(), context())

            self.assertEqual(outcome.disposition, SubmissionDisposition.ACCEPTED)
            self.assertEqual(outcome.run.status.value, "completed")
            self.assertEqual(
                [event.type for event in outcome.initial_events],
                [AgentEventType.MESSAGE, AgentEventType.COST],
            )
            self.assertEqual(outcome.initial_events[0].content, "Completed safely.")
            self.assertEqual(outcome.initial_events[1].metrics["total_tokens"], 15)
            self.assertNotIn("provider_private_identifier", outcome.runtime_run_ref)
            self.assertEqual(len(requester.calls), 1)
            call = requester.calls[0]
            self.assertEqual(call[1], AI_GATEWAY_CHAT_COMPLETIONS_URL)
            self.assertEqual(call[2]["json_body"]["model"], "openai/gpt-5.4")
            self.assertEqual(call[2]["json_body"]["stream"], False)
            self.assertNotIn("gateway-secret-canary", json.dumps(call[2]["json_body"]))
            self.assertEqual(runtime.get_status("run_vercel").status.value, "completed")
            self.assertEqual(len(tuple(runtime.stream_events("run_vercel"))), 2)

    def test_gateway_certainty_semantics_fail_closed(self):
        cases = (
            (response({"error": "bad request"}, 400), None, "rejected"),
            (response({"error": "busy"}, 503), None, "unknown"),
            (response({"choices": []}), None, "unknown"),
            (
                response(
                    {
                        "choices": [{"message": {"content": "result"}}],
                        "usage": {
                            "prompt_tokens": 3,
                            "completion_tokens": 2,
                            "total_tokens": 99,
                        },
                    }
                ),
                None,
                "unknown",
            ),
            (None, VercelInfrastructureError("vercel.request_unknown"), "unknown"),
        )
        for provider_response, error, expected in cases:
            with self.subTest(expected=expected), TemporaryDirectory() as temporary:
                root = Path(temporary)
                configure(root)
                outcome = VercelRuntime(
                    root,
                    requester=Requester(provider_response, error),
                    environment={"AI_GATEWAY_API_KEY": "gateway-secret-canary"},  # pragma: allowlist secret
                ).submit_task(task(), context())
                self.assertEqual(outcome.disposition.value, expected)

    def test_gateway_rejects_surrogates_and_results_over_the_durable_byte_budget(self):
        cases = (
            ("unpaired-surrogate", "\ud800"),
            ("unicode-byte-budget", "😀" * 20_000),
            (
                "redaction-expands-canonical-envelope",
                "😀" * 2_200 + " " + " ".join(["token=x"] * 356),
            ),
        )
        for name, content in cases:
            with self.subTest(name=name), TemporaryDirectory() as temporary:
                root = Path(temporary)
                configure(root)
                runtime = VercelRuntime(
                    root,
                    requester=Requester(
                        response(
                            {
                                "id": "provider_private_identifier",
                                "choices": [{"message": {"content": content}}],
                            }
                        )
                    ),
                    environment={"AI_GATEWAY_API_KEY": "gateway-secret-canary"},  # pragma: allowlist secret
                )
                outcome = runtime.submit_task(task(), context())
                self.assertEqual(outcome.disposition, SubmissionDisposition.UNKNOWN)
                self.assertEqual(
                    outcome.failure_code,
                    "vercel.gateway_response_unknown",
                )
                with self.assertRaises(AgentRuntimeError):
                    runtime.get_status("run_vercel")

    def test_gateway_rejects_non_ascii_provider_identifier_without_escaping(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            configure(root)
            runtime = VercelRuntime(
                root,
                requester=Requester(
                    response(
                        {
                            "id": "provider\ud800identifier",
                            "choices": [
                                {"message": {"content": "Completed safely."}}
                            ],
                        }
                    )
                ),
                environment={"AI_GATEWAY_API_KEY": "gateway-secret-canary"},  # pragma: allowlist secret
            )
            outcome = runtime.submit_task(task(), context())
            self.assertEqual(outcome.disposition, SubmissionDisposition.UNKNOWN)
            self.assertEqual(
                outcome.failure_code,
                "vercel.gateway_response_unknown",
            )
            with self.assertRaises(AgentRuntimeError):
                runtime.get_status("run_vercel")

    def test_gateway_traceback_scrubs_credential_and_raw_response(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            configure(root)
            clock = RetainingClock()
            runtime = VercelRuntime(
                root,
                requester=Requester(
                    response(
                        {
                            "id": "provider_private_identifier",
                            "choices": [
                                {"message": {"content": "Completed safely."}}
                            ],
                            "raw_private": RAW_PROVIDER_SECRET_CANARY,
                        }
                    )
                ),
                environment={"AI_GATEWAY_API_KEY": GATEWAY_SECRET_CANARY},
                clock=clock,
            )
            outcome = runtime.submit_task(task(), context())
            self.assertEqual(outcome.disposition, SubmissionDisposition.UNKNOWN)
            self.assertIsNotNone(clock.error)
            graph = exception_graph_text(clock.error)
            self.assertNotIn(GATEWAY_SECRET_CANARY, graph)
            self.assertNotIn(RAW_PROVIDER_SECRET_CANARY, graph)

    def test_missing_auth_and_disconnected_binding_do_not_call_gateway(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            configure(root)
            requester = Requester(response({}))
            outcome = VercelRuntime(
                root, requester=requester, environment={}
            ).submit_task(task(), context())
            self.assertEqual(outcome.disposition.value, "rejected")
            self.assertEqual(outcome.failure_code, "vercel.gateway_auth_required")
            self.assertEqual(requester.calls, [])

    def test_orchestration_persists_gateway_message_usage_and_terminal_evidence(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            configure(root)
            agent_preview = preview_create_vercel_agent(root, name="Vercel Agent")
            agent = confirm_create_vercel_agent(
                root, agent_preview, agent_preview.confirmation_token
            )
            task_document = {
                "id": "task_vercel",
                "title": "Vercel task",
                "description": "Return the exact result.",
                "project": "Mentat",
                "status": "todo",
                "priority": "medium",
                "assignee": None,
                "assigned_agent_id": agent.id,
                "due_date": None,
                "source": "test",
                "tags": ["dispatch"],
                "required_capabilities": ["model.generate"],
                "acceptance_criteria": ["Return one result."],
                "review_required": False,
                "needs_attention": False,
                "created_at": "2026-08-23T00:00:00+00:00",
                "updated_at": "2026-08-23T00:00:00+00:00",
                "completed_at": None,
            }
            source = root / "tasks.json"
            source.write_text(json.dumps([task_document]) + "\n", encoding="utf-8")
            source.chmod(0o600)
            ensure_run_sqlite_authority(root, history_path(root))
            requester = Requester(
                response(
                    {
                        "id": "provider-secret-reference",
                        "choices": [{"message": {"content": "Canonical result"}}],
                        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
                        "raw_secret": "provider-payload-canary",  # pragma: allowlist secret
                    }
                )
            )
            runtime = VercelRuntime(
                root,
                requester=requester,
                environment={"AI_GATEWAY_API_KEY": "gateway-secret-canary"},  # pragma: allowlist secret
                clock=lambda: datetime(2026, 8, 23, tzinfo=timezone.utc),
            )
            registry = AgentRegistry(
                root, supported_runtime_types=("codex", "hermes", "vercel")
            )
            identifiers = iter(("dispatch_vercel", "run_vercel"))
            service = OrchestrationService(
                root,
                runtime_registry=AgentRuntimeRegistry((runtime,)),
                agent_registry=registry,
                id_factory=lambda _prefix: next(identifiers),
            )
            result = service.dispatch_task(
                task_id="task_vercel",
                expected_revision=1,
                idempotency_key="vercel-dispatch-key-1",
            )
            self.assertEqual(result.run.status, "completed")
            connection = __import__("mentat_db").connect(root)
            try:
                repository = RunRepository(connection)
                events, reset, cursor = repository.list_events("run_vercel")
                self.assertFalse(reset)
                self.assertEqual(
                    [event.type for event in events],
                    [
                        AgentEventType.DISPATCH_RESERVED,
                        AgentEventType.RUN_STARTED,
                        AgentEventType.MESSAGE,
                        AgentEventType.COST,
                        AgentEventType.RUN_COMPLETED,
                    ],
                )
                self.assertEqual(events[2].content, "Canonical result")
                self.assertEqual(events[3].metrics["total_tokens"], 6)
                self.assertEqual(cursor, 5)
                dump = "\n".join(connection.iterdump())
                self.assertNotIn("provider-payload-canary", dump)
                self.assertNotIn("provider-secret-reference", dump)
                self.assertNotIn("gateway-secret-canary", dump)
            finally:
                connection.close()
            with patch.object(server, "DATA_DIR", root):
                projected = server.mentat_run_events_payload("run_vercel", 0)
            self.assertEqual(projected["events"][2]["message"], "Canonical result")
            self.assertTrue(
                all(
                    event["message"] is None
                    for index, event in enumerate(projected["events"])
                    if index != 2
                )
            )

    def test_unknown_gateway_run_can_be_confirmed_interrupted_then_disconnected(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            configure(root)
            agent_preview = preview_create_vercel_agent(root, name="Vercel Agent")
            agent = confirm_create_vercel_agent(
                root,
                agent_preview,
                agent_preview.confirmation_token,
            )
            task_document = {
                "id": "task_vercel",
                "title": "Vercel task",
                "description": "Return the exact result.",
                "project": "Mentat",
                "status": "todo",
                "priority": "medium",
                "assignee": None,
                "assigned_agent_id": agent.id,
                "due_date": None,
                "source": "test",
                "tags": ["dispatch"],
                "required_capabilities": ["model.generate"],
                "acceptance_criteria": ["Return one result."],
                "review_required": False,
                "needs_attention": False,
                "created_at": "2026-08-23T00:00:00+00:00",
                "updated_at": "2026-08-23T00:00:00+00:00",
                "completed_at": None,
            }
            source = root / "tasks.json"
            source.write_text(json.dumps([task_document]) + "\n", encoding="utf-8")
            source.chmod(0o600)
            ensure_run_sqlite_authority(root, history_path(root))
            runtime = VercelRuntime(
                root,
                requester=Requester(
                    error=VercelInfrastructureError("vercel.request_timeout")
                ),
                environment={"AI_GATEWAY_API_KEY": "gateway-secret-canary"},  # pragma: allowlist secret
            )
            registry = AgentRegistry(
                root,
                supported_runtime_types=("codex", "hermes", "vercel"),
            )
            identifiers = iter(("dispatch_vercel_unknown", "run_vercel_unknown"))
            result = OrchestrationService(
                root,
                runtime_registry=AgentRuntimeRegistry((runtime,)),
                agent_registry=registry,
                id_factory=lambda _prefix: next(identifiers),
            ).dispatch_task(
                task_id="task_vercel",
                expected_revision=1,
                idempotency_key="vercel-dispatch-unknown-1",
            )
            self.assertEqual(result.run.status, "unknown")

            reopened = __import__("mentat_db").connect(root)
            try:
                self.assertEqual(
                    RunRepository(reopened).get_run("run_vercel_unknown").status,
                    "unknown",
                )
            finally:
                reopened.close()

            recovery = preview_abandon_vercel_run(
                root,
                run_id="run_vercel_unknown",
            )
            self.assertEqual(recovery.public_summary()["change"]["retry"], False)
            recovered = confirm_abandon_vercel_run(
                root,
                recovery,
                recovery.confirmation_token,
            )
            self.assertEqual(recovered.status, "interrupted")
            self.assertTrue(recovered.partial)

            disconnect = preview_disconnect_vercel(root)
            disconnected = confirm_disconnect_vercel(
                root,
                disconnect,
                disconnect.confirmation_token,
            )
            self.assertEqual(disconnected.state, "disconnected")
            self.assertEqual(load_vercel_connection(root).state, "disconnected")
            self.assertEqual(len(runtime.requester.calls), 1)


if __name__ == "__main__":
    unittest.main()
