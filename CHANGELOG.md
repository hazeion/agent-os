# Changelog

All notable changes to Mentat.

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
