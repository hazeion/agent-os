from __future__ import annotations

import concurrent.futures
import sqlite3
import secrets
import unittest

import owner_auth
from tests import test_google_login_transactions as login


class GoogleSessionIssuanceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = login.GoogleTransactionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.connection = self.fixture.connection
        self.authority = self.fixture.authority

    def verified(self):
        start, state = self.fixture.begin()
        receipt = self.fixture.verify(start, state)
        return dict(transaction_id=receipt.transaction_id, state=state, browser_binding=start.browser_binding)

    def test_claim_issues_fresh_digest_only_google_session_and_cannot_replay(self):
        values = self.verified()
        grant = self.authority.complete_google_login(**values)
        row = self.authority.authenticate_session(grant.cookie_value, grant.csrf_value, touch=False)
        self.assertEqual(row['auth_method'], 'google')
        self.assertIsNone(row['device_id'])
        self.assertEqual(row['reauthenticated_at'], 0)
        self.assertEqual(row['owner_generation'], 1)
        self.assertEqual(row['idle_expires_at'], self.fixture.now + owner_auth.SESSION_IDLE_SECONDS)
        self.assertEqual(row['absolute_expires_at'], self.fixture.now + owner_auth.SESSION_ABSOLUTE_SECONDS)
        self.assertNotEqual(grant.cookie_value, grant.csrf_value)
        self.assertEqual(grant.recovery_codes, ())
        for secret in (grant.cookie_value, grant.csrf_value):
            self.assertNotIn(secret, repr(grant))
            self.assertNotIn(secret, '\n'.join(self.connection.iterdump()))
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.complete_google_login(**values)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions WHERE state='active'").fetchone()[0], 1)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_google_transactions').fetchone()[0], 0)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_audit WHERE event='authentication_succeeded'").fetchone()[0], 1)

    def test_wrong_state_browser_and_unknown_receipt_do_not_claim(self):
        values = self.verified()
        for field in values:
            changed = dict(values)
            changed[field] = owner_auth._token(24 if field == 'transaction_id' else 32)
            with self.subTest(field=field), self.assertRaises(owner_auth.OwnerAuthError):
                self.authority.complete_google_login(**changed)
        self.assertTrue(self.authority.complete_google_login(**values).cookie_value)

    def test_only_verified_and_unexpired_receipts_are_claimable(self):
        for state in ('consumed', 'failed', 'cancelled'):
            values = self.verified()
            self.connection.execute('UPDATE mentat_owner_google_transactions SET state=? WHERE transaction_id=?', (state, values['transaction_id']))
            self.connection.commit()
            with self.subTest(state=state), self.assertRaises(owner_auth.OwnerAuthError):
                self.authority.complete_google_login(**values)
        start, state = self.fixture.begin()
        pending_id = self.connection.execute("SELECT transaction_id FROM mentat_owner_google_transactions WHERE state='pending'").fetchone()[0]
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.complete_google_login(transaction_id=pending_id, state=state, browser_binding=start.browser_binding)
        values = self.verified()
        self.fixture.now += 300
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.complete_google_login(**values)

    def test_changed_owner_configuration_or_reconciliation_rejects(self):
        mutations = (
            ("UPDATE mentat_owner_auth_state SET owner_generation=2", "UPDATE mentat_owner_google_principal SET owner_generation=2"),
            ("UPDATE mentat_owner_google_configuration SET revision=2", "UPDATE mentat_owner_google_principal SET configuration_revision=2"),
            ("UPDATE mentat_owner_google_configuration SET requires_reconciliation=1",),
            ("UPDATE mentat_owner_google_configuration SET client_id='456-test.apps.googleusercontent.com'",),
            ("UPDATE mentat_owner_auth_state SET auth_method='passkey'",),
        )
        for commands in mutations:
            values = self.verified()
            for command in commands:
                self.connection.execute(command)
            self.connection.commit()
            with self.subTest(commands=commands), self.assertRaises(owner_auth.OwnerAuthError):
                self.authority.complete_google_login(**values)
            self.connection.execute("UPDATE mentat_owner_auth_state SET owner_generation=1,auth_method='google'")
            self.connection.execute("UPDATE mentat_owner_google_configuration SET revision=1,requires_reconciliation=0,client_id='123-test.apps.googleusercontent.com'")
            self.connection.execute('UPDATE mentat_owner_google_principal SET owner_generation=1,configuration_revision=1')
            self.connection.commit()

    def test_concurrent_claims_issue_one_session_across_connections(self):
        values = self.verified()
        def claim():
            authority = owner_auth.OwnerAuthAuthority(self.fixture.fixture.fixture.root, clock=lambda: self.fixture.now)
            try:
                return authority.complete_google_login(**values)
            except owner_auth.OwnerAuthError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions WHERE state='active'").fetchone()[0], 1)

    def test_failed_delete_rolls_back_insert_and_preserves_receipt(self):
        values = self.verified()
        self.connection.execute("CREATE TRIGGER fixture_reject_claim BEFORE DELETE ON mentat_owner_google_transactions BEGIN SELECT RAISE(ABORT, 'test'); END")
        self.connection.commit()
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.complete_google_login(**values)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions WHERE state='active'").fetchone()[0], 0)
        self.assertEqual(self.connection.execute('SELECT state FROM mentat_owner_google_transactions WHERE transaction_id=?', (values['transaction_id'],)).fetchone()[0], 'verified')
        self.connection.execute('DROP TRIGGER fixture_reject_claim')
        self.connection.commit()
        self.assertTrue(self.authority.complete_google_login(**values).cookie_value)

    def test_capacity_rejects_without_evicting_any_existing_session(self):
        for _ in range(owner_auth.MAX_OWNER_SESSIONS):
            self.authority.complete_google_login(**self.verified())
            self.fixture.now += 61
        before = self.connection.execute("SELECT session_digest FROM mentat_owner_auth_sessions WHERE state='active' ORDER BY session_digest").fetchall()
        values = self.verified()
        with self.assertRaisesRegex(owner_auth.OwnerAuthError, 'limited'):
            self.authority.complete_google_login(**values)
        after = self.connection.execute("SELECT session_digest FROM mentat_owner_auth_sessions WHERE state='active' ORDER BY session_digest").fetchall()
        self.assertEqual(before, after)
        self.assertEqual(len(after), 32)

    def test_composed_callback_rotates_secrets_and_signout_invalidates_sse(self):
        grants = []
        for _ in range(2):
            start, state = self.fixture.begin()
            grants.append(self.fixture.service.authenticate_callback(state=state, browser_binding=start.browser_binding, code=self.fixture.code, client_secret=self.fixture.client_secret))
        first, second = grants
        self.assertNotEqual(first.cookie_value, second.cookie_value)
        self.assertNotEqual(first.csrf_value, second.csrf_value)
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.authenticate_session(first.cookie_value, second.csrf_value)
        reservation = self.authority.reserve_sse(first.cookie_value)
        self.assertTrue(reservation.reservation_id)
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.start_device_add(first.cookie_value, first.csrf_value, 'test')
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.sign_out(first.cookie_value, second.csrf_value)
        self.authority.authenticate_session(first.cookie_value, first.csrf_value)
        self.authority.sign_out(first.cookie_value, first.csrf_value)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations').fetchone()[0], 0)
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.authenticate_session(first.cookie_value)
        self.authority.authenticate_session(second.cookie_value, second.csrf_value)
        self.authority.sign_out_all(second.cookie_value, second.csrf_value)
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.reserve_sse(second.cookie_value)

    def test_issued_session_backup_restore_discards_live_access(self):
        from private_console_unit import capture_private_console_unit, sanitize_owner_auth_restore_unit, validate_private_console_unit
        grant = self.authority.complete_google_login(**self.verified())
        unit = capture_private_console_unit(self.fixture.fixture.fixture.root)
        for value in (grant.cookie_value, grant.csrf_value):
            self.assertNotIn(value.encode(), unit.database_raw)
        restored = sanitize_owner_auth_restore_unit(unit)
        validate_private_console_unit(restored)
        path = self.fixture.fixture.fixture.root / 'restore-inspection.sqlite3'
        path.write_bytes(restored.database_raw)
        inspected = sqlite3.connect(path)
        self.addCleanup(inspected.close)
        self.assertEqual(inspected.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions WHERE state='active'").fetchone()[0], 0)
        self.assertEqual(inspected.execute('SELECT requires_reconciliation FROM mentat_owner_google_configuration').fetchone()[0], 1)
        self.authority.authenticate_session(grant.cookie_value, grant.csrf_value)

    def test_single_signout_bounds_history_and_records_secret_free_audit(self):
        grant = self.authority.complete_google_login(**self.verified())
        self.connection.execute("DELETE FROM mentat_owner_auth_sessions WHERE state!='active'")
        principal = self.connection.execute('SELECT principal_digest FROM mentat_owner_google_principal').fetchone()[0]
        now = self.fixture.now
        for _ in range(owner_auth.MAX_TERMINAL_SESSIONS):
            self.connection.execute("INSERT INTO mentat_owner_auth_sessions(session_digest,csrf_digest,device_id,auth_method,owner_generation,principal_digest,state,created_at,reauthenticated_at,last_seen_at,idle_expires_at,absolute_expires_at,revoked_at) VALUES(?,?,NULL,'google',1,?,'revoked',?,0,?,?,?,?)", (secrets.token_bytes(32), secrets.token_bytes(32), principal, now-10, now-10, now+100, now+200, now-1))
        self.connection.commit()
        self.authority.sign_out(grant.cookie_value, grant.csrf_value)
        owner_auth.validate_owner_auth_connection(self.connection)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_auth_sessions').fetchone()[0], owner_auth.MAX_TERMINAL_SESSIONS)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_audit WHERE event='session_revoked'").fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
