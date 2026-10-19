# PR 314 cache compatibility carry

Status: two composition reviews clear; all 18 focused methods pass locally.

Original full PR head: `cb668deb1f41d901ebe1551f51a25d91eeeb82d7`.
Repaired parent: `2ea8acf5333c497f10d3d560dd73d504ea66161c`.
Branch: `codex/ci-side-cache-314`. This is a normal merge on the original
schema-44 cache branch, separate from the committed schema-43 cache carry.
No push, hosted pass or PR merge is claimed.

## Contract and resolution

The original and repaired parent have byte-identical `private_console_unit.py`.
Its code-owned one-entry cache, serialized construction, fresh validation,
live-root capture, and schema-44 scope/backup behavior are preserved. Schema,
scope journal and original scope-journal tests remain byte-identical to the
original branch. The manifest/lock conflict uses the reviewed parent only after
the dependency guard rejects any unique original dependency choices.

The template test conflict is resolved as a union. Both reviewed parent history
tests are added. All original schema-44 tests remain, including unowned empty
state and fresh restore epochs, scope-threshold recipe invalidation, current
scope validator fault detection, and the exact previous-schema-43 readback
without a schema-44 scope table. Those method bodies and decorators are
unchanged.

Only the obsolete unsupported-schema-42 fixture changes semantically. Schema
42 is now explicitly supported by the reviewed bounded compatibility repair,
so it is covered by the positive historical test rather than falsely rejected.
The original error-cache test now selects `units.DATABASE_SCHEMA_VERSION + 1`
and is named `unsupported_future_schema_recipe`. It retains two failing
construction attempts, exact reuse of the original warm template, and exactly
three constructor calls. No validation error is cached or normalized into
success. No broader version range or runtime/Run authority is introduced.

Only the new review record is edited directly. Shared carry records inherited
through the normal parent merge are not rewritten.

## Verification plan

Run the complete template module and selected scope-journal cases for prepared
backup/restore, refusal of active capture without source changes, and exact
schema-43 capture/validation/upgrade. Check conflict absence, original source
identity and method/decorator preservation before the local merge commit.
Root and an independent peer must review the concrete composition before
publication. Linux scope execution, hosted exact-head CI and integrated
acceptance remain separate gates.

Root and an independent peer verified the concrete final test composition at
template SHA256 `926aa82bdc7cf3526205d116d2811fe381442debe1e83e287f6efd7d990d3bbf`.
All 18 focused methods pass without skips in 36.740 seconds: all 15 template
tests and the three selected scope-journal backup/capture/upgrade cases. The
future-schema case retains two errors, exact warm-template identity and three
constructor calls. No test source changed after those reviews. Source identity,
conflict absence and whitespace checks pass. These are local schema-44 results,
not Linux namespace execution or a combined later-schema integration claim.
