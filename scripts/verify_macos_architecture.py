#!/usr/bin/env python3
"""Fail closed unless a macOS app bundle contains one expected architecture."""

from __future__ import annotations

import argparse
from pathlib import Path
import platform
import stat
import subprocess
import sys
from typing import Callable


SUPPORTED_ARCHITECTURES = {"arm64", "x86_64"}


class ArchitectureError(RuntimeError):
    """A safe architecture-verification failure."""


Inspector = Callable[[Path], set[str] | None]


def inspect_macho_architectures(path: Path) -> set[str] | None:
    try:
        file_result = subprocess.run(
            ["file", "-b", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
        if "Mach-O" not in file_result.stdout:
            return None
        lipo_result = subprocess.run(
            ["lipo", "-archs", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ArchitectureError("macOS architecture inspection failed") from exc
    architectures = set(lipo_result.stdout.split())
    if not architectures:
        raise ArchitectureError("Mach-O architecture inventory is empty")
    return architectures


def _contained_target(entry: Path, contents: Path) -> Path:
    try:
        target = entry.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ArchitectureError("macOS bundle contains an invalid link") from exc
    if target != contents and contents not in target.parents:
        raise ArchitectureError("macOS bundle link escapes Contents")
    return target


def verify_bundle(
    bundle: Path,
    expected_architecture: str,
    *,
    runner_architecture: str | None = None,
    inspector: Inspector = inspect_macho_architectures,
) -> int:
    if expected_architecture not in SUPPORTED_ARCHITECTURES:
        raise ArchitectureError("unsupported expected macOS architecture")
    observed_runner = (runner_architecture or platform.machine()).lower()
    if observed_runner != expected_architecture:
        raise ArchitectureError(
            f"runner architecture mismatch: expected {expected_architecture}, "
            f"observed {observed_runner or 'unknown'}"
        )

    if bundle.is_symlink():
        raise ArchitectureError("macOS bundle must not be a symlink")
    try:
        resolved_bundle = bundle.resolve(strict=True)
    except OSError as exc:
        raise ArchitectureError("macOS bundle does not exist") from exc
    if not resolved_bundle.is_dir():
        raise ArchitectureError("macOS bundle must be a directory")
    contents = resolved_bundle / "Contents"
    if not contents.is_dir() or contents.is_symlink():
        raise ArchitectureError("macOS bundle Contents directory is invalid")

    main_executable = contents / "MacOS" / "Mentat"
    if main_executable.is_symlink():
        raise ArchitectureError("Mentat executable must not be a symlink")
    try:
        main_metadata = main_executable.lstat()
    except OSError as exc:
        raise ArchitectureError("Mentat executable is missing") from exc
    if not stat.S_ISREG(main_metadata.st_mode):
        raise ArchitectureError("Mentat executable must be a regular file")

    candidates: set[Path] = set()
    for entry in contents.rglob("*"):
        try:
            metadata = entry.lstat()
        except OSError as exc:
            raise ArchitectureError("macOS bundle inventory changed") from exc
        if stat.S_ISLNK(metadata.st_mode):
            target = _contained_target(entry, contents)
            if target.is_file():
                candidates.add(target)
        elif stat.S_ISREG(metadata.st_mode):
            candidates.add(entry)

    matched = 0
    main_matched = False
    for candidate in sorted(candidates):
        architectures = inspector(candidate)
        if architectures is None:
            continue
        if architectures != {expected_architecture}:
            relative = candidate.relative_to(contents)
            observed = ",".join(sorted(architectures))
            raise ArchitectureError(
                f"Mach-O architecture mismatch for {relative}: "
                f"expected {expected_architecture}, observed {observed}"
            )
        matched += 1
        if candidate == main_executable:
            main_matched = True
    if not main_matched:
        raise ArchitectureError("Mentat executable is not a Mach-O file")
    if matched == 0:
        raise ArchitectureError("macOS bundle contains no Mach-O files")
    return matched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--expected",
        choices=sorted(SUPPORTED_ARCHITECTURES),
        required=True,
    )
    args = parser.parse_args(argv)
    try:
        count = verify_bundle(args.bundle, args.expected)
    except ArchitectureError as exc:
        print(f"macOS architecture verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"Verified {count} {args.expected} Mach-O files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
