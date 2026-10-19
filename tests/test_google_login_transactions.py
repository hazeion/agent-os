from __future__ import annotations

import concurrent.futures
import secrets
import sqlite3
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import mentat_db
import owner_auth
from owner_auth_google import GOOGLE_ISSUER, VerifiedGoogleIdentity
from owner_auth_google_transactions import GoogleLoginTransactions, MAX_PENDING, validate_transactions
from private_console_unit import capture_private_console_unit, validate_private_console_unit, sanitize_owner_auth_restore_unit
from tests import test_schema25_owner_methods as methods


class FakeTransport:
    def __init__(self):
        self.calls = 0
        self.callback = None

    def authenticate_code(self, **values):
        self.calls += 1
        if self.callback:
            self.callback(values)
        return VerifiedGoogleIdentity(GOOGLE_ISSUER, 'private-google-subject', 'changed@example.test')


class GoogleTransactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = methods.OwnerMethodTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.connection, _, _ = self.fixture.google_fixture()
        self.authority = self.fixture.authority
        self.now = 2000000000.0
        self.authority._clock = lambda: self.now
        self.transport = FakeTransport()
        self.code = secrets.token_urlsafe(24)
        self.client_secret = secrets.token_urlsafe(32)
        self.service = GoogleLoginTransactions(self.authority, _transport=self.transport)

    def begin(self):
        start = self.service.begin()
        state = parse_qs(urlsplit(start.authorization_url).query)['state'][0]
        return start, state

    def verify(self, start, state, service=None):
        return (service or self.service).verify_callback(state=state, browser_binding=start.browser_binding, code=self.code, client_secret=self.client_secret)

    def test_success_consumes_before_exchange_and_retains_only_private_receipt(self):
        start, state = self.begin()
        pending = self.connection.execute('SELECT nonce,code_verifier FROM mentat_owner_google_transactions').fetchone()
        def inspect(values):
            row = self.connection.execute('SELECT state,nonce,code_verifier FROM mentat_owner_google_transactions').fetchone()
            self.assertEqual(tuple(row), ('consumed', None, None))
            self.assertEqual(values['expected_nonce'], pending[0])
            self.assertEqual(values['code_verifier'], pending[1])
        self.transport.callback = inspect
        receipt = self.verify(start, state)
        self.assertNotIn(state, repr(start))
        self.assertNotIn(receipt.transaction_id, repr(receipt))
        self.assertEqual(self.connection.execute('SELECT state FROM mentat_owner_google_transactions').fetchone()[0], 'verified')
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.verify(start, state)
        self.assertEqual(self.transport.calls, 1)
        raw = '\n'.join(self.connection.iterdump())
        for value in (state, start.browser_binding, pending[0], pending[1], self.code, self.client_secret):
            self.assertNotIn(value, raw)

    def test_bad_binding_and_encoding_never_exchange_or_consume(self):
        start, state = self.begin()
        for bad_state, bad_browser in ((None, start.browser_binding), (state+'=', start.browser_binding), (state, ''), (state, owner_auth._token(32)), (owner_auth._token(32), start.browser_binding)):
            with self.subTest(value=type(bad_state).__name__), self.assertRaises(owner_auth.OwnerAuthError):
                self.service.verify_callback(state=bad_state, browser_binding=bad_browser, code=self.code, client_secret=self.client_secret)
        self.assertEqual(self.transport.calls, 0)
        self.assertEqual(self.connection.execute('SELECT state FROM mentat_owner_google_transactions').fetchone()[0], 'pending')
        self.verify(start, state)

    def test_concurrent_callbacks_have_one_exchange_across_connections(self):
        start, state = self.begin()
        entered, release = threading.Event(), threading.Event()
        self.transport.callback = lambda _: (entered.set(), release.wait(10))
        def submit():
            authority = owner_auth.OwnerAuthAuthority(self.fixture.fixture.root, clock=lambda: self.now)
            return self.verify(start, state, GoogleLoginTransactions(authority, _transport=self.transport))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(submit)
            self.assertTrue(entered.wait(5))
            second = executor.submit(submit)
            try:
                with self.assertRaises(owner_auth.OwnerAuthError):
                    second.result(5)
            finally:
                release.set()
            self.assertTrue(first.result(5).transaction_id)
        self.assertEqual(self.transport.calls, 1)

    def test_ambiguous_failure_and_crash_never_retry(self):
        for failure in (TimeoutError, KeyboardInterrupt):
            with self.subTest(failure=failure):
                start, state = self.begin()
                def fail(_):
                    raise failure('private-provider-detail')
                self.transport.callback = fail
                with self.assertRaises((owner_auth.OwnerAuthError, KeyboardInterrupt)) as caught:
                    self.verify(start, state)
                if isinstance(caught.exception, owner_auth.OwnerAuthError):
                    self.assertEqual(str(caught.exception), 'invalid')
                self.transport.callback = None
                calls = self.transport.calls
                with self.assertRaises(owner_auth.OwnerAuthError):
                    self.verify(start, state)
                self.assertEqual(self.transport.calls, calls)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_google_transactions WHERE nonce IS NOT NULL OR code_verifier IS NOT NULL').fetchone()[0], 0)

    def test_owner_changes_before_and_during_exchange_reject(self):
        start, state = self.begin()
        self.connection.execute('UPDATE mentat_owner_google_configuration SET requires_reconciliation=1')
        self.connection.commit()
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.verify(start, state)
        self.assertEqual(self.transport.calls, 0)
        self.connection.execute('UPDATE mentat_owner_google_configuration SET requires_reconciliation=0')
        self.connection.commit()
        def change(_):
            self.connection.execute('UPDATE mentat_owner_google_configuration SET revision=2')
            self.connection.execute('UPDATE mentat_owner_google_principal SET configuration_revision=2')
            self.connection.commit()
        self.transport.callback = change
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.verify(start, state)
        self.assertEqual(self.connection.execute('SELECT state FROM mentat_owner_google_transactions').fetchone()[0], 'failed')

    def test_wrong_subject_is_not_enrollment(self):
        start, state = self.begin()
        self.transport.authenticate_code = lambda **_: VerifiedGoogleIdentity(GOOGLE_ISSUER, 'wrong', 'owner@example.test')
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.verify(start, state)
        self.assertEqual(self.connection.execute('SELECT subject FROM mentat_owner_google_principal').fetchone()[0], 'private-google-subject')

    def test_generation_change_and_expiry_during_exchange_reject(self):
        for change in ('generation', 'expiry'):
            with self.subTest(change=change):
                start, state = self.begin()
                def mutate(_):
                    if change == 'generation':
                        self.connection.execute('UPDATE mentat_owner_auth_state SET owner_generation=owner_generation+1')
                        self.connection.execute('UPDATE mentat_owner_google_principal SET owner_generation=owner_generation+1')
                        self.connection.commit()
                    else:
                        self.now += 300
                self.transport.callback = mutate
                with self.assertRaises(owner_auth.OwnerAuthError):
                    self.verify(start, state)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM mentat_owner_google_transactions WHERE state='verified'").fetchone()[0], 0)

    def test_failed_consumption_rolls_back_without_provider_call(self):
        start, state = self.begin()
        self.connection.execute("CREATE TRIGGER fixture_reject_consume BEFORE UPDATE ON mentat_owner_google_transactions BEGIN SELECT RAISE(ABORT, 'test'); END")
        self.connection.commit()
        with patch.object(self.service, '_fail', wraps=self.service._fail) as fail:
            with self.assertRaises(owner_auth.OwnerAuthError):
                self.verify(start, state)
            fail.assert_not_called()  # A rolled-back loser must not fail a racing winner.
        self.assertEqual(self.transport.calls, 0)
        self.assertEqual(self.connection.execute('SELECT state FROM mentat_owner_google_transactions').fetchone()[0], 'pending')
        self.connection.execute('DROP TRIGGER fixture_reject_consume')
        self.connection.commit()
        self.verify(start, state)

    def test_terminal_retention_stays_bounded(self):
        for _ in range(67):
            start, state = self.begin()
            self.verify(start, state)
            self.now += 61
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_google_transactions').fetchone()[0], 64)
        validate_transactions(self.connection)

    def test_expiry_admission_and_capacity(self):
        start, state = self.begin()
        self.now += 300
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.verify(start, state)

        for _ in range(10):
            self.begin()
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.begin()
        self.now += 60
        for _ in range(MAX_PENDING - 10):
            self.begin()
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.begin()
        validate_transactions(self.connection)
        self.assertEqual(self.transport.calls, 0)

    def test_unconfigured_passkey_and_reconciliation_cannot_begin(self):
        for change in ("UPDATE mentat_owner_auth_state SET auth_method='passkey'", "UPDATE mentat_owner_google_configuration SET requires_reconciliation=1"):
            self.connection.execute('SAVEPOINT change')
            self.connection.execute(change)
            # The service has a separate connection: commit then restore manually.
            self.connection.execute('RELEASE change')
            with self.assertRaises(owner_auth.OwnerAuthError):
                self.begin()
            self.connection.execute("UPDATE mentat_owner_auth_state SET auth_method='google'")
            self.connection.execute('UPDATE mentat_owner_google_configuration SET requires_reconciliation=0')
            self.connection.commit()

    def test_backup_filters_pending_secrets_and_restore_and_startup_invalidate(self):
        self.connection.execute('DELETE FROM mentat_owner_auth_sessions')
        self.connection.commit()
        start, state = self.begin()
        secrets = self.connection.execute('SELECT nonce,code_verifier FROM mentat_owner_google_transactions').fetchone()
        unit = capture_private_console_unit(self.fixture.fixture.root)
        validate_private_console_unit(unit)
        for value in (*secrets, state, start.browser_binding):
            self.assertNotIn(value.encode(), unit.database_raw)
        inspection_path = self.fixture.fixture.root / 'snapshot-inspection.sqlite3'
        inspection_path.write_bytes(unit.database_raw)
        inspected = sqlite3.connect(inspection_path)
        self.addCleanup(inspected.close)
        self.assertEqual(inspected.execute('SELECT COUNT(*) FROM mentat_owner_google_transactions').fetchone()[0], 0)
        validate_private_console_unit(sanitize_owner_auth_restore_unit(unit))
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_google_transactions').fetchone()[0], 1)
        owner_auth.cleanup_owner_auth_at_startup(self.fixture.fixture.root, clock=lambda: self.now)
        self.assertEqual(self.connection.execute('SELECT COUNT(*) FROM mentat_owner_google_transactions').fetchone()[0], 0)
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.verify(start, state)


class GoogleTransactionMigrationTests(unittest.TestCase):
    def test_schema25_snapshot_compatibility_and_exact_forward_migration(self):
        connection = methods.schema24()
        self.addCleanup(connection.close)
        with patch.object(mentat_db, 'MIGRATIONS', tuple(item for item in mentat_db.MIGRATIONS if item[0] <= 25)):
            mentat_db.migrate(connection)
        self.assertEqual(mentat_db.schema_signature_state(connection, 25), 'expected')
        # Validate historical schema25 through the real private-unit validators.
        connection.execute("INSERT INTO mentat_agent_registry_state(singleton,authority,migration_contract,source_kind,source_sha256,source_agent_count,cutover_at) VALUES(1,'sqlite',?,'fresh',?,0,1)", (mentat_db.AGENT_REGISTRY_AUTHORITY_CONTRACT, mentat_db.EMPTY_AGENT_REGISTRY_SOURCE_SHA256))
        connection.commit()
        import json
        from private_console_unit import PrivateConsoleUnit
        unit = PrivateConsoleUnit(json.dumps({'schema_version': 3, 'runs': []}).encode(), connection.serialize(), None, ())
        validate_private_console_unit(unit)
        validate_private_console_unit(sanitize_owner_auth_restore_unit(unit))
        mentat_db.migrate(connection)
        self.assertEqual(mentat_db.schema_signature_state(connection, mentat_db.SCHEMA_VERSION), 'expected')
        self.assertEqual(connection.execute('SELECT COUNT(*) FROM mentat_owner_google_transactions').fetchone()[0], 0)
        self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_migration_failure_is_atomic(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                connection = methods.schema24()
                self.addCleanup(connection.close)
                with patch.object(mentat_db, 'MIGRATIONS', tuple(item for item in mentat_db.MIGRATIONS if item[0] <= 25)):
                    mentat_db.migrate(connection)
                if corrupt:
                    connection.execute('CREATE TABLE unexpected(value TEXT)')
                original = mentat_db._execute_script_in_active_transaction
                def fail_after_ddl(conn, script):
                    original(conn, script)
                    raise sqlite3.OperationalError('simulated interruption')
                with patch.object(mentat_db, '_execute_script_in_active_transaction', fail_after_ddl):
                    with self.assertRaises((mentat_db.MentatDatabaseError, sqlite3.OperationalError)):
                        mentat_db.migrate(connection)
                self.assertEqual(connection.execute('SELECT MAX(version) FROM schema_migrations').fetchone()[0], 25)
                self.assertIsNone(connection.execute("SELECT name FROM sqlite_master WHERE name='mentat_owner_google_transactions'").fetchone())


if __name__ == '__main__':
    unittest.main()
