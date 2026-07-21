#!/usr/bin/env python3
"""Verify exact public contents and integrity of Mentat wheel/sdist artifacts."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mentat.version import __version__


DIST_NAME = f"mentat_local-{__version__}"
DIST_INFO = f"{DIST_NAME}.dist-info"
EGG_INFO = "mentat_local.egg-info"
PUBLIC_MODULES = {
    "agent_console_artifacts", "agent_console_attachments", "agent_run_history",
    "command_manifest", "data_backup_restore", "data_layout", "data_migration",
    "data_schema", "health_checks", "hermes_kanban", "hermes_profile_creation",
    "hermes_profile_deletion", "hermes_profile_identity", "hermes_profiles",
    "hermes_provider_switching", "hermes_skills", "hermes_transport", "json_store",
    "mentat_db", "mentat_lifecycle", "private_console_migration",
    "private_console_unit", "private_state", "remote_hermes", "runtime_config",
    "server", "task_planning",
}
PUBLIC_PACKAGES = {"mentat"}
PUBLIC_DATA_FILES = {
    "share/mentat/public": {
        "public/app.js", "public/core.js", "public/index.html",
        "public/mentat-logo.png", "public/styles.css",
    },
    "share/mentat/data": {
        "data/agent_messages.json", "data/agents.json", "data/attention.json",
        "data/calendar.json", "data/context_packs.json", "data/dashboard.json",
        "data/email.json", "data/projects.json", "data/tasks.json",
    },
}


def _parent_directories(files: set[str]) -> set[str]:
    directories: set[str] = set()
    for name in files:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _special_tar_members(members: list[tarfile.TarInfo]) -> list[str]:
    return [member.name for member in members if not (member.isfile() or member.isdir())]


def _project() -> dict:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    setuptools = project["tool"]["setuptools"]
    configured_data = {
        destination: set(sources)
        for destination, sources in setuptools["data-files"].items()
    }
    if set(setuptools["py-modules"]) != PUBLIC_MODULES:
        raise ValueError("pyproject public module inventory changed")
    if set(setuptools["packages"]) != PUBLIC_PACKAGES:
        raise ValueError("pyproject public package inventory changed")
    if configured_data != PUBLIC_DATA_FILES:
        raise ValueError("pyproject public data inventory changed")
    return project


def _source_files() -> set[str]:
    project = _project()
    files = {
        "LICENSE",
        "MANIFEST.in",
        "README.md",
        "mentat.toml",
        "pyproject.toml",
        "requirements.txt",
        "requirements-native.in",
        "requirements-native.lock",
        "requirements-native.txt",
        "scripts/build_native.py",
    }
    files.update(f"{name}.py" for name in project["tool"]["setuptools"]["py-modules"])
    for package in project["tool"]["setuptools"]["packages"]:
        files.update(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / package).rglob("*.py")
        )
    for sources in project["tool"]["setuptools"]["data-files"].values():
        files.update(sources)
    files.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "packaging").rglob("*")
        if path.is_file() and path.suffix in {".iss", ".md", ".py", ".spec"}
    )
    return files


def _wheel_files() -> set[str]:
    project = _project()
    files = {f"{name}.py" for name in project["tool"]["setuptools"]["py-modules"]}
    for package in project["tool"]["setuptools"]["packages"]:
        files.update(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / package).rglob("*.py")
        )
    for destination, sources in project["tool"]["setuptools"]["data-files"].items():
        files.update(
            f"{DIST_NAME}.data/data/{destination}/{Path(source).name}"
            for source in sources
        )
    files.update(
        {
            f"{DIST_INFO}/METADATA",
            f"{DIST_INFO}/RECORD",
            f"{DIST_INFO}/WHEEL",
            f"{DIST_INFO}/entry_points.txt",
            f"{DIST_INFO}/licenses/LICENSE",
            f"{DIST_INFO}/top_level.txt",
        }
    )
    return files


def _safe_names(names: list[str], *, label: str) -> None:
    if len(names) != len(set(names)):
        raise ValueError(f"{label} contains duplicate archive members")
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError(f"{label} contains unsafe member: {name}")


def verify_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        _safe_names(names, label="wheel")
        actual = {name for name in names if not name.endswith("/")}
        expected = _wheel_files()
        directories = {name.rstrip("/") for name in names if name.endswith("/")}
        unexpected_directories = directories - _parent_directories(expected)
        if unexpected_directories:
            raise ValueError(
                f"wheel contains unexpected directories: {sorted(unexpected_directories)}"
            )
        if actual != expected:
            raise ValueError(
                f"wheel content mismatch; missing={sorted(expected - actual)}, "
                f"unexpected={sorted(actual - expected)}"
            )
        rows = list(
            csv.reader(io.StringIO(archive.read(f"{DIST_INFO}/RECORD").decode("utf-8")))
        )
        if {row[0] for row in rows} != expected:
            raise ValueError("wheel RECORD inventory does not match archive inventory")
        for name, digest, size in rows:
            if name == f"{DIST_INFO}/RECORD":
                if digest or size:
                    raise ValueError("wheel RECORD must leave its own hash and size empty")
                continue
            content = archive.read(name)
            encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
            if digest != f"sha256={encoded}" or size != str(len(content)):
                raise ValueError(f"wheel RECORD integrity mismatch: {name}")


def verify_sdist(path: Path) -> None:
    generated = {
        "PKG-INFO",
        "setup.cfg",
        f"{EGG_INFO}/PKG-INFO",
        f"{EGG_INFO}/SOURCES.txt",
        f"{EGG_INFO}/dependency_links.txt",
        f"{EGG_INFO}/entry_points.txt",
        f"{EGG_INFO}/requires.txt",
        f"{EGG_INFO}/top_level.txt",
    }
    expected = _source_files() | generated
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        _safe_names(names, label="sdist")
        special = _special_tar_members(members)
        if special:
            raise ValueError(f"sdist contains special members: {sorted(special)}")
        roots = {PurePosixPath(name).parts[0] for name in names}
        if roots != {DIST_NAME}:
            raise ValueError(f"sdist root must be {DIST_NAME}, found {sorted(roots)}")
        root = DIST_NAME
        actual = {
            PurePosixPath(member.name).relative_to(root).as_posix()
            for member in members
            if member.isfile()
        }
        if actual != expected:
            raise ValueError(
                f"sdist content mismatch; missing={sorted(expected - actual)}, "
                f"unexpected={sorted(actual - expected)}"
            )
        allowed_directories = _parent_directories(expected)
        directories = {
            PurePosixPath(member.name).relative_to(root).as_posix()
            for member in members
            if member.isdir() and PurePosixPath(member.name) != PurePosixPath(root)
        }
        unexpected_directories = directories - allowed_directories
        if unexpected_directories:
            raise ValueError(
                f"sdist contains unexpected directories: {sorted(unexpected_directories)}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path)
    args = parser.parse_args()
    wheels = sorted(args.artifact_dir.glob("*.whl"))
    sdists = sorted(args.artifact_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("artifact directory must contain exactly one wheel and one sdist")
    verify_wheel(wheels[0])
    verify_sdist(sdists[0])
    print(f"Verified {wheels[0].name} and {sdists[0].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
