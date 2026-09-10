# Beta QA batch 5 — everyday planning controls

Owner-approved September 7, 2026. Base: `1ca927c` (locally verified batch 4).

## Scope and verification

- [Checklist items cannot be named or edited](https://github.com/hazeion/agent-os/issues/215): editable validated titles,
  stable IDs/order, and normal-inspector completion through exact Task mutation.
- [Someday view has no UI action to defer or return Tasks](https://github.com/hazeion/agent-os/issues/221): explicit defer/return
  with guidance, keeping workflow stage distinct. Scheduled-block editing is excluded.
- [Reminder summaries display raw UTC instead of the entered local time](https://github.com/hazeion/agent-os/issues/218): friendly
  zoned display, unchanged-instant preservation, DST/invalid-time round trips.
- One implementation owner works in the above order. Regressions cover named
  checklist persistence/order/validation, defer/return without dispatch, and
  reminder folds/gaps/zone context. Preserve prior refresh and recovery guards.
  Verify production UI, relevant Python/web checks and two independent reviews.

## Evidence

- Baseline reminder entered at 09:00 displayed raw 16:00Z. Its formatter combined
  incompatible Intl options and fell back to raw text. Baseline checklist rows
  exposed placeholder text without editable title controls.
- Both independent final reviews of `8e49c91` were clean. Each independently
  passed all 66 planner/time tests, including exact autumn-fold/subsecond
  preservation, invalid spring-gap refusal, and imported-zone edits.
- Integrated web lint/typecheck, 336 tests and production build passed. Existing
  Python planning validation/model checks: 21 passed.
- Production UI: saved checklist titles were renamed; Add focused the new title;
  blank titles disabled Save; named completion worked outside the editor.
- Move to Someday made the Task visible there. Return removed it from that view,
  retained Inbox stage and checklist completion, and showed useful empty guidance.
- Reminder summary showed Disabled and Sep 12, 2026, 9:01 AM PDT after an Enabled
  toggle. The exact DOM timestamp from canonical readback was unchanged.
- Batch 5 is locally verified. Publication and cross-platform CI remain pending.
