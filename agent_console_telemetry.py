"""Validated, private telemetry ingestion for local Agent Console runs."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Any

from agent_console_artifacts import prepare_input_directory


MAX_PROGRESS_BYTES = 256 * 1024
MAX_USAGE_BYTES = 32 * 1024
MAX_PROGRESS_EVENTS = 200
TOOL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
SAFE_REASONING_SUMMARIES = {
    "Running verification checks",
    "Preparing a scoped change",
    "Inspecting relevant context",
    "Planning the next action",
    "Analyzing the latest result",
    "Reasoning about the next action",
}


def prepare_local_telemetry_paths(data_dir: Path, run_id: str) -> tuple[Path, Path]:
    """Create private server-owned telemetry files for this run."""
    root = prepare_input_directory(data_dir, run_id)
    paths = (root / "progress.jsonl", root / "usage.json")
    for path in paths:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_BINARY", 0),
            0o600,
        )
        os.close(descriptor)
    return paths


def _read_regular_file(path: Path, *, max_bytes: int) -> bytes | None:
    try:
        if path.is_symlink():
            raise ValueError("Telemetry files must not be symlinks")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0),
        )
    except FileNotFoundError:
        return None
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > max_bytes:
            raise ValueError("Telemetry file is not a bounded regular file")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ValueError("Telemetry file exceeds its size limit")
        return payload
    finally:
        os.close(descriptor)


def normalize_progress_event(value: Any) -> dict | None:
    if type(value) is not dict or value.get("schema_version") != 1:
        return None
    event_type = value.get("type")
    if event_type not in {"tool.started", "tool.completed", "reasoning.available"}:
        return None
    sequence = value.get("sequence")
    if type(sequence) is not int or not (1 <= sequence <= 10**9):
        return None
    if event_type == "reasoning.available":
        summary = value.get("summary")
        if summary not in SAFE_REASONING_SUMMARIES:
            return None
        return {"type": event_type, "summary": summary, "sequence": sequence}
    tool = value.get("tool")
    if not isinstance(tool, str) or not TOOL_NAME_PATTERN.fullmatch(tool):
        return None
    expected_summary = f"Using {tool}" if event_type == "tool.started" else f"Finished {tool}"
    error_summary = f"{tool} reported an error"
    summary = value.get("summary")
    if summary not in {expected_summary, error_summary}:
        return None
    normalized = {
        "type": event_type,
        "tool": tool,
        "summary": summary,
        "sequence": sequence,
    }
    duration = value.get("duration_ms")
    if duration is not None:
        if type(duration) is not int or not (0 <= duration <= 86_400_000):
            return None
        normalized["duration_ms"] = duration
    return normalized


class ProgressTail:
    """Read complete, validated JSONL records without parsing process output."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._offset = 0
        self._remainder = b""
        self._count = 0
        self._last_sequence = 0
        self._disabled = False

    def poll(self) -> list[dict]:
        if self._disabled:
            return []
        payload = _read_regular_file(self.path, max_bytes=MAX_PROGRESS_BYTES)
        if payload is None:
            return []
        if len(payload) < self._offset:
            raise ValueError("Telemetry file was truncated")
        fresh = self._remainder + payload[self._offset :]
        self._offset = len(payload)
        lines = fresh.split(b"\n")
        self._remainder = lines.pop()
        normalized: list[dict] = []
        for line in lines:
            if not line:
                continue
            self._count += 1
            if self._count > MAX_PROGRESS_EVENTS:
                raise ValueError("Telemetry event limit exceeded")
            try:
                event = normalize_progress_event(json.loads(line.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                event = None
            if event is not None:
                sequence = event["sequence"]
                if sequence <= self._last_sequence:
                    self._disabled = True
                    raise ValueError("Telemetry sequence must increase")
                self._last_sequence = sequence
                normalized.append(event)
        return normalized


def read_usage(path: Path) -> dict[str, int] | None:
    payload = _read_regular_file(Path(path), max_bytes=MAX_USAGE_BYTES)
    if payload is None:
        return None
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if type(value) is not dict or value.get("schema_version") != 1:
        return None
    usage: dict[str, int] = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        item = value.get(name)
        if type(item) is not int or not (0 <= item <= 10**9):
            return None
        usage[name] = item
    context_tokens = value.get("context_tokens")
    context_length = value.get("context_length")
    if context_tokens is None and context_length is None:
        return usage
    if (
        type(context_tokens) is not int
        or type(context_length) is not int
        or not (0 <= context_tokens <= context_length <= 10**9)
        or context_length == 0
    ):
        return usage
    usage["context_tokens"] = context_tokens
    usage["context_length"] = context_length
    return usage
