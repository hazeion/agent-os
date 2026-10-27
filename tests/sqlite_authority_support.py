"""Test-only SQLite authority setup and fixture worker ownership."""

from __future__ import annotations

from contextlib import contextmanager
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


THREAD_TIMEOUT = 60


@contextmanager
def drain_workers(workers, *releases):
    """Release gates and drain started workers before fixture resources exit."""
    try:
        yield
    finally:
        for release in releases:
            release.set()
        for worker in workers:
            if worker.ident is not None:
                worker.join()
