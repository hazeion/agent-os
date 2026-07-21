# PyInstaller definition shared by macOS and Windows native test bundles.

from pathlib import Path
import runpy
import sys


ROOT = Path(SPECPATH).parent
VERSION = runpy.run_path(str(ROOT / "mentat" / "version.py"))
PUBLIC_SEEDS = (
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
PUBLIC_ASSETS = (
    "app.js",
    "core.js",
    "index.html",
    "mentat-logo.png",
    "styles.css",
)
datas = [(str(ROOT / "public" / name), "public") for name in PUBLIC_ASSETS]
datas.extend((str(ROOT / "data" / name), "data") for name in PUBLIC_SEEDS)

analysis = Analysis(
    [str(ROOT / "packaging" / "mentat_native.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

gui_name = "Mentat Launcher" if sys.platform.startswith("win") else "Mentat"
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=gui_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
executables = [executable]
if sys.platform.startswith("win"):
    cli_executable = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name="mentat",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
    )
    executables.append(cli_executable)

bundle = COLLECT(
    *executables,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="Mentat",
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle,
        name="Mentat.app",
        icon=None,
        bundle_identifier="dev.mentat.local",
        info_plist={
            "CFBundleDisplayName": "Mentat",
            "CFBundleShortVersionString": VERSION["__version__"].split("b", 1)[0],
            "CFBundleVersion": VERSION["__version__"],
            "LSMinimumSystemVersion": "10.15",
            "NSHighResolutionCapable": True,
        },
    )
