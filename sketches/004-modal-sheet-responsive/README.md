## Variant: Responsive modal / sheet

### Design stance
Keep Variant B as one interaction model, but let its physical form adapt by device: centered modal on desktop, bottom sheet on mobile.

### Key choices
- Layout: same compact queue in both modes
- Interaction: click/tap task to open detail overlay
- Responsive behavior: desktop uses a centered modal; mobile uses a bottom sheet with a drag-handle visual cue

### Trade-offs
- Strong at: mobile-first clarity, simple mental model, low disruption to current Mentat layout
- Weak at: still less efficient than a persistent inspector for rapid comparison across many tasks

### Best for
- Mentat if we want a clean near-term task detail UX that respects mobile-first thinking without giving up desktop polish
