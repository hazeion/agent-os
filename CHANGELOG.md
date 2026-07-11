# Changelog

All notable changes to Mentat.

## 2026-07-10

### Added
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
- Added a versioned, fail-closed profile payload with Hermes capability flags
  and normalized profile metadata that excludes paths and secrets.
- Added `ARCHITECTURE.md` to define executable agents as Hermes profiles and
  document Mentat's typed mutation contract.

### Changed
- Reframed Mentat as a local-first, capability-scoped Hermes control plane
  rather than a strictly read-only dashboard.
- Preserved direct read-only boundaries for Hermes databases, credentials,
  configuration files, skills, and persona files.
- Kept Agent Console execution globally single-run while recording the selected
  profile identity and preventing cross-profile session resume.

### Validation
- `python -m unittest discover -s tests -v` (108 tests)
- `python -m py_compile server.py hermes_profiles.py hermes_profile_creation.py hermes_skills.py`
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
