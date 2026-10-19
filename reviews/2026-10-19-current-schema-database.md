# Current-only database bootstrap

The user chose fresh/current databases only and retired older upgrade and backup paths. This change implements the core SQLite boundary for that decision. Repository validators, private backup/restore and startup orchestration are separate coordinated changes.

## Contract recorded before implementation

Keep schema46 and its exact final object graph. Replace the historical ALTER/rebuild sequence with fixed current DDL. Fresh initialization must preserve random approval/confirmation epochs, the unbootstrapped owner singleton, and the separately gated fresh Agent authority receipt. Existing current databases keep their journal1..46 and execute no DDL or row conversions. Older, future, malformed and unsafe existing databases are refused before directory creation/hardening, writable SQLite or WAL configuration. No source database is wiped or automatically replaced.

`MIGRATIONS` remains a constructor compatibility export containing only `(46, CURRENT_BOOTSTRAP_SQL)`. The script creates the current layout and inserts structural receipts1..45; callers append receipt46 as before. Those structural rows describe the current format and do not implement old-root upgrades. `expected_schema_signature` accepts only46 and has one bounded cache entry. `schema_signature_state` returns only `expected` or `invalid`. Historical drift, plan conversion, Run-source conversion and their temporary-table recipes are removed.

## Fixed DDL and authority

The baseline was extracted once from an isolated in-memory execution of the original reviewed schema46 code at8c0ef6ac909e04f3103f62b4dbdfa7fd211ef9d7. SQLite creates its own internal sequence table. The resulting256-object token signature is exactly unchanged, with JSON signature SHA256 `2962a6b78b5f94ea0d5ae01cdbcba36a1f577e419bed287feb81ee5c98ae6218`. The regression pins that independent original signature.

The three fresh singleton tables retain their original values. Approval and confirmation epochs each use fresh random32-byte blobs. The owner-auth singleton remains unbootstrapped, revision1, timestamp0, passkey method and owner generation0. Agent authority is never inserted by the DDL recipe: initialization retains both authority-presence callback checks, and the existing post-commit raced-receipt cleanup remains unchanged. Task authority remains separately owned.

Fresh construction runs in one transaction and rolls back every object and receipt on failure. Existing current connections validate one coherent read transaction containing the complete receipt journal and exact schema, and run no persistent DDL or row conversion.

## Admission before source writes

`validate_current_database_root(data_dir)` is a public read-only startup check. It returns false only for missing SQLite, true for exact current storage, and raises `MentatDatabaseError` for unsupported, corrupt or unsafe existing storage. Direct connection setup enforces the same admission internally and binds the admitted database inode to the later writable handoff. The live SQLite connection revalidates current state before persistent WAL setup or file hardening. Existing path, permission, link and identity checks remain.

A mandatory use of the existing strict backup snapshot caused all30 owned live opens to refuse while a writer committed every3ms. That strict API remains unchanged. Admission instead captures bounded pinned main bytes with stable metadata across capture, plus a twice-compared prefix of the source WAL's initial size. Later WAL appends are permitted; prefix rewrite/reset and main-file changes refuse. Source SHM contents are never read or reused. SQLite recovers the captured WAL prefix and builds SHM only inside an owned temporary copy, which is removed on success and failure. Source file identities remain checked. This is live format admission, not a backup consistency claim or cached trust decision.

The same owned append-only workload then completed30/30 opens with172 writes in0.70seconds. An earlier checkpointed current fixture measured roughly19ms per open including admission. These are local development measurements, not a benchmark or cross-platform acceptance claim. A checkpoint/reset that changes captured main/WAL state can still cause a safe refusal. No retries or inode-only qualification cache were added.

## Verification and retired fixtures

The focused27-method command passed with ResourceWarnings treated as errors in2.475seconds on macOS/Python3.13, with no skips. It covers exact256-object identity, structural receipts, fresh singleton/epoch/Agent gates, rollback, current no-DDL readback, unchanged old/future/malformed roots, unsafe permissions/links, committed unsupported WAL, absent source SHM, append-only live admission, WAL rewrite/reset, main mutation, owned temporary cleanup, concurrent Task mutations, database handoff replacement, and both fresh Agent race cleanup cases. Raw log: `/private/tmp/mentat-current-schema-database-focused.log`.

The old schema45->46 producer-upgrade tests are replaced by current producer-layout/closed-admission checks, current drift refusal without repair, and atomic fresh bootstrap rollback. Older forward-only modules12/16/17/20/22 are obsolete once their retired upgrade paths are removed globally. Mixed modules such as schema25 owner methods, plan-policy migration and proposal-source migration also contain current owner/security/SQL guard assertions; those require selective adaptation rather than wholesale deletion. This branch changes none of those peer-owned tests or runtime policy.

No Linux or Windows execution, hosted CI, production readiness or runtime activation is claimed. Independent reviews and combined current-only integration tests remain required.
