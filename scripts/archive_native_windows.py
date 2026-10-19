#!/usr/bin/env python3
"""Archive only the exact public Windows COLLECT output before installer smoke."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mentat.package_data import PUBLIC_DATA_FILES

_PRIVATE_NAMES = frozenset({
    "mentat.local.toml", "mentat.local.env", "secrets.json", "credentials.json",
    "google_token.json", "mentat.sqlite3", "agent-registry.sqlite3",
    "server-state.json", "agent-console-runs.json", ".hermes", ".codex",
})
INVENTORY_NAME = "mentat-windows-x64-bundle-inventory.json"
MAX_INVENTORY_BYTES = 16 * 1024 * 1024
MAX_INVENTORY_FILES = 50_000


def _regular(path: Path, *, directory: bool = False) -> bool:
    details = path.lstat()
    return (
        not stat.S_ISLNK(details.st_mode)
        and not getattr(details, "st_file_attributes", 0) & 0x400
        and (stat.S_ISDIR(details.st_mode) if directory else stat.S_ISREG(details.st_mode))
    )


def _validate_names(names: set[str]) -> None:
    if not 1 <= len(names) <= MAX_INVENTORY_FILES or len({name.casefold() for name in names}) != len(names):
        raise ValueError("native COLLECT inventory is invalid")
    for name in names:
        parts = PurePosixPath(name).parts
        if (
            not parts or PurePosixPath(name).is_absolute() or ":" in name or "\\" in name
            or any(part in {".", ".."} for part in parts)
            or PurePosixPath(name).as_posix() != name
            or any(part.lower().startswith(".env") or part.lower().endswith(".secret")
                   or part.lower() in _PRIVATE_NAMES for part in parts)
            or (parts[0] != "_internal" and name not in {"mentat.exe", "Mentat Launcher.exe"})
        ):
            raise ValueError("native COLLECT inventory path is unsafe")
    if not {"mentat.exe", "Mentat Launcher.exe", "_internal/web/server.js"} <= names:
        raise ValueError("native COLLECT inventory is incomplete")
    for surface in ("data", "public"):
        prefix = f"_internal/{surface}/"
        expected = {prefix + Path(name).name for name in PUBLIC_DATA_FILES[f"share/mentat/{surface}"]}
        if {name for name in names if name.startswith(prefix)} != expected:
            raise ValueError("native public payload inventory is invalid")


def _bundle_files(bundle: Path, names: set[str]) -> dict[str, Path]:
    if not _regular(bundle.parent, directory=True) or not _regular(bundle, directory=True):
        raise ValueError("native bundle root is unsafe")
    directories = {parent.as_posix() for name in names for parent in PurePosixPath(name).parents if parent != PurePosixPath(".")}
    files: dict[str, Path] = {}
    pending = [bundle]
    while pending:
        for path in sorted(pending.pop().iterdir()):
            name = path.relative_to(bundle).as_posix()
            # Never recurse through an unlisted directory or read an unlisted
            # file. Intended membership comes from COLLECT, not this walk.
            if name not in names and name not in directories:
                raise ValueError("native bundle contains an unlisted entry")
            details = path.lstat()
            if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
                raise ValueError("native bundle contains an unsafe entry")
            if stat.S_ISDIR(details.st_mode) and name in directories:
                pending.append(path)
            elif stat.S_ISREG(details.st_mode) and details.st_nlink == 1 and name in names:
                files[name] = path
            else:
                raise ValueError("native bundle contains an unsafe entry")
    if set(files) != names:
        raise ValueError("native bundle differs from COLLECT inventory")
    return files


def _hash_file(path: Path) -> str:
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256")
    return digest.hexdigest()


def write_windows_bundle_inventory(bundle: Path, toc, contents_directory: str) -> Path:
    """Seal only destinations explicitly selected by the trusted Windows spec."""

    if contents_directory != "_internal":
        raise ValueError("native contents directory is unsupported")
    names: list[str] = []
    for destination, _source, kind in toc:
        if kind not in {"EXECUTABLE", "DATA", "BINARY", "EXTENSION"}:
            raise ValueError("native COLLECT entry type is unsupported")
        relative = str(destination).replace("\\", "/")
        names.append(relative if kind == "EXECUTABLE" else f"_internal/{relative}")
    if len(set(names)) != len(names):
        raise ValueError("native COLLECT destinations are duplicated")
    _validate_names(set(names))
    files = _bundle_files(bundle, set(names))
    encoded = json.dumps({"schema": 1, "files": {name: _hash_file(files[name]) for name in sorted(names)}}, sort_keys=True).encode()
    if len(encoded) > MAX_INVENTORY_BYTES:
        raise ValueError("native COLLECT inventory exceeds its bound")
    output = bundle.parent / INVENTORY_NAME
    with output.open("xb") as destination:
        destination.write(encoded)
    return output


def _load_inventory(dist: Path) -> dict[str, str]:
    if not _regular(dist, directory=True):
        raise ValueError("native inventory root is unsafe")
    path = dist / INVENTORY_NAME
    if not _regular(path) or path.stat().st_nlink != 1 or path.stat().st_size > MAX_INVENTORY_BYTES:
        raise ValueError("native COLLECT inventory is unsafe")
    with path.open("rb") as source:
        raw = source.read(MAX_INVENTORY_BYTES + 1)
    if len(raw) > MAX_INVENTORY_BYTES:
        raise ValueError("native COLLECT inventory exceeds its bound")
    document = json.loads(raw)
    if not isinstance(document, dict) or set(document) != {"schema", "files"} or type(document["schema"]) is not int or document["schema"] != 1 or not isinstance(document["files"], dict):
        raise ValueError("native COLLECT inventory is invalid")
    files = document["files"]
    _validate_names(set(files))
    if any(not isinstance(value, str) or len(value) != 64 or any(character not in "0123456789abcdef" for character in value) for value in files.values()):
        raise ValueError("native COLLECT digest is invalid")
    return files


def archive_windows_bundle(dist: Path) -> Path:
    """Require exact intended membership and bytes; never archive adjacent state."""

    expected = _load_inventory(dist)
    files = _bundle_files(dist / "Mentat", set(expected))
    if any(_hash_file(path) != expected[name] for name, path in files.items()):
        raise ValueError("native bundle changed after COLLECT")
    output = dist / "mentat-windows-x64-bundle.zip"
    try:
        with output.open("xb") as destination, zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in sorted(files.items()):
                with path.open("rb") as source, archive.open("Mentat/" + name, "w") as member:
                    digest = hashlib.sha256()
                    while chunk := source.read(64 * 1024):
                        digest.update(chunk)
                        member.write(chunk)
                if digest.hexdigest() != expected[name]:
                    raise ValueError("native bundle changed during archive")
    except BaseException:
        # Do not publish a partial archive, and never replace an existing file.
        if "destination" in locals():
            output.unlink(missing_ok=True)
        raise
    return output


if __name__ == "__main__":
    archive_windows_bundle(ROOT / "dist")
