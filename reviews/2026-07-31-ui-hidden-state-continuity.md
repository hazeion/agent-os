# Feature Slice Review: UI Hidden-State Continuity

Status: Successful
Slice: `ui-hidden-state-continuity`
Date: `2026-07-31`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  decisions.
- Standing approval covers this contract, test strategy, outcome, staging,
  commit, push, and ready pull request.
- Work remains one reviewed slice at a time, with unrelated user files excluded.

## Slice contract

### Goal

Prevent controls and panels marked `hidden` from reappearing when component
styles assign their own display mode, and remove the duplicate task-editor
Cancel action revealed by the corrected state transition.

### In scope

- Restore one global, authoritative rendering rule for the HTML `hidden`
  attribute.
- Verify the empty task inspector does not expose its editor-only Cancel action.
- Verify an all-projects queue does not expose the hidden Clear project action.
- Keep one form-local Cancel action when task creation or editing is active;
  remove the duplicate inspector-header action with the same behavior.
- Audit representative hidden overlays, session panels, and responsive views for
  regressions.

### Out of scope

- Changing when application code adds or removes `hidden`.
- Redesigning other task actions, navigation, or dialogs.
- Apple signing, onboarding, and unrelated responsive refinements.
- User-owned `data/projects.json` and `design/`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Any element carrying `hidden` computes to `display: none`. | Browser audit and visual contract | Pass |
| AC-2 | Empty task state has no Cancel and an unfiltered queue hides Clear project. | 390px rendered check | Pass |
| AC-3 | Task creation/editing shows exactly one form-local Cancel; other intentionally revealed controls still appear. | Browser interaction checks | Pass |
| AC-4 | Session tabs, overlays, navigation, and representative breakpoints retain their expected layout. | Focused tests and rendered audit | Pass |
| AC-5 | Two independent adversarial reviewers find no unresolved in-scope regression. | Review record | Pass |

### Constraints and recovery

- The rule affects presentation only; it does not alter state, persistence, or
  Hermes data.
- Application code remains the sole authority for toggling the `hidden`
  attribute.
- Rollback is the slice commit; no migration is required.
- Branch: `codex/ui-responsive-continuity`, based on merged `main`.

## Test strategy

| Criterion | Baseline gap | Planned evidence | Limitation |
| --- | --- | --- | --- |
| AC-1 | Author display rules currently override the user-agent hidden rule. | Assert the global important rule and inspect all current `[hidden]` elements. | Dynamic states are sampled through representative interactions. |
| AC-2 | Cancel and Clear project are visibly rendered despite `hidden`. | Repeat the exact empty all-projects state at 390px. | Uses local operator data only as live supplemental evidence. |
| AC-3 | A global rule could suppress a control after reveal; the editor also has two equivalent Cancel actions. | Open/close navigation, enter task creation, confirm one Cancel, then cancel. | Browser timing is supplemental to deterministic contracts. |
| AC-4 | Hidden is used across dialogs, session tabs, and overlays. | Run visual/frontend tests and desktop/tablet/phone audits. | Calendar horizontal scrolling remains intentional. |
| AC-5 | Baseline defect is independently reproducible. | Two read-only adversarial reviews after implementation and verification. | Reviewers do not modify the worktree. |

## Baseline evidence

- At 390px in Projects & Tasks, `#selected-task-cancel[hidden]` computed to
  `display: flex` and rendered beside disabled empty-state task actions.
- In the same unfiltered state, `#clear-project-filter[hidden]` computed to
  `display: flex` and rendered as a redundant Clear project action.
- A DOM-wide audit found these two visible hidden elements in the active view.
- Session History alignment and outside-only focus remained correct at 390px,
  768px, and 1440px with no page-wide overflow.

## Adversarial review

### Round 1

- The safety/accessibility reviewer found no cascade, keyboard, dialog,
  overlay, or Session tab regression. All current reveal paths remove or toggle
  `hidden` rather than attempting a competing display override.
- The product reviewer found one P2 mobile-flow regression: removing the
  duplicate inspector-header Cancel left the only editor Cancel below roughly
  twenty fields in the one-column phone layout, while Back to queue remained a
  misleading non-cancel action.
- Resolution: keep exactly one form-local Cancel, move it into the editor
  heading before the field grid, and hide Back to queue while the editor is
  active.

### Round 2

- The product reviewer confirmed the Cancel is immediately reachable before
  the field grid, the heading wraps safely on narrow screens, and Back to queue
  is restored after leaving create/edit mode.
- The safety/accessibility reviewer confirmed correct keyboard order,
  non-submit button semantics, delegated close behavior, dynamic reveal paths,
  and unchanged session-tab, overlay, and dialog behavior.
- Both reviewers reported no remaining in-scope finding.

## Implementation record

- Added one global important `[hidden]` rendering rule ahead of all component
  layers so author display declarations cannot override the platform state.
- Removed the duplicate inspector-header task Cancel and its dead state/listener
  wiring.
- Moved the one remaining form-local Cancel into the task editor heading before
  the first field and kept it `type="button"`.
- Hidden Back to queue while task creation or editing is active; normal view
  mode restores it through the existing render cycle.
- No task data, Hermes state, persistence, or mutation behavior changed.

## Verification

### Deterministic and focused

- JavaScript syntax checks for `public/app.js` and `public/core.js`: passed.
- Focus, visual, dashboard-behavior, and workflow-feedback set: 61 passed.
- Patch whitespace check: passed.
- New visual contract asserts the authoritative hidden rule, absence of the
  duplicate header Cancel, one form-local Cancel before the field grid, and
  editor-bound Back visibility.

### Complete suite

- Final local run: 906 tests, 901 passed, 1 failed, 4 skipped.
- The sole failure is the pre-existing user-owned `Daily Check` fixture conflict
  in `test_only_mentat_project_remains_active_for_v1`; this slice does not edit
  `data/projects.json`.
- Two local browser-smoke attempts reached the same unrelated live-runtime race:
  the synthetic waiting/clarification status was replaced by the real remote
  “Checking Hermes runtime…” refresh. The stop visibility and every other
  reported contract passed; CI's isolated fixture remains authoritative for
  that runtime test.

### Live and rendered

- At 390px, 768px, and 1440px, audited views retained page-width containment;
  intentional project-rail and calendar-week scrolling stayed contained.
- Session selector/search heights remained aligned and search focus remained one
  outside-only shell outline with no inner shadow.
- A DOM-wide 390px Projects audit changed from two visible hidden elements to
  zero. Empty state exposed neither Cancel nor Clear project.
- Project selection revealed Clear project; clearing the selection removed it.
- Task creation exposed exactly one visible Cancel before the field grid,
  removed Back to queue, then restored the normal inspector after Cancel.
- Session Replay/Transcript switching produced one visible active panel and one
  zero-sized `display: none` hidden panel.

## Outcome review

- Classification: successful.
- AC-1 through AC-5 pass; the one local full-suite fixture conflict and the
  local live-runtime smoke race are unrelated and disclosed.
- Migration: none. Rollback: revert the slice commit.

## Publication packet

- Proposed files:
  - `CHANGELOG.md`
  - `public/app.js`
  - `public/index.html`
  - `public/styles.css`
  - `tests/test_dashboard_behaviors.py`
  - `tests/test_visual_contract.py`
  - this review log
- Explicit exclusions: user-owned `data/projects.json` and `design/`.
- Branch/base: `codex/ui-responsive-continuity` on `main`.
- Proposed commit and ready PR title: `Keep hidden UI state authoritative`.

## Approval

- Contract, test strategy, outcome handling, and publication are covered by the
  user's standing approval.

## Publication result

- Implementation commit: `0d037a7`.
- Ready pull request: https://github.com/hazeion/agent-os/pull/77
- Base: `main`.
- Exact staged scope matched the publication packet.
- User-owned `data/projects.json` and `design/` remained unstaged.
