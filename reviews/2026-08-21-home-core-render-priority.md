# Feature Slice Review: Home Core Render Priority

Status: Published for review
Slice: `home-core-render-priority` (Pivot 1C-D performance closure)
Date: 2026-08-21
Review log: `reviews/2026-08-21-home-core-render-priority.md`

## Slice contract

### Goal

Render Mentat Home's task focus, project context, and core status as soon as
their local data is available, without waiting for slow Hermes sessions,
Console, agent, or cron requests. Populate those operational panels safely
after the core Home render.

### In scope

- Split the `today` refresh flow into a Home-critical request/render phase and
  independent deferred operational updates.
- Preserve existing API response shapes, 30-second refresh behavior, Hermes
  capability boundaries, task authority, navigation, and Home controls.
- Keep the existing stable Home panel geometry while deferred panels load.
- Add focused regression and rendered-browser evidence that delayed deferred
  requests do not block the Home-critical render.
- Re-run clean mobile Lighthouse diagnostics using a documented, repeatable
  configuration and record the result.

### Out of scope

- SQLite migration of remaining project-owned JSON documents.
- CSS/JavaScript file splitting, a build pipeline, minification, or a frontend
  framework migration.
- Changes to Hermes operations, backend data models, task/run authority, or
  visual redesign.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | On Home, task focus and core project context render before deliberately delayed Hermes Console, sessions, agents, or cron requests settle. | Focused browser regression with controlled delayed responses. | Pass |
| AC-2 | Deferred Home panels render their current data or bounded existing error/empty states once their requests settle, without a second full refresh. | Focused browser regression and existing browser smoke. | Pass |
| AC-3 | Refresh coalescing, navigation, Console behavior, task controls, and accessibility semantics remain compatible. | Existing focused UI/Console suites and browser smoke. | Pass |
| AC-4 | Clean, documented mobile Lighthouse runs show improved Home LCP/performance against the pre-change diagnostic; the 1C-D 100 gate remains explicit and is not claimed without repeatable evidence. | Repeated Lighthouse reports with the same local setup. | Pass for this slice; 1C-D mobile-100 gate remains open |

### Constraints and recovery

- Safety: do not change API authority or Hermes mutation/control behavior; retain
  the existing local-only boundary.
- Compatibility: do not change browser-visible API shapes or make a deferred
  request failure block core Home data.
- Rendered behavior: preserve Home loading states, stable panel geometry,
  keyboard access, and eventually populated operational panels.
- Rollback or recovery: revert the isolated branch commit; no data migration or
  persistent-format change is involved.
- Documentation targets: this review log, `CHANGELOG.md`, and architecture
  guidance only if the client readiness/refresh contract becomes operator-relevant.
- Version-control strategy: `codex/home-core-render-priority` from current
  `origin/main`; preserve `data/projects.json`, `data/tasks.json`, and all
  unrelated untracked operator artifacts.

### Scope discussion and approval

- Recommendation and rationale: the current `Promise.all` waits for every
  Home request before rendering the task focus, so slow remote Hermes requests
  delay LCP despite the data required for Home already being available. Splitting
  this orchestration is the smallest high-confidence performance improvement.
- Alternatives considered: start a CSS/JS module split now (broader and riskier);
  migrate remaining JSON to SQLite (does not address the measured browser
  bottleneck); accept the current Lighthouse variability (does not close the
  existing quality gate).
- User decisions: user requested implementation after the Lighthouse and source
  diagnosis, then approved this slice contract on 2026-08-21.
- Approved at: 2026-08-21, user message `approve`.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | `refresh()` waits for one aggregate `Promise.all` before any Home rendering. | A browser-level startup test delays selected Hermes endpoints while asserting task focus/core content renders first. | The visible Home core is no longer gated by slow remote endpoints. | Requires controlled browser interception rather than an actual slow Hermes instance. |
| AC-2 | Deferred panel updates occur only in the current aggregate render pass. | Browser test releases delayed responses and asserts Home Console/live-agent/cron panels update without another `refresh()` call. | Deferred data is eventually applied independently. | Does not emulate every Hermes payload variant. |
| AC-3 | Refresh ordering affects a large existing static UI and Console surface. | Focused UI/Console tests, `node --check`, and existing multi-view browser smoke. | Existing operations remain available after split rendering. | Browser smoke is Chromium-only. |
| AC-4 | Earlier mobile scores varied from 94–97 on the shared host; a fresh diagnostic exposed a 3.8s LCP when remote panels were slow. | At least three clean-profile mobile audits with fixed Lighthouse/Chromium flags; record all scores and median LCP. | Measures the change under one documented configuration and avoids a single-run claim. | Host contention can still vary results; this does not substitute for hosted CI. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Source and request-flow inspection | current `main`, macOS | Gap confirmed | `public/app.js` starts Home requests at lines 6381–6418 and waits for all of them at line 6426 before rendering focus at lines 6438–6454. |
| Fresh local Lighthouse diagnostic | macOS, Chromium/Lighthouse local default mobile setup, disposable data root | Performance 76 / Accessibility 100 / Best Practices 100 / SEO 100 | FCP 0.9s, LCP 3.8s, CLS .141, TBT 310ms; configuration differs from prior acceptance runs and is diagnostic only. |
| Browser/server timing inspection | disposable loopback server | Gap confirmed | Task/calendar requests settled before slower Console, sessions, agents, and cron requests; aggregate client rendering waited for the slow group. |

### Test discussion and approval

- User questions and decisions: user approved the proposed test strategy on
  2026-08-21, then requested that this approval—and any normally required later
  approval for this slice—be assumed.
- Accepted coverage gaps: controlled delayed browser responses stand in for an
  actual slow Hermes runtime; repeated local Lighthouse runs remain host-variable.
- Approved at: 2026-08-21, user message `assume my approval and any future
  approvals needed assume my approval on those too`.
- Process exception: at the user's explicit direction, the normal separate
  approval prompts for staging, committing, pushing, opening a ready PR, and
  outcome acceptance are pre-authorized for this slice. The publication packet,
  exact changed-file list, reviews, test evidence, and any unresolved risk will
  still be recorded and reported before those actions occur.

## Implementation record

### Changes

- Added a Home-critical render phase for `tasks`, `projects`, and `health`.
  Each core request now settles independently, so one unavailable core source
  cannot prevent the remaining Home-critical content from rendering.
- Converted deferred Home requests into independent render/error paths.
  A slow or failed Console, session, agent, calendar, cron, overview, or
  context-pack request no longer blocks a successful sibling panel or the
  eventual bootstrap state.
- Changed navigation refresh coalescing so a view change during the initial
  deferred window always schedules a follow-up refresh for the selected view.
- Kept `/api/overview` out of that phase after measurement showed its Hermes
  work could still delay the greeting; it now updates independently with the
  existing full response.
- Added `window.__MENTAT_HOME_CORE_READY__` and a `mentat-home-core-rendered`
  User Timing mark as browser-test diagnostics; both are reset on a full page
  load and do not alter authority or API behavior.
- Extended the browser smoke CDP client with scoped event handlers and added a
  regression that pauses all eight deferred Home endpoints (including
  overview), proves the focus/project core renders first, releases Console
  independently, rejects Context Packs, navigates to Agents mid-flight, and
  proves recovery without a stuck bootstrap.
- Corrected an existing browser-smoke selector to match the implemented
  `.managed-agent-row` markup.

### Deviations and decisions

- The first implementation included `/api/overview` in the core group. Three
  measurements showed it remained a slow Hermes-dependent request and held LCP
  near 3.7 seconds, so it was removed from the core group within the approved
  boundary. The corrected three-run median is 85 performance, versus 76 in the
  pre-change diagnostic under the same local setup.
- The slice does not meet the broader 1C-D repeatable mobile-100 gate; the
  remaining evidence still identifies unused CSS/JavaScript and layout work as
  the next boundary rather than remote data latency.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `node --check public/app.js` and `node --check scripts/browser_smoke.mjs` | macOS | Pass | n/a | Syntax checks passed. |
| `python3 -m unittest tests.test_task_delegation_ui tests.test_frontend_workflow_feedback tests.test_home_operations_ui tests.test_visual_contract -q` | macOS | Pass | 62 passed | Covers source contract, existing Home behavior, and visual contract. |
| `scripts/browser_smoke.mjs` against fresh disposable local data | Chromium headless, macOS | Pass | all listed checks passed | Paused 8 deferred endpoints; focus/project context rendered with core marker true while full bootstrap was false; Console rendered independently; Context Packs failed deliberately; an in-flight Agents navigation recovered; a separately rejected `/api/tasks` showed bounded empty focus with live project context; then all ordinary checks passed after clean reloads. |
| Three clean local Lighthouse mobile diagnostics | Chromium/Lighthouse, disposable local data | Pass with documented limitation | performance 85 / 85 / 85; median 85 | FCP about 0.927s, LCP about 3.477s, CLS .141, TBT 42–58ms. Accessibility, Best Practices, and SEO were 100. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | host checkout with operator data | Expected unrelated failure | 1,289 passed, 1 failed, 4 skipped | `test_data_contract` reads the user-edited `data/projects.json`; no candidate file touches it. |
| `python3 -m unittest discover -s tests -q` | host, disposable clean worktree plus only the candidate source/test patch | Pass | 1,290 passed, 4 skipped | Confirms the slice independently of the user’s local fixture edits. |

### Rendered or manual behavior

- The isolated browser smoke retained desktop/mobile Home layouts, six-view
  navigation, Console controls, task behavior, accessibility checks, and the
  new delayed-endpoint contract.
- The temporary Lighthouse reports are diagnostic evidence only and are not
  committed; the remaining mobile-100 quality gate is explicitly unresolved.

## Adversarial review

### Round 1 — blockers found and corrected

- Reviewer A found aggregate deferred rendering still made one slow or failed
  response block successful sibling panels, and noted that a Home-to-Agents
  navigation during the first refresh could be skipped. The finding was
  blocking and in scope. Corrected by independent deferred settlement/error
  handling and unconditional view-change refresh coalescing.
- Reviewer B independently found the same deferred aggregate issue and also
  found that a failed core health response could hide otherwise available tasks
  and projects. The finding was blocking and in scope. Corrected by independent
  core settlement with a bounded health error render.
- Both reviewers noted the previous browser test covered only a successful,
  aggregate release. Corrected by the eight-request, independent-release,
  deliberate-failure, mid-navigation browser regression above.
- Both reviewers also correctly noted that the documented 85/86/85 Lighthouse
  result does not close the broader 1C-D mobile-100 gate. This is explicitly
  out of scope for this narrow slice and remains open.

### Round 2 — blockers found and corrected

- Both reviewers found unbounded initial loading states for a subset of failed
  requests. Corrected by explicit bounded fallbacks for all visible core and
  deferred request keys, including tasks, projects, activity, sessions, Agent
  Console, calendar, crons, profiles, notes, and settings panels.
- The browser regression now verifies both the Context Packs error state and a
  failed Home task request with successful project context.

### Round 3 — final disposition

- Reviewer A found one stale-cache edge for the combined Agents/session pulse:
  a failed current response could be combined with cached data from a prior
  refresh. Corrected by clearing the corresponding cached payload in each
  failure path; focused and rendered-browser checks passed afterward. Reviewer
  A confirmed the micro-fix with no further findings.
- Reviewer B found no functional or browser blockers after the Round 2 fixes;
  its only blocker was this review-log finalization, now resolved.
- Broader mobile-100 closure remains out of scope and open for Pivot 1C-D.

## Documentation updates

- Added a concise user-facing change note to `CHANGELOG.md`.

## Publication gate

- Proposed files: `CHANGELOG.md`, `public/app.js`, `public/core.js`,
  `public/index.html`, `scripts/browser_smoke.mjs`,
  `tests/test_frontend_workflow_feedback.py`,
  `tests/test_task_delegation_ui.py`, and this review log. Explicitly exclude
  existing local data and unrelated untracked artifacts.
- Branch and base: `codex/home-core-render-priority` → `main`.
- Commit message: `Prioritize Home core rendering`.
- PR title: `Prioritize Home core rendering`.
- Commit: published on `codex/home-core-render-priority` (the branch may be
  amended for verified CI corrections before merge).
- Ready PR: https://github.com/hazeion/agent-os/pull/111
- User authorization and scope: user explicitly pre-authorized implementation,
  verification, commit, push, ready PR creation, and outcome acceptance for
  this slice on 2026-08-21. Publication remains contingent on successful final
  review and the recorded file boundary.

## Outcome review

- Classification: successful for the approved Home render-priority slice.
- Delivered: Home-critical content renders before deferred Hermes work;
  individual deferred/core failures become bounded UI states; navigation during
  the first refresh coalesces correctly; tests cover delayed, failed, and
  mid-flight navigation paths.
- Evidence: 62 focused tests passed; final Chromium browser smoke passed all
  checks; repeatable mobile Lighthouse is 85/100 performance and 100/100/100
  for Accessibility, Best Practices, and SEO.
- Deferred work: CSS/JavaScript splitting and additional render/layout work are
  still required for the broader repeated 100-performance target. Pivot 1C-D
  remains open; this slice does not claim its closure.
