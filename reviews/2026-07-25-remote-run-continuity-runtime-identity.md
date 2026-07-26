# Feature Slice Review: Remote Run Continuity and Runtime Identity

Status: Published — ready pull requests open
Slice: `remote-run-continuity-runtime-identity`
Date: `2026-07-25`
Review log: `reviews/2026-07-25-remote-run-continuity-runtime-identity.md`

## Slice contract

### Goal

Keep remote Hermes approvals and clarifications on one continuous stream, recover
safely after a real interruption, and show the selected agent's current
provider/model identity reliably in Agent Console for local and remote
connections.

### In scope

- Keep the Mentat-to-Hermes SSE connection open while a run waits for an exact
  approval or clarification response.
- Retain a bounded, sequenced Hermes run-event journal and replay events after a
  validated client cursor.
- Return the exact current sanitized pending approval or clarification from run
  status as the authoritative recovery path.
- Expose one authenticated, read-only, versioned, secret-free remote profile
  runtime inventory containing profile ID, current provider, and current model.
- Report the effective provider/model used by an active remote run.
- Load the selected agent's current provider/model on initial Agent Console
  render for local and remote connections.
- Clear stale runtime identity while switching agents and refresh after
  connection changes, agent changes, run start/resume/runtime changes,
  approval/clarification continuation, terminal events, new sessions, and a
  successful supported local provider/model change.
- Keep remote provider/model controls disabled while showing their current
  values.

### Out of scope

- Remote provider/model mutation.
- Credential setup, authentication metadata, arbitrary configuration access, or
  browser-visible paths/endpoints/environment names.
- Durable run-event replay across a complete Hermes server restart.
- Redesigning unrelated Agent Console controls.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Two or more sequential approvals/clarifications resume over one uninterrupted upstream SSE subscription without starting another Mentat worker. | Mentat lifecycle integration tests and Hermes run tests. | Verified |
| AC-2 | A reconnect supplies the last verified cursor and receives each missed event once, in order; multiple subscribers do not consume events from one another. | Hermes cursor, replay, retention, and subscriber tests plus Mentat client normalization tests. | Verified |
| AC-3 | If an actionable event is missed, status returns the exact sanitized pending action; Mentat recovers only a matching request and rejects stale, changed, malformed, or unbound actions. | Hermes status contract tests and Mentat recovery/race tests. | Verified |
| AC-4 | Initial load and agent changes show the selected local or remote profile's current provider/model without briefly reusing another agent's values. | Server payload tests and browser-rendered workflow tests. | Verified |
| AC-5 | The Console refreshes runtime identity after every agreed change trigger and uses active-run effective identity when available. | Frontend event/refresh tests and run lifecycle tests. | Verified |
| AC-6 | Remote provider/model identity is visible but mutation controls remain disabled; old Hermes hosts remain compatible and fail closed when recovery capabilities are absent. | Capability compatibility, UI, and negative-path tests. | Verified |
| AC-7 | New contracts remain bounded and secret-free, and replay/status data cannot expose credentials, local paths, raw commands, or unvalidated provider output. | Schema, size, redaction, and recursive privacy tests. | Verified |

### Constraints and recovery

- Safety: approvals and clarifications remain bound to the exact current request
  ID; no blind or inferred response is allowed.
- Compatibility: every new Hermes contract is separately feature-gated and
  versioned; older hosts retain their existing behavior.
- Rendered behavior: agent changes show an explicit loading/unavailable state
  instead of stale provider/model values; remote selectors remain disabled.
- Rollback or recovery: disable the new advertised features to restore the prior
  fail-closed behavior; Mentat may reconcile current status but never guess
  missed history or action details.
- Documentation targets: `ARCHITECTURE.md`, `CHANGELOG.md`, Hermes API contract
  comments/docs, and this review log.
- Version-control strategy: independent ready PRs from
  `codex/remote-run-continuity-runtime-identity`, based on Mentat `main` and
  Hermes `mentat-beta-contracts`.

### Scope discussion and approval

- Recommendation and rationale: persistent streaming is the normal path;
  replay handles genuine transport interruptions; pending-action status is the
  authoritative safety fallback.
- Alternatives considered: reconnect-only replay leaves an avoidable approval
  race; status-only recovery loses non-action events; Mentat-only changes cannot
  provide resilient replay or remote runtime identity.
- User decisions: implement all three continuity layers and current
  provider/model visibility for local and remote profiles; do not add remote
  mutation.
- Approved at: `2026-07-25`, explicitly confirmed by the user.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Mentat ends its reader on a waiting status and starts a second worker; Hermes drops run stream state when the subscriber exits. | Consecutive approval/clarification lifecycle tests with one stream/worker. | Normal interactive continuity has no reconnect race. | Does not simulate every provider tool sequence. |
| AC-2 | Hermes uses one destructive queue and exposes no event cursor. | SSE replay, cursor validation/expiry, dedupe, bounded retention, and two-subscriber tests. | Reconnect and independent subscribers preserve ordered events. | Replay is intentionally in-memory across the server process. |
| AC-3 | Polling exposes only `waiting_*` status, not the current bound action. | Status recovery and malformed/stale/replaced request tests. | Mentat can recover safely without blind approval. | A dead upstream process still cannot resume. |
| AC-4 | Remote profiles omit runtime identity; local payload initially scopes catalog/inventory only to the active profile. | Local/remote multi-profile payload and selected-agent render tests. | The displayed identity belongs to the selected profile. | Provider availability catalogs remain Hermes-owned. |
| AC-5 | Runtime metadata is cached and not refreshed consistently on lifecycle events. | Trigger matrix tests and active-run effective-runtime tests. | Display updates when a relevant event may change runtime. | External config edits without an observable event use normal page refresh. |
| AC-6 | Remote selectors become empty and local-only refresh rejects remote profiles. | Feature-off compatibility and disabled-control browser tests. | Read visibility does not imply remote mutation authority. | Does not add remote switching. |
| AC-7 | New payloads do not exist. | Strict schema, bounds, redaction, and recursive secret-absence tests. | New egress surfaces stay within the existing safety boundary. | Cannot enumerate every possible secret format. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Source inspection of Mentat remote lifecycle | macOS feature worktree | Fail/gap confirmed | Waiting status stops the reader and response handling starts a new worker. |
| Source inspection of Hermes SSE lifecycle | macOS fork worktree | Fail/gap confirmed | Subscriber cleanup removes the shared queue, so later events cannot be published. |
| Source inspection of profile/runtime contracts | Both repositories | Fail/gap confirmed | Remote profile inventory intentionally omits provider/model; local refresh is local-profile-only. |

### Test discussion and approval

- User questions and decisions: added a required uninterrupted-stream test for
  multiple approvals and clarifications.
- Accepted coverage gaps: no automatically billed live-provider call is
  required; deterministic contract tests plus rendered local browser evidence
  are required.
- Approved at: `2026-07-25`, explicitly confirmed by the user.

## Implementation record

### Changes

- Hermes now retains a bounded per-run event journal with monotonic sequence
  identifiers, independent subscriber queues, validated cursor replay, and
  terminal/orphan cleanup.
- Hermes run status now exposes only the exact sanitized current pending action
  and effective runtime identity. Response acknowledgements and runtime changes
  are represented as sequenced run events.
- Hermes exposes an authenticated, complete, profile-scoped runtime inventory
  that rejects unsafe provider/model identifiers and never returns credentials
  or configuration metadata.
- Mentat keeps the initial upstream stream alive through interactive waits,
  submits responses without replacing the worker, reconnects with the last
  verified cursor only after a real interruption, deduplicates verified events,
  and reconciles missed actions from authoritative status.
- Agent Console loads profile runtime identity for local and remote profiles,
  clears stale values during agent/connection changes, ignores out-of-order
  refresh responses, prefers active-run identity, and keeps remote selectors
  disabled.
- Architecture, remote-operation, changelog, Hermes API user, and Hermes
  programmatic-integration documentation now describe the new contracts and
  compatibility boundary.

### Deviations and decisions

- The Hermes repository-wide suite is too large for a practical local
  completion and encounters a pre-existing macOS temporary-path policy failure
  before this feature's gateway tests. The affected gateway/API slice was
  instead run in full with all optional dependencies and passed.
- Replay remains process-local and bounded by design; durable replay across a
  complete Hermes restart remains explicitly out of scope.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_remote_console_runs tests.test_profile_aware_console tests.test_dashboard_behaviors -v` | Mentat worktree, Python 3.13 | Exit 0 | 64 passed | Includes automatic disconnect/replay, duplicate-only retry bounds, sequence-prefix validation, legacy acknowledgement reconciliation, selected-agent runtime precedence, and backend remote-mutation rejection. |
| `uv run --extra dev --extra messaging pytest -q tests/gateway/test_api_server_runs.py tests/gateway/test_api_server.py tests/gateway/test_multiplex_api_server_routing.py` | Hermes fork worktree | Exit 0 | 338 passed | Replay, quoted/repeated-lifecycle/internal-buffer/long-padding credentials, post-state probe replacement, explicit same-line grammar, event ordering, transient buffer bounds, backpressure, byte bounds, approvals, runtime inventory, and authentication. |
| `python -m py_compile server.py remote_hermes.py hermes_transport.py` | Mentat worktree | Exit 0 | 3 modules compiled | Server/client syntax check. |
| `node --check public/core.js` and `node --check public/app.js` | Mentat worktree | Exit 0 | 2 files checked | Frontend syntax check. |
| `git diff --check` | Both worktrees | Exit 0 | No whitespace errors | Patch hygiene. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -v` | Mentat worktree, Python 3.13 | Exit 0 | 795 passed, 4 skipped | Complete Mentat suite after round-five fixes. |
| `uv run --extra all --extra dev pytest -q -x` | Hermes fork worktree, macOS | Exit 1 | 20 passed, 5 skipped, then 1 failed | Stops at pre-existing `tests/acp/test_edit_approval.py::test_write_file_approval_mutates_and_request_includes_diff`: Hermes treats the macOS `/private/var/folders/.../T` pytest temp directory as a protected system path. No feature files are involved. |

### Rendered or manual behavior

- `scripts/browser_smoke.mjs` passed its complete rendered workflow matrix
  against an isolated loopback Mentat server, including approval and
  clarification Console states, agent/runtime controls, responsive layouts, and
  the command manifest.
- Captured `/private/tmp/mentat-remote-run-continuity-home-round2.png` was visually
  inspected. The Emerald Operations Home layout rendered cleanly with current
  agent runtime identity and disabled/read-only-compatible controls.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: all uncommitted diffs in both feature worktrees.
- Verification evidence: focused/full commands and results recorded above.
- Rendered artifacts:
  `/private/tmp/mentat-remote-run-continuity-home.png`.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | High | Yes | `public/app.js` chose a binding-global active run or selected profile's completed run before fresh profile inventory, allowing cross-agent or historical runtime identity. | Yes | Scope runtime override to the selected agent's active run and require a complete provider/model pair. |
| A-2 | High | Yes | A saturated subscriber lost the oldest queued sequence when terminal close inserted a sentinel. | Yes | Never discard an event to close; let the terminal event close the stream or force a clean replay reconnect on overflow. |
| A-3 | High | Yes | Approval registration occurred on the executor thread while the HTTP response handler independently updated status, permitting `running` plus the next pending action. | Yes | Serialize registration on the asyncio loop and derive status/pending action from one mirror snapshot. |
| A-4 | Medium | Yes | A new remote run was seeded with endpoint-global model metadata and could temporarily override the selected profile's exact runtime. | Yes | Leave active-run runtime empty until Hermes emits a validated effective identity. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | High | Yes | Mentat opened only one SSE stream; an EOF/timeout fell into status polling and eventual stop instead of automatic cursor replay. | Yes | Add bounded automatic reconnect from the last verified cursor without resubmission. |
| B-2 | High | Yes | Hermes replay was count-bounded but retained arbitrary raw event fields and had no aggregate byte cap. | Yes | Normalize at the publisher boundary, omit tool/reasoning bodies, redact bounded text, and enforce event/journal byte caps. |
| B-3 | Medium | Yes | Corroborated A-2 saturated subscriber sequence loss. | Yes | Add a full-queue terminal ordering test. |
| B-4 | Medium | Yes | Corroborated A-1/A-4 stale or cross-agent runtime precedence. | Yes | Add selected-agent precedence tests and never use completed runs as current identity. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Cross-agent/historical runtime precedence and endpoint-global run seed | Corroborated | Round 2 pending | Accepted. Focused Mentat tests and rendered workflow pass. | Runtime override now uses only a complete selected-agent active-run pair; completed runs never override inventory; new remote runs start with empty runtime identity. |
| Missing automatic replay reconnect | Unique to Reviewer B | Round 2 pending | Accepted. New disconnect/replay/completion test verifies two subscriptions, cursors `[0, 1]`, one submission, no stop. | Added bounded consecutive reconnect policy, authoritative status recovery between streams, and cursor resume. |
| Replay privacy and byte bounds | Unique to Reviewer B | Round 2 pending | Accepted. New adversarial journal test verifies secret/path/raw-preview omission and aggregate cap. | Added strict public event normalizer, 32 KiB event cap, 4 MiB journal cap, bounded redaction, and omission of raw tool/reasoning bodies. |
| Saturated terminal close drops a sequence | Corroborated | Round 2 pending | Accepted. New full-queue test verifies sequences `1, 2` remain queued in order. | Full close no longer removes an event to insert a sentinel; overflow uses clean disconnect/replay. |
| Sequential approval mirror/status race | Unique to Reviewer A | Round 2 pending | Accepted. Deterministic next-action registration test preserves matching waiting status/action. | Approval registration is scheduled on the asyncio loop and response status is derived from the current pending-action mirror with legacy queue compatibility. |

### Round 2 findings and disposition

| ID | Severity | Finding | Decision and correction |
| --- | --- | --- | --- |
| R2-1 | High | Duplicate replay frames reset the reconnect budget without advancing the verified cursor. | Accepted. Retry reset now requires the stored cursor to advance; duplicate-only bounded-reconnect coverage added. |
| R2-2 | High | Credentials split across adjacent `message.delta` events bypassed per-event redaction. | Accepted. Hermes now withholds a bounded token tail, emits only whitespace-complete chunks, redacts after cross-delta reconstruction, and flushes safely before terminal events. Split provider-key, bearer-token, and path tests added. |
| R2-3 | Medium | Runtime identifiers rejected secret prefixes only at character zero. | Accepted. Boundary-aware credential-token search now applies anywhere in provider/model IDs in both Hermes and Mentat; inventory and event tests cover embedded tokens. |
| R2-4 | Medium | Cursor zero accepted a first event with sequence greater than one. | Accepted. Every sequenced event must equal the prior cursor plus one, including the first event after zero. |
| R2-5 | Medium | Legacy no-ID approval responses lost their lifecycle SSE event under the strict replay schema. | Accepted. The public event schema retains a bounded optional-ID legacy response variant; exact-ID Mentat behavior is unchanged. |
| R2-6 | Medium | A delayed loop callback could mirror an approval already resolved through the legacy path. | Accepted. The queued callback re-checks the exact core request before adding status/action/event state. |
| R2-7 | Medium | Terminal replay output/error truncation was not explicit for generic SSE clients. | Accepted. Terminal events now carry bounded preview completeness metadata and documentation identifies run status as the authoritative terminal result. |

### Round 3 findings and disposition

| ID | Severity | Finding | Decision and correction |
| --- | --- | --- | --- |
| R3-1 | High | A bearer value longer than the withheld tail could be emitted separately from its credential marker; the first regression assertion checked only the combined phrase. | Accepted. Credential labels/schemes and their following token are now parsed as one lexical unit, incomplete markers carry a redact-next-token state across boundaries, long opaque tokens are asserted absent, and terminal status uses the same sanitizer. |
| R3-2 | Medium | A single multi-megabyte delta was concatenated before the retained-buffer cap. | Accepted. Oversized incoming deltas are replaced before concatenation; retained buffer coverage asserts the original value never enters state. |
| R3-3 | Medium | Buffered text could receive a later sequence than intervening tool/lifecycle events. | Accepted. Every non-delta ordering boundary flushes sanitized buffered text first; delta→tool ordering is asserted. |
| R3-4 | Medium | Hermes' valid legacy no-ID approval event was rejected by Mentat. | Accepted. Mentat accepts the explicit legacy-unbound variant, preserves its exact local action until an immediate authoritative status read, then clears, replaces, or completes from that status. End-to-end lifecycle coverage added. |

### Round 4 findings and disposition

| ID | Severity | Finding | Decision and correction |
| --- | --- | --- | --- |
| R4-1 | High | Quoted bearer assignments such as `Authorization: "Bearer …"` and `Authorization='Bearer …'` left the opaque value outside the credential regex match. | Accepted. Quoted and unterminated-quoted values are consumed as one credential unit before generic redaction; terminal and streaming tests cover colon/equal and bare-bearer forms. |
| R4-2 | High | A credential marker split by a non-delta lifecycle event before the word `Bearer` completed could lose its parser state and expose the later token. | Accepted. Hermes now carries a bounded lexical marker probe across lifecycle events and suppresses the remainder of the credential line once the marker completes. A matrix tests every character split of plain and quoted assignments across tool, reasoning, approval, clarification, and terminal boundaries. |

### Round 5 findings and disposition

| ID | Severity | Finding | Decision and correction |
| --- | --- | --- | --- |
| R5-1 | High | More than 128 legal whitespace characters between a lifecycle-split credential label and its delimiter exhausted the raw probe cap before the assignment was recognized. | Accepted. The cross-event state now carries a bounded normalized lexical prefix rather than raw padding and fails closed for the rest of a recognized credential line. Plain, single-quoted, and double-quoted long-padding tests assert absence from journal and live subscriber output. |
| R5-2 | High | Provider-switch preview/apply endpoints relied on disabled remote UI controls and could directly mutate the same-named local Hermes profile while a remote binding was selected. | Accepted. Both backend paths now execute under the Hermes connection-operation lock and require the selected transport to be local before inventory or mutation code runs. Direct remote preview/apply regression coverage verifies a 409 fail-closed response and no inventory or apply calls. |

### Round 6 findings and disposition

| ID | Severity | Finding | Decision and correction |
| --- | --- | --- | --- |
| R6-1 | High | Ordinary delta-buffer compaction could publish a partial credential label plus long padding without carrying its normalized probe state, so a later delimiter/value could escape without any lifecycle event. | Accepted. The same normalized probe state is now recorded across every public buffer emission, and terminal flush first reconciles the retained tail through that state. Plain and quoted tests cover padding at 257, 400, and 1024 characters and assert absence from both journal and live subscriber output. |
| R6-2 | Process | The correctness/safety reviewer pass was interrupted by an automated safety filter before producing a substantive review. | The pass is not counted as a completed independent review. The same reviewer will receive a narrower behavior-oriented packet after the round-six correction. |

### Round 7 findings and disposition

| ID | Severity | Finding | Decision and correction |
| --- | --- | --- | --- |
| R7-1 | High | Repeated lifecycle boundaries inside one credential marker could apply the latest retained tail twice, corrupt the normalized probe, and lose the marker before its value arrived. | Accepted. Probe advancement is now consolidated at the public-emission boundary: each emitted chunk advances state exactly once, whether emitted by routine compaction or lifecycle flush. A two-boundary marker regression asserts journal and subscriber output. |
| R7-2 | High | One-shot redaction accepted CR/LF through `\s`, while streaming state treated a line break as the end of a credential line. | Accepted by narrowing and documenting the grammar consistently. Credential assignment matching now permits horizontal spaces/tabs only; CR/LF explicitly terminates the lexical assignment in regex, stream state, docs, and LF/CRLF regressions. |

### Round 8 findings and disposition

| ID | Severity | Finding | Decision and correction |
| --- | --- | --- | --- |
| R8-1 | High | If a carried partial marker was invalidated by one emitted chunk, the pre-call state flag prevented discovery of a different valid marker suffix at the end of that same chunk. | Accepted. After applying prior state, the emission is rescanned whenever no marker/redaction state remains. A false-prefix-to-valid-marker regression verifies the later value is absent from retained output. |

### Round 9 final reviewer confirmation

| Reviewer | Result | Independent evidence |
| --- | --- | --- |
| Correctness and safety | No blockers | Reproduced prior failure cases as fixed; exercised 132 marker variants across lifecycle boundaries, delimiters, quotes, optional Bearer syntax, long spaces/tabs, journals, and live subscribers; rechecked cursor, terminal, pending-action, runtime ownership, and provider lock paths. |
| Compatibility and product | No blockers | Ran the 26-test focused state matrix plus 500 randomized chained-prefix streams; rechecked Mentat replay/recovery/runtime/provider paths, compatibility behavior, and backend local-only provider authority. |

### Reverification

- Focused tests: Mentat 64 passed; Hermes gateway/API 338 passed.
- Full suite: Mentat 795 passed, 4 skipped. Hermes repository-wide limitation
  remains the unrelated ACP macOS temp-path test documented above.
- Rendered behavior: complete browser smoke passed again; round-two screenshot
  visually inspected at
  `/private/tmp/mentat-remote-run-continuity-home-round2.png`.
- Next review round or gate result: both independent reviewers reported no
  blockers on the exact current diffs; publication approval remains pending.

## Documentation updates

- Roadmap: use this review log as the slice record; no separate roadmap file.
- Changelog: `CHANGELOG.md`.
- Architecture/operator docs: `ARCHITECTURE.md`, `REMOTE_HERMES.md`, Hermes
  API-server user guide, and Hermes programmatic-integration guide.
- Project/session notes: this review log.
- Documentation verification: Markdown structure, capability tables, same-line
  redaction grammar, and local-only provider mutation authority were inspected
  against the implemented names and versions. Both reviewers reported no
  documentation blockers.

## Publication gate

- Proposed Mentat files: `ARCHITECTURE.md`, `CHANGELOG.md`,
  `REMOTE_HERMES.md`, `hermes_transport.py`, `public/app.js`,
  `public/core.js`, `remote_hermes.py`, `server.py`,
  `tests/test_profile_aware_console.py`, `tests/test_remote_console_runs.py`,
  and this review log.
- Proposed Hermes files: `gateway/platforms/api_server.py`,
  `tests/gateway/test_api_server.py`,
  `tests/gateway/test_api_server_runs.py`, `tools/approval.py`,
  `website/docs/developer-guide/programmatic-integration.md`, and
  `website/docs/user-guide/features/api-server.md`.
- Branch and base: `codex/remote-run-continuity-runtime-identity` from Mentat
  `main`; same branch name from Hermes `mentat-beta-contracts`.
- Proposed Mentat commit message: `feat: keep remote Hermes runs continuous`.
- Proposed Hermes commit message:
  `feat(api): add replayable interactive run contracts`.
- Proposed Mentat PR title:
  `Keep remote Hermes runs continuous and show runtime identity`.
- Proposed Hermes PR title:
  `Add replayable interactive run and runtime identity contracts`.
- PR summary: publish the paired Mentat/Hermes contracts for persistent
  approval and clarification streaming, bounded cursor replay, authoritative
  pending-action recovery, current profile/run runtime identity, and
  backend-enforced read-only remote provider controls.
- Unresolved risks: Hermes replay is intentionally in-memory across process
  restarts; remote provider mutation remains out of scope; credential
  assignment redaction is explicitly same-line and cannot enumerate every
  possible sensitive-value format; the unrelated macOS protected-temp-path
  test prevents a clean repository-wide Hermes result.
- User authorization and scope: the user explicitly continued past the
  publication gate after reviewing the exact commit, push, and ready-PR plan.
- Implementation commit hashes: Mentat
  `b3e6889944562a760bf4df7b644b27fbb2cbaede`; Hermes
  `fbd5e42c29b783cba739b959c47b091b17561375`. The Hermes commit was
  metadata-only amended after publication to replace a machine-local author
  address with the repository owner's GitHub noreply identity.
- Ready PR URLs: Mentat
  `https://github.com/hazeion/agent-os/pull/64`; Hermes
  `https://github.com/hazeion/hermes-agent/pull/2`.

## Outcome review

- Classification: Successful implementation, verified, and published as
  ready pull requests.
- Acceptance criteria summary: AC-1 through AC-7 verified.
- Potential bugs or untested paths: no live paid-provider run was required;
  process-restart replay and remote provider mutation remain deliberately out
  of scope; repository-wide Hermes execution retains the documented unrelated
  macOS limitation.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: new remote contracts remain
  separately capability-gated; disabling advertisement restores the prior
  fail-closed behavior, and no durable migration is required.
- User decision: implementation, test strategy, and commit/push/ready-PR
  publication approved and completed.
- Next slice authorized: No.
