# Feature Slice Review: Hermes event refresh coordinator

Status: Reviewed; publication authorized
Slice: `hermes-event-refresh-coordinator`
Date: `2026-08-14`
Review log: `reviews/2026-08-14-hermes-event-refresh-coordinator.md`

## Slice contract

### Goal

Use verified Hermes lifecycle webhooks to wake bounded, coalesced, read-only
refreshes while preserving periodic reconciliation, and establish stock Hermes
outbound hooks as Mentat's preferred future notification boundary.

### In scope

- Add a server-owned refresh coordinator with a bounded queue, per-binding and
  per-projection coalescing, bounded adapter concurrency, failure backoff, and
  bounded shutdown.
- Map the four currently approved lifecycle events to authoritative read-backs
  for sessions, observed agent presence, attention, and relevant Kanban task
  projections.
- Preserve periodic reconciliation so dropped, delayed, duplicate, or
  out-of-order webhook hints converge.
- Keep webhook acknowledgment independent of Hermes read latency.
- Record a migration matrix for stock-Hermes webhook events that may later
  replace custom telemetry or high-frequency polling.

### Out of scope

- Browser push/SSE, the 9D operator health UI, or removal of the browser's
  existing polling loop.
- Accepting `post_tool_call`, `post_api_request`, streaming, model, or Kanban
  events at the receiver in this slice.
- Trusting webhook payload values as authoritative task, run, usage, tool, or
  provider state.
- Removing local telemetry, remote Runs event polling, or custom-fork APIs
  before a native replacement has passed convergence and compatibility tests.
- Merging the 5,183-commit upstream divergence into the custom Hermes fork.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Each approved lifecycle event schedules only its documented read-only projection set. | Event-matrix unit tests | Pass before review |
| AC-2 | 1,000 rapid hints keep memory bounded and collapse to a small number of adapter reads. | Storm/coalescing tests and queue inspection | Pass before review |
| AC-3 | Accepted webhooks acknowledge without waiting for refresh work, and no webhook field directly changes authoritative run/task state. | Route timing/isolation tests and source inspection | Pass before review |
| AC-4 | Adapter failure is isolated, records bounded degraded evidence, backs off, and cannot produce a false terminal state. | Failure/backoff tests | Pass before review |
| AC-5 | A deliberately dropped hint converges through scheduled reconciliation. | Reconciliation integration test | Pass before review |
| AC-6 | Shutdown drains for no more than two seconds, and a fresh coordinator can reconcile after restart without relying on old in-memory hints. | Lifecycle tests | Pass before review |
| AC-7 | Existing webhook security behavior and the wider Mentat suite do not regress. | Focused webhook suite, compile checks, clean exact-slice full suite, wheel/sdist verification | Pass after Round 1 fixes |
| AC-8 | A documented migration matrix distinguishes native webhook wakeups, authoritative read-backs, temporary fallback paths, and removal gates for usage, tool, model/provider, session, and Kanban updates. | Review-log and roadmap inspection | Pass before review |

### Constraints and recovery

- Safety: webhooks remain untrusted hints; only supported Hermes read adapters
  may refresh projections, and no raw body or sensitive `extra` data is kept.
- Compatibility: unconfigured and Hermes 0.19 installations retain existing
  behavior. Stock Hermes compatibility is preferred over custom-fork coupling.
- Rendered behavior: none in this slice; the browser continues its existing
  refresh behavior until a separately reviewed push-channel slice.
- Rollback or recovery: stop the coordinator, restore the bounded hint list,
  and leave polling/reconciliation enabled. No Hermes-owned file is changed.
- Documentation targets: this log, `ROAD_TO_BETA.md`, and the existing Milestone
  9 implementation plan where its upstream baseline is stale.
- Version-control strategy: stacked branch
  `codex/hermes-webhook-refresh-coordinator` based on
  `codex/hermes-webhook-receiver-foundation`; preserve unrelated dirty files.

### Scope discussion and approval

- Recommendation and rationale: implement the coordinator against the stable
  four-event receiver first, then migrate richer stock-Hermes events in
  privacy-reviewed slices after each authoritative read-back is identified.
- Alternatives considered: ingest all upstream hook payloads immediately
  (rejected because tool/API hooks carry prompts, arguments, results, paths,
  and other sensitive fields); merge the entire Hermes fork first (deferred as
  a separate high-risk compatibility integration).
- User decisions: approved the bounded 9C coordinator and test strategy, then
  required an explicit trajectory toward using native Hermes webhooks wherever
  safe so Mentat can eventually stop depending on the custom fork.
- Approved at: 2026-08-14, America/Los_Angeles.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Receiver stores hints but has no consumer or event dispatch matrix. | Pure event-to-projection mapping tests. | Events cannot request unrelated refreshes. | Does not prove live Hermes availability. |
| AC-2 | Existing bounded list rejects overflow but does not coalesce work. | Deterministic 1,000-hint storm test with controlled clock/adapters. | Queue and adapter work remain bounded. | Synthetic workload cannot model all host scheduling. |
| AC-3 | The route currently appends directly to an inert list. | Slow-adapter route test and authority-boundary inspection. | HTTP acknowledgment is independent of Hermes reads. | Network latency outside loopback is out of scope. |
| AC-4 | There is no refresh health/backoff state. | Raising adapter and retry-clock tests. | Failures remain isolated and bounded. | No browser health rendering until 9D. |
| AC-5 | No periodic coordinator reconciliation exists. | Drop a hint, advance reconciliation clock, assert adapter read. | Best-effort webhooks do not become a correctness dependency. | Uses a fake adapter rather than a live Hermes process. |
| AC-6 | No coordinator lifecycle exists. | Blocking adapter shutdown test and fresh-instance restart test. | Process exit is bounded and recovery does not depend on RAM state. | OS-level forced termination is covered later in 9F. |
| AC-7 | Coordinator wiring may alter receiver concurrency and server lifecycle. | Existing receiver tests, compile, and full suite. | Detects local regressions. | Existing unrelated dirty-fixture failures will be classified separately if still present. |
| AC-8 | The desired stock-Hermes migration has no implementation/removal ledger. | Inspect upstream v0.20.1 hook catalog and document candidate-by-candidate gates. | Prevents premature deletion and custom-fork lock-in. | Does not implement the later event expansions. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Official Hermes fetch and hook-catalog inspection | macOS; upstream `a90d536` / v0.20.1 | Pass | Upstream refs fetched; rich observer hooks confirmed. |
| Hermes fork divergence inspection | macOS git checkout | Pass | Fork is 26 commits ahead and 5,183 commits behind upstream; full merge deferred. |
| `python3 -m unittest tests.test_hermes_webhooks tests.test_hermes_webhook_routes tests.test_request_boundary -v` | macOS, Python 3.13, host loopback | Pass | 31 tests passed before implementation. |

### Test discussion and approval

- User questions and decisions: user approved storm, failure, reconciliation,
  lifecycle, route-latency, focused/full-suite, and two-reviewer coverage.
- Accepted coverage gaps: no visible UI check, live Hermes process, richer event
  ingestion, browser push, or old-code removal in 9C.
- Approved at: 2026-08-14, America/Los_Angeles.

## Implementation record

### Changes

- Added `hermes_event_refresh.py` with a fixed event matrix, bounded queue,
  coalescing, one worker, per-projection backoff, in-memory authoritative
  snapshots, periodic reconciliation, safe health evidence, and bounded stop.
- Replaced the inert server hint list with the coordinator while preserving
  dedupe-before-ack behavior and non-blocking webhook responses.
- Added server lifecycle ownership and local-only adapters for sessions,
  agents, attention, and a maximum of three verified Kanban task read-backs.
- Kept local webhook hints from refreshing a selected remote Kanban connection.
- Added package inventory entries for the new module.
- Added the coordinator to the maintained remote-Hermes adapter inventory.
- Added native-event migration/removal gates to the roadmap and review log.

### Deviations and decisions

- The user's native-Hermes objective is recorded as a compatibility constraint
  and follow-up migration ledger, not as permission to ingest sensitive hook
  families or remove fallbacks inside 9C.

### Stock Hermes migration matrix

| Mentat behavior | Current source/fallback | Stock Hermes webhook candidate | Authoritative refresh | Migration/removal gate |
| --- | --- | --- | --- | --- |
| Session list and active-agent presence | Dashboard refresh reads local state DB or the remote Sessions API | `on_session_start`, `on_session_end` | Existing `sessions_payload()` and derived `agents_payload()` | 9C coordinator, then browser push and live dropped-event convergence before reducing dashboard cadence |
| Subagent presence | Session observations and custom run progress | `subagent_start`, `subagent_stop` | Existing observed-agent/session reads | Live nested-delegation verification; keep reconciliation because hooks are droppable |
| Kanban task/run changes | Explicit task refresh and Home reconciliation | `kanban_task_claimed`, `kanban_task_completed`, `kanban_task_blocked`, worker lifecycle, task-updated, and dispatch-tick observers now present upstream | Existing capability-gated Kanban `get_task` read-back | Add a separate safe event allowlist and binding contract; prove exact/bounded refresh and mutation verification before reducing periodic reads |
| Turn completion and attention | Browser refresh plus Agent Console run polling | `on_session_end` | Sessions, active run state, attention, and linked task read-backs | Requires Mentat server-to-browser push; Hermes-to-Mentat delivery alone cannot replace browser polling |
| Token/context usage | Custom local `usage.json`; remote Runs event/terminal usage | `post_api_request` includes usage but also sensitive request/response context | Stock Runs/session usage API or a privacy-safe upstream usage observer | Do not ingest the current broad payload by default; require a minimal event contract, browser push, accounting parity, and dropped-event reconciliation before removing telemetry |
| Tool activity | Custom local `progress.jsonl`; remote Runs events | `post_tool_call` includes duration/status but also raw arguments/results | Stock run event stream or bounded tool-history read-back | Require metadata-only normalization or a safer upstream observer; prove redaction and ordering before removing the strict telemetry writer |
| LLM/model/provider display | Explicit inventory refresh and run/session metadata | Session hooks and `post_api_request` carry model/provider metadata | Existing profile/provider inventory and run identity read-backs | Webhook may wake inventory refresh but never applies a model switch; remove duplicate refreshes only after profile-scoped verification |
| Streaming/interim model output | Remote Runs SSE or local process capture | `on_stream_start`, `on_stream_delta`, `on_stream_end`, `on_interim_message` | Supported stock run stream | Raw text/reasoning is high sensitivity and high volume; do not route through the general webhook receiver without a separate product/privacy decision |
| Approvals, clarification, continuation, stop, provider switching, and artifacts | Custom-fork fixed API contracts | No webhook replacement; these are commands or authenticated API capabilities | Exact upstream operation plus post-action read-back | Audit against current upstream independently. Keep the fork until each required capability has parity, fallback, or approved removal |

Removal rule: a native event first becomes an additional wakeup, then passes
live convergence and rollback evidence, then may reduce fallback cadence, and
only after a soak period may make the superseded path eligible for deletion.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_hermes_event_refresh tests.test_hermes_webhooks tests.test_hermes_webhook_routes tests.test_request_boundary tests.test_packaging_cli -v` | macOS, Python 3.13, host loopback | Exit 0 | 66 passed | Coordinator, route, security, packaging, and boundary coverage. |
| `python3 -m unittest tests.test_hermes_event_refresh tests.test_local_server_lifecycle.LocalServerLifecycleTests.test_dashboard_cleanup_always_releases_connection_reservation -v` | macOS, Python 3.13 | Exit 0 | 10 passed | Reverification after fixing never-started worker cleanup. |
| `python3 -m py_compile server.py hermes_webhooks.py hermes_event_refresh.py` | macOS, Python 3.13 | Exit 0 | N/A | Syntax passed. |
| `git diff --check` | macOS git | Exit 0 | N/A | No whitespace errors. |
| `python3 -m unittest tests.test_hermes_event_refresh tests.test_hermes_webhooks tests.test_hermes_webhook_routes tests.test_request_boundary tests.test_packaging_cli tests.test_local_server_lifecycle -q` | macOS, Python 3.13, host loopback | Exit 0 | 97 passed | Final post-review focused regression suite. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | macOS, Python 3.13, host loopback | Exit 1 | 960 run; 7 failures; 4 skipped | Three cleanup subtest failures were caused by the first coordinator lifecycle implementation and were fixed. Four unrelated dirty roadmap/data fixture failures remained. |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13, host loopback | Exit 1 | 960 run; 4 failures; 4 skipped | Final pre-review code has no 9C failure. Remaining failures match the pre-implementation dirty roadmap/data fixture baseline. |
| `python3 -m unittest discover -s tests -q` in a detached clean worktree containing only the exact 9C code/docs patch | macOS, Python 3.13, host loopback | Exit 0 | 967 run; 4 skipped | Final code proves the slice independently of the user's unrelated dirty roadmap and fixture changes. |
| `uv build` followed by `python3 scripts/verify_python_artifacts.py <dist>` in the clean worktree | macOS, uv 0.11.30 | Exit 0 | Wheel and sdist verified | Both artifacts include `hermes_event_refresh.py`; private/runtime data exclusions remain enforced. |

### Rendered or manual behavior

- Not applicable; no visible UI change is in scope.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: complete uncommitted 9C slice on
  `codex/hermes-webhook-refresh-coordinator`.
- Verification evidence: focused suite, initial full suite with classified
  dirty-file failures, compile, and whitespace checks.
- Rendered artifacts: Not applicable.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | High | Yes | Local webhook adapters called selection-dependent session/agent helpers and could project a selected remote binding. | Yes | Use explicit local reads and reject error-shaped projections. |
| A-2 | High | Yes | Kanban reconciliation used a write-capable helper, accepted tasks without exact binding, and could churn or starve active work. | Yes | Make the adapter read-only, exact-binding, active-only, bounded, and priority ordered. |
| A-3 | Medium | Yes | A success in one projection cleared binding-wide degraded state while another projection remained failed. | Yes | Derive binding health from every active failed projection. |
| A-4 | Medium | Yes | A bounded stop could return while an adapter remained blocked. | Yes | Ensure every coordinator adapter is read-only and discard late results after stop. |
| A-5 | Medium | Yes | The final full suite had not been proven against an exact clean slice. | Yes | Run the exact patch in a detached clean worktree and verify built artifacts. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | High | Yes | Local event wakeups were not fully isolated from selected remote session/Kanban state. | Yes | Bind all current event adapters to `local-default`; exclude remote and legacy-unbound tasks. |
| B-2 | High | Yes | Error dictionaries returned by server reads could be stored as successful authoritative snapshots. | Yes | Validate projection shape and fail/back off on error-shaped payloads. |
| B-3 | Medium | Yes | Periodic Kanban reads included completed tasks and could persist timestamp/error changes every cycle. | Yes | Read at most three active tasks and never persist from event reconciliation. |
| B-4 | Medium | Yes | Shutdown release was unsafe if a lingering coordinator retained write authority. | Yes | Remove all write authority and suppress stopped-worker result publication. |
| B-5 | Medium | Yes | Packaging and complete-suite evidence needed clean-worktree proof. | Yes | Build/verify wheel and sdist after the 963-test clean run. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Binding isolation | Corroborated | Both reviewers maintained the finding after peer critique. | Fixed with direct local session reads, explicit local Kanban adapter construction, and exact `connection_binding_id` filtering. | Yes |
| Kanban mutation and churn | Corroborated | Both reviewers agreed the coordinator must never use delegation persistence. | Adapter now performs bounded `get_task` reads only, excludes terminal tasks, and prioritizes needs-input/running/queued. Tests assert no persistence on success or failure. | Yes |
| Mixed projection health | Unique A, accepted by B | Maintained. | Binding error clears only when no failed projection remains; degraded count is reported. | Yes |
| Error-shaped payload acceptance | Unique B, accepted by A | Maintained. | Shared validation rejects error, missing, and malformed payloads before snapshot replacement. | Yes |
| Bounded shutdown with lingering adapter | Corroborated with narrower final risk | Reviewers agreed read-only authority plus discarded late results addresses the state-corruption risk. | All server adapters are read-only; stopped workers cannot update snapshots. | Yes |
| Exact clean verification | Corroborated | Maintained as publication-blocking until complete. | Detached exact-slice run passed 963 tests with 4 skips; wheel and sdist passed the artifact verifier. | Yes |

### Reverification

- Focused tests: 97 passed after all Round 1 and Round 2 fixes.
- Full suite: exact-slice clean worktree passed 967 tests with 4 skips.
- Packaging: verified wheel and sdist.
- Next review round or gate result: Round 3 final re-review requested after
  resolving Round 2 blockers.

### Round 2 findings and disposition

| ID | Severity | Blocking | Finding | Disposition |
| --- | --- | --- | --- | --- |
| R2-A | Medium | Yes | Local Kanban subprocess inherited ambient `HERMES_HOME`, which could differ from Mentat's configured runtime. | Fixed by passing an explicit environment derived from `os.environ` with configured `HERMES_HOME`; regression test covers configured-versus-ambient homes. |
| R2-B1 | High | Yes | Generic projection validation accepted malformed envelopes, and attention reads could turn malformed source files into a successful empty projection. | Replaced with projection-specific session/agent validators; attention now strictly reads and validates both source lists. |
| R2-B2 | Medium | Yes | Kanban accepted an `ok` response with a different task ID or an absent/unknown status. | Require exact task identity, an allowlisted status, and list-shaped runs/comments before projection. |

### Round 3 final packet

- Diff reviewed: complete current uncommitted slice after all Round 2 fixes.
- Verification evidence: 97 focused tests, 967-test clean full suite with 4
  skips, verified final wheel and sdist, compile and whitespace checks.
- Reviewer A: no actionable findings; all prior blockers resolved; publication
  ready.
- Reviewer B: no blocking findings; all prior blockers resolved; publication
  ready. One accepted low-risk gap remains: malformed `runs` and `comments`
  list branches are enforced in code but not each exercised directly.
- Reconciliation: no reviewer dissent. The low-risk test gap is documented and
  deferred because the checks are explicit, adjacent malformed Kanban paths are
  covered, and focused/full/package verification is green.

## Documentation updates

- Roadmap: records upstream v2026.8.13 and adds native-event migration and
  fallback-retirement gates without deleting current compatibility paths.
- Changelog: Not currently targeted.
- Architecture/operator docs: `REMOTE_HERMES.md` inventories the new adapter;
  this log records the stock-Hermes event/read-back/removal matrix.
- Project/session notes: This review log is the project record.
- Documentation verification: beta contract and complete clean suite pass.

## Publication gate

- Proposed files: `hermes_event_refresh.py`, `server.py`, `pyproject.toml`,
  `scripts/verify_python_artifacts.py`, `tests/test_hermes_event_refresh.py`,
  `tests/test_hermes_webhook_routes.py`, `tests/test_packaging_cli.py`,
  `REMOTE_HERMES.md`, and this review log. `ROAD_TO_BETA.md` contains
  pre-existing user-owned edits in the same added Milestone 9 hunk, so it is
  intentionally left wholly unstaged rather than risking publication of
  unrelated work. The stock-Hermes migration/removal matrix remains published
  in this review log. User-owned data fixtures and unrelated untracked changes
  must remain unstaged.
- Branch and base: `codex/hermes-webhook-refresh-coordinator` based on
  `codex/hermes-webhook-receiver-foundation`.
- Commit message: `feat: add Hermes webhook refresh coordinator`.
- PR title: `feat: add Hermes webhook refresh coordinator`.
- PR summary: consume verified native Hermes lifecycle events as bounded
  wakeups for local authoritative session, agent, attention, and Kanban reads;
  preserve reconciliation/backoff/fallbacks and document the path away from
  custom-fork telemetry.
- Unresolved risks: live stock-Hermes delivery and browser push remain later
  slices; `runs`/`comments` malformed-list branches lack direct unit cases but
  fail closed in implementation. No reviewer considers this blocking.
- User authorization and scope: the publication packet was presented after
  Round 3. The active user goal then explicitly granted standing feature
  approval and directed GitHub to be updated as milestones are crossed. This
  is recorded as the user's process exception authorizing selective staging,
  commit, push, and a ready PR for this completed slice; it does not authorize
  staging unrelated dirty files.
- Commit hash: None.
- Ready PR URL: None.

## Outcome review

- Classification: Ready for user outcome acceptance; publication pending
  explicit user approval.
- Acceptance criteria summary: AC-1 through AC-8 pass with focused, clean full
  suite, artifact, source, and two-reviewer evidence.
- Potential bugs or untested paths: no live Hermes process test; no direct
  malformed-list cases for Kanban `runs`/`comments`; browser push is out of
  scope.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: Hermes 0.19/unconfigured systems
  keep existing behavior; event hints do not replace authoritative reads or
  polling fallbacks. Coordinator removal cleanly restores receiver-only
  behavior without changing Hermes-owned state.
- User decision: Pending.
- Next slice authorized: No
