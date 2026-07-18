# Feature Slice Review: Durable Private Console State

Status: Implementation, local verification, documentation, and two zero-finding adversarial reviews complete; hosted remediation rerun pending
Slice: `beta-1e-private-console-state`
Date: `2026-07-18`
Review log: `reviews/2026-07-18-beta-1e-private-console-state.md`

## Slice contract

### Goal

Move retained Agent Console history, attachment SQLite metadata, and
content-addressed blobs from ephemeral `runtime/` storage into one durable,
owner-only private Console boundary, preserve existing operator state through
an exact migration, and extend ordinary backup/restore with a WAL-safe,
reference-consistent private unit.

### In scope

- Canonical private Console storage below `<data-root>/private/console/` for
  retained history, `mentat.sqlite3` plus SQLite-owned WAL/SHM state, and
  `blobs/sha256/`; uploads, exports, execution inputs, artifact/workspace
  snapshots, lifecycle state, and other scratch remain under `runtime/`.
- One process-reentrant, cross-process private-state lock shared by Console
  history persistence, every attachment/database/blob mutation, private
  migration, backup capture, restore, reconciliation, and garbage collection.
- Read-only preview and exact token-confirmation for existing supported
  `runtime/` Console state. Confirmation requires quiescent Console execution,
  captures SQLite through its supported backup API, validates history/database/
  blob relationships, publishes only to missing canonical destinations, writes
  a verified receipt last, and preserves the legacy source for recovery.
- A backward-compatible general-backup revision. Version-1 JSON-only archives
  remain restorable; the current format adds canonical retained history, a
  WAL-safe SQLite snapshot pruned to retained run references, and exactly the
  ready blobs referenced by that snapshot.
- Private restore preview/confirmation bound to the exact archive and current
  JSON/private target. It creates pre-restore recovery evidence, blocks private
  reads/writes while incomplete, resumes only recognized old-or-new state, and
  verifies history/database/blob integrity before success.
- Startup refusal for incomplete/invalid private migration or restore state;
  clear instructions for explicit migration rather than silently stranding or
  overwriting legacy Console work.
- Documentation, focused/full tests, the nine-job supported CI matrix, two
  independent adversarial reviewers, publication, merge, and outcome review.

### Out of scope

- Remote Hermes endpoint or API-credential storage, secret export/encryption,
  arbitrary private files, browser storage, Hermes/Obsidian/Google state, or
  copying any credential into an ordinary backup.
- Runtime scratch restoration, active Console process checkpointing, arbitrary
  SQLite schemas, database downgrade, backup scheduling/pruning/cloud upload,
  installer/uninstaller behavior, or the unified installed `mentat` CLI.
- Deleting the legacy runtime source after migration; verified source
  preservation is intentional recovery behavior for this slice.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | New Console history, database, and blobs use only the canonical owner-only private Console root, while every scratch surface stays under runtime. | Path/mode, server, artifact, and layout-contract tests | Complete |
| AC-2 | Existing supported runtime state produces a read-only exact preview; confirmation is conflict-free, quiescent, locked, WAL-safe, source-preserving, receipt-last, and repeatable without duplication. | Migration snapshot, WAL, collision, interruption, and idempotence tests | Complete |
| AC-3 | All history, attachment, reconciliation, and GC operations share one private-state lock with consistent lock order, and an operation already waiting during migration/restore rechecks state before mutation. | Concurrency and injected-race tests | Complete |
| AC-4 | The current backup contains the nine durable JSON documents plus canonical retained history, a valid filtered SQLite snapshot, and exactly referenced ready blobs; staged/unreferenced scratch, WAL/SHM files, paths, hashes-as-authority, credentials, runtime, and recursive backups are excluded from public metadata and unintended entries. | Archive inventory, SQLite integrity, reference, privacy, and exclusion tests | Complete |
| AC-5 | Backup captures history, database references, and blob bytes under one boundary; concurrent Console persistence/attachment mutation cannot produce a mixed unit, and malformed/missing referenced content fails closed. | Lock-order, concurrent mutation, missing/tampered blob, and WAL tests | Complete |
| AC-6 | Restore remains backward-compatible with version-1 JSON-only archives and restores the current private unit only through exact preview/confirmation, pre-restore recovery evidence, bounded staging, and post-restore relational/blob verification. | v1/v2 preview, recovery ordering, stale-token, and success tests | Complete |
| AC-7 | Interrupted private restore resumes only exact recognized old-or-new history/database/blob states; unknown bytes, extra/missing blobs, changed receipt/reservation, and unsafe paths block startup and all private mutation without overwrite. | Interruption matrix, startup/live-server gate, conflict, and boundary tests | Complete |
| AC-8 | Browser responses and logs continue to expose only opaque attachment metadata and bounded errors; no local path, storage key, digest, SQLite bytes, history content, or secret is added to public output. | Request-boundary, public-summary, CLI, and redaction tests | Complete |
| AC-9 | Focused/full local checks, static gates, supported nine-job hosted CI, documentation, and two independent adversarial reviews clear on the final diff. | Verification record and CI links | Local/review complete; hosted remediation rerun pending |

### Constraints and recovery

- The server remains loopback-only and Hermes capability boundaries do not
  change.
- Private content is never placed in tracked fixtures, CLI summaries, logs, or
  review records.
- SQLite archive bytes are produced only with SQLite's backup API while private
  mutation is excluded. Because opening a WAL database read-only can still
  create source WAL/SHM files, preview may first stage an identity-revalidated
  bounded copy of the main database and present WAL, run SQLite backup against
  that private temporary, and
  verify that main/WAL/SHM source presence and bytes did not change. Those raw
  staged bytes are never archived or accepted as the final snapshot. Confirmed
  mutation and ordinary backup do this under the shared lock. Read-only legacy
  preview deliberately does not create/acquire the filesystem lock; its
  stopped-server gate plus complete before/after byte, presence, and identity
  checks provide quiescence without turning preview into a write.
- A referenced blob must be bounded, single-link, regular, owner-only where
  supported, content-address consistent, and byte-verified before capture or
  restore.
- The legacy source and a pre-restore recovery archive remain available when a
  mutation cannot be verified. Partial failure is reported without claiming
  completion.
- Python 3.11-3.13, macOS and Windows tier one, Linux preview.

### Scope discussion and approval

- Recommendation: implement the move and private backup/restore unit together
  because changing canonical paths without preserving existing state would
  strand operator work, while backing up legacy runtime paths would duplicate
  the consistency logic at a location the roadmap already rejects.
- Alternatives rejected: treating raw SQLite/WAL file copies as the backup is
  not transaction-safe; the bounded source-preserving staging exception above
  exists only to feed SQLite's backup API without source-side writes. Backing
  up all blobs or the whole private directory would capture staged
  scratch and future credentials; silently auto-moving state would violate the
  preview/confirmation contract; swapping the entire `private/` directory would
  grant authority over future secrets that ordinary restore must exclude.
- User decision: standing authorization in this thread requires the recommended
  bounded roadmap slice, fixes through two zero-finding reviews, publication,
  merge, and immediate continuation. This is the recorded process exception to
  per-phase approval pauses; technical and evidence gates remain mandatory.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Durable Console files currently live under runtime. | Canonical path/mode and scratch-separation tests. | New writes obey the approved class boundary. | OS ACL semantics beyond owner-mode checks remain platform-owned. |
| AC-2 | No private-state migration exists. | Preview/confirmation, WAL, receipt, source, collision, and interruption matrix. | Existing work is not silently lost or overwritten. | Legacy source cleanup is intentionally deferred. |
| AC-3 | History and attachment operations have separate locks. | Waiting-operation and lock-order tests. | Backup/migration/restore sees one coherent private state. | Non-cooperating filesystem actors are handled by file-object checks, not coordinated. |
| AC-4 | Version 1 excludes all private Console state. | Exact archive and filtered-database assertions. | Included/excluded private inventory is deterministic and minimal. | Only the supported schema is portable. |
| AC-5 | Live WAL/history/blob capture has no unit boundary. | Concurrent mutation and malformed-reference tests. | No mixed or dangling snapshot can claim success. | Power failure is injected at explicit durability boundaries. |
| AC-6 | Restore only replaces fixed JSON. | v1 compatibility plus current private success/recovery tests. | Old backups remain useful and current backups restore coherently. | No cross-version database downgrade. |
| AC-7 | Private startup/write gates do not exist. | Partial-state startup and already-waiting writer tests. | Ambiguous private state fails closed before mutation. | Active external process detection remains local-host only. |
| AC-8 | Public APIs already hide paths, but new summaries could regress. | Public serialization and bounded-error checks. | Private movement/backup adds no data disclosure. | Does not inspect OS-level forensic remnants. |
| AC-9 | No slice evidence exists. | Local/static/hosted matrix and two adversarial agents. | Supported regression and independent review gate. | Installer smoke remains Milestone 3. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -q` | macOS, Python 3.13 | Pass | 543 tests, four skips, from merged 1E-A final gate. |
| `python3 -m compileall -q .` and JavaScript syntax checks | macOS | Pass | Merged 1E-A final gate. |
| Private-path and backup inventory search | Repository | Gap confirmed | History, database, and blobs still use `runtime/`; version 1 explicitly excludes them. |

### Test discussion and approval

- Standing authorization accepts the mapped acceptance coverage and the
  intentional exclusions above. No browser UI or secret-storage authority is
  inferred.

## Implementation record

- Canonical retained state now lives below owner-only
  `<data-root>/private/console/`; runtime keeps only uploads, exports, execution
  inputs, workspace/artifact snapshots, and lifecycle scratch.
- `private_state.py` provides the process-reentrant shared root lock and blocks
  every private operation after waiting when a migration/restore control or
  staging tree is present.
- `private_console_migration.py` provides exact read-only preview and
  confirmation. The token binds source file identities/bytes and the normalized
  private unit; confirmation requires a stopped server, reserves first,
  promotes only to a missing destination, verifies, writes the receipt last,
  and preserves the source.
- `private_console_unit.py` captures history plus SQLite through SQLite's backup
  API, validates the exact supported schema and integrity, filters to exact
  retained history references, verifies every content-addressed blob, and
  enforces per-entry/count/64-MiB unit bounds.
- General backup format 2 adds the complete private unit while retaining strict
  canonical parsing of version-1 JSON-only archives. Version-2 restore stages
  and verifies a complete Console directory, retains recovery evidence and the
  old directory through terminal verification, and resumes exact old/new crash
  windows. Version-1 restore intentionally preserves live private state.
- Startup, history, attachment, reconciliation, garbage collection, backup,
  migration, and restore now share the private control boundary. Public
  summaries remain path/content/storage-key/digest-free.

## Verification

- Focused private-state suite: 31 tests passing, including byte-for-byte
  read-only legacy preview, missing-root creation, partial-stage rebuild,
  receipt-crash recovery, stale confirmation, startup refusal, filtered archive
  inventory, missing blob refusal, live-WAL capture, active-run fidelity,
  version-1 compatibility, version-2 private replacement, directory-exchange
  interruption/resume, state-through-cleanup recovery, live-server refusal,
  hard-linked SQLite/sidecar refusal, waiting-writer recheck, and public-summary
  privacy.
- Existing backup/restore, runtime configuration, history, attachment, and
  artifact suites pass after the path move and format revision.
- Full local discovery: 573 tests, four platform-specific skips, zero
  failures/errors on macOS Python 3.13.
- `python3 -m compileall -q .`, every `public/*.js`/`scripts/*.mjs` Node syntax
  check, and `git diff --check` pass.
- Hosted run `29662474337` passed all six Linux/macOS jobs and exposed malformed
  private SQLite snapshots in all three Windows jobs. The first remediation
  kept the live source read-only and byte-revalidated, opened only the private
  main/WAL copy read-write for recovery, and replaced path-string SQLite URIs
  with platform-correct absolute file URIs. The 30-test focused suite and full
  573-test suite passed locally before its hosted rerun.
- Hosted remediation run `29662888922` again passed all six Linux/macOS jobs
  but showed that merely opening the main/WAL temporary copy read-write still
  yielded malformed Windows snapshots in all three Windows jobs. The current
  correction therefore explicitly uses SQLite to rebuild a fresh private SHM,
  checkpoint, integrity-check, and convert only the private temporary copy to
  rollback-journal mode before `sqlite3_backup`. A fresh hosted matrix for this
  second correction is pending.
- Hosted remediation run `29663395377` passed all six Linux/macOS jobs but
  failed all three Windows jobs at the temporary copy's first SQLite checkpoint,
  proving corruption occurred before `sqlite3_backup`. The root cause was the
  private raw-file writer omitting Windows `O_BINARY`, which allowed C-runtime
  text translation while materializing captured database/WAL bytes. All private
  raw-file writes now explicitly use binary mode; the private checkpoint,
  rollback-journal conversion, and integrity check remain as pre-backup proof.
  A fresh hosted matrix for this correction is pending.

## Adversarial review

The first independent pass found five compatibility/recovery issues and eight
filesystem/crash-safety issues. The implementation was revised to:

- capture legacy SQLite/WAL from a private copy so preview cannot mutate source
  sidecars, bind the normalized unit instead of SQLite-owned SHM identity, and
  assert byte-for-byte source preservation;
- preserve active run status/timestamps during capture and report the private
  item accurately in restore preview/results;
- create a missing private root, validate or rebuild partial migration/restore
  stages, make receipt cleanup resumable, and keep restore state through old-tree
  cleanup;
- block current-format private restore while a recorded server is live;
- validate database, WAL, and SHM entries as owner-only, single-link regular
  non-reparse files before SQLite opens them; and
- add fault injection for every reported interruption window.

Later passes additionally found and resolved exact stage-inventory gaps,
post-promotion races, main-database byte stability, malformed manifest types,
cleanup-resume windows, and same-shape mutation during cleanup. The final exact
diff received independent zero-finding results from both the compatibility and
filesystem/crash-safety reviewers after the focused suite and diff hygiene.
Both reviewers then re-reviewed the Windows WAL correction and independently
returned zero findings, including the lexical absolute-URI refinement that
avoids following a pathname merely to construct the SQLite URI.

## Documentation updates

README, architecture, data-layout, changelog, CLI workflow, migration recovery,
backup version compatibility, excluded scratch state, and owner-only private
storage guidance are updated.

## Publication gate

- Branch and base: `codex/beta-1e-private-console-state` to merged `main`.
- Commit/PR packet: PR #26 is open; Windows remediation publication and a fresh
  hosted matrix remain pending.
- User authorization: Standing approval recorded.

## Outcome review

Pending publication, hosted verification, and merge.
