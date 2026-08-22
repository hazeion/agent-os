# Mentat pivot guide

Mentat is moving from a Hermes dashboard to a local multi-agent operations
console. The change is gradual. The current Python app stays available while
the new Next.js interface and runtime adapters are added in small slices.

Read these files in order before planning architecture work:

1. [MENTAT_PIVOT_IMPLEMENTATION_PLAN.md](MENTAT_PIVOT_IMPLEMENTATION_PLAN.md)
   shows what is complete and what comes next.
2. [MENTAT_MULTI_AGENT_PIVOT.md](MENTAT_MULTI_AGENT_PIVOT.md) explains the
   target architecture.
3. [ARCHITECTURE.md](ARCHITECTURE.md) defines the safety rules that the current
   code enforces.
4. The active slice review log contains its approved scope and test evidence.

The roadmap is not permission to start a later slice. Finish the active slice
first and keep the Python app working until its replacement has matching
behavior, safe packaging, and a tested rollback.
