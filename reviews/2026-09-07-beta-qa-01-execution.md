# Beta QA batch 1 — execution and visibility

Approved by the owner on September 7, 2026 as the first of seven Beta QA batches.
Baseline: `8eabe696ed7f06286aa786d018f80aad30210672`.

## Scope

- [Run timelines cannot be read for accepted and failed Codex Runs](https://github.com/hazeion/agent-os/issues/211).
- [Codex reports ready but simple Runs fail without an actionable reason](https://github.com/hazeion/agent-os/issues/210).
- Restore bounded canonical event readback, distinguish sign-in from successful
  execution, and expose only fixed, secret-free failure guidance.
- Preserve runtime authority, fixed dispatch configuration, event provenance,
  exact reconciliation, and loopback-only access.

## Verification strategy

Reproduce each reported boundary failure before fixing it. Cover valid and hostile
Python-to-Node event projections, terminal history and reconnect, Codex protocol
compatibility and failure redaction. Run focused tests followed by the relevant
Python and web checks and a production build. Use isolated private test data for
live/browser acceptance; record platform and runtime limitations explicitly.
Require two independent read-only adversarial reviews before close-out.

## Sequence

Timeline and Codex diagnosis proceed in isolated worktrees. Integrate timeline
corrections before the Codex changes, then verify the complete batch. Batch 2
(failed Task recovery and cascade deletion) begins only after this batch is
verified. Existing MDA work remains parked in its original worktrees.

## Evidence

- Baseline `npm ci --ignore-scripts` and production build passed on Windows,
  Node 24.19.0 / Python 3.14.6.
- Baseline `python -m unittest tests.test_run_repository
  tests.test_mentat_local_bridge -q`: 118 tests, 116 passed and two platform skips.
- Baseline `npm run check`: lint/typecheck and all 302 web tests passed.
- Fresh standard setup and launcher with isolated private data: a UI-created
  Conversation accepted the arithmetic prompt. Runs showed Completed without
  an assistant answer; Open timeline displayed the reported unsafe-read error.
- Timeline root cause: the browser shell's exact-key event validator omitted
  `presentation`, which is present even when null on all canonical events.
- Codex investigation found a failed terminal notification followed by a
  reconstructed completed readback. The adapter discarded the notification.
  The local CLI 0.143.0 fails a model/client compatibility check, including a
  direct CLI comparison. The current official CLI 0.153.4, installed only in
  disposable QA artifacts, completes the same fixed Mentat adapter prompt and
  returns exactly `4`. No identity, model, credentials, or sandbox override was
  needed. The user's installed CLI remains unchanged.
- Timeline correction `bf7e972`: production browser readback now displays all
  five retained events from the same baseline Run. Desktop 1280x720 and mobile
  390x844 layouts were inspected, with no page-level horizontal overflow.
- Initial independent review A of the timeline correction: no actionable
  findings. Reviewer independently passed 12 Node tests and the canonical
  Python fixture test.
- Review A identified false-success inference from non-user items after
  observation loss and stale running evidence after child replacement. Both
  were corrected: missing terminal evidence fails closed; live observations
  are generation-bound while terminal evidence is retained.
- Review B identified an oversized numeric timestamp escaping normalization
  and terminating the shared stdout reader. `7029c0a` fixes conversion and
  proves with an actual subprocess that the following RPC still drains.
- Both independent reviewers re-reviewed the final combined state and reported
  no remaining actionable findings.
- Supported Python 3.13.1 verification: 119 timeline/repository/bridge tests
  (two platform skips), 149 Codex/runtime-coexistence/orchestration tests (two
  skips), and the final 46-test Codex suite (two skips) passed. Counts overlap.
- Integrated `npm run check`: lint, typecheck and all 306 web tests passed;
  production build passed. The final numeric-normalization change is Python-only.
- Production Home on the old CLI now shows Failed, the fixed compatibility
  explanation, and Retry. The failure and its guidance survive a stopped-server
  restart. Historical false-completion evidence predating the fix is preserved;
  lost notifications are not reconstructed from an empty transcript.

## Local acceptance and publication status

Final production Retry on the isolated current CLI returned exactly `4` in the
Conversation, as a separate Run with the prior failed attempt retained. Batch 1
is locally verified. macOS/Linux CI and publication have not run; the original
macOS audit environment is not available on this Windows host.
