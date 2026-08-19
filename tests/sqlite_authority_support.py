"""Test-only setup for the ordered Task-then-Run SQLite authority boundary."""

from __future__ import annotations

from pathlib import Path

from run_repository import ensure_run_sqlite_authority as _ensure_run_sqlite_authority
from task_repository import ensure_task_sqlite_authority


def ensure_run_sqlite_authority(data_dir: Path, history: Path):
    root = Path(data_dir)
    task_source = root / "tasks.json"
    if not task_source.exists():
        task_source.parent.mkdir(parents=True, exist_ok=True)
        task_source.write_text("[]", encoding="utf-8")
        task_source.chmod(0o600)
    ensure_task_sqlite_authority(root, required_source_mode=None)
    return _ensure_run_sqlite_authority(root, history)
