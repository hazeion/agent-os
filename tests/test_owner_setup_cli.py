import io
import secrets
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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

    def test_failure_guidance_keeps_private_errors_out_and_preserves_cleanup(self):
        cases = (
            ('host', 'host verification'), ('ceremony', 'setup preparation'),
            ('gateway', 'setup gateway startup'), ('browser', 'browser sign-in'),
            ('teardown', 'setup gateway shutdown'), ('confirmation', 'owner confirmation'),
            ('recovery', 'recovery-code output'), ('interrupted', 'owner confirmation'),
        )
        for phase, label in cases:
            with self.subTest(phase=phase):
                canary = secrets.token_urlsafe(32)
                failure = RuntimeError(canary)
                events = []
                runtime = Mock()
                runtime._alive.return_value = True
                def stop():
                    events.append('stop')
                    if phase == 'teardown' and events.count('stop') == 1:
                        raise failure
                    return True
                runtime.stop.side_effect = stop
                ceremony = Mock()
                ceremony.take_terminal_grant.return_value = secrets.token_urlsafe(32)
                ceremony.terminal_status.return_value = 'candidate'
                ceremony.terminal_candidate.return_value = SimpleNamespace(
                    candidate_id='candidate', revision=1, email='owner@example.test',
                    purpose='enroll', expires_at=time.time()+60,
                )
                def confirm(**_kwargs):
                    self.assertIn('stop', events)
                    events.append('confirm')
                    if phase == 'confirmation':
                        raise failure
                    class RecoveryCodes:
                        def __iter__(self):
                            raise failure
                    return SimpleNamespace(backup_name='backup.zip', recovery_codes=RecoveryCodes())
                ceremony.confirm.side_effect = confirm
                ceremony.close.side_effect = lambda: events.append('close') or True
                runtime_factory = Mock(return_value=runtime)
                ceremony_factory = Mock(return_value=ceremony)
                if phase == 'host': runtime_factory.side_effect = failure
                if phase == 'ceremony': ceremony_factory.side_effect = failure
                if phase == 'gateway': runtime.start.side_effect = failure
                if phase == 'browser': ceremony.terminal_candidate.side_effect = failure
                confirmation = Mock(return_value=True)
                if phase == 'interrupted': confirmation.side_effect = KeyboardInterrupt(canary)
                args = SimpleNamespace(origin='https://mentat.example', client_id='123-test.apps.googleusercontent.com', purpose='enroll', caddy_bin=None, cosign_bin=None, release_dir=None, architecture='amd64', tls_cert=None, tls_key=None)
                output = Terminal()
                with patch('mentat.owner_setup_cli.SUPPORTED_PLATFORM', True), patch('mentat.owner_setup_cli.sys.stdin', Terminal()), patch('mentat.owner_setup_cli.sys.stdout', output), patch.dict('os.environ', {'MENTAT_GOOGLE_CLIENT_SECRET': canary}), patch('mentat.owner_setup_cli.schema_startup_status', return_value='current'), patch('mentat.owner_setup_cli.OwnerSetupRuntime', runtime_factory), patch('mentat.owner_setup_cli.OwnerSetupCeremony', ceremony_factory), patch('mentat.owner_setup_cli._read_confirmation', confirmation):
                    self.assertEqual(run_google_setup(args, SimpleNamespace(data_dir='unused-test-root')), 2)
                self.assertIn('Owner setup stopped during ' + label + '.', output.getvalue())
                self.assertNotIn(canary, output.getvalue())
                self.assertEqual(ceremony.confirm.call_count, int(phase in {'confirmation', 'recovery'}))
                if phase == 'host':
                    self.assertEqual(events, [])
                elif phase == 'ceremony':
                    self.assertEqual(events, ['stop'])
                else:
                    self.assertEqual(events[-2:], ['stop', 'close'])
                if phase == 'recovery':
                    self.assertIn('Owner confirmation succeeded.', output.getvalue())
                    self.assertNotIn('prior owner remains unchanged', output.getvalue())

    def test_unverified_shutdown_keeps_ceremony_open_and_blocks_restart_guidance(self):
        runtime = Mock()
        runtime.start.side_effect = RuntimeError(secrets.token_urlsafe(32))
        runtime.stop.return_value = False
        ceremony = Mock()
        args = SimpleNamespace(origin='https://mentat.example', client_id='123-test.apps.googleusercontent.com', purpose='enroll', caddy_bin=None, cosign_bin=None, release_dir=None, architecture='amd64', tls_cert=None, tls_key=None)
        output = Terminal()
        with patch('mentat.owner_setup_cli.SUPPORTED_PLATFORM', True), patch('mentat.owner_setup_cli.sys.stdin', Terminal()), patch('mentat.owner_setup_cli.sys.stdout', output), patch.dict('os.environ', {'MENTAT_GOOGLE_CLIENT_SECRET': secrets.token_urlsafe(32)}), patch('mentat.owner_setup_cli.schema_startup_status', return_value='current'), patch('mentat.owner_setup_cli.OwnerSetupRuntime', return_value=runtime), patch('mentat.owner_setup_cli.OwnerSetupCeremony', return_value=ceremony):
            self.assertEqual(run_google_setup(args, SimpleNamespace(data_dir='unused-test-root')), 2)
        ceremony.close.assert_not_called()
        ceremony.confirm.assert_not_called()
        self.assertIn('Setup resources could not be fully stopped.', output.getvalue())
        self.assertIn('Check the host before restarting Mentat', output.getvalue())


if __name__ == '__main__':
    unittest.main()
