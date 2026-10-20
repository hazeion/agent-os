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
