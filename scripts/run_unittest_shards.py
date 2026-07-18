#!/usr/bin/env python3
"""Run the complete unittest inventory in isolated concurrent shards."""

from __future__ import annotations

from fnmatch import fnmatchcase
import subprocess
import sys
from pathlib import Path
from unittest.loader import VALID_MODULE_NAME


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
SHARD_COUNT = 3


def discoverable_test_paths(directory: Path) -> tuple[Path, ...]:
    """Mirror unittest discovery's package traversal and default pattern."""

    selected: list[Path] = []
    for path in sorted(directory.iterdir()):
        if path.is_file():
            if fnmatchcase(path.name, "test*.py") and VALID_MODULE_NAME.match(path.name):
                selected.append(path)
        elif path.is_dir() and (path / "__init__.py").is_file():
            selected.extend(discoverable_test_paths(path))
    return tuple(selected)


def test_modules() -> tuple[str, ...]:
    """Return every unittest module in deterministic recursive order."""

    return tuple(
        ".".join(path.relative_to(ROOT).with_suffix("").parts)
        for path in discoverable_test_paths(TESTS)
    )


def partition_modules(
    modules: tuple[str, ...], shard_count: int = SHARD_COUNT
) -> tuple[tuple[str, ...], ...]:
    """Distribute modules exactly once across non-empty round-robin shards."""

    if shard_count < 1 or len(modules) < shard_count:
        raise ValueError("invalid unittest shard count")
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    for index, module in enumerate(modules):
        shards[index % shard_count].append(module)
    return tuple(tuple(shard) for shard in shards)


def main() -> int:
    modules = test_modules()
    if not modules:
        print("No unittest modules found.", file=sys.stderr)
        return 1

    processes: list[subprocess.Popen[bytes]] = []
    try:
        for shard in partition_modules(modules):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-m", "unittest", "-v", *shard],
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
