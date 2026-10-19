# Initialize one owned browser navigation before fixed readiness

Base90f7f9fdac54e5c140a62fb46d4406ef4de24eda and its failed diagnostic
report/state remain preserved. Its last typed snapshot proved none of the
expected page/viewport predicates and no Project/Task node. It did not establish
an offscreen Task or an application rendering defect.

This follow-up uses the existing browser_smoke.mjs setup order: Runtime.enable,
Page.enable, fixed focus emulation and fixed desktop metrics, followed by one
Page.navigate. Chrome starts at about:blank, and discovery accepts only that
owned blank page behind the verified loopback debug listener/process group.
The single navigation URL is constructed internally from the validated origin
plus literal /tasks. There is no caller-selected URL/method/expression, reload,
second navigation, navigation retry, provider or Run authority. A CDP navigation
error returns only browser_navigation_failed, never raw errorText.

All eleven original readiness checks, exact canonical IDs and names, visible
rows, selected Project, viewport, hydration and ready bridge remain required.
The original40second parent deadline remains authoritative. Safe observations
now separate ready-state and fixed location categories and attach snapshot count
and observer-relative elapsed milliseconds. These counter/time fields do not
enter the change fingerprint or consume progress slots on unchanged polls.
The16-record/12KiB progress plus4KiB final reservation and strict parent schema,
duplicate-key, framing, final-only readiness and late-final refusal remain.

Cleanup now observes read-only owned group/listener quiescence after leader wait
within the same persistent15second deadline. Both retained handles are still
signalled at most once, before waits; no group/discovered-PID signal is added.
Listener probes are capped to remaining time and absence is not accepted after
the deadline. The common listener predicate is strengthened to explicit
ECONNREFUSED; open, in-progress and unrelated network failures are unverified.
Prior348/90 false group-absence results remain failures despite later absence.

Verification:29 Python methods PASS in5.154s, no local POSIX skips,
ResourceWarnings as errors, including nine Node cases through the existing
unittest wrapper. Tests assert exact setup ordering and sole navigation target,
preexisting Tasks-target refusal, private navigation-error redaction/no retry,
fixed blank CLI launch, observation enum/count bounds, group settle versus
permanent refusal within an original deadline, no reset/resignal, and bounded
listener probing with uncertain-error refusal. Compilation, Node syntax and
diff checks pass. Log:
/private/tmp/mentat-acceptance-initial-navigation-tests.log.

No actual Chrome/app launch or acceptance success is claimed. Independent root
and peer source review plus explicit execution authorization remain required.
