# Feature Slice Review: Hermes Webhook Health and Operator Setup

Status: Commit and push approved; ready PR approval pending
Slice: `hermes-webhook-health-setup`
Date: 2026-08-14
Review log: `reviews/2026-08-14-hermes-webhook-health-setup.md`

## Slice contract

### Goal

Let a local operator determine whether native Hermes webhooks are configured
and working, copy safe manual setup guidance, and exercise the real signed
loopback receiver without exposing private receiver material.

### In scope

- Dedicated read-only webhook-health endpoint.
- Deterministic `off`, `ready`, `receiving`, and `degraded` states.
- Bounded last-event, refresh, and reconciliation ages and bounded counters.
- Responsive, accessible Settings health and operator-setup panel.
- Copyable sanitized Hermes configuration using a generic private-secret
  placeholder.
- Fixed server-side signed probe through the real loopback HTTP receiver.
- API and browser contracts proving private fields never appear.
- Focused, full-suite, package, computer-use, adversarial-review, and pinned
  Lighthouse verification.

### Out of scope

- Remote webhook relay or non-loopback access.
- Mentat edits to Hermes configuration or secret storage.
- Browser push or polling retirement; reserved for 9H.
- New webhook event types, Kanban mutations, or webhook-derived authority.
- Busy-input redirect behavior; reserved for 9E.
- Browser exposure of secret values, machine-specific secret references,
  signatures, delivery/session IDs, payload text, paths, profile IDs, or
  exception text.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The endpoint reports `off`, `ready`, `receiving`, and `degraded` deterministically and fails closed. | Unit and route state-matrix tests. | Pass |
| AC-2 | Health ages and counters are bounded, payload-free, and binding-safe. | Unit boundary tests and response-key allowlist. | Pass |
| AC-3 | The operator probe traverses the real signed loopback receiver without sending the secret to the browser. | Loopback integration test and browser interaction. | Pass |
| AC-4 | An unconfigured receiver rejects probing safely and remains quiet. | Negative route and browser-state tests. | Pass |
| AC-5 | Settings explains setup, displays health, copies a sanitized template, and verifies a probe at desktop and phone widths. | UI contracts and computer-use verification. | Pass |
| AC-6 | Browser/API payloads never contain prohibited private receiver fields or values. | Explicit negative assertions and secret scan. | Pass |
| AC-7 | Hermes 0.19 and unconfigured installations retain current behavior. | Compatibility tests and disabled-state server smoke. | Pass |
| AC-8 | Focused/full/package/browser/reviewer gates pass and Lighthouse categories are 100/100/100/100. | Recorded commands, artifacts, and two independent reviews. | Pass |

### Constraints and recovery

- Safety: webhooks remain wakeups only; the probe can enqueue one fixed
  synthetic allowlisted hint but cannot mutate Hermes or Mentat authority.
- Compatibility: no secret means `off`; older/unconfigured Hermes remains
  quiet and functional.
- Rendered behavior: preserve the dark Settings layout, compact edge-aligned
  controls, mobile wrapping, visible status, keyboard operation, and live
  region feedback.
- Rollback or recovery: remove the dedicated endpoint/UI/probe integration;
  disabling the private secret returns the receiver to `off` without touching
  Hermes files.
- Documentation targets: this log, the Milestone 9 implementation plan,
  `REMOTE_HERMES.md`, and applicable architecture/operator guidance.
- Version-control strategy: `codex/hermes-webhook-health-setup` stacked on
  `codex/hermes-webhook-refresh-coordinator`; ready PR only after explicit
  publication approval.

### Scope discussion and approval

- Recommendation and rationale: use a dedicated receiver-health endpoint and
  fixed server-side loopback probe so the UI proves the actual signed HTTP
  boundary without learning the secret.
- Alternatives considered: CLI-only probe (simpler but misses the operator UI
  flow); generic `/api/health` only (blurs receiver-specific states and setup).
- User decisions: approved the recommended contract and asked that it be
  persisted in Markdown before implementation.
- Approved at: 2026-08-14 in the active Codex task.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No public receiver-health payload or four-state classifier exists. | Deterministic unit matrix plus GET route tests. | State semantics and fail-closed behavior. | Does not prove live Hermes delivery. |
| AC-2 | Coordinator health is internal and contains datetime objects/raw implementation keys. | Age/counter clamp tests and exact response schema assertions. | Browser payload is bounded and minimized. | Process-local counters reset on restart by design. |
| AC-3 | No operator probe exists. | Local HTTP integration test using the real verifier and receiver route. | Signature, route, queue, and safe response operate together. | Synthetic probe is not a live Hermes process. |
| AC-4 | Missing secret currently appears only as receiver 404 behavior. | Probe-off route tests and browser disabled-state inspection. | Unconfigured installations remain safe and understandable. | Does not inspect every Hermes 0.19 binary. |
| AC-5 | Settings has generic subsystem health only. | Static contracts, browser smoke, keyboard/copy/probe interaction, desktop/phone computer-use. | User workflow, responsive layout, and accessible feedback. | Subjective visual preference remains manual. |
| AC-6 | No health-specific browser privacy contract exists. | Forbidden-key/value assertions, tracked-secret scan, and reviewer audit. | Secrets and webhook-private fields do not cross the browser boundary. | Cannot prove behavior of future untested fields. |
| AC-7 | Receiver is compatible but 9D routes/UI do not exist. | No-secret server smoke and existing webhook compatibility suites. | Existing unconfigured behavior is preserved. | Live 0.19 executable validation remains part of 9F. |
| AC-8 | No 9D evidence exists. | Focused suite, full clean-slice suite, package verifier, browser smoke, computer-use, two reviewers, pinned Lighthouse 13.4.1. | Repository and rendered quality gates for the complete slice. | Live stock-Hermes end-to-end remains 9F. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Source inspection of `server.py`, `hermes_event_refresh.py`, Settings UI, and current webhook tests | macOS workspace, Python/JS source | Gap confirmed | Internal coordinator health exists, but no 9D endpoint, Settings panel, copy action, or signed operator probe exists. |
| PR #98 accepted 9C outcome | GitHub Actions | Pass | Exact 9C head `f13becd` passed all 51 checks before branching. |

### Test discussion and approval

- User questions and decisions: user accepted the proposed 9D contract and test
  strategy without changes and requested immediate implementation.
- Accepted coverage gaps: the synthetic probe does not substitute for the live
  stock-Hermes validation required by 9F; process-local health resets on
  restart; subjective aesthetics remain manual.
- Approved at: 2026-08-14 in the active Codex task.

## Implementation record

### Changes

- Added `hermes_webhook_health.py`, a pure public-state projector and fixed
  signed-probe request builder.
- Added the dedicated health GET and same-origin probe POST routes. The probe
  uses a trusted loopback host, fixed path/event/body, fresh delivery ID,
  three-second timeout, bounded response read, no redirects, and accepts only a
  fresh empty `202` receiver acknowledgement.
- Added the Settings Webhook Health panel, four-state presentation, bounded
  age/counter display, placeholder-only copy action, and fixed probe feedback.
- Added focused backend, privacy, request-boundary, UI, responsive, packaging,
  and browser-smoke coverage; the new module is included in wheel/sdist
  inventories.
- Added operator guidance to `REMOTE_HERMES.md`, the approved contract to the
  Milestone 9 plan, and the user-visible outcome to `CHANGELOG.md`.
- Retained a compact Lighthouse 13.4.1 evidence artifact and reviewed its
  report digest in `.secrets.baseline`; all other new secret candidates remain
  fail-closed.
- Added semantic health invariants and process-start liveness evidence, plus a
  separate unresolved-drop counter that is cleared only after a completed,
  successful reconciliation. The public cumulative drop counter remains
  monotonic while operator health can recover truthfully after convergence.

### Deviations and decisions

- The existing browser smoke had three stateful fixture races that prevented
  it from reaching Settings: local runtime reads were not awaited, and the
  structured-event fixture inherited the previously selected agent/transport.
  The fixture now stubs and awaits its bounded runtime read and explicitly
  binds the structured event to its test agent/local transport. No product
  behavior changed for these fixes.
- The live operator-data Lighthouse attempt scored 73/99/100/100 because local
  Hermes reads delayed LCP to 7.0 seconds and unrelated existing Home
  accessibility audits were included. As established by 9C, the canonical
  local-product gate uses the exact patch in a detached clean worktree with
  isolated seed data; that result is 100/100/100/100.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| Pre-implementation `python3 -m unittest tests.test_hermes_webhook_health -v` | Workspace | Exit 1 | Import error | Expected TDD failure: `hermes_webhook_health` did not exist. |
| `python3 -m unittest tests.test_hermes_webhook_health tests.test_hermes_webhook_health_ui tests.test_request_boundary.RequestBoundaryTests.test_webhook_probe_uses_local_boundary_before_dispatch tests.test_packaging_cli.PackagingContractTests.test_pyproject_uses_single_version_source_and_pinned_dependencies -v` | macOS, Python 3.13, host loopback | Exit 0 | 15 passed | Includes real signed nested-loopback receiver and browser route. |
| `.venv/bin/python -m py_compile server.py hermes_event_refresh.py hermes_webhook_health.py` plus `.venv/bin/python -m unittest tests.test_hermes_webhook_health tests.test_hermes_webhook_health_ui tests.test_remote_capability_inventory_ui tests.test_beta_contract.BetaContractTests.test_remote_contract_inventories_all_current_hermes_adapters -q`, JS syntax, and diff checks | macOS, Python 3.11, host loopback | Exit 0 | 21 passed | Exact final focused command packet reported to Round 2 reviewers. |
| `.venv/bin/python -m unittest tests.test_hermes_webhooks tests.test_hermes_webhook_routes tests.test_hermes_event_refresh tests.test_hermes_webhook_health tests.test_hermes_webhook_health_ui tests.test_request_boundary -v` after Round 2 corrections | macOS, Python 3.11, host loopback | Exit 0 | 70 passed | Complete receiver/coordinator/health/security regression set, including semantic snapshot invariants, recoverable drops, extreme timestamps, the exact reconciliation deadline, IPv4/IPv6 real probes, and exact GET schema. |
| `.venv/bin/python -m unittest tests.test_hermes_webhook_health tests.test_hermes_event_refresh tests.test_hermes_webhook_health_ui -v` after Round 3 corrections | macOS, Python 3.11, host loopback | Exit 0 | 38 passed | Raw above-cap invariants and a deterministic concurrent post-snapshot drop are covered. |
| `python3 -m unittest tests.test_remote_capability_inventory_ui tests.test_hermes_webhook_health_ui tests.test_beta_contract.BetaContractTests.test_remote_contract_inventories_all_current_hermes_adapters -v` | Workspace | Exit 0 | 9 passed | Final renderer placement and documentation inventory. |
| `node --check public/core.js`, `node --check public/app.js`, `node --check scripts/browser_smoke.mjs`, `python3 -m py_compile server.py hermes_webhook_health.py`, `git diff --check` | Workspace | Exit 0 | N/A | Syntax and whitespace checks passed. |
| `uv run --with detect-secrets==1.5.0 python scripts/check_tracked_secrets.py` | Workspace | Exit 0 | N/A | Pinned tracked-file secret scan passed. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests` before Round 1 correction | Dirty operator workspace | Exit 1 | 982 run; 4 failures; 4 skipped | Historical pre-correction result: one slice-owned static-boundary failure plus three unrelated user-edit failures. Superseded by the runs below. |
| `.venv/bin/python -m unittest discover -s tests -q` after Round 2 correction | Dirty operator workspace | Exit 1 | 990 run; 3 failures; 4 skipped | The remaining failures are exclusively pre-existing user edits: two `ROAD_TO_BETA.md` contract expectations and one personal `data/projects.json` fixture expectation. |
| `<source-workspace>/.venv/bin/python -m unittest discover -s tests -q` in detached clean worktree containing the exact Round 4 9D code/docs patch | macOS, Python 3.11, host loopback | Exit 0 | 991 run; 4 skipped | Proves the final corrected slice independently of unrelated user roadmap/data edits. |
| `uv build --out-dir /private/tmp/mentat-9d-dist-r4.nfue7z` then `<source-workspace>/.venv/bin/python scripts/verify_python_artifacts.py /private/tmp/mentat-9d-dist-r4.nfue7z` in the clean worktree | macOS, uv 0.11.30 | Exit 0 | Wheel and sdist verified | Both exact Round 4 artifacts contain `hermes_webhook_health.py`; private/runtime exclusions remain enforced. |

### Rendered or manual behavior

- Complete `scripts/browser_smoke.mjs` passed against a secret-configured
  loopback server after fixture stabilization. It exercised the live Settings
  health render and then a deliberately stubbed UI success path for copy/probe
  feedback, plus all six views and the seven-width responsive matrix. Real
  signed HTTP probe behavior is covered separately by backend integration tests
  and the in-app browser interaction below.
- Independent in-app browser inspection verified desktop Copy Setup and Verify
  Signed Probe interactions, observed the `Receiving` state, and confirmed the
  visible setup contains `<YOUR_PRIVATE_SECRET_ENV>` rather than Mentat's
  machine-specific secret reference.
- At 390 × 844, page overflow, Settings panel overflow, and setup block
  overflow were all zero. Both action controls were 44px high (about 98px and
  149px wide), with the timing grid stacked and readable.
- Canonical cold-start Lighthouse 13.4.1 desktop/provided audit on the exact
  clean slice with explicit seed data, empty Hermes/Obsidian roots, and an
  explicitly unavailable Hermes command: Performance 100, Accessibility 100,
  Best Practices 100, SEO 100; FCP 291 ms, LCP 385 ms, TBT 0 ms, CLS 0.028.
  Earlier cold/live audits that discovered a real installed Hermes binary took
  6.87–7.55 seconds because those reads waited on machine-local operator state;
  they remain recorded here as environment-latency evidence. The retained gate
  now proves first navigation for the deterministic unconfigured-Hermes
  compatibility case rather than relying on warm caches. Compact evidence:
  `reviews/2026-08-14-hermes-webhook-health-setup-lighthouse.json`.
- Reproduction sequence: prepare the two empty roots with the artifact's
  `prepare_command`; start the exact clean slice with its recorded
  `start_command`; wait only for the process to yield a live listener session;
  make no HTTP readiness/warm-up request; execute the artifact's Lighthouse
  command as the first HTTP navigation. The fixed test-secret placeholder in
  the retained command represents any nonempty private test value and is not a
  credential.

## Adversarial review

### Round 1

- Reviewer A found two blocking issues: incomplete coordinator snapshots could
  be classified as ready, and the probe/setup URL hard-coded IPv4/port behavior
  that was incorrect for an IPv6 bind or implicit origin port. Reviewer A also
  noted the pre-fix full-suite count inconsistency in this log.
- Reviewer B independently found the same origin/binding problem, plus overly
  optimistic receiving health when events were old, drops had occurred, or
  reconciliation was stale. Reviewer B requested exact live GET-schema proof
  and a clear distinction between stubbed browser smoke and real HTTP evidence.
- Corrections: require the complete internal snapshot schema; reject malformed
  or future ages; classify receiving only for recent verified events; degrade
  on stopped coordinator, drops, projection/error evidence, or stale
  reconciliation; expose and test coordinator worker liveness; use the actual
  server bind family for the private probe and `window.location.origin` for
  setup copy; add IPv6, exact live GET, reconciliation-counter, lifecycle, and
  partial/stale-state tests; correct the operator secret-source documentation;
  and reconcile all evidence counts and wording above.

### Round 2

- Reviewer A found optimistic classification for key-complete but semantically
  inconsistent snapshots, sticky degraded health after a repaired queue drop,
  and that the then-retained Lighthouse artifact was warm-only. Reviewer A also
  requested the exact 21-test focused evidence in this log.
- Reviewer B found a two-minute gap between the three-minute reconciliation
  deadline and five-minute recent-event window, an extreme timezone offset that
  could raise `OverflowError`, and an incomplete publication inventory.
- Corrections: enforce bidirectional counter/timestamp/name/error invariants;
  add coordinator-start age; apply the reconciliation deadline independently;
  catch parse/normalization overflow; distinguish cumulative from unresolved
  drops and clear only the latter after successful reconciliation; add all
  boundary and recovery tests; rerun a true cold-start 100/100/100/100 audit
  with deterministic unconfigured Hermes; and complete the focused evidence
  and publication inventory.

### Round 3

- Both reviewers independently found that semantic counter relationships were
  checked after public capping, allowing distinct inconsistent raw values above
  the cap to appear equal. Both also recommended a deterministic concurrent-
  drop regression; Reviewer B required the exact cold-start server sequence in
  retained evidence.
- Corrections: preserve validated raw counters for all semantic checks and cap
  only the public response; add an above-cap inconsistency case; add a blocking-
  adapter test proving that a drop arriving after the reconciliation snapshot
  remains unresolved; and retain exact root preparation, server start,
  readiness/no-warm-up, and Lighthouse commands in the compact artifact and
  this log.

### Round 4

- Reviewer A found no blocking issue and signed off the slice as publication-
  ready. Reviewer B also found no behavioral issue, but blocked publication on
  a machine-specific source-workspace path and an abbreviated artifact-
  verifier command in retained evidence. Both noted that future Lighthouse
  reproductions should allocate fresh empty roots; Reviewer A also noted the
  plan's excluded-video image would be broken on GitHub.
- Corrections: replace the local account/workspace path with the defined
  `<source-workspace>` placeholder; retain the exact artifact-verifier command;
  add fresh-root reproduction guidance; and remove the excluded image link.
- Final documentation-only confirmation: both reviewers reported no remaining
  blocking issue and signed off 9D as publication-ready.

## Documentation updates

- Roadmap: approved 9D contract persisted in the Milestone 9 implementation
  plan; `ROAD_TO_BETA.md` remains the user's unrelated dirty work and is not
  part of this slice.
- Changelog: added the operator-visible health/setup outcome and safety bounds.
- Architecture/operator docs: added local setup, state, probe, and topology
  guidance to `REMOTE_HERMES.md`.
- Project/session notes: this review log and the implementation plan are the
  interruption-safe checkpoint.
- Documentation verification: beta adapter inventory test and focused UI/docs
  tests pass.

## Publication gate

- Proposed files (exact 9D inventory): `.secrets.baseline`, `CHANGELOG.md`,
  `REMOTE_HERMES.md`, `MILESTONE_9_WEBHOOK_IMPLEMENTATION_PLAN.md`,
  `hermes_event_refresh.py`, `hermes_webhook_health.py`, `server.py`,
  `public/app.js`, `public/core.js`, `public/index.html`, `public/styles.css`,
  `pyproject.toml`, `scripts/browser_smoke.mjs`,
  `scripts/verify_python_artifacts.py`, `tests/test_hermes_event_refresh.py`,
  `tests/test_hermes_webhook_health.py`,
  `tests/test_hermes_webhook_health_ui.py`, `tests/test_packaging_cli.py`,
  `tests/test_request_boundary.py`,
  `reviews/2026-08-14-hermes-webhook-health-setup-lighthouse.json`, and
  `reviews/2026-08-14-hermes-webhook-health-setup.md`.
- Explicitly excluded user files: `ROAD_TO_BETA.md`, `data/projects.json`,
  `data/tasks.json`, `design/`, `tmp/`, `uv.lock`, and `videos/`.
- Branch and base: `codex/hermes-webhook-health-setup` on
  `codex/hermes-webhook-refresh-coordinator`.
- Commit message: `feat: add Hermes webhook health and setup`.
- PR title: `Add Hermes webhook health and operator setup`.
- PR summary: add fail-closed, recoverable webhook-health projection; a fixed
  signed loopback probe; sanitized responsive Settings setup guidance; exact
  privacy, compatibility, package, browser, and cold Lighthouse evidence.
- Unresolved risks: live stock-Hermes delivery remains 9F; browser push remains
  9H.
- User authorization and scope: on 2026-08-14, the user explicitly approved
  staging the exact 21-file inventory, committing it, and pushing the branch.
  Opening the ready pull request was not included and remains unauthorized.
- Commit hash: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: Accepted by both adversarial reviewers; publication approval
  pending.
- Acceptance criteria summary: AC-1 through AC-8 pass with the evidence above.
- Potential bugs or untested paths: live stock-Hermes delivery remains the
  explicitly accepted 9F gate; remote relay and browser push remain out of
  scope. Live machine-local Hermes reads can still delay Home rendering, as
  disclosed by the non-canonical operator-data Lighthouse observations.
- Remaining reviewer dissent: none. Both reviewers signed off after Round 4.
- Compatibility/migration/rollback concerns: no data migration; no Hermes file
  writes; no configured secret leaves the receiver off; removing the dedicated
  routes/panel/projector rolls back 9D without changing Hermes state.
- User decision: exact publication packet pending explicit approval.
- Next slice authorized: No
