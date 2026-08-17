#!/usr/bin/env python
"""Validate 9I stock-compatibility evidence against an exact Hermes checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


EXPECTED_TAG = "v2026.8.13"
EXPECTED_COMMIT = "f80f453ae0679347e38abc917c7f94f717bf96c5"
EXPECTED_SOURCE_SHA256 = {
    "gateway/platforms/api_server.py": "d3d7283f40d877ac6fab48581497302da636af93a64798b21cf1ddb60a51d86b",
    "hermes_cli/_parser.py": "4c2e3028855f0e30cc377d47ec8b46594669556eb3d38bc04c737461d11b7fba",
    "hermes_cli/oneshot.py": "1ef49a3c314df8d6c19c4c7c37b37491904705e95e2a028d5ccc85b290b76cba",
}
REQUIRED_SOURCE_MARKERS = {
    "hermes_cli/_parser.py": ('"--usage-file"', 'metavar="PATH"', "One-shot mode only"),
    "hermes_cli/oneshot.py": (
        "def _write_usage_file", '"input_tokens"', '"output_tokens"',
        '"total_tokens"', '"api_calls"', '"model"', '"provider"',
        '"session_id"', '"completed"', '"failed"',
    ),
    "gateway/platforms/api_server.py": (
        '"run_submission"', '"run_status"', '"run_events_sse"',
        '"run_stop"', '"run_steer"', '"skills_api"',
        '"session_resources"', '"model_options"',
    ),
}
FORBIDDEN_SOURCE_MARKERS = {
    "gateway/platforms/api_server.py": (
        '"run_event_replay"', '"run_pending_action_status"',
        '"run_runtime_identity"', '"profile_inventory"',
        '"profile_runtime_switch"', '"kanban_api"', '"jobs_inventory"',
    ),
}


def _git_output(root: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments], check=True,
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def validate_source(root: Path, *, require_exact: bool = True) -> dict:
    root = root.expanduser().resolve()
    failures: list[dict] = []
    hashes: dict[str, str] = {}
    for relative_path, markers in REQUIRED_SOURCE_MARKERS.items():
        path = root / relative_path
        try:
            body = path.read_bytes()
            source = body.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            failures.append({"file": relative_path, "error": "unreadable"})
            continue
        digest = hashlib.sha256(body).hexdigest()
        hashes[relative_path] = digest
        if require_exact and digest != EXPECTED_SOURCE_SHA256[relative_path]:
            failures.append({"file": relative_path, "error": "unexpected_sha256"})
        missing = [marker for marker in markers if marker not in source]
        if missing:
            failures.append({"file": relative_path, "missing": missing})
        unexpected = [
            marker for marker in FORBIDDEN_SOURCE_MARKERS.get(relative_path, ())
            if marker in source
        ]
        if unexpected:
            failures.append({"file": relative_path, "unexpected": unexpected})

    commit = None
    if require_exact:
        commit = _git_output(root, "rev-parse", "HEAD")
        tag_commit = _git_output(root, "rev-parse", f"refs/tags/{EXPECTED_TAG}^{{commit}}")
        dirty = _git_output(root, "status", "--porcelain", "--", *REQUIRED_SOURCE_MARKERS)
        if commit != EXPECTED_COMMIT:
            failures.append({"file": ".git", "error": "unexpected_commit"})
        if tag_commit != EXPECTED_COMMIT:
            failures.append({"file": ".git", "error": "unexpected_tag_target"})
        if dirty is None or dirty:
            failures.append({"file": ".git", "error": "inspected_source_dirty_or_unverified"})
    return {
        "ok": not failures, "expected_tag": EXPECTED_TAG,
        "expected_commit": EXPECTED_COMMIT, "actual_commit": commit,
        "files_checked": len(REQUIRED_SOURCE_MARKERS),
        "source_sha256": hashes, "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-source", type=Path, required=True)
    result = validate_source(parser.parse_args().hermes_source)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
