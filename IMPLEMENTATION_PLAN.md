# Mentat implementation roadmap

Status: active

This is the short resume map for Mentat. It records current direction and slice
order; it does not authorize work. Every non-trivial slice needs an approved
scope, test strategy, and active review log.

## Read before implementation

1. `AGENTS.md` for repository operating rules.
2. `ARCHITECTURE.md` for authority, capability, and safety boundaries.
3. `CONTEXT.md` for domain language.
4. `MENTAT_WEB_DESIGN.md` for Next.js interface work.
5. The active GitHub Wayfinder ticket and review log for approved scope and
   evidence.

Historical implementation detail belongs in GitHub issues and pull requests,
not in a growing collection of repository narratives.

## Current position

On September 21, 2026 the owner approved implementation of the
[secure owner access and coordinated Project delivery map](https://github.com/hazeion/agent-os/issues/234).
Its native child dependencies are the current work queue. The acceptance
scenario is a garage-organization Project: approved research and layout work
uses supplied goals and measurements to produce a dimensioned layout, editable
linked shopping document and implementation sequence, followed by coordinated
review and revision.

The target is one owner on an always-on Linux host, accessible from ordinary
browsers. Google OIDC uses an operator-owned provider application, explicit
owner enrollment, guided CLI setup and host-admin recovery. Login and
integration consent remain separate. Persistent Agents have scoped Project
roles/context; the owner can assign manually or approve a lead Agent's plan.
Work proceeds within budgets between review checkpoints. The dashboard inbox
holds questions, approvals, failures and results.

### Sequence and resume point

1. [Reconcile and verify the baseline](https://github.com/hazeion/agent-os/issues/235):
   close only evidenced historical fixes; complete next-Run objective previews,
   live completion/navigation and transcript-refresh work; repeat focused
   responsive and fresh-install acceptance.
2. Resolve [Google OIDC authority](https://github.com/hazeion/agent-os/issues/236)
   and [runtime qualification](https://github.com/hazeion/agent-os/issues/237)
   through independent primary-source research.
3. Implement [authorized Project context and deliverables](https://github.com/hazeion/agent-os/issues/238).
4. Implement [approved plans and scoped handoffs](https://github.com/hazeion/agent-os/issues/239).
5. Implement [Project review and owner inbox](https://github.com/hazeion/agent-os/issues/240).
6. Implement [owner login and Linux activation gates](https://github.com/hazeion/agent-os/issues/241)
   after its baseline/auth prerequisites; this track is independent of later
   Project UI work.
7. Verify the [complete garage journey](https://github.com/hazeion/agent-os/issues/242)
   on the integrated product and reconcile remaining tracker state.

Active evidence: [owner workflow review](reviews/2026-09-21-owner-workflow.md).
First implementation slice: finish the readable exact next-Run objective and
review-feedback preview in the
[Task results and requested changes issue](https://github.com/hazeion/agent-os/issues/226).

### Implemented baseline and retained boundaries

Beta QA stabilization merged through
[PR 231](https://github.com/hazeion/agent-os/pull/231); it is no longer awaiting
publication. The original batch review logs remain historical evidence.
The [fresh-install audit](https://github.com/hazeion/agent-os/issues/223) remains
open: merged code is not proof that every acceptance finding is resolved.

Agent Console slices 1-10 and the Projects & Tasks workspace are implemented.
MDA-4A, MDA-4B and MDA-4C merged through PRs 207, 232 and 233. Owner-auth
authority, central gateway policy and the disabled Caddy profile are retained;
remote serving remains disabled until the new authentication and activation
gates pass. Do not repeat completed MDA work.

The approved OIDC direction revises the earlier passkey-only product choice,
but does not change live authority until a reviewed migration implements it.
Project context and runtime-neutral coordination likewise require explicit
capability contracts: current Conversation planning links are navigation-only,
and Conversation Turns must never be repurposed as a durable Task scheduler.
Python retains private data/runtime authority; Node exposes fixed capabilities.

Teams, multi-master sync, a distributed personal-computer fleet, autonomous
capability grants, purchases, external messaging integrations, guaranteed
closed-browser notifications and photorealistic rendering are deferred.
Calendar integration is optional. Hermes cron queueing remains an explicitly
tracked upstream dependency, not a substitute implementation opportunity.

## Completed slices

| Slice | Purpose |
| --- | --- |
| 0 | Safe Hermes webhook hints and readbacks. |
| 1A | Runtime-neutral Agent, Task, Run, event, and runtime contracts. |
| 1B | Durable Mentat Agents and private runtime bindings. |
| 1C-A to 1C-D | SQLite authority for Tasks, Runs, and events. |
| 2A-A | Node gateway, private bridge, Next.js shell, and three desktop and three mobile Lighthouse runs. |
| 2A-B | Emerald Operations shell, navigation, route frames, and shared UI. |
| 2B-A | Read-only Agents route through the fixed bridge. |
| 2B-B | Read-only Tasks route through canonical SQLite Tasks. |
| 2B-C | Read-only Runs route through normalized Run APIs. |
| 2C-A to 2C-D | Run timeline, controls, and supported operator responses. |
| 2D | Production packaging, launch, rollback, and legacy interface cutover. |
| 3A to 3C | Codex runtime, coexistence, and Agent registry convergence. |
| 4A | Optional Vercel Gateway, Sandbox, and Connect adapters. |
| Console 1 | Conversation/message read foundation, Direct Agent identity, and three-column Home. |
| Console 2 | One bounded text Turn, atomic Run reservation, exact replay, and safe Codex readiness. |
| Console 3 | Live transcript, active composer, durable queued turns, steering, and adapter-scoped concurrency. |
| Console 4 | Operator control, recovery, and durable continuation. |
| Console 5 | Composer Agent configuration. |
| Console 6 | Polished transcript and reasoning summaries. |
| Console 7 | Safe rich-link previews. |
| Console 8 | Attachments, Context Packs, images, and artifacts. |
| Console 9 | History depth and command ergonomics. |
| Console 10 | Project and planning context. |
| MDA 4A | Durable owner-auth authority behind disabled remote mode. |
| MDA 4B | Central manifest-backed Gateway Authority with local parity. |
| MDA 4C | Disabled, version-pinned Caddy profile and disposable Linux lifecycle gates. |

## Working rules

- Work on one approved slice at a time from a focused `codex/` branch.
- Build on the existing `web/` app. Do not create another frontend project.
- Keep Python authoritative for local data, SQLite, credentials, Hermes, and
  runtime adapters. Node exposes only named, bounded capabilities.
- Keep Mentat Agent, Conversation, Task, Run, and event identities separate
  from runtime-owned profiles, sessions, threads, and references.
- Keep browser projections safe, bounded, and free of credentials, private
  paths, raw provider payloads, and adapter-owned runtime references.
- Preserve the Python compatibility interface as the explicit rollback path
  until matching workflows, packaging, and rollback tests exist.
- The legacy interface may be retired only after required workflows have parity,
  offline packaging works, lifecycle and recovery checks pass, and rollback is
  tested.
- Reconcile the tracker during slice close-out. Add the child ticket's
  resolution, close it, update the parent Wayfinder decisions and checklist,
  and advance this resume map before calling the slice complete.
- Update this roadmap only when slice status or sequence changes. Keep detailed
  evidence in the active review log and merged pull request.

## Resume checklist

1. Confirm the working tree and branch before editing. Preserve unrelated user
   changes.
2. Read the documents above and inspect the active review log.
3. Verify the slice has explicit approval before implementation.
4. Run focused tests first, then the proportionate full verification suite.
5. Use two independent read-only adversarial reviews for non-trivial slices.
6. Record evidence and the outcome before requesting publication approval.
