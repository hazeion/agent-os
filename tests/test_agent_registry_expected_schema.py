from __future__ import annotations

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
import unittest
from unittest.mock import patch

import agent_registry


class ExpectedEmbeddedAgentSchemaTests(unittest.TestCase):
    def setUp(self):
        agent_registry._cached_expected_embedded_schema_signature.cache_clear()
        self.addCleanup(agent_registry._cached_expected_embedded_schema_signature.cache_clear)

    @staticmethod
    def small_recipe(extra=""):
        return ((1, f"CREATE TABLE mentat_agents (id TEXT PRIMARY KEY{extra});"),)

    def test_alternating_retained_and_current_versions_construct_once_each(self):
        normalizer = agent_registry._embedded_schema_signature
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe()), patch.object(
            agent_registry, "_embedded_schema_signature", wraps=normalizer
        ) as inspect:
            signatures = [
                agent_registry._expected_embedded_schema_signature(version)
                for version in (12, agent_registry.DATABASE_SCHEMA_VERSION) * 4
            ]
            self.assertEqual(inspect.call_count, 2)
            self.assertEqual(signatures, [signatures[0]] * 8)

    def test_changed_sql_recipe_rebuilds_same_version(self):
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe()):
            original = agent_registry._expected_embedded_schema_signature(12)
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe(", revision INTEGER")):
            changed = agent_registry._expected_embedded_schema_signature(12)
        self.assertNotEqual(original, changed)
        self.assertIn("revisionINTEGER", changed[0][3])

    def test_changed_normalizer_rebuilds_same_version(self):
        normalizer = agent_registry._embedded_schema_signature
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe()):
            original = agent_registry._expected_embedded_schema_signature(12)
            with patch.object(agent_registry, "_embedded_schema_signature", side_effect=lambda c: ()) as inspect:
                self.assertEqual(agent_registry._expected_embedded_schema_signature(12), ())
                self.assertEqual(inspect.call_count, 1)
            self.assertEqual(agent_registry._expected_embedded_schema_signature(12), original)
        self.assertIs(agent_registry._embedded_schema_signature, normalizer)

    def test_construction_errors_are_not_cached(self):
        connect = sqlite3.connect
        calls = []
        def sometimes_failing(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("injected construction failure")
            return connect(*args, **kwargs)
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe()), patch.object(
            agent_registry.sqlite3, "connect", side_effect=sometimes_failing
        ):
            with self.assertRaisesRegex(RuntimeError, "injected construction failure"):
                agent_registry._expected_embedded_schema_signature(12)
            self.assertEqual(agent_registry._cached_expected_embedded_schema_signature.cache_info().currsize, 0)
            self.assertTrue(agent_registry._expected_embedded_schema_signature(12))
            self.assertEqual(len(calls), 2)

    def test_recipe_change_during_construction_refuses_without_caching(self):
        first = self.small_recipe()
        changed = self.small_recipe(", revision INTEGER")
        normalizer = agent_registry._embedded_schema_signature
        def alter_recipe(connection):
            agent_registry.MIGRATIONS = changed
            return normalizer(connection)
        with patch.object(agent_registry, "MIGRATIONS", first), patch.object(
            agent_registry, "_embedded_schema_signature", side_effect=alter_recipe
        ):
            with self.assertRaisesRegex(agent_registry.AgentRegistryError, "agent_registry.schema_invalid"):
                agent_registry._expected_embedded_schema_signature(12)
            self.assertEqual(agent_registry._cached_expected_embedded_schema_signature.cache_info().currsize, 0)

    def test_expected_recipe_cache_is_bounded_to_eight_entries(self):
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe()):
            for version in range(1, 10):
                agent_registry._expected_embedded_schema_signature(version)
            info = agent_registry._cached_expected_embedded_schema_signature.cache_info()
            self.assertEqual(info.maxsize, 8)
            self.assertEqual(info.currsize, 8)

    def test_concurrent_miss_constructs_only_one_owned_template(self):
        entered, release, second_lookup = Event(), Event(), Event()
        outcomes, errors = [], []
        class ObservedLock:
            def __init__(self):
                self.lock, self.counter_lock = Lock(), Lock()
                self.attempts = 0
            def __enter__(self):
                with self.counter_lock:
                    self.attempts += 1
                    if self.attempts == 2:
                        second_lookup.set()
                self.lock.acquire()
            def __exit__(self, *_args):
                self.lock.release()
        normalizer = agent_registry._embedded_schema_signature
        def paused_normalizer(connection):
            entered.set()
            if not release.wait(2):
                raise AssertionError("test construction release missing")
            return normalizer(connection)
        def call():
            try:
                outcomes.append(agent_registry._expected_embedded_schema_signature(12))
            except BaseException as exc:
                errors.append(exc)
        threads = [Thread(target=call), Thread(target=call)]
        started = []
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe()), patch.object(
            agent_registry, "_embedded_schema_signature", side_effect=paused_normalizer
        ) as inspect, patch.object(agent_registry, "_EXPECTED_EMBEDDED_SCHEMA_LOCK", ObservedLock()):
            try:
                threads[0].start()
                started.append(threads[0])
                self.assertTrue(entered.wait(2))
                threads[1].start()
                started.append(threads[1])
                self.assertTrue(second_lookup.wait(2))
            finally:
                release.set()
                for thread in started:
                    thread.join(2)
                    if thread.is_alive():
                        thread.join(5)
                self.assertFalse(any(thread.is_alive() for thread in started))
            self.assertEqual(errors, [])
            self.assertEqual(len(outcomes), 2)
            self.assertEqual(outcomes[0], outcomes[1])
            self.assertEqual(inspect.call_count, 1)

    def test_warm_expected_signature_never_hides_actual_schema_or_receipt_drift(self):
        agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION)
        statements = (
            "ALTER TABLE mentat_agents ADD COLUMN unexpected TEXT",
            "UPDATE mentat_agent_registry_state SET source_sha256 = replace(hex(zeroblob(32)), '0', 'z') WHERE singleton = 1",
        )
        for statement in statements:
            with self.subTest(statement=statement), TemporaryDirectory() as temporary:
                connection = agent_registry.connect_registry(Path(temporary))
                try:
                    connection.execute(statement)
                    connection.commit()
                    with self.assertRaises(agent_registry.AgentRegistryError):
                        agent_registry.validate_registry_connection(connection)
                finally:
                    connection.close()


if __name__ == "__main__":
    unittest.main()
