# Feature Slice Review: Back Up and Restore Durable Operator JSON

Status: Final local verification and two zero-finding reviews complete; hosted CI correction awaiting publication and rerun
Slice: `beta-1e-durable-backup-restore`
Date: `2026-07-18`
Review log: `reviews/2026-07-18-beta-1e-durable-backup-restore.md`

## Slice contract

### Goal

Let an operator create a validated, versioned snapshot of Mentat's nine
schema-governed durable JSON documents and restore that snapshot into an
initialized compatible data root through an exact preview-and-confirm flow,
without changing current schema provenance or any excluded storage class.

### In scope

- One fixed version-1 general-backup ZIP format for the nine durable operator
  JSON documents, with bounded manifest, classifications, schema versions,
  integrity metadata, and explicit exclusions.
- Owner-only, missing-only, validated backup publication below the selected
  data root's `backups/` directory while the shared pinned-root mutation lock
  prevents ordinary JSON writes from crossing the snapshot.
- A read-only restore preview for an explicitly selected safe backup file,
  including forward-format/schema refusal, exact replace/unchanged actions,
  conflict reporting, and an opaque confirmation token bound to the archive,
  target root, and exact live documents.
- Confirmed restore with locked revalidation, a validated pre-restore recovery
  backup, owner-only staging, per-document atomic replacement, exact terminal
  verification, and interruption-safe reservation/resume.
- Startup refusal while restore state is incomplete or invalid.
- Explicit server CLI operations for creating a backup, previewing a restore,
  and confirming the exact restore token, plus operator and architecture docs.

### Out of scope

- Capturing or restoring Console history, SQLite metadata, referenced blobs,
  credentials, or future remote-connection state. The Console consistency unit
  remains a mandatory follow-up after the approved private-state move so it is
  implemented once at its durable location rather than duplicated in legacy
  `runtime/` storage.
- Runtime scratch, caches, logs, browser state, existing backups, migration
  receipts, schema-bootstrap archives, Hermes/Obsidian/Google data, arbitrary
  files, secrets, or unsupported installed-app configuration.
- A browser backup UI, scheduling, encryption, cloud destinations, pruning,
  general archive extraction, private SQLite schema evolution, installer or
  uninstall behavior, or the later unified `mentat backup/restore` entrypoint.
- Restoring into an uninitialized, legacy, invalid, or newer-schema target.
  Clean-install recovery initializes the compatible root first, then restores.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Backup creates one bounded owner-only versioned ZIP containing exactly the fixed nine documents plus a canonical manifest, and names every included/excluded class without paths, secrets, recursive backups, or private/runtime bytes. | Archive, manifest, privacy, and inventory tests | Local and review verified |
| AC-2 | Backup validates the current schema and exact fixed documents under the shared pinned-root lock, publishes missing-only with exact read-back verification, leaves operator source bytes unchanged, and cannot race an ordinary JSON mutation. | Lock/order, source snapshot, collision, and tamper tests | Local and review verified |
| AC-3 | Restore preview is read-only and bounded, validates the exact archive shape and integrity, reports deterministic replace/unchanged actions, and distinctly refuses malformed, linked, oversized, unsupported-format, or newer-schema backups. | Preview filesystem snapshot and negative archive tests | Local and review verified |
| AC-4 | The opaque confirmation token binds the exact archive bytes, safe archive identity, exact target spelling/identity, current schema, live document bytes, ordered actions, and protocol; any state change requires a new preview. | Token, substitution, archive-change, target-change, and stale-preview tests | Local and review verified |
| AC-5 | Confirmation publishes and validates an owner-only pre-restore recovery backup before the first live replacement, then uses only owner-only verified staging and atomic per-document commits beneath the shared pinned-root lock. | Ordering, mode, staging, and injected-failure tests | Local and review verified |
| AC-6 | A matching interrupted restore can resume only when its reservation, selected/internal source evidence, recovery backup, and every live document exactly match an allowed old-or-new state; conflicts fail closed without overwriting unknown bytes. | Interruption matrix, resume, conflict, and recovery-evidence tests | Local and review verified |
| AC-7 | Success requires exact post-restore schema/integrity verification while preserving schema metadata/evidence and all excluded directories/files; startup and already-running JSON access block incomplete or invalid restore state before ordinary writes. | Terminal verification, exclusion preservation, lifecycle ordering, and live-server lock tests | Local and review verified |
| AC-8 | CLI contracts, documentation, local focused/full checks, the supported nine-job hosted matrix, and two independent adversarial reviews all clear on the final diff. | CLI/docs/CI suites and this review record | Final local/review checks passed; hosted correction pending rerun |

### Constraints and recovery

- Safety: fixed inventory, exact supported JSON types and sizes, owner-only
  regular single-link files, no-follow opens, no overwrite of backup artifacts,
  no archive path extraction, no absolute/private paths in persisted metadata
  or public output, and fail-closed behavior after any unverified mutation.
- Compatibility: Python 3.11-3.13; macOS and Windows tier one; Linux preview;
  loopback-only runtime unchanged; existing data-schema and legacy-migration
  evidence remains valid and untouched.
- Rendered behavior: Not applicable; this slice has no browser-visible UI.
- Rollback or recovery: a verified pre-restore recovery archive is durable
  before the first replacement. Exact recognized interruption state resumes;
  changed or ambiguous state blocks startup and further restore mutation.
- Documentation targets: `DATA_LAYOUT.md`, `ARCHITECTURE.md`, `README.md`,
  `ROAD_TO_BETA.md`, `CHANGELOG.md`, and this log.
- Version-control strategy: branch `codex/beta-1e-backup-restore` from merged
  `main`; one ready PR to `main` only after zero-finding review and clean local
  and hosted verification.

### Scope discussion and approval

- Recommendation and rationale: implement the schema-governed durable operator
  set first. It is already fixed, bounded, versioned, and protected by one
  cross-process lock, so it can deliver a real backup/restore workflow without
  copying the private Console unit from the legacy location that the next
  Milestone 1 slice must replace.
- Alternatives considered: capturing current `runtime/` Console storage now
  would duplicate its SQLite/history/blob move and restore logic; directory-root
  swapping would broaden authority over runtime and private state; restoring
  schema-bootstrap archives would recurse backup evidence unnecessarily;
  delaying all restore work until packaging would leave the current data gap
  open.
- User decisions: the user's standing instruction requires the recommended
  bounded roadmap slice, review fixes through zero findings, publication,
  merge, and immediate continuation. This is a recorded process exception to
  the skill's per-phase pause and repeated publication-approval prompts; all
  technical, evidence, review, and CI gates remain mandatory.
- Approved at: `2026-07-18`, by standing user authorization in this thread.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No general backup format or command exists. | Fixed-entry archive and public-summary tests. | Inventory, privacy, bounds, and stable version metadata. | Private Console inclusion is deliberately deferred and explicitly reported. |
| AC-2 | Current schema backups are migration-specific only. | Source immutability, shared-lock concurrency, missing-only publication, and tamper tests. | Snapshot consistency and non-overwrite publication. | Does not exercise future arbitrary export destinations. |
| AC-3 | No restore preview exists. | Read-only preview snapshots plus malformed/unsupported archive matrix. | Safe parsing, forward refusal, and no preview writes. | Fuzzing is bounded to representative structural/resource cases. |
| AC-4 | No general restore confirmation exists. | State/identity/token mutation matrix. | Exact authorization and stale-confirmation refusal. | Platform-specific handle semantics also rely on hosted CI. |
| AC-5 | No pre-restore recovery checkpoint exists. | Injected failures at publication/staging/first-commit boundaries. | Recovery-before-mutation and atomic-file ordering. | Multi-file atomicity is delivered through reservation/resume, not a filesystem-wide transaction. |
| AC-6 | Interrupted general restore has no recovery state machine. | Old/new/mixed/unknown document matrices and evidence tamper cases. | Only exact recognized partial state can continue. | Power-loss durability is simulated around explicit fsync boundaries. |
| AC-7 | Startup has no restore-state gate. | Lifecycle/preflight ordering and exclusion-preservation tests. | Incomplete work blocks before ordinary writes; excluded state survives. | No browser behavior. |
| AC-8 | CLI/docs/CI have no backup/restore coverage. | Parser/CLI contract tests, full suite, compile/syntax/diff checks, hosted matrix, two reviewers. | Operability and supported-platform regression coverage. | Native installer CLI remains Milestone 3. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS, Python 3.13 | Pass | 514 tests; four platform-specific skips before this slice. |
| `python3 -m compileall -q .` and three `node --check` commands | macOS | Pass | Inherited clean final gate from merged Milestone 1D. |
| Search for a general backup/restore module or CLI | Repository | Gap confirmed | Only migration/schema-specific backups exist. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts the recommended
  smallest slice and requires immediate progress; no new browser surface or
  private-state authority is inferred.
- Accepted coverage gaps: private Console consistency, arbitrary export
  destinations, installer/unified CLI, real power interruption, and native
  signing remain separate roadmap gates.
- Approved at: `2026-07-18`, by standing user authorization in this thread.

## Implementation record

### Changes

- Added `data_backup_restore.py` with a deterministic, fixed-entry version-1
  archive, bounded no-follow validation, read-only restore preview, exact
  confirmation binding, pre-restore source/recovery evidence, durable
  reservation, interruption resume, and exact terminal verification.
- Added exact-byte validated atomic JSON replacement to `json_store.py` so a
  restore preserves the archive's verified document bytes.
- Added mutually exclusive backup/restore CLI modes and routed them before
  normal startup and lifecycle-server handling.
- Added startup and already-running-server restore gates. Dashboard JSON reads
  and writes take the shared cross-process root lock and refuse active or
  invalid restore artifacts, including a request that was already waiting when
  a restore failed.
- Added archive, privacy, forward-version, stale-confirmation, interruption,
  conflict, recovery-ordering, CLI, server-process, exact-byte, and contract
  regressions. The source-checkout coordination lock is ignored as local
  runtime state.
- Hardened the reviewed failure boundaries with descriptor-relative artifact
  classification, locked startup rechecks, recovery cleanup tokens bound to the
  selected archive/live plan, pre-`ZipFile` central-directory bounds, discarded
  decoded JSON trees, exact canonical reservation verification, and conservative
  partial-failure reporting after any restore mutation attempt.
- Corrected the Windows native-directory-pin inventory contract after the first
  hosted run. The presence-aware helper now distinguishes an absent child from
  a native pinned directory whose POSIX descriptor representation is `None`,
  refuses an appeared child without enumerating it, rejects unsafe native
  metadata, and inventories broad POSIX directories only through their pinned
  descriptor so startup permission repair remains compatible.

### Deviations and decisions

- The approved 1E-A boundary covers only the nine fixed schema-governed JSON
  documents. Private Console history/SQLite/referenced blobs remain explicitly
  excluded until their next-slice durable move can define one WAL-safe
  consistency unit.
- The server now retains the cross-process coordination lock even in the
  source-development override. Lower-level JSON helpers preserve their prior
  no-disk-lock test mode; this is the minimum change that prevents a live
  server from crossing an external restore.

## Verification

### Focused checks

- `python3 -m unittest tests.test_data_backup_restore tests.test_json_store tests.test_runtime_config tests.test_beta_contract tests.test_ci_workflow tests.test_data_layout_contract -q`
  passed: 85 tests on the final hosted-CI correction diff.
- `python3 -m compileall -q .`, `node --check public/core.js`,
  `node --check public/app.js`, and `git diff --check` passed.
- One diagnostic static-check command named a nonexistent historical
  `public/agent-console.js`; the repository's complete two-file JavaScript
  inventory was then enumerated with `rg --files public -g '*.js'` and both
  actual files passed syntax checks. This was a command correction, not a
  product failure.

### Full suite

- `python3 -m unittest discover -s tests -q` passed: 543 tests, four
  platform-specific skips, on the final hosted-CI correction diff using local
  macOS/Python 3.13.

### Hosted matrix

- Initial run [29659230543](https://github.com/hazeion/agent-os/actions/runs/29659230543)
  passed all Python 3.11-3.13 jobs on Ubuntu and macOS and failed all three
  Windows jobs. The shared failure was isolated to restore inventory treating
  the Windows native pin's intentional `descriptor=None` as a missing child;
  one concurrency test also attempted to read the live byte-range-locked root
  coordination file.
- The correction is locally verified and reviewed below. A fresh complete
  nine-job run is required after publication; no partial rerun is accepted as
  final evidence.

### Rendered or manual behavior

- Not applicable.

## Adversarial review

### Round 1

- Safety reviewer: five findings — unlocked startup restore race (high),
  confirmation artifact-window race (high), post-reservation failure
  misclassification (medium), pathname backup artifact inspection (medium),
  and recovery-preview error exit (low).
- Compatibility reviewer: four findings — the same startup race (high),
  under-bound recovery cleanup token (medium), ZIP central-directory allocation
  before entry-count rejection (high), and retained decoded JSON memory
  amplification (high).
- Peer critique: each reviewer independently inspected the other reviewer's
  unique findings. Both agreed the artifact-window, failure-status, pinned
  inspection, CLI, ZIP, and decoded-tree findings were actionable. The safety
  reviewer classified archive/live recovery binding as contract exactness rather
  than deletion safety; the stricter binding was implemented because AC-4
  promises any displayed input/action change requires a new preview.
- Additional self-review fix: completion now requires the reservation's exact
  canonical bytes before deletion, rather than semantic JSON equality.
- Resolution: all unique findings were fixed. Ten focused regressions cover the
  synchronized startup and confirmation windows, pinned child substitution,
  post-publication failure status, stale recovery inputs, bounded ZIP preflight,
  discarded decoded trees, exact reservation bytes, evidence tamper, backup
  collision, and real CLI recovery exit behavior. The revised focused and full
  suites pass locally.

### Round 2

- Safety reviewer: zero findings; every prior safety and peer-critiqued finding
  was resolved and the 79-test revision passed its focused gate.
- Compatibility reviewer: one medium blocking finding. Recovery cleanup bound
  the archive, live documents, actions, and temporary but not exact simultaneous
  `restore-state-v1.json` presence, so state appearance/removal could let a stale
  confirmation unlink the temporary before detecting the changed inventory.
- Resolution: the recovery token now includes exact state absence or
  owner-only state byte/identity/link evidence, revalidated both during preview
  stabilization and under the pinned confirmation lock. A two-direction
  regression proves state appearance and state removal both preserve the
  temporary and require a new preview. The 80-test focused set and 538-test full
  suite pass.

### Round 3

- Both reviewers reported the same medium blocking adjacent-check gap: exact
  restore-state evidence was token-checked before several artifact reads, but a
  non-cooperating local filesystem actor could still alter it immediately before
  the temporary unlink.
- The compatibility reviewer also found that an exactly previewed backup
  temporary plus a stable restore reservation cleaned the temporary but then
  incorrectly reported partial failure because the expected remaining artifact
  class did not account for the bound state.
- Resolution: state evidence is re-read adjacent to the unlink, alongside the
  artifact's adjacent identity checks. The post-cleanup expected class derives
  from bound state presence, so an authorized cleanup returns `recovered` while
  preserving the reservation and requiring its next preview. Hooked appearance
  and removal races preserve the temporary; a stable state-plus-backup-temp
  regression succeeds. The 82-test focused set and 540-test full suite pass.

### Round 4

- Safety reviewer: zero findings; both cleanup-edge fixes and regressions were
  sound.
- Compatibility reviewer: production fixes sound, but one high blocking hosted-
  CI test defect. The adjacent-state hook identified confirmation with
  `root_descriptor is not None`; Windows intentionally uses native handle guards
  while exposing `None`, so the mutation would not fire and all Windows jobs
  would fail.
- Resolution: the test now stubs the already-captured preview and counts the two
  confirmation evidence reads directly, independent of descriptor representation.
  Both appearance/removal cases pass locally, followed by the 82-test focused
  set, 540-test full suite, and static gates.

### Round 5

- Safety reviewer: zero findings. The corrected platform-neutral hook still
  exercises both adjacent state transitions and introduced no production or
  review-record regression.
- Compatibility reviewer: zero findings. The Windows test defect is resolved;
  all production cleanup, startup, resource, CLI, documentation, and verification
  fixes remain consistent.
- Review gate: complete with two independent zero-finding reports on the same
  pre-publication diff.

### Hosted-CI correction rounds

- The first correction made descriptor-`None` inventory list the native-pinned
  Windows pathname and excluded the active lock from test snapshots. Safety
  initially reported zero findings. Compatibility found two blocking edges:
  absent-then-appeared children could be pathname-enumerated, and the snapshot
  filter excluded same-named nested files rather than only the root lock.
- Resolution: `data_schema.py` now exposes a presence-aware pinned-child
  context while preserving the existing wrapper API. Restore inventory fails
  closed when an absent child appears, never enumerates unsafe native metadata,
  and the snapshot excludes only the exact root coordination file. Regressions
  force native pinned presence with no POSIX descriptor and prove an appeared
  child is never listed.
- On re-review, compatibility reported zero findings. Safety then found one
  high blocking interaction: skipping all unsafe-directory enumeration could
  hide restore state in a broad POSIX config directory because artifact-free
  broad directories must remain repairable at startup.
- Resolution: unsafe native/pathname metadata still fails immediately; POSIX
  broad directories are enumerated only via their already-pinned descriptor.
  A regression proves hidden restore state is classified invalid and every
  config inventory read used a descriptor, while the existing startup test
  proves artifact-free broad directories are still hardened successfully.
- Safety final re-review: zero findings. Compatibility found only that this
  review record still contained the pre-correction test totals; the exact final
  commands were rerun and are recorded above (85 focused, 543 full, all static
  gates clean). Both reviewers then audited this final record and reported zero
  findings on the same publication diff.

## Documentation updates

- `DATA_LAYOUT.md` defines the implemented archive, exclusion, restore,
  recovery, live-server coordination, and current CLI contract.
- `ARCHITECTURE.md` records the fixed JSON boundary and restore-state safety
  invariant.
- `README.md` adds operator commands and names the deferred private-state
  consistency unit.
- `ROAD_TO_BETA.md` and `CHANGELOG.md` record 1E-A completion while keeping
  Milestone 1 and the complete beta gate open.

## Publication gate

- Proposed files: `.gitignore`, `data_backup_restore.py`, `data_schema.py`, `json_store.py`,
  `runtime_config.py`, `server.py`, `mentat_lifecycle.py`, the focused tests,
  the five operator/architecture records, and this review log.
- Branch and base: `codex/beta-1e-backup-restore` to `main`.
- Commit message: `Back up and restore durable operator data`.
- PR title: `Add durable data backup and restore`.
- PR summary: Fixed-inventory durable JSON backup and exact confirmed restore,
  including interruption recovery, startup/live-server coordination, operator
  documentation, and supported-platform regressions.
- Unresolved risks: None accepted; private Console inclusion is an explicit
  follow-up, not represented as complete.
- User authorization and scope: Standing approval recorded; publication still
  requires clean verification and two zero-finding reviews.
- Implementation commit: `8c69370`.
- Hosted-CI correction commit: Pending.
- Ready PR URL: https://github.com/hazeion/agent-os/pull/25

## Outcome review

- Classification: In progress.
- Acceptance criteria summary: Pending.
- Potential bugs or untested paths: Pending review.
- Remaining reviewer dissent: Pending.
- Compatibility/migration/rollback concerns: Pending.
- User decision: Standing authorization recorded.
- Next slice authorized: Yes after this slice merges cleanly.
