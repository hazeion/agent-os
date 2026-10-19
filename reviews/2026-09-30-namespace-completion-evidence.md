# Immutable local namespace completion evidence

Status: implemented prerequisite for registered producing-Run output within
the approved controller. This is not canonical Run completion or registration.

The current fixed NamespaceWorker verifies one exact terminal packet, native
exit success, whole-scope local cleanup, deadline and immutable image readback,
then returns a mutable dictionary. Later output registration must not accept
that caller-editable dictionary, a Boolean, arbitrary text or a model-prose
path as producing evidence.

Retain one immutable private snapshot only after the existing success gates.
Bind it to the originally handed-off sealed query digest, optional selected
image digest, runtime-image digest and sealed-library selection. Preserve the
exact terminal text, bounded output-byte count and their digest. Issue an opaque
in-process completion witness only after the same original LinuxWorkerScope
has completed verified close and supplies its exact closed identity witness.
Require one original NamespaceWorker issuer and its retained success; copies,
modified returned dictionaries, wrong scopes, failed/partial/late outcomes,
missing handoff context and unverified closure cannot manufacture evidence.
The original scope records the exact handle at successful handoff; both terminal
consumption and witness issuance validate that identity. Cloning a handle before
or after issuance cannot consume its packet or mint a second issuer.

The witness preserves local terminal evidence after owned export descriptors
close. It carries no caller-selected Run ID, path, command, provider or authority.
Persistence/registration must separately bind current canonical Run/generation,
input manifest, scope receipt, provider settlement, grant/approval epoch and
terminal finalization, with exactly-once blob/metadata retention. Apply/review
still requires registered output and owner action. Keep the schema-41 source
guard and default producing-Run refusal unchanged; no route, CLI, database,
backup authority, capacity release or execution capability is introduced.

Test exact packet types and every existing failure gate, no witness before
verified close, copied/mutated metadata refusal, image/query binding and immutable
success after close. Use actual fixed scopes and unchanged stock Hermes with the
durable fake broker for source-bound success; no real provider or owner service.
Run related scope/namespace/image/broker tests, two independent reviews and
package verification before publishing a full PR. This component does not claim
complete runtime qualification or producing-Run/garage acceptance.

Both final independent reviews are clear after recording the exact original
handle on its scope, refusing copies before terminal consumption/issuance and
serializing singleton issuance under that scope's lock. All 79 actual Linux evidence/scope/namespace/broker/image
methods pass without skips, including unchanged stock Hermes/PIL/prepared image
through the durable fake broker and the five-root immutable public image.
Tests bind original query/image/runtime-image digests and library mode, reject
cloned issuers and copied witnesses, and preserve the snapshot after returned
dictionary/metadata edits. Five portable evidence methods pass; Windows passes
40 related methods with 25 Linux-only skips. The reviewed prerequisite CI repair
is carried forward; fresh web lint/typecheck and all 512 web tests pass. Bundle
and package checks pass. Four selected source/wheel/sdist/installed members match,
with three isolated installed imports. The standalone runtime was rebuilt and
restaged after its old package stage was detected; the final wheel explicitly
contains Next.js 16.3.6. No live provider or owner service was used.
