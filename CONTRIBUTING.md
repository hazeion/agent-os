# Contributing

Thanks for helping Mentat grow! Small, focused changes are the easiest to
review and ship.

1. For a larger change, open a bug or feature request first so we can agree on
   the goal. Small fixes can go straight to a pull request.
2. Fork the repository and create a short-lived branch.
3. Follow the [README setup](README.md#quick-start).
4. Keep Mentat local-first and follow the safety boundaries in
   [AGENTS.md](AGENTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
5. Before opening a pull request, run:

   ```bash
   python -m compileall -q .
   node --check public/core.js
   node --check public/app.js
   python -m unittest discover -s tests -v
   ```

   If your change touches `web/`, use Node 24.19 or newer within Node 24 and
   also run:

   ```bash
   npm --prefix web ci --ignore-scripts
   npm --prefix web run check
   npm --prefix web run build
   python scripts/mentat_web_preview.py
   ```

   Open `http://localhost:8890`, inspect the production preview, and stop it
   with Ctrl+C. While it is running, use another terminal for the repeatable
   performance gate. Install the repository-pinned Chrome for Testing release,
   then use the executable path printed by the install command:

   ```bash
   web/node_modules/.bin/browsers install chrome@152.0.7923.0 --path web/.browser-cache/chrome-for-testing
   CHROME_PATH="<printed executable path>" npm --prefix web run lighthouse:gate
   ```

   The gate rejects a different browser version. Required CI uses the same
   non-auto-updating Chrome for Testing build and uploads a bounded diagnostic
   summary if an audit fails.

6. Open a focused pull request. Explain what changed for the user, how you
   checked it, and any limitations that remain.

Node.js 24 is used for JavaScript syntax checks and the optional Next.js source
preview. The installed compatibility dashboard remains Python-hosted and does
not bundle Node yet.

Never commit credentials, personal data, real message history, machine-specific
paths, or generated runtime files. By participating, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Security reports belong in the
[private advisory form](https://github.com/hazeion/agent-os/security/advisories/new),
not a public issue. Questions and setup problems can use the
[issue chooser](https://github.com/hazeion/agent-os/issues/new/choose).
