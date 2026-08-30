# Changelog

All notable changes to Mentat.

## 2026-08-29

### Changed
- Balanced the collapsed desktop rails so the Conversation workspace is
  centered exactly, made Agent configuration compact and text-led, bounded the
  activity rail to the viewport, and removed the empty Provider connections
  card area after settled empty or failure states.

### Added
- Added schema-17 non-owning Conversation Project/Task associations with exact
  Apply/Clear, stale-target projection, bounded planning overview and Task
  paging, draft-only suggestions, and capped planning attention.
- Added the interactive Projects & Tasks workspace with Name-only Project
  creation and selected-Project Task creation using only Title, optional Agent,
  and optional Due date.
- Added schema-16 manual Conversation titles with exact-revision rename for
  active or archived Conversations.
- Added bounded title-only Conversation history search with active, archived,
  and all filters, query-bound 50-row paging, and a compact Open, Rename,
  Archive, and Restore manager.
- Added strict Next.js support for the existing four-command Mentat manifest,
  local keyboard completion, fixed command help, and safe `/new`, `/model`,
  `/steer`, and `/help` handlers.
- Added schema-15 Conversation-owned file and Context Pack staging with exact
  refresh recovery, idle-only local Hermes dispatch, retained Retry inputs, and
  explicit Agent-scoped file permission.
- Added fixed Python/Node upload, workspace snapshot, Context Pack, retained
  media, and Conversation-bound content capabilities plus compact composer
  controls and Run-grouped image/file cards.
- Added Message-bound public-HTTPS rich-link previews with pinned DNS/IP/TLS
  transport, credential-free replaceable workers, bounded metadata parsing,
  verified WebP transformation, safe asynchronous cards, and permanent plain
  link fallback.
- Added an enabled-by-default revisioned privacy control, explicit disposable
  cache clear, negative caching, offline/cache-only behavior, and opaque
  same-origin preview images.
- Added a bounded React-text Markdown transcript with inert highlighted code,
  Message/code copy actions, Run grouping, and provenance-safe Thinking and
  Activity disclosures.
- Added compact Chrome-style Conversation tabs, working close controls, exact
  desktop centering between navigation and activity rails, and a directional
  navigation collapse arrow.
- Added compact Agent, Provider, Model, and Effort controls to the Home composer.
- Added a canonical-Agent configuration bridge that resolves private Hermes
  profile bindings only inside Python and reuses exact provider preview and
  confirmation.
- Added the active Run's safe immutable provider/model/effort snapshot to the
  Conversation projection.

### Safety
- Kept planning context out of Run `task_id`, hidden prompt input, Pending-turn
  scheduling, and Hermes delegation; selector changes remain staged until an
  explicit exact-revision Apply or Clear.
- Kept Project/Task creation behind fixed same-origin and private bridge
  capabilities with server-owned defaults and no runtime or delegation side
  effect. Private Task planning, note, calendar, delegation, file, and Agent
  details remain outside planning projections.
- Kept history search navigation-only and free of Messages, Runs, snippets,
  runtime references, and query echoes. Delete and bulk mutations remain absent.
- Made unknown, malformed, unavailable, or failed slash commands preserve the
  full draft with no ordinary-Send, CLI, shell, or generic-handler fallback.
- Kept file bytes, paths, hashes, storage keys, runtime references, and arbitrary
  URLs outside Node and browser authority; Context Packs and every snapshot are
  revalidated before dispatch with no queued, remote, or text-only fallback.
- Excluded unsent Conversation staging from backup and compatible export,
  preserved retained Run inputs/artifacts, and made startup reconciliation drop
  an entire changed Context Pack snapshot set.
- Prevented browser-selected URLs and generic proxying; every preview re-reads
  one exact accepted user Message and keeps raw URLs, HTML, headers, redirects,
  addresses, original images, paths, credentials, and internal errors outside
  cache and browser projections.
- Excluded the versioned preview cache, transformed images, and cache secret
  from backup/restore/compatible export while keeping the privacy preference in
  a separate owner-only exact-revision file.
- Kept raw HTML, unsupported links, bidi controls, tool payloads, provider reasoning,
  runtime references, and executable code outside the transcript presentation
  boundary; long transcripts remain capped at 200 rendered Message rows.
- Prevented the shell mutation observer from retriggering itself by making
  collapse-control synchronization idempotent.
- Kept Codex, Vercel, unsupported runtimes, and unsupported effort mutation
  read-only; browser input cannot choose private runtime settings.
- Filtered Hermes choices to authenticated profile inventory and preserved
  active-Run exclusion, post-write verification, rollback, and partial-failure
  behavior.

## 2026-08-28

### Added
- Added exact Home Stop and approval/clarification controls through the existing
  preview-confirm runtime boundary.
- Added recent Conversation history, presentation-only tab close/reopen, and
  exact-revision reversible archive and restore.
- Added schema-14 durable Retry and capability-gated Resume attempts for one
  Conversation Turn, with bounded idempotency receipts and preserved prior Run
  evidence.

### Changed
- Treat initial nonterminal Conversation state as reconciling until the exact
  selected Run completes authoritative runtime readback.
- Keep ordinary composer text separate from approval and clarification cards.
- Allow up to seven explicit later attempts for one Turn while retaining one
  active Run per Conversation and existing adapter-scoped capacity.

### Safety
- Kept recovery action keys, binding digests, runtime references, and Resume
  continuity private; browser responses contain only safe Mentat IDs, status,
  and duplicate evidence.
- Made schema 14 accept only the exact schema-13 fingerprint under the same
  SQLite write lock and recover interrupted attempts without resubmission.
- Kept tab close and archive independent from Stop, deletion, queue authority,
  and runtime execution.

## 2026-08-27

### Added
- Added durable eight-Turn FIFO Conversation queues with exact-revision edit,
  cancel, and explicit Continue operations.
- Added selected-Run live progress, exactly-once durable assistant Message
  projection, and bounded global Agent activity hints.
- Added exact active-Run `/steer`, private Codex thread continuity, and typed
  adapter capacity with a qualified two-Conversation Codex ceiling.
- Added authenticated local Hermes live control so active local Runs can accept
  exact `/steer` guidance through Hermes' supported redirect operation.

### Changed
- Kept the Home composer writable during active Runs: ordinary text queues,
  while `/steer` is sent only to the exact selected compatible Run.
- Made verified success claim at most one oldest pending Turn. Stop, failure,
  interruption, unknown or partial evidence, and capacity pressure now pause
  the queue until explicit revalidation.
- Reconciled only the selected detailed Run from its live stream while keeping
  background Conversations on bounded summary hints.
- Made the full interactive capability set, including `run.message`, the
  default for newly created Hermes and Codex Agents; live controls still depend
  on the exact Run's verified adapter state.
- Advanced the private Console database through schema 13: schema 12 converges
  one exact pre-release schema-11 Conversation shape, and schema 13 records an
  exact terminal-finalization barrier plus retention-safe Codex continuation.

### Fixed
- Repaired startup for an existing owner-private data root created by the
  pre-release Slice 3 schema, while continuing to reject every unrecognized
  schema difference.
- Stopped stale legacy attachment and artifact display metadata from exposing
  content routes after its canonical run binding and retained blob are gone.
- Replaced the local Hermes one-shot execution path with the supported
  profile-scoped headless session when available, retaining one-shot fallback
  only before any prompt could have been submitted.
- Prevented a split Hermes status/event read from consuming a newer terminal
  event while leaving the canonical Run active and its FIFO successor stranded.
- Finalized pre-launch Hermes cancellation and binding-loss exits before worker
  cleanup, so each unsafe exit blocks rather than silently marooning the head.
- Kept ambiguous steering partial after later runtime completion, preventing an
  unverified control delivery from automatically advancing queued work.

### Safety
- Bound queue mutations to both Turn and Message revisions and rechecked exact
  Conversation, Turn, Run, Agent, and configuration identity at every bridge
  layer.
- Kept runtime references, capacity scopes, raw provider events, partial token
  text, credentials, and local paths behind the private Python/SQLite boundary;
  ambiguous submissions and steering are never retried automatically.
- Made the schema-12 Turn rewrite and receipt atomic, verified the complete
  foreign-key graph before commit, and restored connection enforcement after
  both successful and rolled-back upgrades.
- Bound the exact schema-11 source fingerprint to the same SQLite write
  transaction as the rewrite, preserved quoted SQL contents and token
  boundaries during layout normalization, and rejected caller-owned
  transactions without committing them.
- Kept the local Hermes control token, socket, session identifiers, redirect
  text, and process private; steering is advertised only after `message.start`,
  never queues, and ambiguous delivery is never retried.
- Published each local control client before startup, closed it from both
  server lifecycles, rejected redirected runtime directories, and owned the
  complete POSIX or Windows process tree through shutdown.
- Added the pinned WebSocket client to the hashed native dependency lock and
  preserved ambiguous steering as a partial Conversation result through the
  browser bridge.
- Exposed terminal Hermes work as `finalizing` until exact final evidence is
  durable, pinned it against retention, and limited the initial cursor gap to
  the exact Agent-and-Turn binding marker.
- Canonicalized schema-12 continuation pins that had already advanced beyond
  reservation before installing schema 13's stricter identity trigger, keeping
  claimed and accepted pre-upgrade successors restart-recoverable.
- Persisted the exact Codex predecessor while a queued successor is reserved;
  the dispatch claim reads its private thread reference and clears the pin only
  in an authorized claim or no-attempt terminal transition, with the exact
  synchronous result protected through its retention pass and bulk recovery
  still bounded by the normal retention ceiling.

## 2026-08-26

### Added
- Added Agent Console text Turn submission through one fixed Next.js/Python
  capability, with atomic Message, Turn, Run, idempotency, immutable execution
  configuration, and bounded capacity evidence before one unlocked runtime call.
- Added write-once verified runtime-execution identity plus synchronous
  pre-readiness crash classification and asynchronous exact-reference readback
  for the Next.js bridge.
- Added explicit Codex CLI readiness states and `codex login` guidance so each
  operator can reuse their own ChatGPT subscription sign-in without giving
  Mentat credential material.
- Added the Agent Console Slice 1 conversation foundation: schema-10
  Conversation, Message, Turn, and Conversation-Run identity; a canonical
  Direct Agent; bounded list/detail/create/activity bridge capabilities; and
  a hydrated prompt-first Home surface with durable reopen behavior.
- Added compact conversation tabs, empty-state suggestions, a presentation-only
  composer, and a read-only Agent activity rail. Dispatch remains unavailable
  until the next Console slice.

### Changed
- Enabled the Next.js prompt composer for idle Conversations with optimistic
  display, Enter-to-send, Shift+Enter newline, exact replay handling, honest
  active-Run gating, one-time pre-Conversation drafts, and Conversation-scoped
  drafts, unresolved retry keys, and Turn announcements.
- Hardened private mutation bodies with exact framing, transfer-encoding
  rejection, and a total wall-clock read deadline.
- Centered the Home rail seams against the app viewport so both collapse
  handles remain aligned with the full page in expanded and collapsed states.
- Corrected the left rail's collapse/expand state, accessible label, and arrow
  direction, and tightened prompt, button, tab, heading, and suggestion sizing
  to match the approved composition.

### Safety
- Kept Codex thread and turn references, runtime configuration, capacity scope,
  account data, and authentication material behind the private SQLite/runtime
  boundary; ambiguous submissions remain durable and are never auto-retried.
- Kept Conversation and Message authority in private SQLite and exposed only
  bounded, validated Mentat-owned projections through same-origin BFF routes.
  Runtime references, credentials, local paths, and raw provider payloads do
  not cross the browser boundary.

## 2026-08-23

### Added
- Added one optional private Vercel connection with exact configure, test,
  Agent-create, status, and disconnect commands.
- Added a bounded AI Gateway runtime plus separate fixed Sandbox Node 24 and
  Connect token readiness checks.
- Added a safe provider status view to the responsive Agents workspace.
- Added explicit recovery for an ambiguous Vercel dispatch. It marks one exact
  Run interrupted without retrying the provider request.

### Changed
- Advanced the private Console database to schema 9 while keeping released
  backups restorable and the schema-5 compatible-root export usable.
- Included provider settings and compatible Agent bindings in the same
  format-4 backup and restore unit.
- Made Vercel result messages visible in the bounded Run timeline and hid Run
  controls that a known Agent does not support.

### Safety
- Kept Vercel optional. Credentials stay in operator environment variables and
  never enter SQLite, backups, browser responses, or normalized Run evidence.
- Limited Vercel traffic to fixed HTTPS operations. Sandbox commands are fixed
  and temporary, use one total deadline, and require verified stopped cleanup;
  Connect tokens are validated and immediately discarded.

## 2026-08-22

### Added
- Added schema-8 Agent identity and private runtime bindings to the canonical
  `mentat.sqlite3` database, with a singleton authority receipt.
- Added `mentat agent-registry-migration`, an offline read-only preview and
  exact confirmation workflow that creates a verified pre-cutover backup.
- Added format-4 private backups with one embedded Console database while
  retaining restore support for released format-2 and format-3 archives.
- Added one runtime-neutral Runs view for concurrent Hermes and Codex work,
  with exact Agent-name joins, readable runtime labels, and safe ID fallbacks.
- Added a deterministic two-runtime integration test covering concurrent
  dispatch, reconciliation, events, message, Stop, and confirmation isolation.
- Added Codex as a second runtime through one fixed local App Server stdio
  connection. It reuses an existing Codex CLI sign-in and supports task start,
  status, bounded events, active-turn messages, and exact-turn stop.
- Added the responsive Emerald Operations shell to the Next.js preview, with
  honest Home, Agents, Tasks, and Runs route frames built from shared React
  components and Tailwind-backed styles.
- Added the 216 px desktop sidebar, 76 px compact rail, accessible mobile
  drawer, saved Standard and High Contrast modes, source-owned icons, and the
  existing Emerald mark.

### Changed
- Made fresh roots use an empty embedded Agent authority and made existing roots
  complete the explicit convergence before normal startup.
- Kept schema-5 compatible-root export working by synthesizing the retired
  standalone registry only inside the downgrade artifact.
- Kept active Runs ahead of terminal history in the bounded 50-Run workspace.
- Required post-message and post-response runtime readback to match the exact
  canonical Run, Task, Agent, and runtime identity.
- Kept layout responsive through CSS while using a small browser runtime for
  drawer focus, contrast preferences, and the existing bounded bridge-health
  check. Initial content never waits for bridge health.
- Published four validated static route shells without the general Next.js
  hydration runtime. The optimized web mark reduced total transfer to about
  33 KB; three desktop and three mobile Lighthouse runs each scored
  100/100/100/100 with zero TBT and zero practical layout shift.

### Safety
- Agent rows, private bindings, and their authority receipt now commit in one
  transaction. After cutover, live paths ignore the old registry file and never
  fall back to or dual-write it.
- Kept Run status, runtime, and controls authoritative when Agent display data
  is unavailable, malformed, or stale. Legacy heartbeat data is never joined.
- Kept Codex credentials, configuration, account details, thread IDs, turn IDs,
  commands, paths, and raw tool payloads out of browser responses. Stop results
  are reported only after exact SQLite Run reconciliation.
- Kept Agent, Task, Run, SQLite, Hermes, filesystem, and credential authority
  in Python. Unconnected routes show named foundation states instead of sample
  operational data.

## 2026-08-21

### Added
- Added an opt-in Node 24.19 source preview with a production standalone
  Next.js/React/TypeScript/Tailwind foundation shell and one command that
  supervises the public Node gateway plus a private Python Local Bridge.
- Added fixed token-bound bridge health and redacted same-origin BFF routes,
  exact Node/npm dependency locking, focused boundary and lifecycle tests, and
  a dedicated CI quality gate for frozen install, build, audit, six locked
  Lighthouse audits on Chrome for Testing 152.0.7923.0, browser smoke,
  bounded failure evidence, and sibling-process cleanup.

### Changed
- Kept the noninteractive foundation shell authored by the App Router while
  publishing a validated no-hydration production prerender. The fixed live
  bridge-status script reduced the simulated-mobile transfer from about 149 KB
  to 8.9 KB and produced three desktop plus three mobile Lighthouse runs at
  100/100/100/100 with zero TBT and zero CLS.
- Closed Pivot Slice 1C-D after stabilizing the Home focus-list viewport during
  Task hydration. The exact repeatable Lighthouse 100/100/100/100 replacement
  gate now applies to the proposed 2A frontend foundation, while the legacy
  surface retains explicit performance budgets and 100-point accessibility,
  best-practices, and SEO gates.
- Replaced Home's delayed sequential script loader with parser-discovered,
  ordered `defer` scripts. Core and application assets now download during HTML
  parsing, preserve execution order and boot failure recovery, and improve the
  measured local mobile LCP.
- Prioritized Home task focus, project context, and health rendering ahead of
  deferred Hermes/Console requests. Deferred requests now settle independently,
  preserve bounded error states, and cannot block a subsequent navigation refresh.
- Began Pivot Slice 1C-D by removing live server Task workflows from the
  generic JSON read/write call graph. Runtime Task snapshots and mutations now
  use explicit SQLite-authority helpers; the legacy `tasks.json` document
  remains only for packaged seed, migration, offline export/downgrade, and
  compatibility/recovery workflows.
- Removed `tasks.json` from the generic project-owned write allowlist without
  changing the explicit stopped-server export path or public Task responses.
- Hardened static browser delivery with deterministic gzip responses, versioned
  immutable cache headers for fingerprinted assets, and a single shared
  versioned logo URL.
- Added a first-paint Home focus and schedule state, stable mobile panel
  geometry, and deferred ordered loading for the core and application bundles.

### Documentation
- Split the active frontend pivot into 2A-A Node Runtime Foundation and the
  proposed 2A-B Emerald Operations shell, with the installed Python dashboard
  retained as the compatibility surface.
- Recorded Slices 1C-C and 1C-D as complete and 2A as the proposed next pivot
  slice in the implementation roadmap and data-layout contract.
- Added request-boundary, Home UI, and browser-bootstrap regression coverage for
  the performance hardening contract.

### Safety
- Kept SQLite, orchestration, Hermes, filesystem, credentials, and runtime
  authority in Python. The preview is loopback-only, exposes no generic proxy,
  keeps its bridge token process-ephemeral, and stops the surviving child when
  either supervised process exits.

## 2026-08-18

### Added
- Added schema-7 authoritative Runs, append-only normalized AgentEvents,
  idempotent dispatch reservations, durable per-Task revision heads, CAS
  reconciliation leases, and fixed per-Run/global retention metadata.
- Added runtime-neutral Task dispatch plus versioned Run detail, paginated Run
  list, and cursor-based AgentEvent APIs. Runtime references, binding digests,
  raw adapter payloads, and private event content stay server-side.
- Added an owner-private durable registry for canonical Mentat Agents and
  separate one-to-one runtime configurations, with Hermes as the only accepted
  runtime in this slice. The registry uses its own versioned SQLite file so the
  prior Console database schema remains usable during rollback.
- Added runtime-neutral create/list API operations at
  `/api/orchestration/agents` without changing the legacy `/api/agents`
  heartbeat surface.
- Added schema-5 canonical Task tables to the existing private
  `mentat.sqlite3`, with ordered tags/dependencies, bounded planning metadata,
  deterministic reconstruction, and optimistic revision conflicts.
- Added `mentat task-migration`, a bounded read-only preview that binds the
  exact `tasks.json` source and destination state without performing a cutover.
- Added schema-6 Task authority receipts and an atomic one-time startup cutover
  that imports the exact legacy Task collection and makes SQLite the sole live
  Task source, including for an intentionally empty collection.
- Added `mentat task-export`, an offline preview/confirmation workflow for
  producing an exact `tasks.json` downgrade snapshot without creating a second
  live authority; `--compatible-root` creates a validated schema-5 sibling data
  root with empty Task tables and exported JSON as the old build's sole Task
  authority while preserving the source.
  Compatible-root export fails closed for active remote-Hermes selection rather
  than silently creating a sibling pointed at local Hermes, and expected
  private capture/recovery failures now return bounded CLI results.
  Exact-limit exports no longer gain an optional newline, and compatible-root
  publication now fsyncs its staged directory hierarchy and final parent rename
  with phase-aware partial-failure reporting.
  Final export verification compares exact bytes without stripping whitespace;
  Windows compatible-root publication now uses missing-only
  `MOVEFILE_WRITE_THROUGH` semantics.

### Changed
- Agent Console persistence now cuts over once from validated legacy history
  and thereafter reads and writes SQLite only. The Hermes compatibility bridge
  reuses preallocated Mentat Run IDs; restart ambiguity becomes durable
  `unknown` state and is never automatically resubmitted. Direct active legacy
  Console Runs become `interrupted`, while adapters with durable private runtime
  references remain reconcilable.
- Dispatch claim and outcome commits now atomically revalidate Task, Agent, Run,
  runtime, and state revisions. Reconciliation is forward-only and uses a
  durable runtime-event cursor that survives event retention and bounded paging.
- Private backup/restore now accepts schemas 4, 5, 6, and 7, derives schema-7
  Run history and attachment reachability from SQLite, semantically validates
  Run/Event/dispatch state, and still emits an exact schema-5 compatible root.
- Routed all existing Task creation, editing, deletion, planning, recurrence,
  calendar, search, delegation, artifact, and webhook refresh workflows through
  the canonical SQLite repository without changing their public payloads.
- Historical sparse Tasks, timezone-naive timestamps, and legacy delegation
  links receive deterministic canonical defaults during import; stale
  `tasks.json` is retained but ignored after cutover.

### Documentation
- Added a canonical multi-agent pivot implementation plan that separates
  complete, active, proposed, provisional, and deferred slices and records the
  current resume point.
- Added the SQLite orchestration system-design reference and documented the
  no-dual-authority Task migration sequence and later unified-database target.

### Safety
- Agent creation is atomic and serialized with private backup/restore. Public
  projections omit adapter-owned runtime references, and the registry stores no
  credentials or arbitrary runtime options. A transactional 128-Agent ceiling
  keeps create/list and recovery behavior bounded.
- Backup format 3 includes the registry with relationship and semantic
  validation; legacy format-2 backups remain restorable as an empty registry.
- Private Console backup/restore snapshots now retain Task rows, report Task
  counts, and reject malformed Task documents or broken dependency references.
- Task rows and the authority receipt commit together. No post-cutover runtime
  path reads, writes, shadows, synchronizes, or falls back to `tasks.json`.
- The registry does not auto-import or mutate Hermes profiles, dispatch work,
  add concurrency, or change current Console behavior.

## 2026-08-17

### Added
- Introduced the first runtime-neutral Mentat contracts for Agent, Task, Run,
  AgentEvent, RuntimeContext, capabilities, and AgentRuntime.
- Registered Hermes as the first runtime adapter. Existing Console transport
  and compatibility routes now cross the registry before delegating to the
  unchanged capability-gated Hermes handlers.
- Added a bounded Hermes-to-Mentat run/event projection that keeps runtime
  references and event payload data out of the normalized domain model.

### Changed
- Began the documented multi-agent strangler migration. Mentat Agent identity
  is now distinct from runtime identity; the legacy browser `agent_id` profile
  alias remains temporarily for compatibility.
- Completed the Hermes stock-compatibility and fork audit after native-event
  migration. Every polling, telemetry, and custom remote contract now has an
  explicit stock-equivalent, partial, custom-required, or Mentat-local class.
- Retained the 30-second browser refresh, 60-second server reconciliation, and
  optional private local Console telemetry because webhook delivery is best
  effort and the required production soak evidence does not yet exist.

### Safety
- The new runtime seam does not add concurrency, a second runtime, credentials,
  durable Agent persistence, or new mutation authority. Existing Hermes locks,
  confirmation, verification, polling, and reconciliation behaviors are retained.
- Webhooks remain payload-discarding freshness hints. They do not become token,
  tool, model, approval, continuation, provider, artifact, Kanban, cron, or
  command authority merely because stock Hermes exposes a related event or API.
- Related stock endpoints do not weaken Mentat's exact capability validators.
  Unsupported hosts continue to fail closed or show the documented degraded
  behavior until an upstream equivalent or separately approved removal exists.

## 2026-08-14

### Added
- Stock Hermes session-finalize/reset, post-API/error, post-tool, and Kanban
  task/worker/dispatcher events can now wake Mentat's existing authoritative
  read adapters without persisting their event-specific payload fields.
- Open dashboards receive bounded, projection-only same-origin refresh hints
  after successful readbacks while retaining polling and reconciliation as
  compatibility and recovery paths.
- A version-pinned source validator now proves the Hermes v2026.8.13 event and
  dispatcher/worker outbound-hook registration topology used by this migration.
- Private database schema version 4 expands durable webhook replay protection
  to every qualified native event while preserving existing replay rows.
- Settings now reports signed local Hermes webhook health as Off, Ready,
  Receiving, or Degraded, with bounded event, refresh, and reconciliation
  evidence.
- Operators can copy a placeholder-only stock-Hermes hook template and run one
  fixed signed loopback probe without giving the browser access to the shared
  secret.
- Stock Hermes 0.20.1 lifecycle webhooks now have a reproducible local
  qualification harness covering real CLI and Gateway turns, all four
  allowlisted lifecycle events, safe mode, rollback, restart replay, dropped
  hints, out-of-order delivery, privacy canaries, and event storms.

### Changed
- Webhook replay protection now survives Mentat restarts in owner-only SQLite,
  expires through bounded 24-hour cleanup, and admits traffic through a
  per-binding token bucket before scheduling authoritative refreshes.
- Native-event normalization now retains only the fixed routing envelope;
  lifecycle completion, interruption, platform, and every other event-specific
  payload field are discarded before refresh scheduling.

### Safety
- Webhook health and probe responses omit secret references, signatures,
  delivery and session identifiers, payloads, profile identifiers, paths, and
  internal exception text. Webhooks remain refresh wakeups; authoritative
  read-back and periodic reconciliation remain the correctness boundary.
- Duplicate claims remain atomic under concurrent receiver threads, raw
  delivery identifiers never enter SQLite, and a queue rejection rolls its
  claim back atomically before returning retryable 503. Rate-limited wakeups are
  intentionally best-effort 429 responses and converge through reconciliation.
- A2A, grounded citations, deliverable artifacts, and voice now have explicit
  Hermes 0.20 adoption decisions. None expands the webhook receiver: Mentat
  keeps A2A native-only, treats citations as response Markdown, retains its
  run-owned/authenticated artifact boundaries instead of parsing response
  paths, and defers voice until browser-audio and verified-interruption
  contracts exist.

## 2026-08-02

### Added
- Native macOS release builds now cover Apple Silicon and Intel independently.
  Apple Silicon is the recommended/default package, while both architectures
  retain the complete signed, notarized, stapled, Gatekeeper-assessed,
  install-smoked, and immutable-release path.

### Safety
- Protected and ordinary native workflows verify the fixed runner mapping and
  every bundled Mach-O architecture before signing or publishing. Release
  assembly, checksums, promotion, and recovery now fail closed unless both
  exact macOS packages are present.

## 2026-07-31

### Fixed
- The empty Projects view now points new users to Mentat's existing project
  creator and makes clear that planning does not require Hermes, replacing
  obsolete direct-file guidance without adding a duplicate action.
- Release-candidate notes now send invited testers to a short, channel-specific
  first-launch path instead of the full maintainer rehearsal; recovery and
  rollback drills remain in the rehearsal guide.
- Apple notarization waits are now bounded below GitHub's hard job limit, so a
  stalled request fails clearly while protected signing cleanup still runs.
  A separately completed upload step durably retains the original submission ID
  before the poll-only step retries temporary status connection failures without
  uploading a duplicate; maintainer guidance still prevents resubmission while
  Apple continues processing the original request.
- Compact icon-only navigation now shows the existing menu name on mouse hover
  and keyboard focus; phones continue to reveal the full labels in the drawer.
- Retired the unused Classic interface choice, migrated any saved layout back to
  Emerald, and kept every Theme Studio preview card the same size.
- Text fields, search controls, and dropdowns now highlight their visible border
  on focus without drawing a second outline or glow outside the control.
- The phone navigation Close button and Hermes connection control now match
  the shared 44px interaction target used by adjacent mobile controls.
- Ensured the shared 44px phone control target wins the final theme cascade for
  Today filters, Agent Console controls, and Settings selectors in Emerald.
- Phone layouts now use the same 44px interaction height for planner filters,
  Agent Console and managed-agent selectors, the Console prompt, Settings
  selectors, and the Today schedule link. Settings keeps its compact theme
  selector on phones without repeating the full theme-button grid below it.
- Installed CLI setup now reports the exact browser-opening launch command and
  makes clear that Mentat's planning features work without Hermes.
- Controls and panels marked `hidden` now stay out of layout even when a
  component assigns its own flex, grid, or block display mode. This removes
  leaked empty-state actions such as Clear project.
- Task creation and editing now provide one immediately reachable Cancel action
  in the form heading. The duplicate inspector-header Cancel is removed, and
  Back to queue stays hidden while an editor is active.

## 2026-07-30

### Fixed
- Remote Hermes session search now omits individual messages that cannot cross
  Mentat's browser privacy boundary instead of making every query unavailable.
  Safe matches in the same bounded recent-session window remain searchable,
  and the coverage note reports only how many messages and sessions were
  privacy-filtered.
- Session History now keeps current-list sessions in its selector when message
  content matches even if the title does not. Search progress and the exact
  title-plus-message match count are announced without adding visible layout
  text.

### Safety
- Schema, pagination, connection binding, capability, transport, and final
  revalidation failures still discard the complete search. Filtered message
  content, filter reasons, paths, credentials, endpoints, and upstream session
  identifiers never reach the browser, and strict transcript reads are
  unchanged.

## 2026-07-29

### Added
- Cron Monitor and the Home scheduled-work count now read active and paused
  jobs from the selected remote Hermes host when it advertises the complete
  read-only jobs contract.
- Remote delegated Kanban tasks can now bring supported generated text, code,
  and raster-image files back into Mentat through an authenticated,
  capability-gated artifact contract.
- Generated files appear on Home when agent work needs attention and in the
  full task view. Home renders local work first, then checks a bounded set of
  current remote work in the background.
- Older remote task links can be reconnected only after Mentat verifies the
  exact task, board, agent, title, and live remote revision and the user
  confirms the match.

### Changed
- Search fields now use one outside focus ring on the visible search box
  without also highlighting the inner editable area. Session History search
  now aligns with the adjacent session selector across desktop layouts and
  preserves matched control heights on narrow layouts.
- Agent Console keeps its Ready status and green indicator without a bordered
  or filled status container.
- Remote Agent Console turns now receive exact context used and total context
  window values from compatible Hermes Runs instead of showing them as
  unavailable.
- Home now keeps **Open today schedule** on a stable row below **Quick add**
  and **Completed work**, including when either section expands.
- Agent Console now keeps its always-visible transcript between the Agent /
  Provider / Model selector row and the prompt composer.
- Removed the redundant runtime banner and repeated provider/model status text.
  Verified switches continue to appear as transcript notices.
- Runtime reconciliation remains available only when needed through a compact
  `Retry check` action alongside New session and Show tools.

### Safety
- Remote cron reads use one fixed, bearer-authenticated endpoint and keep only
  the small set of fields Mentat already displays. Job prompts, delivery
  details, origins, work directories, execution output, paths, and raw
  upstream data never reach the browser. Cron changes and run controls remain
  disabled.
- Artifact downloads are limited to 10 files, 100 MiB per file, and 250 MiB
  per task. Hermes and Mentat both verify type, size, digest, path containment,
  and recognizable-secret patterns before publishing a local download.
- Remote paths, storage keys, digests, bearer credentials, and upstream
  artifact IDs never reach the browser. Files are served from private
  content-addressed storage through opaque same-origin routes.
- Cleartext remote Hermes endpoints require a literal loopback IP. Hostnames
  and non-loopback remotes require verified HTTPS.
- Raster artifacts must decode as a real PNG, JPEG, GIF, or WebP within fixed
  frame and pixel limits. Hermes and Mentat re-encode metadata-free canonical
  snapshots, so hidden chunks, metadata, appended payloads, and the original
  container are not published; delegated images stay download-only in task
  surfaces.

## 2026-07-28

### Added
- Added capability-gated provider/model switching for served profiles on a
  remote Hermes host through its exact authenticated version-one runtime read
  and switch endpoints.
- Agent Console now exposes validated remote provider/model choices through
  the existing selectors when every revision, idempotency, and active-run
  safety capability is advertised.
- Agent Console now keeps Agent, Provider, and Model in one runtime row above
  the prompt. Agent selection re-reads Hermes, while provider or model
  selection automatically runs the bound preview and verified switch without a
  separate review-dialog click. Provider changes use Hermes's first listed
  model and verified changes appear as UI-only transcript notices.
- Detailed tool events now start hidden. A Show tools / Hide tools control
  reveals them, while an outstanding tool call remains visible through an
  animated Agent is using tools indicator outside collapsed history. Its live
  announcement changes only when selected-agent tool activity starts or ends.
- Agent Console keeps Hermes's confirmed runtime separate from selectable
  inventory and pending targets. If a failed switch cannot be reconciled with
  a fresh read, it clears stale picker data and blocks execution until an
  explicit runtime retry succeeds.
- Delayed runtime results cannot cross transport bindings, blank/error refresh
  payloads cannot unlock execution, and Context Pack or attachment staging is
  serialized with provider/model switching.

### Safety
- Remote preview binds the selected connection, profile, current and target
  runtime pairs, and upstream revision. Apply holds the existing
  connection/profile locks, excludes an active run for the target profile,
  re-reads state, and sends one server-generated idempotency key without
  retrying an uncertain mutation.
- Mentat fresh-reads the resulting runtime. A verified mismatch triggers at
  most one revision-bound rollback and one rollback verification only when the
  fresh state retains the revision acknowledged by the switch response. A
  later revision is treated as a concurrent change and is never overwritten;
  malformed, private-shaped, stale, unavailable, unserved, active, and
  unverifiable results fail closed with bounded public errors. Older or partial
  hosts remain read-only, and local switching behavior is unchanged.

## 2026-07-26

### Added
- Added setup-wizard and installed CLI workflows for configuring, testing, and
  selecting local Hermes or one remembered remote endpoint.
- Added `mentat connection status`, `test`, `use`, and `configure-remote` with
  interactive confirmation and exact two-step non-interactive confirmation.

### Changed
- Remote connection records now keep only a credential-source reference. API
  keys resolve from a named environment variable or owner-only env file.
- Existing schema-v1 embedded remote keys migrate to a separate owner-only
  private env file while retaining the selected connection.

### Safety
- CLI connection mutations refuse to run while Mentat is active, remote
  activation probes authenticated readiness/capabilities before commit, failed
  operations restore the prior selection, and browser connection requests no
  longer accept API-key values.
- Server startup and offline connection changes now share a cross-process
  reservation, closing startup races and preventing live schema migration.
- `mentat connection test local` now verifies that the supported Hermes CLI can
  execute instead of treating a saved local label as proof of readiness.

## 2026-07-25

### Added
- Added capability-gated, cursor-based replay for remote Hermes Runs events,
  exact pending approval/clarification recovery from run status, and effective
  provider/model runtime events.
- Added a complete authenticated read-only remote profile runtime inventory so
  Agent Console can show the selected profile's current provider and model.

### Changed
- Remote approval and clarification waits now keep the normal SSE connection
  open. Multiple interactive pauses resume on the same run worker and stream;
  a genuine interruption reconnects automatically from the last verified
  cursor without resubmitting the run.
- Agent Console clears stale runtime values while changing agents, rejects
  out-of-order refresh responses, and refreshes provider/model identity after
  relevant run, response, session, and connection lifecycle events. Remote
  selectors show the current values but remain disabled.

### Safety
- Replay journals and subscriber queues are count- and byte-bounded, sequenced,
  normalized to a public allowlist, and process-local. Raw tool previews and
  reasoning bodies are omitted. Invalid, ahead, expired, duplicated, or gapped
  event cursors fail closed.
- Pending actions remain bound to the exact request ID, and provider/model
  payloads reject URLs, paths, secret-shaped identifiers, endpoint reflection,
  and malformed or partial inventories.

## 2026-07-24

### Changed
- Updated protected Windows release signing to Azure Artifact Signing with
  short-lived GitHub OIDC, and added a concise Apple/Azure maintainer setup
  guide for the first signed release candidate.

### Fixed
- Remote Console runs now retain a safe connection-bound session alias, so a
  fresh completed run can continue in the same Hermes session without exposing
  the upstream session ID.
- Clarification runs now accept Hermes' advertised
  `waiting_for_clarification` status instead of failing after the question
  appears.
- Supported remote image requests now use a dedicated bounded outbound limit
  instead of the smaller response-size limit, and deterministic request
  rejections no longer claim that a run may have started.
- Kanban follow-up confirmations now bind persisted Mentat task state and the
  exact remote revision without including a newly generated sync timestamp.
- Browser smoke gives Chrome a bounded startup window on slower CI runners and
  waits for browser shutdown before removing its private profile directory.

### Verified
- Completed the mandatory maintained-runtime matrix against Hermes `0.19.0`
  over authenticated, certificate-verified HTTPS, including Console
  interactions, continuation, sessions/search, profiles, skills/toolsets,
  Context Packs, images, stopping, cancellation races, and revision-bound
  Kanban creation and result acceptance.

## 2026-07-21

### Added
- Added a protected public-beta promotion path that verifies and republishes
  the immutable tested RC identity, GitHub asset digests, and attestation;
  preserves pre-tag recovery evidence; and requires a closed public Milestone 7
  exit summary with checked, candidate-bound attestations.
- Added a concise limited-beta tester checklist, privacy-safe structured
  feedback form, and maintainer cohort runbook without claiming external
  results or storing participant data in Git.

## 2026-07-20

### Added
- Added deterministic release-candidate checksums, manifest, and release notes,
  plus a short clean-install, upgrade, backup, restore, rollback, and
  uninstall-preservation rehearsal checklist.
- Added a protected Python package job and final prerelease assembly gate beside
  the signed macOS and Windows artifact jobs.
- Added public beta security, privacy, support, contribution, conduct, and issue
  guidance, including a private vulnerability-reporting path and clear
  pre-install platform and support expectations.
- Added a user-initiated redacted diagnostics ZIP and a compact Settings help
  area with the Mentat version, docs, bug-reporting, and diagnostics actions.
- Added read-only remote message search across the same bounded 12 recent
  sessions shown in Agents. Matches open the existing transcript through
  private Mentat aliases, and the UI explains when the session limit was
  reached or compacted history was outside the search window.
- Added a read-only Hermes Capabilities view in Settings for remote skills and
  toolsets. Mentat uses only the exact authenticated endpoints advertised by
  Hermes and keeps local mode unchanged.
- Added bounded remote Context Pack text for Agent Console. One short-lived
  opaque grant binds the selected connection, current pack revision, and exact
  private snapshots before Mentat sends path-free text to Hermes Runs.
- Added capability-gated read-only remote session history using Hermes' exact
  list, detail, and message endpoints. The existing Sessions UI can show a
  bounded recent list, transcript, and replay while local SQLite behavior stays
  unchanged in local mode.
- Added capability-gated remote Agent Console turns for the selected Hermes
  host's default profile, including fixed run submission, bounded SSE progress,
  status reconciliation, usage metadata, and remote cancellation.
- Added a binding-aware Hermes Console transport boundary that keeps the local
  CLI launch contract intact and gives later remote execution one typed entry
  point.
- Added validated transport mode and opaque connection binding metadata to new
  and retained Console run summaries, with safe defaults for older history.

### Safety
- Diagnostics are generated in memory from fixed version, platform-category,
  install-type, and health-status fields. They never collect logs, environment
  variables, credentials, endpoints, personal content, local paths, hostnames,
  usernames, or blob identifiers.
- Remote message search reads only the exact advertised session list/message
  endpoints, returns at most 20 escaped user/assistant snippets, and exposes no
  upstream session IDs. Any failed session read or changed connection discards
  all matches; path-shaped or credential-shaped public text and partial message
  envelopes fail closed, while syntactically public credential-free web URLs,
  numeric dates/fractions, `A/B` abbreviations, and safe text-only multimodal
  content remain searchable. Alternate numeric loopback, non-unicast or local
  hosts, userinfo, backslash hybrids, private query values, and private-key
  headers fail closed, as do special-use DNS and nested/adjacent URL-path
  hybrids. List limits, compaction, and match truncation are explicit.
- Remote capability inventory is connection-bound, size-limited, allowlisted,
  path-free, and escaped in the browser. Raw responses, descriptions, skill
  contents, tool names, credentials, and partial inventories are never exposed.
- Remote Context Pack requests use generic context labels and fixed item,
  total-context, and complete-prompt limits. Changed, expired, replayed, or
  mismatched grants fail before submission. Direct files and artifacts remain
  unavailable; supported runtimes may accept only validated, bounded image
  data URLs for the stoppable Runs lifecycle.
- Remote session identifiers remain process-private behind random aliases bound
  to the selected connection. Mentat allowlists and bounds public metadata,
  returns only user/assistant conversation text, labels compressed
  latest-segment history as partial, and rejects stale aliases, changed
  capabilities, changed message identity, private transport reflection,
  malformed pagination, or uncertain identity.
- Added verified, exact remote continuation, profile inventory, approval,
  clarification, inline-image, and revisioned Kanban contracts for runtimes
  that advertise the complete supported capability set.
- Remote approval and clarification replies now require the verified exact
  request-binding contracts. Runs wait for a verified operator response, then
  resume without submitting a second prompt; unsupported or malformed requests
  still stop safely.
- Remote runs now require the exact advertised Runs API endpoints, remain bound
  to one opaque connection identity, never retry submission, and issue at most
  one stop attempt. Interrupted streams reconcile through status.
- Graceful shutdown performs bounded remote stop/read-back. Abrupt process
  death is reported as an interrupted partial run; upstream run IDs are not
  persisted in this slice.
- Selected remote mode now fails closed instead of inspecting or launching the
  local Hermes CLI. Connection changes are blocked during active runs, bindings
  are rechecked before queue and launch, and private launch errors or failed
  child-process output stay out of browser and retained-history payloads.

## 2026-07-19

### Added
- Added the Milestone 2A remote Hermes foundation: one owner-only local/remote
  connection record, exact preview and confirmation, binding rotation when
  connection authority changes, and a fixed-path server-only discovery client.
- Added bounded public-health, authenticated detailed-health, and capability
  discovery with verified TLS, no redirects or ambient proxy behavior, strict
  response limits, schema validation, and secret-free browser summaries.
- Added loopback-only routes to inspect, preview, select, and test the active
  connection. Existing Console and Hermes behavior remains local until the
  transport adapter lands.

### Changed
- Simplified the README into a quick, friendly first-user setup guide and moved
  advanced implementation detail to the focused architecture and roadmap docs.

### Safety
- Keeps the remote endpoint and API key out of tracked files, ordinary backups,
  logs, diagnostics, and browser responses. Failed probes do not change the
  active selection; uncertain commits roll back exactly or report a bounded
  partial failure.

## 2026-07-18

### Added
- Completed Milestone 1F with an installed-layout integration drill that creates
  a verified pre-upgrade backup, replaces immutable application trees with
  changed packaged seeds, removes only the application tree, and reconnects a
  reinstall without changing durable JSON or retained private Console state.
- Moved retained Agent Console history, SQLite metadata, and content-addressed
  blobs to owner-only durable `private/console` storage while keeping uploads,
  exports, execution inputs, and workspace/artifact snapshots in ephemeral
  runtime storage.
- Added exact preview-confirm migration for legacy runtime Console state with a
  shared cross-process lock, SQLite backup semantics, source preservation,
  reservation-first recovery, verified receipt-last completion, and startup
  refusal for incomplete or conflicting state.
- Extended ordinary backup to version 2 with canonical retained history, a
  supported-schema WAL-safe SQLite snapshot filtered to retained run references,
  and exactly referenced ready blobs. Restore now exchanges the private unit
  through verified old/new states and retains version-1 JSON-only compatibility.
- Added Milestone 1E-A's deterministic, bounded, owner-only general backup
  format for the fixed nine-document durable operator JSON inventory.
- Added read-only restore preview, state-bound confirmation, forward refusal,
  pre-restore recovery backup, exact atomic document replacement, verified
  interruption resume, confirmed orphan-temporary cleanup, and startup refusal
  for incomplete or ambiguous restore state.
- Added explicit source-checkout CLI modes for backup creation and restore
  preview/confirmation while keeping other private/credential state,
  runtime/cache/log/browser/external state, nested backups, and the later
  installed CLI out of this bounded format.
- Completed Milestone 1D with a fixed owner-only durable-JSON schema manifest,
  current metadata for clean seed-only installs, explicit backed-up version-0
  bootstrap, interruption-safe retry, and distinct forward-version refusal.
- Added schema preview/confirmation, manifest/backup integrity, clean/repeat,
  stale-token, interruption, substitution, normal-write serialization, tamper,
  and newer-version coverage.
- Added pre-write current/newer schema refusal, durable clean-initialization
  provenance, exact orphan-temporary reconciliation, canonical resume-backup
  binding, strict integer semantics, bounded malformed-artifact handling,
  pinned descriptor-relative schema writes, seed/target containment refusal,
  and reentrant global-before-file mutation locking.
- Reconciles exact pre-link and same-inode post-link reservation, seed, backup,
  and manifest publication states; rejects multiple recovery temporaries; and
  preserves full required-directory hardening for current-schema startup.
- Pins required-directory hardening and ordinary durable JSON I/O to the locked
  root descriptor, refuses all recovery on newer schemas, rejects contextual
  reserved-namespace lookalikes, and repairs a missing empty fresh backup
  directory without weakening migrated-backup evidence.
- Preserves the configured data-root spelling through component-by-component
  no-follow locking, including the server write handoff; binds recovery
  inventory, validation, deletion, and verification to one pinned root; gives
  cross-category invalid artifacts global precedence; and reports safely read
  newer metadata before any older recovery classification.
- Keeps component validation and pinned JSON I/O active when the source
  development override omits only the on-disk lock artifact; finalizes fresh
  schema state inside the initializer lock with a final root-identity check;
  and verifies complete recovery inventory and promoted-final identity again
  after temporary deletion before claiming reconciliation.
- Binds startup handoff to the guarded root's device/file identity, rejects
  mixed nested lock-mode escalation, validates durable JSON file objects and
  bounded top-level shapes before successful writes, and rechecks all nine
  confirmation/seed bytes at migration, recovery, and fresh terminal success.
- Routes product reads through the pinned bounded file boundary, refuses
  missing installed durable documents, hardens parent permissions only through
  the pinned descriptor, binds temporary and committed bytes/inodes, cleans all
  precommit failures, and validates terminal manifest/backup/data evidence
  entirely through retained root/child descriptors.
- Completed Milestone 1C with an explicit CLI preview/confirmation workflow for
  the fixed legacy durable-JSON inventory, including a validated versioned ZIP,
  locked revalidation, missing-only atomic publication, interruption-safe
  resume, exact verification, and a completion receipt checked at startup.
- Added stale-token, conflict, source-change, destination-race, backup ordering,
  corruption, interruption/resume, receipt, CLI-isolation, and source-
  preservation coverage.
- Completed Milestone 1B with a standard-library, cross-process-locked data-root
  initializer. Clean installed layouts create owner-only durable, private,
  runtime, backup, cache, log, and config boundaries and copy only missing
  validated seeds through synced same-directory temporary files and atomic
  no-replace promotion.
- Added first-run, repeat-run, mixed existing/missing, legacy/conflict,
  permission, interruption-recovery, destination-race, startup-ordering, and
  two-process serialization coverage.

### Safety
- Coordinates ordinary durable JSON writes and schema migration through the
  process-reentrant shared cross-process lock, binds confirmation to live bytes and the exact
  target, publishes backup evidence before metadata, keeps browser-visible JSON
  shapes unchanged, and never performs a downgrade or silent existing-root
  upgrade.
- Keeps migration output path/content/hash-free, preserves the legacy source,
  refuses unknown, symbolic-linked, or hard-linked inputs and changed partial
  state, binds confirmation to exact root spellings and an empty initial target,
  pins receipt validation against root substitution, secures every required
  completed-migration directory boundary before startup, never overwrites a
  destination, preserves owner-only mode before ordinary atomic-write commit,
  tolerates only exact safe orphan writer temporaries after completion, and
  leaves private-state movement and general backup/restore outside this slice.
- Revalidates the complete bounded preflight after acquiring the initialization
  lock, never replaces an existing operator destination, keeps `--print-config`
  side-effect-free, treats the tracked source layout as a no-op development
  override, and fails closed before seed copying when legacy, invalid, linked,
  conflicting, or unverifiable state is present.
- The Milestone 1B initializer kept migration, schema evolution,
  backup/restore, private/runtime data moves, remote credentials, packaging,
  and installers outside that initializer slice.

## 2026-07-17

### Added
- Added the early GitHub Actions guardrail for pull requests and `main`, with
  Python compilation, JavaScript syntax checks, and the complete unittest suite
  across macOS, Windows, and Ubuntu on Python 3.11 through 3.13. This narrow
  guardrail does not yet add packaging, native installers, browser release
  gates, dependency scanning, or branch-protection configuration.
- Defined the Milestone 1A data-layout contract, including the complete current
  mutable-path inventory, target durable/private/runtime/backup/cache/log/config
  classes, platform defaults, override precedence, missing-only seed behavior,
  fail-closed migration/schema rules, and secret exclusions.
- Added the Milestone 1B-A standard-library data-root resolver and bounded
  read-only preflight. Config-less loads select the approved macOS, Windows, or
  Linux/XDG root; explicit CLI, current environment, legacy environment, and
  TOML inputs retain exact precedence and report a safe source label. Preflight
  validates only the fixed seed set, enforces a 16 MiB per-document ceiling and
  current top-level shapes, and fails closed on symlink/reparse, legacy, or
  conflicting state without creating or modifying files. Config-less normal
  startup is blocked before lifecycle cleanup or writes until the writable
  initializer lands; print-config remains side-effect-free.

### Changed
- Closed the remaining Milestone 0 release-contract decisions for the beta
  audience, supported and preview platforms, Python versions, manual updates,
  absent-by-default telemetry, initial version, severity levels, and feedback
  policy.
- Made signed native installers the required primary public-beta path on macOS
  and Windows, with macOS notarization and `pipx` retained as the supported
  advanced/fallback and Linux preview path. Installer implementation remains a
  future packaging milestone.
- Moved the roadmap forward to the early cross-platform CI guardrail followed
  by the Milestone 1A mutable-path inventory and data-layout contract.

### Fixed
- Made Agent Console binary snapshots preserve all bytes on Windows and added
  pinned IANA timezone data for Windows calendar and recurrence behavior.
- Removed test-suite dependencies on a developer's local Hermes profiles and
  Obsidian vault, and made the Hermes-home assertion platform-correct.

## 2026-07-16

### Added
- Adopted the MIT License and documented the approved remote-Hermes portion of
  the public-beta contract without closing the remaining owner decisions.
- Added the remote Hermes capability matrix, security boundary, upstream
  blockers, and ordered implementation plan for connecting local Mentat to one
  operator-managed HTTPS endpoint.

### Changed
- Made Console, sessions/runs, approvals/clarification/cancellation/stopping,
  skills/toolsets, Kanban, and read-only profile discovery the mandatory
  remote-beta capability set.
- Reordered the Road to Beta to put secure remote Hermes parity before public
  trust work, release rehearsal, and external testing.
- Aligned roadmap slices with persistent evidence logs, two independent
  adversarial reviews, and explicitly approved ready pull requests.

## 2026-07-15

### Changed
- Formalized the Road to Beta as a slice-based workflow using one bounded
  GitHub issue and draft pull request at a time, explicit acceptance evidence,
  private Obsidian learnings, and an early cross-platform CI guardrail before
  data-root implementation begins.

## 2026-07-14

### Added
- Added an ordered Road to Beta covering the release contract, durable user
  data, packaging and CLI work, CI, public trust and support, release rehearsal,
  an external tester cohort, and final public-beta acceptance criteria.
- Added Operator Week, a full Sunday-through-Saturday calendar with exact-week
  navigation, all-day and hourly lanes, overlap-aware appointments, a current-
  time marker, and a responsive event inspector that retains Mentat task-link
  actions without writing to Google Calendar.
- Added a clearly labeled client-only preview week for disconnected calendars,
  plus validated timezone-aware week queries and DST-safe Google Calendar
  windows for previous, current, and future weeks.
- Added reusable Context Packs for combining standard instructions, validated
  Obsidian notes, and safe workspace-file references. Packs can stage current
  private snapshots for Agent Console or resolve bounded text into an exact
  Hermes Kanban delegation preview.
- Added five dark editor-inspired themes—Tokyo Night, Gruvbox Dark, Dracula,
  One Dark, and Solarized Dark—and five light themes—GitHub Light, Gruvbox
  Light, Solarized Light, Catppuccin Latte, and Rosé Pine Dawn.
- Grouped Theme Studio choices into dark and light sections while preserving
  instant site-wide selection and saved-theme preloading.

### Changed
- Kept the compact calendar agenda on Today while replacing the standalone
  Calendar page's list with the Operator Week grid.
- Retired the redundant Agent Messages dashboard surface and its frontend
  polling while preserving existing project-owned message data and compatibility
  endpoints for a migration window.
- Renamed the original Light choice to Soft Light and moved it to a calmer
  gray-blue surface palette with less pure-white glare.

### Fixed
- Fixed light-theme button and description contrast across dashboard surfaces.
- Replaced the generic calendar fallback and event fills with palette-aware
  surfaces derived from each active theme.

## 2026-07-13

### Added
- Added private SQLite-backed Agent Console attachment metadata with
  content-addressed blob storage, image/text/source uploads, retained input
  cards, and same-origin content serving.
- Added escaped fenced-code rendering with language labels and copy controls,
  safe raster previews, and download-style cards for non-embedded files.
- Added restricted repository workspace search and private file snapshots, plus
  trusted per-run export directories and discovery of assistant-created files.
- Added capability-gated Hermes runtime identity inspection and confirmed
  synchronization of each profile's canonical name and routing role into a
  versioned Mentat-managed block at the top of `SOUL.md`.
- Added Managed Agent identity readiness, role editing, exact previews, safe
  backfill for existing profiles, post-write verification, and identity checks
  that do not disclose the expected answer in the test prompt.

### Fixed
- Kept successful Console attachments visibly staged for the next prompt,
  preserved upload failures in an accessible composer alert, and labeled sent
  files as prompt context in the conversation.
- Materialized validated images as private extension-bearing per-run inputs so
  Hermes accepts content-addressed blobs whose canonical storage name has no
  suffix; transient input copies are removed when execution ends.

### Safety
- Attachment responses omit hashes, storage keys, and filesystem paths; reject
  traversal, symlinks, secrets, SVG, archives, executables, mismatched content,
  and oversized files; and serve text as non-sniffable plain text.
- Staged expiry, retained-run references, one-hour orphan grace, bounded
  periodic collection, deletion backoff, and startup reconciliation protect
  active files while cleaning abandoned blobs and crash leftovers.
- Workspace and artifact ingestion use private no-follow snapshots and explicit
  roots/export directories. Mentat never opens a path parsed from model prose.
- Identity writes resolve profiles through Hermes, preserve all soul content
  outside the managed block, reject symlinks and malformed/multiple blocks,
  bind confirmations to the current soul revision, block active Console runs,
  use atomic replacement, and attempt rollback on metadata or verification
  failure. No general soul editor or soul-content browser API was added.

## 2026-07-12

### Added
- Added project-owned personal planning fields and Today workflows for quick
  capture, deliberate selection and manual ordering, time estimates, scheduled
  blocks, browser reminders, subtasks, dependencies, recurrence, and built-in
  Today/Waiting/Review/Blocked/Someday decision views.
- Added the capability-gated Hermes Kanban adapter as the durable task-delegation
  path, including exact preview and confirmation binding, fixed shell-free
  operations, post-operation read-back verification, partial-failure reporting,
  task-linked run/session state, and review actions.
- Added Agent Activity and review queues for needs-input, running,
  ready-for-review, failed, and recently-completed delegated work.
- Added Mentat-owned task creation and linkage from verified calendar events
  while preserving read-only Google Calendar access.
- Added searchable Obsidian notes, explicit Open in Obsidian links, validated
  vault-relative task attachments, and bounded attached-note delegation context.
- Added grouped global search across tasks, projects, sessions, notes, and
  calendar events without navigating while the operator types.
- Added Agent Creator and Managed Agent onboarding actions to test profile
  identity in Console or start assigning the profile's first task.

### Changed
- Made Mentat tasks the source of truth for personal day planning while keeping
  Hermes profiles canonical for executable agent identity and Hermes Kanban
  canonical for delegated execution state.
- Kept Agent Messages as a safe project-owned communication queue and Agent
  Console as an interactive surface; neither is presented as durable task
  execution.
- Kept Google Calendar and Hermes session/database access read-only. Calendar
  links, reminders, note attachments, and review state write only to Mentat's
  allowlisted project-owned task data.

### Safety
- Delegation and remote follow-up mutations fail closed when Hermes Kanban is
  unavailable or unsupported, when the bound task/intent changes, or when
  Hermes state cannot be verified after mutation.
- Delegation creation uses an atomic local reservation, live action previews
  bind the current Hermes task/run state, and adapter mutations verify their
  requested postcondition before reporting success.
- Dependency cycles, missing/self dependencies, unsafe vault paths, malformed
  planning metadata, and implicit notification permission requests are rejected.
- Recurring tasks deduplicate reopened completions, preserve completed checklist
  history, honor occurrence counts, and keep local wall-clock blocks stable
  across daylight-saving changes.

## 2026-07-11

### Added
- Added previewed, confirmed deletion for project-owned tasks with stale-preview
  rejection and locked atomic persistence.

### Fixed
- Made Agent Console child processes inherit Hermes' shared binary directory so
  named profiles can discover an installed Tirith scanner without disabling
  security scanning or exposing local paths to the dashboard.
- Added authenticated provider and model controls to the selected Managed Agent
  detail pane, including fresh profiles created without cloned configuration.
- Made Managed Agents report enabled built-in skills instead of the total
  installed catalog, and refresh newly created profiles before Console use.
- Made the Agent Console provider/model toolbar wrap with bounded flexible
  controls so empty or long provider states cannot overlap the model selector.
- Kept long subsystem-health summaries inside the top navigation with an
  ellipsis and full hover text.
- Made the Settings view render its fetched public-safe Hermes configuration
  summary instead of leaving the initial placeholder visible.
- Preserved descriptive navigation labels for assistive technology when the
  compact layout hides visible sidebar text.
- Corrected the README clone URL and directory name to match this repository.
- Removed pill containers from Agent Creator progress and Managed Agent state
  presentation while retaining clear text status.

### Changed
- Kept Hermes cron inventory read-only and made queue controls fail closed after
  confirming that the installed runtime lacks the atomic expected-revision,
  enabled-only operation required for safe next-tick queueing. Immediate
  **Run now** remains a separate deferred product choice.
- Enforced loopback-only server binds and removed non-loopback launch guidance.
- Made provider switching fail closed unless the installed Hermes runtime
  exposes the supported profile-model operation, and removed the legacy direct
  Agent Console model-mutation route.
- Hardened gitignored Agent Console history with owner-only POSIX directory and
  file permissions in addition to bounded redaction, including startup
  migration of existing valid summaries and permission hardening for corrupt
  history.
- Hardened the local HTTP boundary with exact Host/Origin matching, JSON content
  checks, anti-framing headers, and generic public runtime errors.
- Hardened lifecycle cleanup so stale runtime PIDs cannot authorize terminating
  an unrelated listener.
- Made host-resource health reporting use native filesystem labels instead of
  Windows drive names on macOS and Linux.

### Validation
- `python3 -m unittest discover -s tests -p 'test_*.py'` (196 tests)
- JavaScript syntax checks for `public/core.js` and `public/app.js`

## 2026-07-10

### Added
- Added a versioned, project-owned slash-command manifest for `/model`, `/new`,
  and `/help`, including declared handlers, arguments, descriptions, and safety
  classifications.
- Added the capability-gated Hermes profile discovery adapter and local-only
  `/api/hermes/profiles` endpoint.
- Added preview and confirmed creation endpoints for fresh, no-bundled-skills,
  and config-cloned Hermes profiles using fixed, shell-free CLI arguments.
- Added built-in Hermes skill catalog discovery and explicit per-profile skill
  selection using enabled-subset semantics.
- Added a persistent Managed Agents surface that refreshes and highlights newly
  created Hermes profiles before profile-aware console routing is enabled.
- Added profile-aware Agent Console selection, fixed `hermes -p <profile>` run
  routing, profile-scoped model discovery/configuration, and resume isolation.
- Added capability-gated, explicitly confirmed deletion for non-default,
  non-active Hermes profiles, including active-run blocking and refresh-based
  verification after Hermes performs the operation.
- Added a versioned, fail-closed profile payload with Hermes capability flags
  and normalized profile metadata that excludes paths and secrets.
- Added `ARCHITECTURE.md` to define executable agents as Hermes profiles and
  document Mentat's typed mutation contract.
- Persisted up to 24 privacy-aware Agent Console run summaries in gitignored
  `data/runtime` storage with bounded, redacted prompt/response/error excerpts.
- Added versioned structured Agent Console events with monotonic per-run cursors,
  bounded persistence, and a cursor-based incremental run endpoint.
- Added profile-scoped provider inventory sourced from Hermes' explicitly
  configured and authenticated providers, plus confirmed provider/model
  switching with active-run blocking, post-write verification, and rollback.

### Changed
- Documented the approved profile-scoped provider-switching boundary: only
  explicitly configured/authenticated Hermes providers are selectable;
  credentials remain Hermes-owned; switches require preview, confirmation,
  active-run blocking, post-operation verification, and rollback where supported.
- Agent Console completion, help, and dispatch now use the safe manifest and a
  fixed frontend handler registry instead of duplicated hard-coded command
  arrays; arbitrary Hermes CLI passthrough remains unavailable.
- Reframed Mentat as a local-first, capability-scoped Hermes control plane
  rather than a strictly read-only dashboard.
- Preserved direct read-only boundaries for Hermes databases, credentials,
  configuration files, skills, and persona files.
- Preserved the then-current Console run-admission behavior while recording the
  selected profile identity and preventing cross-profile session resume.
- Recovered queued, running, or cancelling console runs as interrupted after
  restart using locked atomic writes and corruption-safe fallback.
- Switched active Agent Console refreshes from complete dashboard polling to
  incremental event polling while retaining the complete run API for compatibility.
- Replaced auto-resizing Managed Agent cards with a stable vertical
  master/detail selector and synchronized the selected agent with Console routing.

### Validation
- `python -m unittest discover -s tests -v` (140 tests)
- `python -m py_compile server.py agent_run_history.py command_manifest.py hermes_profiles.py hermes_profile_creation.py hermes_profile_deletion.py hermes_provider_switching.py hermes_skills.py`
- JavaScript syntax checks for `public/core.js`, `public/app.js`, and
  `scripts/browser_smoke.mjs`

## 2026-06-29

### Added
- Added local agent-message compose and status plumbing (`data/agent_messages.json`, `/api/agent-messages`) with queue-safe state transitions.
- Added project-scoped write APIs for creating/updating projects and richer task/project writeback from the frontend.
- Added read-only email surface (`data/email.json`, `/api/email`) and Obsidian notes cache keying by vault file metadata.
- Added a browser smoke script (`scripts/browser_smoke.mjs`) covering Today, Agents/Sessions, Calendar, Projects/Tasks, Notes, and Agent Message compose flows.

### Changed
- Introduced a shared, locked JSON file store (`json_store.py`) and updated server write paths to use allowlisted JSON updates for safer persistence.
- Updated setup/runtime workflow to better resolve Hermes home, local vault paths, and generated runtime state.
- Expanded visual/test contract handling around refined A desktop/task inspector and project/task editor behavior.
- Kept Dashboard write contracts project-owned while preserving Hermes core read-only boundaries.

### Fixed
- Updated tests and frontend contracts so dashboard contracts remain explicit and stable for the static-vanilla architecture.
- Ensured attention/task/project/agent payload flows align with new status and persistence handling.

### Validation
- `python -m py_compile server.py json_store.py mentat_lifecycle.py runtime_config.py scripts/mentat_setup.py`
- `node --check public/app.js`
- `node --check public/core.js`
- `node --check scripts/browser_smoke.mjs`
- `python -m unittest discover -s tests -v`
