# Beta Support

Mentat is a single-developer beta. Support is best effort, with no guaranteed
response time.

## Current setup

- **Development build:** Python 3.11–3.13 and Git on macOS, Windows, or Linux
- **Agent features:** a supported Hermes runtime; planning features still work
  when Hermes is unavailable
- **Access:** one local operator; the Mentat dashboard stays on your computer

macOS and Windows are the tier-one beta targets. Linux is a preview platform.
There is no public-beta release yet, so use the
[README source setup](README.md#quick-start) unless you received a private
release-candidate invitation.

Invited testers should use the exact build and short
[limited beta checklist](BETA_TESTING.md) provided by the maintainer. Active,
public-safe problems and workarounds appear in [known beta issues](KNOWN_ISSUES.md).

## Known limitations

- Mentat is not a hosted service and does not support remote browser access or
  multiple operators.
- Remote Hermes features appear only when that runtime advertises Mentat's
  exact supported contracts. The maintained fork is currently the verified
  beta runtime; other Hermes releases need fresh compatibility evidence.
- Google Calendar, Obsidian notes, Hermes sessions, and Hermes cron inventory
  are read-only. Mentat does not queue or edit cron jobs.
- Updates are manual. Back up your data before upgrading.
- macOS releases use separate native packages. Apple Silicon (`arm64`) is the
  recommended default; Intel Macs use the `x86_64` package.
- Native signing/notarization and public release-channel settings remain release
  gates; they are not bypassed by source builds.

For ordinary bugs, use the [bug report form](https://github.com/hazeion/agent-os/issues/new?template=bug_report.yml).
For feature ideas, use the [feature request form](https://github.com/hazeion/agent-os/issues/new?template=feature_request.yml).
For possible security problems, use the [private security advisory form](https://github.com/hazeion/agent-os/security/advisories/new).
