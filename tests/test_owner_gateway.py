import os
import secrets
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from owner_auth import OwnerAuthError
from owner_gateway import OwnerGateway
from tests import test_schema25_owner_methods as methods
from tests import test_google_login_transactions as login


class OwnerGatewayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = methods.OwnerMethodTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.connection, self.cookie, self.csrf = self.fixture.google_fixture()
        self.gateway = OwnerGateway(self.fixture.fixture.root, 'https://mentat.example', _transport=login.FakeTransport(), _client_secret=secrets.token_urlsafe(32))

    def test_fixed_login_capabilities_issue_session_without_provider_projection(self):
        start = self.gateway.dispatch('login-start', {})
        self.assertEqual(set(start), {'ok', 'authorization_url', 'browser_binding'})
        state = parse_qs(urlsplit(start['authorization_url']).query)['state'][0]
        with patch.dict(os.environ, {'MENTAT_GOOGLE_CLIENT_SECRET': secrets.token_urlsafe(32)}):
            result = self.gateway.dispatch('login-callback', {'state': state, 'browser_binding': start['browser_binding'], 'code': secrets.token_urlsafe(24)})
        self.assertEqual(set(result), {'ok', 'cookie', 'csrf'})
        session = self.gateway.dispatch('session', {'cookie': result['cookie']})
        self.assertEqual(set(session), {'ok', 'absolute_expires_at'})
        for operation in ('enroll', 'recover', 'configure', 'confirm', 'provider-token'):
            with self.subTest(operation=operation), self.assertRaises(OwnerAuthError):
                self.gateway.dispatch(operation, {})

    def test_private_mutations_require_session_and_matching_csrf(self):
        for csrf in (None, secrets.token_urlsafe(32)):
            with self.subTest(csrf_present=csrf is not None), self.assertRaises(OwnerAuthError):
                self.gateway.admit_private_operation(cookie=self.cookie, csrf=csrf, lease=None, unsafe=True)
        self.gateway.admit_private_operation(cookie=self.cookie, csrf=self.csrf, lease=None, unsafe=True)
        self.gateway.dispatch('sign-out', {'cookie': self.cookie, 'csrf': self.csrf})
        with self.assertRaises(OwnerAuthError):
            self.gateway.admit_private_operation(cookie=self.cookie, csrf=None, lease=None, unsafe=False)

    def test_cancel_requires_browser_binding_and_erases_pending_inputs(self):
        start = self.gateway.dispatch('login-start', {})
        state = parse_qs(urlsplit(start['authorization_url']).query)['state'][0]
        with self.assertRaises(OwnerAuthError):
            self.gateway.dispatch('login-cancel', {'state': state, 'browser_binding': secrets.token_urlsafe(32)})
        self.gateway.dispatch('login-cancel', {'state': state, 'browser_binding': start['browser_binding']})
        row = self.connection.execute('SELECT state,nonce,code_verifier FROM mentat_owner_google_transactions').fetchone()
        self.assertEqual(tuple(row), ('cancelled', None, None))

    def test_sse_check_does_not_allocate_or_touch_and_revocation_invalidates_it(self):
        initial = self.gateway.authority.authenticate_session(self.cookie, touch=False)
        lease = self.gateway.dispatch('sse-reserve', {'cookie': self.cookie})['lease']
        for _ in range(4):
            self.gateway.dispatch('sse-check', {'cookie': self.cookie, 'lease': lease})
            self.gateway.admit_private_operation(cookie=self.cookie, csrf=None, lease=lease, unsafe=False)
        current = self.gateway.authority.authenticate_session(self.cookie, touch=False)
        self.assertEqual(current['idle_expires_at'], initial['idle_expires_at'])
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations').fetchone()[0], 1)
        with self.assertRaises(OwnerAuthError):
            self.gateway.admit_private_operation(cookie=self.cookie, csrf=self.csrf, lease=lease, unsafe=True)
        self.gateway.dispatch('sign-out', {'cookie': self.cookie, 'csrf': self.csrf})
        with self.assertRaises(OwnerAuthError):
            self.gateway.dispatch('sse-check', {'cookie': self.cookie, 'lease': lease})
        self.gateway.dispatch('sse-release', {'cookie': self.cookie, 'lease': lease})

    def test_another_cookie_cannot_release_a_lease_and_expiry_is_committed(self):
        lease = self.gateway.dispatch('sse-reserve', {'cookie': self.cookie})['lease']
        self.gateway.dispatch('sse-release', {'cookie': secrets.token_urlsafe(32), 'lease': lease})
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations').fetchone()[0], 1)
        row = self.gateway.authority.authenticate_session(self.cookie, touch=False)
        self.gateway.authority._clock = lambda: row['idle_expires_at']
        with self.assertRaises(OwnerAuthError):
            self.gateway.dispatch('sse-check', {'cookie': self.cookie, 'lease': lease})
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations').fetchone()[0], 0)

    def test_startup_requires_exact_reconciled_google_origin(self):
        with self.assertRaises(OwnerAuthError):
            OwnerGateway(self.fixture.fixture.root, 'https://wrong.example')
        self.connection.execute('UPDATE mentat_owner_google_configuration SET requires_reconciliation=1')
        self.connection.commit()
        with self.assertRaises(OwnerAuthError):
            OwnerGateway(self.fixture.fixture.root, 'https://mentat.example')

    def test_abandoned_stream_slots_expire_without_ending_the_session(self):
        import time
        now = time.time()
        self.gateway.authority._clock = lambda: now
        first = self.gateway.dispatch('sse-reserve', {'cookie': self.cookie})['lease']
        self.gateway.dispatch('sse-reserve', {'cookie': self.cookie})
        with self.assertRaises(OwnerAuthError):
            self.gateway.dispatch('sse-reserve', {'cookie': self.cookie})
        now += 121
        self.gateway.authority.authenticate_session(self.cookie, touch=False)
        with self.assertRaisesRegex(OwnerAuthError, 'stream_unavailable'):
            self.gateway.dispatch('sse-check', {'cookie': self.cookie, 'lease': first})
        self.gateway.dispatch('sse-reserve', {'cookie': self.cookie})
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
