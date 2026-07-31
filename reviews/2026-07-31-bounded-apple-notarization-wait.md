# Feature Slice Review: Bounded Apple Notarization Wait

Status: Successful  
Slice: `bounded-apple-notarization-wait`  
Date: `2026-07-31`  
Review log: `reviews/2026-07-31-bounded-apple-notarization-wait.md`

## Process exception

- The project owner previously instructed Codex to assume approval for all
  Road-to-Beta slices, decisions, verification, and publication actions.
- That standing authorization covers this contract, test strategy, outcome,
  staging, commit, push, and ready pull request. Work remains one reviewed
  slice at a time and unrelated user files stay excluded.

## Slice contract

### Goal

Make a stalled Apple notarization attempt fail clearly and cleanly before
GitHub's hard job limit, without cancelling Apple's server-side submission or
encouraging duplicate resubmission.

### In scope

- Give the protected macOS signing job a five-hour job limit.
- Give `notarytool` a four-hour wait limit, leaving time for normal post-wait
  validation and always-run signing-material cleanup.
- Document that Apple continues processing a submission after the local wait
  ends, that the run remains failed until an accepted ticket can be stapled,
  and that maintainers should inspect the original submission before rerunning.
- Add focused release-workflow contract coverage and operator-visible
  changelog/roadmap evidence.

### Out of scope

- Cancelling, modifying, or resubmitting the currently active Apple request.
- Accepting an unstapled package, weakening Gatekeeper checks, or publishing a
  timed-out package.
- Adding a resumable notarization workflow, changing Apple credentials, or
  beginning Azure/Windows signing setup.
- UI or Hermes behavior changes.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | The protected macOS job has a five-hour bound and `notarytool` waits at most four hours. | Workflow-scoped contract test and source inspection | Pass |
| AC-2 | Timeout cannot reach staple, Gatekeeper, smoke, upload, validation-success, tag, or release paths; signing cleanup remains always-run. | Named-step ordering, failure-propagation, and cleanup assertions plus existing dependency topology | Pass |
| AC-3 | Maintainer guidance says Apple continues processing, warns against immediate duplicate submission, and preserves the original submission as the status/support reference. | Documentation contract and inspection | Pass |
| AC-4 | Full-release and macOS-only topology, protected-source checks, credentials, and artifact gates remain unchanged. | Focused packaging/release tests and complete suite | Pass |
| AC-5 | Two independent adversarial reviewers report no unresolved in-scope issue. | Three review rounds ending in two independent clean reports | Pass |

### Constraints and recovery

- Safety: secrets stay only in the protected environment; no credential or
  private signing material enters logs, docs, artifacts, or source.
- Compatibility: use `notarytool`'s supported `--timeout` duration and keep
  both validation scopes intact.
- Rendered behavior: not applicable; release automation and maintainer docs
  only.
- Rollback or recovery: revert the slice commit. An Apple submission already
  accepted or still processing is unaffected by workflow-source changes.
- Documentation targets: `RELEASE_SIGNING.md`, `ROAD_TO_BETA.md`,
  `CHANGELOG.md`, and this review log.
- Version-control strategy: branch
  `codex/bounded-apple-notarization-wait` from current merged `main`; ready PR
  back to `main`.

### Scope discussion and approval

- Recommendation and rationale: bound the provider wait below GitHub's
  six-hour hard ceiling so failure is diagnosable and cleanup retains time to
  run. Four hours is deliberately longer than Apple's documented two-hour
  example while reserving nearly an hour for post-processing inside a
  five-hour job limit.
- Alternatives considered: leave the unbounded wait (poor cleanup and failure
  evidence at the runner ceiling); use two hours (too aggressive for the
  observed first-account delay); add submission-resume automation (useful but
  materially broader and unnecessary before one bounded failure is observed).
- User decisions: standing Road-to-Beta authorization accepts the bounded
  release-safety slice and explicitly prioritizes completing the Apple side.
- Approved at: 2026-07-31 under the recorded standing authorization.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned test or evidence | What it proves | Limitations |
| --- | --- | --- | --- | --- |
| AC-1 | The macOS job and `notarytool --wait` have no explicit bound. | Require `timeout-minutes: 300` only in the macOS job and exactly one `--timeout 4h`. | GitHub and Apple polling bounds are source-controlled. | Hosted duration behavior depends on GitHub and Apple. |
| AC-2 | GitHub could terminate the job at its hard ceiling while the wait process is active. | Inspect job ordering/dependencies and retain existing staple, Gatekeeper, artifact, and `if: always()` cleanup assertions. | A nonzero timeout stops all success-only steps and preserves cleanup. | A live timeout is intentionally not induced because it would consume protected signing resources. |
| AC-3 | Guidance says only that the workflow waits for Apple. | Require four-hour, server-side continuation, and no-immediate-rerun guidance. | Operators avoid duplicate submissions and false success. | Status retrieval still requires trusted Apple credentials. |
| AC-4 | Release topology is already strongly covered. | Run packaging, CI, rehearsal, promotion, YAML, compilation, and full-suite checks. | No regression to either validation mode or release gate. | CI cannot notarize without protected secrets. |
| AC-5 | Implementation has not been independently challenged. | Two identical read-only review packets and re-review after fixes. | Correctness, safety, compatibility, and operability review. | Reviewers cannot observe Apple's private queue. |

### Baseline results

| Command or action | Environment | Result | Notes |
| --- | --- | --- | --- |
| Workflow source inspection | Merged `main` | Gap confirmed | macOS job has no `timeout-minutes`; `notarytool submit --wait` has no `--timeout`. |
| Protected run `30655257545` inspection | GitHub Actions, macOS Intel | In progress | Signing passed; Apple notarization remained active for more than two hours, with no failure or completed log available. |
| Responsive dashboard audit | In-app Chromium, 1440/1024/390 px | Pass | No horizontal overflow; session controls align; border-only focus and mobile navigation labels behave as intended. |
| `python -m unittest tests.test_packaging_cli.PackagingContractTests.test_signed_release_path_is_manual_protected_and_ephemeral -v` | macOS, Python 3.13 | Expected fail | New contract failed on the missing macOS job timeout before production changes. |

### Test discussion and approval

- User questions and decisions: standing authorization accepts proportional
  source/contract verification rather than deliberately consuming a protected
  runner for a four-hour failure test.
- Accepted coverage gaps: Apple queue duration and completion remain external;
  the currently active submission is not interrupted.
- Approved at: 2026-07-31 under the recorded standing authorization.

## Implementation record

### Changes

- Added a five-hour macOS job limit and a four-hour `notarytool` wait limit.
- Kept every existing success-only staple, Gatekeeper, smoke, upload, and
  release dependency unchanged; the existing always-run cleanup remains the
  final macOS step.
- Added operator guidance for a still-processing timed-out submission and a
  warning against immediate duplicate resubmission.
- Recorded the bounded wait in the roadmap and changelog without claiming the
  currently active Apple request has completed.

### Deviations and decisions

- None.

## Verification

### Focused checks

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes or artifacts |
| --- | --- | --- | --- | --- |
| `python -m unittest tests.test_packaging_cli.PackagingContractTests.test_signed_release_path_is_manual_protected_and_ephemeral -v` | macOS, Python 3.13 | 0 | 1 pass | New timeout and operator-guidance contract. |
| `python -m unittest tests.test_packaging_cli tests.test_ci_quality_gate tests.test_release_rehearsal tests.test_public_beta_promotion -q` | macOS, Python 3.13 | 0 | 50 pass | Re-run after reviewer-requested named-step hardening; packaging, protected workflow, artifact, rehearsal, and promotion topology all pass. |
| YAML safe-load, Python compilation, and `git diff --check` | macOS | 0 | All pass | Workflow remains valid YAML; release scripts compile; patch is whitespace-clean. |

### Full suite

| Command or action | Environment | Exit/result | Pass/fail/skip counts | Notes |
| --- | --- | --- | --- | --- |
| `python -m unittest discover -s tests -q` | macOS, Python 3.13 | 0 | 915 run, 911 pass, 4 expected platform skips | No regression; subprocess negative-path diagnostics are expected test output. |

### Rendered or manual behavior

- Not applicable to the release-workflow change. The broader goal's UI audit
  is recorded in the baseline above.

## Adversarial review

### Round 1

Two independent read-only reviewers received the same contract, diff, test
strategy, verification record, and Apple-run context.

- Correctness reviewer: no production, documentation, secret-handling, or
  topology defect. Reported one blocking P2 test-contract weakness: broad
  substring checks could still pass if upload moved before notarization, a
  timeout became tolerated, or cleanup stopped being the final always-run step.
- Operability reviewer: no production or operator-safety defect. Independently
  reported the same blocking P2 weakness: the job timeout, exact notary command,
  and cleanup condition were not sufficiently scoped to their YAML locations.
- Reconciliation: accepted. The focused contract now scopes named macOS steps,
  requires the sole job-level five-hour timeout beside the macOS runner,
  requires exactly one real notary submission ending in the four-hour wait,
  rejects tolerated notarization/smoke/upload failures, verifies the full
  submit/staple/Gatekeeper order, and requires cleanup to remain the final
  named step with exactly one `always()` condition.

### Round 2

- Operability reviewer: clean; no P0-P3 findings.
- Correctness reviewer: production behavior remained correct, but reported one
  blocking P2 regression-test gap. The named smoke and upload blocks rejected
  `continue-on-error` but did not reject an `if: always()` or `if: failure()`
  override that could make an otherwise success-only step run after timeout.
- Reconciliation: accepted. Both named success-only steps now reject any
  step-level `if:` override in addition to rejecting `continue-on-error`.

### Round 3

- Correctness reviewer: clean; no findings.
- Operability reviewer: clean; no P0-P3 findings.
- Both independently confirmed that the final contract now protects exact
  timeout placement, failure propagation, ordered notarization validation,
  success-only smoke/upload, final always-run cleanup, downstream release
  gating, and safe operator guidance.
- No reviewer dissent remains.

## Documentation updates

- Roadmap: updated with the bounded-wait safeguard without claiming Apple
  completion.
- Changelog: updated with the operator-visible release-safety change.
- Architecture/operator docs: `RELEASE_SIGNING.md` now explains the bounds,
  server-side continuation, original-submission follow-up, and no-duplicate
  rerun rule.
- Project/session notes: this review log.
- Documentation verification: focused contract assertions pass.

## Publication gate

- Proposed files: `.github/workflows/signed-release-artifacts.yml`,
  `tests/test_packaging_cli.py`, `RELEASE_SIGNING.md`, `ROAD_TO_BETA.md`,
  `CHANGELOG.md`, and this review log.
- Branch and base: `codex/bounded-apple-notarization-wait` to `main`.
- Commit message: `Bound Apple notarization waits`.
- PR title: `Bound Apple notarization waits`.
- PR summary: add explicit provider/job time bounds, preserve fail-closed
  release behavior and cleanup, and document safe timeout handling.
- Unresolved risks: Apple may continue processing beyond four hours; the
  package remains unpublished and a future resumable-status slice may be
  warranted only if the bounded failure recurs.
- User authorization and scope: standing Road-to-Beta approval recorded above.
- Commit hash: pending publication.
- Ready PR URL: pending publication.

## Outcome review

- Classification: Successful.
- Acceptance criteria summary: AC-1 through AC-5 pass.
- Potential bugs or untested paths: Apple's live queue duration cannot be
  simulated locally; a protected hosted timeout is intentionally not induced.
- Remaining reviewer dissent: none.
- Compatibility/migration/rollback concerns: no migration; revert the slice to
  restore the prior unbounded wait.
- User decision: standing authorization permits publication after all gates.
- Next slice authorized: Yes, under the standing Road-to-Beta authorization.
