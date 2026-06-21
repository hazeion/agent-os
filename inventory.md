# Agent OS Phase 1 Inventory

Generated: `2026-06-20T22:32:04`

Purpose: read-only discovery of Brandon's Hermes Agent installation, Obsidian vault, and host environment before building the first Agent OS dashboard.

Related Obsidian notes:
- `E:/Obsidian Notes/Agentic OS Project Home.md`
- `E:/Obsidian Notes/Agent OS - Research Summary & Prompt Stack.md`
- `E:/Obsidian Notes/Agent OS - Implementation Spec.md`

---

## Summary

Phase 1 inventory is complete. The machine has a working Hermes install, accessible Obsidian vault, Python runtime, Node runtime, and Hermes SQLite session database.

Important findings:

- Hermes home is **not** `C:/Users/hazei/.hermes`; it is `C:/Users/hazei/AppData/Local/hermes`.
- `C:/Users/hazei/.hermes` does not exist.
- Hermes `state.db` exists and is queryable using Python's built-in `sqlite3` module.
- The `sqlite3` command-line executable is **not installed**, so the dashboard should use Python `sqlite3` directly.
- Hermes currently reports **0 scheduled jobs**; `cron/jobs.json` does not currently exist.
- Obsidian vault is accessible at `E:/Obsidian Notes`.
- Agent OS project folder now exists at `E:/code/agent-os/` because this inventory file was written there.
- The dashboard should use port `8888` and refresh every 30 seconds.

---

## Host environment

| Item | Value |
|---|---|
| OS | Windows 10 / `Windows-10-10.0.26200-SP0` |
| Shell used by Hermes terminal tool | Git Bash / MSYS bash |
| Home | `C:/Users/hazei` |
| Working directory during inventory | `C:/Users/hazei` |
| `HERMES_HOME` | `C:/Users/hazei/AppData/Local/hermes` |
| Python | `3.11.5` |
| Node | `v22.23.0` |
| npm | `10.9.8` |
| sqlite3 CLI | Not installed |
| Hermes Agent | `v0.17.0 (2026.6.19)` |
| Hermes project source | `C:/Users/hazei/AppData/Local/hermes/hermes-agent` |

### Host memory

| Metric | Value |
|---|---|
| Memory load | `26%` |
| Total RAM | `63.7 GB` |
| Available RAM | `46.6 GB` |

### Disk snapshot

| Drive | Total | Used | Free | Used % |
|---|---:|---:|---:|---:|
| `C:/` | `464.3 GB` | `402.5 GB` | `61.7 GB` | `86.7%` |
| `E:/` | `953.9 GB` | `421.0 GB` | `532.9 GB` | `44.1%` |

Note: `C:/` is relatively full. Agent OS build files should stay on `E:/code/agent-os/` as planned.

---

## Hermes installation

| Resource | Path | Exists | Size |
|---|---|---:|---:|
| Hermes home | `C:/Users/hazei/AppData/Local/hermes` | yes | `3.6 GB` |
| Config | `C:/Users/hazei/AppData/Local/hermes/config.yaml` | yes | `11.9 KB` |
| Env file | `C:/Users/hazei/AppData/Local/hermes/.env` | yes | `23.1 KB` |
| State DB | `C:/Users/hazei/AppData/Local/hermes/state.db` | yes | `2.5 MB` |
| Cron dir | `C:/Users/hazei/AppData/Local/hermes/cron` | yes | `0.0 B` |
| Cron jobs file | `C:/Users/hazei/AppData/Local/hermes/cron/jobs.json` | no | n/a |
| Skills dir | `C:/Users/hazei/AppData/Local/hermes/skills` | yes | `5.6 MB` |
| Logs dir | `C:/Users/hazei/AppData/Local/hermes/logs` | yes | `1.6 MB` |

### Hermes status highlights

From `hermes status`:

- Model: `gpt-5.5`
- Provider: `OpenAI Codex`
- Nous Portal: logged in
- OpenAI Codex: logged in
- Terminal backend: `local`
- Gateway service: stopped
- Messaging platforms: not configured
- Scheduled jobs: `0`
- Active sessions: `1`
- Update available: Hermes is `76 commits behind`; not relevant for Agent OS v1 unless a bug is encountered.

---

## Hermes config notes

The config file exists and was read with secret masking. The dashboard should display config only in masked/summarized form.

Observed top-level config sections include:

- `agent`
- `approvals`
- `auxiliary`
- `bedrock`

Notable observed values from masked config:

```yaml
agent:
  max_turns: 90
  reasoning_effort: high
  task_completion_guidance: true
  tool_use_enforcement: auto
approvals:
  cron_mode: deny
  mode: manual
```

Implementation rule:

- Never display raw values for keys containing `api_key`, `token`, `secret`, `password`, `credential`, or `auth`.
- Never write to this file from Agent OS v1.

---

## Hermes cron inventory

Current state:

- `cron/jobs.json` does not exist.
- `hermes status` reports `Scheduled Jobs: 0`.
- Dashboard should handle this gracefully with an empty-state message like:

> No scheduled Hermes cron jobs found yet.

Recommended API behavior:

```json
{
  "jobs": [],
  "count": 0,
  "source": "C:/Users/hazei/AppData/Local/hermes/cron/jobs.json",
  "exists": false
}
```

---

## Hermes session database

Path:

`C:/Users/hazei/AppData/Local/hermes/state.db`

The database is queryable using Python's built-in `sqlite3` library. The `sqlite3` CLI is unavailable, so the server should use Python directly.

### Tables

```text
compression_locks
messages
messages_fts
messages_fts_config
messages_fts_content
messages_fts_data
messages_fts_docsize
messages_fts_idx
messages_fts_trigram
messages_fts_trigram_config
messages_fts_trigram_content
messages_fts_trigram_data
messages_fts_trigram_docsize
messages_fts_trigram_idx
schema_version
sessions
sqlite_sequence
state_meta
```

### Counts

| Table | Count |
|---|---:|
| `sessions` | `3` |
| `messages` | `75` |
| `messages_fts` | `75` |
| `messages_fts_trigram` | `75` |
| `compression_locks` | `0` |
| `schema_version` | `1` |
| `state_meta` | `2` |

### `sessions` columns

```text
id
source
user_id
model
model_config
system_prompt
parent_session_id
started_at
ended_at
end_reason
message_count
tool_call_count
input_tokens
output_tokens
cache_read_tokens
cache_write_tokens
reasoning_tokens
cwd
billing_provider
billing_base_url
billing_mode
estimated_cost_usd
actual_cost_usd
cost_status
cost_source
pricing_version
title
api_call_count
handoff_state
handoff_platform
handoff_error
rewind_count
archived
```

### `messages` columns

```text
id
session_id
role
content
tool_call_id
tool_calls
tool_name
timestamp
token_count
finish_reason
reasoning
reasoning_content
reasoning_details
codex_reasoning_items
codex_message_items
platform_message_id
observed
active
```

### Recent sessions sample

| ID | Title | Source |
|---|---|---|
| `cron_0f99882844ed_20260619_182318` | `test-telegram-delivery · Jun 19 18:23` | `cron` |
| `20260620_161156_e9d2a5` | null | `tui` |
| `20260620_165530_341d68` | `Initial Greeting and Help Offer` | `tui` |

Implementation notes:

- Use read-only SQLite URI mode if possible.
- For recent sessions, query from `sessions` sorted by `started_at` or `ended_at`; there is no `updated_at` column.
- Use `title`, `source`, `message_count`, `tool_call_count`, `input_tokens`, `output_tokens`, and `estimated_cost_usd` for dashboard cards.
- For activity feed, query the `messages` table ordered by `timestamp DESC` and summarize role/content snippets.

---

## Skills inventory

Skills directory:

`C:/Users/hazei/AppData/Local/hermes/skills`

Detected skill count: `75`

Relevant installed Agent OS skill:

`C:/Users/hazei/AppData/Local/hermes/skills/autonomous-ai-agents/agent-os/SKILL.md`

Useful linked reference:

`C:/Users/hazei/AppData/Local/hermes/skills/autonomous-ai-agents/agent-os/references/brandon-agent-os-discovery.md`

Sample skills:

```text
autonomous-ai-agents/agent-os/SKILL.md
autonomous-ai-agents/claude-code/SKILL.md
autonomous-ai-agents/codex/SKILL.md
autonomous-ai-agents/hermes-agent/SKILL.md
autonomous-ai-agents/opencode/SKILL.md
creative/architecture-diagram/SKILL.md
creative/sketch/SKILL.md
data-science/jupyter-live-kernel/SKILL.md
devops/kanban-orchestrator/SKILL.md
devops/kanban-worker/SKILL.md
```

Dashboard v1 should not need to render all skills, but later a Skills panel could use this directory.

---

## Obsidian inventory

Vault path:

`E:/Obsidian Notes`

Detected notes:

| Note | Size | Purpose |
|---|---:|---|
| `Agent OS - Implementation Spec.md` | `8.2 KB` | Current product/implementation spec |
| `Agent OS - Research Summary & Prompt Stack.md` | `13.3 KB` | Research summary + phased prompt stack |
| `Agentic OS Project Home.md` | `4.2 KB` | Project home note |
| `Brandon Thomas - About Me.md` | `1.9 KB` | User background/goals |

Dashboard v1 should show a visible Project Notes panel with these first three project notes.

Recommended Project Notes card fields:

```json
{
  "title": "Agent OS - Implementation Spec",
  "path": "E:/Obsidian Notes/Agent OS - Implementation Spec.md",
  "modified_at": "...",
  "excerpt": "Build Brandon's first local Agent OS dashboard..."
}
```

---

## Agent OS project folder

Planned project path:

`E:/code/agent-os/`

At the start of inventory, this folder did not exist. It now exists because this inventory file was written into it.

Recommended v1 file layout:

```text
E:/code/agent-os/
  inventory.md
  server.py
  README.md
  data/
    projects.json
    tasks.json
    attention.json
    calendar.json
  public/
    index.html
    styles.css
    app.js
```

---

## Dashboard v1 runtime decisions

| Decision | Value |
|---|---|
| Port | `8888` |
| Refresh interval | `30 seconds` |
| Development startup | Start server only, print URL |
| Later startup | Start server and auto-open browser |
| Initial data | Include Agent OS-specific seed items |
| Calendar v1 | Local `calendar.json` placeholder/manual data |
| Google Calendar | Add later via OAuth after dashboard skeleton works |
| Dashboard writes | Only under `E:/code/agent-os/` |
| Hermes files | Read-only |

---

## Initial local data recommendation

### `projects.json`

```json
[
  {
    "id": "project_agent_os",
    "name": "Agent OS",
    "type": "software",
    "status": "active",
    "description": "Local mission-control and personal productivity dashboard for Hermes Agent workflows.",
    "obsidian_note": "Agentic OS Project Home",
    "created_at": "2026-06-20T22:32:04",
    "updated_at": "2026-06-20T22:32:04"
  }
]
```

### Seed tasks

Recommended seed tasks for v1:

```json
[
  {
    "id": "task_inventory",
    "title": "Run Hermes inventory",
    "description": "Discover Hermes paths, state DB shape, cron availability, Obsidian notes, and runtime tools.",
    "project": "Agent OS",
    "status": "completed",
    "priority": "high",
    "assignee": "Hermes",
    "due_date": null,
    "source": "agent",
    "tags": ["phase-1", "inventory"],
    "review_required": false,
    "needs_attention": false,
    "created_at": "2026-06-20T22:32:04",
    "updated_at": "2026-06-20T22:32:04",
    "completed_at": "2026-06-20T22:32:04"
  },
  {
    "id": "task_dashboard_shell",
    "title": "Build dashboard shell",
    "description": "Create Python server, local JSON data files, and first dark dashboard UI.",
    "project": "Agent OS",
    "status": "todo",
    "priority": "high",
    "assignee": "Hermes",
    "due_date": null,
    "source": "manual",
    "tags": ["phase-2", "dashboard"],
    "review_required": false,
    "needs_attention": false,
    "created_at": "2026-06-20T22:32:04",
    "updated_at": "2026-06-20T22:32:04",
    "completed_at": null
  }
]
```

### Seed attention item

```json
[
  {
    "id": "attn_review_spec",
    "title": "Review Agent OS implementation direction",
    "description": "Confirm that the dashboard inventory and v1 scope match Brandon's expectations before moving beyond the shell.",
    "type": "review_required",
    "source": "agent",
    "project": "Agent OS",
    "severity": "medium",
    "status": "open",
    "created_at": "2026-06-20T22:32:04",
    "resolved_at": null,
    "link": "[[Agent OS - Implementation Spec]]"
  }
]
```

---

## Phase 2 build guidance

The next phase should build the first working dashboard shell.

Recommended approach:

1. Create `server.py` using only the Python standard library if possible.
2. Serve static files from `public/`.
3. Expose JSON API endpoints:
   - `/api/overview`
   - `/api/projects`
   - `/api/tasks`
   - `/api/attention`
   - `/api/calendar`
   - `/api/obsidian-notes`
   - `/api/hermes/sessions`
   - `/api/hermes/crons`
   - `/api/health`
4. Use `data/*.json` for Agent OS-owned writable state.
5. Use read-only Python `sqlite3` for Hermes sessions.
6. Read `cron/jobs.json` only if it exists; otherwise return empty jobs.
7. Style as clean dark dashboard with subtle futuristic/hacker accents.
8. Start manually with:

```bash
cd /e/code/agent-os
python server.py
```

Expected URL:

`http://localhost:8888`

---

## Risks / notes

- Hermes source tree is large (`3.6 GB` Hermes home); avoid scanning the full tree on every refresh.
- `C:/` drive is 86.7% used; keep generated dashboard artifacts on `E:/`.
- `cron/jobs.json` absent is normal right now; dashboard must treat cron monitoring as empty state rather than error.
- `sqlite3` CLI is unavailable; use Python library.
- Google Calendar integration requires OAuth setup later; do not block v1 on it.
- Dashboard should not expose itself publicly; local-only for now.
