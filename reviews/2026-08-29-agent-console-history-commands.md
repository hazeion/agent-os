# Feature Slice Review: Agent Console history depth and command ergonomics

Status: Ready for publication
Slice: `agent-console-history-command-ergonomics`
Date: `2026-08-29`
Review log: `reviews/2026-08-29-agent-console-history-commands.md`

## Slice contract

### Goal

Let a person find, open, rename, archive, and restore durable Conversations,
and use the four approved Mentat slash commands without turning search or the
composer into a generic execution boundary.

### In scope

- Advance the owner-private Console database to schema 16. Rebuild only the
  Conversation table constraint needed to add `manual` to `title_source`,
  preserving every dependent Message, Turn, Run, attachment, and authority row.
- Add exact-revision rename for active or archived Conversations. A manual
  title is trimmed, nonempty, control-free, at most 160 Unicode code points,
  durable across restart, and never replaced by first-Turn title derivation.
- Add title-only Conversation history search over the fixed 1,024-Conversation
  authority. It supports `all`, `active`, and `archived`, returns at most 50
  safe summaries per page, uses Unicode case-folded substring matching, and
  binds its opaque cursor to the normalized query and state filter without
  storing query text in the cursor.
- Add fixed Python Local Bridge and same-origin Node capabilities:
  `GET /api/conversation-history`,
  `POST /api/conversations/{id}/rename`, and
  `GET /api/agent-console/commands`.
- Replace the recent-history disclosure with a compact manager for Search,
  state filter, Open, Rename, Archive, Restore, and paging. Search and filter
  update results only; only explicit Open or result activation selects or
  reopens a Conversation.
- Accept only the complete version-1 project-owned command manifest and one
  fixed Next.js handler registry for `/model`, `/new`, `/steer`, and `/help`.
- Add local keyboard completion for a leading slash: at most four suggestions,
  ArrowUp/ArrowDown movement, Tab completion, Enter completion or exact command
  execution, and Escape dismissal.
- `/new` creates a durable Conversation for the selected Agent. `/model`
  refreshes and focuses the existing safe configuration, and an optional exact
  model name only stages the selector for the existing review/confirm flow.
  `/steer` reuses the exact active-Run capability. `/help` shows the four
  manifest entries.
- Unknown, malformed, unavailable, or failed slash commands preserve the full
  draft and create no Message, Turn, Run, Conversation, or configuration
  mutation beyond the command's exact fixed behavior.

### Out of scope

- Message, artifact, attachment, note, Task, or Project content search;
  snippets; FTS; new search dependencies; or persisted search queries.
- Conversation delete, bulk operations, saved searches, queue reordering, new
  slash commands, CLI discovery, shell execution, runtime-method passthrough,
  or a generic Node/Python proxy.
- Direct provider/model mutation outside the Slice 5 inventory,
  preview/confirmation, verification, rollback, and active-Run boundary.
- Archive stopping work, closing tabs, deleting evidence, or changing Agent
  ownership.
- Task, Project, delegation, calendar, note, Context Pack, or scheduler changes.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Schema 15 upgrades atomically to schema 16, preserves the full graph, accepts `manual`, and rejects drift before rewrite. | Migration, fingerprint, foreign-key, backup/restore, and rollback tests. | Pass |
| AC-2 | Exact rename works for active and archived Conversations, survives restart, and later Turn edits cannot replace a manual title. | Repository, Run admission, bridge, route, and persistence tests. | Pass |
| AC-3 | Title-only history returns deterministic private 50-row pages across 1,024 records, with query/filter-bound cursors and no Message or runtime data. | Repository stress, cursor mismatch, projection, and hostile-query tests. | Pass |
| AC-4 | Search/filter typing never changes the selected Conversation; Open, Close tab, Archive, Restore, and Rename remain distinct and Delete is absent. | React stale-response, focus, tab, lifecycle, and no-delete tests. | Pass |
| AC-5 | Python, private bridge, Node routes, and public clients accept only the frozen history, rename, and manifest shapes. | Same-origin, exact query/body, bounded response, private-field, and error-mapping tests. | Pass |
| AC-6 | The browser accepts only the exact complete four-command manifest and fixed handler registry; no CLI or arbitrary handler can execute. | Manifest parser, duplicate/extra/partial/handler/safety rejection tests. | Pass |
| AC-7 | `/new`, `/model`, `/steer`, and `/help` perform only their fixed behavior, while every command error preserves its full draft and never falls back to ordinary Send. | Composer parser, handler-spy, mutation-count, stale-tab, and failure tests. | Pass |
| AC-8 | History management and completion are keyboard and screen-reader usable, mobile-safe, reduced-motion-safe, high-contrast-safe, and create no page overflow. | React semantics plus production desktop/mobile browser use. | Pass |
| AC-9 | The 1,024-record history fixture paints the current result page with a seven-sample median below 250 ms; completion typing performs no network mutation. | Production performance gate with recorded medians and request deltas. | Pass |
| AC-10 | Full Python/web/build/package/CI gates and two independent adversarial re-reviews pass. | Full local and GitHub evidence. | Local pass; PR CI pending |

### Constraints and recovery

- Safety: Python owns search, rename, SQLite, command-manifest source, and all
  private data. Node exposes only fixed bounded capabilities. Search is
  navigation-only and slash commands never grant authority beyond fixed
  handlers.
- Compatibility: schema 16 is forward-only. Released schemas through 15 remain
  valid backup/restore inputs. The Python compatibility Console keeps the
  version-1 manifest and existing fixed legacy handlers.
- Rendered behavior: the transcript and composer remain dominant. History is a
  compact disclosure/manager, completion stays attached to the composer, and
  mobile actions meet the 44 px target without horizontal overflow.
- Rollback or recovery: restore a validated pre-migration format-4 backup or
  use the existing compatible sibling workflow. Never downgrade schema 16 in
  place. Rename and archive conflicts refresh canonical state and do not retry.
- Documentation targets: `AGENTS.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, this
  review log, and closeout updates to the implementation roadmap and Wayfinder.
- Version-control strategy: isolated branch `codex/agent-console-slice-9` from
  Slice 8 closeout merge `c70335b`, ready PR to `main`, normal merge after every
  required check.

### Frozen capability shapes

- History query: exact `state=all|active|archived`, optional canonical nonempty
  `q`, and optional opaque `cursor`. No other query key is accepted.
- History result: service envelope plus `conversations`, exact `count`, and
  `next_cursor`. It contains no Agents, Messages, Runs, snippets, query echo, or
  private fields.
- Rename body: exactly `expected_revision` and `title`. Result is the service
  envelope plus `action=rename` and one safe Conversation summary.
- Manifest result: the exact version-1 `mentat` manifest plus the service
  envelope. Next.js rejects missing, partial, duplicated, reordered, extra, or
  unknown command definitions and handlers.

### Scope discussion and approval

- Recommendation and rationale: title-only search and exact rename are the
  smallest useful history boundary. Transcript search would require indexing,
  snippet privacy, content retention, and artifact handling outside this slice.
- Alternatives considered: browser-only filtering was rejected because it
  cannot search all 1,024 durable Conversations; FTS was rejected as unnecessary
  complexity; a generic command parser was rejected because it widens execution
  authority; changing the legacy manifest was rejected in favor of consuming
  its existing fixed handler identifiers in Next.js.
- User decisions: the user granted standing approval for every remaining slice,
  scope, integration, commit, push, PR, and merge, and explicitly approved
  parallel agents. That removes repeated approval pauses but not review,
  evidence, ready-PR, CI, or merge gates.
- Approved at: 2026-08-28 standing authorization; Slice 9 scope recorded on
  issue #141 on 2026-08-29.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Schema 15 permits only `default` and `first_prompt`. | Exact schema-15 fixture migration, drift, FK, backup/restore, and active-transaction tests. | Migration preserves authority and fails closed. | Injected races approximate platform timing. |
| AC-2 | No rename operation or `manual` source exists. | Rename CAS, archived, persistence, and later first-Turn/edit tests. | Manual intent stays authoritative. | Timestamps use the repository clock. |
| AC-3 | List supports only unfiltered 50-row paging. | 1,024-row query/filter/cursor stress and private projection tests. | Complete bounded title search. | Search intentionally excludes transcript text. |
| AC-4 | Recent history is an unfiltered list. | React navigation-only, stale-response, lifecycle, rename-focus, and no-delete tests. | History actions remain distinct and safe. | Screen readers are approximated by semantic DOM tests. |
| AC-5 | No named history, rename, or Next manifest routes exist. | Bridge/BFF/public exact-shape and hostile request tests. | Browser input cannot widen the bridge. | Real loopback timing is covered later in browser use. |
| AC-6 | Manifest exists only in the compatibility UI. | Strict parser tests against every near-miss. | Only the reviewed four commands can reach handlers. | Does not prove UI focus behavior. |
| AC-7 | Next recognizes only `/steer`; other slash text becomes an ordinary Turn. | Parser, fixed-handler, draft, mutation-spy, tab-race, and model workflow tests. | No fallback Send or cross-tab action. | Runtime effects remain deterministic fakes at this layer. |
| AC-8 | No history manager or completion menu exists. | Keyboard/focus/live-region/mobile/high-contrast/reduced-motion tests and browser use. | Usable rendered behavior. | Browser automation is not a full assistive-technology audit. |
| AC-9 | Performance fixture has no 1,024-row history path. | Seven production samples and network counters. | Bounded interaction latency and local completion. | Reference-machine evidence, not every device. |
| AC-10 | No Slice 9 implementation or review exists. | Full suites, packaging, two independent reviewers, and PR matrix. | Integration and review closure. | Cannot prove unknown future runtimes. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `git status --short` and `git diff --stat` | isolated Slice 9 worktree | Pass | Clean at `c70335b`. |
| Source and nearest-test inspection | macOS, Python 3.13, Node 24 | Gap confirmed | No rename/history/Next manifest path; unknown slash text falls through to a Turn. |
| `python -m unittest tests.test_command_manifest tests.test_conversation_repository tests.test_schema12_forward_migration -v` | macOS, Python 3.13 | Pass | 29 existing tests pass; they document the pre-Slice-9 boundary. |
| Focused four-file Node baseline | macOS, Node 24 | Pass | 71 existing tests pass after locked dependency install. |

### Test discussion and approval

- User questions and decisions: standing approval covers this mapped strategy
  and the three parallel implementation packages.
- Accepted coverage gaps: Message-body search and real assistive-technology
  software remain outside this slice; semantic tests plus keyboard/browser use
  are the accepted evidence.
- Approved at: 2026-08-29 under standing slice/test authorization.

## Implementation record

### Changes

- Added schema-16 manual-title authority, exact schema-15 migration, title-only
  history, query/filter-bound cursors, exact rename, safe projections, and fixed
  Local Bridge handlers.
- Added strict Node/private/public clients and same-origin routes for history,
  rename, and the complete command manifest.
- Added the compact history manager, fixed Mentat-facing command help, local
  completion, safe `/new` and `/model`, existing exact `/steer`, and draft-safe
  failure handling.
- Added the 1,024-Conversation performance fixture and cross-layer schema,
  repository, bridge, route, interaction, accessibility, and hostile-shape
  tests.

### Deviations and decisions

- Standing approval is the process exception. All technical, verification,
  adversarial-review, ready-PR, CI, and merge gates remain intact.
- The compatibility manifest keeps its existing handler IDs and descriptions.
  The Next.js fixed registry supplies canonical Mentat-facing copy so `/new`
  says Conversation rather than exposing the legacy Hermes-session term.
- Node revalidates history state and ordering. Python alone validates Unicode
  case-folded query matches because JavaScript lacks the same full case-folding
  operation and must not reject a valid `Straße`/`STRASSE` result.

## Verification

### Focused checks

- Backend implementation packages: 197 focused tests plus 45 private-console
  compatibility tests passed. The final integrated history/schema/manifest/
  loopback set passed 64 tests.
- Node contract package passed 35 focused tests. The final integrated
  history/composer/Home set passed 64 tests.
- `npm --prefix web run check` passed lint, typecheck, and 203 tests after the
  first-round adversarial fixes.
- Python compilation and `git diff --check` passed.

### Full suite

- `python -m unittest discover -s tests -v` passed all 1,775 tests with five
  expected native-platform skips on the final reviewed diff. A sandboxed
  attempt could not bind its temporary loopback servers; the required
  host-permission rerun passed cleanly, including the Codex timeout contract.
- The production webpack build and standalone preparation passed. The final
  default Turbopack production build also passed when run with its required
  local worker-socket permission.
- `uv build` produced the source distribution and wheel, and
  `python scripts/verify_python_artifacts.py dist` verified both.
- The seven-sample production gate passed. Medians: history search paint 3.6
  ms on the pre-review run. The final run passed at history 3.4 ms,
  optimistic paint 7.3 ms, accepted dispatch 97.6 ms, stream paint 5.6 ms,
  and loaded tab 7.9 ms. Every completion-mutation and ordinary typing-network
  delta was zero.

### Rendered or manual behavior

- Production standalone acceptance used a disposable schema-16 root. Keyboard
  completion listed the exact four commands and executed `/new`; the normal
  button created another Conversation. Rename updated the selected tab, search
  did not change selection, explicit Open did, and Archive/Restore plus state
  filters remained separate. `/help` used canonical Mentat copy, `/model`
  refreshed the safe selector, failed `/steer` and an unknown command preserved
  their drafts, and reload retained the manual title and archived state.
- At 390×844, history inputs, state selector, actions, command options, and tab
  close measured 44 px high. Desktop and mobile page overflow stayed zero,
  high contrast held, and browser warning/error logs were empty.
- The final post-review production browser run created Conversations through
  keyboard `/new` and the button, proved duplicate-title actions have distinct
  accessible names, renamed durably, kept search navigation-only until Open,
  archived and restored, displayed the fixed four-command help, preserved a
  failed `/steer` draft with an explicit explanation, and retained manual title
  and archive state across reload. At 390×844 the history disclosure, help
  close, search, filter, and tab close measured exactly 44 px high and document
  overflow was zero. Its disposable data root was removed afterward.
- `uv build` produced the final wheel and source distribution, and
  `python scripts/verify_python_artifacts.py dist` verified both artifacts.

## Adversarial review

- Two independent read-only reviewers completed round one. The security
  reviewer found focus loss after a filtered archive/rename removes the current
  row and UTF-16 `maxLength` rejecting valid 160-code-point astral titles. The
  product reviewer independently found both and four additional blockers:
  keyboard-inaccessible collapsed history, silent or premature `/steer`,
  repeated generic result-action names, and sub-44-pixel mobile history/help
  controls.
- Cross-review reconciliation retained all six findings. The security reviewer
  explicitly peer-reviewed the product-only findings and agreed they were
  release-blocking rather than duplicates or scope expansion.
- Fixes make collapsed history keyboard reachable, restore focus to the search
  or disclosure when a mutated row disappears, qualify action names by title,
  enforce the title limit by Unicode code point, raise the mobile disclosure
  and help-close controls to 44 px, and require a verified active Run before
  `/steer` while preserving its draft with an explicit failure notice.
- Focused regression coverage passed 65 tests; the complete web check passed
  lint, typecheck, and 203 tests.
- Round two found two residual blockers: the conflict branch of filtered stale
  rename still lacked fallback focus, and title-qualified action labels still
  collided when two Conversations shared the same title. The fixes reuse the
  editor/search/disclosure fallback after conflict and add a stable visible-row
  position to each action name. Regressions exercise a canonical title leaving
  the active query and two identical default titles.
- Both independent reviewers completed a fresh full-diff round three and
  reported clean results with no remaining release blocker.

## Documentation updates

- `AGENTS.md`, `ARCHITECTURE.md`, and `CHANGELOG.md` record schema 16,
  navigation-only history, exact rename, fixed commands, failure behavior, and
  rollback boundaries. The documentation contract checks are included in the
  complete Python suite and passed in the earlier final-projection run.

## Publication gate

- Branch and base: `codex/agent-console-slice-9` to `main`.
- User authorization and scope: standing approval recorded; ready PR only.
- Implementation commit: `fec5268`.
- Ready PR URL: https://github.com/hazeion/agent-os/pull/158

## Outcome review

- Classification: Implemented and locally verified; publication and PR CI
  pending.
- Acceptance criteria summary: AC-1 through AC-9 pass locally. AC-10 has clean
  local full-suite, build, package, browser, performance, and dual-review
  evidence and awaits only PR CI.
- Potential bugs or untested paths: no release blocker found; a real assistive
  technology audit remains outside the approved semantic/browser scope.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: schema 16 is forward-only.
- User decision: standing acceptance/continuation authorization recorded,
  subject to all-green and clean-review gates.
- Next slice authorized: Yes, but implementation will not begin until Slice 9
  itself is merged and closed out.
