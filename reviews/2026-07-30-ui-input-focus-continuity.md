# Feature Slice Review: Input and status continuity

Status: Publication authorized
Slice: `ui-input-focus-continuity`
Date: `2026-07-30`
Review log: `reviews/2026-07-30-ui-input-focus-continuity.md`

## Slice contract

### Goal

Search and text-entry controls use consistent sizing and a single inner focus
highlight, while Agent Console status appears as lightweight inline information.

### In scope

- Match the Session History search control's visible height to the adjacent
  session selector.
- Remove focused styling from outer search and composite text-entry wrappers.
- Apply one visible focus treatment to the actual editable input or textarea.
- Audit search fields and composite text-entry controls across Home, Agents,
  Tasks, Notes, Context Packs, Agent Creator, and Settings.
- Preserve control-level focus treatment for selects and other controls without
  an inner editable field.
- Render Agent Console status as a green dot and text without a bordered,
  rounded, or filled container.
- Verify desktop and narrow Emerald and Classic layouts.

### Out of scope

- Remote session-search behavior or API changes.
- Cron job descriptions or inventory contract changes.
- Button, link, dropdown, and other non-text focus redesigns.
- Broader visual redesigns.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Session selector and session search have matching visual heights. | Focused DOM/CSS contract plus rendered desktop and narrow measurements. | Pass |
| AC-2 | Focusing any search field produces exactly one highlight around its editable input. | Focus-state contract tests and rendered keyboard-focus inspection. | Pass |
| AC-3 | Composite text-entry wrappers retain their normal border and do not gain a focus ring. | CSS negative assertion and rendered focus inspection. | Pass |
| AC-4 | Standalone text fields and textareas retain one clear, consistent focus state. | Cross-page CSS audit, focused tests, and rendered keyboard inspection. | Pass |
| AC-5 | Agent Console status remains readable and accessible without a box-like container. | DOM/CSS contract and rendered desktop/narrow inspection. | Pass |
| AC-6 | Desktop and narrow layouts remain aligned without stretched action controls. | Browser smoke at representative widths in Emerald and Classic. | Pass |
| AC-7 | Focused checks, full suite, and two independent adversarial reviews pass. | Verification and review records below. | Qualified: reviews clean and focused checks pass; two unrelated local-state full-suite failures require user acceptance. |

### Constraints and recovery

- Safety: Preserve visible keyboard focus and existing live-region semantics.
- Compatibility: Keep Emerald and Classic themes and responsive layouts working.
- Rendered behavior: One focus indication per editable control; status remains
  visually lightweight beside the compact action group.
- Rollback or recovery: Revert the slice's CSS/markup/test changes; no data
  migration or persistent user-state change is involved.
- Documentation targets: `CHANGELOG.md` and this review log; architecture only
  if implementation changes a documented UI contract.
- Version-control strategy: Branch `codex/ui-input-focus-continuity` from
  `main`; exclude the user's modified `data/projects.json` and untracked
  `design/` directory.
- Expected PR base: `main`.

### Scope discussion and approval

- Recommendation and rationale: Keep the visible UI continuity work in one
  Mentat-only slice; handle remote search resilience and cron descriptions as
  later data-contract slices.
- Alternatives considered: Combine all requested behavior in one cross-system
  change; rejected because it would mix independent UI, privacy, and remote API
  risks.
- User decisions: Approved matching search/selector sizing, inner-input-only
  focus, cross-page text-entry audit, and plain Agent Console status.
- Approved at: 2026-07-30 conversation.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Screenshot shows unequal control heights. | Behavioral DOM/CSS contract plus rendered height measurements at desktop and narrow widths. | The adjacent controls share one visible height. | Chromium measurements do not capture every native select difference in Safari or Firefox. |
| AC-2 | Emerald wrapper and input both highlight. | Focus each search input and compare computed wrapper/input styles before and after focus. | Exactly the editable input gains the visible focus treatment. | Browser theme rendering may vary slightly while retaining the same CSS contract. |
| AC-3 | `.search-shell:focus-within` paints the wrapper. | Negative CSS contract for focused wrappers plus rendered focus inspection. | Composite wrappers retain their ordinary border and shadow. | Does not redesign non-search composite controls outside the agreed audit. |
| AC-4 | Focus rules vary across text-entry controls. | Cross-page source audit, behavioral contract tests, and keyboard inspection of representative standalone inputs/textareas. | Editable controls retain one clear focus state without removing accessibility feedback. | Exhaustive native browser/OS combinations are not available locally. |
| AC-5 | Agent Console status has a bordered filled container. | DOM/live-region assertions, CSS contract, and rendered computed-style inspection. | Dot/text semantics remain while border, background, radius, and container padding are absent. | Does not alter status wording or action behavior. |
| AC-6 | Responsive rendered behavior is not yet verified. | Emerald and Classic checks at 1440, 768, and 390 pixels. | Layout remains aligned and compact without stretched action controls. | Chromium-only rendered coverage accepted by the user. |
| AC-7 | Slice has not been implemented or reviewed. | Focused suites, JavaScript syntax check, complete unit suite, and two independent adversarial reviews. | Detects scoped and broad regressions and satisfies the review gate. | Platform-specific skips remain documented if present. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Screenshot inspection | macOS, Emerald shell | Fail | Unequal Session History controls, nested focus rings, and boxed Agent Console status observed. |
| Source inspection | Current `main` baseline | Fail | Emerald `.search-shell:focus-within` adds an outer ring; status CSS supplies a container. |
| `python3 -m unittest tests.test_input_focus_continuity -v` | macOS, Python 3.13 | Expected fail | 4 tests failed before implementation and directly demonstrated the agreed gaps. |

### Test discussion and approval

- User questions and decisions: User approved the proposed behavioral,
  accessibility, responsive, regression, full-suite, and two-reviewer strategy.
- Accepted coverage gaps: Rendered checks use Chromium; minor native
  Safari/Firefox rendering differences are not directly measured.
- Approved at: 2026-07-30 conversation.

## Implementation record

### Changes

- Added one shared height variable for the Session History selector and search
  shell, with 38px Classic, 40px Emerald, and 44px narrow values.
- Removed Emerald's outer `.search-shell:focus-within` treatment.
- Added one final focus contract for editable input types and textareas, with
  explicit resets for task editor, Console prompt, and workspace-search fields.
- Removed the Emerald status container's fill, border, radius, padding, and
  flex growth while preserving the dot, text, and live state rendering.
- Kept long runtime status labels inside their shrinking text item with
  ellipsis, without clipping the presence indicator or reintroducing a box.
- Added focused regression coverage for every search input, shared control
  sizing, editable focus visibility, plain Agent Console status, and long
  narrow-layout status containment.

### Deviations and decisions

- Reviewer B identified that the initial plain-status CSS could allow a long
  supported runtime label to spill toward sibling actions on narrow screens.
  The text item now establishes its own shrinking ellipsis box while the parent
  remains overflow-visible so the working indicator's aura is not clipped.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_input_focus_continuity -v` | macOS, Python 3.13 | Exit 0 | 5 passed | New behavior contracts. |
| `python3 -m unittest tests.test_input_focus_continuity tests.test_visual_contract tests.test_home_operations_ui tests.test_agent_console_runtime_switch_ui -v` | macOS, Python 3.13 | Exit 0 | 53 passed | Scoped UI, Home, Console, and long-status containment coverage after review fix. |
| `node --check public/app.js` and `node --check public/core.js` | macOS, Node.js | Exit 0 | 2 passed | JavaScript syntax unchanged and valid. |
| `git diff --check` | macOS, git | Exit 0 | Pass | Patch hygiene passed. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` before review fix | macOS, Python 3.13 | Exit 1 | 894 passed, 2 failed, 4 skipped | Both failures are outside this slice: the user's existing `data/projects.json` adds `Daily Check`, which violates the seed-fixture assertion, and the selected remote Hermes state causes the local-cron fixture to observe zero jobs. |
| `python3 -m unittest discover -s tests -v` after review fix | macOS, Python 3.13 | Exit 1 | 895 passed, 2 failed, 4 skipped | The new containment test passes. The same two unrelated local-state failures remain; no production Python or data file is changed by this slice. |

### Rendered or manual behavior

- In-app Chromium at 1440x1000, 768x900, and 390x844.
- Emerald Session controls measured 40/40px at desktop and tablet and 44/44px
  at mobile; Classic measured 38/38px desktop and 44/44px mobile.
- Global, Session, Notes, and Agent Creator search wrappers retained identical
  border, shadow, and no-outline styles while focused inputs gained one 2px
  outline.
- Agent Console status computed to transparent background, no border, no
  radius, no padding, and no shadow while retaining the green dot and `Ready`.
- After the review correction, a 390x844 computed-style check confirmed the
  status text is a shrinkable block with hidden overflow and ellipsis while its
  parent remains transparent, borderless, and overflow-visible. The status row
  and transcript reported no horizontal overflow.
- Emerald and Classic produced zero horizontal overflow at measured widths.
- No browser console errors were reported, and the saved shell was restored to
  Emerald after Classic verification.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Uncommitted branch diff for `CHANGELOG.md`,
  `public/styles.css`, `tests/test_input_focus_continuity.py`, and this review
  log. The user's `data/projects.json` and `design/` were explicitly excluded.
- Verification evidence: 52 focused checks passed; JavaScript syntax and patch
  hygiene passed; complete suite recorded two unrelated local-state failures.
- Rendered artifacts: Emerald and Classic at 1440, 768, and 390 pixels, with
  computed focus, control-height, status-container, and overflow checks.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| R1-A1 | Low | No | Review log still contained stale approval and outcome placeholders. | Yes | Complete the review and outcome record before publication. |
| R1-A2 | Low | No | Structural tests do not independently prove the final computed cascade. | Yes | Retain the documented rendered Chromium evidence. |
| R1-A3 | Low | No | Two complete-suite failures come from user/runtime state rather than this patch. | No | Keep AC-7 qualified and disclose the exceptions. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| R1-B1 | Medium | Yes | Long supported runtime labels could spill toward sibling actions because the now-unboxed parent allowed overflow and the inline text did not establish a shrinking ellipsis box. | Yes | Make the status text a bounded shrinking block and verify the longest-state layout at 390px. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Long status containment | Unique to Reviewer B, then corroborated by Reviewer A | Reviewer A confirmed the finding and recommended child-only containment so the working-dot aura remains visible. | Accepted. The text child owns truncation; the parent remains overflow-visible. | Added block/min/max-width/overflow declarations and a regression test. |
| Stale review record | Unique to Reviewer A, then corroborated by Reviewer B | Reviewer B confirmed the record must be completed before publication. | Accepted. This section and Outcome review now reflect both rounds and current evidence. | Documentation only. |
| Structural-test limitation | Reviewer A; consistent with Reviewer B's assessment | Both reviewers accepted rendered inspection as the behavioral complement. | Accepted as a documented limitation; no additional harness is warranted in this slice. | None. |
| Full-suite local-state failures | Corroborated by both reviewers | Both reviewers agreed they do not indicate an in-scope regression, but AC-7 cannot be called an unconditional pass. | Disclosed as qualified evidence for explicit user acceptance at the publication gate. | None; user data and connection state were preserved. |

### Reverification

- Focused tests: 53 passed after the containment correction.
- Full suite: 895 passed, 2 unrelated local-state failures, 4 platform skips.
- Rendered correction: 390px status text computed as a shrinkable ellipsis box;
  status row and transcript had no horizontal overflow.
- Round 2: Both reviewers confirmed the blocking overflow finding is resolved
  and reported no remaining substantive findings. The only remaining task was
  completion of this publication record.

## Documentation updates

- Roadmap: Not applicable unless implementation reveals a roadmap contract.
- Changelog: Updated the current release notes with focus, sizing, and status
  continuity changes.
- Architecture/operator docs: Not applicable; no capability, mutation, data,
  or operator contract changed.
- Project/session notes: This review log.
- Documentation verification: Both reviewers inspected the changelog and
  review record. Their stale-record finding is resolved by this final update.

## Publication gate

- Proposed files:
  - `CHANGELOG.md`
  - `public/styles.css`
  - `tests/test_input_focus_continuity.py`
  - `reviews/2026-07-30-ui-input-focus-continuity.md`
- Explicit exclusions:
  - User-modified `data/projects.json`
  - User-owned untracked `design/`
- Branch and base: `codex/ui-input-focus-continuity` → `main`.
- Commit message: `Unify text input focus and console status styling`
- PR title: `Unify text-entry focus and Agent Console status`
- PR summary:
  - Match Session History search and selector heights across themes and
    responsive widths.
  - Put keyboard focus on editable inputs instead of composite wrappers.
  - Render Agent Console status as plain dot-and-text with safe narrow
    truncation.
  - Add focused contracts and document rendered cross-theme verification.
- Unresolved risks:
  - Rendered checks are Chromium-only; minor native Safari/Firefox differences
    are not directly measured.
  - The complete suite has two disclosed local-state failures unrelated to the
    slice; all 53 focused checks and both substantive reviews are clean.
- User authorization and scope: On 2026-07-30, the user explicitly approved
  staging the four proposed files, committing with the proposed message,
  pushing `codex/ui-input-focus-continuity`, and opening the ready PR against
  `main`. `data/projects.json` and `design/` remain excluded.
- Commit hash: None.
- Ready PR URL: None.

## Outcome review

- Classification: Awaiting publication approval.
- Acceptance criteria summary: AC-1 through AC-6 pass. AC-7 is qualified
  because the complete suite reproduces two unrelated local-state failures;
  focused verification and both adversarial reviews are clean.
- Potential bugs or untested paths: Native Safari and Firefox rendering are not
  directly measured. The longest supported runtime status is protected by CSS
  contract and narrow computed-layout evidence.
- Remaining reviewer dissent: None on the substantive change. Both reviewers
  require transparent acceptance of the full-suite exceptions.
- Compatibility/migration/rollback concerns: No migration or persistent state
  change. Reverting the four proposed files fully rolls back the slice.
- User decision: Exact staging, commit, push, and ready-PR publication approved
  on 2026-07-30.
- Next slice authorized: Broad follow-on approval was given, but work will not
  begin until this slice's publication and outcome gate is complete.
