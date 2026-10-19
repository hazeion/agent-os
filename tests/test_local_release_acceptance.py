"""Boundary checks for the disposable release runner; real execution is a separate command."""
from pathlib import Path
import json
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import mentat_acceptance as acceptance


class LocalReleaseAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.port = patch.object(acceptance, "free_port", return_value=54321)
        self.closed = patch.object(acceptance, "listener_closed", return_value=True)
        self.port.start()
        self.closed.start()
        self.groups = patch.object(acceptance, "process_group_absent", return_value=True)
        self.groups.start()
        self.addCleanup(self.groups.stop)
        self.addCleanup(self.port.stop)
        self.addCleanup(self.closed.stop)

    def test_credentials_and_user_configuration_do_not_enter_child_environment(self):
        with patch.dict(acceptance.os.environ, {"PATH": "/tool/bin", "HOME": "/owner",
                        "OPENAI_API_KEY": "never-forward", "MENTAT_DATA_DIR": "/owner/data",
                        "MENTAT_CONFIG": "/owner/settings", "HERMES_HOME": "/owner/hermes",
                        "GOOGLE_APPLICATION_CREDENTIALS": "/owner/key", "HTTPS_PROXY": "http://proxy"}, clear=True):
            environment = acceptance.isolated_environment(Path("/disposable"))
        self.assertEqual(environment["PATH"], "/tool/bin")
        self.assertEqual(environment["HOME"], "/disposable/home")
        self.assertEqual(environment["HERMES_HOME"], "/disposable/hermes")
        for key in ("OPENAI_API_KEY", "MENTAT_DATA_DIR", "MENTAT_CONFIG", "GOOGLE_APPLICATION_CREDENTIALS", "HTTPS_PROXY"):
            self.assertNotIn(key, environment)

    def test_nonfixed_requests_fail_before_network(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            with patch.object(journey.opener, "open") as opened:
                for path in ("https://example.invalid", "//outside.invalid", "/bridge/v1/anything", "/owner", "/api/runs/run_test/stop", "/api/unknown"):
                    with self.assertRaisesRegex(acceptance.AcceptanceFailure, "route_invalid"):
                        journey.request(path)
                opened.assert_not_called()

    def test_stop_cannot_claim_success_with_a_live_listener(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            with patch.object(journey, "cli", return_value={"ok": True}), patch.object(
                acceptance, "listener_closed", return_value=False
            ):
                journey.process = unittest.mock.Mock(returncode=143)
                journey.process.poll.return_value = None
                with self.assertRaisesRegex(acceptance.AcceptanceFailure, "listener_remains"):
                    journey.stop()
                self.assertIsNotNone(journey.process)

    def test_failed_stop_keeps_original_owned_process_handle(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            owned = unittest.mock.Mock()
            owned.poll.return_value = None
            owned.wait.side_effect = subprocess.TimeoutExpired("owned", 15)
            journey.process = owned
            with patch.object(journey, "cli", return_value={"ok": True}):
                with self.assertRaisesRegex(acceptance.AcceptanceFailure, "launcher_stop_timeout"):
                    journey.stop()
            self.assertIs(journey.process, owned)
            self.assertFalse(journey.cleanup())
            owned.terminate.assert_called_once()

    def test_early_launcher_exit_with_live_owned_group_refuses_cleanup(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            launcher = unittest.mock.Mock(pid=23456)
            launcher.poll.return_value = 7
            journey.process = launcher
            journey.launcher_groups.add(launcher.pid)
            self.assertEqual(journey.children, ())
            with patch.object(acceptance, "process_group_absent", return_value=False) as absent:
                self.assertFalse(journey.cleanup())
            launcher.terminate.assert_not_called()
            absent.assert_called_once_with(23456)

    def test_start_records_owned_group_before_early_health_failure(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            launcher = unittest.mock.Mock(pid=23456)
            launcher.poll.return_value = 7
            with patch.object(acceptance.subprocess, "Popen", return_value=launcher) as spawn:
                with self.assertRaisesRegex(acceptance.AcceptanceFailure, "launcher_exited"):
                    journey.start()
            self.assertIs(spawn.call_args.kwargs["start_new_session"], True)
            self.assertEqual(journey.launcher_groups, {23456})

    def test_incomplete_cleanup_preserves_owned_directory_and_fails_report(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "owned"
            root.mkdir()
            with patch.object(acceptance.tempfile, "mkdtemp", return_value=str(root)), patch.object(
                acceptance.Journey, "run", side_effect=acceptance.AcceptanceFailure("launcher_exited")
            ), patch.object(acceptance.tempfile, "TemporaryFile", return_value=unittest.mock.Mock()), patch.object(acceptance.Journey, "cleanup", return_value=False), patch.object(
                acceptance.shutil, "rmtree"
            ) as remove, patch("builtins.print") as output:
                self.assertEqual(acceptance.main([]), 1)
                remove.assert_not_called()
                self.assertIn('"owned_state_removed": false', output.call_args.args[0])
                self.assertIn('"cleanup_incomplete"', output.call_args.args[0])
                report = json.loads(output.call_args.args[0])
                self.assertEqual(report["primary_phase"], "setup")
                self.assertEqual(report["primary_code"], "launcher_exited")
            self.assertTrue(root.is_dir())

    def test_browser_timeout_retains_primary_failure_without_command_disclosure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "owned"
            root.mkdir()
            def timeout(journey, *_args, **_kwargs):
                journey.phase = "browser"
                raise subprocess.TimeoutExpired(["/private/command", "secret-token"], 40)
            def refuse_cleanup(journey):
                journey.launch_output.close()
                return False
            with patch.object(acceptance.tempfile, "mkdtemp", return_value=str(root)), patch.object(
                acceptance.Journey, "run", timeout
            ), patch.object(acceptance.Journey, "cleanup", refuse_cleanup), patch.object(
                acceptance.shutil, "rmtree"
            ) as remove, patch("builtins.print") as output:
                self.assertEqual(acceptance.main([]), 1)
                remove.assert_not_called()
            report = json.loads(output.call_args.args[0])
            self.assertEqual(report["code"], "cleanup_incomplete")
            self.assertEqual(report["primary_phase"], "browser")
            self.assertEqual(report["primary_code"], "operation_timeout")
            self.assertFalse(report["owned_state_removed"])
            self.assertNotIn("secret-token", output.call_args.args[0])
            self.assertNotIn("/private/command", output.call_args.args[0])
            self.assertTrue(root.is_dir())

    def test_cleanup_report_checks_every_owned_boundary_after_browser_group_failure(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "owned"
            root.mkdir()
            browser = unittest.mock.Mock(pid=23456)
            browser.poll.return_value = 0
            launcher = unittest.mock.Mock(pid=34567)
            launcher.poll.return_value = 0
            def fail(journey, *_args, **_kwargs):
                journey.phase = "browser"
                journey.browser, journey.process = browser, launcher
                journey.launcher_groups = {launcher.pid}
                journey.children = (45678, 56789)
                raise acceptance.AcceptanceFailure("browser_child_remains")
            with patch.object(acceptance.tempfile, "mkdtemp", return_value=str(root)), patch.object(
                acceptance.Journey, "run", fail
            ), patch.object(acceptance, "process_group_absent", side_effect=lambda group: group != browser.pid) as groups, patch.object(
                acceptance, "process_absent", return_value=True
            ) as children, patch.object(acceptance.shutil, "rmtree") as remove, patch("builtins.print") as output:
                self.assertEqual(acceptance.main([]), 1)
                remove.assert_not_called()
            report = json.loads(output.call_args.args[0])
            self.assertEqual(report["primary_phase"], "browser")
            self.assertEqual(report["primary_code"], "browser_child_remains")
            self.assertEqual(report["cleanup"], {
                "browser_terminal": True, "browser_group_absent": False,
                "launcher_terminal": True, "launcher_groups_absent": True,
                "captured_children_absent": True, "listener_closed": True,
            })
            groups.assert_has_calls([unittest.mock.call(browser.pid), unittest.mock.call(launcher.pid)])
            children.assert_has_calls([unittest.mock.call(45678), unittest.mock.call(56789)])
            browser.terminate.assert_not_called()
            launcher.terminate.assert_not_called()
            browser.wait.assert_called_once_with(timeout=15)
            launcher.wait.assert_called_once_with(timeout=15)
            self.assertNotIn("23456", output.call_args.args[0])
            self.assertNotIn(str(root), output.call_args.args[0])

    def test_cleanup_exception_preserves_primary_code_without_exception_data(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "owned"
            root.mkdir()
            with patch.object(acceptance.tempfile, "mkdtemp", return_value=str(root)), patch.object(
                acceptance.Journey, "run", side_effect=acceptance.AcceptanceFailure("launcher_exited")
            ), patch.object(acceptance.tempfile, "TemporaryFile", return_value=unittest.mock.Mock()), patch.object(
                acceptance.Journey, "cleanup", side_effect=OSError("secret /owner/path")
            ), patch.object(acceptance.shutil, "rmtree") as remove, patch("builtins.print") as output:
                self.assertEqual(acceptance.main([]), 1)
                remove.assert_not_called()
            report = json.loads(output.call_args.args[0])
            self.assertEqual(report["primary_code"], "launcher_exited")
            self.assertEqual(report["code"], "cleanup_incomplete")
            self.assertNotIn("secret", output.call_args.args[0])
            self.assertNotIn("/owner", output.call_args.args[0])

    def test_restart_wait_has_a_deadline_and_does_not_relaunch(self):
        with patch.object(acceptance.time, "monotonic", side_effect=[0, 76]), patch.object(
            acceptance.socket, "socket"
        ) as socket:
            with self.assertRaisesRegex(acceptance.AcceptanceFailure, "restart_port_not_reusable"):
                acceptance.wait_for_reusable_port(54321)
            socket.assert_not_called()

    def test_browser_cleanup_failure_does_not_skip_owned_launcher_cleanup(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            browser = unittest.mock.Mock(pid=23456)
            browser.poll.return_value = None
            browser.wait.side_effect = subprocess.TimeoutExpired("browser", 15)
            launcher = unittest.mock.Mock()
            launcher.poll.return_value = None
            journey.browser, journey.process = browser, launcher
            with patch.object(acceptance, "process_group_absent", return_value=False):
                self.assertFalse(journey.cleanup())
            browser.terminate.assert_called_once()
            launcher.terminate.assert_called_once()
            launcher.wait.assert_called_once_with(timeout=15)

    def test_crash_before_stop_is_not_normalized(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            journey.process = unittest.mock.Mock()
            journey.process.poll.return_value = 241
            with patch.object(journey, "cli") as cli:
                with self.assertRaisesRegex(acceptance.AcceptanceFailure, "launcher_crashed_before_stop"):
                    journey.stop()
                cli.assert_not_called()

    def test_unrelated_nonzero_exit_is_not_success(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            journey.process = unittest.mock.Mock(returncode=7)
            journey.process.poll.return_value = None
            with patch.object(journey, "cli", return_value={"ok": True}):
                with self.assertRaisesRegex(acceptance.AcceptanceFailure, "launcher_stop_failed"):
                    journey.stop()

    def test_failure_report_never_prints_exception_data_or_private_paths(self):
        with patch.object(acceptance.Journey, "run", side_effect=OSError("secret /owner/path")), patch(
            "builtins.print"
        ) as output:
            self.assertEqual(acceptance.main([]), 1)
        report = output.call_args.args[0]
        self.assertNotIn("secret", report)
        self.assertNotIn("/owner", report)
        self.assertIn('"owned_state_removed": true', report)


if __name__ == "__main__":
    unittest.main()
