# Observe browser readiness instead of CLI natural exit

Base: c870c50085190f13d67d52a3d72759d7a174b0f8, isolated feature branch.
The original failed no-instrumentation run emitted no DOM. A separately
instrumented diagnostic emitted actual Project/Task rows and hydration/shell
markers at4.958s but its Chrome process remained alive to40s. These observations
are distinct; they do not prove the original failure's underlying cause.

The source-checkout acceptance runner will keep its original/tasks landing,
exact API creation/readback, immediate restart, offline backup/restore-preview,
40second browser wall deadline and15second cleanup. A fixed Node24 CDP helper
will require actual visible created Project/Task IDs and text, selected Project,
correct Projects & Tasks heading, complete/hydrated shell and ready bridge at a1440x1000 desktop viewport. It
will not accept network idleness, API-only evidence, hidden DOM strings or a
natural Chrome CLI exit as rendering success. No arbitrary evaluation,
navigation, response-body reading, provider, Run or restore-confirm capability
is added. Only exact owned browser/helper handles may be stopped.

The existing runner is source-checkout-only and is not shipped as a wheel or
sdist command; its fixed sibling helper must be present in the same source
archive. Production package resource inventory remains unchanged. Independent
root and peer reviews are required before a final actual four-scenario run.
Implementation is complete; independent final reviews are pending. No browser
is authorized yet.


The original/tasks default was checked against the retained canonical IDs: the
created Project was aria-current and its exact Task li was present. No deep
link is added. The helper fixes the desktop viewport using the existing smoke
Emulation pattern and verifies actual viewport dimensions; exact DOM predicates
bind canonical IDs as data and cannot accept arbitrary expressions or URLs.
Chrome keeps the existing owned private profile and is explicitly stopped after
readiness, not accepted merely because a CLI process exits. Helper output has
an exact bounded boolean schema and the helper exits without waiting for a CDP
close handshake. The shared browser/helper cleanup deadline is retained across
a positive-path stop failure, with one signal attempt per exact owned handle.

Light verification: the existing unittest wrapper executes the Node helper
contract tests in the full Python inventory. Cases cover malformed origins/IDs/
fields/budgets, hidden or wrong-identity/unselected/unhydrated rows, incorrect
viewport or heading, typed evidence closure, CONNECTING timeout/close, successful fixed
protocol and foreign debugger endpoint refusal. Python regressions cover the
fixed source-helper closure, early stdin failure retaining both handles, false
or nonboolean visibility evidence, and the no-reset15second stop deadline.
Final focused verification passed all21 Python methods in1.247s with
ResourceWarnings as errors, including the six Node contract cases. The final
run includes the peer-requested exact heading predicate/negative case and
retained-pipe closure on early helper stdin failure. Python compilation, Node
syntax and git diff checks passed. Evidence:
/private/tmp/mentat-acceptance-cdp-readiness-tests.log. Independent final
reviews remain pending. No heavy build, app or
browser has been launched from this branch.

Root's final review identified an inherited permissive backup-name check. The
runner now requires exact current format5 before calling restore preview. A
Journey.run boundary regression preserves the actual restore-preview call for
v5 and refuses v4 or futurev6 before preview or backup-scenario completion.
The first new mock used an unescaped title and exhausted the existing two-read
HTML branch; its fixture was corrected to the real escaped title. Final focused
verification:22 Python methods PASS in1.732s, ResourceWarnings as errors,
including all six Node cases. Compilation, Node syntax and diff checks pass.
Root and peer independently cleared1f1df4a before this narrow followup; final
followup review remains required. No actual app/browser run has occurred.
