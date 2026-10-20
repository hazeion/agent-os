# Keep group signal authority until cleanup's final attempt

Base: PR333 origin-wrapper owner retention (46eab4b).
Branch: codex/worker-pre-reap-group-cleanup.
Reviewed scope-owner prerequisite: PR334 (1e7a812), normally merged without
changing the five cleanup files. Corrected functional source: dd96698.

The former POSIX teardown could reap its leader through poll/wait before sending
its final numeric group signal. Request-start polling also ran outside the
lifecycle lock, racing timer abort. The replacement retains the actual process
and records signal and stream-close attempts before relinquishing authority.

POSIX health uses waitid with WNOWAIT where available. Older macOS Python uses
no reaping health poll: existing EOF/write/watchdog checks detect failed work,
with the same half-second termination grace and no new FFI or OS binding.
Every POSIX spawn and health/control observation requires default SIGCHLD.
SIG_IGN or a custom handler refuses without numeric group control. The supported
ownership model requires exclusive waits for these children and no concurrent
signal-disposition changes; external child reapers are outside that model.

TERM and the final group KILL attempt precede leader reaping. Checked
waitpid(WNOHANG) then validates the exact child and terminal status; unlike
Popen.wait, it exposes ECHILD. Actual terminal status is cached immediately even
when late evidence must be refused. Exact reap and read-only group absence share
the existing half-second kill-wait cap, checked before observation and after
absence. Lost ownership, late evidence or a remaining group stays a sticky
failure, with no later nonzero signal. Windows retains its process/job-handle
termination sequence and limits.

Darwin can return EPERM for an explicit group containing only zombies, according
to Apple's published XNU group-iteration code. EPERM also represents permission
denial, so this fact does not establish the cause of an actual failed group.
A Darwin TERM or final-KILL EPERM is retained as its exact exception and retires
all further signal authority. Cleanup still requires exact owned-child reap,
timely read-only ESRCH, both stream-close attempts and reader completion. An
errno alone never proves absence. Linux denial remains a failure.

Initial health/reaping decisions use short lifecycle locking, never held across
request writes or message waits. Both streams receive independent once-only
close attempts. Exact errors and ownership remain retained after ambiguity;
cleanup never retries a possibly reused resource. HelperSlot does not reclose
streams or convert an inherited cleanup error into success after later absence.
The reader-join bound stays at half a second.

## Verification

Root and an independent reviewer cleared the source before each authorized run.
The first focused run on 7538494 failed: 63 methods, seven real-worker errors at
the final pre-reap SIGKILL, one existing Linux skip and 42 ResourceWarning
markers. Its complete log and exit remain preserved. No success or cause claim
is inferred from that run. The Darwin postcondition reconciliation and checked
wait correction were separately reviewed before new-source verification.

One corrected-source run on dd96698 completed with authoritative exit 0:
66 methods, 65 passed, one existing Linux qualification skip, 3.027 seconds,
zero ResourceWarning markers. Python used -B and ResourceWarnings as errors,
a fresh private HERMES_HOME and no native qualification input variables. It ran
the entire link-preview worker module, SystemOriginParsingTests,
LibraryOriginTests and ReadbackReplyTests. This includes the existing actual
local worker/descendant tests and portable hostile ownership cases. It is not
a Linux helper-origin or execution qualification.

Portable cases cover signal-before-reap ordering; unavailable waitid;
SIG_IGN/custom handler refusal; ECHILD/already-reaped/missing-group refusal;
residual or denied group observation; late wait/probe evidence; Darwin TERM and
KILL denial followed by verified absence; live-child refusal; independent
before/after-close errors; Windows job behavior; deterministic lock ownership;
and abort while request I/O remains blocked. No new skips or larger budgets
were introduced.

One old-source control used an exact 46eab4b archive: all 1,142 original Git
blobs remained unchanged. Only a separate module containing the 14 new portable
cleanup methods/fixtures was added, with a fail-fast Popen substitute. No actual
old-source worker ran. It exited 1 after 2.063 seconds: 13 methods failed with
25 failure events across ordinary and parameterized cases; the Windows
compatibility method passed. Zero ResourceWarning markers were present. These
are counterexamples to the old behavior, not 25 distinct methods or a claim
that every test should fail.

Complete commands, initial session handles, owned PIDs recorded before waiting,
logs, exits and hash proofs are retained in private scratch evidence. The first
failed run, corrected run and old-source control remain separate. These focused
checks did not include a full suite, scanner, package build, native Linux helper
operation or host probe. Final scanner and publication evidence is scoped
separately to the final PR head.
