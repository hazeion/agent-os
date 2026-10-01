# Runs smoke follows canonical readback

PR 244's package browser smoke closed the timeline as soon as an event row
appeared. The new lifecycle hint had disabled Stop pending canonical readback;
closing cancelled that readback and exposed explicit Refresh status recovery.
The smoke then clicked a disabled Stop and timed out. The application correctly
kept uncertain controls closed; its checks are not relaxed for this test.

The smoke now waits for canonical enabled controls after timeline hints. It
also deliberately closes during pending readback, verifies disabled Stop and
the recovery action, then exercises Refresh status before continuing existing
Stop/message conflict and confirmation checks. Multi-runtime fixture navigation
waits for the corresponding exact card's canonical readback as well.

Syntax checking and all seven timeline browser regression tests passed. Two
independent reviewers found no actionable concerns, including the mock's
snapshot-before-close microtask ordering. The real packaged Linux smoke remains
the CI acceptance gate; production behavior is unchanged.
