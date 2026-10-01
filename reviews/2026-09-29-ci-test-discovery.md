# Remove accidental duplicate unittest discovery

`test_project_plans` and `test_project_plans_http` imported the helper
`TaskInputStorageTests` class into their module namespaces. Python unittest
discovery collects imported TestCase classes, so its 15 tests ran in both
consumers as well as the owning `test_task_inputs` module. Import the module
instead and retain the same helper construction, setup and registered cleanup.

On the current schema-42/parser branch, canonical ordinary discovery changes
from 2,389 executions to 2,359 executions. The before/after unique test-ID sets
are identical, and the new inventory executes each unique ID exactly once.
The CI discovery contract now rejects duplicate canonical IDs and continues to
compare the complete ordinary and sharded inventories. No test method,
platform/Python leg, assertion, fixture setup or teardown is removed.

A local canonical 15-test helper run took 25.3 seconds; the two duplicate passes
were redundant work. This is evidence about local fixture cost, not a claim
of hosted wall-time savings. Validate both Project plan modules, the canonical
Task input class and the complete CI inventory contract. Obtain two independent
read-only reviews before publishing a full PR.

All 35 affected Project plan/HTTP/helper tests and seven CI inventory contracts
pass. Both independent reviews confirm unchanged fixture setup/cleanup and
identical unique coverage, with no actionable findings.
