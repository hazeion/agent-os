"""Real built Next website + private Python auth, with an intercepted provider."""

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

from mentat import local_bridge
from owner_gateway import OwnerGateway
from owner_auth_google import GOOGLE_ISSUER, VerifiedGoogleIdentity
from owner_auth_google_transport import GoogleOidcTransportError
from owner_auth_google_transactions import _digest_secret
from tests import test_schema25_owner_methods as methods

ROOT = Path(__file__).resolve().parents[1]
STANDALONE = ROOT / 'web' / '.next' / 'standalone'


class FixtureTransport:
    def authenticate_code(self, **body):
        if body['code'] == 'provider-unavailable':
            raise GoogleOidcTransportError()
        subject = 'wrong-subject' if body['code'] == 'wrong-account' else 'private-google-subject'
        return VerifiedGoogleIdentity(GOOGLE_ISSUER, subject, 'owner@example.test')
    def close(self): return True


class FixtureGateway(OwnerGateway):
    def dispatch(self, operation, body):
        if operation == 'login-callback' and body.get('code') == 'expired':
            connection = self.authority._open()
            try:
                connection.execute('UPDATE mentat_owner_google_transactions SET created_at=created_at-301,expires_at=expires_at-301 WHERE state_digest=?', (_digest_secret(body['state']),))
            finally:
                connection.close()
        return super().dispatch(operation, body)


class FixtureHandler(local_bridge.BridgeRequestHandler):
    def do_GET(self):
        if self.path == local_bridge.BRIDGE_HEALTH_PATH or self.path.startswith('/bridge/v1/runs/'):
            return super().do_GET()
        if not self._request_is_private() or not self._owner_access_allowed(unsafe=False):
            return self._send_json({'error': 'owner_authentication_required'}, 401)
        if self.path == '/bridge/v1/tasks':
            return self._send_json({'schema_version': 1, 'service': 'mentat-local-bridge', 'runtime': 'python', 'status': 'ready', 'count': 1, 'tasks': [{'id': 'fixture-task', 'title': 'Owner-only fixture task', 'project': 'Fixture', 'status': 'todo', 'priority': 'medium', 'due_date': None, 'tags': [], 'needs_attention': False, 'review_required': False, 'updated_at': '2026-09-22T00:00:00Z'}]}, 200)
        if self.path.startswith('/bridge/v1/conversations'):
            return self._send_json({'schema_version': 1, 'service': 'mentat-local-bridge', 'runtime': 'python', 'status': 'ready', 'count': 0, 'agents': [], 'conversations': [], 'direct_agent_id': None, 'next_cursor': None}, 200)
        return self._send_json({'schema_version': 1, 'service': 'mentat-local-bridge', 'runtime': 'python', 'status': 'unavailable'}, 503)

    def do_POST(self):
        if self.path.startswith(local_bridge.OWNER_GATEWAY_ROOT) or self.path.startswith('/bridge/v1/runs/'):
            return super().do_POST()
        if not self._request_is_private(reject_body_headers=False) or not self._owner_access_allowed(unsafe=True):
            return self._send_json({'error': 'owner_authentication_required'}, 401)
        return self._send_json({'schema_version': 1, 'service': 'mentat-local-bridge', 'runtime': 'python', 'status': 'unavailable'}, 503)


@unittest.skipUnless(os.environ.get('CHROME_PATH') and shutil.which('node') and (STANDALONE / 'server.js').is_file(), 'Built website, Node and explicit Chrome required')
class OwnerWebsiteBrowserTests(unittest.TestCase):
    def start_site(self):
        fixture = methods.OwnerMethodTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        _, cookie, csrf = fixture.google_fixture()
        token = secrets.token_urlsafe(32)
        bridge = local_bridge.BridgeHTTPServer(('127.0.0.1', 0), token)
        bridge.RequestHandlerClass = FixtureHandler
        bridge.owner_gateway = FixtureGateway(fixture.fixture.root, 'https://mentat.example', _transport=FixtureTransport(), _client_secret=secrets.token_urlsafe(32))
        bridge.daemon_threads = False
        thread = threading.Thread(target=bridge.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (bridge.shutdown(), bridge.server_close(), thread.join(5), bridge.owner_gateway.close()))
        with socket.socket() as candidate:
            candidate.bind(('127.0.0.1', 0)); port = candidate.getsockname()[1]
        environment = {key: value for key, value in os.environ.items() if key in {'PATH', 'SystemRoot', 'SYSTEMROOT', 'TEMP', 'TMP', 'USERPROFILE', 'LOCALAPPDATA', 'APPDATA', 'CHROME_PATH'}}
        environment.update(PORT=str(port), HOSTNAME='127.0.0.1', NODE_ENV='production', MENTAT_GATEWAY_MODE='owner', MENTAT_OWNER_ORIGIN='https://mentat.example', MENTAT_BRIDGE_ORIGIN=f'http://127.0.0.1:{bridge.server_port}', MENTAT_BRIDGE_TOKEN=token)
        process = subprocess.Popen([shutil.which('node'), str(STANDALONE / 'server.js')], cwd=STANDALONE, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            process.terminate()
            try: process.wait(5)
            except subprocess.TimeoutExpired: process.kill(); process.wait(3)
        self.addCleanup(stop)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            self.assertIsNone(process.poll(), 'website exited before readiness')
            connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
            try:
                connection.request('GET', '/api/gateway/health')
                response = connection.getresponse(); response.read()
                if response.status == 200: break
            except OSError: pass
            finally: connection.close()
            time.sleep(0.05)
        else: self.fail('website did not become ready')
        return fixture, bridge, port, environment, cookie, csrf

    def test_browser_signin_wrong_account_second_device_csrf_and_signout(self):
        _fixture, _bridge, port, environment, _cookie, _csrf = self.start_site()
        environment.update(MENTAT_WEBSITE_TEST_PORT=str(port), MENTAT_WEBSITE_SCREENSHOT_ROOT=str(ROOT / 'artifacts' / 'website-sign-in'))
        result = subprocess.run([shutil.which('node'), str(ROOT / 'web' / 'scripts' / 'owner-website-browser-smoke.mjs')], env=environment, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn('Owner website browser checks passed', result.stdout)


if __name__ == '__main__': unittest.main()
