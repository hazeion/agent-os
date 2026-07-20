from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import agent_run_history
from hermes_transport import (
    HermesTransportError,
    LocalHermesConsoleTransport,
    TransportBinding,
    select_hermes_console_transport,
)
import remote_hermes
import server


SECRET = "transport-test-secret-NEVER-RETURN"


class VerifiedRemote:
    def __init__(self, _endpoint, _api_key):
        pass

    def discover(self):
        return {
            "status": "healthy",
            "liveness": "ok",
            "trusted": True,
            "platform": "hermes-agent",
            "version": "0.18.2",
            "model": "anthropic/claude-test",
            "readiness": {"config": "ok"},
            "capabilities": ["run_submission"],
        }


def select_remote(root: Path, *, label: str = "Remote workshop"):
    payload = {
        "mode": "remote",
        "label": label,
        "endpoint": "https://private-hermes.example",
        "api_key": SECRET,
    }
    preview = remote_hermes.preview_connection(root, payload)
    return remote_hermes.confirm_connection(
        root,
        payload,
        preview.confirmation_token,
        client_factory=VerifiedRemote,
    )


class HermesTransportTests(unittest.TestCase):
    def setUp(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()
        with remote_hermes._PREVIEW_LOCK:
            remote_hermes._PREVIEW_GRANTS.clear()

    def tearDown(self):
        server.AGENT_CONSOLE_RUNS.clear()
        server.AGENT_CONSOLE_PROCESSES.clear()

    def root(self, temporary: str) -> Path:
        root = Path(temporary) / "operator-data"
        root.mkdir(mode=0o700)
        if os.name == "posix":
            root.chmod(0o700)
        return root

    def local_adapter(
        self,
        binding: TransportBinding,
        *,
        popen_factory=None,
    ) -> LocalHermesConsoleTransport:
        return LocalHermesConsoleTransport(
            binding,
            command_path="/opt/hermes/bin/hermes",
            hermes_home=Path("operator-hermes"),
            cwd=Path("mentat-workspace"),
            shared_bin=Path("operator-hermes") / "bin",
            popen_factory=popen_factory,
        )

    def test_local_adapter_preserves_exact_launch_and_process_contract(self):
        binding = TransportBinding("local", "Local Hermes", "local-default")
        process = Mock()
        popen = Mock(return_value=process)
        adapter = self.local_adapter(binding, popen_factory=popen)
        image_path = Path("private-run") / "input.png"
        launch = adapter.build_console_launch(
            profile_id="researcher",
            prompt="Inspect the project",
            session_id="session_1",
            image_path=image_path,
        )

        self.assertEqual(
            launch.command,
            (
                "/opt/hermes/bin/hermes",
                "-p",
                "researcher",
                "chat",
                "-q",
                "Inspect the project",
                "-Q",
                "--source",
                "mentat",
                "--image",
                str(image_path),
                "--resume",
                "session_1",
            ),
        )
        self.assertEqual(launch.env["HERMES_HOME"], str(Path("operator-hermes")))
        self.assertEqual(launch.env["PYTHONUNBUFFERED"], "1")
        self.assertEqual(
            launch.env["PATH"].split(os.pathsep)[0],
            str(Path("operator-hermes") / "bin"),
        )
        self.assertIs(adapter.spawn_console(launch), process)
        self.assertEqual(popen.call_args.args[0], list(launch.command))
        self.assertEqual(popen.call_args.kwargs["cwd"], str(Path("mentat-workspace")))
        self.assertTrue(popen.call_args.kwargs["text"])
        self.assertEqual(popen.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(popen.call_args.kwargs["errors"], "replace")

    def test_selector_is_binding_aware_and_remote_never_builds_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            local_builder = Mock(side_effect=self.local_adapter)
            local = select_hermes_console_transport(
                root,
                local_builder=local_builder,
            )
            self.assertEqual(local.mode, "local")
            local.revalidate(root)
            local_builder.assert_called_once()

            select_remote(root)
            with self.assertRaisesRegex(
                HermesTransportError,
                "transport_binding_changed",
            ):
                local.revalidate(root)

            forbidden_builder = Mock(
                side_effect=AssertionError("local adapter must not be built")
            )
            remote = select_hermes_console_transport(
                root,
                local_builder=forbidden_builder,
            )
            self.assertEqual(remote.mode, "remote")
            self.assertFalse(remote.console_available)
            forbidden_builder.assert_not_called()
            with self.assertRaisesRegex(
                HermesTransportError,
                "remote_console_not_implemented",
            ):
                remote.build_console_launch(
                    profile_id="default",
                    prompt="No fallback",
                    session_id=None,
                    image_path=None,
                )

    def test_remote_console_payload_and_start_never_touch_local_hermes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            select_remote(root)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "hermes_profiles_payload",
                side_effect=AssertionError("local profiles must not be read"),
            ), patch.object(
                server,
                "hermes_command_path",
                side_effect=AssertionError("local CLI must not be resolved"),
            ), patch.object(
                server.subprocess,
                "Popen",
                side_effect=AssertionError("local CLI must not launch"),
            ):
                summary = server.agent_console_payload()
                started, status = server.start_agent_console_run(
                    {"agent_id": "default", "prompt": "Do not run locally"}
                )

            self.assertFalse(summary["local_only"])
            self.assertEqual(summary["agents"], [])
            self.assertEqual(
                summary["transport"]["error_code"],
                "remote_console_not_implemented",
            )
            self.assertEqual(status, 503)
            self.assertEqual(
                started["error_code"],
                "remote_console_not_implemented",
            )
            public = json.dumps({"summary": summary, "started": started})
            self.assertNotIn(SECRET, public)
            self.assertNotIn("private-hermes.example", public)

    def test_unavailable_connection_keeps_active_run_visible(self):
        server.AGENT_CONSOLE_RUNS["run_visible"] = {
            "id": "run_visible",
            "agent_id": "default",
            "agent_name": "default",
            "prompt": "Keep this visible",
            "status": "running",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(
            server,
            "hermes_console_transport",
            side_effect=HermesTransportError("transport_unavailable"),
        ):
            payload = server.agent_console_payload()

        self.assertEqual(payload["active_run_id"], "run_visible")
        self.assertEqual([run["id"] for run in payload["runs"]], ["run_visible"])
        self.assertEqual(payload["transport"]["mode"], "unavailable")

    def test_console_summary_serializes_local_discovery_against_connection_change(self):
        discovery_started = threading.Event()
        release_discovery = threading.Event()
        confirmation_called = threading.Event()
        results = {}

        def slow_profiles():
            discovery_started.set()
            self.assertTrue(release_discovery.wait(2))
            return {
                "status": "available",
                "active_profile": "default",
                "profiles": [{"id": "default", "name": "default"}],
            }

        def confirm(*_args):
            confirmation_called.set()
            return {"ok": True}

        with patch.object(server, "hermes_command_path", return_value="/tmp/hermes"), patch.object(
            server,
            "hermes_profiles_payload",
            side_effect=slow_profiles,
        ), patch.object(
            server,
            "agent_console_model_catalog",
            return_value={"profile_id": "default", "models": []},
        ), patch.object(
            server,
            "agent_console_provider_inventory",
            return_value={"providers": [], "capabilities": {"providers.switch": False}},
        ), patch.object(
            server,
            "confirm_remote_hermes_connection",
            side_effect=confirm,
        ):
            summary_worker = threading.Thread(
                target=lambda: results.setdefault("summary", server.agent_console_payload())
            )
            summary_worker.start()
            self.assertTrue(discovery_started.wait(2))
            self.assertTrue(server.AGENT_CONSOLE_LOCK.acquire(timeout=0.5))
            server.AGENT_CONSOLE_LOCK.release()
            selection_worker = threading.Thread(
                target=lambda: results.setdefault(
                    "selection",
                    server.select_hermes_connection(
                        {
                            "mode": "local",
                            "label": "Local Hermes",
                            "endpoint": None,
                            "api_key": None,
                            "confirmation_token": "test-token",
                        }
                    ),
                )
            )
            selection_worker.start()
            self.assertFalse(confirmation_called.wait(0.1))
            release_discovery.set()
            summary_worker.join(2)
            selection_worker.join(2)

        self.assertFalse(summary_worker.is_alive())
        self.assertFalse(selection_worker.is_alive())
        self.assertTrue(confirmation_called.is_set())
        self.assertTrue(results["summary"]["local_only"])

    def test_active_run_blocks_connection_confirmation_before_mutation(self):
        for run_status in ("queued", "running", "cancelling"):
            with self.subTest(run_status=run_status):
                server.AGENT_CONSOLE_RUNS.clear()
                server.AGENT_CONSOLE_RUNS["run_active"] = {
                    "id": "run_active",
                    "status": run_status,
                }
                with patch.object(
                    server,
                    "confirm_remote_hermes_connection",
                    side_effect=AssertionError("connection mutation must not run"),
                ):
                    payload, status = server.select_hermes_connection({})
                self.assertEqual(status, 409)
                self.assertEqual(payload["error_code"], "connection_change_active_run")
                self.assertEqual(payload["active_run_id"], "run_active")

    def test_start_revalidates_binding_before_queueing_or_binding_attachments(self):
        binding = TransportBinding("local", "Local Hermes", "local-default")
        adapter = self.local_adapter(binding)
        with patch.object(
            adapter,
            "revalidate",
            side_effect=HermesTransportError("transport_binding_changed"),
        ), patch.object(
            server,
            "hermes_console_transport",
            return_value=adapter,
        ), patch.object(
            server,
            "hermes_profiles_payload",
            return_value={
                "status": "available",
                "profiles": [{"id": "default", "name": "default"}],
            },
        ), patch.object(server.threading, "Thread") as worker:
            payload, status = server.start_agent_console_run(
                {"agent_id": "default", "prompt": "Do not queue"}
            )

        self.assertEqual(status, 409)
        self.assertEqual(payload["error_code"], "transport_binding_changed")
        self.assertEqual(server.AGENT_CONSOLE_RUNS, {})
        worker.assert_not_called()

    def test_local_unavailable_keeps_existing_request_validation_order(self):
        binding = TransportBinding("local", "Local Hermes", "local-default")
        adapter = LocalHermesConsoleTransport(
            binding,
            command_path=None,
            hermes_home=Path("operator-hermes"),
            cwd=Path("mentat-workspace"),
            shared_bin=None,
        )
        with patch.object(
            server,
            "hermes_console_transport",
            return_value=adapter,
        ), patch.object(
            server,
            "hermes_profiles_payload",
            return_value={
                "status": "available",
                "profiles": [{"id": "default", "name": "default"}],
            },
        ):
            payload, status = server.start_agent_console_run(
                {"agent_id": "default", "prompt": ""}
            )

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "Prompt is required")

    def test_launch_failure_does_not_expose_private_error_details(self):
        binding = TransportBinding("local", "Local Hermes", "local-default")
        private_detail = f"/Users/private/operator/{SECRET}"
        adapter = self.local_adapter(
            binding,
            popen_factory=Mock(side_effect=OSError(private_detail)),
        )
        run_id = "run_private_launch_failure"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "default",
            "prompt": "Run safely",
            "session_id": None,
            "status": "queued",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "persist_agent_console_runs",
            ), patch.object(
                server,
                "collect_agent_console_artifacts",
            ), patch.object(
                server,
                "cleanup_run_input_directory",
            ):
                server.run_hermes_agent(run_id, adapter)

        public = json.dumps(server.agent_console_snapshot(server.AGENT_CONSOLE_RUNS[run_id]))
        self.assertEqual(
            server.AGENT_CONSOLE_RUNS[run_id]["error"],
            "Hermes could not be started.",
        )
        self.assertNotIn(SECRET, public)
        self.assertNotIn("/Users/private", public)

    def test_run_binding_mismatch_fails_before_revalidation_or_process_launch(self):
        process_factory = Mock()
        adapter = self.local_adapter(
            TransportBinding("local", "Local Hermes", "b" * 32),
            popen_factory=process_factory,
        )
        run_id = "run_wrong_binding"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "default",
            "prompt": "Do not cross bindings",
            "session_id": None,
            "transport_mode": "local",
            "connection_binding_id": "a" * 32,
            "status": "queued",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with patch.object(adapter, "revalidate") as revalidate, patch.object(
            server,
            "persist_agent_console_runs",
        ), patch.object(
            server,
            "cleanup_run_export_directory",
        ), patch.object(
            server,
            "cleanup_run_input_directory",
        ):
            server.run_hermes_agent(run_id, adapter)

        run = server.AGENT_CONSOLE_RUNS[run_id]
        self.assertEqual(run["status"], "failed")
        self.assertIn("connection changed", run["error"].lower())
        revalidate.assert_not_called()
        process_factory.assert_not_called()

    def test_invalid_connection_storage_during_launch_ends_run_safely(self):
        process_factory = Mock()
        adapter = self.local_adapter(
            TransportBinding("local", "Local Hermes", "local-default"),
            popen_factory=process_factory,
        )
        run_id = "run_connection_storage_failure"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "default",
            "prompt": "Fail closed",
            "session_id": None,
            "transport_mode": "local",
            "connection_binding_id": "local-default",
            "status": "queued",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            connection_path = remote_hermes.connection_path(root)
            connection_path.parent.mkdir(parents=True, mode=0o700)
            connection_path.write_text("{", encoding="utf-8")
            if os.name == "posix":
                connection_path.parent.chmod(0o700)
                connection_path.chmod(0o600)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "persist_agent_console_runs",
            ), patch.object(
                server,
                "collect_agent_console_artifacts",
            ), patch.object(
                server,
                "cleanup_run_input_directory",
            ):
                server.run_hermes_agent(run_id, adapter)

        run = server.AGENT_CONSOLE_RUNS[run_id]
        self.assertEqual(run["status"], "failed")
        self.assertEqual(run["error"], "Hermes connection settings are unavailable.")
        process_factory.assert_not_called()

    def test_failed_process_stderr_redacts_private_paths_and_secrets(self):
        process = Mock(returncode=1)
        process.communicate.return_value = (
            "",
            (
                f"/Users/alice/private/hermes/config.yaml api_key={SECRET}\n"
                r"\\server\private-share\secret\config.yaml"
                "\n/srv/operator/config.yaml"
            ),
        )
        adapter = self.local_adapter(
            TransportBinding("local", "Local Hermes", "local-default"),
            popen_factory=Mock(return_value=process),
        )
        run_id = "run_private_stderr"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "default",
            "prompt": "Run safely",
            "session_id": None,
            "transport_mode": "local",
            "connection_binding_id": "local-default",
            "status": "queued",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "persist_agent_console_runs",
            ), patch.object(
                server,
                "collect_agent_console_artifacts",
            ), patch.object(
                server,
                "cleanup_run_input_directory",
            ):
                server.run_hermes_agent(run_id, adapter)

        public = json.dumps(server.agent_console_snapshot(server.AGENT_CONSOLE_RUNS[run_id]))
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "failed")
        self.assertEqual(
            server.AGENT_CONSOLE_RUNS[run_id]["error"],
            "Hermes exited with status 1.",
        )
        self.assertNotIn(SECRET, public)
        self.assertNotIn("/Users/alice", public)
        self.assertNotIn("private-share", public)
        self.assertNotIn("/srv/operator", public)

    def test_failed_process_stdout_fallback_is_sanitized(self):
        process = Mock(returncode=1)
        process.communicate.return_value = (
            f"/Users/alice/private/config api_key={SECRET}",
            "",
        )
        adapter = self.local_adapter(
            TransportBinding("local", "Local Hermes", "local-default"),
            popen_factory=Mock(return_value=process),
        )
        run_id = "run_private_stdout_fallback"
        server.AGENT_CONSOLE_RUNS[run_id] = {
            "id": run_id,
            "agent_id": "default",
            "agent_name": "default",
            "prompt": "Run safely",
            "session_id": None,
            "transport_mode": "local",
            "connection_binding_id": "local-default",
            "status": "queued",
            "events": [],
            "created_at": "2026-07-20T00:00:00-07:00",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = self.root(temporary)
            with patch.object(server, "DATA_DIR", root), patch.object(
                server,
                "persist_agent_console_runs",
            ), patch.object(
                server,
                "collect_agent_console_artifacts",
            ), patch.object(
                server,
                "cleanup_run_input_directory",
            ):
                server.run_hermes_agent(run_id, adapter)

        public = json.dumps(server.agent_console_snapshot(server.AGENT_CONSOLE_RUNS[run_id]))
        self.assertEqual(server.AGENT_CONSOLE_RUNS[run_id]["status"], "failed")
        self.assertEqual(
            server.AGENT_CONSOLE_RUNS[run_id]["error"],
            "Hermes exited with status 1.",
        )
        self.assertNotIn(SECRET, public)
        self.assertNotIn("/Users/alice", public)

    def test_session_resume_requires_exact_current_connection_binding(self):
        adapter = self.local_adapter(
            TransportBinding("local", "Local Hermes", "b" * 32)
        )
        profiles = {
            "status": "available",
            "profiles": [{"id": "default", "name": "default"}],
        }
        cases = (
            {
                "transport_mode": "local",
                "connection_binding_id": "a" * 32,
            },
            {},
        )
        for binding_fields in cases:
            with self.subTest(binding_fields=binding_fields):
                server.AGENT_CONSOLE_RUNS.clear()
                server.AGENT_CONSOLE_RUNS["run_old_session"] = {
                    "id": "run_old_session",
                    "agent_id": "default",
                    "status": "completed",
                    "session_id": "session_old_connection",
                    "created_at": "2026-07-19T00:00:00-07:00",
                    **binding_fields,
                }
                with patch.object(adapter, "revalidate"), patch.object(
                    server,
                    "hermes_console_transport",
                    return_value=adapter,
                ), patch.object(
                    server,
                    "hermes_profiles_payload",
                    return_value=profiles,
                ), patch.object(server.threading, "Thread") as worker:
                    payload, status = server.start_agent_console_run(
                        {
                            "agent_id": "default",
                            "prompt": "Do not cross connections",
                            "session_id": "session_old_connection",
                        }
                    )

                self.assertEqual(status, 409)
                self.assertEqual(payload["error_code"], "session_connection_mismatch")
                worker.assert_not_called()

    def test_transport_binding_round_trips_and_malformed_history_is_skipped(self):
        run = {
            "id": "run_bound",
            "agent_id": "default",
            "agent_name": "default",
            "status": "completed",
            "transport_mode": "local",
            "connection_binding_id": "a" * 32,
        }
        summary = agent_run_history.summarize_run(run)
        self.assertEqual(summary["transport_mode"], "local")
        self.assertEqual(summary["connection_binding_id"], "a" * 32)

        legacy = agent_run_history.summarize_run(
            {"id": "run_legacy", "status": "completed"}
        )
        self.assertEqual(legacy["transport_mode"], "local")
        self.assertEqual(legacy["connection_binding_id"], "local-default")

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "history.json"
            malformed = {
                **summary,
                "transport_mode": "remote",
                "connection_binding_id": "local-default",
            }
            path.write_text(
                json.dumps(
                    {
                        "schema_version": agent_run_history.SCHEMA_VERSION,
                        "runs": [summary, malformed],
                    }
                ),
                encoding="utf-8",
            )
            loaded, recovered = agent_run_history.load_run_summaries(path)
        self.assertFalse(recovered)
        self.assertEqual([item["id"] for item in loaded], ["run_bound"])
        self.assertEqual(loaded[0]["connection_binding_id"], "a" * 32)


if __name__ == "__main__":
    unittest.main()
