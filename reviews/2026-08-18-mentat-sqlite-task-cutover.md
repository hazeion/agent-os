# Feature Slice Review: SQLite Task Authority Cutover

Status: In progress
Slice: `mentat-sqlite-task-cutover`
Date: `2026-08-18`
Review log: `reviews/2026-08-18-mentat-sqlite-task-cutover.md`

## Slice contract

### Goal

Mentat atomically imports the exact current `tasks.json` collection into its
existing owner-private `mentat.sqlite3`, records SQLite authority in that same
transaction, and routes every live Task read and mutation through SQLite with
no dual-read, dual-write, or fallback interval.

### In scope

- Advance `mentat.sqlite3` additively with a singleton, schema-validated Task
  authority receipt that makes an empty post-cutover Task store unambiguous.
- Perform a one-time, state-bound startup cutover under the shared private-state
  lock after Mentat acquires its exclusive server reservation and before it
  opens a listener or publishes runtime state.
- Bind the exact source bytes and identity, require an empty destination, import
  all Tasks and write the authority receipt in one immediate transaction, and
  prove semantic reconstruction before commit.
- Make the centralized server Task read/mutation helpers use SQLite after the
  cutover while preserving current handler inputs, outputs, safety locks, Task
  order, planning/delegation metadata, and mutation result semantics.
- Add an atomic whole-collection repository mutation compatible with current
  Task workflows, preserving revisions for unchanged Tasks, incrementing them
  for changed Tasks, assigning revision 1 to new Tasks, and deleting removed
  Tasks without partial state.
- Preserve `tasks.json` as a stale legacy/recovery artifact and packaged seed;
  no running Task path may consult or update it after the authority receipt
  exists. Only an explicit server-stopped, token-bound downgrade export may
  replace it.
- Keep the existing exact read-only migration preview useful before cutover and
  report already-cut-over state without consulting stale JSON afterward.
- Preserve private backup/restore semantics and document the supported
  downgrade/export boundary now that `tasks.json` no longer follows live Task
  mutations.
- Update architecture, data-layout, pivot-plan, changelog, tests, and this
  persistent review record.

### Out of scope

- Durable Runs, AgentEvents, dispatch reservations, retention, or SSE changes
  (Slice 1C-C).
- Removing the packaged `data/tasks.json` seed or broad obsolete-path cleanup
  (Slice 1C-D).
- Agent Registry database convergence (Slice 3C), dynamic runtime routing, a
  second runtime, or frontend framework work.
- Changing public Task API shapes or exposing SQLite revisions to the browser.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Schema migration creates an exact singleton authority table and remains atomic, idempotent, owner-private, backup-compatible, and forward-version refusing. | Schema/private backup tests. | Pending |
| AC-2 | Exact source import and the SQLite authority receipt commit together; source, destination, or transaction drift leaves no partial Tasks or receipt. | Cutover fault/drift tests. | Pending |
| AC-3 | Empty cutover is durable and cannot later import a changed seed; after receipt, malformed, missing, replaced, or linked `tasks.json` is never read by live Task paths. | Authority/no-fallback tests. | Pending |
| AC-4 | Every production Task read/write path uses SQLite after cutover, with no runtime JSON write, dual write, shadow read, or fallback. | Source assertions and patched-I/O integration tests. | Pending |
| AC-5 | Existing create/edit/delete/reorder/planning/recurrence/calendar/search/delegation behavior and public payloads remain compatible. | Focused server and browser suites. | Pending |
| AC-6 | Whole-collection mutations are one transaction, preserve order and result values, reject invalid graphs/documents, avoid lost updates, and maintain monotonic internal revisions. | Repository concurrency/rollback tests. | Pending |
| AC-7 | Backups retain the authoritative store and receipt; restore cannot silently make stale JSON authoritative, and downgrade/recovery instructions are exact. | Backup/restore tests and docs. | Pending |
| AC-8 | Full suite, package/secret checks, browser smoke, and two independent adversarial reviews finish without blocking findings. | Verification and review records. | Pending |

### Constraints and recovery

- Safety: reuse the shared private-state and Hermes Kanban lock ordering,
  parameterized SQL, exact schema checks, bounded errors, and restore guards.
- Authority: a committed SQLite receipt is the sole source-of-truth decision.
  Absence means cutover has not committed; presence means `tasks.json` is stale
  and cannot be consulted automatically.
- Compatibility: preserve public Task JSON and HTTP behavior. SQLite revisions
  remain internal.
- Rollback/recovery: retain the original `tasks.json` bytes at cutover and rely
  on a current private backup for full recovery. A downgrade after live SQLite
  mutations requires an explicit offline deterministic export made by a
  SQLite-capable build; automatic fallback is forbidden.
- Version control: branch `codex/sqlite-task-cutover` from merged Slice 1C-A;
  ready PR targets `main`. Publication still requires the reviewed-feature
  workflow's immediate explicit authorization checkpoint.

### Scope discussion and approval

- Recommendation: one automatic startup storage migration after normal data
  root initialization and exclusive server reservation, with an atomic database
  receipt and no JSON fallback before the listener opens.
  This gives upgrades and fresh installs one deterministic path without asking
  the dashboard to run in a mixed authority state.
- Alternatives rejected: dual reads/writes create competing truth; an empty
  database without a receipt can re-import stale Tasks; requiring a manual
  migration command would make a normal application upgrade non-startable.
- User decisions: SQLite is the long-term Task authority; destructive migration
  is acceptable; eventual unified Mentat-owned storage remains a later goal;
  all implementation slices are approved to proceed.
- Approved at: 2026-08-18.

## Test strategy

| Acceptance criterion | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- |
| AC-1 | Exact schema-5-to-6 migration, reopen, snapshot, corruption, and newer-schema cases. | Receipt metadata is durable and schema-bound. | Does not exercise later Run/Event tables. |
| AC-2 | Source-byte/identity drift, destination path replacement, occupied target, injected insert/reconstruction/receipt/commit failures, and retry. | Cutover is all-or-nothing and state-bound to the opened database path. | Process-kill simulation uses deterministic fault injection. |
| AC-3 | Empty-source cutover followed by source replacement/removal/corruption/linking while live reads and writes continue from SQLite. | No stale seed resurrection or fallback. | Packaged seed remains present for installation. |
| AC-4 | Patch legacy JSON read/write primitives to fail for `tasks.json`; exercise startup and all centralized Task helpers; static source inventory. | Runtime Task authority is SQLite only. | Explicit offline recovery tooling is a separate path. |
| AC-5 | Existing Task planning, deletion, dashboard, delegation, webhook, artifacts, and browser regressions. | User-visible behavior survives the cutover. | Hermes network behavior remains mocked where already mocked. |
| AC-6 | Concurrent mutators, unchanged/changed/new/deleted revision checks, ordering, invalid return shape, graph failure, and result passthrough. | Current list-mutator contract maps safely to SQLite. | Local SQLite contention only. |
| AC-7 | Current backup/restore with authoritative empty/nonempty stores plus pre-cutover schema-5 restore/startup migration and exact offline export preview/confirmation. | Recovery preserves the authority decision and intentional downgrades can include later Task mutations. | The operator must stop Mentat and explicitly confirm the state-bound export. |
| AC-8 | Focused/full/package/secret/browser checks and two read-only reviewers. | Broad regression and release confidence. | Lighthouse remains the required final 1C-D score gate. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository and call-site inventory | Isolated branch at merged Slice 1C-A | Pass | All live Task operations converge on `read_json_file("tasks.json")` and `update_json_file("tasks.json")`; schema 5 has no authority marker. |
| Prior Slice 1C-A full verification | PR #107 final head | Pass | 1,139 tests and 51 GitHub checks passed; SQLite Task schema/reconstruction/backup foundation accepted and merged. |

### Test discussion and approval

- The user approved the SQLite middle-ground architecture and all slices moving
  forward. The final milestone still requires Lighthouse 100/100/100/100; this
  storage-only cutover keeps Lighthouse as the Slice 1C-D release gate.
- Approved at: 2026-08-18.

## Implementation record

### Changes

- Advanced `mentat.sqlite3` to schema 6 with an exact singleton Task authority
  table included in the repository schema fingerprint.
- Added one-time startup cutover under the exclusive server reservation and
  shared private-state lock. Exact source validation, canonical reconstruction,
  import, and authority receipt commit atomically; startup fails closed on
  unsafe, changed, duplicate, occupied, or invalid state.
- Added deterministic import upgrades for sparse historical Tasks, underscore
  statuses, prior open/ready/done statuses, timezone-naive shipped timestamps,
  and legacy delegation links while retaining the canonical safety and
  dependency validators.
- Routed the centralized server Task read and mutation helpers through SQLite.
  Normal operation opens one authoritative SQLite snapshot; only a missing
  receipt invokes the one-time source import.
- Added whole-collection transactional mutation with stable ordering,
  unchanged/changed/new Task revision handling, result passthrough, graph
  validation, rollback, and cross-thread serialization.
- Bound production repository transactions to the exact database/WAL/SHM path
  identities captured after transaction start and revalidated immediately
  before and after commit. Database open/path/schema failures translate to
  bounded repository codes at startup and live helpers.
- Added `mentat task-export`, an offline exact preview/confirmation operation
  that refuses an active server, binds both the authoritative export and stale
  destination identity, atomically publishes verified legacy JSON, and leaves
  SQLite authority intact.
- Kept exact schema-4 and schema-5 private backups supported, added schema-6
  Task/receipt consistency validation, and retained current authoritative
  SQLite as the lossless recovery unit.
- Updated affected tests to assert SQLite state rather than stale JSON and
  updated architecture, data-layout, roadmap, contributor guidance, and
  changelog contracts.

### Deviations and decisions

- Startup ordering was corrected during implementation: Mentat first acquires
  its exclusive server reservation, then cuts over Tasks, then opens the
  listener. This prevents an older live process from mutating JSON during the
  cutover while still keeping the dashboard unpublished until success.
- Legacy `tasks.json` remains in the fixed durable backup inventory and package
  as a seed, but it is intentionally stale after cutover. Obsolete allowlist and
  wording cleanup remains Slice 1C-D.
- No automatic downgrade or runtime synchronization was added. The explicit
  offline export now satisfies the approved downgrade contract without making
  `tasks.json` a second live authority.

## Verification

### Focused checks

| Command or action | Result | Evidence |
| --- | --- | --- |
| Syntax and whitespace checks | Pass | `py_compile` covered all changed Python entry points/tests; `git diff --check` clean. |
| Core Task/server compatibility suites | Pass | 121 tests across repository, planning, deletion, dashboard, delegation, artifacts, lifecycle, and architecture contracts. |
| Split private backup/restore suite | Pass | 34 private Console tests passed in two bounded groups, including released schema-4 restoration. |
| Packaging | Pass | Wheel and sdist built; `verify_python_artifacts.py dist` verified both exact inventories. |
| Tracked secret scan | Pass | Pinned `detect-secrets` scan reported no unreviewed candidates. |
| Chromium browser smoke | Pass | All 46 named desktop/mobile, Task, Console, Calendar, Agent, Context Pack, Settings, accessibility, and diagnostics checks passed against an isolated schema-6 startup cutover. |
| Round-1 focused corrections | Pass | 38 Task repository tests plus the 3 formerly failing data-schema contracts pass after timestamp, identity, export, and fail-closed updates. |
| Final focused regression groups | Pass | 38 Task repository, 57 data-schema (1 platform skip), 34 private-state, and 124 Task/lifecycle/packaging compatibility tests passed. |
| Final package and secret evidence | Pass | Fresh wheel/sdist build and exact artifact verification passed; tracked-file secret scan passed. |
| Final rendered browser evidence | Pass | All 46 Chromium smoke checks passed against a fresh isolated schema-6 cutover. |

### Full suite

The final four host shards passed 1,158 tests with four platform-specific skips
and no failures. The shard totals were 411, 305, 301, and 141 tests. Expected nested
CLI usage text and the quality-gate canary subprocess output did not change the
outer zero exit statuses.

## Adversarial review

### Round 1

Reviewer A — correctness and safety lens: **not approved**, four blocking
findings.

| ID | Finding | Disposition |
| --- | --- | --- |
| A-01 | Live helpers could invoke startup migration and re-import stale JSON when the receipt was absent. | Accepted. Removed every live fallback; only reserved startup may establish authority. Added a no-source-read regression. |
| A-02 | Deterministic export rejected an authoritative destination. | Accepted. Authoritative export now requires and validates the receipt. |
| A-03 | Pure reorder mutations did not increment revisions. | Accepted. Revision comparison now includes prior sort order and has a focused regression. |
| A-04 | Occupied schema-5 preview reported a ready empty destination. | Accepted. Exact schema-5 validation/counting now blocks occupied migration. |

Reviewer B — compatibility and product lens: **not approved**, five blocking
findings.

| ID | Finding | Disposition |
| --- | --- | --- |
| B-01 | Shipped timezone-naive Task timestamps failed canonical import. | Accepted. Supported naive ISO timestamps deterministically gain UTC; sparse, naive, and aware historical fixtures are covered. |
| B-02 | Three legacy data-schema tests failed without equivalent SQLite assertions. | Accepted. Tests now prove stale linked/missing/broad JSON is ignored after authority and malformed/oversized mutations fail without changing SQLite. |
| B-03 | Replacing the database path during cutover could commit to a detached inode. | Accepted. Guarded transactions pin and verify main/WAL/SHM identities before and after commit; an actual POSIX replacement fault rolls back and fails closed. |
| B-04 | The approved offline deterministic downgrade export had no operator workflow. | Accepted. Added state-bound `mentat task-export` preview/confirmation and documentation. |
| B-05 | Database connection failures escaped repository error translation. | Accepted. All production opens occur inside a bounded translation context; newer, malformed, and redirected database tests assert safe codes. |

All findings are in scope and evidence-based. No finding was rejected or
deferred. Both reviewers will receive the complete updated diff, all original
findings, and fresh verification evidence for independent Round-2 review.

### Round 2

Both reviewers rechecked the complete slice and every Round-1 disposition.
Reviewer A reported four blockers; Reviewer B reported three. Each unique
finding was given to the peer for independent critique before disposition.

| Root cause | Review evidence | Disposition |
| --- | --- | --- |
| Database-open handoff race | B2-01; Reviewer A independently reproduced and maintained it as High/blocking. | Accepted. `mentat_db.connect_with_identity()` now returns its verified pre-return DB/WAL/SHM identity receipt; the repository guard consumes that receipt and immediately rejects replacement between open and guard installation. An actual handoff replacement regression was added. |
| Export without committed authority | B2-02; Reviewer A maintained it as High/blocking. | Accepted. Task recovery preview/confirmation now require an authoritative destination; a schema-6 database without a receipt cannot erase nonempty legacy JSON. |
| Incomplete old-build downgrade | A2-01; Reviewer B revised the wording but maintained the degraded-workflow risk as blocking. | Accepted. `task-export --compatible-root` now atomically publishes a separate schema-5 sibling data root containing current durable documents, exported Tasks, retained Console/attachment/blob state, and Agent registry while preserving the schema-6 source. |
| Layout-sensitive stale-file mode | A2-02; Reviewer B maintained it as blocking. | Accepted. Export receives the same packaged/default-root mode policy as cutover, binds the observed mode into confirmation, and always publishes owner-private `0600` output. |
| Export write/verification reporting | A2-03 and B2-03 corroborated. | Accepted. Expected write failures are bounded; write-uncertain and post-write verification failures report `partial` with `null` or `true` write state rather than a traceback or false no-write claim. |
| Obsolete Windows reparse regression | A2-04; Reviewer B revised it to a blocking tier-one test defect. | Accepted. The Windows test now establishes SQLite authority and proves a stale linked JSON destination is ignored and unmodified by live Task mutation. |

Round-2 corrections pass 43 Task repository tests, 57 data-schema tests (one
platform skip), 34 private-state tests, 49 packaging/lifecycle tests, syntax,
and whitespace checks. Both reviewers will receive the fresh complete tree for
Round 3; this remains within the workflow's default three-round limit.

Final post-fix evidence also includes a fresh wheel/sdist build with exact
artifact verification, a clean tracked-secret scan, and all 46 Chromium smoke
checks against a new isolated schema-6 startup cutover.

### Round 3

Both reviewers verified all earlier dispositions but did not approve the new
compatible-root workflow. The default three-round limit is exhausted, so the
slice is paused for explicit user direction before another correction/review
round.

| Root cause | Review evidence | Current disposition |
| --- | --- | --- |
| Compatible capture consults stale Task JSON | A3-01 High/blocking; B3-03 corroborates unbounded capture failures. | Valid. Capture must snapshot only non-Task durable documents and synthesize `tasks.json` exclusively from authoritative SQLite. Malformed, missing, or linked stale Task JSON must never be opened. |
| Compatible target publication can clobber a race-created directory | A3-02 High/blocking and B3-02 Medium/blocking independently reproduced `os.rename()` replacing an empty competitor. | Valid. Publication needs pinned-parent, atomic missing-only semantics plus an actual target-appearance regression. |
| Schema-5 sibling retains canonical Task rows | B3-01 High/blocking. | Valid. A true pre-cutover sibling must clear schema-5 Task tables, use JSON as its sole Task state, and pass an old-style JSON mutation followed by exact schema-6 re-upgrade import. |
| Capture/private/document failures can escape the CLI boundary | B3-03 Medium/blocking; overlaps A3-01's malformed stale-JSON traceback. | Valid. Preview and confirmation capture failures need bounded repository codes and CLI regressions for malformed/missing/linked non-Task documents and private state. |

No Round-3 finding is rejected or deferred. Publication remains forbidden while
these blockers are open. Recommended next action: user-authorized Round 4 to
apply the four corrections, rerun complete verification, and return the same
two reviewers to the full slice.

### Round 4 authorization and corrections

The user explicitly authorized one fourth correction and reviewer round using
the same two reviewers. This authorization extends only the adversarial-review
limit; it does not waive the required publication checkpoint.

| Round-3 blocker | Round-4 correction |
| --- | --- |
| Compatible capture consulted stale Task JSON. | Compatible capture now opens only the eight non-Task durable documents and synthesizes `tasks.json` exclusively from the authoritative SQLite snapshot. Malformed, missing, and linked stale Task JSON regressions prove it is never consulted. |
| A race-created destination could be replaced. | Publication now pins the destination parent and uses the platform's atomic exclusive rename (`RENAME_EXCL` on macOS or `RENAME_NOREPLACE` on Linux). A real target-appearance regression preserves the competitor and reports no Mentat write. |
| Schema-5 retained canonical Task rows. | The downgrade copy now clears all schema-5 Task tables before removing the schema-6 receipt. A downgrade, old-style JSON mutation, and current-build re-upgrade test proves exact import with JSON as the sibling's sole Task authority. |
| Capture failures escaped the CLI boundary. | Missing, malformed, or linked non-Task documents and malformed private history now produce bounded `task_export.capture_unavailable` CLI results with `writes_performed: false`. |

Fresh complete verification passed and same-reviewer Round 4 is pending.

#### Round-4 verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Focused compatibility regression | Pass | 161 Task repository, data-schema, private-state, and lifecycle tests passed with one native-Windows skip. |
| Complete host suite | Pass | 1,161 tests passed with four platform-specific skips. The first sandboxed run denied seven ephemeral loopback binds; the unchanged suite passed once those real HTTP tests received host loopback access. |
| Syntax and whitespace | Pass | Changed Python entry points/tests compile and `git diff --check` is clean. |
| Fresh package verification | Pass | A new wheel and sdist were built and both passed `verify_python_artifacts.py` exact-inventory verification. |
| Tracked secret scan | Pass | The pinned `detect-secrets` baseline reported no unreviewed candidates. |
| Rendered Chromium smoke | Pass | All 46 named desktop/mobile, Task, Console, Calendar, Agent, Context Pack, Settings, accessibility, and diagnostics checks passed against a fresh schema-6 cutover. |

#### Round-4 reviewer decisions

Both original reviewers rechecked the complete slice and every prior
disposition. Both returned **not approved**. Each unique finding was then given
to the peer for independent critique; no finding was rejected.

| Root cause | Review evidence | Disposition |
| --- | --- | --- |
| Export failures can escape before repository translation. | A4-01 Medium/blocking; B4-01 independently reproduced the digest path, then revised A4-01 to cover shared lock entry plus compatible target/digest processing. | Valid. `private_state_lock()` can raise interrupted-recovery `PrivateStateError` before both export modes enter a bounded repository boundary, and compatible target/digest work can raise expected filesystem/SQLite failures outside it. This supersedes B4-01 and leaves Round-3 B3-03 open. A future correction must preserve phase-aware write reporting and add plain/compatible preview/confirmation CLI regressions. |
| Compatible sibling silently loses remote-Hermes selection. | B4-02 High/blocking; Reviewer A independently maintained it. | Valid. The sibling captures Console state but not the separate private remote connection record or credential source, so an old build can silently load `local-default`. Do not copy credentials indiscriminately. Either add a validated, state-bound safe connection transfer or fail compatible export closed for remote mode and require explicit reconfiguration, with exact tests/docs. |
| Target-race regression uses a nonempty competitor. | B4-03 Low/nonblocking initially; Reviewer A independently maintained the evidence and classified the missing empty-target regression Medium/blocking. | Valid and conservatively blocking because ordinary POSIX rename already rejects the current nonempty fixture. Add an empty race-created target regression proving no replacement, `writes_performed: false`, and no Mentat publication. The current native exclusive implementation itself passed the reviewers' empty-target reproduction. |

All Round-1 findings and the independent Round-2 findings are resolved. The
old-build downgrade finding from Round 2 remains partially open for remote
Hermes installations. Round-3 stale Task JSON capture, exclusive implementation,
and empty schema-5 Task tables are resolved; bounded capture reporting remains
open. AC-1 through AC-6 are satisfied. AC-7 and AC-8 remain unsatisfied while
the three Round-4 dispositions above are open.

## Documentation

`AGENTS.md`, `ARCHITECTURE.md`, `DATA_LAYOUT.md`,
`MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`, and `CHANGELOG.md` now describe SQLite
authority, startup/error safety, timestamp compatibility, stale JSON behavior,
and the exact offline downgrade export workflow.

## Round-4 outcome

**Paused after Round 4.** The explicitly authorized fourth correction/review
round completed with two not-approved decisions and three accepted blocking
dispositions. A fifth correction/re-review round requires new explicit user
authorization. Nothing is staged, committed, pushed, or published.

### Round 5 authorization and corrections

The user explicitly authorized a fifth round after receiving the Round-4
status. The same publication checkpoint remains mandatory.

| Round-4 disposition | Round-5 correction |
| --- | --- |
| Shared lock entry and digest/target failures escape. | Both export modes now translate the complete private-state lock boundary. Compatible capture includes target resolution, private digesting, SQLite/temp failures, and evidence construction. Pre-write failures report bounded no-write results; existing write-uncertain and post-write reporting remain phase-aware. Plain/compatible preview and confirmation tests cover interrupted restore state, plus digest and target fault injection. |
| Remote sibling silently falls back to local Hermes. | Compatible-root export now validates connection state and fails closed with `task_export.compatible_remote_reconfigure_required` while remote mode is active. Credentials remain excluded. Tests prove no sibling or private endpoint output, and docs require an explicit local-mode export followed by old-build remote reconfiguration before any operation. |
| Race test used a nonempty target. | The regression now creates a genuinely empty target, records its identity, and proves exclusive publication preserves that exact empty directory with no Mentat files and `writes_performed: false`. |

Fresh complete verification passed and same-reviewer Round 5 is pending.

#### Round-5 verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Focused compatibility regression | Pass | 164 Task repository, data-schema, private-state, and lifecycle tests passed with one native-Windows skip; an additional combined Task/remote-Hermes run passed 89 tests. |
| Complete host suite | Pass | 1,164 tests passed with four platform-specific skips, including all real loopback receiver tests. |
| Syntax and whitespace | Pass | Changed Python entry points/tests compile and `git diff --check` is clean. |
| Fresh package verification | Pass | A new wheel and sdist were built and both passed exact-inventory verification. |
| Tracked secret scan | Pass | The pinned baseline reported no unreviewed secret candidates. |
| Rendered Chromium smoke | Pass | All 46 named browser checks passed against a fresh schema-6 startup cutover. |

#### Round-5 reviewer decisions

Reviewer B approved the complete frozen slice with no findings. Reviewer A
returned **not approved** with two new edge-case blockers. Reviewer B then
independently reproduced and maintained both findings as Medium/blocking.

| Root cause | Review evidence | Disposition |
| --- | --- | --- |
| Maximum-size canonical export gains an invalid extra byte. | A5-01 Medium/blocking; Reviewer B independently reproduced both exporter failures. | Valid. A canonical Task collection may be exactly 16,777,216 bytes, but both paths append a newline. Plain export writes 16,777,217 bytes and then reports a post-write verification failure; compatible export refuses publication. A future correction should publish canonical bytes without the optional newline and cover exact-limit plus adjacent boundaries through plain export, compatible old-build load, and re-upgrade. |
| Compatible publication is atomic but not fully crash-durable. | A5-02 Medium/blocking; Reviewer B independently maintained it. | Valid. Files are synchronized, but populated nested stage directories and the pinned publication parent are not all fsynced. A future correction must fsync the staged hierarchy bottom-up, mark publication immediately after rename, fsync the pinned parent, report a later fsync failure as partial with `writes_performed: true`, and add fault-injection coverage. |

Every Round-1 through Round-4 finding is resolved. AC-1 through AC-6 remain
satisfied. AC-7 and AC-8 remain unsatisfied while the two Round-5 findings are
open.

## Round-5 outcome

**Paused after Round 5.** The explicitly authorized fifth correction/review
round resolved all prior findings but exposed two new accepted blocking edge
cases. A sixth correction/re-review round requires new explicit user
authorization. Nothing is staged, committed, pushed, or published.

### Round 6 authorization and corrections

The user explicitly authorized Round 6 after receiving an explanation of the
SQLite cutover and downgrade boundary under review. The publication checkpoint
remains mandatory.

| Round-5 blocker | Round-6 correction |
| --- | --- |
| Maximum-size export gains an invalid newline. | Plain and compatible exports now publish exact canonical bytes without optional formatting. An exact 16,777,216-byte authoritative collection passes plain export, old-build compatible loading, and schema-6 re-upgrade byte-for-byte; the adjacent accepted and rejected boundaries are also asserted. |
| Compatible publication is not fully crash-durable. | Private Console materialization fsyncs populated directories bottom-up. Compatible export then fsyncs the complete stage root, performs the exclusive rename, marks the publication as written, and fsyncs the pinned parent before success. A parent-fsync fault after rename returns `partial` with `writes_performed: true`; directory-order and stage/parent synchronization are covered. |

Fresh complete verification passed and same-reviewer Round 6 is pending.

#### Round-6 verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Exact blocker reproductions | Pass | Maximum-size plain/compatible/re-upgrade and staged-tree/post-rename durability tests passed. |
| Focused compatibility regression | Pass | 166 Task repository, data-schema, private-state, and lifecycle tests passed with one native-Windows skip; Task/private-state alone passed 85 tests. |
| Complete host suite | Pass | 1,166 tests passed with four platform-specific skips, including all real loopback receiver tests. |
| Syntax and whitespace | Pass | Changed Python entry points/tests compile and `git diff --check` is clean. |
| Fresh package verification | Pass | A new wheel and sdist were built and passed exact-inventory verification. |
| Tracked secret scan | Pass | The pinned baseline reported no unreviewed secret candidates. |
| Rendered Chromium smoke | Pass | All 46 named browser checks passed against a fresh schema-6 startup cutover. |

#### Round-6 reviewer decisions

Both original reviewers returned **not approved**, each with one new blocker.
The peer reviewer independently maintained each finding; the Windows finding
was narrowed to durability rather than parent-pinning or no-replace semantics.

| Root cause | Review evidence | Disposition |
| --- | --- | --- |
| Plain export final verification still strips newline bytes. | A6-01 Medium/blocking; Reviewer B independently reproduced the false-success race. | Valid. Exact canonical bytes are written, but final verification hashes `published.raw.rstrip(b"\\n")`. A raced appended newline can therefore produce success and an export digest that does not identify the actual file. Compare exact bytes/digest without stripping and add a post-write drift regression requiring partial/true. |
| Compatible crash durability is POSIX-only. | B6-01 Medium/blocking; Reviewer A maintained the durability defect while rejecting claims that Windows lacks handle-chain parent pinning or no-replace behavior. | Valid. Windows is tier-one, but staged-directory and parent synchronization are no-ops and `os.rename()` does not request write-through. Implement exclusive `MoveFileExW(..., MOVEFILE_WRITE_THROUGH)` without replacement and native coverage, or fail compatible-root closed on Windows pending a supported capability. |

Round-1 through Round-4 findings and Round-5 maximum-size publication are
resolved. Round-5 crash durability remains open only on Windows. AC-1 through
AC-6 are satisfied; AC-7 and AC-8 remain unsatisfied while these two Round-6
findings are open.

## Final outcome

**Paused after Round 6.** The explicitly authorized sixth correction/review
round resolved both reported reproductions on POSIX but exposed an exact-byte
verification gap and a tier-one Windows durability gap. A seventh
correction/re-review round requires new explicit user authorization. Nothing is
staged, committed, pushed, or published.

### Round 7 authorization and corrections

After discussing why a trailing newline is unsafe for an exact hash-bound
recovery artifact, the user authorized fixing the issue and running another
review. Because the known Windows durability blocker would otherwise guarantee
review failure, Round 7 also closes that existing disposition. The publication
checkpoint remains mandatory.

| Round-6 blocker | Round-7 correction |
| --- | --- |
| Final verification strips trailing newline bytes. | Plain export now compares the read-back bytes directly with the canonical export. A post-write injected newline produces `task_export.verification_failed`, `partial`, and `writes_performed: true` while preserving evidence of the drift. |
| Windows compatible publication lacks write-through durability. | Windows publication now calls native `MoveFileExW` with only `MOVEFILE_WRITE_THROUGH`; omitting `MOVEFILE_REPLACE_EXISTING` preserves missing-only behavior. The outer Windows handle chain retains parent pinning. Tests assert the exact native flag, no replace flag, and failure propagation; existing compatible success and empty-target tests remain native-Windows coverage in CI. |

Fresh complete verification passed and same-reviewer Round 7 is pending.

#### Round-7 verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Exact blocker reproductions | Pass | Exact post-write byte drift is rejected as partial/true, and the Windows native wrapper requests write-through without replacement and propagates native failure. |
| Focused compatibility regression | Pass | 168 Task repository, data-schema, private-state, and lifecycle tests passed with one native-Windows skip. |
| Complete host suite | Pass | 1,168 tests passed with four platform-specific skips, including all real loopback receiver tests. |
| Syntax and whitespace | Pass | Changed Python entry points/tests compile and `git diff --check` is clean. |
| Fresh package verification | Pass | A new wheel and sdist were built and passed exact-inventory verification. |
| Tracked secret scan | Pass | The pinned baseline reported no unreviewed secret candidates. |
| Rendered Chromium smoke | Pass | All 46 named browser checks passed against a fresh schema-6 startup cutover. |

#### Round-7 reviewer decisions

Reviewer B approved the complete frozen slice with no findings. Reviewer A
confirmed that both Round-6 implementation blockers are resolved but returned
**not approved** for one contradictory sentence in the canonical architecture
document. Reviewer B independently inspected and maintained that finding as
Medium/blocking.

| Root cause | Review evidence | Disposition |
| --- | --- | --- |
| Calendar architecture text still names `data/tasks.json` as the mutation target. | A7-01 Medium/blocking; Reviewer B independently maintained it after checking the SQLite authority contract and actual server repository routing. | Valid. Runtime behavior correctly uses `mutate_authoritative_tasks()`, but `ARCHITECTURE.md` still directs calendar-linked Task mutations to legacy JSON. Replace it with authoritative SQLite Task repository wording and explicitly prohibit live `tasks.json` mutation. |

All implementation findings from Rounds 1 through 6 are resolved. AC-1 through
AC-3 and AC-5 through AC-7 are satisfied. AC-4 and AC-8 remain unsatisfied only
because the canonical documentation contradicts the implemented SQLite-only
authority. Both reviewers also noted the nonblocking evidence limitation that
this macOS review host cannot execute the real Windows API path; native Windows
CI remains required before merge.

## Round-7 outcome

**Paused after Round 7.** Exact-byte verification and Windows write-through
publication passed review, but one accepted documentation blocker remains. An
eighth correction/re-review round requires new explicit user authorization.
Nothing is staged, committed, pushed, or published.

### Round 8 authorization and correction

The user explicitly authorized correcting A7-01 and running the review. The
calendar boundary now states that calendar-linked Mentat Task mutations use the
authoritative SQLite Task repository and never mutate live `data/tasks.json`.
Google Calendar itself remains read-only. The publication checkpoint remains
mandatory.

#### Round-8 verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Focused compatibility regression | Pass | The same 168 Task repository, data-schema, private-state, and lifecycle tests passed with one native-Windows skip. |
| Architecture contract tests | Pass | All four agent-runtime architecture contract tests passed. |
| Documentation contradiction scan | Pass | The old JSON-mutation wording is absent; the only matching `data/tasks.json` text is the new explicit prohibition. |
| Whitespace | Pass | `git diff --check` is clean. |
| Unchanged full-slice gates | Applicable | Round-7 full suite, package, secret, syntax, and 46-check browser evidence remain applicable because Round 8 changes documentation only. |

Same-reviewer Round 8 is pending.

#### Round-8 reviewer decisions

Both original reviewers independently approved the complete frozen slice with
no actionable findings. Both confirmed that A7-01 is resolved, every finding
from Rounds 1 through 7 remains resolved, and AC-1 through AC-8 pass the
technical review gate.

The reviewers retained one nonblocking verification limitation: this macOS
host cannot execute the real Windows `MoveFileExW` path. The wrapper contract,
flags, failure propagation, and platform-neutral publication behavior are
covered locally; native Windows CI must pass before merge.

## Round-8 outcome

**Approved for publication checkpoint.** The implementation, tests,
documentation, downgrade/re-upgrade behavior, and recorded verification satisfy
the slice contract. Nothing is staged, committed, pushed, or published until
the user gives immediate explicit publication approval.

### Round 9 CI correction authorization and implementation

After publication, native Windows CI exposed three unique failures across four
jobs. The GitHub CI-fix workflow identified two fixture-portability defects and
one real delivery/readback race. The user explicitly approved the focused
correction plan, including verification, review, commit, and push.

| CI failure | Root cause | Round-9 correction |
| --- | --- | --- |
| Stale JSON byte assertion observed CRLF on Windows. | The test used text-mode writing for an exact-byte invariant, allowing platform newline translation. | The fixture now writes the exact stale bytes with `write_bytes()`. |
| Remote-mode compatible export returned capture unavailable. | The test manually created a connection record without the required owner-private Windows ACL, so production correctly failed closed before parsing its mode. | The fixture now uses the production connection-record writer and therefore exercises a valid owner-private remote selection on every platform. |
| Verified Kanban wakeup produced no browser projection on Windows. | `claim_and_admit()` queued the refresh while its delivery-record transaction was still open. The worker could immediately open the same SQLite database before commit; Windows file locking made the authoritative readback fail. | A per-admission gate reserves the bounded queue slot immediately but prevents adapter reads until `claim_and_admit()` returns and closes or rolls back its connection. Duplicate, rejected, queue-full, admitted-unrecorded, shutdown, coalescing, and periodic-reconciliation behavior remain intact. |

#### Round-9 verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Exact CI regressions | Pass | Six focused tests cover exact stale bytes, valid owner-private remote state, delayed adapter entry, bounded unreleased-gate shutdown, route commit ordering, and verified Kanban wakeup. |
| Webhook/coordinator/Task regression | Pass | All 91 tests passed, including real loopback HTTP lifecycle coverage. |
| Complete host suite | Pass | 1,171 tests passed with four platform-specific skips. |
| Syntax and whitespace | Pass | Changed Python files compile; JavaScript entry points parse; `git diff --check` is clean. |
| Fresh package verification | Pass | A new wheel and sdist were built and passed exact-inventory verification. |
| Tracked secret scan | Pass | The pinned baseline reported no unreviewed secret candidates. |
| Rendered Chromium smoke | Pass | All 46 named browser checks passed against a fresh schema-6 startup cutover. |

#### Round-9 reviewer decisions

Reviewer B approved the complete correction with no findings. Reviewer A found
one new cross-delivery concurrency blocker. After receiving the exact finding
and evidence, Reviewer B independently inspected it and maintained it as
Medium/blocking.

| Root cause | Review evidence | Disposition |
| --- | --- | --- |
| A per-hint gate cannot represent a newer delivery transaction that has begun but has not reached `admit()`, and it does not cover periodic reconciliation. | A9-01 Medium/blocking; both reviewers maintained that an older queued hint or reconciliation sweep could still enter a projection adapter while the newer transaction remained open. | Valid. Replace the per-hint gate with one shared transaction/projection barrier acquired before delivery-store connection/`BEGIN` and held through commit or rollback and connection close. Acquire the same barrier centrally around every projection adapter read with stop-aware timed waiting. |

## Round-9 outcome

**Paused after Round 9.** The Windows fixture corrections remain valid, but the
per-hint coordination fix does not close cross-delivery or reconciliation
races. Nothing from the correction is staged, committed, or pushed.

### Round 10 authorization and correction

The user explicitly approved the CI correction plan. Round 10 replaces the
unpublished per-hint gate with a shared reentrant barrier. The webhook delivery
store holds that barrier before opening SQLite and through transaction outcome
and connection close. The refresh coordinator acquires it around every adapter
read, so older queued hints and periodic reconciliation cannot overlap an
active delivery transaction. Timed acquisition observes coordinator shutdown,
preserving bounded stop behavior and immediate bounded queue reservation.

Two deterministic regressions pause a real newer delivery after
`BEGIN IMMEDIATE` and before admission: one positions an older queued hint and
the other positions periodic reconciliation. Neither adapter enters while the
transaction is open; both proceed only after the delivery commits and closes.

#### Round-10 verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Exact CI and A9-01 regressions | Pass | Six focused tests cover exact stale bytes, valid owner-private remote state, older-hint transaction ordering, reconciliation transaction ordering, stop-aware barrier waiting, and verified Kanban wakeup. |
| Focused webhook/store/Task regression | Pass | `python -m unittest -v tests.test_hermes_event_refresh tests.test_hermes_webhook_routes tests.test_hermes_webhook_store tests.test_task_repository` passed all 104 tests with real loopback coverage. |
| Complete host suite | Pass | `python -m unittest discover -s tests` passed 1,171 tests with four platform-specific skips. |
| Syntax and whitespace | Pass | Changed Python files compile; both frontend entry points and the browser-smoke script parse; `git diff --check` is clean. |
| Fresh package verification | Pass | A fresh wheel and sdist built with the hash-locked native environment and passed exact-inventory verification. |
| Tracked secret scan | Pass | The hash-locked quality environment reported no unreviewed secret candidates. |
| Rendered Chromium smoke | Pass after one retry | The first run timed out restoring the existing compact-navigation tooltip after scroll. A clean Chromium retry on a fresh debug port passed all 46 named checks. No UI code changed in Round 10. |

#### Round-10 reviewer decisions

Both original reviewers independently returned **not approved** for the same
inverse-order latency defect. Because the root cause and required evidence are
corroborated, no peer-consensus step is needed.

| Root cause | Review evidence | Disposition |
| --- | --- | --- |
| The coordinator holds the shared barrier across the complete projection adapter, including external Hermes CLI work, while a newer request must acquire that barrier inside `claim_and_admit()` before it can acknowledge the webhook. | A10-01 and B10-01, both Medium/blocking. Both reviewers independently reproduced a newer delivery remaining blocked until an older slow adapter was released. The production Kanban projection can perform capability work and three external reads with 15-second subprocess timeouts. | Valid. A9-01 is resolved, but its whole-adapter barrier can delay later acknowledgements and prevent shutdown from acquiring the hints lock. Narrow the shared barrier to the short Mentat SQLite snapshot phase, keep external Hermes work outside it, and add inverse-order acknowledgement and shutdown regressions while retaining the older-hint and reconciliation transaction-exclusion proofs. |

Both reviewers confirmed that the Windows fixture corrections are valid, every
Round-1 through Round-8 finding remains resolved, and the focused 104-test
suite passes. Native Windows execution remains required after publication.

## Round-10 outcome

**Paused after Round 10.** Cross-delivery SQLite safety is restored, but the
whole-adapter critical section introduces a corroborated webhook-response and
shutdown regression. A Round-11 snapshot-narrowing correction and same-reviewer
recheck require explicit user authorization. Nothing is staged, committed, or
pushed.

### Round 11 authorization and correction

The user explicitly authorized Round 11. The refresh coordinator is again
lock-agnostic: it never holds the delivery barrier across a projection adapter.
Only the local authoritative Task snapshot used by attention and Kanban
projections acquires the shared barrier. Kanban constructs and calls the Hermes
adapter only after that snapshot lock is released. The delivery store continues
to hold the same barrier from before opening SQLite through transaction outcome
and connection close.

The existing server shutdown sequence is now a small reusable operation that
first detaches the coordinator under the hints lock and then performs the
already-bounded worker stop. This makes the actual production ordering directly
testable without changing its two-second production timeout.

The older-hint and reconciliation regressions now assert that their Mentat Task
snapshot cannot begin while a newer delivery transaction is open. A new inverse
regression completes that snapshot, blocks simulated external projection work,
and proves that a newer signed webhook still receives `202` within 500 ms and
that detach/stop returns within its requested timeout. Existing queue-full tests
continue to prove that a claim is not committed when queue admission fails.

#### Round-11 verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Exact CI and concurrency regressions | Pass | Six focused tests cover exact stale bytes, valid owner-private remote state, older-hint snapshot exclusion, reconciliation snapshot exclusion, newer-webhook and shutdown responsiveness during slow external work, and verified Kanban wakeup. |
| Focused webhook/store/Task regression | Pass | `python -m unittest -v tests.test_hermes_event_refresh tests.test_hermes_webhook_routes tests.test_hermes_webhook_store tests.test_task_repository` passed all 104 tests with real loopback coverage. |
| Complete host suite | Pass | `python -m unittest discover -s tests` passed 1,171 tests with four platform-specific skips. |
| Syntax and whitespace | Pass | Changed Python files compile; both frontend entry points and the browser-smoke script parse; `git diff --check` is clean. |
| Fresh package verification | Pass | A fresh wheel and sdist built with the hash-locked native environment and passed exact-inventory verification. |
| Tracked secret scan | Pass | The hash-locked quality environment reported no unreviewed secret candidates. |
| Rendered Chromium smoke | Pass | All 46 named checks passed on the first Round-11 run against a fresh schema-6 startup cutover. No UI code changed. |

#### Round-11 reviewer decisions

Reviewer B initially approved with no findings. Reviewer A returned **not
approved** with one new Medium/blocking finding. After receiving the exact
finding and evidence, Reviewer B independently reproduced the overlap and
maintained the finding as Medium/blocking.

| Root cause | Review evidence | Disposition |
| --- | --- | --- |
| Snapshot-only coordination protects attention and Kanban, but every ordinary live `mentat.sqlite3` connection still performs WAL and migration/schema setup without the delivery barrier. `/api/tasks`, Task mutations, attachments, and delegation artifacts therefore retain the same Windows setup race exposed by CI. | A11-01 Medium/blocking. Reviewer A demonstrated an ordinary authoritative Task read entering while a real delivery transaction remained open. Reviewer B independently reproduced the overlap and confirmed that all cited consumers use the same `connect_with_identity()` setup path. | Valid. Move the shared reentrant barrier to `mentat_db`; acquire it only around connection validation/open/WAL/migration/identity verification. Have the delivery store hold that same barrier through its transaction and close. Do not hold it through ordinary queries, mutations, attachment processing, or Hermes work. Add paused-delivery regressions for ordinary Task read, Task mutation, and one attachment or artifact consumer. |

Both reviewers confirmed that A9-01 and A10-01/B10-01 are resolved by Round 11,
that the inverse response/shutdown regression is valid, and that all earlier
findings remain resolved. The required expansion is limited to the shared
connection-setup boundary rather than complete connection lifetimes.

## Round-11 outcome

**Paused after Round 11.** Projection snapshots are safe and external Hermes
work no longer delays acknowledgement, but the demonstrated Windows setup race
still applies to ordinary Mentat database consumers. A Round-12 global
connection-setup correction and same-reviewer recheck require explicit user
authorization. Nothing is staged, committed, or pushed.

### Round 12 authorization and correction

The user explicitly authorized Round 12. The shared reentrant barrier now
belongs to `mentat_db`, the common live Mentat SQLite connection boundary.
Every normal connection holds it only while validating the database set,
opening SQLite, configuring WAL and foreign keys, running migrations, applying
private permissions, and verifying path identity. The barrier is released
before the caller performs an ordinary query, mutation, artifact operation, or
external Hermes work.

The webhook delivery store uses the same non-configurable barrier and retains
it from before connection setup through transaction outcome and connection
close. Reentrancy lets its own connection setup pass while preventing any other
live Mentat setup from racing the open transaction on Windows. Projection Task
snapshots retain their whole-snapshot exclusion, while the inverse slow-Hermes
test continues to prove that external work cannot delay later acknowledgement
or bounded shutdown.

A deterministic regression pauses a real delivery after `BEGIN IMMEDIATE` and
starts three representative live consumers: the ordinary `/api/tasks` read, a
Task collection mutation, and delegation-artifact metadata lookup. All three
remain outside connection setup until the delivery closes, then complete
successfully. A direct-source audit confirms that other live Mentat consumers
use `mentat_db.connect`; remaining direct SQLite opens are in-memory schema
construction, offline Task snapshots/exports, separate Agent Registry storage,
private backup tooling, or read-only Hermes state.

#### Round-12 verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Exact A11-01 and inverse regressions | Pass | Four focused tests prove ordinary Task read/mutation/artifact setup exclusion, older-hint and reconciliation snapshot exclusion, and newer-webhook/shutdown responsiveness during slow external work. |
| Focused webhook/store/Task regression | Pass | `python -m unittest -v tests.test_hermes_event_refresh tests.test_hermes_webhook_routes tests.test_hermes_webhook_store tests.test_task_repository` passed all 105 tests, including three real loopback HTTP cases. |
| Complete host suite | Pass | `python -m unittest discover -s tests` completed successfully; discovery contains 1,172 tests with the existing four platform-specific skips. |
| Syntax and whitespace | Pass | Changed Python files compile; both frontend entry points and the browser-smoke script parse; `git diff --check` is clean. |
| Fresh package verification | Pass | A fresh wheel and sdist built with the hash-locked native environment and passed exact-inventory verification. |
| Tracked secret scan | Pass | The pinned quality environment reported no unreviewed secret candidates. |
| Rendered Chromium smoke | Pass | The complete 46-check browser workflow completed against a disposable schema-6 data root on loopback. No UI code changed. |

Same-reviewer Round 12 is pending. Native Windows CI remains required after
publication because the original failure is platform-specific. Nothing is
staged, committed, or pushed.

#### Round-12 initial reviewer finding and correction

Reviewer B initially approved with no findings after independently running the
105 focused tests and an additional reverse-order database diagnostic.
Reviewer A returned **not approved** with A12-01 High/blocking: the retained
webhook snapshot acquired the database barrier before entering the Task
repository's private-state lock, while every ordinary Task operation acquired
those locks in the reverse order. Reviewer A reproduced a permanent two-thread
cycle. After receiving only the concrete finding and evidence, Reviewer B
independently reproduced the same cycle and changed to **not approved**.

The snapshot now follows the repository's established order:
`private_state_lock` first, then `DATABASE_OPEN_BARRIER`. Both locks are
reentrant on the snapshot thread, so the nested authoritative Task read remains
safe, while an ordinary Task operation can no longer hold private state and
wait on a barrier owned by a projection waiting for that private state.

A new isolated-process regression stages the exact inverse order. An ordinary
Task reader holds private state, a webhook snapshot attempts that lock, and the
ordinary reader then completes its real `tasks_payload()` connection and read
before releasing private state. Both threads must finish with exact snapshots.
The old ordering times out in the disposable child process rather than leaving
the parent test runner with poisoned locks.

#### Round-12 corrected verification evidence

| Command or action | Result | Evidence |
| --- | --- | --- |
| Exact lock and delivery concurrency regressions | Pass | Five focused tests prove the inverse Task/snapshot lock order, ordinary Task read/mutation/artifact setup exclusion, older-hint and reconciliation exclusion, and newer-webhook/shutdown responsiveness. |
| Focused webhook/store/Task regression | Pass | The corrected suite passed all 106 tests, including real loopback HTTP cases and the isolated-process deadlock regression. |
| Complete host suite | Pass | The corrected complete host suite finished successfully; discovery now contains 1,173 tests with the existing four platform-specific skips. |
| Syntax, whitespace, and tracked secrets | Pass | Python and JavaScript parse, `git diff --check` is clean, and the pinned scan reports no unreviewed secret candidates. |
| Fresh corrected package verification | Pass | A newly rebuilt wheel and sdist passed exact-inventory verification after the server correction. |
| Fresh corrected Chromium smoke | Pass | The complete 46-check browser workflow passed again against a new disposable schema-6 data root. |

Same-reviewer re-review of the corrected Round 12 diff is pending. Native
Windows CI remains required after publication. Nothing is staged, committed,
or pushed.

#### Round-12 final reviewer decisions

Both original reviewers independently returned **approved** with no findings.
Each passed the five exact concurrency regressions and all 106 focused tests.
Both confirmed that A12-01 is resolved by the consistent private-state-before-
database-barrier order, A11-01 remains resolved by the common live connection-
setup boundary, and A9-01 plus A10-01/B10-01 remain resolved without reopening
cross-delivery races or response/shutdown latency. All Round-1 through Round-8
findings remain resolved and AC-1 through AC-8 satisfy the technical review
gate.

The reviewers retain one shared verification limitation: native Windows CI
must pass after publication because the original SQLite setup failure was
Windows-specific. The complete host suite, package, secret, syntax, diff, and
Chromium evidence was inspected; the reviewers independently repeated the
focused and exact concurrency suites.

## Round-12 outcome

**Approved for publication checkpoint.** The complete corrected diff and
superseding verification evidence satisfy the reviewed-feature technical gate.
Nothing is staged, committed, pushed, or republished until the user gives the
immediate publication approval required by the workflow.

### Post-publication CI correction

The approved Round-12 commit `bd35864` was published to PR #108. Native
artifact smoke, quality gates, and all but four CI matrix jobs passed. Three
Windows group-1 jobs, one for each supported Python version, consistently
failed the compatible-export remote-state fixture with
`task_export.capture_unavailable`. The fixture applied the production owner-
only writer to the connection file but left its parent private directory with
the inherited Windows ACL. Production correctly validates both directory and
file before parsing the record and therefore failed closed.

The fixture now applies the same production Windows owner-only ACL helper to
the existing private directory before writing the connection record. This is
test setup only; no production permission contract is weakened. A fourth
failure on macOS Python 3.12 was unrelated: the existing maximum-text
performance assertion took 2.354 seconds against a 2.0-second budget while the
same test passed elsewhere. No performance threshold or production validation
is changed for that single timing outlier.

Post-publication correction verification and same-reviewer review are pending.
The correction is not staged, committed, or pushed.

#### Post-publication correction verification

| Command or action | Result | Evidence |
| --- | --- | --- |
| Exact Windows fixture path on host | Pass | The compatible remote-export case reaches the expected safe refusal after constructing a valid directory-and-file private boundary. |
| Task repository module | Pass | All 53 Task repository tests pass. |
| Unrelated timing regression | Pass | The maximum slash-free public-text validation test passed three consecutive runs without changing its 2.0-second assertion. |
| Static checks | Pass | The changed test compiles and `git diff --check` is clean. |

The production diff remains identical to the two-reviewer-approved Round-12
commit. Only the Windows fixture and this persistent verification record have
changed. Native Windows execution remains the decisive fixture proof after the
correction is published. Same-reviewer review is pending.

#### Post-publication correction reviewer decisions

Both original reviewers independently returned **approved** with no findings.
Each confirmed that the fixture now matches production's complete Windows
privacy sequence: protected owner-only private directory first, then protected
owner-only connection file, with read-only loading still validating both.
Neither found any production or security-contract change.

The reviewers independently repeated the exact fixture and Task repository
checks. Native Windows CI remains the decisive proof of the Win32 ACL branch,
and the isolated macOS timing job must rerun successfully before merge.

**Approved for publication checkpoint.** The two-file CI correction is not
staged, committed, or pushed until the user gives immediate approval.
