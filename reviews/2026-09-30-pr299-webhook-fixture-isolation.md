# PR 299 webhook fixture root isolation

Exact base: f699b1199ac9ec8eedcda8863ed0d2f62f976611.
Its Windows group9 job109796301869 times out while eight simultaneous HTTP
clients await duplicate-webhook responses. Buffered logs show one202 and seven
204 responses; that alone does not establish the timing cause.

The fixture's delivery store uses an owned TemporaryDirectory while the route's
global DATA_DIR still names a different default root. Carry only the four-line
DATA_DIR setup/restore portion already independently reviewed on PR2895700797.
Both route gate and store now use the same private fixture root, restored before
deleting it; addCleanup remains the setup-failure fallback. No production lock,
route, deduplication, rate limit, body validation or refresh behavior is mocked.
The exact five-second client budgets, eight simultaneous clients, one202/seven204
assertions, singlepending refresh and privacy assertions remain unchanged.

All19 exact webhook methods pass on Windows in9.312 seconds, including the
actual concurrency and lock-order cases. This does not reproduce or prove the
cause of the hosted timeout. ActualLinux qualification and two independent
compatibility reviews remain gates. The separate in-memory signature fix is
not included here. No target branch is published while its frozen60proposal
head remains pending approval.

All19 actual Linux webhook methods also pass7.587 seconds. The Root DATA_DIR
patch is restored before deleting its fixture directory, matching the prior
reviewed correction exactly. Host cause and current-head CI remain unverified.

Both independent compatibility reviews are clear. They verified the exact prior
reviewed setup/teardown hunk, original five-second/eight-client assertions and
unchanged production route/store/locks. This is fixture correctness/isolation
evidence; it does not establish the original hosted timeout's sole cause.
