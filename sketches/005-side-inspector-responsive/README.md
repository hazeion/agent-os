## Variant: Adaptive side inspector

### Design stance
Preserve Variant A's desktop command-center advantage, but avoid forcing a side-by-side layout on mobile.

### Key choices
- Desktop layout: task queue on the left, persistent selected-task inspector on the right
- Mobile fallback: one-column task queue; tapping a task drills into a full task-detail screen with a Back to Queue control
- Interaction: same selected-task state powers both layouts

### Trade-offs
- Strong at: desktop scanning, future task actions, maintaining the inspector mental model across devices
- Weak at: mobile fallback is a little more structurally involved than the refined B sheet/modal pattern

### Best for
- Mentat if the desktop command-center pattern matters most, while still having a sane mobile fallback instead of a cramped split pane

### Implementation note
This should not be difficult to switch later if the production version uses one task-detail component/state model and changes placement with responsive layout only. It becomes difficult only if desktop and mobile are built as separate duplicated flows.
