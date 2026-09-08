# Beta QA batch 6 — theme, inspector, and Board

Owner-approved September 7, 2026. Base: `a920dc3` (locally verified batch 5).

## Scope and verification

- [Planning inputs and dependency-map controls do not follow the green theme](https://github.com/hazeion/agent-os/issues/216): shared semantic focus/accent
  tokens and readable, bounded map controls without removing keyboard focus.
- [Narrow task inspector buries editing and overlaps execution text](https://github.com/hazeion/agent-os/issues/217): selected identity/actions,
  usable editing width, wrapping metadata, discoverable Board overflow, normal
  planning summaries, and direct mobile access to the selected inspector.
- Theme changes integrate first. Inspector work may proceed in its component,
  but stylesheet edits wait for that integration. Keep mutation contracts and
  staged edit behavior unchanged. Verify desktop/mobile, keyboard/zoom, theme
  contracts, web checks/build, and two independent reviews.

## Evidence

- Theme correction uses shared focus/accent tokens and currentColor map SVGs.
  Production verified keyboard-visible green field/map focus, 32px map buttons,
  and 16px icons matching the foreground color.
- Desktop inspector measured about 461px at 1280x720. Task identity/Edit stayed
  visible while its own panel scrolled; a real completed Run's text and timestamp
  did not overlap. Estimate, Agent, tags, and dependency information were visible.
- Board uses one row with six stages, visible arrows, and keyboard navigation;
  Next scrolls the Board and End reveals the final stage without page overflow.
- Review corrected mobile visual/DOM order. Production caught and corrected
  Project navigation intrinsic overflow, a focused editor offscreen after resize,
  and the compact Back-to-Tasks/same-Task return path.
- Final production checks: Project navigation client/scroll widths both 127px;
  1024x768 selection focuses the inspector with Projects collapsed; 390x844
  retains a visible editor, draft and caret; 640x360 (200% equivalent reflow)
  retains the visible editor without horizontal overflow. Same-Task return
  focuses its heading and preserves the draft. The test draft was cancelled.
- Both independent final reviews were clean through `5494e8c`. Integrated
  lint/typecheck, all 346 web tests, and production build passed.
- Batch 6 is locally verified. Publication and cross-platform CI remain pending.
