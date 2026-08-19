# Feature Slice Review: SQLite Run, AgentEvent, and Dispatch Authority

Slice: `mentat-sqlite-run-event-dispatch` (Pivot 1C-C)

Branch: `codex/sqlite-run-event-dispatch`

Base: merged `origin/main` at `bb9377e`

## Slice contract

Make the existing owner-private `mentat.sqlite3` authoritative for Mentat Runs
and normalized AgentEvents, then route assigned Task execution through one
runtime-neutral dispatch service. Durable intent must commit before the one
external runtime submission attempt. Uncertain acceptance must remain visible
and reconcile without blind resubmission.

This slice includes:

- additive schema migration for canonical Runs, append-only AgentEvents,
  idempotent dispatch reservations, and retention metadata;
- exact migration of validated Mentat-owned Console summaries into SQLite;
  schema-3 events retain only their already-versioned IDs and sequences, while
  older unverifiable timelines import no invented events and are marked
  truncated;
- retirement of the private Console history JSON file as a runtime source or
  write target; any retained JSON representation is derived compatibility or
  export evidence only;
- a repository that validates every persisted value, allocates monotonic event
  sequences transactionally, treats identical event retries as idempotent, and
  rejects conflicting duplicates;
- a runtime-neutral dispatch service that resolves the assigned Agent and its
  current private runtime binding, commits an exact Task-revision reservation,
  Run snapshot, and first event before invoking `AgentRuntime.submit_task()`;
- at-most-one adapter invocation per exact Task revision, durable
  accepted/rejected/unknown outcomes,
  exact Mentat Run identity across the adapter boundary, and no automatic retry
  after an ambiguous external result;
- startup and explicit reconciliation for reserved/submitting/unknown Runs,
  using authoritative runtime status when a verified runtime reference exists;
- fixed retention: preserve every active or waiting Run; retain the newest 250
  terminal Runs; retain at most 1,000 normalized events or 4 MiB of event
  content per Run; also enforce a fixed global count/content budget, compact
  only contiguous oldest prefixes, and mark every truncated timeline explicitly;
- versioned, cursor-based Run/Event read APIs whose projections contain no
  credentials, local paths, raw Hermes payloads, chain-of-thought, or arbitrary
  tool arguments/results;
- WAL-safe backup/restore validation for the new tables and compatibility with
  supported older private-unit database schemas;
- unchanged loopback, request-boundary, attachment/blob, Task, Agent Registry,
  and Hermes capability protections.

This slice excludes:

- a second runtime, dynamic routing, supervisors, A2A/MCP delegation, shared
  tools, credential consolidation, or Agent Registry database convergence;
- Next.js/React/Tailwind UI work or removal of the existing static frontend;
- direct Hermes database/file writes, arbitrary runtime command passthrough,
  blind dispatch retries, or invented legacy event timelines;
- configurable archival policy beyond the fixed initial retention contract;
- final obsolete-path cleanup and Lighthouse publication gates, which remain
  Slice 1C-D.

### Approved implementation correction — transitional Console bridge

On 2026-08-18 the user explicitly directed the slice not to invest heavily in
legacy Console-bridge recovery because Mentat will move away from that bridge.
The bridge must still preserve preallocated Mentat Run identity, avoid leaking
dispatch correlation, and remain compatible for current execution. It will not
gain a new bridge-specific durable restart subsystem. Generic adapters may
reconcile through the runtime-neutral contract; when the transitional bridge
cannot authoritatively reattach after restart, SQLite records the Run as
`interrupted` or `unknown` and never resubmits it. Native Hermes correlation is
a follow-up adapter concern and does not change the SQLite Task/Run/Event model.

## Acceptance criteria

| ID | Requirement | Required evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Schema migration is additive, transactional, owner-private, repeatable, and rejects forward/corrupt schemas. | Empty/current/legacy/forward/corrupt database tests and schema inspection. | Pass |
| AC-2 | SQLite is the sole runtime authority for Runs and normalized AgentEvents; no live path reads or writes the legacy history JSON after cutover. | Source-contract scan, restart tests, and deleted/stale/changed history-file tests. | Pass |
| AC-3 | Run snapshots bind immutable Task revision, Task input, Agent ID, runtime type/config ID, capabilities, and timestamps without credentials or adapter-private payloads. | Repository round-trip, bounds, privacy, and corruption tests. | Pass |
| AC-4 | Dispatch commits reservation + Run + first event before exactly one runtime call; duplicate requests are idempotent and conflicting/stale requests fail before execution. | Fault injection, call-order, duplicate, stale-revision, binding-change, and concurrency tests. | Pass |
| AC-5 | Accepted, rejected, and uncertain submissions become honest durable states; uncertain acceptance is never blindly resubmitted. | Runtime failure matrix and restart/reconciliation tests. | Pass |
| AC-6 | AgentEvents are append-only, strictly monotonic per Run, idempotent by stable key/content, and conflicting duplicates fail closed. | Concurrent append, rollback, gap, duplicate, conflict, and corruption tests. | Pass |
| AC-7 | Reconciliation is binding-aware and authoritative, never converts missing evidence into completion, and marks unrecoverable active work interrupted/unknown. The transitional Console bridge is not required to gain a new durable remote-reattachment subsystem. | Generic status-readback, CAS/lease, restart interruption, and no-resubmission tests. | Pass |
| AC-8 | Retention preserves active/waiting Runs, keeps the newest 250 terminal Runs, enforces 1,000 events/4 MiB per Run, protects referenced attachments, and exposes truncation metadata. | Boundary, active-protection, attachment, deterministic-order, and cursor-gap tests. | Pass |
| AC-9 | Versioned Run/Event APIs expose stable bounded projections and cursor semantics while existing Console behavior remains compatible. | Handler/request-boundary tests plus browser smoke. | Pass |
| AC-10 | Backup/restore snapshots include and semantically validate Runs, events, reservations, retention boundaries, Tasks, attachments, and the separate Agent Registry unit. | Live-WAL round-trip, older-format restore, corruption, rollback, and count evidence. | Pass |
| AC-11 | Documentation identifies SQLite authority, the separate Agent Registry boundary, recovery behavior, and later Slice 3C database convergence. | Architecture, roadmap, operations, and changelog inspection. | Pass |
| AC-12 | Focused suites, full suite, artifact/secret checks, browser smoke, hosted multi-platform CI, and two independent adversarial reviewers pass. | Command log, CI links, and reviewer rounds below. | Local gates and reviewers pass; hosted CI pending publication |

## Invariants and lock order

1. Acquire the project-owned private-state lock before opening or mutating the
   main database; use the existing database-open barrier only inside that
   boundary.
2. Never hold a SQLite transaction or the Console in-memory lock while calling
   an external runtime.
3. Resolve and validate the Agent Registry binding before reservation, then
   compare the exact binding again before submission. A changed binding records
   a durable non-submitted failure; it never falls back to a profile name.
4. The reservation owns one idempotency key and exact Task revision. A committed
   reservation can produce at most one external adapter invocation. The durable
   per-Task dispatch head survives Run pruning and prevents the same Task
   revision from being dispatched again.
5. A Run's Mentat ID is allocated before adapter invocation and is distinct
   from any private runtime-owned run reference.
6. Event sequence allocation and Run-state projection commit together. Terminal
   states cannot transition back to active states.
7. Retention obtains the same private-state/database transaction boundary as
   ordinary writes and deletes only terminal Runs after reference checks.

## Test strategy

- New focused repository tests cover schema, validation, append-only behavior,
  idempotency, concurrency, retention, and malformed database rows.
- Dispatch service tests use fake runtimes and fault injection to prove commit
  ordering, exactly-one invocation, stale/binding conflicts, uncertain outcomes,
  and reconciliation without retries.
- Server integration tests exercise real `HermesRuntime` compatibility handlers,
  restart recovery, Console payload compatibility, and cursor projections.
- Migration tests cover absent, valid, malformed, changed, oversized, linked,
  and already-cut-over legacy history; unverifiable timelines become explicitly
  truncated rather than synthesized.
- Private-unit and general backup/restore tests cover live WAL, prior schemas,
  semantic corruption, recovery rollback, and attachment reachability.
- Regression gates include Task repository, Agent Registry, Console, remote
  Hermes, webhook concurrency, request boundary, browser smoke, full unittest,
  package inventory, secret scan, and hosted platform/native-artifact CI.

## Threat and failure matrix

| Risk | Prevention | Proof |
| --- | --- | --- |
| External work starts without durable intent | Commit reservation, Run, and first event before adapter call. | Call-order/fault-injection tests. |
| Ambiguous submission duplicates work | One attempt flag; unknown status; reconcile only. | Timeout/restart tests with invocation counter. |
| Task or binding changes between preview and dispatch | Exact revision and binding snapshots with pre-call revalidation. | Race tests. |
| Event retry changes history | Stable idempotency digest and content comparison. | Identical/conflicting duplicate tests. |
| Retention removes live work or lies about replay | Terminal-only pruning and explicit first-retained sequence/truncated flag. | Limit/cursor tests. |
| Legacy JSON remains a hidden authority | Cutover receipt and source-contract assertions; stale file ignored. | Restart and source scans. |
| Backup creates dangling attachments or partial relational state | One WAL-safe filtered SQLite unit and semantic validation. | Round-trip/corruption tests. |
| Sensitive adapter data enters durable/browser state | Allowlisted normalized fields and bounded redaction. | Secret/path/raw-payload tests. |

## Review rounds

Round 0 used the same two independent reviewers as Slice 1C-B.

- Reviewer A required at-most-one invocation wording, preallocated Mentat Run
  identity, typed submission outcomes, a separate submission state, one SQLite
  authority for Console and task-dispatch Runs, a persistent per-Task dispatch
  head, SQLite-derived backup reachability, exact binding revalidation, durable
  runtime correlation, CAS reconciliation leases, and explicit truncation
  metadata.
- Reviewer B independently required distinct Mentat/runtime IDs, durable
  idempotency after Run pruning, contiguous-prefix and global retention bounds,
  schema 4/5/6/7 restore and schema-5 compatible export, removal of canonical
  field duplication inside JSON, a defined cross-database lock protocol, and
  one nonterminal Run per Task.
- Resolution: accepted. The contract and schema scaffold now use `console` and
  `task_dispatch` sources, preallocated IDs, reservation/head records, separate
  submission state, canonical columns with compatibility-only JSON, stable
  event source keys, CAS/lease fields, per-Run plus global retention metadata,
  and no automatic Task-completion inference. Legacy schema-1/2 timelines will
  not be synthesized; schema-3 evidence is imported only with exact existing
  identifiers and sequences. Backup/downgrade corrections remain required
  before AC-10 can pass.

### Round 1 — implementation diff

Both reviewers rejected the first implementation diff. Their independently
reproduced blocking findings are grouped here; all affected acceptance criteria
returned to pending until correction and re-review.

- SQLite Run authority and initial Console persistence could fail open, allowing
  runtime work to start with memory-only state.
- Dispatch claim did not atomically revalidate the current Task revision and
  assigned Agent, and submission outcome recording could overwrite an already
  advanced or terminal Run while validating only the Mentat Run ID.
- A valid retained schema-3 event suffix could not migrate, duplicate legacy Run
  IDs silently merged, and the occupied-destination check omitted dispatch heads.
- Never-attempted reservations had no restart resolution; reconciliation omitted
  queued Runs, allowed status regression, ignored the persisted runtime-owned Run
  reference, and made unknown-to-accepted reservation/Run state inconsistent.
- Runtime event polling had no durable source cursor, retained-event deletion
  could erase deduplication evidence, and redacted event retries compared against
  unnormalized input.
- Dispatch/reconciliation event writes did not enforce global or terminal
  retention transactionally, reservation expiry was not collected, and semantic
  validation omitted per-Run and terminal limits.
- Run schema checks did not fingerprint exact tables/indexes, so dropping the
  one-active-Run partial index was not detected.
- Claimed concurrency coverage used sequential calls rather than controlled
  races. HTTP `limit=100` lookahead and malformed idempotency-key behavior also
  need correction, and `DATA_LAYOUT.md` still named the prior slice as active.

Resolution status: **corrected locally; Round 2 re-review pending**. Initial Run
persistence now fails closed; dispatch claim and outcome use transactional
revalidation and compare-and-swap identity checks; restart states are explicit
and never resubmitted; native runtime references remain reconcilable while the
transitional Console bridge receives only minimum truthful interruption/unknown
handling. Exact schema fingerprints, retained-suffix migration, duplicate-ID
rejection, forward-only reconciliation, durable runtime-event cursors, bounded
paging, transactional retention, and real controlled concurrency tests address
the remaining Round 1 findings. No bridge-only durable reattachment subsystem
was added.

### Round 2 — corrected implementation diff

Both original reviewers rejected Round 2. The combined blocking set is:

- valid schema-3 history that pins an old `runtime.bound` event before the
  contiguous newest suffix still fails exact migration;
- normal live Console rolling windows reset migration metadata and stop
  persisting after the 40-event boundary;
- restart recovery updates a `submitting` reservation but can leave a
  worker-advanced Run with a conflicting dispatch state;
- a Task mutation between reservation and claim prevents execution but leaves
  the reservation active and escapes the bounded service/API error boundary;
- post-start Console persistence failures can leave volatile memory presented
  ahead of authoritative SQLite;
- a valid maximum-retention SQLite store can exceed the legacy 4 MiB
  compatibility-history member during backup;
- legacy-history permission repair can chmod an unsafe hardlink before
  rejecting it;
- accepted Runs with durable runtime references receive no bounded automatic
  reconciliation pass after startup; and
- the service can expose the adapter's original `accepted` disposition after
  converting an identity-mismatched outcome to durable `unknown`.

Resolution status: **corrected locally; Round 3 re-review pending**. Migration
now preserves the exact newest contiguous suffix while retaining Task/Agent
binding in canonical columns, and live rolling windows advance rather than
reset the durable cursor. Restart repair preserves worker-advanced states;
claim-time Task changes are durably rejected through a bounded service error;
identity-mismatched acceptance is returned as `unknown`. The backup keeps a
separately bounded legacy projection without dropping canonical SQLite Runs or
attachments, unsafe linked history is rejected before chmod, and startup runs
one bounded native reconciliation pass. A post-start bridge persistence failure
reloads SQLite, exposes a degraded state, blocks new work and controls, and
requires restart after storage repair. Per the accepted legacy scope, no new
bridge reattachment or high-availability recovery subsystem was added.

### Round 3 — complete corrected slice

Both original reviewers rejected Round 3. Peer critique independently
maintained every unique finding, with two refinements: the private unit permits
96 MiB overall but only 64 MiB for the database member, and the 10,000-Run
admission defect is medium rather than high under the current 2,048-Task product
limit. The accepted blocking set is:

- schema-7 capture still opened stale legacy JSON before checking SQLite
  authority, and task-dispatch Runs could not hydrate through the Console-only
  compatibility shape;
- database setup exceptions escaped the degraded-storage boundary, stale
  compatibility summaries could regress terminal Runs, and permission repair
  retained a lexical-path-to-descriptor hardlink replacement race;
- exact idempotency retry incorrectly depended on current Task state, while a
  new revision with an older active/unknown Run leaked a unique-index error;
- semantic validation accepted impossible coordinated Run/reservation states;
- valid Run state was not closed under total Run capacity or the private backup
  database ceiling; and
- schema-5 downgrade retained attachments/blobs belonging to Runs omitted from
  its bounded legacy projection, while module documentation described only the
  older reachability model.

Resolution status: **corrected locally; Round 4 verification and re-review
pending**. Schema-7 capture now establishes authority before legacy-history
handling and projects only Console-source compatibility Runs. Database failures
enter a data-root-scoped degraded state; terminal state is forward-only; both
legacy readers and permission repair bind lexical and descriptor identity and
link count. Durable retries resolve before mutable state, active Task conflicts
are bounded, and validation enforces produced state combinations. Execution
snapshots contain only the exact runtime-facing Task contract, every Run
mutation enforces a 48 MiB compact-store budget below the 64 MiB backup member,
Run-count admission prunes only safe terminal history and otherwise rejects,
and schema-5 export filters its attachment/blob graph to projected Run IDs.
These corrections add no legacy reattachment or high-availability subsystem.

### Round 4 — complete corrected slice

Both original reviewers rejected Round 4. Cross-review maintained the complete
blocking set, narrowing only the event-data wording and generic schema-history
references:

- Task snapshot validation was unreachable, so malformed or unrelated execution
  input could pass repository and backup validation;
- AgentEvent JSON was digest-checked without semantic reconstruction, allowing a
  correctly rehashed invalid metric payload to pass backup but fail API reads;
- database setup failures could still escape startup, dispatch, post-submission,
  and reconciliation boundaries without a bounded unavailable result;
- valid retained attachments could exceed the private-unit count or aggregate
  byte limits before backup; and
- contributor/recovery documentation still named schema 6 as current and the
  dispatch contract still named the removed `start_task()` boundary.

Resolution status: **corrected locally; Round 5 re-review pending**. Repository
validation now reconstructs the exact allowlisted Task execution snapshot and
AgentEvent contract, requires canonical bounded JSON, and rejects identity,
status, metric, timestamp, source, or private-field corruption before backup or
API use. Connection creation is translated at repository/service boundaries and
defensively handled by startup/API paths; an outcome-store failure after an
external call remains a single durable `submitting` attempt and cannot trigger
automatic resubmission. Attachment binding enforces 100-distinct-blob and 24 MiB
referenced-byte budgets transactionally, with backup validation using the same
limits and pre-existing over-limit roots failing closed. Schema-7 and
`submit_task()` documentation is current. These are canonical SQLite, admission,
and recovery guarantees; no legacy Console transport feature was added.

### Round 5 — complete corrected slice

Both reviewers rejected Round 5. Cross-review merged their overlapping Run-row
findings and maintained the complete blocking set:

- canonical Task requirements were not proven to be a subset of the immutable
  Run capability snapshot, and reservation request digests were not reconstructed
  during semantic validation;
- persisted Run timestamps, runtime identity, capability element types/order,
  and terminal timestamp nullability were not reconstructed before backup or
  public projection;
- a correctly rehashed event could retain a `source_type` contradicting its
  normalized `event_type`; and
- Run list/detail/event and Task-deletion safety reads omitted
  `MentatDatabaseError`, producing generic 500 responses on database setup
  failure instead of bounded 503 results.

Resolution status: **corrected locally; Round 6 re-review pending**. A shared
strict Run-row validator now protects both repository validation and public
record projection. It validates source/state, IDs, runtime type/configuration,
canonical sorted unique capabilities, timezone-aware timestamps, counters, and
task-dispatch terminal timestamp nullability. Task snapshot requirements must be
available in the Run capability snapshot; dispatch request digests are built
from that exact execution snapshot and reconstructed against reservations.
AgentEvent validation applies the same source-to-normalized-type mapping used at
insertion. Every direct Mentat SQLite read in scope translates setup failures to
the documented bounded unavailable result. Repository, backup, pagination/read,
and deletion-preview fault regressions cover each correction. No legacy bridge
feature was added.

### Round 6 — complete corrected slice

Both reviewers rejected Round 6. Cross-review maintained five closure findings:

- canonical typed AgentEvents could be inserted successfully and then rejected
  by validation because already-normalized source types were remapped as raw
  adapter aliases;
- terminal Run rollover left accepted/rejected reservations detached from Runs
  without a defined idempotency-tombstone validation contract;
- schema-3 event IDs wider than the normalized 128-character domain could fail
  only after the authority receipt committed;
- canonical 160-character/`@` Task IDs did not survive the runtime/Run model; and
- Run, reservation, and dispatch-head identifiers, digests, and timestamp
  chronology were not completely reconstructed.

Resolution status: **corrected locally; Round 7 re-review pending**. Canonical
event types now validate by exact equality while only raw source aliases use the
status-aware mapper, and all canonical event types pass append plus backup.
Terminal accepted/rejected reservations remain as validated at-most-once
tombstones tied to a same-or-newer Task dispatch head until existing expiry
cleanup; no reservation is destructively removed merely to satisfy retention.
Normalized events use one 128-character ID boundary, schema-3 input is strict,
and complete semantic validation runs inside the authority transaction. A
distinct 160-character Task-ID validator is used by Tasks, runtime contexts,
AgentRuns, persistence, service dispatch, and Task APIs. Run/reservation/head
IDs, request bindings, timezone-aware timestamps, and created/updated chronology
are reconstructed, and event appends cannot regress Run update time. Boundary,
rollback, retention+1 backup, wide Task dispatch, and isolated corruption tests
cover these contracts. No legacy bridge feature was added.

### Round 7 — complete corrected slice

Both reviewers rejected Round 7. Cross-review consolidated the findings into
four canonical-boundary defects:

- server Task editing and dependency graph construction truncated exact Task
  IDs to 80 characters, allowing collisions and broken references;
- production Hermes Console identity, retained binding hydration, and final
  projection still applied the narrower opaque-ID grammar to 160-character or
  `@` Task IDs;
- reconciliation composed `runtime:<event-id>` source keys that could exceed
  the event-ID grammar even though source keys intentionally have a wider
  domain; and
- canonical schema-3 event types could be remapped by legacy status aliases,
  while supported writes needed an explicit pre-commit chronology closure.

Resolution status: **corrected locally; Round 8 verification and re-review
pending**. Task edits, dependency graphs, reorder, delete, production Hermes
submission, retained-history binding, and final projection now preserve and
validate the exact canonical Task ID. Event IDs remain bounded to 128
characters while source keys use their separate 160-character domain; a
maximum-width runtime event reconciles, validates, and backs up. Schema-3
migration preserves every canonical `AgentEventType` exactly. Every repository
mutation validates Run/reservation/head chronology before commit and rolls back
clock-regressing claim and recovery writes. Per the user's explicit direction,
these corrections add no legacy Console capability or restart subsystem; they
only keep the temporary adapter from corrupting canonical SQLite identity.

### Round 8 — complete corrected slice

Both reviewers rejected Round 8. Cross-review maintained the complete blocking
set:

- replaying one already-ingested runtime event under a larger source sequence
  could advance the durable cursor and skip unseen events;
- an exact idempotency retry could lose to mutable Task state after the outer
  lookup released its lock;
- Run `details_json` was only object-decoded, so unapproved private fields could
  survive validation and backup;
- a valid maximum-width dispatch ID produced an invalid derived event ID;
- Run authority and active task-dispatch Runs did not prove their Task-authority
  and canonical-Task prerequisites; and
- missing and malformed Task dispatch requests leaked repository codes and the
  wrong HTTP status.

Resolution status: **corrected locally; Round 9 re-review pending**. Duplicate
runtime events can no longer advance the source cursor; the reservation boundary
rechecks durable idempotency under the same lock before consulting mutable Task
or Agent state. Source-aware exact detail schemas reject unknown, noncanonical,
unbounded, or secret-bearing values before reads and backup. Derived reservation
event IDs are fixed-width hashes. Every task-dispatch Run requires SQLite Task
authority, every active or unknown task-dispatch Run requires its canonical Task
row, and Console-only compatibility history remains independent of Task
authority so this slice does not expand the outgoing bridge. Dispatch API errors
now expose stable `task_not_found`/404 and `task_id_invalid`/400 semantics. The
temporary Console summary projection may update status but cannot overwrite a
task-dispatch Run's canonical details.

### Round 9 — complete corrected slice

Both reviewers rejected Round 9. Their compatibility-read finding overlapped;
Reviewer A also demonstrated a nested attachment-metadata backup leak:

- attachment and artifact normalization preserved untyped timestamp values, so
  a nested credential object could survive semantic validation and backup; and
- Console-summary and AgentEvent list reads projected rows without applying the
  strict Run/event validators, allowing secret-bearing details or a modified
  event with a stale digest to reach callers.

Resolution status: **corrected locally; Round 10 re-review pending**. Retained
media metadata now has an exact canonical scalar shape, bounded/redacted display
strings, allowlisted states, timezone-aware string timestamps, and derived
content URLs; malformed nested values are discarded on write and rejected if
found in authoritative storage. Compatibility Run reads validate the complete
Run row and exact details before hydration. Event reads validate semantic type,
canonical JSON, source agreement, parent identity, byte count, and payload digest
before returning an event. Exact exploit regressions prove backup and both read
paths fail closed.

### Round 10 — complete corrected slice

Both reviewers rejected Round 10. Their findings identified three remaining
canonical-projection gaps:

- Console compatibility summaries projected AgentEvents without validating
  semantic identity, byte count, or payload digest;
- a recomputed unkeyed digest could legitimize secret-bearing event summary or
  content because canonical redaction was not reconstructed; and
- retained media names used host-dependent `Path.name`, allowing Windows paths
  to survive normalization on POSIX.

Resolution status: **corrected locally; Round 11 re-review pending**. Every event
projected through Console summaries now passes the same complete validator as
the new event API. Stored summary and content must equal the bounded, redacted
canonical form even when a payload digest has been recomputed. Retained media
names reject both slash forms before platform path handling. Exact regressions
cover stale-digest forged Console bindings, rehashed secret event text through
validation/read/backup, and POSIX plus Windows media paths.

### Round 11 — complete corrected slice

Reviewer B approved Round 11. Reviewer A rejected it for one remaining
append-only history gap: read paths validated individual events but did not
reconstruct continuity of the complete retained event window, so deleting an
interior event could return sequences 1 and 3 while advertising no cursor reset.

Resolution status: **corrected locally; Round 12 re-review pending**. One shared
event-window validator now enforces per-Run count/byte retention, sorted unique
contiguous sequences, first/last cursor agreement, empty-window semantics,
truncation metadata, and every event's complete canonical validator. Repository
validation, filtered event reads, and Console compatibility hydration all use
that same contract before projection. An exact interior-deletion regression
requires both read paths to fail closed.

### Round 12 — complete corrected slice

Both reviewers rejected Round 12 for the same prefix-loss gap; Reviewer B also
identified that Run list/detail projection validated Run metadata without its
associated event window:

- a non-truncated retained window beginning at sequence 2 still passed because
  only internal continuity, not the required sequence-1 prefix, was checked; and
- public Run list/detail could advertise healthy timeline metadata for a Run
  whose event window would fail the event endpoint.

Resolution status: **corrected locally; Round 13 re-review pending**. A
non-truncated event window must now begin at sequence 1, while a truncated empty
or suffix window remains governed by its explicit tombstone metadata. Public
repository Run list/detail validate the associated complete event window before
projection; internal mutation reads use a private row-only path until retention
finishes, avoiding false failures at the temporary retention+1 boundary. Prefix
and interior deletion regressions cover repository event/summary/list/detail
reads, and server Run list/detail return bounded 503 results on timeline loss.

### Round 13 — complete corrected slice

Reviewer A approved Round 13. Reviewer B rejected it for one return-value
consistency defect: rejection, submission-outcome, and reconciliation mutations
captured their returned Run before retention updated timeline metadata, so the
returned value could differ from the committed row.

Resolution status: **corrected locally; Round 14 re-review pending**. Those
mutations now apply retention first and then perform the same fully validated
Run reread used by public callers. The temporary unvalidated mutation reread was
removed entirely. A one-event-retention orchestration regression asserts the
dispatch mutation result exactly equals the committed post-retention Run.

### Round 14 — approved

Both independent reviewers approved Round 14 with no blocking findings. The
accepted closure includes strict SQLite Task/Run/Event authority, durable
dispatch idempotency and reconciliation, bounded retention and backup,
fail-closed public projections, canonical privacy validation, and exact
post-retention mutation returns. No new legacy Console capability was added.

## Verification log

| Command or review | Environment | Result | Evidence |
| --- | --- | --- | --- |
| Contract baseline inspection | Isolated branch from merged `main` | Pass with corrections | Roadmap, system-design reference, current Run/Event/Console/backup code inspected; both independent reviewers returned P0/P1 corrections and no files were delegated for editing. |
| `python -m unittest tests.test_run_repository -v` | macOS, schema/repository scaffold | Pass | 8 tests passed after the first reviewer-driven schema corrections. |
| Focused SQLite orchestration suites | macOS, Python 3.13 | Pass | 142 tests passed in 65.138s across Run repository, orchestration service, Hermes production bridge, migration/history, deletion, private backup, Task repository, artifacts, and runtime architecture. |
| Corrected orchestration and compatibility suites | Clean isolated data root, macOS, Python 3.13 | Pass | 211 tests passed in 69.256s across schema-7 Run/Event/dispatch authority, controlled races, migration, backup/restore, Task authority, Console compatibility, artifacts, and local/remote Hermes integration. |
| `python -m unittest discover -s tests -q` | Clean isolated checkout state, macOS host execution | Pass | 1,219 tests passed in 185.152s; 4 skipped. Loopback/request-boundary tests ran outside the sandbox. |
| `git diff --check`; Python compile; Node syntax | Isolated branch | Pass | No whitespace errors; changed Python modules compiled; repository compileall and `public/core.js`, `public/app.js`, and browser-smoke syntax checks passed. |
| `python scripts/check_tracked_secrets.py` | Disposable venv from hash-pinned `requirements-quality.lock` | Pass | No unreviewed secret-like values. |
| `python -m pip_audit -r requirements.txt --strict --progress-spinner off` | Disposable quality venv with live vulnerability data | Pass | No known vulnerabilities. |
| `python -m pip_audit -r requirements-native.lock --strict --progress-spinner off` | Disposable quality venv with live vulnerability data | Pass | No known vulnerabilities. |
| `node scripts/browser_smoke.mjs` | Chromium against loopback server and disposable schema-7 data root | Pass | All 46 reported responsive, accessibility, Console, Task, calendar, Agent, Context Pack, Settings, and diagnostics check groups passed. |
| Clean sdist/wheel build plus `scripts/verify_python_artifacts.py` | Disposable hash-pinned build environment | Pass after correction | The first artifact check exposed missing package declarations for the two new modules. `pyproject.toml` and the exact artifact inventory now include `orchestration_service.py` and `run_repository.py`; the rebuilt wheel and sdist passed exact-content/integrity verification, and 34 packaging/quality-gate tests passed. |
| Round 2 migration/restart/dispatch/backup corrections | macOS, Python 3.13 | Pass | 50 focused repository, orchestration, startup-reconciliation, hardlink, rolling-window, identity-mismatch, and bounded-backup tests passed in 7.291s. |
| Transitional Console degraded-storage correction | macOS, Python 3.13 | Pass | 78 history, steer, and remote-Console tests passed in 2.392s; the new fault-injection test proves volatile state is replaced by SQLite state and controls/new work fail closed. |
| Final corrected full suite | macOS host/loopback, Python 3.13 | Pass | 1,228 tests passed in 193.700s; 4 skipped. An initial sandbox run exposed seven expected socket denials and two direct-run fixtures that lacked a durable-persistence mock; the fixtures were corrected without weakening production behavior. A subsequent host run exposed degraded-state test leakage across changed data roots; degraded state is now scoped to its exact configured data directory, and the final host run passed. |
| Round 3 static, secret, packaging, and artifact gates | Isolated branch and existing hash-pinned quality environment | Pass | `git diff --check`, Python compile, Node syntax, tracked-secret scan, 34 packaging/quality tests, a no-isolation wheel/sdist build from the already pinned environment, and exact artifact verification passed. The first isolated build attempt was infrastructure-only: network-restricted pip could not fetch already pinned build requirements. |
| Round 3 browser smoke | Chromium, loopback server, disposable schema-7 fixture | Pass | All 46 reported responsive, accessibility, Console, Task, calendar, Agent, Context Pack, Settings, and diagnostics check groups passed. The first attempt used unmigrated tracked seed data and was correctly blocked before serving; rerun against the existing disposable schema-7 fixture passed. |
| Round 4 focused correction suites | macOS, Python 3.13 | Pass | 168 Run repository, orchestration, history/degraded-storage, private-unit, and Task/export tests passed in 79.561s. New regressions cover all Round 3 findings, including a real 250-terminal-Run backup boundary and controlled POSIX hardlink replacement. |
| Round 4 full suite and static gates | macOS host/loopback, Python 3.13 | Pass | 1,239 tests passed in 198.636s; 4 skipped. `git diff --check`, changed-Python compilation, and Node syntax checks also passed. |
| Round 4 packaging, secret, artifact, and browser gates | Existing hash-pinned quality environment; Chromium loopback | Pass | Tracked-secret scan, 34 packaging/quality tests, no-isolation wheel/sdist build, exact artifact verification, and all 46 browser-smoke groups passed. Generated build metadata was moved out of the worktree. |
| Round 5 focused correction suites | macOS, Python 3.13 | Pass | 137 repository, orchestration, private-unit, startup/degraded-storage, and attachment tests passed in 59.354s. Regressions cover canonical Task snapshots, semantically invalid rehashed events, startup/pre-submit/post-submit database setup failures, the exact 100-blob boundary, and an exact aggregate-byte boundary. |
| Round 5 full suite | macOS host/loopback, Python 3.13 | Pass | 1,246 tests passed in 201.765s; 4 skipped. |
| Round 6 focused correction suites | macOS, Python 3.13 | Pass | 142 repository, orchestration, private-unit, startup/degraded-storage, and attachment tests passed in 59.795s. Added exact Run-row, capability/request binding, rehashed event-source mismatch, backup corruption, Run-read 503, and Task-deletion safety regressions. |
| Round 6 full suite and static gates | macOS host/loopback, Python 3.13 | Pass | 1,251 tests passed in 205.321s; 4 skipped. `git diff --check`, changed-Python compilation, and the tracked-secret scan passed. |
| Round 7 focused correction suites | macOS, Python 3.13 | Pass | 146 repository, orchestration, private-unit, startup/degraded-storage, and attachment tests passed in 61.078s. Added canonical-event closure, event-ID rollback boundaries, 160-character/`@` Task dispatch, retention+1 tombstone backup, timestamp/ID corruption, and non-regressing event-time coverage. |
| Round 7 full suite and static gates | macOS host/loopback, Python 3.13 | Pass | 1,255 tests passed in 209.485s; 4 skipped. `git diff --check`, changed-Python compilation, and the tracked-secret scan passed. |
| Round 8 targeted correction regressions | Clean isolated data roots, macOS, Python 3.13 | Pass | 13 targeted tests passed. They cover exact maximum-width Task IDs across edit/dependency/reorder/delete/history/production Hermes/finalization, every canonical schema-3 event type through backup, maximum-width reconciliation source keys, and pre-commit clock-regression rollback. |
| Round 8 focused correction suites | macOS, Python 3.13 | Pass | 206 repository, orchestration, private-unit, migration/history, artifact, Task authority/deletion, production Hermes, and runtime-architecture tests passed in 88.037s. Expected fault-injection diagnostics remained bounded. |
| Round 8 full suite | macOS host/loopback, Python 3.13 | Pass | 1,264 tests passed in 206.434s; 4 skipped. The initial sandbox run had exactly seven loopback socket denials and no product failures; the identical host run passed every test. |
| Round 8 static and secret gates | Isolated branch; existing hash-pinned quality environment | Pass | `git diff --check` and repository-wide Python compilation passed. The direct secret wrapper first reported its caller lacked `detect-secrets`; rerunning unchanged in the existing pinned quality environment passed with no tracked-file findings. |
| Round 8 packaging contracts and frontend syntax | Isolated branch, Python 3.13 and Node | Pass | All 34 packaging/quality-contract tests passed in 6.991s, and `public/core.js` passed Node syntax validation. No packaging manifest or rendered UI behavior changed during Round 8. |
| Round 8 clean wheel/sdist artifact gate | Existing pinned build environment; output outside worktree | Pass | A no-isolation wheel and sdist build completed, and `scripts/verify_python_artifacts.py` verified the exact contents and integrity of both artifacts. Generated build metadata was moved out of the worktree. |
| Round 8 browser smoke | Chromium, loopback server, disposable schema-7 data root | Pass | All 46 reported responsive, accessibility, Console, Task, calendar, Agent, Context Pack, Settings, and diagnostics groups passed. Two fixture-only attempts were rejected before this result: the first lacked a Task-authority cutover receipt, and the second copied public seed files with mode `0644` instead of the required owner-only `0600`; initializing the disposable authority and correcting its permissions produced the clean pass without product changes. |
| Round 9 targeted repository/service/API regressions | Clean isolated data roots, macOS, Python 3.13 | Pass | 78 Run repository and orchestration tests passed, including cursor-jump rejection, retry precedence after Task drift, exact detail-field allowlists, 128-character dispatch/event boundaries, authority/referential closure, and missing/malformed Task codes. Direct handler regressions prove 404/400 HTTP mapping. |
| Round 9 focused correction suites | macOS, Python 3.13 | Pass | 217 repository, orchestration, private-unit, migration/history, artifact, Task authority/deletion, production Hermes, and runtime-architecture tests passed in 88.959s. Expected fault-injection diagnostics remained bounded. |
| Round 9 full suite | macOS host/loopback, Python 3.13 | Pass after scope correction | 1,271 tests passed in 208.742s; 4 skipped. The first run exposed an over-broad authority condition affecting only Console compatibility fixtures. The invariant was narrowed to require Task authority for every task-dispatch store while allowing Console-only compatibility history; 152 affected compatibility tests then passed before the clean full rerun. |
| Round 9 static and secret gates | Isolated branch; existing pinned secret environment | Pass | `git diff --check`, repository-wide Python compilation, Node syntax checks for both frontend entry points, and the tracked-file secret scan passed. The system Python and one stale quality environment lacked a working `detect-secrets`; the unchanged scan passed in the existing pinned environment. |
| Round 10 exploit regressions and affected compatibility suites | Clean isolated data roots, macOS, Python 3.13 | Pass | The three exact nested-metadata, unknown-detail, and stale-event-digest regressions passed. 128 affected Run/history/artifact/local-and-remote Console tests passed in 5.628s; static diff and changed-module compilation passed. |
| Round 10 corrected full suite | macOS host/loopback, Python 3.13 | Pass | 1,273 tests passed in 207.852s; 4 skipped, after strict nested-media and direct read validation corrections. |
| Round 11 exact projection/privacy regressions | Clean isolated data roots, macOS, Python 3.13 | Pass | Four exact stale-digest Console projection, rehashed-secret event, strict authoritative read, and cross-platform path tests passed; all 78 Run repository and history tests passed in 3.266s. |
| Round 12 event-window regressions | Clean isolated data roots, macOS, Python 3.13 | Pass | The exact interior-gap plus Round 11 privacy/path regressions passed; all 79 Run repository and history tests passed in 3.297s. |
| Round 13 Run projection regressions | Clean isolated data roots, macOS, Python 3.13 | Pass | Prefix/interior event loss fails repository list/detail/event/summary reads and server Run list/detail projection. All 83 Run repository and orchestration tests passed in 5.830s, including retention+1 and 1,001-event reconciliation boundaries. |
| Round 14 post-retention return regression | Clean isolated data roots, macOS, Python 3.13 | Pass | All 83 Run repository and orchestration tests passed in 5.995s; the one-event retention case proves the mutation return exactly matches the committed validated Run. |
| Round 14 independent re-review | Same two adversarial implementation-diff reviewers | Approved | Both reviewers returned **APPROVED — no blocking findings** after independently inspecting the post-retention correction and focused evidence. |
| Final full suite | macOS host/loopback, Python 3.13 | Pass | 1,278 tests passed in 212.585s; 4 skipped. |
| Final Lighthouse gate | Fresh deterministic desktop fixture; Lighthouse 13.4.1; provided throttling | Pass | Performance 100, Accessibility 100, Best Practices 100, SEO 100. FCP 247.626 ms, LCP 343.267 ms, TBT 0 ms, CLS 0.027834. Summary: `reviews/2026-08-18-mentat-sqlite-run-event-dispatch-lighthouse.json`. |
| `python scripts/verify_release_checks.py` | Local feature branch | Not applicable locally | The script requires hosted release environment variables, an exact release SHA, and repository token; no product failure was reported. Hosted checks remain required on the ready PR. |

## Resume point

Present the publication packet for explicit approval; hosted CI remains a
ready-PR gate.
