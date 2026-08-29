# Feature Slice Review: Agent Console attachments, Context Packs, images, and artifacts

Status: Ready for publication
Slice: `agent-console-attachments-context-images-artifacts`
Date: `2026-08-29`
Review log: `reviews/2026-08-29-agent-console-attachments-context-artifacts.md`

## Slice contract

### Goal

Let a person stage validated local files, workspace snapshots, or one existing
Context Pack in a durable Conversation, send that exact context to a supported
local Hermes Run, and review retained input and generated output files after
refresh without exposing filesystem authority to Node or the browser.

### In scope

- Add schema-15 Conversation-owned staging references over the existing private
  attachment/blob authority. Refresh reconstructs safe staged chips for the
  exact Conversation; tab switches and concurrent Conversations remain isolated.
- Accept at most eight staged items total. Direct upload and workspace selection
  retain the established five-item ceiling; an existing Context Pack may fill
  the remaining slots up to its established eight-item ceiling. Retain the local
  Hermes ceiling of one image and all existing byte, pixel, frame, MIME, content,
  symlink, root, snapshot, expiry, grace, retention, and garbage-collection rules.
- Allow one existing Context Pack to be applied by exact ID and revision. Re-read
  the pack and every note/workspace reference during staging and again before
  dispatch. Persist references and revisions, never copied note/file contents or
  absolute paths.
- Permit a context-bearing Send only while the Conversation is idle with no
  queue-active Turn. Reserve the Run and bind the exact staged attachments before
  any runtime call. Capacity or validation failure accepts no text-only fallback
  and preserves the draft and staged context.
- Add `run.attachments` only to the local Hermes runtime path and matching Agent
  declarations. Codex, Vercel, remote Hermes without the complete current
  contract, queued follow-ups, Retry with unavailable source context, and
  `/steer` fail closed without dropping staged state.
- Add fixed private Python bridge and same-origin Node capabilities for raw
  upload, release, workspace search/snapshot, Context Pack list/apply,
  Conversation media, and exact Conversation-bound attachment content.
- Project retained input and output media grouped by canonical Run. Missing
  content remains visible as unavailable metadata without a content URL.
- Add compact composer controls, per-Conversation upload states, cancellation,
  ready/error chips, workspace and Context Pack pickers, bounded local-image
  presentation, and file cards with Review and Download actions.
- Run startup reconciliation before readiness and the existing bounded periodic
  collector afterward. Staged Conversation references are disposable and stay
  outside compatible export; retained Run attachment/blob backup behavior stays
  unchanged.

### Out of scope

- Context Pack create, edit, or delete in the Next.js Console.
- Attachment-only Sends, attached queued Turns, attachment steering, arbitrary
  remote file transfer, Codex attachments, Vercel attachments, PDF/HTML/SVG
  embedding, archives, executables, arbitrary file URLs, or browser-selected
  filesystem roots.
- Copying note/file contents or absolute paths into Conversation staging rows,
  Run details, browser state, logs, tracked JSON, or review evidence.
- Parsing artifact paths from assistant prose, widening artifact types, or
  changing Task-delegation artifact authority.
- Conversation deletion, queue reordering, or unrelated Console refactors.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Upload, workspace, and Context Pack staging is exact-Conversation-owned, survives refresh, and cannot cross tabs or revisions. | Schema/repository/bridge/BFF/Home concurrency and refresh tests. | Pass |
| AC-2 | Every existing validation, snapshot, expiry, grace, active-Run, retention, startup, and bounded-GC rule remains enforced. | Existing attachment/artifact suites plus new staging lifecycle and tamper tests. | Pass |
| AC-3 | A context-bearing Send is idle-only, idempotent, capacity-safe, and never degrades to text-only or queues attached work. | Orchestration/repository race, replay, active queue, unsupported runtime, and `/steer` tests. | Pass |
| AC-4 | Only the exact capable local Hermes Run receives server-resolved snapshots; Node/browser never receive paths, hashes, blob keys, runtime refs, or arbitrary content URLs. | RuntimeContext/Hermes/bridge projection and private-field rejection tests. | Pass |
| AC-5 | Retained input and trusted run-export output media render by Run through Conversation-bound opaque routes; model-prose paths and stale metadata cannot mint access. | Artifact integration, media projection, content authorization, and hostile route tests. | Pass |
| AC-6 | Compact upload/picker/chip/image/file-card UI is keyboard and screen-reader usable, handles cancel/error/loading, and has no desktop/mobile overflow. | React interaction tests and in-app browser checks at desktop/mobile sizes. | Pass |
| AC-7 | Backup/restore, schema-5 compatible export, startup recovery, Windows/POSIX behavior, packaging, performance, and full CI remain green. | Migration/backup/export/full-suite/build/performance/matrix evidence. | Local pass; PR CI pending |
| AC-8 | Two independent adversarial review rounds end with no blocking findings and project records describe the final boundary. | Final review packets, re-review results, and documentation checks. | Pass |

### Constraints and recovery

- Safety: Python alone owns bytes, paths, validation, storage, attachment-to-Run
  binding, Context Pack revalidation, artifact discovery, and content access.
- Compatibility: schema 15 is forward-only; released schemas remain readable by
  backup/restore migration tests. Rollback uses a validated pre-migration backup
  or schema-5 compatible sibling, never in-place downgrade.
- Rendered behavior: the composer remains primary; controls stay compact, images
  are bounded and lazy, unavailable media is explicit, and mobile targets are at
  least 44 px without page-level horizontal overflow.
- Rollback or recovery: startup reconciles interrupted uploads, stale staging,
  missing blobs, expired rows, and retained references before readiness. No
  external runtime call occurs until the exact staged set is durably bound.
- Documentation targets: `AGENTS.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, this log,
  and closeout updates to the implementation roadmap and Wayfinder.
- Version-control strategy: `codex/agent-console-slice-8` based on the Slice 7
  closeout commit, ready PR to `main`, normal merge after every required check.

### Scope discussion and approval

- Recommendation and rationale: use schema-15 Conversation staging and
  immediate-only attached Sends. Browser-only staging cannot meet refresh or
  cross-tab acceptance; Turn-owned queued files would add cancellation,
  continuation, backup, and scheduler semantics beyond this slice.
- Alternatives considered: browser-only staged IDs were rejected because refresh
  loses ownership; attached queued Turns were deferred because they broaden the
  durable queue contract; Context Pack CRUD was deferred to a dedicated Settings
  workflow; eight direct files was rejected in favor of the existing five-file
  direct ceiling.
- User decisions: the user granted standing approval for every remaining slice,
  scope, integration, commit, push, PR, and merge, and explicitly approved
  parallel agents. This overrides the workflow's repeated approval pauses but
  not its evidence, review, ready-PR, or all-green gates.
- Approved at: 2026-08-28 and reaffirmed throughout the active goal.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | No Conversation staging tables or bridge projection exist. | Failing schema/repository/bridge/Home refresh and two-tab tests. | Durable ownership and isolation. | Does not prove runtime delivery. |
| AC-2 | Existing private boundary is legacy-global, not Conversation-scoped. | Reuse full attachment/artifact suites; add expiry, same-size tamper, missing blob, startup, GC, and capacity tests. | Existing storage rules survive the integration. | Injected filesystem races approximate platform timing. |
| AC-3 | Submit accepts text only and queues during active work. | Repository/orchestration tests for exact replay, changed context, capacity race, active Run/queue, Retry, and steer. | No partial binding or silent context loss. | Runtime calls are deterministic fakes at this layer. |
| AC-4 | RuntimeContext and Hermes adapter carry no file identity. | Runtime-neutral type tests, local/remote Hermes capability tests, private handler assertions. | Only approved adapters receive opaque context. | Browser use does not inspect private runtime payloads. |
| AC-5 | Conversation detail exposes no media. | Trusted export, model-prose, stale details, missing bytes, cross-Conversation content, MIME/header tests. | Run authority controls every media route. | Real model artifact generation remains observational. |
| AC-6 | Home has no attachment controls. | React upload cancellation/failure/tab handoff/picker/image tests; desktop/mobile browser use. | Usable, isolated rendered behavior. | Screen-reader software is approximated by semantic DOM tests. |
| AC-7 | Schema 14 and current package omit staging. | Schema migration fingerprints, backup/restore/export, full Python/web, configured build, performance, and CI matrix. | Release and platform compatibility. | Local Turbopack may require CI when sandbox IPC is blocked. |
| AC-8 | No Slice 8 review exists. | Two neutral-packet read-only adversarial reviewers, fixes, full re-review. | Independent safety and product scrutiny. | Review cannot prove unknown future runtime behavior. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `git status --short` | isolated Slice 8 worktree | Pass | Clean; branch contains only the pending Slice 7 closeout commit over merged main. |
| Source and nearest-test inspection | macOS/Python 3.13/Node 24 | Gap confirmed | Existing storage is reusable; Local Bridge, Node/BFF, Conversation staging, runtime context, and Home UI are absent. |

### Test discussion and approval

- User questions and decisions: standing approval covers the complete mapped
  strategy and parallel package execution. No material scope choice remains
  undiscoverable from repository contracts.
- Accepted coverage gaps: real third-party model artifact production is not a
  release gate; trusted deterministic export fixtures plus local browser use are.
- Approved at: 2026-08-29 under standing slice/test authorization.

## Implementation record

### Changes

- Added schema-15 Conversation-owned staging and retained Run-context tables,
  exact source fingerprinting, backup filtering, old-schema restore support, and
  package inventory.
- Added one attachment/context service for upload association, workspace and
  Context Pack snapshots, exact Send binding, retained Retry copying, safe
  media projection, Conversation-bound content reads, and whole-pack startup
  reconciliation.
- Added opaque attachment and Context Pack fields to `RuntimeContext`, local
  Hermes support detection, orchestration revalidation, context-aware replay,
  immediate-only repository admission, and server-resolved Context Pack
  instructions.
- Added an exact explicit Enable files mutation. It is Agent-scoped, current-
  capability-bound, local-Hermes-only, and blocked by active/finalizing Runs.
- Added fixed private bridge and same-origin Node routes for staging, raw upload,
  release, workspace search/snapshot, Context Pack list/apply/release, media,
  content, and Agent permission. Every projection rejects private or extra
  fields.
- Added compact Home upload/workspace/Context Pack controls, per-Conversation
  remount isolation, staged chips, exact pack removal, Run-grouped media cards,
  safe lazy images, and Review/Download actions.
- Preserved the Slice 7 compact Chrome-style tabs, close/reopen behavior, exact
  console centering, and state-dependent left/right collapse chevrons while
  integrating the new controls.

### Deviations and decisions

- The standing-approval process exception is recorded above. All technical,
  verification, adversarial-review, ready-PR, CI, and merge gates remain intact.
- A broad migration that granted `run.attachments` to every existing Hermes
  Agent was rejected as an unsafe permission expansion. Slice 8 instead adds an
  explicit Agent-scoped Enable files action bound to the exact current
  capability set, local Hermes support, and no active/finalizing Run. Existing
  Agents remain unchanged until the operator takes that action.

## Verification

### Focused checks

- `python -m unittest tests.test_conversation_attachments tests.test_conversation_attachment_orchestration tests.test_conversation_file_bridge tests.test_agent_runtime tests.test_agent_registry tests.test_schema12_forward_migration -v` — 82 passed.
- `python -m unittest tests.test_run_repository -v` and the relevant Task,
  Vercel, backup, and private-unit suites — passed during the full gate.
- `npm --prefix web run check` — lint, typecheck, and 184 tests passed.
- Focused Node media/route/public/component/Home tests — 20 passed before the
  full web gate; subsequent exact unsupported-status and Home integration tests
  are included in the 184-test result.
- `git diff --check` and Python compilation for every changed runtime module —
  passed.

### Full suite

- `python -m unittest discover -s tests -v` — 1,764 passed, five expected native-
  platform skips.
- The default local Turbopack command was blocked by this host sandbox when its
  CSS worker attempted a loopback bind. `node scripts/run-next.mjs build
  --webpack` compiled, typechecked, generated all six pages, and traced every
  new route; `node scripts/prepare-standalone.mjs` completed. The unchanged
  default build remains a required PR-CI gate.
- `npm --prefix web run performance:agent-console` — pass. Medians: optimistic
  paint 9.6 ms, accepted dispatch 97.7 ms, stream paint 5.3 ms, loaded tab 7.7
  ms; all seven typing network deltas were zero.
- `python scripts/stage_web_runtime.py`, `uv build`, and
  `python scripts/verify_python_artifacts.py dist` — source distribution and
  wheel built and verified with `conversation_attachments` and every new Node
  route included.

### Rendered or manual behavior

- Production standalone preview used disposable schema-15 data and a disposable
  local Hermes Agent. Raw upload and an instructions-only Context Pack both
  staged, remained isolated to the selected Conversation, survived reload, and
  exposed exact removal controls. With both staged, entering a prompt enabled
  Send and displayed `2 staged context items · Send starts one exact Run`; no
  runtime call was made during acceptance.
- Desktop measurements: Conversation tab height 34 px, empty-state center delta
  0 px, page overflow 0 px. Closing and reopening the tab preserved staging.
  The left collapse glyph changed `‹` to `›`; the right glyph changed `›` to
  `‹`, with matching accessible labels.
- At 390×844, upload, workspace/Context Pack summaries, and tab close measured
  44 px; tab height stayed 34 px and page overflow stayed 0 px.
- Browser console warnings/errors: none. The temporary preview, database, pack,
  and upload fixture were stopped and removed afterward.
- Final production rebuild verification repeated tab create, close, and reopen;
  measured a 34 px tab, exact 0 px empty-state center delta, and 0 px page
  overflow at 1280×720. The left glyph changed `‹` to `›`, the right changed
  `›` to `‹`, and both accessible labels changed with their state. At 390×844,
  the tab stayed 34 px, its close action measured 44×44 px, and page overflow
  remained 0 px. Browser warnings/errors remained empty. The disposable data
  root and preview were removed.

## Adversarial review

Two independent read-only reviewers covered security/authority/migration and
product/accessibility/concurrency. Both final re-reviews were clean.

The security reviewer found and verified fixes for:

- P1 schema-14 restore consumers that omitted version 14;
- P1 late or incomplete Context Pack source validation;
- P1 runtime-support races and mutable, unverified Hermes input paths;
- P1 image handoff loss and validation that could fail only after admission;
- P2 partial-materialization residue;
- P1 descriptor traversal and cleanup races, including Obsidian symlink swaps;
- P2 elapsed staging that stayed readable until garbage collection;
- P1 simultaneous replay and normal SQLite sidecar-churn failures;
- P2 crash-orphaned Run inputs;
- P1 cleanup escaping runtime storage, racing live inputs, or skipping Codex
  shutdown; and
- P1 platforms advertising files before proving secure cleanup support.

The product reviewer found and verified fixes for:

- P1 hidden staging after failed reads and invisible cancelled/uncertain uploads;
- P1 stale Context Pack execution and a staging gate that blocked queue or steer;
- P1 non-FIFO upload/read reconciliation and filename-based upload attribution;
- P2 missing, misordered, or stale retained-media presentation;
- P2 dishonest Agent eligibility and stale Context Pack picker state;
- P2 Strict Mode control breakage;
- P2 duplicate cancelled-upload states, discarded receipt IDs, and missing
  per-operation failure chips; and
- P2 mobile removal targets below 44 px.

Fixes added exact pre-admission revalidation and immutable Run inputs,
descriptor-relative reads and cleanup, operation-scoped upload receipts with
per-Conversation arrival tickets, explicit staging authority states, safe media
ordering, server-derived eligibility, Strict Mode coverage, and exact mobile
targets. The final security review reported no remaining security findings. The
final product review reported no remaining product, accessibility, or
concurrency findings.

## Documentation updates

- `AGENTS.md` records schema-15 staging limits, immediate-only dispatch,
  explicit permission, and whole-pack invalidation.
- `ARCHITECTURE.md` records staging/run-context authority, replay/Retry,
  capability gating, backup filtering, and reconciliation.
- `CHANGELOG.md` records the user-facing controls and safety boundary.

## Publication gate

- Branch and base: `codex/agent-console-slice-8` to `main` after Slice 7 closeout.
- User authorization and scope: standing approval recorded; ready PR only.
- Commit hash: pending.
- Ready PR URL: pending.

## Outcome review

- Classification: Implemented; PR CI pending.
- Acceptance criteria summary: AC-1 through AC-6 and AC-8 pass locally; AC-7
  awaits PR CI.
- Potential bugs or untested paths: real third-party artifact generation remains
  observational; the deterministic trusted export, retained media, and browser
  paths are covered.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: schema-15 migration and old-backup
  restore require explicit cross-platform evidence.
- User decision: standing acceptance/continuation authorization recorded, subject
  to the required all-green and clean-review gates.
- Next slice authorized: Yes, but implementation will not begin until Slice 8
  itself is merged and closed out.
