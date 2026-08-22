<p align="center">
  <img src="public/mentat-logo.png" alt="Mentat" width="320" />
</p>

# Mentat

Mentat is a local operations console for planning work and running agents. It
keeps your projects, tasks, runs, and activity on your computer. Hermes is the
first supported agent runtime.

Mentat is moving to a new Next.js interface. The current Python app remains the
default while the new interface is built and tested beside it.

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

The Python app owns local data and talks to Hermes. Tasks, runs, and events are
stored in Mentat's private SQLite database.

The optional Next.js preview runs through a local Node gateway. It reaches the
Python app through a private bridge that is not exposed to the browser. Both
apps listen only on your computer.

## Quick start

There is no public installer yet. If you were invited to test a signed release
candidate, follow the invitation and [beta testing guide](BETA_TESTING.md)
instead of these source steps.

You need:

- [Python 3.11-3.13](https://www.python.org/downloads/)
- [Git](https://git-scm.com/downloads)
- [Hermes Agent](https://hermes-agent.nousresearch.com/) for agent features

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
run.bat
```

Open [http://localhost:8888](http://localhost:8888) if your browser does not
open on its own.

Mentat works as a project planner without Hermes. Install Hermes when you want
to use chat, delegation, sessions, and other agent features.

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

## Try the Next.js preview

The preview needs Node 24.19 or newer in the Node 24 release line.

Check your version:

```bash
node --version
npm --version
```

Install and build the web app from the repository root:

```bash
npm --prefix web ci --ignore-scripts
npm --prefix web run build
```

Start the Node gateway and private Python bridge:

```bash
python3 scripts/mentat_web_preview.py
```

Open [http://localhost:8890](http://localhost:8890). Press Ctrl+C in the
terminal when you are done.

The preview does not replace the Python app on port 8888. The normal app does
not need npm.

## Keep in mind

- Mentat listens only on local addresses.
- Mentat does not edit Hermes core files directly.
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
