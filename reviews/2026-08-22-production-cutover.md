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
