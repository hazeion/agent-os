import concurrent.futures
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from json_store import write_json_atomic
from owner_auth_setup import assert_owner_setup, release_owner_setup, reserve_owner_setup
from private_state import PrivateStateError, connection_server_reservation_path, mentat_server_active, release_mentat_server, reserve_mentat_server


class OwnerSetupReservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_setup_excludes_normal_startup_and_other_setup(self):
        reservation = reserve_owner_setup(self.root, clock=lambda: 100)
        self.assertTrue(mentat_server_active(self.root))
        assert_owner_setup(self.root, reservation, clock=lambda: 699)
        for reserve in (reserve_mentat_server, reserve_owner_setup):
            with self.assertRaises(PrivateStateError):
                reserve(self.root)
        release_mentat_server(self.root)
        self.assertTrue(mentat_server_active(self.root))
        with self.assertRaises(PrivateStateError):
            assert_owner_setup(self.root, reservation, clock=lambda: 700)
        release_owner_setup(self.root, reservation)
        self.assertFalse(mentat_server_active(self.root))

    def test_normal_server_excludes_setup(self):
        reserve_mentat_server(self.root)
        with self.assertRaises(PrivateStateError):
            reserve_owner_setup(self.root)
        release_mentat_server(self.root)
        self.assertFalse(mentat_server_active(self.root))

    def test_changed_reservation_is_never_released_or_confirmed(self):
        reservation = reserve_owner_setup(self.root)
        changed = replace(reservation, nonce='different')
        write_json_atomic(connection_server_reservation_path(self.root), changed._record(), mode=0o600)
        with self.assertRaises(PrivateStateError):
            assert_owner_setup(self.root, reservation)
        release_owner_setup(self.root, reservation)
        self.assertTrue(mentat_server_active(self.root))
        release_owner_setup(self.root, changed)

    def test_concurrent_claims_have_only_one_winner(self):
        def claim():
            try:
                return reserve_owner_setup(self.root)
            except PrivateStateError:
                return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: claim(), range(2)))
        winners = [result for result in results if result is not None]
        self.assertEqual(len(winners), 1)
        release_owner_setup(self.root, winners[0])


if __name__ == '__main__':
    unittest.main()
