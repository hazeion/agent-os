"""Exercise browser startup failures without launching a browser or app."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest


@unittest.skipUnless(os.name == "posix" and shutil.which("node"), "POSIX executable fixtures and Node required")
class WebSmokeStartupTests(unittest.TestCase):
    def test_exited_browser_reports_status_and_stderr_without_readiness_timeout(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            chrome = root / "chrome"
            chrome.write_text("#!/bin/sh\necho 'synthetic Chrome startup refusal' >&2\nexit 23\n")
            chrome.chmod(0o700)
            environment = dict(os.environ, CHROME_PATH=str(chrome),
                               MENTAT_WEB_BROWSER_RUNTIME_DIR=str(root / "web-foundation-smoke-runtime"))
            result = subprocess.run([shutil.which("node"), "scripts/web_foundation_smoke.mjs"],
                                    cwd=Path(__file__).resolve().parents[1], env=environment,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Chrome exited before debug readiness (code=23", result.stderr)
            self.assertIn("synthetic Chrome startup refusal", result.stderr)
            self.assertNotIn("Timed out waiting", result.stderr)
            self.assertFalse(any((root / "web-foundation-smoke-runtime").glob("run-*")))
