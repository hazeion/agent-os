#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import server


@dataclass(frozen=True)
class Listener:
    pid: int
    port: int
    local_address: str
    raw: str


def lifecycle_state_path(config: server.AppConfig) -> Path:
    return config.data_dir / "runtime" / "server-state.json"


def managed_ports(primary_port: int) -> list[int]:
    return sorted({int(primary_port), 8888, 8890})


def parse_netstat_listeners(output: str) -> list[Listener]:
    listeners: list[Listener] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or "LISTENING" not in line:
            continue
        parts = raw_line.split()
        if len(parts) < 5:
            continue
        local_address = parts[1]
        state = parts[3].upper()
        pid_text = parts[4]
        if state != "LISTENING":
            continue
        try:
            port = int(local_address.rsplit(":", 1)[1])
            pid = int(pid_text)
        except (IndexError, ValueError):
            continue
        listeners.append(Listener(pid=pid, port=port, local_address=local_address, raw=raw_line.rstrip()))
    return listeners


def netstat_listeners() -> list[Listener]:
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    return parse_netstat_listeners(result.stdout)


def read_runtime_state(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def remove_runtime_state(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def looks_like_agent_os_overview(payload) -> bool:
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("cards"), dict)
        and isinstance(payload.get("identity"), dict)
        and isinstance(payload.get("generated_at"), str)
    )


def probe_agent_os(port: int, timeout: float = 0.6) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/overview", timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False
    return looks_like_agent_os_overview(payload)


def process_commandline(pid: int) -> str:
    commands = [
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\"; if ($p) {{ $p.CommandLine }}",
        ],
        ["wmic", "process", "where", f"processid={pid}", "get", "CommandLine", "/value"],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        output = (result.stdout or "").strip()
        if not output:
            continue
        if output.startswith("CommandLine="):
            output = output.partition("=")[2].strip()
        return output
    return ""


def looks_like_agent_os_commandline(commandline: str) -> bool:
    text = (commandline or "").strip().lower()
    if not text:
        return False
    return "server.py" in text or "agent_os_lifecycle.py" in text or "agent-os" in text


def identify_listener(listener: Listener, state_pid: int | None, probe_cache: dict[int, bool], command_cache: dict[int, str]) -> tuple[bool, list[str], str]:
    reasons: list[str] = []
    if state_pid is not None and listener.pid == state_pid:
        reasons.append("matches_runtime_state")

    commandline = command_cache.setdefault(listener.pid, process_commandline(listener.pid))
    if looks_like_agent_os_commandline(commandline):
        reasons.append("command_line")

    if listener.port not in probe_cache:
        probe_cache[listener.port] = probe_agent_os(listener.port)
    if probe_cache[listener.port]:
        reasons.append("overview_probe")

    return bool(reasons), reasons, commandline


def kill_pid(pid: int) -> tuple[bool, str]:
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    message = (result.stdout or result.stderr or "").strip() or f"taskkill exit code {result.returncode}"
    return result.returncode == 0, message


def cleanup_agent_os_listeners(config: server.AppConfig, *, stop_only: bool = False) -> dict:
    state_path = lifecycle_state_path(config)
    state = read_runtime_state(state_path) or {}
    state_pid = state.get("pid") if isinstance(state.get("pid"), int) else None
    ports = managed_ports(config.port)
    listeners = [listener for listener in netstat_listeners() if listener.port in ports]
    actions: list[dict] = []
    killed_pids: set[int] = set()
    blocked = False
    probe_cache: dict[int, bool] = {}
    command_cache: dict[int, str] = {}

    for listener in sorted(listeners, key=lambda item: (item.port, item.pid)):
        is_agent_os, reasons, commandline = identify_listener(listener, state_pid, probe_cache, command_cache)
        if is_agent_os:
            if listener.pid in killed_pids:
                actions.append(
                    {
                        "port": listener.port,
                        "pid": listener.pid,
                        "action": "already_killed",
                        "reasons": reasons,
                        "command_line": commandline,
                    }
                )
                continue
            ok, message = kill_pid(listener.pid)
            actions.append(
                {
                    "port": listener.port,
                    "pid": listener.pid,
                    "action": "killed" if ok else "kill_failed",
                    "reasons": reasons,
                    "command_line": commandline,
                    "message": message,
                }
            )
            if ok:
                killed_pids.add(listener.pid)
            else:
                blocked = True
            continue

        action = "ignored_non_agent_os"
        if listener.port == config.port and not stop_only:
            action = "blocked_non_agent_os"
            blocked = True
        actions.append(
            {
                "port": listener.port,
                "pid": listener.pid,
                "action": action,
                "reasons": reasons,
                "command_line": commandline,
            }
        )

    if state_path.exists() and (state_pid is None or state_pid in killed_pids or not any(listener.pid == state_pid for listener in listeners)):
        remove_runtime_state(state_path)
        actions.append({"action": "cleared_runtime_state", "path": str(state_path), "state_pid": state_pid})

    if not listeners and state_path.exists():
        remove_runtime_state(state_path)
        actions.append({"action": "cleared_runtime_state", "path": str(state_path), "state_pid": state_pid})

    if not listeners and not actions:
        actions.append({"action": "no_managed_listeners", "ports": ports})

    return {
        "ok": not blocked,
        "config_port": config.port,
        "managed_ports": ports,
        "state_path": str(state_path),
        "actions": actions,
    }


def status_report(config: server.AppConfig) -> dict:
    state_path = lifecycle_state_path(config)
    listeners = [listener for listener in netstat_listeners() if listener.port in managed_ports(config.port)]
    probe_cache: dict[int, bool] = {}
    command_cache: dict[int, str] = {}
    state = read_runtime_state(state_path) or {}
    state_pid = state.get("pid") if isinstance(state.get("pid"), int) else None
    items = []
    for listener in sorted(listeners, key=lambda item: (item.port, item.pid)):
        is_agent_os, reasons, commandline = identify_listener(listener, state_pid, probe_cache, command_cache)
        items.append(
            {
                "port": listener.port,
                "pid": listener.pid,
                "local_address": listener.local_address,
                "is_agent_os": is_agent_os,
                "reasons": reasons,
                "command_line": commandline,
            }
        )
    return {
        "config_port": config.port,
        "managed_ports": managed_ports(config.port),
        "state_path": str(state_path),
        "runtime_state": state,
        "listeners": items,
    }


def load_runtime_config(server_args: list[str]) -> server.AppConfig:
    cli_args = server.parse_cli_args(server_args)
    return server.load_app_config(cli_args)


def print_report(report: dict) -> None:
    print(json.dumps(report, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent OS local server lifecycle helper.")
    parser.add_argument("command", choices=["preflight", "stop", "status"])
    parser.add_argument("server_args", nargs=argparse.REMAINDER, help="Arguments forwarded to server.py config parsing.")
    args = parser.parse_args(argv)

    server_args = list(args.server_args or [])
    if server_args and server_args[0] == "--":
        server_args = server_args[1:]
    config = load_runtime_config(server_args)

    if args.command == "status":
        print_report(status_report(config))
        return 0

    if args.command == "stop":
        report = cleanup_agent_os_listeners(config, stop_only=True)
        print_report(report)
        return 0 if report.get("ok", True) else 1

    report = cleanup_agent_os_listeners(config, stop_only=False)
    print_report(report)
    return 0 if report.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
