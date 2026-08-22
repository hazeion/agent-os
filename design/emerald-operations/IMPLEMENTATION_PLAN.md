# Emerald Operations implementation plan

Status: Slice 2A-B complete

Design guide: [DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md)

App: `web/`

The Emerald Operations design is already implemented in the Python app. The
Next.js work ports that design from `public/styles.css` and the current running
interface. The `public/` interface stays available during the migration.

## Goal

Move the completed Emerald shell into Next.js without redesigning it. Keep the
interface honest about what is live, what is read-only, and what is not
connected yet.

The first frontend slice builds the shell. Later slices connect one real route
at a time.

## Rules

- Reuse the Node gateway and Python bridge from Slice 2A-A.
- Treat the effective Emerald layer in `public/styles.css` as the visual source
  of truth.
- Translate that layer into focused Next.js styles. Do not import the whole
  compatibility stylesheet or its historical overrides.
- Do not create another frontend project or local server.
- Keep SQLite, Hermes, files, and credentials in Python.
- Add fixed bridge and Node API routes only when a screen needs them.
- Do not add a generic proxy.
- Keep `public/` working until production cutover is approved.
- Use real state or a named empty state. Do not ship sample operational data.
- Keep each slice small enough to review on its own.

## Foundation check

Slice 2A-A passed CI and merged in PR #114.

From the repository root, confirm the foundation:

```bash
node --version
npm --prefix web ci --ignore-scripts
npm --prefix web run check
npm --prefix web run build
python scripts/mentat_web_preview.py
```

Open `http://localhost:8890`. Check desktop and mobile widths.

## Slice 2A-B: application shell

### Scope

Port:

- the effective Emerald semantic tokens from `public/styles.css`, checked
  against `figma-variables.json`
- the Mentat mark and wordmark
- desktop, compact, and mobile navigation
- the utility bar and safe local connection state
- route frames for `/`, `/agents`, `/tasks`, and `/runs`
- shared panel, button, field, status, data-state, and dialog basics
- Standard and High Contrast modes
- skip link, focus handling, reduced motion, and responsive behavior

Use React Server Components by default. Add a client component only when a
control needs browser state or event handling.

Use the existing `/api/bridge/health` route for the one live status already
approved. Other route frames show a clear foundation state until their data
slice lands.

### Dependencies

The shell already has Next.js, React, TypeScript, and Tailwind. Reuse the
current source-owned line icons and avoid adding a UI dependency unless the
slice has a concrete need for it.

Do not add TanStack Query in this slice. It belongs with the first real server
state consumer.

### Not included

- Agent, Task, or Run data APIs
- SSE or WebSocket
- messaging, stop, or approval controls
- cron data
- legacy interface removal
- production installer changes

### Checks

- all four routes render without fake data
- the Next.js shell matches the current Emerald interface's layout, spacing,
  color, panel, control, and responsive behavior
- desktop, compact, and mobile navigation work with a keyboard
- the mobile drawer traps focus, closes with Escape, and returns focus
- active navigation uses `aria-current="page"`
- Standard and High Contrast modes load without a flash
- no page-level horizontal overflow appears at 1680, 1440, 1024, 768, or 390 px
- the existing bridge health state still works
- all six Lighthouse runs score 100 in every category

## Slice 2B-A: Agents

Add the first real route from browser to Python.

### Scope

- one fixed private Python bridge capability for the browser-safe Agent list
- one same-origin Node API route
- the `/agents` screen
- honest loading, empty, disconnected, unsupported, and error states
- TanStack Query only if the screen needs client caching or invalidation

Never return adapter-owned runtime references, credentials, paths, or raw
Hermes data.

### Checks

- only Mentat Agent IDs and safe display fields reach the browser
- malformed and oversized responses fail closed
- no browser input can choose a private bridge path
- local and remote runtime states have clear labels
- the route works without affecting the Python compatibility interface

## Slice 2B-B: Tasks

Build `/tasks` on Mentat's SQLite Task APIs.

### Scope

- Task list and filters
- selected Task details
- planning fields and Today ordering
- subtasks, dependencies, recurrence, reminders, and links
- approved create, edit, delete, and delegation flows

Keep every existing preview, confirmation, state binding, and readback check.
Node is a same-origin interface. Python remains the authority.

### Checks

- all Task fields survive a read and write round trip
- stale confirmations fail closed
- dependency cycles and unsafe note paths are rejected
- delegation uses the existing Hermes Kanban boundary
- `tasks.json` is never read as live state

## Slice 2B-C: Runs

Build the read-only `/runs` route before adding live controls.

### Scope

- Run list and status
- selected Run summary
- normalized event history
- waiting, failed, stopped, completed, and truncated states
- browser-safe artifact summaries

Keep runtime-specific data inside its adapter.

### Checks

- Mentat Run IDs remain separate from runtime IDs
- bounded event history names truncation
- active and waiting Runs are never hidden by retention
- unsupported data has a named state

## Slice 2C-A: live timeline

Add SSE after the read-only Runs route is stable.

### Scope

- same-origin SSE through Node
- fixed private event capability in Python
- reconnect from the last verified event ID
- bounded event parsing and clear disconnected state
- query updates or invalidation for affected Run data

Do not add WebSocket unless a later requirement needs two-way realtime traffic.

### Checks

- reconnect does not replay a handled event
- gaps and truncation are visible
- malformed events fail closed
- one failed stream does not change durable Run state

## Slice 2C-B: run controls

Add only controls that the selected runtime advertises.

### Scope

- send message
- stop Run
- supported approval and clarification responses

Python checks capability, authority, current state, and confirmation. A control
that cannot work must not appear.

### Checks

- each request binds to the current Mentat Run and runtime state
- duplicate, stale, or unsupported requests fail closed
- partial failures remain visible
- a result is not shown as successful until readback verifies it

## Home and supporting routes

The full Home design includes planning, Agents, time, Scheduled Automations,
projects, and the Agent Console. Connect those areas only after their source
route and API contracts are ready.

Before Home shows live Scheduled Automations, add a small Python safety slice:

1. Read the selected Hermes runtime from trusted configuration.
2. Do not read local cron jobs when a remote runtime is selected.
3. Return a browser-safe availability value.
4. Use `null`, not `0`, when a count is unavailable.
5. Keep every cron mutation unavailable.

Calendar stays read-only. Notes keep validated vault-relative paths. Agent
Console keeps its command allowlist, attachment boundary, confirmations, and
artifact checks.

## Slice 2D: production cutover

The source preview is not ready to replace the installed Python interface until
this slice is complete.

Decide and test:

- how Node is packaged on macOS, Windows, and Linux preview builds
- how the launcher starts and stops Node and Python
- offline startup and upgrade behavior
- port ownership and failure recovery
- rollback to the compatibility interface
- removal timing for old `public/` code

Do not remove the compatibility interface in the same change that introduces
the first production launcher.

## Test commands

Run these for every web slice:

```bash
npm --prefix web ci --ignore-scripts
npm --prefix web run check
npm --prefix web run build
python -m unittest discover -s tests -v
python scripts/mentat_web_preview.py
```

Run Lighthouse in another terminal with the pinned Chrome for Testing build:

```bash
CHROME_PATH="<printed executable path>" npm --prefix web run lighthouse:gate
```

Review at:

- 1680 x 1050
- 1440 x 900
- 1024 x 768
- 768 x 1024
- 390 x 844

Check keyboard use, 200 percent zoom, reduced motion, Standard contrast, High
Contrast, loading, empty, disconnected, unsupported, and failure states.

## Review questions

Before accepting a slice, answer:

1. What new route or behavior works?
2. Which Python authority and safety checks still apply?
3. What data can reach the browser?
4. What happens when the runtime is disconnected or unsupported?
5. Which desktop and mobile states were checked?
6. Can the slice be rolled back without losing data?
