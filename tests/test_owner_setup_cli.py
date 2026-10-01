import io
import secrets
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mentat.owner_setup_cli import run_google_setup


class Terminal(io.StringIO):
    def isatty(self):
        return True


class OwnerSetupCliTests(unittest.TestCase):
    def test_confirmed_path_stops_browser_surface_before_confirmation(self):
        events = []
        candidate = SimpleNamespace(candidate_id='candidate', revision=1, email='owner@example.test', purpose='enroll', expires_at=time.time()+60)
        class Runtime:
            def __init__(self, **_kwargs): pass
            def start(self, _ceremony): events.append('start')
            def stop(self): events.append('stop'); return True
        class Ceremony:
            def __init__(self, *_args, **_kwargs): pass
            def take_terminal_grant(self): return secrets.token_urlsafe(32)
            def terminal_status(self): return 'candidate'
            def terminal_candidate(self): return candidate
            def confirm(self, **kwargs):
                self_outer.assertEqual(kwargs, {'candidate_id': 'candidate', 'revision': 1})
                self_outer.assertIn('stop', events)
                events.append('confirm')
                return SimpleNamespace(backup_name='backup.zip', recovery_codes=('synthetic-recovery',))
            def close(self): events.append('close'); return True
        self_outer = self
        args = SimpleNamespace(origin='https://mentat.example', client_id='123-test.apps.googleusercontent.com', purpose='enroll', caddy_bin=None, cosign_bin=None, release_dir=None, architecture='amd64', tls_cert=None, tls_key=None)
        output = Terminal()
        with patch('mentat.owner_setup_cli.SUPPORTED_PLATFORM', True), patch('mentat.owner_setup_cli.sys.stdin', Terminal()), patch('mentat.owner_setup_cli.sys.stdout', output), patch.dict('os.environ', {'MENTAT_GOOGLE_CLIENT_SECRET': secrets.token_urlsafe(32)}), patch('mentat.owner_setup_cli.schema_startup_status', return_value='current'), patch('mentat.owner_setup_cli.OwnerSetupRuntime', Runtime), patch('mentat.owner_setup_cli.OwnerSetupCeremony', Ceremony), patch('mentat.owner_setup_cli._read_confirmation', return_value=True):
            status = run_google_setup(args, SimpleNamespace(data_dir='unused-test-root'))
        self.assertEqual(status, 0)
        self.assertEqual(events, ['start', 'stop', 'confirm', 'stop', 'close'])
        self.assertIn('not activated', output.getvalue())

    def test_piped_input_cannot_receive_setup_or_recovery_secrets(self):
        with patch('mentat.owner_setup_cli.SUPPORTED_PLATFORM', True), patch('mentat.owner_setup_cli.sys.stdin', io.StringIO()), patch('mentat.owner_setup_cli.sys.stdout', io.StringIO()), patch('mentat.owner_setup_cli.OwnerSetupRuntime') as runtime:
            self.assertEqual(run_google_setup(None, None), 2)
            runtime.assert_not_called()


if __name__ == '__main__':
    unittest.main()
