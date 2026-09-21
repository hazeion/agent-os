# Remaining transcript and responsive acceptance

Baseline: `41fa2ec`, following reviewed PRs 243/244. The owner approved completing
the baseline acceptance map before expanding Project and owner access authority.
Each implementation correction receives two independent reviews before push.

## Responsive reproduction

Isolated production preview, disposable initialized data, Windows in-app browser.
At 320x740 the viewport has 305px available width and both document/body scroll
width equal 305px: the earlier horizontal overflow correction holds.

Selecting a Task places its focused heading at y=11.9 beneath the utility bar.
After Edit, Cancel and resize to 1920x1080, the inspector header spans
y=-6.56..60.33 while the utility bar spans y=0..64. The inspector's 76px sticky
offset is ineffective because its outer .panel has overflow:hidden, creating
a non-scrolling sticky ancestor. The mobile heading also reserves only 12px
scroll margin. Issue 228 remains reproducible, not ready for closure.

Plan: give only the planning panel a non-scrolling clip boundary, retain
interior desktop scrolling, and offset mobile heading/header by the utility
height. Verify phone selection/edit/scroll and desktop resize/scroll, preserved
focus/drafts and no horizontal overflow. Do not change general panel semantics.

Implemented the scoped clip boundary and reduced the desktop pane height to
reserve the outer panel/footer clearance at the bottom of page scroll. Compact
layouts through 1100px use page scrolling with a utility-height sticky header
and heading scroll margin. Existing theme tokens and action grouping remain.

Production readback after correction:

- 320x740: document/body widths remain 305px. Selection places the heading at
  y=103.9 and header at y=78.81, below the utility bar's y=64 bottom. Scrolling
  the page pins the header at y=64 with title and Edit still visible.
- Phone Edit -> Cancel -> 1920x1080: retained page scroll is 195.2px; header
  spans y=89.44..156.33, with inspector height 896px. No horizontal overflow
  (client and scroll width 1905px). Scrolling the inspector internally to
  357.6px leaves its header at y=89.44 and utility bottom at y=64.
- Final compact rules at 1024x768: available and scroll widths both 1009px,
  heading y=103.9, header y=78.81, utility bottom y=64.

These are measured production-browser checks, not physical-device acceptance.

Review identified that enabling viewport stickiness also required the Project
navigation pane to reserve the utility height. Corrected its desktop offset and
height, then rebuilt and checked both panes together at 1440x900: navigation
top y=95.04, inspector header y=95.84, utility bottom y=64; available/scroll
widths both 1425px. Both reviewers re-reviewed with no remaining findings.
Browser viewport overrides were reset, the audit tab closed and the exact
disposable preview stopped. Audit data remains ignored and separate.

## Transcript investigation

Issue 230's seed correction is merged. A new interaction regression executes
Queue -> Stop -> queued cancellation while an older detail read is held open,
then delivers two older snapshots, including one with an empty Message page.
Both accepted user prompts remain visible, cancellation styling persists,
the queue does not resurrect, and each mutation is sent once. The reported
disappearance did not reproduce on current code. No transcript implementation
change was made merely to claim a fix; the test records the required behavior.

All 144 focused Home/planning/shell tests, lint and the final production build
pass. Two independent reviewers verified the CSS scope and transcript test;
both independently reran the Stop/cancel regression. No remaining findings.
