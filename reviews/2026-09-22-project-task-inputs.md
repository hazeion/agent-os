# Approved Project Task inputs and plan admission

Status: contract reviewed; implementation pending. Execution is not qualified
or enabled.
Scope: [exact Task inputs](https://github.com/hazeion/agent-os/issues/262) and
the prerequisite admission contract for
[approved plans and scoped handoffs](https://github.com/hazeion/agent-os/issues/239).
The owner's implementation authorization is recorded in map 234. This contract
does not claim the remaining runtime qualification or garage acceptance gates.

## Product behavior

The owner can assign an Agent manually and prepare one Task, or ask a lead Agent
to propose a dependency plan. A proposal is editable data with no execution
rights. The owner reviews the exact Task objectives, Agents, selected input
versions, allowed operations, limits and checkpoints before approving work.
Saving a plan or input selection never dispatches. Existing Conversation Send,
planning associations and ordinary Run once retain their existing meanings.

One manually approved Task uses the same admission contract as a one-node plan.
This permits a lead's initial planning Task without inventing an implicit
Project-wide permission. Lead roles, dependencies and handoffs confer no grant.
An owner can always change assignments; changes invalidate unstarted approval.
Active or unresolved reserved work must be shown separately and explicitly
stopped before replacement work is eligible. Verified terminal work needs no
Stop. A failed Stop cannot be described as reassignment.

## Exact input authority

Add a private Task incarnation independent of its reusable display ID, with
creation/deletion handling in every canonical Task write path. Input versions
belong to that incarnation and the exact live Project scope. Moving a Task
retires its prior input scope; recreating a Task or Project cannot adopt it.
Migration initializes identity only and grants no inputs or execution rights.
This invariant does not add a Task-move capability where moves are unsupported.

An immutable input version contains canonical Task/Project identity, bounded
instructions, one explicitly granted context version, its grant revision, and
an ordered selection of retained context files. Subsequent deliverable support
adds explicitly selected immutable versions or exact versions resolved under an
owner-approved conditional transfer below, never a latest-result alias.
No implicit Task notes, Calendar links, dependencies, other Project content or
Conversation transcript is injected. The visible Task objective and explicit
owner review feedback must be covered by approval and the immutable receipt.

Preparation validates complete membership, content type/size, retained bytes
and the Agent grant. Storage accepts at most 32 versions per Task and 256
globally within the existing shared metadata budget. Instructions are at most
16 KiB UTF-8. Selected execution inputs remain at most eight files and one
image, or a smaller adapter limit; failures preserve the whole draft and never
truncate or continue without files. The composed text and file manifest also
must fit the exact qualified adapter's declared bounds before approval.

Approval binds the private Task/Project/Agent incarnations, canonical Task
revision and membership, objective/review feedback, input version and ordered
file identities, context/grant revision, private runtime binding/configuration
digest, exact capabilities, qualification revision, allowed tool operations,
approved segment/attempt limits and plan/checkpoint revision. Dispatch separately
makes an atomic reservation against those unchanged limits; insufficient
remaining capacity pauses admission rather than changing the approved budget.
Browser projections expose
safe names, versions and limits; all private bindings remain Python-owned.
Publishing newer context does not change a saved input or enlarge its grant.

## Plan and checkpoint authority

Use immutable plan versions with at most 32 nodes and an acyclic dependency
graph, at most 32 versions per Project and 256 versions globally. Every node
references one canonical Task incarnation and one input version, one Agent,
bounded attempt/time/work limits and its required owner checkpoints. A node
may not refer to itself, another Project, or the same Task twice. The shared
metadata budget charges plans and execution receipts as well as input records.

Lead-generated proposals enter through a fixed validated proposal capability
under the exact producing Run. Model prose is not parsed as a command. A
proposal may contain bounded draft Task specifications; canonical Tasks are
created only by a separate explicit owner Apply action with an exact preview,
guarded transaction, safe Task defaults and a durable idempotency receipt.
Creation is preparation, not execution approval. Existing Tasks and manual
assignments remain selectable without accepting the lead's recommendations.

Every execution approval covers one exact plan version and a finite segment
between review checkpoints. A terminal Run does not imply owner acceptance.
Within a segment, a successor can become ready only from verified successful
predecessor receipts and permitted handoff selections. Crossing a checkpoint
requires exact owner approval; changed output versions require fresh approval.
Failure, missing inputs, uncertain status, exhausted limits or unavailable
permissions pauses affected descendants. Independent already-approved nodes
may proceed only within their unchanged segment and shared remaining limits.

A handoff is either an owner selection of existing immutable versions or an
explicit conditional transfer policy in the approved segment. Dependency edges
alone confer no permission. A conditional policy binds named producer and
destination nodes, Task and Agent incarnations, named output slots, fixed
schemas/types/count/byte limits, allowed uses, deterministic selection rules,
segment and attempt/work limits. The owner sees those transfers before approval
and may require a manual checkpoint on any edge.

After the exact approved producer attempt has verified success, the coordinator
may resolve only its registered, validated output slots. It freezes their exact
immutable artifact IDs, versions and content identities in a durable handoff
receipt before atomically reserving destination inputs. No Agent chooses the
recipient, broadens tool rights, selects arbitrary files or follows an
unrestricted latest-result alias. Missing, ambiguous, malformed, extra or
replaced outputs require a checkpoint; a producer retry or owner edit does not
silently substitute new versions. Outputs may support intermediate approved
work without being marked owner-accepted final deliverables.

This explicitly extends the earlier exact-version-only selection contract:
unknown future identities are resolved only by the bounded preapproved transfer
policy, and become exact receipt identities before downstream dispatch. Direct
grant and file-read APIs retain their exact-version requirements. A transfer
grants only its named destination attempt's immutable inputs, not general
Project/context access. Revoking the plan/transfer prevents new reservations;
revocation of any required context grant also blocks the successor.

## Durable dispatch and limits

Keep Hermes Kanban as the first durable backend. A plan approval creates a
Mentat-owned execution grant, not a Conversation queue or arbitrary Kanban
authority. Only a fixed coordinator may claim one approved ready node and
derive an operation-specific authorization under that grant. Amend the existing
Kanban adapter contract explicitly: that derived authorization must bind the
same refreshed Task/intent/live state as an immediate owner confirmation,
plus the exact plan/input/grant and budget receipt. Ordinary delegation keeps
its explicit preview/confirmation behavior. No generic command or runtime API
passthrough is introduced.

Under the existing private-state lock and one SQLite transaction, revalidate
the full graph, claim the node at most once, reserve bounded adapter capacity
and work budget, and create the canonical Run and immutable input/dispatch
receipts together. External operations happen only after commit, with no
database lock held. A second pre-dispatch check rejects newly revoked or
changed authority before sending any inputs. A revocation after that check
may race with transmission; classify the reserved Run as possibly delivered,
never claim bytes were retracted, and offer verified Stop. Later reservations,
retries, handoffs and new reads remain denied after revocation.

Supported fixed Kanban submission must accept a bounded idempotency identity
and allow exact normalized readback. The adapter records its private remote
references and reconciles them to the canonical Run receipt. CLI acknowledgement
alone is not success. If supported upstream operations cannot preserve the
approved files, restricted tools, receipt identity, limits and verified Stop,
the adapter remains unavailable for Project execution. Do not substitute the
broader Console path or bypass Kanban by launching a worker directly.

Require finite per-attempt wall time, a finite runtime-enforced work ceiling,
bounded concurrency and a segment-wide reservation ledger. A host watchdog
stops overdue attempts through the verified adapter; unresolved Stop remains
unknown and retains capacity/budget reservations. Never release reservations
merely because a browser disconnected, a process restarted or usage was late.
Currency ceilings, when offered, require a verifiable worst-case reservation
or provider-enforced hard cap; an estimate cannot satisfy a requested cap.
An adapter unable to enforce the selected limits cannot receive that approval.

Crash after reservation but before confirmed external delivery is not proof
that nothing ran. Startup/restore pauses automatic admission and reconciles
each nonterminal receipt through supported readback. Indeterminate outcomes
require owner reconciliation and never auto-retry. A verified retry is a new
Run and budget reservation for the same immutable input only after fresh
authority checks and explicit owner action. Duplicate browser confirmation
returns the durable action receipt without contacting the adapter twice.

## Qualification and retention gates

The fixed adapter must prove isolation from unrelated files, credentials,
Projects, local network services and unrestricted tools, including hostile
web/floorplan content. A prompt, toolset name or filtered input list is not an
isolation mechanism. Host-admin qualification binds the exact runtime build,
configuration and supported capabilities; a changed binding invalidates it.
No runtime is currently qualified, and no migration advertises qualification.

Run-input receipts are retention roots. Extend blob capacity, staging release,
pruning, deletion, backup validation, restore, export and garbage collection
together. Current/granted context, retained input versions and exact Run-input
evidence cannot be pruned independently. Deleted Task/Project/Agent history
retains bounded non-owning provenance without recreating live identities.
Restore revokes execution grants and rotates approval epochs; it preserves
immutable evidence and never resumes hidden work.

## Implementation and verification order

1. Review this contract against current Task, Run, Kanban and context authority.
2. Alongside storage design, perform a bounded read-only feasibility check
   against the actual supported Linux/Hermes version for isolation, input/output
   preservation, idempotent readback, enforceable limits and Stop. Report
   unsupported upstream contracts before committing to a coordinator. Inventory
   neither provisions credentials nor runs model work.
3. Implement Task incarnations, immutable input versions, exact owner editing
   and preview/approval, retention and backup/restore. No runtime dispatch yet.
4. Implement canonical Run/input receipts and the fixed qualified-adapter
   admission boundary with race, crash and duplicate-delivery fixtures.
5. Implement plan versions, proposal/apply, approval segments, checkpoints,
   work reservations and fixed Kanban coordinator. Manual approval stays usable.
6. Qualify the actual Linux/Hermes/provider combination, including public
   research, floorplan input, safe output discovery, limits and verified Stop.
7. Integrate versioned deliverables, owner inbox and coordinated review, then
   run the complete garage scenario and requested revisions on the live stack.

Required tests cover identity reuse and moves, stale approvals, concurrent
edit/revoke/dispatch, missing/tampered files, selected-input limits, unrelated
context denial, cyclic plans, changed assignments/configuration, budget races,
checkpoint gating, duplicate apply/approval, all dispatch crash windows,
uncertain readback, failed Stop, restore and explicit retry after revocation.
Conditional-transfer tests additionally prove exact producer-attempt/slot
resolution, malformed/extra/replaced output denial, manual-edge checkpoints,
revoked transfer/context denial and zero general-purpose read authority.
Every major slice requires both independent reviews and tested PR publication.

## Review and inventory evidence

Two independent reviews identified a fidelity problem in the first draft:
requiring owner approval for every new handoff would undermine the approved
coordination between checkpoints. The revised explicit conditional-transfer
policy and matching architecture amendment resolve it. Stop now applies only
to active/unresolved prior work; unsupported Task moves remain unsupported;
approved budget limits are distinguished from per-attempt reservations. Both
re-reviews are clean.

Read-only discovery on the current development machine found no `hermes`
command on either the Windows PATH or the Ubuntu WSL PATH. This is not proof
that Hermes is absent from every location, and WSL is not a selected production
host. No provider credentials were inspected and no Agent work was started.
Actual host/runtime inventory and live qualification remain outstanding;
authority storage and approval implementation can proceed independently.
