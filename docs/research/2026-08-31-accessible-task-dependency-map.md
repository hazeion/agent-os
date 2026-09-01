# Accessible editable Task dependency map

Date: 2026-08-31
Wayfinder ticket: [hazeion/agent-os#167](https://github.com/hazeion/agent-os/issues/167)

## Decision

Use [`@xyflow/react` 12.11.5](https://www.npmjs.com/package/@xyflow/react/v/12.11.5) for a bounded, optional Dependency map in a future implementation slice. Keep a complete semantic HTML dependency editor beside it. Pin the package and do not add a layout package in the first slice.

This recommendation is conditional. React Flow must pass the accessibility, packaging, and performance gates in this note before it becomes a production dependency. In particular, manual screen-reader results matter because React Flow's root has a hard-coded [`role="application"`](https://github.com/xyflow/xyflow/blob/b1b99e9773040e25bd6099762491ab23d8ea6910/packages/react/src/container/ReactFlow/index.tsx#L318-L329), which can change how assistive technology handles keyboard input under the [WAI-ARIA application contract](https://www.w3.org/TR/wai-aria-1.2/#application).

If it fails any gate, use the concrete fallback described below: ordinary HTML controls remain the exact editor, and a source-owned inline SVG provides a bounded read-only overview. Do not fall back to Canvas.

This research does not approve a package installation or production implementation.

## Mentat constraints

Mentat currently uses Next.js 16.3.2, React 19.2.8, and React DOM 19.2.8, as pinned in [`web/package.json`](../../web/package.json). React Flow declares React and React DOM `>=17`, while X6's React adapter declares React and React DOM `>=18`, so both fit the declared peer ranges. A passing peer range is necessary, but it is not proof that a library behaves correctly under React 19 hydration.

The canonical Task model imposes tighter constraints than either library:

- [`task_repository.py`](../../task_repository.py) caps the complete collection at 2,048 Tasks and validates dependency existence and cycles across that complete collection.
- [`task_planning.py`](../../task_planning.py) allows at most 100 `depends_on` identifiers per Task and rejects self-dependencies.
- The repository validation does not require a dependency and its Task to share a Project. This means cross-Project dependencies are legal. That is an inference from the implemented checks, which validate Task identity but contain no same-Project restriction.
- [`conversation_planning.py`](../../conversation_planning.py) already caps a Project Task page at 50 rows. The map should preserve that bounded read instead of loading the 2,048-Task route into a graph.
- The Next.js boundary currently permits only same-origin connections, nonce-bearing local scripts, and local styles, with `style-src 'unsafe-inline'`, in [`web/src/proxy.ts`](../../web/src/proxy.ts). A graph package must not require a CDN, remote worker, runtime compiler, or new network origin.
- [`ARCHITECTURE.md`](../../ARCHITECTURE.md) requires every later interactive route to keep its own performance budget and retain 100 scores in the existing six-run desktop/mobile Lighthouse gate.

The map is a projection of canonical Tasks. It must never become Task authority.

## Candidate comparison

Published package sizes below are npm's compressed tarball or unpacked distribution sizes. They are not tree-shaken route bundle sizes. A production spike must measure the actual Next.js route delta.

| Option | Compatibility and maintenance | Accessibility evidence | SSR, layout, and package cost | Result |
| --- | --- | --- | --- | --- |
| React Flow, `@xyflow/react` 12.11.5 | The [package manifest](https://github.com/xyflow/xyflow/blob/b1b99e9773040e25bd6099762491ab23d8ea6910/packages/react/package.json) declares React `>=17`, MIT licensing, and three direct runtime dependencies. npm published 12.11.5 on 2026-08-25. The [security policy](https://github.com/xyflow/xyflow/security) supports 12.x and lists no published repository advisories. | First-party docs specify focusable nodes and edges, Tab navigation, Enter/Space selection, Escape, arrow-key node movement, focus auto-pan, ARIA labels, and live updates. [Accessibility guide](https://reactflow.dev/learn/advanced-use/accessibility) | React Flow 12 supports SSR when node, handle, and optional container dimensions are supplied. [SSR guide](https://reactflow.dev/learn/advanced-use/ssr-ssg-configuration) The [official package metadata](https://registry.npmjs.org/@xyflow/react/12.11.5) reports a 251,058-byte tarball and 1,213,198 unpacked bytes. It has no layout engine. | Preferred, subject to gates. |
| AntV X6 3.1.8 plus `@antv/x6-react-shape` 3.0.1 | The core was published in August 2026. The React adapter's current `latest` tag was published in November 2025. Both use MIT licenses. The [React adapter guide](https://x6.antv.antgroup.com/en/tutorial/intermediate/react) requires X6 3.x with the 3.x adapter and React 18 or later. | X6 renders SVG and HTML, but its first-party docs provide no equivalent screen-reader, focus-order, ARIA live-region, forced-colors, or reduced-motion contract. Its [keyboard plugin](https://x6.antv.antgroup.com/tutorial/plugins/keyboard) binds shortcuts after the graph container receives focus. That is not a node and edge keyboard model. | The [core package](https://registry.npmjs.org/@antv/x6/3.1.8) is 8,563,331 bytes unpacked and the [React adapter](https://registry.npmjs.org/@antv/x6-react-shape/3.0.1) is another 1,069,430 bytes. X6 claims SSR in its [source repository](https://github.com/antvis/X6). The adapter's default mode creates its own React root, while its portal mode needs extra integration. Hydration would need its own proof. | Reject for Mentat. It is larger and leaves more accessibility work to the application. |
| Source-owned HTML nodes with inline SVG edges | No React compatibility or third-party maintenance risk. HTML controls keep native semantics. SVG 2 supports ARIA relationships, focus, `tabindex`, keyboard events, names, and descriptions. [SVG 2 accessibility appendix](https://www.w3.org/TR/SVG/access.html) | Mentat owns every focus and announcement rule. The safest form uses HTML for interactive nodes and editing, and treats SVG paths as visual output with an exact HTML equivalent. | Deterministic SSR is straightforward because layout and markup are owned. Package cost is zero. Mentat would have to build pan, zoom, pinch, connection gestures, viewport state, hit testing, and layout. | Concrete fallback. Keep the SVG read-only to avoid rebuilding a graph editor. |
| Canvas or WebGL | Reagraph 4.32.0 is a current React/WebGL example, but its [GraphCanvas source](https://github.com/reaviz/reagraph/blob/d2f4f0822e54c8cb0866d51ccb26f08e9fe0a3fe/src/GraphCanvas/GraphCanvas.tsx#L253-L259) renders through a canvas and does not create an accessibility object for every graph node and edge. | The HTML standard says an interactive canvas needs a one-to-one focusable fallback element for each interactive region. [HTML canvas accessibility requirements](https://html.spec.whatwg.org/multipage/canvas.html#the-canvas-element) That duplicates the complete interaction model. | Reagraph's [package metadata](https://registry.npmjs.org/reagraph/4.32.0) reports 686,710 unpacked bytes and a substantial Three.js, React Three Fiber, graphology, force-layout, animation, and gesture dependency set. | Not credible for this feature. The fallback DOM would be the real editor, so Canvas adds cost without reducing accessibility work. |

### React Flow strengths

React Flow covers the expensive interaction mechanics well:

- Its [viewport model](https://reactflow.dev/learn/concepts/the-viewport) includes pointer pan, wheel or pinch zoom, controlled `x`, `y`, and `zoom`, plus named zoom and fit controls.
- Its [MiniMap](https://reactflow.dev/api-reference/components/minimap) is an SVG overview with an accessible name. It can pan and zoom, although Mentat should keep it non-interactive and omit it on mobile.
- Nodes can use `parentId` for visual grouping and edges can cross group boundaries. [Sub-flow guide](https://reactflow.dev/learn/layouting/sub-flows)
- `isValidConnection` can reject a proposed edge. The official [cycle-prevention example](https://reactflow.dev/examples/interaction/prevent-cycles) walks outgoing edges before accepting a connection.
- `onlyRenderVisibleElements` can reduce DOM work. The [component API](https://reactflow.dev/api-reference/react-flow) also notes that this optimization has its own overhead, so it is not permission to feed the component all 2,048 Tasks.
- Version 12 can render static markup and hydrate it when the server provides stable node dimensions and handle positions. That fits a fixed-size Mentat Task card.

### React Flow risks

The accessibility guide is useful, but it does not close the ticket by itself.

1. The guide documents keyboard selection, deletion, and node movement. It does not document keyboard creation or reconnection of an edge. Pointer and touch users can connect handles. Keyboard and screen-reader users therefore need the semantic dependency editor.
2. Nodes and edges are all tabbable by default. A dense 50-Task page can contain thousands of legal edges because each Task permits 100 dependencies. Making every edge a tab stop would be unusable.
3. The root `role="application"` asks screen readers to pass most keyboard commands through to the web application. WAI-ARIA permits this for nonstandard interaction models, but it also warns that some assistive technologies expose only focusable descendants in that region. Static instructions and relationship text must remain available outside the graph.
4. React Flow uses measured DOM geometry. Its [testing guide](https://reactflow.dev/learn/advanced-use/testing) recommends browser tests and requires measurement mocks for DOM-only unit tests.
5. The package supplies pan, zoom, and rendering, not automatic layout. Layout is Mentat's responsibility.

These are manageable only because the map is optional and bounded.

## Recommended product and data shape

### Two equal views

Projects & Tasks should offer two synchronized views:

- **Dependencies.** The exact semantic editor. Show the selected Task, its prerequisites, and its dependents as normal text, links, buttons, and a bounded Task picker. Add and remove operations use this view's controls.
- **Map.** The visual overview. Selecting a node opens the same Task detail and dependency controls. Pointer or touch edge creation may open the same confirmation flow, but it cannot be the only way to edit.

The Dependencies view should remain available even if JavaScript graph initialization fails. On narrow screens and at high browser zoom, make it the default view.

### Bounded graph projection

Do not send the global 2,048-Task collection to React Flow. Use a dedicated read projection with explicit counts and truncation:

- At most 50 Task nodes from the selected Project page.
- At most 50 boundary stubs for dependencies outside that page, including cross-Project Tasks.
- At most 250 rendered edges. If the exact relation count is higher, show a density warning and keep the full relation set in the Dependencies view.
- Include total Task, external-node, and edge counts so truncation is visible. Never silently omit a relation.
- Key pagination and viewport state to the selected Project, page cursor or filter digest, and a layout-version number.

The 250-edge recommendation is a presentation limit, not a Task-model limit. It prevents the worst legal 50-node page from creating thousands of SVG paths and tab stops. The semantic editor remains exact.

Persist only validated `x`, `y`, and `zoom` presentation values, keyed by Project ID, page or filter digest, and layout version. Clamp each value to fixed bounds. Reset the viewport when its layout version or visible scope changes. Never store node positions as Task fields. React Flow's [save and restore example](https://reactflow.dev/examples/interaction/save-and-restore) uses the same three viewport values.

### Cross-Project dependencies

Render the selected Project's Tasks as the main graph. Represent an off-page or cross-Project endpoint as a compact boundary node labeled with both Project and Task name. Group multiple hidden endpoints only when the group shows an exact count and can open the filtered Dependencies view.

Do not load every linked Project into one graph. Do not encode Project ownership through color alone. A boundary node needs text and a distinct outline or shape.

React Flow supports nested groups, but Project groups should remain presentation only. Cross-Project edges are canonical Task relationships, not parent-child relationships in the graph library.

### Cycle-safe editing

Use two validation layers:

1. `isValidConnection` rejects self-links, duplicates, and cycles detectable in the loaded subgraph before submission.
2. Python validates the proposed mutation against the complete canonical repository and exact Task revision. Only this result may claim success.

The second layer is mandatory because a bounded client graph cannot see every cross-Project path. If Python rejects the edge, preserve the selected source and target, announce the safe reason, and refresh the exact Task dependency state. Never add an optimistic edge and call it saved before canonical readback.

## Accessibility requirements

### Keyboard and screen reader

- Put concise instructions before the map, outside React Flow's `application` region. Include a Skip map link to the Dependencies view.
- Keep nodes focusable and give each one a short name containing Task title, status, Project when external, prerequisite count, and dependent count.
- Do not put every edge in the tab order. Expose exact relationships in the Dependencies view and offer a node action that opens them. If selected edges remain focusable for deletion, cap that mode to the selected node's immediate edges.
- Enter on a node opens Task detail. A visible "Edit dependencies" action opens the same semantic editor used outside the map.
- Escape must leave selection or close a graph-owned popover without trapping focus. Tab must move out of the map.
- Use a polite application-owned live region outside the graph for accepted edits, rejected cycles, and scope changes. Do not announce pointer coordinates or every pan step.
- Run manual checks with VoiceOver and Safari on macOS, plus NVDA with Firefox or Chrome on Windows. Automated ARIA checks cannot prove that the hard-coded application role works well.

WAI-ARIA has no generic graph widget role. The [ARIA roles model](https://www.w3.org/TR/wai-aria-1.2/#roles_categorization) and [keyboard guidance](https://www.w3.org/WAI/ARIA/apg/practices/keyboard-interface/) put the interaction contract on the author. Mentat should not invent tree semantics for a directed acyclic graph with multiple parents.

### Zoom, focus, contrast, and motion

- Preserve browser zoom. The map's own zoom controls must not replace page zoom.
- At 400 percent browser zoom or a 320 CSS-pixel viewport, switch to the Dependencies view by default and keep the page free of two-dimensional overflow. This follows the [WCAG 2.2 reflow guidance](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html).
- When node focus triggers auto-pan, keep the focused node fully visible and outside sticky shell controls. Draw a persistent focus outline that survives Project color and selection state.
- Use `currentColor`, text labels, outlines, and system colors under `@media (forced-colors: active)`. Do not opt the map out of user colors. The [CSS Color Adjustment specification](https://www.w3.org/TR/css-color-adjust-1/) applies forced colors to SVG fill and stroke and explains the special handling of embedded SVG.
- Under `prefers-reduced-motion: reduce`, set edge `animated` to false, use zero-duration fit and focus movement, and disable layout transitions. The [Media Queries Level 5 specification](https://www.w3.org/TR/mediaqueries-5/#prefers-reduced-motion) defines `reduce` as a request to remove or replace nonessential motion.
- Give touch handles and graph controls a 44 by 44 CSS-pixel hit area where the layout allows it. React Flow supports tap-to-connect on touch when two handles are tapped in sequence. [Touch example](https://reactflow.dev/examples/interaction/touch-device)

### Mobile

The semantic editor is the mobile default. The optional map opens in a full-width, fixed-height panel with no body-level horizontal overflow. Pinch zoom and explicit controls stay inside that panel. Do not render a minimap on narrow screens. Cross-Project expansion should navigate to a filtered view rather than growing the current graph.

## SSR, hydration, CSP, and offline packaging

Implement the map as a Client Component under a server-rendered Project route. The server should render the semantic editor and the initial bounded graph projection. Use fixed node dimensions, fixed handle positions, and deterministic initial coordinates so server and client markup agree. Avoid `ssr: false` unless the React 19 hydration spike proves SSR unstable.

React Flow's official 12.11.5 tarball is [content-addressed by npm integrity](https://registry.npmjs.org/@xyflow/react/12.11.5). A read-only inspection of the official tarball found:

- a 251,058-byte compressed archive and 1,213,198 unpacked bytes;
- a 232,567-byte ESM entry before application bundling;
- local exported CSS, with no remote CSS import;
- no `eval` or `new Function` in the ESM entry;
- one production external URL used for the optional attribution link, not a runtime fetch.

This fits Mentat's current CSP without a new origin. React Flow uses inline transform and geometry styles, which the current `style-src 'unsafe-inline'` permits. If Mentat later removes that allowance, the package must be reviewed again. Bundle from the lockfile into the standalone Next.js output. Do not use a CDN.

The [Next.js CSP guide](https://nextjs.org/docs/app/guides/content-security-policy) confirms that production React and Next.js do not require `eval` by default and documents nonce handling. The graph must continue to work with `connect-src 'self'` and with the network disconnected.

## Auto-layout

React Flow deliberately has no layout engine. Its [layout overview](https://reactflow.dev/learn/layouting/layouting) compares Dagre, D3, and ELK.

Start with a source-owned deterministic layered layout:

1. Compute each visible Task's rank from its longest visible prerequisite path.
2. Put prerequisites before dependents, with a stable Task-ID tie-breaker.
3. Place boundary stubs in fixed outer ranks grouped by Project name and canonical ID.
4. Keep node dimensions fixed and route simple step edges.
5. Recompute only after the canonical dependency revision or visible scope changes.

This is enough to test whether the map helps. It also gives deterministic SSR, screenshots, and focus order.

If crossing and routing remain poor, evaluate [`@dagrejs/dagre` 3.1.1](https://www.npmjs.com/package/@dagrejs/dagre/v/3.1.1) in a separate decision. It is actively maintained, MIT licensed, 1,413,014 bytes unpacked, and has one runtime dependency. React Flow's own docs still warn about sub-flow layout when children connect outside their group, so Project grouping needs a specific test.

Do not add ELK in the first slice. [`elkjs` 0.12.0](https://www.npmjs.com/package/elkjs/v/0.12.0) is 8,046,232 bytes unpacked and licensed under `EPL-2.0 OR GPL-3.0-or-later`. ELK's layered algorithm supports compound graphs and cross-hierarchy edges, but its [official reference](https://eclipse.dev/elk/reference/algorithms/org-eclipse-elk-layered.html) exposes much more configuration and worker complexity than this first map needs.

Do not use a force layout. Continuous movement conflicts with deterministic rendering, reduced motion, stable focus, and a user's learned spatial position.

## License, maintenance, and security assessment

React Flow 12.11.5 is MIT licensed. Its direct package roots are `@xyflow/system`, `classcat`, and `zustand`. The current direct and immediate transitive packages reported by npm use MIT or ISC licenses. Dagre is also MIT. These licenses are compatible with Mentat's intended local packaging, provided required notices remain in distributed artifacts.

React Flow published multiple 12.x updates in 2026 and published the reviewed version six days before this note. Its repository security policy says 12.x receives full security updates and currently shows no published advisories. An [official GitHub Advisory API query](https://api.github.com/advisories?ecosystem=npm&affects=%40xyflow%2Freact) for `@xyflow/react` returned no matching advisory on 2026-08-31. This is a point-in-time result, not proof that the package or its dependencies are defect-free.

X6 is also active and MIT licensed, but it has a much larger distribution and a weaker documented accessibility contract. A separate AntV package named `@antv/x6-components`, which is not a dependency of the reviewed X6 core pair, had malicious versions published in July 2026. [GitHub Advisory GHSA-qcw9-7qh9-h2m3](https://github.com/advisories/GHSA-qcw9-7qh9-h2m3) This does not show that `@antv/x6` or `@antv/x6-react-shape` was compromised. It does justify exact version pinning and provenance checks for any AntV package.

Before approving React Flow in a later slice:

- inspect the exact lockfile diff and full transitive licenses;
- run the repository's dependency and secret checks;
- verify npm integrity and package provenance;
- confirm no install script or remote asset enters the release;
- record the built route's compressed JavaScript delta;
- keep the package behind the optional map route so the rest of Mentat does not pay its client cost.

## Verification plan for an implementation spike

### Pure and component tests

- Deterministic ranks and coordinates across repeated runs.
- Correct edge direction, dependency counts, stable labels, and cross-Project stubs.
- Explicit truncation at 50 Project Tasks, 50 boundary nodes, and 250 visual edges.
- Client preflight for self-links, duplicates, and visible cycles.
- Server rejection of a cycle that passes through unloaded Tasks.
- Revision conflict handling that preserves the attempted edit.
- Semantic editor parity for every graph add and remove action.
- React Testing Library checks for names, roles, focus return, live messages, and draft retention.

React Flow unit tests need mocked `ResizeObserver`, element dimensions, and SVG bounds, as documented in its [testing guide](https://reactflow.dev/learn/advanced-use/testing). Keep geometry logic in pure functions so most tests do not depend on those mocks.

### Browser and manual tests

- Keyboard entry, node selection, Task opening, dependency editing through the HTML path, zoom, fit, and clean exit from the map.
- VoiceOver and NVDA behavior in and around the `application` region.
- Pointer drag and touch tap-to-connect, followed by canonical server readback.
- Focus auto-pan with sticky shell controls.
- 200 and 400 percent browser zoom, 320 CSS-pixel width, mobile touch emulation, and no page-level overflow.
- Forced-colors screenshots and non-color state identification.
- Reduced-motion behavior with no edge, layout, or viewport animation.
- Reload and viewport restoration without hydration warnings.
- Offline packaged build under the existing CSP with no failed external request.
- Lighthouse's existing three desktop and three mobile runs, all categories at 100.

Use fixtures for 50 nodes with no edges, 50 nodes with 250 visible edges, 50 selected nodes plus 50 boundary stubs, and a canonical 2,048-Task repository whose graph response remains bounded. Record layout time, hydration time, interaction responsiveness, DOM element count, and route JavaScript delta. Do not rely on `onlyRenderVisibleElements` to rescue an unbounded payload.

## Concrete fallback

If React Flow fails packaging, accessibility, or performance gates, ship this instead:

1. Keep the complete dependency editor as semantic HTML.
2. Generate a deterministic, read-only inline SVG for the same bounded Project page.
3. Render Task cards as positioned HTML links or buttons above decorative `aria-hidden` SVG edges.
4. Provide Zoom in, Zoom out, Fit, and Reset as ordinary buttons only if the source-owned transform remains small and testable. Otherwise use a static fit-to-width overview.
5. Make every relationship available as text outside the SVG.
6. Do not implement pointer edge drawing, freeform node dragging, Canvas, or a custom ARIA graph widget.

This fallback preserves the useful part of the feature, seeing dependency shape, without duplicating a full graph interaction engine. Editing remains complete, accessible, deterministic, local, and testable.

## Final recommendation

Approve React Flow 12.11.5 for a time-boxed implementation spike, not an immediate production dependency. Pair it with the exact semantic dependency editor from day one. Use the existing 50-Task Project page as the main bound, add explicit boundary-node and edge caps, and leave full cycle authority in Python.

If the spike cannot make React Flow's `role="application"` behavior, route bundle, dense-edge case, and mobile interaction pass the stated gates, stop. Ship the HTML editor plus source-owned read-only SVG overview. Canvas is not an acceptable fallback.
