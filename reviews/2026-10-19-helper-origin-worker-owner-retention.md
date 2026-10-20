# Preserve helper-origin failure ownership through the safe exception boundary

Base: `e554be5`.
Branch: `codex/helper-origin-worker-owner-retention`.

`verify_helpers` and `verify_fixed_helper_library_origins` previously caught
constructor/execute exceptions, cleared the
candidate, and raised a new safe refusal after leaving the exception handler.
When a failed slot constructor retained an unresolved worker on the original
exception, assignment to the local slot never completed. The later safe refusal
could therefore lose that original exception, traceback and attached owner.

Each one-line production correction raises the same secret-free refusal inside
the active exception handler. Python's exception context retains the original
error and its actual attached owner. The existing finally still closes an assigned
slot exactly as before. A close failure also retains the pending safe refusal and
original execution error in its context chain. Successful behavior, validation,
worker commands, resource limits, deadlines and close/control logic are unchanged.

Two focused portable regressions per API use the existing slot-substitution test seam:
constructor failure must preserve the exact attached owner/handle/error/traceback
through a safe public exception without a spurious close; assigned-slot execution
followed by close failure must retain the complete owner-bearing exception chain
and attempt close exactly once. Existing tests and assertions are unchanged.
These tests do not launch or control a real worker.

Focused verification ran once on the reviewed source checkpoint with `-B`,
ResourceWarnings treated as errors and a fresh private Hermes fixture root. The
existing system-origin parsing and library-origin classes ran 36 methods in
0.848 seconds: 35 passed, with one existing Linux-native platform skip. All four
new ownership regressions passed. The actual Linux class and operator native
fixture inputs were not enabled.

The separate old-source control used an exact `e554be5` Git archive with only the
four new methods inserted into its existing test classes. All 1,141 tracked paths
matched their original blobs except those two deliberate test overlays; all
original test ASTs remained exact. Only the four new methods ran: all four failed
at the missing exception-context/owner-chain assertions in 0.344 seconds, with
process exit 1. The fixed-source run returned verified process/tool exit 0; both
commands recorded their owned Python PIDs before waiting and retained their logs.

No native operation, host call or secret scan ran for this change. The final
unchanged scan is held until the reviewed documentation base is merged. Separate
nine-input staging/foreground preparation remains paused pending the final source
review. The earlier custody positive, guarded finish, controller retirement and
old failed-report history remain separate evidence. No qualifier/source pin or
baseline entry is changed by this patch; later final source snapshots and any
needed pin updates require their own explicit review.


The cohesive library-origin follow-up preserves the first system-origin checkpoint
and applies the identical active-handler correction to its corresponding verifier.
Its two mirrored ownership regressions cover the same constructor and close-error
boundaries. No other API, validator, inspector, bounds, pin or cleanup method changes.
All four regression methods were independently source-reviewed before the
focused verification described above.
