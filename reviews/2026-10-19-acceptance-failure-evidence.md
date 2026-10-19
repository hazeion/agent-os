# Preserve primary local acceptance failure evidence

The actual frozen13a3e545 local journey failed in the browser phase and reported
cleanup_incomplete. The original runner replaced its primary error with the
cleanup code, and browser output/Popen state was not retained after exit.
The failed owned state is preserved separately; no retry, signal or deletion
has been performed by this investigation.

Read-only profile evidence reports a non-crashed session and a final preference
write38.990seconds after profile lock creation. This is consistent with the
existing40-second wait and later termination, but cannot prove a timeout.
There is no retained Chrome debug/crash log or stderr. The original exact
primary error is unrecoverable and must not be invented. Later observation
found the known harness absent, the configured listener closed, no runtime
server-state file, and the owned browser lock's candidate group absent. That
does not retroactively make the failed cleanup a pass.

The narrow fix must retain fixed primary_phase/primary_code if cleanup fails,
distinguish a bounded operation_timeout without printing its command, and
report fixed boolean cleanup observations for the retained owned handles and
groups. It must not change launch/stop/readiness/browser timeouts, retries,
owned process authority, route allowlists or deletion requirements. Independent
reviews are required before one further actual run is considered.

## Verification checkpoint

The primary error now survives a cleanup failure as primary_phase/primary_code;
TimeoutExpired maps to operation_timeout without retaining its command/output.
Six fixed boolean cleanup fields independently report terminal browser/launcher,
owned browser/launcher-group absence, captured-child absence and closed listener.
All must still pass before owned state can be deleted. No PID, path, output or
exception string is added to those observations. Read-only checks now run even
when an earlier owned cleanup proof failed; no new signal authority is added.

Three regressions exercise browser-timeout masking and command redaction,
complete owned-boundary observation after a surviving browser group, and
cleanup exceptions preserving the primary code without leaking their text.
The existing early-orphan refusal, no-delete, original-handle, listener,
unrelated-exit, pre-stop-crash, route and environment checks remain. All15
methods pass in1.586s with ResourceWarnings as errors. The first new timeout
fixture mocked cleanup without closing its temporary output; that fixture
handle is now closed explicitly, and the final run has no resource warning.
py_compile and git diff --check pass. CLI, request, start, stop, readback and
the full real journey methods are independently AST-identical to frozen13a3.

No actual app or browser has been relaunched. The failed journey, original
report and read-only cleanup evidence remain preserved at their existing paths.
This reporting fix requires two independent reviews before any controlled run.
