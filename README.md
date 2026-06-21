# Agent OS

Local mission-control and personal productivity dashboard for Brandon's Hermes Agent workflows.

## Run

From Git Bash:

```bash
cd /e/code/agent-os
python server.py
```

From Windows Explorer / cmd:

```bat
E:\code\agent-os\run.bat
```

Then open:

`http://localhost:8888`

## Current phase

Phase 3 is now substantially implemented on the vanilla local dashboard:

- Clickable read-only session detail from Hermes `state.db`
- Message-level read-only search over Hermes FTS data
- Search-term highlighting in results and conversation detail
- Search result click-through to a focused conversation window around the matched message
- Historical Session Analytics in Agents / Sessions, clearly labeled as read-only rather than live heartbeat tracking
- 3D Obsidian Constellation on Today, generated from read-only vault wikilinks and navigable with drag/zoom/click
- Masked Hermes config/model viewer in Settings

Remaining Phase 3 candidates: richer message navigation controls, optional result-to-message breadcrumbs, and a more complete agent/profile configuration summary. Google Calendar remains the next likely integration after Hermes-native views feel stable.

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

- Local-only v1
- Reads Hermes data from `HERMES_HOME`
- Writes only inside `E:/code/agent-os/`
- Uses local JSON files for projects, tasks, attention items, and calendar placeholder data
- Google Calendar integration is planned later

## Attention items

Open items from `data/attention.json` appear in the Needs Attention panel. Click **Resolve** on an item after handling it; the dashboard marks it `resolved`, sets `resolved_at`, and hides it from open counts while keeping history in the JSON file.

## Main files

```text
server.py
public/index.html
public/styles.css
public/app.js
data/projects.json
data/tasks.json
data/attention.json
data/calendar.json
inventory.md
```
