"""Owner-private remote Hermes selection and fixed Hermes API operations.

This module deliberately exposes no generic request method. One validated
operator-granted origin and one private credential authorize only the fixed
discovery/inventory paths plus capability-gated run submission, status, SSE,
and stop.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import bisect
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
import unicodedata
from urllib.parse import parse_qsl, unquote, unquote_plus, urlsplit
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
FIXED_PATHS = frozenset(
    {
        "/health",
        "/health/detailed",
        "/v1/capabilities",
        "/v1/skills",
        "/v1/toolsets",
        "/v1/profiles",
    }
)
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
        "run_approval_request_binding",
        "run_approval_structured_preview",
        "run_clarification_response",
        "run_clarification_request_binding",
        "clarification_events",
        "run_session_continuation",
        "run_session_continuation_exact_revision",
        "run_session_continuation_stoppable",
        "run_inline_images",
        "profile_inventory",
        "profile_inventory_complete",
        "profile_inventory_requires_api_key",
        "kanban_api",
        "kanban_api_revisioned",
        "kanban_api_idempotency",
        "kanban_api_requires_api_key",
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
_SESSION_ENDPOINTS = {
    "sessions": ("GET", "/api/sessions"),
    "session": ("GET", "/api/sessions/{session_id}"),
    "session_messages": ("GET", "/api/sessions/{session_id}/messages"),
}
_CAPABILITY_INVENTORY_ENDPOINTS = {
    "skills": ("GET", "/v1/skills"),
    "toolsets": ("GET", "/v1/toolsets"),
}
_PROFILE_INVENTORY_ENDPOINT = ("GET", "/v1/profiles")
_CONTINUATION_ENDPOINT = ("GET", "/v1/sessions/{session_id}/continuation")
_APPROVAL_ENDPOINT = ("POST", "/v1/runs/{run_id}/approval")
_CLARIFICATION_ENDPOINT = ("POST", "/v1/runs/{run_id}/clarification")
_KANBAN_ENDPOINTS = {
    "kanban_boards": ("GET", "/v1/kanban/boards"),
    "kanban_profiles": ("GET", "/v1/kanban/profiles?board={board}"),
    "kanban_tasks": ("GET", "/v1/kanban/tasks?board={board}"),
    "kanban_task": ("GET", "/v1/kanban/tasks/{task_id}?board={board}"),
    "kanban_task_create": ("POST", "/v1/kanban/tasks?board={board}"),
    "kanban_task_action": ("POST", "/v1/kanban/tasks/{task_id}/actions?board={board}"),
}
_APPROVAL_REQUEST_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_CLARIFICATION_REQUEST_ID = re.compile(r"clarify_[A-Za-z0-9_-]{1,120}\Z")
_CONTINUATION_REVISION = re.compile(r"sessionrev_[0-9a-f]{64}\Z")
_KANBAN_REVISION = re.compile(r"kanbanrev_[0-9a-f]{64}\Z")
_KANBAN_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}\Z")
_KANBAN_BOARD = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_KANBAN_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
MAX_REMOTE_SKILLS = 500
MAX_REMOTE_TOOLSETS = 128
MAX_REMOTE_TOOLS_PER_TOOLSET = 256
MAX_REMOTE_TOOL_REFERENCES = 4_096
_INVENTORY_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z")
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
SESSION_LIST_LIMIT = 12
SESSION_MESSAGE_LIMIT = 500
SESSION_CONTENT_LIMIT = 100_000
SESSION_CONTENT_PART_LIMIT = 32
MAX_PUBLIC_URL_SPANS = 256
MAX_PUBLIC_URL_QUERY_FIELDS = 64
_SECRET_TOKEN_TEXT = re.compile(
    r"(?i)(?:\bbearer\s+\S+|\b(?:sk-(?:proj-)?|gh[pousr]_|AKIA)[A-Z0-9_-]{8,})"
)
_CREDENTIAL_LABELS = (
    "apikey",
    "accesskey",
    "privatekey",
    "credential",
    "credentials",
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
)
_CREDENTIAL_METADATA_TERMS = frozenset(
    {
        "algorithm",
        "at",
        "auth",
        "cache",
        "configured",
        "count",
        "days",
        "description",
        "enabled",
        "endpoint",
        "expires",
        "expiry",
        "format",
        "kind",
        "length",
        "max",
        "method",
        "methods",
        "min",
        "name",
        "policy",
        "provider",
        "requirements",
        "reset",
        "rotation",
        "scheme",
        "scope",
        "source",
        "status",
        "supported",
        "type",
        "version",
    }
)
_CREDENTIAL_LEXICAL_NEIGHBORS = (
    "betoken",
    "nonsecret",
    "credentialed",
    "passwordless",
    "secretary",
    "tokenization",
    "tokenizer",
    "unsecret",
)
_CREDENTIAL_SENSITIVE_DESCRIPTORS = frozenset({"hash", "header", "id", "json", "pem", "value"})
_HUMAN_CREDENTIAL_COMPOUNDS = (
    ("api", "key"),
    ("access", "key"),
    ("private", "key"),
    ("client", "secret"),
    ("refresh", "token"),
    ("access", "token"),
    ("aws", "access", "key"),
)
_HUMAN_CREDENTIAL_LABELS = (
    *_HUMAN_CREDENTIAL_COMPOUNDS,
    ("apikey",),
    ("accesskey",),
    ("privatekey",),
    ("awsaccesskey",),
    ("clientsecret",),
    ("refreshtoken",),
    ("accesstoken",),
    ("password",),
    ("passwd",),
    ("credential",),
    ("credentials",),
    ("authorization",),
    ("secret",),
    ("token",),
)
_COMPACT_CREDENTIAL_SUFFIXES = (
    "apikey",
    "accesskey",
    "privatekey",
    "awsaccesskey",
    "clientsecret",
    "refreshtoken",
    "accesstoken",
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "credentials",
    "authorization",
)
_HUMAN_METADATA_PROSE_TERMS = frozenset(
    {
        "are",
        "be",
        "can",
        "documented",
        "documentation",
        "follows",
        "is",
        "json",
        "may",
        "must",
        "should",
        "shown",
        "was",
        "were",
        "will",
    }
)
_HUMAN_COMPOUND_PATTERN = re.compile(
    r"(?i)(?:api(?:\s+|_+|[^\w\s]+)key|"
    r"access(?:\s+|_+|[^\w\s]+)key|"
    r"private(?:\s+|_+|[^\w\s]+)key|"
    r"client(?:\s+|_+|[^\w\s]+)secret|"
    r"refresh(?:\s+|_+|[^\w\s]+)token|"
    r"access(?:\s+|_+|[^\w\s]+)token|"
    r"aws(?:\s+|_+|[^\w\s]+)access(?:\s+|_+|[^\w\s]+)key)"
    r"(?![A-Za-z0-9])"
)
_HUMAN_SINGLE_PUNCTUATED_PATTERN = re.compile(
    r"(?i)\b(password|passwd|credentials?|authorization|secret|token)[._,-]"
    r"(?=[A-Za-z0-9])"
)
_HUMAN_SCOPED_LABEL_PATTERN = re.compile(
    r"(?i)\b(?:api key|access key|private key|client secret|refresh token|"
    r"access token|aws access key|apikey|accesskey|privatekey|clientsecret|"
    r"refreshtoken|accesstoken|awsaccesskey|password|passwd|credentials?|"
    r"authorization|secret|token|[A-Za-z0-9_-]*(?:apikey|accesskey|privatekey|"
    r"clientsecret|refreshtoken|accesstoken))\s+\("
)
_SAFE_OVERLENGTH_TOPIC_PATTERN = re.compile(
    r"(?i)^(?:[\w-]*(?:apikey|accesskey|privatekey|clientsecret|refreshtoken|"
    r"accesstoken)|api(?:\s+|_+|[^\w\s]+)key|"
    r"access(?:\s+|_+|[^\w\s]+)key|"
    r"private(?:\s+|_+|[^\w\s]+)key|"
    r"client(?:\s+|_+|[^\w\s]+)secret|"
    r"refresh(?:\s+|_+|[^\w\s]+)token|"
    r"access(?:\s+|_+|[^\w\s]+)token|"
    r"password|passwd|credentials?|authorization|secret|token)\s+"
    r"(?:format|requirements|status|policy|description|method|scope|source|"
    r"type|version|supported|configured)\s+"
    r"(?:(?:is|are|was|were|should|will|can|may|must|be)\s+)*"
    r"(?:documented|documentation|shown|supported|configured|follows)\b"
)
_SAFE_OVERLENGTH_COMPACT_TOPIC_PATTERN = re.compile(
    r"(?i)^(?P<label>(?:[^\W\d]|_)(?:[\w-])*)\s+"
    r"(?:format|requirements|status|policy|description|method|scope|source|"
    r"type|version|supported|configured)\s+"
    r"(?:(?:is|are|was|were|should|will|can|may|must|be)\s+)*"
    r"(?:documented|documentation|shown|supported|configured|follows)\b",
    re.UNICODE,
)


class _ComparisonNormalizationOverflow(ValueError):
    pass
_PRIVATE_KEY_BLOCK = re.compile(
    r"(?i)-----BEGIN [A-Z0-9 ]*PRIVATE\s*KEY(?: BLOCK)?-----"
)
_WEB_URL_START = re.compile(
    r"(?i)https?://(?:\[[^\]\s]+\]|[^\s<>\"'`()\[\]{}*,;/:]+)(?::\d{1,5})?"
)
_SAFE_NUMERIC_SLASH_TOKEN = re.compile(r"\d{1,4}/\d{1,4}(?:/\d{1,4})?\Z")
_SAFE_INITIAL_SLASH_TOKEN = re.compile(r"[A-Z]/[A-Z]\Z")
_PRIVATE_HOST_SUFFIXES = (
    ".local",
    ".localhost",
    ".localdomain",
    ".localdomain4",
    ".localdomain6",
    ".internal",
    ".lan",
    ".home",
    ".arpa",
    ".test",
    ".invalid",
    ".example",
    ".onion",
    ".alt",
)
_PUBLIC_DNS_HOST = re.compile(
    r"(?i)(?=.{1,253}\Z)(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z](?:[A-Z0-9-]{0,61}[A-Z0-9])?\Z"
)
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


def _safe_root_list_shape(
    value: Any,
    *,
    list_limits: Mapping[str, int],
) -> bool:
    """Allow named root lists to exceed the generic 256-item shape ceiling."""
    if type(value) is not dict or len(value) > 256:
        return False
    budget = [16_384]
    budget[0] -= 1
    for key, item in value.items():
        if not isinstance(key, str) or len(key) > 160:
            return False
        limit = list_limits.get(key)
        if limit is not None:
            if not isinstance(item, list) or len(item) > limit:
                return False
            budget[0] -= 1
            if budget[0] < 0:
                return False
            if not all(
                _safe_shape(row, depth=1, budget=budget)
                for row in item
            ):
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


def _inventory_text(
    value: Any,
    *,
    maximum: int,
    allow_empty: bool = False,
    reject_paths: bool = True,
) -> str:
    if not isinstance(value, str):
        raise RemoteHermesError("remote_capability_inventory_schema_invalid")
    if any(
        (ord(char) < 32 and char not in "\t\r\n") or ord(char) == 127
        for char in value
    ):
        raise RemoteHermesError("remote_capability_inventory_schema_invalid")
    text = " ".join(value.split())
    if (not text and not allow_empty) or len(text) > maximum:
        raise RemoteHermesError("remote_capability_inventory_schema_invalid")
    if reject_paths and ("/" in text or "\\" in text):
        raise RemoteHermesError("remote_capability_inventory_private")
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


def _markdown_marker_stripped(value: str) -> str:
    """Catch private values split by inert formatting markers in plain text."""
    return value.translate(str.maketrans("", "", "*`"))


def _is_default_ignorable(character: str) -> bool:
    codepoint = ord(character)
    return (
        codepoint in {0x00AD, 0x034F, 0x061C, 0x3164, 0xFEFF, 0xFFA0}
        or 0x115F <= codepoint <= 0x1160
        or 0x17B4 <= codepoint <= 0x17B5
        or 0x180B <= codepoint <= 0x180F
        or 0x200B <= codepoint <= 0x200F
        or 0x202A <= codepoint <= 0x202E
        or 0x2060 <= codepoint <= 0x206F
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0xFFF0 <= codepoint <= 0xFFF8
        or 0x1BCA0 <= codepoint <= 0x1BCA3
        or 0x1D173 <= codepoint <= 0x1D17A
        or 0xE0000 <= codepoint <= 0xE0FFF
    )


def _browser_ignorable_stripped(value: str) -> str:
    """Remove controls invisible in browser text for comparison only."""
    characters: list[str] = []
    for character in value:
        if character.isspace():
            characters.append(" ")
        elif unicodedata.category(character) == "Cc" or _is_default_ignorable(character):
            continue
        else:
            characters.append(character)
    return "".join(characters)


def _comparison_variants(value: str, *, strip_markers: bool = False) -> list[str]:
    bases = [value]
    if strip_markers:
        bases.append(_markdown_marker_stripped(value))
    variants: list[str] = []
    for base in bases:
        for rendered in (base, _browser_ignorable_stripped(base)):
            normalized = unicodedata.normalize("NFKC", rendered)
            if (
                len(normalized) > SESSION_CONTENT_LIMIT
                or len(normalized) > max(16, len(rendered) * 4)
            ):
                raise _ComparisonNormalizationOverflow
            for candidate in (
                rendered,
                " ".join(rendered.split()),
                normalized,
                " ".join(normalized.split()),
            ):
                if candidate not in variants:
                    variants.append(candidate)
    return variants


def _browser_text_variants(value: str) -> list[str] | None:
    layers = _decoded_text_layers(value, plus=False)
    if layers is None:
        return None
    variants: list[str] = []
    try:
        for layer in layers:
            for rendered in _comparison_variants(layer, strip_markers=True):
                if rendered not in variants:
                    variants.append(rendered)
    except _ComparisonNormalizationOverflow:
        return None
    return variants


def _contains_private_text_variants(
    value: Any,
    private_values: tuple[str, ...],
    *,
    exact_values: tuple[str, ...] = (),
) -> bool:
    if isinstance(value, str):
        variants = _browser_text_variants(value)
        return variants is None or any(
            _contains_private_text(
                variant,
                private_values,
                exact_values=exact_values,
            )
            for variant in variants
        )
    if isinstance(value, list):
        return any(
            _contains_private_text_variants(
                item,
                private_values,
                exact_values=exact_values,
            )
            for item in value
        )
    if type(value) is dict:
        return any(
            _contains_private_text_variants(
                key,
                private_values,
                exact_values=exact_values,
            )
            or _contains_private_text_variants(
                item,
                private_values,
                exact_values=exact_values,
            )
            for key, item in value.items()
        )
    return False


def _slash_tokens(value: str):
    if "/" not in value and "\\" not in value:
        return ()
    return (
        token
        for token in value.split()
        if "/" in token or "\\" in token
    )


def _credential_metadata_suffix(value: str) -> bool:
    if not value:
        return False
    positions = {0}
    for offset in range(len(value) + 1):
        if offset not in positions:
            continue
        digit_match = re.match(r"(?:v?\d+)", value[offset:])
        if offset > 0 and digit_match:
            positions.add(offset + digit_match.end())
        for term in _CREDENTIAL_METADATA_TERMS:
            if value.startswith(term, offset):
                positions.add(offset + len(term))
    return len(value) in positions


def _canonical_credential_identifier_is_sensitive(value: str) -> bool:
    canonical_identifier = "".join(
        character
        for character in value.casefold()
        if character.isalnum()
    )
    labels = sorted(_CREDENTIAL_LABELS, key=len, reverse=True)
    for offset in range(len(canonical_identifier)):
        label = next(
            (
                candidate
                for candidate in labels
                if canonical_identifier.startswith(candidate, offset)
            ),
            None,
        )
        if label is None:
            continue
        suffix = canonical_identifier[offset + len(label):]
        if _credential_metadata_suffix(suffix):
            continue
        lexical_neighbor = any(
            canonical_identifier.startswith(neighbor, offset)
            for neighbor in _CREDENTIAL_LEXICAL_NEIGHBORS
        )
        if not lexical_neighbor:
            return True
    return False


def _credential_identifier_is_sensitive(value: str) -> bool:
    if "." not in value:
        return _canonical_credential_identifier_is_sensitive(value)
    segments = [
        "".join(character for character in segment.casefold() if character.isalnum())
        for segment in value.split(".")
    ]
    segments = [segment for segment in segments if segment]
    for index, segment in enumerate(segments):
        remaining = segments[index + 1:]
        if (
            segment in {"api", "access", "private"}
            and remaining
            and remaining[0] == "key"
        ):
            compound_suffix = "".join(remaining[1:])
            if not compound_suffix or not _credential_metadata_suffix(compound_suffix):
                return True
            continue
        if segment in _CREDENTIAL_LABELS:
            if not remaining:
                return True
            if any(
                remainder in _CREDENTIAL_SENSITIVE_DESCRIPTORS
                for remainder in remaining
            ):
                return True
            if not _credential_metadata_suffix("".join(remaining)):
                return True
            continue
        if _canonical_credential_identifier_is_sensitive(segment):
            combined = segment + "".join(remaining)
            if _canonical_credential_identifier_is_sensitive(combined):
                return True
    return False


def _explicit_dotted_credential_structure(value: str) -> bool:
    segments = [
        "".join(character for character in segment.casefold() if character.isalnum())
        for segment in value.split(".")
    ]
    segments = [segment for segment in segments if segment]
    for index, segment in enumerate(segments):
        if (
            segment in {"api", "access", "private"}
            and index + 1 < len(segments)
            and segments[index + 1] == "key"
        ):
            return True
        if (
            segment in _CREDENTIAL_LABELS
            and any(
                item in _CREDENTIAL_SENSITIVE_DESCRIPTORS
                for item in segments[index + 1:]
            )
        ):
            return True
        if (
            segment not in _CREDENTIAL_LABELS
            and _canonical_credential_identifier_is_sensitive(segment)
        ):
            return True
    return False


def _property_chain_segments(expression: str) -> list[str] | None:
    if not expression or "[" not in expression:
        return None
    depth = 0
    quote = ""
    escaped = False
    for character in expression:
        if quote:
            if escaped:
                if not character.isprintable() or unicodedata.category(character).startswith("C"):
                    return None
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            elif not character.isprintable() or unicodedata.category(character).startswith("C"):
                return None
            continue
        if character in "\"'":
            if depth == 0:
                return None
            quote = character
        elif character == "[":
            depth += 1
            if depth > 3:
                return None
        elif character == "]":
            depth -= 1
            if depth < 0:
                return None
        elif character in " \t":
            continue
        elif character in ".,_-:|+*/%&?":
            if depth == 0 and character in ",:|+*/%&?":
                return None
        elif not character.isalnum():
            return None
    if depth != 0 or quote or escaped:
        return None
    identifier_runs = re.findall(r"(?:[^\W\d]|_)(?:[\w-])*", expression, re.UNICODE)
    if not identifier_runs or any(len(item) > 160 for item in identifier_runs):
        return None
    return identifier_runs


def _bounded_bracket_lhs(value: str, position: int) -> tuple[bool, str | None]:
    start_limit = max(0, position - 512)
    cursor = position - 1
    while cursor >= start_limit and value[cursor] in " \t":
        cursor -= 1
    end = cursor + 1
    depth = 0
    quote = ""
    saw_bracket = False
    while cursor >= start_limit:
        character = value[cursor]
        if quote:
            if character == quote:
                backslash_cursor = cursor - 1
                backslashes = 0
                while backslash_cursor >= start_limit and value[backslash_cursor] == "\\":
                    backslashes += 1
                    backslash_cursor -= 1
                if backslashes % 2 == 0:
                    quote = ""
            cursor -= 1
            continue
        if character in "\"'" and depth > 0:
            quote = character
        elif character == "]":
            saw_bracket = True
            depth += 1
            if depth > 3:
                return True, None
        elif character == "[":
            saw_bracket = True
            depth -= 1
            if depth < 0:
                return True, None
        elif depth == 0 and character in " \t":
            whitespace_end = cursor
            while cursor >= start_limit and value[cursor] in " \t":
                cursor -= 1
            previous = value[cursor] if cursor >= start_limit else ""
            following_index = whitespace_end + 1
            following = value[following_index] if following_index < end else ""
            if previous == "." or following == ".":
                continue
            break
        elif depth == 0 and character in "\r\n=:,;(){}<>/\\":
            break
        cursor -= 1
    if cursor < start_limit and start_limit > 0:
        return True, None
    if not saw_bracket:
        return False, None
    if depth != 0 or quote:
        return True, None
    if cursor < start_limit and start_limit > 0:
        previous = value[start_limit - 1]
        if previous.isalnum() or previous in "_.-[]\"'":
            return True, None
    expression = value[cursor + 1:end]
    return True, expression or None


def _bounded_bracket_key_text(value: str, recent_open: int, position: int) -> str | None:
    cursor = position - 1
    while cursor > recent_open and value[cursor] in " \t":
        cursor -= 1
    if cursor <= recent_open:
        return ""
    if value[cursor] in "\"'":
        quote = value[cursor]
        quote_end = cursor
        cursor -= 1
        while cursor > recent_open:
            if value[cursor] == quote:
                backslashes = 0
                probe = cursor - 1
                while probe > recent_open and value[probe] == "\\":
                    backslashes += 1
                    probe -= 1
                if backslashes % 2 == 0:
                    key_text = value[cursor + 1:quote_end]
                    if len(key_text) > 160:
                        return None
                    return re.sub(r"[^A-Za-z0-9_.-]+", " ", key_text).strip()
            cursor -= 1
        return None
    key_end = cursor + 1
    scanned = 0
    while cursor > recent_open and value[cursor] not in "[,{":
        cursor -= 1
        scanned += 1
        if scanned > 160:
            return None
    return value[cursor + 1:key_end].strip(" \t\"'")


def _public_network_host(hostname: str) -> bool:
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            folded_host = hostname.encode("idna").decode("ascii").casefold().rstrip(".")
        except UnicodeError:
            return False
        return bool(
            _PUBLIC_DNS_HOST.fullmatch(folded_host)
            and folded_host != "localhost"
            and not folded_host.endswith(_PRIVATE_HOST_SUFFIXES)
        )
    return not (
        getattr(address, "scope_id", None) is not None
        or not address.is_global
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        or address.is_loopback
        or address.is_link_local
        or address.is_private
    )


def _compact_credential_token_is_candidate(value: str) -> bool:
    normalized = unicodedata.normalize("NFKC", value)
    canonical = "".join(
        character for character in normalized.casefold() if character.isalnum()
    )
    if canonical in _CREDENTIAL_LABELS:
        return True
    compound_suffixes = {
        "apikey",
        "accesskey",
        "privatekey",
        "awsaccesskey",
        "clientsecret",
        "refreshtoken",
        "accesstoken",
    }
    if any(canonical.endswith(suffix) for suffix in compound_suffixes):
        return True
    for suffix in {
        "token",
        "secret",
        "password",
        "passwd",
        "credential",
        "credentials",
        "authorization",
    }:
        if len(normalized) <= len(suffix):
            continue
        suffix_text = normalized[-len(suffix):]
        if suffix_text.casefold() != suffix:
            continue
        prefix_text = normalized[:-len(suffix)]
        if prefix_text.casefold() in {"be", "non", "un"}:
            continue
        preceding = normalized[-len(suffix) - 1]
        if (
            preceding in "_-"
            or suffix_text[0].isupper()
            or (ord(preceding) > 127 and suffix_text.isascii())
        ):
            return True
    return False


def _human_credential_phrase_is_sensitive(value: str, delimiter: str = "=") -> bool:
    clause = value[-160:].rstrip()
    clause = _HUMAN_COMPOUND_PATTERN.sub(
        lambda match: " " + " ".join(
            re.findall(r"[A-Za-z0-9]+", match.group(0))
        ),
        clause,
    )
    clause = _HUMAN_SINGLE_PUNCTUATED_PATTERN.sub(r"\1 ", clause)
    scoped_compound = bool(_HUMAN_SCOPED_LABEL_PATTERN.search(clause))
    for scoped_match in re.finditer(
        r"((?:[^\W\d]|_)(?:[\w-])*)\s+\(",
        clause,
        re.UNICODE,
    ):
        if _compact_credential_token_is_candidate(scoped_match.group(1)):
            scoped_compound = True
            break
    single_scope_match = re.search(
        r"(?i)\b(?:password|passwd|credentials?|authorization|secret|token)\s+\(",
        clause,
    )
    if (scoped_compound or single_scope_match) and "(" in clause:
        scoped_characters: list[str] = []
        scoped_depth = 0
        for character in clause:
            if character == "(":
                scoped_depth += 1
                scoped_characters.append(" ")
            elif character == ")":
                if scoped_depth == 0:
                    return True
                scoped_depth -= 1
                scoped_characters.append(" ")
            elif scoped_depth > 0 and character in "\r\n.,;:?!…—–=":
                scoped_characters.append(" ")
            else:
                scoped_characters.append(character)
        if scoped_depth != 0:
            return True
        clause = "".join(scoped_characters)
    else:
        parenthesis_boundary = max(clause.rfind("("), clause.rfind(")"))
        if parenthesis_boundary >= 0:
            clause = clause[parenthesis_boundary + 1:]
    boundary = max(
        (clause.rfind(character) for character in "\r\n.,;:?!…—–="),
        default=-1,
    )
    clause = clause[boundary + 1:]
    raw_words = re.findall(r"[A-Za-z0-9]+", clause)
    words = [item.casefold() for item in raw_words]
    for index, word in enumerate(words):
        if (
            word not in _CREDENTIAL_LABELS
            and _compact_credential_token_is_candidate(raw_words[index])
        ):
            if word == "pretoken" and words[index + 1:] == ["stage", "status"]:
                continue
            if _canonical_credential_identifier_is_sensitive(
                word + "".join(words[index + 1:])
            ):
                return True
    for start in range(len(words)):
        for compound in _HUMAN_CREDENTIAL_LABELS:
            end = start + len(compound)
            if tuple(words[start:end]) != compound:
                continue
            suffix_words = words[end:]
            if compound == ("secret",) and suffix_words[:1] == ["sauce"]:
                continue
            if compound == ("secret",) and suffix_words[:1] == ["guide"]:
                continue
            if tuple(words[start:]) in {
                ("password", "policy", "value"),
                ("token", "count", "value"),
            }:
                continue
            if suffix_words:
                sensitive_suffixes = [
                    word
                    for word in suffix_words
                    if word in _CREDENTIAL_SENSITIVE_DESCRIPTORS
                ]
                descriptor_sentence = bool(
                    delimiter == ":"
                    and sensitive_suffixes == ["json"]
                    and "can" in suffix_words
                    and "be" in suffix_words
                )
                if sensitive_suffixes and not descriptor_sentence:
                    return True
                if _credential_metadata_suffix("".join(suffix_words)):
                    continue
                if (
                    suffix_words[0] in _CREDENTIAL_METADATA_TERMS
                    and all(
                        word in _CREDENTIAL_METADATA_TERMS
                        or word in _HUMAN_METADATA_PROSE_TERMS
                        for word in suffix_words
                    )
                ):
                    continue
            identifier = "".join(words[start:])
            if _canonical_credential_identifier_is_sensitive(identifier):
                return True
    return False


def _human_credential_candidate_positions(value: str) -> list[int]:
    positions = {
        match.start()
        for match in _HUMAN_COMPOUND_PATTERN.finditer(value)
    }
    for match in re.finditer(r"(?:[^\W\d]|_)(?:[\w-])*", value, re.UNICODE):
        canonical = "".join(
            character
            for character in unicodedata.normalize("NFKC", match.group(0)).casefold()
            if character.isalnum()
        )
        if _compact_credential_token_is_candidate(match.group(0)):
            positions.add(match.start())
    return sorted(positions)


def _overlength_human_candidate_is_safe(
    value: str,
    position: int,
    delimiter_position: int,
    delimiter: str,
) -> bool:
    candidate = unicodedata.normalize(
        "NFKC",
        value[position:delimiter_position],
    )
    topic_match = _SAFE_OVERLENGTH_TOPIC_PATTERN.match(candidate)
    if topic_match is None:
        compact_topic_match = _SAFE_OVERLENGTH_COMPACT_TOPIC_PATTERN.match(
            candidate
        )
        if (
            compact_topic_match is not None
            and _compact_credential_token_is_candidate(
                compact_topic_match.group("label")
            )
        ):
            topic_match = compact_topic_match
    if topic_match is None:
        return False
    tail_text = candidate[topic_match.end():]
    tail_matches = list(re.finditer(
        r"(?:[^\W\d]|_)(?:[\w-])*",
        tail_text.casefold(),
        re.UNICODE,
    ))
    cursor = 0
    for tail_match in tail_matches:
        separator = tail_text[cursor:tail_match.start()]
        if separator and not separator.isspace():
            return False
        cursor = tail_match.end()
    remainder = tail_text[cursor:]
    if remainder and not remainder.isspace():
        return False
    tail_words = [tail_match.group(0) for tail_match in tail_matches]
    if not tail_words:
        return delimiter == ":" and not tail_text.strip()
    if any(word in _CREDENTIAL_SENSITIVE_DESCRIPTORS for word in tail_words):
        return False
    allowed_tail_words = _CREDENTIAL_METADATA_TERMS | _HUMAN_METADATA_PROSE_TERMS
    if any(word not in allowed_tail_words for word in tail_words):
        return False
    return tail_words[-1] in _CREDENTIAL_METADATA_TERMS


def _secret_shaped_text(value: str) -> bool:
    if _SECRET_TOKEN_TEXT.search(value):
        return True
    identifier_characters = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    human_stem_positions = _human_credential_candidate_positions(value)
    compound_boundary_positions = {
        position
        for match in _HUMAN_COMPOUND_PATTERN.finditer(value)
        for position in range(match.start(), match.end())
        if value[position] in ":=\r\n.,;?!…—–"
    }
    human_stem_cursor = 0
    latest_human_stem = -161
    human_clause_start = 0
    human_parenthesis_depth = 0
    for position, character in enumerate(value):
        if position in compound_boundary_positions:
            continue
        if character not in ":=":
            if character == "(":
                human_parenthesis_depth += 1
            elif character == ")" and human_parenthesis_depth > 0:
                human_parenthesis_depth -= 1
            if (
                human_parenthesis_depth == 0
                and (
                    character in "\r\n;?!…—–"
                    or (
                        character in ".,"
                        and not (
                            position > 0
                            and position + 1 < len(value)
                            and value[position - 1].isalnum()
                            and value[position + 1].isalnum()
                        )
                    )
                )
            ):
                human_clause_start = position + 1
            continue
        current_clause_start = human_clause_start
        human_clause_start = position + 1
        while (
            human_stem_cursor < len(human_stem_positions)
            and human_stem_positions[human_stem_cursor] < position
        ):
            latest_human_stem = human_stem_positions[human_stem_cursor]
            human_stem_cursor += 1
        old_candidate_start = bisect.bisect_left(
            human_stem_positions,
            current_clause_start,
        )
        old_candidate_end = bisect.bisect_left(
            human_stem_positions,
            position - 160,
        )
        if old_candidate_start < old_candidate_end:
            comparison_operator = bool(
                character == "="
                and (
                    (position + 1 < len(value) and value[position + 1] == "=")
                    or (position > 0 and value[position - 1] in "!<>")
                )
            )
            if not comparison_operator:
                for old_candidate in human_stem_positions[
                    old_candidate_start:old_candidate_end
                ]:
                    if not _overlength_human_candidate_is_safe(
                        value,
                        old_candidate,
                        position,
                        character,
                    ):
                        return True
        right = position + 1
        while right < len(value) and value[right] in " \t\"'":
            right += 1
        if right >= len(value) or value[right] in "\r\n":
            continue
        left = position - 1
        while left >= 0 and value[left] in " \t\"'":
            left -= 1
        end = left + 1
        if (
            left >= 0
            and (value[left].isalnum() or value[left] in "_-)]")
            and latest_human_stem >= max(current_clause_start, position - 160)
        ):
            human_window = value[
                max(current_clause_start, position - 160):position
            ]
            if _human_credential_phrase_is_sensitive(human_window, character):
                return True
        recent_open = value.rfind("[", max(0, position - 512), position)
        recent_close = value.rfind("]", max(0, position - 512), position)
        closing_ahead = value.find("]", position + 1, min(len(value), position + 513))
        if character == ":" and recent_open > recent_close and closing_ahead >= 0:
            bracket_key_text = _bounded_bracket_key_text(value, recent_open, position)
            if bracket_key_text is None:
                return True
            if bracket_key_text and _secret_shaped_text(f"{bracket_key_text}=x"):
                return True
            bracket_key_left = left
            bracket_key_scanned = 0
            while (
                bracket_key_left >= 0
                and value[bracket_key_left] in identifier_characters
                and bracket_key_scanned < 160
            ):
                bracket_key_left -= 1
                bracket_key_scanned += 1
            if (
                bracket_key_left >= 0
                and value[bracket_key_left] in identifier_characters
            ):
                return True
            bracket_key = value[bracket_key_left + 1:end]
            if bracket_key and _credential_identifier_is_sensitive(bracket_key):
                return True
            continue
        if character == ":":
            port_end = right
            while port_end < len(value) and value[port_end].isdigit() and port_end - right < 5:
                port_end += 1
            port_text = value[right:port_end]
            port_boundary = port_end == len(value) or not value[port_end].isalnum()
            if port_text and int(port_text) <= 65535 and port_boundary:
                host = ""
                if left >= 0 and value[left] == "]":
                    host_start = value.rfind("[", max(0, left - 80), left)
                    if host_start >= 0:
                        host = value[host_start + 1:left]
                else:
                    host_left = left
                    host_scanned = 0
                    while (
                        host_left >= 0
                        and value[host_left] in identifier_characters
                        and host_scanned < 253
                    ):
                        host_left -= 1
                        host_scanned += 1
                    if host_left >= 0 and value[host_left] in identifier_characters:
                        host = ""
                    else:
                        host = value[host_left + 1:end]
                if host and ("." in host or ":" in host):
                    if _explicit_dotted_credential_structure(host):
                        pass
                    elif _public_network_host(host):
                        continue
                    else:
                        return True
        has_bracket_lhs, bracket_expression = _bounded_bracket_lhs(value, position)
        if has_bracket_lhs:
            if bracket_expression is None:
                return True
            chain_segments = _property_chain_segments(bracket_expression)
            if chain_segments is None:
                return True
            if _credential_identifier_is_sensitive(".".join(chain_segments)):
                return True
            continue
        scanned = 0
        while left >= 0 and value[left] in identifier_characters and scanned < 160:
            left -= 1
            scanned += 1
        if left >= 0 and value[left] in identifier_characters:
            return True
        token = value[left + 1:end]
        if not token:
            continue
        identifiers = [token]
        token_canonical = token.casefold().replace("_", "").replace("-", "")
        if token_canonical == "key":
            while left >= 0 and value[left] in " \t":
                left -= 1
            prior_end = left + 1
            prior_scanned = 0
            while left >= 0 and value[left] in identifier_characters and prior_scanned < 160:
                left -= 1
                prior_scanned += 1
            if left >= 0 and value[left] in identifier_characters:
                return True
            prior = value[left + 1:prior_end].casefold().replace("_", "").replace("-", "")
            if prior:
                identifiers.append(f"{prior}_key")
        if token_canonical in _CREDENTIAL_SENSITIVE_DESCRIPTORS:
            prior_words: list[str] = []
            cursor = left
            for _ in range(2):
                while cursor >= 0 and value[cursor] in " \t":
                    cursor -= 1
                prior_end = cursor + 1
                prior_scanned = 0
                while (
                    cursor >= 0
                    and value[cursor] in identifier_characters
                    and prior_scanned < 160
                ):
                    cursor -= 1
                    prior_scanned += 1
                if cursor >= 0 and value[cursor] in identifier_characters:
                    return True
                prior_word = value[cursor + 1:prior_end]
                if not prior_word:
                    break
                prior_words.insert(0, prior_word)
            if prior_words:
                immediate = prior_words[-1].casefold().replace("_", "").replace("-", "")
                if immediate in _CREDENTIAL_LABELS:
                    identifiers.append(f"{prior_words[-1]}_{token}")
                elif (
                    immediate == "key"
                    and len(prior_words) == 2
                    and prior_words[0].casefold() in {"api", "access", "private"}
                ):
                    identifiers.append("_".join([*prior_words, token]))
        for identifier in identifiers:
            if _credential_identifier_is_sensitive(identifier):
                return True
    return False


def _safe_query_fragment_text(value: str) -> bool:
    if _secret_shaped_text(value) or _PRIVATE_KEY_BLOCK.search(value):
        return False
    slash_value = re.sub(r"\\(?=[\"'])", "", value)
    slash_value = re.sub(
        r"(?<=[A-Za-z0-9_)])\s+/{1,2}\s+(?=[A-Za-z0-9_(])",
        " ",
        slash_value,
    )
    for token in _slash_tokens(slash_value):
        cleaned = token.strip(".,;!?()[]{}<>\"'`*")
        if not (
            _SAFE_NUMERIC_SLASH_TOKEN.fullmatch(cleaned)
            or _SAFE_INITIAL_SLASH_TOKEN.fullmatch(cleaned)
        ):
            return False
    return True


def _decoded_text_layers(value: str, *, plus: bool) -> list[str] | None:
    """Decode nested percent escapes to a small fixed point or fail closed."""
    decoder = unquote_plus if plus else unquote
    layers = [value]
    for _ in range(8):
        decoded = decoder(layers[-1])
        if decoded == layers[-1]:
            return layers
        layers.append(decoded)
    return None


def _safe_decoded_query_fragment(value: str) -> bool:
    layers = _decoded_text_layers(value, plus=True)
    if layers is None:
        return False
    return all(
        _safe_query_fragment_text(variant)
        for layer in layers
        for variant in _comparison_variants(layer)
    )


def _safe_url_parameters(value: str) -> bool:
    try:
        items = parse_qsl(
            value,
            keep_blank_values=True,
            strict_parsing=False,
            max_num_fields=MAX_PUBLIC_URL_QUERY_FIELDS,
        )
    except ValueError:
        return False
    for key, item in items:
        key_layers = _decoded_text_layers(key, plus=True)
        item_layers = _decoded_text_layers(item, plus=True)
        if key_layers is None or item_layers is None:
            return False
        key_variants = [variant for layer in key_layers for variant in _comparison_variants(layer)]
        item_variants = [variant for layer in item_layers for variant in _comparison_variants(layer)]
        if not all(_safe_query_fragment_text(variant) for variant in (*key_variants, *item_variants)):
            return False
        if any(
            _secret_shaped_text(f"{key_variant}={item_variant}")
            for key_variant in key_variants
            for item_variant in item_variants
        ):
            return False
    return True


def _safe_public_web_url(value: str) -> bool:
    if value.count("://") != 1 or re.search(r"[\\|^]", value):
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname or ""
        _ = parsed.port
    except ValueError:
        return False
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return False
    if not _public_network_host(hostname):
        return False
    if re.search(r"%(?![0-9A-Fa-f]{2})", f"{parsed.path}{parsed.query}{parsed.fragment}"):
        return False
    path_layers = _decoded_text_layers(parsed.path, plus=False)
    if path_layers is None:
        return False
    for index, path_layer in enumerate(path_layers):
        for path_variant in _comparison_variants(path_layer):
            if (
                "://" in path_variant
                or "\\" in path_variant
                or _secret_shaped_text(path_variant)
                or _PRIVATE_KEY_BLOCK.search(path_variant)
                or (index > 0 and "//" in path_variant)
                or re.search(r"(?:^|/)[A-Za-z]:/", path_variant)
            ):
                return False
    if not _safe_url_parameters(parsed.query):
        return False
    if "=" in parsed.fragment or "&" in parsed.fragment:
        fragment_safe = _safe_url_parameters(parsed.fragment)
    else:
        fragment_safe = _safe_decoded_query_fragment(parsed.fragment)
    if not fragment_safe:
        return False
    return True


def _web_url_spans(token: str) -> list[tuple[int, int, str]] | None:
    """Return wrapper-aware URL spans without truncating valid path punctuation."""
    spans: list[tuple[int, int, str]] = []
    consumed_until = 0
    for match in _WEB_URL_START.finditer(token):
        start = match.start()
        if start < consumed_until:
            continue
        authority_end = match.end()
        prefix = token[max(0, start - 2):start]
        if prefix.endswith("]("):
            depth = 0
            end = len(token)
            for index in range(authority_end, len(token)):
                character = token[index]
                if character == "(":
                    depth += 1
                elif character == ")":
                    if depth == 0:
                        end = index
                        break
                    depth -= 1
        elif prefix.endswith("`"):
            marker = token.find("`", authority_end)
            end = len(token) if marker < 0 else marker
        elif prefix.endswith("**"):
            marker = token.find("**", authority_end)
            end = len(token) if marker < 0 else marker
        else:
            depth = 0
            end = authority_end
            while end < len(token):
                character = token[end]
                if character.isspace() or character in "<>\"`[]{}|^":
                    break
                if character == "(":
                    depth += 1
                elif character == ")":
                    if depth == 0:
                        break
                    depth -= 1
                end += 1
            while end > authority_end and token[end - 1] in ".,;!?":
                end -= 1
        if len(spans) >= MAX_PUBLIC_URL_SPANS:
            return None
        spans.append((start, end, token[start:end]))
        consumed_until = end
    return spans


def _validated_public_url_residual(value: str) -> str | None:
    spans = _web_url_spans(value)
    if spans is None:
        return None
    if not spans:
        return value
    residual_parts: list[str] = []
    cursor = 0
    for start, end, url in spans:
        if not _safe_public_web_url(url):
            return None
        residual_parts.append(value[cursor:start])
        cursor = end
    residual_parts.append(value[cursor:])
    return "".join(residual_parts)


def _contains_private_public_text(value: Any) -> bool:
    """Reject browser-visible path and credential shapes, not ordinary prose."""
    if isinstance(value, str):
        try:
            current = value
            for _ in range(9):
                residual = _validated_public_url_residual(current)
                if residual is None:
                    return True
                for variant in _comparison_variants(current, strip_markers=True):
                    variant_residual = _validated_public_url_residual(variant)
                    if variant_residual is None or not _safe_query_fragment_text(variant_residual):
                        return True
                decoded = unquote(residual)
                if decoded == residual:
                    return False
                current = decoded
            return True
        except _ComparisonNormalizationOverflow:
            return True
    if isinstance(value, list):
        return any(_contains_private_public_text(item) for item in value)
    if type(value) is dict:
        return any(
            _contains_private_public_text(key)
            or _contains_private_public_text(item)
            for key, item in value.items()
        )
    return False


def browser_text_is_private(value: Any) -> bool:
    """Validate derived browser text with the remote-session public boundary."""
    return _contains_private_public_text(value)


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

    def _request_json(
        self,
        path: str,
        *,
        authenticated: bool,
        root_list_limits: Mapping[str, int] | None = None,
    ) -> Mapping[str, Any]:
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
            shape_ok = (
                _safe_root_list_shape(payload, list_limits=root_list_limits)
                if root_list_limits is not None
                else _safe_shape(payload)
            )
            if type(payload) is not dict or not shape_ok:
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

    @staticmethod
    def _validated_session_id(value: Any) -> str:
        if not isinstance(value, str) or not _SESSION_ID.fullmatch(value):
            raise RemoteHermesError("remote_session_schema_invalid")
        return value

    def _session_private_values(self, session_id: str) -> tuple[str, ...]:
        endpoint_parts = urlsplit(self.endpoint)
        hostname = endpoint_parts.hostname or ""
        private_hostname = "" if hostname in {"localhost", "127.0.0.1", "::1"} else hostname
        distinctive_netloc = endpoint_parts.netloc if endpoint_parts.netloc != hostname else ""
        return (
            self.api_key,
            self.endpoint,
            private_hostname,
            distinctive_netloc,
            session_id,
        )

    def _contains_private_session_text(self, value: Any, session_id: str) -> bool:
        return _contains_private_text(value, self._session_private_values(session_id))

    def _session_json_request(self, path: str) -> Mapping[str, Any]:
        list_path = f"/api/sessions?limit={SESSION_LIST_LIMIT}&offset=0&include_children=false"
        detail_path = re.fullmatch(r"/api/sessions/([A-Za-z0-9][A-Za-z0-9_.:-]{0,199})", path)
        messages_path = re.fullmatch(
            r"/api/sessions/([A-Za-z0-9][A-Za-z0-9_.:-]{0,199})/messages",
            path,
        )
        if path != list_path and detail_path is None and messages_path is None:
            raise RemoteHermesError("remote_path_not_allowed")
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Mentat/remote-hermes-v1",
        }
        connection = self._connection()
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            status = int(response.status)
            if 300 <= status <= 399:
                raise RemoteHermesError("remote_redirect_refused")
            if status in {401, 403}:
                raise RemoteHermesError("remote_authentication_failed")
            if status == 404 and (detail_path is not None or messages_path is not None):
                raise RemoteHermesError("remote_session_not_found")
            if status != 200:
                raise RemoteHermesError("remote_session_unavailable")
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
                payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
            except (UnicodeError, ValueError, RecursionError) as exc:
                raise RemoteHermesError("remote_response_invalid") from exc
            if type(payload) is not dict or len(payload) > 32:
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
    def _session_number(value: Any, *, integer: bool = False) -> int | float | None:
        if value is None:
            return None
        if integer:
            if type(value) is not int or not (0 <= value <= 10**9):
                raise RemoteHermesError("remote_session_schema_invalid")
            return value
        if type(value) not in {int, float} or not math.isfinite(float(value)) or not (0 <= float(value) <= 10**10):
            raise RemoteHermesError("remote_session_schema_invalid")
        return float(value)

    def _normalize_session(self, value: Any, *, expected_id: str | None = None) -> dict[str, Any]:
        if type(value) is not dict or len(value) > 64:
            raise RemoteHermesError("remote_session_schema_invalid")
        session_id = self._validated_session_id(value.get("id"))
        if expected_id is not None and session_id != expected_id:
            raise RemoteHermesError("remote_session_binding_changed")
        title = value.get("title")
        if title is None:
            title = "Untitled session"
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or "\x00" in title:
            raise RemoteHermesError("remote_session_schema_invalid")
        title = re.sub(r"\s+", " ", title).strip()
        model = value.get("model")
        if model is not None and (
            not isinstance(model, str)
            or not _SAFE_MODEL.fullmatch(model)
            or model.startswith("/")
            or ".." in model
            or "://" in model
            or "\\" in model
        ):
            raise RemoteHermesError("remote_session_schema_invalid")
        if model is not None and _secret_shaped_text(model):
            raise RemoteHermesError("remote_private_reflection")
        normalized = {
            "upstream_id": session_id,
            "title": title,
            "model": model,
            "started_at": self._session_number(value.get("started_at")),
            "ended_at": self._session_number(value.get("ended_at")),
            "last_active": self._session_number(value.get("last_active")),
            "message_count": self._session_number(value.get("message_count"), integer=True),
            "tool_call_count": self._session_number(value.get("tool_call_count"), integer=True),
            "input_tokens": self._session_number(value.get("input_tokens"), integer=True),
            "output_tokens": self._session_number(value.get("output_tokens"), integer=True),
        }
        preview = value.get("preview")
        if preview is None:
            preview = ""
        if not isinstance(preview, str) or len(preview) > 200 or "\x00" in preview:
            raise RemoteHermesError("remote_session_schema_invalid")
        normalized["preview"] = re.sub(r"\s+", " ", preview).strip()
        normalized["status"] = "active" if normalized["ended_at"] is None else "ended"
        lineage_root = value.get("_lineage_root_id")
        if lineage_root is not None:
            normalized["lineage_root_id"] = self._validated_session_id(lineage_root)
        parent_id = value.get("parent_session_id")
        if parent_id is not None:
            normalized["parent_session_id"] = self._validated_session_id(parent_id)
        cost = value.get("actual_cost_usd")
        if cost is None:
            cost = value.get("estimated_cost_usd")
        if cost is not None:
            if type(cost) not in {int, float} or not math.isfinite(float(cost)) or not (0 <= float(cost) <= 10**9):
                raise RemoteHermesError("remote_session_schema_invalid")
            normalized["estimated_cost_usd"] = float(cost)
        public_fields = {
            key: item
            for key, item in normalized.items()
            if key not in {"upstream_id", "lineage_root_id", "parent_session_id"}
        }
        identity_values = tuple(
            item
            for item in (
                session_id,
                normalized.get("lineage_root_id"),
                normalized.get("parent_session_id"),
            )
            if isinstance(item, str)
        )
        if _contains_private_text_variants(
            public_fields,
            (
                *(self._session_private_values(session_id)),
                *identity_values,
            ),
        ) or _contains_private_public_text([title, normalized["preview"]]):
            raise RemoteHermesError("remote_private_reflection")
        return normalized

    @staticmethod
    def _session_message_text(value: Any) -> str | None:
        """Keep only bounded textual content from Hermes' persisted message shapes."""
        if value is None:
            return None
        if isinstance(value, str):
            text = value
        elif isinstance(value, (list, dict)):
            parts = [value] if isinstance(value, dict) else value
            if len(parts) > SESSION_CONTENT_PART_LIMIT:
                raise RemoteHermesError("remote_session_schema_invalid")
            text_parts: list[str] = []
            for part in parts:
                if isinstance(part, str):
                    text_parts.append(part)
                    continue
                if type(part) is not dict or len(part) > 8:
                    raise RemoteHermesError("remote_session_schema_invalid")
                part_type = part.get("type")
                if not isinstance(part_type, str) or len(part_type) > 32:
                    raise RemoteHermesError("remote_session_schema_invalid")
                if part_type not in {"text", "input_text", "output_text"}:
                    continue
                part_text = part.get("text")
                if not isinstance(part_text, str):
                    raise RemoteHermesError("remote_session_schema_invalid")
                text_parts.append(part_text)
            if not text_parts:
                return None
            text = "\n".join(text_parts)
        else:
            raise RemoteHermesError("remote_session_schema_invalid")
        if len(text) > SESSION_CONTENT_LIMIT or "\x00" in text:
            raise RemoteHermesError("remote_session_schema_invalid")
        return text

    def require_session_resource_capabilities(self) -> dict[str, Any]:
        discovery = self.discover()
        if "session_resources" not in set(discovery.get("capabilities") or ()):
            raise RemoteHermesError("remote_session_capability_unavailable")
        return discovery

    def list_sessions(self) -> dict[str, Any]:
        payload = self._session_json_request(
            f"/api/sessions?limit={SESSION_LIST_LIMIT}&offset=0&include_children=false"
        )
        data = payload.get("data")
        if (
            set(payload) != {"object", "data", "limit", "offset", "has_more"}
            or payload.get("object") != "list"
            or type(data) is not list
            or len(data) > SESSION_LIST_LIMIT
            or payload.get("limit") != SESSION_LIST_LIMIT
            or payload.get("offset") != 0
            or type(payload.get("has_more")) is not bool
        ):
            raise RemoteHermesError("remote_session_schema_invalid")
        sessions = [self._normalize_session(item) for item in data]
        session_ids = [item["upstream_id"] for item in sessions]
        if len(set(session_ids)) != len(session_ids):
            raise RemoteHermesError("remote_session_schema_invalid")
        all_identity_values = tuple(
            dict.fromkeys(
                item
                for session in sessions
                for item in (
                    session.get("upstream_id"),
                    session.get("lineage_root_id"),
                    session.get("parent_session_id"),
                )
                if isinstance(item, str)
            )
        )
        for session in sessions:
            public_fields = {
                key: item
                for key, item in session.items()
                if key not in {"upstream_id", "lineage_root_id", "parent_session_id"}
            }
            if _contains_private_text_variants(public_fields, all_identity_values):
                raise RemoteHermesError("remote_private_reflection")
        return {
            "sessions": sessions,
            "truncated": payload["has_more"],
        }

    def get_session(self, session_id: str) -> dict[str, Any]:
        session_id = self._validated_session_id(session_id)
        payload = self._session_json_request(f"/api/sessions/{session_id}")
        if payload.get("object") != "hermes.session":
            raise RemoteHermesError("remote_session_schema_invalid")
        return self._normalize_session(payload.get("session"), expected_id=session_id)

    def get_session_messages(
        self,
        session_id: str,
        *,
        structural_ids: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        session_id = self._validated_session_id(session_id)
        if not isinstance(structural_ids, tuple) or len(structural_ids) > 40:
            raise RemoteHermesError("remote_session_schema_invalid")
        private_session_ids = tuple(
            dict.fromkeys(
                [session_id, *(self._validated_session_id(item) for item in structural_ids)]
            )
        )
        payload = self._session_json_request(f"/api/sessions/{session_id}/messages")
        data = payload.get("data")
        if (
            set(payload) != {"object", "session_id", "data"}
            or payload.get("object") != "list"
            or type(data) is not list
            or len(data) > SESSION_MESSAGE_LIMIT
        ):
            raise RemoteHermesError("remote_session_schema_invalid")
        resolved_id = self._validated_session_id(payload.get("session_id"))
        if resolved_id != session_id:
            raise RemoteHermesError("remote_session_binding_changed")
        messages: list[dict[str, Any]] = []
        for item in data:
            if type(item) is not dict or len(item) > 32:
                raise RemoteHermesError("remote_session_schema_invalid")
            role = item.get("role")
            if role not in {"user", "assistant"}:
                continue
            message_session_id = item.get("session_id")
            if message_session_id is not None and message_session_id != resolved_id:
                raise RemoteHermesError("remote_session_binding_changed")
            timestamp = self._session_number(item.get("timestamp"))
            content = self._session_message_text(item.get("content"))
            if content is None:
                continue
            if _contains_private_text_variants(
                content,
                (
                    *self._session_private_values(session_id),
                    *private_session_ids,
                ),
            ) or _contains_private_public_text(content):
                raise RemoteHermesError("remote_private_reflection")
            messages.append({"role": role, "content": content, "timestamp": timestamp})
        return messages

    def _contains_private_inventory_text(self, value: Any) -> bool:
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
        if _contains_private_text(
            value,
            (
                self.api_key,
                self.endpoint,
                distinctive_hostname,
                distinctive_netloc,
            ),
        ):
            return True
        if not short_hostname:
            return False
        hostname_token = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(short_hostname)}(?![A-Za-z0-9])",
            re.IGNORECASE,
        )

        def contains_hostname(item: Any) -> bool:
            if isinstance(item, str):
                return hostname_token.search(item) is not None
            if isinstance(item, dict):
                return any(contains_hostname(key) or contains_hostname(child) for key, child in item.items())
            if isinstance(item, (list, tuple)):
                return any(contains_hostname(child) for child in item)
            return False

        return contains_hostname(value)

    def _normalize_skill_inventory(self, payload: Any) -> list[dict[str, Any]]:
        if type(payload) is not dict:
            raise RemoteHermesError("remote_capability_inventory_schema_invalid")
        data = payload.get("data")
        if (
            set(payload) != {"object", "data"}
            or payload.get("object") != "list"
            or type(data) is not list
        ):
            raise RemoteHermesError("remote_capability_inventory_schema_invalid")
        skills: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in data:
            if type(value) is not dict or len(value) > 32:
                raise RemoteHermesError("remote_capability_inventory_schema_invalid")
            name = _inventory_text(value.get("name"), maximum=120)
            if not _INVENTORY_IDENTIFIER.fullmatch(name) or name in seen:
                raise RemoteHermesError("remote_capability_inventory_schema_invalid")
            seen.add(name)
            category_value = value.get("category") if "category" in value else None
            if category_value is not None:
                _inventory_text(
                    category_value,
                    maximum=120,
                    reject_paths=False,
                )
            description_value = value.get("description") if "description" in value else None
            if description_value is not None:
                _inventory_text(
                    description_value,
                    maximum=1024,
                    allow_empty=True,
                    reject_paths=False,
                )
            normalized = {"name": name}
            if self._contains_private_inventory_text(normalized):
                raise RemoteHermesError("remote_capability_inventory_private")
            skills.append(normalized)
        return sorted(
            skills,
            key=lambda item: item["name"].casefold(),
        )

    def _normalize_toolset_inventory(self, payload: Any) -> list[dict[str, Any]]:
        if type(payload) is not dict:
            raise RemoteHermesError("remote_capability_inventory_schema_invalid")
        data = payload.get("data")
        if (
            set(payload) != {"object", "platform", "data"}
            or payload.get("object") != "list"
            or payload.get("platform") != "api_server"
            or type(data) is not list
        ):
            raise RemoteHermesError("remote_capability_inventory_schema_invalid")
        toolsets: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_tool_references = 0
        for value in data:
            if type(value) is not dict or len(value) > 32:
                raise RemoteHermesError("remote_capability_inventory_schema_invalid")
            name = _inventory_text(value.get("name"), maximum=120)
            if not _INVENTORY_IDENTIFIER.fullmatch(name) or name in seen:
                raise RemoteHermesError("remote_capability_inventory_schema_invalid")
            seen.add(name)
            label_value = value.get("label") if "label" in value else None
            if label_value is not None:
                _inventory_text(
                    label_value,
                    maximum=160,
                    reject_paths=False,
                )
            description_value = value.get("description") if "description" in value else None
            if description_value is not None:
                _inventory_text(
                    description_value,
                    maximum=1024,
                    allow_empty=True,
                    reject_paths=False,
                )
            enabled = value.get("enabled")
            tools = value.get("tools")
            if type(enabled) is not bool or type(tools) is not list or len(tools) > MAX_REMOTE_TOOLS_PER_TOOLSET:
                raise RemoteHermesError("remote_capability_inventory_schema_invalid")
            normalized_tools: list[str] = []
            for tool in tools:
                tool_name = _inventory_text(tool, maximum=120)
                if not _INVENTORY_IDENTIFIER.fullmatch(tool_name):
                    raise RemoteHermesError("remote_capability_inventory_schema_invalid")
                normalized_tools.append(tool_name)
            if len(set(normalized_tools)) != len(normalized_tools):
                raise RemoteHermesError("remote_capability_inventory_schema_invalid")
            total_tool_references += len(normalized_tools)
            if total_tool_references > MAX_REMOTE_TOOL_REFERENCES:
                raise RemoteHermesError("remote_capability_inventory_schema_invalid")
            normalized = {
                "name": name,
                "enabled": enabled,
                "tool_count": len(normalized_tools),
            }
            if self._contains_private_inventory_text(normalized):
                raise RemoteHermesError("remote_capability_inventory_private")
            toolsets.append(normalized)
        return sorted(
            toolsets,
            key=lambda item: (not item["enabled"], item["name"].casefold()),
        )

    def read_capability_inventory(self) -> dict[str, Any]:
        capabilities = self._trusted_capabilities()
        if "skills_api" not in set(capabilities.get("features") or ()):
            raise RemoteHermesError("remote_capability_inventory_unavailable")
        if capabilities.get("capability_inventory_endpoints_valid") is not True:
            raise RemoteHermesError("remote_schema_unsupported")
        skills_payload = self._request_json(
            "/v1/skills",
            authenticated=True,
            root_list_limits={"data": MAX_REMOTE_SKILLS},
        )
        toolsets_payload = self._request_json(
            "/v1/toolsets",
            authenticated=True,
            root_list_limits={"data": MAX_REMOTE_TOOLSETS},
        )
        skills = self._normalize_skill_inventory(skills_payload)
        toolsets = self._normalize_toolset_inventory(toolsets_payload)
        return {
            "skills": skills,
            "toolsets": toolsets,
            "skill_count": len(skills),
            "toolset_count": len(toolsets),
            "enabled_toolset_count": sum(1 for item in toolsets if item["enabled"]),
        }

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

    def _contract_json_request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int = 200,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Call one prevalidated contract path without exposing generic HTTP."""
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "Mentat/remote-hermes-v1",
        }
        encoded: bytes | None = None
        if body is not None:
            try:
                encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
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
                payload = json.loads(raw.decode("utf-8"), parse_constant=_reject_json_constant)
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

    def _require_features(self, *required: str) -> None:
        capabilities = self._trusted_capabilities()
        if not set(required).issubset(set(capabilities.get("features") or ())):
            raise RemoteHermesError("remote_run_capability_unavailable")

    def get_continuation_descriptor(self, session_id: str) -> dict[str, Any]:
        session_id = self._validated_session_id(session_id)
        self._require_features("run_session_continuation", "run_session_continuation_exact_revision", "run_session_continuation_stoppable")
        payload = self._contract_json_request("GET", f"/v1/sessions/{session_id}/continuation")
        if (
            payload.get("object") != "hermes.session.continuation"
            or payload.get("version") != 1
            or self._validated_session_id(payload.get("session_id")) != session_id
            or not isinstance(payload.get("revision"), str)
            or not _CONTINUATION_REVISION.fullmatch(payload["revision"])
        ):
            raise RemoteHermesError("remote_session_schema_invalid")
        return {"version": 1, "session_id": session_id, "revision": payload["revision"]}

    def submit_continuation(self, user_input: str, descriptor: Mapping[str, Any]) -> dict[str, str]:
        if not isinstance(descriptor, Mapping):
            raise RemoteHermesError("remote_run_request_invalid")
        session_id = self._validated_session_id(descriptor.get("session_id"))
        revision = descriptor.get("revision")
        if descriptor.get("version") != 1 or not isinstance(revision, str) or not _CONTINUATION_REVISION.fullmatch(revision):
            raise RemoteHermesError("remote_run_request_invalid")
        self._require_features("run_session_continuation", "run_session_continuation_exact_revision", "run_session_continuation_stoppable")
        return self._submit_run_payload(user_input, {"version": 1, "session_id": session_id, "revision": revision})

    def respond_to_approval(self, run_id: str, request_id: str, choice: str) -> dict[str, Any]:
        run_id = self._validated_run_id(run_id)
        if not isinstance(request_id, str) or not _APPROVAL_REQUEST_ID.fullmatch(request_id) or choice not in {"once", "deny"}:
            raise RemoteHermesError("remote_run_request_invalid")
        self._require_features("run_approval_response", "run_approval_request_binding", "run_approval_structured_preview")
        payload = self._contract_json_request("POST", f"/v1/runs/{run_id}/approval", body={"request_id": request_id, "choice": choice})
        if payload.get("object") != "hermes.run.approval_response" or payload.get("run_id") != run_id or payload.get("request_id") != request_id or payload.get("choice") != choice or type(payload.get("resolved")) is not int or payload["resolved"] < 1:
            raise RemoteHermesError("remote_run_schema_invalid")
        return {"request_id": request_id, "choice": choice, "resolved": payload["resolved"]}

    def respond_to_clarification(self, run_id: str, request_id: str, response: Mapping[str, Any]) -> dict[str, Any]:
        run_id = self._validated_run_id(run_id)
        if not isinstance(request_id, str) or not _CLARIFICATION_REQUEST_ID.fullmatch(request_id) or not isinstance(response, Mapping):
            raise RemoteHermesError("remote_run_request_invalid")
        response_type = response.get("type")
        if response_type == "choice":
            choice_id = response.get("choice_id")
            if not isinstance(choice_id, str) or not re.fullmatch(r"choice-[1-4]", choice_id):
                raise RemoteHermesError("remote_run_request_invalid")
            body_response = {"type": "choice", "choice_id": choice_id}
        elif response_type == "text":
            text = response.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 2_000 or "\x00" in text:
                raise RemoteHermesError("remote_run_request_invalid")
            body_response = {"type": "text", "text": text.strip()}
        else:
            raise RemoteHermesError("remote_run_request_invalid")
        self._require_features("run_clarification_response", "run_clarification_request_binding", "clarification_events")
        payload = self._contract_json_request("POST", f"/v1/runs/{run_id}/clarification", body={"request_id": request_id, "response": body_response})
        if payload.get("object") != "hermes.run.clarification_response" or payload.get("run_id") != run_id or payload.get("request_id") != request_id or payload.get("type") != response_type:
            raise RemoteHermesError("remote_run_schema_invalid")
        return {"request_id": request_id, "type": response_type, **({"choice_id": body_response["choice_id"]} if response_type == "choice" else {})}

    def require_console_run_capabilities(self) -> dict[str, Any]:
        discovery = self.discover()
        required = {"run_submission", "run_status", "run_events_sse", "run_stop"}
        if not required.issubset(set(discovery.get("capabilities") or ())):
            raise RemoteHermesError("remote_run_capability_unavailable")
        return discovery

    def require_kanban_capabilities(self) -> dict[str, Any]:
        """Return trusted capabilities only when the fixed Kanban contract is complete."""
        capabilities = self._trusted_capabilities()
        required = {
            "kanban_api",
            "kanban_api_revisioned",
            "kanban_api_idempotency",
            "kanban_api_requires_api_key",
        }
        if not required.issubset(set(capabilities.get("features") or ())):
            raise RemoteHermesError("remote_run_capability_unavailable")
        return capabilities

    def _submit_run_payload(
        self,
        user_input: str,
        continuation: Mapping[str, Any] | None = None,
        images: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        if (
            not isinstance(user_input, str)
            or not user_input.strip()
            or len(user_input) > 20_000
            or "\x00" in user_input
        ):
            raise RemoteHermesError("remote_run_request_invalid")
        body: dict[str, Any] = {"input": user_input}
        if continuation is not None:
            body["continuation"] = dict(continuation)
        if images is not None:
            body["input"] = [{"type": "input_text", "text": user_input}, *images]
        payload = self._run_json_request(
            "POST",
            "/v1/runs",
            expected_status=202,
            body=body,
        )
        run_id = self._validated_run_id(payload.get("run_id"))
        if payload.get("status") != "started":
            raise RemoteHermesError("remote_run_schema_invalid")
        return {"run_id": run_id, "status": "started"}

    def submit_run(self, user_input: str) -> dict[str, str]:
        return self._submit_run_payload(user_input)

    def submit_run_with_images(self, user_input: str, image_data_urls: list[str]) -> dict[str, str]:
        if not isinstance(image_data_urls, list) or not (1 <= len(image_data_urls) <= 4):
            raise RemoteHermesError("remote_run_request_invalid")
        self._require_features("run_inline_images")
        images: list[dict[str, Any]] = []
        total_bytes = 0
        for value in image_data_urls:
            if not isinstance(value, str) or len(value) > 7_000_000:
                raise RemoteHermesError("remote_run_request_invalid")
            match = re.fullmatch(r"data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/]+={0,2})", value)
            if match is None:
                raise RemoteHermesError("remote_run_request_invalid")
            encoded = match.group(2)
            padding = 2 if encoded.endswith("==") else 1 if encoded.endswith("=") else 0
            decoded_size = (len(encoded) * 3) // 4 - padding
            if decoded_size <= 0 or decoded_size > 5 * 1024 * 1024:
                raise RemoteHermesError("remote_run_request_invalid")
            total_bytes += decoded_size
            if total_bytes > 20 * 1024 * 1024:
                raise RemoteHermesError("remote_run_request_invalid")
            images.append({"type": "input_image", "image_url": value, "detail": "auto"})
        return self._submit_run_payload(user_input, images=images)

    def read_profiles(self) -> list[dict[str, Any]]:
        capabilities = self._trusted_capabilities()
        if not {"profile_inventory", "profile_inventory_complete", "profile_inventory_requires_api_key"}.issubset(set(capabilities.get("features") or ())):
            raise RemoteHermesError("remote_run_capability_unavailable")
        payload = self._request_json("/v1/profiles", authenticated=True, root_list_limits={"data": 1_000})
        if payload.get("object") != "list" or payload.get("version") != 1 or payload.get("complete") is not True or not isinstance(payload.get("active_profile"), str) or not isinstance(payload.get("data"), list):
            raise RemoteHermesError("remote_schema_unsupported")
        profiles: list[dict[str, Any]] = []
        seen: set[str] = set()
        active_count = 0
        for item in payload["data"]:
            if type(item) is not dict or set(item) != {"id", "object", "is_default", "is_active", "served"}:
                raise RemoteHermesError("remote_schema_unsupported")
            profile_id = item.get("id")
            if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", profile_id) or profile_id in seen or item.get("object") != "hermes.profile" or type(item.get("is_default")) is not bool or type(item.get("is_active")) is not bool or type(item.get("served")) is not bool:
                raise RemoteHermesError("remote_schema_unsupported")
            seen.add(profile_id)
            active_count += int(item["is_active"])
            profiles.append({"id": profile_id, "is_default": item["is_default"], "is_active": item["is_active"], "served": item["served"]})
        if (
            not profiles
            or active_count != 1
            or payload["active_profile"] not in seen
            or not any(item["id"] == payload["active_profile"] and item["is_active"] for item in profiles)
            or sum(int(item["is_default"]) for item in profiles) != 1
        ):
            raise RemoteHermesError("remote_schema_unsupported")
        return profiles

    def kanban_request(
        self,
        operation: str,
        *,
        board: str | None = None,
        task_id: str | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Execute only one named revisioned Kanban operation."""
        self._require_features("kanban_api", "kanban_api_revisioned", "kanban_api_idempotency", "kanban_api_requires_api_key")
        if operation == "boards" and board is None and task_id is None and body is None:
            return self._contract_json_request("GET", "/v1/kanban/boards")
        if not isinstance(board, str) or not _KANBAN_BOARD.fullmatch(board):
            raise RemoteHermesError("remote_run_request_invalid")
        suffix = f"?board={board}"
        if operation == "profiles" and task_id is None and body is None:
            return self._contract_json_request("GET", "/v1/kanban/profiles" + suffix)
        if operation == "tasks" and task_id is None and body is None:
            return self._contract_json_request("GET", "/v1/kanban/tasks" + suffix)
        if operation == "create" and task_id is None and isinstance(body, Mapping):
            return self._contract_json_request("POST", "/v1/kanban/tasks" + suffix, body=body)
        if not isinstance(task_id, str) or not _KANBAN_TASK_ID.fullmatch(task_id):
            raise RemoteHermesError("remote_run_request_invalid")
        if operation == "task" and body is None:
            return self._contract_json_request("GET", f"/v1/kanban/tasks/{task_id}" + suffix)
        if operation == "action" and isinstance(body, Mapping):
            return self._contract_json_request("POST", f"/v1/kanban/tasks/{task_id}/actions" + suffix, body=body)
        raise RemoteHermesError("remote_path_not_allowed")

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
            request_id = payload.get("request_id")
            preview = payload.get("preview")
            choices = payload.get("choices")
            if (
                not isinstance(request_id, str)
                or not _APPROVAL_REQUEST_ID.fullmatch(request_id)
                or type(preview) is not dict
                or set(preview) != {"version", "category", "title", "summary", "risk_labels"}
                or preview.get("version") != 1
                or not all(isinstance(preview.get(key), str) and 1 <= len(preview[key]) <= 500 and "\x00" not in preview[key] for key in ("category", "title", "summary"))
                or not isinstance(preview.get("risk_labels"), list)
                or len(preview["risk_labels"]) > 8
                or not all(isinstance(label, str) and 1 <= len(label) <= 120 and "\x00" not in label for label in preview["risk_labels"])
                or not isinstance(choices, list)
                or not {"once", "deny"}.issubset(set(choices))
            ):
                raise RemoteHermesError("remote_run_schema_invalid")
            if any(self._contains_private_run_text(value, run_id) or _contains_private_public_text(value) for value in (
                preview["category"], preview["title"], preview["summary"], *preview["risk_labels"]
            )):
                raise RemoteHermesError("remote_private_reflection")
            return {"type": event_type, "request_id": request_id, "preview": dict(preview), "choices": [choice for choice in ("once", "deny") if choice in choices]}
        if event_type == "clarify.request":
            request_id = payload.get("request_id")
            prompt = payload.get("prompt")
            if not isinstance(request_id, str) or not _CLARIFICATION_REQUEST_ID.fullmatch(request_id) or type(prompt) is not dict or prompt.get("version") != 1 or prompt.get("type") not in {"choice", "text"} or not isinstance(prompt.get("question"), str) or not prompt["question"].strip() or len(prompt["question"]) > 2_000 or "\x00" in prompt["question"]:
                raise RemoteHermesError("remote_run_schema_invalid")
            normalized_prompt: dict[str, Any] = {"version": 1, "type": prompt["type"], "question": prompt["question"]}
            if prompt["type"] == "choice":
                choices = prompt.get("choices")
                if not isinstance(choices, list) or not (1 <= len(choices) <= 4):
                    raise RemoteHermesError("remote_run_schema_invalid")
                normalized_choices = []
                for choice in choices:
                    if type(choice) is not dict or set(choice) != {"id", "label"} or not isinstance(choice.get("id"), str) or not re.fullmatch(r"choice-[1-4]", choice["id"]) or not isinstance(choice.get("label"), str) or not choice["label"].strip() or len(choice["label"]) > 500 or "\x00" in choice["label"]:
                        raise RemoteHermesError("remote_run_schema_invalid")
                    normalized_choices.append({"id": choice["id"], "label": choice["label"]})
                normalized_prompt["choices"] = normalized_choices
            if any(self._contains_private_run_text(value, run_id) or _contains_private_public_text(value) for value in (
                normalized_prompt["question"], *(choice["label"] for choice in normalized_prompt.get("choices", []))
            )):
                raise RemoteHermesError("remote_private_reflection")
            return {"type": event_type, "request_id": request_id, "prompt": normalized_prompt}
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
        if features.get("session_resources") is True:
            for name, expected in _SESSION_ENDPOINTS.items():
                item = endpoints.get(name)
                if type(item) is not dict or (item.get("method"), item.get("path")) != expected:
                    raise RemoteHermesError("remote_schema_unsupported")
        capability_inventory_endpoints_valid = all(
            type(endpoints.get(name)) is dict
            and (
                endpoints[name].get("method"),
                endpoints[name].get("path"),
            ) == expected
            for name, expected in _CAPABILITY_INVENTORY_ENDPOINTS.items()
        )
        if features.get("profile_inventory") is True:
            if (
                features.get("profile_inventory_version") != 1
                or features.get("profile_inventory_complete") is not True
                or features.get("profile_inventory_requires_api_key") is not True
                or type(endpoints.get("profiles")) is not dict
                or (endpoints["profiles"].get("method"), endpoints["profiles"].get("path")) != _PROFILE_INVENTORY_ENDPOINT
            ):
                raise RemoteHermesError("remote_schema_unsupported")
        if features.get("run_session_continuation") is True:
            if (
                features.get("run_session_continuation_version") != 1
                or features.get("run_session_continuation_exact_revision") is not True
                or features.get("run_session_continuation_stoppable") is not True
                or type(endpoints.get("session_continuation")) is not dict
                or (endpoints["session_continuation"].get("method"), endpoints["session_continuation"].get("path")) != _CONTINUATION_ENDPOINT
            ):
                raise RemoteHermesError("remote_schema_unsupported")
        if features.get("run_approval_response") is True:
            if features.get("run_approval_request_binding") is not True or features.get("run_approval_structured_preview") is not True or features.get("run_approval_preview_version") != 1 or type(endpoints.get("run_approval")) is not dict or (endpoints["run_approval"].get("method"), endpoints["run_approval"].get("path")) != _APPROVAL_ENDPOINT:
                raise RemoteHermesError("remote_schema_unsupported")
        if features.get("run_clarification_response") is True:
            if features.get("run_clarification_request_binding") is not True or features.get("clarification_events") is not True or features.get("run_clarification_prompt_version") != 1 or type(endpoints.get("run_clarification")) is not dict or (endpoints["run_clarification"].get("method"), endpoints["run_clarification"].get("path")) != _CLARIFICATION_ENDPOINT:
                raise RemoteHermesError("remote_schema_unsupported")
        if features.get("run_inline_images") is True:
            image_endpoint = endpoints.get("run_inline_images")
            if (
                features.get("run_inline_images_version") != 1
                or features.get("run_inline_images_data_urls_only") is not True
                or features.get("run_inline_images_max_count") != 4
                or features.get("run_inline_images_max_bytes") != 5 * 1024 * 1024
                or type(image_endpoint) is not dict
                or (image_endpoint.get("method"), image_endpoint.get("path"), image_endpoint.get("version"), image_endpoint.get("image_transport"), image_endpoint.get("max_count"), image_endpoint.get("max_bytes_per_image")) != ("POST", "/v1/runs", 1, "data_url_only", 4, 5 * 1024 * 1024)
            ):
                raise RemoteHermesError("remote_schema_unsupported")
        if features.get("kanban_api") is True:
            if features.get("kanban_api_version") != 1 or features.get("kanban_api_revisioned") is not True or features.get("kanban_api_idempotency") is not True or features.get("kanban_api_requires_api_key") is not True:
                raise RemoteHermesError("remote_schema_unsupported")
            for name, expected in _KANBAN_ENDPOINTS.items():
                item = endpoints.get(name)
                if type(item) is not dict or (item.get("method"), item.get("path")) != expected:
                    raise RemoteHermesError("remote_schema_unsupported")
        model = _bounded_text(payload.get("model"), maximum=160)
        if not _SAFE_MODEL.fullmatch(model) or model.startswith("/") or ".." in model or "://" in model or "\\" in model:
            raise RemoteHermesError("remote_schema_unsupported")
        supported = sorted(
            name
            for name in _KNOWN_BOOLEAN_FEATURES
            if features.get(name) is True
        )
        return {
            "model": model,
            "features": supported,
            "capability_inventory_endpoints_valid": capability_inventory_endpoints_valid,
        }

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


def connection_diagnostics(
    data_root: Path,
    *,
    client_factory: Callable[[str, str], RemoteHermesClient] = RemoteHermesClient,
) -> dict[str, Any]:
    """Return a fixed, secret-free health summary for the selected transport."""

    try:
        selected = load_connection(data_root)
    except RemoteHermesError:
        return {
            "mode": "unavailable",
            "status": "error",
            "category": "unsupported",
            "summary": "Hermes connection settings are unavailable.",
        }

    if selected.mode == "local":
        return {
            "mode": "local",
            "status": "healthy",
            "category": "local",
            "label": selected.label,
            "summary": "Mentat is using the local Hermes installation.",
        }

    try:
        result = test_selected_connection(
            data_root,
            client_factory=client_factory,
        )
    except RemoteHermesError as exc:
        if exc.code == "remote_authentication_failed":
            category = "unauthenticated"
            summary = "Remote Hermes rejected the saved API key."
        elif exc.code == "remote_certificate_invalid":
            category = "unreachable"
            summary = "Mentat could not verify the secure remote connection."
        elif exc.code in {"remote_timeout", "remote_unavailable"}:
            category = "unreachable"
            summary = "Remote Hermes is not reachable right now."
        elif exc.code == "connection_changed":
            category = "unavailable"
            summary = "The Hermes connection changed during the health check."
        else:
            category = "unsupported"
            summary = "Mentat rejected the remote Hermes health response."
        return {
            "mode": "remote",
            "status": "error",
            "category": category,
            "label": selected.label,
            "summary": summary,
        }

    discovery = result.get("discovery") if type(result) is dict else None
    if (
        type(discovery) is not dict
        or discovery.get("trusted") is not True
        or discovery.get("status") not in {"healthy", "degraded"}
    ):
        return {
            "mode": "remote",
            "status": "error",
            "category": "unsupported",
            "label": selected.label,
            "summary": "Mentat rejected the remote Hermes health response.",
        }
    status = "degraded" if discovery.get("status") == "degraded" else "healthy"
    summary = (
        "Remote Hermes is connected but reports degraded readiness."
        if status == "degraded"
        else "Remote Hermes is connected and ready."
    )
    return {
        "mode": "remote",
        "status": status,
        "category": status,
        "label": selected.label,
        "summary": summary,
        "liveness": discovery.get("liveness"),
        "version": discovery.get("version"),
        "model": discovery.get("model"),
        "readiness": dict(discovery.get("readiness") or {}),
        "capabilities": list(discovery.get("capabilities") or []),
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
    "connection_diagnostics",
    "confirm_connection",
    "connection_path",
    "load_connection",
    "normalize_endpoint",
    "preview_connection",
    "public_connection_payload",
    "public_error",
    "test_selected_connection",
]
