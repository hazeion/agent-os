"""Owner-private remote Hermes selection, discovery, and fixed Runs operations.

This module deliberately exposes no generic request method. One validated
operator-granted origin and one private credential authorize only the fixed
discovery paths plus capability-gated run submission, status, SSE, and stop.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import threading
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from data_layout import (
    _open_directory_no_follow,
    _windows_close_handle,
    _windows_open_directory_chain,
)
from json_store import read_json, write_json_atomic
from private_state import ensure_private_root, private_root, private_state_lock


CONNECTION_SCHEMA_VERSION = 1
CONNECTION_FILE_NAME = "remote-hermes-connection-v1.json"
MAX_CONNECTION_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_RUN_EVENT_BYTES = 256 * 1024
MAX_RUN_STREAM_BYTES = 4 * 1024 * 1024
MAX_RUN_EVENTS = 5_000
RUN_STREAM_READ_TIMEOUT_SECONDS = 35.0
RUN_STREAM_MAX_SECONDS = 30 * 60.0
DEFAULT_TIMEOUT_SECONDS = 5.0
FIXED_PATHS = frozenset({"/health", "/health/detailed", "/v1/capabilities"})
_RUN_ID = re.compile(r"run_[0-9a-f]{32}\Z")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+()-]{0,79}$")
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/@-]{0,159}$")
_KNOWN_BOOLEAN_FEATURES = frozenset(
    {
        "chat_completions",
        "chat_completions_streaming",
        "responses_api",
        "responses_streaming",
        "run_submission",
        "run_status",
        "run_events_sse",
        "run_stop",
        "run_approval_response",
        "tool_progress_events",
        "approval_events",
        "session_resources",
        "session_chat",
        "session_chat_streaming",
        "session_fork",
        "skills_api",
        "jobs_admin",
        "admin_config_rw",
    }
)
_REQUIRED_ENDPOINTS = {
    "health": ("GET", "/health"),
    "health_detailed": ("GET", "/health/detailed"),
}
_RUN_ENDPOINTS = {
    "runs": ("POST", "/v1/runs", "run_submission"),
    "run_status": ("GET", "/v1/runs/{run_id}", "run_status"),
    "run_events": ("GET", "/v1/runs/{run_id}/events", "run_events_sse"),
    "run_stop": ("POST", "/v1/runs/{run_id}/stop", "run_stop"),
}
_RUN_STATUSES = frozenset(
    {
        "queued",
        "running",
        "waiting_for_approval",
        "stopping",
        "completed",
        "failed",
        "cancelled",
    }
)
_CONFIRMATION_SECRET = os.urandom(32)
_PREVIEW_TTL_SECONDS = 300.0
_MAX_PREVIEW_GRANTS = 256
_PREVIEW_LOCK = threading.Lock()
_PREVIEW_GRANTS: dict[str, tuple[float, bytes]] = {}


def _windows_current_user_sid():
    """Return a live buffer plus the current process user's SID pointer."""

    import ctypes
    from ctypes import wintypes

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", wintypes.LPVOID), ("Attributes", wintypes.DWORD)]

    class TOKEN_USER(ctypes.Structure):
        _fields_ = [("User", SID_AND_ATTRIBUTES)]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.IsValidSid.argtypes = [wintypes.LPVOID]
    advapi32.IsValidSid.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise OSError(ctypes.get_last_error(), "OpenProcessToken failed")
    try:
        needed = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not needed.value:
            raise OSError(ctypes.get_last_error(), "GetTokenInformation size failed")
        buffer = ctypes.create_string_buffer(needed.value)
        if not advapi32.GetTokenInformation(
            token,
            1,
            buffer,
            needed,
            ctypes.byref(needed),
        ):
            raise OSError(ctypes.get_last_error(), "GetTokenInformation failed")
        sid = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents.User.Sid
        if not advapi32.IsValidSid(sid):
            raise OSError("current user SID is invalid")
        return buffer, sid
    finally:
        kernel32.CloseHandle(token)


def _windows_set_owner_only(path: Path, *, directory: bool) -> None:
    """Apply and read back a protected one-user DACL using native Win32 APIs."""

    import ctypes
    from ctypes import wintypes

    class TRUSTEE_W(ctypes.Structure):
        _fields_ = [
            ("pMultipleTrustee", wintypes.LPVOID),
            ("MultipleTrusteeOperation", wintypes.DWORD),
            ("TrusteeForm", wintypes.DWORD),
            ("TrusteeType", wintypes.DWORD),
            ("ptstrName", wintypes.LPVOID),
        ]

    class EXPLICIT_ACCESS_W(ctypes.Structure):
        _fields_ = [
            ("grfAccessPermissions", wintypes.DWORD),
            ("grfAccessMode", wintypes.DWORD),
            ("grfInheritance", wintypes.DWORD),
            ("Trustee", TRUSTEE_W),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.SetEntriesInAclW.argtypes = [
        wintypes.ULONG,
        ctypes.POINTER(EXPLICIT_ACCESS_W),
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi32.SetEntriesInAclW.restype = wintypes.DWORD
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    _sid_buffer, sid = _windows_current_user_sid()
    access = EXPLICIT_ACCESS_W()
    access.grfAccessPermissions = 0x001F01FF  # FILE_ALL_ACCESS
    access.grfAccessMode = 2  # SET_ACCESS
    access.grfInheritance = 0x3 if directory else 0  # container + object inherit
    access.Trustee.TrusteeForm = 0  # TRUSTEE_IS_SID
    access.Trustee.TrusteeType = 1  # TRUSTEE_IS_USER
    access.Trustee.ptstrName = sid
    acl = wintypes.LPVOID()
    result = advapi32.SetEntriesInAclW(1, ctypes.byref(access), None, ctypes.byref(acl))
    if result != 0:
        raise OSError(result, "SetEntriesInAclW failed")
    try:
        result = advapi32.SetNamedSecurityInfoW(
            ctypes.c_wchar_p(os.fspath(path)),
            1,  # SE_FILE_OBJECT
            0x00000001 | 0x00000004 | 0x80000000,  # owner + DACL + protected DACL
            sid,
            None,
            acl,
            None,
        )
        if result != 0:
            raise OSError(result, "SetNamedSecurityInfoW failed")
    finally:
        if acl:
            kernel32.LocalFree(acl)
    if not _windows_owner_only(path, directory=directory):
        raise OSError("owner-only Windows security descriptor did not verify")


def _windows_owner_only(path: Path, *, directory: bool) -> bool:
    """Verify owner SID, protected DACL, and the sole full-control allow ACE."""

    import ctypes
    from ctypes import wintypes

    class ACL(ctypes.Structure):
        _fields_ = [
            ("AclRevision", wintypes.BYTE),
            ("Sbz1", wintypes.BYTE),
            ("AclSize", wintypes.WORD),
            ("AceCount", wintypes.WORD),
            ("Sbz2", wintypes.WORD),
        ]

    class ACE_HEADER(ctypes.Structure):
        _fields_ = [
            ("AceType", wintypes.BYTE),
            ("AceFlags", wintypes.BYTE),
            ("AceSize", wintypes.WORD),
        ]

    class ACCESS_ALLOWED_ACE(ctypes.Structure):
        _fields_ = [
            ("Header", ACE_HEADER),
            ("Mask", wintypes.DWORD),
            ("SidStart", wintypes.DWORD),
        ]

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(ctypes.POINTER(ACL)),
        ctypes.POINTER(wintypes.LPVOID),
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.EqualSid.argtypes = [wintypes.LPVOID, wintypes.LPVOID]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.GetSecurityDescriptorControl.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.WORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetSecurityDescriptorControl.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        ctypes.POINTER(ACL),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    advapi32.GetAce.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    _sid_buffer, user_sid = _windows_current_user_sid()
    owner_sid = wintypes.LPVOID()
    dacl = ctypes.POINTER(ACL)()
    descriptor = wintypes.LPVOID()
    result = advapi32.GetNamedSecurityInfoW(
        ctypes.c_wchar_p(os.fspath(path)),
        1,
        0x00000001 | 0x00000004,
        ctypes.byref(owner_sid),
        None,
        ctypes.byref(dacl),
        None,
        ctypes.byref(descriptor),
    )
    if result != 0:
        return False
    try:
        if not owner_sid or not dacl or not advapi32.EqualSid(owner_sid, user_sid):
            return False
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not advapi32.GetSecurityDescriptorControl(
            descriptor,
            ctypes.byref(control),
            ctypes.byref(revision),
        ) or not (control.value & 0x1000):  # SE_DACL_PROTECTED
            return False
        if dacl.contents.AceCount != 1:
            return False
        ace_pointer = wintypes.LPVOID()
        if not advapi32.GetAce(dacl, 0, ctypes.byref(ace_pointer)):
            return False
        ace = ctypes.cast(ace_pointer, ctypes.POINTER(ACCESS_ALLOWED_ACE)).contents
        if ace.Header.AceType != 0 or (ace.Mask & 0x001F01FF) != 0x001F01FF:
            return False
        if directory and (ace.Header.AceFlags & 0x3) != 0x3:
            return False
        if not directory and (ace.Header.AceFlags & 0x3):
            return False
        ace_sid = ctypes.c_void_p(
            ctypes.addressof(ace) + ACCESS_ALLOWED_ACE.SidStart.offset
        )
        return bool(advapi32.EqualSid(ace_sid, user_sid))
    finally:
        if descriptor:
            kernel32.LocalFree(descriptor)


def _verify_owner_private(path: Path, *, directory: bool) -> bool:
    if os.name == "nt":
        try:
            details = os.lstat(path)
            expected_type = stat.S_ISDIR if directory else stat.S_ISREG
            reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            if (
                not expected_type(details.st_mode)
                or stat.S_ISLNK(details.st_mode)
                or bool(getattr(details, "st_file_attributes", 0) & reparse)
                or (not directory and details.st_nlink != 1)
            ):
                return False
        except OSError:
            return False
        return _windows_owner_only(path, directory=directory)
    try:
        details = os.lstat(path)
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        return (
            expected_type(details.st_mode)
            and not stat.S_ISLNK(details.st_mode)
            and (directory or details.st_nlink == 1)
            and (not hasattr(os, "geteuid") or details.st_uid == os.geteuid())
            and stat.S_IMODE(details.st_mode) == (0o700 if directory else 0o600)
        )
    except OSError:
        return False


def _pinned_directory_matches(path: Path, descriptor: int | None) -> bool:
    if os.name == "nt":
        return _verify_owner_private(path, directory=True)
    if descriptor is None:
        return False
    try:
        pinned = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISDIR(pinned.st_mode)
        and stat.S_ISDIR(current.st_mode)
        and not stat.S_ISLNK(current.st_mode)
        and pinned.st_dev == current.st_dev
        and pinned.st_ino == current.st_ino
        and (not hasattr(os, "geteuid") or pinned.st_uid == os.geteuid())
        and stat.S_IMODE(pinned.st_mode) == 0o700
    )


@contextmanager
def _pinned_private_directory(path: Path):
    if os.name == "nt":
        handles = _windows_open_directory_chain(path)
        try:
            if not _pinned_directory_matches(path, None):
                raise OSError("private connection directory is unsafe")
            yield None
            if not _pinned_directory_matches(path, None):
                raise OSError("private connection directory changed")
        finally:
            for handle in reversed(handles):
                _windows_close_handle(handle)
        return

    descriptor = _open_directory_no_follow(path)
    try:
        if not _pinned_directory_matches(path, descriptor):
            raise OSError("private connection directory is unsafe")
        yield descriptor
        if not _pinned_directory_matches(path, descriptor):
            raise OSError("private connection directory changed")
    finally:
        os.close(descriptor)


def _entry_exists(path: Path, parent_fd: int | None) -> bool:
    try:
        if parent_fd is None:
            os.lstat(path)
        else:
            os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _unlink_connection(path: Path, parent_fd: int | None) -> None:
    if parent_fd is None:
        path.unlink()
    else:
        os.unlink(path.name, dir_fd=parent_fd)


def _write_connection_record(
    path: Path,
    selection: ConnectionSelection,
    *,
    parent_fd: int | None,
) -> None:
    write_json_atomic(
        path,
        _record(selection),
        mode=0o600,
        parent_fd=parent_fd,
        maximum_bytes=MAX_CONNECTION_BYTES,
    )
    if os.name == "nt":
        _windows_set_owner_only(path, directory=False)
    if not _verify_owner_private(path, directory=False):
        raise OSError("connection record privacy could not be verified")


class RemoteHermesError(RuntimeError):
    """A bounded remote-connection failure safe to classify by code only."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ConnectionSelection:
    mode: str
    label: str
    endpoint: str | None
    api_key: str | None
    binding_id: str
    schema_version: int = CONNECTION_SCHEMA_VERSION

    def public_summary(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "label": self.label,
            "binding_id": self.binding_id,
            "configured": self.mode == "remote",
        }


@dataclass(frozen=True)
class ConnectionPreview:
    current: ConnectionSelection
    proposed: ConnectionSelection
    confirmation_token: str
    changed: bool

    def public_summary(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "current": self.current.public_summary(),
            "proposed": {
                "mode": self.proposed.mode,
                "label": self.proposed.label,
                "configured": self.proposed.mode == "remote",
                "transport": _transport_label(self.proposed.endpoint),
            },
            "changed": self.changed,
            "confirmation_token": self.confirmation_token,
        }


def _default_selection() -> ConnectionSelection:
    return ConnectionSelection(
        mode="local",
        label="Local Hermes",
        endpoint=None,
        api_key=None,
        binding_id="local-default",
    )


def connection_path(data_root: Path) -> Path:
    return private_root(Path(data_root)) / CONNECTION_FILE_NAME


def _clean_label(value: Any) -> str:
    if not isinstance(value, str):
        raise RemoteHermesError("connection_label_invalid")
    label = value.strip()
    if not label or len(label) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in label):
        raise RemoteHermesError("connection_label_invalid")
    lowered = label.casefold()
    if any(marker in lowered for marker in ("api_key", "apikey", "bearer ", "password=", "token=")):
        raise RemoteHermesError("connection_label_secret_shaped")
    return label


def _clean_api_key(value: Any) -> str:
    if not isinstance(value, str) or not (16 <= len(value) <= 512):
        raise RemoteHermesError("connection_credential_invalid")
    if value != value.strip() or any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise RemoteHermesError("connection_credential_invalid")
    return value


def _loopback_host(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def normalize_endpoint(value: Any) -> str:
    """Return one root-only origin or reject ambiguous/network-unsafe syntax."""

    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > 512
        or any(ord(char) < 33 or ord(char) == 127 for char in value)
        or "?" in value
        or "#" in value
    ):
        raise RemoteHermesError("connection_endpoint_invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise RemoteHermesError("connection_endpoint_invalid") from exc
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"}:
        raise RemoteHermesError("connection_endpoint_scheme_invalid")
    if (
        parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RemoteHermesError("connection_endpoint_components_invalid")
    hostname = parsed.hostname
    if not hostname or "%" in hostname or hostname.endswith("."):
        raise RemoteHermesError("connection_endpoint_host_invalid")
    try:
        address = ipaddress.ip_address(hostname)
        normalized_host = address.compressed
        host_display = f"[{normalized_host}]" if address.version == 6 else normalized_host
    except ValueError:
        try:
            normalized_host = hostname.encode("idna").decode("ascii").casefold()
        except UnicodeError as exc:
            raise RemoteHermesError("connection_endpoint_host_invalid") from exc
        labels = normalized_host.split(".")
        if (
            not normalized_host
            or len(normalized_host) > 253
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            )
        ):
            raise RemoteHermesError("connection_endpoint_host_invalid")
        host_display = normalized_host
    if scheme == "http" and not _loopback_host(normalized_host):
        raise RemoteHermesError("connection_endpoint_tls_required")
    default_port = 443 if scheme == "https" else 80
    if port is not None and not (1 <= port <= 65535):
        raise RemoteHermesError("connection_endpoint_port_invalid")
    authority = host_display if port in {None, default_port} else f"{host_display}:{port}"
    return f"{scheme}://{authority}"


def _selection_from_values(
    mode: Any,
    label: Any,
    endpoint: Any,
    api_key: Any,
    *,
    binding_id: str,
) -> ConnectionSelection:
    if not isinstance(mode, str) or mode not in {"local", "remote"}:
        raise RemoteHermesError("connection_mode_invalid")
    clean_label = _clean_label(label)
    if mode == "local":
        if (endpoint is not None and endpoint != "") or (
            api_key is not None and api_key != ""
        ):
            raise RemoteHermesError("local_connection_has_remote_fields")
        return ConnectionSelection("local", clean_label, None, None, binding_id)
    clean_endpoint = normalize_endpoint(endpoint)
    clean_key = _clean_api_key(api_key)
    if clean_key.casefold() in clean_label.casefold():
        raise RemoteHermesError("connection_label_secret_shaped")
    raw_parts = urlsplit(str(endpoint))
    clean_parts = urlsplit(clean_endpoint)
    private_markers = {
        str(endpoint),
        clean_endpoint,
        raw_parts.hostname or "",
        raw_parts.netloc,
        clean_parts.hostname or "",
        clean_parts.netloc,
    }
    if any(
        marker and marker.casefold() in clean_label.casefold()
        for marker in private_markers
    ):
        raise RemoteHermesError("connection_label_private_shaped")
    return ConnectionSelection("remote", clean_label, clean_endpoint, clean_key, binding_id)


def _record(selection: ConnectionSelection) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": selection.schema_version,
        "mode": selection.mode,
        "label": selection.label,
        "binding_id": selection.binding_id,
    }
    if selection.mode == "remote":
        payload["endpoint"] = selection.endpoint
        payload["api_key"] = selection.api_key
    return payload


def _selection_from_record(payload: Any) -> ConnectionSelection:
    if type(payload) is not dict:
        raise RemoteHermesError("connection_record_invalid")
    version = payload.get("schema_version")
    if type(version) is not int:
        raise RemoteHermesError("connection_record_invalid")
    if version > CONNECTION_SCHEMA_VERSION:
        raise RemoteHermesError("connection_schema_newer")
    if version != CONNECTION_SCHEMA_VERSION:
        raise RemoteHermesError("connection_record_invalid")
    base_fields = {"schema_version", "mode", "label", "binding_id"}
    expected_fields = (
        base_fields | {"endpoint", "api_key"}
        if payload.get("mode") == "remote"
        else base_fields
    )
    if set(payload) != expected_fields:
        raise RemoteHermesError("connection_record_invalid")
    binding = payload.get("binding_id")
    if not isinstance(binding, str) or not re.fullmatch(r"(?:local-default|[0-9a-f]{32})", binding):
        raise RemoteHermesError("connection_record_invalid")
    if payload.get("mode") == "remote" and binding == "local-default":
        raise RemoteHermesError("connection_record_invalid")
    if (
        payload.get("mode") == "local"
        and binding == "local-default"
        and payload.get("label") != "Local Hermes"
    ):
        raise RemoteHermesError("connection_record_invalid")
    try:
        return _selection_from_values(
            payload.get("mode"),
            payload.get("label"),
            payload.get("endpoint"),
            payload.get("api_key"),
            binding_id=binding,
        )
    except RemoteHermesError as exc:
        raise RemoteHermesError("connection_record_invalid") from exc


def _read_existing_record(
    data_root: Path,
    *,
    parent_fd: int | None = None,
) -> ConnectionSelection:
    path = connection_path(data_root)
    try:
        payload = read_json(
            path,
            None,
            parent_fd=parent_fd,
            maximum_bytes=MAX_CONNECTION_BYTES,
            required_mode=0o600,
            expected_type=dict,
            require_existing=True,
        )
    except FileNotFoundError:
        return _default_selection()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise RemoteHermesError("connection_record_invalid") from exc
    return _selection_from_record(payload)


def load_connection(data_root: Path) -> ConnectionSelection:
    path = connection_path(data_root)
    try:
        with private_state_lock(Path(data_root)):
            if not os.path.lexists(os.fspath(path)):
                return _default_selection()
            private = ensure_private_root(Path(data_root))
            if not _verify_owner_private(private, directory=True) or not _verify_owner_private(path, directory=False):
                raise RemoteHermesError("connection_storage_unavailable")
            with _pinned_private_directory(private) as parent_fd:
                return _read_existing_record(Path(data_root), parent_fd=parent_fd)
    except RemoteHermesError:
        raise
    except OSError as exc:
        raise RemoteHermesError("connection_storage_unavailable") from exc


def _canonical(selection: ConnectionSelection) -> bytes:
    return json.dumps(_record(selection), sort_keys=True, separators=(",", ":")).encode("utf-8")


def _same_intent(left: ConnectionSelection, right: ConnectionSelection) -> bool:
    return (
        left.mode,
        left.label,
        left.endpoint,
        left.api_key,
    ) == (
        right.mode,
        right.label,
        right.endpoint,
        right.api_key,
    )


def _intent_digest(
    current: ConnectionSelection,
    proposed: ConnectionSelection,
) -> bytes:
    message = (
        b"mentat-remote-hermes-intent-v1\0"
        + _canonical(current)
        + b"\0"
        + _canonical(proposed)
    )
    return hmac.new(_CONFIRMATION_SECRET, message, hashlib.sha256).digest()


def _register_confirmation(
    current: ConnectionSelection,
    proposed: ConnectionSelection,
) -> str:
    digest = _intent_digest(current, proposed)
    nonce = os.urandom(16)
    token = hmac.new(
        _CONFIRMATION_SECRET,
        b"mentat-remote-hermes-preview-v1\0" + nonce + digest,
        hashlib.sha256,
    ).hexdigest()
    now = time.monotonic()
    with _PREVIEW_LOCK:
        for stale in [
            item
            for item, (expires, _digest) in _PREVIEW_GRANTS.items()
            if expires <= now
        ]:
            _PREVIEW_GRANTS.pop(stale, None)
        while len(_PREVIEW_GRANTS) >= _MAX_PREVIEW_GRANTS:
            oldest = min(_PREVIEW_GRANTS, key=lambda item: _PREVIEW_GRANTS[item][0])
            _PREVIEW_GRANTS.pop(oldest, None)
        _PREVIEW_GRANTS[token] = (now + _PREVIEW_TTL_SECONDS, digest)
    return token


def _consume_confirmation(
    token: Any,
    current: ConnectionSelection,
    proposed: ConnectionSelection,
) -> None:
    if not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{64}", token):
        raise RemoteHermesError("connection_confirmation_invalid")
    now = time.monotonic()
    expected = _intent_digest(current, proposed)
    with _PREVIEW_LOCK:
        grant = _PREVIEW_GRANTS.get(token)
        if (
            grant is None
            or grant[0] <= now
            or not hmac.compare_digest(grant[1], expected)
        ):
            if grant is not None and grant[0] <= now:
                _PREVIEW_GRANTS.pop(token, None)
            raise RemoteHermesError("connection_confirmation_invalid")
        _PREVIEW_GRANTS.pop(token, None)


def preview_connection(data_root: Path, payload: Any) -> ConnectionPreview:
    if type(payload) is not dict:
        raise RemoteHermesError("connection_payload_invalid")
    if set(payload) - {"mode", "label", "endpoint", "api_key"}:
        raise RemoteHermesError("connection_payload_invalid")
    current = load_connection(data_root)
    proposed = _selection_from_values(
        payload.get("mode"),
        payload.get("label"),
        payload.get("endpoint"),
        payload.get("api_key"),
        binding_id=current.binding_id,
    )
    return ConnectionPreview(
        current=current,
        proposed=proposed,
        confirmation_token=_register_confirmation(current, proposed),
        changed=not _same_intent(current, proposed),
    )


def _transport_label(endpoint: str | None) -> str:
    if endpoint is None:
        return "local_process"
    return "verified_https" if endpoint.startswith("https://") else "loopback_http"


def _safe_shape(value: Any, *, depth: int = 0, budget: list[int] | None = None) -> bool:
    remaining = budget if budget is not None else [1024]
    remaining[0] -= 1
    if remaining[0] < 0 or depth > 10:
        return False
    if value is None or type(value) in {bool, int}:
        return True
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, str):
        return len(value) <= 4096
    if isinstance(value, list):
        return len(value) <= 256 and all(_safe_shape(item, depth=depth + 1, budget=remaining) for item in value)
    if type(value) is dict:
        return len(value) <= 256 and all(
            isinstance(key, str)
            and len(key) <= 160
            and _safe_shape(item, depth=depth + 1, budget=remaining)
            for key, item in value.items()
        )
    return False


def _safe_root_string_shape(
    value: Any,
    *,
    string_limits: Mapping[str, int],
) -> bool:
    """Apply larger limits only to named root strings in a bounded object."""
    if type(value) is not dict or len(value) > 256:
        return False
    budget = [1024]
    budget[0] -= 1
    for key, item in value.items():
        if not isinstance(key, str) or len(key) > 160:
            return False
        limit = string_limits.get(key)
        if limit is not None:
            budget[0] -= 1
            if budget[0] < 0 or not isinstance(item, str) or len(item) > limit:
                return False
            continue
        if not _safe_shape(item, depth=1, budget=budget):
            return False
    return True


def _bounded_text(value: Any, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise RemoteHermesError("remote_schema_unsupported")
    text = value.strip()
    if not text or len(text) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise RemoteHermesError("remote_schema_unsupported")
    return text


def _contains_private_text(
    value: Any,
    private_values: tuple[str, ...],
    *,
    exact_values: tuple[str, ...] = (),
) -> bool:
    if isinstance(value, str):
        folded = value.casefold()
        return any(
            item and item.casefold() in folded
            for item in private_values
        ) or any(
            item and item.casefold() == folded
            for item in exact_values
        )
    if isinstance(value, list):
        return any(
            _contains_private_text(
                item,
                private_values,
                exact_values=exact_values,
            )
            for item in value
        )
    if type(value) is dict:
        return any(
            _contains_private_text(
                key,
                private_values,
                exact_values=exact_values,
            )
            or _contains_private_text(
                item,
                private_values,
                exact_values=exact_values,
            )
            for key, item in value.items()
        )
    return False


def _reject_json_constant(_value: str):
    raise ValueError("non-finite JSON number")


class RemoteHermesClient:
    """Fixed-purpose client for public health and authenticated discovery."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        maximum_bytes: int = MAX_RESPONSE_BYTES,
        connection_factory: Callable[..., Any] | None = None,
    ):
        self.endpoint = normalize_endpoint(endpoint)
        self.api_key = _clean_api_key(api_key)
        if not isinstance(timeout_seconds, (int, float)) or not (0.1 <= float(timeout_seconds) <= 30.0):
            raise RemoteHermesError("remote_timeout_invalid")
        if not isinstance(maximum_bytes, int) or not (1024 <= maximum_bytes <= MAX_RESPONSE_BYTES):
            raise RemoteHermesError("remote_response_limit_invalid")
        self.timeout_seconds = float(timeout_seconds)
        self.maximum_bytes = maximum_bytes
        self.connection_factory = connection_factory

    def _connection(self, *, timeout_seconds: float | None = None):
        parsed = urlsplit(self.endpoint)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        timeout = self.timeout_seconds if timeout_seconds is None else float(timeout_seconds)
        if self.connection_factory is not None:
            return self.connection_factory(
                parsed.scheme,
                host,
                port,
                timeout,
            )
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            context.check_hostname = True
            context.verify_mode = ssl.CERT_REQUIRED
            return http.client.HTTPSConnection(
                host,
                port=port,
                timeout=timeout,
                context=context,
            )
        return http.client.HTTPConnection(host, port=port, timeout=timeout)

    def _request_json(self, path: str, *, authenticated: bool) -> Mapping[str, Any]:
        if path not in FIXED_PATHS:
            raise RemoteHermesError("remote_path_not_allowed")
        headers = {"Accept": "application/json", "User-Agent": "Mentat/remote-hermes-v1"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.api_key}"
        connection = self._connection()
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            status = int(response.status)
            if 300 <= status <= 399:
                raise RemoteHermesError("remote_redirect_refused")
            if status in {401, 403}:
                raise RemoteHermesError("remote_authentication_failed")
            if status != 200:
                raise RemoteHermesError("remote_unavailable")
            content_type = str(response.getheader("Content-Type") or "").split(";", 1)[0].strip().casefold()
            if content_type not in {"application/json", "application/problem+json"}:
                raise RemoteHermesError("remote_content_type_invalid")
            declared = response.getheader("Content-Length")
            if declared is not None:
                try:
                    if int(declared) < 0 or int(declared) > self.maximum_bytes:
                        raise RemoteHermesError("remote_response_too_large")
                except ValueError as exc:
                    raise RemoteHermesError("remote_response_invalid") from exc
            raw = response.read(self.maximum_bytes + 1)
            if len(raw) > self.maximum_bytes:
                raise RemoteHermesError("remote_response_too_large")
            try:
                payload = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=_reject_json_constant,
                )
            except (UnicodeError, ValueError, RecursionError) as exc:
                raise RemoteHermesError("remote_response_invalid") from exc
            if type(payload) is not dict or not _safe_shape(payload):
                raise RemoteHermesError("remote_response_invalid")
            return payload
        except RemoteHermesError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise RemoteHermesError("remote_certificate_invalid") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RemoteHermesError("remote_timeout") from exc
        except (ssl.SSLError, OSError, http.client.HTTPException) as exc:
            raise RemoteHermesError("remote_unavailable") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass

    @staticmethod
    def _validated_run_id(value: Any) -> str:
        if not isinstance(value, str) or not _RUN_ID.fullmatch(value):
            raise RemoteHermesError("remote_run_schema_invalid")
        return value

    def _contains_private_run_text(self, value: Any, run_id: str) -> bool:
        endpoint_parts = urlsplit(self.endpoint)
        hostname = endpoint_parts.hostname or ""
        private_hostname = (
            "" if hostname in {"localhost", "127.0.0.1", "::1"} else hostname
        )
        distinctive_netloc = (
            endpoint_parts.netloc
            if endpoint_parts.netloc != hostname
            else ""
        )
        return _contains_private_text(
            value,
            (
                self.api_key,
                self.endpoint,
                private_hostname,
                distinctive_netloc,
                run_id,
            ),
        )

    def _run_json_request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        run_path = re.fullmatch(r"/v1/runs/(run_[0-9a-f]{32})", path)
        stop_path = re.fullmatch(r"/v1/runs/(run_[0-9a-f]{32})/stop", path)
        allowed = (
            (method == "POST" and path == "/v1/runs" and expected_status == 202 and body is not None)
            or (method == "GET" and run_path is not None and expected_status == 200 and body is None)
            or (method == "POST" and stop_path is not None and expected_status == 200 and body == {})
        )
        if not allowed:
            raise RemoteHermesError("remote_path_not_allowed")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Mentat/remote-hermes-v1",
        }
        encoded: bytes | None = None
        if body is not None:
            try:
                encoded = json.dumps(
                    body,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError, UnicodeError) as exc:
                raise RemoteHermesError("remote_run_request_invalid") from exc
            if len(encoded) > MAX_RESPONSE_BYTES:
                raise RemoteHermesError("remote_run_request_invalid")
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(encoded))
        connection = self._connection()
        try:
            if encoded is None:
                connection.request(method, path, headers=headers)
            else:
                connection.request(method, path, body=encoded, headers=headers)
            response = connection.getresponse()
            status = int(response.status)
            if 300 <= status <= 399:
                raise RemoteHermesError("remote_redirect_refused")
            if status in {401, 403}:
                raise RemoteHermesError("remote_authentication_failed")
            if status != expected_status:
                raise RemoteHermesError("remote_run_rejected")
            content_type = str(response.getheader("Content-Type") or "").split(";", 1)[0].strip().casefold()
            if content_type not in {"application/json", "application/problem+json"}:
                raise RemoteHermesError("remote_content_type_invalid")
            declared = response.getheader("Content-Length")
            if declared is not None:
                try:
                    if int(declared) < 0 or int(declared) > self.maximum_bytes:
                        raise RemoteHermesError("remote_response_too_large")
                except ValueError as exc:
                    raise RemoteHermesError("remote_response_invalid") from exc
            raw = response.read(self.maximum_bytes + 1)
            if len(raw) > self.maximum_bytes:
                raise RemoteHermesError("remote_response_too_large")
            try:
                payload = json.loads(
                    raw.decode("utf-8"),
                    parse_constant=_reject_json_constant,
                )
            except (UnicodeError, ValueError, RecursionError) as exc:
                raise RemoteHermesError("remote_response_invalid") from exc
            if not _safe_root_string_shape(payload, string_limits={"output": 200_000}):
                raise RemoteHermesError("remote_response_invalid")
            return payload
        except RemoteHermesError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise RemoteHermesError("remote_certificate_invalid") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RemoteHermesError("remote_timeout") from exc
        except (ssl.SSLError, OSError, http.client.HTTPException) as exc:
            raise RemoteHermesError("remote_unavailable") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def require_console_run_capabilities(self) -> dict[str, Any]:
        discovery = self.discover()
        required = {"run_submission", "run_status", "run_events_sse", "run_stop"}
        if not required.issubset(set(discovery.get("capabilities") or ())):
            raise RemoteHermesError("remote_run_capability_unavailable")
        return discovery

    def submit_run(self, user_input: str) -> dict[str, str]:
        if (
            not isinstance(user_input, str)
            or not user_input.strip()
            or len(user_input) > 20_000
            or "\x00" in user_input
        ):
            raise RemoteHermesError("remote_run_request_invalid")
        payload = self._run_json_request(
            "POST",
            "/v1/runs",
            expected_status=202,
            body={"input": user_input},
        )
        run_id = self._validated_run_id(payload.get("run_id"))
        if payload.get("status") != "started":
            raise RemoteHermesError("remote_run_schema_invalid")
        return {"run_id": run_id, "status": "started"}

    def get_run(self, run_id: str) -> dict[str, Any]:
        run_id = self._validated_run_id(run_id)
        payload = self._run_json_request(
            "GET",
            f"/v1/runs/{run_id}",
            expected_status=200,
        )
        if payload.get("object") != "hermes.run" or payload.get("run_id") != run_id:
            raise RemoteHermesError("remote_run_schema_invalid")
        status = payload.get("status")
        if status not in _RUN_STATUSES:
            raise RemoteHermesError("remote_run_schema_invalid")
        normalized: dict[str, Any] = {"status": status}
        if status == "completed":
            output = payload.get("output")
            if not isinstance(output, str) or len(output) > 200_000 or "\x00" in output:
                raise RemoteHermesError("remote_run_schema_invalid")
            if self._contains_private_run_text(output, run_id):
                raise RemoteHermesError("remote_private_reflection")
            normalized["output"] = output
        usage = payload.get("usage")
        if usage is not None:
            if type(usage) is not dict:
                raise RemoteHermesError("remote_run_schema_invalid")
            clean_usage: dict[str, int] = {}
            for name in ("input_tokens", "output_tokens", "total_tokens"):
                value = usage.get(name)
                if type(value) is not int or not (0 <= value <= 10**9):
                    raise RemoteHermesError("remote_run_schema_invalid")
                clean_usage[name] = value
            normalized["usage"] = clean_usage
        return normalized

    def stop_run(self, run_id: str) -> dict[str, str]:
        run_id = self._validated_run_id(run_id)
        payload = self._run_json_request(
            "POST",
            f"/v1/runs/{run_id}/stop",
            expected_status=200,
            body={},
        )
        returned_run_id = payload.get("run_id")
        if (
            payload.get("status") != "stopping"
            or (returned_run_id is not None and returned_run_id != run_id)
        ):
            raise RemoteHermesError("remote_run_schema_invalid")
        return {"status": "stopping"}

    def _normalize_run_event(self, payload: Mapping[str, Any], run_id: str) -> dict[str, Any]:
        if payload.get("run_id") != run_id:
            raise RemoteHermesError("remote_run_schema_invalid")
        event_type = payload.get("event")
        if event_type == "message.delta":
            delta = payload.get("delta")
            if not isinstance(delta, str) or len(delta) > 16_000 or "\x00" in delta:
                raise RemoteHermesError("remote_run_schema_invalid")
            if self._contains_private_run_text(delta, run_id):
                raise RemoteHermesError("remote_private_reflection")
            return {"type": event_type, "delta": delta}
        if event_type in {"tool.started", "tool.completed"}:
            tool = payload.get("tool")
            if not isinstance(tool, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", tool):
                raise RemoteHermesError("remote_run_schema_invalid")
            if self._contains_private_run_text(tool, run_id):
                raise RemoteHermesError("remote_private_reflection")
            return {"type": event_type, "tool": tool}
        if event_type == "reasoning.available":
            return {"type": event_type}
        if event_type == "approval.request":
            return {"type": event_type}
        if event_type in {"run.cancelled", "run.failed"}:
            return {"type": event_type}
        if event_type == "run.completed":
            output = payload.get("output")
            if not isinstance(output, str) or len(output) > 200_000 or "\x00" in output:
                raise RemoteHermesError("remote_run_schema_invalid")
            if self._contains_private_run_text(output, run_id):
                raise RemoteHermesError("remote_private_reflection")
            return {"type": event_type, "output": output}
        raise RemoteHermesError("remote_run_event_unsupported")

    def iter_run_events(
        self,
        run_id: str,
        *,
        should_stop: Callable[[], bool] | None = None,
    ):
        run_id = self._validated_run_id(run_id)
        path = f"/v1/runs/{run_id}/events"
        headers = {
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
            "Cache-Control": "no-cache",
            "User-Agent": "Mentat/remote-hermes-v1",
        }
        connection = self._connection(timeout_seconds=RUN_STREAM_READ_TIMEOUT_SECONDS)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            status = int(response.status)
            if 300 <= status <= 399:
                raise RemoteHermesError("remote_redirect_refused")
            if status in {401, 403}:
                raise RemoteHermesError("remote_authentication_failed")
            if status != 200:
                raise RemoteHermesError("remote_run_rejected")
            content_type = str(response.getheader("Content-Type") or "").split(";", 1)[0].strip().casefold()
            if content_type != "text/event-stream":
                raise RemoteHermesError("remote_content_type_invalid")
            total_bytes = 0
            event_count = 0
            data_lines: list[bytes] = []
            data_bytes = 0
            deadline = time.monotonic() + RUN_STREAM_MAX_SECONDS
            while True:
                if time.monotonic() >= deadline:
                    raise RemoteHermesError("remote_timeout")
                if should_stop is not None and should_stop():
                    break
                line = response.readline(MAX_RUN_EVENT_BYTES + 2)
                if not line:
                    if data_lines:
                        raise RemoteHermesError("remote_run_stream_invalid")
                    break
                total_bytes += len(line)
                if total_bytes > MAX_RUN_STREAM_BYTES or len(line) > MAX_RUN_EVENT_BYTES + 1:
                    raise RemoteHermesError("remote_response_too_large")
                if should_stop is not None and should_stop():
                    break
                if line in {b"\n", b"\r\n"}:
                    if not data_lines:
                        continue
                    raw = b"\n".join(data_lines)
                    data_lines = []
                    data_bytes = 0
                    try:
                        payload = json.loads(
                            raw.decode("utf-8"),
                            parse_constant=_reject_json_constant,
                        )
                    except (UnicodeError, ValueError, RecursionError) as exc:
                        raise RemoteHermesError("remote_run_stream_invalid") from exc
                    if not _safe_root_string_shape(
                        payload,
                        string_limits={"delta": 16_000, "output": 200_000},
                    ):
                        raise RemoteHermesError("remote_run_stream_invalid")
                    event_count += 1
                    if event_count > MAX_RUN_EVENTS:
                        raise RemoteHermesError("remote_response_too_large")
                    yield self._normalize_run_event(payload, run_id)
                    continue
                if line.startswith(b":"):
                    continue
                if line.startswith(b"data:"):
                    item = line[5:].lstrip().rstrip(b"\r\n")
                    data_lines.append(item)
                    data_bytes += len(item)
                    if data_bytes > MAX_RUN_EVENT_BYTES:
                        raise RemoteHermesError("remote_response_too_large")
                    continue
                if line.startswith((b"event:", b"id:", b"retry:")):
                    continue
                raise RemoteHermesError("remote_run_stream_invalid")
        except RemoteHermesError:
            raise
        except ssl.SSLCertVerificationError as exc:
            raise RemoteHermesError("remote_certificate_invalid") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise RemoteHermesError("remote_timeout") from exc
        except (ssl.SSLError, OSError, http.client.HTTPException) as exc:
            raise RemoteHermesError("remote_unavailable") from exc
        finally:
            try:
                connection.close()
            except Exception:
                pass

    def _public_liveness(self) -> str:
        payload = self._request_json("/health", authenticated=False)
        return "ok" if payload.get("status") == "ok" else "unavailable"

    def _trusted_health(self) -> dict[str, Any]:
        payload = self._request_json("/health/detailed", authenticated=True)
        if payload.get("platform") != "hermes-agent":
            raise RemoteHermesError("remote_identity_mismatch")
        version = _bounded_text(payload.get("version"), maximum=80)
        if not _SAFE_VERSION.fullmatch(version):
            raise RemoteHermesError("remote_schema_unsupported")
        status = payload.get("status")
        readiness = payload.get("readiness")
        if (
            status not in ("ok", "degraded")
            or type(readiness) is not dict
            or readiness.get("status") != status
        ):
            raise RemoteHermesError("remote_schema_unsupported")
        checks = readiness.get("checks")
        if type(checks) is not dict or not checks or len(checks) > 32:
            raise RemoteHermesError("remote_schema_unsupported")
        safe_checks: dict[str, str] = {}
        for name, item in checks.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) or type(item) is not dict:
                raise RemoteHermesError("remote_schema_unsupported")
            check_status = item.get("status")
            if check_status not in ("ok", "degraded"):
                raise RemoteHermesError("remote_schema_unsupported")
            safe_checks[name] = check_status
        expected_status = (
            "ok"
            if all(item == "ok" for item in safe_checks.values())
            else "degraded"
        )
        if status != expected_status:
            raise RemoteHermesError("remote_schema_unsupported")
        return {"status": status, "version": version, "checks": dict(sorted(safe_checks.items()))}

    def _trusted_capabilities(self) -> dict[str, Any]:
        payload = self._request_json("/v1/capabilities", authenticated=True)
        if payload.get("object") != "hermes.api_server.capabilities" or payload.get("platform") != "hermes-agent":
            raise RemoteHermesError("remote_identity_mismatch")
        auth = payload.get("auth")
        runtime = payload.get("runtime")
        features = payload.get("features")
        endpoints = payload.get("endpoints")
        if (
            type(auth) is not dict
            or auth.get("type") != "bearer"
            or auth.get("required") is not True
            or type(runtime) is not dict
            or runtime.get("mode") != "server_agent"
            or runtime.get("tool_execution") != "server"
            or runtime.get("split_runtime") is not False
            or type(features) is not dict
            or type(endpoints) is not dict
        ):
            raise RemoteHermesError("remote_schema_unsupported")
        for name, expected in _REQUIRED_ENDPOINTS.items():
            item = endpoints.get(name)
            if type(item) is not dict or (item.get("method"), item.get("path")) != expected:
                raise RemoteHermesError("remote_schema_unsupported")
        for name, (method, path, feature) in _RUN_ENDPOINTS.items():
            if features.get(feature) is not True:
                continue
            item = endpoints.get(name)
            if type(item) is not dict or (item.get("method"), item.get("path")) != (method, path):
                raise RemoteHermesError("remote_schema_unsupported")
        model = _bounded_text(payload.get("model"), maximum=160)
        if not _SAFE_MODEL.fullmatch(model) or model.startswith("/") or ".." in model or "://" in model or "\\" in model:
            raise RemoteHermesError("remote_schema_unsupported")
        supported = sorted(
            name
            for name in _KNOWN_BOOLEAN_FEATURES
            if features.get(name) is True
        )
        return {"model": model, "features": supported}

    def discover(self) -> dict[str, Any]:
        try:
            liveness = self._public_liveness()
        except RemoteHermesError:
            liveness = "unknown"
        health = self._trusted_health()
        capabilities = self._trusted_capabilities()
        discovery = {
            "status": "healthy" if health["status"] == "ok" else "degraded",
            "liveness": liveness,
            "trusted": True,
            "platform": "hermes-agent",
            "version": health["version"],
            "model": capabilities["model"],
            "readiness": health["checks"],
            "capabilities": capabilities["features"],
        }
        endpoint_parts = urlsplit(self.endpoint)
        hostname = endpoint_parts.hostname or ""
        distinctive_hostname = (
            hostname
            if len(hostname) >= 8 or any(char in hostname for char in ".:")
            else ""
        )
        short_hostname = hostname if hostname and not distinctive_hostname else ""
        distinctive_netloc = (
            endpoint_parts.netloc
            if endpoint_parts.netloc != hostname
            else ""
        )
        upstream_public_fields = {
            "version": health["version"],
            "model": capabilities["model"],
            "readiness_names": list(health["checks"]),
        }
        if _contains_private_text(
            upstream_public_fields,
            (
                self.api_key,
                self.endpoint,
                distinctive_hostname,
                distinctive_netloc,
            ),
            exact_values=(short_hostname,),
        ):
            raise RemoteHermesError("remote_private_reflection")
        return discovery


def confirm_connection(
    data_root: Path,
    payload: Any,
    confirmation_token: Any,
    *,
    client_factory: Callable[[str, str], RemoteHermesClient] = RemoteHermesClient,
) -> dict[str, Any]:
    if type(payload) is not dict or set(payload) - {"mode", "label", "endpoint", "api_key"}:
        raise RemoteHermesError("connection_payload_invalid")
    current_preview = load_connection(data_root)
    proposed_preview = _selection_from_values(
        payload.get("mode"),
        payload.get("label"),
        payload.get("endpoint"),
        payload.get("api_key"),
        binding_id=current_preview.binding_id,
    )
    _consume_confirmation(
        confirmation_token,
        current_preview,
        proposed_preview,
    )
    discovery: dict[str, Any] | None = None
    if proposed_preview.mode == "remote":
        client = client_factory(
            proposed_preview.endpoint or "",
            proposed_preview.api_key or "",
        )
        discovery = client.discover()
        if discovery.get("trusted") is not True:
            raise RemoteHermesError("remote_verification_failed")

    root = Path(data_root)
    try:
        with private_state_lock(root):
            private = ensure_private_root(root)
            path = private / CONNECTION_FILE_NAME
            if os.name == "nt" and not os.path.lexists(os.fspath(path)):
                _windows_set_owner_only(private, directory=True)
            if not _verify_owner_private(private, directory=True):
                raise RemoteHermesError("connection_storage_unavailable")
            with _pinned_private_directory(private) as parent_fd:
                prior_existed = _entry_exists(path, parent_fd)
                if prior_existed and not _verify_owner_private(path, directory=False):
                    raise RemoteHermesError("connection_storage_unavailable")
                current = _read_existing_record(root, parent_fd=parent_fd)
                proposed = _selection_from_values(
                    payload.get("mode"),
                    payload.get("label"),
                    payload.get("endpoint"),
                    payload.get("api_key"),
                    binding_id=current.binding_id,
                )
                if current != current_preview or proposed != proposed_preview:
                    raise RemoteHermesError("connection_changed")
                selected = (
                    current
                    if _same_intent(current, proposed)
                    else ConnectionSelection(
                        proposed.mode,
                        proposed.label,
                        proposed.endpoint,
                        proposed.api_key,
                        uuid4().hex,
                    )
                )
                if selected != current:
                    try:
                        if not _pinned_directory_matches(private, parent_fd):
                            raise OSError("private connection directory changed")
                        _write_connection_record(
                            path,
                            selected,
                            parent_fd=parent_fd,
                        )
                        if (
                            not _pinned_directory_matches(private, parent_fd)
                            or _read_existing_record(root, parent_fd=parent_fd) != selected
                        ):
                            raise OSError("connection commit did not verify")
                    except Exception as commit_error:
                        rollback_verified = False
                        try:
                            if prior_existed:
                                _write_connection_record(
                                    path,
                                    current,
                                    parent_fd=parent_fd,
                                )
                                rollback_verified = (
                                    _read_existing_record(root, parent_fd=parent_fd)
                                    == current
                                )
                            elif _entry_exists(path, parent_fd):
                                committed = _read_existing_record(
                                    root,
                                    parent_fd=parent_fd,
                                )
                                if committed == selected:
                                    _unlink_connection(path, parent_fd)
                                rollback_verified = not _entry_exists(path, parent_fd)
                            else:
                                rollback_verified = True
                        except Exception:
                            rollback_verified = False
                        raise RemoteHermesError(
                            "connection_commit_rolled_back"
                            if rollback_verified
                            else "connection_commit_partial"
                        ) from commit_error
    except RemoteHermesError:
        raise
    except OSError as exc:
        raise RemoteHermesError("connection_storage_unavailable") from exc
    return {
        "status": "selected",
        "selection": selected.public_summary(),
        "discovery": discovery,
    }


def test_selected_connection(
    data_root: Path,
    *,
    client_factory: Callable[[str, str], RemoteHermesClient] = RemoteHermesClient,
) -> dict[str, Any]:
    selected = load_connection(data_root)
    if selected.mode == "local":
        if load_connection(data_root) != selected:
            raise RemoteHermesError("connection_changed")
        return {
            "status": "local",
            "selection": selected.public_summary(),
            "discovery": None,
        }
    client = client_factory(selected.endpoint or "", selected.api_key or "")
    discovery = client.discover()
    if load_connection(data_root) != selected:
        raise RemoteHermesError("connection_changed")
    return {
        "status": "verified",
        "selection": selected.public_summary(),
        "discovery": discovery,
    }


def public_connection_payload(data_root: Path) -> dict[str, Any]:
    try:
        return {"status": "configured", "selection": load_connection(data_root).public_summary()}
    except RemoteHermesError as exc:
        return {
            "status": "unavailable",
            "error_code": exc.code,
            "error": "Hermes connection settings are unavailable.",
        }


def public_error(error: RemoteHermesError) -> tuple[dict[str, Any], int]:
    status = 502 if error.code.startswith("remote_") else 409
    if error.code in {
        "connection_payload_invalid",
        "connection_mode_invalid",
        "connection_label_invalid",
        "connection_label_private_shaped",
        "connection_label_secret_shaped",
        "connection_credential_invalid",
        "connection_endpoint_invalid",
        "connection_endpoint_scheme_invalid",
        "connection_endpoint_components_invalid",
        "connection_endpoint_host_invalid",
        "connection_endpoint_port_invalid",
        "connection_endpoint_tls_required",
        "local_connection_has_remote_fields",
    }:
        status = 400
    if error.code in {
        "connection_storage_unavailable",
        "connection_commit_rolled_back",
        "connection_commit_partial",
    }:
        status = 500
    payload = {
        "error": "Mentat could not verify this Hermes connection change.",
        "error_code": error.code,
    }
    if error.code == "connection_commit_partial":
        payload["partial"] = True
    return payload, status


__all__ = [
    "CONNECTION_FILE_NAME",
    "CONNECTION_SCHEMA_VERSION",
    "ConnectionPreview",
    "ConnectionSelection",
    "RemoteHermesClient",
    "RemoteHermesError",
    "confirm_connection",
    "connection_path",
    "load_connection",
    "normalize_endpoint",
    "preview_connection",
    "public_connection_payload",
    "public_error",
    "test_selected_connection",
]
