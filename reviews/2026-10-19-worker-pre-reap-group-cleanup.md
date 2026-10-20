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
