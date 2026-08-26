# T3Code patterns for Mentat Agent Console compatibility

Decision ticket: [GitHub issue #129](https://github.com/hazeion/agent-os/issues/129)

Observation date: **2026-08-24** (`America/Los_Angeles`)

Upstream snapshot: `pingdotgg/t3code` `main` at
[`bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c`](https://github.com/pingdotgg/t3code/commit/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c), committed **2026-08-24 22:00:28 PDT** (`2026-08-25T05:00:28Z`), `feat(web): safely attach HEIC photos as JPEG images (#8161)`.

This report is a source-level compatibility decision, not an implementation
approval or an accessibility conformance audit. It adopts no T3Code source or
dependency.

## Executive decision

T3Code is a strong behavioral reference for a prompt-first agent workspace, but
it is not a suitable code or architecture donor for Mentat's first Agent Console
slices.

Mentat should:

- adopt the restrained, auto-growing composer; message-first transcript; local
  draft continuity; ordinary desktop Enter/Shift+Enter flow; IME-safe submission;
  and stable, in-place activity rows;
- adapt T3Code's context chips, searchable provider/model picker, work
  disclosures, context-window meter, status summaries, and keyboard menus to
  Mentat's canonical Agent/Conversation/Run model and safe projections;
- reject T3Code's thread-sidebar model as a replacement for Conversation tabs,
  its flattening of queued/running/waiting activity into “Working,” its
  Shift+Tab mode toggle, browser persistence of attachment/context payloads,
  generic permission modes, and wholesale client/runtime stack; and
- consider copying only a small, dependency-free utility after a separate
  implementation decision satisfies the license, provenance, dependency,
  security, accessibility, and test conditions below.

These decisions preserve the composition and domain language in
[`MENTAT_WEB_DESIGN.md`](../../MENTAT_WEB_DESIGN.md), the locked lifecycle and
slice order in
[`MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md`](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md),
the capability and data boundaries in [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
and the canonical terminology in [`CONTEXT.md`](../../CONTEXT.md).

## Pattern-by-pattern verdicts

The verdict vocabulary is intentionally limited to **adopt behavior**, **adapt
behavior**, **adopt code after conditions**, and **reject**.

| Pattern | Mentat comparison and boundary | Verdict |
| --- | --- | --- |
| Compact, bounded composer with quiet controls | T3Code puts context above a rounded, auto-growing editor and provider/mode/send controls in a compact footer ([composer surface](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ChatComposer.tsx#L2883-L3055), [footer](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ChatComposer.tsx#L3323-L3520)). This directly supports Mentat's transcript-dominant center and narrow composer, but selected-Agent gating and server readiness remain Mentat rules ([web design](../../MENTAT_WEB_DESIGN.md#prompt-composer), [spec](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#locked-product-decisions)). | adopt behavior |
| Rich Lexical editor as the initial composer | T3Code's controlled editor uses Lexical, mention/token plugins, history, and a contenteditable surface ([editor](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/ComposerPromptEditor.tsx#L1529-L1787)). Mentat's first slices need text, queueing, and lifecycle correctness; rich mentions and attachments come later in Slices 8–9. | reject |
| Enter sends, Shift+Enter inserts a newline, IME is guarded | T3Code's pure submission rule sends desktop Enter, leaves mobile/Shift+Enter to the editor, and treats modified Enter on a draft as background submission ([logic](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/composer-logic.ts#L15-L25)); the editor separately guards composition events ([editor key handling](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/ComposerPromptEditor.tsx#L904-L960)). Adopt the ordinary Enter/Shift+Enter and IME behavior, but not modified-Enter background thread creation; Mentat has explicit active-Run queue and `/steer` semantics ([spec](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#send-during-an-active-run), [Context](../../CONTEXT.md#language)). | adopt behavior |
| Shift+Tab toggles plan/interaction mode | T3Code consumes reverse-Tab before ordinary focus movement ([handler](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ChatComposer.tsx#L2015-L2023)). That conflicts with Mentat's predictable visual/keyboard order and creates avoidable keyboard-trap risk. Use an explicit control and optional discoverable shortcut that does not appropriate Tab navigation. | reject |
| Arrow-key menu navigation and Enter/Tab completion | T3Code moves the active item with arrows and accepts it with Enter or Tab ([handler](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ChatComposer.tsx#L2024-L2040)). Keep rapid keyboard completion, but implement only Mentat's versioned command allowlist, preserve Escape and Tab focus behavior, expose the active option semantically, and never derive commands from a runtime CLI ([spec](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#client-architecture-constraints), [architecture](../../ARCHITECTURE.md#calendar-notes-and-search-boundaries)). | adapt behavior |
| Per-conversation drafts separated from server authority | T3Code explicitly distinguishes local draft sessions from durable server threads and uses a dedicated browser store ([draft store](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/composerDraftStore.ts#L247-L359)). The ownership principle matches Mentat's per-Conversation browser presentation state; the exact store and identity model do not ([spec](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#browser-local-presentation-state)). | adopt behavior |
| Persist image bytes, terminal coordinates, page URL, selector, HTML, and styles in `localStorage` | T3Code's persisted draft schema includes image `dataUrl` values and detailed terminal/DOM context ([schema](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/composerDraftStore.ts#L60-L151)). Mentat permits only opaque attachment IDs and bounded safe display metadata in the browser; snapshots, paths, hashes, and content belong behind its private file boundary ([architecture](../../ARCHITECTURE.md#agent-console-file-boundary)). Browser persistence should contain prompt/presentation state only, with explicit size, migration, and expiry policy. | reject |
| Removable context chips beside the composer | T3Code shows removable element and terminal context close to the draft, with tooltips and accessible remove labels ([element context](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ComposerPendingElementContexts.tsx#L28-L68)). Use the same visible “what will be sent” affordance for Mentat Project/Task context, validated Context Packs, notes, relative workspace labels, and opaque attachments. Resolve and snapshot content through named Node→Python capabilities at use time; never expose an absolute path or raw provider/runtime reference ([web design](../../MENTAT_WEB_DESIGN.md#runtime-and-data-boundary), [architecture](../../ARCHITECTURE.md#agent-console-file-boundary)). | adapt behavior |
| Message-first transcript with secondary work disclosure | T3Code keeps user and assistant messages primary, condenses live tool work, and folds settled intermediate work while preserving opening/terminal assistant content ([row model](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/MessagesTimeline.logic.ts#L523-L657), [rendering](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/MessagesTimeline.tsx#L928-L985)). This matches Mentat's hierarchy, but Mentat disclosures may contain only normalized activity and explicit provider-supplied reasoning summaries—never hidden chain of thought or raw runtime events ([web design](../../MENTAT_WEB_DESIGN.md#conversation-and-run-presentation), [spec](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#transcript-and-content-presentation)). | adapt behavior |
| Collapse long user prompts and intermediate work | T3Code collapses user messages above source thresholds and uses summary/toggle rows for work ([user-message collapse](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/MessagesTimeline.tsx#L1786-L1863), [work rows](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/MessagesTimeline.tsx#L1374-L1622)). Adapt the disclosure pattern, but keep failures, approvals, clarifications, Stop results, queue state, and evidence needed to understand an outcome visible or immediately discoverable. | adapt behavior |
| Context-window meter with tokens, percentage, and compaction explanation | T3Code exposes a semantic progress bar, exact token counts when available, and reduced-motion styling ([meter](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ContextWindowMeter.tsx#L90-L130)). Mentat should show this only when a runtime adapter reports trustworthy usage and capacity; label unknown or estimated values, and never infer authority, cost, or readiness from the meter. | adapt behavior |
| Searchable, grouped provider/model picker | T3Code resolves the active provider instance, avoids showing a stale model from another instance, groups only ready providers, exposes disabled reasons, supports search/favorites, and keeps an explicit instance identity ([trigger](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ProviderModelPicker.tsx#L50-L160), [inventory and picker](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ModelPickerContent.tsx#L202-L440)). Mentat should keep search, current-selection clarity, and disabled explanations, but show only the selected Agent's authenticated/supported safe inventory and route changes through exact preview, confirmation, verification, and rollback. The effective configuration is snapshotted per Run and changes apply to the next Run ([spec](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#provider-model-and-effort-behavior), [architecture](../../ARCHITECTURE.md#provider-switching-boundary)). | adapt behavior |
| Generic user-facing permission modes | T3Code documents Supervised, Auto-accept edits, Auto, and Full access as cross-provider modes ([permission modes](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/user/permission-modes.md)). Mentat cannot let browser input select runtime authority, executable, sandbox, credential source, or arbitrary provider behavior. Capability-scoped adapters and operation-specific confirmation remain authoritative ([architecture](../../ARCHITECTURE.md#node-gateway-boundary)). | reject |
| Thread inbox with pinned, active, snoozed, and settled shelves | T3Code partitions durable threads into sidebar shelves and routes to one active thread ([partitioning](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/Sidebar.tsx#L2014-L2117)). Mentat has a locked tab strip for durable Conversations and a separate global Agent activity rail. Keep explicit selection/reopening and useful attention summaries, but do not replace tabs with a thread inbox or conflate a tab, Conversation, Run, and runtime session ([spec](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#product-composition), [Context](../../CONTEXT.md#language)). | reject |
| Stable, fixed-height activity rows updated in place | T3Code's Agent panel intentionally preserves spawn order, row height, and disclosure state while status changes ([design rules](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/AgentsPanel.tsx#L1-L13)). Adapt that visual stability to Mentat's global hierarchy: canonical Agent → durable Conversation → active/most-recent Run. T3Code's “agents” are thread-spawned runtime subagents, not Mentat Agents ([web design](../../MENTAT_WEB_DESIGN.md#right-agent-status-rail), [Context](../../CONTEXT.md#language)). | adapt behavior |
| Flatten pending, running, and waiting to “Working” | T3Code deliberately maps all three states to one label ([status map](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/AgentsPanel.tsx#L33-L50)). Mentat must distinguish queued/waiting for capacity, running, waiting for operator input, failed, stopped, interrupted, and completed because those states drive attention and allowed actions. | reject |
| Server authority, typed commands, cached projections, and explicit synchronization state | T3Code keeps execution on its server, uses typed Effect RPC subscriptions, and separates finite requests, subscriptions, and mutations ([architecture](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/internals/overview.md#L5-L80), [client data boundary](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/internals/connection-runtime.md#L93-L122)). Adopt the ownership principle only: Mentat's Python/SQLite authority, fixed same-origin Node capabilities, runtime-neutral adapters, bounded SSE, idempotency, exact read-back, and fail-closed rules remain unchanged ([web design](../../MENTAT_WEB_DESIGN.md#runtime-and-data-boundary), [architecture](../../ARCHITECTURE.md#node-gateway-boundary)). | adapt behavior |
| Effect RPC WebSocket, Effect Atom factories, and shared web/mobile runtime | T3Code has one authenticated Effect RPC WebSocket and a shared client runtime that owns connectivity, retries, caching, and domain atoms ([overview](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/internals/overview.md#L31-L59), [runtime](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/internals/connection-runtime.md#L14-L40)). Mentat is local-first, web-only at this decision, and already specifies named HTTP capabilities plus selected-detail/global-summary SSE. Decision gate C must prove whether a small client library is needed; T3Code's transport/runtime architecture is not a candidate wholesale replacement ([spec](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#client-architecture-constraints)). | reject |
| Virtualized transcript/model lists and minimap | T3Code uses `@legendapp/list` for long lists and maintains a timeline minimap ([web dependencies](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/package.json#L14-L51), [timeline](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/MessagesTimeline.tsx#L251-L638)). Do not add either in early slices. Reconsider virtualization only after Mentat's long-transcript prototype exceeds render/interaction budgets and after copy, find-in-page, focus, screen-reader order, zoom, and scroll anchoring pass ([spec](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#performance-and-accessibility-gates)). | reject |
| Small, dependency-free pure utility copied from T3Code | Direct copying is unnecessary for the layout behaviors above. If a later prototype identifies an exact pure helper that is better copied than independently implemented, the conditions in “License and copied-code obligations” are mandatory. No component, store, transport module, or T3 workspace package qualifies under this ticket. | adopt code after conditions |

## Composer, transcript, and context implications

### Composer ergonomics and keyboard flow

The most transferable T3Code decision is density, not editor technology. The
composer leaves the transcript visually dominant, keeps contextual material
attached to the draft, and exposes primary send/stop actions at the right edge.
Mentat should implement that behavior in Slices 1–2 with ordinary text controls
first. Lexical, mentions, slash completion, attachments, and richer context are
Slice 8–9 concerns and should not enlarge the initial state model.

T3Code's source also demonstrates why keyboard rules must be explicit rather
than inherited from a component library: its editor has IME guards, menu-specific
Arrow/Enter/Tab behavior, mobile-specific Enter behavior, a modified-Enter
background action, and a Shift+Tab mode action. Mentat should adopt the first,
adapt menu completion, and reject the last two. `/steer`, queueing, and Stop must
remain explicit lifecycle operations, not keyboard variants of “send.”

### Transcript hierarchy and context presentation

T3Code's settled-turn folding is useful because it preserves a readable message
spine while keeping work evidence available. Mentat should use disclosure
headings such as Activity, Thinking summary, Files changed, Approval, and
Clarification, but derive them only from normalized `AgentEvent` projections.
T3Code's bare “Thinking” timer/label is not evidence that reasoning content is
available; Mentat may show a provider-supplied summary only when the adapter
explicitly supplies one.

Context must be visible before send and reconstructable after send without
leaking authority. A chip can display a safe filename or Context Pack title,
while the server owns validated snapshots and immutable Run references. This is
the key point where copying T3Code's browser draft schema would violate Mentat's
file and runtime boundaries.

## Conversation, tab, and Agent activity implications

T3Code's “thread” is its durable conversation/work unit, while its Agent panel
shows runtime-spawned subagents within a thread. Mentat's canonical objects are
different: an Agent is durable and user-managed, a Conversation is durable and
tab-addressable, and a Run is one execution attempt. Consequently:

- selecting or closing a tab is presentation state and must not stop a Run;
- switching tabs should restore cached transcript/draft state immediately and
  reconcile against server authority;
- the right rail should update stable rows in place and group Conversations
  beneath canonical Agents;
- queue position, running, waiting for capacity, waiting for operator, failure,
  interruption, Stop, and completion must remain distinct; and
- only the selected Conversation needs detailed streaming; background work can
  use bounded global activity hints followed by authoritative refresh.

This is an adaptation of T3Code's durable navigation and visual stability, not
an adoption of its sidebar or subagent domain model.

## Client-state and dependency decision

T3Code's architecture is internally coherent for a multi-client product: its
server owns agent processes and workspaces, one shared runtime supervises
authenticated WebSocket RPC, and Effect Atom factories expose cached domain
state to web and mobile. Its web client also uses Zustand for browser-local
stores. That is substantially broader than Mentat's current problem.

At the pinned revision, T3Code requires Node `^24.13.1`, pnpm `11.10.0`, and
Vite Plus ([root manifest](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/package.json#L1-L64)). The web app
depends on Base UI, dnd-kit, Effect Atom, Legend List, Lexical, Pierre diff/tree
packages, TanStack packages, React Markdown/rehype/remark, Zustand, and internal
workspace packages ([web manifest](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/package.json#L14-L51)). The
workspace pins Effect 4 beta and other beta packages, allows native build scripts,
and carries patches for Effect, Legend List, Pierre, and several platform
packages ([workspace catalog](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/pnpm-workspace.yaml#L8-L52), [patches](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/pnpm-workspace.yaml#L135-L150)).

Therefore:

- do not add Effect, Effect Atom, Zustand, Lexical, Legend List, Base UI,
  TanStack Router, or T3 workspace packages in this decision;
- use Decision gate C to prototype tabs, drafts, selected/global SSE handoff,
  optimistic queue rollback, and long transcripts with Mentat's existing
  Next.js/React surface;
- add a local-state library only if the prototype demonstrates coordination
  failures that React state cannot reasonably contain;
- add virtualization only if measured transcript size breaches the specified
  budgets and accessibility remains correct; and
- if rich Markdown is later needed, design Mentat's own strict sanitization and
  URL policy. T3Code permits a `file` protocol in its sanitize schema
  ([Markdown schema](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/ChatMarkdown.tsx#L220-L262)), which must not cross Mentat's browser file boundary.

## License and copied-code obligations

T3Code's repository is MIT-licensed, copyright 2026 T3 Tools Inc. The license
permits use, copying, modification, merging, publication, distribution,
sublicensing, and sale, but requires the copyright and permission notice in all
copies or substantial portions
([license](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/LICENSE#L1-L20)). The web package
also records that `src/pierre-icons.ts` adapts `vscode-icons`, with its own MIT
notice
([third-party notice](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/THIRD_PARTY_NOTICES.md#L1-L11)).

For any future copied code, Mentat must:

1. record the exact upstream commit, source path, and copied/adapted lines;
2. preserve the T3Code MIT copyright and permission text in the appropriate
   notices and source provenance;
3. inspect that path for third-party-derived material and preserve every
   applicable notice; the repository-level MIT license does not relicense
   dependencies or embedded third-party work;
4. audit every imported dependency's license, security posture, bundle/runtime
   cost, and build-script requirements separately;
5. remove T3-specific provider, identity, path, transport, and authority
   assumptions; and
6. add Mentat-owned tests and security/accessibility review before merge.

Reimplementing a behavior from this report without copying expressive source is
the preferred route. It avoids unnecessary source coupling, though provenance
should still be recorded in the implementation decision. This report is not
legal advice and does not authorize copied code.

## Accessibility implications

The source contains useful accessibility details: named icon actions,
`aria-expanded` disclosures, failure labels, a semantic context progress bar,
IME handling, and reduced-motion styling. Those are patterns to preserve.

The source inspection does not establish WCAG 2.2 AA conformance. The following
must remain explicit Mentat gates:

- do not consume Shift+Tab for a mode switch, and define whether Tab completes
  a menu item or moves focus in every menu state;
- test the composer and picker with IMEs, screen readers, keyboard-only use,
  mobile keyboards, and 200% zoom;
- keep status text in addition to color and use restrained live-region
  announcements for meaningful state changes without announcing timers or token
  deltas;
- ensure collapsed work still exposes failures and pending operator actions;
- verify that any virtualized list preserves DOM/screen-reader order, focus,
  selection, copy, browser find, and scroll anchoring;
- give compact icon controls accessible names, visible focus, sufficient contrast,
  and mobile target sizes; and
- honor reduced motion for meters, drawers, list transitions, and streaming
  indicators.

These are required by Mentat's shared visual foundation, responsive rules, and
performance/accessibility gates
([web design](../../MENTAT_WEB_DESIGN.md#shared-visual-foundation), [responsive design](../../MENTAT_WEB_DESIGN.md#responsive-behavior), [spec gates](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md#performance-and-accessibility-gates)).

## Maintenance risk

The maintenance risk of behavioral reference is low; the risk of code or stack
adoption is high.

- T3Code explicitly describes itself as “very very early” and says to expect
  bugs ([README](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/README.md#L68-L72)).
- The inspected composer and transcript are very large, cross-cutting components
  tied to provider options, drafts, approvals, attachments, terminal/DOM context,
  mobile behavior, and T3's client runtime. Copying a visual subset would still
  require substantial disentangling.
- The monorepo spans web, mobile, Electron, server, native modules, provider
  drivers, terminals, VCS, and remote connectivity. Its shared abstractions solve
  a wider product problem than Mentat's fixed local-first Node→Python boundary.
- Beta dependencies, patched packages, native build scripts, and Vite+/pnpm
  tooling increase upgrade and security-review burden.
- Source-level UI details are moving quickly—the pinned head itself is an
  attachment/composer change—so line-level adoption would create upstream drift
  without a compatibility benefit.

Mentat should treat this report as a one-time behavioral reference for Decision
gate A. It should not track T3Code continuously or introduce a compatibility
layer. Revisit upstream code only when a narrowly scoped later slice has a
measured need and a named owner for maintenance.

## Mentat slice mapping

| Mentat decision/slice | T3Code-derived input | Decision |
| --- | --- | --- |
| Decision gate B | Preserve canonical Agent/Conversation/Run identities and distinct queue/wait states; do not import T3 thread/subagent semantics. | adapt behavior |
| Decision gate C | Prototype local drafts, instant tab restoration, selected/global SSE handoff, queue rollback, and long transcripts before choosing state or virtualization libraries. | adapt behavior |
| Slice 1 | Use a transcript-dominant center, compact composer, durable tabs, and stable Agent rail rows. | adopt behavior |
| Slice 2 | Use desktop Enter/Shift+Enter plus IME-safe send; keep Agent gating and exact Run creation. | adopt behavior |
| Slice 3 | Keep composer active during a Run and expose distinct queue, steering, concurrency, and background status. | adapt behavior |
| Slice 4 | Keep Stop, approval, clarification, retry, and resume explicit and visible. | adapt behavior |
| Slice 5 | Use a quiet searchable selector, safe inventory, current/pending distinction, and verified next-Run configuration. | adapt behavior |
| Slice 6 | Preserve the message spine and fold normalized work behind accessible disclosures; show only supplied reasoning summaries. | adapt behavior |
| Slice 8 | Show removable context chips but retain all bytes and authority behind Mentat's attachment boundary. | adapt behavior |
| Slice 9 | Add allowlisted command completion and history ergonomics without T3's general keybinding/runtime command surface. | adapt behavior |

## Primary sources inspected

### Mentat

- [`AGENTS.md`](../../AGENTS.md)
- [`MENTAT_WEB_DESIGN.md`](../../MENTAT_WEB_DESIGN.md)
- [`MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md`](../../MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md)
- [`ARCHITECTURE.md`](../../ARCHITECTURE.md)
- [`CONTEXT.md`](../../CONTEXT.md)
- [`MENTAT_MULTI_AGENT_PIVOT.md`](../../MENTAT_MULTI_AGENT_PIVOT.md)
- [`MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`](../../MENTAT_PIVOT_IMPLEMENTATION_PLAN.md)
- [`docs/agents/issue-tracker.md`](../agents/issue-tracker.md)
- [`docs/agents/domain.md`](../agents/domain.md)

### T3Code

- Pinned [commit](https://github.com/pingdotgg/t3code/commit/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c),
  [README](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/README.md),
  [LICENSE](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/LICENSE),
  [root manifest](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/package.json),
  [web manifest](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/package.json),
  [workspace manifest](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/pnpm-workspace.yaml), and
  [web third-party notices](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/THIRD_PARTY_NOTICES.md).
- Maintainer docs: [architecture overview](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/internals/overview.md),
  [connection runtime](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/internals/connection-runtime.md), and
  [provider architecture](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/internals/providers.md).
- User docs: [keyboard shortcuts](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/user/keybindings.md),
  [permission modes](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/user/permission-modes.md), and
  [thread sidebar](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/docs/user/thread-sidebar.md).
- UI and state source: [`ChatComposer.tsx`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ChatComposer.tsx),
  [`ComposerPromptEditor.tsx`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/ComposerPromptEditor.tsx),
  [`composer-logic.ts`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/composer-logic.ts),
  [`MessagesTimeline.logic.ts`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/MessagesTimeline.logic.ts),
  [`MessagesTimeline.tsx`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/MessagesTimeline.tsx),
  [`ProviderModelPicker.tsx`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ProviderModelPicker.tsx),
  [`ModelPickerContent.tsx`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ModelPickerContent.tsx),
  [`ContextWindowMeter.tsx`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/chat/ContextWindowMeter.tsx),
  [`Sidebar.tsx`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/Sidebar.tsx),
  [`AgentsPanel.tsx`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/components/AgentsPanel.tsx),
  [`composerDraftStore.ts`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/composerDraftStore.ts), and
  [`uiStateStore.ts`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/uiStateStore.ts).
- Client runtime source: [`threads.ts`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/packages/client-runtime/src/state/threads.ts),
  [`presentation.ts`](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/state/presentation.ts), and
  [`threads.ts` web adapter](https://github.com/pingdotgg/t3code/blob/bd9ed2b4bbda3dd6e468df1cb06233e29c4a9f5c/apps/web/src/state/threads.ts).
