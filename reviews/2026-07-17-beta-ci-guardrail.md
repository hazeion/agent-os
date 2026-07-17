# Feature Slice Review: Add the Early Cross-Platform CI Guardrail

Status: Complete
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
- Remediate only the clean-runner and Windows portability gaps exposed by that
  first hosted run: hermetic Hermes/Obsidian fixtures, pinned IANA timezone
  data, binary-safe low-level file copies, and platform-correct path assertions.

### Out of scope

- Packaging, native installers, signing, notarization, or release artifacts.
- Browser automation or rendered UI checks.
- Dependency scanning, secret scanning, or branch-protection configuration.
- UI, Hermes capabilities, configuration behavior, operator data, or migrations.
- Runtime changes beyond the binary-mode portability correction and timezone
  dependency required by the approved Windows support tier.
- Milestone 1A implementation.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A workflow runs on pull requests and pushes to `main`. | Focused workflow contract test and workflow inspection. | Passed locally and hosted |
| AC-2 | The workflow expands to all nine combinations of Ubuntu, macOS, Windows, and Python 3.11 through 3.13 without cancelling sibling failures. | Focused matrix contract test and first Actions run. | Passed; all nine jobs launched |
| AC-3 | Every job checks out the repository, selects its matrix Python version, installs pinned dependencies, and uses a fixed Node version. | Focused workflow contract test and Actions logs/status. | Passed locally and hosted |
| AC-4 | Every job compiles all project Python, checks all three tracked JavaScript/MJS files, and runs the full unittest suite. | Focused workflow contract test and Actions logs/status. | Passed locally and hosted |
| AC-5 | The workflow has read-only repository permissions and does not consume repository secrets. | Focused negative contract assertions and inspection. | Passed |
| AC-6 | The full existing suite remains green locally. | Full-suite result. | Passed |
| AC-7 | The GitHub-hosted nine-job matrix completes successfully after remediation. | GitHub Actions check results for the ready PR. | Passed; run `29617117932` |
| AC-8 | Roadmap and changelog truthfully record the early guardrail without claiming later Milestone 4 gates. | Documentation assertions and inspection. | Passed |
| AC-9 | Runtime changes are limited to Windows-safe binary copies and pinned timezone data; tests no longer depend on developer-owned Hermes/Obsidian state. | Focused regressions, dependency contract, changed-file inspection, and hosted matrix. | Passed locally and hosted |

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

### Hosted-run remediation amendment

- Trigger: The first ready-PR matrix reached all verification steps, but all
  nine jobs failed in the full suite. macOS and Ubuntu exposed seven tests that
  depended on local Hermes/Obsidian state. Windows additionally exposed missing
  IANA timezone data, text-mode truncation of PNG bytes at Ctrl-Z in low-level
  copies, and one POSIX-only path assertion.
- Decision: Treat these as required clean-install and Tier 1 Windows
  compatibility corrections, not as accepted CI gaps or reasons to weaken the
  matrix.
- Constraints: Do not skip or conditionally suppress the affected tests. Do
  not broaden runtime work beyond the demonstrated binary-copy correction and
  pinned timezone dependency. Packaging, installers, and Milestone 1A remain
  deferred.
- Approved at: Explicitly approved by the project owner on 2026-07-17 after
  reviewing the hosted failure causes and amended remediation slice.

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
| AC-9 | The first hosted run exposed local-state assumptions and Windows portability defects. | Isolate Hermes/Obsidian fixtures, assert the pinned timezone package and binary flags, retain the PNG Ctrl-Z fixture, and inspect the narrow runtime diff. | The suite runs without developer state and the demonstrated Windows behaviors are corrected without weakening tests. | Final Windows proof requires the hosted retry. |

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
- After the first hosted run, isolated seven tests from developer-owned Hermes
  profiles and Obsidian files instead of skipping them.
- Added `tzdata==2026.3` for cross-platform `zoneinfo` behavior and applied
  `O_BINARY` to the two low-level copy paths that truncated PNG data on Windows.
- Made the Hermes-home assertion compare the platform representation of the
  input `Path`.

### Deviations and decisions

- The first post-implementation full-suite run had one error in the prior
  release-contract test because it required the early CI guardrail to remain a
  pending action before Milestone 1A. Updating that assertion to require
  Milestone 1A first and reject stale pending-CI language is within AC-8 and is
  necessary to represent the completed handoff accurately.
- The hosted matrix demonstrated that the original no-runtime-change boundary
  could not satisfy the approved Tier 1 Windows contract. The owner approved a
  narrow amendment for binary copy semantics and timezone data; no unrelated
  runtime, UI, configuration, or Hermes capability behavior changed.

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
| Remediation `python3 -m unittest discover -s tests -v` | macOS, local Python 3.13 | Exit 0 | 367 passed, 0 failed, 0 skipped | Includes two new Windows/timezone regression contracts; existing history-permission warning observed. |

### Hosted matrix evidence

| Run | Result | Evidence and disposition |
| --- | --- | --- |
| GitHub Actions run `29611921877`, attempt 2, commit `1036d5e` | 9 jobs launched; all reached the full suite and failed | Checkout, Python/Node setup, dependency installation, compilation, and all JavaScript checks passed in every job. macOS/Ubuntu exposed seven local-state-dependent tests. Windows additionally exposed missing timezone data, binary truncation at Ctrl-Z, and a POSIX-only assertion. The approved remediation addresses those causes; a retry after publication is mandatory. |
| GitHub Actions run `29616839592`, commit `8f9c0be` | 6 macOS/Ubuntu jobs passed; 3 Windows jobs each failed one identical assertion | The runtime, timezone, Hermes/Obsidian, and original path fixes passed. One workspace-snapshot fixture used `Path.write_text`, which produced CRLF on Windows while its assertion intentionally required exact LF bytes. The approved final correction writes the fixture as explicit LF bytes and keeps the strict assertion. |
| GitHub Actions run `29617117932`, commit `bea0f63` | 9 of 9 jobs passed | The complete macOS, Windows, and Ubuntu matrix passed on Python 3.11, 3.12, and 3.13. This satisfies the mandatory hosted acceptance gate. |

### Remediation checks

| Command or action | Environment | Exit/result | Notes |
| --- | --- | --- | --- |
| Focused 9-module remediation suite | macOS, local Python 3.13 | 81 passed | The new binary-mode and dependency tests first failed, then passed after implementation. |
| `python3 -m pip install --dry-run -r requirements.txt` | macOS, local Python 3.13 | Exit 0 | Resolved the pinned universal `tzdata==2026.3` wheel. |
| Python compilation, three JavaScript syntax checks, and `git diff --check` | Local worktree | Exit 0 | No syntax or whitespace errors. |

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

### Round 3 remediation review

- Packet: Complete current diff after the approved hosted-failure remediation,
  with Actions run `29611921877` evidence, 81 focused passes, 367 full-suite
  passes, compilation and JavaScript checks, dependency dry-run, and diff
  check.
- Reviewer A — correctness and safety: No findings. Confirmed both low-level
  copies request Windows binary mode, pinned timezone data is narrow, fixtures
  are hermetic, and the active Ctrl-Z PNG test provides hosted behavioral proof.
- Reviewer B — compatibility and product: No findings. Confirmed the changes do
  not skip or mask failures, preserve POSIX behavior, and remain within the
  amended clean-install and Tier 1 Windows boundary.
- Review gate: Passed. Both reviewers require the nine-job hosted retry as the
  remaining acceptance evidence.

### Final hosted-follow-up review

- Trigger: Run `29616839592` reduced the matrix to one identical Windows-only
  test failure caused by text-mode fixture creation, not snapshot behavior.
- Correction: Create exact LF fixture bytes with `write_bytes` and retain the
  strict byte-equality assertion. No runtime code changed.
- Verification: 18 focused tests and all 367 tests passed locally; Python
  compilation and the diff check also passed.
- Reviewer A — correctness and safety: No findings. Confirmed exact source-byte
  construction preserves the fidelity contract without normalization, skips,
  or masking.
- Reviewer B — compatibility and product: No findings. Confirmed the change
  removes only Windows fixture translation and the review record remains
  truthful.
- Review gate: Passed; the owner authorized publication and another complete
  hosted matrix run.

## Documentation updates

- Roadmap: Records the implemented nine-job early guardrail and advances the
  next action to Milestone 1A while preserving later Milestone 4 scope.
- Changelog: Records the early workflow and its explicit exclusions.
- Changelog: Also records the clean-runner and Windows portability corrections
  exposed by the first matrix.
- Architecture/operator docs: No change expected.
- Project/session notes: This review log.
- Documentation verification: Focused workflow/record contract tests passed.

## Publication gate

- Proposed correction files: `agent_console_artifacts.py`, `requirements.txt`,
  `CHANGELOG.md`, eight affected test modules, and this review log.
- Branch and base: `codex/beta-ci-guardrail`; stacked base
  `codex/beta-0-release-contract` while PR #18 is open.
- Commit message: `Add cross-platform CI guardrail`.
- PR title: `Add the early cross-platform CI guardrail`.
- PR summary: Add the read-only nine-job OS/Python matrix, portable syntax and
  full-suite checks, regression contracts, and truthful roadmap/changelog
  records while deferring the remaining Milestone 4 release gates.
- Unresolved risks: None within the approved slice. PR #18 is still open, so
  PR #19 remains stacked until its approved base lands.
- User authorization and scope: The project owner explicitly approved staging
  the six reviewed files, committing, pushing `codex/beta-ci-guardrail`, and
  opening the ready stacked PR on 2026-07-17. The owner explicitly approved
  staging the 12 reviewed correction files, committing them as `Fix
  cross-platform CI failures`, pushing the same branch, and rerunning the
  nine-job matrix on 2026-07-17. After that run isolated one Windows newline
  fixture mismatch, the owner approved the final test-only byte-explicit
  fixture correction, local verification, re-review, push, and another hosted
  matrix run on 2026-07-17.
- Published workflow commit: `1036d5ea9b245086c19003ab582aa5f56f484e55`.
- Ready PR URL: `https://github.com/hazeion/agent-os/pull/19`.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-9 passed, including all nine
  GitHub-hosted OS/Python jobs.
- Potential bugs or untested paths: Native installers, browser automation,
  packaging, self-hosted runners, dependency scanning, branch protection, and
  later Milestone 4 release gates remain intentionally outside this slice.
- Remaining reviewer dissent: None; both reviewers reported no findings in the
  final hosted-follow-up review.
- Compatibility/migration/rollback concerns: No migration. The workflow,
  timezone dependency, binary flags, and test-fixture corrections can be
  reverted through their ordinary commits.
- User decision: Accepted as successful by the project owner on 2026-07-17.
- Next slice authorized: Milestone 1A contract planning is authorized;
  implementation still requires explicit approval of its bounded slice
  contract and test strategy.
