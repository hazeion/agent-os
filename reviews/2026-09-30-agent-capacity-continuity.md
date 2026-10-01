# Canonical Agent capacity continuity

Status: implementation within the approved controller's shared-capacity
requirement. This hardens existing Console and Task admission; it does not
complete Project admission or enable its guarded source.

Both final independent code reviews are clear after conservative historical
scope handling and race-fixture cleanup/evidence corrections. All 175 affected
repository/orchestration/continuity methods pass on Linux with no skips;
Windows passes the same group with two platform skips. Six new methods cover
the reproduced scope change, both Task/Console orderings, verified queue pause,
concurrent distinct qualified declarations, validated historical missing-Agent
occupancy and exact Retry refusal without a new Run or action receipt.
The affected group also found the inherited current-schema assertion still
expected 43; it now expects 44 and requires generation/call/scope tables.
Wheel/sdist inventory and integrity checks pass. Four exact
source/wheel/sdist/installed members match; two isolated installed imports and
the required canonical Agent/capacity arguments are verified.

## Finding and boundary

An actual OrchestrationService regression on the current stack retains an
unknown Run under qualified synthetic Codex scope A, changes the adapter's
declared private capacity scope to B, and sends from a second Conversation for
the same canonical Agent. The existing binding/scope-only count allows another
adapter submission. Both requests remain unknown, so this is a demonstrated
admission gap rather than successful runtime recovery. No real provider is used.

Every existing reservation must count the union of active Runs belonging to
the canonical Agent and the existing matching adapter scope/binding, with each
Run counted once. Preserve conservative legacy unbound Hermes occupancy.
Unknown Runs retain occupancy. A larger incoming scope ceiling can apply only
if every counted overlapping Run carries the same exact capacity scope,
including historical matching bindings with missing Agent identity;
missing or changed scope forces the new work to wait. Matching qualified Codex
scope retains its existing ceiling of two; the qualification rules stay in the
existing adapter boundary. A new private scope, changed binding, different
Project/Conversation or runtime identity cannot manufacture an Agent slot.

Perform the query and existing canonical reservation in the same guarded SQLite
write transaction. Apply it to initial Conversation Send, queued/Continue
admission, explicit Retry/Resume and Task dispatch. Capacity failure preserves
the existing blocked Turn or conflict result without adapter submission. Do not
rewrite earlier immutable Run capacity evidence, settle unknown work, cancel a
Run, release a slot on scope readback, or add a scheduler/lease sidecar.

This change adds no schema, browser/bridge/CLI field, provider call, qualification
grant or Project source exception. Exact Project authorization, immutable inputs,
work reservations, active-source backup, output provenance and production
admission remain separate required gates.

## Verification

Reproduce before fixing. Test changed and missing scopes, canonical Agent
binding continuity, qualified same-scope limit two and unrelated Agent/scope
independence. Exercise Task/Conversation cross-source rejection, queue release
and Retry paths, unknown occupancy and concurrent SQLite reservations. Retain
existing qualification/capacity tests and run affected repository/orchestration
groups on Windows and Linux. Obtain two independent reviews, fix/re-review,
verify packages and publish a full PR with the exact acceptance limits.
