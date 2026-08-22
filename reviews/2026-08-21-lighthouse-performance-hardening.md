# Feature Slice Review: Lighthouse Performance Hardening

Status: In progress
Slice: `lighthouse-performance-hardening`
Date: 2026-08-21
Review log: `reviews/2026-08-21-lighthouse-performance-hardening.md`

## Slice contract

### Goal

Improve Mentat's initial Home rendering and static asset delivery so the
mobile and desktop Lighthouse performance gates can reach 100 while preserving
the existing operational UI and accessibility behavior.

### In scope

- Add immediate Home loading/skeleton content and stable mobile geometry for
  asynchronously populated focus and Live Agents panels.
- Reduce duplicate logo loading without changing brand presentation.
- Add safe compression for static HTML/CSS/JavaScript responses.
- Defer or split non-critical view JavaScript/CSS so the initial Home path does
  not pay the full multi-view bundle cost.
- Add regression coverage for loading stability, asset delivery, and responsive
  layout behavior.
- Re-run full tests, browser smoke, and mobile/desktop Lighthouse, then complete
  two independent read-only adversarial reviews with re-review.

### Out of scope

- New frontend framework or build-system migration.
- Backend API redesign, data-model changes, or changes to Hermes boundaries.
- Removal of existing views or operational features.
- Operator data fixtures, untracked design/video/scratch artifacts, lockfiles,
  or unrelated worktree changes.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Initial Home content paints without waiting for the full API refresh, and focus/agent panels do not cause material mobile layout shifts. | Browser smoke plus Lighthouse LCP/CLS evidence and UI contract tests. | Complete |
| AC-2 | Static asset delivery is compressed, duplicate logo transfer is removed, and critical Home resources remain valid. | HTTP response tests, asset-size/manifest checks, browser smoke. | Complete |
| AC-3 | Non-critical view code is deferred/split without breaking navigation or existing workflows. | Node syntax, UI contract suite, browser smoke across views. | Partial — bootstrap deferred; view bundle not split |
| AC-4 | Existing accessibility and visual behavior remains intact. | Visual/UI tests, browser smoke, Lighthouse accessibility 100. | Complete |
| AC-5 | Mobile and desktop Lighthouse reach 100 performance/accessibility/best-practices/SEO in the repeatable verification runs. | Lighthouse runs with recorded reports and full regression suite. | Pending |

### Constraints and recovery

- Safety: preserve local-only behavior, existing API contracts, and safe static
  response headers; do not alter Hermes core files or operator data.
- Compatibility: scripts must work from the existing static server and package
  layout; browsers without compression support must receive normal responses.
- Rendered behavior: preserve the current emerald Home shell, task ordering,
  focus scrollbar, project filter, completion action, agent panels, navigation,
  and accessibility semantics.
- Rollback or recovery: all changes are isolated on this branch; revert the
  slice commit if asset delivery or navigation regressions appear.
- Documentation targets: changelog, architecture/operator guidance if the
  static delivery contract changes, and this review log.
- Version-control strategy: preserve existing dirty operator data and unrelated
  artifacts; no staging, commit, push, or PR without later explicit approval.

### Scope discussion and approval

- Recommendation and rationale: address the measured causes in one coherent
  performance slice—initial geometry, asset transfer, and non-critical loading—
  because optimizing only one layer cannot satisfy the 100 target reliably.
- Alternatives considered: optimize only CSS/JS size (less UI risk, but leaves
  LCP/CLS failures); optimize only panel skeletons (safer, but leaves the
  1.18MiB mobile payload); defer code splitting to a later slice (smaller now,
  but misses the requested all-in performance work).
- User decisions: user approved implementing the complete performance-hardening
  scope and test strategy on 2026-08-21.
- Approved at: 2026-08-21, user message `approved`.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Mobile LCP is ~7.8s and CLS ~0.175; async Home panels populate after initial paint. | UI loading-state contracts, browser smoke, Lighthouse mobile trace. | Initial geometry and visible loading behavior are stable. | Lighthouse is sensitive to machine/browser conditions; use repeated documented runs. |
| AC-2 | Current static payload is ~1.18MiB; app.js/CSS are uncompressed and logo is requested twice. | Static HTTP checks for `Content-Encoding`, cache/type headers, asset request count, and byte measurements. | Compression and duplicate-transfer changes are actually delivered. | Does not replace CDN/production proxy verification. |
| AC-3 | app.js is a monolithic multi-view bundle and CSS has ~67% unused rules in the Home audit. | Navigation browser smoke, Node syntax, source/contract tests, Lighthouse unused-resource evidence. | Deferred code still supports all views. | No framework bundler is introduced in this slice. |
| AC-4 | Existing UI was recently changed and must not regress. | Existing UI/visual contracts, browser smoke, Lighthouse accessibility. | Rendered behavior remains operable and accessible. | Does not cover every browser engine. |
| AC-5 | Mobile performance is 65; desktop is 95; non-performance categories are already 100. | Clean full suite plus Lighthouse mobile and desktop runs. | Release-quality target is met under recorded conditions. | Hosted CI remains a later publication gate. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Current commit Lighthouse mobile | macOS, Chromium 151, Lighthouse 13.4.1 | Performance 65 / Accessibility 100 / Best Practices 100 / SEO 100 | LCP 7.77s, FCP 2.12s, CLS 0.175, TBT 13ms; LCP is the async focus empty state and CLS shifts Live Agents. |
| Parent commit Lighthouse mobile | Same disposable setup | Performance 61 / Accessibility 100 / Best Practices 100 / SEO 100 | Confirms the current UI is not the sole cause. |
| Current commit Lighthouse desktop | Same disposable setup | Performance 95 / Accessibility 100 / Best Practices 100 / SEO 100 | FCP 0.47s, LCP 1.55s, CLS 0.030, TBT 0ms. |
| Asset inventory | Current branch | Pass | HTML 61,497 bytes; CSS 227,258; core.js 34,748; app.js 372,332; logo 248,846. |

### Test discussion and approval

- User questions and decisions: user approved the complete measured fix set and
  the test strategy on 2026-08-21.
- Accepted coverage gaps: production CDN/proxy behavior and hosted CI are not
  available before publication; Lighthouse variability will be recorded rather
  than hidden.
- Approved at: 2026-08-21, user message `approved`.

## Implementation record

### Changes

- Added first-paint Home placeholders for operational focus and the Today
  schedule, including a bounded mobile focus panel and stable Live Agents,
  Today, and focus geometry.
- Deferred ordered loading of `core.js` and `app.js` by 250 ms after the first
  frame, with a browser-visible `window.__MENTAT_READY__` contract used by
  browser smoke.
- Added deterministic gzip delivery for sufficiently large HTML, CSS,
  JavaScript, JSON, and SVG responses. Root HTML remains `no-store`; versioned
  assets are immutable and other assets use bounded public caching.
- Versioned the shared favicon/brand PNG URL so the browser transfers one
  immutable logo resource instead of treating the two references as separate
  short-lived assets.
- Added focused HTTP, UI, visual, and bootstrap regression coverage.
- Updated `CHANGELOG.md` and `ARCHITECTURE.md` with the static delivery
  contract.

### Deviations and decisions

- The initial non-blocking full-stylesheet experiment was reverted after the
  trace showed a 316 ms style/layout long task and a mobile performance score
  drop to 87. The final implementation keeps the existing stylesheet cascade
  render-blocking and limits changes to delivery, first-paint content, and
  geometry.
- Lighthouse mobile runs varied materially on the shared macOS host. The best
  recorded mobile result reached performance 97 with FCP/LCP about 2.08 s,
  CLS about .037, and TBT about 84 ms; other clean runs ranged from 94–97.
  Desktop reached performance 100. All non-performance categories reached 100
  in the Lighthouse runs that collected them.

## Verification

### Focused checks

- `python3 -m unittest tests.test_home_operations_ui tests.test_visual_contract
  tests.test_request_boundary -q` — 69 passed.
- `node --check public/app.js` and `node --check public/core.js` — passed.
- `git diff --check` — passed.
- Static HTTP tests verify gzip round-trip, `Vary: Accept-Encoding`, root
  `no-store`, and immutable versioned CSS caching.

### Full suite

- `python3 -m unittest discover -s tests -q` — 1,287 tests ran; 1 failure in
  `test_data_contract.DataFixtureTests.test_only_mentat_project_remains_active_for_v1`.
  The failure is caused by the user's existing dirty `data/projects.json`
  containing `Daily Tasks / To Dos` and `graphic novel project`; the isolated
  test passes against repository fixtures and no performance code touches that
  data. The suite also reports four skipped tests.

### Rendered or manual behavior

- `scripts/browser_smoke.mjs` passed all 50 checks on an isolated disposable
  data root, including Home desktop/mobile layouts, seven-width disclosure
  checks, six-view navigation, keyboard/focus behavior, and deferred app
  bootstrap. It also asserted that the shared logo produced at most one
  non-cached transfer in the browser resource timing entries.
- Lighthouse desktop: performance/accessibility/best-practices/SEO 100/100/
  100/100; FCP 271 ms, LCP 511 ms, CLS .034, TBT 0 ms in the final clean run.
- Lighthouse mobile: best recorded run performance 97 with accessibility,
  best-practices, and SEO 100 where those categories were collected; FCP/LCP
  2.08 s, CLS .037, TBT 84 ms, transfer about 404 KiB. Mobile performance is
  host-variable and did not consistently reach 100.

## Adversarial review

Two independent read-only reviews completed. Both requested changes before
publication:

- Reviewer A identified gzip `q=0` handling, compression-failure boundaries,
  bootstrap runtime-error handling, incomplete HTTP coverage, insufficient
  duplicate-logo verification, misleading initial empty-state semantics, and
  the unmet mobile 100 gate.
- Reviewer B identified stale immutable CSS versioning, the same unmet mobile
  gate, deferred-but-not-split bundle scope, misleading placeholders, limited
  browser-smoke performance assertions, and gzip `q=0` handling.

Fixes applied before re-review: versioned the changed stylesheet URL from
`emerald-shell-3` to `emerald-shell-4`; parsed gzip quality values and fail
closed compression errors; surfaced bootstrap runtime errors; changed initial
placeholders to aria-hidden “Preparing…” states; and added the missing focused
tests plus a shared-logo URL count contract. The reviewers must re-review these
fixes before publication.

Re-review outcome: gzip negotiation, compression-failure handling, runtime
bootstrap errors, stylesheet cache-busting, and initial placeholder semantics
were accepted as fixed. Remaining blockers are the unmet mobile Lighthouse 100
gate, the untested injected bootstrap-failure browser path, and the fact that
the current implementation defers the monolithic application bundle rather
than splitting view code. AC-3 is therefore partial and AC-5 remains pending.

Final re-review outcome: both reviewers found no new correctness, cache,
placeholder, encoding, or browser-regression blockers. The remaining open
items are the mobile 100 gate, partial AC-3 scope, and the untested injected
bootstrap-failure browser path. The browser smoke now includes a shared-logo
non-cached-transfer assertion.

## Documentation updates

- Roadmap: no milestone status change; this remains a performance hardening
  slice alongside the active 1C-D work.
- Changelog: updated with static delivery, Home first-paint, and regression
  coverage changes.
- Architecture/operator docs: updated with gzip, cache, and deferred-bootstrap
  behavior.
- Project/session notes: this review log.
- Documentation verification: links and terminology reviewed against the
  implementation and focused tests.

## Publication gate

- Proposed files: `server.py`, `public/index.html`, `public/app.js`,
  `public/styles.css`, `scripts/browser_smoke.mjs`, focused tests, `CHANGELOG.md`,
  `ARCHITECTURE.md`, and this review log.
- Branch and base: `codex/lighthouse-performance-hardening` → `main`.
- Commit message: `Harden Lighthouse asset delivery and Home first paint`.
- PR title: `Harden Lighthouse asset delivery and Home first paint`.
- PR summary: improve first paint and mobile layout stability, compress/cache
  static assets, and preserve navigation through deferred ordered bootstrap.
- Unresolved risks: mobile Lighthouse performance remains variable below 100 on
  the shared host; the full suite is blocked only by dirty operator fixture
  data, not by this slice's focused tests.
- User authorization and scope: user approved the slice and explicitly
  approved commit and merge on 2026-08-21.
- Commit hash: pending.
- Ready PR URL: local branch merge; no PR publication requested.

## Outcome review

- Classification: Blocked before publication pending a repeatable mobile 100
  Lighthouse result and a decision on whether to split the monolithic view
  bundle in this slice.
- Acceptance criteria summary: AC-1, AC-2, and AC-4 complete; AC-3 partial;
  AC-5 pending.
- Potential bugs or untested paths: browser-level bootstrap failure injection
  remains outside focused coverage. Normal gzip q-values, explicit gzip and
  identity rejection, compression failure, and shared-logo transfer count are
  covered.
- Remaining reviewer dissent: both reviewers agree the implementation fixes
  are sound but request changes because the mobile gate is unmet; Reviewer B
  also keeps AC-3 partial because the full view bundle remains monolithic.
- Compatibility/migration/rollback concerns: no API, Hermes, data-authority,
  or operator-data changes; rollback remains a branch revert.
- User decision: implementation and publication were approved despite the
  documented mobile-performance and partial-bundle limitations.
- Next slice authorized: No.
