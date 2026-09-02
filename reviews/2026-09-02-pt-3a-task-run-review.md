# PT-3A review log — Task Run once and review cycles

Issue: [#178](https://github.com/hazeion/agent-os/issues/178)
Wayfinder map: [#165](https://github.com/hazeion/agent-os/issues/165)
Branch: `codex/pt-3a-task-run-review`

## Approved scope

- Add an exact-revision, assigned-Agent Task **Run once** lifecycle that creates
  one durable private execution attempt.
- Promote only a verified, non-partial terminal Run to Review; keep prior Run
  evidence intact.
- Let an operator explicitly Accept a reviewed Task into Done or Request
  changes back to Planned. Requesting changes never retries automatically.
- Expose only fixed, safe planning-execution projections and same-origin named
  routes. No runtime binding, provider reference, credential, or arbitrary
  execution capability reaches the browser.

## Explicit exclusions

- No Agent-created work, Task delegation, automatic retries, generic runtime
  control, or background scheduler changes. Those remain PT-3B/PT-3C work.

## Verification and review record

- Focused Python execution, bridge, schema migration, private-backup, and
  orchestration tests passed. The focused execution lifecycle suite passed
  4/4 in 1.6 seconds; schema/backup compatibility coverage passed 24/24.
- The independent reviewer found and the implementation corrected stale
  post-reservation revision handling, missing completion promotion wiring,
  backup schema compatibility, and exact bridge/route validation gaps.
- A second independent UI/concurrency review found no remaining product or
  boundary defect. It verified task ID/revision gating across List and Map
  selection, delayed stage saves, stale execution reads, confirmations, and
  review mutations.
- The full web suite passed: 260/260 in 23.5 seconds. Production lint,
  type checking, and optimized Next build passed.
- A temporary test fixture initially made a normal Task projection look like
  an execution projection. The public parser correctly rejected it, then a
  DOM-node equality assertion amplified the ordinary failure into an OOM while
  formatting repeated diffs. The fixtures now keep normal and execution
  projections separate, and the assertion checks a boolean. The focused UI
  suite passes 31/31 in 8.6 seconds; no production render loop was present.

## Browser acceptance

- In a fresh isolated local preview, selected a planned Task, opened its exact
  Run once confirmation, and cancelled it without dispatching the task.
- Moved that Task to Inbox and verified Run once became unavailable, then back
  to Planned and verified Run once returned without a page reload.
- This browser run used disposable local authority data and did not dispatch
  the user-visible research Task.
