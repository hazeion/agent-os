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

    def test_current_signature_reuses_one_bounded_template(self):
        normalizer = agent_registry._embedded_schema_signature
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe()), patch.object(
            agent_registry, "_embedded_schema_signature", wraps=normalizer
        ) as inspect:
            signatures = [agent_registry._expected_embedded_schema_signature(
                agent_registry.DATABASE_SCHEMA_VERSION
            ) for _ in range(8)]
            self.assertEqual(inspect.call_count, 1)
            self.assertEqual(signatures, [signatures[0]] * 8)
            info = agent_registry._cached_expected_embedded_schema_signature.cache_info()
            self.assertEqual((info.maxsize, info.currsize), (1, 1))

    def test_old_future_and_non_integer_versions_refuse_before_construction(self):
        with patch.object(agent_registry.sqlite3, "connect", side_effect=AssertionError("unexpected construction")):
            for version in (0, 33, agent_registry.DATABASE_SCHEMA_VERSION - 1,
                            agent_registry.DATABASE_SCHEMA_VERSION + 1, True, "46"):
                with self.subTest(version=version), self.assertRaisesRegex(
                    agent_registry.AgentRegistryError, "agent_registry.unsupported"
                ):
                    agent_registry._expected_embedded_schema_signature(version)
        self.assertEqual(agent_registry._cached_expected_embedded_schema_signature.cache_info().currsize, 0)

    def test_changed_sql_recipe_rebuilds_same_version(self):
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe()):
            original = agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION)
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe(", revision INTEGER")):
            changed = agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION)
        self.assertNotEqual(original, changed)
        self.assertIn("revisionINTEGER", changed[0][3])

    def test_changed_normalizer_rebuilds_same_version(self):
        normalizer = agent_registry._embedded_schema_signature
        with patch.object(agent_registry, "MIGRATIONS", self.small_recipe()):
            original = agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION)
            with patch.object(agent_registry, "_embedded_schema_signature", side_effect=lambda c: ()) as inspect:
                self.assertEqual(agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION), ())
                self.assertEqual(inspect.call_count, 1)
            self.assertEqual(agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION), original)
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
                agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION)
            self.assertEqual(agent_registry._cached_expected_embedded_schema_signature.cache_info().currsize, 0)
            self.assertTrue(agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION))
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
                agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION)
            self.assertEqual(agent_registry._cached_expected_embedded_schema_signature.cache_info().currsize, 0)

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
                outcomes.append(agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION))
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

    def test_all_repository_boundaries_refuse_noncurrent_journals_without_writes(self):
        import conversation_repository
        import mentat_db
        import project_repository
        import run_repository
        import task_repository
        import vercel_connections

        boundaries = (
            (agent_registry.validate_registry_connection, agent_registry.AgentRegistryError),
            (conversation_repository.validate_repository_connection, conversation_repository.ConversationRepositoryError),
            (project_repository.ProjectRepository, project_repository.ProjectRepositoryError),
            (run_repository.RunRepository, run_repository.RunRepositoryError),
            (task_repository.TaskRepository, task_repository.TaskRepositoryError),
            (vercel_connections.validate_provider_connections, vercel_connections.VercelConnectionError),
        )
        mutations = (
            "DELETE FROM schema_migrations WHERE version = 46",
            "INSERT INTO schema_migrations VALUES (47, 0)",
            "DELETE FROM schema_migrations WHERE version = 1",
        )
        for validate, error in boundaries:
            for mutation in (None, *mutations):
                with self.subTest(boundary=validate.__qualname__, mutation=mutation):
                    connection = sqlite3.connect(":memory:", isolation_level=None)
                    connection.row_factory = sqlite3.Row
                    try:
                        mentat_db.migrate(connection)
                        if mutation is not None:
                            connection.execute(mutation)
                        before = connection.serialize()
                        changes = connection.total_changes
                        connection.execute("PRAGMA query_only = ON")
                        if mutation is None:
                            validate(connection)
                        else:
                            with self.assertRaises(error):
                                validate(connection)
                        self.assertEqual(connection.total_changes, changes)
                        self.assertEqual(connection.serialize(), before)
                    finally:
                        connection.close()

    @staticmethod
    def file_backed_signature(version, migrations, normalizer):
        # Exact former construction protocol, retained only as an independent
        # equivalence oracle. It reads no operator database or configuration.
        with TemporaryDirectory() as temporary:
            connection = sqlite3.connect(Path(temporary) / "expected.sqlite3")
            try:
                connection.execute(
                    "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)"
                )
                for item_version, script in migrations:
                    if item_version > version:
                        break
                    connection.executescript(script)
                    connection.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 0)",
                        (item_version,),
                    )
                return normalizer(connection)
            finally:
                connection.close()

    def test_memory_matches_file_signature_for_current_bootstrap(self):
        expected = self.file_backed_signature(
            agent_registry.DATABASE_SCHEMA_VERSION, agent_registry.MIGRATIONS,
            agent_registry._embedded_schema_signature,
        )
        self.assertEqual(agent_registry._expected_embedded_schema_signature(
            agent_registry.DATABASE_SCHEMA_VERSION
        ), expected)

    def test_memory_matches_changed_recipe_and_normalizer(self):
        migrations = tuple(agent_registry.MIGRATIONS)
        changed = tuple(
            (version, script + "\nALTER TABLE mentat_agents ADD COLUMN recipe_revision INTEGER;"
             if version == agent_registry.DATABASE_SCHEMA_VERSION else script)
            for version, script in migrations
        )
        original = agent_registry._embedded_schema_signature
        def revised(connection):
            return tuple((kind, name, table, sql.lower()) for kind, name, table, sql in original(connection))
        for recipe in (migrations, changed):
            for normalizer in (original, revised):
                with self.subTest(changed=recipe == changed, revised=normalizer is revised), \
                     patch.object(agent_registry, "MIGRATIONS", recipe), \
                     patch.object(agent_registry, "_embedded_schema_signature", normalizer):
                    expected = self.file_backed_signature(agent_registry.DATABASE_SCHEMA_VERSION, recipe, normalizer)
                    self.assertEqual(agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION), expected)

    def test_cold_expected_signature_uses_only_memory_and_closes_connection(self):
        actual_connect, connections = sqlite3.connect, []
        def capture(*args, **kwargs):
            connection = actual_connect(*args, **kwargs)
            connections.append(connection)
            return connection
        with patch.object(agent_registry.sqlite3, "connect", side_effect=capture) as connect:
            self.assertTrue(agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION))
            connect.assert_called_once_with(":memory:")
        self.assertEqual(len(connections), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")

    def test_memory_constructor_failure_closes_connection_and_is_uncached(self):
        actual_connect, connections = sqlite3.connect, []
        def capture(*args, **kwargs):
            connection = actual_connect(*args, **kwargs)
            connections.append(connection)
            return connection
        with patch.object(agent_registry.sqlite3, "connect", side_effect=capture), \
             patch.object(agent_registry, "_embedded_schema_signature", side_effect=RuntimeError("injected normalizer failure")):
            with self.assertRaisesRegex(RuntimeError, "injected normalizer failure"):
                agent_registry._expected_embedded_schema_signature(agent_registry.DATABASE_SCHEMA_VERSION)
        self.assertEqual(agent_registry._cached_expected_embedded_schema_signature.cache_info().currsize, 0)
        self.assertEqual(len(connections), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")


if __name__ == "__main__":
    unittest.main()
