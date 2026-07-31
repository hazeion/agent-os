# Feature Slice Review: Mobile Control Ergonomics

Status: Successful
Slice: `mobile-control-ergonomics`
Date: `2026-07-31`
Review log: `reviews/2026-07-31-mobile-control-ergonomics.md`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  decisions moving forward.
- Standing approval covers this contract, test strategy, implementation,
  outcome, staging, commit, push, and ready pull request.
- Work remains one reviewed slice at a time, with unrelated user files excluded.

## Slice contract

### Goal

Give phone users one consistent, reachable control size across the remaining
compact planner, agent, Console, and Settings controls, while removing the
duplicate wall of theme-choice buttons from the phone Settings flow.

### In scope

- At 640px and below, make the Today project filter and schedule link, Agent
  Console and managed-agent selects, Console prompt, and Settings selects at
  least 44px high.
- Keep the existing compact theme dropdown as the complete phone theme picker.
- Hide only the duplicate visual theme-button grid on phones; retain it on
  larger viewports.
- Add a deterministic visual contract, rendered checks, and changelog entry.

### Out of scope

- Redesigning desktop/tablet density, theme content, or the theme system.
- Changing mobile navigation, calendar scrolling, search focus, or application
  behavior already verified in the audit.
- Adding browser-guided onboarding or changing Hermes data.
- User-owned `data/projects.json` and `design/`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Listed phone controls have an effective height of at least 44px at 390px. | Rendered browser metrics and visual contract | Pass |
| AC-2 | Phone Settings keeps one complete theme dropdown and does not render the duplicate theme-button grid. | Rendered browser check and visual contract | Pass |
| AC-3 | At 768px and 1440px, the theme preview grid remains visible and the existing layout is unchanged. | Rendered browser checks | Pass |
| AC-4 | Primary views retain contained scrolling, no page-wide overflow, no visible `[hidden]` elements, and correct search focus. | Cross-view rendered audit | Pass |
| AC-5 | Two independent adversarial reviewers find no unresolved in-scope regression. | Review record | Pass |

### Constraints and recovery

- Safety: presentation-only CSS; no data, Hermes, or credential behavior.
- Compatibility: preserve the existing theme select and all desktop/tablet
  controls; the breakpoint matches the existing phone treatment.
- Rendered behavior: do not stretch compact actions horizontally or alter
  intentional contained project/calendar scrolling.
- Rollback or recovery: revert the slice commit; no migration.
- Documentation targets: changelog and this review log only.
- Version-control strategy: branch `codex/mobile-control-ergonomics` from
  `main`; ready PR to `main`.

### Scope discussion and approval

- Recommendation and rationale: fix the measured sub-44px controls together at
  the existing phone breakpoint, and remove only the duplicated mobile theme
  surface while keeping full functionality through the select.
- Alternatives considered: globally increase all controls (unnecessarily
  changes desktop density); remove the dropdown (loses the shortest phone
  workflow); keep both theme surfaces (retains roughly 650px of duplicate phone
  scrolling).
- User decisions: standing approval for all slices and publication actions.
- Approved at: `2026-07-31` under the recorded process exception.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | At 390px, measured controls range from 36px to 40px while adjacent mobile targets are 44px. | CSS contract plus computed browser rectangles on affected views. | The final cascade wins at the rendered breakpoint. | Chrome rendering is the live platform sample. |
| AC-2 | Settings renders one dropdown plus sixteen theme buttons on a 390px phone. | Assert select remains; grid is hidden; inspect rendered Settings. | Full theme choice remains without redundant controls. | Does not measure subjective preference. |
| AC-3 | Visual theme buttons are useful on larger screens. | Inspect 768px and 1440px computed visibility. | Phone-only rule does not leak upward. | Samples exact breakpoints. |
| AC-4 | Earlier cross-view audit found no page-wide overflow and correct outside-only search focus. | Repeat phone/tablet/desktop DOM metrics after the change. | The slice does not regress established layout/focus behavior. | Intentional contained rails remain scrollable. |
| AC-5 | CSS specificity and breakpoint changes can affect unrelated surfaces. | Two independent read-only adversarial reviews. | Independent correctness, accessibility, and product scrutiny. | Reviewers do not edit files. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Live cross-view audit | Chrome, local main, 390/768/1440px | Gap reproduced | Today filter/link 36px; agent selects 38px; Settings selects 40px. |
| Phone Settings inspection | Chrome, 390px | Gap reproduced | Dropdown and sixteen duplicate theme buttons rendered. |
| Search focus inspection | Chrome, 390px | Pass | Outer shell has the only outline; inner search input has none. |
| Navigation/calendar/projects audit | Chrome, 390px | Pass | Drawer settles fully off-canvas, project rail/calendar scroll stay contained, zero visible hidden elements. |

### Test discussion and approval

- User questions and decisions: standing approval applies.
- Accepted coverage gaps: exact rendered verification samples Chrome at the
  requested responsive breakpoints; deterministic contracts protect the CSS.
- Approved at: `2026-07-31` under the recorded process exception.

## Implementation record

### Changes

- Added a final phone-only rule with enough specificity to override the compact
  desktop component sizes and establish 44px effective targets.
- Hidden the duplicate Settings theme preview grid only at the phone breakpoint;
  the full theme dropdown remains.
- Added a deterministic contract and changelog entry.

### Deviations and decisions

- Round 1 revealed that the initial selectors were scoped only to Emerald even
  though Classic is a supported phone layout. The implementation was corrected
  to be shell-neutral, and the static contract was strengthened to parse the
  exact phone media rule and grouped declarations.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_visual_contract tests.test_input_focus_continuity -v` | macOS, Python 3.13 | Exit 0 | 32 passed | Includes new phone-control contract and existing focus/session alignment contracts. |
| `git diff --check` | local worktree | Exit 0 | Pass | No whitespace errors. |
| `node --check public/app.js && node --check public/core.js` | local Node | Exit 0 | 2 passed | No JavaScript changes; confirms the served UI source remains syntactically valid. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests` | macOS, Python 3.13 | Exit 1 | 909 run; 904 passed; 1 failed; 4 skipped | Sole failure is the pre-existing user-owned `Daily Check` seed mismatch in `test_only_mentat_project_remains_active_for_v1`; this slice does not edit `data/projects.json`. |

### Rendered or manual behavior

- Chrome at 390px: affected Today/Console controls and managed-agent selectors
  all compute to 44px; session selector/search remain matched at 44px.
- Chrome at 390px in Classic: Today filter, schedule link, all Agent Console
  controls, managed-agent selectors, and session selector/search outer shell all
  compute to 44px; document width remains exactly 390px.
- Chrome at 390px: Settings theme/layout/contrast selects compute to 44px;
  theme dropdown remains visible and the sixteen-button theme grid computes to
  `display: none` with zero size.
- Chrome at 390px in Classic: Settings selectors also compute to 44px and the
  theme grid remains `display: none` with zero size. The session search inner
  input remains borderless with no outline or shadow while its outer shell owns
  the 44px control surface.
- Chrome at 768px and 1440px: theme grid remains `display: grid` with all
  sixteen buttons visible; no page-wide overflow.
- Chrome at 1440px: session selector and outer search shell remain aligned at
  40px; focused outer shell owns the 2px outline while the inner input has no
  border, outline, or shadow.
- Rechecked mobile drawer transition, project rail, calendar week scroller,
  primary views, and hidden state: intended scrolling stays contained, page
  width stays bounded, and zero `[hidden]` elements render visibly.

## Adversarial review

### Round 1 packet

- Diff reviewed: current uncommitted four-file slice.
- Verification evidence: 32 focused passes, full-suite result, and rendered
  390/768/1440px metrics recorded above.
- Rendered artifacts: live Chrome inspection; no tracked screenshots containing
  operator data.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P2 | Yes | New rules used `data-ui-shell='emerald'`; Classic restored sub-44px controls and the theme grid. | Yes | Make phone rules shell-neutral and verify both layouts. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | P1 | Yes | Supported Classic layout bypassed both user-visible changes. | Yes | Make the rules shell-neutral and render-test Classic. |
| B-2 | P2 | Yes | Static contract checked loose strings and could not prove the selectors shared the 640px rule. | Yes | Parse the exact media/grouped rules and add Classic evidence. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Emerald-only selectors | Corroborated | Both reviewers independently reproduced the same supported-state failure. | Accepted; directly contradicts AC-1/AC-2. | Removed shell gating from both phone rules. |
| Weak static contract | Corroborated test-risk evidence | Safety reviewer also noted the test could not catch Classic bypass; product reviewer supplied concrete false-positive cases. | Accepted; inside the agreed verification scope. | Test now parses the exact 640px grouped target and preview rules and rejects shell gating. |

### Reverification

- Focused tests: 32 passed after each correction.
- Full suite: 909 run; 904 passed; 1 failed; 4 skipped after correction. The
  sole failure remains the unrelated user-owned `Daily Check` fixture mismatch.
- Rendered checks: Classic and Emerald both satisfy the phone targets; Emerald
  was restored afterward. Tablet and desktop theme previews remain intact.
- Round 2 product review was clean. Safety review found that the preview-grid
  regex could still false-pass if the rule were shell-gated or moved outside
  the phone media block. The contract now compares the complete final mobile
  block exactly, so either regression fails deterministically.
- Round 3 safety and product reviews were both clean with no remaining blocking
  findings. The exact-tail contract also catches breakpoint drift, selector
  loss, and later overrides.

### Round 3 final review

| Reviewer | Result | Final assessment |
| --- | --- | --- |
| Correctness and safety | Clean | Shell-neutral CSS is narrowly scoped; hidden duplicate buttons leave layout, keyboard order, and the accessibility tree while the native select remains. |
| Compatibility and product | Clean | Phone sizing and theme continuity are protected without tablet/desktop or focus regressions. |

## Documentation updates

- Changelog: updated and verified.
- Roadmap: no milestone status change; this is beta UI polish.
- Architecture/operator docs: not applicable.
- Project/session notes: this review log.

## Publication gate

- Proposed files: `CHANGELOG.md`, `public/styles.css`,
  `tests/test_visual_contract.py`, and this review log.
- Branch and base: `codex/mobile-control-ergonomics` → `main`.
- Commit message: `Improve phone control ergonomics`.
- PR title: `Improve phone control ergonomics`.
- PR summary: unify phone target heights and remove duplicate mobile theme
  controls while retaining tablet/desktop previews.
- Unresolved risks: none in scope; the unrelated user-owned fixture mismatch is
  excluded from this slice.
- User authorization and scope: standing approval recorded above.
- Commit hash: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-5 pass.
- Potential bugs or untested paths: platform-native rendering outside the
  sampled Chrome breakpoints remains covered by deterministic CSS contracts,
  not a second rendering engine.
- Remaining reviewer dissent: none after the Round 3 re-review.
- Compatibility/migration/rollback concerns: no migration; CSS-only rollback.
- User decision: standing approval applies after successful gates.
- Next slice authorized: Yes, under the user's standing approval.
