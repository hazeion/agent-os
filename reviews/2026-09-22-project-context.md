# Project context and versioned deliverables

Scope: [authorized Project context and versioned deliverables](https://github.com/hazeion/agent-os/issues/238).
Baseline: website branch `cf856e0`; no Project-context execution is implemented
or advertised by this contract slice.

## Evidence and proposed sequence

The existing Project/Task repositories are canonical SQLite authorities with
whole-collection replacement paths. Conversation planning links explicitly
carry no execution or file authority. Existing attachment retention, GC,
capacity and backup pruning recognize Run references only; merely adding a
Project-file table would lose files. The approved architecture contract adds a
real second retained reference graph rather than fake Runs.

Implementation sequence:

1. [Immutable Project storage](https://github.com/hazeion/agent-os/issues/260):
   Project briefs/file revisions, scope incarnations, retained
   attachment references, strict quotas and exact backup/restore support.
   Preserve rejection of ordinary collection-removal and Task moves; integrate
   the separately confirmed Project/Task deletion service and ID-reuse rules.
   No dispatch.
2. [Owner editor and grants](https://github.com/hazeion/agent-os/issues/261):
   explicit revision-bound Agent grants, safe file
   access and version pruning preview/confirmation. No grant from assignment.
3. [Approved Task inputs](https://github.com/hazeion/agent-os/issues/262):
   exact snapshots and Run reservation/materialization,
   runtime qualification, revocation/retry races and scoped result handoffs.
   Coordinate this boundary with the approved-plan issue; do not expose an
   alternate scheduler or bypass Hermes Kanban.
4. [Versioned deliverables](https://github.com/hazeion/agent-os/issues/263):
   trusted output promotion, immutable versions and owner editing;
   garage layout data/image, editable source/product document and implementation
   sequence. Exact owner acceptance belongs to the Project review/inbox slice.

## Required acceptance evidence

- Project-only file survives GC, restart and backup/restore; shared bytes survive
  removal of either Run or Project reference; missing/tampered blobs fail closed.
- Migration preserves old authorities; exact schema validation rejects drift;
  old supported backups still restore, and compatible export does not modify
  source or smuggle unsupported authority into the sibling.
- Concurrent edit/grant/dispatch/revoke and quota races have one exact outcome.
  ID reuse, Task moves, reassignment and runtime configuration changes cannot
  revive stale approval. Restart/restore never resumes pending work.
- Each Agent sees only its approved Project/Task/result snapshot through the
  qualified adapter. Revocation prevents new work/reads while preserving the
  truthful already-delivered limitation and a verified Stop action.
- Deliverables import only registered output provenance, survive Run pruning,
  retain previous versions after edits and require exact-version acceptance.
- Browser desktop/mobile workflow creates a brief, uploads a floorplan,
  explicitly grants selected context, assigns manually or approves a plan,
  inspects versioned outputs and requests a revision. Missing dimensions block
  layout execution through an owner question; no fabricated measurements.
- Every implementation slice gets two independent reviews and corrections
  until clean, followed by a tested PR. Real garage/runtime qualification remains
  separate from fixture success.

## Review status

Initial independent storage review confirmed the second-reference-root design
and identified GC/backup/capacity updates as an indivisible implementation unit.
Two independent full-contract reviews identified execution-limit ambiguity,
uncertain-dispatch evidence on restore, and incomplete metadata quota coverage.
The corrected contract explicitly selects bounded Task inputs, preserves all
possibly dispatched evidence without replay, and bounds the entire new graph.
Both reviewers re-reviewed the final contract and report no remaining concerns.
Adjacent stale unauthenticated-only architecture statements were also corrected
to match the existing explicit owner website mode.

This is a documentation/contract slice; no runtime tests or live execution claim
apply. Implementation and its required acceptance evidence remain open in the
four native child issues. The first storage child is the next implementation
slice, with both retention and backup updated together.

## Storage implementation and verification

The active storage branch introduces schema 27, immutable context versions,
ordered attachment references, exact Project/context revision publication and
a shared retained-attachment view. GC/release/reconciliation and backup filters
are being extended to that union. Tests exercise Project-only persistence,
shared-blob lifetime, stale/concurrent publication, quota rollback, tampering,
whole-collection rename and exact backup inventory. This completes the first
storage slice, not the owner editor, grants or execution slices.

Storage review corrections: explicit non-null/type-checked IDs prevent malformed
SQLite values from escaping bounded validation; an immutable file-list digest
detects partial reference removal; all schema allowlists retain version 26,
including the Run repository. A new populated, claimed schema-26 Run-authority
backup test validates, restores and upgrades the historical state. Both final
whole-slice reviewers report no remaining actionable concerns.

Verification before publication:

- 196 migration, Task/Run repository, owner-auth and provider tests pass, with
  eight platform-specific skips on Windows.
- 46 focused Project-context, Google transaction and owner-method tests pass.
  The additional two-Project concurrent blob-quota regression also passes.
- The 53-test private backup/state module passed (one platform-specific skip)
  in the broader 90-test run. That run exposed two stale current-version
  assertions in auth tests; both were corrected and pass in the final focused
  and migration runs above.
- Real archive backup/restore retains Project-only files. A populated historical
  schema-26 Run backup validates, restores and upgrades. Compatible schema-5
  private export omits Project authority/files and leaves source unchanged.
- Wheel and source archive pass exact inventory/integrity checks. An isolated
  installed-wheel smoke publishes/reads context, survives GC, and captures and
  validates the retained backup bytes.

No new browser or Agent execution capability is exposed. Linux platform checks
remain subject to PR CI; real garage/runtime acceptance is still open.

## Confirmed deletion correction

Following the editor's full call path exposed a gap in the initial review:
ordinary Project replacement rejects removal, but `planning_deletion.py`
already implements a separate confirmed deletion capability. The previous
statement that Project deletion was unavailable was incorrect.

Before the unreleased schema-27 PR merges, its scope table now supports terminal
retirement and a unique live Project-ID mapping. Confirmed deletion retires
scope authority atomically while retaining versions/files. Task deletion uses
the union retention root when orphaning Run files. Previews bind affected
context manifests and disclose retained history through a bounded count. An
old deletion receipt cannot be replayed against a recreated target.

New regressions cover Project-only files through deletion/GC/backup/restore,
fresh context after ID reuse, stale preview after context edits, shared Run and
Project files through Task deletion, and rollback after both retirement and
canonical deletion. This refines the draft migration before release; all
Project data created by this work remains disposable test data. Editor and
grant work follows this integration correction.

Correction verification: both independent reviews are clean; 88 storage,
deletion and private-bridge checks passed, followed by 41 focused context,
deletion and planning-bridge checks including the positive retained-count
projection. All 386 web tests pass, including the rendered retention notice.
TypeScript, ESLint and the production build pass. Rebuilt wheel/sdist inventory
and integrity checks pass; an isolated installed-wheel smoke confirms exact
deletion, retired owner history, GC protection and backup. Fresh CI remains
required before merging the draft PR.

## CI worker cleanup correction

The Windows3.11 matrix reported that the immediate-completion test's worker had
not finished within its five-second join; the temporary-root cleanup then hit
an open initialization lock. The test now always releases and drains the worker
in a finally block, captures a bounded stack after five seconds, and allows a
further25 seconds for cleanup before failing. Exactly-once queue assertions and
production deadlines are unchanged. The exact test passes locally in about two
seconds; two independent reviews are clean.
