# Feature Slice Review: Run message control

Status: In progress

Slice: `2c-c-run-message-control`

Date: `2026-08-22`

## Slice contract

### Goal

Let a person send one bounded text-only message to one active, task-bound
Hermes Run from the new Runs workspace after reviewing a state-bound
confirmation.

### In scope

- Fixed authenticated loopback preview and confirmation actions for one active
  Run and one bounded text-only message.
- Runtime-neutral identity, capability, binding, state, message-digest,
  locking, and current-state verification around Hermes' supported steer
  operation.
- Two fixed same-origin Node routes and an accessible compose-review-confirm
  message panel in the Runs workspace.

### Out of scope

- Local-run messaging, arbitrary commands, message history, attachments,
  approval or clarification responses, generic bridge actions, direct Hermes
  access, browser-selected runtime references, and changing legacy Console
  behavior.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The bridge exposes only exact preview and confirmed-message actions for one valid Run and one bounded text field. | Bridge contract tests | Pass |
| AC-2 | A message is capability-, identity-, binding-, text-, and state-checked, confirmation-bound, serialized, and verified against current runtime state. | Python action tests | Pass |
| AC-3 | Node accepts only exact same-origin, bounded message bodies and returns safe action payloads. | Node route and bridge tests | Pass |
| AC-4 | The Runs page gives one accessible compose-review-confirm flow with usable stale and unavailable recovery. | Production browser smoke | Pass |
| AC-5 | Existing Console behavior and the selected Run list, timeline, and Stop action remain unchanged. | Regression tests and diff review | Pass locally; clean CI pending |
| AC-6 | Six Lighthouse runs remain 100/100/100/100. | Lighthouse gate | Pass |

### Constraints and recovery

- Python remains authoritative. Browser text never chooses a bridge target,
  runtime reference, action, or confirmation state.
- The exact confirmation binds a normalized message digest and current Run
  identity/state. Changed text or Run state requires a new review.
- The message is text-only, contains no NUL byte, and is limited to 6,000
  Unicode code points. The bridge and Node bound the JSON body to 24,576 bytes.
- The existing legacy Console steer route remains unchanged. Unsupported,
  local, stale, and unverifiable cases fail closed without claiming a sent
  message.
- Rollback removes the two fixed routes and the Runs-panel control. It has no
  schema migration and writes no Hermes core file.
- Documentation targets: `ARCHITECTURE.md`, implementation plan, review log.
- Branch: `feature/2c-c-run-messages`, ready PR base `main`.

### Scope discussion and approval

- Production cutover cannot be honestly started while the new interface lacks
  the separated message and approval contracts that 2C-B deliberately deferred.
  This slice restores the next smallest parity step; approval responses remain
  2C-D.
- The active pivot goal gives standing approval for scope, tests, publication,
  merge, and continuation. It is an explicit exception to the workflow's
  normal per-slice approval and outcome pauses.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The bridge has no message action. | Exact method/path/body, message-size, encoded-ID, and malformed-route tests. | No generic bridge mutation. | Does not invoke Hermes. |
| AC-2 | No canonical message mutation exists. | Fake-runtime tests for capability, identity, text digest, stale state, runtime failure, and post-operation recheck. | Safe action sequencing. | Hermes transport stays mocked. |
| AC-3 | Node has no message mutation route. | Node request-boundary/body tests and response allowlist tests. | Browser cannot widen the server-side action. | Does not render UI. |
| AC-4 | Runs has no message panel. | Production Chromium smoke for draft, review, stale, retry, confirm, and narrow layout. | Real selected-Run interaction. | Uses deterministic local fixtures. |
| AC-5 | A mutation can regress existing routes. | Existing Python/Node regressions and complete suite. | Compatibility stays stable. | External Hermes behavior is mocked. |
| AC-6 | Gate covers the current shell. | Six-run production Lighthouse gate. | Every category remains perfect. | Local deterministic evidence only. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Current bridge, Node route, and Runs control inspection | macOS local checkout | Pass | No fixed message preview/confirmation routes or rendered message panel exist. |

### Test discussion and approval

- Standing authorization accepts this strategy.
- Accepted coverage gap: no live remote Hermes message is required; the existing
  supported steering adapter is exercised with deterministic test doubles.

## Implementation record

- Added a separate `run.message` runtime-neutral action that accepts only a
  selected active Run, bounded text, and a state- and message-digest-bound
  confirmation.
- Bound Hermes message and status reads to the current Mentat Run context.
- Added two fixed authenticated Python bridge actions and two fixed same-origin
  Node routes. Neither accepts an adapter reference, bridge path, or action
  chosen by the browser.
- Added the Runs compose-review-confirm panel, including stale-confirmation
  recovery and a 6,000-character text limit.
- Added Python, bridge, Node body, browser smoke, architecture, and syntax
  coverage. Updated the architecture and roadmap. Slice 4A is now a planned
  Vercel option with a concrete completion bar; this is a documentation-only
  product decision requested during the slice and does not change this action's
  scope.

## Verification

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest tests.test_run_stop_control tests.test_mentat_local_bridge -q` | macOS host | Pass: 33 tests | Exact action, stale, partial, route, body-size, and bridge coverage. |
| `npm --prefix web run check` | macOS host, Node 24.19.0 | Pass: 35 tests | Lint, typecheck, bridge/body contracts, and shell contracts. |
| `node web/scripts/run-next.mjs build --webpack` and `node web/scripts/prepare-standalone.mjs` | macOS host | Pass | Production Next build completed. |
| `node --check scripts/web_foundation_smoke.mjs` and `python3 -m unittest tests.test_agent_runtime_architecture -q` | macOS host | Pass: 4 architecture tests | Smoke script parses; roadmap and architecture contract remains valid. |
| `CHROME_PATH=… MENTAT_WEB_BASE_URL=http://127.0.0.1:8897 … node scripts/web_foundation_smoke.mjs` | local production preview, Chromium | Pass | Runs timeline, Stop, message review, stale retry, confirmation, responsive reflow, and existing routes passed. |
| `CHROME_PATH=… MENTAT_WEB_BASE_URL=http://127.0.0.1:8897 npm --prefix web run lighthouse:gate` | local production preview, pinned Chromium | Pass: 3 desktop + 3 mobile audits | Gate exits only when every category is 100/100/100/100. |
| `python3 -m unittest discover -s tests -q` | macOS host | Expected unrelated failure | User-modified `data/projects.json` contains two extra projects; `tests.test_data_contract.DataFixtureTests.test_only_mentat_project_remains_active_for_v1` expects only the tracked Mentat seed. No slice file or test was changed to hide this. |

After review fixes, the focused Python suite, Node check, production build,
Chromium smoke, and six-run Lighthouse gate were rerun and passed again.

The local data-fixture failure is outside this slice and will not be staged.
The clean-checkout CI result remains required before merge.

## Adversarial review

### Round 1

- Reviewer A (correctness and safety) found one blocking Unicode body-length
  mismatch: the bridge allowed a 24,576-byte message body but accepted only a
  four-digit `Content-Length`. Reviewer B independently upheld it. Fixed by
  deriving the allowed header digits from the action-specific byte limit and
  adding preview and confirmation tests using more than 9,999 bytes of valid
  UTF-8 text.
- Reviewer B (compatibility and product) found an unlabeled message textarea,
  Stop-specific message error text, and visible whitespace that did not match
  the normalized sent value. Reviewer A independently upheld all three. Fixed
  with an associated visible label, message-specific recovery text, UI
  normalization before review, and browser assertions.
- Reviewer B suggested allowing waiting-state messages. Reviewer A withdrew
  that finding after confirming that this slice intentionally limits messages
  to `running`; approval and clarification paths remain the separate 2C-D
  contract.

### Round 2

- Reviewer B reported no findings after the first fixes. Reviewer A found a
  blocking Unicode code-point mismatch: JavaScript `length` and native
  `maxlength` count UTF-16 units, unlike Python. Reviewer B independently
  upheld it. Fixed by defining the 6,000-character limit as Unicode code
  points, using `Array.from()` in Node and the browser input handler, and
  adding 6,000-emoji parser, bridge, and browser coverage.

### Round 3

- Reviewer A: No findings.
- Reviewer B: No findings.

## Documentation updates

- `ARCHITECTURE.md`: records the separated bounded message action contract.
- `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`: records Slice 2C-C and promotes the
  Vercel infrastructure adapter to a planned option with a concrete completion
  bar.
- `MENTAT_MULTI_AGENT_PIVOT.md`: records the same Vercel product direction.

## Publication gate

- Standing authorization covers staging, commit, push, ready PR publication,
  and merge after clean CI.
- Proposed branch/base: `feature/2c-c-run-messages` into `main`.
- Proposed commit: `Add safe Run message control`.
- Proposed ready PR title: `Add safe Run message control`.
- The local full-suite seed-data failure is excluded from the staged diff;
  clean-checkout CI was the merge gate.
- PR #121 merged after CI, Quality gates, and Native artifact smoke passed.

## Outcome review

- Classification: Successful.
- User continuation: authorized by standing approval.
