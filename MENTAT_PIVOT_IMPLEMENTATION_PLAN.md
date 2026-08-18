# Mentat Pivot Implementation Plan

**Status:** Active implementation roadmap
**Last updated:** 2026-08-18

This document translates the architectural phases in
`MENTAT_MULTI_AGENT_PIVOT.md` into small, reviewable delivery slices. It is the
canonical place to determine what has shipped, what is next, and which work is
only provisional.

Read this plan with:

- `MENTAT_MULTI_AGENT_PIVOT.md` for the target architecture and product direction;
- `design/system-design/MENTAT_SQLITE_ORCHESTRATION_SYSTEM_DESIGN.docx` for the
  approved middle-ground SQLite boundary and database-convergence reference;
- `ARCHITECTURE.md` for currently enforced behavior and safety boundaries;
- `AGENTS.md` for repository-wide implementation rules;
- the linked review log for the exact approved contract and evidence of a
  completed or active slice.

Do not treat a provisional slice summary here as implementation authorization.
Every non-trivial slice still requires an approved contract and test strategy in
its own review log before implementation.

## Status legend

- **Complete:** merged into `main`; the linked review log contains the evidence.
- **In progress:** contract and tests are approved on an active feature branch.
- **Proposed:** recommended next boundary; contract and tests still require
  explicit approval.
- **Provisional:** sequenced for planning, but its boundary may change based on
  evidence from earlier slices.
- **Deferred:** intentionally outside the current implementation horizon.

## Current position

Phase 0, the Hermes native-webhook migration and fallback audit, is complete.
The first additive Phase 1 seam is also complete: Mentat now has runtime-neutral
Agent, Task, Run, AgentEvent, RuntimeContext, capability, registry, and
AgentRuntime contracts, with Hermes wrapped as the first runtime adapter.

Slices 1B and 1C-A are complete. The active slice is **1C-B — SQLite Task
Authority Cutover**. The new Next.js frontend begins only after the minimum durable
orchestration state and dispatch boundaries exist, so it can consume real
Mentat-owned APIs instead of embedding Hermes profiles or temporary mock data.

## Slice roadmap

| Slice | Status | Outcome | Dependency |
| --- | --- | --- | --- |
| 0 | Complete | Hermes webhooks wake authoritative Mentat readbacks; compatibility fallbacks are classified and retained or retired deliberately. | Existing Hermes integration |
| 1A | Complete | Runtime-neutral contracts and `HermesRuntime` adapter surround existing Console execution. | Slice 0 |
| 1B | Complete | Durable Mentat Agent identities and separate runtime-configuration bindings. | Slice 1A |
| 1C-A | Complete | Extend the existing private `mentat.sqlite3` with a canonical Task repository, exact migration preview, deterministic export, and backup-safe schema migration; do not cut over live APIs yet. | Slice 1B |
| 1C-B | In progress | Atomically migrate `tasks.json` and cut every live Task workflow over to SQLite with no dual reads or writes. | Slice 1C-A |
| 1C-C | Provisional | Durable Run and AgentEvent journals, generic runtime-neutral dispatch, reconciliation, and bounded retention. | Slice 1C-B |
| 1C-D | Provisional | Remove obsolete Task JSON runtime paths, finish operational evidence and compatibility cleanup, and enforce browser/Lighthouse quality gates. | Slice 1C-C |
| 2A | Provisional | Next.js/React/TypeScript/Tailwind application foundation and shared Mentat design system. | Slice 1C-D |
| 2B | Provisional | Agents, Tasks, and Runs views backed by real orchestration APIs. | Slice 2A |
| 2C | Provisional | Normalized SSE run timeline, per-run messaging, stop controls, and supported approvals. | Slice 2B |
| 3A | Provisional | Codex runtime adapter with explicit capability and credential boundaries. | Slice 2C |
| 3B | Provisional | Hermes and Codex run concurrently in the same Mentat interface. | Slice 3A |
| 3C | Provisional | Migrate the separate Agent Registry into `mentat.sqlite3` so all Mentat-owned durable relational state uses one unified database and backup unit. | Slice 3B |
| 4+ | Deferred | Shared tools, policy and credentials, dynamic routing, then evaluated A2A/MCP delegation. | Slice 3C |

## Slice details

### Slice 0 — Hermes webhook boundary

Status: **Complete**

Hermes native webhooks are bounded, authenticated freshness hints. Mentat
discards untrusted event-specific payload fields, performs authoritative
read-back, and retains reconciliation where required. Completed Milestone 9
review records under `reviews/2026-08-10-*`, `reviews/2026-08-14-*`, and
`reviews/2026-08-17-hermes-fallback-retirement-audit.md` contain the exact
contracts and evidence.

### Slice 1A — AgentRuntime boundary

Status: **Complete**

Outcome:

- runtime-neutral Agent, Task, Run, AgentEvent, RuntimeContext, capability, and
  AgentRuntime contracts;
- one deterministic runtime registry;
- Hermes run/event normalization;
- compatibility delegation to the existing Hermes Console handlers;
- no second runtime, concurrency, durable Agent registry, or new UI.

Review log: `reviews/2026-08-17-mentat-agent-runtime-boundary.md`

### Slice 1B — Durable Agent Registry and Runtime Bindings

Status: **Complete**

Smallest useful outcome:

> Mentat can create and retrieve persistent Mentat-owned agents whose identity
> remains separate from their Hermes runtime/profile binding.

Recommended boundary:

- add owner-private SQLite storage for Mentat Agents and runtime configurations;
- store Agent identity, name, declared capabilities, runtime type, and a
  separate adapter-owned runtime binding;
- expose bounded runtime-neutral create/list operations;
- preserve Agents across restart and the existing private backup/restore path;
- keep `data/agents.json` as heartbeat observations, not the canonical registry;
- support Hermes bindings only in this slice without storing credentials;
- leave edits, deletion, execution dispatch, UI, and profile auto-import for
  separately approved work.

The approved acceptance criteria, tests, branch, rollback behavior, current
evidence, and resume point are recorded in
`reviews/2026-08-18-mentat-durable-agent-registry.md`.

### Slices 1C-A through 1C-D — SQLite orchestration foundation and cutover

Status: **1C-A complete; 1C-B in progress; later slices provisional**

Approved architectural boundary:

- extend the existing owner-private `mentat.sqlite3`; do not create a third
  orchestration database;
- make SQLite authoritative for Mentat-owned Tasks, Runs, and normalized
  AgentEvents after exact migration and cutover;
- keep `agent-registry.sqlite3` authoritative for Agent identities and private
  runtime bindings until Slice 3C;
- retire `tasks.json` as live state without a dual-read or dual-write period;
- preserve current task API shapes and all validated planning/delegation
  metadata through the migration;
- keep Hermes capacity, submission, and safety limits inside `HermesRuntime`;
- do not add dynamic routing, a second runtime, or the new frontend in 1C.

Delivery is split so schema safety and reconstruction proof land before the
destructive source-of-truth cutover:

1. **1C-A:** schema, repository, exact read-only migration preview,
   transaction-tested import primitive, deterministic export, and private
   backup/restore evidence. Live task APIs continue to use `tasks.json`.
2. **1C-B:** exact state-bound import and atomic API/storage cutover. After
   success, no runtime Task path reads or writes `tasks.json`. A singleton
   SQLite authority receipt commits with the exact imported collection, so an
   empty store is still durably cut over and stale JSON can never be re-imported
   or used as fallback. An explicit server-stopped, token-bound `mentat
   task-export` workflow can refresh the legacy document, while its
   `--compatible-root` mode publishes a validated schema-5 sibling data root
   with empty Task tables and exported JSON as the old build's sole Task
   authority, without changing live authority. Because credentials are
   excluded, compatible-root export fails closed for an actively selected
   remote Hermes connection and requires explicit remote reconfiguration in
   the old-build sibling.
3. **1C-C:** durable Runs, append-only AgentEvents, dispatch reservations,
   reconciliation, and fixed bounded retention that never removes active or
   waiting Runs and marks truncated timelines explicitly.
4. **1C-D:** obsolete-path cleanup, operator documentation, full compatibility
   evidence, browser smoke, and repeatable Lighthouse 100/100/100/100.

System design reference:
`design/system-design/MENTAT_SQLITE_ORCHESTRATION_SYSTEM_DESIGN.docx`

Active contract and evidence:
`reviews/2026-08-18-mentat-sqlite-task-cutover.md`

### Slice 2A — New frontend foundation

Status: **Provisional**

Expected stack:

```text
Next.js + React + TypeScript
Tailwind CSS
shadcn/ui + Radix UI primitives
Lucide icons
TanStack Query
SSE first; WebSocket only when bidirectional realtime requires it
```

Expected boundary:

- introduce the new application shell without replacing the Python Local Bridge;
- establish semantic design tokens and source-owned reusable components;
- preserve Mentat's clean dark visual direction;
- keep the existing `public/` frontend operational as a compatibility surface;
- do not mechanically translate the legacy stylesheet into Tailwind utilities.

### Slices 2B and 2C — Operational web console

Status: **Provisional**

Build `/agents`, `/tasks`, and `/runs` against real Mentat-owned APIs, then add
normalized event streaming and only the run controls advertised by each
runtime. Durable server state remains authoritative; browser state and SSE are
projections.

### Slices 3A and 3B — Runtime number two

Status: **Provisional**

Add Codex behind the same runtime-neutral contract, with provider authentication
kept separate from Agent identity. The proof milestone is two independent runs:

```text
Hermes Researcher  ● Running
Codex Engineer     ● Running
```

Both must be visible and independently controllable through the same
Agent/Task/Run/Event model. Do not begin dynamic routing until this proof is
stable.

### Slice 3C — Unified Mentat database convergence

Status: **Provisional**

After the two-runtime proof, migrate Agent identities and runtime bindings from
`agent-registry.sqlite3` into `mentat.sqlite3` through the same preview,
backup, exact-confirmation, and no-dual-authority discipline used for Tasks.
This is the intended long-term local architecture: one owner-private SQLite
database for Mentat-owned relational state. Credential values and Hermes-owned
state remain outside it. Complete this convergence before shared-tool policy or
dynamic-routing work unless operational evidence supports an explicitly
reviewed resequencing.

## Sequencing rules

1. Work on one approved slice at a time.
2. Start each slice from current `origin/main` on a dedicated feature branch.
3. Preserve the Python Local Bridge and legacy frontend until replacement
   behavior is verified.
4. Keep Mentat IDs distinct from runtime/provider references.
5. Keep runtime-specific schemas inside their adapters.
6. Never store credentials in Agent records, tracked JSON, browser state, or
   review evidence.
7. Update this roadmap only when a slice is accepted, resequenced, split, or
   removed; keep exact verification evidence in the slice review log.
8. Do not start a later slice merely because it appears in this roadmap.

## Resume checklist

When work resumes after an interruption:

1. Confirm `main` matches `origin/main` and preserve unrelated local changes.
2. Read this plan, the pivot, architecture, repository guide, and latest slice
   review log.
3. Resume an **In progress** slice first; otherwise identify the first
   **Proposed** slice. Do not skip unresolved work.
4. Verify its contract and test strategy have explicit user approval.
5. Continue from the review log's recorded resume point.
