# Milestone 2 adversarial review findings

Status: in progress. The review begins only after the complete Milestone 2
contract set was drafted and reconciled to the same upstream baseline.

## Findings closed so far

1. **Runs inline images accepted an inherited free-form `detail` value.**
   This weakened the bounded-input claim. Hermes PR #68202 now accepts only
   `low`, `high`, or `auto`, rejects other values before run allocation, and
   passes 257 focused Runs/session/API tests.
2. **Exact continuation inherited optional API authentication.** A no-key
   API-server instance could otherwise issue a descriptor and accept a
   descriptor-based run. Hermes PR #68177 now requires a configured bearer key
   for both paths and advertises continuation as unavailable without one. Its
   focused Runs/session suite passes 58 tests after the fix.

Both changes remain proposed upstream only. Mentat keeps each remote control
disabled until the reviewed contract is merged, released, advertised by the
installed runtime, and verified over the authenticated transport.
