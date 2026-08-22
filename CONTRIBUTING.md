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

The files in `public/` are the current compatibility interface. Keep its tests
green while the Next.js app is being built.

## Check web changes

Changes under `web/` need Node 24.19 or newer within Node 24.

```bash
npm --prefix web ci --ignore-scripts
npm --prefix web run check
npm --prefix web run build
python scripts/mentat_web_preview.py
```

Open [http://localhost:8890](http://localhost:8890). Check the page at desktop
and mobile widths, then stop the preview with Ctrl+C.

The production preview must run through `scripts/mentat_web_preview.py`. The web
package does not provide `npm start` because the supervisor owns the Node and
Python processes.

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
