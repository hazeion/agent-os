from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, call, patch

from scripts import mentat_web_preview as preview


class MentatWebPreviewTests(unittest.TestCase):
    def test_node_version_gate_requires_24_19_or_newer_within_major_24(self):
        self.assertEqual(preview.parse_node_version("v24.19.0"), (24, 19, 0))
        self.assertEqual(preview.parse_node_version("v24.20.1+build"), (24, 20, 1))
        for value in (
            "24.19.0",
            "v24",
            "v24.19",
            "v24.19.0-rc.1",
            "not-node",
        ):
            with self.subTest(value=value):
                with self.assertRaises(preview.PreviewError):
                    preview.parse_node_version(value)

        for version in ("v22.23.1", "v23.11.1", "v24.18.0", "v25.0.0", "v26.7.0"):
            with self.subTest(version=version), patch.object(
                preview.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(["node"], 0, version + "\n", ""),
            ):
                with self.assertRaises(preview.PreviewError) as raised:
                    preview.require_node_24("/fixed/node")
                self.assertEqual(str(raised.exception), "node_24_19_required")

        with patch.object(
            preview.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(["node"], 0, "v24.19.0\n", ""),
        ):
            self.assertEqual(preview.require_node_24("/fixed/node"), (24, 19, 0))

    def test_commands_are_fixed_arrays_and_never_contain_the_bridge_token(self):
        token = "private_token_that_must_never_enter_a_command_line_12345"
        bridge = preview.bridge_command(49152)
        node = preview.node_command("/fixed/node")
        environment = preview.child_environment(
            token=token,
            bridge_port=49152,
            gateway_port=8890,
        )

        self.assertEqual(
            bridge,
            [
                sys.executable,
                "-m",
                "mentat.local_bridge",
                "--host",
                "127.0.0.1",
                "--port",
                "49152",
            ],
        )
        self.assertEqual(node, ["/fixed/node", str(preview.STANDALONE_SERVER)])
        self.assertNotIn(token, " ".join([*bridge, *node]))
        self.assertEqual(environment["MENTAT_BRIDGE_TOKEN"], token)
        self.assertEqual(environment["MENTAT_BRIDGE_ORIGIN"], "http://127.0.0.1:49152")
        self.assertEqual(environment["HOSTNAME"], "127.0.0.1")
        self.assertEqual(environment["PORT"], "8890")
        self.assertEqual(environment["NEXT_TELEMETRY_DISABLED"], "1")

    def test_cleanup_withdraws_node_before_the_bridge_and_escalates_after_timeout(self):
        node = MagicMock()
        bridge = MagicMock()
        node.poll.return_value = None
        bridge.poll.return_value = None
        order: list[str] = []
        node.terminate.side_effect = lambda: order.append("node-terminate")
        node.wait.side_effect = lambda timeout: order.append(f"node-wait-{timeout}")
        bridge.terminate.side_effect = lambda: order.append("bridge-terminate")
        bridge.wait.side_effect = lambda timeout: order.append(f"bridge-wait-{timeout}")

        preview.stop_preview_processes(node, bridge)
        self.assertEqual(
            order,
            [
                "node-terminate",
                f"node-wait-{preview.SHUTDOWN_TIMEOUT_SECONDS}",
                "bridge-terminate",
                f"bridge-wait-{preview.SHUTDOWN_TIMEOUT_SECONDS}",
            ],
        )

        hung = MagicMock()
        hung.poll.return_value = None
        hung.wait.side_effect = [subprocess.TimeoutExpired("node", 10), 0]
        preview.stop_process(hung)
        hung.terminate.assert_called_once_with()
        hung.kill.assert_called_once_with()
        self.assertEqual(
            hung.wait.call_args_list,
            [call(timeout=preview.SHUTDOWN_TIMEOUT_SECONDS), call(timeout=3)],
        )

    def test_run_preview_fails_before_spawning_when_build_or_port_is_unavailable(self):
        with patch.object(preview.shutil, "which", return_value="/fixed/node"), patch.object(
            preview, "require_node_24", return_value=(24, 19, 0)
        ), patch.object(Path, "is_file", return_value=False), patch.object(
            preview.subprocess, "Popen"
        ) as popen:
            with self.assertRaises(preview.PreviewError) as raised:
                preview.run_preview(8890)
        self.assertEqual(str(raised.exception), "standalone_build_missing")
        popen.assert_not_called()

        with patch.object(preview.shutil, "which", return_value="/fixed/node"), patch.object(
            preview, "require_node_24", return_value=(24, 19, 0)
        ), patch.object(Path, "is_file", return_value=True), patch.object(
            preview, "gateway_port_is_available", return_value=False
        ), patch.object(preview.subprocess, "Popen") as popen:
            with self.assertRaises(preview.PreviewError) as raised:
                preview.run_preview(8890)
        self.assertEqual(str(raised.exception), "gateway_port_unavailable")
        popen.assert_not_called()

    def test_unexpected_child_exit_stops_the_surviving_sibling(self):
        bridge = MagicMock()
        node = MagicMock()
        bridge.poll.side_effect = [7, 7]
        node.poll.return_value = None
        with patch.object(preview.shutil, "which", return_value="/fixed/node"), patch.object(
            preview, "require_node_24", return_value=(24, 19, 0)
        ), patch.object(Path, "is_file", return_value=True), patch.object(
            preview, "gateway_port_is_available", return_value=True
        ), patch.object(preview, "find_free_bridge_port", return_value=49152), patch.object(
            preview, "wait_for_health"
        ), patch.object(preview.subprocess, "Popen", side_effect=[bridge, node]), patch.object(
            preview.signal, "signal", return_value=preview.signal.SIG_DFL
        ), patch.object(preview.time, "sleep"):
            with self.assertRaises(preview.PreviewError) as raised:
                preview.run_preview(8890)
        self.assertEqual(str(raised.exception), "bridge_process_stopped")
        node.terminate.assert_called_once_with()
        node.wait.assert_called_once_with(timeout=preview.SHUTDOWN_TIMEOUT_SECONDS)

        bridge = MagicMock()
        node = MagicMock()
        bridge.poll.side_effect = [None, None]
        node.poll.side_effect = [5, 5]
        with patch.object(preview.shutil, "which", return_value="/fixed/node"), patch.object(
            preview, "require_node_24", return_value=(24, 19, 0)
        ), patch.object(Path, "is_file", return_value=True), patch.object(
            preview, "gateway_port_is_available", return_value=True
        ), patch.object(preview, "find_free_bridge_port", return_value=49152), patch.object(
            preview, "wait_for_health"
        ), patch.object(preview.subprocess, "Popen", side_effect=[bridge, node]), patch.object(
            preview.signal, "signal", return_value=preview.signal.SIG_DFL
        ), patch.object(preview.time, "sleep"):
            self.assertEqual(preview.run_preview(8890), 5)
        bridge.terminate.assert_called_once_with()
        bridge.wait.assert_called_once_with(timeout=preview.SHUTDOWN_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
