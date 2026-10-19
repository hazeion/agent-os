#!/usr/bin/env python3
"""Exercise a disposable source-checkout release without owner state or credentials."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

REPO = Path(__file__).resolve().parents[1]
LIMIT = 262144
PROJECT = "Disposable acceptance Project"
TASK = "Disposable acceptance Task"


class AcceptanceFailure(Exception):
    """Only fixed failure codes cross the report boundary."""


def require(condition: object, code: str) -> None:
    if not condition:
        raise AcceptanceFailure(code)


def isolated_environment(root: Path) -> dict[str, str]:
    essentials = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT")
    environment = {key: os.environ[key] for key in essentials if key in os.environ}
    environment.update(HOME=str(root / "home"), USERPROFILE=str(root / "home"),
                       TMPDIR=str(root / "tmp"), TMP=str(root / "tmp"), TEMP=str(root / "tmp"),
                       HERMES_HOME=str(root / "hermes"), OBSIDIAN_VAULT_PATH=str(root / "vault"),
                       PYTHONNOUSERSITE="1", NEXT_TELEMETRY_DISABLED="1")
    return environment


def free_port() -> int:
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return int(connection.getsockname()[1])


def child_pids(parent: int, environment: dict[str, str]) -> tuple[int, ...]:
    result = subprocess.run(["ps", "-ax", "-o", "pid=", "-o", "ppid="], env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
    require(result.returncode == 0 and len(result.stdout) <= 1048576, "process_inventory_failed")
    children = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 2 and all(field.isdigit() for field in fields) and int(fields[1]) == parent:
            children.append(int(fields[0]))
    require(len(children) == 2, "owned_children_unverified")
    return tuple(children)


def process_absent(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def process_group_absent(group: int) -> bool:
    try:
        os.killpg(group, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def listener_closed(port: int) -> bool:
    with socket.socket() as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(("127.0.0.1", port)) != 0


def wait_for_reusable_port(port: int, timeout: float = 75) -> None:
    # Current runtime preflight uses a non-reusing bind. A closed TCP listener
    # may still have TIME_WAIT sockets; do not relaunch or silently change ports.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as connection:
            try:
                connection.bind(("127.0.0.1", port))
                return
            except OSError:
                pass
        time.sleep(0.2)
    raise AcceptanceFailure("restart_port_not_reusable")


class Journey:
    def __init__(self, root: Path):
        self.root = root
        for name in ("home", "tmp", "hermes", "vault"):
            (root / name).mkdir(mode=0o700)
        self.data = root / "data"
        self.port = free_port()
        self.origin = f"http://127.0.0.1:{self.port}"
        self.environment = isolated_environment(root)
        self.config = root / "acceptance.toml"
        self.config.write_text('[server]\nhost = "127.0.0.1"\n' + f"port = {self.port}\n")
        self.options = ["--config", str(self.config), "--host", "127.0.0.1", "--port", str(self.port),
                        "--data-dir", str(self.data), "--hermes-home", str(root / "hermes"),
                        "--obsidian-vault", str(root / "vault")]
        self.process: subprocess.Popen | None = None
        self.children: tuple[int, ...] = ()
        self.launcher_groups: set[int] = set()
        self.browser: subprocess.Popen | None = None
        self.launch_output = tempfile.TemporaryFile()
        self.opener = build_opener(ProxyHandler({}))
        self.phase = "setup"
        self.completed: list[str] = []

    def cli(self, command: str, extra: list[str] | None = None) -> dict:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run([sys.executable, "-m", "mentat.cli", command,
                                     *self.options, *(extra or [])], cwd=REPO,
                                    env=self.environment, stdout=output, stderr=subprocess.DEVNULL,
                                    timeout=60, check=False)
            require(result.returncode == 0, "cli_failed")
            output.seek(0)
            raw = output.read(LIMIT + 1)
        require(len(raw) <= LIMIT, "cli_output_limit")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise AcceptanceFailure("cli_output_invalid") from None
        require(isinstance(value, dict), "cli_output_invalid")
        return value

    def request(self, path: str, body: dict | None = None, *, html: bool = False):
        # Every caller below uses a fixed route or an ID obtained from its exact creation.
        fixed = {"/tasks", "/api/gateway/health", "/api/bridge/health", "/api/projects",
                 "/api/agent-console/planning-overview", "/api/runs"}
        require(path in fixed or re.fullmatch(r"/api/projects/[A-Za-z0-9_.:-]{1,80}/tasks", path)
                or re.fullmatch(r"/api/agent-console/planning-task\?task_id=[A-Za-z0-9_.:-]{1,128}", path),
                "route_invalid")
        headers = {"Origin": self.origin, "Sec-Fetch-Site": "same-origin"}
        data = None if body is None else json.dumps(body).encode()
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(self.origin + path, data=data, headers=headers)
        with self.opener.open(request, timeout=10) as response:
            require(response.status == (201 if body is not None else 200), "http_status")
            raw = response.read(LIMIT + 1)
        require(len(raw) <= LIMIT, "http_output_limit")
        return raw.decode() if html else json.loads(raw)

    def start(self) -> None:
        require(self.process is None, "already_started")
        self.process = subprocess.Popen([sys.executable, "-m", "mentat.cli", "start", *self.options],
                                        cwd=REPO, env=self.environment,
                                        stdout=self.launch_output, stderr=self.launch_output, start_new_session=True)
        # Record the owned group immediately, before any readiness observation.
        # Its absence remains required even if the launcher exits early.
        self.launcher_groups.add(self.process.pid)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            require(self.process.poll() is None, "launcher_exited")
            try:
                gateway = self.request("/api/gateway/health")
                bridge = self.request("/api/bridge/health")
                if gateway.get("status") == "ready" and bridge.get("status") == "ready":
                    self.children = child_pids(self.process.pid, self.environment)
                    status = self.cli("status")
                    require(status.get("config_port") == self.port and status.get("managed_ports") == [self.port], "managed_ports_invalid")
                    require(any(item.get("is_mentat") is True for item in status.get("listeners", [])), "status_unowned")
                    return
            except (URLError, HTTPError, TimeoutError, OSError):
                pass
            time.sleep(0.2)
        raise AcceptanceFailure("readiness_timeout")

    def stop(self) -> None:
        require(self.process is not None, "not_started")
        require(self.process.poll() is None, "launcher_crashed_before_stop")
        require(self.cli("stop").get("ok") is True, "stop_cli_failed")
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            raise AcceptanceFailure("launcher_stop_timeout") from None
        require(self.process.returncode in {0, 128 + signal.SIGTERM}, "launcher_stop_failed")
        require(process_group_absent(self.process.pid), "owned_launcher_group_remains")
        require(all(process_absent(pid) for pid in self.children), "owned_child_remains")
        require(listener_closed(self.port), "listener_remains")
        require(not (self.data / "runtime" / "server-state.json").exists(), "runtime_state_remains")
        self.process = None

    def read_back(self, project_id: str, task_id: str) -> None:
        overview = self.request("/api/agent-console/planning-overview")
        require(any(item.get("id") == project_id and item.get("name") == PROJECT
                    for item in overview.get("projects", [])), "project_readback")
        detail = self.request("/api/agent-console/planning-task?task_id=" + task_id)
        task = detail.get("task", {})
        require(task.get("id") == task_id and task.get("title") == TASK
                and task.get("project_id") == project_id and task.get("assigned_agent_id") is None
                and task.get("status") == "todo" and task.get("priority") == "medium",
                "task_readback")
        require(self.request("/api/runs").get("count") == 0, "unexpected_runs")

    def run(self, chrome: Path | None = None, *, diagnostic_port_wait: bool = False) -> dict:
        require(self.cli("setup").get("ok") is True, "setup_failed")
        self.phase = "start_create"
        self.start()
        require("Projects &amp; Tasks" in self.request("/tasks", html=True)
                or "Projects & Tasks" in self.request("/tasks", html=True), "dashboard_missing")
        project = self.request("/api/projects", {"name": PROJECT})["project"]
        project_id = project["id"]
        require(isinstance(project_id, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", project_id), "project_id")
        task = self.request(f"/api/projects/{project_id}/tasks",
                            {"title": TASK, "assigned_agent_id": None, "due_date": None})["task"]
        task_id = task["id"]
        require(isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", task_id), "task_id")
        self.read_back(project_id, task_id)
        self.completed.append("fresh_setup_gateway_and_creation")
        self.phase = "restart"
        self.stop()
        if diagnostic_port_wait:
            wait_for_reusable_port(self.port)
        self.start()
        self.read_back(project_id, task_id)
        self.completed.append("restart_exact_durability")
        if chrome is not None:
            self.phase = "browser"
            with tempfile.TemporaryFile() as output:
                self.browser = subprocess.Popen([str(chrome), "--headless=new", "--disable-gpu", "--no-first-run",
                                         "--no-default-browser-check", "--disable-background-networking",
                                         "--user-data-dir=" + str(self.root / "browser-profile"),
                                         "--virtual-time-budget=5000", "--dump-dom", self.origin + "/tasks"],
                                        env=self.environment, stdout=output, stderr=subprocess.DEVNULL,
                                        start_new_session=True)
                self.browser.wait(timeout=40)
                require(process_group_absent(self.browser.pid), "browser_child_remains")
                output.seek(0)
                rendered = output.read(LIMIT + 1)
            require(self.browser.returncode == 0 and len(rendered) <= LIMIT
                    and PROJECT.encode() in rendered, "browser_render_failed")
            self.completed.append("isolated_browser_render")
        self.phase = "offline_backup"
        self.stop()
        backup = self.cli("backup")
        require(backup.get("status") in {"created", "existing"}, "backup_failed")
        name = backup.get("backup_name")
        require(isinstance(name, str) and re.fullmatch(r"mentat-backup-v[1-5]-[0-9a-f]{24}\.zip", name), "backup_name")
        preview = self.cli("restore", [str(self.data / "backups" / name)])
        require(preview.get("status") in {"ready", "not_required"} and not preview.get("issues"),
                "backup_preview_failed")
        self.completed.append("offline_backup_validated_by_restore_preview")
        require(not any((self.root / "hermes").iterdir()), "hermes_directory_changed")
        return {"ok": True, "scenarios": self.completed, "runs_dispatched": False,
                "restore_confirmed": False, "live_remote_acceptance": False,
                "immediate_restart_acceptance": not diagnostic_port_wait}

    def cleanup(self) -> bool:
        clean = True
        if self.browser is not None:
            if self.browser.poll() is None:
                self.browser.terminate()
            try:
                self.browser.wait(timeout=15)
            except subprocess.TimeoutExpired:
                clean = False
            if not process_group_absent(self.browser.pid):
                clean = False
        if self.process is not None:
            # Only signal the Popen handle we created, never a discovered PID or listener.
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                clean = False
        self.launch_output.close()
        return (clean and all(process_group_absent(group) for group in self.launcher_groups)
                and all(process_absent(pid) for pid in self.children) and listener_closed(self.port))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", type=Path, help="Optional installed Chrome executable for an isolated rendering check")
    parser.add_argument("--diagnostic-port-wait", action="store_true",
                        help="Observe TIME_WAIT expiry before restart; does not pass immediate restart acceptance")
    args = parser.parse_args(argv)
    root = Path(tempfile.mkdtemp(prefix="mentat-local-acceptance-"))
    journey = None
    report: dict = {"ok": False, "phase": "initialization", "code": "initialization_failed"}
    try:
        require(os.name == "posix", "posix_host_required")
        require(args.chrome is None or args.chrome.is_absolute() and args.chrome.is_file(), "chrome_invalid")
        journey = Journey(root)
        report = journey.run(args.chrome, diagnostic_port_wait=args.diagnostic_port_wait)
    except (AcceptanceFailure, subprocess.TimeoutExpired, OSError, ValueError, KeyError, TypeError) as exc:
        report = {"ok": False, "phase": journey.phase if journey else "initialization",
                  "code": str(exc) if isinstance(exc, AcceptanceFailure) else "operation_failed"}
    finally:
        try:
            cleaned = journey is None or journey.cleanup()
            if cleaned:
                shutil.rmtree(root)
        except (OSError, subprocess.TimeoutExpired):
            cleaned = False
        report["owned_state_removed"] = cleaned
        if not cleaned:
            report.update(ok=False, code="cleanup_incomplete")
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
