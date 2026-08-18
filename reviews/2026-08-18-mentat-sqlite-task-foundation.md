# Feature Slice Review: SQLite Task Foundation and Migration Preview

Status: Ready for outcome review
Slice: `mentat-sqlite-task-foundation`
Date: `2026-08-18`
Review log: `reviews/2026-08-18-mentat-sqlite-task-foundation.md`

## Slice contract

### Goal

Mentat can represent every valid existing planning Task in its current
owner-private `mentat.sqlite3`, reconstruct the public Task document exactly,
and preview the eventual `tasks.json` migration without changing the live Task
source yet.

### In scope

- Advance the existing `mentat.sqlite3` schema additively from version 4 and
  retain its WAL, owner-private, forward-version-refusal, and exact-schema
  guarantees.
- Add a storage-neutral Task repository whose canonical schema separates:
  indexed scalar task fields; ordered unique tags; ordered dependency edges;
  bounded validated nested planning/delegation JSON; and bounded unknown
  top-level compatibility fields. No field is duplicated as a competing
  canonical value.
- Include a monotonically increasing Task revision even though live JSON APIs
  do not consume it until Slice 1C-B.
- Preserve every field currently accepted by `validate_task_payload()` and
  `normalize_task_planning()`, including safe unknown top-level compatibility
  fields, while rejecting malformed JSON, duplicate IDs, missing/self/cyclic
  dependencies, invalid planning metadata, and repository bounds.
- Add an exact read-only migration preview for the resolved live `tasks.json`.
  The preview reports source identity/digest, count, IDs, destination schema
  and occupancy, and a confirmation fingerprint for the future cutover, but
  performs no Task-table writes.
- Add a transaction-scoped import primitive used only by tests in this slice.
  It must bind the exact preview/source and empty destination, import all Tasks
  atomically, and prove semantic reconstruction; no production confirmation or
  startup auto-import is exposed yet.
- Add a deterministic bounded JSON export/reconstruction operation for a Task
  repository. It is diagnostic/recovery infrastructure, not a second live
  source.
- Preserve canonical Task rows and dependency integrity in existing private
  SQLite backup/restore snapshots; include Task counts and semantic validation
  in private-unit evidence where needed.
- Update the pivot plan, system-design reference, architecture/data-layout
  contract, changelog, and this review record.

### Out of scope

- Switching any dashboard, API, attachment reconciliation, delegation,
  reporting, or search path away from `tasks.json`.
- A production migration confirmation, startup auto-import, dual read, dual
  write, or shadow synchronization.
- Task API shape changes, Agent assignment UI, durable Runs/AgentEvents,
  runtime dispatch, event retention, SSE, or React/Next.js work.
- Migrating `agent-registry.sqlite3`; that convergence is recorded as Slice 3C.
- Importing unverifiable historical Console runs or Hermes-native payloads.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A schema-4 database migrates atomically to the new exact schema; empty initialization, idempotent reopen, integrity/foreign keys, sidecar safety, and newer-schema refusal all pass. | Migration and private-database tests. | Pass |
| AC-2 | The repository round-trips every supported core/planning/delegation field, ordered tags/dependencies, empty/null distinctions, timestamps, revisions, and safe unknown top-level fields without canonical duplication. | Table-driven repository and semantic reconstruction tests. | Pass |
| AC-3 | Invalid IDs, duplicate Tasks/tags, missing/self/cyclic dependencies, malformed nested metadata, oversized collections/documents, non-JSON values, and stale revisions fail closed with no partial mutation. | Negative and transaction rollback tests. | Pass |
| AC-4 | Migration preview is bounded and read-only, validates the resolved `tasks.json` and destination database, and binds exact source bytes/identity plus destination schema/occupancy without exposing local paths or Task contents. | Preview, privacy, source-drift, link/permission, and no-write tests. | Pass |
| AC-5 | The import primitive writes only to an empty Task repository under the shared private-state lock, revalidates the preview, commits all Tasks or none, and reconstructs the normalized source semantically; it is not reachable from production CLI/API/startup in 1C-A. | Transaction, drift, interruption, occupancy, and route/CLI absence tests. | Pass |
| AC-6 | Deterministic export is bounded, read-only, stable across reopen, and reproduces the current Task list shape without becoming a tracked or runtime JSON authority. | Export digest/order/no-write tests. | Pass |
| AC-7 | Supported private backup/restore snapshots retain canonical Task rows and dependency integrity, reject semantic corruption, and remain compatible with the separately versioned Agent Registry unit. | Private backup/restore round-trip and corruption tests. | Pass |
| AC-8 | Existing live Task behavior remains JSON-backed in this slice, with unchanged HTTP/browser payloads and no Task writes to SQLite from production flows. | Existing task suites plus architecture/source assertions and browser regression. | Pass |
| AC-9 | Focused checks, the full suite, package/secret checks, documentation verification, and two independent adversarial reviews complete with no blocking finding. | Verification and review records below. | Pass |

### Constraints and recovery

- Safety: use the existing private-state lock, exact-path/link/mode checks, WAL
  snapshot semantics, parameterized SQL, and bounded public errors. Never store
  credentials, local paths, raw webhook bodies, chain-of-thought, or Hermes
  payloads in Task tables.
- Compatibility: schema migration is additive to `mentat.sqlite3`; live Task
  APIs and `tasks.json` behavior do not change in 1C-A. The separate Agent
  Registry and its backup format remain authoritative and compatible.
- Rendered behavior: only an operator-facing migration preview may be added;
  the dashboard must remain visually and behaviorally unchanged.
- Rollback or recovery: before 1C-B, rolling back application code leaves
  `tasks.json` authoritative. Older code may not understand a newer shared
  private database, so publication requires an exact private backup and an
  explicit downgrade note; no operator Task import occurs in this slice.
- Documentation targets: `ARCHITECTURE.md`, `DATA_LAYOUT.md`,
  `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`, `PIVOT_README.md`, `CHANGELOG.md`, and
  this review record.
- Version-control strategy: branch `codex/sqlite-orchestration-design` from
  `origin/main`; ready PR targets `main`. The primary dirty working copy is not
  used. Publication still requires immediate explicit user approval.

### Scope discussion and approval

- Recommendation and rationale: extend the already secured and backed-up
  `mentat.sqlite3` instead of creating a third database. Prove schema,
  reconstruction, preview, and recovery first; perform the one-way live
  source-of-truth cutover only in Slice 1C-B.
- Alternatives considered: keeping `tasks.json` cannot atomically coordinate
  Tasks/Runs/events; a third database delays convergence; immediate total
  database unification expands the first cutover into Agent Registry and
  attachment migration; dual writes create competing authorities.
- User decisions: selected the middle-ground SQLite architecture, required one
  eventual unified database as the long-term destination, authorized slice
  adjustment, and requested implementation under the reviewed-feature process.
- Approved at: 2026-08-18. The user explicitly approved Slice 1C-A's exact
  contract and test strategy and asked the workflow to proceed.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | `mentat.sqlite3` schema 4 has no canonical Task tables. | Initialize empty/current databases; inspect exact tables/indexes/FKs; reopen; corrupt/forward-version/link/sidecar cases. | Additive, fail-closed schema lifecycle. | Does not prove the later live cutover. |
| AC-2 | Tasks exist only as JSON documents. | Parameterized fixtures covering legacy, full planning, delegation, unknown compatibility fields, ordering, nulls, and revisions. | Lossless semantic reconstruction without duplicated authority. | Byte-for-byte whitespace/key order is intentionally not preserved. |
| AC-3 | Existing validation is file-mutation oriented. | Repository rollback tests for every invalid graph/type/bound and optimistic-revision conflict. | Invalid state cannot partially enter SQLite. | High-contention load remains bounded to local SQLite. |
| AC-4 | No SQLite Task migration preview exists. | Read-only preview tests for exact digest/token binding, changed source/DB, malformed/linked/oversized source, privacy, and no sidecars/writes. | Safe operator knowledge before migration. | Confirmation is intentionally absent until 1C-B. |
| AC-5 | No exact transactional Task import primitive exists. | Temp-database imports with injected failures, stale confirmation, nonempty target, duplicate IDs, graph failure, and post-import reconstruction checks; production reachability assertions. | Future cutover core is atomic and not prematurely active. | Crash-resume orchestration belongs to 1C-B. |
| AC-6 | No repository export exists. | Stable canonical JSON and digest across repeated export/reopen; size/count bounds and read-only identity checks. | Recovery/diagnostic representation is deterministic. | Export is not an automatic rollback mechanism. |
| AC-7 | Private snapshot filtering knows schema 4 only. | WAL-live capture, restore, semantic corruption, FK corruption, and Task-count evidence with Agent Registry format compatibility. | Tasks survive supported recovery as part of the private unit. | Full cutover backup UX is finalized in 1C-B. |
| AC-8 | Production code has many direct `tasks.json` paths. | Existing planning/deletion/delegation/dashboard tests; source assertions that 1C-A adds no production repository caller; Chromium smoke. | No premature behavior/source change. | Lighthouse is a final 1C-D gate, not a schema-slice signal. |
| AC-9 | No evidence exists for this slice. | Focused suites, full unittest suite, syntax/whitespace, artifact inventory, pinned secret scan, two independent reviews. | Broad regression and release confidence. | GitHub platform CI runs after publication. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python -m unittest tests.test_private_console_state tests.test_task_planning tests.test_task_planning_server tests.test_task_deletion tests.test_data_backup_restore tests.test_legacy_data_migration -v` | macOS, clean `origin/main` at `78f3bdf` | Pass | 102 tests passed before implementation. |
| `python -m unittest discover -s tests -q` | macOS host, planning branch before runtime implementation | Pass | 1,114 tests passed, 4 skipped. The sandbox run's seven loopback-bind errors were environment-only; host execution passed after the roadmap contract assertion was updated from merged Slice 1B to proposed Slice 1C-A. |
| Repository inspection | Isolated branch from current `origin/main` | Gap confirmed | Shared private database is schema 4; live Task reads/writes remain direct `tasks.json` operations; the Agent Registry is a separate owner-private database. |
| System-design render and audit | Template-based DOCX, eight rendered pages | Pass | Visual inspection passed; accessibility audit reports 0 high/medium/low findings; no visible placeholder text remains. |

### Test discussion and approval

- User questions and decisions: the user selected SQLite over retained JSON,
  selected the middle-ground sequencing, and required eventual full database
  unification plus Lighthouse 100/100/100/100 at the completed orchestration
  milestone.
- Accepted coverage gaps: no live
  cutover, Run/Event/dispatch behavior, new frontend, second runtime, or
  Lighthouse rerun in 1C-A.
- Approved at: 2026-08-18.

## Implementation record

### Changes

- Advanced `mentat.sqlite3` from schema 4 to schema 5 with exact canonical Task,
  ordered-tag, and ordered-dependency tables plus bounded indexes and deferred
  foreign keys.
- Added `task_repository.py` with exact Task normalization/reconstruction,
  optimistic-revision replacement, atomic empty-repository import, semantic
  corruption checks, deterministic export, and bounded immutable/WAL-snapshot
  reads that do not mutate the source database set.
- Added exact `tasks.json` migration preview through both the server runtime CLI
  and unified `mentat task-migration` command. No production confirmation,
  import, startup migration, API route, shadow read, or dual write was added.
- Extended private Console backup/restore evidence and validation with Task
  counts, Task semantic reconstruction, dependency checks, and corruption
  refusal while preserving the separate Agent Registry unit.
- Added repository, migration, privacy, WAL, rollback, CLI, backup/restore,
  architecture, and packaging coverage; added the module to exact artifact
  inventories.
- Updated the pivot plan, system-design index, architecture, data-layout,
  contributor contract, and changelog.

### Deviations and decisions

- A live-WAL test demonstrated that SQLite `mode=ro` can update source SHM
  bytes. Preview/export now copy bounded main/WAL bytes to a private temporary
  snapshot whenever sidecars exist; a closed sidecar-free database is opened
  with `immutable=1`. Exact source main/WAL bytes and file identities are
  rechecked after inspection.
- The first full implementation suite found that `task_repository.py` was
  missing from the independent artifact allowlist. The allowlist was updated,
  its focused regression passed, and the full suite was rerun successfully.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| System-design template fidelity, render, accessibility, section, image, field, and footnote audits | Isolated branch | `0` | 8 pages; 0 accessibility findings | `design/system-design/MENTAT_SQLITE_ORCHESTRATION_SYSTEM_DESIGN.docx` |
| `git diff --check` and `python -m py_compile ...` | Isolated branch | `0` | No whitespace or syntax failures | Covers all changed Python entry points and the new repository tests. |
| `python -m unittest tests.test_task_repository ... tests.test_ci_quality_gate -q` | Isolated branch | `0` | 168 passed | Post-Round-2 repository, private recovery, registry, CLI/runtime config, packaging, architecture, and quality-gate focus. |
| `python -m build --no-isolation --sdist --wheel` plus `python scripts/verify_python_artifacts.py` | Isolated branch; pinned build tools in temporary dependency directory | `0` | Wheel and sdist verified | Both artifacts include `task_repository.py`; exact public inventories pass. |
| `python scripts/check_tracked_secrets.py` | Isolated branch; pinned scanner in temporary dependency directory | `0` | No new candidates | Tracked-file secret scan passed. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -q` | macOS host, completed Round 2 fixes | `0` | 1,139 passed, 4 skipped | Full regression after the source-replacement, replace-result, SQL-literal, and downgrade-order corrections; loopback tests require host execution. |

### Rendered or manual behavior

- The system-design reference was rendered and visually inspected on all eight
  pages.
- Chromium browser smoke passed all 46 named desktop/mobile, navigation,
  Console, Task, Calendar, Agent, Context Pack, Settings, accessibility, and
  diagnostics checks against a temporary data root. The dashboard has no
  visual or payload changes in this slice.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: complete unstaged working diff on
  `codex/sqlite-orchestration-design` from `origin/main` at `78f3bdf`.
- Verification evidence: 159 focused tests, 1,130 full-suite tests with 4
  platform skips, exact wheel/sdist verification, tracked-secret scan, and
  46-check Chromium smoke, all passing.
- Rendered artifacts: eight-page SQLite orchestration system-design reference;
  no browser visual changes.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-01 | High | Yes | Task schema fingerprint ignored unexpected Task triggers, allowing hidden side effects during import. | Yes | Include every schema object owned by a Task table and revalidate immediately before mutation. |
| A-02 | High | Yes | Exact schema-4 format-3 backups were rejected as unsupported after the schema-5 bump. | Yes | Validate exact released schema 4 as a supported restore input and migrate on normal open. |
| A-03 | Medium | Yes | Read-only preview created `.mentat-initialization.lock`. | Yes | Use the pinned no-write lock mode and fail closed on source drift. |
| A-04 | Medium | Yes | A deferred-FK commit failure could leave the transaction active. | Yes | Roll back when `commit()` raises and test the deferred-FK path. |
| A-05 | Medium | Yes | `get()` could pair an old revision query with a newer document read. | Yes | Read revision and document inside one SQLite snapshot transaction. |
| A-06 | Medium | Yes | Recursive graph validation could raise `RecursionError` for a valid deep chain. | Yes | Replace recursive DFS with bounded iterative traversal and test 1,200 Tasks. |
| A-07 | Medium | Yes | Hand-built SQLite URIs failed for valid paths containing `?`. | Yes | Build the URI with `Path.as_uri()` and test URI-special path segments. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-01 | Medium | Yes | Corroborated A-03: preview's no-write claim was false because the root lock file was created. | Yes | Add complete inventory assertions around preview. |
| B-02 | High | Yes | Corroborated A-02 for released format-2 and format-3 schema-4 backups; existing legacy tests used current schema and masked the regression. | Yes | Add genuine schema-4 v2/v3 restore tests and document migration. |
| B-03 | High | Yes | SQLite rejected live-compatible 101-tag and regex-date Tasks accepted by the current JSON API. | Yes | Preserve live tag cardinality and date syntax, bounded by the existing 16 MiB durable-document limit. |
| B-04 | Medium | Yes | AC/documentation claims were premature and no exact downgrade procedure was recorded. | Yes | Record findings, correct evidence, and document the stop/backup/schema-4 restore or explicit private-state reinitialization procedure. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| A-01 | Unique correctness finding. | Reviewer A verified in Round 3. | Accepted. Task fingerprints now include all tables, indexes, autoindexes, and triggers owned by Task tables; every mutation revalidates schema. | Code and trigger regression test. |
| A-02 / B-02 | Independently corroborated. | Both reviewers verified in Round 3. | Accepted. Exact schema 4 is supported for private snapshot validation/digest/materialization; format-2/3 archives restore unchanged and migrate to schema 5 on normal open. | Compatibility code, genuine old-schema archive tests, docs. |
| A-03 / B-01 | Independently corroborated. | Both reviewers verified in Round 3. | Accepted. Preview uses the no-write pinned-root mode; exact source descriptor/state checks and import-time cross-process locking remain. | Code plus complete inventory/no-sidecar tests. |
| A-04 | Unique correctness finding. | Reviewer A verified in Round 3. | Accepted. Transaction context rolls back a failed commit. | Deferred-FK commit regression. |
| A-05 | Unique concurrency finding. | Reviewer A verified in Round 3. | Accepted. Task list/get reads use one transaction snapshot. | Deterministic two-connection regression. |
| A-06 | Unique bounds finding. | Reviewer A verified in Round 3. | Accepted. Dependency validation is iterative and remains capped at 2,048 Tasks. | 1,200-Task chain regression. |
| A-07 | Unique filesystem compatibility finding. | Reviewer A verified in Round 3. | Accepted. SQLite file URIs use escaped absolute `as_uri()` output. | `?`, `#`, and space path regression. |
| B-03 | Unique product-compatibility finding. | Reviewer B verified in Round 3. | Accepted. Repository tags now rely on the existing full-document bound, date syntax matches live behavior, and Task/JSON columns use the 16 MiB durable-document ceiling. | Round-trip and schema tests. |
| B-04 | Consequence of blocking findings. | Reviewer B verified in Round 3. | Accepted. Evidence now records Round 1 failures/fixes and architecture/data-layout docs include exact old-backup and downgrade behavior. | Review log and operator docs. |

### Reverification

- Focused tests: 168 passed after Round 2 fixes; the narrower repository,
  private-state, and backup suites passed 83 tests before the three final race
  and fingerprint regressions were added.
- Full suite: 1,139 passed, 4 platform skips on the macOS host.
- Round 2 result: both reviewers verified the Round 1 fixes but requested
  changes for the items below.

### Round 2 findings and dispositions

| ID | Severity | Blocking | Finding | Disposition |
| --- | --- | --- | --- | --- |
| R2-01 | Medium | Yes | Preview validated the open source descriptor but not the current `tasks.json` directory entry after an atomic replacement. | Fixed: no-follow `stat` of the still-pinned directory entry must match descriptor device/inode/size/mtime/link state; atomic-replacement regression added. |
| R2-02 | Medium | Yes | `replace()` committed and then called `get()`, so a later writer's revision could be returned. | Fixed: exact stored document/revision is captured inside the mutation transaction and returned after commit; deterministic later-writer regression added. |
| R2-03 | Low | No | Task schema fingerprint removed whitespace inside SQL literals. | Fixed: exact SQLite schema SQL is fingerprinted after edge trimming only; literal-collision regression added. |
| B-04-R2 | Medium | Yes | Downgrade docs incorrectly instructed the older build to restore over a live schema-5 target it cannot validate. | Fixed: schema-5-capable build now performs the schema-4 restore, is not reopened, and the pre-1C-A build is installed and started next. |
| B-05 | Low | No | Review-log documentation/publication entries were stale. | Fixed in the documentation and publication sections below. |

Round 3 uses the same two reviewers and the complete corrected diff.

### Round 3 verdicts

- Reviewer A — correctness and safety: **APPROVE**. No concrete findings
  remain; the source-replacement, exact replace-result, and schema-fingerprint
  fixes were verified, with 58 broader repository/private-backup tests passing.
- Reviewer B — compatibility and product: **APPROVE**. All blocking findings
  are resolved; live Task compatibility, released-backup recovery, executable
  downgrade ordering, package/CLI boundaries, and the absence of dual
  authority were verified. Its only note was to replace stale reviewer
  follow-up wording in this log, completed above.
- Final disposition: no unresolved blocking or non-blocking implementation
  finding remains.

### Publication CI portability follow-up

- PR #107's first Windows Python 3.11 group-8 run found two test-harness
  portability assumptions in `tests/test_task_repository.py`; production code
  was not implicated.
- The URI test used `?` in a directory name, which Windows rejects before the
  preview runs. It now combines space, `#`, and `%` on Windows while retaining
  `?` coverage on platforms where it is a valid path character.
- The atomic source-replacement race depends on POSIX replacement of an open
  file. Windows forbids that filesystem operation, so the test now records an
  explicit Windows platform skip while remaining mandatory on POSIX.
- Local repository coverage remains 24/24 passing, and the broader repository,
  private-state, and backup/restore selection passed 86 tests. Both original
  reviewers rechecked the narrow test-only follow-up and issued **APPROVE**.
- The corrected PR head passed all 51 GitHub checks: Linux, Intel macOS,
  Windows Python 3.11-3.13 shards, browser smoke, package lifecycle,
  dependency/secret gates, native artifact smoke, and aggregate required
  checks. There were no failures, cancellations, skips, or pending checks.

## Documentation updates

- Roadmap: split orchestration into 1C-A through 1C-D and record Slice 3C as
  the intended unified-database convergence.
- Changelog: complete for schema, CLI preview, backup safety, and no-cutover
  behavior.
- Architecture/operator docs: system-design reference, pivot index, exact
  schema/source-of-truth contract, released-backup compatibility, and executable
  downgrade sequence are updated.
- Project/session notes: this review log is the persistent resume record.
- Documentation verification: content and link inspection complete; both
  adversarial reviewers approved the corrected diff.

## Publication gate

- Proposed files: schema/repository/runtime CLI, private backup/restore,
  packaging inventory, focused tests, pivot/system-design/architecture/data
  documentation, changelog, contributor guide, and this review log.
- Branch and base: `codex/sqlite-orchestration-design` -> `main`.
- Commit message: `feat: add SQLite task foundation`.
- PR title: `Add SQLite task foundation and migration preview`; ready PR only,
  never draft.
- PR summary: add the schema-5 canonical Task repository, exact no-write
  migration preview, test-only atomic importer, deterministic export,
  backup/restore compatibility, focused verification, and architecture/design
  documentation without changing the live `tasks.json` authority.
- Unresolved risks: no known implementation, review, or CI blocker.
- User authorization and scope: the user gave immediate explicit approval to
  stage, commit, push, and open the ready PR on 2026-08-18.
- Initial commit hash: `a7403cb2f4ec8d6d413803c9a3e5ecb40bf7ef77`.
- CI portability follow-up commit:
  `eca685e911cc690d06f6489a5446d5f3d3d212e2`.
- Ready PR URL: `https://github.com/hazeion/agent-os/pull/107`.

## Outcome review

- Classification: Ready for user acceptance.
- Acceptance criteria summary: AC-1 through AC-9 pass. The schema/repository,
  no-write preview, test-only atomic import, deterministic export, private
  backup/restore compatibility, production JSON-authority boundary,
  documentation, package checks, local suites, browser smoke, independent
  reviews, and 51-check GitHub matrix are verified.
- Potential bugs or untested paths: the Windows platform cannot exercise the
  POSIX replace-an-open-file race; that regression remains mandatory on POSIX.
  Live Task cutover, Run/Event orchestration, high-contention load, React, and
  final Lighthouse gates intentionally remain outside Slice 1C-A.
- Remaining reviewer dissent: none; both reviewers approved the implementation
  and the CI portability correction.
- Compatibility/migration/rollback concerns: live Task authority remains
  `tasks.json`. Downgrade requires the documented schema-5-build restoration of
  an exact schema-4 backup before installing an older build; alternatively,
  private Console state may be explicitly reinitialized without removing
  durable JSON data.
- User decision: Pending.
- Next slice authorized: No
