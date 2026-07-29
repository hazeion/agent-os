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
from data_migration import (
    migrate_legacy_data,
    migration_status_under_lock,
    migration_startup_status,
    preview_legacy_migration,
)
from private_console_migration import (
    migrate_private_console,
    preview_private_console_migration,
)
from private_state import private_control_issue
from data_schema import (
    initialize_fresh_schema_under_lock,
    migrate_data_schema,
    prepare_fresh_schema_initialization,
    preview_schema_migration,
    schema_preflight_status,
    schema_status_under_lock,
)
from data_layout import (
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
    """Initialize the bounded layout or return a secret-free startup error."""

    schema_preflight = schema_preflight_status(config.data_dir)
    if schema_preflight == "newer":
        return (
            "Mentat refuses a data schema newer than this build supports "
            "(schema_version_newer_than_supported). Install a compatible "
            "Mentat version; no downgrade was attempted."
        )
    if schema_preflight == "invalid":
        return (
            "Mentat found incomplete or invalid data schema metadata "
            "(invalid_data_schema). Run the schema migration preview and "
            "confirm any exact recovery plan before startup."
        )

    if restore_startup_status(config.data_dir) != "clear":
        return (
            "Mentat found an incomplete or invalid durable-data restore "
            "(restore_incomplete_or_invalid). Re-run the restore preview with "
            "the selected backup before startup."
        )

    if private_control_issue(config.data_dir) is not None:
        return (
            "Mentat found incomplete or invalid private Console state "
            "(private_console_state_invalid). Re-run the applicable private "
            "migration or restore preview before startup."
        )

    migration_status = migration_startup_status(config.data_dir)
    if migration_status == "invalid":
        return (
            "Mentat found an incomplete or invalid legacy migration "
            "(migration_incomplete_or_invalid). Re-run the migration preview "
            "before startup."
        )

    private_migration = preview_private_console_migration(config.data_dir)
    if private_migration.status not in {"not_required", "already_migrated"}:
        return (
            "Mentat found legacy or incomplete private Console state "
            "(private_console_migration_required). Run the private Console "
            "migration preview and confirm its exact plan before startup."
        )

    def migration_guard(target: Path, descriptor: int | None) -> str | None:
        if restore_status_under_lock(target, descriptor) != "clear":
            return "restore_incomplete_or_invalid"
        locked_status = migration_status_under_lock(target, descriptor)
        if locked_status == "invalid":
            return "migration_incomplete_or_invalid"
        if migration_status == "complete" and locked_status != "complete":
            return "migration_incomplete_or_invalid"
        if private_control_issue(target) is not None:
            return "private_console_state_invalid"
        if preview_private_console_migration(target).status not in {"not_required", "already_migrated"}:
            return "private_console_migration_required"
        locked_schema = schema_status_under_lock(target, descriptor)
        if locked_schema == "newer":
            return "schema_version_newer_than_supported"
        if locked_schema == "invalid":
            return "invalid_data_schema"
        return None

    def schema_prepare(target: Path, descriptor: int | None, plan) -> str | None:
        return prepare_fresh_schema_initialization(
            PACKAGED_SEED_DIR,
            target,
            descriptor,
            plan,
        )

    verified_schema_status: str | None = None
    verified_root_identity: tuple[int, int] | None = None

    def schema_finalize(target: Path, descriptor: int | None, _plan) -> str | None:
        nonlocal verified_root_identity, verified_schema_status
        finalize_issue = initialize_fresh_schema_under_lock(
            PACKAGED_SEED_DIR,
            target,
            descriptor,
        )
        if finalize_issue is not None:
            return finalize_issue
        if restore_status_under_lock(target, descriptor) != "clear":
            return "restore_incomplete_or_invalid"
        if private_control_issue(target) is not None:
            return "private_console_state_invalid"
        if preview_private_console_migration(target).status not in {"not_required", "already_migrated"}:
            return "private_console_migration_required"
        final_migration = migration_status_under_lock(target, descriptor)
        if migration_status == "complete" and final_migration != "complete":
            return "migration_incomplete_or_invalid"
        final_schema = schema_status_under_lock(target, descriptor)
        allowed = (
            {"current"}
            if schema_preflight in {"current", "fresh_incomplete"}
            else {"legacy", "current"}
        )
        if final_schema not in allowed:
            return (
                "schema_version_newer_than_supported"
                if final_schema == "newer"
                else "invalid_data_schema"
            )
        verified_root_identity = _pinned_root_identity(target, descriptor)
        if verified_root_identity is None:
            return "data_root_identity_unverified"
        verified_schema_status = final_schema
        return None

    legacy_root = None
    if (
        migration_status != "complete"
        and config.data_dir_source == "platform_default"
        and DEFAULT_CONFIG_FILE.exists()
    ):
        # A source checkout may have used its tracked data directory as live
        # storage. Selecting the new default must not hide that state behind
        # fresh seeds. Installed distributions do not ship this source-only
        # TOML override and therefore have no implicit legacy checkout root.
        legacy_root = PACKAGED_SEED_DIR
    result = initialize_data_root(
        PACKAGED_SEED_DIR,
        config.data_dir,
        legacy_root=legacy_root,
        locked_guard=migration_guard,
        locked_prepare=schema_prepare,
        locked_finalize=schema_finalize,
    )
    if result.status in {"initialized", "existing", "development_override"}:
        if result.status == "development_override":
            try:
                with _initialization_lock(config.data_dir) as descriptor:
                    locked_restore = restore_status_under_lock(
                        config.data_dir,
                        descriptor,
                    )
                    locked_private = private_control_issue(config.data_dir)
                    locked_private_migration = preview_private_console_migration(
                        config.data_dir
                    ).status
            except OSError:
                locked_restore = "invalid"
                locked_private = "invalid"
                locked_private_migration = "blocked"
            if locked_restore != "clear":
                return (
                    "Mentat found an incomplete or invalid durable-data restore "
                    "(restore_incomplete_or_invalid). Re-run the restore preview with "
                    "the selected backup before startup."
                )
            if locked_private is not None or locked_private_migration not in {
                "not_required", "already_migrated"
            }:
                return (
                    "Mentat found incomplete or legacy private Console state "
                    "(private_console_state_invalid). Re-run the private migration "
                    "or restore preview before startup."
                )
            return None
        try:
            with _initialization_lock(config.data_dir) as descriptor:
                current_identity = _pinned_root_identity(config.data_dir, descriptor)
                restore_status = restore_status_under_lock(
                    config.data_dir,
                    descriptor,
                )
                schema_status = schema_status_under_lock(config.data_dir, descriptor)
                private_status = private_control_issue(config.data_dir)
                private_migration_status = preview_private_console_migration(
                    config.data_dir
                ).status
                final_identity = _pinned_root_identity(config.data_dir, descriptor)
        except OSError:
            current_identity = None
            final_identity = None
            restore_status = "invalid"
            schema_status = "invalid"
            private_status = "invalid"
            private_migration_status = "blocked"
        if restore_status != "clear":
            return (
                "Mentat found an incomplete or invalid durable-data restore "
                "(restore_incomplete_or_invalid). Re-run the restore preview with "
                "the selected backup before startup."
            )
        if private_status is not None or private_migration_status not in {
            "not_required", "already_migrated"
        }:
            return (
                "Mentat found incomplete or legacy private Console state "
                "(private_console_state_invalid). Re-run the private migration "
                "or restore preview before startup."
            )
        if (
            verified_schema_status is None
            or verified_root_identity is None
            or current_identity != verified_root_identity
            or final_identity != verified_root_identity
            or schema_status != verified_schema_status
        ):
            return (
                "Mentat found the selected data root changed after locked verification "
                "(invalid_data_schema). Restore the approved root before startup."
            )
        if schema_status == "newer":
            return (
                "Mentat refuses a data schema newer than this build supports "
                "(schema_version_newer_than_supported). Install a compatible "
                "Mentat version; no downgrade was attempted."
            )
        if schema_status == "invalid":
            return (
                "Mentat found incomplete or invalid data schema metadata "
                "(invalid_data_schema). Run the schema migration preview and "
                "confirm any exact recovery plan before startup."
            )
        return None
    if "schema_version_newer_than_supported" in result.issues:
        return (
            "Mentat refuses a data schema newer than this build supports "
            "(schema_version_newer_than_supported). Install a compatible "
            "Mentat version; no downgrade was attempted."
        )
    if "restore_incomplete_or_invalid" in result.issues:
        return (
            "Mentat found an incomplete or invalid durable-data restore "
            "(restore_incomplete_or_invalid). Re-run the restore preview with "
            "the selected backup before startup."
        )
    if any(issue in result.issues for issue in {
        "private_console_state_invalid", "private_console_migration_required"
    }):
        return (
            "Mentat found incomplete or legacy private Console state "
            "(private_console_state_invalid). Re-run the private migration "
            "or restore preview before startup."
        )
    if "invalid_data_schema" in result.issues:
        return (
            "Mentat found incomplete or invalid data schema metadata "
            "(invalid_data_schema)."
        )
    issue_text = ", ".join(result.issues[:4]) or "initialization_failed"
    return (
        "Mentat could not safely initialize the selected data root "
        f"({issue_text}). Resolve the reported data-layout condition before startup."
    )


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
        "--preview-legacy-migration",
        action="store_true",
        help="Preview the bounded legacy JSON migration and print its confirmation token.",
    )
    operation.add_argument(
        "--confirm-legacy-migration",
        metavar="TOKEN",
        help="Execute the exact legacy migration preview identified by TOKEN.",
    )
    operation.add_argument(
        "--preview-schema-migration",
        action="store_true",
        help="Preview the bounded durable-JSON schema migration.",
    )
    operation.add_argument(
        "--confirm-schema-migration",
        metavar="TOKEN",
        help="Execute the exact data-schema migration preview identified by TOKEN.",
    )
    operation.add_argument(
        "--preview-private-migration",
        action="store_true",
        help="Preview migration of legacy private Agent Console state.",
    )
    operation.add_argument(
        "--confirm-private-migration",
        metavar="TOKEN",
        help="Execute the exact private Console migration preview identified by TOKEN.",
    )
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
        "--legacy-data-dir",
        help="Legacy checkout data directory; valid only with a legacy migration operation.",
    )
    parser.add_argument(
        "--restore-backup",
        help="Backup ZIP selected for a restore preview or confirmation.",
    )
    args = parser.parse_args(argv)
    if args.legacy_data_dir and not (
        args.preview_legacy_migration or args.confirm_legacy_migration
    ):
        parser.error("--legacy-data-dir requires a legacy migration operation")
    restore_operation = args.preview_restore or args.confirm_restore
    if bool(args.restore_backup) != bool(restore_operation):
        parser.error("--restore-backup is required only with a restore operation")
    return args


def run_legacy_migration_cli(
    cli_args: argparse.Namespace,
    config: AppConfig,
) -> tuple[dict, int]:
    """Run one explicit migration CLI operation with bounded JSON output."""

    legacy_value = maybe_stripped(getattr(cli_args, "legacy_data_dir", None))
    legacy_root = (
        resolve_explicit_data_root(legacy_value, base_dir=Path.cwd())
        if legacy_value is not None
        else PACKAGED_SEED_DIR
    )
    if bool(getattr(cli_args, "preview_legacy_migration", False)):
        preview = preview_legacy_migration(
            PACKAGED_SEED_DIR,
            legacy_root,
            config.data_dir,
        )
        summary = preview.public_summary()
        return summary, 0 if preview.status in {
            "ready",
            "resume_required",
            "already_migrated",
            "not_required",
        } else 2

    token = str(getattr(cli_args, "confirm_legacy_migration", "") or "")
    result = migrate_legacy_data(
        PACKAGED_SEED_DIR,
        legacy_root,
        config.data_dir,
        confirmation_token=token,
    )
    summary = result.public_summary()
    return summary, 0 if result.status in {
        "migrated",
        "resumed",
    } else 2


def run_schema_migration_cli(
    cli_args: argparse.Namespace,
    config: AppConfig,
) -> tuple[dict, int]:
    """Run one explicit schema preview or confirmation with bounded output."""

    if bool(getattr(cli_args, "preview_schema_migration", False)):
        preview = preview_schema_migration(PACKAGED_SEED_DIR, config.data_dir)
        summary = preview.public_summary()
        return summary, 0 if preview.status in {
            "ready",
            "resume_required",
            "recovery_required",
            "already_current",
            "development_override",
        } else 2
    token = str(getattr(cli_args, "confirm_schema_migration", "") or "")
    result = migrate_data_schema(
        PACKAGED_SEED_DIR,
        config.data_dir,
        confirmation_token=token,
    )
    summary = result.public_summary()
    return summary, 0 if result.status in {"migrated", "resumed", "reconciled"} else 2


def run_private_console_migration_cli(
    cli_args: argparse.Namespace,
    config: AppConfig,
) -> tuple[dict, int]:
    if bool(getattr(cli_args, "preview_private_migration", False)):
        preview = preview_private_console_migration(config.data_dir)
        summary = preview.public_summary()
        return summary, 0 if preview.status in {
            "ready", "resume_required", "already_migrated", "not_required"
        } else 2
    result = migrate_private_console(
        config.data_dir,
        confirmation_token=str(getattr(cli_args, "confirm_private_migration", "") or ""),
    )
    summary = result.public_summary()
    return summary, 0 if result.status in {"migrated", "resumed"} else 2


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
