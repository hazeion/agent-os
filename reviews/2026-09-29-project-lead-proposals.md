# Project lead proposals and owner Apply boundary

Status: reviewed implementation contract for [approved lead-agent plans
and handoffs](https://github.com/hazeion/agent-os/issues/239). This is not
authorization to dispatch a Project Run or to treat ordinary Agent prose as a
proposal. The owner may always assign Agents and edit Tasks manually.

## Source and authority

A Project may have at most one active lead Agent for its exact live Project
incarnation. The role is owner-set, bounded, revisioned private Project state;
it conveys no Project context grant, provider credential, runtime capability,
execution approval, Task-write right, or standing to submit a proposal. A
reassigned or deleted Agent, revoked grant, retired Project, restored authority
or changed runtime binding leaves the lead role visibly stale and blocks new
proposal reservation. Retain the old role and its exact incarnation as history
instead of letting a reused display ID inherit it.

A lead proposal needs one separately owner-authorized **proposal-only**
canonical Project Run. This cannot borrow a format-2 plan approval: the Tasks
it proposes do not yet exist in that plan. Admission binds the current Project
incarnation and revision, exact current Project context pointer/version, lead
role revision, Agent incarnation and runtime binding, active context grant,
one current immutable prepared Project planning input, fixed
proposal operations and hard attempt/wall/work ceilings in one private receipt
before any adapter call. A Project proposal Run must be distinguishable from
ordinary Console and Hermes Kanban/task-dispatch Runs. The canonical Run table
needs an exact migration adding a distinct `project_proposal` source; the
Task-scoped `mentat_run_input_receipts` cannot represent it. A separate
immutable Project planning-input/Run receipt must reference that source, with
a composite Run ID/source constraint and same-transaction postcondition before
dispatch. Run validation, retention, backup and reconciliation must understand
the new source; model text, an attachment name, or a browser flag cannot
relabel another Run. The runtime must first prove whole-worker file,
credential, tool, network and output containment on the actual Linux host.
Until then production proposal admission and intake remain unavailable.

The planning Run may read only owner-selected private Project context and may
write one bounded registered proposal artifact. It does not browse the public
web or send an external message. If public research is useful, the owner can
run it through a separate public-only Task and review its registered version
before selecting it as planning input. Current `mentat_deliverable_versions`
are owner-edit authority; their validator does not accept generated versions
or intermediate research slots. Add a separate bounded immutable generated-
output registration, validator, backup and retention authority. Never relabel
an owner edit or raw `run_attachments` as Agent provenance. Only an exact
registered research/document output version from the same live Project and
one successful, finalized, nonpartial producer Run may cross this boundary.
The owner selects
at most three such versions with a total ceiling of 1 MiB and an explicit
read-as-planning-input use; the planning-input and Run receipts freeze each
version ID, digest, type, slot and producer Run/Task incarnation. Each version
binds either its immutable approved format-2 plan/node/slot or an exact
alternative owner-authorized public-only Task Run receipt. A missing or
caller-selected provenance branch is invalid. A generic attachment, URL,
mutable result head or loosely named
blob is never eligible. A proposal-only Run cannot create a
Task, assign an Agent, publish a plan, grant context, dispatch successors, or
approve its own output. Stop and ambiguous delivery retain truthful Run/Event
evidence and never resubmit automatically.

The prepared Project planning input is a separate authority from Task input:
one immutable owner-reviewed instruction brief, the exact current Project
context version, an active lead Agent grant/revision, and at most eight
selected, verified materialized inputs **total** with at most one image. This
shared eight-input ceiling includes context files and the separately bounded
owner-selected registered Project output versions above; a smaller qualified
adapter ceiling wins. Validate count, type and byte limits before reservation,
without silently dropping an over-limit item. It binds file and
output versions and content digests, retains their blobs, uses the existing
descriptor-relative no-follow Run materialization and cleanup boundary, and
never copies absolute paths into a plan or browser response. Editing the
Project context pointer, grant, Agent, file, or planning input blocks future
reservation. The fixed
proposal Run receipt freezes that input version and selected bytes before the
adapter call; it cannot borrow a Task-input receipt for a Task that does not
yet exist.

## Proposal intake

Only one exact successful, terminal-finalized, nonpartial canonical proposal
Run may supply the proposal. The source is a registered immutable artifact
from that Run's server-owned export boundary, not a path found in model prose
or a browser-supplied blob. Freeze the Run incarnation, source receipt, exact
artifact version/digest, Project/context/lead/input identities, proposal
generation and parser version in a
bounded proposal receipt. Unknown, failed, partial, unregistered, oversized,
ambiguous or replaced output cannot enter the owner Apply path. A replay of an
intake request returns the same receipt without rereading a mutable head.
The registered artifact is retained as an immutable project-owned blob and
parsed snapshot (at most 32 KiB per proposal and 128 retained proposals)
with a reference-aware pin in the private backup graph. Its content digest
must verify on every read and restore. The receipt's FK/retention protection
prevents terminal Run pruning or attachment GC from deleting source evidence
while the proposal can be reviewed or applied. After disposition, bounded
pruning may remove old content only through an explicit reference-aware grace
path; never turn a missing blob into an apparent successful proposal.
Generated research outputs selected as planning input have the same producer
Run and blob retention protection through the planning Run and any later
proposal receipt. Registering one requires fixed server-owned run-export
discovery, immutable type/size/digest readback, the exact producer source
receipt and a terminal-finalized nonpartial Run. Generated-output registration
grants no final-deliverable acceptance; promotion into the separate
layout/products/steps owner-review authority requires its own exact reviewed
capability.

Parse the artifact as untrusted structured data: at most 16 suggested Tasks,
each with bounded title and description, optional canonical Agent assignment,
optional due date and earlier-row dependency indexes. Reject duplicate or
unknown fields, duplicate tasks, invalid dates, self/future/cyclic dependencies,
cross-Project references, unsafe links/paths, hidden tool requests, and any
content that exceeds the shared document and Task authority limits. Existing
Task edits need exact canonical Task IDs/revisions and explicit operation
codes; default to proposing additions only. The parser may present explanatory
text as inert bounded prose but never execute it as an instruction. Suggestions
must fit remaining Project/Task/Agent/plan capacities before review.

The browser sees a safe Project-scoped diff: proposed Task title, description,
assignment and prerequisite names; source Run status and bounded provenance;
the current canonical Project/Task values; and any stale reason. Runtime refs,
storage keys, paths, credential sources and raw provider payloads remain
private. The owner can edit suggestions in a local draft or reject the
proposal, and can still create or assign Tasks directly. Editing creates a
new owner draft; it does not mutate the Agent artifact or preserve Agent
provenance for the edited bytes.

## Exact owner Apply

Apply is a separate exact preview and confirmation. Bind the Project
incarnation/revision and current context pointer/version, lead role/Agent/grant
and runtime binding revisions, current prepared Project planning-input version,
proposal receipt and artifact digest, every referenced Task incarnation and
revision, the normalized owner-edited diff, target Task IDs, dependency graph
and a private confirmation epoch. A changed input requires a fresh preview.
If goals, floorplan, context files or the current context pointer changed
since the source Run, the proposal is stale even while its old grant remains
active. Preview and commit reject Apply. The owner may request a new proposal
or manually create Tasks from the displayed ideas; this is an explicit new
owner action without Agent provenance.
The confirmation uses one `private_state_lock` and guarded `BEGIN IMMEDIATE`;
it calls `TaskRepository.mutate_collection` on that same connection (using its
existing nested savepoint) and inserts the idempotency receipt before the
outer commit. Do not call `mutate_authoritative_tasks` in a second transaction.
Test a late receipt failure for whole-batch rollback and same-key/same-body
replay versus same-key/different-body conflict. This is one SQLite Task/receipt
transaction, so either every approved Task/assignment/dependency change and
the idempotency receipt commits or none does. A repeated confirmation returns
the exact committed result without creating Tasks twice. If publication status
is unknown to the browser, it reconciles by exact receipt/readback; it never
auto-retries a different body. Apply does not publish a plan or start a Run.
The owner next reviews a fresh immutable format-2 plan version, including
operations, output slots, handoffs and checkpoints, before any later execution
approval can be considered.

Project deletion/recreation and backup restore retain source evidence without
reviving an old role, proposal or confirmation on a new incarnation. A role
revocation blocks new proposal Runs and an uncommitted Apply. An already
committed owner Apply remains ordinary canonical Task history; it cannot be
rolled back by hiding a proposal. Quotas include role versions, proposal
receipts, bounded artifact bytes, Task additions and action receipts in the
validated private-backup unit.

At most one unresolved proposal generation exists per live Project
incarnation. Reservation under the Project lock creates a monotonic private
generation bound to the exact lead role and context pointer. A second Run
cannot claim that generation or silently supersede it. Verified Apply,
explicit owner rejection, or exact terminal recovery closes the generation;
unknown or active work must be reconciled before a new generation is
authorized. A later generation makes earlier uncommitted proposal output
historical and unapplyable. Intake and Apply both bind the current generation,
so late provider output from an older Run remains evidence without taking
over the owner's current review. Role revocation or reassignment makes a
completed but unapplied proposal stale; the UI can show it for manual copying
without retaining its Agent-proposal authority.

## Implementation and proof order

1. Add bounded role, Project planning-input and proposal-source schema with
   exact predecessor-schema gate, migration/backup compatibility and no
   role-derived grants. Widen the canonical `mentat_runs.source` CHECK through
   a fixed table rebuild, preserve old Run/Event/Task-input bytes and FKs, and
   update every Run validator, retention, backup, reconciliation and capacity
   path. Do not attach a proposal role receipt to an ordinary Console or
   Kanban Run. Expose an
   owner-only lead selector and stale readout; do not advertise proposal Run
   readiness.
2. Define and test the separate proposal-only runtime qualification and
   admission receipt on the actual Linux host. First add generated-output
   registration, validator, source-Run/blob pin graph and exact optional
   plan-versus-direct-Task provenance; current owner-edit deliverables do not
   supply it. Prove file/secret/network/tool isolation, output registration,
   hard time/work limits, Stop, crash and
   uncertain-delivery behavior. Production intake remains closed until this
   gate passes.
3. Add the registered-artifact parser and retained proposal receipt, then an
   owner diff, exact Apply preview/confirmation and readback. The UI can draft
   a new format-2 plan from applied Tasks but may never silently publish it.

Tests must include forged ordinary Runs/artifact paths, duplicate and stale
role identities, revocation/reassignment and two-device races, malformed or
hostile proposal content, missing/partial output, producer retry ambiguity,
Task ID reuse, dependency cycles, batch capacity/rollback, repeated Apply,
lost response, restore, and zero Run/adapter/permission effects from role
selection, intake, and Apply. Built desktop/mobile owner review and a real
host/provider walkthrough are separate final acceptance gates.

Review evidence: two independent read-only design reviews identified and then
cleared gaps in current-context freshness, concurrent proposal generations,
canonical Run source and Project-input migration, producer Run/artifact pinning,
atomic Task/receipt Apply, and the exact generated-research handoff. This
contract does not claim any of those implementation or host-qualification
gates have passed.
