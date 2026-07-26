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

6. Open a focused pull request. Explain what changed for the user, how you
   checked it, and any limitations that remain.

Node.js is only needed for the JavaScript syntax checks. There is no npm build
or frontend dependency install.

Never commit credentials, personal data, real message history, machine-specific
paths, or generated runtime files. By participating, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Security reports belong in the
[private advisory form](https://github.com/hazeion/agent-os/security/advisories/new),
not a public issue. Questions and setup problems can use the
[issue chooser](https://github.com/hazeion/agent-os/issues/new/choose).
