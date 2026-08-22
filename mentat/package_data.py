"""Public package payload definitions shared by setuptools and verification."""

from __future__ import annotations

from pathlib import Path


PUBLIC_DATA_FILES: dict[str, tuple[str, ...]] = {
    "share/mentat/public": (
        "public/app.js", "public/core.js", "public/index.html",
        "public/mentat-logo.png", "public/mentat-mark-emerald.png", "public/styles.css",
    ),
    "share/mentat/data": (
        "data/agent_messages.json", "data/agents.json", "data/attention.json",
        "data/calendar.json", "data/context_packs.json", "data/dashboard.json",
        "data/email.json", "data/projects.json", "data/tasks.json",
    ),
}
WEB_RUNTIME_STAGE = Path("web") / "package-runtime"
WEB_RUNTIME_DESTINATION = "share/mentat/web"
NATIVE_RUNTIME_SUFFIXES = frozenset({".dll", ".dylib", ".exe", ".node", ".so"})
NATIVE_BINARY_SIGNATURES = (
    b"\x7fELF",
    b"MZ",
    b"\xfe\xed\xfa\xce",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
)


def native_runtime_reason(name: str | Path, content_prefix: bytes) -> str | None:
    """Return a portability failure for a native runtime file, if present."""

    filename = Path(name).name.lower()
    if filename.endswith(".so") or ".so." in filename or Path(filename).suffix in NATIVE_RUNTIME_SUFFIXES:
        return "platform-native filename"
    if any(content_prefix.startswith(signature) for signature in NATIVE_BINARY_SIGNATURES):
        return "platform-native binary signature"
    return None


def validate_web_runtime(runtime_root: Path) -> None:
    """Fail closed unless the staged standalone payload is regular and portable."""

    for path in sorted(runtime_root.rglob("*")):
        if path.is_symlink() or (path.exists() and not (path.is_dir() or path.is_file())):
            raise RuntimeError(f"Staged Node dashboard contains an unsafe file: {path}")
        if not path.is_file():
            continue
        reason = native_runtime_reason(path, path.read_bytes()[:8])
        if reason:
            raise RuntimeError(f"Staged Node dashboard contains a {reason}: {path}")


def package_data_files(root: Path, *, require_runtime: bool = True) -> list[tuple[str, list[str]]]:
    """Return static seeds plus the regular-file Node standalone payload."""

    root = Path(root)
    files = [(destination, list(sources)) for destination, sources in PUBLIC_DATA_FILES.items()]
    runtime_root = root / WEB_RUNTIME_STAGE
    server = runtime_root / "server.js"
    if not server.is_file() or server.is_symlink():
        if not require_runtime:
            return files
        raise RuntimeError(
            "Missing staged Node dashboard; run npm --prefix web run build and "
            "python scripts/stage_web_runtime.py before building Python artifacts."
        )
    validate_web_runtime(runtime_root)
    grouped: dict[str, list[str]] = {}
    for path in sorted(runtime_root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Staged Node dashboard contains a symlink: {path}")
        if not path.is_file():
            continue
        relative_parent = path.relative_to(runtime_root).parent
        destination = WEB_RUNTIME_DESTINATION
        if relative_parent != Path("."):
            destination = f"{destination}/{relative_parent.as_posix()}"
        grouped.setdefault(destination, []).append(path.relative_to(root).as_posix())
    if not grouped:
        raise RuntimeError("Staged Node dashboard is empty")
    files.extend(sorted(grouped.items()))
    return files
