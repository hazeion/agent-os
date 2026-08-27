# Feature Slice Review: Agent Console live queue, steering, and concurrency

Status: Published for review; CI tracked on ready PR #145
Slice: `agent-console-live-queue-steering-concurrency`
Date: `2026-08-27`
Review log: `reviews/2026-08-27-agent-console-live-queue-steering-concurrency.md`

## Slice contract

### Goal

Turn the Conversation-owned Home Console into a live workspace where compatible
Conversations can execute concurrently, active work can receive exact steering,
and ordinary follow-up requests wait durably in a bounded FIFO queue.

### In scope

- Project authoritative completed assistant text into durable Conversation
  Messages exactly once while selected-Run progress remains live and bounded.
- Keep the composer writable during an active Run. Ordinary text creates a
  durable Turn; at most eight `pending`, `blocked`, or `dispatching` Turns may
  be queue-active in one Conversation.
- Expose exact-revision edit and cancel operations for `pending` and `blocked`
  Turns, preserving FIFO ordinals and allowing gaps after cancellation.
- Claim at most the oldest pending Turn after verified successful completion.
  Stop, failure, interruption, unknown, partial results, or capacity pressure
  block continuation and require an explicit Continue operation.
- Recognize `/steer` only at the beginning after leading-whitespace
  normalization. Strip the command prefix, target only the exact compatible
  active Run, never queue it, and preserve the draft on every no-send result.
- Keep runtime continuity private and adapter-owned. A later Codex Turn reuses
  only an exactly revalidated prior App Server thread; uncertain continuity
  fails closed without exposing or inventing a browser identity.
- Add trusted private adapter capacity evidence. Unknown or invalid declarations
  remain limited to one; the Codex adapter may admit at most two only after a
  real isolated two-thread qualification passes.
- Add selected-Run live updates and one bounded global activity-hint surface
  without opening detailed streams for background Conversations.
- Preserve the existing exact Stop boundary and prove that its reconciliation
  pauses only the target Conversation's queue. A new Home Stop control is
  deferred to Slice 4.

### Out of scope

- Token-delta transcript authority or persistence of partial assistant text.
- New Home approval, clarification, Stop, Retry, Resume, archive, history, or
  restart-recovery controls planned for Slice 4.
- Provider, model, or effort selectors planned for Slice 5.
- Attachments, artifacts, link previews, rich rendering, or reasoning
  disclosures planned for Slice 6.
- Capacity claims above two, a global scheduler, timed/background capacity
  polling, queue reordering, priority routing, or automatic retry.
- Generic Node-to-Python proxying, browser-visible runtime references, raw
  provider payloads, credentials, private reasoning, or arbitrary commands.
- A schema migration unless implementation evidence proves the accepted
  schema-11 authority cannot express the slice; such evidence is a material
  deviation requiring renewed scope approval.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Completed, safe assistant text from an exact Run appears once in the owning Conversation transcript; replay, reconnect, and another Conversation's events cannot duplicate or cross-project it. | Repository idempotency/race tests, bridge schema tests, selected-stream UI tests, and real-runtime transcript smoke. | Pass — both reviewers clean; final full suite green |
| AC-2 | The selected Run exposes concise live progress and the right rail exposes bounded global hints while background Conversations open no detailed streams. | Stream framing, identity handoff, reconnect, lifecycle, and UI tests. | Pass — both reviewers clean; final full suite green |
| AC-3 | Ordinary text submitted during an active Run becomes a durable FIFO Turn; a ninth queue-active Turn fails without partial rows, and refresh/reopen preserves the exact queue. | Repository/service cap, ordering, idempotency, restart, bridge, and UI tests. | Pass — both reviewers clean; final full suite green |
| AC-4 | Pending or blocked Turns can be edited and cancelled only with exact current revisions; stale, dispatching, consumed, or cancelled mutations fail closed. | CAS, concurrent edit/cancel/claim, route-body, and UI rollback tests. | Pass — multi-blocked cancellation re-reviewed clean |
| AC-5 | Verified success claims at most one oldest pending Turn under races. Stop, failure, interruption, unknown, partial, or capacity blockage marks the head blocked and never submits automatically. | Repository transition matrix, concurrent reconciliation, fault injection, and service tests. | Pass — concurrency and Stop isolation re-reviewed clean |
| AC-6 | Explicit Continue revalidates current Agent/configuration/capacity and either reserves one first Run for the blocked head or leaves it blocked; it is not a scheduler or retry. | Repository/service/bridge/UI positive and negative tests. | Pass — exact continuity and capacity re-reviewed clean |
| AC-7 | `/steer` targets only an exact compatible active Run and never creates a Message or Turn. Unsupported, stale, late, rejected, and accepted-but-unverified outcomes preserve the exact draft and explain no-send without retry. | Parser boundary, runtime/service, exact-target, bridge, UI, and real-runtime steer tests. | Pass — exact receipt and UI semantics re-reviewed clean |
| AC-8 | Two real supported Codex Conversations execute simultaneously under a tested private limit of two; unknown adapters stay at one, all nonterminal states consume capacity, and no product-wide execution lock remains. | Capacity declaration/admission races, cross-Task accounting, code/doc inspection, and isolated real App Server qualification. | Pass — real two-Run qualification and lock probes green |
| AC-9 | Drafts, queues, Run events, Stop/steer targets, configuration snapshots, optimistic responses, and stream handoffs remain isolated by Conversation, Agent, Turn, and Run identity. | Adversarial out-of-order response, cross-target canary, tab switch, closed-tab, and concurrent UI/service tests. | Pass — delayed cross-tab and cross-Turn cases re-reviewed clean |
| AC-10 | Typing performs no network work; optimistic local paint remains within one frame, accepted dispatch is visible within 1 second, received stream activity paints within 250 ms, and loaded-tab switching is immediate in the fixed environment. Accessibility, stress, full-suite, build, and rendered gates do not regress. | Instrumented UI tests, 100-message/200-DOM stress fixture, keyboard/screen-reader checks, production build, rendered QA, and full suites. | Pass — production timing, rendered, build, and 1,573-test gates green |

### Constraints and recovery

- Safety: SQLite and the Python orchestration boundary remain authoritative.
  No SQLite/private-state lock crosses an adapter call, and no ambiguous
  mutation is retried automatically.
- Compatibility: Existing Task dispatch, legacy Console Runs, released backup
  formats, public compatibility UI, and read-only Agents/Tasks/Runs routes must
  remain valid. Adapter capacity accounting includes Task and Conversation Runs
  sharing the same private scope.
- Rendered behavior: Enter sends, Shift+Enter inserts a newline, drafts remain
  per Conversation, queue controls are compact and accessible, and activity is
  concise rather than a raw event dump.
- Rollback or recovery: Canonical Messages and Turns survive refresh/restart.
  Lost selected-stream connections recover from authoritative readback.
  Uncertain submissions, steering, or continuity remain visible and paused.
- Documentation targets: this review log, `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`,
  `ARCHITECTURE.md`, `CHANGELOG.md`, and GitHub issues #128/#135 at the relevant
  in-progress or completion checkpoints.
- Version-control strategy: branch `codex/agent-console-slice-3` from
  `24aea6687814e76bc96c7815a5c92243a3a21b55`; preserve and exclude unrelated
  worktree files. Staging, commit, push, or PR creation requires a later exact
  publication packet and cannot be pre-approved generally.

### Scope discussion and approval

- Recommendation and rationale: implement the full issue #135 boundary as one
  reviewed slice with internal repository, orchestration/runtime, bridge, and UI
  increments. Use completed runtime items as transcript authority and separate
  live progress hints from durable Messages.
- Alternatives considered: token deltas would add partial-text recovery and
  ordering authority beyond this slice; retaining a global limit of one would
  fail the product outcome; claiming an undocumented provider maximum would be
  unsafe; proving concurrency only across unrelated adapters would be weaker
  than qualifying two real Codex Conversations.
- User decisions: approved the recommended contract and all routine future
  local work. General advance approval is recorded for implementation decisions
  but not treated as an unseen publication authorization.
- Approved at: 2026-08-27 conversation.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1, AC-2 | Codex message items have no safe content projection and Home has no live selected stream. | Event normalization, idempotent Message projection, strict bridge schemas, SSE handoff/reconnect, and real response smoke. | Authoritative transcript and bounded live progress remain exact and isolated. | Token deltas are intentionally excluded. |
| AC-3, AC-4 | Active Send is rejected; queue mutation capabilities do not exist. | Repository transaction/race tests, exact Node/Python route tests, optimistic UI rollback, refresh/reopen, and cap stress. | FIFO authority, CAS safety, durability, and eight-turn enforcement. | Reordering is deferred. |
| AC-5, AC-6 | Reconciliation does not claim or block a queue head. | Full terminal-state matrix, simultaneous reconciler races, adapter faults, capacity changes, and explicit Continue tests. | Only verified success auto-advances once; every unsafe state pauses. | No background scheduler is introduced. |
| AC-7 | Runtime adapters can steer, but the Conversation composer has no command path. | Exact parser table, active identity/capability races, no-row assertions, draft-preservation UI tests, and real Codex steer smoke. | Steering never silently becomes durable queued work or crosses targets. | Accepted steering has no provider read receipt beyond the fixed adapter contract. |
| AC-8, AC-9 | Capacity is hard-coded to conservative binding limit one. | Typed adapter declaration validation, admission accounting/races, two real Codex threads, cross-target canaries, and private-field scans. | Concurrent work is bounded by trusted adapter scope rather than a product lock. | Mentat claims only a tested ceiling of two, not provider-wide capacity. |
| AC-10 | Existing Slice 2 UI disables active composing and has no Slice 3 stress/performance coverage. | Instrumented component tests, production rendered checks at desktop/mobile, accessibility inspection, long transcript/rapid-tab stress, web build, and full suites. | The live UI remains responsive, accessible, and compatible. | Host load can affect wall-clock smoke results; fixed fixtures provide the repeatable gate. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python -m unittest ...` | macOS host shell | Not run | The repository guide spelling is unavailable because this host has no `python` executable. |
| `python3 -m unittest tests.test_conversation_repository tests.test_run_repository tests.test_orchestration_service tests.test_codex_runtime tests.test_mentat_local_bridge -v` | macOS, Python 3 | Pass | 182 tests; 181 pass, 1 Windows-only skip. |
| `npm --prefix web run check` | macOS, repository Node toolchain | Pass | lint, TypeScript, and 63/63 Node tests passed. |
| `git diff --check` | focused branch with preserved pre-existing edits | Pass | No whitespace errors. |

### Test discussion and approval

- User questions and decisions: user gave explicit standing approval for the
  disclosed strategy and future routine local work after approving the slice
  contract.
- Accepted coverage gaps: no token deltas, no new Home Stop UI, and no capacity
  claim above the isolated tested limit of two.
- Approved at: 2026-08-27 conversation.

## Implementation record

### Changes

- Added a transactional Conversation queue with an eight-item active cap,
  immutable FIFO ordinals, exact Turn-and-Message revision binding, safe edit,
  cancel, block, Continue, and one-head claim transitions.
- Replaced the product-wide execution limit with adapter-declared private
  capacity scopes. Conservative and malformed declarations remain at one;
  the qualified local Codex binding declares a maximum of two, and Task and
  Conversation Runs share the same accounting boundary.
- Added private continuation references and exact completed-thread reuse for
  Codex without exposing provider thread or turn identities to Node or the
  browser.
- Projected one bounded completed assistant response into the owning
  Conversation exactly once and kept selected-Run progress ephemeral,
  bounded, and separate from transcript authority.
- Added exact `/steer`, queue edit/cancel/Continue, targeted Run refresh, and
  selected-only event-stream routes across the Python bridge, Node bridge, and
  public same-origin API boundary, including cross-target canaries.
- Kept the active composer writable, added per-Conversation drafts, queue and
  recovery controls, explicit non-queued steering language, bounded activity
  hints, cached tab switching, cancelled-message treatment, and focus handoff
  into the queued-turn editor.
- Added repository, race, fault-injection, adapter, bridge, route, component,
  performance, stress, accessibility, and real-runtime qualification coverage.
- Updated `AGENTS.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, the roadmap, and this
  persistent review log. No schema migration was required.

### Deviations and decisions

- The accepted no-schema-migration preference held: schema 11 already had the
  required authoritative Conversation and Run fields.
- Live progress is held as one selected `{runId, summary}` value rather than a
  map, making the browser memory bound explicit.
- Rendered QA found that opening a queue edit did not move keyboard focus. The
  editor now receives focus and the interaction suite asserts that behavior.
- Round 1 review found that a queue action could restore focus before React had
  committed the replacement control and that a delayed response from one tab
  could interfere with another tab's editor. Focus requests now apply only
  after the matching Conversation commit, and editor state is keyed by
  Conversation.
- Round 2 review tightened that focus boundary within one Conversation. Queue
  editor choices now carry a monotonic per-Conversation revision; delayed edit,
  cancel, and Continue responses can neither close nor focus a newer Turn
  editor, and the eventual focus request rechecks the same revision.
- Round 2 also found two backend edge cases. Cancellation now distinguishes the
  actual blocked FIFO head from a blocked non-head and preserves an already
  blocked successor idempotently. Task capability discovery joins capacity
  discovery outside the private lock, followed by exact Task, Agent, binding,
  runtime, and digest revalidation before reservation.
- Round 1 review also found that live event bursts could fan out canonical reads
  and that stale refreshes could overwrite newer queue/Run state or discard
  paginated history. The selected detail reader now permits one in-flight read
  plus one trailing read, merges monotonically, and retains at most 200 rows.
- A combined concurrency run exposed a SQLite race between an exact Run lease
  writer and an unlocked canonical Agent-registry read. The short registry
  snapshot is now serialized by the private-state lock; runtime status, event,
  capacity, and submission adapter calls remain outside that lock. The original
  race passes ten consecutive repetitions.
- AC-10 is now backed by a production-only repeatable gate rather than one-off
  component timings. The gate starts the standalone build and headless Chromium
  with a deterministic two-Conversation, 100-to-200-message fixture and emits
  seven-sample raw values and medians.
- The first repository-wide run used the user's modified tracked seed files and
  correctly failed their private-mode and fixture-contract checks. The complete
  suite was therefore repeated from a clean temporary worktree with only this
  slice overlaid; that authoritative run passed. The temporary worktree was
  removed afterward.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `.venv/bin/python -m unittest tests.test_agent_runtime tests.test_codex_runtime tests.test_conversation_repository tests.test_mentat_local_bridge tests.test_orchestration_service -v` | macOS host, focused branch | Exit 0 | 161 pass, 1 Windows-only skip | Pre-Round2 reference covering identity projection, capacity, FIFO races, reconciliation, steering, exact continuity, bridge projections, Stop isolation, and cross-target canaries. |
| `.venv/bin/python -m unittest tests.test_run_repository -v` | macOS host, focused branch | Exit 0 | 58 pass | Revalidates schema, retention, idempotency, leases, event authority, restart recovery, and Task/Conversation shared Run invariants. |
| `.venv/bin/python -m unittest tests.test_orchestration_service tests.test_run_repository -v` | macOS host, focused branch | Exit 0 | 128 pass | Includes Round2 capability-lock and multi-blocked cancellation regressions. |
| Ten consecutive runs of `test_competing_reconcilers_claim_one_pending_head_once` | macOS host, focused branch | Exit 0 | 10/10 pass | Reproduces and closes the Agent-registry snapshot/lease-writer race without moving adapter I/O under the lock. |
| `npm run check` | `web/`, repository Node toolchain | Exit 0 | 88 pass | ESLint and TypeScript passed; includes 23 Home Console interaction tests. |
| Focused Home Console interaction run | `web/`, Node test runner | Exit 0 | 23 pass | Adds 100-event coalescing, stale-response rejection, 200-row pagination, two-Run handoff/reconnect/drop, delayed cross-tab and same-Conversation cross-Turn mutation isolation, unique action names, and focus restoration. |
| `npm run performance:agent-console` | Next.js standalone production build; headless Chromium 152; macOS 15.7.7; Intel i7-7820HQ; 16 GiB; Node 24.19; 1440x900@1x; two Conversations; 100 initial/200 retained Messages; seven samples | Exit 0 | All thresholds pass | Final medians: optimistic paint 3.8 ms, accepted visibility 10.5 ms, stream paint 2.7 ms, cached-tab switch 2.3 ms. All seven typing network deltas were zero; raw samples were emitted. |
| Isolated real Codex App Server qualification | temporary owner-private data/workspace | `QUALIFICATION_PASSED` | 2 completed Runs | `readiness=ready capacity=2 overlap=verified steer=verified terminal=completed,completed isolation=verified`. |
| `python3 -m py_compile ...` | changed Python modules | Exit 0 | All compiled | No syntax failures. |
| `.venv/bin/python -m unittest tests.test_agent_runtime_architecture tests.test_ci_workflow tests.test_beta_contract tests.test_data_layout_contract tests.test_hermes_020_product_decisions -v` | primary branch after final roadmap/review-log edits | Exit 0 | 41 pass | Documentation, architecture, roadmap, CI, and data-boundary contracts remain green after final map reconciliation. |
| `git diff --check` | focused branch with unrelated files excluded | Exit 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| Pre-Round1 `python3 -m unittest discover -s tests` | clean temporary worktree at base `24aea66`, then-current Slice 3 Python changes overlaid, tracked JSON owner-only | Exit 0 | 1,558 pass, 5 skip | Historical reference only; a final clean-root run is required after all Round 1 fixes. |
| `npm run build` | `web/`, Next.js 16.3.2 production build | Exit 0 | Build pass | All static pages and fixed queue/steer/Run event routes compiled. |
| Final `.venv/bin/python -m unittest discover -s tests` | clean temporary worktree at base `24aea66` with the final reviewed Slice 3 files overlaid; unrelated user files excluded; tracked JSON owner-only | Exit 0 | 1,568 pass, 5 skip; 1,573 total | Authoritative final repository-wide gate after both adversarial review rounds; 409.068 seconds. Temporary worktree removed afterward. |
| Initial `python3 -m unittest discover -s tests` | user's dirty primary worktree | Exit 1 | 1,512 pass, 15 fail, 31 error, 5 skip | Failures were dominated by deliberately preserved modified seed content and broad local fixture permissions; one timing assertion also missed its rendezvous under load. The clean-worktree rerun above is authoritative and green. |

### Rendered or manual behavior

- Final production build inspected through the in-app Browser at desktop
  `1280x720` and mobile `390x844` viewports using an isolated authoritative data
  root; the earlier pre-review pass also covered `1440x900`.
- Verified two simultaneous Conversation tabs, selected-only live status,
  ordinary active Send presented as Queue, pending and blocked queue states,
  compact edit/cancel/Continue controls, non-queued `/steer` language, and
  bounded right-rail activity.
- Verified active `/steer` draft preservation across tab switches and an empty
  draft in the other Conversation, proving the visible draft isolation path.
- Verified responsive wrapping without horizontal overflow, usable mobile
  composer/recovery controls, semantic tabs/tabpanel/regions/status surfaces,
  and focus in the rebuilt queued-turn editor.
- Verified the final `/steer` composer still says **Send** and “Steering is
  never queued,” with no browser warnings or errors. The isolated preview tab,
  processes, and temporary data root were removed afterward.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: uncommitted focused Slice 3 working-tree diff from base
  `24aea6687814e76bc96c7815a5c92243a3a21b55`; unrelated seed/media/tooling
  files explicitly excluded.
- Verification evidence: pre-review focused Python/web suites, clean-root full
  suite, production build, rendered desktop/mobile QA, and isolated real Codex
  two-Run/steer qualification.
- Rendered artifacts: production desktop `1440x900` and mobile `390x844`
  inspection through the in-app Browser on an isolated root.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| S-1 | Blocking | Yes | Hermes could accept a response from a mismatched second status snapshot after validating only the first snapshot. | Yes | Bind both snapshots and every retained event to the exact Mentat Run, Agent, and Task before projection. |
| S-2 | Blocking | Yes | Codex Continue could start a fresh thread when exact prior continuity was absent. | Yes | Require the immediately preceding executed Turn's verified completed thread; missing or unsafe continuity remains blocked. |
| S-3 | Blocking | Yes | Cancelling a blocked FIFO head could leave a pending successor stranded without an explicit Continue surface. | Yes | Atomically transfer the blocked pause state to the next pending head. |
| S-4 | Blocking | Yes | Any adapter could declare capacity above two even though only the fixed Codex path had real qualification evidence. | Yes | Accept a higher declaration only for the fixed Codex `default` binding and exact qualified scope, capped at two; collapse every other declaration to one. |
| S-5 | Blocking | Yes | Task capacity discovery called adapter code while the private-state lock was held. | Yes | Use a two-phase snapshot/declaration/revalidation flow with adapter discovery outside the lock. |
| S-6 | Blocking | Yes | A delayed queue response from Conversation A could close or focus an editor opened later in Conversation B. | Yes | Key editing and focus state by Conversation and apply focus only after a matching selected-Conversation commit. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| P-1 | Blocking | Yes | The selected-Run SSE GET performs reconciliation but lacked the same-origin request boundary expected for a state-changing read. | Yes | Enforce the exact host/origin/fetch-site boundary before streaming and reject all query parameters. |
| P-2 | Blocking | Yes | A live event burst could fan out one canonical read per frame; out-of-order reads could overwrite newer state and discard loaded pagination. | Yes | Coalesce to one in-flight plus one trailing read, merge by monotonic revisions/timestamps, and retain a bounded 200-message window. |
| P-3 | Blocking | Yes | A dedicated **Steer** button contradicted the accepted `/steer`-through-composer interaction. | Yes | Keep the ordinary action labeled **Send** for `/steer`; explain that it is never queued. |
| P-4 | Blocking | Yes | Temporary steering unavailability was surfaced as permanent unsupported behavior. | Yes | Preserve distinct `unavailable` and `unsupported` bridge/UI outcomes and retry guidance. |
| P-5 | Blocking | Yes | Repeated queue controls had duplicate accessible names and focus was not reliably restored after edit/cancel/Continue. | Yes | Include immutable FIFO ordinals in names and use commit-aware successor/editor/composer focus restoration. |
| P-6 | Blocking | Yes | AC-10 was marked passed without a named production environment, repeatable median measurements, a 200-row fixture, or burst/reconnect/handoff evidence. | Yes | Add the standalone-Chromium seven-sample gate and explicit 100-event, 200-row, reconnect, and two-Run handoff tests. |

### Round 2 safety follow-up findings

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| S-7 | Blocking | Yes | Cancellation handoff assumed every blocked target was the FIFO head and every successor was pending, so cancelling either end of a multi-blocked queue rolled back with `conversation.queue_state_invalid`. | Yes | Detect the pre-cancel head; do no handoff for a non-head, transition a pending successor, and preserve an already-blocked successor idempotently. |
| S-8 | Blocking | Yes | Task admission still read live runtime capabilities twice while holding the private-state lock; Codex capability discovery can perform App Server I/O. | Yes | Snapshot capabilities outside the lock with capacity, then accept the snapshot only after exact Task/Agent/binding/runtime revalidation. |
| S-9 | Blocking | Yes | A delayed edit, cancel, or Continue response in one Conversation could retain a newer Turn editor but still steal its keyboard focus. | Yes | Bind editor and focus commits to a monotonic per-Conversation editor revision checked again at response and focus-application time. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Runtime/Conversation identity validation | Corroborated by S-1 and the broader AC-9 isolation concern | Clean | All Hermes readback snapshots/events now require the exact Run, Agent, and Task before response/usage projection. | Added a cross-project second-snapshot canary. |
| Codex continuity ambiguity | Unique S-2 | Clean | Continue selects only the immediately preceding executed Turn and requires a live, completed, nonpartial Codex Run with its exact private reference. A completed submission missing that reference becomes unknown and pauses. | Added failed-prior and missing-reference service tests plus adapter `thread/read` validation. |
| FIFO recovery after cancellation | S-3 refined by S-7 | Clean | The pre-cancel FIFO head is detected exactly. A blocked non-head retires without touching the head; a pending successor inherits the reason; an already-blocked successor is preserved without a revision change. | Added head-plus-pending, head-plus-blocked, and non-head-blocked service regressions. |
| Capacity trust and lock ordering | S-4/S-5 refined by S-8 | Clean | Only qualified fixed Codex evidence can raise the limit to two; both live capability and capacity discovery occur between two short exact snapshots, outside the private lock. | Added unqualified-adapter plus blocking capability and capacity lock probes. |
| Selected stream request/read discipline | Corroborated P-1/P-2 | Clean | Same-origin/query boundary added; 100 events now produce one in-flight plus one trailing read, with stale-revision rejection and 200-row retention. | Added route and adversarial component tests. |
| Steering interaction and failure semantics | Corroborated P-3/P-4 | Clean | Removed the dedicated label and split temporary unavailability from unsupported capability. | Updated bridge mappings, UI copy, and route/component tests. |
| Queue accessibility and tab/Turn isolation | S-6/P-5 refined by S-9 | Clean | Ordinal-specific names, Conversation-keyed editor state, and monotonic editor revisions prevent delayed cross-tab or same-Conversation cross-Turn closure and focus theft. Focus application rechecks the exact editor revision. | Added multi-row keyboard plus delayed cross-tab and delayed edit/cancel/Continue A-to-B tests. |
| AC-10 evidence gap | Unique P-6 | Clean | Production standalone-Chromium gate now emits seven raw samples/medians in a named fixed environment and checks all thresholds with 200 retained rows. | Added `npm run performance:agent-console`; final production gate passes. |
| Reconciliation registry-read race discovered during reverification | New local finding after Round 1 | Clean | A short canonical registry snapshot now shares the private lock with lease writers; all adapter I/O stays outside. | Existing competing-reconciler test passes ten consecutive repetitions. |

### Round 2 dispositions

- Correctness and safety reviewer: **CLEAN** after independently verifying the
  Hermes second snapshot, exact Codex predecessor continuity, all three blocked
  cancellation cases, Codex-only capacity qualification, adapter lock ordering,
  reconciliation locking, delayed cross-tab/cross-Turn focus, exact steer
  receipts, and Stop isolation. Independent evidence: 123 pass, one
  Windows-only skip; 23/23 Home interactions; lint, TypeScript, and diff check
  pass; extra read-only lock/cancellation probes pass.
- Compatibility and product reviewer: **CLEAN** after independently verifying
  the mutating SSE request boundary, coalesced bounded refreshes, ordinary Send
  steering semantics, unavailable-versus-unsupported projection, queue
  accessibility/focus behavior, and the production performance gate.
  Independent evidence: web 85/85 at that review checkpoint, focused route/UI
  27/27, bridge failure mapping pass, and production thresholds pass.
- Remaining blocking findings: none. Reviewer dissent: none.

### Reverification

- Focused tests: web 88/88 pass; production performance gate passes;
  orchestration plus Run repository passes 128/128, including all Round 2
  regression probes.
- Full suite: final clean-root run passes 1,573/1,573 with five skips and no
  failures.
- Next review round or gate result: both original reviewers returned CLEAN;
  exact publication approval is the only remaining gate.

## Documentation updates

- Roadmap: Console Slice 3 remains In progress while its implementation,
  verification, and reviews are recorded complete and publication is pending.
- Changelog: added the Slice 3 queue, steering, concurrency, live-progress, and
  safety outcome.
- Architecture/operator docs: recorded FIFO authority, capacity scope,
  continuation, selected-stream, steering, and Stop isolation contracts in
  `ARCHITECTURE.md` and `AGENTS.md`.
- Project/session notes: GitHub issue #135 remains assigned and its existing
  implementation checkpoint now records the final clean evidence and both
  CLEAN reviewer dispositions; #128 remains the parent map until publication
  and merge.
- Documentation verification: both reviewers are clean, `git diff --check`
  passes, the production build compiles every documented fixed route, and the
  final repository-wide suite passes.

## Publication gate

- Proposed files: the exact Slice 3 implementation, tests, routes, performance
  gate, review log, roadmap, changelog, architecture/operator docs, and the
  carried-forward Slice 2 close-out log listed in the publication packet;
  unrelated seed, mockup, PDF, video, lockfile, and local npm changes excluded.
- Branch and base: `codex/agent-console-slice-3` into `main`, currently
  `24aea6687814e76bc96c7815a5c92243a3a21b55`.
- Commit message: `Agent Console Slice 3: live queue, steering, and concurrency`
- PR title: `Agent Console Slice 3: live queue, steering, and concurrency`
- PR summary: add authoritative live transcript and selected progress; add the
  bounded durable FIFO queue with exact edit/cancel/Continue and steering;
  qualify adapter-scoped concurrency and harden identity, continuity, request,
  lock, accessibility, and performance boundaries.
- PR mode: ready for review, never draft.
- Unresolved risks: no known blocking risk. Accepted limitations remain the
  slice's explicit exclusions: no token-delta authority, Home Stop control,
  capacity above two, scheduler/retry behavior, rich attachments, or Slice 4+
  recovery UI.
- User authorization and scope: user approved the exact 43-file
  stage/commit/push/ready-PR packet in the current conversation on 2026-08-27.
- Implementation commit: `17b93561bf5fb43449b00dcdbac77173d14d8935`.
- Ready PR URL: <https://github.com/hazeion/agent-os/pull/145>.

## Outcome review

- Classification: Published for review; implementation outcome is successful
  against all ten criteria and GitHub checks are tracked on ready PR #145.
- Acceptance criteria summary: AC-1 through AC-10 pass focused, production,
  rendered, real-runtime, independent-review, and final full-suite gates.
- Potential bugs or untested paths: no material missing-test gap identified by
  either reviewer; the explicit out-of-scope Slice 4+ controls remain deferred.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: no schema migration; existing
  backup formats, Task dispatch, legacy Console, and explicit legacy-UI
  rollback remain covered. Unknown/partial admission and continuity fail closed
  and do not retry automatically.
- User decision: exact commit/push/ready-PR publication approved and completed;
  outcome acceptance remains after CI.
- Next slice authorized: No
