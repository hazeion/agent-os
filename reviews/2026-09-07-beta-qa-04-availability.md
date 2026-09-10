# Beta QA batch 4 — availability and Conversation revision handling

Owner-approved September 7, 2026. Base: `833c902` (locally verified batch 3).

## Scope and verification

- [Delegation offers an unhelpful dead end and disables unrelated planning controls](https://github.com/hazeion/agent-os/issues/219): bounded read-only discovery,
  fixed safe unavailable reasons, useful setup/recheck guidance, and independent
  loading state. Actual delegation keeps its existing confirmation/receipt guards.
- [Applying Conversation planning context after restore requires a second Apply](https://github.com/hazeion/agent-os/issues/220): refresh stale cached revisions
  before enabling Apply, retain staged choices, and preserve true conflicts.
- Independent Task and Conversation implementation owners. Regression tests
  cover late success/error, task/revision/navigation changes, deadline limits,
  restore then one Apply, and genuine concurrent conflicts. Production UI plus
  appropriate Python/web checks and two independent reviews precede acceptance.

## Evidence

- Production baseline reproduced the restore sequence and first-Apply conflict
  without another editor. The staged choice remained, but a second Apply was
  required. The regression also reproduces revision 1 being sent after revision 4.
- Production baseline delegation discovery disables unrelated Project navigation
  while displaying Checking delegation options. Source inspection found read
  phases with longer deadlines than the public caller.
- Initial combined web lint/typecheck, 330 tests, and production build passed;
  97 Python delegation/bridge/Kanban/planning tests passed.
- Production local discovery keeps Project navigation and Edit details enabled
  while checking. The unavailable installation then shows a specific missing-
  Hermes explanation, setup guide, and explicit Recheck delegation options.
- Production rename/archive/restore followed by one Apply succeeds, retaining
  an unsent draft and changing no Task or Run.
- Review identified remote multi-request/inactivity timeout gaps and missing
  capability being classified as connection failure. `2a41703` adds one optional
  absolute GET deadline across all nested remote discovery calls, exact socket
  shutdown for header/body/TLS stalls, and two bounded DNS-only daemon slots.
  Ordinary clients and mutation transport retain their existing behavior.
- Healthy remote Hermes without Kanban now reports missing capability rather
  than a connection fault. Positive, capability-negative, trickle, TLS, DNS,
  and no-POST regressions use the actual client/adapter boundary.
- Follow-up Python verification: 76 tests passed. Both final independent
  reviews were clean; each passed 20 targeted server/deadline tests, and one
  additionally verified real TLS handshake interruption and peer socket closure.
- The new helper is included in both package inventories. Batch 4 is locally
  verified; publication, full artifact verification, and cross-platform CI remain pending.
