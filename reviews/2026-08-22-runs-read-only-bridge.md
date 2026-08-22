# Feature Slice Review: Read-only Runs bridge

Status: Complete

Slice: `2b-c-runs-read-only-bridge`

Date: `2026-08-22`

## Slice contract

### Goal

Show current canonical Run summaries in the new `/runs` workspace without
exposing runtime references, event content, or a general Python proxy.

### In scope

- One fixed authenticated loopback Python capability for at most 50 current
  Run summaries from the canonical Run repository.
- One fixed same-origin Node `GET /api/runs` route with bounded strict
  validation.
- A static-first `/runs` list with loading, empty, unavailable, unsupported,
  safe-error states, and manual refresh.
- Safe fields: ID, source, Task ID, Agent ID, runtime type, status, dispatch
  state, partial flag, timeline-truncated flag, and lifecycle timestamps.

### Out of scope

- Run creation, stopping, approval, retry, reconciliation, messages, or any
  other control.
- Event timelines, event summaries or metrics, cursor/pagination controls,
  details pages, attachments, task snapshots, runtime configuration IDs,
  runtime references, binding digests, revisions, sequence counters, and raw
  adapter data.
- Generic bridge forwarding and changes to the Python compatibility UI.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Python exposes one fixed, read-only Run-list capability backed by canonical SQLite authority. | Focused bridge tests | Passed |
| AC-2 | Node calls one fixed path, bounds and validates the response, and excludes private Run fields. | TypeScript contract tests | Passed |
| AC-3 | `/runs` renders only the safe summary projection with no event or runtime-reference content. | Browser smoke and DOM checks | Passed |
| AC-4 | Loading, empty, unavailable, unsupported, and error states are explicit; refresh has no parameters. | Browser/DOM tests | Passed |
| AC-5 | Compatibility UI remains unchanged and the production route stays script-light. | Regression/static checks | Passed |
| AC-6 | Six Lighthouse runs stay 100/100/100/100. | Lighthouse gate | Passed |

### Constraints and recovery

- Python and the canonical Run SQLite authority remain authoritative. The
  bridge reads the existing authority only and never starts or migrates it.
- Browser input cannot choose a bridge path, header, limit, cursor, or token.
- The route remains prerendered with a stable placeholder and no React
  hydration runtime. It fetches only after first paint.
- No mutation or migration occurs. Revert removes only this fixed capability,
  Node route, and static enhancement.
- Documentation targets: `ARCHITECTURE.md`, the implementation plan, and this
  review log.
- Version-control strategy: `feature/2b-c-runs-read-only` -> `main`, normal
  ready-for-review PR.

### Scope and test approval

- Recommendation: prove the existing normalized Run authority with the small
  read-only list before adding event streaming or controls.
- Alternative: expose the existing cursor-based orchestration API. Rejected
  because browser-selected cursors and a broad run projection are unnecessary
  for this first vertical slice.
- Test strategy: Python fixed-path/projection/failure tests; Node
  fixed-path/private/oversized payload tests; production browser state and
  projection checks; static checks; web and focused Python suites; production
  browser smoke; six-run Lighthouse gate; two independent reviews.
- User decision: standing pivot authorization approves this contract, test
  strategy, publication, merge, and continuation. This is an explicit
  exception to the skill's per-slice approval prompts.

## Implementation record

- Added the fixed `/bridge/v1/runs` capability, bounded to 50 canonical Run
  summaries. It reconstructs the allowlisted public projection and never
  forwards runtime references, revisions, event data, or raw adapter output.
- Added `GET /api/runs` and a strict Node validation boundary. The browser
  can request no bridge path, limit, cursor, header, or token.
- Replaced the Runs foundation message with a static-first list, clear state
  messages, manual refresh, readable statuses, and responsive cards.
- Added an existing-only SQLite reader for this bridge. It refuses absent or
  unsafe authority, uses immutable mode when no sidecars exist, and uses a
  bounded, verified temporary snapshot when the live WAL/SHM pair exists.
  It never migrates or changes the source database, WAL, or SHM files.
- Added Slice 4A to the roadmap: Vercel is an optional, capability-scoped
  infrastructure target after the runtime and data model stabilize through
  Slice 3C.

## Verification

- `python3 -m unittest tests.test_mentat_local_bridge tests.test_dashboard_behaviors tests.test_agent_run_events -v` — passed (51 tests).
- `npm --prefix web run check` — passed (21 tests).
- `node web/scripts/run-next.mjs build --webpack && node web/scripts/prepare-standalone.mjs` — passed.
- Production browser smoke — passed, including Runs loading/empty/refresh,
  safe error states, malformed payloads, rejected fetches, phone layout, and
  a maximum-length Run ID.
- Six-run Lighthouse gate — passed at 100/100/100/100 for all three desktop
  and all three mobile runs.
- Focused read-only authority tests prove missing authority creates no
  database, active-WAL reads leave database/WAL/SHM bytes unchanged, and
  oversized snapshots fail closed.

## Adversarial review

- Reviewer A: found and verified fixes for strict browser schemas/timestamps,
  authority initialization, SQLite sidecar writes, active-WAL snapshot
  integrity, and bounded snapshot memory. Final re-review: no findings.
- Reviewer B: found and verified fixes for live-region scope, readable Run
  statuses, mobile/max-ID coverage, malformed payloads, and rejected fetches.
  Final re-review: no findings.

## Documentation and publication

- Updated `ARCHITECTURE.md`, `MENTAT_MULTI_AGENT_PIVOT.md`, and
  `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`.
- Published in PR #118 under the user's standing authorization.

## Outcome review

- Merged to `main` in commit `9f88f056d88ab2c85429100d6e685afa7968018b`
  after CI, quality gates, and native artifact smoke all passed.
