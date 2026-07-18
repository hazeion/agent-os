#!/usr/bin/env python3
"""Run the complete unittest inventory in isolated concurrent shards."""

from __future__ import annotations

from fnmatch import fnmatchcase
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.loader import VALID_MODULE_NAME


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SHARD_COUNT = 6

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


def weighted_modules(modules: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    """Measure discovery suites without splitting their unittest fixtures."""

    weighted: list[tuple[str, int]] = []
    for module in modules:
        weighted.append((module, _discover_module(module).countTestCases()))
    return tuple(weighted)


def partition_modules(
    weighted: tuple[tuple[str, int], ...], shard_count: int = SHARD_COUNT
) -> tuple[tuple[str, ...], ...]:
    """Greedily balance whole modules across non-empty deterministic shards."""

    modules = tuple(module for module, _count in weighted)
    if (
        shard_count < 1
        or len(weighted) < shard_count
        or len(modules) != len(set(modules))
        or any(not isinstance(count, int) or count < 0 for _module, count in weighted)
    ):
        raise ValueError("invalid unittest shard count")
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    totals = [0] * shard_count
    order = {module: index for index, module in enumerate(modules)}
    for module, count in sorted(weighted, key=lambda item: (-item[1], order[item[0]])):
        index = min(range(shard_count), key=lambda candidate: (totals[candidate], candidate))
        shards[index].append(module)
        totals[index] += max(count, 1)
    return tuple(tuple(sorted(shard, key=order.__getitem__)) for shard in shards)


def run_shard(modules: tuple[str, ...]) -> int:
    inventory = test_modules()
    selected = set(modules)
    if (
        not modules
        or len(modules) != len(selected)
        or tuple(module for module in inventory if module in selected) != modules
    ):
        raise RuntimeError("invalid unittest shard inventory")
    suite = unittest.TestSuite(_discover_module(module) for module in modules)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


def main(argv: tuple[str, ...] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments:
        if arguments[0] != "--run-shard":
            raise RuntimeError("invalid unittest shard operation")
        return run_shard(arguments[1:])

    processes: list[subprocess.Popen[bytes]] = []
    try:
        modules = test_modules()
        for shard in partition_modules(weighted_modules(modules)):
            processes.append(
                subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), "--run-shard", *shard],
                    cwd=ROOT,
                )
            )
        results = [process.wait() for process in processes]
    except BaseException:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            process.wait()
        raise
    return 1 if any(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
