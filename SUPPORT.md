# Beta Support

Mentat is a single-developer beta. Support is best effort, with no guaranteed
response time.

## Supported setup

- **Tier one:** current macOS and Windows releases
- **Preview:** Linux, covered by CI but not yet promised at the same level
- **Python fallback:** Python 3.11–3.13 with Git and a supported Hermes runtime
- **Access:** one local operator; Mentat stays bound to loopback

Signed native installers are required for the public beta but are not published
yet. Until then, the README source setup is the supported way to try the current
development build.

## Known limitations

- Mentat is not a hosted service and does not support remote browser access or
  multiple operators.
- Remote Hermes features appear only when that runtime advertises Mentat's
  exact supported contracts. The maintained fork is currently the verified
  beta runtime; other Hermes releases need fresh compatibility evidence.
- Google Calendar, Obsidian notes, Hermes sessions, and Hermes cron inventory
  are read-only. Mentat does not queue or edit cron jobs.
- Updates are manual. Make a backup before upgrading.
- Native signing/notarization and public release-channel settings remain release
  gates; they are not bypassed by source builds.

For ordinary bugs, use the [bug report form](https://github.com/hazeion/agent-os/issues/new?template=bug_report.yml).
For possible security problems, use the [private security advisory form](https://github.com/hazeion/agent-os/security/advisories/new).
