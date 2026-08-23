#!/usr/bin/env python3
"""Copy the Next standalone runtime into a regular-file package staging tree."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mentat.package_data import validate_web_runtime


SOURCE = ROOT / "web" / ".next" / "standalone"
DESTINATION = ROOT / "web" / "package-runtime"
def main() -> int:
    if not (SOURCE / "server.js").is_file():
        raise RuntimeError("Missing web/.next/standalone/server.js; run npm --prefix web run build first.")
    validate_web_runtime(SOURCE)
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    shutil.copytree(SOURCE, DESTINATION, symlinks=False)
    validate_web_runtime(DESTINATION)
    if not (DESTINATION / "server.js").is_file():
        raise RuntimeError("Staged Node dashboard is incomplete")
    print(f"Staged Node dashboard at {DESTINATION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
