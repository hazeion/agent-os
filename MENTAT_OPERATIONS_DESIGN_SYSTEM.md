# Mentat Operations UI Design System

Status: Working design contract
Visual system name: **Mentat Operations / Emerald**
Product name: **Mentat**

This document defines the visual language and reusable interface rules for
converting Mentat from the legacy dark dashboard into the Emerald operations
workspace. “Operations” names the design system; it does not rename the
product.

The system is based on the approved Emerald mock-up and the implemented Home
composition:

```text
┌──────────────┬─────────────────────────────────────────────────────────┐
│ Mentat       │ Connection                         Search        Avatar │
│              ├───────────────────────────┬─────────────────────────────┤
│ Home         │ Operational focus         │ Live agents                 │
│ Agents       │                           │                             │
│ Calendar     ├───────────────────────────┼─────────────────────────────┤
│              │ Today schedule            │ Projects                    │
│ Projects     │                           ├─────────────────────────────┤
│ Notes        │                           │ Scheduled automations        │
│              ├───────────────────────────┴─────────────────────────────┤
│ Settings     │ Agent Console                                           │
└──────────────┴─────────────────────────────────────────────────────────┘
```

The Home page intentionally has no greeting hero and no row of summary cards.
Operational work, agent state, time, projects, scheduled automation, and the
Console are the first visible layer.

## 1. Experience principles

### Operations first

Lead with the next decision or action. Summary information belongs beside the
work it explains, not in a separate metric-card strip.

### Calm density

Mentat may contain substantial information, but the interface should feel
ordered rather than compressed. Use a small number of strong regions, quiet
dividers, restrained state color, and predictable alignment.

### Honest system state

Never invent agent, session, task, health, or schedule information to make a
panel look populated. Empty, stale, disconnected, unsupported, and partial
states remain explicit.

### Progressive disclosure

Keep the primary operating path visible. Put history, advanced provider
controls, completed work, quick capture, and review queues in native,
keyboard-operable disclosures when they would otherwise overwhelm the page.

### Local-first trust

Connection state must always be visible. Read-only data is labeled read-only.
Unavailable Hermes capabilities do not display controls that imply the
capability exists.

## 2. Page anatomy

### Application shell

| Region | Specification |
| --- | --- |
| Desktop navigation | 216 px expanded left rail |
| Intermediate navigation | 76 px compact rail |
| Mobile navigation | Modal drawer at 900 px and below |
| Command header | 64 px minimum height; connection, search, operator identity |
| Content gutter | 16 px desktop; 10–14 px narrow |
| Primary panel gap | 10 px |
| Desktop Home columns | `1.174fr 1fr` |
| Home row order | Focus/Agents, Schedule/Context, Console |
| Main content maximum | Fluid; no artificial centered marketing-page width |

### Home hierarchy

1. **Operational focus** — up to three priorities, completion state, project
   scope, quick add, completed work.
2. **Live agents** — canonical Hermes profiles annotated by current-connection
   runs and observed state.
3. **Today** — today-only calendar and scheduled task blocks; read-only.
4. **Projects** — portfolio state and next open work.
5. **Scheduled automations** — at most two real CRON jobs; read-only.
6. **Agent Console** — always-available compact command strip; history and
   provider settings expand below.

### Responsive behavior

| Width | Shell | Home composition |
| --- | --- | --- |
| 1200 px and wider | Expanded 216 px rail | Two columns; Console spans both |
| 901–1199 px | Compact 76 px rail | Two compact columns while content fits |
| 641–900 px | Drawer | One column: Focus, Agents, Today, Context, Console |
| 320–640 px | Drawer | One column; schedule becomes an agenda; actions wrap |

At every width:

- no page-level horizontal scrolling;
- controls do not overlap or clip;
- touch targets are at least 44 × 44 px at phone widths;
- visual order and DOM reading order agree;
- disclosures expand inside their containing panel.

## 3. Figma variable architecture

Create three Figma variable collections. Use slash-delimited names so Figma
groups related variables automatically.

### Collection A — `Mentat / Primitive`

Modes: `Emerald Dark` only. Primitive values never appear directly in component
properties when a semantic alias exists.

#### Neutral primitives

| Figma variable | Value | CSS source |
| --- | --- | --- |
| `color/neutral/1000` | `#05090B` | `--operations-neutral-1000` |
| `color/neutral/950` | `#070D11` | `--operations-neutral-950` |
| `color/neutral/900` | `#0B1115` | `--operations-neutral-900` |
| `color/neutral/850` | `#0F151A` | `--operations-neutral-850` |
| `color/neutral/800` | `#121A20` | `--operations-neutral-800` |
| `color/neutral/750` | `#182127` | `--operations-neutral-750` |
| `color/neutral/700` | `#202B30` | `--operations-neutral-700` |
| `color/neutral/650` | `#2A373B` | `--operations-neutral-650` |
| `color/neutral/600` | `#344348` | `--operations-neutral-600` |
| `color/neutral/550` | `#596B6F` | `--operations-neutral-550` |
| `color/neutral/500` | `#566166` | `--operations-neutral-500` |
| `color/neutral/400` | `#7E898B` | `--operations-neutral-400` |
| `color/neutral/300` | `#AAB1AF` | `--operations-neutral-300` |
| `color/neutral/200` | `#CBCFC8` | `--operations-neutral-200` |
| `color/neutral/100` | `#EAE7DD` | `--operations-neutral-100` |
| `color/neutral/0` | `#F6F3EA` | `--operations-neutral-0` |

#### Emerald primitives

| Figma variable | Value | CSS source |
| --- | --- | --- |
| `color/emerald/50` | `#EFF9F0` | `--operations-emerald-50` |
| `color/emerald/100` | `#D8EEDB` | `--operations-emerald-100` |
| `color/emerald/200` | `#BFE2C2` | `--operations-emerald-200` |
| `color/emerald/300` | `#9DCE9B` | `--operations-emerald-300` |
| `color/emerald/400` | `#7FBE87` | `--operations-emerald-400` |
| `color/emerald/500` | `#61A66F` | `--operations-emerald-500` |
| `color/emerald/600` | `#478758` | `--operations-emerald-600` |
| `color/emerald/700` | `#326741` | `--operations-emerald-700` |
| `color/emerald/800` | `#264B36` | `--operations-emerald-800` |
| `color/emerald/900` | `#183225` | `--operations-emerald-900` |

#### State primitives

| Figma variable | Value | Purpose |
| --- | --- | --- |
| `color/orange/300` | `#F0AC69` | Warning support |
| `color/orange/400` | `#E69148` | Primary warning |
| `color/orange/500` | `#C96C32` | Strong warning |
| `color/orange/700` | `#7A4027` | Warning boundary |
| `color/orange/900` | `#39241D` | Warning surface |
| `color/red/500` | `#DB716B` | Error/danger |
| `color/red/800` | `#5A2A2C` | Danger surface |
| `color/blue/400` | `#70A9BD` | Informational/working |

### Collection B — `Mentat / Semantic`

Modes:

- `Standard`
- `High Contrast`

Components bind to these aliases. High Contrast changes semantic values without
requiring alternate component variants.

#### Surfaces

| Figma variable | Standard alias/value | Intended use |
| --- | --- | --- |
| `surface/canvas` | `neutral/950` | Main page |
| `surface/app-bar` | `neutral/1000` | Command header |
| `surface/sidebar` | `#070B0F` | Navigation rail |
| `surface/panel` | `neutral/850` | Primary panels |
| `surface/raised` | `neutral/800` | Popovers and expanded regions |
| `surface/row` | `#10171B` | Interactive rows |
| `surface/row-hover` | `neutral/750` | Hover/pressed row |
| `surface/input` | `neutral/900` | Form controls |
| `surface/selected` | Emerald 900 mixed with neutral 850 | Current selection |
| `surface/warning` | Orange 900 mixed with neutral 850 | Warning block |
| `surface/danger` | Red 800 mixed with neutral 850 | Error block |

#### Content, border, and state

| Figma variable | Standard alias | Intended use |
| --- | --- | --- |
| `content/primary` | `neutral/100` | Headings and essential values |
| `content/secondary` | `neutral/300` | Body and controls |
| `content/tertiary` | `neutral/400` | Metadata |
| `content/disabled` | `neutral/500` | Disabled/placeholder |
| `content/accent` | `emerald/300` | Selection and success emphasis |
| `content/on-accent` | `#07110B` | Content on filled accent |
| `border/subtle` | `neutral/700` | Panel and row separation |
| `border/default` | `neutral/650` | Raised boundaries |
| `border/strong` | `neutral/600` | Strong structure |
| `border/control` | `neutral/550` | Interactive control boundary |
| `focus/default` | `emerald/300` | Keyboard focus |
| `state/success` | `emerald/300` | Ready, complete, enabled |
| `state/warning` | `orange/400` | Attention, stale, degraded |
| `state/danger` | `red/500` | Failed, destructive |
| `state/info` | `blue/400` | Working, running |

The default control boundary is intentionally stronger than panel separators.
Interactive boundaries must maintain at least 3:1 non-text contrast against
their adjacent surface.

### Collection C — `Mentat / Dimension`

Modes: `Desktop`, `Compact`, `Phone` where a mode-specific value is needed.

| Figma variable | Value |
| --- | --- |
| `space/1` | 4 px |
| `space/2` | 8 px |
| `space/2-5` | 10 px |
| `space/3` | 12 px |
| `space/3-5` | 14 px |
| `space/4` | 16 px |
| `space/4-5` | 18 px |
| `space/5` | 20 px |
| `space/6` | 24 px |
| `space/8` | 32 px |
| `radius/xs` | 4 px |
| `radius/sm` | 6 px |
| `radius/md` | 10 px |
| `radius/lg` | 12 px |
| `radius/xl` | 16 px |
| `shell/sidebar/desktop` | 216 px |
| `shell/sidebar/compact` | 76 px |
| `shell/header/min-height` | 64 px |
| `layout/panel-gap` | 10 px |
| `control/touch-min` | 44 px |

### Figma setup procedure

1. Create the three collections and modes above.
2. Enter primitive values once.
3. Alias every Semantic variable to a Primitive variable wherever possible.
4. Bind component fills, strokes, text, and effects only to Semantic variables.
5. Bind auto-layout padding, gaps, radii, and shell dimensions to Dimension
   variables.
6. Name component properties by behavior (`State`, `Density`, `Expanded`) rather
   than by color.
7. Publish the library only after the Standard and High Contrast component
   pages have been checked side by side.
8. Keep the CSS token name in each Figma variable’s description so design and
   implementation can be audited mechanically.

## 4. Typography

### Families

- UI: `Inter Variable`, with `Inter`, system sans-serif fallbacks.
- Technical metadata: `JetBrains Mono`, with platform monospace fallbacks.

### Type styles

| Figma text style | Size / line | Weight | Use |
| --- | --- | --- | --- |
| `Heading/Page` | 24 / 30 | 600 | Full-page title where a page needs one |
| `Heading/Panel` | 17 / 22 | 600 | Panel titles |
| `Heading/Row` | 13 / 18 | 600 | Primary row labels |
| `Body/Default` | 13 / 19 | 400 | Main content |
| `Body/Compact` | 12 / 17 | 400 | Dense panel copy |
| `Meta/Default` | 11 / 16 | 400–500 | Time, counts, secondary status |
| `Meta/Compact` | 10 / 14 | 400–500 | Dense operational metadata |
| `Mono/Label` | 10 / 14 | 500 | Technical labels and status summaries |

Use sentence case. Uppercase is reserved for short technical metadata, not
navigation or primary headings. Numeric summaries use tabular figures.

## 5. Shape, borders, and elevation

- Primary panels: 12 px radius, subtle 1 px border, no drop shadow.
- Interactive rows: 9–10 px radius, subtle boundary; strengthen on hover.
- Controls: 6 px radius and the `border/control` token.
- Pills are reserved for compact state display. Do not use pill containers for
  ordinary steps, paragraphs, or every metadata value.
- Elevation is communicated through surface tone and border, not glow.
- Emerald is a state and focus color, not a decorative wash over every panel.

## 6. Iconography and brand

- Use 20–21 px outline icons in panels and 18–20 px icons in navigation.
- Strokes are approximately 1.7 px with round caps and joins.
- Decorative icons are hidden from assistive technology.
- Icon-only actions require a visible tooltip and accessible name.
- Keep the existing Mentat portrait as the product mark.
- Use `public/mentat-mark-emerald.png` on the Emerald shell: transparent
  background, warm-ivory/emerald correction, no enclosing bitmap square.
- Preserve safe space around the mark equal to at least one quarter of its
  rendered diameter.
- Never replace visible product text with “Mentat Operations.”

## 7. Component specifications

### Navigation item

- 44 px minimum height.
- Icon + sentence-case label.
- Current page: subtle emerald-tinted surface, 3 px leading accent, and
  `aria-current="page"`.
- Compact rail retains a descriptive accessible name.

### Panel header

- Left: icon, title, one-line supporting text.
- Right: one compact action group.
- Do not distribute sibling buttons across the full panel width.
- On narrow screens, wrap the action group below the heading.

### Operational Focus row

- 61 px minimum desktop height.
- Columns: 27 px state mark, flexible copy, status/time, chevron.
- Status uses shape/text as well as color.
- Show no more than three priorities on Home.
- Completion describes the planned-today set. If none exists, display “No
  Today plan,” not “0 of 0 done.”

### Live Agent row

- 78 px minimum desktop height.
- Show name, explicit Ready/Working/Needs attention/Unavailable label, role or
  current task, provider/model, distinct session count, open task count, and
  activity freshness when available.
- Profile identity comes from the selected connection’s canonical inventory.
- Runs are filtered to the exact current transport binding before status is
  derived.
- Actionable attention and working agents are ranked first, ready agents next,
  and unavailable profiles last when only three rows fit.

### Today schedule

- Always represents the operator’s current local day.
- Calendar remains read-only.
- Use a horizontal time scale on desktop and an agenda on phone.
- Generate enough vertical lanes to prevent concurrent events from covering one
  another.
- Expand the time scale to contain valid early and late events; never clamp a
  late event outside the track.
- Preserve a readable target for end-of-day events by shifting their visual
  block left when the minimum width would otherwise cross the right edge.
- Disconnected and stale states remain visible in warning text.

### Projects summary

- Four quiet values: Active, Paused, Tasks done, Archived.
- Below them, show one queue summary with next task, open count, and completion.
- Do not describe a project as “completed”; current project status vocabulary
  is Active, Paused, and Archived.

### Scheduled Automations

- Read-only Home surface.
- Show name, enabled/disabled text, schedule, last status, and next run.
- Show at most two rows.
- No Run, Queue, Edit, Enable, Disable, or Delete action appears until a
  separately approved safe capability exists.

### Agent Console dock

- Full-width final Home row.
- Primary strip: title, agent, model, attachment/composer/send, live state.
- Prompt, state, and Stop remain visible for active and waiting runs.
- `waiting_for_approval` and `waiting_for_clarification` are active states.
- History, provider review, and new-session controls expand below with native
  `<details>`.

### Empty and degraded states

| State | Treatment |
| --- | --- |
| Empty | One direct sentence; no illustration needed |
| Loading | Stable region with plain loading label |
| Stale | Warning text plus the last known content when safe |
| Disconnected | Name the unavailable source and fallback |
| Unsupported | Explain that the runtime does not expose the capability |
| Partial failure | Do not claim success; preserve verified state |
| Needs attention | Orange state label and action-oriented copy |
| Destructive failure | Red only when loss, invalid mutation, or hard failure is involved |

## 8. Interaction and motion

- Fast hover/focus transitions: 120 ms.
- Standard disclosure and panel transitions: 160 ms.
- Slow structural transition ceiling: 220 ms.
- Use the shared ease curve `cubic-bezier(.2, .8, .2, 1)`.
- Honor `prefers-reduced-motion`.
- Never loop decorative animation in the operations workspace.
- Typing in global search does not navigate; navigation occurs after explicit
  result selection.
- Request notification permission only from an explicit user action.

## 9. Accessibility contract

- WCAG 2.2 AA text contrast is the minimum target.
- Interactive boundaries maintain 3:1 non-text contrast.
- Focus is never indicated by color alone.
- Ready, Working, Attention, Enabled, and Disabled always have visible text.
- A control’s accessible name includes operational status or is associated with
  a concise description; an overriding `aria-label` must not hide useful
  descendant text.
- Polling does not replace a whole live region. Announce only bounded status
  changes.
- Drawer focus is contained while open; Escape closes it and returns focus.
- Native disclosure, select, button, and form behavior is preferred.

## 10. Content rules

- Use direct labels: “Live agents,” “Scheduled automations,” “Open calendar.”
- Use “Hermes” when referring to the runtime or connection, “agent” for a
  configured profile, and “run” for one execution.
- Use “session” only for a distinct Hermes session, not as a synonym for a run.
- Use local, human time for operator-facing schedules.
- Do not expose secrets, local paths, storage keys, environment-variable names,
  raw runtime errors, or private provider details.
- Keep empty-state copy factual and brief.

## 11. Figma component inventory

Create these component sets before redesigning the remaining pages:

```text
Shell/
  Sidebar
  Sidebar item
  Command header
  Connection selector
  Global search

Panel/
  Header
  Empty state
  Degraded state
  Disclosure

Row/
  Focus task
  Live agent
  Scheduled automation
  Project queue
  Session
  Note

Control/
  Button
  Icon button
  Input
  Select
  Textarea
  Status label
  Progress ring

Console/
  Command dock
  Composer
  Attachment
  Run event
  Approval request
  Clarification request
```

Minimum variants:

- State: Default, Hover, Focus, Disabled, Selected.
- Operational state: Ready, Working, Attention, Unavailable.
- Density: Standard, Compact.
- Contrast: Standard, High Contrast.
- Width examples: 1440, 1024, 390.

## 12. Design review checklist

Before a page is accepted:

- Does the first visible region answer “what needs attention now?”
- Are all counts and states derived from actual Mentat/Hermes data?
- Is read-only content labeled?
- Are action buttons grouped compactly at one edge?
- Does any state depend on color alone?
- Do empty and degraded states preserve the page hierarchy?
- Are advanced controls discoverable without dominating the default view?
- Is the page free of horizontal overflow at 1680, 1440, 1200, 1024, 900,
  768, and 390 px?
- Can every workflow be completed with a keyboard?
- Does the page work in Standard and High Contrast modes?
- Does the Mentat name and portrait remain intact?
- Are screenshots reviewed with sparse, normal, dense, error, and disconnected
  data?

## 13. Source of truth

- CSS implementation tokens: `public/styles.css`
- Application shell and component mounts: `public/index.html`
- Home behavior and state derivation: `public/app.js`
- Browser geometry and workflow checks: `scripts/browser_smoke.mjs`
- Migration plan: `MENTAT_OPERATIONS_IMPLEMENTATION_PLAN.md`
- Slice verification record: `reviews/2026-07-25-emerald-foundation-shell.md`

When design and implementation disagree, reconcile the difference explicitly.
Do not introduce a one-off component color or spacing value merely to match one
screen.
