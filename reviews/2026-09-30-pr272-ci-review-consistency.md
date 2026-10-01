# PR #272 CI review consistency

Publication base: `7cfca09b9e98d673c33536296d6820d85a25154f`. Shared historical review:
`d92e1d62c3bc2fe7805a5dd09a30ef979c44013b:reviews/2026-09-29-ci-efficiency.md`.
The shared record is kept byte-identical across these branches. Its timings
and schema 42 qualification are historical, not measurements of this branch.
Only its location changes: branch-specific evidence below remains separate
so stacked PRs avoid conflicting add/add or independently replaced prefixes.
Source, matrix, security coverage and existing branch deadlines remain intact.

## Prior branch-specific qualification

The following preamble is historical and retained from the exact prior head;
its references to earlier reviewed branches and timings remain unchanged.

# CI execution efficiency

## PR #272 compatible replay

This branch replays the reviewed PR #273 scheduler and private-fixture changes.
Its baseline runner and CI contracts are identical; TaskRepository differs only
in the expected schema number. Original 30-minute watchdog and workflow limits
remain unchanged. Fourteen compatibility/CI methods and two actual overlapping
private split children pass here, with zero lock-audit vulnerabilities. The
record below is historical PR #273/276 measurement and review evidence, not a
new measurement or hosted speed claim for this branch.

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
