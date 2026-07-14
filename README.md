# Mentat

Mentat is a local-first dashboard for planning work and getting things done with
Hermes agents.

It brings your tasks, named agents, Console conversations, delegated work,
sessions, notes, and calendar context into one calm workspace. Mentat is useful
today, but still actively evolving.

## What can Mentat do?

- Plan your day, capture tasks, set reminders, and track recurring or blocked
  work.
- Chat with a named Hermes agent and keep its profile, role, model, and sessions
  together.
- Attach images, text, code, or safe workspace files to a Console prompt, then
  view code, previews, and generated artifacts in the conversation.
- Delegate durable tasks through Hermes Kanban and review results, questions,
  retries, and revisions from Mentat.
- Browse read-only Hermes sessions and cron inventory.
- Search Obsidian notes, view read-only Google Calendar context, and use the
  Agent Pulse live heartbeat registry.

## A small, local stack

Mentat uses:

- a Python server;
- a static HTML, CSS, and vanilla JavaScript frontend;
- local JSON for project-owned tasks and settings;
- private SQLite metadata and content-addressed blobs for Console files.

There is currently **no npm install step**.

Hermes profiles are the canonical agent identities. Mentat uses supported,
validated Hermes operations for agent control and keeps credentials in Hermes.

## Quick start

You need Python 3. Install and configure
[Hermes Agent](https://hermes-agent.nousresearch.com/) if you want agent,
session, provider, and delegation features.

```bash
git clone https://github.com/hazeion/agent-os.git
cd agent-os
python -m pip install -r requirements.txt
python scripts/mentat_setup.py
./run.sh
```

Open [http://localhost:8888](http://localhost:8888).

If your system uses `python3`, substitute it for `python` in the commands above.
On Windows, run `run.bat` instead of `./run.sh`. The setup wizard creates only
local, gitignored configuration and never writes credentials.

### Start without the setup wizard

For the basic local dashboard:

```bash
python "$(pwd)/server.py"
```

On Windows:

```bat
python server.py
```

## Useful commands

```bash
./status.sh                         # check the managed server
./stop.sh                           # stop it
python server.py --print-config     # show effective configuration
python -m unittest discover -s tests -v
```

Windows users can use `status.bat` and `stop.bat`.

Mentat listens only on loopback addresses such as `localhost` and `127.0.0.1`.
Use `./run.sh --port 8890` if port 8888 is busy.

## Configuration

The shared defaults live in `mentat.toml`. Run the setup wizard to create
`mentat.local.toml` and optional local environment files.

Common overrides include:

- `MENTAT_PORT`
- `MENTAT_HOST` (loopback only)
- `HERMES_HOME`
- `OBSIDIAN_VAULT_PATH`
- `MENTAT_CONFIG`

Command-line values override environment variables, which override local and
shared configuration files.

## A few important boundaries

Mentat is a local control plane, not a general editor for Hermes internals.

- Personal planning belongs to Mentat tasks.
- Named agent identity belongs to Hermes profiles.
- Agent Console is for interactive work; Hermes Kanban is the durable
  delegation path.
- Hermes sessions, cron inventory, Google Calendar, and Obsidian note content
  remain read-only.
- Mutations use fixed capabilities, validation, preview, confirmation, locking,
  and read-back verification.
- Secrets, local storage paths, and blob identifiers are not exposed to the
  browser.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full capability and safety
contract.

## Project map

```text
server.py                    Local HTTP server and workflow orchestration
public/                      Static dashboard UI
data/                        Public-safe project-owned seed data
data/runtime/                Private, generated, gitignored runtime data
hermes_*.py                  Capability-scoped Hermes adapters
agent_console_*.py           Console files, artifacts, and run support
task_planning.py             Planning validation and recurrence
scripts/mentat_setup.py      Local setup wizard
mentat.toml                  Shared configuration defaults
tests/                       Unit and contract tests
```

## Contributing

Keep changes small, local-first, and easy to understand. Please avoid direct
writes to Hermes core files and keep tracked fixtures free of personal data,
paths, credentials, and real message history.

Before handing off a change, run:

```bash
python -m py_compile server.py
python -m unittest discover -s tests -v
```

Developer guidance lives in [AGENTS.md](AGENTS.md). Recent changes are in
[CHANGELOG.md](CHANGELOG.md).

## Project status

Mentat is under active development. The current goal is a practical local tool
that stays friendly to new contributors while its workflows mature. If you find
something rough, an issue or a focused pull request is welcome.
