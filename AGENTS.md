# Mentat / Agent OS — Agent Handoff Guide

This file is the first thing a new agent should read when working on Brandon's Agent OS project.

## Project location

```text
E:/code/agent-os
```

Obsidian planning notes live in:

```text
E:/Obsidian Notes
```

Important notes:

- `E:/Obsidian Notes/Agentic OS Project Home.md`
- `E:/Obsidian Notes/Agent OS - Implementation Spec.md`
- `E:/Obsidian Notes/Agent OS - Research Summary & Prompt Stack.md`

## What Mentat / Agent OS is

Mentat is the user-facing name for Brandon's local mission-control and personal productivity dashboard for Hermes Agent workflows.

Current v1 direction:

- Local-only dashboard.
- Clean dark UI with subtle hacker/futuristic styling.
- Start with only the Mentat project.
- Use local JSON files for project-owned data.
- Read Hermes core files only; do not write to Hermes core.
- Google Calendar read-only integration is connected through Hermes-managed OAuth; local `calendar.json` remains the fallback.
- No separate Latest Hermes Activity section.

## Current implementation

The app is a small Python HTTP server plus static frontend. The current user-facing brand is **Mentat**; repo/helper/task compatibility names still use Agent OS / `agent-os` until the larger rename boundary is approved.

Main files:

```text
server.py
runtime_config.py
agent_os_lifecycle.py
agent-os.toml
run.sh
stop.sh
status.sh
run.bat
stop.bat
status.bat
public/index.html
public/styles.css
public/core.js
public/app.js
data/projects.json
data/tasks.json
data/agents.json
data/attention.json
data/calendar.json
README.md
inventory.md
```

Current dashboard features:

- Left navigation shell with Today, Agents/Sessions, Calendar, Projects/Tasks, Notes, and Settings destinations.
- Today View command center as the primary mental model; Open Queue / Next Moves supports project filtering, left-edge task-state color cues, and direct jumps into Projects / Tasks selected-task detail. The redundant Needs Attention overview card and Today container are removed.
- Agents/Sessions view shell with a plain-text session dropdown above the detail area, searchable recent Hermes sessions, and a Replay/Transcript tab toggle for selected sessions.
- Message-level Hermes search from read-only `state.db` FTS, with highlighted results that open a focused conversation window around the matched message.
- Structured run replay / trace-lite endpoint and UI: `GET /api/hermes/sessions/<id>/replay` parses Hermes `state.db` read-only into run summary, user intent, medium-detail agent actions, error blockers, outcome, code/file summary, verification signals, inferred related tasks, and suggest-first/write-later guidance.
- The temporary Historical Session Analytics side panel has been removed; Agents/Sessions now favors structured Replay plus raw Transcript access, while Agent Pulse handles live heartbeat tracking.
- Agent Pulse 2.0 live registry is project-owned via `data/agents.json`, `GET /api/agents`, and `POST /api/agents/heartbeat`; it shows running/idle/blocked/done/failed summaries, marks overdue active producers as stale, and now also promotes currently-running Hermes sessions into live Agent Pulse so work appears even before a custom producer heartbeat is posted. `scripts/agent_heartbeat.py` provides one-shot heartbeat publishing, command wrapping with running/done/failed updates, and an `examples` mode for ready-to-run producer wiring.

- Masked Hermes config/model viewer in Settings.
- Project-configured `Hello <name>` header with JetBrains Mono and blue/teal/white glow styling.
- Low-poly/digitized SVG brain mark in the top-right header, animated with a deliberately choppy 15-frame stepped spin.
- Overview metric cards.
- Task attention is surfaced in Today View through Open Queue / Next Moves left-edge cues and task-state labels rather than a separate Needs Attention card/container.
- Google Calendar read-only source integration through Hermes OAuth, with local `calendar.json` fallback and grouped Today/Calendar agenda rendering.
- `docs/react-readiness.md` documents when to move the frontend from vanilla JS to React without prematurely adding a build step.
- Projects / Tasks command center with a Project Portfolio selector, Open Task Queue defaulting to actionable work, refined-A Selected Task inspector, Project Status panel, and compact Recent Completed Work timeline.
- Project Portfolio is a fixed-width horizontal card rail; project cards show counts and percent text, while the Selected Scope summary keeps the visual progress bar. Rail arrows should appear only when overflow actually requires horizontal scrolling.
- The Open Task Queue stays compact for scale; selecting a task opens its full description, status metadata, tags, and next-move guidance in the persistent Selected Task detail rail. Narrow/mobile layouts stack queue then detail and expose Back to Queue without duplicating the task status pill in the detail header.
- Project Status deliberately lists percent complete as text/number only, not a second progress bar, to avoid duplicating the portfolio progress bars.
- Task list uses a native dark status `<select>` for reliable mouse and keyboard behavior, keeping completed tasks available by filter but excluded from the default open queue.
- Project cards filter the queue/status/completion timeline and show open/completed counts with progress.
- Cron monitor.
- Obsidian notes panel.
- Subsystem-aware health/status indicator: `/api/health` now reports real state for Hermes `state.db`, masked config readability, Google Calendar live/fallback status, cron store availability, and host resource pressure instead of a fixed healthy heartbeat.
- Layered runtime configuration via `agent-os.toml`, optional `agent-os.local.toml`, environment variables, and CLI flags so paths/host/port are no longer hardcoded directly in `server.py`.
- Local server lifecycle helper via `agent_os_lifecycle.py`, `run.sh` / `run.bat`, `stop.sh` / `stop.bat`, and `status.sh` / `status.bat`; startup now performs a preflight cleanup and runtime state tracking to reduce stale-listener confusion.

Near-term project/task direction:

- The dummy project/task fixtures have been removed; keep the local data focused on the real Mentat project unless Brandon asks for temporary UI fixtures again.
- Phase 2.5 UI/UX stabilization review is completed; the current dashboard keeps the stabilized command-center UI while Phase 3 integrations expand.
- Google Calendar has been polished into a read-only 7-day agenda with a Today preview, grouped events, Google live/local fallback source pills, stale/error fallback metadata, and a 5-minute in-memory Google API cache.
- Dashboard-native task create/edit is implemented through project-owned endpoints/data files, not Hermes core writes.
- Dashboard-native project create/edit remains a later write-back slice.
- Agent Pulse 2.0 now has a project-owned heartbeat/write-back model plus verified producer wiring helpers, API/UI guidance, stale-heartbeat downgrade, and Hermes-session fallback visibility so active sessions can surface before explicit producer heartbeats are present.
- Email should come after calendar stabilizes, initially read-only and focused on priority/needs-attention surfacing.
- Keep tasks searchable by title, description, status, and project name from the top search bar.
- Website-to-agent messaging is a planned future feature. Before implementation, read `docs/website-to-agent-messaging-plan.md` and the Obsidian note `[[Mentat - Website-to-Agent Messaging Plan]]`; preserve local-only, project-owned write-back boundaries and do not let browser input directly execute shell commands.
- Dashboard project creation remains a future feature; currently new projects are added by updating `data/projects.json` and related tasks in `data/tasks.json`, usually by asking Hermes to do it safely.
- Structured run replay / trace-lite is now implemented as the latest Phase 3 continuation. Keep it read-only toward Hermes core: first version parses existing sessions now; later versions can accept agent-written summaries and explicit task-link/write-back actions.
- The runtime config foundation is now in place: shared repo defaults live in `agent-os.toml`, Brandon's machine-specific overrides can live in gitignored `agent-os.local.toml`, and env/CLI overrides are available for VPS or alternate-local runs later.
- Local lifecycle cleanup is now in place too: runtime state lives under `data/runtime/server-state.json`, runtime state records `launcher_pid` when available, and the helper should be the first stop before manually killing ports.
- Important Windows/Hermes nuance: Hermes background-session kill can still leave the real Python listener alive even when the project launch helpers are correct. Treat `./stop.sh` / `python agent_os_lifecycle.py stop` plus `./status.sh` as the trustworthy stop/verify workflow until that upstream process-manager behavior is fixed.
- Light modularization has started: config parsing was extracted to `runtime_config.py`, browser constants/helpers/API helpers were extracted to `public/core.js`, and the staged plan lives at `docs/modularization-plan.md`.
- Rename boundary update: the browser title/sidebar brand and project/task data now use **Mentat**. Repo paths, helper script names, Python compatibility modules, and many historical planning notes still intentionally use Agent OS / `agent-os` until a larger compatibility-aware rename pass is approved.

## Run locally

Install the pinned Python runtime dependencies first:

```bash
cd /e/code/agent-os
python -m pip install -r requirements.txt
```

Agent OS currently has no npm/package.json dependency step; the frontend remains static HTML/CSS/vanilla JS.

From Git Bash / Hermes terminal, prefer the lifecycle-aware bash launcher:

```bash
cd /e/code/agent-os
./run.sh
```

From Windows Explorer / cmd, use:

```bat
E:/code/agent-os/run.bat
```

Inspect the effective runtime config when needed:

```bash
cd /e/code/agent-os
python server.py --print-config
```

Config precedence is:
- built-in defaults
- `agent-os.toml`
- `agent-os.local.toml` (gitignored, machine-specific)
- environment variables (`AGENT_OS_PORT`, `AGENT_OS_HOST`, `HERMES_HOME`, `OBSIDIAN_VAULT_PATH`, `AGENT_OS_CONFIG`)
- CLI flags (`--port`, `--host`, `--obsidian-vault`, `--config`, etc.)

Lifecycle helpers:
- `./status.sh` — report current managed listeners and runtime state
- `./stop.sh` — stop managed Agent OS listeners and clear runtime state
- `./run.sh` — preflight cleanup + foreground server start in Git Bash / Hermes terminal
- `./run.bat` — preflight cleanup + foreground server start in cmd / Explorer

Then open:

```text
http://localhost:8888
```

The Windows launcher is:

```text
E:/code/agent-os/run.bat
```

## Verification commands

Run from `E:/code/agent-os`:

```bash
python -m py_compile server.py
python -m unittest discover -s tests -v
python - <<'PY'
import json, urllib.request
from pathlib import Path
for p in ['data/projects.json','data/tasks.json','data/attention.json','data/calendar.json']:
    json.loads(Path(p).read_text(encoding='utf-8'))
print('json ok')
for path in ['/', '/api/overview', '/api/attention', '/api/health', '/api/hermes/sessions', '/api/hermes/config', '/api/hermes/search?q=Wilson']:
    with urllib.request.urlopen('http://127.0.0.1:8888'+path, timeout=5) as r:
        print(path, r.status, r.headers.get('Cache-Control'))
search = json.load(urllib.request.urlopen('http://127.0.0.1:8888/api/hermes/search?q=Wilson', timeout=5))
print('search_count', search.get('count'))
first = (search.get('results') or [{}])[0]
if first.get('session_id') and first.get('message_id'):
    detail = json.load(urllib.request.urlopen(f"http://127.0.0.1:8888/api/hermes/sessions/{first['session_id']}?message_id={first['message_id']}", timeout=5))
    print('detail_window', detail.get('message_window'))
PY
```

Expected basics:

- `/` returns 200.
- `/api/overview` returns 200.
- `/api/attention` returns 200.
- `/api/health` returns 200.
- Static assets should send `Cache-Control: no-store` during local UI iteration.

## Attention item behavior

Open manual attention items live in:

```text
data/attention.json
```

Dashboard endpoint:

```text
GET /api/attention
POST /api/attention/<id>/resolve
```

`GET /api/attention` also includes task-derived attention items from `data/tasks.json` when an open task has status `needs_attention`, boolean `needs_attention`, `review_required`, or a `needs attention` / `needs_attention` tag. Task-derived attention items are not standalone records in `attention.json`; the UI should jump to the project/task queue instead of trying to resolve them through the attention endpoint.

Resolving a manual item should not delete history. It should update the item:

```json
{
  "status": "resolved",
  "resolved_at": "..."
}
```

Resolved manual items are hidden from open counts and the Needs Attention panel.

## Important rules

1. Do not write to Hermes core files:
   - `~/.hermes/state.db`
   - `~/.hermes/cron/jobs.json`
   - `~/.hermes/config.yaml`
   - `~/.hermes/skills/`
2. Dashboard write-back is allowed only through server allowlisted project-owned JSON files under `E:/code/agent-os/data/` unless Brandon explicitly approves otherwise.
3. Keep the app local-only for now. Do not expose port 8888 publicly.
4. Mask secrets if any config display is added later.
5. Preserve the clean dark futuristic design direction.
6. Avoid re-adding the removed Latest Hermes Activity section unless Brandon asks for it.

## Code review agent: Wilson Milsen

Wilson Milsen is the project's impartial code and project reviewer.

Wilson's rules:

- Review only; do **not** edit, patch, format, or rewrite files.
- Understand the project purpose before scoring: read `AGENTS.md`, `README.md`, `server.py`, `public/index.html`, `public/app.js`, `public/styles.css`, and the JSON files under `data/` as needed.
- Apply YAGNI: flag code that adds complexity before the project needs it.
- Look for unneeded imports, redundant code, verbose code, repeated markup/data structures, unnecessary runtime work, avoidable DOM churn, and changes that would make Agent OS run faster without changing its purpose or fundamental behavior.
- Grade efficiency, effectiveness, and conciseness, then provide an overall effectiveness score from 1-100.
- Suggestions must be safe, incremental, and compatible with the local-only/read-only-to-Hermes boundaries.

Wilson's review output should include:

```text
Score: <1-100>
Verdict: <one short paragraph>
Must-fix before score >80: <bullets or none>
YAGNI / conciseness suggestions: <bullets>
Performance suggestions: <bullets>
Verification notes: <commands/results if checked>
```

## Known Windows/runtime pitfalls

If requests to `localhost:8888` fail with `Remote end closed connection without response`, stale Python listeners may remain after a crashed session. Clear them from Git Bash:

```bash
netstat -ano | grep ':8888'
for pid in $(netstat -ano | awk '/127\.0\.0\.1:8888/ && /LISTENING/ {print $NF}' | sort -u); do
  taskkill //PID "$pid" //F
 done
```

Then restart one clean server:

```bash
cd /e/code/agent-os
python server.py
```

Browser cache can make UI changes look broken. Static assets are currently served with `Cache-Control: no-store`, and versioned URLs are used in `index.html`.

## Git status/history

This is a local git repo on branch `main` with GitHub remote:

```text
origin https://github.com/hazeion/agent-os.git
```

Use normal git flow from `E:/code/agent-os`: verify, commit intended files, then `git push origin main`.

## Best first steps for a new agent

1. Read this file.
2. Read `README.md`.
3. Read `E:/Obsidian Notes/Agent OS - Implementation Spec.md`.
4. Check current repo status:
   ```bash
   cd /e/code/agent-os
   git status --short
   git log --oneline -5
   ```
5. Run verification commands above.
6. Only then modify code.

## Suggested prompt for spawning a new agent

Use something like:

```text
You are working on Brandon's Agent OS project. Start in E:/code/agent-os. First read AGENTS.md, README.md, and E:/Obsidian Notes/Agent OS - Implementation Spec.md. Then inspect git status and run the existing verification checks. Preserve the local-only dashboard design, do not write to Hermes core files, and keep dashboard write-back limited to E:/code/agent-os/data unless I explicitly approve otherwise.

Task: <describe the specific thing to build or investigate>
```
