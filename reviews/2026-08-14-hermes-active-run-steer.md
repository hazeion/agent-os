# Feature Slice Review: Hermes Active-Run Steer

Status: Ready PR open; CI correction verified locally
Slice: `hermes-active-run-steer`
Date: `2026-08-14`
Review log: `reviews/2026-08-14-hermes-active-run-steer.md`

## Slice contract

### Goal

Let a user type bounded text into the Mentat Agent Console while a compatible
remote Hermes run is active and send that text through Hermes' fixed,
capability-advertised Runs steer operation.

### In scope

- Recognize `run_steer` only with the exact authenticated
  `POST /v1/runs/{run_id}/steer` contract.
- Keep the existing Console composer available during a verified steer-capable
  remote run, with explicit Steer labeling and text-only behavior.
- Bind steering to the current Mentat run, remote run, connection, profile,
  transport instance, active state, and a monotonic Mentat control revision.
- Verify the run before steering, validate Hermes' exact acceptance response,
  and read the same run back afterward.
- Report an accepted-but-unverified operation as a partial failure without
  claiming success.
- Add `/steer <guidance>` to Mentat's versioned command manifest as a second UI
  entry point to the same guarded operation.
- Keep ordinary Send, attachments, and provider/session mutations locked while
  any run is active; keep Stop separate.
- Document the local/remote transport decision and future compatibility path.

### Out of scope

- Active-turn redirect/replacement semantics.
- Local one-shot process steering or a new local control channel.
- Steering with files, images, Context Packs, or persisted steer text.
- Queued follow-up messages and offline drafts.
- Changes to Hermes itself or direct writes to Hermes-owned files.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Mentat trusts steering only when `run_steer` and its exact fixed endpoint are advertised. | Remote contract tests | Pass |
| AC-2 | During a steer-capable active remote run, the Console text box remains writable and submits an explicitly labeled text-only Steer action; ordinary Send and attachments remain unavailable. | Frontend tests and computer-use | Pass |
| AC-3 | `/steer <guidance>` is a fixed Mentat command that dispatches the same operation and is unavailable without a compatible active run. | Manifest and UI tests | Pass |
| AC-4 | The server binds each request to the live run/connection/profile/transport/control revision and rejects stale, local, terminal, concurrent, malformed, or oversized requests. | Server integration tests | Pass |
| AC-5 | Success requires exact Hermes acceptance plus post-action read-back; accepted-but-unverified results are explicit partial failures. | Client and server negative-path tests | Pass |
| AC-6 | Neither steer text nor private remote identifiers are persisted or returned; only a bounded status event is retained. | Persistence/redaction tests | Pass |
| AC-7 | Existing stop, approval, clarification, session, attachment, and normal-send behavior remains compatible. | Focused and full regression suites | Pass |
| AC-8 | Rendered desktop and narrow layouts remain usable and Lighthouse scores 100 in all four categories. | Computer-use, screenshots, Lighthouse | Pass |

### Constraints and recovery

- Safety: fixed authenticated endpoint only; text capped at 20,000 characters;
  no shell interpolation, attachments, remote identifiers, or steer text in
  public/persisted records.
- Compatibility: local and non-advertising transports remain fail-closed with
  the busy composer locked. Hermes steering is guidance, not redirect.
- Rendered behavior: the existing composer visibly changes from Send to Steer
  only for a compatible active run, with an explanatory placeholder and
  accessible label.
- Rollback or recovery: removing the optional capability path restores the
  existing composer lock; a partial failure tells the operator that Hermes may
  have accepted guidance and does not retry automatically.
- Documentation targets: `MILESTONE_9_WEBHOOK_IMPLEMENTATION_PLAN.md`,
  `ROAD_TO_BETA.md`, `ARCHITECTURE.md`, and this review log.
- Version-control strategy: branch `codex/hermes-active-run-steer`, stacked on
  accepted 9D branch `codex/hermes-webhook-health-setup`; ready PR targets the
  9D branch so the slice diff remains isolated.

### Scope discussion and approval

- Recommendation and rationale: use Hermes' native Runs steer primitive while
  retaining Mentat's fixed-operation, read-back, and fail-closed boundaries.
- Alternatives considered: redirect was rejected as an inaccurate product
  claim; a separate second textarea was superseded by the user's requirement
  that the Agent Console itself remain writable while a run is active.
- User decisions: accepted steer semantics; required typing during an active
  run; requested a `/steer` command path; authorized progress under the
  reviewed-feature workflow.
- Approved at: `2026-08-14` in this Codex task.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | `run_steer` is unknown to Mentat. | Capability permutations and exact endpoint assertions. | No guessed or arbitrary steer route is trusted. | Mock transport cannot prove a deployed Hermes host. |
| AC-2 | The composer is disabled for every active run. | DOM contract tests plus computer-use during a simulated active run. | Writable, labeled steer mode and locked attachments. | Browser simulation does not execute a paid LLM turn. |
| AC-3 | `/steer` is absent from the manifest. | Manifest normalization, argument, and dispatch tests. | Fixed allowlist and shared handler path. | Does not prove upstream acceptance alone. |
| AC-4 | No steer server route exists. | State/binding/revision/race/validation integration tests. | Stale and unsafe mutations fail closed. | Thread scheduling is deterministic test simulation. |
| AC-5 | No native steer client or read-back exists. | Exact request/response tests and post-read failure simulation. | Success and partial-failure claims match evidence. | Upstream can accept text internally after acknowledging it; Mentat cannot inspect model internals. |
| AC-6 | No steer persistence policy exists. | Snapshot/history serialization and secret-reflection assertions. | Text and private IDs stay server-only. | In-memory request text necessarily exists during the call. |
| AC-7 | Existing controls could regress. | Remote Console focused suite and full unit suite. | Existing tested behavior remains intact. | Full suite covers repository-defined scenarios only. |
| AC-8 | No steer rendering exists. | Desktop/narrow computer-use plus Lighthouse. | Visible usability and required quality scores. | Visual checks cover representative viewports. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Source inspection | macOS, branch `codex/hermes-active-run-steer` | Gap confirmed | `renderAgentConsole` disables the prompt whenever any run is active; no `run_steer` capability, route, client method, or `/steer` command exists. |
| Official Hermes source inspection | NousResearch/hermes-agent `main`, 2026-08-14 | Contract confirmed | Hermes advertises `run_steer`, accepts text at the fixed Runs endpoint, emits `run.steered`, and updates pollable status. |

### Test discussion and approval

- User questions and decisions: user confirmed that active-run steering must
  leave the Agent Console writable and asked whether it already existed; the
  current gap was reported before implementation.
- Accepted coverage gaps: no live paid-provider steer is required; exact
  transport mocks plus computer-use of the Mentat workflow are accepted.
- Approved at: `2026-08-14` in this Codex task.

## Implementation record

### Changes

- Added strict remote `run_steer` discovery, exact authenticated request and
  response validation, text-free `run.steered` normalization, and bounded
  public error handling.
- Added a revision-, profile-, transport-, connection-, state-, and run-bound
  server operation with pre-action status verification and post-action
  read-back. Deterministic rejections are not retried; accepted or possibly
  accepted operations that cannot be verified return an explicit partial
  failure.
- Added the fixed `/steer <guidance>` manifest entry and shared frontend
  handler. A compatible active remote run reuses the existing composer in an
  explicit Steer mode while attachment, profile, provider, model, and session
  controls remain locked.
- Kept steer text and private upstream run identifiers out of public snapshots
  and retained history. Route and SSE acknowledgements are deduplicated.
- Added focused transport, server, manifest, frontend, privacy, stale-state,
  concurrency, partial-failure, and neighboring runtime-switch regression
  coverage.
- Updated the Milestone 9 plan and architecture contract; retained a compact
  Lighthouse evidence artifact.

### Deviations and decisions

- The approved first-class Steer action will reuse the existing composer in an
  explicit mode instead of adding a second textarea, per the user's clarified
  active-console requirement.
- The user later proposed broader Hermes-like slash-command parity and active
  steer attachments, then explicitly deferred implementation. These remain
  follow-ups: commands must use Mentat's versioned fixed-handler allowlist, and
  attachments require an upstream versioned, verifiable steer-media contract.
- `ROAD_TO_BETA.md` was not edited because it already contains unrelated local
  user changes. The persistent plan and architecture documents carry the 9E
  decision without overwriting that work.
- During expanded verification, the new handler was found to have displaced
  the existing remote approval/clarification fallback by a few lines. The
  fallback was restored before review and the neighboring regression suite was
  rerun.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m py_compile server.py remote_hermes.py hermes_transport.py command_manifest.py` | Working tree | 0 | Pass | Python syntax gate. |
| `node --check public/core.js` and `node --check public/app.js` | Working tree | 0 | Pass | JavaScript syntax gate. |
| `git diff --check` | Working tree | 0 | Pass | No whitespace errors. |
| `python3 -m unittest tests.test_active_run_steer tests.test_remote_console_runs tests.test_agent_console_runtime_switch_ui tests.test_command_manifest tests.test_frontend_workflow_feedback -q` | Working tree | 0 | 88 pass, 0 fail, 0 skip | Includes Stop-versus-Steer, post-acceptance authority, server staging, and Managed Agent boundary tests plus the restored neighboring response/runtime behavior. |
| `python3 -m unittest tests.test_active_run_steer tests.test_remote_console_runs tests.test_agent_console_runtime_switch_ui tests.test_command_manifest tests.test_frontend_workflow_feedback tests.test_agent_console_attachments tests.test_agent_console_attachments_ui tests.test_agent_console_attachment_runs tests.test_context_packs tests.test_context_pack_ui_contract -q` | Working tree | 0 | 128 pass, 0 fail, 0 skip | Adds attachment upload/workspace/run, in-flight staging, Managed Agent action, and Context Pack UI/server regressions. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | Clean 9D clone plus only 9E files; host execution for loopback integration tests | 0 | 1,004 pass, 0 fail, 4 skip | Final post-review-fix run; all runnable tests passed. |
| Initial full suite in the working tree | Working tree with preserved user changes | 1 | 991 pass, 4 fail, 5 error, 5 skip | Five errors were sandbox loopback denials; three failures came from pre-existing modified `ROAD_TO_BETA.md`/tracked data; one obsolete nearby source assertion was corrected. This run is diagnostic, not the release gate. |

### Rendered or manual behavior

- In-app browser computer-use used a temporary, untracked active-run fixture
  around the exact product assets. At desktop size the existing textbox was
  writable and labeled `Steer active Hermes run`, the form reported
  `data-mode="steer"`, the action was `Steer`, attachments and the agent/runtime
  selectors were disabled, typed guidance remained visible, `/steer` appeared
  in command suggestions, and browser error logs were empty.
- At 390 × 844, the active Steer composer remained visible and writable. Page
  width was exactly 390px; the form had 328px client and scroll widths, so
  neither the page nor composer overflowed horizontally. The prompt measured
  226px and the compact Steer button 44px.
- Post-review browser re-verification started with the browser/default profile
  differing from the profile that owned the active run. Mentat selected and
  locked the owning `researcher` profile, kept Steer available, showed only
  `/steer` and `/help` for `/`, disabled a rendered Context Pack action, and
  logged no browser errors.
- Final browser verification also confirmed Managed Agents `Use in Console`
  and `Test Agent` actions were disabled while active, and `/help` listed only
  `/steer` and `/help` rather than unavailable commands.
- An initial cold audit against the operator's discovered local Hermes runtime
  scored 76/100/100/100 because a machine-local calendar/Hermes update became
  the LCP at 5.9s. The canonical deterministic unconfigured-Hermes cold audit,
  using fresh empty Hermes and Obsidian roots and no warm-up request, scored
  100/100/100/100. The final post-review rerun measured FCP 297ms, LCP 434ms,
  TBT 0ms, and CLS 0.028. Evidence:
  `reviews/2026-08-14-hermes-active-run-steer-lighthouse.json`.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: working-tree slice diff relative to accepted 9D `HEAD`.
- Verification evidence: initial focused 84/84, clean full 1,000/4 skips,
  desktop/narrow computer-use, and canonical Lighthouse 100/100/100/100.
- Rendered artifacts: active composer desktop and 390px fixture observations;
  compact Lighthouse artifact.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A-1 | P1 | Yes | Stop and Steer used independent claims and could race across network calls. | Yes | Use one per-run remote-control claim and revalidate authority before POST and final success. |
| A-2 | P2 | Yes | `/model`, `/new`, command-menu, and Context Pack paths bypassed visible active-run locks. | Yes | Restrict active commands and block all context/attachment staging entry points. |
| A-3 | P2 | Yes | Acceptance validation checked values but allowed extra response fields. | Yes | Require the exact three-key schema and test malformed variants. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B-1 | P1 | Yes | Active `/model` and `/new` bypassed their disabled controls. | Yes | Active allowlist is `/steer` plus read-only `/help`. |
| B-2 | P1 | Yes | Reloading with a run owned by another profile could lock the wrong profile and make Steer unreachable. | Yes | Prefer the bound active run's agent before disabling the selector. |
| B-3 | P1 | Yes | Stop and Steer could race. | Yes | Shared claim and deterministic race tests. |
| B-4 | P2 | Yes | Context Pack and alternate staging actions remained enabled. | Yes | Shared active-run staging guard at render and mutation handlers. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Stop/Steer race | Corroborated | Both reviewers | Accepted. A shared `_remote_control_claim` blocks Stop during Steer; exact authority is checked immediately before POST and after read-back; changed authority after possible acceptance is partial. | Server control claim and two race tests. |
| Active command bypass | Corroborated | Both reviewers | Accepted. Suggestions and dispatch allow only `/steer` and `/help` while active; stale change/click handlers also fail closed. | Frontend allowlist and source/browser verification. |
| Context/attachment bypass | Corroborated | Both reviewers | Accepted. Rendered buttons and every upload/workspace/Context Pack mutation entry point share an active-run guard. | Frontend guards plus 128-test expanded regression set. |
| Wrong profile after reload | Reviewer B unique | Reviewer A did not identify it | Accepted. The bound active run's `agent_id` now precedes prior/default browser selection. | Source test and browser fixture with active `researcher` run. |
| Non-exact response | Reviewer A unique | Reviewer B did not identify it | Accepted. Exact key equality is required. | Five malformed response variants. |

### Reverification

- Focused tests: 88/88; expanded attachment/Context Pack set 128/128.
- Full suite: 1,004 passed, 4 skipped on the clean slice.
- Browser: bound non-default profile, filtered commands, and disabled Context
  Pack action verified with no console errors.
- Lighthouse: post-fix 100/100/100/100.
- Next review round or gate result: Round 2 requested from both reviewers.

### Round 2

- Both reviewers marked the Stop/Steer race, slash-command bypass, wrong-profile
  reload, synchronous staging paths, and exact-response finding resolved.
- Reviewer A found one P2 blocker: upload/workspace/Context Pack requests could
  begin before a run and commit browser state after that run became active.
- Reviewer B corroborated that P2 and found one additional P1 blocker: Managed
  Agents `Use in Console` and `Test Agent` paths could mutate Console state or
  accidentally submit the canned identity prompt as steering. Reviewer B also
  reported a non-blocking P3 that active `/help` still advertised unavailable
  commands.
- Disposition: all accepted. Every asynchronous staging completion now rechecks
  active state before mutation; active rendering discards context that crosses
  the boundary; server upload/workspace/Context Pack staging fails closed while
  active. Managed Agent actions are disabled and guarded before and after async
  profile loading. Active help uses the same command allowlist.
- Reverification: focused/expanded 128/128; clean full 1,004 pass with 4 skips;
  final browser locks/help and zero-error checks passed; final Lighthouse is
  100/100/100/100.
- Next review round or gate result: Round 3 requested from both reviewers.

### Round 3

- Reviewer A reported no P0–P3 findings and marked every Round 1 and Round 2
  item resolved.
- Reviewer B also reported no blocking implementation findings. Its only P3
  was evidence hygiene: the focused row still said 86 after two tests were
  added, and the expanded row lacked its exact command.
- Disposition: accepted and corrected above. The focused command is 88/88 and
  the exact 128-test expansion command is recorded.
- Gate result: both reviewers authorize proceeding to explicit publication
  approval; no reviewer dissent remains.

## Documentation updates

- Roadmap: the focused Milestone 9 implementation plan records the 9E decision,
  transport matrix, and deferred command/attachment follow-ups. The dirty
  `ROAD_TO_BETA.md` was intentionally preserved.
- Changelog: Not applicable unless the repository has a canonical milestone
  changelog target for this slice.
- Architecture/operator docs: updated the fixed `/steer` command, verified
  remote operation, privacy boundary, explicit composer mode, and unsupported
  attachment/local behavior.
- Project/session notes: this review log.
- Documentation verification: source-contract tests, `git diff --check`, and
  adversarial review packet.

## Publication gate

- Published files: `ARCHITECTURE.md`,
  `MILESTONE_9_WEBHOOK_IMPLEMENTATION_PLAN.md`, `command_manifest.py`,
  `hermes_transport.py`, `public/app.js`, `public/core.js`, `remote_hermes.py`,
  `server.py`, `tests/test_active_run_steer.py`,
  `tests/test_agent_console_runtime_switch_ui.py`,
  `tests/test_command_manifest.py`,
  `tests/test_frontend_workflow_feedback.py`,
  `tests/test_remote_console_runs.py`, this review log, and its compact
  Lighthouse JSON artifact. A focused CI follow-up adds
  `scripts/browser_smoke.mjs` and `.secrets.baseline`. Unrelated
  `ROAD_TO_BETA.md`, tracked data changes, and untracked design/video/tmp/lock
  files remain excluded.
- Branch and base: `codex/hermes-active-run-steer` onto
  `codex/hermes-webhook-health-setup`.
- Commit message: `feat: add verified active-run steering`
- PR title: `Milestone 9E: add verified active-run steering`
- PR summary: add capability-gated, revision-bound text-only active-run
  steering; reuse the Console composer in explicit Steer mode; add `/steer`;
  coordinate Stop/Steer and lock all incompatible mutation paths; retain
  privacy, exact-response, regression, browser, Lighthouse, and adversarial
  review evidence.
- Unresolved risks: no live paid-provider steer was executed. Exact mocked
  transport contracts, read-back/partial paths, browser interaction, and the
  complete regression suite cover the approved substitute. Steer attachments
  and broader slash-command parity remain deliberately deferred.
- User authorization and scope: implementation and publication approved.
- Implementation commit hash: `13034ba162f1e9700514330dabc419285e7e732b`.
- Ready PR URL: https://github.com/hazeion/agent-os/pull/100

### Publication CI correction

- GitHub's browser smoke retained the pre-9E three-command expectation, so it
  timed out waiting for a manifest that now correctly contains four commands.
  The bootstrap assertion now expects four commands, and the exact manifest
  assertion now includes `/steer` in its declared order.
- The tracked-secret scan correctly required review of the new Lighthouse
  report's SHA-256 evidence value. Its non-secret fingerprint is recorded in
  the existing reviewed `.secrets.baseline`, matching the prior 9C/9D evidence
  pattern.
- Local correction verification: CI/manifest/steer tests 25/25; full loopback
  browser smoke passed; pinned `detect-secrets` 1.5.0 tracked-file scan passed;
  JavaScript syntax, baseline JSON, and `git diff --check` passed.

## Outcome review

- Classification: Implementation and review complete and the ready PR is
  published; correction checks and user outcome review remain pending.
- Acceptance criteria summary: Pending.
- Potential bugs or untested paths: Pending.
- Remaining reviewer dissent: Pending.
- Compatibility/migration/rollback concerns: Pending.
- User decision: Pending.
- Next slice authorized: No
