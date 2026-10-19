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

## Concrete custody protocol proposal for review

This section proposes the previously unresolved handoff. It is design only and
requires root and independent approval before any custody code. It selects
worker verification into sealed objects followed by descriptor transfer;
it does not select an immutable loader namespace or authorize execution.

### Fixed operation and ownership

Add a separate private fixed custody operation beside the existing origin
comparison; keep the public comparison API and its constructible result
unchanged. Reuse its exact trusted worker bootstrap, disposable input capture,
OS inspection primitives, owned-group lifetime and final source revalidation.
No new trusted interpreter, privileged process or generic transport is added.
The worker's trusted verification code remains the authenticity boundary;
this protocol does not protect a compromised controller, kernel or worker.

The parent creates one unnamed AF_UNIX SOCK_SEQPACKET socketpair before
spawning that exact worker. Both endpoints start close-on-exec. Only the worker
endpoint is explicitly inherited by the one owned worker; it is closed in the
parent immediately after spawn. The worker closes it in every decoder child
through close_fds and an exact pass_fds list. No bound pathname, listener,
connection acceptance, external client or caller-supplied socket exists.

Enable SO_PASSCRED on both receiving endpoints before spawning. Every received
packet must carry exactly one kernel SCM_CREDENTIALS record with the expected
PID and real UID/GID (not effective IDs): the parent expects its unreaped
owned worker identity, and the
worker expects its original parent. Retain the parent's existing start-identity
and pidfd/group controls. SO_PEERCRED on a pre-fork socketpair identifies the
creator at socketpair time, so it must not be mistaken for the child's identity.
This nonprivileged worker must not gain credentials or share its endpoint with
children. A matching nonce alone does not establish sender identity.

Use one parent-generated 32-byte random operation nonce, one protocol version,
and monotonically increasing sequence numbers. Only this parent's active
invocation knows the expected nonce. All messages use bounded UTF-8 JSON with
strict duplicate-key, exact-key/type and termination checks; no raw package,
archive or private path text is returned. This is a fixed internal wire shape,
not a reusable message or execution framework.

### Authentication, sealing and packet order

1. The parent sends one START packet, at most 4 KiB, containing the fixed
   operation name, nonce and parent-created absolute monotonic deadline plus
   the existing bounded input-root reference. No descriptor is attached.
2. The worker performs the existing complete authentication, package grammar,
   archive/member selection, two fixed ELF profiles and four shared-graph
   comparisons over its one captured input set. It must include all four
   helpers as retained regular members. Libraries and the loader authenticate
   through the captured signed archive chain. In this operation the four helper
   ELF inputs bind only to the reviewed compiled size/SHA256 pins in
   project_system_origin.PINS; the fixed19 inputs contain no helper archives,
   so this operation does not reauthenticate helper archive membership. Seal
   and transfer the exact captured helper bytes that passed those pins. The
   separate helper-origin gate remains independent and unresolved here.
   No parent recapture, source reopen or caller report supplies member bytes.
3. For each selected regular member, copy directly from those authenticated
   immutable Python bytes into one fresh memfd, apply F_SEAL_WRITE,
   F_SEAL_GROW, F_SEAL_SHRINK and F_SEAL_SEAL, then use bounded pread on that
   descriptor to recompute size/hash and parse the exact sealed bytes. Bind
   the four graph comparisons to those sealed reads. Do not send a manifest
   before this sealed-object validation finishes. No mmap or executable use.
4. Send one MANIFEST packet without descriptors, at most the existing 16 KiB
   result bound. It contains nonce, sequence, the existing fixed snapshot and
   package identities, ordered regular rows (virtual path, size, SHA256,
   st_dev/st_ino from the sealed object and a fixed trust class), ordered alias
   path/text rows and the four static comparisons. The only trust classes are
   signed-library-archive for the13 library/loader objects and compiled-helper-
   pin for the four fixed helpers. Class selection is internal by fixed member
   identity; callers cannot supply or override it. This is no global
   authenticated/provenance flag and does not clear either qualification gate. Order is lexical virtual path order, not local FD
   number. Aliases remain bounded authenticated metadata; do not materialize
   filesystem links or attach an FD for them.
5. Transfer one MEMBER packet per regular row, in that exact order, with exactly
   one SCM_RIGHTS descriptor, one credentials record and nonce/sequence/index.
   Parent recvmsg uses MSG_CMSG_CLOEXEC and space for exactly the permitted
   rights and credentials. It owns every delivered FD immediately, even on a
   malformed packet. MSG_TRUNC, MSG_CTRUNC, unknown/multiple ancillary records,
   extra or missing rights, wrong ordering, duplicate object identity or wrong
   peer refuse. Close all actually delivered rights on refusal; rely on kernel
   truncation closure only for rights never delivered to userspace.
6. Parent verifies regular object type, size, device/inode, exact required
   seals, and a bounded pread hash from the received descriptor against that
   manifest row. SCM_RIGHTS refers to the same open file description, not an
   authenticated filename; pread avoids its shared mutable offset. The parent
   does not reauthenticate another capture or infer provenance from a report.
   Send one exact MEMBER_ACK only after successful validation. Worker retains
   its original descriptor until that ACK; lost ACK retains both references
   until cleanup. ACK never authorizes execution or source deletion.
7. After the last ACK, the worker repeats terminal source identity/privacy
   checks and drains its owned decoder descendants using the existing worker
   rules. Only then send one READY packet, without rights, binding nonce,
   manifest digest and final sequence. Worker holds the channel open awaiting
   RELEASE; it must not send another packet or create another child.
8. Parent accepts READY only after all rows are verified. Send RELEASE and
   close the sending direction. The worker must close its remaining owned
   descriptors/channel and exit normally with code0. Parent first waits for
   that exact owned worker's normal terminal evidence within the same original
   deadline, retaining all received FDs privately. Drain the receive side
   through EOF; any packet after READY, including another READY or extra
   rights, refuses. Success requires normal exit code0, EOF, no extra packets
   and proved group absence, all before that deadline. A crash, nonzero exit,
   timeout or parent-forced termination always refuses, even after valid READY.
   Only failure paths invoke bounded failure cleanup; killing a worker cannot
   manufacture successful terminal evidence. Publish a private custody lease
   only after all success conditions hold and the channel is closed. No JSON
   result or saved readiness record can recreate a lease.

The manifest's identity rows and fixed trust classes bind received kernel
objects to the owned worker's corresponding signed-library or compiled-helper
verification; they are not portable identities or independently trusted public
metadata. A fixed-byte custody lease preserves that per-member trust distinction in
its private metadata. It can expose bounded private byte reads and close only,
with no path, launch, witness or admission API. It cannot claim that all members
were authenticated by this operation or substitute for the independent helper-
origin gate. Every retained regular object, including
loader and libraries, stays sealed until the lease closes. Later execution
would require a separately reviewed launch capability, not this lease.

### Bounds and failure states

Keep the existing input, archive, capture and result bounds: 19 exact inputs,
80 MiB aggregate captured input, 32 MiB per decoded tar, 320 MiB aggregate scan,
32 MiB selected library bytes, alias depth16, worker512 MiB address space,
15 CPU seconds,64 descriptors and core size0. For this narrower custody
proposal, accept only the already inspected complete fixed selection of
17 regular objects (13 library/loader objects plus4 helpers) and10 aliases;
regular helper bytes add only the existing four compiled helper-size bounds.
A changed selection stops for review rather than extending this count. Do not
increase RLIMIT_NOFILE: transfer sequentially, close acknowledged worker copies,
and require an explicit FD accounting test for existing capture/decoder peaks,
17 retained members, socket and control descriptors before implementation.
If the existing64 limit cannot accommodate the complete staged sequence, refuse
and redesign ownership before changing any limit.

One 30-second absolute monotonic deadline begins before worker creation and
covers START, authentication, sealing, every transfer/hash/ACK, READY, RELEASE,
source revalidation and verified group/channel closure. No stage or per-object
retry resets it. No protocol retry or second worker is permitted. Nonblocking
socket operations check the same deadline; EAGAIN waits consume that budget.
A cleanup action cannot extend acceptance past the deadline. Existing bounded
owned-group cleanup remains mandatory even after failure; if closure cannot be
proved, retain ownership records and temporary capture state and reject the
operation. Never report a lease while cleanup is uncertain.

States are NEW, VERIFYING, TRANSFERRING, CLOSING, LEASED and CLOSED, with a
terminal FAILED or CLEANUP_UNCERTAIN outcome. Before LEASED no descriptor is
available to another consumer. On malformed input, EOF, peer change, deadline,
worker death, parent cancellation or partial handoff, enter CLOSING: close every
parent-delivered FD, terminate/reap only the already owned worker group, close
channels and remove captures only after closure proof. The worker closes all
of its retained FDs on a terminal error. Parent death makes the worker's socket
reach EOF, triggering the same local cleanup; this must be tested with real
Linux ownership rules before qualification. No claim is made that a killed
parent can publish cleanup evidence. The external supervisor must treat that
interruption as unqualified until reconciliation, not replay a previous lease.
A successful lease owns its17 FDs until explicit close; close is idempotent and
must not release a descriptor while any private read is active.

### Hostile protocol tests and actual evidence

Source-level tests should cover a complete exact ordered handoff using real
local descriptors where available, then inject wrong nonce/version/sequence,
old READY replay, crash/nonzero exit after READY, forced termination after
RELEASE, alias substitution, manifest mutation, partial send/EOF,
extra packets, missing/multiple rights, truncated payload/control, foreign
credentials, inherited child endpoint, changed identity and descriptor reuse.
Require real post-seal write/truncate rejection on Linux, not just a mocked
F_GET_SEALS result. Exercise shared-offset changes, incorrect hash/size/seals,
failed ACK after parent receive, worker exit after send before ACK, decoder
survival, parent death, deadline at every transition and cleanup uncertainty.
Assert exact ownership/FD counts and no lease publication on each failure.

Portable tests may substitute credentials/seals only to test refusal logic and
must identify that substitution. Actual Linux positive qualification requires
real SCM_RIGHTS/SCM_CREDENTIALS delivery, CLOEXEC inheritance, kernel seal/write
behavior, process identity and group closure, resource peaks and parent-death
cleanup. No supported host exists yet. Immutable loader namespace, helper
execution, glibc dynamic behavior, FUSE privilege/teardown and provider/Run
qualification remain outside this protocol and unqualified.

Primary APIs: Linux [unix sockets](https://man7.org/linux/man-pages/man7/unix.7.html)
for SOCK_SEQPACKET, SO_PASSCRED, SCM_CREDENTIALS and shared-open-description
SCM_RIGHTS semantics; [recvmsg](https://man7.org/linux/man-pages/man2/recv.2.html)
for ancillary truncation and MSG_CMSG_CLOEXEC; and
[file sealing](https://man7.org/linux/man-pages/man2/F_ADD_SEALS.2const.html)
for required seals and writable-mapping restrictions. These API descriptions
constrain the design; reading them is not actual platform qualification.
