"""Codex App Server adapter for Mentat's runtime-neutral boundary.

The adapter owns one private, local stdio JSONL connection. Browser input can
never select the executable, working directory, provider, credential source,
or App Server method.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import shutil
import stat
import subprocess
import threading
import time
from typing import Any, Callable

from agent_runtime import (
    AgentEvent,
    AgentEventType,
    AgentRun,
    AgentRuntimeError,
    MentatTask,
    PendingRunAction,
    RunActionResponse,
    RunStatus,
    RuntimeCapability,
    RuntimeCapacity,
    RuntimeContext,
    SubmissionDisposition,
    SubmissionOutcome,
)


CODEX_DEFAULT_BINDING = "default"
CODEX_RUNTIME_TYPE = "codex"
MAXIMUM_PROTOCOL_LINE_BYTES = 8 * 1024 * 1024
MAXIMUM_PROTOCOL_REQUEST_BYTES = 256 * 1024
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
READINESS_REQUEST_TIMEOUT_SECONDS = 5.0
START_TASK_OPERATION_TIMEOUT_SECONDS = 20.0
READINESS_CACHE_SECONDS = 5.0
MAXIMUM_TURN_ITEMS = 4096
MAXIMUM_TASK_PROMPT_BYTES = 40_000
CODEX_ADMISSION_LIMIT = 2

_ACCOUNT_TYPES = frozenset({"apiKey", "chatgpt", "amazonBedrock"})
_CHATGPT_PLAN_TYPES = frozenset(
    {
        "free",
        "go",
        "plus",
        "pro",
        "prolite",
        "team",
        "self_serve_business_usage_based",
        "business",
        "enterprise_cbp_usage_based",
        "enterprise",
        "edu",
        "unknown",
    }
)
_APPROVAL_REVIEWERS = frozenset({"user", "auto_review", "guardian_subagent"})

_RUNTIME_ID_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_ITEM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_METHOD = re.compile(r"[A-Za-z][A-Za-z0-9]*/[A-Za-z][A-Za-z0-9/]*\Z|initialize\Z")
_IN_PROGRESS_ITEM_STATUSES = frozenset({"inprogress", "pending", "running", "started"})
_TURN_STATUSES = {
    "inProgress": RunStatus.RUNNING,
    "completed": RunStatus.COMPLETED,
    "interrupted": RunStatus.STOPPED,
    "failed": RunStatus.FAILED,
}
_TERMINAL_STATUSES = frozenset({RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.FAILED})
_ACTIVE_CAPABILITIES = frozenset(
    {
        RuntimeCapability.START_TASK.value,
        RuntimeCapability.STATUS.value,
        RuntimeCapability.EVENTS.value,
        RuntimeCapability.SEND_MESSAGE.value,
        RuntimeCapability.STOP.value,
    }
)
_TERMINAL_CAPABILITIES = frozenset(
    {RuntimeCapability.STATUS.value, RuntimeCapability.EVENTS.value}
)
_ENVIRONMENT_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LOCALAPPDATA",
    "APPDATA",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "CODEX_HOME",
)


class CodexAppServerClientError(RuntimeError):
    """Bounded client failure with submission certainty information."""

    def __init__(self, code: str, *, uncertain: bool):
        super().__init__(code)
        self.code = code
        self.uncertain = bool(uncertain)


def _attach_windows_kill_job(process: subprocess.Popen) -> object | None:
    """Own a Windows process tree by handle, never by a reusable PID."""

    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    try:
        information = _ExtendedLimitInformation()
        information.BasicLimitInformation.LimitFlags = 0x00002000
        if not kernel32.SetInformationJobObject(
            job,
            9,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            raise OSError(
                ctypes.get_last_error(), "SetInformationJobObject failed"
            )
        process_handle = int(getattr(process, "_handle"))
        if not kernel32.AssignProcessToJobObject(
            job, wintypes.HANDLE(process_handle)
        ):
            raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")
    except Exception:
        kernel32.CloseHandle(job)
        raise
    return job


def _close_windows_job(job: object | None) -> None:
    if os.name != "nt" or job is None:
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(job)


@dataclass
class _PendingResponse:
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: CodexAppServerClientError | None = None


def codex_child_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Give App Server only process essentials and host-owned Codex paths."""

    values = os.environ if source is None else source
    environment = {
        name: str(values[name])
        for name in _ENVIRONMENT_ALLOWLIST
        if isinstance(values.get(name), str) and str(values[name])
    }
    environment["NO_COLOR"] = "1"
    return environment


def _trusted_executable(candidate: object) -> str | None:
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        return None
    try:
        resolved = path.resolve(strict=True)
        details = resolved.stat()
    except OSError:
        return None
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        return None
    if os.name == "nt":
        # A .cmd shim requires a command interpreter. The adapter promises a
        # direct child process, so Windows discovery accepts native executables
        # only.
        if resolved.suffix.lower() != ".exe":
            return None
    else:
        owners = {0, os.getuid()} if hasattr(os, "getuid") else {details.st_uid}
        if (
            details.st_uid not in owners
            or details.st_mode & 0o022
            or not os.access(resolved, os.X_OK)
        ):
            return None
    return str(resolved)


def find_codex_command(source: Mapping[str, str] | None = None) -> str | None:
    """Find a trusted local Codex CLI without accepting a browser path."""

    environment = os.environ if source is None else source
    candidates: list[str | None] = [shutil.which("codex", path=environment.get("PATH"))]
    home_value = environment.get("HOME") or environment.get("USERPROFILE")
    if home_value:
        home = Path(home_value).expanduser()
        candidates.extend(
            [
                str(home / ".local" / "bin" / "codex"),
                str(home / ".local" / "bin" / "codex.exe"),
                str(home / ".codex" / "packages" / "standalone" / "current" / "bin" / "codex"),
                str(home / ".codex" / "packages" / "standalone" / "current" / "bin" / "codex.exe"),
            ]
        )
    if os.name == "nt":
        app_data = environment.get("APPDATA")
        if app_data:
            candidates.append(str(Path(app_data) / "npm" / "codex.exe"))
    else:
        candidates.extend(["/usr/local/bin/codex", "/opt/homebrew/bin/codex"])
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        trusted = _trusted_executable(candidate)
        if trusted is not None:
            return trusted
    return None


def codex_app_server_command(command_path: str) -> tuple[str, ...]:
    """Return the complete fixed App Server command with safe child env policy."""

    if not isinstance(command_path, str) or not Path(command_path).is_absolute():
        raise ValueError("Codex command path must be absolute")
    return (
        command_path,
        "-c",
        'shell_environment_policy.inherit="core"',
        "-c",
        "shell_environment_policy.ignore_default_excludes=false",
        "app-server",
        "--stdio",
    )


def codex_binding_is_valid(
    runtime_agent_ref: object, capabilities: object
) -> bool:
    """Validate durable Codex binding values without launching the CLI."""

    if (
        runtime_agent_ref != CODEX_DEFAULT_BINDING
        or isinstance(capabilities, (str, bytes))
        or not isinstance(capabilities, (Sequence, set, frozenset))
    ):
        return False
    try:
        requested = frozenset(capabilities)
    except (TypeError, ValueError):
        return False
    return all(isinstance(value, str) for value in requested) and requested.issubset(
        _ACTIVE_CAPABILITIES
    )


class CodexAppServerClient:
    """Small synchronized JSONL client for one local Codex App Server child."""

    def __init__(
        self,
        *,
        command: Sequence[str],
        cwd: Path,
        environment: Mapping[str, str] | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        maximum_line_bytes: int = MAXIMUM_PROTOCOL_LINE_BYTES,
        process_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ):
        normalized_command = tuple(str(value) for value in command)
        root = Path(cwd).resolve()
        if (
            not normalized_command
            or not root.is_dir()
            or not isinstance(request_timeout, (int, float))
            or not 0.1 <= float(request_timeout) <= 120
            or type(maximum_line_bytes) is not int
            or not 1024 <= maximum_line_bytes <= MAXIMUM_PROTOCOL_LINE_BYTES
        ):
            raise ValueError("Codex App Server client configuration is invalid")
        self.command = normalized_command
        self.cwd = root
        self.environment = dict(environment or codex_child_environment())
        self.request_timeout = float(request_timeout)
        self.maximum_line_bytes = maximum_line_bytes
        self._process_factory = process_factory
        self._condition = threading.Condition(threading.RLock())
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, _PendingResponse] = {}
        self._process: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._generation = 0
        self._next_request_id = 1
        self._ready = False
        self._starting = False
        self._closed = False

    @staticmethod
    def _terminate(process: subprocess.Popen | None) -> None:
        if process is None:
            return
        process_group = getattr(process, "_mentat_process_group", None)
        windows_job = getattr(process, "_mentat_windows_job", None)
        try:
            if os.name == "nt" and windows_job is not None:
                process._mentat_windows_job = None
                _close_windows_job(windows_job)
            elif type(process_group) is int and process_group > 1:
                try:
                    os.killpg(process_group, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            elif process.poll() is None:
                process.terminate()
            if process.poll() is None:
                process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            if os.name != "nt" and type(process_group) is int and process_group > 1:
                try:
                    # The App Server owns this session. Kill any child that
                    # ignored the graceful group signal before closing pipes.
                    os.killpg(process_group, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    pass
            if process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            for stream in (process.stdin, process.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    continue

    def _spawn(self) -> subprocess.Popen:
        process_options: dict[str, object] = {}
        if os.name == "nt":
            process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            process_options["start_new_session"] = True
        try:
            process = self._process_factory(
                list(self.command),
                cwd=str(self.cwd),
                env=dict(self.environment),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                **process_options,
            )
        except OSError as exc:
            raise CodexAppServerClientError("codex.unavailable", uncertain=False) from exc
        if os.name == "nt":
            try:
                process._mentat_windows_job = _attach_windows_kill_job(process)
            except (AttributeError, OSError, TypeError, ValueError) as exc:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                raise CodexAppServerClientError(
                    "codex.unavailable", uncertain=False
                ) from exc
        elif type(getattr(process, "pid", None)) is int:
            process._mentat_process_group = process.pid
        if process.stdin is None or process.stdout is None:
            self._terminate(process)
            raise CodexAppServerClientError("codex.unavailable", uncertain=False)
        return process

    @staticmethod
    def _initialize_params() -> dict[str, object]:
        return {
            "clientInfo": {
                "name": "mentat",
                "title": "Mentat",
                "version": "1",
            }
        }

    def _ensure_ready(self, *, timeout: float | None = None) -> None:
        startup_timeout = self.request_timeout if timeout is None else float(timeout)
        deadline = time.monotonic() + startup_timeout
        while True:
            with self._condition:
                if self._closed:
                    raise CodexAppServerClientError("codex.unavailable", uncertain=False)
                if self._ready and self._process is not None and self._process.poll() is None:
                    return
                if self._starting:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CodexAppServerClientError("codex.unavailable", uncertain=False)
                    self._condition.wait(timeout=remaining)
                    continue
                old_process = self._process
                self._process = None
                self._ready = False
                self._starting = True
                self._generation += 1
                generation = self._generation
                break

        self._terminate(old_process)
        process: subprocess.Popen | None = None
        try:
            process = self._spawn()
            with self._condition:
                if self._closed:
                    raise CodexAppServerClientError("codex.unavailable", uncertain=False)
                self._process = process
                reader = threading.Thread(
                    target=self._reader_loop,
                    args=(process, generation),
                    name="mentat-codex-app-server",
                    daemon=True,
                )
                self._reader = reader
                reader.start()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexAppServerClientError(
                    "codex.request_timeout",
                    uncertain=False,
                )
            initialized = self._request_started(
                "initialize", self._initialize_params(), timeout=remaining
            )
            if not isinstance(initialized, Mapping):
                raise CodexAppServerClientError("codex.protocol_invalid", uncertain=False)
            self._write_message(
                {"method": "initialized", "params": {}}, generation=generation
            )
            with self._condition:
                if self._process is not process or process.poll() is not None:
                    raise CodexAppServerClientError("codex.protocol_unavailable", uncertain=False)
                self._ready = True
                self._starting = False
                self._condition.notify_all()
        except Exception:
            self._terminate(process)
            with self._condition:
                if self._process is process:
                    self._process = None
                self._ready = False
                self._starting = False
                self._condition.notify_all()
            raise

    @staticmethod
    def _encoded_message(message: Mapping[str, Any]) -> bytes:
        try:
            encoded = json.dumps(
                dict(message), ensure_ascii=True, separators=(",", ":")
            ).encode("ascii") + b"\n"
        except (TypeError, ValueError, UnicodeError) as exc:
            raise CodexAppServerClientError("codex.request_invalid", uncertain=False) from exc
        if len(encoded) > MAXIMUM_PROTOCOL_REQUEST_BYTES:
            raise CodexAppServerClientError("codex.request_invalid", uncertain=False)
        return encoded

    def _write_message(self, message: Mapping[str, Any], *, generation: int) -> None:
        encoded = self._encoded_message(message)
        try:
            with self._write_lock:
                with self._condition:
                    process = self._process
                    if (
                        self._closed
                        or generation != self._generation
                        or process is None
                        or process.poll() is not None
                        or process.stdin is None
                    ):
                        raise OSError("Codex App Server is unavailable")
                    stream = process.stdin
                stream.write(encoded)
                stream.flush()
        except (OSError, ValueError) as exc:
            self._mark_broken(generation, "codex.request_unknown")
            raise CodexAppServerClientError("codex.request_unknown", uncertain=True) from exc

    def _request_started(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Any:
        with self._condition:
            generation = self._generation
            if self._process is None or self._process.poll() is not None:
                raise CodexAppServerClientError("codex.unavailable", uncertain=False)
        with self._pending_lock:
            request_id = self._next_request_id
            self._next_request_id += 1
            pending = _PendingResponse()
            self._pending[request_id] = pending
        try:
            self._write_message(
                {"method": method, "id": request_id, "params": dict(params)},
                generation=generation,
            )
        except Exception:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise
        if not pending.event.wait(timeout=timeout):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise CodexAppServerClientError("codex.request_timeout", uncertain=True)
        if pending.error is not None:
            raise pending.error
        return pending.result

    def request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        if (
            not isinstance(method, str)
            or _METHOD.fullmatch(method) is None
            or not isinstance(params, Mapping)
        ):
            raise CodexAppServerClientError("codex.request_invalid", uncertain=False)
        request_timeout = self.request_timeout if timeout is None else timeout
        if not isinstance(request_timeout, (int, float)) or not 0.1 <= float(
            request_timeout
        ) <= 120:
            raise CodexAppServerClientError("codex.request_invalid", uncertain=False)
        deadline = time.monotonic() + float(request_timeout)
        self._ensure_ready(timeout=float(request_timeout))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CodexAppServerClientError(
                "codex.request_timeout",
                uncertain=False,
            )
        return self._request_started(method, params, timeout=remaining)

    def _deliver_response(self, message: Mapping[str, Any], generation: int) -> bool:
        request_id = message.get("id")
        if type(request_id) is not int:
            return False
        with self._pending_lock:
            pending = self._pending.pop(request_id, None)
        if pending is None:
            return True
        has_result = "result" in message
        has_error = "error" in message
        if has_result == has_error:
            pending.error = CodexAppServerClientError(
                "codex.protocol_invalid", uncertain=True
            )
            self._mark_broken(generation, "codex.protocol_invalid")
        elif has_error:
            pending.error = CodexAppServerClientError(
                "codex.request_rejected", uncertain=False
            )
        else:
            pending.result = message.get("result")
        pending.event.set()
        return True

    def _deny_server_request(self, message: Mapping[str, Any], generation: int) -> bool:
        request_id = message.get("id")
        method = message.get("method")
        if (
            not isinstance(method, str)
            or not (type(request_id) is int or isinstance(request_id, str))
            or isinstance(request_id, str) and len(request_id) > 128
        ):
            return False
        try:
            self._write_message(
                {
                    "id": request_id,
                    "error": {
                        "code": -32601,
                        "message": "Mentat does not support this App Server request.",
                    },
                },
                generation=generation,
            )
        except CodexAppServerClientError:
            return False
        return True

    def _reader_loop(self, process: subprocess.Popen, generation: int) -> None:
        stream = process.stdout
        if stream is None:
            self._mark_broken(generation, "codex.protocol_unavailable")
            return
        while True:
            try:
                line = stream.readline(self.maximum_line_bytes + 1)
            except (OSError, ValueError):
                line = b""
            if not line:
                self._mark_broken(generation, "codex.protocol_unavailable")
                return
            if len(line) > self.maximum_line_bytes or not line.endswith(b"\n"):
                self._mark_broken(generation, "codex.protocol_invalid")
                self._terminate(process)
                return
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._mark_broken(generation, "codex.protocol_invalid")
                self._terminate(process)
                return
            if not isinstance(message, dict):
                self._mark_broken(generation, "codex.protocol_invalid")
                self._terminate(process)
                return
            if "id" in message and "method" not in message:
                if not self._deliver_response(message, generation):
                    self._mark_broken(generation, "codex.protocol_invalid")
                    self._terminate(process)
                    return
            elif "id" in message and "method" in message:
                if not self._deny_server_request(message, generation):
                    self._mark_broken(generation, "codex.protocol_invalid")
                    self._terminate(process)
                    return
            elif isinstance(message.get("method"), str):
                # Notifications are intentionally drained but never forwarded.
                continue
            else:
                self._mark_broken(generation, "codex.protocol_invalid")
                self._terminate(process)
                return

    def _mark_broken(self, generation: int, code: str) -> None:
        with self._condition:
            if generation != self._generation:
                return
            self._ready = False
            self._condition.notify_all()
        error = CodexAppServerClientError(code, uncertain=True)
        with self._pending_lock:
            pending = tuple(self._pending.values())
            self._pending.clear()
        for item in pending:
            item.error = error
            item.event.set()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._ready = False
            process = self._process
            reader = self._reader
            self._process = None
            self._condition.notify_all()
        self._terminate(process)
        error = CodexAppServerClientError("codex.unavailable", uncertain=True)
        with self._pending_lock:
            pending = tuple(self._pending.values())
            self._pending.clear()
        for item in pending:
            item.error = error
            item.event.set()
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1)


def _runtime_reference(thread_id: object, turn_id: object) -> str:
    if (
        not isinstance(thread_id, str)
        or _RUNTIME_ID_PART.fullmatch(thread_id) is None
        or not isinstance(turn_id, str)
        or _RUNTIME_ID_PART.fullmatch(turn_id) is None
    ):
        raise ValueError("Codex runtime reference is invalid")
    return f"{thread_id}:{turn_id}"


def _split_runtime_reference(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or value.count(":") != 1:
        raise AgentRuntimeError("runtime.identity_mismatch")
    thread_id, turn_id = value.split(":", 1)
    try:
        _runtime_reference(thread_id, turn_id)
    except ValueError as exc:
        raise AgentRuntimeError("runtime.identity_mismatch") from exc
    return thread_id, turn_id


def _iso_timestamp(value: object, *, code: str) -> str:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise AgentRuntimeError(code)
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError) as exc:
        raise AgentRuntimeError(code) from exc


class CodexRuntime:
    """Capability-scoped Codex adapter backed by the stable App Server API."""

    runtime_type = CODEX_RUNTIME_TYPE
    registration_capabilities = _ACTIVE_CAPABILITIES

    def __init__(
        self,
        *,
        workspace_root: Path,
        command: Sequence[str] | None,
        client: Any | None = None,
        client_factory: Callable[..., CodexAppServerClient] = CodexAppServerClient,
    ):
        root = Path(workspace_root).resolve()
        if not root.is_dir():
            raise ValueError("Codex workspace root is invalid")
        normalized_command = tuple(str(value) for value in command) if command else None
        if normalized_command is not None and (
            not normalized_command
            or normalized_command != codex_app_server_command(normalized_command[0])
        ):
            raise ValueError("Codex App Server command is not fixed")
        self.workspace_root = root
        self.command = normalized_command
        self._client = client
        self._client_factory = client_factory
        self._client_lock = threading.Lock()
        self._readiness_lock = threading.Lock()
        self._readiness_checked_at = 0.0
        self._readiness_available = False
        self._readiness_state = "unavailable"
        self._closed = False

    @staticmethod
    def _account_is_ready(response: object) -> bool:
        if not isinstance(response, Mapping):
            return False
        account = response.get("account")
        requires_openai_auth = response.get("requiresOpenaiAuth")
        if type(requires_openai_auth) is not bool:
            return False
        if account is None:
            return not requires_openai_auth
        if not isinstance(account, Mapping):
            return False
        account_type = account.get("type")
        if account_type not in _ACCOUNT_TYPES:
            return False
        if account_type == "chatgpt":
            email = account.get("email")
            return (
                (email is None or isinstance(email, str))
                and account.get("planType") in _CHATGPT_PLAN_TYPES
            )
        if account_type == "amazonBedrock":
            return account.get("credentialSource", "awsManaged") in {
                "codexManaged",
                "awsManaged",
            }
        return True

    @classmethod
    def _account_readiness_state(cls, response: object) -> str:
        if not isinstance(response, Mapping):
            return "unavailable"
        requires_openai_auth = response.get("requiresOpenaiAuth")
        account = response.get("account")
        if type(requires_openai_auth) is not bool:
            return "unavailable"
        if account is None:
            return "sign_in_required" if requires_openai_auth else "ready"
        return "ready" if cls._account_is_ready(response) else "unavailable"

    def readiness_status(self, *, force: bool = True) -> str:
        """Return one bounded state without exposing Codex account metadata."""

        now = time.monotonic()
        with self._client_lock:
            if self._closed:
                return "unavailable"
            if self.command is None and self._client is None:
                return "cli_missing"
            if (
                not force
                and self._readiness_checked_at > 0
                and now - self._readiness_checked_at <= READINESS_CACHE_SECONDS
            ):
                return self._readiness_state

        with self._readiness_lock:
            now = time.monotonic()
            with self._client_lock:
                if self._closed:
                    return "unavailable"
                if self.command is None and self._client is None:
                    return "cli_missing"
                if (
                    not force
                    and self._readiness_checked_at > 0
                    and now - self._readiness_checked_at <= READINESS_CACHE_SECONDS
                ):
                    return self._readiness_state
            try:
                response = self._require_client().request(
                    "account/read",
                    {"refreshToken": False},
                    timeout=READINESS_REQUEST_TIMEOUT_SECONDS,
                )
                state = self._account_readiness_state(response)
            except (
                AttributeError,
                CodexAppServerClientError,
                OSError,
                TypeError,
                ValueError,
            ):
                state = "unavailable"
            with self._client_lock:
                if self._closed:
                    return "unavailable"
                self._readiness_checked_at = time.monotonic()
                self._readiness_state = state
                self._readiness_available = state == "ready"
            return state

    def _readiness_capabilities(self, *, force: bool) -> frozenset[str]:
        return (
            _ACTIVE_CAPABILITIES
            if self.readiness_status(force=force) == "ready"
            else frozenset()
        )

    @property
    def capabilities(self) -> frozenset[str]:
        return self._readiness_capabilities(force=False)

    def capacity_for_binding(self, runtime_agent_ref: str) -> RuntimeCapacity:
        """Declare Mentat's tested ceiling for this owned App Server process."""

        if runtime_agent_ref != CODEX_DEFAULT_BINDING:
            raise AgentRuntimeError("runtime.binding_invalid")
        workspace_digest = hashlib.sha256(
            str(self.workspace_root).encode("utf-8")
        ).hexdigest()
        return RuntimeCapacity(
            scope=f"codex-app-server:{workspace_digest}",
            limit=CODEX_ADMISSION_LIMIT,
        )

    def validate_agent_binding(
        self,
        runtime_agent_ref: object,
        capabilities: Sequence[object],
    ) -> None:
        """Validate the only Codex binding this first adapter can honor."""

        if not codex_binding_is_valid(runtime_agent_ref, capabilities):
            raise AgentRuntimeError("runtime.binding_invalid")
        requested = frozenset(capabilities)
        available = self._readiness_capabilities(force=False)
        if (
            RuntimeCapability.START_TASK.value not in available
            or not requested.issubset(available)
        ):
            raise AgentRuntimeError("runtime.binding_invalid")

    def _require_client(self):
        with self._client_lock:
            if self._closed or (self._client is None and self.command is None):
                raise CodexAppServerClientError("codex.unavailable", uncertain=False)
            if self._client is None:
                self._client = self._client_factory(
                    command=self.command,
                    cwd=self.workspace_root,
                    environment=codex_child_environment(),
                )
            return self._client

    def close(self) -> None:
        with self._client_lock:
            if self._closed:
                return
            self._closed = True
            self._readiness_available = False
            self._readiness_state = "unavailable"
            client = self._client
            self._client = None
        if client is not None:
            client.close()

    @staticmethod
    def _rejected(code: str) -> SubmissionOutcome:
        return SubmissionOutcome(
            SubmissionDisposition.REJECTED,
            failure_code=code,
        )

    @staticmethod
    def _unknown(
        code: str,
        *,
        runtime_run_ref: str | None = None,
        execution_identity: Mapping[str, str | None] | None = None,
    ) -> SubmissionOutcome:
        return SubmissionOutcome(
            SubmissionDisposition.UNKNOWN,
            runtime_run_ref=runtime_run_ref,
            failure_code=code,
            execution_identity=execution_identity,
        )

    @staticmethod
    def _task_prompt(task: MentatTask) -> str:
        lines = [task.objective]
        if task.acceptance_criteria:
            lines.extend(["", "Acceptance criteria:"])
            lines.extend(f"- {criterion}" for criterion in task.acceptance_criteria)
        prompt = "\n".join(lines)
        if len(prompt.encode("utf-8")) > MAXIMUM_TASK_PROMPT_BYTES:
            raise ValueError("Codex task prompt is too large")
        return prompt

    @staticmethod
    def _submission_binding_valid(task: MentatTask, context: RuntimeContext) -> bool:
        return (
            context.runtime_agent_ref == CODEX_DEFAULT_BINDING
            and context.task_id == task.id
            and context.mentat_run_id is not None
            and context.dispatch_id is not None
            and (task.assigned_agent_id is None or task.assigned_agent_id == context.agent_id)
        )

    def _verified_thread(
        self,
        response: object,
    ) -> tuple[str, Mapping[str, str | None]]:
        if not isinstance(response, Mapping):
            raise ValueError("Codex thread response is invalid")
        required = {
            "approvalPolicy",
            "approvalsReviewer",
            "cwd",
            "model",
            "modelProvider",
            "sandbox",
            "thread",
        }
        if not required.issubset(response):
            raise ValueError("Codex thread boundary is incomplete")
        thread = response.get("thread")
        if not isinstance(thread, Mapping):
            raise ValueError("Codex thread boundary is invalid")
        if response.get("approvalPolicy") != "never":
            raise ValueError("Codex thread boundary is invalid")
        if response.get("approvalsReviewer") not in _APPROVAL_REVIEWERS:
            raise ValueError("Codex thread boundary is invalid")
        cwd = response.get("cwd")
        if not isinstance(cwd, str) or Path(cwd).resolve() != self.workspace_root:
            raise ValueError("Codex thread boundary is invalid")
        for key in ("model", "modelProvider"):
            value = response.get(key)
            if (
                not isinstance(value, str)
                or not value
                or len(value) > 160
                or "\x00" in value
            ):
                raise ValueError("Codex thread boundary is invalid")
        reasoning_effort = response.get("reasoningEffort")
        if reasoning_effort is not None and (
            not isinstance(reasoning_effort, str)
            or not reasoning_effort
            or len(reasoning_effort) > 64
            or "\x00" in reasoning_effort
        ):
            raise ValueError("Codex thread boundary is invalid")
        sandbox = response.get("sandbox")
        if not isinstance(sandbox, Mapping):
            raise ValueError("Codex thread boundary is invalid")
        writable_roots = sandbox.get("writableRoots")
        if (
            sandbox.get("type") != "workspaceWrite"
            or sandbox.get("networkAccess") is not False
            or not isinstance(writable_roots, list)
            or len(writable_roots) > 1
            or any(
                not isinstance(root, str)
                or Path(root).resolve() != self.workspace_root
                for root in writable_roots
            )
        ):
            raise ValueError("Codex thread boundary is invalid")
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or _RUNTIME_ID_PART.fullmatch(thread_id) is None:
            raise ValueError("Codex thread identity is invalid")
        return thread_id, {
            "model": str(response["model"]),
            "provider": str(response["modelProvider"]),
            "reasoning_effort": reasoning_effort,
            "verification": "runtime_response",
        }

    @staticmethod
    def _verified_continuation_thread(
        response: object,
        *,
        expected_thread_id: str,
        expected_turn_id: str,
    ) -> str:
        if not isinstance(response, Mapping) or not isinstance(
            response.get("thread"), Mapping
        ):
            raise ValueError("Codex continuation thread is invalid")
        thread = response["thread"]
        turns = thread.get("turns")
        if (
            thread.get("id") != expected_thread_id
            or not isinstance(turns, list)
            or len(turns) > 1_024
        ):
            raise ValueError("Codex continuation thread is invalid")
        matches = [
            turn
            for turn in turns
            if isinstance(turn, Mapping) and turn.get("id") == expected_turn_id
        ]
        if len(matches) != 1 or matches[0].get("status") != "completed":
            raise ValueError("Codex continuation turn is not complete")
        return expected_thread_id

    @staticmethod
    def _verified_turn(response: object) -> Mapping[str, Any]:
        if not isinstance(response, Mapping) or not isinstance(response.get("turn"), Mapping):
            raise ValueError("Codex turn response is invalid")
        turn = response["turn"]
        turn_id = turn.get("id")
        status = turn.get("status")
        if (
            not isinstance(turn_id, str)
            or _RUNTIME_ID_PART.fullmatch(turn_id) is None
            or status not in _TURN_STATUSES
        ):
            raise ValueError("Codex turn response is invalid")
        return turn

    def submit_task(self, task: MentatTask, context: RuntimeContext) -> SubmissionOutcome:
        if not self._submission_binding_valid(task, context):
            return self._rejected("runtime.binding_invalid")
        if RuntimeCapability.START_TASK.value not in self._readiness_capabilities(force=False):
            return self._rejected("runtime.start_rejected")
        try:
            prompt = self._task_prompt(task)
        except (TypeError, ValueError, UnicodeError):
            return self._rejected("runtime.task_invalid")
        deadline = time.monotonic() + START_TASK_OPERATION_TIMEOUT_SECONDS

        def remaining_timeout() -> float:
            remaining = deadline - time.monotonic()
            if remaining < 0.1:
                raise CodexAppServerClientError(
                    "codex.request_timeout",
                    uncertain=False,
                )
            # A monotonic-clock subtraction may exceed the original budget by
            # a tiny floating-point rounding error.  Keep the timeout passed
            # to the App Server inside the fixed operation budget.
            return min(remaining, START_TASK_OPERATION_TIMEOUT_SECONDS)

        continuation = context.continuation_runtime_run_ref
        try:
            client = self._require_client()
        except CodexAppServerClientError as exc:
            if exc.uncertain:
                return self._unknown("runtime.submission_unknown")
            return self._rejected("runtime.start_rejected")
        execution_identity = None
        if continuation is None:
            try:
                thread_response = client.request(
                    "thread/start",
                    {
                        "approvalPolicy": "never",
                        "cwd": str(self.workspace_root),
                        "ephemeral": False,
                        "sandbox": "workspace-write",
                        "serviceName": "mentat",
                    },
                    timeout=remaining_timeout(),
                )
            except CodexAppServerClientError as exc:
                if exc.uncertain:
                    return self._unknown("runtime.submission_unknown")
                return self._rejected("runtime.start_rejected")
            try:
                thread_id, execution_identity = self._verified_thread(
                    thread_response
                )
            except (OSError, TypeError, ValueError):
                # App Server may already have created this thread. Treat an
                # unsafe or incomplete echo as ambiguous, never as retryable.
                return self._unknown("runtime.start_unverified")
        else:
            try:
                prior_thread_id, prior_turn_id = _split_runtime_reference(
                    continuation
                )
                thread_response = client.request(
                    "thread/read",
                    {"threadId": prior_thread_id, "includeTurns": True},
                    timeout=remaining_timeout(),
                )
                thread_id = self._verified_continuation_thread(
                    thread_response,
                    expected_thread_id=prior_thread_id,
                    expected_turn_id=prior_turn_id,
                )
            except AgentRuntimeError:
                return self._rejected("runtime.continuation_invalid")
            except CodexAppServerClientError:
                return self._rejected("runtime.continuation_unavailable")
            except (OSError, TypeError, ValueError):
                return self._rejected("runtime.continuation_invalid")
        try:
            turn_response = client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt}],
                    "cwd": str(self.workspace_root),
                    "approvalPolicy": "never",
                    "sandboxPolicy": {
                        "type": "workspaceWrite",
                        "writableRoots": [str(self.workspace_root)],
                        "networkAccess": False,
                    },
                },
                timeout=remaining_timeout(),
            )
        except CodexAppServerClientError:
            return self._unknown(
                "runtime.submission_unknown",
                execution_identity=execution_identity,
            )
        try:
            turn = self._verified_turn(turn_response)
            runtime_ref = _runtime_reference(thread_id, turn["id"])
        except (TypeError, ValueError):
            return self._unknown(
                "runtime.start_unverified",
                execution_identity=execution_identity,
            )
        run = AgentRun(
            id=context.mentat_run_id or "",
            task_id=task.id,
            agent_id=context.agent_id,
            runtime_type=self.runtime_type,
            status=_TURN_STATUSES[str(turn["status"])],
        )
        return SubmissionOutcome(
            SubmissionDisposition.ACCEPTED,
            run=run,
            runtime_run_ref=runtime_ref,
            execution_identity=execution_identity,
        )

    @staticmethod
    def _bound_context(
        run_id: str,
        context: RuntimeContext | None,
    ) -> tuple[str, str, RuntimeContext]:
        if context is None or context.mentat_run_id is None:
            raise AgentRuntimeError("runtime.identity_context_required")
        if context.runtime_agent_ref != CODEX_DEFAULT_BINDING or context.runtime_run_ref != run_id:
            raise AgentRuntimeError("runtime.identity_mismatch")
        thread_id, turn_id = _split_runtime_reference(run_id)
        return thread_id, turn_id, context

    def _turn_snapshot(
        self, run_id: str, *, context: RuntimeContext | None
    ) -> tuple[Mapping[str, Any], RuntimeContext]:
        thread_id, turn_id, bound = self._bound_context(run_id, context)
        try:
            response = self._require_client().request(
                "thread/read", {"threadId": thread_id, "includeTurns": True}
            )
        except CodexAppServerClientError as exc:
            raise AgentRuntimeError("runtime.status_unavailable") from exc
        if not isinstance(response, Mapping) or not isinstance(response.get("thread"), Mapping):
            raise AgentRuntimeError("runtime.status_invalid")
        thread = response["thread"]
        turns = thread.get("turns")
        if thread.get("id") != thread_id or not isinstance(turns, list) or len(turns) > 1024:
            raise AgentRuntimeError("runtime.status_invalid")
        matches = [
            turn
            for turn in turns
            if isinstance(turn, Mapping) and turn.get("id") == turn_id
        ]
        if len(matches) != 1 or matches[0].get("status") not in _TURN_STATUSES:
            raise AgentRuntimeError("runtime.status_invalid")
        return matches[0], bound

    def get_status(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> AgentRun:
        turn, bound = self._turn_snapshot(run_id, context=context)
        return AgentRun(
            id=bound.mentat_run_id or "",
            task_id=bound.task_id,
            agent_id=bound.agent_id,
            runtime_type=self.runtime_type,
            status=_TURN_STATUSES[str(turn["status"])],
        )

    def send_message(
        self, run_id: str, message: str, *, context: RuntimeContext | None = None
    ) -> None:
        thread_id, turn_id, _bound = self._bound_context(run_id, context)
        if (
            not isinstance(message, str)
            or not message.strip()
            or "\x00" in message
            or len(message.strip()) > 20_000
        ):
            raise AgentRuntimeError("runtime.message_invalid")
        try:
            response = self._require_client().request(
                "turn/steer",
                {
                    "threadId": thread_id,
                    "expectedTurnId": turn_id,
                    "input": [{"type": "text", "text": message.strip()}],
                },
            )
        except CodexAppServerClientError as exc:
            raise AgentRuntimeError(
                "runtime.message_partial"
                if exc.uncertain
                else "runtime.message_failed"
            ) from exc
        if not isinstance(response, Mapping) or response.get("turnId") != turn_id:
            # The App Server returned after the side-effecting request, but the
            # receipt does not prove which turn was steered.
            raise AgentRuntimeError("runtime.message_partial")

    def stop(self, run_id: str, *, context: RuntimeContext | None = None) -> None:
        thread_id, turn_id, bound = self._bound_context(run_id, context)
        try:
            response = self._require_client().request(
                "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}
            )
        except CodexAppServerClientError as exc:
            raise AgentRuntimeError("runtime.stop_failed") from exc
        if not isinstance(response, Mapping):
            raise AgentRuntimeError("runtime.stop_failed")
        for attempt in range(25):
            status = self.get_status(run_id, context=bound).status
            if status == RunStatus.STOPPED:
                return
            if status in {RunStatus.COMPLETED, RunStatus.FAILED}:
                break
            if attempt < 24:
                time.sleep(0.2)
        raise AgentRuntimeError("runtime.stop_unverified")

    @staticmethod
    def _item_is_unstable(item: Mapping[str, Any]) -> bool:
        status = item.get("status")
        if not isinstance(status, str):
            return False
        normalized = re.sub(r"[^a-z]", "", status.lower())
        return normalized in _IN_PROGRESS_ITEM_STATUSES

    @staticmethod
    def _item_event_type(item_type: str) -> tuple[AgentEventType, str]:
        if item_type in {
            "commandExecution",
            "mcpToolCall",
            "dynamicToolCall",
            "collabAgentToolCall",
            "webSearch",
        }:
            return AgentEventType.TOOL_COMPLETED, "Codex tool completed"
        if item_type in {"fileChange", "imageGeneration"}:
            return AgentEventType.ARTIFACT_CREATED, "Codex created an artifact"
        if item_type == "agentMessage":
            return AgentEventType.MESSAGE, "Codex responded"
        return AgentEventType.MESSAGE, "Codex activity updated"

    @staticmethod
    def _event_id(runtime_ref: str, source_id: str, event_type: AgentEventType) -> str:
        digest = hashlib.sha256(
            f"codex\0{runtime_ref}\0{source_id}\0{event_type.value}".encode("utf-8")
        ).hexdigest()[:32]
        return f"codex_{digest}"

    def stream_events(
        self,
        run_id: str,
        after_sequence: int = 0,
        *,
        context: RuntimeContext | None = None,
    ):
        if type(after_sequence) is not int or not 0 <= after_sequence <= 10**9:
            raise AgentRuntimeError("runtime.events_invalid")
        turn, bound = self._turn_snapshot(run_id, context=context)
        items = turn.get("items")
        if not isinstance(items, list) or len(items) > MAXIMUM_TURN_ITEMS:
            raise AgentRuntimeError("runtime.events_invalid")
        started_at = _iso_timestamp(turn.get("startedAt"), code="runtime.events_invalid")
        events: list[AgentEvent] = [
            AgentEvent(
                id=self._event_id(run_id, "start", AgentEventType.RUN_STARTED),
                run_id=bound.mentat_run_id or "",
                sequence=1,
                type=AgentEventType.RUN_STARTED,
                occurred_at=started_at,
                summary="Codex run started",
            )
        ]
        seen_ids: set[str] = set()
        for item in items:
            if not isinstance(item, Mapping):
                raise AgentRuntimeError("runtime.events_invalid")
            item_id = item.get("id")
            item_type = item.get("type")
            if (
                not isinstance(item_id, str)
                or _ITEM_ID.fullmatch(item_id) is None
                or item_id in seen_ids
                or not isinstance(item_type, str)
                or len(item_type) > 80
            ):
                raise AgentRuntimeError("runtime.events_invalid")
            if self._item_is_unstable(item):
                break
            seen_ids.add(item_id)
            event_type, summary = self._item_event_type(item_type)
            content = None
            if item_type == "agentMessage":
                from agent_run_history import bounded_public_excerpt

                content = bounded_public_excerpt(item.get("text"), 20_000)[0]
                if not content:
                    raise AgentRuntimeError("runtime.events_invalid")
            events.append(
                AgentEvent(
                    id=self._event_id(run_id, item_id, event_type),
                    run_id=bound.mentat_run_id or "",
                    sequence=len(events) + 1,
                    type=event_type,
                    occurred_at=started_at,
                    summary=summary,
                    content=content,
                )
            )
        status = _TURN_STATUSES[str(turn["status"])]
        if status in _TERMINAL_STATUSES and len(seen_ids) == len(items):
            completed_at = _iso_timestamp(
                turn.get("completedAt"), code="runtime.events_invalid"
            )
            terminal_type = {
                RunStatus.COMPLETED: AgentEventType.RUN_COMPLETED,
                RunStatus.STOPPED: AgentEventType.RUN_STOPPED,
                RunStatus.FAILED: AgentEventType.RUN_FAILED,
            }[status]
            events.append(
                AgentEvent(
                    id=self._event_id(run_id, "terminal", terminal_type),
                    run_id=bound.mentat_run_id or "",
                    sequence=len(events) + 1,
                    type=terminal_type,
                    occurred_at=completed_at,
                    summary={
                        RunStatus.COMPLETED: "Codex run completed",
                        RunStatus.STOPPED: "Codex run stopped",
                        RunStatus.FAILED: "Codex run failed",
                    }[status],
                )
            )
        return tuple(event for event in events if event.sequence > after_sequence)

    def capabilities_for_run(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> frozenset[str]:
        status = self.get_status(run_id, context=context).status
        return _TERMINAL_CAPABILITIES if status in _TERMINAL_STATUSES else self.capabilities

    def pending_action(
        self, run_id: str, *, context: RuntimeContext | None = None
    ) -> PendingRunAction:
        self._bound_context(run_id, context)
        raise AgentRuntimeError("runtime.action_unavailable")

    def respond_to_action(
        self,
        run_id: str,
        action: PendingRunAction,
        response: RunActionResponse,
        *,
        context: RuntimeContext | None = None,
    ) -> None:
        self._bound_context(run_id, context)
        raise AgentRuntimeError("runtime.action_unavailable")


__all__ = [
    "CODEX_DEFAULT_BINDING",
    "CODEX_RUNTIME_TYPE",
    "CodexAppServerClient",
    "CodexAppServerClientError",
    "CodexRuntime",
    "codex_app_server_command",
    "codex_binding_is_valid",
    "codex_child_environment",
    "find_codex_command",
]
