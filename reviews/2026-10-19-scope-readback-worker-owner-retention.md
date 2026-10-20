# Preserve unresolved readback worker ownership without changing unknown observations

Base: `46eab4b`.
Branch: `codex/scope-readback-worker-owner-retention`.

The private `inspect_scope` wrapper previously converted every caught ordinary
exception into an unknown observation. If a failed constructor carried an actual
unresolved worker owner, its slot assignment had not completed and the later
unknown result could discard the original error, traceback and owner reference.

The narrow correction propagates only exceptions whose existing
`_mentat_worker_owner` field is non-None. It raises the fixed safe
`ValueError('scope_readback.unverified')` explicitly from that original exception.
Ordinary unowned failures retain the existing `ScopeObservation` unknown result.
The existing finally, success projection, validation, ten-second deadline,
worker commands and control/resource boundaries are unchanged. No new caller,
capability or API is introduced.

Three portable regressions use the existing slot-substitution seam: constructor
ownership retains the exact error/traceback/handle through the safe cause without
a spurious close; an unowned constructor error still returns unknown; owned
execution followed by close failure preserves the original owner chain and one
close attempt. All pre-existing assertions and platform skips remain unchanged.

Source checkpoint only: no tests, scans, native operation or host call have run
for this change. The separate pre-reap group-cleanup work remains on its own
branch and files. Prior helper-origin and custody evidence remains scoped to its
recorded source; no native claim, source pin or baseline entry changes here.
