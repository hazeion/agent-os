from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

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

    def test_cleanup_kills_listener_tracked_by_runtime_state(self):
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
                lifecycle, "kill_pid", return_value=(True, "terminated")
            ):
                report = lifecycle.cleanup_mentat_listeners(config)

        self.assertTrue(report["ok"])
        self.assertEqual(report["actions"][0]["action"], "killed")
        self.assertEqual(report["actions"][0]["pid"], 4321)
        self.assertFalse(state_path.exists())

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


if __name__ == "__main__":
    unittest.main()
