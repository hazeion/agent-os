from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, call, patch

import mentat_lifecycle as lifecycle
import server


class LocalServerLifecycleTests(unittest.TestCase):
    def make_config(self, data_dir: Path, port: int = 8888) -> server.AppConfig:
        return server.AppConfig(
            config_files=tuple(),
            host="127.0.0.1",
            port=port,
            data_dir=data_dir,
            public_dir=server.PUBLIC_DIR,
            hermes_home=server.HERMES_HOME,
            obsidian_vault=server.OBSIDIAN_VAULT,
            display_name=None,
            greeting_prefix=None,
        )

    def test_managed_ports_include_primary_and_dev_ports(self):
        self.assertEqual(lifecycle.managed_ports(8888), [8888, 8890])
        self.assertEqual(lifecycle.managed_ports(9001), [8888, 8890, 9001])

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

        self.assertTrue(ipv4_result[0])
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

    def test_commandline_detection_requires_exact_project_script_path(self):
        server_path = lifecycle.BASE_DIR / "server.py"
        windows_server_path = str(server_path).replace("/", "\\")
        self.assertTrue(lifecycle.looks_like_mentat_commandline(f'python "{server_path}" --port 8888'))
        self.assertTrue(lifecycle.looks_like_mentat_commandline(f'python "{windows_server_path}" --port 8888'))
        self.assertFalse(lifecycle.looks_like_mentat_commandline("python /tmp/server.py --port 8888"))
        self.assertFalse(lifecycle.looks_like_mentat_commandline(f"python {server_path}.backup --port 8888"))
        self.assertFalse(lifecycle.looks_like_mentat_commandline(f"python {lifecycle.BASE_DIR / 'other.py'} --port 8888"))

    def test_launchers_pass_absolute_script_paths(self):
        run_sh = (lifecycle.BASE_DIR / "run.sh").read_text(encoding="utf-8")
        run_bat = (lifecycle.BASE_DIR / "run.bat").read_text(encoding="utf-8")

        self.assertIn('"$SCRIPT_DIR/mentat_lifecycle.py" preflight', run_sh)
        self.assertIn('"$SCRIPT_DIR/server.py" "$@"', run_sh)
        self.assertIn('"%CD%\\mentat_lifecycle.py" preflight', run_bat)
        self.assertIn('"%CD%\\server.py" %*', run_bat)

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


if __name__ == "__main__":
    unittest.main()
