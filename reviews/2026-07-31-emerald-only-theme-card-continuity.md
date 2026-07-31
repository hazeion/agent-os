# Feature Slice Review: Emerald-only Appearance and Theme-card Continuity

Status: Ready for publication
Slice: `emerald-only-theme-card-continuity`
Date: `2026-07-31`

## Process exception

- Standing user approval covers the contract, test strategy, implementation,
  outcome, and publication.
- This local branch is stacked on the fully reviewed focus-border commit while
  PR #87 runs hosted checks. It will not be published until that PR merges and
  `main` contains its base.
- User-owned `data/projects.json`, `design/`, and `uv.lock` remain excluded.

## Contract

### Goal

Retire the unused Classic interface choice, make all theme preview cards the
same dimensions regardless of theme group or row population, and extend the
border-only focus treatment to native dropdown controls.

### In scope

- Hard-set `data-ui-shell="emerald"` before CSS loads.
- Remove the Interface layout selector, its event/runtime switching path, and
  explicit Classic-only CSS.
- Remove the legacy `mentat-ui-shell-v1` preference on startup so a saved
  Classic value cannot survive the migration.
- Keep shared/base CSS that Emerald still depends on.
- Give every theme preview card one fixed width and height across Dark and
  Light groups; preserve the existing phone behavior that uses the compact
  theme selector instead of the preview grid.
- Make Agent Console, Session History, task, theme, contrast, and other native
  dropdowns highlight their actual border without an outer outline or shadow.
- Tests, changelog, review record, and documentation copy.

### Out of scope

- Removing any color theme, redesigning Theme Studio, changing contrast
  behavior, or rewriting the shared stylesheet.
- Data, Hermes behavior, Apple notarization, and unrelated responsive work.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Mentat always initializes in Emerald and a stored Classic preference is discarded before first paint. | Head/preloader contract | Pass |
| AC-2 | Settings exposes no interface-layout choice and runtime code cannot switch to Classic. | HTML/JS absence contract | Pass |
| AC-3 | Explicit Classic-only CSS is removed without deleting Emerald's shared foundations. | CSS/source contract and regression suite | Pass |
| AC-4 | Dark and Light theme cards use identical fixed width and height independent of row count. | Theme-card layout contract | Pass |
| AC-5 | Native dropdowns show focus on their visible border only, including Agent Console, Session History, and task controls. | Focus contract and UI suite | Pass |
| AC-6 | Two independent adversarial reviewers find no unresolved in-scope issue. | Review record | Pass |

### Safety and recovery

- Client-side presentation/preference change only; no server or data mutation.
- Legacy preference cleanup is limited to the obsolete shell storage key.
- Rollback: revert the slice commit; no schema migration.
- Target branch: ready PR to `main` after PR #87 merges.

## Test strategy and baseline

- Update the saved-theme preloader test to require a fixed Emerald shell and
  legacy-key removal before the stylesheet.
- Update Settings contracts to reject the Classic option, shell selector,
  switching helpers/listeners, and Classic-only CSS.
- Require the theme preview grid to use fixed columns and each card to have the
  same explicit width/height; reject flexible `1fr` stretching.
- Require a final, shell-wide native-select rule that removes outside outlines
  and shadows while changing the visible control border.
- Run visual, Home, focus, workflow, syntax, and full suites, plus the isolated
  focused Chromium appearance path. The complete workflow smoke may still
  depend on broader local Hermes runtime fixtures.
- Baseline: three desired appearance contracts failed before implementation:
  fixed Emerald initialization, Classic-removal, and fixed theme-card sizing.
  The added dropdown focus contract also failed before its final override was
  added.

## Implementation

- The pre-style initializer now removes `mentat-ui-shell-v1` and always sets
  the Emerald shell; runtime shell persistence, switching, selector markup,
  and explicit Classic-only layout rules were removed.
- Browser smoke now verifies migration of a saved Classic value to Emerald and
  no longer exercises retired Classic geometry.
- Theme preview grids use fixed 160 px columns and every preview card is
  exactly 160 x 88 px, independent of group population.
- The final cascade now gives every native `select` the same border-only focus
  treatment already used by text fields and search controls.
- The Operations plan and changelog now describe Emerald as the sole interface
  layout.

## Verification

- Focused UI regression: 78 tests passed after all corrections.
- JavaScript syntax checks for `public/app.js` and
  `scripts/browser_smoke.mjs`: passed.
- Full sharded suite: 913 tests ran; 912 passed, four were skipped, and the sole
  failure is the unchanged user-owned `Daily Check` fixture in
  `data/projects.json` against the repository's Mentat-only seed contract.
- Focused Chromium smoke against an isolated loopback server passed. It
  measured all 16 theme cards at exactly 160 x 88 px, confirmed the preview
  grid is hidden at 390 px, verified the saved Classic value migrates to
  Emerald, and computed `outline: none`, `box-shadow: none`, and an accent-color
  border on focused Theme and Contrast dropdowns.
- The complete existing browser smoke advanced past this appearance coverage
  but stopped later on an unrelated local Agent Console runtime-state fixture;
  the focused appearance path is independently executable through
  `MENTAT_APPEARANCE_SMOKE=1`.

## Adversarial review

### Round 1

- Both reviewers found the implementation visually correct but blocked on the
  original select test's ability to detect stronger or important competing
  rules. The test now inventories select-focus competitors, compares source
  order and specificity, rejects `!important`, and includes synthetic
  higher-specificity and important-rule failures.
- Both reviewers required rendered evidence. A focused browser path now checks
  the legacy migration, exact card rectangles, phone hiding, and computed
  dropdown focus styles against an isolated server.
- Reviewer A found stale Classic-era plan and changelog copy. Those references
  now describe fixed Emerald initialization and theme/contrast persistence.
- The first focused browser run exposed a real High Contrast custom-property
  cycle for non-Emerald palettes. The shell-qualified High Contrast selector
  now ties the palette bridge and restores the intended accent border. Static,
  focused, full-suite, and rendered checks were rerun after this correction.

### Round 2

- Both reviewers found the first cascade inventory still missed functional
  selector lists and ID/class rules that did not literally contain `select`;
  one reviewer also noted border-only competitors were omitted. The corrected
  inventory splits only top-level commas, discovers actual select IDs/classes
  from markup, evaluates border/border-color/outline/shadow declarations, and
  adds synthetic functional-selector, important-rule, and ID-border failures.
- Both reviewers found stale strategy text that still disclaimed rendered
  evidence. The record now describes the passing isolated appearance smoke and
  limits the remaining full-smoke dependency to broader Hermes runtime
  fixtures.
- Focused UI, syntax, diff, full-suite, and isolated rendered checks remained
  at their recorded outcomes after the corrections.

### Round 3

- Reviewer A found no implementation or test blocker after the corrected
  selector parser and requested only this complete Round-2 disposition record.
- Reviewer B independently rechecked the complete diff and found no remaining
  in-scope issue. Reviewer A granted final clearance after confirming the
  completed review record. No P0-P3 finding remains.

## Publication and outcome

- Proposed files: `CHANGELOG.md`, `MENTAT_OPERATIONS_IMPLEMENTATION_PLAN.md`,
  `public/index.html`, `public/app.js`, `public/styles.css`,
  `scripts/browser_smoke.mjs`, `tests/test_input_focus_continuity.py`,
  `tests/test_visual_contract.py`, `tests/test_home_operations_ui.py`, and this
  review log.
- Commit/PR title: `Retire Classic appearance layout`.
- Classification: Ready for publication.
