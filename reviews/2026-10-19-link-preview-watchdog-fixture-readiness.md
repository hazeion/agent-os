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
receipt after initialization. The test consumes exact bytes/PID from that slot's
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

Source checkpoint only: AST syntax and diff checks passed; no tests or controls
have run. Execution waits for full11706 terminal and independent source review.
This fixture correction does not reclassify the failed historical result or
claim its precise underlying scheduling/startup cause.
