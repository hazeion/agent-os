# Explicit current Task seed fixtures

Base: current-only storage302468c47a4f401e7249dfc96ffd2b620086ab05.
This source-only fixture checkpoint is on a separate branch. Frozen QA262 and
its running full inventory remain untouched. No tests have run for this change.

Forty pre-authority Task seed literals across nine existing test modules now
carry all current required Task fields explicitly. There is no new shared
coercion helper, production normalization, skip, deadline or business assertion.
The existing synthetic metadata uses complete timezone-aware timestamps;
otherwise irrelevant missing creation times use the explicit UTC epoch. Seeds
without a selected Project retain the same General label. Synthetic source
metadata is explicitly test-owned. The dashboard replay and application
replacement fixtures use the current core status spelling `in progress` rather
than the retired `in_progress` alias; workflow-stage spellings are unchanged.

The ported modules retain their original current behavior coverage:

- daily reorder, zero rank, maximum Task ID, calendar link and grouped search;
- dashboard attention, counts, task replay and exact dependency locators;
- personal planning updates, dependency refusal and recurrence;
- vault-relative note attachment and path rejection;
- current data-schema product-write, symlink, reparse and root-identity guards;
- delegation setup, live Task authority and ignored stale JSON;
- exact deletion confirmation, revision change, duplicate-ID refusal, dependency
  blocking and active-Run protection;
- external operator data preservation across application replacement.

Only the initial record in the stale-JSON authority test is ported. Its later
sparse/invalid stale overwrite remains unchanged to prove it is ignored after
the SQLite receipt. Duplicate-ID seeds are otherwise complete current records,
so a missing-field error cannot mask the intended ambiguous-identity refusal.
Invalid browser request and non-Task fixtures are unchanged. Remote artifact
fixtures are owned separately and are not edited on this branch.

Static Python AST parsing succeeds for all nine modules. Every original
assertion expression, function name and decorator is exact. A second structural
comparison proves every original function AST is exact after removing only the
new seed metadata and restoring the two intentional status alias spellings.
The source-only diff has no whitespace errors. Scratch proof records:
`/private/tmp/mentat-current-task-seed-fixture-ast-proof.json` and
`/private/tmp/mentat-current-task-seed-fixture-semantic-proof.json`.

This is not a test pass. Root and independent review plus focused verification
against the composed strict seed validator remain required after the frozen
full inventory is terminal. No operator data, runtime, storage schema or
production capability is changed. Both fixture-first and later strict-source
histories must be retained when integrated.
