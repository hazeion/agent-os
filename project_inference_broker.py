"""Durable proposal broker core with an explicit synthetic qualification backend.

No production factory, credentials, provider URL or Run admission is exposed.
Real backends require separately qualified credential/release/model custody and
durable scope admission. Historical fixtures here cannot grant that authority.
"""
from __future__ import annotations

from contextlib import closing, nullcontext
from dataclasses import dataclass, field
import base64
import hashlib
import json
import math
from pathlib import Path
import socket
import sqlite3
import struct
import threading
import time

import mentat_db
import project_worker_journal as journal
from agent_console_attachments import read_attachment_bytes
from private_state import private_state_lock
from run_repository import RunRepository
from mentat.project_worker_frontend import _json, _read_exact, MAX_REPLY
from mentat.project_worker_scope import LinuxWorkerScope, WorkerScopeLimits, _effective_limits

SYSTEM = ("You are the selected Mentat Project lead. Propose a plan only; do not execute work. "
          "Use only the supplied Project brief, owner instructions and selected files. "
          "Ask bounded blocking questions for missing measurements or goals; never invent them. "
          "Return one JSON proposal in the version-1 Mentat proposal format, with at most "
          "16 new tasks and 8 blocking questions. Exact top-level keys: version (1), summary "
          "(nonempty text, at most 2048 UTF-8 bytes), questions, tasks. A question has exactly "
          "kind (measurement or clarification) and text (nonempty, at most 512 UTF-8 bytes). "
          "A task has exactly title (nonempty, at most 160 UTF-8 bytes), description (at most "
          "4096 UTF-8 bytes), agent_id (null; the owner assigns Agents), due_date (null or "
          "YYYY-MM-DD), and after (unique zero-based indexes of earlier tasks). Include at "
          "least one task or blocking question, no duplicate titles/questions and no extra "
          "keys, HTML, Markdown fences or control characters. Entire JSON at most 32 KiB. "
          "Assignments and dependencies are suggestions for exact owner review.")
_MIMES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_FIELDS = {"model", "messages", "stream", "tools", "stream_options", "max_tokens",
           "max_completion_tokens", "temperature", "top_p", "reasoning_effort",
           "prompt_cache_key", "prompt_cache_retention"}
_UNKNOWN = {"state": "unknown", "disposition": "unknown"}
_INDETERMINATE = object()


class InferenceBrokerError(RuntimeError):
    pass


def _fail(code="invalid"):
    raise InferenceBrokerError("project_broker." + code)


def _encode(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail()


@dataclass(frozen=True)
class ProposalInputs:
    manifest_digest: str
    query: bytes = field(repr=False)
    image: bytes | None = field(default=None, repr=False)
    image_mime: str | None = None
    image_digest: str | None = None

    @property
    def image_extension(self):
        return _MIMES.get(self.image_mime, "")


def _derive_inputs(root, connection, run_id, generation):
    RunRepository(connection).validate(private_qualification_proposals=True)
    claim = journal._live_generation(connection, run_id, generation)
    receipt = connection.execute("SELECT context_id,input_id,manifest_digest,runtime_type FROM "
                                 "mentat_project_proposal_input_receipts WHERE run_id=?", (run_id,)).fetchone()
    if receipt is None or receipt[3] != "hermes":
        _fail("runtime")
    brief = connection.execute("SELECT brief FROM mentat_project_context_versions WHERE id=?", (receipt[0],)).fetchone()[0]
    instructions = connection.execute("SELECT instructions FROM mentat_project_planning_input_versions WHERE id=?", (receipt[1],)).fetchone()[0]
    files = connection.execute("SELECT attachment_id,blob_id,sha256,byte_size,kind,mime_type FROM "
                               "mentat_project_proposal_input_files WHERE run_id=? ORDER BY ordinal", (run_id,)).fetchall()
    text_files = []
    image = mime = image_digest = None
    for ordinal, row in enumerate(files):
        metadata, data = read_attachment_bytes(root, row[0])
        if ((metadata["kind"], metadata["mime_type"], metadata["byte_size"]) != tuple(row[4:6]) + (row[3],)
                or len(data) != row[3] or hashlib.sha256(data).hexdigest() != row[2]):
            _fail("inputs")
        if row[4] == "image":
            if image is not None or row[5] not in _MIMES or not 0 < len(data) <= 8 * 1024 * 1024:
                _fail("inputs")
            image, mime, image_digest = data, row[5], row[2]
        else:
            try:
                text_files.append({"ordinal": ordinal, "text": data.decode("utf-8")})
            except UnicodeError:
                _fail("inputs")
    query = _encode({"format": 1, "operation": "project_proposal", "brief": brief,
                     "instructions": instructions, "files": text_files,
                     "has_native_image": image is not None})
    policy, snapshot = json.loads(claim[6]), json.loads(claim[8])
    if len(query) > 1024 * 1024 or (image is not None and snapshot["supports_vision"] is not True):
        _fail("inputs")
    return ProposalInputs(receipt[2], query, image, mime, image_digest), policy, snapshot


def derive_qualification_inputs(root: Path, run_id: str, generation: str) -> ProposalInputs:
    """Private historical fixture preparation, not permission to execute."""
    with private_state_lock(root), closing(mentat_db.connect(root)) as connection:
        connection.execute("BEGIN")
        try:
            inputs, _, _ = _derive_inputs(root, connection, run_id, generation)
            return inputs
        finally:
            connection.rollback()


def _host_request(raw, inputs, policy, snapshot):
    if type(raw) is not bytes or not 0 < len(raw) <= policy["max_request_bytes"]:
        _fail("request")
    try:
        body = _json(raw)
    except (ValueError, RuntimeError):
        _fail("request")
    if (not isinstance(body, dict) or not {"model", "messages", "stream"} <= set(body) <= _FIELDS
            or body["model"] != snapshot["model"] or body["stream"] is not True
            or body.get("tools") not in (None, [])):
        _fail("request")
    for key in ("max_tokens", "max_completion_tokens"):
        value = body.get(key)
        if value is not None and (type(value) is not int or not 0 < value <= 8192):
            _fail("request")
    for key in ("temperature", "top_p"):
        value = body.get(key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 2):
            _fail("request")
    for key in ("reasoning_effort", "prompt_cache_key", "prompt_cache_retention"):
        value = body.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 256
                                 or any(ord(c) < 32 for c in value)):
            _fail("request")
    if "stream_options" in body and body["stream_options"] != {"include_usage": True}:
        _fail("request")
    messages = body["messages"]
    if not isinstance(messages, list) or not 1 <= len(messages) <= 5:
        _fail("request")
    for message in messages[:-1]:
        if (not isinstance(message, dict) or set(message) != {"role", "content"}
                or message["role"] != "system" or not isinstance(message["content"], str)
                or len(message["content"]) > 65536):
            _fail("request")
    user = messages[-1]
    if not isinstance(user, dict) or set(user) != {"role", "content"} or user["role"] != "user":
        _fail("request")
    text = inputs.query.decode("utf-8")
    if inputs.image is None:
        expected = text
    else:
        # Stock 0.21.5 appends this fixed local-input annotation. Validate its
        # exact namespace alias, then discard it from the host-owned request.
        annotated = text + "\n\n[Image attached at: /inputs/image" + inputs.image_extension + "]"
        expected = [{"type": "text", "text": annotated}, {"type": "image_url", "image_url": {
            "url": "data:" + inputs.image_mime + ";base64," + base64.b64encode(inputs.image).decode("ascii")}}]
        # Stock may set the default native-image detail explicitly.
        content = user["content"]
        if isinstance(content, list) and len(content) == 2 and isinstance(content[1], dict):
            image_url = content[1].get("image_url")
            if isinstance(image_url, dict) and image_url.get("detail") == "auto":
                expected[1]["image_url"]["detail"] = "auto"
    if user["content"] != expected:
        _fail("inputs")
    # Construct fresh trusted content; do not retain the worker's detail or
    # system text in the provider operation.
    actual_content = text if inputs.image is None else [
        {"type": "text", "text": text}, {"type": "image_url", "image_url": {
            "url": "data:" + inputs.image_mime + ";base64," + base64.b64encode(inputs.image).decode("ascii")}}]
    actual = {"model": snapshot["model"], "messages": [{"role": "system", "content": SYSTEM},
               {"role": "user", "content": actual_content}], "max_tokens": policy["max_output_tokens"], "stream": False}
    if len(_encode(actual)) > policy["max_request_bytes"]:
        _fail("request")
    return actual, hashlib.sha256(_encode([1, inputs.manifest_digest, body, actual])).hexdigest()


class SyntheticCompletionBackend:
    """Explicit fake completion; no callable, URL, credential or network path."""
    def __init__(self, text: object = "PROBE_OK", *, unknown=False, release: threading.Event | None = None):
        if type(unknown) is not bool or (release is not None and type(release) is not threading.Event):
            _fail("synthetic")
        self._text, self._unknown, self._release = text, unknown, release
        self.calls = 0
        self.requests = []
        self.started = threading.Event()

    def _start(self, request, deadline):
        if time.monotonic() >= deadline:
            _fail("deadline")
        if self.calls != 0:
            _fail("spent")
        self.calls += 1
        self.requests.append(request)
        self.started.set()
        return self

    def _wait(self, deadline):
        if self._release is not None and not self._release.wait(max(0, deadline - time.monotonic())):
            return _INDETERMINATE
        return _INDETERMINATE if self._unknown else self._text


class SyntheticScope:
    """Private test scope; never qualifies a real process or Run."""
    def __init__(self, wall_seconds=20, *, memory_bytes=512 * 1024 * 1024, processes=32, cpu_percent=100):
        self._limits = WorkerScopeLimits(wall_seconds=wall_seconds, memory_bytes=memory_bytes,
                                         processes=processes, cpu_percent=cpu_percent)
        self.deadline = time.monotonic() + wall_seconds
        self.alive = True

    @property
    def limits(self):
        return self._limits


class QualificationInferenceBroker:
    """Durable fake-backend controller used only for component qualification."""
    def __init__(self, root, run_id, generation, backend, scope):
        if type(backend) is not SyntheticCompletionBackend or type(scope) not in (SyntheticScope, LinuxWorkerScope):
            _fail("unqualified")
        self._root, self._run, self._generation = Path(root), run_id, generation
        self._backend, self._scope = backend, scope
        self._fence = threading.RLock()
        self._stopped = False
        self._endpoint = None
        self._scope_identity = None
        if type(scope) is LinuxWorkerScope:
            self._scope_identity = (scope.unit, scope._invocation, scope._identity)
        with private_state_lock(self._root), closing(mentat_db.connect(self._root)) as connection:
            connection.execute("BEGIN")
            self._inputs, self._policy, self._snapshot = _derive_inputs(self._root, connection, self._run, self._generation)
            if self._snapshot["provider"] != "custom" or self._snapshot["model"] not in {"mentat-test", "mentat-probe"}:
                _fail("synthetic")
        self._policy_limits = WorkerScopeLimits(**{key: self._policy[key] for key in
                                                   ("wall_seconds", "memory_bytes", "processes", "cpu_percent")})
        self._deadline = scope.deadline if type(scope) is SyntheticScope else scope._deadline
        if (type(self._deadline) not in (int, float) or not math.isfinite(self._deadline)
                or self._deadline <= time.monotonic()):
            _fail("scope")
        self._check_limits()
        with private_state_lock(self._root), closing(mentat_db.connect(self._root)) as connection:
            self._live(connection)

    @property
    def deadline(self):
        current = self._scope.deadline if type(self._scope) is SyntheticScope else self._scope._deadline
        if (type(current) not in (int, float) or not math.isfinite(current)
                or current <= time.monotonic()):
            _fail("fenced")
        return min(self._deadline, current)

    def _check_limits(self):
        if any(getattr(self._scope.limits, key) > getattr(self._policy_limits, key)
               for key in ("wall_seconds", "memory_bytes", "processes", "cpu_percent")):
            _fail("policy")

    def _live(self, connection):
        if (self._stopped or type(self.deadline) not in (int, float)
                or not math.isfinite(self.deadline) or time.monotonic() >= self.deadline):
            _fail("fenced")
        self._check_limits()
        # Qualification consistency is separate from archival eligibility:
        # an owned scope remains ineligible for private backup capture.
        RunRepository(connection).validate(private_qualification_proposals=True)
        journal._live_generation(connection, self._run, self._generation)
        if self._run not in journal.qualification_proposal_ids(connection):
            _fail("synthetic")
        if type(self._scope) is SyntheticScope:
            if connection.execute('SELECT 1 FROM mentat_project_worker_scopes WHERE run_id=?', (self._run,)).fetchone():
                _fail("fenced")
            if not self._scope.alive:
                _fail("fenced")
        else:
            with self._scope._lock:
                scope = self._scope
                if (scope._closed or scope.deadline_hit or scope._control is None
                        or (scope.unit, scope._invocation, scope._identity) != self._scope_identity
                        or scope._descriptor is None or scope._empty()):
                    _fail("fenced")
                state = scope._state()
                if (state["InvocationID"] != scope._invocation or state["ControlGroup"] != scope._relative
                        or state["ActiveState"] != "active"):
                    _fail("fenced")
                _effective_limits(scope._descriptor, self._policy_limits)
                row = connection.execute('SELECT * FROM mentat_project_worker_scopes WHERE run_id=?', (self._run,)).fetchone()
                if row is None or row[1] != self._generation or row[10] != 'owned' or row[9] != 3:
                    _fail("fenced")
                from mentat.project_scope_evidence import witness_metadata
                owned = witness_metadata(scope.journal_owned_identity(), 'owned')
                if json.loads(row[11]) != owned:
                    _fail("fenced")
                frozen = getattr(self, '_scope_receipt', None)
                if frozen is not None and frozen != tuple(row):
                    _fail("fenced")
                self._scope_receipt = tuple(row)

    def stop(self):
        """Fence new synthetic submissions; owned local Stop remains separate."""
        with self._fence:
            self._stopped = True
            if self._endpoint is not None:
                try:
                    self._endpoint.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def handle_body(self, raw):
        try:
            with self._fence:
                with private_state_lock(self._root), closing(mentat_db.connect(self._root)) as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    self._live(connection)
                    current, policy, snapshot = _derive_inputs(self._root, connection, self._run, self._generation)
                    if current != self._inputs or policy != self._policy or snapshot != self._snapshot:
                        _fail("inputs")
                    actual, digest = _host_request(raw, current, policy, snapshot)
                    receipt = journal.reserve_call(connection, run_id=self._run, generation=self._generation,
                                                   request_digest=digest)
                    connection.commit()
                    if not receipt.newly_reserved:
                        self._live(connection)
                        return self._cached(receipt)
                with private_state_lock(self._root), closing(mentat_db.connect(self._root)) as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    self._live(connection)
                    if not journal.record_submission(connection, call_id=receipt.call_id, generation=self._generation,
                            request_digest=digest, settlement_token=receipt.settlement_token):
                        _fail("unknown")
                    connection.commit()
                    row = connection.execute("SELECT state FROM mentat_project_worker_calls WHERE call_id=?", (receipt.call_id,)).fetchone()
                    if row is None or row[0] != "unknown":
                        _fail("unknown")
                    # Only constant-time synthetic acceptance occurs under the
                    # fence/root/scope lock, after commit. No network or wait.
                    scope_lock = self._scope._lock if type(self._scope) is LinuxWorkerScope else nullcontext()
                    with scope_lock:
                        self._live(connection)
                        submission = self._backend._start(actual, self.deadline)
            # Never hold a database/private-state or submission fence during work.
            text = submission._wait(self.deadline)
            if text is _INDETERMINATE:
                return dict(_UNKNOWN)
            with private_state_lock(self._root), closing(mentat_db.connect(self._root)) as connection:
                connection.execute("BEGIN IMMEDIATE")
                journal.settle_call(connection, call_id=receipt.call_id, generation=self._generation,
                    request_digest=digest, settlement_token=receipt.settlement_token, response_text=text)
                connection.commit()
            with self._fence, private_state_lock(self._root), closing(mentat_db.connect(self._root)) as connection:
                self._live(connection)
                row = connection.execute("SELECT state,response_text,disposition FROM mentat_project_worker_calls WHERE call_id=?", (receipt.call_id,)).fetchone()
                return self._cached(journal.CallReceipt(receipt.call_id, row[0], False, row[1], row[2]))
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            # An ambiguous transaction/validation fault suspends this channel;
            # the worker cannot turn it into an automatic new first attempt.
            self.stop()
            return dict(_UNKNOWN)

    @staticmethod
    def _cached(receipt):
        if receipt.state == "succeeded":
            return {"state": "succeeded", "text": receipt.response_text}
        if receipt.state == "failed":
            return {"state": "failed", "disposition": receipt.disposition}
        return dict(_UNKNOWN)

    def serve(self, endpoint):
        if type(endpoint) is not socket.socket or endpoint.family != socket.AF_UNIX or endpoint.type != socket.SOCK_STREAM:
            _fail("transport")
        with self._fence:
            if self._endpoint is not None or self._stopped:
                _fail("transport")
            with private_state_lock(self._root), closing(mentat_db.connect(self._root)) as connection:
                self._live(connection)
            self._endpoint = endpoint
        try:
            for _ in range(8):
                amount = struct.unpack("!I", _read_exact(endpoint, 4, self.deadline))[0]
                if not 0 < amount <= self._policy["max_request_bytes"]:
                    _fail("request")
                reply = _encode(self.handle_body(_read_exact(endpoint, amount, self.deadline)))
                if len(reply) > MAX_REPLY or time.monotonic() >= self.deadline:
                    _fail("reply")
                with self._fence:
                    if self._stopped or time.monotonic() >= self.deadline:
                        _fail("fenced")
                    endpoint.settimeout(self.deadline - time.monotonic())
                    endpoint.sendall(struct.pack("!I", len(reply)) + reply)
        except (OSError, ValueError, RuntimeError):
            pass
        finally:
            self.stop()
            endpoint.close()
