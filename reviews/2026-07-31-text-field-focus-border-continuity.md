# Feature Slice Review: Text-field Focus Border Continuity

Status: Successful
Slice: `text-field-focus-border-continuity`
Date: `2026-07-31`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  publication actions.
- Work remains one reviewed slice at a time; user-owned `data/projects.json`,
  `design/`, and `uv.lock` stay excluded.

## Slice contract

### Goal

Make typing-field focus consistent across Mentat: the visible control border
changes to the theme highlight color, with no highlight drawn outside it.

### In scope

- All text-entry `input` types and `textarea` controls in both UI shells.
- Search fields whose visible border belongs to `.search-shell`.
- Agent Console prompt/workspace search, global search, session search, notes
  search, creator search, task/project forms, and dynamically rendered editors.
- A deterministic cascade contract, focused regressions, changelog, and review
  record.

### Out of scope

- Buttons, links, selects, radio/checkbox controls, scroll regions, cards, and
  other non-text keyboard targets; their existing focus indication remains.
- Layout, field dimensions, behavior, data, Hermes, and Apple notarization.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A focused normal text field or textarea highlights its own border and has no outer outline or shadow. | Final cascade contract | Pass |
| AC-2 | A focused `.search-shell` highlights the visible shell border while its borderless inner search input adds no second highlight. | Search-shell contract | Pass |
| AC-3 | Agent Console and dynamically rendered task/project fields follow the same rule. | Coverage inventory and focused tests | Pass |
| AC-4 | Non-text focus behavior, layout, and interaction remain unchanged. | Scoped CSS diff and regression suites | Pass |
| AC-5 | Two independent adversarial reviewers find no unresolved in-scope regression. | Review record | Pass |

### Constraints and recovery

- Presentation-only CSS and deterministic test changes; no runtime mutation.
- Preserve keyboard-visible focus through the highlighted border.
- Apply to both Classic and Emerald without one-off page overrides.
- Rollback: revert the slice commit; no migration.
- Branch: `codex/text-field-focus-border-continuity` to `main` as a ready PR.

### Scope and test approval

- Standing user approval applies to the contract, test strategy, outcome, and
  publication.
- Baseline source audit found late rules that explicitly add outside outlines
  to `.search-shell`, general text-entry controls, task-editor fields, Agent
  Console prompt, and workspace search. The earlier Emerald global rule also
  outlines all inputs, so the final text-entry rule must override it.
- Live localhost browser rendering remains unavailable under the selected
  browser's URL safety boundary. Exact final-cascade checks, broad UI suites,
  and two adversarial reviews are the accepted evidence; no new hosted browser
  result is claimed for this unpushed revision.

## Test strategy

| Criterion | Planned evidence | Limitation |
| --- | --- | --- |
| AC-1 | Require the final general text-entry rule to set a highlight border and explicitly remove outline and shadow. | Static CSS contract does not measure pixels. |
| AC-2 | Require `.search-shell:focus-within` to change border only, and the inner input to remove outline/shadow/border. | Does not capture a screenshot. |
| AC-3 | Inventory all text-entry elements in static and dynamic UI sources and protect the Agent Console/task editor selectors against later outer effects. | Dynamic browser state is covered by source and existing UI tests. |
| AC-4 | Run focus, visual, Home, attachment, workflow, syntax, and full suites. | User-owned fixture may keep its known unrelated failure. |
| AC-5 | Two independent read-only reviewer passes with reconciliation and reverification. | Reviewers do not edit files. |

## Baseline

- Source audit: gap confirmed; the final shared rules use positive-width
  `outline` and `outline-offset` for search shells and text-entry controls.
- Baseline regression: 6 focus-continuity tests ran; 4 passed and the 2 new
  border-only contracts failed as expected on the existing outside outlines.

## Implementation

- `.search-shell:focus-within` now changes its visible border to `var(--accent)`
  and explicitly removes outline and shadow; its borderless inner input stays
  free of a second highlight.
- The final shared text-entry rule changes the actual input/textarea border and
  removes outline and shadow for all supported text-entry types.
- Higher-specificity task-editor, Agent Console prompt, and workspace-search
  rules use the same border-only treatment.
- Non-text focus rules were not changed.

## Verification

- Focused UI suites: 76 passed after implementation.
- Frontend syntax and patch checks: passed.
- Initial full suite: 912 ran; 911 passed; 1 failed on the unrelated user-owned
  `Daily Check` fixture; 4 skipped.

## Adversarial review

### Round 1

| ID | Reviewers | Severity | Blocking | Finding | Disposition |
| --- | --- | --- | --- | --- | --- |
| R1-01 | A and B | P1 | Yes | Emerald's earlier global focus rule had greater specificity, so most text fields would retain the outer outline despite the new later declarations. | Accepted. Final text-entry and component selectors are now scoped through `:root[data-ui-shell]`; a deterministic specificity/source-order/importance contract covers the global competitor and search path. |
| R1-02 | B | P2 | Yes | Full-suite and hosted-smoke evidence were incomplete or overstated in the initial record. | Accepted. Exact full-suite counts are recorded and the unearned hosted-smoke claim is removed. |

### Round 2

| ID | Reviewers | Severity | Blocking | Finding | Disposition |
| --- | --- | --- | --- | --- | --- |
| R2-01 | A, then independently confirmed by B | P1 | Yes | Emerald's more-specific base `.search-shell` border defeated the unprefixed focused wrapper, leaving no visible accent border. | Accepted. The focused wrapper is now scoped through `:root[data-ui-shell]`; the cascade test proves greater specificity, later source order, border-only declarations, and no importance. |

- Round 1 reverification: 77 focused UI tests passed; 913 full
  tests ran with 912 passed, the same 1 unrelated user-fixture failure, and 4
  skipped; syntax and patch checks passed.
- Round 2 reverification: 77 focused UI tests passed; 913 full tests ran with
  912 passed, the same 1 unrelated user-fixture failure, and 4 skipped; syntax
  and patch checks passed.

### Round 3 gate

- Reviewer A: clean; correctness and accessibility gate clear.
- Reviewer B: clean; product, accessibility, cascade, coverage, and
  verification gate clear. Independent focused run: 77 passed.

## Documentation and publication

- Changelog: complete.
- Proposed files: `CHANGELOG.md`, `public/styles.css`,
  `tests/test_input_focus_continuity.py`, and this review log.
- Commit: `Use border-only text field focus`.
- PR title: `Use border-only text field focus`.

## Outcome

- Classification: Successful; AC-1 through AC-5 pass.
- Remaining risks: no new live browser rectangle because of the recorded local
  URL safety boundary; exact cascade and broad regression evidence are clean.
- Next slice authorized: yes under standing approval; Emerald-only appearance
  and equal theme-card sizing are queued next.
