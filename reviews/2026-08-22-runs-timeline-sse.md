# Feature Slice Review: Run timeline SSE

Status: Complete in this branch

Slice: `2c-a-runs-timeline-sse`

Date: `2026-08-22`

## Slice contract

### Goal

Let a person open one current Run in the new Runs workspace and see its live,
safe normalized event timeline.

### In scope

- One fixed, authenticated loopback bridge capability for one validated Run's
  latest 100 safe normalized events, a cursor, and an explicit retention reset.
- One same-origin Node SSE route that validates a selected Run ID and
  `Last-Event-ID`, reconnects through bounded polling, emits a keepalive, and
  closes regularly so the browser reconnects.
- One selected Run timeline in the static-first Runs workspace, including
  loading, empty, unavailable, missing, retention-reset, and safe-error states.
- Safe event fields only: ID, Run ID, sequence, type, occurred-at timestamp,
  bounded summary, and bounded numeric metrics.

### Out of scope

- Run creation, stopping, approvals, retry, reconciliation, messages,
  attachments, event content, raw adapter payloads, details pages, controls,
  generic bridge forwarding, query-controlled limits, or multi-Run streams.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Python exposes only a fixed, bounded, existing-authority event projection. | Focused bridge and SQLite tests | Passed |
| AC-2 | Node offers one validated same-origin SSE stream with cursor reconnect, reset, and keepalive behavior. | Node contract tests | Passed |
| AC-3 | The Runs workspace opens one accessible, responsive selected timeline with safe event fields only. | Production browser smoke | Passed |
| AC-4 | Missing, unavailable, malformed, disconnected, and truncation states fail closed with clear feedback. | Negative-path tests and browser smoke | Passed |
| AC-5 | The compatibility UI remains unchanged and no control or private data route is added. | Regression/static checks | Passed |
| AC-6 | Six Lighthouse runs remain 100/100/100/100. | Lighthouse gate | Passed |

### Constraints and recovery

- Safety: existing private SQLite authority is read only; browser input cannot
  select a bridge path, bridge token, limit, or arbitrary cursor.
- Compatibility: Python compatibility UI and existing orchestration routes stay
  unchanged. Node remains the only browser-facing bridge caller.
- Rendered behavior: the page stays useful before enhancement; only one
  timeline stream is active; controls meet mobile target and overflow rules.
- Rollback: remove only the fixed event bridge, Node stream route, and Runs
  timeline enhancement. No mutation or migration occurs.
- Documentation targets: `ARCHITECTURE.md`, the implementation plan, and this
  log.
- Version-control strategy: focused branch from `main`, ready-for-review PR to
  `main`.

### Scope discussion and approval

- Recommendation and rationale: stream one selected Run before any controls.
  It validates the event contract and reconnect behavior without multiplying
  active connections or widening runtime authority.
- Alternatives considered: poll every card (simpler but noisy and not live);
  add controls now (larger mutation surface); use WebSocket (unnecessary for
  server-to-browser events).
- User decisions: the active goal grants standing approval for every remaining
  pivot slice, its test strategy, publication, merge, and continuation. This
  is an explicit exception to per-slice approval prompts.
- Approved at: standing authorization recorded before this slice began.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No fixed Run-event bridge exists. | Bridge projection, limit, malformed, missing-authority, and unchanged-file tests. | Exact safe Python boundary. | Does not prove browser rendering. |
| AC-2 | No Node SSE route exists. | Node stream framing, fixed bridge path, header cursor, reset, error, and cancellation tests. | Same-origin streaming contract. | Does not prove a long-lived production network. |
| AC-3 | Runs lists summaries only. | Production browser smoke for open, live event, close, keyboard, and phone layout. | Rendered selected-timeline workflow. | Uses deterministic local fixtures. |
| AC-4 | No timeline states exist. | Browser and Node malformed/unavailable/missing/reset tests. | Fail-closed status handling. | Upstream process crashes remain simulated. |
| AC-5 | Current route has no timeline capability. | Existing compatibility/static tests and source/diff review. | No legacy regression or widened route. | Manual code review supplements tests. |
| AC-6 | Gate currently covers the shell. | Six-run production Lighthouse gate. | Performance, accessibility, best practices, SEO. | Local deterministic gate, not field telemetry. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `rg` inspection of bridge, Node routes, and Runs workspace | macOS local checkout | Pass | Confirms 2B-C has no event bridge, Node SSE route, or timeline UI. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts this strategy.
- Accepted coverage gaps: no real remote runtime is required; deterministic
  local event fixtures exercise the public boundary.
- Approved at: standing authorization recorded before this slice began.

## Implementation record

### Changes

- Added the fixed `/bridge/v1/runs/<run-id>/events?after=<cursor>` read-only
  event capability. It reads existing SQLite authority only, returns at most
  100 normalized safe events, and signals replay gaps explicitly.
- Added the same-origin Node SSE route. It validates the Run ID and
  `Last-Event-ID`, polls the fixed bridge, emits an initial snapshot,
  incremental events, keepalives, reset events, and a bounded reconnect window.
- Added an on-demand selected timeline to the Runs workspace. It renders safe
  event summaries and metrics, closes the previous stream, and reports clear
  safe failure states.
- Added fixed bridge, Node stream, and production browser smoke coverage.

### Deviations and decisions

- The underlying repository retains up to 1,000 events. This public stream
  exposes only the newest 100; a larger gap becomes an explicit reset instead
  of silently skipping history.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_mentat_local_bridge -v` | macOS host | Exit 0 | 22 passed | Fixed route, strict projection, failures, and authority-reader checks. |
| `npm --prefix web run check` | macOS Node 24 | Exit 0 | 28 passed | Lint, types, bridge, SSE framing, bounded cursor, later reset, and encoded Run-ID tests. |
| `node web/scripts/run-next.mjs build --webpack && node web/scripts/prepare-standalone.mjs` | macOS Node 24 | Exit 0 | Build passed | Production build includes one dynamic SSE route and four static shell routes. |
| Production browser smoke | macOS Chromium, loopback preview | Exit 0 | Passed | Selected timeline, replacement, close/focus, phone layout, static-shell, and regression checks. |
| Six-run Lighthouse gate | macOS Chromium, loopback preview | Exit 0 | 6 passed | Three desktop and three mobile audits all scored 100/100/100/100 after the final review fixes. |
| `python3 -m unittest tests.test_mentat_web_preview tests.test_dashboard_behaviors tests.test_agent_run_events -v` | macOS host | Exit 0 | 39 passed | Node preview lifecycle, dashboard compatibility, and existing Run-event contracts. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS host | Exit 1 | 1 failure, 4 skipped | Pre-existing dirty `data/projects.json` contains two user projects beyond the fixture's single-project expectation. This slice does not touch that file; focused and clean-checkout CI will cover the slice. |

### Rendered or manual behavior

- Production Chromium smoke passed. It opens a single on-demand timeline with
  a maximum-length Run ID and normalized event fixture at phone width, confirms
  no horizontal overflow, replaces the selection without accumulating panels,
  closes the panel, restores focus to its opener, and checks no browser console
  or event errors.

## Adversarial review

### Round 1

Two independent read-only reviewers examined the implementation before its
final verification pass. They found three blocking defects and one test-coverage
gap:

- Native EventSource connection errors were being treated as terminal custom
  SSE errors, preventing the intended reconnect.
- A later retention reset omitted the required `reset: true` envelope field.
- Closing or replacing a selection left old timeline panels in the page.
- Tests did not cover bounded `Last-Event-ID` handling or the
  replace-and-close workflow.

All four findings were addressed. The client now distinguishes native errors
from custom server error messages, reset frames use the UI envelope, timeline
panels are removed on every close/replacement/error path with focus restoration,
and the Node/browser coverage covers cursor validation, later reset, replacement,
and close.

### Final re-review

Two independent reviewers rechecked the fixes. One found a valid Run ID with a
colon was encoded by Node but not decoded by the bridge. The bridge now decodes
exactly one path segment before applying the existing strict Run-ID validation,
and Python plus Node tests cover that supported ID. A final coverage observation
requested explicit rejected cases for encoded separators, double encoding,
encoded traversal, and extra segments; those cases now assert the fixed 404
response. The reviewers found no remaining blocking or major defect.

## Documentation updates

- Roadmap: marks 2C-A complete in this branch and records its exact boundary.
- Architecture/operator docs: records the event allowlist, one-stream limit,
  cursor reconnect, reset, and redactions.
- Documentation verification: pending final diff check.

## Publication gate

- Ready for commit and pull-request publication under the recorded standing
  authorization. The final branch verification passed, including the six-run
  Lighthouse gate.

## Outcome review

- Classification: Accepted for publication under standing authorization.
- User decision: standing authorization records continuation after a successful
  published slice.
- Next slice authorized: Yes, by standing authorization.
