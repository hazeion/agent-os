# Feature Slice Review: Run response control

Status: Verification in progress

Slice: `2c-d-run-response-control`

Date: `2026-08-22`

## Slice contract

### Goal

Let a person review and submit one exact pending approval or clarification for
one selected task-bound Hermes Run from the new Runs workspace.

### In scope

- Fixed loopback preview and confirmation actions for the exact current pending
  approval or clarification.
- Runtime-neutral request and response boundary, identity, capability, binding,
  current-state, confirmation, lock, and post-response verification.
- Two fixed Node routes and an accessible Runs-panel response control with
  clear stale, unavailable, and partial-result recovery.

### Out of scope

- Arbitrary commands, message/steer controls, local-run responses, attachments,
  response history, provider setup, generic bridge forwarding, browser-selected
  runtime references, and legacy Console changes.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The bridge exposes only exact preview and confirmation actions for the current pending request. | Fixed-route tests passed. | Pass |
| AC-2 | Python binds the response to current Run identity, capability, request kind/ID, allowed choice or bounded answer, and post-response state. | Focused response-control tests passed. | Pass |
| AC-3 | Node accepts only exact same-origin response bodies and returns safe projections. | Node body and bridge tests passed. | Pass |
| AC-4 | The Runs page provides accessible approval and clarification controls with usable stale recovery. | Production browser smoke. | Pending: clean CI uses the production static build; local webpack changes the script contract. |
| AC-5 | Existing message, Stop, timeline, and legacy Console behavior remain unchanged. | Focused regressions and Node check passed. | Pass |
| AC-6 | Six Lighthouse runs remain 100/100/100/100. | Lighthouse gate. | Pending: clean CI must run the required Turbopack build. |

### Constraints and recovery

- Approval and clarification stay distinct: an approval accepts only the
  current advertised choice; a clarification accepts only the current structured
  choice or bounded text answer.
- Python owns current pending-request data. The browser receives only the safe
  display projection necessary to review the action and never chooses a bridge
  path, runtime reference, request ID, or action name.
- A confirmation binds the current Run state, request kind/ID, and normalized
  response digest. Changed state or input requires a new preview.
- Hermes remains behind the runtime-neutral adapter. A response accepted but not
  verified is reported as partial and never claimed as complete.
- Rollback removes the fixed routes and panel only. No schema migration or
  Hermes core-file write is permitted.
- Documentation targets: `ARCHITECTURE.md`, implementation plan, and this log.
- Branch/base: `feature/2c-d-run-responses` into `main`.

### Scope discussion and approval

- This is the remaining action-control parity slice before production cutover.
- The active pivot goal provides standing approval for scope, tests,
  publication, merge, and continuation.

## Test strategy

| Acceptance criterion | Planned evidence | What it proves | Limitation |
| --- | --- | --- | --- |
| AC-1 | Exact path/body/size/encoded-ID bridge tests. | No generic mutation route. | Does not call Hermes. |
| AC-2 | Fake runtime tests for identity, capability, request mismatch, choice/text validation, stale state, failure, and read-back. | Safe response sequencing. | Hermes transport remains deterministic. |
| AC-3 | Node request-boundary/body and response allowlist tests. | Browser cannot widen the action. | Does not render the UI. |
| AC-4 | Production Chromium smoke for approval, clarification, stale retry, confirm, and narrow layout. | Rendered user workflow works. | Uses deterministic local fixtures. |
| AC-5 | Existing focused tests and full suite. | Regression detection. | User's dirty seed data may require clean CI confirmation. |
| AC-6 | Six-run production Lighthouse gate. | Every category remains perfect. | Local deterministic evidence. |

### Test discussion and approval

- Standing authorization accepts this strategy.
- Accepted coverage gap: no live remote Hermes response is required before PR;
  the supported adapter path is exercised with deterministic test doubles.

## Implementation record

- Added runtime-neutral pending action and response values, with strict bounded
  fields and choice validation.
- Added fixed private bridge and Node routes for request display, preview, and
  confirmation. The browser receives no runtime reference or Hermes request ID.
- Added an accessible Runs-panel control for the current approval or
  clarification only.
- Confirmation now binds the complete displayed request, Run state and binding,
  and response. A changed prompt, choice list, or request is stale.
- Post-response verification accepts only a confirmed cleared or replaced
  request; all other verification failures are partial failures. A partial
  result clears the confirmation and remains visible in the refreshed Runs
  summary, preventing an automatic retry.

## Verification

- `python3 -m py_compile agent_runtime.py hermes_runtime.py server.py mentat/local_bridge.py` passed.
- `python3 -m unittest tests.test_run_response_control tests.test_agent_runtime -v` passed (20 tests).
- Host-only loopback bridge response-route test passed.
- `npm --prefix web run check` passed (38 tests).
- Next webpack production build and standalone preparation passed. Turbopack
  cannot create its required worker port in this environment.
- Existing browser smoke rejected webpack-only runtime script entries before it
  exercised the Runs control.
- The local Turbopack build cannot create its worker port in this environment.
  Its webpack fallback transfers 213 KB rather than the normal static-build
  ~34 KB and scored mobile Performance 98, so it is not Lighthouse evidence.
  Clean CI remains the production Lighthouse gate.

## Adversarial review

- Reviewer one found incomplete request binding and preview validation; fixed
  by binding all display fields and validating the exact response before preview.
- Reviewer two found missing post-response proof and Unicode UI inconsistency;
  fixed by requiring the original pending request to clear or change and using
  code-point input limiting.
- Final re-reviews: no findings from either reviewer.

## Documentation updates

- Updated the implementation plan and this verification log.

## Publication gate

- Standing authorization recorded. Final review is complete; clean CI is the
  remaining browser/Lighthouse publication gate.

## Outcome review

- Classification: In verification.
- User continuation: authorized by standing approval.
