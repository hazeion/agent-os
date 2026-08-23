# Feature Slice Review: Production cutover

Status: In progress

Slice: `2d-production-cutover`

Date: `2026-08-22`

## Slice contract

### Goal

Make the Node dashboard the supported installed launch path while retaining a
tested, explicit legacy rollback until cutover acceptance is complete.

### Scope

- Package the prebuilt Next standalone server and its fixed private Python
  bridge with the installed product; startup must not download or build web
  dependencies.
- Make the supported launcher start the supervised Node gateway by default,
  validate its loopback readiness, and stop both children together.
- Provide an explicit local legacy rollback selector. It must be bounded,
  observable, and leave data authority unchanged.
- Update installer, lifecycle, release, and user documentation for offline
  launch, recovery, rollback, and retirement criteria.

### Out of scope

- New Agent runtime, provider credentials, Vercel adapter, remote hosting,
  broad Node APIs, legacy dashboard deletion, or direct Hermes-file writes.

### Acceptance criteria

| ID | Criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Installed product contains a prebuilt Node web runtime and fixed bridge assets. | Package inspection | Pending |
| AC-2 | Default launcher starts Node, bridge, and data bootstrap without network access. | Isolated install/lifecycle tests | Pending |
| AC-3 | Stop, unexpected-child recovery, and port collision fail closed. | Lifecycle tests | Pending |
| AC-4 | Explicit legacy rollback launches only the existing Python UI and never changes data authority. | Rollback tests | Pending |
| AC-5 | Installer and release documentation match the supported path. | Docs and package tests | Pending |
| AC-6 | Clean production browser and six-run Lighthouse gates remain perfect. | CI | Pending |

### Standing approval

The active pivot goal authorizes this scope, review, publication, merge, and
continuation. The legacy interface remains available only as explicit rollback
until this slice is accepted; it is not deleted here.

## Test strategy

- Unit-test launch selection, exact commands, Node version gate, no-network
  startup, and child cleanup.
- Inspect native package contents on macOS and Windows and exercise offline
  launch where supported.
- Run production browser smoke, lifecycle sibling-death checks, full clean CI,
  and the six-run Lighthouse gate.
- Independently review package inclusion, rollback safety, and user-facing
  launcher behavior before publication.

## Implementation notes

- `mentat start` and the source launch scripts now start the supervised Node
  gateway by default. `--legacy-ui` is the bounded rollback path.
- The supervisor reserves the selected data root, starts an authenticated
  loopback Python bridge, then starts Node. It records the Node listener only
  after gateway readiness and always withdraws Node before the bridge.
- Native bundles collect the prebuilt standalone output. Node 24.19 remains a
  documented host prerequisite; the product never downloads or builds web
  files when it launches.

## Verification

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_web_runtime tests.test_packaging_cli tests.test_local_server_lifecycle tests.test_mentat_web_preview tests.test_node_runtime_foundation -v` | Pass | 60 tests passed. |
| `npm --prefix web run check` | Pass | Lint, type check, and 38 Node tests passed. |
| Host loopback launch | Pass | The private bridge and Next server both reached readiness on port 8899. |
| `npm --prefix web run build` | Environment-limited | Turbopack cannot bind its internal worker port in this environment. The unchanged normal-build Lighthouse gate passed in clean CI for Slice 2C-D. |
| `git diff --check` | Pass | No whitespace errors. |

## Review status

### Round 1

- Correctness/safety found that Node inherited Python runtime settings and
  parent secrets, and that a recorded Node gateway could become an unowned
  port blocker after bridge failure. Both were accepted and fixed.
- Compatibility/product found an IPv6 Host-header formatting failure and stale
  README quick-start wording. Both were accepted and fixed.

The Node environment is now allowlisted to OS process essentials plus the
private bridge capability. Lifecycle records the exact standalone server path
and can stop that recorded gateway when bridge health is unavailable. IPv6 and
orphan-gateway tests cover the corrections.

### Post-fix verification

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_web_runtime tests.test_local_server_lifecycle tests.test_packaging_cli -v` | Pass | 55 tests passed. |
| `npm --prefix web run check` | Pass | Lint, type check, and 38 Node tests passed. |
| `git diff --check` | Pass | No whitespace errors. |

Round 2 re-review pending.

### Round 2 follow-up

- Correctness/safety found that the recorded Node gateway ownership check
  rejected Windows drive-absolute paths. The validator now accepts both POSIX
  and Windows absolute paths; the Windows-path lifecycle regression test
  passes.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_local_server_lifecycle tests.test_web_runtime -v` | Pass | 31 tests passed. |
| `git diff --check` | Pass | No whitespace errors. |

### Final review

- Compatibility/product: no findings.
- Correctness/safety: no findings after the bridge launcher watch adopted the
  existing Windows-safe liveness check.

The host-bound bridge, launcher, and lifecycle suite passed 58 checks after
the supervisor-watch fix. The focused bridge-watch regression suite passed 8
checks after the Windows correction. The full local suite remains unsuitable as
final evidence because user-owned `data/projects.json` changes make unrelated
legacy dashboard expectations fail; clean CI is required for the full suite,
native installer smoke, browser smoke, and six-run Lighthouse gate.

## CI correction round

The initial PR found three cutover gaps:

- the Node environment regression test used a provider-secret identifier that
  the secret scanner correctly required to be reviewed;
- a legacy documentation assertion still described the old Python dashboard;
- `pipx` installed only Python assets, so it could not start the default Node
  dashboard.

The correction stages the built standalone runtime as regular files, packages
it into the wheel under `share/mentat/web`, and makes the launcher select that
installed payload when a source build is absent. The package and signed-release
workflows build and stage the runtime before producing Python artifacts. The
release instructions now list Node 24.19+ for `pipx` as well.

Native smoke failures currently lack the child launcher output. The native
workflow now emits the captured startup log before failing, so a remaining
platform issue will be diagnosable on the next run.

| Check | Result | Notes |
| --- | --- | --- |
| Webpack production build + staging | Pass | Local environment blocks Turbopack's internal worker port; the supported Webpack build produced the standalone payload. |
| Isolated sdist and wheel build | Pass | The exact verifier accepted both artifacts, including the prebuilt Node runtime. |
| `python3 -m unittest tests.test_limited_beta_readiness tests.test_release_rehearsal tests.test_web_runtime tests.test_next_phase_readiness tests.test_ci_quality_gate tests.test_packaging_cli -v` | Pass | 66 checks passed. |
| `git diff --check` | Pass | No whitespace errors. |

The local secret-scanner executable is not installed. The CI secret scan remains
required and is expected to cover the corrected test value.

### Correction review

The first correction review found that a platform-native file inserted after
staging could still enter the universal wheel. The accepted fix centralizes
native filename and binary-signature validation, applies it before and after
runtime staging, checks it again at package construction, and independently
inspects every runtime member in the finished wheel. A second review noted that
copying could dereference an unsafe source symlink. Staging now validates the
source standalone tree before copying it.

| Check | Result | Notes |
| --- | --- | --- |
| Focused Python contract suite | Pass | 71 checks passed after the portable-runtime corrections. |
| `npm --prefix web run check` | Pass | Lint, type check, and 38 Node tests passed. |
| Isolated sdist and wheel build | Pass | The verifier accepted the complete staged runtime and rejects native wheel members. |
| Two independent final reviews | Pass | No blockers or non-blockers after source validation was moved before the copy. |

After the correction commit reached GitHub, the secret scanner flagged the
test-only key `PROVIDER_SECRET`; no credential or runtime behavior was
involved. The test now uses the neutral `UNRELATED_PARENT_VALUE` marker. The
targeted test suite passes locally; GitHub remains the authoritative scanner
because the local `detect-secrets` module is unavailable.

The replacement CI run passed the browser and secret-scan gates, then the
installed-package smoke stopped before Chromium launched because its private
runtime directory did not have the exact name the smoke script requires. The
workflow now uses `web-foundation-smoke-runtime`, and the CI contract test
asserts that exact value.

### CI correction round 2

The next CI run exposed two remaining startup paths:

- the installed wheel started the bridge before completing the one-time SQLite
  Task cutover, so its first Tasks request was unavailable;
- the Apple Silicon native smoke received only a generic gateway timeout even
  when Node remained alive and the bridge-proxy health route returned `503`.

The supervisor now establishes Task authority before it starts the bridge.
It also waits for a fixed Node-only readiness route before it waits for the
Node-to-bridge route. A persistent proxy `503` returns the bounded
`gateway_bridge_unavailable` code rather than a generic timeout. No token,
route response body, or child environment is logged.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_web_runtime tests.test_packaging_cli tests.test_ci_quality_gate -v` | Pass | 47 checks passed. |
| `npm --prefix web run check` | Pass | Lint, type check, and 38 Node tests passed. |
| `git diff --check` | Pass | No whitespace errors. |
| Native local build | Environment-limited | Turbopack cannot bind its internal worker port in this execution environment; CI remains the native-bundle evidence. |

Two independent read-only investigations reproduced an installed-style,
read-only standalone payload with a live bridge and found no packaging-layout
failure. Both recommended separating Node-listener and Node-to-bridge
readiness instead of extending timeouts blindly. Their accepted correction is
within this slice's launch and lifecycle contract. Re-review is pending after
the complete correction diff is ready.

### CI correction round 2 review

Both reviewers found two non-blocking gaps: a prior transient `503` could be
misclassified after a later transport failure, and the tests did not prove the
supervisor ordering. The accepted in-scope follow-up now reports a bridge
failure only when the final observed response is `503`, proves authority before
bridge spawn and all three readiness stages in order, and tests the fixed Node
health payload and headers.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_web_runtime tests.test_packaging_cli tests.test_ci_quality_gate -v` | Pass | 49 checks passed. |
| `npm --prefix web run check` | Pass | Lint, type check, and 39 Node tests passed. |
| `python3 -m unittest discover -s tests` | Environment/user-data limited | 1,355 tests ran: one pre-existing fixture expectation conflicts with the user-owned `data/projects.json` additions; 32 loopback-server tests cannot bind sockets in this sandbox; five tests skipped. No Slice 2D failure was reported. |
| `git diff --check` | Pass | No whitespace errors. |

The final adversarial re-review is pending this amended correction diff.

### Final correction review

Both independent reviewers reported no findings after the transient-response,
startup-order, and Node-route tests were added. The correction is ready for
the existing PR. GitHub CI remains the required authority for the isolated
wheel lifecycle, native installer smoke, browser smoke, and Lighthouse gates.

### CI correction round 3

The pushed correction exposed three new CI facts:

- the installed wheel had completed Task authority but not Run authority, so
  the Runs workspace was unavailable;
- the Lighthouse score gate reached a Chrome `NO_NAVSTART` trace-recording
  error, before any score was produced;
- macOS native Node stayed alive but did not answer the Node-only readiness
  route. The gateway used PyInstaller's Frameworks resource link, while the
  actual Node runtime is packaged under `Contents/Resources/web`.

The supervisor now establishes Run authority before bridge startup, retries a
single `NO_NAVSTART` trace error without accepting an audit result, and uses
the real macOS Resources root for frozen assets. Native CI also starts the
installed `Resources/web/server.js` and verifies its fixed gateway route
before it exercises the app. The normal web build remains unchanged.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_web_runtime tests.test_packaging_cli tests.test_node_runtime_foundation tests.test_ci_quality_gate -v` | Pass | 54 checks passed. |
| `npm --prefix web run check` | Pass | Lint, type check, and 39 Node tests passed. |
| `node --check web/scripts/lighthouse-gate.mjs` | Pass | Retry script parses. |
| `git diff --check` | Pass | No whitespace errors. |

Two independent macOS investigations disagreed on the primary cause. The
Resources-root correction was selected because `runtime_config.py` already
uses the canonical macOS app Resources directory, whereas `web_runtime.py`
uniquely used `_MEIPASS`; the new frozen-path test covers that exact boundary.
The Turbopack packaging hypothesis was not adopted without a reproducing
failure after the canonical-path correction. Final re-review is pending.

### Final correction round 3 review

The compatibility reviewer found one blocking workflow issue: a live but
non-responsive packaged Node process could leave an unbounded `curl` probe
stuck. Both probes now use `--max-time 1`, and the workflow contract test
requires that bound. The originating reviewer and the independent
correctness/safety reviewer both reported no findings after the fix.

### CI correction round 4

Both macOS native installers now reach the packaged Node-only health route,
but the frozen app's Node-to-private-bridge route remains unavailable. The
same Node 24 process can reach a source Python bridge through the fixed token
contract, and Windows native smoke passes. This isolates the remaining risk to
the macOS frozen standalone build rather than the bridge protocol or data
authority.

Native packaging temporarily used an explicit Webpack standalone build to test
whether Turbopack caused the macOS bridge failure. It reproduced the same
failure, so native packaging has returned to the normal Turbopack build. This
test did not change runtime providers, browser behavior, or the Node gateway
contract.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_packaging_cli tests.test_web_runtime tests.test_node_runtime_foundation tests.test_ci_quality_gate -v` | Pass | 54 focused checks passed. |
| `npm --prefix web run check` | Pass | Lint, type check, and 39 Node tests passed. |
| `node scripts/run-next.mjs build --webpack && node scripts/prepare-standalone.mjs` | Pass | Webpack produced and staged the standalone runtime for the diagnostic comparison. |
| `git diff --check` | Pass | No whitespace errors. |

The complete local native bundle could not be retained for a smoke run because
this environment's normal native build path lacks PyInstaller and its isolated
temporary build was interrupted by the execution sandbox. GitHub's signed-free
macOS installer smoke remains the required cross-platform evidence.

### Final correction round 4 review

Both independent reviewers reported no findings. They confirmed that the
portable Webpack command is fixed, is supported by the installed Next CLI, is
covered by the packaging contract test, and stays isolated to native packaging.
Normal Turbopack development and dashboard builds are unchanged.

### CI correction round 5

The portable Webpack package reproduced the same macOS bridge failure, so the
build engine is not the cause and native packaging has returned to Turbopack.
The app's private bridge is currently launched through the windowed macOS
executable. Native packaging now supplies a regular console companion used
only for the private bridge process. The visible Mentat.app launcher remains
unchanged; the bridge's fixed arguments, loopback binding, token boundary,
lifecycle, and data authority remain unchanged.

The first final review found that resolving the macOS launcher could select a
Frameworks symlink instead of its lexical `Contents/MacOS` sibling. The
companion lookup now stays beside the un-resolved launcher path and fails
closed if that regular companion is missing. The test suite models the bundle
symlink layout and the missing-companion failure.

The installed artifact confirmed that the companion is present, but the frozen
macOS process can report its executable from `Frameworks`. The companion path
now derives from the validated app Resources root, whose parent is always the
app `Contents` directory, rather than from the runtime executable location.

### Final correction round 6 review

Both independent reviewers reported no findings. They confirmed that the
Resources-root derivation works whether the frozen process reports from
`MacOS` or `Frameworks`, keeps the companion regular and macOS-only, preserves
the loopback token boundary, and does not affect Windows.

### CI correction round 7

The installed gateway still timed out after the companion lookup was corrected.
The supervisor now checks that the already-verified private bridge remains
alive while it waits for the Node bridge route. A stopped bridge returns the
bounded `bridge_process_stopped` code; a live bridge with an unavailable proxy
continues to return the existing bounded proxy failure. This distinguishes the
two failure modes without extending timeouts or exposing process output.

The correctness review found a narrow coverage gap: the supervisor test did
not prove that its final bridge-route readiness call received the bridge
process. The test now asserts that exact wiring and that the earlier readiness
calls do not receive it.

### Final correction round 7 review

Both independent reviewers reported no findings after the supervisor-wiring
assertion was added.

### CI correction round 8

The bridge stayed alive throughout the failed Node readiness wait, so the
remaining issue is Node's fixed bridge request rather than process lifecycle.
The bridge health route now returns only a bounded failure reason
(`bridge_configuration_invalid`, `bridge_unavailable`, or
`bridge_response_invalid`) on its loopback-only `503` response. The macOS
smoke prints that existing health response only when it fails. No path, port,
token, child output, or credential is returned.

| Check | Result | Notes |
| --- | --- | --- |
| Frozen console bridge health | Pass | The temporary macOS companion answered its authenticated loopback health route. |
| Frozen app → bridge → Node health | Pass | The temporary macOS app reached `/api/bridge/health` through the companion. |
| `python3 -m unittest tests.test_packaging_cli tests.test_web_runtime tests.test_node_runtime_foundation tests.test_ci_quality_gate -v` | Pass | 57 focused checks passed. |
| `npm --prefix web run check` | Pass | Lint, type check, and 39 Node tests passed. |
| `git diff --check` | Pass | No whitespace errors. |

### Correction round 5 review

The compatibility reviewer found that resolving a macOS launcher could select
a Frameworks symlink rather than its lexical `MacOS` sibling. The correction
uses the lexical sibling and fails closed when the regular console companion is
missing; dedicated tests cover both cases. The correctness reviewer noted that
the shipped artifact verifier already rejects a symlinked main launcher, so it
classified this as defense-in-depth rather than a release blocker. The stricter
in-scope correction was retained because it is safe and makes the bridge
selection explicit. Both reviewers agreed that the companion remains isolated
to frozen macOS builds and leaves the visible launcher and Windows behavior
unchanged. Final re-review is pending.

### Final correction round 5 review

Both independent reviewers reported no findings in the macOS companion
correction. One reviewer separately flagged user-owned `data/tasks.json`
changes as private, non-slice content; those changes are excluded from this
commit and remain untouched in the working tree.

### CI correction round 9

The macOS artifact confirmed that the private bridge remains live while the
Node gateway never binds to its loopback port. To preserve that evidence
without exposing process state, Node startup output now goes to a fresh,
owner-private runtime log. The capture drains continuously but retains no more
than 8 KiB. Failed starts keep at most three regular, single-link logs owned by
the current user; clean user-requested shutdown closes the capture before it
removes its log. The installer smoke prints no more than a redacted 8 KiB
aggregate tail when it fails.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_web_runtime tests.test_packaging_cli -v` | Pass | 51 focused Python checks passed, including symlink, byte-cap, cleanup-order, and retention coverage. |
| `npm --prefix web run check` | Pass | Lint, type check, and 39 Node tests passed. |
| `git diff --check` | Pass | No whitespace errors. |

### Final correction round 9 review

Two independent reviewers found no remaining blockers. They confirmed the
private-log creation, bounded draining capture, Windows-safe shutdown order,
regular-file retention filter, and aggregate CI output cap. User-owned data
and untracked workspace files remain excluded from the slice.

### CI correction round 10

The packaged Next server passed its fixed gateway health check under the exact
minimal environment used by Mentat. Turbopack and the Node environment are
therefore not the macOS failure. The remaining difference is the windowed
macOS launcher supervising Node. On frozen macOS starts, the visible launcher
now delegates the existing start arguments to its validated regular console
companion using a fixed internal marker. That companion runs the normal CLI
gateway; its already-fixed private-bridge marker still takes precedence, so it
does not recurse. Windows and non-frozen launches keep their existing paths.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_packaging_cli tests.test_web_runtime -v` | Pass | 55 focused Python checks passed, including exact macOS delegation, marker precedence, and fallback coverage. |
| `npm --prefix web run check` | Pass | Lint, type check, and 39 Node tests passed. |
| `git diff --check` | Pass | No whitespace errors. |

### Final correction round 10 review

Two independent reviewers found no remaining blockers. They confirmed the
fixed argument handoff, regular non-symlink companion check, dispatch order,
non-recursive bridge path, and behavioral test coverage.

### CI correction round 11

The latest macOS smoke still timed out after the bridge became ready. Its
intended fixture data root contained no retained startup log. The frozen
macOS resource-root selection was unnecessarily conditional on importing the
optional Python `resource` module. Resource lookup now always uses the regular
`Contents/Resources` directory. If that optional module is unavailable, Node
uses the existing bounded pipe capture rather than a direct file descriptor;
the default closed-descriptor boundary is preserved.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_web_runtime tests.test_packaging_cli -v` | Pass | 58 focused checks passed. |
| `npm --prefix web run check` | Pass | Lint, type check, and 39 Node tests passed. |
| `python3 -m unittest discover -s tests -v` | Environment-limited | 1,375 tests ran; one assertion reads the user-modified `data/projects.json`, and 32 bridge-route tests cannot bind a loopback test port in this sandbox. The affected focused suite passed. |
| `git diff --check` | Pass | No whitespace errors. |

The user previously granted standing approval for implementation and
publication actions. That standing approval is the recorded exception to the
skill's per-publication approval prompt for this narrow CI correction.

### Final correction round 11 review

Two independent reviewers reported no findings. They confirmed that the
resource-root lookup no longer depends on an optional module, the fallback
retains bounded diagnostics and closed descriptors, and the change is limited
to frozen macOS behavior.

### CI diagnostic round 12

The user approved a diagnostic-only pass to identify the exact frozen macOS
startup stage before changing runtime behavior. The supervisor now reports
distinct bounded errors for private-bridge readiness, Node gateway readiness,
and Node-to-bridge readiness. The fixed macOS Node companion prints one
secret-free marker immediately before replacing itself with Node. Native CI
also compares a direct console-supervisor start with the visible launcher.
That comparison runs in a dedicated process session and cleanup targets the
whole process group with bounded TERM/KILL escalation before the normal smoke.

Acceptance evidence:

1. A failed startup identifies one of the three readiness stages.
2. The fixed handoff marker proves whether the companion reached `exec`.
3. The direct-console comparison cannot leave its Node child or listener for
   the following visible-launcher test.
4. No token, path, credential, arbitrary child output, or Hermes state enters
   the public API or fixed error codes.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_web_runtime tests.test_packaging_cli tests.test_ci_quality_gate -v` | Pass | 68 focused checks passed. |
| `npm --prefix web run check` | Pass | Lint, type check, and 39 Node tests passed. |
| `python3 -m py_compile mentat/web_runtime.py packaging/mentat_native.py` | Pass | Both changed Python runtime entry points compile. |
| Extracted macOS smoke block with `bash -n` | Pass | The diagnostic and bounded process-group cleanup are valid Bash. |
| `git diff --check` | Pass | No whitespace errors. |

The user has explicitly approved this step-by-step diagnostic and retains the
standing publication approval recorded above. Full native behavior remains a
GitHub macOS-runner gate; no runtime correction will be selected until this
diagnostic returns evidence.

### Final diagnostic round 12 review

Two independent reviewers reported no findings. They confirmed that all three
stage errors are fixed and secret-free, the marker occurs immediately before
`exec`, the direct comparison owns a separate process group, and bounded
cleanup completes before the visible-launcher smoke.

### CI correction round 13

The stage diagnostics showed that both frozen macOS launch paths stopped at
private-bridge readiness, before Node was launched. The frozen entry point had
already imported `mentat.local_bridge` through the web runtime, then tried to
execute that same module again with `runpy`. Python reported the duplicate
execution warning and the bridge never printed its ready marker. The private
bridge marker now calls the already-loaded bridge `main()` directly with the
fixed remaining arguments. It no longer mutates process-wide `sys.argv` or
executes the module a second time.

Acceptance evidence:

1. The private marker dispatches only to `mentat.local_bridge.main()`.
2. The fixed `--host` and `--port` arguments pass through unchanged.
3. The server, Node gateway, visible-app handoff, and Hermes boundaries are
   unchanged.
4. The focused test verifies no `runpy` execution and no global argument
   mutation.

| Check | Result | Notes |
| --- | --- | --- |
| `python3 -m unittest tests.test_packaging_cli tests.test_web_runtime -v` | Pass | 59 focused startup and packaging checks passed. |
| `python3 -m unittest tests.test_ci_quality_gate -v` | Pass | 9 CI contract checks passed. |
| `python3 -m py_compile packaging/mentat_native.py` | Pass | The corrected native entry point compiles. |
| `git diff --check` | Pass | No whitespace errors. |

The user explicitly approved this step-by-step correction and retains the
standing publication approval recorded above. GitHub's macOS runner remains
the required frozen-bundle verification environment.

### Final correction round 13 review

Two independent reviewers reported no findings. They confirmed that direct
dispatch preserves the fixed bridge arguments, token and lifecycle handling,
dispatch precedence, frozen import semantics, and the existing security
boundary while removing the duplicate module execution.

### CI diagnostic round 14

Native run 254 confirmed that direct dispatch removed the frozen duplicate-
module warning, but both macOS architectures still timed out at private-bridge
readiness. Windows passed. A local Intel bundle was then built with Python
3.13.14, PyInstaller 6.21.0, and Node 24.19.0 after every existing Mentat
listener had been stopped. Its direct private bridge, direct console
supervisor, visible launcher, and background redirected launcher all reached
the authenticated bridge health route and were shut down afterward. This
clears the bundled code paths locally and leaves a hosted-runner startup-stage
or cold-start timing difference to identify.

The frozen private bridge now emits four fixed, secret-free stage markers:

1. entry point reached;
2. project imports ready;
3. bridge dispatch reached; and
4. socket binding started.

The existing ready marker remains the final stage. GitHub timestamps around
these markers will identify the exact interval without printing arguments,
ports, process IDs, paths, environment values, tokens, or provider state. The
binding marker is frozen-only, so source-checkout output is unchanged.

| Check | Result | Notes |
| --- | --- | --- |
| Local frozen Intel bridge and gateway matrix | Pass | Direct bridge, direct supervisor, visible launcher, and background redirected launcher all became ready; all listeners were stopped afterward. |
| `python3 -m unittest tests.test_packaging_cli tests.test_web_runtime tests.test_ci_quality_gate tests.test_mentat_local_bridge -v` | Pass | 96 focused startup, packaging, CI, and authenticated bridge checks passed with loopback test access. |
| `python3 -m py_compile packaging/mentat_native.py mentat/local_bridge.py` | Pass | Both instrumented entry points compile. |
| `git diff --check` | Pass | No whitespace errors. |

The local diagnostic regenerated only the ignored standalone web payload with
webpack because this host blocks Turbopack's temporary worker port. The tracked
build remains Turbopack, and GitHub's Turbopack bundle step passed before both
macOS smoke failures.

The first adversarial review found that the initial entry markers were broader
than the macOS-only diagnostic scope. All markers now require both a frozen
runtime and macOS. Fresh-module and isolated bridge-main tests prove the entry,
dispatch, and binding markers are present on frozen macOS and silent for source
macOS and frozen Windows.

### Final diagnostic round 14 review

After the platform-scope and test-evidence corrections, two independent
reviewers reported no remaining findings. They confirmed the frozen-macOS-only
gates, fixed secret-free output, import-time coverage, dispatch coverage,
binding coverage, and isolated cleanup behavior.
