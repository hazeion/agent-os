from __future__ import annotations

from pathlib import Path
import sys
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
        with patch.object(web_runtime.sys, "frozen", True, create=True):
            self.assertEqual(
                web_runtime.bridge_command(49152),
                [sys.executable, "--mentat-private-bridge", "--host", "127.0.0.1", "--port", "49152"],
            )

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

    def test_node_environment_excludes_bridge_runtime_settings_and_parent_secrets(self):
        with patch.dict(
            web_runtime.os.environ,
            {"PATH": "/fixed", "MENTAT_DATA_DIR": "/private/data", "HERMES_HOME": "/private/hermes", "OPENAI_API_KEY": "secret"},
            clear=True,
        ):
            environment = web_runtime.node_environment(
                token="x" * 43, bridge_port=49152, gateway_port=8890, gateway_host="127.0.0.1"
            )
        self.assertEqual(environment["PATH"], "/fixed")
        self.assertEqual(environment["MENTAT_BRIDGE_TOKEN"], "x" * 43)
        self.assertNotIn("MENTAT_DATA_DIR", environment)
        self.assertNotIn("HERMES_HOME", environment)
        self.assertNotIn("OPENAI_API_KEY", environment)

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
