"""Supervise Mentat's production Node gateway and private Python bridge."""

from __future__ import annotations

import argparse
from http.client import HTTPConnection
from io import BufferedReader
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import threading
import webbrowser

try:
    import resource
except ImportError:  # pragma: no cover - unavailable on Windows
    resource = None

from json_store import write_json_atomic
from private_state import PrivateStateError, release_mentat_server, reserve_mentat_server
from private_state import history_path as private_history_path
from project_repository import ProjectRepositoryError, ensure_project_sqlite_authority
from run_repository import RunRepositoryError, ensure_run_sqlite_authority
from task_repository import TaskRepositoryError, ensure_task_sqlite_authority
from .local_bridge import BRIDGE_TOKEN_ENV, BRIDGE_TOKEN_HEADER
from .process_identity import IS_LINUX, linux_process_start_ticks


SOURCE_ROOT = Path(__file__).resolve().parent.parent
GATEWAY_HOST = "127.0.0.1"
MINIMUM_NODE_VERSION = (24, 19, 0)
NODE_MAJOR = 24
STARTUP_TIMEOUT_SECONDS = 15.0
SHUTDOWN_TIMEOUT_SECONDS = 10.0
STARTUP_LOG_MAXIMUM_BYTES = 8192
STARTUP_LOG_RETAINED_FILES = 3
NODE_VERSION_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:\+[0-9A-Za-z.-]+)?$")


class WebRuntimeError(RuntimeError):
    """A bounded, operator-safe gateway startup failure."""


def application_root() -> Path:
    """Return the source root or the PyInstaller resource root."""

    if bool(getattr(sys, "frozen", False)) and sys.platform == "darwin":
        resource_root = Path(sys.executable).resolve().parent.parent / "Resources"
        if resource_root.is_dir() and not resource_root.is_symlink():
            return resource_root
    frozen_root = getattr(sys, "_MEIPASS", None)
    return Path(frozen_root) if frozen_root else SOURCE_ROOT


def default_standalone_root() -> Path:
    root = application_root()
    if getattr(sys, "frozen", False):
        return root / "web"
    source_build = root / "web" / ".next" / "standalone"
    if (source_build / "server.js").is_file():
        return source_build
    return Path(sys.prefix) / "share" / "mentat" / "web"


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
        raise WebRuntimeError("node_version_invalid")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def require_node_24(node_path: str) -> tuple[int, int, int]:
    try:
        result = subprocess.run(
            [node_path, "--version"], capture_output=True, check=False, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WebRuntimeError("node_unavailable") from exc
    if result.returncode != 0:
        raise WebRuntimeError("node_unavailable")
    version = parse_node_version(result.stdout)
    if version[0] != NODE_MAJOR or version < MINIMUM_NODE_VERSION:
        raise WebRuntimeError("node_24_19_required")
    return version


def find_node_24() -> str | None:
    """Find a locally installed Node runtime when a GUI launcher has a sparse PATH."""

    candidates = [shutil.which("node")]
    if sys.platform == "darwin":
        candidates.extend(
            [
                "/opt/homebrew/bin/node",
                "/usr/local/bin/node",
                "/Applications/Node.app/Contents/MacOS/node",
            ]
        )
    elif os.name == "nt":
        for variable in ("ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.append(str(Path(root) / "nodejs" / "node.exe"))
        candidates.append(r"C:\Program Files\nodejs\node.exe")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def find_free_bridge_port(host: str = GATEWAY_HOST) -> int:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as candidate:
        candidate.bind((host, 0))
        return int(candidate.getsockname()[1])


def gateway_port_is_available(port: int, host: str = GATEWAY_HOST) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as candidate:
            candidate.bind((host, port))
    except OSError:
        return False
    return True


def bridge_command(port: int, host: str = GATEWAY_HOST) -> list[str]:
    if bool(getattr(sys, "frozen", False)):
        executable = Path(sys.executable)
        if sys.platform == "darwin":
            companion = application_root().parent / "MacOS" / "mentat-bridge"
            if not companion.is_file() or companion.is_symlink():
                raise WebRuntimeError("bridge_companion_missing")
            executable = companion
        return [str(executable), "--mentat-private-bridge", "--host", host, "--port", str(port)]
    return [sys.executable, "-m", "mentat.local_bridge", "--host", host, "--port", str(port)]


def node_command(node_path: str, standalone_root: Path) -> list[str]:
    if bool(getattr(sys, "frozen", False)) and sys.platform == "darwin":
        companion = application_root().parent / "MacOS" / "mentat-node-gateway"
        if not companion.is_file() or companion.is_symlink():
            raise WebRuntimeError("node_gateway_companion_missing")
        return [str(companion), "--mentat-node-gateway", node_path, str(standalone_root / "server.js")]
    return [node_path, str(standalone_root / "server.js")]


def node_output_options(startup_log) -> dict:
    """Keep macOS Node output off a pipe while enforcing the private log cap."""

    if (
        bool(getattr(sys, "frozen", False))
        and sys.platform == "darwin"
        and resource is not None
    ):
        def limit_output_file() -> None:
            resource.setrlimit(resource.RLIMIT_FSIZE, (STARTUP_LOG_MAXIMUM_BYTES, STARTUP_LOG_MAXIMUM_BYTES))
        return {"stdout": startup_log, "stderr": subprocess.STDOUT, "preexec_fn": limit_output_file}
    return {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}


def child_environment(
    *, token: str, bridge_port: int | None = None, gateway_port: int | None = None,
    gateway_host: str = GATEWAY_HOST, runtime_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    environment = os.environ.copy()
    if runtime_environment:
        environment.update(runtime_environment)
    environment[BRIDGE_TOKEN_ENV] = token
    environment["NEXT_TELEMETRY_DISABLED"] = "1"
    if bridge_port is not None:
        host = f"[{gateway_host}]" if ":" in gateway_host else gateway_host
        environment["MENTAT_BRIDGE_ORIGIN"] = f"http://{host}:{bridge_port}"
    if gateway_port is not None:
        environment["HOSTNAME"] = gateway_host
        environment["PORT"] = str(gateway_port)
    return environment


def node_environment(*, token: str, bridge_port: int, gateway_port: int, gateway_host: str) -> dict[str, str]:
    """Give Node only its fixed bridge capability and process essentials."""

    environment = {
        name: os.environ[name]
        for name in (
            "PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT",
            "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA",
        )
        if os.environ.get(name)
    }
    display_host = f"[{gateway_host}]" if ":" in gateway_host else gateway_host
    environment.update(
        {
            BRIDGE_TOKEN_ENV: token,
            "MENTAT_BRIDGE_ORIGIN": f"http://{display_host}:{bridge_port}",
            "HOSTNAME": gateway_host,
            "PORT": str(gateway_port),
            "NEXT_TELEMETRY_DISABLED": "1",
            "NODE_ENV": "production",
        }
    )
    return environment


def wait_for_health(*, port: int, path: str, process: subprocess.Popen, host: str = GATEWAY_HOST,
                    token: str | None = None, timeout: float = STARTUP_TIMEOUT_SECONDS,
                    unavailable_error: str | None = None,
                    timeout_error: str = "gateway_readiness_timeout",
                    required_process: subprocess.Popen | None = None) -> dict:
    deadline = time.monotonic() + timeout
    last_response_status: int | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise WebRuntimeError("gateway_process_exited_during_startup")
        if required_process is not None and required_process.poll() is not None:
            raise WebRuntimeError("bridge_process_stopped")
        connection = HTTPConnection(host, port, timeout=0.5)
        display_host = f"[{host}]" if ":" in host else host
        headers = {"Accept": "application/json", "Host": f"{display_host}:{port}"}
        if token is not None:
            headers[BRIDGE_TOKEN_HEADER] = token
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            body = response.read(8193)
            last_response_status = response.status
            if response.status == 200 and len(body) <= 8192:
                payload = json.loads(body)
                if isinstance(payload, dict) and payload.get("status") == "ready":
                    return payload
        except (OSError, TimeoutError, ValueError, json.JSONDecodeError):
            last_response_status = None
        finally:
            connection.close()
        time.sleep(0.1)
    if last_response_status == 503 and unavailable_error is not None:
        raise WebRuntimeError(unavailable_error)
    raise WebRuntimeError(timeout_error)


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


def stop_gateway_processes(node_process: subprocess.Popen | None, bridge_process: subprocess.Popen | None) -> None:
    """Withdraw the browser gateway before its private authority sibling."""

    stop_process(node_process)
    stop_process(bridge_process)


def runtime_state_path(data_dir: Path) -> Path:
    return Path(data_dir) / "runtime" / "server-state.json"


def gateway_startup_log_path(data_dir: Path, nonce: str) -> Path:
    """Keep a bounded Node startup diagnostic inside the private runtime area."""

    return Path(data_dir) / "runtime" / f"node-gateway-startup-{nonce}.log"


def prune_gateway_startup_logs(data_dir: Path, *, keep: int = STARTUP_LOG_RETAINED_FILES - 1) -> None:
    """Keep only a few owner-private startup diagnostics from failed launches."""

    runtime_root = Path(data_dir) / "runtime"
    candidates: list[tuple[float, Path]] = []
    for path in runtime_root.glob("node-gateway-startup-*.log"):
        try:
            details = path.lstat()
        except OSError:
            continue
        if (
            stat.S_ISREG(details.st_mode)
            and details.st_nlink == 1
            and (not hasattr(os, "getuid") or details.st_uid == os.getuid())
        ):
            candidates.append((details.st_mtime, path))
    for _mtime, path in sorted(candidates, reverse=True)[max(0, keep):]:
        try:
            path.unlink()
        except OSError:
            continue


def open_gateway_startup_log(data_dir: Path):
    """Create a new private Node startup log without following an existing path."""

    runtime_root = Path(data_dir) / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    prune_gateway_startup_logs(data_dir)
    for _attempt in range(3):
        path = gateway_startup_log_path(data_dir, secrets.token_hex(8))
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue
        try:
            details = os.fstat(descriptor)
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_nlink != 1
                or (hasattr(os, "getuid") and details.st_uid != os.getuid())
            ):
                raise WebRuntimeError("gateway_startup_log_unavailable")
            if hasattr(os, "fchmod"):
                os.fchmod(descriptor, 0o600)
            else:
                os.chmod(path, 0o600)
            return path, os.fdopen(descriptor, "wb")
        except Exception:
            os.close(descriptor)
            path.unlink(missing_ok=True)
            raise
    raise WebRuntimeError("gateway_startup_log_unavailable")


def copy_bounded_startup_output(source: BufferedReader, destination, maximum_bytes: int = STARTUP_LOG_MAXIMUM_BYTES) -> None:
    """Drain Node output while retaining only a small private startup diagnostic."""

    retained = 0
    while True:
        chunk = source.read(1024)
        if not chunk:
            break
        remaining = maximum_bytes - retained
        if remaining > 0:
            kept = chunk[:remaining]
            destination.write(kept)
            retained += len(kept)
    destination.flush()


def start_startup_output_capture(process: subprocess.Popen, destination) -> threading.Thread:
    """Drain the Node output pipe without allowing its diagnostic file to grow."""

    if process.stdout is None:
        raise WebRuntimeError("gateway_startup_log_unavailable")
    capture = threading.Thread(
        target=copy_bounded_startup_output,
        args=(process.stdout, destination),
        name="mentat-node-startup-output",
        daemon=True,
    )
    capture.start()
    return capture


def close_startup_output_capture(capture: threading.Thread | None, destination, path: Path | None,
                                 *, remove: bool) -> None:
    """Close capture handles before optionally removing their private log on any platform."""

    if capture is not None:
        capture.join(timeout=1)
    if destination is not None:
        destination.close()
    if remove and path is not None:
        path.unlink(missing_ok=True)


def write_runtime_state(*, data_dir: Path, node_process: subprocess.Popen, host: str, port: int,
                        standalone_root: Path) -> None:
    payload = {
        "pid": int(node_process.pid), "host": host, "port": port,
        "managed_ports": [port], "runtime": "node-gateway",
        "command_path": str(standalone_root / "server.js"), "started_at": int(time.time()),
    }
    process_start_ticks = linux_process_start_ticks(int(node_process.pid))
    if IS_LINUX:
        if process_start_ticks is None:
            raise WebRuntimeError("gateway_process_identity_unavailable")
        payload["process_start_ticks"] = process_start_ticks
    write_json_atomic(
        runtime_state_path(data_dir),
        payload,
        mode=0o600,
        maximum_bytes=1024,
    )


def clear_runtime_state(data_dir: Path, node_process: subprocess.Popen | None) -> None:
    path = runtime_state_path(data_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or node_process is None or payload.get("pid") != node_process.pid:
            return
        path.unlink()
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return


def establish_task_authority(data_dir: Path) -> None:
    """Complete the one-time Task cutover before the bridge can read it."""

    try:
        ensure_task_sqlite_authority(Path(data_dir), required_source_mode=0o600)
    except (OSError, TaskRepositoryError) as exc:
        raise WebRuntimeError("task_authority_unavailable") from exc


def establish_project_authority(data_dir: Path) -> None:
    """Complete Project membership cutover before the bridge can read it."""

    try:
        ensure_project_sqlite_authority(Path(data_dir), required_source_mode=0o600)
    except (OSError, ProjectRepositoryError, TaskRepositoryError) as exc:
        raise WebRuntimeError("project_authority_unavailable") from exc


def establish_run_authority(data_dir: Path) -> None:
    """Complete the one-time Run cutover before the bridge can read it."""

    try:
        ensure_run_sqlite_authority(Path(data_dir), private_history_path(Path(data_dir)))
    except (OSError, RunRepositoryError) as exc:
        raise WebRuntimeError("run_authority_unavailable") from exc


def run_gateway(*, host: str, port: int, data_dir: Path, standalone_root: Path | None = None,
                runtime_environment: dict[str, str] | None = None, open_browser: bool = False) -> int:
    """Run one Node gateway with its authenticated, loopback-only bridge."""

    safe_host = str(host or "").strip().lower()
    if safe_host not in {"127.0.0.1", "::1"}:
        raise WebRuntimeError("gateway_host_must_be_loopback")
    node_path = find_node_24()
    if node_path is None:
        raise WebRuntimeError("node_unavailable")
    require_node_24(node_path)
    standalone = standalone_root or default_standalone_root()
    if not (standalone / "server.js").is_file():
        raise WebRuntimeError("standalone_build_missing")
    if not gateway_port_is_available(port, safe_host):
        raise WebRuntimeError("gateway_port_unavailable")

    token = secrets.token_urlsafe(32)
    bridge_port = find_free_bridge_port(safe_host)
    bridge_process: subprocess.Popen | None = None
    node_process: subprocess.Popen | None = None
    node_startup_log_path: Path | None = None
    node_startup_log = None
    node_startup_capture: threading.Thread | None = None
    remove_startup_log = False
    stop_requested = False
    reserved = False

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
        try:
            reserve_mentat_server(data_dir)
            reserved = True
        except PrivateStateError as exc:
            raise WebRuntimeError("mentat_server_already_active") from exc
        establish_task_authority(data_dir)
        establish_project_authority(data_dir)
        establish_run_authority(data_dir)
        bridge_process = subprocess.Popen(
            bridge_command(bridge_port, safe_host), cwd=application_root(),
            env=child_environment(token=token, runtime_environment=runtime_environment),
        )
        wait_for_health(port=bridge_port, path="/bridge/v1/health", process=bridge_process,
                        host=safe_host, token=token,
                        timeout_error="private_bridge_readiness_timeout")
        node_startup_log_path, node_startup_log = open_gateway_startup_log(data_dir)
        node_process = subprocess.Popen(
            node_command(node_path, standalone), cwd=standalone,
            env=node_environment(token=token, bridge_port=bridge_port, gateway_port=port,
                                 gateway_host=safe_host),
            **node_output_options(node_startup_log),
        )
        if node_process.stdout is not None:
            node_startup_capture = start_startup_output_capture(node_process, node_startup_log)
        wait_for_health(
            port=port, path="/api/gateway/health", process=node_process, host=safe_host,
            timeout_error="node_gateway_readiness_timeout",
        )
        wait_for_health(
            port=port,
            path="/api/bridge/health",
            process=node_process,
            host=safe_host,
            unavailable_error="gateway_bridge_unavailable",
            timeout_error="node_bridge_readiness_timeout",
            required_process=bridge_process,
        )
        write_runtime_state(data_dir=data_dir, node_process=node_process, host=safe_host, port=port,
                            standalone_root=standalone)
        display_host = f"[{safe_host}]" if ":" in safe_host else safe_host
        url = f"http://{display_host}:{port}"
        print(f"Mentat ready at {url}", flush=True)
        if open_browser:
            webbrowser.open(url)
        while not stop_requested:
            if bridge_process.poll() is not None:
                raise WebRuntimeError("bridge_process_stopped")
            node_return = node_process.poll()
            if node_return is not None:
                return int(node_return or 1)
            time.sleep(0.2)
        remove_startup_log = True
        return 0
    finally:
        clear_runtime_state(data_dir, node_process)
        stop_gateway_processes(node_process, bridge_process)
        close_startup_output_capture(
            node_startup_capture, node_startup_log, node_startup_log_path, remove=remove_startup_log
        )
        if reserved:
            release_mentat_server(data_dir)
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (OSError, ValueError):
                pass
