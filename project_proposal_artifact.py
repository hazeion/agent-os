"""Parse bounded Agent-authored Project proposal bytes into inert suggestions.

This module does not establish Run provenance, current Agent authority, owner
approval, or permission to create Tasks. Its caller must first verify the
registered output and exact producing Run.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import re
import unicodedata


MAX_ARTIFACT_BYTES = 32 * 1024
MAX_TASKS = 16
MAX_QUESTIONS = 8
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_TOP_KEYS = {"version", "summary", "questions", "tasks"}
_QUESTION_KEYS = {"kind", "text"}
_TASK_KEYS = {"title", "description", "agent_id", "due_date", "after"}


class ProjectProposalArtifactError(ValueError):
    """A fixed failure without source content or a private path."""


def _fail() -> None:
    raise ProjectProposalArtifactError("project_proposal.artifact_invalid")


def _object(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    _fail()


def _text(value: object, *, maximum: int, required: bool,
          multiline: bool = False) -> str:
    if not isinstance(value, str):
        _fail()
    canonical = unicodedata.normalize("NFC", value)
    for character in canonical:
        if (unicodedata.category(character).startswith("C")
                and not (multiline and character in "\n\t")):
            _fail()
        if not multiline and unicodedata.category(character) in {"Zl", "Zp"}:
            _fail()
    normalized = canonical.strip()
    try:
        size = len(normalized.encode("utf-8"))
    except UnicodeError:
        _fail()
    if size > maximum or required and size == 0:
        _fail()
    return normalized


def _due_date(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        _fail()
    try:
        date.fromisoformat(value)
    except ValueError:
        _fail()
    return value


def parse_proposal_artifact(raw: bytes) -> dict:
    """Return exact version-1 text/questions/new-Task suggestions.

    Every question is blocking for Apply until a separate owner decision and
    new proposal or revision resolves it. Suggested Agent IDs are syntax-only.
    """
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_ARTIFACT_BYTES:
        _fail()
    try:
        source = json.loads(raw.decode("utf-8", errors="strict"),
                            object_pairs_hook=_object,
                            parse_constant=_reject_constant)
    except (UnicodeError, ValueError, RecursionError):
        _fail()
    if (not isinstance(source, dict) or set(source) != _TOP_KEYS
            or type(source["version"]) is not int or source["version"] != 1):
        _fail()
    summary = _text(source["summary"], maximum=2048, required=True, multiline=True)
    raw_questions = source["questions"]
    raw_tasks = source["tasks"]
    if (not isinstance(raw_questions, list) or len(raw_questions) > MAX_QUESTIONS
            or not isinstance(raw_tasks, list) or len(raw_tasks) > MAX_TASKS
            or not raw_questions and not raw_tasks):
        _fail()
    questions: list[dict] = []
    seen_questions: set[tuple[str, str]] = set()
    for value in raw_questions:
        if not isinstance(value, dict) or set(value) != _QUESTION_KEYS:
            _fail()
        kind = value["kind"]
        if type(kind) is not str or kind not in {"measurement", "clarification"}:
            _fail()
        question = {
            "kind": kind,
            "text": _text(value["text"], maximum=512, required=True),
        }
        key = (kind, question["text"].casefold())
        if key in seen_questions:
            _fail()
        seen_questions.add(key)
        questions.append(question)
    tasks: list[dict] = []
    seen_titles: set[str] = set()
    for index, value in enumerate(raw_tasks):
        if not isinstance(value, dict) or set(value) != _TASK_KEYS:
            _fail()
        agent_id = value["agent_id"]
        if agent_id is not None and (
                not isinstance(agent_id, str) or _AGENT.fullmatch(agent_id) is None):
            _fail()
        after = value["after"]
        if (not isinstance(after, list) or len(after) > index
                or any(type(item) is not int or not 0 <= item < index for item in after)
                or len(set(after)) != len(after)):
            _fail()
        title = _text(value["title"], maximum=160, required=True)
        if title.casefold() in seen_titles:
            _fail()
        seen_titles.add(title.casefold())
        tasks.append({
            "title": title,
            "description": _text(value["description"], maximum=4096,
                                 required=False, multiline=True),
            "agent_id": agent_id,
            "due_date": _due_date(value["due_date"]),
            "after": sorted(after),
        })
    snapshot = {"version": 1, "summary": summary, "questions": questions,
                "tasks": tasks}
    if len(_snapshot_bytes(snapshot)) > MAX_ARTIFACT_BYTES:
        _fail()
    return snapshot


def _snapshot_bytes(snapshot: dict) -> bytes:
    try:
        return json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail()


def proposal_snapshot_digest(snapshot: dict) -> str:
    """Digest only a snapshot returned by this parser, with canonical bytes."""
    if not isinstance(snapshot, dict) or set(snapshot) != _TOP_KEYS:
        _fail()
    encoded = _snapshot_bytes(snapshot)
    if len(encoded) > MAX_ARTIFACT_BYTES:
        _fail()
    if parse_proposal_artifact(encoded) != snapshot:
        _fail()
    return hashlib.sha256(encoded).hexdigest()
