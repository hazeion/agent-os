import http.client
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import threading
import time
import unittest
from urllib.parse import parse_qs, urlencode, urlsplit

from mentat.owner_setup_bridge import SetupBridge
from tests import test_owner_setup_ceremony as ceremony_tests


@unittest.skipUnless(shutil.which('node'), 'Node required for setup gateway integration')
class OwnerSetupGatewayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ceremony_tests.OwnerSetupCeremonyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.ceremony = self.fixture.ceremony()
        self.start_gateway(self.ceremony)

    def start_gateway(self, ceremony):
        self.ceremony = ceremony
        self.token = secrets.token_urlsafe(32)
        self.bridge = SetupBridge(self.ceremony, self.token)
        self.thread = threading.Thread(target=self.bridge.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_bridge)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            self.port = listener.getsockname()[1]
        env = {key: value for key, value in os.environ.items() if key in {'PATH', 'SystemRoot', 'SYSTEMROOT', 'TEMP', 'TMP'}}
        env.update(MENTAT_SETUP_ORIGIN='https://mentat.example', MENTAT_SETUP_BRIDGE=f'http://127.0.0.1:{self.bridge.server_port}', MENTAT_SETUP_TOKEN=self.token, MENTAT_SETUP_PORT=str(self.port))
        script = Path(__file__).resolve().parents[1] / 'web' / 'scripts' / 'owner-setup-gateway.mjs'
        self.process = subprocess.Popen([shutil.which('node'), str(script)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop_node)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.fail('setup gateway exited before ready')
            try:
                if self.request('GET', '/auth/setup')[0] == 200:
                    break
            except OSError:
                time.sleep(0.03)
        else:
            self.fail('setup gateway did not become ready')

    def stop_node(self):
        self.process.terminate()
        try:
            self.process.wait(5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(5)

    def stop_bridge(self):
        self.bridge.shutdown()
        self.bridge.server_close()
        self.thread.join(5)

    def request(self, method, path, body=None, headers=None):
        values = {'Host': 'mentat.example', 'X-Forwarded-Host': 'mentat.example', 'X-Forwarded-Proto': 'https'}
        values.update(headers or {})
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=18)
        try:
            connection.request(method, path, body=body, headers=values)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_complete_browser_proof_leaves_confirmation_in_terminal(self):
        grant = self.ceremony.take_terminal_grant()
        status, headers, body = self.request('POST', '/auth/setup/start', urlencode({'grant': grant}), {'Origin': 'https://mentat.example', 'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(status, 303)
        self.assertEqual(body, b'')
        cookie = headers['set-cookie']
        for flag in ('Secure', 'HttpOnly', 'SameSite=Lax', 'Path=/'):
            self.assertIn(flag, cookie)
        self.assertNotIn(grant, headers['location'])
        state = parse_qs(urlsplit(headers['location']).query)['state'][0]
        status, headers, body = self.request('GET', '/auth/google/callback?' + urlencode({'state': state, 'code': secrets.token_urlsafe(24), 'scope': 'openid email', 'authuser': '0', 'prompt': 'select_account'}), headers={'Cookie': cookie.split(';')[0]})
        self.assertEqual(status, 303)
        self.assertEqual(headers['location'], '/auth/setup/complete')
        self.assertIn('Max-Age=0', headers['set-cookie'])
        candidate = self.ceremony.terminal_candidate()
        self.assertEqual(candidate.email, 'owner@example.test')
        connection = self.fixture.authority._open()
        try:
            self.assertEqual(connection.execute('SELECT state FROM mentat_owner_auth_state').fetchone()[0], 'unbootstrapped')
        finally:
            connection.close()

    def test_unknown_data_paths_and_wrong_origin_are_denied(self):
        for path in ('/', '/api/tasks', '/api/agents', '/bridge/v1/tasks', '/auth/setup/../setup', '/auth/setup?grant=secret'):
            with self.subTest(path=path):
                self.assertIn(self.request('GET', path)[0], (403, 404))
        self.assertEqual(self.request('GET', '/auth/setup', headers={'X-Forwarded-Host': 'wrong.example'})[0], 403)
        self.assertEqual(self.request('POST', '/auth/setup/start', urlencode({'grant': self.ceremony.take_terminal_grant()}), {'Origin': 'https://wrong.example', 'Content-Type': 'application/x-www-form-urlencoded'})[0], 403)
        self.assertEqual(self.fixture.transport.calls, 0)

    def test_hostile_callbacks_are_cleaned_without_exchange(self):
        for query in ('state=a&state=b&code=x', 'error=access_denied&error_description=private', 'state=x&code=y&unknown=z'):
            status, headers, body = self.request('GET', '/auth/google/callback?' + query)
            self.assertEqual(status, 303)
            self.assertEqual(headers['location'], '/auth/setup/complete')
            self.assertEqual(body, b'')
            self.assertEqual(headers['referrer-policy'], 'no-referrer')
        self.assertEqual(self.fixture.transport.calls, 0)

    def test_private_bridge_requires_exact_token_and_has_no_confirm_capability(self):
        for path, token in (('/setup/begin', 'wrong'), ('/setup/confirm', self.token), ('/bridge/v1/tasks', self.token)):
            connection = http.client.HTTPConnection('127.0.0.1', self.bridge.server_port, timeout=5)
            try:
                connection.request('POST', path, body='{}', headers={'Content-Type': 'application/json', 'X-Mentat-Setup-Token': token})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                self.assertEqual(response.read(), b'{"ok":false}')
            finally:
                connection.close()


if __name__ == '__main__':
    unittest.main()
