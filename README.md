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

## Current features

Mentat currently includes:

- Today View as the main command center
- front-page Hermes prompt console with live run status and resumable follow-ups
- profile-aware Agent Console routing with profile-scoped models and sessions
- capability-gated Hermes profile discovery, confirmed creation and deletion, built-in skill selection, and a persistent Managed Agents list
- Projects / Tasks workspace with an open queue, task inspector, and completed work timeline
- Agents / Sessions view with managed Hermes profiles plus transcript and replay support
- Hermes session search from `state.db` in read-only mode
- Agent Pulse live heartbeat registry
- read-only Google Calendar integration with local fallback
- Obsidian notes visibility
- local lifecycle helpers for start, stop, and status

## Quick start

### 1) Clone the repo

```bash
git clone https://github.com/hazeion/mentat.git
cd mentat
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
python server.py
```

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
python server.py --port 8890
```

Bind a different host and port:

```bash
python server.py --host 0.0.0.0 --port 8890
```

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

Important local config files:

- `mentat.toml` — shared repo defaults
- `mentat.local.toml` — your machine-specific overrides
- `mentat.local.env` — optional POSIX env exports
- `mentat.local.env.bat` — optional Windows env exports

## Scope

Mentat is a local-first, capability-scoped Hermes control plane. It can perform
explicit Hermes operations, but it is not a general editor for Hermes files.

- Local-only by default on `127.0.0.1:8888`
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

## Main files

```text
server.py
hermes_profiles.py
hermes_profile_creation.py
hermes_profile_deletion.py
hermes_skills.py
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

Then restart:

```bash
./run.sh
```

Or:

```bash
python server.py
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
