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

The runtime-neutral Python foundation, SQLite authority, Node gateway,
Emerald shell, read-only Agents/Tasks/Runs routes, Run timeline and controls,
production packaging, Codex adapter, runtime coexistence, Agent registry
convergence, and optional Vercel capability adapters are complete through Slice
4A.

Agent Console Slices 1 through 10 are complete. Slice 10 shipped through PR
#160 with schema-17 non-owning Conversation planning context, bounded planning
reads, minimal Project and Task creation, Home planning attention and
draft-only suggestions, exact Task deep links, a hydrated Projects & Tasks
workspace, clean adversarial re-reviews, 52 green PR checks, and production
desktop/mobile browser and Lighthouse acceptance. No later Agent Console slice
is currently approved. Choose the next frontier through the Wayfinder.

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
