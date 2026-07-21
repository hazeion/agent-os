#!/usr/bin/env python3
"""Verify and prepare promotion of exact tested RC assets to public beta."""

from __future__ import annotations

import argparse
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
from scripts.release_rehearsal import (
    MAX_ARTIFACT_BYTES,
    _sha256,
    _write_new_text,
    expected_artifacts,
    validate_rc_tag,
    validate_source_sha,
)


MAX_METADATA_BYTES = 1024 * 1024
CONFIRMATION = "PROMOTE_V0.1.0_BETA_1"
COHORT_URL_PATTERN = re.compile(
    r"https://github\.com/hazeion/agent-os/issues/([1-9][0-9]*)"
)
METADATA_NAMES = {"SHA256SUMS", "release-manifest.json"}


def expected_public_assets() -> set[str]:
    return set(expected_artifacts()) | METADATA_NAMES


def validate_cohort_summary_url(url: str) -> str:
    if not COHORT_URL_PATTERN.fullmatch(url):
        raise ValueError("cohort summary must be an issue URL in hazeion/agent-os")
    return url


def _read_regular(path: Path, *, maximum: int, label: str) -> bytes:
    metadata = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{label} must be a regular file")
    if metadata.st_size <= 0 or metadata.st_size > maximum:
        raise ValueError(f"{label} size is outside the allowed range")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or (opened.st_dev, opened.st_ino, opened.st_size)
        != (metadata.st_dev, metadata.st_ino, metadata.st_size)
    ):
        os.close(descriptor)
        raise ValueError(f"{label} changed while it was being inspected")
    with os.fdopen(descriptor, "rb") as handle:
        payload = handle.read(maximum + 1)
        finished = os.fstat(handle.fileno())
    if len(payload) != metadata.st_size or finished.st_size != metadata.st_size:
        raise ValueError(f"{label} changed while it was being read")
    return payload


def _load_json(path: Path, *, label: str) -> dict:
    raw = _read_regular(path, maximum=MAX_METADATA_BYTES, label=label)
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if type(payload) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _validate_release_snapshot(
    path: Path, bundle_dir: Path, release_tag: str, *, prerelease: bool
) -> None:
    payload = _load_json(path, label="candidate release snapshot")
    if set(payload) != {
        "assets", "draft", "html_url", "immutable", "prerelease", "tag_name"
    }:
        raise ValueError("candidate release snapshot has an unexpected shape")
    expected_url = f"https://github.com/hazeion/agent-os/releases/tag/{release_tag}"
    if (
        payload.get("draft") is not False
        or payload.get("prerelease") is not prerelease
        or payload.get("immutable") is not True
        or payload.get("tag_name") != release_tag
        or payload.get("html_url") != expected_url
    ):
        raise ValueError("release is not the exact immutable published release")
    assets = payload.get("assets")
    if type(assets) is not list or len(assets) != len(expected_public_assets()):
        raise ValueError("release asset digest inventory is invalid")
    by_name: dict[str, dict] = {}
    for asset in assets:
        if type(asset) is not dict or set(asset) != {"digest", "name", "size"}:
            raise ValueError("release asset digest entry is invalid")
        name = asset.get("name")
        size = asset.get("size")
        digest = asset.get("digest")
        if (
            name not in expected_public_assets()
            or name in by_name
            or type(size) is not int
            or size <= 0
            or size > MAX_ARTIFACT_BYTES
            or type(digest) is not str
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
        ):
            raise ValueError("release asset digest entry is invalid")
        by_name[name] = asset
    if set(by_name) != expected_public_assets():
        raise ValueError("release asset digest inventory is invalid")
    root = bundle_dir.resolve(strict=True)
    for name, asset in by_name.items():
        path = root / name
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"release asset must be a regular file: {name}")
        if (
            metadata.st_size != asset["size"]
            or _sha256(path, metadata) != asset["digest"].removeprefix("sha256:")
        ):
            raise ValueError(f"release asset does not match GitHub digest: {name}")


def verify_published_release(
    bundle_dir: Path, release_snapshot: Path, release_tag: str, *, prerelease: bool
) -> None:
    _validate_release_snapshot(
        release_snapshot, bundle_dir, release_tag, prerelease=prerelease
    )


def _validate_cohort_snapshot(
    path: Path, cohort_url: str, candidate_tag: str, source_sha: str
) -> None:
    payload = _load_json(path, label="cohort summary snapshot")
    if set(payload) != {"body", "state", "url"}:
        raise ValueError("cohort summary snapshot has an unexpected shape")
    body = payload.get("body")
    if payload.get("state") != "CLOSED" or payload.get("url") != cohort_url:
        raise ValueError("cohort summary is not the exact closed public issue")
    if type(body) is not str or len(body.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError("cohort summary body is invalid")
    headings = (
        "### Exact tested RC tag and source commit",
        "### Cohort window and coverage",
        "### Installation and first-workflow results",
        "### Migration, backup, and recovery results",
        "### Remote matrix v1 results",
        "### Issues and repeated confusion",
        "### Exit attestation",
    )
    sections: dict[str, list[str]] = {}
    current: str | None = None
    seen_order: list[str] = []
    for line in body.splitlines():
        if line.startswith("### "):
            current = line
            if current in sections:
                raise ValueError("cohort summary contains a duplicate section")
            sections[current] = []
            seen_order.append(current)
        elif current is not None:
            sections[current].append(line)
    if seen_order != list(headings):
        raise ValueError("cohort summary sections are missing, extra, or out of order")
    for heading in headings[:-1]:
        content = "\n".join(sections[heading]).strip()
        if not content or content == "_No response_":
            raise ValueError("cohort summary contains an empty required section")
    candidate = "\n".join(sections[headings[0]]).strip()
    if candidate != f"{candidate_tag} at {source_sha}":
        raise ValueError("cohort summary candidate evidence does not match")
    checked = {
        "- [x] At least 10 external testers used Mentat for roughly two weeks and every Milestone 7 exit criterion passed.",
        "- [x] No unresolved P0 or P1 issue remains.",
        "- [x] This issue contains only aggregate, redacted, public-safe evidence.",
    }
    exit_lines = {line.strip() for line in sections[headings[-1]] if line.strip()}
    if exit_lines != checked:
        raise ValueError("cohort summary is missing required checked exit evidence")


def inspect_candidate_assets(bundle_dir: Path, candidate_tag: str, source_sha: str) -> dict:
    root = bundle_dir.resolve(strict=True)
    if bundle_dir.is_symlink() or not root.is_dir():
        raise ValueError("candidate asset directory must be a real directory")
    entries = list(root.iterdir())
    names = {entry.name for entry in entries}
    expected_names = expected_public_assets()
    if names != expected_names:
        raise ValueError(
            "candidate asset inventory mismatch; "
            f"missing={sorted(expected_names - names)}; extra={sorted(names - expected_names)}"
        )

    manifest = _load_json(root / "release-manifest.json", label="release manifest")
    if set(manifest) != {
        "artifacts",
        "display_version",
        "package_version",
        "release_tag",
        "schema_version",
        "source_sha",
    }:
        raise ValueError("release manifest has an unexpected shape")
    if manifest.get("schema_version") != 1 or type(manifest.get("schema_version")) is not int:
        raise ValueError("release manifest schema is unsupported")
    if manifest.get("display_version") != DISPLAY_VERSION or manifest.get("package_version") != __version__:
        raise ValueError("release manifest version does not match this promotion")
    if manifest.get("release_tag") != candidate_tag or manifest.get("source_sha") != source_sha:
        raise ValueError("release manifest does not match the candidate tag and source")

    artifact_rows = manifest.get("artifacts")
    if type(artifact_rows) is not list or len(artifact_rows) != len(expected_artifacts()):
        raise ValueError("release manifest artifact list is invalid")
    rows: list[dict] = []
    for row in artifact_rows:
        if type(row) is not dict or set(row) != {"name", "role", "sha256", "size"}:
            raise ValueError("release manifest artifact entry is invalid")
        name = row.get("name")
        size = row.get("size")
        digest = row.get("sha256")
        if name not in expected_artifacts() or row.get("role") != expected_artifacts().get(name):
            raise ValueError("release manifest artifact identity is invalid")
        if type(size) is not int or size <= 0 or size > MAX_ARTIFACT_BYTES:
            raise ValueError("release manifest artifact size is invalid")
        if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("release manifest artifact digest is invalid")
        rows.append(row)
    if [row["name"] for row in rows] != sorted(expected_artifacts()):
        raise ValueError("release manifest artifact ordering or inventory is invalid")

    for row in rows:
        path = root / row["name"]
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"candidate artifact must be a regular file: {path.name}")
        if metadata.st_size != row["size"] or _sha256(path, metadata) != row["sha256"]:
            raise ValueError(f"candidate artifact does not match its manifest: {path.name}")

    checksums = _read_regular(
        root / "SHA256SUMS", maximum=MAX_METADATA_BYTES, label="candidate checksums"
    )
    expected_checksums = "".join(
        f'{row["sha256"]}  {row["name"]}\n' for row in rows
    ).encode("utf-8")
    if checksums != expected_checksums:
        raise ValueError("candidate checksums do not exactly match the manifest")
    return manifest


def _final_notes(candidate_tag: str, source_sha: str, cohort_url: str) -> str:
    return f"""# Mentat {DISPLAY_VERSION}

This public beta promotes the exact tested assets from [{candidate_tag}](https://github.com/hazeion/agent-os/releases/tag/{candidate_tag}) at source commit `{source_sha}`. The installers and Python artifacts were not rebuilt or renamed.

Read the [quick start](https://github.com/hazeion/agent-os/blob/{DISPLAY_VERSION}/README.md), [support and known limitations](https://github.com/hazeion/agent-os/blob/{DISPLAY_VERSION}/SUPPORT.md), [known issues](https://github.com/hazeion/agent-os/blob/{DISPLAY_VERSION}/KNOWN_ISSUES.md), [privacy policy](https://github.com/hazeion/agent-os/blob/{DISPLAY_VERSION}/PRIVACY.md), [security policy](https://github.com/hazeion/agent-os/blob/{DISPLAY_VERSION}/SECURITY.md), and [recovery guide](https://github.com/hazeion/agent-os/blob/{DISPLAY_VERSION}/RELEASE_REHEARSAL.md) before installing or upgrading.

The limited-beta exit summary is recorded in [this public issue]({cohort_url}). Security reports belong in [private advisories](https://github.com/hazeion/agent-os/security/advisories/new); ordinary bugs use the public issue forms.

Updates are manual. Back up before upgrading. The macOS artifact is Intel; Apple Silicon requires Rosetta. Linux remains a `pipx` preview.
"""


def prepare_promotion(
    bundle_dir: Path,
    release_snapshot: Path,
    cohort_snapshot: Path,
    output_notes: Path,
    candidate_tag: str,
    source_sha: str,
    cohort_summary_url: str,
    confirmation: str,
) -> dict:
    tag = validate_rc_tag(candidate_tag)
    sha = validate_source_sha(source_sha)
    cohort_url = validate_cohort_summary_url(cohort_summary_url)
    if confirmation != CONFIRMATION:
        raise ValueError("public beta promotion confirmation does not match")
    _validate_release_snapshot(release_snapshot, bundle_dir, tag, prerelease=True)
    _validate_cohort_snapshot(cohort_snapshot, cohort_url, tag, sha)
    manifest = inspect_candidate_assets(bundle_dir, tag, sha)
    output_parent = output_notes.parent
    if output_parent.is_symlink() or not output_parent.resolve(strict=True).is_dir():
        raise ValueError("output notes parent is invalid")
    _write_new_text(output_notes, _final_notes(tag, sha, cohort_url))
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Verify an RC and prepare public notes.")
    verify = commands.add_parser(
        "verify-release", help="Verify published release identity and digests."
    )
    for target in (prepare, verify):
        target.add_argument("--bundle-dir", type=Path, required=True)
        target.add_argument("--release-snapshot", type=Path, required=True)
    verify.add_argument("--release-tag", required=True)
    verify.add_argument("--prerelease", action="store_true")
    prepare.add_argument("--cohort-snapshot", type=Path, required=True)
    prepare.add_argument("--output-notes", type=Path, required=True)
    prepare.add_argument("--candidate-tag", required=True)
    prepare.add_argument("--source-sha", required=True)
    prepare.add_argument("--cohort-summary-url", required=True)
    prepare.add_argument("--confirmation", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify-release":
            verify_published_release(
                args.bundle_dir,
                args.release_snapshot,
                args.release_tag,
                prerelease=args.prerelease,
            )
        else:
            prepare_promotion(
                args.bundle_dir,
                args.release_snapshot,
                args.cohort_snapshot,
                args.output_notes,
                args.candidate_tag,
                args.source_sha,
                args.cohort_summary_url,
                args.confirmation,
            )
    except (OSError, ValueError) as error:
        print(f"Public beta promotion failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
