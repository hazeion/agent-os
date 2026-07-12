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
hermes_kanban.py
task_planning.py
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
- day planning, review, and personal task-management depth
- durable task delegation through Hermes' supported Kanban adapter
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
when supported; otherwise report a partial failure and fail closed. Advertise
switching only when the installed Hermes runtime exposes the supported fixed
profile-model operation. Do not restore a direct, unconfirmed model-mutation
route.

Project-owned task deletion requires an exact preview, confirmation bound to
the current task state, and a locked atomic update. A changed task must be
previewed again.

Project-owned personal tasks are the planning source of truth. Optional planning
fields may cover Today selection/order, estimates, scheduled blocks, browser
reminders, subtasks, dependencies, recurrence, calendar links, note links,
planning state, and safe delegation references. Validate these fields through
`task_planning.py`; reject missing/self/cyclic dependencies and unsafe note
paths, and create recurring successors only through the locked task update.

Hermes Kanban is the only approved durable delegation mutation path. Use the
fixed, shell-free operations in `hermes_kanban.py`; never edit Hermes Kanban
storage, turn Agent Messages into an execution queue, or treat Agent Console as
a durable scheduler. Delegation creation and remote follow-up actions require a
capability match, exact task-and-intent preview, matching confirmation, the
Kanban mutation lock, a project-owned in-flight reservation, and operation-
specific post-operation read-back verification. Action confirmations must bind
the refreshed live Hermes task/run state as well as the current Mentat task.
Changed input, unsupported capabilities, and unverified results fail closed. A
Hermes-accepted operation that cannot be verified must be reported as a partial
failure without claiming completion. Store only normalized, secret-free
references and bounded audit text in the Mentat task.

Google Calendar stays read-only. Creating or linking a task from a verified
calendar event may write Mentat task metadata only. Obsidian note attachments
must be vault-relative validated Markdown paths; attached content used for a
delegation preview must remain bounded, and Mentat must not edit the note.

Grouped dashboard search is navigation-only and may cover tasks, projects,
session metadata, notes, and cached/local calendar events. Typing must not change
views; navigate only after an explicit result selection. Browser notification
permission must be requested only from an explicit user action.

Hermes cron inventory is currently read-only. The installed Hermes runtime lacks
an atomic expected-revision, enabled-only operation for queueing the next
scheduler tick, so Mentat must advertise no working queue capability and all
queue controls must fail closed. Safe next-tick queueing requires an upstream
Hermes compare-and-swap capability; do not approximate it with a read-then-
trigger sequence or a direct cron-store write. An immediate **Run now** action
is a separate deferred product choice, not a substitute. Do not create, edit,
enable, disable, or delete Hermes cron jobs, and never write the cron store
directly.

Direct skill-content editing, hub installation, `SOUL.md` editing, clone-all,
rename, credential management, and arbitrary MCP changes remain deferred.

Agent Console slash commands are a separate Mentat allowlist, not a projection
of the Hermes CLI. Add commands through the versioned command manifest with a
fixed dashboard handler, argument declarations, description, safety class, and
tests. Never derive this surface by parsing CLI output or add arbitrary command
passthrough.

Tracked JSON fixtures under `data/` should remain public-safe seed/example data. Avoid committing personal names, local paths, account identifiers, or real message history there.
Gitignored Agent Console history must remain redacted and private. Use
owner-only runtime-directory and file permissions where the platform supports
them.

### Local-first only

Keep the app bound to loopback only. Non-loopback hosts must be rejected until
an authenticated remote-access capability is separately approved and
implemented safely.

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

Launch directly on POSIX from the repository root using an absolute script
argument so lifecycle cleanup can identify a hung process:

```bash
python "$(pwd)/server.py"
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
- Keep Agent Creator progress compact and text-led; do not reintroduce pill
  containers for its step indicator.
- Avoid reintroducing removed/redundant dashboard surfaces without a clear product reason.
- Keep completed work visible when useful; do not assume deletion is the right default.
- Favor incremental changes over broad rewrites.
- Apply YAGNI: do not add complexity before the project needs it.

## Repository notes

- `mentat.local.toml` and local env files are machine-specific and should stay untracked.
- Runtime output, generated artifacts, and scratch data should stay out of the repo.
- If repo-safe documentation conflicts with machine-local setup, prefer generic repo-safe guidance in tracked files and keep machine-specific notes out of the repository.
