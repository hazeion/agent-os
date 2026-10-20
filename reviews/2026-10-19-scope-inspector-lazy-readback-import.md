# Keep the reusable inspection slot independent of application readback imports

Base: `0b87dbd`. Branch: `codex/scope-inspector-lazy-readback-import`.

The native helper-origin attempt entered `verify_helpers` but failed while its
local `_InspectionSlot` import loaded `ScopeObservation`. That module imports
Run/attachment repositories, whose application import graph reaches Pillow.
The first retained diagnostic identifies the import-time path; the exact missing
module is still awaiting its separately reviewed read-only diagnostic. No worker
owner, slot or command process was observed, and the complete finite FD inventory
matched the original three-pipe baseline. This is a failed attempt, not a native
qualification or proof of cleanup beyond the reported observations.

`ScopeObservation` is used only inside `inspect_scope`; import it there rather
than when defining the reusable `_InspectionSlot`. The class itself remains the
canonical readback class. The import stays before the existing argument checks
and ten-second deadline; all validation, request/result rules, owner-preserving
exceptions, finally, timers and worker-control behavior are unchanged. The
helper-origin API can import its shared slot without loading application data
repositories or requiring optional application packages at that import point.
No fallback, package install, new capability or execution authority is added.

One existing type assertion now names `readback.ScopeObservation`, its defining
module, rather than relying on the inspector's removed incidental module alias.
All other readback business assertions remain unchanged. A new fresh-process
regression uses the existing isolated `-I -B -S` shape and 15-second import-test
cap, first proves Pillow is unavailable, then imports the real slot without
mocks or worker construction and verifies readback/Run/Pillow were not loaded.
It exercises the dependency boundary rather than a cached import or a fixture
substitute. Production operation and cleanup budgets are unchanged.

Source checkpoint only: no new test, scanner, host call, project/API operation
or native retry has run. The original foreground attempt and all failure
receipts remain retained. The separate diagnostic and any later source staging,
controller startup or native call require their own exact reviews and explicit
root authorization. Source pins and the 447-entry baseline remain unchanged;
this change cannot reuse an old graph's qualification claim.
