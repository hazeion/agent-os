# Feature Slice Review: Hermes signed loopback receiver foundation

Status: Complete for the approved foundation slice; publication remains gated
Slice: `hermes-webhook-receiver-foundation`
Date: `2026-08-10`
Review log: `reviews/2026-08-10-hermes-webhook-receiver-foundation.md`

## Slice contract

### Goal

Accept a bounded, signed local Hermes lifecycle webhook quickly and turn it
into a safe, bounded in-memory refresh hint without performing a synchronous
Hermes read or treating the webhook as authoritative state.

### In scope

- Versioned loopback POST endpoint for configured-by-convention local binding IDs.
- Raw-byte HMAC-SHA256 verification with constant-time comparison.
- Exact content type, event allowlist, header/body identity, timestamp, and body-size validation.
- Immediate `202` response for a new valid delivery and `204` for a duplicate.
- Bounded process-local delivery deduplication and hint queue.
- Secret-free HTTP error responses.

### Out of scope

- Durable SQLite delivery records or restart-safe replay protection.
- TOML binding configuration, readiness/health UI, rate limiting, or operator setup tooling.
- Background Hermes reconciliation or browser push updates.
- Remote webhook ingress, Hermes-owned configuration writes, or live Hermes 0.20 verification.
- Agent Console redirect/steer behavior.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A valid signed delivery is accepted without a synchronous Hermes read. | HTTP route integration test and code-path inspection | Pass |
| AC-2 | A duplicate delivery returns success without enqueueing a second hint. | HTTP route integration test | Pass |
| AC-3 | Invalid signature, stale timestamp, unknown event, header mismatch, wrong content type, and oversized body fail closed. | Negative HTTP route tests, including real loopback HTTP unknown-event coverage | Pass |
| AC-4 | The hint queue and dedupe cache remain bounded. | Unit test and source inspection | Pass |
| AC-5 | Existing Mentat behavior remains regression-free. | Focused and full test suites | Partial: webhook-focused tests pass; four unrelated beta/data fixture failures remain in the full suite |

### Constraints and recovery

- Safety: webhook data is untrusted observation; it cannot directly mutate Mentat or Hermes state.
- Compatibility: unconfigured bindings fail closed; existing Hermes 0.19 behavior is unchanged.
- Rendered behavior: not applicable; this slice has no browser-visible changes.
- Rollback or recovery: remove the receiver module/import/route and its tests; no Hermes-owned files are changed.
- Documentation targets: this review log and the Milestone 9 roadmap status if the slice is accepted.
- Version-control strategy: isolate only the webhook module, server wiring, focused tests, review log, and applicable documentation; preserve unrelated worktree changes.

### Scope discussion and approval

- Recommendation and rationale: review the smallest useful receiver foundation before adding durable storage or reconciliation complexity.
- Alternatives considered: review the complete webhook milestone (too broad for one slice); review only the pure verifier (does not exercise the server boundary).
- User decisions: approved the exact scope, review-log path, and test strategy on 2026-08-10.
- Approved at: 2026-08-10, America/Los_Angeles.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No route-level proof that acknowledgment is immediate and independent of Hermes reads. | Start an ephemeral local HTTP server with a stub handler and submit a signed event. | Valid input reaches the receiver and returns `202` without a refresh call. | Does not prove a future background coordinator works. |
| AC-2 | Cache unit coverage exists; HTTP duplicate behavior is untested. | Submit the same signed request twice and inspect response codes and hint count. | Retry is idempotent within one process. | Restart recovery is explicitly out of scope. |
| AC-3 | Verifier negative cases exist, but handler status mapping/body limits are not fully exercised. | Route tests for each required rejection class. | HTTP boundary fails closed with bounded status and no payload leakage. | Does not cover network-level abuse beyond the body limit. |
| AC-4 | Queue capacity is not directly tested. | Cache/queue overflow unit test plus source inspection. | In-memory state cannot grow without bound. | No durable backpressure metrics yet. |
| AC-5 | No baseline was captured before this implementation because the change preceded this workflow. | Current `HEAD` focused tests, then full suite after changes. | Detects regressions against the repository state available for review. | Cannot prove behavior against the exact pre-change working tree. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest tests.test_hermes_webhooks -v` | macOS, Python 3.x | Pass | 5 tests passed. |
| `python3 -m unittest discover -s tests -v` | macOS, Python 3.x | Fail | 941 tests run; 4 failures, 4 skips. Failures are existing beta/data fixture contracts unrelated to the webhook files and correlate with pre-existing dirty worktree changes. |

### Test discussion and approval

- User questions and decisions: User approved the exact scope and test strategy on 2026-08-10.
- Accepted coverage gaps: durable restart-safe dedupe, configuration, rate limiting, reconciliation, UI, live Hermes 0.20, and remote transport are deferred by contract.
- Approved at: 2026-08-10, America/Los_Angeles.

## Implementation record

### Changes

- Existing `hermes_webhooks.py` verifier and delivery cache provide the pure validation boundary.
- Existing `server.py` wiring provides the local POST endpoint, immediate response, and bounded hint queue.
- Route-level tests cover accepted, duplicate, hostile-host, unknown-event, malformed, and bounded-rejection behavior.

### Deviations and decisions

- This workflow began after the initial implementation, so the original pre-change baseline is unavailable.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_hermes_webhooks -v` | macOS, Python 3.x | Exit 0 | 5 passed | Existing verifier/cache coverage. |
| `python3 -m unittest tests.test_hermes_webhooks -v` | macOS, Python 3.x | Exit 0 | 7 passed | Post-Round-2 pure verifier/cache coverage. |
| `python3 -m unittest tests.test_hermes_webhooks tests.test_hermes_webhook_routes tests.test_request_boundary -v` | macOS, Python 3.x with host loopback permission | Exit 0 | 30 passed | Includes real ephemeral loopback HTTP dispatch, host rejection, truncation, duplicate, saturation, and negative-path checks. |
| `python3 -m unittest tests.test_hermes_webhooks tests.test_hermes_webhook_routes tests.test_request_boundary -v` | macOS, Python 3.x with host loopback permission | Exit 0 | 31 passed | Final focused suite; real HTTP rejection matrix includes matching-header unknown-event rejection and canonical secret mapping. |
| `python3 -m py_compile server.py hermes_webhooks.py` | macOS, Python 3.x | Exit 0 | N/A | Syntax check passed. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.x with host loopback permission | Exit 1 | 950 run; 4 failed; 4 skipped | Webhook tests passed. The 4 failures remain unrelated beta/data fixture contracts from dirty worktree changes. |

### Rendered or manual behavior

- Not applicable; no visible UI changes are in scope.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Working-tree diff for `server.py`, `hermes_webhooks.py`, `tests/test_hermes_webhooks.py`, and `tests/test_hermes_webhook_routes.py`.
- Verification evidence: Focused suite initially 26 passed; full baseline 941 run with 4 unrelated failures and 4 skips.
- Rendered artifacts: Not applicable.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P1 | Yes | Valid deliveries were deduplicated before queue-capacity checking, so a full queue returned `202` while dropping the hint. | Yes | Atomically check capacity, enqueue, and record dedupe; return `503` without deduping when full. |
| A-2 | P2 | Yes | A short read was not checked against declared `Content-Length`, allowing a truncated signed body to be accepted. | Yes | Reject incomplete reads with `400`. |
| A-3 | P2 | No | `platform` text had no field-level bound or normalization. | Yes | Normalize to a small allowlist/`other` and bound length. |
| A-4 | P2 | No | Duplicate security headers were accepted using only the first value. | Yes | Reject duplicate signature, event, delivery, and content-type headers. |
| A-5 | P2 | Yes for evidence | Route tests called the handler directly and did not exercise the actual HTTP lifecycle and loopback boundary. | Yes | Add an ephemeral loopback HTTP integration test. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | P1 | Yes | Route tests bypassed `do_POST`, path matching, host/origin checks, and response framing. | Yes | Add real loopback HTTP integration coverage. |
| B-2 | P1 | Yes | Declared body length was not compared with bytes read. | Yes | Reject short reads before signature verification. |
| B-3 | P2 | No | Queue saturation silently acknowledged dropped hints. | Yes | Retry with `503` without recording the delivery. |
| B-4 | P2 | No | Queue/cache overflow was not directly demonstrated by tests. | Yes | Add saturation/retry and boundedness evidence. |
| B-5 | P2 | No | `platform` was copied as arbitrary text. | Yes | Normalize and bound it. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Real HTTP lifecycle was not exercised | Corroborated | Both maintained the finding. | Accept; required by AC-1 and the approved test strategy. | Added ephemeral loopback HTTP test with accepted and hostile-Host requests. |
| Truncated body accepted | Corroborated | Both maintained the finding. | Accept; exact request-body integrity is in scope. | Reject short reads with `400`. |
| Queue full acknowledges dropped delivery | Corroborated | Both maintained the risk; B classified it non-blocking. | Accept; it can falsely acknowledge a valid event and fits queue-bound behavior. | Check duplicate/capacity/enqueue under one lock; return `503` before dedupe on saturation. |
| Unbounded platform field | Corroborated | Both recommended bounding/normalization. | Accept; normalized events must be bounded. | Added allowlist, `other` fallback, and 32-character bound. |
| Duplicate security headers | Unique to Reviewer A | Not applicable; no conflict. | Accept; exact security-header identity is in scope. | Reject duplicate case-insensitive security headers. |
| Direct overflow evidence | Unique to Reviewer B | Not applicable; no conflict. | Accept; add explicit saturation/retry test. | Added route saturation test. |

### Reverification

- Focused tests: 30 passed with host execution for the loopback test.
- Full suite: 949 run; 4 unrelated failures; 4 skips; no webhook failure.
- Next review round or gate result: Round 2 independent re-review in progress.

### Round 2 packet

- Diff/commit reviewed: Complete post-Round-1 working-tree diff, including queue, framing, normalization, and HTTP lifecycle fixes.
- Verification evidence: 30 focused tests passed; 949 full-suite tests run with 4 unrelated failures and 4 skips.
- Rendered artifacts: Not applicable.

#### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A2-1 | P2 | Yes | Signed malformed `hook_event_name: []` could raise `TypeError` and become a `503` temporary failure. | Yes | Validate event type before allowlist membership and map malformed JSON recursion to validation failure. |
| A2-2 | P2 | No | Duplicate `Content-Length` framing was ambiguous. | Yes | Require one length and reject transfer-encoding conflicts. |
| A2-3 | P2 | No | Case/format binding aliases could bypass deduplication while reusing the same environment secret. | Yes | Enforce canonical lowercase binding IDs and one-to-one secret naming. |
| A2-4 | P3 | No | Distinct-event eviction and concurrent dedupe were not directly tested. | Yes | Add bounded eviction evidence. |
| A2-5 | P3 | No | Review log recorded a stale pure-webhook test count. | Yes | Reconcile log counts. |

#### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B2-1 | P2 | Yes for AC-2 evidence | Duplicate delivery was only tested through the direct handler harness, not real HTTP. | Yes | Assert real `204`, empty body, and no second hint over `HTTPConnection`. |
| B2-2 | P2 | No | Duplicate `Content-Length` was not rejected. | Yes | Reject ambiguous request framing. |
| B2-3 | P3 | No | Review log recorded a stale pure-webhook test count. | Yes | Correct the log. |

#### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Malformed typed event can become `503` | Unique to A | No conflicting evidence. | Accept; malformed signed inputs must fail as client validation errors. | Added event type validation and `RecursionError` mapping. |
| Ambiguous `Content-Length`/transfer framing | Corroborated | Both supported rejection. | Accept; exact body boundary is in scope. | Added single-length and transfer-encoding checks plus tests. |
| Binding aliases bypass identity | Unique to A | No conflicting evidence. | Accept; binding identity must be canonical before secret lookup. | Lowercase-only binding IDs and distinct hyphen/underscore env encoding. |
| Real HTTP duplicate behavior not tested | Unique to B | No conflicting evidence. | Accept; AC-2 requires route-level evidence. | Added real `204`/empty-body duplicate assertion. |
| Cache eviction evidence | Unique to A | No conflicting evidence. | Accept as coverage improvement. | Added distinct-event bounded eviction test. |
| Stale review-log count | Corroborated | Both observed it. | Accept as documentation correction. | Current count is reconciled in focused checks above. |

#### Reverification

- Focused tests: 30 passed after Round 2 fixes, including real `202`, `204`, and `403` HTTP responses.
- Full suite: 949 run; 4 unrelated failures; 4 skips.
- Next review round or gate result: Round 3 independent re-review required.

### Round 3 packet

- Diff/commit reviewed: Complete post-Round-2 working-tree diff, including canonical secret mapping, UTC enforcement, HTTP rejection matrix, and negative-length handling.
- Verification evidence: 31 focused tests passed; compile passed. Full-suite rerun pending after this final code state.
- Rendered artifacts: Not applicable.

#### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A3-1 | P2 | Yes for AC-3 evidence | Required negative cases were only direct-harness tested; event-header mismatch lacked route-level evidence. | Yes | Add real HTTP rejection-matrix coverage. |
| A3-2 | P2 | Yes for AC-5 evidence | Full-suite evidence was recorded before the latest fixes. | Yes | Rerun the full suite after final code. |
| A3-3 | P2 | No | Code’s secret convention conflicted with the documented `DEFAULT` environment variable. | Yes | Use the canonical documented mapping and test it. |

#### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B3-1 | P1 | Yes | `local-default` was incompatible with the documented secret environment variable. | Yes | Align implementation and documentation. |
| B3-2 | P2 | Yes for AC-3 evidence | Real HTTP coverage did not exercise the rejection matrix. | Yes | Add real HTTP negative cases. |
| B3-3 | P2 | No | Non-UTC offsets were accepted. | Yes | Require UTC timestamps. |
| B3-4 | P2 | No | Hint queue has no consumer in this foundation slice. | Deferred | Document the limitation and implement the consumer in the next reconciliation slice. |
| B3-5 | P3 | No | Negative `Content-Length` shared the oversized `413` path. | Yes | Return `400` for invalid negative framing. |
| B3-6 | P3 | No | Residual review-log wording was stale. | Yes | Refresh final outcome documentation. |

#### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Real HTTP negative matrix | Corroborated | Both required it. | Accept; required for AC-3 evidence. | Added real HTTP signature, event, content-type, stale, and size rejection tests. |
| Full-suite evidence timing | Unique to A | No conflicting evidence. | Accept; rerun after final code before closing the gate. | Resolved; final rerun recorded 950 tests, 4 unrelated failures, and 4 skips. |
| Secret convention mismatch | Corroborated | A noted compatibility; B classified it P1. | Accept; operator setup must interoperate with the documented plan. | Canonical `local-default` maps to `MENTAT_HERMES_WEBHOOK_SECRET_DEFAULT`; tests updated. |
| Non-UTC timestamps | Unique to B | No conflicting evidence. | Accept; contract specifies UTC. | Reject non-zero offsets and test it. |
| Queue has no consumer | Unique to B | Fits deferred reconciliation scope. | Defer explicitly; no false claim of refresh completion. | Added source comment and outcome limitation. |
| Negative content length status | Unique to B | No conflicting evidence. | Accept; malformed framing is `400`. | Split negative and oversized branches and test it. |
| Residual log wording | Unique to B | No conflicting evidence. | Accept; update final outcome section after suite rerun. | Resolved in the final review-log reconciliation. |

#### Reverification

- Focused tests: 31 passed after the final Round 4 evidence fix, including real HTTP matching-header unknown-event rejection.
- Full suite: 950 run; 4 failed; 4 skipped. All four failures are unrelated beta/data fixture contracts in the pre-existing dirty worktree.
- Next review round or gate result: Round 4 and final post-framing re-review completed; no runtime blockers remain.

### Round 4 packet

- Diff/commit reviewed: Feature-branch working tree with the real HTTP matching-header unknown-event case, final server implementation, and reconciled roadmap/review documentation.
- Verification evidence: 31 focused tests passed; compile passed; full suite ran 950 tests with 4 unrelated failures and 4 skips.
- Rendered artifacts: Not applicable.

#### Reviewer A — correctness and safety

- Result: No blocking runtime correctness or safety findings. The remaining issue was stale review-record evidence, addressed in this log and the roadmap.

#### Reviewer B — compatibility and product

- Result: Identified the missing real HTTP matching-header unknown-event case; the case was added and passed. No runtime-safety findings were known at the Round 4 checkpoint.

#### Reconciliation and disposition

| Finding | Decision and evidence | Change made |
| --- | --- | --- |
| Missing real HTTP unknown-event rejection case | Accept; AC-3 requires route-level proof for every required rejection class. | Added a signed `unknown` event with a matching `X-Hermes-Event` header to the real loopback rejection matrix; it returns `400` and leaves the hint queue empty. |
| Stale review and roadmap status | Accept; final evidence and implementation status must be truthful. | Reconciled acceptance statuses, verification counts, deferred limitations, outcome, and Milestone 9 status. |

## Documentation updates

- Roadmap: Updated in the working tree to identify the receiver foundation as implemented/reviewed while retaining the Hermes 0.19 compatibility baseline and deferred Milestone 9 work; intentionally excluded from the publication packet because it contains unrelated pre-existing edits and links to excluded planning/video artifacts.
- Changelog: Not updated; no release publication is authorized.
- Architecture/operator docs: No changes required for this foundation; setup and live Hermes verification remain deferred.
- Project/session notes: Not applicable to repository publication yet.
- Documentation verification: Review log and working-tree roadmap wording reconciled with the final test evidence; roadmap publication is deferred to a separately isolated documentation slice.

## Publication gate

- Proposed files: `hermes_webhooks.py`, `server.py`, `tests/test_hermes_webhooks.py`, `tests/test_hermes_webhook_routes.py`, and this review log. `ROAD_TO_BETA.md` is intentionally excluded from this publication packet; unrelated roadmap and worktree changes remain excluded and must not be staged.
- Branch and base: `codex/hermes-webhook-receiver-foundation` from `main`.
- Commit message: Pending user approval.
- PR title: Pending user approval.
- PR summary: Pending user approval.
- Unresolved risks: Process-local dedupe is not restart-safe; no asynchronous reconciliation exists yet.
- User authorization and scope: No staging, commit, push, or PR authorization yet.
- Commit hash: None.
- Ready PR URL: None.

## Outcome review

- Classification: Partially successful: the approved receiver foundation passes focused verification, while repository-wide regression evidence is limited by four unrelated existing failures.
- Acceptance criteria summary: AC-1 through AC-4 pass; AC-5 is partial because the focused webhook and boundary suites pass while the full suite has four unrelated beta/data fixture failures.
- Potential bugs or untested paths: Durable restart-safe dedupe, reconciliation consumption, rate limiting, operator health, remote ingress, live Hermes 0.20 behavior, and a live Hermes 0.19 runtime exercise remain explicitly deferred or outside this slice; 0.19 compatibility is supported by additive source inspection and the existing/full regression suites.
- Remaining reviewer dissent: None on runtime correctness or security. Round 4’s missing real HTTP matching-header unknown-event case and the final review’s duplicate `Transfer-Encoding` framing case are both resolved and verified. Publication-scope hygiene remains documented as a separate concern.
- Compatibility/migration/rollback concerns: No Hermes-owned or tracked fixture data changes are required.
- User decision: Approved feature-branch isolation and merged-branch cleanup on 2026-08-10; staging, commit, push, and PR publication remain separately gated.
- Next slice authorized: No.

### Final re-review

- Reviewer A: No blocking security or correctness findings; duplicate and absent `Transfer-Encoding`, framing, HMAC, loopback boundary, bounded state, and response mapping were independently verified.
- Reviewer B: No runtime blockers; AC-1 through AC-4 pass, AC-5 remains partial because the full suite has four unrelated failures and four skips. Publication must exclude unrelated roadmap, fixture, generated, and scratch changes.
- Final evidence: 31 focused tests passed, compilation passed, and 950 full-suite tests ran with 4 unrelated failures and 4 skips.
