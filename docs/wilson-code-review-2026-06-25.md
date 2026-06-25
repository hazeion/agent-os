# Wilson Milsen Review — Mentat Big Files

Date: 2026-06-25
Scope: read-only review after compact dark dashboard redesign was merged to `main`.
Reviewed files: `AGENTS.md`, `README.md`, `server.py`, `public/index.html`, `public/core.js`, `public/app.js`, `public/styles.css`, `tests/test_dashboard_behaviors.py`, `tests/test_visual_contract.py`, and project task/docs context.

## Score

**78 / 100**

## Verdict

Mentat is in a strong functional state for a local-first command center. The project has good boundary discipline, a useful test suite, and a clear product direction. The main reason the score is not above 80 is hotspot concentration: `server.py`, `public/app.js`, and `public/styles.css` are now large enough that another major feature — especially website-to-agent messaging — could make the project harder to maintain unless we split responsibilities or add stronger browser-level smoke coverage first.

## What looks good

- Local-only posture remains clear and appropriate.
- Hermes core is still treated as read-only.
- Project-owned write-back is allowlisted to local JSON/API surfaces.
- Agent Pulse is sensibly project-owned (`data/agents.json`, heartbeat API, helper script) instead of pretending to control Hermes internals.
- The compact dark redesign has an explicit design doc and visual contract coverage.
- Runtime config, health checks, lifecycle helpers, and frontend core helpers have already started reducing earlier monolith risk.
- Current verification is real: full unit suite is passing, syntax checks pass, and live smoke endpoints were checked after the main-branch push.

## Must-fix before score >80

1. **Add browser-level smoke tests before website-to-agent messaging.**
   - Current tests are good, but many frontend guarantees are still source-string/contract checks.
   - Messaging will add more interaction state, so at least one headless browser path should verify render/click/submit/status behavior.

2. **Split or strongly section `public/app.js` before adding chat-like workflows.**
   - `app.js` is ~1,814 lines and owns tasks, projects, calendar, sessions, replay, Agent Pulse, notes, health, and event wiring.
   - Website-to-agent messaging should not be added as another large block without either extraction or clearer sections.

3. **Organize `public/styles.css` after the compact redesign.**
   - `styles.css` is ~2,786 lines.
   - The new compact-dark layer works, but future edits will be easier if sections/tokens/components are organized around views and components.

4. **Define message safety/data model before implementation.**
   - Browser-to-agent input is a new trust boundary.
   - Do not wire browser input directly to shell execution or implicit Hermes-core mutation.
   - Use the dedicated plan in `docs/website-to-agent-messaging-plan.md`.

## YAGNI / conciseness suggestions

- Do not migrate to React yet. Vanilla JS is strained but still acceptable; modularizing view responsibilities is a lower-risk next move.
- Do not build full realtime chat first. Start with a local message queue/API/status model, then wire a consumer.
- Do not add Kanban now. The grouped queue + Selected Task inspector is still the right default.
- Do not add dashboard-native project editing before clarifying whether agent messaging or project editing is the next user value priority.
- Avoid turning Agent Pulse into a full message database; keep `data/agents.json` for liveness and a separate `data/agent_messages.json` for message history.

## Performance suggestions

- Keep polling centralized and view-gated. Avoid adding more always-on dashboard fetches for messaging if the active view does not need them.
- For future message history, paginate or limit results by status/date so the dashboard does not render unbounded chat logs.
- Keep the 5-minute Calendar cache pattern as the model for any expensive integrations.
- Consider smaller render functions per view to reduce unnecessary DOM churn when one state domain changes.

## Recommended implementation order

1. Add/confirm browser smoke-test foundation.
2. Organize compact CSS sections without visual changes.
3. Split or section `app.js` by view/domain.
4. Add `agent_messages` data contract and backend tests.
5. Add website compose/status UI.
6. Add a simple consumer bridge or polling helper.
7. Only then consider richer live/streaming chat behavior.

## Verification notes

Observed verification from this session:

- `git status --short --branch` showed clean `main...origin/main` before planning changes.
- Full test suite passed: `python -m unittest discover -s tests -v` → **58/58 OK**.
- Current hotspot sizes:
  - `server.py`: 1,835 lines
  - `public/app.js`: 1,814 lines
  - `public/styles.css`: 2,786 lines
  - `public/index.html`: 333 lines
  - `public/core.js`: 258 lines
  - `tests/test_dashboard_behaviors.py`: 538 lines
  - `tests/test_visual_contract.py`: 147 lines

## Files / tasks that reference this review

- Repo review file: `docs/wilson-code-review-2026-06-25.md`
- Messaging plan: `docs/website-to-agent-messaging-plan.md`
- Obsidian plan: `E:/Obsidian Notes/Mentat - Website-to-Agent Messaging Plan.md`
- Task: `task_wilson_big_file_review_20260625`
- Follow-up tasks:
  - `task_agent_pulse_auto_producer_visibility`
  - `task_browser_smoke_tests_before_agent_messaging`
  - `task_css_compact_board_cleanup`
  - `task_appjs_view_modularization_before_chat`
  - `task_server_api_domain_split_before_chat`
  - `task_agent_messaging_v1`


## Async Wilson addendum — detailed big-file findings

The background Wilson pass independently returned the same score, **78 / 100**, but identified several sharper implementation risks. These findings supersede the earlier generic cleanup wording where more specific.

### Additional must-fix before score >80

1. **Add server-side write locking for project-owned JSON writes.**
   - `ThreadingHTTPServer` can handle concurrent requests.
   - Multiple read-modify-write paths update task/agent JSON through the shared write helper.
   - Add per-file/thread locking plus unique temp filenames before introducing `agent_messages.json` or more write-back routes.

2. **Collapse the stylesheet to one active design system.**
   - The compact dark redesign currently overrides a substantial earlier visual layer.
   - The UI works, but doubled cascade surface increases maintenance cost and parse work.
   - Keep the approved compact dark look; prune inactive pre-compact CSS and removed-panel selectors.

3. **Prune orphaned UI branches before further modularization.**
   - `renderAttention()` and attention list wiring remain even though the Today attention panel/list/count are removed.
   - `renderSessionStats()` remains even though `#session-stats` is absent and the temporary Session Analytics panel was removed.
   - Remove dead branches before splitting `app.js`; otherwise dead code may be preserved in new modules.

4. **Keep docs current with implementation.**
   - Stale references to the removed Session Analytics panel and custom dropdown/listbox were found.
   - Those references have now been corrected in README/AGENTS as part of saving this review.

### Additional performance / maintainability ideas

- Cache derived task/project stats per refresh payload to avoid overlapping work between Today, Projects, and task renderers.
- Skip DOM rendering for sections whose payload hash/timestamp has not changed.
- Add cache/limit/pagination to `obsidian_notes()` because the Notes view recursively reads markdown files.
- Consider mtime-based caching for read-only session detail/replay payloads.
- Remove small unused imports such as `sys` / `HEALTH_STATUS_RANK` during the next backend cleanup pass after verifying they remain unused.

### Extra tasks created from the addendum

- `task_json_write_lock_project_owned_data`
- `task_prune_orphaned_attention_session_ui`
- `task_reconcile_current_docs_after_ui_changes`
- `task_dashboard_refresh_render_perf`
- `task_obsidian_and_replay_cache_perf`
- `task_trim_onboarding_docs_history`
- `task_remove_unused_server_imports`
