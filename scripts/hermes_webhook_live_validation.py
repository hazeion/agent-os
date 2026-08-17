#!/usr/bin/env python3
"""Run a redacted, isolated stock-Hermes webhook qualification.

The harness never touches the operator's Hermes home. It launches Mentat with
temporary data, drives stock Hermes from a caller-supplied immutable checkout,
and prints only boolean/count evidence. Raw webhook material remains in memory.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import datetime, timezone
import hashlib
import hmac
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


EXPECTED_COMMIT = "f80f453ae0679347e38abc917c7f94f717bf96c5"
EXPECTED_VERSION = "0.20.1"
EVENTS = (
    "on_session_start",
    "on_session_end",
    "subagent_start",
    "subagent_stop",
)


class _QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


class _FakeModelHandler(_QuietHandler):
    model_name = "mentat-webhook-live"

    def _json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") in {"/v1/models", "/api/v0/models"}:
            self._json(
                {
                    "object": "list",
                    "data": [
                        {
                            "id": self.model_name,
                            "object": "model",
                            "owned_by": "mentat-live-fixture",
                        }
                    ],
                }
            )
            return
        self._json({"error": "not_found"}, 404)

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json({"error": "not_found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            request_payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "invalid_request"}, 400)
            return
        response_id = "chatcmpl-live-fixture"
        if request_payload.get("stream"):
            chunks = (
                {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": self.model_name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "LIVE_OK"},
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": response_id,
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": self.model_name,
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "stop"}
                    ],
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 2,
                        "total_tokens": 10,
                    },
                },
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for chunk in chunks:
                self.wfile.write(
                    b"data: "
                    + json.dumps(chunk, separators=(",", ":")).encode()
                    + b"\n\n"
                )
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return
        self._json(
            {
                "id": response_id,
                "object": "chat.completion",
                "created": 1,
                "model": self.model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "LIVE_OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 2,
                    "total_tokens": 10,
                },
            }
        )


class _RelayState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.mentat_port = 0
        self.attempts: list[tuple[bytes, dict[str, str]]] = []
        self.fail_next = False
        self.drop_next = False
        self.duplicate_next = False
        self.hold_next = False
        self.held: tuple[bytes, dict[str, str]] | None = None

    def snapshot_count(self) -> int:
        with self.lock:
            return len(self.attempts)


class _RelayHandler(_QuietHandler):
    state: _RelayState

    def _respond(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    @classmethod
    def _forward(cls, body: bytes, headers: dict[str, str]) -> int:
        forwarded = {
            key: value
            for key, value in headers.items()
            if key.lower()
            in {
                "content-type",
                "x-hermes-event",
                "x-hermes-delivery",
                "x-hermes-signature-256",
            }
        }
        connection = HTTPConnection("127.0.0.1", cls.state.mentat_port, timeout=5)
        try:
            connection.request(
                "POST",
                "/api/integrations/hermes/webhooks/v1/local-default",
                body,
                forwarded,
            )
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
            body = self.rfile.read(length)
        except ValueError:
            self._respond(400)
            return
        headers = {key: value for key, value in self.headers.items()}
        state = self.state
        with state.lock:
            state.attempts.append((body, headers))
            if state.fail_next:
                state.fail_next = False
                action = "fail"
            elif state.drop_next:
                state.drop_next = False
                action = "drop"
            elif state.hold_next:
                state.hold_next = False
                state.held = (body, headers)
                action = "hold"
            else:
                action = "duplicate" if state.duplicate_next else "forward"
                state.duplicate_next = False
                held = state.held
                state.held = None
        if action == "fail":
            self._respond(503)
            return
        if action in {"drop", "hold"}:
            self._respond(204)
            return
        status = self._forward(body, headers)
        if action == "duplicate":
            self._forward(body, headers)
        if held is not None:
            self._forward(*held)
        self._respond(status)


def _start_http(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_http(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _http_json(url: str, *, method: str = "GET", payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    body = None if payload is None else json.dumps(payload).encode()
    request_headers = dict(headers or {})
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read()
        with suppress(json.JSONDecodeError):
            return exc.code, json.loads(raw) if raw else {}
        return exc.code, {}


def _wait_json(url: str, timeout: float = 20) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, payload = _http_json(url)
            if status == 200:
                return payload
        except (OSError, URLError):
            pass
        time.sleep(0.1)
    raise RuntimeError("local service did not become ready")


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _start_mentat(
    project_root: Path,
    data_dir: Path,
    hermes_home: Path,
    vault: Path,
    port: int,
    secret: str | None,
    log_path: Path,
) -> tuple[subprocess.Popen[bytes], Any]:
    environment = os.environ.copy()
    if secret is None:
        environment.pop("MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT", None)
    else:
        environment["MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT"] = secret
    log_handle = log_path.open("ab")
    process = subprocess.Popen(
        [
            str(project_root / ".venv" / "bin" / "python"),
            str(project_root / "server.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--data-dir",
            str(data_dir),
            "--hermes-home",
            str(hermes_home),
            "--obsidian-vault",
            str(vault),
        ],
        cwd=project_root,
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_json(f"http://127.0.0.1:{port}/api/hermes/webhooks/health")
    except Exception:
        _stop_process(process)
        log_handle.close()
        raise
    return process, log_handle


def _run_stock_dispatch(
    python: Path,
    source: Path,
    home: Path,
    events: tuple[str, ...],
    *,
    safe_mode: bool = False,
    private_canary: str = "",
    working_dir: Path | None = None,
) -> subprocess.CompletedProcess[bytes]:
    code = """
import os
from hermes_cli.config import load_config
from agent.outbound_webhooks import flush, register_from_config
from hermes_cli.plugins import get_plugin_manager
targets = register_from_config(load_config())
manager = get_plugin_manager()
events = os.environ['MENTAT_LIVE_EVENTS'].split(',')
private_canary = os.environ.get('MENTAT_LIVE_PRIVATE_CANARY', '')
for event in events:
    payload = {'session_id': 'live-session', 'platform': 'cli'}
    if event == 'on_session_end':
        payload.update(completed=True, interrupted=False)
    elif event.startswith('subagent_'):
        payload = {
            'parent_session_id': 'live-parent',
            'child_status': 'completed',
            'child_goal': private_canary,
            'child_summary': private_canary,
        }
    manager.invoke_hook(event, **payload)
if not flush(timeout=8):
    raise SystemExit(3)
"""
    environment = os.environ.copy()
    secret_value = ""
    for line in (home / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("HERMES_OUTBOUND_WEBHOOK_SECRET="):
            secret_value = line.split("=", 1)[1]
            break
    environment.update(
        {
            "HERMES_HOME": str(home),
            "HERMES_OUTBOUND_WEBHOOK_SECRET": secret_value,
            "MENTAT_LIVE_EVENTS": ",".join(events),
            "MENTAT_LIVE_PRIVATE_CANARY": private_canary,
            "PYTHONPATH": str(source),
        }
    )
    if safe_mode:
        environment["HERMES_SAFE_MODE"] = "1"
    else:
        environment.pop("HERMES_SAFE_MODE", None)
    return subprocess.run(
        [str(python), "-c", code],
        cwd=working_dir or source,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )


def _run_cli(
    hermes: Path,
    source: Path,
    home: Path,
    prompt: str,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["HERMES_HOME"] = str(home)
    environment.pop("HERMES_SAFE_MODE", None)
    return subprocess.run(
        [
            str(hermes),
            "chat",
            "--provider",
            "lmstudio",
            "--model",
            _FakeModelHandler.model_name,
            "--max-turns",
            "2",
            "--ignore-rules",
            "--quiet",
            "--query",
            prompt,
        ],
        cwd=source,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=45,
        check=False,
    )


def _start_gateway(
    hermes: Path,
    source: Path,
    home: Path,
    log_path: Path,
    gateway_port: int,
    api_key: str,
) -> tuple[subprocess.Popen[bytes], Any]:
    environment = os.environ.copy()
    environment.update(
        {
            "HERMES_HOME": str(home),
            "API_SERVER_ENABLED": "true",
            "API_SERVER_HOST": "127.0.0.1",
            "API_SERVER_PORT": str(gateway_port),
            "API_SERVER_KEY": api_key,
        }
    )
    environment.pop("HERMES_SAFE_MODE", None)
    log_handle = log_path.open("ab")
    process = subprocess.Popen(
        [str(hermes), "gateway", "run", "--force", "--no-supervise"],
        cwd=source,
        env=environment,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    return process, log_handle


def _wait_run_terminal(gateway_port: int, run_id: str, api_key: str) -> dict[str, Any]:
    deadline = time.monotonic() + 45
    headers = {"Authorization": f"Bearer {api_key}"}
    while time.monotonic() < deadline:
        status, payload = _http_json(
            f"http://127.0.0.1:{gateway_port}/v1/runs/{run_id}",
            headers=headers,
        )
        if status == 200 and payload.get("status") in {
            "completed",
            "failed",
            "cancelled",
        }:
            return payload
        time.sleep(0.2)
    raise RuntimeError("stock Gateway run did not finish")


def _write_hermes_config(
    home: Path,
    relay_port: int,
    model_port: int,
    gateway_port: int,
    api_key: str,
    *,
    target: bool = True,
) -> None:
    hooks = ""
    if target:
        hooks = f"""
hooks:
  outbound:
    - name: mentat-live
      url: http://127.0.0.1:{relay_port}/events
      events: [on_session_start, on_session_end, subagent_start, subagent_stop]
      secret_env: HERMES_OUTBOUND_WEBHOOK_SECRET
      timeout: 3
"""
    config = f"""model:
  default: {_FakeModelHandler.model_name}
  provider: lmstudio
  base_url: http://127.0.0.1:{model_port}/v1
agent:
  max_turns: 2
terminal:
  home_mode: profile
{hooks}"""
    (home / "config.yaml").write_text(config, encoding="utf-8")
    os.chmod(home / "config.yaml", 0o600)
    # Gateway reads these through Hermes' normal private dotenv loader.
    existing_secret = ""
    dotenv = home / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            if line.startswith("HERMES_OUTBOUND_WEBHOOK_SECRET="):
                existing_secret = line
                break
    dotenv.write_text(
        "\n".join(
            filter(
                None,
                (
                    existing_secret,
                    "API_SERVER_ENABLED=true",
                    "API_SERVER_HOST=127.0.0.1",
                    f"API_SERVER_PORT={gateway_port}",
                    f"API_SERVER_KEY={api_key}",
                ),
            )
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(dotenv, 0o600)


def _find_free_port() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    try:
        return int(server.server_port)
    finally:
        server.server_close()


def _scan_for_canaries(paths: list[Path], canaries: tuple[bytes, ...]) -> bool:
    for root in paths:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for candidate in candidates:
            with suppress(OSError):
                data = candidate.read_bytes()
                if any(canary in data for canary in canaries):
                    return False
    return True


def _signed_mentat_delivery(port: int, secret: str, index: int) -> int:
    delivery_id = f"storm-{index:04d}-{secrets.token_hex(8)}"
    body = json.dumps(
        {
            "delivery_id": delivery_id,
            "hook_event_name": "on_session_start",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "POST",
            "/api/integrations/hermes/webhooks/v1/local-default",
            body,
            {
                "Content-Type": "application/json",
                "X-Hermes-Event": "on_session_start",
                "X-Hermes-Delivery": delivery_id,
                "X-Hermes-Signature-256": f"sha256={signature}",
            },
        )
        response = connection.getresponse()
        response.read()
        return response.status
    finally:
        connection.close()


def _wait_reconciliation(port: int, prior_count: int, timeout: float = 70) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        health = _wait_json(
            f"http://127.0.0.1:{port}/api/hermes/webhooks/health"
        )
        if health.get("counters", {}).get("reconciliations", 0) > prior_count:
            return health
        time.sleep(0.5)
    raise RuntimeError("Mentat reconciliation did not run")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hermes-source", type=Path, required=True)
    parser.add_argument("--hermes-python", type=Path, required=True)
    parser.add_argument("--legacy-hermes", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args(argv)


def main() -> int:
    args = _parse_args()
    source = args.hermes_source.resolve()
    # Preserve the virtual-environment path even when its interpreter is a
    # symlink into uv's shared runtime; sibling console scripts live beside it.
    python = args.hermes_python.absolute()
    project_root = args.project_root.resolve()
    hermes = python.parent / "hermes"

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        timeout=10,
    ).stdout.decode().strip()
    version_run = subprocess.run(
        [str(hermes), "--version"],
        cwd=source,
        env={**os.environ, "HERMES_HOME": str(source / ".mentat-unused-home")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    version_ok = version_run.returncode == 0 and EXPECTED_VERSION in version_run.stdout.decode(errors="replace")
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "stock_commit_verified": commit == EXPECTED_COMMIT,
        "stock_version_verified": version_ok,
        "observations": {},
    }
    if not (evidence["stock_commit_verified"] and evidence["stock_version_verified"]):
        print(json.dumps(evidence, sort_keys=True))
        return 1

    with tempfile.TemporaryDirectory(prefix="mentat-hermes-live-") as temporary:
        root = Path(temporary)
        home = root / "hermes-home"
        data_dir = root / "mentat-data"
        vault = root / "vault"
        home.mkdir(mode=0o700)
        vault.mkdir(mode=0o700)
        secret = secrets.token_urlsafe(36)
        api_key = secrets.token_hex(32)
        prompt_canary = "PROMPT_" + secrets.token_hex(12)
        path_canary = "PATH_" + secrets.token_hex(12)
        private_working_dir = root / path_canary
        private_working_dir.mkdir(mode=0o700)
        (home / ".env").write_text(
            f"HERMES_OUTBOUND_WEBHOOK_SECRET={secret}\n", encoding="utf-8"
        )
        os.chmod(home / ".env", 0o600)

        model_server, model_thread = _start_http(_FakeModelHandler)
        relay_state = _RelayState()
        _RelayHandler.state = relay_state
        relay_server, relay_thread = _start_http(_RelayHandler)
        mentat_port = _find_free_port()
        gateway_port = _find_free_port()
        relay_state.mentat_port = mentat_port
        _write_hermes_config(
            home,
            relay_server.server_port,
            model_server.server_port,
            gateway_port,
            api_key,
        )
        log_path = root / "mentat.log"
        mentat: subprocess.Popen[bytes] | None = None
        mentat_log = None
        gateway: subprocess.Popen[bytes] | None = None
        gateway_log = None
        gateway_log_path = root / "gateway.log"
        try:
            mentat, mentat_log = _start_mentat(
                project_root,
                data_dir,
                home,
                vault,
                mentat_port,
                secret,
                log_path,
            )

            dispatch = _run_stock_dispatch(
                python,
                source,
                home,
                EVENTS,
                private_canary=prompt_canary,
                working_dir=private_working_dir,
            )
            health = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            )
            with relay_state.lock:
                emitted_events = sorted(
                    {
                        headers.get("X-Hermes-Event", "")
                        for _body, headers in relay_state.attempts
                    }
                )
            evidence["observations"]["initial_relay_attempts"] = relay_state.snapshot_count()
            evidence["observations"]["initial_events"] = emitted_events
            evidence["observations"]["initial_accepted"] = health.get("counters", {}).get("accepted", 0)
            evidence["observations"]["dispatch_exit"] = dispatch.returncode
            evidence["all_four_stock_events"] = (
                dispatch.returncode == 0
                and health.get("counters", {}).get("accepted", 0) >= 4
            )

            before_retry = relay_state.snapshot_count()
            with relay_state.lock:
                relay_state.fail_next = True
            retry = _run_stock_dispatch(
                python, source, home, ("on_session_start",)
            )
            with relay_state.lock:
                retry_attempts = relay_state.attempts[before_retry:]
            evidence["retry_same_raw_delivery"] = (
                retry.returncode == 0
                and len(retry_attempts) == 2
                and retry_attempts[0][0] == retry_attempts[1][0]
                and retry_attempts[0][1].get("X-Hermes-Delivery")
                == retry_attempts[1][1].get("X-Hermes-Delivery")
            )

            captured_body, captured_headers = retry_attempts[-1]
            before_restart = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            ).get("counters", {}).get("accepted", 0)
            _stop_process(mentat)
            mentat_log.close()
            mentat = None
            mentat_log = None
            mentat, mentat_log = _start_mentat(
                project_root,
                data_dir,
                home,
                vault,
                mentat_port,
                secret,
                log_path,
            )
            replay_status = _RelayHandler._forward(captured_body, captured_headers)
            evidence["observations"]["restart_replay_status"] = replay_status
            evidence["restart_replay_deduplicated"] = replay_status == 204

            cli_before = relay_state.snapshot_count()
            cli_health_before = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            ).get("counters", {}).get("accepted", 0)
            cli = _run_cli(hermes, source, home, prompt_canary)
            cli_after = relay_state.snapshot_count()
            cli_health_after = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            ).get("counters", {}).get("accepted", 0)
            evidence["real_cli_lifecycle"] = (
                cli.returncode == 0
                and cli_after >= cli_before + 2
                and cli_health_after >= cli_health_before + 2
            )

            gateway_before = relay_state.snapshot_count()
            gateway_health_before = cli_health_after
            gateway, gateway_log = _start_gateway(
                hermes,
                source,
                home,
                gateway_log_path,
                gateway_port,
                api_key,
            )
            _wait_json(f"http://127.0.0.1:{gateway_port}/health", timeout=30)
            run_status, run_payload = _http_json(
                f"http://127.0.0.1:{gateway_port}/v1/runs",
                method="POST",
                payload={"input": "Reply exactly GATEWAY_OK."},
                headers={"Authorization": f"Bearer {api_key}"},
            )
            run_id = run_payload.get("run_id") if isinstance(run_payload, dict) else None
            terminal_run = (
                _wait_run_terminal(gateway_port, run_id, api_key)
                if run_status in {200, 201, 202} and isinstance(run_id, str)
                else {}
            )
            gateway_health_after = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            ).get("counters", {}).get("accepted", 0)
            evidence["real_gateway_lifecycle"] = (
                terminal_run.get("status") == "completed"
                and relay_state.snapshot_count() >= gateway_before + 2
                and gateway_health_after >= gateway_health_before + 2
            )
            _stop_process(gateway)
            gateway = None
            gateway_log.close()
            gateway_log = None

            duplicate_health_before = gateway_health_after
            with relay_state.lock:
                relay_state.duplicate_next = True
            duplicate = _run_stock_dispatch(
                python, source, home, ("on_session_start",)
            )
            duplicate_health_after = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            ).get("counters", {}).get("accepted", 0)
            evidence["live_duplicate_is_idempotent"] = (
                duplicate.returncode == 0
                and duplicate_health_after == duplicate_health_before + 1
            )

            ordering_health_before = duplicate_health_after
            with relay_state.lock:
                relay_state.hold_next = True
            held_end = _run_stock_dispatch(
                python, source, home, ("on_session_end",)
            )
            reversed_start = _run_stock_dispatch(
                python, source, home, ("on_session_start",)
            )
            ordering_health_after = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            ).get("counters", {}).get("accepted", 0)
            evidence["out_of_order_hints_remain_notifications"] = (
                held_end.returncode == 0
                and reversed_start.returncode == 0
                and ordering_health_after == ordering_health_before + 2
            )

            health_before_drop = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            )
            with relay_state.lock:
                relay_state.drop_next = True
            dropped = _run_stock_dispatch(
                python, source, home, ("on_session_end",)
            )
            dropped_health = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            )
            reconciled_health = _wait_reconciliation(
                mentat_port,
                dropped_health.get("counters", {}).get("reconciliations", 0),
            )
            evidence["dropped_hint_reconciles"] = (
                dropped.returncode == 0
                and dropped_health.get("counters", {}).get("accepted", 0)
                == health_before_drop.get("counters", {}).get("accepted", 0)
                and reconciled_health.get("counters", {}).get("reconciliations", 0)
                > dropped_health.get("counters", {}).get("reconciliations", 0)
            )

            # Restart to give the storm a fresh token bucket, while keeping the
            # same durable replay database and receiver configuration.
            _stop_process(mentat)
            mentat_log.close()
            mentat = None
            mentat_log = None
            mentat, mentat_log = _start_mentat(
                project_root,
                data_dir,
                home,
                vault,
                mentat_port,
                secret,
                log_path,
            )
            storm_started = time.monotonic()
            with ThreadPoolExecutor(max_workers=32) as pool:
                storm_statuses = list(
                    pool.map(
                        lambda index: _signed_mentat_delivery(
                            mentat_port,
                            secret,
                            index,
                        ),
                        range(1_000),
                    )
                )
            storm_elapsed = time.monotonic() - storm_started
            evidence["live_storm_rate_limited"] = (
                set(storm_statuses).issubset({202, 429})
                and storm_statuses.count(202) <= 160
                and storm_statuses.count(429) >= 840
                and storm_elapsed < 30
            )
            evidence["observations"]["storm_accepted"] = storm_statuses.count(202)
            evidence["observations"]["storm_rate_limited"] = storm_statuses.count(429)
            evidence["observations"]["storm_concurrency"] = 32

            safe_before = relay_state.snapshot_count()
            safe = _run_stock_dispatch(
                python,
                source,
                home,
                ("on_session_start",),
                safe_mode=True,
            )
            evidence["safe_mode_quiet"] = (
                safe.returncode == 0
                and relay_state.snapshot_count() == safe_before
            )

            # A missing Mentat binding fails closed even while stock Hermes is
            # still configured. The relay sees one attempt; Mentat accepts none.
            _stop_process(mentat)
            mentat_log.close()
            mentat = None
            mentat_log = None
            mentat, mentat_log = _start_mentat(
                project_root,
                data_dir,
                home,
                vault,
                mentat_port,
                None,
                log_path,
            )
            disabled_health = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            )
            disabled_before = relay_state.snapshot_count()
            disabled = _run_stock_dispatch(
                python, source, home, ("on_session_start",)
            )
            evidence["disabled_binding_fails_closed"] = (
                disabled.returncode == 0
                and relay_state.snapshot_count() == disabled_before + 1
                and disabled_health.get("state") == "off"
            )

            if args.legacy_hermes is not None:
                legacy_home = root / "legacy-hermes-home"
                legacy_home.mkdir(mode=0o700)
                _write_hermes_config(
                    legacy_home,
                    relay_server.server_port,
                    model_server.server_port,
                    gateway_port,
                    api_key,
                    target=False,
                )
                legacy_before = relay_state.snapshot_count()
                legacy_environment = {
                    **os.environ,
                    "HERMES_HOME": str(legacy_home),
                }
                legacy_version = subprocess.run(
                    [str(args.legacy_hermes), "--version"],
                    env=legacy_environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=20,
                    check=False,
                )
                legacy_help = subprocess.run(
                    [str(args.legacy_hermes), "--help"],
                    env=legacy_environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=20,
                    check=False,
                )
                legacy_cli = _run_cli(
                    args.legacy_hermes,
                    project_root,
                    legacy_home,
                    "Reply exactly LEGACY_OK.",
                )
                _stop_process(mentat)
                mentat_log.close()
                mentat = None
                mentat_log = None
                mentat, mentat_log = _start_mentat(
                    project_root,
                    data_dir,
                    legacy_home,
                    vault,
                    mentat_port,
                    None,
                    log_path,
                )
                legacy_sessions_status, _legacy_sessions = _http_json(
                    f"http://127.0.0.1:{mentat_port}/api/hermes/sessions"
                )
                evidence["legacy_019_quiet_fallback"] = (
                    legacy_version.returncode == 0
                    and b"v0.19.0" in legacy_version.stdout
                    and legacy_help.returncode == 0
                    and legacy_cli.returncode == 0
                    and relay_state.snapshot_count() == legacy_before
                    and legacy_sessions_status == 200
                    and disabled_health.get("state") == "off"
                )
                _stop_process(mentat)
                mentat_log.close()
                mentat = None
                mentat_log = None
                mentat, mentat_log = _start_mentat(
                    project_root,
                    data_dir,
                    home,
                    vault,
                    mentat_port,
                    None,
                    log_path,
                )

            # Rollback removes the operator-owned target. No delivery reaches
            # the relay, while authoritative reads and reconciliation remain
            # live independently of webhook delivery.
            _write_hermes_config(
                home,
                relay_server.server_port,
                model_server.server_port,
                gateway_port,
                api_key,
                target=False,
            )
            rollback_before = relay_state.snapshot_count()
            rollback = _run_stock_dispatch(
                python, source, home, ("on_session_start",)
            )
            rollback_health = _wait_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/webhooks/health"
            )
            rollback_sessions_status, _rollback_sessions = _http_json(
                f"http://127.0.0.1:{mentat_port}/api/hermes/sessions"
            )
            rollback_agents_status, _rollback_agents = _http_json(
                f"http://127.0.0.1:{mentat_port}/api/agents"
            )
            rollback_refresh_status, rollback_refresh = _http_json(
                f"http://127.0.0.1:{mentat_port}/api/tasks/delegations/refresh-home",
                method="POST",
                payload={},
            )
            evidence["rollback_quiet_and_readable"] = (
                rollback.returncode == 0
                and relay_state.snapshot_count() == rollback_before
                and rollback_health.get("state") == "off"
                and rollback_sessions_status == 200
                and rollback_agents_status == 200
                and rollback_refresh_status == 200
                and rollback_refresh.get("ok") is True
            )

            diagnostics = _wait_json(f"http://127.0.0.1:{mentat_port}/api/health")
            public_payload = json.dumps(
                {"webhooks": rollback_health, "diagnostics": diagnostics},
                sort_keys=True,
            ).encode()
            observable_paths = [data_dir, log_path, gateway_log_path]
            process_outputs = b"".join(
                result.stdout + result.stderr
                for result in (
                    dispatch,
                    retry,
                    cli,
                    duplicate,
                    held_end,
                    reversed_start,
                    dropped,
                    safe,
                    disabled,
                    rollback,
                )
            )
            tracked_diff = subprocess.run(
                ["git", "diff", "HEAD", "--no-ext-diff"],
                cwd=project_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            if tracked_diff.returncode != 0:
                raise RuntimeError("tracked diff scan failed")
            private_canaries = (
                secret.encode(),
                api_key.encode(),
                prompt_canary.encode(),
                path_canary.encode(),
            )
            evidence["private_canaries_absent"] = (
                _scan_for_canaries(
                    observable_paths,
                    private_canaries,
                )
                and not any(canary in public_payload for canary in private_canaries)
                and not any(canary in process_outputs for canary in private_canaries)
                and not any(
                    canary in tracked_diff.stdout for canary in private_canaries
                )
            )
            evidence["pre_restart_acceptance_observed"] = before_restart >= 5
        finally:
            _stop_process(gateway)
            if gateway_log is not None:
                gateway_log.close()
            _stop_process(mentat)
            if mentat_log is not None:
                mentat_log.close()
            _stop_http(relay_server, relay_thread)
            _stop_http(model_server, model_thread)

    evidence["passed"] = all(
        value is True
        for key, value in evidence.items()
        if key not in {"schema_version", "observations"}
    )
    print(json.dumps(evidence, sort_keys=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
