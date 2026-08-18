# Mentat Architecture Pivot Notice

Read `MENTAT_MULTI_AGENT_PIVOT.md` before planning new architectural work. It describes the target architecture; `ARCHITECTURE.md` still describes much of the currently implemented system. Read `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md` to identify the completed, active, proposed, and provisional delivery slices.

`ARCHITECTURE.md` remains important for understanding current implementation contracts, safety boundaries, and behavior that must be preserved during migration. `MENTAT_MULTI_AGENT_PIVOT.md` defines the intended direction for the multi-agent orchestration pivot.

When the documents differ because of the migration, do not perform a wholesale rewrite. Preserve current behavior and introduce the smallest compatibility seam that advances the pivot.

The implementation plan is a roadmap, not authorization to begin every listed
slice. Use the active slice's review log for its approved scope, test strategy,
verification evidence, and resume point.
