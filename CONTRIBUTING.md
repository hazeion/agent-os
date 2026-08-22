# Contributing

Thanks for helping with Mentat. Small, focused changes are easier to review and
safer to ship.

## Before you start

1. Read [AGENTS.md](AGENTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
2. For larger work, agree on the scope before writing code.
3. Create a short-lived branch from the latest `main`.
4. Keep private data, credentials, local paths, and runtime files out of Git.

## Check Python changes

Run these commands from the repository root:

```bash
python -m compileall -q .
node --check public/core.js
node --check public/app.js
python -m unittest discover -s tests -v
```

The files in `public/` are the rollback interface. Keep their tests green.

## Check web changes

Changes under `web/` need Node 24.19 or newer within Node 24.

```bash
npm --prefix web ci --ignore-scripts
npm --prefix web run check
npm --prefix web run build
./run.sh
```

Open [http://localhost:8888](http://localhost:8888). Check the page at desktop
and mobile widths, then stop the preview with Ctrl+C.

The production dashboard must run through `./run.sh` (or `run.bat`). The web
package does not provide `npm start` because the supervisor owns Node and
Python processes. Use `--legacy-ui` only when checking rollback.

## Run the Lighthouse gate

Install the pinned browser once:

```bash
web/node_modules/.bin/browsers install chrome@152.0.7923.0 --path web/.browser-cache/chrome-for-testing
```

Use the executable path printed by that command:

```bash
CHROME_PATH="<printed executable path>" npm --prefix web run lighthouse:gate
```

The gate runs three desktop audits and three mobile audits. Every category must
score 100. CI uses the same Lighthouse and Chrome versions.

## Open a pull request

Explain what changed, how you tested it, and what remains unfinished. Do not
include credentials, personal data, private messages, machine-specific paths,
or generated runtime files.

Report security problems through the
[private advisory form](https://github.com/hazeion/agent-os/security/advisories/new),
not a public issue.
