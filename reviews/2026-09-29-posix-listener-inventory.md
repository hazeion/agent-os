# Complete POSIX listener discovery and recorded gateway Stop

The running WSL host demonstrated a partial successful `lsof` inventory:
the bridge and Hermes listeners were present, but the live Next.js dashboard
was omitted. `ss` simultaneously returned the dashboard and its PID. Returning
the first successful tool's rows made Mentat status claim an empty dashboard
inventory even while HTTP and sockets proved readiness.

Collect both bounded inventories, retaining each unique PID, port and
normalized endpoint observation. A missing, timed-out or failed tool must not
discard usable observations from the other. PID-less rows grant no ownership.
Discovery remains evidence only: the existing command, gateway and generation
checks still decide whether a process belongs to Mentat.

When the recorded Node state carries process-start identity, cleanup must
reconcile that exact generation regardless of listener visibility. Never let
the added observation bypass the existing PID-fenced Stop, retry a failed
fenced Stop with raw PID signaling, or erase unresolved runtime state. Other
owners on the configured port remain separate observations and retain existing
blocking behavior.

Verification covers successful partial inventory, IPv6 deduplication, distinct
owners/addresses, tool failures, partial output, PID-less rows, and the combined
discovery-to-Stop path. The latter checks successful exact-generation Stop,
reused PID, malformed recorded identity, and failed fenced Stop. Obtain two
independent reviews, correct findings, then verify real WSL status without
stopping the owner's running dashboard. Disposable owned-process tests cover
signaling; no owner Agent work is stopped for acceptance.

Verification completed: 50 lifecycle tests pass on Windows (three Linux-only
skips) and all 50 pass on actual WSL/Linux, including an actual disposable-child
pidfd test that refuses the wrong generation before stopping the exact one.
Both independent reviewers found legacy missing-identity and Linux-fixture
gaps; these were fixed and both final reviews are clear. The exact host
backport passes the same 50 tests. Read-only host status now reports the live
dashboard as Mentat-owned; its PID is unchanged, and HTTP remains available.
No production service restart or owner work interruption was needed.
