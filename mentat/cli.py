"""Unified command line for installed and source-checkout Mentat."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from .version import DISPLAY_VERSION, __version__


def _runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", dest="config_path")
    parser.add_argument("--host")
    parser.add_argument("--port")
    parser.add_argument("--data-dir")
    parser.add_argument("--public-dir")
    parser.add_argument("--hermes-home")
    parser.add_argument("--obsidian-vault")


def _forward_runtime_arguments(args: argparse.Namespace) -> list[str]:
    forwarded: list[str] = []
    option_names = {"config_path": "config"}
    for name in (
        "config_path",
        "host",
        "port",
        "data_dir",
        "public_dir",
        "hermes_home",
        "obsidian_vault",
    ):
        value = getattr(args, name, None)
        if value is None:
            continue
        option = option_names.get(name, name.replace("_", "-"))
        forwarded.extend([f"--{option}", str(value)])
    return forwarded


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mentat",
        description="Run and care for your local Mentat dashboard.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Mentat {DISPLAY_VERSION} ({__version__})",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("setup", "Prepare Mentat's private local data."),
        ("stop", "Stop a running local dashboard."),
        ("status", "Show whether Mentat is running."),
        ("doctor", "Check Mentat and optional integrations."),
        ("backup", "Create a validated local backup."),
    ):
        command = commands.add_parser(name, help=help_text)
        _runtime_arguments(command)

    start = commands.add_parser("start", help="Start the local dashboard.")
    _runtime_arguments(start)
    start.add_argument(
        "--open-browser",
        action="store_true",
        help="Open the dashboard after the loopback server is ready.",
    )

    restore = commands.add_parser("restore", help="Preview or confirm a validated restore.")
    _runtime_arguments(restore)
    restore.add_argument("backup_file", type=Path)
    restore.add_argument("--confirm", metavar="TOKEN")
    return parser


def _load_config(args: argparse.Namespace):
    import runtime_config

    runtime_args = runtime_config.parse_cli_args(_forward_runtime_arguments(args))
    return runtime_config, runtime_config.load_app_config(runtime_args)


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def run_setup(args: argparse.Namespace) -> int:
    import server

    _runtime_config, config = _load_config(args)
    issue = server.prepare_data_root_for_startup(config)
    if issue is not None:
        _print_json({"ok": False, "status": "blocked", "issue": issue})
        return 2
    _print_json(
        {
            "ok": True,
            "status": "ready",
            "message": "Mentat is ready. Run `mentat start` to open your dashboard.",
            "version": __version__,
        }
    )
    return 0


def run_lifecycle(command: str, args: argparse.Namespace) -> int:
    import mentat_lifecycle

    return mentat_lifecycle.main([command, "--", *_forward_runtime_arguments(args)])


def run_start(args: argparse.Namespace) -> int:
    preflight = run_lifecycle("preflight", args)
    if preflight != 0:
        return preflight
    runtime_arguments = _forward_runtime_arguments(args)
    if bool(getattr(sys, "frozen", False)):
        command = [sys.executable, *runtime_arguments]
    else:
        command = [sys.executable, "-m", "server", *runtime_arguments]
    environment = os.environ.copy()
    environment["MENTAT_LAUNCHER_PID"] = str(os.getpid())
    if bool(getattr(sys, "frozen", False)):
        environment["MENTAT_NATIVE_SERVER"] = "1"
    if not args.open_browser:
        return subprocess.call(command, env=environment)

    _runtime_config, config = _load_config(args)
    host = "::1" if config.host == "localhost" and ":" in config.host else config.host
    display_host = f"[{host}]" if ":" in host else host
    url = f"http://{display_host}:{config.port}"
    process = subprocess.Popen(command, env=environment)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return int(process.returncode or 1)
            try:
                with urlopen(f"{url}/api/overview", timeout=0.5) as response:
                    if response.status == 200:
                        webbrowser.open(url)
                        return process.wait()
            except (URLError, TimeoutError, OSError):
                time.sleep(0.1)
        process.terminate()
        process.wait(timeout=5)
        print("Mentat did not become ready within 15 seconds.", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return 130


def run_doctor(args: argparse.Namespace) -> int:
    import runtime_config

    _module, config = _load_config(args)
    data_status = runtime_config.schema_preflight_status(config.data_dir)
    hermes_available = shutil.which("hermes") is not None
    google_calendar_available = importlib.util.find_spec("googleapiclient") is not None
    payload = {
        "ok": data_status not in {"invalid", "newer"},
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.system().lower(),
        "network": "loopback-only",
        "data": {"status": data_status},
        "optional_integrations": {
            "hermes": "available" if hermes_available else "not detected",
            "google_calendar": "available" if google_calendar_available else "not installed",
        },
    }
    _print_json(payload)
    return 0 if payload["ok"] else 2


def run_backup(args: argparse.Namespace) -> int:
    import runtime_config

    forwarded = [*_forward_runtime_arguments(args), "--create-backup"]
    cli_args = runtime_config.parse_cli_args(forwarded)
    config = runtime_config.load_app_config(cli_args)
    payload, exit_code = runtime_config.run_backup_restore_cli(cli_args, config)
    _print_json(payload)
    return exit_code


def run_restore(args: argparse.Namespace) -> int:
    import runtime_config

    operation = ["--confirm-restore", args.confirm] if args.confirm else ["--preview-restore"]
    forwarded = [
        *_forward_runtime_arguments(args),
        *operation,
        "--restore-backup",
        str(args.backup_file),
    ]
    cli_args = runtime_config.parse_cli_args(forwarded)
    config = runtime_config.load_app_config(cli_args)
    payload, exit_code = runtime_config.run_backup_restore_cli(cli_args, config)
    _print_json(payload)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {
        "setup": run_setup,
        "start": run_start,
        "stop": lambda value: run_lifecycle("stop", value),
        "status": lambda value: run_lifecycle("status", value),
        "doctor": run_doctor,
        "backup": run_backup,
        "restore": run_restore,
    }
    return handlers[args.command](args)
