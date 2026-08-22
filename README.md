<p align="center">
  <img src="public/mentat-logo.png" alt="Mentat" width="320" />
</p>

# Mentat

Mentat is a local web dashboard for planning projects, managing tasks, and
working with [Hermes Agent](https://hermes-agent.nousresearch.com/).

I built Mentat because I wanted one friendly place to organize my projects and
let an agent help move the work forward. It runs on your computer and opens in
your browser.

> Mentat is actively evolving. You can run the development build today; signed
> installers will arrive with the public beta.

## What can it do?

- Plan your day and keep projects, tasks, reminders, and recurring work tidy.
- Chat with named Hermes agents and keep their sessions together.
- Delegate longer-running work through Hermes Kanban.
- Attach files and reuse Context Packs in agent conversations.
- Search connected Obsidian notes and view Google Calendar events read-only.
- Pick a comfortable light, dark, or editor-inspired theme.

## Quick start

There is no public installer yet, so the current way to try Mentat is from
source. You need:

- [Python 3.11–3.13](https://www.python.org/downloads/)
- [Git](https://git-scm.com/downloads)
- [Hermes Agent](https://hermes-agent.nousresearch.com/) for agent features

macOS and Windows are the tier-one beta platforms; Linux is a preview. The
macOS release provides separate native Apple Silicon (recommended) and Intel
installers.
Before you begin, check the [supported platforms and known limitations](SUPPORT.md).

Open a terminal and run:

```bash
git clone https://github.com/hazeion/agent-os.git
cd agent-os
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/mentat_setup.py
./run.sh
```

Press Enter to accept the setup helper's recommended local values, or choose a
supported remote Hermes connection when prompted. Then open
[http://localhost:8888](http://localhost:8888). That's it! 🎉

On Windows, replace the virtual-environment and launch commands above with:

```bat
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python scripts\mentat_setup.py
run.bat
```

Mentat works as a project planner without Hermes. Install and set up
[Hermes Agent](https://hermes-agent.nousresearch.com/) to use chat, delegation,
sessions, and other agent features.

The setup helper stores settings only on your computer. Hermes continues to
manage provider credentials. A remote server key is read only from an
environment variable or owner-only env file; see the
[remote Hermes guide](REMOTE_HERMES.md#operator-experience-local-and-remote-selection).

### Connect to a remote Hermes

There are two small pieces: turn on the API server in your Hermes fork, then
give Mentat the same key.

On the **remote Hermes computer**, add this to `~/.hermes/.env`:

```bash
API_SERVER_ENABLED=true
API_SERVER_HOST=127.0.0.1
API_SERVER_PORT=8642
API_SERVER_KEY=replace-with-a-long-random-key
```

Generate a strong key with `openssl rand -hex 32`, save it in the file above,
and restart `hermes gateway`. Put the local API server behind a trusted HTTPS
address such as `https://hermes.example.com`. Mentat intentionally rejects
ordinary remote HTTP, and port 8642 should not be exposed directly to the
internet.

On the **Mentat computer**, create an owner-only file such as
`~/.config/mentat/remote-hermes.env` containing the same key:

```bash
MENTAT_REMOTE_HERMES_API_KEY="your-key"
```

On macOS or Linux, protect it with
`chmod 600 ~/.config/mentat/remote-hermes.env`. On Windows, keep the file in a
folder accessible only to your account. Then stop Mentat and connect:

```bash
./stop.sh
python -m mentat connection configure-remote \
  --endpoint https://hermes.example.com \
  --label "Remote Hermes" \
  --api-key-file ~/.config/mentat/remote-hermes.env
python -m mentat connection test remote
./run.sh
```

Use the HTTPS address without `/v1`. Mentat shows the planned change and asks
before saving it.

Later, switching is quick—stop Mentat, choose the connection, and start it
again:

```bash
./stop.sh
python -m mentat connection use local    # Use Hermes on this computer
python -m mentat connection use remote   # Use the remembered remote
./run.sh
```

Only run the `use local` or `use remote` line you want. Windows users can use
`stop.bat` and `run.bat`; the `python -m mentat connection ...` commands stay
the same. For TLS, firewall, and recovery details, see the
[remote Hermes guide](REMOTE_HERMES.md#operator-experience-local-and-remote-selection).

If you were invited to test a signed release candidate, use the exact release
link and instructions from the invitation instead. See [Beta Support](SUPPORT.md)
for current platform and compatibility notes.

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
8888 is busy, start the normal dashboard with `./run.sh --port 8889` and open
`http://localhost:8889`.

### Try the next frontend preview

The new frontend is currently an optional source preview. It requires Node.js
24.19 or newer within the Node 24 release line. From the repository root, prepare
it once:

```bash
npm --prefix web ci --ignore-scripts
npm --prefix web run build
```

Then launch both the Node gateway and its private Python bridge with one command:

```bash
python3 scripts/mentat_web_preview.py
```

Open [http://localhost:8890](http://localhost:8890) and press Ctrl+C when you
are done. This preview does not replace the normal dashboard on port 8888.

## A few good things to know

- Mentat stays on your computer and listens only on local addresses.
- The normal dashboard still has no npm step. npm is needed only for the
  optional next-frontend preview and frontend development.
- Mentat does not directly edit Hermes' core files.
- Mentat can use local Hermes or a supported remote Hermes server. It checks
  available capabilities and hides actions that cannot be completed safely.
- Calendar events, Obsidian note contents, Hermes sessions, and cron jobs are
  read-only in Mentat.

## Want the technical details?

You do not need these documents to use Mentat, but they are here if you want to
dig deeper:

- [Architecture and safety boundaries](ARCHITECTURE.md)
- [Data storage, migration, and backups](DATA_LAYOUT.md)
- [Privacy](PRIVACY.md) and [security reporting](SECURITY.md)
- [Beta support and known limitations](SUPPORT.md)
- [Public beta status and roadmap](ROAD_TO_BETA.md)
- [Remote Hermes contract](REMOTE_HERMES.md)
- [Recent changes](CHANGELOG.md)

## Contributing

Contributions are welcome. Keep changes small, local-first, and easy to
understand. The [contributor guide](CONTRIBUTING.md) gets you started, and the
[repository guide](AGENTS.md) explains the deeper project boundaries.

Mentat is made by a single developer, is licensed under the
[MIT License](LICENSE), and is still finding its feet. If you find a rough edge,
feel free to open an issue or a focused pull request.
