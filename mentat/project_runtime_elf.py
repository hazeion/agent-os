"""Bounded nonexecuting ELF64 dependency evidence for Linux runtime images.

This inventories direct ELF declarations, not every dlopen path or package
origin. Real built-worker qualification remains required before admission.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import struct

MAX_ELF_BYTES = 128 * 1024 * 1024
MAX_HEADERS = 1024
MAX_DYNAMIC = 4096
MAX_DEPENDENCIES = 256
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,255}\Z")
# Fixed glibc/ELF64 declarations understood by the host-only policy. Unknown
# vendor tags cannot silently introduce another dependency/search mechanism.
_HOST_DYNAMIC_TAGS = frozenset({
    0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
    20, 21, 23, 24, 25, 26, 27, 28, 30, 32, 33, 34, 35, 36, 37,
    0x6ffffef5, 0x6ffffef6, 0x6ffffef7, 0x6ffffff0, 0x6ffffff9,
    0x6ffffffa, 0x6ffffffb, 0x6ffffffc, 0x6ffffffd, 0x6ffffffe, 0x6fffffff,
})


class RuntimeElfError(ValueError):
    pass


def _fail():
    raise RuntimeElfError("runtime_elf.invalid")


@dataclass(frozen=True)
class ElfDependencies:
    machine: int
    interpreter: str | None
    needed: tuple[str, ...]
    soname: str | None
    rpath: tuple[str, ...]
    runpath: tuple[str, ...]


def inspect_elf(data: bytes, *, host_only: bool = False) -> ElfDependencies | None:
    if type(host_only) is not bool:
        _fail()
    if type(data) is not bytes or len(data) > MAX_ELF_BYTES:
        _fail()
    if not data.startswith(b"\x7fELF"):
        return None
    if len(data) < 64:
        _fail()
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    identifier, kind, machine, version, _, offset, _, _, header_size, entry_size, count, _, _, _ = header
    if (identifier[4:7] != b"\x02\x01\x01" or identifier[7] not in {0, 3}
            or kind not in {2, 3} or machine not in {62, 183} or version != 1
            or header_size != 64 or entry_size != 56 or not 0 < count <= MAX_HEADERS
            or offset < 64 or offset + count * entry_size > len(data)):
        _fail()
    loads, dynamic = [], None
    interpreter = None
    for index in range(count):
        tag, _, file_offset, address, _, file_size, memory_size, _ = struct.unpack_from("<IIQQQQQQ", data, offset + index * entry_size)
        if file_size > memory_size or file_offset + file_size > len(data) or address + memory_size > 0xffffffffffffffff:
            _fail()
        if tag == 1:
            loads.append((address, file_offset, file_size))
        elif tag == 2:
            if dynamic is not None or not 0 < file_size <= MAX_DYNAMIC * 16 or file_size % 16:
                _fail()
            dynamic = (file_offset, file_size)
        elif tag == 3:
            if interpreter is not None or not 1 < file_size <= 4096:
                _fail()
            payload = data[file_offset:file_offset + file_size]
            if payload[-1:] != b"\0" or b"\0" in payload[:-1]:
                _fail()
            try:
                interpreter = payload[:-1].decode("ascii")
            except UnicodeError:
                _fail()
            if (not interpreter.startswith(("/lib/", "/lib64/", "/usr/lib/", "/usr/lib64/"))
                    or any(part in {"", ".", ".."} for part in interpreter.split("/")[1:])
                    or any(ord(char) < 33 or ord(char) > 126 for char in interpreter)):
                _fail()
    if dynamic is None:
        return ElfDependencies(machine, interpreter, (), None, (), ())
    tags = {}
    needed_offsets = []
    ended = False
    host_tags = set()
    for index in range(dynamic[1] // 16):
        tag, value = struct.unpack_from("<qQ", data, dynamic[0] + index * 16)
        if host_only:
            if tag not in _HOST_DYNAMIC_TAGS or tag != 1 and tag in host_tags:
                _fail()
            host_tags.add(tag)
        if tag == 0:
            ended = True
            break
        if tag == 1:
            needed_offsets.append(value)
            if len(needed_offsets) > MAX_DEPENDENCIES:
                _fail()
        elif tag in {5, 10, 14, 15, 29}:
            if tag in tags:
                _fail()
            tags[tag] = value
        elif tag in {0x6ffffefb, 0x6ffffefc}:  # DT_DEPAUDIT / DT_AUDIT
            _fail()
        elif host_only:
            # These declarations alter lookup or introduce objects outside the
            # represented DT_NEEDED graph. Do not mistake a partial graph for
            # a fixed host helper's complete declared loading requirements.
            if tag == 30 and value & ~(8 | 16):  # NOW / STATIC_TLS only
                _fail()
            if tag == 0x6ffffffb and value & ~(1 | 8 | 0x08000000):  # NOW / NODELETE / PIE
                _fail()
    if not ended:
        _fail()
    if not needed_offsets and not any(tag in tags for tag in (14, 15, 29)) and 5 not in tags and 10 not in tags:
        return ElfDependencies(machine, interpreter, (), None, (), ())
    if 5 not in tags or 10 not in tags or not 0 < tags[10] <= 1024 * 1024:
        _fail()
    cursor, end = tags[5], tags[5] + tags[10]
    if end > 0xffffffffffffffff:
        _fail()
    start = None
    for _ in range(len(loads) + 1):
        candidates = [(address, file_offset, size) for address, file_offset, size in loads
                      if address <= cursor < address + size]
        if len(candidates) != 1:
            _fail()
        address, file_offset, segment_size = candidates[0]
        current_offset = file_offset + cursor - address
        if start is None:
            start = current_offset
        elif current_offset != start + cursor - tags[5]:
            _fail()
        # Inspect every mapping boundary; a LOAD starting inside the current
        # segment can make a later part ambiguous even with the same offset.
        next_starts = [start_address for start_address, _, size in loads
                       if size and cursor < start_address < end]
        cursor = min(end, address + segment_size, *next_starts)
        if cursor == end:
            break
    if cursor != end or start + tags[10] > len(data):
        _fail()
    size = tags[10]
    strings = data[start:start + size]

    def text(position):
        if position >= len(strings):
            _fail()
        end = strings.find(b"\0", position, min(len(strings), position + 4097))
        if end < 0:
            _fail()
        try:
            value = strings[position:end].decode("ascii")
        except UnicodeError:
            _fail()
        if not value or any(ord(char) < 33 or ord(char) > 126 for char in value):
            _fail()
        return value

    needed = tuple(text(position) for position in needed_offsets)
    soname = text(tags[14]) if 14 in tags else None
    def dependency_name(name):
        if _NAME.fullmatch(name) is not None:
            return True
        if name.startswith(("$ORIGIN/", "${ORIGIN}/", "/lib/", "/lib64/", "/usr/lib/", "/usr/lib64/")):
            remaining = name.replace("${ORIGIN}", "").replace("$ORIGIN", "")
            return "$" not in remaining and len(name) <= 4096
        return False
    if (len(set(needed)) != len(needed) or any(not dependency_name(name) for name in needed)
            or soname is not None and _NAME.fullmatch(soname) is None):
        _fail()

    def paths(tag):
        if tag not in tags:
            return ()
        value = text(tags[tag]).split(":")
        if len(value) > 32 or any(not item or item == "." or "\x00" in item for item in value):
            _fail()
        # Only the selected runtime's ORIGIN token is supported. Other dynamic
        # linker tokens require a separately qualified target-specific rule.
        for item in value:
            remaining = item.replace("${ORIGIN}", "").replace("$ORIGIN", "")
            if "$" in remaining or not (item.startswith("/") or item.startswith(("$ORIGIN", "${ORIGIN}"))):
                _fail()
        return tuple(value)

    result = ElfDependencies(machine, interpreter, needed, soname, paths(15), paths(29))
    if host_only and (result.rpath or result.runpath):
        _fail()
    return result


def inspect_host_elf(data: bytes) -> ElfDependencies:
    """Inspect the deliberately narrower fixed Ubuntu amd64 helper subset.

    This is static declaration evidence, never proof of ld.so cache/preload,
    hwcaps, dlopen, package provenance, immutable execution or privileges.
    """
    result = inspect_elf(data, host_only=True)
    if (result is None or result.machine != 62 or result.interpreter not in
            {None, "/lib64/ld-linux-x86-64.so.2"}):
        _fail()
    return result
