# Feature Slice Review: Agent Console immediate runtime switching

Status: Approved; ready for publication approval
Slice: `agent-console-immediate-runtime-switching`
Date: `2026-07-28`
Review log: `reviews/2026-07-28-agent-console-immediate-runtime-switching.md`

## Slice contract

### Goal

Make the Agent Console provider and model selectors apply verified Hermes
runtime changes immediately, while keeping the selected agent's exact runtime
visible and making the console layout and tool activity easier to follow.

### In scope

- Place the Agent, Provider, and Model selectors in one row, with the prompt
  composer in the row below.
- Re-read and display the selected profile's exact Hermes provider and model
  whenever the Agent selector changes, without mutating the runtime.
- When Provider changes, use Hermes's first listed model for that provider and
  automatically run the existing preview, switch, and verification flow.
- When Model changes, automatically run the same preview, switch, and
  verification flow.
- Remove the Agent Console Review change button and interactive confirmation
  dialog while retaining revision-, profile-, and connection-bound server
  confirmation internally.
- Disable runtime selectors during a switch, preserve active-run exclusion, and
  refresh the exact Hermes runtime after a failed operation.
- Add a visible, UI-only transcript notice after a verified runtime switch.
- Hide detailed tool events by default. Show a live, animated "Agent is using
  tools" summary while a tool call is outstanding, and expose a Show tools /
  Hide tools toggle beside New session.
- Preserve read-only fallback for unsupported Hermes hosts and preserve the
  Managed Agents review/confirmation workflow.

### Out of scope

- Effort and speed controls.
- Effort or speed slash commands.
- Changes to Hermes credential ownership, provider authentication, or runtime
  inventory ordering.
- Changes to the Managed Agents provider-switch confirmation flow.
- Injecting runtime notices into the agent's prompt or model context.
- New provider/model mutation endpoints or a weakened backend safety contract.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Agent, Provider, and Model are in one responsive row and the prompt composer is directly below. | DOM contract and rendered browser geometry | Pass, pre-review |
| AC-2 | Agent selection makes a fresh profile-runtime read, displays Hermes-confirmed values, and sends no switch mutation. | Browser interaction and frontend contract tests | Pass, pre-review |
| AC-3 | Provider selection chooses Hermes's first listed model and automatically previews, switches once, verifies, and displays the confirmed pair. | Browser interaction plus existing backend integration tests | Pass, pre-review |
| AC-4 | Model selection automatically previews, switches once, verifies, and displays the confirmed pair. | Browser interaction plus existing backend integration tests | Pass, pre-review |
| AC-5 | Controls lock during mutation; active runs and unsupported hosts remain blocked/read-only; failure refreshes the actual runtime and uncertain mutation is not retried. | Negative-path frontend tests and backend safety suite | Pass, pre-review |
| AC-6 | A verified switch adds a visible UI-only Agent Console transcript notice. | Rendered browser and source contract tests | Pass, pre-review |
| AC-7 | Tool details are hidden by default, Show tools / Hide tools toggles them, and an outstanding tool call shows an animated activity summary. | Browser interaction, accessibility, and visual contract tests | Pass, pre-review |
| AC-8 | The redundant provider toolbar and Review change button are removed; New session remains; Managed Agents keeps its review flow. | DOM/source contract tests | Pass, pre-review |
| AC-9 | Existing local and remote provider-switch safety, console behavior, and narrow-layout behavior remain compatible. | Focused and full suites plus browser smoke | Pass, pre-review |

### Constraints and recovery

- Safety: Keep exact capability gating, active-run locking, fresh preview,
  connection/revision binding, one-shot mutation, verification, and
  concurrency-safe rollback ownership. The browser may automate confirmation
  but may not bypass the server contract.
- Compatibility: Preserve local and remote transports, read-only degradation,
  existing API response shapes, and the Managed Agents workflow.
- Rendered behavior: Three selectors share the first control row on wide
  layouts and wrap compactly on narrow layouts; the prompt remains a distinct
  row. Tool activity remains perceivable when details are hidden.
- Rollback or recovery: On frontend failure, refresh the selected profile's
  runtime and render Hermes's confirmed values. Backend rollback and
  fail-closed behavior remain authoritative.
- Documentation targets: `ARCHITECTURE.md`, `REMOTE_HERMES.md`,
  `ROAD_TO_BETA.md`, `CHANGELOG.md`, and this review log.
- Version-control strategy: isolated
  `codex/agent-console-immediate-runtime-switching` worktree based on `main`;
  no staging, commit, push, or ready PR before the final publication approval.

### Scope discussion and approval

- Recommendation and rationale: Automate the existing safe preview/confirmed
  apply protocol in the Agent Console instead of adding an unconfirmed server
  mutation path. This removes the extra click without weakening runtime
  revision, transport, verification, or rollback boundaries.
- Alternatives considered: wait for a model choice after provider selection;
  the user instead chose Hermes's first listed model. Keep tool details visible
  by default; the user chose hidden by default with a live activity summary.
- User decisions: Provider selection immediately targets the first Hermes model;
  tool details start hidden; runtime changes appear as UI-only transcript
  notices. Effort/speed selectors and slash commands are a future slice.
- Approved at: `2026-07-28`. The user approved the contract and authorized work
  through final review without intermediate approval pauses, while reserving
  explicit approval for commit/publication.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Provider is inside the history disclosure and the composer shares the command-bar row. | Update DOM/visual contracts and browser geometry checks at desktop and narrow widths. | Required ordering, grouping, and responsive rendering. | Does not prove mutation behavior. |
| AC-2 | Agent change refresh exists, but exact no-mutation behavior is not exercised through a rendered interaction. | Browser mock interaction plus source contract assertions. | Agent selection calls refresh and does not call switch. | Browser test uses controlled API responses. |
| AC-3 | Provider change only repopulates the model selector and requires Review change. | Browser mock interaction asserting first-model selection, preview request, one apply request, and verified rendering. | Full UI event path and request ordering. | Backend correctness is covered separately. |
| AC-4 | Model change only updates browser state. | Browser mock interaction asserting automatic preview/apply and result rendering. | Immediate model-change behavior. | Backend correctness is covered separately. |
| AC-5 | No frontend in-flight runtime lock or failure reconciliation for automatic selection exists. | Frontend negative-path contracts/browser checks plus existing profile-aware and remote console safety tests. | UI locking/recovery and unchanged backend fail-closed guarantees. | Timing races are controlled rather than load-tested. |
| AC-6 | Provider change success is only shown in status/state controls. | Browser check for a runtime transcript notice after a mocked verified result. | User-visible notice exists and is not a prompt mutation. | Notice is intentionally browser-session only. |
| AC-7 | Every tool event renders and there is no visibility toggle or hidden-mode activity summary. | Observability/visual contracts and browser checks using paired/unpaired tool events. | Default-hidden details, toggle semantics, outstanding-tool indicator, and animation hook. | CSS animation cadence is visually inspected rather than pixel-timed. |
| AC-8 | Provider and Review change are in the history toolbar. | DOM/source contract tests. | Redundancy is removed without removing New session or Managed Agents review. | Static contract complements browser smoke. |
| AC-9 | Existing suites describe the current supported safety surface. | Focused provider/console tests, full unittest discovery, py_compile, node syntax, browser smoke, and diff check. | Compatibility across backend, frontend, and docs contracts. | WSL/Tailscale deployment is outside repository CI. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python -m unittest tests.test_home_operations_ui tests.test_visual_contract tests.test_frontend_workflow_feedback tests.test_agent_console_observability tests.test_profile_aware_console tests.test_dashboard_behaviors tests.test_hermes_provider_switching tests.test_remote_console_runs -v` | Isolated macOS worktree, Python | Pass | 142 tests passed before implementation. |
| `python -m py_compile server.py hermes_provider_switching.py hermes_transport.py remote_hermes.py` | Isolated macOS worktree, Python | Pass | Exit 0. |
| `node --check public/app.js` | Isolated macOS worktree, Node | Pass | Exit 0. |

### Test discussion and approval

- User questions and decisions: The user approved the proposed DOM, browser
  interaction, negative-path, backend safety, full-suite, and rendered checks.
- Accepted coverage gaps: No live WSL/Tailscale mutation during repository
  tests; controlled browser responses plus local/remote server integration tests
  cover the boundary.
- Approved at: `2026-07-28`, together with the slice contract.

## Implementation record

### Changes

- Moved all three Agent Console runtime selectors into one responsive runtime
  row and placed the prompt composer in the next row.
- Added one in-flight frontend runtime-mutation guard. Provider and model
  changes automate the existing preview/confirmed apply pair, with one apply
  call and fresh inventory reconciliation after failure.
- Kept Agent selection read-only and surfaced the exact refreshed pair in the
  Console status.
- Added bounded, transport/profile-bound browser-session runtime notices
  without modifying prompts, retained run history, or Hermes context.
- Added default-hidden tool events, an accessible Show tools / Hide tools
  toggle, unmatched-tool activity detection, cycling dot animation, and a
  reduced-motion fallback.
- Updated the browser smoke harness to exercise desktop/mobile placement,
  provider/model selection, first-model behavior, failure recovery, agent
  refresh, runtime notices, and tool visibility.
- Added focused UI contracts and updated existing layout/workflow contracts.
- Updated architecture, remote operator, roadmap, and changelog records,
  including the deferred effort/speed controls and slash commands.

### Deviations and decisions

- The user authorized implementation through final review without intermediate
  approval pauses, while explicitly reserving commit/publication approval. This
  process exception is recorded here.
- No server mutation endpoint changed. Immediate selection is implemented by
  automating the already-approved safe preview and confirmed apply calls.
- The first full-suite run found one outdated CSS source-contract assertion
  that assumed the old flex-only provider toolbar. The implementation was
  unchanged; the test was updated to assert both the retained wrapping toolbar
  and the new three-column runtime grid, then the full suite passed.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_agent_console_runtime_switch_ui tests.test_home_operations_ui tests.test_visual_contract tests.test_frontend_workflow_feedback tests.test_agent_console_observability tests.test_profile_aware_console tests.test_dashboard_behaviors tests.test_hermes_provider_switching tests.test_remote_console_runs tests.test_beta_contract tests.test_limited_beta_readiness tests.test_public_beta_promotion -v` | Isolated macOS worktree, Python | Exit 0 | 177 passed | Covers the new UI contracts, existing local/remote switch safety, observability, layout, and beta/docs contracts. |
| `python -m py_compile server.py hermes_provider_switching.py hermes_transport.py remote_hermes.py` | Isolated macOS worktree, Python | Exit 0 | N/A | Production Python syntax green. |
| `node --check public/core.js && node --check public/app.js && node --check scripts/browser_smoke.mjs` | Isolated macOS worktree, Node | Exit 0 | N/A | Frontend and browser harness syntax green. |
| `git diff --check` | Isolated worktree | Exit 0 | N/A | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -v` | Isolated macOS worktree, Python | Exit 0 | 855 passed, 4 skipped | Final rerun after updating the obsolete responsive CSS assertion. |

### Rendered or manual behavior

- Started the isolated server on loopback port 8892 and ran
  `scripts/browser_smoke.mjs` in Chromium.
- Result: pass. The smoke matrix covered desktop runtime-control alignment,
  prompt placement, seven responsive widths, mobile layout, default-hidden
  tool activity, Show tools / Hide tools, immediate first-model provider
  switching, immediate model switching, failed-switch reconciliation, exact
  agent runtime refresh without a switch call, and the runtime transcript
  notice.
- Reduced-motion CSS renders a static ellipsis instead of a cycling animation.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Complete uncommitted worktree diff from `main`
  (`cc6df71`); no commit or publication.
- Verification evidence: 177 focused tests passed; 855 full tests passed with
  4 skipped; Python/Node syntax and diff checks passed.
- Rendered artifacts: Chromium smoke passed on loopback port 8892 across the
  desktop/mobile matrix and the initial selector/tool interaction cases.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| S-1 | High | Yes | If a switch failed and the follow-up runtime refresh also failed, stale browser inventory could render as ready; prompt/send/attach did not share the mutation uncertainty lock. | Yes | Discard stale runtime state and block execution/switching until an explicit fresh read succeeds. |
| S-2 | Medium | Yes | Runtime notices were prepended before retained runs, so their chronology was wrong and they could scroll out of useful context. | Yes | Sort run turns and runtime notices by timestamp and keep the latest verified notice visible outside collapsed history. |
| S-3 | Medium | Yes | Tool activity/status nodes were rebuilt during polling inside a non-live transcript, risking missing or repeated announcements. | Yes | Use one persistent live-status node updated only when tool activity transitions; keep transcript rows non-live. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| P-1 | High | Yes | A valid Hermes runtime pair may be absent from the authenticated selectable inventory; the UI fell back to the first selectable pair and labeled it ready. | Yes | Source the confirmed display only from exact `current_provider`/`current_model`, with a disabled confirmed-only option when needed. |
| P-2 | Medium | Yes | Change handlers selected the requested target before verification, allowing it to appear ready during preview/apply latency. | Yes | Track a separate pending target while keeping the last confirmed pair authoritative until verified. |
| P-3 | Medium | Yes | The requested verified-switch notice lived only inside Console history, which is collapsed by default. | Yes | Add a visible bounded runtime banner outside the disclosure while retaining a chronological history entry. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Confirmed runtime versus selectable inventory and pending target | Corroborated by both reviewers after cross-critique | Safety reviewer agreed P-1/P-2 were safety-relevant, not merely presentation issues. | Accepted. Browser coverage now exercises an exact current pair absent from selectable inventory and a deferred preview/apply state. | Added confirmed-only options and separate pending runtime state; readiness copy uses only Hermes-confirmed fields. |
| Uncertain switch plus failed reconciliation | Corroborated by both reviewers after cross-critique | Product reviewer agreed S-1 must block all execution-affecting controls. | Accepted. A new double-failure browser path verifies no stale ready state, blocked prompt/send/attach/session/selectors, and a read-only retry with no extra switch call. | Added fail-closed unresolved state, stale-inventory clearing, explicit Retry runtime check, and programmatic submit/session guards. |
| Notice visibility and chronology | Corroborated root cause | Both reviewers required a notice visible by default and correctly ordered retained history. | Accepted. Browser smoke checks the visible banner while history is closed and verifies the notice follows an older retained run. | Added the outside banner and timestamp-merged transcript entries. |
| Tool status accessibility | Corroborated by both reviewers after cross-critique | Product reviewer agreed the persistent transition-based live region was the correct remedy. | Accepted. Browser/source checks assert exactly one persistent status node and no transient `role=status` tool rows. | Added a persistent screen-reader live region keyed to tool-activity transitions; visual activity remains animated and non-live. |

### Reverification

- Focused tests: 179 passed after the fixes.
- Full suite: 857 passed, 4 skipped in 117.339 seconds.
- Syntax/diff checks: `py_compile`, all three Node syntax checks, and
  `git diff --check` passed.
- Rendered check: Chromium smoke passed, including confirmed runtime outside
  selectable inventory, deferred pending state, default-visible verified
  notice, retained-run chronology, fail-closed double failure, explicit
  read-only recovery, and stable tool live status.
- Next review round or gate result: Full revised slice sent to both independent
  reviewers for round 2.

### Round 2 findings and disposition

Both reviewers re-read the full revised slice. Their Context Pack and tool-live
findings corroborated one another; the other findings were independent and
accepted as blocking.

| ID | Severity | Reviewer(s) | Finding | Disposition |
| --- | --- | --- | --- | --- |
| R2-1 | High | Product/compatibility | An HTTP-successful refresh with an inventory error or blank current pair could clear the unresolved lock because the helper returned only a truthy model-catalog object. | Fixed. Refresh now returns the full payload and `agentConsoleConfirmedRuntime()` requires the exact profile, non-empty current provider/model, and no inventory error before any reconciliation unlock. |
| R2-2 | High | Safety | A delayed apply response from an old transport could be projected onto a newly selected connection because the browser rechecked only the profile. | Fixed. Each operation captures the opaque binding and mutation generation; it rechecks binding after preview, after apply, and before error/final state changes. Rebinding invalidates and discards the old result and notice. |
| R2-3 | Medium | Safety | Agent selection cleared unresolved state while its required fresh runtime read was still pending, leaving execution controls enabled. | Fixed. Runtime loading is now part of the shared execution block, is rendered immediately, and the agent handler is generation/profile safe. |
| R2-4 | Medium | Safety | A prior successful banner could contradict a later fresh-read pair. | Fixed. Only a current-binding/profile notice whose pair matches the exact confirmed runtime may appear in the always-visible banner; unmatched history remains chronological. |
| R2-5 | Medium | Both | Context Pack staging bypassed the runtime block and could overlap switching or apply results after its profile/connection changed. | Fixed. All attachment/Context Pack entry points share the runtime guard; staging disables selectors, runtime switching refuses while staging, and in-flight pack results are discarded after a binding/profile change. |
| R2-6 | Medium | Product/compatibility | The sighted tool-activity animation remained inside history, which is collapsed by default. | Fixed. The visual animated summary now lives outside the disclosure and is hidden only when detailed tool events are deliberately shown. |
| R2-7 | Medium | Both | The live-region key included outstanding tool count and was global, causing repeated or false completion announcements. | Fixed. Live state is boolean and scoped to the selected transport/profile; count changes do not announce, and context changes reset without a false completion. |

Round-2 adversarial browser additions cover the degraded `200` refresh, stale
old-binding response, deferred agent read and blocked submit/session controls,
mismatched banner suppression, unresolved and in-flight Context Pack staging,
visible tool activity with closed history, concurrent tools, and selected-agent
live-region changes.

### Round 2 reverification

- Focused tests: 180 passed.
- Chromium smoke: passed with all round-2 adversarial interactions.
- Python/Node syntax and `git diff --check`: passed.
- Full suite: 858 passed, 4 skipped in 103.110 seconds.
- Next review round or gate result: Full revised slice sent to both independent
  reviewers for the third and final review round.

### Round 3 findings and disposition

Both reviewers found remaining asynchronous ownership gaps during the third and
final review round. The fixes below stay within the approved UI slice and do
not change the Hermes mutation contract.

| ID | Severity | Reviewer(s) | Finding | Disposition |
| --- | --- | --- | --- | --- |
| R3-1 | High | Safety | An A→B→A transport-binding sequence could allow an old mutation response to pass the profile/binding checks after the binding string returned to its original value. | Fixed. The per-mutation generation is now checked after preview, after apply, before error reconciliation, and after reconciliation. A binding change invalidates the generation even if the opaque binding later returns to the same value. |
| R3-2 | High | Safety | Managed-profile navigation changed the selected profile before establishing the fresh-read execution gate; a failed read could leave execution enabled. | Fixed. Navigation enters the loading gate before any asynchronous view/API work, projects the requested profile only after inventory confirms it still exists, and converts a failed current-profile read into an unresolved fail-closed state. |
| R3-3 | High | Both | Scheduled Console payloads could project runtime inventory for a different profile, and an incidental inventory could clear a dedicated fresh-read loading gate. | Fixed. Incoming model/provider inventories are accepted only when their explicit `profile_id` matches the selected agent. Rendering never clears the fresh-read gate; only the owning generation-checked runtime read may do so. A transport change starts a new dedicated read. |
| R3-4 | Medium | Product/compatibility | Cancelled or superseded agent-selection and retry reads returned the same sentinel as a current failure, allowing old handlers to clear newer valid state after a profile/connection change. | Fixed. Both handlers capture the selected profile, transport binding, and request generation around the fresh read and return without any state mutation when any ownership value changes. |
| R3-5 | High | Product/compatibility follow-up | The new transport-owned refresh could reject or return an unconfirmed `200` inventory without a caller converting that result into an unresolved state. | Fixed. Transport refreshes require the bounded readable-runtime policy inside the owning helper; rejected and degraded responses clear runtime projection, expose retry, and remain execution-blocked. |

Round-3 adversarial browser additions cover the exact A→B→A mutation replay,
a stale agent-selection read after rebinding, a stale explicit retry read after
rebinding, and an exact-profile incidental payload arriving while the selected
agent's dedicated runtime read is pending. Transport-rebind coverage also
exercises a rejected refresh and a degraded successful response. Source
contracts cover every
mutation-generation checkpoint, profile-navigation fail-closed gating,
exact-profile inventory acceptance without gate release, and request-generation
ownership in both read handlers.

### Round 3 reverification

- Focused tests: 181 passed.
- Chromium smoke: passed, including all earlier interaction cases plus the
  A→B→A mutation replay and stale agent/retry read cases.
- Python/Node syntax and `git diff --check`: passed.
- Full suite: 859 passed, 4 skipped in 96.506 seconds.
- Final reviewer result: Both independent reviewers explicitly cleared the
  current full diff with no remaining blocking findings. The safety reviewer
  confirmed mutation/read ownership and fail-closed transport refreshes. The
  product/compatibility reviewer confirmed immediate selection, readable
  read-only fallback, and rejected/degraded rebind behavior.
- Review gate result: Approved after the third and final review round. No
  additional review round was started.

## Documentation updates

- Roadmap: Recorded automatic Agent Console selection and deferred per-model
  effort/speed dropdown and slash-command work.
- Changelog: Recorded layout, automatic verified runtime switching, notices,
  and tool visibility behavior.
- Architecture/operator docs: Clarified that a deliberate selector change is
  the user action while preview/confirmation remain enforced internally;
  documented first-model selection, exact agent refresh, and UI-only notices.
- Project/session notes: This review log.
- Documentation verification: Beta/readiness focused tests passed within the
  179-test focused suite. Docs now also describe confirmed/pending separation
  and the fail-closed explicit runtime retry.

## Publication gate

- Proposed files: `public/app.js`, `public/core.js`, `public/index.html`,
  `public/styles.css`, `scripts/browser_smoke.mjs`, focused UI/contract tests,
  `ARCHITECTURE.md`, `REMOTE_HERMES.md`, `ROAD_TO_BETA.md`, `CHANGELOG.md`,
  and this review log.
- Branch and base: `codex/agent-console-immediate-runtime-switching` to `main`.
- Commit message: `feat: streamline Agent Console runtime switching`.
- PR title: `Streamline Agent Console runtime switching`.
- PR summary: Put Agent/Provider/Model in one row; automatically apply
  provider/model selection through the existing safe preview/confirmed switch;
  fresh-read selected-agent runtime; preserve read-only fallback; add verified
  transcript notices; hide tool details by default with accessible activity;
  add generation/connection/profile ownership and fail-closed recovery.
- Unresolved risks: No live WSL/Tailscale mutation was performed in repository
  verification. Controlled Chromium cases and local/remote backend contract
  tests cover the boundary; the existing Hermes capability and mutation
  contract remains unchanged.
- User authorization and scope: Commit/publication approval intentionally
  reserved until after final review.
- Commit hash: Pending.
- Ready PR URL: Pending.

## Outcome review

- Classification: Approved and verified; not yet published.
- Acceptance criteria summary: AC-1 through AC-9 pass.
- Potential bugs or untested paths: Live operator WSL/Tailscale behavior remains
  an environment-level smoke step after publication; no known repository
  blocker remains.
- Remaining reviewer dissent: None.
- Compatibility/migration/rollback concerns: No storage or API migration.
  Managed Agents keeps its explicit review flow, unsupported hosts remain
  readable/read-only, and server-side verification/rollback remains
  authoritative.
- User decision: Explicit commit/push/ready-PR approval pending.
- Next slice authorized: No
