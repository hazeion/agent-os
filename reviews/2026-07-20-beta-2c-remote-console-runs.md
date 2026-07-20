# Feature Slice Review: Remote Hermes Console Runs and Events

Status: Local verification and adversarial review complete; publication pending
Slice: `beta-2c-remote-console-runs`
Date: `2026-07-20`
Review log: `reviews/2026-07-20-beta-2c-remote-console-runs.md`

## Slice contract

### Goal

Make plain, default-profile Agent Console turns work through one selected remote
Hermes host using only its authenticated, capability-advertised Runs API, while
preserving exact local behavior and failing closed on unsupported lifecycle
states.

### In scope

- Validate the exact advertised run submission, status, SSE-event, and stop
  operations before remote Console becomes actionable.
- Add fixed, bounded server-side client operations for `POST /v1/runs`,
  `GET /v1/runs/{run_id}`, `GET /v1/runs/{run_id}/events`, and
  `POST /v1/runs/{run_id}/stop`; no generic request method.
- Submit one plain prompt to the selected endpoint's active/default profile,
  bind the Mentat/upstream run to the exact connection identity, and normalize
  bounded deltas, tool progress, lifecycle, output, usage, and terminal state.
- Fall back to bounded status polling when SSE is interrupted; never infer
  completion from a disconnected stream.
- Route explicit cancellation through remote stop and verify terminal state.
- If an approval request appears, stop the run and report that approval response
  is not available in this slice; never auto-approve or leave a hidden wait.
- Keep run IDs, endpoint details, credentials, upstream errors, headers, paths,
  and unbounded model/tool output out of public or retained payloads except for
  the existing bounded user-visible response/event text.
- Focused compatibility/security tests, full local and hosted verification, two
  independent adversarial reviews, docs, ready PR, and merge.

### Out of scope

- Approval-response UI/operations, session list/replay/resume/search, remote
  profile inventory, non-default profile routing, attachments, Context Packs,
  inline images, artifacts, provider/model switching, skills, Kanban, cron, or
  arbitrary remote requests.
- Replaying a local session or run against remote Hermes, or vice versa.
- Browser-to-Hermes requests, SSH, remote shells, dashboard-token reuse, direct
  remote files/databases, retries that could duplicate run submission, or
  claiming full remote parity.
- Durable persistence of upstream run IDs and crash-time control after an
  abrupt process kill. Upstream IDs remain memory-only; restored remote runs
  are marked interrupted and partial because their upstream state cannot be
  verified. A separately reviewed owner-private recovery ledger would be
  required to close that gap without violating this slice's retention scope.
- README changes; first-run installation is unchanged.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Remote Console is actionable only when authenticated discovery advertises the exact required booleans and fixed endpoint templates; missing/changed capability fails closed. | Capability schema and negative routing tests | Pass locally |
| AC-2 | A valid plain prompt creates exactly one upstream run, records only a private bound reference, consumes bounded SSE events, and completes only from a validated terminal status/output. | Client/transport/server lifecycle tests | Pass locally |
| AC-3 | Interrupted or malformed SSE never claims completion; status polling either verifies a bounded terminal result or returns a bounded failure. | Stream interruption/schema/timeout tests | Pass locally |
| AC-4 | Remote cancellation calls the fixed stop operation once, verifies the response and eventual terminal status, and cannot affect a different binding/run. | Cancellation and stale-binding tests | Pass locally |
| AC-5 | Approval requests are visible but never auto-approved; Mentat stops the upstream run and reports the unsupported response state clearly. | Approval-event fail-closed tests | Pass locally |
| AC-6 | Local argv/env/cwd/process/event/success behavior remains exact, while remote mode never resolves or launches the local CLI. | Existing local suite plus local-call/Popen negative tests | Pass locally |
| AC-7 | Secrets, endpoints, upstream IDs/errors/headers, private paths, and unbounded payloads do not cross public/history/log surfaces. | Recursive absence and bounds tests | Pass locally |
| AC-8 | Focused/full/static checks, supported hosted matrix, docs, and two independent adversarial reviews clear on the final diff. | Verification and review record | Pending |

### Constraints and recovery

- Safety: every operation is selected from owner-private state, capability
  matched, connection-bound, fixed-method/fixed-path, TLS verified, size/time
  bounded, schema validated, and secret-free at public boundaries.
- Compatibility: Python 3.11-3.13 and macOS/Windows/Linux standard-library
  behavior; local mode remains the established CLI transport.
- Rendered behavior: reuse the existing Console states and events. Remote mode
  exposes one default endpoint agent only when ready and clear unavailable
  messages otherwise; no new settings surface.
- Rollback or recovery: select local through the exact confirmation flow. A
  remote failure terminates or verifies the upstream run where supported and
  leaves a bounded failed/cancelled Mentat record. Graceful shutdown stops and
  verifies accepted work; abrupt process death is the explicit limitation above.
- Documentation targets: `ROAD_TO_BETA.md`, `REMOTE_HERMES.md`,
  `ARCHITECTURE.md`, `CHANGELOG.md`, and this log. README remains unchanged.
- Version-control strategy: branch `codex/beta-2c-remote-console-runs` from
  merged `main`; ready PR to `main`, squash merge after exact-head hosted CI.

### Scope discussion and approval

- Recommendation and rationale: submission, event/status reconciliation, and
  stop belong in one slice because a remotely accepted run must remain visible,
  cancellable, and terminally verified. Approval response stays separate, but
  approval events are handled safely by stopping rather than waiting invisibly.
- Alternatives considered: submission-only can orphan work; polling-only loses
  the structured progress contract; implementing sessions/attachments/approval
  UI together would make the review surface too broad.
- User decisions: standing authorization requires immediate continuation
  through bounded reviewed slices. README remains a light, concise first-user
  welcome and changes only for material installation changes.
- Approved at: `2026-07-20` through standing authorization.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Discovery keeps booleans but does not validate run endpoint templates for use. | Exact capability matrix plus missing/changed endpoint tests. | No undocumented or mismatched route is called. | Uses fake HTTPS connections in unit tests. |
| AC-2 | Remote adapter is intentionally unavailable. | One-submit lifecycle with bounded SSE/status/output normalization. | Accepted remote work maps to one bound Mentat run. | No live model in CI. |
| AC-3 | No run stream parser/reconciliation exists. | Oversize, malformed, timeout, disconnect, and terminal polling cases. | Transport uncertainty cannot become false success. | Network partitions are simulated. |
| AC-4 | Cancel only terminates a local child process. | Fixed stop/read-back and wrong-binding negative tests. | Cancellation targets only the authorized upstream run. | Approval response remains later. |
| AC-5 | Approval events are not represented remotely. | Approval event triggers stop and bounded failure. | No automatic authorization or hidden indefinite wait. | Operator cannot answer approval yet. |
| AC-6 | Local adapter is verified, remote execution absent. | Existing exact local tests and exploding local-call patches in remote mode. | Remote never falls through to local. | Local real-model invocation remains outside CI. |
| AC-7 | 2A/2B protect discovery/launch boundaries only. | Recursive secret/endpoint/ID/path absence and retention bounds. | New run surfaces remain public-safe. | Successful user-requested response text remains intentionally visible. |
| AC-8 | No 2C evidence exists. | Focused/full/static/hosted checks and two reviewers. | Regression and independent review gates. | Live approved host remains beta-exit evidence. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13 | Pass | Merged 2B head: 619 tests, four native-platform skips. |
| GitHub Actions `29711996211` | Supported matrix | Pass | Exact merged-PR final head: all 42 jobs passed. |
| Primary Hermes API docs/source inspection | Upstream `NousResearch/hermes-agent` | Gap confirmed | Runs API supplies submission/status/SSE/stop; Mentat has no remote execution adapter yet. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts this smallest
  lifecycle-safe 2C boundary and its explicit exclusions.
- Accepted coverage gaps: no live remote host/model in CI and no approval
  response, sessions, or content transfer until separately reviewed slices.
- Approved at: `2026-07-20` through standing authorization.

## Implementation record

### Changes

- Added exact capability endpoint validation plus fixed, authenticated,
  bounded submit/status/SSE/stop client operations in `remote_hermes.py`.
- Activated the remote Console transport only after capability discovery while
  leaving the local CLI adapter unchanged.
- Added default-profile remote queue/run/event/status/cancel/shutdown lifecycle
  handling with exact connection binding, private upstream identity, one-shot
  stop claiming, terminal reconciliation, approval fail-closed behavior, and
  bounded history retention.
- Persisted normalized usage and partial-failure markers in private Console
  history without changing the compatible schema version.
- Added focused remote lifecycle, security, compatibility, retention, and
  history tests.

### Deviations and decisions

- Upstream emits SSE keepalive comments every 30 seconds, so only the event
  stream uses a 35-second read timeout; discovery and JSON operations retain the
  existing five-second default. Each SSE attachment also has a 30-minute
  wall-clock bound before Mentat switches to status reconciliation.
- Mentat claims at most one stop attempt per bound run. An uncertain stop is
  retained as a partial failure rather than retried, because retry safety is not
  advertised.
- Upstream identifiers remain memory-only. Graceful shutdown is bounded and
  verified, while abrupt process death restores the Mentat summary as partial
  rather than pretending the upstream run was stopped.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m py_compile remote_hermes.py hermes_transport.py agent_run_history.py server.py tests/test_remote_console_runs.py` | macOS, Python 3.13 | Exit 0 | Pass | Static syntax check. |
| `python3 -m unittest tests.test_remote_console_runs -v` | macOS, Python 3.13 | Exit 0 | 19 passed | Fixed paths, timeout, binding, lifecycle, cancellation races, approval, privacy, retention, shutdown, and history. |
| `python3 -m unittest tests.test_remote_console_runs tests.test_remote_hermes tests.test_hermes_transport tests.test_agent_run_history tests.test_agent_run_events tests.test_private_console_state tests.test_profile_aware_console tests.test_agent_console_attachment_runs tests.test_beta_contract -v` | macOS, Python 3.13 | Exit 0 | 130 passed | Remote foundation plus affected Console, private-state, profile, attachment, and beta-contract compatibility. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13 | Exit 0 | 638 passed, 4 skipped | Full repository suite after updating the completed-slice roadmap assertion; skips require native Windows behavior. |

### Rendered or manual behavior

- Existing Console UI contract only. Remote payload exposes one ready default
  agent when capabilities validate, keeps retained runs visible on failure, and
  uses existing queued/running/completed/failed/cancelled surfaces.

## Adversarial review

- Safety/privacy reviewer: challenged accepted-run cleanup, submission
  uncertainty, approval handling, identifier/endpoint reflection, shutdown,
  response bounds, and the proposed durable recovery scope. The implementation
  now performs one-shot stop plus terminal verification, reports unverifiable
  accepted work as partial, rejects reflected private identity, keeps upstream
  IDs memory-only, and documents abrupt-process-death recovery as deferred.
- Compatibility/lifecycle reviewer: challenged stop-response compatibility,
  SSE timeout and complexity bounds, cancellation authority, worker/shutdown
  races, and late events after authoritative reconciliation. The implementation
  now accepts the documented optional stop identity only when exact, bounds
  stream duration and parsing, preserves verified terminal state, starts and
  registers workers with a fail-closed shutdown race path, and ignores events
  after a run leaves `running`.
- All ranked findings were fixed with focused regressions. Both independent
  reviewers reported zero findings on the final exact diff.

## Documentation updates

- Roadmap: records 2C default-profile run lifecycle complete and names the next
  remote gaps.
- Changelog: records the new remote lifecycle and fail-closed behavior.
- Architecture/operator docs: distinguish implemented runs/events/status/stop
  from pending sessions, approval responses, content, profiles, and Kanban.
- Project/session notes: this review log.
- README: intentionally unchanged because installation did not change.
- Documentation verification: full suite and contract tests pass locally.

## Publication gate

- Proposed files: `remote_hermes.py`, `hermes_transport.py`, `server.py`,
  `agent_run_history.py`, focused and contract tests,
  architecture/roadmap/changelog docs, and this review log. No tracked fixtures
  or README changes.
- Branch and base: `codex/beta-2c-remote-console-runs` to `main`.
- Commit message: `Add remote Hermes Console runs`.
- PR title: `Add remote Hermes Console runs`.
- PR summary: capability-gated, binding-aware remote run submission, bounded
  events/status reconciliation, and verified stop without local fallback.
- Unresolved risks: approval response, sessions, content transfer, profile
  inventory, mandatory upstream Kanban, and durable abrupt-crash run recovery
  remain.
- User authorization and scope: standing approval recorded.
- Commit hash: Pending.
- Ready PR URL: Pending.

## Outcome review

- Classification: Pending.
- Acceptance criteria summary: Pending.
- Potential bugs or untested paths: Pending.
- Remaining reviewer dissent: Pending.
- Compatibility/migration/rollback concerns: Pending.
- User decision: standing authorization requires completion and continuation.
- Next slice authorized: Yes, after merge.
