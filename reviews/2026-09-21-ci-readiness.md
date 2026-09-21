# CI readiness and synthetic secret correction

PR 243's Node foundation job exited 130 exactly ten seconds into its fixed-time
legacy bootstrap, before preview/lifecycle tests ran. Its redirected bootstrap
log was not emitted, so the interrupted phase is unknown. The new check waits
for actual loopback readiness and initialized SQLite before requesting graceful
shutdown, requires successful process exit and listener withdrawal, and emits
bounded logs on failure. The timeout wrapper remains an absolute 90-second
deadline with forced cleanup; no failed exit is accepted as success.

The synthetic literal in the new webhook timeout regression was flagged by the
tracked-secret scan. Replace it with a per-test random value, rather than add an
exclusion or alter the scanner. Production authentication and timeouts unchanged.

Twenty webhook/preview tests pass, workflow YAML parses, and two independent
reviews found no actionable issues. Reviewers checked the timeout wrapper's
signal forwarding against GNU coreutils source. Linux workflow execution is
still a required gate.

The raw Windows secret scan reports existing baseline entries because detected
filenames use backslashes and the baseline uses slashes. A diagnostic comparison
normalizing only those path separators reports no new candidates. The checked-in
scanner/baseline were not weakened or changed; the Linux CI scan remains required.

Follow-up: the repository's quality-workflow contract test still required the
retired exact ten-second bootstrap string. Updated it to require the reviewed
absolute timeout plus readiness, bounded diagnostics and verified shutdown in
the correct order. This preserves the gate's intent instead of deleting it.
The Node foundation contract contained a second copy of the old literal;
updated that assertion too and ran all 24 Node/CI/preview contract tests. Both
independent reviewers found no actionable concerns in this test-only follow-up.
