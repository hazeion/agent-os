# Feature Slice Review: Agent Console layout polish

Status: Ready for publication
Slice: `agent-console-layout-polish`
Date: `2026-08-29`
Review log: `reviews/2026-08-29-agent-console-layout-polish.md`

## Slice contract

### Goal

Make the large-screen Agent Console visually balanced and remove unnecessary
space without changing any Agent, Conversation, Run, Project, Task, provider,
or runtime behavior.

### In scope

- Give the collapsed right activity rail the effective width needed to center
  the Conversation workspace exactly when both rails are collapsed, while
  retaining equal 12-pixel panel gaps.
- Keep Agent configuration primary and render Agent, Provider, Model, and
  Effort as compact borderless inline controls without overlap.
- Stop the activity rail from stretching to a long transcript's full height;
  keep it content-led, viewport-bounded, and independently scrollable when its
  contents exceed the available desktop height.
- Collapse the Provider connections card area after a verified empty,
  unsupported, unavailable, or error result while retaining a stable bounded
  loading placeholder and unchanged real provider cards.
- Preserve the established phone layout, touch targets, high contrast,
  reduced motion, focus behavior, and rail action labels.

### Out of scope

- Changes to provider inventory, Agent configuration mutations, API shapes,
  runtime authority, Project or Task behavior, transcript rendering, Runs
  metadata, navigation order, or data storage.
- New cards, component libraries, animation systems, themes, or settings.
- Redesigning the mobile activity rail into a separate sheet.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | At 1680 and 2560 pixels, both collapsed rails leave equal 12-pixel inner gaps and the center panel midpoint equals the viewport midpoint. | CSS contract plus production geometry measurements. | Passed |
| AC-2 | At 1440 and 1024 pixels, all four composer configuration labels and values remain readable, compact, and non-overlapping; at 390 pixels the existing two-column 44-pixel controls remain intact. | CSS contract, DOM rectangles, desktop/compact/phone browser screenshots. | Passed |
| AC-3 | The expanded desktop activity rail no longer equals a long transcript's height, remains viewport-bounded, and scrolls internally when needed; the phone rail remains a normal single-column section. | CSS contract and production geometry/scroll checks. | Passed |
| AC-4 | Provider loading retains its placeholder height, while settled empty and failure states reserve no empty card area; a real provider card still renders normally. | Browser smoke state matrix and CSS contract. | Passed |
| AC-5 | Home, Agents, Projects & Tasks, and Runs keep zero page-level horizontal overflow and no new console errors at representative widths. | Production browser smoke and manual visual inspection. | Passed |
| AC-6 | Focused tests, full web checks, production build, Lighthouse, and two independent adversarial reviews pass. | Recorded verification and review results. | Passed |

### Constraints and recovery

- Safety: CSS and browser-test changes only; no authority or mutation boundary
  changes.
- Compatibility: preserve current markup, accessible names, fixed APIs, and
  mobile behavior.
- Rendered behavior: fewer boxes, compact text-led configuration, balanced
  collapsed rails, and no transcript-height empty rail.
- Rollback or recovery: revert the isolated layout commit; no data migration or
  recovery action is involved.
- Documentation targets: this review log and `CHANGELOG.md`; the roadmap and
  architecture do not change because no product capability changes.
- Version-control strategy: isolated `codex/agent-console-layout-polish`
  branch from `f09112b`, ready PR to `main` after verification and review.
- Tracker: https://github.com/hazeion/agent-os/issues/162

### Scope discussion and approval

- Recommendation and rationale: make the smallest shared CSS and smoke-test
  corrections that address the measured defects. Preserve every existing
  capability and markup boundary.
- Alternatives considered: reducing the left rail to 60 pixels would crowd its
  icons; widening the collapsed right rail to 44 pixels makes its 32-pixel
  outer inset match the left rail's effective 76-pixel footprint. Removing
  configuration controls would break supported Hermes selection, so the
  controls remain functional but visually compact.
- User decisions: explicitly approved all four fixes and requested fewer boxes
  and less space for Provider, Model, and Effort. Earlier standing authorization
  covers this scope, tests, integration, pushes, and merges.
- Approved at: 2026-08-29.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Both collapsed rails shift the center panel eight pixels right because the effective side footprints are 76 and 60 pixels. | Exact CSS tokens plus 1680/2560 production DOM geometry. | True viewport centering and equal inner gaps. | Browser pixels may differ fractionally across platforms. |
| AC-2 | At 1024 pixels, configuration labels collapse to zero width and selects to 38-57 pixels; the explanation overlaps them. | Contract assertions and bounding-rectangle overlap checks at three widths. | The actual regression is absent, not merely hidden. | Native select glyphs vary by platform. |
| AC-3 | At 1440 pixels the rail stretches to 3,676 pixels; at 1024 it stretches to 4,150 pixels. | Rail height, max-height, overflow, and sticky-position checks on a long Conversation. | Long transcript height no longer controls the rail. | Short empty Conversations are checked separately by existing tests. |
| AC-4 | Settled empty provider state retains the loading list's 188-pixel minimum. | Existing production smoke extended to distinguish loading from settled states. | Empty/failure space collapses while loading remains stable and ready cards remain visible. | Does not alter provider data behavior. |
| AC-5 | No current page-level overflow or console errors; visual defects are localized. | Existing full production smoke plus screenshots and DOM clipping scan. | No cross-route responsive regression. | Manual review is not a full assistive-technology audit. |
| AC-6 | No focused regression coverage for these exact geometry contracts. | Focused Node tests, full web check, build, Lighthouse, and two reviewers. | Integration readiness. | GitHub CI remains the final cross-platform gate after publication. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Live production visual inspection | Chromium 152, 1440/1024/390 | Fail | Composer overlap at desktop/compact; mobile correct. |
| Large-screen rail geometry | Chromium 152, 1680/2560 | Fail | Inner gaps are both 12 px, but both-collapsed center is 8 px right of viewport center. |
| Long-Conversation rail measurement | Chromium 152, 1440/1024 | Fail | Rail height equals full transcript: 3,676/4,150 px. |
| Provider empty-state inspection | Chromium 152, desktop/phone | Fail | Settled empty list reserves 188 px and produces a large blank section. |
| Page overflow and console scan | Chromium 152, all four routes | Pass | Zero horizontal overflow and no browser warnings/errors. |

### Test discussion and approval

- User questions and decisions: user requested implementation of the measured
  fixes and explicitly prioritized compact inline Provider/Model/Effort text.
- Accepted coverage gaps: no separate screen-reader application audit; existing
  semantic DOM, Lighthouse, focus, and keyboard checks remain required.
- Approved at: 2026-08-29 under the user's explicit request and standing test
  authorization.

## Implementation record

### Changes

- Increased the collapsed activity track from 28 to 44 pixels. With the fixed
  32-pixel outer inset, its effective 76-pixel footprint now matches the
  collapsed left rail.
- Made the composer configuration flex-wrap at every desktop width, kept the
  fields borderless and inline, and restored the established two-column phone
  layout with four 44-pixel controls.
- Made the desktop activity rail sticky, content-led, and capped at the
  available 720-pixel viewport budget. Its content scrolls internally only when
  required; mobile restores normal document flow.
- Limited the 188-pixel Provider connections reservation to loading. Settled
  empty, unsupported, unavailable, and error lists are removed from layout;
  real provider cards are unchanged.
- Strengthened production browser smoke with configuration overlap/width,
  non-stretched rail, exact 1680/2560 collapsed-centering, and state-specific
  Provider-list geometry checks.

### Deviations and decisions

- Lighthouse initially produced two noisy mobile medians of 94 on the branch.
  An unchanged-main run against the exact same disposable data root passed at
  96, and a cooled exact-branch rerun passed at 97 with all non-performance
  categories at 100. No threshold or test was weakened.
- The first GitHub Node runtime foundation run exposed a browser-smoke race:
  after the two new large-screen navigation passes, the phone drawer click
  could run before Home finished hydrating. The smoke now waits for the bridge
  ready projection before testing drawer interaction. The unchanged UI test
  then passed locally; no production behavior or timeout was changed.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `node --import ./web/scripts/register-test-typescript.mjs --test web/tests/shell-contract.test.ts` | Node 24.19 | 0 | 8 pass | Includes new layout contract. |
| `python3 -m unittest tests.test_node_runtime_foundation -v` | Python 3.13 | 0 | 3 pass | Packaging/browser contract remains valid. |
| `node scripts/web_foundation_smoke.mjs` | Production standalone, Chromium 152 | 0 | 1 complete smoke | Six standard viewports, two centering viewports, all routes and provider states pass. |
| Browser smoke after CI hydration-race fix | Production standalone, Chromium 152 | 0 | 1 complete smoke | Drawer interaction now begins only after the hydrated ready projection; the full smoke passes unchanged. |
| `npm --prefix web run check` | Node 24.19 | 0 | 228 pass | Lint and typecheck also pass. |
| `node web/scripts/run-next.mjs build --webpack && node web/scripts/prepare-standalone.mjs` | Node 24.19 | 0 | Build pass | Home and Projects & Tasks remain dynamic; Agents and Runs remain static. |
| `npm --prefix web run performance:agent-console` | Production, 7 samples | 0 | Gate pass | Optimistic 10.4 ms; accepted 120 ms; stream 5.4 ms; loaded tab 10.6 ms. |
| `npm --prefix web run lighthouse:gate` | Production, 3 desktop + 3 mobile | 0 | Gate pass | Median 100 desktop, 97 mobile; accessibility, best practices, SEO all 100. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| Complete Python suite | Python 3.13, host loopback access | 0 | 1,784 pass, 5 skip, 0 fail/error | Ran 1,789 tests in 662.090 seconds. The sandbox-only attempt was stopped after loopback restrictions; no errors reproduced on the host run. |

### Rendered or manual behavior

- Exact collapsed geometry passed at 1680 and 2560 pixels: 12-pixel left and
  right gaps, 44-pixel right rail, and center midpoints exactly 840 and 1280.
- Composer configuration has no intersecting rectangles. At 1024 pixels the
  four label widths are 275, 170, 200, and 175 pixels; at 390 pixels all four
  selects are 149 pixels wide and 44 pixels tall.
- Desktop fixture rail is 349 pixels high beside an 831-pixel center panel and
  carries a 710-pixel maximum at a 900-pixel viewport.
- Provider loading list remains 188 pixels high. Settled empty and all three
  failure lists measure zero; the real provider projection still renders.
- Home, Agents, Projects & Tasks, and Runs have zero page-level horizontal
  overflow at every tested width. Browser console/error collection is empty.

## Adversarial review

### Round 1

| Reviewer lens | Result | Findings or evidence gaps | Resolution |
| --- | --- | --- | --- |
| Correctness and safety | Clean | No P0-P2 findings. No evidence gap. Provider cards, mobile flow, touch sizing, focus styling, and interaction semantics remain intact. | No change required. |
| Product behavior and compatibility | Clean | No P0-P2 findings. No evidence gap. Responsive layout, provider states, focus behavior, and activity rail behavior match the contract. | No change required. |

Both reviews were independent and read-only. No reviewer disagreement remains.

### Round 2

The reviewers independently inspected the single browser-smoke readiness wait
added after the first CI run exposed a hydration race.

| Reviewer lens | Result | Findings or evidence gaps | Resolution |
| --- | --- | --- | --- |
| Correctness and safety | Clean | The bounded ready-state wait proves shell initialization and does not mask an unavailable bridge or weaken drawer assertions. | No change required. |
| Product behavior and compatibility | Clean | Without hydration the status remains checking, so the test still fails closed. The full smoke and Node foundation rerun close the evidence gap. | No change required. |

## Documentation updates

- Roadmap: not applicable; no slice sequence or capability change.
- Changelog: updated with the four visible layout corrections.
- Architecture/operator docs: not applicable unless implementation changes a
  durable rendered rule.
- Project/session notes: this review log.
- Rendered design contract: `MENTAT_WEB_DESIGN.md` now records compact inline
  configuration, bounded desktop activity, symmetric collapsed footprints, and
  compact settled empty states.
- Documentation verification: full web checks and `git diff --check` pass.

## Publication gate

- Proposed files: `CHANGELOG.md`, `MENTAT_WEB_DESIGN.md`,
  `reviews/2026-08-29-agent-console-layout-polish.md`,
  `scripts/web_foundation_smoke.mjs`, `web/src/app/globals.css`, and
  `web/tests/shell-contract.test.ts`.
- Branch and base: `codex/agent-console-layout-polish` to `main`.
- Commit message: `fix: polish Agent Console layout`.
- PR title: `Polish Agent Console layout`.
- PR summary: balance collapsed rails, compact composer configuration, bound
  the activity rail, and remove empty provider space.
- Unresolved risks: none identified by either adversarial reviewer.
- User authorization and scope: approved implementation and standing
  publication authorization; the repository workflow's final publication
  packet will still be presented before staging.
- Commit hash: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: Pending.
- Acceptance criteria summary: Pending.
- Potential bugs or untested paths: Pending.
- Remaining reviewer dissent: Pending.
- Compatibility/migration/rollback concerns: CSS-only rollback.
- User decision: Pending outcome review.
- Next slice authorized: No
