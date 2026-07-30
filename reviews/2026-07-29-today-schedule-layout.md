# Feature Slice Review: Today Schedule Layout

Status: Ready for publication
Slice: `today-schedule-layout`
Date: `2026-07-29`

## Slice contract

### Goal

Keep the Home utility controls stable by placing **Open today schedule** below
the **Quick add** and **Completed work** disclosures instead of making all three
items compete in one wrapping flex row.

### In scope

- Keep Quick add and Completed work together as a compact control group.
- Put Open today schedule on its own row immediately below that group.
- Preserve the existing link target, wording, keyboard behavior, and compact
  dark visual style.
- Verify desktop and narrow responsive layouts.

### Out of scope

- Changing task capture, completed-work behavior, or the Today calendar.
- Remote artifact behavior.
- Token and context-window telemetry.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Quick add appears before Completed work, and Open today schedule appears below both. | HTML order contract | Pass |
| AC-2 | Opening either disclosure does not move the schedule link into a different horizontal position. | CSS contract and rendered check | Pass |
| AC-3 | The layout remains compact and usable at desktop and 390 px width without horizontal overflow. | Rendered browser check | Pass |
| AC-4 | Existing Home interactions and visual contracts continue to pass. | Focused and full tests | Pass; 881 full-suite tests passed |

### Approval

The user requested this exact layout change and granted standing approval for
all slice, test, review, and publication decisions. Approved `2026-07-29`.

## Test strategy

- Add a structural UI contract for the exact control order and row grouping.
- Run Home operations and visual-contract tests.
- Render the Home panel at desktop and narrow widths.
- Run the full repository suite, preserving the user's unrelated local data.

## Implementation record

- Wrapped Quick add and Completed work in a compact
  `home-panel-utility-row`.
- Moved Open today schedule after that row and gave it a stable
  `home-schedule-link` class.
- Made the footer a centered column while leaving disclosure expansion inside
  its own wrapping row.
- Added an exact DOM-order and CSS-direction regression test.

## Verification

- Focused Home/visual/delegation UI suite: 42 passed.
- Desktop rendered check at 1680×962: schedule link remained centered at
  `x=545` before expansion, after Quick add expansion, and after Completed work
  expansion; no horizontal overflow.
- Narrow rendered check at 390×844: schedule link remained centered at `x=116`
  before and after Quick add expansion; no horizontal overflow.
- Visual inspection confirmed a compact two-control row followed by a clear
  schedule action, with the expanded Quick add form contained above it.
- Complete repository suite: 881 passed, 1 failed, 4 skipped. The only failure
  is the pre-existing `Daily Check` change in the user's uncommitted
  `data/projects.json`, which this slice leaves untouched.

## Adversarial review

- Security and behavior review: approved. Native disclosure/link semantics,
  keyboard behavior, responsive layout, and the rendered positions were
  preserved. The reviewer identified a weak closing-tag assertion in the first
  regression test; it was replaced with an HTML parser that verifies the exact
  direct-child hierarchy, then approved on re-review.
- Compatibility and scope review: approved. The reviewer found no actionable
  disclosure, responsive, visual-contract, or scope issue and independently
  reproduced the stable link position and overflow checks.

## Publication gate

- Branch: `codex/today-schedule-layout`
- Base: `codex/remote-delegation-artifacts-v1` (stacked)
- Proposed commit: `fix(ui): stabilize Today schedule action`
- User authorization: standing approval.

## Outcome review

The Today footer now has one predictable layout: its two optional work areas
stay together, and the schedule action stays in the same centered row beneath
them. Both adversarial reviews approved the final change, the focused suite
passes 42/42, and rendered checks cover desktop and narrow widths. The slice is
ready to publish without including the user's unrelated data or design changes.
