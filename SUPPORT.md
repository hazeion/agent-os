# Beta support

Mentat is a single-developer beta. Support is best effort and has no guaranteed
response time.

## Current setup

Mentat needs:

- Python 3.11-3.13
- Node 24.19 or newer within Node 24
- Git
- macOS, Windows, or Linux

Agent features need a supported Hermes runtime. Planning still works when
Hermes is unavailable.

The default dashboard is a local Node gateway with a private Python bridge.
Native packages include the prebuilt dashboard; Node remains a host
prerequisite. Use `mentat start --legacy-ui` only for temporary rollback.

macOS and Windows are the main beta platforms. Linux is a preview platform.
There is no public beta release yet, so use the
[README source setup](README.md#quick-start) unless you received a private
release candidate invitation.

Invited testers should use the exact build in their invitation and follow the
[limited beta checklist](BETA_TESTING.md).

## Known limitations

- Mentat is for one local operator. It is not a hosted service and does not
  support remote browser access.
- Remote Hermes features appear only when the runtime advertises the exact
  contract Mentat needs.
- Google Calendar, Obsidian notes, Hermes sessions, and Hermes cron inventory
  are read-only.
- Mentat does not queue or edit cron jobs.
- Updates are manual. Back up your data before upgrading.
- macOS packages are separate for Apple Silicon and Intel. Apple Silicon is the
  recommended package.
- Signing, notarization, and public release settings are still release gates.

Check [known beta issues](KNOWN_ISSUES.md) for current problems and
workarounds.

Use the [bug report form](https://github.com/hazeion/agent-os/issues/new?template=bug_report.yml)
for ordinary bugs. Use the
[feature request form](https://github.com/hazeion/agent-os/issues/new?template=feature_request.yml)
for ideas. Report security problems through the
[private security advisory form](https://github.com/hazeion/agent-os/security/advisories/new).
