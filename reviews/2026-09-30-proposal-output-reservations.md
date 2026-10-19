# Prelaunch proposal output reservations

Status: implemented, independently reviewed and verified; production remains closed.

The real outcome remains producing-Run admission, registered immutable output,
owner intake/Apply and coordinated Task work. This prerequisite closes a real
capacity gap: schema-43 call charges and schema-44 scope charges reserve no
retained blob slot. No alternate output store or non-Apply output path is added.

Schema 45 stores one immutable reservation per exact canonical proposal
Run/generation. The row binds the immutable generation claim, manifest, policy,
historical epoch, one blob slot, policy maximum response bytes, creation time
and a one-time private holder-token hash. Reservation is guarded by the private
lock and BEGIN IMMEDIATE; it requires the current exact dormant proposal graph
and live grant/binding/epoch, and refuses if any scope or inference call already
exists. A repeated exact reservation returns historical receipt without token;
it never creates a new holder or releases the hold. No update/delete API exists.

Reserve 128 KiB of future output/receipt metadata per row. The future parser
snapshot is bounded to 32 KiB canonical UTF-8 JSON; storing that JSON as an
embedded JSON string can escape every byte at most twice, so its charge is at
most 64 KiB plus bounded fixed fields. The remaining 64 KiB is reserved for
the immutable receipt/terminal/attachment representation. Future capture must
prove its exact representation fits this charge before consuming it; no future
migration may silently reinterpret this as sufficient for arbitrary payloads.
The shared metadata validator counts the same fixed charge while pending,
including the reservation's bounded historical metadata. New empty schema-45
roots receive only bounded empty-graph framing, preserving old full roots.

All retained writers count distinct existing retained blobs plus pending slots,
and distinct retained byte sizes plus pending maximum response bytes, against
the existing 100-blob/24-MiB limits. This includes the Project/Task shared graph,
Console file binding and Project context staging. Conversation binding uses
the shared check; copies add no new distinct retained blobs. Delegation files
already pass Console binding before recording their mapping. The hold is
capacity accounting, not a guarantee of disk availability or execution authority.

New scope preparation and broker qualification/debit require the reservation;
scope starting and call submission recheck it. The controller fixture commits
and reads back reservation before preparing/starting the scope. Existing
historical schema-44 claims migrate without invented reservations; they cannot
start a new scope or broker call until explicitly reserving before any work.
Already-recorded old scopes/calls remain historical and cannot be retrofitted.

Private backup validates the exact graph and retains immutable holds. Restore
preserves charges and token hashes, rotates current epoch and never returns a
token or refunds uncertain work. The schema-5 compatible projection omits this
authority and leaves the source unchanged. Active scope archival rejection,
default Run/attention/Inbox refusal and schema-41 SQL source guards remain.
Pending-to-output conversion later must atomically exchange hold for the exact
pinned blob and bounded receipt; release requires separately reviewed evidence,
never a timeout, missing process or restored scope name.

Verification covers shared slot/byte limits, deduplication, all retained writer
paths, original-token secrecy, replay and old-work refusal, grant/epoch fencing,
late validation rollback, concurrent reservations, bounded metadata, populated
backup/restore/schema-5 omission, exact migration/Run inventories and unchanged
dispatch gates. Two independent contract/code reviews and package checks are
required before publishing a full PR.

Both independent contract and code reviews are clear after preserving all
historical schema-44 repository/readback consumers and accepting separately
committed operations on a shared wall-clock tick. Mutation order and committed
readback enforce prelaunch intent; timestamps reject earlier work but are not
transaction-order proof. No active-source or successful-producer allowance was
added. Existing old-schema exact migration and negative metadata tests now name
the current schema/ceiling without reducing their safety assertions.

The final real Linux scope/broker/image/completion/readback/reservation group
passes 155 methods with no skips. Shared writer, Conversation, Task-input,
deliverable, Inbox and migration coverage passes 142 Linux methods. All 14 new
reservation methods pass on Windows and independently in review B; the related
49 Run-input/deliverable/review/Inbox methods pass on Windows. The full historical
private consistency group passes 127 of 128 Linux methods before correcting one
stale schema-16 current-version assertion; the corrected three-method module
passes on Windows and is included in the clean Linux writer run. The equivalent
128-method Windows run has the same stale assertion failure and two POSIX-only
skips; its other 125 executions pass, and the corrected three-method Windows
module passes. These original runs are not recorded as fully green. No remaining
implementation failure was observed; the targeted rerun resolves the changed
assertion without repeating the ten-minute historical Windows backup group.

Fresh wheel/sdist public inventory and RECORD verification pass. Sixteen
authority/readback files match byte for byte across source, wheel, sdist and
isolated installed tree; fifteen root modules import from the installed tree,
which reports schema 45 and packages Next 16.3.6.
