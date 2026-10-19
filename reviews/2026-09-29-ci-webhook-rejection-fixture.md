# Bounded webhook rejection fixture

PR #289 at `16f5b4b` failed Windows Python 3.13 group 10 after the server logged
all six exact statuses, including the final 413. Client response receipt raised
Winsock 10053. Thirty local exact loopback repetitions reproduced one reset.

The oversized request length is rejected before any body read. Sending its
entire refused body while the HTTP/1.0 server closes leaves unread bytes and
can reset the socket before the response is observed. Send that one case's
unchanged oversized Content-Length and headers before reading the rejection.
Require actual 413 and a response body at most 512 bytes; never accept a reset,
retry, omit an assertion or increase the three-second network deadline. All
other five cases still send their exact bodies and retain their statuses.

A read-bomb regression verifies the oversized length gate never reads a body
or admits refresh work. Every client connection now closes in finally even
when assertions fail. The server implementation, body ceiling, verifier,
signature, timestamp, connection behavior and mutation authority are unchanged.

The route class already owns a temporary delivery-store root, but three
transaction/snapshot fixtures still took server private-state locks under the
checkout's DATA_DIR. Bind DATA_DIR to that same temporary root for the class,
and restore it with addCleanup after worker teardown. This preserves the real
global database barrier and exact ordering deadlines while removing dependence
on unrelated checkout runtime state. No lock or production behavior is mocked.

Run the complete route suite and repeated real loopback requests, then obtain
two independent fixture/security reviews before committing and updating the
existing full PR. Review frozen dependency security separately before push.
