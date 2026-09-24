# Durable Run outcomes in the owner Inbox

Status: independently reviewed design for the existing-Run producer portion of
[#240](https://github.com/hazeion/agent-os/issues/240). No Run-attention
implementation or execution authority is approved by this document alone.
Schema 35 first establishes the private Run incarnation. It does not yet
reserve Inbox capacity or publish Run notices; those remain follow-up work
under the admission and transition contract below.

## Source and identity

An Inbox item for a Run must be derived from Mentat's canonical Run state, not
adapter text, a browser poll hint, or a Conversation Message. It covers
Console and Task-dispatch Runs. A private 128-bit Run incarnation is assigned
when the canonical Run row is created and backfilled once for retained Runs in
schema 35. The pair `(Run ID, incarnation)` prevents a pruned/reused public ID
from retargeting an old notice. One item covers one exact Run attempt, not a
Conversation, Task, Agent role, or automatic retry queue. A later Retry is a
new canonical Run and can get a separate item. The browser sees only the
opaque Inbox item ID and safe names/status.

Schema 35 widens the Inbox's fixed kind/source-ID checks without changing the
schema-34 result-review meaning. It also widens the current 16-revision item
ceiling to a bounded signed integer: a Run can change attention repeatedly and
owner actions consume revisions. Python, Node, browser and backup validators
must agree on that ceiling. The schema-34 Project-retirement trigger must be
scoped to `kind='result_review'` so it cannot retire unrelated Run items.

Schema 35 adds a minimal owner-private retired-Run outcome receipt. A live
item resolves against the exact Run row. When either Run retention path or
confirmed Task/Project deletion removes that row, one transaction captures
its canonical ID/incarnation, source kind, exact status, dispatch state,
`partial`, `terminal_finalized`, state revision, safe ownership references and
timestamps in an immutable receipt. The item then points to that receipt, so
it never becomes an orphan or silently resolves to another Run. The receipt
records Mentat's last evidence classification rather than upgrading an
incomplete outcome to a verified one. It does not certify Agent output or
retain raw provider payloads, credentials, files or model reasoning. A
deleted source is shown as retained history, with all Run controls closed.
Existing full Run evidence remains under normal retention while available.

## Admission and transitions

Admission creates a hidden capacity reservation tied to the exact Run
incarnation. It is not a visible Inbox item, does not increment unread counts,
and cannot be acknowledged. This applies to every Run insertion/upsert path,
including Task and Console admission, legacy Console import in
`ensure_run_sqlite_authority()`, and `sync_summaries`. Historical imports
establish a quiet baseline only for already-finalized ordinary completed,
stopped or cancelled Runs. Existing `unknown` Runs, unresolved
partial/unfinalized terminal Runs, and retained finalized `failed` or
`interrupted` Runs must surface as Needs me exactly once on upgrade or import
unless an exact item already represents them. Repeated startup cannot create
another item. A reservation
converts atomically to one visible item when the Run first has a qualifying
outcome. Its capacity remains charged thereafter.

Only durable canonical transitions produce attention, in the source SQLite
transaction. `unknown` with `dispatch_state='unknown'` is presented as
uncertain delivery requiring exact reconciliation, never as a failure or
permission to retry. All first-time finalized terminal outcomes—`completed`,
`failed`, `interrupted`, `stopped`, and `cancelled`—are eligible; stopped and
cancelled are informational unless their evidence is partial or uncertain.
`failed` and `interrupted` require terminal finalization before being named
terminal. A verified `completed` Run may produce an informational completion
item, but it never implies accepted Project deliverables. Partial or
unfinalized terminal evidence remains checking/uncertain; no success label
crosses the Inbox boundary. The exact no-submission recovery path may finalize
an interrupted Run in the same transaction only if its separate *dispatch*
reservation is still `reserved` with `attempt_count=0`, proving no provider
call was attempted. The hidden Inbox reservation proves no such thing. A
fixed trigger or repository hook may
maintain one source-bound item as status changes; every path (startup
recovery, adapter readback, Task Run, Console Run, Stop, import and restore)
must pass the same final validator before commit.

An unknown attempt that later becomes terminal updates its one item to the
new verified outcome, clears its old read/ack state and increments its item
revision. A completed or stopped attempt after uncertainty likewise retains
the old evidence but tells the owner the newly verified status. Duplicate
readbacks do not generate duplicate items. An acknowledged or resolved item
may be pruned while its Run is live only if that Run's outcome is immutable;
otherwise retain the item/slot or atomically recreate it on the next
qualifying transition. Startup reconciliation must materialize the existing
unknown, unresolved partial/unfinalized, finalized failed, and finalized
interrupted Runs specified above;
it cannot contact an adapter, dispatch work, resume or retry. The global
activity rail and Inbox must both label unreconciled nonterminal state as
checking, not working.

## Owner actions and navigation

Opening or acknowledging a Run item changes attention state only. Unknown
delivery cannot be dismissed as harmless; it remains Needs me until exact
operator reconciliation verifies its source or an explicit, source-bound
recovery action records a new outcome. A failed/interrupted Run may be
acknowledged as seen, but Retry, Stop, Resume and Task-stage changes remain
their existing source-specific preview/confirmation capabilities. Dismissal
of a finished failure is a separate exact owner choice that resolves only the
Inbox notice, preserving the Run or retired receipt. A verified completion
item may be resolved by explicit Acknowledge without changing the Run.

`/inbox?item=<opaque-id>` opens a fixed item-bound detail, rechecking the
live Run incarnation and state revision before offering a safe navigation
link. Current Console Runs may open their exact Conversation tab; current
Task Runs may open the exact Task inspector or Runs page. The destination
must recheck the same private identity, not trust `?run=<ID>` alone. If the
Run was pruned, deleted or restored with changed authority, the item shows
the minimal retained outcome and no Retry/Stop control. A stale browser read
or repeated action never calls an adapter. Owner read/ack/dismiss revisions
are durable across devices and validated in backup/restore.

## Capacity, retention and backup

The current Run authority admits at most 10,000 Run rows. Charge a hidden
reservation at admission so a later failure or unknown state can be recorded
without making the Run transition fail. Existing Runs receive reservations
in the exact schema-35 migration. The candidate global maximum is 10,256
charged slots: at most 10,000 Run reservations/items and 256 result-review
generations. These bounds must be measured against serialized row and backup sizes;
the final caps must fit the existing 64-MiB database and 96-MiB backup unit
ceilings. Before a new reservation, only resolved, acknowledged oldest items
and their now-unneeded retired receipts may be pruned. Hidden reservations
for active Runs cannot be evicted. If every slot is protected, Run admission
fails clearly before provider dispatch; a Run failure itself never fails for
Inbox capacity. Both ordinary Run retention paths and confirmed deletion
either leave exact live evidence or atomically publish the immutable retired
outcome receipt. Task/Project deletion preview and confirmation must freeze
Run incarnation and evidence state, then recheck them at the final deletion
transaction so a reused ID cannot retire a different Run. Restore preserves
receipts/read state, revokes execution authority as already specified, and
never replays uncertain work.

## Proof and sequence

First validate the actual Run mutation paths and retirement/deletion ordering
against this contract, then implement source identity/receipt/storage and
backup consistency, then the fixed owner item projection and guarded website
detail. Test old schema upgrade, exact Run ID reuse, duplicate/ambiguous
readback, unknown→failed/completed, partial/unfinalized evidence, Stop,
cancel, no-submission interruption, both retention paths, legacy import of
unknown/incomplete/failed/interrupted, duplicate startup,
sync-upsert, retry, Task/Project deletion and ID reuse, full-capacity admission,
restore tampering, two-device read/ack/dismiss races and no adapter call from
Inbox. Run the cross-platform suites and two independent read-only reviews
after each major slice before a full PR. This work does not qualify a runtime
for Project execution and does not turn Conversation Turns into a Task
scheduler. Approval/clarification requests and coordinated Project revision
routing require their own source-bound capabilities before #240 can close.

## Schema 35 review record

Two independent read-only code reviews checked the first Run-identity slice.
The first found no correctness defect. The second found that the original
"attention slot" name overstated its guarantee, that a valid near-48-MiB
database could exceed its old budget after migration, and that unclaimed
backup validation omitted the new table. The implementation now names only
Run identity, admits up to 56 MiB of SQLite within the 96-MiB private-unit
bound, and checks the new table only in schema-35 unclaimed stores. Both
reviewers rechecked the fixes and found no remaining blocker. Focused tests
cover exact schema-34 upgrade/drift, 10,000 maximum-length Run IDs, a
near-limit database, ID reuse, immutability, and orphaned unclaimed data.
Later backup checks found that older schema validators must explicitly retain
versions 33 and 34 after the current version advances. The allowlists now do
so, and a schema-34 private-unit validation and restore test exercises the
upgrade to schema 35.
