# Keep the reusable inspection slot independent of application readback imports

Base: `0b87dbd`. Branch: `codex/scope-inspector-lazy-readback-import`.

The native helper-origin attempt entered `verify_helpers` but failed while its
local `_InspectionSlot` import loaded `ScopeObservation`. That module imports
Run/attachment repositories, whose application import graph reaches Pillow.
A separately reviewed read-only diagnostic on the retained failure confirmed
exact `ModuleNotFoundError` and the fixed missing-PIL boolean. Its traceback
reached the Run and attachment imports. No worker owner, slot or command process
was observed, every operational Owner had attempted closure and the complete
finite FD inventory matched the original three-pipe baseline. The API did not
reach slot construction. This remains a failed native attempt, not qualification
of the corrected source or proof beyond those retained observations.

`ScopeObservation` is used only inside `inspect_scope`; import it there rather
than when defining the reusable `_InspectionSlot`. The class itself remains the
canonical readback class. The import stays before the existing argument checks
and ten-second deadline; all validation, request/result rules, owner-preserving
exceptions, finally, timers and worker-control behavior are unchanged. The
helper-origin API can import its shared slot without loading application data
repositories or requiring application dependencies at that import point.
No fallback, package install, new capability or execution authority is added.

One existing type assertion now names `readback.ScopeObservation`, its defining
module, rather than relying on the inspector's removed incidental module alias.
All other readback business assertions remain unchanged. A new fresh-process
regression uses the existing isolated `-I -B -S` shape and 15-second import-test
cap, first proves Pillow is unavailable, then imports the real slot without
mocks or worker construction and verifies readback/Run/Pillow were not loaded.
It exercises the dependency boundary rather than a cached import or a fixture
substitute. Production operation and cleanup budgets are unchanged.

Focused verification on `a601723` ran the new import module, the eight portable
readback reply methods, helper-origin parsing and library-origin tests once with
ResourceWarnings treated as errors. All 46 methods completed in 1.288 seconds:
45 passed and the existing actual-Linux signature/decoder test was skipped. The
child had fresh private HOME, Hermes and temporary directories, umask 022, and
native opt-in variables unset. No ResourceWarning occurred.

The separate exact `0b87dbd` source archive retained all 1,146 original blobs and
modes, adding only the new import test module. Only that method ran; it failed as
expected in 0.474 seconds on actual `ModuleNotFoundError: PIL` through the original
readback/attachment import chain. The no-Pillow premise was checked before the
real import. Both processes recorded their owned PIDs before waiting and retained
separate complete tool receipts, logs and exit files. This counterexample failed;
it is not counted as a passing test.

Pillow remains a required application dependency. The correction removes its
incidental import requirement only from the reusable slot's import path; actual
scope readback retains its canonical class and application dependencies. The test
file and production source remain byte-exact to the tested checkpoint; this
follow-up changes only the evidence document.

No scanner, broader suite, package gate, host call or native retry ran during
this verification. The original foreground attempt and all failure receipts stay
retained. Any later source staging, controller startup or native call requires a
fresh exact review and explicit root authorization. Source pins and the existing
447-entry baseline remain unchanged. The old native failure is not converted to
a positive, and no older graph's qualification is transferred to this change.
