# Mentat

Mentat is a local-first operations console that owns durable work and delegates
execution to capability-scoped Agent runtimes.

## Language

**Agent**:
A durable Mentat-owned worker identity with a private runtime configuration and
declared capabilities.
_Avoid_: Hermes profile, Codex identity, runtime profile

**Conversation**:
A durable Mentat-owned interaction thread that can be reopened and continued
and that contains messages and one or more Runs.
_Avoid_: Runtime session, runtime thread, chat session

**Run**:
One bounded execution attempt within a Conversation, with its own lifecycle and
normalized events.
_Avoid_: Conversation, session, thread

**Runtime session**:
A private adapter-owned continuity reference used beneath a Mentat Conversation
or Run when a runtime supports it.
_Avoid_: Mentat Conversation, Mentat Run

**Agent Console**:
The prompt-first Mentat workspace for holding Conversations, assigning work to
Agents, observing Runs, and handling operator input.
_Avoid_: Runtime console, Hermes console

**Direct Agent**:
The canonical Mentat Agent used by Direct mode so a person can begin a general
provider/model Conversation without first choosing a custom Agent.
_Avoid_: Agentless Run, anonymous Agent

**Conversation tab**:
An open workspace view of one Conversation, including its Agent identity,
current Run state, transcript, and composer.
_Avoid_: Agent tab, Run tab

**Agent activity rail**:
The global right-side workflow navigator that groups active and attention-worthy
Conversations by Agent. Expanding an Agent reveals its Conversation work items;
selecting a work item focuses or reopens that Conversation tab.
_Avoid_: Run navigator, second transcript, Agent details page

**Queued turn**:
A Conversation turn waiting behind another Run or a temporary admission
boundary.
_Avoid_: Scheduled Task, Agent Message queue

**Conversation turn**:
One accepted user request within a Conversation that may wait or create one or
more execution attempts through Retry or Resume.
_Avoid_: Task, Run, Agent Message

**Waiting for capacity**:
A Conversation projection indicating that Mentat accepted a turn but its
runtime adapter cannot currently admit the next Run.
_Avoid_: Running, scheduled Task, retry loop

**Capacity scope**:
A private runtime-adapter boundary within which Mentat counts admitted Runs.
_Avoid_: Product-wide Run lock, browser-visible runtime identity

**Run configuration snapshot**:
The immutable Agent, runtime-configuration, capability, provider, model, and
effort evidence captured when a Run is admitted.
_Avoid_: Current Agent settings, browser configuration

**Steering message**:
A bounded message intended to influence the active Run immediately when its
runtime advertises steering support.
_Avoid_: Queued turn, follow-up Run

**Reasoning summary**:
A safe, bounded runtime-provided summary of current reasoning progress that may
appear in the expandable Thinking disclosure. It is not private chain-of-thought
or a raw provider reasoning payload.
_Avoid_: Chain-of-thought, raw reasoning, hidden prompt

**Context window**:
The model-reported token capacity and current token use for an execution.
_Avoid_: Conversation surface, transcript, composer
