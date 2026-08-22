#!/usr/bin/env python3
"""Launch the production Next.js foundation with its private Python bridge."""

from __future__ import annotations

import argparse
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mentat.local_bridge import BRIDGE_TOKEN_ENV, BRIDGE_TOKEN_HEADER


STANDALONE_ROOT = ROOT / "web" / ".next" / "standalone"
STANDALONE_SERVER = STANDALONE_ROOT / "server.js"
GATEWAY_HOST = "127.0.0.1"
DEFAULT_GATEWAY_PORT = 8890
MINIMUM_NODE_VERSION = (24, 19, 0)
NODE_MAJOR = 24
STARTUP_TIMEOUT_SECONDS = 15.0
SHUTDOWN_TIMEOUT_SECONDS = 10.0
NODE_VERSION_PATTERN = re.compile(
    r"^v(\d+)\.(\d+)\.(\d+)(?:\+[0-9A-Za-z.-]+)?$"
)


class PreviewError(RuntimeError):
    """A bounded, operator-safe preview failure."""


def parse_port(value: object) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def parse_node_version(value: str) -> tuple[int, int, int]:
    match = NODE_VERSION_PATTERN.fullmatch(str(value or "").strip())
    if match is None:
        raise PreviewError("node_version_invalid")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def require_node_24(node_path: str) -> tuple[int, int, int]:
    try:
        result = subprocess.run(
            [node_path, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreviewError("node_unavailable") from exc
    if result.returncode != 0:
        raise PreviewError("node_unavailable")
    version = parse_node_version(result.stdout)
    if version[0] != NODE_MAJOR or version < MINIMUM_NODE_VERSION:
        raise PreviewError("node_24_19_required")
    return version


def find_free_bridge_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind((GATEWAY_HOST, 0))
        return int(candidate.getsockname()[1])


def gateway_port_is_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.bind((GATEWAY_HOST, port))
    except OSError:
        return False
    return True


def bridge_command(port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "mentat.local_bridge",
        "--host",
        GATEWAY_HOST,
        "--port",
        str(port),
    ]


def node_command(node_path: str) -> list[str]:
    return [node_path, str(STANDALONE_SERVER)]


def child_environment(
    *,
    token: str,
    bridge_port: int | None = None,
    gateway_port: int | None = None,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment[BRIDGE_TOKEN_ENV] = token
    environment["NEXT_TELEMETRY_DISABLED"] = "1"
    if bridge_port is not None:
        environment["MENTAT_BRIDGE_ORIGIN"] = f"http://{GATEWAY_HOST}:{bridge_port}"
    if gateway_port is not None:
        environment["HOSTNAME"] = GATEWAY_HOST
        environment["PORT"] = str(gateway_port)
    return environment


def wait_for_health(
    *,
    port: int,
    path: str,
    process: subprocess.Popen,
    token: str | None = None,
    timeout: float = STARTUP_TIMEOUT_SECONDS,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise PreviewError("preview_process_exited_during_startup")
        connection = HTTPConnection(GATEWAY_HOST, port, timeout=0.5)
        headers = {"Accept": "application/json", "Host": f"{GATEWAY_HOST}:{port}"}
        if token is not None:
            headers[BRIDGE_TOKEN_HEADER] = token
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            body = response.read(8193)
            if response.status == 200 and len(body) <= 8192:
                payload = json.loads(body)
                if isinstance(payload, dict) and payload.get("status") == "ready":
                    return payload
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            pass
        finally:
            connection.close()
        time.sleep(0.1)
    raise PreviewError("preview_readiness_timeout")


def stop_process(process: subprocess.Popen | None, timeout: float = SHUTDOWN_TIMEOUT_SECONDS) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    except OSError:
        return


def stop_preview_processes(
    node_process: subprocess.Popen | None,
    bridge_process: subprocess.Popen | None,
) -> None:
    # Withdraw the browser gateway first so no new work reaches the bridge.
    stop_process(node_process)
    stop_process(bridge_process)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=parse_port, default=DEFAULT_GATEWAY_PORT)
    return parser.parse_args(argv)


def run_preview(port: int) -> int:
    node_path = shutil.which("node")
    if node_path is None:
        raise PreviewError("node_unavailable")
    require_node_24(node_path)
    if not STANDALONE_SERVER.is_file():
        raise PreviewError("standalone_build_missing")
    if not gateway_port_is_available(port):
        raise PreviewError("gateway_port_unavailable")

    token = secrets.token_urlsafe(32)
    bridge_port = find_free_bridge_port()
    bridge_process: subprocess.Popen | None = None
    node_process: subprocess.Popen | None = None
    stop_requested = False

    def request_stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    previous_handlers: dict[int, object] = {}
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_handlers[signum] = signal.signal(signum, request_stop)
        except (OSError, ValueError):
            continue

    try:
        bridge_process = subprocess.Popen(
            bridge_command(bridge_port),
            cwd=ROOT,
            env=child_environment(token=token),
        )
        wait_for_health(
            port=bridge_port,
            path="/bridge/v1/health",
            process=bridge_process,
            token=token,
        )

        node_process = subprocess.Popen(
            node_command(node_path),
            cwd=STANDALONE_ROOT,
            env=child_environment(
                token=token,
                bridge_port=bridge_port,
                gateway_port=port,
            ),
        )
        wait_for_health(
            port=port,
            path="/api/bridge/health",
            process=node_process,
        )
        print(f"Mentat Node preview ready at http://{GATEWAY_HOST}:{port}", flush=True)
        print("Press Ctrl+C to stop both preview processes.", flush=True)

        while not stop_requested:
            bridge_return = bridge_process.poll()
            node_return = node_process.poll()
            if bridge_return is not None:
                raise PreviewError("bridge_process_stopped")
            if node_return is not None:
                return int(node_return or 1)
            time.sleep(0.2)
        return 0
    finally:
        stop_preview_processes(node_process, bridge_process)
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_preview(args.port)
    except PreviewError as exc:
        print(f"Mentat Node preview could not start: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
