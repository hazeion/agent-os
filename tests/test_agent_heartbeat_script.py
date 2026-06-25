import importlib.util
import unittest
from argparse import Namespace
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "agent_heartbeat.py"
spec = importlib.util.spec_from_file_location("agent_heartbeat", SCRIPT_PATH)
agent_heartbeat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent_heartbeat)


class AgentHeartbeatScriptTests(unittest.TestCase):
    def test_build_payload_maps_cli_args_to_agent_pulse_contract(self):
        args = Namespace(
            agent_id="agent_test_worker",
            name="Test Worker",
            status="active",
            current_task="Publish heartbeat",
            project="Mentat",
            cwd="E:/code/agent-os",
            model="test-model",
            source="heartbeat-script",
            latest_output="Working",
            needs_user_input=False,
            related_task_id="task_agent_pulse_producer_wiring",
        )

        payload = agent_heartbeat.build_payload(args)

        self.assertEqual(payload["id"], "agent_test_worker")
        self.assertEqual(payload["name"], "Test Worker")
        self.assertEqual(payload["status"], "running")
        self.assertEqual(payload["current_task"], "Publish heartbeat")
        self.assertEqual(payload["related_task_id"], "task_agent_pulse_producer_wiring")
        self.assertFalse(payload["needs_user_input"])

    def test_parser_supports_beat_and_run_producer_modes(self):
        parser = agent_heartbeat.build_parser()

        beat_args = parser.parse_args([
            "beat",
            "--name",
            "Hermes",
            "--status",
            "blocked",
            "--needs-user-input",
            "true",
        ])
        run_args = parser.parse_args([
            "run",
            "--name",
            "Codex Worker",
            "--interval",
            "5",
            "--",
            "python",
            "worker.py",
        ])
        example_args = parser.parse_args(["examples"])

        self.assertEqual(beat_args.command_name, "beat")
        self.assertEqual(beat_args.status, "blocked")
        self.assertTrue(beat_args.needs_user_input)
        self.assertEqual(run_args.command_name, "run")
        self.assertEqual(run_args.interval, 5)
        self.assertEqual(agent_heartbeat.command_after_separator(run_args.command), ["python", "worker.py"])
        self.assertEqual(example_args.command_name, "examples")

    def test_example_commands_cover_beat_and_wrapped_run_wiring(self):
        commands = agent_heartbeat.example_commands(base_url="http://127.0.0.1:8890")

        self.assertIn("beat", commands)
        self.assertIn("run", commands)
        self.assertIn("agent_heartbeat.py beat", commands["beat"])
        self.assertIn("agent_heartbeat.py run", commands["run"])
        self.assertIn("127.0.0.1:8890", commands["beat"])

    def test_heartbeat_url_targets_project_owned_api(self):
        self.assertEqual(
            agent_heartbeat.heartbeat_url("http://127.0.0.1:8888/"),
            "http://127.0.0.1:8888/api/agents/heartbeat",
        )


if __name__ == "__main__":
    unittest.main()
