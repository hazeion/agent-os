## Variant: Modal focus

### Design stance
Keep the existing queue almost unchanged and open full task details only when needed.

### Key choices
- Layout: same compact queue, temporary overlay for deep reading
- Typography: reading-focused dialog with larger title and long-form body text
- Interaction: click card, read, close

### Trade-offs
- Strong at: minimal disruption to the current layout, clear focus, straightforward implementation
- Weak at: repeated open/close can feel slower for scanning several tasks in a row

### Best for
- A first-pass Mentat solution if we want a clean upgrade without redesigning the whole Projects / Tasks view
