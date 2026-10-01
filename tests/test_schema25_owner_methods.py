from __future__ import annotations

import secrets
import json
import sqlite3
import time
import unittest
from unittest.mock import patch

import mentat_db
import owner_auth
from private_console_unit import PrivateConsoleUnit, capture_private_console_unit, sanitize_owner_auth_restore_unit, validate_private_console_unit
from task_repository import _schema5_private_unit
from tests import test_owner_auth as legacy


def schema24():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
    for version, script in mentat_db.MIGRATIONS:
        if version > 24:
            break
        connection.executescript(script)
        connection.execute("INSERT INTO schema_migrations VALUES (?, 0)", (version,))
        connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("UPDATE mentat_owner_auth_state SET state='active', user_handle=?, canonical_origin='https://mentat.example', rp_id='mentat.example', configuration_revision=1", (b"u" * 32,))
    connection.execute("INSERT INTO mentat_owner_auth_credentials(device_id,credential_lookup_digest,cose_public_key,state,created_at) VALUES (?, ?, ?, 'active', 100)", ("device_fixture_0000000000", b"d" * 32, b"fixture-key"))
    for index, state in enumerate(("active", "revoked")):
        connection.execute("INSERT INTO mentat_owner_auth_sessions(session_digest,csrf_digest,device_id,state,created_at,reauthenticated_at,last_seen_at,idle_expires_at,absolute_expires_at,revoked_at) VALUES (?, ?, ?, ?, 100, 0, 100, 200, 300, ?)", (bytes([index + 1]) * 32, bytes([index + 3]) * 32, "device_fixture_0000000000", state, None if state == "active" else 150))
    connection.execute("INSERT INTO mentat_owner_auth_sse_reservations VALUES (?, ?, 1, 110)", ("sse_fixture_000000000000", b"\x01" * 32))
    connection.execute("INSERT INTO mentat_owner_auth_ceremonies(ceremony_id,purpose,challenge_digest,configuration_revision,expires_at,state,created_at) VALUES (?, 'authentication', ?, 1, 180, 'pending', 100)", ("ceremony_fixture_00000000", b"c" * 32))
    connection.commit()
    return connection


class Schema25ForwardTests(unittest.TestCase):
    def test_released_schema24_private_snapshot_still_validates_and_sanitizes(self):
        connection = schema24()
        self.addCleanup(connection.close)
        connection.execute("INSERT INTO mentat_agent_registry_state(singleton,authority,migration_contract,source_kind,source_sha256,source_agent_count,cutover_at) VALUES(1,'sqlite',?,'fresh',?,0,1)", (mentat_db.AGENT_REGISTRY_AUTHORITY_CONTRACT, mentat_db.EMPTY_AGENT_REGISTRY_SOURCE_SHA256))
        connection.commit()
        unit = PrivateConsoleUnit(json.dumps({"schema_version": 3, "runs": []}).encode(), connection.serialize(), None, ())
        validate_private_console_unit(unit)
        restored = sanitize_owner_auth_restore_unit(unit)
        validate_private_console_unit(restored)
        inspected = sqlite3.connect(":memory:")
        self.addCleanup(inspected.close)
        inspected.deserialize(restored.database_raw)
        self.assertEqual(inspected.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 24)
        self.assertEqual(inspected.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions WHERE state='active'").fetchone()[0], 0)

    def test_populated_migration_preserves_sessions_and_sse_foreign_key_and_trigger(self):
        connection = schema24()
        self.addCleanup(connection.close)
        before_sessions = connection.execute("SELECT * FROM mentat_owner_auth_sessions ORDER BY session_digest").fetchall()
        old_columns = [row[1] for row in connection.execute("PRAGMA table_info(mentat_owner_auth_sessions)")]
        before_sse = connection.execute("SELECT * FROM mentat_owner_auth_sse_reservations").fetchall()
        before_ceremony = connection.execute("SELECT * FROM mentat_owner_auth_ceremonies").fetchall()
        ceremony_columns = [row[1] for row in connection.execute("PRAGMA table_info(mentat_owner_auth_ceremonies)")]
        owner_auth.validate_owner_auth_connection(connection)  # Historical backup remains readable.
        mentat_db.migrate(connection)
        self.assertEqual(mentat_db.schema_signature_state(connection, 25), "expected")
        self.assertEqual(connection.execute("SELECT " + ",".join(old_columns) + " FROM mentat_owner_auth_sessions ORDER BY session_digest").fetchall(), before_sessions)
        self.assertEqual(connection.execute("SELECT * FROM mentat_owner_auth_sse_reservations").fetchall(), before_sse)
        self.assertEqual(connection.execute("SELECT " + ",".join(ceremony_columns) + " FROM mentat_owner_auth_ceremonies").fetchall(), before_ceremony)
        self.assertEqual(connection.execute("SELECT owner_generation FROM mentat_owner_auth_ceremonies").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT auth_method,owner_generation,principal_digest FROM mentat_owner_auth_sessions").fetchall(), [("passkey", 0, None)] * 2)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_google_configuration").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_google_principal").fetchone()[0], 0)
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(connection.execute("PRAGMA foreign_key_list(mentat_owner_auth_sse_reservations)").fetchone()[2], "mentat_owner_auth_sessions")
        owner_auth.validate_owner_auth_connection(connection)
        connection.execute("UPDATE mentat_owner_auth_sessions SET state='revoked',revoked_at=150 WHERE state='active'")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations").fetchone()[0], 0)

    def test_changed_source_and_mid_rewrite_failure_leave_schema24_and_restore_fk_enforcement(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                connection = schema24()
                try:
                    if corrupt:
                        connection.execute("CREATE INDEX unexpected_owner_index ON mentat_owner_auth_sessions(state)")
                    before = mentat_db.schema_signature(connection)
                    original = mentat_db._execute_script_in_active_transaction
                    def fail_after_rewrite(conn, script):
                        original(conn, script)
                        raise RuntimeError("injected failure before receipt")
                    with patch.object(mentat_db, "_execute_script_in_active_transaction", side_effect=fail_after_rewrite), self.assertRaises((mentat_db.MentatDatabaseError, RuntimeError)):
                        mentat_db.migrate(connection)
                    self.assertEqual(mentat_db.schema_signature(connection), before)
                    self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 24)
                    self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations").fetchone()[0], 1)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions").fetchone()[0], 2)
                finally:
                    connection.close()


class OwnerMethodTests(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy.OwnerAuthAuthorityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        _, self.passkey = self.fixture.bootstrap()
        self.authority = self.fixture.authority

    def google_fixture(self):
        connection = mentat_db.connect(self.fixture.root)
        self.addCleanup(connection.close)
        now = time.time()
        issuer, subject = "https://accounts.google.com", "private-google-subject"
        principal = owner_auth.google_principal_digest(issuer, subject)
        cookie, csrf = owner_auth._token(32), owner_auth._token(32)
        with mentat_db.transaction(connection, immediate=True):
            connection.execute("UPDATE mentat_owner_auth_sessions SET state='revoked',revoked_at=? WHERE state='active'", (now,))
            connection.execute("UPDATE mentat_owner_auth_credentials SET state='revoked',revoked_at=? WHERE state='active'", (now,))
            connection.execute("UPDATE mentat_owner_auth_state SET auth_method='google',owner_generation=1")
            connection.execute("INSERT INTO mentat_owner_google_configuration VALUES (1, '123-test.apps.googleusercontent.com', 'https://mentat.example', 'environment', 0, 1)")
            connection.execute("INSERT INTO mentat_owner_google_principal VALUES (1, ?, ?, 'owner@example.test', ?, 1, 1)", (issuer, subject, principal))
            connection.execute("INSERT INTO mentat_owner_auth_sessions(session_digest,csrf_digest,device_id,auth_method,owner_generation,principal_digest,state,created_at,reauthenticated_at,last_seen_at,idle_expires_at,absolute_expires_at) VALUES (?, ?, NULL, 'google', 1, ?, 'active', ?, 0, ?, ?, ?)", (owner_auth._digest(owner_auth._token_bytes(cookie, 32)), owner_auth._digest(owner_auth._token_bytes(csrf, 32)), principal, now, now, now + 3600, now + 86400))
        return connection, cookie, csrf

    def test_google_session_has_no_fake_device_and_does_not_unlock_passkey_flows(self):
        connection, cookie, csrf = self.google_fixture()
        row = self.authority.authenticate_session(cookie, csrf)
        self.assertIsNone(row["device_id"])
        self.assertEqual(row["auth_method"], "google")
        self.assertEqual(row["reauthenticated_at"], 0)
        owner_auth.validate_owner_auth_connection(connection)
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.authenticate_session(self.passkey.cookie_value, self.passkey.csrf_value)
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.start_authentication()
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.start_device_reauthentication(cookie, csrf)
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.authenticate_session(cookie, owner_auth._token(32))

    def test_generation_principal_configuration_and_restore_gates_fail_closed(self):
        connection, cookie, csrf = self.google_fixture()
        mutations = (
            "UPDATE mentat_owner_auth_state SET owner_generation=2",
            "UPDATE mentat_owner_google_configuration SET requires_reconciliation=1",
            "UPDATE mentat_owner_google_configuration SET revision=2",
            "UPDATE mentat_owner_google_principal SET subject='other-subject'",
            "UPDATE mentat_owner_auth_state SET auth_method='passkey'",
        )
        for sql in mutations:
            with self.subTest(sql=sql):
                connection.execute("SAVEPOINT tamper")
                connection.execute(sql)
                with self.assertRaises(owner_auth.OwnerAuthError):
                    owner_auth.validate_owner_auth_connection(connection)
                connection.execute("ROLLBACK TO tamper")
                connection.execute("RELEASE tamper")
        reservation = self.authority.reserve_sse(cookie)
        self.assertTrue(reservation.reservation_id)
        with mentat_db.transaction(connection, immediate=True):
            owner_auth.sanitize_after_restore(connection)
        self.assertEqual(connection.execute("SELECT requires_reconciliation FROM mentat_owner_google_configuration").fetchone()[0], 1)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_google_principal").fetchone()[0], 1)
        owner_auth.validate_owner_auth_connection(connection)
        with self.assertRaises(owner_auth.OwnerAuthError):
            self.authority.authenticate_session(cookie, csrf)

    def test_database_rejects_mixed_method_or_fake_reauthentication(self):
        connection, _cookie, _csrf = self.google_fixture()
        for sql in (
            "UPDATE mentat_owner_auth_sessions SET device_id='device-does-not-exist' WHERE auth_method='google'",
            "UPDATE mentat_owner_auth_sessions SET reauthenticated_at=1 WHERE auth_method='google'",
            "UPDATE mentat_owner_auth_sessions SET principal_digest=NULL WHERE auth_method='google'",
        ):
            with self.subTest(sql=sql), self.assertRaises(sqlite3.IntegrityError):
                connection.execute(sql)
            connection.rollback()

    def test_private_backup_restore_and_compatible_export_keep_identity_boundaries(self):
        connection, cookie, csrf = self.google_fixture()
        unit = capture_private_console_unit(self.fixture.root)
        validate_private_console_unit(unit)
        restored = sanitize_owner_auth_restore_unit(unit)
        validate_private_console_unit(restored)
        restored_path = self.fixture.root / "restored-inspection.sqlite3"
        restored_path.write_bytes(restored.database_raw)
        inspected = sqlite3.connect(restored_path)
        self.addCleanup(inspected.close)
        self.assertEqual(inspected.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions WHERE state='active'").fetchone()[0], 0)
        self.assertEqual(inspected.execute("SELECT requires_reconciliation FROM mentat_owner_google_configuration").fetchone()[0], 1)
        self.assertEqual(inspected.execute("SELECT subject FROM mentat_owner_google_principal").fetchone()[0], "private-google-subject")
        compatible = _schema5_private_unit(unit)
        compatible_path = self.fixture.root / "compatible-inspection.sqlite3"
        compatible_path.write_bytes(compatible.database_raw)
        compatible_connection = sqlite3.connect(compatible_path)
        self.addCleanup(compatible_connection.close)
        self.assertEqual(compatible_connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'mentat_owner_%'").fetchall(), [])
        self.assertEqual(compatible_connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 5)
        # Export/restore transforms snapshots, not the live source authority.
        self.assertEqual(connection.execute("SELECT requires_reconciliation FROM mentat_owner_google_configuration").fetchone()[0], 0)
        self.authority.authenticate_session(cookie, csrf)

    def test_old_generation_cannot_manage_security_even_with_fresh_passkey_reauthentication(self):
        ceremony = self.authority.start_device_reauthentication(self.passkey.cookie_value, self.passkey.csrf_value)
        fresh = self.authority.finish_authentication(ceremony.ceremony_id, self.fixture.assertion(b"credential-a", 1))
        connection = mentat_db.connect(self.fixture.root)
        self.addCleanup(connection.close)
        device = connection.execute("SELECT device_id FROM mentat_owner_auth_credentials WHERE state='active'").fetchone()[0]
        connection.execute("UPDATE mentat_owner_auth_state SET owner_generation=1")
        connection.commit()
        actions = (
            lambda: self.authority.start_device_add(fresh.cookie_value, fresh.csrf_value, "extra"),
            lambda: self.authority.revoke_device(fresh.cookie_value, fresh.csrf_value, device, 1),
            lambda: self.authority.rotate_recovery_codes(fresh.cookie_value, fresh.csrf_value),
            lambda: self.authority.sign_out_all(fresh.cookie_value, fresh.csrf_value),
            lambda: self.authority.start_device_reauthentication(fresh.cookie_value, fresh.csrf_value),
        )
        with patch.object(self.authority, "_admit_durable", return_value=True):
            for action in actions:
                with self.assertRaisesRegex(owner_auth.OwnerAuthError, "^invalid$"):
                    action()
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state='active'").fetchone()[0], 10)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials WHERE state='active'").fetchone()[0], 1)

    def test_google_reconciliation_blocks_security_mutations(self):
        connection, cookie, csrf = self.google_fixture()
        connection.execute("UPDATE mentat_owner_google_configuration SET requires_reconciliation=1")
        connection.commit()
        with self.assertRaisesRegex(owner_auth.OwnerAuthError, "^invalid$"):
            self.authority.sign_out_all(cookie, csrf)

    def test_pending_ceremony_is_generation_bound_before_verification(self):
        ceremony = self.authority.start_authentication()
        connection = mentat_db.connect(self.fixture.root)
        self.addCleanup(connection.close)
        connection.execute("UPDATE mentat_owner_auth_state SET owner_generation=1")
        connection.commit()
        with patch.object(self.authority, "_assertion_verifier") as verify, self.assertRaisesRegex(owner_auth.OwnerAuthError, "^invalid$"):
            self.authority.finish_authentication(ceremony.ceremony_id, self.fixture.assertion(b"credential-a", 1))
        verify.assert_not_called()

    def test_device_registration_rechecks_generation_after_external_verification(self):
        reauth = self.authority.start_device_reauthentication(self.passkey.cookie_value, self.passkey.csrf_value)
        fresh = self.authority.finish_authentication(reauth.ceremony_id, self.fixture.assertion(b"credential-a", 1))
        ceremony = self.authority.start_device_add(fresh.cookie_value, fresh.csrf_value, "extra")
        original = self.authority._registration_verifier
        def changed_generation(payload, **kwargs):
            connection = mentat_db.connect(self.fixture.root)
            try:
                connection.execute("UPDATE mentat_owner_auth_state SET owner_generation=1")
                connection.commit()
            finally:
                connection.close()
            return original(payload, **kwargs)
        with patch.object(self.authority, "_registration_verifier", side_effect=changed_generation), self.assertRaisesRegex(owner_auth.OwnerAuthError, "^invalid$"):
            self.authority.finish_registration(ceremony.ceremony_id, self.fixture.registration(b"credential-b"))
        connection = mentat_db.connect(self.fixture.root)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials").fetchone()[0], 1)

    def test_authentication_rechecks_generation_after_verification_outside_transaction(self):
        ceremony = self.authority.start_authentication()
        original = self.authority._assertion_verifier
        def changed_generation(payload, **kwargs):
            connection = mentat_db.connect(self.fixture.root)
            try:
                connection.execute("UPDATE mentat_owner_auth_state SET owner_generation=1")
                connection.commit()
            finally:
                connection.close()
            return original(payload, **kwargs)
        with patch.object(self.authority, "_assertion_verifier", side_effect=changed_generation), self.assertRaisesRegex(owner_auth.OwnerAuthError, "^invalid$"):
            self.authority.finish_authentication(ceremony.ceremony_id, self.fixture.assertion(b"credential-a", 1))
        connection = mentat_db.connect(self.fixture.root)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions").fetchone()[0], 1)

    def test_restore_retains_bounded_terminal_evidence_at_full_capacity(self):
        connection, _cookie, _csrf = self.google_fixture()
        active = connection.execute("SELECT session_digest FROM mentat_owner_auth_sessions WHERE state='active'").fetchone()[0]
        connection.execute("DELETE FROM mentat_owner_auth_sessions WHERE state!='active'")
        device = connection.execute("SELECT device_id FROM mentat_owner_auth_credentials LIMIT 1").fetchone()[0]
        for index in range(owner_auth.MAX_TERMINAL_SESSIONS):
            connection.execute("INSERT INTO mentat_owner_auth_sessions(session_digest,csrf_digest,device_id,state,created_at,reauthenticated_at,last_seen_at,idle_expires_at,absolute_expires_at,revoked_at) VALUES (?, ?, ?, 'revoked', 100, 0, 100, 200, 300, ?)", (secrets.token_bytes(32), secrets.token_bytes(32), device, 150 + index))
        connection.commit()
        owner_auth.validate_owner_auth_connection(connection)
        with mentat_db.transaction(connection, immediate=True):
            owner_auth.sanitize_after_restore(connection)
        owner_auth.validate_owner_auth_connection(connection)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions").fetchone()[0], owner_auth.MAX_TERMINAL_SESSIONS)
        self.assertEqual(connection.execute("SELECT state FROM mentat_owner_auth_sessions WHERE session_digest=?", (active,)).fetchone()[0], "revoked")

    def test_sign_out_all_keeps_full_terminal_history_backup_valid(self):
        connection, cookie, csrf = self.google_fixture()
        connection.execute("DELETE FROM mentat_owner_auth_sessions WHERE state!='active'")
        device = connection.execute("SELECT device_id FROM mentat_owner_auth_credentials LIMIT 1").fetchone()[0]
        now = time.time()
        for _ in range(owner_auth.MAX_TERMINAL_SESSIONS):
            connection.execute("INSERT INTO mentat_owner_auth_sessions(session_digest,csrf_digest,device_id,state,created_at,reauthenticated_at,last_seen_at,idle_expires_at,absolute_expires_at,revoked_at) VALUES (?, ?, ?, 'revoked', ?, 0, ?, ?, ?, ?)", (secrets.token_bytes(32), secrets.token_bytes(32), device, now-10, now-10, now+100, now+200, now-1))
        connection.commit()
        owner_auth.validate_owner_auth_connection(connection)
        self.authority.sign_out_all(cookie, csrf)
        owner_auth.validate_owner_auth_connection(connection)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions").fetchone()[0], owner_auth.MAX_TERMINAL_SESSIONS)


if __name__ == "__main__":
    unittest.main()
