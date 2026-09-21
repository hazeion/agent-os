# Webhook probe CI fixture lifecycle

Parent PR 243 Windows Python 3.12 group 1 failed in the live same-origin probe
test: a fixed three-second probe returned 503 and teardown found SQLite still
open. Read-only diagnosis reproduced the mechanism by delaying receiver work
while it held a database connection. The full local module passed without the
injected delay; the CI log does not prove the exact slow initialization step.

The fixture previously migrated SQLite inside its first timed request and used
daemon request workers, which server_close does not drain. This correction warms
the fixture database before the success deadline and gives test-owned IPv4/IPv6
servers non-daemon workers. A synchronization-based timeout regression asserts
safe failure, one submission and worker completion before cleanup. Production
timeout, receiver policy and failure semantics remain unchanged.

All 15 webhook-health tests pass. Two independent read-only reviewers found no
actionable concerns and each independently reran the complete 15-test module.
This is a correction to the parent CI gate, not acceptance of either
success/failure in success-path tests. Production code is unchanged.
