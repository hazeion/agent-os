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
- The repo path, helper names, task project key, and compatibility docs still use `agent-os` / Agent OS until the larger rename is approved.
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
- Historical Session Analytics in Agents / Sessions, clearly labeled as read-only rather than live heartbeat tracking
- Masked Hermes config/model viewer in Settings
- Google Calendar read-only source integration through the Hermes Google OAuth token, with local `calendar.json` fallback, 7-day agenda grouping, Today preview, visible read-only/fallback/stale states, and a short in-memory cache so dashboard polling does not hit Google every 30 seconds
- Subsystem-aware `/api/health` status that reports real state for Hermes `state.db`, config readability, calendar live/fallback mode, cron store availability, and host resource pressure

Current UI stabilization focus:

- Today View is the primary command center.
- The `Hello <name>` hero title is project-configured from `data/dashboard.json`, styled with JetBrains Mono, and now uses the dashboard's blue/teal/white glow instead of the prior amber dot-matrix treatment.
- The old right-side Local badge has been replaced by a low-poly/digitized SVG brain mark animated with a deliberately choppy 15-frame stepped spin.
- Projects / Tasks is a project command center with Project Portfolio, Open Task Queue, Project Status, and Recent Completed Work.
- Project Portfolio keeps visual progress bars; Project Status lists percent complete as text only.
- Project Portfolio cards are fixed-width in a horizontal rail with arrow controls when the rail overflows.
- The task status filter is a custom dark dropdown/listbox with a centered SVG chevron, click-to-toggle behavior, outside-click close, Escape close, and keyboard navigation.
- Runtime configuration now comes from layered TOML/env/CLI sources in `runtime_config.py` so shared defaults and local machine overrides are no longer hardcoded directly in `server.py`.
- Local server lifecycle is now safer: `run.sh` / `run.bat` perform preflight cleanup, `stop.sh` / `status.sh` wrap the lifecycle helper, and `server.py` writes a runtime state file for restart/shutdown coordination.
- Runtime state now also records a `launcher_pid` when available so Windows background-launch diagnostics are easier.

Next likely phase: begin Phase 3 expansion around the next high-value interaction surfaces after calendar stabilization, then move toward dashboard-native project/task write-back. React remains deferred until direct editing, routing, modals/drawers, or live agent heartbeat interactions justify it, and the future VPS move should now mostly build on config/service work rather than hardcoded path cleanup.

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

- **Project Portfolio** selects the project scope, uses fixed-width horizontal cards, and keeps the visual progress bar.
- **Open Task Queue** defaults to actionable work only; completed tasks are available through the custom status dropdown but are not shown by default.
- **Project Status** shows percent complete as text only, plus open/completed counts, blockers/waiting count, next move, and latest completed item.
- **Recent Completed Work** is a compact timeline/archive below the queue.

For now, new projects are added by editing `data/projects.json` and linking tasks in `data/tasks.json` — usually by asking Hermes to add them safely. A dashboard-native project creation flow is still a future feature.

## Future roadmap tasks

- Phase 2.5 UI/UX stabilization review and Google Calendar read-only polish are completed; move into the next Phase 3 expansion only after keeping the dashboard verified and local-only.
- Future-phase TODOs are tracked under the `Agent OS` project in `data/tasks.json`:

- Build dashboard-native project and task creation
- Design Agent Pulse 2.0 heartbeat/write-back model
- Evaluate Kanban or richer task board write-back
- Add a read-only email pane after calendar stabilizes
- Add Windows startup service docs and safe remote access option
- Reassess React migration only when interactions justify it
- Run Wilson Milsen review before the next major expansion

## Attention items

Open manual items from `data/attention.json` appear in the Needs Attention panel. Click **Resolve** on a manual item after handling it; the dashboard marks it `resolved`, sets `resolved_at`, and hides it from open counts while keeping history in the JSON file.

Open tasks from `data/tasks.json` also appear in Needs Attention when they have status `needs_attention`, boolean `needs_attention`, `review_required`, or a `needs attention` / `needs_attention` tag. These task-derived items use **Open task** to jump to the relevant project queue instead of being resolved as standalone attention records.

## Main files

```text
server.py
agent_os_lifecycle.py
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
