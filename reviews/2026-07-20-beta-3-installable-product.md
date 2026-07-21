# Milestone 3 — Installable product verification log

Status: in progress

## Outcome

Replace repository-only startup with a versioned `mentat` command, tested
Python packages, and native installers while preserving Mentat's local-only
network and private-data boundaries.

## Approved scope

The user approved all milestone slices in advance. Work remains split into
reviewable slices so packaging, lifecycle behavior, and installer security can
be verified independently.

1. Package metadata, single version source, package assets, and CLI foundation.
2. Setup, lifecycle, doctor, backup, restore, and compatibility wrappers.
3. Wheel/sdist content checks and clean isolated `pipx`-style install smoke.
4. macOS and Windows native installer formats, runtime strategy, and unsigned
   test artifacts.
5. Protected signing/notarization path, clean-machine smoke evidence, and
   operator-first README updates.

The final milestone commit, push, and merge happen only after the complete test
strategy and two independent adversarial reviews pass.

## Safety boundaries

- Keep every server bind loopback-only.
- Do not expose credentials or private paths through `doctor`, version, health,
  logs, package metadata, or installer output.
- Keep operator data outside the installed application and preserve it during
  upgrades and application-only uninstall.
- Keep signing credentials out of source, pull-request jobs, artifacts, logs,
  diagnostics, and browser state.
- Preserve source-checkout scripts as beta compatibility wrappers.

## Test strategy

- Focused unit tests for version, CLI dispatch, diagnostics, and asset lookup.
- Existing full Python suite and JavaScript syntax checks after each risky
  lifecycle or server change.
- Build wheel and sdist, inspect their contents, then install the wheel into a
  fresh isolated environment and exercise version/setup/start/health/stop.
- Build unsigned native test artifacts on macOS and Windows and inspect their
  contents without release credentials.
- Exercise signed release artifacts only in a protected trusted context.
- Before publication, run two independent adversarial read-only reviews, fix
  all P0/P1 findings, and repeat affected verification.

## Evidence

### Slice 1 — package and CLI foundation

- Added PEP 517 metadata with Python 3.11–3.13 support, pinned runtime and
  build requirements, a console entry point, explicit root modules, and
  allowlisted public assets.
- Added one product version source (`0.1.0b1` / `v0.1.0-beta.1`) used by the
  CLI, HTTP server identity, health payload, startup log, and browser health
  line.
- Added the initial `mentat setup/start/stop/status/doctor/backup/restore`
  command surface. Commands are independent of the current working directory;
  `doctor` returns bounded, path-free integration status.
- Built `mentat_local-0.1.0b1.tar.gz` and
  `mentat_local-0.1.0b1-py3-none-any.whl` with the pinned isolated backend.
- Installed the wheel plus pinned dependencies into a fresh Python 3.13
  environment outside the checkout. `--version`, `doctor`, `setup`, `start`,
  `/api/health`, and `stop` passed on loopback port 8895.
- Inspected every sdist and wheel filename. Both contain only allowlisted seed
  JSON and static assets; no `data/private`, `data/runtime`, test, cache, or
  local configuration content is present.
- Rebuilt with the final non-yanked backend pins, installed the final wheel in
  a second fresh environment, and re-ran version, doctor, and setup outside the
  checkout successfully. The sdist contains the native build driver and still
  excludes private/runtime/test content.
- Focused packaging, lifecycle, health, and security tests: 49 passed.
- Full regression suite after the final review fixes: 720 passed, 4
  native-Windows tests skipped on macOS.

### Slice 2 — lifecycle and native launch

- Installed-wheel `backup` created a validated version-2 backup and `restore`
  safely returned an exact no-change preview.
- Native launch waits for the loopback overview endpoint before opening the
  browser and binds the child server to the native launcher lifetime.
- Frozen executables use an explicit internal server mode instead of trying to
  relaunch the bundled executable with Python's `-m` flag.
- Frozen macOS builds resolve seed/static assets from the real
  `Contents/Resources` directory. Mentat continues to reject the Frameworks
  symlink rather than weakening the seed-root safety check.

### Slice 4 — native artifact foundation

- Selected PyInstaller 6.21.0 folder bundles, a macOS `.pkg`, and a Windows
  Inno Setup `.exe`. The macOS/Windows definitions consume the shared Mentat
  version source through the build driver.
- Added a pinned native build manifest and a cross-platform unsigned test
  artifact driver. The native environment includes the pinned runtime
  dependencies as well as build tools.
- Built an ad-hoc-signed local `Mentat.app` (129 MB) and an unsigned macOS
  `.pkg` (31 MB) with Python 3.13 bundled. These are test artifacts, not beta
  release artifacts.
- Inspected the app and installer payload: all nine public seeds are present;
  private/runtime/local-config data is absent.
- Executed the final app outside the checkout on loopback port 8895, initialized
  a fresh external data root, opened only after `/api/overview` was ready,
  returned the exact version through `/api/health`, and shut down with its
  launcher. The normal development server was restored afterward.
- Rebuilt after lifecycle hardening and exercised explicit native
  `start --port 8896` and `stop --port 8896`. The configured-port-only cleanup
  left unrelated ports alone, required runtime-state-plus-probe ownership, and
  returned no command lines or private state paths.
- Corrected the macOS component install root to `/Applications`, changed the
  Windows installer to a per-user install, and made custom Windows build output
  paths authoritative.
- Pinned every third-party GitHub Action to an exact verified release commit,
  selected a fixed Windows runner, removed incomplete pull-request path
  filters, and added native install/start/health/stop/uninstall-preservation
  smoke steps for both tier-one platforms.
- Added a manual `beta-release` environment workflow that keeps credentials
  out of pull requests, signs the app and package/installer, submits macOS for
  notarization, verifies both platforms, uploads only signed outputs, and
  removes imported identities in unconditional cleanup steps.
- Added one shared, fully resolved native dependency lock with package hashes,
  pinned Python 3.13.14, an Inno Setup 6.7.1 assertion, and exact PyInstaller
  static assets. A fresh environment installed the lock with
  `--require-hashes` and reported PyInstaller 6.21.0.
- Added a Windows console-subsystem `mentat.exe` beside the double-click GUI
  launcher so explicit CLI output and restore confirmation tokens remain
  visible.
- Both native jobs now install a deterministic lower-version fixture with a
  deliberately stale application file, create external operator state, install
  the current package over it, verify the stale file is gone, run health and
  lifecycle checks, uninstall the application, and verify operator state
  remains. The macOS job also forgets and verifies removal of its package
  receipt. A real prior-beta-to-current upgrade remains a future release gate
  because no earlier Mentat beta artifact exists yet.
- Rebuilt the final macOS app from the hash-locked environment. The bundle and
  package contain exactly five public assets and nine seed JSON files. Its
  path-free health payload and explicit start/stop lifecycle passed on
  loopback port 8897.
- PR #51's first Windows 2025 run exposed a platform-specific lock omission:
  `build==1.3.0` requires Colorama only on Windows, so the macOS-generated lock
  had not included it. Added explicit `colorama==0.4.6` input with both PyPI
  artifact hashes and a contract assertion; hash-locked dry-run resolution and
  all 17 packaging tests pass locally. Remote Windows re-verification is
  pending the follow-up commit.
- The next Windows run passed the repaired lock, then showed that Inno Setup's
  executable resource reports `0.0.0.0` despite the fixed runner manifest
  supplying 6.7.1. Replaced the unreliable executable-resource check in both
  native workflows with an exact local Chocolatey package assertion while
  retaining the executable existence check.

## Review findings

- Fixed during slice 1: the first sdist manifest recursively included
  gitignored private/runtime JSON and tests. Replaced recursive data inclusion
  with an exact public-seed allowlist, pruned private/runtime/tests, rebuilt,
  and re-inspected both artifacts.
- Fixed during slice 1: replaced yanked `wheel==0.46.1` with current non-yanked
  `wheel==0.47.0` in both isolated build manifests.
- Fixed during native testing: the first native builder omitted runtime
  dependencies; the next build hit the fail-closed macOS Frameworks seed
  symlink; the next frozen launch recursively relaunched itself. The final
  build includes runtime dependencies, uses real Resources, and starts one
  internal bundled server.
- First adversarial review found cross-port/process ownership, path-bearing
  diagnostics, broad asset inclusion, mutable CI references, elevated Windows
  install defaults, incorrect macOS install location, incomplete CI triggers,
  and shape-only installer tests. These implementation findings are fixed and
  covered by focused regressions.
- Native retesting found that the executable ignored explicit CLI arguments;
  it now preserves double-click launch while honoring `start`, `stop`,
  `status`, and their runtime options.
- Native health inspection found legacy browser-visible Hermes paths. Local
  health payloads now expose status and bounded metadata without filesystem
  paths, raw runtime state, or underlying exception text.
- Local `/Applications` installation could not run because macOS requires an
  interactive administrator password. The package payload root was inspected
  locally, and the exact privileged install lifecycle is encoded in the clean
  macOS CI job.
- Both independent adversarial re-reviews are clean: neither reviewer found a
  remaining P0 or P1 implementation defect.
- Remaining gates are external release evidence: protected `main`, a
  non-self-approved `beta-release` environment, real signing/notarization
  credentials, and successful native and protected-release workflow runs on
  GitHub's fixed runners. This milestone remains in progress until that
  evidence is recorded.

## Publication

- The review-clean implementation slice is ready for a pull request so the
  remote unsigned native workflow can produce runner evidence.
- Do not publish beta installers as trusted release artifacts until the
  protected signed workflow succeeds with the required repository controls.
