#!/usr/bin/env python3
"""Create deterministic metadata for one exact Mentat release candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mentat.version import DISPLAY_VERSION, __version__


MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
SOURCE_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
RC_TAG_PATTERN = re.compile(
    rf"{re.escape(DISPLAY_VERSION)}-rc\.([1-9][0-9]*)"
)


def expected_artifacts() -> dict[str, str]:
    display = DISPLAY_VERSION.removeprefix("v")
    return {
        f"Mentat-{display}-macos-x86_64-signed.pkg": "macOS signed and notarized installer",
        f"Mentat-{display}-windows-x64.exe": "Windows signed installer",
        f"mentat_local-{__version__}-py3-none-any.whl": "Python wheel for pipx",
        f"mentat_local-{__version__}.tar.gz": "Python source distribution",
    }


def validate_release_tag(tag: str) -> str:
    if tag == DISPLAY_VERSION or RC_TAG_PATTERN.fullmatch(tag):
        return tag
    raise ValueError(
        f"release tag must be {DISPLAY_VERSION} or {DISPLAY_VERSION}-rc.N"
    )


def validate_rc_tag(tag: str) -> str:
    if RC_TAG_PATTERN.fullmatch(tag):
        return tag
    raise ValueError(f"release candidate tag must be {DISPLAY_VERSION}-rc.N")


def validate_source_sha(source_sha: str) -> str:
    if not SOURCE_SHA_PATTERN.fullmatch(source_sha):
        raise ValueError("source SHA must be exactly 40 lowercase hexadecimal characters")
    return source_sha


def _directory(path: Path, *, label: str, create: bool = False) -> Path:
    if create:
        path.mkdir(parents=True, exist_ok=True)
    resolved = path.resolve(strict=True)
    if not resolved.is_dir() or path.is_symlink():
        raise ValueError(f"{label} must be a real directory")
    return resolved


def _sha256(path: Path, expected: os.stat_result) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    opened = os.fstat(descriptor)
    if not stat.S_ISREG(opened.st_mode) or (
        getattr(expected, "st_ino", None), getattr(expected, "st_dev", None)
    ) != (getattr(opened, "st_ino", None), getattr(opened, "st_dev", None)) or (
        opened.st_size != expected.st_size
    ):
        os.close(descriptor)
        raise ValueError(f"artifact changed while it was being inspected: {path.name}")
    bytes_read = 0
    with os.fdopen(descriptor, "rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            bytes_read += len(chunk)
        finished = os.fstat(handle.fileno())
    if bytes_read != expected.st_size or finished.st_size != expected.st_size:
        raise ValueError(f"artifact changed while it was being hashed: {path.name}")
    return digest.hexdigest()


def _write_new_text(path: Path, content: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def inspect_artifacts(artifact_dir: Path) -> list[dict[str, object]]:
    root = _directory(artifact_dir, label="artifact directory")
    entries = list(root.iterdir())
    expected = expected_artifacts()
    if {entry.name for entry in entries} != set(expected):
        missing = sorted(set(expected) - {entry.name for entry in entries})
        extra = sorted({entry.name for entry in entries} - set(expected))
        raise ValueError(f"artifact inventory mismatch; missing={missing}; extra={extra}")

    artifacts: list[dict[str, object]] = []
    for entry in sorted(entries, key=lambda item: item.name):
        metadata = entry.lstat()
        if entry.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"artifact must be a regular file: {entry.name}")
        if metadata.st_size <= 0 or metadata.st_size > MAX_ARTIFACT_BYTES:
            raise ValueError(f"artifact size is outside the allowed range: {entry.name}")
        artifacts.append(
            {
                "name": entry.name,
                "role": expected[entry.name],
                "sha256": _sha256(entry, metadata),
                "size": metadata.st_size,
            }
        )
    return artifacts


def _release_notes(tag: str, source_sha: str, artifacts: list[dict[str, object]]) -> str:
    wheel = next(item["name"] for item in artifacts if str(item["name"]).endswith(".whl"))
    return f"""# Mentat {tag}

This release candidate comes from source commit `{source_sha}`.

## Install

- macOS: download the signed `.pkg`, verify it with `SHA256SUMS`, then open it.
- Windows: download the signed `.exe`, verify its SHA-256 value, then run it.
- pipx: `pipx install https://github.com/hazeion/agent-os/releases/download/{tag}/{wheel}`

Use the [release rehearsal](https://github.com/hazeion/agent-os/blob/{tag}/RELEASE_REHEARSAL.md) for artifact installation and recovery. The [README](https://github.com/hazeion/agent-os/blob/{tag}/README.md) covers source-development setup.

## Before upgrading

Native installs do not add `mentat` to PATH. Use `/Applications/Mentat.app/Contents/MacOS/Mentat backup` on macOS or `& "$env:LOCALAPPDATA\\Programs\\Mentat\\mentat.exe" backup` in Windows PowerShell. The reported `backup_name` is under the platform Mentat data folder's `backups` directory; copy it outside that folder before upgrading.

The macOS artifact is Intel. Apple Silicon acceptance requires a clean Rosetta rehearsal. Linux remains a pipx preview.

## Roll back

Stop Mentat, reinstall the last known-good release, preview with `COMMAND restore BACKUP_FILE`, then repeat it with `--confirm TOKEN_FROM_PREVIEW`.
"""


def build_bundle(
    artifact_dir: Path,
    output_dir: Path,
    release_tag: str,
    source_sha: str,
) -> dict[str, object]:
    tag = validate_release_tag(release_tag)
    sha = validate_source_sha(source_sha)
    artifact_root = _directory(artifact_dir, label="artifact directory")
    unresolved_output = output_dir.resolve(strict=False)
    if artifact_root == unresolved_output or artifact_root in unresolved_output.parents or unresolved_output in artifact_root.parents:
        raise ValueError("artifact and output directories must not overlap")
    output_root = _directory(output_dir, label="output directory", create=True)
    if any(output_root.iterdir()):
        raise ValueError("output directory must be empty")

    artifacts = inspect_artifacts(artifact_root)
    manifest: dict[str, object] = {
        "artifacts": artifacts,
        "display_version": DISPLAY_VERSION,
        "package_version": __version__,
        "release_tag": tag,
        "schema_version": 1,
        "source_sha": sha,
    }
    checksums = "".join(f'{item["sha256"]}  {item["name"]}\n' for item in artifacts)
    outputs = {
        "SHA256SUMS": checksums,
        "release-manifest.json": json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        "RELEASE_NOTES.md": _release_notes(tag, sha, artifacts),
    }
    for name, content in outputs.items():
        _write_new_text(output_root / name, content)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-tag", help="Validate one beta or RC tag.")
    validate.add_argument("release_tag")
    validate_rc = commands.add_parser("validate-rc-tag", help="Validate one numbered RC tag.")
    validate_rc.add_argument("release_tag")
    bundle = commands.add_parser("build", help="Create release checksums, manifest, and notes.")
    bundle.add_argument("--artifact-dir", type=Path, required=True)
    bundle.add_argument("--output-dir", type=Path, required=True)
    bundle.add_argument("--release-tag", required=True)
    bundle.add_argument("--source-sha", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-tag":
            validate_release_tag(args.release_tag)
        elif args.command == "validate-rc-tag":
            validate_rc_tag(args.release_tag)
        else:
            build_bundle(
                args.artifact_dir,
                args.output_dir,
                args.release_tag,
                args.source_sha,
            )
    except (OSError, ValueError) as error:
        print(f"Release rehearsal failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
