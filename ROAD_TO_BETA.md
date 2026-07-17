# Mentat Road to Beta

Status: Milestone 0 in progress
Last updated: 2026-07-15

This document organizes the work required to make Mentat safe, installable,
supportable, and useful as a public beta. It is deliberately ordered: each
milestone removes a class of risk that later milestones depend on.

## What "public beta" means

The first public beta is a **locally installed, single-operator Mentat app for
Hermes users**. It remains bound to loopback and keeps the capability and
mutation boundaries in [ARCHITECTURE.md](ARCHITECTURE.md).

Public beta does not mean exposing Mentat as a hosted or remotely accessible
web service. Remote access would require a separate authentication,
authorization, tenancy, and threat-model project.

The beta should be:

- safe to install without placing personal data inside the application or Git
  checkout;
- safe to upgrade, back up, restore, and uninstall without losing operator
  data;
- predictable on the supported operating systems and Python versions;
- explicit when Hermes, Google Calendar, or Obsidian is unavailable;
- supportable through versioned releases, useful diagnostics, and a clear
  issue-reporting path;
- honest about limitations and beta-quality behavior.

## Recommended release contract

These are the recommended defaults for Milestone 0. They become commitments
only after project sign-off.

| Decision | Recommended beta choice |
| --- | --- |
| Audience | Hermes operators comfortable installing local software |
| Access model | One local operator; loopback only; no remote access |
| Tier-one platforms | macOS and Windows |
| Preview platform | Linux, covered by CI but not initially promised at the same support level |
| Python | 3.11 through 3.13 |
| Install channel | `pipx` from a tagged release; consider PyPI after the release process is proven |
| Update model | Manual, versioned upgrades with a pre-upgrade backup |
| Telemetry | Off and absent by default |
| First version | `0.1.0b1`, displayed to users as `v0.1.0-beta.1` |
| Native installers | Deferred until the package-based beta is stable |
| License | Project-owner decision required before public distribution |

## Current baseline

Mentat already has a strong product and safety foundation:

- a useful local dashboard with planning, Agent Console, Hermes profiles,
  durable Kanban delegation, Context Packs, notes, and a weekly calendar;
- a loopback-only server and a documented capability-scoped mutation boundary;
- setup and lifecycle scripts for POSIX and Windows;
- pinned runtime dependencies and a substantial unit/contract test suite;
- public-safe tracked fixtures and gitignored private runtime artifacts.

The largest beta gaps are operational rather than feature gaps:

- mutable user data still defaults to the repository's `data/` directory;
- there is no installable Python package, product version source, or unified
  `mentat` command;
- the repository has no automated GitHub Actions quality gate;
- backup, restore, upgrade, and rollback are not yet a complete user workflow;
- public trust and support documents are incomplete;
- the release and external-tester process has not been rehearsed.

## How roadmap work is organized

Each project artifact has one job:

| Artifact | Purpose |
| --- | --- |
| This roadmap | Milestone order, status, dependencies, and exit evidence |
| GitHub issue | One bounded implementation slice with acceptance criteria |
| Branch and draft pull request | Implementation, tests, review, and discussion |
| `CHANGELOG.md` | The operator-visible outcome that actually shipped |
| Obsidian notes | Private brainstorming, session summaries, and reusable learnings |

Do not put credentials, personal operator content, machine-specific paths, or
private diagnostics in GitHub issues or pull requests.

### Slice workflow

Every slice follows the same reviewable loop:

1. Select the next task from the earliest incomplete milestone.
2. Define the goal, non-goals, safety boundaries, acceptance criteria, and
   verification evidence in a GitHub issue.
3. Create a focused `codex/beta-<milestone>-<slice>` branch.
4. Add or identify the tests that prove the acceptance criteria before
   broadening implementation.
5. Implement only the agreed slice.
6. Run focused checks, the full suite, and rendered/browser verification when
   the slice changes user-facing behavior.
7. Review failure modes, compatibility, privacy, and rollback behavior.
8. Update the roadmap, changelog, and relevant private notes with the result.
9. Push a draft pull request with the evidence and unresolved decisions.
10. Merge or revise the slice before beginning dependent work.

### Early CI guardrail

Before Milestone 1 changes the data boundary, pull forward a narrow part of
Milestone 3: run Python compilation, JavaScript syntax checks, and the existing
test suite automatically on macOS, Windows, and Ubuntu. Packaging, release
artifacts, dependency scanning, and browser release gates remain in Milestone
3. This early guardrail exists to catch cross-platform path regressions while
the data-root work is still small.

## Milestone map

| Order | Milestone | Status | Depends on | Exit evidence |
| --- | --- | --- | --- | --- |
| 0 | Beta contract | In progress | — | Approved scope and support decisions |
| 1 | Durable user data | Not started | 0 | Migration, backup, restore, and clean-install tests |
| 2 | Installable product and CLI | Not started | 1 | Fresh `pipx` install and lifecycle smoke test |
| 3 | Automated quality gate | Not started | 2 | Required CI green on the supported matrix |
| 4 | Trust and support readiness | Not started | 0, 2 | Public policies, diagnostics, and issue path |
| 5 | Release-candidate rehearsal | Not started | 1–4 | Reproducible tagged RC with rollback drill |
| 6 | Limited external beta | Not started | 5 | Tester acceptance window completed |
| 7 | Public beta release | Not started | 6 | Published beta artifacts and release notes |

## Milestone 0 — Lock the beta contract

Goal: remove ambiguity about who the beta serves and what the project promises.

Work in order:

1. Adopt the slice-based working process in this roadmap. **Approved
   2026-07-15.**
2. Approve or revise the recommended release contract above.
3. Choose the public license.
4. Confirm tier-one operating systems and Python versions.
5. Confirm the initial install channel and version naming convention.
6. Define severity levels:
   - P0: data loss, secret exposure, unsafe mutation, or app-wide unusability;
   - P1: a core workflow is unusable with no reasonable workaround;
   - P2: degraded behavior with a workaround;
   - P3: polish, documentation, or minor inconvenience.
7. Record explicit non-goals and the policy for accepting beta feedback.

Exit criteria:

- the release contract is approved in this document;
- the license choice is recorded;
- supported and preview environments are unambiguous;
- the slice workflow and review evidence are used consistently;
- every later milestone can make decisions against the same target.

## Milestone 1 — Move user data out of the install

Goal: make operator data survive upgrades and keep a running installation from
modifying its application files or Git checkout.

Work in order:

1. Inventory every mutable path and classify it as seed data, operator data,
   cache, runtime data, log, backup, or configuration.
2. Add one platform-aware data-root resolver, preferably using
   [`platformdirs`](https://platformdirs.readthedocs.io/en/latest/platforms.html):
   - macOS: `~/Library/Application Support/Mentat`;
   - Windows: `%LOCALAPPDATA%\Mentat`;
   - Linux: `~/.local/share/Mentat`.
3. Treat the repository's `data/` files as immutable, public-safe seed data.
   Copy missing seeds into a new data root; never run against tracked fixtures.
4. Preserve explicit local overrides for development and advanced operators.
5. Detect legacy repo-local data and offer a previewed, backed-up migration.
   Do not silently overwrite either source or destination.
6. Add versioned data-schema migrations and forward-version refusal.
7. Implement atomic backup and restore with validation and a restore preview.
8. Add tests for first run, repeat run, migration, interrupted migration,
   upgrade, restore, and uninstall-data preservation.

Exit criteria:

- starting and using Mentat does not dirty a clean checkout or installation;
- a legacy operator can migrate without losing or duplicating data;
- backup and restore are documented, tested, and fail closed;
- an upgrade preserves tasks, settings, Context Packs, and private Console
  metadata according to their retention rules.

## Milestone 2 — Create an installable product and unified CLI

Goal: replace repository-specific setup steps with a versioned installation and
one predictable command surface.

Work in order:

1. Add `pyproject.toml` with metadata, Python compatibility, pinned runtime
   requirements, package data, and console entry points.
2. Establish one Mentat version source and expose it in the CLI, UI, health
   payload, diagnostics, and logs.
3. Introduce an incremental package layout without weakening the existing
   module boundaries or broadening the public API.
4. Provide these commands:
   - `mentat setup`
   - `mentat start`
   - `mentat stop`
   - `mentat status`
   - `mentat doctor`
   - `mentat backup`
   - `mentat restore`
5. Preserve the existing scripts as compatibility wrappers during the beta.
6. Test wheel/sdist contents and install into a fresh isolated environment.
7. Update the README from source-checkout instructions to an operator-first
   install path, with source setup retained for contributors.

Exit criteria:

- a clean machine can install Mentat through the chosen `pipx` path;
- no command depends on the current working directory;
- `mentat doctor` explains missing optional integrations without exposing
  credentials or private paths;
- version output is consistent everywhere;
- install, start, health, stop, upgrade, and uninstall-preservation smoke tests
  pass from an isolated environment.

Packaging references:

- [Writing `pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Creating and packaging command-line tools](https://packaging.python.org/en/latest/guides/creating-command-line-tools/)

## Milestone 3 — Make CI the release gate

Goal: turn the existing local verification into an automatic, repeatable
compatibility signal.

Work in order:

1. Add a GitHub Actions workflow for pull requests and `main`.
2. Run unit and contract tests on macOS, Windows, and Ubuntu across the approved
   Python versions.
3. Run Python compilation and JavaScript syntax checks.
4. Build the package and verify wheel/sdist contents.
5. Install the built artifact in a clean environment and exercise setup,
   lifecycle, and health checks.
6. Run browser smoke coverage on at least one supported platform.
7. Add dependency and secret scanning with actionable failure output.
8. Require the stable checks before merging and before creating a release tag.

Exit criteria:

- the required matrix is green from a clean checkout;
- packaging and lifecycle failures block release candidates;
- CI logs do not disclose environment secrets or private operator data;
- the exact release artifact has passed installation smoke tests.

CI reference: [Building and testing Python with GitHub Actions](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)

## Milestone 4 — Establish public trust and support

Goal: make it clear how Mentat handles data, security reports, contributions,
and beta support.

Work in order:

1. Add the approved `LICENSE`.
2. Add `SECURITY.md` with supported versions, private reporting instructions,
   response expectations, and the local-only threat boundary.
3. Add `PRIVACY.md` describing local storage, Google Calendar's read-only
   behavior, Obsidian access, Hermes ownership, logs, backups, and the absence
   of default telemetry.
4. Add `CONTRIBUTING.md`, a code of conduct decision, and focused issue
   templates for bugs, feature requests, and security-routing reminders.
5. Document supported platforms, prerequisites, known limitations, and the
   beta support window.
6. Add a user-initiated, redacted diagnostics bundle. It must omit secrets,
   personal content, local paths, blob identifiers, and unrestricted logs.
7. Add an in-app version, documentation, issue-reporting, and diagnostics path.

Exit criteria:

- a tester can understand where their data lives and what Mentat can mutate;
- security reports have a non-public path;
- bug reports include enough redacted environment information to be useful;
- support boundaries and known limitations are visible before installation.

## Milestone 5 — Rehearse a release candidate

Goal: prove that the release process works before inviting external testers.

Work in order:

1. Create a release checklist and scripted artifact build.
2. Generate a tagged release candidate such as `v0.1.0-beta.1-rc.1`.
3. Publish checksums, installation instructions, release notes, known
   limitations, backup steps, and rollback instructions.
4. Test clean installation on each tier-one platform.
5. Test upgrade from a representative legacy checkout and prior package build.
6. Restore a backup into a clean install and compare the expected data.
7. Test uninstall/reinstall while preserving operator data.
8. Practice revoking or replacing a bad release without hiding its history.

Exit criteria:

- another person can install the exact tagged artifact using only public docs;
- clean install, upgrade, rollback, backup, restore, and uninstall-preservation
  drills pass on every tier-one platform;
- artifact checksums and release notes are reproducible;
- there are no unresolved P0 or P1 issues.

## Milestone 6 — Run a limited external beta

Goal: learn from real installations while the tester group and support load are
still bounded.

Work in order:

1. Recruit a small cohort that represents the supported platforms and both new
   and experienced Hermes operators.
2. Give testers a short onboarding path and a structured first-run checklist.
3. Track installation success, time to first useful workflow, integration
   degradation, data migration, and recovery outcomes.
4. Triage reports by the Milestone 0 severity policy.
5. Ship small release candidates through the same gated process.
6. Keep a visible known-issues list and close the loop with testers.

Exit criteria:

- at least 10 external testers have used Mentat for roughly two weeks;
- supported-platform installation succeeds without maintainer intervention for
  the large majority of testers;
- backup and recovery have been exercised outside the maintainer environment;
- no unresolved P0 or P1 issue remains;
- repeated confusion has been fixed in product or onboarding documentation.

## Milestone 7 — Publish the beta

Goal: release a stable-enough beta to the public with a controlled support and
update path.

Work in order:

1. Freeze the release candidate except for release-blocking fixes.
2. Run the full CI, clean-install, upgrade, backup, restore, and rollback gates.
3. Tag `v0.1.0-beta.1` and publish the tested artifacts and checksums.
4. Publish release notes, known limitations, security/privacy links, and
   rollback instructions.
5. Open the public issue path and begin the documented beta support window.
6. Review beta health on a regular cadence and publish follow-up versions
   through the same release gate.

Exit criteria:

- every public artifact matches a tested release candidate;
- installation and recovery instructions are public and verified;
- users can identify the running version and report a redacted diagnostic;
- the issue queue has an owner and triage cadence;
- the release has no known unresolved P0 or P1 issue.

## Public beta definition of done

The release cannot be called public beta until all of the following are true:

- [ ] The beta contract and license are approved.
- [ ] User data lives outside the application/install directory by default.
- [ ] Legacy data migration is previewed, backed up, and tested.
- [ ] Backup, restore, upgrade, rollback, and uninstall preservation work.
- [ ] A versioned package and unified CLI install cleanly through the supported
  channel.
- [ ] Required CI is green on the supported platform/Python matrix.
- [ ] Missing Hermes, Google Calendar, or Obsidian degrades safely and clearly.
- [ ] Security, privacy, contributing, support, and known-limitations documents
  are public.
- [ ] Release artifacts, checksums, notes, and rollback instructions are
  reproducible.
- [ ] The limited external beta meets its cohort and stability exit criteria.
- [ ] There are no unresolved P0 or P1 issues.

## Work intentionally deferred until after beta

- non-loopback or hosted access;
- authentication, multi-user accounts, or multi-tenancy;
- native signed installers and automatic updates;
- telemetry or analytics by default;
- Hermes cron write controls without upstream atomic capabilities;
- general Hermes configuration, soul, skill-content, credential, or MCP
  editors;
- large new product surfaces that do not close a beta acceptance gap.

## Current next actions

1. Finish Milestone 0 by approving the release contract and choosing the
   license. These remain explicit project-owner decisions.
2. Land the early CI guardrail described above.
3. Begin Milestone 1A with a complete mutable-path inventory and data-layout
   contract before changing any runtime default.
4. Do not begin a dependent slice while an earlier data-safety or release
   blocker remains open.
