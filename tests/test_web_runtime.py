from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from mentat import web_runtime
from mentat import local_bridge


class WebRuntimeTests(unittest.TestCase):
    def test_source_and_frozen_bridge_commands_are_fixed_and_secret_free(self):
        source = web_runtime.bridge_command(49152)
        self.assertEqual(
            source,
            [sys.executable, "-m", "mentat.local_bridge", "--host", "127.0.0.1", "--port", "49152"],
        )
        with patch.object(web_runtime.sys, "frozen", True, create=True), patch.object(
            web_runtime.sys, "platform", "win32"
        ):
            self.assertEqual(
                web_runtime.bridge_command(49152),
                [sys.executable, "--mentat-private-bridge", "--host", "127.0.0.1", "--port", "49152"],
            )

    def test_frozen_macos_uses_its_console_bridge_companion(self):
        with TemporaryDirectory() as temporary:
            macos = Path(temporary) / "Mentat.app" / "Contents" / "MacOS"
            executable = macos / "Mentat"
            companion = macos / "mentat-bridge"
            macos.mkdir(parents=True)
            (macos.parent / "Resources").mkdir()
            executable.touch()
            companion.touch()
            with patch.object(web_runtime.sys, "frozen", True, create=True), patch.object(
                web_runtime.sys, "platform", "darwin"
            ), patch.object(web_runtime.sys, "executable", str(executable)):
                self.assertEqual(
                    web_runtime.bridge_command(49152),
                    [str(companion.resolve()), "--mentat-private-bridge", "--host", "127.0.0.1", "--port", "49152"],
                )

    def test_frozen_macos_uses_lexical_launcher_sibling_for_the_console_bridge(self):
        with TemporaryDirectory() as temporary:
            contents = Path(temporary) / "Mentat.app" / "Contents"
            macos = contents / "MacOS"
            framework_launcher = contents / "Frameworks" / "Mentat"
            executable = macos / "Mentat"
            companion = macos / "mentat-bridge"
            framework_launcher.parent.mkdir(parents=True)
            macos.mkdir()
            (contents / "Resources").mkdir()
            framework_launcher.touch()
            executable.symlink_to("../Frameworks/Mentat")
            companion.touch()
            with patch.object(web_runtime.sys, "frozen", True, create=True), patch.object(
                web_runtime.sys, "platform", "darwin"
            ), patch.object(web_runtime.sys, "executable", str(executable)):
                self.assertEqual(web_runtime.bridge_command(49152)[0], str(companion.resolve()))

    def test_frozen_macos_refuses_to_launch_the_bridge_without_its_console_companion(self):
        with TemporaryDirectory() as temporary:
            executable = Path(temporary) / "Mentat.app" / "Contents" / "MacOS" / "Mentat"
            executable.parent.mkdir(parents=True)
            (executable.parent.parent / "Resources").mkdir()
            executable.touch()
            with patch.object(web_runtime.sys, "frozen", True, create=True), patch.object(
                web_runtime.sys, "platform", "darwin"
            ), patch.object(web_runtime.sys, "executable", str(executable)):
                with self.assertRaisesRegex(web_runtime.WebRuntimeError, "bridge_companion_missing"):
                    web_runtime.bridge_command(49152)

    def test_gateway_refuses_non_loopback_before_spawning(self):
        with self.assertRaises(web_runtime.WebRuntimeError) as raised:
            web_runtime.run_gateway(
                host="0.0.0.0",
                port=8890,
                data_dir=Path("/private/mentat"),
            )
        self.assertEqual(str(raised.exception), "gateway_host_must_be_loopback")

    def test_lifecycle_recognizes_only_marked_gateway_health(self):
        import mentat_lifecycle

        self.assertTrue(
            mentat_lifecycle.looks_like_mentat_gateway_health(
                {"gateway": "mentat-node-gateway", "service": "mentat-local-bridge", "status": "ready"}
            )
        )
        self.assertFalse(mentat_lifecycle.looks_like_mentat_gateway_health({"status": "ready"}))

    def test_ipv6_readiness_uses_a_bracketed_host_header(self):
        process = MagicMock()
        process.poll.return_value = None
        response = MagicMock(status=200)
        response.read.return_value = b'{"status":"ready"}'
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch.object(web_runtime, "HTTPConnection", return_value=connection):
            self.assertEqual(
                web_runtime.wait_for_health(port=8890, path="/bridge/v1/health", process=process, host="::1"),
                {"status": "ready"},
            )
        self.assertEqual(connection.request.call_args.kwargs["headers"]["Host"], "[::1]:8890")

    def test_readiness_reports_a_bridge_proxy_that_stays_unavailable(self):
        process = MagicMock()
        process.poll.return_value = None
        response = MagicMock(status=503)
        response.read.return_value = b'{"status":"unavailable"}'
        connection = MagicMock()
        connection.getresponse.return_value = response
        with patch.object(web_runtime, "HTTPConnection", return_value=connection), patch.object(
            web_runtime.time, "monotonic", side_effect=[0.0, 0.0, 0.2]
        ), patch.object(web_runtime.time, "sleep"):
            with self.assertRaises(web_runtime.WebRuntimeError) as raised:
                web_runtime.wait_for_health(
                    port=8890,
                    path="/api/bridge/health",
                    process=process,
                    timeout=0.1,
                    unavailable_error="gateway_bridge_unavailable",
                )
        self.assertEqual(str(raised.exception), "gateway_bridge_unavailable")

    def test_readiness_does_not_misclassify_an_earlier_bridge_proxy_503(self):
        process = MagicMock()
        process.poll.return_value = None
        response = MagicMock(status=503)
        response.read.return_value = b'{"status":"unavailable"}'
        connection = MagicMock()
        connection.request.side_effect = [None, OSError("later probe failed")]
        connection.getresponse.return_value = response
        with patch.object(web_runtime, "HTTPConnection", return_value=connection), patch.object(
            web_runtime.time, "monotonic", side_effect=[0.0, 0.0, 0.0, 0.2]
        ), patch.object(web_runtime.time, "sleep"):
            with self.assertRaises(web_runtime.WebRuntimeError) as raised:
                web_runtime.wait_for_health(
                    port=8890,
                    path="/api/bridge/health",
                    process=process,
                    timeout=0.1,
                    unavailable_error="gateway_bridge_unavailable",
                )
        self.assertEqual(str(raised.exception), "gateway_readiness_timeout")

    def test_readiness_stops_when_the_required_private_bridge_exits(self):
        process = MagicMock()
        process.poll.return_value = None
        bridge = MagicMock()
        bridge.poll.return_value = 2
        with self.assertRaisesRegex(web_runtime.WebRuntimeError, "bridge_process_stopped"):
            web_runtime.wait_for_health(
                port=8890,
                path="/api/bridge/health",
                process=process,
                required_process=bridge,
            )

    def test_gateway_establishes_task_authority_before_spawning_the_bridge(self):
        events: list[str] = []
        readiness_calls: list[dict] = []
        bridge = MagicMock()
        bridge.poll.return_value = None
        node = MagicMock()
        node.poll.side_effect = [0, 0]

        def spawn(command, **_kwargs):
            events.append("node" if command[0] == "/fixed/node" else "bridge")
            return node if command[0] == "/fixed/node" else bridge

        with TemporaryDirectory() as temporary:
            standalone = Path(temporary)
            (standalone / "server.js").write_text("// fixed test entry\n", encoding="utf-8")
            with patch.object(web_runtime, "find_node_24", return_value="/fixed/node"), patch.object(
                web_runtime, "require_node_24"
            ), patch.object(web_runtime, "gateway_port_is_available", return_value=True), patch.object(
                web_runtime, "find_free_bridge_port", return_value=49152
            ), patch.object(web_runtime, "reserve_mentat_server", side_effect=lambda _root: events.append("reserve")), patch.object(
                web_runtime, "release_mentat_server", side_effect=lambda _root: events.append("release")
            ), patch.object(web_runtime, "establish_task_authority", side_effect=lambda _root: events.append("task_authority")), patch.object(
                web_runtime, "establish_run_authority", side_effect=lambda _root: events.append("run_authority")
            ), patch.object(
                web_runtime.subprocess, "Popen", side_effect=spawn
            ), patch.object(
                web_runtime,
                "wait_for_health",
                side_effect=lambda **kwargs: (readiness_calls.append(kwargs), events.append(kwargs["path"])),
            ), patch.object(
                web_runtime, "start_startup_output_capture", return_value=MagicMock()
            ), patch.object(web_runtime, "write_runtime_state"), patch.object(web_runtime, "clear_runtime_state"):
                self.assertEqual(
                    web_runtime.run_gateway(
                        host="127.0.0.1", port=8890, data_dir=standalone / "data", standalone_root=standalone
                    ),
                    1,
                )
        self.assertLess(events.index("task_authority"), events.index("run_authority"))
        self.assertLess(events.index("run_authority"), events.index("bridge"))
        self.assertLess(events.index("bridge"), events.index("/bridge/v1/health"))
        self.assertLess(events.index("/bridge/v1/health"), events.index("node"))
        self.assertLess(events.index("node"), events.index("/api/gateway/health"))
        self.assertLess(events.index("/api/gateway/health"), events.index("/api/bridge/health"))
        self.assertNotIn("required_process", readiness_calls[0])
        self.assertNotIn("required_process", readiness_calls[1])
        self.assertIs(readiness_calls[2]["required_process"], bridge)

    def test_node_environment_excludes_bridge_runtime_settings_and_parent_secrets(self):
        with patch.dict(
            web_runtime.os.environ,
            {"PATH": "/fixed", "MENTAT_DATA_DIR": "/private/data", "HERMES_HOME": "/private/hermes", "UNRELATED_PARENT_VALUE": "ignored"},
            clear=True,
        ):
            environment = web_runtime.node_environment(
                token="x" * 43, bridge_port=49152, gateway_port=8890, gateway_host="127.0.0.1"
            )
        self.assertEqual(environment["PATH"], "/fixed")
        self.assertEqual(environment["MENTAT_BRIDGE_TOKEN"], "x" * 43)
        self.assertNotIn("MENTAT_DATA_DIR", environment)
        self.assertNotIn("HERMES_HOME", environment)
        self.assertNotIn("UNRELATED_PARENT_VALUE", environment)

    def test_gateway_startup_log_is_owner_private_and_runtime_scoped(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            path, startup_log = web_runtime.open_gateway_startup_log(root)
            with startup_log:
                startup_log.write(b"safe startup detail\n")
            self.assertEqual(path.parent, root / "runtime")
            self.assertRegex(path.name, r"^node-gateway-startup-[0-9a-f]{16}\.log$")
            self.assertEqual(path.read_bytes(), b"safe startup detail\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_gateway_startup_log_never_follows_an_existing_link(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "outside.txt"
            target.write_text("keep this", encoding="utf-8")
            link = root / "runtime" / "node-gateway-startup-0000000000000000.log"
            link.parent.mkdir()
            link.symlink_to(target)
            with patch.object(web_runtime.secrets, "token_hex", return_value="0000000000000000"):
                with self.assertRaisesRegex(web_runtime.WebRuntimeError, "gateway_startup_log_unavailable"):
                    web_runtime.open_gateway_startup_log(root)
            self.assertEqual(target.read_text(encoding="utf-8"), "keep this")

    def test_gateway_startup_log_retention_removes_only_old_owned_regular_files(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "runtime"
            runtime.mkdir()
            logs = [runtime / f"node-gateway-startup-{index:016x}.log" for index in range(3)]
            for index, path in enumerate(logs):
                path.write_bytes(b"log")
                os.utime(path, (index + 1, index + 1))
            external = root / "outside.txt"
            external.write_text("keep this", encoding="utf-8")
            (runtime / "node-gateway-startup-unsafe-link.log").symlink_to(external)
            web_runtime.prune_gateway_startup_logs(root, keep=2)
            self.assertFalse(logs[0].exists())
            self.assertTrue(logs[1].exists())
            self.assertTrue(logs[2].exists())
            self.assertEqual(external.read_text(encoding="utf-8"), "keep this")

    def test_startup_output_capture_is_byte_bounded(self):
        source = BytesIO(b"first" + (b"x" * 64))
        destination = BytesIO()
        web_runtime.copy_bounded_startup_output(source, destination, maximum_bytes=5)
        self.assertEqual(destination.getvalue(), b"first")

    def test_successful_startup_log_cleanup_closes_the_capture_before_unlinking(self):
        capture = MagicMock()
        destination = MagicMock()
        path = MagicMock()
        events: list[str] = []
        capture.join.side_effect = lambda **_kwargs: events.append("join")
        destination.close.side_effect = lambda: events.append("close")
        path.unlink.side_effect = lambda **_kwargs: events.append("unlink")
        web_runtime.close_startup_output_capture(capture, destination, path, remove=True)
        self.assertEqual(events, ["join", "close", "unlink"])

    def test_installed_runtime_uses_the_wheel_payload_when_source_build_is_absent(self):
        with patch.object(web_runtime, "SOURCE_ROOT", Path("/missing/source")), patch.object(
            web_runtime.sys, "prefix", "/installed"
        ):
            self.assertEqual(
                web_runtime.default_standalone_root(),
                Path("/installed/share/mentat/web"),
            )

    def test_frozen_macos_uses_the_real_resources_root_not_the_frameworks_link(self):
        with TemporaryDirectory() as temporary:
            contents = Path(temporary) / "Mentat.app" / "Contents"
            executable = contents / "MacOS" / "Mentat"
            resources = contents / "Resources"
            executable.parent.mkdir(parents=True)
            executable.touch()
            resources.mkdir()
            with patch.object(web_runtime.sys, "frozen", True, create=True), patch.object(
                web_runtime.sys, "platform", "darwin"
            ), patch.object(web_runtime.sys, "executable", str(executable)), patch.object(
                web_runtime.sys, "_MEIPASS", str(contents / "Frameworks"), create=True
            ):
                self.assertEqual(web_runtime.application_root(), resources.resolve())

    def test_gateway_establishes_task_authority_before_the_bridge_reads_tasks(self):
        with patch.object(web_runtime, "ensure_task_sqlite_authority") as establish:
            web_runtime.establish_task_authority(Path("/private/mentat"))
        establish.assert_called_once_with(Path("/private/mentat"), required_source_mode=0o600)

    def test_gateway_establishes_run_authority_before_the_bridge_reads_runs(self):
        with patch.object(web_runtime, "ensure_run_sqlite_authority") as establish:
            web_runtime.establish_run_authority(Path("/private/mentat"))
        establish.assert_called_once_with(
            Path("/private/mentat"), Path("/private/mentat/private/console/agent-console-runs.json")
        )

    def test_node_lookup_uses_validated_gui_launch_fallbacks(self):
        with patch.object(web_runtime.shutil, "which", return_value=None), patch.object(
            web_runtime.sys, "platform", "darwin"
        ), patch.object(web_runtime.Path, "is_file", return_value=True):
            self.assertEqual(web_runtime.find_node_24(), "/opt/homebrew/bin/node")

    def test_bridge_launcher_watch_exits_when_the_supervisor_is_gone(self):
        with patch.dict(local_bridge.os.environ, {"MENTAT_LAUNCHER_PID": "4321"}, clear=True), patch.object(
            local_bridge.os, "getpid", return_value=9999
        ):
            self.assertEqual(local_bridge.configured_launcher_pid(), 4321)
        with patch.object(local_bridge.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(local_bridge.launcher_is_running(4321))

    def test_bridge_launcher_watch_uses_windows_safe_liveness_probe(self):
        with patch.object(local_bridge.os, "name", "nt"), patch(
            "private_state._pid_is_running", return_value=True
        ) as running:
            self.assertTrue(local_bridge.launcher_is_running(4321))
        running.assert_called_once_with(4321)


if __name__ == "__main__":
    unittest.main()
