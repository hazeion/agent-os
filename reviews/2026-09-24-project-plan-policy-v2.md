# Policy-bearing Project plan preparation

Status: reviewed design for [approved plans and scoped handoffs](https://github.com/hazeion/agent-os/issues/239)
and [exact Task admission](https://github.com/hazeion/agent-os/issues/262).
No Project execution, owner execution approval, or runtime qualification is
claimed by this design or by a saved plan.

## Why the next format is needed

Schema-33 format-1 plans freeze Task/Agent/input identities, graph,
checkpoint segments and requested limits. They do not freeze the operations
an Agent may perform or the conditions under which one Task may use another
Task's output. Format-1 versions remain permanently ineligible for execution
approval; an out-of-band mutable policy cannot repair an old version.

As checked September 24, 2026, current upstream Hermes Kanban describes a
worker as a full OS process and says attached files are handed to a worker as
absolute paths with full file/terminal access. The Kanban CLI has bounded
runtime and idempotency fields, but no per-card allowed-operation policy.
Hermes' Docker terminal backend can isolate terminal/file/code commands, yet
its standard persistent container is shared by a profile across sessions and
explicitly forwarded secrets or credential files remain available there.
Neither that profile configuration nor a prompt is an exact per-Task tool,
file, network or output authority. Mentat's fixed Kanban adapter presently
selects scratch/worktree and idempotency but does not pass a per-Task tool or
work ceiling. No actual Linux Hermes build and provider is qualified.

Primary sources: [Kanban reference](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/kanban.md),
[Kanban CLI](https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/kanban.py),
[Hermes security guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/security.md),
[worker lanes](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/kanban-worker-lanes.md),
and the upstream [strict-worker boundary tracker](https://github.com/NousResearch/hermes-agent/issues/82591).
The tracker is a proposal, not a shipped qualification.

## Format-2 immutable intent

Add format 2 to the existing immutable `mentat_plan_versions` authority, not a
sidecar that can be edited after publication. Preserve every format-1 row,
digest, history reference and read projection exactly. A format-2 version
binds the existing Project/context scope, Project revision and 1–32 exact
Task/Agent/input nodes. It adds one policy block to the canonical content
whose bytes are covered by the plan version's content digest.

Each node names a sorted, nonempty subset of fixed *requested* operations:
`read_selected_inputs`, `read_public_web`, `write_registered_artifacts`, and
`ask_owner`. These are runtime-neutral owner-review categories, not grants.
They do not imply arbitrary filesystem access, private network access,
external messages, purchases, credential use or shell authority. A runtime
qualifier must later map each category to exact, enforceable adapter methods;
unsupported mappings fail approval. The owner editor calls them requested
operations until that proof exists. `ask_owner` means one fixed, bounded,
source-bound Mentat question/Inbox capability, never arbitrary email, chat or
webhook delivery. `write_registered_artifacts` means only the run-owned export
and registered-output boundary, not a general file-write tool.

Public web research and private Project data are separated by default.
`read_public_web` may not coexist on one node/Run with
`read_selected_inputs`, materialized private context or Task notes, or a
conditional transfer of private outputs. Existing Task-input publication still
requires an active Project context grant, but that grant is an identity and
staleness check, not permission to materialize its private context in a web
worker. The public-research Task receives only a bounded public brief/query:
the exact immutable Task-input `instructions` reviewed by the owner. Its
selected input-file set must be empty. Format-2 publication freezes that
Task-input version ID and the UTF-8 digest of its reviewed instructions in the
node policy, and rejects any mismatch. Execution approval and Run admission
recheck both against the published plan. The web adapter cannot quietly
prepend any other hidden prompt text. Its admission receipt binds the same
brief identity and digest and proves no private context, notes, selected files,
credentials, or other Project outputs were mounted or injected despite the
stored grant reference. A later synthesis/layout Task may receive the
floorplan, goals and exact registered research versions, but
has no outbound web operation. An explicit future owner declassification and
qualified egress broker would be required to mix those flows; no format-2
toggle silently enables it. Host/runtime tests must prove both the network
boundary and resistance to hostile web/floorplan instructions. This split
still supports the garage journey: research public organization methods,
then synthesize them locally against private measurements and goals.
Publication must reject a web node whose exact prepared Task-input version
selects private files or whose reviewed instructions no longer match the
frozen brief digest; it cannot publish a knowingly unexecutable policy and
hope later admission catches it.

The policy names at most three final output slots (`layout`, `products`,
`steps`) and at most eight intermediate handoff slots (such as
`public_research_findings`). Every slot has exactly one producing Task, a
bounded registered artifact type and size, and an owner-review requirement.
Each slot's producer must request `write_registered_artifacts`.
Only final slots can satisfy the Project deliverable heads; intermediate slots
may be consumed by planned downstream Tasks but cannot masquerade as the
finished layout, products document, or implementation steps. For the garage
flow, public research produces a registered findings version in an intermediate
slot; private synthesis consumes that exact version and produces the final
customized `products` version.

At most 64 conditional transfers use bounded producer and consumer *node
indexes* in the same immutable plan, one or more named slots, a fixed
allowed-use code, schema/type, file-count and total-byte ceilings, and an
explicit checkpoint segment. Allowed-use codes describe only operations
that a later broker can constrain (for example, read a registered version as
input or carry its public citation into the products document); unsupported
semantic or adapter mappings are unapprovable. Producer and downstream
Task/Agent incarnations come from those plan nodes, never caller-provided
runtime IDs. A transfer requires a direct planned dependency edge from the
consumer to the producer, not merely a favorable list order, and cannot name
an external Task or cross the Project boundary. Every named slot, including
each slot in a multi-slot transfer, must name that exact producer node as its
sole producer. Publication discloses any
canonical Task dependency mismatch; approval must reject an unresolved
mismatch. A same-segment transfer is still conditional, not an unrestricted
latest-output alias.

At future execution, the producer must be one exact successful, finalized,
nonpartial canonical Run with the approved input receipt. The registered
immutable output versions must match the producer attempt, approved slot,
schema/type, count and bytes. Freeze those exact version IDs in a transfer
receipt before reserving the consumer Run; a later head or owner edit cannot
replace them. Missing, ambiguous, malformed, extra, unregistered or replaced
output needs owner review, never implicit substitution. An allowed-use code
does not claim that a model's reasoning can be policed after bytes are read;
qualification must prove the actual data-flow and output-control boundary.

Segment 0 needs its own exact execution approval. Every later segment waits
for a separate exact owner checkpoint decision before *any* node in it can
start. Owner-required transfer reviews and out-of-bound changes are additional
decisions, never substitutes for the segment checkpoint. No dependency or
segment number itself grants work.

Keep the existing finite per-node attempts, wall time and work units. The
worst-case requested attempts are `sum(max_attempts)`, work is
`sum(max_attempts * max_work_units)`, and wall time is
`sum(max_attempts * max_wall_seconds)`, counting every permitted retry. Format
2 stores separate plan-wide ceilings no larger than 96 attempts, 32,000 work
units and 604,800 wall seconds; each worst-case sum must fit its ceiling.
These are requested bounds, not enforcement claims or currency caps. Actual
approval later binds a qualified runtime revision and hard capacity/budget
reservations. A currency budget may be offered only when the provider gives a
verifiable worst-case reservation or hard cap.

An owner may publish format 2 only after the same exact Project, Task,
assignment, Agent incarnation, input version, context grant and dependency
checks as format 1. The new policy also validates output/transfer uniqueness,
types, sizes, graph order and checkpoint boundaries before the immutable
version commits. No browser text becomes a shell argument or a hidden prompt.
The policy projection is safe and bounded; runtime references, credential
sources and storage paths remain private. Owner manual assignments stay
canonical Task authority and can stale an unstarted plan.

Format-2 canonical JSON is at most 24 KiB UTF-8, with at most 64 transfers
and node indexes rather than repeated long Task IDs. The global 256-version
and 32-version-per-scope limits stay unchanged. The existing shared plan
metadata allowance adds 8 MiB beyond deliverable-review metadata; migration
tests must measure worst-case serialized rows, referenced inputs, scope
overhead, the 63-MiB SQLite admission ceiling and the 96-MiB private backup
unit. If 24 KiB cannot fit the measured bounds, reduce transfer count or
content size before shipping; do not raise the backup limit by assertion.
The SQL content check uses UTF-8 byte length
(`length(CAST(content_json AS BLOB)) <= 24576`) for format 2; the application
validator independently enforces the same byte ceiling. SQLite text character
count alone cannot enforce a byte limit.

## Deferred authority and qualification

Publishing a format-2 plan still creates no Run, Kanban card, provider call,
approval grant, Agent proposal, or Inbox approval item. A later execution
approval must recheck its exact content digest, current source identities,
grant, runtime binding and qualification receipt inside the reservation
transaction. It must reserve the exact Run/input/plan/budget receipts before
an adapter call, then require idempotent readback. Unknown delivery never
auto-retries. Stop, cancellation, reassignment, checkpoint continuation and
restore must keep the same exact evidence and capacity rules.

A lead Agent role gives no context or execution right. A distinct
owner-authorized, qualified *proposal-only* Project Run is needed before a
lead can propose Tasks that do not yet appear in a plan. It binds the exact
Project/context grant and prepared planning input without borrowing a
format-2 execution approval. An ordinary Console Run or Hermes Kanban card
cannot gain Project proposal standing from its prose or exported file.
The proposal-only runtime still needs the same whole-worker isolation and
bounded output proof; until qualified, proposal intake is dormant.

The accepted source is a registered, bounded artifact of that exact
successful, finalized, nonpartial canonical proposal Run. Parse it strictly
as untrusted data and show Task/Agent/dependency additions and changes as an
owner-side diff. Applying its Task suggestions requires a separate exact
preview, owner confirmation, guarded transaction and durable idempotency
receipt; it never silently creates or assigns canonical Tasks. Owner editing
may then publish a fresh format-2 plan version, never mutate the Agent
artifact into authority. Lead-role storage, proposal-only admission and
owner Apply need their own reviewed slices. Do not claim the garage lead
workflow complete from an owner-only format-2 editor.

Real host qualification must prove whole-worker separation from unrelated
Projects and host credentials, fixed allowed operations, public-only network
research, selected-file reads, registered output discovery, exact wall/work
limits, safe Stop and crash recovery. A Docker *terminal* sandbox alone does
not prove the worker's other tools and provider calls are constrained. If the
installed Hermes contract cannot meet these checks, keep it unavailable for
approved Project work and select or build a genuinely enforceable adapter;
ordinary Hermes Kanban delegation retains its separate existing capability.

## Implementation and proof order

1. Validate the exact schema-36 source graph and format-1 backup, restore,
   deletion and history behavior. Schema 37 must begin from the exact
   schema-36 signature, disable foreign keys only for the fixed migration,
   drop/recreate the immutable version triggers around a shadow-table copy,
   widen the format/content checks, and preserve every old row's bytes,
   digest, origin, version ID, scope/revision and input references exactly.
   Verify source and destination row/ref counts and bytes before the migration
   receipt commits; rollback on mismatch. Preflight free disk and database/WAL
   headroom for the shadow copy's transient duplicate rows, indexes and journal
   before changing a source near the valid schema-36 capacity ceiling. Fail
   safely before migration when that temporary space is unavailable, and test
   that near-capacity case as well as the final database/backup sizes. A
   schema-36 backup must still
   restore and upgrade, and a drifted source must fail closed. Format-1
   versions remain readable and forever unapprovable.
2. Add owner-only format-2 publication and a draft editor that shows the
   requested operations, output slots, transfers, limits and checkpoint
   differences. A lost save remains unresolved until exact version readback.
3. Add a distinct Project lead-role and strictly parsed proposal authority
   without granting or dispatching. Proposal intake stays dormant until a
   separately qualified, owner-authorized proposal-only Run can produce it.
   Keep manual Task assignment and an exact owner Apply boundary.
4. Implement execution approval only after an actual adapter/host proves the
   policy categories and limits. Use one atomic receipt and budget boundary,
   source-bound Inbox approval, verified readback and no automatic retry.

Tests must cover format-1 compatibility and ID reuse; forged/duplicate
operations or slots; cycles, cross-Project or future-producer transfers;
oversize policy; stale Agent/Task/grant/input/config; two-device publication
races; retained history and backup tampering; deletion/restore; and explicit
no-dispatch behavior. Qualified execution later needs hostile files/web,
unrelated-secret denial, budget and wall-time limits, crash windows, Stop,
uncertain delivery and checkpoint fixtures on the actual Linux runtime.
