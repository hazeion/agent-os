#!/usr/bin/env python
from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

import server

BASE_DIR = Path(__file__).resolve().parent
MENTAT_COMMAND_PATHS = {
    str((BASE_DIR / "server.py").resolve()).lower().replace("\\", "/"),
    str((BASE_DIR / "mentat_lifecycle.py").resolve()).lower().replace("\\", "/"),
}


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
    if os.name == "nt":
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return parse_netstat_listeners(result.stdout)
    return posix_listeners()


def parse_lsof_listeners(output: str) -> list[Listener]:
    listeners: list[Listener] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("COMMAND"):
            continue
        parts = raw_line.split()
        if len(parts) < 3:
            continue
        pid_text = parts[1]
        name_field = parts[-2] if parts[-1] == "(LISTEN)" else parts[-1]
        if ":" not in name_field:
            continue
        try:
            pid = int(pid_text)
            port = int(name_field.rsplit(":", 1)[1].rstrip(")"))
        except ValueError:
            continue
        listeners.append(Listener(pid=pid, port=port, local_address=name_field, raw=raw_line.rstrip()))
    return listeners


def posix_listeners() -> list[Listener]:
    commands = [
        ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"],
        ["ss", "-ltnp"],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        if result.returncode != 0 and not result.stdout:
            continue
        if command[0] == "lsof":
            return parse_lsof_listeners(result.stdout)
        return parse_ss_listeners(result.stdout)
    return []


def parse_ss_listeners(output: str) -> list[Listener]:
    listeners: list[Listener] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("State"):
            continue
        parts = raw_line.split()
        if len(parts) < 6:
            continue
        if parts[0].upper() != "LISTEN":
            continue
        local_address = parts[3]
        process_info = " ".join(parts[5:])
        match = None
        for pattern in [r"pid=(\d+)", r",pid=(\d+),", r'pid=(\d+)']:
            match = re.search(pattern, process_info)
            if match:
                break
        if match is None:
            continue
        try:
            pid = int(match.group(1))
            port = int(local_address.rsplit(":", 1)[1])
        except ValueError:
            continue
        listeners.append(Listener(pid=pid, port=port, local_address=local_address, raw=raw_line.rstrip()))
    return listeners


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


def looks_like_mentat_overview(payload) -> bool:
    return (
        isinstance(payload, dict)
        and isinstance(payload.get("cards"), dict)
        and isinstance(payload.get("identity"), dict)
        and isinstance(payload.get("generated_at"), str)
    )


def normalized_listener_host(local_address: str, port: int | None = None) -> str:
    """Return the address portion of an OS listener endpoint.

    Listener tools disagree about whether IPv6 addresses are bracketed, so
    normalize them before probing and before using them as cache keys.
    """
    endpoint = str(local_address or "").strip()
    if endpoint.startswith("[") and "]" in endpoint:
        host = endpoint[1 : endpoint.index("]")]
    else:
        host = endpoint
        candidate_host, separator, port_text = endpoint.rpartition(":")
        parsed_port = port_text.rstrip(")")
        if separator and parsed_port.isdigit() and (port is None or int(parsed_port) == port):
            host = candidate_host

    host = host.strip().strip("[]").lower()
    if host in {"*", "0.0.0.0"}:
        return "127.0.0.1"
    if host == "::":
        return "::1"
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return host


def probe_mentat(local_address: str, port: int, timeout: float = 0.6) -> bool:
    host = normalized_listener_host(local_address, port)
    display_host = f"[{host.replace('%', '%25')}]" if ":" in host else host
    try:
        with urlopen(f"http://{display_host}:{port}/api/overview", timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False
    return looks_like_mentat_overview(payload)


def process_commandline(pid: int) -> str:
    if os.name != "nt":
        try:
            result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, check=False, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ""
        return (result.stdout or "").strip()

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
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        output = (result.stdout or "").strip()
        if not output:
            continue
        if output.startswith("CommandLine="):
            output = output.partition("=")[2].strip()
        return output
    return ""


def looks_like_mentat_commandline(commandline: str) -> bool:
    text = (commandline or "").strip().lower().replace("\\", "/")
    if not text:
        return False
    return any(
        re.search(rf"(?:^|\s)[\"']?{re.escape(path)}[\"']?(?:$|\s)", text) is not None
        for path in MENTAT_COMMAND_PATHS
    )


def identify_listener(
    listener: Listener,
    state_pid: int | None,
    probe_cache: dict[tuple[str, int], bool],
    command_cache: dict[int, str],
) -> tuple[bool, list[str], str]:
    reasons: list[str] = []
    if state_pid is not None and listener.pid == state_pid:
        reasons.append("matches_runtime_state")

    commandline = command_cache.setdefault(listener.pid, process_commandline(listener.pid))
    command_matches = looks_like_mentat_commandline(commandline)
    if command_matches:
        reasons.append("command_line")

    probe_host = normalized_listener_host(listener.local_address, listener.port)
    probe_key = (probe_host, listener.port)
    if probe_key not in probe_cache:
        probe_cache[probe_key] = probe_mentat(probe_host, listener.port)
    probe_matches = probe_cache[probe_key]
    if probe_matches:
        reasons.append("overview_probe")

    # Runtime state is only a hint: PIDs can be reused after Mentat exits. Never
    # terminate a listener unless the live process or HTTP response independently
    # identifies it as Mentat.
    return command_matches or probe_matches, reasons, commandline


def kill_pid(pid: int) -> tuple[bool, str]:
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        message = (result.stdout or result.stderr or "").strip() or f"taskkill exit code {result.returncode}"
        return result.returncode == 0, message

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True, "process already exited"
    except OSError as exc:
        return False, str(exc)

    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True, "terminated with SIGTERM"
        except OSError as exc:
            return False, str(exc)
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True, "terminated with SIGTERM"
    except OSError as exc:
        return False, str(exc)
    return True, "terminated with SIGKILL"


def cleanup_mentat_listeners(config: server.AppConfig, *, stop_only: bool = False) -> dict:
    state_path = lifecycle_state_path(config)
    state = read_runtime_state(state_path) or {}
    state_pid = state.get("pid") if isinstance(state.get("pid"), int) else None
    ports = managed_ports(config.port)
    listeners = [listener for listener in netstat_listeners() if listener.port in ports]
    actions: list[dict] = []
    killed_pids: set[int] = set()
    blocked = False
    probe_cache: dict[tuple[str, int], bool] = {}
    command_cache: dict[int, str] = {}

    for listener in sorted(listeners, key=lambda item: (item.port, item.pid)):
        is_mentat, reasons, commandline = identify_listener(listener, state_pid, probe_cache, command_cache)
        if is_mentat:
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

        action = "ignored_non_mentat"
        if listener.port == config.port and not stop_only:
            action = "blocked_non_mentat"
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
    probe_cache: dict[tuple[str, int], bool] = {}
    command_cache: dict[int, str] = {}
    state = read_runtime_state(state_path) or {}
    state_pid = state.get("pid") if isinstance(state.get("pid"), int) else None
    items = []
    for listener in sorted(listeners, key=lambda item: (item.port, item.pid)):
        is_mentat, reasons, commandline = identify_listener(listener, state_pid, probe_cache, command_cache)
        items.append(
            {
                "port": listener.port,
                "pid": listener.pid,
                "local_address": listener.local_address,
                "is_mentat": is_mentat,
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


def load_runtime_request(server_args: list[str]) -> tuple[argparse.Namespace, server.AppConfig]:
    cli_args = server.parse_cli_args(server_args)
    return cli_args, server.load_app_config(cli_args)


def load_runtime_config(server_args: list[str]) -> server.AppConfig:
    return load_runtime_request(server_args)[1]


def loopback_host_is_supported(host: str) -> bool:
    return str(host or "").strip().lower() in {"127.0.0.1", "::1", "localhost"}


def print_report(report: dict) -> None:
    print(json.dumps(report, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mentat local server lifecycle helper.")
    parser.add_argument("command", choices=["preflight", "stop", "status"])
    parser.add_argument("server_args", nargs=argparse.REMAINDER, help="Arguments forwarded to server.py config parsing.")
    args = parser.parse_args(argv)

    server_args = list(args.server_args or [])
    if server_args and server_args[0] == "--":
        server_args = server_args[1:]
    server_cli_args, config = load_runtime_request(server_args)

    if args.command == "status":
        print_report(status_report(config))
        return 0

    if args.command == "stop":
        report = cleanup_mentat_listeners(config, stop_only=True)
        print_report(report)
        return 0 if report.get("ok", True) else 1

    # Keep the server's print-only mode side-effect free. The server prints the
    # effective config and exits before its bind-host validation.
    if (
        server_cli_args.print_config
        or server_cli_args.preview_legacy_migration
        or server_cli_args.confirm_legacy_migration
        or server_cli_args.preview_schema_migration
        or server_cli_args.confirm_schema_migration
    ):
        return 0
    if not loopback_host_is_supported(config.host):
        print_report(
            {
                "ok": False,
                "error": "Mentat refuses non-loopback binds until authenticated remote access is implemented.",
                "host": config.host,
            }
        )
        return 2

    startup_error = server.prepare_data_root_for_startup(config)
    if startup_error is not None:
        print_report({"ok": False, "error": startup_error})
        return 2

    report = cleanup_mentat_listeners(config, stop_only=False)
    print_report(report)
    return 0 if report.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
