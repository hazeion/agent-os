# Feature Slice Review: Mobile Control Cascade Continuity

Status: Successful
Slice: `mobile-control-cascade-continuity`
Date: `2026-07-31`
Review log: `reviews/2026-07-31-mobile-control-cascade-continuity.md`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  decisions moving forward.
- Standing approval covers this contract, test strategy, implementation,
  outcome, staging, commit, push, and ready pull request.
- Work remains one reviewed slice at a time, with unrelated user files excluded.

## Slice contract

### Goal

Make the existing 44px phone-control promise win the real CSS cascade for Home
and Agent Console controls in both supported UI shells.

### In scope

- Strengthen only the final phone selectors for the Today project filter and
  schedule link, Agent Console selects and prompt, and Settings theme select.
- Preserve the established 640px breakpoint, sizes, layouts, and theme system.
- Add a deterministic cascade-specific contract, rendered checks, and a
  changelog entry.

### Out of scope

- Desktop or tablet density changes, component redesign, or behavior changes.
- Session-search behavior, Hermes data, credentials, or signing configuration.
- User-owned `data/projects.json` and `design/`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Affected controls compute to at least 44px at 390px in Emerald and Classic. | Rendered browser metrics | Pass |
| AC-2 | Phone layout has no page-wide overflow or newly visible hidden elements. | Rendered browser audit | Pass |
| AC-3 | Desktop/tablet presentation remains unchanged. | Breakpoint inspection and focused contracts | Pass |
| AC-4 | The final mobile selector cannot silently lose to the existing shell-specific component rules. | Cascade-specific visual contract | Pass |
| AC-5 | Two independent adversarial reviewers find no unresolved in-scope regression. | Review record | Pass |

### Constraints and recovery

- Safety: presentation-only CSS and deterministic tests; no application data or
  Hermes behavior.
- Compatibility: cover both `data-ui-shell` values without changing theme
  tokens or component structure.
- Rollback or recovery: revert the slice commit; no migration.
- Version-control strategy: branch
  `codex/mobile-control-cascade-continuity` from `main`; ready PR to `main`.

### Scope discussion and approval

- Recommendation: match the specificity of shell-specific compact control
  rules using the shared shell attribute and existing structural ancestors.
- Alternatives considered: `!important` (unnecessary), globally enlarging
  controls (changes desktop density), or shell-specific duplicate overrides
  (less maintainable).
- User decisions: standing approval for all slices and publication actions.
- Approved at: `2026-07-31` under the recorded process exception.

## Test strategy

| Acceptance criterion | Baseline gap | Planned evidence | Limitation |
| --- | --- | --- | --- |
| AC-1 | At 390px, Emerald Console controls compute to 36–38px. | Measure computed rectangles in both UI shells. | Chrome is the live browser sample. |
| AC-2 | Existing mobile layout is contained. | Check document width and visible `[hidden]` elements. | Samples the audited views. |
| AC-3 | Rule should remain phone-only. | Focused breakpoint contract and rendered desktop check. | Exact viewport samples. |
| AC-4 | Prior test asserted declarations but not winning specificity. | Assert shell-scoped structural selectors and the complete final rule. | Static contract complements live rendering. |
| AC-5 | Specificity changes can have distant effects. | Two independent read-only adversarial reviews. | Reviewers do not edit files. |

### Baseline results

| Check | Result | Notes |
| --- | --- | --- |
| Emerald, 390px | Gap reproduced | Agent select 38px; Console prompt about 39px despite the 44px declaration. |
| CSS inspection | Root cause confirmed | Later mobile selectors lose to earlier Emerald structural selectors. |

### Test discussion and approval

- User questions and decisions: standing approval applies.
- Accepted coverage gaps: exact rendered verification samples Chrome at the
  requested phone breakpoint; deterministic contracts protect both shells.
- Approved at: `2026-07-31` under the recorded process exception.

## Implementation record

### Changes

- Scoped the final phone rule through `:root[data-ui-shell]` and retained the
  existing structural ancestors so its specificity equals or exceeds each
  competing compact-control rule in either shell.
- Added a regression contract that checks source order, competing declarations
  for `!important`, and selector specificity instead of only checking that the
  intended declaration exists.

## Verification record

| Check | Result | Evidence |
| --- | --- | --- |
| `python3 -m unittest tests.test_visual_contract tests.test_input_focus_continuity -v` | Exit 0 | 33 tests passed after the strengthened cascade contract. |
| Local Chrome through the in-app browser, Emerald at 390×844 | Pass | Today project select, schedule link, all three Agent Console selects, and Console prompt each measured 44px. The schedule link rendered as flex. Document width and scroll width were both 390px; zero visible `[hidden]` elements. |
| Local Chrome through the in-app browser, Classic at 390×844 | Pass | The same complete control set each measured 44px. The schedule link rendered as inline-flex. Document width and scroll width were both 390px; zero visible `[hidden]` elements. |
| Local Chrome phone Settings, both shells | Pass | Theme, interface-layout, and contrast selects each measured 44px; preview grid computed `display: none`; no page-wide overflow. |
| Local Chrome through the in-app browser, Emerald at 768×900 | Pass | Compact Today/Console heights remained 36–39px, the theme grid remained visible, document width equaled scroll width, and zero hidden elements became visible. |
| Local Chrome through the in-app browser, Emerald at 1440×1000 | Pass | Today select returned to 36px, Agent select to 38px, and prompt to its existing compact height; theme preview grid computed `display: grid`; document width equaled scroll width. |
| `python3 -m unittest discover -s tests -v` | Exit 1: 908 pass, 2 fail, 4 skip | Both failures are pre-existing machine-state mismatches outside this slice: the local Hermes cron inventory contains zero jobs while its test expects one, and user-owned `data/projects.json` adds `Daily Check` while the tracked fixture contract expects only Mentat. |
| `git diff --check` | Exit 0 | No whitespace errors. |

## Independent reviews

### Round 1

- Correctness reviewer: CSS was correctly scoped and specific enough; blocked
  only because post-change evidence had not yet been written into this log.
- Product/UI reviewer: implementation showed no direct regression; requested
  the same evidence record and a stronger deterministic cascade test.
- Resolution: recorded the live Emerald/Classic phone and desktop measurements;
  expanded the contract to compare source order, `!important`, and specificity
  against every competing compact-control rule. Re-review pending.

### Round 2

- Correctness reviewer: implementation and strengthened contract passed; asked
  that commands, environments, and exit statuses be explicit in the record.
- Product/UI reviewer: implementation and strengthened contract passed; asked
  for the schedule link, every Console select, and interface-layout select to be
  measured explicitly in both shells.
- Resolution: recorded exact commands and exit statuses, then measured the
  complete in-scope control set in local Chrome at 390×844 in Emerald and
  Classic. Every control computed to 44px with contained page width and no
  hidden-state leak.

### Round 3

- Correctness reviewer: no substantive P0–P3 findings; independently confirmed
  the implementation, cascade contract, and reproducible evidence.
- Product/UI reviewer: no substantive P0–P3 findings; independently reran all
  33 focused tests and `git diff --check` successfully.
- Resolution: review gate passed with no unresolved in-scope findings.

## Outcome and publication

- Outcome: successful. The existing 44px phone-control contract now wins in
  Emerald and Classic without changing tablet or desktop density.
- Publication: approved under the standing process exception; commit, push, and
  ready pull request are recorded below after completion.
