# Feature Slice Review: Agent Registry Convergence

Status: Approved for publication
Slice: `3C-agent-registry-convergence`
Date: `2026-08-22`
Branch: `feature/3c-agent-registry-convergence`

## Slice contract

### Goal

Make owner-private `mentat.sqlite3` the only live authority for canonical Agent
identity and private runtime bindings.

### In scope

- Add the canonical Agent and runtime-configuration tables to the Mentat
  database schema.
- Give fresh databases an empty embedded Agent authority.
- Add an offline migration with a no-write preview, exact confirmation token,
  verified pre-cutover backup, atomic import and authority receipt, and exact
  post-cutover verification.
- Keep existing roots stopped until their required migration is confirmed.
- Make all live Agent reads and writes use `mentat.sqlite3` after cutover, with
  no fallback or dual write to `agent-registry.sqlite3`.
- Preserve format-2 and format-3 restore compatibility while making new
  backups self-contained without a separate live registry database.
- Preserve the schema-5 compatible-root export by materializing a standalone
  registry only as an explicit downgrade artifact.
- Preserve public Agent APIs, runtime privacy, limits, backup/restore, packaged
  launch, and the current UI.

### Out of scope

- Agent edit/delete UI, credentials, provider login, or runtime routing.
- Moving heartbeat observations from `data/agents.json`.
- Vercel infrastructure, hosted databases, or remote dashboard access.
- Changing Task, Run, event, attachment, or runtime authority contracts.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Fresh roots store Agents and bindings only in schema-8 `mentat.sqlite3`. | Schema and repository tests. | Verified |
| AC-2 | Existing roots receive a no-write exact preview and a verified backup before confirmation can cut over. | Migration and backup tests. | Verified |
| AC-3 | Agent/config rows and the authority receipt commit together; changed input, active servers, occupied destinations, and failures leave no partial authority. | Transaction, race, and negative-path tests. | Verified |
| AC-4 | After the receipt exists, all live reads/writes ignore the old registry and never shadow or dual-write it. | Stale/corrupt-source and source-immutability tests. | Verified |
| AC-5 | New backups need no separate registry member; supported old backups remain restorable, and explicit schema-5 export retains Agents. | Backup/restore and compatible-root tests. | Verified |
| AC-6 | Public APIs remain bounded and secret-free; browser behavior, accessibility, and Lighthouse remain clean. | HTTP, browser, and Lighthouse evidence. | Verified |
| AC-7 | Two independent adversarial reviewers approve the final diff with no unresolved blocking finding. | Review record below. | Verified |

### Constraints and recovery

- Migration is offline and serialized with Mentat's durable mutation boundary.
- The source database is semantically validated and bounded to 128 Agents.
- The confirmation binds source identity/content, destination identity/schema,
  exact public Agent identities, and the backup requirement.
- A format-3 backup is retained before a legacy source is cut over. Recovery
  uses the supported restore path, not a second live authority.
- Existing user-modified JSON and untracked design/runtime files are outside
  this slice and must not be staged.

### Scope discussion and approval

- The user explicitly approved continuing through all pivot slices and granted
  standing approval for required slice, publication, and merge gates.
- The chosen boundary keeps migration and recovery in 3C. Provider and hosted
  infrastructure remain in 4A.
- Approved at: 2026-08-22.

## Test strategy

| Acceptance criterion | Planned evidence | What it proves | Limitation |
| --- | --- | --- | --- |
| AC-1 | Fresh-schema and Agent repository tests. | One database and one embedded authority on new installs. | Does not exercise an old source. |
| AC-2 | Preview byte/identity checks and backup inventory assertions. | Preview does not mutate; backup precedes cutover. | Filesystem durability still needs platform CI. |
| AC-3 | Token invalidation, active-server, concurrency, injected rollback, and receipt tests. | Exact fail-closed atomic cutover. | Process crash injection is simulated at bounded seams. |
| AC-4 | Corrupt/stale legacy source after cutover plus write-isolation assertions. | No live fallback or dual write. | Legacy artifacts may still exist only as ignored recovery input. |
| AC-5 | Format-2/3 restore, format-4 backup, and schema-5 compatible-root tests. | Supported recovery and intentional downgrade remain exact. | Old binaries cannot read schema 8 directly. |
| AC-6 | Focused/full suites, production browser smoke, accessibility checks, and six Lighthouse runs. | Product and performance regression confidence. | Browser checks use the supported local Chromium fixture. |
| AC-7 | Independent correctness/security and product/compatibility reviews. | Adversarial review of code and evidence. | Reviewers inspect the final bounded diff. |

### Baseline

- Base: synchronized `main` at merge commit `c3df0f66de6bf58f625f748f061b6ebd2d42acbc`.
- Current gap: schema 7 stores Agent identity and bindings in the separately
  versioned `agent-registry.sqlite3`; no convergence preview or receipt exists.

## Implementation record

- Added schema 8 with embedded Agent, runtime-configuration, and authority
  tables. Fresh databases receive one empty authority receipt.
- Added a migration-only database open path so a legacy-only root cannot be
  mistaken for a new empty install. Normal database opens also suppress a
  fresh empty claim when that source exists, without probing it after cutover.
- Added `mentat agent-registry-migration` with read-only preview, exact token,
  active-server refusal, format-3 backup verification, source write lock,
  atomic import, receipt commit, and post-cutover verification.
- Moved ordinary Agent reads and writes to `mentat.sqlite3`; retired registry
  files and sidecars are ignored after the receipt exists.
- Added format-4 backup evidence with embedded Agents while retaining exact
  format-2/3 restore and interrupted-restore compatibility.
- Added canonical empty pre-convergence units so default format-2/3 archive
  construction remains internally restorable.
- Kept schema-5 compatible export by synthesizing a standalone registry only
  in the published downgrade root.
- Fixed the fresh-schema startup check so a retained schema-migration backup is
  not mistaken for an unfinished clean installation.

## Verification

| Check | Result |
| --- | --- |
| Full host suite with loopback access | 1,447 passed, 5 skipped; the sole failure is the known assertion against the user's intentionally edited `data/projects.json` fixture |
| Final Agent/migration/backup/schema/runtime regression set | 147 passed, 1 skipped in 95.235s |
| Agent registry, convergence, and private Console suites | 82 passed in 83.014s |
| Backup/restore, Task, and Run suites | 139 passed in 77.661s |
| Final security regressions | 19 convergence tests passed; preview mode/symlink safety, orphan sidecars, pre/post-commit source races, concurrent supported writes, backup refusal, and private cutover-lock coverage included |
| Final broad Python regressions | 100 Agent/private/backup tests, 74 migration/runtime/packaging tests, and 168 schema/Task/Run tests passed with `ResourceWarning` treated as an error |
| Reviewer regression cases | Passed: legacy-only root, stale post-cutover source, hot rollback journals, source writer race, schema-7 format-3 restore, protocol-3 resume, old private-migration receipt, and schema-5 Agent export |
| Released archive defaults | Format-2 and format-3 default private units both build, parse, validate, and round-trip |
| Node 24 web gate | ESLint, TypeScript, and 39 tests passed |
| Production browser smoke | Passed all routes, responsive layouts, keyboard/focus behavior, and Agent/Task/Run projections and controls |
| Lighthouse | Six production audits passed 100/100/100/100; desktop LCP 215–224 ms, mobile LCP 1.11–1.14 s, TBT 0, CLS 0 or effectively 0 |
| Source checks | Python compile and `git diff --check` passed |

The official Turbopack build cannot complete in the local sandbox because the
runtime denies its internal loopback worker port. The same source completed the
Webpack production build and standalone preparation; CI remains the official
Turbopack verification.

## Adversarial review

### First pass

- Correctness/security reviewer found four blockers: a standalone-only root
  could claim empty authority, post-cutover preview still touched retired
  storage, rollback journals were not rejected, and a legacy source writer
  could race the final import.
- Compatibility/product reviewer found the persisted private-unit digest had
  changed for released standalone-registry units, plus the standalone-only and
  stale-file issues. It also found a misleading CLI success flag, stale backup
  documentation, and missing released-state tests.

### Fixes

- Added a specialized no-empty-claim migration open, embedded-first preview,
  exact sidecar rejection, and a source `BEGIN IMMEDIATE` lock held through the
  destination commit.
- Removed the writable public legacy connector.
- Preserved the released digest for standalone-registry units and added genuine
  schema-7 format-3, protocol-3 interruption, and private-migration receipt
  fixtures.
- Prevented ordinary database opens from claiming empty authority over a
  standalone-only source and corrected default old-format private units.
- Corrected the CLI preview flag and current backup/restore documentation.
- Made the startup error show both the source-safe
  `python -m mentat.cli agent-registry-migration` form and the installed
  `mentat` form.
- Made every retired-registry artifact suppress a fresh empty authority claim,
  including orphan rollback-journal, WAL, SHM, and unknown prefixed files.
- Made the source cutover lock private and non-writable to its caller, and put
  its internal SQLite connection into query-only mode after acquiring the
  required writer exclusion.
- Made migration preview capture without creating or hardening operator
  directories; a POSIX regression proves an existing `0755` Console directory
  remains byte- and mode-identical after preview.
- Kept the user's edited tracked JSON and unrelated untracked files outside the
  intended Slice 3C diff and publication allowlist.
- Rechecked retired-registry inventory before and after fresh authority insert,
  then once more before returning the new connection; a detected race rolls
  back or removes the fresh receipt and fails closed.
- Changed the private cutover lock to yield only a read-only validator and
  invoke it immediately before destination commit and again on lock exit.
- Rejected orphan registry sidecars from every pre-convergence private-unit
  capture, so format-3 backup cannot synthesize an empty registry over them.
- Added a no-write Console-chain inspector that rejects symlink/reparse points,
  verifies ownership and directory identity, and rechecks the chain after
  preview capture.
- Added a state-bound compensating transaction for an uncertain or invalid
  destination commit. It removes only the exact imported Agent/config rows and
  receipt, verifies the empty result, and otherwise reports a partial failure
  without deleting unfamiliar state.
- Bound fresh-authority cleanup to the exact receipt timestamp and an empty
  Agent/config state under `BEGIN IMMEDIATE`. If a supported concurrent Agent
  write has advanced the authority, cleanup leaves its receipt and rows intact
  and fails without stranding the data.

Both reviewers are being asked to inspect the corrected final diff.

The correctness/security reviewer approved the final exactness hardening with
no unresolved blocker. The compatibility/product reviewer independently
approved the same final diff.

## Documentation updates

- Updated `AGENTS.md`, `ARCHITECTURE.md`, `DATA_LAYOUT.md`, the pivot roadmap,
  pivot contract, changelog, and private-unit module contract for schema 8,
  format 4, explicit convergence, and downgrade behavior.

## Publication gate

Standing user approval applies after the slice passes its documented gates.

## Outcome review

Pending.
