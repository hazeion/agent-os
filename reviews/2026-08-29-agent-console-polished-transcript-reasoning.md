# Feature Slice Review: Agent Console polished transcript and reasoning summaries

Status: Complete
Slice: `agent-console-polished-transcript-reasoning`
Date: `2026-08-29`
Review log: `reviews/2026-08-29-agent-console-polished-transcript-reasoning.md`

## Slice contract

### Goal

Make the durable Agent Console transcript easy to scan and safe to use: messages
remain primary, bounded Markdown and inert code gain useful hierarchy and copy
actions, exact safe tool/reasoning summaries live in disclosures, and long live
transcripts remain stable, accessible, and responsive.

### In scope

- Render a deliberately small Markdown subset as React text elements. Support
  paragraphs, headings, lists, emphasis, inline code, and fenced code without
  `dangerouslySetInnerHTML` or arbitrary HTML parsing. URLs remain plain text
  until Slice 7's safe link boundary.
- Render fenced code as inert text with bounded language-token highlighting,
  horizontal containment, wrapping/scrolling, and explicit copy. Never execute
  it, transform it into a command, or send it to a terminal.
- Preserve safe event provenance so only allowlisted tool activity and genuine
  runtime-provided `reasoning.available` summaries can drive Activity/Thinking.
  Never derive Thinking from assistant prose.
- Group durable Messages into visible Run/queued boundaries without exposing
  private runtime IDs. Keep assistant Messages and user prompts dominant over
  status, tool, or reasoning detail.
- Thinking expands while safe summarized reasoning is active, collapses after
  later progress/terminal state, and remains manually reopenable. Activity is
  collapsed by default and contains summary-only rows.
- Add focused live-region transitions, copy feedback, keyboard focus, reduced
  motion, bidi isolation, scroll anchoring, and a repeatable 200-row stress gate.
- Apply the user's requested adjacent Console polish: compact Chrome-like tabs
  with visible close controls and no redundant Active line, measured centering
  between the navigation and activity rails, and a collapse arrow that always
  points toward its next action.

### Out of scope

- Raw chain-of-thought, provider reasoning payloads, tool arguments/results,
  logs, paths, credentials, raw event data, or arbitrary HTML.
- Syntax-highlighting dependencies, HTML sanitizers, MDX, executable snippets,
  command promotion, arbitrary file/URL opening, images, artifacts, or rich-link
  previews from later slices.
- New runtime telemetry sources or parsing model/CLI prose to infer activity.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Messages remain primary and render the approved safe Markdown hierarchy with inert code and copy. | Renderer unit/interaction and browser tests. | Passed |
| AC-2 | Hostile HTML/Markdown, bidi controls, oversized blocks, unsafe links, and code overflow remain inert and contained. | Hostile fixture and responsive tests. | Passed |
| AC-3 | Thinking appears only from genuine safe reasoning provenance, opens while active, collapses later, and is reopenable. | Backend provenance plus Home state-transition tests. | Passed |
| AC-4 | Tool Activity is summary-only, collapsed by default, ordered, bounded, and contains no raw data. | Bridge/event and disclosure tests. | Passed |
| AC-5 | Run/message groups preserve screen-reader order and queued/no-Run messages without exposing private IDs. | Transcript semantic tests. | Passed |
| AC-6 | Copy, focus, live announcements, scroll anchoring, and reduced motion behave without layout churn. | Interaction and visual-contract tests. | Passed |
| AC-7 | The 200-row stress fixture meets the recorded responsiveness budget; focused/full/build/browser/review gates pass. | Performance script, full evidence, reviewers. | Passed |

### Constraints and recovery

- Durable Message text and canonical Agent events remain authoritative. The
  browser holds only transient disclosure/open/copy state.
- Safe presentation type must be derived from validated canonical event source
  provenance. Unknown or malformed sources project no Thinking/Activity hint.
- Existing 100-Message pages and 200-row DOM ceiling remain unchanged.
- Plain text is the permanent fallback for every unsupported construct.
- Branch: `codex/agent-console-slice-6`; ready PR into `main`.

### Scope discussion and approval

- The user granted standing approval for all remaining slices and explicitly
  authorized parallel agents for bounded work inside a slice. Backend event
  provenance and the standalone safe renderer are being developed in parallel;
  integration, combined testing, browser use, and two final adversarial reviews
  remain centralized.
- Approved at: 2026-08-28 conversation; parallelization confirmed 2026-08-29.

## Test strategy

| Criterion | Planned evidence | What it proves |
| --- | --- | --- |
| AC-1, AC-2 | Pure renderer fixtures for headings/lists/emphasis/code plus scripts, event handlers, malformed fences, unsafe schemes, bidi, and long lines. | Richness never becomes HTML execution or overflow. |
| AC-3, AC-4 | Canonical source-type tests, strict bridge parsers, live event sequences, terminal/reopen behavior, and raw-data canaries. | Only safe provenance drives disclosures. |
| AC-5, AC-6 | DOM order, keyboard copy/focus, polite transition announcements, reduced-motion CSS, append-at-bottom and scrolled-up tests. | Transcript stays accessible and stable during updates. |
| AC-7 | Existing 200-row Home fixture plus repeatable performance command, production build, desktop/mobile browser run, full suites, and two reviewers. | Integrated behavior remains within the bounded Console budget. |

### Test discussion and approval

- Standing approval covers the strategy. Unsupported Markdown remains text;
  no dependency is approved unless the existing platform cannot satisfy the
  safe subset.

## Implementation record

- Added a source-type-aware internal Run-event read model and a fixed public
  `presentation` projection. Only validated tool lifecycle sources and genuine
  provider reasoning availability receive a browser hint; all other events
  receive `null`.
- Added a dependency-free bounded transcript renderer with React text nodes,
  inert token highlighting, Message/code copy, bidi replacement, and hostile
  input tests. Formatting is capped at 512 units per Message and 8,000 units
  across the retained transcript, with bounded plain-text fallback.
- Added presentation-only Run/queued Message groups, Thinking and Activity
  disclosures, selected-Run event merging, transition announcements, reduced
  motion, and per-Conversation scroll anchoring. Run labels reuse stable
  first-seen ordinals across queued interleaving; Run-local disclosure state is
  keyed by exact selected Run.
- Reconnect snapshots merge or replace according to the exact reset flag;
  explicit resets replace, malformed envelopes fail closed, and bounded
  null-presentation markers preserve disclosure ordering without rendering.
- Reworked Conversation tabs into a 34-pixel connected strip with 44-pixel
  mobile close targets, removed the redundant state line, and kept close
  presentation-only.
- Made the navigation arrow describe its next action and made shell DOM writes
  idempotent. Production testing caught and fixed a mutation-observer feedback
  loop caused by unconditional synchronization writes.
- Removed the desktop max-width gutter and measured the Conversation workspace
  at an exact zero-pixel center delta between the 216-pixel navigation rail and
  330-pixel activity rail.
- Hardened the production performance driver by registering CDP response state
  before sending and adding bounded command timeouts plus opt-in progress logs.

## Verification

- `npm --prefix web run check`: 127 passed; lint and typecheck clean.
- `node scripts/run-next.mjs build --webpack` plus
  `node scripts/prepare-standalone.mjs`: production build passed.
- `npm run performance:agent-console`: seven production Chromium samples,
  200 retained rows, zero typing network requests; final uncontended medians were
  145.6 ms accepted dispatch, 11.1 ms loaded tab, 9.6 ms optimistic paint, and 5.1 ms
  stream paint.
- In-app browser at 2048×900: 34-pixel tabs, working presentation-only close,
  no Active labels, correct `‹`/`›` rail transitions, and exact 0-pixel Console
  center delta. At 390×844: no page overflow, contained horizontal tab scroll,
  and 44-pixel close targets.
- `python -m unittest discover -s tests -v` with host loopback permission:
  1,652 passed, 5 skipped, in 897.386 seconds. A prior sandboxed run reached the
  same test count but correctly failed 46 loopback-bind setups; it is not used
  as publication evidence.

## Adversarial review

- Product/accessibility/performance and safety/backend reviewers independently
  reviewed the full integrated diff. Their findings drove fixes for structural
  DOM amplification, aggregate formatting bounds, stable Run ordinals,
  Run-local disclosure state, reset/reconnect ordering, null-presentation
  ordering markers, and per-Conversation scroll state. Both final re-reviews
  returned no findings.

## Documentation updates

- Updated `AGENTS.md`, `ARCHITECTURE.md`, and `CHANGELOG.md` with the safe
  transcript grammar, event provenance, DOM bounds, Console layout, tab-close,
  and idempotent shell synchronization contracts.

## Publication gate

- Standing authorization was recorded. Implementation PR #152 passed all 51
  GitHub checks and merged to `main` as `89a3b127bdcc2594ec6e0c54c38c35962d4ece56`
  on 2026-08-29. GitHub issue #138 closed with the merge.

## Outcome review

- Classification: Met the approved Slice 6 scope. The safe transcript,
  provenance-aware disclosures, bounded long-transcript behavior, requested tab
  and rail polish, browser use, production performance gate, full repository
  suite, and both adversarial re-reviews are complete.
