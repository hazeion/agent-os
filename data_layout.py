"""Read-only data-root resolution and initialization preflight.

This module deliberately does not create directories, copy seeds, change
permissions, migrate data, or expose file contents. Writable data-root behavior
belongs to a later reviewed slice.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path, PureWindowsPath
import stat
import sys
from typing import Mapping, Sequence


SEED_FILE_NAMES = (
    "agent_messages.json",
    "agents.json",
    "attention.json",
    "calendar.json",
    "context_packs.json",
    "dashboard.json",
    "email.json",
    "projects.json",
    "tasks.json",
)

DATA_ROOT_SOURCES = {
    "cli",
    "environment",
    "legacy_environment",
    "toml",
    "platform_default",
}

MAX_PREFLIGHT_JSON_BYTES = 16 * 1024 * 1024
SEED_ROOT_TYPES = {
    name: dict if name == "dashboard.json" else list for name in SEED_FILE_NAMES
}
_DARWIN_TRUSTED_ALIASES = (Path("/var"), Path("/tmp"), Path("/etc"))


@dataclass(frozen=True)
class DataRootResolution:
    path: Path
    source: str

    def __post_init__(self) -> None:
        if self.source not in DATA_ROOT_SOURCES:
            raise ValueError("Unsupported data-root source.")


@dataclass(frozen=True)
class PreflightItem:
    name: str
    status: str

    def public_summary(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status}


@dataclass(frozen=True)
class DataRootPreflight:
    status: str
    items: tuple[PreflightItem, ...]
    issues: tuple[str, ...] = ()

    def public_summary(self) -> dict:
        return {
            "status": self.status,
            "items": [item.public_summary() for item in self.items],
            "issues": list(self.issues),
        }


def _nonempty(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _absolute_without_following(path: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if sys.platform != "darwin":
        return absolute
    for alias in _DARWIN_TRUSTED_ALIASES:
        try:
            relative = absolute.relative_to(alias)
        except ValueError:
            continue
        if not alias.is_symlink():
            continue
        return alias.resolve(strict=True) / relative
    return absolute


def resolve_platform_data_root(
    *,
    platform_name: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the approved platform default without creating it."""

    platform_value = (platform_name or sys.platform).lower()
    environment = os.environ if environ is None else environ
    home_path = Path.home() if home is None else Path(home)

    if platform_value == "darwin":
        return home_path / "Library" / "Application Support" / "Mentat"

    if platform_value.startswith("win"):
        local_app_data = _nonempty(environment.get("LOCALAPPDATA"))
        if local_app_data is None or not PureWindowsPath(local_app_data).is_absolute():
            raise ValueError("Windows LOCALAPPDATA must be an absolute path.")
        return Path(str(PureWindowsPath(local_app_data) / "Mentat"))

    if platform_value.startswith("linux"):
        xdg_data_home = _nonempty(environment.get("XDG_DATA_HOME"))
        if xdg_data_home is not None and Path(xdg_data_home).is_absolute():
            return Path(xdg_data_home) / "Mentat"
        return home_path / ".local" / "share" / "Mentat"

    raise ValueError("Mentat has no approved data-root default for this platform.")


def resolve_explicit_data_root(value: str | Path, *, base_dir: Path) -> Path:
    """Make a data-root input absolute without following its final symlink."""

    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    path = Path(expanded)
    if not path.is_absolute():
        path = Path(base_dir) / path
    return _absolute_without_following(path)


def resolve_data_root(
    *,
    cli_value: str | Path | None,
    environ: Mapping[str, str] | None,
    toml_value: str | Path | None,
    base_dir: Path,
    platform_name: str | None = None,
    home: Path | None = None,
) -> DataRootResolution:
    """Resolve the data root with the approved app-specific precedence."""

    environment = os.environ if environ is None else environ
    candidates = (
        (cli_value, "cli"),
        (environment.get("MENTAT_DATA_DIR"), "environment"),
        (environment.get("AGENT_OS_DATA_DIR"), "legacy_environment"),
        (toml_value, "toml"),
    )
    for value, source in candidates:
        normalized = _nonempty(value)
        if normalized is not None:
            return DataRootResolution(
                path=resolve_explicit_data_root(normalized, base_dir=base_dir),
                source=source,
            )

    default_path = resolve_platform_data_root(
        platform_name=platform_name,
        environ=environment,
        home=home,
    )
    return DataRootResolution(path=default_path, source="platform_default")


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.fspath(_absolute_without_following(left))) == os.path.normcase(
        os.fspath(_absolute_without_following(right))
    )


def _root_is_too_broad(path: Path, home: Path | None) -> bool:
    absolute = _absolute_without_following(path)
    anchor = Path(absolute.anchor) if absolute.anchor else None
    if anchor is not None and _same_path(absolute, anchor):
        return True
    return home is not None and _same_path(absolute, Path(home))


def _is_redirecting_entry(metadata: os.stat_result) -> bool:
    if stat.S_ISLNK(metadata.st_mode):
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)


def _redirected_component_issue(path: Path, label: str) -> str | None:
    absolute = _absolute_without_following(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            return None
        except OSError:
            return f"{label}_unreadable"
        if _is_redirecting_entry(metadata):
            return f"{label}_symlink"
    return None


def _root_issue(path: Path, label: str, *, allow_missing: bool) -> str | None:
    redirect_issue = _redirected_component_issue(path, label)
    if redirect_issue is not None:
        return redirect_issue
    if not path.exists():
        return None if allow_missing else f"{label}_missing"
    if not path.is_dir():
        return f"{label}_not_directory"
    return None


def _open_readonly_no_follow(path: Path) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    can_walk = bool(no_follow and directory and os.open in os.supports_dir_fd)
    if not can_walk:
        return os.open(path, flags | no_follow)

    absolute = _absolute_without_following(path)
    directory_fd = os.open(absolute.anchor, flags | directory)
    try:
        for part in absolute.parts[1:-1]:
            next_fd = os.open(
                part,
                flags | directory | no_follow,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        return os.open(absolute.name, flags | no_follow, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)


def _read_bounded_json(path: Path):
    descriptor = _open_readonly_no_follow(path)
    try:
        metadata = os.fstat(descriptor)
        if _is_redirecting_entry(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise TypeError("not_regular")
        if metadata.st_size > MAX_PREFLIGHT_JSON_BYTES:
            raise OverflowError("too_large")
        chunks: list[bytes] = []
        remaining = MAX_PREFLIGHT_JSON_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_PREFLIGHT_JSON_BYTES:
            raise OverflowError("too_large")
        return json.loads(raw.decode("utf-8"))
    finally:
        os.close(descriptor)


def _json_file_state(
    path: Path,
    label: str,
    name: str,
    *,
    required: bool,
) -> tuple[bool, str | None]:
    redirect_issue = _redirected_component_issue(path, label)
    if redirect_issue is not None:
        return False, f"{redirect_issue}:{name}"
    if not path.exists():
        issue = f"{label}_missing:{name}" if required else None
        return False, issue
    try:
        metadata = os.lstat(path)
    except OSError:
        return False, f"{label}_unreadable:{name}"
    if not stat.S_ISREG(metadata.st_mode):
        return False, f"{label}_not_regular:{name}"
    try:
        document = _read_bounded_json(path)
    except TypeError:
        return False, f"{label}_not_regular:{name}"
    except OverflowError:
        return False, f"{label}_too_large:{name}"
    except (OSError, UnicodeError, ValueError, RecursionError, MemoryError):
        return False, f"{label}_invalid_json:{name}"
    if type(document) is not SEED_ROOT_TYPES[name]:
        return False, f"{label}_invalid_shape:{name}"
    return True, None


def _blocked_items(seed_names: Sequence[str]) -> tuple[PreflightItem, ...]:
    return tuple(PreflightItem(name=name, status="blocked") for name in seed_names)


def preflight_data_root(
    seed_root: Path,
    data_root: Path,
    *,
    legacy_root: Path | None = None,
    home: Path | None = None,
    seed_names: Sequence[str] = SEED_FILE_NAMES,
) -> DataRootPreflight:
    """Inspect known data surfaces and return a bounded, read-only plan."""

    names = tuple(seed_names)
    if names != SEED_FILE_NAMES:
        return DataRootPreflight(
            status="unsafe",
            items=_blocked_items(names),
            issues=("unsupported_seed_inventory",),
        )

    seeds = _absolute_without_following(Path(seed_root))
    target = _absolute_without_following(Path(data_root))
    legacy = _absolute_without_following(Path(legacy_root)) if legacy_root is not None else None
    home_path = _absolute_without_following(Path(home)) if home is not None else Path.home()

    if _root_is_too_broad(target, home_path):
        return DataRootPreflight(
            status="unsafe",
            items=_blocked_items(names),
            issues=("data_root_too_broad",),
        )

    issues: list[str] = []
    seed_root_issue = _root_issue(seeds, "seed_root", allow_missing=False)
    if seed_root_issue is not None:
        issues.append(seed_root_issue)
    else:
        for name in names:
            _present, issue = _json_file_state(seeds / name, "seed", name, required=True)
            if issue is not None:
                issues.append(issue)
    if issues:
        return DataRootPreflight("unsafe", _blocked_items(names), tuple(issues))

    if _same_path(seeds, target):
        return DataRootPreflight(
            status="development_override",
            items=tuple(PreflightItem(name=name, status="development") for name in names),
        )

    target_root_issue = _root_issue(target, "target_root", allow_missing=True)
    if target_root_issue is not None:
        return DataRootPreflight("unsafe", _blocked_items(names), (target_root_issue,))

    target_names: set[str] = set()
    if target.exists():
        for name in names:
            present, issue = _json_file_state(
                target / name,
                "target",
                name,
                required=False,
            )
            if issue is not None:
                issues.append(issue)
            elif present:
                target_names.add(name)
    if issues:
        return DataRootPreflight("unsafe", _blocked_items(names), tuple(issues))

    legacy_names: set[str] = set()
    if legacy is not None:
        if _same_path(legacy, target):
            return DataRootPreflight(
                "unsafe",
                _blocked_items(names),
                ("legacy_root_matches_target",),
            )
        legacy_root_issue = _root_issue(legacy, "legacy_root", allow_missing=True)
        if legacy_root_issue is not None:
            return DataRootPreflight("unsafe", _blocked_items(names), (legacy_root_issue,))
        if legacy.exists():
            for name in names:
                present, issue = _json_file_state(
                    legacy / name,
                    "legacy",
                    name,
                    required=False,
                )
                if issue is not None:
                    issues.append(issue)
                elif present:
                    legacy_names.add(name)
    if issues:
        return DataRootPreflight("unsafe", _blocked_items(names), tuple(issues))

    if legacy_names and target_names:
        return DataRootPreflight(
            status="conflict",
            items=tuple(PreflightItem(name=name, status="conflict") for name in names),
            issues=("legacy_destination_conflict",),
        )

    if legacy_names:
        return DataRootPreflight(
            status="migration_required",
            items=tuple(
                PreflightItem(name=name, status="migrate" if name in legacy_names else "reserved")
                for name in names
            ),
        )

    items = tuple(
        PreflightItem(name=name, status="existing" if name in target_names else "initialize")
        for name in names
    )
    status = "existing" if len(target_names) == len(names) else "ready"
    return DataRootPreflight(status=status, items=items)
