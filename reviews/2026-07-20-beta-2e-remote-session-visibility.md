# Feature Slice Review: Remote Session Visibility

Status: Successful; ready PR and hosted implementation matrix complete
Slice: `beta-2e-remote-session-visibility`
Date: `2026-07-20`

## Goal

Show a bounded read-only list and replay of sessions from the selected remote
Hermes endpoint without exposing endpoint-owned identifiers or weakening local
session behavior.

## In scope

- Require authenticated `session_resources` plus the exact advertised fixed
  list, detail, and message endpoints.
- List a fixed maximum of recent Hermes-listable sessions with bounded title,
  model, timestamps, counts, usage, status, and preview metadata.
- Replace upstream session IDs with process-private Mentat aliases bound to the
  current connection; reject stale or cross-connection aliases.
- Fetch one exact aliased projected session and its bounded user/assistant
  message replay; fail closed if its message identity changes after listing.
- Mark compression-projected history as a latest partial segment because the
  upstream messages endpoint does not return ancestor turns.
- Keep upstream session IDs, connection endpoint identity, transport headers,
  Mentat's connection credential, system prompts, model configuration,
  reasoning, tool arguments, and arbitrary metadata out of browser responses
  and retained Console history.
- Preserve local SQLite session list/detail/replay behavior unchanged.
- Fail closed on changed capabilities, malformed/broad responses, unsafe IDs,
  pagination uncertainty, or a changed connection.
- Focused/full/static tests, two independent adversarial reviews, docs, ready
  PR, hosted matrix, and merge.

## Out of scope

- Session continuation/chat, create, fork, rename, end, delete, or search.
- Remote session-chat SSE, because it has no matching status/stop operation.
- Passing `session_id` to Runs until Hermes advertises that input as an exact
  stoppable continuation capability.
- Approval responses, clarification, attachments, Context Packs, images,
  artifacts, profiles, providers, skills, Kanban, or cron.
- Durable upstream identifiers across a Mentat restart.
- README changes; installation and first-run setup are unchanged.

## Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Remote sessions appear only with `session_resources` and exact list/detail/messages endpoints. | Capability tests | Complete |
| AC-2 | Browser payloads contain only bounded public fields and Mentat aliases; upstream IDs and Mentat connection secrets are recursively absent. User-authored replay text is returned as content, not treated as a general-purpose secret scanner. | Client/server privacy tests | Complete |
| AC-3 | Detail/replay resolves only a current alias bound to the selected connection and exact upstream session. | Binding and stale-alias tests | Complete |
| AC-4 | Messages are limited to bounded user/assistant text; non-conversation roles are omitted, while malformed conversation content, reasoning, and tool arguments never cross the public boundary. | Schema/bounds tests | Complete |
| AC-5 | Local session behavior and remote 2C run/cancel/safe-stop behavior remain unchanged. | Compatibility/full suite | Complete |
| AC-6 | Remote continuation remains unavailable before submission and no session mutation route is added. | Negative route/UI tests | Complete |
| AC-7 | Static/focused/full checks, two reviewers, docs, and hosted supported matrix pass. | Verification record | Complete |

## Upstream evidence

- `/v1/capabilities` advertises `session_resources` and fixed `GET` endpoints
  for `/api/sessions`, `/api/sessions/{session_id}`, and
  `/api/sessions/{session_id}/messages`.
- List supports bounded `limit`/`offset`; Mentat will request one fixed page and
  report truncation rather than following arbitrary pagination.
- Session responses omit full system prompts/model config, but Mentat still
  independently allowlists and bounds every returned field.
- Runs currently accepts a `session_id` body field without a distinct feature
  declaration. Session chat/stream is advertised, but exposes no matching
  status/stop mutation. Continuation is therefore deferred.

## Test strategy

| Area | Planned evidence |
| --- | --- |
| Client | Exact paths/query, bearer auth, response objects, bounds, malformed schemas, private reflection |
| Alias boundary | Same-connection resolution, stale/cross-binding rejection, no upstream ID in public payloads |
| Server/UI | Remote list/detail/replay selection, bounded rendering, local compatibility, continuation disabled |
| Regression | Existing remote Runs, cancellation, approval safe-stop, connection switching, history |

## Baseline

- Merged blocker audit: PR `#32`, merge `32b86ca`.
- Exact final hosted run `29715640495`: all 42 jobs passed.
- Local full suite before this slice: 638 passed, 4 skipped.
- README remains intentionally unchanged.

## Implementation

- `remote_hermes.py` validates the exact advertised session resource endpoints
  and permits only one fixed Hermes-list query plus validated detail/messages
  paths. All reads use the owner-private bearer credential, bounded response
  size, fixed timeouts, redirect refusal, and strict normalized schemas.
- Hermes-listable sessions receive random process-private aliases bound to the
  active connection. Stale, evicted, malformed, or cross-connection aliases fail
  before an upstream detail read.
- Only bounded public session metadata and user/assistant text cross the
  browser boundary. Upstream session/message IDs, lineage, tool calls,
  reasoning, system/model configuration, arbitrary metadata, endpoint identity,
  and the Mentat transport credential are omitted.
- Hermes' list endpoint already projects compression chains to their current
  tip. Mentat binds that surfaced identity exactly, marks projected transcripts
  partial, and fails closed if the messages endpoint later resolves elsewhere.
- Existing local list/detail/replay handlers remain the exact local-mode path.
  Remote continuation and every session mutation remain unavailable.
- `ROAD_TO_BETA.md`, `REMOTE_HERMES.md`, `ARCHITECTURE.md`, and `CHANGELOG.md`
  record the delivered read-only slice and remaining continuation blocker.
  `README.md` is unchanged because setup did not change.

## Local verification

- `python3 -m py_compile remote_hermes.py hermes_transport.py server.py`: pass.
- `python3 -m unittest tests.test_remote_sessions tests.test_remote_console_runs tests.test_hermes_transport -v`: 46 passed after fixes.
- `python3 -m unittest tests.test_remote_sessions tests.test_remote_console_runs tests.test_hermes_transport tests.test_dashboard_behaviors tests.test_usability_features_ui tests.test_visual_contract tests.test_beta_contract tests.test_ci_workflow -v`: 107 passed.
- `python3 -m unittest discover -s tests -v`: 650 passed, 4 skipped after fixes.
- `python3 -m compileall -q .` plus `node --check` for `public/core.js`,
  `public/app.js`, and `scripts/browser_smoke.mjs`: pass.
- `git diff --check`: pass.

## Hosted verification

- Ready PR `#33` published at implementation commit `a5885c8`.
- GitHub Actions run `29717574858`: all 42 supported-platform jobs passed
  (macOS and Ubuntu on Python 3.11-3.13, plus all 36 Windows shards).

## Independent review and publication

Round 1 found six actionable issues:

- Safety reviewer: P1 cross-record upstream-ID reflection and P2 stale detail
  rendering after selection/connection changes.
- Compatibility reviewer: high-severity rejection of valid listable branches,
  high-severity reliance on lineage metadata absent from detail responses,
  medium-severity complete-history claims for partial compressed segments, and
  medium-severity missing status/preview metadata promised by the contract.

Fixes implemented before re-review:

- Cross-check every public list record against all surfaced, parent, and
  lineage IDs in the bounded response; check detail fields against their own
  structural IDs.
- Accept upstream listable branches. Bind the already-projected list identity
  and fail closed if message resolution changes afterward.
- Retain only a boolean partial-history marker in the alias, expose an explicit
  latest-segment notice, and avoid calling its first visible request the
  original intent.
- Normalize and expose bounded status and preview metadata.
- Clear selected detail when the current alias disappears and gate asynchronous
  detail rendering with a monotonically increasing request generation plus the
  current alias.

Re-verification and two zero-finding re-reviews pending.

Round 2 re-review confirmed the prior compatibility and UI fixes, then both
reviewers found one remaining P1 privacy gap: replay text was checked against
the selected tip ID but not every other surfaced/parent/lineage ID known from
the bounded list. Mentat now carries that complete bounded identity set only in
the process-private alias record, adds any structural IDs observed at detail,
and rejects user or assistant replay text reflecting any of them. Direct and
list-to-detail server tests cover other surfaced IDs plus compression roots.

Round 3 re-review found one remaining P1 alias-refresh gap: the bounded alias
record retained old identities before current list identities, so enough list
churn could drop newly surfaced IDs before replay validation. A successful list
refresh now replaces the alias identity set with the complete current bounded
page, while detail enrichment prioritizes newly observed structural IDs. A
two-page churn regression verifies that a late identity from the refreshed page
survives alias reuse and is rejected when reflected in replay text.

Round 4 produced two unique findings that both peers independently reproduced
and maintained after cross-review. The safety reviewer found that a saturated
flat alias set could still drop a current detail parent or lineage ID before
message validation. The compatibility reviewer found that the expanded focused
test count was stale and its command was not reproducible from the log.

The alias now retains only the complete current-list identity set. Each detail
read forms the exact de-duplicated union of that set and the current detail's
parent/lineage IDs; an over-bound union fails closed rather than truncating.
The saturated-alias regression verifies that message retrieval is never called
when the exact required set exceeds the bound. The expanded focused command and
fresh 107-test result are now recorded verbatim above.

Round 5 independently re-reviewed the complete slice after those corrections.
The correctness/safety reviewer and compatibility/product reviewer both
reported `ZERO FINDINGS`. The local adversarial review gate is complete;
publication and the hosted supported-platform matrix remain pending.
