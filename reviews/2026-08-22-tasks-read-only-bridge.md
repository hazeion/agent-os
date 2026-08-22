# Feature Slice Review: Read-only Tasks bridge

Status: Successful

Slice: `2b-b-tasks-read-only-bridge`

Date: `2026-08-22`

Review log: `reviews/2026-08-22-tasks-read-only-bridge.md`

## Slice contract

### Goal

Show the current canonical SQLite Task list in the new `/tasks` workspace
without exposing task descriptions, notes, delegation details, or a general
Python proxy.

### In scope

- One fixed authenticated loopback Python capability for a read-only Task-list
  projection.
- One fixed same-origin Node `GET /api/tasks` route with bounded strict
  validation.
- A static-first `/tasks` list with loading, empty, unavailable, unsupported,
  and safe-error states plus manual refresh.
- The safe Task fields: ID, title, project, status, priority, due date, tags,
  attention flag, review-required flag, and last-updated timestamp.

### Out of scope

- Creating, editing, deleting, reordering, completing, delegating, or running
  Tasks.
- Descriptions, notes, attachments, calendar links, dependencies, subtasks,
  recurrence, private artifacts, or raw delegation fields.
- Agent/provider controls, generic bridge forwarding, and changes to the
  Python compatibility UI.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Python exposes only one fixed authenticated loopback Task-list capability backed by the SQLite Task authority. | Focused bridge tests | Pass |
| AC-2 | Node calls one fixed path, bounds and strictly validates the response, and exposes no bridge authority or excluded Task fields. | TypeScript contract tests | Pass |
| AC-3 | `/tasks` shows the safe current Task projection and nothing from the excluded fields. | Browser smoke and DOM checks | Pass |
| AC-4 | The route gives honest loading, empty, unavailable, unsupported, and error feedback; refresh is fixed-route only. | Browser/DOM tests | Pass |
| AC-5 | The Python compatibility UI stays unchanged and the production route stays script-light. | Regression/static checks | Pass |
| AC-6 | The six-run Lighthouse gate stays 100/100/100/100. | Lighthouse gate | Pass |

### Constraints and recovery

- Python and `mentat.sqlite3` remain authoritative. The bridge reads only the
  existing canonical Task snapshot and never consults `tasks.json`.
- Browser input cannot choose a bridge target, path, token, or headers.
- The route remains prerendered with a stable placeholder and no React
  hydration runtime. It fetches only after first paint.
- No migration or mutation occurs. Revert removes only this fixed capability,
  Node route, and static enhancement.
- Documentation targets: `ARCHITECTURE.md`, the implementation plan, and this
  review log.
- Version-control strategy: `feature/2b-b-tasks-read-only` -> `main`, normal
  ready-for-review PR.

### Scope and test approval

- Recommendation: deliver the first read-only Task vertical slice before Task
  controls. It proves the SQLite authority through the Node boundary without
  prematurely recreating the legacy planner.
- Alternative: expose the existing broad `/api/tasks` payload. Rejected because
  it would carry descriptions, delegation, attachments, and planning details
  beyond the first workspace need.
- Test strategy: Python fixed-path/projection/failure tests; Node fixed-path,
  malformed/private/oversized payload tests; production browser state and
  projection checks; existing static route checks; the full web check, focused
  Python suite, browser smoke, and six-run Lighthouse gate.
- User decision: standing pivot authorization approves this contract, test
  strategy, publication, merge, and continuation. This is an explicit
  exception to the skill's per-slice approval prompts.

## Implementation record

### Changes

- Added fixed private `GET /bridge/v1/tasks` and same-origin `GET /api/tasks`
  capabilities. Python reads canonical SQLite Tasks only and both boundaries
  reject malformed or excluded fields.
- Replaced the static Tasks placeholder with a script-light current Task list,
  fixed refresh, and loading/empty/unavailable/unsupported/error states.
- Added Task bridge, shell contract, and production browser-smoke coverage.

### Deviations and decisions

- The first Lighthouse run had one desktop browser-process timeout. A complete
  fresh-browser retry passed all six audits at 100 in every category.
- The production smoke check initially raced the post-load shell runtime in its
  compact-keyboard assertion. The check now waits for an explicit runtime-ready
  marker before exercising that behavior.
- The strengthened smoke check also found that a focused compact navigation
  link lost its tooltip when the sidebar scrolled it into view. The runtime now
  repositions that focused tooltip after sidebar scrolling.
- CI found that a clean preview had no prepared Task authority. The bridge
  remains read-only; CI now prepares its isolated data root through the normal
  Python server lifecycle before starting the bridge. A bounded foreground
  process receives `SIGINT`, releases its lifecycle reservation cleanly, and
  proves the authority database exists before the bridge starts; a short
  forced-stop window prevents a hung cleanup from consuming the job timeout.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `npm --prefix web run check` | macOS source checkout | 0 | 19 pass | Lint, typecheck, and Node contracts. |
| `python3 -m unittest tests.test_mentat_local_bridge tests.test_node_runtime_foundation tests.test_ci_quality_gate -v` | macOS host checkout | 0 | 25 pass | Fixed Task bridge, read-only authority guard, and safe CI preview lifecycle. |
| Webpack production build | macOS source checkout | 0 | Pass | Static `/tasks` and dynamic `/api/tasks` emitted. |
| Production browser smoke | `127.0.0.1:8890` | 0 | Pass | Real Task list, refresh, responsive layout, and three failure states. |
| Six-run Lighthouse gate | `127.0.0.1:8890` | 0 | 6/6 pass | All desktop/mobile categories 100; desktop LCP 215–236ms and mobile LCP 1.038–1.041s. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | Dirty macOS source checkout | 1 | 1 unrelated failure, 4 skipped | 1,309 tests ran. Existing data fixture expects only Mentat but user data has two additional projects. |

### Rendered behavior

- The production Tasks route remains prerendered with only the two shared
  scripts, then shows the current SQLite projection after first paint.
- Browser smoke verified loading, refresh, ready/empty behavior, unsupported,
  unavailable, and error states without console errors or horizontal overflow.

## Adversarial review

### Review packets

- Reviewers received the full fixed-bridge, Node-route, Tasks UI, tests,
  smoke coverage, documentation, and final compact-navigation correction.
- Both reviews were read-only and independent. The final pass followed the
  corrupt-store regression assertion and compact-navigation correction.
- The clean-checkout CI correction received a separate two-reviewer pass. Both
  reviewers accepted the final foreground bounded-bootstrap design.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | Medium | Yes | Canonical Task IDs accepted by SQLite were narrower in the bridge projection. | Yes | Align the bridge regex with Task authority. |
| A-2 | Medium | Yes | A corrupt Task store was presented as unsupported. | Yes | Return fixed internal-error state. |
| A-3 | Low | No | UI omitted safe Task fields from the approved projection. | Yes | Render them without adding private fields. |
| A-4 | Low | No | Plan and review record needed the completed Task route. | Yes | Update both before publication. |
| A-5 | Low | No | Review record showed 11 focused Python tests after a twelfth was added. | Yes | Correct the evidence count. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | Medium | Yes | The Node route did not map a fixed legacy bridge 404 to unsupported. | Yes | Map only that exact response. |
| B-2 | Medium | Yes | Response-size validation read the body without enforcing the limit while streaming. | Yes | Bound the stream itself. |
| B-3 | Medium | Yes | Corrupt Task authority mapping needed fixed error state. | Yes | Match the Python correction. |
| B-4 | Low | No | Long safe Task values could overflow cards. | Yes | Add safe wrapping. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Bridge ID regex was narrower than canonical Task IDs. | A unique | Accepted; final pass clean. | Focused bridge test accepts canonical-wide IDs. | Aligned projection validation with Task authority. |
| Corrupt authority classified as unsupported. | A/B corroborated | Accepted; final pass clean. | Focused bridge test maps corruption to 500/error. | Reserved unsupported for schema compatibility only. |
| Node bridge response boundaries were incomplete. | B unique | Accepted; final pass clean. | Node contracts cover exact legacy 404 and oversized streamed body. | Added exact 404 mapping and bounded stream reader. |
| Safe UI details and long values needed treatment. | A/B unique | Accepted; final pass clean. | Production smoke passed without overflow. | Rendered all approved safe fields and added wrapping. |
| Compact keyboard tooltip hid while sidebar scrolled. | Browser-smoke finding | Both final reviewers found no regression. | Full production smoke confirms Runs tooltip stays visible. | Reposition focused tooltip on sidebar scroll; wait for runtime-ready before the check. |
| Clean CI preview had no Task authority. | CI failure | Accepted after two reviews. | Manual isolated lifecycle check and workflow contracts pass. | Bootstrap a temporary data root through the normal Python server before preview. |
| Bridge bootstrap attempted authority mutation. | A/B corroborated | Accepted; final pass clean. | Bridge test proves the Task projection never invokes authority setup. | Removed the unsafe bridge startup call; kept the bridge read-only. |
| Background bootstrap shutdown could hang or skip cleanup. | A/B unique | Accepted; final pass clean. | Workflow contracts cover bounded foreground bootstrap. | Use foreground `timeout` with `SIGINT` and a short forced-stop fallback. |

## Documentation and publication

- Updated `ARCHITECTURE.md` with the fixed canonical Task projection and its
  redaction boundary.
- Updated the implementation plan to mark Slice 2B-B complete and record its
  explicit scope.
- Updated the required Node quality gate to prepare its isolated Task authority
  through the normal Python lifecycle before browser and Lighthouse checks.
- Publication scope excludes user-modified `data/projects.json` and
  `data/tasks.json`, plus unrelated untracked local files.

## Outcome review

The route provides the intended read-only SQLite Task vertical without changing
the Python compatibility UI or creating a second Task authority. It is ready
for normal PR publication and merge under the standing pivot authorization.
