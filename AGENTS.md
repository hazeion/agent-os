# Mentat Repository Guide

This file is the quick project guide for contributors and coding agents working in this repository.

## Overview

Mentat is a small local-first dashboard for Hermes-powered workflows.

Goals:

- keep the app local-first
- read Hermes data without writing to Hermes core files
- use simple project-owned local data where possible
- keep the UI practical, lightweight, and easy to understand
- avoid unnecessary complexity or premature framework/tooling choices

The user-facing product name and repository naming convention is **Mentat**.

## Architecture

Mentat is a small Python server with a static frontend.

Core pieces:

```text
server.py
runtime_config.py
mentat_lifecycle.py
mentat.toml
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
- capability-scoped Hermes control through fixed, supported interfaces
- safe project-owned write paths

The project is still a work in progress. Some areas are complete enough to use, while others are still partial or evolving.

## Boundaries

### Hermes capability boundary

Mentat is a local-first, capability-scoped Hermes control plane. A named
Hermes profile is the canonical executable agent identity; `data/agents.json`
contains heartbeat observations and must not become a competing registry.

Hermes mutations are allowed only when an approved adapter operation uses a
fixed Hermes CLI/API call with validation, capability checks, confirmation,
locking, verification, and secret-free audit behavior. Browser text must never
be interpolated into shell commands.

### Do not write directly to Hermes core files

Do not modify:

- `~/.hermes/state.db`
- `~/.hermes/cron/jobs.json`
- `~/.hermes/config.yaml`
- `~/.hermes/skills/`

### Allowed write surface

Dashboard write-back may use project-owned allowlisted storage or an explicitly
approved Hermes adapter capability. Do not directly edit Hermes files to
implement a capability that Hermes exposes through a supported command or API.

The initial profile creator may use fixed Hermes profile operations after the
user confirms a preview. It may also enable or disable identifiers returned by
Hermes' built-in skill catalog through the capability-gated adapter. Managed
Agents may delete a non-default, non-active profile only after a profile-bound
preview and confirmation, while no Mentat console run is active, followed by
profile refresh verification.

Provider inventory and switching are profile-scoped. Read picker context from
Hermes with `load_picker_context()` and request only explicit authenticated
inventory through `build_models_payload(..., explicit_only=True,
picker_hints=True)`. Return provider identifiers, current-selection state, and
safe model metadata only. Never return credential values, paths,
environment-variable names, or tokens to the browser, and never show the full
unsupported provider catalog as if it were configured. Hermes exclusively owns
credential setup and authentication.

A provider switch requires an inventory match, exact preview, profile-bound
confirmation, and no active Agent Console run. Refresh Hermes state afterward
to verify the change and roll back to the prior provider on verification failure
when supported; otherwise report a partial failure and fail closed.

Direct skill-content editing, hub installation, `SOUL.md` editing, clone-all,
rename, credential management, and arbitrary MCP changes remain deferred.

Agent Console slash commands are a separate Mentat allowlist, not a projection
of the Hermes CLI. Add commands through the versioned command manifest with a
fixed dashboard handler, argument declarations, description, safety class, and
tests. Never derive this surface by parsing CLI output or add arbitrary command
passthrough.

Tracked JSON fixtures under `data/` should remain public-safe seed/example data. Avoid committing personal names, local paths, account identifiers, or real message history there.

### Local-first only

Keep the app local-only by default. Do not expose the dashboard publicly unless that direction is explicitly approved and implemented safely.

See `ARCHITECTURE.md` for the complete capability and mutation contract.

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
python mentat_lifecycle.py status
python mentat_lifecycle.py stop
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

- `mentat.local.toml` and local env files are machine-specific and should stay untracked.
- Runtime output, generated artifacts, and scratch data should stay out of the repo.
- If repo-safe documentation conflicts with machine-local setup, prefer generic repo-safe guidance in tracked files and keep machine-specific notes out of the repository.
