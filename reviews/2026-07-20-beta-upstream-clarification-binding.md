# Feature Slice Review: Upstream Runs Clarification Binding

Status: Published upstream as draft; integration pending
Slice: `beta-upstream-clarification-binding`
Date: `2026-07-20`

## Slice contract

### Goal

Give authenticated Hermes Runs clients a bounded, typed, exact-request way to
answer a clarification without using free-form continuation or dashboard APIs.

### In scope

- Enable `clarify` only for the stoppable Runs lifecycle.
- Emit a stable request ID and a versioned, bounded request payload.
- Redact secrets before question or choice text leaves Hermes.
- Accept either an exact choice ID or bounded free text on a fixed Runs route.
- Bind every response to the run, session, and still-pending request.
- Keep the run waiting until the exact response is accepted, then verify state.
- Advertise and document the authenticated capability.

### Out of scope

- Mentat UI or browser routes.
- Approval responses, session continuation, profiles, Kanban, or images.
- Enabling clarification on Chat Completions or Responses.
- Using normal chat input as an implicit clarification answer.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A Runs clarification event has an exact ID and bounded typed prompt. | Event integration and privacy tests | Pass |
| AC-2 | Choice responses use server-issued choice IDs; text responses are length-bounded. | Positive and validation tests | Pass |
| AC-3 | Stale, unknown, cross-run, or already-resolved IDs cannot answer another request. | Negative binding tests | Pass |
| AC-4 | Secrets are redacted and oversized model text cannot produce an unbounded event. | Redaction and bounds tests | Pass |
| AC-5 | Stop/cleanup releases a waiting clarification without hanging the run. | Stop and cleanup regression tests | Pass |
| AC-6 | Authenticated capabilities and docs define the exact contract. | Capability test and docs inspection | Pass |
| AC-7 | Existing API surfaces and messaging clarification remain compatible. | Focused regression suites | Pass |

### Constraints and recovery

- Unknown or changed requests fail closed.
- Only the exact Runs API session may resolve the request.
- Question/answer text is bounded and secret-redacted; local paths are not
  treated as secrets and may remain when needed to answer the question.
- Rendered behavior is not applicable; this is an HTTP contract.
- Rollback removes the additive route, capability, Runs-only tool enablement,
  and callback while leaving existing messaging clarification untouched.
- Version-control strategy: independent Hermes branch from current `main` and
  a separate upstream draft PR.

### Scope discussion and approval

- Recommendation: reuse Hermes' exact clarification primitive, but add a
  run/session binding check and typed HTTP schema instead of accepting arbitrary
  chat text.
- Alternatives rejected: TUI JSON-RPC is a different host boundary; normal
  continuation is not request-bound or safely stoppable.
- User decision: standing authorization applies to slice scope, tests,
  publication, and continuation without another approval prompt.

## Test strategy

Use behavior tests for request emission, typed choice/text responses, stale and
cross-run rejection, bounds/redaction, stop cleanup, capabilities, and existing
messaging/core compatibility. Run focused suites without file retries, then the
canonical upstream suite or document any pristine-main failures exactly.

## Implementation record

- Hardened Hermes' shared clarification primitive with an exact, optional
  session binding and atomic single-use resolution while preserving existing
  messaging callers.
- Enabled `clarify` only for `/v1/runs`, with a per-run callback that emits a
  versioned `clarify.request` event containing a stable transport-safe ID,
  server-issued choice IDs, bounded text, and secret-redacted labels.
- Added `POST /v1/runs/{run_id}/clarification` for typed choice or text
  responses. Invalid, stale, resolved, and cross-run IDs fail closed.
- Added stop, finalization, and orphan cleanup for pending clarification waits;
  a stopped run cannot be put back into a waiting state by a delayed event.
- Advertised the response, request-binding, prompt-version, and event
  capabilities and documented the HTTP schema. Chat Completions and Responses
  remain headless and unchanged.

## Verification

- Focused API, core tool, and messaging compatibility run: `472 passed`,
  `0 failed` across ten files.
- Final focused API/core run after cleanup hardening: `307 passed`, `0 failed`
  across five files.
- Post-rebase focused API/core/messaging compatibility run: `472 passed`,
  `0 failed` across ten files.
- Ruff: passed on all changed Python files.
- Python compile, diff whitespace, and Windows-footgun checks: passed.
- Canonical full Hermes suite: `43,605 passed`, `26 failed` across 2,113 files.
  The failures are the exact same 12-file pristine-main set already reproduced
  on this macOS/Python 3.13 host: Anthropic credential fixtures, `/tmp` versus
  `/private/tmp`, Linux/systemd assumptions, host command availability, and
  process timing. Two unrelated large-suite/performance tests failed once and
  passed on retry; the Matrix file passed all 251 tests but exited non-zero.

## Adversarial review

Deferred by explicit user direction until all Milestone 2 blockers are closed.

## Publication gate

Standing authorization applies. Exact publication packet:

- Hermes source: `/tmp/mentat-hermes-approval.DhdMme/hermes-baseline`
- Branch: `feat/http-clarification-binding-main`
- Files: API server, clarification primitive, focused behavior tests, and two
  API-server documentation pages listed by the final staged diff.
- Commit message: `feat(api): bind Runs clarification responses`
- Destination: `hazeion/hermes-agent`, same branch name.
- External publication: open a draft pull request to
  `NousResearch/hermes-agent:main`; do not mark ready or merge.
- Mentat evidence: commit only this review log on a separate Mentat branch and
  open a separate draft PR; do not update README or mark the beta blocker
  complete before upstream availability.

Publication result:

- Rebased onto upstream `main` at `8f33e3968`.
- Hermes commit: `704617f9434b1e5eaa1765a5fd3c97bc804380dc`.
- Fork branch:
  `hazeion/hermes-agent:feat/http-clarification-binding-main`.
- Upstream draft PR: https://github.com/NousResearch/hermes-agent/pull/68105

## Outcome review

Implementation and local verification are complete. Upstream publication and
integration remain; Mentat must continue to report clarification as blocked
until the Hermes capability is merged and available in an installed release.
