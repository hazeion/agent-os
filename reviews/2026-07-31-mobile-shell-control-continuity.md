# Feature Slice Review: Mobile Shell Control Continuity

Status: Successful
Slice: `mobile-shell-control-continuity`
Date: `2026-07-31`
Review log: `reviews/2026-07-31-mobile-shell-control-continuity.md`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  decisions moving forward.
- Standing approval covers this contract, test strategy, implementation,
  outcome, staging, commit, push, and ready pull request.
- Work remains one reviewed slice at a time, with unrelated user files excluded.

## Slice contract

### Goal

Give phone users the same reachable 44px target for the remaining interactive
shell controls: the Hermes connection control and the navigation drawer's Close
button.

### In scope

- At 640px and below, make the Emerald shell's Hermes connection button at
  least 44px high.
- At the drawer breakpoint, make the Emerald navigation Close button exactly
  44px square without changing its icon.
- Protect both results against the final CSS cascade with a deterministic
  visual contract and record the outcome in the changelog.

### Out of scope

- Redesigning the header, navigation drawer, connection workflow, or Classic
  shell.
- Changing desktop or tablet density, the non-interactive 40px operator avatar,
  or other controls already covered by earlier mobile slices.
- Session-search behavior, Hermes data, Apple notarization, credentials, and
  user-owned `data/projects.json`, `design/`, and `uv.lock`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | At 640px and below, the Emerald Hermes connection button has an effective minimum height of 44px. | Deterministic final-cascade contract | Pass |
| AC-2 | At the drawer breakpoint, the Emerald Close navigation button is 44px square. | Deterministic final-cascade contract | Pass |
| AC-3 | The changes are phone/drawer scoped and do not alter desktop/tablet density or the Close icon. | CSS source-order contract and focused regression suite | Pass |
| AC-4 | Existing search focus, session alignment, hidden-state, mobile layout, and shell accessibility contracts remain green. | Focused UI suites | Pass |
| AC-5 | Two independent adversarial reviewers find no unresolved in-scope regression. | Review record | Pass |

### Constraints and recovery

- Safety: CSS and deterministic test changes only; no data or runtime mutation.
- Compatibility: retain existing 900px drawer and 640px phone breakpoints and
  preserve Classic behavior.
- Rendered behavior: no horizontal stretching; only the two undersized targets
  gain the missing pixels.
- Rollback or recovery: revert the slice commit; no migration.
- Documentation targets: `CHANGELOG.md` and this review log.
- Version-control strategy: branch `codex/mobile-shell-control-continuity` from
  merged `main`; ready PR to `main`.

### Scope discussion and approval

- Recommendation and rationale: close the two explicit exclusions left by the
  earlier mobile-control slices in one presentation-only continuity change.
- Alternatives considered: globally enlarge all buttons (changes density),
  redesign the top bar/drawer (unnecessary scope), or leave 40/42px targets
  beside 44px controls (retains the measured inconsistency).
- User decisions: standing approval for all slices and publication actions.
- Approved at: `2026-07-31` under the recorded process exception.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The final Emerald connection rule is 42px at phone widths. | Parse the final 640px block and require a 44px connection declaration after the 42px competitor. | The intended phone declaration wins by source order and specificity. | Static CSS contract does not measure a browser rectangle. |
| AC-2 | Drawer Close is explicitly 40px square. | Require 44px width, height, and flex basis in the drawer rule. | The visible hit target is square and consistent. | Static CSS contract does not model platform pixel rounding. |
| AC-3 | Broad rules could change larger layouts or the icon. | Assert breakpoint scoping and keep the SVG at 20px. | Density and icon presentation remain bounded. | Does not compare screenshots. |
| AC-4 | Cascade changes can regress nearby focus and responsive contracts. | Run visual, focus, Home, attachment, and workflow UI suites. | Existing deterministic UI promises remain intact. | Live localhost browser testing is unavailable in this environment because the selected browser blocks the local test URL. |
| AC-5 | Small CSS changes can still miss specificity or accessibility interactions. | Two independent read-only adversarial reviews. | Independent correctness and product scrutiny. | Reviewers do not modify files. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| CSS source inspection | macOS, current `main` | Gap confirmed | Drawer Close is 40px square; phone connection control inherits 42px. |
| Existing focused UI contracts | macOS, Python 3.13 | Pass | 47 visual/focus/workflow tests passed; the attempted nonexistent `test_mobile_responsive_ui` module was removed from the corrected command. |
| Home and attachment UI contracts | macOS, Python 3.13 | Pass | 28 tests passed. |
| In-app localhost audit | Codex in-app browser | Unavailable | Browser URL safety policy blocked the isolated loopback test tab; it was closed and temporary data was removed rather than bypassing the boundary. |

### Test discussion and approval

- User questions and decisions: standing approval applies.
- Accepted coverage gaps: this environment cannot provide a new live browser
  rectangle without bypassing the selected browser's safety policy. The slice
  therefore requires an exact final-cascade contract, the existing broad UI
  suites, and two adversarial reviews; no screenshot claim will be made.
- Approved at: `2026-07-31` under the recorded process exception.

## Implementation record

### Changes

- Enlarged only the Emerald drawer Close target from 40px to 44px while
  retaining its existing 20px icon.
- Added a final phone declaration that raises the Emerald Hermes connection
  button from 42px to 44px.
- Added an exact cascade regression contract and a changelog entry.

### Deviations and decisions

- None. The implementation remains inside the approved two-control CSS scope.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_visual_contract.VisualContractTests.test_phone_shell_controls_complete_the_44px_target_contract -v` before implementation | macOS, Python 3.13 | Exit 1, expected baseline | 1 failed | Reproduced the inherited 42px connection target before the CSS change. |
| `python3 -m unittest tests.test_visual_contract tests.test_input_focus_continuity tests.test_home_operations_ui tests.test_agent_console_attachments_ui tests.test_daily_workflow_ui tests.test_frontend_workflow_feedback -v` | macOS, Python 3.13 | Exit 0 | 76 passed | Covers the new cascade contract and established focus, session, shell, Home, attachment, and workflow UI promises. |
| `node --check public/app.js && node --check public/core.js && git diff --check` | macOS, Node/Python checkout | Exit 0 | 3 checks passed | Frontend sources parse and the patch has no whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 scripts/run_unittest_shards.py` | macOS, Python 3.13 | Exit 1 | 912 run; 911 passed; 1 failed; 4 skipped | Sole failure is the pre-existing user-owned `Daily Check` fixture mismatch in `test_only_mentat_project_remains_active_for_v1`; no UI or slice test failed. |

### Rendered or manual behavior

- New live rendering is unavailable under the selected browser's localhost URL
  policy. Static cascade evidence and previously verified surrounding rendered
  behavior are recorded without claiming a new browser measurement.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: uncommitted scoped diff on
  `codex/mobile-shell-control-continuity`; unrelated user files excluded.
- Verification evidence: 76 focused tests passed; full suite had one unrelated
  user-fixture failure among 912 tests; syntax and whitespace checks passed.
- Rendered artifacts: none; accepted coverage gap recorded above.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-01 | P2 | Yes | Exact-selector matching could miss a later, more-specific sizing override for either target. | Yes | Inspect any later rule whose final selector subject is the control and prove synthetic more-specific cases are caught. |
| A-02 | P2 | Yes | The review packet did not clearly distinguish the timing of earlier focused evidence from the latest test-only edit. | Yes | Run and record the complete focused command after test hardening. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-01 | P2 | Yes | The 42px competitor could gain `!important` while the test still certified 44px. | Yes | Reject `!important` in the competitor and winner. |
| B-02 | P3 | No | Verification chronology could be read as overstating post-edit coverage. | Yes | Record the fresh post-hardening 76-test run explicitly. |

### Round 2 reviewers

| ID | Reviewer | Severity | Blocking | Finding and evidence | Disposition |
| --- | --- | --- | --- | --- | --- |
| A2-01 | Correctness and safety | P2 | Yes | An earlier differently selected `!important` sizing rule remained outside the post-winner scan. | Accepted; inventory every subject-targeting sizing rule across the full stylesheet and allow only the known exact rules. |
| B2-01 | Compatibility and product | P2 | Yes | An earlier more-specific sizing rule could win even without `!important` and remain outside the post-winner scan. | Accepted; the same full-stylesheet inventory closes both earlier and later paths. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Later sizing rules were checked only by exact selector. | Unique A finding; B independently confirmed the proposed boundary. | B required checking the final selector subject while ignoring descendants and pseudo-elements. | Accepted. The helper now catches more-specific target rules, covers physical/logical sizing, and proves descendant and pseudo-element rules do not cause false failures. | Hardened deterministic cascade test with positive and negative synthetic cases. |
| `!important` could make the earlier 42px rule win. | Unique B finding within the same cascade-safety root cause. | A's broader finding also required accounting for `!important`. | Accepted. Both the competitor and intended winner must remain free of `!important`. | Added explicit assertions. |
| Verification chronology was ambiguous. | Corroborated. | Both reviewers requested explicit post-hardening evidence. | Accepted. The complete 76-test command was rerun after all Round 1 test changes. | Corrected this record. |
| Only post-winner target rules were inventoried. | Corroborated in Round 2. | A demonstrated an earlier `!important` rule; B demonstrated an earlier higher-specificity rule. | Accepted. The test now inventories every subject-targeting sizing rule in the stylesheet, requires only the three known exact connection rules and one exact Close rule, verifies expected values, and rejects importance. | Replaced one-sided scanning with a full deterministic rule inventory and synthetic important/more-specific cases. |

### Round 3 gate

- Reviewer A: clean; no remaining correctness or safety finding.
- Reviewer B: clean; no remaining compatibility, product, accessibility,
  cascade, or verification finding. Independent focused run: 76 passed; syntax
  and patch checks passed.

### Reverification

- Focused tests after all Round 1 fixes: 76 passed.
- Full suite: 912 run; 911 passed; 1 unrelated user-fixture failure; 4 skipped.
- Syntax/patch checks: 3 passed.
- Round 2 full-inventory fix reverification: 76 focused tests passed; 912 full
  tests ran with 911 passed, the same one unrelated user-fixture failure, and 4
  skipped; syntax and patch checks passed.
- Next review round or gate result: both independent Round 3 gates are clean.

## Documentation updates

- Roadmap: no milestone status change expected; this is beta UI polish.
- Changelog: completed.
- Architecture/operator docs: not applicable.
- Project/session notes: this review log.
- Documentation verification: changelog and review record are included in the
  scoped diff; patch whitespace check passed.

## Publication gate

- Proposed files: `CHANGELOG.md`, `public/styles.css`,
  `tests/test_visual_contract.py`, and this review log.
- Branch and base: `codex/mobile-shell-control-continuity` to `main`.
- Commit message: `Align phone shell controls`.
- PR title: `Align phone shell controls`.
- PR summary: make the remaining interactive phone shell targets consistently
  reachable without changing desktop or tablet density.
- Unresolved risks: live browser rectangle unavailable due the recorded local
  URL safety boundary; deterministic cascade and broad regression evidence are
  used instead.
- User authorization and scope: standing approval recorded above.
- Commit hash: recorded by the resulting Git commit after this review record is
  finalized.
- Ready PR URL: recorded in GitHub publication metadata after the branch is
  pushed.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-5 pass.
- Potential bugs or untested paths: live rendering gap described above.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: no migration; CSS-only rollback.
- User decision: standing approval applies after successful gates.
- Next slice authorized: yes, under the standing approval; focus-border
  continuity is queued next.
