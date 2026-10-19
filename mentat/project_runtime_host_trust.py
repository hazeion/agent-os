"""Nonexecuting candidate evidence for fixed Ubuntu amd64 helper closures.

No path is opened, object executed, trust capability issued or readiness saved.
Helper bytes must match the existing reviewed signed-package pins. Supplied
library bytes are NOT authenticated merely because their hashes are recorded.
This deliberately has no integration with image launch or production admission.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import PurePosixPath
import re

from mentat.project_runtime_elf import MAX_ELF_BYTES, RuntimeElfError, inspect_host_elf
from mentat.project_system_origin import PINS

MAX_MEMBERS = 256
MAX_BYTES = 256 * 1024 * 1024
_HELPERS = {PurePosixPath(pin.member).name: pin for pin in PINS}
_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,255}\Z")
_LIBRARY_ROOTS = ("/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib")
_REQUIRED = (
    "signed-library-provenance", "helper-and-library-security-review", "actual-loader-behavior",
    "immutable-helper-execution", "fuse-privilege-and-verified-teardown",
)


class HostClosureError(ValueError):
    pass


def _fail():
    # Never propagate a caller path, payload or arbitrary ELF text.
    raise HostClosureError("runtime_host_closure.unverified")


def _library_path(value: str, *, origin: str | None = None) -> str:
    if type(value) is not str or not value or len(value) > 512 or value.startswith("//"):
        _fail()
    if not value.startswith("/"):
        if origin is None:
            _fail()
        value = str(PurePosixPath(origin).parent / value)
    parts = []
    for part in value.split("/")[1:]:
        if part == "..":
            if not parts:
                _fail()
            parts.pop()
        elif part != ".":
            if _PART.fullmatch(part) is None:
                _fail()
            parts.append(part)
    path = "/" + "/".join(parts)
    if path.startswith(("/lib/", "/lib64/")):
        path = "/usr" + path
    if not any(path.startswith(root + "/") for root in _LIBRARY_ROOTS):
        _fail()
    return path


@dataclass(frozen=True)
class HostClosureCandidate:
    """Immutable static evidence, with explicit unresolved trust requirements."""
    helper: str
    members: tuple[tuple[str, str, int], ...]
    aliases: tuple[tuple[str, str], ...]
    edges: tuple[tuple[str, str], ...]
    required_qualification: tuple[str, ...] = _REQUIRED


def audit_fixed_helper_closure(
    helper: str, members: tuple[tuple[str, bytes | str], ...],
) -> HostClosureCandidate:
    """Check exact fixed-helper bytes and a bounded supplied ELF/alias graph.

    Members are immutable captured bytes or explicit symlink text, never paths
    to read. The result cannot authorize launch. Resolution requires one unique
    supplied target under the existing Ubuntu amd64 default library roots;
    unrepresented cache, preload, hwcaps and dlopen behavior remains unqualified.
    """
    if type(helper) is not str or helper not in _HELPERS or type(members) is not tuple:
        _fail()
    pin = _HELPERS[helper]
    helper_path = "/" + pin.member
    if not 1 <= len(members) <= MAX_MEMBERS:
        _fail()
    captured = {}
    total = 0
    for member in members:
        if type(member) is not tuple or len(member) != 2:
            _fail()
        path, raw = member
        if type(path) is not str or type(raw) not in (bytes, str):
            _fail()
        if path != helper_path:
            # Input member names must already be canonical; only recorded
            # link targets may contain relative components or /lib aliases.
            if _library_path(path) != path:
                _fail()
        if path in captured:
            _fail()
        if type(raw) is bytes:
            total += len(raw)
            if not raw or len(raw) > MAX_ELF_BYTES or total > MAX_BYTES:
                _fail()
        elif not raw or len(raw) > 512:
            _fail()
        captured[path] = raw
    raw = captured.get(helper_path)
    if (type(raw) is not bytes or len(raw) != pin.member_size
            or hashlib.sha256(raw).hexdigest() != pin.member_digest):
        _fail()

    used, aliases, regular, edges = set(), {}, {}, set()

    def resolve(path):
        chain = set()
        while True:
            if path in chain or len(chain) >= 16 or path not in captured:
                _fail()
            chain.add(path)
            used.add(path)
            payload = captured[path]
            if type(payload) is bytes:
                return path
            destination = _library_path(payload, origin=path)
            aliases[path] = destination
            path = destination

    pending = [helper_path]
    try:
        while pending:
            path = resolve(pending.pop())
            if path in regular:
                continue
            raw = captured[path]
            elf = inspect_host_elf(raw)
            regular[path] = (hashlib.sha256(raw).hexdigest(), len(raw))
            requirements = []
            if elf.interpreter:
                requirements.append((_library_path(elf.interpreter), None))
            for name in elf.needed:
                if "/" in name:
                    # Host helpers cannot depend on caller ORIGIN/token paths.
                    if not name.startswith("/"):
                        _fail()
                    requirements.append((_library_path(name), None))
                else:
                    options = [root + "/" + name for root in _LIBRARY_ROOTS]
                    targets = {resolve(option) for option in options if option in captured}
                    if len(targets) != 1:
                        _fail()
                    requirements.append((targets.pop(), name))
            for requirement, soname in requirements:
                target = resolve(requirement)
                if target == helper_path:
                    _fail()
                dependency = inspect_host_elf(captured[target])
                if soname is not None and dependency.soname not in (None, soname):
                    _fail()
                edges.add((path, target))
                if target not in regular:
                    pending.append(target)
    except RuntimeElfError:
        _fail()
    if used != set(captured):
        _fail()
    return HostClosureCandidate(
        helper, tuple((path, *regular[path]) for path in sorted(regular)),
        tuple(sorted(aliases.items())), tuple(sorted(edges)),
    )
