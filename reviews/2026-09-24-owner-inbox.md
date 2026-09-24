# Durable owner inbox and coordinated Project review

Status: contract reviewed by two independent agents for issue
[#240](https://github.com/hazeion/agent-os/issues/240); implementation has not
started. This is the contract for a complete owner
attention surface, built in reviewed slices on the current Project, Task, Run,
plan and deliverable authorities.

## Purpose and authority

The inbox shows one owner's questions, pending approvals, failed or uncertain
work, and results awaiting review across devices. It is an index of durable
Mentat facts, not an Agent mailbox, execution scheduler, or second source of
truth. Each item points to one exact source record and its safe navigation
target. Opening, reading, acknowledging or dismissing an item never approves a
plan, accepts a result, retries or stops a Run, changes a Task, grants context,
or sends text to an Agent. The destination invokes its own exact guarded
preview/confirmation capability after refreshing canonical state.

The first producer is the existing three-slot Project result bundle. A complete
set of current saved result versions appears as one `result_review` item only
while `read_review_status()` is `pending`: there is no exact owner decision on
those three heads. It names the Project and three safe slot summaries,
not file paths, raw content or runtime payloads. A new head in any slot creates
a new exact attention generation even if the previous generation was read or
acknowledged. Acceptance or a request for changes resolves that generation.
A change request keeps the affected slots and owner note visible in the Project
review authority but does not recreate an item for unchanged heads. Revisions
and Agent-produced results retain
their immutable provenance at their source. The inbox must not infer that a
completed Run is an accepted deliverable.

Existing canonical Run failure, unknown-submission and recovery evidence can
feed later inbox producers without waiting for Project execution. Producers
for exact plan-approval requests, checkpoint questions and Project completion
depend on their future canonical capabilities. A lead Agent proposal can create a request only
after a trusted producing Run has registered a bounded draft plan; model prose
alone never becomes an inbox action. The owner can also assign Agents manually
without an inbox item. Unqualified Project execution remains unavailable.

## Identity, state and retention

An item has a server-owned kind and opaque ID, a stable source identity, an
exact source generation, severity, created and updated times, resolved state,
and a server-generated destination kind plus canonical IDs. A safe title and
summary are derived from the current source on read, capped to 500 UTF-8 bytes
each, and never copied into inbox storage. Source incarnation and approval
epochs stay private. A unique
`(kind, source identity, generation)` key deduplicates repeated source reads,
HTTP retries and restart reconciliation. For result review, the private source
identity is Project ID plus Project incarnation; the generation is a canonical
digest of the ordered three exact current version IDs. Only the opaque inbox
ID crosses to the browser. A new source generation is not merged
into an acknowledged old item. Acknowledgment records that the owner handled
the notification; it never resolves the underlying work. Unread and
acknowledged are distinct owner-private states. Opening may mark an exact item
read; an explicit Acknowledge action changes acknowledgment with an expected
item revision and idempotent action receipt. A stale request reloads the item
without silently applying to a newer generation.

Source changes and item creation or resolution must commit in the same private
SQLite transaction when Mentat owns the mutation. For existing retained
sources, a one-time bounded reconciliation may materialize only current
actionable generations; it must not manufacture a backlog of old unread work.
At startup, reconciliation is idempotent and cannot execute any action. Result
reconciliation derives only `pending` heads. A current `accept` or
`request_changes` decision leaves its exact generation resolved; a newly saved
slot head creates a different pending generation. A non-active Project leaves
its item visible with `activation_required`: review controls stay closed until
an explicit supported status change and fresh exact-head check. Archived
Projects may use the existing guarded Restore; paused Projects cannot be
reviewed until a supported activation path exists. Confirmed Project deletion
marks any open item for that
incarnation stale/resolved and retains its read/ack history; recreating the
same public Project ID starts a separate source identity. Restore validates
the inbox against the restored source graph and never resumes work. If an
external adapter supplies incomplete or ambiguous evidence, show a checking
or unknown item rather than success or automatic retry. The inbox may safely
lag a nonterminal source, but it must never claim completed work from a hint.

Bound the global item count to 2,048, result-review generations to 256 (the
existing global deliverable-version ceiling), derived title/summary to 500
UTF-8 bytes each, and list pages to 50. Persist no title, summary or source
content. Bound each serialized inbox row, including IDs, state, timestamps and
action receipt, to at most 768 bytes; charge 768 bytes per admitted row plus
fixed table overhead against a 2 MiB inbox metadata allowance in private
backup validation. An over-limit row or budget fails admission before write.
Prune only resolved, acknowledged oldest items when capacity requires it;
unresolved or unread owner action is retained. At capacity with no safely
prunable item, reject the originating source transaction before commit rather
than silently lose a required notification. Show an explicit Inbox capacity
error and retain the owner's source draft for retry after resolving or
acknowledging old items. The source authority retains its
own history. Owner-private inbox state joins the validated backup/restore
consistency unit; restore preserves notices and read state, rotates action
receipts where needed, and never starts hidden work. Retired/deleted Project,
Task or Agent identities stay stale navigation references, not live ID reuse.

## Browser behavior

The Next.js Emerald interface has one Inbox destination with Needs me, Unread
and All views, bounded pagination and a visible unavailable/reconnecting
state. Home may show a capped count and top items as navigation only; the full
inbox remains the owner surface. Every item says what needs the owner's input,
what changed, and where to review it. A click opens an item-bound destination,
not a plain `?project=ID` link. For result review, a fixed server capability
joins the opaque inbox ID with the current Project incarnation and ordered
three exact heads. It exposes the review surface only while those identities
still match, then focuses `Review Project results`. A non-active Project instead
shows an activation-required detail with review controls closed; Restore is
offered only for archived Projects through the existing guarded lifecycle.
Changed heads, deletion,
ID reuse or a source change between list and open yields a stale item detail
with Refresh; it never selects another Project sharing an old ID. An actual
review still uses the existing exact preview/confirmation path bound to this
item generation. Other destination kinds need equivalent source guards before
they become interactive. No generic URL or runtime reference is accepted from
the item. The Node gateway exposes
fixed same-origin owner-session reads and CSRF-protected exact mutations; only
Python reads and writes SQLite. Browser push/notifications are optional and
request permission only after an explicit owner action. Closing the browser
never stops previously authorized work.

## Coordinated revision workflow

A Project review decision binds all three exact current deliverable versions.
An owner change request names affected slots and a bounded note under that
existing authority. The coordinator later maps each affected slot to the
approved plan nodes and their exact output receipts; it cannot infer that a
Task should rerun from a free-text note or silently replace downstream
inputs. Changes beyond the approved scope or remaining limits become a new
owner approval item. Unchanged prior versions remain inspectable as source
history; schema 32 accepts the whole bundle, not individual slots. A
replacement three-slot bundle requires a fresh whole-bundle decision, while prior versions and decisions
remain inspectable. Failures, cancellations, unknown submissions and interrupted
recovery stay separate items until their canonical status is verified; they
are never auto-retried because an inbox tab was opened.

## Slices and proof

1. Add a schema-backed inbox authority with bounded source identities,
   generations, read/ack state, transactional result-review projection,
   backup/restore validation and exact owner HTTP bridge. No generic event
   publisher or browser-selected source key.
2. Add the owner Inbox page, Home count/navigation, exact stale deep links,
   cross-device read/ack and built desktop/mobile review acceptance.
3. Add producer adapters for existing Run failure, unknown and recovery
   sources, then trusted plan requests, checkpoint questions and verified
   Project completion as their canonical capabilities land. Add coordinated
   change routing only after the approved
   plan and qualified runtime receipts can identify affected nodes exactly.

Test duplicate transaction/restart materialization, repeated browser actions,
stale source/Project ID reuse, source change between list and click, two-device
read/ack races, deletion and restore, capacity pressure, backup tampering,
ambiguous adapter outcomes, bounded text, same-origin/owner admission and
desktop/mobile keyboard focus on the review section. A completed first or
second slice is not proof that every kind of requested work can already
execute or appear. Keep issue #240 open until its full producer and
coordinated-revision scope is verified.
