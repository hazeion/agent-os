from __future__ import annotations

import struct
import unittest

from mentat.project_runtime_elf import inspect_elf, RuntimeElfError


def fixture(*, needed=("libc.so.6",), interpreter="/lib64/ld-linux-x86-64.so.2", rpath="$ORIGIN/../lib", machine=62,
            split_strings=False):
    strings = bytearray(b"\0")
    offsets = []
    for name in needed:
        offsets.append(len(strings)); strings.extend(name.encode() + b"\0")
    rpath_offset = len(strings); strings.extend(rpath.encode() + b"\0")
    dynamic = [(5, 0x1000 + 512), (10, len(strings)), *[(1, value) for value in offsets], (15, rpath_offset), (0, 0)]
    image = bytearray(512 + len(strings))
    identifier = b"\x7fELF\x02\x01\x01" + b"\0" * 9
    struct.pack_into("<16sHHIQQQIHHHHHH", image, 0, identifier, 3, machine, 1, 0, 64, 0, 0, 64, 56, 4 if split_strings else 3, 0, 0, 0)
    split = 522 if split_strings else len(image)
    struct.pack_into("<IIQQQQQQ", image, 64, 1, 4, 0, 0x1000, 0, split, split, 4096)
    struct.pack_into("<IIQQQQQQ", image, 120, 2, 4, 320, 0x1140, 0, len(dynamic)*16, len(dynamic)*16, 8)
    interp = interpreter.encode() + b"\0"
    struct.pack_into("<IIQQQQQQ", image, 176, 3, 4, 448, 0x11c0, 0, len(interp), len(interp), 1)
    image[448:448+len(interp)] = interp
    if split_strings:
        struct.pack_into("<IIQQQQQQ", image, 232, 1, 4, split, 0x1000+split, 0, len(image)-split, len(image)-split, 1)
    for index, pair in enumerate(dynamic):
        struct.pack_into("<qQ", image, 320 + 16*index, *pair)
    image[512:] = strings
    return bytes(image)


class RuntimeElfTests(unittest.TestCase):
    def test_nonelf_is_not_executed_or_interpreted(self):
        self.assertIsNone(inspect_elf(b"#!/bin/sh\nexit 1\n"))

    def test_exact_declarations_are_bounded_immutable_metadata(self):
        value = inspect_elf(fixture())
        self.assertEqual(value.needed, ("libc.so.6",))
        self.assertEqual(value.interpreter, "/lib64/ld-linux-x86-64.so.2")
        self.assertEqual(value.rpath, ("$ORIGIN/../lib",))
        self.assertEqual(value.machine, 62)

    def test_string_table_can_span_only_contiguous_unambiguous_load_segments(self):
        self.assertEqual(inspect_elf(fixture(split_strings=True)).needed, ("libc.so.6",))
        wrong = bytearray(fixture(split_strings=True))
        struct.pack_into("<Q", wrong, 232+8, 523)  # Physical hole in the mapping.
        with self.assertRaises(RuntimeElfError): inspect_elf(bytes(wrong))

    def test_origin_qualified_dependency_is_preserved_for_containment_validation(self):
        self.assertEqual(inspect_elf(fixture(needed=("$ORIGIN/../lib/libpython3.13.so.1.0",))).needed,
                         ("$ORIGIN/../lib/libpython3.13.so.1.0",))
        with self.assertRaises(RuntimeElfError): inspect_elf(fixture(needed=("$ORIGIN/$LIB/libprivate.so",)))

    def test_midspan_same_or_conflicting_load_overlap_is_rejected(self):
        for second_offset in (522, 523):
            payload = bytearray(fixture(split_strings=True))
            struct.pack_into("<Q", payload, 64+32, len(payload))
            struct.pack_into("<Q", payload, 64+40, len(payload))
            struct.pack_into("<Q", payload, 232+8, second_offset)
            with self.subTest(offset=second_offset), self.assertRaises(RuntimeElfError):
                inspect_elf(bytes(payload))
        wrong = bytearray(fixture(split_strings=True))
        struct.pack_into("<Q", wrong, 232+16, 0x1000+521)  # Virtual overlap.
        with self.assertRaises(RuntimeElfError): inspect_elf(bytes(wrong))

    def test_unsupported_loader_tokens_paths_and_duplicate_names_fail(self):
        for payload in (fixture(needed=("../secret.so",)), fixture(needed=("libc.so.6", "libc.so.6")),
                        fixture(interpreter="/home/owner/loader"), fixture(rpath="relative"),
                        fixture(rpath="$LIB/foo"), fixture(rpath="$ORIGIN::/usr/lib"), fixture(machine=3)):
            with self.subTest(payload=payload[:24]), self.assertRaises(RuntimeElfError):
                inspect_elf(payload)

    def test_truncated_wrong_class_and_overlapping_string_maps_fail(self):
        good = fixture()
        for length in (4, 32, 63, 100, len(good)-1):
            with self.assertRaises(RuntimeElfError):
                inspect_elf(good[:length])
        wrong = bytearray(good); wrong[4] = 1
        with self.assertRaises(RuntimeElfError): inspect_elf(bytes(wrong))
        wrong = bytearray(good); struct.pack_into("<Q", wrong, 120+32, 999999)
        with self.assertRaises(RuntimeElfError): inspect_elf(bytes(wrong))


if __name__ == "__main__":
    unittest.main()
