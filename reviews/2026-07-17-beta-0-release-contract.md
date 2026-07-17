# Feature Slice Review: Close the Public-Beta Release Contract

Status: Paused
Slice: `beta-0-release-contract`
Date: `2026-07-17`
Review log: `reviews/2026-07-17-beta-0-release-contract.md`

## Slice contract

### Goal

Resolve every remaining Milestone 0 owner decision and establish one
unambiguous release target for later implementation slices.

### In scope

- Approve the audience, platforms, Python versions, update model, telemetry
  policy, version, severity policy, and feedback policy.
- Require signed native installers for macOS and Windows while retaining
  `pipx` as an advanced/fallback channel and the Linux preview path.
- Update downstream packaging, CI, release-candidate, and beta exit
  requirements without selecting installer tooling prematurely.
- Mark Milestone 0 complete and preserve the next-slice order: early CI, then
  Milestone 1A.

### Out of scope

- Building installers, packages, `pyproject.toml`, or GitHub Actions.
- Changing runtime, UI, data storage, or Hermes behavior.
- Selecting exact installer formats or implementation frameworks.
- Beginning Milestone 1A.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Every previously pending Milestone 0 decision is recorded as approved on 2026-07-17 while preserving the 2026-07-16 dates for the license and remote contract. | Focused contract tests and roadmap inspection. | Passed |
| AC-2 | The supported platform and Python contract is unambiguous. | Focused contract tests. | Passed |
| AC-3 | Native installer, signing, `pipx`, update, telemetry, and version commitments are unambiguous. | Focused positive and negative contract assertions. | Passed |
| AC-4 | Installer requirements are consistent across Milestones 3, 4, 6, and 8 and the definition of done. | Cross-section contract test and inspection. | Passed |
| AC-5 | The P0-P3 severity definitions and feedback policy are approved as written. | Focused contract test. | Passed |
| AC-6 | Documentation distinguishes future commitments from implemented behavior. | README contract assertion and inspection. | Passed |
| AC-7 | Tests reject stale native-installer deferral and pending-decision language. | Negative contract assertions. | Passed |
| AC-8 | The roadmap orders early CI before Milestone 1A. | Focused ordering assertion. | Passed |
| AC-9 | No runtime, UI, configuration, fixture, or operator-data behavior changes. | Changed-file and raw-diff inspection. | Passed |

### Constraints and recovery

- Safety: Do not change runtime authority, credentials, operator data, or
  Hermes behavior. Do not claim that planned artifacts already exist.
- Compatibility: Current source-checkout behavior remains unchanged. Later
  installer and `pipx` work must preserve the loopback-only product boundary.
- Rendered behavior: Not applicable; this slice has no UI changes.
- Rollback or recovery: Revert the documentation and contract-test changes;
  there is no data migration.
- Documentation targets: `ROAD_TO_BETA.md`, `README.md`, `CHANGELOG.md`, and
  this review log.
- Version-control strategy: Branch `codex/beta-0-release-contract` from merged
  `main`; request separate approval before staging, committing, pushing, or
  opening a ready pull request.

### Scope discussion and approval

- Recommendation and rationale: Close the decision contract before CI and
  data-root implementation so later slices share one release target.
- Alternatives considered: Keep native installers deferred or allow unsigned
  installers. Both reduce release complexity but fail to provide the trusted
  tier-one installation experience selected by the owner.
- User decisions: Native installers are required for macOS and Windows;
  macOS is signed and notarized, Windows is signed, `pipx` remains supported,
  and the existing severity and feedback proposals are approved.
- Approved at: Explicitly approved by the project owner on 2026-07-17.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1, AC-2 | Milestone 0 is in progress and choices remain pending. | Roadmap section assertions. | The release contract and support matrix are recorded as approved. | Does not exercise platforms. |
| AC-3, AC-4 | Native installers are deferred and downstream milestones cover only `pipx`. | Positive and negative cross-section assertions. | Distribution commitments are consistent and stale deferral is absent. | Does not build or sign artifacts. |
| AC-5 | Severity and feedback language is recommended but pending. | Policy assertions scoped to Milestone 0. | The approved release-blocking and report-handling contract is retained. | Does not run a support process. |
| AC-6 | Docs do not describe the newly selected native-installer target. | README truthfulness assertions and manual inspection. | Planned and current behavior cannot be easily conflated. | No rendered check because no UI changes. |
| AC-7 | Existing tests protect the prior pending state. | Add tests first and capture expected failures. | The new checks observe the actual pre-change gap. | Documentation contract tests remain intentionally text-based. |
| AC-8 | Next actions still begin by finishing Milestone 0. | Ordering and stale-action assertions. | Early CI is next and Milestone 1A follows. | Does not add CI. |
| AC-9 | Runtime is outside the approved scope. | Changed-file and raw-diff inspection; full regression suite. | Only approved records/tests changed and existing behavior remains green. | Cannot prove behavior on platforms not executed locally. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest tests.test_beta_contract -v` | macOS, local Python | Pass | 7 passed before adding the new contract assertions. |
| `python3 -m unittest discover -s tests -v` | macOS, local Python | Pass | 356 passed; existing history-permission warning observed. |
| `python3 -m py_compile server.py` and JavaScript syntax checks | macOS, local Python/Node | Pass | All syntax checks passed. |
| `git status --short --branch` and `git diff --check` | Local worktree | Pass | Worktree was clean on the merged PR #17 head. |
| `python3 -m unittest tests.test_beta_contract -v` after adding approved assertions | macOS, local Python | Expected fail | 6 passed and 4 failed against the old documents, demonstrating the approved contract gap. |

### Test discussion and approval

- User questions and decisions: The owner approved focused documentation
  contract tests, full regression coverage, syntax/diff checks, and targeted
  contradiction searches.
- Accepted coverage gaps: This slice does not build, sign, notarize, install,
  upgrade, or uninstall artifacts; does not claim cross-platform runtime
  evidence; and requires no browser check because it changes no UI.
- Approved at: Explicitly approved by the project owner on 2026-07-17.

## Implementation record

### Changes

- Added the focused contract checks first. Against the pre-change documents,
  6 tests passed and 4 failed in the expected completion, native-channel,
  severity/feedback, and truthful-status areas.
- Updated the release contract and downstream milestones to reflect the
  approved decisions without implementing packaging, CI, or runtime behavior.
- Updated the README and changelog with truthful current-versus-future status.

### Deviations and decisions

- AC-1 is recorded as applying the 2026-07-17 date to the decisions that were
  pending when this slice began. The already approved MIT and remote-contract
  decisions retain their accurate 2026-07-16 dates rather than being
  retroactively redated.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_beta_contract -v` | macOS, local Python | Exit 0 | 10 passed, 0 failed, 0 skipped | Focused release-contract checks passed. |
| `python3 -m py_compile server.py` | macOS, local Python | Exit 0 | Not applicable | Existing Python entry point compiles. |
| `node --check public/core.js` and `node --check public/app.js` | macOS, local Node | Exit 0 | Not applicable | Existing JavaScript entry points parse. |
| `git diff --check` | Local worktree | Exit 0 | Not applicable | No whitespace errors. |
| Targeted contradiction search | Approved docs and tests | No active-doc matches | Not applicable | No pending Milestone 0 or deferred-native-installer language remains in the active roadmap or README. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS, local Python | Exit 0 | 359 passed, 0 failed, 0 skipped | Existing history-permission warning observed; no regression failure. |

### Rendered or manual behavior

- Not applicable; this slice changes no rendered UI.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Uncommitted working-tree diff against `origin/main` on
  `codex/beta-0-release-contract`; five approved slice files.
- Verification evidence: Focused 10/10 and full 359/359 tests passed; Python,
  JavaScript, diff, and contradiction checks passed.
- Rendered artifacts: Not applicable; no UI files changed.

Independent reviewer findings are pending.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P2 | Yes | `README.md` Quick Start says only Python 3 although the approved range is 3.11-3.13, allowing unsupported expectations. | Yes | State the exact range and protect it with a README assertion. |
| A-2 | P2 | Yes | `tests/test_beta_contract.py` checks exact signing language only globally and generic native-installer text per milestone, so a downstream milestone could weaken signing while tests pass. | Yes | Bind macOS signing/notarization, Windows signing, and `pipx` to every applicable section. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | P2 | Yes | Section checks accept generic native-installer text, and the stale-language assertion would not match the former case and table punctuation. | Yes | Use section-specific commitments and normalized stale-language checks. |
| B-2 | P3 | No | Quick Start's generic Python 3 prerequisite is broader than the approved 3.11-3.13 range. | Yes | State the approved range in Quick Start. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Quick Start Python range | Corroborated; severity/blocking classification differs, evidence and correction agree | No clarification needed; both reviewers supplied the same source and impact. | Accepted as an in-scope truthful-documentation correction. | Quick Start now says Python 3.11 through 3.13; focused test protects it. |
| Downstream signing and stale-language coverage | Corroborated | No clarification needed; both reviewers demonstrated a weakening edit that would pass. | Accepted as an in-scope test-adequacy correction. | Milestones use explicit signing language; tests bind signing and `pipx` to each section and normalize stale-language checks. |

### Reverification

- Focused tests: `python3 -m unittest tests.test_beta_contract -v` passed 10/10
  after Round 1 fixes.
- Full suite: `python3 -m unittest discover -s tests -v` passed 359/359 after
  Round 1 fixes; the existing history-permission warning was observed.
- Syntax, diff, and contradiction checks passed after Round 1 fixes.
- Next review round or gate result: Both reviewers receive the complete
  refreshed diff and current evidence for Round 2.

### Round 2 packet

- Diff/commit reviewed: Complete uncommitted working-tree diff against
  `origin/main`, including both Round 1 corrections and this review record.
- Verification evidence: Focused 10/10 and full 359/359 tests passed after
  fixes; Python, JavaScript, diff, and active-doc contradiction checks passed.
- Rendered artifacts: Not applicable; no UI files changed.

### Round 2 review and reconciliation

- Reviewer A: No findings; both Round 1 findings were resolved and the complete
  refreshed slice introduced no finding under its review.
- Reviewer B: One P2 blocking test-adequacy finding. The focused feedback-policy
  test did not protect the approved ordinary-report route, private security
  route, or link to explicit deferred-work non-goals. Reviewer B confirmed the
  Round 1 fixes were resolved.
- Classification: Unique finding in the independent Round 2 pass.
- Peer critique: Reviewer A independently reviewed Reviewer B's exact evidence,
  corroborated it, and revised its position to a P2 blocking finding because
  AC-5 and the approved strategy promise protection for issue/security routing.
- Disposition: Accepted as in scope. Added scoped assertions for both report
  routes, the deferred-work link, and the core explicit beta non-goals.

### Round 3 packet

- Diff/commit reviewed: Complete uncommitted working-tree diff against
  `origin/main`, including all accepted Round 1 and Round 2 corrections and the
  current review record.
- Verification evidence: Focused 10/10 and full 359/359 tests passed after the
  Round 2 fix; Python, JavaScript, diff, and active-doc contradiction checks
  passed.
- Rendered artifacts: Not applicable; no UI files changed.

### Round 3 final review

- Reviewer A: No findings. All prior findings are resolved; the complete slice
  introduced no new correctness, safety, compatibility, regression,
  documentation-truthfulness, or test-adequacy issue.
- Reviewer B: No findings. All prior findings are resolved; the complete slice
  is consistent with the approved contract and introduces no new issue.
- Gate result: Passed after three review rounds with no unresolved blocking or
  nonblocking finding and no surviving reviewer dissent.

## Documentation updates

- Roadmap: Milestone 0 is complete; the approved distribution, support, and
  feedback contract is recorded; downstream installer gates and next actions
  are aligned.
- Changelog: Recorded the approved contract and made clear that installer
  implementation remains future work.
- Architecture/operator docs: README now records the approved target and says
  source checkout remains the current path; architecture behavior is unchanged.
- Project/session notes: This review log is the persistent slice record.
- Documentation verification: Focused contract tests, cross-document
  inspection, targeted contradiction search, and `git diff --check` passed.

## Publication gate

- Proposed files: `ROAD_TO_BETA.md`, `README.md`, `CHANGELOG.md`,
  `tests/test_beta_contract.py`, and this review log.
- Branch and base: `codex/beta-0-release-contract` from merged `main`.
- Commit message: `Close Milestone 0 beta contract`.
- PR title: `Close the public-beta release contract`.
- PR summary: Approve the remaining release, support, severity, and feedback
  decisions; require signed native installers with a supported `pipx` path;
  align downstream milestones; and add focused contract regression coverage.
- Unresolved risks: Installer implementation, signing infrastructure, and
  cross-platform operation remain future work by contract. The early CI
  guardrail and Milestone 1A are separate unstarted slices.
- User authorization and scope: On 2026-07-17 the project owner approved
  staging exactly the five proposed files, committing with the approved
  message, pushing the approved branch, and opening a ready pull request.
  Publication initially paused before staging because `gh auth status`
  reported that the active `hazeion` token is invalid. The owner then
  explicitly directed use of the connected GitHub plugin instead. This is a
  process exception to the publish helper's GitHub CLI prerequisite: local Git
  remains responsible for the approved commit and push, while the connected
  plugin verifies repository access and opens the ready pull request.
- Commit hash: To be reported in the outcome review after publication.
- Ready PR URL: To be reported in the outcome review after publication.

## Outcome review

- Classification: Paused.
- Acceptance criteria summary: AC-1 through AC-9 pass locally; publication and
  final user outcome acceptance remain pending.
- Potential bugs or untested paths: Native installer and cross-platform paths
  are intentionally unimplemented and untested in this slice.
- Remaining reviewer dissent: None after the Round 3 full-slice review.
- Compatibility/migration/rollback concerns: Documentation/test-only slice;
  no migration.
- User decision: Pending.
- Next slice authorized: No
