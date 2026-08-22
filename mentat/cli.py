"""Unified command line for installed and source-checkout Mentat."""

from __future__ import annotations

import argparse
import hmac
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
    start.add_argument(
        "--legacy-ui",
        action="store_true",
        help="Start the compatibility interface instead of the Node dashboard.",
    )

    restore = commands.add_parser("restore", help="Preview or confirm a validated restore.")
    _runtime_arguments(restore)
    restore.add_argument("backup_file", type=Path)
    restore.add_argument("--confirm", metavar="TOKEN")

    task_migration = commands.add_parser(
        "task-migration",
        help="Preview the exact Task cutover or report existing SQLite authority.",
    )
    _runtime_arguments(task_migration)

    task_export = commands.add_parser(
        "task-export",
        help="Export authoritative Tasks to tasks.json for an intentional downgrade.",
    )
    _runtime_arguments(task_export)
    task_export.add_argument("--confirm", metavar="TOKEN")
    task_export.add_argument(
        "--compatible-root",
        action="store_true",
        help="Create a schema-5 sibling data root for a pre-cutover Mentat build.",
    )

    connection = commands.add_parser(
        "connection",
        help="Configure, test, or select local and remote Hermes.",
    )
    connection_commands = connection.add_subparsers(
        dest="connection_command",
        required=True,
    )
    connection_status = connection_commands.add_parser(
        "status",
        help="Show the active mode and whether one remote is remembered.",
    )
    _runtime_arguments(connection_status)
    connection_test = connection_commands.add_parser(
        "test",
        help="Test local Hermes or the remembered remote without switching.",
    )
    connection_test.add_argument("mode", choices=("local", "remote"))
    _runtime_arguments(connection_test)
    connection_use = connection_commands.add_parser(
        "use",
        help="Select local Hermes or the remembered remote.",
    )
    connection_use.add_argument("mode", choices=("local", "remote"))
    connection_use.add_argument("--confirm", metavar="TOKEN")
    _runtime_arguments(connection_use)
    connection_configure = connection_commands.add_parser(
        "configure-remote",
        help="Remember and select one authenticated remote Hermes endpoint.",
    )
    connection_configure.add_argument("--endpoint", required=True)
    connection_configure.add_argument("--label", default="Remote Hermes")
    source = connection_configure.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--api-key-env",
        nargs="?",
        const="MENTAT_REMOTE_HERMES_API_KEY",
        metavar="NAME",
        help="Read the key from NAME (default: MENTAT_REMOTE_HERMES_API_KEY).",
    )
    source.add_argument(
        "--api-key-file",
        type=Path,
        metavar="OWNER_ONLY_ENV_FILE",
        help="Read MENTAT_REMOTE_HERMES_API_KEY from an owner-only env file.",
    )
    connection_configure.add_argument("--confirm", metavar="TOKEN")
    _runtime_arguments(connection_configure)
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
    repeat_setup_options = bool(_forward_runtime_arguments(args))
    issue = server.prepare_data_root_for_startup(config)
    if issue is not None:
        _print_json({"ok": False, "status": "blocked", "issue": issue})
        return 2
    _print_json(
        {
            "ok": True,
            "status": "ready",
            "message": (
                "Mentat is ready. Run `mentat start --open-browser`"
                + (
                    " with the same setup options"
                    if repeat_setup_options
                    else ""
                )
                + " to launch the dashboard. You can use planning features "
                "without Hermes."
            ),
            "next_command": "mentat start --open-browser",
            "repeat_setup_options": repeat_setup_options,
            "version": __version__,
        }
    )
    return 0


def run_lifecycle(command: str, args: argparse.Namespace) -> int:
    import mentat_lifecycle

    return mentat_lifecycle.main([command, "--", *_forward_runtime_arguments(args)])


def _web_runtime_environment(args: argparse.Namespace) -> dict[str, str]:
    """Pass selected runtime settings to the private bridge, never to Node APIs."""

    environment: dict[str, str] = {}
    values = {
        "MENTAT_CONFIG": getattr(args, "config_path", None),
        "MENTAT_DATA_DIR": getattr(args, "data_dir", None),
        "MENTAT_PUBLIC_DIR": getattr(args, "public_dir", None),
        "HERMES_HOME": getattr(args, "hermes_home", None),
        "OBSIDIAN_VAULT_PATH": getattr(args, "obsidian_vault", None),
    }
    for name, value in values.items():
        if value is not None:
            environment[name] = str(value)
    environment["MENTAT_LAUNCHER_PID"] = str(os.getpid())
    return environment


def _legacy_start(args: argparse.Namespace) -> int:
    """Keep the prior server path available for an explicit rollback."""

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


def run_start(args: argparse.Namespace) -> int:
    if getattr(args, "legacy_ui", False):
        return _legacy_start(args)

    preflight = run_lifecycle("preflight", args)
    if preflight != 0:
        return preflight
    from .web_runtime import WebRuntimeError, run_gateway

    _runtime_config, config = _load_config(args)
    try:
        return run_gateway(
            host=config.host,
            port=config.port,
            data_dir=config.data_dir,
            runtime_environment=_web_runtime_environment(args),
            open_browser=args.open_browser,
        )
    except WebRuntimeError as exc:
        print(f"Mentat could not start the Node dashboard: {exc}", file=sys.stderr)
        return 2


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


def run_task_migration(args: argparse.Namespace) -> int:
    import runtime_config

    forwarded = [*_forward_runtime_arguments(args), "--preview-task-sqlite-migration"]
    cli_args = runtime_config.parse_cli_args(forwarded)
    config = runtime_config.load_app_config(cli_args)
    payload, exit_code = runtime_config.run_task_sqlite_migration_cli(cli_args, config)
    _print_json(payload)
    return exit_code


def run_task_export(args: argparse.Namespace) -> int:
    from task_repository import (
        TaskRepositoryError,
        confirm_task_compatible_export,
        confirm_task_legacy_export,
        preview_task_compatible_export,
        preview_task_legacy_export,
    )

    runtime_config, config = _load_config(args)
    required_destination_mode = (
        None
        if runtime_config._absolute_without_following(config.data_dir)
        == runtime_config._absolute_without_following(runtime_config.PACKAGED_SEED_DIR)
        else 0o600
    )
    try:
        if args.compatible_root and args.confirm:
            payload = confirm_task_compatible_export(
                config.data_dir,
                args.confirm,
            )
        elif args.compatible_root:
            payload = preview_task_compatible_export(config.data_dir).public_summary()
        elif args.confirm:
            payload = confirm_task_legacy_export(
                config.data_dir,
                args.confirm,
                required_destination_mode=required_destination_mode,
            )
        else:
            payload = preview_task_legacy_export(
                config.data_dir,
                required_destination_mode=required_destination_mode,
            ).public_summary()
    except TaskRepositoryError as exc:
        writes_performed = getattr(exc, "writes_performed", False)
        _print_json(
            {
                "ok": False,
                "status": (
                    "blocked" if writes_performed is False else "partial"
                ),
                "error_code": exc.code,
                "writes_performed": writes_performed,
            }
        )
        return 2
    _print_json({"ok": True, **payload})
    return 0


def _connection_server_running(config) -> bool:
    import mentat_lifecycle
    from private_state import mentat_server_active

    try:
        if mentat_server_active(config.data_dir):
            return True
        report = mentat_lifecycle.status_report(config)
        return any(
            item.get("is_mentat") is True
            for item in report.get("listeners", [])
            if isinstance(item, dict)
        )
    except Exception:
        return True


def _safe_connection_error(error) -> int:
    code = getattr(error, "code", "connection_operation_failed")
    _print_json(
        {
            "ok": False,
            "status": "blocked",
            "error_code": str(code),
            "message": "The Hermes connection operation was not applied.",
        }
    )
    return 2


def _confirmation_payload(preview) -> dict:
    from remote_hermes import offline_confirmation_token

    payload = preview.public_summary()
    payload["confirmation_token"] = offline_confirmation_token(preview)
    payload["message"] = "Review this exact change, then confirm it."
    return payload


def _confirm_connection_change(args, preview, apply) -> int:
    from remote_hermes import offline_confirmation_token

    expected = offline_confirmation_token(preview)
    provided = getattr(args, "confirm", None)
    if provided is None:
        _print_json(_confirmation_payload(preview))
        if not sys.stdin.isatty():
            return 3
        response = input("Apply this Hermes connection change? [y/N]: ").strip().lower()
        if response not in {"y", "yes"}:
            _print_json({"ok": False, "status": "cancelled"})
            return 1
    elif not hmac.compare_digest(str(provided), expected):
        _print_json(
            {
                "ok": False,
                "status": "blocked",
                "error_code": "connection_confirmation_invalid",
                "message": "The connection changed or the confirmation token is invalid.",
            }
        )
        return 2

    _runtime_config, config = _load_config(args)
    if _connection_server_running(config):
        _print_json(
            {
                "ok": False,
                "status": "blocked",
                "error_code": "connection_change_server_running",
                "message": "Stop Mentat before changing its Hermes connection.",
            }
        )
        return 2
    try:
        result = apply(preview.confirmation_token)
    except Exception as exc:
        from remote_hermes import RemoteHermesError

        if isinstance(exc, RemoteHermesError):
            return _safe_connection_error(exc)
        raise
    _print_json({"ok": True, **result})
    return 0


def run_connection(args: argparse.Namespace) -> int:
    from remote_hermes import (
        RemoteHermesError,
        confirm_connection_from_source,
        confirm_remembered_connection,
        credential_source_from_values,
        preview_connection_from_source,
        preview_remembered_connection,
        public_connection_payload,
        test_connection_mode,
    )

    _runtime_config, config = _load_config(args)
    try:
        if args.connection_command == "status":
            payload = public_connection_payload(config.data_dir)
            _print_json({"ok": payload.get("status") == "configured", **payload})
            return 0 if payload.get("status") == "configured" else 2
        if args.connection_command == "test":
            result = test_connection_mode(config.data_dir, args.mode)
            _print_json({"ok": True, **result})
            return 0
        if args.connection_command == "use":
            preview = preview_remembered_connection(config.data_dir, args.mode)
            return _confirm_connection_change(
                args,
                preview,
                lambda token: confirm_remembered_connection(
                    config.data_dir,
                    args.mode,
                    token,
                    require_server_stopped=True,
                ),
            )
        if args.connection_command == "configure-remote":
            source = (
                credential_source_from_values(
                    "environment",
                    name=args.api_key_env,
                )
                if args.api_key_env is not None
                else credential_source_from_values(
                    "env_file",
                    path=os.path.abspath(
                        os.fspath(args.api_key_file.expanduser())
                    ),
                )
            )
            preview = preview_connection_from_source(
                config.data_dir,
                label=args.label,
                endpoint=args.endpoint,
                credential_source=source,
            )
            return _confirm_connection_change(
                args,
                preview,
                lambda token: confirm_connection_from_source(
                    config.data_dir,
                    label=args.label,
                    endpoint=args.endpoint,
                    credential_source=source,
                    confirmation_token=token,
                    require_server_stopped=True,
                ),
            )
    except RemoteHermesError as exc:
        return _safe_connection_error(exc)
    raise RuntimeError("unknown connection command")


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
        "task-migration": run_task_migration,
        "task-export": run_task_export,
        "connection": run_connection,
    }
    return handlers[args.command](args)
