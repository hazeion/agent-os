# Header-only bridge refusal fixture

PR #244 at `c210eb0` fails Windows Python 3.13 group 2 in
`test_planning_integration_routes_are_named_and_exact` for a non-capability
POST route carrying an extra query parameter. The client receives Winsock
10053 instead of the expected 405 method refusal in
[job 109737245601](https://github.com/hazeion/agent-os/actions/runs/36668173201/job/109737245601).

The fixed bridge rejects both non-capability paths before reading a body.
Sending an unread JSON payload while the server closes can reset the socket
and hide its actual response. Those two cases now send the same headers and
declared Content-Length without transmitting refused bytes. A read-bomb around
the exact body reader requires zero body reads; exact 405 and method_not_allowed
payload checks remain. The two body-dependent invalid-JSON-field cases still
transmit their full payloads and require their unchanged exact 404 responses.

The original HTTP deadline, token/Host checks, application bridge, authority,
Calendar/note capabilities and handler behavior are unchanged. Thirty local
old-fixture repetitions passed, so the hosted reset was not reproduced on this
Python 3.11 environment; do not claim otherwise. Validate the complete bridge
suite and repeated corrected real-loopback cases, then obtain two independent
fixture/security reviews before publishing. The next hosted result is pending.

The 30 corrected real-loopback repetitions pass (15.609 seconds). The broader
57-method module attempt reached two unchanged LocalBridgeMainTests failures:
its startup/loaded-runtime fixtures return 2 rather than 0 and never signal
recovery entry in this local environment. Those are outside the changed HTTP
fixture, passed in the cited hosted run, and are not called resolved or altered
by this patch. Verify the complete LocalBridgeTests route/projection class
separately; do not claim all 57 module methods passed.

The complete LocalBridgeTests class passes all 54 route/projection methods
in 29.046 seconds. Both independent read-only reviews are clear; one reviewer
also reran the directly affected real-loopback method successfully.
