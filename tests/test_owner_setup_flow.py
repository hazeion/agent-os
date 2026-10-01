"""Actual terminal -> Node -> Python proof -> backup/commit flow, fake provider.

TLS ingress has a separate real-Caddy Linux gate. This test keeps networking
on loopback and supplies only the TLS forwarding headers from that contract.
"""

import io
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from mentat.owner_setup_cli import run_google_setup
from owner_auth import OwnerAuthAuthority, validate_owner_auth_connection
from owner_auth import OwnerAuthError
from owner_auth_google_transactions import GoogleLoginTransactions
from owner_auth_setup import OwnerSetupCeremony
from private_state import mentat_server_active
from tests import test_owner_setup_ceremony as provider_fixture
from tests import test_owner_setup_gateway as gateway_fixture
from tests import test_private_console_state as private_fixture


@unittest.skipUnless(shutil.which('node'), 'Node required')
class OwnerSetupFlowTests(unittest.TestCase):
    def test_terminal_and_browser_confirm_real_owner_with_real_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = private_fixture.PrivateConsoleStateTests().make_current(Path(temporary), 'owner', 'fixture')
            old_session = None
            for purpose in ('enroll', 'recover'):
                with self.subTest(purpose=purpose):
                    gateway = gateway_fixture.OwnerSetupGatewayTests()
                    browser_threads, failures, ceremonies = [], [], []
                    def create_ceremony(authority, **kwargs):
                        result = OwnerSetupCeremony(authority, **kwargs, _transport=provider_fixture.SetupTransport())
                        ceremonies.append(result)
                        return result
                    class Runtime:
                        def __init__(self, **_kwargs): pass
                        def start(self, ceremony): gateway.start_gateway(ceremony)
                        def _alive(self): return gateway.process.poll() is None
                        def stop(self): gateway.doCleanups(); return True
                    def browser(grant):
                        try:
                            status, headers, _ = gateway.request('POST', '/auth/setup/start', urlencode({'grant': grant}), {'Origin': 'https://mentat.example', 'Content-Type': 'application/x-www-form-urlencoded'})
                            self.assertEqual(status, 303)
                            state = parse_qs(urlsplit(headers['location']).query)['state'][0]
                            status, headers, _ = gateway.request('GET', '/auth/google/callback?' + urlencode({'state': state, 'code': secrets.token_urlsafe(24)}), headers={'Cookie': headers['set-cookie'].split(';')[0]})
                            self.assertEqual(status, 303)
                            self.assertEqual(headers['location'], '/auth/setup/complete')
                        except BaseException as exc:
                            failures.append(exc)
                            ceremonies[0].close()
                    class Terminal(io.StringIO):
                        def isatty(self): return True
                        def write(self, value):
                            if value.startswith('Setup code: '):
                                thread = threading.Thread(target=browser, args=(value.removeprefix('Setup code: '),))
                                browser_threads.append(thread)
                                thread.start()
                            return super().write(value)
                    output = Terminal()
                    args = SimpleNamespace(origin='https://mentat.example', purpose=purpose, client_id='123-test.apps.googleusercontent.com', caddy_bin=None, cosign_bin=None, release_dir=None, architecture='amd64', tls_cert=None, tls_key=None)
                    with patch('mentat.owner_setup_cli.SUPPORTED_PLATFORM', True), patch('mentat.owner_setup_cli.sys.stdin', Terminal()), patch('mentat.owner_setup_cli.sys.stdout', output), patch.dict(os.environ, {'MENTAT_GOOGLE_CLIENT_SECRET': secrets.token_urlsafe(32)}), patch('mentat.owner_setup_cli.OwnerSetupRuntime', Runtime), patch('mentat.owner_setup_cli.OwnerSetupCeremony', create_ceremony), patch('mentat.owner_setup_cli._read_confirmation', return_value=True):
                        result = run_google_setup(args, SimpleNamespace(data_dir=root))
                    for thread in browser_threads:
                        thread.join(10)
                        self.assertFalse(thread.is_alive())
                    self.assertEqual(failures, [])
                    self.assertEqual(result, 0, output.getvalue())
                    self.assertIn('Validated backup:', output.getvalue())
                    self.assertFalse(mentat_server_active(root))
                    connection = OwnerAuthAuthority(root)._open()
                    try:
                        validate_owner_auth_connection(connection)
                        self.assertEqual(connection.execute('SELECT owner_generation FROM mentat_owner_auth_state').fetchone()[0], 1 if purpose == 'enroll' else 2)
                    finally:
                        connection.close()
                    if purpose == 'enroll':
                        authority = OwnerAuthAuthority(root)
                        login = GoogleLoginTransactions(authority, _transport=provider_fixture.SetupTransport())
                        start = login.begin()
                        state = parse_qs(urlsplit(start.authorization_url).query)['state'][0]
                        old_session = login.authenticate_callback(state=state, browser_binding=start.browser_binding, code=secrets.token_urlsafe(24), client_secret=secrets.token_urlsafe(32))
                    else:
                        with self.assertRaises(OwnerAuthError):
                            OwnerAuthAuthority(root).authenticate_session(old_session.cookie_value)


if __name__ == '__main__':
    unittest.main()
