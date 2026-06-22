## Variant: Side inspector

### Design stance
Keep the queue dense and stable; move full task reading into a dedicated inspector surface.

### Key choices
- Layout: split pane with queue on the left, details on the right
- Typography: compact queue, larger reading surface in inspector
- Interaction: clicking a task swaps the selected detail state

### Trade-offs
- Strong at: scanability, future task actions, command-center feel
- Weak at: needs more layout space and a responsive fallback on small screens

### Best for
- Mentat as a dashboard where task details may later include archive/delete/edit/history actions
