<p align="center">
  <img src="public/mentat-logo.png" alt="Mentat" width="320" />
</p>

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
- Reuse Context Packs that combine standard instructions, Obsidian notes, and
  safe workspace files for Console prompts or reviewed delegation context.
- Delegate durable tasks through Hermes Kanban and review results, questions,
  retries, and revisions from Mentat.
- Browse read-only Hermes sessions and cron inventory.
- Search Obsidian notes, scan a full read-only Google Calendar week, and use the
  Agent Pulse live heartbeat registry.
- Choose from compact, soft-light, and popular editor-inspired color themes.

## A small, local stack

Mentat uses:

- a Python server;
- a static HTML, CSS, and vanilla JavaScript frontend;
- local JSON for project-owned tasks and settings;
- private SQLite metadata and content-addressed blobs for Console files.

There is currently **no npm install step**.

Hermes profiles are the canonical agent identities. Mentat uses supported,
validated Hermes operations for agent control and keeps provider/model
credentials in Hermes. The future remote-connection API key will be
Mentat-owned, server-only operator configuration stored outside the install.

## Remote Hermes direction

The public-beta contract keeps Mentat installed locally and bound to loopback,
while allowing one active local or operator-managed remote Hermes endpoint.
Remote mode is not implemented yet. Its mandatory feature set, HTTPS/API-key
boundary, safe degradation rules, and upstream Kanban, profile-discovery, and
clarification blockers are documented in
[REMOTE_HERMES.md](REMOTE_HERMES.md).

Mentat will not expose its own dashboard to the network, send a Hermes API key
to the browser, mount a remote Hermes home, or use SSH and undocumented APIs as
substitutes for supported capabilities.

## Quick start

Native installers are required for the public beta but are not implemented yet.
Until the packaging and installer milestones are complete, the following
source-checkout instructions remain the current install path.

You need Python 3.11 through 3.13. Install and configure
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
python server.py --data-dir "/path/to/mentat-data" --preview-legacy-migration
python server.py --data-dir "/path/to/mentat-data" --confirm-legacy-migration TOKEN_FROM_PREVIEW
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
- `MENTAT_DATA_DIR`
- `HERMES_HOME`
- `OBSIDIAN_VAULT_PATH`
- `MENTAT_CONFIG`

Command-line values override environment variables, which override local and
shared configuration files.

The source checkout currently keeps `data_dir = "data"` in the shared config.
The approved installed-app target, platform defaults, complete mutable-path
inventory, missing-only seed rules, and migration/backup safety boundary are in
[DATA_LAYOUT.md](DATA_LAYOUT.md). Milestone 1A documents and tests that contract.
Milestone 1B resolves the approved platform default for config-less
installs, preserves the tracked development override, exposes a non-sensitive
source label in `--print-config`, and supplies bounded preflight plus
lock-protected, owner-only, missing-only seed initialization. A clean installed
launch can initialize before ordinary runtime writes, while legacy checkout
data, conflicts, links, invalid files, and raced destinations fail closed.
Milestone 1C adds explicit CLI preview and token-confirmation for the nine
durable JSON slots, using legacy files or explicit packaged-seed fallbacks,
with a verified migration backup, locked revalidation, missing-only
publication, safe interruption resume, source
preservation, and a verified completion receipt. Use the same `--data-dir` and,
if supplied, `--legacy-data-dir` for preview and confirmation. Milestone 1D
adds a fixed owner-only sidecar schema manifest, current metadata for clean
installs, explicit backed-up version-0 to version-1 bootstrap, and startup
refusal for newer unsupported versions. Existing unversioned roots remain
supported until explicitly upgraded. If preview reports `recovery_required`,
confirm that exact token to discard only the revalidated orphan schema
temporary, then preview again:

```bash
python server.py --data-dir "/path/to/mentat-data" --preview-schema-migration
python server.py --data-dir "/path/to/mentat-data" --confirm-schema-migration TOKEN_FROM_PREVIEW
```

Milestone 1E-A adds fixed durable-JSON backup and restore. It creates an
owner-only versioned archive of the nine schema-governed documents, then
requires an exact read-only preview and matching confirmation before restore.
It publishes a pre-restore recovery archive and resumes only recognized exact
interruption state; startup blocks ambiguous or incomplete restore evidence.

```bash
python server.py --data-dir "/path/to/mentat-data" --create-backup
python server.py --data-dir "/path/to/mentat-data" --preview-restore --restore-backup "/path/to/mentat-backup-v1-ID.zip"
python server.py --data-dir "/path/to/mentat-data" --confirm-restore TOKEN_FROM_PREVIEW --restore-backup "/path/to/mentat-backup-v1-ID.zip"
```

Private Console history/SQLite/blob backup, private-state movement, unified
installed CLI commands, and installer behavior remain separate roadmap work.
`--print-config` and every preview mode remain side-effect-free.

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
data_layout.py               Data-root resolver, preflight, and safe initializer
data_migration.py            Previewed, backed-up legacy JSON migration
data_schema.py               Durable JSON schema manifest and migration
public/                      Static dashboard UI
data/                        Public-safe project-owned seed data
data/runtime/                Private, generated, gitignored runtime data
DATA_LAYOUT.md               Approved target data-root and migration contract
hermes_*.py                  Capability-scoped Hermes adapters
agent_console_*.py           Console files, artifacts, and run support
task_planning.py             Planning validation and recurrence
scripts/mentat_setup.py      Local setup wizard
mentat.toml                  Shared configuration defaults
ARCHITECTURE.md              Capability and mutation contract
REMOTE_HERMES.md             Remote capability matrix and trust boundary
ROAD_TO_BETA.md              Ordered public-beta milestones and exit evidence
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
[CHANGELOG.md](CHANGELOG.md). Mentat is licensed under the [MIT License](LICENSE).

## Project status

Mentat is under active development. The current goal is a practical local tool
that stays friendly to new contributors while its workflows mature. If you find
something rough, an issue or a focused pull request is welcome.

The ordered release plan, milestone dependencies, and public-beta acceptance
criteria live in [ROAD_TO_BETA.md](ROAD_TO_BETA.md). The beta contract is
approved: macOS and Windows are tier one, Linux is preview, Python 3.11 through
3.13 is supported, and signed native installers plus a supported `pipx` path
are required release channels. Those artifacts do not exist yet. The early CI
guardrail, Milestone 1A data-layout contract, Milestone 1B resolver/preflight/
initializer, and Milestone 1C legacy durable-JSON migration are complete.
Durable JSON schema evolution and its bounded backup/restore foundation are
complete. Moving private Console state and adding its consistent backup unit
remain the next durable-data work before remote-Hermes implementation and
packaging begin.
