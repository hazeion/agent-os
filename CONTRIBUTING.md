# Contributing

Thanks for helping Mentat grow. Small, focused changes are easiest to review.

1. Open a bug or feature issue so the goal is clear.
2. Fork the repo and create a short-lived branch.
3. Keep Mentat local-first and follow the safety boundaries in
   [AGENTS.md](AGENTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
4. Run:

   ```bash
   python -m py_compile server.py
   python -m unittest discover -s tests -v
   ```

5. Open a focused pull request and explain the user-visible result.

Never commit credentials, personal data, real message history, machine-specific
paths, or generated runtime files. By participating, you agree to follow the
[Code of Conduct](CODE_OF_CONDUCT.md). Security reports belong in the
[private advisory form](https://github.com/hazeion/agent-os/security/advisories/new),
not a public issue.
