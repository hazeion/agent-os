import secrets
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from owner_auth import OwnerAuthError, validate_owner_auth_connection
from owner_auth_google import GOOGLE_ISSUER, VerifiedGoogleIdentity
from owner_auth_setup import OwnerSetupCeremony
from private_state import mentat_server_active
from tests import test_owner_auth as legacy


class SetupTransport:
    calls = 0
    def authenticate_code(self, **kwargs):
        self.calls += 1
        return VerifiedGoogleIdentity(GOOGLE_ISSUER, 'fixture-subject', 'owner@example.test')
    def close(self):
        return True


class OwnerSetupCeremonyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy.OwnerAuthAuthorityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.authority = self.fixture.authority
        self.transport = SetupTransport()
        self.backups = []

    def ceremony(self, purpose='enroll', backup_status='created'):
        def backup(root):
            self.backups.append(root)
            return SimpleNamespace(status=backup_status, backup_name='fixture-backup.zip')
        ceremony = OwnerSetupCeremony(self.authority, purpose=purpose,
            client_id='123-test.apps.googleusercontent.com', origin='https://mentat.example',
            client_secret=secrets.token_urlsafe(32), _transport=self.transport, _backup=backup)
        self.addCleanup(ceremony.close)
        return ceremony

    def prove(self, ceremony):
        grant = ceremony.take_terminal_grant()
        start = ceremony.begin_browser(grant)
        state = parse_qs(urlsplit(start.authorization_url).query)['state'][0]
        ceremony.verify_browser(state=state, browser_binding=start.browser_binding, code=secrets.token_urlsafe(24))
        return ceremony.terminal_candidate()

    def test_enrollment_requires_terminal_confirmation_after_proof(self):
        ceremony = self.ceremony()
        candidate = self.prove(ceremony)
        connection = self.authority._open()
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute('SELECT state FROM mentat_owner_auth_state').fetchone()[0], 'unbootstrapped')
        with self.assertRaises(OwnerAuthError):
            ceremony.confirm(candidate_id=secrets.token_urlsafe(24), revision=1)
        result = ceremony.confirm(candidate_id=candidate.candidate_id, revision=candidate.revision)
        self.assertEqual(len(result.recovery_codes), 10)
        self.assertEqual(len(self.backups), 1)
        self.assertEqual(tuple(connection.execute('SELECT state,auth_method,owner_generation FROM mentat_owner_auth_state').fetchone()), ('active', 'google', 1))
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_owner_auth_sessions').fetchone()[0], 0)
        validate_owner_auth_connection(connection)
        with self.assertRaises(OwnerAuthError):
            ceremony.confirm(candidate_id=candidate.candidate_id, revision=candidate.revision)
        self.assertTrue(mentat_server_active(self.fixture.root))
        ceremony.close()
        self.assertFalse(mentat_server_active(self.fixture.root))

    def test_conversion_revokes_old_sessions_and_passkey_authority(self):
        _, session = self.fixture.bootstrap()
        ceremony = self.ceremony('convert')
        candidate = self.prove(ceremony)
        ceremony.confirm(candidate_id=candidate.candidate_id, revision=1)
        with self.assertRaises(OwnerAuthError):
            self.authority.authenticate_session(session.cookie_value)
        with self.assertRaises(OwnerAuthError):
            self.authority.start_authentication()
        connection = self.authority._open()
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials WHERE state='active'").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state='active'").fetchone()[0], 10)
        validate_owner_auth_connection(connection)

    def test_backup_failure_and_changed_authority_preserve_old_owner(self):
        _, session = self.fixture.bootstrap()
        ceremony = self.ceremony('convert', backup_status='blocked')
        candidate = self.prove(ceremony)
        with self.assertRaisesRegex(OwnerAuthError, 'backup_required'):
            ceremony.confirm(candidate_id=candidate.candidate_id, revision=1)
        self.authority.authenticate_session(session.cookie_value)
        connection = self.authority._open()
        self.addCleanup(connection.close)
        connection.execute('UPDATE mentat_owner_auth_state SET revision=revision+1')
        with self.assertRaisesRegex(OwnerAuthError, 'changed'):
            ceremony.confirm(candidate_id=candidate.candidate_id, revision=1)
        self.assertEqual(connection.execute('SELECT auth_method FROM mentat_owner_auth_state').fetchone()[0], 'passkey')

    def test_wrong_grant_browser_and_callback_replay_do_not_replace_candidate(self):
        ceremony = self.ceremony()
        with self.assertRaises(OwnerAuthError):
            ceremony.begin_browser(secrets.token_urlsafe(32))
        start = ceremony.begin_browser(ceremony.take_terminal_grant())
        state = parse_qs(urlsplit(start.authorization_url).query)['state'][0]
        with self.assertRaises(OwnerAuthError):
            ceremony.verify_browser(state=state, browser_binding=secrets.token_urlsafe(32), code='unused')
        self.assertEqual(self.transport.calls, 0)
        ceremony.verify_browser(state=state, browser_binding=start.browser_binding, code=secrets.token_urlsafe(24))
        candidate = ceremony.terminal_candidate()
        with self.assertRaises(OwnerAuthError):
            ceremony.verify_browser(state=state, browser_binding=start.browser_binding, code=secrets.token_urlsafe(24))
        self.assertEqual(self.transport.calls, 1)
        self.assertEqual(ceremony.terminal_candidate(), candidate)

    def test_expired_provider_completion_cannot_create_a_candidate(self):
        now = [2000000000.0]
        self.authority._clock = lambda: now[0]
        ceremony = self.ceremony()
        start = ceremony.begin_browser(ceremony.take_terminal_grant())
        state = parse_qs(urlsplit(start.authorization_url).query)['state'][0]
        def expired(**_kwargs):
            now[0] += 600
            return VerifiedGoogleIdentity(GOOGLE_ISSUER, 'fixture-subject', 'owner@example.test')
        with patch.object(self.transport, 'authenticate_code', side_effect=expired), self.assertRaises(OwnerAuthError):
            ceremony.verify_browser(state=state, browser_binding=start.browser_binding, code=secrets.token_urlsafe(24))
        self.assertEqual(ceremony.terminal_status(), 'expired')
        connection = self.authority._open()
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute('SELECT state FROM mentat_owner_auth_state').fetchone()[0], 'unbootstrapped')

    def test_confirmation_rolls_back_if_recovery_rotation_fails(self):
        ceremony = self.ceremony()
        candidate = self.prove(ceremony)
        with patch.object(self.authority, '_new_recovery_codes', side_effect=RuntimeError('synthetic failure')), self.assertRaises(RuntimeError):
            ceremony.confirm(candidate_id=candidate.candidate_id, revision=1)
        connection = self.authority._open()
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute('SELECT state FROM mentat_owner_auth_state').fetchone()[0], 'unbootstrapped')
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_owner_google_principal').fetchone()[0], 0)
        result = ceremony.confirm(candidate_id=candidate.candidate_id, revision=1)
        self.assertEqual(len(result.recovery_codes), 10)


if __name__ == '__main__':
    unittest.main()
