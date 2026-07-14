# Mentat

Mentat is a small local-first dashboard for people who want a more practical way to use AI while managing a real build project.

It is built around Hermes-powered workflows and gives you one place to see projects, tasks, agents, sessions, calendar context, notes, and the next things that need attention.

This project is still a work in progress. It is actively being developed, and some ideas are ahead of the current implementation. The foundation is here, but not every feature is fully realized yet.

## Overview

Mentat is a small Python server with a static frontend.

It is designed to:

- stay local-first
- read Hermes data without writing to Hermes core files
- make active work, task flow, and session history easier to follow
- help people build with AI without dragging in a heavyweight stack

Current stack:

- Python backend
- static HTML, CSS, and vanilla JavaScript frontend
- local JSON files for project-owned data
- private SQLite metadata plus content-addressed blobs for Console files
- optional Hermes-aware setup through the included wizard

There is currently **no npm install step**.

## Requirements

- Python 3
- Hermes Agent for the Hermes-aware setup flow and read-only integrations

If you only want to launch the local dashboard, Python is enough. If you want the Hermes-aware setup flow, session views, and related integrations, make sure Hermes is installed and configured.

## Current status

Mentat is usable today, but it is still evolving.

- core local dashboard workflows are in place
- several read-only integrations are working
- project-owned local data flows are implemented
- some planned features are still partial, rough around the edges, or not built yet

If you try it now, expect a real working project, not a finished product.

### Deferred frontend direction

Mentat should eventually render its major dashboard surfaces independently as
their data arrives, with explicit loading, ready, empty, and error states rather
than waiting for the complete dashboard payload before showing useful content.
This could be implemented incrementally in the current frontend or become one
reason to adopt a small component framework such as React later. It is a future
performance and interaction goal, not part of the current attachment/database
work and not, by itself, a reason for an immediate framework migration.

## Current features

Mentat currently includes:

- Today View as the main command center, with quick capture, deliberate daily
  planning, manual ordering, time estimates, reminders, calendar context, and
  agent work that needs attention or review
- front-page Hermes prompt console with live run status and resumable follow-ups
- Agent Console image, text, and source attachments; safe fenced-code rendering;
  generated-file cards; and restricted project-workspace file snapshots
- manifest-driven `/model`, `/new`, and `/help` dashboard commands with no Hermes CLI passthrough
- profile-aware Agent Console routing with profile-scoped models and sessions
- capability-gated Hermes profile discovery, confirmed creation and deletion, built-in skill selection, persistent runtime name/role synchronization, and a Managed Agents list
- confirmed provider switching among providers Hermes reports as already authenticated for the selected profile, available from both Managed Agents and the Agent Console
- private local Agent Console history across Mentat restarts
- Projects / Tasks workspace with an open queue, task inspector, completed work
  timeline, previewed task deletion, subtasks, dependencies, recurrence,
  scheduled blocks, saved decision views, calendar links, and note attachments
- capability-gated delegation of a Mentat task to a named Hermes profile through
  Hermes' supported Kanban interface, with preview, confirmation, verification,
  progress refresh, blocking questions, retries, revision requests, and result
  acceptance
- Agent Activity / Review inbox for linked work that is running, blocked, ready
  for review, failed, or recently completed
- Agents / Sessions view with managed Hermes profiles plus transcript and replay support
- Hermes session search from `state.db` in read-only mode
- read-only Hermes cron inventory, with unsupported queue controls failing closed
- Agent Pulse live heartbeat registry
- read-only Google Calendar integration with local fallback, plus Mentat-owned
  task creation and task links from calendar events
- searchable Obsidian notes with safe vault-relative task attachments and an
  explicit Open in Obsidian action
- grouped global search across tasks, projects, sessions, notes, and calendar
  events; selecting a result performs navigation
- post-creation and Managed Agent actions to test profile identity or begin
  assigning the agent's first task
- local lifecycle helpers for start, stop, and status

## Quick start

### 1) Clone the repo

```bash
git clone https://github.com/hazeion/agent-os.git
cd agent-os
```

### 2) Install Python dependencies

```bash
python -m pip install -r requirements.txt
```

### 3) Run the setup wizard (recommended)

This creates your machine-specific local config files and tries to detect your Hermes profile.

```bash
python scripts/mentat_setup.py
```

The wizard creates local-only files such as:

- `mentat.local.toml`
- `mentat.local.env`
- `mentat.local.env.bat`

It does **not** write credentials or tokens.

### 4) Launch Mentat

Once the server is running, open:

```text
http://localhost:8888
```

## Launch instructions by OS

### Windows

#### Option A: Git Bash / Hermes terminal

```bash
cd "/path/to/mentat"
./run.sh
```

#### Option B: Command Prompt / Explorer

```bat
cd /d C:\path\to\mentat
run.bat
```

You can also double-click `run.bat` in Explorer.

#### Stop or check status on Windows

From Git Bash:

```bash
./status.sh
./stop.sh
```

From Command Prompt:

```bat
python mentat_lifecycle.py status
python mentat_lifecycle.py stop
```

### macOS

```bash
cd "/path/to/mentat"
python -m pip install -r requirements.txt
python scripts/mentat_setup.py
./run.sh
```

To stop or check status:

```bash
./status.sh
./stop.sh
```

If Hermes is not installed yet, install and configure it first, then rerun the setup wizard:

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes setup
hermes doctor
```

### Linux

```bash
cd "/path/to/mentat"
python -m pip install -r requirements.txt
python scripts/mentat_setup.py
./run.sh
```

To stop or check status:

```bash
./status.sh
./stop.sh
```

If Hermes is not installed yet, install and configure it first, then rerun the setup wizard:

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes setup
hermes doctor
```

## Minimal launch flow

If you do not want to use the setup wizard, you can launch directly:

```bash
python "$(pwd)/server.py"
```

Use the absolute script path for direct launches so `status.sh` and `stop.sh`
can still identify Mentat if its HTTP health probe becomes unavailable.

Then open:

```text
http://localhost:8888
```

## Useful commands

Print the effective runtime config:

```bash
python server.py --print-config
```

Run on a different port:

```bash
./run.sh --port 8890
```

Mentat accepts loopback hosts only (`localhost`, `127.0.0.1`, or `::1`). It
refuses non-loopback binds because the dashboard does not provide remote-access
authentication. Use `--port` when you need a different local address.

Check lifecycle state:

```bash
python mentat_lifecycle.py status
```

Stop the managed server:

```bash
python mentat_lifecycle.py stop
```

## Configuration

Mentat uses layered runtime configuration in this order:

1. built-in defaults
2. `mentat.toml`
3. `mentat.local.toml`
4. environment variables
5. CLI flags

Useful overrides:

- `MENTAT_PORT`
- `MENTAT_HOST`
- `MENTAT_APP_NAME`
- `HERMES_HOME`
- `OBSIDIAN_VAULT_PATH`
- `MENTAT_CONFIG`

`MENTAT_HOST` may select a loopback spelling only. Values such as `0.0.0.0` or
a LAN address are rejected at startup.

Important local config files:

- `mentat.toml` — shared repo defaults
- `mentat.local.toml` — your machine-specific overrides
- `mentat.local.env` — optional POSIX env exports
- `mentat.local.env.bat` — optional Windows env exports

## Scope

Mentat is a local-first, capability-scoped Hermes control plane. It can perform
explicit Hermes operations, but it is not a general editor for Hermes files.

- Local-only on `127.0.0.1:8888` by default, with non-loopback binds rejected
- Reads Hermes data from `HERMES_HOME`
- Writes project-owned local data through allowlisted storage
- Mutates Hermes only through approved, fixed CLI/API capabilities
- Does **not** directly edit Hermes core files
- Keeps secrets in Hermes, not in this repo

Please do not write to:

- `~/.hermes/state.db`
- `~/.hermes/cron/jobs.json`
- `~/.hermes/config.yaml`
- `~/.hermes/skills/`

A named Hermes profile is Mentat's canonical executable agent identity.
`data/agents.json` remains heartbeat/observation data, not a second profile
registry. See `ARCHITECTURE.md` for validation, confirmation, locking, rollback,
and audit requirements for every write-capable Hermes operation.

### Provider inventory and switching

Mentat asks Hermes for provider picker context for the selected profile and
limits the UI to providers Hermes reports as explicitly configured and
authenticated. The current provider is distinguished from other authenticated
choices. Mentat does not inspect, store, or return credential values, credential
paths, environment-variable names, or tokens; credentials are configured and
managed only through Hermes.

Changing providers requires a preview and profile-bound confirmation, is blocked
while an Agent Console run is active, and is verified by refreshing Hermes state.
If verification fails, Mentat attempts to restore the previous provider when the
Hermes capability supports rollback and otherwise reports a partial failure.
The switch control is advertised only when the installed Hermes runtime exposes
the supported profile-model operation; otherwise Mentat leaves provider state
read-only and fails closed. The former direct Agent Console model-mutation route
is not supported—provider/model changes use this confirmed provider workflow.

### Project task deletion

Mentat can delete a task from its project-owned `data/tasks.json` store only
after showing an exact preview and receiving its matching confirmation. The
confirmation is tied to the complete current task state, so any changed task
must be previewed again. The locked update is atomic, and deletion cannot
be undone from Mentat.

### Personal planning and durable agent work

Mentat tasks in `data/tasks.json` are the source of truth for personal planning.
In addition to their project, status, priority, and due date, they can carry a
daily-plan flag and rank, an estimate and scheduled block, browser reminders,
subtasks, dependencies, recurrence, calendar links, Obsidian note links, and a
safe reference to delegated Hermes work. These fields remain project-owned;
Mentat does not turn Hermes session or heartbeat data into a competing task
registry.

The Today view brings the planning fields together with quick capture, the next
calendar events, due reminders, Agent Activity, review decisions, and recent
completion context. Built-in task views cover Today, Waiting, Review, Blocked,
Someday, and completed work. Browser notification permission is requested only
after the operator chooses **Enable Reminders**; reminders remain visible in the
dashboard when browser notifications are unavailable or not granted.

Completing a recurring task may create its next Mentat-owned occurrence. Task
dependencies are validated against existing task identifiers, and self-links,
missing dependencies, and dependency cycles are rejected. Google Calendar
remains read-only: creating a task from an event or linking an event writes only
to Mentat's task store and never changes the Google event.

Obsidian attachments are stored as validated vault-relative Markdown paths.
Delegation previews may include bounded context from attached notes, but Mentat
does not edit the notes or expose an arbitrary local-file operation. Opening a
note is an explicit browser action using Obsidian's application link.

### Hermes Kanban delegation boundary

Hermes' supported Kanban CLI is Mentat's only durable agent-delegation mutation
path. Mentat does not edit Hermes Kanban storage, use `agent_messages.json` as an
execution queue, or treat Agent Console prompts as a durable task scheduler.

Before showing delegation controls, Mentat probes the installed Hermes runtime
for the required Kanban capabilities. A delegation preview is bound to the
complete current Mentat task and the requested board, profile, workspace mode,
instructions, and attached-note context. Confirmation is rejected if any bound
input changes. Under the Kanban mutation lock, Mentat then invokes only the
adapter's fixed, validated command, reads the resulting Hermes task back, and
persists safe task/run/session/review references only after verification.

Unsupported commands and missing capabilities fail closed. If Hermes reports
that it created or changed work but Mentat cannot verify the result, Mentat
reports a partial failure and directs the operator to inspect Hermes before
retrying. Follow-up mutations such as replies, retries, stop/reclaim, revision
requests, and blocking decisions use the same preview and confirmation
contract, followed by a Hermes refresh when a remote mutation occurs. Accepting
a reviewed result is a Mentat-owned decision that completes the personal task
without introducing an extra Hermes mutation.

Agent Activity groups only task-linked delegation state into needs-input,
running, ready-for-review, failed, and recently-completed queues. It is an
operator review surface, not a replacement for Hermes' task or run history.

### Hermes cron boundary

Mentat currently displays Hermes cron inventory read-only. The installed Hermes
runtime does not expose an atomic operation that both verifies the expected job
revision and confirms the job is still enabled while queueing its next scheduler
tick. The available trigger operation cannot safely provide that guarantee, so
Mentat does not advertise queueing as available and its queue controls fail
closed.

Next-tick queueing remains dependent on an upstream Hermes compare-and-swap
capability. Mentat will not approximate it by editing
`~/.hermes/cron/jobs.json` or chaining non-atomic operations. An immediate
**Run now** action would be a separate product feature with its own execution
and confirmation contract; it remains deferred rather than serving as a
substitute. Mentat also does not create, edit, enable, disable, or delete Hermes
cron jobs.

## Main project-owned data files

```text
data/projects.json
data/tasks.json
data/attention.json
data/calendar.json
data/agents.json
data/agent_messages.json
```

These tracked JSON files are intended to remain **public-safe seed/example data**.
Do not commit personal names, local filesystem paths, real messages, or private account details into them.
Use local overrides or untracked runtime files for machine-specific/private content.

Agent Console history is stored separately at `data/runtime/agent-console-runs.json`,
which is gitignored. Mentat keeps at most 24 run summaries there. Each summary has
run metadata plus a redacted excerpt of the prompt (500 characters), response
(2,000 characters), and error (1,000 characters); complete prompt and response
content is not written to this history file. Up to 40 bounded, redacted status
events are retained per run. Runs that were active when Mentat
stopped are shown as interrupted after restart. Missing, corrupt, or unknown
history formats fall back to an empty history without preventing startup.
On platforms that support POSIX permissions, Mentat writes the runtime directory
for its owner only and the history file with owner read/write permissions. On
startup, existing valid summaries are re-redacted through the current policy;
corrupt history is permission-restricted but preserved for manual recovery.

Agent Console file metadata is stored in the gitignored
`data/runtime/mentat.sqlite3` database. File bytes live beside it in private,
SHA-256 content-addressed blob storage; duplicate bytes share a blob while each
attachment keeps its own opaque identity and display metadata. Browser responses
never include blob keys, hashes, or local filesystem paths. Uploads accept
validated UTF-8 text/source files and PNG, JPEG, GIF, or WebP images. Archives,
executables, SVG, secrets, path traversal, and mismatched file content fail
closed. Text is always served as plain text with `nosniff`; only validated raster
images may render inline.

The Console composer keeps accepted files in a persistent **Prompt
attachments** tray until the turn is sent or the user removes them. Submitted
turns label retained inputs as files used for prompt context, and upload
failures remain visible in the composer instead of collapsing with the upload
indicator. For Hermes image execution, Mentat creates a private per-run copy
with the validated image extension, passes that fixed path to Hermes, and
removes the transient copy after the run.

Unsubmitted uploads expire after two hours. Removing or releasing the last run
reference begins a one-hour deletion grace. Active and retained runs protect
their input and generated files; evicting a run releases both. A bounded cleanup
pass runs at startup and every 30 minutes, retries failed deletes with backoff,
and reconciles interrupted uploads, missing blobs, crash-orphaned references,
and old untracked blob files.

Every Console run receives a private, run-owned export directory through a fixed
server-generated execution context. After Hermes exits, Mentat scans only that
directory, snapshots allowed files without following symlinks, stores them as
run output attachments, and removes successfully registered exports. Workspace
selection is limited to configured project roots (the Mentat repository today),
returns relative paths only, excludes VCS/runtime/hidden/secret/executable paths,
and snapshots the selected file into blob storage before it becomes prompt
context. Mentat never treats a path mentioned in model prose as an artifact.

Agent Console events use a stable schema with `schema_version`, `run_id`,
monotonic `sequence`/`cursor`, `type` (plus the legacy `kind` alias), `timestamp`,
structured `data`, and `display_text` (plus the legacy `message` alias). A GET to
`/api/agent-console/runs/<run-id>` still returns the complete run for existing
clients. Supplying `?after=<cursor>` returns only newer retained events, a fresh
run-state snapshot, and `next_cursor` for lightweight polling. If a cursor predates
the retained window, `cursor_reset_required` tells the client to rebuild from the
returned retained events. Mentat does not infer tool calls by parsing unstable
Hermes CLI output, and this contract intentionally uses ordinary local polling
rather than SSE or WebSockets.

## Main files

```text
server.py
command_manifest.py
agent_run_history.py
hermes_profiles.py
hermes_profile_creation.py
hermes_profile_deletion.py
hermes_profile_identity.py
hermes_skills.py
hermes_kanban.py
task_planning.py
runtime_config.py
mentat_lifecycle.py
scripts/mentat_setup.py
scripts/agent_heartbeat.py
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
mentat.toml
README.md
ARCHITECTURE.md
inventory.md
```

## Troubleshooting

### Port 8888 is stuck or the browser says the connection closed

Sometimes a stale Python listener is left behind after a crash or interrupted session.

On Windows Git Bash:

```bash
netstat -ano | grep ':8888'
for pid in $(netstat -ano | awk '/127\\.0\\.0\\.1:8888/ && /LISTENING/ {print $NF}' | sort -u); do
  taskkill //PID "$pid" //F
done
```

Then restart through the managed launcher:

```bash
./run.sh
```

### Hermes was not detected by the setup wizard

Install or finish configuring Hermes first, then rerun:

```bash
hermes setup
hermes doctor
python scripts/mentat_setup.py
```

On Linux or macOS, if Hermes is not installed yet:

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes setup
hermes doctor
```

## Verification

Basic sanity check:

```bash
python -m py_compile server.py
python -m unittest discover -s tests -v
```

You can also confirm the server config before launch:

```bash
python server.py --print-config
```

## Project notes

Mentat is the user-facing name and the repository naming convention.

This project is still local-first and intentionally small in scope. The goal is to make it easier for other people to adopt, configure, and use without a lot of setup friction.

Mentat is being developed in the open and is still taking shape. If something feels unfinished, that is probably because it is. The aim right now is to keep the project useful, local-first, and easy to understand while the feature set matures.
