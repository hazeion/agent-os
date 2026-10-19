# Webhook lock-order fixture isolation

Status: reviewed fixture isolation; hosted verification pending.

The full schema-46 Python run reports a subprocess timeout in
`test_webhook_snapshot_preserves_private_then_database_lock_order`. An
unchanged isolated run takes 9.902 seconds against its ten-second limit.
Profiling a real cold server import attributes 6.087 of 6.856 seconds to two
`hermes config path` discovery calls. The parent test patches server state,
but its fresh child previously inherited the developer's runtime discovery.

Give only that subprocess a `HERMES_HOME` path beneath the parent fixture's
owned temporary root. Keep the complete original child script, including empty
authority creation, real server/Task reads, lock choreography, exact results,
and thread-liveness assertions. The ten-second subprocess deadline, two-second
events and three-second joins remain unchanged. No production code or runtime
configuration changes.

A setup-only attempt was insufficient under the full module and is excluded
from the final diff. The final fix isolates the irrelevant installed-runtime
lookup instead of extending or repartitioning the original deadline.

Both final independent reviews are clear and independently pass the isolated
test. All 19 corrected webhook route tests pass in 27.776 seconds. The
original full-suite process retains its original error and is not claimed
green or restarted merely because of that observation.
