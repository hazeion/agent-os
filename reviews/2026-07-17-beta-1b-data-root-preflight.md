# Feature Slice Review: Resolve and Preflight the Platform Data Root

Status: In progress
Slice: `beta-1b-data-root-preflight`
Date: `2026-07-17`
Review log: `reviews/2026-07-17-beta-1b-data-root-preflight.md`

## Slice contract

### Goal

Let Mentat deterministically select the future installed data root and classify
initialization, legacy-migration, conflict, existing, and unsafe conditions
without writing to the filesystem.

### In scope

- A standard-library resolver for the approved macOS, Windows, and Linux/XDG
  data-root defaults.
- Exact CLI, Mentat environment, legacy environment, TOML, and platform-default
  precedence while preserving current TOML layer ordering.
- Preserve the tracked source-checkout `data_dir = "data"` override.
- A read-only preflight limited to the nine allowlisted packaged seed names.
- Fail-closed classification of invalid seeds, unsafe roots, symlinks,
  non-regular files, legacy reservations, and source/destination conflicts.
- Side-effect-free, secret-free configuration/preflight reporting.
- Static/operator documentation and the preceding Milestone 1A outcome closure.

### Out of scope

- Directory creation, permission mutation, seed copying, or a source-checkout
  default switch.
- Moving durable private or ephemeral runtime files.
- Migration, backup, restore, package-resource loading, UI changes, remote
  Hermes, packaging, or installers.
- A `platformdirs` dependency.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | macOS, Windows, and Linux resolve exactly to the approved platform roots; Linux honors only a valid absolute non-empty `XDG_DATA_HOME`. | Table-driven resolver tests | Passed locally |
| AC-2 | Data-root precedence is CLI → `MENTAT_DATA_DIR` → `AGENT_OS_DATA_DIR` → existing TOML layers → platform default, with a safe source label. | Resolver/config integration tests | Passed locally |
| AC-3 | The tracked `mentat.toml` keeps source checkouts on repo-local `data/`; a config-less load uses the platform resolver. | Current-config and config-less tests | Passed locally |
| AC-4 | Preflight inspects only the nine known seeds and returns clean, existing, migration-required, conflict, development-override, or unsafe results without writes. | Temporary-filesystem preflight tests | Passed locally |
| AC-5 | Any supported legacy state is detected before initialization planning, reserves all potentially colliding destinations, and never produces a partial clean plan. | Legacy reservation/conflict tests | Passed locally |
| AC-6 | Symlinked/non-regular roots or files, invalid/missing seeds, invalid target JSON, and dangerously broad roots fail closed without exposing file contents. | Negative-path tests | Passed locally |
| AC-7 | Configuration/preflight summaries are side-effect-free and contain only normalized source/status/name metadata. | Reporting and before/after filesystem assertions | Passed locally |
| AC-8 | Documentation remains truthful about the read-only boundary, focused/full tests pass, hosted CI passes, and two independent reviewers clear the slice. | Docs tests, suites, CI, review record | Passed |

### Constraints and recovery

- Safety: No filesystem write is authorized. Preflight never follows symlinks,
  scans arbitrary directories, or returns seed/operator contents.
- Compatibility: macOS and Windows tier one; Linux preview; Python 3.11–3.13;
  Mentat-named values outrank legacy aliases; existing source checkout behavior
  remains unchanged.
- Rendered behavior: Not applicable; no browser-visible change.
- Rollback or recovery: Revert the resolver, preflight, tests, and documentation;
  no data or permission state needs recovery.
- Documentation targets: `DATA_LAYOUT.md`, `ROAD_TO_BETA.md`, `README.md`,
  `CHANGELOG.md`, the Milestone 1A log, and this review log.
- Version-control strategy: `codex/beta-1b-data-root-preflight` from merged
  `main`, followed by a ready PR to `main` after publication approval.

### Scope discussion and approval

- Recommendation and rationale: Split path resolution/read-only preflight from
  writes so legacy data and private permission enforcement cannot be stranded or
  weakened by the first implementation slice.
- Alternatives considered: One writable resolver/initializer slice (rejected as
  too much mutation risk); `platformdirs` (rejected here because the approved
  contract is narrower than its current macOS XDG behavior and needs no new
  dependency).
- User decisions: Approved the 1B-A split and the standard-library resolver.
- Approved at: 2026-07-17.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Current built-in fallback is repo-local. | Simulated platform/env/home tests. | Exact default paths and XDG validation. | Does not call native permission APIs. |
| AC-2 | Current loader does not expose a source and collapses Mentat/legacy env aliases. | Precedence matrix and source assertions. | Ordering is explicit and inspectable. | Does not alter non-data settings. |
| AC-3 | Tracked config masks the built-in fallback. | Test both tracked and config-less loaders. | Development remains stable while installed fallback advances. | Packaging remains deferred. |
| AC-4 | No initialization plan type exists. | Clean/existing/development/read-only tests. | Known files are classified without writes. | No plan is executed. |
| AC-5 | Legacy-before-seed sequencing exists only in docs. | Legacy-only and legacy-plus-target tests. | No partial clean initialization is proposed. | Migration remains deferred. |
| AC-6 | No bounded preflight validation exists. | Symlink, non-file, invalid JSON, missing seed, unsafe-root tests. | Unsafe input fails closed. | JSON schema migration is deferred. |
| AC-7 | Current print-config lacks data-root source. | Summary metadata and filesystem snapshot tests. | Reporting is bounded and side-effect-free. | No new CLI command. |
| AC-8 | No implementation evidence. | Focused suite, full suite, nine-job CI, two reviewers. | Required gates execute. | No rendered testing is applicable. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository/path inspection | macOS source checkout | Pass | Confirmed repo-local fallback, existing TOML/env ordering, and no preflight module. |
| `python3 -m unittest tests.test_runtime_config tests.test_data_layout_contract tests.test_local_server_lifecycle tests.test_beta_contract tests.test_ci_workflow -v` | macOS, system Python 3 | Pass (exit 0) | 47 passed, 0 failed/skipped before implementation tests. |
| `python3 -m unittest discover -s tests -v` | macOS, system Python 3 | Pass (exit 0) | 375 passed, 0 failed/skipped; existing history-permission warning only. |

### Test discussion and approval

- User questions and decisions: Approved table-driven platform, precedence,
  read-only legacy/conflict, negative-path, full-suite, hosted-CI, and independent
  review coverage.
- Accepted coverage gaps: No write, permission, migration, backup, packaging, or
  browser execution in this slice.
- Approved at: 2026-07-17.

## Implementation record

### Changes

- Added `data_layout.py` with exact standard-library platform resolution,
  explicit source labels, and an immutable read-only preflight result.
- Integrated resolution into `runtime_config.py` while retaining the tracked
  TOML development override and exposed only `data_dir_source` in print-config.
- Added table-driven resolver/config tests and temporary-filesystem safety,
  legacy, conflict, symlink, bounded-reporting, and no-write tests.
- Updated the canonical contract, architecture, README, roadmap, changelog, and
  preceding Milestone 1A outcome record.

### Deviations and decisions

- The first preflight implementation rejected all ancestor symlinks. That is
  not portable on macOS, where temporary paths commonly pass through the
  platform `/var` alias. The final design normalizes only the standard trusted
  macOS system aliases, then rejects symlink/reparse components everywhere in
  the selected seed, target, and legacy paths.
- Self-review found that `Path.resolve()` could hide an explicitly selected
  root symlink before preflight. Data-root inputs now become absolute without
  following the final component, and a composed resolver/preflight regression
  test proves the root remains rejectable.
- No dependency was added and no write path was introduced.
- Round 1 review showed that merely selecting the platform root could feed the
  server's existing startup writes. Until 1B-B, both lifecycle preflight and
  direct server startup now fail before cleanup, directory creation, Console
  reconciliation, or runtime-state writes when the source is
  `platform_default`; print-config remains available.

### Gap evidence

- The first focused implementation-test run failed at import with
  `ModuleNotFoundError: data_layout`, directly demonstrating the missing
  resolver/preflight surface.
- After the module was introduced, 7 of 10 focused tests failed because the
  ancestor-symlink check misclassified normal macOS temporary paths; the
  portability fix made those safety-state tests pass.
- The first integrated 44-test run had three expected transition failures:
  bounded summary assertion shape, POSIX path canonicalization, and a stale
  contract-only documentation assertion. Each was corrected before the green
  focused run.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_data_root_preflight tests.test_runtime_config tests.test_data_layout_contract tests.test_local_server_lifecycle -v` | macOS, system Python 3 | Exit 0 | 45 passed, 0 failed/skipped | Includes composed explicit-root symlink regression and source-checkout compatibility. |
| `python3 -m py_compile data_layout.py runtime_config.py server.py` | macOS, system Python 3 | Exit 0 | 3 modules compiled | Syntax gate. |
| `git diff --check` | Git worktree | Exit 0 | No whitespace errors | Static diff gate. |
| `python3 server.py --print-config` | macOS source checkout | Exit 0 | Effective config printed | Confirmed repo-local TOML data root and safe `toml` source label; machine-local values omitted from this log. |
| Post-review focused rerun of resolver/config/contract/lifecycle modules | macOS, system Python 3 | Exit 0 | 50 passed, 0 failed/skipped | Adds startup gate, intermediate-link, reparse-attribute, shape, size, and whitespace regressions. |
| Final focused rerun after optional-file TOCTOU and special-file hardening | macOS, system Python 3 | Exit 0 | 51 passed, 0 failed/skipped | Adds single-result presence classification, FIFO, and nested-parser regressions. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS, system Python 3 | Exit 0 | 389 passed, 0 failed/skipped | Existing history-permission warning only. |
| Post-review quiet full-suite rerun | macOS, system Python 3 | Exit 0 | 394 passed, 0 failed/skipped | Existing history-permission warning only. |
| Final quiet full-suite rerun after TOCTOU/special-file fixes | macOS, system Python 3 | Exit 0 | 395 passed, 0 failed/skipped | Existing history-permission warning only. |
| GitHub Actions run `29633885730`, first attempt | macOS/Windows/Ubuntu, Python 3.11–3.13 | Exit 1 | 6 jobs passed, 3 Windows jobs failed | All Windows versions exposed the same host-dependent simulated Linux absolute-path check. macOS and Ubuntu were green. |
| Approved hosted-CI correction local rerun | macOS, system Python 3 | Exit 0 | 51 focused and 395 full tests passed | Compilation and diff check passed; both independent reviewers reported no findings on the `PurePosixPath` correction. |
| GitHub Actions run `29634031472`, second attempt | macOS/Windows/Ubuntu, Python 3.11–3.13 | Exit 1 | 6 jobs passed, 3 Windows jobs failed | Production validation advanced correctly; the configless integration fixture still supplied a native Windows temp path while simulating Linux. |
| GitHub Actions run `29634337791`, corrected code/fixture | macOS/Windows/Ubuntu, Python 3.11–3.13 | Exit 0 | 9 jobs passed, 0 failed | All compile, JavaScript syntax, and 395-test suite steps passed on Python 3.11–3.13 for macOS, Windows, and Ubuntu. |

### Rendered or manual behavior

- Not applicable.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Complete uncommitted slice diff and all new files.
- Verification evidence: 45 focused tests, 389 full tests, compilation, diff
  check, and print-config behavior.
- Rendered artifacts: Not applicable.

### Reviewer A — correctness and safety

- A-1 (P1, blocking): config-less startup selected the platform root and then
  reached existing write/reconciliation paths before initialization approval.
- A-2 (P2, blocking): user-controlled intermediate symlinks could redirect
  root inspection.
- A-3 (P2, blocking): JSON reads were unbounded and the final open lacked a
  no-follow descriptor boundary.
- A-4 (P2, blocking): whitespace was tested only as an empty-value predicate,
  while the untrimmed CLI/environment value was resolved.

### Reviewer B — compatibility and product

- B-1 (P1, blocking): intermediate symlinks and Windows reparse points could
  redirect inspection.
- B-2 (P1, blocking): config-less server startup could create a partial future
  destination before the writable initializer.
- B-3 (P1, blocking): valid JSON with the wrong fixed top-level document shape
  could be classified as existing.
- B-4 (P2, blocking): a known filename could contain an arbitrarily large JSON
  document and exhaust resources.

### Reconciliation and disposition

All eight findings were accepted. The overlapping path/startup/size findings
were reconciled as single fixes:

- Added a shared startup gate used by the lifecycle helper and direct server
  entry point; platform-default normal startup exits before cleanup or writes.
- Normalized only trusted macOS system aliases, rejected every other
  symlink/reparse component, added POSIX `openat`-style no-follow descriptor
  walking, and retained Windows reparse attribute checks.
- Added a 16 MiB per-document ceiling and exact current top-level list/object
  validation with bounded issue codes.
- Resolved the stripped CLI/environment value, restoring prior whitespace
  behavior.
- Added target/seed/legacy intermediate-link tests, a mocked Windows reparse
  test, root-link composition, wrong-shape and oversized-file tests, and a
  lifecycle-before-cleanup no-write test.

### Reverification

- Focused tests: 50 passed, 0 failed/skipped.
- Full suite: 394 passed, 0 failed/skipped.
- Next review round or gate result: Round 2 requested from both independent
  reviewers; hosted CI remains a publication-stage gate.

### Round 2 and Round 3

- Reviewer A found one additional P2 blocker in Round 2: optional target and
  legacy files used a second existence check after validation, so a newly
  appearing entry could be misclassified as validated. Reviewer B reported no
  findings.
- The finding was accepted. `_json_file_state` now returns validated presence
  and any issue together; target/legacy classification has no second existence
  check. A deterministic regression introduces a symlink after a missing result
  and proves it remains `initialize`, never `existing`.
- Defense in depth added during reconciliation rejects known special files
  before open, uses nonblocking opens, verifies the opened descriptor is still
  regular, and covers FIFO substitution. Deep parser failures also return a
  bounded invalid-JSON issue.
- Final Round 3: both reviewers independently reported no P0-P3 findings and
  confirmed every Round 1/2 blocker resolved.
- Residual reviewer risks: native Windows reparse behavior and hosted matrix
  execution remain to be verified; Windows cannot match POSIX descriptor-walk
  guarantees against a concurrent local substitution; every future writable
  operation must lock and atomically revalidate because a read-only plan can
  become stale after return.

## Documentation updates

- Roadmap: Records 1A and 1B-A complete and identifies bounded 1B-B next.
- Changelog: Records resolver/preflight behavior and the explicit no-write boundary.
- Architecture/operator docs: `DATA_LAYOUT.md`, architecture, and README now
  distinguish implemented read-only selection/preflight from deferred writes.
- Project/session notes: This review log and completed prior-slice outcome closure.
- Documentation verification: Focused contract tests and `git diff --check` passed.

## Publication gate

- Proposed files: `data_layout.py`, `runtime_config.py`, `server.py`,
  `mentat_lifecycle.py`, `tests/test_data_root_preflight.py`,
  `tests/test_runtime_config.py`, `tests/test_local_server_lifecycle.py`,
  `tests/test_data_layout_contract.py`, `tests/test_beta_contract.py`,
  `tests/test_ci_workflow.py`, `DATA_LAYOUT.md`, `ARCHITECTURE.md`, `README.md`,
  `ROAD_TO_BETA.md`, `CHANGELOG.md`, this review log, and the Milestone 1A
  outcome closure.
- Branch and base: `codex/beta-1b-data-root-preflight` to `main`.
- Commit message: `Add read-only platform data-root preflight`.
- PR title: `Add the Milestone 1B-A data-root preflight`.
- PR summary: Add exact platform-default and override resolution with safe
  source labels; add bounded, shape-aware, no-write seed/target/legacy
  preflight; fail closed on links, reparse points, special files, unsafe roots,
  invalid state, legacy reservations, and conflicts; block config-less normal
  startup before deferred initialization writes; preserve the tracked source
  checkout override; update milestone records and tests.
- Unresolved risks: The read-only result grants no future mutation authority
  and 1B-B must lock/revalidate; Windows cannot provide the same descriptor-walk
  guarantee as POSIX against concurrent local substitution; initializer,
  permission, seed-copy, migration, backup, and restore work remains deferred.
- User authorization and scope: Approved staging the documented slice, creating
  the agreed commit, pushing the feature branch, and opening a ready PR on
  2026-07-17. Merge remains separately gated after hosted CI.
- Initial commit hash: `0ad4260c48e348064493dc645216874f5ed810d0`.
- Hosted correction commits: `7dd9179beecfea575168bb8d7ccdf1352a5e5ce2`
  and `79ac55379617257ba7e2d63696f976deee966c35`.
- Ready PR URL: https://github.com/hazeion/agent-os/pull/21
- Hosted-CI correction: The first hosted run showed that Linux/XDG validation
  used the runner host's `Path.is_absolute()` semantics during simulation, so
  Windows treated `/srv/operator-data` as non-absolute. The approved focused fix
  uses `PurePosixPath` for Linux validation without changing runtime precedence
  or platform defaults.
- Hosted-CI correction review: Both independent post-publication reviewers
  reported no P0-P3 findings. A new nine-job run remains required after push.
- Second hosted-fixture correction: Approved on 2026-07-17. The simulated Linux
  configless test now keeps a POSIX-form absolute XDG environment value as a
  raw string on every runner, using the host `Path` only for the expected result
  and no-creation assertion; production resolver code is unchanged. Both first
  review attempts caught and prevented host-native slash conversion before push.
- Final hosted-fixture review: Both independent reviewers reported no P0-P3
  findings after the raw-string correction; 51 focused and 395 full local tests,
  compilation, and diff checks passed.
- Final hosted gate: GitHub Actions run `29634337791` passed all nine jobs.

## Outcome review

- Classification: In progress.
- Acceptance criteria summary: AC-1 through AC-8 pass locally, independently,
  and on the complete hosted OS/Python matrix.
- Potential bugs or untested paths: Writable initialization and migration remain deferred.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: No filesystem mutations in this slice.
- User decision: Pending.
- Next slice authorized: No.
