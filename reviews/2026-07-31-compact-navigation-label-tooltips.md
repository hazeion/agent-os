# Feature Slice Review: Compact Navigation Label Tooltips

Status: Ready
Slice: `compact-navigation-label-tooltips`
Date: `2026-07-31`

## Process exception

- Standing user approval covers the contract, test strategy, implementation,
  outcome, and publication.
- This branch is stacked on the fully reviewed appearance slice while PR #88
  runs hosted checks. It will not be published until that PR merges.

## Contract

### Goal

Show each existing navigation name when an icon-only compact-rail item is
hovered or keyboard-focused, while phones continue to expose the same full
labels through the navigation drawer.

### In scope

- Reuse the exact visible labels: Home, Agents & Sessions, Calendar, Projects &
  Tasks, Notes & Context, and Settings.
- At the 901-1199 px compact-rail breakpoint, show the label beside its icon on
  mouse hover and keyboard focus.
- Keep the tooltip non-interactive, visually contained, and above page content.
- Preserve the <=900 px drawer behavior where tapping the menu button reveals
  all full labels; do not introduce hover or long-press dependence on phones.
- Static, rendered, responsive, accessibility, changelog, and review evidence.

### Out of scope

- Changing navigation destinations, labels, icons, breakpoints, or drawer
  interaction; adding descriptive help copy; redesigning the sidebar.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Compact-rail hover reveals the exact existing menu name beside its icon. | CSS/source and rendered contract | Pass |
| AC-2 | Keyboard focus reveals the identical tooltip without changing the accessible name. | CSS/source and rendered contract | Pass |
| AC-3 | The tooltip is non-interactive, does not cover its icon, and remains within the compact viewport. | CSS geometry and rendered measurement | Pass |
| AC-4 | Phone navigation still uses the full-label drawer and does not depend on hover. | Responsive source/rendered contract | Pass |
| AC-5 | Two independent adversarial reviewers find no unresolved in-scope issue. | Review record | Pass |

### Safety and recovery

- Presentation-only HTML/CSS/browser-test change; no data or Hermes mutation.
- Rollback by reverting the slice commit.
- User-owned files are absent from this isolated worktree.

## Test strategy and baseline

- Require the six exact existing labels in navigation markup.
- Parse only the 901-1199 px compact block and require hover/focus disclosure,
  hidden idle state, non-interactive behavior, and bounded one-line sizing.
- Preserve the <=900 px drawer's visible label rule.
- Extend browser smoke at 1024 px to focus a compact item and measure tooltip
  visibility, placement, text, and viewport containment.
- Run focused UI, syntax, full-suite, and two independent reviews.
- Baseline: the new compact-tooltip contract failed because the icon rail hid
  its label span with no hover/focus disclosure rule. Existing navigation and
  drawer contracts were green.

## Implementation

- At 901-1199 px, pointer and focus events copy each navigation button's
  existing label into a page-level, fixed-position visual tooltip. This avoids
  clipping by the navigation's necessary scroll container.
- The tooltip uses bounded one-line sizing, stays to the right of the icon,
  remains hidden while idle, and sits above page content without intercepting
  pointer input.
- The <=900 px drawer remains unchanged and restores the label span as normal
  in-flow text after the user taps the menu button.
- Browser smoke now has a focused `MENTAT_NAV_TOOLTIP_SMOKE=1` path and includes
  the same checks in the complete responsive workflow.

## Verification

- Focused UI suite: 79 tests passed.
- JavaScript syntax and diff checks passed.
- Focused isolated Chromium smoke passed after review correction: at 1024 px
  “Agents & Sessions” was actually paint-hit-testable, visible on focus, began
  10 px to the right of the icon, ended at 204.5 px inside the viewport, and
  retained production `pointer-events: none`; at 390 px the opened drawer
  showed the same label at 122.5625 px wide. Idle state was hidden.
- Final full sharded suite: all 915 tests passed with four expected skips. An
  earlier run had one transient two-second performance-budget miss under
  concurrent load; its isolated rerun and the complete post-review run passed.

## Adversarial review

### Round 1

- Both reviewers found the original absolutely positioned child tooltip was
  clipped by `.nav-groups` overflow even though its rectangle and computed
  visibility looked correct. The tooltip now renders outside the sidebar as a
  page-level fixed element while navigation scrolling remains intact.
- Reviewer A found the idle-hidden state was not protected. Static and rendered
  checks now require the idle tooltip to be hidden.
- Browser smoke now temporarily enables hit testing only during the assertion
  and confirms `elementFromPoint()` reaches the tooltip, closing the clipped-
  paint false positive while verifying production pointer input remains off.

### Round 2

- Reviewer B found every focus event was treated as keyboard focus, so a
  pointer-focused item could leave the tooltip stuck after activation. Input
  modality is now tracked explicitly; pointer activation dismisses the visual,
  pointer leave retains it only for keyboard focus, and browser smoke exercises
  real Tab navigation plus pointer enter/activate/leave.
- Reviewer B found the copied label was being exposed as duplicate,
  unassociated accessibility-tree text. The page-level mirror now remains
  `aria-hidden="true"` throughout; the button's existing `aria-label` remains
  the sole accessible name.
- Reviewer A required Escape dismissal for keyboard-opened overlay content.
  Escape now hides the tooltip without moving focus, and the browser test
  verifies that lifecycle.
- Post-correction verification: focused 79 passed, full 915 passed with four
  expected skips, syntax/diff checks passed, and the isolated browser path
  passed its keyboard, paint, Escape, pointer-dismissal, and phone-drawer checks.

### Round 3

- Reviewer B found the shared visual could stay hidden after the pointer briefly
  hovered another item or after the rail scrolled, even though the original
  item retained keyboard focus. The implementation now records the
  keyboard-focused source separately, restores it after pointer leave, and
  recalculates its position after scrolling or resizing. Escape remains a
  deliberate dismissal until focus changes.
- Reviewer A found pointer-leave dismissal was only exercised after pointer
  activation had already hidden the tooltip. Browser smoke now checks hover
  leave and activation as independent lifecycles, plus the mixed keyboard
  focus/other-item hover/leave and scroll restoration paths.
- Post-correction verification passed: focused visual contracts, JavaScript
  syntax, diff checks, the full suite, and isolated Chromium smoke all passed.
  Both independent reviewers re-reviewed the final state and reported no
  actionable findings.

## Publication and outcome

- Target: ready PR to `main`.
- Commit/PR title: `Label compact navigation icons`.
- Classification: Ready.
