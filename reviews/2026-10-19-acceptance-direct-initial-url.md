# Observe one fixed Chrome startup navigation

Base f5db7ee2927d76c4760ac297dd3a6986395e615a and all failed reports remain
preserved. The final static control completed four setup responses but timed out
with navigation pending and no Tasks request at the owned server. All cleanup
proofs passed. A source audit found no concrete request serialization, pending
registration, response-ID or port mismatch. Installed Chrome metadata was read
without launching it or reading a default profile.

Existing browser_smoke launches at baseUrl before its later CDP navigation;
that differs from the failed blank-to-Tasks contract. The official protocol
allows an omitted top-frame ID, and Chromium can defer its navigation callback
until a navigation lifecycle transition. Neither observation identifies the
installed browser's cause. This change makes no causal or success claim.
[Page protocol](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/pdl/domains/Page.pdl)
[Chromium navigation handler](https://raw.githubusercontent.com/chromium/chromium/main/content/browser/devtools/protocol/page_handler.cc)

Chrome now receives exactly one fixed origin/tasks startup URL. Page.navigate
is removed from both the helper path and method allowlist. Discovery permits
only one exact Tasks page; one initial blank page may transition within the
original budget. Multiple pages (including different URLs), foreign targets,
auth redirects, browser-error targets, nonexact Tasks URLs and foreign debugger
endpoints are refused without connecting or choosing an alternative. Live
redirect/error classifications remain nonready and disclose only fixed enums.
There is no reload, second navigation, retry, scroll or new protocol authority.

Fixed setup now follows initial navigation. All eleven checks remain unchanged,
including actual live document origin/path, exact selected canonical Project,
visible ID/text-bound rows, hydration, bridge and actual viewport. Metadata
alone grants no readiness. The 40-second Python deadline from Chrome spawn, shared
remaining CDP budget, 250 ms evaluation CPU limit, bounded metadata sampling and persistent
15-second owned cleanup are unchanged.

The Runtime handler exists before enable. A targeted mock delivers a retained
startup exception before that enable ACK, then supplies an otherwise-ready
snapshot: no_js_exceptions remains false and readiness fails without disclosing
its payload. Primary V8 source replays retained message storage on enable and
maps retained exceptions to exceptionThrown. Storage can be evicted/cleared or
reset; the claim is limited to retained/replayed and subsequently observed
events, not exhaustive startup-error history or a measurement of the installed
browser's retention behavior.
[V8 enable replay](https://raw.githubusercontent.com/v8/v8/main/src/inspector/v8-runtime-agent-impl.cc)
[V8 stored exception presentation](https://raw.githubusercontent.com/v8/v8/main/src/inspector/v8-console-message.cc)

Verification: 33 Python methods PASS in 7.727 s, no local POSIX skips,
ResourceWarnings as errors, including 21 Node cases through the existing 15-second
wrapper. Coverage includes direct CLI URL, sole blank transition and deadline,
mixed-page ambiguity, auth/error/foreign/nonexact URL and debugger rejection,
live redirects, startup exception replay, unchanged 650 ms Runtime/connect
acknowledgements, transport failure/races and all existing cleanup boundaries.
Three obsolete Page.navigate-only cases were retired: navigation errorText,
preexisting Tasks-target refusal, and delayed Page.navigate acknowledgement.
Timer/late-response cases now exercise the retained fixed Runtime capability.
An initial selector fixture's 30 ms real clock expired during the mock; the
selector-only negative now uses a fixed injected clock. Production deadlines
were not changed. Compilation, Node syntax and diff checks pass. Log:
/private/tmp/mentat-acceptance-direct-url-tests.log.

No app, Chrome or static server launched from this branch. Independent reviews,
unchanged secret gate, exact private source checks and explicit authorization
remain required before any next control or acceptance journey.
