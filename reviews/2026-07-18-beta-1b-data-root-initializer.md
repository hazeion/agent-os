# Feature Slice Review: Initialize the Platform Data Root

Status: Successful
Slice: `beta-1b-data-root-initializer`
Date: `2026-07-18`
Review log: `reviews/2026-07-18-beta-1b-data-root-initializer.md`

## Slice contract

### Goal

Let a clean installed Mentat startup safely create its platform data layout and
copy each immutable packaged seed exactly once, without overwriting operator or
legacy data.

### In scope

- Standard-library, lock-protected execution of the approved read-only
  preflight plan with revalidation after the initialization lock is held.
- Owner-only creation and read-back verification of the data root plus the
  `private`, `runtime`, `backups`, `cache`, `logs`, and `config` directory
  classes where the platform supports POSIX permission modes.
- Bounded, no-follow packaged-seed reads and same-directory temporary copies
  promoted without replacement only when a known destination is missing.
- Idempotent repeat startup, safe continuation after a partial interruption,
  bounded public results, and config-less lifecycle/direct-server startup
  integration.
- Legacy checkout detection before seed copying; migration-required, conflict,
  unsafe, and stale/raced states fail closed.
- Milestone records, operator documentation, and the completed 1B-A outcome.

### Out of scope

- Legacy migration execution or deletion of any legacy source.
- Schema evolution, seed merging, backup/restore, upgrade, uninstall, or
  installer implementation.
- Moving the current Console private/runtime surfaces into the new directory
  classes.
- Remote Hermes credentials, UI changes, or a new third-party dependency.
- Cleaning abandoned initialization temporary files; this slice only makes
  them recognizable and harmless to repeat initialization.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A clean target creates the approved directory classes and copies all nine validated seeds; POSIX roots/directories are `0700` and seed/lock files are `0600`. | Temporary-filesystem integration and mode tests | Passed locally |
| AC-2 | Existing valid seed destinations are never overwritten, missing destinations alone are initialized, and repeat initialization is idempotent. | Sentinel-content, mixed-state, and repeat-run tests | Passed locally |
| AC-3 | Initialization holds a cross-process lock, reruns preflight under that lock, and atomically promotes a same-directory copy without replacing a raced destination. | Lock/revalidation and destination-race tests | Passed locally |
| AC-4 | Legacy, conflict, unsafe, symlink/reparse, invalid seed/target, and permission-verification failures stop before any seed copy and return bounded errors. | Negative-path and filesystem snapshot tests | Passed locally |
| AC-5 | A failure or interruption leaves prior valid destinations intact and any temporary copy distinctly named; the next run can safely complete missing seeds. | Injected failure/interruption and recovery tests | Passed locally |
| AC-6 | Development override remains a no-op, while config-less lifecycle and direct server startup initialize before ordinary runtime writes; print-config stays side-effect-free. | Lifecycle/server integration and source-checkout compatibility tests | Passed locally |
| AC-7 | Documentation accurately closes Milestone 1B, leaves migration/backup/restore pending, focused/full tests pass, and two independent reviewers clear the slice. | Contract tests, suites, and review record | Passed |

### Constraints and recovery

- Safety: Never follow links/reparse points, scan arbitrary names, overwrite an
  existing destination, return file contents, or copy while legacy/conflict or
  unsafe state is present.
- Compatibility: macOS and Windows tier one; Linux preview; Python 3.11-3.13;
  source checkout keeps `data_dir = "data"`; no dependency added.
- Rendered behavior: Not applicable; no browser-visible surface changes.
- Rollback or recovery: Revert the initializer/startup integration. Valid seed
  files already created are public-safe initial defaults and may remain; an
  interrupted temporary file is ignored by the fixed inventory and can be
  removed only by a later bounded reconciliation workflow.
- Documentation targets: `DATA_LAYOUT.md`, `ROAD_TO_BETA.md`, `README.md`,
  `CHANGELOG.md`, the 1B-A review log, and this review log.
- Version-control strategy: `codex/beta-1b-data-root-initializer` from merged
  `main`, followed by a ready PR to `main` only after the publication gate.

### Scope discussion and approval

- Recommendation and rationale: Complete Milestone 1B with the smallest
  writable step needed for a clean installed start, while keeping user-data
  migration and backup/restore as independently reviewable mutations.
- Alternatives considered: Combine initialization with migration (rejected as
  a larger data-loss boundary); direct writes to final names (rejected because
  interruption exposes partial JSON); overwrite-on-rename (rejected because a
  raced operator file must win); add `platformdirs` or a lock dependency
  (unnecessary for this bounded standard-library slice).
- User decisions: On 2026-07-18 the owner requested completion of Milestone 1B,
  approved all implementation/review steps in advance, and asked not to pause
  for intermediate confirmations. This is recorded as a process exception for
  scope and test-strategy prompts; it does not authorize staging, commit, push,
  or PR publication before the required final publication packet.
- Approved at: 2026-07-18.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Preflight is read-only and platform-default startup is blocked. | Clean-root copy, inventory, byte equality, class-directory, and POSIX mode tests. | Required layout and seeds are created with bounded permissions. | Native Windows ACL equivalence cannot be proven by POSIX mode bits. |
| AC-2 | No write executor exists. | Existing sentinel, mixed existing/missing, and before/after repeat-run assertions. | Missing-only semantics and idempotence. | Does not define future schema merges. |
| AC-3 | Preflight results can become stale. | Mocked revalidation, concurrent lock serialization, and destination-appears-before-promotion tests. | Mutations use fresh state and fail closed instead of replacing data. | Does not coordinate with non-Mentat writers that ignore the lock. |
| AC-4 | Unsafe plans are only reported, not executed. | Legacy/conflict/link/invalid/permission failures with destination snapshots. | Rejected states create no seed destinations. | Native reparse and ACL behavior also depends on hosted CI. |
| AC-5 | No interruption behavior exists. | Inject copy failure after one file and retain a named temporary copy, then retry. | Partial valid progress is recoverable and temporary state is distinguishable. | Automated stale-temp deletion remains deferred. |
| AC-6 | Config-less startup intentionally exits. | Lifecycle and direct-start helper tests plus print-config/source override regressions. | Initializer is ordered before ordinary runtime writes without changing development. | Does not launch a browser or long-running HTTP server. |
| AC-7 | Docs describe 1B-B as future work. | Contract assertions, focused/full suites, diff check, hosted CI after publication, two reviews. | Records and gates match delivered behavior. | Rendered verification is not applicable. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest tests.test_data_root_preflight tests.test_runtime_config tests.test_data_layout_contract tests.test_local_server_lifecycle -v` | macOS, system Python 3 | Pass (exit 0) | 51 passed; confirms the read-only 1B-A baseline. |
| `python3 -m unittest discover -s tests -q` | macOS, system Python 3 | Pass (exit 0) | 395 passed; existing history-permission warnings only. |
| Repository and merged PR inspection | clean merged `main` | Pass | PR 21 merged with all nine macOS/Windows/Ubuntu Python 3.11-3.13 CI jobs green. |

### Test discussion and approval

- User questions and decisions: The owner approved all steps ahead of time and
  explicitly requested no intermediate approval prompts. The strategy preserves
  the documented one-slice boundary and all mandatory safety/review gates.
- Accepted coverage gaps: Native Windows ACL exclusivity, simulated process
  crash timing, and hosted matrix execution are not locally provable; Windows
  behavior is covered by portable failure checks and later hosted CI.
- Approved at: 2026-07-18.

## Implementation record

### Changes

- Extended `data_layout.py` with bounded initialization results, verified
  directory/file modes, POSIX no-follow descriptor walking, a persistent OS
  file lock, validated byte-preserving seed reads, synced unique temporary
  copies, atomic hard-link no-replace promotion, and final revalidation.
- Added startup preparation in `runtime_config.py`; clean installed roots
  initialize before lifecycle cleanup or server runtime writes, source
  development layout remains a no-op, and source-checkout platform selection
  reserves repo-local data for migration.
- Replaced the former platform-default startup block in both lifecycle and
  direct-server entry points with the bounded initializer result.
- Added focused initializer/startup tests, including two spawned processes,
  a raced destination, partial failure recovery, stale interruption state,
  permissions, legacy/conflict refusal, and print-only ordering.
- Updated the canonical data contract, architecture, README, roadmap,
  changelog, static contract tests, and the merged 1B-A outcome record.

### Deviations and decisions

- The user's advance approval is treated as explicit scope and test-strategy
  approval. Publication remains separately gated by repository and skill rules.
- The first concurrent test exposed a transient `ENOENT` while two fresh
  processes simultaneously established the new root and opened its lock. Lock
  acquisition now retries that narrow pre-lock race up to three times; 30
  consecutive spawned-process repetitions then passed.
- Windows uses its standard user-profile ACL inheritance and the portable file
  lock; exact POSIX `0700`/`0600` verification applies only on POSIX. No private
  content or credential is moved/written by this slice. A later secret-bearing
  capability must add and verify the approved native Windows private ACL
  boundary before writing secrets.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| Initial pre-review focused command | macOS, system Python 3.13 | Exit 0 | 74 passed, 0 failed/skipped | First-run, repeat, legacy/conflict, race, interruption, lifecycle, and docs contract coverage. |
| `for run_id in {1..30}; do python3 -m unittest tests.test_data_root_initializer.DataRootInitializerTests.test_two_processes_serialize_and_leave_one_complete_layout -q || break; done` | macOS, spawned Python processes | Exit 0 | 30 repetitions passed | Stress evidence after bounded lock-open retry. |
| `python3 -m py_compile data_layout.py runtime_config.py server.py mentat_lifecycle.py` | macOS, system Python 3.13 | Exit 0 | 4 modules compiled | Syntax gate. |
| `git diff --check` | Git worktree | Exit 0 | No whitespace errors | Static diff gate. |
| Post-review focused command including CI contract | macOS, system Python 3.13 | Exit 0 | 84 passed, 0 failed, 1 Windows-native test skipped | Adds bidirectional overlap, hard-link confinement, extended Windows lock retry, startup overlap, and native root-pinning coverage. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| First post-implementation full run | macOS, system Python 3.13 | Exit 1 | 406 passed, 2 failed | One stale roadmap assertion and one transient concurrent lock-open race; both corrected. |
| Post-review `python3 -m unittest discover -s tests -q` | macOS, system Python 3.13 | Exit 0 | 412 passed, 0 failed, 1 Windows-native test skipped | Existing history-permission warnings only. |
| Post-Round-2 `python3 -m unittest discover -s tests -q` | macOS, system Python 3.13 | Exit 0 | 413 passed, 0 failed, 1 Windows-native test skipped | Adds native macOS case-insensitive containment coverage. |
| Post-Round-3 `python3 -m unittest discover -s tests -q` | macOS, system Python 3.13 | Exit 0 | 416 passed, 0 failed, 1 Windows-native test skipped | Adds native and portable Darwin case/Unicode alias coverage. Existing history-permission warnings only. |
| Post-Round-4 `python3 -m unittest discover -s tests -q` | macOS, system Python 3.13 | Exit 0 | 417 passed, 0 failed, 2 Windows-native tests skipped | Adds portable aliased-ancestor coverage and native Windows seed-root/short-name guards. Existing history-permission warnings only. |

### Rendered or manual behavior

- Not applicable.

## Adversarial review

### Round 1 packet

- Diff reviewed: Complete uncommitted implementation, tests, documentation,
  and both untracked slice files against `origin/main`.
- Verification evidence: 74 focused tests, 408 full tests, compilation, diff
  check, and 30 consecutive two-process stress repetitions.
- Rendered artifacts: Not applicable.

### Reviewer A — correctness and safety

- A-1 (P0, blocking): A pre-existing hard-linked initialization lock was
  accepted and `fchmod` changed an unrelated outside inode; Windows could also
  write the lock byte to it.
- A-2 (P0, blocking): Windows path-based fallback did not pin the root, so a
  junction substitution between inspection and mutation could redirect lock or
  seed writes outside the selected root.

### Reviewer B — compatibility and product

- B-1 (P1 proposed, blocking; reconciled to P2): Only exact seed/target equality
  was special-cased, so an ancestor or descendant target could dirty the
  package or checkout.
- B-2 (P2 proposed, blocking; reconciled to P0): Independently reproduced the
  hard-linked lock mutation.
- B-3 (P2, blocking): Windows `LK_LOCK` stops after its short CRT retry window,
  so long initialization could make a second startup fail instead of serialize.
- B-4 (P3, nonblocking): The review log's gate text still said implementation
  was pending after implementation and local verification had completed.

### Reconciliation and disposition

- Both reviewers maintained the hard-link finding and agreed the roadmap's
  explicit unsafe-mutation definition makes it P0. Accepted: lock/temp
  descriptors must be single-link and current-owner on POSIX before chmod or
  lock-byte writes; an outside-inode regression proves bytes and mode unchanged.
- Reviewer A accepted B-1 as P2 blocking because a disjoint override is a
  workaround. Accepted: preflight now rejects both overlap directions, while
  exact seed-root equality remains the development no-op; initializer and
  startup tests cover both.
- Reviewer B accepted A-2 as P0 blocking. Accepted: Windows now pins every
  existing root component with non-delete-sharing, no-reparse handles and opens
  lock/temp final components with `FILE_FLAG_OPEN_REPARSE_POINT`. A native
  Windows test attempts root replacement at both writes and requires the guard
  to block it.
- Reviewer A accepted B-3 as P2 blocking. Accepted: Windows uses nonblocking
  lock attempts under an explicit 120-second deadline; a portable regression
  exceeds the CRT's ten-attempt behavior.
- Both reviewers accepted B-4 as P3 nonblocking. This log now states the actual
  review/reconciliation gate.

### Reverification

- Focused tests: 84 passed, 0 failed, 1 native-Windows test skipped on macOS.
- Full suite: 412 passed, 0 failed, 1 native-Windows test skipped on macOS.
- Compilation and diff check: Passed.
- Next review round: Both reviewers receive the complete refreshed diff and
  evidence; native Windows execution remains a hosted-CI publication gate.

### Round 2

- Reviewer A reported no findings and confirmed all Round 1 findings resolved.
- Reviewer B found one new P2 blocker: lexical POSIX containment remained
  case-sensitive on default case-insensitive macOS filesystems, so `Seeds` and
  `seeds/operator` could bypass the overlap rejection.
- Reviewer A independently accepted the finding and severity. The fix uses
  filesystem identity for existing non-redirecting paths and conservative
  Darwin case-folded containment for missing suffixes. A native macOS test
  covers case-variant exact development equality plus both overlap directions.
- Reverification: 45 initializer/preflight/runtime tests passed with the native
  Windows test skipped; the full suite passed 413 tests with that same skip;
  compilation and diff checks passed.
- Next review round: Both reviewers receive the complete refreshed slice.

### Round 3

- Reviewer A found one P2 blocker: composed and decomposed Unicode aliases on
  macOS could share the nearest existing filesystem entry while a missing
  descendant bypassed the lexical containment check.
- Reviewer B found one P2 blocker: conservative Darwin case-folding was also
  used for exact equality, so distinct existing case variants on a
  case-sensitive macOS volume could be mistaken for the development no-op.
- Each reviewer independently accepted the other reviewer's finding, severity,
  scope, and proposed correction.
- The correction separates exact identity from conservative overlap identity.
  Development equality now requires `samefile()` or exact platform-native
  lexical equality. Darwin case-folding and Unicode normalization only classify
  an uncertain relationship as unsafe overlap, and missing suffixes are checked
  against nearest existing ancestors by filesystem identity.
- Portable regressions cover distinct Darwin case variants and decomposed
  Unicode descendants. Native macOS coverage exercises composed/decomposed
  exact identity and both overlap directions.
- Reverification: 91 focused tests passed with one native-Windows skip; the
  full suite passed 416 tests with that same skip; compilation and diff checks
  passed.
- Process exception: this is the third default review round. The owner explicitly
  approved all steps ahead of time and requested no intermediate approval
  prompts, so one final confirmation round is authorized instead of pausing for
  another process decision. Publication remains separately gated.
- Next review round: Both reviewers receive the complete refreshed slice for
  final independent confirmation.

### Round 4

- Reviewer A found one P2 blocker: overlap detection compared only the nearest
  existing entries, so an existing non-lexical filesystem alias for a package
  ancestor, such as a Windows 8.3 short name, could bypass both containment
  directions.
- Reviewer B found one P0 blocker: Windows seed-file opens protected the final
  component but did not pin the packaged seed root and its intermediate
  components, allowing a junction substitution between preflight and copying.
- Each reviewer independently accepted the other reviewer's finding, severity,
  scope, and proposed correction.
- Containment now walks every validated existing ancestor state and compares
  filesystem identity plus the conservative suffix. A portable mocked-identity
  test covers aliased existing ancestors and descendants; a native Windows test
  exercises short-name aliases when the volume exposes them.
- Windows now pins the full packaged-seed component chain and any distinct
  existing legacy-root chain before the initial preflight and holds those
  no-reparse, non-delete-sharing handles through target locking, seed reads,
  and final verification. The native Windows substitution test now attacks
  source seed opens as well as target lock and temporary-file opens and verifies
  copied bytes remain the packaged bytes.
- Reverification: 92 focused tests passed with two native-Windows skips; the
  full suite passed 417 tests with those same skips; compilation and diff checks
  passed.
- Process exception: the owner's explicit advance approval and no-prompt request
  authorize resolving newly confirmed blockers and repeating final independent
  confirmation until the slice is clear. This does not authorize publication.
- Next review round: Both reviewers receive the complete refreshed slice.

### Round 5

- Reviewer A reported no findings and confirmed all prior safety, containment,
  Windows pinning/contention, macOS identity, startup-ordering, documentation,
  and coverage findings resolved without an identified regression.
- Reviewer B independently reported no findings and confirmed all prior
  blockers resolved with appropriate implementation, tests, documentation,
  and verification evidence.
- Final disposition: no blocking or nonblocking reviewer findings remain.
- Hosted Windows execution of the two native tests remains the publication CI
  gate; no local approximation is recorded as equivalent evidence.

### Hosted CI correction

- The first published matrix run passed all six macOS/Ubuntu jobs and failed
  all three Windows jobs with the same deterministic test results.
- Two portable regressions made invalid host assumptions: `LONGPA~1` was a real
  short-name alias on Windows, and patching `sys.platform` did not undo Windows'
  native case-folding in `normcase`. The tests now use a synthetic alias name
  and an explicit Darwin-native lexical-key stub.
- The native substitution test proved that a metadata-only directory handle did
  not block the hosted Windows runner's rename operation. Directory guards now
  request `FILE_TRAVERSE | FILE_READ_ATTRIBUTES` while continuing to omit
  `FILE_SHARE_DELETE`. Traverse supplies ordinary access for share-mode
  enforcement without the directory-list permission included by generic read.
- The corrective reviewers agreed the original generic-read fix was broader
  than necessary for traverse-only enterprise paths. The narrowed mask retains
  the native rename-substitution test and adds a native mask regression that
  rejects accidental directory-list access.
- Corrective verification: 92 focused tests passed with three Windows-native
  skips; the full suite passed 417 tests with those same skips; compilation and
  diff checks passed.
- Final corrective review: Both independent reviewers reported no findings and
  confirmed the prior traverse-only compatibility concern resolved. Hosted
  Windows execution remained required to prove the native behavioral guards.
- Corrective hosted run `29642167247` passed all nine macOS, Ubuntu, and Windows
  Python 3.11-3.13 jobs. Each Windows job completed all 420 tests successfully;
  the native root-substitution, short-name, and access-mask gates did not fail.

## Documentation updates

- Roadmap: Records 1A/1B complete and makes previewed, backed-up legacy
  migration the next bounded Milestone 1 work.
- Changelog: Records initialization, safety invariants, tests, and exclusions.
- Architecture/operator docs: `DATA_LAYOUT.md`, `ARCHITECTURE.md`, and README
  now distinguish completed clean initialization from deferred migration,
  backup/restore, schema, and data-class moves.
- Project/session notes: This review log and the closed 1B-A outcome.
- Documentation verification: Focused contract tests and `git diff --check` pass.

## Publication gate

- Proposed files: `ARCHITECTURE.md`, `CHANGELOG.md`, `DATA_LAYOUT.md`,
  `README.md`, `ROAD_TO_BETA.md`, `data_layout.py`, `mentat_lifecycle.py`,
  `runtime_config.py`, `server.py`, the 1B-A and 1B-B review logs, and six
  focused contract/integration test files.
- Branch and base: `codex/beta-1b-data-root-initializer` to `main`.
- Commit message: `Initialize the platform data root`.
- PR title: `Complete Milestone 1B data-root initialization`.
- PR summary: Execute the approved clean-root preflight under a cross-platform
  lock; create the six data classes and copy only missing fixed seeds through
  confined, no-replace operations; integrate config-less installed startup;
  preserve source/legacy data for later migration; document and test the full
  Milestone 1B contract.
- Verification: Before first publication, 92 focused and 417 full tests passed
  with two Windows-native skips. After the corrective delta, 92 focused and 417
  full tests pass with three Windows-native skips; compilation/diff checks pass;
  two independent reviewers report no findings. Hosted run `29642167247`
  passed all nine jobs, including Windows Python 3.11-3.13.
- Unresolved risks: Exact native Windows private ACL enforcement remains a
  prerequisite for any later secret-bearing surface. Migration, backup,
  restore, schema, and data-class moves are intentionally deferred.
- User authorization and scope: Initial publication was explicitly approved.
  The four-file CI correction requires immediate approval before staging,
  commit, and push.
- Initial commit hash: `eff458d985365ccda0431c5054fec06b9d417cb8`.
- Corrective commit: `5cd248a782f541028e295bafb354225df475cb01`.
- Outcome-record commit: Not committed; proposed message `Close Milestone 1B outcome`.
- Ready PR URL: `https://github.com/hazeion/agent-os/pull/22`.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-7 pass locally and in the full
  nine-job hosted matrix. Both independent reviewers report no findings.
- Potential bugs or untested paths: No known Milestone 1B blocker remains.
  Native Windows ACL exclusivity is intentionally not claimed for future
  secret-bearing data.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: Source checkout behavior remains
  unchanged; migration, backup, and restore remain separate slices. Reverting
  startup integration is the code rollback; public-safe initialized defaults
  can remain without overwriting operator data.
- User decision: Pending owner confirmation of this outcome classification and
  immediate approval to publish the documentation-only closure record.
- Next slice authorized: Pending owner outcome review; the roadmap's next
  bounded slice is previewed, backed-up, locked legacy migration.
