# Share the original CDP budget and retain passive transport evidence

Base589f0435b88d69e44f52147d27a90bfb1069c1fa and all prior failed runs
remain preserved. The independently reviewed static control failed with
browser_protocol_timeout at runtime, before any Tasks HTTP request. Its server
thread/process/listener and all nine browser/helper cleanup proofs passed.
That evidence demonstrates an internal setup timer failure independent of
Mentat; it does not prove an application rendering defect.

Fixed CDP connection/setup/response waits now use the same remaining helper
budget instead of fresh500ms response ceilings. The authoritative Python
40second Chrome-spawn deadline and timely final receipt are unchanged. Metadata
sampling still uses min(500,remaining), and Runtime.evaluate retains its250ms
CPU argument. One fixed navigation, eleven UI criteria, exact ready/code/stage/
exit requirements and shared15second cleanup are unchanged. Exhausted budget
rejects before send or accepting a late response. No reconnect, resend or
second navigation is introduced.

Passive transport metadata contains sent requests, text frames, invalid frames,
matched responses, pending count, unexpected-close/error booleans, numeric
close code and a saturation flag. Counters cap at4096, pending at1 and close
code at65535. No raw frame, response ID, URL, close reason or error payload is
retained. Counters/time stay out of the progress fingerprint; fixed stage and
unexpected socket-state changes can emit within the existing16-record/12KiB
progress and4KiB reserved final envelope. The parent independently validates
all types/ranges and exact keys. Metadata cannot grant readiness.

Unexpected close/error clears pending timers and rejects the active connection
or response wait with a fixed transport code and retained stage. Transport
failure between an evaluation reply and its continuation cannot promote a ready
snapshot. Normal owned transport close is excluded from unexpected-failure
metadata. All process-control and cleanup code remains unchanged.

Verification:33 Python methods PASS in8.465s, no local POSIX skips,
ResourceWarnings as errors, including eighteen Node cases through the existing
unittest wrapper. Cases cover650ms Runtime/setup and connection acknowledgements
within the existing shared budget, late/dropped replies, exhausted setup,
close/error before connection or while waiting, an evaluation-response race,
invalid/saturated frame counters, fixed-code parent report retention, malformed
transport schemas and no success from passive diagnostics. The bounded-progress
fixture still exceeds the16-record ceiling while advancing its synthetic clock
in fewer real polling intervals; no production or test deadline changed.
Compilation, Node syntax and diff checks pass. Log:
/private/tmp/mentat-acceptance-shared-cdp-budget-tests.log.

The identical650ms Runtime acknowledgement regression against exact old589
helper bytes fails expected readiness with exit1; the new helper reaches all
eleven checks within1500ms. Counterexample:
/private/tmp/mentat-shared-cdp-old589-counterexample.log.

No Chrome/app/static server launch or new acceptance success is claimed.
Independent root/peer review and unchanged secret gate are required before any
separately authorized next static control.

Root's follow-up review identified a timeout evidence gap: a pending call could
receive an invalid/unmatched text frame without emitting progress before the
parent deadline. The progress fingerprint now includes only monotone presence
transitions for text, invalid and matched frames and counter saturation.
Frame classifications and matches publish those transitions, including early
returns and unmatched frames. Changing numeric counts do not create records or
a heartbeat; unchanged fingerprints skip record serialization. Caps, wait
budgets, predicates and cleanup are unchanged.52fc2ea remains preserved.

A new pending Runtime fixture sends three private unmatched text or invalid
frames without a response: exactly one presence record retains the first frame,
sent1/pending1/matched0, while final counters reach3 and readiness still times
out without navigation/evaluation or payload disclosure. Stage-order assertions
now account for legitimate presence records at the same fixed stage.

The Node-only timing audit passed all19 cases in5.328s under the existing15s
wrapper. Timeout-only synthetic negative budgets were then shortened from550ms
to30ms with a fixed injected clock; the real650ms positive acknowledgements and
old-source counterexamples remain unchanged. No production/test deadline was
increased. Final verification:33 Python methods PASS in7.833s, no local POSIX
skips, ResourceWarnings as errors, including19 Node cases. Compilation, Node
syntax and diff checks passed. No Chrome or server launch occurred.
