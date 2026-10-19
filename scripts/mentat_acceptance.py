#!/usr/bin/env python3
"""Exercise a disposable source-checkout release without owner state or credentials."""
from __future__ import annotations

import argparse
import errno
import json
import math
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



BROWSER_CHECKS = frozenset({"document_complete", "shell_hydrated", "shell_runtime_ready", "bridge_ready",
                            "workspace_exists", "heading_correct", "viewport_correct", "project_selected", "project_visible",
                            "task_visible", "no_js_exceptions"})


def browser_helper_path() -> Path:
    path = REPO / "scripts" / "mentat_acceptance_browser.mjs"
    require(path.is_file() and not path.is_symlink(), "browser_helper_missing")
    return path


def browser_listener_owned(browser: subprocess.Popen, port: int, environment: dict[str, str]) -> bool:
    """Inspect only the allocated loopback debug port; never control its owner."""
    executable = shutil.which("lsof", path=environment.get("PATH"))
    require(executable is not None, "browser_inventory_unavailable")
    if browser.poll() is not None:
        return False
    result = subprocess.run([executable, "-nP", "-a", "-iTCP:" + str(port), "-sTCP:LISTEN", "-Fpn"],
                            env=environment, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=1, check=False)
    if result.returncode != 0 or len(result.stdout) > 4096:
        return False
    current = None
    listeners = []
    for line in result.stdout.splitlines():
        if line.startswith(b"p") and line[1:].isdigit():
            current = int(line[1:])
        elif line.startswith(b"n"):
            if current is None or line[1:] != f"127.0.0.1:{port}".encode():
                return False
            listeners.append(current)
    try:
        return bool(listeners) and browser.poll() is None and all(os.getpgid(pid) == browser.pid for pid in listeners)
    except (ProcessLookupError, PermissionError):
        return False


def listener_closed(port: int, *, timeout: float = 0.2) -> bool:
    with socket.socket() as connection:
        connection.settimeout(timeout)
        return connection.connect_ex(("127.0.0.1", port)) == errno.ECONNREFUSED


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


BROWSER_TRANSPORT_COUNTS = frozenset({"sent_requests", "text_frames", "invalid_frames", "matched_responses"})
BROWSER_TRANSPORT_FLAGS = frozenset({"socket_closed", "socket_error", "counters_saturated"})


BROWSER_STAGES = frozenset({"discovery", "connect", "runtime", "page", "focus", "viewport", "navigation", "evaluation", "ready"})


BROWSER_DIAGNOSTICS = frozenset({"project_exists", "project_text_matches", "project_renderable", "project_intersects_viewport",
                                 "task_exists", "task_text_matches", "task_renderable", "task_intersects_viewport"})


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
        self.browser_helper: subprocess.Popen | None = None
        self.browser_debug_port: int | None = None
        self.browser_cleanup_deadline: float | None = None
        self.browser_stop_requested: set[int] = set()
        self.browser_checks: dict[str, bool] = {}
        self.browser_diagnostics: dict[str, bool] = {}
        self.browser_observation: dict = {}
        self.browser_stage: str | None = None
        self.browser_helper_code: str | None = None
        self.browser_transport: dict = {}
        self.browser_closure_proof: tuple | None = None
        self.cleanup_observations: dict[str, bool] = {}
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

    def begin_browser_cleanup(self) -> float:
        if self.browser_cleanup_deadline is None:
            self.browser_cleanup_deadline = time.monotonic() + 15
        for process in (self.browser, self.browser_helper):
            if process is not None and process.pid not in self.browser_stop_requested and process.poll() is None:
                self.browser_stop_requested.add(process.pid)
                process.terminate()
        return self.browser_cleanup_deadline

    def browser_quiescence(self, deadline: float) -> tuple[bool, bool, bool]:
        proof = self.browser_closure_proof
        handles_terminal = lambda: all(process is None or process.poll() is not None
                                       for process in (self.browser, self.browser_helper))
        if (proof is not None and proof[0] is self.browser and proof[1] is self.browser_helper
                and proof[2] == self.browser_debug_port and handles_terminal()):
            return True, True, True
        while True:
            try:
                browser_absent = self.browser is None or process_group_absent(self.browser.pid)
            except OSError:
                browser_absent = False
            try:
                helper_absent = self.browser_helper is None or process_group_absent(self.browser_helper.pid)
            except OSError:
                helper_absent = False
            remaining = deadline - time.monotonic()
            try:
                debug_closed = self.browser_debug_port is None or (remaining > 0 and listener_closed(self.browser_debug_port, timeout=min(0.2, remaining)))
            except OSError:
                debug_closed = False
            if self.browser_debug_port is not None and time.monotonic() > deadline:
                debug_closed = False
            if browser_absent and helper_absent and debug_closed:
                if handles_terminal():
                    self.browser_closure_proof = (self.browser, self.browser_helper, self.browser_debug_port)
                return browser_absent, helper_absent, debug_closed
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return browser_absent, helper_absent, debug_closed
            time.sleep(min(0.05, remaining))

    def capture_browser_evidence(self, output, *, require_final: bool) -> dict | None:
        # Positional reads never move the stdout descriptor shared with the child.
        raw = os.pread(output.fileno(), 16385, 0)
        require(len(raw) <= 16384, "browser_output_limit")
        lines = raw.split(b"\n")
        tail = lines.pop()
        require(not require_final or not tail, "browser_output_invalid")
        require(len(lines) <= 17, "browser_output_limit")
        def unique_members(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate_member")
                value[key] = item
            return value
        final = None
        progress_count = progress_bytes = 0
        latest = None
        diagnostics = None
        observation = None
        stage = None
        transport = None
        for line in lines:
            try:
                value = json.loads(line, object_pairs_hook=unique_members)
            except (ValueError, UnicodeError):
                raise AcceptanceFailure("browser_output_invalid") from None
            require(isinstance(value, dict) and final is None
                    and type(value.get("schema_version")) is int and value["schema_version"] == 1
                    and isinstance(value.get("checks"), dict) and set(value["checks"]) == BROWSER_CHECKS
                    and all(type(check) is bool for check in value["checks"].values())
                    and isinstance(value.get("diagnostics"), dict) and set(value["diagnostics"]) == BROWSER_DIAGNOSTICS
                    and all(type(item) is bool for item in value["diagnostics"].values()), "browser_output_invalid")
            require(isinstance(value.get("stage"), str) and value["stage"] in BROWSER_STAGES, "browser_output_invalid")
            transported = value.get("transport")
            require(isinstance(transported, dict) and set(transported) == BROWSER_TRANSPORT_COUNTS | BROWSER_TRANSPORT_FLAGS | {"pending_calls", "close_code"}
                    and all(type(transported[key]) is int and 0 <= transported[key] <= 4096 for key in BROWSER_TRANSPORT_COUNTS)
                    and all(type(transported[key]) is bool for key in BROWSER_TRANSPORT_FLAGS)
                    and type(transported["pending_calls"]) is int and 0 <= transported["pending_calls"] <= 1
                    and type(transported["close_code"]) is int and 0 <= transported["close_code"] <= 65535, "browser_output_invalid")
            observed = value.get("observation")
            require(isinstance(observed, dict) and set(observed) == {"ready_state", "location_category", "snapshots", "observer_elapsed_ms"}
                    and isinstance(observed["ready_state"], str) and observed["ready_state"] in {"unknown", "loading", "interactive", "complete", "other"}
                    and isinstance(observed["location_category"], str) and observed["location_category"] in {"unknown", "tasks", "blank", "browser_error", "auth", "other"}
                    and type(observed["snapshots"]) is int and 0 <= observed["snapshots"] <= 512
                    and type(observed["observer_elapsed_ms"]) is int and 0 <= observed["observer_elapsed_ms"] <= 40000, "browser_output_invalid")
            if "event" in value:
                progress_count += 1
                progress_bytes += len(line) + 1
                require(progress_count <= 16 and progress_bytes <= 12288, "browser_output_limit")
                require(set(value) == {"schema_version", "event", "stage", "checks", "diagnostics", "observation", "transport"}
                        and value["event"] == "progress", "browser_output_invalid")
            else:
                require(len(line) + 1 <= 4096, "browser_output_limit")
                require(set(value) == {"schema_version", "ready", "code", "stage", "checks", "diagnostics", "observation", "transport"}
                        and type(value["ready"]) is bool and isinstance(value["code"], str)
                        and value["code"] in {"ready", "browser_readiness_timeout", "browser_protocol_failed", "browser_protocol_timeout", "browser_transport_closed", "browser_transport_error",
                                             "browser_readiness_invalid", "browser_js_exception", "browser_configuration_invalid", "browser_navigation_failed", "browser_target_ambiguous"},
                        "browser_output_invalid")
                final = value
            latest = dict(value["checks"])
            diagnostics = dict(value["diagnostics"])
            observation = dict(observed)
            stage = value["stage"]
            transport = dict(transported)
        require(not require_final or final is not None, "browser_final_evidence_missing")
        if latest is not None:
            self.browser_checks = latest
            self.browser_diagnostics = diagnostics
            self.browser_observation = observation
            self.browser_stage = stage
            self.browser_transport = transport
            if final is not None:
                self.browser_helper_code = final["code"]
        return final

    def render_browser(self, chrome: Path, project_id: str, task_id: str) -> None:
        require(self.browser is None and self.browser_helper is None, "browser_already_started")
        require(re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", project_id)
                and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", task_id), "browser_target_invalid")
        helper = browser_helper_path()
        node = shutil.which("node", path=self.environment.get("PATH"))
        require(node is not None, "browser_node_unavailable")
        self.browser_debug_port = free_port()
        started = time.monotonic()
        deadline = started + 40
        self.browser = subprocess.Popen([
            str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
            "--disable-background-networking", "--window-size=1440,1000",
            "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={self.browser_debug_port}",
            "--user-data-dir=" + str(self.root / "browser-profile"), "about:blank",
        ], env=self.environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        owned = False
        while self.browser.poll() is None and time.monotonic() < deadline - 1:
            if browser_listener_owned(self.browser, self.browser_debug_port, self.environment):
                owned = True
                break
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))
        require(owned, "browser_debug_ownership_unverified")
        offset = math.ceil((time.monotonic() - started) * 1000)
        require(0 <= offset < 40000, "browser_readiness_timeout")
        configuration = {"origin": self.origin, "debug_port": self.browser_debug_port,
                         "project_id": project_id, "task_id": task_id,
                         "elapsed_offset_ms": offset, "remaining_ms": 40000 - offset}
        with tempfile.TemporaryFile() as output:
            # Retain the exact handle immediately, including stdin/startup failures.
            self.browser_helper = subprocess.Popen([node, str(helper)], cwd=REPO, env=self.environment,
                                                   stdin=subprocess.PIPE, stdout=output, stderr=subprocess.DEVNULL,
                                                   start_new_session=True)
            self.browser_helper.stdin.write(json.dumps(configuration).encode())
            self.browser_helper.stdin.close()
            try:
                self.browser_helper.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    self.capture_browser_evidence(output, require_final=False)
                except (AcceptanceFailure, OSError):
                    pass  # Unavailable or malformed diagnostics never replace the authoritative wall timeout.
                raise AcceptanceFailure("browser_readiness_timeout") from None
            require(process_group_absent(self.browser_helper.pid), "browser_helper_child_remains")
            result = self.capture_browser_evidence(output, require_final=True)
            require(time.monotonic() <= deadline, "browser_readiness_timeout")
        require(result["ready"] is True and result["code"] == "ready" and result["stage"] == "ready"
                and all(self.browser_checks.values()) and self.browser_helper.returncode == 0,
                "browser_readiness_failed")
        require(self.browser.poll() is None, "browser_exited_before_owned_stop")
        cleanup_deadline = self.begin_browser_cleanup()
        try:
            self.browser.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise AcceptanceFailure("browser_stop_timeout") from None
        require(self.browser.returncode in {0, -signal.SIGTERM, 128 + signal.SIGTERM}, "browser_stop_failed")
        require(all(self.browser_quiescence(cleanup_deadline)), "browser_cleanup_incomplete")

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
            self.render_browser(chrome, project_id, task_id)
            self.completed.append("isolated_browser_render")
        self.phase = "offline_backup"
        self.stop()
        backup = self.cli("backup")
        require(backup.get("status") in {"created", "existing"}, "backup_failed")
        name = backup.get("backup_name")
        require(isinstance(name, str) and re.fullmatch(r"mentat-backup-v5-[0-9a-f]{24}\.zip", name), "backup_name")
        preview = self.cli("restore", [str(self.data / "backups" / name)])
        require(preview.get("status") in {"ready", "not_required"} and not preview.get("issues"),
                "backup_preview_failed")
        self.completed.append("offline_backup_validated_by_restore_preview")
        require(not any((self.root / "hermes").iterdir()), "hermes_directory_changed")
        return {"ok": True, "scenarios": self.completed, "runs_dispatched": False,
                "restore_confirmed": False, "live_remote_acceptance": False,
                "immediate_restart_acceptance": not diagnostic_port_wait}

    def cleanup(self) -> bool:
        browser_terminal = True
        helper_terminal = True
        browser_group_absent = True
        helper_group_absent = True
        launcher_terminal = True
        # Preserve the original window if a positive-path stop already timed out.
        browser_deadline = self.begin_browser_cleanup()
        for process in (self.browser, self.browser_helper):
            if process is not None:
                try:
                    process.wait(timeout=max(0, browser_deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    if process is self.browser:
                        browser_terminal = False
                    else:
                        helper_terminal = False
        if self.browser_helper is not None and self.browser_helper.stdin is not None:
            try:
                self.browser_helper.stdin.close()
            except OSError:
                pass
        browser_group_absent, helper_group_absent, debug_closed = self.browser_quiescence(browser_deadline)
        if self.process is not None:
            # Only signal the Popen handle we created, never a discovered PID or listener.
            if self.process.poll() is None:
                self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                launcher_terminal = False
        self.launch_output.close()
        # Evaluate every owned boundary even when another one failed, so the
        # bounded report identifies which exact cleanup proof was unavailable.
        self.cleanup_observations = {
            "browser_terminal": browser_terminal,
            "browser_group_absent": browser_group_absent,
            "browser_helper_terminal": helper_terminal,
            "browser_helper_group_absent": helper_group_absent,
            "browser_debug_listener_closed": debug_closed,
            "launcher_terminal": launcher_terminal,
            "launcher_groups_absent": all(process_group_absent(group) for group in self.launcher_groups),
            "captured_children_absent": all(process_absent(pid) for pid in self.children),
            "listener_closed": listener_closed(self.port),
        }
        return all(self.cleanup_observations.values())


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
    except subprocess.TimeoutExpired:
        report = {"ok": False, "phase": journey.phase if journey else "initialization",
                  "code": "operation_timeout"}
    except (AcceptanceFailure, OSError, ValueError, KeyError, TypeError) as exc:
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
        if journey is not None and journey.cleanup_observations:
            report["cleanup"] = journey.cleanup_observations
        if journey is not None and journey.browser_checks:
            report["browser_checks"] = journey.browser_checks
            report["browser_diagnostics"] = journey.browser_diagnostics
            report["browser_observation"] = journey.browser_observation
            report["browser_stage"] = journey.browser_stage
            report["browser_transport"] = journey.browser_transport
            if journey.browser_helper_code is not None:
                report["browser_helper_code"] = journey.browser_helper_code
        if not cleaned:
            primary_phase = report.get("phase", "complete")
            primary_code = report.get("code", "none")
            report.update(ok=False, code="cleanup_incomplete",
                          primary_phase=primary_phase, primary_code=primary_code)
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
