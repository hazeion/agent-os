# PT-2A review log — everyday planning workbench

Issue: [#177](https://github.com/hazeion/agent-os/issues/177)
Wayfinder map: [#165](https://github.com/hazeion/agent-os/issues/165)
Branch: `codex/pt-2a-planning-workbench`

## Approved scope

- Replace the minimal `/tasks` body with the accepted Variant A desktop
  workbench: Project and saved-view navigation, List and Board modes, shared
  selection and filters, and a persistent selected-Task inspector.
- Add the Variant B narrow-screen focus flow without horizontal page overflow.
- Use the existing named same-origin planning capabilities for exact-revision
  Task and Project changes. Add only bounded, purpose-specific safe
  projections where the inspector needs authoritative detail.
- Support quick edits and deliberate Details editing for workflow stage,
  dates, Today state/order, recurrence, checklists, canonical Agent assignment,
  and Project rename/archive/restore controls.

## Explicit exclusions

- No dependency graph rendering or dependency editing; PT-2B owns the
  semantic dependency editor and PT-2C owns the optional visual Map tab.
- No Task execution, Run once, delegation, review-cycle actions, or Agent-run
  lifecycle changes.
- No Project or Task cascade deletion, generic bridge capability, browser
  runtime selection, or authority migration.

## Verification strategy

- Cover exact mutation bodies, hostile/detail projection rejection, selection,
  filters, List/Board parity, inspector edits and stale conflicts in Python,
  bridge, Node, and React tests.
- Exercise keyboard focus return, live announcements, reduced motion,
  standard and high contrast, 200% and 400% zoom, tablet, and 390 by 844
  mobile layouts without page-level horizontal overflow.
- Before every push and immediately before merge, navigate and interact with
  the production-like local browser build. Require the complete GitHub quality,
  native artifact, and cross-platform CI matrix plus two independent
  defect-first reviews before merge.

## Execution evidence

- Added a three-region desktop workbench with responsive two-region tablet and
  single-column narrow-screen arrangements.
- Added selected-Task-only detail projection and fixed bridge/API route; list,
  overview, and attention projections remain summary-only.
- `npm --prefix web run check` passed (lint, typecheck, 231 Node tests).
- Focused planning Python suite passed: `tests.test_planning_model` and
  `tests.test_conversation_planning_bridge` (10 tests).

## Review record

- Independent reviewer 1 found and verified fixes for recurrence preservation,
  deep-link selection/focus, immediate description-preview reconciliation, and
  failed-save draft retention.
- Independent reviewer 2 found and verified fixes for tablet reflow, narrow
  touch targets, post-save reconciliation, and cross-Task mutation races.
- Final result: no actionable P0–P3 findings. Remaining risk is limited to
  additional dedicated route/race test coverage.

## Browser acceptance

- Local production-like browser pass confirmed four fixed-height 108px Task
  cards with visible descriptions, selected-Task inspector/editor open and
  close, and List/Board switching across all six stages.
