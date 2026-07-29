# Mentat Operations UI Conversion Plan

Status: Foundation and Home implemented in an uncommitted review branch;
remaining page conversions are planned. Publication requires separate approval.

This plan converts Mentat incrementally to the Emerald operations design system
without rewriting the application or changing its capability boundaries.

## Outcomes

- Mentat keeps its existing product name, data model, Python server, and static
  frontend.
- All pages use the shared Emerald tokens, application shell, typography,
  spacing, and component states.
- Home follows the approved operations layout with Live Agents visible and no
  hero-card row.
- Existing workflows remain available while visual density and hierarchy
  improve.
- A saved Classic shell remains available until the conversion reaches parity.

## Constraints

- Preserve the current six internal view keys: `today`, `agents`, `calendar`,
  `projects`, `notes`, and `settings`.
- Do not write directly to Hermes core files.
- Do not add local/remote switching behavior as part of visual conversion.
- Keep Hermes CRON inventory read-only.
- Keep Google Calendar read-only.
- Preserve the Console, provider, identity, attachment, Context Pack,
  delegation, and confirmation safety boundaries.
- Prefer incremental DOM/CSS changes to a frontend-framework migration.

## Conversion sequence

### Slice 0 — Design contract

Status: Complete in this branch.

Deliverables:

- Emerald primitive and semantic token tables.
- Figma collection, mode, and alias specification.
- typography, spacing, radius, icon, state, and accessibility rules;
- responsive page anatomy;
- reusable component inventory.

Acceptance:

- Every implemented color maps to a documented semantic token.
- Component behavior is specified independently of sample data.
- Product naming and logo usage are explicit.

### Slice 1 — Foundation and shell

Status: Implemented and verified in this branch.

Deliverables:

- saved Emerald theme;
- saved Emerald/Classic shell preference;
- Standard, System, and High Contrast behavior;
- expanded desktop rail, compact intermediate rail, mobile drawer;
- command header, connection state, global search, operator identity;
- transparent color-corrected Mentat mark;
- keyboard, focus, responsive, packaging, and visual contract coverage.

Acceptance:

- All six existing views remain reachable.
- No page-level overflow at the viewport matrix.
- Current page, skip link, drawer focus, Escape, and focus return work.
- Static assets ship in source, wheel, sdist, and frozen builds.

### Slice 2 — Home operations workspace

Status: Implemented and verified in this branch; awaiting user outcome
acceptance.

Deliverables:

- remove overview metric cards from Home;
- Operational Focus and Live Agents in the first row;
- Today schedule and Projects/Scheduled Automations in the second row;
- compact full-width Agent Console dock;
- real canonical profile, current-binding run, task, project, calendar, and
  CRON data;
- bounded disclosures for quick add, completed work, agent review, and Console
  history.

Acceptance:

- Today never displays another day beneath a Today heading.
- Concurrent and late events remain visible.
- waiting-for-approval and waiting-for-clarification remain active Console
  states.
- Live Agent state cannot leak across local/remote transport bindings.
- CRON remains read-only and Enabled/Disabled is explicit.
- Quick Add and Completed Work never clip at supported widths.

### Slice 3 — Agents and Sessions

Status: Planned.

Goals:

- convert profile list, selected-agent inspector, session history, and model
  usage to Emerald rows and panels;
- keep live operational state at the top;
- retain Agent Creator, provider selection, identity, skill, delete, and
  confirmation flows;
- distinguish profile identity, run status, and session history clearly;
- reuse the Home Live Agent row and Status Label components.

Suggested layout:

```text
Managed agents rail | Selected agent detail
                    | Session history / model usage
```

Verification:

- profile availability and capability states;
- long profile names and provider/model values;
- empty, unavailable, and partial inventories;
- active Console run mutation locks;
- all dialogs and confirmation tokens;
- 1440, 1024, 900, 390 px rendered review.

### Slice 4 — Projects and Tasks

Status: Planned.

Goals:

- retain the portfolio/task/inspector workflow while replacing dense legacy
  chrome;
- make current queue, blocked work, delegation state, and selected-task actions
  visually dominant;
- reuse Operational Focus rows, Project Queue, Status Label, and disclosures;
- preserve task planning, dependencies, recurrence, notes, calendar links,
  deletion, and Hermes delegation safeguards.

Suggested layout:

```text
Project rail / filters
Task queue            | Selected task inspector
```

Verification:

- all task states and filters;
- long descriptions, subtasks, dependencies, recurrence;
- safe delegation preview/confirmation/review;
- calendar and note links;
- project and task creation/edit/delete;
- dense and empty project fixtures.

### Slice 5 — Calendar

Status: Planned.

Goals:

- apply Emerald typography, borders, controls, and state labels to Operator
  Week;
- preserve exact seven-day navigation and timezone behavior;
- visually distinguish verified Google events, local fallback, linked tasks,
  and disconnected examples without implying write access;
- reuse the Home schedule scale where appropriate without reducing the full
  week view.

Verification:

- all-day, overlapping, cross-midnight, DST, early, and late events;
- exact-week navigation and stale-response rejection;
- event inspector and safe task linking;
- disconnected preview mutation restrictions;
- 1440, 1024, 768, and 390 px.

### Slice 6 — Notes and Context

Status: Planned.

Goals:

- convert notes search/list/detail and Context Packs to the Emerald panel and
  row system;
- keep note paths vault-relative and context references bounded;
- make selection, attachment, stale reference, and validation states explicit;
- reuse Empty/Degraded State, Disclosure, Input, and compact action groups.

Verification:

- long note titles and excerpts;
- no absolute-path exposure;
- missing, changed, and unsafe reference states;
- Context Pack creation, application, and deletion;
- narrow-width search and picker behavior.

### Slice 7 — Settings, dialogs, and support

Status: Planned.

Goals:

- organize connection, appearance, health, capability inventory, version,
  diagnostics, and support into clear Emerald sections;
- preserve theme, shell, and contrast controls;
- standardize dialog spacing, button grouping, warning text, and review steps;
- keep local/remote connection configuration behavior unchanged until its
  separate product capability is approved.

Verification:

- local, remote, unavailable, and degraded connection summaries;
- High Contrast across every saved theme/shell combination;
- all destructive and confirmed flows;
- diagnostics download and support links;
- keyboard dialog focus and Escape behavior.

### Slice 8 — Parity, cleanup, and Classic retirement decision

Status: Planned.

Goals:

- run cross-page component and token audit;
- remove obsolete selectors only after every existing workflow has parity;
- complete Safari, Firefox, and screen-reader review;
- decide whether to retain or retire the Classic shell;
- update screenshots, changelog, and contributor guidance.

Classic is not removed automatically. Retirement requires:

- all six pages accepted in Emerald;
- no workflow relies on Classic-only layout;
- migration and recovery are documented;
- a separately approved publication slice.

## Current-to-target mapping

| Existing surface | Target component or pattern |
| --- | --- |
| Horizontal primary navigation | Responsive Sidebar |
| Greeting hero | Accessible page heading/operator avatar; no Home hero |
| Overview metric cards | Contextual summaries inside Focus/Projects |
| Today next moves | Operational Focus |
| Agent activity panel | Live Agents disclosure |
| Calendar preview | Today schedule |
| Project summary cards | Projects summary + queue |
| CRON monitor-only visibility | Read-only Scheduled Automations on Home plus full monitor |
| Tall Console panel | Compact Console dock + expandable history |
| Generic stacked `.item` rows | Named Emerald row components |
| Component-specific colors | Semantic variables |
| Distributed action buttons | Compact edge-aligned action groups |

## Delivery rules for each slice

1. Write observable acceptance criteria.
2. Map each criterion to a focused test or rendered check.
3. Preserve existing functional mounts and capability boundaries.
4. Implement one page or coherent component family.
5. Test sparse, normal, dense, loading, empty, degraded, and error data.
6. Run the supported viewport matrix.
7. Obtain two independent adversarial reviews.
8. Fix blocking findings and request re-review.
9. Present the rendered outcome to the user.
10. Commit or publish only after explicit approval.

## Test matrix

### Automated

- JavaScript syntax.
- Python unit and contract suite.
- DOM mount uniqueness and source contracts.
- current-page and keyboard behavior.
- page geometry, overflow, and touch targets.
- live workflow smoke in disposable Chromium.
- theme/shell/contrast persistence.
- packaged static-asset inventory.

### Rendered fixtures

Every converted page should be inspected with:

- no data;
- one item;
- typical data;
- maximum supported Home/list density;
- long names and metadata;
- stale/disconnected dependencies;
- current local connection;
- current remote connection;
- active, waiting, failed, and completed runs;
- Standard and High Contrast.

### Manual release checks

- Safari and Firefox.
- VoiceOver or equivalent screen reader.
- keyboard-only traversal.
- 200% zoom.
- reduced motion.
- packaged macOS and Windows builds.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Visual rewrite silently removes a workflow | Preserve IDs; add workflow smoke before restyling |
| Dense data clips without page overflow | Open disclosures and use populated fixtures at every width |
| Local run state appears on remote agent | Filter runs by exact transport binding |
| State becomes color-only | Pair color with text and accessible descriptions |
| Empty screens feel unfinished | Preserve hierarchy with concise, bounded empty states |
| Legacy CSS leaks into the new layout | Use explicit grid areas and computed geometry checks |
| One-off styles fragment the system | Require semantic token and named component mapping |
| Classic breaks during incremental migration | Test Classic geometry until retirement is approved |

## Definition of complete

The conversion is complete when:

- every current workflow is present and verified in Emerald;
- all six views use shared tokens and named component patterns;
- Home and every detail page work at the supported viewport matrix;
- Standard and High Contrast pass the visual contract;
- the Mentat name and original portrait remain consistent;
- manual cross-browser and screen-reader checks are closed;
- the user accepts the rendered outcome;
- publication is separately authorized.
