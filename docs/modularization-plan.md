# Mentat Modularization Plan

Date: 2026-06-22

## Goal
Reduce monolith risk in the existing Agent OS codebase while preserving the current local-first dashboard behavior and preparing for the eventual product rename to **Mentat**.

## Guardrails
- Do not rewrite the app or introduce React/build tooling yet.
- Keep endpoint contracts stable.
- Keep Hermes core read-only.
- Prefer responsibility-based extraction over file-size-only splitting.
- Make each slice testable and reversible.

## Phase A — safe first slice, complete
1. Extract runtime configuration concerns out of `server.py` into a small dedicated module.
2. Extract shared browser constants/utilities/API helpers out of `public/app.js` into `public/core.js`.
3. Apply the fast user-facing brand rename to **Mentat** without renaming the repo, Python modules, or task IDs yet. The data project key/name was later moved to Mentat once Brandon approved that narrower migration.
4. Run existing Python/JS checks and HTTP smoke tests.

## Phase B — next server slices
- `server.py` should keep route dispatch and HTTP response plumbing.
- Extract Hermes/session reads into a `hermes_data.py`-style module.
- Extract health subsystem checks into a `health.py`-style module.
- Extract project/task/attention data helpers into a dashboard data module.

## Phase C — next frontend slices
- Keep `public/app.js` as the UI orchestrator.
- Extract renderers by view when the current utility extraction is stable:
  - `calendar-view.js`
  - `projects-view.js`
  - `sessions-view.js`
  - `settings-view.js`
- Keep shared DOM/API/markdown helpers in `public/core.js` until they get large enough to split again.

## Phase D — full Mentat rename later
Later, when Brandon approves the larger rename boundary:
- rename repo/package/module surfaces deliberately,
- update docs and Obsidian note names,
- consider compatibility aliases for old helper script names.

Task/project data already use Mentat, so the remaining rename scope is mainly repo/package/module/helper compatibility.

## Current slice success criteria
- `server.py` loses config-loading responsibility.
- `public/app.js` loses shared constants/utility/API helper responsibility.
- Mentat appears as the user-facing app title/sidebar brand.
- Existing dashboard behavior remains unchanged.
- Tests and smoke checks pass.


## Recommendation after Phase A

Keep **Mentat** as the visible product name and project/task data name now, but postpone the remaining internal repo/module/helper rename. The next internal rename should be a deliberate migration milestone, not opportunistic cleanup during feature work. Continue modularization only with one small concern-based slice at a time when it directly reduces risk.
