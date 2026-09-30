# Verified Google worker close fixture backport

PR #254's macOS Python 3.12 job reports live caller threads after `close()`.
The fixture's spawn signal fired before the runner registered worker ownership;
its close raced that registration and then expected every caller to unwind
within four seconds. This exact controlled-fixture repair was reviewed and
published later in commit `aa53cb2`.

Backport only the worker fixture: wait for two registered owned workers and no
starting worker before testing shared capacity/close. Require immediate close
success and verified process exit, then allow the same bounded ten-second
caller unwind as the existing reviewed repair. The original three-second spawn
condition, two-worker ceiling, two refused calls, no retry, and final no-live-
thread/process assertions remain. Production close, capacity and work deadlines
are unchanged; a longer runtime timeout cannot satisfy this test.

Review found that asserting the first close result inside `finally` could skip
caller cleanup when that contract failed. Capture the first result, always
reap only the exact fixture children and join its started callers, reconcile
close again, then assert the original immediate result. An injected false
first close verifies both children and callers are terminal before the failed
assertion is reported, with an outer owned-only safety drain if it regresses.

All 12 Google transport methods pass on the exact old base `bd722052`. Keep
browser/navigation changes from the original compound commit out of this
backport. Obtain two independent reviews before commit/push and rerun the
unchanged old CI contracts after replaying other required compatible repairs.
