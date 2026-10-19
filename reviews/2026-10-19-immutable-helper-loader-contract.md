# Immutable helper and loader boundary: proposed qualification contract

Status: draft for root and independent review. No implementation, launch,
credential use, host qualification or execution authority is added.
Base: published library PR327, commit
`8cb90dda62fd355638340c3949f7fa0e46872546`, descended from host PR324.
The published library, earlier contract and paused original references remain
unchanged. This draft does not replace their evidence or exclusions.

## Authorization and limits

[Issue239](https://github.com/hazeion/agent-os/issues/239) authorizes controller
implementation and qualification while withholding production dispatch until
its gates pass. The
[recorded prerequisite](https://github.com/hazeion/agent-os/issues/239#issuecomment-5922242612)
includes immutable fixed helper/loader closure and actual FUSE privilege and
teardown proof. Root authorized this contract draft, not a new runtime launch
implementation. Current ARCHITECTURE.md and IMPLEMENTATION_PLAN.md still govern
image leases, kernel ownership, provider isolation and admission.

This proposal covers only the existing fixed bwrap, squashfuse, fusermount3 and
mksquashfs identities and the exact library-origin component's loader/library
closure. It proposes no interpreter, Hermes source, package, helper, loader,
security-pocket or distribution replacement. The separate fourteen-member
sealed Hermes/Python image, dependency compatibility and current package safety
remain separate gates. A historical signed-byte comparison is neither current
security freshness nor permission to execute those bytes.

No supported operator Linux host is configured. Portable tests can establish
refusal and ownership logic; they cannot qualify Linux execution, privilege,
loader behavior, FUSE or production Project dispatch. No provider credential,
account, model, network capability, Run receipt or production witness is issued.

## Observed boundary gaps

The current source has these concrete paths; this draft changes none of them:

- ImmutableRuntimeImage seals and rehashes the runtime image, but its initial
  helper checks only installed root ownership/type/mode. Mount bootstrap runs
  through sys.executable and then execve of /usr/bin/squashfuse. Unmount launches
  /usr/bin/fusermount3 by pathname.
- namespace_command begins with /usr/bin/bwrap. Its later five sealed root
  bindings protect worker inputs; they do not retroactively protect bwrap's own
  initial loader/library resolution.
- LinuxWorkerScope begins through /usr/bin/systemd-run and sys.executable.
  Kernel, system manager, controller interpreter and bootstrap remain an
  explicit host trust base. The four-helper byte audit does not authenticate
  this larger bootstrap chain.
- The library component proves fixed static byte relations only. It does not
  prove which objects the actual loader maps, absence of undeclared dynamic
  loads, privileged helper behavior or immutable execution lifetime.

Image immutability and immutable helper execution must therefore be separate
claims. An ordinary open descriptor or root-owned pathname is insufficient:
file contents may remain writable through another reference. Executing one
sealed helper alone also leaves its interpreter and dependencies unresolved.

## Proposed narrow custody boundary

The first implementation, if separately approved, should establish one private
fixed-purpose byte-custody lease and synthetic refusal suite. It must not wire
existing mount, namespace, image-builder or Run launch paths to a new launcher.
A positive custody result proves only that exact reviewed bytes remain sealed
and owned. It is not executable readiness, authenticated provenance or a
persistable capability. There is no caller-supplied trusted report, callback,
parser profile, command, helper selector, environment or generic exec service.

1. Reuse the exact authenticated archive/member checks from the library slice;
   never elevate a caller-constructed result object into provenance. Capture
   only its closed regular members and aliases, within its existing input and
   object bounds. Changed bytes, tuple, alias, graph or unknown dynamic tags
   refuse through the same reviewed checks.
2. Keep captured objects in owner-private storage until terminal validation.
   For every retained regular member, including each helper, loader and
   library, require kernel-enforced write, grow, shrink and seal seals, then
   re-read and hash the sealed descriptor. Reject
   partial sealing, writable shared mappings, wrong size, descriptor reuse,
   partial writes, duplicate identities or allocation failure. Names are not
   identity. Close-on-exec remains default; future explicit handoff must list
   each descriptor and purpose.
3. Retain one parent-owned lease over the exact descriptors until every owned
   consumer is proved closed. No close-and-reopen by a mutable pathname. No
   eviction, replacement or reference release while a child or mount may use
   the bytes. Identity/generation mismatch invalidates the operation rather
   than selecting another object. Unknown cleanup retains ownership evidence
   and blocks new use; it does not claim successful teardown.
4. Preserve the existing bounded worker/capture limits and absolute deadline.
   This custody stage may not reset a deadline for each object, decoder or
   cleanup attempt. Temporary roots are deleted only after owned workers and
   descriptors are reconciled. Signals target only the already owned process
   identity; no discovered PID or global process search authorizes control.

The authenticated worker-to-parent byte/descriptor transfer and lifetime
protocol is unresolved. The current freely constructible origin result cannot
authorize bytes recaptured later. No authenticated flag or result object may
stand in for byte custody; no cross-boundary reopen or repeated inspection may
silently replace the exact authenticated objects with another capture. Before
any custody code is approved, a follow-up must choose a reviewed fixed, bounded
ownership and descriptor-handoff design that preserves same-byte identity from
authentication through sealing, parent receipt, terminal validation and closure,
including failed or partial handoff. The custody stages above specify required
properties, not an approved transfer implementation.

A whole immutable executable namespace is still required before actual dynamic
helper launch. This draft deliberately does not choose an unreviewed privileged
mount/bootstrap mechanism to obtain it. Before launch implementation approval,
a follow-up design must bind the exact loader and library filesystem seen from
first instruction through teardown, including the initial interpreter lookup,
cache/preload/audit paths, hwcaps selection, dlopen/NSS and child helper paths.
Neither LD_LIBRARY_PATH nor invoking a copied loader with a library-path option
is sufficient evidence of that complete property. The ordinary ELF API remains
strict; the two authenticated glibc profiles do not become a global override.

## Privilege and teardown are separate gates

A sealed memfd copy must not be treated as preserving fusermount3's installed
privilege semantics. Direct loader invocation must not be used to imply the
same credential transition as kernel execution of the original file. No chmod,
setuid bit, file capability, privileged broker or new namespace/mount policy is
authorized by this draft. If the supported unprivileged host cannot mount and
unmount through the exact qualified path, qualification fails closed.

The existing runtime image lease contract stays intact: exact mount generation
and target identity, read-only/nosuid/nodev state, retained roots and worker
references, bounded probes, pidfd/start identity and owned daemon closure.
Active references, replaced mounts, missing evidence, busy unmounts or unclosed
probes refuse. No lazy detach, recursive mount deletion or underlying directory
delete before verified mount absence. Failed startup must reconcile any late
owned mount. A cleanup timeout remains uncertain and cannot settle a provider
operation, release execution authority or be hidden by a successful child exit.

## Synthetic refusal strategy

Meaningful tests should exercise the real capture, hash, seal-verification,
reference and cleanup decisions, substituting only unavailable kernel effects.
They should cover complete custody of the exact fixture graph plus:

- source symlink/FIFO/hardlink/permission/identity races; byte changes before,
  during and after capture; unknown member, alias loop and extra unused object;
- missing/partial seals, post-seal hash mismatch, wrong size, open writable
  mapping, descriptor replacement/reuse and premature reference release;
- ordinary parser rejection of tagged libraries and authentication failure
  before special profile selection; a forged positive result cannot bypass it;
- per-object deadline reset attempts, aggregate limits, short writes, child
  exit with live descendant, uncertain closure and source/root retention;
- refused launch without qualified immutable loader namespace or proven FUSE
  privilege, without substituting host libraries or installed helper paths;
- busy/replaced/late mounts, leaked roots, reused PID, missing pidfd evidence,
  mount absence without daemon closure and daemon exit without mount absence.

Tests must not execute helper ELF, load libraries or emulate a successful
production witness. Existing ordinary parser, static graph, runtime image and
worker-scope contracts remain regression coverage. No new scanner exclusions,
threshold changes or mirror tests that merely compare configuration strings.

## Required actual Linux evidence before launch integration

A supported host and separately reviewed launch design must demonstrate exact
executed helper, interpreter and mapped object identities under source/path
replacement attacks; enforced write rejection; absence of undeclared loader
inputs; actual glibc rewrite/IFUNC behavior; credential and capability outcomes;
FUSE mount options/generation and verified teardown under busy and interrupted
conditions; descriptor/process/cgroup closure; and unchanged worker isolation.
The Linux kernel, system manager, trusted bootstrap and inspection primitives
must be stated explicitly rather than claimed to be self-authenticated.

Missing host, unsafe host policy, unsupported privilege, unbounded dynamic
loading or uncertain cleanup is a failed qualification. No portable/mock
positive substitutes for this evidence. Current dependency and Hermes-source
blockers, provider policy/consent/live qualification and final admission remain
independent. Root and independent review are required before any source work.

## Primary semantics reviewed

The Linux [memfd manual](https://man7.org/linux/man-pages/man2/memfd_create.2.html)
describes mutable anonymous files and optional sealing; a name is diagnostic.
[execveat](https://man7.org/linux/man-pages/man2/execveat.2.html) supports execution
through an exact descriptor, but that alone says nothing about dependency
closure. [execve](https://man7.org/linux/man-pages/man2/execve.2.html) documents
interpreter loading and credential-transition conditions.
The [dynamic-loader manual](https://man7.org/linux/man-pages/man8/ld.so.8.html)
documents search and environment/secure-execution behavior. These are design
constraints, not measurements of a supported host or permission to use a new
launcher. The reviewed glibc rewrite and ABI-marker evidence remains in the
published signed-library contract; this draft grants it no execution authority.
