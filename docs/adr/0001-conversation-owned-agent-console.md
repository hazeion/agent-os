# Conversation-owned Agent Console execution

Status: accepted

Mentat will add a durable Conversation authority to its owner-private SQLite
database. A Conversation owns its ordered Messages and user-authored Turns; a
Run remains one immutable execution attempt. This preserves conversational
continuity without turning runtime sessions into product identity, and it
allows compatible Conversations to execute concurrently without introducing a
global scheduler.

This is the decision record for GitHub issue #131 and the Next.js Agent Console
specification. It plans schema 10 and its repository contracts; it does not
change production schema or runtime code.

## Decision

The ownership chain is:

```text
Agent 1 -- * Conversation 1 -- * Message
                    |
                    `-- * Turn 1 -- * Run -- * AgentEvent
```

- A Conversation has one immutable canonical Mentat Agent.
- A Message is durable transcript content, not a runtime event log.
- A Turn is one accepted user request. It may wait, be dispatched once, or
  acquire later Retry or Resume Runs.
- A Run is one execution attempt with an immutable Agent/configuration snapshot.
- AgentEvents remain the detailed Run journal and are projected into transcript
  Messages only through a fixed, idempotent projection.
- A private runtime session or thread is an adapter-owned continuity reference,
  never the Conversation identity.

### Schema-10 authority

Schema 10 is an additive migration of `mentat.sqlite3`. It adds the following
records and extends the existing Run and Agent authorities.

`mentat_conversations` owns:

- an opaque `conv_...` identifier;
- an immutable `agent_id` foreign key;
- a title of at most 160 characters and fixed title-source code;
- `active` or `archived` lifecycle state and an optional archive timestamp;
- a monotonic record revision;
- private next-message and next-turn sequence counters;
- created, updated, and last-activity timestamps.

The Conversation revision is the compare-and-swap boundary for metadata and
lifecycle changes. Message and Turn appends allocate their sequence values in a
transaction and do not require a browser to race live activity with a volatile
Conversation revision. Changing the Agent creates a new Conversation.

`mentat_conversation_messages` owns:

- an opaque `msg_...` identifier and Conversation foreign key;
- a per-Conversation monotonic sequence with a unique composite index;
- role `user` or `assistant`;
- state `accepted` or `cancelled`;
- versioned content JSON of at most 64 KiB and its byte count;
- an optional Run foreign key with `ON DELETE SET NULL`;
- a monotonic revision, immutable source key, and created/updated timestamps.

The initial content schema supports text. User text is at most 6,000 characters
and any one assistant text block is at most 20,000 characters. Later code,
image, artifact, and link-preview parts extend the versioned content schema; they
do not bypass content, storage, or browser-projection limits. An optimistic
user bubble is browser-local until Send is accepted and is not a third durable
Message state.

`mentat_conversation_turns` owns:

- an opaque `turn_...` identifier and Conversation foreign key;
- exactly one user Message through a unique foreign key;
- a monotonic queue ordinal unique within the Conversation;
- state `pending`, `dispatching`, `consumed`, `blocked`, or `cancelled`;
- an optional blocked-reason code of at most 64 characters from a fixed
  allowlist;
- the latest Run foreign key with `ON DELETE SET NULL`;
- a monotonic revision and attempt count;
- a unique Send idempotency-key digest and immutable request digest;
- created and updated timestamps.

Turn text is stored once in its user Message. A queued edit updates that Message
and the Turn under their expected revisions while the Turn is `pending` or
`blocked`. Cancellation is a durable state transition. `pending`, `blocked`,
and `dispatching` are queue-active states; SQLite triggers and repository checks
reject a ninth queue-active Turn for one Conversation. Queue ordinals are never
reused and gaps from cancellation are valid.

The current Agent tables gain monotonic revisions. `mentat_agents` also gains an
optional `system_role` with a unique partial index permitting at most one
`direct` Agent. Direct mode is therefore a canonical Agent with its own unique,
validated RuntimeConfig. Migration does not fabricate, alias, or share a
runtime binding. The Slice-1 bootstrap is idempotent: it designates or creates a
Direct Agent only when a supported unclaimed binding can be validated;
otherwise Direct mode is visibly setup-required.

Conversation-source rows in `mentat_runs` retain `source = 'console'` and gain:

- nullable Conversation and Turn foreign keys;
- nullable `retry_of_run_id` and `resume_of_run_id` links, both using
  `ON DELETE SET NULL`;
- Agent and RuntimeConfig revisions;
- a private execution-configuration JSON snapshot of at most 16 KiB and its
  digest;
- a private capacity-scope digest and admitted capacity limit.

New Next.js Console Runs always have a Conversation and Turn. Existing
compatibility Console Runs remain valid with both fields null, and Task-dispatch
Runs keep their current Task identity, dispatch-head, and idempotency behavior.
No legacy Run or Console-history entry is inferred into a Conversation because
the required identity and ordering evidence does not exist.

A unique partial index rejects more than one Run for a Conversation in any of
the existing nonterminal states: `reserved`, `queued`, `submitting`, `starting`,
`running`, `cancelling`, `waiting`, `waiting_for_approval`,
`waiting_for_clarification`, or `unknown`. Database triggers reject changes to
Conversation/Turn identity and execution-snapshot columns after Run insertion.
Repository validation repeats these checks and verifies all foreign-key and
sequence relationships.

### Send and message projection

Send uses a caller-generated opaque idempotency key. Mentat stores only its
digest. The request digest binds the Conversation, Agent, user content, and
expected queued-message revision where applicable. Repeating the same key and
request returns the original canonical result; reusing the key with different
input fails closed. The evidence remains for the lifetime of the Turn.

Under `private_state_lock` and `BEGIN IMMEDIATE`, an accepted Send:

1. validates the Conversation, immutable Agent ownership, content, queue cap,
   runtime capability, and safe current Agent configuration;
2. appends the user Message and Turn with the next canonical sequences;
3. when no nonterminal Run exists and capacity is available, creates a
   `reserved` Run, captures its immutable execution snapshot, changes the Turn
   to `dispatching`, and binds its latest Run;
4. when another Run owns the Conversation, leaves the Turn `pending`;
5. when runtime capacity is unavailable, leaves the Turn `blocked` with reason
   `capacity`, creates no Run, and projects `Waiting for capacity`;
6. commits before any adapter call.

The runtime-neutral orchestration layer claims and performs at most one external
submission attempt after all SQLite and private-state locks are released. Its
result is reconciled under a new short transaction. A rejected or ambiguous
attempt is durable and is never retried automatically.

For a new Conversation Run, appending a normalized `message` AgentEvent and
projecting its safe assistant content into a Conversation Message occur in the
same SQLite transaction. The Message source key is derived from the exact Run
and AgentEvent source key, so replay returns the existing Message. Raw provider
payloads, tool arguments/results, paths, credentials, private runtime references,
and private reasoning are never transcript authority.

### Queue continuation is not scheduling

After a verified successful terminal transition, the same repository operation
may claim only the oldest queue-active Turn in that Conversation. It revalidates
the current Agent configuration and runtime capacity, then creates one new Run
reservation. The adapter call again occurs outside the transaction.

Stop, failure, interruption, unknown or partial outcomes pause continuation by
marking the oldest pending Turn `blocked` with a fixed reason. Capacity failure
does the same. The operator must explicitly continue that Conversation after
the blocking condition is resolved. Pending Turns behind the blocked head stay
FIFO.

This mechanism has no timer, due date, recurrence, priority routing,
cross-Conversation or cross-Agent selection, automatic retry, Task mutation, or
Agent Message consumption. It cannot dispatch work unless an accepted Send or
a verified success transition is already operating on that exact Conversation.
Tasks remain the durable planning/delegation authority and Agent Messages remain
communication, not an execution queue.

### Adapter capacity

On an explicit dispatch path, a runtime adapter returns a trusted private
capacity scope and an integer limit from 1 through 32. Missing, invalid, or
unknown declarations fail to the conservative limit of one. Mentat hashes the
scope and stores only the digest and admitted limit on the Run.

Run admission counts all nonterminal Runs with the same scope digest inside the
same `BEGIN IMMEDIATE` transaction. Approval, clarification, cancellation, and
unknown states continue to consume capacity until reconciled terminal. The
browser receives only bounded availability and `Waiting for capacity`
projections; it never receives the scope, hash, runtime reference, or adapter
identity material. Compatibility adapters may remain serial while their limits
are one, but that is not a product-wide Run lock.

### Configuration snapshots

The Run snapshot binds the canonical Agent ID and revision, RuntimeConfig ID and
revision, runtime type, binding digest, declared capabilities, safe
provider/model/effort selection, and capacity admission. Snapshot fields are
immutable after reservation. Credentials and adapter-owned runtime references
are not copied into the JSON snapshot and are never browser-visible.

Composer configuration changes complete the existing safe Agent configuration
workflow before a later Run is admitted. A pending Turn does not freeze a model
at typing time; it receives the selected Agent's then-current validated
configuration when its Run is reserved. An active Run never changes.

### Retry, Resume, and restart recovery

Retry is an explicit action on a terminal Run. It creates a new Run for the same
Turn with a fresh configuration snapshot and a `retry_of_run_id` link. The old
Run and its events remain evidence under normal Run/Event retention. A Turn
blocked before admission uses the separate explicit Continue action because no
prior Run exists to retry.

Resume is exposed only when the selected adapter advertises a fixed resumable
capability and can revalidate the exact private continuity identity. It also
creates a new Run, links `resume_of_run_id`, and never turns a private runtime
session into Conversation identity.

Startup reconciles every nonterminal Conversation Run before presenting it as
live. A durable accepted runtime reference is read through its adapter. A
reservation with no external attempt becomes `interrupted`; an in-flight
submission with no authoritative outcome becomes `unknown`; neither is
automatically retried. A freshly verified success may perform the same atomic
oldest-Turn continuation described above. Persisted Messages and Turns render
while reconciliation is pending, but controls fail closed when current Run
identity is uncertain.

### Retention, projections, and recovery media

Conversation history is private and durable. Archive is reversible and does
not free authority. Until separately approved deletion exists, Mentat does not
silently prune accepted Conversations, Messages, or Turns. Admission uses these
initial hard bounds:

- 1,024 Conversations;
- 10,000 Conversation Messages;
- 10,000 Conversation Turns;
- 12 MiB of total encoded Message content;
- eight queue-active Turns per Conversation;
- the existing 48 MiB database-admission budget across old and new authorities,
  beneath the 64 MiB private database backup ceiling.

Cross-row totals are checked under `BEGIN IMMEDIATE`; startup semantic
validation rechecks them. Reaching a bound returns a typed history-capacity
error and does not delete older work. Transcript and Conversation APIs are
paged with a maximum of 100 records. The Agent activity rail is a bounded,
status-oriented projection rather than a second transcript.

Browser projections contain Mentat IDs, safe names and labels, revisions,
timestamps, lifecycle codes, bounded content, and declared safe capabilities.
They omit runtime configuration IDs, runtime references, capacity scopes and
digests, content hashes, credential metadata or values, local paths, storage
keys, and raw adapter payloads.

Format-4 backups already embed the complete private SQLite database, so schema
10 does not require a new archive format. Backup capture, restore staging,
schema fingerprints, semantic validators, and consistency-unit digests must be
made schema-10 aware in the implementing slice. Existing format-2, format-3,
and pre-schema-10 format-4 backups restore through their current contracts and
then migrate forward. A schema-10 backup is accepted only by a schema-10-aware
build.

The schema-5 compatible-root export intentionally omits Conversations,
Messages, Turns, Direct-Agent designation, Agent revisions, and Conversation
Run extensions. It leaves the schema-10 source unchanged and warns that this is
a lossy downgrade view. A lossless rollback uses a validated pre-migration
format-4 backup while Mentat is stopped. There is no in-place schema downgrade
and no fallback to legacy Console history after migration.

The migration creates empty Conversation tables and adds nullable Run extension
columns in one transaction. Existing Agent and RuntimeConfig rows receive
revision 1 and no system role; existing Runs receive null Conversation
extensions. The migration does not need an authority receipt because there is
no prior competing Conversation store. Existing Task-dispatch Runs, legacy
Console Runs, AgentEvents, reservations, dispatch heads, and authority receipts
must validate unchanged before the migration commits.

## Considered options

### Use a Run as the Conversation

Rejected. It makes Retry overwrite or fork product identity, loses a stable
transcript after Run retention, and cannot represent queued follow-ups cleanly.

### Use the runtime session or thread as the Conversation

Rejected. It leaks adapter identity into the product model, makes provider
changes and cross-runtime behavior inconsistent, and weakens Mentat's authority
boundary.

### Keep Messages and the queue in browser storage

Rejected. Refresh, another browser tab, server restart, reconciliation, and
idempotent Send would disagree about accepted work.

### Add a global queue or scheduler

Rejected. Mentat already has Task planning and capability-scoped delegation.
A global scheduler would conflate conversational follow-up with durable planned
work and would broaden authority far beyond the Console.

### Preserve the legacy product-wide Run lock

Rejected. It prevents the accepted multi-Agent workflow. Capacity belongs to
the adapter scope, while Conversation identity supplies the isolation boundary.

## Consequences

- Conversation persistence survives Run/Event retention and runtime changes.
- Concurrent work becomes possible only where the adapter declares capacity;
  compatibility runtimes may remain serial without constraining other scopes.
- Message projection and Send admission become part of the Run repository's
  transactional correctness surface and require race, replay, restart, and
  backup tests.
- Agent and RuntimeConfig revisions become durable because a Run must prove
  exactly what configuration it used.
- The first implementation slice must establish schema, Direct-Agent identity,
  read projections, and migration/backup validation before writable dispatch is
  enabled.
- The interactive-state prototype may model this contract but cannot replace
  any of its durable authority with client state.
