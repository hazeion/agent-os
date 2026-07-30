# Feature Slice Review: Remote Context Telemetry

Status: Ready for publication
Slice: `remote-context-telemetry`
Date: `2026-07-29`

## Slice contract

### Goal

Show trustworthy context tokens used and the total context window after a
remote Agent Console turn, instead of leaving both values unavailable.

### In scope

- Add the exact active-context pair to Hermes Runs status and the completed
  terminal event.
- Use only the latest provider-reported prompt count and the active model
  context length.
- Preserve cumulative input, output, and total billing-token values as
  separate metrics.
- Omit the optional pair when either value is missing, malformed, zero, or
  internally inconsistent.
- Reuse Mentat's existing bounded remote normalization, private history, and
  Console presentation.
- Document and test the coordinated remote contract.

### Out of scope

- Guessing token use from text length, billing totals, or model-name tables.
- Reconstructing telemetry for older runs.
- Exposing prompts, responses, provider credentials, endpoint details, or
  hidden reasoning.
- Changing model selection, compression behavior, or billing calculations.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | A completed remote run with exact provider telemetry shows context used and total context window in Mentat. | Hermes Runs status test plus existing Mentat normalization/UI tests | Pass |
| AC-2 | The same exact pair survives the bounded completed-run SSE event contract. | Hermes run-event test | Pass |
| AC-3 | Missing, zero, malformed, or impossible context values are omitted rather than guessed. | Producer and consumer negative tests | Pass |
| AC-4 | Billing totals remain separate and existing Runs, Console, and remote compatibility behavior still pass. | Focused regression suites | Pass |
| AC-5 | No new secret, path, prompt, response, or browser-to-Hermes exposure is introduced. | Source review and two adversarial reviews | Pass |

### Approval

The user requested this fix for the remote connection and granted standing
approval for slice, test, review, and publication decisions, with secret
protection as the top priority.

## Test strategy

- Prove the current Hermes Runs result omits the context pair, then verify
  status and SSE responses after the producer fix.
- Test zero and over-window values so unavailable measurements cannot appear as
  authoritative numbers.
- Rerun Mentat's Console observability and remote-run suites to verify its
  existing validator and UI.
- Run the affected Hermes Runs/API suite, syntax checks, and patch hygiene.
- Send the final coordinated diff through independent security and
  compatibility reviews.

## Implementation record

- Hermes now builds one bounded usage object for API and Runs execution.
- The optional context pair comes from
  `context_compressor.latest_provider_prompt_tokens` and the active
  `context_length`; no rough estimate or cumulative billing total is used.
- Multi-model MoA runs retain their billing totals but omit active-context
  fields because combined advisor and aggregator usage is not one prompt size.
- Pollable terminal status retains the pair for completed, structured-failure,
  and post-result cancellation states.
- Completed-run SSE events allowlist the same pair and omit invalid optional
  values without dropping otherwise valid billing telemetry. Failed and
  post-result cancelled runs retain the pair in pollable status, which is the
  authoritative state Mentat reconciles.
- Mentat already validates this exact pair, persists only normalized numeric
  values, and renders an explicit unavailable state when the pair is absent.

## Verification

- Hermes Runs, broader API, and structured one-shot usage suites: 362 passed.
- Mentat Console observability, remote runs, runtime switching, attachment UI,
  and Home operations: 95 passed.
- The complete Mentat suite produced
  881 passes, 1 failure, and 4 skips. Its sole failure is the unrelated
  user-owned `data/projects.json` addition of `Daily Check`; that file remains
  untouched.
- Hermes and Mentat Python compilation, browser JavaScript parsing, and
  `git diff --check` passed.

## Adversarial review

- The security review found that Hermes rejected a zero prompt measurement
  while Mentat still accepted it. Remote normalization now requires a positive
  measurement and its malformed-pair test covers zero.
- The compatibility review found the same zero policy remained permissive in
  retained history and the final browser guard. Both now require a positive
  measurement and have regression assertions.
- The compatibility review also found that a MoA turn's combined advisor and
  aggregator billing usage could be mistaken for one active prompt size. The
  producer now omits the optional pair for MoA while keeping billing totals.
- Final compatibility passes requested direct tests for structured-failure and
  post-result cancellation in Hermes, then for normal, recovery, cancellation,
  and shutdown reconciliation in Mentat. Those exact branches now have
  passing tests.
- Final security and compatibility reviews report no remaining P0-P3 findings.

## Publication gate

- Mentat branch: `codex/remote-context-telemetry`, stacked on
  `codex/today-schedule-layout`.
- Hermes branch: `codex/remote-context-telemetry`, stacked on
  `codex/remote-delegation-artifacts-v1`.
- Proposed commits: `fix: retain exact remote context telemetry`; `fix(api):
  expose exact run context usage`.
- User authorization: standing approval.
- Implementation commits: Mentat `6127f07`; Hermes `c2b802f1a`.
- Ready PRs: Mentat https://github.com/hazeion/agent-os/pull/71; Hermes
  https://github.com/hazeion/hermes-agent/pull/5.

## Outcome review

The unavailable remote context display was caused by a producer gap: Mentat
already knew how to validate and render the pair, but Hermes Runs did not send
it. The coordinated fix now carries exact single-model context telemetry
through completed, failed, cancelled, recovery, and retained-history paths.
Unknown, zero, malformed, and multi-model aggregate values remain unavailable
instead of being guessed. All acceptance criteria pass, both adversarial
reviews are clear, and the slice is ready to publish.
