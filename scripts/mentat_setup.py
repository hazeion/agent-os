#!/usr/bin/env python
"""Interactive, local-first setup wizard for Mentat.

This helper writes only local, untracked bootstrap files:
- `mentat.local.toml` (machine-specific runtime overrides)
- `mentat.local.env` (POSIX shell `source`-ready env overrides)
- `mentat.local.env.bat` (Windows batch `call`-ready env overrides)

It intentionally does not collect or write credentials/tokens.
Credentials should remain in your existing Hermes profile (`$HERMES_HOME`) and
are never touched by this tool.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

import tomllib


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOML_PATH = Path("mentat.local.toml")
DEFAULT_ENV_PATH = Path("mentat.local.env")
DEFAULT_ENV_BAT_PATH = Path("mentat.local.env.bat")
DEFAULT_PREVIOUS_TOML_PATH = Path("agent" "-os.local.toml")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8888
DEFAULT_APP_NAME = "Mentat"
DEFAULT_GREETING_PREFIX = "Hello"
HERMES_INSTALL_URL = "https://hermes-agent.nousresearch.com/install.sh"


@dataclass
class WizardValues:
    host: str
    port: int
    data_dir: str
    public_dir: str
    hermes_home: str
    obsidian_vault: str
    app_name: str
    greeting_prefix: str
    display_name: str


@dataclass
class HermesInspection:
    command: str
    profile: str
    detected: bool
    version: str = ""
    config_path: str = ""
    hermes_home: str = ""
    error: str = ""


def default_hermes_home() -> str:
    env = os.environ.get("HERMES_HOME")
    if env:
        return env
    if os.name == "nt":
        return str(Path.home() / "AppData" / "Local" / "hermes")
    return str(Path.home() / ".hermes")


def default_obsidian_vault() -> str:
    env = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env:
        return env
    return str(Path.home() / "Documents" / "Obsidian Vault")


def hermes_command_parts(command: str) -> list[str]:
    parts = shlex.split(command)
    return parts or ["hermes"]


def hermes_subcommand(command: str, profile: str, *args: str) -> list[str]:
    parts = hermes_command_parts(command)
    if profile:
        parts.extend(["--profile", profile])
    parts.extend(args)
    return parts


def run_text_command(command: list[str]) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    output = (result.stdout or result.stderr or "").strip()
    return result.returncode == 0, output


def detect_hermes(command: str, profile: str = "") -> HermesInspection:
    version_ok, version_output = run_text_command(hermes_subcommand(command, profile, "--version"))
    config_ok, config_output = run_text_command(hermes_subcommand(command, profile, "config", "path"))

    inspection = HermesInspection(
        command=command,
        profile=profile,
        detected=version_ok or config_ok,
        version=version_output.splitlines()[0].strip() if version_ok and version_output else "",
        config_path=config_output.splitlines()[0].strip() if config_ok and config_output else "",
        error="" if version_ok or config_ok else (version_output or config_output or "Hermes CLI not found"),
    )

    if inspection.config_path:
        config_path = Path(os.path.expanduser(os.path.expandvars(inspection.config_path)))
        if config_path.name.lower() == "config.yaml":
            inspection.hermes_home = str(config_path.parent)
        elif config_path.is_dir():
            inspection.hermes_home = str(config_path)

    return inspection


def print_hermes_guidance(inspection: HermesInspection) -> None:
    print("Hermes detection:")
    print(f"  CLI command:     {inspection.command}")
    print(f"  Profile:         {inspection.profile or '(current default)'}")
    if inspection.version:
        print(f"  Version:         {inspection.version}")
    if inspection.config_path:
        print(f"  Config path:     {inspection.config_path}")
    if inspection.hermes_home:
        print(f"  Hermes home:     {inspection.hermes_home}")
        print("  Status:          Mentat can target this Hermes profile by default.")
    elif inspection.detected:
        print("  Status:          Hermes CLI found, but config path could not be resolved automatically.")
        print("  Guidance:        Run `hermes setup` (or `hermes doctor`) and rerun this wizard, or pass --hermes-home manually.")
    else:
        print(f"  Status:          {inspection.error or 'Hermes CLI not detected.'}")
        if os.name == "nt":
            print("  Guidance:        Install/configure Hermes first, then rerun this wizard or pass --hermes-home manually.")
        else:
            print(f"  Install Hermes:  curl -fsSL {HERMES_INSTALL_URL} | bash")
            print("  Then run:        hermes setup")
    print()


def parse_port(raw: str) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"Invalid port {raw!r}")
    if value < 1 or value > 65535:
        raise argparse.ArgumentTypeError("Port must be between 1 and 65535")
    return value


def toml_quote(value: str) -> str:
    # Use JSON quoting rules for stable TOML string escaping.
    return json.dumps(str(value))


def load_existing_local(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = path.read_text(encoding="utf-8")
        parsed = tomllib.loads(payload)
        if isinstance(parsed, dict):
            return parsed
    except Exception as exc:
        print(f"Warning: could not parse existing {path}: {exc}")
    return {}


def prompt_text(label: str, default: str, *, required: bool = True, allow_blank: bool = False) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None and default != "":
            return default
        if allow_blank:
            return ""
        if not required:
            return ""
        print("This field is required.")


def prompt_bool(label: str, default: bool) -> bool:
    yes_no = "Y/n" if default else "y/N"
    response = input(f"{label} ({yes_no}): ").strip().lower()
    if not response:
        return default
    return response in {"y", "yes", "true", "1"}


def prompt_int(label: str, default: int) -> int:
    default_text = str(default)
    while True:
        value = prompt_text(label, default_text)
        try:
            return parse_port(value)
        except argparse.ArgumentTypeError as exc:
            print(exc)


def _normalize_path(text: str) -> str:
    return os.path.expanduser(os.path.expandvars(text)).strip()


def gather_inputs(
    defaults: dict[str, str],
    *,
    interactive: bool,
    cli: argparse.Namespace,
) -> WizardValues:
    if interactive:
        host = prompt_text("Bind host", defaults["host"])
        port = prompt_int("Bind port", int(defaults["port"]))
        data_dir = _normalize_path(prompt_text("Data directory", defaults["data_dir"]))
        public_dir = _normalize_path(prompt_text("Public assets directory", defaults["public_dir"]))
        hermes_home = _normalize_path(prompt_text("Hermes home", defaults["hermes_home"]))
        obsidian_vault = _normalize_path(prompt_text("Obsidian vault", defaults["obsidian_vault"]))
        app_name = prompt_text("App name", defaults["app_name"])
        greeting_prefix = prompt_text("Greeting prefix", defaults["greeting_prefix"])
        display_name = prompt_text("Default dashboard display name (blank for none)", defaults.get("display_name", ""), required=False, allow_blank=True)

        if not display_name:
            display_name = ""
    else:
        host = cli.host if cli.host is not None else defaults["host"]
        port = int(cli.port) if cli.port is not None else int(defaults["port"])
        data_dir = _normalize_path(cli.data_dir or defaults["data_dir"])
        public_dir = _normalize_path(cli.public_dir or defaults["public_dir"])
        hermes_home = _normalize_path(cli.hermes_home or defaults["hermes_home"])
        obsidian_vault = _normalize_path(cli.obsidian_vault or defaults["obsidian_vault"])
        app_name = cli.app_name or defaults["app_name"]
        greeting_prefix = cli.greeting_prefix or defaults["greeting_prefix"]
        display_name = cli.display_name or defaults.get("display_name", "")

    return WizardValues(
        host=host,
        port=port,
        data_dir=data_dir,
        public_dir=public_dir,
        hermes_home=hermes_home,
        obsidian_vault=obsidian_vault,
        app_name=app_name,
        greeting_prefix=greeting_prefix,
        display_name=display_name,
    )


def write_local_toml(path: Path, values: WizardValues) -> None:
    lines = [
        "# Auto-generated local overrides for this machine.",
        "# This file is intentionally git-ignored and safe to keep machine-specific.",
        "",
        "[server]",
        f"host = {toml_quote(values.host)}",
        f"port = {values.port}",
        "",
        "[paths]",
        f"data_dir = {toml_quote(values.data_dir)}",
        f"public_dir = {toml_quote(values.public_dir)}",
        f"hermes_home = {toml_quote(values.hermes_home)}",
        f"obsidian_vault = {toml_quote(values.obsidian_vault)}",
        "",
        "[dashboard]",
        f"app_name = {toml_quote(values.app_name)}",
        f"greeting_prefix = {toml_quote(values.greeting_prefix)}",
    ]
    if values.display_name:
        lines.extend([f"display_name = {toml_quote(values.display_name)}", ""])
    else:
        lines.append("")

    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_env_file(path: Path, bat_path: Path, values: WizardValues) -> None:
    env_map = {
        "MENTAT_HOST": values.host,
        "MENTAT_PORT": str(values.port),
        "MENTAT_DATA_DIR": values.data_dir,
        "MENTAT_PUBLIC_DIR": values.public_dir,
        "HERMES_HOME": values.hermes_home,
        "OBSIDIAN_VAULT_PATH": values.obsidian_vault,
        "MENTAT_APP_NAME": values.app_name,
        "MENTAT_GREETING_PREFIX": values.greeting_prefix,
    }
    if values.display_name:
        env_map["MENTAT_DISPLAY_NAME"] = values.display_name

    sh_lines = [
        "# Auto-generated Mentat env flags for this machine.",
        "# This file is intentionally git-ignored.",
        "",
        "# Load with: source ./mentat.local.env",
    ]
    for key, value in env_map.items():
        sh_lines.append(f"export {key}={shlex.quote(value)}")

    bat_lines = [
        "@echo off",
        "REM Auto-generated Mentat env flags for this machine.",
        "REM This file is intentionally git-ignored.",
        "",
        "REM Load with: call mentat.local.env.bat",
    ]
    for key, value in env_map.items():
        escaped = str(value).replace('^', '^^').replace('%', '%%').replace('"', '""')
        bat_lines.append(f'set "{key}={escaped}"')

    path.write_text("\n".join(sh_lines).rstrip() + "\n", encoding="utf-8")
    bat_path.write_text("\n".join(bat_lines).rstrip() + "\n", encoding="utf-8")


def current_summary(values: WizardValues) -> str:
    return "\n".join(
        [
            "Mentat local setup summary:",
            f"  Host:            {values.host}",
            f"  Port:            {values.port}",
            f"  Data dir:        {values.data_dir}",
            f"  Public dir:      {values.public_dir}",
            f"  Hermes home:     {values.hermes_home}",
            f"  Obsidian vault:  {values.obsidian_vault}",
            f"  App name:        {values.app_name}",
            f"  Greeting prefix: {values.greeting_prefix}",
            f"  Display name:    {values.display_name or '(unset)'}",
        ]
    )


def existing_diff_text(existing: dict, values: WizardValues) -> str:
    lines: list[str] = []
    if not existing:
        lines.append("No existing Mentat local config found; this will create a new local override file.")
        return "\n".join(lines)

    existing_server = existing.get("server", {}) if isinstance(existing.get("server"), dict) else {}
    existing_paths = existing.get("paths", {}) if isinstance(existing.get("paths"), dict) else {}
    existing_dashboard = existing.get("dashboard", {}) if isinstance(existing.get("dashboard"), dict) else {}

    candidate = {
        "server.host": values.host,
        "server.port": values.port,
        "paths.data_dir": values.data_dir,
        "paths.public_dir": values.public_dir,
        "paths.hermes_home": values.hermes_home,
        "paths.obsidian_vault": values.obsidian_vault,
        "dashboard.app_name": values.app_name,
        "dashboard.greeting_prefix": values.greeting_prefix,
        "dashboard.display_name": values.display_name,
    }
    source = {
        "server.host": existing_server.get("host", DEFAULT_HOST),
        "server.port": existing_server.get("port", DEFAULT_PORT),
        "paths.data_dir": existing_paths.get("data_dir", "data"),
        "paths.public_dir": existing_paths.get("public_dir", "public"),
        "paths.hermes_home": existing_paths.get("hermes_home", default_hermes_home()),
        "paths.obsidian_vault": existing_paths.get("obsidian_vault", default_obsidian_vault()),
        "dashboard.app_name": existing_dashboard.get("app_name", DEFAULT_APP_NAME),
        "dashboard.greeting_prefix": existing_dashboard.get("greeting_prefix", DEFAULT_GREETING_PREFIX),
        "dashboard.display_name": existing_dashboard.get("display_name", ""),
    }

    for key, new_value in candidate.items():
        old_value = source.get(key)
        if old_value != new_value:
            lines.append(f"  {key}: {old_value!r} -> {new_value!r}")

    if not lines:
        lines.append("No effective changes from existing local config values.")
    return "\n".join(lines)


def write_mode_confirm(path: Path, values: WizardValues, *, interactive: bool, force: bool) -> bool:
    if not path.exists():
        return True
    if force:
        return True
    if not interactive:
        return True

    print(f"{path} already exists and will be updated.")
    return prompt_bool("Continue", True)


def print_next_steps(env_path: Path, env_bat_path: Path, *, wrote_env: bool) -> None:
    print("\nNext step:")
    print("  python server.py --print-config")
    if wrote_env:
        if os.name == "nt":
            print(f"  call {env_bat_path}")
        else:
            print(f"  source {env_path}")
    if os.name == "nt":
        print("  run.bat")
    else:
        print("  ./run.sh")
    print("\nIf Mentat should follow a different Hermes profile than the one detected above, rerun this wizard with --hermes-home or set HERMES_HOME before starting the server.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Walk a teammate through Mentat local setup")
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="Path to Mentat repo root")
    parser.add_argument("--non-interactive", action="store_true", help="Run with flags only (no prompts)")
    parser.add_argument("--host", default=None, help="Mentat host (default: prompt/repo default)")
    parser.add_argument("--port", default=None, type=parse_port, help="Mentat port")
    parser.add_argument("--data-dir", default=None, help="Data directory path override")
    parser.add_argument("--public-dir", default=None, help="Public assets directory path override")
    parser.add_argument("--hermes-home", default=None, help="Hermes home path override")
    parser.add_argument("--hermes-command", default="hermes", help="Hermes CLI command to inspect (default: hermes)")
    parser.add_argument("--hermes-profile", default="", help="Hermes profile to inspect before choosing HERMES_HOME")
    parser.add_argument("--skip-hermes-check", action="store_true", help="Skip Hermes CLI inspection and use manual/default HERMES_HOME resolution only")
    parser.add_argument("--obsidian-vault", default=None, help="Obsidian vault path override")
    parser.add_argument("--app-name", default=None, help="Dashboard product name")
    parser.add_argument("--greeting-prefix", default=None, help="Greeting prefix in dashboard identity")
    parser.add_argument("--display-name", default=None, help="Optional dashboard display name")
    parser.add_argument("--toml", default=str(DEFAULT_TOML_PATH), help="Output path for local TOML")
    parser.add_argument("--env", default=str(DEFAULT_ENV_PATH), help="Output path for POSIX env file")
    parser.add_argument("--env-bat", default=str(DEFAULT_ENV_BAT_PATH), help="Output path for Windows env file")
    parser.add_argument(
        "--write-env",
        choices=("always", "ask", "never"),
        default="ask",
        help="Whether to generate local env override files",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite local files without prompting")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).expanduser().resolve()
    repo_root.mkdir(parents=True, exist_ok=True)

    hermes_inspection = HermesInspection(command=args.hermes_command, profile=args.hermes_profile, detected=False)
    if not args.skip_hermes_check:
        hermes_inspection = detect_hermes(args.hermes_command, args.hermes_profile)
        print_hermes_guidance(hermes_inspection)

    toml_path = Path(args.toml).expanduser()
    env_path = Path(args.env).expanduser()
    env_bat_path = Path(args.env_bat).expanduser()

    if not toml_path.is_absolute():
        toml_path = repo_root / toml_path
    if not env_path.is_absolute():
        env_path = repo_root / env_path
    if not env_bat_path.is_absolute():
        env_bat_path = repo_root / env_bat_path

    previous_toml_path = repo_root / DEFAULT_PREVIOUS_TOML_PATH
    defaults_source_path = toml_path
    defaults = load_existing_local(toml_path)
    if not defaults and previous_toml_path.exists() and previous_toml_path != toml_path:
        defaults = load_existing_local(previous_toml_path)
        if defaults:
            defaults_source_path = previous_toml_path
            print(f"Imported defaults from previous local config: {previous_toml_path}")
    existing_server = defaults.get("server", {}) if isinstance(defaults.get("server"), dict) else {}
    existing_paths = defaults.get("paths", {}) if isinstance(defaults.get("paths"), dict) else {}
    existing_dashboard = defaults.get("dashboard", {}) if isinstance(defaults.get("dashboard"), dict) else {}

    if defaults:
        print(f"Found existing local config: {defaults_source_path}")

    detected_hermes_home = hermes_inspection.hermes_home if hermes_inspection.hermes_home else default_hermes_home()
    resolved_defaults = {
        "host": str(existing_server.get("host", DEFAULT_HOST)),
        "port": str(existing_server.get("port", DEFAULT_PORT)),
        "data_dir": str(existing_paths.get("data_dir", "data")),
        "public_dir": str(existing_paths.get("public_dir", "public")),
        "hermes_home": str(existing_paths.get("hermes_home", detected_hermes_home)),
        "obsidian_vault": str(existing_paths.get("obsidian_vault", default_obsidian_vault())),
        "app_name": str(existing_dashboard.get("app_name", DEFAULT_APP_NAME)),
        "greeting_prefix": str(existing_dashboard.get("greeting_prefix", DEFAULT_GREETING_PREFIX)),
        "display_name": str(existing_dashboard.get("display_name", "")),
    }

    values = gather_inputs(resolved_defaults, interactive=not args.non_interactive, cli=args)

    print("\n" + current_summary(values))
    print("\nPlanned changes:")
    print(existing_diff_text(defaults, values))

    if not write_mode_confirm(toml_path, values, interactive=not args.non_interactive, force=args.force):
        print("Aborted.")
        return 1

    write_local_toml(toml_path, values)
    print(f"\nWrote local config: {toml_path}")

    should_write_env: bool
    if args.write_env == "always":
        should_write_env = True
    elif args.write_env == "never":
        should_write_env = False
    else:
        should_write_env = prompt_bool("Also write local env flag files (mentat.local.env and .bat)?", True) if not args.non_interactive else True

    if should_write_env:
        write_env_file(env_path, env_bat_path, values)
        print(f"Wrote env overrides: {env_path}")
        print(f"Wrote env overrides: {env_bat_path}")

    print("\nAll local bootstrap files are local-only and should stay out of git.")
    print_next_steps(env_path, env_bat_path, wrote_env=should_write_env)

    print("\nCredentials are never written by this wizard; your Hermes OAuth tokens and API keys remain in your Hermes profile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
