# Immutable runtime image lease

Replace mutable source/venv/Python directory bytes with one digest-verified,
kernel-sealed SquashFS image served through a fixed owned read-only FUSE mount.
This is a private runtime component; no provider, Agent capability, Run
admission, credential source or execution guard changes. Image-origin trust,
dependency provenance, model qualification and system-library closure remain
distinct prerequisites. Do not call a sealed arbitrary image a qualified
official runtime.

The parent reads one bounded no-follow image file, checks size/SHA, seals its
memfd against writes/growth/shrink/further seals and verifies the sealed bytes.
Only the image FD reaches a fixed foreground system squashfuse command; the
worker never receives /dev/fuse or the image FD. A fixed bootstrap sets parent
death and nondumpable behavior before exec. Pin the daemon generation/pidfd,
owned mountpoint parent and kernel mount identity; demand FUSE and ST_RDONLY.
Potentially blocking FUSE inspection and source sentinels run only in a fixed
disposable probe with a one-second receive wall and bounded kill/reap. It
returns O_PATH handles; the parent uses kernel-only mount/fd metadata. An
unreaped probe suspends further probing and cleanup, retaining its ownership.
Only source/venv/Python roots from that exact mount may be bound to their
original private virtual runtime paths, preserving unchanged CLI/shebang/PTH
behavior. No fallback to mutable source paths on failure.

Hold image/mount ownership while prepared namespaces use its roots. Recheck
daemon/mount before handoff and terminal readback. Close worker scopes first,
release their root descriptors, then unmount only the exact owned mount with
verified disappearance, reap its daemon and close the image. Busy or ambiguous
cleanup retains ownership; no lazy detach or recursive deletion of a mount.
The private mountpoint is created by the factory, never caller/browser input.
Each handed-off scope owns a separate image reference until verified scope
closure, even when its PreparedNamespace closes early. Startup records the
kernel mount generation before probing, and cannot adopt a replacement probe
identity. Normal cleanup proves both that mount ID and target/submounts absent.
The single-threaded decoder has fixed 768 MiB address space, 120 cumulative CPU
seconds, 64 descriptors and zero core-dump limits. These are a separate helper
budget, not a claim that it lies within the worker's cgroup accounting.

Test kernel write denial, original image mutation after sealing, descriptor
mount replacement, daemon loss, missing tools/platforms, busy cleanup and
source alias behavior. Also prepare a separate secret-free operator snapshot
from the pinned public Git tree and verified dependency inventory, then run
the unchanged stock CLI through the image with a fake broker. Host /usr/lib
and /usr/lib64 remain separate mutable inputs in this component and must be
sealed/qualified before production. Obtain two independent reviews and repair
findings before a full PR. Keep complete runtime and garage acceptance open.

Final image suite: 15 actual Linux tests pass, including the unchanged official
0.21.5 CLI from sealed candidate source/venv/Python, canonical accepted PNG,
one durable synthetic completion, early prepared-input close, exact worker
termination and mounted-image cleanup. The broader 91-test Linux group passed
before the final mount-ID/pending-probe corrections; the final 15-test rerun
includes both corrected regressions and stock integration. Windows executes
13 portable image/namespace/scope contracts and skips 35 Linux-only checks.

The ignored operator candidate contains the exact pinned public Git object
tree and RECORD-verified installed dependency members; it excludes repository
metadata, ignored owner files and installed direct URL metadata. This documents
candidate assembly only, not package-origin or complete system-library trust.
No owner Hermes home/configuration/credentials, live provider, owner service,
Run admission or execution guard was touched. The snapshot and machine-local
paths remain outside tracked data and documentation.

Both independent final re-reviews are clear after correcting worker-held
ownership, parent-blocking FUSE calls, mount-before-identification recovery,
recorded/probed mount mismatch and unresolved-probe accumulation. The final
portable bootstrap correction imports resource only after its Linux guard;
two Windows refusal checks and two actual Linux mount/resource checks pass.
Final wheel/sdist exact public inventory/RECORD and installed-module byte
equality checks pass. Owned test mounts, including the explicitly recovered
failed identity fixtures, are absent from final kernel mount readback.
