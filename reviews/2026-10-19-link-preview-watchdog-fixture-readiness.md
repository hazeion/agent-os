# Separate fixture initialization from timed watchdog operations

Full fc4 reported link_preview.unavailable on the watchdog test's normal request.
Its traceback identifies the watchdog-expiry branch. The normal synthetic worker
emits no phase frames, so that operation exhausted the mocked 0.35-second total
budget. The trace has no iteration/PID/startup timing evidence; it does not prove
which normal request or whether cold startup versus scheduling caused that run.
Original fc4, full-run evidence and its unexecuted actual preparation are preserved.

The production worker/test blobs were unchanged from earlier passing checkpoints.
The pool starts processes/readers without an interpreter-ready receipt. A flushed
stdin request can wait behind initialization. The old test's round-robin normal
requests also exercised only the unaffected slot, not the replacement.

Only this watchdog test now uses a dedicated fake command emitting a fixed ready
binary UTF-8 receipt after initialization, avoiding platform newline translation.
The test consumes exact bytes/PID from that slot's
current queue and verifies retained Popen/queue identity and a live process. Both
initial slots share one setup bound using the existing unmocked 5.25-second
operation constant; each new replacement has that same bounded fixture setup.
This is a test preparation receipt, never a production protocol or result.

The DNS 0.15-second, operation 0.35-second and failed-call <1-second assertions
are unchanged, as are every production/cleanup deadline, existing skip and all
other tests. Each hang now proves the old retained process terminal, replacement
object/PID changed, and unaffected process stable. Both normal calls remain under
the patched 0.35-second watchdog and verify unaffected then replacement PID, so
both slots and both replacement generations are exercised. No retries, operation
budget increases, production changes or generic readiness fallback are added.

Root and independent peer cleared exact source
`35b2c6abd3ff697da63e079f3ecb3ce3ed790385`, including the fixed binary LF
receipt. AST syntax (module and generated child command) and diff checks passed.
After the failed frozen full run became terminal and the machine was quiet, one
worker-module run passed all seven methods in 2.720 s, with no skips and
ResourceWarnings as errors, using a fresh private Hermes root. Exact command/head
and result: `/private/tmp/mentat-link-preview-35b-focused-owned.json`; log:
`/private/tmp/mentat-link-preview-35b-focused.log`.

One separately authorized prospective control used an isolated exact-source Git
archive and real synthetic processes with a 0.5-second initialization delay.
Cold normal execution refused at the total-watchdog branch in 0.3599 s. The
same delayed initialization plus validated fixture receipts let two normal
operations pass in 0.0003/0.0002 s, still under the unchanged 0.35-second
operation watchdog. DNS remained 0.15 s; fixture setup used the existing
5.25-second bound. No retry or deadline increase was used. Every owned worker
was terminal and reader thread joined. Worker environment input was empty and
there was no network/provider operation. This control's parent environment was
inherited, not separately assigned a Hermes home; its synthetic worker API does
not use Hermes storage. Evidence:
`/private/tmp/mentat-link-preview-35b-delayed-control-report.json` and matching
`-owned.json`/`.log` record source, command and result.

The control proves the prospective startup/watchdog seam, not the precise cause
of the historical fc4 timeout. The failed full result and all prior artifacts
remain unchanged; the prepared fc4 actual journey remains unexecuted. This is
fixture-only validation, not a full-suite, packaging or actual Mentat acceptance
pass. No actual app/browser/provider launch is part of this work.
