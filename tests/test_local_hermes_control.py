from __future__ import annotations

from io import StringIO
import json
import os
from pathlib import Path
from queue import Empty, Queue
import signal
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock, patch

import agent_run_history
import hermes_local_control
from hermes_local_control import (
    LocalHermesControlClient,
    LocalHermesControlError,
    LocalHermesTerminal,
)
from hermes_transport import LocalHermesConsoleTransport, TransportBinding
import server


class _FakeProcess:
    def __init__(self):
        self.pid = 9_999_991
        self.stdout = StringIO("")
        self.stderr = StringIO("")
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class _ScriptedConnection:
    def __init__(
        self,
        *,
        redirect_status="redirected",
        redirect_text=None,
        redirect_error_code=None,
        create_result=None,
        resume_result=None,
    ):
        self.redirect_status = redirect_status
        self.redirect_text = redirect_text
        self.redirect_error_code = redirect_error_code
        self.create_result = create_result
        self.resume_result = resume_result
        self.incoming: Queue[str | None] = Queue()
        self.requests: list[dict] = []
        self.closed = False
        self.incoming.put(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "event",
                    "params": {"type": "gateway.ready", "session_id": ""},
                }
            )
        )

    def send(self, raw):
        request = json.loads(raw)
        self.requests.append(request)
        method = request["method"]
        params = request["params"]
        if method == "session.redirect" and not params.get("text"):
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {"code": 4002, "message": "text is required"},
            }
        elif method == "session.create":
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": self.create_result
                if self.create_result is not None
                else {
                    "session_id": "live1234",
                    "stored_session_id": "stored-session",
                },
            }
        elif method == "session.resume":
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": self.resume_result
                if self.resume_result is not None
                else {
                    "session_id": "live5678",
                    "resumed": params["session_id"],
                    "session_key": params["session_id"],
                },
            }
        elif method == "image.attach":
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"attached": True},
            }
        elif method == "prompt.submit":
            response = {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"status": "streaming"},
            }
        elif method == "session.redirect":
            if self.redirect_error_code is not None:
                response = {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {
                        "code": self.redirect_error_code,
                        "message": "redirect failed",
                    },
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {
                        "status": self.redirect_status,
                        "text": (
                            params["text"]
                            if self.redirect_text is None
                            else self.redirect_text
                        ),
                    },
                }
        else:
            raise AssertionError(f"unexpected method: {method}")
        self.incoming.put(json.dumps(response))
        if method == "prompt.submit":
            self.event("message.start", params["session_id"])

    def recv(self, timeout=None):
        try:
            value = self.incoming.get(timeout=timeout)
        except Empty as exc:
            raise TimeoutError from exc
        if value is None:
            raise ConnectionError("closed")
        return value

    def close(self):
        self.closed = True
        self.incoming.put(None)

    def event(self, event_type, session_id, payload=None):
        params = {"type": event_type, "session_id": session_id}
        if payload is not None:
            params["payload"] = payload
        self.incoming.put(
            json.dumps(
                {"jsonrpc": "2.0", "method": "event", "params": params}
            )
        )


class LocalHermesControlProtocolTests(unittest.TestCase):
    def client(self, root: Path, connection: _ScriptedConnection):
        command_path = root / "hermes"
        command_path.write_text("placeholder", encoding="utf-8")
        launch: dict = {}

        def popen(command, **kwargs):
            launch.update(command=command, kwargs=kwargs)
            ready_path = Path(kwargs["env"]["HERMES_DESKTOP_READY_FILE"])
            ready_path.write_text('{"port":43123}', encoding="utf-8")
            return _FakeProcess()

        def connect(uri, **kwargs):
            launch.update(uri=uri, connect_kwargs=kwargs)
            return connection

        client = LocalHermesControlClient(
            command_path=str(command_path.resolve()),
            profile_id="default",
            hermes_home=(root / "hermes-home").resolve(),
            cwd=root.resolve(),
            runtime_root=(root / "runtime").resolve(),
            popen_factory=popen,
            connect_factory=connect,
            startup_timeout_seconds=1,
            request_timeout_seconds=1,
        )
        return client, launch

    def test_fixed_authenticated_protocol_steers_only_after_message_start(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = _ScriptedConnection()
            client, launch = self.client(root, connection)
            try:
                client.start()
                self.assertEqual(
                    launch["command"],
                    [
                        str((root / "hermes").resolve()),
                        "-p",
                        "default",
                        "serve",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "0",
                        "--isolated",
                    ],
                )
                token = launch["kwargs"]["env"]["HERMES_DASHBOARD_SESSION_TOKEN"]
                self.assertTrue(token)
                self.assertNotIn(token, launch["command"])
                self.assertTrue(launch["uri"].startswith("ws://127.0.0.1:43123/api/ws?token="))
                self.assertEqual(launch["connect_kwargs"]["proxy"], None)

                live_id, durable_id = client.open_session(None)
                self.assertEqual((live_id, durable_id), ("live1234", "stored-session"))
                self.assertFalse(client.can_steer(live_id))
                client.submit_prompt(live_id, "Research the game")
                deadline = time.monotonic() + 1
                while not client.can_steer(live_id) and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(client.can_steer(live_id))

                client.redirect(live_id, "Check BigFry")
                connection.event(
                    "message.complete",
                    live_id,
                    {
                        "status": "complete",
                        "text": "A concise report.",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 5,
                            "total_tokens": 15,
                        },
                    },
                )
                terminal = client.wait_terminal()
                self.assertEqual(terminal.status, "completed")
                self.assertEqual(terminal.text, "A concise report.")
                self.assertFalse(client.can_steer(live_id))
            finally:
                client.close()

    def test_queued_redirect_is_uncertain_not_success(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = _ScriptedConnection(redirect_status="queued")
            client, _launch = self.client(root, connection)
            try:
                client.start()
                live_id, _durable_id = client.open_session(None)
                client.submit_prompt(live_id, "Research the game")
                deadline = time.monotonic() + 1
                while not client.can_steer(live_id) and time.monotonic() < deadline:
                    time.sleep(0.01)
                with self.assertRaises(LocalHermesControlError) as raised:
                    client.redirect(live_id, "Check BigFry")
                self.assertTrue(raised.exception.uncertain)
                self.assertEqual(
                    raised.exception.code,
                    "local_control_steer_unverified",
                )
            finally:
                client.close()

    def test_malformed_receipt_and_runtime_error_are_uncertain(self):
        scenarios = (
            _ScriptedConnection(redirect_text="different text"),
            _ScriptedConnection(redirect_error_code=5000),
        )
        for connection in scenarios:
            with self.subTest(connection=connection.__dict__):
                with TemporaryDirectory() as tmpdir:
                    root = Path(tmpdir)
                    client, _launch = self.client(root, connection)
                    try:
                        client.start()
                        live_id, _durable_id = client.open_session(None)
                        client.submit_prompt(live_id, "Research the game")
                        deadline = time.monotonic() + 1
                        while (
                            not client.can_steer(live_id)
                            and time.monotonic() < deadline
                        ):
                            time.sleep(0.01)
                        with self.assertRaises(LocalHermesControlError) as raised:
                            client.redirect(live_id, "Check BigFry")
                        self.assertTrue(raised.exception.uncertain)
                        self.assertEqual(
                            raised.exception.code,
                            "local_control_steer_unverified",
                        )
                    finally:
                        client.close()

    def test_ready_file_is_exact_bounded_and_loopback_only(self):
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "ready.json"
            path.write_text('{"port":43123}', encoding="utf-8")
            self.assertEqual(LocalHermesControlClient._read_ready_port(path), 43123)
            for raw in ('{"port":0}', '{"port":43123,"host":"0.0.0.0"}', "x" * 257):
                with self.subTest(raw=raw[:30]):
                    path.write_text(raw, encoding="utf-8")
                    with self.assertRaises((ValueError, json.JSONDecodeError)):
                        LocalHermesControlClient._read_ready_port(path)

    def test_resume_requires_exact_string_continuity_receipt(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = _ScriptedConnection(
                create_result={"session_id": 123, "stored_session_id": 456}
            )
            client, _launch = self.client(root, connection)
            try:
                client.start()
                with self.assertRaisesRegex(
                    LocalHermesControlError,
                    "local_control_protocol_invalid",
                ):
                    client.open_session(None)
            finally:
                client.close()

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            connection = _ScriptedConnection()
            client, _launch = self.client(root, connection)
            try:
                client.start()
                self.assertEqual(
                    client.open_session("stored-session"),
                    ("live5678", "stored-session"),
                )
            finally:
                client.close()

        invalid_results = (
            {"session_id": 123, "resumed": "stored-session", "session_key": "stored-session"},
            {"session_id": "live5678", "resumed": 456, "session_key": 456},
            {"session_id": "live5678", "resumed": "stored-session", "session_key": "other-session"},
            {"session_id": "live5678", "resumed": "stored-session"},
        )
        for result in invalid_results:
            with self.subTest(result=result), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                connection = _ScriptedConnection(resume_result=result)
                client, _launch = self.client(root, connection)
                try:
                    client.start()
                    with self.assertRaisesRegex(
                        LocalHermesControlError,
                        "local_control_protocol_invalid",
                    ):
                        client.open_session("stored-session")
                finally:
                    client.close()

    @unittest.skipUnless(os.name == "posix", "symlink regression is POSIX-specific")
    def test_runtime_root_symlink_is_rejected_without_touching_target(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            command_path = root / "hermes"
            command_path.write_text("placeholder", encoding="utf-8")
            victim = root / "outside"
            victim.mkdir(mode=0o755)
            runtime_link = root / "runtime-link"
            runtime_link.symlink_to(victim, target_is_directory=True)
            client = LocalHermesControlClient(
                command_path=str(command_path.resolve()),
                profile_id="default",
                hermes_home=(root / "hermes-home").resolve(),
                cwd=root.resolve(),
                runtime_root=runtime_link.absolute(),
                popen_factory=Mock(side_effect=AssertionError("must not spawn")),
                startup_timeout_seconds=1,
                request_timeout_seconds=1,
            )

            with self.assertRaisesRegex(
                LocalHermesControlError,
                "local_control_storage_unsafe",
            ):
                client.start()

            self.assertEqual(victim.stat().st_mode & 0o777, 0o755)

    def test_process_tree_cleanup_always_escalates_owned_posix_group(self):
        process = _FakeProcess()
        process._mentat_process_group = process.pid
        signals: list[tuple[int, signal.Signals]] = []

        with patch.object(
            hermes_local_control.os,
            "killpg",
            side_effect=lambda pid, sig: signals.append((pid, sig)),
        ):
            LocalHermesControlClient._terminate_process(process)

        self.assertEqual(
            signals,
            [
                (process.pid, signal.SIGTERM),
                (process.pid, signal.SIGKILL),
            ],
        )

    def test_windows_cleanup_closes_kill_on_close_job(self):
        process = _FakeProcess()
        process._mentat_windows_job = object()
        fake_os = SimpleNamespace(name="nt")
        with (
            patch.object(hermes_local_control, "os", fake_os),
            patch.object(hermes_local_control, "_close_windows_job") as close_job,
        ):
            LocalHermesControlClient._terminate_process(process)

        close_job.assert_called_once()
        self.assertIsNone(process._mentat_windows_job)


class _BoundLocalClient(LocalHermesControlClient):
    def __init__(self, *, error: LocalHermesControlError | None = None):
        self.error = error
        self.steered: list[tuple[str, str]] = []
        self.active = True

    @property
    def process(self):
        return None

    def can_steer(self, session_id):
        return self.active and session_id == "live-session"

    def redirect(self, session_id, text):
        if self.error is not None:
            raise self.error
        self.steered.append((session_id, text))

    def close(self):
        self.active = False


class _ControlledRunClient(LocalHermesControlClient):
    def __init__(
        self,
        event_callback,
        *,
        start_error=None,
        submit_error=None,
        terminal_hook=None,
    ):
        self.event_callback = event_callback
        self.start_error = start_error
        self.submit_error = submit_error
        self.terminal_hook = terminal_hook
        self.active = False
        self.closed = False
        self.submissions: list[tuple[str, str]] = []
        self._process = _FakeProcess()

    @property
    def process(self):
        return self._process

    def start(self):
        if self.start_error is not None:
            raise self.start_error
        return None

    def open_session(self, resume_session_id):
        return "live-session", resume_session_id or "stored-session"

    def attach_image(self, session_id, image_path):
        return None

    def submit_prompt(self, session_id, text):
        self.submissions.append((session_id, text))
        if self.submit_error is not None:
            raise self.submit_error
        self.active = True
        self.event_callback(
            {
                "type": "message.start",
                "session_id": session_id,
                "payload": {},
            }
        )

    def can_steer(self, session_id):
        return self.active and session_id == "live-session"

    def wait_terminal(self, *, should_abort=None):
        if self.terminal_hook is not None:
            self.terminal_hook()
        self.active = False
        self.event_callback(
            {
                "type": "message.complete",
                "session_id": "live-session",
                "payload": {"status": "complete"},
            }
        )
        return LocalHermesTerminal(
            status="completed",
            text="Hermes report",
            usage={
                "input_tokens": 8,
                "output_tokens": 4,
                "total_tokens": 12,
            },
        )

    def close(self):
        self.closed = True
        self.active = False
        self._process.terminate()


class _BlockingStartClient(_ControlledRunClient):
    def __init__(self, event_callback):
        super().__init__(event_callback)
        self.start_entered = threading.Event()
        self.start_release = threading.Event()

    def start(self):
        self.start_entered.set()
        self.start_release.wait(timeout=3)

    def close(self):
        super().close()
        self.start_release.set()


class LocalHermesSteerServerTests(unittest.TestCase):
    def setUp(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()

    def active_run(self, client):
        run = {
            "id": "run_local_steer",
            "agent_id": "default",
            "agent_name": "default",
            "transport_mode": "local",
            "connection_binding_id": "local-default",
            "prompt": "Original prompt",
            "status": "running",
            "events": [],
            "event_cursor": 0,
            "created_at": "2026-08-27T12:00:00-07:00",
            "updated_at": "2026-08-27T12:00:00-07:00",
            "_local_control_client": client,
            "_local_control_session_id": "live-session",
            "_local_steer_ready": True,
        }
        server.AGENT_CONSOLE_RUNS[run["id"]] = run
        return run

    @staticmethod
    def adapter(root: Path):
        adapter = LocalHermesConsoleTransport(
            TransportBinding("local", "Local Hermes", "local-default"),
            command_path=str(Path(__file__).resolve()),
            hermes_home=root,
            cwd=root,
        )
        return adapter

    @staticmethod
    def controlled_run(run_id: str) -> dict:
        return {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "default",
            "transport_mode": "local",
            "connection_binding_id": "local-default",
            "prompt": "Research the game",
            "status": "running",
            "session_id": None,
            "starts_new_session": False,
            "new_session_state": "pending",
            "events": [],
            "event_cursor": 0,
            "created_at": "2026-08-27T12:00:00-07:00",
            "updated_at": "2026-08-27T12:00:00-07:00",
        }

    def test_local_success_is_exact_revision_bound_and_text_free(self):
        with TemporaryDirectory() as tmpdir:
            client = _BoundLocalClient()
            run = self.active_run(client)
            adapter = self.adapter(Path(tmpdir))
            before = server.agent_console_snapshot(run)
            self.assertTrue(before["controls"]["steer"]["available"])

            with (
                patch.object(server, "hermes_console_transport", return_value=adapter),
                patch.object(adapter, "revalidate"),
                patch.object(server, "persist_agent_console_runs", return_value=True),
            ):
                payload, status = server.steer_remote_console_run(
                    run["id"],
                    {
                        "text": "Check BigFry",
                        "control_revision": 0,
                        "agent_id": "default",
                    },
                )

            self.assertEqual(status, 200)
            self.assertTrue(payload["accepted"])
            self.assertEqual(client.steered, [("live-session", "Check BigFry")])
            self.assertEqual(payload["run"]["controls"]["steer"]["revision"], 1)
            self.assertNotIn("Check BigFry", json.dumps(payload))
            self.assertNotIn(
                "Check BigFry",
                json.dumps(agent_run_history.summarize_run(run)),
            )

    def test_unverified_delivery_is_partial_and_consumes_revision(self):
        with TemporaryDirectory() as tmpdir:
            client = _BoundLocalClient(
                error=LocalHermesControlError(
                    "local_control_request_timeout",
                    uncertain=True,
                )
            )
            run = self.active_run(client)
            adapter = self.adapter(Path(tmpdir))
            with (
                patch.object(server, "hermes_console_transport", return_value=adapter),
                patch.object(adapter, "revalidate"),
                patch.object(server, "persist_agent_console_runs", return_value=True),
            ):
                payload, status = server.steer_remote_console_run(
                    run["id"],
                    {
                        "text": "May have landed",
                        "control_revision": 0,
                        "agent_id": "default",
                    },
                )

            self.assertEqual(status, 502)
            self.assertTrue(payload["partial"])
            self.assertEqual(payload["error_code"], "local_steer_unverified")
            self.assertTrue(run["partial"])
            self.assertEqual(run["_steer_revision"], 1)
            self.assertNotIn("May have landed", json.dumps(payload))

    def test_accepted_delivery_with_failed_persistence_is_partial(self):
        with TemporaryDirectory() as tmpdir:
            client = _BoundLocalClient()
            run = self.active_run(client)
            adapter = self.adapter(Path(tmpdir))
            with (
                patch.object(server, "hermes_console_transport", return_value=adapter),
                patch.object(adapter, "revalidate"),
                patch.object(server, "persist_agent_console_runs", return_value=False),
            ):
                payload, status = server.steer_remote_console_run(
                    run["id"],
                    {
                        "text": "Accepted upstream",
                        "control_revision": 0,
                        "agent_id": "default",
                    },
                )

            self.assertEqual(client.steered, [("live-session", "Accepted upstream")])
            self.assertEqual(status, 502)
            self.assertTrue(payload["partial"])
            self.assertEqual(payload["error_code"], "local_steer_unverified")
            self.assertNotIn("Accepted upstream", json.dumps(payload))

    def test_availability_and_stop_fail_closed_during_control_claim(self):
        client = _BoundLocalClient()
        run = self.active_run(client)
        run["_local_control_claim"] = "local-steer:0:test"
        run["_steer_inflight"] = True
        self.assertFalse(
            server.agent_console_snapshot(run)["controls"]["steer"]["available"]
        )
        with patch.object(server, "persist_agent_console_runs", return_value=True):
            payload, status = server.cancel_agent_console_run(run["id"])
        self.assertEqual(status, 409)
        self.assertIn("verified", payload["error"])
        self.assertEqual(run["status"], "running")

    def test_controlled_run_enables_live_steer_and_projects_terminal_output(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transport = self.adapter(root)
            run = {
                "id": "run_controlled_success",
                "agent_id": "default",
                "agent_name": "default",
                "transport_mode": "local",
                "connection_binding_id": "local-default",
                "prompt": "Research the game",
                "status": "queued",
                "session_id": None,
                "starts_new_session": False,
                "new_session_state": "pending",
                "events": [],
                "event_cursor": 0,
                "created_at": "2026-08-27T12:00:00-07:00",
                "updated_at": "2026-08-27T12:00:00-07:00",
            }
            server.AGENT_CONSOLE_RUNS[run["id"]] = run
            holder = {}

            def open_client(**kwargs):
                client = _ControlledRunClient(
                    kwargs["event_callback"],
                    terminal_hook=lambda: holder.update(
                        steer_available=server.agent_console_snapshot(run)[
                            "controls"
                        ]["steer"]["available"]
                    ),
                )
                holder["client"] = client
                return client

            with (
                patch.object(transport, "revalidate"),
                patch.object(transport, "open_control_client", side_effect=open_client),
                patch.object(server, "persist_agent_console_runs", return_value=True),
                patch.object(server, "collect_agent_console_artifacts", return_value=[]),
                patch.object(server, "cleanup_run_input_directory"),
            ):
                server.run_hermes_agent(run["id"], transport)

            self.assertTrue(holder["steer_available"])
            self.assertTrue(holder["client"].closed)
            self.assertEqual(run["status"], "completed")
            self.assertEqual(run["response"], "Hermes report")
            self.assertEqual(run["session_id"], "stored-session")
            self.assertTrue(run["starts_new_session"])
            self.assertEqual(run["new_session_state"], "started")
            self.assertEqual(
                run["usage"],
                {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
            )
            self.assertFalse(
                server.agent_console_snapshot(run)["controls"]["steer"]["available"]
            )

    def test_uncertain_prompt_submission_never_retries_legacy_transport(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transport = self.adapter(root)
            run = {
                "id": "run_controlled_uncertain",
                "agent_id": "default",
                "agent_name": "default",
                "transport_mode": "local",
                "connection_binding_id": "local-default",
                "prompt": "Research the game",
                "status": "queued",
                "session_id": None,
                "starts_new_session": False,
                "new_session_state": "pending",
                "events": [],
                "event_cursor": 0,
                "created_at": "2026-08-27T12:00:00-07:00",
                "updated_at": "2026-08-27T12:00:00-07:00",
            }
            server.AGENT_CONSOLE_RUNS[run["id"]] = run

            def open_client(**kwargs):
                return _ControlledRunClient(
                    kwargs["event_callback"],
                    submit_error=LocalHermesControlError(
                        "local_control_request_timeout",
                        uncertain=True,
                    ),
                )

            with (
                patch.object(transport, "revalidate"),
                patch.object(transport, "open_control_client", side_effect=open_client),
                patch.object(transport, "spawn_console") as legacy_spawn,
                patch.object(server, "persist_agent_console_runs", return_value=True),
                patch.object(server, "collect_agent_console_artifacts", return_value=[]),
                patch.object(server, "cleanup_run_input_directory"),
            ):
                server.run_hermes_agent(run["id"], transport)

            legacy_spawn.assert_not_called()
            self.assertEqual(run["status"], "failed")
            self.assertTrue(run["partial"])
            self.assertEqual(run["new_session_state"], "failed")

    def test_definite_pre_submit_failure_allows_one_compatibility_fallback(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transport = self.adapter(root)
            run = self.controlled_run("run_controlled_fallback")
            server.AGENT_CONSOLE_RUNS[run["id"]] = run
            holder = {}

            def open_client(**kwargs):
                client = _ControlledRunClient(
                    kwargs["event_callback"],
                    start_error=LocalHermesControlError(
                        "local_control_startup_failed",
                        uncertain=False,
                    ),
                )
                holder["client"] = client
                return client

            with (
                patch.object(transport, "revalidate"),
                patch.object(
                    transport,
                    "open_control_client",
                    side_effect=open_client,
                ),
                patch.object(
                    server, "persist_agent_console_runs", return_value=True
                ),
                patch.object(server, "cleanup_run_input_directory"),
            ):
                handled = server._run_controlled_local_hermes_agent(
                    run["id"],
                    transport,
                    prompt=run["prompt"],
                    session_id=None,
                    profile_id="default",
                    image_path=None,
                    started=time.monotonic(),
                )

            self.assertFalse(handled)
            self.assertTrue(holder["client"].closed)
            self.assertEqual(holder["client"].submissions, [])
            self.assertEqual(run["status"], "running")
            self.assertNotIn("_local_control_client", run)
            self.assertEqual(run["events"][-1]["data"]["steering"], False)

    def test_stop_during_startup_closes_owned_client_before_submission(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transport = self.adapter(root)
            run = self.controlled_run("run_controlled_start_stop")
            server.AGENT_CONSOLE_RUNS[run["id"]] = run
            holder = {}

            def open_client(**kwargs):
                client = _BlockingStartClient(kwargs["event_callback"])
                holder["client"] = client
                return client

            with (
                patch.object(transport, "revalidate"),
                patch.object(
                    transport,
                    "open_control_client",
                    side_effect=open_client,
                ),
                patch.object(
                    server, "persist_agent_console_runs", return_value=True
                ),
                patch.object(server, "cleanup_run_input_directory"),
                patch.object(server, "finalize_agent_console_runtime_event"),
            ):
                worker = threading.Thread(
                    target=server._run_controlled_local_hermes_agent,
                    args=(run["id"], transport),
                    kwargs={
                        "prompt": run["prompt"],
                        "session_id": None,
                        "profile_id": "default",
                        "image_path": None,
                        "started": time.monotonic(),
                    },
                )
                worker.start()
                deadline = time.monotonic() + 2
                while "client" not in holder and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertIn("client", holder)
                client = holder["client"]
                self.assertTrue(client.start_entered.wait(timeout=1))
                payload, status = server.cancel_agent_console_run(run["id"])
                worker.join(timeout=2)

            self.assertEqual(status, 202)
            self.assertTrue(payload["ok"])
            self.assertFalse(worker.is_alive())
            self.assertTrue(client.closed)
            self.assertEqual(client.submissions, [])
            self.assertEqual(run["status"], "cancelled")

    def test_shutdown_during_startup_and_runtime_hook_close_all_owners(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            transport = self.adapter(root)
            run = self.controlled_run("run_controlled_start_shutdown")
            server.AGENT_CONSOLE_RUNS[run["id"]] = run
            holder = {}

            def open_client(**kwargs):
                client = _BlockingStartClient(kwargs["event_callback"])
                holder["client"] = client
                return client

            with (
                patch.object(transport, "revalidate"),
                patch.object(
                    transport,
                    "open_control_client",
                    side_effect=open_client,
                ),
                patch.object(
                    server, "persist_agent_console_runs", return_value=True
                ),
                patch.object(server, "cleanup_run_input_directory"),
                patch.object(server, "finalize_agent_console_runtime_event"),
            ):
                worker = threading.Thread(
                    target=server._run_controlled_local_hermes_agent,
                    args=(run["id"], transport),
                    kwargs={
                        "prompt": run["prompt"],
                        "session_id": None,
                        "profile_id": "default",
                        "image_path": None,
                        "started": time.monotonic(),
                    },
                )
                worker.start()
                deadline = time.monotonic() + 2
                while "client" not in holder and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertIn("client", holder)
                client = holder["client"]
                self.assertTrue(client.start_entered.wait(timeout=1))
                server.stop_agent_console_processes()
                worker.join(timeout=2)

            self.assertFalse(worker.is_alive())
            self.assertTrue(client.closed)
            self.assertEqual(client.submissions, [])
            self.assertEqual(run["status"], "cancelled")

        with (
            patch.object(server, "stop_agent_console_processes") as stop_runs,
            patch.object(server.CODEX_RUNTIME, "close") as close_codex,
        ):
            server.shutdown_agent_runtimes()
        stop_runs.assert_called_once_with()
        close_codex.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
