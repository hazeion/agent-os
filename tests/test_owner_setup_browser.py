import os
from pathlib import Path
import shutil
import subprocess
import unittest

from tests import test_owner_setup_gateway as gateway_tests


@unittest.skipUnless(os.environ.get('CHROME_PATH') and shutil.which('node'), 'Explicit Chrome path and Node required')
class OwnerSetupBrowserTests(unittest.TestCase):
    def test_real_browser_redirect_and_restrictive_csp_control(self):
        for blocking in (True, False):
            with self.subTest(blocking=blocking):
                fixture = gateway_tests.OwnerSetupGatewayTests()
                fixture.setUp()
                try:
                    environment = {key: value for key, value in os.environ.items() if key in {'PATH', 'SystemRoot', 'SYSTEMROOT', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'CHROME_PATH'}}
                    environment.update(MENTAT_SETUP_TEST_PORT=str(fixture.port), MENTAT_SETUP_TEST_GRANT=fixture.ceremony.take_terminal_grant(), MENTAT_SETUP_TEST_BLOCK='1' if blocking else '0')
                    script = Path(__file__).resolve().parents[1] / 'web' / 'scripts' / 'owner-setup-browser-smoke.mjs'
                    result = subprocess.run([shutil.which('node'), str(script)], env=environment, capture_output=True, text=True, timeout=40)
                    self.assertEqual(result.returncode, 0, result.stderr[-1500:])
                    self.assertIn('CSP control blocked' if blocking else 'permitted Google redirect', result.stdout)
                finally:
                    fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
