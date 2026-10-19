# Deterministic rate-window and discovery-worker fixtures

Scope: reviewed test corrections originally on PR #276, with compatible fixture
and dev-transitive security backports on PR #244. Preserve authentication,
private locking, discovery order, verifier counts and every test assertion.
No workflow watchdog, adapter capability or runtime behavior changes.

Compatibility backport for PR #244 (base `7c06ed47`): copy only this reviewed
test correction and add the two diagnostic standard-library imports absent
from the older fixture. Its schema version, production modules and workflow
remain unchanged. PR #245 receives the same compatible correction through its
existing stacked parent, with its own exact-head verification.
Fresh audit of the older PR #244 lock reproduces the known Undici 8.10.0 high
severity failure, so the same three-field reviewed 8.10.2 correction is also
backported before publishing; no other dependency or package constraints change.
The same fresh audit also reports the newly reviewed brace-expansion recursion
advisories [GHSA-qhr7-859c-m2p7](https://github.com/advisories/GHSA-qhr7-859c-m2p7)
and [GHSA-6j4f-fj2g-mc7p](https://github.com/advisories/GHSA-6j4f-fj2g-mc7p).
Update only its two existing dev-transitive lock entries from 1.1.18 to 1.1.21
and 5.0.9 to 5.0.12, using their registry tarball identities/integrities; their
parent minimatch ranges and Node requirements remain satisfied. The existing
dependency graph, production package constraints and audit threshold remain.
PR #244 compatibility checks: five directly affected unittest methods and seven
existing CI contracts pass (12 methods; the injected-failure method contains
four control-flow subcases). Frozen install, explicit audit and dependency-tree
validation pass with zero vulnerabilities. PR #244/#245's pre-backport Python
authentication/orchestration files are byte-identical.
PR #244 web lint, typecheck and all 377 web tests also pass against the patched
frozen dependency tree.

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

Original PR #276 validation: both recovery cases, both discovery cases, the four
injected failure paths, and all CI contracts pass (16 discovered tests).
Full related modules also pass: 27 owner-auth tests and 107 orchestration tests.
Two independent read-only reviews found no actionable concerns. Each reviewer
independently passed all five directly affected methods, including the four
injected failure paths. The exact verifier counts, ordering assertions and
production behavior remain unchanged.
This is local Windows test evidence, not hosted confirmation that PR #244/#245
failures are resolved. Obtain two independent reviews before commit/push and
propagate only the reviewed test correction into the product stack separately.
