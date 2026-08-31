# Mentat domain documentation

Mentat is a single-context repository with an established documentation set.
Engineering skills must use the current authority before introducing new
terms, plans, or architectural decisions.

## Required starting documents

For architectural or product planning, read:

- `AGENTS.md`
- `ARCHITECTURE.md`
- `IMPLEMENTATION_PLAN.md`
- `CONTEXT.md`

For Next.js web design or implementation, also read:

- `MENTAT_WEB_DESIGN.md`

The canonical web guide contains its own conditional-reference table. A linked
file is not automatically a required read. Do not preload older design files,
the Python compatibility interface, or broad review history. Consult them only
when the canonical guide identifies a gap, a parity question requires the
implemented behavior, or a specific contract needs verification.

## Existing authority

Topic-specific Mentat documents remain authoritative for their areas. Relevant
review records under `reviews/` hold detailed implementation and verification
evidence. Use the narrowest relevant record rather than loading the whole
review history.

If documents conflict:

1. `ARCHITECTURE.md` and the repository safety boundaries govern implemented
   authority and security.
2. The active implementation plan governs slice sequencing and the resume
   point.
3. `MENTAT_WEB_DESIGN.md` governs the current Next.js visual experience.
4. GitHub issues, pull requests, and repository history provide historical
   rationale but do not override current authority.

## Supplemental domain documents

- `CONTEXT.md` may hold a concise shared glossary and domain relationships.
- `docs/adr/` may hold new durable architectural decisions.
- Create these lazily when domain modeling identifies a real gap.
- They supplement existing Mentat documentation and must not silently
  duplicate or override it.

## Vocabulary

Use Mentat's established terms, including Agent, RuntimeConfig,
ProviderConnection, Task, Run, AgentEvent, Capability, Policy, Local Bridge,
and runtime adapter. Runtime-owned profiles, sessions, threads, and model IDs
are external references, not Mentat identities.

If a proposed decision conflicts with current architecture, the pivot, the
canonical web guide, or an applicable review decision, surface the conflict
explicitly before changing direction.
