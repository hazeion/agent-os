"""Two-slot replaceable process boundary for hostile preview operations."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Mapping, Sequence

from codex_runtime import _attach_windows_kill_job, _close_windows_job


WORKER_COUNT = 2
DNS_WATCHDOG_SECONDS = 1.0
OPERATION_WATCHDOG_SECONDS = 5.25
MAXIMUM_WORKER_LINE_BYTES = 1024 * 1024
_ALLOWED_ENVIRONMENT = ("SYSTEMROOT", "WINDIR")


class LinkPreviewWorkerError(RuntimeError):
    def __init__(self, code: str):
        safe = code if code in {
            "link_preview.blocked",
            "link_preview.capacity_unavailable",
            "link_preview.unavailable",
        } else "link_preview.unavailable"
        super().__init__(safe)
        self.code = safe


def minimal_worker_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    values = os.environ if source is None else source
    result = {name: values[name] for name in _ALLOWED_ENVIRONMENT if values.get(name)}
    result.update({"LANG": "C.UTF-8", "PYTHONUTF8": "1"})
    return result


def default_worker_command() -> tuple[str, ...]:
    worker = Path(__file__).with_name("link_preview_worker.py").resolve()
    module_root = worker.parent
    bootstrap = (
        "import runpy,sys;"
        f"sys.path.insert(0,{str(module_root)!r});"
        f"runpy.run_path({str(worker)!r},run_name='__main__')"
    )
    return (sys.executable, "-I", "-c", bootstrap)


class _WorkerSlot:
    def __init__(
        self,
        command: Sequence[str],
        *,
        clock: Callable[[], float],
        environment: Mapping[str, str],
        operation_watchdog_seconds: float | None = None,
        maximum_line_bytes: int | None = None,
    ):
        self._command = tuple(command)
        self._clock = clock
        self._environment = dict(environment)
        self._operation_watchdog_seconds = operation_watchdog_seconds
        self._maximum_line_bytes = maximum_line_bytes
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._messages: queue.Queue[bytes | None] = queue.Queue(maxsize=16)
        self._reader: threading.Thread | None = None
        self._shutdown = False
        self._output_failed = threading.Event()
        self._start()

    def _start(self) -> None:
        with self._lifecycle_lock:
            if self._shutdown:
                return
            try:
                self._spawn()
            except BaseException as startup_error:
                self._shutdown = True
                owned_process = self._process
                try:
                    self._terminate()
                except BaseException:
                    self._process = owned_process
                    startup_error._mentat_worker_owner = self
                    raise startup_error from None
                raise

    def _spawn(self) -> None:
        if self._shutdown:
            return
        self._messages = queue.Queue(maxsize=16)
        self._output_failed = threading.Event()
        options: dict[str, object] = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=self._environment,
            cwd=tempfile.gettempdir(),
            close_fds=True,
            **options,
        )
        if os.name == "nt":
            try:
                self._process._mentat_windows_job = _attach_windows_kill_job(self._process)
            except Exception:
                self._process.terminate()
                self._process.wait(timeout=0.5)
                self._process = None
                raise LinkPreviewWorkerError("link_preview.unavailable")
        elif type(self._process.pid) is int:
            self._process._mentat_process_group = self._process.pid

        process = self._process
        messages = self._messages
        output_failed = self._output_failed

        def read_output() -> None:
            if process.stdout is None:
                return
            while True:
                line = process.stdout.readline((self._maximum_line_bytes or MAXIMUM_WORKER_LINE_BYTES) + 1)
                if not line:
                    try:
                        messages.put_nowait(None)
                    except queue.Full:
                        pass
                    return
                try:
                    messages.put(line, timeout=0.1)
                except queue.Full:
                    # Parent owns lifecycle and joining. The output thread
                    # must not contend with shutdown while its parent joins it.
                    output_failed.set()
                    return

        self._reader = threading.Thread(target=read_output, daemon=True, name="mentat-link-preview-worker-reader")
        self._reader.start()

    def _terminate(self) -> None:
        with self._lifecycle_lock:
            try:
                self._terminate_owned()
            except BaseException as cleanup_error:
                self._shutdown = True
                cleanup_error._mentat_worker_owner = self
                raise

    def _terminate_owned(self) -> None:
        process = self._process
        if process is None:
            return
        process_group = getattr(process, "_mentat_process_group", None)
        windows_job = getattr(process, "_mentat_windows_job", None)
        if os.name == "nt" and windows_job is not None:
            process._mentat_windows_job = None
            _close_windows_job(windows_job)
        elif type(process_group) is int and process_group > 1:
            try:
                os.killpg(process_group, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass
        elif process.poll() is None:
            process.terminate()
        if process.poll() is None:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    self._shutdown = True
                    raise LinkPreviewWorkerError("link_preview.unavailable") from None
        if process.poll() is None:
            self._shutdown = True
            raise LinkPreviewWorkerError("link_preview.unavailable")
        if os.name != "nt" and type(process_group) is int and process_group > 1:
            try:
                os.killpg(process_group, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
        for pipe in (process.stdin, process.stdout):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass
        reader = self._reader
        if reader is threading.current_thread():
            # The output thread is returning immediately after this call.
            # Retain ownership until its parent verifies the join.
            return
        if reader is not None and reader.ident is not None:
            reader.join(timeout=0.5)
            if reader.is_alive():
                self._shutdown = True
                raise LinkPreviewWorkerError("link_preview.unavailable")
        self._reader = None
        self._process = None

    def replace(self) -> None:
        with self._lifecycle_lock:
            self._terminate()
            self._start()

    def abort(self) -> None:
        with self._lifecycle_lock:
            self._shutdown = True
            self._terminate()

    def close(self) -> None:
        self.abort()

    def execute(self, *, kind: str, url: str) -> dict[str, object]:
        with self._lock:
            if self._shutdown:
                raise LinkPreviewWorkerError("link_preview.unavailable")
            process = self._process
            if process is None or process.poll() is not None or process.stdin is None:
                self.replace()
                process = self._process
            if process is None or process.stdin is None:
                raise LinkPreviewWorkerError("link_preview.unavailable")
            request_id = secrets.token_hex(16)
            body = json.dumps({"id": request_id, "kind": kind, "url": url}, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
            if len(body) > 4 * 1024:
                raise LinkPreviewWorkerError("link_preview.unavailable")
            try:
                process.stdin.write(body)
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                self.replace()
                raise LinkPreviewWorkerError("link_preview.unavailable")
            started = self._clock()
            watchdog = self._operation_watchdog_seconds or OPERATION_WATCHDOG_SECONDS
            dns_started: float | None = None
            while True:
                if self._output_failed.is_set():
                    self.replace()
                    raise LinkPreviewWorkerError("link_preview.unavailable")
                elapsed = self._clock() - started
                if elapsed >= watchdog or dns_started is not None and self._clock() - dns_started >= DNS_WATCHDOG_SECONDS:
                    self.replace()
                    raise LinkPreviewWorkerError("link_preview.unavailable")
                wait = min(
                    0.05,
                    watchdog - elapsed,
                    DNS_WATCHDOG_SECONDS - (self._clock() - dns_started) if dns_started is not None else 0.05,
                )
                try:
                    raw = self._messages.get(timeout=max(0.001, wait))
                except queue.Empty:
                    continue
                if raw is None or len(raw) > (self._maximum_line_bytes or MAXIMUM_WORKER_LINE_BYTES) or not raw.endswith(b"\n"):
                    self.replace()
                    raise LinkPreviewWorkerError("link_preview.unavailable")
                try:
                    message = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self.replace()
                    raise LinkPreviewWorkerError("link_preview.unavailable")
                if not isinstance(message, dict) or not isinstance(message.get("type"), str):
                    self.replace()
                    raise LinkPreviewWorkerError("link_preview.unavailable")
                if message["type"] == "phase":
                    if set(message) != {"type", "phase"} or message.get("phase") not in {"dns", "connect", "transfer", "parse", "image_decode"}:
                        self.replace()
                        raise LinkPreviewWorkerError("link_preview.unavailable")
                    dns_started = self._clock() if message["phase"] == "dns" else None
                    continue
                if message.get("id") != request_id:
                    self.replace()
                    raise LinkPreviewWorkerError("link_preview.unavailable")
                if message["type"] == "error":
                    if set(message) != {"type", "id", "code"}:
                        self.replace()
                        raise LinkPreviewWorkerError("link_preview.unavailable")
                    code = message.get("code")
                    raise LinkPreviewWorkerError(code if isinstance(code, str) else "link_preview.unavailable")
                if message["type"] != "result" or set(message) != {"type", "id", "result"} or not isinstance(message.get("result"), dict):
                    self.replace()
                    raise LinkPreviewWorkerError("link_preview.unavailable")
                with self._lifecycle_lock:
                    if self._shutdown or self._process is not process:
                        raise LinkPreviewWorkerError("link_preview.unavailable")
                    return message["result"]


class LinkPreviewWorkerPool:
    def __init__(
        self,
        *,
        command: Sequence[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
        environ: Mapping[str, str] | None = None,
    ):
        worker_command = tuple(command or default_worker_command())
        environment = minimal_worker_environment(environ)
        self._slots = []
        self._available: queue.Queue[_WorkerSlot] = queue.Queue(maxsize=WORKER_COUNT)
        self._closed = False
        self._guard = threading.Lock()
        try:
            for _ in range(WORKER_COUNT):
                slot = _WorkerSlot(worker_command, clock=clock, environment=environment)
                self._slots.append(slot)
                self._available.put_nowait(slot)
        except BaseException as startup_error:
            try:
                self.close()
            except BaseException:
                startup_error._mentat_worker_pool = self
                raise startup_error from None
            raise

    def execute(self, *, kind: str, normalized_url: str) -> dict[str, object]:
        if kind not in {"page", "image"} or not isinstance(normalized_url, str):
            raise LinkPreviewWorkerError("link_preview.unavailable")
        with self._guard:
            if self._closed:
                raise LinkPreviewWorkerError("link_preview.unavailable")
        try:
            slot = self._available.get(timeout=0.25)
        except queue.Empty as exc:
            raise LinkPreviewWorkerError("link_preview.capacity_unavailable") from exc
        try:
            result = slot.execute(kind=kind, url=normalized_url)
            with self._guard:
                if self._closed:
                    raise LinkPreviewWorkerError("link_preview.unavailable")
                return result
        finally:
            with self._guard:
                if not self._closed:
                    self._available.put_nowait(slot)

    def close(self) -> None:
        with self._guard:
            self._closed = True
        failure = None
        for slot in self._slots:
            try:
                slot.abort()
            except BaseException as error:
                # Finish every owned slot even for interrupts/unexpected bugs,
                # then re-raise the original failure; never suppress it.
                failure = failure or error
        if failure is not None:
            failure._mentat_worker_pool = self
            raise failure


__all__ = [
    "DNS_WATCHDOG_SECONDS",
    "LinkPreviewWorkerError",
    "LinkPreviewWorkerPool",
    "OPERATION_WATCHDOG_SECONDS",
    "minimal_worker_environment",
]
