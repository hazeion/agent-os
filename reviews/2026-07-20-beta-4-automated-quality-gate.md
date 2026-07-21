# Milestone 4 — Automated quality gate verification log

Status: implementation and internal review complete; hosted evidence pending

## Outcome

Turn Mentat's local verification into stable GitHub release gates across the
supported OS/Python matrix, package and native install paths, browser behavior,
and dependency/secret safety checks.

## Approved scope

The user approved all Road to Beta slices in advance.

1. Pin CI actions and supported runner/toolchain inputs.
2. Build and inspect wheel/sdist artifacts, then exercise an isolated
   `pipx`-style install and lifecycle.
3. Run the project-owned browser smoke on a supported clean runner.
4. Add dependency and secret scanning with bounded actionable output.
5. Require stable checks for merge and release-tag creation.

Protected signed/notarized artifact execution remains the Milestone 3 external
credential/environment gate; M4 must make that workflow release-blocking but
must not weaken its protected context or introduce credentials into PR jobs.

## Safety boundaries

- CI and the browser remain loopback-only.
- Pull-request jobs receive no signing credentials or private operator data.
- Actions and release tools use immutable or exact inputs.
- Package/native artifacts retain exact public asset allowlists.
- Scanner output must identify an actionable dependency/file without printing
  environment secrets or unrestricted local content.
- Required-check configuration must bind stable job names and must not permit a
  release tag to bypass the trusted signed-artifact gate.

## Test strategy

- Parse every workflow and add source-contract tests for immutable references,
  triggers, permissions, secret isolation, and expected gates.
- Build wheel/sdist locally and on GitHub, inspect exact contents, and install
  into a fresh isolated environment for setup/start/health/stop checks.
- Run `scripts/browser_smoke.mjs` against an ephemeral data root and loopback
  server on a supported fixed runner.
- Exercise dependency and secret scanners against the repository and add small
  deterministic positive/negative scanner contract fixtures where practical.
- Run the full Python suite plus JavaScript syntax checks.
- Before publication, give the same final diff and evidence to two independent
  adversarial read-only reviewers, fix all P0/P1 findings, and re-review.

## Evidence

- M3 PR #51 established green fixed-runner native evidence on macOS Intel and
  Windows 2025. Final M3 head CI #119 and Native artifact smoke #8 both passed.
- M4 branch created from merge commit `e2e7361`.
- Replaced mutable CI action tags with immutable official commits and changed
  the broad matrix from floating runner aliases to `ubuntu-24.04`,
  `macos-15-intel`, and `windows-2025`. Added focused contract coverage for
  runner/action immutability, read-only permissions, safe triggers, and absence
  of PR secrets.
- Added exact wheel/sdist inventory and wheel `RECORD` integrity verification.
  A clean local build passed, followed by a fresh wheel install and successful
  setup, doctor, start, health, stop, and data-preservation checks.
- Added the project browser smoke to a fixed Ubuntu/Chrome gate with an
  ephemeral data root. The local 15-check smoke passed; its bounded readiness
  wait is now 30 seconds so optional local Hermes discovery cannot create a
  false failure on slower clean runners.
- Added hash-locked `pip-audit` and `detect-secrets` tooling. The initial audit
  found `PYSEC-2026-3447` in `setuptools==80.9.0`; upgraded the exact build pin
  and metadata to `83.0.0`, regenerated hashes, rebuilt artifacts, and verified
  both runtime and native locks report no known vulnerabilities.
- Reviewed every initial secret-scan candidate as a deliberate redaction or
  credential-rejection fixture, code marker, or public skill content hash. The
  baseline stores fingerprints only. New findings fail with file, line, and
  detector type while the candidate value remains suppressed.
- Added stable aggregation contexts: `CI required`,
  `Native artifacts required`, and `Quality gates required`.
- Final full local suite: 729 tests passed with 4 expected platform-specific skips.
  Two old CI contract assertions initially failed because they required mutable
  action tags and floating runner aliases; they were updated to enforce the new
  immutable inputs, then the complete suite passed.
- The first adversarial pass found no P0s and three P1 release-gate gaps: PEP
  517 recreated an unhashed build environment, the isolated install was venv
  based rather than actual `pipx`, and tag creation was not bound to signed
  artifacts. Fixed these with `build --no-isolation`, hash-locked `pipx 1.8.0`
  and a real pipx lifecycle, plus a protected-main release orchestrator that
  verifies all three stable checks for the exact SHA, requires both signed
  installer jobs, fails if either is skipped, and only then creates the exact
  version tag. Unsigned native smoke now also rebuilds on `main`.
- Follow-up hardening rejects archive special members and unapproved packaging
  inventory expansion, cleans browser scratch state, preserves duplicate secret
  findings, and establishes project-owner review for gate/baseline changes.

## Review findings

- Initial independent release review: 0 P0, 3 P1, 3 P2, 1 P3.
- Initial independent security review: 0 P0, 1 overlapping P1, 3 P2, 1 P3.
- All P1 findings fixed; selected P2/P3 archive, duplicate-scan, owner-review,
  native-main, and browser-runtime findings were also fixed.
- Final independent release re-review: no internal P0/P1 findings remain.
- Final independent security re-review: no internal P0/P1 findings remain.
  GitHub tag-ruleset and protected `beta-release` environment configuration are
  explicit external configuration/evidence gates because the connected GitHub
  plugin does not expose repository ruleset or environment-setting mutations.
- Final browser smoke passed all 15 checks and removed its process-owned runtime
  child before the temporary loopback Mentat server was stopped.

## Publication

- Pending milestone completion.
