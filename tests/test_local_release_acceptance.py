"""Boundary checks for the disposable release runner; real execution is a separate command."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import mentat_acceptance as acceptance


LISTENER_PROBE = acceptance.listener_closed
TRANSPORT = {"sent_requests": 0, "text_frames": 0, "invalid_frames": 0, "matched_responses": 0, "pending_calls": 0, "socket_closed": False, "socket_error": False, "close_code": 0, "counters_saturated": False}
OBSERVATION = {"ready_state": "complete", "location_category": "tasks", "snapshots": 1, "observer_elapsed_ms": 1}


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
        self.assertEqual(environment["HOME"], str(Path("/disposable") / "home"))
        self.assertEqual(environment["HERMES_HOME"], str(Path("/disposable") / "hermes"))
        for key in ("OPENAI_API_KEY", "MENTAT_DATA_DIR", "MENTAT_CONFIG", "GOOGLE_APPLICATION_CREDENTIALS", "HTTPS_PROXY"):
            self.assertNotIn(key, environment)

    def test_offline_journey_requires_current_backup_name_before_restore_preview(self):
        for version in (5, 4, 6):
            with self.subTest(version=version), TemporaryDirectory() as directory:
                journey = acceptance.Journey(Path(directory))
                self.addCleanup(journey.launch_output.close)
                name = f"mentat-backup-v{version}-" + "a" * 24 + ".zip"
                with patch.object(journey, "start"), patch.object(journey, "stop"), patch.object(
                    journey, "read_back"
                ), patch.object(journey, "request", side_effect=["Projects &amp; Tasks", {"project": {"id": "project_exact"}}, {"task": {"id": "task_exact"}}]), patch.object(
                    journey, "cli", side_effect=[{"ok": True}, {"status": "created", "backup_name": name}, {"status": "ready", "issues": []}]
                ) as cli:
                    if version == 5:
                        self.assertTrue(journey.run()["ok"])
                        self.assertEqual(cli.call_args.args, ("restore", [str(journey.data / "backups" / name)]))
                    else:
                        with self.assertRaisesRegex(acceptance.AcceptanceFailure, "backup_name"):
                            journey.run()
                        self.assertEqual(cli.call_count, 2)
                        self.assertNotIn("offline_backup_validated_by_restore_preview", journey.completed)

    def test_unsupported_host_refuses_before_journey_or_process_creation(self):
        with patch.object(acceptance, "os", SimpleNamespace(name="nt")), patch.object(
            acceptance, "Journey"
        ) as journey, patch.object(acceptance.subprocess, "Popen") as spawn, patch("builtins.print") as output:
            self.assertEqual(acceptance.main([]), 1)
            journey.assert_not_called()
            spawn.assert_not_called()
        report = json.loads(output.call_args.args[0])
        self.assertEqual(report["code"], "posix_host_required")
        self.assertTrue(report["owned_state_removed"])

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

    @unittest.skipUnless(acceptance.os.name == "posix", "POSIX-only main lifecycle boundary")
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

    @unittest.skipUnless(acceptance.os.name == "posix", "POSIX-only main lifecycle boundary")
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

    @unittest.skipUnless(acceptance.os.name == "posix", "POSIX-only main lifecycle boundary")
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
                journey.browser_cleanup_deadline = 0
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
                "browser_helper_terminal": True, "browser_helper_group_absent": True,
                "browser_debug_listener_closed": True,
                "launcher_terminal": True, "launcher_groups_absent": True,
                "captured_children_absent": True, "listener_closed": True,
            })
            groups.assert_has_calls([unittest.mock.call(browser.pid), unittest.mock.call(launcher.pid)])
            children.assert_has_calls([unittest.mock.call(45678), unittest.mock.call(56789)])
            browser.terminate.assert_not_called()
            launcher.terminate.assert_not_called()
            self.assertEqual(browser.wait.call_count, 1)
            self.assertGreaterEqual(browser.wait.call_args.kwargs["timeout"], 0)
            self.assertLessEqual(browser.wait.call_args.kwargs["timeout"], 15)
            launcher.wait.assert_called_once_with(timeout=15)
            self.assertNotIn("23456", output.call_args.args[0])
            self.assertNotIn(str(root), output.call_args.args[0])

    @unittest.skipUnless(acceptance.os.name == "posix", "POSIX-only main lifecycle boundary")
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

    def test_browser_helper_is_a_required_fixed_regular_source_sibling(self):
        original = acceptance.browser_helper_path()
        with TemporaryDirectory() as directory, patch.object(acceptance, "REPO", Path(directory)):
            with self.assertRaisesRegex(acceptance.AcceptanceFailure, "browser_helper_missing"):
                acceptance.browser_helper_path()
            sibling = Path(directory) / "scripts" / original.name
            sibling.parent.mkdir()
            sibling.write_bytes(original.read_bytes())
            self.assertEqual(acceptance.browser_helper_path(), sibling)
            if acceptance.os.name != "nt":
                sibling.unlink()
                sibling.symlink_to(original)
                with self.assertRaisesRegex(acceptance.AcceptanceFailure, "browser_helper_missing"):
                    acceptance.browser_helper_path()

    def test_debug_listener_requires_exact_loopback_and_owned_group_without_signals(self):
        browser = unittest.mock.Mock(pid=23456)
        browser.poll.return_value = None
        for address, group, expected in ((b"127.0.0.1:54322", 23456, True),
                                         (b"127.0.0.1:54322", 99999, False),
                                         (b"*:54322", 23456, False),
                                         (b"127.0.0.1:54323", 23456, False)):
            with self.subTest(address=address, group=group), patch.object(
                acceptance.shutil, "which", return_value="/lsof"
            ), patch.object(acceptance.subprocess, "run", return_value=unittest.mock.Mock(
                returncode=0, stdout=b"p23456\nn" + address + b"\n"
            )), patch.object(acceptance.os, "getpgid", return_value=group, create=True):
                self.assertIs(acceptance.browser_listener_owned(browser, 54322, {}), expected)
        browser.terminate.assert_not_called()

    def test_browser_helper_start_failure_keeps_both_owned_handles(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            browser = unittest.mock.Mock(pid=23456)
            helper = unittest.mock.Mock(pid=34567)
            browser.poll.return_value = helper.poll.return_value = None
            helper.stdin.write.side_effect = BrokenPipeError
            with patch.object(acceptance.shutil, "which", return_value="/node"), patch.object(
                acceptance, "browser_listener_owned", return_value=True
            ), patch.object(acceptance.subprocess, "Popen", side_effect=[browser, helper]) as spawned:
                with self.assertRaises(BrokenPipeError):
                    journey.render_browser(Path("/chrome"), "project_exact", "task_exact")
            self.assertEqual(spawned.call_args_list[0].args[0][-1], journey.origin + "/tasks")
            self.assertIs(journey.browser, browser)
            self.assertIs(journey.browser_helper, helper)
            self.assertTrue(journey.cleanup())
            browser.terminate.assert_called_once()
            helper.terminate.assert_called_once()
            helper.stdin.close.assert_called_once()
            self.assertLessEqual(browser.wait.call_args.kwargs["timeout"], 15)
            self.assertLessEqual(helper.wait.call_args.kwargs["timeout"], browser.wait.call_args.kwargs["timeout"])

    def test_invisible_or_unbound_browser_evidence_never_claims_render_success(self):
        for invalid in (False, 1):
            with self.subTest(invalid=invalid), TemporaryDirectory() as directory:
                journey = acceptance.Journey(Path(directory))
                self.addCleanup(journey.launch_output.close)
                browser = unittest.mock.Mock(pid=23456)
                browser.poll.return_value = None
                helper = unittest.mock.Mock(pid=34567, returncode=0)
                checks = {name: True for name in acceptance.BROWSER_CHECKS}
                checks["task_visible"] = invalid
                result = {"schema_version": 1, "ready": True, "code": "ready", "checks": checks, "diagnostics": {name: True for name in acceptance.BROWSER_DIAGNOSTICS}, "observation": dict(OBSERVATION), "transport": dict(TRANSPORT), "stage": "ready"}
                output = unittest.mock.MagicMock()
                output.__enter__.return_value = output
                output.read.return_value = (json.dumps(result) + "\n").encode()
                with patch.object(acceptance.shutil, "which", return_value="/node"), patch.object(
                    acceptance, "browser_listener_owned", return_value=True
                ), patch.object(acceptance.subprocess, "Popen", side_effect=[browser, helper]), patch.object(
                    acceptance.tempfile, "TemporaryFile", return_value=output
                ), patch.object(acceptance.os, "pread", side_effect=lambda *_: output.read.return_value, create=True):
                    with self.assertRaisesRegex(acceptance.AcceptanceFailure, "browser_(readiness_failed|output_invalid)"):
                        journey.render_browser(Path("/chrome"), "project_exact", "task_exact")
                browser.terminate.assert_not_called()
                self.assertIs(journey.browser, browser)
                self.assertIs(journey.browser_helper, helper)

    def test_failed_positive_browser_stop_cannot_reset_cleanup_deadline(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            browser = unittest.mock.Mock(pid=23456, returncode=None)
            browser.poll.return_value = None
            browser.wait.side_effect = subprocess.TimeoutExpired("owned", 15)
            helper = unittest.mock.Mock(pid=34567, returncode=0)
            helper.poll.return_value = 0
            checks = {name: True for name in acceptance.BROWSER_CHECKS}
            output = unittest.mock.MagicMock()
            output.__enter__.return_value = output
            output.read.return_value = (json.dumps({"schema_version": 1, "ready": True, "code": "ready", "checks": checks, "diagnostics": {name: True for name in acceptance.BROWSER_DIAGNOSTICS}, "observation": dict(OBSERVATION), "transport": dict(TRANSPORT), "stage": "ready"}) + "\n").encode()
            with patch.object(acceptance.shutil, "which", return_value="/node"), patch.object(
                acceptance, "browser_listener_owned", return_value=True
            ), patch.object(acceptance.subprocess, "Popen", side_effect=[browser, helper]), patch.object(
                acceptance.tempfile, "TemporaryFile", return_value=output
            ), patch.object(acceptance.os, "pread", side_effect=lambda *_: output.read.return_value, create=True), patch.object(acceptance.time, "monotonic", return_value=0):
                with self.assertRaisesRegex(acceptance.AcceptanceFailure, "browser_stop_timeout"):
                    journey.render_browser(Path("/chrome"), "project_exact", "task_exact")
            self.assertEqual(journey.browser_cleanup_deadline, 15)
            with patch.object(acceptance.time, "monotonic", return_value=20):
                self.assertFalse(journey.cleanup())
            self.assertEqual(journey.browser_cleanup_deadline, 15)
            browser.terminate.assert_called_once()
            self.assertEqual([call.kwargs["timeout"] for call in browser.wait.call_args_list], [15, 0])

    @unittest.skipUnless(acceptance.os.name == "posix", "POSIX-only main lifecycle boundary")
    def test_nonready_helper_fixed_code_and_stage_survive_actual_parent_report(self):
        checks = {name: False for name in acceptance.BROWSER_CHECKS}
        diagnostics = {name: False for name in acceptance.BROWSER_DIAGNOSTICS}
        for code, stage in (("browser_protocol_timeout", "runtime"), ("browser_protocol_failed", "focus"),
                            ("browser_target_rejected", "discovery"), ("browser_evaluation_exception", "evaluation"), ("browser_transport_closed", "runtime"), ("browser_transport_error", "page")):
            with self.subTest(code=code, stage=stage):
                raw = (json.dumps({"schema_version": 1, "ready": False, "code": code, "stage": stage,
                                   "checks": checks, "diagnostics": diagnostics, "observation": dict(OBSERVATION), "transport": dict(TRANSPORT)}) + "\n").encode()
                browser = unittest.mock.Mock(pid=23456); browser.poll.return_value = None
                helper = unittest.mock.Mock(pid=34567, returncode=1); helper.poll.return_value = 1
                def run(journey, *_args, **_kwargs):
                    journey.phase = "browser"
                    return journey.render_browser(Path("/chrome"), "project_exact", "task_exact")
                with patch.object(acceptance.Journey, "run", run), patch.object(acceptance.shutil, "which", return_value="/node"), patch.object(
                    acceptance, "browser_listener_owned", return_value=True
                ), patch.object(acceptance.subprocess, "Popen", side_effect=[browser, helper]), patch.object(
                    acceptance.os, "pread", return_value=raw, create=True
                ), patch("builtins.print") as output:
                    self.assertEqual(acceptance.main([]), 1)
                report = json.loads(output.call_args.args[0])
                self.assertEqual(report["code"], "browser_readiness_failed")
                self.assertEqual(report["browser_helper_code"], code)
                self.assertEqual(report["browser_stage"], stage)
                self.assertEqual(report["browser_transport"], TRANSPORT)
                self.assertTrue(report["owned_state_removed"])

    def test_known_but_inconsistent_final_stage_cannot_claim_readiness(self):
        for ready, code, stage in ((True, "ready", "viewport"), (True, "browser_protocol_failed", "ready"),
                                   (False, "ready", "ready")):
            with self.subTest(ready=ready, code=code, stage=stage), TemporaryDirectory() as directory:
                journey = acceptance.Journey(Path(directory))
                self.addCleanup(journey.launch_output.close)
                checks = {name: True for name in acceptance.BROWSER_CHECKS}
                diagnostics = {name: True for name in acceptance.BROWSER_DIAGNOSTICS}
                raw = (json.dumps({"schema_version": 1, "ready": ready, "code": code, "stage": stage,
                                   "checks": checks, "diagnostics": diagnostics, "observation": dict(OBSERVATION), "transport": dict(TRANSPORT)}) + "\n").encode()
                browser = unittest.mock.Mock(pid=23456); browser.poll.return_value = None
                helper = unittest.mock.Mock(pid=34567, returncode=0)
                with patch.object(acceptance.shutil, "which", return_value="/node"), patch.object(
                    acceptance, "browser_listener_owned", return_value=True
                ), patch.object(acceptance.subprocess, "Popen", side_effect=[browser, helper]), patch.object(
                    acceptance.os, "pread", return_value=raw, create=True
                ):
                    with self.assertRaisesRegex(acceptance.AcceptanceFailure, "browser_readiness_failed"):
                        journey.render_browser(Path("/chrome"), "project_exact", "task_exact")
                browser.terminate.assert_not_called()
                self.assertNotIn("isolated_browser_render", journey.completed)

    @unittest.skipUnless(hasattr(acceptance.os, "pread"), "Native positional descriptor reads require POSIX")
    def test_progress_capture_is_bounded_positional_and_never_final_success(self):
        checks = {name: True for name in acceptance.BROWSER_CHECKS}
        diagnostics = {name: True for name in acceptance.BROWSER_DIAGNOSTICS}
        progress = {"schema_version": 1, "event": "progress", "checks": checks, "diagnostics": diagnostics, "observation": dict(OBSERVATION), "transport": dict(TRANSPORT), "stage": "evaluation"}
        with TemporaryDirectory() as directory, tempfile.TemporaryFile() as output:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            output.write((json.dumps(progress) + "\n" + '{"partial":').encode())
            output.flush()
            position = output.tell()
            self.assertIsNone(journey.capture_browser_evidence(output, require_final=False))
            self.assertEqual(output.tell(), position)
            self.assertEqual(journey.browser_checks, checks)
            self.assertEqual(journey.browser_diagnostics, diagnostics)
            with self.assertRaisesRegex(acceptance.AcceptanceFailure, "browser_output_invalid"):
                journey.capture_browser_evidence(output, require_final=True)
            output.seek(0); output.truncate()
            output.write((json.dumps(progress) + "\n").encode()); output.flush()
            with self.assertRaisesRegex(acceptance.AcceptanceFailure, "browser_final_evidence_missing"):
                journey.capture_browser_evidence(output, require_final=True)

    def test_invalid_framing_diagnostics_and_duplicate_final_refuse_success(self):
        checks = {name: True for name in acceptance.BROWSER_CHECKS}
        diagnostics = {name: True for name in acceptance.BROWSER_DIAGNOSTICS}
        final = {"schema_version": 1, "ready": True, "code": "ready", "checks": checks, "diagnostics": diagnostics, "observation": dict(OBSERVATION), "transport": dict(TRANSPORT), "stage": "ready"}
        line = (json.dumps(final) + "\n").encode()
        progress = {"schema_version": 1, "event": "progress", "checks": checks, "diagnostics": diagnostics, "observation": dict(OBSERVATION), "transport": dict(TRANSPORT), "stage": "evaluation"}
        progress_line = (json.dumps(progress) + "\n").encode()
        for raw in (line + line, line + b"unframed", b"x" * 16385,
                    progress_line * 17,
                    b" " * 12288 + progress_line,
                    b" " * 4096 + line,
                    line.replace(b'"ready": true', b'"ready": false, "ready": true'),
                    progress_line.replace(b'"event": "progress"', b'"event": "other", "event": "progress"') + line,
                    line.replace(b'"task_exists": true', b'"task_exists": false, "task_exists": true'),
                    (json.dumps({**final, "stage": "Page.navigate private"}) + "\n").encode(),
                    (json.dumps({**final, "stage": []}) + "\n").encode(),
                    (json.dumps({**final, "transport": {**TRANSPORT, "raw_frame": "private"}}) + "\n").encode(),
                    (json.dumps({**final, "transport": {**TRANSPORT, "sent_requests": True}}) + "\n").encode(),
                    (json.dumps({**final, "transport": {**TRANSPORT, "pending_calls": 2}}) + "\n").encode(),
                    (json.dumps({**final, "transport": {**TRANSPORT, "close_code": "private reason"}}) + "\n").encode(),
                    (json.dumps({**final, "observation": {**OBSERVATION, "location_category": "http://private.invalid"}}) + "\n").encode(),
                    (json.dumps({**final, "observation": {**OBSERVATION, "ready_state": []}}) + "\n").encode(),
                    (json.dumps({**final, "observation": {**OBSERVATION, "snapshots": True}}) + "\n").encode(),
                    (json.dumps({**final, "observation": {**OBSERVATION, "observer_elapsed_ms": 40001}}) + "\n").encode(),
                    (json.dumps({**final, "diagnostics": {**diagnostics, "raw_dom": "private"}}) + "\n").encode()):
            with self.subTest(raw_length=len(raw)), TemporaryDirectory() as directory, tempfile.TemporaryFile() as output:
                journey = acceptance.Journey(Path(directory))
                self.addCleanup(journey.launch_output.close)
                output.write(raw); output.flush()
                with patch.object(acceptance.os, "pread", return_value=raw, create=True), self.assertRaises(acceptance.AcceptanceFailure):
                    journey.capture_browser_evidence(output, require_final=True)
                self.assertEqual(journey.browser_checks, {})

    def test_browser_timeout_retains_progress_without_promoting_it_or_late_final(self):
        for late, capture_fault in ((False, False), (True, False), (False, True)):
            with self.subTest(late_final=late, capture_fault=capture_fault), TemporaryDirectory() as directory:
                journey = acceptance.Journey(Path(directory))
                self.addCleanup(journey.launch_output.close)
                checks = {name: True for name in acceptance.BROWSER_CHECKS}
                diagnostics = {name: True for name in acceptance.BROWSER_DIAGNOSTICS}
                record = {"schema_version": 1, "checks": checks, "diagnostics": diagnostics, "observation": dict(OBSERVATION), "transport": dict(TRANSPORT), "stage": "evaluation"}
                record.update({"ready": True, "code": "ready", "stage": "ready"} if late else {"event": "progress"})
                raw = (json.dumps(record) + "\n").encode()
                browser = unittest.mock.Mock(pid=23456); browser.poll.return_value = None
                helper = unittest.mock.Mock(pid=34567, returncode=0)
                clock = [0]
                def wait(**_):
                    clock[0] = 41
                    if not late:
                        raise subprocess.TimeoutExpired("owned", 40)
                helper.wait.side_effect = wait
                with patch.object(acceptance.shutil, "which", return_value="/node"), patch.object(
                    acceptance, "browser_listener_owned", return_value=True
                ), patch.object(acceptance.subprocess, "Popen", side_effect=[browser, helper]), patch.object(
                    acceptance.os, "pread", return_value=raw, side_effect=OSError("private read failure") if capture_fault else None, create=True
                ), patch.object(acceptance.time, "monotonic", side_effect=lambda: clock[0]):
                    with self.assertRaisesRegex(acceptance.AcceptanceFailure, "browser_readiness_timeout"):
                        journey.render_browser(Path("/chrome"), "project_exact", "task_exact")
                self.assertEqual(journey.browser_checks, {} if capture_fault else checks)
                self.assertEqual(journey.browser_diagnostics, {} if capture_fault else diagnostics)
                self.assertEqual(journey.browser_stage, None if capture_fault else ("ready" if late else "evaluation"))
                self.assertNotIn("isolated_browser_render", journey.completed)
                browser.terminate.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "Node is required for the fixed CDP helper contract")
    def test_browser_helper_fixed_predicates_and_transport_boundary(self):
        test_file = acceptance.REPO / "tests" / "test_local_release_browser.mjs"
        result = subprocess.run([shutil.which("node"), "--test", str(test_file)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
        self.assertEqual(result.returncode, 0, result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace"))

    def test_verified_browser_closure_survives_offline_work_only_for_exact_terminal_handles(self):
        for replacement in (None, "browser", "helper", "port", "live"):
            with self.subTest(replacement=replacement), TemporaryDirectory() as directory:
                journey = acceptance.Journey(Path(directory))
                self.addCleanup(journey.launch_output.close)
                journey.browser = unittest.mock.Mock(pid=23456)
                journey.browser_helper = unittest.mock.Mock(pid=34567)
                journey.browser.poll.return_value = journey.browser_helper.poll.return_value = 0
                journey.browser_debug_port = 54322
                journey.browser_cleanup_deadline = 15
                with patch.object(acceptance.time, "monotonic", return_value=10):
                    self.assertTrue(all(journey.browser_quiescence(15)))
                if replacement == "port":
                    journey.browser_debug_port = 54323
                elif replacement == "live":
                    journey.browser.poll.return_value = None
                elif replacement:
                    process = unittest.mock.Mock(pid=45678)
                    process.poll.return_value = 0
                    setattr(journey, "browser" if replacement == "browser" else "browser_helper", process)
                # Backup/restore-preview can finish after the already-proven window.
                with patch.object(acceptance.time, "monotonic", return_value=100):
                    if replacement is None:
                        calls = []
                        def cli(command, *_):
                            calls.append(command)
                            if command == "setup":
                                return {"ok": True}
                            if command == "backup":
                                return {"status": "created", "backup_name": "mentat-backup-v5-" + "a" * 24 + ".zip"}
                            return {"status": "ready", "issues": []}
                        with patch.object(journey, "start"), patch.object(journey, "stop"), patch.object(
                            journey, "read_back"
                        ), patch.object(journey, "render_browser"), patch.object(journey, "cli", side_effect=cli), patch.object(
                            journey, "request", side_effect=["Projects &amp; Tasks", {"project": {"id": "project_exact"}}, {"task": {"id": "task_exact"}}]
                        ):
                            self.assertTrue(journey.run(Path("/chrome"))["ok"])
                        self.assertEqual(calls, ["setup", "backup", "restore"])
                        self.assertIn("offline_backup_validated_by_restore_preview", journey.completed)
                        self.assertTrue(journey.cleanup())
                        journey.browser.terminate.assert_not_called()
                        journey.browser_helper.terminate.assert_not_called()
                        self.assertEqual(journey.browser_cleanup_deadline, 15)
                    else:
                        self.assertFalse(all(journey.browser_quiescence(15)))

    def test_browser_probe_error_still_stops_owned_launcher_and_refuses_cleanup(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            journey.browser = unittest.mock.Mock(pid=23456)
            journey.browser.poll.return_value = 0
            journey.process = unittest.mock.Mock(pid=34567)
            journey.process.poll.return_value = None
            journey.browser_debug_port = 54322
            journey.browser_cleanup_deadline = 15
            clock = [14.95]
            def pause(seconds):
                clock[0] += seconds
            def probe(port, **_):
                if port == journey.browser_debug_port:
                    raise OSError("private socket details")
                return True
            with patch.object(acceptance.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
                acceptance.time, "sleep", side_effect=pause
            ), patch.object(acceptance, "listener_closed", side_effect=probe):
                self.assertFalse(journey.cleanup())
            journey.process.terminate.assert_called_once()
            journey.process.wait.assert_called_once_with(timeout=15)
            journey.browser.terminate.assert_not_called()
            self.assertFalse(journey.cleanup_observations["browser_debug_listener_closed"])
            self.assertTrue(journey.cleanup_observations["launcher_terminal"])
            self.assertEqual(clock[0], 15)

    def test_listener_probe_requires_refusal_not_uncertain_connection_failure(self):
        for code, expected in ((0, False), (acceptance.errno.ECONNREFUSED, True),
                               (acceptance.errno.EINPROGRESS, False), (acceptance.errno.ENETUNREACH, False)):
            with self.subTest(code=code), patch.object(acceptance.socket, "socket") as factory:
                connection = factory.return_value.__enter__.return_value
                connection.connect_ex.return_value = code
                self.assertIs(LISTENER_PROBE(54322, timeout=0.01), expected)
                connection.settimeout.assert_called_once_with(0.01)
                connection.connect_ex.assert_called_once_with(("127.0.0.1", 54322))

    def test_debug_listener_quiescence_caps_probe_to_remaining_original_budget(self):
        with TemporaryDirectory() as directory:
            journey = acceptance.Journey(Path(directory))
            self.addCleanup(journey.launch_output.close)
            journey.browser_debug_port = 54322
            with patch.object(acceptance.time, "monotonic", return_value=14.99), patch.object(
                acceptance, "listener_closed", return_value=True
            ) as probe:
                self.assertTrue(all(journey.browser_quiescence(15)))
                self.assertLessEqual(probe.call_args.kwargs["timeout"], 0.011)
            journey.browser_debug_port = 54323  # A different port has no retained proof.
            with patch.object(acceptance.time, "monotonic", return_value=15), patch.object(
                acceptance, "listener_closed"
            ) as probe:
                self.assertFalse(journey.browser_quiescence(15)[2])
                probe.assert_not_called()

    def test_browser_quiescence_observes_owned_groups_within_original_deadline_only(self):
        for remains in (False, True):
            with self.subTest(permanent_group=remains), TemporaryDirectory() as directory:
                journey = acceptance.Journey(Path(directory))
                self.addCleanup(journey.launch_output.close)
                journey.browser = unittest.mock.Mock(pid=23456)
                journey.browser.poll.return_value = 0
                journey.browser_cleanup_deadline = 15
                clock = [14.9]
                def pause(seconds):
                    clock[0] += seconds
                with patch.object(acceptance.time, "monotonic", side_effect=lambda: clock[0]), patch.object(
                    acceptance.time, "sleep", side_effect=pause
                ), patch.object(acceptance, "process_group_absent", side_effect=lambda _: not remains and clock[0] >= 14.95):
                    self.assertEqual(journey.browser_quiescence(15)[0], not remains)
                    self.assertLessEqual(clock[0], 15)
                    self.assertEqual(journey.browser_cleanup_deadline, 15)
                    if remains:
                        self.assertFalse(journey.browser_quiescence(journey.begin_browser_cleanup())[0])
                        self.assertEqual(clock[0], 15)
                journey.browser.terminate.assert_not_called()

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
            journey.browser_cleanup_deadline = 0
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

    @unittest.skipUnless(acceptance.os.name == "posix", "POSIX-only main lifecycle boundary")
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
