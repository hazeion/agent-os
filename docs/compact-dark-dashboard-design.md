# Mentat Compact Dark Dashboard Design

Source inspiration: the provided Agentlytics-style analytics dashboard screenshot — dense dark command UI, sharp card edges, thin charcoal borders, mono labels, and many scan targets visible above the fold.

## Intent

Rewrite the dashboard UI without changing features or data contracts. The redesign should make the first page feel like a compact operator board: more panels visible immediately, less decorative whitespace, sharper boxes, darker surfaces, and higher information density.

## Design Principles

1. **Density first** — every major section should use tighter spacing, smaller titles, shorter cards, and scroll-contained lists where needed.
2. **Sharp, low-radius geometry** — cards and controls should feel like precise instrument panels, not rounded app widgets.
3. **Quiet dark surfaces** — use near-black and charcoal layers with subtle borders; avoid heavy glows and glass blur except for state emphasis.
4. **Mono telemetry language** — labels, metrics, nav, status pills, and metadata use monospace for a console/analytics feel.
5. **Feature parity** — preserve current navigation, panels, controls, task write-back surfaces, session replay, Agent Pulse, Calendar, Notes, and Settings behavior.
6. **Accent as signal, not decoration** — reserve saturated cyan, green, amber, red, and violet for state, focus, and charts/status cues.

## Design Tokens

```css
:root {
  color-scheme: dark;

  --bg: #050505;
  --bg-elevated: #0b0b0c;
  --sidebar: #080808;
  --card: #121212;
  --card-2: #161616;
  --card-3: #1a1a1b;

  --line: rgba(255, 255, 255, 0.08);
  --line-strong: rgba(255, 255, 255, 0.16);
  --line-hot: rgba(107, 102, 255, 0.42);

  --text: #e8e8ea;
  --muted: #858589;
  --muted-2: #5f5f64;

  --accent: #16c8de;
  --accent-2: #7567ff;
  --success: #18c76f;
  --warn: #d99000;
  --danger: #ff4d6d;

  --radius: 2px;
  --radius-sm: 1px;
  --space-1: 4px;
  --space-2: 6px;
  --space-3: 8px;
  --space-4: 10px;
  --space-5: 12px;
  --space-6: 16px;
}
```

## Layout Rules

### Shell / Navigation

- Replace the space-heavy left rail feel with a compact sticky top command rail using the existing navigation markup.
- Header height target: **56–68px**.
- Brand mark target: **32px** square.
- Nav items: inline, uppercase/mono, 34–40px tall, squared corners, active item indicated by border/background rather than glow.
- Sidebar footer becomes a right-aligned compact status strip.

### Main Command Surface

- Main padding: **16–20px desktop**, **10–12px mobile**.
- Keep content full-width with dense grids; avoid large centered hero spacing.
- Top greeting/search header becomes a compact bordered toolbar, not a large hero.
- H1 target: **1.25–1.45rem**, mono, no oversized display treatment.

### Metrics

- Metric cards target height: **70–80px**.
- Desktop grid should auto-fit **5–8 cards per row** depending on viewport width.
- Metric card padding: **10px**.
- Metric value: **1.35–1.55rem**, mono, high contrast.
- Metric label: uppercase, small, muted.

### Panels / Cards

- Panel padding: **10–12px**.
- Panel gap: **8–10px**.
- Border: `1px solid var(--line)`.
- Radius: `2px` or less.
- Box shadow: none by default; use border color for hierarchy.
- Panel headers: uppercase mono, **0.78–0.88rem**, muted/cyan.
- Child rows/cards should be flatter than parent panels and only highlight on hover/focus.

### Today View

- Desktop grid: three columns for Open Queue, Agent Pulse, Calendar; Completed Work wraps below.
- Open Queue should show more compact task rows above the fold (8 target rows when available).
- Task rows target height: **70–82px** with two-line description clamp.
- Calendar preview should show **5 events** when available.
- Completed Work should remain compact and horizontal where width allows.

### Projects / Tasks

- Preserve refined-A model: queue left, selected task inspector right.
- Use tighter portfolio cards and task rows, but do not starve the selected inspector; right column minimum stays roughly **360px** on desktop.
- Project cards: **220–260px** wide in the horizontal rail, **112–132px** tall.
- Task queue rows: compact, strong selected left edge or inset border.

## Component Details

### Buttons / Controls

- Default height: 30–36px.
- Border radius: 2px.
- Background: `#121212` / `#161616`.
- Hover: brighter border + slightly lighter background; avoid movement/translate animations.
- Focus-visible: clear outline or border using cyan/violet.

### Pills

- Small squared badges; use uppercase mono.
- Padding: `3px 7px`.
- Border uses semantic color at low opacity.

### Scroll Containers

- Long lists inside dashboard panels should scroll internally where practical.
- Use dark thin scrollbars where supported.
- Avoid allowing one panel to push the whole first page too far down.

### Typography

- Mono-first dashboard language: JetBrains Mono / ui-monospace.
- Body copy can remain system sans, but labels/metrics/nav/status must be mono.
- Reduce letter spacing on body; use uppercase letter spacing only for labels.

## State Colors

- Cyan `#16c8de`: open/running/focus.
- Green `#18c76f`: completed/healthy/live.
- Amber `#d99000`: waiting/due/stale.
- Red `#ff4d6d`: needs attention/failed.
- Violet `#7567ff`: selected/accent/navigation.

## Implementation Notes

- Implement as CSS-first rewrite using existing DOM and JS hooks.
- Keep JS changes limited to visible-density knobs such as preview item counts.
- Add visual contract coverage so future changes preserve the compact board tokens.
- Verify with syntax checks, unit tests, live server smoke tests, and a real screenshot capture.
