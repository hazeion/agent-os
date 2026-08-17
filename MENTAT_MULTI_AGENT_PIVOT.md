# Mentat Multi-Agent Orchestration Pivot

**Status:** Architectural direction and Codex implementation guide  
**Repository:** `hazeion/agent-os`  
**Date:** 2026-08-17

> **Codex directive:** Read this file with `ARCHITECTURE.md`, `AGENTS.md`, and the relevant implementation files before making architectural changes. This document defines the target direction of the current pivot. Where an existing rule assumes Hermes is the canonical Mentat agent/runtime, preserve current behavior while introducing the migration seams below. **Do not perform a wholesale rewrite.**

## 1. Product direction

Mentat began as a local-first dashboard/control plane around Hermes. It is pivoting into a **web-based multi-agent operations console and orchestrator**.

Target behavior:

- multiple configured agents from different runtimes/providers;
- multiple concurrent agent runs;
- manual task assignment first, dynamic routing later;
- per-agent/run monitoring and event timelines;
- ability to chat with/intervene in each agent run;
- stop/pause controls;
- normalized run events regardless of runtime;
- durable Mentat-owned tasks, runs, messages, approvals, artifacts, cost and outcomes;
- Hermes remains supported as the first runtime, but is no longer the definition of Mentat.

Core principle:

> **Mentat owns workflow and authority. Runtimes supply execution. Models supply intelligence. Infrastructure supplies sandboxing, model access, and credentials.**

## 2. Critical domain-model change

The old architecture intentionally treats a Hermes profile as the canonical executable agent identity and avoids a competing Mentat agent registry.

That rule must change.

The target model is:

```text
Mentat Agent = canonical worker identity
Runtime identity = implementation detail
```

Examples:

```text
Researcher
  runtime: hermes
  runtime identity: Hermes profile "researcher-main"

Software Engineer
  runtime: codex
  runtime identity: Codex runtime configuration

Reviewer
  runtime: claude-code
  runtime identity: Claude runtime configuration
```

Do not remove Hermes profiles. Wrap them beneath a Mentat-owned Agent identity.

## 3. Migration strategy: wrap, do not rewrite

This is a **strangler migration**.

Preserve the mature Python work: Hermes local/remote transport, profiles, provider switching, skills, run history, attachments, artifacts, telemetry, task planning, backup/restore, migrations, local filesystem protections, SQLite/private state, configuration and process management.

Do **not** begin by porting `server.py`, `remote_hermes.py`, or the Python support modules to TypeScript.

The Python application should gradually become the **Mentat Local Bridge**, especially for Hermes and local-machine capabilities.

New orchestration and new web UI work should increasingly use TypeScript.

## 4. Target architecture

```text
                    Mentat Web UI
                  Next.js / TypeScript
                           |
                           v
                  Mentat Orchestrator
            workflow / state / authority
                           |
             Agent Runtime Router
              /          |          \
             /           |           \
      HermesRuntime   CodexRuntime   ClaudeRuntime
           |               \           /
           v                Harness adapter
    Python Local Bridge          |
           |                Sandbox/runtime
     existing Hermes
       integration

                           |
                     Mentat Tools
                           |
                  policy / approvals
                           |
                  credential broker
                           |
             Calendar / GitHub / CRM / Email
```

Keep these concepts distinct:

```text
Agent               worker identity
AgentRuntime        harness/software executing work
Model               intelligence used by a runtime
ProviderConnection  authentication/credential relationship
Task                durable requested work
Run                 one execution attempt
AgentEvent          normalized runtime activity
Tool Capability     operation an agent may request
Policy              whether the operation is authorized
```

## 5. Foundational orchestration types

Start with only the minimum abstractions:

```ts
interface MentatAgent {
  id: string;
  name: string;
  runtimeType: string;
  runtimeConfigId?: string;
  capabilities: string[];
  status: "idle" | "working" | "waiting" | "failed" | "offline";
}

interface MentatTask {
  id: string;
  title: string;
  objective: string;
  status: "queued" | "assigned" | "running" | "blocked" | "completed" | "failed";
  assignedAgentId?: string;
  requiredCapabilities?: string[];
  acceptanceCriteria?: string[];
}

interface AgentRun {
  id: string;
  taskId: string;
  agentId: string;
  runtimeType: string;
  status: "starting" | "running" | "waiting" | "completed" | "failed" | "stopped";
}

interface AgentRuntime {
  startTask(task: MentatTask, context: RuntimeContext): Promise<AgentRun>;
  sendMessage(runId: string, message: string): Promise<void>;
  stop(runId: string): Promise<void>;
  getStatus(runId: string): Promise<AgentRun>;
  streamEvents(runId: string): AsyncIterable<AgentEvent>;
}
```

Exact schemas may evolve. Keep them minimal and runtime-neutral.

## 6. Hermes becomes the first runtime adapter

The existing `HermesConsoleTransport`, local/remote transports, Remote Hermes API, profile support, and run machinery should be reused.

Target:

```text
Mentat AgentRuntime
        |
   HermesRuntime
        |
 Python Local Bridge
        |
existing Hermes transport
        |
      Hermes
```

New Mentat business/orchestration code must not directly depend on Hermes-specific execution APIs.

## 7. Finish the current Hermes webhook work

**Do not abandon the webhook implementation currently in progress.**

It becomes the event-ingestion boundary for `HermesRuntime`.

Target:

```text
Hermes
  -> native webhook
  -> Hermes webhook ingestion
  -> Hermes adapter normalization
  -> Mentat AgentEvent
  -> event store
  -> orchestrator
  -> SSE/WebSocket
  -> web UI
```

Normalize Hermes payloads close to ingress. Do not spread Hermes webhook field names through new orchestration or UI code.

Initial normalized event vocabulary should cover at least:

```text
run.started
message
tool.requested
tool.completed
approval.required
artifact.created
cost
run.completed
run.failed
run.stopped
```

Finish enough webhook work to reliably track lifecycle and progress. Avoid adding new Hermes-specific UI coupling unless required for compatibility.

## 8. Concurrency model

The old globally single Agent Console run must not become the new Mentat orchestration model.

Target:

```text
Hermes Agent -> Run 100
Codex Agent  -> Run 101
Claude Agent -> Run 102
```

all active simultaneously.

`Run` is the concurrency boundary.

Preserve runtime-specific safety constraints inside each adapter. If a particular Hermes installation can only run one job, `HermesRuntime` enforces that without limiting unrelated Codex/Claude runs.

## 9. Frontend direction

New multi-agent UI work should move toward:

```text
Next.js + React + TypeScript
```

Do not rebuild the whole existing dashboard first.

Initial views:

```text
/agents
/tasks
/runs
```

Initial components:

```text
AgentCard
AgentStatus
AgentChat
TaskBoard
RunTimeline
RunControls
```

First UI success criterion:

```text
Hermes Researcher   ● Running   [Open]
Codex Engineer      ● Running   [Open]
Claude Reviewer     ○ Idle      [Assign]
```

Opening a run should show normalized events and allow messaging/stopping where supported.

## 9A. Frontend stack decision

New orchestration UI work should use this default stack unless a concrete requirement justifies otherwise:

```text
Next.js
TypeScript
React

UI
├── Tailwind CSS
├── shadcn/ui
├── Radix UI primitives
└── Lucide icons

Server state
└── TanStack Query

Realtime
├── SSE for primarily server-to-client run/event streams
└── WebSocket only when genuinely bidirectional realtime behavior justifies it
```

### Styling rules

The existing `public/app.js`, `public/index.html`, and `public/styles.css` are **legacy compatibility surfaces during the pivot**. Do not place substantial new multi-agent orchestration UI in those files unless needed to preserve or bridge existing behavior.

Do not perform a one-shot rewrite of the legacy UI. Build the new `/agents`, `/tasks`, and `/runs` surfaces in the new stack while the existing dashboard continues to function. Retire legacy surfaces incrementally after equivalent behavior exists.

Do not mechanically translate the existing large stylesheet into Tailwind classes. Establish semantic design tokens and reusable Mentat components instead. Examples:

```text
AgentCard
StatusBadge
TaskCard
RunTimeline
RunEvent
ToolCall
ApprovalCard
ConnectionStatus
RuntimeBadge
```

Prefer semantic states such as `running`, `waiting`, `needs-approval`, `completed`, `failed`, and `offline` over one-off color values. Preserve Mentat's existing clean dark visual direction while allowing the component system to own layout and styling.

Use shadcn/ui as source-owned component scaffolding and Radix primitives where useful for accessible dialogs, menus, popovers, tabs, tooltips, sheets, forms, and related application UI. Avoid introducing a second large opinionated component framework without a demonstrated need.

Use TanStack Query for ordinary server-state fetching/caching/invalidation. Keep durable orchestration state on the server; do not turn browser state into the source of truth for agents, tasks, or runs. Live run events should layer on top through SSE/WebSocket and update/query-invalidate the relevant server state.

## 10. Mentat becomes the system of record

Provider/runtime objects must not be the authoritative business state.

Long-term orchestration entities should include:

```text
organizations
users
provider_connections
agents
agent_runtime_configs
tasks
runs
messages
events
tool_calls
approvals
artifacts
policies
cost_events
business_outcomes
```

Do not migrate every existing JSON store immediately. Use compatibility adapters and incremental migrations.

The current private SQLite implementation may continue for local/private state. A hosted multi-user version may later use Postgres, but Postgres is not required to establish the runtime abstraction.

## 11. Credentials belong to connections, not agents

Conceptual relationship:

```text
Agent
 -> RuntimeConfig
 -> ProviderConnection
 -> credential / OAuth / gateway identity
```

Agents should receive capabilities, not permanent provider credentials.

Examples:

```text
Codex Engineer -> OpenAI provider connection
Hermes Researcher -> configured Hermes/AI Gateway connection
calendar.* -> Google OAuth connection
```

External SaaS credentials should eventually be brokered through a controlled integration layer rather than injected into arbitrary agent environments.

## 12. Tools become Mentat capabilities

Avoid permanent runtime-specific integrations such as:

```text
Hermes -> Google
Codex -> GitHub
Claude -> CRM
```

Move gradually toward:

```text
Hermes --\
Codex ----> Mentat Tools -> policy -> credential broker -> external service
Claude --/
```

The first strong extraction candidate is Google Calendar.

Target API:

```text
calendar.listEvents
calendar.findAvailability
calendar.getEvent
calendar.createEvent
```

The runtime should not need to know how Google OAuth works.

## 13. Vercel's intended role

Use Vercel where it removes infrastructure plumbing, but keep Mentat-owned abstractions above it.

Potential uses:

- **AI Gateway:** model access, routing/fallback, budgets, usage/cost telemetry.
- **Harness/AI SDK:** common adapter path for Codex, Claude Code and compatible harnesses.
- **Sandbox:** isolated task execution.
- **Connect:** OAuth/API connection lifecycle and scoped/temporary external-service credentials.

Always prefer:

```text
Mentat abstraction -> Vercel adapter -> Vercel service
```

not Vercel-specific types throughout Mentat business logic.

Mentat must continue to own agent identity, task/run state, runtime selection, policy, approvals, customer boundaries and business outcomes.

## 14. MCP and A2A are later

Do not make MCP or A2A prerequisites for the pivot.

MCP may later standardize tool exposure. It describes capability, **not authorization**.

A2A may later standardize delegation/communication between independent agents.

First prove that Mentat can independently start, observe, message and stop at least two different runtimes.

## 15. Routing roadmap

Start with manual/explicit routing:

```text
coding   -> Codex
research -> Hermes
review   -> Claude
```

Later routing may consider capabilities, availability, workload, success rate, cost, latency, policy, risk and model availability.

Do not make an LLM supervisor the foundational authority. Mentat should remain deterministic where possible; an LLM may recommend a route, but Mentat validates and executes it.

## 16. Implementation phases

### Phase 0 — Complete Hermes webhooks

Deliver:

```text
Hermes webhook -> normalized event boundary
```

Centralize ingestion and establish stable `agentId` / `runId` relationships.

### Phase 1 — Introduce the seam

Add:

```text
Agent
Task
Run
AgentEvent
AgentRuntime
```

Wrap current Hermes execution behind `HermesRuntime`.

**Success:** current Hermes behavior still works, but new orchestration code no longer calls Hermes directly.

### Phase 2 — Minimal new web console

Create the TypeScript/React UI for Agents, Tasks and Runs.

**Success:** one Hermes run is visible through normalized events and can be messaged/stopped.

### Phase 3 — Add runtime #2

Add Codex, preferably through a Vercel harness adapter where practical.

**Critical proof milestone:**

```text
Hermes ● Running
Codex  ● Running
```

simultaneously in the same Mentat interface.

### Phase 4 — Extract shared tools

Move Calendar first, then other integrations behind Mentat capabilities.

### Phase 5 — Policy and credentials

Introduce explicit provider connections, approval boundaries, scoped credentials and task-level authority.

### Phase 6 — Dynamic routing

Add capability/load/cost/performance-aware task assignment.

### Phase 7 — Agent-to-agent delegation

Only after the above is stable, evaluate A2A/MCP and richer multi-agent delegation.

## 17. Rules for Codex while implementing the pivot

1. **Do not perform a big-bang rewrite.**
2. Preserve working Hermes behavior while adding seams around it.
3. New orchestration code must be runtime-neutral.
4. Do not let Hermes-native schemas escape the Hermes adapter.
5. Do not let Vercel-native schemas become Mentat's domain model.
6. Mentat owns IDs for Agents, Tasks and Runs.
7. Provider sessions/threads/profile IDs are external/runtime references.
8. Prefer additive migrations and compatibility layers.
9. Keep security boundaries fail-closed where the existing system already does so.
10. Do not weaken existing filesystem, credential, attachment, or remote-host safety checks to make the pivot easier.
11. Keep tests green at each migration step.
12. Prefer small PRs with one architectural seam at a time.
13. Before modifying a Hermes-specific subsystem, ask: **Should this behavior remain Hermes-specific, or should it become a Mentat runtime/tool abstraction?**
14. Do not prematurely generalize functionality that only one runtime currently supports; expose optional runtime capabilities instead.
15. When uncertain, preserve current behavior and introduce the smallest boundary that enables the next runtime.

## 18. Immediate priority

The current priority remains:

> **Finish Hermes webhook support, but shape it as the final major Hermes-specific infrastructure step before introducing the generic AgentRuntime boundary.**

The first architectural PR after webhook completion should be approximately:

```text
architecture: introduce Mentat AgentRuntime boundary
```

It should focus on types/contracts and wrapping existing Hermes behavior, not on adding multiple providers immediately.

The pivotal product proof after that is:

> Mentat can display and operate a Hermes agent and a Codex agent concurrently through the same Agent/Task/Run/Event model.

Once that works, Mentat is no longer a Hermes dashboard. It is a multi-agent orchestrator.

### Implementation status

The first additive Phase 1 seam is implemented on
`codex/mentat-agent-runtime-boundary`: runtime-neutral domain/protocol contracts,
one runtime registry, normalized Hermes run/event projections, and compatibility
delegation to the existing Hermes Console handlers. Durable Mentat Agent
persistence, generic task dispatch, concurrency, runtime #2, and the new web UI
remain separate follow-up slices.
