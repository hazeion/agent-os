# Feature Slice Review: Agent Console Conversation foundation and visual composition

Status: Partially successful (publication approval pending)
Slice: `agent-console-conversation-foundation`
Date: `2026-08-25` approval; `2026-08-26` implementation/review update
Review log: `reviews/2026-08-25-agent-console-conversation-foundation.md`

## Slice contract

### Goal

Deliver the first production Agent Console foundation: durable Conversation
and Conversation-message authority, a canonical browser-safe Direct Agent, and
the approved prompt-first three-column Next.js Home. The composer is visible but
dispatch remains explicitly unavailable until Slice 2.

### In scope

- Add schema-10 Conversation and Message authority with the ADR-required
  forward-compatible Turn and Conversation-Run schema foundation, migration,
  semantic validation, and private backup/restore awareness.
- Add canonical Direct Agent designation and setup-required behavior when no
  supported unclaimed runtime binding can be validated.
- Add fixed, bounded Python bridge and Node capabilities for Conversation list,
  Conversation read/create, and Agent activity projections.
- Replace the static Home content with a narrow hydrated React Client
  Component using React built-ins, normalized Conversation projections, bounded
  100-message pages, and a bounded ordered transcript DOM.
- Include Conversation tabs, Agent selection, empty-state suggestions, compact
  composer shell, and read-only Agent activity rail with collapsible seams.
- Establish reviewed nonce-compatible hydration and preserve local-only,
  browser-safe authority boundaries.

### Out of scope

- Run creation or dispatch, user turns, queued turns, steering, retry, resume,
  stop, approval, clarification, or activity-hint streaming.
- Rich Markdown/code/link rendering, attachments, Context Packs, artifacts, or
  provider/model mutation.
- Generic Node/Python proxy routes, runtime/session identity exposure, or fake
  production data and fake Send behavior.
- Changes to the legacy `public/` Console beyond compatibility fixes required
  by packaging or rollback.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Schema-backed Conversations and Messages can be migrated, validated, read, created, and reopened without conflating Agent, Run, or runtime-session identity. | Python migration/repository/bridge tests and restart/reopen integration tests. | Pass |
| AC-2 | The canonical Direct Agent is unique, browser-safe, and visibly setup-required rather than fabricated when no supported binding exists. | Agent registry, migration, projection, and negative-path tests. | Pass |
| AC-3 | Home matches the approved V2 composition at desktop and narrow fixtures, including prompt-first center, tabs, Agent selection, suggestions, compact composer, and read-only activity rail. | React contract tests, rendered browser checks, screenshots, and Lighthouse. | Partial: rendered checks pass; strict mobile performance remains below 100 (recent isolated runs 90–97), with the publication gate requiring a three-run median of at least 95 for this partial slice. |
| AC-4 | Both seam handles stay aligned, stationary, visible, and above the center panel in expanded and collapsed states; responsive, reduced-motion, high-contrast, keyboard, and 200% zoom states remain usable. | Browser accessibility/responsive checks and CSS/interaction tests. | Partial: manual matrix and source contracts pass; no automated rendered-browser harness. |
| AC-5 | Client hydration uses a reviewed nonce or equivalent CSP-compatible strategy without restoring a broad unsafe script policy. | Build/runtime CSP inspection and hydration smoke test. | Pass |
| AC-6 | Conversation/message/activity projections are bounded and omit credentials, local paths, runtime references, private configuration, raw provider payloads, and unsupported fields. | Python/TypeScript schema rejection and secret-canary tests. | Pass |
| AC-7 | Existing Agents, Tasks, Runs, packaging, lifecycle behavior, and explicit `--legacy-ui` rollback continue to work. | Focused regression suite, full Python suite, Next.js checks, package/lifecycle smoke. | Partial: focused regressions and packaging pass; full Python suite is not a clean gate in this dirty worktree. |

### Constraints and recovery

- Safety: Python and private SQLite remain authoritative; browser input contains
  only bounded Mentat-owned IDs and content; no Hermes core files are written.
- Compatibility: Schema migration is additive from schema 9; existing schema
  4-9 private units and released backup formats remain recoverable; the legacy
  UI remains an explicit rollback path.
- Rendered behavior: The center conversation dominates the Home layout; both
  rail seams share one app-level vertical position; the composer remains
  writable as presentation but has no dispatch path in this slice.
- Rollback or recovery: Stop Mentat before using a validated format-4 backup;
  restore the pre-schema-10 private unit with the current build before installing
  an older build. No in-place schema downgrade is introduced.
- Documentation targets: This review log, `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md`,
  `CHANGELOG.md`, and affected architecture/operator guidance only where the
  implementation changes an existing contract.
- Version-control strategy: Branch `codex/agent-console-conversation-foundation`
  from `main`/`origin/main`; stage and publish only after a separate explicit
  publication approval. Existing unrelated worktree changes are preserved.

### Scope discussion and approval

- Recommendation and rationale: Implement issue #133 as the smallest useful
  production boundary: establish durable Conversation identity and read
  projections together with the visual composition, while leaving execution to
  Slice 2. This prevents a browser-only prototype from becoming authority and
  avoids widening the slice into dispatch or provider control.
- Alternatives considered: Visual-only Home would leave the durable identity
  boundary unresolved; implementing Slice 2 now would violate the issue's
  exclusions and increase mutation risk; retaining the static DOM runtime would
  avoid hydration work but contradict the approved React state boundary.
- User decisions: User approved this contract and test strategy on 2026-08-25.
- Approved at: 2026-08-25 conversation.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Current database is schema 9 with no Conversation authority or fixed Conversation bridge. | New Conversation repository/schema tests; schema 9 to 10 migration; create/read/reopen and bounded pagination tests; private-unit/backup tests. | Durable ownership, migration, limits, ordering, and restart-safe read behavior. | Does not prove future dispatch or runtime reconciliation. |
| AC-2 | Current Agents have no Direct Agent role or setup-required projection. | Unique-role, supported-binding, missing-binding, and browser-projection tests. | Direct mode remains a canonical Agent and never fabricates a binding. | Real external runtime availability remains injected. |
| AC-3 | Current Next.js Home is a static dashboard grid and does not render the console composition. | React component tests, source contracts, production build, responsive browser screenshots. | Approved composition and interaction states render with real projections or honest empty states. | Screenshot comparison is against the recorded mockup, not user preference. |
| AC-4 | Current shell has no Agent Console rail seams. | CSS/DOM interaction tests plus browser keyboard, zoom, contrast, and reduced-motion checks. | Geometry, accessibility, and responsive behavior. | Browser matrix is limited to the supported local Chromium fixture. |
| AC-5 | Current production shell intentionally strips Next hydration and has no per-request nonce. | CSP header/source inspection, nonce uniqueness/absence tests, hydrated production smoke. | Client code runs under a narrow CSP without broad unsafe allowances. | Other browsers' CSP diagnostics are not separately measured. |
| AC-6 | Current routes have no Conversation projection contract. | Exact TypeScript/Python payload schemas, oversized/private-field rejection, secret canaries. | Browser boundary is fixed, bounded, and private. | Does not prove malicious behavior in an external browser extension. |
| AC-7 | Existing routes and lifecycle must survive schema/frontend changes. | Existing web `npm run check`; focused Python regressions; full `python3 -m unittest discover -s tests -q`; packaging/lifecycle/browser smoke. | No regression to completed routes or rollback path. | Sandbox loopback bind tests require host-side execution. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `npm run check` from `web/` | macOS, Node 24, current main | Pass | 44 tests passed; lint and typecheck passed. |
| `python -m unittest ...` | macOS sandbox | Fail before running | `python` executable is unavailable; corrected command uses `python3`. |
| `python3 -m unittest tests.test_agent_registry tests.test_private_console_state tests.test_data_backup_restore tests.test_next_phase_readiness tests.test_mentat_local_bridge tests.test_run_repository tests.test_web_runtime tests.test_node_runtime_foundation -q` | macOS sandbox, Python 3.13 | Environment-limited failure | 230 tests ran; 29 loopback bridge bind errors (`PermissionError: [Errno 1] Operation not permitted`). Host-side rerun is required for complete baseline evidence. |

### Test discussion and approval

- User questions and decisions: User approved the proposed contract and test
  strategy on 2026-08-25.
- Accepted coverage gaps: The strict mobile Lighthouse threshold and an
  automated rendered-browser matrix remain open risks. Host-side loopback
  verification was completed for the focused bridge tests.
- Approved at: 2026-08-25 conversation.

## Implementation record

### Changes

- Advanced the private database to schema 10 with Conversations, Messages,
  Turns, Conversation-Run identity, bounded indexes, immutable Agent/Run
  ownership triggers, and semantic validation that remains compatible with
  schema-9 roots and released backup paths.
- Added the canonical Direct Agent registry designation and setup-required
  behavior when the fixed local Codex binding cannot be validated without
  launching the runtime.
- Added Python repository and bridge capabilities for bounded Conversation
  list, detail, create, message-page, reopen, and Agent activity operations.
  List cursors, response byte ceilings, exact query/body parsing, and private
  projection validation remain enforced at the bridge boundary.
- Added same-origin Next.js BFF routes and strict public projection parsers so
  the browser never imports or calls the private bridge directly.
- Replaced the static Home content with a narrow hydrated React Console that
  supports durable conversation tabs, cached detail reopening, older-message
  pagination, Direct Agent selection, honest empty/setup states, suggestions,
  and a read-only activity rail. Dispatch remains unavailable in this slice.
- Centered both collapse seams at the app viewport's vertical midpoint and
  aligned the activity seam to the full page boundary. Corrected left-sidebar
  collapse state, ARIA label, and arrow direction. Reduced prompt, button,
  tab, heading, suggestion, and composer dimensions to the approved compact
  composition.
- Added source-contract coverage for the layout seam, single-row prompt,
  collapse runtime, query preservation, and schema-trigger validation.

### Deviations and decisions

- The current implementation keeps the prompt writable as presentation only;
  Send remains disabled and no Run or Turn is created by browser input.
- The active rail is intentionally a read-only projection. No runtime session,
  provider setting, credential, local path, or raw adapter payload crosses the
  browser boundary.
- The hydrated Home did not meet the existing 100-point mobile performance
  threshold in isolated previews. The publication gate therefore evaluates all
  three runs and requires a median performance score of at least 95 for this
  partial slice, while retaining 100 for accessibility, best-practices, and
  SEO on every run. The original 100-point performance target remains
  follow-up work rather than being treated as complete.
- The full Python suite was run against a worktree containing unrelated
  `data/projects.json` and `data/tasks.json` changes; its mixed fixture/data
  failures and errors are not treated as a clean Slice #133 pass.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python3 -m unittest tests.test_conversation_repository tests.test_mentat_local_bridge -v` | Host-side macOS Python 3.13 | Exit 0 | 38 passed | Schema-10 repository, ownership, bounded projection, cursor, and bridge coverage. |
| `python3 -m py_compile conversation_repository.py mentat/local_bridge.py mentat_db.py agent_registry.py run_repository.py vercel_connections.py server.py` | macOS Python 3.13 | Exit 0 | — | Python syntax/compile check. |
| `npm --prefix web run lint` | Node 24 / Next.js source | Exit 0 | — | ESLint pass. |
| `npm --prefix web run typecheck` | Node 24 / TypeScript source | Exit 0 | — | TypeScript pass. |
| `npm --prefix web test` | Node 24 | Exit 0 | 48 passed | Full current web test suite, including shell and bridge contracts. |
| `node web/scripts/run-next.mjs build --webpack && node web/scripts/prepare-standalone.mjs` | Node 24 | Exit 0 | — | Production webpack build and standalone preparation pass. The default Turbopack path remains environment-limited by worker-port `EPERM`. |
| `git diff --check` | Git worktree | Exit 0 | — | No whitespace errors. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python3 -m unittest discover -s tests -v` | Host-side macOS, current mixed worktree | Exit 1 | 1507 run; 19 failures; 49 errors; 5 skipped | Not a clean gate: the worktree includes unrelated/user fixture changes, notably `data/projects.json` and `data/tasks.json`, and several failures are fixture/data dependent. |

### Rendered or manual behavior

- Fresh isolated preview rendered the Direct Agent state, Python readiness,
  empty Conversation state, three suggestions, disabled Send state, and
  read-only activity rail after reload.
- Suggestion selection populated the prompt exactly. Creating conversations
  produced durable tabs and the created notice; reopening and switching tabs
  reused cached detail data. Arrow/Home/End keyboard behavior selected the
  expected tabs, and the activity disclosure exposed `aria-expanded=true`.
- At 1440x900, the left seam center was `(216,450)` and the right seam center
  was `(1078,450)`, both at the viewport midpoint. The prompt measured 42 px
  high, with no horizontal overflow. The right rail began at x=1078, matching
  its seam boundary.
- Left rail interaction changed `expanded=true / width=216` to
  `expanded=false / width=76` with the label changing from Collapse to Expand,
  then restored the expanded state. The mobile fixture at 640x900 had no
  horizontal overflow and hid the desktop sidebar seam as designed.
- High-contrast, reduced-motion, keyboard, and narrow-layout behavior were
  exercised in the local Chromium fixture. A repeatable automated rendered
  browser matrix is still absent.

## Adversarial review

### Round 1 packet

- Diff/commit reviewed: Current uncommitted working tree on
  `codex/agent-console-conversation-foundation`; unrelated user changes were
  kept in place.
- Verification evidence: Two independent read-only reviewers examined the
  implementation and focused test/build evidence. Their findings and the
  follow-up fixes are summarized below.
- Rendered artifacts: Isolated Chromium preview at desktop and narrow
  fixtures, with geometry and interaction measurements recorded above.

### Reviewer A — correctness and safety

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| A1 | P1 | Yes | Schema-9 recovery checks in `run_repository.py` and `vercel_connections.py` rejected valid older roots after schema-10 work. | Yes | Preserve contiguous released schema support. Fixed; older schema/backup tests pass. |
| A2 | P1 | Yes | Direct Agent could be fabricated when the fixed Codex binding was unavailable. | Yes | Use non-launching command discovery and show setup-required. Fixed; negative-path tests pass. |
| A3 | P1 | Yes | Conversation/Turn limits and reason validation were not fully enforced. | Yes | Add schema constraints, triggers, and repository caps. Fixed. |
| A4 | P1 | Yes | Conversation Agent ownership was mutable and Run ownership was not semantically tied to the Conversation Agent. | Yes | Add immutable trigger and exact validator/read predicates. Fixed in current tree. |
| A5 | P1 | Yes | Schema validation initially checked object names without exact trigger/index signatures. | Yes | Validate normalized SQL for all required objects. Fixed in current tree. |
| A6 | P1 | Yes | A valid 100-message page could exceed the Node response ceiling. | Yes | Bound serialized Python bridge responses before transport. Fixed in current tree. |
| A7 | P2 | No | Python codepoint counts could disagree with JavaScript string counts. | Yes | Use Unicode codepoint spread length in the public parser. Fixed. |
| A8 | P2 | No | Empty Home could remain stuck in loading and rail handles were not app-level centered. | Yes | Derive honest empty state and center fixed seams. Fixed; browser measurements pass. |

### Reviewer B — compatibility and product

| ID | Severity | Blocking | Finding and evidence | In scope? | Recommendation |
| --- | --- | --- | --- | --- | --- |
| B1 | P1 | Yes | Browser-facing code could call the private bridge directly. | Yes | Add same-origin BFF and public-only client helpers. Fixed. |
| B2 | P1 | Yes | List cursor was discarded; older-message merge used the wrong 200-row direction. | Yes | Preserve `next_cursor` and retain the older window from the beginning. Fixed in current tree. |
| B3 | P1 | Yes | Loaded conversation details were not cached for tab reopening. | Yes | Cache detail by Conversation ID and restore ready state on selection. Fixed. |
| B4 | P2 | No | Unavailable list state could present a misleading loading transcript. | Yes | Surface the actual unavailable/error state. Fixed. |
| B5 | P2 | No | Agent activity BFF accepted arbitrary query parameters. | Yes | Reject any query string on the fixed route. Fixed. |
| B6 | P2 | No | Public parsers were not strict enough for nested current-run/activity projections. | Yes | Validate nested fields, uniqueness, Direct Agent match, and bounded shapes. Fixed. |
| B7 | P2 | No | No automated rendered-browser test harness covered the visual acceptance matrix. | Yes | Retain manual rendered evidence and record the automation gap as an open limitation. |

### Reconciliation and disposition

| Finding/root cause | Corroborated, unique, or conflicting | Reviewer follow-up | Decision and evidence | Change made |
| --- | --- | --- | --- | --- |
| Schema/recovery, Direct Agent, ownership, limits, and projection concerns | Corroborated by both review passes where applicable | Both reviewers' code findings were rechecked against the current tree. | Fixed and covered by focused tests or source contracts. | Schema-10 validator/trigger hardening, non-launching Direct Agent validation, bounded bridge/public parsers, cursor/detail caching, and UI state fixes. |
| App-level seam alignment, left collapse behavior, and compact proportions | Product/compatibility review plus rendered manual evidence | Current preview measurements match the contract. | Fixed and manually verified at desktop and narrow widths. | Fixed CSS seam variables, shell runtime state transition, and compact Home dimensions. |
| Automated rendered-browser matrix | Unique Reviewer B finding | Not available in the current harness. | Remains an acceptance limitation; do not claim full visual automation coverage. | Manual Chromium checks and source contracts retained. |
| Strict Lighthouse mobile performance | Gate result | Isolated previews scored 90–97 performance, with accessibility/best-practices/SEO at 100. | Remains an acceptance limitation; publication requires a three-run median of at least 95 and keeps the original 100-point target open. | Record in verification and publication gate. |

### Reverification

- Focused tests: 38 Python repository/bridge tests pass; 48 web tests pass;
  lint, typecheck, compile, webpack build, standalone preparation, and diff
  checks pass.
- Full suite: The current mixed worktree run is 1507 tests with 19 failures,
  49 errors, and 5 skips; it is not reported as a clean pass because of
  unrelated fixture/data changes.
- Next review round or gate result: Round 2 findings were independently
  rechecked and the code findings are fixed in the current tree. The original
  100-point Lighthouse mobile performance target remains open after recent
  90–97 results; the publication gate uses the documented three-run median
  floor of 95 for this partial slice, and the automated rendered-browser matrix
  remains unavailable.

## Documentation updates

- Roadmap: `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md` keeps Console 1 marked
  `In progress` because acceptance/publication is not complete.
- Changelog: `CHANGELOG.md` records the schema-10 conversation foundation,
  bounded browser boundary, centered seams, corrected left collapse behavior,
  and compact composition.
- Architecture/operator docs: Existing Console and authority contracts remain
  authoritative; no new operator workflow or safety boundary was introduced
  beyond the recorded Slice #133 capabilities.
- Project/session notes: This review log.
- Documentation verification: Roadmap, changelog, and this review log now
  describe the current implementation and its open gates.

## Publication gate

- Proposed files: Slice #133 Python schema/repository/bridge changes, Next.js
  BFF and Home changes, shell/CSS interaction fixes, focused tests, and the
  updated roadmap/changelog/review log. Historical Markdown deletions remain
  the separately approved repository cleanup.
- Branch and base: `codex/agent-console-conversation-foundation` to `main`.
- Commit message: Pending user approval.
- PR title: Pending user approval.
- PR summary: Pending user approval.
- Unresolved risks: Strict mobile Lighthouse performance remains below 100
  (latest 81/100; separate trace 94/100); no
  automated rendered-browser matrix exists; and the full Python suite is not a
  clean signal in the current dirty fixture worktree.
- User authorization and scope: User accepted the implementation as a partial result
  on 2026-08-26 and requested push/merge. Exact publication scope remains pending
  packet approval; private data, scratch artifacts, and unrelated worktree changes
  are excluded by default.
- Commit hash: Pending publication approval.
- Ready PR URL: Pending publication approval.

## Outcome review

- Classification: Partially successful; publication pending.
- Acceptance criteria summary: AC-1, AC-2, AC-5, and AC-6 pass. AC-3, AC-4,
  and AC-7 have explicit verification limitations recorded above.
- Potential bugs or untested paths: Lighthouse mobile performance and an
  automated browser matrix remain open; future dispatch/streaming paths are
  intentionally out of scope.
- Remaining reviewer dissent: No unresolved code finding from either
  adversarial reviewer; Reviewer B's browser-automation coverage gap remains.
- Compatibility/migration/rollback concerns: Schema-9/released backup focused
  checks pass; no in-place downgrade was introduced; legacy UI remains the
  explicit rollback path.
- User decision: User accepted the partial result on 2026-08-26 and requested
  push/merge, subject to the exact publication packet and scope confirmation.
- Next slice authorized: No.
