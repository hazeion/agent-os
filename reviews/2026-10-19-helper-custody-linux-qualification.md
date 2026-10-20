# Nonexecuting Linux custody qualification driver

Source-only checkpoint, not executed or qualified. This branch adds a fixed
source-checkout callable, portable boundary tests and this record. Production,
CI, dependencies, packaging, pins and detector baseline are unchanged.

The approved design is `/private/tmp/mentat-helper-custody-linux-driver-design.md`,
SHA256 `0a25bd79eda47b1483d270d83d5f8adc339f2671a61a138e70842eae00f74585`.
The production base is `fc4e572b17ea9032fadae867743e6f0b05562aeb`. An aggregate
with only later fixture/document changes may use this same production graph.

## Contract and implementation

`QualificationAttempt` starts its single 30-second clock before source/host/input
preflight. Its compiled map has 178 exact fc4 blob/size pins: 173 production
Python files, fixed deploy/module JSON and root TOML resources. The tool performs
bounded no-follow reads and Git blob hashing before project imports and repeats
the same source observations before accepting success. There is no Git process,
caller manifest, source selector, supplied clock or runtime-profile override.
The external reviewed supervisor still verifies the complete source snapshot and
this tool's hash. These hashes do not establish host trust or immutable custody
of the Python interpreter/source during execution.

Each source/input read retains directory descriptors through its bounded read;
lexical and descriptor identities must still agree. Input inspection is limited
to the exact 19 names, with at most a twentieth directory entry used to refuse
extras. Existing compiled sizes/hashes and owner-private metadata apply. No
source/input bytes are changed. `-B` is mandatory for the foreground interpreter.
The unchanged API child uses `-I` without `-B`, so the supervisor must prepare a
NEW dedicated qualification source copy with read-only files and Python parent
directories before the first driver observation. It must never chmod a Git
worktree, original source/input, prepared acceptance archive or existing proof.
The driver refuses writable source files/directories, project __pycache__, legacy
bytecode and each interpreter-defined extension-shadow filename, before imports
and again at final validation. This is a prepared-copy permission requirement;
Git byte/size pins do not pin those new prepared modes or claim an immutable
loader. The external supervisor must still verify the entire fresh source copy.

The one component operation is the existing `acquire_fixed_helper_bytes` call.
It retains its own unchanged 30-second and resource limits. The outer deadline
also includes preflight and final checks, so a late successful API return must
close and refuse. Failure cleanup may finish after the acceptance deadline.
No retries, extra worker, downloaded ELF execution or privilege operation exist.

The actual lease type and private descriptor map are inspected deliberately as
white-box qualification evidence. Exactly 17 distinct regular objects, 13
signed-library-archive classes, four compiled-helper-pin classes and ten aliases
are required. Sizes/hashes, the two fixed libc/libm profiles, helper pins,
FD_CLOEXEC and real kernel seal mask 15 are checked. Alias chains must terminate
at an owned regular member. The tool does not impose a new memfd mode assumption:
the existing implementation seals anonymous memfds without an explicit chmod.

Every member is read once through the existing one-second bounded `lease.read`.
One additional bwrap read checks that pread leaves a deliberately moved shared
file offset unchanged. The duplicate has CLOEXEC, is explicitly accounted for,
and its prior offset is restored before independent close. There are no writes,
truncates, seal modifications or executable mappings.

The FD inventory probes exactly slots 0 through 63, accepts only EBADF as absent
and requires a stdio-only baseline. Successful acquisition must add exactly the
17 observed slots. Closing the duplicate and lease is independent, with one
attempt per resource; ambiguous numeric descriptors are never retried. Former
member slots must be absent before opening final-check files. Unknown or reused
slots refuse and are never closed by the driver.

`begin` installs one global `active_attempt` before running it. Every original
exception, cause/traceback, attached worker owner/pidfd, lease and ambiguous
resource record remains strongly referenced. Any acquire exception is
conservatively blocked even if the visible baseline FD set is restored. A blocked
report explicitly requires keeping the foreground session open. There is no CLI
main, daemon, listener, PID reconstruction or kill/control endpoint. The retained
controller lifetime is a prerequisite, not something a serialized report proves.

Reports are fixed JSON within 16 KiB and contain only booleans, counts, elapsed
milliseconds, fixed source commit and public-coordinate/member digests. No raw
paths, descriptor/PID numbers, environment values, errors or public archive bytes
are reported. Encoding and the final acceptance timestamp must fit the same
outer deadline. Later output transport cannot turn a late result into success.

## Portable tests proposed, not run

The new module covers source pin shape, earliest clock ordering, one-use retained
state, unsupported/expired preflight, exact bounded FD enumeration, EBADF versus
EPERM, independent close attempts, live/reused slot refusal, retained actual owner
objects, source size refusal, and an explicitly substituted positive candidate.
Negative candidate cases cover missing seals, wrong trust class and bad bytes,
and source-layout cases refuse writable parents, caches and extension shadows.
Every OS/API substitution is explicit. These tests cannot establish real Linux
signature verification, ancillary transport, seals, worker exit or namespace
behavior. No compile, test or native qualification command has run at this source
checkpoint.

## Concrete foreground execution plan for later review

Execution is held until root and independent source reviews and an explicitly
named supported Linux connection are available. Do not use a one-shot `python`
command that exits after printing a report. Do not provision or connect now.

1. Prepare a new owner-private exact source snapshot and the 19 explicitly staged
   public input files. The supervisor verifies the complete source graph and
   reviewed tool hash, and the fixed trusted host interpreter. Make only this new
   dedicated source copy read-only before qualification, as described above. No credentials,
   owner home scan, network fetch or installer is needed by this tool.
2. A separately reviewed fixed local launcher owns one foreground Python process
   with `close_fds=True`, only stdin/stdout/stderr inherited and no extra pass_fds.
   That launcher's trusted bootstrap lowers both its own RLIMIT_NOFILE limits to
   the minimum of existing soft/hard and 64, without raising a weaker existing
   limit; failure refuses. It uses isolated Python with `-I -B -i`, inserts only
   the exact source root and imports this fixed driver. The launcher keeps the
   exact live process/session handle. The startup inheritance/limit receipt is
   external prerequisite evidence, not a caller-controlled driver boolean.
3. At that retained foreground context, invoke exactly
   `qualifier.begin(Path(EXACT_REVIEWED_PUBLIC_INPUT_ROOT))`. There is no second
   attempt. The callable owns the global active_attempt before acquisition and
   returns a bounded report at its own acceptance timestamp. The supervisor must
   observe that exact result and timestamp, preserving source/input evidence.
4. On verified success or fully closed refusal, the owned foreground context may
   end normally after root review. On `session_must_remain_open=true`, it stays at
   the same foreground prompt with active_attempt and real owners alive. There
   is no automated EOF, timeout kill, replacement, backgrounding or daemon. A
   connection/session loss is unresolved interruption, not cleanup success.
   Reconciliation needs a separate review; no saved PID can reconstruct authority.

This plan still needs a concrete hash-pinned launcher/session-owner preparation
before execution. The present branch intentionally supplies no process launcher.
If the eventual connection cannot retain that foreground context, do not run the
driver or substitute a serializing one-shot script.

Success would cover only this positive nonexecuting acquisition/read/release on
that exact code/host/input set. Hostile write/truncate-denial, parent death,
malformed transport and descendant cases remain separately unqualified. Actual
immutable loader execution, FUSE privilege/teardown, security currency and
provider/Run/runtime admission remain open. Helpers have compiled-pin evidence
here; their independent signed helper-origin gate is not minted by this result.

## Source-binding correction, still source-only

Root and independent review found that byte pins alone did not bind the imported
API: ordinary imports could use an installed Mentat under ambient sys.path.
The driver now refuses preimported pinned modules and packages, including deploy,
then places its fixed verified source root first before the fixed API imports.
The acquisition path's fixed lazy link-preview dependency is imported and checked
before acquisition. All actually imported project module names, __file__, spec
origin/name, exact ordinary SourceFileLoader/path and package search locations
must bind to the pinned source graph before and after the operation. An alias
from that source tree or unknown module under a pinned project package refuses.
The fixed prefix is also rechecked before acquisition and final acceptance.
This is a binding check inside the already trusted isolated interpreter; it does
not authenticate arbitrary import machinery or establish immutable execution.

Pinned module-stem package directory shadows now refuse alongside caches and
extension files. New portable tests use explicit module metadata substitutes to
exercise correct binding, installed API substitution, later dependency rebinding,
preimported deploy and same-stem package refusal. They do not execute those fake
modules. Existing size and class negatives were corrected to isolate their
intended guards: readonly mode otherwise validates before the wrong-size check;
a helper/library class swap preserves the 13/4 totals, and fstat/read must never
be called when the exact path/class guard refuses. No budget or production change
is part of this correction. Tests and native operations remain unexecuted pending
exact source review and a root-coordinated window.

The exact-class preflight now covers every member row before any descriptor is
observed. The negative swaps later helper/library rows while preserving 13/4,
so earlier valid rows cannot mask the guard with unrelated FD failures. All
metadata-declared slots are retained before the first actual fstat/read for
independent close and post-close absence accounting.

A subsequent self-review found a baseline-accounting gap: recording an unexpected
live slot and then comparing to that same baseline could label cleanup verified.
The baseline is now recorded before project imports, after source pinning. A
non-stdio baseline or failed passive inventory is retained uncertainty, with no
unknown-slot close. Imports/preflight must preserve the original stdio baseline,
and final cleanup still compares it. Portable negatives retain the original
probe exception and require an open foreground session rather than a cleanup
claim. This follow-up remains source-only and unexecuted.

## Portable verification and explicitly approved public-hash baseline

The single authorized portable module at source checkpoint fa231d5 passed all
28 methods in 0.072 seconds, with no skips, using the existing private Python
environment, `-B` and ResourceWarnings as errors. OS/API/module substitutions are
explicit. Log: `/private/tmp/mentat-helper-custody-driver-fa231-portable.log`.
No real Linux custody, host contact, helper execution or limit change occurred.

The unchanged tracked-secret gate first FAILED with 180 new Hex High Entropy
rows. That failure remains preserved in
`/private/tmp/mentat-helper-custody-driver-fa231-secret.log`; it is not rewritten
as a pass. Root and two independent reviewers classified every row: 178 fixed
public fc4 Git blob identities, the public source commit and its repeated test
literal. Each path, size, object ID and detector fingerprint was checked against
immutable Git data and the exact reviewed source. There were no unclassified
values. The classification and additive application proofs are retained at:

- `/private/tmp/mentat-helper-custody-driver-fa231-public-hash-proof.json`
- `/private/tmp/mentat-helper-custody-fa231-independent-public-hash-proof.json`
- `/private/tmp/mentat-helper-custody-baseline-application-proof.json`

Automatic approval review initially rejected applying baseline exemptions without
explicit human authorization. No rejected command executed, and the clean source,
original baseline and failure log were preserved. The user subsequently gave
this exact approval:

> I approve adding the 180 verified public Git hashes to the secret-scan baseline.
> Keep the scanner rules unchanged and continue with anything we can finish while
> I get the Linux host ready.

Only the exact reviewed proposal is applied: all 264 original records and all
non-results metadata remain unchanged; exactly 180 reviewed `is_secret: false`
records bring the total to 444. Tool/test bytes remain exact fa231d5. No detector,
filter, threshold, exclusion, encoding, production or package change accompanies
this baseline update. The unchanged gate will run once on this prepared commit;
its terminal result must be recorded separately from the original failure.

CODEOWNERS `@hazeion` normal GitHub review policy remains in effect. The explicit
user permission to prepare this change is not a fabricated GitHub review, merge
or publication approval. No baseline addition is a dependency or execution waiver.
The foreground launcher and real Linux positive qualification remain separately
unapproved and unperformed. Immutable loader/FUSE/runtime/provider readiness and
hostile native qualification cases remain open.

## Source-only re-pin for deferred scope ctypes initialization

The first native attempt at the old 13a source refused BEFORE acquisition: no
worker/signature/decoder operation started and no lease was returned. Its held
foreground attempt and original errors remain preserved. Passive inventory found
one new regular descriptor while all three baseline FIFOs stayed unchanged.
A separately authorized fresh ctypes-only diagnostic reproduced that descriptor
class addition without importing project code or calling a custody API. Upstream
CPython initializes its libffi allocator at ctypes import. This evidence does
not identify or authorize closing the old unknown descriptor, and no session or
native retry was performed by this preparation.

The independently reviewed production candidate e861743 defers ctypes import
until the actual cgroup check or scope constructor needs it. Both existing
consumers and their width/refusal conditions remain supported. Production
focused, old-code counterfactual and unchanged scanner evidence are still pending
at this source-only checkpoint; no later result is assumed.

The qualifier's fixed source graph is re-pinned coherently to that exact
production candidate. Only SOURCE_COMMIT, the scope file's committed size/blob
identity, and the test's exact commit assertion change. All 178 tuple paths were
checked against immutable e861743; the scope row is the only changed tuple and
all other 177 are exact. The tool remains separately supervisor-pinned. This
refresh adds no import/FD exception, callback, selector, deadline, retry or owner
control, and it must not claim the old fc4 graph matches changed production bytes.

All 444 previously approved baseline entries and scanner rules remain unchanged.
The two new source-commit literals and one new scope-blob literal are expected to
produce three unreviewed public-hash records, but no scan has run on this new
checkpoint. The prior human approval covered 180 old values only. Exact new
classification and any necessary direct human/normal owner approval must precede
a further baseline change; no encoding or detector workaround is allowed.

Existing portable and secret passes remain evidence only for their original
heads. This new source preparation requires root and independent review before
any tests or scan. A later actual native attempt requires separately reviewed
fresh source/staging/foreground pins and explicit authorization. Original 13a,
its PR history, staged copies and held attempt are untouched. No source upload,
host call, helper execution, provider action or publication occurred here.

## Re-pin verification and exact three-hash user approval

The source-reviewed re-pin at fb26d82 passed its single 28-method portable module
in 0.037 seconds, without skips, with `-B`, ResourceWarnings as errors and a fresh
private Hermes directory. The following unchanged tracked-secret gate FAILED on
exactly three new records: the fixed production commit in tool/test and the
committed scope blob in the tool. No source, baseline or scanner change occurred
while either check was live. Complete initial/wait tool results, exits and logs
are retained under `/private/tmp/mentat-custody-fb26d82-checks/`.

The three records were classified from actual failure lines, detector-core
PotentialSecret fingerprints and immutable e861743 commit/blob objects. Root and
independent review confirmed the exact private proposal preserves every original
444 record and all non-results metadata while adding only those three public
Git identities. The original failure remains preserved; it is not relabeled as
a pass. The user explicitly answered:

> Approve the 3 public hashes

That answer applied to the exact reviewed three-record proposal. This commit
therefore adds only those three `is_secret: false` records, total447. All detector,
filter, threshold, exclusion and encoding rules remain unchanged. Tool/test bytes
are still exact fb26d82; no portable repeat is necessary for this baseline/doc
change. The unchanged final secret gate will run once at this prepared commit,
and its actual terminal result is recorded separately for final review.

The normal merge of C's evidence-only cc7ff22 preserves both feature histories
and its exact reviewed production/test bytes. C's production evidence is recorded
in `reviews/2026-10-19-worker-scope-lazy-ctypes-import.md`; the qualifier's fixed
production pin remains the exact e861743 source object, not a different graph.

Normal CODEOWNERS/GitHub review and publication authorization remain required;
no synthetic owner review, forced update or primary/PR330/PR331 change occurred.
This is not a native retry or cleanup action on the original held session. No
new staging, host call, helper execution, loader/FUSE/runtime/provider readiness
or actual Linux positive qualification is claimed by these portable checks.

## Actual Linux nonexecuting custody positive

One authorized run on non-root Ubuntu 26.04 amd64 under WSL2 passed using the
complete staged e554be5 source snapshot and its compiled e861743 production graph.
The selected controller interpreter was Python 3.14.4; this does not change the
separate runtime Python contract. The driver completed in 708 ms and the local
result capture in 3,522 ms, with timely capture inside the original acceptance
limit. It observed 17 sealed regular members and ten aliases: thirteen members
from the signed library archive chain and four compiled-helper-pin members.

The real acquisition, peer-credential checks and descriptor transfer, sealed-byte reads, fixed
bwrap offset check, source/input rechecks and release completed. The driver
reported cleanup verified, no retained owner and no need to keep its session
open. Independent result review preceded the authorized normal finish; the
finish and exact-child terminal receipts then recorded exit0 and verified
cleanup. Both controllers completed the reviewed normal finish path.

Private evidence is retained in `mentat-custody-e554-native-first-result.json`,
`mentat-custody-e554-native-finish-tool-result.json` and
`mentat-custody-e554-native-terminal.json`, with independent result review. The
old 13a pre-acquisition refusal remains a failure in preserved evidence; its
separately authorized retirement does not relabel that attempt as successful.

This evidence binds the actual e554be5 staged snapshot, not an entire later
Git head. The acceptance update after e554be5 changes this review document only;
production, qualifier, tests, baseline447 and scanner bytes are unchanged. No
full, portable or native run was repeated for the documentation update.

Execution, freshness and hostile-case qualification flags all remain false.
The four helpers retain their compiled-pin classification here; separate helper
archive-to-installed-byte authentication is not supplied by this result or by
local nine-input preparation. Immutable loader/helper execution, FUSE privilege
and teardown, broader isolation, dependency/provider/account qualification and
production Run admission remain independent gates.
