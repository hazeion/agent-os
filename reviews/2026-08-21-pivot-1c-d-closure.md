# Feature Slice Review: Pivot 1C-D Closure and Lighthouse Gate Resequencing

Status: Successful
Slice: `pivot-1c-d-closure`
Date: 2026-08-21
Review log: `reviews/2026-08-21-pivot-1c-d-closure.md`

## Slice contract

### Goal

Close Pivot Slice 1C-D after removing the remaining deterministic Home layout
shift, and move the exact repeatable Lighthouse 100/100/100/100 replacement
gate intact to Slice 2A, where the new frontend architecture can satisfy it
without deep throwaway optimization of the legacy compatibility surface.

### In scope

- Reserve stable first-paint geometry for the Home focus list so replacing its
  loading state and initially empty project-filter slot with real Task rows and
  controls does not cause the measured layout shift.
- Add static and rendered-browser regression coverage for loading-to-loaded
  focus-list geometry.
- Amend the pivot roadmap so 1C-D closes on its completed SQLite cleanup,
  compatibility evidence, browser gates, non-performance Lighthouse 100s, and
  explicit performance budgets.
- Promote 2A from provisional to proposed next slice and make repeatable
  Lighthouse 100/100/100/100 a prerequisite for replacing the legacy frontend.
- Update the changelog and this persistent verification record.

### Out of scope

- Splitting or rebuilding legacy `public/app.js` or `public/styles.css` solely
  to optimize a frontend that Slice 2A is designed to replace.
- Implementing Next.js, React, TypeScript, Tailwind, shadcn/ui, Radix, TanStack
  Query, or any 2A application code.
- API, SQLite, migration, runtime, Hermes, Task authority, or operator-data
  changes.
- Including the user's modified `data/projects.json`, `data/tasks.json`, or
  unrelated design, mockup, lockfile, runtime, and video artifacts.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Home focus-list and project-filter geometry remain stable when loading markup is replaced by zero, one, or multiple real Task rows. | Static CSS contract and controlled browser request hold/release. | Met |
| AC-2 | Three equivalent local simulated-mobile Lighthouse runs each retain 100 Accessibility, Best Practices, and SEO; CLS is below 0.10; median Performance is at least 87 with no run below 85; median LCP is at most 3.4 s. | Three recorded Lighthouse reports. | Met |
| AC-3 | The roadmap closes 1C-D without weakening the product target: 2A is the proposed next slice and must achieve repeatable 100/100/100/100 before replacing the legacy frontend. | Roadmap contract tests and review inspection. | Met |
| AC-4 | Existing Home boot, core/deferred rendering, failure recovery, responsive layouts, and accessibility behavior remain intact. | Focused UI tests and complete Chromium browser smoke. | Met |
| AC-5 | Existing SQLite/runtime/Hermes compatibility and safety contracts remain unchanged and the repository verification gate is green. | Full suite, diff inspection, and two independent adversarial reviews. | Met |

### Constraints and recovery

- Safety: no persistence, API, runtime, credential, or Hermes mutation changes.
- Compatibility: preserve the legacy static frontend as the active surface
  until 2A replacement behavior passes its own contract.
- Rendered behavior: keep the current 239 px focus-list viewport, scrollbar,
  responsive row layout, empty state, and keyboard semantics.
- Rollback or recovery: revert the isolated branch commit; there is no data
  migration or persistent-format change.
- Documentation targets: `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`, `CHANGELOG.md`,
  and this review log.
- Version-control strategy: dedicated
  `codex/close-1c-d-performance-gate` branch from synchronized `main`, targeting
  `main`; preserve and exclude unrelated worktree changes.

### Scope discussion and approval

- Recommendation and rationale: the current score is no longer server- or
  Hermes-bound. The repeatable audit shows a single 0.141 shift in
  `#focus-task-list`, while deep legacy asset splitting would overlap the
  upcoming 2A frontend foundation. Fix the real layout defect, retain measured
  budgets, and move the exact 100 target to the frontend that will remain.
- Alternatives considered: keep exact 100 as a 1C-D blocker and deeply split
  the legacy CSS/JavaScript (higher throwaway cost); close immediately without
  fixing CLS (leaves a real visible defect); abandon 100 entirely (contrary to
  the user's target).
- User decisions: user approved the recommendation to amend the contract and
  move forward with the slices. The user's earlier standing direction to assume
  future approvals is recorded as a process exception for contract/test gates;
  evidence, independent review, and exact publication boundaries remain
  mandatory.
- Approved at: 2026-08-21, user message “let’s amend the contract as you have
  suggested and then move forward with the slices”.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Loading content reserves 120 px while the loaded list reaches 239 px, and the empty filter slot gains 72 px during hydration; Lighthouse attributes the resulting 0.141 shift to `#focus-task-list`. | Assert equal list min/max viewport height and reserved filter-slot height; browser-intercept `/api/tasks`, compare loading and loaded geometry. | The first rendered boxes and hydrated boxes occupy the same vertical space. | Chromium plus source contract does not represent every browser engine. |
| AC-2 | Current fixed run is Performance 87/86/87, LCP 3.326/3.340/3.333 s, CLS 0.141, other categories 100. | Three equivalent Lighthouse audits after the change. | The deterministic shift is removed without trading away other quality metrics. | Local simulated audits remain host-variable and are not field telemetry. |
| AC-3 | Roadmap currently says 1C-D is in progress and requires 100/100/100/100 before provisional 2A. | Documentation contract assertions plus direct roadmap inspection. | The gate is deliberately resequenced, not silently dropped. | Does not itself implement 2A. |
| AC-4 | Existing smoke covers boot asset failures, Home priority, responsive layouts, and accessibility but not held-core geometry. | Extend and run full browser smoke plus focused UI contracts. | Existing behavior survives and the new geometry path is rendered. | Headless Chromium is not manual device testing. |
| AC-5 | Full suite has not yet run for this branch. | `python3 -m unittest discover -s tests -q`, syntax checks, diff check, reviewers. | Repository-wide regressions and contract drift are detected. | Hosted CI follows publication. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Current roadmap and review inspection | merged `main` | Gap confirmed | 1C-D remains open solely around the exact Lighthouse performance gate; 2A remains provisional. |
| Three prior equivalent Lighthouse runs | Chromium/Lighthouse simulated mobile, disposable loopback data | 87 / 86 / 87 Performance; other categories 100 | Median LCP 3.333 s, CLS 0.141, TBT 23–53 ms. |
| Lighthouse shift attribution | same | Gap confirmed | One shift; `#focus-task-list` accounts for 0.140968. |
| Lighthouse payload diagnostics | same | Deferred architectural work identified | About 55 KiB unused initial JavaScript and 25 KiB unused CSS; deep splitting belongs with the replacement frontend rather than this closure slice. |

### Test discussion and approval

- User questions and decisions: exact Lighthouse 100 remains the product target
  but moves to the 2A replacement gate. The closure budgets above preserve the
  current repeatable baseline while requiring the known CLS defect to be fixed.
- Accepted coverage gaps: no field telemetry or non-Chromium rendered audit;
  hosted CI runs after publication. The controlled browser scenario hydrates a
  multi-row fixture rather than separately replaying zero and one-row payloads.
  The fixed 239 px list viewport makes row count geometry-independent, and the
  static source contract covers that invariant; this remains a low-risk
  evidence gap rather than a product behavior gap.
- Approved at: 2026-08-21 under the recorded user instruction and process
  exception.

## Implementation record

### Changes

- Added a 239 px minimum height matching the existing focus-list maximum so the
  first-paint loading list and loaded list share one viewport.
- Added a 72 px first-paint reservation for the project-filter slot, matching
  the exact rendered desktop control height discovered by the controlled
  browser test, plus an 80 px phone reservation for the 44 px mobile control.
- Extended the complete browser smoke at desktop and phone widths to pause
  `/api/tasks`, capture loading geometry, release the request, and require
  list/shell/panel geometry to stay within one pixel after real Task rendering.
- Closed 1C-D and promoted 2A to proposed in the canonical roadmap. The exact
  repeatable 100/100/100/100 target is an explicit 2A prerequisite before the
  legacy surface may be replaced.
- Updated the architecture contract test, data-layout status, changelog, and
  this evidence record.

### Deviations and decisions

- The first browser run exposed a 72 px shift even after the list itself was
  stabilized. The initially empty `#focus-scope` slot gained that exact height
  when the Project selector rendered. Reserving the measured slot height was
  inside AC-1 and corrected the actual root cause.
- One initial browser-smoke attempt timed out during an unrelated appearance
  reload. A fresh-profile retry reached the new regression and produced the
  actionable geometry failure above; the final fresh-profile full smoke passed.
- First-round adversarial review found that the 72 px desktop filter-slot
  reservation was eight pixels short at phone width because the phone selector
  is 44 px tall. The phone override now reserves 80 px and the controlled
  browser regression runs at both desktop and phone widths.
- First-round review also found an ambiguity between the roadmap's definition
  of `Complete` as merged and the closure branch showing the intended
  post-merge state. The roadmap now explicitly treats feature-branch status
  changes as proposed until merged `main` makes them canonical.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `node --check scripts/browser_smoke.mjs` | Node 22, macOS | 0 | Pass | Browser regression syntax valid. |
| `python3 -m unittest tests.test_home_operations_ui tests.test_visual_contract tests.test_agent_runtime_architecture tests.test_next_phase_readiness -q` | Python 3.13, macOS | 0 | 58 passed | UI geometry, roadmap, and frontend readiness contracts pass. |
| `git diff --check` | branch worktree | 0 | Pass | No whitespace errors. |
| Full `scripts/browser_smoke.mjs` | Chromium, disposable loopback data, fresh profile | 0 | Pass | Includes held `/api/tasks` hydration geometry at 1440×1000 and 390×844, both boot-asset failures, Home priority/fallback, responsive layouts, and accessibility workflows. |
| Lighthouse runs 1–3 | Chromium/Lighthouse simulated mobile, disposable loopback data | 0 each | 3 passed | Local JSON reports retained outside the repository. |

Lighthouse results:

| Run | Performance | Accessibility | Best Practices | SEO | FCP | LCP | CLS | TBT |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 90 | 100 | 100 | 100 | 1.768 s | 3.337 s | 0 | 149 ms |
| 2 | 92 | 100 | 100 | 100 | 0.937 s | 3.337 s | 0.00012 | 41 ms |
| 3 | 92 | 100 | 100 | 100 | 0.938 s | 3.338 s | 0.00012 | 30 ms |

Median Performance is 92 and median LCP is 3.337 s. CLS fell from 0.141 to at
most 0.00012 while all non-performance categories remained 100.

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | shared dirty worktree, sandbox | 1 | 1290 run: 1277 passed, 1 failed, 7 errors, 5 skipped | Seven loopback-bind tests were denied by the sandbox; `test_data_contract` saw the user's intentionally modified `data/projects.json`. No failure touched candidate files. |
| Same command | clean detached validation worktree with final candidate files, host loopback permission | 0 | 1290 run: 1286 passed, 4 skipped | Clean full repository gate; final rerun completed in 211.430 s after first-round review fixes. |

### Rendered or manual behavior

- Controlled Chromium hydration produced exactly zero shift in the focus list,
  scroll shell, and focus panel at both desktop and phone widths.
- The complete browser smoke passed current desktop/mobile layout, navigation,
  keyboard, accessibility, failure, and operational interaction checks.
- Three final Lighthouse audits reduced the prior attributed focus-list CLS to
  effectively zero without degrading the other quality categories.

## Adversarial review

### Round 1

- Correctness/safety reviewer: independently identified the phone filter-slot
  height mismatch and the pre-merge `Complete` status ambiguity. It also found
  a stale changelog sentence and an arithmetic error in the dirty-worktree
  test accounting.
- Compatibility/product reviewer: independently identified the same phone and
  roadmap issues. It separately noted that the controlled browser fixture
  exercises multiple rows but not explicit zero and one-row payloads.
- Reconciliation: the corroborated phone and roadmap findings were accepted as
  blocking and fixed. The changelog and accounting findings were validated by
  the peer reviewer and fixed. The zero/one-row observation was validated as a
  real but non-blocking evidence gap: the invariant is source-level fixed
  viewport geometry, the multi-row rendered path exercises the hydration
  boundary, and no data-dependent production geometry remains.
- Post-fix evidence: 58 focused tests, syntax and diff checks, complete desktop
  and phone Chromium smoke, three Lighthouse audits, and the 1,290-test clean
  suite all pass.

### Round 2

- Correctness/safety reviewer
  `01a026d9-4ef3-7f80-98d6-7778bfb25621` independently re-reviewed the entire
  post-fix candidate diff and evidence: no findings; publication-ready.
- Compatibility/product reviewer
  `01a026d9-5303-79c3-8fa7-e33d19719cf1` independently re-reviewed the entire
  post-fix candidate diff and evidence: no findings; publication-ready.
- Both reviewers explicitly accepted the documented zero/one-row fixture
  limitation as non-blocking and confirmed that the roadmap keeps staged
  feature-branch closure status non-canonical until merge.
- Remaining unresolved reviewer findings or dissent: none.

## Documentation updates

- Roadmap: 1C-D is complete; 2A is proposed; the exact repeated 100 target is a
  required replacement gate in 2A.
- Changelog: records the geometry fix, 1C-D closure, and gate resequencing.
- Architecture/operator docs: no contract change expected; the runtime and
  persistence boundary is unchanged. `DATA_LAYOUT.md` status now reflects the
  already-complete Task cleanup.
- Project/session notes: this review log.
- Documentation verification: architecture and readiness contract tests pass.

## Publication gate

- Proposed files: `CHANGELOG.md`, `DATA_LAYOUT.md`,
  `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`, `public/styles.css`,
  `scripts/browser_smoke.mjs`, `tests/test_agent_runtime_architecture.py`,
  `tests/test_home_operations_ui.py`, and this review log. All unrelated
  worktree changes are excluded.
- Branch and base: `codex/close-1c-d-performance-gate` → `main`.
- Commit message: `Close Pivot 1C-D and resequence Lighthouse gate`.
- PR title: `Close Pivot 1C-D and resequence Lighthouse gate`.
- PR summary: fix deterministic Home hydration CLS at desktop and phone widths;
  close 1C-D on explicit compatibility/performance budgets; retain exact
  repeated Lighthouse 100/100/100/100 as the Slice 2A replacement gate.
- Unresolved risks: local Lighthouse scores remain host-variable; no field or
  non-Chromium telemetry; explicit zero/one-row browser variants are not
  replayed. None blocks this CSS geometry and roadmap-only slice.
- User authorization and scope: implementation and exact publication packet
  authorized under the user's recorded standing approval exception.
- Primary slice commit: `72dce47`.
- Ready PR URL: https://github.com/hazeion/agent-os/pull/113 (filed through
  the GitHub connector).
- Hosted CI before outcome acceptance: required `Quality gates required`
  check passed on published head `5c20a39`; the broader optional matrix had 31
  passing and 18 pending checks.

## Outcome review

- Classification: Successful; canonical roadmap closure awaits merge.
- Acceptance criteria summary: AC-1 through AC-5 met.
- Potential bugs or untested paths: no field or non-Chromium telemetry; the
  controlled browser hydration fixture is multi-row rather than separate zero
  and one-row replays. The fixed-height CSS invariant covers those row counts.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: no data, API, runtime, or migration
  changes; revert the isolated commit if necessary.
- User decision: accepted the successful outcome and authorized PR #113 to
  merge on 2026-08-21.
- Next slice authorized: Yes. Slice 2A may begin after PR #113 merges and local
  `main` is synchronized.
