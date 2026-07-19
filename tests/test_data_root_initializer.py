from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path
import stat
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import data_layout
from data_layout import SEED_FILE_NAMES, initialize_data_root


def _initializer_worker(seed_root: str, data_root: str, home: str, ready, start, results) -> None:
    ready.put(True)
    start.wait(10)
    result = initialize_data_root(Path(seed_root), Path(data_root), home=Path(home))
    results.put((result.status, result.issues))


class DataRootInitializerTests(unittest.TestCase):
    def write_seeds(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        for name in SEED_FILE_NAMES:
            payload = {"theme": "midnight"} if name == "dashboard.json" else []
            (root / name).write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def test_clean_root_creates_private_layout_and_copies_exact_seeds(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)

            result = initialize_data_root(seeds, target, home=root / "home")

            self.assertEqual(result.status, "initialized")
            self.assertEqual({item.status for item in result.items}, {"initialized"})
            self.assertEqual(result.issues, ())
            self.assertEqual(
                set(path.name for path in target.iterdir()),
                set(SEED_FILE_NAMES)
                | {"private", "runtime", "backups", "cache", "logs", "config", ".mentat-initialization.lock"},
            )
            for name in SEED_FILE_NAMES:
                self.assertEqual((target / name).read_bytes(), (seeds / name).read_bytes())
            if os.name == "posix":
                for path in (target, *(target / name for name in ("private", "runtime", "backups", "cache", "logs", "config"))):
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
                for path in (*(target / name for name in SEED_FILE_NAMES), target / ".mentat-initialization.lock"):
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            summary = result.public_summary()
            self.assertEqual(set(summary), {"status", "items", "issues"})
            self.assertNotIn(str(root), json.dumps(summary))
            self.assertNotIn("midnight", json.dumps(summary))

    def test_existing_documents_are_never_overwritten_and_repeat_is_idempotent(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            target.mkdir()
            operator_tasks = b'[{"id":"operator-task"}]\n'
            (target / "tasks.json").write_bytes(operator_tasks)

            first = initialize_data_root(seeds, target, home=root / "home")
            before = {
                path.relative_to(target): (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
                for path in target.rglob("*")
            }
            second = initialize_data_root(seeds, target, home=root / "home")
            after = {
                path.relative_to(target): (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
                for path in target.rglob("*")
            }

            self.assertEqual(first.status, "initialized")
            tasks = next(item for item in first.items if item.name == "tasks.json")
            self.assertEqual(tasks.status, "existing")
            self.assertEqual((target / "tasks.json").read_bytes(), operator_tasks)
            self.assertEqual(second.status, "existing")
            self.assertEqual({item.status for item in second.items}, {"existing"})
            self.assertEqual(before, after)

    def test_legacy_conflict_and_unsafe_plans_copy_no_seed_destinations(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            legacy = root / "legacy"
            self.write_seeds(seeds)
            legacy.mkdir()
            (legacy / "tasks.json").write_text("[]\n", encoding="utf-8")

            migration_target = root / "migration-target"
            migration = initialize_data_root(
                seeds,
                migration_target,
                legacy_root=legacy,
                home=root / "home",
            )
            self.assertEqual(migration.status, "blocked")
            self.assertIn("migration_required", migration.issues)
            self.assertFalse(migration_target.exists())

            conflict_target = root / "conflict-target"
            conflict_target.mkdir()
            (conflict_target / "projects.json").write_text("[]\n", encoding="utf-8")
            conflict = initialize_data_root(
                seeds,
                conflict_target,
                legacy_root=legacy,
                home=root / "home",
            )
            self.assertEqual(conflict.status, "blocked")
            self.assertIn("conflict", conflict.issues)
            self.assertEqual(
                [path.name for path in conflict_target.glob("*.json")],
                ["projects.json"],
            )

            (seeds / "tasks.json").write_text("not json\n", encoding="utf-8")
            unsafe_target = root / "unsafe-target"
            unsafe = initialize_data_root(seeds, unsafe_target, home=root / "home")
            self.assertEqual(unsafe.status, "blocked")
            self.assertIn("unsafe", unsafe.issues)
            self.assertFalse(unsafe_target.exists())

    def test_seed_and_target_roots_may_not_overlap_in_either_direction(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "package" / "data"
            self.write_seeds(seeds)
            package_before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

            nested = initialize_data_root(seeds, seeds / "operator", home=root / "home")
            ancestor = initialize_data_root(seeds, seeds.parent, home=root / "home")

            self.assertEqual(nested.status, "blocked")
            self.assertEqual(ancestor.status, "blocked")
            self.assertIn("data_root_overlaps_seed_root", nested.issues)
            self.assertIn("data_root_overlaps_seed_root", ancestor.issues)
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                package_before,
            )

    def test_nonlexical_existing_alias_overlap_fails_closed_in_both_directions(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "LongPackageName"
            seeds = package / "data"
            alias_package = root / "MockAliasSpelling"
            alias_seeds = alias_package / "data"
            self.write_seeds(seeds)
            alias_seeds.mkdir(parents=True)
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            real_samefile = os.path.samefile
            identity_pairs = {
                frozenset(
                    os.fspath(data_layout._absolute_without_following(path))
                    for path in (package, alias_package)
                ),
                frozenset(
                    os.fspath(data_layout._absolute_without_following(path))
                    for path in (seeds, alias_seeds)
                ),
            }

            def alias_samefile(left, right):
                pair = frozenset(
                    (
                        os.fspath(Path(left).absolute()),
                        os.fspath(Path(right).absolute()),
                    )
                )
                if pair in identity_pairs:
                    return True
                return real_samefile(left, right)

            with patch.object(data_layout.os.path, "samefile", side_effect=alias_samefile):
                ancestor = initialize_data_root(
                    seeds,
                    alias_package,
                    home=root / "home",
                )
                descendant = initialize_data_root(
                    seeds,
                    alias_seeds / "operator",
                    home=root / "home",
                )

            self.assertEqual(ancestor.status, "blocked")
            self.assertEqual(descendant.status, "blocked")
            self.assertIn("data_root_overlaps_seed_root", ancestor.issues)
            self.assertIn("data_root_overlaps_seed_root", descendant.issues)
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                before,
            )

    @unittest.skipUnless(os.name == "nt", "native Windows short-name behavior")
    def test_windows_short_name_alias_overlap_fails_closed(self):
        import ctypes

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "Long Mentat Package Name"
            seeds = package / "data"
            self.write_seeds(seeds)
            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetShortPathNameW(
                os.fspath(package),
                buffer,
                len(buffer),
            )
            if not length or length >= len(buffer):
                self.skipTest("Windows short names are unavailable")
            alias_package = Path(buffer.value)
            if os.path.normcase(os.fspath(alias_package)) == os.path.normcase(
                os.fspath(package)
            ):
                self.skipTest("volume did not expose a distinct short name")
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

            ancestor = initialize_data_root(
                seeds,
                alias_package,
                home=root / "home",
            )
            descendant = initialize_data_root(
                seeds,
                alias_package / "data" / "operator",
                home=root / "home",
            )

            self.assertEqual(ancestor.status, "blocked")
            self.assertEqual(descendant.status, "blocked")
            self.assertIn("data_root_overlaps_seed_root", ancestor.issues)
            self.assertIn("data_root_overlaps_seed_root", descendant.issues)
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                before,
            )

    @unittest.skipUnless(sys.platform == "darwin", "native macOS case behavior")
    def test_macos_case_variant_seed_overlap_fails_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "package"
            seeds = package / "Seeds"
            case_variant = package / "seeds"
            self.write_seeds(seeds)
            try:
                same_entry = os.path.samefile(seeds, case_variant)
            except OSError:
                same_entry = False
            if not same_entry:
                self.skipTest("test volume is case-sensitive")
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

            exact = initialize_data_root(seeds, case_variant, home=root / "home")
            descendant = initialize_data_root(
                seeds,
                case_variant / "operator",
                home=root / "home",
            )
            ancestor = initialize_data_root(
                seeds,
                root / "PACKAGE",
                home=root / "home",
            )

            self.assertEqual(exact.status, "development_override")
            self.assertIn("data_root_overlaps_seed_root", descendant.issues)
            self.assertIn("data_root_overlaps_seed_root", ancestor.issues)
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                before,
            )

    def test_macos_case_fold_never_establishes_development_identity(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "Seeds"
            target = root / "seeds"
            self.write_seeds(seeds)

            with (
                patch.object(data_layout.sys, "platform", "darwin"),
                patch.object(data_layout.os.path, "samefile", return_value=False),
                patch.object(
                    data_layout,
                    "_native_path_comparison_key",
                    side_effect=lambda path: os.fspath(
                        data_layout._absolute_without_following(path)
                    ),
                ),
            ):
                result = initialize_data_root(seeds, target, home=root / "home")

            self.assertEqual(result.status, "blocked")
            self.assertIn("data_root_overlaps_seed_root", result.issues)
            self.assertFalse((target / ".mentat-initialization.lock").exists())

    def test_macos_unicode_alias_descendant_fails_closed_portably(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "S\u00e9eds"
            target = root / "Se\u0301eds" / "operator"
            self.write_seeds(seeds)
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

            with patch.object(data_layout.sys, "platform", "darwin"):
                result = initialize_data_root(seeds, target, home=root / "home")

            self.assertEqual(result.status, "blocked")
            self.assertIn("data_root_overlaps_seed_root", result.issues)
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                before,
            )

    @unittest.skipUnless(sys.platform == "darwin", "native macOS Unicode behavior")
    def test_macos_unicode_alias_overlap_fails_closed(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            package = root / "P\u00e1ckage"
            seeds = package / "S\u00e9eds"
            alias_package = root / "Pa\u0301ckage"
            alias_seeds = alias_package / "Se\u0301eds"
            self.write_seeds(seeds)
            try:
                same_entry = os.path.samefile(seeds, alias_seeds)
            except OSError:
                same_entry = False
            if not same_entry:
                self.skipTest("test volume does not alias Unicode normalization")
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))

            exact = initialize_data_root(seeds, alias_seeds, home=root / "home")
            descendant = initialize_data_root(
                seeds,
                alias_seeds / "operator",
                home=root / "home",
            )
            ancestor = initialize_data_root(
                seeds,
                alias_package,
                home=root / "home",
            )

            self.assertEqual(exact.status, "development_override")
            self.assertIn("data_root_overlaps_seed_root", descendant.issues)
            self.assertIn("data_root_overlaps_seed_root", ancestor.issues)
            self.assertEqual(
                sorted(str(path.relative_to(root)) for path in root.rglob("*")),
                before,
            )

    def test_development_override_is_a_noop(self):
        with TemporaryDirectory() as tmpdir:
            seeds = Path(tmpdir) / "data"
            self.write_seeds(seeds)
            before = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in seeds.iterdir()}

            result = initialize_data_root(seeds, seeds, home=Path(tmpdir) / "home")

            after = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in seeds.iterdir()}
            self.assertEqual(result.status, "development_override")
            self.assertEqual(before, after)
            self.assertFalse((seeds / ".mentat-initialization.lock").exists())

    def test_destination_race_fails_without_replacing_the_new_file(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            original = data_layout._promote_seed_copy
            raced_payload = b'[{"id":"raced-operator-task"}]\n'

            def race(temp_path: Path, destination: Path, **kwargs) -> None:
                if destination.name == "tasks.json" and not destination.exists():
                    destination.write_bytes(raced_payload)
                original(temp_path, destination, **kwargs)

            with patch.object(data_layout, "_promote_seed_copy", side_effect=race):
                result = initialize_data_root(seeds, target, home=root / "home")

            self.assertEqual(result.status, "blocked")
            self.assertIn("destination_exists:tasks.json", result.issues)
            self.assertEqual((target / "tasks.json").read_bytes(), raced_payload)

    def test_stale_temporary_copy_is_distinct_and_repeat_run_completes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            target.mkdir()
            stale = target / ".tasks.json.mentat-init-interrupted.tmp"
            stale.write_text("partial", encoding="utf-8")

            result = initialize_data_root(seeds, target, home=root / "home")

            self.assertEqual(result.status, "initialized")
            self.assertEqual((target / "tasks.json").read_bytes(), (seeds / "tasks.json").read_bytes())
            self.assertEqual(stale.read_text(encoding="utf-8"), "partial")

    def test_partial_valid_progress_is_preserved_and_retry_completes(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            original = data_layout._copy_seed_missing_only

            def fail_second(seed: Path, destination: Path, name: str, **kwargs):
                if name == SEED_FILE_NAMES[1]:
                    return f"seed_copy_failed:{name}"
                return original(seed, destination, name, **kwargs)

            with patch.object(data_layout, "_copy_seed_missing_only", side_effect=fail_second):
                failed = initialize_data_root(seeds, target, home=root / "home")

            first_name = SEED_FILE_NAMES[0]
            self.assertEqual(failed.status, "blocked")
            self.assertEqual((target / first_name).read_bytes(), (seeds / first_name).read_bytes())
            self.assertFalse((target / SEED_FILE_NAMES[1]).exists())

            recovered = initialize_data_root(seeds, target, home=root / "home")
            self.assertEqual(recovered.status, "initialized")
            self.assertEqual(
                sorted(path.name for path in target.glob("*.json")),
                sorted(SEED_FILE_NAMES),
            )

    def test_permission_verification_failure_stops_before_seed_copy(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)

            with patch.object(data_layout, "_secure_directory", return_value=False):
                result = initialize_data_root(seeds, target, home=root / "home")

            self.assertEqual(result.status, "blocked")
            self.assertIn("directory_permissions_unverified", result.issues)
            self.assertEqual(list(target.glob("*.json")) if target.exists() else [], [])

    def test_hard_linked_lock_is_rejected_without_mutating_outside_inode(self):
        if not hasattr(os, "link"):
            self.skipTest("hard links unavailable")
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            outside = root / "outside.txt"
            self.write_seeds(seeds)
            target.mkdir()
            outside.write_bytes(b"outside-content")
            outside.chmod(0o644)
            try:
                os.link(outside, target / data_layout.INITIALIZATION_LOCK_NAME)
            except OSError as exc:
                self.skipTest(f"hard-link creation unavailable: {exc}")
            before = (outside.read_bytes(), stat.S_IMODE(outside.stat().st_mode))

            result = initialize_data_root(seeds, target, home=root / "home")

            after = (outside.read_bytes(), stat.S_IMODE(outside.stat().st_mode))
            self.assertEqual(result.status, "blocked")
            self.assertIn("initialization_lock_failed", result.issues)
            self.assertEqual(after, before)
            self.assertEqual(list(target.glob("*.json")), [])

    def test_windows_lock_retry_outlives_the_crt_ten_attempt_limit(self):
        class FakeMsvcrt:
            LK_NBLCK = 1

            def __init__(self):
                self.calls = 0

            def locking(self, _descriptor, _mode, _length):
                self.calls += 1
                if self.calls <= 12:
                    raise OSError("busy")

        with TemporaryDirectory() as tmpdir:
            lock_path = Path(tmpdir) / "lock"
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            fake = FakeMsvcrt()
            try:
                with patch.dict(sys.modules, {"msvcrt": fake}):
                    data_layout._lock_windows_descriptor(descriptor, timeout=1.0, poll=0.0)
            finally:
                os.close(descriptor)

            self.assertEqual(fake.calls, 13)

    @unittest.skipUnless(os.name == "nt", "native Windows path pinning")
    def test_windows_root_guard_blocks_lock_and_temp_substitution(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            displaced = root / "displaced"
            seed_displaced = root / "seed-displaced"
            self.write_seeds(seeds)
            original = data_layout._windows_open_file_descriptor
            blocked_attempts: set[str] = set()

            def attempt_substitution(path: Path, **kwargs):
                name = Path(path).name
                if name == data_layout.INITIALIZATION_LOCK_NAME:
                    kind = "lock"
                    guarded_root = target
                    moved_root = displaced
                elif ".mentat-init-" in name:
                    kind = "temp"
                    guarded_root = target
                    moved_root = displaced
                elif Path(path).parent == seeds and name in data_layout.SEED_FILE_NAMES:
                    kind = "seed"
                    guarded_root = seeds
                    moved_root = seed_displaced
                else:
                    kind = None
                if kind is not None:
                    try:
                        guarded_root.rename(moved_root)
                    except OSError:
                        blocked_attempts.add(kind)
                    else:
                        moved_root.rename(guarded_root)
                        self.fail(f"Windows root guard allowed {kind} path substitution")
                return original(path, **kwargs)

            with patch.object(
                data_layout,
                "_windows_open_file_descriptor",
                side_effect=attempt_substitution,
            ):
                result = initialize_data_root(seeds, target, home=root / "home")

            self.assertEqual(result.status, "initialized")
            self.assertEqual(blocked_attempts, {"lock", "temp", "seed"})
            for name in data_layout.SEED_FILE_NAMES:
                self.assertEqual((target / name).read_bytes(), (seeds / name).read_bytes())

    @unittest.skipUnless(os.name == "nt", "native Windows access mask")
    def test_windows_directory_guards_do_not_require_listing_access(self):
        import ctypes

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            captured_access: list[int] = []
            kernel32 = data_layout._windows_kernel32()
            real_create_file = kernel32.CreateFileW

            def capture_create_file(
                path,
                desired_access,
                share_mode,
                security_attributes,
                disposition,
                flags,
                template,
            ):
                captured_access.append(desired_access)
                return real_create_file(
                    path,
                    desired_access,
                    share_mode,
                    security_attributes,
                    disposition,
                    flags,
                    template,
                )

            with (
                patch.object(data_layout, "_windows_kernel32", return_value=kernel32),
                patch.object(kernel32, "CreateFileW", side_effect=capture_create_file),
            ):
                handles = data_layout._windows_open_directory_chain(root)
            for handle in reversed(handles):
                data_layout._windows_close_handle(handle)

            self.assertTrue(captured_access)
            self.assertEqual(set(captured_access), {0x00000020 | 0x00000080})
            self.assertTrue(all(not access & 0x00000001 for access in captured_access))

    def test_preflight_is_repeated_after_the_initialization_lock(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            legacy = root / "legacy"
            self.write_seeds(seeds)
            legacy.mkdir()
            real_preflight = data_layout.preflight_data_root
            calls = 0

            def change_after_first(*args, **kwargs):
                nonlocal calls
                calls += 1
                result = real_preflight(*args, **kwargs)
                if calls == 1:
                    (legacy / "tasks.json").write_text("[]\n", encoding="utf-8")
                return result

            with patch.object(data_layout, "preflight_data_root", side_effect=change_after_first):
                result = initialize_data_root(
                    seeds,
                    target,
                    legacy_root=legacy,
                    home=root / "home",
                )

            self.assertGreaterEqual(calls, 2)
            self.assertEqual(result.status, "blocked")
            self.assertIn("migration_required", result.issues)
            self.assertEqual(list(target.glob("*.json")) if target.exists() else [], [])

    def test_two_processes_serialize_and_leave_one_complete_layout(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            seeds = root / "seeds"
            target = root / "target"
            self.write_seeds(seeds)
            context = multiprocessing.get_context("spawn")
            ready = context.Queue()
            results = context.Queue()
            start = context.Event()
            workers = [
                context.Process(
                    target=_initializer_worker,
                    args=(str(seeds), str(target), str(root / "home"), ready, start, results),
                )
                for _ in range(2)
            ]
            try:
                for worker in workers:
                    worker.start()
                for _ in workers:
                    self.assertTrue(ready.get(timeout=10))
                start.set()
                for worker in workers:
                    worker.join(15)
                    self.assertEqual(worker.exitcode, 0)

                worker_results = [results.get(timeout=5) for _ in workers]
                statuses = sorted(result[0] for result in worker_results)
                self.assertEqual(statuses, ["existing", "initialized"], worker_results)
                self.assertEqual(
                    sorted(path.name for path in target.glob("*.json")),
                    sorted(SEED_FILE_NAMES),
                )
            finally:
                original_failure = sys.exc_info()[0] is not None
                cleanup_errors: list[BaseException] = []

                def attempt(action):
                    try:
                        return True, action()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                        return False, None

                attempt(start.set)
                for worker in workers:
                    if worker.ident is None:
                        continue
                    alive_ok, alive = attempt(worker.is_alive)
                    if alive_ok and alive:
                        attempt(worker.terminate)
                    attempt(lambda worker=worker: worker.join(5))
                    alive_ok, alive = attempt(worker.is_alive)
                    if alive_ok and alive:
                        attempt(worker.kill)
                        attempt(lambda worker=worker: worker.join(5))
                        alive_ok, alive = attempt(worker.is_alive)
                    if alive_ok and not alive:
                        attempt(worker.close)
                    elif alive_ok:
                        cleanup_errors.append(RuntimeError("initializer test worker did not stop"))
                for queue in (ready, results):
                    attempt(queue.close)
                    attempt(queue.join_thread)
                if cleanup_errors and not original_failure:
                    raise RuntimeError("multiprocessing test cleanup failed") from cleanup_errors[0]


if __name__ == "__main__":
    unittest.main()
