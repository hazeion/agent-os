# Feature Slice Review: Dual-Architecture Native macOS Release

Status: Publication in progress
Slice: `dual-architecture-macos-release`
Date: `2026-08-02`
Review log: `reviews/2026-08-02-dual-architecture-macos-release.md`

## Slice contract

### Goal

Every protected Mentat release produces independently built, signed,
notarized, stapled, installed, and smoke-tested installers for Apple Silicon
and Intel Macs. Apple Silicon is presented as the default while Intel remains
fully supported.

### In scope

- Add a fixed macOS build matrix mapping `macos-15` to `arm64` and
  `macos-15-intel` to `x86_64`.
- Add fail-closed architecture verification for the runner, main executable,
  and every bundled Mach-O before signing.
- Give each matrix leg unique package and workflow-artifact names.
- Require both matrix legs in macOS-only validation and full releases.
- Include both packages in checksums, manifests, recovery bundles, immutable
  prereleases, promotion validation, and rehearsal guidance, with `arm64`
  presented first.
- Add Apple Silicon to ordinary unsigned native artifact smoke CI.
- Update release/signing documentation, roadmap wording, changelog, contract
  tests, and this review log.

### Out of scope

- DMG packaging, one universal2 binary, automatic download-page architecture
  detection, automatic updates, or Apple credential changes.
- Publishing a real release or changing Windows/Python artifacts.
- Live protected Apple Silicon signing/notarization before merge to protected
  `main`.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Apple Silicon and Intel native bundles build and pass matching unsigned smoke jobs. | Native-workflow contract tests and GitHub PR checks | Pre-publication checks pass; hosted ARM run pending push |
| AC-2 | Both protected matrix legs independently complete the existing build/sign/submit-once/poll/staple/Gatekeeper/install/health/stop/uninstall/upload path. | Signed-workflow contract tests; protected post-merge runs | Contract passes; protected execution pending merge |
| AC-3 | A runner or bundled Mach-O architecture mismatch fails before signing. | Focused architecture-verifier tests and workflow ordering assertions | Pass |
| AC-4 | Release assembly and promotion require exactly both macOS packages and reject missing, duplicate, renamed, or unexpected architecture assets. | Release rehearsal and promotion tests | Pass |
| AC-5 | User/operator guidance recommends `arm64` first and clearly identifies Intel as the alternative. | Documentation contract inspection | Pass |
| AC-6 | Existing notarization, cleanup, protected-source, Windows/Python, and immutable-tag gates remain intact. | Packaging/CI/release contract tests and full suite | Pass |

### Constraints and recovery

- Safety: architecture labels must come from a fixed matrix and must be
  verified against the runner and bundle before protected signing. Each
  notarization submission remains single-upload, resumable, bounded, and
  fail-closed.
- Compatibility: retain the existing Intel package and Windows/Python release
  behavior; add a native Apple Silicon package without changing runtime data.
- Rendered behavior: no product UI changes. Release notes and install guidance
  list Apple Silicon first.
- Rollback or recovery: revert the slice before a release, or omit release
  publication unless both architecture jobs and exact-asset verification pass.
- Documentation targets: `README.md`, `RELEASE_SIGNING.md`,
  `RELEASE_REHEARSAL.md`, `PUBLIC_BETA_RELEASE.md`, `ROAD_TO_BETA.md`,
  `CHANGELOG.md`, and packaging guidance where relevant.
- Version-control strategy: branch `codex/dual-architecture-macos-release`
  from `main`; ready PR to `main` only after a separate publication approval.

### Scope discussion and approval

- Recommendation and rationale: two thin native packages provide direct ARM
  support without the dependency/toolchain complexity of a universal2 Python
  bundle, and retain a fully native Intel path.
- Alternatives considered: keep Intel-only and rely on Rosetta (rejected);
  ship only ARM (rejected); build universal2 (deferred due larger artifact and
  multi-architecture Python/dependency requirements).
- User decisions: support both architectures and treat Apple Silicon as the
  default because most current Mac users run Apple Silicon.
- Approved at: 2026-08-02.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | Native artifact CI names only `macos-15-intel`. | Assert exact runner/architecture matrix and matching smoke commands. | Both thin native builds enter ordinary CI. | Hosted ARM execution occurs after push. |
| AC-2 | Protected workflow has one Intel job and hard-coded x86_64 names. | Assert exact protected matrix, unique artifact names, complete ordered safety path, and aggregate success. | Both architectures retain every release gate. | Real protected signing requires merged `main`. |
| AC-3 | No explicit bundle-wide architecture verifier exists. | Unit-test valid ARM/Intel inventories plus mixed, missing, unknown, and tool-failure cases; assert verification precedes signing. | Mislabelled or mixed thin packages fail closed. | Uses mocked tool output locally; hosted builds exercise real tools. |
| AC-4 | Release metadata expects one macOS package. | Exercise exact asset inventory, checksum, manifest, recovery, prerelease, and promotion rejection paths. | Neither architecture can be silently omitted or substituted. | Does not create a public release pre-merge. |
| AC-5 | Rehearsal and tester docs name only x86_64. | Contract inspection and focused documentation assertions. | Apple Silicon is the primary documented path. | GitHub asset ordering beyond filenames is not controllable. |
| AC-6 | Current safety contracts cover only one macOS leg. | Run focused packaging/notary/release tests, YAML parse, compilation, quality gates, and full suite. | Existing protected behavior remains fail-closed. | No credential-bearing job runs locally. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| `.venv/bin/python -m unittest tests.test_packaging_cli tests.test_release_rehearsal tests.test_public_beta_promotion tests.test_apple_notarization -q` | macOS local checkout, Python 3.13 venv | Pass | 49 existing tests pass; source inspection confirms signed/native workflows and release metadata are Intel-only. |
| Worktree inventory | `codex/dual-architecture-macos-release` | Pass | Preserved unrelated `design/` and `uv.lock` files and excluded them from slice scope. A user-authorized cleanup later restored `data/projects.json` to the committed generic seed. |

### Test discussion and approval

- User questions and decisions: user approved the proposed slice contract and
  test strategy without changes.
- Accepted coverage gaps: live protected ARM signing/notarization is deferred
  until the slice merges to protected `main`; PR ARM native CI supplies the
  pre-merge architecture/build proof.
- Approved at: 2026-08-02.

## Implementation record

### Changes

- Added exact `arm64`/`x86_64` matrices to ordinary native CI and the
  protected signing/notarization workflow, with Apple Silicon first.
- Added unique architecture-qualified packages and workflow artifacts, and
  required both packages in release recovery, rehearsal, and promotion.
- Added a fail-closed macOS bundle verifier. It validates the runner, rejects
  unknown architectures and escaping links, and requires every bundled
  Mach-O to be a thin match before signing identities are imported.
- Added verifier unit tests and expanded packaging, release, promotion,
  readiness, and documentation contract tests.
- Updated the limited-beta feedback form to classify Apple Silicon and Intel
  as separate native platforms, with Apple Silicon first.
- Added the verifier to the source distribution's explicit allowlist and
  exact artifact inventory.
- Updated install, support, signing, testing, release, roadmap, and changelog
  guidance to recommend native Apple Silicon while retaining native Intel.
- Audited all packaged seed JSON. Restored the sole user-added project entry
  to the committed generic seed and confirmed that package data contains no
  user paths, common personal email domains, credential-like fields, or
  private/runtime directories.

### Deviations and decisions

- The user explicitly requested removal of personal user-owned data during
  implementation. This did not broaden release behavior; it restored a
  packaged seed fixture to its committed public-safe state.
- A first full-suite run exposed that personal fixture through an existing
  seed-invariant test. The fixture was removed rather than weakening the test.
- Local hardware is Intel. A real local Intel bundle and a previously produced
  notarized Intel bundle were inspected; hosted Apple Silicon execution remains
  the agreed post-push evidence.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `.venv/bin/python -m unittest tests.test_macos_architecture tests.test_packaging_cli tests.test_release_rehearsal tests.test_public_beta_promotion tests.test_apple_notarization tests.test_limited_beta_readiness tests.test_ci_quality_gate -q` | Local Intel macOS, Python 3.13 | Exit 0 | 72 pass, 0 fail, 0 skip | Architecture, workflow, release, promotion, notarization, readiness, and quality contracts. |
| Build wheel/sdist in an isolated copy, then run `scripts/verify_python_artifacts.py` on the output | Local Intel macOS, locked build environment | Exit 0 | 2 artifacts verified | Exact wheel/sdist inventory passes; verifier is in the sdist; private/runtime content is absent. |
| Build `Mentat.app` with `scripts/build_native.py --bundle-only`, then run `scripts/verify_macos_architecture.py ... --expected x86_64` | Local Intel macOS, locked native environment | Exit 0 | 85 Mach-O files verified | Fresh thin Intel bundle passes exhaustive architecture inspection. |
| Run `verify_bundle()` against a previously signed and notarized Intel package expansion | Local Intel macOS | Pass | 85 Mach-O files verified | Verifier handles the real PyInstaller layout and its 54 internal links. |
| Ruby YAML parse of all three changed workflows | Local Intel macOS | Exit 0 | 3 pass | Workflow documents are syntactically valid YAML. |
| Python compilation, browser-smoke JavaScript syntax, `git diff --check`, tracked-secret scan, and `pip-audit` for runtime/native locks | Local Intel macOS | Exit 0 | All pass; 0 known vulnerabilities | No syntax, whitespace, tracked-secret, or known dependency-vulnerability failure. |
| Scan packaged seed JSON for user-home paths, common personal email domains, and credential-like fields; inspect `git diff -- data` | Local checkout | Exit 0 | 9 seed files clean; empty data diff | No personal user-owned delta remains in package data. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `.venv/bin/python -m unittest discover -s tests -v` | Local Intel macOS, Python 3.13 | Exit 0 | 936 pass, 0 fail, 4 skip | Final direct-worktree suite after package-data cleanup. |
| Same focused 72-test command after the Round 1 reviewer fix | Local Intel macOS, Python 3.13 | Exit 0 | 72 pass, 0 fail, 0 skip | Confirms exact native platform wording/order in the feedback form. |
| `.venv/bin/python -m unittest discover -s tests -v` after the Round 1 reviewer fix | Local Intel macOS, Python 3.13 | Exit 0 | 936 pass, 0 fail, 4 skip | Complete regression check after feedback-form correction. |

### Rendered or manual behavior

- Not applicable; this slice changes build/release behavior and documentation,
  not rendered product UI.

## Adversarial review

### Round 1 packet

- Contract, test strategy, this log, raw diff and file list, repository
  instructions, and all verification evidence supplied identically to two
  independent read-only reviewers.
- Reviewer A correctness/safety findings: no findings in the independent pass.
- Reviewer B compatibility/product findings: one medium blocking finding. The
  required beta feedback form still listed Intel first and classified Apple
  Silicon as Rosetta, conflicting with the native ARM-default release and
  cohort evidence terminology.
- Reconciliation: unique finding sent verbatim to Reviewer A, who independently
  corroborated its evidence, severity, impact, and in-scope correction. The
  implementing agent changed the exact ordered platform options to Apple
  Silicon native, Intel native, Windows, and Linux preview, and added an exact
  wording/order/no-Rosetta contract assertion. Focused and full suites pass.

### Round 2 packet

- Fresh complete raw diff and current evidence supplied independently to both
  reviewers after the accepted fix.
- Reviewer A correctness/safety findings: no findings.
- Reviewer B compatibility/product findings: no findings.
- Reconciliation: review gate complete with no blocking findings or surviving
  dissent.

## Documentation updates

- Roadmap: updated `ROAD_TO_BETA.md` for two native Mac packages.
- Changelog: added the dual-architecture release and fail-closed verification.
- Architecture/operator docs: updated `README.md`, `SUPPORT.md`, packaging,
  signing, rehearsal, cohort, testing, and public-beta release guidance.
- Project/session notes: this review log.
- Documentation verification: included in the 72 focused contract tests and
  final 936-test suite.

## Publication gate

- Proposed files: the three workflows; release/support/testing documentation;
  `MANIFEST.in`; release/promotion/verifier scripts; focused tests; and this
  review log. Unrelated `design/` and `uv.lock` remain excluded.
- Branch and base: `codex/dual-architecture-macos-release` to `main`.
- Commit message: `Add dual-architecture macOS releases`.
- PR title: `Add native Apple Silicon and Intel releases`.
- PR summary: build, verify, sign, notarize, and release separate thin native
  Mac packages; recommend Apple Silicon first; retain Intel and all existing
  release safety gates.
- Unresolved risks: protected ARM signing/notarization requires post-merge run.
- User authorization and scope: approved on 2026-08-02 to stage only the
  reviewed slice, commit, push this branch, and open a ready PR to `main`;
  unrelated `design/` and `uv.lock` remain excluded.
- Commit hash: None.
- Ready PR URL: None.

## Outcome review

- Classification: Paused pending publication decision.
- Acceptance criteria summary: all local and contract evidence passes; hosted
  ARM and protected credential-bearing runs remain gated on publication/merge.
- Potential bugs or untested paths: no local ARM runner or protected Apple
  credentials were used, as agreed.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: Intel remains supported as a
  separate native package; release fails closed unless both Mac packages are
  present. Revert the slice before release if hosted ARM/protected checks fail.
- User decision: Pending.
- Next slice authorized: No
