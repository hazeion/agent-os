# Mentat (Agent OS)

Local mission-control and personal productivity dashboard for Brandon's Hermes Agent workflows.

## Run

Install the pinned Python runtime dependencies first:

```bash
cd /e/code/agent-os
python -m pip install -r requirements.txt
```

Mentat currently has **no npm/package.json dependency step**; the frontend is static HTML/CSS/vanilla JS.

From Git Bash / Hermes terminal, prefer the bash-native helpers:

```bash
cd /e/code/agent-os
./run.sh
```

From Windows Explorer / cmd, use the batch launcher:

```bat
E:/code/agent-os/run.bat
```

Stop or inspect the local server lifecycle when needed:

```bash
./status.sh
./stop.sh
```

Then open the default local URL:

`http://localhost:8888`

## Configuration

Mentat now uses a clean layered runtime config:

1. built-in defaults
2. `agent-os.toml` (shared repo defaults)
3. `agent-os.local.toml` (gitignored machine-specific overrides)
4. environment variables
5. CLI flags

Useful commands:

```bash
python server.py --print-config
python server.py --port 8890
python server.py --host 0.0.0.0 --port 8890
python agent_os_lifecycle.py status --port 8890
python agent_os_lifecycle.py stop
```

Useful files / overrides:

- `agent-os.toml` — shared local-only defaults checked into the repo
- `agent-os.local.toml` — local machine overrides such as Brandon's Obsidian vault path
- `AGENT_OS_CONFIG` — optional extra TOML file to merge after the shared/local files
- `AGENT_OS_PORT`, `AGENT_OS_HOST`, `AGENT_OS_APP_NAME`, `HERMES_HOME`, `OBSIDIAN_VAULT_PATH` — common env overrides

This keeps the dashboard local-only by default while making later VPS migration a config exercise instead of a code rewrite.

Current modularization / naming status:

- The user-facing dashboard brand is now **Mentat**.
- The project/task data now use **Mentat** as the project name; repo path, helper names, Python compatibility modules, and some compatibility docs still use `agent-os` / Agent OS until the larger rename is deliberately planned.
- Runtime config loading lives in `runtime_config.py`; `server.py` now focuses more narrowly on data access, routes, and HTTP serving.
- Shared browser constants, markdown helpers, and API helpers live in `public/core.js`; `public/app.js` remains the UI orchestrator.
- See `docs/modularization-plan.md` for the staged split plan.

## Current phase

Agent OS is transitioning out of **Phase 2.5 UI/UX stabilization** with the first important Phase 3 read-only integration polished.

Implemented Phase 3 / integration pieces:

- Clickable read-only session detail from Hermes `state.db`
- Message-level read-only search over Hermes FTS data
- Search-term highlighting in results and conversation detail
- Search result click-through to a focused conversation window around the matched message
- Structured run replay / trace-lite in Agents / Sessions, clearly labeled as read-only toward Hermes core and paired with raw transcript access
- Masked Hermes config/model viewer in Settings
- Google Calendar read-only source integration through the Hermes Google OAuth token, with local `calendar.json` fallback, 7-day agenda grouping, Today preview, visible read-only/fallback/stale states, and a short in-memory cache so dashboard polling does not hit Google every 30 seconds
- Subsystem-aware `/api/health` status that reports real state for Hermes `state.db`, config readability, calendar live/fallback mode, cron store availability, and host resource pressure
- Dashboard-native task create/edit write-back through project-owned `POST /api/tasks` and `POST /api/tasks/<id>` routes, surfaced from the Projects / Tasks queue and Selected Task inspector
- Agent Pulse 2.0 live heartbeat registry through project-owned `data/agents.json`, `GET /api/agents`, and `POST /api/agents/heartbeat`, with historical session fallback when no live agents are registered, stale-heartbeat downgrade when producers stop reporting, and producer guidance/examples surfaced through the API/UI and `scripts/agent_heartbeat.py examples`. If the panel appears empty, verify whether a producer is emitting heartbeats; follow-up task `task_agent_pulse_auto_producer_visibility` tracks making this clearer and/or wiring default producer visibility.
- Structured run replay / trace-lite view in Agents / Sessions: `GET /api/hermes/sessions/<id>/replay` parses Hermes `state.db` read-only into run summary, user intent, agent actions, error blockers, outcome, code/file summary, verification, inferred related tasks, and suggest-first/write-later guidance. The page now uses a plain-text session dropdown above Replay/Transcript instead of a dense session-card column, and the temporary Session Analytics panel has been removed from this view.

Current UI stabilization focus:

- Today View is the primary command center; Open Queue / Next Moves includes a project selector, left-edge task state indicators, and task-card jumps into the Projects / Tasks selected-task detail. The redundant Needs Attention hero card and Today container have been removed; attention is now represented by task-state color cues in the queue.
- The `Hello <name>` hero title is project-configured from `data/dashboard.json`, styled with JetBrains Mono, and now uses the dashboard's blue/teal/white glow instead of the prior amber dot-matrix treatment.
- The old right-side Local badge has been replaced by a low-poly/digitized SVG brain mark animated with a deliberately choppy 15-frame stepped spin.
- Projects / Tasks is a project command center with Project Portfolio, Open Task Queue, Project Status, and Recent Completed Work.
- Project Portfolio keeps project cards compact with counts and percent text; the Selected Scope summary keeps the visual progress bar.
- Project Portfolio cards are fixed-width in a horizontal rail with arrow controls when the rail overflows.
- The task status filter uses a native dark `<select>` surface for reliable mouse and keyboard behavior while keeping completed tasks available by filter.
- Runtime configuration now comes from layered TOML/env/CLI sources in `runtime_config.py` so shared defaults and local machine overrides are no longer hardcoded directly in `server.py`.
- Local server lifecycle is now safer: `run.sh` / `run.bat` perform preflight cleanup, `stop.sh` / `status.sh` wrap the lifecycle helper, and `server.py` writes a runtime state file for restart/shutdown coordination.
- Runtime state now also records a `launcher_pid` when available so Windows background-launch diagnostics are easier.

Next likely phase: structured run replay / trace-lite is now in place for Agents / Sessions. Brandon has identified website-to-agent messaging as a desired future feature; use `docs/website-to-agent-messaging-plan.md` and the Obsidian note `[[Mentat - Website-to-Agent Messaging Plan]]` before implementation. The next practical expansion can be website-to-agent messaging, dashboard-native project create/edit, or deeper replay evolution with agent-written summaries and explicit task-link/write-back actions. React remains deferred until routing, modals/drawers, heavier editing, websocket-like live roster behavior, or direct agent chat justify it.

React migration is deliberately deferred until interaction complexity justifies it. See `docs/react-readiness.md` for the trigger points and migration path.

## Troubleshooting

### Browser says the connection closed / endpoints fail on port 8888

If a previous Hermes session crashed while the dashboard server was running, stale Python listeners may remain on port 8888. Check and clear them from Git Bash:

```bash
netstat -ano | grep ':8888'
for pid in $(netstat -ano | awk '/127\\.0\\.0\\.1:8888/ && /LISTENING/ {print $NF}' | sort -u); do
  taskkill //PID "$pid" //F
 done
```

Then restart:

```bash
cd /e/code/agent-os
python server.py
```

## Scope

- Local-only v1 by default (`127.0.0.1:8888`)
- Reads Hermes data from `HERMES_HOME`
- Runtime paths/host/port can be overridden through TOML, environment variables, or CLI flags
- Dashboard write-back is allowlisted to project-owned JSON files under the configured data directory (default `E:/code/agent-os/data/`)
- Uses local JSON files for projects, tasks, attention items, and calendar fallback data
- Google Calendar uses the Hermes Google OAuth token at `HERMES_HOME/google_token.json` for read-only upcoming events

## Projects / Tasks

Projects / Tasks is now a project command center rather than a duplicate task/archive view:

- **Project Portfolio** selects the project scope with compact fixed-width horizontal cards. Portfolio cards show counts and percent text only; the Selected Scope summary retains the progress bar.
- **Open Task Queue** defaults to actionable work only; completed tasks are available through the native status filter but are not shown by default.
- **Selected Task** uses the refined-A inspector pattern: the queue stays compact and the selected task's full description, status metadata, tags, and next-move guidance live in a persistent detail rail. On narrow/mobile layouts, the queue stacks above the detail panel and exposes a Back to Queue control instead of duplicating the status pill in the detail header.
- **Project Status** shows percent complete as text only, plus open/completed counts, blockers/waiting count, next move, and latest completed item.
- **Recent Completed Work** is a compact timeline/archive below the queue.

Tasks can now be created and edited from the dashboard through project-owned local API routes. New projects are still added by editing `data/projects.json` — usually by asking Hermes to add them safely — until the separate project create/edit slice is implemented.

## Agent Pulse producers

Agent Pulse has a project-owned heartbeat registry at `GET /api/agents` and `POST /api/agents/heartbeat`, backed by `data/agents.json`. The producer helper in `scripts/agent_heartbeat.py` can either publish one heartbeat or wrap a long-running command:

```bash
python scripts/agent_heartbeat.py beat --name Hermes --status running --project Mentat --current-task "Working on Mentat"
python scripts/agent_heartbeat.py run --name "Codex Worker" --project Mentat --current-task "Implement feature" --interval 30 -- python worker.py
python scripts/agent_heartbeat.py examples
```

The helper writes only through Mentat's local API and does not mutate Hermes core files. Use stable `--agent-id` values when wrapping recurring agents so each heartbeat updates the same live record. `GET /api/agents` now also derives producer freshness: active records that stop heartbeating are marked stale instead of appearing live forever, and the Today View Agent Pulse panel surfaces example producer commands when the registry is empty.

## Future roadmap tasks

- Phase 2.5 UI/UX stabilization review and Google Calendar read-only polish are completed; move into the next Phase 3 expansion only after keeping the dashboard verified and local-only.
- Future-phase TODOs are tracked under the `Mentat` project in `data/tasks.json`:

- Build website-to-agent messaging v1 from `docs/website-to-agent-messaging-plan.md`
- Add browser smoke tests before heavier agent messaging interactions
- Organize compact board CSS and split `app.js`/server domains before chat scope grows
- Add dashboard-native project creation and editing
- Add a read-only email pane after calendar stabilizes
- Add Windows startup service docs and safe remote access option
- Reassess React migration only when interactions justify it
- Reference `docs/wilson-code-review-2026-06-25.md` for the latest Wilson cleanup recommendations

## Attention items

Task attention is now surfaced primarily through Today View → Open Queue / Next Moves using left-edge color cues and the task-state label. The old standalone Needs Attention hero card and Today container were removed as redundant.

Open tasks from `data/tasks.json` count as attention when they have status `needs_attention`, boolean `needs_attention`, `review_required`, or a `needs attention` / `needs_attention` tag. These items remain task-owned and can be opened through the queue or Projects / Tasks rather than resolved as standalone records.

Manual `data/attention.json` items remain supported at the API/data layer for future surfaces, but they are no longer rendered as a top-level Today container.

## Main files

```text
server.py
agent_os_lifecycle.py
scripts/agent_heartbeat.py
agent-os.toml
agent-os.local.toml (local-only, gitignored)
run.bat
stop.bat
status.bat
public/index.html
public/styles.css
public/app.js
data/projects.json
data/tasks.json
data/attention.json
data/calendar.json
inventory.md
```
