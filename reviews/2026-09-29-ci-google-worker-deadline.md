# Coarse-clock full Google worker budget

PR #265's Windows Python 3.11 job fails the no-network worker test with
`GoogleOidcTransportError: invalid` before a child is created. The same private
production exchange constructs its deadline as `time.monotonic() + 10`.

Reproduced on the exact base `398ad645`: a repeated coarse tick of 246.004 and
its computed deadline 256.004 subtract to 10.000000000000028. The old relative
`remaining <= WORK_SECONDS` check rejects that legitimate full budget. Windows
Python 3.11's coarse monotonic readings make consecutive equal ticks possible;
shrinking only the fixture's budget would hide the production edge case.

Validate the supplied absolute deadline against the freshly computed absolute
`started_at + WORK_SECONDS` bound, still rejecting expired, genuinely excessive
and nonfinite values before child creation. Clamp the later communicate wait
to the unchanged hard ten-second ceiling; do not add tolerance, retry, a larger
watchdog or a new request. Worker credential/environment, capacity, output,
signaling and identity validation remain unchanged.

All 14 Google transport tests pass, including a real owned no-network worker at
the exact coarse-clock boundary, explicit excessive/expired/infinite/NaN refusal
without spawn, and a captured wait that cannot exceed ten seconds. No provider
request, model call, owner configuration or private credentials are accessed.
All 38 related transport/verifier/login tests also pass. Both independent code
reviews are clear; reviewer B independently reran all 14 transport tests.
