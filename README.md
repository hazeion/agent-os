<p align="center">
  <img src="public/mentat-logo.png" alt="Mentat" width="320" />
</p>

# Mentat

Mentat is a local operations console for planning work and running agents. It
keeps your projects, tasks, runs, and activity on your computer. It can run
work through Hermes, a signed-in local Codex CLI, or an optional Vercel AI
Gateway connection.

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

The Python bridge owns local data and runtime access. Tasks, agents, runs,
events, and provider settings are stored in Mentat's private SQLite database.

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

Codex execution needs an installed Codex CLI. Sign in with the ChatGPT account
that owns your Codex subscription, then verify the local CLI:

```bash
codex login
codex login status
```

Complete the browser sign-in opened by `codex login`, then start Mentat and use
**Recheck** in the Agent Console. If you install the CLI while Mentat is already
running, restart Mentat so readiness and dispatch use the same fixed CLI
process. Mentat asks the Codex CLI only for a bounded readiness
state; never paste a password, token, API key, cookie, or Codex auth file into
Mentat. See the [official Codex authentication guide](https://developers.openai.com/codex/auth/)
for CLI setup. Hermes is still required for Hermes chat, delegation, sessions,
and profile features.

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
Hermes features, or sign in through the Codex CLI for Codex task and Agent
Console execution.

The setup helper stores settings on your computer. Hermes continues to manage
provider credentials. To connect Mentat to Hermes on another computer, follow
the [remote Hermes guide](REMOTE_HERMES.md#operator-experience-local-and-remote-selection).

### Optional Vercel connection

Vercel is optional. AI Gateway can run a compatible Agent, while Sandbox and
Connect are separate readiness checks. Mentat reads credentials from your
environment and never saves their values.

For an AI Gateway API key:

```bash
export AI_GATEWAY_API_KEY="your-key"
python -m mentat.cli vercel configure --auth api_key --model openai/gpt-5.4
```

On Windows, set the key in your current terminal with
`$env:AI_GATEWAY_API_KEY = "your-key"` in PowerShell, or
`set AI_GATEWAY_API_KEY=your-key` in Command Prompt.

Review the preview, then repeat the command with `--confirm TOKEN`. Create an
Agent the same way:

```bash
python -m mentat.cli vercel create-agent --name "Vercel Agent"
```

Use `python -m mentat.cli vercel status` to check the safe connection state.
`Configured` means the local settings are valid. `Credential present` means
the required environment value is available. Use the confirmed `vercel test`
command when you need a live readiness check.
Sandbox also needs `VERCEL_TOKEN`, `--team-id`, and `--project-id`. OIDC and
Connect use `VERCEL_OIDC_TOKEN`; Connect also needs `--connector`. Run
`python -m mentat.cli vercel configure --help` for setup options. Stop Mentat
before changing or testing this connection.

If a Gateway request ends in `unknown`, Mentat will not retry it. After you
check the provider, stop Mentat and review this recovery command:

```bash
python -m mentat.cli vercel recover-run --run-id RUN_ID
```

Confirming it marks the Run interrupted without sending the request again.

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
- [Current implementation roadmap](IMPLEMENTATION_PLAN.md)
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
