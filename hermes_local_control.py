"""Private loopback control channel for local Hermes Console runs.

The legacy local Console adapter launches ``hermes chat -q``.  That interface
is intentionally one-shot and has no supported way to address the in-memory
agent after launch.  Hermes' headless backend exposes the same fixed JSON-RPC
surface used by its desktop client, including an active-turn-aware
``session.redirect`` operation.  This module owns that backend process and its
authenticated loopback WebSocket; neither the credential nor the upstream
session identifier crosses the browser boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
from tempfile import TemporaryDirectory
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import quote

from data_layout import (
    _absolute_without_following,
    _is_redirecting_entry,
    _redirected_component_issue,
    _secure_directory,
)


MAXIMUM_PROTOCOL_MESSAGE_BYTES = 8 * 1024 * 1024
MAXIMUM_PROTOCOL_REQUEST_BYTES = 256 * 1024
DEFAULT_STARTUP_TIMEOUT_SECONDS = 25.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 15.0

_PROFILE_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")


class LocalHermesControlError(RuntimeError):
    """Bounded local-control failure with delivery certainty."""

    def __init__(
        self,
        code: str,
        *,
        uncertain: bool = False,
        remote_code: int | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.uncertain = bool(uncertain)
        self.remote_code = remote_code


@dataclass(frozen=True)
class LocalHermesTerminal:
    status: str
    text: str
    usage: Mapping[str, Any] | None = None


@dataclass
class _PendingResponse:
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: LocalHermesControlError | None = None
    sent: bool = False


def local_control_dependencies_available(command_path: object) -> bool:
    """Return whether this installation can attempt the fixed control path."""

    if not isinstance(command_path, str) or not command_path:
        return False
    try:
        command = Path(command_path)
        if not command.is_absolute() or not command.is_file():
            return False
        from websockets.sync.client import connect as _connect  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def _ensure_private_runtime_root(path: Path) -> Path:
    """Create one owner-only directory without following redirected entries."""

    absolute = _absolute_without_following(Path(path))
    if (
        not _secure_directory(absolute)
        or _redirected_component_issue(absolute, "hermes_control") is not None
    ):
        raise LocalHermesControlError("local_control_storage_unsafe")
    try:
        details = os.lstat(absolute)
        resolved = absolute.resolve(strict=True)
        resolved_parent = absolute.parent.resolve(strict=True)
    except OSError as exc:
        raise LocalHermesControlError("local_control_storage_unsafe") from exc
    if (
        _is_redirecting_entry(details)
        or not stat.S_ISDIR(details.st_mode)
        or resolved.parent != resolved_parent
        or (
            os.name == "posix"
            and (
                details.st_uid != os.getuid()
                or stat.S_IMODE(details.st_mode) != 0o700
            )
        )
    ):
        raise LocalHermesControlError("local_control_storage_unsafe")
    return resolved


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
        # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
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


class LocalHermesControlClient:
    """Own one profile-scoped Hermes backend and exact live session."""

    def __init__(
        self,
        *,
        command_path: str,
        profile_id: str,
        hermes_home: Path,
        cwd: Path,
        runtime_root: Path,
        shared_bin: Path | None = None,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
        popen_factory: Callable[..., subprocess.Popen] | None = None,
        connect_factory: Callable[..., Any] | None = None,
        startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
        request_timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ):
        command = Path(command_path)
        if (
            not command.is_absolute()
            or not _PROFILE_ID.fullmatch(profile_id)
            or not Path(cwd).is_absolute()
            or not Path(runtime_root).is_absolute()
        ):
            raise LocalHermesControlError("local_control_invalid")
        self.command_path = str(command)
        self.profile_id = profile_id
        self.hermes_home = Path(hermes_home)
        self.cwd = Path(cwd)
        self.runtime_root = Path(runtime_root)
        self.shared_bin = Path(shared_bin) if shared_bin is not None else None
        self._event_callback = event_callback
        self._popen_factory = popen_factory or subprocess.Popen
        self._connect_factory = connect_factory
        self._startup_timeout = max(1.0, float(startup_timeout_seconds))
        self._request_timeout = max(1.0, float(request_timeout_seconds))

        self._process: subprocess.Popen | None = None
        self._connection: Any = None
        self._temporary: TemporaryDirectory[str] | None = None
        self._reader: threading.Thread | None = None
        self._stream_readers: list[threading.Thread] = []
        self._closed = threading.Event()
        self._gateway_ready = threading.Event()
        self._terminal_ready = threading.Event()
        self._terminal: LocalHermesTerminal | None = None
        self._terminal_error: LocalHermesControlError | None = None
        self._last_event_error = ""
        self._pending_lock = threading.Lock()
        self._pending: dict[int, _PendingResponse] = {}
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._next_request_id = 0
        self._submitted = False
        self._active_turn = False
        self._live_session_id: str | None = None
        self._durable_session_id: str | None = None
        self._stderr_tail: list[str] = []

    @property
    def process(self) -> subprocess.Popen | None:
        return self._process

    @property
    def durable_session_id(self) -> str | None:
        with self._state_lock:
            return self._durable_session_id

    @property
    def live_session_id(self) -> str | None:
        with self._state_lock:
            return self._live_session_id

    def can_steer(self, session_id: object) -> bool:
        with self._state_lock:
            return (
                not self._closed.is_set()
                and self._submitted
                and self._active_turn
                and isinstance(session_id, str)
                and session_id == self._live_session_id
            )

    def start(self) -> None:
        if (
            self._closed.is_set()
            or self._process is not None
            or self._connection is not None
        ):
            raise LocalHermesControlError("local_control_invalid")
        if not local_control_dependencies_available(self.command_path):
            raise LocalHermesControlError("local_control_unavailable")

        try:
            runtime_root = _ensure_private_runtime_root(self.runtime_root)
            with self._lifecycle_lock:
                if self._closed.is_set():
                    raise LocalHermesControlError("local_control_connection_lost")
                self._temporary = TemporaryDirectory(
                    prefix="hermes-control-",
                    dir=str(runtime_root),
                )
                temporary_path = Path(self._temporary.name)
            if os.name != "nt":
                temporary_path.chmod(0o700)
            ready_path = temporary_path / "ready.json"
            token = secrets.token_urlsafe(32)
            environment = os.environ.copy()
            environment["HERMES_HOME"] = str(self.hermes_home)
            environment["PYTHONUNBUFFERED"] = "1"
            environment["HERMES_DASHBOARD_SESSION_TOKEN"] = token
            environment["HERMES_DESKTOP_READY_FILE"] = str(ready_path)
            if self.shared_bin is not None:
                current_path = environment.get("PATH") or ""
                entries = current_path.split(os.pathsep) if current_path else []
                if str(self.shared_bin) not in entries:
                    environment["PATH"] = os.pathsep.join(
                        [str(self.shared_bin), *entries]
                    )
            command = [
                self.command_path,
                "-p",
                self.profile_id,
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--isolated",
            ]
            process_options: dict[str, Any] = {}
            if os.name == "nt":
                process_options["creationflags"] = getattr(
                    subprocess,
                    "CREATE_NEW_PROCESS_GROUP",
                    0,
                )
            else:
                process_options["start_new_session"] = True
            with self._lifecycle_lock:
                if self._closed.is_set():
                    raise LocalHermesControlError("local_control_connection_lost")
                process = self._popen_factory(
                    command,
                    cwd=str(self.cwd),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    **process_options,
                )
                self._process = process
                try:
                    if os.name == "nt":
                        process._mentat_windows_job = _attach_windows_kill_job(
                            process
                        )
                    elif type(getattr(process, "pid", None)) is int:
                        process._mentat_process_group = process.pid
                except (AttributeError, OSError, TypeError, ValueError) as exc:
                    raise LocalHermesControlError(
                        "local_control_startup_failed"
                    ) from exc
            self._start_stream_drains()
            port = self._wait_for_ready_port(ready_path)
            connect_factory = self._connect_factory
            if connect_factory is None:
                from websockets.sync.client import connect

                connect_factory = connect
            uri = (
                f"ws://127.0.0.1:{port}/api/ws?token="
                f"{quote(token, safe='')}"
            )
            connection = connect_factory(
                uri,
                open_timeout=5,
                close_timeout=1,
                max_size=MAXIMUM_PROTOCOL_MESSAGE_BYTES,
                proxy=None,
            )
            with self._lifecycle_lock:
                if self._closed.is_set():
                    try:
                        connection.close()
                    except Exception:
                        pass
                    raise LocalHermesControlError(
                        "local_control_connection_lost"
                    )
                self._connection = connection
            self._reader = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name="mentat-hermes-control-reader",
            )
            self._reader.start()
            if not self._gateway_ready.wait(timeout=5):
                raise LocalHermesControlError("local_control_startup_failed")
            self._probe_redirect()
        except LocalHermesControlError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise LocalHermesControlError("local_control_startup_failed") from exc

    def open_session(self, resume_session_id: str | None) -> tuple[str, str]:
        if resume_session_id is not None and not _SESSION_ID.fullmatch(
            resume_session_id
        ):
            raise LocalHermesControlError("local_control_session_invalid")
        if resume_session_id:
            result = self._request(
                "session.resume",
                {
                    "session_id": resume_session_id,
                    "cols": 80,
                    "source": "mentat",
                    "close_on_disconnect": True,
                },
            )
            if not isinstance(result, Mapping):
                raise LocalHermesControlError("local_control_protocol_invalid")
            live_id = result.get("session_id")
            resumed_id = result.get("resumed")
            session_key = result.get("session_key")
            if (
                not isinstance(resumed_id, str)
                or not isinstance(session_key, str)
                or resumed_id != session_key
            ):
                raise LocalHermesControlError("local_control_protocol_invalid")
            durable_id = resumed_id
        else:
            result = self._request(
                "session.create",
                {
                    "cols": 80,
                    "cwd": str(self.cwd),
                    "source": "mentat",
                    "close_on_disconnect": True,
                },
            )
            if not isinstance(result, Mapping):
                raise LocalHermesControlError("local_control_protocol_invalid")
            live_id = result.get("session_id")
            durable_id = result.get("stored_session_id")
        if (
            not isinstance(live_id, str)
            or not isinstance(durable_id, str)
            or not _SESSION_ID.fullmatch(live_id)
            or not _SESSION_ID.fullmatch(durable_id)
        ):
            raise LocalHermesControlError("local_control_protocol_invalid")
        with self._state_lock:
            self._live_session_id = live_id
            self._durable_session_id = durable_id
        return live_id, durable_id

    def attach_image(self, session_id: str, image_path: Path) -> None:
        if not self._session_matches(session_id):
            raise LocalHermesControlError("local_control_session_invalid")
        path = Path(image_path)
        if not path.is_absolute():
            raise LocalHermesControlError("local_control_session_invalid")
        result = self._request(
            "image.attach",
            {"session_id": session_id, "path": str(path)},
        )
        if not isinstance(result, Mapping) or result.get("attached") is not True:
            raise LocalHermesControlError("local_control_request_rejected")

    def submit_prompt(self, session_id: str, text: str) -> None:
        if (
            not self._session_matches(session_id)
            or not isinstance(text, str)
            or not text.strip()
            or "\x00" in text
        ):
            raise LocalHermesControlError("local_control_session_invalid")
        with self._state_lock:
            self._submitted = True
            self._active_turn = False
            self._terminal = None
            self._terminal_error = None
            self._last_event_error = ""
            self._terminal_ready.clear()
        try:
            result = self._request(
                "prompt.submit",
                {"session_id": session_id, "text": text},
            )
        except LocalHermesControlError as exc:
            with self._state_lock:
                active_turn = self._active_turn
            if (
                exc.uncertain
                or active_turn
                or exc.remote_code is None
                or exc.remote_code >= 5000
            ):
                raise LocalHermesControlError(
                    "local_control_prompt_unverified",
                    uncertain=True,
                    remote_code=exc.remote_code,
                ) from exc
            with self._state_lock:
                self._submitted = False
            raise
        if not isinstance(result, Mapping) or result.get("status") != "streaming":
            raise LocalHermesControlError(
                "local_control_prompt_unverified",
                uncertain=True,
            )

    def redirect(self, session_id: str, text: str) -> None:
        """Deliver guidance only if Hermes confirms an active-turn redirect."""

        if (
            not self.can_steer(session_id)
            or not isinstance(text, str)
            or not text.strip()
            or "\x00" in text
        ):
            raise LocalHermesControlError("local_control_steer_unavailable")
        try:
            result = self._request(
                "session.redirect",
                {"session_id": session_id, "text": text.strip()},
            )
        except LocalHermesControlError as exc:
            if exc.remote_code in {4002, 4006, 4007, 4010}:
                raise LocalHermesControlError(
                    "local_control_steer_unavailable",
                    remote_code=exc.remote_code,
                ) from exc
            raise LocalHermesControlError(
                "local_control_steer_unverified",
                uncertain=True,
                remote_code=exc.remote_code,
            ) from exc
        if not isinstance(result, Mapping):
            raise LocalHermesControlError(
                "local_control_steer_unverified",
                uncertain=True,
            )
        status = result.get("status")
        echoed = result.get("text")
        if status == "redirected" and echoed == text.strip():
            return
        if status == "rejected":
            raise LocalHermesControlError("local_control_steer_rejected")
        # A future/incompatible Hermes build could report a queued status. That
        # is not Mentat's exact-Run contract and may already have changed state.
        raise LocalHermesControlError(
            "local_control_steer_unverified",
            uncertain=True,
        )

    def wait_terminal(
        self,
        *,
        should_abort: Callable[[], bool] | None = None,
    ) -> LocalHermesTerminal:
        while not self._terminal_ready.wait(timeout=1):
            if should_abort is not None and should_abort():
                raise LocalHermesControlError(
                    "local_control_aborted",
                    uncertain=self._submitted,
                )
            process = self._process
            if process is not None and process.poll() is not None:
                raise LocalHermesControlError(
                    "local_control_connection_lost",
                    uncertain=self._submitted,
                )
            if self._closed.is_set():
                raise LocalHermesControlError(
                    "local_control_connection_lost",
                    uncertain=self._submitted,
                )
        with self._state_lock:
            error = self._terminal_error
            terminal = self._terminal
        if error is not None:
            raise error
        if terminal is None:
            raise LocalHermesControlError(
                "local_control_terminal_unverified",
                uncertain=self._submitted,
            )
        return terminal

    def close(self) -> None:
        self._closed.set()
        with self._state_lock:
            self._active_turn = False
        with self._lifecycle_lock:
            connection = self._connection
            self._connection = None
            process = self._process
            self._process = None
            temporary = self._temporary
            self._temporary = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        self._fail_pending("local_control_connection_lost")
        self._terminate_process(process)
        if temporary is not None:
            try:
                temporary.cleanup()
            except OSError:
                pass

    def _session_matches(self, session_id: object) -> bool:
        with self._state_lock:
            return (
                isinstance(session_id, str)
                and session_id == self._live_session_id
                and not self._closed.is_set()
            )

    def _probe_redirect(self) -> None:
        try:
            self._request(
                "session.redirect",
                {"session_id": "", "text": ""},
                timeout=5,
            )
        except LocalHermesControlError as exc:
            if not exc.uncertain and exc.remote_code == 4002:
                return
            raise LocalHermesControlError("local_control_steer_unavailable") from exc
        raise LocalHermesControlError("local_control_protocol_invalid")

    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        connection = self._connection
        if connection is None or self._closed.is_set():
            raise LocalHermesControlError("local_control_connection_lost")
        with self._pending_lock:
            self._next_request_id += 1
            request_id = self._next_request_id
            pending = _PendingResponse()
            self._pending[request_id] = pending
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(payload.encode("utf-8")) > MAXIMUM_PROTOCOL_REQUEST_BYTES:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise LocalHermesControlError("local_control_request_invalid")
        try:
            with self._write_lock:
                connection.send(payload)
                pending.sent = True
        except Exception as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise LocalHermesControlError(
                "local_control_connection_lost",
                uncertain=pending.sent,
            ) from exc
        wait_seconds = self._request_timeout if timeout is None else max(1.0, timeout)
        if not pending.event.wait(timeout=wait_seconds):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise LocalHermesControlError(
                "local_control_request_timeout",
                uncertain=pending.sent,
            )
        with self._pending_lock:
            self._pending.pop(request_id, None)
        if pending.error is not None:
            raise pending.error
        return pending.result

    def _reader_loop(self) -> None:
        connection = self._connection
        if connection is None:
            return
        try:
            while not self._closed.is_set():
                try:
                    raw = connection.recv(timeout=1)
                except TimeoutError:
                    process = self._process
                    if process is not None and process.poll() is not None:
                        break
                    continue
                if isinstance(raw, bytes):
                    if len(raw) > MAXIMUM_PROTOCOL_MESSAGE_BYTES:
                        raise ValueError("oversized protocol message")
                    raw = raw.decode("utf-8")
                if (
                    not isinstance(raw, str)
                    or len(raw.encode("utf-8")) > MAXIMUM_PROTOCOL_MESSAGE_BYTES
                ):
                    raise ValueError("invalid protocol message")
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError("invalid protocol message")
                if message.get("method") == "event":
                    self._handle_event(message.get("params"))
                    continue
                request_id = message.get("id")
                if type(request_id) is not int:
                    continue
                with self._pending_lock:
                    pending = self._pending.get(request_id)
                if pending is None:
                    continue
                if "error" in message:
                    error = message.get("error")
                    remote_code = (
                        error.get("code")
                        if isinstance(error, Mapping)
                        and type(error.get("code")) is int
                        else None
                    )
                    pending.error = LocalHermesControlError(
                        "local_control_request_rejected",
                        remote_code=remote_code,
                    )
                elif "result" in message:
                    pending.result = message.get("result")
                else:
                    pending.error = LocalHermesControlError(
                        "local_control_protocol_invalid"
                    )
                pending.event.set()
        except Exception:
            pass
        finally:
            if not self._closed.is_set():
                with self._state_lock:
                    self._active_turn = False
                    if self._submitted and self._terminal_error is None and self._terminal is None:
                        self._terminal_error = LocalHermesControlError(
                            "local_control_connection_lost",
                            uncertain=True,
                        )
                        self._terminal_ready.set()
                self._fail_pending("local_control_connection_lost")

    def _handle_event(self, params: object) -> None:
        if not isinstance(params, Mapping):
            return
        event_type = params.get("type")
        if not isinstance(event_type, str) or not event_type or len(event_type) > 80:
            return
        session_id = params.get("session_id")
        payload = params.get("payload")
        safe_payload = dict(payload) if isinstance(payload, Mapping) else {}
        if event_type == "gateway.ready":
            self._gateway_ready.set()
        matches = self._session_matches(session_id)
        if matches and event_type == "message.start":
            with self._state_lock:
                self._active_turn = True
        elif matches and event_type == "message.complete":
            raw_status = safe_payload.get("status")
            status = (
                "completed"
                if raw_status in {None, "complete"}
                else "cancelled"
                if raw_status == "interrupted"
                else "failed"
            )
            text = safe_payload.get("text")
            usage = safe_payload.get("usage")
            with self._state_lock:
                self._active_turn = False
                self._terminal = LocalHermesTerminal(
                    status=status,
                    text=text if isinstance(text, str) else "",
                    usage=dict(usage) if isinstance(usage, Mapping) else None,
                )
                self._terminal_ready.set()
        elif matches and event_type == "error":
            message = safe_payload.get("message")
            with self._state_lock:
                self._active_turn = False
                self._last_event_error = (
                    str(message)[:500] if isinstance(message, str) else ""
                )
                self._terminal_error = LocalHermesControlError(
                    "local_control_run_failed"
                )
                self._terminal_ready.set()
        callback = self._event_callback
        if callback is not None:
            try:
                callback(
                    {
                        "type": event_type,
                        "session_id": session_id,
                        "payload": safe_payload,
                    }
                )
            except Exception:
                pass

    def _fail_pending(self, code: str) -> None:
        with self._pending_lock:
            pending_items = tuple(self._pending.values())
            self._pending.clear()
        for pending in pending_items:
            pending.error = LocalHermesControlError(
                code,
                uncertain=pending.sent,
            )
            pending.event.set()

    def _start_stream_drains(self) -> None:
        process = self._process
        if process is None:
            return

        def drain(stream: Any, *, stderr: bool) -> None:
            if stream is None:
                return
            try:
                for line in stream:
                    if stderr:
                        cleaned = str(line).strip()
                        if cleaned:
                            self._stderr_tail.append(cleaned[:500])
                            del self._stderr_tail[:-20]
            except (OSError, ValueError):
                pass

        for stream, is_stderr, name in (
            (process.stdout, False, "stdout"),
            (process.stderr, True, "stderr"),
        ):
            reader = threading.Thread(
                target=drain,
                args=(stream,),
                kwargs={"stderr": is_stderr},
                daemon=True,
                name=f"mentat-hermes-control-{name}",
            )
            reader.start()
            self._stream_readers.append(reader)

    def _wait_for_ready_port(self, ready_path: Path) -> int:
        deadline = time.monotonic() + self._startup_timeout
        while time.monotonic() < deadline:
            process = self._process
            if (
                self._closed.is_set()
                or process is None
                or process.poll() is not None
            ):
                raise LocalHermesControlError("local_control_startup_failed")
            try:
                return self._read_ready_port(ready_path)
            except FileNotFoundError:
                time.sleep(0.05)
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise LocalHermesControlError(
                    "local_control_protocol_invalid"
                ) from exc
        raise LocalHermesControlError("local_control_startup_failed")

    @staticmethod
    def _read_ready_port(path: Path) -> int:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_size > 256:
                raise ValueError("invalid ready file")
            if hasattr(os, "getuid") and details.st_uid != os.getuid():
                raise ValueError("invalid ready file owner")
            raw = os.read(descriptor, 257)
        finally:
            os.close(descriptor)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"port"}:
            raise ValueError("invalid ready payload")
        port = payload.get("port")
        if type(port) is not int or not (1 <= port <= 65_535):
            raise ValueError("invalid ready port")
        return port

    @staticmethod
    def _terminate_process(process: subprocess.Popen | None) -> None:
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
                    # Always reap descendants that ignored SIGTERM, even when
                    # the backend leader exited promptly.
                    os.killpg(process_group, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    pass
            if process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    pass
            for stream in (process.stdout, process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except (OSError, ValueError):
                    pass


__all__ = [
    "LocalHermesControlClient",
    "LocalHermesControlError",
    "LocalHermesTerminal",
    "local_control_dependencies_available",
]
