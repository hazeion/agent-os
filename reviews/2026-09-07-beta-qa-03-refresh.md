# Beta QA batch 3 — planner refresh

Owner-approved September 7, 2026. Base: `8416c1a` (locally verified batch 2).

## Scope and verification

- [Saving task integrations leaves execution and delegation loading forever](https://github.com/hazeion/agent-os/issues/214).
- [Task deletion and recurring completion leave stale task lists and search results](https://github.com/hazeion/agent-os/issues/213).
- One implementation owner repairs guarded same-Task projection refresh, then
  list/search invalidation after deletion, recurrence, and rename. Preserve
  bounded pages, current filters, explicit navigation, and stale-response guards.
- Interaction regressions cover same-ID mutation readbacks, out-of-order
  responses, recurrence independently, deleted URL targets and search results.
  Verify production UI, web checks/build, and two independent read-only reviews.

## Evidence

- Baseline production UI: a valid reminder save reports success while both
  execution and delegation remain loading; a verified disposable Task deletion
  leaves one ghost card; daily recurrence completion leaves one occurrence
  visible until Project reselection exposes the durable successor.
- Renaming a Project updates its heading but leaves the old title in the
  already-visible search result for an unchanged matching query.
- Ordinary Save details also stranded execution at its prior revision. Clicking
  an already-selected Task clears details without rerunning its keyed effect,
  leaving Loading details. These belong to the same invalidation correction.
- Independent review found four new invalidation/pagination races. They were
  corrected with same-Project no-op selection, pagination busy reset and
  serialization, and retaining pending details on projection-only retry.
  Repeated Task selection and explicit search navigation preserve the inspector.
- Review also caught two malformed separator bytes. They were repaired to UTF-8;
  the final production build passed. Both final independent reviews were clean.
- Integrated web lint/typecheck and 321 tests passed. Python 3.13 planning,
  bridge, and density checks: 68 passed. Independent reviewers additionally
  passed 62 UI/search tests and 11 Python planning tests each.
- Production acceptance: reminder save settles both status panels; same-Task
  selection and ordinary editing retain usable details; deleting a Task opened
  from search clears its card, search hit, and URL target without reload.
- Completing the next daily occurrence immediately shows the third occurrence.
  Search distinguishes all occurrences by Project, stage, and due date.
  Project rename updates the result for the unchanged matching query.
- Batch 3 is locally verified. Publication and cross-platform CI remain pending.
