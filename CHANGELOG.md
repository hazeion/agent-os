# Changelog

All notable changes to Mentat.

## 2026-07-20

### Added
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
  unavailable, and inline images fail clearly because Hermes does not yet
  advertise image input for the stoppable Runs lifecycle.
- Remote session identifiers remain process-private behind random aliases bound
  to the selected connection. Mentat allowlists and bounds public metadata,
  returns only user/assistant conversation text, labels compressed
  latest-segment history as partial, and rejects stale aliases, changed
  capabilities, changed message identity, private transport reflection,
  malformed pagination, or uncertain identity.
- Remote session continuation remains unavailable because the current Runs
  input is not separately capability-advertised and the session-chat stream has
  no matching public status/stop operation.
- Audited remote approval responses and kept them unavailable: Hermes' current
  mutation has no request ID/revision/hash, so Mentat cannot prove that a
  user's confirmation still targets the displayed request. Approval requests
  continue to stop the bound run safely until upstream adds exact binding and
  a structured privacy-safe preview.
- Remote runs now require the exact advertised Runs API endpoints, remain bound
  to one opaque connection identity, never retry submission, and issue at most
  one stop attempt. Interrupted streams reconcile through status; approval
  requests stop safely because approval responses are not supported yet.
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
  Console as an interactive single-run surface; neither is presented as durable
  task execution.
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
- Kept Agent Console execution globally single-run while recording the selected
  profile identity and preventing cross-profile session resume.
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
