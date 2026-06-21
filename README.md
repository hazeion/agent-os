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
