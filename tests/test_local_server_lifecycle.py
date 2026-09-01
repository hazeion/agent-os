from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, call, patch

import mentat_lifecycle as lifecycle
from mentat.process_identity import parse_linux_process_start_ticks
import private_state
from private_state import connection_server_reservation_path, mentat_server_active
import server


class LocalServerLifecycleTests(unittest.TestCase):
    def make_config(
        self, data_dir: Path, port: int = 8888, host: str = "127.0.0.1"
    ) -> server.AppConfig:
        return server.AppConfig(
            config_files=tuple(),
            host=host,
            port=port,
            data_dir=data_dir,
            public_dir=server.PUBLIC_DIR,
            hermes_home=server.HERMES_HOME,
            obsidian_vault=server.OBSIDIAN_VAULT,
            display_name=None,
            greeting_prefix=None,
        )

    def test_managed_ports_include_only_the_configured_port(self):
        self.assertEqual(lifecycle.managed_ports(8888), [8888])
        self.assertEqual(lifecycle.managed_ports(9001), [9001])

    def test_linux_process_start_ticks_parser_handles_retitled_process_names(self):
        fields = ["S", *("0" for _ in range(18)), "987654"]
        payload = f"4321 (next-server (v16.0.10)) {' '.join(fields)}\n"
        self.assertEqual(parse_linux_process_start_ticks(payload, 4321), 987654)
        self.assertIsNone(parse_linux_process_start_ticks(payload, 4322))
        self.assertIsNone(parse_linux_process_start_ticks(payload + ("0" * 4096), 4321))

    def test_exited_process_does_not_keep_server_reservation_active(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reservation = connection_server_reservation_path(root)
            reservation.parent.mkdir(parents=True)
            child = subprocess.Popen([sys.executable, "-c", "pass"])
            child.wait(timeout=5)
            reservation.write_text(json.dumps({"pid": child.pid}) + "\n", encoding="utf-8")

            self.assertFalse(private_state._pid_is_running(child.pid))
            self.assertFalse(mentat_server_active(root))

    def test_parse_netstat_listeners_extracts_listening_rows(self):
        output = """
  TCP    127.0.0.1:8888         0.0.0.0:0              LISTENING       8808
  TCP    127.0.0.1:8890         0.0.0.0:0              LISTENING       28176
  TCP    127.0.0.1:8888         127.0.0.1:51206        TIME_WAIT       0
"""
        listeners = lifecycle.parse_netstat_listeners(output)
        self.assertEqual([(item.port, item.pid) for item in listeners], [(8888, 8808), (8890, 28176)])

    def test_looks_like_mentat_overview_requires_expected_shape(self):
        self.assertTrue(
            lifecycle.looks_like_mentat_overview(
                {
                    "generated_at": "2026-06-22T00:00:00-07:00",
                    "cards": {"active_tasks": 1},
                    "identity": {"display_name": "Operator"},
                }
            )
        )
        self.assertFalse(lifecycle.looks_like_mentat_overview({"cards": {}, "identity": {}}))

    def test_probe_mentat_uses_bracketed_ipv6_listener_address(self):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        payload = {
            "generated_at": "2026-07-11T00:00:00-07:00",
            "cards": {},
            "identity": {},
        }
        with patch.object(lifecycle, "urlopen", return_value=response) as urlopen, patch.object(
            lifecycle.json, "load", return_value=payload
        ):
            self.assertTrue(lifecycle.probe_mentat("::1", 8888))

        urlopen.assert_called_once_with("http://[::1]:8888/api/overview", timeout=0.6)

    def test_recorded_node_probe_requires_the_fixed_gateway_marker(self):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        with patch.object(lifecycle, "urlopen", return_value=response) as urlopen, patch.object(
            lifecycle.json,
            "load",
            return_value={"gateway": "mentat-node-gateway", "status": "ready"},
        ):
            self.assertTrue(lifecycle.probe_recorded_node_gateway("::1", 8888))

        urlopen.assert_called_once_with(
            "http://[::1]:8888/api/gateway/health", timeout=0.6
        )
        self.assertFalse(
            lifecycle.looks_like_mentat_node_gateway(
                {"generated_at": "2026-08-22T00:00:00Z", "cards": {}, "identity": {}}
            )
        )

    def test_listener_probe_cache_is_scoped_to_normalized_address_and_port(self):
        ipv4 = lifecycle.Listener(pid=4101, port=8888, local_address="127.0.0.1:8888", raw="")
        ipv6 = lifecycle.Listener(pid=6101, port=8888, local_address="[0:0:0:0:0:0:0:1]:8888", raw="")
        probe_results = {
            ("127.0.0.1", 8888): True,
            ("::1", 8888): False,
        }
        probe_cache: dict[tuple[str, int], bool] = {}
        command_cache: dict[int, str] = {}
        with patch.object(lifecycle, "process_commandline", return_value=""), patch.object(
            lifecycle,
            "probe_mentat",
            side_effect=lambda host, port: probe_results[(host, port)],
        ) as probe:
            ipv4_result = lifecycle.identify_listener(ipv4, None, probe_cache, command_cache)
            ipv6_result = lifecycle.identify_listener(ipv6, None, probe_cache, command_cache)

        self.assertFalse(ipv4_result[0])
        self.assertFalse(ipv6_result[0])
        self.assertEqual(probe.call_args_list, [call("127.0.0.1", 8888), call("::1", 8888)])

    def test_server_runtime_state_captures_launcher_pid(self):
        with patch.dict(server.os.environ, {"MENTAT_LAUNCHER_PID": "4321"}, clear=False):
            payload = server.runtime_state_payload()
        self.assertEqual(payload["launcher_pid"], 4321)

    def test_server_configured_launcher_pid_rejects_missing_invalid_or_self(self):
        with patch.dict(server.os.environ, {}, clear=False):
            server.os.environ.pop("MENTAT_LAUNCHER_PID", None)
            self.assertIsNone(server.configured_launcher_pid())
        with patch.dict(server.os.environ, {"MENTAT_LAUNCHER_PID": "not-a-number"}, clear=False):
            self.assertIsNone(server.configured_launcher_pid())
        with patch.dict(server.os.environ, {"MENTAT_LAUNCHER_PID": str(server.os.getpid())}, clear=False):
            self.assertIsNone(server.configured_launcher_pid())

    def test_dashboard_cleanup_always_releases_connection_reservation(self):
        for failing_step in ("stop_runs", "server_close", "runtime_state"):
            with self.subTest(failing_step=failing_step), TemporaryDirectory() as tmpdir:
                root = Path(tmpdir) / "operator-data"
                root.mkdir(mode=0o700)
                public = Path(tmpdir) / "public"
                fake_server = MagicMock()
                fake_server.serve_forever.return_value = None
                if failing_step == "server_close":
                    fake_server.server_close.side_effect = RuntimeError(
                        "server close failed"
                    )
                stop_effect = (
                    RuntimeError("run cleanup failed")
                    if failing_step == "stop_runs"
                    else None
                )
                clear_effect = (
                    RuntimeError("runtime cleanup failed")
                    if failing_step == "runtime_state"
                    else None
                )
                with patch.object(server, "DATA_DIR", root), patch.object(
                    server, "PUBLIC_DIR", public
                ), patch.object(
                    server,
                    "load_remote_hermes_connection_state",
                ), patch.object(
                    server, "ensure_task_authority"
                ), patch.object(
                    server, "ensure_project_authority"
                ), patch.object(
                    server, "load_agent_console_runs"
                ), patch.object(
                    server, "maintain_agent_console_attachments"
                ), patch.object(
                    server.threading.Thread, "start"
                ), patch.object(
                    server,
                    "server_class_for_host",
                    return_value=lambda *_args: fake_server,
                ), patch.object(
                    server, "start_launcher_watch", return_value=None
                ), patch.object(
                    server, "write_runtime_state"
                ), patch.object(
                    server,
                    "stop_agent_console_processes",
                    side_effect=stop_effect,
                ) as stop_runs, patch.object(
                    server,
                    "clear_runtime_state",
                    side_effect=clear_effect,
                ) as clear_state:
                    with self.assertRaises(RuntimeError):
                        server.serve_dashboard()

                stop_runs.assert_called_once_with()
                fake_server.server_close.assert_called_once_with()
                clear_state.assert_called_once_with()
                self.assertFalse(
                    connection_server_reservation_path(root).exists()
                )
                self.assertFalse(mentat_server_active(root))

    def test_cleanup_does_not_kill_listener_tracked_only_by_stale_runtime_state(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"pid": 4321}) + "\n", encoding="utf-8")
            listener = lifecycle.Listener(pid=4321, port=8888, local_address="127.0.0.1:8888", raw="")
            with patch.object(lifecycle, "netstat_listeners", return_value=[listener]), patch.object(
                lifecycle, "process_commandline", return_value=""
            ), patch.object(lifecycle, "probe_mentat", return_value=False), patch.object(
                lifecycle, "kill_pid"
            ) as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config)

            self.assertFalse(report["ok"])
            self.assertEqual(report["actions"][0]["action"], "blocked_non_mentat")
            self.assertEqual(report["actions"][0]["pid"], 4321)
            self.assertEqual(report["actions"][0]["reasons"], ["matches_runtime_state"])
            self.assertTrue(state_path.exists())
            kill_pid.assert_not_called()

    def test_cleanup_kills_runtime_listener_with_exact_mentat_command_path(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"pid": 4321}) + "\n", encoding="utf-8")
            listener = lifecycle.Listener(pid=4321, port=8888, local_address="127.0.0.1:8888", raw="")
            commandline = f'python "{lifecycle.BASE_DIR / "server.py"}" --port 8888'
            with patch.object(lifecycle, "netstat_listeners", return_value=[listener]), patch.object(
                lifecycle, "process_commandline", return_value=commandline
            ), patch.object(lifecycle, "probe_mentat", return_value=False), patch.object(
                lifecycle, "kill_pid", return_value=(True, "terminated")
            ) as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config)

            self.assertTrue(report["ok"])
            self.assertEqual(report["actions"][0]["action"], "killed")
            self.assertEqual(report["actions"][0]["reasons"], ["matches_runtime_state", "command_line"])
            kill_pid.assert_called_once_with(4321)

    def test_cleanup_kills_runtime_listener_with_mentat_overview_probe(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"pid": 4321}) + "\n", encoding="utf-8")
            listener = lifecycle.Listener(pid=4321, port=8888, local_address="127.0.0.1:8888", raw="")
            with patch.object(lifecycle, "netstat_listeners", return_value=[listener]), patch.object(
                lifecycle, "process_commandline", return_value="python /tmp/unrelated_server.py"
            ), patch.object(lifecycle, "probe_mentat", return_value=True), patch.object(
                lifecycle, "kill_pid", return_value=(True, "terminated")
            ) as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config)

            self.assertTrue(report["ok"])
            self.assertEqual(report["actions"][0]["action"], "killed")
            self.assertEqual(report["actions"][0]["reasons"], ["matches_runtime_state", "overview_probe"])
            kill_pid.assert_called_once_with(4321)

    def test_cleanup_kills_recorded_node_gateway_after_bridge_failure(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            gateway = "/tmp/mentat-web/server.js"
            state_path.write_text(
                json.dumps({"pid": 4321, "runtime": "node-gateway", "command_path": gateway}) + "\n",
                encoding="utf-8",
            )
            listener = lifecycle.Listener(pid=4321, port=8888, local_address="127.0.0.1:8888", raw="")
            with patch.object(lifecycle, "netstat_listeners", return_value=[listener]), patch.object(
                lifecycle, "process_commandline", return_value=f"node {gateway}"
            ), patch.object(lifecycle, "probe_mentat", return_value=False), patch.object(
                lifecycle, "kill_pid", return_value=(True, "terminated")
            ) as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config)

        self.assertTrue(report["ok"])
        self.assertEqual(report["actions"][0]["reasons"], ["matches_runtime_state", "recorded_node_gateway"])
        kill_pid.assert_called_once_with(4321)

    def test_cleanup_kills_healthy_recorded_node_gateway_when_listener_inventory_is_empty(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            gateway = "/tmp/mentat-web/server.js"
            state_path.write_text(
                json.dumps({"pid": 4321, "runtime": "node-gateway", "command_path": gateway}) + "\n",
                encoding="utf-8",
            )
            with patch.object(lifecycle, "netstat_listeners", return_value=[]), patch.object(
                lifecycle, "process_commandline", return_value=f"node {gateway}"
            ), patch.object(lifecycle, "probe_recorded_node_gateway", return_value=True), patch.object(
                lifecycle, "kill_pid", return_value=(True, "terminated")
            ) as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

            self.assertTrue(report["ok"])
            self.assertEqual(
                report["actions"][0],
                {
                    "port": 8888,
                    "pid": 4321,
                    "action": "killed",
                    "reasons": ["matches_runtime_state", "recorded_node_gateway", "gateway_probe"],
                    "message": "terminated",
                },
            )
            self.assertFalse(state_path.exists())
            kill_pid.assert_called_once_with(4321)

    def test_empty_listener_inventory_accepts_exact_gateway_cwd_after_node_retitles(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            standalone = data_dir / "installed-web"
            standalone.mkdir()
            gateway = standalone / "server.js"
            gateway.write_text("", encoding="utf-8")
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "runtime": "node-gateway",
                        "command_path": str(gateway),
                        "process_start_ticks": 555,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(
                lifecycle, "netstat_listeners", return_value=[]
            ), patch.object(
                lifecycle,
                "process_commandline",
                return_value="next-server (v16.0.10)",
            ), patch.object(
                lifecycle,
                "process_working_directory",
                return_value=str(standalone),
            ), patch.object(
                lifecycle, "linux_process_start_ticks", return_value=555
            ), patch.object(
                lifecycle, "probe_recorded_node_gateway", return_value=True
            ), patch.object(
                lifecycle,
                "kill_linux_pid_with_start_ticks",
                return_value=(True, "terminated"),
            ) as kill_recorded_pid:
                report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

            self.assertTrue(report["ok"])
            self.assertEqual(
                report["actions"][0]["reasons"],
                [
                    "matches_runtime_state",
                    "process_start_identity",
                    "recorded_node_gateway_cwd",
                    "gateway_probe",
                ],
            )
            self.assertFalse(state_path.exists())
            kill_recorded_pid.assert_called_once_with(4321, 555)

    def test_empty_listener_inventory_rejects_reused_pid_despite_exact_command(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            standalone = data_dir / "installed-web"
            standalone.mkdir()
            gateway = standalone / "server.js"
            gateway.write_text("", encoding="utf-8")
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "runtime": "node-gateway",
                        "command_path": str(gateway),
                        "process_start_ticks": 555,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(
                lifecycle, "netstat_listeners", return_value=[]
            ), patch.object(
                lifecycle, "process_commandline", return_value=f"node {gateway}"
            ), patch.object(
                lifecycle, "process_working_directory", return_value=str(standalone)
            ), patch.object(
                lifecycle, "linux_process_start_ticks", return_value=777
            ), patch.object(
                lifecycle, "probe_recorded_node_gateway", return_value=True
            ), patch.object(
                lifecycle, "kill_linux_pid_with_start_ticks"
            ) as kill_recorded_pid, patch.object(lifecycle, "kill_pid") as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

            self.assertFalse(report["ok"])
            self.assertEqual(
                report["actions"][0]["reasons"],
                ["matches_runtime_state", "process_identity_mismatch", "gateway_probe"],
            )
            self.assertTrue(state_path.exists())
            kill_recorded_pid.assert_not_called()
            kill_pid.assert_not_called()

    def test_empty_listener_inventory_rejects_missing_recorded_gateway_file(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            standalone = data_dir / "installed-web"
            standalone.mkdir()
            gateway = standalone / "server.js"
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "runtime": "node-gateway",
                        "command_path": str(gateway),
                        "process_start_ticks": 555,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(
                lifecycle, "netstat_listeners", return_value=[]
            ), patch.object(
                lifecycle,
                "process_commandline",
                return_value="next-server (v16.0.10)",
            ), patch.object(
                lifecycle, "process_working_directory", return_value=str(standalone)
            ), patch.object(
                lifecycle, "linux_process_start_ticks", return_value=555
            ), patch.object(
                lifecycle, "probe_recorded_node_gateway", return_value=True
            ), patch.object(
                lifecycle, "kill_linux_pid_with_start_ticks"
            ) as kill_recorded_pid:
                report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

            self.assertFalse(report["ok"])
            self.assertEqual(
                report["actions"][0]["reasons"],
                ["matches_runtime_state", "process_start_identity", "gateway_probe"],
            )
            self.assertTrue(state_path.exists())
            kill_recorded_pid.assert_not_called()

    def test_empty_listener_inventory_rejects_same_cwd_unrelated_reused_process(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            standalone = data_dir / "installed-web"
            standalone.mkdir()
            gateway = standalone / "server.js"
            gateway.write_text("", encoding="utf-8")
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "runtime": "node-gateway",
                        "command_path": str(gateway),
                        "process_start_ticks": 555,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(
                lifecycle, "netstat_listeners", return_value=[]
            ), patch.object(
                lifecycle,
                "process_commandline",
                return_value="python unrelated_worker.py",
            ), patch.object(
                lifecycle, "process_working_directory", return_value=str(standalone)
            ), patch.object(
                lifecycle, "linux_process_start_ticks", return_value=777
            ), patch.object(
                lifecycle, "probe_recorded_node_gateway", return_value=True
            ), patch.object(
                lifecycle, "kill_linux_pid_with_start_ticks"
            ) as kill_recorded_pid:
                report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

            self.assertFalse(report["ok"])
            self.assertIn("process_identity_mismatch", report["actions"][0]["reasons"])
            self.assertTrue(state_path.exists())
            kill_recorded_pid.assert_not_called()

    def test_empty_listener_inventory_requires_both_recorded_path_and_live_health(self):
        cases = (
            ("node /tmp/unrelated/server.js", True),
            ("node /tmp/mentat-web/server.js", False),
        )
        for commandline, healthy in cases:
            with self.subTest(commandline=commandline, healthy=healthy), TemporaryDirectory() as tmpdir:
                data_dir = Path(tmpdir)
                config = self.make_config(data_dir)
                state_path = lifecycle.lifecycle_state_path(config)
                state_path.parent.mkdir(parents=True, exist_ok=True)
                gateway = "/tmp/mentat-web/server.js"
                state_path.write_text(
                    json.dumps({"pid": 4321, "runtime": "node-gateway", "command_path": gateway}) + "\n",
                    encoding="utf-8",
                )
                with patch.object(lifecycle, "netstat_listeners", return_value=[]), patch.object(
                    lifecycle, "process_commandline", return_value=commandline
                ), patch.object(lifecycle, "probe_recorded_node_gateway", return_value=healthy), patch.object(
                    lifecycle, "kill_pid"
                ) as kill_pid:
                    report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

                self.assertFalse(report["ok"])
                expected_reason = "gateway_probe" if healthy else "recorded_node_gateway"
                self.assertEqual(report["actions"][0]["action"], "blocked_unverified_gateway")
                self.assertIn(expected_reason, report["actions"][0]["reasons"])
                self.assertTrue(state_path.exists())
                kill_pid.assert_not_called()

    def test_empty_listener_inventory_clears_stale_gateway_state_without_evidence(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            gateway = "/tmp/mentat-web/server.js"
            state_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "runtime": "node-gateway",
                        "command_path": gateway,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(
                lifecycle, "netstat_listeners", return_value=[]
            ), patch.object(
                lifecycle,
                "process_commandline",
                return_value="node /tmp/unrelated/server.js",
            ), patch.object(
                lifecycle, "probe_recorded_node_gateway", return_value=False
            ), patch.object(lifecycle, "kill_pid") as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

            self.assertTrue(report["ok"])
            self.assertEqual(
                report["actions"],
                [{"action": "cleared_runtime_state", "state_pid": 4321}],
            )
            self.assertFalse(state_path.exists())
            kill_pid.assert_not_called()

    def test_empty_listener_inventory_never_probes_or_kills_for_non_loopback_host(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir, host="192.0.2.10")
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            gateway = "/tmp/mentat-web/server.js"
            state_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "runtime": "node-gateway",
                        "command_path": gateway,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(
                lifecycle, "netstat_listeners", return_value=[]
            ), patch.object(
                lifecycle, "process_commandline", return_value=f"node {gateway}"
            ), patch.object(lifecycle, "probe_recorded_node_gateway") as probe, patch.object(
                lifecycle, "kill_pid"
            ) as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

            self.assertFalse(report["ok"])
            self.assertEqual(
                report["actions"],
                [
                    {
                        "port": 8888,
                        "pid": 4321,
                        "action": "blocked_unverified_gateway",
                        "reasons": ["matches_runtime_state", "non_loopback_host"],
                    }
                ],
            )
            self.assertTrue(state_path.exists())
            probe.assert_not_called()
            kill_pid.assert_not_called()

    def test_empty_listener_inventory_blocks_malformed_recorded_process_identity(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            gateway = "/tmp/mentat-web/server.js"
            state_path.write_text(
                json.dumps(
                    {
                        "pid": 4321,
                        "runtime": "node-gateway",
                        "command_path": gateway,
                        "process_start_ticks": True,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.object(
                lifecycle, "netstat_listeners", return_value=[]
            ), patch.object(lifecycle, "process_commandline") as commandline, patch.object(
                lifecycle, "probe_recorded_node_gateway"
            ) as probe, patch.object(lifecycle, "kill_pid") as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

            self.assertFalse(report["ok"])
            self.assertEqual(
                report["actions"][0]["reasons"],
                ["matches_runtime_state", "invalid_process_identity"],
            )
            self.assertTrue(state_path.exists())
            commandline.assert_not_called()
            probe.assert_not_called()
            kill_pid.assert_not_called()

    def test_failed_recorded_gateway_stop_preserves_runtime_state(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir)
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            gateway = "/tmp/mentat-web/server.js"
            state_path.write_text(
                json.dumps({"pid": 4321, "runtime": "node-gateway", "command_path": gateway}) + "\n",
                encoding="utf-8",
            )
            with patch.object(lifecycle, "netstat_listeners", return_value=[]), patch.object(
                lifecycle, "process_commandline", return_value=f"node {gateway}"
            ), patch.object(lifecycle, "probe_recorded_node_gateway", return_value=True), patch.object(
                lifecycle, "kill_pid", return_value=(False, "permission denied")
            ):
                report = lifecycle.cleanup_mentat_listeners(config, stop_only=True)

            self.assertFalse(report["ok"])
            self.assertEqual(report["actions"][0]["action"], "kill_failed")
            self.assertTrue(state_path.exists())

    def test_commandline_detection_requires_exact_project_script_path(self):
        server_path = lifecycle.BASE_DIR / "server.py"
        windows_server_path = str(server_path).replace("/", "\\")
        self.assertTrue(lifecycle.looks_like_mentat_commandline(f'python "{server_path}" --port 8888'))
        self.assertTrue(lifecycle.looks_like_mentat_commandline(f'python "{windows_server_path}" --port 8888'))
        self.assertFalse(lifecycle.looks_like_mentat_commandline("python /tmp/server.py --port 8888"))
        self.assertFalse(lifecycle.looks_like_mentat_commandline(f"python {server_path}.backup --port 8888"))
        self.assertFalse(lifecycle.looks_like_mentat_commandline(f"python {lifecycle.BASE_DIR / 'other.py'} --port 8888"))

    def test_recorded_node_gateway_path_accepts_windows_absolute_paths(self):
        self.assertTrue(
            lifecycle.commandline_contains_exact_path(
                r'node "C:\Mentat\_internal\web\server.js"',
                r"C:\Mentat\_internal\web\server.js",
            )
        )

    def test_recorded_node_gateway_cwd_requires_the_exact_existing_parent(self):
        with TemporaryDirectory() as tmpdir:
            standalone = Path(tmpdir) / "standalone"
            sibling = Path(tmpdir) / "sibling"
            standalone.mkdir()
            sibling.mkdir()
            gateway = standalone / "server.js"
            self.assertFalse(lifecycle.gateway_entrypoint_is_regular(str(gateway)))
            gateway.write_text("", encoding="utf-8")
            self.assertTrue(lifecycle.gateway_entrypoint_is_regular(str(gateway)))
            self.assertFalse(lifecycle.gateway_entrypoint_is_regular(str(standalone)))
            with patch.object(
                lifecycle, "process_working_directory", return_value=str(standalone)
            ):
                self.assertTrue(
                    lifecycle.working_directory_matches_gateway(4321, str(gateway))
                )
            with patch.object(
                lifecycle, "process_working_directory", return_value=str(sibling)
            ):
                self.assertFalse(
                    lifecycle.working_directory_matches_gateway(4321, str(gateway))
                )
            self.assertFalse(
                lifecycle.working_directory_matches_gateway(4321, "server.js")
            )

    @unittest.skipUnless(hasattr(lifecycle.select, "poll"), "pidfd polling is Linux/POSIX only")
    def test_pidfd_stop_rechecks_process_identity_before_signaling(self):
        poller = MagicMock()
        poller.poll.return_value = [(91, lifecycle.select.POLLIN)]
        with patch.object(lifecycle, "IS_LINUX", True), patch.object(
            lifecycle, "linux_process_start_ticks", side_effect=[555, 555]
        ), patch.object(lifecycle.os, "pidfd_open", return_value=91, create=True) as pidfd_open, patch.object(
            lifecycle.signal, "pidfd_send_signal", create=True
        ) as pidfd_send_signal, patch.object(
            lifecycle.select, "poll", return_value=poller
        ), patch.object(lifecycle.os, "close") as close:
            result = lifecycle.kill_linux_pid_with_start_ticks(4321, 555)

        self.assertEqual(result, (True, "terminated with SIGTERM"))
        pidfd_open.assert_called_once_with(4321, 0)
        pidfd_send_signal.assert_called_once_with(91, lifecycle.signal.SIGTERM)
        close.assert_called_once_with(91)

    @unittest.skipUnless(hasattr(lifecycle.select, "poll"), "pidfd polling is Linux/POSIX only")
    def test_pidfd_stop_blocks_when_identity_changes_after_open(self):
        with patch.object(lifecycle, "IS_LINUX", True), patch.object(
            lifecycle, "linux_process_start_ticks", side_effect=[555, 777]
        ), patch.object(lifecycle.os, "pidfd_open", return_value=91, create=True), patch.object(
            lifecycle.signal, "pidfd_send_signal", create=True
        ) as pidfd_send_signal, patch.object(lifecycle.os, "close") as close:
            result = lifecycle.kill_linux_pid_with_start_ticks(4321, 555)

        self.assertEqual(result, (False, "recorded process identity changed"))
        pidfd_send_signal.assert_not_called()
        close.assert_called_once_with(91)

    def test_pidfd_stop_fails_closed_when_race_safe_signaling_is_unavailable(self):
        with patch.object(lifecycle, "IS_LINUX", True), patch.object(
            lifecycle.os, "pidfd_open", None, create=True
        ):
            self.assertEqual(
                lifecycle.kill_linux_pid_with_start_ticks(4321, 555),
                (False, "race-safe process identity is unavailable"),
            )

    def test_launchers_pass_absolute_script_paths(self):
        run_sh = (lifecycle.BASE_DIR / "run.sh").read_text(encoding="utf-8")
        run_bat = (lifecycle.BASE_DIR / "run.bat").read_text(encoding="utf-8")

        self.assertIn('exec "$PYTHON" -m mentat.cli start "$@"', run_sh)
        self.assertIn('"%PYTHON%" -m mentat.cli start %*', run_bat)

    def test_cleanup_blocks_unknown_process_on_configured_port(self):
        with TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            config = self.make_config(data_dir, port=8888)
            listener = lifecycle.Listener(pid=9988, port=8888, local_address="127.0.0.1:8888", raw="")
            with patch.object(lifecycle, "netstat_listeners", return_value=[listener]), patch.object(
                lifecycle, "process_commandline", return_value=""
            ), patch.object(lifecycle, "probe_mentat", return_value=False):
                report = lifecycle.cleanup_mentat_listeners(config)

        self.assertFalse(report["ok"])
        self.assertEqual(report["actions"][0]["action"], "blocked_non_mentat")
        self.assertEqual(report["actions"][0]["pid"], 9988)

    def test_cleanup_ignores_listener_on_a_different_port(self):
        with TemporaryDirectory() as tmpdir:
            config = self.make_config(Path(tmpdir), port=8895)
            listener = lifecycle.Listener(pid=8881, port=8888, local_address="127.0.0.1:8888", raw="")
            with patch.object(lifecycle, "netstat_listeners", return_value=[listener]), patch.object(
                lifecycle, "kill_pid"
            ) as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config)

        self.assertTrue(report["ok"])
        self.assertEqual(report["managed_ports"], [8895])
        self.assertEqual(report["actions"], [{"action": "no_managed_listeners", "ports": [8895]}])
        kill_pid.assert_not_called()

    def test_probe_only_listener_on_configured_port_is_blocked_not_killed(self):
        with TemporaryDirectory() as tmpdir:
            config = self.make_config(Path(tmpdir), port=8895)
            listener = lifecycle.Listener(pid=8896, port=8895, local_address="127.0.0.1:8895", raw="")
            with patch.object(lifecycle, "netstat_listeners", return_value=[listener]), patch.object(
                lifecycle, "process_commandline", return_value="python /tmp/unrelated_server.py"
            ), patch.object(lifecycle, "probe_mentat", return_value=True), patch.object(
                lifecycle, "kill_pid"
            ) as kill_pid:
                report = lifecycle.cleanup_mentat_listeners(config)

        self.assertFalse(report["ok"])
        self.assertEqual(report["actions"][0]["action"], "blocked_non_mentat")
        self.assertEqual(report["actions"][0]["reasons"], ["overview_probe"])
        kill_pid.assert_not_called()

    def test_public_reports_do_not_expose_paths_commands_or_raw_runtime_state(self):
        with TemporaryDirectory() as tmpdir:
            config = self.make_config(Path(tmpdir), port=8895)
            state_path = lifecycle.lifecycle_state_path(config)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"pid": 4321, "data_dir": str(config.data_dir)}) + "\n", encoding="utf-8")
            listener = lifecycle.Listener(pid=4321, port=8895, local_address="127.0.0.1:8895", raw="private")
            private_command = f'python "{lifecycle.BASE_DIR / "server.py"}" --data-dir {config.data_dir}'
            with patch.object(lifecycle, "netstat_listeners", return_value=[listener]), patch.object(
                lifecycle, "process_commandline", return_value=private_command
            ), patch.object(lifecycle, "probe_mentat", return_value=True):
                report = lifecycle.status_report(config)

        serialized = json.dumps(report)
        self.assertNotIn(str(config.data_dir), serialized)
        self.assertNotIn('"command_line":', serialized)
        self.assertNotIn('"runtime_state":', serialized)
        self.assertNotIn('"state_path":', serialized)

    def test_preflight_rejects_non_loopback_host_before_cleanup(self):
        with TemporaryDirectory() as tmpdir, patch.object(lifecycle, "cleanup_mentat_listeners") as cleanup, patch.object(
            lifecycle, "print_report"
        ) as print_report:
            exit_code = lifecycle.main(["preflight", "--host", "0.0.0.0", "--data-dir", tmpdir])

        self.assertEqual(exit_code, 2)
        cleanup.assert_not_called()
        self.assertIn("non-loopback", print_report.call_args.args[0]["error"])

    def test_preflight_blocks_initializer_failure_before_cleanup(self):
        with TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "platform-data"
            config = self.make_config(data_root)
            config = server.AppConfig(
                **{
                    **config.__dict__,
                    "data_dir_source": "platform_default",
                }
            )
            cli_args = server.parse_cli_args([])
            with patch.object(
                lifecycle,
                "load_runtime_request",
                return_value=(cli_args, config),
            ), patch.object(
                server,
                "prepare_data_root_for_startup",
                return_value="Mentat could not safely initialize the selected data root (unsafe).",
            ), patch.object(lifecycle, "cleanup_mentat_listeners") as cleanup, patch.object(
                lifecycle, "print_report"
            ) as print_report:
                result = lifecycle.main(["preflight"])

            self.assertEqual(result, 2)
            self.assertFalse(data_root.exists())
            cleanup.assert_not_called()
            self.assertIn("initialize", print_report.call_args.args[0]["error"])

    def test_preflight_initializes_before_listener_cleanup(self):
        with TemporaryDirectory() as tmpdir:
            config = self.make_config(Path(tmpdir) / "platform-data")
            cli_args = server.parse_cli_args([])
            order = []
            with patch.object(
                lifecycle,
                "load_runtime_request",
                return_value=(cli_args, config),
            ), patch.object(
                server,
                "prepare_data_root_for_startup",
                side_effect=lambda _config: order.append("initialize"),
            ), patch.object(
                lifecycle,
                "cleanup_mentat_listeners",
                side_effect=lambda *_args, **_kwargs: order.append("cleanup") or {"ok": True},
            ), patch.object(lifecycle, "print_report"):
                result = lifecycle.main(["preflight"])

            self.assertEqual(result, 0)
            self.assertEqual(order, ["initialize", "cleanup"])

    def test_preflight_print_config_remains_side_effect_free(self):
        with TemporaryDirectory() as tmpdir, patch.object(lifecycle, "cleanup_mentat_listeners") as cleanup, patch.object(
            lifecycle, "print_report"
        ) as print_report, patch.object(server, "prepare_data_root_for_startup") as initialize:
            exit_code = lifecycle.main(
                ["preflight", "--host", "0.0.0.0", "--data-dir", tmpdir, "--print-config"]
            )

        self.assertEqual(exit_code, 0)
        cleanup.assert_not_called()
        initialize.assert_not_called()
        print_report.assert_not_called()

    def test_preflight_legacy_migration_mode_remains_side_effect_free(self):
        with patch.object(lifecycle, "cleanup_mentat_listeners") as cleanup, patch.object(
            lifecycle,
            "print_report",
        ) as print_report, patch.object(server, "prepare_data_root_for_startup") as initialize:
            exit_code = lifecycle.main(
                ["preflight", "--preview-legacy-migration"]
            )

        self.assertEqual(exit_code, 0)
        cleanup.assert_not_called()
        initialize.assert_not_called()
        print_report.assert_not_called()

    def test_preflight_schema_migration_mode_remains_side_effect_free(self):
        with patch.object(lifecycle, "cleanup_mentat_listeners") as cleanup, patch.object(
            lifecycle,
            "print_report",
        ) as print_report, patch.object(server, "prepare_data_root_for_startup") as initialize:
            exit_code = lifecycle.main(
                ["preflight", "--preview-schema-migration"]
            )

        self.assertEqual(exit_code, 0)
        cleanup.assert_not_called()
        initialize.assert_not_called()
        print_report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
