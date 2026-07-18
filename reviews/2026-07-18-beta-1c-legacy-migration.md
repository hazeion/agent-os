# Feature Slice Review: Migrate Legacy Durable JSON

Status: Review cleared; publication authorized
Slice: `beta-1c-legacy-migration`
Date: `2026-07-18`
Review log: `reviews/2026-07-18-beta-1c-legacy-migration.md`

## Slice contract

### Goal

Let an operator explicitly migrate the nine bounded legacy repo-local JSON
documents into a selected durable data root without overwriting either side,
after an exact preview, validated pre-migration backup, confirmation, locked
revalidation, and destination verification.

### In scope

- A CLI-only preview and confirmation workflow; ordinary startup never performs
  migration silently.
- Fixed-inventory validation for the nine durable JSON documents, with current
  top-level shape and 16 MiB per-file bounds.
- An opaque confirmation token bound to the exact source, target, source bytes,
  destination state, classifications, and migration protocol version.
- A versioned, owner-only, validated pre-migration ZIP below the selected data
  root's `backups/` class, containing a secret-free manifest and exact legacy
  durable JSON bytes.
- The shared data-root mutation lock, complete re-preview under lock,
  missing-only atomic destination publication, exact verification, a fixed
  in-flight reservation, safe retry of verified partial progress, and a fixed
  completion receipt.
- Source preservation, bounded public CLI results, startup recognition of only
  an integrity-valid receipt, tests, operator documentation, and roadmap state.

### Out of scope

- Deleting or modifying the legacy source or offering cleanup.
- Schema evolution, forward-version transforms, or seed merge rules.
- General operator backup/restore, restore preview, pre-upgrade backup, or
  uninstall behavior.
- Moving Console history, SQLite/WAL/SHM, blobs, uploads, exports, snapshots,
  caches, logs, or machine-local configuration.
- A browser migration UI, installer discovery of arbitrary old checkouts, or a
  new dependency.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Preview is read-only, lists all nine source/destination actions plus the excluded runtime class, exposes no paths/content/hashes, and returns a state-bound opaque confirmation token. | Preview and resume-preview filesystem snapshots; bounded-summary/token tests | Passed |
| AC-2 | Missing/invalid/linked/oversized sources, unsafe roots, unknown legacy entries, destination conflicts, invalid receipts/reservations, and changed state fail closed before migration data is written. | Negative-path filesystem snapshots and bounded archive/control validation | Passed |
| AC-3 | Confirmation must match a fresh preview; execution re-previews under the shared lock and rejects source, target, or reservation changes. | Token mutation and under-lock source-change tests | Passed |
| AC-4 | A validated, versioned, owner-only pre-migration ZIP and manifest are durably published and verified before the first durable destination JSON. | Ordering injection, archive content/size/semantics, integrity, and mode tests | Passed |
| AC-5 | Destinations are missing-only atomic copies, exact legacy bytes are verified, source bytes/metadata remain unchanged, and no operation overwrites a raced destination. | Copy/race/source-preservation tests | Passed |
| AC-6 | A fixed reservation permits retry only when partial destinations and backup still match the original snapshot; changed partial state fails closed without claiming success. | Interruption/resume and destination/backup/reservation tamper tests | Passed |
| AC-7 | A completion receipt is written only after all destinations verify; valid receipt makes startup idempotent while invalid or incomplete migration artifacts block startup for implicit and explicit roots. | Receipt semantic-integrity and startup integration tests | Passed |
| AC-8 | CLI preview/confirm modes are explicit and mutually exclusive, remain loopback/server side-effect free, documentation is current, focused/full suites pass, and two independent reviewers clear the slice. | CLI/lifecycle/contract tests, suites, and review record | Passed |

### Constraints and recovery

- Safety: Fixed inventory only; no browser-supplied paths; no overwrite,
  source deletion, link following, package mutation, secret copying, or success
  claim after incomplete verification.
- Compatibility: macOS and Windows tier one; Linux preview; Python 3.11-3.13;
  standard library only; preserve explicit development/operator overrides.
- Recovery: Preserve the source and validated backup. A verified reservation
  may resume matching partial copies; mismatched state fails closed with bounded
  recovery guidance and requires a later reviewed reconciliation path.
- Documentation targets: `DATA_LAYOUT.md`, `ROAD_TO_BETA.md`, `ARCHITECTURE.md`,
  `README.md`, `CHANGELOG.md`, project map, CLI help contracts, and this log.
- Version-control strategy: `codex/beta-1c-legacy-migration` from merged PR 22,
  followed by a ready PR to `main` only after the publication gate.

### Scope discussion and approval

- Recommendation: Deliver the smallest complete legacy durable-JSON migration
  workflow before schema or general backup/restore work. The migration-specific
  backup is mandatory recovery evidence, not the later ordinary backup product.
- Alternatives rejected: silent startup migration; destination-wins or
  source-wins conflict resolution; deleting the source; migrating private
  runtime surfaces in the same slice; treating a general backup/restore feature
  as a prerequisite.
- User decisions: The owner approved the successful Milestone 1B outcome,
  explicitly authorized this next bounded slice, and requested uninterrupted
  progress. That authorizes implementation and review of this slice. The
  integration workflow still requires an immediate publication packet and
  explicit approval before commit, push, or PR publication.
- Approved at: 2026-07-18.

## Test strategy

| Acceptance criterion | Planned test or evidence | Important limitation |
| --- | --- | --- |
| AC-1 | Exact preview/public summary/token stability and mutation tests | CLI preview is not a browser UI. |
| AC-2 | Invalid roots/files/entries/receipts/conflicts with before/after trees | Native reparse behavior also requires hosted Windows CI. |
| AC-3 | Wrong token plus source/destination change injected before and after lock | Does not coordinate with writers that ignore Mentat's lock. |
| AC-4 | Inspect and corrupt ZIP/manifest; assert backup-verification hook precedes target copy | This is migration recovery only, not general restore. |
| AC-5 | Byte equality, metadata preservation, race injection, and repeat result | No schema transforms occur. |
| AC-6 | Fail after one publication, resume exact state, reject tampered partial/backup | Automated rollback/cleanup is intentionally deferred. |
| AC-7 | Validate receipt hashes and startup legacy suppression; corrupt receipt blocks | Receipt is local integrity/provenance, not an authentication secret. |
| AC-8 | Parser/mode ordering, lifecycle isolation, static docs, suites, two reviewers | Rendered browser QA is not applicable. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest tests.test_data_root_preflight tests.test_data_root_initializer tests.test_runtime_config tests.test_data_layout_contract -q` | macOS, system Python 3.13 | Exit 0; 56 passed, 3 native-Windows skips | Merged Milestone 1B focused baseline. |
| `python3 -m unittest discover -s tests -q` | macOS, system Python 3.13 | Exit 0; 417 passed, 3 native-Windows skips | Existing Console history permission warnings only. |
| PR 22 merge and branch creation | Git/GitHub | Pass | Squash `ebcfd60`; new branch starts from merged `main`. |

### Test discussion and approval

- User questions and decisions: The standing approval covers the mapped
  failure-path, CLI, startup, contract, and full-suite strategy.
- Accepted coverage gaps: Native Windows reparse/locking behavior requires the
  hosted Windows matrix; the slice has no browser UI, and writers that ignore
  Mentat's shared lock remain outside Mentat's coordination boundary.
- Approved at: 2026-07-18.

## Implementation record

- Added `data_migration.py` with fixed-inventory preview/result models, bounded
  no-follow/single-link source reads, an opaque exact-spelling/empty-target
  token, missing-only atomic publication, and path/content/hash-free public
  summaries.
- Added a deterministic stored ZIP with a canonical secret-free manifest,
  bounded archive and entry validation, owner/single-link/mode checks, and
  byte-for-byte recovery content.
- Added shared-lock revalidation, fixed reservation and completion documents,
  safe verified-partial resume, destination-race refusal, and receipt validation
  that binds immutable manifest/archive evidence while allowing later valid
  mutations to the live owner-only JSON documents.
- Added exact mixed-state conflict previews, dangling control/backup refusal,
  and startup detection for reservations, fixed artifacts, and exact orphaned
  migration temporaries across every data-root source. Completed receipts are
  checked under the shared lock against a pinned target-root identity.
- Integrated explicit mutually exclusive preview/confirmation CLI modes, kept
  lifecycle preflight side-effect-free for those modes, made startup reject
  incomplete/invalid migration artifacts for any selected root, and bypassed
  ordinary source-checkout legacy detection only after locked receipt validation
  confirms the pinned target identity. Completed-migration startup also creates
  or tightens every required directory boundary under that pin, rejects unsafe
  file/link/reparse boundaries, then rechecks identity and receipt integrity.
- Added migration, CLI, startup, lifecycle, contract, race, interruption,
  corruption, metadata, semantic-forgery, and documentation tests.
- Hardened project-owned atomic JSON replacement to preserve an existing
  regular file's mode and default new files to owner-only mode, so an ordinary
  post-migration Mentat mutation preserves the safe-live-file receipt boundary.
- Kept schema evolution, general backup/restore, source cleanup, and private or
  runtime data movement outside this slice.

### Deviations and decisions

- A partial legacy inventory uses the corresponding validated packaged seed for
  each absent slot and reports that source explicitly. At least one legacy
  document is required, so a clean installed layout remains initialization, not
  migration.
- Preview validation of already-published control and backup files is strictly
  read-only; it rejects unsafe ownership/link/mode state instead of repairing it.
- Publication and the post-merge outcome/next-slice decision remain separate
  immediate approval gates under the integration workflow.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_legacy_data_migration tests.test_runtime_config tests.test_local_server_lifecycle tests.test_data_root_initializer tests.test_data_root_preflight tests.test_data_layout_contract tests.test_beta_contract tests.test_ci_workflow -q` | macOS, Python 3.13 | Exit 0 | 119 run, 0 failed, 3 skipped | Native-Windows-only tests skipped as designed; argparse negative tests emit expected usage text. |
| `python3 -m compileall -q .` | macOS, Python 3.13 | Exit 0 | No errors | Includes the new migration module and modified server/config/lifecycle code. |
| `node --check public/core.js && node --check public/app.js && node --check scripts/browser_smoke.mjs` | macOS, Node 24-compatible syntax check | Exit 0 | 3 passed | No UI code changed; retained the repository CI syntax gate. |
| `git diff --check` | Git worktree | Exit 0 | No whitespace errors | Checked tracked diff before review. |
| Direct `server.py` preview and confirmation against an isolated temporary target | macOS, Python 3.13 | Exit 0; `ready` then `migrated` | Nine preview/result items | Confirmed the executable CLI path and bounded JSON output without starting the server. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13 | Exit 0 | 447 run, 0 failed, 3 skipped | Existing Console permission warnings and expected argparse usage output only. |

### Rendered or manual behavior

- Not applicable: this slice adds a CLI-only operation and no browser-rendered
  surface.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Complete uncommitted branch diff from merged `ebcfd60`,
  including untracked implementation, tests, and this review log.
- Verification evidence: 93 focused tests and 437 full-suite tests passed on the
  initial packet;
  compileall, three JavaScript syntax checks, and diff check pass.
- Rendered artifacts: Not applicable.
- Status: Both independent read-only reviews returned blocking findings.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | High | Yes | Dangling reservation/receipt links were treated as absent because `Path.exists()` preceded no-follow validation, allowing writes before the collision. | Yes | Use lexical/no-follow presence checks and add no-write dangling-control tests. |
| A-2 | High | Yes | A kill after fsync of the hidden backup temporary but before promotion left an artifact not recognized by startup, allowing ordinary initialization of the explicit target. | Yes | Recognize the exact versioned backup-temporary pattern and block startup pending recovery. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | High | Yes | Interrupted reservations/partial targets were not consistently checked for every data-root source, so startup could seed missing slots and destroy resume eligibility. | Yes | Check migration artifacts before initialization independently of CLI/environment/TOML/default source. |
| B-2 | High | Yes | Receipt validity permanently compared mutable live JSON bytes with migration-time hashes, so the first legitimate task or settings update blocked a later startup. | Yes | Bind hashes to immutable backup evidence; validate live files for safety and current shape, not historical byte identity. |
| B-3 | High | Yes | Same dangling-control root cause as A-1. | Yes | Same correction as A-1. |
| B-4 | High | Yes on initial snapshot | Snapshot read races could expose raw OS exception paths in public CLI issues. | Yes | Map failures to bounded fixed or allowlisted issue identifiers and test path secrecy. |
| B-5 | Medium | Yes | Destination conflicts collapsed to nine generic blocked items, so the principal recovery preview was not exact or actionable. | Yes | Collect all destination states and retain safe per-item `migrate`, `verify_existing`, `conflict`, or `blocked` actions. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Dangling controls/backup paths | Corroborated A-1/B-3 | No clarification required; both reproduced the same pre-write failure. | Accepted as a direct AC-2 violation. | Control reads and fixed publication checks now use lexical presence plus no-follow validation; dangling receipt/reservation/backup tests assert no writes. |
| Startup after interrupted migration | Corroborated family A-2/B-1, with A-2 identifying a distinct earlier temp window | Reviewer B maintained A-2 as a separate concrete defect in the same root-cause family. | Accepted; startup must recognize every supported persisted migration state before ordinary initialization. | Startup checks all selected root sources and exact final/control/temp artifact patterns; reservation/partial and orphaned-backup-temp tests prove no seed initialization. |
| Receipt freezes mutable operator data | Unique B-2 | Reviewer A independently maintained it as High/blocking. | Accepted; live durable JSON is expected to change after migration. | Receipt validation binds original hashes to the immutable backup/manifest while live files must remain fixed-inventory, no-follow, owner-only, bounded, valid, and correctly shaped. |
| Raw exception path disclosure | Unique B-4 | Reviewer A withdrew it against the corrected worktree after verifying fixed/allowlisted identifiers and a private-path regression test. | Accepted and resolved; no raw exception text is public. | Snapshot failures use bounded identifiers; injected absolute-path failure test passes. |
| Inexact conflict preview | Unique B-5 | Reviewer A independently maintained it as Medium/blocking. | Accepted because the approved migration contract requires every safe source, destination, conflict, and exclusion. | Preview collects all nine target states and returns safe per-item actions and allowlisted filename issues; mixed-state test covers conflict/matching/missing items. |

### Reverification after Round 1 fixes

- Focused: 116 passed, 0 failed, 3 native-Windows skips.
- Full suite: 444 passed, 0 failed, 3 native-Windows skips.
- Compileall, three JavaScript syntax checks, and `git diff --check`: pass.
- Direct executable CLI: `ready` preview followed by `migrated`, with nine
  bounded items and no server startup.
- Next review round: Round 2 required for the complete corrected slice.

### Round 2 packet

- Diff/commit reviewed: Complete corrected uncommitted diff from `ebcfd60`,
  including all Round 1 fixes, tests, documentation, and this disposition.
- Verification evidence at dispatch: 116 focused and 444 full-suite tests
  passed; compileall, JavaScript syntax, diff check, and direct CLI exercise
  passed.
- Rendered artifacts: Not applicable.
- Status: Both independent reviewers returned blocking findings. Reviewer B
  then independently maintained Reviewer A's unique file-mode finding.

| ID | Reviewer | Severity | Blocking | Finding and evidence | Resolution |
| --- | --- | --- | --- | --- | --- |
| R2-A1 | A, maintained by B | High | Yes | Ordinary `json_store.update_json()` replacements inherited the process umask instead of the migrated file's `0600` mode. A legitimate product write could become `0644`, weaken privacy, and make receipt validation reject the next startup. | Atomic JSON publication now creates the temporary with the existing regular target mode, defaulting new files to `0600`, and preserves that mode through replacement. The migration/startup integration test mutates through the real JSON store and verifies `0600`, receipt validity, and successful startup. |
| R2-A2 / R2-B2 | A and B | High | Yes | The initial migration-artifact check and ordinary initialization were separate lock transactions. A migration could become interrupted after the first check but before initialization's locked re-preview, allowing missing seeds to destroy resume eligibility. | `initialize_data_root()` accepts a bounded guard that runs after acquiring the shared pinned-root lock and before its current preflight or seed copies. Startup rechecks migration state there and fails closed. A deterministic two-thread test pauses startup after the first check, creates a supported interrupted migration, then proves startup seeds nothing. |
| R2-A3 / R2-B1 | A and B | Medium (A), High (B) | Yes | A valid receipt bypassed ordinary required-directory repair and safety validation, so missing/broad directories survived and a linked/reparse runtime class could redirect later writes. | Completed roots are validated, pinned, and all required directory classes are created or hardened under the shared lock. Startup then runs receipt-bound missing-only layout validation with implicit legacy detection disabled. Missing and broad directories recover; file and link substitutions block. |

The Round 2 packet also contained implementation-audit corrections for root
substitution pinning, exact-spelling token binding, hard-linked inputs,
preexisting destination conflicts, publication link-order verification, and
already-complete confirmation semantics. Their regression tests remain part of
the complete slice.

### Reverification after Round 2 fixes

- Targeted mode, lock-race, root-substitution, and required-directory tests:
  4 passed, 0 failed.
- Focused migration/config/lifecycle/data-root/document checks: 119 passed,
  0 failed, 3 native-Windows skips.
- Full suite: 447 passed, 0 failed, 3 native-Windows skips.
- Compileall, syntax checks for `public/core.js`, `public/app.js`, and
  `scripts/browser_smoke.mjs`, plus `git diff --check`: pass.
- Next review round: Round 3 required for the complete corrected slice.

### Round 3 packet

- Diff/commit reviewed: Complete corrected uncommitted diff from `ebcfd60`,
  including the normal JSON-writer integration and all prior dispositions.
- Verification evidence at dispatch: 119 focused and 447 full-suite tests
  passed; compileall, JavaScript syntax, and diff check passed.
- Rendered artifacts: Not applicable.
- Status: Reviewer B initially cleared the slice. Reviewer A returned two
  blocking writer/recovery findings; Reviewer B independently maintained both
  as High/blocking.

| ID | Severity | Blocking | Finding and evidence | Resolution |
| --- | --- | --- | --- | --- |
| R3-1 | High | Yes | A process interruption could leave the normal writer's exact `.<document>.json.<uuid>.tmp`; completed receipt validation rejected every top-level unknown, stranding an otherwise valid root with no supported preview recovery. | Completed-receipt validation tolerates only the exact fixed-inventory writer pattern when the entry is bounded, owner-only, single-link, and regular. Pre-migration targets, unsafe lookalikes, and unknown entries remain blocked. Startup/preview and unsafe-mode regressions cover the behavior. |
| R3-2 | High | Yes | The replacement retry block performed `path.chmod()` after `tmp.replace()`. If the replace committed and chmod raised `PermissionError`, the code retried a consumed temp and reported failure after mutation. | The temporary's effective mode is fully established before replacement; successful replacement is now the commit point with no fallible post-commit metadata step. An event-order regression proves no chmod occurs after replace and the mutation commits once. |

### Reverification after Round 3 fixes

- Focused migration/writer/config/lifecycle/data-root/document checks: 120
  passed, 0 failed, 3 native-Windows skips.
- Full suite: 448 passed, 0 failed, 3 native-Windows skips.
- Compileall, syntax checks for `public/core.js`, `public/app.js`, and
  `scripts/browser_smoke.mjs`, plus `git diff --check`: pass.
- Next review round: Round 4 required for the complete corrected slice.

### Round 4 packet

- Diff/commit reviewed: Complete corrected uncommitted diff from `ebcfd60`,
  including Round 3 writer/recovery corrections and current documentation.
- Verification evidence at dispatch: 120 focused and 448 full-suite tests
  passed; compileall, JavaScript syntax, and diff check passed.
- Rendered artifacts: Not applicable.
- Status: Each reviewer found one unique blocking gap; peer critique maintained
  both findings.

| ID | Severity | Blocking | Finding and evidence | Resolution |
| --- | --- | --- | --- | --- |
| R4-A1 | Medium | Yes | The security-sensitive completed-receipt writer-temp exception had only a positive exact-temp test and POSIX mode rejection. Exact naming, receipt gating, no-follow, owner, single-link, and size predicates lacked direct negative regressions. | Added a compact failure matrix for lookalike names, symlinks, hard links, oversized files, portable owner mismatch, and a safe exact temporary without a receipt. Each completed-root case verifies invalid receipt, blocked preview/startup, and recovery after removal. |
| R4-B1 | Low | Yes | The changelog's retained Milestone 1B safety bullet said migration remained outside "this slice," contradicting the Milestone 1C completion entry in the same section. | Scoped the historical statement explicitly to the Milestone 1B initializer and "that initializer slice." |

### Reverification after Round 4 fixes

- Focused migration/writer/config/lifecycle/data-root/document checks: 121
  passed, 0 failed, 3 native-Windows skips.
- Full suite: 449 passed, 0 failed, 3 native-Windows skips.
- Compileall, syntax checks for `public/core.js`, `public/app.js`, and
  `scripts/browser_smoke.mjs`, plus `git diff --check`: pass.
- Next review round: Round 5 required for the complete corrected slice.

### Round 5 packet

- Diff/commit reviewed: Complete corrected uncommitted diff from `ebcfd60`,
  including every prior disposition, the full writer-temp negative matrix, and
  corrected changelog language.
- Verification evidence at dispatch: 121 focused and 449 full-suite tests
  passed; compileall, JavaScript syntax, and diff check passed.
- Rendered artifacts: Not applicable.
- Reviewer A verdict: Clear, no blocking or non-blocking findings.
- Reviewer B verdict: Clear, no findings.
- Residual reviewer risk: Native Windows reparse-point, handle-pinning,
  no-delete-sharing/locking, ACL, and atomic-replacement behavior remains for
  the hosted Windows publication gate; three platform-specific tests skip on
  macOS.
- Status: Cleared by both independent reviewers with no dissent.

## Documentation updates

- Roadmap: Marks only Milestone 1C complete and advances the next bounded work to
  schema evolution; Milestone 1 remains in progress.
- Changelog: Records the operator-visible migration workflow and fail-closed
  boundaries.
- Architecture/operator docs: Updates `DATA_LAYOUT.md`, `ARCHITECTURE.md`, and
  `README.md` with the implemented behavior, CLI use, recovery, and exclusions.
- Project/session notes: This persistent log is the project review record; no
  private operator note is required.
- Documentation verification: Data-layout, beta-contract, and CI-contract tests
  pass in the focused and full suites.

## Publication gate

- Proposed files: `data_migration.py`, `data_layout.py`, `json_store.py`,
  `runtime_config.py`, `server.py`, `mentat_lifecycle.py`,
  `tests/test_json_store.py`, `tests/test_legacy_data_migration.py`,
  `tests/test_runtime_config.py`, `tests/test_local_server_lifecycle.py`,
  `tests/test_data_layout_contract.py`, `tests/test_beta_contract.py`,
  `tests/test_ci_workflow.py`, `DATA_LAYOUT.md`, `ARCHITECTURE.md`, `README.md`,
  `ROAD_TO_BETA.md`, `CHANGELOG.md`, and this review log.
- Branch and base: `codex/beta-1c-legacy-migration` to `main`.
- Commit message: `Migrate legacy durable data safely`.
- PR title: `Add previewed legacy data migration`.
- PR summary: Add explicit backed-up legacy durable-JSON migration with locked
  confirmation, verified interruption resume, startup receipt validation, and
  complete safety/contract coverage while deferring schema/general restore work.
- Unresolved risks: Hosted cross-platform CI is pending; no known local or
  reviewer finding remains.
- User authorization: Standing approval granted to publish, merge, and continue
  after each clean slice without another pause.
- Commit: This review log is part of the publication commit; use Git history
  for its immutable hash.
- Ready PR URL: Recorded in the GitHub publication result after push.

## Outcome review

- Classification: Successful locally; publication/hosted CI pending.
- Acceptance criteria summary: AC-1 through AC-8 passed locally.
- Remaining reviewer dissent: None.
- User decision: Standing approval authorizes publication, merge after green
  required checks, and immediate progression to the next bounded slice.
- Next slice authorized: Yes, after this slice publishes and merges cleanly.
