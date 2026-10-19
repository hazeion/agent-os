from dataclasses import FrozenInstanceError, replace
import hashlib
import struct
import unittest
from unittest.mock import patch

from mentat import project_runtime_host_trust as host
from mentat.project_runtime_elf import RuntimeElfError, inspect_elf, inspect_host_elf
from tests.test_project_runtime_elf import fixture


def elf(*, needed=(), executable=False, tag=21, value=0):
    raw = bytearray(fixture(needed=needed, rpath="/fixture-build-path"))
    # Replace fixture RPATH with an inert DEBUG declaration by default.
    struct.pack_into("<qQ", raw, 320 + 16 * (2 + len(needed)), tag, value)
    if not executable:
        struct.pack_into("<I", raw, 176, 0)  # No PT_INTERP on shared libraries.
    return bytes(raw)


class HostClosureCandidateTests(unittest.TestCase):
    def members(self):
        return (
            ("/usr/bin/squashfuse", elf(needed=("libc.so.6",), executable=True)),
            ("/usr/lib/x86_64-linux-gnu/libc.so.6", elf()),
            ("/usr/lib64/ld-linux-x86-64.so.2", "../lib/x86_64-linux-gnu/ld-linux-x86-64.so.2"),
            ("/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2", elf()),
        )

    def synthetic_pin(self, members):
        # This patch belongs only to the unit fixture. Public API has no pin
        # argument, fixture manifest, production override or trust constructor.
        raw = members[0][1]
        return patch.dict(host._HELPERS, {"squashfuse": replace(
            host._HELPERS["squashfuse"], member_size=len(raw),
            member_digest=hashlib.sha256(raw).hexdigest(),
        )})

    def test_closure_is_exact_immutable_static_evidence_with_unresolved_trust(self):
        members = self.members()
        with self.synthetic_pin(members), patch("builtins.open", side_effect=AssertionError("host path read")):
            result = host.audit_fixed_helper_closure("squashfuse", members)
        self.assertEqual(result.helper, "squashfuse")
        self.assertEqual(len(result.members), 3)
        self.assertEqual(len(result.aliases), 1)
        self.assertEqual(len(result.edges), 2)
        self.assertIn("signed-library-provenance", result.required_qualification)
        self.assertIn("fuse-privilege-and-verified-teardown", result.required_qualification)
        with self.assertRaises(FrozenInstanceError):
            result.helper = "bwrap"
        self.assertFalse(hasattr(result, "ready"))

    def test_real_fixed_pins_never_accept_synthetic_or_unknown_helper(self):
        for helper in ("squashfuse", "bwrap", "fusermount3", "mksquashfs", "sh", "/usr/bin/squashfuse"):
            with self.subTest(helper=helper), self.assertRaises(host.HostClosureError):
                host.audit_fixed_helper_closure(helper, self.members())

    def test_changed_helper_bytes_cannot_reuse_a_fixed_pin(self):
        members = self.members()
        changed = ((members[0][0], members[0][1] + b"changed"), *members[1:])
        with self.synthetic_pin(members), self.assertRaises(host.HostClosureError):
            host.audit_fixed_helper_closure("squashfuse", changed)

    def test_missing_interpreter_dependency_and_unrelated_bytes_are_refused(self):
        members = self.members()
        for changed in (members[:1], members[:2], (members[0], *members[2:]),
                        (*members, ("/usr/lib/unrelated.so", elf()))):
            with self.subTest(members=len(changed)), self.synthetic_pin(members), self.assertRaises(host.HostClosureError):
                host.audit_fixed_helper_closure("squashfuse", changed)

    def test_recursive_dependencies_are_required_and_audited(self):
        members = self.members()
        recursive = (members[0], (members[1][0], elf(needed=("libsecond.so",))), *members[2:])
        with self.synthetic_pin(members), self.assertRaises(host.HostClosureError):
            host.audit_fixed_helper_closure("squashfuse", recursive)
        complete = (*recursive, ("/usr/lib/x86_64-linux-gnu/libsecond.so", elf()))
        with self.synthetic_pin(members):
            self.assertEqual(len(host.audit_fixed_helper_closure("squashfuse", complete).edges), 3)
        unsafe = (*recursive, ("/usr/lib/x86_64-linux-gnu/libsecond.so", elf(tag=0x7fffffff, value=1)))
        with self.synthetic_pin(members), self.assertRaises(host.HostClosureError):
            host.audit_fixed_helper_closure("squashfuse", unsafe)

    def test_ambiguous_distinct_targets_are_not_silently_resolved_by_search_order(self):
        members = (*self.members(), ("/usr/lib64/libc.so.6", elf(tag=30, value=8)))
        with self.synthetic_pin(members), self.assertRaises(host.HostClosureError):
            host.audit_fixed_helper_closure("squashfuse", members)

    def test_alias_cycles_escaping_paths_and_unbounded_chains_are_refused(self):
        members = self.members()
        for target in ("/home/owner/lib.so", "../../../../secret", "//usr/lib/private.so",
                       "$ORIGIN/private.so", "ld-linux-x86-64.so.2", "x" * 513):
            changed = (*members[:2], (members[2][0], target), members[3])
            with self.subTest(target=target), self.synthetic_pin(members), self.assertRaises(host.HostClosureError):
                host.audit_fixed_helper_closure("squashfuse", changed)
        chain = tuple((f"/usr/lib/chain{index}", f"chain{index+1}") for index in range(17))
        changed = (*members[:2], (members[2][0], "/usr/lib/chain0"), *chain, ("/usr/lib/chain17", elf()))
        with self.synthetic_pin(members), self.assertRaises(host.HostClosureError):
            host.audit_fixed_helper_closure("squashfuse", changed)

    def test_paths_types_duplicates_counts_and_bytes_are_bounded_before_parsing(self):
        members = self.members()
        cases = ((), list(members), (*members, members[1]),
                 (*members, ("/usr/lib/../lib/private.so", elf())),
                 (*members, ("/lib/private.so", elf())),
                 (*members, ("/usr/lib/private.so", bytearray(b"ELF"))),
                 tuple(members[0] for _ in range(host.MAX_MEMBERS + 1)))
        for changed in cases:
            with self.subTest(kind=type(changed).__name__), self.assertRaises(host.HostClosureError):
                host.audit_fixed_helper_closure("squashfuse", changed)
        with self.synthetic_pin(members), patch.object(host, "MAX_BYTES", 10), \
                patch.object(host, "inspect_host_elf") as inspect, self.assertRaises(host.HostClosureError):
            host.audit_fixed_helper_closure("squashfuse", members)
        inspect.assert_not_called()

    def test_runtime_default_parser_retains_its_existing_rpath_contract(self):
        self.assertEqual(inspect_elf(fixture()).rpath, ("$ORIGIN/../lib",))
        with self.assertRaises(RuntimeElfError):
            inspect_host_elf(fixture())

    def test_host_policy_refuses_unrepresented_dynamic_loading_features(self):
        for tag, value in ((16, 0), (22, 0), (0x6ffffefa, 1), (0x7ffffffd, 1),
                           (0x7fffffff, 1), (0x6ffffdfc, 0), (0x6ffffdfd, 0),
                           (0x60000000, 0), (0x6ffffef9, 0),
                           (30, 1), (30, 4), (0x6ffffffb, 4),
                           (0x6ffffffb, 0x800), (0x6ffffffb, 0x80)):
            with self.subTest(tag=tag, value=value), self.assertRaises(RuntimeElfError):
                inspect_host_elf(elf(tag=tag, value=value))
        for tag, value in ((20, 7), (30, 8 | 16), (0x6ffffffb, 1 | 8 | 0x08000000)):
            with self.subTest(tag=tag):
                self.assertEqual(inspect_host_elf(elf(tag=tag, value=value)).needed, ())

    def test_duplicate_host_flags_are_refused(self):
        raw = bytearray(elf(tag=30, value=8))
        # Replace the terminator with a duplicate flag and add a new terminator.
        struct.pack_into("<qQ", raw, 320 + 16 * 3, 30, 8)
        struct.pack_into("<qQ", raw, 320 + 16 * 4, 0, 0)
        struct.pack_into("<Q", raw, 120 + 32, 16 * 5)
        struct.pack_into("<Q", raw, 120 + 40, 16 * 5)
        with self.assertRaises(RuntimeElfError):
            inspect_host_elf(bytes(raw))

    def test_wrong_architecture_interpreter_and_nonelf_are_not_host_evidence(self):
        wrong_machine = bytearray(elf()); struct.pack_into("<H", wrong_machine, 18, 183)
        for raw in (b"plain text", bytes(wrong_machine), fixture(interpreter="/usr/lib/alternate-loader", rpath="/fixture")):
            with self.subTest(raw=raw[:4]), self.assertRaises(RuntimeElfError):
                inspect_host_elf(raw)


if __name__ == "__main__":
    unittest.main()
