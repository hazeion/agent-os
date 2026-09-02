# PT-2C review log — optional visual dependency map

Issue: [#174](https://github.com/hazeion/agent-os/issues/174)
Wayfinder map: [#165](https://github.com/hazeion/agent-os/issues/165)
Branch: `codex/pt-2c-visual-dependency-map`

## Approved scope

- Add a bounded, optional Map tab to the existing Projects & Tasks workbench.
- Make the map a presentation-only projection of canonical SQLite Task
  dependencies for the selected Project, with deterministic layout and safe
  cross-Project endpoint stubs.
- Keep the semantic dependency editor and its exact-revision save/readback
  flow as the only dependency editing authority.
- Time-box pinned `@xyflow/react` 12.11.5 behind the desktop Map tab, with a
  source-owned read-only SVG overview fallback if its package, hydration,
  offline, accessibility, mobile, bundle, or Lighthouse gates do not hold.

## Explicit exclusions

- No Canvas, graph-only write endpoint, optimistic graph mutation, or browser
  selected runtime/project/file authority.
- No persisted node positions, viewport metadata, layout engine, or second
  Task/dependency authority.
- No change to Task dispatch, review cycles, Kanban delegation, Agent-created
  Tasks, or cascade deletion.

## Verification strategy

- Establish exact projection caps and validation in Python, the private bridge,
  Node, and UI contracts before visual implementation.
- Test deterministic layout, selected Task/Project/filter coherence, cross-
  Project stubs, truncation/count disclosure, keyboard/focus behavior, staged
  semantic-editor save behavior, and failure fallback.
- Complete production-build browser acceptance at desktop and narrow/mobile
  viewports; test pointer and keyboard interaction, zoom, reduced motion, and
  no page-level overflow.
- Before merge, run focused and broad suites, the full GitHub CI matrix, and
  independent authority/bounds and accessibility/hydration/performance reviews.

## Implementation and review result

- Added a fixed, selected-Project map projection with 50 Project nodes, 50
  external endpoint stubs, and 250 edges as strict server/bridge/public-client
  caps. The projection contains no descriptions, revisions, paths, or mutation
  authority.
- The Map tab is lazy-loaded and only fetches while selected. List, Board, Map,
  saved views, and the bounded title/preview filter now share one normalisation
  contract. A verified Task mutation invalidates the Map even if its optional
  detail read-back cannot complete.
- Desktop uses pinned React Flow 12.11.5 with deterministic source-owned
  layout and non-connectable source/target handles; narrow layouts use the
  keyboard-selectable source-owned SVG overview. External stubs stay
  noninteractive. Map activation uses one React Flow node-click route.
- Independent review found and the implementation corrected: an invalid
  stub-to-stub bridge edge, map filtering after pagination, stale map refresh
  after a successful edit, missing desktop edge handles, duplicate desktop node
  activation, and Unicode filter mismatch.

## Local verification

- Focused Python map/bridge/model suite: 64 passed.
- Web lint, typecheck, and test suite: passed after the final fixes.
- Production build: passed.
- Browser acceptance used an isolated seed data root: created a dependency via
  the existing semantic editor, confirmed the desktop edge rendered, clicked
  graph nodes into the existing Task inspector, exercised Zoom In/Fit View,
  filtered the map, and confirmed the narrow SVG fallback selects Tasks. No
  browser console errors were reported.
- The broad local Python suite is still tracked separately; it reported an
  existing Windows data-root preflight failure unrelated to this slice while
  continuing through the matrix-like suite. GitHub CI remains the merge gate.
