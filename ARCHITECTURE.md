# Mentat architecture and capability contract

## What Mentat is

Mentat is a local operations console for planning work and running agents. It
owns Agent, Task, Run, and event records. Agent runtimes execute the work.
Hermes is the first supported runtime.

The migration keeps the current Python app working while new parts are added.
Python owns local data, Hermes access, and the existing safety checks. New
runtimes must use small, named capabilities instead of direct access to runtime
files.

Mentat may read supported Hermes state. It may change Hermes only through an
approved adapter operation. It must never edit Hermes core files directly.

## Current local layout

The Python app and `public/` interface remain the default product on port 8888.
The optional Next.js preview runs on port 8890. Both listen only on loopback.

```text
Browser
  -> Node gateway on 127.0.0.1:8890
  -> fixed same-origin API route
  -> private Python Local Bridge
  -> Mentat data and Hermes adapters
```

Node is the only browser-facing process in the preview. Python remains the
authority for SQLite, files, credentials, Hermes, Tasks, Runs, and Agents.

## Node preview boundary

The preview requires Node `>=24.19.0 <25`. Build `web/` and start it with:

```bash
npm --prefix web run build
python scripts/mentat_web_preview.py
```

The supervisor creates a private token, starts the Python bridge on an
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
read-only `/api/agents`, `/api/tasks`, `/api/runs`, and selected-Run timeline
route. Node builds each private request on the server, checks its bounded
response, and returns only the route's safe public fields. The Agent route exposes canonical Mentat IDs,
names, runtime types, runtime configuration IDs, and declared capabilities. It
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

The selected-Run timeline is one bounded same-origin SSE stream. Node validates
the Run ID and browser reconnect cursor, polls one fixed authenticated bridge
capability, emits a keepalive, and regularly closes so the browser reconnects.
It returns at most 100 retained normalized events: ID, Run ID, sequence, type,
timestamp, summary, and approved numeric usage metrics. It sends an explicit
reset when history is missing or shortened. Event content, data payloads,
runtime references, and browser-selected limits or bridge paths never cross
this boundary. Only one timeline is active in the Runs workspace at a time.

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
- Canonical Mentat Agents are persisted in an independently versioned,
  owner-private `agent-registry.sqlite3`, separately from the schema-versioned
  Console database and from one-to-one adapter runtime configurations. The runtime configuration retains
  the private runtime-owned Agent reference; ordinary browser projections omit
  that reference and expose only Mentat identity, runtime type/config identity,
  and declared capabilities. The local registry is transactionally capped at
  128 Agents so create/list responses and private recovery remain bounded.
- The additive registry supports create/list behavior only during its first
  slice. It does not auto-import or mutate Hermes profiles, store credentials,
  dispatch tasks, edit/delete Agents, or replace heartbeat observations.
- A Hermes **session** remains conversation history owned by a specific Hermes
  profile and is a runtime reference, not Mentat workflow authority.
- Durable Agent persistence remains additive without inventing profile-derived IDs.

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
the old build import exactly if that sibling is later upgraded. The schema-7
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

Released format-2 and format-3 backups with exact Console schema 4, 5, or 6
remain valid and migrate transactionally to schema 7. Current backups retain
Tasks, Runs, AgentEvents, dispatch state, and both authority receipts as one
recovery unit. To downgrade after live Task
mutations, stop Mentat, preview `mentat task-export --compatible-root`, confirm
its exact token, and point the older build at the reported schema-5 sibling
data-root name. Restoring a pre-cutover backup remains an alternative that
discards later Task mutations. Mentat never uses stale `tasks.json`
automatically and never downgrades the authoritative schema-7 source database.

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
short compare-and-swap leases, revalidates the separate Agent Registry binding,
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

Hermes 0.20's A2A, grounded-citation, deliverable-artifact, and voice surfaces
do not inherit webhook authority merely because they share a release. A2A is a
separate bidirectional execution boundary; citations remain untrusted response
Markdown until a structured provenance API exists; local artifacts remain
restricted to Mentat's run-owned export boundary (with remote Kanban artifacts
using the authenticated custom-host artifact API and stock 0.20.1 degrading to
summary-only); and voice requires explicit browser
audio privacy plus transport-advertised interruption semantics. Mentat does not
parse assistant prose for local paths, `MEDIA:` directives, citation authority,
audio, or transcripts. The complete decisions and future entry gates are in
[HERMES_020_PRODUCT_DECISIONS.md](HERMES_020_PRODUCT_DECISIONS.md).

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

In the current Hermes compatibility mode, Agent Console execution is globally
single-run. This is a Hermes adapter capacity constraint, not the target Mentat
orchestrator concurrency model.
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

The runtime-neutral Agent registry is available at
`/api/orchestration/agents`, separate from the legacy `/api/agents` heartbeat
projection. Creation is serialized with the durable backup/restore boundary,
stores the Agent and Hermes binding atomically, accepts only a registered
runtime, and never returns the adapter-owned runtime reference. A configured
Agent authorizes work only through an exact Task assignment, capability match,
binding snapshot, and durable dispatch reservation. Backup format 3 includes
and semantically validates the registry;
pre-registry format-2 backups remain restorable and produce an empty registry.

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
queue, and Agent Console remains an interactive, globally single-run
conversation surface; neither is a durable dispatcher.

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
CLI. `/steer` is a remote-control command, not CLI passthrough: it dispatches
the same fixed, revision-bound server operation as the active Console's Steer
button.

Remote active-run steering is available only when Hermes advertises
`run_steer` with the exact `POST /v1/runs/{run_id}/steer` endpoint. Mentat
requires a running remote run bound to the current connection, profile,
transport instance, and local control revision; it verifies status before the
mutation, validates Hermes' exact acceptance response, and reads the same run
back afterward. An accepted action whose read-back fails is reported as a
partial failure and is never retried automatically. The steer text and remote
run identifier remain private and are not persisted; only a bounded text-free
status event enters Console history.

While a compatible run is active, the existing Console textbox remains
writable but changes visibly and accessibly from Send mode to text-only Steer
mode. Attachments, ordinary Send, new-session, profile/provider changes, and
parallel run submission remain locked. Local one-shot CLI runs and remote hosts
without the exact capability keep the composer locked. Stop remains a separate
hard-stop control. Attachment steering remains unavailable until Hermes
advertises a versioned media contract with exact bounds and verifiable
read-back.

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

Mentat retains one active dashboard run globally for the first version. This
can be revisited after profile-scoped execution and cancellation are proven.
