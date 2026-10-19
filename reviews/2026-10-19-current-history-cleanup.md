# Current SQL history and lifecycle fixtures

Contract recorded before implementation: retire production-unused JSON history
file load/save/upgrade/permission-repair APIs and the obsolete record-renaming
script, while preserving current SQL summary hydration, redaction, event and
transport normalization. Port current security and application replacement
assertions to canonical SQLite. Removed migration flags must refuse before
startup mutation; current lifecycle preflight remains tested. No current row
provenance, unknown outcome, capacity, timeout or provider behavior changes.

Caller audit found only tests using the retired file APIs. RunRepository still
uses _hydrate for validated current SQL detail projections, so it stays unchanged.
Outside original test scope, root explicitly assigned remote Console, Hermes
transport, observability and application replacement/uninstall fixture ports.
The obsolete scripts/mentat_migrate.py has no product caller or CLI subcommand.

## Implementation and preserved current behavior

The five removed definitions are save_run_summaries, load_run_summaries,
secure_history_permissions, _chmod_verified_path and their private sort key.
All15 retained projection/normalization/redaction/_hydrate definitions are
AST-identical to root checkpoint7822226. The module now performs no JSON file
load/save, old-version recovery or permission-repair operation. Summary format3
and event format1 remain current projection formats, not older SQLite support.
The old schema1/2 file acceptance constants and unused I/O imports are removed.
No production caller used the retired file APIs; all test callers are ported.

Current privacy tests now persist through canonical SQL and inspect the validated
SQL-derived backup projection. They retain bounded excerpts, common/extended
secret redaction, modes0600/0700, malformed-binding atomic refusal, deterministic
retention, structured-event/cursor/binding semantics, degraded-state handling,
initial-write/no-worker safety, post-start failure controls and steer/finalizer
races. Current corruption/future schemas and unsafe unclaimed history refuse
without hardening or rewriting; established SQL ignores stale JSON. The inode
attack test now probes current no-follow admission instead of retired repair.

Remote usage/partial state, transport-binding rollback and observability context
round trips use actual SQL. Remote unbound Console restart verifies durable
interruption plus partial evidence through the existing current recovery API,
not a fabricated JSON-loader error. Application replacement/uninstall still
preserves exact operator documents, Context Packs, SQL-derived private digest,
attachments/blobs and backup bytes; it additionally checks actual canonical Task
retention after initializing current Project/Task/Run authority.

The obsolete rename-only scripts/mentat_migrate.py and its single upgrade test
are removed. No migrate CLI subcommand existed to remove. The two retired
lifecycle flags now prove argparse refusal before initialization/listener
cleanup. Three unchanged current preflight tests caught a real remaining
Namespace reference in mentat_lifecycle; root fixed exactly those four obsolete
flag checks in64b4a5c, normally merged before final verification.

## Verification

The initial35 history/event methods passed22.986seconds. An initial54-method
caller/lifecycle run exposed the real lifecycle bug above and one incomplete
Project timestamp fixture; neither was hidden by weaker assertions. After the
root source fix and valid current fixture, the app preservation scenario passed
independently in18.434seconds.

Final verification runs on the real normally merged root55da226 stable graph,
with no overlays or legacy stubs. All89 focused methods completed in20.835s:
88passed and one existing Linux-only pidfd acceptance test skipped on macOS.
ResourceWarnings are errors. Raw log: /private/tmp/mentat-current-history-final.log.
The command includes both full history/event modules, the full local lifecycle
module, full application replacement/uninstall module and the three directly
affected remote/transport/observability methods. No full Python/hosted suite,
Linux pidfd execution or release readiness is claimed.

Remaining audit findings outside this branch: test_project_producer_transactions
still calls removed JSON schema migration helpers to prepare an otherwise
current backup fixture. TaskRepository preview_task_sqlite_migration and
import_tasks_from_preview are now product-unused preview/test primitives; their
remaining test consumers need a separate explicit retirement or current fresh
initialization port. Compile-time old-schema conditions remain in
codex_task_creation and task_delegation_receipts; they do not admit old databases
through the current kernel but are candidates for narrow dead-branch cleanup.
