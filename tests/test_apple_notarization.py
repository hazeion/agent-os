import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import apple_notarization


SUBMISSION_ID = "aecd1025-cbf2-4f18-86a7-24c607387e20"


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class FakeNotarytool:
    def __init__(self, statuses, *, clock=None, info_duration=0):
        self.statuses = list(statuses)
        self.commands = []
        self.timeouts = []
        self.clock = clock
        self.info_duration = info_duration

    def __call__(self, command, *, check, text, timeout, stdout=None):
        self.commands.append(list(command))
        self.timeouts.append(timeout)
        action = command[2]
        if action == "submit":
            json.dump({"id": SUBMISSION_ID}, stdout)
        elif action == "info":
            result = self.statuses.pop(0)
            if self.clock is not None:
                self.clock.value += self.info_duration
            if isinstance(result, BaseException):
                raise result
            json.dump({"id": SUBMISSION_ID, "status": result}, stdout)
        elif action == "log":
            Path(command[-1]).write_text('{"status":"complete"}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)


class AppleNotarizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.package = root / "Mentat-signed.pkg"
        self.package.write_bytes(b"signed package")
        self.summary = root / "summary.md"
        self.output = root / "output.txt"
        self.environment = {
            "RUNNER_TEMP": str(root),
            "GITHUB_STEP_SUMMARY": str(self.summary),
            "GITHUB_OUTPUT": str(self.output),
            "MENTAT_MACOS_NOTARY_DEADLINE_EPOCH": "11000",
            "MAC_NOTARY_APPLE_ID": "notary@example.invalid",
            "MAC_NOTARY_PASSWORD": "test fixture",  # pragma: allowlist secret
            "MAC_NOTARY_TEAM_ID": "TEAM123456",
        }

    def tearDown(self):
        self.temp.cleanup()

    def wait_case(self, statuses, *, deadline_epoch=11000, info_duration=0):
        self.environment["MENTAT_MACOS_NOTARY_DEADLINE_EPOCH"] = str(deadline_epoch)
        clock = FakeClock()
        runner = FakeNotarytool(statuses, clock=clock, info_duration=info_duration)
        result = apple_notarization.wait_for_submission(
            SUBMISSION_ID,
            self.environment,
            runner=runner,
            monotonic=clock.monotonic,
            wall_clock=lambda: 1000.0,
            sleep=clock.sleep,
        )
        return result, clock, runner

    def test_submits_once_then_follows_same_request_until_accepted(self):
        clock = FakeClock()
        runner = FakeNotarytool(["In Progress", "Accepted"])
        submitted = apple_notarization.submit_package(
            self.package,
            self.environment,
            runner=runner,
            monotonic=clock.monotonic,
            wall_clock=lambda: 1000.0,
        )
        result = apple_notarization.wait_for_submission(
            submitted,
            self.environment,
            runner=runner,
            monotonic=clock.monotonic,
            wall_clock=lambda: 1000.0,
            sleep=clock.sleep,
        )
        self.assertEqual(result, SUBMISSION_ID)
        self.assertEqual(
            [command[2] for command in runner.commands],
            ["submit", "info", "info", "log"],
        )
        self.assertEqual(sum(command[2] == "submit" for command in runner.commands), 1)
        self.assertTrue(all(SUBMISSION_ID in command for command in runner.commands[1:]))
        self.assertEqual(clock.value, apple_notarization.POLL_INTERVAL_SECONDS)
        self.assertIn(SUBMISSION_ID, self.summary.read_text(encoding="utf-8"))
        self.assertEqual(
            self.output.read_text(encoding="utf-8"),
            f"submission_id={SUBMISSION_ID}\n",
        )
        self.assertLessEqual(max(runner.timeouts), apple_notarization.SUBMIT_TIMEOUT_SECONDS)

    def test_transient_status_failure_does_not_resubmit(self):
        failure = subprocess.TimeoutExpired(["xcrun", "notarytool", "info"], 120)
        result, _, runner = self.wait_case([failure, "Accepted"])
        self.assertEqual(result, SUBMISSION_ID)
        self.assertEqual(sum(command[2] == "submit" for command in runner.commands), 0)
        self.assertEqual(sum(command[2] == "info" for command in runner.commands), 2)

    def test_deadline_caps_sleep_and_reports_submission_and_last_status(self):
        with self.assertRaises(apple_notarization.NotarizationError) as caught:
            self.wait_case(["In Progress"], deadline_epoch=1010)
        message = str(caught.exception)
        self.assertIn("Status deadline expired", message)
        self.assertIn(SUBMISSION_ID, message)
        self.assertIn("In Progress", message)

    def test_rejected_submission_fetches_log_and_fails_closed(self):
        with self.assertRaises(apple_notarization.NotarizationError) as caught:
            self.wait_case(["Rejected"])
        self.assertIn("Rejected", str(caught.exception))
        self.assertTrue((Path(self.temp.name) / "mentat-notary-log.json").is_file())

    def test_expired_job_relative_window_never_uploads(self):
        clock = FakeClock()
        runner = FakeNotarytool([])
        self.environment["MENTAT_MACOS_NOTARY_DEADLINE_EPOCH"] = "999"
        with self.assertRaises(apple_notarization.NotarizationError) as caught:
            apple_notarization.submit_package(
                self.package,
                self.environment,
                runner=runner,
                monotonic=clock.monotonic,
                wall_clock=lambda: 1000.0,
            )
        self.assertIn("no upload was attempted", str(caught.exception))
        self.assertEqual(runner.commands, [])

    def test_accepted_at_deadline_does_not_overrun_for_log(self):
        with self.assertRaises(apple_notarization.NotarizationError) as caught:
            self.wait_case(["Accepted"], deadline_epoch=1010, info_duration=10)
        self.assertIn("accepted", str(caught.exception).lower())
        self.assertIn("no time remained", str(caught.exception))

    def test_unknown_status_fails_closed(self):
        with self.assertRaises(apple_notarization.NotarizationError) as caught:
            self.wait_case(["Mystery"])
        self.assertIn("Unexpected", str(caught.exception))

    def test_ten_consecutive_status_failures_stop_without_submit(self):
        failures = [
            subprocess.TimeoutExpired(["xcrun", "notarytool", "info"], 120)
            for _ in range(10)
        ]
        with self.assertRaises(apple_notarization.NotarizationError) as caught:
            self.wait_case(failures)
        self.assertIn("10 consecutive checks", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
