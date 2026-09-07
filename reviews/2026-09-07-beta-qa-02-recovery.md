# Beta QA batch 2 — failed Task recovery and cascade deletion

Owner-approved September 7, 2026. Base: `f1797e7` (locally verified batch 1).

## Scope and verification

- [Failed task Run leaves Review, Done and Run once blocked without recovery](https://github.com/hazeion/agent-os/issues/209): expose an explicit recovery action
  for verified terminal failure, keeping all attempt evidence and exact revisions.
- [Project cascade deletion repeatedly fails after a successful preview](https://github.com/hazeion/agent-os/issues/208): reproduce the mixed Task/Conversation/
  retry graph, correct verified deletion, and report partial outcomes honestly.
- Investigate backend paths in isolated worktrees; one owner edits shared Task
  UI and execution authority. Integrate recovery first, then deletion.
- Test canonical failure, stale revision, active/unknown/partial evidence,
  idempotency and rollback. Exercise production UI with isolated private data.
  Run relevant Python/web checks and two independent read-only reviews.

## Evidence

- Baseline production UI reproduced `dispatched · failed` with Review, Done,
  and Run once unavailable and no recovery action. The fixture was created
  entirely through UI operations in the isolated private QA data root.
- The fixture's Project deletion preview matches the original audit exactly:
  one Project, two Tasks, one Conversation, three terminal Runs, no artifacts.
- Real repository reproduction established the exception:
  `conversation_run_identity_immutable` when bulk deletion removes a Retry's
  predecessor before its child. The fix preserves the trigger and deletes
  descendants first. No Conversation Turn cascade change is needed.
- First independent review of deletion commit `b875812`: no actionable
  findings; nine deletion tests plus a 10,000-Run ordering/cycle check passed.
- Recovery uses an explicit note and exact Task/Run revision confirmation,
  preserving the failed attempt and recording the operator resolution. A
  same-second ordering regression uses canonical Task revision to identify
  the latest attempt; nullable review revisions are guarded without inventing
  successful review evidence.
- Both independent reviews of final `97d82b5` plus documentation and the
  ambiguous-outcome deletion notice were clean.
- Integrated web lint/typecheck, all 308 web tests, and production build passed.
  Python 3.13: 238 recovery/deletion/repository/bridge/orchestration tests passed
  (two platform skips); the final ordering change passed 71 focused recovery/
  repository tests (two skips). Counts overlap.
- Production UI: Return to Planned changed the failed attempt to operator-
  resolved, kept failure evidence, and restored Run once. Opening Run once
  required its own confirmation, which was cancelled without dispatch.
- The same exact 1-Project/2-Task/1-Conversation/3-Run cascade then succeeded
  through the UI. Deleted records disappeared from the workspace; canonical
  Run readback retained the one unrelated baseline Run.
- Batch 2 is locally verified. Publication and cross-platform CI remain pending.
