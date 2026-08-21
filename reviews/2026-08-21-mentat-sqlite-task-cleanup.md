# Feature Slice Review: SQLite Task Runtime Cleanup

Status: In progress
Slice: `mentat-sqlite-task-cleanup` (Pivot 1C-D)
Date: 2026-08-21
Review log: `reviews/2026-08-21-mentat-sqlite-task-cleanup.md`

## Slice contract

### Goal

Remove obsolete live Task JSON access from Mentat runtime workflows while
preserving the explicit seed, migration, export, downgrade, and recovery
compatibility paths around the authoritative SQLite Task repository.

### In scope

- Route all server-side Task reads through an explicit SQLite-authority helper.
- Route all server-side Task mutations through an explicit SQLite-authority helper.
- Keep `tasks.json` only where it is an immutable packaged seed, migration
  source, explicit offline export/downgrade target, compatibility fixture, or
  documented recovery artifact.
- Add source-contract and stale-file regression coverage for the runtime
  boundary.
- Include the user's current runtime UI changes in `public/app.js`,
  `public/index.html`, `public/styles.css`, and their UI/visual contract tests;
  verify the resulting rendered behavior.
- Update the pivot roadmap, data-layout status, changelog, and architecture/
  operator wording needed to close 1C-C and record 1C-D.

### Out of scope

- Next.js/React/Tailwind frontend work.
- A second runtime, dynamic routing, database convergence, or orchestration
  redesign.
- Removal of supported migration/export/recovery behavior.
- Inclusion of operator data fixtures, untracked design/mockup/video artifacts,
  lockfiles, or scratch files already present in the worktree. The tracked task
  fixture contains personal/message content and remains excluded from this
  public-safe slice.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | No live server Task workflow uses the generic JSON read/write path or reads/writes `tasks.json` as runtime authority. | Static source-contract test plus focused server tests. | Pass |
| AC-2 | Task reads and mutations continue to use SQLite authority with existing response shapes and safety/error behavior. | Task, planning, deletion, delegation, webhook, search, and dashboard regression suites. | Pass |
| AC-3 | Seed, migration, export/downgrade, recovery, packaging, and compatibility paths remain available and are not falsely classified as live runtime access. | Migration/export/data-root/backup tests and source-boundary inspection. | Pass |
| AC-4 | Roadmap and operational documentation accurately identify 1C-D as active and preserve the separate Agent Registry / later 3C boundary. | Documentation contract tests and review-log inspection. | Pass |
| AC-5 | The full local verification gate remains green, including browser smoke, packaging/artifact checks, and Lighthouse where available. | Focused suite, full suite, browser smoke, packaging, and Lighthouse evidence. | Pass |
| AC-6 | The current UI changes render and remain operable without regressing accessibility or task interactions. | UI/visual contract tests, Node syntax check, and browser smoke at desktop/mobile widths. | Pass |

### Constraints and recovery

- Safety: SQLite remains the sole live Task authority after the existing
  authority receipt; stale JSON must not be consulted as fallback.
- Compatibility: preserve public Task API shapes and explicit offline
  migration/export/downgrade workflows.
- Rendered behavior: preserve and verify the user's current UI changes,
  including date-aware task ordering/labels, overdue styling, the focus-list
  scrollbar, project filtering, task completion action, and accessibility
  semantics; existing browser smoke must remain green.
- Rollback or recovery: changes remain isolated on the feature branch; the
  tracked `data/tasks.json` seed and explicit export/recovery tools remain
  untouched as runtime authority artifacts.
- Documentation targets: `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`, `DATA_LAYOUT.md`,
  `ARCHITECTURE.md`, and `CHANGELOG.md`.
- Version-control strategy: dedicated branch from current `main`; preserve all
  pre-existing unrelated worktree changes; no commit, push, or PR without a
  later explicit publication approval.

### Scope discussion and approval

- Recommendation and rationale: use a narrow explicit Task-authority boundary
  and remove only obsolete live JSON call sites; this completes the cutover
  without broad frontend or database work.
- Alternatives considered: leave generic JSON call sites in place (smaller
  diff, but leaves the obsolete authority seam visible); begin Slice 2A (would
  skip unresolved cleanup and documentation work).
- User decisions: user approved this contract and test strategy on 2026-08-21,
  then explicitly expanded the slice to include the current runtime UI changes.
- Approved at: 2026-08-21, user message `approved`.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | `server.py` still contains many direct `read_json_file("tasks.json")` and `update_json_file("tasks.json")` call sites. | AST/source-contract test and repository-wide task-reference inventory. | Live workflows use the explicit authority boundary; remaining JSON references are classified compatibility paths. | Static classification cannot prove every dynamic call; runtime tests cover major workflows. |
| AC-2 | Existing behavior is routed through compatibility branches of the generic helpers. | Focused Task repository, dashboard, planning, deletion, delegation, webhook, and server integration tests. | SQLite reads/writes and public behavior remain intact. | Does not replace a full multi-process production soak. |
| AC-3 | JSON references mix seed/migration/export behavior with runtime call sites. | Source inventory plus migration/export/data-root/backup tests and stale-file read/write regressions. | Explicit compatibility paths remain functional and stale JSON cannot affect live reads after authority. | Packaging installers are inspected and tested through existing artifact gates. |
| AC-4 | Roadmap and data-layout status still describe 1C-C as active. | Documentation assertions and exact text inspection. | Project records match merged implementation and current slice. | Does not constitute hosted release CI. |
| AC-5 | Existing 1C-C evidence is local; 1C-D must rerun applicable gates after cleanup. | Focused tests, `python -m unittest discover -s tests -q`, browser smoke, package/artifact checks, and Lighthouse. | Regression and release confidence. | Hosted CI/release checks require later publication and are not performed before publication approval. |
| AC-6 | UI changes are covered at source and rendered boundaries. | `node --check public/app.js`, `tests.test_home_operations_ui`, `tests.test_visual_contract`, and browser smoke. | The current UI changes are syntactically valid and preserve tested interaction/visual contracts. | Existing browser smoke is the rendered gate; no new screenshot baseline is required. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Repository/source inventory | macOS, Python 3.13, current `main` plus unrelated dirty files | Pass | 17 direct runtime Task references remain in `server.py`; Slice 1C-C and its post-merge registry correction are present on `main`. |
| User scope update | 2026-08-21 | Accepted | Include current runtime UI files/tests; exclude operator data fixtures and unrelated untracked artifacts. |

### Test discussion and approval

- User questions and decisions: user approved the concrete 1C-D contract and
  test strategy after it was presented, then directed that the current UI
  changes be included. The implementation scope was updated to include the
  runtime UI files/tests and rendered verification.
- Accepted coverage gaps: hosted CI and ready-PR publication remain gated on a
  later explicit publication approval; operator data fixtures are not part of
  this public-safe slice.
- Approved at: 2026-08-21, user message `approved`.

## Implementation record

### Changes

- Added explicit `read_task_snapshot()` and `update_task_snapshot()` server
  helpers backed by the authoritative SQLite Task repository.
- Migrated live dashboard, planning, deletion, delegation, webhook, search,
  attachment, and activity workflows to those helpers; retained the generic
  JSON helper branches only as compatibility shims for older callers/tests.
- Removed `tasks.json` from the generic server write allowlist and added source
  and stale-file regression coverage proving live reads/writes ignore stale
  JSON after the authority receipt exists.
- Updated the 1C-C/1C-D roadmap, data-layout status, architecture boundary,
  and changelog wording.
- Included the user's current runtime UI changes and their contract tests in
  the candidate scope: focus ordering/labels, overdue styling, scrollable
  focus list, project filtering, task completion, and accessibility behavior.

### Deviations and decisions

- The worktree contains unrelated operator data edits in
  `data/projects.json`/`data/tasks.json` and untracked design, video, scratch,
  and lockfile artifacts. They remain excluded from the candidate diff because
  the tracked task fixture contains personal/message content and those files
  are not required by 1C-D.
- The first full-suite run on the dirty checkout hit a data-fixture assertion
  caused by the operator's extra active projects. A clean HEAD-based worktree
  verification including the approved source, docs, UI, and tests was run to
  separate that local data state from the slice result.
- Existing webhook tests that mocked the generic JSON helper were updated to
  mock the explicit Task helper, preserving the test seam after the call-graph
  cleanup.

## Verification

### Focused checks

| Command | Result |
| --- | --- |
| `python3 -m unittest tests.test_task_runtime_cleanup tests.test_task_repository tests.test_task_deletion tests.test_task_planning_server tests.test_task_delegation tests.test_dashboard_behaviors tests.test_orchestration_service tests.test_hermes_webhook_routes tests.test_hermes_event_refresh -q` | 185 passed |
| `python3 -m unittest tests.test_task_runtime_cleanup tests.test_agent_runtime_architecture tests.test_next_phase_readiness tests.test_data_schema -q` | 71 passed, 1 skipped |
| `node --check public/app.js && python3 -m unittest tests.test_home_operations_ui tests.test_visual_contract -q` | 43 passed |
| `python3 -m unittest tests.test_hermes_webhook_routes tests.test_task_runtime_cleanup tests.test_home_operations_ui tests.test_visual_contract -q` | 64 passed |
| `python3 -m py_compile server.py tests/test_task_runtime_cleanup.py` | Pass |
| `git diff --check` and repository-wide direct-call inventory | Pass; no live generic `tasks.json` Task call sites remain |

### Full suite

Clean HEAD-based worktree with the approved slice patch and new regression test:

`python3 -m unittest discover -s tests -q` → 1,281 tests passed, 4 skipped.

The original dirty checkout's one data-contract failure was caused by
operator-edited project fixtures and is excluded from the public-safe slice.

### Rendered or manual behavior

The included UI changes require browser smoke at desktop/mobile widths and the
existing visual contract checks.

- `scripts/browser_smoke.mjs` against a fresh disposable local server: 46
  checks passed at desktop and mobile widths after the final UI fixes.
- Final disposable-fixture Lighthouse run: performance 66, accessibility 100,
  best practices 100, SEO 100; FCP 2.14s, LCP 7.81s, TBT 25ms. The local
  Lighthouse performance score is environment-sensitive; no repository
  threshold failed, and the browser smoke/functional gates are green.

## Adversarial review

Two independent read-only reviewers were launched after implementation and
verification.

### Initial findings and dispositions

- Reviewer A: the dirty operator fixture contained sensitive/out-of-scope
  data. Disposition: excluded from the candidate file set; clean HEAD-based
  verification rerun and passed.
- Reviewer A: completion sent the full browser task projection, including
  display-only delegation artifacts rejected by task validation. Disposition:
  fixed by sending only completion/planning fields; added
  `test_minimal_completion_preserves_delegation_metadata`.
- Reviewer A: artifact-bearing `ready_for_review` tasks were not consistently
  classified as attention work. Disposition: fixed in `taskArea()` so focus
  cards retain artifact cards and actions.
- Reviewer B: completed tasks could receive overdue styling. Disposition: fixed
  `isTaskOverdue()` to exclude completed tasks.
- Reviewer B: scheduled tasks hid their state label. Disposition: fixed status
  rendering to compose the state with the schedule range.
- Reviewer B: completion controls had indistinguishable accessible names.
  Disposition: added the task title to each completion button's accessible
  label.
- Reviewer B: the review log needed final status and outcome updates.
  Disposition: this log is being updated through the re-review and outcome
  review below.

Both reviewers were sent an independent read-only re-review request after the
fixes. Re-review disposition:

- Reviewer A confirmed the five UI behavior fixes and found no remaining code
  defect. The operator data finding remains excluded from the candidate; the
  final browser smoke was rerun; the completion regression now includes an
  artifact-bearing browser projection assertion.
- Reviewer B confirmed the prior behavioral fixes and found no remaining code
  defect. The stale `artifactAttention` assertion was updated, and this log
  now records final acceptance and outcome status.
- No blocking, high, medium, or unresolved product/safety findings remain in
  the approved candidate scope.
- Reviewer B's independent run against the shared dirty checkout still reports
  the excluded `tests.test_data_contract` failure; the clean HEAD-based run
  with the candidate allowlist passes all 1,284 tests. The remaining low-risk
  coverage note is that the artifact assertion is synthetic rather than a
  private artifact-store projection test; browser smoke and source checks
  cover the rendered path.

## Documentation updates

- Roadmap: `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md` now marks 1C-C complete and
  1C-D in progress.
- Changelog: `CHANGELOG.md` records the 1C-D cleanup and authority boundary.
- Architecture/operator docs: `ARCHITECTURE.md` and `DATA_LAYOUT.md` describe
  the explicit SQLite runtime boundary and remaining JSON compatibility paths.
- Project/session notes: this review log.
- Documentation verification: focused architecture/readiness/data-schema tests
  passed; full clean-suite verification passed.

## Publication gate

- Proposed files: `server.py`, `public/app.js`, `public/index.html`,
  `public/styles.css`, the approved UI/server tests, the new runtime cleanup
  test, the four documentation files, and this review log. Operator data and
  unrelated untracked artifacts are excluded.
- Branch and base: `codex/sqlite-task-cleanup-1c-d` → `main`.
- Commit message: `Complete Pivot 1C-D SQLite Task Runtime Cleanup`.
- PR title: not created; push/PR requires separate approval.
- PR summary: pending final verification and outcome review.
- Unresolved risks: hosted CI is not run before publication.
- User authorization and scope: user approved staging and commit on 2026-08-21;
  push and PR remain unauthorized.
- Commit hash: pending explicit publication approval.
- Ready PR URL: pending.

## Outcome review

- Classification: Ready for publication approval.
- Acceptance criteria summary: AC-1 through AC-6 pass; 1,284 tests passed,
  4 skipped in the clean verification worktree; browser smoke passed 46/46;
  Lighthouse accessibility, best practices, and SEO scored 100.
- Potential bugs or untested paths: hosted CI/release checks remain unrun;
  Lighthouse performance is 66 in the final local run and should be watched
  in hosted quality gates.
- Remaining reviewer dissent: none within the approved candidate scope.
- Compatibility/migration/rollback concerns: supported migration, export,
  downgrade, backup, and recovery paths remain in scope and pass the clean
  suite; no direct Hermes-core writes or destructive data actions were taken.
- User decision: publication commit approved; no next slice authorized.
- Next slice authorized: No.
