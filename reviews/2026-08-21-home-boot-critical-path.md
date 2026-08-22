# Feature Slice Review: Home Boot Critical Path

Status: Ready for publication
Slice: `home-boot-critical-path` (Pivot 1C-D performance hardening)
Date: 2026-08-21
Review log: `reviews/2026-08-21-home-boot-critical-path.md`

## Slice contract

### Goal

Make Mentat Home begin its client boot work without the current arbitrary 250 ms
delay or sequential script-download waterfall, while retaining ordered execution
and the existing visible boot-failure state.

### In scope

- Replace the dynamic `core.js` then `app.js` loader with parser-discovered,
  ordered `defer` scripts so both assets can download during HTML parsing.
- Remove the 250 ms delayed boot scheduling path.
- Preserve the pre-theme initialization, existing Home markup, API calls,
  browser-visible behavior, and error affordance when either script fails.
- Add regression coverage for ordered asset delivery and bounded boot failure.
- Repeat the same three-run mobile Lighthouse configuration and record the
  outcome against the current 85/85/85 baseline.

### Out of scope

- CSS file splitting, critical-CSS extraction, or a build pipeline.
- Splitting `app.js` by feature/view, a framework migration, or visual redesign.
- Hermes/API/data-model/SQLite changes.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Home no longer waits 250 ms or a `core.js`-then-`app.js` network waterfall before client boot begins. | Static contract plus browser resource timing. | Met |
| AC-2 | `core.js` executes before `app.js`; normal Home boot, theme initialization, and existing loading/error states remain usable. | Browser smoke and focused UI tests. | Met |
| AC-3 | A failed core or application asset still exposes the existing bounded Home boot-failure message. | Controlled browser asset-failure regression. | Met |
| AC-4 | Three equivalent mobile audits show a median Performance score of at least 88 or a documented measurable LCP improvement; the overall 1C-D 100 gate remains explicit. | Repeated Lighthouse evidence. | Met (LCP improvement) |

### Constraints and recovery

- Safety: no API, persistence, runtime, or Hermes behavior changes.
- Compatibility: retain static-frontend support on the project’s supported
  browsers; preserve execution ordering and no-JavaScript Home markup.
- Rendered behavior: avoid FOUC, keep the selected theme before first paint,
  and preserve a visible boot-failure state.
- Rollback or recovery: revert the isolated branch commit; no data migration or
  persistent-format change is involved.
- Documentation targets: this review log and `CHANGELOG.md`; roadmap only if
  the 1C-D status changes.
- Version-control strategy: `codex/home-boot-critical-path` from merged
  `origin/main`; preserve the user-owned local data and untracked artifacts.

### Scope discussion and approval

- Recommendation and rationale: Lighthouse’s current LCP candidate is Home
  focus-row text. TTFB is about 9 ms, while the current page intentionally
  waits 250 ms before dynamically fetching `core.js`, then fetches `app.js`
  only after `core.js` completes. Replacing that loader with ordered `defer`
  assets is the smallest direct reduction to initial client delivery.
- Alternatives considered: critical/noncritical CSS split (larger selector and
  responsive-ordering risk); view-level JavaScript split (larger ownership
  extraction); DOM redesign (not necessary for this measured bottleneck).
- User decisions: user asked to move to the next slice and previously directed
  that future approval gates should be assumed. This records that process
  exception for the contract, test strategy, and later publication gates while
  preserving evidence and reporting.
- Approved at: 2026-08-21, user messages “assume my approval and any future
  approvals needed assume my approval on those too” and “let’s move onto th[e]
  next slice”.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Inline loader uses `setTimeout(boot, 250)` and sequential dynamic scripts. | Static source test plus browser resource-timing inspection. | Assets are parser-discovered and no artificial scheduler delay remains. | Does not isolate every browser cache/network condition. |
| AC-2 | Dynamic loader currently guarantees ordering implicitly through chained promises. | Existing browser smoke plus a focused boot-order regression. | `app.js` remains dependent on, but executes after, `core.js`. | Chromium does not substitute for every supported browser. |
| AC-3 | Existing boot error is tied to the dynamic loader promise chain. | Controlled browser request failures for both boot assets. | User sees bounded recovery copy instead of an inert loading state when either dependency fails. | Uses CDP interception rather than a real cache/network failure. |
| AC-4 | Current fixed local mobile median is 85 with a 3.477 s LCP. | Three fixed-configuration Lighthouse audits. | Measures the delivery change consistently. | Local simulated audits cannot guarantee production-network score. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Source inspection | merged `main`, static frontend | Gap confirmed | Inline boot loader delays 250 ms, requests `core.js`, then requests `app.js` after it loads. |
| Three mobile Lighthouse audits | Chromium/Lighthouse local simulated mobile, disposable data | Performance 85 / 85 / 85 | FCP about 0.927 s, LCP about 3.477 s, TTFB about 9 ms; all non-performance categories 100. |
| Lighthouse asset diagnostics | same | Gap confirmed | `app.js` has about 54 KiB estimated unused JavaScript and the stylesheet about 25 KiB estimated unused CSS; those are intentionally deferred to later slices. |

### Test discussion and approval

- User questions and decisions: future approvals are pre-authorized as recorded
  above; CI and rendered evidence remain mandatory.
- Accepted coverage gaps: no hosted/mobile-device audit; CDP simulates asset
  failure.
- Approved at: 2026-08-21 under the recorded process exception.

## Implementation record

### Changes

- Moved the bootstrap-state and bounded boot-error listener into `<head>` after
  the saved-theme pre-initializer.
- Replaced the delayed dynamic loader with source-ordered `<script defer>`
  tags for `core.js` then `app.js`. Browsers can discover both resources while
  parsing the document while preserving dependency order at execution.
- Retained the prior runtime-error and unhandled-rejection handling, added
  capture handling for a failed core/application resource, and deferred the
  visible error update until Home markup exists.
- Extended the browser smoke with parser-discovery timing assertions and
  controlled `core.js` and `app.js` request failures that must render the
  existing retry message. Updated static UI/visual contracts for the new
  delivery mechanism.

### Deviations and decisions

- The planned 88 median score was not reached. The contract permits a
  measurable LCP improvement instead: median performance is 87 and median LCP
  improved by about 145 ms. The 1C-D 100-performance milestone remains open.

## Verification

### Focused checks

| Command or action | Result |
| --- | --- |
| `node --check scripts/browser_smoke.mjs` | Passed. |
| `python3 -m unittest tests.test_visual_contract tests.test_home_operations_ui tests.test_next_phase_readiness -q` | Passed: 54 tests. |
| Browser smoke against disposable loopback data and Chromium | Passed: parser-discovered `core.js`/`app.js`, forced `core.js` and `app.js` failure messages, core/deferred rendering, and existing responsive workflow coverage. |
| `git diff --check` | Passed. |

### Lighthouse evidence

Same local simulated-mobile command/configuration as the baseline, against a
disposable loopback server:

| Run | Performance | Accessibility | Best Practices | SEO | FCP | LCP | TBT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 87 | 100 | 100 | 100 | 0.926 s | 3.326 s | 53 ms |
| 2 | 86 | 100 | 100 | 100 | 0.940 s | 3.340 s | 33 ms |
| 3 | 87 | 100 | 100 | 100 | 0.933 s | 3.333 s | 23 ms |

Median: Performance 87; LCP 3.333 s. Compared with the 3.477 s baseline,
this is about 145 ms faster. Local result artifacts are intentionally kept
outside the tracked repository.

### Full suite

`python3 -m unittest discover -s tests -q` entered pre-existing server and
SQLite stress tests, including `test_supported_mutations_roll_back_when_the_clock_moves_backward`, and was manually interrupted after several quiet minutes.
The previously noisy restore-inventory test passes in isolation. This is an
unresolved full-suite execution limitation, not a reported success.

### Rendered or manual behavior

The browser smoke exercised the normal Home boot, saved theme reload, controlled
failed core and application assets, Home core/deferred request behavior,
responsive desktop and mobile layouts, and accessibility interactions.

## Adversarial review

### Round 1

- Correctness/safety reviewer: found a medium blocking test gap: the controlled
  asset-failure regression covered only `core.js`, not `app.js`, so AC-3 had
  incomplete evidence. It also noted that the timing inspection alone does not
  prove parser discovery, which is covered together with the static source
  contract. The incomplete full suite remains an out-of-scope verification
  limitation.
- Compatibility/product reviewer: independently found the same in-scope gap as
  P2/non-blocking and recommended a forced `app.js` failure plus clean reload.
  It reported no other blocking findings.
- Disposition: corroborated in-scope finding accepted. The browser smoke now
  independently fails both assets and requires the same bounded alert for each.
  Focused rechecks passed.

### Round 2

- Both reviewers found the runtime correction adequate, but identified the
  review log's stale core-only wording as an in-scope audit-record defect.
- Disposition: corroborated documentation finding accepted. The strategy,
  focused evidence, and rendered-behavior record now state that both assets
  are forced to fail. A final independent re-review is pending.

### Round 3

- Correctness/safety reviewer: No findings.
- Compatibility/product reviewer: No findings.
- Disposition: review gate complete; no unresolved reviewer findings.

## Documentation updates

- Roadmap: no status change yet.
- Changelog: updated with the parser-discovered deferred bootstrap and measured
  LCP improvement.
- Architecture/operator docs: not expected for this static delivery change.

## Publication gate

- Proposed files: `public/index.html`, `scripts/browser_smoke.mjs`,
  `tests/test_home_operations_ui.py`, `tests/test_visual_contract.py`,
  `CHANGELOG.md`, and this review log. Explicitly exclude local data and
  unrelated untracked artifacts.
- Branch and base: `codex/home-boot-critical-path` → `main`.
- Commit message: `Improve Home boot critical path`.
- PR title: `Improve Home boot critical path`.
- User authorization and scope: pre-authorized under the recorded process
  exception; exact evidence and file boundary will be reported before action.

## Outcome review

Implementation, acceptance criteria, and independent review are complete;
publication is next. Measured limitation: this delivery slice reaches a median
Performance score of 87, not the milestone's 100; it delivers a repeatable
145 ms median LCP improvement and leaves CSS/JavaScript payload reduction for
later 1C-D work.
