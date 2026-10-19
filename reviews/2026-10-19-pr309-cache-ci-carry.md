# PR 309 cache compatibility carry

Status: two composition reviews clear; all 16 focused methods pass locally.

Original full PR head: `d283dc42a7dbca7a8a6f126479fa8958ea266f8d`.
Repaired parent: `1e659a2d43720a87bf6c87d5708cb78747301a9b`.
Branch: `codex/ci-side-cache-309`. This is a normal merge of the repaired
Project-runtime-origin parent, preserving the original PR history. No push,
hosted acceptance or PR merge is claimed by this record.

## Resolution and preserved contract

`private_console_unit.py` is byte-identical between the original PR and repaired
parent before the merge. Both already implement the one-entry immutable empty
template cache, exact code-owned recipe, serialized misses, fresh per-caller
validation and unchanged live-root capture. No replacement of that production
feature is needed. Schema 43, worker journal, source and public-origin contracts
remain intact.

Only the dependency manifest/lock and the template-test file conflict. The
manifest/lock use the exact reviewed parent after guards establish that there
are no unique dependency choices to discard. The template tests retain both
original schema-43 additions exactly: unowned synthetic state with fresh
restore epochs, and journal-threshold recipe cache invalidation. Parent schema
33 and retained Project-schema backup regressions are added alongside them.

One old test subcase explicitly expected schema 42 to fail because provider
validation omitted it. The repaired parent fixes that already-promised retained
version across the six bounded validators. That obsolete refusal expectation
now uses the reviewed parent's successful construction and different-database-
bytes assertion. It still proves a changed recipe misses the warm schema-43
cache and retains the exact five-construction and one-entry cache assertions.
All other original template methods and decorators remain AST-identical.
This is an explicit supported-version correction, not a dropped refusal test
or relaxed validation requirement.

The union helper preserves only explicit implemented historical versions
38 through 42 beneath current schema 43. Full fingerprints, rows, receipts,
schema bounds and production no-dispatch gates are unchanged. No owner/runtime
configuration, provider, credentials or service is touched.

## Verification plan

Run the complete `tests.test_empty_console_template` module and the three
worker-journal backup/restore cases for empty, known and unknown records with
the existing read-only shared Python environment. The original journal source
and its tests remain byte-identical; its complete 25-method group already has
parent-branch evidence, which is not claimed as a rerun on this head. Preserve
original schema-43 and journal assertions. Check
source equality, original method/decorator inventory, conflict absence and
staged whitespace before the local merge commit. The shared performance
measurement takes priority; no new heavy test group starts during its quiet
window. Record actual results here after the run, and obtain two independent
composition reviews before publication. Root and an independent peer have
verified the original method/decorator preservation and explicit schema-42
correction against template-file SHA256
`c6fdc2ade6210b4305c5eaeefcda338b307ebf0a3420956ee4aa854ad388459d`.
Hosted current-head checks and
integrated acceptance remain separate gates.

The final focused run passed all 16 discovered methods without skips in
88.284 seconds: all 13 template tests, including both original schema-43
regressions, and all three selected journal backup/restore tests. The repaired
schema-42 recipe subcase succeeds with distinct bytes and five constructor
calls. Empty, known-result and unknown/token-hash journal backup graphs retain
their exact restore/fencing assertions. No test source or assertion changed
after the two composition reviews. Conflict absence and whitespace checks pass.
