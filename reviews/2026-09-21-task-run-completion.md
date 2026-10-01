# Task execution completion and navigation

Scope: [Reconcile Task and Run state through completion and preserve Task navigation](https://github.com/hazeion/agent-os/issues/227).
Approved through the September 21 owner-workflow goal. Baseline: `8176fa1`;
parent PR 243 remains independently under CI. This slice will receive two
independent subagent reviews and fixes/re-review before any PR push.

## Contract

- Reconcile only the selected Task's nonterminal execution through the existing
  exact-revision refresh capability. Serialize polls, discard obsolete responses,
  preserve unsaved input, and stop when execution becomes terminal/verified.
- Selected Run timeline events trigger bounded canonical readback; never infer
  authoritative Run status from event prose. Keep controls closed while readback
  is uncertain and preserve the open timeline during card updates.
- Explicit Task/Project selection persists safe navigation context. Task-to-Run
  and Run-to-Task links target canonical IDs and do not dispatch work.
- Background activity must not reset drafts, steal focus or create duplicate
  external execution. Existing bridge/runtime authority remains unchanged.

## Verification plan

Test completion without manual refresh, serialized delayed refreshes, selection
races, errors and stale revision recovery, draft preservation, canonical Run
card refresh with retained transcript, and safe round-trip navigation. Run
focused web tests, typecheck/lint and production build. Record two independent
review results before publishing.

## Evidence

Implemented serialized selected-Task reconciliation, exact revision recovery,
bounded coalesced timeline card readback, preserved transcript/control drafts,
explicit uncertain-status recovery, safe Task/Run links and tab-local remembered
planning selection. No runtime mutation or submission capability was added.

Two independent reviews found and reproduced draft loss, an initial
Task-list/execution revision race, stuck controls after timeline close, and
late action-preview responses reopening terminal controls. All were corrected
with regression coverage. Both reviewers re-reviewed the final code and report
no remaining actionable findings; each independently ran seven timeline tests.

Focused planning/contract/timeline suite passed 107 tests before the final two
action-race tests; all seven final timeline tests passed. TypeScript, ESLint and
the production build passed. Final verification after the control guards:
all 377 web tests passed, and the optimized production build passed again.

The parent PR's Windows Python 3.12 CI exposed a separate webhook-fixture
timeout/worker-drain defect. It is diagnosed independently and is not waived as
a passing parent gate. No merged-state or integrated garage acceptance claimed.
