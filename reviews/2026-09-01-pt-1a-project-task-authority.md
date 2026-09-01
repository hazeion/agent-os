# PT-1A review log — Project and Task SQLite authority

Issue: [#179](https://github.com/hazeion/agent-os/issues/179)
Wayfinder map: [#165](https://github.com/hazeion/agent-os/issues/165)
Branch: `codex/pt-1a-project-task-authority`

## Approved scope

- Move canonical Projects and canonical Task membership into the existing
  owner-private SQLite authority.
- Introduce immutable Project IDs and migrate legacy Project-name membership
  exactly once under the existing protected authority-cutover discipline.
- Treat `projects.json` and `tasks.json` as seed/recovery artifacts after a
  durable receipt commits; do not add a live JSON fallback.
- Extend the private-state backup, restore, compatible export, rollback, and
  schema-fingerprint boundaries for the new authority.
- Refuse unsupported forward database versions before any consumer-visible
  mutation.

## Explicit exclusions

- No planner UI, workflow-stage model, broad Task editing, dependency editor,
  Task execution, delegation UI, or cascade deletion behavior.
- No browser-selected storage, runtime, path, credential, or generic bridge
  capability.

## Verification strategy

Focused automated coverage must demonstrate:

1. Deterministic one-time import, exact legacy source binding, immutable Task
   Project IDs, receipt idempotency, interrupted-cutover recovery, and stale
   source refusal.
2. Project/Task atomicity, rollback, Project rename identity preservation, and
   cross-store race refusal.
3. Backup/restore and compatible export correctness; no live JSON fallback
   after receipt; forward-version and schema-fingerprint refusal.
4. Safe bridge and public projection behavior, including hostile private
   fields, without exposing private paths or database/runtime identities.
5. Existing Task repository, backup/restore, lifecycle, and Web checks remain
   green in proportion to affected code.

## Review protocol

After focused and proportionate full verification, a separate read-only
reviewer will inspect the merge-base diff under the `review-agent` procedure.
Any actionable P0–P3 finding returns the change to implementation and the
same execution/review cycle repeats. The final log records commands, results,
and residual risks before publication.

## Execution evidence

- `python -m py_compile project_repository.py mentat_db.py task_repository.py
  server.py conversation_planning.py private_console_unit.py` — passed.
- `python -m unittest tests.test_project_repository
  tests.test_schema17_forward_migration tests.test_task_repository
  tests.test_conversation_planning tests.test_task_planning_server -v` — 80
  passed; six platform-specific durability tests skipped on Windows.
- `git diff --check` — passed.

The focused dashboard-behavior module was also exercised earlier. Two existing
Hermes test doubles select a different optional backend when the local test
environment includes WebSocket dependencies; that is unrelated to this slice.
The affected authority, planning, schema, and export modules above pass in the
same environment.

## Independent defect review

Two independent, read-only reviewers inspected the merge-base diff using the
required defect-first review procedure. They initially identified three P1
issues, all repaired and regression-tested before a clean re-review:

1. Cutover now pins and re-checks the `projects.json` pathname identity instead
   of accepting a replaced descriptor snapshot.
2. Schema 18 now applies the exact schema-17 source gate before writing a
   migration receipt.
3. Authoritative Task collection and direct replacement paths now reject a
   missing, orphaned, or changed Project ID.

Both re-reviews reported no remaining P0–P3 findings.

## Residual risk

The six skips cover POSIX-only link/mode/durability and replacement behavior;
the implementation is covered by the established cross-platform unit paths and
should be exercised on POSIX CI. `data/tasks.json` was a pre-existing local
user modification and remains intentionally unreviewed and unstaged.
