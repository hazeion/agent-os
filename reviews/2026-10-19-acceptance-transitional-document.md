# Handle a nullable document root without hiding evaluation failures

Base 56b17e48b8b6086d30825b09cb96843b4421c195 and its failed actual report
remain preserved. That report classified a reply as browser_readiness_invalid
after 69 valid blank observations. It did not identify the invalid reply's
cause. Both root and worker independently reproduced the archived expression
throwing TypeError when documentElement was null, without launching a browser.
This establishes a probe robustness bug, not the cause of that actual run.

The DOM standard permits documentElement to be absent. The expression now
captures it once and optional-chains its dataset for the two shell markers.
An absent root produces valid false booleans instead of throwing. All eleven
criteria are unchanged; false markers never grant readiness. There is no broad
exception catch or generic invalid-reply tolerance.
[DOM documentElement contract](https://dom.spec.whatwg.org/#dom-document-documentelement)

Before value-shape validation, any exceptionDetails property forces
no_js_exceptions=false and the fixed browser_evaluation_exception code. Its
payload is never emitted. Missing/nonobject/malformed values without that
property remain browser_readiness_invalid and fail immediately. Existing
Runtime exception events still prevent readiness. No retry, new method, flag,
initial URL, authority, target policy or process-control change is introduced.
The 40-second Python deadline, shared CDP budget, 250 ms evaluation CPU limit
and persistent 15-second cleanup remain unchanged.

Verification: 33 Python methods PASS in 9.303 s, no local POSIX skips,
ResourceWarnings as errors, including 24 Node cases through the existing
15-second wrapper. New cases cover valid nonready absent-root booleans,
absent-root-to-ready polling within the same budget, exceptionDetails with
missing or otherwise-ready values, malformed exception property presence, and
missing/null/malformed values without exception. Every exception/malformed case
fails on its first evaluation, omits private payloads and adds no navigation.
Parent report retention of the new fixed code is also exercised. Compilation,
Node syntax and diff checks passed. Log:
/private/tmp/mentat-acceptance-transient-dom-tests.log.

The identical absent-root regression run against exact old 56b helper bytes
fails with exit 1, while the new expression returns typed false markers.
Source-only counterexample:
/private/tmp/mentat-transient-dom-old56b-counterexample.log.

Before execution, root and an independent peer cleared exact source
`204275ebfee1f4428118e05416d3927ea2f6b09f`; the unchanged tracked-secret gate
passed. Earlier failed pins, reports and their original outcomes remain preserved.

## Actual disposable local result

One separately authorized actual journey passed on 19 October 2026 in 34.710 s
(exit 0), using exact source `204275ebfee1f4428118e05416d3927ea2f6b09f`.
All 1,114 source blobs were checked against Git. The unchanged Next standalone
runtime contained 2,451 files / 24,817,140 bytes, with normalized manifest SHA256
`ffefc85397738902015943646ec78e3daea943b4983e33ab3593de7654412bbe`.
No rebuild or frozen-checkout write was needed.

All four scenarios passed: fresh CLI setup/start and synthetic Project/Task
creation; immediate same-port restart with exact durability readback; isolated
browser rendering; and stopped-server current format-5 backup validated by
read-only restore preview. All eleven browser checks and eight diagnostic
booleans were true. The helper reported `ready` at stage `ready`, with a complete
Tasks document after 22 snapshots (4,892 observer-relative ms). All nine owned
process/group/listener cleanup proofs passed. Inner disposable state was removed
under the existing cleanup rule; outer evidence and every earlier report remain
preserved unchanged. There was no retry or diagnostic port wait.

The bounded report was 1,573 bytes, stderr was empty, and the supervisor verified
all prior report hashes unchanged. Retained local evidence:
`/private/tmp/mentat-actual-direct-204275e-report.json` (SHA256
`747fd1bfc9def1919c99944ebdb79c7dcab1e72377a813afaa645b89d12944ce`) and
`/private/tmp/mentat-actual-direct-204275e-owned.json`. These machine-local files
are not committed.

This qualifies only these four local component scenarios on that exact source
and runtime. It does not qualify a later aggregate head, Linux pidfd behavior,
native artifacts, real Project execution, provider/account authentication,
Google login, remote HTTPS, physical devices or the garage journey. No Run was
dispatched, provider activated or restore confirmed. The passing run does not
establish the cause of the failed 56b run or alter any earlier failure.
