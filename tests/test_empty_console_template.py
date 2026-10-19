from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from threading import Barrier, Event, Lock, Thread, get_ident
import unittest
from unittest.mock import patch

from agent_run_history import save_run_summaries
import mentat_db
import private_console_unit as units
from private_state import history_path


class EmptyConsoleTemplateTests(unittest.TestCase):
    @contextmanager
    def isolated_cache(self):
        units._cached_empty_private_console_unit.cache_clear()
        try:
            yield
        finally:
            units._cached_empty_private_console_unit.cache_clear()

    def uncached_original_bytes(self):
        # The pre-cache construction protocol is the raw-byte compatibility
        # reference; do not substitute a logical/schema-only comparison.
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "mentat.sqlite3"
            units._initialize_database(database)
            self.assertEqual(units._validate_and_filter_database(database, ()), ())
            return units.PrivateConsoleUnit(units._empty_history(), database.read_bytes(), None, ())

    def snapshot(self, root):
        return {
            path.relative_to(root).as_posix(): (path.lstat().st_mtime_ns, stat.S_IMODE(path.lstat().st_mode), path.read_bytes() if path.is_file() else None)
            for path in root.rglob("*")
        }

    def test_repeated_reuse_preserves_original_raw_bytes_digest_and_immutability(self):
        with self.isolated_cache():
            original = self.uncached_original_bytes()
            with patch.object(units, "_initialize_database", wraps=units._initialize_database) as initialize, patch.object(
                units, "validate_private_console_unit", wraps=units.validate_private_console_unit
            ) as validate:
                first = units.empty_private_console_unit()
                second = units.empty_private_console_unit()
                third = units.empty_private_console_unit()
                self.assertIs(first, second)
                self.assertIs(second, third)
                self.assertEqual(initialize.call_count, 1)
                self.assertGreaterEqual(validate.call_count, 3)
                self.assertEqual(first, original)
                self.assertEqual(hashlib.sha256(first.database_raw).digest(), hashlib.sha256(original.database_raw).digest())
                self.assertEqual(units.private_console_unit_digest(first), units.private_console_unit_digest(original))
                with self.assertRaises(FrozenInstanceError):
                    first.history_raw = b"changed"
                self.assertIsInstance(first.database_raw, bytes)
                self.assertEqual(first.blobs, ())
                self.assertEqual(units._cached_empty_private_console_unit.cache_info().maxsize, 1)
                self.assertEqual(units._cached_empty_private_console_unit.cache_info().currsize, 1)

    def test_migration_history_schema_and_normalization_recipe_changes_miss_cache(self):
        with self.isolated_cache(), patch.object(units, "_initialize_database", wraps=units._initialize_database) as initialize:
            original = units.empty_private_console_unit()
            migrations = tuple((version, script + "\n-- template recipe test\n") for version, script in units.MIGRATIONS)
            with patch.object(units, "MIGRATIONS", migrations):
                changed = units.empty_private_console_unit()
                self.assertIsNot(changed, original)
                self.assertEqual(changed, original)
            with patch.object(units, "HISTORY_SCHEMA_VERSION", units.HISTORY_SCHEMA_VERSION + 1):
                changed = units.empty_private_console_unit()
                self.assertEqual(json.loads(changed.history_raw)["schema_version"], units.HISTORY_SCHEMA_VERSION)
                self.assertNotEqual(changed.history_raw, original.history_raw)
            with patch.object(units, "PROJECT_CONTEXT_ACCESS_DATABASE_SCHEMA_VERSION", units.PROJECT_CONTEXT_ACCESS_DATABASE_SCHEMA_VERSION + 1):
                changed = units.empty_private_console_unit()
                self.assertEqual(changed, original)
            with patch.object(units, "DATABASE_SCHEMA_VERSION", units.DATABASE_SCHEMA_VERSION - 1):
                changed = units.empty_private_console_unit()
                self.assertNotEqual(changed.database_raw, original.database_raw)
            self.assertEqual(initialize.call_count, 5)
            self.assertEqual(units._cached_empty_private_console_unit.cache_info().currsize, 1)

    def test_construction_and_filter_errors_are_not_cached(self):
        original_initialize = units._initialize_database
        original_filter = units._validate_and_filter_database
        for target in ("initialize", "filter"):
            with self.subTest(target=target), self.isolated_cache():
                calls = []

                def fail_then_construct(*args, **kwargs):
                    calls.append(1)
                    if len(calls) == 1:
                        raise units.PrivateConsoleUnitError("injected template fault")
                    return (original_initialize if target == "initialize" else original_filter)(*args, **kwargs)

                with patch.object(units, "_initialize_database" if target == "initialize" else "_validate_and_filter_database", side_effect=fail_then_construct):
                    with self.assertRaisesRegex(units.PrivateConsoleUnitError, "injected template fault"):
                        units.empty_private_console_unit()
                    self.assertEqual(units._cached_empty_private_console_unit.cache_info().currsize, 0)
                    first = units.empty_private_console_unit()
                    self.assertIs(first, units.empty_private_console_unit())
                    self.assertEqual(len(calls), 2)

    def test_cached_bytes_are_freshly_validated_and_do_not_hide_validation_faults(self):
        with self.isolated_cache(), patch.object(units, "_initialize_database", wraps=units._initialize_database) as initialize:
            template = units.empty_private_console_unit()
            with patch.object(units, "_inspect_filtered_database", side_effect=units.PrivateConsoleUnitError("current validation fault")) as inspect:
                for _ in range(2):
                    with self.assertRaisesRegex(units.PrivateConsoleUnitError, "current validation fault"):
                        units.empty_private_console_unit()
                self.assertEqual(inspect.call_count, 2)
            self.assertIs(units.empty_private_console_unit(), template)
            self.assertEqual(initialize.call_count, 1)

    def test_warm_template_cannot_hide_changed_transaction_normalizer_fault(self):
        with self.isolated_cache():
            units.empty_private_console_unit()
            with patch("owner_auth_google_transactions.discard_transactions", side_effect=units.PrivateConsoleUnitError("normalizer fault")) as normalize:
                for _ in range(2):
                    with self.assertRaisesRegex(units.PrivateConsoleUnitError, "normalizer fault"):
                        units.empty_private_console_unit()
                self.assertEqual(normalize.call_count, 2)

    def test_simultaneous_misses_construct_once_and_validate_both_callers_outside_lock(self):
        with self.isolated_cache():
            template = units.validate_private_console_unit(self.uncached_original_bytes())
            start = Barrier(3)
            validators = Barrier(2)
            entered = Event()
            second_arrived = Event()
            release = Event()
            counters = Lock()
            constructions, validated, returned, failures = [], [], [], []

            class ObservedLock:
                def __init__(self):
                    self.lock = Lock()
                    self.owner = None
                    self.attempts = 0

                def __enter__(self):
                    with counters:
                        self.attempts += 1
                        if self.attempts == 2:
                            second_arrived.set()
                    self.lock.acquire()
                    self.owner = get_ident()

                def __exit__(self, *_args):
                    self.owner = None
                    self.lock.release()

            lock = ObservedLock()

            @lru_cache(maxsize=1)
            def construct(_recipe):
                # Use validated immutable bytes to isolate synchronization from
                # disk speed. This has the production cache's same miss behavior.
                with counters:
                    constructions.append(get_ident())
                    if len(constructions) == 2:
                        second_arrived.set()
                entered.set()
                if not release.wait(5):
                    raise AssertionError("constructor release missing")
                return template

            def validate(value):
                self.assertNotEqual(lock.owner, get_ident())
                with counters:
                    validated.append(get_ident())
                validators.wait(5)
                return value

            def caller():
                try:
                    start.wait(5)
                    value = units.empty_private_console_unit()
                    with counters:
                        returned.append(value)
                except BaseException as error:
                    with counters:
                        failures.append(error)

            threads = [Thread(target=caller) for _ in range(2)]
            with patch.object(units, "_EMPTY_PRIVATE_TEMPLATE_LOCK", lock), patch.object(
                units, "_cached_empty_private_console_unit", construct
            ), patch.object(units, "validate_private_console_unit", side_effect=validate):
                try:
                    for thread in threads:
                        thread.start()
                    start.wait(5)
                    self.assertTrue(entered.wait(5))
                    self.assertTrue(second_arrived.wait(5))
                    release.set()
                    for thread in threads:
                        thread.join(10)
                finally:
                    # Always release only this fixture's workers before contract
                    # assertions, including partial-start and barrier failures.
                    release.set()
                    start.abort()
                    validators.abort()
                    for thread in threads:
                        if thread.ident is not None:
                            thread.join(10)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                self.assertEqual(failures, [])
                self.assertEqual(len(constructions), 1)
                self.assertEqual(len(set(validated)), 2)
                self.assertEqual(returned, [template, template])

    def test_warm_template_does_not_replace_nonempty_or_changed_store_capture(self):
        with self.isolated_cache(), TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            missing = units.capture_private_console_unit(root, harden_source=False)
            self.assertFalse(root.exists())
            connection = mentat_db.connect(root)
            connection.close()
            for status in ("running", "failed"):
                save_run_summaries(history_path(root), [{
                    "id": "run_fixture", "status": status,
                    "created_at": "2026-07-18T01:00:00+00:00",
                    "updated_at": "2026-07-18T01:01:00+00:00",
                }], data_root=root)
                before = self.snapshot(root)
                captured = units.capture_private_console_unit(root, harden_source=False)
                self.assertEqual(json.loads(captured.history_raw)["runs"][0]["status"], status)
                self.assertIsNot(captured, missing)
                self.assertEqual(before, self.snapshot(root))

    def test_changed_root_type_is_reinspected_and_refused_without_writes(self):
        with self.isolated_cache(), TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            units.capture_private_console_unit(root, harden_source=False)
            (root / "private").mkdir(parents=True, mode=0o700)
            (root / "private" / "console").write_bytes(b"unsafe fixture entry")
            before = self.snapshot(root)
            with self.assertRaises(OSError):
                units.capture_private_console_unit(root, harden_source=False)
            self.assertEqual(before, self.snapshot(root))

    @unittest.skipUnless(os.name == "posix", "owner-only POSIX permission contract")
    def test_warm_template_does_not_bypass_current_permissions_or_harden_readonly_root(self):
        with self.isolated_cache(), TemporaryDirectory() as temporary:
            root = Path(temporary) / "data"
            units.capture_private_console_unit(root, harden_source=False)
            connection = mentat_db.connect(root)
            connection.close()
            units.database_path(root).chmod(0o644)
            before = self.snapshot(root)
            with self.assertRaises(units.PrivateConsoleUnitError):
                units.capture_private_console_unit(root, harden_source=False)
            self.assertEqual(before, self.snapshot(root))


if __name__ == "__main__":
    unittest.main()
