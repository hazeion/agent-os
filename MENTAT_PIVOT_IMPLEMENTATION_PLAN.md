# Mentat implementation roadmap

Status: active

This is the short resume map for the local-first Mentat migration. It records
current direction and slice order; it does not authorize work. Every non-trivial
slice needs an approved scope, test strategy, and active review log.

## Read before implementation

1. `AGENTS.md` — repository operating rules.
2. `ARCHITECTURE.md` — authority, capability, and safety boundaries.
3. `MENTAT_MULTI_AGENT_PIVOT.md` — target product direction.
4. `CONTEXT.md` — domain language, when present.
5. `MENTAT_WEB_DESIGN.md` and `MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md` — Next.js
   Console work.
6. The active slice review log — approved scope and evidence.

Historical implementation detail belongs in GitHub issues and pull requests,
not in a growing collection of repository narratives.

## Current position

The runtime-neutral Python foundation, SQLite authority, Node gateway,
Emerald shell, read-only Agents/Tasks/Runs routes, Run timeline and controls,
production packaging, Codex adapter, runtime coexistence, Agent registry
convergence, and optional Vercel capability adapters are complete through Slice
4A.

Agent Console Slices 1 and 2 are also complete. The current Wayfinder frontier
is Agent Console Slice 3: live transcript, active composer, queue, steering,
and concurrency (GitHub issue #135). Its scope and test strategy were approved
on 2026-08-27. PR #145 merged after implementation, final verification, both
adversarial review rounds, and the required matrix passed. Post-merge validation
against the existing owner-private data root then exposed one exact pre-release
schema-11 drift and stale legacy attachment projections. The schema-12 repair
and local Hermes steering path are implemented. Final adversarial review then
identified terminal-finalization and queued-continuity races; schema-13
hardening is implemented and the uncontaminated two-runtime browser acceptance
now passes: fresh Hermes and Codex Conversations ran concurrently, both exact
`/steer` operations were accepted without queueing, both final responses stayed
in their owning tabs with separate BigFry assessments, and both right-rail
statuses returned to Idle. The slice remains In progress only until the exact
remediation packet is published, required CI passes, the remediation merges,
and tracker close-out is complete.

## Slice order

| Slice | Status | Purpose |
| --- | --- | --- |
| 0 | Complete | Safe Hermes webhook hints and readbacks. |
| 1A | Complete | Runtime-neutral Agent, Task, Run, event, and runtime contracts. |
| 1B | Complete | Durable Mentat Agents and private runtime bindings. |
| 1C-A to 1C-D | Complete | SQLite authority for Tasks, Runs, and events. |
| 2A-A | Complete | Node gateway, private bridge, Next.js shell, and three desktop and three mobile Lighthouse runs. |
| 2A-B | Complete | Emerald Operations shell, navigation, route frames, and shared UI. |
| 2B-A | Complete | Read-only Agents route through the fixed bridge. |
| 2B-B | Complete | Read-only Tasks route through canonical SQLite Tasks. |
| 2B-C | Complete | Read-only Runs route through normalized Run APIs. |
| 2C-A–2C-D | Complete | Run timeline, controls, and supported operator responses. |
| 2D | Complete | Production packaging, launch, rollback, and legacy interface cutover. |
| 3A–3C | Complete | Codex runtime, coexistence, and Agent registry convergence. |
| 4A | Complete | Optional Vercel Gateway, Sandbox, and Connect adapters. |
| Console 1 | Complete | Conversation/message read foundation, Direct Agent identity, and three-column Home. |
| Console 2 | Complete | One bounded text Turn, atomic Run reservation, exact replay, and safe Codex readiness. |
| Console 3 | In progress | Live transcript, active composer, durable queued turns, steering, and adapter-scoped concurrency. |
| Console 4+ | Proposed | Operator control, recovery, rich rendering, attachments, and deeper operations. |

## Working rules

- Work on one approved slice at a time from a focused `codex/` branch.
- Build on the existing `web/` app; do not create another frontend project.
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
- Treat tracker reconciliation as part of slice close-out: add the child
  ticket's resolution, close it, update the parent Wayfinder decisions and
  checklist, and advance this resume map before calling the slice complete.
- Update this roadmap only when slice status or sequence changes. Keep detailed
  evidence in the active review log.

## Resume checklist

1. Confirm the working tree and branch before editing; preserve unrelated user
   changes.
2. Read the documents in the order above and inspect the active review log.
3. Verify the slice has explicit approval before implementation.
4. Run focused tests first, then the proportionate full verification suite.
5. Use two independent read-only adversarial reviews for non-trivial slices.
6. Record evidence and the outcome before requesting publication approval.
