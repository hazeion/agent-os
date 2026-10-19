# Final-stack cache test integration

Status: local combined verification complete; independent review pending.

Start from repaired schema-46 producer tip `9024a87`. Preserve complete side
histories through normal merges of CI side 276, schema-43 cache side 309 and
schema-44 cache side 314. Preflight each merge tree before checkout changes;
an unexpected production delta stops integration. No production mutation,
readiness, provider policy or execution authority changes belong to this slice.

## Test composition agreed before implementation

The side cache suites contain seventeen unique test contracts. Retain all of
them and add one split historical recipe test. The schema-43 warm/restore and
journal-threshold fixtures run under an outer scoped private-unit schema-43
constant; schema-44 warm/restore, scope-threshold and scope-validation-fault
fixtures likewise run under schema 44. The outer patch covers complete cache,
temporary-root, filtering, restore, readback and teardown lifetimes. Every
original table, epoch, empty/unowned-state and fresh-validation assertion stays.

The generic recipe test stays on the actual current schema and immediate
predecessor, with five constructor misses and cache size one. Move side 314's
specific MAX(version)=43 and absent schema-44 scope-table assertions into a
separate schema-44-to-43 recipe fixture. The unsupported-future test stays
unpatched at actual current+1 and retains both failures, warm identity and
three constructor attempts. No source initializer, migration or validator
seam is patched to make a historical fixture pass.

Verify unique assertion coverage against both side suites, the full combined
eighteen-test module, existing CI/shard contracts and selected known/unknown
backup consistency checks. Hold the broad full Python run for final release QA
after the independent feature integrations. Obtain independent reviews before
any publication. No original checkout, shared publication metadata or remote
branch is changed here.

## Merge and coverage evidence

Each prospective merge tree was checked before modifying the checkout. Side
276 adds review records only; side 309 adds its records and cache tests; side
314 adds its records and produces one cache-test-only conflict. No review-file
conflicts occurred, and both complete records are retained. All original side
commits remain reachable through normal merges, without rebasing or replacing
their histories.

The combined module has eighteen methods: all seventeen unique side contracts
plus the split historical recipe case. AST comparison accounts for every
original method body and decorator after removing exactly five outer historical
schema contexts and normalizing one future-test name. The generic recipe body
has the same AST as side 309's current-schema contract. All eleven original
repaired-tip method names and their assertion ASTs are retained as well. Every unique
original assertion-call AST from both suites remains in the combined file,
including side 314's exact schema-43 maximum and absent scope-table SQL checks.
No new skip or deadline was introduced.

An exhaustive final diff against `9024a87` contains only review records and
`tests/test_empty_console_template.py`. Production code, migrations, producer,
Console/Task/Run authority, runtime helpers, source/dependency locks, workflow,
shard runner and existing CI contract bytes remain exactly that repaired tip.
The collect-each-canonical-test-once assertion is retained.

## Focused validation

One local Python 3.13 run passes all 32 selected methods without skips in
49.930 seconds: eighteen combined cache tests, eleven existing CI/shard contract
methods and these three private worker-journal backup cases:

- Empty backup/restore with schema-5 omission.
- Populated known completion restore without live execution authority.
- Populated unknown debit/token-hash restore without reissue.

The complete current and historical fixture graph therefore executes together.
All contexts restore the actual current schema and clear their private cache
after failure as well as success. Whitespace and Python parsing checks pass.
The broad full Python run remains intentionally deferred until the separately
reviewed feature branches are composed for one final release-QA invocation.
No Linux runtime, provider, owner-service or garage acceptance is claimed by
these local cache/backup checks, and no remote branch has been updated.
