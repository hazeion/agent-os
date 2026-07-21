# Privacy

Mentat is local-first. It has no default telemetry, analytics, or crash-report
upload.

## What stays local

Projects, tasks, planning data, settings, Context Packs, and private Agent
Console history live in Mentat's application-data directory on your computer.
Attachments and generated artifacts use private, gitignored runtime storage.
The exact platform locations and backup rules are listed in
[DATA_LAYOUT.md](DATA_LAYOUT.md).

Backups may contain your projects, tasks, and retained Console data. Store and
share them as carefully as any other personal file.

## Connected tools

- **Hermes:** Local sessions and supported metadata are read for the dashboard.
  If you select a remote Hermes runtime, Mentat stores the connection endpoint
  and sends requested agent work to it over HTTPS. Hermes owns provider
  credentials; Mentat stores the remote API key only in its private connection
  record and never returns it to the browser, diagnostics, or normal backups.
- **Google Calendar:** Calendar access is read-only. Mentat can create or link a
  Mentat task from an event, but does not edit the calendar event.
- **Obsidian:** Mentat reads validated Markdown notes from the configured vault.
  It can attach a note reference to a Mentat task but does not edit the note.

## Logs and diagnostics

Local server output can contain operational timing and error locations, so
review it before sharing. The in-app diagnostics download is safer for bug
reports: it contains only an allowlisted version, generation time, platform
category, Python version, install type, and subsystem status. It excludes logs, secrets, personal
content, local paths, hostnames, usernames, endpoints, and blob identifiers.

Deleting Mentat data or uninstalling the application is an operator action.
Application-only uninstall is designed to preserve durable data; see
[DATA_LAYOUT.md](DATA_LAYOUT.md) before removing anything manually.
