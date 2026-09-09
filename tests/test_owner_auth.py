"""Focused contract tests for the MDA-4A private authority."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mentat_db import SCHEMA_VERSION, connect, transaction
from owner_auth import (
    MAX_SSE_STREAMS,
    MAX_TERMINAL_CEREMONIES,
    SECURITY_MANAGEMENT_LIMIT,
    UNSAFE_REQUEST_LIMIT,
    OwnerAuthAuthority,
    OwnerAuthError,
    cleanup_owner_auth_at_startup,
    sanitize_after_restore,
)
from owner_auth_webauthn import AssertionEvidence, RegistrationEvidence, WebAuthnVerificationError


class OwnerAuthAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.authority = OwnerAuthAuthority(
            self.root,
            _registration_verifier=self._fixture_registration,
            _assertion_verifier=self._fixture_assertion,
            _assertion_credential_id=lambda payload: str(payload["credential"]).encode("ascii"),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def registration(value: bytes = b"credential-a") -> dict[str, str]:
        return {"fixture": "registration", "credential": value.decode("ascii")}

    @staticmethod
    def assertion(value: bytes, count: int) -> dict[str, int | str]:
        return {"fixture": "assertion", "credential": value.decode("ascii"), "count": count}

    @staticmethod
    def _fixture_registration(payload, **_kwargs) -> RegistrationEvidence:
        if set(payload) != {"fixture", "credential"} or payload.get("fixture") != "registration":
            raise WebAuthnVerificationError("invalid")
        return RegistrationEvidence(str(payload["credential"]).encode("ascii"), b"minimal-cose-key", 0, False, False)

    @staticmethod
    def _fixture_assertion(payload, **_kwargs) -> AssertionEvidence:
        if set(payload) != {"fixture", "credential", "count"} or payload.get("fixture") != "assertion" or type(payload.get("count")) is not int:
            raise WebAuthnVerificationError("invalid")
        return AssertionEvidence(str(payload["credential"]).encode("ascii"), int(payload["count"]), False, False)

    def bootstrap(self):
        grant = self.authority.open_bootstrap("https://mentat.example")
        ceremony = self.authority.start_bootstrap_registration(grant.code, "primary")
        session = self.authority.finish_registration(ceremony.ceremony_id, self.registration())
        return grant, session

    def test_migration_is_empty_and_private_until_the_local_bootstrap(self) -> None:
        connection = connect(self.root)
        try:
            self.assertEqual(SCHEMA_VERSION, 24)
            self.assertEqual(
                connection.execute("SELECT state FROM mentat_owner_auth_state").fetchone()[0],
                "unbootstrapped",
            )
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials").fetchone()[0], 0)
        finally:
            connection.close()

    def test_bootstrap_is_one_time_and_replayed_completion_is_atomic(self) -> None:
        grant = self.authority.open_bootstrap("https://mentat.example")
        ceremony = self.authority.start_bootstrap_registration(grant.code, "primary")
        self.authority.finish_registration(ceremony.ceremony_id, self.registration())
        with self.assertRaises(OwnerAuthError):
            self.authority.finish_registration(ceremony.ceremony_id, self.registration(b"credential-b"))
        with self.assertRaises(OwnerAuthError):
            self.authority.open_bootstrap("https://mentat.example")
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials WHERE state = 'active'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state = 'active'").fetchone()[0], 10)
        finally:
            connection.close()

    def test_public_completion_rejects_forged_evidence_objects_before_the_test_seam(self) -> None:
        grant = self.authority.open_bootstrap("https://mentat.example")
        ceremony = self.authority.start_bootstrap_registration(grant.code, "primary")
        with self.assertRaises(OwnerAuthError):
            self.authority.finish_registration(
                ceremony.ceremony_id,
                RegistrationEvidence(b"forged", b"forged", 0, False, False),  # type: ignore[arg-type]
            )
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT state FROM mentat_owner_auth_state").fetchone()[0], "bootstrap_open")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials").fetchone()[0], 0)
        finally:
            connection.close()

    def test_recovery_reserves_then_replaces_all_prior_live_authority(self) -> None:
        _bootstrap, session = self.bootstrap()
        ceremony = self.authority.start_recovery_registration(session.recovery_codes[0], "replacement")
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state = 'reserved'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state = 'active'").fetchone()[0], 9)
        finally:
            connection.close()
        replacement = self.authority.finish_registration(ceremony.ceremony_id, self.registration(b"credential-b"))
        self.assertEqual(len(replacement.recovery_codes), 10)
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials WHERE state = 'active'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions WHERE state = 'active'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state = 'active'").fetchone()[0], 10)
        finally:
            connection.close()

    def test_recovery_rejects_a_phc_verifier_outside_the_pinned_policy(self) -> None:
        _bootstrap, session = self.bootstrap()
        connection = connect(self.root)
        try:
            connection.execute("UPDATE mentat_owner_auth_recovery_codes SET verifier = replace(verifier, 'm=65536', 'm=65535')")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaises(OwnerAuthError):
            self.authority.start_recovery_registration(session.recovery_codes[0], "replacement")

    def test_counter_regression_revokes_a_suspected_clone_and_all_its_sessions(self) -> None:
        self.bootstrap()
        ceremony = self.authority.start_authentication()
        self.authority.finish_authentication(ceremony.ceremony_id, self.assertion(b"credential-a", 5))
        regression = self.authority.start_authentication()
        with self.assertRaises(OwnerAuthError):
            self.authority.finish_authentication(regression.ceremony_id, self.assertion(b"credential-a", 4))
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT state FROM mentat_owner_auth_credentials").fetchone()[0], "suspected_clone")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions WHERE state = 'active'").fetchone()[0], 0)
        finally:
            connection.close()

    def test_nonzero_counter_must_strictly_increase(self) -> None:
        self.bootstrap()
        first = self.authority.start_authentication()
        self.authority.finish_authentication(first.ceremony_id, self.assertion(b"credential-a", 5))
        repeated = self.authority.start_authentication()
        with self.assertRaises(OwnerAuthError):
            self.authority.finish_authentication(repeated.ceremony_id, self.assertion(b"credential-a", 5))
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT state FROM mentat_owner_auth_credentials").fetchone()[0], "suspected_clone")
        finally:
            connection.close()

    def test_device_add_and_exact_revision_revocation_keep_recovery_available(self) -> None:
        _bootstrap, session = self.bootstrap()
        reauth = self.authority.start_device_reauthentication(session.cookie_value, session.csrf_value)
        session = self.authority.finish_authentication(reauth.ceremony_id, self.assertion(b"credential-a", 1))
        ceremony = self.authority.start_device_add(session.cookie_value, session.csrf_value, "secondary")
        added = self.authority.finish_registration(ceremony.ceremony_id, self.registration(b"credential-b"))
        connection = connect(self.root)
        try:
            devices = connection.execute("SELECT device_id, revision FROM mentat_owner_auth_credentials WHERE state = 'active' ORDER BY created_at").fetchall()
        finally:
            connection.close()
        self.assertEqual(len(devices), 2)
        reauth = self.authority.start_device_reauthentication(added.cookie_value, added.csrf_value)
        added = self.authority.finish_authentication(reauth.ceremony_id, self.assertion(b"credential-b", 1))
        with self.assertRaises(OwnerAuthError):
            self.authority.revoke_device(session.cookie_value, session.csrf_value, devices[1][0], devices[1][1] + 2)
        self.authority.revoke_device(added.cookie_value, added.csrf_value, devices[1][0], devices[1][1] + 1)
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT state FROM mentat_owner_auth_credentials WHERE device_id = ?", (devices[1][0],)).fetchone()[0], "revoked")
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state = 'active'").fetchone()[0], 10)
        finally:
            connection.close()

    def test_restore_sanitization_keeps_snapshot_credentials_but_invalidates_live_grants(self) -> None:
        _bootstrap, session = self.bootstrap()
        ceremony = self.authority.start_recovery_registration(session.recovery_codes[0], "replacement")
        connection = connect(self.root)
        try:
            connection.execute("BEGIN IMMEDIATE")
            sanitize_after_restore(connection)
            connection.commit()
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_credentials WHERE state = 'active'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions WHERE state = 'active'").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_ceremonies WHERE state = 'pending'").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_recovery_codes WHERE state = 'reserved'").fetchone()[0], 0)
        finally:
            connection.close()
        with self.assertRaises(OwnerAuthError):
            self.authority.finish_registration(ceremony.ceremony_id, self.registration(b"credential-b"))

    def test_discoverable_login_and_global_unauthenticated_ceremony_cap(self) -> None:
        _bootstrap, _session = self.bootstrap()
        ceremonies = [self.authority.start_authentication() for _ in range(5)]
        self.assertNotIn("allowCredentials", ceremonies[0].public_key_options)
        self.assertEqual(ceremonies[0].public_key_options["userVerification"], "required")
        with self.assertRaises(OwnerAuthError):
            self.authority.start_authentication()

    def test_registration_options_require_discoverable_es256_credentials(self) -> None:
        grant = self.authority.open_bootstrap("https://mentat.example")
        ceremony = self.authority.start_bootstrap_registration(grant.code, "primary")
        options = ceremony.public_key_options
        self.assertEqual(options["pubKeyCredParams"], ({"type": "public-key", "alg": -7},))
        self.assertEqual(options["authenticatorSelection"]["residentKey"], "required")
        self.assertTrue(options["authenticatorSelection"]["requireResidentKey"])
        self.assertTrue(options["extensions"]["credProps"])

    def test_reauthentication_rotates_authorizing_session_before_device_management(self) -> None:
        _bootstrap, session = self.bootstrap()
        with self.assertRaises(OwnerAuthError):
            self.authority.start_device_add(session.cookie_value, session.csrf_value, "secondary")
        ceremony = self.authority.start_device_reauthentication(session.cookie_value, session.csrf_value)
        renewed = self.authority.finish_authentication(ceremony.ceremony_id, self.assertion(b"credential-a", 1))
        with self.assertRaises(OwnerAuthError):
            self.authority.authenticate_session(session.cookie_value)
        add = self.authority.start_device_add(renewed.cookie_value, renewed.csrf_value, "secondary")
        self.assertEqual(add.public_key_options["authenticatorSelection"]["userVerification"], "required")

    def test_sse_reservations_are_exactly_two_and_release_on_disconnect_revocation_and_startup(self) -> None:
        _bootstrap, session = self.bootstrap()
        first = self.authority.reserve_sse(session.cookie_value)
        second = self.authority.reserve_sse(session.cookie_value)
        with self.assertRaises(OwnerAuthError):
            self.authority.reserve_sse(session.cookie_value)
        self.authority.release_sse(first.reservation_id)
        self.authority.release_sse(first.reservation_id)
        third = self.authority.reserve_sse(session.cookie_value)
        connection = connect(self.root)
        try:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations").fetchone()[0],
                MAX_SSE_STREAMS,
            )
        finally:
            connection.close()
        self.authority.sign_out_all(session.cookie_value, session.csrf_value)
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations").fetchone()[0], 0)
        finally:
            connection.close()
        # A restart is also terminal for process-owned streams, including a
        # row left behind by a crash before its disconnect callback.
        session = self.authority.finish_authentication(
            self.authority.start_authentication().ceremony_id,
            self.assertion(b"credential-a", 1),
        )
        self.authority.reserve_sse(session.cookie_value)
        cleanup_owner_auth_at_startup(self.root)
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sse_reservations").fetchone()[0], 0)
        finally:
            connection.close()

    def test_recovery_rotation_and_signout_all_revoke_prior_grants(self) -> None:
        _bootstrap, session = self.bootstrap()
        reauth = self.authority.start_device_reauthentication(session.cookie_value, session.csrf_value)
        renewed = self.authority.finish_authentication(reauth.ceremony_id, self.assertion(b"credential-a", 1))
        rotated = self.authority.rotate_recovery_codes(renewed.cookie_value, renewed.csrf_value)
        self.assertEqual(len(rotated), 10)
        with self.assertRaises(OwnerAuthError):
            self.authority.start_recovery_registration(session.recovery_codes[0], "replacement")
        # #201 deliberately gives security management its own one-action
        # session/minute budget; use a fresh session for the later action.
        fresh = self.authority.finish_authentication(
            self.authority.start_authentication().ceremony_id,
            self.assertion(b"credential-a", 2),
        )
        self.authority.sign_out_all(fresh.cookie_value, fresh.csrf_value)
        with self.assertRaises(OwnerAuthError):
            self.authority.authenticate_session(fresh.cookie_value)

    def test_failed_completion_is_consumed_before_verifier_and_cannot_replay(self) -> None:
        self.bootstrap()
        ceremony = self.authority.start_authentication()

        def fail(*_args, **_kwargs):
            raise WebAuthnVerificationError("invalid")

        self.authority._assertion_verifier = fail
        with self.assertRaises(OwnerAuthError):
            self.authority.finish_authentication(ceremony.ceremony_id, self.assertion(b"credential-a", 1))
        connection = connect(self.root)
        try:
            self.assertEqual(
                connection.execute("SELECT state FROM mentat_owner_auth_ceremonies WHERE ceremony_id = ?", (ceremony.ceremony_id,)).fetchone()[0],
                "cancelled",
            )
        finally:
            connection.close()
        with self.assertRaises(OwnerAuthError):
            self.authority.finish_authentication(ceremony.ceremony_id, self.assertion(b"credential-a", 1))

    def test_racing_completion_cannot_replay_while_the_first_verifier_is_live(self) -> None:
        import threading

        self.bootstrap()
        ceremony = self.authority.start_authentication()
        entered = threading.Event()
        release = threading.Event()

        def delayed(payload, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return self._fixture_assertion(payload, **kwargs)

        self.authority._assertion_verifier = delayed
        outcome: list[object] = []

        def first_completion() -> None:
            try:
                outcome.append(self.authority.finish_authentication(ceremony.ceremony_id, self.assertion(b"credential-a", 1)))
            except Exception as exc:  # assertion below reports the exact unexpected error
                outcome.append(exc)

        thread = threading.Thread(target=first_completion)
        thread.start()
        self.assertTrue(entered.wait(3))
        with self.assertRaises(OwnerAuthError):
            self.authority.finish_authentication(ceremony.ceremony_id, self.assertion(b"credential-a", 1))
        release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcome), 1)
        self.assertNotIsInstance(outcome[0], Exception)

    def test_recovery_flood_is_rejected_before_argon2_work(self) -> None:
        _bootstrap, session = self.bootstrap()
        with patch("owner_auth._verify_recovery", return_value=False) as verify:
            for _ in range(5):
                with self.assertRaises(OwnerAuthError):
                    self.authority.start_recovery_registration(session.recovery_codes[0], "replacement")
            admitted_work = verify.call_count
            with self.assertRaises(OwnerAuthError):
                self.authority.start_recovery_registration(session.recovery_codes[0], "replacement")
        self.assertEqual(admitted_work, 50)
        self.assertEqual(verify.call_count, admitted_work)

    def test_failed_recovery_keeps_its_reserved_code_until_success_or_restart_reconciliation(self) -> None:
        _bootstrap, session = self.bootstrap()
        ceremony = self.authority.start_recovery_registration(session.recovery_codes[0], "replacement")

        def fail(*_args, **_kwargs):
            raise WebAuthnVerificationError("invalid")

        self.authority._registration_verifier = fail
        with self.assertRaises(OwnerAuthError):
            self.authority.finish_registration(ceremony.ceremony_id, self.registration(b"credential-b"))
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT state FROM mentat_owner_auth_recovery_codes WHERE recovery_id = (SELECT recovery_id FROM mentat_owner_auth_ceremonies WHERE ceremony_id = ?)", (ceremony.ceremony_id,)).fetchone()[0], "active")
        finally:
            connection.close()
        # The same recovery code may start one fresh ceremony after its failed
        # WebAuthn completion; the terminal ceremony itself remains unusable.
        self.authority._registration_verifier = self._fixture_registration
        retry = self.authority.start_recovery_registration(session.recovery_codes[0], "replacement")
        self.assertNotEqual(retry.ceremony_id, ceremony.ceremony_id)

    def test_terminal_ceremony_collector_has_a_global_cap(self) -> None:
        self.bootstrap()
        connection = self.authority._open()
        try:
            with transaction(connection, immediate=True):
                for index in range(MAX_TERMINAL_CEREMONIES + 8):
                    connection.execute(
                        "INSERT INTO mentat_owner_auth_ceremonies(ceremony_id, purpose, challenge_digest, configuration_revision, expires_at, state, created_at, consumed_at) "
                        "VALUES (?, 'authentication', ?, 1, ?, 'cancelled', ?, ?)",
                        (f"terminal-{index:014d}", bytes([index % 256]) * 32, float(index), float(index), float(index)),
                    )
                self.authority._cleanup(connection, 1000.0)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_ceremonies WHERE state != 'pending' AND state != 'consumed'").fetchone()[0],
                    MAX_TERMINAL_CEREMONIES,
                )
        finally:
            connection.close()

    def test_exact_budget_classes_keep_unsafe_and_security_management_separate(self) -> None:
        _bootstrap, session = self.bootstrap()
        # Exercise the authoritative transaction directly: no verifier/body
        # parsing occurs before these class-specific counters are committed.
        import hashlib
        subject = hashlib.sha256(session.cookie_value.encode("ascii")).digest()
        fixed_clock = OwnerAuthAuthority(self.root, clock=lambda: 60.0)
        for _ in range(UNSAFE_REQUEST_LIMIT):
            self.assertTrue(fixed_clock._admit_durable("unsafe_request", subject, UNSAFE_REQUEST_LIMIT))
        self.assertFalse(fixed_clock._admit_durable("unsafe_request", subject, UNSAFE_REQUEST_LIMIT))
        self.assertTrue(fixed_clock._admit_durable("security_management", subject, SECURITY_MANAGEMENT_LIMIT))
        self.assertFalse(fixed_clock._admit_durable("security_management", subject, SECURITY_MANAGEMENT_LIMIT))

    def test_restore_sanitization_preserves_terminal_session_grace(self) -> None:
        _bootstrap, _session = self.bootstrap()
        connection = connect(self.root)
        try:
            connection.execute("BEGIN IMMEDIATE")
            sanitize_after_restore(connection, now=1000.0)
            connection.commit()
        finally:
            connection.close()
        connection = self.authority._open()
        try:
            with transaction(connection, immediate=True):
                self.authority._cleanup(connection, 1000.0 + 24 * 60 * 60 - 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions").fetchone()[0], 1)
                self.authority._cleanup(connection, 1000.0 + 24 * 60 * 60 + 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM mentat_owner_auth_sessions").fetchone()[0], 0)
        finally:
            connection.close()

    def test_startup_releases_an_abandoned_consumed_recovery_reservation(self) -> None:
        _bootstrap, session = self.bootstrap()
        ceremony = self.authority.start_recovery_registration(session.recovery_codes[0], "replacement")
        self.authority._consume_ceremony_durable(ceremony.ceremony_id, ("recovery",))
        cleanup_owner_auth_at_startup(self.root)
        connection = connect(self.root)
        try:
            self.assertEqual(
                connection.execute(
                    "SELECT state FROM mentat_owner_auth_recovery_codes WHERE recovery_id = "
                    "(SELECT recovery_id FROM mentat_owner_auth_ceremonies WHERE ceremony_id = ?)",
                    (ceremony.ceremony_id,),
                ).fetchone()[0],
                "active",
            )
        finally:
            connection.close()

    def test_startup_terminalizes_every_consumed_purpose_under_the_global_cap(self) -> None:
        """A crash cannot leave any verifier-in-flight marker outside retention."""

        purposes = ("bootstrap", "authentication", "reauthentication", "device_add", "recovery")
        ceremony_ids = {
            purpose: f"startup-{purpose}-000000000000000000000000"
            for purpose in purposes
        }
        connection = connect(self.root)
        try:
            with transaction(connection, immediate=True):
                for index in range(MAX_TERMINAL_CEREMONIES - len(purposes)):
                    connection.execute(
                        "INSERT INTO mentat_owner_auth_ceremonies(ceremony_id, purpose, challenge_digest, configuration_revision, expires_at, state, created_at, consumed_at) "
                        "VALUES (?, 'authentication', ?, 1, 10000, 'cancelled', ?, ?)",
                        (f"retained-{index:014d}", bytes([index]) * 32, float(index), float(index)),
                    )
                for index, purpose in enumerate(purposes):
                    recovery_id = None
                    if purpose == "recovery":
                        recovery_id = "startup-recovery-code-000000000000000"
                        connection.execute(
                            "INSERT INTO mentat_owner_auth_recovery_codes(recovery_id, verifier, generation, state, reserved_ceremony_id, created_at, updated_at) "
                            "VALUES (?, ?, 1, 'reserved', ?, ?, ?)",
                            (recovery_id, "x" * 80, ceremony_ids[purpose], float(index), float(index)),
                        )
                    connection.execute(
                        "INSERT INTO mentat_owner_auth_ceremonies(ceremony_id, purpose, challenge_digest, configuration_revision, recovery_id, expires_at, state, created_at, consumed_at) "
                        "VALUES (?, ?, ?, 1, ?, 10000, 'consumed', ?, ?)",
                        (ceremony_ids[purpose], purpose, bytes([index]) * 32, recovery_id, float(index), float(index)),
                    )
        finally:
            connection.close()

        cleanup_owner_auth_at_startup(self.root, clock=lambda: 1000.0)

        connection = connect(self.root)
        try:
            rows = connection.execute(
                "SELECT ceremony_id, state FROM mentat_owner_auth_ceremonies "
                "WHERE ceremony_id IN ({})".format(", ".join("?" for _ in ceremony_ids)),
                tuple(ceremony_ids.values()),
            ).fetchall()
            self.assertEqual({row[0]: row[1] for row in rows}, {ceremony_id: "cancelled" for ceremony_id in ceremony_ids.values()})
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM mentat_owner_auth_ceremonies "
                    "WHERE state NOT IN ('pending', 'consumed')"
                ).fetchone()[0],
                MAX_TERMINAL_CEREMONIES,
            )
        finally:
            connection.close()

    def test_startup_cleanup_reopens_expired_bootstrap_state(self) -> None:
        grant = self.authority.open_bootstrap("https://mentat.example")
        connection = connect(self.root)
        try:
            connection.execute("UPDATE mentat_owner_auth_state SET bootstrap_expires_at = 0 WHERE singleton = 1")
            connection.commit()
        finally:
            connection.close()
        cleanup_owner_auth_at_startup(self.root)
        connection = connect(self.root)
        try:
            self.assertEqual(connection.execute("SELECT state FROM mentat_owner_auth_state").fetchone()[0], "unbootstrapped")
        finally:
            connection.close()

    def test_real_fido2_rejects_registration_without_user_presence(self) -> None:
        """Exercise the maintained fido2 parser with real signed structures."""

        import base64
        import hashlib
        import json
        from cryptography.hazmat.primitives.asymmetric import ec
        from fido2 import cbor
        from owner_auth_webauthn import verify_registration

        def b64(value: bytes) -> str:
            return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

        origin = "https://mentat.example"
        rp_id = "mentat.example"
        challenge = b"fido2-registration-challenge-0000"
        client_data = json.dumps(
            {"type": "webauthn.create", "challenge": b64(challenge), "origin": origin},
            separators=(",", ":"),
        ).encode("utf-8")
        key = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
        cose = cbor.encode({1: 2, 3: -7, -1: 1, -2: key.x.to_bytes(32, "big"), -3: key.y.to_bytes(32, "big")})
        def payload(flags: int) -> dict[str, object]:
            auth_data = (
                hashlib.sha256(rp_id.encode("ascii")).digest()
                + bytes([flags])
                + (1).to_bytes(4, "big")
                + b"\0" * 16
                + len(b"credential").to_bytes(2, "big")
                + b"credential"
                + cose
            )
            return {
                "clientDataJSON": b64(client_data),
                "attestationObject": b64(cbor.encode({"fmt": "none", "authData": auth_data, "attStmt": {}})),
                "clientExtensionResults": {"credProps": {"rk": True}},
            }

        accepted = verify_registration(
            payload(0x45),
            challenge_digest=hashlib.sha256(challenge).digest(),
            origin=origin,
            rp_id=rp_id,
        )
        self.assertEqual(accepted.credential_id, b"credential")
        # AT + UV, deliberately without UP.  This used to pass because the
        # registration verifier checked UV only.
        with self.assertRaises(WebAuthnVerificationError):
            verify_registration(
                payload(0x44),
                challenge_digest=hashlib.sha256(challenge).digest(),
                origin=origin,
                rp_id=rp_id,
            )

    def test_real_fido2_assertion_matrix_enforces_up_uv_and_signature(self) -> None:
        import base64
        import hashlib
        import json
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from fido2 import cbor
        from owner_auth_webauthn import verify_assertion

        def b64(value: bytes) -> str:
            return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

        origin = "https://mentat.example"
        rp_id = "mentat.example"
        challenge = b"fido2-assertion-challenge-000000"
        client_data = json.dumps(
            {"type": "webauthn.get", "challenge": b64(challenge), "origin": origin},
            separators=(",", ":"),
        ).encode("utf-8")
        private_key = ec.generate_private_key(ec.SECP256R1())
        public = private_key.public_key().public_numbers()
        cose = cbor.encode({1: 2, 3: -7, -1: 1, -2: public.x.to_bytes(32, "big"), -3: public.y.to_bytes(32, "big")})

        def payload(flags: int) -> dict[str, str]:
            auth_data = hashlib.sha256(rp_id.encode("ascii")).digest() + bytes([flags]) + (9).to_bytes(4, "big")
            signature = private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
            return {
                "credentialId": b64(b"credential"),
                "clientDataJSON": b64(client_data),
                "authenticatorData": b64(auth_data),
                "signature": b64(signature),
            }

        accepted = verify_assertion(payload(0x05), challenge_digest=hashlib.sha256(challenge).digest(), origin=origin, rp_id=rp_id, cose_public_key=cose)
        self.assertEqual(accepted.sign_count, 9)
        for flags in (0x04, 0x01):
            with self.subTest(flags=flags), self.assertRaises(WebAuthnVerificationError):
                verify_assertion(payload(flags), challenge_digest=hashlib.sha256(challenge).digest(), origin=origin, rp_id=rp_id, cose_public_key=cose)


if __name__ == "__main__":
    unittest.main()
