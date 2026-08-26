# Mentat web design guide

Status: Canonical Next.js product and interaction design

Last updated: 2026-08-24

This is the required starting point for Mentat web-interface work. It defines
the current Next.js experience, including the prompt-first Agent Console Home.
The implemented Next.js UI and this guide are the design authority. Historical
design work is preserved in GitHub pull requests rather than duplicated in the
working tree.

For the approved Agent Console behavior, lifecycle, technical boundary,
acceptance gates, and implementation sequence, continue with
[MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md](MENTAT_NEXTJS_AGENT_CONSOLE_SPEC.md).

## Reading policy

Read this document for every `web/` design or implementation slice.

Do not read every linked historical document merely because it is linked here.
Consult a conditional reference only when this guide identifies a genuine gap,
the task requires parity with an implemented workflow, or exact historical
rationale is necessary. This keeps stale composition guidance out of the
working context and preserves context for the current task.

Architecture and safety are governed separately by `AGENTS.md`,
`ARCHITECTURE.md`, `MENTAT_MULTI_AGENT_PIVOT.md`, and
`MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`. If a visual proposal conflicts with one
of those contracts, the architecture or safety contract wins.

## Design authority

Use this order when sources disagree:

1. This guide and its approved Agent Console composition.
2. The implemented Next.js application under `web/` for current behavior and
   reusable components.
3. The Python compatibility interface under `public/` for proven workflow
   behavior that this guide has not yet specified.
4. GitHub pull requests for historical rationale.

The approved Mentat Chat Console V2 mockup is the composition reference for the
Home screen. Use the current issue description and this guide for implementation
decisions; do not add a second design document for a single slice.

## Product character

Mentat is a local-first, agent-first operations console. It should feel calm,
capable, and practical: closer to a strong modern LLM harness than a dense
administration dashboard.

The first screen should make it obvious that the user can talk to an Agent,
assign work, and observe active work without leaving the conversation.

Use the Emerald Operations visual language:

- near-black green surfaces;
- warm ivory primary text;
- restrained emerald for selection, readiness, and primary action;
- orange for attention;
- red for failure and destructive action;
- compact chrome around a spacious conversation surface.

Use real Mentat state or a clearly named empty, unavailable, unsupported,
waiting, failed, or disconnected state. Never display sample operational data
as though it were live.

## Agent-first interaction model

Any prompt, task assignment, or dispatch has a canonical Mentat Agent. The
Agent is the user's durable worker identity; runtime profiles, provider
connections, model identifiers, runtime sessions, and threads remain private
implementation references.

The browser may select or submit only bounded Mentat-owned context. It must not
select an executable, working directory, credential source, adapter reference,
runtime session ID, or runtime operation.

The normal composer flow is:

1. Select or confirm the Agent.
2. Review the Agent's safe Provider and Model projection when supported.
3. Optionally add Project, Task, attachment, or Context Pack context.
4. Enter the prompt.
5. Start a new Mentat Run or continue a supported Agent-owned conversation.

Agent is visually primary. Provider and Model are compact, subordinate
selectors and do not independently grant execution authority.

## Application composition

### Left workspace rail

The left rail provides navigation:

- Home
- Agents
- Projects & Tasks
- Calendar
- Runs
- Settings

Expanded state shows icons and labels. Collapsed state shows icons with
accessible names and tooltips. Do not make a navigation item interactive until
it has an honest screen.

The collapse control is a small handle centered on the rail seam. It stays at
the same app-level vertical position in expanded and collapsed states and must
not cover the header.

### Center conversation

The center is the primary workspace and receives most of the available width.
It contains the welcome state, conversation transcript, runtime events that are
useful to the user, action requests, artifacts, and the prompt composer.

The initial Home state contains:

- “What can Mentat help with?”;
- a small set of useful prompt suggestions;
- a large empty context/transcript area;
- a narrow composer anchored at the bottom.

Do not place a permanent dashboard-card grid in the center. Project context,
due work, and operator attention belong in the right rail or their dedicated
workspaces unless they become directly relevant to the conversation.

### Prompt composer

The text field starts approximately one line tall. It expands to a bounded
height as text grows and then scrolls internally. The transcript must remain
larger than the composer.

Keep attachment and Context Pack controls compact. Place Agent, Provider, and
Model as borderless or visually quiet selectors in the composer footer. The
send action remains clear and reachable without turning the footer into a
toolbar wall.

An unassigned prompt cannot be sent. Disabled, unsupported, uploading,
validation, and disconnected states must explain what is preventing dispatch.

### Right Agent status rail

The right rail is a workflow surface. It may show:

- Agent name and state;
- one-line current work summary;
- active Run or Task association;
- shared project focus;
- pending approval or clarification;
- failed or completed work needing review;
- overdue work or other operator attention.

It must derive identity from canonical Agents and activity from canonical Runs,
not legacy heartbeat observations.

The right rail collapses completely except for its narrow edge rail and toggle.
Its toggle uses the same app-level vertical center as the left toggle, remains
on the seam in both states, and is layered above the center conversation.

## Conversation and Run presentation

The console should present a coherent conversation while preserving honest Run
state. Messages, normalized events, tool activity, approvals, clarifications,
artifacts, and terminal outcomes are different concepts even when they share a
timeline.

Prioritize:

- user and assistant messages;
- current Agent and Run state;
- work requiring operator input;
- concise tool and progress activity;
- generated artifacts and reviewable outcomes.

Avoid dumping raw event payloads or runtime logs into the primary transcript.
Detailed diagnostics may use a secondary disclosure when they are safe and
useful.

Waiting for approval, waiting for clarification, stopped, failed, unknown,
partially verified, truncated, and disconnected states must remain distinct.
Do not claim success before server-side readback verifies it.

## Runtime and data boundary

The web flow is:

```text
Next.js UI
    -> fixed same-origin Node capability
    -> private Python Local Bridge capability
    -> runtime-neutral Mentat orchestration
    -> Hermes, Codex, Vercel, or a future adapter
```

Python and Mentat's private storage remain authoritative for Agents, Tasks,
Runs, events, capability checks, confirmation, dispatch, and reconciliation.
Do not restore the legacy `/api/agent-console` route as the new browser
contract or add a generic bridge proxy.

## Shared visual foundation

Use semantic design tokens and the effective Next.js implementation. Preserve
the inherited Emerald principles unless this guide overrides them:

- a 4 px spacing rhythm;
- restrained radii and shadows;
- compact desktop controls with accessible mobile targets;
- visible focus in standard and high-contrast modes;
- sentence-case labels;
- status text in addition to color;
- stable layouts during loading and failure;
- no page-level horizontal overflow;
- reduced-motion support;
- WCAG 2.2 AA target.

When an exact token, typography value, or shared-component rule is missing,
inspect the existing `web/` implementation and the compatibility interface under
`public/`. Record any new durable rule here instead of creating a parallel
design guide.

## Responsive behavior

Desktop keeps the three-region composition. Compact layouts may collapse the
left rail to icons. The right rail may collapse by default when width becomes
constrained. Mobile uses the established navigation drawer pattern and a
single-column conversation; secondary Agent status becomes an explicit drawer
or sheet rather than squeezing the transcript.

Keyboard order must match visual order. Icon controls require accessible names.
Check keyboard use, 200 percent zoom, reduced motion, standard contrast, high
contrast, and representative desktop, tablet, and mobile widths.

## Route direction

- `/`: prompt-first Agent Console Home.
- `/agents`: canonical Agent identity, capabilities, status, and supported
  management.
- `/tasks`: project planning, assignment, dependencies, scheduling, and safe
  mutations.
- `/runs`: bounded Run history, normalized timeline, artifacts, and supported
  controls.
- Calendar and Settings become active only with real screens and contracts.

Use `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md` for slice order and current completion
status. This guide defines the target experience, not authorization to start a
slice.

## Historical references

Use the implemented `web/` and `public/` code for parity questions. Use the
relevant GitHub pull request when historical implementation rationale is needed.
Do not create or preload a second design guide for routine work.

## Acceptance principles

- The prompt composer is the primary action on Home.
- A prompt cannot be sent without an Agent.
- The transcript/context area dominates the center column.
- Both side rails are useful, collapsible, and visually quiet.
- Active work and operator attention are visible without crowding the prompt.
- The interface exposes only safe Mentat projections.
- Every capability and state shown to the user is honest.
- New work preserves the local-first architecture and tested rollback path.
