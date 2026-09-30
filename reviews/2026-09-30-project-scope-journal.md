# Durable Project scope ownership

Status: implementation contract within the owner-approved
[Mentat controller direction](2026-09-29-official-hermes-project-controller.md).
Production admission, provider qualification and dispatch remain closed.

Both independent contract reviews are clear after exact transition/identity,
closure-witness and worst-case metadata-accounting corrections. Implementation
includes private planned/owned/closed witnesses and schema-44 storage, exact
migration, fixed accounting and archival/restore/schema-5 integration. All 69
affected methods pass on Linux without skips. The namespace/synthetic-broker
group executes all 44 methods successfully across its initial run and explicit
two-method pinned-stock rerun. The 50-method portable compatibility group passes.
All 14 final journal methods also pass on Linux after predecessor compatibility
corrections. The private-unit Windows group passes 52 methods with its one
POSIX-only method skipped. Both final independent code reviews are clear after
shared-budget, concurrency, tamper, unknown/closure and owned-thread cleanup
regressions. The second reviewer found three predecessor-schema allowlist gaps;
Vercel, Conversation and Agent Registry now explicitly retain schema 43, along
with Task/Project/Run validation. Exact populated schema-43 private capture,
validation and normal upgrade to 44 pass, preserving the generation graph; the
second reviewer independently reran that regression. Refreshed wheel/sdist
inventories and ten isolated installed module comparisons pass; the isolated
installation migrates an empty database to exact schema 44 and validates the
empty scope graph. Production dispatch/source guards are unchanged; no release
acceptance is claimed.

## Problem and scope

Schema 43 binds controller generations, inputs, policy, epoch and inference
debits, but records no process-scope launch identity. LinuxWorkerScope retains
systemd invocation, pinned cgroup and process identity only in memory. A future
controller cannot infer a second launch or successful Stop after restart from
an empty in-memory map.

Add private SQLite scope bookkeeping beneath one exact existing generation.
It grants no Run, shared capacity, namespace handoff, broker, provider, output or
owner-approval authority. This slice does not advertise a recovery command or
rehydrate kernel handles. Complete admission and kernel reconciliation remain
required before enabling the production controller.

## Receipt and transitions

Schema 44 adds one bounded scope record per Run/generation, joined by an exact
foreign key to the immutable schema-43 generation. At most 128 records share
the existing private metadata budget and retained graph. Before a future launch,
prepare the fixed randomly named unit, Linux boot identity, owner UID, exact
policy/epoch and a one-time host claim token. Persist only the token hash; expose
the token once, omit it from repr and never recover it from a duplicate request.
Neither a database row nor a supplied identity string proves kernel ownership.

Allowed states are prepared, starting, owned, unknown, stopped and cancelled.
The complete permitted transition graph is prepared to starting or cancelled,
starting to owned or unknown, owned to unknown or stopped, and unknown to
stopped. Starting may go directly to stopped only with the same exact kernel
closure witness required below. Terminal rows are immutable. No edge returns
to prepared/starting or authorizes another launch.
Only the original token may change the exact record/revision. Identical duplicate
preparation returns retained metadata without another token; changed intent
conflicts. Commit starting before any future external launch. Starting and
unknown never authorize a second launch. Owned freezes one private identity
snapshot: the fixed unit/boot/UID plus invocation, cgroup device/inode and
launcher PID/start ticks. Cgroup paths are derived from fixed rules and are not
caller-supplied stored paths. Bind the snapshot digest to the immutable receipt.
Prepared, cancelled and initial starting rows have no observed kernel identity.
Owned requires a complete snapshot. Unknown retains that exact snapshot if one
was already bound; otherwise it remains absent. It never clears, substitutes or
learns a different live identity. A terminal closure witness may bind previously
unrecorded historical identity only by matching the immutable planned scope.
All later witnesses must exactly match an already frozen snapshot.

Each transition binds its expected revision and complete normalized intent.
An exact repeat of the immediately retained transition returns its result
without another revision or capability; changed or older transitions conflict.
Prepared cancellation cannot be used after starting. Repeated requests must
never become a second external-action instruction.

Cancel only before starting. Stop is terminal local evidence, independent from
an inference call's possibly unknown external outcome. No method settles,
refunds or retries that call. Record unknown on ambiguous startup or identity
evidence. A new epoch, revoked grant or changed input/binding fences preparation,
launch and attachment. Original-token cleanup may retain truthful historical
cancel/Stop evidence without granting stale execution authority.

The storage layer validates bounded identities and monotonic transitions;
it must not claim that caller metadata alone proves a live or empty scope.
The stopped transition requires an opaque closure witness issued by the exact
held LinuxWorkerScope only after verified local emptiness/close. Bind its fixed
unit, boot, UID, invocation and cgroup/process identity to this claim; reject a
raw identity dictionary, Boolean or token alone. Retained witness metadata and
its digest are historical evidence, not an independent live-kernel probe.
Failed starts without that witness remain unknown. The future controller must
derive attachment and Stop evidence from the exact held kernel generation,
not browser text or model prose.
This slice contains no process launcher, signal operation or generic unit API.

Loss of the original token after restart cannot reissue launch authority or
silently release the receipt. Production recovery needs a separately reviewed,
authenticated kernel-reconciliation path for the exact immutable identity.
It is an explicit remaining gate, not token replay or a promise of this slice.

## Consistency and recovery limits

Every mutation runs within the guarded private transaction and its own
savepoint. Exact schema-43 source preflight must precede schema-44 DDL; failure
rolls back the schema and migration receipt. Validate scope identity/digests,
generation/input/policy/epoch references, token hashes, revisions, timestamps
and state-dependent fields on every graph read and metadata accounting path.
Include schema objects in Run-reference/schema inventories and both packages.
Preparation precharges the largest legal owned/unknown/terminal representation,
including its closure witness, under the existing metadata ceiling. Later
attachment or cleanup must not depend on headroom left by unrelated owner
writes. Keep that fixed charge through terminal state; never increase the
global ceiling or silently omit retained evidence to make a mutation fit.

Preserve schema-41 proposal insertion guards and default live Run/Inbox refusal.
The existing dormant proposal archival allowance may retain prepared, cancelled
or closure-witness-bound stopped bookkeeping only; starting, owned and unknown refuse archival
capture until the full active-source backup/reconciliation contract exists.
Restore preserves terminal evidence and rotates authority; it never reissues a
claim token, resets a spent inference debit, starts work or reconstructs a PID.
Compatible schema-5 export omits this authority and leaves the source unchanged.

An unresolved active receipt remains owned recovery evidence in SQLite, not a
successful backup or live-controller qualification. Supporting capture/restore
of active production scopes is an explicit remaining admission gate. Ordinary
operator roots retain empty scope tables while Project dispatch is unavailable.

## Verification

Use disposable historical proposal fixtures with the source guard restored;
never invoke a provider or represent the fixtures as admitted Runs. Test exact
migration drift/rollback, duplicate and changed-body preparation, concurrent
claims, token loss/no reacquisition, stale revisions, no relaunch after unknown,
identity/digest tampering, monotonic terminal behavior, grant/input/epoch fencing,
late cleanup and preserved unknown inference outcomes. Verify private metadata
precharge/headroom invariance and ceilings, prepared/terminal backup round trips, active archival refusal, restore
fencing and schema-5 omission. Add actual Linux scope-identity evidence only if
the existing fixed scope helper can supply it without widening authority.
Obtain two independent contract/code reviews, fix/re-review and publish a full
PR after proportional local/Linux and artifact checks.
