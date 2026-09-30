# CI execution efficiency

## PR #287 compatible replay

This branch replays the reviewed PR #273 scheduler/private fixtures, retaining
its original40-minute group watchdog and workflow limits. The prepared runner
and CI contract differ from the30-minute backport only in this unchanged
existing watchdog and its matching assertion. All other split-module sources
are unchanged; TaskRepository differs only expected schema number. Fourteen
compatibility/CI methods and two actual overlapping private split children pass
here, with zero lock-audit vulnerabilities. Historical PR #273/276 measurements
below are not new branch or hosted speed evidence.

## Older-base compatibility backport

This PR #273 backport starts at `2fd7e7d` and preserves its original 30-minute
group watchdog and unchanged workflow/job limits. It copies only the reviewed
two-child split-unit overlap plus fixture-free Task repository distribution;
no product/schema changes or timeout increase. Exact coverage preserves the
ordinary-discovery ID multiset and schedules every selected unit once. This
older source has 2,241 ordinary executions but 2,226 unique IDs (15 existing
imported-fixture duplicates); this scheduler preserves that inventory. Removing
those accidental duplicate IDs is separate reviewed discovery work, not a claim
made by this backport. The record below is historical PR #276/schema-42
evidence; its 40-minute values are not this older branch's limits.

Measured this exact older branch's three slow backup/schema units sequentially:
44.219 seconds, then 31.953 seconds with two-child overlap (27.7% lower wall
time), all passed. Individual durations increased under contention from
12.122/17.182/14.084 to 15.969/22.840/15.405 seconds. All 11 exact-coverage and
scheduler contracts pass with the unchanged 30-minute deadline. These are
local subset measurements; hosted full-group improvement is unproven. Obtain
two independent old-base compatibility reviews before publishing.

The complete mixed group discovered 181 tests and exposed one unrelated fixture
error: the mocked identity-apply test still resolved the machine's installed
Hermes interpreter. Patch that lookup to a fixed fixture value and require the
same exact apply arguments, so tests never inspect an owner's runtime install.
The 16 identity, owner-website and planning-integration methods pass with this
isolated lookup. A repeated full group exposed two legacy Console fixtures
reusing fixed Run IDs in the checkout's runtime directory: stale exclusive-create
telemetry made their mocked launch fail. Each now uses its own TemporaryDirectory
as DATA_DIR. Exact command, resume, response, PATH and Hermes-home assertions
remain; 25 dashboard methods plus both repeated fixture methods (27) pass.
The complete mixed group then passed on a repeated invocation (181 test
executions); all 11 CI contracts passed again. Two independent reviewers
cleared the scheduler compatibility changes; both must also clear the final
private fixture isolation before publication.

Scope: retain every platform/Python leg, test, syntax check, dependency/security
gate, fixture boundary, and existing watchdog. Improve execution time inside
the current Windows jobs. No product/runtime authority changes.

## Evidence

The successful baseline [CI run 36610505935](https://github.com/hazeion/agent-os/actions/runs/36610505935)
ran from 18:13:21 to 20:13:23 UTC on September 29, 2026. GitHub's job/step
timestamps distinguish runner queue delay from test execution:

| Platform | Jobs | Test-step range | Sum of test-step time | Largest start delay |
| --- | ---: | ---: | ---: | ---: |
| Linux | 3 | 17.43–19.47 min | 56.30 min | 0.05 min |
| macOS Intel | 3 | 30.72–45.33 min | 116.55 min | 0.05 min |
| Windows | 36 | 5.75–26.02 min | 466.38 min | 93.23 min |

The final Windows groups waited over 90 minutes to start. Windows setup and
syntax steps are roughly one minute; test execution dominates runner occupancy.
Warm Linux dependency installation was 6–8 seconds in this run. Additional
cache work would not address the primary measured bottleneck.

For example, [Windows Python 3.12 group 7](https://github.com/hazeion/agent-os/actions/runs/36610505935/job/109550400039)
spent about 93 seconds on one backup recovery test, 149 seconds on a second,
and 129 seconds on the schema inventory test, executing them sequentially.
This motivates conservative overlap of independent filesystem/SQLite fixtures.

## Change and boundaries

`run_group` overlaps at most two consecutive split-test units, each still in
a fresh isolated subprocess. A whole-module unit is a serial barrier: preceding
split children finish before it starts, and it finishes before another child
starts. Ordinary assertion failures remain non-fail-fast within the group.
The existing global 40-minute watchdog is checked before each new child, and
watchdog expiry, cancellation, spawn/poll/reap exceptions stop every owned
active process tree. The 5-second process-stop/reap limits remain unchanged.

The split allowlist is unchanged. The four modules were reviewed for resources
that would make cross-process overlap unsafe:

- `test_data_backup_restore`: independent `TemporaryDirectory` trees, backup
  roots, restore destinations, and recovery markers; CLI subprocesses receive
  explicit temporary `--data-dir` and backup paths. No live listener or shared
  service mutation.
- `test_data_schema`: temporary seed/data/home trees; junction/reparse and
  permission tests operate on paths under those fixtures. Patches and thread
  coordination remain inside one test subprocess. No fixed listening port.
- `test_private_console_state`: temporary authority/blob roots and independent
  SQLite snapshots; the crash-journal subprocess receives its fixture's exact
  database path. Deletes and permission changes target fixture-owned trees.
- `test_task_repository`: temporary task/authority/compatible-export roots;
  tracked seeds and source files are read as fixtures, then copied into private
  test roots. SQLite races, environment/module patches, and threads remain
  local to one child. No external runtime is invoked.

Fixture-free discovery checks continue to reject module/class fixtures and
cleanup hooks before split execution. The inventory is still dynamically
discovered and its multiset compared with ordinary unittest discovery: 194
modules, 388 isolated units (198 split units), and 2,382 tests on this branch,
including the four new scheduler contracts. There is no cached inventory or
timing profile that could silently omit a new test.

## Local measurement and validation

Windows Python 3.11 used the exact three slow backup/schema tests named above
on the schema-42 PR #291 source tree (`93c9e07`, then packaging-only correction
`aef6f08`), the same interpreter, fixture construction, and fresh process
boundary. The inventory counts above describe that tree. The scheduler and
contract-test baseline is identical to PR #276 (`6dcace6`); publishing the
optimization independently on that base requires its own contract rerun.

| Experiment | Sequential | Two children | Wall-time decrease |
| --- | ---: | ---: | ---: |
| Original runner, then changed runner | 57.094 s | 45.906 s | 19.6% |
| Changed runner, two then one child | 57.000 s | 42.672 s | 25.1% |

Every selected test passed. The reverse-order repetition reduces cache-order
bias. Contention made individual test durations longer (first trial: 15.636 to
21.986 s, 21.922 to 32.910 s, 18.392 to 23.250 s), so the measured improvement
is substantially below an assumed twofold speedup. Keep the ceiling at two.
These are local subset measurements, not proof of hosted full-suite improvement
or reduced GitHub queue delay. Hosted job/step timings must establish that after
the reviewed branch runs.

The 11 CI contracts pass, including exact discovery coverage, serial barriers,
maximum concurrency, continued membership after assertion failure, deadline
expiry between spawns, and cleanup on spawn/poll/reap/cancellation failures.
Complete Windows group 11 passed: 34 isolated units and 193 discovered tests
(five existing platform/build skips), including all four split modules and
serial whole-module HTTP, auth, delegation, and upgrade checks. The command
was `python scripts/run_unittest_shards.py --run-group 11`. Python compilation
and `git diff --check` also pass.

## Deferred investigation

The POSIX matrix still runs its complete suite sequentially. Parallelizing it
would require a separate resource/fixture review and measurement. Reducing the
Windows matrix, skipping paths, relaxing security checks, reusing private data
fixtures, or increasing watchdogs is outside this change. Account runner
capacity and the number of concurrent PR stacks affect queue delay; this code
change cannot promise to remove that delay.

The expected SQLite schema signature has a process-local cache. Each isolated
single-test subprocess computes its own expected migration signatures again;
overlap reduces wall time while preserving that CPU cost. Profiling that cost,
batching fixture-free tests, or changing immutable schema computation caching
requires a separate isolation and production review.
