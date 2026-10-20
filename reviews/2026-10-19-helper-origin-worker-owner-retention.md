# Preserve helper-origin failure ownership through the safe exception boundary

Base: `e554be5b3ee6699fbdb563d3dd48102f497f1c40`.
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

Source checkpoint only. No tests, secret scan, native operation or host call have
run for this change. Separate nine-input staging/foreground preparation is paused
pending review of this correction. The earlier custody positive, guarded finish,
controller retirement and old failed-report history remain separate evidence.
No qualifier/source pin or baseline entry is changed by this patch; a later final
source snapshot and any needed pin updates require their own explicit review.


The cohesive library-origin follow-up preserves the first system-origin checkpoint
and applies the identical active-handler correction to its corresponding verifier.
Its two mirrored ownership regressions cover the same constructor and close-error
boundaries. No other API, validator, inspector, bounds, pin or cleanup method changes.
All four regression methods remain source-only pending independent review.
