# PR 274 archive-in-flight fixture failure cleanup

Exact base: 0445b7328e68d554ef3920309cdb0e9906d6ad2c.
Windows group 0 job 109892371370 failed its original five-second submit-entered
assertion, then masked it with WinError32 deleting the initialization lock beneath
a still-live owned worker.

The fixture now releases and attempts bounded drain in finally. A manual temporary
owner cleans only after verified worker exit; unresolved liveness retains that
owner on the exact active Thread, preventing finalizer deletion until thread exit.
No operator or production-root path is retained or modified. Keep the original
five-second entry and captured five-second completion conditions; the extra
25-second diagnostic drain cannot satisfy the primary success assertion.
Completed/archived/finalizing/single-call semantics remain unchanged.

Two meaningful regressions cover an injected ordering failure with actual worker
liveness observed before failure and before root cleanup, and a controlled fake
always-alive worker proving retained-root behavior after [5,25] joins without
starting a hanging child. Test safety cleanup resolves only its exact fake owner.

The original broad 107-method suite passes (57.321 seconds). Final three focused
cases pass Windows3.079 seconds and Linux0.956 seconds; reviewer B independently
runs all three in3.483 seconds. Both independent re-reviews are clear after fixing
their undrained-root finding. Final complete orchestration/discovery checks remain
in progress. No production, authority, schema, timing, matrix or coverage weakening.
The exact frozen60 publication proposal remains unchanged and unpushed.

Final complete orchestration + CI/discovery qualification passes all119 methods
on Windows in71.650 seconds, including both added regressions. This supersedes
the formerly-in-progress gate above. Linux final three-case qualification and
both independent re-reviews are also complete. No target branch is published
or merged; the local record is ready for the ordered post-approval carry.
