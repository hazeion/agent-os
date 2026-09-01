# PT-1B review log — planning model and exact mutations

Issue: [#175](https://github.com/hazeion/agent-os/issues/175)
Wayfinder map: [#165](https://github.com/hazeion/agent-os/issues/165)
Branch: `codex/pt-1b-planning-model`

## Approved scope

- Establish the single visible workflow-stage vocabulary: Inbox, Planned, In
  progress, Waiting, Review, and Done. Blocked remains derived from unmet
  prerequisites; Someday remains a deferred-planning flag rather than a stage.
- Add exact, monotonic Project and Task revisions to public-safe planning
  projections and require their matching revision for every named mutation.
- Add Project rename and archive/restore, named Task move, detailed Task edit,
  Today ordering, recurrence inheritance, checklist edit, canonical Agent
  assignment, and full-graph dependency validation across Projects.
- Expose only fixed Python bridge and same-origin mutation capabilities with
  bounded, public-safe projections. The browser cannot select storage paths,
  runtime bindings, credentials, or arbitrary operations.
- Preserve one SQLite authority: stable Project IDs remain immutable; a named,
  exact-revision Task move may intentionally replace its Project membership.

## Explicit exclusions

- No Task dispatch, execution, Agent run lifecycle changes, delegation UI,
  visual dependency graph, cascade deletion, or new planning workbench UI.
- No Project hard deletion or implicit Task moves.

## Verification strategy

Focused coverage must demonstrate migration, backup/restore and compatible
export compatibility; exact revision conflicts; archive and Task-move guards;
derived blocked state; cross-Project cycle rejection; recurrence inheritance
and reset rules; checklist and Agent-assignment validation; safe bridge
projections; stale source/race and forward-version refusal. The final review
uses two independent defect-first, read-only passes under `review-agent`.

## Execution evidence

- Python focused suite passed: planning-model, Project repository, Conversation
  planning, local bridge, and Task-planning server coverage (72 tests).
- Web planning contract and UI suites passed (24 tests), including named
  mutation routes, exact bodies, same-origin rejection, and hostile projection
  handling. `npm --prefix web run check` lint/type-check pass and the production
  Next build pass.
- A broad local Python discovery run hit one isolated backup/restore failure;
  its immediate standalone rerun passed. It is retained as a local runner
  isolation observation, not attributed to this slice. The GitHub platform
  matrix remains the merge gate.

## Review record

- Reviewer 1 found that an ordinary edit of a legacy `planning_state: someday`
  Task erased the Someday meaning. The implementation now materializes its
  deferred flag before replacing the legacy state; a regression test passes.
- Reviewer 2 found the detailed Task-edit body was limited to 512 bytes by the
  private bridge while the same-origin route allowed 64 KiB. The named bridge
  capability now has the matching 64 KiB bound; a 4 KiB edit regression test
  passes.
- The final independent recheck found empty Task edits incremented a Task
  revision. Both boundaries now reject an empty `changes` object and the normal
  same-origin route plus server regression tests pass.
- All reviewer findings are fixed. The focused Python suite now passes 74
  tests; the web planning suites pass 25 tests, with type checking and the
  production build also passing.

## Browser acceptance

- A fresh local preview was exercised in the browser before publication:
  Home → Projects & Tasks navigation, Project creation and selection, Task
  creation, success announcements, and navigation away and back all worked.
  The created Task remained visible in its selected Project after return.
- PT-1B intentionally exposes the detailed model through named safe routes;
  its full interactive workbench controls are deferred to PT-2A. This check
  verifies that the current user-facing planning workflow remains sound.
- The first GitHub packaging job found that `project_repository` was omitted
  from the installed Python module list. It is now packaged, a newly built
  wheel imports it from an isolated virtual environment, and the focused
  Python suite passes 74 tests while the web planning suites pass 25 tests.
- The repeat pre-push browser check navigated Home and Projects & Tasks and
  opened and cancelled both Project and Task creation forms successfully.
