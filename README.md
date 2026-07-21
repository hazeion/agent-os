<p align="center">
  <img src="public/mentat-logo.png" alt="Mentat" width="320" />
</p>

# Mentat

Mentat is a local web dashboard for planning projects, managing tasks, and
working with [Hermes Agent](https://hermes-agent.nousresearch.com/).

I built Mentat because I wanted one friendly place to organize my projects and
let an agent help move the work forward. It runs on your computer and opens in
your browser.

> Mentat is actively evolving. The current development build is ready to
> explore; native installers are still on the way and will be signed for the
> public beta.

## What can it do?

- Plan your day and keep projects, tasks, reminders, and recurring work tidy.
- Chat with named Hermes agents and keep their sessions together.
- Delegate longer-running work through Hermes Kanban.
- Attach files and reuse Context Packs in agent conversations.
- Search connected Obsidian notes and view Google Calendar events read-only.
- Pick a comfortable light, dark, or editor-inspired theme.

## Quick start

You need:

- [Python 3.11–3.13](https://www.python.org/downloads/)
- [Git](https://git-scm.com/downloads)
- [Hermes Agent](https://hermes-agent.nousresearch.com/) for agent features

Before installing, take a quick look at [supported platforms and known
limitations](SUPPORT.md). macOS and Windows are the tier-one beta platforms;
Linux is a preview.

Open a terminal and run:

```bash
git clone https://github.com/hazeion/agent-os.git
cd agent-os
python -m pip install -r requirements.txt
python scripts/mentat_setup.py
./run.sh
```

Then open [http://localhost:8888](http://localhost:8888). That's it! 🎉

On Windows, use `run.bat` instead of `./run.sh`. If your computer does not
recognize `python`, try `python3` (macOS/Linux) or `py` (Windows).

The setup helper stores its settings locally and does not ask for or save your
provider credentials. Hermes continues to manage those.

## Starting and stopping

After the first setup, start Mentat from its folder:

```bash
./run.sh
```

Useful commands:

```bash
./status.sh    # Is Mentat running?
./stop.sh      # Stop Mentat
```

Windows users can run `run.bat`, `status.bat`, and `stop.bat` instead. If port
8888 is busy, start Mentat with `./run.sh --port 8890` and open
`http://localhost:8890`.

## A few good things to know

- Mentat stays on your computer and listens only on local addresses.
- There is no npm install step—the frontend is plain HTML, CSS, and JavaScript.
- Mentat does not directly edit Hermes' core files.
- Mentat works great with local Hermes. If you connect a supported remote
  Hermes runtime, Mentat checks what it can safely do and keeps unavailable
  controls out of your way.
- Calendar events, Obsidian note contents, Hermes sessions, and cron jobs are
  read-only in Mentat.

## Want the technical details?

You do not need these documents to use Mentat, but they are here if you want to
dig deeper:

- [Architecture and safety boundaries](ARCHITECTURE.md)
- [Data storage, migration, and backups](DATA_LAYOUT.md)
- [Privacy](PRIVACY.md) and [security reporting](SECURITY.md)
- [Beta support and known limitations](SUPPORT.md)
- [Public beta roadmap](ROAD_TO_BETA.md)
- [Remote Hermes plans](REMOTE_HERMES.md)
- [Recent changes](CHANGELOG.md)

## Contributing

Contributions are welcome. Keep changes small, local-first, and easy to
understand. The [contributor guide](CONTRIBUTING.md) gets you started, and the
[repository guide](AGENTS.md) explains the deeper project boundaries.

Mentat is made by a single developer, is licensed under the
[MIT License](LICENSE), and is still finding its feet. If you find a rough edge,
feel free to open an issue or a focused pull request.
