# Mentat Operations implementation guide

Status: Superseded

The current frontend sequence is in:

- `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`
- `design/emerald-operations/IMPLEMENTATION_PLAN.md`

The Emerald Operations design is already complete in the static `public/`
interface. New UI work ports that established design into the Next.js app under
`web/`; it does not begin another redesign.

Keep `public/` available as a compatibility interface until the new app has
matching workflows, production packaging, and a tested rollback.
