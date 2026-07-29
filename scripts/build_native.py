#!/usr/bin/env python3
"""Build an unsigned native Mentat test bundle on the current platform."""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mentat.version import DISPLAY_VERSION, __version__


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def build_bundle(dist_dir: Path, work_dir: Path) -> None:
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(work_dir / "config")
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--clean",
            "--noconfirm",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir),
            "packaging/mentat.spec",
        ],
        env=environment,
    )


def build_macos_installer(dist_dir: Path) -> Path:
    app = dist_dir / "Mentat.app"
    if not app.is_dir():
        raise RuntimeError("PyInstaller did not produce Mentat.app")
    architecture = platform.machine().lower() or "unknown"
    output = dist_dir / f"Mentat-{DISPLAY_VERSION.removeprefix('v')}-macos-{architecture}-unsigned.pkg"
    with tempfile.TemporaryDirectory(prefix="mentat-pkg-", dir=dist_dir.parent) as temporary:
        package_root = Path(temporary) / "root"
        installed_app = package_root / "Applications" / "Mentat.app"
        installed_app.parent.mkdir(parents=True)
        shutil.copytree(app, installed_app, symlinks=True)
        component_plist = Path(temporary) / "components.plist"
        run(["pkgbuild", "--analyze", "--root", str(package_root), str(component_plist)])
        components = plistlib.loads(component_plist.read_bytes())
        if not isinstance(components, list) or not components or any(
            not isinstance(component, dict) for component in components
        ):
            raise RuntimeError("pkgbuild produced invalid component metadata")
        for component in components:
            component["BundleIsRelocatable"] = False
        component_plist.write_bytes(plistlib.dumps(components, sort_keys=False))
        run(
            [
                "pkgbuild",
                "--root",
                str(package_root),
                "--component-plist",
                str(component_plist),
                "--install-location",
                "/",
                "--identifier",
                "dev.mentat.local",
                "--version",
                __version__,
                str(output),
            ]
        )
    return output


def build_windows_installer(dist_dir: Path) -> Path:
    compiler = shutil.which("ISCC.exe") or shutil.which("ISCC")
    if compiler is None:
        program_files = os.environ.get("ProgramFiles(x86)") or os.environ.get("ProgramFiles")
        candidate = Path(program_files) / "Inno Setup 6" / "ISCC.exe" if program_files else None
        if candidate is not None and candidate.is_file():
            compiler = str(candidate)
    if compiler is None:
        raise RuntimeError("Inno Setup 6 (ISCC.exe) is required to build the Windows installer")
    run(
        [
            compiler,
            f"/DMyAppVersion={DISPLAY_VERSION.removeprefix('v')}",
            f"/DMyAppSourceDir={dist_dir / 'Mentat'}",
            f"/DMyAppOutputDir={dist_dir / 'installer'}",
            "packaging/windows/Mentat.iss",
        ]
    )
    return dist_dir / "installer" / f"Mentat-{DISPLAY_VERSION.removeprefix('v')}-windows-x64.exe"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-only", action="store_true")
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "build" / "native")
    args = parser.parse_args(argv)
    dist_dir = args.dist_dir.resolve()
    work_dir = args.work_dir.resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    build_bundle(dist_dir, work_dir)
    if args.bundle_only:
        return 0
    if sys.platform == "darwin":
        output = build_macos_installer(dist_dir)
    elif os.name == "nt":
        output = build_windows_installer(dist_dir)
    else:
        print("Linux preview uses the pipx package; no native installer is built.")
        return 0
    print(f"Created unsigned test installer: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
