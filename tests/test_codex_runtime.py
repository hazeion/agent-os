from __future__ import annotations

from collections import deque
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import textwrap
import threading
import time
import unittest
from unittest.mock import patch

from agent_runtime import (
    AgentEventType,
    AgentRuntimeError,
    MentatTask,
    RunStatus,
    RuntimeCapability,
    RuntimeContext,
    SubmissionDisposition,
)
from codex_runtime import (
    CODEX_DEFAULT_BINDING,
    START_TASK_OPERATION_TIMEOUT_SECONDS,
    CodexAppServerClient,
    CodexAppServerClientError,
    CodexRuntime,
    codex_app_server_command,
    codex_child_environment,
    find_codex_command,
)


THREAD_ID = "0199a213-81c0-7800-8aa1-bbab2a035a53"
TURN_ID = "0199a213-81c0-7800-8aa1-bbab2a035a54"
RUNTIME_REF = f"{THREAD_ID}:{TURN_ID}"
READY_ACCOUNT = {
    "account": {"type": "chatgpt", "email": None, "planType": "plus"},
    "requiresOpenaiAuth": True,
}


class FakeClient:
    def __init__(self, *responses, account_response=READY_ACCOUNT):
        self.responses = deque(responses)
        self.account_response = account_response
        self.calls = []
        self.closed = False

    def request(self, method, params, *, timeout=None):
        self.calls.append((method, params, timeout))
        result = (
            self.account_response
            if method == "account/read"
            else self.responses.popleft()
        )
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


def task() -> MentatTask:
    return MentatTask(
        id="task_codex",
        title="Improve the adapter",
        objective="Implement the requested change safely.",
        assigned_agent_id="agent_codex",
        acceptance_criteria=("Keep tests green.", "Do not expose credentials."),
    )


def context(*, runtime_run_ref=None) -> RuntimeContext:
    return RuntimeContext(
        agent_id="agent_codex",
        runtime_agent_ref=CODEX_DEFAULT_BINDING,
        task_id="task_codex",
        mentat_run_id="run_codex",
        dispatch_id="dispatch_codex",
        runtime_run_ref=runtime_run_ref,
    )


def thread_start(root: Path) -> dict:
    return {
        "approvalPolicy": "never",
        "approvalsReviewer": "user",
        "cwd": str(root.resolve()),
        "model": "gpt-5.6",
        "modelProvider": "openai",
        "reasoningEffort": "high",
        "sandbox": {
            "type": "workspaceWrite",
            # App Server reports cwd as the implicit workspace and reserves
            # writableRoots for additional roots.
            "writableRoots": [],
            "networkAccess": False,
        },
        "thread": {"id": THREAD_ID},
    }


def turn_start(status="inProgress") -> dict:
    return {
        "turn": {
            "id": TURN_ID,
            "status": status,
            "items": [],
            "startedAt": 1787428800,
            "completedAt": None,
        }
    }


def thread_read(*, status="inProgress", items=None) -> dict:
    completed_at = 1787428810 if status != "inProgress" else None
    return {
        "thread": {
            "id": THREAD_ID,
            "status": {"type": "active" if status == "inProgress" else "idle"},
            "turns": [
                {
                    "id": TURN_ID,
                    "status": status,
                    "items": list(items or ()),
                    "startedAt": 1787428800,
                    "completedAt": completed_at,
                }
            ],
        }
    }


class CodexRuntimeTests(unittest.TestCase):
    def runtime(self, root: Path, client: FakeClient) -> CodexRuntime:
        command_path = str((root / "codex.exe").resolve())
        return CodexRuntime(
            workspace_root=root,
            command=codex_app_server_command(command_path),
            client=client,
        )

    def test_fixed_command_and_environment_do_not_forward_credentials(self):
        command_path = str((Path.cwd() / "codex.exe").resolve())
        command = codex_app_server_command(command_path)
        self.assertEqual(command[0], command_path)
        self.assertEqual(command[-2:], ("app-server", "--stdio"))
        self.assertIn('shell_environment_policy.inherit="core"', command)
        self.assertIn("shell_environment_policy.ignore_default_excludes=false", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)

        environment = codex_child_environment(
            {
                "HOME": "/safe/home",
                "PATH": "/safe/bin",
                "CODEX_HOME": "/safe/codex-home",
                "MENTAT_LOCAL_BRIDGE_TOKEN": "bridge-secret",
                "CODEX_API_KEY": "provider-secret",  # pragma: allowlist secret
                "OPENAI_API_KEY": "provider-secret",  # pragma: allowlist secret
                "UNRELATED_PARENT_VALUE": "private-parent-value",
            }
        )
        self.assertEqual(environment["HOME"], "/safe/home")
        self.assertEqual(environment["PATH"], "/safe/bin")
        self.assertEqual(environment["CODEX_HOME"], "/safe/codex-home")
        self.assertEqual(environment["NO_COLOR"], "1")
        for private_name in (
            "MENTAT_LOCAL_BRIDGE_TOKEN",
            "CODEX_API_KEY",
            "OPENAI_API_KEY",
            "UNRELATED_PARENT_VALUE",
        ):
            self.assertNotIn(private_name, environment)

    def test_runtime_rejects_a_non_fixed_command_or_missing_workspace(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            command_path = str((root / "codex.exe").resolve())
            with self.assertRaisesRegex(ValueError, "command is not fixed"):
                CodexRuntime(
                    workspace_root=root,
                    command=(command_path, "exec", "browser-controlled"),
                )
            with self.assertRaisesRegex(ValueError, "workspace root is invalid"):
                CodexRuntime(
                    workspace_root=root / "missing",
                    command=codex_app_server_command(command_path),
                )

    @unittest.skipIf(os.name == "nt", "POSIX executable trust rules")
    def test_discovery_returns_a_resolved_trusted_executable(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "codex"
            executable.write_bytes(b"fixed executable")
            executable.chmod(0o700)
            alias = root / "alias"
            alias.symlink_to(executable)
            discovered = find_codex_command({"PATH": str(root), "HOME": str(root)})
        self.assertEqual(discovered, str(executable.resolve()))

    def test_available_runtime_advertises_only_implemented_capabilities(self):
        with TemporaryDirectory() as temporary:
            runtime = self.runtime(Path(temporary), FakeClient())
        self.assertEqual(runtime.readiness_status(force=True), "ready")
        self.assertEqual(
            runtime.capabilities,
            frozenset(
                {
                    RuntimeCapability.START_TASK.value,
                    RuntimeCapability.STATUS.value,
                    RuntimeCapability.EVENTS.value,
                    RuntimeCapability.SEND_MESSAGE.value,
                    RuntimeCapability.STOP.value,
                }
            ),
        )
        self.assertNotIn(RuntimeCapability.APPROVAL_RESPONSE.value, runtime.capabilities)
        self.assertNotIn(RuntimeCapability.ATTACHMENTS.value, runtime.capabilities)
        runtime.validate_agent_binding(
            CODEX_DEFAULT_BINDING,
            [RuntimeCapability.START_TASK.value],
        )
        with self.assertRaisesRegex(AgentRuntimeError, "runtime.binding_invalid"):
            runtime.validate_agent_binding("other", [])
        with self.assertRaisesRegex(AgentRuntimeError, "runtime.binding_invalid"):
            runtime.validate_agent_binding(CODEX_DEFAULT_BINDING, ["provider.login"])

    def test_runtime_fails_closed_when_protocol_or_account_is_not_ready(self):
        failures = (
            {"account": None, "requiresOpenaiAuth": True},
            {"account": {"type": "chatgpt"}},
            {
                "account": {"type": "unsupported-account"},
                "requiresOpenaiAuth": True,
            },
            CodexAppServerClientError("codex.protocol_invalid", uncertain=False),
        )
        for failure in failures:
            with self.subTest(failure=failure), TemporaryDirectory() as temporary:
                runtime = self.runtime(
                    Path(temporary), FakeClient(account_response=failure)
                )
                expected = (
                    "sign_in_required"
                    if failure == {"account": None, "requiresOpenaiAuth": True}
                    else "unavailable"
                )
                self.assertEqual(runtime.readiness_status(force=True), expected)
                self.assertEqual(runtime.capabilities, frozenset())
                with self.assertRaisesRegex(
                    AgentRuntimeError, "runtime.binding_invalid"
                ):
                    runtime.validate_agent_binding(CODEX_DEFAULT_BINDING, [])

    def test_unavailable_runtime_advertises_no_capabilities(self):
        with TemporaryDirectory() as temporary:
            runtime = CodexRuntime(workspace_root=Path(temporary), command=None)
        self.assertEqual(runtime.readiness_status(force=True), "cli_missing")
        self.assertEqual(runtime.capabilities, frozenset())
        with self.assertRaisesRegex(AgentRuntimeError, "runtime.binding_invalid"):
            runtime.validate_agent_binding(CODEX_DEFAULT_BINDING, [])

    def test_submit_starts_one_bound_thread_and_turn(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            client = FakeClient(thread_start(root), turn_start())
            outcome = self.runtime(root, client).submit_task(task(), context())

        self.assertEqual(outcome.disposition, SubmissionDisposition.ACCEPTED)
        self.assertEqual(outcome.runtime_run_ref, RUNTIME_REF)
        self.assertEqual(outcome.run.id, "run_codex")
        self.assertEqual(outcome.run.task_id, "task_codex")
        self.assertEqual(outcome.run.agent_id, "agent_codex")
        self.assertEqual(outcome.run.runtime_type, "codex")
        self.assertEqual(outcome.run.status, RunStatus.RUNNING)
        self.assertEqual(
            dict(outcome.execution_identity),
            {
                "model": "gpt-5.6",
                "provider": "openai",
                "reasoning_effort": "high",
                "verification": "runtime_response",
            },
        )
        self.assertEqual(
            [call[0] for call in client.calls],
            ["account/read", "thread/start", "turn/start"],
        )
        self.assertEqual(
            client.calls[1][1],
            {
                "approvalPolicy": "never",
                "cwd": str(root),
                "ephemeral": False,
                "sandbox": "workspace-write",
                "serviceName": "mentat",
            },
        )
        self.assertEqual(
            client.calls[2][1]["sandboxPolicy"],
            {
                "type": "workspaceWrite",
                "writableRoots": [str(root)],
                "networkAccess": False,
            },
        )
        self.assertEqual(client.calls[2][1]["cwd"], str(root))
        self.assertEqual(client.calls[2][1]["approvalPolicy"], "never")
        self.assertGreater(client.calls[1][2], 0)
        self.assertLessEqual(client.calls[1][2], START_TASK_OPERATION_TIMEOUT_SECONDS)
        self.assertGreater(client.calls[2][2], 0)
        self.assertLessEqual(client.calls[2][2], client.calls[1][2])
        prompt = client.calls[2][1]["input"][0]
        self.assertEqual(prompt["type"], "text")
        self.assertIn(task().objective, prompt["text"])
        self.assertIn("Keep tests green.", prompt["text"])
        self.assertNotIn(str(root), prompt["text"])

    def test_submit_rejects_wrong_binding_before_protocol_io(self):
        client = FakeClient()
        with TemporaryDirectory() as temporary:
            runtime = self.runtime(Path(temporary), client)
            wrong = RuntimeContext(
                agent_id="agent_codex",
                runtime_agent_ref="browser-selected-profile",
                task_id="task_codex",
                mentat_run_id="run_codex",
                dispatch_id="dispatch_codex",
            )
            outcome = runtime.submit_task(task(), wrong)
        self.assertEqual(outcome.disposition, SubmissionDisposition.REJECTED)
        self.assertEqual(outcome.failure_code, "runtime.binding_invalid")
        self.assertEqual(client.calls, [])

    def test_submit_distinguishes_known_rejection_from_unknown_attempt(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            rejected = self.runtime(
                root,
                FakeClient(CodexAppServerClientError("codex.request_rejected", uncertain=False)),
            ).submit_task(task(), context())
            unknown = self.runtime(
                root,
                FakeClient(CodexAppServerClientError("codex.request_unknown", uncertain=True)),
            ).submit_task(task(), context())
            after_thread = self.runtime(
                root,
                FakeClient(
                    thread_start(root),
                    CodexAppServerClientError("codex.request_rejected", uncertain=False),
                ),
            ).submit_task(task(), context())
        self.assertEqual(rejected.disposition, SubmissionDisposition.REJECTED)
        self.assertEqual(unknown.disposition, SubmissionDisposition.UNKNOWN)
        self.assertEqual(after_thread.disposition, SubmissionDisposition.UNKNOWN)

    def test_submit_fails_unknown_when_effective_thread_boundary_is_not_safe(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            unsafe = thread_start(root)
            unsafe["sandbox"] = {"type": "dangerFullAccess"}
            outcome = self.runtime(root, FakeClient(unsafe)).submit_task(task(), context())
        self.assertEqual(outcome.disposition, SubmissionDisposition.UNKNOWN)
        self.assertEqual(outcome.failure_code, "runtime.start_unverified")

    def test_submit_requires_every_official_thread_safety_field(self):
        required = {
            "approvalPolicy",
            "approvalsReviewer",
            "cwd",
            "model",
            "modelProvider",
            "sandbox",
            "thread",
        }
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for missing in sorted(required):
                with self.subTest(missing=missing):
                    incomplete = thread_start(root)
                    incomplete.pop(missing)
                    client = FakeClient(incomplete)
                    outcome = self.runtime(root, client).submit_task(task(), context())
                    self.assertEqual(
                        outcome.disposition,
                        SubmissionDisposition.UNKNOWN,
                    )
                    self.assertEqual(
                        outcome.failure_code,
                        "runtime.start_unverified",
                    )
                    self.assertEqual(
                        [call[0] for call in client.calls],
                        ["account/read", "thread/start"],
                    )

    def test_submit_rejects_an_optional_read_only_thread_echo(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            downgraded = thread_start(root)
            downgraded["sandbox"] = {"type": "readOnly"}
            outcome = self.runtime(root, FakeClient(downgraded)).submit_task(
                task(), context()
            )
        self.assertEqual(outcome.disposition, SubmissionDisposition.UNKNOWN)
        self.assertEqual(outcome.failure_code, "runtime.start_unverified")

    def test_submit_accepts_only_empty_or_exact_cwd_additional_writable_roots(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            exact = thread_start(root)
            exact["sandbox"]["writableRoots"] = [str(root)]
            accepted = self.runtime(root, FakeClient(exact, turn_start())).submit_task(
                task(), context()
            )

            foreign = thread_start(root)
            foreign["sandbox"]["writableRoots"] = [str(root.parent)]
            rejected = self.runtime(root, FakeClient(foreign)).submit_task(
                task(), context()
            )

        self.assertEqual(accepted.disposition, SubmissionDisposition.ACCEPTED)
        self.assertEqual(rejected.disposition, SubmissionDisposition.UNKNOWN)
        self.assertEqual(rejected.failure_code, "runtime.start_unverified")

    def test_close_is_permanent_and_cannot_respawn_a_client(self):
        factory_started = threading.Event()
        release_factory = threading.Event()
        created: list[FakeClient] = []

        def factory(**_kwargs):
            factory_started.set()
            release_factory.wait(timeout=2)
            client = FakeClient()
            created.append(client)
            return client

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = CodexRuntime(
                workspace_root=root,
                command=codex_app_server_command(
                    str((root / "codex.exe").resolve())
                ),
                client_factory=factory,
            )
            request_thread = threading.Thread(target=runtime._require_client)
            request_thread.start()
            self.assertTrue(factory_started.wait(timeout=1))
            close_thread = threading.Thread(target=runtime.close)
            close_thread.start()
            release_factory.set()
            request_thread.join(timeout=2)
            close_thread.join(timeout=2)

            self.assertFalse(request_thread.is_alive())
            self.assertFalse(close_thread.is_alive())
            self.assertEqual(len(created), 1)
            self.assertTrue(created[0].closed)
            self.assertEqual(runtime.capabilities, frozenset())
            with self.assertRaises(CodexAppServerClientError):
                runtime._require_client()
            self.assertEqual(len(created), 1)

    def test_status_maps_only_the_exact_private_thread_and_turn(self):
        expected = {
            "inProgress": RunStatus.RUNNING,
            "completed": RunStatus.COMPLETED,
            "interrupted": RunStatus.STOPPED,
            "failed": RunStatus.FAILED,
        }
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            for source, status in expected.items():
                with self.subTest(source=source):
                    runtime = self.runtime(root, FakeClient(thread_read(status=source)))
                    observed = runtime.get_status(RUNTIME_REF, context=context(runtime_run_ref=RUNTIME_REF))
                    self.assertEqual(observed.id, "run_codex")
                    self.assertEqual(observed.status, status)

    def test_status_rejects_runtime_reference_or_context_mismatch(self):
        with TemporaryDirectory() as temporary:
            runtime = self.runtime(Path(temporary), FakeClient())
            with self.assertRaisesRegex(AgentRuntimeError, "runtime.identity_context_required"):
                runtime.get_status(RUNTIME_REF)
            with self.assertRaisesRegex(AgentRuntimeError, "runtime.identity_mismatch"):
                runtime.get_status(RUNTIME_REF, context=context(runtime_run_ref="other:turn"))

    def test_events_are_bounded_private_and_deterministic(self):
        items = [
            {"id": "item.message:1", "type": "agentMessage", "text": "token=private /Users/alice/work"},
            {
                "id": "item_command",
                "type": "commandExecution",
                "status": "completed",
                "command": "read /Users/alice/private",
                "aggregatedOutput": "provider-secret",
            },
            {
                "id": "item_file",
                "type": "fileChange",
                "status": "completed",
                "changes": [{"path": "/Users/alice/private"}],
            },
        ]
        with TemporaryDirectory() as temporary:
            runtime = self.runtime(
                Path(temporary),
                FakeClient(thread_read(status="completed", items=items), thread_read(status="completed", items=items)),
            )
            first = tuple(runtime.stream_events(RUNTIME_REF, context=context(runtime_run_ref=RUNTIME_REF)))
            later = tuple(runtime.stream_events(RUNTIME_REF, 3, context=context(runtime_run_ref=RUNTIME_REF)))

        self.assertEqual([event.sequence for event in first], [1, 2, 3, 4, 5])
        self.assertEqual(
            [event.type for event in first],
            [
                AgentEventType.RUN_STARTED,
                AgentEventType.MESSAGE,
                AgentEventType.TOOL_COMPLETED,
                AgentEventType.ARTIFACT_CREATED,
                AgentEventType.RUN_COMPLETED,
            ],
        )
        self.assertEqual(later, first[3:])
        public_text = repr(first)
        for private in ("provider-secret", "/Users/alice", "token=private"):
            self.assertNotIn(private, public_text)
        self.assertTrue(all(event.content is None for event in first))

    def test_events_stop_at_first_unstable_item_to_remain_append_only(self):
        active_items = [
            {"id": "item_message", "type": "agentMessage", "text": "Ready"},
            {"id": "item_command", "type": "commandExecution", "status": "inProgress", "command": "test"},
            {"id": "item_later", "type": "agentMessage", "text": "Not stable yet"},
        ]
        complete_items = [
            active_items[0],
            {**active_items[1], "status": "completed"},
            active_items[2],
        ]
        with TemporaryDirectory() as temporary:
            runtime = self.runtime(
                Path(temporary),
                FakeClient(
                    thread_read(status="inProgress", items=active_items),
                    thread_read(status="completed", items=complete_items),
                ),
            )
            active = tuple(runtime.stream_events(RUNTIME_REF, context=context(runtime_run_ref=RUNTIME_REF)))
            complete = tuple(runtime.stream_events(RUNTIME_REF, context=context(runtime_run_ref=RUNTIME_REF)))
        self.assertEqual([event.sequence for event in active], [1, 2])
        self.assertEqual([event.sequence for event in complete], [1, 2, 3, 4, 5])
        self.assertEqual([event.id for event in active], [event.id for event in complete[:2]])

    def test_message_uses_expected_active_turn_and_never_starts_another_turn(self):
        with TemporaryDirectory() as temporary:
            client = FakeClient({"turnId": TURN_ID})
            runtime = self.runtime(Path(temporary), client)
            runtime.send_message(
                RUNTIME_REF,
                "Focus on the failing test.",
                context=context(runtime_run_ref=RUNTIME_REF),
            )
        self.assertEqual(
            client.calls,
            [
                (
                    "turn/steer",
                    {
                        "threadId": THREAD_ID,
                        "expectedTurnId": TURN_ID,
                        "input": [{"type": "text", "text": "Focus on the failing test."}],
                    },
                    None,
                )
            ],
        )

    def test_stop_interrupts_only_the_exact_turn_and_verifies_terminal_state(self):
        with TemporaryDirectory() as temporary:
            client = FakeClient({}, thread_read(status="interrupted"))
            runtime = self.runtime(Path(temporary), client)
            runtime.stop(RUNTIME_REF, context=context(runtime_run_ref=RUNTIME_REF))
        self.assertEqual(client.calls[0][0], "turn/interrupt")
        self.assertEqual(client.calls[0][1], {"threadId": THREAD_ID, "turnId": TURN_ID})
        self.assertEqual(client.calls[1][0], "thread/read")

    def test_terminal_run_capabilities_remove_message_and_stop(self):
        with TemporaryDirectory() as temporary:
            runtime = self.runtime(Path(temporary), FakeClient(thread_read(status="completed")))
            capabilities = runtime.capabilities_for_run(
                RUNTIME_REF, context=context(runtime_run_ref=RUNTIME_REF)
            )
        self.assertEqual(
            capabilities,
            frozenset({RuntimeCapability.STATUS.value, RuntimeCapability.EVENTS.value}),
        )

    def test_approval_methods_fail_closed_because_capability_is_not_advertised(self):
        with TemporaryDirectory() as temporary:
            runtime = self.runtime(Path(temporary), FakeClient())
            with self.assertRaisesRegex(AgentRuntimeError, "runtime.action_unavailable"):
                runtime.pending_action(RUNTIME_REF, context=context(runtime_run_ref=RUNTIME_REF))


class CodexAppServerClientTests(unittest.TestCase):
    SERVER = textwrap.dedent(
        """
        import json
        import os
        import sys

        def send(value):
            sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\\n")
            sys.stdout.flush()

        for raw in sys.stdin:
            message = json.loads(raw)
            method = message.get("method")
            if method == "initialized":
                continue
            request_id = message.get("id")
            if method == "initialize":
                send({"id": request_id, "result": {"platformFamily": "unix"}})
            elif method == "test/echo":
                send({"method": "thread/status/changed", "params": {"private": "ignored"}})
                send({"id": request_id, "result": message.get("params")})
            elif method == "test/environment":
                send({"id": request_id, "result": {"keys": sorted(os.environ)}})
            elif method == "test/child":
                import subprocess
                import time
                child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
                send({"id": request_id, "result": {"pid": child.pid}})
            elif method == "test/serverRequest":
                send({
                    "id": "approval_1",
                    "method": "item/commandExecution/requestApproval",
                    "params": {"private": "not returned"},
                })
                denial = json.loads(sys.stdin.readline())
                send({"id": request_id, "result": {"denial": denial.get("error", {}).get("code")}})
            elif method == "test/malformed":
                sys.stdout.write("not-json\\n")
                sys.stdout.flush()
            elif method == "test/oversized":
                sys.stdout.write(json.dumps({"padding": "x" * 8192}) + "\\n")
                sys.stdout.flush()
            elif method == "test/timeout":
                continue
            else:
                send({"id": request_id, "error": {"code": -32601, "message": "unknown"}})
        """
    ).lstrip()

    def client(self, root: Path, *, maximum_line_bytes=4096, request_timeout=1.0):
        script = root / "fake_codex_app_server.py"
        script.write_text(self.SERVER, encoding="utf-8")
        environment = codex_child_environment(
            {
                "HOME": str(root),
                "PATH": os.environ.get("PATH", ""),
                "MENTAT_LOCAL_BRIDGE_TOKEN": "must-not-cross",
                "CODEX_API_KEY": "must-not-cross",  # pragma: allowlist secret
            }
        )
        return CodexAppServerClient(
            command=(sys.executable, str(script)),
            cwd=root,
            environment=environment,
            request_timeout=request_timeout,
            maximum_line_bytes=maximum_line_bytes,
        )

    def test_real_stdio_handshake_drains_notifications_and_keeps_environment_private(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = self.client(root)
            try:
                self.assertEqual(client.request("test/echo", {"value": "ok"}), {"value": "ok"})
                environment = client.request("test/environment", {})
            finally:
                client.close()
        keys = set(environment["keys"])
        self.assertIn("HOME", keys)
        self.assertNotIn("MENTAT_LOCAL_BRIDGE_TOKEN", keys)
        self.assertNotIn("CODEX_API_KEY", keys)

    def test_server_initiated_permission_request_is_denied_not_forwarded(self):
        with TemporaryDirectory() as temporary:
            client = self.client(Path(temporary))
            try:
                result = client.request("test/serverRequest", {})
            finally:
                client.close()
        self.assertEqual(result, {"denial": -32601})

    def test_malformed_and_oversized_protocol_lines_fail_bounded(self):
        for method, line_limit in (("test/malformed", 4096), ("test/oversized", 1024)):
            with self.subTest(method=method), TemporaryDirectory() as temporary:
                client = self.client(Path(temporary), maximum_line_bytes=line_limit)
                try:
                    with self.assertRaises(CodexAppServerClientError) as raised:
                        client.request(method, {})
                finally:
                    client.close()
                self.assertTrue(raised.exception.uncertain)
                self.assertIn(
                    raised.exception.code,
                    {"codex.protocol_invalid", "codex.protocol_unavailable"},
                )

    def test_request_timeout_is_unknown_and_shutdown_is_bounded(self):
        with TemporaryDirectory() as temporary:
            client = self.client(Path(temporary), request_timeout=0.2)
            try:
                with self.assertRaises(CodexAppServerClientError) as raised:
                    client.request("test/timeout", {})
            finally:
                client.close()
        self.assertEqual(raised.exception.code, "codex.request_timeout")
        self.assertTrue(raised.exception.uncertain)

    def test_request_timeout_is_one_end_to_end_startup_and_method_budget(self):
        with TemporaryDirectory() as temporary:
            client = CodexAppServerClient(
                command=("codex",),
                cwd=Path(temporary),
                request_timeout=1,
            )
            clock = [100.0]
            observed = []
            startup_timeouts = []

            def ensure_ready(*, timeout):
                startup_timeouts.append(timeout)
                clock[0] += 0.05

            client._ensure_ready = ensure_ready
            client._request_started = (
                lambda method, params, *, timeout: observed.append(timeout) or {}
            )
            with patch("codex_runtime.time", wraps=time) as codex_time:
                codex_time.monotonic.side_effect = lambda: clock[0]
                result = client.request("account/read", {}, timeout=0.25)

        self.assertEqual(result, {})
        self.assertEqual(startup_timeouts, [0.25])
        self.assertEqual(len(observed), 1)
        self.assertAlmostEqual(observed[0], 0.2)

    @unittest.skipIf(os.name == "nt", "POSIX process-group lifecycle check")
    def test_close_terminates_the_owned_app_server_process_tree(self):
        with TemporaryDirectory() as temporary:
            client = self.client(Path(temporary))
            child_pid = client.request("test/child", {})["pid"]
            client.close()

            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("App Server child survived client shutdown")

    @unittest.skipUnless(os.name == "nt", "Windows Job Object lifecycle check")
    def test_windows_close_terminates_the_exact_owned_process_tree(self):
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        with TemporaryDirectory() as temporary:
            client = self.client(Path(temporary))
            child_pid = client.request("test/child", {})["pid"]
            child_handle = kernel32.OpenProcess(0x00100000, False, child_pid)
            self.assertTrue(child_handle)
            try:
                client.close()
                self.assertEqual(kernel32.WaitForSingleObject(child_handle, 5_000), 0)
            finally:
                kernel32.CloseHandle(child_handle)


if __name__ == "__main__":
    unittest.main()
