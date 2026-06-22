# React Readiness Notes

Agent OS is intentionally still a small Python server plus static HTML/CSS/vanilla JS frontend. The current phase is about validating the product shape before introducing a build system.

## Current decision

Do **not** migrate to React yet. The app is still easy to change in vanilla JS, and the next few UI iterations are mostly product/UX validation.

## What changed in this phase to keep a future React refactor clean

- Calendar rendering now has clearer data-shaping helpers (`sortedCalendarItems`, `calendarGroups`, `calendarTimeLabel`, `renderCalendarInto`) instead of one flat map inside `renderCalendar`.
- Calendar API responses include normalized metadata (`source`, `auth`, `range_days`, `read_only`, `summary`) so a future component can consume state without scraping text.
- The dashboard continues to keep write-back local/project-owned and Hermes core read-only.
- Versioned static asset URLs remain in `public/index.html` to avoid stale browser caches during iteration.

## React migration trigger points

Reassess React when one or more of these become real requirements:

1. Dashboard-native project/task create/edit forms with validation and optimistic UI.
2. Real routes for Today, Agents/Sessions, Calendar, Projects/Tasks, Notes, and Settings.
3. Modals/drawers for session detail, task detail, calendar event detail, and project editing.
4. Live Agent Pulse 2.0 heartbeat/roster updates, especially if websockets enter the design.
5. Direct Hermes chat from the dashboard.
6. Shared client state becomes difficult to reason about in `public/app.js`.

## Suggested migration path when ready

1. Keep `server.py` as the local API boundary first.
2. Create a React/Vite frontend in a new directory or branch.
3. Port one view at a time, starting with Calendar or Projects/Tasks.
4. Preserve the existing endpoint contracts and read-only-to-Hermes boundaries.
5. Only then add richer client-side routing/state management if needed.

## Non-goals for now

- No npm/build step just for visual polish.
- No framework rewrite before the direct-editing/live-agent features justify it.
- No public deployment or remote exposure as part of a frontend migration.
