# Feature Slice Review: First-task prerequisite continuity

Status: Successful  
Slice: `first-task-prerequisite`  
Date: `2026-07-31`  
Review log: `reviews/2026-07-31-first-task-prerequisite.md`

## Slice contract

### Goal

Keep first-run task creation honest and actionable by requiring a real Mentat project before task-entry actions appear.

### In scope

- Hide the Projects header Create Task action until at least one project exists.
- Hide Managed Agent and post-creation Assign First Task actions until at least one project exists.
- Guard every create-task editor entry point against an empty project inventory.
- Explain the project prerequisite in empty task surfaces.

### Out of scope

- A guided setup wizard.
- Automatic project creation.
- Changes to task or project persistence rules.
- Hermes mutation behavior.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | With zero projects, Create Task and Assign First Task actions are not offered. | Focused UI contract plus desktop/mobile browser inspection | Pass |
| AC-2 | A create-task editor cannot open through a secondary/programmatic entry path until a project exists. | Focused UI contract | Pass |
| AC-3 | Empty task surfaces tell the user to create a project first. | Focused UI contract plus browser inspection | Pass |
| AC-4 | After creating a project, Create Task becomes available and opens the valid task editor. | Browser interaction | Pass |
| AC-5 | Existing task editing and server-side project validation remain unchanged. | Full unit suite | Pass |

### Constraints and recovery

- Safety: Keep the existing server-side project allowlist; no Hermes core writes.
- Compatibility: Preserve editing of existing tasks, including legacy data.
- Rendered behavior: Check desktop and phone-sized layouts.
- Rollback or recovery: Revert this isolated slice commit.
- Documentation targets: This review log; no user guide change needed for this narrow continuity fix.
- Version-control strategy: Isolated branch from `origin/main`, one intentional commit, ready PR after both reviews are clean.

### Scope discussion and approval

- Recommendation and rationale: Remove invalid actions at the point of use and retain a defensive guard, avoiding a form that can never save.
- Alternatives considered: Disable buttons (weak explanation and tooltip behavior); redirect Create Task to Create Project (label/action mismatch); auto-create a project (surprising mutation).
- User decisions: User requested removal of redundant controls and authorized all slices moving forward.
- Approved at: Standing approval recorded before this slice on 2026-07-31.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Task actions render with zero projects. | Static UI contract and browser checks | Invalid actions are absent. | Static checks do not prove runtime layout alone. |
| AC-2 | `openTaskEditor('create')` has no prerequisite guard. | Static UI contract | All callers share a fail-closed boundary. | Does not invoke every future caller. |
| AC-3 | Empty task copy mentions only filters. | Static UI contract and browser checks | First-run direction is visible. | Copy comprehension is qualitative. |
| AC-4 | No post-project transition evidence. | Browser create-project flow | Action appears and editor opens. | Temporary local fixture only. |
| AC-5 | Regression risk across task workflows. | Full unit suite | Existing contracts continue to pass. | Platform-specific release behavior is separate. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Focused first-task prerequisite contract | macOS / Python 3.13 | Fail as expected | New contract failed because the pre-change UI always rendered task actions and had no shared prerequisite guard. |

### Test discussion and approval

- User questions and decisions: None; the user granted standing approval for slice and test choices.
- Accepted coverage gaps: Browser verification uses temporary local data and does not mutate personal Mentat data.
- Approved at: Standing approval recorded before this slice on 2026-07-31.

## Implementation record

### Changes

- Hid the Projects Create Task button while the project inventory is empty.
- Hid both Managed Agent Assign First Task actions while no project exists.
- Added a shared fail-closed guard to the create-task editor and its agent-assignment caller.
- Made the task inspector clear an already-open create form if project inventory transitions back to zero; legacy edit mode keeps its existing compatibility fallback.
- Replaced filter-oriented task empty copy with a first-project prerequisite when appropriate.
- Used stable task and Managed Agent cache keys with project availability inside each hashed payload so zero-to-one-to-zero cycles cannot reuse stale DOM.

### Deviations and decisions

- None.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_dashboard_behaviors... tests.test_agent_creator_ui tests.test_usability_features_ui -v` | macOS / Python 3.13 | 0 | 20 pass | Covers the new prerequisite plus adjacent task and agent UI contracts. |
| `node --check public/app.js` | Node.js | 0 | Pass | JavaScript syntax valid. |
| `git diff --check` | Git | 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -v` | macOS / Python 3.13 | 0 | 917 pass, 4 skip | All repository tests passed. |

### Rendered or manual behavior

- Desktop 1440×900 zero-project view: Create Task absent; both task surfaces show the project prerequisite; document width equals viewport width.
- Phone 390×844 zero-project view: Create Task absent; two prerequisite messages visible; document width equals viewport width (390px).
- Temporary project creation: Create Task appeared immediately; opening it produced a create-mode editor with `First Project` preselected.
- Phone task editor and restored desktop task editor both had document width equal to viewport width.
- A fresh browser tab after fixture permission correction reported no console errors.
- Temporary data directory `/private/tmp/mentat-first-task.DJBgug` was removed after verification.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Working-tree diff on `codex/beta-first-task-prerequisite` before publication.
- Verification evidence: Focused checks, 917-test full suite, desktop/phone browser interaction above.
- Rendered artifacts: Live local browser inspection with temporary data; no persistent screenshot required.

### Round 3 packet

- Diff/commit reviewed: Corrected working-tree diff after the two round-1 findings and corroborated round-2 cache-cycle finding.
- Verification evidence: Focused checks passed; final full suite passed 917 tests with 4 platform skips.
- Rendered artifacts: Prior desktop/phone evidence remains applicable; the cache-cycle correction is structurally covered.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | Medium | Yes | An already-open create form could survive a one-to-zero project refresh and render the synthetic General fallback. | Yes | Enforce the project prerequisite in the renderer before editor markup is produced; retain fallback only for edit compatibility. |
| A-2 | None | No | Round-3 corrected diff is clean; stable cache keys and the renderer guard resolve repeated availability transitions. | Yes | None. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | Medium | Yes | Managed Agents could retain a cached zero-project rendering after the first project was created, leaving Assign First Task hidden. | Yes | Bind the Hermes-profile render cache to project availability and cover the transition contract. |
| B-2 | None | No | Round-3 corrected diff is clean; no remaining compatibility or product finding. | Yes | None. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Open create mode survived a later empty project inventory. | Unique correctness finding. | Maintained and verified resolved in round 3. | Accepted; the renderer must uphold the invariant, not only entry points. | Clear create mode/draft before computing editor-active state whenever projects are empty. |
| Managed Agents cache ignored the project prerequisite state. | Unique product/compatibility finding. | Revised in round 2: alternate keys still allowed a stale cache cycle. | Accepted; the action must react to every project-availability transition. | Moved availability into the hashed profile render payload under one stable component key. |
| Availability was encoded in alternate task/profile cache keys, allowing an old matching key to skip a later 0→1→0 render. | Corroborated by both reviewers in round 2. | Maintained and verified resolved in round 3. | Accepted; component identity stays stable and all render-affecting state belongs in the hashed payload. | Replaced alternate keys with stable `tasks` and `hermes-profiles` keys; payloads now include project availability and task UI state. |

### Reverification

- Focused tests: 20 passed plus JavaScript and diff checks after the final correction.
- Full suite: 917 passed, 4 skipped after the final correction.
- Next review round or gate result: Round 3 clean from both independent reviewers; publication gate passed.

## Documentation updates

- Roadmap: No change planned; this is a bounded implementation-continuity fix within the current beta scope.
- Changelog: No separate changelog exists for this slice.
- Architecture/operator docs: No contract change.
- Project/session notes: This review log.
- Documentation verification: Review log checked through `git diff --check`; no product/operator contract changed.

## Publication gate

- Proposed files: `public/app.js`, focused tests, this review log.
- Branch and base: `codex/beta-first-task-prerequisite` from `origin/main`.
- Commit message: `Prevent task creation before project setup`
- PR title: `Prevent task creation before project setup`
- PR summary: Hide invalid first-task actions until a real project exists, fail closed at the shared editor boundary, and clarify empty-state guidance.
- Unresolved risks: Non-blocking residual—Managed Agents 0→1→0 is covered by cache-structure assertions and two reviewer analyses rather than an end-to-end browser automation.
- User authorization and scope: Standing approval for all slices and publication steps.
- Commit hash: Recorded by Git and the PR after publication.
- Ready PR URL: Pending.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-5 passed.
- Potential bugs or untested paths: No known bug; the rendered Managed Agents repeated availability cycle remains a future browser-regression opportunity.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: No data migration or backend contract change; revert the isolated commit to roll back.
- User decision: Standing approval applies.
- Next slice authorized: Yes, under the user's standing approval; still execute one slice at a time.
