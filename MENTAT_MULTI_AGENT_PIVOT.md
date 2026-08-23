# Mentat multi-agent pivot

Status: Target architecture

Use [MENTAT_PIVOT_IMPLEMENTATION_PLAN.md](MENTAT_PIVOT_IMPLEMENTATION_PLAN.md)
for current slice status. Use [ARCHITECTURE.md](ARCHITECTURE.md) for rules that
the current code enforces.

## Product direction

Mentat is moving from a Hermes dashboard to a local multi-agent operations
console.

Mentat owns the work:

- Agent identities
- Tasks and assignments
- Runs and events
- Messages, approvals, artifacts, cost, and outcomes

Agent runtimes execute the work. Hermes is the first supported runtime, but a
Hermes profile is no longer the definition of a Mentat Agent.

```text
Mentat Agent
  -> runtime configuration
  -> runtime identity
  -> model and provider connection
```

These are separate records. A runtime profile, session, thread, or model ID is
an external reference, not a Mentat ID.

## Migration approach

The migration is incremental. Do not rewrite the Python app in one pass.

Keep the parts that already work:

- local and remote Hermes transport
- profiles and provider selection
- task planning and delegation
- run history, attachments, and artifacts
- setup, backup, restore, and migrations
- filesystem and credential protections

Python is becoming the Mentat Local Bridge for local data and Hermes features.
The new web interface and new orchestration work use TypeScript where it helps.

## Target layout

```text
Mentat web interface
        |
        v
Mentat orchestrator
        |
        v
Agent runtime router
   |       |       |
Hermes   Codex   future runtimes
   |
Python Local Bridge
   |
existing Hermes integration
```

Mentat stays local and listens only on loopback. A supported remote Hermes
connection is server to server. The browser never connects to Hermes directly.

## Current web layout

The Next.js app runs through a supervised Node gateway on the configured local
port (8888 by default). The Python app and `public/` interface remain available
only through the explicit `--legacy-ui` rollback switch during cutover.
Node calls the Python Local Bridge through fixed, private capabilities. It does
not get generic access to Python routes, SQLite, files, credentials, or Hermes.

The new interface uses:

```text
Next.js
React
TypeScript
Tailwind CSS
```

Add source-owned shadcn/ui components, Radix primitives, and Lucide icons only
when the interface needs them. Add TanStack Query with the first real server
state consumer.

Use SSE for server-to-browser run events. Use WebSocket only if a later feature
needs two-way realtime traffic that SSE cannot handle cleanly.

The first new routes are:

```text
/agents
/tasks
/runs
```

Keep `public/` working until the new app has matching behavior, production
packaging, and a tested rollback.

## Domain model

Keep these concepts separate:

| Record | Meaning |
| --- | --- |
| Agent | Mentat-owned worker identity |
| AgentRuntime | Software that executes work |
| RuntimeConfig | Settings and external runtime references |
| Model | Model used by a runtime |
| ProviderConnection | Authentication relationship |
| Task | Durable requested work |
| Run | One execution attempt |
| AgentEvent | Normalized runtime activity |
| Capability | Operation a runtime or tool supports |
| Policy | Whether Mentat allows the operation |

The runtime contract must support starting work, reading status, sending a
message, stopping a run, and streaming normalized events when the runtime
advertises those capabilities.

Exact schemas may change. Keep them small and runtime neutral.

## Hermes adapter

Hermes stays behind `HermesRuntime` and the Python Local Bridge.

```text
Mentat runtime contract
  -> HermesRuntime
  -> Python Local Bridge
  -> Hermes transport
  -> Hermes
```

Normalize Hermes data near the adapter. Do not spread Hermes field names or
profile rules through new orchestration code or the web interface.

The normalized event set should cover:

- run started, completed, failed, and stopped
- messages
- tool requests and results
- approval requests
- artifacts
- cost events

Hermes may have a smaller concurrency limit than other runtimes. Keep that
limit inside `HermesRuntime`. It must not block unrelated runtimes.

## State and authority

Mentat is the source of truth for its Agents, Tasks, Runs, and events.

Agents, private runtime bindings, Tasks, Runs, and AgentEvents use owner-private
`mentat.sqlite3`. Existing data roots move their former standalone Agent
registry through the explicit preview-and-confirm convergence workflow; after
cutover, that old file is ignored rather than used as fallback authority.

Tracked JSON files are public-safe examples or recovery inputs. They are not a
second live authority after a SQLite cutover.

Browser state is a projection. It must not become the source of truth for
orchestration records.

## Credentials and tools

Credentials belong to provider or service connections, not Agent records.

```text
Agent
  -> RuntimeConfig
  -> ProviderConnection
  -> credential source
```

Agents receive capabilities, not permanent credentials. Browser responses,
tracked files, logs, and review evidence must not contain credential values.

Shared services should move behind Mentat tool capabilities over time. Google
Calendar is the first likely candidate. Runtime code should not need to know
how a service stores or refreshes credentials.

MCP can describe tools later, but it does not grant authority. A2A may help
independent agents communicate later. Neither is required for the current
pivot.

## Optional infrastructure

Vercel is a first-class, planned optional infrastructure target for Mentat.
Slice 4A will make it a working choice behind Mentat's own connection and
runtime contracts. Using a Vercel service must not require hosting the
local-first Mentat console on Vercel.

- AI Gateway for model access and usage data
- harness or AI SDK adapters for compatible runtimes
- Sandbox for isolated execution
- Connect for OAuth and scoped service access

Keep Mentat types above those services. Vercel types must not become Mentat's
domain model. The Vercel integration must prove all of the following before it
is offered in the product:

- local-only Mentat continues to work without a Vercel account;
- each Vercel service is an explicitly configured, capability-scoped optional
  connection;
- credentials stay server-side and out of Agent records, browser responses,
  tracked files, and logs;
- provider selection, Runs, events, and policy remain Mentat-owned normalized
  records; and
- a disabled or unavailable Vercel service fails closed without blocking other
  runtimes.

The viable option is concrete: an operator can configure a Vercel connection,
see only its declared safe capabilities, assign a compatible Agent, run and
observe work, and disconnect it without disrupting local or Hermes Agents.
AI Gateway, Sandbox, and Connect remain separate adapters. Sandbox provides
isolated execution, not durable Mentat storage or a permanently running server;
Connect provides OAuth-backed service access and never returns tokens to the
browser.

## Delivery phases

The implementation plan splits these phases into reviewable slices.

1. Wrap Hermes behind a runtime-neutral contract.
2. Store Mentat Agents, Tasks, Runs, and events as Mentat-owned records.
3. Build the Next.js operations interface beside the Python app.
4. Show and control one Hermes run through normalized APIs and events.
5. Add Codex as a second runtime.
6. Prove that Hermes and Codex can run at the same time.
7. Converge Mentat-owned relational data into one private SQLite database.
8. Add shared tools, policy, credentials, routing, and agent delegation in later
   slices.

The proof for runtime number two is simple:

```text
Hermes Researcher  Running
Codex Engineer     Running
```

Both runs must be visible and independently controllable through the same
Agent, Task, Run, and event model.

## Rules for implementation

1. Work on one approved slice at a time.
2. Keep the Python app working during the migration.
3. Keep new orchestration code runtime neutral.
4. Keep runtime-specific schemas inside their adapters.
5. Keep Mentat IDs separate from runtime and provider IDs.
6. Keep credentials out of Agents, browser state, tracked files, and logs.
7. Use optional capabilities for features that one runtime does not support.
8. Keep existing filesystem, attachment, remote host, and confirmation checks.
9. Prefer small compatibility seams over broad rewrites.
10. Keep tests green after each slice.

Before changing a Hermes-specific area, decide whether the behavior belongs in
the Hermes adapter or in a runtime-neutral Mentat capability.

## Current work

Do not keep current branch or milestone status in this document. The canonical
sequence and resume point are in
[MENTAT_PIVOT_IMPLEMENTATION_PLAN.md](MENTAT_PIVOT_IMPLEMENTATION_PLAN.md).
