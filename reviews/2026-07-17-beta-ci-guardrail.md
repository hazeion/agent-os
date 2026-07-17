# Feature Slice Review: Add the Early Cross-Platform CI Guardrail

Status: Paused
Slice: `beta-ci-guardrail`
Date: `2026-07-17`
Review log: `reviews/2026-07-17-beta-ci-guardrail.md`

## Slice contract

### Goal

Automatically run Mentat's existing syntax and regression checks across the
approved operating-system and Python matrix before Milestone 1 changes the
mutable-data boundary.

### In scope

- Add one GitHub Actions workflow for pull requests and pushes to `main`.
- Run Ubuntu, macOS, and Windows with Python 3.11, 3.12, and 3.13.
- Install the pinned runtime dependencies in every matrix job.
- Compile the Python sources, syntax-check every tracked JavaScript source, and
  run the complete unittest suite in every matrix job.
- Keep the workflow read-only and secret-free.
- Add focused workflow contract tests and update the roadmap and changelog.
- Require a green first GitHub-hosted matrix run before classifying the slice
  as successful.

### Out of scope

- Packaging, native installers, signing, notarization, or release artifacts.
- Browser automation or rendered UI checks.
- Dependency scanning, secret scanning, or branch-protection configuration.
- Runtime, UI, Hermes, operator-data, or migration behavior.
- Milestone 1A implementation.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A workflow runs on pull requests and pushes to `main`. | Focused workflow contract test and workflow inspection. | Passed locally; hosted parse pending |
| AC-2 | The workflow expands to all nine combinations of Ubuntu, macOS, Windows, and Python 3.11 through 3.13 without cancelling sibling failures. | Focused matrix contract test and first Actions run. | Passed statically; hosted run pending |
| AC-3 | Every job checks out the repository, selects its matrix Python version, installs pinned dependencies, and uses a fixed Node version. | Focused workflow contract test and Actions logs/status. | Passed statically; hosted run pending |
| AC-4 | Every job compiles all project Python, checks all three tracked JavaScript/MJS files, and runs the full unittest suite. | Focused workflow contract test and Actions logs/status. | Passed locally; hosted run pending |
| AC-5 | The workflow has read-only repository permissions and does not consume repository secrets. | Focused negative contract assertions and inspection. | Passed |
| AC-6 | The full existing suite remains green locally. | Full-suite result. | Passed |
| AC-7 | The first GitHub-hosted nine-job matrix completes successfully. | GitHub Actions check results for the ready PR. | Pending |
| AC-8 | Roadmap and changelog truthfully record the early guardrail without claiming later Milestone 4 gates. | Documentation assertions and inspection. | Passed |
| AC-9 | No runtime, UI, Hermes, configuration, operator-data, or migration behavior changes. | Changed-file and raw-diff inspection. | Passed |

### Constraints and recovery

- Safety: Use `contents: read`, no secrets, no write-capable workflow token,
  and no execution of untrusted external scripts beyond official GitHub
  actions and pinned Python packages.
- Compatibility: Use GitHub-hosted Ubuntu, macOS, and Windows runners and the
  approved CPython 3.11, 3.12, and 3.13 versions. Keep commands portable across
  the runners' default shells.
- Rendered behavior: Not applicable; this slice has no UI changes.
- Rollback or recovery: Revert the workflow, focused contract test, and
  documentation updates. There is no data or runtime migration.
- Documentation targets: `ROAD_TO_BETA.md`, `CHANGELOG.md`, and this review
  log. Update `README.md` only if operator-facing verification instructions
  materially change.
- Version-control strategy: Branch `codex/beta-ci-guardrail` from PR #18's
  approved head. If PR #18 is still open, publish a stacked ready PR against
  `codex/beta-0-release-contract`; retarget to `main` after PR #18 merges.

### Scope discussion and approval

- Recommendation and rationale: Add the narrow cross-platform syntax and
  regression matrix before changing mutable paths so path regressions surface
  while the data-root work remains small.
- Alternatives considered: Run one Python version per OS to reduce job cost,
  or append this work to PR #18. The reduced matrix would not verify the full
  approved Python range, while extending PR #18 would blur the one-slice
  review boundary.
- User decisions: Proceed with the complete 3x3 matrix and the documented
  exclusions.
- Approved at: Explicitly approved by the project owner on 2026-07-17.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1, AC-2 | No `.github` workflow exists. | Add a stdlib contract test that inspects the workflow triggers, OS values, Python values, and `fail-fast: false`. | The checked-in workflow statically declares the required trigger and nine-job matrix. | A text contract cannot execute GitHub's matrix expansion. |
| AC-3 | No clean-runner dependency/tool setup exists. | Assert official checkout, setup-python, and setup-node steps, matrix Python selection, fixed Node version, and dependency installation. | Each declared job prepares the expected reproducible toolchain. | Installation succeeds only when exercised on hosted runners. |
| AC-4 | Checks are local-only. | Assert the portable compile, three JavaScript syntax, and unittest commands; run them locally before and after implementation. | The workflow contains every agreed check and each command works on the local platform. | Local execution cannot prove Windows or Ubuntu behavior. |
| AC-5 | No workflow permission boundary exists. | Assert `contents: read`; reject write permissions, `secrets.`, `pull_request_target`, and credential persistence. | The workflow is read-only and does not intentionally consume repository secrets. | Static assertions cannot detect future compromise of an upstream action. |
| AC-6 | Existing local baseline must remain stable. | Run the complete unittest suite before and after implementation. | Existing repository behavior does not regress locally. | One local platform/runtime is not the support matrix. |
| AC-7 | No hosted matrix evidence exists. | Inspect the ready PR's GitHub Actions checks and require all nine jobs to pass. | The actual GitHub-hosted OS/Python combinations execute successfully. | Does not cover self-hosted runners or native installers. |
| AC-8 | Roadmap still describes the guardrail as future work. | Focused documentation assertions and manual contradiction search. | Records match implemented CI scope without overstating Milestone 4. | Documentation tests remain intentionally text-based. |
| AC-9 | Runtime is outside scope. | Inspect changed files and raw diff; run the full suite. | Only workflow, tests, and approved records changed. | Cannot prove absence of every indirect dependency-service change. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Workflow inventory | Local worktree | Expected gap | No `.github` directory or GitHub Actions workflow exists. |
| `python3 -m unittest discover -s tests -v` | macOS, local Python 3.13 | Pass | 359 passed in 15.047s; the existing history-permission warning was observed. |
| `python3 -m compileall -q .` | macOS, local Python 3.13 | Pass | All discovered Python sources compiled successfully. |
| `node --check public/core.js`, `public/app.js`, and `scripts/browser_smoke.mjs` | macOS, local Node | Pass | All three tracked JavaScript/MJS sources parsed successfully. |
| `git diff --check` | Local worktree | Pass | No whitespace errors in the process-log change. |
| `python3 -m unittest tests.test_ci_workflow -v` after adding the approved contract tests | macOS, local Python 3.13 | Expected fail | 6 failed because the workflow and completed project-record language did not yet exist. |

### Test discussion and approval

- User questions and decisions: The owner rejected treating the missing
  pre-publication hosted run as an accepted final gap. The strategy was revised
  so all nine GitHub-hosted jobs are a mandatory final acceptance gate after
  the reviewed workflow is published.
- Accepted coverage gaps: None for the approved OS/Python matrix. Hosted
  evidence is sequenced after publication but must pass before the slice can be
  classified as successful. Native installers, browser automation, packaging,
  and later Milestone 4 gates remain outside this slice.
- Approved at: Explicitly approved by the project owner on 2026-07-17.

## Implementation record

### Changes

- Added the six focused workflow contract tests first and captured their
  expected failures against the missing workflow and stale project records.
- Added one read-only, secret-free GitHub Actions workflow with the approved
  nine-job OS/Python matrix and every agreed verification command.
- Updated the roadmap and changelog to distinguish the early guardrail from
  the deferred Milestone 4 release gates.

### Deviations and decisions

- The first post-implementation full-suite run had one error in the prior
  release-contract test because it required the early CI guardrail to remain a
  pending action before Milestone 1A. Updating that assertion to require
  Milestone 1A first and reject stale pending-CI language is within AC-8 and is
  necessary to represent the completed handoff accurately.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_ci_workflow tests.test_beta_contract -v` | macOS, local Python 3.13 | Exit 0 | 16 passed, 0 failed, 0 skipped | Workflow and roadmap handoff contracts passed. |
| `python3 -m compileall -q .` | macOS, local Python 3.13 | Exit 0 | All discovered Python sources compiled | Matches the workflow compile command. |
| Three `node --check` commands | macOS, local Node | Exit 0 | 3 passed | `public/core.js`, `public/app.js`, and `scripts/browser_smoke.mjs` parsed. |
| `git diff --check` | Local worktree | Exit 0 | No errors | Whitespace check passed. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| First `python3 -m unittest discover -s tests -v` | macOS, local Python 3.13 | Exit 1 | 364 passed, 1 error | Prior beta-contract test still expected CI to be pending; corrected within AC-8. |
| Final `python3 -m unittest discover -s tests -v` | macOS, local Python 3.13 | Exit 0 | 365 passed, 0 failed, 0 skipped | Existing history-permission warning observed; no test failure. |

### Rendered or manual behavior

- Not applicable; this slice has no UI changes.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Uncommitted working-tree diff on
  `codex/beta-ci-guardrail`, including all six slice files.
- Verification evidence: 16 focused tests passed; Python compilation and all
  three JavaScript syntax checks passed; 365 full-suite tests passed; diff
  check passed.
- Rendered artifacts: Not applicable; no UI changes.

Reviewer findings pending.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P2 | Yes | The three native `node --check` calls share one multiline step. On the Windows default PowerShell shell, a failure in an earlier native command can be masked by a successful final command. | Yes | Put each JavaScript check in its own step and protect that structure with a contract assertion. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | P2 | Yes | The matrix test checks member values but would permit an `exclude:` that silently reduces the matrix below nine jobs. | Yes | Reject `include:` and `exclude:` modifiers for the fixed Cartesian matrix. |
| B-2 | P2 | Yes | The safety test permits unlisted write scopes, bracket-form secret access, and additional third-party `uses:` actions. | Yes | Reject generic write scopes and all secret-context syntax; require the exact approved action list. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Windows native-command failure propagation | Unique in initial pass; corroborated by peer critique | Reviewer B maintained A-1 as P2 blocking because the default Windows PowerShell step can report only the final native command's status. | Accepted; AC-4 requires every matrix job to enforce every check. | Split the three JavaScript checks into independent steps and required each exact `run:` command in the contract test. |
| Matrix modifiers can defeat the nine-job contract | Unique in initial pass; corroborated by peer critique | Reviewer A maintained B-1 as P2 blocking and reproduced the eight-job exclusion case conceptually. | Accepted; AC-2 requires the full Cartesian matrix. | Added negative assertions for `include:` and `exclude:`. |
| Safety assertions are not exhaustive | Unique in initial pass; corroborated by peer critique | Reviewer A maintained B-2 as P2 blocking and confirmed extra write scopes, actions, and bracket-form secrets would pass. | Accepted; AC-5 explicitly requires the read-only, secret-free, official-action boundary. | Added generic write/secret rejection and exact action-list validation. |

### Reverification

- Focused tests: 16 passed after the three Round 1 corrections. The JavaScript
  step-structure assertion failed before the workflow was split, then passed.
- Full suite: 365 passed after the Round 1 corrections.
- Syntax/diff checks: Python compilation, all three JavaScript checks, and
  `git diff --check` passed.
- Next review round or gate result: Round 2 complete-slice review pending.

### Round 2 packet

- Diff/commit reviewed: Fresh complete uncommitted working-tree diff after all
  accepted Round 1 fixes.
- Verification evidence: 16 focused tests passed; 365 full-suite tests passed;
  compilation, syntax, and diff checks passed.
- Rendered artifacts: Not applicable; no UI changes.

### Round 2 reviewer results

- Reviewer A — correctness and safety: No findings. Confirmed independent
  JavaScript failure propagation, matrix-modifier rejection, exact official
  action validation, and generic write/secret-context rejection.
- Reviewer B — compatibility and product: No findings. Confirmed all Round 1
  findings are resolved and the hosted nine-job result remains correctly
  sequenced as a mandatory post-publication gate.
- Review gate: Passed with no blocking findings after two rounds.

## Documentation updates

- Roadmap: Records the implemented nine-job early guardrail and advances the
  next action to Milestone 1A while preserving later Milestone 4 scope.
- Changelog: Records the early workflow and its explicit exclusions.
- Architecture/operator docs: No change expected.
- Project/session notes: This review log.
- Documentation verification: Focused workflow/record contract tests passed.

## Publication gate

- Proposed files: `.github/workflows/ci.yml`, `CHANGELOG.md`,
  `ROAD_TO_BETA.md`, `tests/test_beta_contract.py`,
  `tests/test_ci_workflow.py`, and this review log.
- Branch and base: `codex/beta-ci-guardrail`; stacked base
  `codex/beta-0-release-contract` while PR #18 is open.
- Commit message: `Add cross-platform CI guardrail`.
- PR title: `Add the early cross-platform CI guardrail`.
- PR summary: Add the read-only nine-job OS/Python matrix, portable syntax and
  full-suite checks, regression contracts, and truthful roadmap/changelog
  records while deferring the remaining Milestone 4 release gates.
- Unresolved risks: Hosted-runner evidence is unavailable until publication;
  all nine jobs are mandatory before successful outcome acceptance. PR #18 is
  still open, so this slice must remain stacked until its approved base lands.
- User authorization and scope: The project owner explicitly approved staging
  the six reviewed files, committing, pushing `codex/beta-ci-guardrail`, and
  opening the ready stacked PR on 2026-07-17.
- Commit hash: Pending.
- Ready PR URL: Pending.

## Outcome review

- Classification: Paused pending publication approval and hosted matrix
  evidence.
- Acceptance criteria summary: AC-1 through AC-6, AC-8, and AC-9 pass local
  evidence; AC-7 requires all nine GitHub-hosted jobs after publication.
- Potential bugs or untested paths: Cross-platform execution is untested until
  the first hosted matrix run.
- Remaining reviewer dissent: None; both reviewers reported no findings in
  Round 2.
- Compatibility/migration/rollback concerns: No migration; workflow rollback
  is a normal revert.
- User decision: Pending.
- Next slice authorized: No
