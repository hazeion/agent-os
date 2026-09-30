# Sealed system-library projection

Add selected immutable system libraries to the runtime image and bind all five
source/venv/Python/system roots from the same read-only FUSE generation. The
sealed-library namespace mode must never open or mount raw host /usr/lib or
/usr/lib64 and must refuse a missing image/report/root rather than fall back.
No provider, Agent capability, Run admission or execution-guard change.

Use bounded nonexecuting ELF64 metadata parsing for the fixed Linux x86-64 or
AArch64 target: program headers, interpreter, direct dependencies, SONAME and
RPATH/RUNPATH. Validate unique bounded virtual-to-file string mappings, including
the real standalone Python table spanning adjacent segments, and reject
malformed bounds/overlaps, unresolved tokens and unsafe names. ORIGIN-qualified
dependencies must resolve inside selected immutable roots or fixed system
roots. No ldd or scanned executable is invoked.

Collect a strict static dependency superset, copy only root-owned bounded
system files/symlink chains under fixed public library roots, preserve aliases,
verify copied digests and recursively inspect selected bytes. Bound members
and total bytes. This is not a simulator of complete loader ordering or proof
of every dlopen/NSS/locale/plugin path. The exact built operation is qualified
separately. [The Linux loader contract](https://man7.org/linux/man-pages/man8/ld.so.8.html)
distinguishes direct dependency paths, ORIGIN expansion and RPATH/RUNPATH lookup.

Some public standalone dependencies retain an unused build-time RPATH such as
/tools/deps/lib. Preserve original bytes, record it as a negative namespace
mount invariant and never use it as a library source. Reject writable/input/
device/process paths, runtime/system mount aliases or ancestors, relative/empty
components and unresolved tokens. The fixed namespace must verify every such
recorded path is absent before the CLI starts, with no later capability to
create/mount it. Mount-map changes require requalification.

Test parser hostility/adjacent mappings, source ownership/symlink escape,
unreachable path rejection, no raw host mounts, missing-image refusal and real
unchanged official Hermes/PIL/accepted image/canonical fake-broker flow from
the complete five-root image. Public package origin, helper qualification,
live credentials/model behavior and durable Run admission remain separate
gates. Obtain two independent reviews, repair findings, then full PR.

Final combined actual Linux group: 110 tests pass, with no skips. The public
candidate includes 14 selected system members (7,768,040 bytes) and all five
roots are bound from its sealed image. The unchanged official 0.21.5/PIL/
accepted PNG/durable fake-broker path passes within the original 20-second
policy; one integration run takes 8.76 seconds after fixed native synthetic
configuration replaces ten CLI startups. This is observed test duration, not a
hosted CI or live-provider performance claim.

Windows runs 19 portable methods and skips 15 Linux-only cases in the focused
library/ELF/namespace group. Exact wheel/sdist public inventory/RECORD and
installed six-module byte equality pass. Final kernel readback shows no owned
image mounts. An unread-body Windows refusal fixture was corrected to transmit
headers only for unsupported paths, with an exact body-read bomb; body-dependent
requests, status assertions and deadlines remain unchanged.

Reviews caught missing recursive system-ELF RPATH checks, mid-span ELF LOAD
ambiguity and double-slash negative-path aliases. All received refusal tests
and corrections, preserving adjacent valid Python mappings and original binary
bytes. Package-origin, full dlopen coverage, helper/model/credential trust and
production Run authority remain unverified.
Both final independent re-reviews are clear after those corrections. Exact
final artifact inventory and installed-module equality checks ran on the
corrected code. The library candidate was regenerated through the final
recursive audit before the full 110-test pass; its machine-local metadata and
paths remain in ignored operator artifacts.
