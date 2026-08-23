<p align="center">
  <img src="public/mentat-logo.png" alt="Mentat" width="320" />
</p>

# Mentat

Mentat is a local operations console for planning work and running agents. It
keeps your projects, tasks, runs, and activity on your computer. It can run
work through Hermes or a signed-in local Codex CLI.

Mentat uses a Next.js dashboard with a small private Python bridge. The older
Python interface is available only as a temporary troubleshooting fallback.

> Mentat is in beta. You can run it from source today. Signed installers are
> planned for the public beta.

## What you can do

- Plan projects, tasks, reminders, and recurring work.
- Chat with named Hermes agents and keep their sessions together.
- Delegate longer work through Hermes Kanban.
- Attach files and reuse Context Packs.
- Search connected Obsidian notes.
- View Google Calendar events without changing them.

## How Mentat works

The Python bridge owns local data and talks to Hermes. Tasks, runs, and events
are stored in Mentat's private SQLite database.

The dashboard reaches the bridge through a private local connection that is not
exposed to the browser. Both parts listen only on your computer.

## Quick start

There is no public installer yet. If you were invited to test a signed release
candidate, follow the invitation and [beta testing guide](BETA_TESTING.md)
instead of these source steps.

You need:

- [Python 3.11-3.13](https://www.python.org/downloads/)
- [Node 24.19 or newer within Node 24](https://nodejs.org/)
- [Git](https://git-scm.com/downloads)
- [Hermes Agent](https://hermes-agent.nousresearch.com/) for Hermes features

Codex execution needs an installed Codex CLI that is already signed in. Hermes
is still required for Hermes chat, delegation, sessions, and profile features.

macOS and Windows are the main beta platforms. Linux is available as a preview.
See [supported platforms and known limitations](SUPPORT.md) before installing.

### macOS or Linux

```bash
git clone https://github.com/hazeion/agent-os.git
cd agent-os
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/mentat_setup.py
npm --prefix web ci --ignore-scripts
npm --prefix web run build
./run.sh
```

### Windows

```bat
git clone https://github.com/hazeion/agent-os.git
cd agent-os
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python scripts\mentat_setup.py
npm --prefix web ci --ignore-scripts
npm --prefix web run build
run.bat
```

Open [http://localhost:8888](http://localhost:8888) if your browser does not
open on its own.

Mentat works as a project planner without an agent runtime. Install Hermes for
Hermes features, or sign in through the Codex CLI for Codex task execution.

The setup helper stores settings on your computer. Hermes continues to manage
provider credentials. To connect Mentat to Hermes on another computer, follow
the [remote Hermes guide](REMOTE_HERMES.md#operator-experience-local-and-remote-selection).

## Start and stop Mentat

On macOS or Linux:

```bash
./run.sh
./status.sh
./stop.sh
```

On Windows, use `run.bat`, `status.bat`, and `stop.bat`.

If port 8888 is busy, run:

```bash
./run.sh --port 8889
```

Then open [http://localhost:8889](http://localhost:8889).

Mentat starts the Node dashboard and its private Python bridge. It needs Node
24.19 or newer within the Node 24 release line. The launcher does not download
or build anything when it starts.

If you need the previous interface while troubleshooting, use:

```bash
./run.sh --legacy-ui
```

On Windows, add `--legacy-ui` to `run.bat` instead.

## Build from source

Install Node 24.19 or newer within Node 24, then build the dashboard once after changing web
files or dependencies:

```bash
npm --prefix web ci --ignore-scripts
npm --prefix web run build
```

## Keep in mind

- Mentat listens only on local addresses.
- Mentat does not edit Hermes or Codex configuration files directly.
- Calendar events, Obsidian note contents, Hermes sessions, and cron jobs are
  read-only in Mentat.
- Private data and runtime files stay out of the repository.

## More documentation

- [Architecture and safety rules](ARCHITECTURE.md)
- [Current pivot roadmap](MENTAT_PIVOT_IMPLEMENTATION_PLAN.md)
- [Data, migration, and backups](DATA_LAYOUT.md)
- [Remote Hermes setup](REMOTE_HERMES.md)
- [Privacy](PRIVACY.md)
- [Security](SECURITY.md)
- [Beta support](SUPPORT.md)
- [Recent changes](CHANGELOG.md)

## Contributing

Contributions are welcome. Keep changes small and local. Read the
[contributor guide](CONTRIBUTING.md) before opening a pull request.

Mentat is licensed under the [MIT License](LICENSE).
