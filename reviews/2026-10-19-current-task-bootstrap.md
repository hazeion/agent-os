# Current Task bootstrap and recovery only

Contract recorded before implementation: remove the production-unused Task
migration preview/import APIs and their exclusive token/preview structures.
Keep actual fresh Task seed import with its receipt, exact source rechecks and
current SQLite authority. Keep current offline Task export and all refusal,
privacy, dependency/capacity and integrity checks. Simplify only always-false
old-version constants in Codex creation and delegation receipt guards.

Callgraph proof: preview_task_sqlite_migration and import_tasks_from_preview
are called only by tests. Their _confirmation_token and TaskMigrationPreview
are exclusive. TaskDestinationSnapshot, _inspect_destination and bounded WAL/
member read helpers remain live through export_tasks, so they are preserved.
TaskSourceSnapshot remains required by actual fresh authority and callers.
Meaningful source/URI/WAL/occupied-store assertions will exercise current
bootstrap/export instead of being deleted with obsolete preview semantics.

## Final change and preserved behavior

Exactly four top-level Task definitions are removed: TaskMigrationPreview, the
migration-only _confirmation_token, preview_task_sqlite_migration and
import_tasks_from_preview. All 50 retained Task definitions are AST-identical
to the reviewed428d392 baseline. This includes the whole TaskRepository class,
fresh ensure_task_sqlite_authority, source identity/byte rechecks, authority
receipt, domain lock, current export preview/confirmation, destination inspector
and bounded main/WAL snapshot machinery. No current row coercion is removed.

The two other source changes remove always-false compile-time version<22
clauses from Codex Task creation and delegation-receipt guards. Complete current
SQL signature, table/index and row checks remain unchanged. The delegation
comment now correctly describes caller-supplied connections instead of claiming
current connect skips validation. No runtime, permission, retry, timeout,
capability, capacity or external mutation policy changes.

Task tests now contain44 methods,37 with unchanged ASTs. Two retired preview/
confirmation-only positive methods are removed. Existing meaningful URI escaping,
committed live WAL no-write behavior, source replacement, unsafe broad/link
refusal, occupied unclaimed-store refusal and deterministic export assertions
use actual current ensure/export paths. Unsafe source cases retain bytes/modes
and prove no Task rows/receipt were committed; fresh SQLite initialization is
not confused with the retired no-database preview capability. Existing adjacent
source/receipt recheck, rollback, current/future schema refusal, concurrent
mutation, dependency/capacity, secret-free CLI, max-size export, partial-write
and current backup integrity coverage remains.

## Verification

The actual new branch starts from428d392 and preserves that reviewed history
branch unchanged. No overlays, legacy stubs or peer file edits are used. The
following focused command passed all67 methods with no skips in94.175seconds,
with ResourceWarnings treated as errors:

```sh
/private/tmp/mentat-ci-recovery-venv/bin/python -W error::ResourceWarning -m unittest tests.test_task_repository tests.test_codex_task_creation tests.test_task_delegation_receipts -v
```

Counts are44 Task methods,12 Codex Task creation methods and11 delegation
receipt methods. Raw log: /private/tmp/mentat-current-task-bootstrap-focused.log.
The only remaining Python reference to a retired API name is an existing
negative assertion forbidding production migration passthrough. Product caller
inventory and git diff --check pass. No full-suite, hosted-CI, live runtime or
release readiness claim follows from this focused result.
