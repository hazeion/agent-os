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

## Planning language

**Project**:
A durable Mentat-owned planning container that groups Tasks. Project membership
is separate from Task dependencies.
_Avoid_: Task tree, dependency group

**Task**:
A durable operator-owned unit of requested work within one Project. An Agent
assignment names an intended executor but does not start work.
_Avoid_: Conversation turn, Run, delegated job

**Workflow stage**:
The operator-managed planning position of a Task: Inbox, Planned, In progress,
Waiting, Review, or Done.
_Avoid_: Run status, delegation status, blocked state

**Blocked condition**:
A derived reason that a Task cannot proceed, such as an unmet dependency or an
execution condition. It is not a workflow stage.
_Avoid_: Blocked stage, failed Run

**Task dependency**:
A directed prerequisite relationship between Tasks. Dependencies may cross
Projects.
_Avoid_: Project membership, checklist order

**Checklist subtask**:
A Task-owned checklist item that cannot receive an Agent assignment or appear
as a dependency-map node.
_Avoid_: Child Task, nested Task

**Agent assignment**:
An optional reference to the Agent intended to execute a Task. Assignment does
not transfer Task ownership or start a Run or delegation.
_Avoid_: Task ownership, dispatch

**Task dispatch**:
An explicit request for one runtime-neutral execution attempt against a Task.
_Avoid_: Agent assignment, durable delegation

**Durable delegation**:
An explicit Hermes Kanban work item with its own verified lifecycle. It remains
separate from Agent assignment and one-off Task dispatch.
_Avoid_: Task dispatch, queued turn

**Task review cycle**:
The operator-owned decision after an Agent reports completion. The operator may
accept the Task as Done or request another execution attempt with added
instructions while preserving earlier evidence.
_Avoid_: Automatic completion, Run retry

**Agent-created Task**:
An operator-owned Task created through an Agent's explicit Project-scoped
capability during a Run. Creation does not start the new Task or grant broader
Project authority.
_Avoid_: Agent-owned Task, automatic dispatch

**Mentat owner**:
The single human account that owns one Mentat installation and may sign in from
multiple devices.
_Avoid_: Local OS user, browser session, workspace member

**Authoritative Mentat host**:
The one Mentat installation that owns durable state and runtime control for its
owner account. Other devices are clients, not synchronized Mentat peers.
_Avoid_: Synced installation, browser authority

**Associated Conversation**:
A Conversation whose planning context or execution history refers to a Task or
Project. Cascade deletion removes the entire Conversation.
_Avoid_: Conversation link, detachable history

**Cascade deletion**:
One confirmed destructive operation that removes a Project or Task, its
transitive dependent Tasks across Projects, and their associated Mentat work.
_Avoid_: Archive, unlink, soft delete

**Deletion receipt**:
A content-free tombstone that prevents stale events or repeated requests from
recreating deleted work.
_Avoid_: Deleted Task history, archive record
