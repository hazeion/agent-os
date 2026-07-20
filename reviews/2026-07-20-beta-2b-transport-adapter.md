# Feature Slice Review: Transport-Neutral Hermes Console Boundary

Status: Implemented, locally verified, and independently reviewed; publication pending
Slice: `beta-2b-transport-adapter`
Date: `2026-07-20`
Review log: `reviews/2026-07-20-beta-2b-transport-adapter.md`

## Slice contract

### Goal

Introduce the transport-neutral boundary that later remote Console work can
implement, while keeping local Hermes Console behavior exact and ensuring a
selected remote connection can never fall through to the local CLI.

### In scope

- A small typed Hermes Console transport interface selected from the existing
  owner-private local/remote connection record.
- A local implementation that owns the established fixed CLI command,
  environment, working directory, process launch, and current-binding check.
- A remote placeholder that advertises no Console execution capability and
  fails closed without calling local Hermes or a remote run endpoint.
- Agent Console summary/start integration through the selected transport.
- Safe `transport_mode` and opaque `connection_binding_id` fields on new and
  retained run summaries.
- Blocking connection selection confirmation while any Console run is queued,
  running, or cancelling.
- Focused safety/compatibility tests, full local and hosted verification, two
  independent adversarial reviews, documentation, ready PR, and merge.

### Out of scope

- Remote prompts, streaming, runs, approvals, cancellation, sessions,
  clarifications, attachments, Context Packs, profiles, providers, Kanban,
  skills, cron, or any new Hermes mutation/read endpoint.
- A Settings UI or any claim that remote Console is operational.
- Refactoring unrelated local profile/provider/Kanban adapters.
- Persisting endpoints, credentials, local paths, launch arguments, or process
  details in public run history.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | One adapter selector returns a local or remote implementation bound to the exact current opaque connection ID; changed selection fails revalidation. | Adapter unit and binding-race tests | Pass |
| AC-2 | Local launch argv, profile/session/image behavior, environment, working directory, process options, events, and successful response handling remain exact; failed child output is replaced with a bounded status error. | Existing Console tests plus focused launch tests | Pass |
| AC-3 | When remote is selected, Console summary/start do not inspect or launch local Hermes and return a bounded unavailable state without a network execution call. | Patched local-call/Popen negative tests | Pass |
| AC-4 | New and retained run summaries carry only validated `transport_mode` and opaque `connection_binding_id`; legacy history safely defaults to local. | Run-history round-trip and malformed-field tests | Pass |
| AC-5 | Connection confirmation fails before mutation while any Console run is active; preview and connection testing remain available. | Route handler active-run tests | Pass |
| AC-6 | No endpoint, credential, local path, environment, argv, or private process detail crosses run/public/history payloads. | Recursive secret/path absence tests | Pass |
| AC-7 | Focused/full/static checks, supported hosted matrix, docs, and two independent adversarial reviews clear on the final diff. | Verification and review record | Pending |

### Constraints and recovery

- Safety: selection is read through the 2A owner-private boundary; remote mode
  cannot silently use the local CLI; every launch revalidates its binding.
- Compatibility: Python 3.11-3.13 and macOS/Windows/Linux standard-library
  behavior; existing local tests and public payload keys remain compatible.
- Rendered behavior: no frontend code is planned. Existing local UI is
  unchanged; selected remote mode receives an honest unavailable message.
- Rollback or recovery: select local through the existing exact confirmation
  flow. This slice creates no new durable authority or migration.
- Documentation targets: `ROAD_TO_BETA.md`, `REMOTE_HERMES.md`,
  `ARCHITECTURE.md`, `CHANGELOG.md`, and this log. The README stays concise and
  changes only if first-run guidance materially changes (not expected).
- Version-control strategy: branch `codex/beta-2b-transport-adapter` from merged
  `main`; ready PR to `main`, squash merge after exact-head hosted CI.

### Scope discussion and approval

- Recommendation and rationale: move only Agent Console launch selection behind
  the first typed transport boundary. It is the next mandatory remote path and
  proves local preservation plus remote fail-closed behavior without inventing
  any upstream operation.
- Alternatives considered: a broad rewrite of every Hermes adapter would make
  regression review too large; an unused interface would not prove behavior;
  routing remote Console now would skip the ordered boundary and review gate.
- User decisions: standing authorization requires immediate continuation through
  bounded reviewed slices. README remains a light, concise first-user welcome.
- Approved at: `2026-07-20` through standing authorization.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Console code directly builds local process state. | Selector, public summary, and changed-binding revalidation tests. | Authority is explicit and endpoint-bound. | Remote API execution follows in 2C. |
| AC-2 | Local launch is embedded in `server.py`. | Exact command/env/Popen tests plus existing Console suite. | Refactor preserves local behavior. | Does not call a real model in CI. |
| AC-3 | Remote selection currently does not govern Console. | Remote summary/start tests that make local discovery/Popen explode if touched. | No local fallback or premature remote call. | UI uses existing error rendering. |
| AC-4 | History has no transport binding. | Current/legacy/malformed summary round trips. | Durable runs cannot lose or forge binding metadata. | No remote run exists yet. |
| AC-5 | Connection confirmation ignores active Console state. | Queued/running/cancelling block and completed allow tests. | Active work cannot cross selection. | Cross-process Console remains a single server concern. |
| AC-6 | Launch internals are currently server-local by convention. | Recursive payload/history absence assertions. | New boundary stays secret/path-free. | Process memory necessarily contains launch data. |
| AC-7 | No 2B evidence exists. | Focused/full/static/hosted checks and two reviewers. | Regression and independent review gates. | Live remote host remains later exit evidence. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13 | Pass | Merged 2A head: 603 tests, four native-platform skips. |
| GitHub Actions `29710960619` | Supported matrix | Pass | Exact merged-PR head: all 42 jobs passed. |
| Source inspection of Console launch and history | Repository | Gap confirmed | Local launch is embedded in `server.py`; no binding metadata or selected transport boundary exists. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts this smallest
  ordered 2B boundary and its explicit exclusions.
- Accepted coverage gaps: no live Hermes/model dependency and no remote run API
  until the separately reviewed 2C slice.
- Approved at: `2026-07-20` through standing authorization.

## Implementation record

### Changes

- Added `hermes_transport.py` with a typed, binding-aware Console interface, an
  exact local CLI adapter, and an explicit unavailable remote adapter.
- Routed Console summary, start, and worker launch through the selected
  transport without changing established local request validation, process,
  event, successful response, attachment, or artifact behavior.
- Serialized connection confirmation against active-run creation and
  revalidated the opaque selection before both queue and process launch.
- Added validated transport metadata to retained run summaries with legacy
  defaults and malformed-record refusal.
- Reduced local process-launch exceptions to a bounded public error.

### Deviations and decisions

- The binding is revalidated twice—before queue and immediately before
  launch—because the first protects attachment/run creation and the second
  protects the asynchronous worker handoff.
- Local CLI availability remains checked after the existing request validation
  steps so installations without Hermes retain the prior 400-versus-503 API
  behavior.
- Failed child-process stdout/stderr is intentionally no longer exposed as a
  public error. Mentat returns only the exit status, preventing credentials,
  UNC paths, and uncommon absolute paths from crossing the Console/history
  boundary while successful model responses remain unchanged.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m py_compile hermes_transport.py server.py agent_run_history.py` | macOS, Python 3.13 | 0 | Pass | Import/syntax check. |
| Focused Console, transport, history, event, and artifact suites | macOS, Python 3.13 | 0 | 63 pass | Exact local compatibility, binding/race, recovery, privacy, and remote fail-closed coverage. |
| `python3 -m unittest -v tests.test_beta_contract tests.test_hermes_transport` | macOS, Python 3.13 | 0 | 25 pass | Documentation and adapter contract. |
| `git diff --check` | Repository | 0 | Pass | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13 | 0 | 619 pass, 4 skip | Final corrected diff green. |

### Rendered or manual behavior

- No frontend files changed. Local payload behavior is covered by the existing
  Console suite; remote summary/start return a bounded unavailable state and do
  not call local discovery or process launch.

## Adversarial review

Two independent read-only reviewers initially found cross-binding session and
launch gaps, connection-storage and summary races, run-visibility recovery,
failed-process output leakage, and malformed-save acceptance. The fixes now:

- bind session resume and worker launch to the exact transport identity;
- normalize connection-storage failures and keep runs visible;
- serialize summary discovery against selection confirmation;
- return no raw failed-process stdout/stderr; and
- reject explicitly malformed transport metadata on save and load.

All focused regressions and the full suite pass. Final zero-finding re-review is
complete: both independent reviewers reported zero findings on the corrected
complete diff. The final review also exercised the dedicated connection/run
lock ordering repeatedly under slow discovery.

## Documentation updates

- Roadmap: 2B marked complete; 2C remote Console runs/events is next.
- Changelog: Added the adapter, retained binding metadata, and safety behavior.
- Architecture/operator docs: Documented the exact local boundary and explicit
  remote unavailable state in `ARCHITECTURE.md` and `REMOTE_HERMES.md`.
- Project/session notes: this review log.
- Documentation verification: beta contract suite passes. README unchanged
  because first-run installation behavior did not change.

## Publication gate

- Proposed files: `hermes_transport.py`, `server.py`, `agent_run_history.py`,
  the focused Console/history/contract tests, `ARCHITECTURE.md`,
  `REMOTE_HERMES.md`, `ROAD_TO_BETA.md`, `CHANGELOG.md`, and this review log.
- Branch and base: `codex/beta-2b-transport-adapter` to `main`.
- Commit message: `Add Hermes transport adapter boundary`.
- PR title: `Add Hermes transport adapter boundary`.
- PR summary: preserve local Console through a binding-aware adapter and fail
  closed for selected remote mode before remote execution exists.
- Unresolved risks: mandatory remote run/session and upstream blockers remain.
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
