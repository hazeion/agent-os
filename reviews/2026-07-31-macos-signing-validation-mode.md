# Feature Slice Review: macOS Signing Validation Mode

Status: Successful
Slice: `macos-signing-validation-mode`
Date: `2026-07-31`
Review log: `reviews/2026-07-31-macos-signing-validation-mode.md`

## Process exception

- The user instructed Codex to assume approval for all slices and related
  implementation, verification, publication, and continuation decisions.
- Standing approval covers this contract, test strategy, implementation,
  verification, outcome, staging, commit, push, ready pull request, merge, and
  continuation to the next reviewed slice.

## Slice contract

### Goal

Permit a protected, macOS-only hosted signing and notarization validation run
before Azure is configured, while preserving the existing full cross-platform
release, immutable tag, and prerelease gates.

### In scope

- Add an explicit manual workflow scope choice with `full-release` as the safe
  default and `macos-only` as the isolated Apple validation option.
- Make the RC tag input required by validation logic for a full release and
  require it to be blank for macOS-only validation.
- In macOS-only mode, run the protected-source and complete signed/notarized
  macOS package path while requiring Windows and Python release jobs to remain
  skipped.
- Add a fail-closed validation summary that proves the expected job outcomes.
- Keep the release/tag job unreachable in macOS-only mode.
- Add structural tests and maintainer documentation for both paths.

### Out of scope

- Creating or changing Apple credentials, Azure resources, or GitHub
  environment protection rules.
- Dispatching the hosted workflow before Apple notarization credentials are
  present.
- Publishing a release, tag, or long-lived recovery bundle from macOS-only
  validation.
- Changing application code, installer contents, signing identities, or any
  user-owned project data/design files.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Manual dispatch exposes only `full-release` and `macos-only`, with `full-release` as the default. | Workflow source and exact input-scoped contract test | Pass |
| AC-2 | Full release requires a valid numbered RC tag; macOS-only requires the tag field to be empty; unknown scope fails closed. | Workflow source and contract test | Pass |
| AC-3 | macOS-only runs protected source verification and the unchanged complete macOS signing, notarization, Gatekeeper, install, health, stop, uninstall, and ephemeral upload path. | Dependency/guard inspection and existing packaging assertions | Pass |
| AC-4 | macOS-only requires Windows and Python jobs to be skipped and cannot run the release/tag job. | Job-scoped guards, dependencies, result assertions, and permission assertions | Pass |
| AC-5 | Full release continues to require source, macOS, Windows, and Python success before tag and prerelease publication. | Release dependency/result inspection and full tests | Pass |
| AC-6 | Operator guidance clearly distinguishes safe Apple validation from a real release and does not expose credentials. | Documentation and secret-free diff inspection | Pass |
| AC-7 | Two independent adversarial reviewers find no unresolved blocking correctness, safety, compatibility, or operability gap. | Final correctness/safety and operability reviews | Pass |

### Constraints and recovery

- Security: Apple secrets remain available only through the protected
  `beta-release` environment; validation must not print or persist them beyond
  the existing ephemeral artifact behavior.
- Safety: macOS-only must have no contents-write permission and no path to tag
  or GitHub release creation.
- Fail closed: an unknown mode, inappropriate tag value, failed protected
  source check, failed macOS job, or unexpected Windows/Python execution makes
  validation fail.
- Compatibility: keep the full-release default and current job topology so
  existing operator expectations remain intact.
- Recovery: validation produces only a seven-day workflow artifact; failed or
  superseded attempts can be rerun from a later reviewed `main` revision.
- Version-control strategy: ready PR from
  `codex/macos-signing-validation-mode` to `main`.

### Scope discussion and approval

- Recommendation and rationale: add an isolated mode to the existing protected
  workflow instead of duplicating the signing implementation. This keeps one
  Apple path to maintain and makes divergence less likely.
- Alternatives considered: wait for Azure (blocks Apple proof); weaken the
  release gate (unsafe); duplicate the entire macOS job in another workflow
  (high drift risk); publish a macOS-only RC (misrepresents release readiness).
- User decision: standing approval applies.
- Approved at: `2026-07-31` under the process exception.

## Test strategy

| Acceptance criterion | Planned evidence | Limitation |
| --- | --- | --- |
| AC-1 | Assert the choice input, exact options, and default. | Structural test does not render GitHub's dispatch UI. |
| AC-2 | Assert both tag predicates, existing RC validator, and unsupported-scope failure. | Hosted expression evaluation remains an external gate. |
| AC-3 | Assert macOS keeps the protected-main guard and source dependency; retain existing signing/notary/smoke assertions. | Real notarization requires a protected hosted dispatch. |
| AC-4 | Assert Windows/Python full-only guards, macOS validation summary result checks, and release full-only guard. | Hosted skipped-result values are verified finally by dispatch. |
| AC-5 | Inspect release `needs` and success checks; run focused and full suites. | Azure remains intentionally undispatched. |
| AC-6 | Inspect operator guide and diff for secret-free, unambiguous instructions. | Documentation cannot enforce GitHub environment configuration. |
| AC-7 | Two independent read-only adversarial reviews after implementation and verification. | Reviewers do not access secrets. |

### Baseline results

- `main` at `8ff618f` has a single manual full-release path that requires an RC
  tag and always schedules macOS, Windows, and Python protected jobs.
- The Apple signing path has passed a real local identity/package proof and now
  establishes the pinned Developer ID G2 trust chain in hosted runners.
- Azure environment variables are not configured, so the existing workflow
  cannot currently prove Apple notarization without also scheduling the
  unavailable Windows signing path.
- User-owned `data/projects.json` and untracked `design/` are present and are
  explicitly excluded from this slice.

## Implementation record

### Changes

- Manual dispatch now has an exact two-value `validation_scope` choice:
  `full-release` is the default and `macos-only` is the explicit Apple-only
  validation path. The tag field is optional in GitHub's form because GitHub
  cannot express conditional requiredness.
- The protected-source job validates the cross-field contract before any
  protected signing job: full release requires a nonempty tag that passes the
  existing numbered-RC validator, macOS-only requires an empty tag, and every
  other value fails closed.
- The macOS job retains its protected-`main` guard, protected-source dependency,
  `beta-release` environment, and unchanged build/sign/notarize/staple/
  Gatekeeper/install/health/stop/uninstall/upload steps. It runs in either mode.
- Windows and Python artifact jobs now have job-specific full-release guards.
- A read-only `macos-validation` summary runs under `always()` only for
  macOS-only dispatches. It depends on all four protected jobs and succeeds only
  when source and macOS succeeded while Windows and Python were skipped.
- The sole contents-write job is explicitly full-release-only and retains all
  four dependencies plus its existing success assertions before tag/release
  creation.
- Operator documentation explains the exact UI choices, blank-tag requirement,
  environment approval, seven-day artifact, complete Apple checks, and absence
  of tag/release/recovery publication.
- Tests use input- and job-scoped workflow sections to lock the exact two
  options, safe default, conditional tag rules, every job guard, both summary
  success predicates, both skipped predicates, both dependency graphs, and the
  single contents-write location.

### Deviations and decisions

- `release_tag` is marked optional in the form because workflow-dispatch inputs
  cannot be conditionally required. The protected-source shell contract makes
  it required for `full-release` and forbidden for `macos-only` before secrets
  can be used.
- The Apple validation path stays inside the existing workflow instead of
  duplicating hundreds of lines. This keeps one signing/notarization
  implementation while separate guards and a fail-closed summary preserve the
  release boundary.
- The validation artifact retains the existing seven-day lifetime. It is proof
  material, not a release candidate or recovery bundle.

## Verification

### Focused checks

- `python3 -m unittest tests.test_packaging_cli tests.test_ci_quality_gate -v`:
  33 passed after the reviewer-requested scoped-test strengthening.
- YAML safe-load of `.github/workflows/signed-release-artifacts.yml`: passed.
- `git diff --check`: passed.
- `actionlint` is not installed locally, so GitHub's hosted workflow parser and
  checks remain the authoritative publication validation.
- Source inspection confirms the macOS job body is unchanged apart from the
  surrounding dispatch graph. Its protected environment, signing, notarization,
  stapling, both Gatekeeper assessments, exact-package install/health/stop/
  uninstall smoke, ephemeral artifact, and always-run identity cleanup remain.
- Job-scoped tests confirm both validation-summary positive results, both
  skipped results, all four dependencies for validation and release, and that
  the only `contents: write` permission remains inside the full-release-only
  release job.

### Full suite

- `python3 -m unittest discover -s tests -q`: 910 run; 908 passed, 2 failed,
  4 skipped.
- The two failures are unchanged local-state differences outside this slice:
  user-owned `data/projects.json` contains the intentionally preserved
  `Daily Check` project, and the live local Hermes cron inventory returned zero
  jobs where the fixture test expects one.
- An initial full run also exposed the pre-existing CI contract assertion that
  required the release job's former unconditional `always()` guard. That test
  now asserts the exact full-release-only guard; both affected modules pass
  33/33 and the subsequent full run contains only the two known local-state
  failures.

### Publication checks

- The scoped diff contains only the protected workflow, release-signing guide,
  two workflow contract test modules, and this review record. User-owned
  `data/projects.json` and `design/` are excluded from the slice.
- No credential value, local private path, account identifier, certificate
  payload, or new external action is present. Existing secret references remain
  confined to the protected macOS job.
- Pull request 83 ran 50 hosted checks after merging the validated remote-text
  performance fix from `main`; all 50 passed. This includes workflow parsing,
  the complete Linux/macOS/Windows Python matrix, native installers, browser
  smoke, package lifecycle, quality aggregation, and dependency/secret scan.
- The previously failing macOS Python 3.12 shard passed with the isolated
  performance correction present. No workflow or signing-validation check
  failed.

## Adversarial review

- The correctness/safety reviewer found no workflow-code P0/P1 defect. The
  initial P1 was a process/evidence gap because this record still contained
  placeholders. This completed implementation and verification packet resolves
  that gap for re-review.
- The operability/compatibility reviewer found no implementation P0/P1 defect
  and confirmed the intended dispatch, approval, skipped-job, read-only, and
  full-release continuity semantics.
- Both reviewers requested stronger regression evidence. Tests now parse exact
  input/job sections and assert the exact two options, each job-specific guard,
  validation dependencies, source/macOS success, Windows/Python skipped, and
  write-permission confinement.
- The final correctness/safety re-review found no remaining P0-P3 issue and
  confirmed its prior P1 and P2 findings resolved.
- The final operability/compatibility re-review independently found no
  remaining P0-P3 issue, reran the 33 focused tests, and confirmed the exact
  dispatch, isolation, permission, documentation, and full-release contracts.

## Outcome

- Successful. Local implementation, verification, both independent reviews,
  and all 50 hosted checks satisfy AC-1 through AC-7 with no unresolved P0-P3
  finding. The mode remains non-publishing and rollback is a normal commit
  revert with no credential or data migration.
