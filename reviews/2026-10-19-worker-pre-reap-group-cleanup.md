# Keep group signal authority until cleanup's final signal

Base: PR333 origin-wrapper owner-retention checkpoint (46eab4b).
Branch: codex/worker-pre-reap-group-cleanup.

Source-only checkpoint. No tests, subprocess experiment, native helper operation
or host call has run for this change. Independent source reviews precede checks.

The existing POSIX teardown could reap its leader in poll/wait before sending
its final numeric group signal. Request-start polling also ran outside the
lifecycle lock, racing timer abort. The new internal cleanup state retains the
actual process and records its signal/close attempts. POSIX health uses waitid
with WNOWAIT when available. Older macOS Python has no reaping health poll and
uses the existing EOF/write/watchdog failure paths. Its existing half-second
termination grace stays unchanged; no ctypes or new OS binding is introduced.
Every POSIX spawn and health/control observation requires the default SIGCHLD
disposition. SIG_IGN or a custom handler refuses without numeric group control.
The supported ownership model requires exclusive Popen waits for these children;
external waitpid reapers or concurrent signal-disposition changes are outside
that model. The older macOS fallback relies on this same explicit assumption.

TERM and final group KILL happen while the original leader remains unreaped.
Only then can Popen.wait run. Reap and read-only group-absence checks share the
existing half-second kill wait. Eligibility is checked before each absence probe
and after its terminal evidence, so late waits or late absence cannot clear
ownership. Already-reaped, missing-group, ECHILD and other
uncertain states fail closed without a signal. Later cleanup calls retain the
actual failure rather than repeating group control or ambiguous stream closes.
Windows retains its real process/job-handle termination sequence and time limits.

Initial health/reaping decisions use short lifecycle locking. The lock is never
held across request writes or message waits, so timer abort remains effective.
Closed-pipe ValueError from that race maps to the same unavailable boundary.

Both owned streams get independent close attempts, recorded before each close.
Their exact errors and the process remain retained on uncertainty. Reader join
still uses the existing half-second bound. HelperSlot no longer closes streams
a second time and does not turn an inherited ambiguous cleanup error into
success merely because the group later disappears.

Planned portable tests substitute process/kernel effects explicitly and cover
signal-before-reap ordering, natural exit without reaping, absent waitid fallback,
ECHILD/already-reaped/reused-group refusal, lifecycle selection/abort ordering,
nondefault SIGCHLD refusal, late terminal evidence, deterministic lock ownership,
Windows job handles, independent before/after-close failures and HelperSlot's
no-reclose behavior. No new skip or timeout increase is proposed. Existing tests
retain their behavior assertions; fakes will represent cached terminal state,
and inherited unknown cleanup must remain an error rather than become success.


The first focused run on the merged source checkpoint failed: 63 methods,
seven real-worker final-SIGKILL EPERM errors, one existing Linux skip and
ResourceWarning markers. That original log is preserved; it is not a pass.
Apple's published XNU group iteration excludes zombies and can return EPERM
when no eligible member remains, but that source fact does not establish the
cause of the actual failed groups or turn permission denial into absence.

The source-only correction records an actual Darwin EPERM and consumes all
remaining nonzero signal authority. Only exact owned-child terminal/reap and
read-only group ESRCH within the same half-second cap can then complete cleanup.
POSIX reap uses checked waitpid(WNOHANG), under the lifecycle lock, because
Popen.wait can translate ECHILD into a synthetic success. ECHILD and wait timeout
retain a safe unavailable error with cause. Linux denial remains a failure.
Portable fixtures cover denied TERM/final KILL, old-macOS observation fallback,
live/lost child, residual or denied group observation, late evidence and close
uncertainty. These corrections have not yet been executed or qualified.
