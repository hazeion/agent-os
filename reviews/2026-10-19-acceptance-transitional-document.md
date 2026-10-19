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

No app, Chrome or static server launched from this branch. No prior outcome is
changed and no actual acceptance success is claimed. Independent root and peer
review plus unchanged gates are required before a separately authorized run.
