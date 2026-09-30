# Supported Project worker admission boundary

Status: proposed prerequisite contract for issues
[#239](https://github.com/hazeion/agent-os/issues/239) and
[#262](https://github.com/hazeion/agent-os/issues/262). This records the concrete
missing runtime boundary; it does not authorize a Hermes upgrade, an upstream
repository change, a replacement dispatcher or model work.

## Audited evidence

The selected candidate remains local original Hermes co-located with the Linux
Mentat host, as resolved in issue #237. At the initial host audit, the temporary
WSL installation reported Hermes v0.19.0 from a clean checkout of the owner's fork at
`1ce05d8fb1ae16c3d694d1f06003445edb632046`; that is not an official upstream
commit pin. The inspected source files matched that local commit. Its Kanban CLI exposes separate create and
attach operations, per-task runtime and retry limits. The current Mentat adapter
passes neither an immutable input set nor per-Task permitted operations or work
limits to creation. These are unsupported, rather than qualified capabilities.

Current upstream was separately pinned to
[`8cd3d8149ead2b86aad825a539b1efabf7781963`](https://github.com/NousResearch/hermes-agent/tree/8cd3d8149ead2b86aad825a539b1efabf7781963).
Its [worker dispatcher](https://github.com/NousResearch/hermes-agent/blob/8cd3d8149ead2b86aad825a539b1efabf7781963/hermes_cli/kanban_db_dispatch.py)
still builds a profile-scoped host CLI worker, enables configured hooks and
toolsets, and supplies its board/runtime context. Runtime timeout handling may
return a task to a retry phase. The
[strict-worker tracker](https://github.com/NousResearch/hermes-agent/issues/82591)
is open and marked for a maintainer decision; its design is not a shipped
capability. This audit neither adopts that issue's instructions nor changes it.

A credential-free Bubblewrap mount probe on WSL hid the owner's home and
Windows mounts. It did not run an Agent, exercise provider traffic or establish
a supported Hermes whole-worker API. A terminal-tool sandbox, profile toolset
or prompt cannot alone qualify the Agent loop and its descendants.

## Required supported operation

Preserve Hermes Kanban as the durable backend. Before Mentat may approve or
admit Project execution, Hermes must expose one fixed, versioned operation
that accepts an exact owner-authorized worker request. Mentat's browser and
Node layers never select commands, paths, provider credentials, runtime refs,
hooks, skills, plugins or MCP authority. Python resolves canonical IDs and
constructs the private bounded request from retained authority.

That operation must bind these facts together before a worker starts:

- a stable idempotency key and exact request digest, with changed-body conflict;
- canonical Project/Task scope and immutable input bytes/digests, or the
  separately authorized proposal-only Project input;
- the fixed operation set and exact qualified runtime/configuration revision;
- a finite attempt reservation, wall deadline and enforceable work ceiling;
- fixed expected output slots, types and byte/count limits;
- an exact run-generation identity, owned execution scope and readback receipt.

File preparation may create immutable content-addressed bytes before the
transaction, but Hermes publishes no executable claim until every selected
byte verifies and its own retention references, card/run admission, policy and
idempotency receipt commit together. Mentat's SQLite reservation and Hermes's
Kanban admission are separate atomic boundaries, joined by the exact request
digest and supported idempotent readback; there is no cross-database atomicity.
A lost response retains Mentat's unresolved reservation without a second
submission. Failure cannot leave an executable card with partial inputs.
The worker may not claim, complete, requeue, change policy or dispatch its own
successor through a general Kanban tool.

## Whole-worker qualification

The Agent loop, file/terminal tools and every descendant execute inside one
verified per-Run Linux boundary. It exposes only the selected inputs and
controlled outputs, with no host home, Windows mount, unrelated Project,
credential file, Kanban database, Docker socket or host command bridge.
Unknown setup, ineffective limits and unsupported platforms fail before bytes
or authority are delivered; no ordinary local-worker fallback is permitted.

Provider credentials remain in a trusted inference broker outside the worker.
The worker gets only a fixed, bounded, per-Run inference capability whose model,
endpoint, headers and credential source are host-owned. Public research uses a
separate qualified public-only network broker and the exact reviewed public
brief; it receives no private files/context/notes. Private synthesis/proposal
workers have no public web or private-network capability. Denied hooks,
skills/plugins/MCP/provider-native tools must not initialize or connect.

Public retrieval is a fixed broker operation with a versioned egress policy,
not a generic URL or HTTP proxy. For page reads, accept HTTPS/443 only, fixed
GET semantics and broker-owned credential-free headers; deny caller cookies,
headers, authentication, alternate methods and proxy settings. Resolve and
validate every address as public, denying loopback/private/link-local,
multicast, tailnet and cloud metadata destinations. Pin the validated address
while checking TLS for the original hostname; revalidate every redirect with
at most three hops. Bound each request to ten seconds and two MiB of decoded
response bytes, including decompression, then parse only inside a replaceable
credential-free worker. Fixed search-provider calls keep credentials outside
the worker and receive only the reviewed public query. Every search/read
consumes the approved work reservation. Bind this policy revision to
qualification and test hostile DNS changes, mixed public/private answers,
redirects, alternative IP encodings, metadata endpoints and slow/compressed
responses. Reuse the existing pinned-HTTPS policy where its contracts apply;
do not weaken it to make research succeed.

The qualifier must define the actual meaning of a work unit and enforce the
approved ceiling across inference attempts/retries and all descendants.
Iteration count or reported usage alone cannot establish a hard token or money
cap. Unsupported spending promises remain unavailable. A parent/controller
watchdog owns the full execution scope; Stop verifies the same generation's
whole-scope termination before claiming success or admitting a replacement.
It also fences/revokes that generation's inference and research broker
capabilities. Late calls/results cannot acquire authority. Local worker death
does not prove that an already submitted provider request stopped; unresolved
provider outcomes and their budget reservations remain retained until supported
reconciliation establishes the result. Report local and external stop evidence
separately instead of claiming full Stop from process termination alone.

After any ambiguous submission, timeout, provider failure or crash, preserve
the exact Run and frozen inputs as checking/unknown until supported readback
resolves it. There is no automatic requeue or resubmission. `max_attempts` is
a ceiling, not authorization for another attempt. Every broker inference
submission has a distinct durable call identity; a repeated call identity
returns its known outcome or unresolved state without another provider request.
The trusted controller/broker owns that identity and binds it to the exact Run
generation and request digest; changed bodies conflict. Workers and SDK retry
loops cannot mint a fresh identity for an unresolved request. An unresolved
submission fences further inference for that Run until a definitive outcome
or supported reconciliation is recorded.
An explicit owner-authorized retry creates another exact
Run and fresh reservation; it cannot reuse stale grants or authorization.

## Mentat admission and results

Only a host-qualified exact runtime build may advertise the new fixed
capability. Qualification records no credential values and expires on build,
binding, broker, policy or host-boundary changes. A normal capability inventory
or version string is not qualification.

Mentat reserves the canonical Run, exact Task or Project input receipt,
approval/checkpoint and budget debit in one guarded transaction before the
adapter call. Source validation, retention, backup, Run attention and owner
Inbox must all support that exact receipt before the proposal insert guard is
replaced. The source cannot be borrowed from a Console Run or model text.

The trusted controller freezes and registers only the expected bounded output
set from the Run-owned boundary after verified success/finalization. Missing,
extra, malformed, replaced or partial output is quarantined as review evidence
and remains ineligible for proposal Apply, final promotion or downstream input.
Quarantine retains bounded sanitized failure metadata and only file bytes
permitted by the existing validated attachment boundary; it grants no arbitrary
file import or raw provider-payload retention.
Registration,
proposal parsing, exact owner Apply, final deliverable promotion and owner
acceptance remain distinct operations. The Agent cannot approve its own output.

## Implementation decision and verification

This boundary requires work beyond the currently supported Hermes adapter.
Extending the original Hermes repository needs an explicit scope decision;
switching durable backends needs a separately approved architecture amendment.
Do not add more execution UI or remove existing guards as a substitute.

If the extension is selected, first pin the original repository and review a
minimal supported worker protocol there. Then implement the broker and owned
worker scope, atomic exact admission/readback, bounded work/time and verified
Stop; qualify them with hostile inputs and crash windows on the actual host.
Only then wire Mentat approval/admission and generated-output registration.

Required tests cover complete input binding, unrelated-file/credential/network
denial, denied tool initialization, scope ownership and descendants, attempt
and work ceilings, timeout/cancel/crash cleanup, duplicate/changing requests,
lost-response reconciliation, revocation races, restored authority, missing or
extra outputs and no hidden retries. Two independent reviewers must inspect
each major implementation slice. Live provider tests require operator-supplied
configuration and must retain secret-free evidence.

## Review evidence

Two independent source/contract reviews found transaction-ownership, retry,
broker Stop/call identity, partial-output and public-egress ambiguities. Those
were corrected; both re-reviews report no remaining actionable findings.
The audit read public code and fixed help/version output only. It did not read
provider secrets, change Hermes configuration/storage, update the runtime or
run a model. This record remains a proposed scope prerequisite while the
operator chooses whether to extend the original Hermes repository or approve
a different runtime architecture.

After this review, the owner selected migration to the updated official Hermes
agent instead of developing the fork. Official stable `v2026.9.24` (0.21.5,
`f97608f178d1ffeca59860195ab7da295f7c8e5f`) and current main were audited
separately. Shipped Subagent Lifecycle, `ctx.llm`, provider-plugin, run-API and
egress-proxy seams are integration opportunities, so they must not be described
as absent. Their current scope does not alone qualify the exact Project worker
contract above. [Stock compatibility and backed-up activation](2026-09-29-official-hermes-compatibility.md)
are now verified. The [reviewed controller proposal](2026-09-29-official-hermes-project-controller.md)
maps the supported seams to an unchanged official runtime and identifies the
specific execution-ownership amendment requiring an owner decision. This
prerequisite remains the safety floor; no production Project dispatch is enabled.
