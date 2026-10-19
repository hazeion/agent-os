# Preserve fixed helper failure codes and stages

Base5cc8095ebf3eca6611cb5ae1088b1dfc5884f8a1 and its actual failed run
remain preserved. That run failed readiness before recording a DOM snapshot;
all nine owned cleanup proofs passed and disposable state was removed. Its
parent report discarded the helper's validated fixed code, leaving the failure
unlocalized. No application, navigation or timeout cause is inferred.

This reporting-only change retains the validated final helper code and adds a
closed stage enum: discovery, connect, runtime, page, focus, viewport,
navigation, evaluation and ready. Stage is emitted before each awaited phase
and retained on failure. Stage changes participate in the existing bounded
progress fingerprint; counters and observer-relative time remain excluded.
The same16-record/12KiB progress cap reserves4KiB for final output within16KiB.
No raw method, exception, URL, ID, DOM, debugger payload or provider value is
added to output. Parent timeouts retain a known typed progress stage without
promoting progress to success.

An internal exception type identifies the existing connect/call timer expiry
as browser_protocol_timeout. Rejected CDP methods and unexpected exceptions
remain browser_protocol_failed; provider/browser error text is never copied.
The original500ms connect/call ceilings,250ms evaluation argument, original
40second parent deadline and shared15second cleanup are unchanged. Fixed single
navigation, exact eleven UI checks and all cleanup authority/proofs are
unchanged. Final success also requires stage=ready with code=ready, all checks,
exit0 and timely parent receipt; a known but inconsistent stage cannot pass.

Verification:33 Python methods PASS in5.633s, no local POSIX skips,
ResourceWarnings as errors, including eleven Node cases through the existing
inventory wrapper. Tests exercise actual parent main/report preservation for
nonready navigation/protocol/timeout codes and stages, malformed/unknown stage
refusal, known inconsistent stage and ready/code contradictions, progress-only
failure and late final refusal. Node tests distinguish the unchanged navigation
call timer from protocol rejection at the same stage, retain pre-await stage
progress, classify connect timeout and verify private errors are omitted.
Compilation, Node syntax and diff checks pass. Log:
/private/tmp/mentat-acceptance-cdp-stage-tests.log.

No actual Chrome/app launch, timer change, acceptance retry or new success is
claimed. Independent root/peer review and the unchanged secret gate are required
before any explicitly authorized next journey.
