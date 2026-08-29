# Mentat Repository Guide

This file is the quick project guide for contributors and coding agents working in this repository.

Before planning architectural work, read `MENTAT_MULTI_AGENT_PIVOT.md` for the
target direction and `MENTAT_PIVOT_IMPLEMENTATION_PLAN.md` for the current slice
sequence and resume point. Continue to use `ARCHITECTURE.md` for implemented
contracts and safety boundaries. A provisional roadmap entry is not approval to
implement that slice.

## Agent skills

### Issue tracker

Issues, specs, and Wayfinder maps are tracked in GitHub Issues for
`hazeion/agent-os`. See `docs/agents/issue-tracker.md`.

### Domain docs

Mentat uses a single-context domain-document layout. Existing architecture,
pivot, design, implementation-plan, and review documents remain authoritative.
See `docs/agents/domain.md`.

## Overview

Mentat is a local-first multi-agent operations console in a strangler migration
from its original Hermes-powered dashboard architecture.

Goals:

- keep the app local-first
- read Hermes data without writing to Hermes core files
- use simple project-owned local data where possible
- keep the UI practical, lightweight, and easy to understand
- avoid unnecessary complexity or premature framework/tooling choices

The user-facing product name and repository naming convention is **Mentat**.

## Architecture

Mentat's default local interface is the Next.js dashboard on the configured
port (8888 by default). The Python `public/` interface is an explicit
`--legacy-ui` rollback path during cutover.

Python still owns local data, Hermes access, and safety checks. The Node gateway
reaches Python through small, named bridge capabilities. Do not add a generic
proxy or move SQLite, credentials, filesystem access, or Hermes authority into
the browser layer.

Main files:

```text
server.py
codex_runtime.py
vercel_connections.py
vercel_infrastructure.py
vercel_runtime.py
hermes_kanban.py
hermes_profile_identity.py
task_planning.py
task_repository.py
runtime_config.py
mentat_lifecycle.py
mentat/local_bridge.py
mentat.toml
run.sh / stop.sh / status.sh
run.bat / stop.bat / status.bat
public/index.html
public/styles.css
public/core.js
public/app.js
web/
scripts/mentat_web_preview.py
data/projects.json
data/tasks.json (seed and recovery only after SQLite cutover)
data/agents.json
data/attention.json
data/calendar.json
README.md
```

## Current direction

Current priorities:

- local-only dashboard experience
- the Emerald Operations interface in `web/`
- a small, secure boundary between Node and Python
- project/task visibility and actionability
- day planning, review, and personal task-management depth
- durable task delegation through Hermes' supported Kanban adapter
- read-only Hermes session visibility
- runtime-neutral orchestration with capability-scoped runtime adapters
- optional Vercel AI Gateway, Sandbox, and Connect adapters
- capability-scoped Hermes control through fixed, supported interfaces
- safe project-owned write paths

The project is still a work in progress. Some areas are complete enough to use, while others are still partial or evolving.

## Boundaries

### Runtime and Hermes capability boundary

Mentat owns the target canonical Agent identity, workflow, tasks, runs, events,
and authority. Runtime identities are implementation references beneath an
Agent. During the migration, legacy browser `agent_id` values remain Hermes
profile IDs for compatibility; do not treat that alias or `data/agents.json`
heartbeat observations as the durable Mentat Agent registry.

Canonical Mentat Agents, runtime bindings, and optional provider settings are
stored in schema-9 owner-private `mentat.sqlite3`. Existing roots move from
the retired `agent-registry.sqlite3` source only through `mentat
agent-registry-migration`: preview is read-only, confirmation requires a
validated backup, and Agent/config rows plus the receipt commit together. Once
the receipt exists, live code must never read, write, shadow, synchronize, or
fall back to the old file. Browser-facing Agent projections may expose Mentat IDs,
names, runtime types, runtime configuration IDs, and declared capabilities, but
must not expose adapter-owned runtime references. `data/agents.json` remains a
legacy heartbeat-observation surface and must not be merged into or substituted
for the canonical registry. The registry is capped at 128 Agents and is part of
the validated private Console backup/restore consistency unit. New format-4
backups carry the embedded authority without a separate registry member;
format-2/3 restores remain supported and require convergence before normal use.

Vercel is optional. Its private connection record may store validated settings
and the credential-source kind, but never a credential value. Vercel setup,
readiness tests, Agent creation, and disconnect use stopped-server exact
preview/confirmation CLI operations. The browser may see only the safe
connection projection and cannot create or bind a Vercel Agent directly.
AI Gateway, Sandbox, and Connect stay behind separate fixed-host, bounded
adapters. Sandbox accepts no arbitrary commands and Connect tokens must be
discarded immediately. Schema-5 compatible-root export must omit Vercel Agents
and provider tables while leaving the schema-9 source unchanged.
Browser status reports configuration and credential presence, not live
readiness. Only an explicit confirmed CLI test may claim readiness. Ambiguous
Gateway submissions must remain `unknown` without retry until the stopped-
server `mentat vercel recover-run` flow explicitly marks the exact Run
interrupted. A Vercel result may cross the browser event boundary only as one
bounded message; raw provider payloads and runtime references remain private.

Pivot Slice 1C-B makes the canonical Task tables in owner-private
`mentat.sqlite3` authoritative. The exact one-time startup import and singleton
authority receipt commit in the same transaction. After the receipt exists,
live Task paths must use SQLite exclusively and must never read, write, shadow,
synchronize, or fall back to stale `tasks.json`; the tracked file is only a
packaged seed/recovery artifact. `mentat task-migration` remains read-only and
reports existing authority without consulting stale JSON. Deterministic export
is recovery infrastructure, not an alternate runtime authority. The offline
`mentat task-export` command may replace `tasks.json` only after an exact
preview/confirmation while no Mentat server is active; live code must still
ignore that file while the SQLite authority receipt exists. Use its
`--compatible-root` mode for an actual pre-cutover build: it publishes a new
schema-5 sibling data root whose Task tables are empty and whose exported
`tasks.json` is the old build's sole Task authority. It must leave the
authoritative schema-9 root unchanged. Compatible-root export must fail closed
while the source actively selects remote Hermes because connection credentials
are deliberately excluded; the operator must explicitly return the source to
local mode and reconfigure the sibling before any remote operation.
The exact canonical Task export must remain within the shared document limit;
do not append or ignore optional formatting bytes during write or verification.
Compatible sibling publication must fsync its populated staged hierarchy and
pinned parent on POSIX, or use missing-only Windows directory publication with
`MOVEFILE_WRITE_THROUGH`, before reporting durable success. Post-rename failures
must be reported as partial writes.

Hermes is the first capability-scoped runtime adapter. Codex is the second,
through one fixed local App Server stdio connection in `codex_runtime.py`.
New orchestration code must use the runtime-neutral boundary and must not
depend directly on Hermes- or Codex-specific execution schemas.

The first Codex binding is the fixed `default` local CLI identity. Mentat may
reuse an existing Codex CLI sign-in, but browser input must never select the
executable, working directory, provider, model, credential source, App Server
method, thread ID, or turn ID. Codex App Server requests use fixed arguments,
an allowlisted child environment, the `workspaceWrite` sandbox, and approval policy
`never`. Unsupported approval and attachment capabilities fail closed. Stop
success requires exact canonical Run reconciliation, and runtime shutdown must
close the App Server's owned process tree. Routine Agent registry reads must
not launch or wait for Codex; live readiness probes belong only on explicit
Codex capability, binding, or dispatch paths.

Agent Console follow-ups are durable Conversation Turns in SQLite, not an
in-memory execution queue. Keep at most eight pending, blocked, or dispatching
Turns per Conversation, preserve FIFO ordinals, and require exact Turn plus
Message revisions for edit, cancel, and Continue. Verified success may claim
only one oldest pending Turn; Stop, failure, interruption, unknown/partial
evidence, or capacity pressure pauses the head. Cancelling a blocked head must
leave its next queue-active successor explicitly blocked rather than silently
stranded: transition a pending successor with the inherited reason, or preserve
an already-blocked successor exactly. Cancelling a blocked non-head must not
change the current head.
`/steer` targets only the exact selected compatible running Run, never queues
or retries, and preserves the draft whenever delivery cannot be verified; keep
the composer action labeled Send rather than adding a separate Steer button.
Detailed live events are selected-Run-only, same-origin bounded, and coalesced
to one in-flight canonical refresh plus at most one trailing refresh. Assistant
transcript text becomes authoritative only through the exactly-once durable
Message projection. Adapter capacity is private and scope-specific: every
unqualified adapter remains at one, while only the fixed qualified Codex
`default` binding may use the ceiling of two concurrent compatible Runs.

Operator recovery remains Conversation-owned. Retry creates a separate Run for
the same Turn and preserves prior Run/Event evidence; a bounded durable action
receipt prevents a repeated browser request from calling the adapter twice.
Resume is a separate fixed capability and must not appear unless both the Agent
and exact live adapter advertise `run.resume` with verified private continuity.
No production adapter currently advertises it. Initial nonterminal browser
state is reconciling until exact readback; controls fail closed meanwhile.
Global activity must likewise project unverified nonterminal state as checking,
not working or waiting.
Closing a tab is presentation-only, and reversible Conversation archive never
stops work or deletes evidence. Completion while archived commits normally but
must not start hidden queued work.
Console transcript Markdown is a small React-text-only presentation subset;
raw HTML, unsupported links, provider reasoning, tool payloads, and executable
code remain inert or omitted. Thinking and Activity may appear only from fixed safe event
presentations derived from validated server-side provenance. Keep transcript
pages bounded to 100 Messages and the retained browser DOM bounded to 200 rows,
512 formatting units per Message, and 8,000 formatting units per transcript.
Reconnect snapshots merge unless their exact reset flag requires replacement;
retain null-presentation sequence markers only for disclosure ordering.

Rich-link previews are Message-bound derived data, never a generic fetch
capability. Browser and Node requests may name only an exact accepted user
Message and revision; Python extracts at most three candidates and owns URL,
DNS/IP, pinned HTTPS, redirect, metadata, image, cache, and preference policy.
Only HTTPS/443 public destinations may be fetched. Hostile work runs in two
credential-free replaceable workers with fixed phase and wall-clock watchdogs.
Persist no raw URL, HTML, header, redirect, address, image source, path, or
secret outside canonical Message text. The disposable preview cache and its
secret are excluded from backup/export; the owner-private enabled preference is
separate and revisioned. Plain links remain independent from preview success.

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

The Next.js composer may address configuration only by canonical Mentat Agent
ID. Resolve its private runtime binding in Python and never return that binding
to Node or the browser. Only a uniquely bound local Hermes Agent with authenticated
inventory and the fixed switch capability is mutable. Codex, Vercel,
unsupported runtimes, and unsupported effort controls remain visible but
read-only. Configuration changes are for the next Run; an active Run displays
only its immutable safe execution snapshot.
Remote Hermes may expose only its current safe identity here, never alternate
provider/model inventory or mutation.

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
Calendar week navigation may request only a validated Sunday start, a fixed
seven-day range, and a validated IANA timezone. Keep disconnected preview events
client-only and ineligible for task or calendar mutations.

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

Mentat may synchronize only its versioned, profile-bound identity block at the
top of `SOUL.md`, together with Hermes' supported profile description metadata.
This requires an exact preview, confirmation bound to the current soul revision,
the shared profile mutation lock, no active Console run, atomic replacement,
post-write verification, and rollback on failure. Never return other soul
content to the browser. Direct skill-content editing, hub installation, general
`SOUL.md` editing outside that block, clone-all, rename, credential management,
and arbitrary MCP changes remain deferred.

Agent Console slash commands are a separate Mentat allowlist, not a projection
of the Hermes CLI. Add commands through the versioned command manifest with a
fixed dashboard handler, argument declarations, description, safety class, and
tests. Never derive this surface by parsing CLI output or add arbitrary command
passthrough.

Agent Console attachments and generated artifacts belong only in gitignored
`data/runtime` storage. Use the project-owned SQLite metadata and
content-addressed blob boundary; never store file bytes in tracked JSON or
return local paths, hashes, storage keys, or arbitrary file URLs to the browser.
Uploads and workspace choices must remain type/size/content validated,
symlink-safe, and snapshot-based. Workspace search is restricted to configured
roots and relative paths. Assistant artifacts may be discovered only inside the
run-owned export directory from trusted server context; never parse or open a
path merely because model prose mentions it. Preserve staged expiry,
reference-aware grace, active-run protection, bounded garbage collection, and
startup reconciliation when extending this surface.

Do not pass extensionless content-addressed blob paths directly to Hermes image
arguments. Materialize a private run-scoped input snapshot with the validated
image extension, keep that path server-only, and clean it after execution.

Context Packs are project-owned reusable references, not copied authority.
Store only bounded instructions, validated vault-relative Markdown paths, and
validated workspace root IDs plus relative paths in `data/context_packs.json`.
Revalidate every referenced item when a pack is used. Console application must
create private staged snapshots through the existing attachment boundary;
delegation application must resolve bounded text into the exact preview so any
pack, note, or file change invalidates confirmation. Never persist absolute
paths, note contents, file contents, credentials, or Hermes state in a pack.

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

Install Python dependencies:

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

Launch directly on POSIX from the repository root:

```bash
python -m mentat.cli start
```

Default local URL:

```text
http://localhost:8888
```

To build and run the default Next.js dashboard from source:

```bash
npm --prefix web ci --ignore-scripts
npm --prefix web run check
npm --prefix web run build
./run.sh
```

Open `http://localhost:8888`. Node must satisfy the version in `.node-version`
and `web/package.json`.

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
- Use the Emerald Operations design system for new work in `web/`.
- Treat `public/` as a compatibility interface. Fix regressions there, but do
  not build the new orchestration UI in it.
- Keep sibling action buttons in compact groups aligned to one edge of their
  panel or section. Do not use `space-between` to distribute individual buttons
  across the available width. A panel heading may separate its title/content
  from one compact control group on the opposite edge.
- On narrow layouts, wrap compact button groups before considering full-width
  or stretched controls. Use stretched actions only when the interaction has an
  explicit mobile reason for one dominant full-width action.
- Keep Agent Creator progress compact and text-led; do not reintroduce pill
  containers for its step indicator.
- Add site themes through the shared token set, saved-theme preloader, selector,
  preview swatches, and visual contract tests together. Avoid one-off
  component-specific palette overrides.
- Avoid reintroducing removed/redundant dashboard surfaces without a clear product reason.
- Keep completed work visible when useful; do not assume deletion is the right default.
- Favor incremental changes over broad rewrites.
- Apply YAGNI: do not add complexity before the project needs it.

## README guidance

Treat `README.md` as a first-time user's welcome and setup guide. Keep it light,
friendly, informative where needed, and concise. A reader with little technical
experience should be able to install and launch Mentat quickly without working
through architecture, milestone, or migration details. Link to focused docs for
advanced material instead of expanding it in the README, and trim anything that
is not vital to understanding, installing, or running Mentat.

## Repository notes

- `mentat.local.toml` and local env files are machine-specific and should stay untracked.
- Runtime output, generated artifacts, and scratch data should stay out of the repo.
- If repo-safe documentation conflicts with machine-local setup, prefer generic repo-safe guidance in tracked files and keep machine-specific notes out of the repository.
