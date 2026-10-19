# Durable scope receipts in synthetic broker qualification

Status: implemented approved-controller qualification integration; production stays closed.

The existing broker used private archival validation. That correctly rejects
starting/owned/unknown scope receipts, but also prevented combining the broker
with a scope journal committed before launch. Do not weaken that archive rule
or retrofit a prepared record after execution.

Use a distinct private qualification validator for the exact existing dormant
reserved proposal Run and schema-42/43 source graph, plus complete historical
schema-44 scope validation. Normal validation/getters/attention/Inbox, source
SQL guards and private archival eligibility remain unchanged. The broker still
accepts only its exact synthetic backend and fixed fake model/provider; this
private consistency mode grants no admitted Run or producing-output authority.

Every real Linux broker requires an exact committed owned scope receipt for its
Run/generation. Read the original scope's current opaque owned witness and
compare its complete plan/kernel identity to the frozen receipt, under the
existing broker/private/scope lock order. Recheck current input/grant/epoch,
policy/limits and the entire exact scope row before debit, synthetic acceptance
and cached-result replay. Missing receipts, prepared/starting/unknown/stopped,
changed generation/revision/identity or restoration refuse. No OS-only or
synthetic fallback may be chosen by missing real bookkeeping. The explicit
type-exact SyntheticScope unit fixture remains separate and cannot override a
recorded real scope.

Real disposable fixtures commit prepare/starting before start_inert, then commit
the original owned witness before constructing the broker. After Stop/verified
close, only the original closed witness settles the scope receipt. Lost tokens
remain lost; no automatic relaunch or replay is introduced. The canonical Run
remains reserved. Owned/unknown archival capture still refuses; settled scope
history remains eligible through the existing exact archive gate.

Test active owned qualification with default/archive rejection, missing and
changed scope receipt refusal before debit/backend/cache reply, synthetic
override denial, generation/kernel/epoch/limit mismatch, durable prelaunch
ordering, ambiguous commit boundaries and no postlaunch preparation. Exercise
actual unchanged Hermes/native image via the durable fake broker with scope
bookkeeping attached before launch, and retain existing Stop/input/restore tests.
Obtain two independent code reviews and package verification before full PR.

The reviewed next milestone remains complete canonical proposal lifecycle,
active-source backup/recovery, precharged durable output/blob registration and
owner intake/Apply. This integration is necessary qualification infrastructure,
not a smaller replacement for that outcome or live provider qualification.

The final actual Linux group passes all 123 methods without skips, including
prelaunch scope receipts in unchanged stock Hermes/native-image execution and
the source/Scope/call journal/archive contracts. Windows passes 69 related
methods with nine Linux-only skips. Five additional actual Linux methods prove
owned qualification while default/archive/backup remain closed, prelaunch
starting commit readback, missing/foreign receipt refusal, changed state and
epoch fencing before debit or cached replay, and synthetic override denial.
Both independent code reviews are clear. Fresh wheel and sdist pass the public
artifact inventory and RECORD verification. Four authority modules match byte
for byte across source, wheel, sdist and isolated installed tree, and all four
import from that installed tree. The packaged Next runtime is 16.3.6. No live
provider submission, production enablement or canonical proposal completion
is claimed.
