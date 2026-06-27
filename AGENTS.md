# Mentat / Agent OS — repository guide

This file is the quick project guide for contributors and coding agents working in this repository.

## Overview

Mentat is a small local-first dashboard for Hermes-powered workflows.

Goals:

- keep the app local-first
- read Hermes data without writing to Hermes core files
- use simple project-owned local data where possible
- keep the UI practical, lightweight, and easy to understand
- avoid unnecessary complexity or premature framework/tooling choices

The user-facing product name is **Mentat**. Some repo paths, helper names, and compatibility references still use `agent-os` / Agent OS.

## Architecture

Mentat is a small Python server with a static frontend.

Core pieces:

```text
server.py
runtime_config.py
agent_os_lifecycle.py
agent-os.toml
run.sh / stop.sh / status.sh
run.bat / stop.bat / status.bat
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
```

## Current direction

Current priorities:

- local-only dashboard experience
- clean dark UI
- project/task visibility and actionability
- read-only Hermes session visibility
- safe project-owned write paths only

The project is still a work in progress. Some areas are complete enough to use, while others are still partial or evolving.

## Boundaries

### Do not write to Hermes core files

Do not modify:

- `~/.hermes/state.db`
- `~/.hermes/cron/jobs.json`
- `~/.hermes/config.yaml`
- `~/.hermes/skills/`

### Allowed write surface

Dashboard write-back should stay limited to project-owned files and allowlisted endpoints, typically under `data/`.

### Local-first only

Keep the app local-only by default. Do not expose the dashboard publicly unless that direction is explicitly approved and implemented safely.

## Setup and run

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Recommended local setup:

```bash
python scripts/mentat_setup.py
```

Launch on Windows (Git Bash / Hermes terminal):

```bash
./run.sh
```

Launch on Windows (cmd / Explorer):

```bat
run.bat
```

Launch directly on any OS:

```bash
python server.py
```

Default local URL:

```text
http://localhost:8888
```

Useful commands:

```bash
python server.py --print-config
python agent_os_lifecycle.py status
python agent_os_lifecycle.py stop
```

## Verification

Basic checks:

```bash
python -m py_compile server.py
python -m unittest discover -s tests -v
```

## UI and implementation guidance

- Prefer simple, readable code over clever abstractions.
- Preserve the clean dark styling direction.
- Avoid reintroducing removed/redundant dashboard surfaces without a clear product reason.
- Keep completed work visible when useful; do not assume deletion is the right default.
- Favor incremental changes over broad rewrites.
- Apply YAGNI: do not add complexity before the project needs it.

## Repository notes

- `agent-os.local.toml` and local env files are machine-specific and should stay untracked.
- Runtime output, generated artifacts, and scratch data should stay out of the repo.
- If repo-safe documentation conflicts with machine-local setup, prefer generic repo-safe guidance in tracked files and keep machine-specific notes out of the repository.
