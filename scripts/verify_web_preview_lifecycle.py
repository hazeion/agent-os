#!/usr/bin/env python3
"""Exercise real sibling-death cleanup for the source Node preview."""

from __future__ import annotations

from http.client import HTTPConnection
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT / "scripts" / "mentat_web_preview.py"
STARTUP_TIMEOUT_SECONDS = 20.0
EXIT_TIMEOUT_SECONDS = 15.0


class LifecycleVerificationError(RuntimeError):
    """Raised when the production preview leaves a sibling process alive."""


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def health_is_ready(port: int) -> bool:
    connection = HTTPConnection("127.0.0.1", port, timeout=0.5)
    try:
        connection.request("GET", "/api/bridge/health")
        response = connection.getresponse()
        body = response.read(4097)
        if response.status != 200 or len(body) > 4096:
            return False
        payload = json.loads(body)
        return payload.get("status") == "ready"
    except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
        return False
    finally:
        connection.close()


def child_processes(parent_pid: int) -> dict[str, int]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,command="],
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    children: dict[str, int] = {}
    for line in result.stdout.splitlines():
        fields = line.strip().split(maxsplit=2)
        if len(fields) != 3:
            continue
        try:
            process_id, process_parent = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        if process_parent != parent_pid:
            continue
        command = fields[2]
        if "-m mentat.local_bridge" in command:
            children["bridge"] = process_id
        elif command.endswith("web/.next/standalone/server.js") or command.startswith(
            "next-server (v"
        ):
            children["node"] = process_id
    return children


def process_exists(process_id: int) -> bool:
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def stop_exact_process(process_id: int) -> None:
    if not process_exists(process_id):
        return
    try:
        os.kill(process_id, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not process_exists(process_id):
            return
        time.sleep(0.05)
    if process_exists(process_id):
        os.kill(process_id, signal.SIGKILL)


def verify_sibling_death(target: str) -> dict[str, object]:
    port = free_loopback_port()
    supervisor = subprocess.Popen(
        [sys.executable, str(PREVIEW), "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    observed_children: dict[str, int] = {}
    try:
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if supervisor.poll() is not None:
                output = supervisor.communicate(timeout=2)[0]
                raise LifecycleVerificationError(
                    f"{target}_startup_failed:{supervisor.returncode}:{output[-500:]}"
                )
            observed_children = child_processes(supervisor.pid)
            if set(observed_children) == {"bridge", "node"} and health_is_ready(port):
                break
            time.sleep(0.1)
        else:
            raise LifecycleVerificationError(f"{target}_startup_timeout")

        os.kill(observed_children[target], signal.SIGTERM)
        try:
            return_code = supervisor.wait(timeout=EXIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired as exc:
            raise LifecycleVerificationError(f"{target}_supervisor_did_not_exit") from exc
        if return_code == 0:
            raise LifecycleVerificationError(f"{target}_death_reported_success")
        remaining = {
            role: process_id
            for role, process_id in observed_children.items()
            if process_exists(process_id)
        }
        if remaining:
            raise LifecycleVerificationError(
                f"{target}_left_child_processes:{','.join(sorted(remaining))}"
            )
        if health_is_ready(port):
            raise LifecycleVerificationError(f"{target}_left_gateway_ready")
        return {
            "target": target,
            "supervisor_exit_nonzero": True,
            "sibling_stopped": True,
            "gateway_stopped": True,
        }
    finally:
        if supervisor.poll() is None:
            supervisor.terminate()
            try:
                supervisor.wait(timeout=5)
            except subprocess.TimeoutExpired:
                supervisor.kill()
                supervisor.wait(timeout=2)
        for process_id in observed_children.values():
            stop_exact_process(process_id)
        if supervisor.stdout is not None:
            supervisor.stdout.close()


def main() -> int:
    if os.name != "posix":
        print("Real sibling-death verification requires a POSIX process inventory.")
        return 2
    results = [verify_sibling_death(target) for target in ("bridge", "node")]
    print(json.dumps({"ok": True, "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (LifecycleVerificationError, OSError, subprocess.SubprocessError) as exc:
        print(f"Node preview lifecycle verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
