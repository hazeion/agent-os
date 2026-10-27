"""Test-only SQLite authority setup and fixture worker ownership."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from contextvars import ContextVar
from tempfile import TemporaryDirectory as _TemporaryDirectory
import sys
import time

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


_active_roots = ContextVar("worker_fixture_roots", default=())


class TemporaryDirectory(_TemporaryDirectory):
    """Retain a fixture root when a timed-out worker may still own its files."""

    def __enter__(self):
        self._root_token = _active_roots.set((*_active_roots.get(), self))
        self._worker_retained = False
        return super().__enter__()

    def __exit__(self, *args):
        _active_roots.reset(self._root_token)
        if not self._worker_retained:
            return super().__exit__(*args)


@contextmanager
def drain_workers(workers, *releases):
    """Release gates and drain workers within one bounded cleanup budget."""
    try:
        yield
    finally:
        original_error = sys.exception()
        for release in releases:
            release.set()
        deadline = time.monotonic() + THREAD_TIMEOUT
        for worker in workers:
            if worker.ident is not None:
                worker.join(max(0, deadline - time.monotonic()))
        alive = [worker for worker in workers if worker.is_alive()]
        if alive:
            roots = _active_roots.get()
            for root in roots:
                root._worker_retained = True
                root._finalizer.detach()
            diagnostic = (
                f"Workers did not stop within {THREAD_TIMEOUT}s: "
                + ", ".join(f"{w.name} (ident={w.ident})" for w in alive)
                + "; retained fixture roots: "
                + ", ".join(root.name for root in roots)
            )
            if original_error is not None:
                original_error.add_note(diagnostic)
            else:
                raise AssertionError(diagnostic)
