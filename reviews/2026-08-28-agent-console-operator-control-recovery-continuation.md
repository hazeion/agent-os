# Feature Slice Review: Agent Console operator control, recovery, and durable continuation

Status: Ready for publication
Slice: `agent-console-operator-control-recovery-continuation`
Date: `2026-08-28`
Review log: `reviews/2026-08-28-agent-console-operator-control-recovery-continuation.md`

## Slice contract

### Goal

Complete the first usable Agent Console milestone. An operator can control an
active Run, answer exact approval or clarification requests, recover from unsafe
terminal states, reopen durable work, and archive or restore a Conversation
without losing evidence or confusing presentation state with execution state.

### In scope

- Integrate the existing exact Stop preview and confirmation capability into
  the selected Conversation without tying Stop to tab close or archive.
- Project one exact pending approval or clarification request into a dedicated
  inline card and the bounded Agent activity rail. Ordinary composer text never
  answers it.
- Add explicit Retry for a terminal Conversation Run. Retry creates a new Run
  for the same Turn, preserves the prior Run and events, captures a fresh
  configuration snapshot, and is idempotent under an exact action key.
- Add the fixed capability-gated Resume contract. No production adapter may
  advertise Resume until it can revalidate exact private continuity; adapters
  without that proof show no Resume action.
- Reconcile nonterminal work before the browser claims it is live after startup,
  refresh, or reopen. Cached transcript content may render while controls stay
  unavailable.
- Add recent Conversation history, presentation-only tab close and reopen, and
  exact-revision reversible archive and restore. Delete remains unavailable.
- Keep failure, stopped, interrupted, unknown, partial, capacity-blocked, and
  reconciliation-unavailable states distinct and actionable.

### Out of scope

- Conversation deletion or pending-turn reordering.
- Provider, model, effort, or Agent rebinding in an existing Conversation.
- Markdown, code highlighting, reasoning summaries, rich links, attachments,
  Context Packs, images, artifacts, project context, or planning suggestions.
- Automatic retry, cross-Conversation scheduling, generic proxying, arbitrary
  runtime methods, or browser-visible runtime references.
- Advertising Resume for Hermes, Codex, Vercel, or another production adapter
  without an adapter-specific continuity proof in this slice.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Approval and clarification appear as dedicated exact-Run cards and right-rail attention items. Composer Send cannot answer or dismiss them. | Repository/bridge schemas, UI interaction tests, browser exercise. | Pass |
| AC-2 | Stop uses the existing state-bound preview and confirmation, reconciles the exact Run, pauses its queue, and does not close or archive the Conversation. | Stop control, route, queue-isolation, stale-confirmation, and browser tests. | Pass |
| AC-3 | Retry creates one new Run for the same Turn with a fresh immutable snapshot and `retry_of_run_id`, keeps old evidence, and replays one exact action key without a second adapter call. | Schema/repository/service race, retention, restart, and bridge tests. | Pass |
| AC-4 | Resume appears and executes only for a fixed advertised capability with exact private continuity. Unsupported and ambiguous outcomes fail closed and do not retry. | Fake-adapter protocol tests, negative production-adapter tests, UI absence tests. | Pass |
| AC-5 | Every nonterminal startup state is classified or reconciled before the browser asserts live state. Stale local `running` evidence never enables controls by itself. | Full restart state matrix, delayed readback, dropped SSE, refresh/reopen tests. | Pass |
| AC-6 | Closing a tab changes presentation only. Recent history can reopen it. Archive is exact-revision and reversible, remains durable across refresh, and never stops active work. | Repository CAS/race tests, client state tests, browser desktop/mobile checks. | Pass |
| AC-7 | Failed, stopped, interrupted, unknown, partial, blocked, and unavailable outcomes stay distinct. No unsafe action retries automatically. | Terminal matrix, fault injection, public projection, UI copy, and canary tests. | Pass |
| AC-8 | Stop, response, retry/resume, archive, drafts, tabs, pending cards, and activity remain isolated by Conversation, Turn, Run, Agent, and revision under delayed cross-tab responses. | Cross-target service/route/UI races and adversarial canaries. | Pass |
| AC-9 | The first usable Console passes focused and full suites, production build, accessibility, reduced-motion, responsive, performance, and real browser use gates without UI or logic defects. | Repeatable web gate, build, browser use test, screenshots, and full matrix. | Pass |
| AC-10 | Browser projections remain bounded and omit credentials, paths, adapter references, private continuity, raw payloads, and runtime methods. Later-slice behavior is not pulled forward. | Strict schema rejection, secret/path scans, architecture review, and diff inspection. | Pass |

### Constraints and recovery

- Safety: SQLite and Python remain authoritative. No SQLite or private-state
  lock crosses runtime I/O. An ambiguous external action is never retried.
- Compatibility: preserve Task dispatch, legacy Console, released backup
  formats, schema-13 restores, the explicit legacy UI, and runtime coexistence.
- Rendered behavior: compact controls, visible focus, status text beyond color,
  no page overflow, restrained live announcements, and usable narrow layouts.
- Rollback or recovery: schema changes are forward-only and require a validated
  pre-migration backup for lossless rollback. Archive and tab close are
  reversible; old Run evidence remains under normal retention.
- Documentation targets: this log, `ARCHITECTURE.md`, `AGENTS.md` when a durable
  boundary changes, `CHANGELOG.md`, the roadmap, issue #136, and Wayfinder #128.
- Version-control strategy: branch `codex/agent-console-slice-4` from merged
  Slice 3 close-out commit `93198ad`; ready PR into `main`.

### Scope discussion and approval

- Recommendation and rationale: implement issue #136 as one coherent recovery
  slice because Stop, pending actions, retry/resume, startup truth, and durable
  history share exact Run and Conversation identity. Splitting the UI from its
  authority would ship misleading controls.
- Alternatives considered: UI-only wiring would not support durable Retry or
  restart truth; advertising a production Resume without continuity evidence
  would violate the runtime boundary; pulling configuration or rich rendering
  forward would broaden the slice without helping recovery.
- User decisions: the user approved all remaining Wayfinder slices, scopes,
  commits, pushes, PRs, and merges in advance. This explicitly replaces the
  review skill's repeated approval pauses. Tests, browser use, two independent
  reviews, ready PRs, CI, and honest outcome records remain mandatory.
- Approved at: 2026-08-28 conversation.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Exact backend response controls exist, but Conversation detail and Home expose no pending-action card. | Pending-action projection, strict bridge/BFF schemas, stale request races, card/rail UI tests. | Ordinary Send stays separate and exact response authority survives navigation. | Real providers may not reliably emit a pending action on demand; hostile fixtures cover the UI contract. |
| AC-2 | Stop exists on Runs routes but Home has no Stop workflow. | Existing Stop suite plus Home preview/confirm, stale token, queue pause, and cross-tab tests. | The Console reuses rather than weakens the fixed Stop boundary. | Browser smoke may use an isolated supported runtime rather than every adapter. |
| AC-3, AC-4 | Schema fields exist, but one submission receipt per Turn prevents later attempts and no retry/resume service exists. | Forward migration, multiple-attempt repository invariants, idempotency races, retention, fake resumable adapter, negative adapter matrix. | A Turn can own multiple immutable Runs without losing old evidence or duplicating calls. | No production Resume capability will be claimed without separate adapter proof. |
| AC-5 | Startup classifies crash states, but initial Conversation reads can still project stale nonterminal status before exact readback. | Every-state restart matrix, reconciliation-pending projection, action gating, dropped-stream recovery, background-tab reopen. | Browser liveness claims come from current evidence. | Runtime outages remain visibly unavailable rather than repaired automatically. |
| AC-6 | Archive columns exist, but no CAS mutation or tab/history interaction exists. | Repository conflicts, active-Run archive, pagination, local tab state, keyboard/focus, refresh/reopen tests. | Presentation changes cannot mutate execution and archive remains reversible. | Delete stays deferred. |
| AC-7 to AC-10 | Slice 3 has basic terminal labels and isolation but no complete control/recovery surface. | Terminal/fault matrix, cross-target canaries, 200-message fixture, production performance/build, desktop/mobile browser use, full Python/web suites. | The milestone works as a whole without widening private or later-slice boundaries. | Live approval generation remains provider-dependent. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository and issue audit | merged `93198ad`, macOS | Pass | Slice 3 is closed; issue #136 is open, unblocked, and claimed. |
| Existing focused tests and source inspection | Python/Next.js | Gap confirmed | Stop/response backends exist; Home lacks Stop/cards/history/archive/retry/resume and initial read reconciliation. |

### Test discussion and approval

- User questions and decisions: standing approval covers this test strategy and
  the full issue #136 scope without another pause.
- Accepted coverage gaps: no production adapter claims Resume; provider-driven
  pending actions may use hostile deterministic fixtures for rendered QA.
- Approved at: 2026-08-28 conversation.

## Implementation record

### Changes

- Added exact-revision archive and restore without touching Runs, Messages, or
  queue authority. Home tabs can close and reopen through bounded recent
  history without an execution mutation.
- Added selected-Run reconciliation gating. Stop, steering, approval, and
  clarification controls appear only after the exact selected stream performs
  authoritative readback.
- Integrated the existing Stop and pending-response preview-confirm boundaries
  into compact Home controls. Ordinary composer text remains a queued Turn and
  cannot answer a pending action.
- Advanced the private database to schema 14. One Turn may retain up to seven
  explicit later Retry or Resume attempts, each with its own immutable Run,
  predecessor link, idempotency receipt, restart classification, and bounded
  retained result.
- Added fixed Retry and Resume bridge/BFF capabilities. Retry uses the current
  Agent configuration; Resume also requires `run.resume`, an exact private
  source reference, a live adapter capability, and a fixed adapter method. No
  production adapter advertises Resume.

### Deviations and decisions

- The implementation does not add a production Resume claim. A fake adapter
  proves the runtime-neutral contract, while all shipped adapters remain
  correctly absent from the UI.
- Initial nonterminal Messages remain readable while Run controls say
  `Reconciling`. Ordinary active-Run Send may still create a durable queued Turn
  because that mutation does not target or retry the uncertain runtime Run.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `.venv/bin/python -m unittest tests.test_agent_runtime tests.test_orchestration_service tests.test_run_repository tests.test_conversation_repository tests.test_schema12_forward_migration tests.test_run_stop_control tests.test_run_response_control -q` | macOS, Python 3.11 | Exit 0 | 212 pass | Core schema, retry/resume, restart, archive, Stop, response, and repository gate. |
| `.venv/bin/python -m unittest tests.test_mentat_local_bridge -q` | macOS host loopback | Exit 0 | 42 pass | Socket-bound private bridge gate; rerun outside sandbox because ephemeral bind is prohibited there. |
| `npm run check` | Next.js web, Node 24 toolchain | Exit 0 | 105 pass | Lint, TypeScript, bridge/BFF, Home interaction, accessibility, isolation, and duplicate-replay liveness gates. |
| Private backup/restore compatibility group | macOS, Python 3.11 | One fixture failure corrected | 143 pass before correction | Schema-5 downgrade fixture now drops the new attempt table before Conversation tables. Exact corrected test passes. |
| `node scripts/run-next.mjs build --webpack`; `node scripts/prepare-standalone.mjs` | Next.js 16.3.2 production | Exit 0 | Build pass | Every fixed archive, restore, retry, resume, Stop, response, and event route compiled. Standard Turbopack remains a required CI gate because its local worker port is blocked in the temporary worktree environment. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -q` | macOS host, Python 3.13 | Exit 0 | 1,646 pass, 5 platform skips | Complete repository suite in 565.977 seconds; rerun on the host because loopback tests cannot bind in the sandbox. |

### Rendered or manual behavior

- Started the production supervisor against an isolated schema-14 data root and
  used the in-app browser at the default desktop viewport and `390x844` mobile.
- Verified real Codex readiness and a real durable Conversation response.
- Started a longer real Codex Run, observed `Reconciling` before readback and a
  verified **Stop** afterward. The first Stop confirmation correctly went stale
  during a Run revision change; a fresh preview-confirm stopped the exact Run
  with no automatic retry and left the Conversation open.
- Retried the stopped Turn. Mentat created a distinct Run and retained the prior
  transcript and recovery evidence. The right rail returned to Working.
- Archived the active Retry without stopping it, closed its tab, confirmed the
  activity rail still showed Working, reopened it from Recent Conversations,
  restored it, and stopped the Retry before cleanup.
- Restarted the production supervisor over the same isolated root. Conversations,
  Messages, stopped recovery state, tabs from canonical history, and the
  schema-14 database reopened without stale live controls.
- Desktop and mobile had no horizontal overflow. Mobile recovery actions were
  initially measured at 36.5 px; CSS now gives new mobile actions a 44 px
  minimum. Rebuild and browser recheck measured exactly 44 px and a 390 px
  document width at a 390 px viewport.
- Browser console warnings/errors: zero.
- Final post-review browser recheck used the rebuilt production server at
  `390x844`. The tab-close target measured exactly `44x44`, document and viewport
  widths both measured `390`, and closing the selected tab moved focus to its
  successor tab.

## Adversarial review

### Round 1

- Safety reviewer verdict: blocked. It found released schema-13 component
  validators missing from the format-4 restore path, Retry exposed for active
  partial Runs, and Resume exposed from the Agent declaration without exact
  live adapter and continuity evidence.
- Product/compatibility reviewer verdict: blocked. It independently confirmed
  the Retry and Resume defects, then found archived completion rollback,
  unverified activity claiming Working after restart, partial recovery copy
  hiding the terminal outcome, unloaded activity navigation omitting its tab,
  same-Run recovery responses crossing the Node boundary, and tab-close focus
  and mobile target regressions.
- Corrections: all schema-13 repository validators now accept the released
  fingerprint and a full format-4 restore test covers it. Archived completion
  commits and leaves queued work pending. Retry is terminal-only. Resume stays
  hidden in the shipped UI. Activity projects current-process readback receipts
  and treats absent evidence as Checking/Reconciliation. Recovery headings preserve both
  terminal status and partial evidence. Activity navigation reopens a tab.
  Both Node validation layers reject `run.id === source_run_id`. Tab close moves
  focus to its successor or Recent Conversations, and its mobile target is at
  least 44 px.
- Focused remediation evidence: six backend recovery/restore/activity tests
  pass; the complete web check passes lint, typecheck, and 104 tests.

### Round 2

- Both reviewers confirmed the original schema, Retry, Resume, recovery copy,
  activity navigation, response-boundary, and focus defects were corrected,
  but blocked on three follow-ups: the archived pending head was not Continue-
  eligible, the mobile close target was only 24 by 44 px, and synchronous
  activity polling could outlive the Node deadline while holding the global
  continuation gate.
- Corrections: archived completion now converts the oldest pending head to an
  explicit blocked partial state; restore plus exact Continue is covered. The
  mobile close target is 44 by 44 px with matching tab padding. Activity reads
  no longer perform runtime I/O. A bounded process-local receipt set is cleared
  at startup and populated only by startup reconciliation, accepted submission,
  or selected-Run readback; absent receipts project Checking/Reconciliation.
  The set is pruned to active projected Runs. A bridge-level slow-runtime test
  proves activity returns within one second without entering the adapter.

### Round 3

- Both reviewers confirmed the archive, mobile-target, and activity-I/O fixes,
  then found one replay gap: a durable duplicate Send, Continue, Retry, or Resume
  could recreate server and browser liveness receipts without adapter readback.
- Correction: only fresh, non-duplicate accepted results may create a liveness
  receipt. Durable duplicate Turn and Retry tests clear receipts as on restart,
  replay the exact key without a second adapter call, and keep activity in
  Checking/Reconciliation. A Home interaction test keeps duplicate Retry
  controls gated until the selected stream performs exact readback.

### Round 4

- Safety reviewer verdict: clean, no findings.
- Product/compatibility reviewer verdict: clean, no findings.
- Both reviewers verified non-duplicate receipt gating across Send, Continue,
  Retry, and Resume; restart-style replay coverage; archive restore/Continue;
  nonblocking activity reads; mobile target sizing; and selected-control gating.

## Documentation updates

- Updated `AGENTS.md` and `ARCHITECTURE.md` with archive continuation,
  recovery-attempt, liveness-receipt, and browser capability-honesty contracts.
- Updated `CHANGELOG.md`, this review log, and the implementation roadmap's
  active Slice 4 record. Tracker resolution and final roadmap advancement occur
  after the ready PR merges.

## Publication gate

- Standing authorization recorded above. Exact files, commit, ready PR, CI,
  and merge evidence will be recorded before publication.

## Outcome review

- Classification: Successful and ready for publication.
- Next slice authorized: Yes, under the user's standing approval, but it will
  not begin until Slice 4 passes its required gates and closes.
