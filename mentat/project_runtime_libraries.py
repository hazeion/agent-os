"""Private bounded system-library projection for a sealed Linux candidate.

No object is executed. This selected static dependency superset still requires
actual built-worker qualification and independent package-origin evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

from mentat.project_runtime_elf import inspect_elf, RuntimeElfError, MAX_ELF_BYTES
from mentat.project_worker_scope import IS_LINUX, _open_directory, WorkerScopeError

MAX_SYSTEM_FILES = 256
MAX_SYSTEM_BYTES = 256 * 1024 * 1024
MAX_RUNTIME_FILES = 40000
MAX_RUNTIME_BYTES = 1024 * 1024 * 1024
_DEFAULTS = {62: ("x86_64-linux-gnu",), 183: ("aarch64-linux-gnu",)}


def _fail(code):
    raise WorkerScopeError("runtime_libraries." + code)


def _normalized(path):
    if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
        _fail("path")
    result = []
    for part in PurePosixPath(path).parts:
        if part in {"/", "."}:
            continue
        if part == "..":
            if not result:
                _fail("path")
            result.pop()
        else:
            result.append(part)
    return PurePosixPath("/", *result)


def validate_unreachable_paths(paths, virtual_roots):
    if (not isinstance(paths, (tuple, list)) or len(paths) > 16
            or any(not isinstance(value, str) for value in paths) or len(set(paths)) != len(paths)):
        _fail("loader_path")
    if sum(len(value.encode("utf-8")) for value in paths) > 2048:
        _fail("loader_path")
    mounts = (*virtual_roots, *(PurePosixPath(value) for value in
                ("/usr/lib", "/usr/lib64", "/lib", "/lib64", "/tmp", "/home/mentat", "/exports", "/inputs",
                 "/worker", "/dev", "/proc", "/run", "/sys")))
    for value in paths:
        if (not isinstance(value, str) or not value.startswith("/") or value.startswith("//") or len(value) > 512
                or any(part in {".", ".."} for part in PurePosixPath(value).parts)
                or str(_normalized(value)) != value or "$" in value or any(ord(char) < 33 for char in value)):
            _fail("loader_path")
        path = PurePosixPath(value)
        if any(path == mount or mount in path.parents or path in mount.parents for mount in mounts):
            _fail("loader_path")
    return tuple(paths)


def _read_regular_at(root_fd, relative, *, system=False):
    parts = PurePosixPath(relative).parts
    if not parts or any(part in {"/", ".", ".."} for part in parts):
        _fail("path")
    parent = os.dup(root_fd)
    descriptor = None
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            os.close(parent); parent = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
        details = os.fstat(descriptor)
        if (not stat.S_ISREG(details.st_mode) or not 0 <= details.st_size <= MAX_ELF_BYTES
                or (system and (details.st_uid != 0 or details.st_mode & 0o022))):
            _fail("file")
        data = bytearray()
        while len(data) <= details.st_size:
            chunk = os.read(descriptor, min(1024 * 1024, details.st_size + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(descriptor)
        if len(data) != details.st_size or (details.st_dev, details.st_ino, details.st_mtime_ns, details.st_size) != (
                after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size):
            _fail("changed")
        return bytes(data), details.st_mode
    finally:
        if descriptor is not None: os.close(descriptor)
        os.close(parent)


def project_system_libraries(stage: Path, virtual_roots: tuple[PurePosixPath, ...]) -> dict:
    """Add selected /usr/lib roots to an owner-created disposable stage.

    The stage's source/venv/python must already be a trusted candidate projection.
    This operation never reads a model/credential/owner home or runs scanned ELF.
    """
    if not IS_LINUX or not isinstance(stage, Path) or len(virtual_roots) != 3:
        _fail("unsupported")
    stage_fd = _open_directory(stage)
    lib_fd = lib64_fd = None
    try:
        machines = set()
        names, interpreters, bundled = set(), set(), {}
        runtime_paths, explicit_paths, unreachable = set(), set(), set()
        files = total = 0

        def audit_loader_paths(elf, virtual):
            for path_value in (*elf.rpath, *elf.runpath):
                expanded = path_value.replace("${ORIGIN}", str(virtual.parent)).replace("$ORIGIN", str(virtual.parent))
                normalized = _normalized(expanded)
                if (not any(normalized == target or target in normalized.parents for target in virtual_roots)
                        and not str(normalized).startswith(("/usr/lib/", "/usr/lib64/", "/lib/", "/lib64/"))):
                    validate_unreachable_paths([path_value], virtual_roots)
                    unreachable.add(path_value)
                validate_unreachable_paths(sorted(unreachable), virtual_roots)
        for index, label in enumerate(("source", "venv", "python")):
            root = stage / label
            root_fd = _open_directory(root)
            try:
                for current, directories, filenames in os.walk(root, followlinks=False):
                    directories[:] = [name for name in sorted(directories) if not (Path(current) / name).is_symlink()]
                    for name in sorted(filenames):
                        path = Path(current) / name
                        if path.is_symlink():
                            continue  # Root/alias validation remains a candidate recipe gate.
                        files += 1
                        if files > MAX_RUNTIME_FILES:
                            _fail("capacity")
                        relative = path.relative_to(root).as_posix()
                        # Inspect only the magic before bounded ELF reads; public
                        # image data/resources are not parsed as native objects.
                        current_fd = _open_directory(Path(current))
                        try:
                            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=current_fd)
                            try: magic = os.read(descriptor, 4)
                            finally: os.close(descriptor)
                        finally:
                            os.close(current_fd)
                        if magic != b"\x7fELF":
                            continue
                        data, _ = _read_regular_at(root_fd, relative)
                        total += len(data)
                        if total > MAX_RUNTIME_BYTES:
                            _fail("capacity")
                        elf = inspect_elf(data)
                        machines.add(elf.machine)
                        if len(machines) > 1:
                            _fail("architecture")
                        if elf.interpreter: interpreters.add(elf.interpreter)
                        key = elf.soname or name
                        digest = hashlib.sha256(data).hexdigest()
                        if key in bundled and bundled[key] != digest:
                            _fail("ambiguous")
                        bundled[key] = digest
                        virtual = virtual_roots[index] / relative
                        runtime_paths.add(virtual)
                        for dependency in elf.needed:
                            if "/" not in dependency:
                                names.add(dependency)
                            else:
                                expanded = dependency.replace("${ORIGIN}", str(virtual.parent)).replace("$ORIGIN", str(virtual.parent))
                                normalized = _normalized(expanded)
                                if any(normalized == target or target in normalized.parents for target in virtual_roots):
                                    explicit_paths.add(normalized)
                                elif str(normalized).startswith(("/usr/lib/", "/usr/lib64/", "/lib/", "/lib64/")):
                                    interpreters.add(str(normalized))
                                else:
                                    _fail("path")
                        audit_loader_paths(elf, virtual)
            finally:
                os.close(root_fd)
        if len(machines) != 1:
            _fail("architecture")
        if not explicit_paths <= runtime_paths:
            _fail("missing")
        machine = next(iter(machines))
        lib_fd = _open_directory(Path("/usr/lib"))
        lib64_fd = _open_directory(Path("/usr/lib64"))
        inventory = {}
        total_system = 0
        queue = []
        for name in sorted(names):
            queue.append(("needed", name))
        for interpreter in sorted(interpreters):
            queue.append(("absolute", interpreter))
        processed = set()
        for label in ("system_lib", "system_lib64"):
            os.mkdir(label, mode=0o700, dir_fd=stage_fd)

        def source_path(absolute):
            normalized = _normalized(absolute)
            text = str(normalized)
            if text.startswith("/lib64/"): text = "/usr" + text
            elif text.startswith("/lib/"): text = "/usr" + text
            if text.startswith("/usr/lib64/"):
                return "system_lib64", lib64_fd, text[len("/usr/lib64/"):]
            if text.startswith("/usr/lib/"):
                return "system_lib", lib_fd, text[len("/usr/lib/"):]
            _fail("path")

        def copy(absolute, depth=0):
            nonlocal total_system
            if depth > 16: _fail("link")
            label, descriptor, relative = source_path(absolute)
            key = label + "/" + relative
            if key in inventory: return
            if len(inventory) >= MAX_SYSTEM_FILES: _fail("capacity")
            parts = PurePosixPath(relative).parts
            parent = os.dup(descriptor)
            try:
                for part in parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    details = os.fstat(child)
                    if details.st_uid != 0 or details.st_mode & 0o022: _fail("file")
                    os.close(parent); parent = child
                details = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if details.st_uid != 0 or (not stat.S_ISLNK(details.st_mode) and details.st_mode & 0o022): _fail("file")
                target = stage / label / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if stat.S_ISLNK(details.st_mode):
                    link = os.readlink(parts[-1], dir_fd=parent)
                    if len(link) > 512: _fail("link")
                    destination = _normalized(link if link.startswith("/") else str(PurePosixPath(absolute).parent / link))
                    copy(str(destination), depth + 1)
                    target.symlink_to(link)
                    inventory[key] = "link:" + link
                    return
            finally:
                os.close(parent)
            data, mode = _read_regular_at(descriptor, relative, system=True)
            total_system += len(data)
            if total_system > MAX_SYSTEM_BYTES: _fail("capacity")
            elf = inspect_elf(data)
            if elf is None or elf.machine != machine: _fail("architecture")
            audit_loader_paths(elf, PurePosixPath(absolute))
            target.write_bytes(data)
            target.chmod(0o555 if mode & 0o111 else 0o444)
            digest = hashlib.sha256(data).hexdigest()
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest: _fail("changed")
            inventory[key] = digest
            for name in elf.needed:
                if "/" in name:
                    expanded = name.replace("${ORIGIN}", str(PurePosixPath(absolute).parent)).replace("$ORIGIN", str(PurePosixPath(absolute).parent))
                    queue.append(("absolute", str(_normalized(expanded))))
                else:
                    queue.append(("needed", name))

        while queue:
            kind, value = queue.pop(0)
            if (kind, value) in processed: continue
            processed.add((kind, value))
            if len(processed) > MAX_SYSTEM_FILES: _fail("capacity")
            if kind == "absolute":
                copy(value)
                continue
            options = ["/usr/lib/" + architecture + "/" + value for architecture in _DEFAULTS[machine]] + ["/usr/lib64/" + value, "/usr/lib/" + value]
            present = [path for path in options if os.path.lexists(path)]
            if not present:
                if value not in bundled: _fail("missing")
                continue
            # Default candidates are a static superset; loader choice and
            # dlopen coverage are verified by the actual built operation.
            for path in present:
                copy(path)
        result = {"format": 1, "machine": machine, "runtime_elf_bytes": total,
                  "system_bytes": total_system, "members": [[key, value] for key, value in sorted(inventory.items())],
                  "unreachable_paths": list(validate_unreachable_paths(sorted(unreachable), virtual_roots))}
        report = json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(report) > 32768: _fail("capacity")
        target = stage / "runtime-libraries.json"
        with target.open("xb") as stream: stream.write(report)
        target.chmod(0o444)
        return result
    except (RuntimeElfError, OSError, ValueError) as exc:
        if isinstance(exc, WorkerScopeError): raise
        raise WorkerScopeError("runtime_libraries.invalid") from exc
    finally:
        for descriptor in (lib_fd, lib64_fd, stage_fd):
            if descriptor is not None: os.close(descriptor)
