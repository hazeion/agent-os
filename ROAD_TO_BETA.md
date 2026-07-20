# Mentat Road to Beta

Status: Milestone 2 in progress — 2A through 2C and 2E through 2H complete
Last updated: 2026-07-20
Beta release contract approved: 2026-07-17
Remote architecture and license decisions approved: 2026-07-16

This document organizes the work required to make Mentat safe, installable,
supportable, and useful as a public beta. It is deliberately ordered: each
milestone removes a class of risk that later milestones depend on.

## What "public beta" means

The first public beta is a **locally installed, single-operator Mentat app for
Hermes users**. Mentat remains bound to loopback and connects to one active
local or remote Hermes endpoint through the capability and mutation boundaries
in [ARCHITECTURE.md](ARCHITECTURE.md) and
[REMOTE_HERMES.md](REMOTE_HERMES.md).

Public beta does not mean exposing Mentat itself as a hosted or remotely
accessible web service. The operator may instead keep Mentat on the current
device and connect its server to an operator-managed Hermes host over verified
HTTPS. Hosted Mentat, browser-to-Hermes access, multi-user access, and
Mentat-managed relays remain separate authentication, authorization, tenancy,
and threat-model projects.

The beta should be:

- safe to install without placing personal data inside the application or Git
  checkout;
- safe to upgrade, back up, restore, and uninstall without losing operator
  data;
- predictable on the supported operating systems and Python versions;
- explicit when Hermes, Google Calendar, or Obsidian is unavailable;
- able to preserve its mandatory workflows when Hermes is reached through the
  approved remote capability boundary;
- supportable through versioned releases, useful diagnostics, and a clear
  issue-reporting path;
- honest about limitations and beta-quality behavior.

## Beta contract decisions

The remote architecture and MIT license were approved by the project owner on
2026-07-16. The remaining release choices, severity definitions, and feedback
policy were approved on 2026-07-17. This table is the authoritative beta
release contract for later implementation and release decisions.

| Decision | Current beta choice | Status |
| --- | --- | --- |
| Audience | Hermes operators comfortable installing local software | Approved 2026-07-17 |
| Access model | One local operator; Mentat loopback only; one active local or remote Hermes endpoint | Approved 2026-07-16 |
| Remote transport | Operator-supplied HTTPS endpoint and API key; server-to-server only | Approved 2026-07-16 |
| Remote parity | Console, sessions/runs, approvals/clarification/cancellation/stopping, skills/toolsets, Kanban, and read-only profile discovery are mandatory; approved administration features may degrade clearly | Approved 2026-07-16 |
| Tier-one platforms | macOS and Windows | Approved 2026-07-17 |
| Preview platform | Linux, covered by CI but not initially promised at the same support level | Approved 2026-07-17 |
| Python | 3.11 through 3.13 | Approved 2026-07-17 |
| Install channels | Native installers are primary on tier-one platforms; `pipx` from a tagged release remains supported as an advanced/fallback channel and is the Linux preview path | Approved 2026-07-17 |
| Native installers | A signed and notarized native installer for macOS and a signed native installer for Windows are required public-beta artifacts; they bundle or manage the required runtime and launch loopback-only Mentat | Approved 2026-07-17 |
| Installer implementation | Exact installer formats and tooling are selected in Milestone 3; the current source-checkout flow remains in place until that work is complete | Approved 2026-07-17 |
| Update model | Manual, versioned upgrades with a pre-upgrade backup | Approved 2026-07-17 |
| Telemetry | Off and absent by default | Approved 2026-07-17 |
| First version | `0.1.0b1`, displayed to users as `v0.1.0-beta.1` | Approved 2026-07-17 |
| License | MIT | Approved 2026-07-16 |

## Current baseline

Mentat already has a strong product and safety foundation:

- a useful local dashboard with planning, Agent Console, Hermes profiles,
  durable Kanban delegation, Context Packs, notes, and a weekly calendar;
- a loopback-only server and a documented capability-scoped mutation boundary;
- setup and lifecycle scripts for POSIX and Windows;
- pinned runtime dependencies and a substantial unit/contract test suite;
- public-safe tracked fixtures and gitignored private runtime artifacts.

The largest beta gaps are operational rather than feature gaps:

- clean installed layouts initialize the platform root from immutable seeds;
  legacy durable JSON and private Console state migrate explicitly; schema,
  backup/restore, application-upgrade, and application-only uninstall
  preservation boundaries are implemented and tested;
- there is no installable Python package, native installer, product version
  source, or unified `mentat` command;
- the early GitHub Actions matrix is in place, while later packaging, browser,
  dependency, and release gates remain outstanding;
- the selected remote runtime supports plain default-profile Console runs plus
  bounded read-only session history; richer inputs, continuation, and the
  remaining mandatory parity capabilities are still outstanding;
- complete remote profile discovery and API-key-authenticated Kanban require a
  supported upstream Hermes capability;
- backup, restore, upgrade, and rollback are not yet a complete user workflow;
- public trust and support documents are incomplete;
- the release and external-tester process has not been rehearsed.

## How roadmap work is organized

Each project artifact has one job:

| Artifact | Purpose |
| --- | --- |
| This roadmap | Milestone order, status, dependencies, and exit evidence |
| Persistent review log | Approved contract, test strategy, evidence, reviewer findings, and outcome |
| GitHub issue | Optional public tracker for one already-bounded slice |
| Branch and ready pull request | Verified implementation and public review after explicit publication approval |
| `CHANGELOG.md` | The operator-visible outcome that actually shipped |
| Obsidian notes | Private brainstorming, session summaries, and reusable learnings |

Do not put credentials, personal operator content, machine-specific paths, or
private diagnostics in GitHub issues or pull requests.

### Slice workflow

Every slice follows the same reviewable loop:

1. Select the next task from the earliest incomplete milestone.
2. Discuss and explicitly approve the goal, non-goals, safety boundaries,
   acceptance criteria, and version-control strategy.
3. Discuss and explicitly approve the test strategy and accepted evidence gaps.
4. Create a persistent review log and focused
   `codex/beta-<milestone>-<slice>` branch.
5. Implement only the agreed slice and keep the review log current.
6. Run focused checks, the full suite, and rendered/browser verification when
   the slice changes user-facing behavior.
7. Give the same diff and evidence to two independent adversarial reviewers;
   reconcile, fix, and re-review blocking findings.
8. Update the roadmap, changelog, and relevant private notes with the result.
9. Present the final diff, evidence, risks, commit message, and ready-PR packet;
   request explicit approval immediately before staging or publication.
10. After approval, publish a ready pull request and complete an outcome review
    before authorizing another slice.

### Early CI guardrail

Implemented by `.github/workflows/ci.yml`, this narrow part of Milestone 4 runs
Python compilation, JavaScript syntax checks, and the existing test suite on
pull requests and pushes to `main`. It covers all nine OS/Python combinations:
macOS, Windows, and Ubuntu with Python 3.11, 3.12, and 3.13. The guardrail is
complete only when its GitHub-hosted matrix is green.

Packaging, release artifacts, dependency scanning, browser release gates, and
branch-protection configuration remain in Milestone 4 after the installable
product work in Milestone 3. Keeping those later gates separate lets this early
guardrail catch cross-platform path regressions while the Milestone 1 data-root
work is still small.

## Milestone map

| Order | Milestone | Status | Depends on | Exit evidence |
| --- | --- | --- | --- | --- |
| 0 | Beta contract | Complete | — | Approved release, support, distribution, severity, and feedback contract |
| 1 | Durable user data | Complete — 1A through 1F | 0 | Upgrade/uninstall preservation tests |
| 2 | Secure remote Hermes parity | In progress — 2A through 2C and 2E through 2H complete; approval response and continuation blockers recorded | 1 | Mandatory remote capabilities verified over HTTPS |
| 3 | Installable product, native installers, and CLI | Not started | 2 | Fresh native and `pipx` installs plus lifecycle smoke tests |
| 4 | Automated quality gate | Not started | 3 | Required CI green on the supported matrix |
| 5 | Trust and support readiness | Not started | 0, 3, 4 | Public policies, diagnostics, and issue path |
| 6 | Release-candidate rehearsal | Not started | 1–5 | Reproducible tagged RC with rollback drill |
| 7 | Limited external beta | Not started | 6 | Tester acceptance window completed |
| 8 | Public beta release | Not started | 7 | Published beta artifacts and release notes |

## Milestone 0 — Lock the beta contract

Goal: remove ambiguity about who the beta serves and what the project promises.

Work in order:

1. Adopt the slice-based working process in this roadmap. **Approved
   2026-07-15.**
2. Approve the remaining release contract choices above. **Approved
   2026-07-17.**
3. Choose the public license. **MIT approved 2026-07-16.**
4. Approve the local-Mentat/one-endpoint remote Hermes architecture and
   mandatory capability set. **Approved 2026-07-16.**
5. Confirm tier-one operating systems and Python versions. **Approved
   2026-07-17.**
6. Confirm the install channels, signed native-installer requirement, update
   model, telemetry policy, and version naming convention. **Approved
   2026-07-17.**
7. Define severity levels. **Approved 2026-07-17:**
   - P0: data loss, secret exposure, unsafe mutation, or app-wide unusability;
   - P1: a core workflow is unusable with no reasonable workaround;
   - P2: degraded behavior with a workaround;
   - P3: polish, documentation, or minor inconvenience.
8. Record explicit non-goals and the policy for accepting beta feedback.
   **Approved 2026-07-17:**
   - P0 and P1 issues block a release;
   - P2 and P3 issues are prioritized by frequency and operator impact;
   - ordinary reports use GitHub Issues after the public issue path opens;
   - security reports use the private channel established in Milestone 5;
   - beta support is best effort with no guaranteed response-time SLA;
   - reports must exclude credentials and private operator content; and
   - the explicit beta non-goals are maintained in the deferred-work section
     below.

Exit criteria:

- the release contract is approved in this document;
- the license choice is recorded;
- supported and preview environments are unambiguous;
- the slice workflow and review evidence are used consistently;
- every later milestone can make decisions against the same target.

The approved remote capability details and upstream blockers are recorded in
[REMOTE_HERMES.md](REMOTE_HERMES.md). Milestone 0 is complete; changes to this
contract require another explicit project-owner decision.

## Milestone 1 — Move user data out of the install

Goal: make operator data survive upgrades and keep a running installation from
modifying its application files or Git checkout.

Status: Milestone 1A contract, Milestone 1B resolver/preflight/initializer,
Milestone 1C legacy durable-JSON migration, Milestone 1D schema versioning, and
Milestone 1E-A durable-JSON backup/restore complete. Milestone 1E-B durable
private Console migration/backup/restore and Milestone 1F application-upgrade/
uninstall preservation coverage are also complete. The complete current mutable-path inventory, target directory
classes, platform defaults,
precedence, and fail-closed initialization/migration/backup rules are approved
in [DATA_LAYOUT.md](DATA_LAYOUT.md). A clean config-less installed launch now
creates the owner-only layout and copies only missing immutable seeds under a
cross-process lock. An explicit CLI preview/confirmation flow can migrate the
nine legacy JSON documents after a validated backup; the source remains
unchanged. The fixed JSON inventory has explicit version metadata, backed-up
bootstrap, forward-version refusal, and validated preview-confirm
backup/restore. Retained Console history, SQLite metadata, and referenced blobs
now use one owner-only durable consistency unit with explicit legacy migration,
WAL-safe version-2 backup, exact restore, and version-1 restore compatibility.

Work in order:

1. Inventory every mutable path and classify it as seed data, operator data,
   cache, runtime data, log, backup, or configuration.
2. Add one platform-aware standard-library data-root resolver: **Milestone 1B-A
   complete.**
   - macOS: `~/Library/Application Support/Mentat`;
   - Windows: `%LOCALAPPDATA%\Mentat`;
   - Linux: `$XDG_DATA_HOME/Mentat` when valid and set, otherwise
     `~/.local/share/Mentat`.
3. Treat the repository's `data/` files as immutable, public-safe seed data.
   Copy missing seeds into a new data root; never run against tracked fixtures.
   **Milestone 1B-B complete.**
4. Preserve explicit local overrides for development and advanced operators.
5. Detect legacy repo-local data and offer a previewed, backed-up migration.
   Do not silently overwrite either source or destination. **Milestone 1C
   complete.**
6. Add versioned data-schema migrations and forward-version refusal.
   **Milestone 1D complete.**
7. Implement atomic backup and restore with validation and a restore preview.
   **Milestone 1E-A complete for the fixed durable JSON set; Milestone 1E-B
   complete for the retained private Console consistency unit.**
8. Add tests for first run, repeat run, migration, interrupted migration,
   upgrade, restore, and uninstall-data preservation. **Milestone 1F complete.**

Exit criteria:

- starting and using Mentat does not dirty a clean checkout or installation;
- a legacy operator can migrate without losing or duplicating data;
- backup and restore are documented, tested, and fail closed;
- an upgrade preserves tasks, settings, Context Packs, and private Console
  metadata according to their retention rules; and
- removing only the application tree preserves the external data root, while a
  reinstall reconnects without recopying packaged defaults.

## Milestone 2 — Secure remote Hermes parity

Goal: let local Mentat use one operator-managed remote Hermes host without
weakening either product's capability, credential, or verification boundaries.

Work in order:

1. Store one active connection selection and its API credential in the
   owner-only operator-data boundary created by Milestone 1. **Milestone 2A
   foundation complete.**
2. Add a bounded server-side HTTPS client that rejects credentials in URLs,
   cross-origin redirects, invalid certificates, unbounded responses, and
   unsupported capability schemas. **Milestone 2A foundation complete for the
   fixed discovery paths.**
3. Treat public health only as untrusted liveness; discover trusted readiness,
   version, active-profile, authentication, and feature capabilities through
   authenticated responses without returning the API key or upstream response
   details to the browser. **Milestone 2A implements readiness, version, model,
   authentication, and feature discovery; complete active-profile inventory
   remains blocked on the capability in item 7.**
4. Introduce a transport-neutral adapter boundary while preserving the existing
   local Hermes behavior. **Milestone 2B foundation complete for Agent Console
   launch selection and run binding.**
5. Route Console conversations, sessions, runs, structured events, approvals,
   cancellation, and stopping through supported remote APIs. Add clarification
   handling only when Hermes advertises a typed request/response capability.
   **Milestone 2C implements one plain default-profile run, bounded events and
   status, cancellation, and safe stopping for approval requests. The 2D audit
   found that Hermes' response mutation has no exact request binding or safe
   structured preview, so approval response remains an upstream blocker.
   Milestone 2E adds bounded,
   read-only remote session list and replay with private connection-bound
   aliases. Milestone 2H searches user/assistant text across that same complete
   visible 12-session window, returns at most 20 safe snippets, and labels when
   the session limit was reached or compacted/additional matches are excluded;
   remote continuation
   remains blocked until Hermes advertises an exact stoppable continuation
   capability.**
6. Send only bounded Context Pack text and supported inline images; keep local
   paths private and degrade unsupported file/artifact transfers clearly.
   **Milestone 2F sends one exact, bounded, private-snapshot Context Pack as
   path-free text through the stoppable Runs API. Direct files, artifacts, and
   images fail clearly before submission. Inline images remain blocked because
   current Hermes advertises them for chat/responses, not for the Runs
   submission/status/stop lifecycle used by Agent Console.**
7. Show remote skills and toolsets only through supported, advertised,
   API-key-authenticated read-only endpoints. **Milestone 2G adds a bounded,
   connection-bound Settings inventory. It exposes only validated identifiers,
   enabled state, and counts while omitting descriptions, categories, labels,
   skill contents, paths, tool names, configured-provider details, and raw or
   partial upstream results.**
8. Add complete read-only profile discovery through a supported,
   API-key-authenticated upstream capability.
9. Add Kanban delegation and follow-up only after Hermes exposes the supported
   authenticated, revision-aware capability required by
   [REMOTE_HERMES.md](REMOTE_HERMES.md).
10. Test endpoint changes, authentication failure, certificate failure,
   capability loss, timeouts, interrupted streams, stale confirmations,
   partial failures, local fallback, upgrade, and rollback.

Exit criteria:

- local mode retains its established behavior and safety contract;
- remote credentials remain outside the install, browser, logs, diagnostics,
  tracked files, and unrestricted backups;
- every mandatory remote capability passes against an approved Hermes version
  over verified HTTPS;
- unsupported degradable features are visible but non-actionable;
- endpoint/profile changes cannot reuse bound sessions, runs, previews, or
  confirmations; and
- remote Kanban mutations preserve exact preview, confirmation, locking,
  idempotency where available, and operation-specific read-back verification.

## Milestone 3 — Create an installable product, native installers, and unified CLI

Goal: replace repository-specific setup steps with versioned native and `pipx`
installation paths plus one predictable command surface.

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
7. Select the exact native installer formats and tooling, then build a signed
   and notarized native installer for macOS and a signed native installer for
   Windows. Each installer must bundle or manage its required runtime, preserve
   the loopback-only boundary, and support clean removal without deleting
   operator data.
8. Keep signing credentials out of source, ordinary CI jobs, artifacts, logs,
   diagnostics, and browser-visible state.
9. Update the README from source-checkout instructions to operator-first native
   and `pipx` install paths, with source setup retained for contributors.

Exit criteria:

- clean macOS and Windows machines can install Mentat through their native
  installer, and `pipx` works as the supported advanced/fallback and Linux
  preview path;
- no command depends on the current working directory;
- native installs launch the local Mentat service and browser without changing
  the loopback-only network boundary;
- `mentat doctor` explains missing optional integrations without exposing
  credentials or private paths;
- version output is consistent everywhere;
- install, start, health, stop, upgrade, and uninstall-preservation smoke tests
  pass from an isolated environment.

Packaging references:

- [Writing `pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [Creating and packaging command-line tools](https://packaging.python.org/en/latest/guides/creating-command-line-tools/)

## Milestone 4 — Make CI the release gate

Goal: turn the existing local verification into an automatic, repeatable
compatibility signal.

Work in order:

1. Add a GitHub Actions workflow for pull requests and `main`.
2. Run unit and contract tests on macOS, Windows, and Ubuntu across the approved
   Python versions.
3. Run Python compilation and JavaScript syntax checks.
4. Build the package and verify wheel/sdist contents.
5. Build native installer test artifacts on macOS and Windows and validate
   their contents without exposing signing credentials to pull-request jobs.
6. Produce a signed and notarized native installer for macOS and a signed
   native installer for Windows only in a protected, trusted release context.
7. Install the built native installer and `pipx` artifacts in clean
   environments and exercise setup, lifecycle, and health checks.
8. Run browser smoke coverage on at least one supported platform.
9. Add dependency and secret scanning with actionable failure output.
10. Require the stable checks before merging and before creating a release tag.

Exit criteria:

- the required matrix is green from a clean checkout;
- package, native installer, signing/notarization, and lifecycle failures block
  release candidates;
- CI logs do not disclose environment secrets or private operator data;
- the exact release artifact has passed installation smoke tests.

CI reference: [Building and testing Python with GitHub Actions](https://docs.github.com/en/actions/tutorials/build-and-test-code/python)

## Milestone 5 — Establish public trust and support

Goal: make it clear how Mentat handles data, security reports, contributions,
and beta support.

Work in order:

1. Maintain the approved MIT `LICENSE` and surface it in release artifacts.
2. Add `SECURITY.md` with supported versions, private reporting instructions,
   response expectations, the loopback Mentat boundary, and the outbound remote
   Hermes trust boundary.
3. Add `PRIVACY.md` describing local storage, Google Calendar's read-only
   behavior, Obsidian access, remote Hermes connection metadata, credential
   ownership, logs, backups, and the absence of default telemetry.
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

## Milestone 6 — Rehearse a release candidate

Goal: prove that the release process works before inviting external testers.

Work in order:

1. Create a release checklist and scripted artifact build.
2. Generate a tagged release candidate such as `v0.1.0-beta.1-rc.1`.
3. Produce the signed and notarized native installer for macOS, signed native
   installer for Windows, and supported `pipx` artifact with checksums,
   installation instructions, release notes, known limitations, backup steps,
   and rollback instructions.
4. Test each native installer on a clean tier-one system and test the `pipx`
   path in its supported roles.
5. Test upgrade from a representative legacy checkout and prior package build.
6. Restore a backup into a clean install and compare the expected data.
7. Test uninstall/reinstall while preserving operator data.
8. Practice revoking or replacing a bad release without hiding its history.

Exit criteria:

- another person can install each exact tagged native installer or the
  supported `pipx` artifact using only public docs;
- clean install, upgrade, rollback, backup, restore, and uninstall-preservation
  drills pass on every tier-one platform;
- artifact checksums and release notes are reproducible;
- there are no unresolved P0 or P1 issues.

## Milestone 7 — Run a limited external beta

Goal: learn from real installations while the tester group and support load are
still bounded.

Work in order:

1. Recruit a small cohort that represents the supported platforms and both new
   and experienced Hermes operators.
2. Give testers a short onboarding path and a structured first-run checklist.
3. Track installation success, time to first useful workflow, integration
   degradation, data migration, and recovery outcomes.
4. Exercise both local and remote Hermes installations and triage reports by
   the Milestone 0 severity policy.
5. Ship small release candidates through the same gated process.
6. Keep a visible known-issues list and close the loop with testers.

Exit criteria:

- at least 10 external testers have used Mentat for roughly two weeks;
- supported-platform installation succeeds without maintainer intervention for
  the large majority of testers;
- backup and recovery have been exercised outside the maintainer environment;
- the mandatory remote capability set has been exercised outside the
  maintainer environment;
- no unresolved P0 or P1 issue remains;
- repeated confusion has been fixed in product or onboarding documentation.

## Milestone 8 — Publish the beta

Goal: release a stable-enough beta to the public with a controlled support and
update path.

Work in order:

1. Freeze the release candidate except for release-blocking fixes.
2. Run the full CI, clean-install, upgrade, backup, restore, and rollback gates.
3. Tag `v0.1.0-beta.1` and publish the tested signed and notarized native
   installer for macOS, signed native installer for Windows, supported `pipx`
   artifact, and checksums.
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
  `pipx` channel.
- [ ] A signed and notarized native installer for macOS and a signed native
  installer for Windows pass clean-install, upgrade, rollback, and uninstall-
  preservation checks.
- [ ] Required CI is green on the supported platform/Python matrix.
- [ ] One remote Hermes endpoint can provide every mandatory capability over
  verified HTTPS without exposing its API credential.
- [ ] Remote Kanban and read-only profile discovery use supported,
  capability-advertised authentication surfaces.
- [ ] Missing Hermes, Google Calendar, or Obsidian degrades safely and clearly.
- [ ] Security, privacy, contributing, support, and known-limitations documents
  are public.
- [ ] Release artifacts, checksums, notes, and rollback instructions are
  reproducible.
- [ ] The limited external beta meets its cohort and stability exit criteria.
- [ ] There are no unresolved P0 or P1 issues.

## Work intentionally deferred until after beta

- non-loopback or hosted Mentat access, browser-to-Hermes access, and a
  Mentat-operated relay;
- authentication, multi-user accounts, or multi-tenancy;
- automatic updates;
- telemetry or analytics by default;
- Hermes cron write controls without upstream atomic capabilities;
- general Hermes configuration, soul, skill-content, credential, or MCP
  editors;
- large new product surfaces that do not close a beta acceptance gap.

## Current next actions

1. Continue Milestone 2 after bounded Context Pack text and remote
   skill/toolset visibility by keeping inline images unavailable until Hermes
   advertises an exact image-input capability for the stoppable Runs lifecycle;
   do not substitute chat/responses or enable general file transfer.
2. Keep remote session continuation unavailable until Hermes advertises an
   exact stoppable continuation capability, and keep approval response
   unavailable until Hermes advertises an exact request binding plus a
   structured preview that is safe to display.
3. With read-only skills and toolsets now visible, continue tracking the
   remaining mandatory upstream Hermes capabilities for
   authenticated Kanban, complete read-only profile discovery, and
   clarification handling without implementing an unsafe substitute.
4. After the data-root and remote-parity milestones, design the native
   installer formats, runtime strategy, signing boundary, and `pipx` fallback
   in Milestone 3 rather than choosing tooling prematurely.
5. Do not begin a dependent slice while an earlier data-safety or release
   blocker remains open.
