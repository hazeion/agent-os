# Feature Slice Review: First Project Empty State

Status: Successful
Slice: `first-project-empty-state`
Date: `2026-07-31`
Review log: `reviews/2026-07-31-first-project-empty-state.md`

## Process exception

- The project owner instructed Codex to assume approval for all Road-to-Beta
  slices, decisions, verification, and publication actions.
- That standing authorization covers this contract, test strategy, outcome,
  staging, commit, push, and ready pull request. Work remains one reviewed
  slice at a time and unrelated user files remain excluded.
- The previous beta-tester first-launch slice completed successfully and merged
  as pull request 91. Standing authorization permits this next slice without a
  separate outcome pause.

## Slice contract

### Goal

When Mentat has no projects, tell a new user how to start planning through the
existing safe dashboard action without implying that Hermes or direct JSON
editing is required.

### In scope

- Replace the stale zero-project message in the Projects view.
- Point to the existing **Create Project** control and state that Hermes is
  optional for planning.
- Keep one project-creation action rather than adding a duplicate empty-state
  button.
- Add a focused UI contract and verify the state at desktop and phone widths.

### Out of scope

- Automatically opening the editor or changing project creation behavior.
- Adding a walkthrough, setup wizard, modal, or new onboarding surface.
- Changing project storage, APIs, Hermes integration, task creation, or sample
  data.
- Changing release gates, roadmap status, or external beta evidence.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | With zero projects, the Projects view points to the existing **Create Project** action and makes clear that Hermes is optional for planning. | Focused UI contract plus rendered inspection | Pass |
| AC-2 | The zero-project state contains no instruction to ask Hermes or edit `data/projects.json`. | Negative UI contract and raw diff inspection | Pass |
| AC-3 | The view retains exactly one project-creation button and does not add a competing empty-state action. | Static DOM/JS contract | Pass |
| AC-4 | The corrected message remains readable without clipping or horizontal overflow at desktop and phone widths. | In-app browser screenshots and geometry inspection | Pass |
| AC-5 | Two independent adversarial reviewers report no unresolved in-scope issue. | Review record | Pass |

### Constraints and recovery

- Safety: keep project creation on the project-owned validated write path; do
  not instruct users to edit storage or mutate Hermes.
- Compatibility: preserve the existing editor, event delegation, and project
  list markup.
- Rendered behavior: retain the quiet empty-state hierarchy and one compact
  panel-heading action at wide and narrow widths.
- Rollback or recovery: revert the slice commit; no stored data or runtime state
  changes.
- Documentation targets: changelog and this review log only; the correction is
  self-explanatory in the product.
- Version-control strategy: branch `codex/beta-first-project-onboarding` from
  merged `main`, with a ready pull request back to `main`.

### Scope discussion and approval

- Recommendation and rationale: correct the contradictory empty-state copy and
  reuse the existing action. This closes a real first-run gap without creating
  another onboarding system or redundant button.
- Alternatives considered: add a second CTA inside the empty state (more
  obvious but redundant); automatically open the editor (surprising and
  removes orientation); add a guided setup screen (explicitly deferred and far
  broader).
- User decisions: streamline onboarding, remove redundant actions, preserve
  local-first planner use without requiring Hermes, and continue Road to Beta.
- Approved at: 2026-07-31 under the recorded standing authorization.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The current empty state says to ask Hermes to edit a file. | Isolate `renderProjects` and require first-project and Hermes-optional guidance. | The zero state names the supported user path. | Static text alone does not prove rendered fit. |
| AC-2 | Direct storage-edit guidance is present. | Forbid `ask Hermes` and `data/projects.json` in the render block. | The stale unsafe guidance cannot return silently. | Does not inspect unrelated documentation. |
| AC-3 | A second CTA would conflict with the panel heading. | Require exactly one `id="create-project-button"` and no empty-state button hook. | Project creation has one clear action. | Does not simulate a click already covered by existing UI behavior. |
| AC-4 | Long replacement copy could wrap or overflow on a phone. | Render zero-project state at 1440×900 and 390×844; inspect visibility, bounds, and horizontal overflow. | The actual responsive UI remains readable. | Visual checks use the local test machine and theme. |
| AC-5 | Copy can still be ambiguous or violate product boundaries. | Two identical read-only review packets and re-review after accepted fixes. | Independent safety and product scrutiny. | Reviewers do not replace external novice testing. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Source inspection | Merged `main` | Gap confirmed | `renderProjects` says to ask Hermes to add a project to `data/projects.json`, despite the existing safe **Create Project** action. |
| New zero-state UI contract | Pre-implementation branch | Expected fail | Missing `No projects yet.` and retained the instruction to ask Hermes to edit `data/projects.json`. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts a focused static
  contract, responsive in-app browser checks, and the complete repository
  suite.
- Accepted coverage gaps: only an external novice can prove the wording needs
  no clarification; this slice does not claim cohort evidence.
- Approved at: 2026-07-31 under the recorded standing authorization.

## Implementation record

### Changes

- Replaced the stale zero-project instruction with a short handoff to the
  existing **Create Project** control and an explicit statement that Hermes is
  optional for planning.
- Added a focused contract that keeps the unsafe direct-file wording out and
  prevents a duplicate empty-state action.
- Added an operator-visible changelog entry.

### Deviations and decisions

- None.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_usability_features_ui tests.test_visual_contract tests.test_dashboard_behaviors -q` | Isolated worktree, Python 3 | Exit 0 | 54 passed, 0 failed, 0 skipped | Covers the new zero-project contract and adjacent UI/behavior contracts. |
| `node --check public/app.js` | Isolated worktree | Exit 0 | Pass | JavaScript syntax is valid. |
| `git diff --check` | Isolated worktree | Exit 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -q` | Isolated worktree, Python 3 | Exit 0 | 912 passed, 0 failed, 4 skipped (916 total) | Complete repository suite. Expected CLI argument-parser diagnostics were emitted by negative-path tests. |

### Rendered or manual behavior

- In-app browser, isolated empty data directory, light theme, desktop
  1440×900: the message and existing **Create Project** control were visible,
  the button count was exactly one, and document width equaled viewport width
  (1440 px). The empty-state box was 632.65×96 px and fully contained the copy.
- In-app browser, same state, phone 390×844: the message wrapped cleanly, the
  existing button remained visible at 114.83×44 px, the button count remained
  one, and document width equaled viewport width (390 px).
- No duplicate empty-state CTA, clipping, or horizontal overflow was observed.

## Adversarial review

### Round 1

- Correctness and test-adequacy reviewer: no findings. The reviewer confirmed
  that the copy routes users to the single existing validated action, treats
  Hermes as optional, removes direct-file guidance, preserves behavior, and is
  adequately covered by the static and responsive evidence.
- Product, accessibility, and responsive-operability reviewer: no findings.
  The reviewer confirmed that the wording is clear, the existing heading
  control remains the sole initial action, the later editor submit control is
  not a competing empty-state action, and the existing responsive structure is
  preserved.
- Reconciliation: no fixes or repeat round required. Both reviewers identified
  only the accepted residual risk that external novice use is needed to prove
  subjective first-use clarity; existing project-creation behavior is covered
  outside this copy-focused slice.

## Documentation updates

- Roadmap: no status change planned; external gates remain open.
- Changelog: updated under 2026-07-31 Fixed.
- Architecture/operator docs: no change planned.
- Project/session notes: this review log.
- Documentation verification: focused contract, raw diff inspection, and full
  repository suite pass.

## Publication gate

- Proposed files: `CHANGELOG.md`, `public/app.js`,
  `tests/test_usability_features_ui.py`, and this review log.
- Branch and base: `codex/beta-first-project-onboarding` to `main`.
- Commit message: `Clarify first project onboarding`.
- PR title: `Clarify first project onboarding`.
- PR summary: replace stale direct-file/Hermes zero-state guidance with the
  existing safe project creator and verify responsive continuity.
- Unresolved risks: external novice evidence remains required; no unresolved
  in-scope issue.
- User authorization and scope: standing Road-to-Beta approval recorded above.
- Commit hash: recorded in Git history by the publication step.
- Ready PR URL: recorded in the GitHub publication result.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-5 pass.
- Potential bugs or untested paths: novice wording comprehension remains an
  external cohort check; click-through behavior is unchanged and covered by
  existing project-creation tests rather than duplicated in this slice.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: copy-only UI change; revert the
  slice commit.
- User decision: standing authorization permits publication after all gates.
- Next slice authorized: Yes, under the standing Road-to-Beta authorization.
