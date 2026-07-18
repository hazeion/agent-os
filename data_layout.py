"""Resolve, inspect, and safely initialize Mentat's bounded data root.

Initialization is deliberately limited to owner-only directory creation and
missing-only copies of the fixed packaged seed inventory. Migration, schema
evolution, backup, restore, and private/runtime data moves remain separate
reviewed capabilities.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import sys
import time
from typing import Mapping, Sequence
import unicodedata
from uuid import uuid4


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
DATA_ROOT_DIRECTORY_NAMES = ("private", "runtime", "backups", "cache", "logs", "config")
INITIALIZATION_LOCK_NAME = ".mentat-initialization.lock"
INITIALIZATION_LOCK_TIMEOUT_SECONDS = 120.0
INITIALIZATION_LOCK_POLL_SECONDS = 0.1
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


@dataclass(frozen=True)
class DataRootInitialization:
    status: str
    items: tuple[PreflightItem, ...]
    issues: tuple[str, ...] = ()

    def public_summary(self) -> dict:
        return {
            "status": self.status,
            "items": [item.public_summary() for item in self.items],
            "issues": list(self.issues),
        }


class _DestinationExistsError(Exception):
    pass


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
        if xdg_data_home is not None and PurePosixPath(xdg_data_home).is_absolute():
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
    left_path = _absolute_without_following(left)
    right_path = _absolute_without_following(right)
    if (
        left_path.exists()
        and right_path.exists()
        and _redirected_component_issue(left_path, "comparison") is None
        and _redirected_component_issue(right_path, "comparison") is None
    ):
        try:
            if os.path.samefile(left_path, right_path):
                return True
        except OSError:
            pass
    return _native_path_comparison_key(left_path) == _native_path_comparison_key(
        right_path
    )


def _native_path_comparison_key(path: Path) -> str:
    """Return native lexical equality without inventing filesystem identity."""

    return os.path.normcase(os.fspath(_absolute_without_following(path)))


def _path_comparison_key(path: Path) -> str:
    key = _native_path_comparison_key(path)
    # Most macOS operator volumes are case-insensitive even though POSIX
    # normcase is a no-op. Conservative Unicode normalization and folding keep
    # case/canonical aliases in the unsafe-overlap path. This key must never be
    # used to establish exact development identity: distinct paths on a
    # case-sensitive macOS volume may intentionally compare equal here.
    return unicodedata.normalize("NFC", key).casefold() if sys.platform == "darwin" else key


def _existing_ancestor_states(path: Path) -> tuple[tuple[Path, tuple[str, ...]], ...]:
    current = _absolute_without_following(path)
    missing_parts: list[str] = []
    states: list[tuple[Path, tuple[str, ...]]] = []
    while True:
        if (
            current.exists()
            and _redirected_component_issue(current, "comparison") is None
        ):
            states.append((current, tuple(reversed(missing_parts))))
        parent = current.parent
        if parent == current:
            break
        missing_parts.append(current.name)
        current = parent
    return tuple(states)


def _component_comparison_key(component: str) -> str:
    if sys.platform == "darwin":
        return unicodedata.normalize("NFC", component).casefold()
    return os.path.normcase(component)


def _components_start_with(parts: tuple[str, ...], prefix: tuple[str, ...]) -> bool:
    if len(prefix) > len(parts):
        return False
    return all(
        _component_comparison_key(part) == _component_comparison_key(expected)
        for part, expected in zip(parts, prefix)
    )


def _path_contains(parent: Path, child: Path) -> bool:
    try:
        Path(_path_comparison_key(child)).relative_to(Path(_path_comparison_key(parent)))
        return True
    except ValueError:
        pass

    for parent_ancestor, parent_suffix in _existing_ancestor_states(parent):
        for child_ancestor, child_suffix in _existing_ancestor_states(child):
            try:
                same_ancestor = os.path.samefile(parent_ancestor, child_ancestor)
            except OSError:
                same_ancestor = False
            if same_ancestor and _components_start_with(child_suffix, parent_suffix):
                return True
    return False


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


def _windows_kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _windows_open_handle(
    path: Path,
    *,
    directory: bool,
    disposition: int = 3,
    writable: bool = False,
) -> int:
    """Open one Windows entry without following its final reparse point."""

    import ctypes
    from ctypes import wintypes

    class FileAttributeTagInfo(ctypes.Structure):
        _fields_ = (("file_attributes", wintypes.DWORD), ("reparse_tag", wintypes.DWORD))

    generic_read = 0x80000000
    generic_write = 0x40000000
    file_traverse = 0x00000020
    file_read_attributes = 0x00000080
    file_share_read = 0x00000001
    file_share_write = 0x00000002
    file_attribute_normal = 0x00000080
    file_attribute_directory = 0x00000010
    file_attribute_reparse_point = 0x00000400
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000
    invalid_handle = wintypes.HANDLE(-1).value
    desired_access = (generic_read | generic_write) if writable else file_read_attributes
    flags = file_flag_open_reparse_point
    if directory:
        # Metadata-only directory handles did not prevent a POSIX-style rename
        # on current hosted Windows. FILE_TRAVERSE establishes ordinary access
        # whose missing FILE_SHARE_DELETE permission is enforced, while avoiding
        # the FILE_LIST_DIRECTORY permission included by GENERIC_READ.
        desired_access = file_traverse | file_read_attributes
        flags |= file_flag_backup_semantics
    else:
        flags |= file_attribute_normal
        if not writable:
            desired_access = generic_read
    kernel32 = _windows_kernel32()
    handle = kernel32.CreateFileW(
        os.fspath(path),
        desired_access,
        file_share_read | file_share_write,
        None,
        disposition,
        flags,
        None,
    )
    if handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    handle_value = int(handle)
    info = FileAttributeTagInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        9,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise ctypes.WinError(error)
    is_directory = bool(info.file_attributes & file_attribute_directory)
    if bool(info.file_attributes & file_attribute_reparse_point) or is_directory != directory:
        kernel32.CloseHandle(handle)
        raise OSError("unsafe Windows file type or reparse point")
    return handle_value


def _windows_close_handle(handle: int) -> None:
    from ctypes import wintypes

    _windows_kernel32().CloseHandle(wintypes.HANDLE(handle))


def _windows_open_directory_chain(path: Path) -> list[int]:
    """Pin every existing component and deny rename/delete while held."""

    absolute = _absolute_without_following(path)
    anchor = Path(absolute.anchor)
    current = anchor
    candidates = [anchor]
    for part in absolute.parts[1:]:
        current /= part
        candidates.append(current)
    handles: list[int] = []
    try:
        for candidate in candidates:
            handles.append(_windows_open_handle(candidate, directory=True))
        return handles
    except Exception:
        for handle in reversed(handles):
            _windows_close_handle(handle)
        raise


@contextmanager
def _windows_input_root_guards(seed_root: Path, legacy_root: Path | None):
    """Pin Windows read roots across preflight, reads, and verification."""

    handles: list[int] = []
    if os.name != "nt":
        yield
        return
    roots = [seed_root]
    if legacy_root is not None and legacy_root.exists() and not _same_path(
        seed_root,
        legacy_root,
    ):
        roots.append(legacy_root)
    try:
        for root in roots:
            handles.extend(_windows_open_directory_chain(root))
        yield
    finally:
        for handle in reversed(handles):
            _windows_close_handle(handle)


def _windows_open_file_descriptor(
    path: Path,
    *,
    disposition: int,
    writable: bool,
) -> int:
    import msvcrt

    handle = _windows_open_handle(
        path,
        directory=False,
        disposition=disposition,
        writable=writable,
    )
    flags = (os.O_RDWR if writable else os.O_RDONLY) | getattr(os, "O_BINARY", 0)
    try:
        return msvcrt.open_osfhandle(handle, flags)
    except Exception:
        _windows_close_handle(handle)
        raise


def _open_readonly_no_follow(path: Path) -> int:
    if os.name == "nt":
        return _windows_open_file_descriptor(path, disposition=3, writable=False)

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


def _open_directory_no_follow(path: Path) -> int:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    can_walk = bool(no_follow and directory and os.open in os.supports_dir_fd)
    if not can_walk:
        return os.open(path, flags)

    absolute = _absolute_without_following(path)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


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
    if _path_contains(seeds, target) or _path_contains(target, seeds):
        return DataRootPreflight(
            status="unsafe",
            items=_blocked_items(names),
            issues=("data_root_overlaps_seed_root",),
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


def _initialization_blocked(
    preflight: DataRootPreflight,
    *,
    issue: str | None = None,
    items: tuple[PreflightItem, ...] | None = None,
) -> DataRootInitialization:
    issues = [preflight.status]
    issues.extend(preflight.issues)
    if issue is not None:
        issues.append(issue)
    return DataRootInitialization(
        status="blocked",
        items=items or _blocked_items(SEED_FILE_NAMES),
        issues=tuple(dict.fromkeys(issues)),
    )


def _secure_directory(path: Path) -> bool:
    """Create/harden one Mentat-owned directory and verify its final type/mode."""

    absolute = _absolute_without_following(path)
    if os.name == "nt":
        guards: list[int] = []
        final_handle = -1
        try:
            if not absolute.parent.exists() and not _secure_directory(absolute.parent):
                return False
            guards = _windows_open_directory_chain(absolute.parent)
            try:
                os.mkdir(absolute, mode=0o700)
            except FileExistsError:
                pass
            final_handle = _windows_open_handle(absolute, directory=True)
            return True
        except OSError:
            return False
        finally:
            if final_handle >= 0:
                _windows_close_handle(final_handle)
            for handle in reversed(guards):
                _windows_close_handle(handle)

    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    can_walk = bool(
        os.name == "posix"
        and no_follow
        and directory
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
    )
    if can_walk:
        flags = os.O_RDONLY | directory | no_follow | getattr(os, "O_CLOEXEC", 0)
        descriptor = -1
        try:
            descriptor = os.open(absolute.anchor, flags)
            parts = absolute.parts[1:]
            for index, part in enumerate(parts):
                try:
                    next_descriptor = os.open(part, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    next_descriptor = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
                metadata = os.fstat(descriptor)
                if _is_redirecting_entry(metadata) or not stat.S_ISDIR(metadata.st_mode):
                    return False
                if index == len(parts) - 1:
                    os.fchmod(descriptor, 0o700)
                    metadata = os.fstat(descriptor)
                    if stat.S_IMODE(metadata.st_mode) != 0o700:
                        return False
            return bool(parts)
        except OSError:
            return False
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    try:
        absolute.mkdir(parents=True, mode=0o700, exist_ok=True)
        redirect_issue = _redirected_component_issue(absolute, "directory")
        if redirect_issue is not None:
            return False
        metadata = os.lstat(absolute)
        if _is_redirecting_entry(metadata) or not stat.S_ISDIR(metadata.st_mode):
            return False
        if os.name == "posix":
            os.chmod(absolute, 0o700, follow_symlinks=False)
            metadata = os.lstat(absolute)
            if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o700:
                return False
        return True
    except (OSError, TypeError):
        return False


def _secure_regular_descriptor(
    descriptor: int,
    mode: int,
    *,
    require_single_link: bool = False,
    require_current_owner: bool = False,
) -> bool:
    try:
        metadata = os.fstat(descriptor)
        if _is_redirecting_entry(metadata) or not stat.S_ISREG(metadata.st_mode):
            return False
        if require_single_link and metadata.st_nlink != 1:
            return False
        if (
            require_current_owner
            and os.name == "posix"
            and hasattr(os, "geteuid")
            and metadata.st_uid != os.geteuid()
        ):
            return False
        if os.name == "posix":
            os.fchmod(descriptor, mode)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != mode:
                return False
        return True
    except OSError:
        return False


def _lock_windows_descriptor(
    descriptor: int,
    *,
    timeout: float = INITIALIZATION_LOCK_TIMEOUT_SECONDS,
    poll: float = INITIALIZATION_LOCK_POLL_SECONDS,
) -> None:
    import msvcrt

    if os.fstat(descriptor).st_size == 0:
        os.write(descriptor, b"\0")
        os.fsync(descriptor)
    deadline = time.monotonic() + timeout
    while True:
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(poll)


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        _lock_windows_descriptor(descriptor)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_EX)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def _initialization_lock(data_root: Path):
    lock_path = data_root / INITIALIZATION_LOCK_NAME
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    use_dir_fd = bool(
        getattr(os, "O_NOFOLLOW", 0)
        and getattr(os, "O_DIRECTORY", 0)
        and os.open in os.supports_dir_fd
    )
    root_descriptor = -1
    descriptor = -1
    windows_guards: list[int] = []
    for attempt in range(3):
        try:
            if os.name == "nt":
                windows_guards = _windows_open_directory_chain(data_root)
                descriptor = _windows_open_file_descriptor(
                    lock_path,
                    disposition=4,
                    writable=True,
                )
            elif _redirected_component_issue(lock_path, "initialization_lock") is not None:
                raise OSError("unsafe initialization lock")
            elif use_dir_fd:
                root_descriptor = _open_directory_no_follow(data_root)
                descriptor = os.open(
                    INITIALIZATION_LOCK_NAME,
                    flags,
                    0o600,
                    dir_fd=root_descriptor,
                )
            else:
                descriptor = os.open(lock_path, flags, 0o600)
            break
        except FileNotFoundError:
            if root_descriptor >= 0:
                os.close(root_descriptor)
                root_descriptor = -1
            for handle in reversed(windows_guards):
                _windows_close_handle(handle)
            windows_guards = []
            if attempt == 2:
                raise
        except Exception:
            if root_descriptor >= 0:
                os.close(root_descriptor)
            for handle in reversed(windows_guards):
                _windows_close_handle(handle)
            raise
    locked = False
    try:
        if not _secure_regular_descriptor(
            descriptor,
            0o600,
            require_single_link=True,
            require_current_owner=True,
        ):
            raise OSError("initialization lock permissions could not be verified")
        _lock_descriptor(descriptor)
        locked = True
        yield root_descriptor if use_dir_fd else None
    finally:
        if locked:
            _unlock_descriptor(descriptor)
        os.close(descriptor)
        if root_descriptor >= 0:
            os.close(root_descriptor)
        for handle in reversed(windows_guards):
            _windows_close_handle(handle)


def _read_validated_seed_bytes(path: Path, name: str) -> bytes:
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
        document = json.loads(raw.decode("utf-8"))
        if type(document) is not SEED_ROOT_TYPES[name]:
            raise ValueError("invalid_shape")
        return raw
    finally:
        os.close(descriptor)


def _temporary_seed_path(destination: Path) -> Path:
    return destination.parent / f".{destination.name}.mentat-init-{uuid4().hex}.tmp"


def _write_seed_temporary(path: Path, raw: bytes, *, data_root_fd: int | None = None) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    if os.name == "nt":
        descriptor = _windows_open_file_descriptor(path, disposition=1, writable=True)
    elif data_root_fd is None:
        descriptor = os.open(path, flags, 0o600)
    else:
        descriptor = os.open(path.name, flags, 0o600, dir_fd=data_root_fd)
    try:
        if not _secure_regular_descriptor(
            descriptor,
            0o600,
            require_single_link=True,
            require_current_owner=True,
        ):
            raise OSError("temporary seed permissions could not be verified")
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise OSError("temporary seed write did not progress")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _promote_seed_copy(
    temp_path: Path,
    destination: Path,
    *,
    data_root_fd: int | None = None,
) -> None:
    """Atomically publish a same-directory copy without replacement."""

    try:
        if data_root_fd is not None and os.link in os.supports_dir_fd:
            os.link(
                temp_path.name,
                destination.name,
                src_dir_fd=data_root_fd,
                dst_dir_fd=data_root_fd,
                follow_symlinks=False,
            )
        else:
            os.link(temp_path, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise _DestinationExistsError from exc


def _copy_seed_missing_only(
    seed: Path,
    destination: Path,
    name: str,
    *,
    data_root_fd: int | None = None,
) -> str | None:
    temp_path = _temporary_seed_path(destination)
    try:
        raw = _read_validated_seed_bytes(seed, name)
        _write_seed_temporary(temp_path, raw, data_root_fd=data_root_fd)
        _promote_seed_copy(temp_path, destination, data_root_fd=data_root_fd)
        if data_root_fd is not None:
            os.fsync(data_root_fd)
        present, issue = _json_file_state(destination, "target", name, required=True)
        if not present or issue is not None:
            return f"destination_verification_failed:{name}"
        if _read_validated_seed_bytes(destination, name) != raw:
            return f"destination_verification_failed:{name}"
        if os.name == "posix" and stat.S_IMODE(destination.stat().st_mode) != 0o600:
            return f"destination_permissions_unverified:{name}"
        return None
    except _DestinationExistsError:
        return f"destination_exists:{name}"
    except (
        OSError,
        TypeError,
        OverflowError,
        UnicodeError,
        ValueError,
        RecursionError,
        MemoryError,
        NotImplementedError,
    ):
        return f"seed_copy_failed:{name}"
    finally:
        try:
            if data_root_fd is not None and os.unlink in os.supports_dir_fd:
                os.unlink(temp_path.name, dir_fd=data_root_fd)
            else:
                temp_path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def initialize_data_root(
    seed_root: Path,
    data_root: Path,
    *,
    legacy_root: Path | None = None,
    home: Path | None = None,
) -> DataRootInitialization:
    """Create the private layout while holding any required input guards."""

    seeds = _absolute_without_following(Path(seed_root))
    target = _absolute_without_following(Path(data_root))
    legacy = _absolute_without_following(Path(legacy_root)) if legacy_root is not None else None
    try:
        with _windows_input_root_guards(seeds, legacy):
            return _initialize_data_root_guarded(
                seeds,
                target,
                legacy_root=legacy,
                home=home,
            )
    except OSError:
        failed = DataRootPreflight(
            status="unsafe",
            items=_blocked_items(SEED_FILE_NAMES),
            issues=("input_root_guard_failed",),
        )
        return _initialization_blocked(failed)


def _initialize_data_root_guarded(
    seed_root: Path,
    data_root: Path,
    *,
    legacy_root: Path | None = None,
    home: Path | None = None,
) -> DataRootInitialization:
    """Create the layout after platform input-root guards are established."""

    seeds = _absolute_without_following(Path(seed_root))
    target = _absolute_without_following(Path(data_root))
    legacy = _absolute_without_following(Path(legacy_root)) if legacy_root is not None else None
    initial = preflight_data_root(seeds, target, legacy_root=legacy, home=home)
    if initial.status == "development_override":
        return DataRootInitialization(initial.status, initial.items)
    if initial.status not in {"ready", "existing"}:
        return _initialization_blocked(initial)

    if not _secure_directory(target):
        return _initialization_blocked(initial, issue="directory_permissions_unverified")

    try:
        with _initialization_lock(target) as data_root_fd:
            current = preflight_data_root(seeds, target, legacy_root=legacy, home=home)
            if current.status not in {"ready", "existing"}:
                return _initialization_blocked(current)

            for name in DATA_ROOT_DIRECTORY_NAMES:
                if not _secure_directory(target / name):
                    return _initialization_blocked(
                        current,
                        issue="directory_permissions_unverified",
                    )

            result_items: list[PreflightItem] = []
            copied_any = False
            for item in current.items:
                if item.status == "existing":
                    result_items.append(PreflightItem(item.name, "existing"))
                    continue
                if item.status != "initialize":
                    return _initialization_blocked(
                        current,
                        issue=f"unexpected_plan_item:{item.name}",
                        items=tuple(result_items) + _blocked_items(SEED_FILE_NAMES[len(result_items):]),
                    )
                issue = _copy_seed_missing_only(
                    seeds / item.name,
                    target / item.name,
                    item.name,
                    data_root_fd=data_root_fd,
                )
                if issue is not None:
                    return _initialization_blocked(
                        current,
                        issue=issue,
                        items=tuple(result_items)
                        + (PreflightItem(item.name, "blocked"),)
                        + _blocked_items(SEED_FILE_NAMES[len(result_items) + 1 :]),
                    )
                copied_any = True
                result_items.append(PreflightItem(item.name, "initialized"))

            final = preflight_data_root(seeds, target, legacy_root=legacy, home=home)
            if final.status != "existing":
                return _initialization_blocked(
                    final,
                    issue="final_verification_failed",
                    items=tuple(result_items),
                )
            return DataRootInitialization(
                status="initialized" if copied_any else "existing",
                items=tuple(result_items),
            )
    except OSError:
        return _initialization_blocked(initial, issue="initialization_lock_failed")
