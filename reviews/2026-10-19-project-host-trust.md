# Fixed helper ELF closure prerequisite

Status: implemented locally; independent review and actual Linux qualification pending.

Base: `2324cb1ffb25407f20a1a7c7f6b341e5cf357bb1`, branch
`codex/project-host-trust`. The owner authorized credential-free host-trust
prerequisites beneath the unchanged official-Hermes controller. Live issue
239 identifies immutable fixed helper/loader closure, signed system libraries
and actual FUSE privilege/teardown as independent missing gates. Issue 234
retains separate provider-policy implementation approval, account consent,
live qualification and production admission. None is granted here.

## Contract and implementation

The existing image lease checks root ownership/mode before reopening fixed
host helpers. Its hash-pinned SquashFS image does not make those helper or
loader bytes immutable. The separate signed-origin inspector proves four
selected Ubuntu 26.04 amd64 helper identities, not their dynamic closure or
execution. In particular, copying a setuid fusermount helper into a memfd would
not preserve its privilege semantics. This slice does not approximate that
qualification or change the image lease.

`audit_fixed_helper_closure` is a nonexecuting private validator over bounded
immutable captured bytes and explicit alias text. It accepts only the existing
four helper names and exact member size/SHA256 identities in
`project_system_origin.PINS`. There is no caller pin/manifest override, path
reader, subprocess, credential access, public route, saved readiness state,
trust capability or launch integration. Successful output is immutable static
candidate evidence. Supplied library hashes are not signed provenance.

All members must be consumed by the selected helper's recursively inspected
DT_NEEDED/interpreter graph. Alias names are canonical, alias targets stay in
the existing Ubuntu library roots, loops/depth, aggregate bytes and member
counts are bounded, and ambiguous targets or missing/unused objects fail.
No search through the host loader cache or filesystem is performed.

The host-only ELF policy requires amd64 and the fixed standard interpreter.
It rejects RPATH/RUNPATH, FILTER/AUXILIARY/CONFIG, audit/depaudit,
SYMBOLIC/TEXTREL, FEATURE/POSFLAG, unknown dynamic tags, duplicate singleton
tags and unsupported FLAGS/FLAGS_1 bits. Only NOW/STATIC_TLS and
NOW/NODELETE/PIE flag bits are admitted. Ordinary ELF inspection retains its
existing behavior, including runtime ORIGIN paths. The strict policy is an
explicit new entry point, not a new restriction on current image qualification.

The output retains explicit requirements for signed-library provenance,
helper/library security review, actual loader behavior, immutable helper
execution, and FUSE privilege/verified teardown. Preload, loader cache,
hwcaps, dlopen/plugin behavior and helper implicit subprocesses are not proven
by a declared dependency graph. A supplied member tuple or copied dataclass
cannot be used as production trust. Production no-dispatch gates are untouched.

## Verification strategy and evidence

Portable tests use tiny adversarial ELF fixtures, and patch helper pins only
inside unit fixtures to exercise positive graph behavior. With real fixed pins,
those fixtures are refused. Tests cover exact/changed helper bytes, recursive
dependencies, aliases/cycles/escape/depth, ambiguity, missing/unused objects,
immutable output, bounded input and refusal of unsupported dynamic loading.
The existing generic ELF and sealed-library contracts run alongside them.

Four public Ubuntu archives were fetched into task-owned temporary storage
from the exact existing `PINS` filenames. Archive sizes/SHA256 and selected
regular-member sizes/SHA256 matched those pins before nonexecuting inspection.
All four real helper declarations pass the final strict policy: bubblewrap
has three direct DT_NEEDED declarations, squashfuse seven, fusermount3 one,
and mksquashfs seven. No downloaded code was imported or executed. The local
zstd tool decoded these exact pinned public bytes only. This reuses existing
reviewed pin identities; it is not a fresh signed-index verification.

The initial closed-tag policy accidentally omitted the ordinary DT_PLTREL
declaration and refused the real helpers. Adding that represented relocation
tag, with a portable positive regression, fixes the compatibility error.
Earlier inspection results are not substituted for final-policy evidence.

The final selected run discovers 43 methods across host-closure, ordinary ELF,
runtime-library and image modules: 25 pass and 18 actual-Linux methods skip.
All 12 new portable host-closure methods pass. `git diff --check` passes.

Actual Linux mounting, immutable helper execution, signed loader/library
closure, privilege retention, worker supervision and FUSE teardown were not
run on this macOS host. Existing Linux-only library/image tests remain skipped,
not passed. No owner configuration, mounts, services, sysctls, provider accounts
or credentials were read or changed. This slice is not host readiness or issue
acceptance. Parent integration requires two independent reviews before push.
