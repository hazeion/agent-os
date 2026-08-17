# Feature Slice Review: Hermes native event migration

Status: Ready for publication
Slice: `hermes-native-event-migration`
Date: `2026-08-14`
Review log: `reviews/2026-08-14-hermes-native-event-migration.md`

## Slice contract

### Goal

Use privacy-minimized stock Hermes webhook events to wake Mentat's existing
authoritative session, agent, attention, and Kanban read paths, then notify an
open dashboard immediately through a payload-free browser event stream.

### In scope

- Retain the four qualified lifecycle events and add stock Hermes
  `on_session_finalize`, `on_session_reset`, `post_api_request`,
  `api_request_error`, and `post_tool_call` events as readback wakeups.
- Add all eight stock Kanban observer events: `kanban_task_claimed`,
  `kanban_task_completed`, `kanban_task_blocked`,
  `on_kanban_worker_spawned`, `on_kanban_worker_exited`,
  `on_kanban_worker_stale_claim`, `on_kanban_task_updated`, and
  `on_kanban_dispatch_tick`.
- Map each event to a fixed set of existing authoritative projections. Treat
  claimed/completed/blocked as distinct transitions; manual updates do not
  stand in for them.
- Ignore all event-specific payload fields. Never persist, log, project, or
  send raw webhook fields to the browser.
- Publish successful authoritative refreshes over a bounded, same-origin,
  loopback-only Server-Sent Events channel containing only a schema version,
  sequence number, timestamp, and fixed projection names.
- Coalesce browser wakeups and invoke existing dashboard APIs. Retain the
  30-second browser poll and 60-second server reconciliation as fallbacks in
  this slice.
- Document exact stock Hermes v2026.8.13 source/process registration evidence
  and operator configuration.

### Out of scope

- Trusting webhook payloads as state or mutation confirmation.
- Persisting token counts, model names, tool names, task IDs, assignees,
  summaries, reasons, paths, prompts, arguments, results, response text, or raw
  bodies from webhook deliveries.
- `pre_api_request`, `pre_tool_call`, `pre_llm_call`, or `post_llm_call`; stock
  payloads expose request/conversation content and add no required authority.
- Editing Hermes configuration automatically.
- Reducing or removing fallback polling, custom telemetry, or fork contracts;
  that is slice 9I.
- Adding Kanban mutations or new UI controls. Existing confirmed Kanban adapter
  mutations remain unchanged.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Every in-scope stock event is signed, allowlisted, mapped to a fixed projection set, and unknown events remain rejected. | Verifier and mapping contract tests for every event. | Pass |
| AC-2 | Event-specific private fields cannot enter normalized events, coordinator state, health, logs, SSE frames, or browser state. | Adversarial privacy payload tests and source contract scans. | Pass |
| AC-3 | Kanban claimed, completed, blocked, manual-update, worker, and dispatch events each wake authoritative Kanban readback; webhook summaries/reasons/paths are discarded. | Event-transition matrix tests plus adapter readback tests. | Pass |
| AC-4 | Stock Hermes v2026.8.13 CLI, Gateway, dispatcher, and worker process paths register outbound hooks where required; missing emitters/deliveries still converge. | Exact-source contract fixture/tests and dropped-event reconciliation test. | Pass |
| AC-5 | Successful readbacks publish only bounded projection hints through a loopback/same-origin SSE endpoint with bounded clients/history, reconnect, heartbeat, and disconnect behavior. | Broker unit tests and live HTTP route tests. | Pass |
| AC-6 | The browser coalesces push hints, refreshes affected existing APIs, handles Kanban readback, reconnects safely, and retains periodic polling fallback. | Browser contract tests and computer-use network/UI validation. | Pass |
| AC-7 | Hermes absent, unconfigured, legacy, Safe Mode, duplicate, out-of-order, storm, and dropped-event behavior remains safe and compatible. | Existing compatibility suite plus focused regression tests. | Pass |
| AC-8 | No visible regression occurs and Lighthouse reports 100/100/100/100 before publication. | Full suite, browser smoke/computer-use, and Lighthouse artifact. | Pass |

### Constraints and recovery

- Safety: Webhooks wake; existing adapter readbacks prove. Browser events carry
  projection names only and grant no mutation authority.
- Compatibility: Existing four-event configurations continue to work. Older or
  unconfigured Hermes installations retain polling/reconciliation behavior.
- Rendered behavior: No new controls or layout changes. Open views refresh more
  promptly without stealing focus, scrolling, or disabling the console.
- Rollback or recovery: Disable the Hermes target or remove the additional
  event names while retaining a schema-v4-capable Mentat binary; polling and
  reconciliation remain intact. Do not downgrade to a pre-9H binary after the
  private database has migrated to schema version 4.
- Documentation targets: `ARCHITECTURE.md`, `CHANGELOG.md`,
  `MILESTONE_9_WEBHOOK_IMPLEMENTATION_PLAN.md`, and this review log.
- Version-control strategy: branch `codex/hermes-native-event-migration`, based
  on accepted 9G commit `ba73948`, ready PR targeting the 9G branch so the
  Milestone 9 stack remains reviewable.

### Scope discussion and approval

- Recommendation and rationale: qualify only post-operation observations and
  lifecycle/Kanban events that can wake an existing readback. Add browser push
  before any polling retirement so missed delivery and old-runtime behavior
  stay correct.
- Alternatives considered: trusting safe-looking fields was rejected because
  webhook delivery is best effort; adding pre-call and post-LLM events was
  rejected because stock payloads include private content and duplicate safer
  wakeups; removing polling now is deferred to 9I pending soak evidence.
- User decisions: The user directed migration of every suitable feature,
  including Kanban, and explicitly granted standing approval for feature and
  workflow decisions. This is a recorded exception to the skill's per-decision
  approval pauses; it does not authorize destructive actions or scope beyond
  Milestone 9.
- Approved at: `2026-08-14`, by the user's standing approval.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Receiver has only four events. | Exhaustive allowlist and event/projection table tests. | Public contract and routing are exact. | Does not prove stock emission. |
| AC-2 | Existing normalizer ignores unknown data but expanded private payload families are untested. | Poison-value payload test across every new event; scans of public/state surfaces. | Private event fields are discarded at ingress and absent downstream. | Process memory briefly holds the signed request body. |
| AC-3 | Only `subagent_stop` wakes bounded Kanban readback. | Exhaustive Kanban mapping and authoritative adapter tests. | Every transition family causes verified live readback without trusting payload state. | Does not add new Mentat mutations. |
| AC-4 | Lifecycle registration was proven, but Kanban dispatcher/worker topology was not. | Version-pinned stock source manifest and fixture test; existing reconciliation drop test. | Events exist at post-commit sites and relevant entrypoints register outbound targets. | A real long-running Kanban job is impractical in CI; source proof is paired with generic live signed delivery. |
| AC-5 | No browser push endpoint exists. | Broker concurrency/bounds tests and live HTTP SSE tests. | Stream schema, cursor recovery, client cap, heartbeat, and local-origin boundary. | Browser network scheduling is also checked manually. |
| AC-6 | Dashboard refreshes only on timers/user actions. | Static browser contract tests, browser automation, request observation. | Push starts, coalesces, calls existing APIs, and leaves fallback poll. | Timing assertions use bounded windows rather than exact milliseconds. |
| AC-7 | Existing compatibility covers only four events. | Full existing webhook/legacy/live validation plus new storm and out-of-order cases. | Migration does not weaken fallback or admission controls. | External Hermes network delivery still depends on operator configuration. |
| AC-8 | No 9H implementation exists. | Full unit suite, package checks, computer-use, Lighthouse. | Repository and rendered release gates pass. | Platform CI follows publication. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository/worktree inspection | macOS, branch `codex/hermes-native-event-migration` | Pass | Clean worktree based on accepted 9G `ba73948`. |
| Contract gap inspection | Python/vanilla JS sources | Fail as expected | Receiver has four events; no SSE endpoint or `EventSource`; browser uses a 30-second interval. |
| Exact stock source inspection | Hermes `v2026.8.13` / `f80f453ae0679347e38abc917c7f94f717bf96c5` | Pass | In-scope events and CLI/Gateway registration sites are present; detailed fixture pending. |

### Test discussion and approval

- User questions and decisions: The user requested perfect Lighthouse results
  and computer-use verification after every slice; both are required gates.
- Accepted coverage gaps: A destructive/full Kanban worker run is not required
  in CI. Version-pinned post-commit call-site and process-registration evidence,
  signed live delivery, adapter tests, and reconciliation tests jointly cover
  the topology without mutating the user's real board.
- Approved at: `2026-08-14`, by the user's standing approval.

## Implementation record

### Changes

- Expanded the exact signed event allowlist from four lifecycle observations to
  17 privacy-qualified stock Hermes lifecycle, API, tool, and Kanban events.
- Added a fixed event-to-projection table and a success-only coordinator
  callback; event payload fields remain non-authoritative and are discarded.
- Added a bounded projection-only browser event broker and loopback,
  same-origin SSE endpoint with reconnect history, client limits, heartbeats,
  and an immediate connection comment.
- Added browser coalescing with native `EventSource` and streaming-fetch
  compatibility paths. Both invoke existing authoritative APIs and preserve
  the 30-second browser poll and 60-second server reconciliation fallback.
- Added a version/commit-pinned stock Hermes source validator covering CLI,
  Gateway, dispatcher, worker, hook registration, and post-commit event sites.
- Migrated the private replay table to schema version 4 so all 17 qualified
  event names satisfy the database constraint, while retaining version 3 rows.
  Replay insertion now distinguishes an exact duplicate from another integrity
  failure instead of suppressing every constraint error.
- Made local as well as remote Kanban bindings refresh project-owned delegation
  state, retained overlapping Kanban hints for a follow-up refresh, and reset
  stale browser stream cursors safely after a server restart.
- Added focused privacy, mapping, broker, HTTP, browser-contract, packaging,
  and compatibility tests and updated architecture/operator/milestone docs.

### Deviations and decisions

- The in-app computer-use browser does not expose native `EventSource`; a
  bounded streaming-fetch parser was added without changing the wire schema.
- The first Lighthouse attempt exposed that waiting for the first 15-second
  heartbeat delayed streaming-fetch first paint. The server now flushes an
  immediate comment after headers; the canonical cold audit is perfect.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python scripts/validate_hermes_native_events.py --hermes-source <stock-checkout>` | Hermes `v2026.8.13`, commit `f80f453` | 0 | 9 files / 0 failures | Exact source hashes and process/event contracts passed. |
| `node --check public/app.js` plus focused webhook/event/browser/packaging tests | macOS / Python 3.13 / Node | 0 | 69 tests / 0 failures | Post-stream-first-paint fix. |
| Post-review focused regression command | macOS / Python 3.13 / Node | 0 | 111 tests / 0 failures | Includes local Kanban sync, overlapping-refresh drain, replay schema migration, strict integrity behavior, restart cursor reset, exact artifact inventory, and `git diff --check`. |
| Lighthouse 13.4.1 desktop/provided | Cold owner-private isolated fixture | 0 | 100/100/100/100 | FCP 361ms, LCP 526ms, TBT 0ms, CLS 0.028; compact artifact retains the full-report SHA-256 and rejected attempts. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| First post-restart full suite | macOS / Python 3.13 | 1 | 1048 tests: 1 error, 4 skips | Correctly rejected: new public module was missing from verifier inventory. |
| Corrected post-review full suite | macOS / Python 3.13 | 0 | 1055 tests run, 4 skipped | State submitted to correction re-review. |
| Round-2 correction full suite | macOS / Python 3.13 | 0 | 1056 tests run, 4 skipped | Includes injected migration failure, rollback, reopen, and retry coverage. |
| `uv build` plus `scripts/verify_python_artifacts.py` | Isolated 9H worktree and temporary output | 0 | Wheel and sdist verified | Exact module/data inventories and RECORD hashes passed; private/runtime/test content excluded. |
| Pinned `detect-secrets==1.5.0` tracked-file scan | Isolated 9H worktree | 0 | 0 unreviewed findings | Compact Lighthouse hash and all changed files passed. |
| GitHub dependency and secret scan correction | PR #103 merge checkout | 0 after correction | 12 reviewed false positives | The initial job correctly found newly tracked release/source SHA-256 values that the pre-stage local scan had not seen. A narrow 12-entry baseline update covers only the pinned Hermes commit/file hashes and Lighthouse report hash; the exact CI script then passed locally. |

### Rendered or manual behavior

- Live operator-data server loaded the Home dashboard without horizontal
  overflow or browser diagnostics. A same-origin fixed signed probe returned
  200 after its receiver delivery returned 202; the projection wakeup refreshed
  the dashboard while the `Prompt Hermes` textbox retained focus. The browser
  had no lingering loading state and no console errors.
- Lighthouse operator-data diagnostics scored 76/100/100/100 because real
  machine-local Hermes reads made initial APIs take roughly five seconds; that
  observation is not the deterministic release gate. The cold isolated release
  fixture passed 100/100/100/100 after the stream-first-byte product fix.
- Post-review computer-use loaded the exact corrected build from an
  owner-private isolated fixture. A fixed same-origin probe returned 200; the
  `Prompt Hermes` textbox retained focus and remained enabled through the push
  refresh, with zero horizontal overflow, zero visible busy surfaces, and no
  browser-console diagnostics.

## Adversarial review

### Round 1

Two fresh independent read-only reviewers received the same neutral packet.
Both rejected the slice and independently identified the material issues:

- local Kanban observations refreshed only remote bindings, so browser-visible
  project task state could remain stale;
- normalized events retained lifecycle/platform fields despite the payload-free
  contract;
- the stock-source validator proved marker strings but not the exact tag,
  commit, dirty state, and file hashes;
- a browser reconnect with a cursor from a prior process could wait instead of
  receiving a projection reset;
- a Kanban hint arriving during an active refresh could be consumed without a
  guaranteed follow-up refresh; and
- the documented remote integration module inventory omitted the new broker.

Correction work removed all event-specific normalized fields, added exact
commit/tag/hash/clean-state validation, made local delegation synchronization
binding-scoped, added restart cursor recovery, retained and drained overlapping
Kanban projection hints, and corrected the inventory. During that work, direct
route testing exposed a related database constraint defect: the version 3
replay table admitted only the original four events and `INSERT OR IGNORE`
misclassified the constraint failure as a duplicate. Schema version 4 and
strict integrity handling correct that defect and preserve existing replay
rows.

### Round 2

Two fresh independent read-only reviewers received the same corrected diff and
evidence. Both rejected the slice for an interruption-unsafe schema version 4
table rebuild: `executescript()` could commit individual DDL statements before
the version receipt, leaving startup unable to retry after a mid-migration
failure. They also found canonical documentation that still described the
historical four-event, payload-bearing contract.

The migration runner now wraps each migration script and its version receipt
in one explicit immediate transaction, rolls back on every failure, and has an
injected mid-rebuild failure/reopen/retry regression test. Architecture,
changelog, configuration examples, event schema, request contract, diagnostics,
and the plan's baseline language now distinguish the historical 9A four-event
slice from the current 9H 17-event routing-envelope-only contract. The complete
suite, artifacts, secret gate, and diff check pass after correction.

### Round 3

Two final fresh independent read-only reviewers examined the complete corrected
diff. One found that rollback wording incorrectly implied a pre-schema-v4
binary downgrade was safe, the live HTTP SSE evidence was overstated, and one
rollout sentence still excluded the qualified `post_tool_call` wakeup. The
other found that the current event-to-refresh table still listed only the four
historical lifecycle events.

The recovery contract now requires retaining a schema-v4-capable binary and
disabling the target/events instead of downgrading. A real loopback HTTP SSE
test now covers wrong-origin rejection, same-origin admission, a stale process
cursor reset, projection-frame delivery, peer disconnect, and bounded client
slot release. Rollout guidance distinguishes the payload-discarding post-tool
wakeup from excluded pre-tool/LLM-content events, and the current matrix lists
all 17 exact event mappings. The 36-test final correction set, tracked-file
secret gate, and diff check pass. The workflow's three-round review cap is now
exhausted; all final findings were corrected locally with direct regression
coverage and no unresolved reviewer dissent remains.

## Documentation updates

- Roadmap: Milestone plan records 9H scope and 9I fallback-retirement boundary.
- Changelog: Native event/projection wakeups and retained fallback behavior.
- Architecture/operator docs: Projection-only SSE boundary, exact stock event
  inventory, privacy posture, and compatibility behavior.
- Project/session notes: This persistent log records the resume point.
- Documentation verification: Architecture, operator, changelog, milestone,
  package inventory, recovery guidance, exact 17-event matrix, and persistent
  evidence were checked against the final implementation.

## Publication gate

- Proposed files: Exact staged scope is the 9H implementation, tests, source
  validator, compact Lighthouse artifact, and the four named documentation
  surfaces plus this review log; no runtime/private data is included.
- Branch and base: `codex/hermes-native-event-migration` onto
  `codex/hermes-020-product-decisions`.
- Commit message: `feat: migrate Hermes native event wakeups`
- PR title: `Migrate Mentat refreshes to native Hermes events`
- PR summary: Expand to 17 payload-discarding native event wakeups, add bounded
  projection SSE, synchronize verified local Kanban state, migrate durable
  replay protection atomically, and retain polling/reconciliation fallbacks.
- Unresolved risks: Native events remain best-effort and depend on operator
  configuration; fallback polling and reconciliation intentionally remain.
- User authorization and scope: Standing publication approval is recorded as a
  process exception; exact staged scope will still be audited before action.
- Commit hash: Pending.
- Ready PR URL: Pending.

## Outcome review

- Classification: Pending.
- Acceptance criteria summary: Pending.
- Potential bugs or untested paths: Pending.
- Remaining reviewer dissent: Pending.
- Compatibility/migration/rollback concerns: Polling remains enabled until 9I.
- User decision: Pending.
- Next slice authorized: Yes, under standing approval, only after 9H passes all
  required gates and is published.
