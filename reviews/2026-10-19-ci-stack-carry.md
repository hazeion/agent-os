# Reviewed CI repair carry

Status: dependency-order publication and hosted verification in progress.

The owner requested finishing the open work, beginning with current checkouts
and CI repair. Carry the reviewed foundation through existing full PRs using
normal merges. Preserve each branch's own work; never force-push or use a
passing ancestor as current-head acceptance.

| PR | Original head | Parent repair | Resolution and local evidence |
| --- | --- | --- | --- |
| 244 | `b83137c` | `fefd987` | Only package manifest/lock conflicts. Both take the byte-identical reviewed parent dependency graph. Agent DDL and Node contract repairs merge normally. Preserve Task/Run completion/navigation and the existing fixed-minute auth fixtures. All 17 Node-contract, recovery-budget and Task-recovery tests pass in one clean run. |
| 245 | `6e223ab` | `4cd6b44` | Same dependency-only conflict resolution. Preserve responsive Task inspection and transcript changes. Carry the existing reviewed header-only bridge-refusal fixture and urllib3 2.8.0 locks; the historical security failure is the old 2.7.0 lock audit, not a secret finding. All 57 Node-contract and complete bridge route-class tests pass. |
| 247 | `dcd1516` | `c387bc3` | Dependency-only conflict resolution; verifier code/tests/artifact rules unchanged. Recover missing parent Caddy drain, auth window, orchestration worker cleanup and bridge-refusal fixtures. Two independent carry reviews clear. All 13 identity/Node tests and all 122 Caddy/orchestration/auth tests pass with original deadlines and assertions. |
| 249 | `305ed65` | `0461b93` | Same guarded dependency-only resolution; fixed-host transport, worker and identity implementations unchanged. Inherited fixtures match the reviewed parent. All 24 token/JWK transport, identity and Node-contract tests pass without credentials or owner services. |
| 252 | `0e73d84` | `a50605f` | Guarded dependency-only conflicts; all other inherited changes are the reviewed shared repair/fixtures. Original feature code unchanged. 44 targeted Node/feature tests pass; no skips. Hosted and integrated acceptance remain pending. |
| 254 | `3280e83` | `a6358cd` | Guarded dependency-only conflicts; all other inherited changes are the reviewed shared repair/fixtures. Original feature code unchanged. 32 targeted Node/feature tests pass; no skips. Hosted and integrated acceptance remain pending. |

| 255 | `24bfe1a` | `a623f5a` | Guard stopped for inherited Google transport changes. Two independent reviews clear the existing absolute-deadline/coarse-clock correction and owned-worker close fixture; the ten-second ceiling, capacity and no-retry policy remain. Session issuance feature unchanged. All 47 Node/session/transport/webhook tests pass without skips. |
| 258 | `5f25476` | `fb8fb82` | Guarded dependency-only conflicts; all other inherited changes are the reviewed shared repair/fixtures. Original feature code unchanged. 21 targeted Node/feature tests pass; 1 platform/build skips. Hosted and integrated acceptance remain pending. |
| 259 | `f6fae64` | `16641d7` | Guarded dependency-only conflicts; all other inherited changes are the reviewed shared repair/fixtures. Original feature code unchanged. 15 targeted Node/feature tests pass; 2 platform/build skips. Hosted and integrated acceptance remain pending. |

The foundation's two independent reviews, 371 web tests, production build,
32 registry/Node tests, fresh zero-vulnerability npm audit and tracked-secret
gate are recorded in `2026-10-19-ci-foundation-recovery.md`. This carry adds no
new runtime authority, drops no gate and changes no timeout or assertion.
Hosted current-head checks, later branch carries and integrated acceptance
remain incomplete. No PR merge or issue closure is claimed.
