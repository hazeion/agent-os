# Feature Slice Review: Agent Console project and planning context

Status: Complete
Slice: `agent-console-project-planning-context`
Date: `2026-08-30`
Review log: `reviews/2026-08-30-agent-console-project-planning-context.md`

## Slice contract

### Goal

Connect durable Conversations to safe canonical Project and Task references,
then make planning attention and draft-only suggestions useful from Home without
turning the Console into another Task workspace or delegation scheduler.

### In scope

- Advance the owner-private Console database to schema 17 with a separate
  Conversation planning-association table. It stores one canonical Project ID
  and optional Task ID beneath a Conversation, has no Task foreign key, and
  preserves stale references until an exact rebind or clear.
- Add exact-revision planning-context read and mutation capabilities. Project
  and Task selector changes are local staging until explicit Apply. Clear is
  explicit. Neither operation changes a Task, Run, Turn, runtime, delegation,
  attachment, note, calendar link, or Context Pack.
- Validate Project identity from bounded project-owned `projects.json` under
  the durable root lock. Resolve the Task from canonical SQLite authority in
  the same SQLite snapshot and require its current Project name to map uniquely
  to the selected Project name or aliases.
- Add fixed bounded planning-overview and project-scoped paginated Task
  capabilities. Public fields are limited to canonical IDs, bounded labels,
  status, priority, due date, selected safe planning flags, fixed attention
  reasons, and timestamps.
- Add one compact Planning context disclosure with staged Project and Task
  selectors, Apply/Clear/Cancel, current stale or ready state, and at most three
  fixed planning suggestion buttons. Suggestions fill and focus only an empty
  draft.
- Add a bounded Planning attention section below Agent activity. It shows at
  most eight deterministic overdue, due-today, review, needs-attention,
  planned-today, or due-soon Tasks and uses navigation-only links to the
  dedicated Tasks workspace.
- Add exact safe `/tasks?project=<project-id>&task=<task-id>` focus, highlight,
  and announcement after the existing Task projection loads. Invalid, missing,
  mismatched, or unavailable targets do not hide the full Task list and perform
  no mutation.
- Complete the dedicated Next.js Projects & Tasks creation surface. It uses a
  selected-Project list/detail layout, a Name-only Project form, and a Task form
  containing only Title, optional Agent, and optional Due date. Project is
  implicit from the current selection; Task status and priority use server
  defaults.
- Add fixed Project-create and selected-Project Task-create capabilities. Task
  assignment stores only a validated canonical Mentat Agent reference and does
  not start a Run or invoke delegation.

### Out of scope

- Project/Task editing, deletion, completion, review acceptance, calendar
  mutation, note mutation, Context Pack mutation, or delegation from Home or
  the dedicated workspace.
- Copying descriptions, notes, reminders, dependencies, subtasks, delegation
  state, attachments, artifacts, or arbitrary planning metadata into a
  Conversation or runtime prompt.
- Automatic prompt injection, implicit Send, automatic Task association,
  Pending-turn scheduling, cross-Conversation routing, or Run `task_id`
  assignment.
- Conversation deletion, Task search redesign, a second planning dashboard,
  generic bridge/proxy behavior, or any new slash command.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Exact schema 16 upgrades atomically to schema 17, preserves the complete Console graph, and stores syntactically valid non-owning references. | Migration, drift, transaction, graph, fingerprint, backup/restore, and compatible-export tests. | Pass |
| AC-2 | Apply and Clear are exact Conversation-revision mutations and validate one coherent Project/Task snapshot without changing other authority. | Repository/service race, CAS, guard, stale, and mutation-spy tests. | Pass |
| AC-3 | Missing, moved, deleted, ambiguous, or malformed Project/Task targets project bounded stale/unavailable state and remain safely clearable. | Cross-store, alias, corruption, deletion, restore, and stale-reference tests. | Pass |
| AC-4 | Planning overview and Task pages are bounded, deterministic, canonical-ID based, and omit every private or unrelated field. | Python/bridge/Node/client projection, hostile-field, cursor, cap, and response-size tests. | Pass |
| AC-5 | Planning attention uses fixed date/review rules, excludes completed stale-due work, caps visible rows, and never blocks Agent activity. | Fixed-clock classification, sorting, truncation, and failure-isolation tests. | Pass |
| AC-6 | Project/Task selection is staged until Apply; Clear and stale conflicts preserve honest canonical and staged state per Conversation. | React network-spy, stale-response, reload, tab-isolation, focus, and live-region tests. | Pass |
| AC-7 | Planning suggestions change only an empty draft and explicit attention actions navigate only to the exact Tasks card. | Draft, non-overwrite, zero-mutation, navigation, invalid-query, focus, and announcement tests. | Pass |
| AC-8 | Prompt/transcript remain dominant with keyboard, mobile, high-contrast, reduced-motion, zoom, and no-overflow behavior intact. | Semantic React tests and production desktop/mobile browser use. | Pass |
| AC-9 | Projects & Tasks provides simple accessible creation: Name-only Project; Title, Agent, and Due Task; Project implicit; short actions; canonical persistence with no execution side effect. | Backend/Node exact-mutation tests plus React and production browser creation workflows. | Pass |
| AC-10 | Worst-case planning fixtures meet the approved paint/filter budget and create no picker, suggestion, creation-form, or ordinary typing mutation traffic before explicit submit. | Seven-sample production performance gate with request deltas. | Pass |
| AC-11 | Full Python/web/build/package/CI gates and two independent adversarial re-reviews pass. | Full local and GitHub evidence. | Pass |

### Constraints and recovery

- Safety: Project JSON and Task SQLite remain their own authorities. The
  association is a revalidated reference only. No browser field becomes a
  storage path, runtime reference, Task mutation, or delegation request.
- Compatibility: schema 17 is forward-only. Released schema 16 remains a valid
  format-4 restore input and migrates with no associations. Schema-5 compatible
  export omits Conversation authority as before.
- Rendered behavior: planning stays in a compact disclosure and a capped
  right-rail section. The transcript and composer remain the dominant surface.
- Rollback or recovery: restore a validated pre-schema-17 format-4 backup.
  Never downgrade schema 17 in place. Stale references are explicitly cleared
  or rebound; they are not followed or silently rewritten.
- Documentation targets: `AGENTS.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, this
  review log, and closeout updates to the roadmap and Wayfinder.
- Version-control strategy: isolated branch `codex/agent-console-slice-10`
  from Slice 9 closeout merge `475d308`, ready PR to `main`, normal merge after
  every required check.

### Frozen capability shapes

- Overview read: query-free `GET`; returns service envelope, local ISO date,
  at most 256 exact Project summaries, at most 50 ordered attention summaries,
  total attention count, and truncation flag.
- Project Task read: exact canonical `project_id`, optional opaque cursor, at
  most 50 safe Tasks per page, and a project-bound cursor. No title/body search
  or browser-selected projection fields.
- Task locator read: exactly one canonical `task_id`; returns only its verified
  safe Project and Task projections so task-only navigation never scans every
  Project or depends on the capped attention list.
- Context read: exact Conversation path; returns its revision, stored nullable
  association, fixed `empty|ready|project_unavailable|task_unavailable|project_mismatch`
  state, and only verified safe Project/Task summaries.
- Context mutation: body exactly `expected_revision`, `project_id`, and
  `task_id`; both IDs null clears, Task without Project is invalid. Result is
  the exact updated Conversation summary plus the re-read context projection.
- Project create: body exactly `name`; returns one safe canonical Project and
  defaults every nonessential field server-side.
- Selected-Project Task create: exact Project path and body exactly `title`,
  nullable `assigned_agent_id`, and nullable `due_date`; returns the exact safe
  Project and Task. Status defaults to `todo`, priority to `medium`, and no Run
  or delegation is created.

### Scope discussion and approval

- Recommendation and rationale: explicit metadata association plus draft-only
  prompts is the smallest complete way to make planning useful without copying
  private Task content or creating hidden execution authority.
- Alternatives rejected: a Task foreign key would silently clear references
  during the repository's replace cycle; automatic Task-to-prompt injection
  would hide input authority; Home Task mutations or delegation would duplicate
  dedicated workflows and widen the Kanban boundary; loading all Tasks at Home
  startup would crowd the response and hurt first paint; advanced Project/Task
  forms would duplicate the detailed planner and obscure quick creation.
- Interaction references: Salesforce's official activity guidance keeps a Task
  related to its current record and makes assignment explicit. Todoist's
  official Quick Add starts inside the current Project and leads with the Task
  name and date. Mentat adopts only those behavioral principles, not source,
  dependencies, permissions, or external domain models.
- User decisions: standing approval covers all remaining slice scopes, tests,
  commits, pushes, PRs, and merges, and explicitly authorizes parallel agents.
- Approved at: 2026-08-29 standing authorization; exact Slice 10 scope recorded
  on issue #142 on 2026-08-30.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Schema 16 has no planning association. | Exact schema-16 fixture migration plus recovery and export tests. | Forward migration preserves authority and rollback inputs. | Filesystem races are injected. |
| AC-2 | No exact association mutation exists. | CAS, active/queue guard, cross-store snapshot, and mutation spies. | One explicit metadata-only write. | SQLite/JSON cannot share one transaction; root lock closes the Project race. |
| AC-3 | Stale reference state is undefined. | Missing/moved/ambiguous/malformed/stale round trips. | Stale data cannot become trusted content. | Operator must explicitly repair stale links. |
| AC-4 | Existing Task route lacks canonical Project IDs. | Exact projection and hostile-response tests across every layer. | Browser receives only the reviewed planning vocabulary. | Full Task workspace remains a separate surface. |
| AC-5 | Home has no planning-attention model. | Fixed-date sort/cap/failure tests. | Due and review state is honest and bounded. | Date-only semantics use Mentat's local date. |
| AC-6 | Home has no planning controls. | React staging, Apply/Clear, stale, reload, tab, and focus tests. | UI does not mutate before explicit action or cross tabs. | Assistive technology is approximated by semantic DOM tests. |
| AC-7 | No planning prompts or Task deep link exists. | Draft/network/navigation/focus tests. | Suggestions and review links remain presentation-only. | Suggestions intentionally omit private Task detail. |
| AC-8 | Planning layout does not exist. | Responsive contract tests and production browser use. | Planning does not displace the Console. | Browser automation is not a full AT audit. |
| AC-9 | Next Tasks route is read-only. | Exact Project/Task create contracts, defaults, assignment, error/focus, and browser workflow tests. | Simple creation persists canonically without execution. | Advanced planning remains in existing detailed workflows. |
| AC-10 | Performance gate has no planning fixture. | 256-Project, 50-attention, paged 2,048-Task production fixture. | Bounded paint/filter latency and zero hidden traffic. | Reference-machine evidence only. |
| AC-11 | No Slice 10 integration exists. | Full suites, packaging, reviewers, and PR matrix. | Integration closure. | Cannot prove unknown future runtimes. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `git status --short --branch` and `git diff --stat` | isolated Slice 10 worktree | Pass | Clean code baseline at `475d308`; only this review log was then added. |
| Required contract, source, and nearest-test inspection | macOS, Python 3.13, Node 24 | Gap confirmed | No schema association, planning capability, Home planning controls, attention projection, or Task deep-link behavior exists. |
| `python -m unittest tests.test_schema16_forward_migration tests.test_conversation_repository tests.test_mentat_local_bridge -v` | host loopback permissions | Pass | 58 baseline tests. The initial sandboxed run passed non-network tests but could not bind 40 temporary bridge servers. |
| Focused five-file Node baseline | macOS, Node 24 | Pass | 80 existing Conversation, Task, route, Home, and shell tests. |
| `npm --prefix web ci --ignore-scripts` | macOS, Node 24 | Pass | Locked install; 515 packages audited with zero vulnerabilities. |

### Test discussion and approval

- Standing user authorization covers this mapped strategy and parallel package
  implementation.
- Accepted coverage gaps: no real assistive-technology audit and no new
  destructive, delegation, or Task-mutation workflow in this slice.
- Approved at: 2026-08-30 under standing slice/test authorization.

## Implementation record

### Changes

- Added schema-17 non-owning Conversation planning associations, exact guarded
  Apply/Clear, stale target projection, bounded planning overview and
  Project-bound Task paging, plus minimal canonical Project/Task creates.
- Added fixed private bridge and same-origin Node capabilities with strict
  safe projections, exact bodies, cursors, deadlines, and failure mapping.
- Added compact Home planning context, local-only suggestions, capped planning
  attention, exact Projects & Tasks navigation, and the interactive minimal
  creation workspace.
- Changed production cutover so Agents and Runs retain script-light static
  shells while the now-interactive Projects & Tasks route remains hydrated.
  The route renders dynamically so Next can attach the proxy's per-request CSP
  nonce on direct loads.
- Moved exact Task-link focus to a post-render handoff. The UI now waits until
  the canonical Task row is committed before focusing, highlighting, and
  announcing it.

### Deviations and decisions

- Standing approval removes repeated publication pauses but not review,
  evidence, ready-PR, CI, or merge gates.
- User direction expanded the approved slice from read/association context to
  minimal Project and Task creation. The issue and this review record were
  updated before those capabilities were implemented.
- Attention links carry both canonical Project and Task IDs so the dedicated
  workspace can focus an exact Task without a broad cross-Project search.

## Verification

### Focused checks

- Backend package: 10 new planning/schema/bridge tests, 185 affected
  repository/schema tests, 44 authenticated bridge tests, 81 private-console
  and backup tests, and 33 packaging tests passed. Compilation, tracked-secret
  scan, and diff checks passed.
- Node/public package: 29 focused planning and Conversation/Task contract tests
  passed with lint and typecheck.
- React package: 66 focused Home, Projects & Tasks, and shell tests passed.
- Final integrated `npm --prefix web run check` passed lint, typecheck, and 227
  tests after the adversarial and browser-use fixes. The schema/planning/node-foundation
  integration set passed 13 tests before the final exact Task-locator additions;
  the locator-focused Python service/bridge set passed 10 tests.
- The default Turbopack production build and standalone preparation passed
  after retiring the obsolete static `/tasks` rewrite. After the final
  browser fixes, Turbopack's CSS worker could not bind its private local port
  under the execution sandbox; the clean final webpack production build,
  TypeScript pass, route manifest, and standalone preparation passed. The
  resulting manifest marks both Home and Projects & Tasks dynamic.

### Full suite

- The final full Python suite passed 1,789 tests with five platform skips in
  677.051 seconds. GitHub passed all 52 checks on the final head. `uv build` plus
  artifact verification passed for `mentat_local-0.1.0b1-py3-none-any.whl`
  and `mentat_local-0.1.0b1.tar.gz`; the tracked-file secret scan also passed.
- The final seven-sample production performance gate passed: planning Task
  paint 2.5 ms median, history 3.6 ms, optimistic paint 10.6 ms, accepted
  dispatch 111.1 ms, stream paint 5.0 ms, and loaded tab 10.8 ms. Planning selection,
  suggestion, command completion, and ordinary typing mutation/network deltas
  were all zero.
- The final uncontended Lighthouse gate passed three desktop and three mobile
  runs. Median performance was 100 desktop and 96 mobile; accessibility, best
  practices, and SEO were 100 in every run.
- The first GitHub run found three integration-test defects rather than product
  failures: one hostile-field fixture used a secret-scanner keyword, the
  production smoke still classified `/tasks` as a static shell and expected
  its old title, and two planning tests relied on a machine-local Agent. The
  fixture now uses a neutral unexpected field, the smoke treats Home and
  Projects & Tasks as hydrated routes with their exact current labels, and the
  tests create their own canonical Agent. Focused tests, the tracked-file scan,
  and the complete production browser smoke pass after the fixes.

### Rendered or manual behavior

Production browser acceptance passed on a disposable owner-private data root.
It covered Conversation creation, staged planning selection, explicit Apply,
reload persistence, draft-only suggestions with no Run, Clear, tab close,
Project creation, selected-Project Task creation, assignment persistence,
due-date persistence and rendering, direct `/tasks` loading, exact Project plus
Task and task-only links, 390 by 844 responsive layout, 44-pixel mobile action
targets, zero horizontal overflow, high contrast, and browser console errors.

The first browser round found two defects before publication. Static `/tasks`
HTML could not hydrate because its inline Flight data lacked the proxy's
per-request nonce, and the zero-delay Task-focus callback could beat React's
row commit. Dynamic rendering and a post-render focus handoff fixed both. Fresh
direct loads and both link forms then passed with no console errors.

Lighthouse then found that the separate close button was an invalid child of
the ARIA tab list. Each Conversation now uses one `role="tab"` button with a
visible close hit area inside it. Clicking the `×` closes without selecting,
and Delete closes the focused tab. Pointer and keyboard browser checks passed,
the shortcut is included in the accessible name, and Lighthouse accessibility
rose from 96 to 100. Loading and pagination controls now sit outside the
tablist; the empty strip omits tablist role, orientation, and accessible name.

## Adversarial review

- Two independent read-only reviewers completed five full-diff rounds.
- Product round one found eight blockers: split-revision Apply, a fragile
  post-commit GET, archived Clear exclusion, dishonest stale labels, tab-shared
  mutation state, ambiguous Agent inventory failure, colliding form action
  names, and undersized More/View-all targets. All were fixed with direct
  regressions.
- Security round one found three blockers: create results were not bound to
  requested values, schema SQL accepted application-invalid leading ID
  characters, and Task deep links were incomplete. Exact result checks, SQL
  constraints, and navigation tests fixed them.
- Round two found exact planning mutation revisions were not constrained to
  one increment, Projects waited on optional Agent inventory, Task forms could
  cross Projects, and the Tasks workspace consumed all pages before first
  paint. Exact revision checks, independent reads, Project-bound form state,
  progressive paging, and stale-completion guards fixed them.
- Later rounds exposed Task-only links outside the attention cap and a locator
  versus overview/manual-selection race. One exact global Task locator plus
  deterministic initialization and manual-selection generation guards fixed
  both completion orders.
- Both reviewers rechecked the complete diff after the browser and Lighthouse
  fixes. Their final security and product reviews are clean with no remaining
  P0-P2 blocker.

## Documentation updates

`AGENTS.md`, `ARCHITECTURE.md`, `MENTAT_WEB_DESIGN.md`, and `CHANGELOG.md`
record schema 17, non-owning planning context, safe projections, metadata-only
suggestions/attention, minimal creation, and the hydrated Projects & Tasks
cutover.

## Publication gate

- Branch and base: `codex/agent-console-slice-10` to `main` at `475d308`.
- User authorization and scope: standing approval recorded; ready PR only.
- Implementation commit: `fe8db57`; CI-fix commit: `c4c8155`; merge commit:
  `bc1efe57`.
- Ready PR URL: https://github.com/hazeion/agent-os/pull/160

## Outcome review

- Classification: Complete and merged.
- Acceptance criteria summary: AC-1 through AC-11 pass.
- Potential bugs or untested paths: no known P0-P2 issue; a real assistive-
  technology audit remains outside the approved slice.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: schema 17 is forward-only.
- User decision: standing acceptance/continuation authorization recorded,
  subject to all-green and clean-review gates.
- Next slice authorized: none currently listed after Slice 10; final Wayfinder
  audit follows merge.
