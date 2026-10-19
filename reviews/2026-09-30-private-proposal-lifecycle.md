# Private proposal lifecycle consistency

Status: coupled producer/output contract review within the approved controller.
The destination remains registered producing-Run output and exact owner Apply;
this prerequisite does not replace those outcomes.

## Sequencing and authority

Schema 41 rejects new project_proposal Runs. Default Run, attention and Inbox
validation reject this source. The existing private archival allowance accepts
only a dormant reserved Run with no execution/Event/attachment state. A local
namespace completion witness and a succeeded synthetic call cannot turn that
row into a successful canonical producer. Complete source lifecycle and private
consistency handling must be implemented together with output registration and
successful finalization. A lifecycle-only PR or another dormant/non-Apply output
store is not the intended outcome.

Implement a separate strict private opt-in for the exact canonical proposal
source, using its schema-42 input receipt, one schema-43 generation/call graph
and schema-44 scope graph. It must not create another Run store or reinterpret
Conversation/Task fields. Retain the SQL insertion/source-update guard and
default live Run/attention/Inbox/getter refusal, browser controls and provider
qualification gates. No provider/model call or public product capability is
introduced. Credential-free synthetic fixtures may exercise future source
states by temporarily disabling the guard within their isolated transaction,
then restoring the exact trigger before validation/backup.

## Private state contract to resolve

Canonical proposal records have no Task/Conversation ID or runtime session
reference. Their details remain fixed empty metadata. Exact Agent/binding,
immutable input manifest, generation/model/policy, epoch and shared capacity
must match the retained source graph. Define private reserved, starting,
running and unknown state/dispatch pairs with strict revision/timestamp and
safe Event/attention order. Pending/unknown work retains capacity; absent or
ambiguous kernel scope does not mean closed. Successful completion remains
invalid until registered output can commit with finalization.

Prelaunch cancellation/interruption needs evidence that no external work was
possible. Postlaunch failure/Stop needs exact closure and truthful provider
settlement; unresolved provider work stays unknown/spent. No generic waiting,
queued, retry/resume, arbitrary Event payload, adapter reference or inferred
output promotion may enter this source. Private state validation is historical
consistency, not current approval or runtime qualification.

Private backup must capture active/unknown scope/call evidence and all immutable
input references without silently filtering it as dormant. Restore preserves
prior evidence and spending, rotates authority, fences delayed calls/outputs
and blocks new execution. It never reissues lost scope tokens or probes an old
PID/unit name as ownership. Same-host activation requires separately verified
old-scope/broker fencing; until available, unresolved restored state remains
blocked/checking and must not be advertised ready.

Registered output will later use an immutable receipt with exact Run,
generation/call/input/scope/terminal/blob/parser digests. Stage and verify bytes
through the existing private content-addressed boundary before the atomic
receipt/finalization/Event/Inbox transaction, retaining orphan-GC and exact
lost-response reconciliation. Precharge worst-case output/metadata/blob budgets.
No bare run_attachments row is sufficient provenance. Questions block owner
Apply; creating suggested Tasks grants no plan approval or Run execution.

## Verification before implementation

Resolve accepted state/Event/capacity and restore-readiness rules in two
independent contract reviews against existing source consumers. Test exact
pending/uncertain graphs, malformed authority/binding/epoch/state/Event fields,
private active backup without source changes, restored spent-debit/token-loss
fencing, wrong/missing scopes, shared-Agent races, default live refusal and
unchanged SQL guard, and schema-5 omission. Registered success is part of this
coupled implementation. Use no real provider or owner service. Code/package reviews and
proportional integrated tests remain required before any full PR publication.

## Resolved coupled contract

Both independent architecture reviews require one coupled producer/output
slice. Bind a frozen private launch receipt before scope intent to the exact
Run incarnation, generation, epoch, input manifest, Agent/binding, shared
capacity and fixed query/image/runtime/model/policy snapshot. Existing exact
dormant schema-44 history without a hold remains historical; no old scope/call
may be retrofitted. Synthetic qualification must be explicitly distinguishable
and cannot become production intake authority by later qualification.

| Canonical Run / dispatch | Required evidence | Capacity |
| --- | --- | --- |
| reserved / reserved | Exact new launch/input/generation/hold; no execution | Held |
| starting / submitting | Committed original scope-start intent | Held |
| running / accepted | Exact owned scope and bounded call graph; a verified close may await bounded finalization | Held |
| unknown / unknown | Any ambiguous launch, scope, provider, finalization or restored continuity | Held |
| completed / accepted | Known succeeded call, original natural completion/closure, stopped scope and registered immutable output | Released atomically |
| cancelled / rejected | Proven prelaunch cancellation with no starting/submission history | Released |
| other terminal failure/Stop | Exact local closure and nonambiguous provider outcome | Released |

Unresolved work cannot be terminal with partial=1 or terminal_finalized=0:
shared capacity counts active statuses, so that shape would release it early.
Questions in a valid proposal block Apply; they do not turn a completed
inference into waiting execution. Fixed safe events and the exact canonical
attention source must commit with lifecycle changes; generic payloads and
retiring retained producer Runs/events remain prohibited.

Record immutable Stop/cancel intent before any fencing/signaling. Successful
conversion requires no such intent; natural broker channel retirement is not
owner Stop. Conversion and owner Stop serialize through one exact Run revision
and the private lock. Whichever commits first determines the result. Execution
and cleanup still obey the original worker wall. Successful conversion's
acceptance decision must occur within the original scope's pinned monotonic
deadline, frozen in the original completion witness and checked before/after
publication and as the last pre-COMMIT fence. There is no extra publication
window and no caller-supplied timestamp or newly minted late witness can extend
that deadline. A physical COMMIT or acknowledgment may finish later without
downgrading truthful accepted success. Uncertain commit outcomes resolve by
exact immutable receipt readback; absent receipt grants no delayed conversion.

Retain exact response UTF-8 bytes as one bounded content-addressed blob, with
parser-v1 normalized snapshot/digest stored separately. Bind the immutable
conversion receipt to the launch/input/generation/call/Stop/scope/terminal
evidence and original output holder. Preserve schema45's immutable hold;
pending capacity counts only holds lacking an exact conversion receipt.
Publish/fsync/verify bytes through pinned no-follow descriptors, then atomically
commit conversion, retained attachment, scope closure, Run finalization,
fixed terminal events and attention. Full graph and budgets validate before
commit. A failed transaction retains only bounded disposable orphan bytes; an
exact committed receipt resolves a lost reply without repeating provider work.

Private backup must retain active/unknown/completed producer graphs and their
blobs without mutating live source. Exclude producer Runs from legacy JSON while
retaining all canonical IDs for private capture. Schema5 omits exclusive producer
output authority. Restore retains spent work/holds/output history and rotates
epoch; it never reissues launch/output tokens, converts delayed output or retries.
Same-host activation stays unavailable while original controller/broker cleanup
is unverified. A scope-name/PID probe is observation only and cannot satisfy that
activation gate. Production source insertion, browser getters/Inbox actions,
provider dispatch and owner Apply remain closed until their qualified admission
and consumer contracts are implemented and tested.

## Implemented coupled private slice

The original namespace handoff now pins the monotonic deadline before wait;
verified completion freezes that same deadline in its opaque witness. A new
acceptance check rejects missing/nonfinite/changed/expired deadlines and never
refreshes them. Historical completion readback remains distinct from new
conversion permission.

The descriptor-owned Linux output stage publishes exact bounded UTF-8 terminal
bytes through owner-private no-follow directories, missing-only links and
fsync/readback of the actual named inode and parent. It rejects malformed digest
references before traversal, symlinks, mismatched existing content and changed
root identity. A transaction-local attachment helper uses the caller's root-owned
guarded SQLite connection, savepoint rollback and exact ready deduplication. The
opening guard retains that exact connection identity, so foreign-root and
same-path handle/guard swaps both refuse before any metadata write. It
creates no retained reference, source receipt, Run completion or Apply authority.
Cross-root connections/guards are rejected before metadata insertion.

Both independent primitive reviews are clear after correcting final-inode
durability, deadline pinning and transaction-root binding. Twenty focused
methods pass on Linux with one unsupported-platform skip; Windows executes eight
portable methods with twelve Linux-only skips. The full actual Linux namespace,
stock-Hermes/image/broker/scope/readback/reservation regression passes 156 methods
without skips after the original handoff deadline change.

The coupled schema46 producer launch receipt, canonical state/Event/attention
validator, durable Stop fence, immutable output conversion/finalization,
source-aware active backup/restore and retention protections are now implemented
in this slice. Qualification purpose is immutable and does not
grant production intake or owner Apply. Exact unknown-Run Stop remains possible
after grant revocation/epoch rotation, while exact Stop replay returns retained
intent without another Event. Readback validates canonical authority, Events,
attention, source graph and stored bytes independently from completion witnesses.

Current qualification evidence: 14 actual Linux producer methods pass; six
independent recovery methods pass; three transaction methods cover concurrent
Stop/conversion, existing-blob deduplication at the metadata ceiling and real
durable-backup refusal of tampered input provenance before publication. The
156-method actual Linux namespace/image/broker/scope/readback/reservation
regression passes without skips. The schema46 exact-source/drift/DDL rollback
tests and related historical migration/input group pass 22 Windows methods.
Fresh wheel/sdist inventory and RECORD verification pass; 18 changed module
files match source/wheel/sdist/isolated install and all 18 import from that
installed tree, reporting schema46 and Next16.3.6.

The shared-writer, Conversation, Task-input, deliverable, Inbox and migration
group passes 142 Linux methods. Six independent synthetic pressure methods pass
on Windows and Linux without skips: 128 retained producers survive 265 ordinary
Runs plus Event pressure; malformed conversion/corrupt scope refuse shared
writers; unknown provider work cannot refund; concurrent Stop returns one exact
intent; and escaped near-32-KiB output fits the unchanged 128-KiB charge.

Final review found an ownership gap in the transaction test's thread cleanup.
The corrected helper always aborts its barrier and drains started children,
retaining the fixture if any remain alive. Two fault regressions cover a failed
second thread start and an interrupted join. All five transaction methods pass
on Linux; seven cleanup/architecture methods pass on Windows. The architecture
test now asserts the focused roadmap's current headings and ten destination and
safety boundaries instead of stale removed prose. Six existing canonical
Agent-capacity continuity/race methods pass on Windows, as do the 59-method
worker/reservation/blob/evidence group (12 Linux-only skips).

Independent A and B reviews are clear on the complete implementation, pressure
tests, thread repair and CI assertion update. Hosted CI and integrated acceptance
remain pending. This evidence uses an unchanged public Hermes image and a synthetic
credential-free backend, not a qualified live provider or owner host. No
issue-close, real garage acceptance or production enablement claim follows.
