# Feature Slice Review: Agent Console text turn and Run creation

Status: PR open; CI follow-up verified, awaiting publication approval
Slice: `agent-console-text-turn-run-creation`
Date: `2026-08-26`
Review log: `reviews/2026-08-26-agent-console-text-turn-run-creation.md`

## Slice contract

### Goal

Let an operator submit one text Turn in an idle durable Conversation and start
one real runtime-neutral Mentat Run through the Next.js Console without a
confirmation dialog.

### In scope

- Keep Conversation creation as its existing fixed capability and add one
  separate fixed submit-Turn capability through Next.js, the private Python
  bridge, SQLite repositories, and runtime-neutral orchestration.
- Support the Conversation's immutable selected custom Agent or canonical
  Direct Agent when its runtime advertises `run.start`.
- Accept text-only input of at most 6,000 Unicode code points in an idle active
  Conversation.
- Commit the user Message, Turn, Run reservation, exact idempotency evidence,
  immutable execution-configuration evidence, and private capacity evidence
  before any adapter call.
- Invoke a runtime at most once after releasing SQLite and private-state locks,
  then durably reconcile accepted, rejected, or unknown submission evidence.
- Add optimistic user-message display with rollback for pre-admission
  rejection, Enter-to-send, Shift+Enter newline, and an honest unavailable
  composer while the selected Conversation has a nonterminal Run.
- Prove the production path with a real supported local Codex runtime; fixture
  evidence remains supplementary.
- Reuse each user's existing Codex CLI sign-in, expose only an explicit bounded
  Codex readiness check, and show `codex login` setup guidance plus a Recheck
  action when Direct Agent authentication is unavailable.

### Out of scope

- Queued or capacity-blocked Turns, active-Run composing, Turn editing or
  cancellation, automatic next-Turn dispatch, steering, Retry, or Resume.
- Live transcript/event streaming, Stop or pending-action integration,
  attachments, Context Packs, rich rendering, link previews, artifacts, or
  provider/model/effort mutation.
- A generic Node/Python proxy, legacy Console API reuse as the browser contract,
  browser-selected runtime references, or automatic retry after an ambiguous
  mutation.
- Mentat credential entry or storage, embedded OAuth/device-code login, API-key
  entry, logout/account management, or browser access to Codex auth caches,
  tokens, account identifiers, or raw account responses.
- Closing the automated rendered-browser gap or restoring a strict 100 mobile
  Lighthouse performance score from Slice #133 unless this slice regresses the
  current accepted gate.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | An idle Conversation owned by a Direct or selected custom Agent accepts one bounded text Turn through named Next.js and private-bridge capabilities and creates a canonical Run without a confirmation modal. | Repository/service, bridge/BFF, UI, and real-runtime tests. | Pass |
| AC-2 | Message, Turn, Run reservation, idempotency digest, immutable Agent/runtime/configuration snapshot, and private capacity evidence commit atomically before an unlocked adapter call and survive refresh/restart. | Transaction-order, fault-injection, restart, backup/restore, and read-projection tests. | Pass |
| AC-3 | Repeating the same idempotency key and request digest returns the same canonical result without another adapter call; changed input with the same key fails closed. | Replay, persistence, and concurrent race tests. | Pass |
| AC-4 | One Conversation cannot admit two nonterminal Runs under concurrent different-key submissions. | SQLite constraint/repository race test. | Pass |
| AC-5 | Pre-admission rejection writes no Message, Turn, or Run and restores the optimistic draft; a post-reservation rejection or unknown outcome remains durable and is never represented as accepted runtime execution or retried automatically. | Negative-path service and UI rollback tests. | Pass |
| AC-6 | A real local supported runtime starts from the production Next.js Console path, and canonical accepted input plus Run evidence remain after process restart. | Host-side production build/browser smoke using local Codex plus SQLite inspection/reopen. | Pass |
| AC-7 | Browser projections remain bounded and omit runtime references, configuration IDs/digests, capacity scope/digest, credentials, paths, and raw provider data; Node adds only named capabilities. | Exact-schema, canary, malformed-body, oversized-body, and route tests. | Pass |
| AC-8 | Existing schema migration, backup/restore, Agent/Task/Run routes, lifecycle, rollback UI, accessibility, performance, and supported platform gates do not regress. | Focused compatibility checks, full Python/web suites, production build, browser smoke, and CI matrix. | Pass locally; publication CI pending |
| AC-9 | An explicit Codex readiness check reports only CLI missing, sign-in required, ready, or unavailable; setup guidance uses the official `codex login` flow, Recheck becomes ready after local ChatGPT sign-in, and no credential material crosses the browser, bridge, SQLite, backup, log, or tracked-file boundary. | Safe-projection tests, readiness failure tests, setup UI tests, and a host-side ChatGPT-subscription readiness/dispatch smoke. | Pass |

### Constraints and recovery

- Safety: Python and owner-private SQLite remain authoritative. Browser input
  selects only the Conversation, text, and opaque idempotency key. No lock may
  cross a runtime call.
- Compatibility: Existing Task dispatch remains unchanged. Legacy Console Runs
  stay unbound compatibility evidence. Existing schema-10 roots and released
  backup formats remain readable.
- Rendered behavior: The optimistic Message appears immediately. Pre-admission
  failure removes it and restores the exact submitted draft. Active-Run follow-up
  composing remains explicitly unavailable until Slice 3.
- Rollback or recovery: A reservation never attempted before restart becomes
  interrupted; an uncertain claimed attempt becomes unknown; accepted work is
  reconciled only from an exact durable runtime reference. No submission is
  automatically repeated.
- Documentation targets: This review log, `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`,
  `CHANGELOG.md`, and `ARCHITECTURE.md` only where production behavior changes.
- Version-control strategy: Branch
  `codex/agent-console-text-turn-run-creation` from `main`; preserve and exclude
  unrelated worktree files. Publication requires a separate exact approval.

### Scope discussion and approval

- Recommendation and rationale: Add a runtime-neutral Conversation-Turn
  submission contract instead of synthesizing a Task. Keep creation and Send
  separate so Conversation identity exists before execution and the mutation
  remains idempotent and recoverable.
- Alternatives considered: Codex-only production code would not satisfy custom
  Agent behavior; reusing Task dispatch would conflate Turns with Tasks; a
  combined create-and-send route would weaken the durable Conversation boundary.
- User decisions: Approved the recommended contract, exclusions, review-log
  path, branch, and base.
- Approved at: 2026-08-26 conversation.

### Codex authentication/setup amendment

Status: Approved after the original contract and test strategy.

- Codex CLI/App Server, not Mentat, remains the credential owner. A subscription
  user signs in through the official ChatGPT browser flow with `codex login`;
  Mentat reuses that local sign-in and receives no password, browser cookie,
  API key, access token, refresh token, auth-cache file, or account identifier.
- Add an explicit, named Codex readiness check that reports only bounded public
  states such as CLI missing, sign-in required, ready, or unavailable. Routine
  Agent/Conversation reads must remain static and must not launch Codex.
- When Direct Agent setup is required, show concise cross-platform setup
  guidance for `codex login` plus an explicit **Recheck** action. An already
  signed-in user proceeds without reauthentication.
- Update first-run documentation so every local Mentat user authenticates their
  own Codex CLI on the same machine. Never ask a user to paste a credential into
  the Mentat browser, configuration, issue, log, or support channel.
- Add AC-9: after official CLI sign-in, an explicit readiness recheck becomes
  ready and the real Direct Agent path can run; before sign-in it fails closed
  with setup guidance, and no authentication secret crosses the browser,
  bridge, SQLite, backup, log, or tracked-file boundary.
- Add tests for CLI-missing, sign-in-required, ready, malformed/timeout, and
  safe-projection states, plus a real host-side ChatGPT-subscription readiness
  and dispatch smoke. The smoke validates status only and records no account
  identity or credential material.
- Keep an embedded OAuth/device-code ceremony and API-key entry out of this
  slice. Those require a separately reviewed authentication lifecycle even
  though Codex App Server exposes fixed managed-login methods.
- User decision: Approved the amendment as written.
- Approved at: 2026-08-26 conversation.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Send is disabled and no Turn submission API/service exists. | Failing repository/service contract tests, exact bridge/BFF route tests, React interaction test, and one real local Codex smoke. | The complete named production path creates real canonical work. | One live runtime proves the path; other adapters use production contract tests unless locally configured. |
| AC-2 | Schema columns exist but no production atomic Send mutation, immutable snapshot writer, or Conversation restart recovery exists. | Fault injection before/after commit and adapter claim; SQLite inspection; reopen and format-4 backup/restore tests. | Durable intent precedes external effects and recovery preserves exact evidence. | Abrupt power-loss durability is represented by transaction/restart tests, not hardware fault injection. |
| AC-3 | Turn idempotency fields are unused. | Sequential, post-restart, concurrent duplicate, and changed-digest tests with adapter call counts. | Exact replay is stable and changed intent cannot borrow prior authority. | Does not emulate every browser retry policy. |
| AC-4 | The schema has a unique active-Conversation index but no writable race proof. | Two-thread barrier race with separate SQLite connections and different keys. | Exactly one nonterminal Run is admitted. | Scheduler timing is nondeterministic; the barrier fixes the critical overlap. |
| AC-5 | No optimistic Send behavior or rejection contract exists. | Service rollback/failure injection plus UI optimistic-paint, draft-restore, and durable unknown/rejected-state tests. | Local rejection and post-attempt uncertainty are distinct and honestly rendered. | Visual polish is checked in the supported Chromium fixture only. |
| AC-6 | Current production UI cannot dispatch. | Production Next.js build, local supervised preview, browser Send through Direct Agent, SQLite reopen, and bounded restart reconciliation. | Fixture-only success is not being substituted for real execution. | Requires a locally signed-in Codex CLI; absence pauses this acceptance gate. |
| AC-7 | Existing read projections do not include a submit response. | Exact Python/TypeScript parsers, secret/private canaries, malformed JSON, unknown field, duplicate header, route, size, and timeout tests. | The new mutation does not widen the browser/bridge authority boundary. | Browser extensions are outside the threat model. |
| AC-8 | Existing suites are green only on the merged Slice #133 baseline. | Focused compatibility suites, full Python discovery, full web check, production build, browser smoke, Lighthouse gate, and GitHub platform matrix. | Existing product, recovery, and packaging contracts remain intact. | Unrelated modified tracked fixtures remain excluded and may make a mixed-worktree full-suite run non-authoritative. |
| AC-9 | Conversation setup currently distinguishes only static CLI/binding availability; it has no explicit authentication/readiness projection or Recheck action. | Codex readiness service, bridge/BFF exact-schema tests, CLI-missing/sign-in-required/ready/timeout fixtures, setup UI tests, secret canaries, and a real signed-in host probe. | Users can establish and verify subscription-backed Codex readiness without giving Mentat a credential. | The slice documents the official CLI browser flow; embedded OAuth/device-code login is deferred. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest tests.test_conversation_repository tests.test_orchestration_service -q` | macOS, Python 3.13, branch from `origin/main` | Pass | 35 tests passed in 7.008 seconds. Existing Conversation reads and Task orchestration are green; no submit-Turn behavior exists. |
| `npm --prefix web run check` | macOS, Node 24 | Pass | Lint and typecheck passed; all 48 web tests passed. Existing source contracts still require a disabled Send action. |
| Source inspection of `home-console.tsx`, Conversation routes, bridge, repository, and orchestration service | Current branch | Expected gap confirmed | Send is disabled; there is no named submit-Turn BFF/private route, production Turn writer, Conversation Run reservation, or Conversation recovery path. |

### Test discussion and approval

- User questions and decisions: The user approved the proposed matrix, including
  atomicity/recovery fault injection, sequential/concurrent/restart
  idempotency, one-nonterminal-Run race coverage, unlocked adapter-call proof,
  fixed bridge/BFF schemas and canaries, optimistic rollback and keyboard
  behavior, and a real local Codex production-path smoke.
- Accepted coverage gaps: The real-runtime smoke covers Codex; other adapters
  use production contract tests unless locally configured. Abrupt power loss is
  represented with transaction and process-restart fault injection rather than
  hardware power-loss testing.
- Approved at: 2026-08-26 conversation.

## Implementation record

### Changes

- Added atomic Conversation Message/Turn/Run reservation and exact replay,
  one-active-Run, immutable binding/configuration, conservative capacity, and
  restart-recovery behavior in `run_repository.py` and
  `conversation_repository.py`.
- Added runtime-neutral Conversation Turn dispatch in
  `orchestration_service.py`, with all readiness and adapter work outside
  SQLite/private-state locks and no more than one adapter submission.
- Added write-once, digest-bound runtime-execution identity from verified
  adapter responses and truthful RuntimeConfig revision evidence.
- Added explicit four-state Codex readiness plus the fixed App Server production
  request in `codex_runtime.py`; the Codex CLI remains the sole authentication
  and credential owner.
- Added exact Python bridge and Next.js BFF capabilities for Turn submission and
  Codex readiness, with exact-length bounded bodies, transfer-encoding
  rejection, total body-read deadlines, projections, and fixed error states.
- Enabled the Next.js composer with optimistic display, pre-admission rollback,
  exact-key ambiguous retry behavior, Enter/Shift+Enter handling, canonical
  result replacement, IME protection, readiness gating, and nonterminal-Run
  gating. Drafts, optimistic state, in-flight state, admission blocks, exact
  retry keys, and Turn announcements are Conversation-scoped across navigation;
  monotonic notice ordering lets newer global failures supersede stale Turn
  feedback. Initial loading gates drafting, and an empty-workspace draft moves
  to exactly one newly created Conversation. A rendered empty-workspace
  regression test prevents a false block when both optional Conversation IDs
  are null.
- The Next.js private bridge now classifies crash states synchronously after
  bind but before readiness or request handling, then performs only bounded
  exact-reference readback on a background thread. Unattempted, uncertain,
  unattached, and durable-reference states retain their existing fail-honest
  semantics and are never resubmitted.
- Added concise Codex subscription setup guidance and updated architecture,
  implementation-plan, changelog, and README documentation.
- Kept the retired Console loader isolated from Conversation-bound Runs; no
  additional legacy feature work was undertaken.

### Deviations and decisions

- The first production Codex smoke exposed a fixed-protocol spelling error:
  installed App Server schema `0.144.6` accepts `sandbox: "workspace-write"`
  for `thread/start`, while the response-side sandbox policy uses
  `workspaceWrite`. The fixed request and exact test expectation were corrected;
  the subsequent production Next.js submission was accepted.
- A cold first Conversation read measured 1.512 seconds, just beyond the prior
  1.5-second bridge deadline. The bounded private read deadline is now 3.5
  seconds and the browser-to-BFF read deadline is 5 seconds. A new isolated
  cold-root browser run loaded canonical Direct Agent data without the transient
  unavailable state or bridge broken pipe.
- An interrupted sandbox build left stale generated `.next` state that caused
  repeated Turbopack helper-bind failures. Moving only that generated directory
  to `/private/tmp` and rebuilding on the host produced a clean Next 16.3.2
  Turbopack production artifact; a subsequent incremental build also passed.
- Production browser inspection found a null-state bug where an empty workspace
  compared two absent Conversation IDs as equal and falsely disabled the
  composer. Requiring a non-null selected Conversation fixed it and added a
  rendered regression test.
- The lightweight preview harness does not claim Run authority as the real
  launcher does. The real-runtime proof explicitly established that production
  invariant before Send. It then exposed that the Next private bridge was not
  starting crash recovery/reconciliation; bridge startup now runs the existing
  runtime-neutral recovery and exact-reference readback after bind.
- Adversarial review then exposed that background crash classification could
  overlap the first newly admitted Turn. Startup now gates all request handling
  on synchronous classification, initializes authoritative Console history
  without rerunning recovery, and leaves only exact-reference readback in the
  background. The same review found permissive private-body framing plus global
  or stale draft/retry/announcement state; exact body reads and
  Conversation-scoped, recency-aware UI state close those paths with controlled
  socket, Hermes, and rendered-navigation regressions.
- The first quiet Lighthouse sample had a high-variance mobile median of 93
  (99/78/93, including a 984 ms blocking-time outlier). An immediate isolated
  confirmation with unchanged thresholds passed at desktop 100/mobile 97 and
  all accessibility, best-practices, and SEO scores at 100. The failed sample is
  retained in this record rather than hidden or used to lower the gate.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m py_compile` over all changed Python production modules | macOS, Python 3.13 | Exit 0 | Pass | Repository, adapters, bridge, server, schema, and authority modules compile. |
| `python3 -m unittest tests.test_codex_runtime tests.test_orchestration_service tests.test_hermes_runtime_server_integration tests.test_run_repository tests.test_agent_registry tests.test_private_console_state -q` | macOS, Python 3.13 | Exit 0 | 215 pass, 1 skip | End-to-end deadlines, immutable runtime identity, acceptance races, restart readback, registry, schema-10 restore, and schema-11 backup semantics. |
| `python3 -m unittest tests.test_mentat_local_bridge -q` | Host loopback execution | Exit 0 | 39 pass | Authenticated fixed capabilities, 96 KiB Turn boundary, exact framing/deadline sockets, safe projections, and pre-readiness recovery gating. |
| `python3 -m unittest tests.test_node_runtime_foundation tests.test_mentat_web_preview -v` | macOS, Python 3.13 | Exit 0 | 8 pass | Pins the lifecycle verifier to the preflighted CI data root and preserves fixed preview commands, version gates, and sibling cleanup. |
| Targeted legacy-root, bridge-startup, Node-foundation, and source-preview tests | macOS, Python 3.13 | Exit 0 | 12 pass | Proves recovery performs no destination write before a required private migration and preserves synchronous classification plus preview lifecycle contracts. |
| `python3 -m unittest tests.test_private_console_state tests.test_orchestration_service tests.test_mentat_local_bridge tests.test_hermes_runtime_server_integration -q` | Host loopback execution | Exit 0 | 142 pass | Private migration/state, orchestration recovery, authenticated bridge, and production Hermes integration after the read-only authority preflight. |
| `MENTAT_DATA_DIR=<preflighted-root> python3 scripts/verify_web_preview_lifecycle.py` | Host process execution with a fresh isolated root prepared through the normal startup and Task/Run authority contracts | Exit 0 | 2 sibling-death scenarios pass | Reproduces the amended PR CI lifecycle path; both bridge-death and Node-death cleanup stop the sibling and gateway without initializing authority inside the bridge. |
| Five targeted startup/reconciliation tests | macOS, Python 3.13 | Exit 0 | 5 pass | Production startup entrypoint recovers unattempted/uncertain Conversation Runs and reconciles durable references without another submit call. |
| `npm --prefix web run check` | macOS, Node 24 | Exit 0 | 63 pass | ESLint, TypeScript, exact routes, keyboard/IME/readiness/rollback, initial draft gating/one-time movement, cross-Conversation draft/retry isolation, activity return, and notice recency. |
| `npm --prefix web run build` | Host execution, Node 24 | Exit 0 | Production build pass | Next 16.3.2 Turbopack compiled all named routes and prepared the standalone artifact. Repeated successfully after the rendered empty-state fix. |
| `npm --prefix web run lighthouse:gate` | Pinned Chromium 152, isolated production loopback | Exit 0 on final post-fix gate | Desktop median 100; mobile median 98; all other category runs 100 | Three runs per mode at the unchanged 95/100 threshold. The preceding failed 93 mobile-median sample is documented under deviations. |
| `git diff --check` | Current worktree | Exit 0 | Pass | No whitespace errors after the final implementation and documentation changes before reviewer disposition. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | Host execution from clean `/private/tmp` issue-only tree | Exit 0 | 1,541 pass, 5 skip | 482.239 seconds; excluded user-owned tracked fixtures and unrelated untracked files. Run immediately before the final startup-entrypoint integration. |
| `python3 -m unittest discover -s tests -q` | Host execution from final clean `/private/tmp` issue-only tree | Exit 0 | 1,541 pass, 5 skip | 517.773 seconds; includes the final startup recovery/reconciliation entrypoint and excludes user-owned tracked fixtures and unrelated untracked files. |
| `python3 -m unittest discover -s tests -q` | Host execution from final post-review clean `/private/tmp` issue-only tree | Exit 0 | 1,544 pass, 5 skip | 464.232 seconds; includes every adversarial fix and excludes user-owned tracked fixtures and unrelated untracked files. |
| `python3 -m unittest discover -s tests -q` | Host execution from clean `/private/tmp` PR-plus-follow-up tree | Exit 0 | 1,545 pass, 5 skip | 533.956 seconds; includes the non-mutating recovery preflight, legacy-root regression, workflow correction, and no user-owned workspace changes. |

### Rendered or manual behavior

- An isolated production Next.js instance on loopback and a temporary private
  data root loaded the canonical Direct Agent and created a durable Conversation.
  A rendered check first caught and then verified the empty-workspace composer
  fix; the left and right collapse controls remained vertically centered on the
  full viewport border.
- Explicit **Check readiness** changed the safe UI state to **Codex ready** using
  the existing local ChatGPT subscription sign-in; no account identifier,
  credential, auth path, or raw response crossed the browser boundary.
- The real browser submission painted the optimistic **You · Sending…** Message
  and disabled editing before the response. Codex then accepted it, the durable
  Message replaced the optimistic row, the draft cleared, and the canonical
  `Run Running` state blocked another Send.
- SQLite inspection showed one consumed Turn, attempt count 1, one accepted Run,
  a private runtime reference, RuntimeConfig revision 1, immutable execution and
  capacity digests, plus a write-once verified runtime-execution document and
  digest. No credential or account data was recorded.
- After stopping the owning process, the updated bridge restarted, recovered
  crash states, queried the exact durable Codex reference once, and moved the
  same Run to `completed` with no resubmission. Refresh preserved the accepted
  user Message and reopened the composer; the same Conversation remained active.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Complete issue-only working-tree diff against
  `origin/main`; no commit existed during review.
- Verification evidence: Focused repository/service/bridge/UI suites, clean
  full-suite runs, Turbopack production builds, strict Lighthouse runs, and the
  real signed-in Codex production/restart smoke described above.
- Rendered artifacts: Isolated production-browser inspection of idle, sending,
  active-Run, restarted, collapsed-rail, and compact-composer states.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P1 | Yes | Accepted Conversation Runs lacked restart readback; fast Hermes completion could be overwritten by a later acceptance write; runtime configuration evidence used placeholders. | Yes | Add exact-reference startup reconciliation, preserve worker-authored terminal state, and persist truthful write-once execution identity. |
| A-2 | P1 | Yes | The bridge announced readiness while crash classification ran asynchronously, so a newly admitted Turn could be reclassified unknown. | Yes | Finish crash classification before readiness/request handling and leave only reference readback asynchronous. |
| A-3 | P1 | Yes | Hermes could lazily load Console history after claiming a new Turn, rerunning crash recovery against live work. | Yes | Initialize authoritative Console history in the pre-readiness phase without a second recovery pass. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | P1/P2 | Yes | Inner Codex deadlines could outlive outer route certainty; known not-ready Codex state still enabled Send; the composer remained editable during in-flight/active-conflict states. | Yes | Nest one end-to-end deadline and gate/disable the composer from canonical readiness and Run state. |
| B-2 | P2 | Yes | The private body cap rejected valid worst-case 6,000-code-point JSON and IME protection missed composition lifecycle/key-code cases. | Yes | Raise the exact bounded cap to 96 KiB and cover composition start/end, native composition state, and key code 229. |
| B-3 | P2 | Yes | Private mutation reads accepted transfer encoding or short bodies and had no total read deadline. | Yes | Require exact framing/bytes and enforce one monotonic body-read deadline. |
| B-4 | P2 | Yes | Draft, optimistic, in-flight, admission, and unresolved retry state was global, so navigation could lose one Conversation's exact key or mutate another draft. | Yes | Scope all submission state and retry evidence per Conversation. |
| B-5 | P2 | Yes | The pre-Conversation draft could resurface in later Conversations, and global/Conversation announcements could hide or mislabel newer feedback, including activity-rail return. | Yes | Gate initial drafting, atomically move the unbound draft once, and use scoped monotonic notice ordering with non-advancing clear. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Runtime outcome/restart evidence was not fully monotonic. | Reviewer A; corroborated by production restart smoke. | Re-reviewed after service/repository fixes. | Accepted. Exact durable references reconcile without resubmission; worker terminal state and execution identity are write-once. | Repository CAS/state rules, adapter outcome handling, startup readback, and tests. |
| Crash classification could overlap post-readiness admission. | Reviewer A; unique controlled race. | Re-reviewed after startup split. | Accepted. Request handling starts only after synchronous classification. | Split crash classification from runtime readback; added blocked-recovery/serve ordering test. |
| Lazy Hermes history initialization could rerun recovery live. | Reviewer A; unique Hermes path. | Re-reviewed after history split. | Accepted. The production Hermes test fails if the full recovery loader is called after admission. | Pre-readiness history initialization without recovery plus Hermes integration regression. |
| Route/runtime deadline and UI readiness/editability gaps. | Reviewer B; consistent with route/UI inspection. | Re-reviewed after bounded deadline and state-gate changes. | Accepted. Exact route and rendered tests pass. | Shared Codex budgets and canonical readiness/in-flight/active-Run gates. |
| Body framing/cap and IME edge cases. | Reviewer B; socket and rendered reproduction. | Re-reviewed after parser/input changes. | Accepted. Live socket tests reject chunked, short, and stalled bodies; IME tests pass. | Exact 96 KiB parser with total deadline and full composition guards. |
| Cross-Conversation draft/retry/announcement leakage. | Reviewer B; rendered navigation reproduction. | Re-reviewed through tab and activity paths. | Accepted. A's exact key/draft/notice survive B; newer global failures still win. | Per-Conversation state, one-time unbound draft move, and monotonic notice ordering. |

### Reverification

- Focused tests: 215 runtime/orchestration tests pass with 1 skip; 39 host
  bridge tests pass; 63 web tests plus lint/typecheck pass; Hermes production
  integration passes 5/5.
- Full suite: Final post-fix clean issue-only tree passed 1,544 tests with 5
  skips in 464.232 seconds.
- Final independent gate: Reviewer A **CLEAN** and Reviewer B **CLEAN** after
  all findings and focused regression tests.

### Publication CI follow-up — PR #144

- Initial commit `a6894ae80658f98d29b729b1f9103b203fdaebd8` opened
  [PR #144](https://github.com/hazeion/agent-os/pull/144). The production
  build, browser smoke, dependency/secret scan, and Lighthouse gate passed;
  Lighthouse reported desktop 100 and mobile 97 medians at the unchanged 95
  threshold.
- The final Node preview lifecycle check failed before readiness with
  `startup_recovery_unavailable`. A fresh isolated data root reproduced the
  same failure locally.
- Root cause: the new synchronous bridge crash-classification path correctly
  requires the Run authority established by the owning production supervisor.
  The CI job established that authority in `preview_data_dir` for browser smoke
  but dropped `MENTAT_DATA_DIR` when it invoked the final lifecycle verifier, so
  the verifier accidentally started against the checkout's unprepared default
  root. Existing development roots masked that test-fixture gap.
- The first local correction initialized Run authority inside the bridge. The
  compatibility reviewer reproduced a P1 upgrade regression: doing so could
  claim an empty destination before an operator completed the required private
  Console migration. That correction was fully reverted before publication.
- Follow-up review then found the underlying feature commit still opened the
  writable SQLite boundary before checking the required receipt. A direct
  bridge invocation on an unmigrated root could therefore create the private
  destination even though recovery failed. Recovery now verifies the existing
  receipt through the non-mutating read-only database boundary while holding
  the private-state lock, and only then opens the writable recovery connection.
  A real legacy-root regression proves the source bytes and `ready` migration
  status remain unchanged and no destination directory appears.
- Final CI fix: the workflow passes its already preflighted `preview_data_dir`
  to the lifecycle verifier, matching the production parent/child authority
  contract. A workflow contract test pins the exact environment assignment.
- Reverification: 12 focused tests and the broader 142-test private-state,
  orchestration, bridge, and Hermes set pass; Python compile and
  `git diff --check` pass; and the exact lifecycle script passes both process-
  death cases on a fresh normally prepared root. The final clean tree passes
  1,545 tests with 5 skips, and both independent follow-up reviewers returned
  **CLEAN**.

## Documentation updates

- Roadmap: `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md` marks Console Slice 1 complete,
  this text-Turn slice in progress through publication, and removes startup
  reconciliation from later work because it is now implemented here.
- Changelog: `CHANGELOG.md` records the named Turn capability, immutable
  execution evidence, startup recovery/reconciliation, and composer/readiness
  behavior.
- Architecture/operator docs: `ARCHITECTURE.md` records schema-11 Conversation
  authority, submission/recovery boundaries, write-once runtime identity,
  Codex readiness, and deadline nesting. `README.md` documents each user's
  official `codex login` / `codex login status` setup and the browser Recheck
  flow without credential entry in Mentat.
- Project/session notes: This review log.
- Documentation verification: Cross-checked against production code, exact
  route tests, the real signed-in Codex smoke, restart reconciliation, and the
  final clean-tree suite.

## Publication gate

- Proposed files (exact 46-file packet):

  ```text
  ARCHITECTURE.md
  CHANGELOG.md
  MENTAT_PIVOT_IMPLEMENTATION_PLAN.md
  README.md
  agent_registry.py
  agent_runtime.py
  codex_runtime.py
  conversation_repository.py
  hermes_runtime.py
  mentat/local_bridge.py
  mentat_db.py
  orchestration_service.py
  private_console_unit.py
  reviews/2026-08-26-agent-console-text-turn-run-creation.md
  run_repository.py
  server.py
  task_repository.py
  tests/test_agent_registry.py
  tests/test_codex_runtime.py
  tests/test_conversation_repository.py
  tests/test_hermes_runtime_server_integration.py
  tests/test_mentat_local_bridge.py
  tests/test_orchestration_service.py
  tests/test_private_console_state.py
  tests/test_run_repository.py
  tests/test_task_repository.py
  tests/test_vercel_connections.py
  vercel_connections.py
  web/package-lock.json
  web/package.json
  web/scripts/register-test-typescript.mjs
  web/scripts/test-typescript-loader.mjs
  web/src/app/api/codex-readiness/route.ts
  web/src/app/api/conversations/[conversationId]/turns/route.ts
  web/src/app/globals.css
  web/src/app/home-console.tsx
  web/src/lib/bridge-conversations.ts
  web/src/lib/codex-readiness-route.ts
  web/src/lib/conversation-turn-route.ts
  web/src/lib/exact-json-body.ts
  web/src/lib/public-conversations.ts
  web/tests/bridge-conversations.test.ts
  web/tests/conversation-routes.test.ts
  web/tests/exact-json-body.test.ts
  web/tests/home-console-interaction.test.tsx
  web/tests/shell-contract.test.ts
  ```
- Branch and base: `codex/agent-console-text-turn-run-creation` to `main`.
- Commit message: `feat: add Agent Console text Turn execution`
- PR title: `Agent Console Slice 2: text Turn and Run creation`
- PR summary: Add atomic, idempotent runtime-neutral text Turn submission and
  recovery; explicit credential-safe Codex readiness; and the Next.js
  optimistic composer with Conversation-scoped retry state.
- Unresolved risks: Initial PR CI exposed the clean-root startup-ordering gap.
  Its local fix is verified but has not yet been committed or pushed; the
  required matrix must rerun on the amended PR. The live production smoke
  exercised signed-in Codex; Hermes uses the production integration contract
  test. Lighthouse has documented host variance, although local and PR gates
  passed unchanged thresholds.
- Explicit exclusions: user-owned `data/projects.json`, `data/tasks.json`,
  `design/mockups/`, `tmp/`, `uv.lock`, `videos/`, and `web/.npmrc`.
- User authorization and scope: The exact 46-file packet was approved, committed,
  pushed, and opened as a PR. The follow-up packet is limited to
  `.github/workflows/quality-gates.yml`, `server.py`,
  `tests/test_node_runtime_foundation.py`, `tests/test_private_console_state.py`,
  and this review log; it requires refreshed publication approval after re-review.
- Commit hash: `a6894ae80658f98d29b729b1f9103b203fdaebd8`.
- Proposed follow-up commit: `fix: guard bridge startup recovery authority`.
- Ready PR URL: https://github.com/hazeion/agent-os/pull/144

## Outcome review

- Classification: Initial publication complete; the clean-root CI and migration-
  safety follow-up is locally verified and awaits publication authorization.
- Acceptance criteria summary: AC-1 through AC-9 pass locally; AC-8's required
  publication CI remains pending on the amended PR rerun.
- Potential bugs or untested paths: The known clean-root startup failure is fixed
  locally but remains blocking until the amended PR passes required CI. Only one
  local Codex installation was used for the real runtime smoke; Hermes and
  failure paths are covered by production integration/fault tests rather than
  a second live provider account.
- Remaining reviewer dissent: None. Both independent follow-up reviewers returned
  **CLEAN** after the unsafe first approach was reverted and writable recovery
  gained the read-only receipt preflight plus real legacy-root regression.
- Compatibility/migration/rollback concerns: Schema-10 roots and released
  backup formats remain covered; schema-11 restore/export and clean full-suite
  checks pass. Rollback remains branch/commit based until publication.
- User decision: Original contract, test strategy, Codex authentication/setup
  amendment, and initial exact publication packet approved. Follow-up CI-fix
  publication approval pending.
- Next slice authorized: No
