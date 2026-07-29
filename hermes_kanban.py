"""Fail-closed adapter for Hermes' supported Kanban CLI.

Mentat must not know where Hermes stores Kanban data.  This module therefore
uses only fixed, shell-free ``hermes kanban`` commands, accepts a runner for
tests, and reduces Hermes responses to a path- and secret-free public schema.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any, Callable
from uuid import uuid4

from remote_hermes import RemoteHermesClient, RemoteHermesError


SCHEMA_VERSION = 1
DEFAULT_TIMEOUT_SECONDS = 15
MAX_TASKS = 500
MAX_TEXT = 20_000

CAPABILITY_KEYS = (
    "boards.read",
    "profiles.read",
    "tasks.read",
    "runs.read",
    "tasks.create",
    "tasks.assign",
    "tasks.comment",
    "tasks.reply",
    "tasks.promote",
    "tasks.block",
    "tasks.retry",
    "tasks.terminate",
)

_BOARD_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_PROFILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
_VERSION_RE = re.compile(r"Hermes Agent v([0-9]+(?:\.[0-9]+){1,3})")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}"),
    re.compile(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gh[opsu]_[A-Za-z0-9]{8,})\b"),
)
_PATH_PATTERNS = (
    re.compile(r"(?<!:)\/(?:Users|home|root|private|tmp|var|opt|etc)\/[^\s\"'<>]+"),
    re.compile(r"\b[A-Za-z]:\\[^\r\n\"'<>]+"),
)


def _clean_text(value: Any, limit: int = MAX_TEXT) -> str:
    text = str(value or "").replace("\x00", "")[:limit]
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted-secret]", text)
    for pattern in _PATH_PATTERNS:
        text = pattern.sub("[redacted-path]", text)
    return text


def sanitize_public_text(value: Any, limit: int = MAX_TEXT) -> str:
    """Redact common credentials and private local paths from shared context."""
    return _clean_text(value, limit)


def _short_text(value: Any, limit: int) -> str:
    return " ".join(_clean_text(value, limit).split())[:limit]


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _timestamp(value: Any) -> int | None:
    result = _integer(value, -1)
    return result if result >= 0 else None


def _failure(code: str, message: str, *, partial: bool = False) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "error": {"code": code, "message": _short_text(message, 500)},
        "partial": bool(partial),
    }


def _validate(value: Any, pattern: re.Pattern, label: str) -> str:
    normalized = str(value or "").strip()
    if not pattern.fullmatch(normalized):
        raise ValueError(f"Invalid {label}.")
    return normalized


def _validate_text(value: Any, label: str, limit: int, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if (required and not text) or len(text) > limit or "\x00" in text:
        raise ValueError(f"Invalid {label}.")
    if text.startswith("-"):
        raise ValueError(f"{label.capitalize()} must not start with '-'.")
    return text


def _normalize_task(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    task_id = _short_text(value.get("id"), 128)
    if not _IDENTIFIER_RE.fullmatch(task_id):
        return None
    status = _short_text(value.get("status"), 32).lower()
    return {
        "id": task_id,
        "title": _clean_text(value.get("title"), 500),
        "body": _clean_text(value.get("body"), MAX_TEXT),
        "assignee": _short_text(value.get("assignee"), 80) or None,
        "status": status,
        "priority": _integer(value.get("priority")),
        "tenant": _short_text(value.get("tenant"), 120) or None,
        "workspace_kind": _short_text(value.get("workspace_kind"), 32),
        # workspace_path is deliberately omitted from the browser contract.
        "branch": _short_text(value.get("branch_name"), 240) or None,
        "project_id": _short_text(value.get("project_id"), 128) or None,
        "created_by": _short_text(value.get("created_by"), 80),
        "created_at": _timestamp(value.get("created_at")),
        "started_at": _timestamp(value.get("started_at")),
        "completed_at": _timestamp(value.get("completed_at")),
        "result": _clean_text(value.get("result"), MAX_TEXT),
        "skills": [
            _short_text(item, 120)
            for item in (value.get("skills") if isinstance(value.get("skills"), list) else [])[:50]
            if _short_text(item, 120)
        ],
        "max_retries": (
            max(1, _integer(value.get("max_retries")))
            if value.get("max_retries") is not None
            else None
        ),
        "session_id": _short_text(value.get("session_id"), 160) or None,
    }


def _normalize_run(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    run_id = _integer(value.get("id"), -1)
    if run_id < 0:
        return None
    started = _timestamp(value.get("started_at"))
    ended = _timestamp(value.get("ended_at"))
    return {
        "id": run_id,
        "profile": _short_text(value.get("profile"), 80) or None,
        "status": _short_text(value.get("status"), 40),
        "outcome": _short_text(value.get("outcome"), 40) or None,
        "summary": _clean_text(value.get("summary"), MAX_TEXT),
        "error": _clean_text(value.get("error"), 2_000),
        "started_at": started,
        "ended_at": ended,
        "elapsed_seconds": max(0, ended - started) if ended is not None and started is not None else None,
        "step_key": _short_text(value.get("step_key"), 120) or None,
        # metadata and worker_pid are deliberately omitted.
    }


class HermesKanbanAdapter:
    """Capability-gated wrapper around the public Hermes Kanban CLI."""

    def __init__(
        self,
        executable: str | None,
        *,
        runner: Callable = subprocess.run,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        env: dict[str, str] | None = None,
    ) -> None:
        self.executable = str(executable or "").strip()
        self.runner = runner
        self.timeout = max(1, int(timeout))
        self.env = dict(env) if env is not None else None
        self._detected: dict | None = None

    def _invoke(self, arguments: list[str], *, json_output: bool = False) -> tuple[dict | None, dict | None]:
        if not self.executable:
            return None, _failure("runtime_unavailable", "Hermes is not available.")
        argv = [self.executable, *arguments]
        try:
            result = self.runner(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                env=self.env,
            )
        except subprocess.TimeoutExpired:
            return None, _failure("runtime_timeout", "Hermes Kanban timed out.", partial=True)
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            return None, _failure("runtime_failed", "Hermes Kanban could not be started.")
        if result.returncode != 0:
            detail = _short_text(result.stderr, 300) or "Hermes Kanban command failed."
            return None, _failure("command_failed", detail)
        if not json_output:
            return {"stdout": _clean_text(result.stdout, 5_000)}, None
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError):
            return None, _failure("invalid_payload", "Hermes Kanban returned invalid JSON.")
        return {"payload": payload}, None

    def detect_capabilities(self, *, refresh: bool = False) -> dict:
        if self._detected is not None and not refresh:
            return self._detected
        capabilities = {key: False for key in CAPABILITY_KEYS}
        version = ""
        version_result, version_error = self._invoke(["--version"])
        if version_result:
            match = _VERSION_RE.search(version_result["stdout"])
            version = match.group(1) if match else ""
        help_result, help_error = self._invoke(["kanban", "--help"])
        if help_error or not help_result:
            error = help_error or version_error or _failure("unsupported", "Hermes Kanban is unavailable.")
            self._detected = {
                "schema_version": SCHEMA_VERSION,
                "status": "unavailable",
                "hermes_version": version,
                "capabilities": capabilities,
                "error": error["error"],
            }
            return self._detected
        words = set(re.findall(r"[a-z][a-z-]+", help_result["stdout"].lower()))
        capabilities.update({
            "boards.read": "boards" in words,
            "profiles.read": "assignees" in words,
            "tasks.read": {"list", "show"}.issubset(words),
            "runs.read": "runs" in words,
            "tasks.create": "create" in words,
            "tasks.assign": "assign" in words,
            "tasks.comment": "comment" in words,
            # Hermes comments are task-level; a reply is represented by a comment.
            "tasks.reply": "comment" in words,
            "tasks.promote": "promote" in words,
            "tasks.block": "block" in words,
            "tasks.retry": "unblock" in words,
            # Reclaim is Hermes' supported stop/requeue operation for a running task.
            "tasks.terminate": "reclaim" in words,
        })
        self._detected = {
            "schema_version": SCHEMA_VERSION,
            "status": "available" if capabilities["tasks.read"] else "unsupported",
            "hermes_version": version,
            "capabilities": capabilities,
            "error": None,
        }
        return self._detected

    def _require(self, capability: str) -> dict | None:
        if not self.detect_capabilities()["capabilities"].get(capability):
            return _failure("capability_unavailable", f"Hermes Kanban does not support {capability}.")
        return None

    @staticmethod
    def _scope(board: str) -> list[str]:
        return ["kanban", "--board", _validate(board, _BOARD_RE, "board")]

    def list_boards(self) -> dict:
        if error := self._require("boards.read"):
            return error
        result, error = self._invoke(["kanban", "boards", "list", "--json"], json_output=True)
        if error:
            return error
        rows = result["payload"] if isinstance(result["payload"], list) else []
        boards = []
        for row in rows[:100]:
            if not isinstance(row, dict):
                continue
            slug = _short_text(row.get("slug"), 64).lower()
            if not _BOARD_RE.fullmatch(slug):
                continue
            counts = row.get("counts") if isinstance(row.get("counts"), dict) else {}
            boards.append({
                "id": slug,
                "name": _short_text(row.get("name") or slug, 160),
                "description": _clean_text(row.get("description"), 1_000),
                "icon": _short_text(row.get("icon"), 16),
                "color": _short_text(row.get("color"), 32),
                "is_current": bool(row.get("is_current")),
                "archived": bool(row.get("archived")),
                "counts": {str(k): max(0, _integer(v)) for k, v in counts.items() if str(k)[:32]},
            })
        return {"schema_version": SCHEMA_VERSION, "ok": True, "boards": boards, "error": None}

    def list_profiles(self, board: str) -> dict:
        if error := self._require("profiles.read"):
            return error
        try:
            args = [*self._scope(board), "assignees", "--json"]
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        result, error = self._invoke(args, json_output=True)
        if error:
            return error
        rows = result["payload"] if isinstance(result["payload"], list) else []
        profiles = []
        for row in rows[:200]:
            if not isinstance(row, dict):
                continue
            name = _short_text(row.get("name"), 80)
            if not _PROFILE_RE.fullmatch(name):
                continue
            counts = row.get("counts") if isinstance(row.get("counts"), dict) else {}
            profiles.append({"id": name, "name": name, "available": bool(row.get("on_disk")), "counts": {str(k): max(0, _integer(v)) for k, v in counts.items()}})
        return {"schema_version": SCHEMA_VERSION, "ok": True, "profiles": profiles, "error": None}

    def list_tasks(self, board: str, *, status: str | None = None, assignee: str | None = None) -> dict:
        if error := self._require("tasks.read"):
            return error
        try:
            args = [*self._scope(board), "list", "--json"]
            if status is not None:
                status = _validate(status, re.compile(r"(?:triage|todo|scheduled|ready|running|blocked|review|done|archived)\Z"), "status")
                args.extend(["--status", status])
            if assignee is not None:
                args.extend(["--assignee", _validate(assignee, _PROFILE_RE, "assignee")])
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        result, error = self._invoke(args, json_output=True)
        if error:
            return error
        rows = result["payload"] if isinstance(result["payload"], list) else []
        tasks = [task for task in (_normalize_task(row) for row in rows[:MAX_TASKS]) if task]
        return {"schema_version": SCHEMA_VERSION, "ok": True, "tasks": tasks, "error": None}

    def get_task(self, board: str, task_id: str) -> dict:
        if error := self._require("tasks.read"):
            return error
        try:
            tid = _validate(task_id, _IDENTIFIER_RE, "task id")
            args = [*self._scope(board), "show", tid, "--json"]
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        result, error = self._invoke(args, json_output=True)
        if error:
            return error
        payload = result["payload"] if isinstance(result["payload"], dict) else {}
        task = _normalize_task(payload.get("task"))
        if task is None:
            return _failure("invalid_payload", "Hermes Kanban returned an invalid task.")
        comments = []
        for value in payload.get("comments", [])[:500] if isinstance(payload.get("comments"), list) else []:
            if isinstance(value, dict):
                comments.append({"author": _short_text(value.get("author"), 80), "body": _clean_text(value.get("body"), MAX_TEXT), "created_at": _timestamp(value.get("created_at"))})
        runs = [run for run in (_normalize_run(row) for row in (payload.get("runs") or [])[:200]) if run]
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "task": task,
            "latest_summary": _clean_text(payload.get("latest_summary"), MAX_TEXT),
            "parents": [_short_text(x, 128) for x in (payload.get("parents") or [])[:100]],
            "children": [_short_text(x, 128) for x in (payload.get("children") or [])[:100]],
            "comments": comments,
            "runs": runs,
            # Raw events are intentionally omitted: arbitrary event payloads can contain paths.
            "error": None,
        }

    def list_runs(self, board: str, task_id: str) -> dict:
        if error := self._require("runs.read"):
            return error
        try:
            args = [*self._scope(board), "runs", _validate(task_id, _IDENTIFIER_RE, "task id"), "--json"]
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        result, error = self._invoke(args, json_output=True)
        if error:
            return error
        rows = result["payload"] if isinstance(result["payload"], list) else []
        runs = [run for run in (_normalize_run(row) for row in rows[:200]) if run]
        return {"schema_version": SCHEMA_VERSION, "ok": True, "runs": runs, "error": None}

    def create_task(self, board: str, *, title: str, body: str = "", assignee: str | None = None, priority: int = 0, workspace: str = "scratch", idempotency_key: str | None = None) -> dict:
        if error := self._require("tasks.create"):
            return error
        try:
            args = [*self._scope(board), "create", "--json", "--created-by", "mentat"]
            title = _validate_text(title, "title", 500)
            if body:
                args.extend(["--body", _validate_text(body, "body", MAX_TEXT)])
            if assignee:
                args.extend(["--assignee", _validate(assignee, _PROFILE_RE, "assignee")])
            if workspace not in {"scratch", "worktree"}:
                raise ValueError("Invalid workspace kind.")
            args.extend(["--workspace", workspace, "--priority", str(max(-1000, min(1000, int(priority))))])
            if idempotency_key:
                args.extend(["--idempotency-key", _validate(idempotency_key, _IDENTIFIER_RE, "idempotency key")])
            args.append(title)
        except (TypeError, ValueError) as exc:
            return _failure("invalid_request", str(exc))
        result, error = self._invoke(args, json_output=True)
        if error:
            return error
        task = _normalize_task(result["payload"])
        if task is None:
            return _failure("invalid_payload", "Hermes Kanban returned an invalid task.", partial=True)
        return {"schema_version": SCHEMA_VERSION, "ok": True, "task": task, "error": None}

    def _mutate_and_refresh(
        self,
        capability: str,
        board: str,
        task_id: str,
        command: list[str],
        *,
        expected_assignee: str | None = None,
        expected_comment: str | None = None,
        expected_statuses: set[str] | None = None,
        forbidden_statuses: set[str] | None = None,
    ) -> dict:
        if error := self._require(capability):
            return error
        try:
            tid = _validate(task_id, _IDENTIFIER_RE, "task id")
            args = [*self._scope(board), *command[:1], tid, *command[1:]]
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        _, error = self._invoke(args)
        if error:
            return error
        refreshed = self.get_task(board, tid)
        if not refreshed.get("ok"):
            return _failure("verification_failed", "Hermes accepted the operation but its result could not be verified.", partial=True)
        task = refreshed["task"]
        comments = refreshed.get("comments") or []
        verified = True
        if expected_assignee is not None:
            verified = task.get("assignee") == (None if expected_assignee == "none" else expected_assignee)
        if expected_comment is not None:
            verified = verified and bool(comments) and comments[-1].get("body") == sanitize_public_text(expected_comment)
        if expected_statuses is not None:
            verified = verified and task.get("status") in expected_statuses
        if forbidden_statuses is not None:
            verified = verified and task.get("status") not in forbidden_statuses
        if not verified:
            return _failure("verification_failed", "Hermes accepted the operation but the requested state change was not observed.", partial=True)
        return {"schema_version": SCHEMA_VERSION, "ok": True, "task": task, "error": None}

    def assign_task(self, board: str, task_id: str, assignee: str | None) -> dict:
        try:
            profile = "none" if assignee is None else _validate(assignee, _PROFILE_RE, "assignee")
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        return self._mutate_and_refresh("tasks.assign", board, task_id, ["assign", profile], expected_assignee=profile)

    def comment_task(self, board: str, task_id: str, text: str, *, author: str = "mentat") -> dict:
        try:
            body = _validate_text(text, "comment", MAX_TEXT)
            author = _validate(author, _PROFILE_RE, "author")
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        return self._mutate_and_refresh(
            "tasks.comment", board, task_id,
            ["comment", body, "--author", author, "--max-len", str(MAX_TEXT)],
            expected_comment=body,
        )

    def reply_task(self, board: str, task_id: str, text: str, *, author: str = "mentat") -> dict:
        """Append a task-level reply; Hermes does not expose threaded comment IDs."""
        return self.comment_task(board, task_id, text, author=author)

    def promote_task(self, board: str, task_id: str, *, reason: str = "") -> dict:
        command = ["promote"]
        if reason:
            try:
                command.append(_validate_text(reason, "reason", 2_000))
            except ValueError as exc:
                return _failure("invalid_request", str(exc))
        return self._mutate_and_refresh("tasks.promote", board, task_id, command, expected_statuses={"ready"})

    def block_task(self, board: str, task_id: str, reason: str, *, kind: str = "needs_input") -> dict:
        if kind not in {"capability", "dependency", "needs_input", "transient"}:
            return _failure("invalid_request", "Invalid block kind.")
        try:
            reason = _validate_text(reason, "reason", 2_000)
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        return self._mutate_and_refresh("tasks.block", board, task_id, ["block", reason, "--kind", kind], expected_statuses={"blocked"})

    def retry_task(self, board: str, task_id: str, *, reason: str = "Retried from Mentat") -> dict:
        try:
            reason = _validate_text(reason, "reason", 2_000)
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        return self._mutate_and_refresh("tasks.retry", board, task_id, ["unblock", "--reason", reason], forbidden_statuses={"blocked", "scheduled"})

    def terminate_task(self, board: str, task_id: str, *, reason: str = "Stopped from Mentat") -> dict:
        """Reclaim a running task using Hermes' stop-and-requeue operation."""
        try:
            reason = _validate_text(reason, "reason", 2_000)
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        return self._mutate_and_refresh("tasks.terminate", board, task_id, ["reclaim", "--reason", reason], forbidden_statuses={"running"})

    def update_task(self, board: str, task_id: str, **changes: Any) -> dict:
        """Update only fields supported by the public CLI (currently assignee)."""
        if set(changes) != {"assignee"}:
            return _failure("capability_unavailable", "Hermes CLI supports only assignee updates; title, body, priority, and arbitrary status updates are unavailable.")
        return self.assign_task(board, task_id, changes["assignee"])


class RemoteHermesKanbanAdapter:
    """Revision-aware remote Kanban adapter using only Hermes' fixed API contract."""

    def __init__(self, client: RemoteHermesClient) -> None:
        self.client = client

    def _call(self, operation: str, **kwargs: Any) -> tuple[dict | None, dict | None]:
        try:
            return dict(self.client.kanban_request(operation, **kwargs)), None
        except RemoteHermesError as exc:
            return None, _failure(exc.code, "Remote Hermes Kanban is unavailable.", partial=exc.code in {"remote_timeout", "remote_unavailable"})

    def detect_capabilities(self, *, refresh: bool = False) -> dict:
        try:
            capabilities = self.client.require_kanban_capabilities()
        except RemoteHermesError as exc:
            return {"schema_version": SCHEMA_VERSION, "status": "unavailable", "capabilities": {key: False for key in CAPABILITY_KEYS}, "error": _failure(exc.code, "Remote Hermes Kanban is unavailable.")["error"]}
        supported = {"kanban_api", "kanban_api_revisioned", "kanban_api_idempotency", "kanban_api_requires_api_key"}.issubset(set(capabilities.get("features") or ()))
        values = {key: supported for key in CAPABILITY_KEYS}
        return {"schema_version": SCHEMA_VERSION, "status": "available" if supported else "unsupported", "hermes_version": "remote", "capabilities": values, "error": None if supported else {"code": "capability_unavailable", "message": "Remote Hermes does not advertise revisioned Kanban."}}

    def list_boards(self) -> dict:
        payload, error = self._call("boards")
        if error:
            return error
        if payload.get("object") != "list" or payload.get("version") != 1 or payload.get("complete") is not True or not isinstance(payload.get("data"), list):
            return _failure("invalid_payload", "Remote Hermes returned an invalid Kanban board list.")
        boards = []
        for item in payload["data"]:
            if type(item) is not dict or set(item) != {"id", "object", "name", "archived", "is_current"} or item.get("object") != "hermes.kanban.board":
                return _failure("invalid_payload", "Remote Hermes returned an invalid Kanban board.")
            board_id = _short_text(item.get("id"), 64).lower()
            if not _BOARD_RE.fullmatch(board_id):
                return _failure("invalid_payload", "Remote Hermes returned an invalid Kanban board.")
            boards.append({"id": board_id, "name": _short_text(item.get("name"), 160) or board_id, "archived": bool(item.get("archived")), "is_current": bool(item.get("is_current")), "description": "", "icon": "", "color": "", "counts": {}})
        return {"schema_version": SCHEMA_VERSION, "ok": True, "boards": boards, "error": None}

    def list_profiles(self, board: str) -> dict:
        try:
            board = _validate(board, _BOARD_RE, "board")
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        payload, error = self._call("profiles", board=board)
        if error:
            return error
        if payload.get("object") != "list" or payload.get("version") != 1 or payload.get("complete") is not True or payload.get("board") != board or not isinstance(payload.get("data"), list):
            return _failure("invalid_payload", "Remote Hermes returned an invalid Kanban profile list.")
        profiles = []
        for item in payload["data"]:
            if type(item) is not dict or set(item) != {"id", "object", "available", "counts"} or item.get("object") != "hermes.kanban.profile":
                return _failure("invalid_payload", "Remote Hermes returned an invalid Kanban profile.")
            profile_id = _short_text(item.get("id"), 80)
            if not _PROFILE_RE.fullmatch(profile_id) or type(item.get("counts")) is not dict:
                return _failure("invalid_payload", "Remote Hermes returned an invalid Kanban profile.")
            profiles.append({"id": profile_id, "name": profile_id, "available": bool(item["available"]), "counts": {str(k): max(0, _integer(v)) for k, v in item["counts"].items() if str(k)[:32]}})
        return {"schema_version": SCHEMA_VERSION, "ok": True, "profiles": profiles, "error": None}

    @staticmethod
    def _detail(payload: dict, board: str) -> dict | None:
        if payload.get("object") != "hermes.kanban.task_detail" or payload.get("version") != 1 or payload.get("board") not in {None, board} or not isinstance(payload.get("revision"), str) or not re.fullmatch(r"kanbanrev_[0-9a-f]{64}", payload["revision"]):
            return None
        task = _normalize_task(payload.get("task"))
        if task is None:
            return None
        comments = payload.get("comments")
        runs = payload.get("runs")
        if not isinstance(comments, list) or not isinstance(runs, list):
            return None
        clean_comments = [{"author": _short_text(item.get("author"), 80), "body": _clean_text(item.get("body"), MAX_TEXT), "created_at": _timestamp(item.get("created_at"))} for item in comments if isinstance(item, dict)]
        clean_runs = [item for item in (_normalize_run(value) for value in runs) if item]
        return {"schema_version": SCHEMA_VERSION, "ok": True, "task": task, "latest_summary": _clean_text(task.get("result"), MAX_TEXT), "parents": [], "children": [], "comments": clean_comments, "runs": clean_runs, "revision": payload["revision"], "error": None}

    def get_task(self, board: str, task_id: str) -> dict:
        try:
            board, task_id = _validate(board, _BOARD_RE, "board"), _validate(task_id, _IDENTIFIER_RE, "task id")
        except ValueError as exc:
            return _failure("invalid_request", str(exc))
        payload, error = self._call("task", board=board, task_id=task_id)
        if error:
            return error
        detail = self._detail(payload, board)
        return detail or _failure("invalid_payload", "Remote Hermes returned an invalid Kanban task.")

    def create_task(self, board: str, *, title: str, body: str = "", assignee: str | None = None, priority: int = 0, workspace: str = "scratch", idempotency_key: str | None = None) -> dict:
        try:
            board = _validate(board, _BOARD_RE, "board")
            material = {"title": _validate_text(title, "title", 500), "body": _validate_text(body, "body", MAX_TEXT, required=False), "assignee": _validate(assignee, _PROFILE_RE, "assignee") if assignee else None, "workspace_kind": workspace, "priority": max(-1000, min(1000, int(priority))), "idempotency_key": _validate(idempotency_key, _IDENTIFIER_RE, "idempotency key")}
            if workspace not in {"scratch", "worktree"}:
                raise ValueError("Invalid workspace kind.")
        except (TypeError, ValueError) as exc:
            return _failure("invalid_request", str(exc))
        payload, error = self._call("create", board=board, body=material)
        if error:
            return error
        detail = self._detail(payload, board)
        return detail or _failure("invalid_payload", "Remote Hermes returned an invalid created task.", partial=True)

    def mutate_task(self, board: str, task_id: str, action: str, *, expected_revision: str, idempotency_key: str, **changes: Any) -> dict:
        if not isinstance(expected_revision, str) or not re.fullmatch(r"kanbanrev_[0-9a-f]{64}", expected_revision) or not isinstance(idempotency_key, str) or not _IDENTIFIER_RE.fullmatch(idempotency_key):
            return _failure("invalid_request", "Remote Kanban mutation binding is invalid.")
        body = {"action": action, "expected_revision": expected_revision, "idempotency_key": idempotency_key, **changes}
        payload, error = self._call("action", board=board, task_id=task_id, body=body)
        if error:
            return error
        detail = self._detail(payload, board)
        return detail or _failure("verification_failed", "Remote Hermes accepted the operation but its result could not be verified.", partial=True)

    def _action(self, board: str, task_id: str, action: str, **changes: Any) -> dict:
        before = self.get_task(board, task_id)
        if not before.get("ok"):
            return before
        return self.mutate_task(board, task_id, action, expected_revision=before["revision"], idempotency_key=f"mentat-{uuid4().hex}", **changes)

    def assign_task(self, board: str, task_id: str, assignee: str | None) -> dict: return self._action(board, task_id, "assign", assignee=assignee)
    def comment_task(self, board: str, task_id: str, text: str, *, author: str = "mentat") -> dict: return self._action(board, task_id, "comment", body=text, author=author)
    def reply_task(self, board: str, task_id: str, text: str, *, author: str = "mentat") -> dict: return self._action(board, task_id, "reply", body=text, author=author)
    def promote_task(self, board: str, task_id: str, *, reason: str = "") -> dict: return self._action(board, task_id, "promote", reason=reason)
    def block_task(self, board: str, task_id: str, reason: str, *, kind: str = "needs_input") -> dict: return self._action(board, task_id, "block", reason=reason, kind=kind)
    def retry_task(self, board: str, task_id: str, *, reason: str = "Retried from Mentat") -> dict: return self._action(board, task_id, "retry", reason=reason)
    def terminate_task(self, board: str, task_id: str, *, reason: str = "Stopped from Mentat") -> dict: return self._action(board, task_id, "terminate", reason=reason)
    def update_task(self, board: str, task_id: str, **changes: Any) -> dict:
        return self.assign_task(board, task_id, changes["assignee"]) if set(changes) == {"assignee"} else _failure("capability_unavailable", "Remote Hermes supports only assignment updates.")
