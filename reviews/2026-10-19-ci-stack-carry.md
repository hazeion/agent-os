# Reviewed CI repair carry

Status: dependency-order publication and hosted verification in progress.

The owner requested finishing the open work, beginning with current checkouts
and CI repair. Carry the reviewed foundation through existing full PRs using
normal merges. Preserve each branch's own work; never force-push or use a
passing ancestor as current-head acceptance.

| PR | Original head | Parent repair | Resolution and local evidence |
| --- | --- | --- | --- |
| 244 | `b83137c` | `fefd987` | Only package manifest/lock conflicts. Both take the byte-identical reviewed parent dependency graph. Agent DDL and Node contract repairs merge normally. Preserve Task/Run completion/navigation and the existing fixed-minute auth fixtures. All 17 Node-contract, recovery-budget and Task-recovery tests pass in one clean run. |

The foundation's two independent reviews, 371 web tests, production build,
32 registry/Node tests, fresh zero-vulnerability npm audit and tracked-secret
gate are recorded in `2026-10-19-ci-foundation-recovery.md`. This carry adds no
new runtime authority, drops no gate and changes no timeout or assertion.
Hosted current-head checks, later branch carries and integrated acceptance
remain incomplete. No PR merge or issue closure is claimed.
