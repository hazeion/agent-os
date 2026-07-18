# Feature Slice Review: Version Durable JSON Schemas

Status: Round 15 cleared with zero findings; hosted CI pending
Slice: `beta-1d-data-schema`
Date: `2026-07-18`
Review log: `reviews/2026-07-18-beta-1d-data-schema.md`

## Slice contract

### Goal

Give the fixed nine-document durable JSON inventory an explicit, durable schema
version; provide a backed-up, previewed, confirmed bootstrap migration from the
currently unversioned shape; and refuse newer unsupported schema metadata before
normal runtime writes begin.

### In scope

- One owner-only `config/` schema manifest that versions the fixed nine durable
  JSON documents without changing their browser/server-compatible top-level
  list/object shapes.
- Missing manifest means supported legacy schema version 0. A clean seed-only
  initialization receives the current version-1 manifest; an existing version-0
  root remains readable and may be upgraded explicitly.
- Explicit CLI preview and confirmation for the version-0 to version-1 identity
  migration, with an opaque state-bound token and bounded public output.
- A validated, owner-only, versioned pre-migration ZIP containing the exact nine
  durable documents and a secret-free manifest, published before schema metadata.
- Shared-lock revalidation, missing-only atomic publication, interruption-safe
  retry, immutable backup verification, live-document shape/safety validation,
  and fixed applied-step metadata without paths, content, credentials, or tokens.
- Startup validation before lifecycle cleanup or runtime/private writes, with a
  distinct bounded refusal for manifest/document versions newer than supported.
- macOS and Windows tier-one behavior, Linux preview behavior, tests,
  documentation, roadmap state, and publication evidence.

### Out of scope

- Changing any current durable JSON record shape or adding product fields.
- General backup/restore, arbitrary backup selection, restore preview, or
  uninstall behavior.
- Private Console SQLite schema evolution, WAL/SHM movement, blobs, uploads,
  exports, caches, logs, or machine-local configuration.
- Automatic migration of existing operator data during ordinary startup.
- Downgrades, best-effort forward-version reads, per-file sidecars, embedded
  wrappers that would break current consumers, or browser migration controls.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Missing metadata is recognized as supported legacy version 0; a clean all-seed initialization receives an exact owner-only version-1 manifest without changing the nine JSON documents. | Clean/repeat/mixed initialization tests | Passed locally |
| AC-2 | Preview is read-only and bounded, names all nine versions/actions plus exclusions, and binds an opaque token to exact target identity and live bytes without returning paths/content/hashes. | Filesystem snapshot and public-summary tests | Passed locally |
| AC-3 | Confirmation requires a fresh matching preview and repeats validation under the shared pinned-root lock; changed data, metadata, target, or token fails before schema publication. | Mutation, race, and token tests | Passed locally |
| AC-4 | A validated owner-only schema backup is durably published and verified before the current manifest, and retry accepts only the exact matching backup. | Ordering, archive, mode, corruption, and retry tests | Passed locally |
| AC-5 | The version-1 manifest is fixed-inventory, owner-only, no-follow, single-link, bounded, atomically missing-only, and records only ordered supported steps and safe backup evidence. | Manifest semantic and filesystem-boundary tests | Passed locally |
| AC-6 | Startup accepts valid version 0 or 1, blocks interrupted/invalid schema artifacts, and distinctly refuses any newer manifest or document version before other writes. | Startup/lifecycle ordering and forward-version tests | Passed locally |
| AC-7 | Ordinary post-upgrade JSON mutations preserve manifest validity while unsafe live shapes, modes, links, missing documents, or invalid backup evidence fail closed. | Product-writer and tamper integration tests | Passed locally |
| AC-8 | CLI/lifecycle/docs contracts are current; focused/full/local checks and hosted matrix pass; two independent reviewers clear the complete slice. | Suites, CI, and this review record | Local verification and review passed; hosted CI pending |

### Constraints and recovery

- Safety: fixed inventory only; no overwrite, deletion, downgrade, link
  following, secret copying, raw exception output, or success claim after
  incomplete verification.
- Compatibility: preserve all existing JSON consumer shapes and the source
  checkout development override; standard library only.
- Recovery: preserve live data and the validated schema backup. A matching
  backup may retry metadata publication; changed or unverifiable state fails
  closed with bounded guidance.
- Version-control strategy: branch `codex/beta-1d-data-schema` from merged PR
  #23; ready PR to `main` only after every review and verification gate clears.

### Scope discussion and approval

- Recommendation: use one fixed sidecar manifest. It versions data without
  wrapping arrays/objects or forcing broad server/frontend rewrites, and it
  gives future ordered transforms one authoritative checkpoint.
- Alternatives rejected: embedded wrappers (break every current consumer),
  nine per-file sidecars (larger atomicity/recovery surface), silent startup
  upgrade (violates preview/backup expectations), or folding in general restore
  and private SQLite work (materially broader recovery authorities).
- Tradeoff: version 0 remains supported when the manifest is absent, so existing
  installations continue to start until the operator runs the explicit
  bootstrap. New clean roots begin at version 1, and any explicit newer version
  is refused immediately.
- Approval: The user's standing instruction authorizes the recommended bounded
  slice, publication after clean review/CI, and immediate progression without a
  separate pause. Review, verification, and recovery gates remain mandatory.

## Verification plan

- Unit and integration tests for preview, confirmation, backup, manifest,
  interruption, startup ordering, normal writes, tamper cases, and forward
  refusal.
- Existing focused data-root/migration/lifecycle/document contract suites.
- Full unittest discovery, compileall, JavaScript syntax checks, and diff check.
- Hosted Ubuntu/macOS/Windows matrix on Python 3.11, 3.12, and 3.13.
- Two independent read-only adversarial reviewers on the complete slice, with
  peer critique of unique findings and iterative re-review until zero findings.

## Adversarial review

### Round 1 packet

- Diff/commit for review: Complete uncommitted branch diff from merged
  `8fe116f`, including implementation, tests, documentation, and this log.
- Local verification: 136 focused tests passed with three native-Windows skips;
  464 full-suite tests passed with the same three skips. Compileall, syntax
  checks for `public/core.js`, `public/app.js`, and
  `scripts/browser_smoke.mjs`, plus `git diff --check`, passed.
- Direct executable CLI: bounded `ready` preview followed by `migrated`, nine
  items, no server startup.
- Rendered artifacts: Not applicable.
- Review status: Round 1 completed with nine reconciled blocking findings; all
  fixes and direct regressions are implemented, with re-review pending.

### Round 1 findings and dispositions

Both reviewers inspected the complete branch diff independently before seeing
the other's report. Their unique findings were then exchanged for peer
critique. Every finding was maintained as in-scope and blocking:

1. **High — startup wrote seeds before schema refusal.** Maintained by both.
   Added a read-only schema preflight before legacy/layout handling and an
   under-lock schema guard. Current/newer roots with missing documents now
   refuse without filesystem change.
2. **High — resume could bind metadata to different backup bytes.** Maintained
   by both. Resume now requires the existing archive to equal the deterministic
   canonical bytes before metadata publication.
3. **High — malformed bounded JSON/ZIP could escape.** Maintained by both.
   Parser recursion/resource and ZIP runtime/unsupported failures are normalized
   at schema trust boundaries; deep JSON and encrypted ZIP regressions fail
   closed without tracebacks.
4. **Medium — JSON booleans passed as integer versions/sizes.** Maintained by
   both. Manifest, step, document, backup, and item integer fields require exact
   `int` types.
5. **Medium — interrupted clean initialization lost version-1 provenance.**
   Maintained by both. A hidden owner-only reservation is published before the
   first seed copy and completed after partial-copy or post-copy interruption;
   pre-existing seed-equal version-0 roots remain version 0.
6. **High — early absolute schema directory writes could hit a substituted
   root.** Maintained after peer critique. Schema mutation directories are now
   opened/created relative to the pinned root descriptor; injected substitution
   leaves the replacement untouched.
7. **High — per-file-before-global locking could deadlock nested writers.**
   Maintained after peer critique. A process-local reentrant root manager now
   takes the cross-process mutation lock before every per-file lock, with nested
   and opposing-order regressions.
8. **Medium — exact interruption temporaries had no public recovery path.**
   Maintained after peer critique. Preview now returns a state-bound
   `recovery_required` plan for exactly one safe recognized orphan temporary;
   confirmation revalidates and removes only that temporary under the pinned
   lock, then requires a new migration preview.
9. **High — seed/target ancestor or descendant overlap was permitted.** Found
   in maintainer self-audit and maintained by both reviewers. Both containment
   directions are refused before artifact reads or writes.

No Round 1 dissent remains. Round 2 must inspect the complete revised diff and
may not clear the slice until focused/full verification is clean.

### Round 1 fix verification

- 127 focused schema/runtime/data-root/migration/lifecycle/contract tests pass,
  with three native-Windows-only skips on macOS.
- 472 full repository tests pass with the same three skips.
- `compileall`, JavaScript syntax checks for `public/core.js`, `public/app.js`,
  and `scripts/browser_smoke.mjs`, plus `git diff --check`, pass.

### Round 2 findings and dispositions

Both reviewers independently re-read the complete revised diff. Unique findings
were peer-critiqued and all were maintained:

1. **High — current schema bypassed required-directory validation.** The
   under-lock guard stopped the initializer before its six-directory hardening
   loop, then runtime treated the current schema as success. Current roots now
   continue through the existing-only initializer path; missing/broad
   directories are repaired and redirected private/runtime/cache/log boundaries
   are refused without touching their targets.
2. **High — real backup/manifest post-link interruption was stranded.** The
   missing-only publisher may leave temporary and final names as two links to
   one inode. Recovery now recognizes a bounded owner-only exact same-inode
   pair with canonical expected bytes, and confirmed reconciliation removes
   only the temporary. Backup and manifest regressions cover this actual state.
3. **High — fresh seed/manifest publication kill windows were stranded.** The
   fresh reservation path now enumerates its reservation, fixed seed, and
   manifest temporaries under the pinned lock. It discards a safe pre-link temp
   or removes the temp name from an exact expected two-link promotion pair,
   verifies existing seed bytes before further copies, and removes the
   reservation last after complete verification.
4. **Medium — recovery ignored a second temporary category.** Explicit schema
   recovery enumerates both config and backup temporaries and requires exactly
   one total. A second artifact present initially or added before under-lock
   re-preview blocks confirmation and deletes neither.

No Round 2 dissent remains. Direct regressions for all four root causes pass;
full verification and Round 3 re-review are pending.

### Round 2 fix verification

- 132 focused tests pass with three native-Windows-only skips on macOS.
- 477 full repository tests pass with the same three skips.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 3 findings and dispositions

Both complete-diff reviews remained blocking. Peer critique maintained all five
findings (the missing-backup severity differed between Medium and High, but both
reviewers required the fix):

1. **High — required-directory hardening escaped the pinned root.** The shared
   initializer now creates/opens/hardens each fixed child relative to the pinned
   root descriptor on POSIX, retaining Windows handle guards. Substitution after
   locked preflight leaves the replacement untouched.
2. **High — ordinary JSON I/O escaped the locked root.** The reentrant root-lock
   manager now yields and reuses its pinned descriptor for reads, temporary
   creation, and atomic replace, with identity checks before commit and after
   mutation. A substituted pathname receives no write.
3. **High — v1 recovery could mutate a newer schema.** Preview now establishes
   forward-version state before recovery. Newer manifest/document versions with
   backup or manifest temporaries return distinct refusal and no token; an
   attempted old-token confirmation deletes nothing.
4. **Medium — reserved temporary lookalikes were ignored.** Contextual broad
   candidate detection now covers fresh reservation, fixed fresh seed,
   manifest, and schema-backup namespaces. Only exact lowercase-hex publisher
   names are recoverable; lookalikes block and remain untouched.
5. **Medium/High — fresh current could not repair missing `backups/`.** A valid
   fresh manifest with `backup: null` may pass read-only preflight when the
   backup directory alone is absent, allowing the pinned initializer to create
   it. Migrated manifests still require exact backup evidence, and redirected
   backup boundaries remain invalid.

No Round 3 dissent remains. Direct regressions and the complete local
verification gate pass; Round 4 re-review is pending.

### Round 3 fix verification

- 136 focused tests pass with three native-Windows-only skips on macOS.
- 481 full repository tests pass with the same three skips.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 4 findings and dispositions

The independent reviews produced five blocking root causes. Peer critique
maintained all five, broadened the writer finding from Windows-only to
cross-platform ancestor/final redirects, and required pinned recovery semantics
rather than relying on path-identity checks alone:

1. **High — ordinary writers followed a redirected selected root.** JSON lock
   keys and the server handoff now preserve the normalized absolute lexical
   spelling instead of resolving its destination. The existing initialization
   lock therefore validates every original path component, while POSIX I/O
   remains descriptor-relative and Windows retains its guarded handle chain.
   Final-root and ancestor redirect regressions cover both direct store and
   server writers without modifying the outside destination.
2. **High — the server could erase or disable the writer boundary.** The
   allowlisted child helper no longer creates or resolves the request-time root,
   and installed/development mutation-lock mode is recorded from the approved
   startup identity rather than filesystem resolution during a request.
3. **High — recovery validated and deleted through different roots.** Explicit
   and fresh reconciliation now inventory, open/read, compare promotion pairs,
   unlink, and verify absence beneath the same pinned root/child descriptors.
   Deterministic substitution regressions prove the replacement is untouched
   and a changed spelling cannot receive a success claim.
4. **High — an exact temporary could mask a cross-category lookalike.** One
   complete root/config/backup classifier gives invalid or ambiguous names
   global precedence and is repeated before each fresh recovery/publication/
   reservation-removal decision. Mixed exact-plus-lookalike snapshots remain
   byte-identical and receive no confirmation token.
5. **Medium — startup classified artifacts before newer metadata.** Read-only
   startup status now detects a safely readable newer manifest/document version
   before old recovery classification. Newer-plus-lookalike, reservation, and
   exact-temporary states receive the distinct forward refusal without writes.

No Round 4 dissent remains. Full local verification passes; Round 5 re-review
is pending.

### Round 4 fix verification

- 142 focused tests pass with three native-Windows-only skips on macOS.
- 486 full repository tests pass with the same three skips.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 5 findings and dispositions

Both reviews remained blocking. Peer critique maintained all three root causes:

1. **High — development mode disabled containment with the disk lock.** The
   process-reentrant lexical root manager and pinned descriptor/Windows handle
   guard now run for every durable mutation. The development flag suppresses
   only the repo-visible cross-process lock file. Normal development writes
   create no lock artifact, while final-root and ancestor redirects are refused
   through both direct and server write paths.
2. **High — final initializer success was not root-identity bound.** A new
   locked finalizer completes fresh schema publication before releasing the
   initializer lock, validates the exact permitted initial-to-final schema and
   migration states, and checks selected-path identity after final data preflight
   and again after finalization. Replacing current v1 with valid legacy v0 or a
   different current-v1 inode before the final preflight now fails closed.
3. **Medium/High — recovery could claim success after a post-check artifact
   appeared.** Explicit reconciliation snapshots the complete pinned inventory,
   verifies it again after unlink as exactly the old inventory minus the
   confirmed temporary, and revalidates any promoted final's inode and bytes.
   Cross-category injection at the unlink boundary now yields a partial failure,
   never `reconciled`; fresh terminal boundaries already perform exact pinned
   postconditions before success.

No Round 5 dissent remains. Complete local verification passes; Round 6
re-review is pending.

### Round 5 fix verification

- 145 focused tests pass with three native-Windows-only skips on macOS.
- 489 full repository tests pass with the same three skips.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 6 findings and dispositions

The original second reviewer could not return a report, so a fresh independent
replacement reviewer examined the same frozen diff. The two completed reviews
found six reconciled root causes (two reports overlapped); peer critique maintained
all of them:

1. **High — same-status root replacement could cross the final handoff.** The
   locked finalizer now records the guarded root's device/file identity. Startup
   reacquires the root, compares that opaque identity before and after pinned
   schema validation, and refuses a different current-v1 inode. Migration also
   rechecks root identity after terminal schema and byte verification.
2. **High — terminal success was status-bound, not byte-bound.** Migration and
   recovery re-read all nine live files relative to the pinned root and compare
   exact confirmation snapshots after their last mutation. Fresh finalization
   compares the same pinned inventory with packaged seed bytes after reservation
   removal. Valid-shape byte drift now prevents success.
3. **High — recovery did not prove its exact next state.** Post-delete recovery
   must now produce the exact `ready`, validated `resume_required`, or fully
   valid `already_current` preview. Invalid surviving backup/manifest evidence
   fails. An explicit mutation flag makes every failure after an attempted
   unlink a partial failure rather than an untouched block.
4. **High — durable reads did not enforce the file-object boundary.** Generic
   JSON storage now opens no-follow on every platform, rejects reparse/nonregular,
   multi-link, unowned, over-limit, or caller-disallowed-mode files, and verifies
   the private single-link temporary before commit. POSIX hard-link and native
   Windows file-reparse regressions cover the boundary.
5. **High — successful product writes could invalidate the next startup.** The
   schema-aware server wrapper supplies a byte ceiling and fixed top-level type;
   serialized output is checked before temporary creation. Wrong-shape and
   oversized mutations leave current schema bytes unchanged.
6. **Medium — nested development mode could swallow an installed lock request.**
   Per-root reentrant state records the outer disk-lock mode. True-to-false
   inheritance is allowed, while false-to-true escalation fails closed.

No Round 6 dissent remains. Complete local verification passes; Round 7
re-review is pending.

### Round 6 fix verification

- 154 focused tests pass with four platform-specific skips on macOS.
- 498 full repository tests pass with the same four skips.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 7 findings and dispositions

Both independent reviews remained blocking. Peer critique maintained the six
technical root causes and the publication-log correction:

1. **High — product reads bypassed the durable boundary.** `read_json_file()`
   now uses the allowlisted lexical child, process/root lock, pinned descriptor
   or Windows guard, no-follow single-link file validation, byte ceiling,
   installed mode, and fixed top-level type. Linked or oversized outside data
   is never returned through product reads.
2. **High — installed writes could chmod a replacement pathname.** POSIX parent
   hardening now uses and verifies `fchmod()` on the pinned root descriptor.
   The Windows pathname branch remains protected by its retained no-delete
   handle chain. A writer-entry swap leaves the replacement mode and bytes
   untouched.
3. **Medium/High — temporary verification was not bound through commit.** The
   writer retains the temporary descriptor on POSIX, compares exact serialized
   bytes and inode/name identity before replace, performs exact no-follow
   post-commit validation, and cleans the temporary after every precommit
   failure. Windows closes only at its required replace boundary and still
   requires exact post-commit verification; committed-but-unverified failures
   use a distinct exception.
4. **High — terminal schema evidence was still pathname-based and ordered.** A
   descriptor-bound status capture now retains config/backup child descriptors,
   reads manifest, backup, artifact inventories, and all nine live files from
   the pinned root, re-reads evidence identities/bytes, and compares exact
   confirmation snapshots before success. Migration, recovery, fresh finalizer,
   and startup-under-lock use this boundary rather than absolute status/preview.
5. **High — missing installed documents could be silently recreated.** Product
   reads and mutations require every fixed document to exist after installed
   startup, so loss fails before a mutator or temporary can run. Generic storage
   retains opt-in creation only for explicitly different data models.
6. **Medium — unparameterized Windows mutation could still follow a file
   reparse.** Generic JSON reads now always use the platform no-follow opener and
   validate regular/single-link/owner state, even when no size/mode policy was
   supplied.

No Round 7 dissent remains. Complete local verification passes; Round 8
re-review is pending.

### Round 7 fix verification

- 158 focused tests pass with four platform-specific skips on macOS.
- The Round 7 record originally claimed 502 full repository tests passed. Both
  Round 8 reviewers reproduced one error in the installed-root overview fixture;
  that historical claim was inaccurate and is superseded by the clean Round 8
  gate below.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 8 findings and dispositions

The original second reviewer became unavailable, so two replacement reviewers
independently inspected the same frozen complete diff. They agreed on the red
full-suite gate; their unique technical findings were exchanged for peer
critique, and all six root causes were maintained:

1. **Medium — startup status still used pathname evidence under its pinned
   lock.** `schema_startup_status()` now uses the descriptor-bound status
   capture and repeats root identity validation. A regression makes the removed
   pathname helper fail if it is ever reintroduced under this lock.
2. **High — descriptor-relative untrusted opens could block on FIFOs.** Schema
   artifact/live-document reads, durable post-commit verification, and shared
   publication verification now include nonblocking, close-on-exec, no-follow
   opens before regular-file validation. POSIX FIFO regressions prove both
   boundaries return promptly rather than holding a shared mutation lock.
3. **High — a changed runtime root received only the disk lock, not the full
   installed policy.** One normalized effective durable-root decision now
   controls cross-process locking, owner-only mode, and require-existing
   behavior for both reads and writes. A post-startup root mismatch cannot read
   broad documents or silently recreate a missing fixed document.
4. **Medium — the read-only email endpoint was rejected by the write allowlist.**
   Reads use the union of fixed schema seeds and project-owned writable
   documents; writes retain the narrower mutation allowlist. `email.json` is
   readable but remains impossible to mutate through the generic wrapper.
5. **High — a durable schema backup could be misreported as untouched after a
   post-commit root swap.** Missing-only publication exposes a commit callback
   at the link-and-directory-fsync boundary, verifies through the retained
   parent descriptor, and classifies every later failure as partial. The
   displaced pinned root retains the exact backup, no manifest, and no
   temporary while the replacement remains untouched.
6. **Medium — the recorded full-suite pass was false.** The overview fixture
   now supplies the complete private fixed inventory with an empty dashboard
   identity, preserving the installed missing/mode contract. All older test
   root overrides now bind both selected and approved roots; deliberate
   mismatch regressions remain separate.

No Round 8 dissent remains. Complete local verification passes; Round 9
re-review is pending.

### Round 8 fix verification

- 156 focused schema/store/runtime and affected product integration tests pass,
  with one native-Windows skip on macOS.
- 508 full repository tests pass with four platform-specific skips on macOS.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 9 findings and dispositions

Both independent reviewers found the same incomplete publication inventory and
separate adjacent windows in the backup-publication state machine. Peer critique
maintained both technical variants:

1. **High — mutation tracking began after a fallible directory fsync.** The
   publication callback is now a publication marker, invoked immediately after
   the final missing-only hard link succeeds and before directory durability or
   verification operations. A link-success/root-swap/fsync-failure regression
   must return partial failure with the exact backup retained in the displaced
   root and the replacement untouched.
2. **High — changed reciprocal backup evidence still returned an untouched
   block.** Once publication is marked, any unequal or unverifiable reciprocal
   descriptor read raises into the shared partial-failure classifier. A direct
   post-helper changed-read regression retains backup evidence, publishes no
   manifest, leaves no temporary, and never reports `blocked`.
3. **Medium — the publication record omitted eleven compatibility-test files.**
   The proposed-file inventory now enumerates every current tracked and
   untracked diff path, including the console, calendar, context-pack,
   dashboard, delegation, deletion, note, and planning fixtures updated for the
   approved-root contract.

No Round 9 dissent remains. Complete local verification passes; Round 10
re-review is pending.

### Round 9 fix verification

- 85 focused schema/store/runtime tests pass, with one native-Windows skip on
  macOS.
- 510 full repository tests pass with four platform-specific skips on macOS.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 10 findings and dispositions

One reviewer returned zero findings. The other review run failed before a
report, so a fresh independent replacement inspected the same frozen snapshot
and found one high-severity race. The clean reviewer peer-critiqued and
maintained it:

1. **High — the pre-existing backup branch escaped the pinned directory.** The
   branch used pathname existence and archive validation even while retaining
   `backup_fd`. A POSIX swap-away/restore sequence could validate a replacement
   root's exact backup, restore the original pinned root, and publish a manifest
   there without its required backup. Presence and exact canonical bytes are now
   read only through `backup_fd`, then re-read through that descriptor
   immediately before manifest publication. The pathname validator is forbidden
   in this locked branch. An ABA regression swaps the selected path around the
   pinned existence decision and proves the original root receives its own
   exact backup before its manifest and finishes current.

No Round 10 dissent remains. Complete local verification passes; Round 11
re-review is pending.

### Round 10 fix verification

- 86 focused schema/store/runtime tests pass, with one native-Windows skip on
  macOS.
- 511 full repository tests pass with four platform-specific skips on macOS.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 11 findings and dispositions

One reviewer initially cleared the diff. The other found a deeper confirmation
race; peer critique maintained it as high and blocking:

1. **High — confirmation re-preview read one tree while mutation descriptors
   authorized another.** After taking the root lock, migration called the public
   pathname preview again. A swap-away/restore sequence could preview confirmed
   tree A, restore changed pinned tree B, then publish A's backup and manifest
   into B. Terminal verification returned partial, but ordinary startup could
   still accept the resulting version-1 B because historical backups are not
   required to equal later live bytes. The locked pathname preview is removed.
   A dedicated pinned confirmation capture now validates exact live snapshots,
   confirmation token, stable complete artifact inventory, exact resume backup,
   and exact recovery temporary/promotion evidence for `ready`,
   `resume_required`, and `recovery_required` before any publication or deletion.
   The A/B ABA regression proves changed B remains byte-identical legacy with no
   backup or manifest, and promoted recovery-pair tests remain green.

No Round 11 dissent remains. Complete local verification passes; Round 12
re-review is pending.

### Round 11 fix verification

- 87 focused schema/store/runtime tests pass, with one native-Windows skip on
  macOS.
- 512 full repository tests pass with four platform-specific skips on macOS.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 12 findings and dispositions

One reviewer initially cleared the diff. The other found a recovery-token state
gap; the clean reviewer reproduced all four core transitions and maintained the
finding as high and blocking:

1. **High — recovery confirmation did not bind temporary-only versus promoted
   hard-link-pair state.** `_RecoveryArtifact` and its token recorded the
   temporary identity/bytes but not whether the final backup or manifest name
   already existed as the same inode. The same token could therefore authorize
   deletion after either promotion direction changed, yielding a different
   `ready`, `resume_required`, or `already_current` post-state than previewed.
   Recovery artifacts now record `final_present`, expose only the bounded
   `temporary_only`/`promoted_pair` value to token construction, compare that
   state during pinned confirmation, and enforce it again immediately before
   unlink. A distinct pre-mutation state-change result remains `blocked`. The
   eight-case matrix covers backup and manifest, both promotion directions, and
   changes before pinned matching or between matching and deletion; every case
   preserves the temporary and rejects the stale confirmation.

No Round 12 dissent remains. Complete local verification passes; Round 13
re-review is pending.

### Round 12 fix verification

- 88 focused schema/store/runtime tests pass, with one native-Windows skip on
  macOS.
- 513 full repository tests pass with four platform-specific skips on macOS.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 13 findings and dispositions

One reviewer initially cleared the diff. The other found a narrower pre-unlink
window; peer critique reproduced and maintained it as high and blocking:

1. **High — promotion state was not rechecked directly adjacent to recovery
   deletion.** `_discard_recovery_artifact()` checked token-bound final presence
   before several final validations. A hard-link transition triggered as the
   last inventory check returned could still delete the stale-confirmation
   temporary. After that inventory check, the code now reopens and validates the
   temporary and final through the pinned parent descriptor, including final
   presence, link count, inode identity, exact paired bytes, size, and digest,
   directly before setting the mutation marker and unlinking. Boundary failures
   raise the dedicated pre-mutation state-change result. The recovery matrix now
   has twelve cases: backup/manifest, both promotion directions, and transitions
   before pinned matching, before discard, or at the exact final-inventory/
   pre-unlink boundary. Every stale confirmation returns `blocked` and preserves
   the byte-exact temporary.

No Round 13 dissent remains. Complete local verification passes; Round 14
re-review is pending.

### Round 13 fix verification

- 88 focused schema/store/runtime tests pass, with one native-Windows skip on
  macOS.
- 513 full repository tests pass with four platform-specific skips on macOS.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.

### Round 14 final review

Both independent reviewers inspected the same frozen complete diff and returned
zero findings. They specifically verified token-bound recovery promotion state,
descriptor-relative confirmation, adjacent pre-unlink evidence validation, the
twelve-case recovery matrix, every prior disposition, documentation, the review
record, and the exact 32-path publication inventory.

### Round 14 verification

- 88 focused schema/store/runtime tests pass, with one native-Windows skip on
  macOS.
- 513 full repository tests pass with four platform-specific skips on macOS.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.
- Remaining reviewer dissent: None.

### Hosted matrix follow-up and Round 15 fix

Hosted run `29656633349` passed all Ubuntu and macOS jobs on Python 3.11,
3.12, and 3.13, but all three Windows jobs exposed one platform-specific
exact-byte bug. `write_json_atomic()` created its temporary descriptor without
`O_BINARY`; Windows text-mode translation changed serialized line feeds on
disk while the same text descriptor translated them back during pre-commit
verification. The secure committed-file reopen correctly used binary mode and
therefore rejected the changed bytes with `JsonCommitVerificationError`.

All low-level regular-file reads and the atomic temporary write in this slice
now request `O_BINARY` where available. A regression injects a synthetic binary
flag on POSIX, records the temporary open, and proves that the exact-byte writer
requests it. The revised frozen snapshot requires complete local verification,
two fresh independent zero-finding reviews, and a clean hosted matrix before
publication can clear.

### Round 15 fix verification

- 89 focused schema/store/runtime tests pass, with one native-Windows skip on
  macOS.
- 514 full repository tests pass with four platform-specific skips on macOS.
- `compileall`, all three JavaScript syntax checks, and `git diff --check` pass.
- Independent re-review: Both reviewers returned zero findings on the final
  native-safe technical snapshot.

### Round 15 findings and dispositions

One reviewer found a low-severity record inconsistency: the document headline
still described the cleared Round 14 snapshot after the hosted-Windows fix had
changed it. The headline now states the current Round 15 and hosted-CI gates.
The other reviewer found a medium-severity native-Windows flaw in the portable
regression: it replaced a real `os.O_BINARY` process-wide with the synthetic
POSIX bit, which would remove binary mode from the exact write and contaminate
the secure committed reopen. The test now preserves and passes through the
native Windows flag, and synthesizes and strips a fake bit only when the host
does not define `O_BINARY`. Both independent reviewers then rechecked the exact
revised diff and returned zero findings.

### Implementation notes

- `data_schema.py` owns the fixed manifest, preview/token, deterministic schema
  backup, confirmation, interruption retry, startup validation, and fresh-seed
  initialization.
- `json_store.update_json()` shares the cross-process data mutation lock for
  installed durable roots, while the repo-local development override avoids a
  new tracked-root lock artifact.
- Runtime startup recognizes supported version 0, initializes clean version 1,
  validates current version 1 under a pinned lock, and reports newer versions
  distinctly before lifecycle/private/runtime writes.
- The CLI and lifecycle surfaces keep schema preview/confirmation mutually
  exclusive and side-effect isolated from server startup.
- Documentation marks only Milestone 1D complete and advances the next bounded
  work to general backup/restore; Milestone 1 remains in progress.

## Publication gate

- Proposed files: `data_schema.py`, `data_layout.py`, `data_migration.py`, `json_store.py`,
  `runtime_config.py`, `server.py`, `mentat_lifecycle.py`,
  `tests/test_agent_console_artifact_integration.py`,
  `tests/test_agent_console_attachment_runs.py`,
  `tests/test_agent_run_history.py`, `tests/test_calendar_week_backend.py`,
  `tests/test_context_packs.py`, `tests/test_daily_workflow.py`,
  `tests/test_dashboard_behaviors.py`, `tests/test_task_delegation.py`,
  `tests/test_task_deletion.py`, `tests/test_task_note_context.py`,
  `tests/test_task_planning_server.py`,
  `tests/test_data_schema.py`, `tests/test_json_store.py`,
  `tests/test_runtime_config.py`, `tests/test_local_server_lifecycle.py`,
  `tests/test_data_layout_contract.py`, `tests/test_next_phase_readiness.py`,
  `tests/test_beta_contract.py`, `tests/test_ci_workflow.py`, `DATA_LAYOUT.md`,
  `ARCHITECTURE.md`, `README.md`, `ROAD_TO_BETA.md`, `CHANGELOG.md`, and this
  review log.
- Branch/base: `codex/beta-1d-data-schema` to `main`.
- Commit message: `Version durable JSON schemas safely`.
- PR title: `Add durable JSON schema versioning`.
- User authorization: Standing approval granted; publication remains gated on
  clean independent review and hosted CI.

## Outcome review

- Classification: Ready for publication; hosted CI pending.
- Acceptance criteria summary: AC-1 through AC-7 passed; AC-8 awaits hosted CI.
- Remaining reviewer dissent: None after Round 15.
- User decision: Standing approval recorded; publication remains gated.
- Next slice authorized: Yes after this slice merges cleanly.
