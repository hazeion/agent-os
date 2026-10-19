# Fixed helper byte custody: implementation checkpoint

Status: source and synthetic fixtures in progress, not qualified or published.
Root and independent review approved the requirements and protocol through
33ccd78, including the d1b62a1 trust-class correction. This checkpoint does not
clear Linux execution, signatures, loader behavior, FUSE or Run admission.

The private operation uses the existing 19 fixed public inputs. Thirteen
library/loader objects follow the captured signed archive chain; four helper
ELF objects bind only to their reviewed compiled size/SHA256 pins. No helper
archive is added or newly authenticated. The parent checks the exact fixed
member-to-class mapping, not membership in a caller-selected class enum.

The origin comparison keeps its ordinary API. A private retained context holds
the exact captured bytes and source descriptors while the custody worker seals
all 17 regular objects, rehashes and reparses their sealed bytes, and repeats the
four shared graph comparisons. Ten aliases remain authenticated library
metadata, never filesystem links. A fresh private sequenced socket transfers
one descriptor at a time with kernel credentials and strict nonce/order/hash,
identity and class binding. No caller report creates a custody lease.

Successful publication requires READY, RELEASE, EOF without extra packets,
normal exit 0 from the exact owned worker and read-only group-absence proof
inside the original 30 seconds. Failure signals target only the pinned original
unreaped leader's group. After reap, a surviving or reused group refuses with
retained uncertainty and no further signal. A successful lease exposes byte
reads and close only; it does not launch anything or persist readiness.

## Descriptor and allocation accounting

The worker retains 19 input descriptors plus one capture-root descriptor.
During sealing it adds 17 regular memfds, one socket and three standard
descriptors: 41 stable descriptors. Decoder commands run before those 17 member
memfds are created. A conservative decoder-phase allowance of 12 temporary
descriptors for sealed command input, pipes, spawn error channel, selector and
transient directory opens gives 36, below the unchanged 64 ceiling. Terminal
source revalidation needs at most one additional directory descriptor while
the worker copies are being released after ACK. The exact fixed graph must
remain 17 regular members and 10 aliases; a different selection refuses.

The parent owns 17 received descriptors, one socket and one pidfd beyond its
existing controller state. Each accepted right is owned immediately, including
malformed-packet paths. Input bounds, 32 MiB selected library bytes, the four
existing helper-size bounds, 512 MiB worker address space, 15 CPU seconds and
core size 0 remain unchanged. Real Linux FD/resource peak observations are
still required; this arithmetic does not substitute for them.

## Portable verification

After the parent released the browser quiet window, the focused command was:

```text
/private/tmp/mentat-ci-recovery-venv/bin/python -W error::ResourceWarning -m unittest tests.test_project_helper_byte_custody tests.test_project_library_origin tests.test_project_library_plt tests.test_project_runtime_host_trust tests.test_project_runtime_elf -v
```

Result: 64 methods, 63 passed and one existing actual-Linux skip, 0.509 seconds.
Log: /private/tmp/mentat-helper-byte-custody-focused.log. No real worker,
decoder, signature utility, helper ELF, library load, network request, image or
actual Linux qualification was executed. Source edits were made during the
parent-coordinated browser quiet window; the batch ran only after authorization.
Portable fixtures explicitly substitute unavailable Linux credentials/seals
while exercising actual descriptor reads, ownership, closure and parent
publication decisions. The parent success/partial-handoff fixture substitutes
the worker report and terminal evidence; it does not qualify actual worker
authentication or real Linux descriptor transport. Independent source reviews,
actual Linux qualification, security and packaging gates remain pending.
No security baseline or packaging policy is changed here.

## Corrective source review checkpoint

Root and independent review found gaps despite the first passing batch:
unisolated close errors could abandon later resources or retry a reused numeric
descriptor; the worker sealing/handoff path lacked direct synthetic coverage;
ACK equality admitted booleans/floats; and genuine POSIX fixtures needed targeted
Windows guards. These findings were corrected without changing the protocol or
resource limits.

Every member close is attempted once and independently. Ambiguous failures
retain cleanup evidence and prevent a lease or successful close. Lease state
retains uncertainty across later close calls without retrying numeric FDs.
Parent cleanup still attempts both sockets and owned-worker closure after a
member close failure. Worker endpoint closure remains independent; ACK and
pidfd cleanup relinquish numeric retry authority before the close attempt.

The complete library fixture now has an optional custody-layout variant; its
ordinary default and existing assertions remain. The worker fixture performs
real capture, index grammar, tar/ELF/shared-graph validation, sealed-descriptor
reads and FD ownership. Signature/decoder primitives, Linux seals/credentials,
resource effects and the transport are explicitly substituted. It asserts
source-context exit before READY, exact library/helper classes, graph mismatch,
partial/boolean/float ACK refusal and endpoint/member cleanup after close
errors. Instrumented real descriptor counts cover the 20 retained input/root
FDs plus 17 member descriptors; observed growth plus worker stdio/channel stays
below 64. This is portable accounting, not a real decoder/Linux peak claim.

The same focused command then passed 68 methods: 67 passed and one existing
actual-Linux skip in 0.772 seconds, with ResourceWarnings as errors. Log:
/private/tmp/mentat-helper-byte-custody-corrective-focused.log. Tests are stopped
for the next coordinated browser window. Independent corrective source review,
scanner/package gates and actual Linux qualification remain pending.
