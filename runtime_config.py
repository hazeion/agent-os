"""Runtime configuration loading for the local Mentat dashboard.

This module owns TOML/env/CLI config parsing so the HTTP server can stay focused
on data access and route handling.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from data_backup_restore import (
    create_durable_backup,
    preview_durable_restore,
    restore_durable_backup,
    restore_startup_status,
    restore_status_under_lock,
)
from private_state import private_control_issue
from data_schema import (
    initialize_fresh_schema_under_lock,
    prepare_fresh_schema_initialization,
    schema_preflight_status,
    schema_status_under_lock,
)
from data_layout import (
    SEED_FILE_NAMES,
    _absolute_without_following,
    _initialization_lock,
    _pinned_root_identity,
    initialize_data_root,
    resolve_data_root,
    resolve_explicit_data_root,
)

BASE_DIR = Path(__file__).resolve().parent
INSTALLED_ASSET_ROOT = Path(sys.prefix) / "share" / "mentat"


def bundled_asset_dir(name: str) -> Path:
    """Locate source-checkout or wheel-installed read-only product assets."""

    if bool(getattr(sys, "frozen", False)) and sys.platform == "darwin":
        native_path = Path(sys.executable).resolve().parent.parent / "Resources" / name
        if native_path.is_dir() and not native_path.is_symlink():
            return native_path
    source_path = BASE_DIR / name
    if source_path.is_dir():
        return source_path
    return INSTALLED_ASSET_ROOT / name


DEFAULT_CONFIG_FILE = BASE_DIR / "mentat.toml"
LOCAL_CONFIG_FILE = BASE_DIR / "mentat.local.toml"
LEGACY_DEFAULT_CONFIG_FILE = BASE_DIR / ("agent" "-os.toml")
LEGACY_LOCAL_CONFIG_FILE = BASE_DIR / ("agent" "-os.local.toml")
ENV_PREFIX = "MENTAT"
LEGACY_ENV_PREFIX = "AGENT" + "_OS"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8888
DEFAULT_APP_NAME = "Mentat"
DEFAULT_OBSIDIAN_VAULT = Path.home() / "Documents" / "Obsidian Vault"
PACKAGED_SEED_DIR = bundled_asset_dir("data")
PATH_SETTING_KEYS = {"data_dir", "public_dir", "hermes_home", "obsidian_vault"}




@dataclass(frozen=True)
class AppConfig:
    config_files: tuple[Path, ...]
    host: str
    port: int
    data_dir: Path
    public_dir: Path
    hermes_home: Path
    obsidian_vault: Path
    display_name: str | None = None
    greeting_prefix: str | None = None
    app_name: str | None = None
    data_dir_source: str = "unknown"


def prepare_data_root_for_startup(config: AppConfig) -> str | None:
    """Admit only fresh/current storage before any source mutation."""

    from mentat_db import (
        MentatDatabaseError, connect,
        validate_current_database_root,
    )
    from private_state import fresh_console_storage_issue

    unsupported = (
        "Mentat supports only its current database and data format "
        "(current_data_root_required). Choose a fresh data directory. "
        "Existing files were not upgraded or deleted."
    )

    def database_issue(target: Path) -> str | None:
        try:
            current = validate_current_database_root(target)
            if not current:
                issue = fresh_console_storage_issue(target)
                if issue is not None:
                    return issue
        except (MentatDatabaseError, OSError):
            return "unsupported_or_invalid_current_database"
        return None

    if database_issue(config.data_dir) is not None:
        return unsupported
    schema_preflight = schema_preflight_status(config.data_dir)
    if schema_preflight not in {"legacy", "current", "fresh_incomplete"}:
        return unsupported
    development = _absolute_without_following(config.data_dir) == _absolute_without_following(PACKAGED_SEED_DIR)
    if schema_preflight == "legacy" and not development and any(
        os.path.lexists(os.fspath(config.data_dir / name)) for name in SEED_FILE_NAMES
    ):
        return unsupported
    try:
        if schema_preflight == "current" and not validate_current_database_root(config.data_dir):
            return unsupported
    except (MentatDatabaseError, OSError):
        return unsupported
    if restore_startup_status(config.data_dir) != "clear":
        return "Mentat found an incomplete restore (restore_incomplete_or_invalid). Preview the selected current-format backup before startup."
    if private_control_issue(config.data_dir) is not None:
        return "Mentat found incomplete private state (private_console_state_invalid). Existing files were not changed."

    def guard(target: Path, descriptor: int | None) -> str | None:
        issue = database_issue(target)
        if issue is not None:
            return issue
        schema = schema_status_under_lock(target, descriptor)
        allowed = {"current"} if schema_preflight == "current" else {"legacy", "fresh_incomplete", "current"}
        if schema not in allowed:
            return "invalid_data_schema"
        if schema == "current" and not validate_current_database_root(target):
            return "current_database_missing"
        if restore_status_under_lock(target, descriptor) != "clear":
            return "restore_incomplete_or_invalid"
        return private_control_issue(target)

    def prepare(target: Path, descriptor: int | None, plan) -> str | None:
        issue = prepare_fresh_schema_initialization(PACKAGED_SEED_DIR, target, descriptor, plan)
        if issue is not None:
            return issue
        # The fresh reservation remains until JSON publication completes. A crash
        # can resume it; an established current root cannot recreate a lost DB.
        try:
            connection = connect(target)
            connection.close()
        except (MentatDatabaseError, OSError):
            return "unsupported_or_invalid_current_database"
        return None

    verified_identity = None
    verified_schema = None

    def finalize(target: Path, descriptor: int | None, _plan) -> str | None:
        nonlocal verified_identity, verified_schema
        issue = initialize_fresh_schema_under_lock(PACKAGED_SEED_DIR, target, descriptor)
        if issue is not None:
            return issue
        issue = guard(target, descriptor)
        if issue is not None:
            return issue
        if schema_status_under_lock(target, descriptor) != "current":
            return "current_data_root_required"
        verified_identity = _pinned_root_identity(target, descriptor)
        verified_schema = "current"
        return None if verified_identity is not None else "data_root_identity_unverified"

    result = initialize_data_root(
        PACKAGED_SEED_DIR, config.data_dir,
        locked_guard=guard, locked_prepare=prepare, locked_finalize=finalize,
    )
    if result.status not in {"initialized", "existing", "development_override"}:
        if "data_root_overlaps_seed_root" in result.issues:
            return "Mentat cannot use a data directory overlapping packaged seeds (data_root_overlaps_seed_root)."
        if "restore_incomplete_or_invalid" in result.issues:
            return "Mentat found an incomplete restore (restore_incomplete_or_invalid). Existing files were not changed."
        return unsupported if any("schema" in issue or "legacy" in issue or "database" in issue for issue in result.issues) else "Mentat could not initialize its current data root (data_initialization_failed)."
    try:
        with _initialization_lock(config.data_dir) as descriptor:
            issue = guard(config.data_dir, descriptor)
            if issue is not None:
                return unsupported
            identity = _pinned_root_identity(config.data_dir, descriptor)
            schema = schema_status_under_lock(config.data_dir, descriptor)
            if result.status == "development_override":
                if not development or schema not in {"legacy", "current"}:
                    return unsupported
            elif identity != verified_identity or schema != verified_schema:
                return "Mentat data root changed after verification (invalid_data_schema)."
            if result.status == "development_override":
                connection = connect(config.data_dir)
                connection.close()
    except (MentatDatabaseError, OSError):
        return unsupported
    return None


def maybe_stripped(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def first_nonempty(*values) -> str | None:
    for value in values:
        text = maybe_stripped(value)
        if text is not None:
            return text
    return None


def env_name(suffix: str, *, legacy: bool = False) -> str:
    prefix = LEGACY_ENV_PREFIX if legacy else ENV_PREFIX
    return f"{prefix}_{suffix}"


def env_value(suffix: str) -> str | None:
    return first_nonempty(os.environ.get(env_name(suffix)), os.environ.get(env_name(suffix, legacy=True)))


def default_hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    discovered = discover_hermes_home_from_cli()
    if discovered is not None:
        return discovered
    if sys.platform.startswith("win"):
        return Path.home() / "AppData" / "Local" / "hermes"
    return Path.home() / ".hermes"


def discover_hermes_home_from_cli() -> Path | None:
    command = ["hermes", "config", "path"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if not lines:
        return None

    config_path = Path(os.path.expanduser(os.path.expandvars(lines[0]))).resolve()
    if config_path.name.lower() == "config.yaml":
        return config_path.parent
    if config_path.is_dir():
        return config_path
    return None


def default_obsidian_vault() -> Path:
    return DEFAULT_OBSIDIAN_VAULT


def resolve_path(value: str | Path, *, base_dir: Path) -> Path:
    if isinstance(value, Path):
        path = value
    else:
        path = Path(os.path.expandvars(os.path.expanduser(str(value))))
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path.resolve()


def parse_port(value, *, source: str) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {source}: {value!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid {source}: {value!r}")
    return port


def deep_merge_dicts(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_toml_file(path: Path) -> dict:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Mentat config must parse to a table: {path}")
    return data


def normalize_config_document(config: dict, source_path: Path) -> dict:
    normalized = deep_merge_dicts({}, config)
    paths = normalized.get("paths")
    if isinstance(paths, dict):
        for key in PATH_SETTING_KEYS:
            value = paths.get(key)
            if maybe_stripped(value) is None:
                continue
            if key == "data_dir":
                paths[key] = str(
                    resolve_explicit_data_root(value, base_dir=source_path.parent)
                )
            else:
                paths[key] = str(resolve_path(value, base_dir=source_path.parent))
    return normalized


def parse_cli_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the Mentat dashboard.")
    parser.add_argument("--config", dest="config_path", help="Extra TOML config file to merge after mentat.toml and mentat.local.toml.")
    parser.add_argument("--host", help="Bind host override.")
    parser.add_argument("--port", help="Bind port override.")
    parser.add_argument("--data-dir", help="Dashboard data directory override.")
    parser.add_argument("--public-dir", help="Static assets directory override.")
    parser.add_argument("--hermes-home", help="Hermes home directory override.")
    parser.add_argument("--obsidian-vault", help="Obsidian vault path override.")
    parser.add_argument("--display-name", help="Dashboard greeting name override.")
    parser.add_argument("--greeting-prefix", help="Dashboard greeting prefix override.")
    parser.add_argument("--app-name", help="User-facing dashboard product name override.")
    operation = parser.add_mutually_exclusive_group()
    operation.add_argument("--print-config", action="store_true", help="Print the effective runtime config and exit.")
    operation.add_argument(
        "--create-backup",
        action="store_true",
        help="Create a validated backup of durable operator JSON and retained private Console state.",
    )
    operation.add_argument(
        "--preview-restore",
        action="store_true",
        help="Preview restoring one validated durable-data backup.",
    )
    operation.add_argument(
        "--confirm-restore",
        metavar="TOKEN",
        help="Execute the exact durable-data restore preview identified by TOKEN.",
    )
    parser.add_argument(
        "--restore-backup",
        help="Backup ZIP selected for a restore preview or confirmation.",
    )
    args = parser.parse_args(argv)
    restore_operation = args.preview_restore or args.confirm_restore
    if bool(args.restore_backup) != bool(restore_operation):
        parser.error("--restore-backup is required only with a restore operation")
    return args










def run_backup_restore_cli(
    cli_args: argparse.Namespace,
    config: AppConfig,
) -> tuple[dict, int]:
    """Run one bounded backup or restore CLI operation."""

    if bool(getattr(cli_args, "create_backup", False)):
        result = create_durable_backup(config.data_dir)
        return result.public_summary(), 0 if result.status in {"created", "existing"} else 2

    selected_value = maybe_stripped(getattr(cli_args, "restore_backup", None))
    if selected_value is None:
        return {"status": "blocked", "issues": ["restore_backup_required"]}, 2
    selected = resolve_path(selected_value, base_dir=Path.cwd())
    if bool(getattr(cli_args, "preview_restore", False)):
        preview = preview_durable_restore(config.data_dir, selected)
        return preview.public_summary(), 0 if preview.status in {
            "ready",
            "resume_required",
            "recovery_required",
            "not_required",
        } else 2
    result = restore_durable_backup(
        config.data_dir,
        selected,
        confirmation_token=str(getattr(cli_args, "confirm_restore", "") or ""),
    )
    return result.public_summary(), 0 if result.status in {
        "restored",
        "resumed",
        "recovered",
    } else 2


def load_app_config(cli_args: argparse.Namespace | None = None) -> AppConfig:
    cli_args = cli_args or argparse.Namespace()
    config_doc: dict = {}
    loaded_files: list[Path] = []

    for candidate in (LEGACY_DEFAULT_CONFIG_FILE, DEFAULT_CONFIG_FILE, LEGACY_LOCAL_CONFIG_FILE, LOCAL_CONFIG_FILE):
        if not candidate.exists():
            continue
        config_doc = deep_merge_dicts(config_doc, normalize_config_document(load_toml_file(candidate), candidate))
        resolved = candidate.resolve()
        if resolved not in loaded_files:
            loaded_files.append(resolved)

    extra_config = first_nonempty(getattr(cli_args, "config_path", None), env_value("CONFIG"))
    if extra_config:
        extra_path = resolve_path(extra_config, base_dir=Path.cwd())
        if not extra_path.exists():
            raise FileNotFoundError(f"Mentat config file not found: {extra_path}")
        config_doc = deep_merge_dicts(config_doc, normalize_config_document(load_toml_file(extra_path), extra_path))
        resolved = extra_path.resolve()
        if resolved not in loaded_files:
            loaded_files.append(resolved)

    server_config = config_doc.get("server") if isinstance(config_doc.get("server"), dict) else {}
    paths_config = config_doc.get("paths") if isinstance(config_doc.get("paths"), dict) else {}
    dashboard_config = config_doc.get("dashboard") if isinstance(config_doc.get("dashboard"), dict) else {}

    host = first_nonempty(getattr(cli_args, "host", None), env_value("HOST"), server_config.get("host")) or DEFAULT_HOST
    if host.strip().lower() == "localhost":
        host = DEFAULT_HOST
    port = parse_port(
        first_nonempty(getattr(cli_args, "port", None), env_value("PORT"), server_config.get("port"), DEFAULT_PORT),
        source="Mentat port",
    )
    data_resolution = resolve_data_root(
        cli_value=getattr(cli_args, "data_dir", None),
        environ=os.environ,
        toml_value=paths_config.get("data_dir"),
        base_dir=BASE_DIR,
    )
    data_dir = data_resolution.path
    public_dir = resolve_path(
        first_nonempty(
            getattr(cli_args, "public_dir", None),
            env_value("PUBLIC_DIR"),
            paths_config.get("public_dir"),
            bundled_asset_dir("public"),
        ),
        base_dir=BASE_DIR,
    )
    hermes_home = resolve_path(
        first_nonempty(getattr(cli_args, "hermes_home", None), os.environ.get("HERMES_HOME"), paths_config.get("hermes_home"), default_hermes_home()),
        base_dir=BASE_DIR,
    )
    obsidian_vault = resolve_path(
        first_nonempty(
            getattr(cli_args, "obsidian_vault", None),
            os.environ.get("OBSIDIAN_VAULT_PATH"),
            paths_config.get("obsidian_vault"),
            default_obsidian_vault(),
        ),
        base_dir=BASE_DIR,
    )
    display_name = first_nonempty(
        getattr(cli_args, "display_name", None),
        env_value("DISPLAY_NAME"),
        dashboard_config.get("display_name"),
    )
    greeting_prefix = first_nonempty(
        getattr(cli_args, "greeting_prefix", None),
        env_value("GREETING_PREFIX"),
        dashboard_config.get("greeting_prefix"),
    )
    app_name = first_nonempty(
        getattr(cli_args, "app_name", None),
        env_value("APP_NAME"),
        dashboard_config.get("app_name"),
        DEFAULT_APP_NAME,
    )

    return AppConfig(
        config_files=tuple(loaded_files),
        host=host,
        port=port,
        data_dir=data_dir,
        public_dir=public_dir,
        hermes_home=hermes_home,
        obsidian_vault=obsidian_vault,
        display_name=display_name,
        greeting_prefix=greeting_prefix,
        app_name=app_name,
        data_dir_source=data_resolution.source,
    )
