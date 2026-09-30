"""Fixed credential-free frontend inside a Project worker namespace.

The inherited broker carries only bounded completion bodies and normalized
replies. It grants no provider authority; the host broker independently checks
admission, exact inputs, policy, call identity, journal and revocation.
"""
from __future__ import annotations

import array
import ctypes
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import selectors
import socket
import struct
import subprocess
import sys
import threading
import time

MAX_REQUEST = 16 * 1024 * 1024
MAX_TEXT = 32768
MAX_OUTPUT = 512 * 1024
MAX_REPLY = 2 * MAX_TEXT + 256


class FrontendError(RuntimeError):
    pass


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise FrontendError("duplicate")
        result[key] = value
    return result


def _json(data):
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(FrontendError("constant")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise FrontendError("json") from exc


def _text(value):
    if (not isinstance(value, str) or len(value) > MAX_TEXT
            or any(ord(c) < 32 and c not in "\t\r\n" for c in value)
            or len(value.encode("utf-8")) > MAX_TEXT):
        raise FrontendError("text")
    return value


def _read_exact(endpoint, length, deadline=None):
    value = bytearray()
    while len(value) < length:
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FrontendError("deadline")
            endpoint.settimeout(remaining)
        chunk = endpoint.recv(length - len(value))
        if not chunk:
            raise FrontendError("eof")
        value.extend(chunk)
    return bytes(value)


def exchange(endpoint, body, deadline):
    if not 0 < len(body) <= MAX_REQUEST or time.monotonic() >= deadline:
        raise FrontendError("request")
    endpoint.settimeout(max(.001, deadline - time.monotonic()))
    endpoint.sendall(struct.pack("!I", len(body)) + body)
    amount = struct.unpack("!I", _read_exact(endpoint, 4, deadline))[0]
    if not 0 < amount <= MAX_REPLY:
        raise FrontendError("reply")
    reply = _json(_read_exact(endpoint, amount, deadline))
    if not isinstance(reply, dict):
        raise FrontendError("reply")
    if set(reply) == {"state", "text"} and reply["state"] == "succeeded":
        _text(reply["text"])
    elif (set(reply) != {"state", "disposition"}
          or reply["state"] not in {"unknown", "failed"}
          or reply["disposition"] not in {"unknown", "rejected", "non_text", "oversized"}):
        raise FrontendError("reply")
    return reply


def _completion(text, model):
    chunks = []
    for delta, reason in (({"role": "assistant", "content": text}, None), ({}, "stop")):
        chunk = {"id": "mentat-completion", "object": "chat.completion.chunk", "created": 0,
                 "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": reason}]}
        chunks.append("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n")
    return ("".join(chunks) + "data: [DONE]\n\n").encode("utf-8")


class CompletionServer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, broker, model, deadline):
        self.broker, self.model, self.deadline = broker, model, deadline
        self.attempts = 0
        self.accepted_text = None
        super().__init__(("127.0.0.1", 0), CompletionHandler)

    def get_request(self):
        endpoint, address = super().get_request()
        endpoint.settimeout(min(2, max(.001, self.deadline - time.monotonic())))
        return endpoint, address


class CompletionHandler(BaseHTTPRequestHandler):
    def _reply(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_POST(self):
        self.server.attempts += 1
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if (self.path != "/v1/chat/completions" or len(lengths) != 1
                    or not lengths[0].isascii() or not lengths[0].isdigit()
                    or self.headers.get_all("Transfer-Encoding")
                    or self.server.attempts > 8 or time.monotonic() >= self.server.deadline):
                raise FrontendError("request")
            amount = int(lengths[0])
            if not 0 < amount <= MAX_REQUEST:
                raise FrontendError("request")
            body = self.rfile.read(amount)
            if len(body) != amount:
                raise FrontendError("request")
            parsed = _json(body)
            if (not isinstance(parsed, dict) or parsed.get("model") != self.server.model
                    or parsed.get("stream") is not True or parsed.get("tools") not in (None, [])):
                raise FrontendError("request")
            # Raw bytes, never headers or a caller-chosen upstream destination.
            reply = exchange(self.server.broker, body, self.server.deadline)
            if reply["state"] != "succeeded":
                self._reply(409, b'{"error":{"message":"completion unavailable"}}')
                return
            self.server.accepted_text = reply["text"]
            self._reply(200, _completion(reply["text"], self.server.model), "text/event-stream")
        except (FrontendError, OSError, ValueError, UnicodeError):
            self._reply(400, b'{"error":{"message":"completion rejected"}}')

    def log_message(self, *_):
        pass


def run_bounded(command, environment, deadline):
    """Drain both pipes incrementally; never collect unbounded child output."""
    child = subprocess.Popen(command, cwd="/worker", env=environment, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True)
    selector = selectors.DefaultSelector()
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    total = 0
    try:
        for label, stream in (("stdout", child.stdout), ("stderr", child.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, label)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FrontendError("deadline")
            for key, _ in selector.select(min(.1, remaining)):
                data = os.read(key.fd, 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                total += len(data)
                if total > MAX_OUTPUT:
                    raise FrontendError("output")
                outputs[key.data].extend(data)
        code = child.wait(timeout=max(.001, deadline - time.monotonic()))
        return code, bytes(outputs["stdout"]), total
    finally:
        selector.close()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=1)
        child.stdout.close()
        child.stderr.close()


def terminal_result(output, code):
    terminals = []
    for line in output.splitlines():
        try:
            value = _json(line)
        except FrontendError:
            if line.lstrip().startswith(b"{"):
                raise FrontendError("terminal")
            continue  # Bounded scanner warnings are inert diagnostics.
        if isinstance(value, dict) and value.get("type") == "result":
            terminals.append(value)
    if len(terminals) != 1 or type(terminals[0].get("exit_code")) is not int:
        raise FrontendError("terminal")
    if code != 0 or terminals[0]["exit_code"] != code:
        raise FrontendError("terminal")
    return _text(terminals[0].get("text"))


def _notify(endpoint, value, descriptor=None):
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ancillary = [] if descriptor is None else [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                                array.array("i", [descriptor]))]
    if endpoint.sendmsg([data], ancillary) != len(data):
        raise FrontendError("control")


def main():
    # The sealed configuration is generated by Mentat, not worker/browser input.
    with open("/worker/config.json", "rb") as source:
        config = source.read(4097)
    if len(config) > 4096:
        raise FrontendError("config")
    spec = _json(config)
    broker = socket.socket(fileno=int(sys.argv[1]))
    lifecycle = socket.socket(fileno=int(sys.argv[2]))
    # Mount-source descriptors must never survive into the frontend. In
    # particular, an outside directory FD could permit openat('..') escape.
    keep = {0, 1, 2, broker.fileno(), lifecycle.fileno()}
    for name in os.listdir("/proc/self/fd"):
        descriptor = int(name)
        if descriptor not in keep:
            try:
                os.close(descriptor)
            except OSError:
                pass  # os.listdir's already-closed enumeration descriptor.
    deadline = float(sys.argv[3])
    server = thread = None
    exports = None
    try:
        library = ctypes.CDLL(None, use_errno=True)
        if library.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            raise FrontendError("boundary")
        server = CompletionServer(broker, spec["model"], deadline)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        exports = os.open("/exports", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        _notify(lifecycle, {"version": 1, "kind": "ready"}, exports)
        endpoint = "http://127.0.0.1:" + str(server.server_address[1]) + "/v1"
        environment = {"PATH": "/usr/bin:/bin", "HOME": "/home/mentat",
                       "HERMES_HOME": "/home/mentat/.hermes", "LANG": "C.UTF-8",
                       "HERMES_SAFE_MODE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONNOUSERSITE": "1", "CUSTOM_BASE_URL": endpoint,
                       "OPENAI_BASE_URL": endpoint, "OPENAI_API_KEY": "mentat-local-only",
                       "NO_PROXY": "127.0.0.1,localhost"}
        cli = spec["venv"] + "/bin/hermes"
        settings = (("agent.image_input_mode", "native"),
                    ("model.supports_vision", "true" if spec["vision"] else "false"),
                    ("auxiliary.title_generation.enabled", "false"),
                    ("agent.api_max_retries", "1"), ("agent.auto_recovery_cycles", "0"))
        for key, expected in settings:
            code, _, _ = run_bounded([cli, "config", "set", key, expected], environment, deadline)
            if code != 0:
                raise FrontendError("config")
            code, output, _ = run_bounded([cli, "config", "get", key, "--json"], environment, deadline)
            readback = _json(output.strip())
            if code != 0 or readback != (expected == "true" if expected in {"true", "false"} else int(expected) if expected.isdigit() else expected):
                raise FrontendError("config")
        command = [cli, "chat", "--ignore-rules", "--provider", "custom", "--model", spec["model"],
                   "--toolsets", "bot_room", "--max-turns", "1", "--run-budget", str(spec["wall_seconds"]),
                   "--query-file", "/inputs/query.txt", "--oneshot", "--format", "stream-json"]
        if spec["image_extension"]:
            command += ["--image", "/inputs/image" + spec["image_extension"]]
        code, output, total = run_bounded(command, environment, deadline)
        text = terminal_result(output, code)
        if server.accepted_text != text:
            raise FrontendError("terminal")
        descriptor = os.open("completion.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=exports)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        _notify(lifecycle, {"version": 1, "kind": "terminal", "exit_code": code,
                            "text": text, "output_bytes": total})
        return 0
    except (FrontendError, OSError, ValueError, subprocess.SubprocessError):
        try:
            _notify(lifecycle, {"version": 1, "kind": "failed"})
        except OSError:
            pass
        return 1
    finally:
        broker.close()
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=2)
        if exports is not None:
            os.close(exports)
        lifecycle.close()


if __name__ == "__main__":
    raise SystemExit(main())
