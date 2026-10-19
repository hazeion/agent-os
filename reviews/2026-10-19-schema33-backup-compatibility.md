# Retained schema-33 backup compatibility

The guarded PR 275 CI carry exposed a historical-backup failure on schema 34.
The initial 40-test focused run had one error: the synthetic template's schema
change test selected schema 33, which private-unit backup explicitly supports,
but provider validation rejected it. Fixing that first refusal exposed the same
omission in registry and Task validation. The Project, Conversation and Run
validators also omitted this retained version.

Add only literal schema 33 to those six existing bounded allowlists. Preserve
all other admitted versions, full schema fingerprints, authority receipts,
row and relationship validation, and existing runtime capability boundaries.
Keep the original recipe-keyed in-memory registry cache rather than replacing
it with the earlier foundation's memory-only constructor.

The provider and registry regressions build real historical schema-33 databases
and require unchanged versions and exact file bytes after validation. A third
regression initializes, filters and validates a complete empty historical
private unit. This covers the reported empty-backup graph; it does not claim
new populated-provider, live-runtime or owner-service qualification.

Two independent read-only reviews clear the final six-source/three-test repair.
Both confirm that existing validation remains in place. The second review
identified the additional historical allowlist omissions after the initial
provider fix. Those intermediate failures remain part of the evidence rather
than being reported as successful runs.

All 53 final Node, Inbox, template, registry and provider tests pass without
skips. The separate complete template group also passes all ten methods.
Hosted exact-head CI and integrated backup/restore acceptance remain required.
No PR merge or issue closure is claimed.
