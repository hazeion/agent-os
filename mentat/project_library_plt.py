"""Private exact-two-member glibc metadata profile; never executes or rewrites PLT.

This parser has no caller policy input and supplies no provenance or readiness.
The library-origin worker calls it only after authenticated exact archive/member
validation. Ordinary inspect_host_elf remains closed to these processor tags.
"""
from bisect import bisect_left
from dataclasses import dataclass
import hashlib
import struct

from mentat.project_runtime_elf import (
    MAX_HEADERS, MAX_DYNAMIC, _fail, _host_dynamic_tag, inspect_elf,
)

MARKER = "GLIBC_ABI_DT_X86_64_PLT"
TRIPLE = frozenset({0x70000000, 0x70000001, 0x70000003})
MAX_SYMBOLS = 65536
MAX_VERSIONS = 4096


@dataclass(frozen=True)
class _Profile:
    size: int
    digest: str
    address: int
    table_bytes: int
    jumps: int
    indirect: int
    role: str


_PROFILES = {
    "/usr/lib/x86_64-linux-gnu/libc.so.6": _Profile(
        2190608, "85e64f97e348786a8fb4d9f3d52fec289e2fb86bba20f0731dfe61990525e0f7",
        0x283f0, 960, 15, 45, "libc"),
    "/usr/lib/x86_64-linux-gnu/libm.so.6": _Profile(
        1198376, "1c488db6f4fe8cecb72456bc018de000b7a9b539c2994864b0416b5e8371b3d8",
        0x12320, 736, 11, 35, "libm"),
}


def _add(address, size):
    if type(address) is not int or type(size) is not int or address < 0 or size < 0 or address + size > 0xffffffffffffffff:
        _fail()
    return address + size


def _elf_hash(text):
    value = 0
    for byte in text.encode("ascii"):
        value = (value << 4) + byte
        high = value & 0xf0000000
        value ^= high >> 24
        value &= ~high
    return value


class _Image:
    def __init__(self, data):
        self.data = data
        self.result = inspect_elf(data)
        if (self.result is None or self.result.machine != 62 or self.result.rpath or self.result.runpath
                or self.result.interpreter not in {None, "/lib64/ld-linux-x86-64.so.2"}):
            _fail()
        values = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
        phoff, phsize, phnum = values[5], values[9], values[10]
        if phsize != 56 or not 1 <= phnum <= MAX_HEADERS or phoff + phsize * phnum > len(data):
            _fail()
        self.loads = []
        dynamic = None
        for n in range(phnum):
            kind, flags, offset, address, _physical, filesz, memsz, _align = struct.unpack_from("<IIQQQQQQ", data, phoff + n * phsize)
            if kind == 1:
                if flags & ~7 or filesz > memsz or offset + filesz > len(data):
                    _fail()
                _add(address, memsz)
                self.loads.append((address, filesz, offset, flags, memsz))
            elif kind == 2:
                if dynamic is not None or not 0 < filesz <= MAX_DYNAMIC * 16 or filesz % 16 or offset + filesz > len(data):
                    _fail()
                dynamic = (offset, filesz)
        if dynamic is None:
            _fail()
        self.tags = {}
        seen = set()
        ended = False
        for pos in range(dynamic[0], dynamic[0] + dynamic[1], 16):
            tag, value = struct.unpack_from("<qQ", data, pos)
            if tag in TRIPLE:
                if tag in seen:
                    _fail()
                seen.add(tag)
            else:
                _host_dynamic_tag(tag, value, seen)
            self.tags[tag] = value
            if tag == 0:
                ended = True
                break
        if not ended or not TRIPLE <= set(self.tags):
            _fail()
        strings = self.need(10)
        if not 0 < strings <= 1024 * 1024:
            _fail()
        self.strings = self.slice(self.need(5), strings)
        self.version_ranges = []
        self.version_records = 0

    def need(self, tag):
        if tag not in self.tags:
            _fail()
        return self.tags[tag]

    def mapping(self, address, size, *, required=4, forbidden=0):
        if size <= 0:
            _fail()
        end = _add(address, size)
        overlaps = [load for load in self.loads if address < load[0] + load[4] and load[0] < end]
        if len(overlaps) != 1:
            _fail()
        start, filesz, offset, flags, _memsz = overlaps[0]
        if not start <= address < end <= start + filesz or flags & required != required or flags & forbidden:
            _fail()
        file_offset = offset + address - start
        if file_offset + size > len(self.data):
            _fail()
        return file_offset

    def slice(self, address, size, **kwargs):
        offset = self.mapping(address, size, **kwargs)
        return self.data[offset:offset + size]

    def read(self, fmt, address, **kwargs):
        offset = self.mapping(address, struct.calcsize(fmt), **kwargs)
        return struct.unpack_from(fmt, self.data, offset)

    def text(self, index):
        if not 0 <= index < len(self.strings):
            _fail()
        end = self.strings.find(b"\0", index, min(len(self.strings), index + 256))
        if end < 0 or end == index:
            _fail()
        raw = self.strings[index:end]
        if any(byte < 33 or byte > 126 for byte in raw):
            _fail()
        return raw.decode("ascii")

    def symbols(self):
        buckets, count = self.read("<II", self.need(4))
        if not 1 <= buckets <= MAX_SYMBOLS or not 1 <= count <= MAX_SYMBOLS or self.need(11) != 24:
            _fail()
        table = self.slice(self.need(4), 8 + 4 * (buckets + count))
        values = struct.unpack_from("<" + "I" * (buckets + count), table, 8)
        if any(value >= count for value in values):
            _fail()
        chains = values[buckets:]
        if chains[0] != 0:
            _fail()
        # Linear total traversal, including unreachable malformed chain cycles.
        finished = {0}
        for index in range(1, count):
            local = set()
            while index not in finished:
                if index in local:
                    _fail()
                local.add(index); index = chains[index]
            finished.update(local)
        address = self.need(0x6ffffef5)
        nbuckets, offset, blooms, shift = self.read("<IIII", address)
        if (not 1 <= nbuckets <= MAX_SYMBOLS or not 0 <= offset <= count
                or not 1 <= blooms <= 8192 or blooms & (blooms - 1) or shift >= 64):
            _fail()
        raw = self.slice(address, 16 + 8 * blooms + 4 * nbuckets + 4 * (count - offset))
        starts = struct.unpack_from("<" + "I" * nbuckets, raw, 16 + 8 * blooms)
        words = struct.unpack_from("<" + "I" * (count - offset), raw, 16 + 8 * blooms + 4 * nbuckets)
        # A cached suffix terminator bounds work by symbols+buckets, not their product.
        terminal = None
        ends = [None] * len(words)
        for n in range(len(words) - 1, -1, -1):
            if words[n] & 1:
                terminal = n
            ends[n] = terminal
        spans = []
        for start in starts:
            if start:
                if not offset <= start < count or ends[start - offset] is None:
                    _fail()
                spans.append((start - offset, ends[start - offset]))
        cursor = 0
        for start, end in sorted(spans):
            if start != cursor:
                _fail()
            cursor = end + 1
        if cursor != len(words):
            _fail()
        self.mapping(self.need(6), count * 24)
        self.mapping(self.need(0x6ffffff0), count * 2)
        return count

    def reserve_version(self, address, size):
        if address % 4:
            _fail()
        end = _add(address, size)
        index = bisect_left(self.version_ranges, (address, end))
        if (index and self.version_ranges[index - 1][1] > address
                or index < len(self.version_ranges) and self.version_ranges[index][0] < end):
            _fail()
        self.mapping(address, size)
        self.version_ranges.insert(index, (address, end))
        self.version_records += 1
        if self.version_records > MAX_VERSIONS:
            _fail()

    def versions(self, count, role):
        versions = {}
        definitions, requirements, providers = set(), set(), set()
        for kind, ptrtag, counttag in (("definition", 0x6ffffffc, 0x6ffffffd), ("requirement", 0x6ffffffe, 0x6fffffff)):
            address = self.need(ptrtag)
            number = self.need(counttag)
            if not 1 <= number <= MAX_VERSIONS:
                _fail()
            for n in range(number):
                if kind == "definition":
                    self.reserve_version(address, 20)
                    version, flags, index, auxiliaries, digest, aux, next_offset = self.read("<HHHHIII", address)
                    if version != 1 or flags & ~3 or not 1 <= index < 0x8000 or index in versions:
                        _fail()
                    provider = None
                    minimum, aux_size = 20, 8
                else:
                    self.reserve_version(address, 16)
                    version, auxiliaries, filename, aux, next_offset = self.read("<HHIII", address)
                    if version != 1:
                        _fail()
                    provider = self.text(filename)
                    if provider in providers or provider not in self.result.needed:
                        _fail()
                    providers.add(provider)
                    minimum, aux_size = 16, 16
                if not 1 <= auxiliaries <= MAX_VERSIONS or aux < minimum or aux % 4:
                    _fail()
                current = _add(address, aux)
                primary = None
                for a in range(auxiliaries):
                    self.reserve_version(current, aux_size)
                    if kind == "definition":
                        name, advance = self.read("<II", current)
                        value = self.text(name)
                        if a == 0:
                            primary = value
                            if digest != _elf_hash(value) or value in definitions:
                                _fail()
                            definitions.add(value)
                            versions[index] = (value, None)
                            if value == MARKER and flags != 0:
                                _fail()
                    else:
                        digest, flags, index, name, advance = self.read("<IHHII", current)
                        value = self.text(name)
                        if (flags & ~2 or not 2 <= index < 0x8000 or index in versions
                                or digest != _elf_hash(value) or (provider, value) in requirements):
                            _fail()
                        versions[index] = (value, provider)
                        requirements.add((provider, value))
                        if value == MARKER and flags != 0:
                            _fail()
                    if a + 1 == auxiliaries:
                        if advance != 0:
                            _fail()
                    else:
                        if advance < aux_size or advance % 4:
                            _fail()
                        current = _add(current, advance)
                if n + 1 == number:
                    if next_offset != 0:
                        _fail()
                else:
                    if next_offset < minimum or next_offset % 4:
                        _fail()
                    address = _add(address, next_offset)
        if (role == "libc" and (MARKER not in definitions or any(v == MARKER for _, v in requirements))
                or role == "libm" and (MARKER in definitions or ("libc.so.6", MARKER) not in requirements)):
            _fail()
        for index in range(count):
            value = self.read("<H", _add(self.need(0x6ffffff0), index * 2))[0] & 0x7fff
            if value > 1 and value not in versions:
                _fail()
        return versions


def _validate_plt(data, profile):
    """Private arithmetic fixture seam; production profile is never caller input."""
    if profile.role not in {"libc", "libm"}:
        _fail()
    image = _Image(data)
    tags = image.tags
    address, size, entry = tags[0x70000000], tags[0x70000001], tags[0x70000003]
    count = profile.jumps + profile.indirect
    if (address != profile.address or size != profile.table_bytes or entry != 16
            or entry & (entry - 1) or address % entry or not size or size % entry or size // entry != count):
        _fail()
    _add(address, size)
    code = image.slice(address, size, required=5, forbidden=2)
    if (image.need(20) != 7 or image.need(9) != 24 or image.need(2) != 24 * count):
        _fail()
    relocations = image.slice(image.need(23), 24 * count)
    symbol_count = image.symbols()
    image.versions(symbol_count, profile.role)
    got = {}
    for n in range(count):
        location = _add(address, 16 * n)
        chunk = code[n * 16:n * 16 + 16]
        if chunk[:6] != bytes.fromhex("f3 0f 1e fa ff 25") or chunk[10:] != bytes.fromhex("66 0f 1f 44 00 00"):
            _fail()
        slot = location + 10 + struct.unpack_from("<i", chunk, 6)[0]
        _add(slot, 8)
        if slot % 8 or slot in got:
            _fail()
        image.mapping(slot, 8, required=6, forbidden=1)
        got[slot] = location
    jumps = indirect = 0
    used = set()
    for offset in range(0, len(relocations), 24):
        slot, info, addend = struct.unpack_from("<QQq", relocations, offset)
        symbol, kind = info >> 32, info & 0xffffffff
        if slot not in got or slot in used:
            _fail()
        used.add(slot)
        if kind == 7:
            if not 0 < symbol < symbol_count or addend != got[slot] + 4:
                _fail()
            name, _info, _other, _section, value, symbol_size = image.read("<IBBHQQ", _add(image.need(6), symbol * 24))
            image.text(name)
            _add(value, symbol_size)
            jumps += 1
        elif kind == 37:
            if symbol != 0 or addend <= 0 or address <= addend < address + size:
                _fail()
            image.mapping(addend, 1, required=5, forbidden=2)
            indirect += 1
        else:
            _fail()
    if used != set(got) or jumps != profile.jumps or indirect != profile.indirect:
        _fail()
    return image.result


def _inspect_fixed_member(path, data):
    """Only two compiled, exact authenticated-origin members select this path."""
    profile = _PROFILES.get(path)
    if (profile is None or type(data) is not bytes or len(data) != profile.size
            or hashlib.sha256(data).hexdigest() != profile.digest):
        _fail()
    return _validate_plt(data, profile)
