# Feature Slice Review: Define the Milestone 1A Data Layout Contract

Status: Paused — awaiting publication approval
Slice: `beta-1a-data-layout-contract`
Date: `2026-07-17`
Review log: `reviews/2026-07-17-beta-1a-data-layout-contract.md`

## Slice contract

### Goal

Define one complete, test-enforced target layout for durable Mentat operator
data before any runtime default, migration, backup, or installer behavior changes.

### In scope

- Inventory every current mutable or stateful surface: tracked seeds,
  project-owned operator JSON, private Console data, ephemeral runtime data,
  migration backups, caches/development output, machine-local configuration,
  browser storage, and external Hermes/Obsidian/Google/browser state.
- Define the target data-root directories and the ownership, retention, privacy,
  and backup class for each.
- Define macOS, Windows, and Linux defaults plus the exact CLI, environment,
  TOML, and platform-default precedence.
- Define missing-only seed initialization, migration preview/conflict/backup
  behavior, schema-version rules, forward-version refusal, and secret handling.
- Add static contract tests and update the architecture, operator, roadmap, and
  changelog records.

### Out of scope

- Runtime resolver or path changes, a `platformdirs` dependency, seed copying,
  migration/backup/restore commands, schema migrations, UI changes, remote
  Hermes implementation, packaging, or native installers.
- Moving, deleting, or rewriting current operator data.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A canonical contract inventories every current mutable/stateful surface and all tracked seed JSON files. | `tests.test_data_layout_contract` inventory tests | Passed |
| AC-2 | The target root defines durable JSON plus `private/`, `runtime/`, `backups/`, `cache/`, `logs/`, and `config/` with unambiguous ownership and retention. | Layout contract tests and document inspection | Passed |
| AC-3 | Platform defaults are macOS Application Support, Windows LocalAppData, and Linux XDG data home with local-share fallback, with CLI → environment → TOML → default precedence. | Platform/precedence contract test | Passed |
| AC-4 | Initialization is missing-only and migration is previewed, conflict-refusing, backed up, versioned, atomic where implemented, and forward-version refusing. | Migration safety contract test | Passed |
| AC-5 | Private storage is owner-only and remote credentials never enter browser payloads/storage, logs, diagnostics, tracked files, or ordinary backups. | Privacy contract test | Passed |
| AC-6 | Architecture, README, roadmap, and changelog point to the canonical contract without claiming runtime implementation. | Primary-document contract test | Passed |
| AC-7 | Current repo-local runtime defaults and dependencies remain unchanged in this contract-only slice. | Explicit negative contract assertions and diff inspection | Passed |
| AC-8 | Focused tests, full suite, and both independent adversarial reviews pass. | Verification and review records | Passed |

### Constraints and recovery

- Safety: No current data is mutated. No direct Hermes/Obsidian/Google writes
  are authorized. Secrets remain outside ordinary data flows and backups.
- Compatibility: The contract covers macOS and Windows tier one, Linux preview,
  Python 3.11 through 3.13, source-checkout development overrides, and future
  native/pipx installs without implementing them.
- Rendered behavior: Not applicable; no browser-visible behavior changes.
- Rollback or recovery: Revert documentation and contract tests. There is no
  data migration or runtime state to undo.
- Documentation targets: `DATA_LAYOUT.md`, `ARCHITECTURE.md`, `README.md`,
  `ROAD_TO_BETA.md`, `CHANGELOG.md`, and this review log.
- Version-control strategy: branch `codex/beta-1a-data-layout-contract` from
  merged `main`; ready PR to `main` only after explicit publication approval.

### Scope discussion and approval

- Recommendation and rationale: Establish the data and secrecy boundary before
  changing defaults so later initialization, migration, and backup slices share
  one testable contract.
- Alternatives considered: Implement the resolver immediately (rejected because
  it combines policy with mutation); add `platformdirs` now (deferred until the
  resolver slice); keep private and ephemeral files mixed (rejected because it
  prevents clear retention and backup rules).
- User decisions: Approved the target directories, platform defaults,
  precedence, missing-only seeds, owner-only privacy, guarded migrations,
  forward refusal, and contract-only boundary.
- Approved at: 2026-07-17.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No canonical complete inventory exists. | Enumerate current `data/*.json` and require each current surface in the contract. | The written contract covers known state. | Static tests cannot discover every future runtime write automatically. |
| AC-2 | `data/runtime` mixes durable private and ephemeral state. | Require every target directory and its policy language. | Target classes are distinct before implementation. | Does not create directories. |
| AC-3 | Current default is repo-local. | Require exact platform defaults and ordered precedence text. | Resolver behavior is specified consistently. | Does not exercise platform APIs. |
| AC-4 | Migration/backup behavior is partial and repo-local. | Require missing-only, preview, conflict, backup, schema, and forward-refusal rules. | Destructive edge cases have a written fail-closed policy. | Commands remain deferred. |
| AC-5 | Future credentials lack a finalized storage class. | Require owner-only private storage and explicit exclusion surfaces. | Secret flows are bounded before remote work. | No credential storage exists yet. |
| AC-6 | Primary docs describe only the current mixed layout. | Require canonical links and implementation-status language. | Operators are not misled. | No rendered docs test is needed. |
| AC-7 | A broad data change could accidentally alter runtime behavior. | Assert current repo-local default and absence of `platformdirs`; inspect diff. | This slice remains contract-only. | These assertions are intentionally removed or revised in the implementation slice. |
| AC-8 | No slice evidence yet. | Focused suite, full suite, two independent reviews. | Required gates are exercised. | Hosted CI follows publication. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Inventory inspection of runtime config, tracked data, browser keys, migration paths, and primary docs | macOS workspace, Python source checkout | Pass | Confirmed the current mixed repo-local layout and captured all known surfaces in the approved contract. |
| `python3 -m unittest tests.test_beta_contract tests.test_data_contract tests.test_runtime_config -v` | macOS, system Python 3 | Pass (exit 0) | Pre-change focused baseline: 21 passed, 0 failed or skipped. |
| `python3 -m unittest tests.test_data_layout_contract -v` after adding tests but before the contract | macOS, system Python 3 | Expected fail (exit 1) | 7 failed because `DATA_LAYOUT.md` and primary-doc links did not exist; direct evidence of the agreed gap. |

### Test discussion and approval

- User questions and decisions: The user approved static data-layout contract
  tests plus the full suite, with no rendered-browser testing.
- Accepted coverage gaps: No platform API, migration, backup/restore, installer,
  or UI execution because all of those behaviors are explicitly deferred.
- Approved at: 2026-07-17.

## Implementation record

### Changes

- Added `DATA_LAYOUT.md` as the canonical contract for the complete current
  inventory, target root, platform defaults, precedence, initialization,
  migration/schema, backup/restore, and privacy boundaries.
- Added eight static data-layout contract tests and advanced two existing
  roadmap assertions from Milestone 1A to Milestone 1B.
- Linked the contract from architecture, README, and roadmap; updated the
  changelog and next-action records without changing runtime defaults.
- Closed the preceding CI review record with its exact green run and merge SHA.

### Deviations and decisions

- Process-only carry-forward: closed the preceding CI slice's persistent record
  after its exact merge candidate passed all nine hosted jobs and PR #19 merged.
  Recording that evidence before the merge would have changed the tested commit
  SHA, so the closure is included here without changing this slice's runtime or
  data-layout scope.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_data_layout_contract -v` | macOS, system Python 3 | Exit 0 | 7 passed, 0 failed/skipped | New canonical contract tests. |
| `python3 -m unittest tests.test_data_layout_contract tests.test_beta_contract tests.test_ci_workflow tests.test_data_contract tests.test_runtime_config -v` | macOS, system Python 3 | Exit 0 | 34 passed, 0 failed/skipped | Contract, roadmap, CI record, seed, and current-config boundaries. |
| `python3 -m unittest tests.test_data_layout_contract -v` after Round 1 assertions | macOS, system Python 3 | Exit 1 then 0 | 5 failed before corrections; 8 passed after | Directly reproduced every accepted reviewer root cause, then verified the strengthened contract. |
| `python3 -m unittest tests.test_data_layout_contract tests.test_beta_contract tests.test_ci_workflow tests.test_data_contract tests.test_runtime_config -v` after Round 1 fixes | macOS, system Python 3 | Exit 0 | 35 passed, 0 failed/skipped | Revised inventory, sequencing, permission, backup, and XDG rules plus adjacent records. |
| `python3 -m compileall -q .` and `git diff --check` | macOS, system Python 3 / Git | Exit 0 | No errors | Ran after the successful full suite. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS, system Python 3 | Exit 1 | 373 passed, 1 failed | First run exposed one stale CI-record assertion requiring “Begin Milestone 1A”; updated to the approved 1B handoff. |
| `python3 -m unittest discover -s tests -v` | macOS, system Python 3 | Exit 0 | 374 passed, 0 failed/skipped | Existing history-permission warning only. |
| `python3 -m unittest discover -s tests -v` after Round 1 fixes | macOS, system Python 3 | Exit 0 | 375 passed, 0 failed/skipped | Existing history-permission warning only. |

### Rendered or manual behavior

- Not applicable; this slice changes documentation and static contract tests only.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Complete uncommitted Milestone 1A worktree diff and all
  new files before the reviewer fixes.
- Verification evidence: 34 focused tests and 374 full-suite tests passed;
  compilation and diff checks passed.
- Rendered artifacts: Not applicable.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P1 | Yes | Seed initialization preceded deferred legacy migration, so fresh seeds would manufacture destination conflicts and strand legacy work. | Yes | Detect/reserve legacy state before any seed copy and test the sequencing. |
| A-2 | P1 | Yes | Permission-hardening failure was only reported, allowing private/credential writes without verified owner-only access. | Yes | Establish and read back owner-only access or fail closed before private writes. |
| A-3 | P2 | Yes | The inventory named nonexistent `mentat.local.bat` and omitted real Windows and legacy compatibility inputs. | Yes | Record `mentat.local.env.bat`, legacy TOMLs/environment aliases, precedence, and tests. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | P1 | Yes | Backup inclusion was ambiguous for config and durable private state, permitting inconsistent Console database/history/blob snapshots. | Yes | Assign every class an explicit policy and capture the Console set as one WAL-safe consistency unit. |
| B-2 | P2 | Yes | Independently found the same incorrect Windows helper and omitted compatibility inputs as A-3. | Yes | Correct and test the complete active config inventory. |
| B-3 | P2 | Yes | Linux was called XDG-style while ignoring `XDG_DATA_HOME`, conflicting with XDG/platformdirs behavior. | Yes | Define valid set/unset XDG semantics inside the platform-default layer and test them. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Incomplete/inaccurate compatibility config inventory (A-3/B-2) | Corroborated | Both independently blocking. | Accepted; AC-1/AC-3 require all active inputs. | Correct helper, legacy shared/local TOMLs, `AGENT_OS_*`, intra-layer precedence, migration window, and assertions added. |
| Seed initialization can block later legacy migration (A-1) | Unique | Reviewer B independently maintained P1 after cross-critique. | Accepted; roadmap requires migration without loss/duplication. | Legacy detection/reservation now precedes seed copying; colliding destinations stay absent. |
| Owner-only enforcement can report and continue (A-2) | Unique | Reviewer B independently maintained P1 after cross-critique. | Accepted; AC-5 requires a real security boundary. | Read-back verification and fail-closed behavior before private/secret writes added and tested. |
| Ambiguous backup classes/Console consistency (B-1) | Unique | Reviewer A independently maintained P1 after cross-critique. | Accepted; backup contract must prevent dangling references. | Explicit policy for every class and WAL-safe database/history/referenced-blob consistency unit added and tested. |
| Linux XDG base unspecified (B-3) | Unique | Reviewer A independently maintained P2 blocking after cross-critique. | Accepted; this clarifies the platform-default layer without changing app-specific precedence. | Valid non-empty `XDG_DATA_HOME` plus local-share fallback documented in contract/roadmap and tested. |

### Reverification

- Focused tests: 35 passed; all five added reviewer assertions initially failed
  against the old contract and all eight data-layout tests now pass.
- Full suite: 375 passed, 0 failed/skipped; existing permission warning only.
- Next review round or gate result: Round 2 completed with no blocking findings.

### Round 2 results

- Reviewer A — correctness and safety: No findings. Confirmed all five Round 1
  root causes were resolved without a new contract or test issue.
- Reviewer B — compatibility and product: All five Round 1 root causes resolved;
  one P3 non-blocking finding that the milestone map still said “Not started”
  while the detailed section and next action said 1A complete.
- Peer critique: Reviewer A independently maintained the P3 as accurate,
  non-blocking, and inside the approved documentation scope.
- Disposition: Accepted. Added a focused roadmap-status assertion, observed its
  expected failure, and changed the map to `In progress — 1A complete`.
- Reverification: 35 focused tests and all 375 tests passed; compilation and
  `git diff --check` passed.

### Round 3 packet

- Diff/commit reviewed: Complete current worktree, including all new files,
  after the roadmap status correction.
- Verification evidence: 35 focused and 375 full-suite tests passed.
- Rendered artifacts: Not applicable.

### Round 3 results

- Reviewer A — correctness and safety: No findings. Confirmed the complete slice
  is internally consistent, contract-only, fully verified, and truthfully logged.
- Reviewer B — compatibility and product: No findings. Confirmed every prior
  safety/compatibility fix remains intact and the roadmap correction is accurate
  and tested.
- Final independent review gate: Passed; no blocking or non-blocking finding
  remains.

## Documentation updates

- Roadmap: Milestone 1A contract complete; next action is bounded Milestone 1B.
- Changelog: Records the contract and explicit lack of runtime changes.
- Architecture/operator docs: Canonical contract linked from architecture and
  README; current repo-local behavior remains explicit.
- Project/session notes: This review log.
- Documentation verification: 35 focused contract tests and `git diff --check`
  passed.

## Publication gate

- Proposed files: `DATA_LAYOUT.md`, `ARCHITECTURE.md`, `README.md`,
  `ROAD_TO_BETA.md`, `CHANGELOG.md`, `tests/test_data_layout_contract.py`,
  `tests/test_beta_contract.py`, `tests/test_ci_workflow.py`,
  `reviews/2026-07-17-beta-1a-data-layout-contract.md`, and the process-only
  closure in `reviews/2026-07-17-beta-ci-guardrail.md`.
- Branch and base: `codex/beta-1a-data-layout-contract` to `main`.
- Commit message: `Define Milestone 1A data layout contract`.
- PR title: `Define the Milestone 1A data layout contract`.
- PR summary: Add the complete mutable-path inventory and canonical target data
  layout; define platform/XDG defaults, override compatibility, legacy-first
  initialization, fail-closed permissions/migration/schema rules, explicit
  backup classes, and secret exclusions; add static contract coverage and
  advance the roadmap to Milestone 1B without changing runtime behavior.
- Unresolved risks: No blocking slice risk. Runtime resolver, initialization,
  migration, backup/restore, and cross-platform execution remain deliberately
  unimplemented and require later reviewed slices.
- User authorization and scope: Not yet requested.
- Commit hash: Pending.
- Ready PR URL: Pending.

## Outcome review

- Classification: In progress.
- Acceptance criteria summary: AC-1 through AC-8 passed locally; publication and
  hosted CI remain pending approval.
- Potential bugs or untested paths: Runtime implementation remains deferred.
- Remaining reviewer dissent: None; both final reviewers reported no findings.
- Compatibility/migration/rollback concerns: No runtime mutation in this slice.
- User decision: Pending.
- Next slice authorized: No.
