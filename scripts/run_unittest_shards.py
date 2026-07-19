#!/usr/bin/env python3
"""Run the complete unittest inventory in isolated concurrent shards."""

from __future__ import annotations

from fnmatch import fnmatchcase
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.loader import VALID_MODULE_NAME


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SHARD_COUNT = 12
MAX_CONCURRENT_SHARDS = 4
SPLIT_TEST_WEIGHT = 12
SPLITTABLE_MODULES = frozenset(
    {
        "tests.test_data_backup_restore",
        "tests.test_private_console_state",
    }
)
MODULE_UNIT_PREFIX = "module:"
TEST_UNIT_PREFIX = "test:"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _SingleModuleLoader(unittest.TestLoader):
    def __init__(self, filename: str):
        super().__init__()
        self.filename: str | None = filename

    def _match_path(self, path: str, full_path: str, pattern: str) -> bool:
        return (self.filename is None or path == self.filename) and super()._match_path(
            path, full_path, pattern
        )

    def loadTestsFromModule(
        self, module: object, *, pattern: str | None = None
    ) -> unittest.TestSuite:
        filename = self.filename
        self.filename = None
        try:
            return super().loadTestsFromModule(module, pattern=pattern)
        finally:
            self.filename = filename


def discoverable_test_paths(directory: Path) -> tuple[Path, ...]:
    """Select default-pattern modules and reject unsupported test packages."""

    selected: list[Path] = []
    for path in sorted(directory.iterdir()):
        if path.is_file():
            if fnmatchcase(path.name, "test*.py") and VALID_MODULE_NAME.match(path.name):
                selected.append(path)
        elif path.is_dir() and (path / "__init__.py").is_file():
            raise RuntimeError("package-style unittest discovery is unsupported")
    return tuple(selected)


def test_modules() -> tuple[str, ...]:
    """Return every top-level unittest module in deterministic order."""

    return tuple(
        ".".join(path.relative_to(ROOT).with_suffix("").parts)
        for path in discoverable_test_paths(TESTS)
    )


def _discover_module(module: str) -> unittest.TestSuite:
    prefix = "tests."
    name = module.removeprefix(prefix)
    if not module.startswith(prefix) or "." in name or not VALID_MODULE_NAME.match(f"{name}.py"):
        raise RuntimeError("invalid unittest module")
    loader = _SingleModuleLoader(f"{name}.py")
    suite = loader.discover(str(TESTS))
    if loader.errors:
        raise RuntimeError(f"unittest discovery failed for {module}")
    return suite


def _tests_in(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _tests_in(item)
        else:
            yield item


def _canonical_test_id(test: unittest.TestCase) -> str:
    identifier = test.id()
    return identifier if identifier.startswith("tests.") else f"tests.{identifier}"


def _split_tests(module: str, suite: unittest.TestSuite) -> tuple[unittest.TestCase, ...]:
    """Return explicitly fixture-free tests that may run in separate processes."""

    loaded_name = module.removeprefix("tests.")
    loaded = sys.modules.get(loaded_name)
    if loaded is None or any(
        getattr(loaded, hook, None) is not None
        for hook in ("load_tests", "setUpModule", "tearDownModule")
    ):
        raise RuntimeError(f"split unittest module has fixtures: {module}")
    tests = tuple(_tests_in(suite))
    identifiers = tuple(_canonical_test_id(test) for test in tests)
    if (
        not tests
        or len(identifiers) != len(set(identifiers))
        or any(not identifier.startswith(f"{module}.") for identifier in identifiers)
    ):
        raise RuntimeError(f"split unittest inventory is invalid: {module}")
    for test in tests:
        if getattr(test.__class__, "_class_cleanups", ()):
            raise RuntimeError(f"split unittest class has cleanups: {module}")
        for base in test.__class__.__mro__:
            if base is unittest.TestCase:
                break
            if any(
                hook in base.__dict__
                for hook in (
                    "setUpClass",
                    "tearDownClass",
                    "addClassCleanup",
                    "enterClassContext",
                    "doClassCleanups",
                )
            ):
                raise RuntimeError(f"split unittest class has fixtures: {module}")
    return tests


def _discover_split_tests(module: str) -> tuple[unittest.TestCase, ...]:
    module_cleanups = getattr(unittest.case, "_module_cleanups", None)
    if not isinstance(module_cleanups, list):
        raise RuntimeError("unittest module cleanup state is unavailable")
    before = list(module_cleanups)
    try:
        suite = _discover_module(module)
    except BaseException:
        module_cleanups[:] = before
        raise
    if module_cleanups != before:
        module_cleanups[:] = before
        raise RuntimeError(f"split unittest module has cleanups: {module}")
    return _split_tests(module, suite)


def weighted_units(modules: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    """Measure fixture-preserving modules and allowlisted independent tests."""

    weighted: list[tuple[str, int]] = []
    for module in modules:
        if module in SPLITTABLE_MODULES:
            weighted.extend(
                (f"{TEST_UNIT_PREFIX}{_canonical_test_id(test)}", SPLIT_TEST_WEIGHT)
                for test in _discover_split_tests(module)
            )
        else:
            suite = _discover_module(module)
            weighted.append(
                (f"{MODULE_UNIT_PREFIX}{module}", suite.countTestCases())
            )
    return tuple(weighted)


def partition_units(
    weighted: tuple[tuple[str, int], ...], shard_count: int = SHARD_COUNT
) -> tuple[tuple[str, ...], ...]:
    """Greedily balance fixture-safe units across deterministic shards."""

    units = tuple(unit for unit, _count in weighted)
    if (
        shard_count < 1
        or len(weighted) < shard_count
        or len(units) != len(set(units))
        or any(not isinstance(count, int) or count < 0 for _unit, count in weighted)
    ):
        raise ValueError("invalid unittest shard count")
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    totals = [0] * shard_count
    order = {unit: index for index, unit in enumerate(units)}
    for unit, count in sorted(weighted, key=lambda item: (-item[1], order[item[0]])):
        index = min(range(shard_count), key=lambda candidate: (totals[candidate], candidate))
        shards[index].append(unit)
        totals[index] += max(count, 1)
    return tuple(tuple(sorted(shard, key=order.__getitem__)) for shard in shards)


def _split_module_for_id(identifier: str) -> str:
    matches = tuple(
        module for module in SPLITTABLE_MODULES if identifier.startswith(f"{module}.")
    )
    if len(matches) != 1:
        raise RuntimeError("invalid unittest shard inventory")
    return matches[0]


def _build_shard_suite(units: tuple[str, ...]) -> unittest.TestSuite:
    inventory = set(test_modules())
    if not units or len(units) != len(set(units)):
        raise RuntimeError("invalid unittest shard inventory")
    split_inventories: dict[str, dict[str, unittest.TestCase]] = {}
    suite = unittest.TestSuite()
    for unit in units:
        if unit.startswith(MODULE_UNIT_PREFIX):
            module = unit.removeprefix(MODULE_UNIT_PREFIX)
            if module not in inventory or module in SPLITTABLE_MODULES:
                raise RuntimeError("invalid unittest shard inventory")
            suite.addTest(_discover_module(module))
            continue
        if not unit.startswith(TEST_UNIT_PREFIX):
            raise RuntimeError("invalid unittest shard inventory")
        identifier = unit.removeprefix(TEST_UNIT_PREFIX)
        module = _split_module_for_id(identifier)
        if module not in inventory:
            raise RuntimeError("invalid unittest shard inventory")
        if module not in split_inventories:
            split_inventories[module] = {
                _canonical_test_id(test): test
                for test in _discover_split_tests(module)
            }
        test = split_inventories[module].get(identifier)
        if test is None:
            raise RuntimeError("invalid unittest shard inventory")
        suite.addTest(test)
    return suite


def run_shard(units: tuple[str, ...]) -> int:
    suite = _build_shard_suite(units)
    return 0 if unittest.TextTestRunner(verbosity=0, buffer=True).run(suite).wasSuccessful() else 1


def _spawn_shard(units: tuple[str, ...]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--run-shard", *units],
        cwd=ROOT,
    )


def run_shards(
    shards: tuple[tuple[str, ...], ...],
    max_concurrent: int = MAX_CONCURRENT_SHARDS,
) -> int:
    """Run every shard while bounding process contention on smaller CI hosts."""

    if not shards or max_concurrent < 1 or any(not shard for shard in shards):
        raise ValueError("invalid unittest shard schedule")
    pending = iter(shards)
    active: list[subprocess.Popen[bytes]] = []
    results: list[int] = []

    def fill_available_slots() -> None:
        while len(active) < max_concurrent:
            try:
                shard = next(pending)
            except StopIteration:
                return
            active.append(_spawn_shard(shard))

    try:
        fill_available_slots()
        while active:
            finished: list[subprocess.Popen[bytes]] = []
            for process in active:
                result = process.poll()
                if result is not None:
                    results.append(result)
                    finished.append(process)
            if not finished:
                time.sleep(0.05)
                continue
            for process in finished:
                active.remove(process)
            fill_available_slots()
    except BaseException:
        for process in active:
            if process.poll() is None:
                process.terminate()
        for process in active:
            process.wait()
        raise
    return 1 if any(results) else 0


def main(argv: tuple[str, ...] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        if arguments[0] != "--run-shard":
            raise RuntimeError("invalid unittest shard operation")
        return run_shard(arguments[1:])

    modules = test_modules()
    return run_shards(partition_units(weighted_units(modules)))


if __name__ == "__main__":
    raise SystemExit(main())
