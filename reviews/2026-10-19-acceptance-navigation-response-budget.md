# Bound one navigation acknowledgement by the original browser budget

Base6da73702fafe08acf55b2e90bdf74749f4b7dba3 and its actual failed report
remain preserved. The typed evidence localized that run to
browser_protocol_timeout at navigation before any DOM snapshot; all nine
cleanup proofs passed. This establishes the existing500ms navigation-response
timer expired, not an application rendering or viewport defect.

Only the fixed Page.navigate response wait now uses remaining(). Other call
and connect ceilings remain500ms, evaluation's250ms argument is unchanged,
and the Python parent still enforces its original40seconds from Chrome spawn.
Budget exhaustion is checked before sending navigation (including inside its
call) and after acknowledgement before evaluation. There is still exactly one
fixed navigation, no retry/reload/scroll, and all eleven original checks plus
final typed ready/code/stage/exit/receipt requirements remain. Cleanup retains
its original shared15second window and exact-handle proof. No new production
time threshold is introduced.

Verification:33 Python methods PASS in6.817s, no local POSIX skips,
ResourceWarnings as errors, including fourteen Node cases through the existing
inventory wrapper. A real delayed fake-CDP acknowledgement at650ms reaches all
eleven ready checks within a1500ms remaining test budget; the same650ms ACK
cannot reach evaluation with only550ms left. Late acknowledgement, dropped
acknowledgement and exhausted setup cannot evaluate or send another navigation.
Compilation, Node syntax and diff checks passed. Focused log:
/private/tmp/mentat-acceptance-navigation-budget-tests.log.

The exact old6da helper was read from Git into owned temporary storage and run
against the identical650ms positive regression: it failed expected-ready with
exit1, while the new helper passes. Counterexample log:
/private/tmp/mentat-acceptance-navigation-old6da-counterexample.log.
No old checkout or report was modified. Synthetic timing values occur only in
tests and are not new production budgets.

No actual app/Chrome launch or acceptance success is claimed. Independent root
and peer review, unchanged secret gate and explicit execution authorization are
required before one next actual journey.
