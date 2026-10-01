# Deterministic rate-window and discovery-worker fixtures

PR #277 compatibility replay starts at `d33f52d`. The affected auth methods and
discovery fixture code match the reviewed PR #276 fix; preserve this branch's
schema-34 expectation. This record's PR #276 scope is historical source evidence.

Scope: test-only corrections on PR #276. Preserve production authentication,
private locking, discovery order, verifier counts and every test assertion.
No workflow watchdog, adapter capability or runtime behavior changes.

## Diagnosis

- [PR #244 Windows Python 3.11 group 11](https://github.com/hazeion/agent-os/actions/runs/35661485347/job/106537514863)
  failed the recovery-flood assertion: five rejected invalid-code submissions
  made 50 verifier calls, but a sixth made 10 more. The fixture used real time
  while production intentionally starts a new fixed-minute budget at the next
  wall-clock minute. A minute rollover is legitimate admission, not proof of
  an authentication-rate-limit defect.
- [PR #245 Windows Python 3.13 group 0](https://github.com/hazeion/agent-os/actions/runs/35661486856/job/106537520256)
  failed temporary SQLite cleanup in capability discovery with WinError 32.
  The fixture checked the entry event outside its release `finally`, joined
  threads after the ordering assertion, and checked liveness only after
  `TemporaryDirectory` cleanup. An assertion failure could bypass both joins;
  a slow worker could also outlive the short join and still hold SQLite when
  the root was removed. The neighboring capacity-discovery fixture had the
  same ownership error.

Both relevant fixtures remain unchanged at product `0bd6adf` and CI base
`a895e83`, apart from unrelated schema-version assertions. Earlier completion
worker corrections concern a different fixture. Reviewed production dispatch
closes its connections in `finally` and discovers adapter capability/capacity
outside the private-state lock; these tests must continue verifying that.

## Correction and validation

Freeze the existing authority clock seam before bootstrap for the flood test.
Its exact 50-call assertion and refusal of sixth-request verifier work remain.
A separate boundary case proves that 119.999 seconds and 120.0 seconds each
permit exactly five invalid-code submissions, and the sixth is `limited`
without further verification. No production rate-limit logic is changed.

Both discovery fixtures put entry and lock-probe assertions inside the release
`try/finally`. Release and drain every started worker/probe before leaving the
temporary root, including failure before the probe starts. The existing
two-second entry and one-second lock-acquisition assertions are unchanged.
Finishing released workers has the same bounded five-plus-25-second diagnostic
grace used by the existing completion-worker fixture. A worker still alive
fails the test; no cleanup error or failure is ignored.

An injected-failure regression runs each fixture with failure at either ordering
assertion. It observes thread liveness before SQLite-root cleanup, requires all
owned threads stopped, and verifies that the original injected assertion is
the sole failure. The regression itself drains only its captured fixture
workers if the old bug returns, so it does not leak threads while detecting it.

Targeted validation: both recovery cases, both discovery cases, the four
injected failure paths, and all CI contracts pass (16 discovered tests).
Full related modules also pass: 27 owner-auth tests and 107 orchestration tests.
Two independent read-only reviews found no actionable concerns. Each reviewer
independently passed all five directly affected methods, including the four
injected failure paths. The exact verifier counts, ordering assertions and
production behavior remain unchanged.
This is local Windows test evidence, not hosted confirmation that PR #244/#245
failures are resolved. Obtain two independent reviews before commit/push and
propagate only the reviewed test correction into the product stack separately.
