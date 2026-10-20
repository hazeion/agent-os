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

Focused verification on `ac2593c` ran the portable `ReadbackReplyTests` class
once with `-B`, ResourceWarnings treated as errors and a fresh private Hermes
fixture root. All eight methods passed in 0.004 seconds, with no skips or
ResourceWarnings. The three new ownership/unknown cases all passed.

The separate control used an exact `46eab4b` source archive with only the three
new methods inserted into its existing readback test class. All 1,142 tracked
paths matched their original blobs except that deliberate test overlay, and all
old test ASTs were preserved. Only those three new methods ran: the two ownership
cases failed as expected, while the ordinary-unowned unknown case passed, in
0.003 seconds. The control returned verified process/tool exit 1; the fixed class
returned verified exit 0. Both commands recorded their owned Python PIDs before
waiting and retained separate logs and exit files.

No native operation or host call ran during this focused verification. Publication
checks are recorded separately against the final PR head. The separate pre-reap
group-cleanup work remains on its own branch and files; these portable cases do
not qualify that pending source. Prior helper-origin and custody evidence remains
scoped to its recorded source. No native claim, source pin or baseline entry
changes here.
