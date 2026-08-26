# Mentat Next.js Agent Console specification

Status: implementation planning baseline

This document defines the approved product behavior and target technical
contract for the Next.js Agent Console. It plans production work; it does not
authorize or implement a slice. Each implementation slice still requires
explicit approval under the repository's review process.

Use this document with:

1. [MENTAT_WEB_DESIGN.md](MENTAT_WEB_DESIGN.md) for visual authority;
2. [ARCHITECTURE.md](ARCHITECTURE.md) for implemented safety and ownership
   boundaries;
3. [CONTEXT.md](CONTEXT.md) for canonical domain language;
4. [ADR 0001](docs/adr/0001-conversation-owned-agent-console.md) for the
   Conversation, queue, concurrency, and recovery decision;
5. the Agent Console Wayfinder map in GitHub Issues for ticket order and
   blocking relationships.

Older Emerald and Python Console documents are conditional references under the
reading policy in `MENTAT_WEB_DESIGN.md`. They are not required reading unless
this specification identifies a concrete gap.

## Destination

Deliver a fast, prompt-first, Agent-first Next.js Console where a person can:

- choose an Agent or use the built-in Direct Agent;
- start, revisit, and continue durable Conversations;
- observe useful live progress without exposing raw runtime internals;
- keep typing and queue follow-up turns while work continues;
- steer a compatible active Run with `/steer`;
- operate multiple compatible Agents and Conversations concurrently;
- stop work, answer approvals or clarifications, recover from failures, and
  review generated artifacts;
- select the Agent's provider, model, and effort through the safe configuration
  workflow directly from the composer;
- read polished text, code, local images, artifacts, and safe rich-link cards;
- refresh or reopen Mentat without losing accepted Conversation state.

The Console must look and behave like the approved Mentat composition while
preserving Python and Mentat's private storage as the authority boundary.

## Locked product decisions

These decisions are resolved and must not be reopened inside an implementation
slice without a new product decision ticket.

| Area | Decision |
| --- | --- |
| Primary unit | A tab represents one durable Conversation. A Run is one execution attempt inside it. |
| Agent ownership | A Conversation has one immutable Agent. Changing Agent starts another Conversation. |
| Direct mode | Direct mode uses a canonical built-in Direct Agent; it is not Agentless execution. |
| New Conversation | New Conversation defaults to the currently selected Agent, including the Direct Agent. |
| Concurrent work | One active Run per Conversation. Compatible Conversations and Agents may run concurrently. |
| Runtime capacity | Each adapter declares and enforces its capacity. Capacity pressure is visible as `Waiting for capacity`. |
| Routine Send | Sending ordinary text is sufficient authorization to create the user turn and start its Run. No confirmation modal is added. |
| Active composer | The composer remains writable while a Run is active. Ordinary text enters the Conversation's pending-turn queue. |
| Queue | At most eight queue-active turns per Conversation, FIFO, durable across refresh, editable and cancellable before dispatch. Reordering is deferred. |
| Queue continuation | Verified successful completion may dispatch the next turn. Stop, failure, unknown, interruption, or capacity blockage pauses automatic dispatch for operator action. |
| Steering | `/steer` at the beginning of submitted text targets only the active Run and only when its runtime advertises steering. It is never silently queued. |
| Stop | Stop is a distinct explicit action and does not imply closing, archiving, or deleting the Conversation. |
| Approvals | Approval and clarification requests are dedicated inline cards and right-rail attention items; ordinary composer text cannot answer them accidentally. |
| Recovery | Mentat reconciles nonterminal Runs before presenting them after restart. Retry creates a new Run and preserves failed evidence. Resume appears only when advertised by the runtime. |
| Provider configuration | Provider, model, and effort controls remain in the composer. Changes go through the selected Agent's safe configuration workflow and affect the next Run, never the active Run. |
| Run configuration | Every Run captures an immutable execution-configuration snapshot. Secrets and adapter references remain private. |
| History | Conversations persist until explicit deletion. Closing a tab only closes the view. Archive is reversible. Delete is deferred beyond the first milestone and will require confirmation. |
| Thinking | The expandable Thinking disclosure contains only safe runtime-provided reasoning summaries. It opens while active, collapses after reasoning ends, and may be reopened. Raw chain-of-thought is prohibited. |
| Rich links | Public HTTPS links may receive automatic server-fetched previews after message submission through the bounded link-preview capability. A fallback link remains usable when previewing is blocked or unavailable. |
| Keyboard | Enter sends; Shift+Enter inserts a newline. The one-line composer grows to a fixed maximum and then scrolls. |

## Product composition

### Left workspace rail

The left rail contains Mentat workspace navigation in this order:

- Home;
- Agents;
- Projects & Tasks;
- Calendar;
- Runs;
- Settings.

It collapses to an icon rail. The seam handle remains at the shared app-level
vertical center in both states.

### Center Conversation workspace

The center is always the dominant surface:

1. a compact Conversation tab strip;
2. a large, scrollable transcript and context surface;
3. a compact pending-turn queue when nonempty;
4. a one-line prompt composer that grows only to a fixed maximum;
5. quiet Agent, provider, model, and effort selectors in the composer footer;
6. attachment and Context Pack controls as compact secondary actions;
7. Send or Stop as the clear primary Run action for the current state.

The initial empty Conversation keeps the approved “What can Mentat help with?”
prompt and suggestion cards without filling the transcript area with dashboard
cards.

### Right Agent activity rail

The right rail groups active or attention-worthy Conversations by Agent.

- Selecting an Agent row expands or collapses its work list.
- Selecting a Conversation focuses its existing tab or reopens the persisted
  Conversation in a new tab.
- Each Conversation item shows its current Run or attention state.
- Selection never starts, stops, archives, deletes, or changes Agent ownership.
- Closing a tab never stops its active Run.

The right rail collapses fully except for its seam and centered handle. The
handle stays above the center workspace and aligns with the left handle.

## Domain and persistence contract

### Conversation

A new Mentat-owned private SQLite record with:

- opaque Conversation ID;
- immutable Mentat Agent ID;
- bounded title and title source;
- active or archived state;
- monotonic revision;
- created, updated, and archived timestamps;
- optional safe project or Task association;
- no runtime session, provider credential, local path, or adapter-owned ID in
  its browser projection.

Conversation title initially derives from a bounded first-prompt summary. Manual
rename and delete are later features. Archive is reversible.

### Conversation message

A durable ordered transcript record with:

- opaque message ID and Conversation ID;
- role from the fixed Mentat role vocabulary;
- optional Run ID;
- monotonic Conversation sequence;
- bounded, versioned safe content blocks;
- accepted or cancelled lifecycle state;
- created timestamp and immutable source key.

User text is limited to the existing safe Console input limit of 6,000
characters. A text content block is limited to 20,000 characters. Large runtime
outputs must become bounded parts or artifacts rather than bypassing limits.
Assistant message events are projected idempotently into Conversation messages;
raw provider payloads are never transcript authority.

### Pending turn

A durable Conversation-scoped user turn with:

- opaque ID and Conversation ID;
- FIFO position;
- bounded text;
- state: `pending`, `dispatching`, `consumed`, `blocked`, or `cancelled`;
- optional bound Run ID after dispatch begins;
- monotonic revision and timestamps.

At most eight `pending`, `blocked`, or `dispatching` turns may exist for one
Conversation.
Editing and cancellation require the expected current revision. Cancellation is
a state transition, not physical deletion. A pending turn has no timer, retry
schedule, Task authority, or cross-Conversation routing.

### Run extensions

Canonical Runs gain an optional Conversation ID for Console-source execution.
The repository must enforce at most one nonterminal Run per Conversation.
Task-dispatch Runs retain their existing Task identity and authority rules.

Every Conversation Run stores an immutable private configuration snapshot:

- Mentat Agent ID and revision;
- runtime type and runtime-configuration digest;
- safe provider, model, and effort identity when applicable;
- declared capabilities at admission;
- no credential value or browser-selected adapter reference.

Existing normalized Run events remain the activity and diagnostic journal.
Conversation messages remain readable after detailed Run events are pruned.

### Direct Agent

Direct mode resolves to one seeded canonical Mentat Agent. Its provider, model,
and effort may be changed from the composer through the same safe Agent
configuration workflow. It is subject to the same Run snapshots, capability
checks, concurrency rules, and private runtime boundary as any other Agent.
Mentat must not share or fabricate its RuntimeConfig; if no supported unclaimed
binding can be validated, Direct mode is visibly setup-required.

### Browser-local presentation state

Open tab IDs, selected tab, rail collapse state, unsent per-Conversation drafts,
and dismissed cosmetic disclosures may be stored locally in the browser. They
are presentation state, never authority for Conversation messages, queued turns,
Runs, approvals, or configuration.

## Lifecycle contracts

### Create and send

1. The user selects an Agent or accepts the current Direct Agent.
2. New Conversation creates the durable Conversation before execution.
3. Send immediately paints a visibly pending user message without blocking
   typing.
4. The fixed server capability validates Agent/configuration, text,
   one-active-Run admission, queue bounds, and adapter capacity.
5. Mentat commits the user message, turn, and idempotency evidence. It also
   commits a Run reservation when capacity is available; otherwise the accepted
   turn becomes visibly blocked without fabricating a Run.
6. Accepted dispatch returns the canonical IDs and state. Rejection restores the
   draft and visibly marks the optimistic message as unsent.
7. The runtime-neutral orchestration layer performs at most one submission
   attempt and reconciles the exact Run.

The browser may generate an opaque idempotency key, but the server validates and
owns its meaning. Repeating a request with the same key and digest returns the
same result; a changed digest fails closed.

### Send during an active Run

Ordinary text creates a Pending turn. The composer clears only after the server
accepts it. The compact queue permits edit or cancel while the turn remains
`pending`.

After a verified successful terminal state, Mentat may atomically claim the
oldest pending turn and attempt its next Run. It must revalidate Conversation
revision, Agent binding, safe configuration, and capacity. Any ambiguous or
failed transition becomes visible and pauses the queue.

A capacity-blocked turn has no Run to retry. Its explicit Continue action
revalidates admission and either reserves its first Run or remains visibly
blocked; it never waits on a background scheduler.

### Steering

`/steer` is recognized only when it begins submitted text after leading
whitespace normalization. The command text is sent through the fixed,
capability-gated, exact-Run steering operation.

- It works only while the selected Conversation has a compatible active Run.
- It never becomes a pending turn.
- If unsupported, stale, too late, rejected, or not active, the composer keeps
  the text and explains why nothing was sent.
- Accepted-but-unverified steering is partial/unknown and is not retried.
- Steering text and private runtime references follow the existing bounded audit
  rules.

There is no Steer button.

### Stop, failure, retry, and resume

Stop retains the existing exact-Run preview/confirmation and reconciliation
boundary. It pauses pending-turn auto-dispatch. Closing a tab does not stop.

Failure, interrupted, stopped, unknown, and partial states remain distinct. A
Retry action creates a new Run in the same Conversation from explicitly reviewed
input and a newly validated configuration snapshot. It never overwrites the old
Run. Resume appears only when an adapter advertises a fixed resumable capability
and exact identity can be revalidated.

### Approval and clarification

Pending actions use dedicated inline cards with their own bounded, revision-bound
response controls. The same request appears as an attention item in the Agent
activity rail. Switching Conversations or closing a tab does not dismiss it.
Ordinary Send never answers a pending action.

### Refresh and reopening

On load, Mentat reads canonical Conversations, messages, pending turns, Runs,
and pending actions. Every nonterminal Run is reconciled through its runtime
adapter before the UI asserts a live status. Old local `running` evidence alone
is insufficient. The selected Conversation may render cached safe content while
reconciliation is visibly pending, but action controls fail closed until the
authoritative state is known.

## Provider, model, and effort behavior

The composer always displays the effective Agent, provider, model, and effort.

- Selectors are quiet dropdowns rather than bordered cards.
- During an active Run, its immutable snapshot remains visible.
- A permitted change is staged for the next Run and enters the Agent's existing
  safe configuration workflow.
- Provider/model changes use authenticated inventory only, exact preview and
  confirmation where required, active-Run protection, verification, and rollback
  behavior from `ARCHITECTURE.md`.
- Unsupported or read-only adapters leave the control visible with a concise
  explanation rather than presenting a false choice.
- Browser input never chooses an executable, working directory, credential
  source, runtime session/thread, or private provider reference.

## Transcript and content presentation

### Hierarchy

Messages remain primary. Run boundaries and concise progress cues are secondary.
Detailed safe tool activity is grouped under an expandable Activity disclosure.
Raw runtime payloads, commands, arguments, results, logs, paths, and secrets are
never rendered.

### Thinking disclosure

The Thinking disclosure:

- appears only for a safe runtime-provided reasoning summary;
- expands while reasoning is active;
- uses restrained motion and a concise live label;
- collapses automatically when reasoning ends;
- remains manually reopenable;
- respects reduced-motion preferences;
- never contains raw chain-of-thought or provider reasoning payloads.

### Code

Fenced code renders with language-aware highlighting, wrapping/scrolling that
does not create page overflow, and a copy action. Code is inert text: Mentat does
not execute it, transform it into commands, or trust embedded HTML.

### Images and artifacts

Only validated attachment/artifact IDs may resolve through same-origin safe
Mentat content routes. The browser never receives an absolute path, blob key,
hash, or arbitrary file URL. Inline images include bounded dimensions, loading
states, alt-text treatment, and a review/download action where permitted.

### Rich links

Rich previews begin only after the containing message is submitted. The
project-owned link-preview capability:

- accepts only normalized public `https` URLs;
- sends no browser cookies, authorization headers, or Mentat credentials;
- blocks loopback, link-local, private, reserved, multicast, and other
  non-public destinations before connection and after every DNS resolution;
- revalidates every redirect and limits redirect count;
- applies strict connect/read timeouts, response-byte limits, and allowed MIME
  types;
- parses only bounded title, description, site name, canonical URL, and image
  metadata;
- sanitizes text and never returns arbitrary HTML;
- proxies and caches permitted preview images through a separate bounded safe
  route;
- records `pending`, `ready`, `unavailable`, or `blocked` without blocking the
  message;
- supports a global Rich link previews setting, enabled by default.

Sites without usable OpenGraph metadata, sites that block automation, and
unsafe or unreachable targets receive a polished plain-link fallback. “Most
websites” is a best-effort compatibility goal, not permission to weaken the
network boundary.

## Fixed web and bridge capabilities

Exact route names may be adjusted by the owning implementation ticket, but the
capability separation is mandatory. Do not combine these into a generic proxy.

| Capability | Web shape | Authority behavior |
| --- | --- | --- |
| List Conversations | bounded cursor-paginated `GET` | Safe summaries only; active/attention first where requested. |
| Read Conversation | fixed Conversation `GET` | Bounded messages, queued turns, Run summaries, pending action, safe config projection. |
| Create Conversation | fixed `POST` | Validates canonical Agent; creates no Run by itself. |
| Submit turn | fixed Conversation `POST` | Idempotent; creates immediate Run or durable pending turn according to active state. |
| Edit/cancel pending turn | separate revision-bound mutations | Pending state only; no physical deletion. |
| Retry Run | separate fixed mutation | Creates a new Run; never mutates terminal evidence. |
| Steer Run | separate fixed mutation | Capability-gated exact active Run; no arbitrary command passthrough. |
| Stop Run | existing preview/confirm mutation | Exact state-bound confirmation and readback. |
| Respond to pending action | existing preview/confirm mutation | Exact request and Run binding. |
| Configure Agent | dedicated inventory/preview/confirm capabilities | Affects next Run; no credential or private reference exposure. |
| Read Agent activity | bounded global projection | Agent identity plus Conversation/Run/attention summaries only. |
| Stream selected Run | existing same-origin bounded SSE | One detailed selected-Run stream at a time with cursor validation. |
| Stream activity hints | bounded same-origin SSE or equivalent proven wakeup | IDs, revisions, and safe status only; the browser refreshes authoritative projections. |
| Fetch link preview | separate server capability | Public-HTTPS SSRF-safe fetch and sanitized cache only. |
| Read safe media | opaque same-origin ID route | Validated attachment/artifact/preview-image content only. |

The selected Conversation uses its current Run stream for detailed live output.
The right rail uses the bounded global activity projection. Background tabs do
not each open an unbounded detailed event stream; a revision hint causes an
authoritative refresh and opening a tab subscribes to that Conversation's active
Run.

## Client architecture constraints

- The Console becomes a real React/Next.js interaction surface; the existing
  `shell-runtime.js` remains migration input, not an assumption that the new
  Console must use DOM data-attribute orchestration.
- A focused prototype must choose the lightest state architecture that proves
  tab switching, per-Conversation drafts, concurrent activity, SSE handoff, and
  optimistic-send rollback without typing stalls.
- Server Components may provide the first safe shell/projection. Interactive
  transcript, composer, tab, queue, and rail state live behind a narrow client
  boundary.
- Server authority state and browser presentation state remain separate.
- Slice 1 uses React built-ins with a normalized Conversation projection cache
  and small presentation state. No client-state or transcript-virtualization
  dependency is approved. A later ticket may reconsider that decision only with
  new measured need plus accepted license, bundle, accessibility, and maintenance
  cost.
- Loaded Conversation switching uses cached normalized projections immediately
  and refreshes in the background.
- Long transcripts initially request 100-Message server pages and retain a
  bounded 200-row ordered DOM window with an explicit keyboard-accessible Load
  older control. The transcript receives only the selected immutable Message
  page plus stable scalar props and callbacks so draft typing cannot reconcile
  the transcript tree.
- The selected-detail stream effect is keyed by exact Conversation and Run IDs;
  cleanup and the event reducer both enforce that identity. Bounded global
  activity hints are a separate channel and trigger authoritative readback.
- Production hydration must remain compatible with the reviewed Content
  Security Policy. Do not weaken the static shell's script policy merely to
  enable the Agent Console Client Component.

## Performance and accessibility gates

For the supported local reference machine and production Next.js build:

- composer typing never awaits network work;
- a submitted local user message paints within one animation frame;
- an accepted dispatch becomes visibly accepted within 1 second;
- received stream activity paints within 250 ms;
- switching to an already loaded Conversation is visually immediate;
- long transcripts remain responsive under the ticket's fixed stress fixture;
- layout does not jump when status labels, queue rows, or link cards arrive;
- all actions are keyboard reachable with visible focus;
- status never relies on color alone;
- approval, clarification, queue, and Run transitions use restrained live-region
  announcements;
- reduced-motion mode removes nonessential animation;
- the feature meets the repository's WCAG 2.2 AA and Lighthouse gates.

Each implementation ticket must define the machine, browser, fixture sizes, and
repeatable measurement commands used for its relevant budget. Median results
must be recorded; one favorable run is not evidence.

## Acceptable and unacceptable outcomes

### Acceptable

- The first screen is recognizably the approved Mentat three-column composition.
- A selected Agent can create a text Conversation and Run through a fixed
  Next.js-to-Python capability.
- The transcript remains primary and useful while concise progress stays live.
- The composer remains writable during execution.
- Pending turns, steering, stops, approvals, failures, and retries have visibly
  distinct outcomes.
- At least two compatible Conversations can execute concurrently without state,
  cancellation, event, or configuration leakage.
- Refresh restores durable state and reconciles uncertain work honestly.
- Provider/model/effort changes are convenient in the composer without weakening
  Agent-owned safe configuration.
- Safe code, local media, artifacts, and rich-link fallbacks render without
  exposing private storage or unsafe network access.

### Unacceptable

- Restoring the legacy Console route as the new Next.js API or adding a generic
  Node/Python proxy.
- Treating a runtime session, provider profile, heartbeat record, tab, or Run as
  a Mentat Conversation or Agent.
- A product-wide Run lock, a disabled composer during work, or a Steer button.
- Silent conversion between steering and queued turns.
- Automatic retry after ambiguous dispatch, steering, stop, approval, or
  provider mutation.
- Raw chain-of-thought, provider payloads, tool arguments/results, logs, paths,
  credentials, runtime references, or unsafe HTML in the browser.
- Browser-selected executables, working directories, credential sources,
  runtime methods, session IDs, or thread IDs.
- Link fetching from the browser or any server fetch that can reach local/private
  networks, forward credentials, follow unchecked redirects, or return raw HTML.
- Using Agent Messages, Pending turns, or the Console as a durable Task scheduler.
- Closing a tab stopping work, or a right-rail selection mutating work.
- Claiming completion, acceptance, steering, stopping, or recovery without the
  required server-side evidence.
- Shipping fake or fixture-backed production interactions.

## Ordered implementation slices

The research and decision tickets below block production slices. A slice may be
approved, implemented, verified, reviewed, and rolled back independently. Every
slice includes tests, documentation updates, two independent adversarial
reviews, and the persistent verification log required by the repository.

### Decision gate A: T3Code compatibility research

Study T3Code's current source and behavior for composer ergonomics, transcript
hierarchy, context presentation, model selection, keyboard flow, tab/activity
feedback, licensing, dependencies, and architecture. Produce a source-cited
research document. No source code or dependency may be adopted until this gate
records license and Mentat-boundary compatibility.

Resolved by
[`docs/research/2026-08-24-t3code-agent-console-compatibility.md`](docs/research/2026-08-24-t3code-agent-console-compatibility.md):
use T3Code as a behavioral reference for composer density, message hierarchy,
draft continuity, keyboard flow, and stable activity rows. Do not adopt its
thread/subagent domain, permission modes, sensitive browser persistence,
WebSocket/Effect state architecture, component stack, or dependencies. Any
later copied utility needs a separate provenance, license, dependency, security,
accessibility, and maintenance decision.

### Decision gate B: Conversation and concurrency ADR

Resolved by
[`docs/adr/0001-conversation-owned-agent-console.md`](docs/adr/0001-conversation-owned-agent-console.md).
Schema 10 adds Conversation-owned Messages and Turns, extends Runs with immutable
configuration and private capacity evidence, enforces one nonterminal Run and
eight queue-active Turns per Conversation, and preserves Task-dispatch authority.
Adapter-scoped capacity replaces product-wide admission. The bounded FIFO can
advance only from a verified success in that same Conversation and is explicitly
not a scheduler.

### Decision gate C: interactive-state prototype

Resolved by [GitHub issue #132](https://github.com/hazeion/agent-os/issues/132)
and the quarantined throwaway branch
`codex/prototype-agent-console-state`. The prototype proved:

- open/close/reopen Conversation tabs;
- cached instant switching and per-Conversation drafts;
- selected-Run SSE handoff;
- global activity updates;
- optimistic send rollback;
- eight queued turns;
- at least two concurrent active Conversations;
- a long transcript stress fixture.

React built-ins, narrow memoized props, and a bounded ordered transcript page
were sufficient. A 2,000-row DOM was materially slower than a 200-row window,
while the bounded version preserved focus, scroll anchoring, draft isolation,
DOM order, queue capacity, and exact stream isolation. No state or virtualization
dependency is approved. The prototype also found that the current static-shell
CSP blocks Next.js Client Component hydration in a production build; Slice 1
must establish a reviewed nonce or equivalent CSP-compatible hydration strategy
before production interaction measurements can pass. The prototype is evidence,
not production code.

### Slice 1: Conversation foundation and visual composition

Implement schema-backed Conversation and Conversation-message read foundations,
the Direct Agent seed/identity contract, and the approved three-column Next.js
composition. Include Conversation tabs, Agent selection, empty-state suggestions,
the compact composer shell, and the live read-only Agent activity rail. The
composer may remain explicitly unavailable for dispatch until Slice 2; no fake
send path is permitted.

Acceptance includes exact visual comparison to the approved mockup, rail-handle
behavior, responsive/reduced-motion/high-contrast states, durable Conversation
reopen, CSP-compatible Client Component hydration without a broad unsafe script
policy, and no regression to existing Agents/Tasks/Runs routes.

### Slice 2: text turn and Run creation

Add the fixed create-Conversation and submit-turn capabilities through Node,
the private Python bridge, repository, and runtime-neutral orchestration. Support
Agent selection, Direct Agent, text-only input, one idle-Conversation Run,
optimistic message display with rollback, exact idempotency, and honest dispatch
states. Routine Send has no confirmation modal.

Exclude queued turns, steering, attachments, rich rendering, and provider
mutation. Acceptance requires a real supported runtime and restart-safe canonical
records; fixture-only proof is insufficient.

### Slice 3: live transcript, active composer, queue, steering, and concurrency

Add selected-Run live transcript updates, concise inline activity, bounded global
right-rail activity, writable active composer, durable eight-turn FIFO queue,
edit/cancel, automatic next-turn dispatch after verified success, `/steer`, and
adapter-scoped concurrent admission.

Acceptance requires two simultaneous compatible Conversations, exact isolation
of stop/steer/events/configuration, late/unsupported steer preserving text,
capacity waiting, pause-on-nonsuccess behavior, the performance budgets above,
and no product-wide execution lock.

### Slice 4: operator control, recovery, and durable continuation

Integrate Stop, approval, clarification, attention navigation, failure display,
Retry, capability-gated Resume, startup reconciliation, refresh/reopen behavior,
recent Conversation history, and reversible archive. Keep ordinary composer text
separate from pending-action responses.

Acceptance covers stale confirmations, dropped SSE, restart during every
nonterminal state, unknown/partial outcomes, closed active tabs, blocked queues,
and no automatic retry. Completing Slice 4 establishes the first usable Agent
Console milestone.

### Slice 5: composer Agent configuration

Expose Agent, authenticated provider inventory, model, and effort as compact
composer selectors. Integrate existing safe preview/confirm/verification/rollback
workflows, Direct Agent configuration, pending-next-Run presentation, and
immutable Run snapshots.

Acceptance proves that an active Run never changes, unsupported adapters fail
closed, concurrent Conversations cannot cross-bind configuration, and the
browser receives no secret or private adapter identity.

### Slice 6: polished transcript and reasoning summaries

Add safe Markdown hierarchy, inert highlighted code, copy affordances, Activity
disclosures, Thinking summaries, tasteful motion, live-region behavior, bounded
long-transcript rendering, and message/run grouping.

Acceptance includes hostile Markdown/HTML fixtures, reduced motion, screen-reader
order, copy behavior, no raw reasoning/tool payload exposure, and performance
stress evidence.

### Slice 7: safe rich-link previews

Implement the separate SSRF-safe public-HTTPS metadata and preview-image
capabilities, cache, setting, asynchronous link-card state, and polished
fallbacks.

The implementation contract is researched in
[`docs/research/2026-08-24-safe-rich-link-previews.md`](docs/research/2026-08-24-safe-rich-link-previews.md).
Its initial fixed limits and hostile-server matrix are the Slice 7 starting
point; relaxing a limit requires a separate evidence-backed decision.

Acceptance includes DNS rebinding, redirect-to-private, compressed/oversized
body, MIME confusion, slow response, malformed metadata, credential stripping,
cache isolation, offline mode, and representative public-site compatibility
tests.

### Slice 8: attachments, Context Packs, images, and artifacts

Bring the existing private content-addressed attachment and artifact boundary to
the Next.js Conversation. Add compact attachment/Context Pack controls, safe
same-origin local-image rendering, upload state, artifact cards, review/download,
expiry, and refresh recovery.

Acceptance retains every storage, path, symlink, type, size, snapshot, expiry,
reference, and garbage-collection rule in `ARCHITECTURE.md`. Do not widen runtime
attachment capabilities implicitly.

### Slice 9: history depth and command ergonomics

Add history search/filter, title rename, archive management, command completion,
and the remaining versioned safe slash-command manifest behavior. Conversation
delete remains a later separately approved destructive feature.

Acceptance keeps search navigation-only, commands allowlisted, and history
bounded and private.

### Slice 10: project and planning context

Connect Conversations to safe Project/Task context, planning prompts, due or
overdue attention, and review workflows without crowding the center transcript.
Delegation remains inside the Hermes Kanban authority boundary and is not
implemented through Pending turns.

## Deferred or separately approved

- Conversation deletion;
- pending-turn drag reordering;
- arbitrary command or shell execution;
- remote Mentat serving;
- browser credential setup;
- arbitrary external image embedding;
- runtime capability fabrication or fallback steering;
- cross-Conversation scheduling or automatic retries;
- adopting T3Code source/dependencies before Decision gate A passes.
