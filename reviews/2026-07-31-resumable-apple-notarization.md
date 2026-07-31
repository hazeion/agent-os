# Feature Slice Review: Resumable Apple Notarization Status

Status: Successful  
Slice: `resumable-apple-notarization`  
Date: `2026-07-31`  
Review log: `reviews/2026-07-31-resumable-apple-notarization.md`

## Process exception

- The project owner instructed Codex to assume approval for all Road-to-Beta
  slices, verification, publication actions, and Apple-side work.
- That standing authorization covers this contract and proportional test
  strategy. Work remains one reviewed slice at a time and the owner's unrelated
  working-tree files remain excluded.

## Slice contract

### Goal

Keep one Apple notarization submission recoverable through temporary status
connection failures so a runner interruption does not encourage duplicate
uploads or discard the request identity.

### In scope

- Submit the signed package once in a short, separately completed step.
- Validate and retain Apple's submission ID in the protected job summary and a
  step output before the multi-hour poll-only step begins.
- Poll the same submission for up to four hours, bounded by a job-relative
  final-hour post-work reserve and per-command timeouts, while tolerating a
  bounded run of temporary status failures.
- Fail closed unless Apple explicitly reports `Accepted`, retrieve the completed
  notarization log, and retain all staple, Gatekeeper, smoke, upload, and cleanup
  gates.
- Update focused workflow contracts and maintainer-facing release guidance.

### Out of scope

- Changing signing identities, credentials, package contents, or Apple account
  configuration.
- Recovering across separate GitHub workflow runs or publishing an unstapled
  package.
- Starting another protected run, setting up Azure/Windows signing, tagging an
  RC, or claiming clean-machine/cohort evidence.
- UI or Hermes behavior changes.

### Acceptance criteria

| ID | Observable criterion | Evidence | Status |
| --- | --- | --- | --- |
| AC-1 | Exactly one short upload step produces a validated UUID, completes after recording it in the job summary/output, and passes it to a later poll-only step. | Focused workflow contract and executable state tests | Pass |
| AC-2 | The same ID is checked for no more than four hours and bounded transient failures do not resubmit. | Focused workflow contract and shell/YAML validation | Pass |
| AC-3 | Only explicit `Accepted` reaches log retrieval, stapling, Gatekeeper, smoke, and artifact upload; terminal/unknown/unreachable states fail closed. | Named-step ordering and state assertions | Pass |
| AC-4 | Always-run cleanup removes temporary notary files and all existing release topology remains intact. | Cleanup/topology contract and complete suite | Pass |
| AC-5 | Two independent adversarial reviewers report no unresolved in-scope issue. | Four review rounds ending in two clean reports | Pass |

### Constraints and recovery

- Secrets remain protected environment values and are never written to source,
  summaries, documentation, or artifacts.
- The public-safe submission UUID may appear in the protected job summary for
  later status/support use.
- Rollback is a revert of this slice; any Apple request already submitted is
  unaffected.
- Branch: `codex/resumable-apple-notarization` from merged `main`.

### Scope discussion and approval

- Evidence: attempt 1 uploaded successfully but its four-hour combined wait
  ended on a transient `NSURLErrorDomain -1009` connection failure, losing the
  workflow's ability to continue with the known Apple request.
- Recommendation: separate the single upload from status checks using Apple's
  supported submission ID, rather than retrying `submit`.
- Alternatives: retry the combined upload-and-wait command (duplicate risk), or
  leave manual-only recovery (slower and error-prone). Both were rejected.
- Approved under the owner's standing Road-to-Beta authorization.

## Test strategy

| Acceptance criterion | Pre-implementation gap | Planned evidence | Limitations |
| --- | --- | --- | --- |
| AC-1 | Workflow uses `submit --wait`, so the ID is not retained independently. | Require one no-wait JSON submission, UUID validation, and summary record. | A real UUID comes only from protected Apple execution. |
| AC-2 | One failed wait ends the step. | Require a four-hour monotonic deadline, same-ID `info`, bounded failure counter, and no second submit. | Live provider timing is external. |
| AC-3 | Existing success gates are strong but depend on the opaque command exit. | Require explicit status cases and an Accepted assertion before existing ordered gates. | Rejection is source/contract tested, not intentionally submitted. |
| AC-4 | Temporary notary metadata is not yet created. | Require cleanup entries plus existing full release topology tests. | macOS tools are unavailable in the local test environment. |
| AC-5 | No independent review yet. | Two identical read-only reviewer packets after verification. | Reviewers cannot observe Apple's private queue. |

### Baseline results

- The focused packaging contract fails as expected because merged `main` has no
  retained submission JSON, deadline-controlled status loop, or explicit
  Accepted assertion.
- The active protected attempt remains on the prior trusted source revision and
  is not altered by this slice.

## Implementation record

- Replaced `submit --wait` with a short structured JSON submission/UUID step and
  a separate poll-only step that receives the validated ID through a GitHub step
  output.
- Added a testable state machine with a monotonic four-hour phase limit, a
  job-relative final-hour post-work reserve, per-command timeouts, deadline-
  capped two-minute sleeps, and a limit of ten consecutive connection failures.
  Successful status checks reset that failure count; no status path invokes
  `submit` again.
- Added exact handling for `Accepted`, `In Progress`, `Invalid`, `Rejected`, and
  unknown states. A completed submission log is retrieved before stapling.
- Added the three temporary notary JSON files to the final always-run cleanup.
- Updated maintainer guidance, roadmap evidence, and the changelog without
  claiming that the currently active Apple run uses this newer workflow.

## Verification

- Baseline: the new focused contract failed on the missing deadline before the
  production workflow changed.
- Focused Apple state-machine tests: 8 pass.
- Release workflow/rehearsal/promotion checks: 50 pass (58 combined focused
  checks).
- Complete suite after final corrections: 925 run, 921 pass, 4 expected
  platform skips.
- Workflow YAML safe-load, relevant Python compilation, and `git diff --check`:
  pass.
- First hosted secret scan: failed only on the explicit fake notary password in
  the new unit-test environment. The reviewed fixture now carries the scanner's
  standard inline allowlist annotation; all 8 Apple tests and `git diff --check`
  pass after that correction. Local scanner replay is unavailable because the
  optional `detect-secrets` package is not installed; the next hosted run is the
  authoritative scan evidence.
- Live protected attempt 2: still in progress on its prior trusted source
  revision at the time of verification; signing passed and Apple notarization
  remains active.

## Adversarial review

### Round 1

- Correctness reviewer: blocking P2. The inline shell checked its deadline only
  outside an unbounded `notarytool info` call and always slept another 120
  seconds, so the claimed phase bound and cleanup reserve were not enforced.
- Operability reviewer: blocking P1 on the same timing/reserve flaw and blocking
  P2 because an ordinary deadline ended with a bare failed assertion rather
  than an actionable UUID/status diagnostic. The reviewer also identified the
  lack of executable state-machine coverage as a residual gap.
- Reconciliation: accepted all findings. The five-hour inline loop was replaced
  by a unit-tested Python state machine with per-command timeouts and deadline-
  capped sleeps. The job now starts a job-relative five-hour notary deadline
  inside a six-hour hard limit, so its final hour is reserved for post-work and
  cleanup. Deadline errors name the validated submission UUID and last known
  status. Eight mocked provider sequences now exercise the control flow.

### Round 2

- Correctness reviewer: blocking P2. Accepted/rejected log retrieval had a fresh
  three-minute timeout outside the monotonic deadline, so a boundary result
  could erode the post-work reserve.
- Operability reviewer: blocking P2. The UUID was written during the same
  multi-hour step that polled Apple; because GitHub uploads step summaries after
  a step completes, runner loss could still discard the identity this slice was
  meant to preserve.
- Reconciliation: accepted both. Log retrieval is now capped to the remaining
  phase window, including an Accepted-at-deadline test. Submission/UUID
  persistence is now a separately completed step with a validated step output;
  the later wait step contains only the fixed poll invocation. Unknown status
  and ten-consecutive-failure tests were also added.

### Round 3

- Both reviewers found no remaining production correctness, safety, workflow,
  or operability issue. Each independently reported the same non-blocking P3:
  the verification log still contained the pre-round-3 5/55 test totals.
- Reconciliation: corrected the record to 8 state-machine tests and 58 combined
  focused checks. The operator guide also accurately calls GitHub's UUID handoff
  a validated string step output rather than a typed output.

### Round 4

- Correctness reviewer: clean; no P0-P3 findings.
- Operability reviewer: clean; no P0-P3 findings. Its independent focused
  recheck passed 33 tests and `git diff --check`.
- No reviewer dissent remains. Residual risk is limited to real Apple/GitHub
  service behavior and the deliberately fail-closed ambiguous case where the
  initial upload times out before Apple returns a UUID.

## Publication gate

- Proposed files: `.github/workflows/signed-release-artifacts.yml`,
  `scripts/apple_notarization.py`, `tests/test_apple_notarization.py`,
  `tests/test_packaging_cli.py`, `RELEASE_SIGNING.md`, `ROAD_TO_BETA.md`,
  `CHANGELOG.md`, and this review log.
- Branch and base: `codex/resumable-apple-notarization` to `main`.
- Commit/PR title: `Make Apple notarization status resumable`.
- User authorization: covered by the recorded standing Road-to-Beta approval.
- Implementation commit: `39d1474` (`Make Apple notarization status resumable`).
- Ready PR: <https://github.com/hazeion/agent-os/pull/94>.
- Remaining publication requirements: green hosted checks and merge.

## Outcome review

- Classification: Successful.
- Acceptance criteria: AC-1 through AC-5 pass.
- Compatibility: no package, credential, signing-identity, release-tag, or
  artifact-format change.
- Recovery: revert the slice; already-submitted Apple requests remain external
  and unchanged.
- Next gate: the protected live Apple run, then external clean-machine rehearsal.
