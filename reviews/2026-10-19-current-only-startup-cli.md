# Current-only startup and CLI

The owner explicitly retired older database upgrades and old backup paths. This branch removes the legacy JSON, private Console and standalone Agent-registry migration modules and commands. Named migration modules leave both public package inventories. Their eight unchanged pure file helpers now live in `data_documents`; current backup and JSON validation use that module.

Startup admits supported fresh/current storage before hardening. It rechecks schema, restore state and root identity under the initialization lock. A new SQLite database is created after the fresh reservation and before JSON manifest finalization. Interrupted fresh initialization can resume through that reservation. An established current JSON root with a missing database is refused at startup. No existing source is upgraded, deleted or overwritten to achieve admission. The packaged-seed development override and platform/config precedence remain unchanged.

The shared missing-database Console inspection runs before private storage hardening and direct SQL creation. It permits only absent/empty storage or exact current empty UTF-8 history, with bounded reads, duplicate-key rejection, descriptor-relative no-follow opens, identity and private regular-file checks. Existing current SQLite authority continues to ignore stale JSON and retired registry bytes. Those are never alternate authorities.

Current validator branches now enforce schema46 rather than omitting tables for older versions. Existing provenance, cutoff40 action receipts, unknown outcomes, producer consumption, capacity charges and archival restrictions remain. Plain offline `task-export` recovery remains, while schema5 sibling export and migration commands are removed. Doctor now checks SQLite admission read-only and does not report an older database as healthy merely because its JSON metadata is valid.

Only upgrade-specific positive tests are retired. Current webhook replay/concurrency and attention lifetime/capacity tests remain. The actual current database-size bound is checked inside the existing10,000-row attention capacity fixture rather than maintaining a second upgrade-only fixture. Restore fixtures now create owner-only target directories instead of relying on automatic hardening of an existing unsafe private database.

## Verification checkpoint

- Source review of `0bd705b` and `f1955a5` cleared independently by both repository and backup agents. Current JSON initializer, shared history race fixes and storage documentation also received two independent reviews across the composed branches.
- Full Python collection after removed migration imports and current JSON composition:2591 methods, zero import failures. This is collection only, not a full-suite pass.
- Startup/core/Vercel group:56 methods,55 passed and one specific overlap-error projection failure. The projection was fixed; the corrected overlap and current producer/backup admission group then passed all12 methods. Final full-suite verification remains necessary.
- Current domain group:107 methods,100 passed,3 existing platform skips and4 fixture/obsolete-test errors. The errors were two retired schema35 upgrade fixtures and two unsafe restore-target fixture modes. Both current restore tests subsequently passed with owner-only targets; the separate current maximum-size fixture passed before its assertions were folded into the existing capacity test.
- Final current webhook plus attention modules:20 methods pass in59.719seconds, no skips, with ResourceWarnings treated as errors. This includes the preserved10,000-row live/retired capacity and actual current storage bound.
- Doctor older-schema/no-write and path-privacy checks:2 pass in0.042seconds with ResourceWarnings as errors.

Logs are under `/private/tmp/mentat-current-*`; these results do not claim hosted checks, Windows execution, a Linux operator host, live provider qualification, production readiness or a completed full-suite run. Personal edits in the original checkout remain untouched. Nothing from this cleanup has been pushed yet.
