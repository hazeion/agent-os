# Agent OS — Agent Handoff Guide

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

## What Agent OS is

Agent OS is Brandon's local mission-control and personal productivity dashboard for Hermes Agent workflows.

Current v1 direction:

- Local-only dashboard.
- Clean dark UI with subtle hacker/futuristic styling.
- Start with only the Agent OS project.
- Use local JSON files for project-owned data.
- Read Hermes core files only; do not write to Hermes core.
- Google Calendar read-only integration is connected through Hermes-managed OAuth; local `calendar.json` remains the fallback.
- No separate Latest Hermes Activity section.

## Current implementation

The app is a small Python HTTP server plus static frontend.

Main files:

```text
server.py
public/index.html
public/styles.css
public/app.js
data/projects.json
data/tasks.json
data/attention.json
data/calendar.json
README.md
inventory.md
```

Current dashboard features:

- Left navigation shell with Today, Agents/Sessions, Calendar, Projects/Tasks, Notes, and Settings destinations.
- Today View command center as the primary mental model.
- Agents/Sessions view shell with searchable recent Hermes sessions and click-to-read conversation detail.
- Message-level Hermes search from read-only `state.db` FTS, with highlighted results that open a focused conversation window around the matched message.
- Historical Session Analytics side panel based on recent Hermes sessions; this is explicitly read-only and not live heartbeat tracking.
- Masked Hermes config/model viewer in Settings.
- `Hello Brandon` header and clean dark futuristic styling.
- Overview metric cards.
- Needs Attention panel.
- Open items from `data/attention.json` can be resolved from the dashboard; tasks tagged `needs attention` / `needs_attention` or otherwise marked `needs_attention` also surface there as task-derived attention items that jump to the relevant task queue.
- Google Calendar read-only integration through Hermes-managed OAuth, with local `calendar.json` fallback.
- Projects / Tasks command center with a Project Portfolio selector, Open Task Queue defaulting to actionable work, Project Status panel, and compact Recent Completed Work timeline.
- Project Portfolio is a fixed-width horizontal card rail with progress bars on project cards; overflow scrolls left/right with rail arrow controls when enough projects exist.
- Project Status deliberately lists percent complete as text/number only, not a second progress bar, to avoid duplicating the portfolio progress bars.
- Task list supports a custom dark status dropdown/listbox with a centered SVG chevron; it toggles open/closed when clicked, closes on outside click/Escape, and keeps completed tasks available by filter but excluded from the default open queue.
- Project cards filter the queue/status/completion timeline and show open/completed counts with progress.
- Cron monitor.
- Obsidian notes panel.
- Health/status indicator.

Near-term project/task direction:

- The next work should finish **Phase 2.5 UI/UX stabilization** before major new integrations: review Today/Projects/Tasks screenshots, polish remaining responsive issues, and remove dummy fixtures when no longer needed.
- Google Calendar is connected at a read-only source level; the next external-data phase should polish the Calendar/Today agenda experience and fallback/stale states.
- Future dashboard write-back should start with dashboard-native project/task creation using project-owned endpoints/data files, not Hermes core writes.
- Agent Pulse 2.0 requires a project-owned heartbeat/write-back model before claiming live active-agent tracking.
- Email should come after calendar stabilizes, initially read-only and focused on priority/needs-attention surfacing.
- Keep tasks searchable by title, description, status, and project name from the top search bar.
- Dashboard project creation remains a future feature; currently new projects are added by updating `data/projects.json` and related tasks in `data/tasks.json`, usually by asking Hermes to do it safely.

## Run locally

From Git Bash:

```bash
cd /e/code/agent-os
python server.py
```

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
2. Dashboard write-back is allowed only inside `E:/code/agent-os/data/` unless Brandon explicitly approves otherwise.
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
