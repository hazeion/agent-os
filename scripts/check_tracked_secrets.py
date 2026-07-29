#!/usr/bin/env python3
"""Fail when tracked files contain secret candidates outside the reviewed baseline."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _candidates(
    payload: dict[str, Any],
) -> dict[tuple[str, str, str], list[int | None]]:
    found: dict[tuple[str, str, str], list[int | None]] = {}
    for filename, entries in payload.get("results", {}).items():
        for entry in entries:
            key = (filename, entry["type"], entry["hashed_secret"])
            found.setdefault(key, []).append(entry.get("line_number"))
    return found


def new_candidates(
    current: dict[str, Any], baseline: dict[str, Any]
) -> list[tuple[str, str, int | None]]:
    reviewed = _candidates(baseline)
    findings: list[tuple[str, str, int | None]] = []
    for key, lines in _candidates(current).items():
        filename, kind, _fingerprint = key
        reviewed_count = len(reviewed.get(key, []))
        findings.extend((filename, kind, line) for line in lines[reviewed_count:])
    return sorted(findings)


def scan_repository() -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "detect_secrets",
        "scan",
        "--no-verify",
        "--exclude-files",
        r"(^|/)\.secrets\.baseline$",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline", type=Path, default=Path(".secrets.baseline")
    )
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    findings = new_candidates(scan_repository(), baseline)
    if findings:
        print("Unreviewed secret-like values detected:", file=sys.stderr)
        for filename, kind, line in findings:
            location = f"{filename}:{line}" if line else filename
            print(f"- {location} ({kind})", file=sys.stderr)
        return 1
    print("Tracked-file secret scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
