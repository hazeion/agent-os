# Mentat architecture and capability contract

## What Mentat is

Mentat is a local operations console for planning work and running agents. It
owns Agent, Task, Run, event, and provider-connection records. Hermes, a
signed-in local Codex CLI, and optional Vercel services execute work through
separate capability-scoped adapters.

The migration keeps the current Python app working while new parts are added.
Python owns local data, runtime access, and the existing safety checks. New
runtimes must use small, named capabilities instead of direct access to runtime
files.

Mentat may read supported Hermes state. It may change Hermes only through an
approved adapter operation. It must never edit Hermes core files directly.

## Current local layout

The Next.js dashboard is the default product on the configured local port
(8888 by default). The Python `public/` interface remains available only with
the explicit `--legacy-ui` rollback switch. Both listen only on loopback.

```text
Browser
  -> Node gateway on 127.0.0.1:8888
  -> fixed same-origin API route
  -> private Python Local Bridge
  -> Mentat data and Hermes adapters
```

Node is the only browser-facing process. Python remains the
authority for SQLite, files, credentials, Hermes, Tasks, Runs, and Agents.

## Node gateway boundary

The gateway requires Node `>=24.19.0 <25`. Build `web/` before launching from
source:

```bash
npm --prefix web ci --ignore-scripts
npm --prefix web run build
./run.sh
```

The launcher supervisor creates a private token, starts the Python bridge on an
ephemeral loopback port, waits for `/bridge/v1/health`, and then starts Node.
The token stays in child process environments. It does not appear in command
arguments, logs, browser responses, or saved data.

The bridge accepts only its exact Host and port, a loopback client, and one
constant-time token match. Browser Origin, Cookie, and `Sec-Fetch-Site` headers
are rejected. The bridge has no catch-all route, generic proxy, state mutation,
SQLite access, or direct Hermes access.

The Node request boundary covers every public path, including framework
assets. It accepts only the configured loopback Host and port. Cross-site,
mismatched-origin, and malformed fetch metadata requests fail closed.

The browser can call fixed same-origin routes only: `/api/bridge/health`, the
read-only `/api/agents`, `/api/provider-connections`, `/api/tasks`, `/api/runs`,
and selected-Run timeline route. Node builds each private request on the
server, checks its bounded response, and returns only the route's safe public
fields. The Agent route exposes canonical Mentat IDs, names, runtime types,
runtime configuration IDs, and declared capabilities. It
never exposes adapter-owned runtime references, credentials, paths, raw Hermes
data, or legacy heartbeat observations. Browser input cannot choose a bridge
path, target, headers, or token.

The Task route reads canonical SQLite Tasks only. It exposes IDs, titles,
projects, statuses, priorities, due dates, tags, attention/review flags, and
timestamps. Descriptions, notes, attachments, delegation, planning fields,
and other private Task details stay behind Python.

The Run route reads canonical SQLite Runs only. It exposes IDs, source, linked
Task and Agent IDs, runtime type, status, dispatch state, partial and timeline
truncation flags, and lifecycle timestamps. Runtime references, revisions,
event counters, event contents, attachments, task snapshots, and adapter data
stay behind Python.

The Runs workspace returns at most 50 records, with every retained active Run
ahead of newer terminal history. It may add a display name from the canonical
Agent Registry only when both Mentat Agent ID and runtime type match the Run.
Unavailable, malformed, missing, or mismatched Agent data leaves the Run
visible under a safe ID label and does not change its status, runtime, or
controls. Legacy `data/agents.json` observations are never used for this join.

The selected-Run timeline is one bounded same-origin SSE stream. Node validates
the Run ID and browser reconnect cursor, polls one fixed authenticated bridge
capability, emits a keepalive, and regularly closes so the browser reconnects.
It returns at most 100 retained normalized events: ID, Run ID, sequence, type,
timestamp, summary, and approved numeric usage metrics. It sends an explicit
reset when history is missing or shortened. Event content, data payloads,
runtime references, and browser-selected limits or bridge paths never cross
this boundary. Only one timeline is active in the Runs workspace at a time.

The selected-Run Stop flow is one separate fixed preview-confirm action. Node
accepts only the selected Run ID and a state-bound confirmation token, while
Python checks the active task-bound Run, Agent and runtime binding, declared
`run.stop` capability, and current state under the shared runtime operation
lock. It reads the canonical Run again before returning a requested result.
The browser never selects an adapter reference, action name, or bridge target.

The selected-Run message flow is a separate fixed preview-confirm action. Node
accepts only the selected Run ID, one text-only message of at most 6,000
Unicode code points, and its state-bound confirmation. Python validates the active
task-bound Run, Agent and runtime binding, declared `run.message` capability,
normalized message digest, and current state under the operation lock. It
checks the runtime state after the supported message operation before returning
an accepted result. Message and response readback must match the exact canonical
Run, Task, Agent, and runtime identity; a mismatch is a partial failure. A
changed message or Run requires a new preview. Approval and clarification
responses use their own bounded preview-confirm contracts.

The first shell is prerendered and has no React hydration runtime. One fixed
local script reads the health route after first paint. Later routes may add
client code when they need real interaction, but each route must keep its own
performance budget.

The performance gate uses Lighthouse 13.4.1 and Chrome for Testing
152.0.7923.0. It runs three desktop audits and three mobile audits. Every
category must score 100. Each audit gets a fresh browser and profile. Timeouts
and signals clean up Lighthouse, Chrome, and temporary files.

The supervisor watches Node and Python. If either process exits, it stops the
other one within a bounded timeout. The browser gateway stops first during a
normal shutdown. The web package has no production `npm start` shortcut because
the supervisor must own both processes.

## Identity model

- A Mentat **Agent** is the target canonical worker identity.
- A runtime identity, such as a Hermes profile, is an adapter-owned execution
  reference and must not become a Mentat Agent ID.
- During the compatibility phase, the legacy browser `agent_id` field still
  carries a Hermes profile ID. New orchestration code must not copy that alias
  into the canonical Agent model.
- A Mentat **heartbeat agent** remains an observation about a running or
  recently completed process. Records in `data/agents.json` are not the new
  canonical Agent registry.
- Canonical Mentat Agents and their one-to-one adapter runtime configurations
  are persisted in schema-9 owner-private `mentat.sqlite3`. The runtime
  configuration retains the private runtime-owned Agent reference; ordinary
  browser projections omit that reference and expose only Mentat identity,
  runtime type/config identity, and declared capabilities. The local registry
  is transactionally capped at 128 Agents so create/list responses and private
  recovery remain bounded.
- Existing roots converge only through `mentat agent-registry-migration`.
  Preview performs no write and binds the exact standalone source and Mentat
  database state. Confirmation refuses an active server, creates or verifies a
  format-3 backup, revalidates both sides under the durable mutation lock, and
  commits Agent/config rows with the singleton authority receipt in one
  transaction. After that receipt exists, the old `agent-registry.sqlite3` is
  ignored and never updated or used as fallback authority.
- The registry does not auto-import or mutate Hermes profiles, store
  credentials, edit/delete Agents, or replace heartbeat observations.
- A Hermes **session** remains conversation history owned by a specific Hermes
  profile and is a runtime reference, not Mentat workflow authority.
- Durable Agent persistence remains additive without inventing profile-derived IDs.

## Optional Vercel boundary

Schema 9 adds one private, versioned Vercel connection record. It stores only
validated settings and the credential-source kind. Credential values stay in
operator environment variables and never enter SQLite, backups, logs, Node, or
browser responses. The browser receives only the connection label, model,
safe state, and declared capability states.

Vercel is not required to start or use Mentat. Configuration, readiness tests,
Agent creation, and disconnect are stopped-server CLI operations with exact
preview and confirmation. Browser Agent creation cannot select a Vercel
binding.

The AI Gateway runtime makes one bounded request to its fixed HTTPS endpoint
and stores only normalized Mentat Run, message, and token-usage evidence.
Only the bounded Gateway result message may cross the Run-event bridge; raw
provider payloads and runtime references remain private. Ambiguous transport
or provider results become `unknown` and are not retried. The stopped-server
`mentat vercel recover-run` flow can explicitly mark one exact unknown Vercel
submission interrupted. Its preview and confirmation bind the connection,
Run revision, and data-root identity, and never resend the request.
The Sandbox adapter can run only one fixed Node 24 readiness probe in a
non-persistent, time-limited sandbox through Vercel's fixed
`https://api.vercel.com/v2/sandboxes` runtime route. Every HTTPS operation has
one total wall-clock deadline, and a
created session is successful only after cleanup reports that exact session as
stopped. The
Connect adapter requests one configured app-scoped token, validates it, and
immediately discards it. Neither adapter accepts arbitrary browser commands,
hosts, headers, scopes, or tokens.

The read-only browser state deliberately distinguishes configuration from a
live probe: `configured` and `credential_present` report validated local
configuration only. Only an explicit confirmed CLI test may report `ready`.

Format-4 backup and restore treat provider settings and their bound Agents as
one schema-9 consistency unit. The schema-5 compatible-root export omits the
provider table and Vercel Agents so an older build never opens schema 9 or sees
an unsupported runtime binding.

## Data ownership and layout

The canonical durable-data inventory, platform defaults, target directory
classes, initialization rules, migration/backup contract, and secret exclusions
live in [DATA_LAYOUT.md](DATA_LAYOUT.md). Milestone 1A defines that target,
while Milestone 1B implements deterministic resolution, bounded read-only
preflight, owner-only directory creation, and locked missing-only seed copying.
Milestone 1C adds explicit, backed-up, locked migration of the fixed legacy
durable-JSON inventory with source preservation, interruption-safe reservation,
and verified completion receipt. Milestone 1D adds a sidecar schema manifest,
backed-up version-0 bootstrap, read-only pre-write schema gating, clean-install
provenance, exact temporary reconciliation, process-reentrant shared-lock
coordination with ordinary durable JSON writes, and forward-version refusal
without changing consumer-visible JSON shapes. Both ordinary writers and schema
recovery preserve the configured no-follow root spelling and keep validation
and mutation on the same pinned filesystem objects. Terminal success is bound
to root identity and exact durable bytes, and ordinary writers preserve the
same schema size/type/file-object invariants. Milestone 1E-A adds a fixed,
versioned backup and preview-confirm restore boundary for the nine
schema-governed durable JSON documents. Backup snapshots share the pinned root
lock with normal mutations. Restore binds exact archive and target state,
publishes pre-restore recovery evidence and a reservation before atomic document
commits, resumes only exact old/new interruption state, and blocks startup while
incomplete. Already-running dashboard JSON reads and writes share that lock and
fail closed while a reservation or restore recovery temporary exists. It
preserves the destination's schema provenance and every excluded class.
Milestone 1E-B moves retained Console history, SQLite metadata, and
content-addressed blobs to owner-only `<data-root>/private/console/`. A shared
private-state lock coordinates history and attachment mutation, reconciliation,
migration, backup, and restore. Version-2 backups add a WAL-safe filtered
SQLite snapshot, canonical retained history, and only referenced ready blobs;
version-1 JSON-only restores remain supported and leave private state intact.
Milestone 1F treats the installed application tree as replaceable and the data
root as operator-owned. Integration coverage replaces immutable application
trees whose seeds differ, requires a verified pre-upgrade backup, removes only
the application tree, and reconnects a reinstall to the unchanged durable JSON
and retained private Console consistency unit. Installer mechanics remain a
separate Milestone 3 boundary.
Milestone 2A adds one versioned owner-only remote-connection record below
`<data-root>/private/`, exact state-bound preview/confirmation, binding rotation
when authority changes, and a fixed-path server-only health/capability client.
The stored credential and endpoint remain excluded from ordinary backup and
are never returned from stored state or upstream responses; only the
operator-supplied setup request, a public label, opaque binding, and minimized
trusted discovery state may cross the browser boundary.
Milestone 2E extends that fixed authenticated boundary with read-only remote
session list, detail, and message operations. Upstream session IDs remain
process-private behind random connection-bound aliases; browser payloads carry
only bounded public metadata and user/assistant replay text. Hermes branch
and compression projection is consumed at the list boundary; projected
transcripts are labeled as partial because Hermes does not return ancestor
turns, and any later message-identity change fails closed. Remote continuation
is enabled only when the maintained runtime advertises the exact stoppable,
revision-bound capability.
Milestone 2F adds one-use, process-private remote Context Pack grants. A grant
binds the selected connection, current pack revision, and exact staged text
snapshot ids; Mentat sends only bounded UTF-8 text with generic context labels.
Local paths, filenames, blob metadata, and storage identities never enter the
upstream request. Direct files and artifacts fail before submission. Images
also fail clearly because Hermes currently documents them on chat/responses,
not on the stoppable Runs lifecycle used by Agent Console.
Milestone 2G adds fixed authenticated reads for the advertised remote skills
and toolsets endpoints. The Settings payload is read-only, connection-bound,
bounded, path-free, and allowlisted to skill/toolset identifiers, enabled state,
and tool counts. It never includes raw responses, descriptions, categories,
labels, skill contents, tool names, configured-provider details, or partial
results.
Milestone 2H adds bounded remote message search over the same 12 recent session
projections used by the Sessions view. Mentat reads every visible user/assistant
message in that window through the exact authenticated message endpoint, returns
at most 20 bounded snippets behind connection-bound aliases, and discards the
whole search if any envelope, schema, pagination, binding, transport, or final
connection check fails. Individual messages that fail the browser-visible
privacy classifier are omitted only from search after the complete response
envelope and binding validate; the browser receives bounded filtered-message
and affected-session counts, never the content or reason. The browser is told
when the 12-session limit was reached and older sessions may not be included,
or when filtered messages, compacted ancestor turns, or additional matches were
omitted; Mentat does not claim complete-history search. Strict transcript reads
remain fail-closed.
Milestone 2I makes diagnostics transport-aware. Local mode retains the existing
Hermes file/runtime checks. Remote mode replaces them with one authenticated,
bounded readiness summary and fixed failure categories; it does not return the
endpoint, credential, binding ID, local Hermes paths, or raw upstream details.
Remote browser-visible session titles, previews, and message text fail closed
when they contain path-shaped slash/backslash tokens or credential-shaped
assignments. Ordinary web URLs, numeric dates/fractions, and `A/B` abbreviations
remain readable. URL exceptions require a syntactically public host, no user
credentials, canonical global-unicast IP or valid public DNS syntax, no raw or
encoded backslash, and only the same safe slash tokens in query/fragment values.
Special-use DNS suffixes and nested/adjacent URL-path hybrids are rejected;
Markdown, backtick, and emphasis wrappers are parsed outside the URL span.
Supported structured messages contribute only bounded allowlisted text parts;
image, tool, and reasoning content is omitted.

### SQLite Task persistence transition

Pivot Slice 1C-A advanced the existing owner-private Console database to schema
5 and added canonical `mentat_tasks`, ordered tag, and ordered dependency tables.
Scalar planning fields are indexed columns; bounded nested planning/delegation
objects and safe unknown compatibility fields are stored once in separate JSON
columns. Internal monotonically increasing revisions provide compare-and-swap
replacement semantics, while deferred foreign keys and collection validation
reject missing, self-referential, or cyclic dependencies.

Pivot Slice 1C-B advances that database to schema 6 with an exact singleton
Task-authority receipt. After acquiring its exclusive server reservation and
before opening a listener, Mentat takes the shared private-state lock, validates
the exact bounded `tasks.json` bytes and
identity, requires an empty repository, imports and reconstructs the collection,
and commits both Tasks and the receipt in one immediate transaction. Sparse
historical Tasks receive deterministic canonical defaults; duplicate IDs,
invalid dependency graphs, unsafe metadata, source drift, occupied destinations,
and partial writes fail closed.

Once the receipt exists, every live Task workflow, including delegation
reservations, calendar links, search, recurrence, attachment reconciliation,
and webhook-triggered refresh, reads and mutates SQLite. The centralized list
mutator adapter preserves public payloads and order while maintaining internal
monotonic revisions. A zero-Task receipt is authoritative. Runtime code never
reads, writes, shadows, or falls back to stale `tasks.json` after cutover.

Slice 1C-D makes that boundary explicit in the server call graph: live
workflows use dedicated SQLite Task snapshot and mutation helpers, while the
generic JSON helpers retain only a compatibility shim for older callers and
tests. `tasks.json` is not in the generic project-owned write allowlist. Its
remaining references are limited to packaged seed, migration, explicit offline
export/downgrade, backup compatibility, or documented recovery behavior.

The operator command `mentat task-migration` remains read-only. Before cutover
it validates and binds the exact source bytes/file identity and destination
schema/occupancy without creating a database or sidecar. After cutover it
reports existing SQLite authority without consulting stale JSON. Deterministic
export is an explicit offline recovery action, not another runtime authority.
`mentat task-export` first previews a token bound to the authoritative export
and current `tasks.json` identity; confirmation refuses an active server,
revalidates both states, atomically replaces only `tasks.json`, and verifies the
published bytes. This Task-only form is a recovery artifact, not a complete old
build environment. `mentat task-export --compatible-root` instead creates a
new validated sibling data root containing current durable documents, exported
Tasks, retained Console/attachment/blob state, the Agent registry, and an exact
schema-5 copy of the Console database with empty Task tables. Exported
`tasks.json` is therefore the sibling's sole Task authority, so changes made by
the old build import exactly if that sibling is later upgraded. The schema-9
source root stays unchanged.

Remote Hermes selection is separate private state and its credential is not a
downgrade artifact. Compatible-root preview and confirmation therefore fail
closed while the source is actively in remote mode. The operator must
deliberately switch the stopped source to local mode, create the sibling, and
configure remote Hermes in the old build before it performs any operation.
Missing, interrupted, malformed, or unavailable private state must produce a
bounded Task-export error rather than a traceback.
Canonical export bytes are published and verified exactly, without adding or
stripping an optional trailing newline, so both the digest and accepted
maximum-size repository identify the actual old-build document. Compatible
publication synchronizes populated staged directories bottom-up, the complete
stage root, and the pinned parent after its exclusive POSIX rename. Windows
uses missing-only `MoveFileExW` with `MOVEFILE_WRITE_THROUGH`. A durability
failure after publication is a partial write, never a no-write result or
success.

Released format-2 and format-3 backups with exact Console schemas 4 through 7
remain valid. Restored pre-convergence Agent state must complete the explicit
registry migration before normal startup. Current format-4 backups retain
Agents, Tasks, Runs, AgentEvents, dispatch state, and all authority receipts as one
recovery unit. To downgrade after live Task
mutations, stop Mentat, preview `mentat task-export --compatible-root`, confirm
its exact token, and point the older build at the reported schema-5 sibling
data-root name. Restoring a pre-cutover backup remains an alternative that
discards later Task mutations. Mentat never uses stale `tasks.json`
automatically and never downgrades the authoritative schema-9 source database.

### SQLite Run and AgentEvent authority

Pivot Slice 1C-C advances the same owner-private database to schema 7. SQLite
is authoritative for both compatibility Console Runs and runtime-neutral Task
dispatch Runs. `mentat_runs` stores immutable Task/Agent/runtime-binding
snapshots plus independently revisioned execution and submission state;
`mentat_agent_events` is an append-only, per-Run monotonic journal.
`mentat_dispatch_reservations` commits exact intent before an adapter call,
while `mentat_task_dispatch_heads` survives Run retention and prevents a Task
revision from being dispatched twice under a new idempotency key.

Dispatch preallocates the Mentat Run and dispatch IDs, commits the reservation,
then releases every SQLite/private-state lock before making at most one runtime
submission attempt. Claiming that attempt atomically revalidates the current
Task revision and assigned Agent. Accepted outcomes must match the complete
Mentat Run, Task, Agent, and runtime identity, and compare-and-swap updates may
not regress a Run already advanced by a worker. Rejected and ambiguous outcomes
are durable. An ambiguous attempt becomes `unknown` and is never automatically
resubmitted. A restart rejects a reservation that never reached an adapter and
marks an in-flight submission unknown without retrying it. Reconciliation uses
short compare-and-swap leases, revalidates the canonical Agent Registry binding,
performs runtime reads outside database transactions, and commits only
identity-matching, forward-only status and normalized events. Webhooks may wake
this readback; their payloads never prove Run state.

The durable Task snapshot is the bounded execution contract actually delivered
to a runtime: identity, title/objective, status, assignment, required
capabilities, and acceptance criteria. It is not a duplicate of unrelated planning
metadata. Canonical Task identifiers retain the Task repository's 160-character
`[A-Za-z0-9_.:@-]` contract across runtime contexts and Run persistence; Run,
Agent, runtime, dispatch, and normalized event identifiers keep their narrower
128-character domains. Run admission transactionally preserves the active/newest-terminal
retention contract, rejects capacity before an external attempt, and keeps the
compact SQLite store below the private-backup database ceiling. Exact
idempotency retries resolve the durable reservation before consulting mutable
Task or Agent state; a different revision cannot start while an older Run for
that Task remains active or unknown.

The transitional Hermes Console bridge reuses the preallocated Mentat Run ID
but keeps dispatch and runtime correlation private. Mentat will not build a new
bridge-specific durable restart subsystem: after restart, accepted bridge work
that cannot be authoritatively reattached becomes `unknown`, remains visible,
and is not retried; a direct legacy Console Run becomes `interrupted`. Native
Hermes adapters may persist a private runtime Run reference and remain eligible
for reconciliation behind the same runtime-neutral contract. If a post-start
compatibility projection cannot be committed to SQLite, the bridge reloads the
last authoritative snapshot, disables new work and controls, and requires a
restart after storage is corrected; it does not maintain a second recovery
engine for volatile bridge state.

Run retention keeps every active/waiting Run and the newest 250 terminal Runs.
When a terminal Run ages out before its idempotency window, its accepted/rejected
reservation remains as a validated tombstone tied to that Task's same-or-newer
dispatch head; it never authorizes resubmission and expires through normal
bounded cleanup. Run, reservation, and dispatch-head timestamps and identifiers
are semantically reconstructed, including monotonic created/updated chronology.
Attachment binding transactionally limits the retained graph to 100 distinct
ready blobs and 24 MiB of referenced blob bytes. Existing over-limit roots fail
closed on further binding. Together with the 48 MiB SQLite budget and bounded
history/registry members, this keeps every admitted retained state within the
96 MiB private-backup unit ceiling.
Event retention keeps contiguous newest suffixes under per-Run and global count
and content budgets and records explicit replay-gap metadata. A private durable
runtime-event cursor survives retained-event deletion, so old runtime events
cannot reappear and a long source timeline is consumed in bounded pages.
Schema startup verifies the exact Run/Event/dispatch table and index
fingerprint, and semantic validation rechecks retention and relationship
invariants. Legacy authority import performs that complete validation inside
the same transaction as its authority receipt, so invalid event identity or
semantics cannot leave a committed cutover. Public version-1 Run/Event APIs expose only bounded domain fields
and numeric usage metrics;
runtime references, binding digests, raw adapter payloads, tool arguments and
results, paths, credentials, and private reasoning remain server-side. The
legacy Console-history JSON file is migration/export compatibility evidence
only after the Run-authority receipt exists; backup derives that representation
and attachment reachability from SQLite. That compatibility member is bounded
independently, contains Console-source Runs only, and may omit old event detail
or older Runs without pruning canonical SQLite task-dispatch Runs, events, or
referenced attachments. Once schema-7 authority exists, stale, missing, linked,
or malformed legacy JSON is not opened during backup. A schema-5 compatible
export separately filters attachments and blobs to the Runs its legacy
projection retains. Startup performs one bounded reconciliation pass for native
Runs that have a durable runtime reference.

### Conversation authority, live Turns, and bounded concurrency

[ADR 0001](docs/adr/0001-conversation-owned-agent-console.md) fixes the target
Next.js Agent Console persistence and concurrency contract. Schema 10 owns
durable Conversation Messages and Turns in the owner-private SQLite authority
and extends Console-source Runs with Conversation/Turn identity, Agent and
RuntimeConfig revisions, immutable execution-configuration evidence, and
private adapter-capacity evidence. Schema 11 retains each Turn's bounded
submission result after full Run-detail retention expires, preserving exact
idempotent replay without keeping unbounded Run history. Legacy Console Runs
remain unbound compatibility evidence.

The first write slice accepts one bounded text Turn only while its Conversation
is idle. Under one immediate transaction it appends the user Message and Turn,
reserves the canonical Run, records the opaque Send-key digest and immutable
request/configuration evidence, and admits the conservative private runtime
capacity before any adapter call. The runtime-neutral service claims exactly
one attempt, releases all SQLite/private-state locks, invokes the adapter once,
then durably records accepted, rejected, or unknown. Exact replay returns the
same authority; changed input with the same key fails closed. Restart marks an
unattempted reservation interrupted and a claimed uncertain attempt unknown.
An accepted Run without a durable runtime reference also becomes unknown; an
accepted Run with an exact durable reference is eligible only for status
readback. After binding but before publishing health readiness or serving any
request, the Next.js private bridge synchronously classifies pre-start crash
states under the private-state lock and fails startup if that classification
cannot complete. Only the slower exact-reference readback runs in the
background afterward. Neither phase repeats a submission.

The pre-submission execution document records immutable Mentat selection policy
and its digest. After a runtime accepts, the repository may add exactly one
separate runtime-execution identity and digest from the verified adapter
response (for Codex, the safe model, provider, and reasoning-effort selection).
SQLite and repository guards reject replacement or partial writes, and neither
document is projected to the browser.

The implemented invariant is one nonterminal Run per Conversation, not one Run
for the product. Runtime adapters may declare a typed private capacity scope and
a bounded limit. Missing, invalid, or unavailable declarations collapse to one
binding-derived slot. The qualified Codex adapter declares two slots for its
one owned App Server and workspace; all nonterminal Task and Conversation Runs
using that scope consume the same transactional capacity. Capacity scope,
digest, limit, and runtime references remain private.

The Home Agent picker selects the immutable Agent binding for a new
Conversation. Changing the picker does not retarget an existing Conversation;
the operator creates another Conversation and switches between the resulting
tabs. Each tab keeps its own draft, transcript, queue, selected Run, stream, and
control target.

An ordinary Send during an active Run appends a durable user Message and Turn
without starting another Run. Each Conversation admits at most eight
`pending`, `blocked`, or transient `dispatching` Turns. FIFO ordinals are never
reused. Pending and blocked Turns may be edited or cancelled only with both the
exact Turn revision and exact user-Message revision; cancellation retires the
ordinal and keeps the cancelled Message visible. A verified successful Run
completion may claim only the oldest pending Turn, in the same SQLite authority
transaction, and competing reconcilers can claim it only once. Failure, Stop,
interruption, unknown or partial evidence, and capacity pressure block the head.
Only an explicit Continue revalidates the current Agent, runtime configuration,
capabilities, and capacity before attempting that exact blocked Turn. Continue
is not a scheduler and no unsafe outcome is retried automatically. Cancelling a
blocked head atomically leaves the next queue-active Turn blocked: a pending
successor inherits the pause reason, while an already-blocked successor is
preserved exactly. Cancelling a blocked non-head does not alter the current
head, so the queue always retains an explicit recoverable head.

Normalized, completed runtime message items may project one safe assistant
Message into their owning Conversation under a deterministic source key. Event
replay, retention, reconnect, and competing reconciliation therefore cannot
duplicate or cross-project the Message. Partial token text is neither durable
authority nor a browser stream. The selected Run alone has a detailed SSE
subscription; each poll asks Python to reconcile that exact Run, publishes only
bounded event summaries, and refreshes the canonical Conversation for durable
Messages and terminal state. This mutating readback route requires the exact
same-origin request boundary and accepts no query parameters. Browser event
bursts collapse to one in-flight canonical Conversation read and at most one
trailing read; revision-monotonic merging rejects stale queue/Run state while
preserving at most 200 paginated Messages. The global activity rail remains a
bounded hint surface and opens no background detailed streams. Process-local
verification receipts are cleared at startup, then populated only by the
bounded startup readback, an accepted submission, or an exact selected-Run
readback. Any nonterminal Conversation Run without one of those current-process
receipts is projected as `reconciling`, and its Agent as `checking`, rather than
claiming stale work is live. Activity reads never call a runtime adapter or hold
the continuation gate across runtime I/O.

The Home composer remains writable during active work. `/steer` is recognized
only at the beginning after leading whitespace, strips its prefix, and targets
the exact selected running Run only when `run.message` is currently supported.
Steering creates no Message or Turn, never queues, and is never retried. A
stale, late, unsupported, rejected, or accepted-but-unverified result keeps the
draft and reports no-send. Temporary adapter unavailability remains distinct
from unsupported steering, and the composer keeps its ordinary Send action
rather than exposing a separate Steer button. The existing exact previewed Stop
capability remains the control path; its targeted reconciliation blocks only
that Conversation's queue.

Browser-created Hermes and Codex Agents receive Mentat's complete interactive
capability declaration by default, including `run.message`. That durable Agent
declaration is permission, not a claim that an idle or incompatible runtime can
currently accept a message: live `steer.available` still comes only from the
exact selected Run's verified adapter state.

Codex Conversation continuity is adapter-private. A later Turn may reuse only
the same App Server thread after `thread/read` proves the immediately preceding
executed Turn completed. A failed, partial, missing-reference, or non-adjacent
Run cannot be replaced with an older thread or a fresh thread. The browser
cannot supply or observe a thread or Turn ID, and missing or unsafe continuity
evidence fails closed. Browser drafts, optimistic Messages,
in-flight state, queue edits, unresolved exact retry keys, Turn announcements,
streams, and live summaries remain scoped by Conversation and Run so navigation
cannot replace another Conversation's evidence or mislabel a background result.
One monotonic notice order still lets newer global setup/navigation failures
supersede stale Turn feedback. Existing Task-dispatch Runs retain their Task,
reservation, dispatch-head, and idempotency authority.

Format-4 backup remains the recovery container because it embeds the private
database. Schema 12 is a forward-only repair for one exactly fingerprinted
pre-release schema-11 Conversation shape: before upgrade, read-only capture may
accept released fingerprints or that exact missing-trigger and broad
blocked-reason variant. SQL fingerprints ignore layout only: token boundaries
and quoted contents remain exact. The migration acquires its SQLite write lock
before classifying the source, then rebuilds the Turn table with the released
enum, restores all four queue/identity triggers, checks every foreign key, and
commits the schema receipt with the rewrite. Released schema 11 and that exact
legacy shape converge to one schema-12 fingerprint; every other drift and every
active caller transaction fail closed.

Schema 13 adds an exact terminal-finalization barrier. A terminal local Hermes
Conversation remains publicly `finalizing` until its exact normalized terminal
event is durable; it is still active for UI, retention, shutdown, and FIFO
purposes. One trailing terminal event may close a stale nonterminal status read
from the same reconciliation snapshot. Multiple, conflicting, non-trailing, or
paginated terminal evidence rolls back without consuming the runtime cursor.
An unfinalized terminal is retention-pinned, and startup recovery marks
incomplete evidence partial and blocks the queue head rather than advancing it.
The only accepted first-event cursor discontinuity is the exact initial Hermes
binding marker for the same Agent and Turn; every other gap fails closed.
During the same migration, schema-12 continuation pins that already advanced
beyond `reserved` are cleared before the stricter identity trigger is installed;
this keeps claimed or accepted pre-upgrade successors recoverable after restart.

Queued Codex continuity stores the exact predecessor Run while the successor is
reserved, which pins that predecessor against retention. Dispatch revalidates
the immediately preceding executed Turn and loads its private runtime reference
before one atomic `reserved` to `submitting` claim clears the temporary link. A
verified pre-attempt rejection or restart interruption also clears the link in
its terminal transaction. A single synchronous rejection protects the exact
result it returns through that retention pass; bulk restart recovery enforces
the normal retention ceiling and keeps every classification in the durable
submission receipts even if an older Run row is evicted. The schema trigger
permits only those exact claim or no-attempt terminal clears; every other
Conversation Run identity change remains immutable. Backup, restore,
fingerprint, and semantic validation remain compatible with released schemas
10 through 13.

Schema 14 adds explicit Conversation Run attempts for operator recovery.
Retry creates a new Run for the same Turn with a fresh immutable execution
snapshot and `retry_of_run_id`. Resume uses `resume_of_run_id` only when the
Agent and exact live adapter both advertise `run.resume`, the source retains a
private runtime reference, and the adapter implements the fixed resume method.
No current production adapter advertises Resume. Retry and Resume accept one
bounded idempotency key, preserve a durable result receipt after full Run
retention, and permit at most seven later attempts for one Turn. The latest
submission projection advances to the new Run without deleting prior Runs or
events. Concurrent keys cannot create two successors from one source, and a
restart marks an unattempted recovery reservation interrupted or a claimed
uncertain attempt unknown without another adapter call. Migration 14 requires
the exact schema-13 fingerprint in the same write transaction, replaces only
the latest-result insertion trigger, and adds the bounded attempt-receipt
authority.

Schema 16 rebuilds only the exact schema-15 Conversation table constraint to
add the `manual` title source. The migration preserves Messages, Turns, Runs,
submission receipts, staging, and attachment references under one SQLite write
transaction and foreign-key check. Manual rename is an exact-revision mutation
for active or archived Conversations. Later first-Turn title derivation and
queued-Turn edits may update only their existing derived title source and can
never replace a manual title.

Conversation history search reads titles only. It scans the validated maximum
of 1,024 Conversations, applies Unicode case-folded substring matching plus an
`all`, `active`, or `archived` filter, and returns at most 50 safe summaries in
deterministic state and update order. The opaque cursor carries only the state,
query digest, and ordering key. It is rejected under another query/filter or if
its exact ordering boundary is no longer authoritative. Messages, Runs,
snippets, Agents, attachments, runtime references, and query text are absent
from the result. Typing changes only the result view; selection requires an
explicit Open action.

### Conversation Project and Task planning context

Schema 17 adds `mentat_conversation_planning_context`, one optional
Conversation-owned reference containing a canonical Project ID and optional
Task ID. It is deliberately separate from Conversation rows and has no Task
foreign key: Task authority uses whole-collection replacement, and a foreign
key would silently erase context during a valid replacement. The Conversation
foreign key cascades only when its owning Conversation is removed. Missing,
moved, deleted, or ambiguous targets remain stored but project only fixed
`project_unavailable`, `task_unavailable`, or `project_mismatch` state until an
explicit rebind or clear.

Apply and Clear require the exact Conversation revision. Under the durable
root lock, Python validates the bounded Project document and resolves the Task
inside one immediate SQLite transaction before updating the association and
Conversation revision. Setting context requires an active Conversation; every
change is blocked by a nonterminal/finalizing Run or queue-active Turn. The
operation changes no Project, Task, Message, Turn, Run, attachment, calendar,
note, Context Pack, delegation, or runtime state. Context is presentation
metadata only and never becomes `mentat_runs.task_id` or hidden runtime input.

The browser receives separate fixed planning capabilities: a query-free
overview capped at 256 Projects and 50 attention Tasks, a Project-bound 50-row
Task page with an opaque cursor, one exact canonical Task locator for task-only
navigation, and exact Conversation context read/mutation.
Safe Task fields are limited to canonical identity, title, Project identity,
status, priority, due date, selected boolean/state planning flags, fixed
attention reasons, and update time. Descriptions, assignees, Agent IDs, notes,
calendar links, reminders, dependencies, subtasks, delegation, files,
artifacts, extensions, paths, and runtime references stay private.

Planning attention is a capped navigation surface, not a second Task
workspace. Fixed classification distinguishes overdue, due today, explicit
review, needs attention, planned today, and due soon; completed Tasks are not
overdue solely because an old due date passed. Planning suggestions only fill
an empty visible draft. They do not Send, queue, mutate, or delegate.

Projects & Tasks is the dedicated creation surface. Project creation accepts
only a Name. Task creation is scoped by the selected canonical Project and
accepts only Title, optional canonical Agent assignment, and optional Due date;
status defaults to `todo` and priority to `medium`. These are named bridge and
same-origin capabilities, not exposure of the generic compatibility routes.
Assignment stores Task metadata only and never dispatches an Agent or enters
the Hermes Kanban boundary.

The Next.js Home Console treats initial nonterminal SQLite state as
`Reconciling` until the selected Run stream completes its fixed mutating
readback. Stop, steering, and pending-action controls remain unavailable until
that exact Run is verified. Approval and clarification use dedicated inline
cards and the existing preview-confirm response boundary; composer text never
answers them. Closing a tab changes browser presentation only. Recent history
reopens the same durable Conversation, while exact-revision archive and restore
change only the Conversation lifecycle and never stop a Run or delete evidence.
If an archived Conversation's active Run completes, the terminal result still
commits while its queued head remains paused until an explicit restore and
Continue.

Run `details_json` remains a bounded display snapshot, while `run_attachments`
is the retention/access authority;
legacy media metadata without an exact direction-bound row is omitted from
browser and backup projections rather than minting a dead content route.
Compatible-root export intentionally omits Conversation
authority and leaves the source unchanged. Lossless rollback uses a validated
pre-migration backup; in-place schema downgrade is unsupported.

Milestone 9 adds a loopback-only signed Hermes native-event receiver as an
observation wakeup. The receiver authenticates the exact raw body, accepts an
exact 17-event lifecycle, post-operation, and Kanban observer allowlist, stores
only a keyed delivery digest in owner-only SQLite, atomically deduplicates
concurrent and post-restart retries, expires records through bounded 24-hour
cleanup, and applies a bounded per-binding token bucket. Accepted events retain
only the configuration-bound routing envelope; event-specific payload fields
are discarded before entering the bounded coalescing coordinator. Every
projected state change still comes from an authoritative Hermes adapter read.
Dropped, delayed, duplicate, and
out-of-order deliveries therefore affect freshness only, while periodic
reconciliation remains the correctness and recovery boundary. Stock Hermes
0.20.1 is the maintained local webhook baseline after live qualification and
Linux, macOS, and Windows CI; Hermes 0.19, absent,
unconfigured, disabled, and safe-mode runtimes retain quiet polling fallback.
Private migration and restore use exact reservations, verified old/new states,
source or recovery evidence, and startup refusal while incomplete. Runtime
uploads, exports, execution inputs, snapshots, future credentials, and other
secret-bearing private state are excluded.

Hermes 0.20's A2A, grounded-citation, deliverable-artifact, and voice features
do not inherit webhook authority merely because they share a release. A2A is a
separate bidirectional execution boundary. Citations remain untrusted response
Markdown until a structured provenance API exists. Local artifacts remain
restricted to Mentat's run-owned export boundary, while remote Kanban artifacts
use the authenticated custom-host artifact API and stock 0.20.1 degrades to
summary-only. Voice remains unavailable until Mentat has explicit browser audio
privacy controls and transport-advertised interruption semantics. Mentat does
not parse assistant prose for local paths, `MEDIA:` directives, citation
authority, audio, or transcripts.

## Write boundaries

| Surface | Policy |
| --- | --- |
| Hermes sessions and `state.db` | Read-only |
| Hermes provider credentials and authentication files | Never read or write directly |
| Remote Hermes API credential | Server-side owner-only configuration; never returned to the browser or written to tracked files |
| Hermes profiles | Mutate only through approved, fixed Hermes CLI/API operations |
| Model/provider configuration | Mutate only through validated Hermes operations |
| Existing Hermes cron jobs | Read-only inventory; queue controls fail closed |
| Skills and general `SOUL.md` content | Read-only; only the versioned Mentat identity block is writable |
| Mentat retained Console history | Writable below owner-only durable private storage and gitignored in development |
| Mentat attachment database and blobs | Writable below owner-only durable private storage, gitignored, and project-owned |
| Mentat project/task data | Writable through allowlisted project-owned storage |
| Hermes Kanban tasks and runs | Mutate only through the supported, capability-gated Kanban adapter |
| Arbitrary Hermes files | Never write directly |
| Remote Hermes files and stores | Never access directly; use only documented, authenticated capabilities |

## Mutation contract

Every write-capable Hermes operation must declare:

1. a typed intent and fixed handler; browser input never becomes a command;
2. capability and Hermes-version requirements;
3. input validation and affected profile scope;
4. preview and human-confirmation requirements;
5. concurrency and locking rules;
6. verification, partial-failure, and rollback behavior;
7. privacy-aware local audit data that excludes secrets.

Unsupported capabilities and unknown Hermes versions fail closed. Mentat never
constructs a shell command from browser text and never collects Hermes-owned
provider/model credentials or authentication-file contents. The sole remote
connection credential is the operator-supplied API key governed by the
owner-only, server-side boundary below. Mentat's connection record stores only
a credential-source reference; the key is resolved from a validated environment
variable or owner-only env file.

Mentat is an unauthenticated local application and must bind only to a loopback
host. Non-loopback serving of Mentat is not a deployment option under this
contract. A later server-side outbound connection to one remote Hermes endpoint
is allowed only under [REMOTE_HERMES.md](REMOTE_HERMES.md); that does not expose
Mentat itself or permit the browser to call Hermes directly.

Compatibility paths may serialize starts within a runtime adapter while the
strangler cutover is incomplete. Adapter capacity is not a product-wide Mentat
execution policy: the target Console permits concurrent Conversations, limits
each Conversation to one active Run, and represents unavailable adapter capacity
as an explicit waiting state.
Every run records its Hermes profile id, launches with a fixed
`-p <profile>` selector, and may resume only a session already associated with
that same profile. `agent_runtime.py` owns the runtime-neutral domain/protocol
boundary; `hermes_runtime.py` registers Hermes as the first runtime, normalizes
its run and event projections, and delegates compatibility routes to the
existing handlers. `hermes_transport.py` remains the Hermes local/remote launch
boundary: it preserves the exact local command/environment/process contract,
binds retained runs to the selected opaque connection identity, and revalidates
that identity before queue and launch. Its remote implementation supports one
profile-scoped turn through fixed Runs API operations, reads only the advertised
complete profile/runtime inventories, and can neither inspect nor launch local
Hermes.

`codex_runtime.py` registers the second runtime through Codex App Server's
local stdio JSONL protocol. Mentat discovers one trusted native CLI executable,
launches it directly with fixed arguments, and reuses the CLI's existing local
sign-in. The browser cannot choose the command, workspace, provider, model,
credential source, App Server method, thread, or turn. The child receives an
allowlisted environment; commands run with Codex's trimmed core environment,
the `workspaceWrite` sandbox, approval policy `never`, and the default credential-name
exclusions. This slice supports start, status, bounded events, active-turn
messages, exact completed-thread continuation, and exact-turn interruption. Its
private, qualified admission ceiling is two concurrent Runs on the owned App
Server; it is not a provider-wide capacity claim. Approvals and attachments are
not advertised. Capability and binding checks use a bounded read-only App
Server account probe. Ordinary registry reads use the static registered runtime
names and never start or wait for Codex.

The Agent Console exposes a separate explicit Codex readiness check with only
`cli_missing`, `sign_in_required`, `ready`, or `unavailable`. Setup directs the
operator to the Codex-owned `codex login` browser flow and requires an explicit
Recheck. Mentat never accepts a password, browser cookie, API key, access or
refresh token, account identifier, or Codex auth-cache contents; routine Agent
and Conversation reads never launch Codex.

Readiness and submission use nested end-to-end deadlines: each Codex operation
shares one budget across App Server startup and its request, and the private
bridge and browser-facing route retain longer outer response margins. A timeout
therefore cannot leave an inner operation running beyond the public caller's
certainty window. Private mutation bodies reject transfer encoding, require one
exact JSON content type and decimal content length, read exactly the declared
bounded bytes, and stop on one total wall-clock body deadline.

Codex thread and turn IDs remain private runtime references. Public records use
Mentat Run and event IDs. App Server text, commands, paths, and tool payloads
are omitted from the normalized event projection. A confirmed Stop is reported
only after a short exact-Run lease reconciles the terminal state into SQLite;
the private bridge and legacy server both close the App Server's owned process
tree during shutdown. POSIX uses a private process session; Windows uses a
kill-on-close Job Object rather than a reusable numeric PID.

The runtime-neutral Agent registry is available at
`/api/orchestration/agents`, separate from the legacy `/api/agents` heartbeat
projection. Creation is serialized with the durable backup/restore boundary,
stores the Agent and runtime binding atomically, accepts only a registered
runtime, and never returns the adapter-owned runtime reference. A configured
Agent authorizes work only through an exact Task assignment, capability match,
binding snapshot, and durable dispatch reservation. Codex Agents use only the
fixed `default` binding and capabilities implemented by the available adapter.
Backup format 4 includes and semantically validates embedded Hermes and Codex
bindings, including Codex's fixed binding and capability vocabulary. Format-3
backups retain the former standalone registry, and pre-registry format-2
backups restore an empty migration source; both require the explicit
convergence command before normal startup.

## Remote Hermes connection boundary

The approved public-beta direction is local Mentat connected to one active
local or remote Hermes endpoint. The detailed capability matrix, upstream
blockers, implementation order, and exit evidence live in
[REMOTE_HERMES.md](REMOTE_HERMES.md). The connection/storage/discovery
foundation, Agent Console transport boundary, default-profile remote run
lifecycle, read-only sessions, bounded Context Pack text, and remote
skill/toolset visibility are implemented. Exact approval and clarification
responses, continuation, complete profile discovery, revisioned Kanban, and
bounded image transfer are enabled only when their complete advertised
contracts are present. Remote delegated Kanban artifact download is available
only through its complete version-one manifest/digest contract. General remote
Console file transfer remains incomplete, so Mentat must not advertise full
remote parity.

The remote boundary has these architectural invariants:

1. the operator explicitly supplies an HTTPS endpoint and API credential;
2. setup and CLI accept only a credential-source reference, never an API-key
   value argument; the key is used only by Mentat's server and remains outside
   the connection record, tracked files, URLs, browser storage/payloads,
   diagnostics, backups that are not secret-aware, and logs;
3. public health is treated only as untrusted liveness; authenticated readiness
   and machine-readable capabilities are validated before Mentat enables a
   dependent feature;
4. endpoint, profile, session, run, preview, and confirmation identity remain
   bound so state from one host cannot authorize an operation on another;
5. unsupported, changed, timed-out, or unverifiable capabilities fail closed;
6. the existing typed-intent, preview, confirmation, locking, read-back,
   partial-failure, audit, and rollback rules apply equally to HTTP adapters;
7. Mentat never substitutes SSH, a remote shell, a mounted Hermes home,
   dashboard-token scraping, direct database/file access, or an undocumented
   endpoint for a missing capability; and
8. local Mentat features continue to work when they do not depend on the failed
   or unavailable remote capability.

Remote runs, bounded events/status, cancellation, stopping, approval, and
clarification use the documented Hermes Runs API only when each exact
capability is advertised. Mentat keeps one SSE subscription open while a run
waits for an operator response. Hermes assigns monotonic event IDs and retains
a bounded in-memory journal; a real reconnect supplies the last verified event
ID and receives only later events. Run status returns the current sanitized,
request-bound pending action as the authoritative recovery path if its event
was missed. Mentat never guesses or replays a stale response.

Hermes may also advertise a complete API-key-authenticated profile runtime
inventory containing only profile ID, current provider ID, and current model
ID. Mentat uses it to show the selected remote agent's current runtime on load
and after relevant lifecycle events. Active-run runtime events take precedence.
These values are read-only in remote mode: visibility does not grant provider
mutation authority. Provider-switch preview and apply handlers revalidate the
selected transport under the connection-operation lock and reject every
non-local binding before local inventory or mutation code runs. Profile
creation/deletion, identity editing, remote provider administration, and
general Console artifact transfer may degrade clearly in remote mode.

Remote upstream run identifiers are process-private and are not retained in
Console history. Graceful shutdown performs one stop attempt and bounded
terminal read-back. After an abrupt process death, Mentat marks a restored
remote summary interrupted and partial; durable upstream-run recovery is a
separate storage/authority slice and is not implied by 2C.

## Agent Console file boundary

Console files are Mentat-owned private/runtime data, never Hermes core data.
Retained history, attachment/blob/run-reference SQLite metadata, and referenced
content-addressed bytes form one durable owner-only unit below
`<data-root>/private/console/`. Uploads, execution inputs/exports, workspace
snapshots, and lifecycle files remain ephemeral below `<data-root>/runtime/`,
as defined in [DATA_LAYOUT.md](DATA_LAYOUT.md). The browser sees only opaque attachment ids, bounded
display metadata, and fixed same-origin content routes. It never receives blob
hashes, storage keys, trusted server paths, or arbitrary file-serving URLs.

Uploads and workspace snapshots must pass extension, MIME/magic, UTF-8, size,
secret-name/content, regular-file, containment, and symlink checks. Text is
served as `text/plain` with `nosniff`. Inline display is restricted to validated
PNG, JPEG, GIF, and WebP content. SVG, HTML execution, PDF embedding, archives,
executables, path traversal, and remote/data/file URLs are outside this
capability.

Content-addressed blob filenames are intentionally extensionless. They must not
be passed directly to Hermes image arguments because Hermes validates supported
image suffixes. Mentat creates a bounded, private, run-scoped input snapshot
with the server-validated extension, uses that path only for the fixed Hermes
adapter call, and deletes the snapshot when execution ends. Browser responses
and retained history never expose this path.

Workspace selection searches only explicit configured roots and returns
relative paths. The current root is the Mentat repository; VCS, hidden,
dependency, build, runtime, secret, archive, executable, and symlinked paths are
excluded. Selection creates a private no-follow snapshot before storage, so a
later workspace edit cannot change prompt context already attached to a run.

Context Packs store reusable references in project-owned `data/context_packs.json`:
bounded instructions, vault-relative Markdown paths, and workspace root ids plus
relative paths. They never store note/file contents or absolute paths. Every use
revalidates the references. Console use creates normal private staged snapshots;
delegation use resolves bounded text into the exact preview and confirmation
digest, so changed pack content must be previewed again.

Schema 15 makes Conversation composer staging durable without making it backup
authority. `mentat_conversation_staged_contexts` and
`mentat_conversation_staged_attachments` belong to one active, idle
Conversation and hold only an exact Context Pack revision plus opaque attachment
references. At most eight context items may be staged, with at most five direct
upload/workspace items and one image. A context-bearing Send must reserve one
immediate local Hermes Run and move that exact set into `run_attachments` and
`mentat_conversation_run_contexts` in the same SQLite transaction. It cannot
queue, steer, cross Conversations, or fall back to text-only. Exact Send replay
uses the retained context digest, and Retry copies the retained input bindings
or fails before another adapter call.

Existing Agents do not gain file authority during migration. The browser may
offer an explicit two-step Enable files action only for a stopped, exact local
Hermes Agent; the mutation is bound to its current capability set and rechecks
that the fixed local runtime supports the file boundary. Codex, Vercel, remote
Hermes, and incomplete adapters remain unsupported. Unsent staging is removed
from private backup snapshots and compatible export, while retained Run inputs
and trusted export artifacts remain part of the validated private consistency
unit. Startup and periodic reconciliation discard an entire staged Context Pack
if any of its snapshots becomes unavailable.

Local Hermes file capability also requires descriptor-relative, no-follow Run
input cleanup. Platforms without that primitive do not advertise or enable
Conversation files; they fail before materializing input bytes. A stale input
directory left by an older build is never traversed through a pathname fallback.
Recovery is stopped-server-only: inspect and remove the exact
`<data-root>/runtime/agent-console-inputs` scratch tree, then restart so bounded
reconciliation can verify a clean root. Retained attachment/blob authority under
`private/console` is not removed by that scratch recovery.

Remote Console use adds a short-lived random grant around those existing
private snapshots. The grant is bound to one connection, pack revision, and
ordered attachment-id set, and is consumed once. Mentat reads only validated
text snapshots, applies fixed item and total limits, and constructs a
path-free user-context block. A restart, expiry, connection change, pack edit,
or attachment mismatch requires the operator to apply the pack again.

Assistant-created artifacts are accepted only from a private per-run export
directory named in trusted server-generated execution context. Mentat does not
parse paths from assistant prose. After execution, it scans that directory with
bounded allowlists, snapshots acceptable files without following symlinks,
binds stored outputs to retained history, and cleans successfully registered
exports. Failed registration preserves the export for retry.

Remote delegated artifacts use a narrower boundary. Hermes promotes only files
explicitly declared when an API-created Kanban task completes inside its managed
scratch workspace. It returns opaque IDs and safe metadata, never paths.
Mentat streams each accepted file over the selected authenticated connection,
verifies its digest and content again, and stores an independent private
snapshot keyed to the Mentat task, connection, board, and remote task. Home
and task detail render raster outputs as download-only file cards rather than
decoding the original file inline. Both sides structurally decode raster files,
enforce frame and pixel ceilings, then re-encode metadata-free canonical
snapshots. Unknown chunks, embedded metadata, appended bytes, and the original
untrusted container never become downloadable content. Home
renders its local data before refreshing at most three current-connection
delegations in the background. Failed artifact transfers use a bounded retry
delay, and unsupported hosts are not polled again automatically. An explicit
refresh compares the remote completion revision and restores a missing local
snapshot when possible. The browser sees only fixed same-origin opaque download
routes. Older Hermes versions keep the summary-only workflow, and older unbound
Mentat delegations require an explicit verified reconnect before any remote
read or download.

Staged files expire after two hours. Unreferenced files use a one-hour grace;
active and retained run references prevent collection. Startup reconciliation
and a bounded periodic collector repair interrupted states, release references
for history that no longer exists, and retry failed deletions with backoff.

## Profile identity boundary

The Hermes profile id remains the canonical executable name. Hermes profile
metadata remains the routing-role source used by Kanban, while a versioned
Mentat-managed block at the top of the profile's `SOUL.md` makes the same name
and role available to the running agent's system prompt. Mentat does not create
a second identity registry and never returns the remaining soul content to the
browser.

In local mode, identity inspection and writes run inside the Hermes runtime and
resolve the profile only through Hermes' profile API. A write is allowed only
when the runtime exposes the required profile-resolution and metadata
operations. The adapter rejects symlinked soul files, multiple or malformed
managed blocks,
reserved marker text, unknown profiles, stale revisions, and active Console
runs. Every change requires an exact preview and profile-bound confirmation,
uses an atomic same-directory soul replacement, synchronizes the Hermes routing
description, refreshes both surfaces for verification, and attempts rollback on
failure. Content outside the managed block is preserved and remains read-only.
Remote mode must not inspect or edit `SOUL.md`; identity controls remain
unavailable until Hermes advertises an equivalent authenticated capability.

## Personal task and planning model

Mentat's project-owned task record is the source of truth for personal planning.
Optional planning metadata covers deliberate Today selection and rank, estimates
and scheduled blocks, browser reminders, subtasks, dependencies, recurrence,
calendar links, Obsidian note links, planning state, and the safe references
needed to associate a task with delegated Hermes work.

The planning validator preserves legacy task records while strictly validating
nested planning objects. It rejects unsafe note paths, malformed timestamps,
unknown nested execution metadata, missing or self-referential dependencies,
and dependency cycles. Recurrence is implemented in Mentat's locked task update:
completing a recurring task creates at most one next occurrence and preserves
the completed instance as history. Scheduled blocks and reminders retain a
validated IANA time zone so recurring wall-clock times remain stable across
daylight-saving transitions.

Browser reminders are advisory UI behavior over Mentat-owned timestamps. The
browser asks for notification permission only after an explicit operator action
and locally deduplicates delivered notifications. No reminder mutates Hermes or
Google Calendar.

## Hermes Kanban delegation boundary

The supported Hermes Kanban adapter is the only durable delegation mutation
path. It uses fixed local Hermes operations or the authenticated,
capability-advertised remote Kanban surface with the same revision and
read-back behavior. Hosts without the complete contract fail closed. Agent
Messages remains a project-owned communication
queue, and Agent Console remains an interactive Conversation surface; neither is
a durable task dispatcher. The Console's separate bounded pending-turn contract
may retain up to eight user-authored turns for one Conversation and dispatch the
next turn only after that Conversation's active Run reaches a verified successful
terminal state. It has no timers, automatic retries, cross-Agent routing, or Task
orchestration. Stop, failure, unknown, interrupted, and capacity-blocked states
pause automatic dispatch and require explicit operator action.

The adapter uses shell-free argument arrays and a fixed set of supported Kanban
operations. It omits workspace paths, process identifiers, arbitrary metadata,
and secrets from browser payloads. Mentat advertises a Kanban operation only
when runtime discovery reports the corresponding capability.

Creating a delegation requires:

1. a Mentat task, Hermes profile, Kanban board, supported workspace mode, and
   bounded instructions;
2. an exact preview whose confirmation token is bound to the current task and
   complete delegation intent, including bounded attached-note context;
3. revalidation of the same intent at confirmation time;
4. an atomic project-owned reservation that prevents task edits or duplicate
   delegation while the external operation is in flight;
5. a shared Kanban/task mutation lock and one fixed adapter operation;
6. a read-back that verifies the created task's title, context, assignee, and
   workspace before Mentat stores its safe link.

A changed task or intent invalidates confirmation. Missing capabilities and
unknown boards/profiles fail closed. If Hermes accepts a mutation but its state
cannot be read back, Mentat returns a partial failure and does not claim that
the operation was verified. Follow-up remote actions such as reply, retry,
reclaim/stop, request revision, and mark blocked also require an exact preview and confirmation
and are refreshed from Hermes after mutation. Result acceptance is a local review
decision that completes the Mentat task without an additional Hermes mutation.
Action previews refresh and bind the live Hermes task status and latest run
identity; confirmation is rejected if either Hermes or the Mentat task changes.
Adapter mutations verify operation-specific postconditions rather than treating
a merely readable task as proof that the requested effect occurred.

The task's delegation object stores normalized profile, board, task, run and
session identifiers plus the opaque selected-connection binding; state,
synchronization and review status; bounded summary
or blocking-question text; attempt count; timestamps; and a bounded secret-free
audit. Agent Activity is derived from these task-linked records and groups work
into needs input, ready for review, running, failed, and recently completed.

## Calendar, notes, and search boundaries

Google Calendar access remains read-only. Creating a Mentat task from a verified
event, linking a selected task, or assigning a scheduled block mutates the
authoritative Task collection through the SQLite Task repository. These
operations never mutate live `data/tasks.json`. Mentat never edits, deletes, or
reschedules the Google event.
The week view accepts only a validated Sunday start, a fixed seven-day range,
and a validated IANA timezone. Google and local-fallback results are filtered to
the exact half-open week window, including events that overlap a boundary. The
disconnected preview is generated only in the browser and its sample events are
never eligible for task-link mutations.

Task note attachments are validated Markdown paths relative to the configured
Obsidian vault. Symlinks and paths that escape the vault are rejected. Delegation
context may contain a bounded excerpt from attached notes; Mentat does not edit
those files. Opening a note is an explicit user-facing Obsidian application link,
not a generic server-side file opener.

Grouped global search returns bounded, public-safe navigation records for tasks,
projects, session metadata, notes, and cached/local calendar events. Searching
does not itself change views; navigation occurs only after the operator selects
a result. Deep Hermes message search remains a separate read-only endpoint.

## Provider switching boundary

The Next.js Home composer reaches this boundary only through a canonical Mentat
Agent ID. Python resolves the private runtime binding, and the fixed bridge
returns no profile ID or runtime reference. For a uniquely bound local Hermes Agent,
the composer may show only the authenticated profile-scoped provider/model
inventory below and must use the same exact preview-confirm-verification path.
Codex, Vercel, unsupported runtimes, and effort without a fixed mutation
capability stay visible but read-only. The browser never selects their provider,
model, effort, executable, working directory, credential source, session, or
thread. A confirmed pair is labeled for the next Run. The active Run continues
to display its immutable runtime-reported provider/model/effort snapshot from
SQLite and is never relabeled from current Agent state.
Remote Hermes exposes only its current safe provider/model identity through this
composer capability; alternate remote inventory never crosses the boundary.

Provider discovery and selection are scoped to the selected Hermes profile.
The current mutation adapter runs locally. Remote mode may display the
capability-advertised current provider/model identity, but keeps mutation
controls disabled unless a future endpoint advertises equivalent authenticated
inventory, mutation, verification, and rollback behavior.
Mentat obtains picker context from Hermes through `load_picker_context()` and
builds the selectable inventory with
`build_models_payload(..., explicit_only=True, picker_hints=True)`. The browser
may therefore see only providers Hermes reports as explicitly configured and
authenticated for that profile, plus whether each provider is current. It must
not receive credential values, credential paths, environment-variable names,
tokens, or an unfiltered catalog of every provider Hermes supports.

Hermes remains the sole owner of provider credentials and authentication.
Mentat does not add, edit, validate, migrate, or delete credentials. Provider
switching is an approved, fixed Hermes adapter capability with these rules:

- Mentat advertises the switch capability only after probing that the installed
  Hermes runtime exposes the supported profile-model operation;
- the requested provider must be present in the profile-scoped authenticated
  inventory returned by Hermes;
- the current provider/model is reported separately from the authenticated
  selectable set and remains the only confirmed runtime projection, even when
  the current pair is not selectable;
- Mentat previews the affected profile, current provider, requested provider,
  and model implications before applying a profile-bound confirmation. Agent
  Console treats a deliberate provider/model selector change as the user
  action, obtains that bound preview, and applies it immediately without a
  second modal click. Managed Agents retains its separate review dialog;
- switching is blocked while an Agent Console run is active;
- Mentat refreshes Hermes picker context after the operation to verify the
  selected provider and models;
- while preview/apply is pending, the Console keeps the last confirmed pair
  visible and labels the requested pair as pending rather than ready;
- browser apply results are accepted only for the same opaque transport
  binding and selected profile that initiated the operation;
- if both a switch attempt and its fresh reconciliation read fail, Mentat
  discards stale browser inventory and blocks prompts, attachments, sessions,
  and further switching until an explicit runtime re-check returns an exact
  non-error current provider/model pair;
- attachment and Context Pack staging serialize with runtime switching and
  discard results if the selected profile or connection changes in flight;
- verified runtime notices are browser-session display state bound to the
  current Hermes transport and profile, not durable run history;
- a failed verification triggers rollback to the previous provider when Hermes
  supports it, otherwise Mentat reports the partial failure and fails closed.

This boundary covers selection among already authenticated providers only.
Credential setup and reauthentication continue to happen through Hermes.
There is no direct or unconfirmed Agent Console model-mutation route. The
browser may automate preview and confirmation after an explicit selector
change, but all provider/model changes still enter through this capability
contract and the server still recomputes the exact confirmation under lock.

## Project task deletion boundary

Task deletion affects only Mentat's allowlisted project-owned task store. It
requires an exact preview and matching confirmation bound to the task's complete
current state. The task is re-read under the project-data lock before
the atomic update, so a changed or missing task fails closed. This operation
does not mutate Hermes data and is not reversible from Mentat.

## Hermes cron boundary

Mentat exposes cron inventory as read-only. Local mode reads the local Hermes
cron store. Remote mode never reads that store or any remote path; it requires
Hermes to advertise the complete version-one `GET /v1/jobs` contract. That
endpoint requires the API key and returns a read-only public view capped at 128
jobs and 256 KiB. It includes only the job ID, an ID-based label, schedule,
enabled state, last and next run times, status, and an opaque revision. Hermes
never puts stored names, job instructions, delivery settings, work directories,
or execution output in this response. Mentat checks the selected connection
before and after the request and rejects older, partial, malformed, or
oversized responses.

The installed Hermes runtime does not provide an atomic, expected-revision,
enabled-only operation for moving an existing job to the next scheduler tick.
A separate read followed by the available trigger operation cannot close that
race: a job could be changed or disabled between validation and mutation, and
the trigger may implicitly enable it. Mentat therefore advertises no working
queue capability and its queue controls fail closed.

Safe next-tick queueing requires an upstream Hermes compare-and-swap operation
that atomically verifies the complete expected job revision and enabled state
while scheduling the next tick. If Hermes adds that capability, Mentat may
integrate it through the normal preview, confirmation, lock, and post-operation
verification contract. Mentat must not approximate it by writing
`~/.hermes/cron/jobs.json` or by composing multiple non-atomic operations.

An immediate **Run now** action is a separate product choice with different
execution, confirmation, progress, and delivery semantics. It remains deferred
and must not be presented as a substitute for next-tick queueing. Creating,
editing, enabling, disabling, and deleting cron jobs also remain Hermes-owned
operations.

Agent Console progress is exposed as versioned, structured Mentat events. Event
sequence numbers are monotonic within a run and double as polling cursors. The
browser requests only events newer than its cursor and merges them into its local
run view; the full-run response remains available for compatibility and recovery.
Mentat-owned lifecycle events include a durable `session.started` boundary only
after an explicitly fresh local run launches or a remote run is accepted.

Local Hermes tool progress arrives through an optional, private, run-scoped
JSONL channel owned and pre-created by Mentat runtime storage. Mentat passes the
paths through optional environment variables so an older Hermes runtime keeps
the exact legacy command and safely ignores them. Mentat validates the file
boundary, schema, monotonic sequence, type, count, size, and tool identifier
before projecting an event. It never derives reasoning status from assistant
text; a local `reasoning.available` phase is accepted only when Hermes reports
that the provider supplied a genuine reasoning field, and its summary is fixed.
Mentat never parses native CLI stdout/stderr into tool events or returns raw
reasoning, tool arguments, tool results, paths, or secrets. The source file is
deleted with the run's private input workspace. On platforms without secure
directory-descriptor/no-follow writes, this optional local detail channel fails
closed and the Console retains its generic lifecycle status and unavailable
context state.

Detailed tool events are hidden by default. The Console transcript remains
visible between the runtime selectors and prompt composer. While the selected
run has one or more outstanding tools, an animated summary remains visible in
the transcript header above the detailed rows. A persistent live region
announces only inactive-to-active and active-to-inactive transitions for the
selected transport/profile; concurrent tool counts do not repeat the
announcement.

Durable Message text is rendered through a deliberately small presentation
grammar: paragraphs, up to three heading levels, blockquotes, ordered and
unordered lists, emphasis, inline code, and fenced code. React text nodes are
the only HTML boundary; raw HTML and URLs remain inert text, bidi controls are
replaced, displayed content is bounded, and fenced code is never executable.
Copy acts only on the bounded displayed Message or code text. Consecutive
Messages are grouped under presentation-only Run or queued-turn headings
without revealing runtime references. The browser retains at most 200 Message
rows, 512 formatting units per Message, and 8,000 formatting units across the
transcript; excess formatting falls back to bounded plain text. Scroll position
and near-bottom state are isolated per Conversation.

Presentation history follows the SSE envelope contract: `reset: false`
snapshots merge after reconnect, `reset: true` snapshots and explicit reset
events replace the retained window, and malformed envelopes change nothing.
Events without an allowlisted presentation remain bounded sequence markers so
later ordinary progress can close Thinking without exposing unclassified data.

The desktop Console uses one compact tab strip and centers the Conversation
workspace exactly between the navigation rail and activity rail. Closing a tab
does not archive or delete its Conversation. The rail arrow and accessible
label describe the action that the next click will take. Shell synchronization
must compare current DOM values before writing so its mutation observer cannot
be retriggered by idempotent updates.

### Safe rich-link preview boundary

Link previews are asynchronous, Message-bound derived data. A browser request
contains only canonical Conversation ID, Message ID, exact Message revision,
and a fixed enqueue or retry action. Python re-reads the accepted user Message
and extracts at most three candidates; no browser or Node field can select a
URL, header, destination, proxy, cache key, image source, or bridge path.

The network policy allows only canonical public HTTPS on port 443. It applies
UTS #46 nontransitional IDNA, strict component normalization, credential-query
blocking, special-use domain and source-controlled IANA address denial, whole
A/AAAA-set validation, sixteen-answer and two-candidate bounds, numeric-IP
dialing, hostname SNI/Host, peer-address verification, and three fully
revalidated redirects. Fixed page/image requests send no cookie, authorization,
proxy authorization, referrer, origin, browser user-agent, language, client
certificate, provider credential, or returned cookie.

Two replaceable isolated Python workers own DNS, TLS, bounded transfer, HTML
metadata parsing, and image decoding. They receive no data-root path, Console
descriptor, HOME, NETRC, proxy, CA override, provider variable, or bridge token.
The parent kills and replaces a worker after a one-second DNS phase or a
5.25-second operation watchdog. Page bodies, decoded gzip, headers, MIME,
charsets, tags, attributes, images, pixels, dimensions, frames, and output WebP
all retain the fixed limits recorded in the Slice 7 review log and accepted
research.

Sanitized metadata is cached under keyed, versioned URL digests in the
owner-private disposable `cache/link-previews-v1/` namespace. It stores no raw
URLs, HTML, headers, addresses, or original images and is capped at 512 rows and
64 MiB of transformed images. Process-local no-store and capacity states use a
separate 512-entry LRU, and persisted results are not duplicated there. The
256-bit cache secret and cache members are
excluded from backup, restore, and compatible export. The enabled-by-default,
exact-revision privacy preference lives separately at
`config/link-previews-v1.json`; clearing cache cannot change it. Disabling
cancels/suppresses work and cards, and re-enabling never automatically fetches
old Messages.

Candidate ordinals preserve the raw first-three Message positions even when
equivalent normalized URLs share one fetch. The browser receives only candidate ordinal, fixed status, bounded text,
canonical display host, and optional opaque image ID. Images are fixed
same-origin WebP responses and cannot fetch on a miss. Remote HTML and image
URLs never cross. The original HTTPS text remains present when metadata is
pending, blocked, disabled, unavailable, expired, or unsupported, and preview
failure never changes Message, Turn, Conversation, or Run authority.

Completed runs may also receive a private structured usage report. Billing
totals remain separate from `context_tokens` (the last actual prompt size) and
`context_length` (the active model window). The UI calculates a percentage only
when both exact non-negative integers are present and internally consistent;
otherwise it says the context measurement is unavailable. Cumulative billing
tokens must never be substituted for active context usage. Remote Runs may
provide the same optional fields and safe progress summaries through their
versioned response/event contracts.

For remote runs, the upstream Hermes event sequence is separately verified
before Mentat projects events into that local history. Approval and
clarification waits remain active states and do not close the upstream stream.
Reconnect replay is bounded and in-memory; current pending-action status is the
fail-closed recovery source when retained history is unavailable.

Agent Console slash commands come from Mentat's versioned, project-owned safe
command manifest. Each entry declares its dashboard handler, arguments,
description, and safety classification. The frontend accepts only the current
schema and a fixed handler registry. The allowlist is `/model`, `/new`,
`/steer`, and `/help`; this is intentionally distinct from the full Hermes
CLI. `/steer` is a remote-control command, not CLI passthrough, and dispatches a
fixed, revision-bound exact-Run operation. The target Next.js Console has no
Steer button.

The Next.js Console reads that exact complete version-one manifest through one
fixed same-origin capability and maps it to a fixed local handler registry.
`/new` creates a durable Conversation for the selected Agent, `/model` refreshes
or stages only the existing safe next-Run configuration selector, `/steer`
retains the exact active-Run boundary, and `/help` shows fixed Mentat-facing
descriptions. Local completion never performs a mutation. Any unknown command,
invalid usage, manifest failure, handler failure, or stale target preserves the
full draft and creates no ordinary Turn as fallback.

Remote active-run steering is available only when Hermes advertises
`run_steer` with the exact `POST /v1/runs/{run_id}/steer` endpoint. Mentat
requires a running remote run bound to the current connection, profile,
transport instance, and local control revision; it verifies status before the
mutation, validates Hermes' exact acceptance response, and reads the same run
back afterward. An accepted action whose read-back fails is reported as a
partial failure and is never retried automatically. The steer text and remote
run identifier remain private and are not persisted; only a bounded text-free
status event enters Console history.

Local Hermes uses the runtime's supported headless control backend rather than
the one-shot `chat -q` child whenever that backend and Mentat's pinned WebSocket
client are available. Mentat starts one profile-scoped backend with a fixed
loopback host, ephemeral port, isolated mode, private caller-generated token,
and owner-private readiness file. The authenticated socket, token, live session
ID, and process remain server-only. Startup probes the fixed
`session.redirect` method before any prompt submission; a definite pre-submit
startup failure may fall back to the established one-shot Console launch.
After a prompt request begins, an uncertain result is never retried. The
control client is published to the exact Run before any blocking startup work,
and both the default Python bridge and legacy server lifecycle close it before
runtime teardown. Its owner-private runtime directory is created through a
no-follow path boundary; POSIX owns the complete process group and Windows owns
the complete process tree through a kill-on-close Job Object.

The local steer control becomes available only after `message.start` proves
that the exact bound live session has an active turn. Mentat then maps `/steer`
to `session.redirect`, not the queue-capable `session.steer` operation. Success
requires Hermes to return `status=redirected` with the exact guidance text; a
rejection leaves the draft intact, while a queued, timed-out, disconnected, or
authority-racing result is partial and consumes the control revision. Guidance
text is never persisted. That partial classification remains intact through the
runtime-neutral Conversation bridge so the browser preserves the draft and
does not retry. Stop and shutdown close the authenticated backend and its owned
process tree.

The Python compatibility Console retains its implemented active-run control
behavior during cutover. The target Next.js composer instead remains writable:
ordinary text creates a durable Conversation Turn, and only text beginning with
`/steer` attempts active-Run steering. Unsupported or stale steering preserves
the draft and reports why it was not sent; it is never silently queued. Stop
remains a separate hard-stop control. Attachment steering remains unavailable
until a runtime advertises a versioned media contract with exact bounds and
verifiable read-back.

Future command sources must be introduced as an explicit capability and emit
the stable Mentat schema. Mentat does not parse CLI help/output to discover
commands, and it never provides arbitrary Hermes CLI passthrough.

### Native Hermes event wakeups

Mentat accepts a reviewed subset of stock Hermes outbound events only through
the signed, loopback webhook receiver. In addition to session and subagent
lifecycle events, this subset covers completed API/error observations,
completed tool observations, and post-commit Kanban task, worker, and dispatcher
observations. Every event is reduced to its configuration-bound identity and a
fixed projection class; prompts, arguments, results, summaries, reasons,
task/session IDs, models, token values, paths, and raw bodies do not enter
projected state.

The event-to-projection table in `hermes_event_refresh.py` is the authority for
wakeups. Kanban claim, complete, block, manual update, worker lifecycle, and
dispatcher-tick events all cause live adapter readback; no event payload proves
a transition. Successful readbacks publish only fixed projection names through
the same-origin `/api/hermes/events` Server-Sent Events endpoint. Its bounded
history and client count limit resource use, while reconnect overflow requests
a full projection refresh. The browser coalesces these hints and uses existing
APIs. Periodic browser polling and server reconciliation remain recovery paths
for old Hermes versions, Safe Mode, absent emitter processes, dropped queues,
oversized private payloads, disconnections, and readback failure.

The Milestone 9I stock-compatibility audit intentionally retires none of these
fallbacks. Native hooks reduce freshness latency but are not liveness proof,
data-bearing telemetry, or mutation authority. The 30-second browser refresh,
60-second server reconciliation, optional private local Console telemetry, and
capability-gated remote contracts remain until their separate retirement gates
pass. The complete machine-checked inventory and stock degradation behavior are
in [HERMES_STOCK_COMPATIBILITY.md](HERMES_STOCK_COMPATIBILITY.md).

## Initial agent-creator scope

The first version may create a fresh profile or clone approved configuration
through supported Hermes operations. It may collect a profile name,
description, creation mode/source, and skill-seeding choice.

Approved for the initial creator:

- default Hermes bundled skills;
- no bundled skills for a fresh profile;
- an explicit enabled subset selected from Hermes' built-in skill catalog.

Skill selection uses a capability-gated Hermes runtime operation. Mentat stores
skill identifiers only; it does not edit skill contents or copy skill files.

Approved for Managed Agents:

- deletion of a non-default, non-active Hermes profile when Hermes advertises
  `profiles.delete`;
- an exact preview and profile-bound confirmation token before deletion;
- blocking deletion while any Mentat Agent Console run is active;
- post-operation profile discovery to verify the profile was removed.
- profile-scoped provider/model configuration using the same authenticated-only
  inventory, preview, confirmation, active-run lock, verification, and rollback
  contract as the Agent Console. This is the configuration path for a fresh
  profile that does not yet have a provider assigned.
- profile identity inspection and confirmed synchronization of the immutable
  profile name and routing role into the versioned managed `SOUL.md` block.

Deletion is performed only through Hermes' supported profile API in its own
runtime. Mentat never deletes profile directories or their contents directly.

The Agent Creator uses a compact step-progress indicator instead of status-pill
controls; skill choices and review details remain explicit form controls.

## Static browser delivery

Mentat's loopback static server may gzip sufficiently large HTML, CSS,
JavaScript, JSON, and SVG responses when the browser advertises gzip. It keeps
the root document private and non-cacheable, while versioned asset URLs receive
long-lived immutable caching; unversioned assets receive bounded public
caching. Compressed responses advertise `Vary: Accept-Encoding`, and clients
without gzip support receive the original bytes. The Home document includes
stable first-paint placeholders for asynchronously populated panels and loads
the ordered core/application bundles after the initial frame. This delivery
optimization does not change API, Hermes, or local-only boundaries.

After creation, the operator may explicitly test the selected profile in a new
Agent Console identity-check session or begin creating and assigning its first
task. The same actions appear in Managed Agents. Provider/model mutation remains
inside the existing authenticated-only, previewed Advanced configuration flow;
these onboarding actions do not weaken that boundary.

Deferred until separately approved:

- general `SOUL.md` editing outside the managed identity block;
- clone-all;
- profile rename;
- skill content editing, hub installation, or arbitrary MCP configuration;
- non-loopback Mentat serving or browser-to-Hermes access.

The target Agent Console permits concurrent Conversations and Agents while
allowing at most one active Run per Conversation. Runtime adapters declare and
enforce their own capacity, and the orchestration layer must isolate execution,
steering, cancellation, reconciliation, and configuration snapshots by exact
Conversation and Run identity.
