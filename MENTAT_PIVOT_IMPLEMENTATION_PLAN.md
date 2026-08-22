# Mentat pivot implementation plan

Status: Active roadmap

Last updated: 2026-08-22

This file shows what is complete, what is active, and what comes next. It does
not approve a proposed slice. Each nontrivial slice needs its own approved scope
and test plan.

Read it with:

- [MENTAT_MULTI_AGENT_PIVOT.md](MENTAT_MULTI_AGENT_PIVOT.md) for the target
  architecture
- [ARCHITECTURE.md](ARCHITECTURE.md) for current safety rules
- the active slice review log for exact scope and evidence

## Status labels

- `Complete`: merged into `main`
- `In progress`: approved work on an active branch
- `Proposed`: recommended next slice, not yet approved
- `Provisional`: later work that may change
- `Deferred`: outside the current work window

A feature branch may show its intended post-merge status. The version on
`main` remains canonical.

## Current position

The runtime-neutral Python foundation and SQLite orchestration work are
complete through Slice 1C-D.

Slice 2A-A is complete. PR #114 merged the supervised Node 24 gateway, private
Python health bridge, and repeatable Lighthouse gate without replacing the
Python app.

Slice 2A-B is complete in this branch. It ports the completed Emerald shell
into React and Tailwind before any operational route receives new data
authority.

Slice 2B-A is complete in this branch: the read-only Agents route uses one
fixed bridge and Node API capability. It does not add Agent controls, provider
credentials, or provider switching.

Slice 2B-B is complete in this branch: the read-only Tasks route carries a
small canonical SQLite projection through one fixed bridge and Node API
capability. It does not add Task controls or expose Task details.

## Roadmap

| Slice | Status | Result | Depends on |
| --- | --- | --- | --- |
| 0 | Complete | Hermes webhooks trigger safe Mentat readbacks and normalized events. | Existing Hermes integration |
| 1A | Complete | Runtime-neutral Agent, Task, Run, event, and runtime contracts wrap Hermes. | Slice 0 |
| 1B | Complete | Mentat Agents and runtime bindings are durable and separate. | Slice 1A |
| 1C-A to 1C-D | Complete | SQLite owns Tasks, Runs, and events. Live Task paths no longer use JSON. | Slice 1B |
| 2A-A | Complete | Node 24 gateway, private Python bridge, minimal Next.js shell, and six-run Lighthouse gate. | Slice 1C-D |
| 2A-B | Complete | Emerald Operations shell, tokens, navigation, route frames, and shared UI basics. | Slice 2A-A |
| 2B-A | Complete | Read-only Agents route through one fixed bridge and Node API capability. | Slice 2A-B |
| 2B-B | Complete | Read-only Tasks route backed by Mentat's SQLite Task APIs. | Slice 2B-A |
| 2B-C | Complete | Read-only Runs route backed by normalized Run APIs. | Slice 2B-B |
| 2C-A | Complete in this branch | SSE run timeline with reconnect and bounded event handling. | Slice 2B-C |
| 2C-B | Complete in this branch | Safe preview-confirm stop control for a selected Run. Messaging and approvals need separate contracts. | Slice 2C-A |
| 2C-C | Complete in this branch | Safe preview-confirm text message for a selected active Run. | Slice 2C-B |
| 2C-D | Provisional | Supported approval and clarification responses. | Slice 2C-C |
| 2D | Provisional | Production packaging, launch, rollback, and legacy interface cutover after control parity. | Slice 2C-D |
| 3A | Provisional | Codex runtime adapter with clear capability and credential boundaries. | Slice 2D |
| 3B | Provisional | Hermes and Codex run together in one interface. | Slice 3A |
| 3C | Provisional | Move the Agent Registry into `mentat.sqlite3`. | Slice 3B |
| 4A | Planned | Vercel infrastructure adapter: optional AI Gateway, Sandbox, and Connect behind Mentat contracts. | Slice 3C |
| 4B+ | Deferred | Shared tools, policy, credentials, routing, MCP, and A2A evaluation. | Slice 4A |

## Completed foundation

### Slice 0: Hermes webhook boundary

Hermes webhooks are authenticated freshness hints. Mentat performs its own
readback before changing state.

Evidence is stored in the `reviews/2026-08-10-*`, `reviews/2026-08-14-*`, and
`reviews/2026-08-17-hermes-fallback-retirement-audit.md` records.

### Slice 1A: runtime contract

Mentat has runtime-neutral Agent, Task, Run, event, context, capability, and
runtime contracts. `HermesRuntime` is the first adapter.

Review log: `reviews/2026-08-17-mentat-agent-runtime-boundary.md`

### Slice 1B: durable Agent Registry

Mentat Agents have their own IDs and private SQLite records. Hermes profile
bindings are adapter-owned references and are never returned to the browser.

Review log: `reviews/2026-08-18-mentat-durable-agent-registry.md`

### Slices 1C-A to 1C-D: SQLite orchestration

These slices moved Tasks, Runs, and normalized events into private SQLite
storage.

Important rules:

- `mentat.sqlite3` owns Tasks, Runs, and events.
- `agent-registry.sqlite3` owns Agent identity and runtime bindings until 3C.
- `tasks.json` is a seed or recovery file, not live Task state.
- There is no live dual read or dual write path.
- Runtime-specific limits stay inside their adapters.

Design reference:
`design/system-design/MENTAT_SQLITE_ORCHESTRATION_SYSTEM_DESIGN.docx`

Review logs:

- `reviews/2026-08-18-mentat-sqlite-task-cutover.md`
- `reviews/2026-08-18-mentat-sqlite-run-event-dispatch.md`
- `reviews/2026-08-21-mentat-sqlite-task-cleanup.md`
- `reviews/2026-08-21-pivot-1c-d-closure.md`

## Active frontend work

### Slice 2A-A: Node web foundation

Status: Complete

This slice provides:

- Node `>=24.19.0 <25`, pinned to 24.19.0 in source and CI
- a supervised Next.js production preview on port 8890
- one private Python health capability
- one safe same-origin Node health route
- a prerendered shell with no general React hydration runtime
- three desktop and three mobile Lighthouse runs at 100 in every category

The Python app on port 8888 remains the default product. Node receives no
SQLite, filesystem, credential, Hermes, Task, Run, or Agent authority.

Review log: `reviews/2026-08-21-node-runtime-foundation.md`

Merged in PR #114.

### Slice 2A-B: Emerald Operations shell

Status: Complete

Build on the existing `web/` app. Do not create another frontend project or
another local server.

Scope:

- Emerald semantic tokens and local assets
- responsive navigation and utility bar
- route frames for `/`, `/agents`, `/tasks`, and `/runs`
- accessible shared components needed by those frames
- small client boundaries only where interaction requires them
- the same six-run Lighthouse gate

Keep route content honest. A route with no live data yet must show a clear
foundation state instead of sample operational data.

Do not add real orchestration APIs, TanStack Query, SSE, runtime controls, or
legacy interface removal in this slice.

Design sources:

- the current Emerald compatibility interface
- `public/styles.css`, especially its final Emerald foundation layer
- `public/index.html` for shell composition
- `design/emerald-operations/DESIGN_SYSTEM.md`
- `design/emerald-operations/IMPLEMENTATION_PLAN.md`

## Operational routes

### Slices 2B-A to 2B-C

Add one real vertical route at a time: Agents, Tasks, then Runs.

Each slice must add only the bridge and Node API capabilities that route needs.
Do not add a generic Python proxy. Python and SQLite remain authoritative.

TanStack Query may be added with the first route that needs client-side server
state, caching, or invalidation.

Before the new Home shows Scheduled Automations, the Python API must hide local
Hermes cron data when a remote runtime is selected. That safety fix needs its
own approved backend slice.

### Slices 2C-A and 2C-B

Add event streaming before controls.

2C-A adds normalized SSE with reconnect, bounded history, and explicit
truncation. 2C-B adds one state-bound Stop action. 2C-C adds a separate,
bounded preview-confirm text-message action. 2C-D adds supported approval and
clarification responses. Keeping each mutation contract separate prevents a
generic action route and makes the cutover's control-parity requirement honest.

All browser traffic stays same-origin through Node. Python performs authority,
capability, confirmation, and state checks.

### Slice 2B-A: read-only Agents route

Status: Complete in this branch

This slice makes the canonical Agent list available through one fixed,
read-only Python bridge capability and one safe Node route. The new `/agents`
screen shows only the public Agent projection and gives clear loading, empty,
unavailable, unsupported, and error feedback.

It does not create or switch Agents, configure a provider, accept credentials,
or add a generic bridge proxy.

Review log: `reviews/2026-08-22-agents-read-only-bridge.md`

### Slice 2B-B: read-only Tasks route

Status: Complete in this branch

This slice makes the canonical Task list available through one fixed,
read-only Python bridge capability and one safe Node route. The `/tasks`
screen shows only ID, title, project, status, priority, due date, tags,
attention/review flags, and last-updated time. It gives explicit loading,
empty, unavailable, unsupported, and error feedback.

It does not change Tasks, consult `tasks.json`, expose descriptions or planning
details, add provider controls, or add a generic bridge proxy.

Review log: `reviews/2026-08-22-tasks-read-only-bridge.md`

### Slice 2B-C: read-only Runs route

Status: Complete

This slice makes a bounded canonical Run list available through one fixed,
read-only Python bridge capability and one safe Node route. The `/runs` screen
shows only lifecycle summary fields and gives clear loading, empty,
unavailable, unsupported, and error feedback.

It does not control Runs, stream events, expose runtime references or
revisions, add a details page, or add a generic bridge proxy.

Review log: `reviews/2026-08-22-runs-read-only-bridge.md`

### Slice 2C-A: selected Run timeline SSE

Status: Complete in this branch

This slice adds one selected Run's bounded normalized event timeline. The
browser connects only to a same-origin SSE route. Node validates the Run ID and
reconnect cursor, reads one fixed loopback bridge projection, emits keepalives,
and reconnects through bounded stream windows.

The timeline shows only safe event IDs, sequence, type, timestamp, summary,
and approved numeric usage metrics. It reports unavailable, missing, malformed,
and retention-reset states clearly.

It does not add Run controls, details pages, raw event content, browser-chosen
limits, generic bridge forwarding, or multi-Run streams.

Review log: `reviews/2026-08-22-runs-timeline-sse.md`

### Slice 2C-B: selected Run stop control

Status: Complete in this branch

This slice adds one fixed Stop action for a selected, active, task-bound Run.
The person first receives an exact preview, then confirms it. Python checks the
current Agent and runtime binding, current capability, current Run state, and a
state-bound confirmation while holding the operation lock. It reads the Run
again before reporting that the Stop request was accepted.

It does not add browser-selected actions, direct Hermes access, messages,
steering, approval responses, or generic bridge forwarding.

Review log: `reviews/2026-08-22-run-stop-control.md`

### Slice 2C-C: selected Run message control

Status: Complete in this branch

This slice adds one fixed, text-only message action for a selected active Run.
The person types a bounded message, reviews the exact current state, then
confirms the same message. Python validates current identity, capability,
binding, state, and confirmation before calling the runtime-neutral message
operation. It rechecks the supported run state before returning an accepted
result.

It does not add arbitrary commands, attachments, local-run messaging, approval
responses, generic bridge forwarding, or browser-selected runtime references.

Review log: `reviews/2026-08-22-run-message-control.md`

### Slice 2C-D: selected Run response control

Status: In progress

This slice adds separate fixed review-confirm controls for the current pending
approval or clarification on a selected task-bound Run. Python reads the
current request through the runtime-neutral adapter, validates the active Run,
identity, binding, capability, request kind/ID, allowed choice or bounded text,
and state-bound confirmation, then verifies the resulting runtime state.

It does not add a generic response form, arbitrary commands, message/steer
controls, attachments, local-run responses, browser-selected runtime
references, or legacy Console changes.

Review log: `reviews/2026-08-22-run-response-control.md`

### Slice 2D: production cutover

The source preview is not an installed product. This slice must decide how Node
ships, starts, updates, and rolls back on supported platforms after the
separate Run-message and supported-approval contracts reach parity.

The legacy interface may be retired only after:

- required workflows have parity
- packaging works without network access at launch
- lifecycle and recovery checks pass on supported platforms
- performance and accessibility gates pass
- a tested rollback remains available

## Runtime number two

### Slices 3A and 3B

Node is the web runtime. It is not the second Agent runtime.

3A adds Codex behind the same Mentat runtime contract. 3B proves that Hermes
and Codex can run at the same time and remain independently visible and
controllable.

Do not add dynamic routing until that proof is stable.

### Slice 3C: database convergence

Move Agent identity and runtime bindings from `agent-registry.sqlite3` into
`mentat.sqlite3` through an exact preview, backup, confirmation, and cutover.
Do not create a dual-authority period.

## Optional Vercel infrastructure

### Slice 4A: Vercel infrastructure adapter

Vercel becomes a real, optional infrastructure choice for compatible agent
workloads. This is not a requirement to host the Mentat console on Vercel.

The slice evaluates and, where appropriate, adds capability-scoped adapters
for:

- AI Gateway for model access and usage reporting
- Sandbox for isolated workload execution
- Connect for OAuth-backed, scoped service access

Mentat remains the owner of Agent, provider-connection, Run, event, and policy
records. The integration must be optional, preserve local operation without
Vercel, keep credentials private, and fail closed if a configured service is
unavailable. Exact implementation begins only after the runtime and data model
are stable through Slice 3C.

The Slice 4A completion bar is a working optional connection, not a research
note: an operator can explicitly configure a Vercel connection, see its safe
capabilities, assign a compatible Agent to it, start and observe a bounded
Run, and disconnect it without affecting local or Hermes Agents. AI Gateway,
Sandbox, and Connect remain separate capability-scoped adapters. Sandbox is
for isolated workloads, not Mentat's durable database or permanently running
server. Connect is for OAuth-backed service access; it does not expose tokens
to the browser or replace every provider's authentication flow.

## Working rules

1. Start from current `origin/main` on a focused branch.
2. Work on one approved slice at a time.
3. Keep the Python app and compatibility interface working.
4. Keep Mentat IDs separate from runtime and provider references.
5. Keep runtime-specific schemas inside adapters.
6. Keep credentials out of tracked files, browser state, and review evidence.
7. Update this roadmap when a slice is accepted, split, moved, or removed.
8. Store detailed test evidence in the slice review log.

## Resume checklist

1. Confirm `main` matches `origin/main` and preserve unrelated local work.
2. Read this plan, the pivot, architecture, repository guide, and active review
   log.
3. Resume the first `In progress` slice. If none exists, choose the first
   `Proposed` slice.
4. Confirm the scope and test plan have explicit approval.
5. Continue from the review log's last recorded state.
