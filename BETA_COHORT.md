# Limited Beta Cohort Runbook

This runbook prepares the small external beta. It does not replace the signed
release rehearsal and is not evidence that the cohort has started.

## Entry gate

Begin invitations only after Milestone 6 is marked complete and every one of
its exit criteria passes. The exact RC must have the full cross-platform and
channel matrix in [the release rehearsal](RELEASE_REHEARSAL.md): Intel macOS,
Apple Silicon with Rosetta, Windows, and supported `pipx`, including clean
install, upgrade, backup, restore, uninstall preservation, and rollback. Every
tester receives one exact immutable RC and [the tester checklist](BETA_TESTING.md).

## Cohort shape

- Recruit at least 10 external testers for roughly two weeks.
- Cover macOS and Windows, plus both new and experienced Hermes operators.
- Exercise both local and remote Hermes. Linux may contribute preview evidence
  but does not replace a tier-one platform.
- Assign recovery drills to willing testers using disposable test data.

Each invitation packet includes the exact Mentat RC, exact verified Hermes
runtime/build, safe setup link, and assigned local or remote connection steps.
Share credentials privately. The first-workflow timer starts when Mentat
installation begins with Hermes ready and stops after the tester creates a
project/task and completes the assigned Hermes workflow.

Keep the participant roster and raw session notes in private maintainer
storage. Do not commit names, email addresses, account identifiers,
credentials, endpoints, conversation content, note contents, diagnostics, or
participant-level timelines. Give each tester an opaque local identifier and
publish only aggregate, redacted results.

## Evidence to record privately

For each tester, record:

- exact RC and Hermes runtime versions, platform, install channel, and Hermes
  experience level;
- install success and whether it needed maintainer intervention;
- approximate time to first useful workflow;
- local or remote Hermes mode and any integration degradation;
- assigned backup and recovery result;
- assigned migration result;
- issue links and severity, without copying private report content.

Use one consistent outcome vocabulary: `pass`, `pass-with-help`, `blocked`, or
`not-run`. The public form's friendly labels map to those four values in order;
“not assigned” or “not applicable” maps to `not-run`. Do not turn missing
evidence into a pass.

For every remote tester, assign and record every row in this matrix with that
same vocabulary. Use the matching performer, safe action, and pass criteria in
[Remote Hermes Beta Checks](REMOTE_BETA_MATRIX.md). The row names map
one-for-one to the capabilities currently marked **Required** in
[the remote contract](REMOTE_HERMES.md).

### Remote evidence matrix v1

| Required capability |
| --- |
| Public connection liveness |
| Authenticated readiness and capability discovery |
| Hermes configuration and overview summary |
| Agent Console conversation and streaming |
| Run status, progress, approval, cancellation, and stopping |
| Clarification requests and responses |
| Session list, replay, continuation, and search |
| Read-only agent/profile discovery |
| Skill and toolset visibility |
| Durable Kanban delegation and follow-up |
| Console input attachments and Context Packs |
| Connection setup and local/remote runtime selection |
| Hermes diagnostics |

Aggregate by matrix version, exact RC, and Hermes runtime. Every row needs
external remote evidence before the mandatory remote capability exit criterion
can pass. Update the matrix version whenever a Required contract row changes.

## Triage and release cadence

- Triage P0 and P1 reports immediately. They block invitations and releases.
- Prioritize P2 and P3 reports by frequency and operator impact.
- Move possible vulnerabilities to the private security advisory path.
- Fix repeated confusion in the product or onboarding docs, not only in direct
  replies.
- Update [known beta issues](KNOWN_ISSUES.md) at least twice a week and before
  each invitation wave or RC. The maintainer owns this list.
- Ship another numbered RC only through the same protected Milestone 6 gate.
  Never replace an existing tag or artifact in place.

## Aggregate checkpoint

At least twice a week, update a private checkpoint with:

```text
Invited / started / completed:
Platform and install-channel counts:
Installs without maintainer intervention:
No-help install rate / 80% threshold:
No-help numerator / denominator by Intel Mac native, Apple Silicon + Rosetta native, Windows native, and pipx:
First-workflow time-bucket counts and median observed bucket:
Local / remote Hermes exercises:
Remote capability category passes / assigned:
Backup and recovery passes / assigned:
Migration passes / attempted:
Open P0 / P1 / P2 / P3:
Repeated confusion and action taken:
```

The final public summary may contain these aggregate counts and redacted issue
links only.

## Exit decision

Milestone 7 passes only when the roadmap's full cohort window and platform,
installation, recovery, remote-capability, severity, and repeated-confusion
criteria are supported by the private evidence. Otherwise extend the cohort or
ship a corrected RC; do not lower an unmet criterion after seeing the results.

“Large majority” means at least 80% of supported-platform testers who begin a
Mentat install finish the install without maintainer intervention. Every
product-caused install block, dropout after starting, and help-assisted install
remains in the denominator and is not a success. A first workflow that is `not
reached` is reported separately and does not rewrite a completed install.
Record demonstrably unrelated withdrawals separately; they never silently
disappear from the cohort report.

The cohort also needs at least one no-help success for the Intel Mac native,
Apple Silicon with Rosetta native, Windows native, and supported `pipx` strata.
Report numerator and denominator separately for each; the 80% overall result
cannot hide a stratum with no independent success.
