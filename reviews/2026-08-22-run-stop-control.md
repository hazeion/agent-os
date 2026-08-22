# Feature Slice Review: Run stop control

Status: In progress

Slice: `2c-b-run-stop-control`

Date: `2026-08-22`

## Slice contract

### Goal

Let a person stop one active, task-bound Hermes Run from the new Runs workspace
only after reviewing an exact, state-bound confirmation.

### In scope

- One fixed authenticated loopback bridge preview and confirmation action for
  stopping one validated Mentat Run.
- Runtime-neutral capability, binding, active-state, confirmation, locking,
  and post-action read-back checks before the existing Hermes stop operation.
- Two fixed same-origin Node mutation routes and an accessible selected-Run
  Stop flow with clear unavailable, stale, and partial-failure feedback.

### Out of scope

- Run creation, retry, resubmission, arbitrary commands, direct Hermes access,
  browser-selected runtime references, messages/steering, approval responses,
  attachments, raw events, and any control for an unsupported runtime.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The bridge exposes only exact preview and confirmed-stop operations for one valid Run. | Bridge contract tests | Pass |
| AC-2 | A stop is capability- and binding-checked, state-bound, serialized, and read back; stale or unsupported requests fail closed. | Python action tests | Pass |
| AC-3 | Node accepts only exact same-origin requests and returns bounded safe action payloads. | Node route/bridge tests | Pass |
| AC-4 | The Runs page gives one accessible preview-confirm-stop flow and clear safe failures. | Production browser smoke | Pass |
| AC-5 | Existing compatibility Console controls and read-only Run/timeline behavior stay unchanged. | Regression tests and diff review | Pass with one unrelated fixture failure |
| AC-6 | Six Lighthouse runs remain 100/100/100/100. | Lighthouse gate | Pass |

### Constraints and recovery

- Safety: Python remains authoritative. The browser cannot choose a bridge
  target, runtime reference, action, or confirmation state. Stop is available
  only when the selected runtime currently advertises it for the exact,
  task-bound Run.
- Compatibility: the existing Python Console stop route remains unchanged; the
  new path uses the runtime-neutral adapter and fixed bridge only.
- Rendered behavior: Stop first opens a review panel. Confirming it is the
  only mutation; stale, unsupported, unavailable, and partial states stay
  visible and do not claim success.
- Rollback: remove the fixed preview/confirmation routes and the selected-Run
  control. It adds no schema migration or Hermes core-file write.
- Documentation targets: `ARCHITECTURE.md`, implementation plan, review log.
- Version-control strategy: branch from `main`, ready PR to `main`.

### Scope discussion and approval

- Recommendation and rationale: stop is the smallest safe mutation after the
  read-only timeline. It uses an existing fixed Hermes operation while proving
  the new Node-to-Python action boundary.
- Alternatives considered: add messages now (requires a separate text and
  steering contract); add approvals now (requires a separate request-response
  schema); add a generic action endpoint (unsafe).
- User decisions: the active pivot goal grants standing approval for all
  remaining slice scope, test strategy, publication, merge, and continuation.
  This is an explicit exception to the normal per-slice approval and outcome
  pause requirements in the reviewed-slice workflow.
- Approved at: standing authorization recorded before this slice began.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The bridge is read-only. | Exact method/path/body, encoded-ID, and malformed-route tests. | No generic bridge mutation. | Does not invoke Hermes. |
| AC-2 | No canonical stop mutation exists. | Fake runtime tests for capability, binding/state changes, duplicate action, read-back, and fixed failures. | Safe adapter action sequencing. | Hermes transport remains mocked. |
| AC-3 | Node has no mutation route. | Node request-boundary and response allowlist tests. | Browser cannot widen the server-side action. | Does not render UI. |
| AC-4 | Runs has timeline only. | Production Chromium smoke for preview, cancel, confirm, stale/error, keyboard, and phone layout. | Real selected-Run interaction. | Uses deterministic local fixtures. |
| AC-5 | New mutation can regress existing routes. | Existing Python/Node regression suites and full suite. | Compatibility surface remains stable. | Legacy external Hermes behavior is mocked. |
| AC-6 | Gate covers the current shell. | Six-run production Lighthouse gate. | All category scores remain perfect. | Local deterministic evidence only. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Current Runs bridge and Node route inspection | macOS local checkout | Pass | No stop preview, confirmed-stop route, or rendered Stop control exists. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts this strategy.
- Accepted coverage gaps: no real remote Hermes stop is required; the existing
  fixed adapter path is exercised with deterministic test doubles.
- Approved at: standing authorization recorded before this slice began.

## Implementation record

### Changes

- Added a fixed bridge preview and confirmed Stop action for one Run.
- Added state-bound confirmation, current runtime capability and binding checks,
  serialized execution, and durable post-action read-back.
- Added same-origin Node routes and an on-demand review-confirm Stop panel in
  the Runs workspace.

### Deviations and decisions

- Slice 2C-B begins with stop only. Text steering and approval responses remain
  separate follow-up mutation contracts rather than being widened into this
  first action boundary.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_run_stop_control tests.test_mentat_local_bridge tests.test_agent_runtime -q` | macOS host | Exit 0 | 42 passed | Fixed bridge action, confirmation race, capability, exact runtime identity, durable read-back, active waiting-state, and route checks. |
| `npm --prefix web run check` | macOS Node 24 | Exit 0 | 32 passed | Lint, types, fixed Stop bridge requests, and bounded preview/confirmation body checks. |
| `node web/scripts/run-next.mjs build --webpack && node web/scripts/prepare-standalone.mjs` | macOS Node 24 | Exit 0 | Build passed | Production build includes the two fixed Stop routes. |
| Production browser smoke | macOS Chromium, bridge-backed loopback preview | Exit 0 | Passed | Preview, stale-confirmation recovery, refreshed preview, confirmation, Run refresh, mobile layout, and existing shell flows. |
| Six-run Lighthouse gate | macOS Chromium, bridge-backed loopback preview | Exit 0 | 6 passed | Three desktop and three mobile audits scored 100/100/100/100. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS host | Exit 1 | 1 failed, 4 skipped, 1,327 passed | Repeated after the final fix. The only failure is pre-existing user fixture data in `data/projects.json`: `test_only_mentat_project_remains_active_for_v1` expects exactly `Mentat`, while the user’s uncommitted fixture adds two projects. This slice neither reads nor changes that file. |

### Rendered or manual behavior

- Production Chromium smoke passed on a loopback Node preview: it opened the
  selected Run timeline, opened and confirmed Stop, refreshed the Run list,
  preserved the existing shell flows, and checked the narrow layout.

## Adversarial review

### Round 1

- Reviewer A (correctness and safety) found two blocking issues: the Hermes
  adapter bound only Agent and Task rather than the exact Run, and a changed
  revision alone was insufficient durable Stop evidence.
- Reviewer B (compatibility and product) found a blocking state-change race
  after preview validation, plus two in-scope hardening/usability issues: a
  stale Confirm button could retry the same token, and the preview route did
  not validate its public request body.
- Both reviewers independently maintained the peer findings. All findings fit
  the contract and were accepted.

### Fixes and re-verification

- The Hermes adapter now checks the supplied runtime reference and returned
  Mentat Run ID against private context. Stop rechecks the confirmation against
  the final locked Run snapshot and requires a newer, stop-related durable
  status. Tests cover identity mismatch, preview races, and revision-only
  read-back.
- A 409 replaces Confirm with an explicit fresh-review action. The browser
  smoke covers conflict, fresh preview, and a successful subsequent Stop.
- Both Node mutation routes stream-read bounded JSON before parsing. Preview
  accepts only `{}`; confirmation accepts exactly one 64-character lowercase
  hexadecimal `confirmation_id`. Unit tests cover malformed, extra,
  wrong-content-type, and oversized bodies.

### Round 2

- Reviewer A found confirmation's public Node route still buffered an
  unbounded `request.json()` body. Reviewer B independently confirmed it as a
  blocking bounded-mutation issue. The shared bounded confirmation reader and
  tests above resolved it.

### Round 3

- Reviewer A: No actionable findings.
- Reviewer B: No actionable findings.
- Final status: no blocking findings remain.

## Documentation updates

- Updated `ARCHITECTURE.md` with the fixed state-bound Stop boundary and
  `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md` with the narrowed 2C-B scope and
  Vercel-compatible roadmap relationship.

## Publication gate

- Standing authorization covers staging, commit, push, ready PR, merge, and
  continuation. Proposed branch: `feature/2c-b-stop-run-control`; base:
  `main`; commit and PR title: `Add safe Run stop control`.

## Outcome review

- Classification: Successful pending publication.
- User decision: standing authorization records continuation after publication.
- Next slice authorized: Yes, by standing authorization.
